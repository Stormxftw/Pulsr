"""Session pulses: bounded process memory, public observer hooks, no payloads/I/O.

Raw session ids exist only for public SDK title matching and chat focus. Titles
are resolved in Desktop, never recorded here. Consent is rechecked on every hook
and read; OFF clears memory. Restart loses observations (intentionally).
"""
from collections import OrderedDict
from contextvars import copy_context
import hashlib
import hmac
import secrets
import threading
import time

from . import background

HOOKS = ('on_session_start', 'on_session_end', 'on_session_finalize',
         'pre_llm_call', 'post_llm_call', 'post_tool_call',
         'subagent_start', 'subagent_stop')
DONE_LINGER = 15 * 60
IDLE_AFTER = 2 * 3600
MAX_SESSIONS = 128
MAX_CHILDREN = 256
_TRACKERS = {}
_LOCK = threading.Lock()


def valid_id(value):
    return isinstance(value, str) and 0 < len(value) <= 4096


class SessionTracker:
    def __init__(self, *, clock=time.time):
        self.clock = clock
        self.enabled = False
        self.rows = OrderedDict()
        self.children = OrderedDict()
        self.salt = secrets.token_bytes(32)
        self.lock = threading.RLock()
        self.revision = 0
        self.binding_token: object | None = None

    def clear(self):
        with self.lock:
            self.rows.clear()
            self.children.clear()

    def _prune(self, now):
        for sid, row in list(self.rows.items()):
            if row['finished_ts'] is not None and now - row['finished_ts'] >= DONE_LINGER:
                del self.rows[sid]
            elif row['state'] == 'Working' and now - row['last_activity_ts'] >= IDLE_AFTER:
                row['state'] = 'Idle'
        for child, (parent, ts) in list(self.children.items()):
            if now - ts >= IDLE_AFTER or parent not in self.rows:
                del self.children[child]

    def observe(self, hook, **kwargs):
        # Never inspect messages, tool name, args, result, goals or summaries.
        with self.lock:
            if not self.enabled:
                self.clear()
                return None
            now = self.clock()
            self._prune(now)
            sid = kwargs.get('session_id')
            if hook in ('subagent_start', 'subagent_stop'):
                sid, child = kwargs.get('parent_session_id'), kwargs.get('child_session_id')
                if not valid_id(sid) or not valid_id(child) or child == sid:
                    return None
                parent = self.children.get(sid, (sid, now))[0]
                if hook == 'subagent_start':
                    self.children[child] = (parent, now)
                    self.rows.pop(child, None)
                    while len(self.children) > MAX_CHILDREN:
                        self.children.popitem(last=False)
                # Keep child->parent until TTL, to catch late tool/end observers.
                sid = parent
            if not valid_id(sid) or hook not in HOOKS:
                return None
            is_child = sid in self.children
            if is_child:
                parent = self.children[sid][0]
                # Renew active mappings; a long-running child must not become a
                # separate session merely because its original start is old.
                self.children[sid] = (parent, now)
                self.children.move_to_end(sid)
                sid = parent
                if hook in ('on_session_end', 'on_session_finalize', 'on_session_start'):
                    return None
            row = self.rows.get(sid)
            if row is None:
                if hook in ('on_session_end', 'on_session_finalize') and is_child:
                    return None
                digest = hmac.new(self.salt, sid.encode(), hashlib.sha256).hexdigest()
                row = {'id': 'session:' + digest, 'session_id': sid,
                       'state': 'Idle', 'tool_calls_turn': 0, 'tool_calls_total': 0,
                       'last_activity_ts': now, 'finished_ts': None, 'turn_id': None}
                self.rows[sid] = row
            turn = kwargs.get('turn_id')
            if (hook in ('on_session_end', 'on_session_finalize') and valid_id(turn)
                    and row['turn_id'] not in (None, turn)):
                return None  # A delayed completion must not finish a newer turn.
            if hook in ('pre_llm_call', 'on_session_start', 'post_tool_call', 'subagent_start'):
                if not is_child and hook != 'subagent_start' and (row['state'] != 'Working' or
                                     (valid_id(turn) and row['turn_id'] not in (None, turn))):
                    row['tool_calls_turn'] = 0
                if not is_child and valid_id(turn):
                    row['turn_id'] = turn
                row['state'], row['finished_ts'] = 'Working', None
            if hook == 'post_tool_call':
                row['tool_calls_turn'] += 1
                row['tool_calls_total'] += 1
            if hook in ('on_session_end', 'on_session_finalize'):
                if row['finished_ts'] is None:
                    row['finished_ts'] = now
                row['state'] = 'Done'
            row['last_activity_ts'] = now
            self.rows.move_to_end(sid)
            while len(self.rows) > MAX_SESSIONS:
                self.rows.popitem(last=False)
            self.revision += 1
        return None

    def snapshot(self):
        with self.lock:
            if not self.enabled:
                self.clear()
                return []
            self._prune(self.clock())
            return [{k: v for k, v in row.items() if k != 'turn_id'}
                    for row in reversed(self.rows.values())]


