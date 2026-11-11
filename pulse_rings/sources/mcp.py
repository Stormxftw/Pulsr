"""Approved read-only MCP counts. No direct transport, prompt, or raw persistence."""
import copy
import json
from pathlib import Path
import queue
import threading

from .base import Deferred, SourceError, SourceResult
from .http_json import json_pointer, _number
from .. import mcp_access
from ..net import strict_json

TIMEOUT = 8
OUTPUT_LIMIT = 256 * 1024  # Secondary decoded-body cap; host caps envelopes at ~64K chars.
_SLOTS = threading.BoundedSemaphore(4)
_LOCK = threading.Lock()
_INFLIGHT = set()


def _params(definition):
    from ..kinds import KINDS
    from ..spec import _shape
    params = definition['source']['params']
    if _shape(params, KINDS['mcp.tool']['params_schema']):
        raise SourceError('Invalid approved MCP parameters.')
    return params


class NeedsMcpGrant(Deferred):
    """Operator consent is missing, not a remote failure or exponential backoff."""
    def __init__(self, server):
        super().__init__(mcp_access.grant_message(server), retry_after=60)


class TruncatedResult(SourceError):
    def __init__(self):
        super().__init__('MCP result truncated by Hermes; metrics unknown.')


def _decode(outer):
    """call_mcp envelope -> structuredContent, else JSON-decoded result body.

    Presence, not truthiness, selects structuredContent (including null). Never
    inspect partial output, including a valid-looking structured prefix.
    """
    if not isinstance(outer, dict):
        raise SourceError('MCP result was not a supported JSON envelope.')
    if outer.get('truncated'):
        raise TruncatedResult()
    if outer.get('ok') is not True or 'error' in outer or outer.get('isError') is True:
        raise SourceError('MCP call failed or requires interactive attention.', retry_after=3600)
    if 'structuredContent' in outer:
        body = outer['structuredContent']
    elif 'result' in outer:
        raw = outer['result']
        if isinstance(raw, str) and (len(raw) > OUTPUT_LIMIT or len(raw.encode('utf-8')) > OUTPUT_LIMIT):
            raise SourceError('MCP result exceeded the size limit.')
        body = strict_json(raw) if isinstance(raw, str) else raw
    else:
        raise SourceError('MCP result was not a supported JSON envelope.')
    # Bound structured results too; no output is stored by this decoder.
    if len(json.dumps(body, ensure_ascii=False).encode('utf-8')) > OUTPUT_LIMIT:
        raise SourceError('MCP result exceeded the size limit.')
    if isinstance(body, dict) and ('error' in body or body.get('isError') is True):
        raise SourceError('MCP call failed or requires interactive attention.', retry_after=3600)
    return body

