"""Synthetic engine rows for the opt-in message preview; no real store, no network.

A scripted reader stands in for the Windows store: counts come from the real engine and
adapter, and `preview()` returns invented senders and texts, so the renderer is tested on
exactly what the backend sends. Prints {"pane": [...], "agent": [...]}: the pane's status and
the compact status the agent reads, which must carry no preview text.
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
DISCORD = 'com.squirrel.discord.discord'
WAITING = [NOW - 600, NOW - 300, NOW - 60]
LONG = 'This message is deliberately long so that the collapsed row has to cut it with an ellipsis ' * 3
PREVIEW = [
    {'from': 'Ada (#general, Test Server)', 'text': 'Are we still on for the demo at four?', 'ts': NOW - 60},
    {'from': 'Grace', 'text': LONG, 'ts': NOW - 300},
    {'from': None, 'text': 'A toast with only one line', 'ts': NOW - 600},
]
clock = {'t': NOW - 1800}


class ScriptedReader:
    def read(self, aumids, types, now):
        rows = [(DISCORD, i + 1, 'toast', t, None) for i, t in enumerate(WAITING) if t <= now]
        return Snapshot(registered={DISCORD}, rows=rows, last_added={DISCORD: max(WAITING)}, current_id=len(rows))

    def preview(self, aumids, now):
        return [dict(item) for item in PREVIEW]


def source(**params):
    return {'kind': 'desktop.notifications', 'params': params}


with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as root:
    engine = Engine(root, clock=lambda: clock['t'], jitter=lambda: 0,
                    adapters={'desktop.notifications@1': DesktopNotifications(reader=ScriptedReader())})
    engine.activate({'pulse': 1, 'id': 'preview-on', 'title': 'Discord pings', 'icon': {'brand': 'discord'},
                     'source': source(apps=['discord'], preview=True), 'every': '30m'})
    engine.activate({'pulse': 1, 'id': 'preview-designed', 'title': 'Discord · my layout', 'icon': {'brand': 'discord'},
                     'feeds': {'main': {**source(apps=['discord'], preview=True), 'every': '30m'}},
                     'display': [{'type': 'stat', 'value': 'main.waiting', 'label': 'In Action Center'}]})
    engine.activate({'pulse': 1, 'id': 'preview-off', 'title': 'Discord · counts only', 'icon': {'brand': 'discord'},
                     'source': source(apps=['discord']), 'every': '30m'})
    while clock['t'] <= NOW:
        while engine.poll_one_due(previews=False):
            pass
        clock['t'] += 1800
    clock['t'] = NOW
    pane = engine.status(poll=False)['pulses']
    agent = engine.status(poll=False, include_icons=False, compact=True)['pulses']
    print(json.dumps({'pane': pane, 'agent': agent}, ensure_ascii=True))
