"""Builder 2 public contract: pure conversion/layouts and explicitly consented lookup."""
import importlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pulse_rings.spec import normalize, ValidationError
from pulse_rings.layout import layout_check
from pulse_rings.engine import Engine

ROOT = Path(__file__).resolve().parents[1]
VALUES = {
    'discord': {'invite': 'https://discord.gg/hermes'},
    'github-repo': {'repo': 'https://github.com/NousResearch/hermes-agent'},
    'github-search': {'repo': 'NousResearch/hermes-agent', 'type': 'pr'},
    'weather': {'latitude': 38.25, 'longitude': -85.76, 'city': 'Louisville'},
    'steam': {'appid': 'https://store.steampowered.com/app/730/CounterStrike_2/'},
    'json': {'url': 'https://example.org/data.json', 'metrics': {'used': '/used', 'limit': '/limit', 'cpu_pct': '/cpu_pct'}},
    'mcp': {'server': 'probe', 'tool': 'read_counts', 'metrics': {'used': '/used', 'limit': '/limit'}},
    'hermes': {},
    'notifications': {'app': 'discord'},
    'posts': {'url': 'https://example.org/feed.xml'},
    'releases': {'repo': 'NousResearch/hermes-agent'},
    'blank': {'url': 'https://example.org/counts.json', 'metrics': {'count': '/count'}},
}


def module(name):
    assert importlib.util.find_spec('pulse_rings.' + name), f'Builder 2 needs {name}'
    return importlib.import_module('pulse_rings.' + name)


def test_catalog_contract():
    t = module('templates')
    rows = t.catalog()
    assert {r['id'] for r in rows} == set(VALUES)
    assert len(rows) == 12 and 'ebay' not in json.dumps(rows).lower()
    for row in rows:
        assert set(row) == {'id', 'title', 'description', 'icon', 'kind', 'fields', 'lookup', 'test'}
        assert row['icon']['kind'] in ('brand', 'emoji', 'initials')
        assert row['title'] and row['description']
        for field in row['fields']:
            assert {'key', 'label', 'help', 'type', 'placeholder', 'required'} <= field.keys()
            assert field['type'] in ('text', 'url', 'select', 'number', 'checkbox')
    rows[0]['title'] = 'changed'
    assert t.catalog()[0]['title'] != 'changed'


@pytest.mark.parametrize('template', VALUES)
def test_template_and_all_metric_subsets_are_valid(template):
    t, presets = module('templates'), module('layout_presets')
    values = deepcopy(VALUES[template])
    out = t.from_template(template, values)
    assert out['ok'], out
    assert not out['errors'] and out['feeds'] and any(m['default_selected'] for m in out['metrics'])
    assert all(set(m) == {'ref', 'label', 'unit', 'hint', 'default_selected'} for m in out['metrics'])
    refs = [m['ref'] for m in out['metrics']]
    # All nonempty subsets, including pairs across weather and air feeds.
    for mask in range(1, 1 << len(refs)):
        selected = [ref for i, ref in enumerate(refs) if mask & (1 << i)]
        rows = presets.layouts(out['feeds'], selected, out['suggested_title'], out['suggested_icon'])
        assert 3 <= len(rows) <= 6
        assert len({r['id'] for r in rows}) == len(rows)
        for row in rows:
            assert set(row) == {'id', 'title', 'description', 'why', 'definition'}
            assert row['title'] and row['description'] and row['why']
            d = row['definition']
            assert normalize(d) == d
            assert layout_check(d)['ok']
            from pulse_rings.spec import bindings_of
            shown = {ref for path, ref in bindings_of(d) if path.endswith(('/value', '/metric'))}
            assert set(selected) <= shown
        assert presets.layouts(out['feeds'], selected, out['suggested_title'], out['suggested_icon']) == rows
    assert values == VALUES[template]


