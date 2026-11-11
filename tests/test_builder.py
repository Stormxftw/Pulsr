"""Builder boundaries are offline except the explicitly consented single call."""
import importlib.util
import json
from contextlib import nullcontext
from contextvars import copy_context
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pulse_rings.engine import Engine
from pulse_rings import mcp_access

ROOT = Path(__file__).resolve().parents[1]


def definition():
    return {'pulse': 1, 'title': 'Builder', 'feeds': {'main': {'kind': 'mcp.tool', 'params': {
        'server': 'probe', 'tool': 'read_counts', 'args': {}, 'metrics': {'used': '/used', 'limit': '/limit'}}}},
        'display': [{'type': 'bar', 'value': 'main.used', 'max': 'main.limit'}]}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('builder_test_api', ROOT / 'dashboard/plugin_api.py')
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    engine = Engine(tmp_path, clock=lambda: 10000, jitter=lambda: 0)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_pulse] = lambda: engine
    calls = []
    flags = {'connected': True, 'exists': True, 'read_only': True, 'requires_approval': False}
    ctx = SimpleNamespace(tool_info=lambda name: flags, list_tools=lambda: ['mcp__probe__read_counts'],
                          call_mcp=lambda server, tool, args, *, timeout: calls.append((server, tool, args, timeout)) or {'ok': True, 'result': {'used': 42, 'limit': 500, 'a/b': {'~': [1.5, True, '7', None]}}})
    monkeypatch.setitem(mcp_access._BINDINGS, str(tmp_path.resolve()), (ctx, copy_context(), str(tmp_path)))
    monkeypatch.setattr(mcp_access, 'unattended_scope', nullcontext)
    monkeypatch.setattr(mcp_access, 'server_granted', lambda server: True, raising=False)
    with TestClient(app) as client:
        yield client, engine, calls, flags, ctx


def test_layout_check_normalized_budget_errors_yaml_and_no_persistence(setup):
    c, e, calls, *_ = setup
    out = c.post('/layout-check', json={'definition': definition()}).json()
    assert out['ok'] and out['normalized']['display'][0]['min'] == 0
    assert out['budget']['req_per_hour'] == 4 and 'pulse: 1' in out['yaml']
    out = c.post('/layout-check', json={'definition': out['yaml']}).json()
    assert out['ok']
    d = definition(); d['display'][0]['value'] = 'wrong.used'
    out = c.post('/layout-check', json={'definition': d}).json()
    assert not out['ok'] and out['errors'][0]['path'] == '/display/0/value'
    assert c.post('/layout-check', json={'definition': '!!python/object:bad {}'}).json()['ok'] is False
    assert not calls and not e.store.rows() and not e.status(poll=False)['drafts']


@pytest.mark.parametrize('state', ['measured', 'learning', 'unknown', 'over', 'under', 'stale', 'degraded'])
def test_preview_seeded_real_display_no_io(setup, state):
    from pulse_rings.display import compute_display
    c, e, calls, *_ = setup
    body = {'definition': definition(), 'mode': 'sample', 'state': state, 'seed': 13}
    out = c.post('/builder/preview', json=body).json()
    assert out['sample'] is True and out['display']
    assert c.post('/builder/preview', json=body).json() == out
    assert out['display'] == compute_display(out['definition'], out['synthetic_feeds'])
    item = out['display'][0]['items'][0]
    if state in ('unknown', 'degraded'):
        assert item['unknown'] and item['fill'] is None
    if state in ('over', 'under'):
        assert item[state]
    assert not calls and not e.store.rows() and not e.status(poll=False)['drafts']


@pytest.mark.parametrize('body', [{'mode': 'cached'}, {'mode': 'sample', 'state': 'garbage'}, {'seed': True}, {'seed': '4'}])
def test_preview_strict_modes(setup, body):
    c, *_ = setup
    assert c.post('/builder/preview', json={'definition': definition(), **body}).status_code == 422


def test_brand_search_bounded_offline(setup):
    c, _, calls, *_ = setup
    rows = c.get('/brands?q=github').json()['brands']
    assert any(b['slug'] == 'github' and b['path'].startswith('M') for b in rows)
    assert 0 < len(c.get('/brands').json()['brands']) <= 20
    assert c.get('/brands?q=' + 'x' * 101).status_code == 422
    assert not calls


