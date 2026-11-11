"""desktop.notifications: spec, privacy, observation and fail-closed tests.

Every test uses a synthetic store built here with the v8 column layout and an
injected registry. The real user notification database is never opened.
"""
import ast
import inspect
import json
import sqlite3
from pathlib import Path

import pytest

from pulse_rings import desktop_apps, spec
from pulse_rings.engine import Engine
from pulse_rings.kinds import KINDS
from pulse_rings.layout import proposal_disclosure
from pulse_rings.sources import desktop_notifications as dn
from pulse_rings.sources.base import Deferred, SourceError
from pulse_rings.sources.desktop_notifications import (DesktopNotifications, Snapshot,
                                                       WindowsNotificationStore)

NOW = 1_794_173_800.0
DISCORD = 'com.squirrel.Discord.Discord'
TEAMS = 'MSTeams_8wekyb3d8bbwe!MSTeams'


def ft(ts):
    return int((ts + dn.FILETIME_EPOCH) * 1e7)


def make_store(path, version=8, drop_column=None):
    db = sqlite3.connect(path)
    notification_cols = ['[Order] INTEGER PRIMARY KEY', 'Id INTEGER', 'HandlerId INTEGER', 'Type TEXT',
                         'Payload BLOB', 'Tag TEXT', '[Group] TEXT', 'ExpiryTime INT64', 'ArrivalTime INT64']
    if drop_column:
        notification_cols = [c for c in notification_cols if not c.startswith(drop_column)]
    db.executescript(f"""
        CREATE TABLE NotificationHandler (RecordId INTEGER PRIMARY KEY, PrimaryId TEXT NOT NULL COLLATE NOCASE,
            HandlerType TEXT);
        CREATE TABLE HandlerSettings (HandlerId INTEGER, SettingKey TEXT NOT NULL, Value INT);
        CREATE TABLE Notification ({', '.join(notification_cols)});
        CREATE TABLE NotificationData (NotificationId INTEGER, Key TEXT, Value TEXT);
        CREATE TABLE Metadata (Key TEXT PRIMARY KEY, Value INT64);
        PRAGMA user_version = {version};
    """)
    db.execute("INSERT INTO NotificationHandler VALUES (149, ?, 'app:desktop')", (DISCORD,))
    db.execute("INSERT INTO NotificationHandler VALUES (300, ?, 'app:immersive')", (TEAMS,))
    db.execute("INSERT INTO HandlerSettings VALUES (149, 's:toast', 1)")
    db.execute("INSERT INTO Metadata VALUES ('CurrentNotificationId', 1000)")
    db.commit()
    return db


def add(db, nid, handler=149, arrival=NOW, expiry=None, kind='toast', secret='hello from someone'):
    expiry = arrival + 3 * 86400 if expiry is None else expiry
    db.execute('INSERT INTO Notification (Id, HandlerId, Type, Payload, Tag, ArrivalTime, ExpiryTime) '
               'VALUES (?,?,?,?,?,?,?)', (nid, handler, kind, secret.encode(), secret, ft(arrival), ft(expiry)))
    db.execute("UPDATE Metadata SET Value=? WHERE Key='CurrentNotificationId'", (nid,))
    db.execute('INSERT INTO NotificationData VALUES (?, ?, ?)', (nid, 'body', secret))
    db.commit()


def clear(db, handler=149):
    db.execute('DELETE FROM Notification WHERE HandlerId=?', (handler,))
    db.commit()


class Registry:
    def __init__(self):
        self.toasts = True
        self.enabled = {}
        self.stamps = {}

    def toasts_enabled(self):
        return self.toasts

    def app_enabled(self, aumid):
        return self.enabled.get(aumid)

    def last_added(self, aumid):
        stamp = self.stamps.get(aumid)
        return None if stamp is None else ft(stamp)


def definition(params=None, every='1m'):
    return spec.normalize({'pulse': 1, 'title': 'Discord pings', 'every': every,
                           'source': {'kind': 'desktop.notifications', 'params': params or {'apps': ['discord']}}})


