"""Synthetic counts-only engine rows for notification renderer QA; no real DB."""
import json
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulse_rings.engine import Engine
from pulse_rings.sources.desktop_notifications import DesktopNotifications, Snapshot

NOW = 1794189600
DISCORD = 'com.squirrel.Discord.Discord'.lower()
TEAMS = 'MSTeams_8wekyb3d8bbwe!MSTeams'.lower()


class SyntheticReader:
    def read(self, aumids, types, now):
        if 'qa.missing' in aumids:
            raise FileNotFoundError('synthetic unavailable store')
        registered = {DISCORD, TEAMS, 'chrome', 'com.squirrel.discordptb.discordptb'}
        rows = [(DISCORD, i, 'toast', NOW - 187 * 60, None) for i in (1, 2)]
        rows += [('chrome', i + 10, 'toast', NOW - 60, None) for i in range(12345)]
        return Snapshot(registered=registered, disabled={TEAMS}, rows=rows,
                        last_added={DISCORD: NOW - 187 * 60}, current_id=13000)


source = {'kind': 'desktop.notifications', 'params': {'apps': ['discord']}}
blocks = {
    'stat': [{'type': 'stat', 'value': 'waiting', 'label': 'In Action Center'},
             {'type': 'stat', 'value': 'minutes_since_last', 'label': 'Last notification', 'unit': 'min'}],
    'rings': [{'type': 'rings', 'rings': [{'value': 'waiting', 'label': 'In Action Center', 'max': 5}]}],
    'bar': [{'type': 'bar', 'value': 'waiting', 'label': 'In Action Center', 'max': 'usual'}],
    'bars': [{'type': 'bars', 'scale': 'independent', 'bars': [
        {'value': 'waiting', 'label': 'In Action Center', 'max': 5},
        {'value': 'new_1h', 'label': 'Observed · last hour', 'max': 'auto'}]}],
    'score': [{'type': 'score', 'label': 'Notification unusualness', 'components': [
        {'metric': 'waiting', 'type': 'level', 'full_at': 5, 'weight': 70},
        {'metric': 'new_1h', 'type': 'delta', 'baseline': 'median', 'weight': 30}]}],
    'spark': [{'type': 'spark', 'value': 'waiting', 'label': 'Action Center trend'}],
}
with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as root:
    engine = Engine(root, clock=lambda: NOW, jitter=lambda: 0,
                    adapters={'desktop.notifications@1': DesktopNotifications(reader=SyntheticReader())})
    for kind, display in blocks.items():
        engine.activate({'pulse': 1, 'id': 'notify-' + kind, 'title': 'Discord · ' + kind + ' · 通知 🔔',
                         'icon': {'brand': 'discord'}, 'source': source, 'display': display})
    for id, params in [('zero', {'app_ids': ['com.squirrel.DiscordPTB.DiscordPTB']}),
                       ('partial', {'apps': ['discord', 'teams']}),
                       ('missing', {'app_ids': ['qa.missing']}), ('large', {'apps': ['chrome']})]:
        engine.activate({'pulse': 1, 'id': 'notify-' + id, 'title': 'Notifications · ' + id,
                         'source': {'kind': 'desktop.notifications', 'params': params},
                         'display': [{'type': 'stat', 'value': 'waiting', 'label': 'In Action Center'}]})
    engine.activate({'pulse': 1, 'id': 'notify-legacy', 'title': 'Discord · local notification counts', 'source': source})
    for _ in range(11):
        engine.poll_one_due(previews=False)
    status = engine.status(poll=False)
    assert len(status['pulses']) == 11 and all(p['last_ok_ts'] == NOW for p in status['pulses'])
    unsupported = Engine(Path(root) / 'unsupported', clock=lambda: NOW, jitter=lambda: 0,
                         adapters={'desktop.notifications@1': DesktopNotifications(platform='linux')})
    unsupported.activate({'pulse': 1, 'id': 'notify-unsupported', 'title': 'Notifications · unsupported',
                          'source': source})
    print(json.dumps(status['pulses'] + unsupported.status(poll=True)['pulses'], ensure_ascii=True))
