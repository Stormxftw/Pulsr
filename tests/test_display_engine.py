"""Expected values built from normalized dicts, independent of spec.normalize."""
import copy

import pytest

from pulse_rings import display
from pulse_rings.engine import compute_ring


def item(value='main.used', **changes):
    return dict(value=value, label=value.split('.')[1].replace('_', ' ').capitalize(),
                min=0, max='auto', auto_window='7d') | changes


def definition(*blocks):
    return {'pulse': 1, 'display': list(blocks)}


def sample(ts, value=None, **metrics):
    return {'ts': ts, 'metrics': {'used': value, **metrics},
            'baselines': {}, 'unknown_reasons': {}}


def feeds(current=10, history=(), *, ts=7200, error=None, **metrics):
    return {'main': {'current': sample(ts, current, **metrics),
                     'history': list(history), 'status': {'error': error}}}


def row(spec=None, data=None):
    return display.compute_display(definition({'type': 'bar', **(spec or item(max=20))}),
                                   data if data is not None else feeds())[0]['items'][0]


def test_legacy_definition_has_no_display():
    assert display.compute_display({'pulse': 1}, {}) is None


def test_fixed_row_exact_and_inputs_unchanged():
    spec = definition({'type': 'bar', **item(max=20, unit='calls', style={'color': 'ok'})})
    data = feeds()
    original = copy.deepcopy((spec, data))
    assert display.compute_display(spec, data) == [{
        'type': 'bar', 'label': 'Used', 'style': {'color': 'ok'}, 'index': 0,
        'items': [{
            'ref': 'main.used', 'feed': 'main', 'metric': 'used', 'label': 'Used',
            'value': 10, 'value_text': '10 calls', 'unit': 'calls', 'unknown': False,
            'reason': None, 'min': 0, 'max': 20, 'fill': 50, 'over': False,
            'under': False, 'learning': False, 'tone': None, 'ticks': [],
            'range': {'min_form': 'fixed', 'max_form': 'fixed',
                      'window_seconds': 604800, 'samples': 1},
            'caption': '50% of 20', 'style': {'color': 'ok'},
        }],
    }]
    assert (spec, data) == original


@pytest.mark.parametrize('x,up,down', [
    (0, 0, 0), (1e-13, 1e-13, 0), (.99, 1, .5), (1, 1, 1),
    (1.0000000001, 1, 1), (2, 2, 2), (2.4, 2.5, 2), (2.5, 2.5, 2.5),
    (2.6, 5, 2.5), (5, 5, 5), (7, 10, 5), (10, 10, 10),
    (99, 100, 50), (101, 200, 100), (.0023, .0025, .002),
    (-2.4, 0, -2.5), (-.99, 0, -1),
])
def test_nice_boundaries(x, up, down):
    assert display.nice_up(x) == up
    assert display.nice_down(x) == down


# Every scale form sees measured, zero, unknown, over, under, and negative data.
@pytest.mark.parametrize('scale', ['fixed', 'ref', 'auto', 'usual', 'min_auto'])
@pytest.mark.parametrize('value', [10, 0, None, 30, -10, -2])
def test_scale_value_matrix(scale, value):
    specs = {
        'fixed': item(min=-5, max=20),
        'ref': item(min='main.floor', max='main.limit'),
        'auto': item(min=-5),
        'usual': item(max='usual'),
        'min_auto': item(min='auto', max=20),
    }
    data = feeds(value, [sample(0, -4 if scale == 'min_auto' else 10),
                         sample(1800, 10), sample(3600, 10)], floor=-5, limit=20)
    result = row(specs[scale], data)
    lo = 0 if scale == 'usual' else -10 if scale == 'min_auto' and value == -10 else -5
    hi = (50 if value == 30 else 10) if scale == 'auto' else 20
    assert (result['min'], result['max']) == (lo, hi)
    assert not result['learning']
    assert result['unknown'] == (value is None)
    assert result['fill'] == (None if value is None else
                              pytest.approx(max(0, min(100, 100 * (value - lo) / (hi - lo)))))
    assert result['over'] == (value is not None and value > hi)
    assert result['under'] == (value is not None and value < lo)
    if value is None:
        assert result['tone'] is None
        assert result['caption'] == 'Not measured'


