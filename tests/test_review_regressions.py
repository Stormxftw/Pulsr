"""Opus W1–W6/B1–B8 regressions: corrected expectations, offline only."""
import copy
import http.client
import io
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pulse_rings.engine import Engine, compute_ring, compute_capsule, compute_lines
from pulse_rings.spec import normalize, budget, validate
from pulse_rings.net import retry_delay, Net, fetch_json
from pulse_rings.sources.base import SourceError

ROOT = Path(__file__).resolve().parents[1]
PRESET = normalize((ROOT / 'examples/a-discord.pulse.yaml').read_text(encoding='utf-8'))
RAW = json.loads((ROOT / 'tests/fixtures/nousresearch.json').read_text())


def rig(tmp_path, **kwargs):
    now = [1_000_000.0]
    return Engine(tmp_path, clock=lambda: now[0], jitter=lambda: 0,
                  icon_fetch=lambda *_: b'', **kwargs), now


def test_W1_B3_local_pacing_defers_without_failure(tmp_path):
    e, now = rig(tmp_path, fetch=lambda _: RAW)
    e.activate(PRESET)
    e.store.extend_gate('host:discord.com', now[0] + 2)
    e.status(poll=True)
    row = e.store.rows()[0]
    assert row['failures'] == 0 and row['backoff_until'] == 0 and row['error'] is None
    assert row['next_due'] == now[0] + 2
    assert e.status()['pulses'][0]['state'] != 'backoff'


@pytest.mark.parametrize('error', [http.client.IncompleteRead(b''), KeyError('secret'), RuntimeError('secret')])
def test_W2_poll_exception_never_500(tmp_path, error):
    import dashboard.plugin_api as api
    class Broken:
        def poll(self, *a, **kw):
            raise error
    e, _ = rig(tmp_path, adapters={'discord.invite@1': Broken()})
    e.activate(PRESET)
    app = FastAPI(); app.include_router(api.router)
    app.dependency_overrides[api.get_pulse] = lambda: e
    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.get('/status')
        assert response.status_code == 200
        item = response.json()['pulses'][0]
        assert item['state'] == 'error' and 'Internal error' in item['error']
        assert 'secret' not in response.text


def test_W3_bad_row_isolated_and_no_hot_path_validation(tmp_path, monkeypatch):
    e, _ = rig(tmp_path)
    e.activate(PRESET)
    e.activate({**PRESET, 'id': 'bad-row'})
    with e.store.transaction() as db:
        db.execute("UPDATE pulses SET definition=? WHERE id='bad-row'", ('{bad json',))
    monkeypatch.setattr('pulse_rings.spec.normalize', lambda *_: pytest.fail('hot path validation'))
    monkeypatch.setattr('pulse_rings.spec.budget', lambda *_: pytest.fail('hot path budget'))
    data = e.status(poll=True)
    assert len(data['pulses']) == 2
    assert next(p for p in data['pulses'] if p['id'] == 'bad-row')['state'] == 'error'


def test_W4_source_first_sample_and_preview():
    d = normalize((ROOT / 'examples/b-github.pulse.yaml').read_text())
    s = {'ts': 10, 'metrics': {'recent': 125}, 'baselines': {'recent': 50}}
    ring = compute_ring(d, s, [s])
    assert not ring['warming'] and ring['score'] == 100
    assert compute_capsule(d, s, ring)['caption'] == '2.5× usual'
    assert compute_ring(PRESET, {'ts': 10, 'metrics': {'online': 100, 'members': 1000}}, [])['score'] == 0


def test_W5_B6_unknown_and_plurals():
    s = {'ts': 10, 'metrics': {}}
    ring = compute_ring(PRESET, s, [{'ts': 1, 'metrics': {'online': 100, 'members': 1000}}])
    assert ring['unknown']
    assert [x['label'] for x in compute_lines(PRESET, s, ring)] == ['Members unknown', 'Voice channels unknown']
    s = {'ts': 10, 'metrics': {'members': 1001, 'voice_channels': 1}}
    ring = compute_ring(PRESET, s, [{'ts': 1, 'metrics': {'members': 1000}}])
    labels = [x['label'] for x in compute_lines(PRESET, s, ring)]
    assert labels == ['Net +1 member · 1 min', '1 active voice channel']


def test_W6_B5_retry_delay_bounded_and_reset_only_exhausted():
    h = {'x-ratelimit-reset': '1003000', 'x-ratelimit-remaining': '55'}
    assert retry_delay(422, h, now=1000000) == 600
    assert retry_delay(429, {'Retry-After': '1e12'}) == 21600
    assert retry_delay(404, {'Retry-After': '1e12'}) == 86400
    h['x-ratelimit-remaining'] = '0'
    assert retry_delay(403, h, now=1000000) == 3000


