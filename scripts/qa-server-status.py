"""Synthetic Discord server rows for the server card's renderer QA; no real store, no network.

Five invented servers are watched by the real engine and Discord source, every 30 minutes with
a voice check every 15, through a scripted public API. The first for 50 hours, the rest for 26:
- lantern: widget on, so voice counts are exact;
- harbor: the public member list is full, so voice is a minimum;
- bigquiet: the list is full and nobody in it is in voice, which is unknown, not zero;
- quietco: widget off, so there is no voice figure;
- designed: the owner's own display blocks, which replace the card.
Every number in the rows was produced by the shipped code. Counts only; the scripted widget
members have no names.
"""
import json
import math
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulse_rings.engine import Engine
from pulse_rings.sources.base import SourceError
from pulse_rings.sources.discord import preset

NOW = 1794189600
H, D = 3600, 86400
clock = {'t': NOW - 50 * H}
CHANNELS = ['111111111111111111', '222222222222222222', '333333333333333333']
# code -> (guild id, name, members at the end, net member change over the last day, online swing, widget)
SERVERS = {
    'lantern': ('100000000000000001', 'Lantern community', 48210, 164, (2900, 700), 'open'),
    'harbor': ('100000000000000002', 'Harbor & Pine', 151300, 420, (15200, 2400), 'full'),
    'quietco': ('100000000000000003', 'Quiet Co.', 8120, -37, (410, 90), 'off'),
    'bigquiet': ('100000000000000005', 'Big & busy', 247190, 209, (15800, 2600), 'full-none'),
    'designed': ('100000000000000004', 'My own layout', 2140, 12, (120, 40), 'open'),
}


def wave(ts, low_hour=9):
    """0..1 over a day: lowest at low_hour UTC, highest twelve hours later."""
    return 0.5 - 0.5 * math.cos((ts / H - low_hour) / 24 * 2 * math.pi)


def invite(code, ts):
    gid, name, members, change, (base, swing), _ = SERVERS[code]
    progress = min(1, max(0, (ts - (NOW - D)) / D))
    eased = progress * progress * (3 - 2 * progress)           # growth is not a straight line
    return {'type': 0, 'code': code, 'guild': {'id': gid, 'name': name, 'icon': None, 'description': '', 'features': []},
            'approximate_member_count': round(members - change * (1 - eased)),
            # Yesterday was a little quieter, so today's line and yesterday's are both visible.
            'approximate_presence_count': round((base + swing * wave(ts)) * (0.94 if ts < NOW - D else 1))}


def widget(code, ts):
    gid, _, _, _, _, mode = SERVERS[code]
    if mode == 'off':
        raise SourceError('Widget Disabled', 403)
    evening = wave(ts, low_hour=11)
    # 'full-none': the public list is full and nobody in it is in voice, which is not a count of zero.
    in_voice = round(1 + 13 * evening ** 2) if mode == 'open' else 0 if mode == 'full-none' else round(2 + 5 * evening)
    listed = 100 if mode.startswith('full') else in_voice + 23
    members = [{'channel_id': CHANNELS[i % (1 + in_voice // 5)]} for i in range(in_voice)] + [{} for _ in range(listed - in_voice)]
    return {'id': gid, 'channels': [{'id': c, 'name': 'Voice'} for c in CHANNELS], 'members': members, 'presence_count': listed}


def fetch(path):
    if '/invites/' in path:
        return invite(path.split('/invites/')[1].split('?')[0], clock['t'])
    gid = path.split('/guilds/')[1].split('/')[0]
    return widget(next(code for code, row in SERVERS.items() if row[0] == gid), clock['t'])


with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as root:
    engine = Engine(root, fetch=fetch, clock=lambda: clock['t'], jitter=lambda: 0, icon_fetch=lambda *a, **k: None)
    def watch(code):
        definition = {**preset(code, pulse_id='server-' + code, title=SERVERS[code][1]), 'every': '30m'}   # keeps the fixture quick
        if code == 'designed':                        # the owner's own display blocks win over the server card
            definition = {'pulse': 1, 'id': definition['id'], 'title': SERVERS[code][1],
                          'feeds': {'main': {**definition['source'], 'every': '30m'}},
                          'display': [{'type': 'stat', 'value': 'main.online', 'label': 'Online now'}]}
        engine.activate(definition)

    watch('lantern')                                  # two full days, so yesterday's line is complete
    later = [code for code in SERVERS if code != 'lantern']
    while clock['t'] <= NOW:
        if later and clock['t'] >= NOW - 26 * H:
            for code in later:
                watch(code)
            later = []
        while engine.poll_one_due(previews=False):
            clock['t'] += 3          # the engine spaces requests to one host two seconds apart
        clock['t'] = (clock['t'] // 300 + 1) * 300
    clock['t'] = NOW
    status = engine.status(poll=False)
    assert len(status['pulses']) == 5 and all(p['error'] is None and bool(p.get('server')) == (p['id'] != 'server-designed') for p in status['pulses']), [
        (p['id'], p['state'], p.get('error'), bool(p.get('server'))) for p in status['pulses']]
    print(json.dumps(status['pulses'], ensure_ascii=True))
