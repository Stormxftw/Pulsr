"""Generate UI read models through Engine.status, never hand-edit measurements.

Discord hero series is the committed counts-only real export. Pending GitHub
previews replay recorded API bodies; other GitHub/Hermes and edge-state inputs
are explicitly synthetic conformance/fault scenarios. No network.
Run with the same isolated test dependencies; --output allows reproducibility tests.
"""
import argparse
import copy
import json
import os
import sqlite3
from contextlib import closing
from contextvars import copy_context
from pathlib import Path
import sys
import tempfile
import uuid
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pulse_rings.engine import Engine
from pulse_rings.migrate import DiscordPulseImporter
from pulse_rings.sources.base import SourceResult
from pulse_rings.sources.github import GitHubSearch
from pulse_rings.sources.discord import normalize_invite
from pulse_rings.spec import normalize

REAL = json.loads((ROOT / 'tests/fixtures/golden/live-discord-series.json').read_text())
NOW = max(s['ts'] for s in REAL) + 60


class Offline:
    def poll(self, *args, **kwargs):
        raise AssertionError('Fixture generator must never poll')


def definition(kind, pulse_id, title, params=None, **kwargs):
    return normalize({'pulse': 1, 'id': pulse_id, 'title': title,
                      'source': {'kind': kind, 'params': params or {}}, **kwargs})


def github():
    return definition('github.search', 'catalog-prs', 'hermes-agent · catalog PRs',
                      {'repo': 'NousResearch/hermes-agent', 'type': 'pr', 'title_contains': 'catalog'},
                      alert={'ring_at_least': 70})


def gh_sample(ts=NOW-60, count=125):
    return {'ts': ts, 'metrics': {'recent': count, 'baseline': 50}, 'baselines': {'recent': 50}}