@pytest.mark.parametrize('bound', ['min', 'max'])
@pytest.mark.parametrize('bad', [None, float('nan'), float('inf'), True, '20'])
def test_unknown_ref_bounds(bound, bad):
    spec = item(max=20) | {bound: 'main.bound'}
    result = row(spec, feeds(bound=bad))
    assert result['caption'] == 'Range unavailable'
    assert result['fill'] is None
    assert not result['learning']


@pytest.mark.parametrize('bound', [0, -1])
def test_ref_max_not_above_min(bound):
    result = row(item(max='main.bound'), feeds(bound=bound))
    assert result['caption'] == 'Range unavailable'
    assert result['fill'] is None


def test_ref_failure_precedes_auto_learning():
    result = row(item(min='auto', max='main.limit'), feeds(limit=None))
    assert not result['learning']
    assert result['caption'] == 'Range unavailable'


@pytest.mark.parametrize('count,span,learning', [
    (0, 7200, True), (1, 7200, True), (2, 7200, True),
    (3, 3599, True), (3, 3600, False), (3, 7200, False),
])
@pytest.mark.parametrize('auto', ['min', 'max', 'both'])
def test_auto_learning_gate(count, span, learning, auto):
    # Null samples do not contribute to count or span.
    history = [sample(7200 - span + i * span / 2, 10) for i in range(max(0, count - 1))]
    data = feeds(10 if count else None, [sample(-100, None), *history])
    spec = item(min='auto' if auto in ('min', 'both') else 0,
                max='auto' if auto in ('max', 'both') else 20)
    result = row(spec, data)
    assert result['learning'] is learning
    assert result['range']['samples'] == count
    if learning:
        assert result['fill'] is None
        assert result['caption'] == ('Not measured' if not count else f'Learning range · {count} samples')


@pytest.mark.parametrize('history,learning,maximum', [
    ([], True, None), ([sample(7100, None)], True, None),
    ([sample(7100, 0)], True, 0), ([sample(7100, -1)], True, -2),
    ([sample(7100, 10)], False, 20),
    ([sample(7000, 10), sample(7100, 20)], False, 30),
    ([sample(6900, 10), sample(7000, 30), sample(7100, 20)], False, 40),
])
def test_usual_gate_has_no_hour_or_three_sample_requirement(history, learning, maximum):
    result = row(item(max='usual'), feeds(10, history))
    assert result['learning'] is learning
    assert result['max'] == (None if learning else maximum)
    assert result['ticks'] == [50]
    if learning:
        assert result['caption'] == 'Baseline not ready'
        assert result['fill'] is None


def test_window_boundary_age_out_old_extreme_and_all_zero():
    spec = item(auto_window='1h')
    result = row(spec, feeds(10, [sample(3599, 999), sample(3600, 10), sample(5400, 10)]))
    assert result['max'] == 10
    assert result['range']['samples'] == 3
    assert not result['learning']
    assert result['caption'] == 'auto 0–10 · 1h'
    result = row(spec, feeds(0, [sample(3600, 0), sample(5400, 0)]))
    assert (result['min'], result['max'], result['fill'], result['learning']) == (0, 1, 0, False)
    assert result['value_text'] == '0'


@pytest.mark.parametrize('spec,value,expected', [
    (item(max=20), 10.1, '51% of 20'),
    (item(max=20), 30, '150% of 20 · above max'),
    (item(min=5, max=20), 0, '0% of 20 · below min'),
    (item(max=20), -.1, '-1% of 20 · below min'),
    (item(max='main.order_limit'), 10, '50% of order limit'),
    (item(max='usual'), 10, '100% of usual'),
    (item(max='usual'), 19.95, '200% of usual'),
    (item(max='usual'), 20, '2.0× usual'),
    (item(max='usual'), 25, '2.5× usual · above max'),
    (item(min=5), 0, 'auto 5–10 · 168h · below min'),
])
def test_exact_captions(spec, value, expected):
    assert row(spec, feeds(value, [sample(0, 10), sample(3600, 10)], order_limit=20))['caption'] == expected


