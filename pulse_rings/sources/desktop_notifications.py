"""Local desktop-notification counts (Windows). Counts and times only.

Reads the per-user Windows notification store (wpndatabase.db) read-only and
per-app registry timestamps. Polling never selects payloads, tags, groups or
NotificationData, never writes either store and never touches the network.
Message text, senders and app payloads never enter samples, state, metadata or
errors. Undocumented store formats fail closed to unknown, never zero.

The one exception is the opt-in, separately approved ``preview`` param: then
``preview()`` reads the newest waiting toasts' text for the pane only, through
``notification_preview``; it is never part of a poll.
"""
from contextlib import closing
import copy
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import sqlite3
import sys

from .base import Deferred, SourceError, SourceResult
from .. import desktop_apps
from ..spec import duration_seconds

METRICS = ('waiting', 'new_1h', 'new_24h', 'minutes_since_last')

DISCLOSURE = {
    'summary': 'Counts notifications still in Windows, not unread messages. Local only.',
    'details': ('This PC only · reads the local Windows notification store and per-app registry '
                'timestamps read-only; counts and times only, never message text. No network. '
                'Waiting means selected entries still in Windows (toasts in Action Center), not '
                'unread messages. New counts need a continuously watched full window; several '
                'arrivals that clear between polls may count only once.'),
}
PREVIEW_DISCLOSURE = {
    'summary': ('Shows who waiting notifications are from and their text, here only. '
                'Never sent to Hermes. Local only.'),
    'details': ('This PC only · reads the local Windows notification store and per-app registry '
                'timestamps read-only. Message previews are on: for the newest waiting '
                'notifications of these apps (at most 5) the sender line and text, cut to 120 '
                'characters, are read when this pane refreshes, kept in memory for a few '
                'seconds and shown only here; never saved, logged or sent to Hermes or the '
                'model. No network. Waiting means selected entries still in Windows (toasts in '
                'Action Center), not unread messages. New counts need a continuously watched '
                'full window; several arrivals that clear between polls may count only once.'),
    'preview': True,
}


def disclosure(params):
    """The row disclosure for these params: counts-only unless preview was approved."""
    from ..notification_preview import enabled
    return copy.deepcopy(PREVIEW_DISCLOSURE if enabled(params) else DISCLOSURE)
WINDOWS = {'new_1h': 3600, 'new_24h': 86400}
COVERAGE = ('Counts and times only; never message text. Arrivals are counted between polls: '
            'several that arrive and clear within one poll count once.')
SUPPORTED_VERSIONS = frozenset({8})
REQUIRED_COLUMNS = {
    'NotificationHandler': {'RecordId', 'PrimaryId'},
    'Notification': {'Id', 'HandlerId', 'Type', 'ArrivalTime', 'ExpiryTime'},
    'HandlerSettings': {'HandlerId', 'SettingKey', 'Value'},
    'Metadata': {'Key', 'Value'},
}
MAX_ARRIVALS = 2000
FILETIME_EPOCH = 11644473600  # seconds between 1601-01-01 and 1970-01-01
MIN_TS = 946684800  # 2000-01-01
SETTINGS_KEY = r'Software\Microsoft\Windows\CurrentVersion\Notifications\Settings'
PUSH_KEY = r'Software\Microsoft\Windows\CurrentVersion\PushNotifications'

R_PLATFORM = 'Desktop notifications are only available on Windows.'
R_MISSING = 'Windows notification store not found.'
R_FORMAT = 'Windows notification store format not recognized.'
R_GLOBAL_OFF = 'Windows notifications are turned off.'
R_UNREGISTERED = 'This app has not registered for notifications on this PC.'
R_APP_OFF = 'Notifications for this app are turned off in Windows.'
R_WARMING = 'Collecting the first complete observation window.'
R_GAP = 'Not watched continuously for the full window.'
R_OVERFLOW = 'More arrivals than this pulse can count in 24 hours.'
R_NEVER = 'No notification from these apps has been seen yet.'


class StoreFormatError(Exception):
    """Undocumented store layout changed; never guessed around."""


@dataclass
class Snapshot:
    """Counts-only view. Rows are (aumid, id, type, arrival_ts, expiry_ts)."""
    toasts_enabled: bool | None = True
    registered: set = field(default_factory=set)
    disabled: set = field(default_factory=set)
    rows: list = field(default_factory=list)
    last_added: dict = field(default_factory=dict)
    current_id: int | None = None


