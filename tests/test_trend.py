"""Today-against-yesterday trend and the public voice summary (Refs #91). Display only."""
import json
from pathlib import Path

import pytest

from pulse_rings.sources.discord import DiscordSource, preset, voice_summary
from pulse_rings.trend import compute_trend

RAW = json.loads((Path(__file__).parent / 'fixtures/nousresearch.json').read_text())
GID = RAW['guild']['id']
CHANNEL, OTHER = '123456789012345678', '223456789012345678'
DEFINITION = preset('nousresearch', pulse_id='qa-trend', title='Trend QA')
SAMPLE = {'ts': 1000, 'metrics': {'online': 16082, 'members': 149800}, 'metadata': {'id': GID}}
DAY, NOW = 86400, 10 * 86400


class Net:
    def call(self, host, fn):
        return fn()


def wave(ts):
    """A plain daily cycle: 100 at the start of each day, 200 half a day later."""
    phase = (ts % DAY) / DAY
    return round(100 + 100 * (1 - abs(2 * phase - 1)))


def series(start, end, step=900, shift=0):
    return [{'ts': ts, 'metrics': {'online': wave(ts) + shift}} for ts in range(start, end + 1, step)]


def test_trend_compares_now_with_the_same_time_yesterday_not_the_cycle():
    # Two identical days: the daily wave swings 100..200, yet today equals yesterday.
    trend = compute_trend(series(NOW - 2 * DAY, NOW), 'online', NOW, integral=True)
    assert trend['metric'] == 'online' and trend['window_seconds'] == DAY
    assert trend['latest'] == {'ts': NOW, 'value': wave(NOW)}
    assert trend['yesterday']['value'] == pytest.approx(wave(NOW), abs=4)
    assert abs(trend['yesterday']['delta']) <= 4
    assert trend['yesterday']['ratio'] == pytest.approx(1, abs=0.05)
    assert trend['low']['value'] <= 104 and trend['high']['value'] >= 196  # the wave itself is still shown
    assert trend['low']['ts'] != trend['high']['ts']