@pytest.fixture
def env(tmp_path):
    path = tmp_path / 'wpndatabase.db'
    db = make_store(path)
    registry = Registry()
    adapter = DesktopNotifications(reader=WindowsNotificationStore(path, registry))
    yield db, registry, adapter
    db.close()


def poll(adapter, state, now, defn=None):
    return adapter.poll(defn or definition(), None, state, now=now, net=None)


# ---------------------------------------------------------------- spec

def test_kind_contract():
    meta = KINDS['desktop.notifications']
    assert meta['hosts'] == [] and meta['calls_per_poll'] == 0 and meta['periodic_calls'] == []
    assert meta['pre_approval_sample'] is None and meta['min_every'] == 30 and meta['default_every'] == '1m'
    assert meta['metrics'] == ['waiting', 'new_1h', 'new_24h', 'minutes_since_last']
    assert meta['source_baselines'] == {}


def test_normalizes_with_preset_and_zero_budget():
    out = definition()
    assert out['source'] == {'kind': 'desktop.notifications', 'params': {'apps': ['discord'], 'types': ['toast']}}
    assert out['capsule']['metric'] == 'waiting' and out['icon'] == 'source'
    assert spec.normalize(out) == out
    assert spec.budget(out) == {'hosts': [], 'req_per_hour': 0.0, 'req_per_hour_display': 0}
    alias = {'pulse': 1, 'title': 'x', 'source': {'kind': 'desktop.notifications@1', 'params': {'app_ids': [DISCORD]}}}
    assert spec.normalize(alias)['source']['kind'] == 'desktop.notifications'


@pytest.mark.parametrize('params, path', [
    ({}, '/source/params'),
    ({'apps': []}, '/source/params/apps'),
    ({'apps': ['icq']}, '/source/params/apps/0'),
    ({'apps': ['discord', 'discord']}, '/source/params/apps'),
    ({'app_ids': [DISCORD, DISCORD.upper()]}, '/source/params/app_ids'),
    ({'app_ids': [' leading']}, '/source/params/app_ids/0'),
    ({'app_ids': ['trailing ']}, '/source/params/app_ids/0'),
    ({'app_ids': ['tab\there']}, '/source/params/app_ids/0'),
    ({'app_ids': ['x' * 201]}, '/source/params/app_ids/0'),
    ({'apps': ['discord'], 'types': ['tile']}, '/source/params/types/0'),
    ({'apps': ['discord'], 'types': ['toast', 'toast']}, '/source/params/types'),
    ({'apps': ['discord'], 'payload': True}, '/source/params/payload'),
    ({'apps': list(desktop_apps.ALIASES[:5]), 'app_ids': ['a', 'b', 'c', 'd']}, '/source/params'),
])
def test_param_errors_have_fixable_paths(params, path):
    errors = spec.validate({'pulse': 1, 'title': 'x', 'source': {'kind': 'desktop.notifications', 'params': params}})
    assert path in [e['path'] for e in errors], errors


def test_minimum_cadence_and_feeds_paths():
    errors = spec.validate({'pulse': 1, 'title': 'x', 'every': '10s',
                            'source': {'kind': 'desktop.notifications', 'params': {'apps': ['discord']}}})
    assert [e['path'] for e in errors] == ['/every']
    feeds = {'pulse': 1, 'title': 'x', 'feeds': {'dm': {'kind': 'desktop.notifications', 'params': {}}},
             'display': [{'type': 'stat', 'value': 'dm.waiting'}]}
    assert '/feeds/dm/params' in [e['path'] for e in spec.validate(feeds)]


def test_real_aumid_shapes_accepted():
    for aumid in ['Chrome', '{6D809377-6AF0-444B-8957-A3773F02200E}\\LGHUB\\lghub.exe',
                  '{6D809377-6AF0-444B-8957-A3773F02200E}/Voicemod Desktop/VoicemodDesktop.exe',
                  'Microsoft.MicrosoftEdge.Stable_8wekyb3d8bbwe!https://www.instagram.com/?utm_source=pwa&__pwa=1',
                  *[a for _, _, ids in desktop_apps.APPS.values() for a in ids]]:
        assert not spec.validate({'pulse': 1, 'title': 'x', 'source': {'kind': 'desktop.notifications',
                                                                       'params': {'app_ids': [aumid]}}}), aumid