@pytest.mark.parametrize('error', [http.client.IncompleteRead(b''), http.client.BadStatusLine('x'), http.client.LineTooLong('x')])
def test_B4_transport_http_client_errors_are_sanitized(monkeypatch, error):
    class Reply(io.BytesIO):
        headers = {'Content-Type': 'application/json'}
        def read(self, *_):
            raise error
    class Opener:
        def open(self, *a, **kw):
            return Reply()
    monkeypatch.setattr('pulse_rings.net.urllib.request.build_opener', lambda *_: Opener())
    with pytest.raises(SourceError, match='Could not reach'):
        fetch_json('https://discord.com/api/test')


def test_B8_versioned_widget_allowed(monkeypatch):
    from pulse_rings.sources import discord
    monkeypatch.setattr(discord, 'fetch_json', lambda url: {'url': url})
    assert '/api/v10/guilds/' in discord.discord_get('/api/v10/guilds/1053877538025386074/widget.json')['url']
    with pytest.raises(ValueError):
        discord.discord_get('/api/guilds/1053877538025386074/widget.json')


def test_budget_admission_and_ports(tmp_path):
    from pulse_rings.spec import admission
    assert budget(normalize((ROOT / 'examples/b-github.pulse.yaml').read_text()))['req_per_hour_display'] == 5
    assert admission([{'req_per_hour': 290}], {'req_per_hour': 11}, 300)
    assert not admission([{'req_per_hour': 290}], {'req_per_hour': 10}, 300)
    d = {'pulse': 1, 'title': 'bad port', 'source': {'kind': 'http_json', 'params': {'url': 'https://example.com:444/x', 'metrics': {'n': '/n'}}}}
    assert validate(d)
    e, _ = rig(tmp_path)
    e.net.ceiling = 10
    e.activate(PRESET)
    with pytest.raises(ValueError, match='budget'):
        e.activate({**PRESET, 'id': 'over-budget'})


def test_cache_readback_route_does_not_poll(tmp_path):
    import dashboard.plugin_api as api
    class Broken:
        def poll(self, *a, **kw):
            pytest.fail('cache read polled')
    e, _ = rig(tmp_path, adapters={'discord.invite@1': Broken()})
    e.activate(PRESET)
    app = FastAPI(); app.include_router(api.router)
    app.dependency_overrides[api.get_pulse] = lambda: e
    with TestClient(app) as c:
        assert c.get('/status?poll=0').status_code == 200


def _race_worker(path, ready, queue):
    from pulse_rings.engine import Engine
    from pulse_rings.sources.base import SourceResult
    class Poll:
        def poll(self, definition, previous, state, *, now, net):
            net.call('discord.com', lambda: None)
            return SourceResult(sample={'ts': now, 'metrics': {'online': 100, 'members': 1000}}, next_due=now+600)
    e = Engine(path, clock=lambda: 1000, jitter=lambda: 0, adapters={'discord.invite@1': Poll()})
    ready.wait(15)
    queue.put(e.poll_one_due())


def test_two_process_engines_race_claims_and_gate(tmp_path):
    import multiprocessing
    e = Engine(tmp_path, clock=lambda: 1000, jitter=lambda: 0)
    e.activate({**PRESET, 'id': 'race-first'})
    e.activate({**PRESET, 'id': 'race-second'})
    context = multiprocessing.get_context('spawn')
    ready = context.Event(); queue = context.Queue()
    workers = [context.Process(target=_race_worker, args=(str(tmp_path), ready, queue)) for _ in range(2)]
    try:
        for worker in workers: worker.start()
        ready.set()
        results = [queue.get(timeout=30) for _ in workers]
        for worker in workers:
            worker.join(30)
            assert worker.exitcode == 0
        assert sorted(results) == [False, True]
        assert e.net.usage()['used'] == 1
        assert all(row['failures'] == 0 and row['error'] is None for row in e.store.rows())
        assert sorted(row['next_due'] for row in e.store.rows()) == [1002,1600]
    finally:
        for worker in workers:
            if worker.is_alive(): worker.terminate(); worker.join(10)
        queue.close()


def test_retry_reset_uses_injected_clock(tmp_path, monkeypatch):
    import urllib.error
    class Opener:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(request.full_url,403,'limited',
                {'X-RateLimit-Reset':'1300','X-RateLimit-Remaining':'0'},io.BytesIO(b'{}'))
    monkeypatch.setattr('pulse_rings.net.urllib.request.build_opener',lambda *_:Opener())
    e = Engine(tmp_path, clock=lambda: 1000)
    with pytest.raises(SourceError) as exc:
        e.net.json('https://api.github.com/search/issues')
    assert exc.value.retry_after == 300
    assert e.store.gate('host:api.github.com') == 1300


