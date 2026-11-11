"""One-time HUMAN-consented, offline import of Discord Pulse v0.3.0 data.

No hooks/tool registration or automatic migration. plan() is read-only; apply()
requires literal consent=True and the exact plan token. Source DB is opened with
mode=ro AND immutable=1 so even SQLite's WAL/SHM housekeeping cannot write there.
A pending WAL is refused (ask the user to close the old plugin first), never
silently ignored, checkpointed, copied into the repository or modified by us.
"""
from contextlib import closing
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import sqlite3
import time

from .icons import GUILD_RE, ICON_RE, ICON_LIMIT, image_type
from .limits import MAX_ACTIVE, DEFAULT_REQUESTS_PER_HOUR
from .net import strict_json
from .spec import normalize, budget, admission
from .sources.discord import parse_invite

MARKER = 'discord_pulse_import_v1'
NOTE_LIMIT = 1024 * 1024


class MigrationError(ValueError):
    """Sanitized local import failure, safe for the consent card."""


def _safe_path(root, path):
    """No symlink/junction/reparse traversal at any existing component."""
    root, path = root.absolute(), path.absolute()
    if not path.is_relative_to(root):
        return False
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
            return False
    return True


def _read_file(root, path, limit):
    if not _safe_path(root, path) or not path.is_file():
        return None
    try:
        with path.open('rb') as stream:
            raw = stream.read(limit + 1)
        return raw if len(raw) <= limit else None
    except OSError:
        return None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return value if math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None


def _pulse_id(code, guild, collisions):
    slug = re.sub(r'[^a-z0-9-]+', '-', code.lower()).strip('-') or 'server'
    if len(slug) > 40 or collisions:
        slug = slug[:29] + '-' + hashlib.sha256(guild.encode()).hexdigest()[:10]
    return 'discord-' + slug


def _empty(*, available=False, completed=False):
    return {'available': available, 'completed': completed, 'pulses': 0, 'samples': 0,
            'notes': 0, 'icons': 0, 'skipped_existing': 0, 'skipped_invalid': 0,
            'skipped_admission': 0, 'ids': [], 'budget': {'hosts': [], 'req_per_hour': 0,
            'req_per_hour_display': 0}, 'summary': 'Import 0 pulses · 0 samples · 0 notes',
            'recommendation': 'After import, disable Discord Pulse yourself to avoid double polling; its data is kept.'}


