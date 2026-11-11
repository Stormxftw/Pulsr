"""WP9: real SQLite + engine, fake adapter boundary only; never live egress."""
import copy
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from pulse_rings.engine import Engine
from pulse_rings.spec import normalize, budget
from pulse_rings.sources.base import SourceResult, SourceError, Deferred
from pulse_rings.store import Store

FIX = Path(__file__).parent / 'fixtures'


def definition():
    return {'pulse': 1, 'id': 'live', 'title': 'Live feeds', 'icon': 'initials',
            'feeds': {
                'fast': {'kind': 'http_json', 'every': '5m', 'params': {'url': 'https://example.org/fast', 'metrics': {'count': '/count'}}},
                'slow': {'kind': 'http_json', 'every': '30m', 'params': {'url': 'https://example.net/slow', 'metrics': {'count': '/count'}}}},
            'display': [{'type': 'bar', 'value': 'fast.count', 'max': 100},
                        {'type': 'bar', 'value': 'slow.count', 'max': 100}],
            'theme': {'accent': '#123456'}, 'alert': {'metric': 'slow.count', 'above': 15}}


class Changing:
    def __init__(self):
        self.calls = []
        self.errors = {}

    def poll(self, d, previous, state, *, now, net):
        name = d['source']['params']['url'].rsplit('/', 1)[-1]
        self.calls.append((name, previous, copy.deepcopy(state), copy.deepcopy(d)))
        if name in self.errors:
            raise self.errors[name]
        n = state.get('n', 0) + 1
        return SourceResult(sample={'ts': now, 'metrics': {'count': n * 10}},
                            state={'n': n}, metadata={'name': name})


@pytest.fixture
def setup(tmp_path):
    now = [10000.0]
    fake = Changing()
    e = Engine(tmp_path, clock=lambda: now[0], jitter=lambda: 0, adapters={'http_json': fake})
    e.activate(definition())
    return e, fake, now


def test_upgrade_database_created_by_main_in_place(tmp_path):
    with closing(sqlite3.connect(tmp_path / 'pulse.sqlite3')) as db:
        db.executescript((FIX / 'wp9-main.sql').read_text())
    store = Store(tmp_path)
    with store.read() as db:
        assert 'feed' in {r[1] for r in db.execute('PRAGMA table_info(samples)')}
        sample = db.execute('SELECT * FROM samples').fetchone()
        assert sample['feed'] == 'main'
        assert json.loads(sample['payload'])['metrics']['online'] == 42
        main = db.execute('SELECT * FROM feeds').fetchone()
        assert main['feed'] == 'main' and main['last_ok_ts'] == 1000
        assert json.loads(main['source_state']) == {'invite_due': 1600}
        assert db.execute('SELECT count(*) FROM drafts').fetchone()[0] == 1
        assert db.execute('SELECT until_ts FROM gates WHERE key=?', ('remote:discord.com',)).fetchone()[0] == 1234
    Store(tmp_path)
    assert store.history('old')[0]['metrics']['online'] == 42
    with store.transaction() as db:
        for name in ('alpha', 'beta'):
            store.insert_sample(db, 'old', {'ts': 1000, 'metrics': {'count': 7}}, feed=name)
    assert len(store.history('old', feed='alpha')) == 1
    assert len(store.history('old', feed='beta')) == 1
    assert store.history('old')[0]['metrics']['online'] == 42


def test_mixed_cadences_one_claim_per_refresh_and_scoped_state(setup):
    e, fake, now = setup
    assert not e.status()['pulses'][0]['history']
    for t in (10000, 10000, 10300, 10600, 11800):
        now[0] = t
        before = len(fake.calls)
        row = e.status(poll=True)['pulses'][0]
        assert len(fake.calls) == before + 1
        assert row['display'] and len(row['feeds']) == 2
    assert [c[0] for c in fake.calls] == ['fast', 'slow', 'fast', 'fast', 'fast']
    assert fake.calls[2][1]['metrics']['count'] == 10
    assert fake.calls[2][1]['metadata'] == {'name': 'fast'}
    assert fake.calls[2][2] == {'n': 1}
    assert fake.calls[1][1] is None and fake.calls[1][2] == {}
    assert fake.calls[0][3]['every'] == '5m'
    assert fake.calls[1][3]['every'] == '30m'
    e.status(poll=True)
    assert fake.calls[-1][0] == 'slow'
    assert row['theme'] == {'accent': '#123456'}
    assert row['lines'] == [] and row['ring']['unknown']
    assert row['capsule']['label'] == 'Count 40'