@pytest.mark.parametrize('template,values,field', [
    ('discord', {'invite': 'https://discord.gg.evil/a'}, 'invite'),
    ('github-repo', {'repo': 'https://github.com.evil/a/b'}, 'repo'),
    ('github-search', {'repo': 'a/b', 'type': 'anything'}, 'type'),
    ('weather', {'latitude': True, 'longitude': 0}, 'latitude'),
    ('weather', {'latitude': 91, 'longitude': 0}, 'latitude'),
    ('weather', {'latitude': 0, 'longitude': -181}, 'longitude'),
    ('weather', {'latitude': 0, 'longitude': 0, 'units': 'kelvin'}, 'units'),
    ('steam', {'appid': 'https://evil.example/app/730'}, 'appid'),
    ('steam', {'appid': 0}, 'appid'),
    ('json', {'url': 'http://localhost/', 'metrics': {'count': '/count'}}, 'url'),
    ('json', {'url': 'https://example.org/', 'metrics': {'count': '/bad~2'}}, 'metrics'),
    ('mcp', {'server': 'a__b', 'tool': 'read', 'metrics': {'x': '/x'}}, 'server'),
    ('mcp', {'server': 'a', 'tool': 'read', 'args': {'token': 'secret'}, 'metrics': {'x': '/x'}}, 'args'),
    ('hermes', {'scope': 'all'}, 'scope'),
    ('blank', {}, 'url'),
    ('unknown', {}, 'template'),
    ('hermes', {'secret': 'no'}, 'secret'),
])
def test_field_errors_no_partial_feeds(template, values, field):
    out = module('templates').from_template(template, values)
    assert not out['ok'] and out['feeds'] == {} and out['metrics'] == []
    assert any(e['field'] == field or e['field'].startswith(field + '.') for e in out['errors']), out


@pytest.mark.parametrize('value', ['730', 730, 'https://store.steampowered.com/app/730/', 'https://store.steampowered.com/app/730/CounterStrike_2/?snr=1'])
def test_steam_offline_forms(value):
    out = module('templates').from_template('steam', {'appid': value})
    assert out['ok'] and out['feeds']['main']['params']['url'].endswith('?appid=730')


@pytest.mark.parametrize('value', ['https://github.com/a/b/', 'a/b', 'https://github.com/a/b'])
def test_repo_offline_forms(value):
    out = module('templates').from_template('github-repo', {'repo': value})
    assert out['ok'] and out['feeds']['main']['params']['repo'] == 'a/b'


@pytest.mark.parametrize('value', ['hermes', 'https://discord.gg/hermes', 'https://discord.com/invite/hermes'])
def test_discord_offline_forms(value):
    out = module('templates').from_template('discord', {'invite': value})
    assert out['ok'] and out['feeds']['main']['params']['invite'] == 'hermes'


def test_weather_units_and_friendly_metadata():
    t = module('templates')
    imperial = t.from_template('weather', VALUES['weather'])
    metric = t.from_template('weather', {**VALUES['weather'], 'units': 'metric'})
    assert len(imperial['feeds']) == 2
    assert imperial['metrics'][0]['unit'] == '°F' and metric['metrics'][0]['unit'] == '°C'
    assert 'temperature_unit=fahrenheit' in imperial['feeds']['weather']['params']['url']
    assert 'temperature_unit=celsius' in metric['feeds']['weather']['params']['url']
    assert imperial['feeds']['air'] == metric['feeds']['air']
    assert any(m['ref'] == 'air.aqi' and m['default_selected'] for m in imperial['metrics'])


def test_smart_ranges_and_change_ring():
    t, p = module('templates'), module('layout_presets')
    out = t.from_template('json', VALUES['json'])
    rows = p.layouts(out['feeds'], ['main.used', 'main.cpu_pct'])
    items = [item for r in rows for b in r['definition']['display'] for item in b.get('rings', b.get('bars', [b]))]
    assert any(i.get('value') == 'main.used' and i.get('max') == 'main.limit' for i in items)
    assert all(i['max'] == 100 for i in items if i.get('value') == 'main.cpu_pct' and 'max' in i)
    out = t.from_template('github-search', VALUES['github-search'])
    scores = [b for r in p.layouts(out['feeds'], ['main.recent']) for b in r['definition']['display'] if b['type'] == 'score']
    assert scores and scores[0]['components'][0]['baseline'] == 'source'
    out = t.from_template('steam', VALUES['steam'])
    assert any(b.get('max') == 'usual' for r in p.layouts(out['feeds'], ['main.players']) for b in r['definition']['display'])


