"""Notification mode: the counts-and-times summary a notifications pulse is drawn from."""
import pytest

from pulse_rings.engine import Engine
from pulse_rings.inbox import summarize
from pulse_rings.sources.desktop_notifications import DesktopNotifications, Snapshot, R_GAP, R_MISSING

NOW = 1_794_189_600.0
HOUR, DAY = 3600, 86400
DISCORD = 'com.squirrel.discord.discord'


def sample(waiting=0, hour=0, day=0, minutes=None, reasons=None):
    return {'ts': NOW, 'metrics': {'waiting': waiting, 'new_1h': hour, 'new_24h': day, 'minutes_since_last': minutes},
            'unknown_reasons': reasons or {}}


def state(since=NOW - 2 * DAY, arrivals=(), reason='start'):
    return {'observed_since': since, 'since_reason': reason, 'arrivals': list(arrivals), 'last_poll_ts': NOW}


def test_waiting_and_the_time_of_the_last_notification():
    box = summarize(sample(waiting=2, minutes=187), state())
    assert box['waiting'] == 2 and box['reason'] is None
    assert box['last_ts'] == NOW - 187 * 60
    assert box['ts'] == NOW


def test_a_fully_watched_day_reports_hour_and_day_counts():
    arrivals = [NOW - 20 * HOUR, NOW - 5 * HOUR, NOW - 600]
    box = summarize(sample(hour=1, day=3, minutes=10), state(arrivals=arrivals))
    assert (box['hour'], box['day']) == (1, 3)
    assert box['complete'] is True and box['since'] == NOW - DAY and box['seen'] == 3


def test_a_partly_watched_day_says_since_when_instead_of_claiming_a_day():
    box = summarize(sample(hour=0, day=None, minutes=120, reasons={'new_24h': R_GAP}),
                    state(since=NOW - 3 * HOUR, arrivals=[NOW - 2 * HOUR], reason='gap'))
    assert box['day'] is None and box['hour'] == 0
    assert box['complete'] is False and box['since'] == NOW - 3 * HOUR and box['seen'] == 1


def test_marks_are_twenty_four_hourly_counts_ending_at_the_sample():
    arrivals = [NOW - 23.5 * HOUR, NOW - 90 * 60, NOW - 80 * 60, NOW - 30 * 60, NOW]
    box = summarize(sample(hour=2, day=5, minutes=0), state(arrivals=arrivals))
    assert len(box['marks']) == 24 and sum(box['marks']) == 5
    assert box['marks'][0] == 1 and box['marks'][-2] == 2 and box['marks'][-1] == 2


def test_marks_ignore_times_outside_the_day_and_junk():
    arrivals = [NOW - 2 * DAY, NOW + 60, 'yesterday', None, True, float('nan'), NOW - HOUR / 2]
    box = summarize(sample(hour=1, day=1, minutes=30), state(arrivals=arrivals))
    assert sum(box['marks']) == 1 and box['seen'] == 1


def test_an_unreadable_store_is_unknown_with_its_reason_not_zero():
    reasons = {m: R_MISSING for m in ('waiting', 'new_1h', 'new_24h', 'minutes_since_last')}
    box = summarize(sample(waiting=None, hour=None, day=None, reasons=reasons), {})
    assert box['waiting'] is None and box['reason'] == R_MISSING
    assert box['last_ts'] is None and box['hour'] is None and box['day'] is None
    assert box['seen'] == 0 and box['marks'] == [0] * 24 and box['complete'] is False


def test_no_sample_is_no_summary():
    assert summarize(None, {}) is None
    assert summarize({'ts': NOW, 'metrics': {}}, {})['waiting'] is None


def test_summary_is_numbers_only():
    box = summarize(sample(waiting=1, hour=1, day=1, minutes=5), state(arrivals=[NOW - 300]))
    assert set(box) == {'waiting', 'reason', 'last_ts', 'hour', 'day', 'seen', 'since', 'complete', 'marks', 'ts'}
    for key, value in box.items():
        assert value is None or isinstance(value, (int, float, bool, list)), key
    assert all(isinstance(n, int) and not isinstance(n, bool) for n in box['marks'])


class Reader:
    def read(self, aumids, types, now):
        return Snapshot(registered={DISCORD}, rows=[(DISCORD, i, 'toast', NOW - 187 * 60, None) for i in (1, 2)],
                        last_added={DISCORD: NOW - 187 * 60}, current_id=40)


@pytest.fixture
def engine(tmp_path):
    return Engine(tmp_path, clock=lambda: NOW, jitter=lambda: 0,
                  adapters={'desktop.notifications@1': DesktopNotifications(reader=Reader())})


SOURCE = {'kind': 'desktop.notifications', 'params': {'apps': ['discord']}}


def test_status_carries_the_summary_for_a_plain_notifications_pulse(engine):
    engine.activate({'pulse': 1, 'id': 'pings', 'title': 'Discord pings', 'source': SOURCE})
    engine.poll_one_due(previews=False)
    row = engine.status(poll=False)['pulses'][0]
    assert row['inbox']['waiting'] == 2 and row['inbox']['last_ts'] == NOW - 187 * 60
    assert row['inbox']['complete'] is False and row['inbox']['day'] is None
    # The agent-facing compact status keeps it: it is the pulse's actual reading.
    assert engine.status(poll=False, compact=True)['pulses'][0]['inbox']['waiting'] == 2


def test_status_carries_the_summary_for_a_designed_notifications_pulse(engine):
    engine.activate({'pulse': 1, 'id': 'designed', 'title': 'Discord pings', 'feeds': {'main': {**SOURCE, 'every': '1m'}},
                     'display': [{'type': 'stat', 'value': 'main.waiting', 'label': 'In Action Center'}]})
    engine.poll_one_due(previews=False)
    row = engine.status(poll=False)['pulses'][0]
    assert row['inbox']['waiting'] == 2 and len(row['inbox']['marks']) == 24


def test_a_pulse_never_sampled_has_no_summary(engine):
    engine.activate({'pulse': 1, 'id': 'pings', 'title': 'Discord pings', 'source': SOURCE})
    assert 'inbox' not in engine.status(poll=False)['pulses'][0]
