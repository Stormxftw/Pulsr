"""Official observer callbacks; persist counts, enum labels and salted ids only.

One connection per process/profile, acquired during registration (never per hook).
No prompts, command text, tool names/args/results, goals, summaries or provider
payloads are inspected. All callbacks return None, including on storage failures.
"""
from collections import deque
import hashlib
import hmac
import math
import os
import secrets
import sqlite3
import threading
import time

from .store import Store

HOOKS = ('pre_llm_call', 'on_session_end', 'post_tool_call',
         'on_human_input_request', 'on_human_input_resolved',
         'subagent_start', 'subagent_stop', 'api_request_error')
RETENTION = 48 * 3600
TURN_TTL = SUBAGENT_TTL = 2 * 3600
WAIT_TTL = 30 * 60
_WAIT_KINDS = frozenset(('approval', 'clarify', 'sudo'))
_STATUSES = frozenset(('ok', 'error', 'blocked', 'cancelled', 'timeout'))
_POOL = {}
_POOL_LOCK = threading.Lock()


class HookRecorder:
    def __init__(self, store, *, clock=time.time, cron_provider=None):
        self.clock = clock
        self.cron_provider = cron_provider
        self.lock = threading.Lock()
        self.pending_lock = threading.Lock()
        self.pending_closes = deque(maxlen=4096)
        self.waiting_closed = False
        self.pid = os.getpid()
        self.closed = False
        self.dropped = 0
        if store.managed:
            # Public plugin_db sets check_same_thread=False and the host WAL policy.
            self.db = store.db(timeout=0.001)
        else:
            self.db = sqlite3.connect(store.root / 'pulse.sqlite3', timeout=0.001, check_same_thread=False)
            self.db.execute('PRAGMA busy_timeout=1')
        self.db.isolation_level = None
        # Telemetry is best effort: WAL NORMAL avoids an fsync per tool event.
        # Set once, never change Hermes's journal/fallback policy. A power loss
        # may lose recent counters, not approvals or definitions (other handles).
        self.db.execute('PRAGMA synchronous=NORMAL')
        now = self.clock()
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('hermes_hash_salt',?)", (secrets.token_hex(32),))
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('hermes_observed_since',?)", (str(now),))
        self.salt = bytes.fromhex(self.db.execute("SELECT value FROM meta WHERE key='hermes_hash_salt'").fetchone()[0])
        self.next_cleanup = now
        self.callbacks = {name: self._callback(name) for name in HOOKS}

    def _callback(self, name):
        def observer(**kwargs):
            self.record(name, **kwargs)
            return None
        observer.__name__ = name
        return observer

    def _hash(self, namespace, value):
        # Refuse missing/non-string ids instead of merging unknown sessions/prompts.
        if not isinstance(value, str) or not value or len(value) > 4096:
            return None
        return hmac.new(self.salt, (namespace + '\0' + value).encode('utf-8'), hashlib.sha256).hexdigest()

    def _origin(self, kwargs):
        try:
            if self.cron_provider is not None and self.cron_provider() is not None:
                return 'cron'
        except Exception:
            pass
        if kwargs.get('parent_session_id') or kwargs.get('parent_subagent_id'):
            return 'subagent'
        return 'interactive'

    def _close_target(self, hook, kwargs):
        if hook == 'on_session_end':
            return 'turn', self._hash('session', kwargs.get('session_id'))
        if hook == 'subagent_stop':
            return 'subagent', self._hash('child', kwargs.get('child_session_id'))
        if hook == 'on_human_input_resolved' and kwargs.get('kind') in _WAIT_KINDS:
            return 'waiting:' + kwargs['kind'], self._hash('request', kwargs.get('request_id'))
        return None

    def _queue_close(self, target):
        if target and target[1]:
            with self.pending_lock:
                self.pending_closes.append(target)

    def _flush_locked(self):
        with self.pending_lock:
            while self.pending_closes:
                self._close(*self.pending_closes[0])
                self.pending_closes.popleft()

    def flush_pending(self):
        if self.closed or self.pid != os.getpid() or not self.lock.acquire(timeout=0.25):
            return
        try:
            self.db.execute('PRAGMA busy_timeout=250')
            self._flush_locked()
        except Exception:
            pass  # Keep the unflushed tail for a later callback or poll.
        finally:
            try:
                self.db.execute('PRAGMA busy_timeout=1')
            except Exception:
                pass
            waiting_changed = self.waiting_closed
            self.waiting_closed = False
            self.lock.release()
            if waiting_changed:
                from .events import emit
                emit('hermes.waiting', {})

    def record(self, hook, **kwargs):
        acquired = False
        target = None
        close_done = False
        waiting_changed = False
        try:
            # Do not inherit a connection across fork, block on another callback,
            # or pay stat/path-resolution/plugin_db/PRAGMA costs in a callback.
            if self.closed or os.getpid() != self.pid:
                return None
            target = self._close_target(hook, kwargs)
            acquired = self.lock.acquire(timeout=0.25) if target else self.lock.acquire(blocking=False)
            if not acquired:
                self._queue_close(target)
                self.dropped += 1
                return None
            if target:
                self.db.execute('PRAGMA busy_timeout=250')
            self._flush_locked()
            now = self.clock()
            if not isinstance(now, (int, float)) or not math.isfinite(now):
                return None
            origin = self._origin(kwargs)
            if target:
                if target[1]:
                    self._close(*target)
                close_done = True
                waiting_changed = bool(target[1] and target[0].startswith('waiting:'))
            elif hook in ('pre_llm_call', 'on_session_end'):
                key = self._hash('session', kwargs.get('session_id'))
                if key:
                    if hook == 'pre_llm_call':
                        self._open('turn', key, now, TURN_TTL, origin)
                    else:
                        self._close('turn', key)
            elif hook in ('on_human_input_request', 'on_human_input_resolved'):
                kind = kwargs.get('kind')
                if isinstance(kind, str) and kind in _WAIT_KINDS:
                    key = self._hash('request', kwargs.get('request_id'))
                    if key:
                        if hook == 'on_human_input_request':
                            self._open('waiting:' + kind, key, now, WAIT_TTL, origin)
                            waiting_changed = True
                        else:
                            self._close('waiting:' + kind, key)
            elif hook in ('subagent_start', 'subagent_stop'):
                # child_session_id is present in BOTH official emitters. The
                # child_subagent_id is absent on stop, so cannot pair reliably.
                key = self._hash('child', kwargs.get('child_session_id'))
                if key:
                    if hook == 'subagent_start':
                        self._open('subagent', key, now, SUBAGENT_TTL, origin)
                    else:
                        self._close('subagent', key)
            elif hook == 'post_tool_call':
                status = kwargs.get('status')
                status = status if isinstance(status, str) and status in _STATUSES else 'unknown'
                self.db.execute('INSERT INTO hermes_events(ts,kind,status,origin) VALUES (?,?,?,?)',
                                (now, 'tool', status, origin))
            elif hook == 'api_request_error':
                self.db.execute('INSERT INTO hermes_events(ts,kind,status,origin) VALUES (?,?,?,?)',
                                (now, 'provider_error', 'error', origin))
            if now >= self.next_cleanup:
                self.db.execute('DELETE FROM hermes_events WHERE ts<=?', (now - RETENTION,))
                self.db.execute('DELETE FROM hermes_open WHERE expires_ts<=?', (now,))
                self.next_cleanup = now + 60
        except Exception:
            # Do not log kwargs or exception text (they may contain credentials).
            self.dropped += 1
            if not close_done:
                self._queue_close(target)
        finally:
            if acquired:
                try:
                    if target:
                        self.db.execute('PRAGMA busy_timeout=1')
                except Exception:
                    pass
                waiting_changed = waiting_changed or self.waiting_closed
                self.waiting_closed = False
                self.lock.release()
            if waiting_changed:
                from .events import emit
                emit('hermes.waiting', {})
        return None

    def _open(self, kind, key, now, ttl, origin):
        self.db.execute('INSERT OR REPLACE INTO hermes_open(kind,key,ts,expires_ts,origin) VALUES (?,?,?,?,?)',
                        (kind, key, now, now + ttl, origin))

    def _close(self, kind, key):
        self.db.execute('DELETE FROM hermes_open WHERE kind=? AND key=?', (kind, key))
        if kind.startswith('waiting:'):
            self.waiting_closed = True

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                self.db.close()


