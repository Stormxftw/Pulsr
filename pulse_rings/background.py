"""Opt-in, profile-root-scoped collection; no host scheduler or model turns.

PluginContext.spawn_task needs a running asyncio loop, which synchronous plugin
registration/dashboard dependencies do not guarantee. Use our own daemon, public
on_unload cleanup, and atexit. No private host service, cron or child processes.
"""
import atexit
from contextlib import closing, contextmanager
from contextvars import copy_context
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

TICK_SECONDS = 5
LEASE_SECONDS = 30
JOIN_SECONDS = 1.5
_LOCK = threading.RLock()
_WORKERS = {}
_BINDINGS = {}
_TICK_LOCKS = {}
logger = logging.getLogger(__name__)


def key_for(root):
    return os.path.normcase(str(Path(root).resolve()))


def binding_for(root):
    with _LOCK:
        return _BINDINGS.get(key_for(root))


def _home_for_root(root):
    """Public plugin storage layout pins the owner, never the current viewer."""
    root = Path(root).resolve()
    if root.name == 'pulse-rings' and root.parent.name == 'plugin-data':
        return root.parent.parent
    return None


@contextmanager
def _secret_scope(home):
    """Refresh the owner's secrets per tick; old Hermes keeps its existing path."""
    if home is None:
        yield
        return
    try:
        from agent.secret_scope import build_profile_secret_scope, set_secret_scope, reset_secret_scope
    except ImportError:
        yield
        return
    token = set_secret_scope(build_profile_secret_scope(home), profile_home=home)
    try:
        yield
    finally:
        reset_secret_scope(token)


def bind_context(ctx, *, root=None, start=True):
    """Capture the registering profile, not a later request thread's profile."""
    if root is None:
        from plugins.plugin_storage import plugin_data_dir
        root = plugin_data_dir('pulse-rings')
    key = key_for(root)
    home = _home_for_root(root)
    if home is None:
        # Explicit/custom storage roots still belong to the registering profile.
        from hermes_constants import get_hermes_home
        home = Path(get_hermes_home()).resolve()
    binding = (ctx, copy_context(), home)
    with _LOCK:
        _BINDINGS[key] = binding
    unload = getattr(ctx, 'on_unload', None)
    if callable(unload):
        def cleanup():
            if binding_for(root) is binding:
                shutdown(root)
                unbind_context(root)
        unload(cleanup)
    # Only construct storage/start a collector when the operator has opted in.
    if start and read_setting(root):
        from .engine import Engine
        ensure(Engine(root))


def unbind_context(root):
    with _LOCK:
        _BINDINGS.pop(key_for(root), None)


def read_setting(root, *, managed=False):
    binding = binding_for(root)
    try:
        if binding:
            ctx, context, _ = binding
            return context.copy().run(ctx.get_config, 'background_collection', False) is True
        if managed:
            # Documented dashboard reader, not a private config-file parser.
            from hermes_cli.config import load_config_readonly
            settings = (load_config_readonly() or {}).get('plugins', {}).get('entries', {}).get('pulse-rings', {}).get('settings', {})
            return settings.get('background_collection') is True
    except Exception:
        pass  # Unknown config is OFF, never an implicit opt-in.
    return False


def enabled(engine):
    reader = getattr(engine, '_collection_enabled', None)
    return reader() is True if reader else read_setting(engine.root, managed=engine.store.managed)


def settings(engine):
    return {'background_collection': enabled(engine),
            'writable': binding_for(engine.root) is not None}


def set_setting(engine, value):
    if type(value) is not bool:
        raise ValueError('background_collection must be a boolean')
    binding = binding_for(engine.root)
    if binding is None:
        raise RuntimeError('Settings writer unavailable: load the enabled agent plugin in this Hermes process, or use Settings > Plugins.')
    ctx, context, _ = binding
    context.copy().run(ctx.set_config, 'background_collection', value)
    if context.copy().run(ctx.get_config, 'background_collection', False) is not value:
        raise RuntimeError('Settings readback did not match; refresh before retrying.')
    if value:
        ensure(engine)
    else:
        shutdown(engine.root)
    return settings(engine)


def info(engine, *, db=None, now=None):
    now = engine.clock() if now is None else now
    with engine.store.read(db) as connection:
        row = connection.execute('SELECT * FROM collection_lease WHERE singleton=1').fetchone()
    return {'mode': 'background' if enabled(engine) else 'viewed',
            'lease_holder_alive': bool(row and row['owner'] and row['expires_ts'] > now),
            'last_tick_ts': row['last_tick_ts'] if row else None}


@contextmanager
def exclusive(root):
    """Nonblocking process + OS mutex, also fences a stalled/expired lease holder.

    The SQLite lease provides ownership, cadence and read-only status. An OS
    byte/file lock additionally prevents overlap if an in-flight network call
    outlives the lease. Crash/exit releases it without a private host lock API.
    Never hold a SQLite write transaction across network I/O.
    """
    key = key_for(root)
    with _LOCK:
        lock = _TICK_LOCKS.setdefault(key, threading.Lock())
    if not lock.acquire(blocking=False):
        yield False
        return
    stream, acquired = None, False
    try:
        stream = open(Path(root) / 'collection.lock', 'a+b')
        if os.name == 'nt':
            import msvcrt
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError:
                pass
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                pass
        yield acquired
    finally:
        if stream:
            if acquired:
                if os.name == 'nt':
                    import msvcrt
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()
        lock.release()


