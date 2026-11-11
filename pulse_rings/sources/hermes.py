"""Local counts-only source; reads only this plugin's observer tables."""
from contextlib import closing
import math
import copy
import sqlite3

from .base import SourceError, SourceResult
from ..store import Store

METRICS = ('turns_running', 'waiting_on_you', 'tool_calls_10m', 'tool_errors_1h',
           'subagents_running', 'provider_errors_1h')
COVERAGE = 'Only this profile with Pulsr enabled; open pairs expire after crashes.'


class HermesActivity:
    def __init__(self, store=None):
        self.store = store if store is not None else Store()

    def current(self, sample, state, *, now):
        try:
            from ..hooks import flush_pending
            flush_pending(self.store)
            uri = (self.store.root / 'pulse.sqlite3').resolve().as_uri() + '?mode=ro'
            with closing(sqlite3.connect(uri, uri=True, timeout=0.25)) as db:
                db.execute('PRAGMA query_only=ON')
                observed = db.execute("SELECT value FROM meta WHERE key='hermes_observed_since'").fetchone()
                since = float(observed[0]) if observed else None
                if since is None or not math.isfinite(since) or since > now:
                    return sample
                rows = db.execute('SELECT kind,count(*) FROM hermes_open WHERE expires_ts>? AND ts<=? GROUP BY kind', (now, now))
                counts = {'turns_running': 0, 'waiting_on_you': 0, 'subagents_running': 0}
                for kind, count in rows:
                    metric = {'turn': 'turns_running', 'subagent': 'subagents_running'}.get(kind)
                    if kind in ('waiting:approval', 'waiting:clarify', 'waiting:sudo'):
                        metric = 'waiting_on_you'
                    if metric:
                        counts[metric] += count
            result = copy.deepcopy(sample)
            result.setdefault('metrics', {}).update(counts)
            for metric in counts:
                result.get('unknown_reasons', {}).pop(metric, None)
            return result
        except Exception:
            return sample

    def poll(self, definition, previous, state, *, now, net):
        try:
            if definition['source']['params'].get('scope', 'profile') != 'profile':
                raise SourceError('Unsupported Hermes activity scope.')
            from ..hooks import flush_pending
            flush_pending(self.store)
            with closing(self.store.db(timeout=0.25)) as db, db:
                db.execute('DELETE FROM hermes_events WHERE ts<=?', (now - 48 * 3600,))
                db.execute('DELETE FROM hermes_open WHERE expires_ts<=?', (now,))
                observed = db.execute("SELECT value FROM meta WHERE key='hermes_observed_since'").fetchone()
                since = float(observed[0]) if observed else None
                if since is None or not math.isfinite(since) or since > now:
                    return SourceResult(sample={'ts': now, 'metrics': {key: None for key in METRICS},
                        'baselines': {}, 'unknown_reasons': {key: 'Observer hooks have not been initialized.' for key in METRICS}},
                        metadata={'coverage': COVERAGE})
                opens = db.execute('SELECT kind,origin,count(*) FROM hermes_open WHERE expires_ts>? AND ts<=? GROUP BY kind,origin',
                                   (now, now)).fetchall()
                counts = {key: 0 for key in METRICS}
                origins = {'cron': 0, 'subagent': 0}
                for kind, origin, count in opens:
                    metric = {'turn': 'turns_running', 'subagent': 'subagents_running'}.get(kind)
                    if kind in ('waiting:approval', 'waiting:clarify', 'waiting:sudo'):
                        metric = 'waiting_on_you'
                    if metric:
                        counts[metric] += count
                    if kind == 'turn' and origin in origins:
                        origins[origin] += count
                rows = db.execute('''SELECT kind,status,ts FROM hermes_events WHERE ts>? AND ts<=?''', (now - 3600, now))
                unknown_tool_status = False
                for kind, status, ts in rows:
                    if kind == 'tool':
                        if ts > now - 600:
                            counts['tool_calls_10m'] += 1
                        if status in ('error', 'timeout'):
                            counts['tool_errors_1h'] += 1
                        if status == 'unknown':
                            unknown_tool_status = True
                    elif kind == 'provider_error':
                        counts['provider_errors_1h'] += 1
                values: dict[str, int | None] = dict(counts)
                reasons = {}
                # An incomplete observation window is not a measured zero.
                for metric, window in [('tool_calls_10m', 600), ('tool_errors_1h', 3600), ('provider_errors_1h', 3600)]:
                    if now - since < window:
                        values[metric] = None
                        reasons[metric] = 'Collecting the first complete observation window.'
                if unknown_tool_status:
                    values['tool_errors_1h'] = None
                    reasons['tool_errors_1h'] = 'Some tool completions did not report an outcome.'
                return SourceResult(sample={'ts': now, 'metrics': values, 'baselines': {}, 'unknown_reasons': reasons},
                    metadata={'observed_since': since, 'coverage': COVERAGE,
                              'cron_turns_running': origins['cron'], 'subagent_turns_running': origins['subagent']})
        except SourceError:
            raise
        except Exception:
            raise SourceError('Hermes activity counts are temporarily unavailable.') from None
