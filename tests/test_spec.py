"""pulse/1 conformance: offline, no Hermes imports or runtime dependencies."""
from copy import deepcopy
import builtins
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pulse_rings import spec
from pulse_rings.kinds import KINDS


def minimal(kind='github.search'):
    params = {
        'github.search': {'repo': 'NousResearch/hermes-agent', 'type': 'pr'},
        'github.repo': {'repo': 'NousResearch/hermes-agent'},
        'discord.invite': {'invite': 'nousresearch'},
        'hermes.activity': {},
        'mcp.tool': {'server': 'probe', 'tool': 'read_metrics', 'metrics': {'count': '/count'}},
        'http_json': {'url': 'https://api.example.com/data', 'metrics': {'players': '/count'}},
        'desktop.notifications': {'apps': ['discord']},
        'web.feed': {'url': 'https://example.org/feed.xml'},
    }[kind]
    return {'pulse': 1, 'title': 'Test pulse', 'source': {'kind': kind, 'params': params}}


def changed(path, value, kind='github.search'):
    draft = minimal(kind)
    node = draft
    keys = path.split('.')
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value
    return draft


def component(**changes):
    return dict({'metric': 'recent', 'weight': 100, 'type': 'delta', 'baseline': 'source'}, **changes)


# Structural and semantic conformance fixtures, each with an exact actionable path.
NEGATIVE = [
    (changed('pulse', 2), '/pulse'),
    (changed('pulse', True), '/pulse'),
    (changed('pulse', '1'), '/pulse'),
    (changed('id', 'A'), '/id'),
    (changed('id', '../escape'), '/id'),
    (changed('id', 'x' * 49), '/id'),
    (changed('title', ''), '/title'),
    (changed('title', 'x' * 61), '/title'),
    (changed('title', 1), '/title'),
    (changed('unknown', 'typo'), '/unknown'),
    (changed('source.unknown', 1), '/source/unknown'),
    (changed('source.kind', 'feed'), '/source/kind'),
    (changed('source.kind', 'github.search@2'), '/source/kind'),
    (changed('source.params.query', 'raw query'), '/source/params/query'),
    (changed('source.params.repo', '../bad'), '/source/params/repo'),
    (changed('source.params.repo', 'o/n is:private'), '/source/params/repo'),
    (changed('source.params.type', 'pull'), '/source/params/type'),
    (changed('source.params.title_contains', 'catalog OR is:private'), '/source/params/title_contains'),
    (changed('source.params.label', 'bug" OR is:private'), '/source/params/label'),
    (changed('source.params.window', '1d'), '/source/params/window'),
    (changed('source.params.baseline_days', 6), '/source/params/baseline_days'),
    (changed('source.params.baseline_days', 31), '/source/params/baseline_days'),
    (changed('source.params.baseline_days', True), '/source/params/baseline_days'),
    (changed('source.params.scope', 'all', 'hermes.activity'), '/source/params/scope'),
    (changed('source.params.voice', 'yes', 'discord.invite'), '/source/params/voice'),
    (changed('source.params.invite', 'https://evil.example/invite/x', 'discord.invite'), '/source/params/invite'),
    (changed('source.params.invite', 'http://discord.gg/abcd', 'discord.invite'), '/source/params/invite'),
    (changed('source.params.invite', 'https://discord.gg/ab/extra', 'discord.invite'), '/source/params/invite'),
    (changed('source.params.invite', 'https://user@discord.gg/abcd', 'discord.invite'), '/source/params/invite'),
    (changed('every', '1m'), '/every'),
    (changed('every', '0s'), '/every'),
    (changed('every', 600), '/every'),
    (changed('every', '1d'), '/every'),
    (changed('ring.components', []), '/ring/components'),
    (changed('ring.components', [component(weight=20)] * 5), '/ring/components'),
    (changed('ring.components', [component(weight=90)]), '/ring/components'),
    (changed('ring.components', [component(weight=True)]), '/ring/components/0/weight'),
    (changed('ring.components', [component(metric='typo')]), '/ring/components/0/metric'),
    (changed('ring.components', [component(sensitivity=0)]), '/ring/components/0/sensitivity'),
    (changed('ring.components', [component(floor=0)]), '/ring/components/0/floor'),
    (changed('ring.components', [component(baseline=-1)]), '/ring/components/0/baseline'),
    (changed('ring.components', [component(baseline='invented')]), '/ring/components/0/baseline'),
    (changed('ring.components', [component(baseline='source', metric='stars')], 'github.repo'), '/ring/components/0/baseline'),
    (changed('ring.components', [component(direction='sideways')]), '/ring/components/0/direction'),
    (changed('ring.components', [component(window='0h')]), '/ring/components/0/window'),
    (changed('ring.components', [{'metric': 'recent', 'weight': 100, 'type': 'level', 'full_at': 0}]), '/ring/components/0/full_at'),
    (changed('ring.components', [component(type='script')]), '/ring/components/0/type'),
    (changed('ring.components', [component(code='evil')]), '/ring/components/0/code'),
    (changed('capsule', {'metric': 'recent', 'label': '{value.__class__}', 'fill': 'baseline'}), '/capsule/label'),
    (changed('capsule', {'metric': 'recent', 'label': '{value!r}', 'fill': 'none'}), '/capsule/label'),
    (changed('capsule', {'metric': 'recent', 'label': '{value:02d}', 'fill': 'none'}), '/capsule/label'),
    (changed('capsule', {'metric': 'recent', 'label': '{{value}}', 'fill': 'none'}), '/capsule/label'),
    (changed('capsule', {'metric': 'recent', 'label': '{unknown}', 'fill': 'none'}), '/capsule/label'),
    (changed('capsule', {'metric': 'recent', 'label': 'x' * 41, 'fill': 'none'}), '/capsule/label'),
    (changed('capsule', {'metric': 'recent', 'label': '{value}', 'fill': {'full_at': 0}}), '/capsule/fill/full_at'),
    (changed('lines', [{'metric': 'recent', 'label': '{value}'}] * 4), '/lines'),
    (changed('lines', [{'metric': 'recent', 'label': '{value}', 'show': 'html'}]), '/lines/0/show'),
    (changed('alert', {'ring_at_least': 101}), '/alert/ring_at_least'),
    (changed('alert', {'metric': 'recent', 'above': 1, 'below': 2}), '/alert'),
    (changed('alert', {'metric': 'recent'}), '/alert'),
    (changed('alert', {'ring_at_least': 1, 'notify': 'email'}), '/alert/notify'),
    (changed('link', 'http://example.com'), '/link'),
    (changed('link', 'https://user:pass@example.com'), '/link'),
    (changed('icon', 'https://example.com/icon.png'), '/icon'),
    (changed('source.params.url', 'http://example.com/a', 'http_json'), '/source/params/url'),
    (changed('source.params.url', 'https://user:pass@example.com', 'http_json'), '/source/params/url'),
    (changed('source.params.url', 'https://127.0.0.1/x', 'http_json'), '/source/params/url'),
    (changed('source.params.url', 'https://10.0.0.1/x', 'http_json'), '/source/params/url'),
    (changed('source.params.url', 'https://169.254.169.254/latest', 'http_json'), '/source/params/url'),
    (changed('source.params.url', 'https://[::1]/x', 'http_json'), '/source/params/url'),
    (changed('source.params.url', 'https://localhost/x', 'http_json'), '/source/params/url'),
    (changed('source.params.url', 'https://api.example.com/{secret}', 'http_json'), '/source/params/url'),
    (changed('source.params.url', 'https://example.com/%7Bsecret%7D', 'http_json'), '/source/params/url'),
    (changed('source.params.url', 'https://example.com\\@127.0.0.1', 'http_json'), '/source/params/url'),
    (changed('source.params.url', 'https://example.com:bad', 'http_json'), '/source/params/url'),
    (changed('source.params.url', 'https://example.com/' + 'a' * 512, 'http_json'), '/source/params/url'),
    (changed('source.params.metrics', {}, 'http_json'), '/source/params/metrics'),
    (changed('source.params.metrics', {f'm{i}': '/x' for i in range(7)}, 'http_json'), '/source/params/metrics'),
    (changed('source.params.metrics', {'bad name': '/x'}, 'http_json'), '/source/params/metrics/bad name'),
    (changed('source.params.metrics', {'players': 'response/count'}, 'http_json'), '/source/params/metrics/players'),
    (changed('source.params.metrics', {'players': '/bad~2escape'}, 'http_json'), '/source/params/metrics/players'),
    (changed('source.params.headers', {'Authorization': 'secret'}, 'http_json'), '/source/params/headers'),
]


