"""Opt-in collection uses the ordinary engine, never preview work or model turns."""
import importlib.util
from contextlib import closing
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pulse_rings.engine import Engine
from pulse_rings.spec import normalize

ROOT = Path(__file__).resolve().parents[1]


def test_default_off_status_is_cached_and_has_collection(tmp_path):
    engine = Engine(tmp_path)
    assert engine.status()['collection'] == {
        'mode': 'viewed', 'lease_holder_alive': False, 'last_tick_ts': None}


def fixture_engine(tmp_path, *, ceiling=300):
    from pulse_rings.sources.base import SourceResult
    now, calls = [10000.0], []
    class Source:
        def poll(self, definition, previous, state, *, now, net):
            net.call('discord.com', lambda: calls.append(now))
            return SourceResult(sample={'ts': now, 'metrics': {'online': len(calls), 'members': 100}}, next_due=now + 10)
    engine = Engine(tmp_path, clock=lambda: now[0], jitter=lambda: 0,
                    adapters={'discord.invite@1': Source()}, ceiling=ceiling)
    engine.activate(normalize((ROOT / 'examples/a-discord.pulse.yaml').read_text(encoding='utf-8')))
    return engine, now, calls


def worker_for(engine, enabled=True):
    from pulse_rings.background import Collector
    return Collector(engine, enabled=lambda: enabled)


def test_off_no_work_and_on_collects_without_viewer(tmp_path):
    engine, now, calls = fixture_engine(tmp_path)
    assert worker_for(engine, False).tick() is False
    assert calls == []
    worker = worker_for(engine)
    assert worker.tick() is True
    now[0] += 10
    assert worker.tick() is True
    assert calls == [10000, 10010]
    status = engine.status()
    assert len(engine.store.history(status['pulses'][0]['id'])) == 2
    assert status['pulses'][0]['ring']['baseline_samples'] == 1
    assert status['collection'] == {'mode': 'background', 'lease_holder_alive': True, 'last_tick_ts': 10010}
    worker.stop()


def test_lease_two_engines_and_viewer_do_not_double_schedule(tmp_path):
    engine, now, calls = fixture_engine(tmp_path)
    other = Engine(tmp_path, clock=lambda: now[0], adapters=engine.adapters)
    one, two = worker_for(engine), worker_for(other)
    assert one.tick()
    assert not two.tick()
    # Another due feed must not run from viewed status while a holder is alive.
    with engine.store.transaction() as db:
        db.execute('UPDATE pulses SET next_due=0')
    engine.status(poll=True)
    assert calls == [10000]
    now[0] += 5
    assert not two.tick()
    assert one.tick()
    assert calls == [10000, 10005]
    one.stop()
    now[0] += 10
    assert two.tick()
    two.stop()


def test_background_never_ticks_previews_or_polls_with_zero_active(tmp_path, monkeypatch):
    from pulse_rings import previews
    engine = Engine(tmp_path)
    worker = worker_for(engine)
    monkeypatch.setattr(previews, 'tick', lambda *a, **k: pytest.fail('background preview'))
    monkeypatch.setattr(engine, 'poll_one_due', lambda **k: pytest.fail('empty background poll'))
    assert not worker.tick()
    worker.stop()


def test_ceiling_uses_existing_gate(tmp_path):
    engine, now, calls = fixture_engine(tmp_path)
    # Lower runtime ceiling only after approval to exercise collection's gate.
    engine.net.ceiling = 1
    worker = worker_for(engine)
    assert worker.tick()
    now[0] += 10
    worker.tick()
    assert calls == [10000]
    assert engine.net.usage()['used'] == 1
    worker.stop()


def test_locked_db_backs_off_without_poll_and_stop_is_bounded(tmp_path):
    engine, now, calls = fixture_engine(tmp_path)
    worker = worker_for(engine)
    with closing(engine.db()) as db:
        db.execute('BEGIN IMMEDIATE')
        start = time.monotonic()
        assert not worker.tick()
        assert time.monotonic() - start < 1
        assert worker.retry_at > now[0]
        assert calls == []
        db.rollback()
    assert not worker.tick()  # no busy spin after contention clears
    now[0] = worker.retry_at
    assert worker.tick()
    worker.start()
    start = time.monotonic()
    assert worker.stop()
    assert time.monotonic() - start < 2
    assert not worker.thread.is_alive()


def test_slow_poll_cannot_overlap_after_lease_expiry(tmp_path, monkeypatch):
    engine, now, calls = fixture_engine(tmp_path)
    other = Engine(tmp_path, clock=lambda: now[0], adapters=engine.adapters)
    one, two = worker_for(engine), worker_for(other)
    entered, release = threading.Event(), threading.Event()
    def slow(**kwargs):
        entered.set()
        release.wait(3)
        return True
    monkeypatch.setattr(engine, 'poll_one_due', slow)
    thread = threading.Thread(target=one.tick)
    thread.start()
    try:
        assert entered.wait(1)
        now[0] += 1000
        assert not two.tick()
    finally:
        release.set()
        thread.join(1)
        one.stop()
        two.stop()
    assert not thread.is_alive()