@pytest.mark.parametrize('refs', [[], ['bad.x'], ['main.missing'], ['main.stars'] * 9])
def test_layout_invalid_input(refs):
    out = module('templates').from_template('github-repo', VALUES['github-repo'])
    with pytest.raises(ValidationError):
        module('layout_presets').layouts(out['feeds'], refs)


@pytest.fixture
def client(tmp_path):
    spec = importlib.util.spec_from_file_location('builder2_api', ROOT / 'dashboard/plugin_api.py')
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    engine = Engine(tmp_path, clock=lambda: 10000, jitter=lambda: 0)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_pulse] = lambda: engine
    with TestClient(app) as c:
        yield c, engine


def test_pure_routes_do_not_construct_engine_or_resolve_profile():
    spec = importlib.util.spec_from_file_location('builder2_pure_api', ROOT / 'dashboard/plugin_api.py')
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    app = FastAPI()
    app.include_router(api.router)
    def forbidden():
        raise RuntimeError('Pure builder route must not resolve an Engine or start collection')
    app.dependency_overrides[api.get_pulse] = forbidden
    with TestClient(app) as c:
        assert c.get('/builder/templates').status_code == 200
        out = c.post('/builder/from-template', json={'template': 'hermes', 'values': {}}).json()
        assert out['ok']
        assert c.post('/builder/layouts', json={'feeds': out['feeds'], 'metrics': ['main.turns_running']}).status_code == 200


def test_documented_responses_match_real_routes(client):
    c, _ = client
    examples = json.loads((ROOT / 'submission/BUILDER-2-API-EXAMPLES.json').read_text(encoding='utf-8'))
    for route, example in examples.items():
        method, path = route.split(' ')
        response = c.get(path) if method == 'GET' else c.post(path, json=example['request'])
        assert response.status_code == 200 and response.json() == example['response']


def test_routes_and_no_persistence(client):
    c, e = client
    assert c.get('/builder/templates').status_code == 200
    out = c.post('/builder/from-template', json={'template': 'github-repo', 'values': VALUES['github-repo']})
    assert out.status_code == 200 and out.json()['ok']
    result = c.post('/builder/layouts', json={'feeds': out.json()['feeds'], 'metrics': ['main.stars']})
    assert result.status_code == 200 and len(result.json()) >= 3
    assert result.headers['cache-control'] == 'no-store'
    assert c.post('/builder/layouts', json={'feeds': {}, 'metrics': []}).status_code == 400
    assert c.post('/builder/from-template', json={'template': 'hermes', 'values': {}, 'confirm': True}).status_code == 422
    assert not e.store.rows() and not e.status(poll=False)['drafts']