@pytest.mark.parametrize('draft,path', NEGATIVE)
def test_negative(draft, path):
    errors = spec.validate(draft)
    assert errors, draft
    assert all(set(error) == {'path', 'message'} and error['message'] for error in errors)
    assert path in [error['path'] for error in errors], errors
    with pytest.raises(spec.ValidationError) as exc:
        spec.normalize(draft)
    assert exc.value.errors == errors


@pytest.mark.parametrize('kind', KINDS)
def test_minimal_presets(kind):
    draft = minimal(kind)
    original = deepcopy(draft)
    out = spec.normalize(draft)
    assert draft == original
    assert spec.validate(out) == []
    assert spec.normalize(out) == out
    assert out['source']['kind'] == kind
    assert 'alert' not in out  # Alerts are explicit opt-in, not preset authority.
    assert sum(c['weight'] for c in out['ring']['components']) == 100
    pinned = deepcopy(draft)
    pinned['source']['kind'] += '@1'
    assert spec.normalize(pinned) == out


def test_examples():
    paths = sorted((ROOT / 'examples').glob('*.pulse.yaml'))
    assert len(paths) == 5
    for path in paths:
        draft = spec.parse(path.read_bytes())
        assert spec.validate(draft) == [], path
        out = spec.normalize(draft)
        assert spec.normalize(out) == out
    discord = spec.normalize(spec.parse(paths[0].read_bytes()))
    assert [c['weight'] for c in discord['ring']['components']] == [70, 20, 10]


