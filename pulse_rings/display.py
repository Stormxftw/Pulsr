"""Pure display rows for NORMALIZED pulse/1 definitions (spec/DISPLAY.md §4).

No clock, storage, validation, collection or renderer dependencies. Feed history
excludes current; all metric lookups use the existing engine's finite-number rule.
"""
import copy
from decimal import Decimal, ROUND_HALF_UP, localcontext
import sys

from .engine import _age_minutes, _estimate, _format, _window, compute_ring, number, seconds, value_of

__all__ = ['compute_display', 'nice_up', 'nice_down', 'resolve_scale', 'item_row']

_MAX_FLOAT = Decimal(str(sys.float_info.max))
_NICE = tuple(Decimal(str(n)) for n in (1, 2, 2.5, 5, 10))


def _decimal(value):
    return Decimal(str(value))


def _finite(value):
    """Keep derived magnitudes representable, including near the float limits."""
    return float(max(-_MAX_FLOAT, min(_MAX_FLOAT, value)))


def nice_up(x):
    """Round upward to 1/2/2.5/5/10, with the contract's relative tolerance."""
    if x <= 0:
        return 0
    value = _decimal(x)
    power = Decimal(10) ** value.adjusted()
    for step in _NICE:
        candidate = step * power
        if candidate * Decimal('1.000000001') >= value:
            return _finite(Decimal(format(candidate, '.12g')))
    raise AssertionError('Unreachable nice-number interval')


def nice_down(x):
    """Round a lower bound downward; tiny nonnegative values resolve to zero."""
    if x < 0:
        return -nice_up(-x)
    if x < 1e-12:
        return 0
    value = _decimal(x)
    power = Decimal(10) ** value.adjusted()
    return _finite(max(step * power for step in _NICE[:-1] if step * power <= value))


def _duration(value):
    # engine.seconds intentionally accepts only legacy s/m/h; display also has d.
    return int(value[:-1]) * 86400 if isinstance(value, str) and value.endswith('d') else seconds(value)


def _samples(feed):
    current = feed.get('current')
    return [*feed.get('history', []), *([current] if current is not None else [])]


def _latest(feeds):
    return max((s['ts'] for f in feeds.values() for s in _samples(f)), default=0)


def _now(refs, feeds):
    current = [feeds.get(ref.split('.')[0], {}).get('current') for ref in refs]
    latest = _latest(feeds)
    return max((s['ts'] if s is not None else latest for s in current), default=latest)


def _reading(ref, feeds):
    name, metric = ref.split('.')
    feed = feeds.get(name, {})
    current = feed.get('current')
    value = value_of(current, metric) if current is not None else None
    reason = None
    if value is None:
        reason = ((current or {}).get('unknown_reasons', {}).get(metric)
                  or (feed.get('status') or {}).get('error') or 'Not measured')
    return name, metric, value, reason


def _points(refs, feeds, now, window, *, prior=False):
    points = []
    # Repeating the same binding must not multiply the learning evidence.
    for ref in dict.fromkeys(refs):
        name, metric = ref.split('.')
        feed = feeds.get(name, {})
        samples = feed.get('history', []) if prior else _samples(feed)
        for sample in samples:
            ts = sample['ts']
            value = value_of(sample, metric)
            if ts >= now - window and (not prior or ts < now) and value is not None:
                points.append((ts, value))
    return points


def _median(values):
    ordered = sorted(values)
    mid = len(ordered) // 2
    return (ordered[mid] if len(ordered) % 2 else
            _finite((_decimal(ordered[mid - 1]) + _decimal(ordered[mid])) / 2))


def _form(bound):
    return bound if bound in ('auto', 'usual') else 'ref' if isinstance(bound, str) else 'fixed'


