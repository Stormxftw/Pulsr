"""http_json QA: recorded public shapes and hostile boundaries, no live requests."""
import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from pulse_rings import builder_lookup, templates
from pulse_rings.display import compute_display
from pulse_rings.layout_presets import layouts
from pulse_rings.sources import http_json as h
from pulse_rings.sources.base import SourceError
from pulse_rings.spec import normalize

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/qa-json.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('value,signed', [(-0.3, True), (0.3, True), (-0.3, False)])
def test_weather_rounding_does_not_show_signed_zero(value, signed):
    from pulse_rings.display import _text
    assert _text(value, '°F', signed=signed, decimals=0) == '0 °F'


class Gate:
    def call(self, host, callback):
        return callback()


def definition():
    return {'source': {'kind': 'http_json', 'params': {'url': 'https://example.org/data', 'metrics': {'value': '/value'}}}}


@pytest.mark.parametrize('query,expected', [
    ({'temperature_unit': 'fahrenheit'}, ['°F', 'km/h', 'mm']),
    ({'wind_speed_unit': 'mph', 'precipitation_unit': 'inch'}, ['°C', 'mph', 'in']),
    ({'wind_speed_unit': 'ms'}, ['°C', 'm/s', 'mm']),
    ({'wind_speed_unit': 'kn'}, ['°C', 'kn', 'mm']),
])
def test_open_meteo_units_are_independent(query, expected):
    feed = {'kind': 'http_json', 'params': {'url': 'https://api.open-meteo.com/v1/forecast?' + urlencode(query),
            'metrics': {'temp': '/current/temperature_2m', 'wind': '/current/wind_speed_10m', 'rain': '/current/precipitation'}}}
    assert [m['unit'] for m in templates.metrics_for({'weather': feed})] == expected


@pytest.mark.parametrize('status,fragment', [(301, 'redirect'), (302, 'redirect'), (307, 'redirect'), (308, 'redirect'), (404, 'not found'), (429, 'rate limited')])
def test_safe_actionable_poll_error(monkeypatch, status, fragment):
    def refused(*args, **kwargs):
        raise SourceError('secret upstream https://private.invalid', status, 123)
    monkeypatch.setattr(h, '_fetch', refused)
    with pytest.raises(SourceError) as error:
        h.HttpJsonSource().poll(definition(), None, {}, now=1, net=Gate())
    assert fragment in str(error.value).lower()
    assert 'secret' not in str(error.value) and 'https://' not in str(error.value)
    assert error.value.status == status and error.value.retry_after == 123


