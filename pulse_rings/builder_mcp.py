"""Explicit human one-shot MCP inspection. No durable state or source activation.

Shares the poller's profile binding, public read-only policy, worker
semaphore/in-flight exclusion, public call_mcp and JSON decoder. No direct MCP
transport and no retries; results live only in the HTTP response.
"""
import copy
import json
from pathlib import Path
import queue
import re
import threading
import time

from . import mcp_access
from .sources import mcp
from .spec import normalize
from .builder import numeric_leaves

_NAME = re.compile(r'^(?!.*__)[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')
_RECENT = {}
_RATE_LOCK = threading.Lock()
LIMIT = 65536


class TestCallError(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def tool_inventory(root):
    binding = mcp_access.binding_for(root)
    if binding is None:
        return {'tools': [], 'reason': 'MCP connector unavailable here; load the agent plugin in this process.'}
    ctx, context, scope = binding
    if not mcp_access.available(ctx):
        return {'tools': [], 'reason': mcp_access.UNAVAILABLE}

    def read():
        public = getattr(ctx, 'list_tools', None)
        if callable(public):
            names = public()
        else:
            from tools.registry import registry
            names = registry.get_all_tool_names()
        rows = []
        for name in sorted(set(names)):
            if not isinstance(name, str):
                continue
            parts = name.split('__')
            if len(parts) != 3 or parts[0] != 'mcp' or not all(_NAME.fullmatch(x) for x in parts[1:]):
                continue
            server, tool = parts[1:]
            okay, reason = mcp_access.tool_policy(ctx, server, tool, scope)
            # Discovered existence/policy only; never discovers or reconnects.
            if reason == 'MCP server not connected.':
                continue
            allowed = mcp_access.server_granted(server)
            rows.append({'server': server, 'tool': tool, 'read_only': okay, 'reason': reason,
                         'hermes_allowed': allowed, 'grant_message': mcp_access.grant_message(server, allowed)})
        return {'tools': rows, 'reason': None}
    try:
        return context.copy().run(read)
    except Exception:
        return {'tools': [], 'reason': 'MCP policy unavailable; source disabled.'}


def test_call(root, server, tool, args, *, clock=time.monotonic):
    # The exact source schema/args guard, not a relaxed testing-only grammar.
    normalize({'pulse': 1, 'title': 'Test call', 'source': {'kind': 'mcp.tool', 'params': {
        'server': server, 'tool': tool, 'args': args, 'metrics': {'test': ''}}}})
    binding = mcp_access.binding_for(root)
    if binding is None:
        raise TestCallError(503, 'MCP connector unavailable here; load the agent plugin in this process.')
    ctx, context, scope = binding
    if not context.copy().run(mcp_access.server_granted, server):
        raise TestCallError(403, mcp_access.grant_message(server))
    okay, reason = context.copy().run(mcp_access.tool_policy, ctx, server, tool, scope)
    if not okay:
        raise TestCallError(403, reason)
    key = (str(Path(root).resolve()), server, tool)
    now = clock()
    with _RATE_LOCK:
        for old in [k for k, ts in _RECENT.items() if now - ts >= 10]:
            _RECENT.pop(old, None)
        if key in _RECENT:
            raise TestCallError(429, 'One test per 10 seconds per tool; wait before trying again.')
        if len(_RECENT) >= 4096:
            raise TestCallError(429, 'Test call limit reached; wait before trying again.')
        _RECENT[key] = now
    with mcp._LOCK:
        if key in mcp._INFLIGHT:
            raise TestCallError(429, 'MCP call still in flight; wait before trying again.')
        if not mcp._SLOTS.acquire(blocking=False):
            raise TestCallError(429, 'MCP connector is busy; wait before trying again.')
        mcp._INFLIGHT.add(key)
    result = queue.Queue(maxsize=1)
    cancelled = threading.Event()

    def run():
        try:
            okay, reason = mcp_access.tool_policy(ctx, server, tool, scope)
            if not okay:
                raise TestCallError(403, reason)
            if cancelled.is_set():
                return
            # EXACTLY ONE public call. Host auth/trust/grant remains authoritative.
            raw = ctx.call_mcp(server, tool, copy.deepcopy(args), timeout=mcp.TIMEOUT)
            if cancelled.is_set():
                return
            body = mcp._decode(raw)
            text = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            encoded = text.encode('utf-8')
            truncated = len(encoded) > LIMIT
            item = {'body': None if truncated else body,
                    'text': encoded[:LIMIT].decode('utf-8', errors='ignore'), 'truncated': truncated,
                    'numeric': [] if truncated else numeric_leaves(body), 'calls': 1, 'persisted': False}
        except PermissionError:
            item = TestCallError(403, mcp_access.grant_message(server))
        except mcp.TruncatedResult as exc:
            item = {'body': None, 'text': str(exc), 'truncated': True,
                    'numeric': [], 'calls': 1, 'persisted': False}
        except TestCallError as exc:
            item = exc
        except Exception:
            item = TestCallError(502, 'MCP test failed or requires interactive attention; no result retained.')
        finally:
            with mcp._LOCK:
                mcp._INFLIGHT.discard(key)
            mcp._SLOTS.release()
        if not cancelled.is_set():
            result.put_nowait(item)
    try:
        worker_context = context.copy()
        threading.Thread(target=lambda: worker_context.run(run), name='pulse-builder-test', daemon=True).start()
    except Exception:
        with mcp._LOCK:
            mcp._INFLIGHT.discard(key)
        mcp._SLOTS.release()
        raise TestCallError(503, 'MCP worker unavailable.') from None
    try:
        item = result.get(timeout=mcp.TIMEOUT)
    except queue.Empty:
        cancelled.set()
        raise TestCallError(504, 'MCP test timed out; late results discarded. Do not retry until the call finishes.') from None
    if isinstance(item, TestCallError):
        raise item
    return item