@pytest.mark.parametrize('direction,values,tones', [
    ('up', [0, 5, 10, 20], ['ok', 'warn', 'crit', 'crit']),
    ('down', [20, 10, 5, 0], ['ok', 'warn', 'crit', 'crit']),
])
def test_zone_tones_and_ticks(direction, values, tones):
    zones = {'warn': 5 if direction == 'up' else 10,
             'crit': 10 if direction == 'up' else 5, 'direction': direction}
    for value, tone in zip(values, tones):
        result = row(item(max=20, zones=zones), feeds(value))
        assert result['tone'] == tone
        assert result['ticks'] == ([25, 50] if direction == 'up' else [50, 25])
    result = row(item(max=20, zones=zones), feeds(None))
    assert result['tone'] is None and result['fill'] is None


def test_ticks_clamped_and_single_thresholds():
    result = row(item(min=5, max=20, zones={'warn': -10, 'crit': 30, 'direction': 'up'}))
    assert result['ticks'] == [0, 100]
    assert row(item(max=20, zones={'crit': 10, 'direction': 'up'}))['tone'] == 'crit'
    assert row(item(max=20, zones={'warn': 10, 'direction': 'down'}))['tone'] == 'warn'


def test_shared_bars_union_and_independent_ranges():
    data = feeds(10, [sample(0, 10, other=100), sample(3600, 10, other=200)], other=200)
    children = [item(), item('main.other', style={'color': '#abc'})]
    shared = {'type': 'bars', 'label': 'Together', 'scale': 'shared',
              'min': 0, 'max': 'auto', 'auto_window': '7d', 'bars': children}
    independent = {'type': 'bars', 'scale': 'independent', 'bars': children}
    rings = {'type': 'rings', 'rings': children}
    result = display.compute_display(definition(shared, independent, rings), data)
    assert [(i['min'], i['max'], i['fill']) for i in result[0]['items']] == [(0, 200, 5), (0, 200, 100)]
    assert [i['range']['samples'] for i in result[0]['items']] == [6, 6]
    assert [(i['max'], i['fill']) for i in result[1]['items']] == [(10, 100), (200, 100)]
    assert [i['max'] for i in result[2]['items']] == [10, 200]
    assert [b['index'] for b in result] == [0, 1, 2]
    assert result[0]['label'] == 'Together'
    assert result[1]['label'] is None
    assert result[0]['items'][1]['style'] == {'color': '#abc'}
    assert result[2]['style'] == {}


def test_shared_auto_min_and_ref_max_across_feeds():
    data = feeds(10, [sample(0, -4), sample(3600, 5)], limit=30)
    data['other'] = {'current': sample(7200, 20), 'history': [sample(0, -9)], 'status': {}}
    block = {'type': 'bars', 'scale': 'shared', 'min': 'auto', 'max': 'main.limit',
             'auto_window': '7d', 'bars': [item(), item('other.used')]}
    rows = display.compute_display(definition(block), data)[0]['items']
    assert [(r['min'], r['max'], r['fill']) for r in rows] == [(-10, 30, 50), (-10, 30, 75)]


@pytest.mark.parametrize('current,reason,error,expected', [
    (None, 'Permission denied', 'Fetch failed', 'Permission denied'),
    (None, None, 'Fetch failed', 'Fetch failed'),
    (None, None, None, 'Not measured'),
    (0, 'Old warning', 'Fetch failed', None),
])
def test_unknown_reason_precedence(current, reason, error, expected):
    data = feeds(current, error=error)
    data['main']['current']['unknown_reasons']['used'] = reason
    result = row(data=data)
    assert result['reason'] == expected
    assert result['unknown'] == (current is None)


def test_missing_current_uses_pulse_latest_clock_not_wall_time():
    data = feeds(10, [sample(0, 1000), sample(3600, 10), sample(5400, 10)], error='Offline')
    data['main']['current'] = None
    data['other'] = {'current': sample(7200, 5), 'history': [], 'status': {}}
    result = row(item(auto_window='1h'), data)
    assert result['unknown'] and result['reason'] == 'Offline'
    assert result['fill'] is None and result['tone'] is None
    assert result['max'] is None  # Provisional bounds are not exposed while learning.
    assert result['range']['samples'] == 2
    assert result['learning']


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), float('-inf'), True, '10'])
def test_non_numeric_values_are_unknown(bad):
    result = row(data=feeds(bad))
    assert result['value'] is None and result['value_text'] is None
    assert result['fill'] is None and result['tone'] is None


