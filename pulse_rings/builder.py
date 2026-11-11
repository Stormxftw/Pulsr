"""Pure offline builder validation and deterministic, explicitly synthetic feeds.

No storage, clock, network, Hermes dispatch, or ambient random state in this module.
"""
from io import StringIO
import hashlib
import json
import math
import random
import re

from .spec import parse, normalize, budget, ValidationError, feeds_of
from .kinds import metrics_for_params
from .display import compute_display
from . import brands

STATES = ('measured', 'learning', 'unknown', 'over', 'under', 'stale', 'degraded')


def layout_check(definition):
    try:
        normalized = normalize(parse(definition) if isinstance(definition, str) else definition)
        output = StringIO()
        from ruamel.yaml import YAML
        yaml = YAML(typ='safe')
        yaml.default_flow_style = False
        yaml.dump(normalized, output)
        return {'ok': True, 'errors': [], 'normalized': normalized,
                'budget': budget(normalized), 'yaml': output.getvalue()}
    except ValidationError as exc:
        return {'ok': False, 'errors': exc.errors, 'normalized': None, 'budget': None, 'yaml': None}


def _base(metric):
    """Plausible magnitudes, including realistic denominators rather than tiny limits."""
    key = metric.lower()
    if any(x in key for x in ('limit', 'total', 'capacity', 'quota', 'max')):
        return 500
    if 'percent' in key or key.endswith('_pct'):
        return 62
    if any(x in key for x in ('error', 'late', 'waiting', 'running', 'voice')):
        return 3
    if any(x in key for x in ('member', 'star')):
        return 4200
    if 'baseline' in key:
        return 25
    if 'used' in key:
        return 310
    return 42


def _limit(metric):
    return bool(set(re.split(r'[^a-z0-9]+', metric.lower())) & {'limit', 'total', 'capacity', 'quota', 'max'})


def _sample_hint(d, name, metric, feed):
    """Decimals are opt-in by metric/pointer tokens or bound display unit, not label.

    Unknown names remain counts. Match whole tokens (not 'rate' in 'enumerated').
    Binding pointers and units can reveal precision for otherwise opaque names.
    """
    hint = metric + ' ' + str(feed['params'].get('metrics', {}).get(metric, ''))
    for block in d.get('display', []):
        for item in block.get('rings', block.get('bars', [block])):
            if item.get('value') == name + '.' + metric:
                hint += ' ' + item.get('unit', '')
    hint = re.sub(r'([a-z])([A-Z])', r'\1_\2', hint)
    tokens = set(re.split(r'[^a-z0-9]+', hint.lower()))
    if '%' in hint:
        tokens.add('%')
    return tokens


def _fractional(tokens):
    return bool(tokens & {'ratio', 'percent', 'percentage', 'pct', 'rate', 'temperature', 'temp',
                          'gb', 'gib', 'mb', 'mib', 'tb', 'celsius', 'fahrenheit',
                          'latency', 'seconds', 'ms', 'c', 'f'} or '%' in tokens)