def test_degraded_unknown_and_recovery_without_destroying_history(setup):
    e, fake, now = setup
    e.poll_one_due(); e.poll_one_due()
    fake.errors['fast'] = SourceError('Fast unavailable', 503, 5)
    now[0] += 300
    row = e.status(poll=True)['pulses'][0]
    assert row['state'] == 'degraded'
    a, b = [block['items'][0] for block in row['display']]
    assert a['unknown'] and a['reason'] == 'Fast unavailable' and a['fill'] is None
    assert b['value'] == 10 and b['fill'] == 10
    assert len(e.store.history('live', feed='fast')) == 1
    fake.errors['slow'] = SourceError('Slow unavailable', 503, 5)
    now[0] += 1800
    e.poll_one_due(); row = e.status(poll=True)['pulses'][0]
    assert row['state'] == 'error'
    fake.errors.clear()
    now[0] += 1800
    e.poll_one_due(); e.poll_one_due()
    assert e.status()['pulses'][0]['state'] == 'active'


def test_per_feed_backoff_deferral_and_404(setup):
    e, fake, now = setup
    fake.errors['fast'] = SourceError('Limited', 429, 900)
    e.poll_one_due()
    e.poll_one_due()  # unrelated host/feed remains available
    feeds = {f['name']: f for f in e.status()['pulses'][0]['feeds']}
    assert feeds['fast']['backoff_until'] == 10900
    assert feeds['slow']['state'] == 'active'
    fake.errors['fast'] = Deferred('Local pacing', 429, 10)
    now[0] = 10900
    e.poll_one_due()
    with e.store.read() as db:
        r = db.execute("SELECT * FROM feeds WHERE feed='fast'").fetchone()
        assert r['failures'] == 1 and r['next_due'] == 10910
    fake.errors['fast'] = SourceError('Gone', 404)
    now[0] = 10910
    e.poll_one_due()
    with e.store.read() as db:
        r = db.execute("SELECT * FROM feeds WHERE feed='fast'").fetchone()
        assert r['next_due'] == 10910 + 86400 and r['backoff_until'] == 0


def test_claims_single_most_due_feed_across_pulses_and_instances(setup):
    e, fake, now = setup
    d = definition(); d['id'] = 'another'; e.activate(d)
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: Store(e.root).claim_due(now[0]), range(8)))
    claims = [r for r in claims if r]
    assert len(claims) == 4
    assert len({(r['id'], r['feed']) for r in claims}) == 4
    assert e.store.claim_due(now[0]) is None


def test_live_sequence_fixed_fill_stat_spark_and_auto_learning(setup):
    e, fake, now = setup
    d = definition(); del d['feeds']['slow']; d.pop('alert')
    d['display'] = [{'type': 'bar', 'value': 'fast.count', 'max': 100},
                    {'type': 'bar', 'value': 'fast.count'},
                    {'type': 'stat', 'value': 'fast.count', 'delta_vs': 'previous'},
                    {'type': 'spark', 'value': 'fast.count'}]
    e.activate(d)
    rows = []
    for t in (10000, 11800, 13600, 15400):
        now[0] = t
        rows.append(e.status(poll=True)['pulses'][0])
    assert [r['display'][0]['items'][0]['value'] for r in rows] == [10, 20, 30, 40]
    assert [r['display'][0]['items'][0]['fill'] for r in rows] == [10, 20, 30, 40]
    assert [r['display'][1]['items'][0]['learning'] for r in rows] == [True, True, False, False]
    assert [r['display'][2]['delta'] for r in rows] == [None, 10, 10, 10]
    assert [len(r['display'][3]['points']) for r in rows] == [1, 2, 3, 4]
    assert [r['display'][1]['items'][0]['range']['samples'] for r in rows] == [1, 2, 3, 4]
    restarted = Engine(e.root, clock=e.clock, adapters={'http_json': fake})
    assert restarted.status()['pulses'][0]['display'] == rows[-1]['display']


