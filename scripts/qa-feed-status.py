"""Synthetic new-posts engine rows for renderer QA; no real store, no network.

Scripted RSS and Atom documents are served to the real adapter through the real engine, so every
number, title and link in the rows was produced by the shipped parser. The posts are invented.
"""
from datetime import datetime, timezone
from email.utils import format_datetime
import json
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulse_rings.engine import Engine
from pulse_rings.sources import http_json

NOW = 1794189600
H, D = 3600, 86400


def rfc(ago):
    # Ages sit well inside a minute, never on its edge: the pane's clock is a float and may
    # read a hair before the sample time.
    return format_datetime(datetime.fromtimestamp(NOW - ago - 30, timezone.utc))


def rss(title, posts):
    items = ''.join(
        f'<item><title>{name}</title>' + (f'<link>{link}</link>' if link else '')
        + (f'<pubDate>{rfc(ago)}</pubDate>' if ago is not None else '') + '</item>'
        for name, ago, link in posts)
    return f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{title}</title>{items}</channel></rss>'.encode()


RELEASES = rss('Lantern releases', [
    ('Lantern 2.4: offline mode, faster sync and a rebuilt settings screen for every platform', 2 * H + 600, 'https://lantern.example/releases/2-4'),
    ('Lantern 2.3.2 fixes a crash on startup', 19 * H, 'https://lantern.example/releases/2-3-2'),
    ('Lantern 2.3.1', 3 * D, 'https://lantern.example/releases/2-3-1'),
    ('Lantern 2.3: shared folders', 5 * D, 'http://lantern.example/releases/2-3'),
    ('Lantern 2.2.4', 9 * D, 'https://lantern.example/releases/2-2-4'),
    ('Lantern 2.2.3', 16 * D, 'https://lantern.example/releases/2-2-3'),
    ('Lantern 2.2.2', 24 * D, 'https://lantern.example/releases/2-2-2'),
] + [(f'Lantern 2.{minor}', (40 + 20 * (9 - minor)) * D, f'https://lantern.example/releases/2-{minor}') for minor in (1, 0)]
  + [(f'Lantern 1.{minor}', (100 + 30 * (9 - minor)) * D, f'https://lantern.example/releases/1-{minor}') for minor in range(9, 6, -1)])
BLOG = rss('Harbor &amp; Pine journal', [
    ('What we learned moving the workshop', 3 * D + 2 * H, 'https://harborpine.example/journal/moving'),
    ('Autumn open day: photos', 12 * D, 'https://harborpine.example/journal/open-day'),
    ('A short guide to oiling a workbench', 31 * D, 'https://harborpine.example/journal/workbench'),
])
UNDATED = rss('Changelog', [('Faster search', None, 'https://notes.example/changelog#search'),
                            ('New export formats', None, 'https://notes.example/changelog#export')])
EMPTY = rss('Brand new blog', [])
BODIES = {'/releases.xml': RELEASES, '/journal.xml': BLOG, '/changelog.xml': UNDATED, '/new.xml': EMPTY}


def fetch(url, host, target, **kw):
    return BODIES[target], {'content-type': 'application/rss+xml'}


def source(path):
    return {'kind': 'web.feed', 'params': {'url': 'https://feeds.example' + path}}


http_json._fetch = fetch
with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as root:
    engine = Engine(root, clock=lambda: NOW, jitter=lambda: 0)
    engine.net.call = lambda host, callback: callback()
    # No icon given: the bundled feed mark is used.
    engine.activate({'pulse': 1, 'id': 'posts-busy', 'title': 'Lantern · releases', 'source': source('/releases.xml')})
    engine.activate({'pulse': 1, 'id': 'posts-quiet', 'title': 'Harbor & Pine · journal', 'icon': {'emoji': '📰'}, 'source': source('/journal.xml')})
    engine.activate({'pulse': 1, 'id': 'posts-designed', 'title': 'Lantern · my layout', 'icon': {'emoji': '📰'},
                     'feeds': {'main': {**source('/releases.xml'), 'every': '30m'}},
                     'display': [{'type': 'stat', 'value': 'main.new_24h', 'label': 'New · 24 hours'},
                                 {'type': 'stat', 'value': 'main.new_7d', 'label': 'New · 7 days'}]})
    engine.activate({'pulse': 1, 'id': 'posts-undated', 'title': 'Notes · changelog', 'icon': {'emoji': '📰'}, 'source': source('/changelog.xml')})
    engine.activate({'pulse': 1, 'id': 'posts-empty', 'title': 'Brand new blog', 'icon': {'emoji': '📰'}, 'source': source('/new.xml')})
    while engine.poll_one_due(previews=False):
        pass
    status = engine.status(poll=False)
    assert len(status['pulses']) == 5 and all(p['last_ok_ts'] == NOW and p.get('posts') for p in status['pulses']), [
        (p['id'], p['last_ok_ts'], p['state'], p.get('error')) for p in status['pulses']]
    print(json.dumps(status['pulses'], ensure_ascii=True))
