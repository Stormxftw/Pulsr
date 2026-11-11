"""Synthetic counts-only engine rows for notification-mode renderer QA; no real store, no network.

A scripted reader plays a day of arrivals and clearings; the real engine and adapter
watch it for 26 hours at their normal cadence, so every number comes from the real code.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulse_rings.engine import Engine
from pulse_rings.sources.desktop_notifications import DesktopNotifications, Snapshot

NOW = 1794189600
H = 3600
DISCORD, SLACK, SIGNAL = 'com.squirrel.discord.discord', 'com.squirrel.slack.slack', 'org.whispersystems.signal-desktop'
# (arrived, cleared) per app. Cleared None = still in Windows at NOW.
EVENTS = {
    DISCORD: [(NOW - 20 * H, NOW - 19 * H), (NOW - 5 * H, NOW - 4 * H), (NOW - 187 * 60, None), (NOW - 187 * 60 + 20, None)],
    # Ages sit well inside a minute, never on its edge: the pane's clock is a float and may
    # read a hair before the sample time.
    SLACK: [(NOW - 27 * H - 300, NOW - 26.5 * H)],
    SIGNAL: [(NOW - 40 * 60 - 30, None)],
}
ORDER = sorted((arrived, app) for app, events in EVENTS.items() for arrived, _ in events)
clock = {'t': NOW - 26 * H}


class ScriptedReader:
    def read(self, aumids, types, now):
        if 'qa.missing' in aumids:
            raise FileNotFoundError('synthetic unavailable store')
        wanted = {a.lower() for a in aumids}
        rows, last = [], {}
        for app, events in EVENTS.items():
            if app not in wanted:
                continue
            for arrived, cleared in events:
                if arrived > now:
                    continue
                last[app] = max(last.get(app, 0), arrived)
                if cleared is None or cleared > now:
                    rows.append((app, ORDER.index((arrived, app)) + 1, 'toast', arrived, None))
        return Snapshot(registered=set(EVENTS), rows=rows, last_added=last,
                        current_id=sum(1 for arrived, _ in ORDER if arrived <= now))


def source(**params):
    return {'kind': 'desktop.notifications', 'params': params}


with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as root:
    engine = Engine(root, clock=lambda: clock['t'], jitter=lambda: 0,
                    adapters={'desktop.notifications@1': DesktopNotifications(reader=ScriptedReader())})
    engine.activate({'pulse': 1, 'id': 'inbox-waiting', 'title': 'Discord · notifications', 'icon': {'brand': 'discord'},
                     'source': source(apps=['discord']), 'every': '30m'})
    engine.activate({'pulse': 1, 'id': 'inbox-quiet', 'title': 'Slack · notifications',
                     'source': source(apps=['slack']), 'every': '30m'})
    engine.activate({'pulse': 1, 'id': 'inbox-designed', 'title': 'Discord · my layout', 'icon': {'brand': 'discord'},
                     'feeds': {'main': {**source(apps=['discord']), 'every': '30m'}},
                     'display': [{'type': 'stat', 'value': 'main.waiting', 'label': 'In Action Center'},
                                 {'type': 'spark', 'value': 'main.waiting', 'label': 'Action Center trend'}]})
    while clock['t'] <= NOW:
        while engine.poll_one_due(previews=False):
            pass
        clock['t'] += 1800
    clock['t'] = NOW
    engine.activate({'pulse': 1, 'id': 'inbox-fresh', 'title': 'Signal · notifications',
                     'source': source(apps=['signal']), 'every': '30m'})
    engine.activate({'pulse': 1, 'id': 'inbox-missing', 'title': 'Unavailable · notifications',
                     'source': source(app_ids=['qa.missing']), 'every': '30m'})
    while engine.poll_one_due(previews=False):
        pass
    status = engine.status(poll=False)
    assert len(status['pulses']) == 5 and all(p['last_ok_ts'] == NOW for p in status['pulses']), [
        (p['id'], p['last_ok_ts'], p['state']) for p in status['pulses']]
    print(json.dumps(status['pulses'], ensure_ascii=True))
