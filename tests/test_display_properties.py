"""Deterministic property-style checks; no optional dependency is required."""
import json
import random

import pytest

from pulse_rings.display import compute_display, nice_down, nice_up, resolve_scale
from test_display_engine import definition, feeds, item, sample


def test_seeded_random_stream_invariants():
    randomizer = random.Random(1234)
    for _ in range(2000):
        ts = randomizer.randint(3600, 2_000_000)
        count = randomizer.randint(0, 40)
        times = sorted(randomizer.sample(range(ts - 800000, ts), count))
        values = [randomizer.choice([None, 0, randomizer.uniform(-1000, 10000)]) for _ in times]
        history = [sample(t, v, other=randomizer.choice([None, 0, randomizer.uniform(-1000, 10000)]))
                   for t, v in zip(times, values)]
        current = randomizer.choice([None, 0, randomizer.uniform(-1000, 10000)])
        data = feeds(current, history, ts=ts, limit=randomizer.choice([None, 100, 10000]),
                     other=randomizer.choice([None, 0, randomizer.uniform(-1000, 10000)]))
        window = randomizer.choice(['1h', '24h', '7d'])
        seconds = {'1h': 3600, '24h': 86400, '7d': 604800}[window]
        zones = {'warn': 100, 'crit': 1000, 'direction': 'up'}
        specs = [item(min=-1000, max='auto', auto_window=window, zones=zones),
                 item(min='auto', max='auto', auto_window=window, zones=zones),
                 item(max='usual', auto_window=window, zones=zones),
                 item(min=-500, max='main.limit', auto_window=window, zones=zones)]
        rows = compute_display(definition({'type': 'rings', 'rings': specs}), data)
        json.dumps(rows, allow_nan=False)
        for spec, row in zip(specs, rows[0]['items']):
            assert row['fill'] is None or 0 <= row['fill'] <= 100
            if current is None:
                assert row['unknown'] and row['fill'] is None and row['tone'] is None
            if spec['max'] == 'auto':
                measured = [v for t, v in [*zip(times, values), (ts, current)]
                            if t >= ts - seconds and v is not None]
                if measured:
                    # Refs #66: bounds remain internal until learning completes.
                    assert resolve_scale(spec, data)['max'] >= max(measured)
                    if row['learning']:
                        assert row['min'] is None and row['max'] is None
                    else:
                        assert row['max'] >= max(measured)

        # Cover every block shape in the same random stream, including shared ranges.
        children = [item(auto_window=window), item('main.other', auto_window=window)]
        blocks = definition(
            {'type': 'bars', 'scale': 'shared', 'min': 'auto', 'max': 'auto',
             'auto_window': window, 'bars': children},
            {'type': 'stat', 'label': 'Used', 'value': 'main.used', 'show': 'both',
             'delta_vs': randomizer.choice(['usual', 'previous']), 'auto_window': window},
            {'type': 'spark', 'label': 'Used', 'value': 'main.used', 'points': 8},
            {'type': 'score', 'components': [
                {'metric': 'main.used', 'type': 'delta', 'weight': 100, 'window': '24h',
                 'baseline': 'median', 'floor': 1, 'sensitivity': 1, 'direction': 'both'}]},
        )
        rows = compute_display(blocks, data)
        json.dumps(rows, allow_nan=False)
        for result in rows[0]['items']:
            assert result['fill'] is None or 0 <= result['fill'] <= 100
            if result['unknown']:
                assert result['fill'] is None and result['tone'] is None


def test_seeded_nice_rounding_invariants():
    randomizer = random.Random(1234)
    values = sorted(10 ** randomizer.uniform(-300, 300) for _ in range(2000))
    rounded = [nice_up(value) for value in values]
    assert rounded == sorted(rounded)
    for value, upper in zip(values, rounded):
        assert upper >= value
        assert nice_down(value) <= value
        assert nice_down(-value) <= -value


@pytest.mark.parametrize('value', [1.0000000001, 2.0000000001, 2.5000000001, 5.0000000001, 10.0000000001])
def test_nice_tolerance_is_explicit_not_a_strict_bound(value):
    # The specified 1e-9 tolerance deliberately permits a slightly inward bound.
    assert nice_up(value) >= value / (1 + 1e-9)
    assert nice_down(-value) <= -value / (1 + 1e-9)


@pytest.mark.parametrize('minimum,maximum,value', [
    (-1e308, 1e308, 0), (-1e308, 1e308, 1e308),
    (0, 1e-300, 1e308), (-1e308, -1e300, 1e308),
])
def test_finite_extreme_item_arithmetic(minimum, maximum, value):
    rows = compute_display(definition({'type': 'bar', **item(min=minimum, max=maximum)}), feeds(value))
    json.dumps(rows, allow_nan=False)
    assert 0 <= rows[0]['items'][0]['fill'] <= 100
