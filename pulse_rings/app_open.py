"""Open a watched desktop app on a human click. Windows only; code-owned targets only.

A notifications pulse that watches one curated app can bring that app forward when
its row is clicked. The target is never text from a definition: it is an exact
AppUserModelID from the code-owned table in ``desktop_apps``, handed to the Windows
shell as ``shell:AppsFolder\\<AUMID>`` (the same activation the Start menu uses).
No arguments, no command line, no network, nothing read back.

Only an adapter that reads the real Windows store offers this (``can_open``), so a
test reader, another platform or an older adapter never does.
"""
import json
import os
import threading
import time

from . import desktop_apps
from .feed_runtime import adapter_definition, hero_ref

KIND = 'desktop.notifications'
MIN_GAP = 2.0  # seconds between two opens of the same app; a double click is one open
_CURATED = frozenset(a for _, _, aumids in desktop_apps.APPS.values() for a in aumids)
_recent = {}
_lock = threading.Lock()


class OpenError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def hero_feed(definition):
    """(params, feed name or None) of the notifications feed a pulse is drawn from, else None."""
    if not isinstance(definition, dict):
        return None
    if 'feeds' in definition:
        name = hero_ref(definition).split('.')[0]
        spec = definition['feeds'].get(name) or {}
        kind, params = spec.get('kind'), spec.get('params')
    else:
        name, source = None, definition.get('source') or {}
        kind, params = source.get('kind'), source.get('params')
    return (params or {}, name) if str(kind or '').removesuffix('@1') == KIND else None


def target(engine, definition, source_state):
    """(display name, AUMID) this pulse may open on this PC, or None."""
    hero = hero_feed(definition)
    if hero is None:
        return None
    params, name = hero
    adapter = engine.adapter(adapter_definition(definition, name) if name else definition)
    if getattr(adapter, 'can_open', False) is not True:
        return None
    seen = source_state.get('apps') if isinstance(source_state, dict) else None
    return desktop_apps.launch_target(params, seen if isinstance(seen, list) else ())


def describe(engine, definition, source_state):
    """Status enrichment: ``{'name': 'Discord'}`` when a click can open the app, else None."""
    found = target(engine, definition, source_state)
    return {'name': found[0]} if found else None


def launch(aumid, *, starter=None, clock=time.monotonic):
    """Activate one curated app; False when the same app was opened a moment ago."""
    if aumid not in _CURATED:
        raise OpenError(403, 'Only curated apps can be opened.')
    with _lock:
        now = clock()
        if now - _recent.get(aumid, now - MIN_GAP) < MIN_GAP:
            return False
        _recent[aumid] = now
    try:
        (starter or os.startfile)('shell:AppsFolder\\' + aumid)
    except Exception:
        with _lock:
            _recent.pop(aumid, None)
        raise OpenError(502, 'Windows could not open this app.') from None
    return True


def open_for_pulse(engine, pulse_id, *, starter=None):
    """Open the app an approved notifications pulse watches. Returns ``{'opened': name}``."""
    with engine.store.read() as db:
        row = db.execute('SELECT definition, source_state FROM pulses WHERE id=?', (pulse_id,)).fetchone()
        if row is None:
            raise OpenError(404, 'Pulse not found')
        try:
            definition = json.loads(row['definition'])
            hero = hero_feed(definition)
            state = json.loads(row['source_state'] or '{}')
            if hero is not None and hero[1] is not None:
                state = json.loads(engine.store.feed_rows(pulse_id, db=db).get(hero[1], {}).get('source_state') or '{}')
        except (ValueError, TypeError, KeyError, IndexError):
            raise OpenError(409, 'Invalid stored pulse') from None
    found = target(engine, definition, state)
    if found is None:
        raise OpenError(409, 'This pulse has no app to open on this PC.')
    launch(found[1], starter=starter)
    return {'opened': found[0]}