def flush_pending(store):
    key = (os.getpid(), str(store.root.absolute()))
    with _POOL_LOCK:
        recorder = _POOL.get(key)
    if recorder is not None:
        recorder.flush_pending()


def register_hooks(ctx, *, store=None, clock=time.time, context_observer=None):
    """Call once from register(ctx). Optional args isolate tests from user data.

    No prompt, network, approval mutation or background task. Failure to initialize
    telemetry never prevents plugin/tools registration. The source remains unknown
    until a recorder has successfully initialized its observation marker.
    """
    try:
        store = store if store is not None else Store()
        key = (os.getpid(), str(store.root.absolute()))
        with _POOL_LOCK:
            recorder = _POOL.get(key)
            if recorder is None or recorder.closed:
                recorder = HookRecorder(store, clock=clock, cron_provider=getattr(ctx, 'current_cron_execution', None))
                _POOL[key] = recorder
        for name, callback in recorder.callbacks.items():
            if context_observer is not None:
                def observed(_name=name, _callback=callback, **kwargs):
                    try:
                        context_observer(_name, **kwargs)
                    except Exception:
                        pass
                    return _callback(**kwargs)
                ctx.register_hook(name, observed)
            else:
                ctx.register_hook(name, callback)
        if hasattr(ctx, 'on_unload'):
            ctx.on_unload(recorder.close)
        return recorder
    except Exception:
        # Registration is declarative even when telemetry storage is unavailable
        # (including the bare-interpreter capability probe). Keep origin safety
        # observation alive, but never let a failed recorder break a turn.
        if hasattr(ctx, 'register_hook'):
            for name in HOOKS:
                def observer(_name=name, **kwargs):
                    if context_observer is not None:
                        try:
                            context_observer(_name, **kwargs)
                        except Exception:
                            pass
                    return None
                observer.__name__ = name
                ctx.register_hook(name, observer)
        return None