def resolve_scale(spec, feeds, *, items=None, now=None):
    """Resolve one item or a shared group's bounds without changing inputs.

    ``spec`` owns min/max/auto_window. ``items`` is the shared group's items (or
    omitted for one item). The returned dict can be passed to :func:`item_row`.
    ``now`` optionally selects the group's reference sample timestamp, never a
    wall-clock time. ``range.samples`` counts measured points, including current.
    """
    refs = [i['value'] for i in items] if items is not None else [spec['value']]
    now = _now(refs, feeds) if now is None else now
    window = _duration(spec['auto_window'])
    points = _points(refs, feeds, now, window)
    forms = {key: _form(spec[key]) for key in ('min', 'max')}
    baseline = None
    if forms['max'] == 'usual':
        prior = _points(refs, feeds, now, window, prior=True)
        baseline = _median([v for _, v in prior]) if prior else None

    def bound(key):
        form, raw = forms[key], spec[key]
        if form == 'fixed':
            return raw
        if form == 'ref':
            return _reading(raw, feeds)[2]
        if form == 'usual':
            return _finite(2 * _decimal(baseline)) if baseline is not None else None
        if not points:
            return None
        values = [v for _, v in points]
        return nice_down(min(values)) if key == 'min' else nice_up(max(values))

    lo, hi = bound('min'), bound('max')
    if forms['max'] == 'auto' and lo == 0 and hi == 0:
        hi = 1
    unavailable = any(forms[k] == 'ref' and v is None for k, v in [('min', lo), ('max', hi)])
    auto_learning = ('auto' in forms.values() and
                     (len(points) < 3 or max(t for t, _ in points) - min(t for t, _ in points) < 3600))
    usual_learning = forms['max'] == 'usual' and (baseline is None or baseline <= 0)
    learning = not unavailable and (auto_learning or usual_learning)
    if not learning and lo is not None and hi is not None and hi <= lo:
        unavailable = True
    return {'min': lo, 'max': hi, 'learning': learning, 'unavailable': unavailable,
            'baseline': baseline, 'range': {'min_form': forms['min'], 'max_form': forms['max'],
                                          'window_seconds': window, 'samples': len(points)}}


def _position(value, lo, hi):
    fraction = (_decimal(value) - _decimal(lo)) / (_decimal(hi) - _decimal(lo))
    return float(max(Decimal(0), min(Decimal(100), 100 * fraction)))


def _text(value, unit='', *, signed=False, decimals=None):
    if value is None:
        return None
    if decimals is None:
        text = _format(value, signed=signed)
    else:
        # Explicit stat precision is fixed-width, half up, with engine-style signs.
        magnitude = _decimal(abs(value) if signed else value)
        with localcontext() as context:
            context.prec = max(28, magnitude.adjusted() + decimals + 2)
            rounded = magnitude.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
        if rounded == 0:
            rounded = abs(rounded)  # Decimal retains a minus sign on quantized zero.
        sign = ('+' if value > 0 else '−' if value < 0 else '') if signed and rounded != 0 else ''
        text = sign + f'{rounded:,.{decimals}f}'
    return text + (f' {unit}' if unit else '')


def _delta_text(value, delta, unit, mode, decimals):
    # A count compared with its usual differs from an average, so the fraction is
    # noise ("+138", not "+138.071"). Fractional measurements and explicit
    # precision keep the standard format.
    count_vs_usual = (decimals is None and mode == 'usual' and delta is not None
                      and value is not None and value == int(value))
    if not count_vs_usual:
        return _text(delta, unit, signed=True, decimals=decimals)
    return _estimate(delta, signed=True) + (f' {unit}' if unit else '')


def _tone(value, zones):
    if value is None or not zones:
        return None
    down = zones.get('direction', 'up') == 'down'
    for key in ('crit', 'warn'):
        if key in zones and (value <= zones[key] if down else value >= zones[key]):
            return key
    return 'ok'


def _duration_item(spec):
    return spec.get('unit') == 'duration' or (spec.get('unit') == 'min' and spec['value'].split('.')[1] == 'minutes_since_last')


def _bound_text(spec, value):
    if _duration_item(spec) and value is not None and value >= 0:
        minutes = _decimal(value) * (60 if spec.get('unit') == 'duration' else 1)
        return _age_minutes(minutes).removesuffix(' ago')
    return _format(value)