def test_multi_feed_comparison_and_alert():
    value = spec.normalize({'pulse': 1, 'title': 'Pings', 'feeds': {
        'discord': {'kind': 'desktop.notifications', 'params': {'apps': ['discord']}},
        'teams': {'kind': 'desktop.notifications', 'params': {'apps': ['teams']}, 'every': '30s'}},
        'display': [{'type': 'bars', 'bars': [{'value': 'discord.waiting', 'label': 'Discord'},
                                              {'value': 'teams.waiting', 'label': 'Teams'}]}],
        'alert': {'metric': 'discord.waiting', 'above': 3, 'notify': 'toast'}})
    assert spec.budget(value)['req_per_hour'] == 0


def test_disclosure_names_local_read_and_exact_target():
    result = proposal_disclosure(definition({'apps': ['discord', 'teams'], 'app_ids': ['Chrome']}))
    row = result['feeds'][0]
    assert row['target'] == 'this PC · discord, teams, Chrome' and row['hosts'] == []
    assert 'never message text' in result['summary'] and 'No network' in result['summary']


def test_published_schema_matches_python():
    root = Path(__file__).resolve().parents[1]
    assert json.loads((root / 'spec/pulse-1.schema.json').read_text()) == spec.schema()


# ---------------------------------------------------------------- privacy

def test_adapter_sql_never_selects_content():
    source = inspect.getsource(dn)
    queries = [node.value for node in ast.walk(ast.parse(source))
               if isinstance(node, ast.Constant) and isinstance(node.value, str) and 'SELECT' in node.value]
    queries += [ast.unparse(node) for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.JoinedStr) and 'SELECT' in ast.unparse(node)]
    assert queries
    for query in queries:
        for banned in ('Payload', 'Tag', '[Group]', 'Group,', 'NotificationData', '*'):
            assert banned not in query, (banned, query)


def test_samples_state_metadata_hold_no_text(env):
    db, registry, adapter = env
    add(db, 1001, secret='SECRET-MESSAGE')
    registry.stamps[DISCORD] = NOW
    first = poll(adapter, {}, NOW)
    add(db, 1002, arrival=NOW + 30, secret='SECRET-MESSAGE-2')
    second = poll(adapter, first.state, NOW + 60)
    blob = json.dumps([first.sample, first.state, first.metadata, second.sample, second.state, second.metadata])
    assert 'SECRET' not in blob and 'hello' not in blob
    for value in second.sample['metrics'].values():
        assert value is None or isinstance(value, (int, float)) and not isinstance(value, bool)


def test_store_is_opened_read_only(env, tmp_path):
    db, registry, adapter = env
    add(db, 1001)
    path = tmp_path / 'wpndatabase.db'
    before = path.read_bytes()
    poll(adapter, {}, NOW)
    assert path.read_bytes() == before


def test_net_is_never_used(env):
    class NoNet:
        def __getattr__(self, name):
            raise AssertionError('desktop.notifications must not use net.' + name)
    _, _, adapter = env
    adapter.poll(definition(), None, {}, now=NOW, net=NoNet())


# ---------------------------------------------------------------- metrics

def test_waiting_counts_unexpired_selected_toasts(env):
    db, registry, adapter = env
    add(db, 1001)
    add(db, 1002)
    add(db, 1003, expiry=NOW - 5)            # expired
    add(db, 1004, handler=300)               # Teams, not selected
    add(db, 1005, kind='badge')              # badge, not selected by default
    result = poll(adapter, {}, NOW + 1)
    assert result.sample['metrics']['waiting'] == 2
    both = definition({'apps': ['discord'], 'types': ['toast', 'badge']})
    assert poll(adapter, {}, NOW + 1, both).sample['metrics']['waiting'] == 3