def filetime(value, now, future=0):
    """FILETIME (100 ns since 1601) to Unix seconds, or None when implausible."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    try:
        ts = value / 1e7 - FILETIME_EPOCH
    except OverflowError:
        return None
    return ts if math.isfinite(ts) and MIN_TS <= ts <= now + future else None


class WindowsRegistry:
    """KEY_READ only. Returns raw values; never writes or enumerates other apps."""

    def __init__(self):
        import winreg
        self.winreg = winreg

    def _value(self, path, name):
        try:
            with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER, path, 0, self.winreg.KEY_READ) as key:
                return self.winreg.QueryValueEx(key, name)[0]
        except OSError:
            return None

    def toasts_enabled(self):
        value = self._value(PUSH_KEY, 'ToastEnabled')
        return None if value is None else value != 0

    def app_enabled(self, aumid):
        value = self._value(SETTINGS_KEY + '\\' + aumid, 'Enabled')
        return None if value is None else value != 0

    def last_added(self, aumid):
        return self._value(SETTINGS_KEY + '\\' + aumid, 'LastNotificationAddedTime')


class WindowsNotificationStore:
    """Read-only reader for %LOCALAPPDATA%/Microsoft/Windows/Notifications/wpndatabase.db."""

    def __init__(self, path=None, registry=None):
        if path is None:
            base = os.environ.get('LOCALAPPDATA', '')
            path = Path(base) / 'Microsoft' / 'Windows' / 'Notifications' / 'wpndatabase.db'
        self.path = Path(path)
        self.registry = registry

    def read(self, aumids, types, now):
        if not self.path.is_file():
            raise FileNotFoundError('store')
        registry = self.registry if self.registry is not None else WindowsRegistry()
        uri = self.path.resolve().as_uri() + '?mode=ro'
        snap = Snapshot(toasts_enabled=registry.toasts_enabled())
        with closing(sqlite3.connect(uri, uri=True, timeout=0.25)) as db:
            db.execute('PRAGMA query_only=ON')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in SUPPORTED_VERSIONS:
                raise StoreFormatError('version')
            for table, needed in REQUIRED_COLUMNS.items():
                have = {row[1] for row in db.execute(f'PRAGMA table_info([{table}])')}
                if not needed <= have:
                    raise StoreFormatError('columns')
            marks = ','.join('?' * len(aumids))
            handlers = {}
            for record, primary in db.execute(
                    f'SELECT RecordId, PrimaryId FROM NotificationHandler WHERE PrimaryId IN ({marks})', aumids):
                if not isinstance(record, int) or not isinstance(primary, str):
                    raise StoreFormatError('handler')
                handlers[record] = primary.lower()
            snap.registered = set(handlers.values())
            if handlers:
                ids = ','.join('?' * len(handlers))
                for record, value in db.execute(
                        f"SELECT HandlerId, Value FROM HandlerSettings WHERE SettingKey='s:toast' AND HandlerId IN ({ids})",
                        list(handlers)):
                    if value == 0:
                        snap.disabled.add(handlers[record])
                kinds = ','.join('?' * len(types))
                for record, nid, kind, arrival, expiry in db.execute(
                        f'SELECT HandlerId, Id, Type, ArrivalTime, ExpiryTime FROM Notification '
                        f'WHERE HandlerId IN ({ids}) AND Type IN ({kinds})', list(handlers) + list(types)):
                    if not isinstance(nid, int) or isinstance(nid, bool):
                        raise StoreFormatError('id')
                    snap.rows.append((handlers[record], nid, kind, filetime(arrival, now), filetime(expiry, now, 20 * 365 * 86400)))
            current = db.execute("SELECT Value FROM Metadata WHERE Key='CurrentNotificationId'").fetchone()
            snap.current_id = current[0] if current and isinstance(current[0], int) else None
        for aumid in aumids:
            key = aumid.lower()
            if registry.app_enabled(aumid) is False:
                snap.disabled.add(key)
            stamp = filetime(registry.last_added(aumid), now)
            if stamp is not None:
                snap.last_added[key] = stamp
        return snap

    def preview(self, aumids, now):
        """Opt-in preview only: newest waiting toasts' sender and text, for the pane."""
        from ..notification_preview import read_store
        if not self.path.is_file():
            return []
        return read_store(self.path, aumids, now, filetime)


def _unknown(now, reason, metadata=None, state=None):
    return SourceResult(sample={'ts': now, 'metrics': {m: None for m in METRICS}, 'baselines': {},
                                'unknown_reasons': {m: reason for m in METRICS}},
                        state=state or {}, metadata=metadata or {'coverage': COVERAGE})


