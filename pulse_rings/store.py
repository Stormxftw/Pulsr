"""Profile-local SQLite state; admission and claims are cross-process atomic."""
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import time
import os
import threading
import uuid
import difflib
import re

from .limits import MAX_ACTIVE, MAX_DRAFTS, DEFAULT_REQUESTS_PER_HOUR
from .spec import normalize, budget, admission
from .display_spec import feeds_of
from .feed_runtime import feed_budgets

ID = 'pulse-rings'
SCHEMA_VERSION = 1
MAX_PULSES = MAX_ACTIVE
_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = {}


class Store:
    def __init__(self, data_dir=None):
        self.managed = data_dir is None
        if self.managed:
            from plugins.plugin_storage import plugin_data_dir
            data_dir = plugin_data_dir(ID)
        self.root = Path(data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        with _SCHEMA_LOCK:
            with closing(self.db()) as db, db:
                identity = (self.root / 'pulse.sqlite3').stat()
                key = (os.getpid(), str(self.root.resolve()), identity.st_dev, identity.st_ino)
                schema_cookie = db.execute('PRAGMA schema_version').fetchone()[0]
                if _SCHEMA_READY.get(key) == schema_cookie:
                    version = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                    if not version or int(version[0]) != SCHEMA_VERSION:
                        raise ValueError('Unsupported Pulsr database schema version')
                    return
                self._initialize_schema(db)
                schema_cookie = db.execute('PRAGMA schema_version').fetchone()[0]
            # Only cache committed initialization, never a failed migration.
            _SCHEMA_READY[key] = schema_cookie

    def _initialize_schema(self, db):
        db.executescript('''
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pulses (
                id TEXT PRIMARY KEY, definition TEXT NOT NULL, paused INTEGER NOT NULL DEFAULT 0,
                next_due REAL NOT NULL DEFAULT 0, last_ok_ts REAL,
                backoff_until REAL NOT NULL DEFAULT 0, error TEXT,
                failures INTEGER NOT NULL DEFAULT 0, source_state TEXT NOT NULL DEFAULT '{}',
                metadata TEXT NOT NULL DEFAULT '{}', approved_via TEXT NOT NULL DEFAULT 'rest',
                created_ts REAL NOT NULL, updated_ts REAL NOT NULL, budget TEXT);
            CREATE TABLE IF NOT EXISTS samples (
                pulse_id TEXT NOT NULL, ts REAL NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(pulse_id, ts));
            CREATE TABLE IF NOT EXISTS gates (key TEXT PRIMARY KEY, until_ts REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS collection_lease (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), owner TEXT NOT NULL,
                expires_ts REAL NOT NULL, last_tick_ts REAL, next_tick_ts REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS drafts (
                id TEXT PRIMARY KEY, definition TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                created_ts REAL NOT NULL, expires_ts REAL NOT NULL, origin TEXT,
                replaces TEXT, note TEXT, sample TEXT, preview TEXT, decided_ts REAL, budget TEXT);
            CREATE TABLE IF NOT EXISTS hermes_events (
                id INTEGER PRIMARY KEY, ts REAL NOT NULL, kind TEXT NOT NULL,
                status TEXT, origin TEXT);
            CREATE INDEX IF NOT EXISTS hermes_events_ts ON hermes_events(ts);
            CREATE TABLE IF NOT EXISTS hermes_open (
                kind TEXT NOT NULL, key TEXT NOT NULL, ts REAL NOT NULL,
                expires_ts REAL NOT NULL, origin TEXT, PRIMARY KEY(kind,key));
        ''')
        version = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if version and int(version[0]) != SCHEMA_VERSION:
            raise ValueError('Unsupported Pulsr database schema version')
        db.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        # Additive v1 migration. Invalid old definitions stay visible and fail closed.
        for table in ('pulses', 'drafts'):
            if 'budget' not in {r[1] for r in db.execute(f'PRAGMA table_info({table})')}:
                db.execute(f'ALTER TABLE {table} ADD COLUMN budget TEXT')
                for row in db.execute(f'SELECT id,definition FROM {table}').fetchall():
                    try:
                        d = normalize(json.loads(row['definition']))
                        b = budget(d)
                    except Exception:
                        continue
                    db.execute(f'UPDATE {table} SET definition=?,budget=? WHERE id=?',
                               (json.dumps(d), json.dumps(b), row['id']))

        # Rebuild only the old sample key: two feeds may sample at the same ts.
        # DDL is guarded by the existing identity/schema-cookie cache.
        if 'feed' not in {r[1] for r in db.execute('PRAGMA table_info(samples)')}:
            db.execute('ALTER TABLE samples RENAME TO samples_v1')
            db.execute("""CREATE TABLE samples (pulse_id TEXT NOT NULL, ts REAL NOT NULL,
                payload TEXT NOT NULL, feed TEXT NOT NULL DEFAULT 'main',
                PRIMARY KEY(pulse_id,feed,ts))""")
            db.execute("INSERT INTO samples(pulse_id,ts,payload,feed) SELECT pulse_id,ts,payload,'main' FROM samples_v1")
            db.execute('DROP TABLE samples_v1')
        db.execute("""CREATE TABLE IF NOT EXISTS feeds (
            pulse_id TEXT NOT NULL, feed TEXT NOT NULL, source_state TEXT NOT NULL DEFAULT '{}',
            metadata TEXT NOT NULL DEFAULT '{}', next_due REAL NOT NULL DEFAULT 0,
            last_ok_ts REAL, error TEXT, failures INTEGER NOT NULL DEFAULT 0,
            backoff_until REAL NOT NULL DEFAULT 0, budget TEXT,
            PRIMARY KEY(pulse_id,feed))""")
        if 'generation' not in {r[1] for r in db.execute('PRAGMA table_info(samples)')}:
            db.execute('ALTER TABLE samples RENAME TO samples_pre_generation')
            db.execute("""CREATE TABLE samples (pulse_id TEXT NOT NULL, ts REAL NOT NULL,
                payload TEXT NOT NULL, feed TEXT NOT NULL DEFAULT 'main',
                generation TEXT NOT NULL DEFAULT '', PRIMARY KEY(pulse_id,feed,generation,ts))""")
            db.execute("""INSERT INTO samples(pulse_id,ts,payload,feed)
                SELECT pulse_id,ts,payload,feed FROM samples_pre_generation""")
            db.execute('DROP TABLE samples_pre_generation')
        if 'generation' not in {r[1] for r in db.execute('PRAGMA table_info(feeds)')}:
            db.execute("ALTER TABLE feeds ADD COLUMN generation TEXT NOT NULL DEFAULT ''")
        db.execute('CREATE INDEX IF NOT EXISTS feeds_due ON feeds(next_due,pulse_id,feed)')
        db.execute("""CREATE TABLE IF NOT EXISTS draft_feeds (
            draft_id TEXT NOT NULL, feed TEXT NOT NULL, source_state TEXT NOT NULL DEFAULT '{}',
            sample TEXT, metadata TEXT NOT NULL DEFAULT '{}', preview_calls INTEGER NOT NULL DEFAULT 0,
            preview_due REAL NOT NULL DEFAULT 0, preview_allowed INTEGER NOT NULL DEFAULT 0,
            preview_lease TEXT, preview_error TEXT, budget TEXT NOT NULL,
            PRIMARY KEY(draft_id,feed))""")
        for row in db.execute('SELECT * FROM pulses').fetchall():
            try:
                definition = json.loads(row['definition'])
                if definition.get('pulse') != 1:
                    continue
                allocations = feed_budgets(definition) if 'feeds' in definition else {'main': json.loads(row['budget'])}
                for name in feeds_of(definition):
                    legacy = 'source' in definition
                    db.execute("""INSERT OR IGNORE INTO feeds(pulse_id,feed,source_state,metadata,
                        next_due,last_ok_ts,error,failures,backoff_until,budget) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (row['id'], name, row['source_state'] if legacy else '{}',
                         row['metadata'] if legacy else '{}', row['next_due'] if legacy else 0,
                         row['last_ok_ts'] if legacy else None, row['error'] if legacy else None,
                         row['failures'] if legacy else 0, row['backoff_until'] if legacy else 0,
                         json.dumps(allocations[name])))
            except (ValueError, TypeError, KeyError, AttributeError):
                continue  # Preserve invalid/future rows, never invent approval.

        additions = {'source_state': "TEXT NOT NULL DEFAULT '{}'", 'preview_calls': 'INTEGER NOT NULL DEFAULT 0',
                     'preview_due': 'REAL NOT NULL DEFAULT 0', 'preview_allowed': 'INTEGER NOT NULL DEFAULT 0',
                     'auth': 'TEXT', 'preview_lease': 'TEXT', 'diff': 'TEXT', 'base_definition': 'TEXT', 'preview_error': 'TEXT'}
        columns = {r[1] for r in db.execute('PRAGMA table_info(drafts)')}
        for name, declaration in additions.items():
            if name not in columns:
                db.execute(f'ALTER TABLE drafts ADD COLUMN {name} {declaration}')

    def db(self, timeout: float = 5):
        if self.managed:
            from plugins.plugin_storage import plugin_db
            db = plugin_db(ID, filename='pulse.sqlite3')
        else:
            db = sqlite3.connect(self.root / 'pulse.sqlite3', timeout=timeout)
            db.execute('PRAGMA journal_mode=WAL')
        db.row_factory = sqlite3.Row
        db.execute(f'PRAGMA busy_timeout={int(timeout * 1000)}')
        return db

    @contextmanager
    def transaction(self):
        with closing(self.db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            yield db

    def put_pulse(self, definition, *, now=None, approved_via='rest', sample=None,
                  ceiling=DEFAULT_REQUESTS_PER_HOUR):
        """Human activation seam; validate once here, not during status reads."""
        now = time.time() if now is None else now
        if definition.get('pulse') == 1:
            definition = normalize(definition)
            computed = budget(definition)
        else:
            computed = {'hosts': [], 'req_per_hour': 0, 'req_per_hour_display': 0}
        with self.transaction() as db:
            self._put_pulse(db, definition, computed, now, approved_via, sample, ceiling)
        return definition['id']

    def _put_pulse(self, db, definition, computed, now, approved_via, sample, ceiling):
        known = db.execute('SELECT id FROM pulses WHERE id=?', (definition['id'],)).fetchone()
        if not known and db.execute('SELECT count(*) FROM pulses').fetchone()[0] >= MAX_ACTIVE:
            raise ValueError('At most 24 active pulses per profile.')
        active = []
        for r in db.execute('SELECT budget FROM pulses WHERE id!=?', (definition['id'],)):
            if r['budget'] is None:
                raise ValueError('Active request budget unknown; repair or remove the pulse first.')
            active.append(json.loads(r['budget']))
        errors = admission(active, computed, ceiling)
        if errors:
            raise ValueError(errors[0]['message'])
        from .feed_runtime import source_fingerprint
        old_row = db.execute('SELECT * FROM pulses WHERE id=?', (definition['id'],)).fetchone()
        old_definition = json.loads(old_row['definition']) if old_row else {}
        old_feeds = self.feed_rows(definition['id'], db=db)
        retained = {name for name in (feeds_of(definition) if definition.get('pulse') == 1 else {}) if name in old_feeds
                    and old_definition.get('pulse') == 1 and name in feeds_of(old_definition)
                    and source_fingerprint(definition, name) == source_fingerprint(old_definition, name)}
        db.execute('''INSERT INTO pulses(id,definition,created_ts,updated_ts,approved_via,budget)
            VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET definition=excluded.definition,
            budget=excluded.budget, updated_ts=excluded.updated_ts, approved_via=excluded.approved_via''',
            (definition['id'], json.dumps(definition), now, now, approved_via, json.dumps(computed)))
        if 'main' not in retained or 'source' not in definition:
            db.execute("""UPDATE pulses SET error=NULL,failures=0,source_state='{}',metadata='{}',
                next_due=0,backoff_until=0,last_ok_ts=NULL WHERE id=?""", (definition['id'],))
        db.execute('DELETE FROM feeds WHERE pulse_id=?', (definition['id'],))
        if definition.get('pulse') == 1:
            allocations = feed_budgets(definition) if 'feeds' in definition else {'main': computed}
            for name in feeds_of(definition):
                db.execute('INSERT INTO feeds(pulse_id,feed,budget,generation) VALUES (?,?,?,?)',
                           (definition['id'], name, json.dumps(allocations[name]),
                            old_feeds[name]['generation'] if name in retained else uuid.uuid4().hex))
                if name in retained:
                    state = old_feeds[name]
                    # Legacy columns remain authoritative for old DB/import seams.
                    if 'source' in old_definition:
                        state = dict(old_row)
                    keys = ('source_state', 'metadata', 'next_due', 'last_ok_ts', 'error', 'failures', 'backoff_until')
                    assignments = ','.join(f'{key}=?' for key in keys)
                    db.execute(f'UPDATE feeds SET {assignments} WHERE pulse_id=? AND feed=?',
                               (*(state[k] for k in keys), definition['id'], name))
        if 'source' in definition and 'main' in retained and 'feeds' in old_definition:
            keys = ('source_state', 'metadata', 'next_due', 'last_ok_ts', 'error', 'failures', 'backoff_until')
            assignments = ','.join(f'{key}=?' for key in keys)
            db.execute(f'UPDATE pulses SET {assignments} WHERE id=?',
                       (*(old_feeds['main'][k] for k in keys), definition['id']))
        if 'feeds' in definition and sample is not None:
            for name, observation in sample.items():
                if name in definition['feeds'] and observation is not None:
                    self.insert_sample(db, definition['id'], observation, feed=name)
                    db.execute('UPDATE feeds SET last_ok_ts=?,metadata=? WHERE pulse_id=? AND feed=?',
                               (observation['ts'], json.dumps(observation.get('metadata', {})), definition['id'], name))
        elif sample is not None:
            self.insert_sample(db, definition['id'], sample)
            db.execute('UPDATE pulses SET last_ok_ts=?,metadata=? WHERE id=?',
                       (sample['ts'], json.dumps(sample.get('metadata', {})), definition['id']))

    @staticmethod
    def insert_sample(db, pulse_id, sample, *, feed='main', generation=None):
        if generation is None:
            row = db.execute('SELECT generation FROM feeds WHERE pulse_id=? AND feed=?', (pulse_id, feed)).fetchone()
            generation = row['generation'] if row else ''
        slim = {k: v for k, v in sample.items() if k != 'metadata'}
        db.execute('INSERT OR REPLACE INTO samples(pulse_id,ts,payload,feed,generation) VALUES (?,?,?,?,?)',
                   (pulse_id, sample['ts'], json.dumps(slim, allow_nan=False), feed, generation))

    @contextmanager
    def read(self, db=None):
        if db is not None:
            yield db
        else:
            with closing(self.db()) as connection:
                yield connection

    def rows(self, *, db=None):
        with self.read(db) as db:
            return [dict(row) for row in db.execute('SELECT * FROM pulses ORDER BY id')]

    def history(self, pulse_id, since=0, tail=0, *, feed='main', generation=None, db=None, limit=20161):
        """Compatible current generation only; archived observations stay on disk."""
        with self.read(db) as db:
            if generation is None:
                row = db.execute('SELECT generation FROM feeds WHERE pulse_id=? AND feed=?', (pulse_id, feed)).fetchone()
                generation = row['generation'] if row else ''
            return [json.loads(row['payload']) for row in db.execute('''
                SELECT ts,payload FROM (SELECT ts,payload FROM samples WHERE pulse_id=? AND feed=? AND generation=? AND ts>=?
                    ORDER BY ts DESC LIMIT ?)
                UNION SELECT ts,payload FROM (SELECT ts,payload FROM samples
                    WHERE pulse_id=? AND feed=? AND generation=? ORDER BY ts DESC LIMIT ?)
                ORDER BY ts''', (pulse_id, feed, generation, since, limit, pulse_id, feed, generation, tail))]

    def bucketed(self, pulse_id, metric, since, width, *, feed='main', db=None):
        """Mean time and value of one numeric metric per time bucket, current generation only.

        A bounded read for charts: SQLite aggregates, so a pulse sampled every few
        seconds returns at most (now - since) / width rows. Booleans, nulls and
        non-numbers are skipped. Returns [] if this SQLite build lacks JSON functions.
        """
        path = '$.metrics."' + str(metric).replace('"', '') + '"'
        with self.read(db) as db:
            row = db.execute('SELECT generation FROM feeds WHERE pulse_id=? AND feed=?', (pulse_id, feed)).fetchone()
            try:
                return [{'ts': r[0], 'value': r[1]} for r in db.execute('''
                    SELECT AVG(ts), AVG(json_extract(payload, ?)) FROM samples
                    WHERE pulse_id=? AND feed=? AND generation=? AND ts>=?
                        AND json_type(payload, ?) IN ('integer', 'real')
                    GROUP BY CAST(ts / ? AS INTEGER) ORDER BY 1''',
                    (path, pulse_id, feed, row['generation'] if row else '', since, path, width))]
            except sqlite3.OperationalError:
                return []

    def feed_rows(self, pulse_id, *, db=None):
        with self.read(db) as db:
            return {r['feed']: dict(r) for r in db.execute('SELECT * FROM feeds WHERE pulse_id=?', (pulse_id,))}

    def pause(self, pulse_id, paused, now=None):
        with self.transaction() as db:
            return bool(db.execute('UPDATE pulses SET paused=?,updated_ts=? WHERE id=?',
                (int(paused), time.time() if now is None else now, pulse_id)).rowcount)

    def remove(self, pulse_id):
        with self.transaction() as db:
            return bool(db.execute('DELETE FROM pulses WHERE id=?', (pulse_id,)).rowcount)

    def claim_due(self, now, *, in_progress=None):
        """Claim one due feed, longest overdue first.

        `in_progress(row)` is an optional pure hint (no I/O: it runs inside the
        claim transaction). A due feed it marks True holds bounded staged work and
        is finished before another collection starts; a failing hint is ignored.
        Due time, backoff, pause and the 90-second claim lease are unchanged.
        """
        def started(row):
            try:
                return in_progress is not None and in_progress(row) is True
            except Exception:
                return False
        with self.transaction() as db:
            # Legacy pulse columns remain authoritative for old importers/DBs.
            rows = []
            for pulse in db.execute('SELECT * FROM pulses WHERE paused=0').fetchall():
                try:
                    definition = json.loads(pulse['definition'])
                except (ValueError, TypeError):
                    definition = {}
                if isinstance(definition, dict) and 'feeds' in definition:
                    for feed in db.execute('SELECT * FROM feeds WHERE pulse_id=? AND next_due<=? AND backoff_until<=?',
                                           (pulse['id'], now, now)):
                        rows.append(dict(dict(pulse), **{k: feed[k] for k in ('feed','generation','next_due','last_ok_ts','backoff_until','error','failures','source_state','metadata')}))
                elif pulse['next_due'] <= now and pulse['backoff_until'] <= now:
                    generation = db.execute("SELECT generation FROM feeds WHERE pulse_id=? AND feed='main'", (pulse['id'],)).fetchone()
                    rows.append(dict(dict(pulse), feed='main', generation=generation[0] if generation else ''))
            rows.sort(key=lambda r: (not started(r), r['next_due'], r['id'], r['feed']))
            for row in rows:
                try:
                    major = json.loads(row['definition']).get('pulse')
                except (ValueError, TypeError, AttributeError):
                    db.execute('UPDATE pulses SET error=?,next_due=? WHERE id=?',
                               ('Invalid stored definition', now + 86400, row['id']))
                    continue
                if major == 1:
                    if 'feeds' in json.loads(row['definition']):
                        db.execute('UPDATE feeds SET next_due=? WHERE pulse_id=? AND feed=?', (now + 90, row['id'], row['feed']))
                    else:
                        db.execute('UPDATE pulses SET next_due=? WHERE id=?', (now + 90, row['id']))
                    return dict(row)
        return None

    @staticmethod
    def claim_current(db, row):
        return db.execute('''SELECT 1 FROM feeds f JOIN pulses p ON p.id=f.pulse_id
            WHERE f.pulse_id=? AND f.feed=? AND f.generation=?''',
            (row['id'], row.get('feed', 'main'), row.get('generation', ''))).fetchone() is not None

    @staticmethod
    def update_feed(db, row, **values):
        """Write the claimed feed; mirror legacy columns for old import/read seams."""
        if not Store.claim_current(db, row):
            return False
        assignments = ','.join(f'{key}=?' for key in values)
        current = db.execute('SELECT definition FROM pulses WHERE id=?', (row['id'],)).fetchone()
        if 'feeds' not in json.loads(current['definition']):
            db.execute(f'UPDATE pulses SET {assignments} WHERE id=?', (*values.values(), row['id']))
        db.execute(f'UPDATE feeds SET {assignments} WHERE pulse_id=? AND feed=?',
                   (*values.values(), row['id'], row.get('feed', 'main')))

    def gate(self, key, *, db=None):
        with self.read(db) as db:
            row = db.execute('SELECT until_ts FROM gates WHERE key=?', (key,)).fetchone()
            return row[0] if row else 0

    def extend_gate(self, key, until):
        with self.transaction() as db:
            db.execute('''INSERT INTO gates VALUES (?,?) ON CONFLICT(key) DO UPDATE
                SET until_ts=MAX(until_ts,excluded.until_ts)''', (key, until))

    def put_draft(self, definition, *, now=None, origin=None, sample=None, preview=None,
                  replaces=None, note=None, preview_allowed=False, auth=None, preview_feeds=None):
        """Persist normalized, server-budgeted proposal, never activate it."""
        now = time.time() if now is None else now
        d = normalize(definition)
        b = budget(d)
        if not isinstance(origin or {}, dict):
            raise ValueError('Draft origin must be an object')
        draft_id = 'pd_' + uuid.uuid4().hex[:10]
        with self.transaction() as db:
            db.execute("UPDATE drafts SET status='expired',decided_ts=? WHERE status='pending' AND expires_ts<=?", (now, now))
            if db.execute("SELECT count(*) FROM drafts WHERE status='pending'").fetchone()[0] >= MAX_DRAFTS:
                raise ValueError('At most 5 pending drafts per profile.')
            existing = db.execute('SELECT definition FROM pulses WHERE id=?', (d['id'],)).fetchone()
            if replaces is not None and (replaces != d['id'] or existing is None):
                raise ValueError('replaces must name the existing definition id.')
            replaces = d['id'] if existing else None
            before = existing['definition'] if existing else None
            diff = ''.join(difflib.unified_diff(
                json.dumps(json.loads(before), indent=2, sort_keys=True).splitlines(True) if before else [],
                json.dumps(d, indent=2, sort_keys=True).splitlines(True), fromfile='active', tofile='proposed')) if before else None
            db.execute("""INSERT INTO drafts(id,definition,created_ts,expires_ts,origin,sample,preview,budget,
                replaces,note,preview_allowed,diff,base_definition,auth) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (draft_id, json.dumps(d), now, now + 7 * 86400, json.dumps({k: v for k, v in (origin or {}).items() if k != 'session_id'}),
                 json.dumps(sample) if sample else None, json.dumps(preview) if preview else None,
                 json.dumps(b), replaces, note, int(preview_allowed), diff, before, auth))
            if 'feeds' in d:
                allocations = feed_budgets(d)
                for name in d['feeds']:
                    observation = (sample or {}).get(name)
                    db.execute('''INSERT INTO draft_feeds(draft_id,feed,preview_allowed,budget,sample)
                        VALUES (?,?,?,?,?)''', (draft_id, name, int(name in (preview_feeds or [])),
                        json.dumps(allocations[name]), json.dumps(observation) if observation else None))
        return draft_id

    def draft(self, draft_id, now):
        if not isinstance(draft_id, str) or not re.fullmatch(r'pd_[a-f0-9]{10}', draft_id):
            raise KeyError('Draft not found')
        with self.transaction() as db:
            db.execute("UPDATE drafts SET status='expired',decided_ts=? WHERE status='pending' AND expires_ts<=?", (now, now))
            row = db.execute('SELECT * FROM drafts WHERE id=?', (draft_id,)).fetchone()
        if row is None:
            raise KeyError('Draft not found')
        item = dict(row)
        for key in ('definition', 'origin', 'budget', 'sample', 'preview', 'source_state'):
            if item[key] is not None:
                item[key] = json.loads(item[key])
        if any(not isinstance(item[key], dict) for key in ('definition', 'origin', 'budget', 'source_state')):
            raise ValueError('Invalid stored draft object')
        if 'feeds' in item['definition']:
            from .feed_previews import records
            item['_preview_feeds'] = records(self, draft_id)
        return item

    def claim_preview(self, now, draft_id=None):
        claimed = self._claim_legacy_preview(now, draft_id)
        if claimed is not None:
            return claimed
        from .feed_previews import claim
        return claim(self, now, draft_id)

    def _claim_legacy_preview(self, now, draft_id=None):
        token = uuid.uuid4().hex
        with self.transaction() as db:
            row = db.execute("""SELECT * FROM drafts WHERE status='pending' AND expires_ts>?
                AND NOT EXISTS(SELECT 1 FROM draft_feeds f WHERE f.draft_id=drafts.id)
                AND preview_allowed=1 AND preview_calls<2 AND sample IS NULL AND preview_due<=?
                AND (? IS NULL OR id=?) ORDER BY preview_due,created_ts,id LIMIT 1""",
                (now, now, draft_id, draft_id)).fetchone()
            if row is None:
                return None
            db.execute('UPDATE drafts SET preview_due=?,preview_lease=? WHERE id=?', (now + 90, token, row['id']))
        return row['id'], token

    def preview_call(self, draft_id, token, now, *, feed=None):
        """Count dispatches after host admission, before sending; crash-safe upper bound."""
        if feed is not None:
            from .feed_previews import call
            return call(self, draft_id, token, now, feed)
        with self.transaction() as db:
            changed = db.execute("""UPDATE drafts SET preview_calls=preview_calls+1 WHERE id=?
                AND preview_lease=? AND status='pending' AND expires_ts>? AND preview_calls<2""",
                (draft_id, token, now)).rowcount
            if not changed:
                raise ValueError('Draft preview no longer available')

    def finish_preview(self, draft_id, token, *, state=None, sample=None, preview=None, due=0, error=None, feed=None):
        if feed is not None:
            from .feed_previews import finish
            return finish(self, draft_id, token, feed, state=state, sample=sample, preview=preview, due=due, error=error)
        with self.transaction() as db:
            db.execute("""UPDATE drafts SET source_state=COALESCE(?,source_state),sample=COALESCE(?,sample),
                preview=COALESCE(?,preview),preview_due=?,preview_error=?,preview_lease=NULL
                WHERE id=? AND preview_lease=? AND status='pending'""",
                (json.dumps(state) if state is not None else None,
                 json.dumps(sample) if sample is not None else None,
                 json.dumps(preview) if preview is not None else None, due, error, draft_id, token))

    def decide_draft(self, draft_id, decision, *, now, ceiling=DEFAULT_REQUESTS_PER_HOUR, via='rest'):
        if decision not in ('approve', 'reject'):
            raise ValueError('Unknown decision')
        self.draft(draft_id, now)  # Commit expiry even when the decision is refused.
        with self.transaction() as db:
            row = db.execute('SELECT * FROM drafts WHERE id=?', (draft_id,)).fetchone()
            if row['status'] != 'pending':
                raise ValueError('Draft is ' + row['status'])
            if decision == 'approve':
                d = json.loads(row['definition'])
                existing = db.execute('SELECT definition FROM pulses WHERE id=?', (d['id'],)).fetchone()
                if (existing['definition'] if existing else None) != row['base_definition']:
                    raise ValueError('Active definition changed; propose again to review a fresh diff.')
                sample = json.loads(row['sample']) if row['sample'] else None
                before = self.feed_rows(d['id'], db=db)
                self._put_pulse(db, d, json.loads(row['budget']), now, via, sample, ceiling)
                after = self.feed_rows(d['id'], db=db)
                retained = {name for name in after if name in before
                            and after[name]['generation'] == before[name]['generation']}
                db.execute('UPDATE pulses SET next_due=? WHERE id=?', (now + 2, d['id']))
                if 'source' in d and 'main' not in retained:
                    db.execute('UPDATE pulses SET source_state=? WHERE id=?', (row['source_state'], d['id']))
                if 'feeds' in d:
                    for feed in db.execute('SELECT * FROM draft_feeds WHERE draft_id=?', (draft_id,)).fetchall():
                        db.execute('UPDATE feeds SET next_due=? WHERE pulse_id=? AND feed=?',
                                   (now + 2, d['id'], feed['feed']))
                        if feed['feed'] not in retained:
                            db.execute('UPDATE feeds SET source_state=?,metadata=? WHERE pulse_id=? AND feed=?',
                                       (feed['source_state'], feed['metadata'], d['id'], feed['feed']))
                else:
                    db.execute("UPDATE feeds SET next_due=?,source_state=(SELECT source_state FROM pulses WHERE id=?) WHERE pulse_id=? AND feed='main'",
                               (now + 2, d['id'], d['id']))
            db.execute('UPDATE drafts SET status=?,decided_ts=?,preview_lease=NULL WHERE id=?',
                       ('approved' if decision == 'approve' else 'rejected', now, draft_id))
        return self.draft(draft_id, now)

    def pending_drafts(self, now, *, db=None):
        # Historical method name retained; decided rows let cards read back outcomes.
        with self.read(db) as db:
            result = []
            for row in db.execute("""SELECT * FROM drafts WHERE status='pending' OR id IN
                (SELECT id FROM drafts ORDER BY created_ts DESC LIMIT 50) ORDER BY created_ts DESC"""):
                item = dict(row)
                try:
                    for key in ('definition', 'sample', 'preview', 'origin', 'budget', 'source_state'):
                        if item[key] is not None:
                            item[key] = json.loads(item[key])
                    item['origin'] = item['origin'] if isinstance(item['origin'], dict) else {}
                    if item['status'] == 'pending' and item['expires_ts'] <= now:
                        item['status'] = 'expired'
                    if item['status'] not in ('pending', 'approved', 'rejected', 'expired'):
                        item['status'] = 'expired'
                    if 'feeds' in item['definition']:
                        from .feed_previews import records
                        item['_preview_feeds'] = records(self, item['id'], db=db)
                    json.dumps(item, allow_nan=False)
                except (ValueError, TypeError):
                    item = {'id': row['id'], 'status': 'expired', 'origin': {}, 'budget': None,
                            'preview': None, 'definition': {}, 'sample': None, 'expires_ts': None}
                result.append(item)
            return result