def test_measured_zero_is_zero(env):
    _, registry, adapter = env
    registry.stamps[DISCORD] = NOW - 600
    result = poll(adapter, {}, NOW)
    assert result.sample['metrics']['waiting'] == 0
    assert result.sample['metrics']['minutes_since_last'] == 10.0


def test_windows_unknown_until_observed_then_count_arrivals(env):
    db, registry, adapter = env
    registry.stamps[DISCORD] = NOW - 7200
    state, t, result = {}, NOW, None
    first = poll(adapter, state, t)
    assert first.sample['metrics']['new_1h'] is None
    assert first.sample['unknown_reasons']['new_1h'] == dn.R_WARMING
    state = first.state
    # A toast that stays in Action Center.
    add(db, 1001, arrival=t + 100)
    registry.stamps[DISCORD] = t + 100.2
    # A toast Discord clears before the next poll: only the registry stamp moves.
    for step in range(1, 62):
        t += 60
        if step == 30:
            registry.stamps[DISCORD] = t - 10
        result = poll(adapter, state, t)
        state = result.state
    # Window (t-3600, t]: the row that stayed (NOW+100) and the cleared one (stamp only).
    assert result.sample['metrics']['new_1h'] == 2
    assert result.sample['unknown_reasons'].get('new_1h') is None
    assert result.sample['metrics']['new_24h'] is None      # 24h not yet observed


def test_new_row_and_its_stamp_count_once(env):
    db, registry, adapter = env
    state = poll(adapter, {}, NOW).state
    add(db, 1001, arrival=NOW + 10)
    registry.stamps[DISCORD] = NOW + 10.3
    state = poll(adapter, state, NOW + 30).state
    assert state['arrivals'] == [pytest.approx(NOW + 10, abs=0.01)]


def test_two_rows_in_one_poll_both_count(env):
    db, registry, adapter = env
    state = poll(adapter, {}, NOW).state
    add(db, 1001, arrival=NOW + 10)
    add(db, 1002, arrival=NOW + 12)
    registry.stamps[DISCORD] = NOW + 12.2
    assert len(poll(adapter, state, NOW + 30).state['arrivals']) == 2


def test_gap_resets_observation(env):
    db, registry, adapter = env
    state, t = {}, NOW
    for _ in range(70):
        state = poll(adapter, state, t).state
        t += 60
    assert poll(adapter, state, t).sample['metrics']['new_1h'] == 0
    add(db, 1001, arrival=t + 100)
    result = poll(adapter, state, t + 1000)        # > max(3 x 60s, 300s): gap
    assert result.sample['metrics']['new_1h'] is None
    assert result.sample['unknown_reasons']['new_1h'] == dn.R_GAP
    assert len(result.state['arrivals']) == 1      # still-present rows are not lost
    assert result.sample['metrics']['waiting'] == 1


def test_clock_going_backwards_resets(env):
    _, _, adapter = env
    state = poll(adapter, {}, NOW).state
    assert poll(adapter, state, NOW - 100).state['observed_since'] == NOW - 100


def test_arrival_overflow_makes_24h_unknown(env):
    _, _, adapter = env
    state = {'max_seen_id': 1000, 'last_added': [None], 'last_poll_ts': NOW - 60,
             'observed_since': NOW - 90000, 'since_reason': 'start', 'apps': [DISCORD.lower()],
             'arrivals': [NOW - 100 + i * 0.01 for i in range(dn.MAX_ARRIVALS + 5)]}
    result = poll(adapter, state, NOW)
    assert len(result.state['arrivals']) == dn.MAX_ARRIVALS
    assert result.sample['metrics']['new_24h'] is None
    assert result.sample['unknown_reasons']['new_24h'] == dn.R_OVERFLOW
    assert result.sample['metrics']['new_1h'] is None
    assert result.sample['unknown_reasons']['new_1h'] == dn.R_OVERFLOW


# ---------------------------------------------------------------- fail closed

