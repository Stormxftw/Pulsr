"""Human decisions and bounded preview collection; no live network."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pulse_rings.engine import Engine
from pulse_rings.spec import ValidationError

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / 'tests/fixtures/github'
MANIFEST = json.loads((FIX / 'manifest.json').read_text())
NOW = MANIFEST['now']


def gh(id='catalog-prs'):
    return {'pulse': 1, 'id': id, 'title': 'Catalog PRs', 'source': {'kind': 'github.search',
            'params': {'repo': 'NousResearch/hermes-agent', 'type': 'pr', 'title_contains': 'catalog'}}}


@pytest.fixture
def engine(tmp_path, monkeypatch):
    clock = [NOW]
    e = Engine(tmp_path, clock=lambda: clock[0], jitter=lambda: 0)
    e.test_clock = clock
    calls = []
    def fetch(url, **kw):
        calls.append(url)
        name = 'baseline' if len(calls) == 1 else 'recent'
        response = json.loads((FIX / MANIFEST['files'][name]).read_text())
        return json.dumps(response['body']).encode(), response['headers']
    monkeypatch.setattr('pulse_rings.net.fetch_bytes', fetch)
    monkeypatch.setattr('pulse_rings.sources.github._optional_token', lambda: None)
    monkeypatch.setattr('pulse_rings.events.broadcast', lambda *a, **kw: None)
    e.test_calls = calls
    return e


def test_model_fixable_field_paths(engine):
    d = gh(); d['source']['params']['raw_query'] = 'not allowed'
    with pytest.raises(ValidationError) as err:
        engine.create_draft(d, origin={'kind': 'session'})
    assert any(x['path'] == '/source/params/raw_query' for x in err.value.errors)
    assert not engine.test_calls


def test_cold_preview_ticks_and_approval_first_sample(engine):
    result = engine.create_draft(gh(), origin={'kind': 'session', 'session_id': 's'})
    id = result['draft_id']
    assert result['status'] == 'pending' and result['preview'] is None
    assert result['preview_calls'] == 1 and len(engine.test_calls) == 1
    assert engine.status(poll=False)['drafts'][0]['preview_state'] == 'sampling'
    engine.status(poll=True)  # host gate still closed
    assert len(engine.test_calls) == 1
    engine.test_clock[0] += 2
    hot = engine.status(poll=True)['drafts'][0]
    assert hot['preview_calls'] == 2 and len(engine.test_calls) == 2
    assert hot['preview']['ring']['score'] == 100
    assert hot['preview']['capsule']['caption'].startswith('3.0')
    engine.test_clock[0] += 30
    engine.status(poll=True)
    assert len(engine.test_calls) == 2
    live = engine.decide_draft(id, 'approve')
    assert live['row']['id'] == 'catalog-prs'
    assert live['row']['ring']['score'] == 100
    assert engine.store.history('catalog-prs') == [hot['sample']]
    assert engine.store.draft(id, engine.clock())['status'] == 'approved'
    assert engine.store.rows()[0]['source_state'] != '{}'


@pytest.mark.parametrize('kind', ['cron', 'subagent', 'kanban', 'unattended'])
def test_unattended_never_fetches_even_from_later_interactive_poller(engine, kind):
    engine.create_draft(gh(), origin={'kind': kind})
    for _ in range(3):
        engine.test_clock[0] += 3
        engine.status(poll=True)
    assert engine.test_calls == []
    assert engine.status()['drafts'][0]['preview_calls'] == 0


def test_arbitrary_host_never_calls_adapter(engine):
    adapter = Mock()
    engine.adapters['http_json'] = adapter
    d = {'pulse': 1, 'title': 'Public count', 'source': {'kind': 'http_json',
         'params': {'url': 'https://example.org/count', 'metrics': {'count': '/count'}}}}
    engine.create_draft(d, origin={'kind': 'session'})
    for _ in range(3):
        engine.test_clock[0] += 3
        engine.status(poll=True)
    adapter.poll.assert_not_called()
    assert not engine.test_calls


def test_pending_limit_and_seven_day_expiry(engine):
    for i in range(5):
        engine.create_draft(gh('draft-' + str(i)), origin={'kind': 'cron'})
    with pytest.raises(ValueError, match='5 pending'):
        engine.create_draft(gh('sixth'), origin={'kind': 'session'})
    assert not engine.test_calls  # no fetch before cap check
    first = engine.status()['drafts'][0]
    assert first['expires_ts'] - first['created_ts'] == 7 * 86400
    engine.test_clock[0] += 7 * 86400
    with pytest.raises(ValueError, match='expired'):
        engine.decide_draft(first['id'], 'approve')
    assert engine.store.draft(first['id'], engine.clock())['status'] == 'expired'
    engine.create_draft(gh('new-draft'), origin={'kind': 'cron'})


def test_pending_is_never_lost_behind_recent_decision_history(engine):
    old = engine.create_draft(gh('old'), origin={'kind': 'cron'})['draft_id']
    for i in range(51):
        engine.test_clock[0] += 1
        recent = engine.create_draft(gh('recent-' + str(i)), origin={'kind': 'cron'})['draft_id']
        engine.decide_draft(recent, 'reject')
    assert any(d['id'] == old and d['status'] == 'pending' for d in engine.status()['drafts'])
    assert engine.test_calls == []


def test_duplicate_id_diff_and_budget_replacement(engine):
    engine.activate(gh())
    d = gh(); d['title'] = 'New title'
    result = engine.create_draft(d, origin={'kind': 'cron'})
    draft = engine.store.draft(result['draft_id'], engine.clock())
    assert draft['replaces'] == 'catalog-prs'
    assert '-  "title": "Catalog PRs"' in draft['diff']
    assert '+  "title": "New title"' in draft['diff']
    engine.decide_draft(draft['id'], 'approve')
    assert len(engine.store.rows()) == 1


def test_decision_admission_is_atomic_and_reject_terminal(engine):
    engine.net.ceiling = 5
    engine.activate(gh('active'))
    result = engine.create_draft(gh('over-budget'), origin={'kind': 'cron'})
    with pytest.raises(ValueError, match='budget|ceiling'):
        engine.decide_draft(result['draft_id'], 'approve')
    assert engine.store.draft(result['draft_id'], engine.clock())['status'] == 'pending'
    assert len(engine.store.rows()) == 1
    engine.decide_draft(result['draft_id'], 'reject')
    with pytest.raises(ValueError, match='rejected'):
        engine.decide_draft(result['draft_id'], 'approve')


def test_broadcast_failure_never_loses_draft_or_decision(engine, monkeypatch):
    monkeypatch.setattr('pulse_rings.events.broadcast', Mock(side_effect=RuntimeError('no gateway')))
    result = engine.create_draft(gh(), origin={'kind': 'cron'})
    engine.decide_draft(result['draft_id'], 'approve')
    assert len(engine.store.rows()) == 1


def test_share_yaml_is_exact_normalized_definition(engine):
    from pulse_rings.spec import normalize
    spec = importlib.util.spec_from_file_location('share_test_api', ROOT / 'dashboard/plugin_api.py')
    api = importlib.util.module_from_spec(spec); spec.loader.exec_module(api)
    app = FastAPI(); app.include_router(api.router)
    app.dependency_overrides[api.get_pulse] = lambda: engine
    engine.activate(gh())
    with TestClient(app) as client:
        result = client.get('/pulses/catalog-prs/definition')
        assert result.status_code == 200
        assert normalize(result.json()['yaml']) == normalize(gh())
        assert client.get('/pulses/missing/definition').status_code == 404
        assert client.get('/status?poll=0').json()['features']['share_yaml'] is True
    assert not engine.test_calls


def test_rest_routes_and_cached_status(engine):
    spec = importlib.util.spec_from_file_location('draft_test_api', ROOT / 'dashboard/plugin_api.py')
    api = importlib.util.module_from_spec(spec); spec.loader.exec_module(api)
    app = FastAPI(); app.include_router(api.router)
    app.dependency_overrides[api.get_pulse] = lambda: engine
    client = TestClient(app)
    response = client.post('/drafts', json={'definition': gh()})
    assert response.status_code == 200
    id = response.json()['draft_id']
    assert len(engine.test_calls) == 1
    assert client.get('/status?poll=0').status_code == 200
    assert len(engine.test_calls) == 1
    assert client.get('/drafts/' + id).json()['status'] == 'pending'
    approved = client.post('/drafts/' + id + '/approve', json={'confirm': True})
    assert approved.status_code == 200 and approved.json()['row']['id'] == 'catalog-prs'
    assert client.post('/drafts/' + id + '/reject', json={'confirm': True}).status_code == 409
    assert client.post('/drafts/bad/approve', json={'confirm': True}).status_code == 404
    assert client.get('/catalog').status_code == 200
    bad = gh(); bad['bad'] = 3
    assert client.post('/drafts', json={'definition': bad}).json()['detail']['errors'][0]['path'] == '/bad'

@pytest.mark.parametrize('kind', ['cron', 'subagent', 'kanban'])
def test_fixed_host_tool_mocks_prove_zero_fetches_in_unattended_contexts(engine, monkeypatch, kind):
    from pulse_rings.authoring import RunContexts, register_tools
    ctx = SimpleNamespace(current_cron_execution=lambda: object() if kind == 'cron' else None,
                          register_tool=lambda **kw: tools.update({kw['name']: kw['handler']}))
    tools = {}
    contexts = RunContexts(ctx)
    contexts.observe('pre_llm_call', session_id='s', parent_session_id='parent' if kind == 'subagent' else None)
    monkeypatch.delenv('HERMES_DELEGATED_CHILD_CONTEXT', raising=False)
    monkeypatch.delenv('HERMES_KANBAN_TASK', raising=False)
    if kind == 'kanban': monkeypatch.setenv('HERMES_KANBAN_TASK', 'task')
    network = Mock(side_effect=AssertionError('Unattended source attempted egress'))
    monkeypatch.setattr('pulse_rings.net.fetch_bytes', network)
    register_tools(ctx, contexts, lambda: engine)
    result = json.loads(tools['pulse_rings_propose']({'definition': gh()}, session_id='s'))
    assert result['origin']['kind'] == kind
    for _ in range(3):
        engine.test_clock[0] += 3
        engine.status(poll=True)
    network.assert_not_called()


def test_preview_restart_error_cap_and_local_gate_count(engine, monkeypatch):
    from pulse_rings.sources.base import SourceError
    error = Mock(side_effect=SourceError('rate limited', 403, 10))
    monkeypatch.setattr('pulse_rings.net.fetch_bytes', error)
    result = engine.create_draft(gh(), origin={'kind': 'session'})
    assert result['preview_calls'] == 1
    engine.test_clock[0] += 2
    engine.status(poll=True)
    assert error.call_count == 1  # durable host backoff
    engine.test_clock[0] += 10
    restarted = Engine(engine.root, clock=engine.clock, jitter=lambda: 0)
    restarted.status(poll=True)
    assert error.call_count == 2
    for _ in range(3):
        engine.test_clock[0] += 1000
        restarted.status(poll=True)
    assert error.call_count == 2
    assert restarted.draft(result['draft_id'])['preview_calls'] == 2
    assert restarted.draft(result['draft_id'])['preview'] is None


def test_discord_preview_does_not_fetch_icon_or_widget(engine):
    raw = json.loads((ROOT / 'tests/fixtures/nousresearch.json').read_text())
    source = engine.adapters['discord.invite@1']
    source.fetch = Mock(return_value=raw)
    source.icons = SimpleNamespace(cache=Mock(side_effect=AssertionError('No icons before approval')))
    result = engine.create_draft({'pulse': 1, 'title': 'Nous', 'source': {'kind': 'discord.invite',
                                 'params': {'invite': 'nousresearch'}}}, origin={'kind': 'session'})
    assert result['preview_calls'] == 1 and result['preview'] is not None
    for _ in range(3):
        engine.test_clock[0] += 3
        engine.status(poll=True)
    source.fetch.assert_called_once()
    source.icons.cache.assert_not_called()


def test_preview_lease_and_stale_replacement_never_bypass_decision(engine):
    from pulse_rings.previews import PreviewNet
    id = engine.propose(gh(), origin={'kind': 'session'}, preview_allowed=True)
    claimed = engine.store.claim_preview(engine.clock(), id)
    assert claimed is not None
    assert engine.store.claim_preview(engine.clock(), id) is None
    engine.decide_draft(id, 'reject')
    callback = Mock()
    with pytest.raises(ValueError, match='no longer'):
        PreviewNet(engine, id, claimed[1], ['api.github.com']).call('api.github.com', callback)
    callback.assert_not_called()
    engine.activate(gh())
    change = gh(); change['title'] = 'Change'
    id = engine.create_draft(change, origin={'kind': 'cron'})['draft_id']
    newer = gh(); newer['title'] = 'Someone else changed it'
    engine.activate(newer)
    with pytest.raises(ValueError, match='changed'):
        engine.decide_draft(id, 'approve')


def test_approval_rechecks_active_cap_and_replacement_credit(engine):
    for i in range(24):
        engine.activate({'pulse': 1, 'id': 'local-' + str(i), 'title': 'Local', 'source': {'kind': 'hermes.activity'}})
    id = engine.create_draft(gh(), origin={'kind': 'cron'})['draft_id']
    with pytest.raises(ValueError, match='24 active'):
        engine.decide_draft(id, 'approve')
    assert engine.draft(id)['status'] == 'pending'
    # Replacing an existing allocation doesn't consume another active slot.
    engine.net.ceiling = 1
    replacement = {'pulse': 1, 'id': 'local-0', 'title': 'Changed', 'source': {'kind': 'hermes.activity'}}
    id = engine.create_draft(replacement, origin={'kind': 'cron'})['draft_id']
    assert engine.decide_draft(id, 'approve')['row']['title'] == 'Changed'



def test_immutable_icons_are_separate_from_status_payload(engine):
    import base64
    spec = importlib.util.spec_from_file_location('icon_test_api', ROOT / 'dashboard/plugin_api.py')
    api = importlib.util.module_from_spec(spec); spec.loader.exec_module(api)
    app = FastAPI(); app.include_router(api.router)
    app.dependency_overrides[api.get_pulse] = lambda: engine
    gid, hash_ = '100000000000000000', 'a' * 32
    png = (ROOT / 'tests/fixtures/tiny.png').read_bytes()
    path = engine.icons.path(gid, hash_)
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(png)
    d = {'pulse': 1, 'id': 'icon-pulse', 'title': 'Icon', 'source': {'kind': 'discord.invite', 'params': {'invite': 'nousresearch'}}}
    engine.activate(d, sample={'ts': NOW, 'metrics': {'online': 1}, 'metadata': {'id': gid, 'icon_hash': hash_}})
    with TestClient(app) as client:
        row = client.get('/status?poll=0').json()['pulses'][0]
        assert row['icon_data'] is None
        assert row['icon_url'] == f'/icons/{gid}-{hash_}'
        response = client.get(row['icon_url'])
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'private, max-age=31536000, immutable'
        assert response.json()['icon_data'] == 'data:image/png;base64,' + base64.b64encode(png).decode()
        assert client.get('/icons/' + gid + '-' + 'b' * 32).status_code == 404
        assert client.get('/icons/bad').status_code == 404
        path.write_bytes(b'not an image')
        assert client.get(row['icon_url']).status_code == 404