@pytest.mark.parametrize('delta_vs,expected,text', [('usual', 5, '+5'), ('previous', 0, '0')])
def test_stat_delta(delta_vs, expected, text):
    block = {'type': 'stat', 'value': 'main.used', 'label': 'Used', 'show': 'both',
             'delta_vs': delta_vs, 'auto_window': '1h'}
    result = display.compute_display(definition(block), feeds(20, [sample(3599, 1000), sample(3600, 10), sample(5400, 20)]))[0]
    assert result == {'type': 'stat', 'label': 'Used', 'ref': 'main.used', 'value': 20,
                      'value_text': '20', 'unit': '', 'unknown': False, 'reason': None,
                      'delta': expected, 'delta_text': text, 'delta_vs': delta_vs,
                      'caption': f'vs {delta_vs}', 'show': 'both', 'style': {}, 'index': 0}


@pytest.mark.parametrize('show', ['value', 'delta', 'both'])
def test_stat_learning_unknown_negative_delta_decimals_and_unit(show):
    block = {'type': 'stat', 'value': 'main.used', 'label': 'Used', 'show': show,
             'delta_vs': 'usual', 'auto_window': '7d', 'decimals': 2, 'unit': 'GB'}
    result = display.compute_display(definition(block), feeds(1.125))[0]
    assert result['value_text'] == '1.13 GB'
    assert result['delta'] is None and result['delta_text'] is None
    assert result['caption'] == 'Learning baseline' and not result['unknown']
    assert result['show'] == show
    result = display.compute_display(definition(block), feeds(1.125, [sample(3600, 2.5)]))[0]
    assert result['delta'] == -1.375
    assert result['delta_text'] == '−1.38 GB'
    result = display.compute_display(definition(block), feeds(None, [sample(3600, 2.5)], error='Offline'))[0]
    assert result['unknown'] and result['reason'] == 'Offline'
    assert result['delta'] is None and result['delta_text'] is None
    assert result['caption'] == 'Not measured'


def test_spark_null_gaps_extrema_last_n_and_current_last():
    block = {'type': 'spark', 'label': 'Used', 'value': 'main.used', 'points': 8, 'style': {'dot': 'last'}}
    history = [sample(i, v) for i, v in enumerate([999, -999, 2, None, -2, 5, None, 3, 4])]
    result = display.compute_display(definition(block), feeds(None, history, ts=9))[0]
    assert result == {'type': 'spark', 'label': 'Used', 'ref': 'main.used',
                      'points': [{'ts': i, 'value': v} for i, v in enumerate([2, None, -2, 5, None, 3, 4, None], 2)],
                      'lo': -2, 'hi': 5, 'unknown': True, 'style': {'dot': 'last'}, 'index': 0}
    result = display.compute_display(definition(block), feeds(None))[0]
    assert result['lo'] is None and result['hi'] is None
    data = feeds()
    data['main']['current'] = None
    result = display.compute_display(definition(block), data)[0]
    assert result['points'] == [] and result['unknown']


def test_score_exactly_reuses_compute_ring_with_bare_names():
    components = [
        {'metric': 'main.used', 'type': 'delta', 'weight': 60, 'baseline': 'median',
         'window': '2h', 'floor': 1, 'sensitivity': 1, 'direction': 'both'},
        {'metric': 'main.other', 'type': 'level', 'weight': 40, 'full_at': 20},
    ]
    block = {'type': 'score', 'label': 'Health', 'components': components, 'style': {'color': 'accent'}}
    data = feeds(20, [sample(0, 10, other=10), sample(3600, 10, other=10)], other=10)
    original = copy.deepcopy(block)
    expected = compute_ring({'ring': {'components': [{**c, 'metric': c['metric'].split('.')[1]} for c in components]}},
                            data['main']['current'], data['main']['history'])
    assert display.compute_display(definition(block), data) == [
        {'type': 'score', 'label': 'Health', 'ring': expected, 'style': {'color': 'accent'}, 'index': 0}]
    assert block == original


