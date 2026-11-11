"""Arrangement is local UI state, never a pulse definition or approval."""
import copy
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pulse_rings.engine import Engine

ROOT = Path(__file__).resolve().parents[1]


def model():
    from pulse_rings import arrangement
    return arrangement


def layout():
    return {'version': 1, 'groups': [{'id': 'work', 'title': 'Work', 'collapsed': False,
            'children': [{'pulse': 'a'}, {'id': 'apps', 'title': 'Apps', 'collapsed': True,
                         'children': [{'pulse': 'b'}]}]}], 'ungrouped': [{'pulse': 'c'}]}


def test_normalize_drops_removed_appends_new_and_preserves_order():
    m = model()
    out = m.reconcile(layout(), ['b', 'c', 'd'])
    assert out['groups'][0]['children'] == [layout()['groups'][0]['children'][1]]
    assert out['ungrouped'] == [{'pulse': 'c'}, {'pulse': 'd'}]
    assert m.reconcile(out, ['b', 'c', 'd']) == out


@pytest.mark.parametrize('mutation', [
    lambda x: x.update(version=True),
    lambda x: x.update(extra=1),
    lambda x: x['groups'][0].update(collapsed=1),
    lambda x: x['groups'][0].update(title=' '),
    lambda x: x['groups'][0].update(id='../oops'),
    lambda x: x['groups'][0].update(title='x' * 81),
    lambda x: x['ungrouped'].append({'pulse': 'a'}),
    lambda x: x['groups'].append(copy.deepcopy(x['groups'][0])),
    lambda x: x['groups'][0]['children'][1]['children'].append({'id': 'deep', 'title': 'Deep', 'collapsed': False, 'children': []}),
    lambda x: x['ungrouped'].append({'pulse': 'session:one'}),
    lambda x: x['ungrouped'].append({'pulse': 'x', 'extra': True}),
])
def test_invalid_models_rejected(mutation):
    value = layout()
    mutation(value)
    with pytest.raises(ValueError):
        model().validate(value)


def test_reserved_sessions_reconciled_and_not_movable_out():
    m = model()
    value = layout()
    value['ungrouped'].append({'pulse': 'session:one'})
    # Reconciliation accepts trusted inventory, not misplaced session refs.
    value['ungrouped'].pop()
    out = m.reconcile(value, ['a', 'b', 'c', 'session:one'], show_sessions=True)
    assert out['groups'][-1] == {'id': 'hermes-sessions', 'title': 'Hermes sessions',
                               'collapsed': False, 'children': [{'pulse': 'session:one'}]}
    out['groups'][-1].update(title='Chats', collapsed=True)
    assert m.reconcile(out, ['session:two'], show_sessions=True)['groups'][-1]['title'] == 'Chats'
    assert not any(g['id'] == 'hermes-sessions' for g in m.reconcile(out, [], show_sessions=False)['groups'])


def test_atomic_round_trip_stale_write_and_profile_isolation(tmp_path):
    m = model()
    engine = Engine(tmp_path / 'one')
    first = m.read(engine.store, ['a', 'b', 'c'])
    assert first['layout']['ungrouped'] == [{'pulse': 'a'}, {'pulse': 'b'}, {'pulse': 'c'}]
    saved = m.write(engine.store, layout(), first['revision'], ['a', 'b', 'c'])
    assert m.read(Engine(tmp_path / 'one').store, ['a', 'b', 'c']) == saved
    with pytest.raises(m.StaleLayout):
        m.write(engine.store, layout(), first['revision'], ['a', 'b', 'c'])
    assert m.read(Engine(tmp_path / 'two').store, ['a'])['layout']['groups'] == []
    assert (tmp_path / 'one' / 'layout.json').is_file()
    assert engine.status()['pulses'] == []


def test_concurrent_compare_and_swap_has_one_winner(tmp_path):
    m = model()
    store = Engine(tmp_path).store
    revision = m.read(store, ['a', 'b', 'c'])['revision']
    def put(_):
        try:
            m.write(store, layout(), revision, ['a', 'b', 'c'])
            return 'saved'
        except m.StaleLayout:
            return 'stale'
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sorted(pool.map(put, range(4))) == ['saved', 'stale', 'stale', 'stale']


def test_corrupt_or_oversize_local_file_never_overwritten(tmp_path):
    m = model()
    store = Engine(tmp_path).store
    for data in [b'bad', b'x' * 65537]:
        (tmp_path / 'layout.json').write_bytes(data)
        with pytest.raises(ValueError):
            m.read(store, [])
        assert (tmp_path / 'layout.json').read_bytes() == data