def test_mcp_inventory_refusal_and_exactly_one_consented_call(setup):
    c, e, calls, flags, _ = setup
    assert c.get('/builder/mcp-tools').json()['tools'][0]['read_only'] is True
    body = {'server': 'probe', 'tool': 'read_counts', 'args': {}, 'confirm': True}
    for confirm in [False, 'true', 1, None]:
        assert c.post('/builder/mcp-test-call', json={**body, 'confirm': confirm}).status_code in (400, 422)
    assert not calls
    out = c.post('/builder/mcp-test-call', json=body)
    assert out.status_code == 200, out.text
    assert out.json()['body']['used'] == 42
    assert out.json()['numeric'] == [{'pointer': '/used', 'value': 42}, {'pointer': '/limit', 'value': 500},
                                      {'pointer': '/a~1b/~0/0', 'value': 1.5}]
    assert calls == [('probe', 'read_counts', {}, 8)]
    assert c.post('/builder/mcp-test-call', json=body).status_code == 429
    assert len(calls) == 1
    flags['read_only'] = False
    inv = c.get('/builder/mcp-tools').json()['tools'][0]
    assert not inv['read_only'] and 'read-only' in inv['reason']
    assert c.post('/builder/mcp-test-call', json=body).status_code == 403
    assert len(calls) == 1 and not e.store.rows() and not e.status(poll=False)['drafts']


@pytest.mark.parametrize('field,value', [('server', 'bad__server'), ('tool', ' bad'), ('args', {'token': 'secret'})])
def test_test_call_validates_before_dispatch(setup, field, value):
    c, _, calls, *_ = setup
    body = {'server': 'probe', 'tool': 'read_counts', 'args': {}, 'confirm': True, field: value}
    assert c.post('/builder/mcp-test-call', json=body).status_code in (400, 422)
    assert not calls


def test_no_binding_fails_closed(setup, monkeypatch):
    c, e, calls, *_ = setup
    monkeypatch.delitem(mcp_access._BINDINGS, str(e.store.root.resolve()))
    assert c.get('/builder/mcp-tools').json()['tools'] == []
    assert c.post('/builder/mcp-test-call', json={'server': 'probe', 'tool': 'read_counts', 'args': {}, 'confirm': True}).status_code == 503
    assert not calls


def test_truncated_body_cannot_bind_invisible_numbers(setup):
    c, _, calls, _, ctx = setup
    ctx.call_mcp = lambda *a, **kw: calls.append(a) or {'ok': True, 'result': '{partial', 'truncated': True}
    out = c.post('/builder/mcp-test-call', json={'server': 'probe', 'tool': 'read_counts', 'args': {}, 'confirm': True}).json()
    assert out['truncated'] and len(out['text'].encode()) <= 65536
    assert out['body'] is None and out['numeric'] == [] and len(calls) == 1


@pytest.mark.parametrize('seed', range(8))
def test_samples_count_defaults_and_stable_denominators(seed):
    from pulse_rings.builder import sample_preview
    d = definition()
    d['feeds']['main']['params']['metrics'].update({'stars': '/stars', 'star_limit': '/star_limit',
                                                  'ratio': '/ratio', 'memory': '/memory_gb'})
    out = sample_preview(d, seed=seed)
    f = out['synthetic_feeds']['main']
    samples = [*f['history'], f['current']]
    for sample in samples:
        m = sample['metrics']
        assert all(type(m[k]) is int for k in ('used', 'limit', 'stars', 'star_limit'))
        assert m['limit'] > m['used'] and m['star_limit'] > m['stars']
        assert 0 <= m['ratio'] <= 1
    assert len({s['metrics']['limit'] for s in samples}) == 1
    assert len({s['metrics']['star_limit'] for s in samples}) == 1
    assert any(not s['metrics']['memory'].is_integer() for s in samples)
    assert sample_preview(d, seed=seed) == out


@pytest.mark.parametrize('metric,pointer,unit,fractional', [
    ('mystery', '/events', '', False), ('enumerated', '/events', '', False),
    ('temperature', '/temperature', '', True), ('errorRate', '/errors', '', True),
    ('value', '/value', '%', True), ('value', '/memory_gb', '', True),
    ('value', '/value', 'GB', True), ('percent', '/percent', '', True),
])
def test_sample_precision_heuristic(metric, pointer, unit, fractional):
    from pulse_rings.builder import sample_preview
    d = definition()
    d['feeds']['main']['params']['metrics'] = {metric: pointer}
    d['display'] = [{'type': 'stat', 'value': 'main.' + metric, 'unit': unit}]
    out = sample_preview(d, seed=7)
    values = [s['metrics'][metric] for s in out['synthetic_feeds']['main']['history']]
    assert any(type(v) is float and not v.is_integer() for v in values) == fractional
    if not fractional:
        assert all(type(v) is int for v in values)