def for_root(root):
    key = background.key_for(root)
    with _LOCK:
        if key not in _TRACKERS:
            _TRACKERS[key] = SessionTracker()
        return _TRACKERS[key]


def enabled(engine):
    binding = background.binding_for(engine.root)
    try:
        if binding:
            ctx, context, _ = binding
            return context.copy().run(ctx.get_config, 'show_sessions', False) is True
        if engine.store.managed:
            from hermes_cli.config import load_config_readonly
            settings = (load_config_readonly() or {}).get('plugins', {}).get('entries', {}).get('pulse-rings', {}).get('settings', {})
            return settings.get('show_sessions') is True
    except Exception:
        pass
    return False


def status(engine):
    tracker = for_root(engine.root)
    with tracker.lock:
        tracker.enabled = enabled(engine)
        return {'show_sessions': tracker.enabled, 'sessions': tracker.snapshot(),
                'group': {'id': 'hermes-sessions', 'title': 'Hermes sessions'} if tracker.enabled else None}


def set_setting(engine, value):
    if type(value) is not bool:
        raise ValueError('show_sessions must be a boolean')
    binding = background.binding_for(engine.root)
    if not binding:
        raise RuntimeError('Settings writer unavailable: load the enabled agent plugin in this Hermes process.')
    ctx, context, _ = binding
    tracker = for_root(engine.root)
    with tracker.lock:
        context.copy().run(ctx.set_config, 'show_sessions', value)
        if context.copy().run(ctx.get_config, 'show_sessions', False) is not value:
            raise RuntimeError('Settings readback did not match; refresh before retrying.')
        tracker.enabled = value
        if not value:
            tracker.clear()


def bind_context(ctx, *, root=None):
    if root is None:
        try:
            from plugins.plugin_storage import plugin_data_dir
            root = plugin_data_dir('pulse-rings')
        except Exception:
            pass  # Capability probes/older hosts may lack storage; still register.
    tracker = for_root(root) if root is not None else SessionTracker()
    token = object()
    tracker.binding_token = token
    context = copy_context()
    def observe(name, **kwargs):
        changed = False
        with tracker.lock:
            if tracker.binding_token is not token:
                return None
            try:
                tracker.enabled = context.copy().run(ctx.get_config, 'show_sessions', False) is True
                revision = tracker.revision
                tracker.observe(name, **kwargs)
                changed = tracker.revision != revision
            except Exception:
                tracker.enabled = False
                tracker.clear()
        if changed:
            from .events import emit
            emit('sessions.updated', {})  # local invalidation only; no ids/payloads
        return None
    for name in HOOKS:
        try:
            def observer(_name=name, **kwargs):
                return observe(_name, **kwargs)
            ctx.register_hook(name, observer)
        except Exception:
            continue  # Older hosts may lack some hooks; the others remain useful.
    if callable(getattr(ctx, 'on_unload', None)):
        def cleanup():
            with tracker.lock:
                if tracker.binding_token is not token:
                    return
                tracker.enabled = False
                tracker.clear()
                if root is not None:
                    with _LOCK:
                        if _TRACKERS.get(background.key_for(root)) is tracker:
                            _TRACKERS.pop(background.key_for(root), None)
        ctx.on_unload(cleanup)
    return tracker