def test_lookup_consent_rate_fixed_host_results_no_store(client, monkeypatch):
    c, e = client
    m = module('builder_lookup')
    monkeypatch.setattr(m, '_RECENT', {})
    calls = []
    def fetch(url, host, target, **kwargs):
        calls.append((url, host, target, kwargs))
        if host == 'geocoding-api.open-meteo.com':
            return {'results': [{'name': 'Louisville', 'admin1': 'Kentucky', 'country': 'US', 'latitude': 38.2527, 'longitude': -85.7585}] * 10}
        return {'total': 1, 'items': [{'id': 730, 'name': 'Counter-Strike 2', 'tiny_image': 'https://evil.example/unused'}]}
    monkeypatch.setattr(m, '_fetch', fetch)
    for confirm in [False, 1, 'true', None]:
        assert c.post('/builder/lookup', json={'kind': 'city', 'q': 'Louisville', 'confirm': confirm}).status_code in (400, 422)
    assert not calls
    out = c.post('/builder/lookup', json={'kind': 'city', 'q': 'Louisville', 'confirm': True})
    assert out.status_code == 200, out.text
    assert out.headers['cache-control'] == 'no-store'
    assert out.json() == {'results': [{'name': 'Louisville', 'admin1': 'Kentucky', 'country': 'US', 'latitude': 38.25, 'longitude': -85.76}] * 8, 'calls': 1, 'persisted': False}
    assert c.post('/builder/lookup', json={'kind': 'city', 'q': 'Other', 'confirm': True}).status_code == 429
    out = c.post('/builder/lookup', json={'kind': 'steam', 'q': 'Counter Strike', 'confirm': True})
    assert out.json()['results'] == [{'name': 'Counter-Strike 2', 'appid': 730}]
    assert len(calls) == 2 and calls[0][1] == 'geocoding-api.open-meteo.com' and calls[1][1] == 'store.steampowered.com'
    assert all(call[3]['timeout'] == 3 for call in calls)
    assert parse_qs(urlsplit(calls[1][0]).query) == {'term': ['Counter Strike'], 'cc': ['us'], 'l': ['english']}
    assert not e.store.rows() and not e.status(poll=False)['drafts']


@pytest.mark.parametrize('q', ['', 'x' * 101, 'bad\nquery'])
def test_lookup_query_validation(client, monkeypatch, q):
    m = module('builder_lookup')
    monkeypatch.setattr(m, '_fetch', lambda *a, **k: pytest.fail('must not fetch'))
    c, _ = client
    assert c.post('/builder/lookup', json={'kind': 'steam', 'q': q, 'confirm': True}).status_code in (400, 422)


def test_lookup_timeout_sanitization_and_boundary(monkeypatch, tmp_path):
    m = module('builder_lookup')
    monkeypatch.setattr(m, '_RECENT', {})
    calls = []
    def fail(*a, **k):
        calls.append(1)
        raise TimeoutError('secret https://private.example?q=secret')
    with pytest.raises(m.LookupError) as exc:
        m.lookup(tmp_path, 'city', 'Town', True, fetch=fail, clock=lambda: 0)
    assert 'secret' not in str(exc.value) and exc.value.status == 503
    with pytest.raises(m.LookupError) as exc:
        m.lookup(tmp_path, 'city', 'Town', True, fetch=fail, clock=lambda: 2.99)
    assert exc.value.status == 429 and len(calls) == 1
    assert m.lookup(tmp_path, 'city', 'Town', True, fetch=lambda *a, **k: {}, clock=lambda: 3)['results'] == []
    assert list(tmp_path.iterdir()) == []