def test_toggle_route_strict_confirmation_and_persistence(tmp_path, monkeypatch):
    from pulse_rings import background
    engine = Engine(tmp_path)
    values = {}
    class Context:
        def get_config(self, key, default=None):
            return values.get(key, default)
        def set_config(self, key, value):
            values[key] = value
    background.bind_context(Context(), root=tmp_path, start=False)
    spec = importlib.util.spec_from_file_location('background_test_api', ROOT / 'dashboard/plugin_api.py')
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_pulse] = lambda: engine
    try:
        with TestClient(app) as client:
            assert client.get('/settings').json()['background_collection'] is False
            for body, code in [({}, 422), ({'background_collection': True}, 422),
                               ({'background_collection': True, 'confirm': 'true'}, 422),
                               ({'background_collection': 1, 'confirm': True}, 422),
                               ({'background_collection': True, 'confirm': False}, 400)]:
                assert client.put('/settings', json=body).status_code == code
            assert values == {}
            assert client.put('/settings', json={'background_collection': True, 'confirm': True}).status_code == 200
            assert values == {'background_collection': True}
            assert client.get('/settings').json()['background_collection'] is True
            assert client.get('/status?poll=false').json()['collection']['mode'] == 'background'
            assert client.put('/settings', json={'background_collection': False, 'confirm': True}).status_code == 200
            assert client.get('/settings').json()['background_collection'] is False
    finally:
        background.shutdown(tmp_path)
        background.unbind_context(tmp_path)


def test_default_off_does_not_create_a_worker(tmp_path, monkeypatch):
    from pulse_rings import background
    engine = Engine(tmp_path)
    monkeypatch.setattr(background, 'Collector', lambda *a, **k: pytest.fail('implicit worker'))
    assert background.ensure(engine) is None
    assert engine.status(compact=True)['collection']['mode'] == 'viewed'


def test_real_loop_collects_over_simulated_time_without_status_requests(tmp_path, monkeypatch):
    from pulse_rings import background
    engine, now, calls = fixture_engine(tmp_path)
    monkeypatch.setattr(background, 'TICK_SECONDS', .01)
    worker = worker_for(engine)
    worker.start()
    try:
        deadline = time.monotonic() + 2
        while len(calls) < 1 and time.monotonic() < deadline:
            time.sleep(.01)
        assert calls == [10000]
        now[0] += 10
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(.01)
        assert calls == [10000, 10010]
    finally:
        assert worker.stop()


def test_active_collector_never_calls_draft_preview_tick(tmp_path, monkeypatch):
    from pulse_rings import previews
    engine, now, calls = fixture_engine(tmp_path)
    monkeypatch.setattr(previews, 'tick', lambda *a, **k: pytest.fail('background draft preview'))
    worker = worker_for(engine)
    assert worker.tick()
    worker.stop()


def test_stale_lease_viewer_fallback_and_new_holder(tmp_path):
    engine, now, calls = fixture_engine(tmp_path)
    worker = worker_for(engine)
    assert worker.tick()
    now[0] += 31
    engine.status(poll=True)
    assert calls == [10000, 10031]
    assert not worker.tick()  # fallback owns the lease, not a parallel poll
    worker.stop()


def test_paused_set_never_calls_sources(tmp_path):
    engine, now, calls = fixture_engine(tmp_path)
    engine.store.pause(engine.store.rows()[0]['id'], True, now[0])
    worker = worker_for(engine)
    assert not worker.tick()
    assert calls == []
    worker.stop()