@pytest.mark.parametrize('state', ['over', 'under'])
def test_count_scenarios_remain_integer(state):
    from pulse_rings.builder import sample_preview
    d = definition()
    d['display'][0]['max'] = 101
    d['display'][0]['min'] = 1.5
    out = sample_preview(d, state=state)
    assert type(out['synthetic_feeds']['main']['current']['metrics']['used']) is int
    assert out['display'][0]['items'][0][state]


def test_pure_sample_icons_seed_and_input_integrity():
    from copy import deepcopy
    import random
    from pulse_rings.builder import sample_preview
    d = definition()
    original = deepcopy(d)
    before = random.getstate()
    a = sample_preview(d, seed=5)
    b = sample_preview(d, seed=6)
    assert d == original and before == random.getstate()
    assert a['synthetic_feeds'] != b['synthetic_feeds']
    metrics = a['synthetic_feeds']['main']['current']['metrics']
    assert 0 < metrics['used'] < metrics['limit']
    for icon, kind in [({'brand': 'github'}, 'brand'), ({'emoji': '🦙'}, 'emoji'), ('initials', 'initials'), ('hermes', 'brand')]:
        d['icon'] = icon
        assert sample_preview(d)['icon_resolved']['kind'] == kind


@pytest.mark.parametrize('change', [{'connected': False}, {'exists': False}, {'requires_approval': True}])
def test_policy_all_refusal_branches_no_dispatch(setup, change):
    c, e, calls, flags, _ = setup
    flags.update(change)
    out = c.post('/builder/mcp-test-call', json={'server': 'probe', 'tool': 'read_counts', 'args': {}, 'confirm': True})
    assert out.status_code == 403 and not calls
    assert not e.store.rows() and not e.status(poll=False)['drafts']


def test_decode_failure_is_static_no_private_output(setup):
    c, e, calls, _, ctx = setup
    ctx.call_mcp = lambda *a, **kw: calls.append(a) or 'private not-json payload'
    out = c.post('/builder/mcp-test-call', json={'server': 'probe', 'tool': 'read_counts', 'args': {}, 'confirm': True})
    assert out.status_code == 502 and 'private' not in out.text and len(calls) == 1
    assert not e.store.rows()


def test_timeout_keeps_inflight_late_result_discarded(setup, monkeypatch):
    import threading
    import time
    from pulse_rings.sources import mcp
    c, e, calls, _, ctx = setup
    release, done = threading.Event(), threading.Event()
    monkeypatch.setattr(mcp, 'TIMEOUT', .03)
    def dispatch(*a, **kw):
        calls.append(a)
        release.wait(2)
        done.set()
        return {'ok': True, 'result': {'private_late_number': 123}}
    ctx.call_mcp = dispatch
    body = {'server': 'probe', 'tool': 'read_counts', 'args': {}, 'confirm': True}
    try:
        out = c.post('/builder/mcp-test-call', json=body)
        assert out.status_code == 504 and 'private' not in out.text
        assert len(calls) == 1 and any(k[0] == str(e.store.root.resolve()) for k in mcp._INFLIGHT)
        assert c.post('/builder/mcp-test-call', json=body).status_code == 429
    finally:
        release.set()
        assert done.wait(2)
    deadline = time.monotonic() + 2
    while any(k[0] == str(e.store.root.resolve()) for k in mcp._INFLIGHT) and time.monotonic() < deadline:
        time.sleep(.005)
    assert not any(k[0] == str(e.store.root.resolve()) for k in mcp._INFLIGHT)
    assert not e.store.rows() and not e.status(poll=False)['drafts']


def test_inspection_outputs_no_store_and_strict_extra_fields(setup):
    c, _, calls, *_ = setup
    for route, body in [('/layout-check', {'definition': definition()}), ('/builder/preview', {'definition': definition()})]:
        assert c.post(route, json=body).headers['cache-control'] == 'no-store'
        assert c.post(route, json={**body, 'confirm': True}).status_code == 422
    assert c.get('/builder/mcp-tools').headers['cache-control'] == 'no-store'
    assert not calls