def test_ref_alert_uses_named_feed(setup):
    e, fake, now = setup
    e.poll_one_due(); e.poll_one_due()
    now[0] += 1800
    e.poll_one_due()
    assert not e.status()['pulses'][0]['alert']['active']  # fast=20, slow=10
    row = e.status(poll=True)['pulses'][0]
    assert row['alert'] == {'active': True, 'reason': 'slow.count: 20', 'notify': 'none'}


def test_summed_budget_refused_at_activation_and_approval(tmp_path):
    e = Engine(tmp_path, clock=lambda: 1000, ceiling=13)
    assert budget(definition())['req_per_hour'] == 14
    with pytest.raises(ValueError, match='budget|ceiling'):
        e.activate(definition())
    id = e.create_draft(definition(), origin={'kind': 'cron'})['draft_id']
    with pytest.raises(ValueError, match='budget|ceiling'):
        e.decide_draft(id, 'approve')
    assert e.draft(id)['status'] == 'pending' and not e.store.rows()


@pytest.mark.parametrize('origin', ['session', 'cron', 'subagent', 'kanban', 'unattended'])
def test_mcp_http_feeds_never_preview(tmp_path, origin):
    d = definition()
    d['feeds']['slow'] = {'kind': 'mcp.tool', 'params': {'server': 'demo', 'tool': 'status', 'args': {}, 'metrics': {'count': '/count'}}}
    fake = Mock(side_effect=AssertionError('No preapproval calls'))
    e = Engine(tmp_path, clock=lambda: 10000, adapters={'http_json': fake, 'mcp.tool': fake})
    draft = e.create_draft(d, origin={'kind': origin})
    for _ in range(8): e.status(poll=True)
    fake.poll.assert_not_called()
    assert e.draft(draft['draft_id'])['preview_calls'] == 0
    assert not e.store.rows()


@pytest.mark.parametrize('origin', ['session', 'cron', 'subagent', 'kanban'])
def test_fixed_preview_rules_per_feed_and_approval(tmp_path, monkeypatch, origin):
    now = [10000]
    raw = json.loads((FIX / 'nousresearch.json').read_text())
    calls = []
    e = Engine(tmp_path, clock=lambda: now[0], fetch=lambda path: (calls.append(path), raw)[1], jitter=lambda: 0)
    monkeypatch.setattr('pulse_rings.sources.github._optional_token', lambda: None)
    monkeypatch.setattr('pulse_rings.events.broadcast', lambda *a, **k: None)
    d = definition(); d.pop('alert')
    for name in ('fast', 'slow'):
        d['feeds'][name] = {'kind': 'discord.invite', 'params': {'invite': name, 'voice': False}}
    d['display'] = [{'type': 'bar', 'value': 'fast.online', 'max': 100}, {'type': 'stat', 'value': 'slow.online'}]
    result = e.create_draft(d, origin={'kind': origin})
    for _ in range(8):
        now[0] += 3; e.status(poll=True)
    draft = e.draft(result['draft_id'])
    assert len(calls) == (2 if origin == 'session' else 0)
    assert draft['preview_calls'] == len(calls)
    if origin == 'session':
        assert len(draft['preview']['display']) == 2
        assert all(not b.get('unknown', False) for b in draft['preview']['display'])
        approved = e.decide_draft(result['draft_id'], 'approve')['row']
        assert approved['display'] == draft['preview']['display']
        assert len(e.store.history('live', feed='fast')) == 1
        assert len(e.store.history('live', feed='slow')) == 1
    else:
        assert draft['preview'] is None


