"""Ephemeral opt-in session observations: no transcripts, disk or network."""
import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pulse_rings.engine import Engine

ROOT = Path(__file__).resolve().parents[1]


def tracker(clock):
    from pulse_rings.sessions import SessionTracker
    return SessionTracker(clock=lambda: clock[0])


def test_sequence_and_done_linger():
    now = [1000.0]
    t = tracker(now)
    t.observe('pre_llm_call', session_id='one', turn_id='t1', messages='SECRET')
    assert t.snapshot() == []  # opt-in, not merely presentation gating
    t.enabled = True
    t.observe('on_session_start', session_id='one')
    t.observe('pre_llm_call', session_id='one', turn_id='t1')
    t.observe('post_tool_call', session_id='one', args={'password': 'SECRET'})
    t.observe('pre_llm_call', session_id='one', turn_id='t1')
    row = t.snapshot()[0]
    assert row['state'] == 'Working'
    assert row['tool_calls_turn'] == row['tool_calls_total'] == 1
    assert row['id'].startswith('session:') and 'one' not in row['id']
    assert 'SECRET' not in repr(t.__dict__)
    now[0] += 10
    t.observe('post_llm_call', session_id='one')
    assert t.snapshot()[0]['state'] == 'Working'  # not the end of a turn
    t.observe('on_session_end', session_id='one', completed=True)
    assert t.snapshot()[0]['finished_ts'] == now[0]
    now[0] += 899
    assert t.snapshot()[0]['state'] == 'Done'
    now[0] += 1
    assert t.snapshot() == []


def test_new_turn_resets_only_turn_count_and_finalize_is_idempotent():
    now = [1000.0]
    t = tracker(now)
    t.enabled = True
    t.observe('post_tool_call', session_id='one')
    t.observe('on_session_end', session_id='one')
    now[0] += 1
    t.observe('on_session_finalize', session_id='one')
    assert t.snapshot()[0]['finished_ts'] == 1000
    t.observe('pre_llm_call', session_id='one', turn_id='next')
    row = t.snapshot()[0]
    assert row['state'] == 'Working' and row['finished_ts'] is None
    assert row['tool_calls_turn'] == 0 and row['tool_calls_total'] == 1


def test_subagents_roll_up_and_never_finish_parent():
    now = [1000.0]
    t = tracker(now)
    t.enabled = True
    t.observe('pre_llm_call', session_id='parent')
    t.observe('subagent_start', parent_session_id='parent', child_session_id='child')
    t.observe('subagent_start', parent_session_id='child', child_session_id='grandchild')
    t.observe('post_tool_call', session_id='grandchild')
    t.observe('on_session_end', session_id='child')
    t.observe('subagent_stop', parent_session_id='child', child_session_id='grandchild')
    rows = t.snapshot()
    assert len(rows) == 1 and rows[0]['session_id'] == 'parent'
    assert rows[0]['tool_calls_total'] == 1 and rows[0]['state'] == 'Working'


def test_active_subagent_mapping_renews_without_splitting_parent():
    now = [1000.0]
    t = tracker(now)
    t.enabled = True
    t.observe('subagent_start', parent_session_id='parent', child_session_id='child')
    now[0] += 7100
    t.observe('post_tool_call', session_id='child')
    now[0] += 200
    t.observe('post_tool_call', session_id='child')
    rows = t.snapshot()
    assert len(rows) == 1 and rows[0]['session_id'] == 'parent'
    assert rows[0]['tool_calls_total'] == 2


def test_bounds_disable_clear_and_missing_fields():
    now = [1000.0]
    t = tracker(now)
    t.enabled = True
    for bad in [None, '', 12, 'x' * 4097]:
        t.observe('post_tool_call', session_id=bad)
    assert t.snapshot() == []
    for i in range(300):
        t.observe('pre_llm_call', session_id=str(i))
        t.observe('subagent_start', parent_session_id=str(i), child_session_id='c' + str(i))
    assert len(t.snapshot()) <= 128 and len(t.children) <= 256
    now[0] += 7201
    assert all(r['state'] == 'Idle' for r in t.snapshot())
    t.enabled = False
    assert t.snapshot() == [] and not t.rows and not t.children


def test_settings_route_strict_gating_and_no_network(tmp_path, monkeypatch):
    from pulse_rings import background, sessions
    values = {}
    class Context:
        def get_config(self, key, default=None):
            return values.get(key, default)
        def set_config(self, key, value):
            values[key] = value
    background.bind_context(Context(), root=tmp_path, start=False)
    engine = Engine(tmp_path)
    monkeypatch.setattr(engine, 'poll_one_due', lambda **k: pytest.fail('network poll'))
    spec = importlib.util.spec_from_file_location('sessions_test_api', ROOT / 'dashboard/plugin_api.py')
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_pulse] = lambda: engine
    app.dependency_overrides[api.get_local_pulse] = lambda: engine
    app.dependency_overrides[api.get_arrangement_pulse] = lambda: engine
    try:
        with TestClient(app) as client:
            assert client.get('/settings').json()['show_sessions'] is False
            assert client.get('/sessions').json()['sessions'] == []
            for body, code in [({}, 422), ({'show_sessions': True}, 422),
                               ({'show_sessions': 1, 'confirm': True}, 422),
                               ({'show_sessions': True, 'confirm': 'true'}, 422),
                               ({'show_sessions': True, 'confirm': False}, 400)]:
                assert client.put('/settings', json=body).status_code == code
            assert values == {}
            assert client.put('/settings', json={'show_sessions': True, 'confirm': True}).status_code == 200
            assert client.get('/settings').json()['show_sessions'] is True
            layout = client.get('/layout').json()
            group = layout['layout']['groups'][0]
            assert group == {'id': 'hermes-sessions', 'title': 'Hermes sessions', 'collapsed': False, 'children': []}
            sessions.for_root(tmp_path).observe('post_tool_call', session_id='one')
            observed = client.get('/sessions').json()['sessions']
            assert len(observed) == 1
            layout = client.get('/layout').json()
            group = layout['layout']['groups'][0]
            assert group['children'] == [{'pulse': observed[0]['id']}]
            group.update(title='My local chats', collapsed=True)
            assert client.put('/layout', json={'layout': layout['layout'], 'revision': layout['revision']}).status_code == 200
            saved = client.get('/layout').json()['layout']
            assert saved['groups'][0]['title'] == 'My local chats'
            assert saved['groups'][0]['collapsed'] is True
            assert saved['ungrouped'] == []
            assert client.put('/settings', json={'show_sessions': False, 'confirm': True}).status_code == 200
            assert client.get('/sessions').json()['sessions'] == []
            assert client.get('/layout').json()['layout']['groups'] == []
    finally:
        background.unbind_context(tmp_path)