@pytest.mark.parametrize('kind,every,expected', [
    ('discord.invite', '10m', 10),
    ('github.search', '15m', 4 + 1 / 6),
    ('github.repo', '15m', 8),
    ('hermes.activity', '30s', 0),
    ('http_json', '5m', 12),
])
def test_budget(kind, every, expected):
    draft = minimal(kind)
    draft['every'] = every
    result = spec.budget(draft)
    assert result['req_per_hour'] == pytest.approx(expected)
    hosts = ['api.example.com'] if kind == 'http_json' else list(KINDS[kind]['hosts'])
    if kind.startswith('github.'):
        hosts.append('avatars.githubusercontent.com')
    assert result['hosts'] == sorted(hosts)


def test_budget_voice_off():
    draft = minimal('discord.invite')
    draft['source']['params']['voice'] = False
    assert spec.budget(draft)['req_per_hour'] == 6


def test_extensions_and_slugs():
    draft = minimal()
    draft.update({'title': '🚀', 'x-review': {'anything': [1, None, True]}})
    draft['source']['params']['x-note'] = 'preserved'
    out = spec.normalize(draft)
    assert out['id'] == 'pulse'
    assert out['x-review'] == draft['x-review']
    assert out['source']['params']['x-note'] == 'preserved'
    draft['title'] = 'A'
    assert spec.normalize(draft)['id'] == 'a-pulse'


@pytest.mark.parametrize('text', [b'\xff', '[]', 'null', '{broken', 'pulse: 1\npulse: 2',
                                  'x: &loop [*loop]', '!!python/object:evil {}',
                                  '{"pulse":1,"pulse":2}', '{"x":NaN}', 'x: .inf'])
def test_parse_rejects_unsafe_input(text):
    with pytest.raises(spec.ValidationError) as exc:
        spec.parse(text)
    assert all(set(error) == {'path', 'message'} for error in exc.value.errors)


