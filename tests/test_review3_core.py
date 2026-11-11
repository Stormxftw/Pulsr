"""Review-3 regressions: source identity and honest artwork admission scope."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_live_feeds import definition, Changing
from pulse_rings.engine import Engine
from pulse_rings.sources.base import SourceResult, SourceError, Deferred

ROOT = Path(__file__).resolve().parents[1]


def client_for(e):
    import dashboard.plugin_api as api
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_pulse] = lambda: e
    return TestClient(app)


def replace(client, d):
    proposal = client.post('/drafts', json={'definition': d})
    assert proposal.status_code == 200, proposal.text
    draft = proposal.json()['draft_id']
    response = client.post(f'/drafts/{draft}/approve', json={'confirm': True})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize('edit', ['url', 'pointer', 'kind', 'rename', 'style', 'cadence'])
def test_rest_replacement_scopes_current_learning_and_previous(tmp_path, edit):
    now = [10000.0]
    fake = Changing()
    e = Engine(tmp_path, clock=lambda: now[0], jitter=lambda: 0, adapters={'http_json': fake})
    d = definition(); d.pop('alert')
    d['display'] = [{'type': 'bar', 'value': 'fast.count'}, {'type': 'stat', 'value': 'slow.count'}]
    e.activate(d)
    for t in (10000, 11800, 13600):
        now[0] = t
        e.poll_one_due(); e.poll_one_due()
    old = e.status()['pulses'][0]['display'][0]['items'][0]
    assert old['value'] == 30 and old['fill'] == 60 and not old['learning']
    if edit == 'url': d['feeds']['fast']['params']['url'] = 'https://example.edu/new-source'
    if edit == 'pointer': d['feeds']['fast']['params']['metrics']['count'] = '/other'
    if edit == 'kind': d['feeds']['fast'] = {'kind': 'mcp.tool', 'params': {'server': 'demo', 'tool': 'read', 'args': {}, 'metrics': {'count': '/count'}}}
    if edit == 'rename':
        d['feeds']['new'] = d['feeds'].pop('fast')
        d['display'][0]['value'] = 'new.count'
    if edit == 'style': d['theme'] = {'accent': '#654321'}
    if edit == 'cadence': d['feeds']['fast']['every'] = '30m'
    with client_for(e) as client:
        replace(client, d)
        row = client.get('/status?poll=0').json()['pulses'][0]
    item = row['display'][0]['items'][0]
    unchanged = edit in ('style', 'cadence')
    assert item['value'] == (30 if unchanged else None)
    assert item['learning'] is (not unchanged)
    assert item['unknown'] is (not unchanged)
    name = 'new' if edit == 'rename' else 'fast'
    expected_state = 'active' if unchanged else 'needs_mcp_grant' if edit == 'kind' else 'warming'
    assert next(f for f in row['feeds'] if f['name'] == name)['state'] == expected_state
    assert row['display'][1]['value'] == 30  # Unchanged sibling keeps its data/state.
    if not unchanged:
        assert not e.store.history('live', feed='new' if edit == 'rename' else 'fast')
    # Restart must retain the approved identity boundary.
    restarted = Engine(tmp_path, clock=lambda: now[0], adapters={'http_json': fake})
    assert restarted.status()['pulses'][0]['display'] == row['display']


@pytest.mark.parametrize('field,value', [('server', 'other'), ('tool', 'other'), ('args', {'scope': 'new'}), ('metrics', {'count': '/other'})])
def test_mcp_identity_changes_reset(tmp_path, field, value):
    e = Engine(tmp_path, clock=lambda: 10000)
    d = definition(); d.pop('alert')
    d['feeds']['fast'] = {'kind': 'mcp.tool', 'params': {'server': 'demo', 'tool': 'read', 'args': {}, 'metrics': {'count': '/count'}}}
    e.activate(d)
    with e.store.transaction() as db:
        e.store.insert_sample(db, 'live', {'ts': 9999, 'metrics': {'count': 30}}, feed='fast')
    d['feeds']['fast']['params'][field] = value
    with client_for(e) as client:
        replace(client, d)
        assert client.get('/status?poll=0').json()['pulses'][0]['display'][0]['items'][0]['unknown']


@pytest.mark.parametrize('outcome', ['sample', 'error', 'deferred'])
@pytest.mark.parametrize('legacy', [False, True])
def test_old_inflight_completion_cannot_write_new_generation(tmp_path, outcome, legacy):
    started, release = threading.Event(), threading.Event()
    class Blocking:
        def poll(self, d, previous, state, *, now, net):
            started.set()
            assert release.wait(10)
            if outcome == 'error': raise SourceError('Old source failed', 503)
            if outcome == 'deferred': raise Deferred('Old pacing', 429, 900)
            return SourceResult(sample={'ts': now, 'metrics': {'count': 777}}, state={'old': True})
    e = Engine(tmp_path, clock=lambda: 10000, adapters={'http_json': Blocking()}, jitter=lambda: 0)
    d = definition(); d.pop('alert')
    if legacy:
        d = {'pulse': 1, 'id': 'live', 'title': 'Legacy', 'source': {'kind': 'http_json', 'params': d['feeds']['fast']['params']}}
    e.activate(d)
    worker = threading.Thread(target=e.poll_one_due)
    worker.start()
    try:
        assert started.wait(5)
        if legacy: d['source']['params']['url'] = 'https://example.edu/new'
        else: d['feeds']['fast']['params']['url'] = 'https://example.edu/new'
        with client_for(e) as client: replace(client, d)
    finally:
        release.set(); worker.join(10)
    assert not worker.is_alive()
    name = 'main' if legacy else 'fast'
    assert not e.store.history('live', feed=name)
    feed = e.store.feed_rows('live')[name]
    assert feed['source_state'] == '{}' and feed['error'] is None and feed['failures'] == 0
    assert feed['next_due'] == 10002


def test_removed_feed_name_reintroduced_never_resurrects_history(tmp_path):
    e = Engine(tmp_path, clock=lambda: 10000)
    d = definition(); d.pop('alert')
    e.activate(d)
    with e.store.transaction() as db:
        e.store.insert_sample(db, 'live', {'ts': 9999, 'metrics': {'count': 30}}, feed='fast')
    reduced = copy.deepcopy(d); reduced['feeds'].pop('fast'); reduced['display'].pop(0)
    e.activate(reduced)
    e.activate(d)
    assert not e.store.history('live', feed='fast')


@pytest.mark.parametrize('changed', [False, True])
def test_legacy_replacement_retains_only_compatible_state_and_history(tmp_path, changed):
    fake = Changing()
    e = Engine(tmp_path, clock=lambda: 10000, adapters={'http_json': fake})
    d = {'pulse': 1, 'id': 'live', 'title': 'Legacy', 'source': {'kind': 'http_json', 'params': definition()['feeds']['fast']['params']}}
    e.activate(d); e.poll_one_due()
    d['title'] = 'New layout title'
    if changed: d['source']['params']['url'] = 'https://example.edu/new'
    with client_for(e) as client: replace(client, d)
    assert bool(e.store.history('live')) is (not changed)
    assert json.loads(e.store.rows()[0]['source_state']) == ({} if changed else {'n': 1})


@pytest.mark.parametrize('explicit_first', [False, True])
def test_same_source_survives_switch_between_implicit_and_explicit_main(tmp_path, explicit_first):
    fake = Changing()
    e = Engine(tmp_path, clock=lambda: 10000, adapters={'http_json': fake})
    source = {'pulse': 1, 'id': 'live', 'title': 'Same', 'source': {'kind': 'http_json', 'params': definition()['feeds']['fast']['params']}}
    explicit = {'pulse': 1, 'id': 'live', 'title': 'Same', 'feeds': {'main': definition()['feeds']['fast']},
                'display': [{'type': 'stat', 'value': 'main.count'}]}
    first, second = (explicit, source) if explicit_first else (source, explicit)
    e.activate(first); e.poll_one_due()
    with client_for(e) as client: replace(client, second)
    state = e.store.feed_rows('live')['main']
    assert json.loads(state['source_state']) == {'n': 1} and state['last_ok_ts'] == 10000
    if explicit_first:
        row = e.store.rows()[0]
        assert json.loads(row['source_state']) == {'n': 1} and row['last_ok_ts'] == 10000
    assert len(e.store.history('live')) == 1


def builder():
    spec = importlib.util.spec_from_file_location('brands_scope_test', ROOT / 'scripts/build-brands.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_artwork_mirror_excludes_actual_records_without_renaming():
    b = builder()
    assert b.artwork_exclusions('monero', 'Monero', 'https://example.org') == ['crypto_mining']
    assert b.artwork_exclusions('ngrok', 'ngrok', '') == ['tunnel_service']
    assert b.artwork_exclusions('neutral', 'Neutral', 'https://ngrok.com/logo') == ['tunnel_service']
    data = json.loads((ROOT / 'pulse_rings/brands.json').read_text(encoding='utf-8'))
    assert all(not b.artwork_exclusions(slug, item['title'], '') for slug, item in data.items())
    assert 'monero' not in data and 'ngrok' not in data


def real_scanner():
    source = os.environ.get('HERMES_SOURCE')
    if source: sys.path.insert(0, source)
    try:
        from tools.plugin_guard import scan_plugin
        from tools.skills_guard import scan_file, THREAT_PATTERNS
    except ImportError as exc:
        pytest.skip(f'Real Hermes admission scanner not importable; set HERMES_SOURCE: {exc}')
    return scan_plugin, scan_file, THREAT_PATTERNS


def test_artwork_mirror_matches_real_scanner_when_importable():
    _, _, patterns = real_scanner()
    b = builder()
    assert b.ARTWORK_SCOPE_PATTERNS == {pid: pattern for pattern, pid, *_ in patterns if pid in b.ARTWORK_SCOPE_PATTERNS}


def test_real_admission_scanner_brands_and_whole_shipped_tree():
    scan_plugin, scan_file, _ = real_scanner()
    assert not [f for f in scan_file(ROOT / 'pulse_rings/brands.json') if f.severity in ('high', 'critical')]
    result = scan_plugin(ROOT)
    assert result.verdict != 'dangerous', [(f.file, f.pattern_id, f.line) for f in result.findings if f.severity == 'critical']