def test_legacy_status_golden_byte_identical_except_additive_fields(tmp_path):
    cases = json.loads((FIX / 'wp9-status.golden').read_text())
    for i, case in enumerate(cases):
        e = Engine(tmp_path / str(i), clock=lambda: case['now'])
        e.activate(case['definition'])
        with e.store.transaction() as db:
            for sample in case['samples']: e.store.insert_sample(db, case['definition']['id'], sample)
            for key, value in case['updates'].items():
                db.execute(f'UPDATE pulses SET {key}=?', (value,))
        row = e.status()['pulses'][0]
        row['note_path'] = '<notes>'
        assert row['display'] is None and row['theme'] is None and row['feeds'][0]['name'] == 'main'
        for key in ('display', 'feeds', 'theme'): row.pop(key)
        # Refs #91: additive trend/voice read-model fields, covered by test_trend.py.
        row.pop('trend'); row.pop('voice', None)
        # Refs #107: the additive server card, covered by test_server_card.py.
        row.pop('server', None)
        for component in row['ring']['components']:
            # Refs #60/#58: these additive presentation/learning fields are
            # covered by live-polish tests; the old byte contract excludes them.
            component.pop('baseline_text')
            component.pop('warming')
        # Refs #61: the frozen fixture predates acronym-preserving labels.
        for line in case['expected']['lines']:
            if line.get('metric') == 'open_prs' and line.get('unknown'):
                line['label'] = 'Open PRs unknown'
        assert json.dumps(row, sort_keys=True) == json.dumps(case['expected'], sort_keys=True)


def test_feeds_cached_status_single_connection_no_validation(setup, monkeypatch):
    e, fake, now = setup
    e.poll_one_due(); e.poll_one_due()
    original = e.store.db
    opened = []
    def db(*a, **k): opened.append(1); return original(*a, **k)
    monkeypatch.setattr(e.store, 'db', db)
    monkeypatch.setattr('pulse_rings.spec.normalize', Mock(side_effect=AssertionError('No read validation')))
    monkeypatch.setattr('pulse_rings.spec.budget', Mock(side_effect=AssertionError('No read budget recompute')))
    row = e.status()['pulses'][0]
    assert len(opened) == 1 and row['display'][0]['items'][0]['value'] == 10


def test_feed_notes_definition_and_share_yaml(setup):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import dashboard.plugin_api as api
    e, fake, now = setup
    notes = e.root / 'notes'; notes.mkdir(); (notes / 'live.md').write_text('Local note')
    app = FastAPI(); app.include_router(api.router); app.dependency_overrides[api.get_pulse] = lambda: e
    with TestClient(app) as client:
        assert normalize(client.get('/pulses/live/definition').json()['yaml']) == normalize(definition())
        row = client.get('/status?poll=0').json()['pulses'][0]
        assert row['note'] == 'Local note' and row['note_path'].endswith('live.md')
    assert not fake.calls


@pytest.mark.parametrize('origin', ['session', 'cron', 'subagent', 'kanban'])
def test_github_previews_two_calls_per_feed_with_mixed_inert_feed(tmp_path, monkeypatch, origin):
    from pulse_rings.sources.github import GitHubSearch
    now = [10000]
    calls = []
    fixture = FIX / 'github'
    manifest = json.loads((fixture / 'manifest.json').read_text())
    responses = [json.loads((fixture / manifest['files'][name]).read_text()) for name in ('baseline', 'recent')]
    now[0] = manifest['now']
    # Both feeds perform baseline first, then recent, through the real adapter.
    def fetch(url, **kwargs):
        calls.append(url)
        response = responses[0 if len(calls) <= 2 else 1]
        return json.dumps(response['body']).encode(), response['headers']
    monkeypatch.setattr('pulse_rings.net.fetch_bytes', fetch)
    monkeypatch.setattr('pulse_rings.sources.github._optional_token', lambda: None)
    monkeypatch.setattr('pulse_rings.events.broadcast', lambda *a, **k: None)
    e = Engine(tmp_path, clock=lambda: now[0], jitter=lambda: 0)
    d = definition(); d.pop('alert')
    d['feeds'] = {'alpha': {'kind': 'github.search', 'params': {'repo': 'NousResearch/hermes-agent', 'type': 'pr'}},
                  'beta': {'kind': 'github.search', 'params': {'repo': 'NousResearch/hermes-agent', 'type': 'pr'}},
                  'inert': definition()['feeds']['fast']}
    d['display'] = [{'type': 'stat', 'value': 'alpha.recent'}, {'type': 'stat', 'value': 'beta.recent'}, {'type': 'stat', 'value': 'inert.count'}]
    result = e.create_draft(d, origin={'kind': origin})
    if origin == 'session':
        assert result['preview_calls'] == 1
        # Restart after first baseline to exercise persisted per-feed preview state.
        e = Engine(e.root, clock=lambda: now[0], jitter=lambda: 0)
    for _ in range(12):
        now[0] += 3
        before = len(calls)
        e.status(poll=True)
        assert len(calls) - before <= 1
    draft = e.draft(result['draft_id'])
    assert len(calls) == (4 if origin == 'session' else 0)
    if origin == 'session':
        assert draft['preview_calls'] == 4
        assert [f['preview_calls'] for f in draft['preview_feeds']] == [2, 2, 0]
        assert [b['unknown'] for b in draft['preview']['display']] == [False, False, True]
        assert not e.store.rows()
        approved = e.decide_draft(result['draft_id'], 'approve')['row']
        assert [b['value'] for b in approved['display']] == [b['value'] for b in draft['preview']['display']]