def _all_unknown(result, reason):
    assert all(v is None for v in result.sample['metrics'].values())
    assert set(result.sample['unknown_reasons'].values()) == {reason}


def test_non_windows_is_unknown_not_zero():
    adapter = DesktopNotifications(platform='linux')
    _all_unknown(adapter.poll(definition(), None, {}, now=NOW, net=None), dn.R_PLATFORM)


def test_global_toasts_off(env):
    _, registry, adapter = env
    registry.toasts = False
    _all_unknown(poll(adapter, {}, NOW), dn.R_GLOBAL_OFF)


def test_app_disabled_in_settings_or_store(env):
    db, registry, adapter = env
    registry.enabled[DISCORD] = False
    _all_unknown(poll(adapter, {}, NOW), dn.R_APP_OFF)
    registry.enabled[DISCORD] = None
    db.execute("UPDATE HandlerSettings SET Value=0 WHERE HandlerId=149")
    db.commit()
    _all_unknown(poll(adapter, {}, NOW), dn.R_APP_OFF)


def test_partial_apps_are_unknown_and_disclose_count(env):
    db, registry, adapter = env
    add(db, 1001)
    add(db, 1002, handler=300)
    registry.enabled[TEAMS] = False
    result = poll(adapter, {}, NOW, definition({'apps': ['discord', 'teams', 'slack']}))
    assert all(value is None for value in result.sample['metrics'].values())
    assert '1 of 3' in result.sample['unknown_reasons']['waiting']
    # Per selected app, not per ID variant: Discord reachable; Teams off; Slack absent.
    assert result.metadata['apps_watched'] == 1 and result.metadata['apps_unavailable'] == 2


def test_unregistered_app(env):
    _, _, adapter = env
    _all_unknown(poll(adapter, {}, NOW, definition({'app_ids': ['Some.Other.App']})), dn.R_UNREGISTERED)


def test_unsupported_version_and_missing_columns(tmp_path):
    for name, kwargs in [('v9.db', {'version': 9}), ('cols.db', {'drop_column': 'ArrivalTime'})]:
        path = tmp_path / name
        make_store(path, **kwargs).close()
        adapter = DesktopNotifications(reader=WindowsNotificationStore(path, Registry()))
        _all_unknown(poll(adapter, {}, NOW), dn.R_FORMAT)


def test_missing_store(tmp_path):
    adapter = DesktopNotifications(reader=WindowsNotificationStore(tmp_path / 'absent.db', Registry()))
    _all_unknown(poll(adapter, {}, NOW), dn.R_MISSING)


def test_implausible_filetimes_ignored(env):
    db, registry, adapter = env
    db.execute("INSERT INTO Notification (Id, HandlerId, Type, ArrivalTime, ExpiryTime) VALUES (1001, 149, 'toast', -5, 0)")
    db.commit()
    registry.stamps[DISCORD] = NOW + 10 * 86400   # in the future: ignored
    result = poll(adapter, {}, NOW)
    assert result.sample['metrics']['waiting'] == 1
    assert result.sample['metrics']['minutes_since_last'] is None
    assert result.sample['unknown_reasons']['minutes_since_last'] == dn.R_NEVER


def test_busy_store_defers_without_failure():
    class Busy:
        def read(self, *args):
            raise sqlite3.OperationalError('database is locked')
    with pytest.raises(Deferred):
        DesktopNotifications(reader=Busy()).poll(definition(), None, {}, now=NOW, net=None)


def test_unexpected_errors_are_sanitized():
    class Boom:
        def read(self, *args):
            raise RuntimeError('C:/Users/someone/secret path')
    with pytest.raises(SourceError) as exc:
        DesktopNotifications(reader=Boom()).poll(definition(), None, {}, now=NOW, net=None)
    assert 'secret' not in str(exc.value) and not isinstance(exc.value, Deferred)


def test_unknown_results_preserve_observation_state(env):
    _, registry, adapter = env
    state = poll(adapter, {}, NOW).state
    registry.toasts = False
    assert poll(adapter, state, NOW + 60).state == state