def test_transport_rejects_valid_json_in_truncated_content_length(monkeypatch):
    raw = b'{"value":12}'
    class Socket:
        def settimeout(self, value):
            pass
    class Connection:
        def __init__(self, *args, **kwargs):
            self.sock = Socket()
        def request(self, *args, **kwargs):
            pass
        def getresponse(self):
            # Real HTTPResponse.read1 semantics, including premature EOF.
            response = h.http.client.HTTPResponse(SimpleNamespace(makefile=lambda *a: io.BytesIO(
                b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 99\r\n\r\n' + raw)))
            response.begin()
            return response
        def close(self):
            pass
    monkeypatch.setattr(h, '_vetted_address', lambda *a: None)
    monkeypatch.setattr(h, '_PinnedHTTPSConnection', Connection)
    with pytest.raises(SourceError, match='incomplete'):
        h._fetch('https://example.org/data', 'example.org', '/data', now=1)


def test_lookup_steam_excludes_non_app_ids(tmp_path):
    result = builder_lookup.lookup(tmp_path, 'steam', 'Game name', True, fetch=lambda *a, **k: {'items': [
        {'type': 'bundle', 'id': 730, 'name': 'Bundle, not an app'},
        {'type': 'sub', 'id': 730, 'name': 'Package, not an app'},
        {'type': 'app', 'id': 730, 'name': 'Counter-Strike 2'}]})
    assert result['results'] == [{'name': 'Counter-Strike 2', 'appid': 730}]


@pytest.mark.parametrize('body,pointer,expected', [
    ({'a/b': {'~x': [0, 1e200]}}, '/a~1b/~0x/0', 0),
    ({'a/b': {'~x': [0, 1e200]}}, '/a~1b/~0x/1', 1e200),
    ({'x': ['12', True, None]}, '/x/0', None),
    ({'x': ['12', True, None]}, '/x/1', None),
    ({'x': ['12', True, None]}, '/x/2/nested', None),
    ({'x': [5]}, '/x/01', None), ({'x': [5]}, '/x/-1', None),
    ({'x': [5]}, '/x/99999999999999999999', None), (0, '', 0),
])
def test_numeric_pointer_edges(monkeypatch, body, pointer, expected):
    d = definition()
    d['source']['params']['metrics']['value'] = pointer
    monkeypatch.setattr(h, '_fetch', lambda *a, **k: body)
    sample = h.HttpJsonSource().poll(d, None, {}, now=1, net=Gate()).sample
    assert sample['metrics']['value'] == expected
    assert ('value' in sample['unknown_reasons']) == (expected is None)


def test_recorded_weather_demo_measurements_and_default_region(monkeypatch):
    d = normalize(dict(pulse=1, **FIXTURE['definitions'][0]))
    feeds = {}
    for name, f in d['feeds'].items():
        monkeypatch.setattr(h, '_fetch', lambda *a, _body=FIXTURE[name], **k: _body)
        sample = h.HttpJsonSource().poll({'source': f}, None, {}, now=10000, net=Gate()).sample
        feeds[name] = {'current': sample, 'history': []}
    rows = compute_display(d, feeds)
    assert rows[0]['value_text'] == '48 °F'
    assert [i['value_text'] for i in rows[1]['items']] == ['5.7 mph', '0 in', '37']
    weather = templates.from_template('weather', {'latitude': 38.25, 'longitude': -85.76})
    assert [m['unit'] for m in weather['metrics']] == ['°F', 'mph', 'in', '', 'µg/m³']
    assert 'temperature_unit=fahrenheit' in weather['feeds']['weather']['params']['url']
    feeds['air']['current']['metrics']['aqi'] = None
    unknown = compute_display(d, feeds)[1]['items'][2]
    assert unknown['unknown'] and unknown['value_text'] is None and unknown['fill'] is None


def test_recorded_steam_usual_learning_zero_and_large_number(monkeypatch):
    d = normalize(dict(pulse=1, **FIXTURE['definitions'][1]))
    monkeypatch.setattr(h, '_fetch', lambda *a, **k: FIXTURE['steam'])
    sample = h.HttpJsonSource().poll(d, None, {}, now=10000, net=Gate()).sample
    feed = {'current': sample, 'history': []}
    rows = compute_display(d, {'main': feed})
    assert rows[0]['value_text'] == '459,907'
    assert rows[1]['items'][0]['learning'] and rows[1]['items'][0]['fill'] is None
    feed['history'] = [{'ts': 6000, 'metrics': {'players': 0}}]
    assert compute_display(d, {'main': feed})[1]['items'][0]['learning']
    feed['history'] = [{'ts': 6000, 'metrics': {'players': 500000}}]
    item = compute_display(d, {'main': feed})[1]['items'][0]
    assert item['caption'] == '92% of usual' and item['max'] == 1000000


@pytest.mark.parametrize('template,values', [('weather', {'latitude': 38.25, 'longitude': -85.76}),
    ('steam', {'appid': 'https://store.steampowered.com/app/730/', 'name': 'Counter-Strike 2'}),
    ('json', {'url': 'https://example.org/counts', 'metrics': {'active': '/data/0/active', 'total': '/total'}})])
def test_template_recommendations_keep_selected_refs(template, values):
    result = templates.from_template(template, values)
    assert result['ok']
    refs = [m['ref'] for m in result['metrics'] if m['default_selected']]
    for layout in layouts(result['feeds'], refs, result['suggested_title'], result['suggested_icon']):
        from pulse_rings.builder import sample_preview
        out = sample_preview(layout['definition'])
        assert out['ok'] and out['display']
        assert not any(s in json.dumps(out['display']) for s in ['NaN', 'undefined', '[object Object]'])


def test_lookup_requires_literal_click_confirmation_and_recorded_shapes(tmp_path):
    calls = []
    def fetch(*args, **kwargs):
        calls.append(args[1])
        return FIXTURE['city'] if args[1].startswith('geocoding') else FIXTURE['store']
    for confirm in (False, None, 'true', 1):
        with pytest.raises(builder_lookup.LookupError):
            builder_lookup.lookup(tmp_path, 'city', 'Louisville', confirm, fetch=fetch)
    assert not calls
    city = builder_lookup.lookup(tmp_path, 'city', 'Louisville', True, fetch=fetch)
    assert city['results'][0]['latitude'] == 38.25 and city['calls'] == 1 and city['persisted'] is False
    steam = builder_lookup.lookup(tmp_path, 'steam', 'Counter-Strike 2', True, fetch=fetch)
    assert steam['results'][0] == {'name': 'Counter-Strike 2', 'appid': 730}
    assert len(calls) == 2
    offline = builder_lookup.lookup(tmp_path, 'steam', '730', True, fetch=fetch)
    assert offline['calls'] == 0 and len(calls) == 2
