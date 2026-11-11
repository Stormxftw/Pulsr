"""Notification QA: synthetic counts/timestamps only; never notification content."""
import pytest

from pulse_rings import spec, templates
from pulse_rings.display import compute_display
from pulse_rings.engine import compute_capsule, compute_lines, compute_ring
from pulse_rings.layout import proposal_disclosure
from pulse_rings.sources import desktop_notifications as dn
from test_desktop_notifications import (NOW, DISCORD, TEAMS, Registry, add, definition,
                                        env, ft, make_store, poll)


def test_partial_selection_is_unknown_not_a_smaller_total(env):
    db, registry, adapter = env
    add(db, 1001)
    registry.enabled[TEAMS] = False
    result = poll(adapter, {}, NOW, definition({'apps': ['discord', 'teams']}))
    assert all(v is None for v in result.sample['metrics'].values())
    assert '1 of 2' in result.sample['unknown_reasons']['waiting']
    assert result.metadata['apps_unavailable'] == 1


def test_overflow_never_presents_truncated_hour_as_exact(env):
    _, _, adapter = env
    state = {'max_seen_id': 1000, 'last_added': [None], 'last_poll_ts': NOW - 60,
             'observed_since': NOW - 90000, 'apps': [DISCORD.lower()],
             'arrivals': [NOW - 100 + i * .01 for i in range(dn.MAX_ARRIVALS + 5)]}
    result = poll(adapter, state, NOW)
    assert result.sample['metrics']['new_1h'] is None
    assert 'count' in result.sample['unknown_reasons']['new_1h']
    # Once dropped observations cannot overlap this hour it can be exact again.
    state = result.state
    for step in range(1, 62):
        result = poll(adapter, state, NOW + step * 60)
        state = result.state
    assert result.sample['metrics']['new_1h'] == 0
    assert result.sample['metrics']['new_24h'] is None


def test_future_timestamp_is_not_a_fresh_notification(env):
    _, registry, adapter = env
    registry.stamps[DISCORD] = NOW + 3600
    result = poll(adapter, {}, NOW)
    assert result.sample['metrics']['minutes_since_last'] is None


def test_notification_labels_and_disclosure_explain_action_center():
    d = definition()
    current = {'ts': NOW, 'metrics': {'waiting': 0, 'new_1h': None, 'minutes_since_last': 187},
               'unknown_reasons': {'new_1h': dn.R_WARMING}}
    ring = compute_ring(d, current, [])
    assert compute_capsule(d, current, ring)['label'] == '0 in Action Center'
    assert 'Action Center' in templates.metric_info('main', 'waiting', d['source'])['label']
    disclosure = proposal_disclosure(d)['summary']
    assert 'not unread messages' in disclosure
    assert 'read-only' in disclosure and 'No network' in disclosure
    assert 'never message text' in disclosure
    assert 'Action Center' in next(t for t in templates.catalog() if t['id'] == 'notifications')['description']


def test_notification_labels_do_not_relabel_unrelated_sources():
    feed = {'kind': 'http_json', 'params': {'url': 'https://example.org/counts', 'metrics': {'waiting': '/waiting'}}}
    assert templates.metric_info('main', 'waiting', feed)['label'] == 'Waiting notifications'


def test_badge_selection_does_not_claim_action_center_toasts():
    d = definition({'apps': ['discord'], 'types': ['badge']})
    assert d['capsule']['label'] == '{value} in Windows'
    assert templates.metric_info('main', 'waiting', d['source'])['label'] == 'In Windows'
    assert spec.normalize(d) == d


def test_legacy_duration_and_unknown_reasons_are_readable():
    d = definition()
    current = {'ts': NOW, 'metrics': {'waiting': None, 'minutes_since_last': 187},
               'unknown_reasons': {'waiting': dn.R_PLATFORM, 'new_1h': dn.R_WARMING}}
    ring = compute_ring(d, current, [])
    assert compute_capsule(d, current, ring)['caption'] == dn.R_PLATFORM
    labels = [line['label'] for line in compute_lines(d, current, ring)]
    assert 'Last one 3h 7m ago' in labels
    assert dn.R_WARMING in labels


@pytest.mark.parametrize('minutes, expected', [(0, '0m ago'), (3, '3m ago'), (187, '3h 7m ago'),
                                               (2881, '2d 0h 1m ago'), (None, None)])
def test_notification_stat_duration_is_minutes_not_hours(minutes, expected):
    d = spec.normalize({'pulse': 1, 'title': 'Last notification',
                        'source': {'kind': 'desktop.notifications', 'params': {'apps': ['discord']}},
                        'display': [{'type': 'stat', 'value': 'minutes_since_last', 'unit': 'min'}]})
    row = compute_display(d, {'main': {'current': {'ts': NOW, 'metrics': {'minutes_since_last': minutes}},
                                     'history': []}})[0]
    assert row['value_text'] == expected
    assert row['delta_text'] is None
    assert row['unknown'] is (minutes is None)


def test_sqlite_wal_reads_latest_committed_counts_and_writer_is_untouched(tmp_path):
    path = tmp_path / 'wal.db'
    writer = make_store(path)
    try:
        writer.execute('PRAGMA journal_mode=WAL')
        add(writer, 1001)
        reader = dn.WindowsNotificationStore(path, Registry())
        assert len(reader.read([DISCORD], ['toast'], NOW).rows) == 1
        writer.execute("UPDATE Metadata SET Value=2000 WHERE Key='CurrentNotificationId'")
        assert reader.read([DISCORD], ['toast'], NOW).current_id == 1001
        writer.rollback()
        assert writer.execute('SELECT COUNT(Id) FROM Notification').fetchone()[0] == 1
    finally:
        writer.close()


def test_actual_exclusive_lock_defers_then_recovers(tmp_path):
    path = tmp_path / 'locked.db'
    writer = make_store(path)
    try:
        writer.execute('BEGIN EXCLUSIVE')
        adapter = dn.DesktopNotifications(reader=dn.WindowsNotificationStore(path, Registry()))
        with pytest.raises(dn.Deferred):
            poll(adapter, {}, NOW)
        writer.rollback()
        assert poll(adapter, {}, NOW).sample['metrics']['waiting'] == 0
    finally:
        writer.close()


def test_registered_empty_vs_never_registered(env):
    _, _, adapter = env
    assert poll(adapter, {}, NOW).sample['metrics']['waiting'] == 0
    result = poll(adapter, {}, NOW, definition({'app_ids': ['Unknown.App']}))
    assert result.sample['metrics']['waiting'] is None
    assert result.sample['unknown_reasons']['waiting'] == dn.R_UNREGISTERED


def test_complete_day_window_is_measured_zero_not_a_fabricated_startup_zero():
    class EmptyRegisteredApp:
        def read(self, *args):
            return dn.Snapshot(registered={DISCORD.lower()}, current_id=1000)
    adapter = dn.DesktopNotifications(reader=EmptyRegisteredApp())
    state = {}
    for minute in range(1441):
        result = poll(adapter, state, NOW + minute * 60)
        if minute < 1440:
            assert result.sample['metrics']['new_24h'] is None
        state = result.state
    assert result.sample['metrics']['new_1h'] == 0
    assert result.sample['metrics']['new_24h'] == 0
    assert result.sample['metrics']['minutes_since_last'] is None


def test_filetime_is_utc_and_does_not_depend_on_local_timezone():
    assert dn.filetime(ft(NOW - 187 * 60), NOW) == pytest.approx(NOW - 187 * 60)
    assert dn.filetime(0, NOW) is None
    assert dn.filetime(True, NOW) is None
    assert dn.filetime(10 ** 1000, NOW) is None