def test_score_with_no_current_is_unknown_and_uses_feed_error():
    block = {'type': 'score', 'components': [{'metric': 'main.used', 'type': 'level', 'weight': 100, 'full_at': 20}]}
    data = feeds(error='Offline')
    data['main']['current'] = None
    result = display.compute_display(definition(block), data)[0]['ring']
    assert result['unknown'] and result['components'][0]['reason'] == 'Offline'


def test_exported_helpers_match_compute_display():
    spec, data = item(max=20), feeds()
    scale = display.resolve_scale(spec, data)
    assert display.item_row(spec, data, scale=scale) == row(spec, data)


@pytest.mark.parametrize('count', [0, 1, 2, 3])
@pytest.mark.parametrize('maximum', [20, 'main.limit'])
def test_declared_ranges_never_learn(count, maximum):
    history = [sample(i, 5) for i in range(count)]
    result = row(item(max=maximum), feeds(10, history, limit=20))
    assert result['fill'] == 50 and not result['learning']


def test_usual_decimal_ratio_uses_existing_capsule_float_format():
    result = row(item(max='usual'), feeds(25.5, [sample(3600, 10)]))
    assert result['caption'] == '2.5× usual · above max'


def test_shared_clock_includes_missing_feed_fallback():
    data = feeds(10, [sample(3000, 1000), sample(3600, 10), sample(4500, 10)], ts=5400)
    data['missing'] = {'current': None, 'history': [], 'status': {'error': 'Offline'}}
    data['latest'] = {'current': sample(7200, 1), 'history': [], 'status': {}}
    block = {'type': 'bars', 'scale': 'shared', 'min': 0, 'max': 'auto',
             'auto_window': '1h', 'bars': [item(), item('missing.used')]}
    results = display.compute_display(definition(block), data)[0]['items']
    assert [r['max'] for r in results] == [None, None]
    # Still prove the clock excludes the old extreme internally.
    assert display.resolve_scale(block, data, items=block['bars'])['max'] == 10
    assert [r['range']['samples'] for r in results] == [3, 3]


def test_zero_max_negative_range_keeps_geometry_without_dividing_by_zero():
    result = row(item(min=-10, max=0), feeds(-5))
    assert result['fill'] == 50
    assert result['caption'] == 'Range unavailable'


def test_unavailable_after_auto_gate_and_measured_tone_is_independent():
    result = row(item(min='auto', max=5, zones={'warn': 10, 'direction': 'up'}),
                 feeds(10, [sample(0, 10), sample(3600, 10)]))
    assert result['fill'] is None and not result['learning']
    assert result['caption'] == 'Range unavailable'
    assert result['tone'] == 'warn' and result['ticks'] == []


def test_shared_duplicate_binding_does_not_multiply_learning_evidence():
    block = {'type': 'bars', 'scale': 'shared', 'min': 0, 'max': 'auto',
             'auto_window': '7d', 'bars': [item(), item()]}
    result = display.compute_display(definition(block), feeds(10, [sample(0, 10)]))[0]
    assert all(r['learning'] and r['range']['samples'] == 2 for r in result['items'])


def test_returned_styles_and_ranges_are_not_input_or_sibling_aliases():
    spec = definition({'type': 'bars', 'scale': 'shared', 'min': 0, 'max': 20,
                       'auto_window': '7d', 'style': {'color': 'ok'},
                       'bars': [item(style={'color': 'warn'}), item('main.other')]})
    result = display.compute_display(spec, feeds(other=5))
    result[0]['style']['color'] = 'crit'
    result[0]['items'][0]['style']['color'] = 'crit'
    result[0]['items'][0]['range']['samples'] = 999
    assert spec['display'][0]['style']['color'] == 'ok'
    assert spec['display'][0]['bars'][0]['style']['color'] == 'warn'
    assert result[0]['items'][1]['range']['samples'] == 2