def test_trend_reports_a_real_change_against_yesterday():
    # Same wave, but the last twelve hours run 30 higher than they did yesterday.
    samples = series(NOW - 2 * DAY, NOW - DAY // 2 - 1) + series(NOW - DAY // 2, NOW, shift=30)
    trend = compute_trend(samples, 'online', NOW, integral=True)
    assert trend['latest']['value'] == wave(NOW) + 30
    assert trend['yesterday']['delta'] == pytest.approx(30, abs=5)
    assert trend['yesterday']['ratio'] == pytest.approx(1.3, abs=0.06)


def test_trend_points_are_time_buckets_in_order_for_both_days():
    trend = compute_trend(series(NOW - 2 * DAY, NOW), 'online', NOW, integral=True)
    for key, lo, hi in (('points', NOW - DAY, NOW), ('previous', NOW - 2 * DAY, NOW - DAY)):
        points = trend[key]
        assert 40 <= len(points) <= 49, key
        assert all(lo <= p['ts'] <= hi for p in points), key
        assert [p['ts'] for p in points] == sorted(p['ts'] for p in points), key
        assert all(isinstance(p['value'], int) for p in points), key


def test_trend_keeps_gaps_instead_of_inventing_samples():
    # Collected only while the pane was open: nothing between 20h and 8h ago.
    samples = series(NOW - 22 * 3600, NOW - 20 * 3600) + series(NOW - 8 * 3600, NOW)
    trend = compute_trend(samples, 'online', NOW, integral=True)
    stamps = [p['ts'] for p in trend['points']]
    assert max(b - a for a, b in zip(stamps, stamps[1:])) >= 11 * 3600
    assert trend['previous'] == [] and trend['yesterday'] is None


def test_trend_without_yesterday_is_honest():
    trend = compute_trend(series(NOW - 6 * 3600, NOW), 'online', NOW, integral=True)
    assert trend['yesterday'] is None and trend['previous'] == []
    assert len(trend['points']) >= 2


def test_trend_day_ends_at_the_last_measurement_when_sampling_stopped():
    # Last sample two hours ago: the window and the comparison shift with it.
    last = NOW - 7200
    trend = compute_trend(series(NOW - 3 * DAY, last), 'online', NOW, integral=True)
    assert trend['latest'] == {'ts': last, 'value': wave(last)}
    assert trend['points'][0]['ts'] < last - DAY + 1800 and trend['points'][-1]['ts'] <= last
    assert trend['yesterday']['value'] == pytest.approx(wave(last), abs=4)
    assert all(p['ts'] < last - DAY for p in trend['previous'])
    assert trend['previous'][0]['ts'] < last - 2 * DAY + 1800  # the whole of yesterday, not cut at the wall clock
    # Nothing measured for more than a day: no trend is claimed.
    assert compute_trend(series(NOW - 3 * DAY, NOW - DAY - 900), 'online', NOW, integral=True) is None


def test_trend_needs_two_measured_points():
    assert compute_trend([], 'online', NOW, integral=True) is None
    assert compute_trend(series(NOW, NOW), 'online', NOW, integral=True) is None
    assert compute_trend(series(NOW - DAY, NOW), '', NOW, integral=True) is None
    unknown = [{'ts': NOW - 600, 'metrics': {'online': None}}, {'ts': NOW, 'metrics': {'online': True}}]
    assert compute_trend(unknown, 'online', NOW, integral=True) is None


def test_trend_never_divides_by_a_zero_yesterday():
    samples = [{'ts': ts, 'metrics': {'online': 0}} for ts in range(NOW - 2 * DAY, NOW - DAY + 3600, 900)] + series(NOW - DAY + 3600, NOW)
    trend = compute_trend(samples, 'online', NOW, integral=True)
    assert trend['yesterday']['value'] == 0 and trend['yesterday']['ratio'] is None


def test_trend_fractional_metrics_keep_one_decimal():
    samples = [{'ts': NOW - 1800, 'metrics': {'load': 1.26}}, {'ts': NOW, 'metrics': {'load': 2.04}}]
    trend = compute_trend(samples, 'load', NOW, integral=False)
    assert [p['value'] for p in trend['points']] == [1.3, 2.0]


def activated(tmp_path, now):
    from pulse_rings.engine import Engine
    engine = Engine(tmp_path, clock=lambda: now)
    engine.activate(DEFINITION)
    return engine


def test_bucketed_read_is_bounded_and_skips_non_numbers(tmp_path):
    engine = activated(tmp_path, NOW)
    with engine.store.transaction() as db:
        for ts in range(NOW - DAY, NOW, 30):          # 2,880 raw samples
            engine.store.insert_sample(db, DEFINITION['id'], {'ts': ts, 'metrics': {'online': 100, 'members': None}})
        engine.store.insert_sample(db, DEFINITION['id'], {'ts': NOW, 'metrics': {'online': True}})
        engine.store.insert_sample(db, DEFINITION['id'], {'ts': NOW - 3 * DAY, 'metrics': {'online': 5}})
    rows = engine.store.bucketed(DEFINITION['id'], 'online', NOW - 2 * DAY, 900)
    assert 96 <= len(rows) <= 97 and all(r['value'] == 100 for r in rows)
    assert [r['ts'] for r in rows] == sorted(r['ts'] for r in rows) and rows[0]['ts'] >= NOW - DAY
    assert engine.store.bucketed(DEFINITION['id'], 'members', NOW - 2 * DAY, 900) == []
    assert engine.store.bucketed(DEFINITION['id'], 'no"such', NOW - 2 * DAY, 900) == []
    assert engine.store.bucketed('missing', 'online', 0, 900) == []


def test_status_carries_trend_and_voice_and_compact_drops_the_trend(tmp_path):
    engine = activated(tmp_path, NOW)
    with engine.store.transaction() as db:
        for sample in series(NOW - 2 * DAY, NOW):
            sample['metrics']['members'] = 1000
            engine.store.insert_sample(db, DEFINITION['id'], sample)
        db.execute('UPDATE pulses SET last_ok_ts=?, source_state=?', (NOW, json.dumps({'widget_state': 'unavailable'})))
    row = engine.status()['pulses'][0]
    assert row['trend']['metric'] == 'online' and row['trend']['latest'] == {'ts': NOW, 'value': wave(NOW)}
    assert abs(row['trend']['yesterday']['delta']) <= 4 and len(row['trend']['previous']) >= 40
    assert row['voice'] == {'state': 'unavailable', 'users': None, 'channels': None, 'capped': False}
    # Display only: the ring still scores against its own baseline.
    assert row['ring']['components'][0]['baseline_mode'] == 'median'
    compact = engine.status(compact=True, include_icons=False)['pulses'][0]
    assert 'trend' not in compact and compact['voice'] == row['voice']


def test_status_trend_is_absent_before_two_points_exist(tmp_path):
    engine = activated(tmp_path, NOW)
    assert engine.status()['pulses'][0]['trend'] is None


def poll_widget(widget, now=1001):
    source = DiscordSource(fetch=lambda _: widget)
    return source.poll(DEFINITION, SAMPLE, {'invite_due': 1600}, now=now, net=Net()).state


def test_voice_summary_counts_people_and_channels_without_member_data():
    state = poll_widget({'id': GID, 'presence_count': 400, 'channels': [{'id': CHANNEL, 'name': 'General'}, {'id': OTHER, 'name': 'Music'}],
                         'members': [{'channel_id': CHANNEL, 'username': 'never persist me'}, {'channel_id': CHANNEL},
                                     {'channel_id': OTHER}, {'channel_id': None}, {}]})
    assert state['widget']['voice_users'] == 3 and state['widget']['listed'] == 5
    assert 'never persist me' not in json.dumps(state)
    assert voice_summary(DEFINITION, state, now=1001) == {'state': 'available', 'users': 3, 'channels': 2, 'capped': False}


def test_voice_summary_is_a_floor_when_the_member_list_is_full():
    members = [{'channel_id': CHANNEL}] * 4 + [{}] * 96
    state = poll_widget({'id': GID, 'presence_count': 13652, 'channels': [{'id': CHANNEL, 'name': 'General'}], 'members': members})
    assert voice_summary(DEFINITION, state, now=1001) == {'state': 'available', 'users': 4, 'channels': 1, 'capped': True}


def test_voice_summary_empty_widget_is_a_measured_zero():
    state = poll_widget({'channels': [], 'members': []})
    assert voice_summary(DEFINITION, state, now=1001) == {'state': 'available', 'users': 0, 'channels': 0, 'capped': False}


@pytest.mark.parametrize('state,expected', [
    ({'widget_state': 'unavailable'}, 'unavailable'),
    ({'widget_state': 'backoff'}, 'pending'),
    ({'widget_state': 'unchecked'}, 'pending'),
    ({}, 'pending'),
])
def test_voice_summary_says_when_voice_is_not_public_or_not_checked(state, expected):
    assert voice_summary(DEFINITION, state, now=1001) == {'state': expected, 'users': None, 'channels': None, 'capped': False}


def test_voice_summary_goes_stale_and_respects_voice_off():
    state = poll_widget({'channels': [], 'members': []})
    assert voice_summary(DEFINITION, state, now=1001 + 1801)['state'] == 'pending'
    off = json.loads(json.dumps(DEFINITION))
    off['source']['params']['voice'] = False
    assert voice_summary(off, state, now=1001) is None


def test_voice_summary_reads_state_saved_before_people_were_counted():
    old = {'widget_state': 'available', 'widget': {'ts': 1000, 'presence_count': 5, 'voice_channels': 2, 'channels': ['a', 'b']}}
    assert voice_summary(DEFINITION, old, now=1001) == {'state': 'available', 'users': None, 'channels': 2, 'capped': False}