def test_lookup_transport_refuses_redirect(monkeypatch, tmp_path):
    m = module('builder_lookup')
    transport = importlib.import_module('pulse_rings.sources.http_json')
    from pulse_rings.sources.base import SourceError
    calls = []
    def refusing(url, host, target, **kwargs):
        calls.append((url, host, target, kwargs))
        raise SourceError('redirect to https://secret.example rejected', 302)
    monkeypatch.setattr(transport, '_fetch', refusing)
    monkeypatch.setattr(m, '_RECENT', {})
    # Exercise the lookup's production safe transport adapter, not its injected fetch seam.
    with pytest.raises(m.LookupError) as exc:
        m.lookup(tmp_path, 'steam', 'https://evil.example/?x=1', True)
    assert len(calls) == 1 and calls[0][1] == 'store.steampowered.com'
    assert calls[0][2].startswith('/api/storesearch/?term=https%3A')
    assert exc.value.status == 503 and 'secret' not in str(exc.value)


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
def test_lookup_real_transport_redirect_response(monkeypatch, tmp_path, status):
    import socket
    from test_http_json import fake_http
    from pulse_rings.sources import http_json as h
    m = module('builder_lookup')
    monkeypatch.setattr(m, '_RECENT', {})
    hosts = []
    def address(host, deadline):
        import time
        hosts.append(host)
        assert 0 < deadline - time.monotonic() <= 3
        return socket.AF_INET, ('93.184.216.34', 443)
    monkeypatch.setattr(h, '_vetted_address', address)
    seen = fake_http(monkeypatch, b'private', status, {'Location': 'https://private.example/secret'})
    with pytest.raises(m.LookupError) as exc:
        m.lookup(tmp_path, 'city', 'Town', True)
    assert exc.value.status == 503 and 'private' not in str(exc.value)
    assert hosts == ['geocoding-api.open-meteo.com'] and len(seen) == 1
    assert seen[0]['host'] == 'geocoding-api.open-meteo.com' and seen[0]['closed']
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('kind,payload', [
    ('city', {'results': [None, {'name': 'Bad', 'latitude': True, 'longitude': 0}, {'name': 'Bad', 'latitude': 900, 'longitude': 0}, {'name': 'Fine\u0000', 'latitude': 1.234, 'longitude': 2.345, 'secret': 'omitted'}]}),
    ('steam', {'items': [None, {'name': 'Bad', 'id': True}, {'name': 'Bad', 'id': -1}, {'name': 'Fine\u0000', 'id': 42, 'secret': 'omitted'}]}),
])
def test_lookup_result_projection(monkeypatch, tmp_path, kind, payload):
    m = module('builder_lookup')
    monkeypatch.setattr(m, '_RECENT', {})
    out = m.lookup(tmp_path, kind, 'query', True, fetch=lambda *a, **k: payload)
    assert len(out['results']) == 1 and out['results'][0]['name'] == 'Fine'
    assert 'secret' not in json.dumps(out) and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('q', ['730', 'https://store.steampowered.com/app/730/'])
def test_lookup_offline_appid_does_not_consume_rate(monkeypatch, tmp_path, q):
    m = module('builder_lookup')
    monkeypatch.setattr(m, '_RECENT', {})
    out = m.lookup(tmp_path, 'steam', q, True, fetch=lambda *a, **k: pytest.fail('offline app ID'))
    assert out == {'results': [{'name': 'Steam app 730', 'appid': 730}], 'calls': 0, 'persisted': False}
    assert m._RECENT == {}


@pytest.mark.parametrize('count', [1, 2, 3, 4, 5, 6, 7, 8])
def test_layout_binding_ceiling_and_all_refs_preserved(count):
    feeds = {name: {'kind': 'http_json', 'params': {'url': 'https://example.org/' + name, 'metrics': {
        'used': '/used', 'limit': '/limit', 'cpu_pct': '/cpu_pct', 'temperature': '/temperature'}}} for name in ('one', 'two')}
    refs = [f'{name}.{metric}' for name in feeds for metric in feeds[name]['params']['metrics']][:count]
    for row in module('layout_presets').layouts(feeds, refs):
        from pulse_rings.spec import bindings_of
        d = row['definition']
        assert normalize(d) == d and layout_check(d)['ok']
        assert len(bindings_of(d)) <= 8
        assert set(refs) <= {ref for path, ref in bindings_of(d) if path.endswith(('/value', '/metric'))}


def test_limit_only_still_has_default_selection_and_pointer_percent_hint():
    t = module('templates')
    out = t.from_template('json', {'url': 'https://example.org/', 'metrics': {'limit': '/limit'}})
    assert out['ok'] and out['metrics'][0]['default_selected']
    out = t.from_template('json', {'url': 'https://example.org/', 'metrics': {'cpu': '/cpu_pct'}})
    assert out['metrics'][0]['hint'] == 'percent' and out['metrics'][0]['unit'] == '%'


@pytest.mark.parametrize('template,key,value', [
    ('github-repo', 'repo', 'https://github.com/a/\nb'),
    ('github-repo', 'repo', 'https://github.com/a/b//'),
    ('steam', 'appid', 'https://store.steampowered.com/app/7\n30/'),
    ('discord', 'invite', 'https://discord.gg/her\nmes'),
])
def test_offline_links_never_repair_malformed_tokens(template, key, value):
    out = module('templates').from_template(template, {key: value})
    assert not out['ok'] and any(e['field'] == key for e in out['errors'])