class Collector:
    def __init__(self, engine, *, enabled=None):
        self.engine = engine
        self.enabled = enabled or (lambda: read_setting(engine.root, managed=engine.store.managed))
        if enabled is not None:
            engine._collection_enabled = self.enabled
        self.owner = uuid.uuid4().hex
        self.stop_event = threading.Event()
        engine.net.cancelled = self.stop_event.is_set
        self.thread = None
        self.retry_at = 0
        self.failures = 0
        binding = binding_for(engine.root)
        self.context = binding[1].copy() if binding else copy_context()
        self.profile_home = binding[2] if binding else _home_for_root(engine.root)

    def tick(self):
        engine, now = self.engine, self.engine.clock()
        if self.stop_event.is_set() or now < self.retry_at or self.enabled() is not True:
            return False
        try:
            with exclusive(engine.root) as acquired:
                if not acquired:
                    return False
                # Short busy timeout: a contended writer must not freeze a worker
                # or shutdown. Backoff applies before the next attempted claim.
                with closing(engine.store.db(timeout=.05)) as db, db:
                    db.execute('BEGIN IMMEDIATE')
                    row = db.execute('SELECT * FROM collection_lease WHERE singleton=1').fetchone()
                    if row and ((row['owner'] != self.owner and row['expires_ts'] > now) or row['next_tick_ts'] > now):
                        return False
                    db.execute('''INSERT INTO collection_lease VALUES (1,?,?,?,?)
                        ON CONFLICT(singleton) DO UPDATE SET owner=excluded.owner,
                        expires_ts=excluded.expires_ts,last_tick_ts=excluded.last_tick_ts,
                        next_tick_ts=excluded.next_tick_ts''', (self.owner, now + LEASE_SECONDS, now, now + TICK_SECONDS))
                    active = db.execute('SELECT 1 FROM pulses WHERE paused=0 LIMIT 1').fetchone() is not None
                self.failures = 0
                if not active or self.stop_event.is_set() or self.enabled() is not True:
                    return False
                # Same claims/budgets/backoff/MCP gate, but never draft previews.
                with _secret_scope(self.profile_home):
                    return engine.poll_one_due(previews=False)
        except sqlite3.OperationalError:
            self.failures += 1
            self.retry_at = now + min(60, TICK_SECONDS * 2 ** min(self.failures - 1, 4))
            return False

    def _run(self):
        try:
            while not self.stop_event.is_set():
                if self.enabled() is not True:
                    break
                try:
                    self.tick()
                except Exception as exc:
                    # Never leak source text/args, and never busy-spin on errors.
                    logger.warning('Background collection tick failed: %s', type(exc).__name__)
                if self.stop_event.wait(TICK_SECONDS):
                    break
        finally:
            self.release()

    def start(self):
        if self.thread is None and not self.stop_event.is_set():
            self.thread = threading.Thread(target=lambda: self.context.run(self._run), name='pulse-rings-collection', daemon=True)
            self.thread.start()
        return self

    def release(self):
        try:
            with closing(self.engine.store.db(timeout=.05)) as db, db:
                db.execute('UPDATE collection_lease SET owner=\'\',expires_ts=0,next_tick_ts=0 WHERE singleton=1 AND owner=?', (self.owner,))
        except (sqlite3.Error, OSError):
            pass  # Expiring lease and OS lock remain crash-safe.

    def stop(self, timeout=JOIN_SECONDS):
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout)
        stopped = self.thread is None or not self.thread.is_alive()
        if stopped and self.thread is None:
            self.release()  # Threaded workers release in _run's finally block.
        return stopped


def viewed_poll(engine):
    # A viewer can still advance eligible previews. They never run on the
    # collector, and use at most the existing single-operation viewed allowance.
    if not enabled(engine):
        with exclusive(engine.root) as acquired:
            return engine.poll_one_due() if acquired else False
    from .previews import tick
    if tick(engine):
        return True
    if info(engine)['lease_holder_alive']:
        return False
    reader = getattr(engine, '_collection_enabled', None)
    return Collector(engine, enabled=reader or (lambda: read_setting(engine.root, managed=engine.store.managed))).tick()


def ensure(engine):
    if not enabled(engine):
        return None
    key = key_for(engine.root)
    with _LOCK:
        worker = _WORKERS.get(key)
        if worker and worker.thread and worker.thread.is_alive():
            if not worker.stop_event.is_set():
                return worker
            # A rapid OFF→ON may leave the old operation draining. Its cancelled
            # Net must never be reused by the replacement; the OS fence still
            # prevents simultaneous polls while the stopped daemon drains.
            if engine is worker.engine:
                from .engine import Engine
                engine = Engine(engine.root, fetch=engine.fetch, clock=engine.clock,
                    jitter=engine.jitter, icon_fetch=engine.icon_fetch,
                    adapters=engine.adapters, ceiling=engine.net.ceiling)
        worker = Collector(engine)
        _WORKERS[key] = worker
        return worker.start()


def shutdown(root=None):
    with _LOCK:
        workers = list(_WORKERS.values()) if root is None else [_WORKERS.get(key_for(root))]
    workers = [worker for worker in workers if worker is not None]
    deadline = time.monotonic() + JOIN_SECONDS
    for worker in workers:
        worker.stop_event.set()
    results = [worker.stop(max(0, deadline - time.monotonic())) for worker in workers]
    return all(results)


atexit.register(shutdown)
