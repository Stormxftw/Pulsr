"""Schema, durable scheduling and renderer contract tests. All network is injected."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pulse_rings.engine import Engine
from pulse_rings.sources.base import SourceResult, SourceError
from pulse_rings.store import Store

PRESET = json.loads((Path(__file__).parent / 'fixtures/normalized/discord-reference.json').read_text())


class Counter:
    def __init__(self):
        self.calls = []

    def poll(self, definition, previous, state, *, now, net):
        self.calls.append(definition['id'])
        return SourceResult(sample={'ts': now, 'metrics': {'online': 100, 'members': 1000}},
                            state={'count': state.get('count', 0) + 1}, next_due=now + 600)


def test_schema_and_idempotent_initialization(tmp_path):
    store = Store(tmp_path)
    Store(tmp_path)
    with store.db() as db:
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert names >= {'pulses', 'samples', 'gates', 'drafts', 'hermes_events', 'hermes_open', 'meta'}
        assert db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '1'
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        db.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
    with pytest.raises(ValueError, match='schema'):
        Store(tmp_path)


def test_status_polls_at_most_one_due_source_and_cached_never_polls(tmp_path):
    adapter = Counter()
    engine = Engine(tmp_path, clock=lambda: 1000, adapters={'discord.invite@1': adapter})
    for name in ('first', 'second', 'third'):
        definition = copy.deepcopy(PRESET)
        definition['id'] = name
        engine.activate(definition)
    assert len(engine.status(poll=False)['pulses']) == 3
    assert adapter.calls == []
    payload = engine.status(poll=True)
    assert adapter.calls == ['first']
    assert payload['api_version'] == '0.5.0-dev'
    assert len(payload['pulses']) == 3
    item = payload['pulses'][0]
    assert set(item) >= {'id','title','kind','state','ring','capsule','lines','icon_data',
        'last_ok_ts','next_due','backoff_until','error','alert','history','budget'}
    assert all(set(c) >= {'metric','value','baseline','baseline_mode','observed_seconds','unknown','contribution'}
               for c in item['ring']['components'])


def test_cross_instance_due_lease(tmp_path):
    store = Store(tmp_path)
    store.put_pulse(PRESET, now=1000)
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(lambda _: Store(tmp_path).claim_due(1000), range(6)))
    assert sum(r is not None for r in rows) == 1
    assert store.claim_due(1090)['id'] == PRESET['id']


def test_error_404_is_preserved_with_24h_retry(tmp_path):
    class Expired(Counter):
        def poll(self, *args, **kwargs):
            raise SourceError('Invite expired.', 404)
    e = Engine(tmp_path, clock=lambda: 1000, adapters={'discord.invite@1': Expired()})
    e.activate(PRESET)
    item = e.status(poll=True)['pulses'][0]
    assert item['state'] == 'error'
    assert item['next_due'] == 87400
    assert item['error'] == 'Invite expired.'


def test_pause_delete_and_retention(tmp_path):
    e = Engine(tmp_path, clock=lambda: 1000, adapters={'discord.invite@1': Counter()})
    e.activate(PRESET)
    e.poll_one_due()
    assert e.store.pause(PRESET['id'], True)
    restarted = Engine(tmp_path, clock=lambda: 100000, adapters={'discord.invite@1': Counter()})
    assert restarted.status(poll=True)['pulses'][0]['state'] == 'paused'
    assert restarted.adapters['discord.invite@1'].calls == []
    e.store.remove(PRESET['id'])
    assert e.status()['pulses'] == []
    assert len(e.store.history(PRESET['id'])) == 1


def test_unsupported_is_visible_and_never_polled(tmp_path):
    e = Engine(tmp_path, clock=lambda: 1000)
    definition = copy.deepcopy(PRESET)
    definition['pulse'] = 2
    e.activate(definition)
    assert e.status(poll=True)['pulses'][0]['state'] == 'unsupported_version'
    assert e.store.rows()[0]['next_due'] == 0


def test_future_shape_is_visible_without_v1_fields(tmp_path):
    e = Engine(tmp_path, clock=lambda: 1000)
    e.activate({'pulse': 2, 'id': 'future', 'title': 'Future format', 'x-extra': True})
    item = e.status(poll=True)['pulses'][0]
    assert item['id'] == 'future'
    assert item['state'] == 'unsupported_version'
    assert item['ring']['score'] == 0
    assert item['capsule']['fill'] is None
    assert e.store.rows()[0]['next_due'] == 0


def test_active_cap_and_update_are_atomic(tmp_path):
    store = Store(tmp_path)
    for i in range(24):
        store.put_pulse({**PRESET, 'id': f'counter-{i}'}, now=1)
    store.put_pulse({**PRESET, 'id': 'counter-0'}, now=2)
    with pytest.raises(ValueError, match='24'):
        store.put_pulse({**PRESET, 'id': 'overflow'}, now=2)
    assert len(store.rows()) == 24


def test_patch_delete_routes(tmp_path):
    import dashboard.plugin_api as api
    e = Engine(tmp_path, clock=lambda: 1000, adapters={'discord.invite@1': Counter()})
    e.activate(PRESET)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_pulse] = lambda: e
    with TestClient(app) as client:
        url = '/pulses/' + PRESET['id']
        assert client.patch(url, json={'paused': True}).status_code == 200
        assert client.get('/status').json()['pulses'][0]['state'] == 'paused'
        assert client.patch(url, json={'paused': 'true'}).status_code == 422
        assert client.patch(url, json={'paused': True, 'definition': PRESET}).status_code == 422
        assert client.patch('/pulses/missing', json={'paused': True}).status_code == 404
        assert client.delete(url).json() == {'ok': True}
        assert client.get('/status').json()['pulses'] == []
        assert client.delete(url).status_code == 404


def test_status_route_refreshes_only_one_of_multiple_due_pulses(tmp_path):
    import dashboard.plugin_api as api
    adapter = Counter()
    e = Engine(tmp_path, clock=lambda: 1000, adapters={'discord.invite@1': adapter})
    e.activate({**PRESET, 'id': 'first'})
    e.activate({**PRESET, 'id': 'second'})
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_pulse] = lambda: e
    with TestClient(app) as client:
        payload = client.get('/status').json()
    assert payload['api_version'] == '0.5.0-dev'
    assert len(payload['pulses']) == 2
    assert adapter.calls == ['first']


def test_registered_status_tool_uses_same_engine_without_polling(tmp_path, monkeypatch):
    import importlib.util
    import sys
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('_wp2_entrypoint', root / '__init__.py',
                                                submodule_search_locations=[str(root)])
    plugin = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, '_wp2_entrypoint', plugin)
    spec.loader.exec_module(plugin)
    module = __import__('_wp2_entrypoint.pulse_rings.engine', fromlist=['Engine'])
    adapter = Counter()
    e = Engine(tmp_path, clock=lambda: 1000, adapters={'discord.invite@1': adapter})
    e.activate(PRESET)
    monkeypatch.setattr(module, 'Engine', lambda: e)
    hooks = __import__('_wp2_entrypoint.pulse_rings.hooks', fromlist=['Store'])
    monkeypatch.setattr(hooks, 'Store', lambda: e.store)
    class Context:
        def register_tool(self, **kwargs):
            self.tool = kwargs
        def register_skill(self, *args):
            pass
        def register_hook(self, *args):
            pass
        def register_command(self, *args, **kwargs):
            pass
        def get_config(self, key, default=None):
            return default
    ctx = Context()
    plugin.register(ctx)
    assert ctx.tool['name'] == 'pulse_rings_status'
    output = json.loads(ctx.tool['handler']({}))
    assert output['api_version'] == '0.5.0-dev'
    assert output['pulses'][0]['id'] == PRESET['id']
    assert 'icon_data' not in output['pulses'][0]
    assert 'history' not in output['pulses'][0] and 'servers' not in output and 'curated' not in output
    assert adapter.calls == []


def test_pending_drafts_filter_expiry_and_strip_tool_icons(tmp_path):
    e = Engine(tmp_path, clock=lambda: 1000)
    preview = {'icon_data': 'sentinel-image', 'nested': [{'icon_data': 'nested-image'}]}
    with e.store.transaction() as db:
        for draft_id, status, expires in [('pd_pending', 'pending', 2000),
                ('pd_expired', 'pending', 500), ('pd_decided', 'approved', 2000)]:
            db.execute('''INSERT INTO drafts(id,definition,status,created_ts,expires_ts,preview)
                VALUES (?,?,?,?,?,?)''', (draft_id, json.dumps(PRESET), status, 1, expires, json.dumps(preview)))
    draft = e.status()['drafts']
    assert {d['id']: d['status'] for d in draft} == {'pd_pending': 'pending', 'pd_expired': 'expired', 'pd_decided': 'approved'}
    assert draft[0]['preview']['icon_data'] == 'sentinel-image'
    tool_draft = e.status(include_icons=False)['drafts'][0]
    assert tool_draft['preview']['icon_data'] is None
    assert tool_draft['preview']['nested'][0]['icon_data'] is None
