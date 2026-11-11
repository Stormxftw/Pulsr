"""Averages and differences from averages read as estimates, not false precision (Refs #60)."""
from pathlib import Path

import pytest

from pulse_rings import display
from pulse_rings.engine import _estimate, compute_lines, compute_ring
from pulse_rings.spec import normalize

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('value,signed,expected', [
    (55.92857142857143, False, '56'),      # a 14-day average of a count
    (57.5, False, '58'),                   # half rounds up
    (14769.5, False, '14,770'),
    (138.07142857142856, True, '+138'),
    (-57.5, True, '−58'),
    (0.4, True, '+0.4'),                   # below 10 one decimal keeps small counts honest
    (-2.64, True, '−2.6'),
    (9.96, False, '10'),
    (0.04, True, '0'),                     # rounds to nothing: no sign either
    (12, True, '+12'),
    (0, False, '0'),
    (None, False, 'unknown'),
])
def test_estimate_rounding(value, signed, expected):
    assert _estimate(value, signed=signed) == expected


def github_search():
    return normalize((ROOT / 'examples/b-github.pulse.yaml').read_text(encoding='utf-8'))


def test_usual_line_shows_a_source_average_without_noise_decimals():
    definition = github_search()
    current = {'ts': 7200, 'metrics': {'recent': 194, 'baseline': 55.92857142857143},
               'baselines': {'recent': 55.92857142857143}}
    ring = compute_ring(definition, current, [])
    labels = [line['label'] for line in compute_lines(definition, current, ring)]
    assert any(label.startswith('usual ≈56/') for label in labels), labels
    assert not any('55.9' in label for label in labels)
    # The measured number itself is never rounded or changed.
    assert ring['components'][0]['baseline'] == 55.92857142857143


def stat(value, usual, **spec):
    block = {'type': 'stat', 'value': 'main.used', 'label': 'Used', 'show': 'both',
             'delta_vs': 'usual', 'auto_window': '7d', **spec}
    definition = {'pulse': 1, 'display': [block]}
    feeds = {'main': {'current': {'ts': 7200, 'metrics': {'used': value}, 'baselines': {'used': usual},
                                  'unknown_reasons': {}}, 'history': [], 'status': {'error': None}}}
    return display.compute_display(definition, feeds)[0]


def test_count_versus_average_delta_is_a_whole_number():
    result = stat(194, 55.92857142857143)
    assert result['delta_text'] == '+138'
    assert result['delta'] == pytest.approx(138.07142857142856)  # the number is kept exact


def test_small_count_delta_keeps_one_decimal():
    assert stat(3, 2.6)['delta_text'] == '+0.4'
    assert stat(2, 2.6)['delta_text'] == '−0.6'


def test_fractional_measurements_keep_their_own_precision():
    # A non-integer measurement is not a count: its delta keeps the existing format.
    assert stat(1.125, 2.5)['delta_text'] == '−1.375'
    assert stat(1.125, 2.5, decimals=2, unit='GB')['delta_text'] == '−1.38 GB'


def test_explicit_decimals_still_win_for_counts():
    assert stat(194, 55.92857142857143, decimals=1)['delta_text'] == '+138.1'
