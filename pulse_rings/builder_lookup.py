"""Human-click, fixed-host builder lookups. No query/result persistence or retries."""
import math
from pathlib import Path
import threading
import time
import unicodedata
from urllib.parse import urlencode

from .templates import steam_appid

_HOSTS = {'city': 'geocoding-api.open-meteo.com', 'steam': 'store.steampowered.com'}
_RECENT = {}  # Only (profile, kind) -> monotonic timestamp, never queries/results.
_LOCK = threading.Lock()


class LookupError(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def _fetch(url, host, target, **kwargs):
    # Same capped, IP-pinned, public-address-only, no-redirect transport as JSON
    # polling. Do NOT add lookup hosts to recurring Net.FIXED_HOSTS or use proxies.
    from .sources.http_json import _fetch as safe_fetch
    return safe_fetch(url, host, target, **kwargs)


def _text(value):
    return ''.join(c for c in value if not unicodedata.category(c).startswith('C'))[:160] if isinstance(value, str) else ''


def _coordinate(value, bound):
    if type(value) not in (int, float) or not math.isfinite(value) or not -bound <= value <= bound:
        return None
    return round(value, 2)


def lookup(root, kind, q, confirm, *, fetch=None, clock=time.monotonic):
    if confirm is not True:
        raise LookupError(400, 'Explicit confirmation required for one builder lookup.')
    if kind not in _HOSTS or not isinstance(q, str) or not 1 <= len(q.strip()) <= 100 or any(unicodedata.category(c).startswith('C') for c in q):
        raise LookupError(400, 'Choose city or steam and enter 1–100 plain-text characters.')
    q = q.strip()
    if kind == 'steam':
        try:
            appid = steam_appid(q)
        except ValueError:
            pass
        else:
            return {'results': [{'name': f'Steam app {appid}', 'appid': appid}], 'calls': 0, 'persisted': False}
    key = (str(Path(root).resolve()), kind)
    now = clock()
    with _LOCK:
        for old in [k for k, ts in _RECENT.items() if now - ts >= 3]:
            del _RECENT[old]
        if key in _RECENT or len(_RECENT) >= 4096:
            raise LookupError(429, 'One lookup per 3 seconds per kind; wait before trying again.')
        _RECENT[key] = now
    host = _HOSTS[kind]
    target = ('/v1/search?' + urlencode({'name': q, 'count': 8, 'language': 'en', 'format': 'json'}) if kind == 'city'
              else '/api/storesearch/?' + urlencode({'term': q, 'cc': 'us', 'l': 'english'}))
    try:
        body = (fetch or _fetch)('https://' + host + target, host, target, now=None, timeout=3, limit=256 * 1024)
        if not isinstance(body, dict):
            raise ValueError('Invalid response')
        rows = body.get('results' if kind == 'city' else 'items', [])
        if not isinstance(rows, list):
            raise ValueError('Invalid response')
        results = []
        for row in rows:
            if not isinstance(row, dict) or not _text(row.get('name')):
                continue
            if kind == 'city':
                lat, lon = _coordinate(row.get('latitude'), 90), _coordinate(row.get('longitude'), 180)
                if lat is None or lon is None:
                    continue
                results.append({'name': _text(row['name']), 'admin1': _text(row.get('admin1')),
                                'country': _text(row.get('country')), 'latitude': lat, 'longitude': lon})
            else:
                # Store packages/bundles use a different ID namespace from apps.
                # Older app-shaped responses may omit type; explicit others cannot bind.
                appid = row.get('id')
                if row.get('type', 'app') != 'app' or type(appid) is not int or not 0 < appid <= 4294967295:
                    continue
                results.append({'name': _text(row['name']), 'appid': appid})
            if len(results) == 8:
                break
        return {'results': results, 'calls': 1, 'persisted': False}
    except Exception:
        # No exception string, upstream body, URL, query, or redirect target escapes.
        raise LookupError(503, 'Builder lookup is unavailable. Try again later.') from None