def test_concurrent_instances_admit_only_one_tick(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    engine, now, calls = fixture_engine(tmp_path)
    other = Engine(tmp_path, clock=lambda: now[0], adapters=engine.adapters)
    workers = [worker_for(engine), worker_for(other)]
    try:
        with ThreadPoolExecutor(2) as pool:
            assert sorted(pool.map(lambda w: w.tick(), workers)) == [False, True]
        assert calls == [10000]
    finally:
        for worker in workers:
            worker.stop()


def test_stop_during_inflight_call_is_bounded_and_late_sample_is_discarded(tmp_path):
    from pulse_rings.sources.base import SourceResult, Deferred
    engine, now, calls = fixture_engine(tmp_path)
    entered, release = threading.Event(), threading.Event()
    class Slow:
        def poll(self, definition, previous, state, *, now, net):
            entered.set()
            release.wait(4)
            with pytest.raises(Deferred, match='stopped'):
                net.call('discord.com', lambda: pytest.fail('post-stop request'))
            return SourceResult(sample={'ts': now, 'metrics': {'online': 999}})
    engine.adapters['discord.invite@1'] = Slow()
    worker = worker_for(engine)
    worker.start()
    try:
        assert entered.wait(5)  # tolerate a loaded CI box; the stop bound below is the contract
        start = time.monotonic()
        assert worker.stop() is False  # honestly reports the draining call
        assert time.monotonic() - start < 2
    finally:
        release.set()
        worker.thread.join(3)
    assert not worker.thread.is_alive()
    assert engine.store.history(engine.store.rows()[0]['id']) == []


def test_context_capture_unload_and_singleton(tmp_path):
    from contextvars import ContextVar
    from pulse_rings import background
    profile = ContextVar('background-test-profile', default='other')
    profile.set('registered')
    cleanups = []
    values = {'background_collection': True}
    class Context:
        def get_config(self, key, default=None):
            assert profile.get() == 'registered'
            return values.get(key, default)
        def on_unload(self, callback):
            cleanups.append(callback)
    background.bind_context(Context(), root=tmp_path)
    try:
        profile.set('request-profile')
        assert background.read_setting(tmp_path)
        engine = Engine(tmp_path)
        first = background.ensure(engine)
        assert background.ensure(Engine(tmp_path)) is first
        start = time.monotonic()
        cleanups[0]()
        assert time.monotonic() - start < 2
        assert not first.thread.is_alive()
        assert background.binding_for(tmp_path) is None
    finally:
        background.shutdown(tmp_path)
        background.unbind_context(tmp_path)


def test_settings_without_context_fail_closed(tmp_path):
    from pulse_rings import background
    engine = Engine(tmp_path)
    assert background.settings(engine) == {'background_collection': False, 'writable': False}
    with pytest.raises(RuntimeError, match='Settings writer unavailable'):
        background.set_setting(engine, True)


def _process_lock_probe(root, output):
    from pulse_rings.background import exclusive
    with exclusive(root) as acquired:
        output.put(acquired)


def test_os_fence_is_cross_process_even_without_a_fresh_lease(tmp_path):
    import multiprocessing
    from pulse_rings.background import exclusive
    context = multiprocessing.get_context('spawn')
    output = context.Queue()
    def probe():
        child = context.Process(target=_process_lock_probe, args=(str(tmp_path), output))
        child.start()
        try:
            result = output.get(timeout=30)
            child.join(30)
            assert child.exitcode == 0
            return result
        finally:
            if child.is_alive():
                child.terminate()
                child.join(2)
    try:
        with exclusive(tmp_path) as acquired:
            assert acquired
            assert probe() is False
        assert probe() is True
    finally:
        output.close()
        output.join_thread()


@pytest.mark.parametrize('read_only,requires_approval', [(False, False), (True, True)])
def test_background_mcp_uses_same_refusal_gate(tmp_path, monkeypatch, read_only, requires_approval):
    from contextvars import copy_context
    from pulse_rings import mcp_access
    calls = []
    ctx = SimpleNamespace(
        tool_info=lambda name: {'exists': True, 'connected': True,
            'read_only': read_only, 'requires_approval': requires_approval},
        call_mcp=lambda *args, **kw: calls.append(args))
    monkeypatch.setitem(mcp_access._BINDINGS, str(tmp_path.resolve()), (ctx, copy_context(), str(tmp_path)))
    monkeypatch.setattr(mcp_access, 'server_granted', lambda server: True)
    engine = Engine(tmp_path, clock=lambda: 10000)
    engine.activate(normalize({'pulse': 1, 'title': 'MCP', 'source': {'kind': 'mcp.tool',
        'params': {'server': 'probe', 'tool': 'read_counts', 'args': {}, 'metrics': {'count': '/count'}}}}))
    worker = worker_for(engine)
    try:
        assert not worker.tick()
        assert calls == []
        assert engine.net.usage()['used'] == 0
        assert engine.store.rows()[0]['error']
    finally:
        worker.stop()


def test_rapid_reenable_replaces_cancelled_worker_without_overlap(tmp_path, monkeypatch):
    from pulse_rings import background
    engine, now, calls = fixture_engine(tmp_path)
    entered, release = threading.Event(), threading.Event()
    values = {'background_collection': True}
    ctx = SimpleNamespace(get_config=lambda key, default=None: values.get(key, default))
    background.bind_context(ctx, root=tmp_path, start=False)
    original = engine.poll_one_due
    def slow(**kwargs):
        entered.set()
        release.wait(5)
        return original(**kwargs)
    monkeypatch.setattr(engine, 'poll_one_due', slow)
    first = background.ensure(engine)
    second = None
    try:
        assert entered.wait(1)
        assert not first.stop(timeout=.01)
        second = background.ensure(engine)
        assert second is not first and second.engine is not first.engine
        assert first.engine.net.cancelled()
        assert not second.engine.net.cancelled()
        assert calls == []  # old operation still holds the OS fence
    finally:
        values['background_collection'] = False
        release.set()
        first.thread.join(2)
        background.shutdown(tmp_path)
        background.unbind_context(tmp_path)
    assert not first.thread.is_alive()
    assert not second.thread.is_alive()
    assert calls == []
