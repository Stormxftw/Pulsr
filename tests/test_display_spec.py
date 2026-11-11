"""Offline display extension contract, including legacy normalization capture."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from test_spec import ROOT, minimal
from pulse_rings import spec


def definitions():
    """Find actual pulse definitions, including those nested in status fixtures."""
    found = {}
    def walk(node, key):
        if isinstance(node, dict):
            if node.get('pulse') == 1 and not spec.validate(node):
                found[key] = node
            for name, value in node.items():
                walk(value, key + '/' + str(name))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, key + '/' + str(index))
    paths = sorted((ROOT / 'examples').glob('*.yaml')) + sorted((ROOT / 'tests/fixtures').rglob('*'))
    for path in paths:
        if path.name == 'display-backcompat.json' or path.suffix not in ('.json', '.yaml', '.yml'):
            continue
        try:
            node = spec.parse(path.read_bytes()) if path.suffix != '.json' else json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, spec.ValidationError):
            continue
        walk(node, path.relative_to(ROOT).as_posix())
    return found


def draft(block=None, count=1):
    feed = {'kind': 'http_json', 'params': {'url': 'https://api.example.com/data',
            'metrics': {'used': '/used', 'limit': '/limit', 'late_orders': '/late'}}}
    return {'pulse': 1, 'title': 'Display test', 'feeds': {name: deepcopy(feed) for name in ['a', 'b', 'c'][:count]},
            'display': [deepcopy(block or {'type': 'bar', 'value': 'used'})]}


BLOCKS = [
    {'type': 'score', 'components': [{'metric': 'used', 'type': 'delta', 'weight': 100}]},
    {'type': 'rings', 'rings': [{'value': 'used'}]},
    {'type': 'bar', 'value': 'used'},
    {'type': 'bars', 'bars': [{'value': 'used'}, {'value': 'limit'}]},
    {'type': 'stat', 'value': 'used'},
    {'type': 'spark', 'value': 'used'},
]


def changed(path, value, base=None):
    out = deepcopy(base or draft())
    node = out
    parts = path.strip('/').split('/')
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    if isinstance(node, list):
        node[int(parts[-1])] = value
    else:
        node[parts[-1]] = value
    return out


INVALID = []

def bad(path, value, base=None, error=None):
    INVALID.append((changed(path, value, base), path if error is None else error))


for key, value in [('feeds', {}), ('feeds', []), ('feeds', {str(i): {} for i in range(4)}),
                   ('display', []), ('display', {}), ('display', BLOCKS[:5])]:
    bad('/' + key, value)
for key in ['every', 'ring', 'capsule', 'lines']:
    bad('/' + key, {'every': '10m', 'ring': {}, 'capsule': {}, 'lines': []}[key])
bad('/source', minimal()['source'], error='')
missing_display = draft(); del missing_display['display']
INVALID.append((missing_display, '/display'))
bad('/feeds', {'Bad': draft()['feeds']['a']}, error='/feeds/Bad')
for key, value in [('every', '299s'), ('every', 300), ('kind', 'unknown'), ('params', []), ('typo', 1)]:
    bad('/feeds/a/' + key, value)
bad('/feeds/a/params/url', 'http://example.com')
for value in ['missing.used', 'a.nope', 'a.used + 1', 1, None, {}, 'a.used.extra']:
    bad('/display/0/value', value)
bad('/display/0/value', 'used', draft(count=2))
for key, values in {'min': [True, {}, 'usual', 'a.nope', 'a.used'],
                    'max': [False, [], 'bogus', 'a.used'],
                    'auto_window': ['3599s', '604801s', '8d', 3600],
                    'label': ['x' * 41, 1, 'bad\nlabel'], 'unit': ['x' * 9, 1, 'bad\n'],
                    'zones': [{}, {'warn': 1, 'crit': 1}, {'warn': 2, 'crit': 1},
                              {'warn': 1, 'crit': 2, 'direction': 'down'}, {'warn': True}, {'crit': 'x'},
                              {'warn': 1, 'direction': 'sideways'}, {'warn': 1, 'typo': 1}],
                    'typo': [1]}.items():
    for value in values:
        error = '/display/0/' + key
        if key == 'zones' and isinstance(value, dict):
            if 'typo' in value: error += '/typo'
            elif value.get('direction') == 'sideways': error += '/direction'
            elif type(value.get('warn')) is bool: error += '/warn'
            elif isinstance(value.get('crit'), str): error += '/crit'
            elif 'warn' in value and 'crit' in value: error += '/crit'
        bad('/display/0/' + key, value, error=error)
for lo, hi in [(2, 2), (3, 2), (1, 'usual'), ('auto', 'usual')]:
    bad('/display/0/max', hi, changed('/display/0/min', lo))
for block in BLOCKS:
    base = draft(block)
    bad('/display/0/typo', 1, base)
    bad('/display/0/style', {'typo': 1}, base, '/display/0/style/typo')
    bad('/display/0/label', 'x' * 41, base)
    bad('/display/0/type', 'unknown', base)
for block_type, field, counts in [('rings', 'rings', [0, 4]), ('bars', 'bars', [0, 1, 4])]:
    for count in counts:
        bad('/display/0/' + field, [{'value': 'used'}] * count, draft({'type': block_type, field: []}))
    for key in ['min', 'max', 'auto_window']:
        bad('/display/0/bars/0/' + key, 0 if key == 'min' else 'auto' if key == 'max' else '7d',
            draft(BLOCKS[3]), '/display/0/bars/0')
        bad('/display/0/' + key, 0 if key == 'min' else 'auto' if key == 'max' else '7d',
            draft(dict(BLOCKS[3], scale='independent')))
for key, values in [('decimals', [-1, 4, True, 1.5]), ('show', ['bad', 1]), ('delta_vs', ['bad', False])]:
    for value in values: bad('/display/0/' + key, value, draft(BLOCKS[4]))
for value in [7, 49, True, 8.5, '24']:
    bad('/display/0/points', value, draft(BLOCKS[5]))
for value in [[], [{'metric': 'used', 'type': 'delta', 'weight': 20}] * 5,
              [{'metric': 'used', 'type': 'delta', 'weight': 90}]]:
    bad('/display/0/components', value, draft(BLOCKS[0]))
bad('/display/0/components/0/baseline', 'source', draft(BLOCKS[0]))
bad('/display/0/components', [{'metric': 'a.used', 'type': 'level', 'weight': 50, 'full_at': 1},
                             {'metric': 'b.used', 'type': 'level', 'weight': 50, 'full_at': 1}],
    draft(BLOCKS[0], count=2))
# Nine display bindings (three values + six bounds) exceed the global limit.
bad('/display', [{'type': 'rings', 'rings': [{'value': 'used', 'min': 'a.limit', 'max': 'a.late_orders'}] * 3}])
for field, limits in [('thickness', (2, 24)), ('radius', (0, 12)), ('glow', (0, 16))]:
    for value in [limits[0] - 1, limits[1] + 1, True, 1.5]:
        bad('/display/0/style', {field: value}, error='/display/0/style/' + field)
for value in ['#ab', '#abcd', '#1234567', '#ggg', 'red', 'url(evil)', 1]:
    bad('/display/0/style', {'color': value}, error='/display/0/style/color')
for field, value in [('radius', 25), ('radius', True), ('density', 'dense'), ('font', 'arial'), ('motion', 'fast'),
                     ('accent', 'red'), ('surface', 1), ('text', '#zzz'), ('typo', 1)]:
    bad('/theme', {field: value}, error='/theme/' + field)
for icon in [{}, {'brand': 'github', 'emoji': '🔥'}, {'brand': 'githb'}, {'brand': '../github'},
             {'emoji': 'source'}, {'emoji': 'ab'}, {'url': 'http://example.com/icon'},
             {'url': 'https://example.com:444/icon'}, {'url': 'https://user@example.com/icon'},
             {'url': 'https://127.0.0.1/icon'}, {'url': 'https://host.local/icon'},
             {'url': 'https://example.com/icon?token=abc'}, {'url': 'https://example.com/' + 'x' * 300}]:
    key = next(iter(icon), None)
    bad('/icon', icon, error='/icon/' + key if len(icon) == 1 else '/icon')
bad('/alert', {'metric': 'a.nope', 'above': 1}, error='/alert/metric')


# Every typed/style boundary gets explicit wrong-type and out-of-domain coverage.
STYLE_EXTRAS = {
    'score': {},
    'rings': {'gap': [0, 6], 'cap': ['round', 'flat'], 'direction': ['cw', 'ccw']},
    'bar': {'ticks': ['none', 'usual', 'zones'], 'show_range': [True, False]},
    'bars': {'ticks': ['none', 'usual', 'zones'], 'show_range': [True, False]},
    'stat': {'delta_colors': ['semantic', 'neutral']},
    'spark': {'fill': ['none', 'area'], 'dot': ['last', 'none']},
}
for block in BLOCKS:
    base = draft(block)
    for field in ['color', 'color2', 'track', 'text', 'label']:
        bad('/display/0/style', {field: 'bad'}, base, '/display/0/style/' + field)
    bad('/display/0/style', [], base)
    for field, choices in STYLE_EXTRAS[block['type']].items():
        for value in ['bad', None]:
            bad('/display/0/style', {field: value}, base, '/display/0/style/' + field)
    if block['type'] in ('rings', 'bars'):
        key = block['type']
        for field, value in [('value', True), ('label', 1), ('unit', False), ('zones', []), ('typo', 1)]:
            bad('/display/0/' + key + '/0/' + field, value, base)
        bad('/display/0/' + key + '/0/style', {'track': 'accent'}, base,
            '/display/0/' + key + '/0/style/track')
        bad('/display/0/' + key, [None, {'value': 'used'}], base,
            '/display/0/' + key + '/0')
for value in [None, False, 1, 'bad', []]:
    bad('/feeds/a', value)
    bad('/theme', value)
for value in [None, False, 1, 'bad', {}]:
    bad('/display', value)
for value in [None, False, 1, 'bad', []]:
    bad('/display/0', value)
for name in ['a' * 17, 'a-b', 'A', '1a']:
    bad('/feeds', {name: draft()['feeds']['a']}, error='/feeds/' + name)
for key in ['min', 'max']:
    bad('/display/0/' + key, 'missing.used')
bad('/display/0/bars/0/label', 'x' * 41, draft(BLOCKS[3]))
bad('/display/0/style', {'gap': 7}, draft(BLOCKS[1]), '/display/0/style/gap')
bad('/display/0/style', {'gap': -1}, draft(BLOCKS[1]), '/display/0/style/gap')
bad('/display/0/style', {'gap': True}, draft(BLOCKS[1]), '/display/0/style/gap')
bad('/display/0/scale', 'bad', draft(BLOCKS[3]))
bad('/theme', {'radius': -1}, error='/theme/radius')
bad('/icon', {'brand': 1}, error='/icon/brand')
bad('/icon', {'emoji': 1}, error='/icon/emoji')
bad('/icon', {'url': 1}, error='/icon/url')
bad('/icon', {'emoji': '🔥', 'typo': 1}, error='/icon/typo')
bad('/display/0/value', 'a.used\n')
bad('/display/0/value', 'used\n')
bad('/display/0/style', {'color': '#abc\n'}, error='/display/0/style/color')
bad('/feeds', {'a\n': draft()['feeds']['a']}, error='/feeds/a\n')
missing_source = minimal(); del missing_source['source']
INVALID.append((missing_source, ''))


@pytest.mark.parametrize('value,path', INVALID)
def test_invalid_display(value, path):
    original = deepcopy(value)
    errors = spec.validate(value)
    assert value == original
    assert path in [e['path'] for e in errors], errors
    with pytest.raises(spec.ValidationError): spec.normalize(value)


@pytest.mark.parametrize('block', BLOCKS)
def test_minimal_display(block):
    value = draft(block)
    original = deepcopy(value)
    assert spec.validate(value) == []
    normalized = spec.normalize(value)
    assert value == original
    assert spec.validate(normalized) == []
    assert spec.normalize(normalized) == normalized
    assert normalized['feeds']['a']['every'] == '5m'
    assert not any(k in normalized for k in ['source', 'every', 'ring', 'capsule', 'lines'])
    assert all(ref.startswith('a.') for _, ref in spec.bindings_of(normalized))
    normalized['feeds']['a']['params']['metrics']['used'] = '/other'
    assert value == original


def test_defaults_and_helpers():
    out = spec.normalize(draft({'type': 'rings', 'rings': [{'value': 'late_orders', 'zones': {'warn': 1}}]}))
    assert out['display'][0]['rings'][0] == {'value': 'a.late_orders', 'label': 'Late orders', 'min': 0,
                                          'max': 'auto', 'auto_window': '7d', 'zones': {'warn': 1, 'direction': 'up'}}
    assert 'label' not in out['display'][0]
    assert spec.feeds_of(out) == out['feeds']
    assert spec.bindings_of(out) == [('/display/0/rings/0/value', 'a.late_orders')]
    assert spec.normalize(draft(BLOCKS[3]))['display'][0]['scale'] == 'shared'
    stat = spec.normalize(draft(BLOCKS[4]))['display'][0]
    assert (stat['show'], stat['delta_vs'], stat['auto_window']) == ('value', 'usual', '7d')
    assert spec.normalize(draft(BLOCKS[5]))['display'][0]['points'] == 24
    assert spec.normalize(draft(BLOCKS[0]))['display'][0]['components'][0]['baseline'] == 'median'


def test_source_display_and_alert_refs():
    value = minimal('github.repo')
    value['display'] = [{'type': 'bar', 'value': 'stars', 'max': 'forks'}]
    value['alert'] = {'metric': 'stars', 'above': 1}
    out = spec.normalize(value)
    assert out['display'][0]['value'] == 'main.stars'
    assert out['display'][0]['max'] == 'main.forks'
    assert out['alert']['metric'] == 'main.stars'
    assert spec.feeds_of(out) == {'main': dict(out['source'], every=out['every'])}
    assert spec.normalize(out) == out


def test_style_canonicalization_and_extensions():
    value = draft()
    value['theme'] = {'accent': '#ABC', 'x-note': '#ABC'}
    value['display'][0]['style'] = {'color': '#AABBCCDD', 'x-note': '#ABC'}
    value['display'][0]['x-note'] = {'keep': [1]}
    out = spec.normalize(value)
    assert out['theme'] == {'accent': '#abc', 'x-note': '#ABC'}
    assert out['display'][0]['style'] == {'color': '#aabbccdd', 'x-note': '#ABC'}
    assert out['display'][0]['x-note'] == {'keep': [1]}
    assert spec.normalize(out) == out


@pytest.mark.parametrize('icon', [{'brand': 'github'}, {'brand': 'discord'}, {'brand': 'ebay'},
                                  {'brand': 'youtube'}, {'brand': 'tesla'}, {'emoji': '👩🏽\u200d💻'},
                                  {'url': 'https://images.example.com:443/icon.png'}])
def test_icon_forms(icon):
    assert spec.validate(dict(draft(), icon=icon)) == []


def test_brand_suggestion():
    errors = spec.validate(dict(draft(), icon={'brand': 'githb'}))
    assert any(e['path'] == '/icon/brand' and 'did you mean' in e['message'].lower() and 'github' in e['message'] for e in errors)


def test_budget_union_and_exact_sum():
    value = draft({'type': 'bar', 'value': 'a.used'}, count=3)
    value['feeds']['b'] = dict(minimal('github.search')['source'], every='15m')
    value['feeds']['c'] = dict(minimal('github.repo')['source'], every='15m')
    value['icon'] = {'url': 'https://images.example.com/icon.png'}
    b = spec.budget(value)
    assert b['req_per_hour'] == pytest.approx(12 + 4 + 1 / 6 + 8)
    assert b['req_per_hour_display'] == 25
    assert b['hosts'] == ['api.example.com', 'api.github.com', 'images.example.com']
    value['icon'] = 'source'
    assert spec.budget(value)['hosts'] == ['api.example.com', 'api.github.com', 'avatars.githubusercontent.com']


def test_backcompat_snapshot():
    snapshot = json.loads((ROOT / 'tests/fixtures/normalized/display-backcompat.json').read_text(encoding='utf-8'))
    values = definitions()
    # New opt-in fixture is not part of the frozen pre-display legacy corpus.
    activity = values.pop('examples/e-repo-activity.pulse.yaml')
    assert spec.normalize(activity)['source']['params']['activity'] is True
    # Search QA's opt-in display demo is new, not part of the frozen legacy corpus.
    search_demo = values.pop('tests/fixtures/github/hackathon-race.pulse.yaml')
    assert [b['type'] for b in spec.normalize(search_demo)['display']] == ['score', 'stat', 'spark']
    assert set(values) == set(snapshot['definitions'])
    assert snapshot['revision'] == '3b04572'
    for key, value in values.items():
        expected = snapshot['definitions'][key]
        normalized = spec.normalize(value)
        assert normalized == expected['normalized'], key
        assert json.dumps(normalized, ensure_ascii=False, separators=(',', ':')) == json.dumps(expected['normalized'], ensure_ascii=False, separators=(',', ':')), key
        budget = spec.budget(value)
        old = expected['budget']
        github = expected['normalized']['source']['kind'].startswith('github.') and expected['normalized']['icon'] == 'source'
        assert budget == dict(old, hosts=sorted(set(old['hosts']) | ({'avatars.githubusercontent.com'} if github else set()))), key


def maximal_blocks():
    item = {'value': 'a.used', 'label': 'x' * 40, 'unit': 'x' * 8, 'min': -1, 'max': 'a.limit',
            'auto_window': '1h', 'zones': {'warn': 2, 'crit': 5, 'direction': 'up'}, 'style': {'color': '#ABC'}}
    common_style = {'color': '#ABC', 'color2': '#AABBCC', 'track': '#AABBCCDD', 'thickness': 24,
                    'radius': 12, 'glow': 16, 'text': 'l', 'label': 'above'}
    return [
        {'type': 'score', 'label': 'x' * 40, 'components': [
            {'metric': 'a.used', 'weight': 25, 'type': 'delta', 'baseline': 'oldest', 'window': '24h',
             'floor': 1, 'sensitivity': 2, 'direction': 'down'}] * 4, 'style': common_style},
        {'type': 'rings', 'label': 'x' * 40, 'rings': [deepcopy(item) for _ in range(3)],
         'style': dict(common_style, gap=6, cap='flat', direction='ccw')},
        dict(item, type='bar', style=dict(common_style, ticks='zones', show_range=True)),
        {'type': 'bars', 'label': 'x' * 40, 'bars': [deepcopy(item) for _ in range(3)],
         'scale': 'independent', 'style': dict(common_style, ticks='usual', show_range=False)},
        {'type': 'bars', 'bars': [{k: v for k, v in item.items() if k not in ('min', 'max', 'auto_window')} for _ in range(3)],
         'scale': 'shared', 'min': 0, 'max': 50, 'auto_window': '7d'},
        {'type': 'stat', 'value': 'a.used', 'label': 'x' * 40, 'unit': 'x' * 8, 'show': 'both',
         'delta_vs': 'previous', 'decimals': 3, 'auto_window': '7d', 'style': dict(common_style, delta_colors='neutral')},
        {'type': 'spark', 'value': 'a.used', 'label': 'x' * 40, 'points': 48,
         'style': dict(common_style, fill='area', dot='last')},
    ]


@pytest.mark.parametrize('block', maximal_blocks())
def test_maximal_display(block):
    value = draft(block, count=3)
    value['theme'] = {'accent': '#ABC', 'surface': '#FFFFFF', 'text': 'ink', 'density': 'roomy',
                      'radius': 24, 'font': 'mono', 'motion': 'lively'}
    assert spec.validate(value) == []
    normalized = spec.normalize(value)
    assert spec.normalize(normalized) == normalized


@pytest.mark.parametrize('color', ['#ABC', '#AABBCC', '#AABBCCDD', 'accent', 'ok', 'warn', 'crit', 'muted', 'ink'])
def test_all_colors(color):
    assert not spec.validate(changed('/display/0/style', {'color': color}))


@pytest.mark.parametrize('field,choices', [('thickness', (2, 24)), ('radius', (0, 12)), ('glow', (0, 16)),
                                          ('text', ('s', 'm', 'l')), ('label', ('above', 'inline', 'hidden'))])
def test_common_style_boundaries(field, choices):
    for value in choices:
        assert not spec.validate(changed('/display/0/style', {field: value}))


@pytest.mark.parametrize('block', BLOCKS)
def test_all_specific_styles(block):
    for field, choices in STYLE_EXTRAS[block['type']].items():
        for value in choices:
            assert not spec.validate(draft(dict(block, style={field: value})))


@pytest.mark.parametrize('key,choices', [('density', ['compact', 'cozy', 'roomy']), ('radius', [0, 24]),
                                       ('font', ['system', 'rounded', 'mono']), ('motion', ['none', 'calm', 'lively'])])
def test_theme_values(key, choices):
    for value in choices:
        assert not spec.validate(dict(draft(), theme={key: value}))


def test_exact_binding_and_block_limits():
    value = draft()
    value['display'] = [deepcopy(BLOCKS[0]), deepcopy(BLOCKS[1]), deepcopy(BLOCKS[4]), deepcopy(BLOCKS[5])]
    value['display'][0]['components'] *= 4
    for c in value['display'][0]['components']: c['weight'] = 25
    value['display'][1]['rings'] *= 2
    assert not spec.validate(value)
    assert len(spec.bindings_of(value)) == 8
    value['display'][1]['rings'].append({'value': 'used'})
    assert '/display' in [e['path'] for e in spec.validate(value)]


@pytest.mark.parametrize('kind', list(spec.KINDS))
def test_feed_kind_defaults_aliases_and_minima(kind):
    value = {'pulse': 1, 'title': 'Feed kind', 'feeds': {'a': dict(minimal(kind)['source'])}}
    metric = next(iter(value['feeds']['a']['params']['metrics'])) if kind in ('mcp.tool', 'http_json') else spec.KINDS[kind]['metrics'][0]
    value['display'] = [{'type': 'bar', 'value': metric}]
    out = spec.normalize(value)
    assert out['feeds']['a']['every'] == spec.KINDS[kind]['default_every']
    assert spec.feeds_of(value) == out['feeds']
    value['feeds']['a']['kind'] += '@1'
    assert spec.normalize(value) == out
    value['feeds']['a']['every'] = str(spec.KINDS[kind]['min_every'] - 1) + 's'
    assert '/feeds/a/every' in [e['path'] for e in spec.validate(value)]


@pytest.mark.parametrize('window', ['1h', '3600s', '60m', '168h', '7d'])
def test_auto_window_boundaries(window):
    assert not spec.validate(changed('/display/0/auto_window', window))


@pytest.mark.parametrize('decimals', [0, 1, 2, 3])
def test_stat_decimals(decimals):
    assert not spec.validate(draft(dict(BLOCKS[4], decimals=decimals)))


@pytest.mark.parametrize('points', [8, 48])
def test_spark_points(points):
    assert not spec.validate(draft(dict(BLOCKS[5], points=points)))


@pytest.mark.parametrize('zones', [{'warn': 0}, {'crit': 0}, {'warn': 2, 'crit': 5},
                                  {'warn': 5, 'crit': 2, 'direction': 'down'}])
def test_valid_zones(zones):
    out = spec.normalize(changed('/display/0/zones', zones))
    assert out['display'][0]['zones']['direction'] == zones.get('direction', 'up')


@pytest.mark.parametrize('bounds', [{'min': 'auto', 'max': 'usual'}, {'min': 'a.used', 'max': 'auto'}])
def test_shared_scale_constraints(bounds):
    value = draft(dict(BLOCKS[3], **bounds))
    key = 'max' if bounds['max'] == 'usual' else 'min'
    assert '/display/0/' + key in [e['path'] for e in spec.validate(value)]


def test_shared_bars_defaults_are_valid_and_idempotent():
    out = spec.normalize(draft(BLOCKS[3]))
    block = out['display'][0]
    assert (block['min'], block['max'], block['auto_window']) == (0, 'auto', '7d')
    assert all(not any(k in item for k in ['min', 'max', 'auto_window']) for item in block['bars'])
    assert spec.normalize(out) == out


def test_extensions_at_every_display_boundary():
    value = draft({'type': 'rings', 'rings': [{'value': 'used', 'x-note': [1],
                    'zones': {'warn': 0, 'x-note': [1]}, 'style': {'color': 'ok', 'x-note': [1]}}], 'x-note': [1]})
    value['feeds']['a']['x-note'] = [1]
    value['feeds']['a']['params']['x-note'] = [1]
    value['icon'] = {'emoji': '🔥', 'x-note': [1]}
    out = spec.normalize(value)
    assert out['icon']['x-note'] == [1]
    assert out['display'][0]['rings'][0]['zones']['x-note'] == [1]
    assert spec.normalize(out) == out


def test_alert_binding_and_github_icon_optout():
    value = dict(draft(), alert={'metric': 'used', 'above': 2})
    out = spec.normalize(value)
    assert out['alert'] == {'metric': 'a.used', 'above': 2, 'notify': 'none'}
    assert spec.bindings_of(out)[-1] == ('/alert/metric', 'a.used')
    github = minimal('github.repo')
    for icon in ['hermes', {'brand': 'github'}, {'emoji': '🔥'}]:
        assert spec.budget(dict(github, icon=icon))['hosts'] == ['api.github.com']


def test_helpers_copy_and_binding_paths():
    value = draft({'type': 'bars', 'scale': 'shared', 'min': 'a.late_orders', 'max': 'a.limit',
                   'bars': [{'value': 'used'}, {'value': 'used'}]})
    value['alert'] = {'metric': 'used', 'below': 1}
    expected = [('/display/0/min', 'a.late_orders'), ('/display/0/max', 'a.limit'),
                ('/display/0/bars/0/value', 'a.used'), ('/display/0/bars/1/value', 'a.used'),
                ('/alert/metric', 'a.used')]
    assert spec.bindings_of(value) == expected
    assert spec.bindings_of(spec.normalize(value)) == expected
    feeds = spec.feeds_of(value)
    feeds['a']['params']['metrics']['used'] = '/other'
    assert value['feeds']['a']['params']['metrics']['used'] == '/used'


def test_feed_and_icon_url_character_boundaries():
    value = draft()
    value['feeds']['a' * 16] = value['feeds'].pop('a')
    assert spec.normalize(value)['display'][0]['value'] == 'a' * 16 + '.used'
    prefix = 'https://images.example.com/'
    value['icon'] = {'url': prefix + 'x' * (300 - len(prefix))}
    assert not spec.validate(value)


@pytest.mark.parametrize('feed,path', [(None, '/feeds/a'), ([], '/feeds/a'),
    ({'kind': 'unknown'}, '/feeds/a/kind'), ({'kind': None}, '/feeds/a/kind'),
    ({'kind': []}, '/feeds/a/kind'), ({'kind': 'github.repo', 'params': []}, '/feeds/a/params')])
def test_malformed_feed_with_score_source_baseline_never_crashes(feed, path):
    value = draft({'type': 'score', 'components': [{'metric': 'a.used', 'weight': 100, 'type': 'delta', 'baseline': 'source'}]})
    value['feeds']['a'] = feed
    assert path in [e['path'] for e in spec.validate(value)]


def test_schema_parity():
    import jsonschema
    published = json.loads((ROOT / 'spec/pulse-1.schema.json').read_text())
    assert published == spec.schema()
    checker = jsonschema.FormatChecker()
    for name, check in spec.FORMAT_CHECKS.items(): checker.checks(name)(check)
    validator = jsonschema.Draft202012Validator(published, format_checker=checker)
    for value in [draft(b) for b in BLOCKS + maximal_blocks()] + [v for v, _ in INVALID]:
        shape = list(validator.iter_errors(value))
        assert bool(shape) == bool(spec._shape(value, spec.SCHEMA)), value
        assert bool(shape or spec.semantic_errors(value)) == bool(spec.validate(value)), value