def _caption(spec, scale, value, over, under):
    if value is None:
        return 'Not measured'
    form = scale['range']['max_form']
    if scale['unavailable']:
        return 'Range unavailable'
    if scale['learning']:
        return ('Baseline not ready' if form == 'usual' else
                f'Learning range · {scale["range"]["samples"]} samples')
    if form == 'auto':
        caption = f'auto {_bound_text(spec, scale["min"])}–{_bound_text(spec, scale["max"])} · {_window(scale["range"]["window_seconds"])}'
    else:
        denominator = scale['baseline'] if form == 'usual' else scale['max']
        if denominator == 0:
            # A valid negative-to-zero range has geometry but no max-relative ratio.
            caption = 'Range unavailable'
        else:
            ratio = _decimal(value) / _decimal(denominator)
            pct = int((100 * ratio).to_integral_value(rounding=ROUND_HALF_UP))
            if form == 'usual':
                # Preserve compute_capsule's float .1f rounding on ordinary ratios.
                ratio_text = float(ratio) if number(float(ratio)) is not None else ratio
                caption = f'{ratio_text:.1f}× usual' if ratio >= 2 else f'{pct}% of usual'
            elif form == 'ref':
                caption = f'{pct}% of {spec["max"].split(".")[1].replace("_", " ").lower()}'
            else:
                caption = f'{pct}% of {_bound_text(spec, scale["max"])}'
    return caption + (' · above max' if over else ' · below min' if under else '')


def item_row(spec, feeds, *, scale=None):
    """Return one item row; an optional pre-resolved scale enables shared bars."""
    scale = resolve_scale(spec, feeds) if scale is None else scale
    name, metric, value, reason = _reading(spec['value'], feeds)
    duration = _duration_item(spec)
    if duration and value is not None and value < 0:
        value, reason = None, 'Duration unavailable'
    lo, hi = scale['min'], scale['max']
    valid = not scale['learning'] and not scale['unavailable'] and lo is not None and hi is not None
    over = valid and value is not None and value > hi
    under = valid and value is not None and value < lo
    zones = spec.get('zones', {})
    ticks = ([50] if scale['range']['max_form'] == 'usual' else
             [_position(zones[k], lo, hi) for k in ('warn', 'crit') if k in zones] if valid else [])
    unit = spec.get('unit', '')
    value_text = (_bound_text(spec, value) + ' ago' if duration and value is not None else _text(value, unit))
    extra = ({'range_text': f'{_bound_text(spec, lo)}–{_bound_text(spec, hi)}' if valid else None}
             if duration or scale['learning'] else {})
    return {'ref': spec['value'], 'feed': name, 'metric': metric, 'label': spec['label'],
            'value': value, 'value_text': value_text, 'unit': unit,
            'unknown': value is None, 'reason': reason,
            'min': lo if not scale['learning'] else None, 'max': hi if not scale['learning'] else None,
            'fill': _position(value, lo, hi) if valid and value is not None else None,
            'over': over, 'under': under, 'learning': scale['learning'],
            'tone': _tone(value, zones), 'ticks': ticks, 'range': copy.deepcopy(scale['range']),
            'caption': _caption(spec, scale, value, over, under),
            'style': copy.deepcopy(spec.get('style', {})), **extra}


