"""Opt-in notification preview: who each waiting notification is from, and its text.

Only for a ``desktop.notifications`` pulse whose approved params say ``preview: true``
(the approval card discloses it and its target changes, so turning it on means approving
again). The text is read from the local Windows notification store when the pane asks
for status, kept in memory for a few seconds and handed to the pane only. It never enters
samples, source state, metadata, the store's files, logs, errors, the agent's status tool
or the ``/rings`` command output. Without ``preview`` nothing here runs.

Toast payloads are untrusted XML: a size cap, no document type declarations, and only the
first two plain ``<text>`` elements of the toast's binding are kept, cleaned and cut short.
"""
from contextlib import closing
import re
import sqlite3
import threading
import time
import xml.etree.ElementTree as ET

MAX_ITEMS = 5          # waiting notifications listed
TEXT_LIMIT = 120       # characters kept from the sender line and from the body
PAYLOAD_LIMIT = 16384  # bytes of toast XML parsed; anything larger is skipped
SCAN_LIMIT = 50        # newest rows looked at to find the waiting ones
CACHE_SECONDS = 4

_CONTROL = re.compile(r'[\x00-\x1f\x7f-\x9f]')
# Zero-width and bidirectional controls can reorder or hide text.
_INVISIBLE = re.compile('[\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]')  # escapes, never literal invisible characters
_SPACES = re.compile(r'\s+')
_DECLARATION = re.compile(rb'<!\s*(DOCTYPE|ENTITY)', re.IGNORECASE)

_cache = {}
_lock = threading.Lock()


def enabled(params):
    return isinstance(params, dict) and params.get('preview') is True


def clean(value, limit=TEXT_LIMIT):
    """Plain, single-line, bounded text, or None when nothing readable is left."""
    if not isinstance(value, str):
        return None
    text = _SPACES.sub(' ', _INVISIBLE.sub('', _CONTROL.sub(' ', value))).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def parse_toast(payload):
    """(sender, text) from one toast payload, or None. Never raises."""
    if isinstance(payload, str):
        payload = payload.encode('utf-8', 'replace')
    if not isinstance(payload, bytes) or not payload or len(payload) > PAYLOAD_LIMIT:
        return None
    if _DECLARATION.search(payload):
        return None
    try:
        root = ET.fromstring(payload)
    except (ET.ParseError, ValueError):
        return None
    if root.tag != 'toast':
        return None
    binding = root.find('./visual/binding')
    if binding is None:
        return None
    texts = []
    for node in binding.findall('text'):
        if node.get('placement') or node.get('hint-style') == 'captionSubtle':
            continue  # Attribution lines ("via Discord") are not the message.
        text = clean(''.join(node.itertext()))
        if text:
            texts.append(text)
        if len(texts) == 2:
            break
    if not texts:
        return None
    return (texts[0], texts[1]) if len(texts) == 2 else (None, texts[0])


def read_store(path, aumids, now, filetime):
    """Newest waiting toasts for exactly these app ids: [{from, text, ts}], newest first."""
    if not aumids:
        return []
    uri = path.resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=0.25)) as db:
        db.execute('PRAGMA query_only=ON')
        if db.execute('PRAGMA user_version').fetchone()[0] != 8:
            return []
        columns = {row[1] for row in db.execute('PRAGMA table_info([Notification])')}
        if not {'HandlerId', 'Type', 'Payload', 'ArrivalTime', 'ExpiryTime', 'PayloadType'} <= columns:
            return []
        marks = ','.join('?' * len(aumids))
        rows = db.execute(
            'SELECT n.Payload, n.ArrivalTime, n.ExpiryTime FROM Notification n '
            'JOIN NotificationHandler h ON h.RecordId = n.HandlerId '
            f"WHERE h.PrimaryId IN ({marks}) AND n.Type = 'toast' AND n.PayloadType = 'Xml' "
            'ORDER BY n.ArrivalTime DESC, n.Id DESC LIMIT ?', list(aumids) + [SCAN_LIMIT]).fetchall()
    items = []
    for payload, arrival, expiry in rows:
        expires = filetime(expiry, now, 20 * 365 * 86400)
        if expires is not None and expires <= now:
            continue
        parsed = parse_toast(payload)
        if parsed is None:
            continue
        items.append({'from': parsed[0], 'text': parsed[1], 'ts': filetime(arrival, now)})
        if len(items) == MAX_ITEMS:
            break
    return items


def bounded(items):
    """Re-check whatever a reader returned: at most MAX_ITEMS plain, bounded items."""
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        text, sender = clean(item.get('text')), clean(item.get('from'))
        ts = item.get('ts')
        if not text and not sender:
            continue
        out.append({'from': sender, 'text': text or '',
                    'ts': ts if isinstance(ts, (int, float)) and not isinstance(ts, bool) else None})
        if len(out) == MAX_ITEMS:
            break
    return out


def items_for(adapter, params, inbox, now):
    """Preview items for a status row, or None when preview is off or does not apply.

    Called only for the pane's own status. Failures show no preview and are not logged:
    a message must never reach a log line or an error string.
    """
    if not enabled(params) or not isinstance(inbox, dict) or not isinstance(inbox.get('waiting'), int):
        return None
    if inbox['waiting'] <= 0:
        return []
    reader = getattr(adapter, 'preview', None)
    if not callable(reader):
        return None
    from . import desktop_apps
    aumids = desktop_apps.app_ids(params)
    key = (type(adapter).__name__, id(getattr(adapter, 'reader', None)), tuple(a.lower() for a in aumids))
    tick = time.monotonic()
    with _lock:
        for stale in [k for k, (until, _) in _cache.items() if until <= tick]:
            del _cache[stale]
        hit = _cache.get(key)
    if hit is not None:
        return [dict(item) for item in hit[1]]
    try:
        found = bounded(reader(aumids, now))
    except Exception:
        return []
    until = tick + CACHE_SECONDS
    with _lock:
        _cache[key] = (until, found)
    # Expire on its own, even if the pane is closed or previews are turned off and no
    # later call ever looks at the cache: the text is never kept past CACHE_SECONDS.
    timer = threading.Timer(CACHE_SECONDS, _expire, args=(key, until))
    timer.daemon = True
    timer.start()
    return [dict(item) for item in found]


def _expire(key, until):
    with _lock:
        entry = _cache.get(key)
        if entry is not None and entry[0] <= until:
            del _cache[key]


def forget():
    """Drop every cached preview (tests, and when a pulse is removed)."""
    with _lock:
        _cache.clear()