def test_budget_denial_transaction_preserves_previous_allocation(tmp_path):
    e, _ = rig(tmp_path)
    e.net.ceiling = 10
    e.activate(PRESET)
    with pytest.raises(ValueError, match='budget'):
        e.activate({**PRESET, 'id': 'cannot-fit'})
    assert len(e.status()['pulses']) == 1
    e.activate({**PRESET, 'title': 'Same budget replacement'})
    assert e.status()['budget']['remaining_req_per_hour'] == 0


def test_B7_legacy_weights_are_intentionally_not_renormalized():
    # Carry-over #9 is outside the frozen numeric equivalence task: characterize
    # rather than silently change the approved movement standard.
    prior = [{'ts': 100, 'online': 1000, 'members': 10000}]
    same = {'ts': 700, 'online': 1000, 'members': 10000}
    assert compute_ring(PRESET, {**same,'voice_channels':5}, prior)['score'] == 10
    assert compute_ring(PRESET, same, prior)['score'] == 0


def test_ceiling_is_invisible_deferral(tmp_path):
    e, now = rig(tmp_path, fetch=lambda _: RAW)
    e.activate(PRESET)
    e.net.ceiling = 1
    e.net.call('other.example',lambda:None)
    e.poll_one_due()
    row = e.store.rows()[0]
    assert row['next_due'] == now[0]+3600
    assert row['failures'] == 0 and row['error'] is None and row['backoff_until'] == 0
    assert e.status()['pulses'][0]['state'] != 'backoff'


def test_nonfinite_or_corrupt_sample_is_one_error_row_not_route_failure(tmp_path):
    e, _ = rig(tmp_path)
    e.activate(PRESET)
    e.activate({**PRESET,'id':'valid-other'})
    with e.store.transaction() as db:
        db.execute('INSERT INTO samples(pulse_id,ts,payload,generation) VALUES (?,?,?,(SELECT generation FROM feeds WHERE pulse_id=? AND feed=\'main\'))',
                   (PRESET['id'],1000000,'{"ts":NaN,"metrics":{}}',PRESET['id']))
    data = e.status()
    assert len(data['pulses']) == 2
    assert next(p for p in data['pulses'] if p['id']==PRESET['id'])['state'] == 'error'
    json.dumps(data,allow_nan=False)


def test_old_schema_budget_migration_keeps_invalid_row_visible(tmp_path):
    import sqlite3
    from pulse_rings.store import Store
    e, _ = rig(tmp_path)
    e.activate(PRESET)
    # Recreate the pre-budget schema shape using SQLite's supported DROP COLUMN.
    with e.store.transaction() as db:
        db.execute('ALTER TABLE pulses DROP COLUMN budget')
        db.execute('ALTER TABLE drafts DROP COLUMN budget')
    migrated = Store(tmp_path)
    assert json.loads(migrated.rows()[0]['budget'])['req_per_hour'] == 10
    assert json.loads(migrated.rows()[0]['definition'])['source']['kind'] == 'discord.invite'
    with migrated.transaction() as db:
        db.execute('UPDATE pulses SET definition=?',('not json',))
    assert Engine(tmp_path).status()['pulses'][0]['state'] == 'error'


def test_corrupt_draft_does_not_break_valid_pulses(tmp_path):
    e, _ = rig(tmp_path)
    e.activate(PRESET)
    with e.store.transaction() as db:
        db.execute('INSERT INTO drafts(id,definition,created_ts,expires_ts,preview) VALUES (?,?,?,?,?)',
                   ('pd_0123456789',json.dumps(PRESET),1,2000000,'{"ring":{"score":NaN}}'))
    data = e.status()
    assert data['drafts'][0]['status'] == 'expired'
    assert len(data['pulses']) == 1
    json.dumps(data,allow_nan=False)


def test_corrupt_row_envelopes_and_legacy_metadata_still_serializable(tmp_path):
    e, _ = rig(tmp_path)
    e.activate(PRESET, sample={'ts':1000000,'metrics':{'online':1,'members':1}})
    with e.store.transaction() as db:
        db.execute('UPDATE pulses SET metadata=?,backoff_until=?',('{"name":4,"arbitrary":NaN}',float('inf')))
    data = e.status()
    assert data['pulses'][0]['state'] == 'error'
    assert data['budget']['active_req_per_hour'] == 10
    assert data['budget']['remaining_req_per_hour'] == 290
    json.dumps(data,allow_nan=False)