def generate(output, scratch=None):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    results = {}
    for mode in ('hero', 'states', 'pending', 'approval', 'arbitrary-host', 'mcp', 'sampling', 'twelve', 'empty', 'migration', 'old-backend'):
        with tempfile.TemporaryDirectory(prefix='pulse-fixture-', dir=scratch) as data:
            e = Engine(data, clock=lambda: NOW, jitter=lambda: 0,
                       adapters={k: Offline() for k in ('github.search', 'hermes.activity')})

            fixture_binding = {}

            def seed(d, samples, *, metadata=None, **state):
                e.activate(d)
                with e.store.transaction() as db:
                    for sample in samples:
                        e.store.insert_sample(db, d['id'], sample)
                    db.execute('UPDATE pulses SET last_ok_ts=?,metadata=?,next_due=? WHERE id=?',
                               (samples[-1]['ts'] if samples else None, json.dumps(metadata or {}), NOW + 600, d['id']))
                    for k, v in state.items():
                        assert k in ('error', 'backoff_until', 'paused', 'source_state')
                        db.execute(f'UPDATE pulses SET {k}=? WHERE id=?', (v, d['id']))

            def discord(code, pulse_id, title=None):
                raw = json.loads((ROOT / f'tests/fixtures/{code}.json').read_text())
                metadata = normalize_invite(raw)
                d = definition('discord.invite', pulse_id, title or metadata['name'], {'invite': code})
                series = [{'ts': s['ts'], 'metrics': {'online': s['online'], 'members': s['members']}}
                          for s in REAL if s['guild'] == metadata['id']]
                if not series:
                    series = [{'ts': NOW-60, 'metrics': {k: metadata[k] for k in ('online', 'members')}}]
                seed(d, series, metadata=metadata)

            def proposal(http=False):
                if http:
                    d = definition('http_json', 'public-count', 'Public count',
                        {'url': 'https://api.example.org/v1/count?region=world', 'metrics': {'count': '/count'}})
                else:
                    d = github()
                hexid = 'abcdef0123' if http else '0123456789'
                if http:
                    with patch('pulse_rings.store.uuid.uuid4', return_value=SimpleNamespace(hex=hexid)):
                        e.propose(d, origin={'kind': 'cron', 'name': 'morning-scout'})
                    return
                # Exercise the real draft/poller path against recorded baseline +
                # recent response bodies. No synthetic GitHub draft measurement.
                manifest = json.loads((ROOT / 'tests/fixtures/github/manifest.json').read_text())
                responses = [json.loads((ROOT / 'tests/fixtures/github' / manifest['files'][name]).read_text())
                             for name in ('baseline', 'recent')]
                clock = [manifest['now']]
                def fetch(url, **kwargs):
                    response = responses.pop(0)
                    return json.dumps(response['body']).encode(), response['headers']
                original_uuid = uuid.uuid4
                ids = [SimpleNamespace(hex=hexid)]
                def next_id():
                    return ids.pop() if ids else original_uuid()
                e.adapters['github.search'] = GitHubSearch()
                with patch.object(e, 'clock', lambda: clock[0]), \
                     patch('pulse_rings.store.uuid.uuid4', side_effect=next_id), \
                     patch('pulse_rings.net.fetch_bytes', side_effect=fetch), \
                     patch('pulse_rings.sources.github._optional_token', return_value=None), \
                     patch('pulse_rings.events.broadcast'):
                    e.create_draft(d, origin={'kind': 'session', 'name': 'Hermes'})
                    if mode != 'sampling':
                        clock[0] += 2
                        e.poll_one_due()

            if mode in ('hero', 'old-backend'):
                discord('nousresearch', 'nous-discord')
                discord('typesafe', 'typescript')
                discord('6EbMcWJHdb', 'hugging-face')
                seed(github(), [gh_sample(NOW-3600, 50), gh_sample(NOW-1800, 75), gh_sample()])
                h = definition('hermes.activity', 'hermes-self', 'Hermes · this profile', alert={'metric': 'waiting_on_you', 'above': 0})
                seed(h, [{'ts': NOW-600, 'metrics': {'turns_running': 1, 'tool_calls_10m': 26}},
                         {'ts': NOW-10, 'metrics': {'turns_running': 2, 'tool_calls_10m': 48,
                          'tool_errors_1h': 0, 'waiting_on_you': 1, 'subagents_running': 1}}])
            elif mode in ('pending', 'approval', 'sampling'):
                discord('nousresearch', 'nous-discord')
                if mode == 'pending': discord('6EbMcWJHdb', 'hugging-face')
                proposal()
            elif mode == 'arbitrary-host':
                proposal(http=True)
            elif mode == 'mcp':
                # Synthetic host metadata via the public policy seam; no dispatch.
                from pulse_rings import mcp_access
                params = {'server': 'probe', 'tool': 'read_metrics',
                          'args': {'filter': '<img src=x onerror="window.MCP_XSS=1">', 'padding': 'z' * 650},
                          'metrics': {'count': '/count'}, 'x-read-only': True}
                d = definition('mcp.tool', 'mcp-queue', 'MCP queue', params,
                               ring={'components': [{'metric': 'count', 'weight': 100, 'type': 'level', 'full_at': 100}]})
                ctx = SimpleNamespace(tool_info=lambda name: {
                    'exists': True, 'connected': True, 'read_only': True, 'requires_approval': False})
                fixture_binding[str(Path(data).resolve())] = (ctx, copy_context(), 'synthetic')
                seed(d, [{'ts': NOW-60, 'metrics': {'count': 45}}])
                with patch('pulse_rings.store.uuid.uuid4', return_value=SimpleNamespace(hex='0123456789')):
                    e.create_draft(dict(d, id='mcp-pending', title='MCP pending'), origin={'kind': 'session'})
            elif mode == 'states':
                # History-only definition lets this scenario exercise full warming.
                for id_, title in [('sampling','First sample'), ('learning','Learning baseline'),
                                  ('unknown','Unknown value'), ('zero','Measured zero'),
                                  ('stale','Stale signal'), ('error','Expired invite'),
                                  ('backoff','Rate limited'), ('paused','Paused by you')]:
                    d = definition('discord.invite', id_, title, {'invite': 'nousresearch'})
                    d['ring']['components'] = d['ring']['components'][:2]
                    d['ring']['components'][0]['weight'] = 80
                    samples = [{'ts': NOW-660, 'metrics': {'online': 100, 'members': 1000}},
                               {'ts': NOW-60, 'metrics': {'online': 110, 'members': 1001}}]
                    state = {}
                    if id_ == 'sampling': samples = []
                    if id_ == 'learning': samples = samples[-1:]
                    if id_ == 'unknown': samples[-1]['metrics'] = {'online': None, 'members': None}
                    if id_ == 'zero': samples[-1]['metrics']['online'] = 0
                    if id_ == 'stale':
                        for s in samples: s['ts'] -= 3600
                    if id_ == 'error': state['error'] = 'Invite expired. Replace it to resume polling.'
                    if id_ == 'backoff': state.update(error='Rate limited', backoff_until=NOW+240)
                    if id_ == 'paused': state['paused'] = 1
                    seed(d, samples, **state)
                seed(github(), [gh_sample()])
                e.activate({'pulse': 2, 'id': 'unsupported', 'title': 'Future definition'})
                proposal()
            elif mode == 'twelve':
                titles = ['Nous Research', 'Catalog PRs', 'Hermes · this profile', 'TypeSafe AI', 'Hugging Face',
                          'NVIDIA Developers', 'Open-source builders', 'Research collective', 'Model releases',
                          '🦙 Ollama', 'Agent maintainers', 'Very long title that must never overflow the row']
                for i, title in enumerate(titles):
                    discord(['nousresearch','typesafe','6EbMcWJHdb'][i%3], f'layout-{i}', title)
            # Explicit isolated profile for the importer; never probe live data.
            home = Path(data) / 'synthetic-home'
            if mode == 'migration':
                old = home / 'plugin-data/discord-pulse'
                old.mkdir(parents=True)
                with closing(sqlite3.connect(old / 'pulse.sqlite3')) as db, db:
                    db.executescript((ROOT / 'tests/fixtures/migrate/v030.sql').read_text())
                    for i, code in enumerate(('FakeAlpha', 'FakeBeta', 'FakeGamma')):
                        guild = str(100000000000000001 + i)
                        raw = json.dumps({'id': guild, 'name': 'Synthetic ' + str(i), 'online': 4+i, 'members': 100+i})
                        db.execute('INSERT INTO servers(id,code,payload) VALUES (?,?,?)', (guild, code, raw))
                        for step in range(i+1):
                            db.execute('INSERT INTO snapshots VALUES (?,?,?)', (guild, NOW-600+step, raw))
                (old / 'notes').mkdir()
                (old / 'notes/100000000000000001.md').write_text('# Synthetic import note', encoding='utf-8')
            importer = DiscordPulseImporter(e.store, hermes_home=home, clock=e.clock, ceiling=e.net.ceiling)
            from pulse_rings import mcp_access
            with patch('pulse_rings.engine.DiscordPulseImporter', return_value=importer), \
                 patch.dict(mcp_access._BINDINGS, fixture_binding), \
                 patch('pulse_rings.mcp_access.server_granted', return_value=True):
                result = e.status(poll=False)
            if mode == 'migration':
                result['import_plan'] = importer.plan()
            # Path redaction only; computed rows/budgets/measurements remain untouched.
            result['data_dir'] = '<fixture-data>'
            for p in result['pulses']:
                if p.get('note_path'): p['note_path'] = '<fixture-data>/notes/' + p['id'] + '.md'
            if mode == 'old-backend': result['api_version'] = '0.3.0'  # intentional fault fixture
            results[mode] = result
            (output / (mode+'.json')).write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / 'tests/fixtures/ui'))
    parser.add_argument('--scratch')
    args = parser.parse_args()
    generated = generate(args.output, args.scratch)
    print(f'Generated {len(generated)} engine status fixtures; Discord + pending GitHub recorded, other scenarios synthetic; no network.')