def test_jitter_budget_accounting_and_clean_deferral(setup):
    e, fake, now = setup
    e.jitter = lambda: 60
    original = fake.poll
    def poll(d, *a, **kw):
        host = 'example.org' if d['every'] == '5m' else 'example.net'
        kw['net'].call(host, lambda: None)
        return original(d, *a, **kw)
    fake.poll = poll
    e.poll_one_due(); e.poll_one_due()
    status = e.status()
    assert status['budget']['used'] == 2
    feeds = {f['name']: f for f in status['pulses'][0]['feeds']}
    assert feeds['fast']['next_due'] == 10330 and feeds['slow']['next_due'] == 11860
    e.net.ceiling = 2
    now[0] = 10330
    assert not e.poll_one_due()
    with e.store.read() as db:
        f = db.execute("SELECT * FROM feeds WHERE feed='fast'").fetchone()
        assert f['failures'] == 0 and f['error'] is None and f['backoff_until'] == 0
        assert f['next_due'] > now[0]
    assert len(fake.calls) == 2


def test_hero_icon_score_and_source_display_live(tmp_path):
    from pulse_rings.icon_resolver import HERMES
    now = [10000]
    class Local:
        def poll(self, d, previous, state, *, now, net):
            return SourceResult(sample={'ts': now, 'metrics': {'turns_running': 2}})
    e = Engine(tmp_path, clock=lambda: now[0], adapters={'hermes.activity': Local()}, jitter=lambda: 0)
    d = {'pulse': 1, 'title': 'Hero', 'id': 'hero', 'feeds': {
        'discord': {'kind': 'discord.invite', 'params': {'invite': 'nousresearch', 'voice': False}},
        'hero': {'kind': 'hermes.activity', 'params': {}}},
        'display': [{'type': 'score', 'components': [{'metric': 'hero.turns_running', 'type': 'level', 'weight': 100, 'full_at': 4}]}]}
    e.activate(d)
    # Poll only hero, avoiding any real Discord network.
    with e.store.transaction() as db: db.execute("UPDATE feeds SET next_due=999999 WHERE feed='discord'")
    row = e.status(poll=True)['pulses'][0]
    assert row['icon_resolved'] == HERMES
    assert row['ring']['score'] == row['display'][0]['ring']['score'] == 50
    assert row['kind'] == 'hermes.activity' and row['history'] == [{'ts': 10000, 'value': 2}]
    e.store.remove('hero')
    d = {'pulse': 1, 'id': 'single', 'title': 'Single', 'source': {'kind': 'hermes.activity'},
         'display': [{'type': 'bar', 'value': 'turns_running', 'max': 4}], 'alert': {'metric': 'turns_running', 'above': 1}}
    e.activate(d)
    row = e.status(poll=True)['pulses'][0]
    assert row['display'][0]['items'][0]['fill'] == 50
    assert row['alert']['active']