def _stat(spec, feeds):
    name, metric, value, reason = _reading(spec['value'], feeds)
    now = _now([spec['value']], feeds)
    prior = _points([spec['value']], feeds, now, _duration(spec['auto_window']), prior=True)
    mode = spec['delta_vs']
    baseline = None
    if prior:
        baseline = max(prior, key=lambda p: p[0])[1] if mode == 'previous' else _median([v for _, v in prior])
    # A source's measured historical average is the same usual used by scores.
    # Previous remains the last local sample, never the source average.
    source_baseline = number((feeds.get(name, {}).get('current') or {}).get('baselines', {}).get(metric))
    if mode == 'usual' and source_baseline is not None:
        baseline = source_baseline
    delta = number(value - baseline) if value is not None and baseline is not None else None
    unit = spec.get('unit', '')
    special = {}
    value_text = _text(value, unit, decimals=spec.get('decimals'))
    if 'states' in spec:
        entry = spec['states'].get(str(int(value))) if value is not None and value == int(value) else None
        value_text = entry if isinstance(entry, str) else entry.get('label') if isinstance(entry, dict) else None
        reason = reason if value is None else 'Unmapped state' if entry is None else None
        special = {'tone': entry.get('tone') if isinstance(entry, dict) else None, 'discrete': True}
        if entry is None:
            value = None
    elif unit == 'duration' or (unit == 'min' and spec['value'].split('.')[1] == 'minutes_since_last'):
        if value is not None and value >= 0:
            value_text = _age_minutes(_decimal(value) * (60 if unit == 'duration' else 1))
        else:
            value, value_text = None, None
            reason = reason or 'Duration unavailable'
        special = {'duration': True}
    if special:
        delta = None
    # A previous-sample comparison still waits for local history even when the
    # source has already measured its historical usual.
    learning_caption = ('Learning baseline' if source_baseline is None else
                        'Waiting for previous sample')
    return {'ref': spec['value'], 'value': value,
            'value_text': value_text,
            'unit': unit, 'unknown': value is None, 'reason': reason,
            'delta': delta, 'delta_text': _delta_text(value, delta, unit, mode, spec.get('decimals')),
            'delta_vs': mode, 'show': spec['show'],
            'caption': ((reason or 'Not measured') if special and value is None else 'Not measured' if value is None else '' if special else learning_caption if baseline is None
                        else 'Range unavailable' if delta is None else f'vs {mode}'), **special}


def _spark(spec, feeds):
    name, metric, value, _ = _reading(spec['value'], feeds)
    samples = _samples(feeds.get(name, {}))[-spec['points']:]
    points = [{'ts': s['ts'], 'value': value_of(s, metric)} for s in samples]
    measured = [p['value'] for p in points if p['value'] is not None]
    return {'ref': spec['value'], 'points': points, 'lo': min(measured, default=None),
            'hi': max(measured, default=None), 'unknown': value is None}


def _score(spec, feeds):
    name = spec['components'][0]['metric'].split('.')[0]
    feed = feeds.get(name, {})
    components = [{**c, 'metric': c['metric'].split('.')[1]} for c in spec['components']]
    current = feed.get('current')
    if current is None:
        current = {'ts': _latest(feeds), 'metrics': {}, 'unknown_reasons': {
            c['metric']: (feed.get('status') or {}).get('error') or 'Not measured' for c in components}}
    return compute_ring({'ring': {'components': components}}, current, feed.get('history', []))


def compute_display(definition, feeds):
    """Compute block rows, or None for a legacy definition without ``display``."""
    if 'display' not in definition:
        return None
    rows = []
    for index, spec in enumerate(definition['display']):
        kind = spec['type']
        row = {'type': kind, 'label': spec.get('label'),
               'style': copy.deepcopy(spec.get('style', {})), 'index': index}
        if kind == 'score':
            row['ring'] = _score(spec, feeds)
        elif kind == 'bar':
            row['items'] = [item_row(spec, feeds)]
        elif kind in ('rings', 'bars'):
            children = spec[kind]
            scale = None
            if kind == 'bars':
                row['scale'] = spec['scale']
                if spec['scale'] == 'shared':
                    scale = resolve_scale(spec, feeds, items=children)
            # Shared captions use the group's max form/reference, not child defaults.
            group = {k: spec[k] for k in ('min', 'max', 'auto_window')} if scale is not None else {}
            row['items'] = [item_row({**i, **group}, feeds, scale=scale) for i in children]
        elif kind == 'stat':
            row.update(_stat(spec, feeds))
        elif kind == 'spark':
            row.update(_spark(spec, feeds))
        else:
            raise ValueError(f'Unknown normalized display block: {kind}')
        rows.append(row)
    return rows