def sample_preview(definition, state='measured', seed=0):
    checked = layout_check(definition)
    if not checked['ok']:
        return checked
    d = checked['normalized']
    # Stable across processes, no Python salted hash and no wall-clock dependency.
    digest = hashlib.sha256(json.dumps([d, seed], sort_keys=True).encode()).digest()
    rng = random.Random(int.from_bytes(digest, 'big'))
    now = 1800000000
    feeds = {}
    declared = feeds_of(d)
    for index, (name, feed) in enumerate(declared.items()):
        kind = feed['kind'].removesuffix('@1')
        metrics = list(metrics_for_params(kind, feed['params']))
        hints = {m: _sample_hint(d, name, m, feed) for m in metrics}
        bases = {m: (.62 if 'ratio' in hints[m] else 62 if hints[m] & {'percent', 'percentage', 'pct', '%'}
                     else 7.1 if hints[m] & {'gb', 'gib', 'mb', 'mib', 'tb'}
                     else 24 if hints[m] & {'temperature', 'temp', 'celsius', 'fahrenheit', 'c', 'f'}
                     else _base(m)) for m in metrics}
        for m in metrics:
            if _limit(m):
                # Prefer named siblings; a generic denominator covers the whole feed.
                stem = re.sub(r'_(limit|total|capacity|quota|max)$', '', m)
                siblings = [v for k, v in bases.items() if not _limit(k) and
                            (stem == m or k.rstrip('s') == stem.rstrip('s') or k.startswith(stem + '_'))]
                bases[m] = max(bases[m], math.ceil(max(siblings, default=310) * 1.6))
        def value(m, factor):
            if kind == 'github.repo' and m in ('ci_passing', 'ci_running'):
                return 1 if m == 'ci_passing' else 0  # explicitly synthetic completed success
            if kind == 'github.repo' and m == 'hours_since_push':
                return 3.2  # hours; duration stats are not integer counts
            v = bases[m] if _limit(m) else bases[m] * factor
            return round(v, 2) if _fractional(hints[m]) else round(v)
        count = 1 if state == 'learning' else 24
        history = []
        for step in range(count):
            values = {m: value(m, 0.88 + 0.16 * rng.random()) for m in metrics}
            history.append({'ts': now - (count - step) * 3600, 'metrics': values,
                            'baselines': {'recent': bases.get('recent', 25)}, 'unknown_reasons': {}})
        current = {'ts': now, 'metrics': {m: value(m, 0.94 + rng.random() * 0.12) for m in metrics},
                   'baselines': {'recent': bases.get('recent', 25)}, 'unknown_reasons': {}}
        if kind == 'github.repo' and feed['params'].get('activity'):
            for sample in [*history, current]:
                sample['baselines']['commits_week'] = bases['commits_week']
        unavailable = state == 'unknown' or (state == 'degraded' and index == len(declared) - 1)
        if unavailable:
            current['metrics'] = {m: None for m in metrics}
            current['unknown_reasons'] = {m: 'Synthetic feed unavailable' for m in metrics}
        feeds[name] = {'current': current, 'history': history,
                       'status': {'name': name, 'kind': kind, 'state': 'error' if unavailable else 'active',
                                  'last_ok_ts': now - 86400 if state == 'stale' else now,
                                  'error': 'Synthetic feed unavailable' if unavailable else None}}
    # Scenario inputs, not renderer output patches: all geometry remains engine-owned.
    if state in ('over', 'under'):
        for b in d.get('display', []):
            items = b.get('rings', b.get('bars', [b]))
            for item in items:
                ref = item.get('value')
                if not ref:
                    continue
                name, metric = ref.split('.')
                bounds = b if b.get('type') == 'bars' and b.get('scale') == 'shared' else item
                bound = bounds.get('max' if state == 'over' else 'min', 'auto' if state == 'over' else 0)
                if isinstance(bound, str) and '.' in bound:
                    fn, mn = bound.split('.')
                    bound = feeds[fn]['current']['metrics'][mn]
                if bound == 'usual':
                    bound = 2 * _base(metric)
                if isinstance(bound, (int, float)):
                    v = bound + max(1, abs(bound) * .25) * (1 if state == 'over' else -1)
                    hint = _sample_hint(d, name, metric, declared[name])
                    feeds[name]['current']['metrics'][metric] = (round(v, 2) if _fractional(hint) else
                                                               math.ceil(v) if state == 'over' else math.floor(v))
    display = compute_display(d, feeds)
    icon = d.get('icon', 'source')
    initials = ''.join(part[0] for part in d['title'].split()[:2]).upper() or '?'
    resolved = {'kind': 'initials', 'text': initials}
    if icon == 'hermes' or icon == 'source' and any(f['kind'].startswith('hermes.') for f in declared.values()):
        from .icon_resolver import HERMES
        resolved = dict(HERMES)
    elif isinstance(icon, dict) and icon.get('emoji'):
        resolved = {'kind': 'emoji', 'text': icon['emoji']}
    elif isinstance(icon, str) and icon not in ('source', 'initials'):
        resolved = {'kind': 'emoji', 'text': icon}
    slug = icon.get('brand') if isinstance(icon, dict) else next((f['kind'].split('.')[0] for f in declared.values() if icon == 'source' and f['kind'].startswith(('github.', 'discord.'))), None)
    if slug:
        b = brands.brand(slug)
        if b:
            resolved = {'kind': 'brand', 'slug': slug, **b}
    # URL/MCP source icons never fetch here; initials/bundled glyphs are honest fallbacks.
    return {'ok': True, 'sample': True, 'state': state, 'seed': seed, 'id': d.get('id', 'builder-preview'),
            'title': d['title'], 'display': display, 'theme': d.get('theme'), 'icon': icon,
            'icon_resolved': resolved, 'definition': d, 'synthetic_feeds': feeds,
            'feeds': [f['status'] for f in feeds.values()], 'budget': checked['budget']}


def search_brands(query=''):
    q = query.casefold().strip()
    records = brands._brands()  # Bundled immutable data, not a service or a filesystem path input.
    matches = [(slug, b) for slug, b in records.items() if q in slug or q in b['title'].casefold()]
    matches.sort(key=lambda pair: (pair[0] != q, not pair[0].startswith(q), pair[1]['title'].casefold()))
    return [{'slug': slug, **b} for slug, b in matches[:20]]


def numeric_leaves(body):
    """Finite numeric leaves, RFC 6901 escaped; booleans/strings are never numbers."""
    result = []
    stack = [('', body, 0)]
    seen = 0
    while stack and seen < 8192:
        pointer, value, depth = stack.pop()
        seen += 1
        if len(pointer) > 512 or depth > 32:
            continue
        if type(value) in (int, float):
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if finite:
                result.append({'pointer': pointer, 'value': value})
        elif isinstance(value, dict):
            stack.extend((pointer + '/' + str(k).replace('~', '~0').replace('/', '~1'), v, depth + 1)
                         for k, v in reversed(list(value.items())))
        elif isinstance(value, list):
            stack.extend((pointer + '/' + str(i), value[i], depth + 1) for i in reversed(range(len(value))))
    return result