# ---------------------------------------------------------------- engine

def test_engine_registers_adapter_and_never_previews(tmp_path):
    reads = []

    class Spy:
        def read(self, *args):
            reads.append(args)
            return Snapshot()

    engine = Engine(tmp_path, adapters={'desktop.notifications@1': DesktopNotifications(reader=Spy())})
    assert 'desktop.notifications@1' in Engine(tmp_path / 'b').adapters
    draft_id = engine.propose({'pulse': 1, 'title': 'Discord pings',
                               'source': {'kind': 'desktop.notifications', 'params': {'apps': ['discord']}}},
                              origin={'kind': 'session'}, preview_allowed=True)
    assert not reads
    engine.status(poll=True)
    engine.status(poll=True)
    assert not reads, 'drafts must never read notifications before approval'
    assert str(draft_id).startswith('pd_')


def test_approved_pulse_polls_and_renders(env):
    db, registry, adapter = env
    add(db, 1001)
    add(db, 1002)
    registry.stamps[DISCORD] = NOW - 120
    from pulse_rings.engine import Engine
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        engine = Engine(root, clock=lambda: NOW, jitter=lambda: 0,
                        adapters={'desktop.notifications@1': adapter})
        engine.activate({'pulse': 1, 'id': 'discord-pings', 'title': 'Discord pings',
                         'source': {'kind': 'desktop.notifications', 'params': {'apps': ['discord']}},
                         'alert': {'metric': 'waiting', 'above': 1, 'notify': 'toast'}})
        row = next(p for p in engine.status(poll=True)['pulses'] if p['id'] == 'discord-pings')
        assert row['capsule']['label'] == '2 in Action Center'
        assert row['error'] is None and row['budget']['hosts'] == []
        assert row['ring']['score'] == pytest.approx(28.0)   # level 70 x 2/5; delta warming
        assert row['alert']['active'] is True
        assert row['lines'][0]['unknown'] is True            # new_1h: not observed for an hour yet
        assert row['icon_resolved']['slug'] == 'discord'


# ---------------------------------------------------------------- Desktop approval gate

def _node():
    import shutil
    return shutil.which('node')


@pytest.mark.skipif(_node() is None, reason='Node.js is required to evaluate the Desktop approval gate')
@pytest.mark.parametrize('params', [{'apps': ['discord']}, {'apps': ['discord', 'teams'], 'app_ids': ['Chrome']},
                                    {'app_ids': ['{6D809377-6AF0-444B-8957-A3773F02200E}/Voicemod Desktop/VoicemodDesktop.exe']}])
def test_desktop_approval_gate_accepts_real_draft_and_rejects_tampering(tmp_path, params):
    import subprocess
    engine = Engine(tmp_path)
    draft_id = engine.propose({'pulse': 1, 'title': 'Pings', 'icon': 'source',
                               'source': {'kind': 'desktop.notifications', 'params': params}},
                              origin={'kind': 'session'})
    draft = next(d for d in engine.status(poll=False)['drafts'] if d['id'] == draft_id)
    tampered = json.loads(json.dumps(draft))
    tampered['disclosure']['feeds'][0]['target'] = 'this PC · something else'
    source = (Path(__file__).resolve().parents[1] / 'desktop/plugin.js').read_text(encoding='utf-8')
    start = source.index('const jsonIdentity = value =>')
    end = source.index('\nfunction FeedDisclosures(')
    script = source[start:end] + '\nconst drafts = JSON.parse(require("fs").readFileSync(0, "utf8"));\n' \
        'process.stdout.write(JSON.stringify(drafts.map(approvalProblem)));\n'
    runner = tmp_path / 'gate.cjs'
    runner.write_text(script, encoding='utf-8')
    out = subprocess.run([_node(), str(runner)], input=json.dumps([draft, tampered]), capture_output=True,
                         text=True, encoding='utf-8', timeout=60, check=True)
    ok, bad = json.loads(out.stdout)
    assert ok == '', ok
    assert 'target unknown' in bad