def disclosure(definition, root):
    """Ephemeral engine enrichment. Never persisted with samples/state/metadata.

    Args are escaped JSON from the approved definition only, not tool output.
    A badge is based on fresh host policy, never x-* fields or definition claims.
    """
    params = definition['source']['params']  # Already normalized at admission; no hot-path validation.
    binding = mcp_access.binding_for(root)
    okay, reason = False, 'MCP connector unavailable here; load the agent plugin in this process.'
    allowed = False
    if binding:
        ctx, context, scope = binding
        okay, reason = context.copy().run(mcp_access.tool_policy, ctx, params['server'], params['tool'], scope)
        allowed = context.copy().run(mcp_access.server_granted, params['server'])
    args = json.dumps(params.get('args', {}), ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    return {'server': params['server'], 'tool': params['tool'], 'read_only': okay,
            'hermes_allowed': allowed, 'grant_message': mcp_access.grant_message(params['server'], allowed),
            'args_display': args[:512] + ('… [truncated; review full definition]' if len(args) > 512 else ''),
            'reason': reason, 'transport': 'via Hermes MCP connector (Hermes handles sign-in)'}


class McpToolSource:
    # Deliberately stricter than fixed-host previews: MCP can read private data,
    # incur costs or invoke server-side elicitation. No pre-approval dispatch,
    # even for interactive proposals. The agent can call its own tool normally.
    pre_approval_sample = False

    def __init__(self, root):
        self.root = Path(root).resolve()

    def poll(self, definition, previous, state, *, now, net):
        try:
            params = _params(definition)
            binding = mcp_access.binding_for(self.root)
            if binding is None:
                raise SourceError('MCP connector unavailable here; load the agent plugin in this process.')
            result = queue.Queue(maxsize=1)
            cancelled = threading.Event()
            ctx, context, scope = binding
            if not context.copy().run(mcp_access.server_granted, params['server']):
                raise NeedsMcpGrant(params['server'])
            worker_context = context.copy()
            key = (str(self.root), params['server'], params['tool'])
            with _LOCK:
                if key in _INFLIGHT:
                    raise Deferred('MCP call still in flight; waiting before retry.', retry_after=300)
                if not _SLOTS.acquire(blocking=False):
                    raise Deferred('MCP connector is busy; waiting before retry.', retry_after=300)
                _INFLIGHT.add(key)

            def collect():
                if not mcp_access.server_granted(params['server']):
                    raise NeedsMcpGrant(params['server'])
                okay, reason = mcp_access.tool_policy(ctx, params['server'], params['tool'], scope)
                if not okay:
                    raise SourceError(reason)
                if cancelled.is_set() or net.cancelled():
                    return None
                # Reservation only: all transport/auth remains in Hermes.
                net.reserve('mcp:' + params['server'])
                if cancelled.is_set() or net.cancelled():
                    return None
                try:
                    raw = ctx.call_mcp(params['server'], params['tool'],
                                       copy.deepcopy(params.get('args', {})), timeout=TIMEOUT)
                except PermissionError:
                    raise NeedsMcpGrant(params['server']) from None
                except Exception:
                    # Even a SourceError from a foreign handler is untrusted.
                    raise SourceError('MCP call failed. Cached values are preserved.') from None
                if cancelled.is_set() or net.cancelled():
                    return None  # Late output is neither decoded nor published/persisted.
                try:
                    body = _decode(raw)
                    metrics = {name: _number(json_pointer(body, pointer)) for name, pointer in params['metrics'].items()}
                except TruncatedResult as exc:
                    return SourceResult(sample={'ts': now, 'metrics': {name: None for name in params['metrics']},
                        'baselines': {}, 'unknown_reasons': {name: str(exc) for name in params['metrics']}})
                except SourceError:
                    raise
                except Exception:
                    raise SourceError('MCP result unavailable or invalid JSON. Cached values are preserved.') from None
                sample = {'ts': now, 'metrics': metrics, 'baselines': {}, 'unknown_reasons': {
                    name: 'MCP metric missing or not a finite number.' for name, value in metrics.items() if value is None}}
                return SourceResult(sample=sample)

            def run():
                try:
                    with mcp_access.unattended_scope():
                        item = collect()
                except SourceError as exc:
                    item = exc  # Includes Deferred: local pacing is not a remote failure.
                except Exception:
                    item = SourceError('MCP unattended safety unavailable; source disabled.')
                finally:
                    # One owner, including context-entry AND context-exit failure.
                    with _LOCK:
                        _INFLIGHT.discard(key)
                    _SLOTS.release()
                if not cancelled.is_set() and item is not None:
                    result.put_nowait(item)
            try:
                worker = threading.Thread(target=lambda: worker_context.run(run), name='pulse-mcp-call', daemon=True)
                worker.start()
            except Exception:
                with _LOCK:
                    _INFLIGHT.discard(key)
                _SLOTS.release()
                raise SourceError('MCP worker unavailable.') from None
            try:
                item = result.get(timeout=TIMEOUT)
            except queue.Empty:
                cancelled.set()
                raise SourceError('MCP call timed out. Cached values are preserved.', retry_after=900) from None
            if isinstance(item, SourceError):
                raise item
            return item
        except SourceError:
            raise
        except Exception:
            raise SourceError('MCP source unavailable. Cached values are preserved.') from None