def test_failed_replace_keeps_old_layout(tmp_path, monkeypatch):
    m = model()
    store = Engine(tmp_path).store
    before = m.read(store, ['a', 'b', 'c'])
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(m.os, 'replace', fail)
    with pytest.raises(OSError):
        m.write(store, layout(), before['revision'], ['a', 'b', 'c'])
    assert m.read(store, ['a', 'b', 'c']) == before
    assert not list(tmp_path.glob('layout-*.tmp'))


def test_routes_are_plain_local_strict_and_no_poll(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('groups_api', ROOT / 'dashboard/plugin_api.py')
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    engine = Engine(tmp_path)
    monkeypatch.setattr(engine, 'status', lambda **kw: pytest.fail('Layout must never poll status'))
    app = FastAPI()
    app.include_router(api.router)
    monkeypatch.setattr(api._core, 'Pulse', lambda: engine)
    monkeypatch.setattr(api._core, 'ensure_collection', lambda *a: pytest.fail('Layout must not start collection'))
    client = TestClient(app)
    got = client.get('/layout')
    assert got.status_code == 200
    assert got.headers['cache-control'] == 'no-store'
    body = got.json()
    empty = {'version': 1, 'groups': [], 'ungrouped': []}
    saved = client.put('/layout', json={'layout': empty, 'revision': body['revision']})
    assert saved.status_code == 200
    assert client.get('/layout').json() == saved.json()
    # A no-op is idempotent; a real old revision must be rejected.
    changed = {**empty, 'groups': [{'id': 'work', 'title': 'Work', 'collapsed': False, 'children': []}]}
    assert client.put('/layout', json={'layout': changed, 'revision': body['revision']}).status_code == 200
    assert client.put('/layout', json={'layout': empty, 'revision': body['revision']}).status_code == 409
    assert client.put('/layout', json={'layout': empty}).status_code == 422
    assert client.put('/layout', json={'layout': {**empty, 'version': True}, 'revision': saved.json()['revision']}).status_code == 400
    assert client.put('/layout', json={'layout': empty, 'revision': 'x', 'confirm': True}).status_code == 422
    import inspect
    assert not inspect.iscoroutinefunction(api.get_layout)
    assert not inspect.iscoroutinefunction(api.put_layout)


def test_item_count_and_utf8_size_caps():
    m = model()
    too_many = {'version': 1, 'groups': [
        {'id': f'g{i}', 'title': 'G', 'collapsed': False, 'children': []}
        for i in range(513)], 'ungrouped': []}
    with pytest.raises(ValueError):
        m.validate(too_many)
    too_large = {'version': 1, 'groups': [
        {'id': f'g{i}', 'title': '🌟' * 80, 'collapsed': False, 'children': []}
        for i in range(200)], 'ungrouped': []}
    with pytest.raises(ValueError):
        m.validate(too_large)


def test_membership_changes_invalidate_revision_and_append_new(tmp_path):
    m = model()
    store = Engine(tmp_path).store
    old = m.read(store, ['a', 'b', 'c'])
    new = m.read(store, ['a', 'b', 'c', 'new'])
    assert new['revision'] != old['revision']
    assert new['customized'] is False
    with pytest.raises(m.StaleLayout):
        m.write(store, layout(), old['revision'], ['a', 'b', 'c', 'new'])
    saved = m.write(store, layout(), new['revision'], ['a', 'b', 'c', 'new'])
    assert saved['customized'] is True
    assert saved['layout']['ungrouped'][-1] == {'pulse': 'new'}
    pruned = m.read(store, ['a', 'c', 'new'])
    assert pruned['layout']['groups'][0]['children'][1]['children'] == []


def test_optional_session_inventory_uses_sibling_public_module(tmp_path, monkeypatch):
    import pulse_rings
    from types import SimpleNamespace
    m = model()
    pulse = Engine(tmp_path)
    state = {'show_sessions': True, 'sessions': [{'id': 'session:one'}]}
    monkeypatch.setattr(pulse_rings, 'sessions', SimpleNamespace(status=lambda engine: state), raising=False)
    ids, enabled = m.inventory(pulse)
    assert ids == ['session:one'] and enabled is True
    value = m.read(pulse.store, ids, show_sessions=enabled)
    assert value['layout']['groups'][0]['id'] == 'hermes-sessions'
    state['show_sessions'] = False
    assert m.inventory(pulse) == ([], False)


def test_target_directory_or_link_is_not_followed(tmp_path):
    m = model()
    store = Engine(tmp_path).store
    (tmp_path / 'layout.json').mkdir()
    with pytest.raises(ValueError):
        m.read(store, [])