def test_hook_registration_missing_hooks_fail_soft(tmp_path):
    from pulse_rings import sessions
    callbacks = {}
    class Context:
        def get_config(self, key, default=None):
            return key == 'show_sessions'
        def register_hook(self, name, fn):
            if name != 'post_tool_call':
                raise ValueError('unsupported')
            callbacks[name] = fn
    t = sessions.bind_context(Context(), root=tmp_path)
    assert list(callbacks) == ['post_tool_call']
    assert callbacks['post_tool_call'](session_id='one', result='SECRET') is None
    assert t.snapshot()[0]['tool_calls_total'] == 1


def test_hook_consent_reload_and_event_contains_no_data(tmp_path, monkeypatch):
    from pulse_rings import sessions, events
    import socket
    seen, callbacks, unloads = [], {}, []
    consent: list[bool | str] = [True]
    class Context:
        def get_config(self, key, default=None):
            if consent[0] == 'unavailable':
                raise RuntimeError('config unavailable')
            return consent[0]
        def register_hook(self, name, fn):
            callbacks[name] = fn
        def on_unload(self, fn):
            unloads.append(fn)
    monkeypatch.setattr(events, 'broadcast', lambda event, payload: seen.append((event, payload)))
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('network'))
    t = sessions.bind_context(Context(), root=tmp_path)
    assert callbacks['post_tool_call'](session_id='local', args='SECRET', result='SECRET') is None
    assert seen == [('sessions.updated', {})]
    assert list(tmp_path.iterdir()) == []
    consent[0] = False
    callbacks['post_tool_call'](session_id='local')
    assert not t.rows and seen == [('sessions.updated', {})]
    consent[0] = True
    callbacks['post_tool_call'](session_id='local')
    assert t.snapshot()[0]['tool_calls_total'] == 1
    consent[0] = 'unavailable'
    callbacks['post_tool_call'](session_id='local')
    assert not t.rows
    consent[0] = True
    callbacks['post_tool_call'](session_id='local')
    unloads[0]()
    assert not t.rows and t.enabled is False


def test_tracker_profile_isolation(tmp_path):
    from pulse_rings import sessions
    a, b = sessions.for_root(tmp_path / 'a'), sessions.for_root(tmp_path / 'b')
    a.enabled = b.enabled = True
    a.observe('post_tool_call', session_id='same')
    b.observe('post_tool_call', session_id='same')
    b.observe('post_tool_call', session_id='same')
    assert a.snapshot()[0]['tool_calls_total'] == 1
    assert b.snapshot()[0]['tool_calls_total'] == 2
    assert a.snapshot()[0]['id'] != b.snapshot()[0]['id']
    a.enabled = False
    assert a.snapshot() == [] and len(b.snapshot()) == 1


def test_missing_settings_writer_and_failed_readback(tmp_path):
    from pulse_rings import sessions, background
    engine = Engine(tmp_path)
    with pytest.raises(RuntimeError, match='writer unavailable'):
        sessions.set_setting(engine, True)
    class Context:
        def get_config(self, key, default=None):
            return False
        def set_config(self, key, value):
            pass
    background.bind_context(Context(), root=tmp_path, start=False)
    try:
        with pytest.raises(RuntimeError, match='readback'):
            sessions.set_setting(engine, True)
        assert sessions.status(engine)['show_sessions'] is False
    finally:
        background.unbind_context(tmp_path)


def test_rebind_old_callbacks_and_unload_cannot_clear_new_tracker(tmp_path, monkeypatch):
    from pulse_rings import sessions, events
    monkeypatch.setattr(events, 'broadcast', lambda *a: None)
    class Context:
        def __init__(self):
            self.callbacks, self.unloads = {}, []
        def get_config(self, key, default=None):
            return True
        def register_hook(self, name, fn):
            self.callbacks[name] = fn
        def on_unload(self, fn):
            self.unloads.append(fn)
    first, second = Context(), Context()
    t = sessions.bind_context(first, root=tmp_path)
    first.callbacks['post_tool_call'](session_id='one')
    assert sessions.bind_context(second, root=tmp_path) is t
    first.unloads[0]()
    first.callbacks['post_tool_call'](session_id='one')
    second.callbacks['post_tool_call'](session_id='one')
    assert t.snapshot()[0]['tool_calls_total'] == 2
    assert sessions.for_root(tmp_path) is t
    second.unloads[0]()
    assert t.snapshot() == []