@pytest.mark.parametrize('value', ['x' * (16384 + 1), 'é' * 8193, b'x' * 16385],
                         ids=['ascii', 'utf8', 'bytes'])
def test_size_cap(value):
    with pytest.raises(spec.ValidationError) as exc:
        spec.parse(value)
    assert exc.value.errors[0]['path'] == ''
    assert '16 KiB' in exc.value.errors[0]['message']


def test_mapping_size_cap():
    assert spec.validate(dict(minimal(), **{'x-large': 'x' * 16384}))[0]['path'] == ''


def test_json_fallback(monkeypatch):
    original = builtins.__import__
    def no_yaml(name, *args, **kwargs):
        if name == 'ruamel.yaml':
            raise ImportError('ruamel intentionally unavailable')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', no_yaml)
    draft = minimal()
    assert spec.parse(json.dumps(draft)) == draft
    assert spec.normalize(json.dumps(draft)) == spec.normalize(draft)
    with pytest.raises(spec.ValidationError, match='JSON'):
        spec.parse('pulse: 1\ntitle: Test')


def test_yaml_path():
    __import__('ruamel.yaml')
    assert spec.parse('pulse: 1\ntitle: Test\nsource: {kind: hermes.activity}')['pulse'] == 1


def test_schema_shape_conformance():
    import jsonschema
    schema = json.loads((ROOT / 'spec/pulse-1.schema.json').read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    checker = jsonschema.FormatChecker()
    for name, check in spec.FORMAT_CHECKS.items():
        checker.checks(name)(check)
    validator = jsonschema.Draft202012Validator(schema, format_checker=checker)
    # Shape includes kind params, duration minima and URL/template formats. The
    # normative semantic pass also checks sums and metric references (§3.8).
    for draft in [minimal(k) for k in KINDS] + [spec.parse(p.read_bytes()) for p in (ROOT / 'examples').glob('*.pulse.yaml')]:
        assert not list(validator.iter_errors(draft))
        assert not list(validator.iter_errors(spec.normalize(draft)))
    for draft, _ in NEGATIVE:
        shape_errors = list(validator.iter_errors(draft))
        assert bool(shape_errors) == bool(spec._shape(draft, spec.SCHEMA)), draft
        semantic_errors = spec.semantic_errors(draft)
        assert bool(shape_errors or semantic_errors) == bool(spec.validate(draft)), draft
    assert schema == spec.schema()


def test_strict_json_data():
    for value in [float('nan'), float('inf'), {1: 'bad'}, {'nested': {1, 2}}, ('tuple',)]:
        assert spec.validate(dict(minimal(), **{'x-bad': value}))
    cyclic = minimal()
    cyclic['x-loop'] = cyclic
    assert spec.validate(cyclic)


def test_weight_tolerance():
    for weight in [99.99, 100, 100.0]:
        draft = changed('ring.components', [component(weight=weight)])
        assert spec.validate(draft) == []
    assert spec.validate(changed('ring.components', [component(weight=99.98)]))


def test_empty_required_fields():
    for draft in [{}, {'pulse': 1}, {'pulse': 1, 'title': 'X'}, changed('source', None)]:
        assert spec.validate(draft)


def test_no_hermes_imports():
    import ast
    for filename in ['spec.py', 'kinds.py']:
        tree = ast.parse((ROOT / 'pulse_rings' / filename).read_text())
        imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        imports += [alias.name for n in ast.walk(tree) if isinstance(n, ast.Import) for alias in n.names]
        assert all(not name.startswith(('hermes', 'plugins', 'tools', 'agent.')) for name in imports if name)


@pytest.mark.parametrize('value', [None, False, 1, 1.5, '', [], {}, ['bad'], {'bad': 1}],
                         ids=['null', 'bool', 'int', 'float', 'str', 'list', 'object', 'array', 'mapping'])
def test_malformed_values_never_crash(value):
    # Exercise all publicly writable shape boundaries, not just valid-type typos.
    for key in ['pulse', 'id', 'title', 'source', 'every', 'ring', 'capsule', 'lines', 'alert', 'icon', 'link']:
        spec.validate(dict(minimal(), **{key: value}))
    for key in ['kind', 'params']:
        draft = minimal()
        draft['source'][key] = value
        spec.validate(draft)
    for key in ['metric', 'weight', 'type', 'baseline', 'window', 'floor', 'sensitivity', 'direction', 'full_at']:
        draft = changed('ring.components', [component(**{key: value})])
        spec.validate(draft)
    draft = minimal('http_json')
    draft['source']['params']['metrics'] = value
    spec.validate(draft)


@pytest.mark.parametrize('url', [
    'https://[fc00::1]/', 'https://[fe80::1]/', 'https://[::ffff:127.0.0.1]/',
    'https://192.168.1.1/', 'https://100.64.0.1/', 'https://0.0.0.0/',
    'https://224.0.0.1/', 'https://2130706433/', 'https://127.1/',
    'https://0177.0.0.1/', 'https://0x7f000001/', 'https://localhost./',
    'https://metadata.google.internal/', 'https://host.local/',
    'https://example.com/#fragment', 'https://exa mple.com/',
    'https://example.com:65536/', 'https://%31%32%37.0.0.1/',
])
def test_public_url_rejections(url):
    errors = spec.validate(changed('source.params.url', url, 'http_json'))
    assert any(error['path'] == '/source/params/url' for error in errors)


@pytest.mark.parametrize('url,host', [
    ('https://8.8.8.8/data', '8.8.8.8'),
    ('https://[2606:4700:4700::1111]/', '2606:4700:4700::1111'),
    ('https://API.Example.com.:443/data?q=a', 'api.example.com'),
])
def test_public_url_acceptance(url, host):
    draft = changed('source.params.url', url, 'http_json')
    assert spec.validate(draft) == []
    assert spec.budget(draft)['hosts'] == [host]


@pytest.mark.parametrize('icon', ['🌡️', '👩🏽\u200d💻', '🇺🇸', '1️⃣', '🔥', 'hermes', 'initials'])
def test_icon_clusters(icon):
    assert spec.validate(changed('icon', icon)) == []


def test_boundaries_and_pointer_escaping():
    assert spec.parse('{"x":"' + 'x' * (16384 - 8) + '"}')
    prefix = 'https://example.com/'
    assert spec.validate(changed('source.params.url', prefix + 'x' * (512 - len(prefix)), 'http_json')) == []
    assert spec.validate(changed('source.params.metrics', {'players': '/a~1b/~0name'}, 'http_json')) == []
    assert spec.validate(changed('source.params.metrics', {'players': ''}, 'http_json')) == []
    errors = spec.validate(dict(minimal(), **{'typo/~': 1}))
    assert errors[0]['path'] == '/typo~1~0'


def test_metadata_policies_and_copy_isolation():
    from pulse_rings.kinds import get_kind
    for kind in KINDS:
        meta = get_kind(kind + '@1')
        assert meta == KINDS[kind]
        meta['hosts'].append('evil.invalid')
        assert 'evil.invalid' not in KINDS[kind]['hosts']
        assert KINDS[kind]['pre_approval_sample'] is (
            None if kind in ('hermes.activity', 'desktop.notifications') else kind not in ('http_json', 'mcp.tool', 'web.feed'))


def test_large_number_does_not_crash_validation():
    errors = spec.validate(changed('ring.components', [component(weight=10 ** 1000)]))
    assert any(error['path'] == '/ring/components/0/weight' for error in errors)


def test_duration_minima_and_preset_isolation():
    for kind, meta in KINDS.items():
        draft = minimal(kind)
        draft['every'] = str(meta['min_every']) + 's'
        assert spec.validate(draft) == []
        draft['every'] = str(meta['min_every'] - 1) + 's'
        assert any(error['path'] == '/every' for error in spec.validate(draft))
    a = spec.normalize(minimal('discord.invite'))
    a['ring']['components'][0]['floor'] = 999
    assert spec.normalize(minimal('discord.invite'))['ring']['components'][0]['floor'] == 25