class DesktopNotifications:
    """Adapter for kind desktop.notifications. Local only; `net` is never used."""
    arbitrary_host = False

    def __init__(self, reader=None, platform=None):
        self.reader = reader
        self.platform = platform or sys.platform
        # Opening the watched app is offered only when reading the real Windows store.
        self.can_open = reader is None and self.platform.startswith('win')

    def preview(self, aumids, now):
        """Text preview for the pane; only the real Windows store or an injected reader."""
        if self.reader is not None:
            reader = getattr(self.reader, 'preview', None)
            return reader(aumids, now) if callable(reader) else []
        if not self.platform.startswith('win'):
            return []
        return WindowsNotificationStore().preview(aumids, now)

    def poll(self, definition, previous, state, *, now, net):
        params = definition['source']['params']
        aumids = desktop_apps.app_ids(params)
        types = list(params.get('types') or ['toast'])
        every = duration_seconds(definition.get('every', '1m'))
        if not self.platform.startswith('win') and self.reader is None:
            return _unknown(now, R_PLATFORM)
        reader = self.reader or WindowsNotificationStore()
        try:
            snap = reader.read(aumids, types, now)
        except sqlite3.OperationalError as exc:
            text = str(exc).lower()
            if 'locked' in text or 'busy' in text:
                raise Deferred('Windows notification store is busy; retrying shortly.', retry_after=every) from None
            return _unknown(now, R_MISSING if 'unable to open' in text else R_FORMAT, state=state)
        except (FileNotFoundError, PermissionError):
            return _unknown(now, R_MISSING, state=state)
        except (StoreFormatError, sqlite3.DatabaseError):
            return _unknown(now, R_FORMAT, state=state)
        except Exception:
            raise SourceError('Desktop notification counts are temporarily unavailable.') from None
        return self._sample(snap, aumids, desktop_apps.entries(params), state, now, every)

    def _sample(self, snap, aumids, groups, state, now, every):
        if snap.toasts_enabled is False:
            return _unknown(now, R_GLOBAL_OFF, state=state)
        selected = {a.lower() for a in aumids}
        registered = selected & (snap.registered | set(snap.last_added))
        if not registered:
            return _unknown(now, R_UNREGISTERED, state=state)
        reachable = registered - snap.disabled
        watched = sum(1 for group in groups if {a.lower() for a in group} & reachable)
        metadata = {'coverage': COVERAGE, 'apps_watched': watched, 'apps_unavailable': len(groups) - watched}
        if not reachable:
            return _unknown(now, R_APP_OFF, metadata, state)
        if watched < len(groups):
            return _unknown(now, f'Only {watched} of {len(groups)} selected apps available; '
                            'notification totals are unknown.', metadata, state)

        rows = [r for r in snap.rows if r[0] in reachable]
        waiting = sum(1 for r in rows if r[4] is None or r[4] > now)

        # Observation state: numbers plus the definition's own selected app ids.
        order = sorted(reachable)
        prev_ids = state.get('max_seen_id')
        prev_marks = state.get('last_added') if isinstance(state.get('last_added'), list) else None
        marks = [snap.last_added.get(a) for a in order]
        last_poll = state.get('last_poll_ts')
        since = state.get('observed_since')
        arrivals = [t for t in state.get('arrivals', []) if isinstance(t, (int, float)) and t > now - 86400]
        overflow = state.get('overflow_until')
        gap_limit = max(3 * every, 300)
        same_apps = state.get('apps') == order and prev_marks is not None and len(prev_marks) == len(order)
        started = isinstance(prev_ids, int) and isinstance(since, (int, float)) and isinstance(last_poll, (int, float))
        fresh = not started or not same_apps or now - last_poll > gap_limit or now < last_poll
        why = state.get('since_reason', 'start')
        top_id = max([r[1] for r in rows] + [snap.current_id or 0, prev_ids if isinstance(prev_ids, int) else 0])
        if fresh:
            since = now  # A gap or (re)start resets continuous observation.
            why = 'gap' if started and same_apps else 'start'
            if started and same_apps:
                arrivals += [r[3] or now for r in rows if r[1] > prev_ids]
        else:
            new_rows = [r for r in rows if r[1] > prev_ids]
            arrivals += [r[3] if r[3] is not None else now for r in new_rows]
            seen_apps = {r[0] for r in new_rows}
            for app, old, mark in zip(order, prev_marks or [], marks):
                # The registry stamp survives apps clearing their own toasts.
                if mark is not None and (old is None or mark > old + 0.5) and app not in seen_apps:
                    arrivals.append(mark)
        arrivals.sort()
        if len(arrivals) > MAX_ARRIVALS:
            arrivals = arrivals[-MAX_ARRIVALS:]
            overflow = now + 86400

        metrics: dict[str, float | int | None] = {'waiting': waiting}
        reasons = {}
        for metric, window in WINDOWS.items():
            if now - since < window:
                metrics[metric] = None
                reasons[metric] = R_GAP if why == 'gap' else R_WARMING
            elif isinstance(overflow, (int, float)) and overflow - 86400 + window > now:
                metrics[metric] = None
                reasons[metric] = R_OVERFLOW
            else:
                metrics[metric] = sum(1 for t in arrivals if now - window < t <= now)
        newest = max([r[3] for r in rows if r[3] is not None] + [m for m in marks if m is not None]
                     + ([arrivals[-1]] if arrivals else []), default=None)
        if newest is None:
            metrics['minutes_since_last'] = None
            reasons['minutes_since_last'] = R_NEVER
        else:
            metrics['minutes_since_last'] = round(max(0.0, now - newest) / 60, 1)
        new_state = {'max_seen_id': top_id, 'last_added': marks, 'last_poll_ts': now,
                     'observed_since': since, 'since_reason': why, 'arrivals': arrivals, 'apps': order}
        if isinstance(overflow, (int, float)) and overflow > now:
            new_state['overflow_until'] = overflow
        metadata['observed_since'] = since
        return SourceResult(sample={'ts': now, 'metrics': metrics, 'baselines': {}, 'unknown_reasons': reasons},
                            state=new_state, metadata=metadata)