class DiscordPulseImporter:
    def __init__(self, store, *, hermes_home=None, clock=time.time,
                 ceiling=DEFAULT_REQUESTS_PER_HOUR):
        if hermes_home is None:
            from hermes_constants import get_hermes_home
            hermes_home = get_hermes_home()
        self.source = Path(hermes_home) / 'plugin-data' / 'discord-pulse'
        self.store, self.clock, self.ceiling = store, clock, ceiling
        if store.root.resolve().is_relative_to(self.source.resolve()):
            raise MigrationError('Import destination must not be inside the Discord Pulse source.')

    def offer(self, *, db=None):
        """Cheap first-run banner probe; never opens or reads the old database."""
        with self.store.read(db) as db:
            completed = bool(db.execute('SELECT 1 FROM meta WHERE key=?', (MARKER,)).fetchone())
        path = self.source / 'pulse.sqlite3'
        return {'available': not completed and _safe_path(self.source, path) and path.is_file(),
                'completed': completed}

    def _source_rows(self):
        path = self.source / 'pulse.sqlite3'
        if not _safe_path(self.source, path) or not path.is_file():
            return None
        wal = path.with_name(path.name + '-wal')
        if wal.exists() and (not _safe_path(self.source, wal) or wal.stat().st_size):
            raise MigrationError('Discord Pulse has a pending WAL. Close the old plugin before importing.')
        journal = path.with_name(path.name + '-journal')
        if journal.exists() and (not _safe_path(self.source, journal) or journal.stat().st_size):
            raise MigrationError('Discord Pulse has an active journal. Close the old plugin before importing.')
        with path.open('rb') as stream:
            before = hashlib.file_digest(stream, 'sha256').hexdigest()
        # immutable=1 prevents read-only SQLite from creating/updating -shm files.
        uri = path.resolve().as_uri() + '?mode=ro&immutable=1'
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            for table, expected in {
                'servers': {'id', 'code', 'payload'},
                'snapshots': {'guild', 'ts', 'payload'},
                'gates': {'key', 'until_ts'},
            }.items():
                if not expected <= {row[1] for row in db.execute(f'PRAGMA table_info({table})')}:
                    raise MigrationError('Unsupported Discord Pulse database schema.')
                entry = db.execute('SELECT type FROM sqlite_master WHERE name=?', (table,)).fetchone()
                if not entry or entry[0] != 'table':
                    raise MigrationError('Unsupported Discord Pulse database schema.')
            servers = [dict(row) for row in db.execute('SELECT id,code,payload FROM servers ORDER BY id')]
            snapshots = [dict(row) for row in db.execute('SELECT guild,ts,payload FROM snapshots ORDER BY guild,ts')]
            # A writer starting a WAL mid-read must not turn this into a stale import.
            if wal.exists() and wal.stat().st_size:
                raise MigrationError('Discord Pulse has a pending WAL. Close the old plugin before importing.')
        with path.open('rb') as stream:
            unchanged = before == hashlib.file_digest(stream, 'sha256').hexdigest()
        if not unchanged or (journal.exists() and journal.stat().st_size):
            raise MigrationError('Discord Pulse source changed; close the old plugin and review a new import plan.')
        return servers, snapshots

    def _candidate(self, db):
        completed = db.execute('SELECT value FROM meta WHERE key=?', (MARKER,)).fetchone()
        existing = [dict(row) for row in db.execute('SELECT id,budget,definition,approved_via FROM pulses ORDER BY id')]
        result = _empty(completed=bool(completed))
        if completed:
            return result, [], {'marker': completed[0]}
        rows = self._source_rows()
        if rows is None:
            return result, [], {'missing': True}
        servers, snapshots = rows
        result['available'] = True
        ids = {row['id'] for row in existing}
        allocations = []
        unknown_budget = False
        for row in existing:
            try:
                b = strict_json(row['budget'])
                if _number(b['req_per_hour']) is None:
                    raise ValueError()
                allocations.append(b)
            except (ValueError, TypeError, KeyError):
                unknown_budget = True
        candidates, groups = [], {}
        for row in servers:
            try:
                guild = row['id']
                if not isinstance(guild, str) or not GUILD_RE.fullmatch(guild):
                    raise ValueError()
                payload = strict_json(row['payload'])
                if not isinstance(payload, dict) or not isinstance(payload.get('name'), str) or not payload['name'].strip():
                    raise ValueError()
                code = parse_invite(row['code'])
                base = _pulse_id(code, guild, False)
                groups[base] = groups.get(base, 0) + 1
                candidates.append((guild, code, payload, base))
            except (ValueError, TypeError):
                result['skipped_invalid'] += 1
        samples = {}
        for row in snapshots:
            try:
                if row['guild'] not in {candidate[0] for candidate in candidates}:
                    continue  # Unwatched/orphan history is not an active pulse.
                ts = _number(row['ts'])
                if ts is None:
                    raise ValueError()
                raw = strict_json(row['payload'])
                if not isinstance(raw, dict):
                    raise ValueError()
                metrics = {key: _number(raw.get(key)) for key in ('online', 'members')}
                samples.setdefault(row['guild'], []).append({'ts': ts, 'metrics': metrics, 'baselines': {},
                    'unknown_reasons': {key: 'Not measured in imported snapshot.' for key, value in metrics.items() if value is None}})
            except (ValueError, TypeError):
                result['skipped_invalid'] += 1
        selected, file_fingerprints = [], []
        for guild, code, payload, base in candidates:
            pulse_id = _pulse_id(code, guild, groups[base] > 1)
            if pulse_id in ids:
                result['skipped_existing'] += 1
                continue
            d = normalize({'pulse': 1, 'id': pulse_id, 'title': payload['name'][:60],
                'source': {'kind': 'discord.invite', 'params': {'invite': code, 'voice': True}}})
            b = budget(d)
            if len(ids) >= MAX_ACTIVE or unknown_budget or admission(allocations, b, self.ceiling):
                result['skipped_admission'] += 1
                continue
            metadata = {'id': guild, 'name': payload['name'][:100]}
            files = []
            note = _read_file(self.source, self.source / 'notes' / (guild + '.md'), NOTE_LIMIT)
            if note is not None:
                try:
                    note.decode('utf-8')
                except UnicodeError:
                    note = None
            if note is not None:
                relative = Path('notes') / (pulse_id + '.md')
                if self._copy_allowed(relative):
                    files.append((relative, note, 'notes'))
            icon = payload.get('icon_hash')
            if isinstance(icon, str) and ICON_RE.fullmatch(icon):
                relative = Path('icons') / (guild + '-' + icon + '.image')
                raw = _read_file(self.source, self.source / relative, ICON_LIMIT)
                if raw is not None and image_type(raw):
                    metadata['icon_hash'] = icon
                    if self._copy_allowed(relative):
                        files.append((relative, raw, 'icons'))
            history = samples.get(guild, [])
            selected.append({'definition': d, 'budget': b, 'metadata': metadata, 'samples': history, 'files': files})
            ids.add(pulse_id)
            allocations.append(b)
            result['ids'].append(pulse_id)
            result['pulses'] += 1
            result['samples'] += len(history)
            result['budget']['req_per_hour'] += b['req_per_hour']
            result['budget']['hosts'] = sorted(set(result['budget']['hosts']) | set(b['hosts']))
            for relative, raw, kind in files:
                result[kind] += 1
                file_fingerprints.append((relative.as_posix(), hashlib.sha256(raw).hexdigest()))
        result['budget']['req_per_hour_display'] = math.ceil(result['budget']['req_per_hour'])
        result['summary'] = (f"Import {result['pulses']} pulses · {result['samples']} samples · "
                             f"{result['notes']} {'note' if result['notes'] == 1 else 'notes'}")
        fingerprint = {'servers': servers, 'snapshots': snapshots, 'existing': existing,
                       'files': file_fingerprints, 'ceiling': self.ceiling}
        return result, selected, fingerprint

    def _copy_allowed(self, relative):
        target = self.store.root / relative
        return _safe_path(self.store.root, target) and not target.exists()

    @staticmethod
    def _token(summary, fingerprint):
        encoded = json.dumps([summary, fingerprint], sort_keys=True, ensure_ascii=True, allow_nan=False).encode()
        return hashlib.sha256(encoded).hexdigest()

    def plan(self):
        """No target writes, network, source writes, hooks or automatic approval."""
        try:
            with closing(self.store.db()) as db:
                result, _, fingerprint = self._candidate(db)
            result['token'] = self._token(result, fingerprint)
            return result
        except MigrationError:
            raise
        except Exception:
            raise MigrationError('Could not read the Discord Pulse import safely.') from None

    def _copy(self, relative, raw):
        path = self.store.root / relative
        if not self._copy_allowed(relative):
            raise MigrationError('Import destination changed; review a new import plan.')
        path.parent.mkdir(exist_ok=True)
        if not _safe_path(self.store.root, path):
            raise MigrationError('Import destination is not a safe local directory.')
        # Exclusive create: never replace notes/icons belonging to a human.
        owned = False
        try:
            with path.open('xb') as stream:
                owned = True
                stream.write(raw)
        except Exception:
            # Never unlink somebody else's file after losing an exclusive-create race.
            if owned and _safe_path(self.store.root, path):
                path.unlink(missing_ok=True)
            raise
        return path

    def apply(self, *, consent=False, token=None):
        if consent is not True:
            raise MigrationError('Explicit human consent is required to import.')
        if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{64}', token):
            raise MigrationError('Review an import plan before giving consent.')
        created = []
        try:
            with self.store.transaction() as db:
                result, selected, fingerprint = self._candidate(db)
                if result['completed']:
                    return result  # One-time marker survives restarts/deletions.
                if not result['available']:
                    raise MigrationError('Discord Pulse data is not available to import.')
                if not hmac.compare_digest(token, self._token(result, fingerprint)):
                    raise MigrationError('Import data or destination changed; review a new import plan.')
                now = self.clock()
                for item in selected:
                    d, history = item['definition'], item['samples']
                    # BEGIN IMMEDIATE holds the same cap/admission critical section
                    # as Store.put_pulse. INSERT (not upsert) prevents overwrites.
                    db.execute('''INSERT INTO pulses(id,definition,budget,metadata,approved_via,created_ts,updated_ts,last_ok_ts)
                        VALUES (?,?,?,?,?,?,?,?)''', (d['id'], json.dumps(d, allow_nan=False),
                        json.dumps(item['budget']), json.dumps(item['metadata']), 'import', now, now,
                        history[-1]['ts'] if history else None))
                    # Create the generation before importing its compatible observations.
                    import uuid
                    db.execute('''INSERT INTO feeds(pulse_id,feed,generation,budget,metadata,last_ok_ts)
                        VALUES (?,'main',?,?,?,?)''', (d['id'], uuid.uuid4().hex,
                        json.dumps(item['budget']), json.dumps(item['metadata']),
                        history[-1]['ts'] if history else None))
                    for sample in history:
                        self.store.insert_sample(db, d['id'], sample)
                    for relative, raw, _ in item['files']:
                        created.append(self._copy(relative, raw))
                db.execute('INSERT INTO meta(key,value) VALUES (?,?)', (MARKER, json.dumps({'ts': now, 'ids': result['ids']})))
            result['completed'] = True
            return result
        except Exception as exc:
            for path in reversed(created):
                try:
                    if _safe_path(self.store.root, path):
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
            if isinstance(exc, MigrationError):
                raise
            raise MigrationError('Discord Pulse import failed; target database changes were rolled back.') from None