def test_usual_window_age_out_and_current_exclusion():
    result = row(item(max='usual', auto_window='1h'),
                 feeds(100, [sample(3599, 1000), sample(3600, 10), sample(5400, 20)]))
    assert result['max'] == 30
    assert result['caption'] == '6.7× usual · above max'
    assert result['range']['samples'] == 3


@pytest.mark.parametrize('mode', ['usual', 'previous'])
def test_stat_skips_null_prior_and_accepts_zero_baseline(mode):
    block = {'type': 'stat', 'value': 'main.used', 'label': 'Used', 'show': 'delta',
             'delta_vs': mode, 'auto_window': '1h'}
    result = display.compute_display(definition(block),
                                    feeds(5, [sample(3600, 0), sample(5400, None)]))[0]
    assert result['delta'] == 5 and result['delta_text'] == '+5'
    assert result['caption'] == f'vs {mode}'


def test_spark_nonfinite_sample_is_a_gap_not_zero():
    block = {'type': 'spark', 'label': 'Used', 'value': 'main.used', 'points': 8}
    result = display.compute_display(definition(block),
                                    feeds(0, [sample(0, float('nan')), sample(3600, 5)]))[0]
    assert result['points'] == [{'ts': 0, 'value': None}, {'ts': 3600, 'value': 5}, {'ts': 7200, 'value': 0}]
    assert (result['lo'], result['hi'], result['unknown']) == (0, 5, False)


def test_shared_usual_uses_union_prior_median_and_one_range():
    block = {'type': 'bars', 'scale': 'shared', 'min': 0, 'max': 'usual',
             'auto_window': '1h', 'bars': [item(), item('main.other')]}
    data = feeds(10, [sample(3600, 10, other=30)], other=30)
    results = display.compute_display(definition(block), data)[0]['items']
    assert [(r['max'], r['fill'], r['caption']) for r in results] == [
        (40, 25, '50% of usual'), (40, 75, '150% of usual')]
    assert all(r['range']['samples'] == 4 and r['ticks'] == [50] for r in results)


def test_auto_both_zero_evidence_and_empty_evidence():
    spec = item(min='auto')
    result = row(spec, feeds(0, [sample(0, 0), sample(3600, 0)]))
    assert (result['min'], result['max'], result['fill'], result['learning']) == (0, 1, 0, False)
    result = row(spec, feeds(None))
    assert result['min'] is None and result['max'] is None
    assert result['learning'] and result['range']['samples'] == 0


def test_numeric_limits_keep_derived_scales_and_stat_json_finite():
    import json
    import sys

    assert display.nice_up(sys.float_info.max) == sys.float_info.max
    assert display.nice_down(-sys.float_info.max) == -sys.float_info.max
    data = feeds(1e308, [sample(0, 1e308), sample(3600, 1e308)])
    result = row(item(max='usual'), data)
    assert result['max'] == sys.float_info.max
    json.dumps(result, allow_nan=False)
    # An opposite-sign prior makes the stat delta unrepresentable as a float.
    block = {'type': 'stat', 'value': 'main.used', 'label': 'Used', 'show': 'both',
             'delta_vs': 'usual', 'auto_window': '7d', 'decimals': 3}
    result = display.compute_display(definition(block), feeds(1e308, [sample(0, -1e308)]))[0]
    assert result['delta'] is None and result['caption'] == 'Range unavailable'
    json.dumps(result, allow_nan=False)


def test_score_overflow_delta_is_null_and_json_finite():
    import json

    component = {'metric': 'main.used', 'type': 'delta', 'weight': 100,
                 'baseline': 'median', 'window': '1h', 'floor': 1,
                 'sensitivity': 1, 'direction': 'both'}
    data = feeds(1e308, [sample(0, -1e308)], ts=3600)
    result = display.compute_display(definition({'type': 'score', 'components': [component]}), data)[0]['ring']
    expected = compute_ring({'ring': {'components': [{**component, 'metric': 'used'}]}},
                            data['main']['current'], data['main']['history'])
    assert result == expected
    assert result['components'][0]['delta'] is None
    assert result['components'][0]['contribution'] == 100
    json.dumps(result, allow_nan=False)
