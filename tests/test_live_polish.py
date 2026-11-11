"""Regressions from the real status/render review (Refs #58–#68)."""
import json

import pytest

from pulse_rings.display import compute_display
from pulse_rings.engine import Engine, compute_capsule, compute_lines, compute_ring
from pulse_rings.spec import budget, normalize


def score(value, usual, metric='waiting', **changes):
    component = {'metric': metric, 'weight': 100, 'type': 'delta',
                 'baseline': 'source', **changes}
    return compute_ring({'ring': {'components': [component]}},
                        {'ts': 7200, 'metrics': {metric: value}, 'baselines': {metric: usual}}, [])


def test_small_count_noise_does_not_saturate_in_either_direction():
    for value, usual in [(0, 1), (2, 1), (1, 2)]:
        ring = score(value, usual)
        assert score(value, usual, metric='count')['score'] == ring['score']
        assert 0 < ring['score'] <= 20
        assert ring['components'][0]['delta'] == value - usual
        assert not ring['unknown'] and not ring['warming']


def test_zero_usual_with_activity_is_measured_but_not_comparable():
    ring = score(108, 0, metric='commits_week')
    assert ring['warming'] and not ring['unknown']
    assert ring['score'] == 0
    c = ring['components'][0]
    assert (c['value'], c['baseline'], c['delta']) == (108, 0, 108)
    assert c['reason'] == 'No positive usual yet'
    assert score(0, 0)['score'] == 0


def test_zero_usual_with_unknown_sibling_does_not_claim_measured_calm():
    d = {'ring': {'components': [
        {'metric': 'commits_week', 'weight': 80, 'type': 'delta', 'baseline': 'source'},
        {'metric': 'errors', 'weight': 20, 'type': 'level', 'full_at': 5}]}}
    ring = compute_ring(d, {'ts': 7200, 'metrics': {'commits_week': 108},
                            'baselines': {'commits_week': 0}}, [])
    assert ring['warming'] and not ring['unknown'] and ring['score'] == 0


def test_big_rise_stays_high_and_full_drop_is_not_maximum():
    assert score(182, 53.5, metric='recent')['score'] >= 70
    assert 0 < score(0, 100)['score'] <= 50
    assert score(0, 100, direction='up')['score'] == 0
    assert score(182, 53.5, direction='down')['score'] == 0
    json.dumps(score(1e308, 1), allow_nan=False)


def test_stat_usual_uses_source_average_but_previous_stays_local():
    d = normalize({'pulse': 1, 'title': 'Race',
                   'source': {'kind': 'github.search', 'params': {'repo': 'a/b', 'type': 'pr'}},
                   'display': [{'type': 'score', 'components': [{'metric': 'recent', 'type': 'delta', 'weight': 100, 'baseline': 'source'}]},
                               {'type': 'stat', 'value': 'recent', 'show': 'both'},
                               {'type': 'stat', 'value': 'recent', 'delta_vs': 'previous', 'show': 'both'}]})
    feeds = {'main': {'current': {'ts': 7200, 'metrics': {'recent': 182}, 'baselines': {'recent': 53.5}},
                      'history': [{'ts': 3600, 'metrics': {'recent': 165}}]}}
    rows = compute_display(d, feeds)
    assert rows[0]['ring']['components'][0]['baseline'] == 53.5
    assert rows[1]['delta'] == 128.5 and rows[1]['caption'] == 'vs usual'
    assert rows[2]['delta'] == 17 and rows[2]['caption'] == 'vs previous'


def test_count_usual_text_rounds_half_up_without_changing_numeric_baseline():
    ring = score(19864, 17777.5, metric='online')
    c = ring['components'][0]
    assert c['baseline'] == 17777.5
    assert c['baseline_text'] == '17,778'
    assert score(2.75, 1.25, metric='temperature')['components'][0]['baseline_text'] == '1.25'


def test_unknown_legacy_metric_labels_preserve_acronyms():
    d = normalize({'pulse': 1, 'title': 'Repo', 'source': {'kind': 'github.repo', 'params': {'repo': 'a/b'}}})
    current = {'ts': 7200, 'metrics': {}}
    ring = compute_ring(d, current, [])
    assert compute_lines(d, current, ring)[-1]['label'] == 'Open PRs unknown'
    d['capsule']['metric'] = 'open_prs'
    assert compute_capsule(d, current, ring)['label'] == 'Open PRs unknown'
    d['display'] = [{'type': 'stat', 'value': 'open_prs'}]
    assert normalize(d)['display'][0]['label'] == 'Open PRs'


def notification_definition():
    return normalize({'pulse': 1, 'title': 'Notifications',
                      'feeds': {'main': {'kind': 'desktop.notifications', 'params': {'apps': ['discord']}}},
                      'display': [{'type': 'bar', 'value': 'main.waiting', 'max': 'usual'},
                                  {'type': 'bar', 'value': 'main.minutes_since_last', 'unit': 'min'}]})


def test_learning_range_has_no_provisional_zero_range_and_duration_is_readable():
    d = notification_definition()
    data = {'main': {'current': {'ts': 7200, 'metrics': {'waiting': 0, 'minutes_since_last': 624.2}},
                     'history': [{'ts': 0, 'metrics': {'waiting': 0, 'minutes_since_last': 504.2}},
                                 {'ts': 3600, 'metrics': {'waiting': 0, 'minutes_since_last': 564.2}}]}}
    learning, duration = [r['items'][0] for r in compute_display(d, data)]
    assert learning['learning'] and learning['min'] is None and learning['max'] is None
    assert learning['range_text'] is None and learning['caption'] == 'Baseline not ready'
    assert duration['value_text'] == '10h 24m ago'
    assert duration['range_text'] == '0m–16h 40m'
    assert duration['caption'] == 'auto 0m–16h 40m · 168h'
    assert duration['fill'] == pytest.approx(62.42)


@pytest.mark.parametrize('explicit_feeds', [False, True])
def test_notifications_disclosure_has_short_summary_and_full_separate_text(tmp_path, explicit_feeds):
    d = notification_definition()
    if not explicit_feeds:
        d = normalize({'pulse': 1, 'title': 'Notifications',
                       'source': {'kind': 'desktop.notifications', 'params': {'apps': ['discord']}}})
    engine = Engine(tmp_path, clock=lambda: 7200)
    engine.activate(d)
    row = engine.status(poll=False, include_icons=False)['pulses'][0]
    preview = engine.preview(d, {'main': {'ts': 7200, 'metrics': {}}} if explicit_feeds else {'ts': 7200, 'metrics': {}}, budget(d))
    for result in [row, preview]:
        disclosure = result['notifications']
        assert disclosure['summary'] == 'Counts notifications still in Windows, not unread messages. Local only.'
        assert 'never message text' in disclosure['details']
        assert 'continuously watched full window' in disclosure['details']
        assert 'clear between polls' in disclosure['details']