def test_seven_day_history_retention_and_query_bound(setup):
    e, fake, now = setup
    with e.store.transaction() as db:
        for name in ('fast', 'slow'):
            for ts in (-700000, 1, 2, 3):
                e.store.insert_sample(db, 'live', {'ts': ts, 'metrics': {'count': 1}}, feed=name)
    assert len(e.store.history('live', feed='fast', limit=2)) == 2
    e.poll_one_due()
    assert [s['ts'] for s in e.store.history('live', feed='slow')] == [1, 2, 3]
    assert e.store.history('live', feed='fast')[-1]['ts'] == now[0]


def test_feed_preview_lease_rejection_and_stale_preview_readback(tmp_path):
    from pulse_rings.feed_previews import records
    from pulse_rings.previews import PreviewNet
    now = 10000
    e = Engine(tmp_path, clock=lambda: now)
    d = definition(); d.pop('alert')
    d['feeds'] = {name: {'kind': 'discord.invite', 'params': {'invite': name, 'voice': False}} for name in ('fast', 'slow')}
    d['display'] = [{'type': 'stat', 'value': 'fast.online'}, {'type': 'stat', 'value': 'slow.online'}]
    id = e.propose(d, origin={'kind': 'session'}, preview_allowed=True, preview_feeds=['fast', 'slow'])
    first = e.store.claim_preview(now, id); second = e.store.claim_preview(now, id)
    assert first[2] != second[2] and e.store.claim_preview(now, id) is None
    for claim in (first, second):
        e.store.finish_preview(id, claim[1], feed=claim[2], sample={'ts': now, 'metrics': {'online': 12}},
                               preview={'stale': True})
    # Readback recomputes from aggregate samples, not the last finisher's stale snapshot.
    draft = e.draft(id)
    assert [b['value'] for b in draft['preview']['display']] == [12, 12]
    assert '_preview_feeds' not in draft
    e.decide_draft(id, 'reject')
    callback = Mock()
    with pytest.raises(ValueError, match='no longer'):
        PreviewNet(e, id, first[1], ['discord.com'], feed=first[2]).call('discord.com', callback)
    callback.assert_not_called()


def test_existing_ui_fixture_rows_keep_main_golden_hashes():
    import hashlib
    expected = json.loads((FIX / 'wp9-ui-hashes.golden').read_text())
    actual = {}
    for path in sorted((FIX / 'ui').glob('*.json')):
        fixture = json.loads(path.read_text(encoding='utf-8'))
        rows = [(path.name + '/' + row['id'], row) for row in fixture.get('pulses', [])]
        rows += [(path.name + '/draft/' + str(i), draft['preview'])
                 for i, draft in enumerate(fixture.get('drafts', [])) if draft.get('preview')]
        for key, row in rows:
            reduced = {k: v for k, v in row.items() if k not in ('display', 'feeds', 'theme')}
            actual[key] = hashlib.sha256(json.dumps(reduced, sort_keys=True).encode()).hexdigest()
    assert actual == expected


def test_direct_multi_preview_has_full_feed_budgets_and_display(setup):
    e, fake, now = setup
    d = normalize(definition())
    preview = e.preview(d, {'fast': {'ts': now[0], 'metrics': {'count': 5}}}, budget(d))
    assert [f['budget']['req_per_hour'] for f in preview['feeds']] == [12, 2]
    assert preview['display'][0]['items'][0]['value'] == 5
    assert preview['display'][1]['items'][0]['unknown']
    assert preview['history'] == [{'ts': now[0], 'value': 5}]


@pytest.mark.parametrize('payload', ['[]', 'null', '7', '{"pulse":2}'])
def test_upgrade_preserves_invalid_or_future_rows(tmp_path, payload):
    with closing(sqlite3.connect(tmp_path / 'pulse.sqlite3')) as db:
        db.executescript((FIX / 'wp9-main.sql').read_text())
        db.execute('UPDATE pulses SET definition=?', (payload,))
        db.commit()
    store = Store(tmp_path)
    assert store.rows()[0]['definition'] == payload
    assert len(store.history('old')) == 1
