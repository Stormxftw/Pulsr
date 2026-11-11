"""Boundary and control cases for Fable findings #69, #71 and #72. Offline only."""
import contextlib
from contextvars import copy_context
import io
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.error

import pytest

from pulse_rings import mcp_access
from pulse_rings.engine import Engine
from pulse_rings.net import Net, NetworkError, _http_error
from pulse_rings.sources.base import Deferred, SourceError, SourceResult
from pulse_rings.sources.github import GitHubRepo, STAGE_TTL
from pulse_rings.spec import normalize
from pulse_rings.store import Store

NOW = 1794000000
PRESET = json.loads((Path(__file__).parent / 'fixtures/normalized/discord-reference.json').read_text())
REPO = {'id': 123, 'stargazers_count': 3, 'forks_count': 2,
        'open_issues_count': 1, 'pushed_at': '2026-11-06T18:00:00Z', 'default_branch': 'main'}
QUOTA = {'x-ratelimit-remaining': '4999'}
PERMISSION = b'{"message":"Resource not accessible by integration"}'
ACTIONS_URL = 'https://api.github.com/repos/offline/repo0/actions/runs?per_page=1'


@pytest.fixture(autouse=True)
def no_secret(monkeypatch):
    monkeypatch.setattr('pulse_rings.sources.github._optional_token', lambda: None)


def repo(name, **params):
    return normalize({'pulse': 1, 'title': name, 'source': {'kind': 'github.repo',
        'params': {'repo': 'offline/' + name, **params}}, 'icon': 'initials'})


def transport(calls, denied=()):
    def fetch(url, **kwargs):
        calls.append(url)
        if '/actions/' in url:
            if any('/repos/offline/' + name + '/' in url for name in denied):
                raise _http_error(403, QUOTA, PERMISSION, now=kwargs.get('now'))
            body = {'workflow_runs': [{'status': 'completed', 'conclusion': 'success'}]}
        elif '/stats/' in url:
            body = {'all': list(range(1, 53))}
        else:
            body = [] if '/pulls?' in url else REPO
        return json.dumps(body).encode(), {'content-type': 'application/json'}
    return fetch


class FixtureNet:
    def __init__(self):
        self.calls = []
        self.fetch = transport(self.calls)

    def bytes(self, url, **kwargs):
        return self.fetch(url)


def viewed_ticks(engine, clock, count=40):
    for _ in range(count):
        engine.poll_one_due(previews=False)
        clock[0] += 15


def sample_counts(engine):
    return {row['id']: len(engine.store.history(row['id'], since=0)) for row in engine.store.rows()}


# --- #69 -------------------------------------------------------------------

def test_69_mixed_plain_ci_and_activity_repos_finish_once_each(tmp_path, monkeypatch):
    clock, calls = [NOW], []
    engine = Engine(tmp_path, clock=lambda: clock[0], jitter=lambda: 0)
    monkeypatch.setattr('pulse_rings.net.fetch_bytes', transport(calls))
    # Seven plain two-stage repositories alone outlast one snapshot when interleaved.
    for index in range(7):
        engine.activate(repo(f'plain{index}'))
    engine.activate(repo('checks', ci=True))
    engine.activate(repo('busy', activity=True, ci=True))
    viewed_ticks(engine, clock)
    counts = sample_counts(engine)
    assert len(counts) == 9 and set(counts.values()) == {1}, counts
    assert len(calls) == 7 * 2 + 3 + 4, 'No snapshot may be re-read'
    assert sum('/stats/participation' in url for url in calls) == 1
    assert engine.net.usage()['used'] == len(calls)


def test_69_other_source_kinds_keep_being_served(tmp_path, monkeypatch):
    clock, calls, local = [NOW], [], []

    class Local:
        def poll(self, definition, previous, state, *, now, net):
            local.append(now)
            return SourceResult(sample={'ts': now, 'metrics': {'turns_running': 1}})

    engine = Engine(tmp_path, clock=lambda: clock[0], jitter=lambda: 0, adapters={'hermes.activity': Local()})
    monkeypatch.setattr('pulse_rings.net.fetch_bytes', transport(calls))
    engine.activate({'pulse': 1, 'id': 'aa-local', 'title': 'Local', 'source': {'kind': 'hermes.activity'},
                     'display': [{'type': 'bar', 'value': 'turns_running', 'max': 4}]})
    for index in range(4):
        engine.activate(repo(f'ci{index}', ci=True))
    viewed_ticks(engine, clock)
    assert local and local[0] == NOW, 'Equally overdue feeds keep their id order'
    assert len(local) >= 2, 'A staged collection may delay, never starve, another source'
    counts = sample_counts(engine)
    assert all(counts[f'ci{index}'] == 1 for index in range(4)), counts
    assert len(calls) == 12


@pytest.mark.parametrize('params', [{}, {'ci': True}, {'activity': True, 'ci': True}])
def test_69_staged_hint_is_bounded_by_the_snapshot_lifetime(params):
    adapter, net, definition = GitHubRepo(), FixtureNet(), repo('edge', **params)
    assert adapter.staged(definition, {}, now=NOW) is False
    assert adapter.staged(definition, None, now=NOW) is False
    state = adapter.poll(definition, None, {}, now=NOW, net=net).state
    assert adapter.staged(definition, state, now=NOW + 2) is True
    assert adapter.staged(definition, state, now=NOW + STAGE_TTL) is True
    assert adapter.staged(definition, state, now=NOW + STAGE_TTL + 1) is False  # Expired: poll re-reads.
    assert adapter.staged(definition, state, now=NOW - 1) is False  # Clock moved back.
    assert adapter.staged(repo('other', **params), state, now=NOW + 2) is False
    result = None
    for step in range(1, 6):
        result = adapter.poll(definition, None, state, now=NOW + 2 * step, net=net)
        state = result.state
        if result.sample is not None:
            break
    assert result is not None and result.sample is not None
    assert adapter.staged(definition, state, now=NOW + 12) is False, 'A finished collection is not in progress'


def test_69_claim_hint_orders_only_due_feeds_and_fails_open(tmp_path):
    store = Store(tmp_path)
    for name in ('first', 'second', 'third'):
        store.put_pulse({**PRESET, 'id': name}, now=1000)

    def due():
        with store.transaction() as db:
            for name, value in (('first', 10), ('second', 20), ('third', 5000)):
                db.execute('UPDATE pulses SET next_due=? WHERE id=?', (value, name))
                db.execute('UPDATE feeds SET next_due=? WHERE pulse_id=?', (value, name))

    def broken(row):
        raise RuntimeError('hint failed')

    due()
    assert store.claim_due(1000)['id'] == 'first'  # Longest overdue first.
    due()
    assert store.claim_due(1000, in_progress=lambda row: row['id'] == 'second')['id'] == 'second'
    due()
    assert store.claim_due(1000, in_progress=lambda row: row['id'] == 'third')['id'] == 'first'  # Never early.
    due()
    assert store.claim_due(1000, in_progress=broken)['id'] == 'first'
    due()
    assert store.claim_due(1000, in_progress=lambda row: 1)['id'] == 'first'  # Only a literal True counts.


# --- #72 -------------------------------------------------------------------

def refuse(tmp_path, monkeypatch, status, headers, body):
    store = Store(tmp_path)
    net = Net(store, clock=lambda: NOW)

    def fetch(url, **kwargs):
        raise _http_error(status, headers, body, now=kwargs.get('now'))

    monkeypatch.setattr('pulse_rings.net.fetch_bytes', fetch)
    with pytest.raises(SourceError) as error:
        net.bytes(ACTIONS_URL)
    return store, error.value


@pytest.mark.parametrize('status,headers,body', [
    (403, {}, b''),
    (403, QUOTA, b''),
    (403, QUOTA, b'<html>Forbidden</html>'),
    (403, QUOTA, b'{"message":"Forbidden"}'),
    (403, QUOTA, b'["Resource not accessible by integration"]'),
    # A quota header that is present must prove quota remains: malformed, empty
    # and exhausted values are ambiguous, unlike an absent header (see below).
    (403, {'x-ratelimit-remaining': 'many'}, PERMISSION),
    (403, {'x-ratelimit-remaining': ''}, PERMISSION),
    (403, {'x-ratelimit-remaining': '-1'}, PERMISSION),
    (403, {'x-ratelimit-remaining': '0'}, PERMISSION),
    (403, {'x-ratelimit-remaining': '0', 'x-ratelimit-reset': str(NOW + 300)}, PERMISSION),
    (403, {**QUOTA, 'Retry-After': '60'}, PERMISSION),
    (403, QUOTA, b'{"message":"Resource not accessible by integration","retry_after":30}'),
    (403, QUOTA, b'{"message":"Resource not accessible by integration","documentation_url":"rate-limits-for-the-rest-api"}'),
    (403, QUOTA, b'{"message":"You have exceeded a secondary rate limit. Please wait."}'),
    (403, QUOTA, b'{"message":"API rate limit exceeded for this client."}'),
    (403, QUOTA, b'{"message":"You have triggered an abuse detection mechanism."}'),
    (429, QUOTA, PERMISSION),
    # Headerless controls: absent headers never turn limit evidence or an
    # unrecognized body into a permission refusal.
    (403, {}, b'<html>Forbidden</html>'),
    (403, {}, b'{"message":"Forbidden"}'),
    (403, {}, b'{"message":"You have exceeded a secondary rate limit. Please wait."}'),
    (403, {}, b'{"message":"API rate limit exceeded for this client."}'),
    (403, {}, b'{"message":"You have triggered an abuse detection mechanism."}'),
    (403, {'Retry-After': '60'}, PERMISSION),
    (403, {}, b'{"message":"Resource not accessible by integration","retry_after":30}'),
    (403, {}, b'{"message":"Resource not accessible by integration","documentation_url":"rate-limits-for-the-rest-api"}'),
    (403, {}, b'{"message":"Resource not accessible by integration","errors":[{"message":"secondary rate limit"}]}'),
    (429, {}, PERMISSION),
])
def test_72_ambiguous_or_limited_responses_keep_shared_backoff(tmp_path, monkeypatch, status, headers, body):
    store, error = refuse(tmp_path, monkeypatch, status, headers, body)
    assert error.permission_denied is False
    assert store.gate('remote:api.github.com') >= NOW + 2
    assert store.gate('host:api.github.com') == store.gate('remote:api.github.com')


@pytest.mark.parametrize('headers,body', [
    (QUOTA, b'{"message":"Resource not accessible by integration","documentation_url":"rest/actions/workflow-runs","status":"403"}'),
    ({'X-RateLimit-Remaining': '57'}, b'{"message":"Resource not accessible by personal access token"}'),
    (QUOTA, b'{"message":"Resource protected by organization SAML enforcement. You must grant your Personal Access token access to this organization."}'),
    # Issue #72's original reproduction: the recognized fixed message with no
    # headers at all. The message is the affirmative evidence; a missing quota
    # header is the absence of rate-limit evidence, not ambiguity. Only a header
    # that is present and malformed or exhausted vetoes it (controls above).
    ({}, PERMISSION),
    ({}, b'{"message":"Resource not accessible by personal access token"}'),
])
def test_72_affirmative_permission_refusal_is_not_a_host_limit(tmp_path, monkeypatch, headers, body):
    store, error = refuse(tmp_path, monkeypatch, 403, headers, body)
    assert error.status == 403 and error.permission_denied is True
    assert store.gate('remote:api.github.com') == 0
    assert store.gate('host:api.github.com') == NOW + 2, 'Only normal two-second pacing remains'
    assert 'Resource' not in str(error) and 'accessible' not in str(error), 'No upstream body text'


def test_72_unclassified_403_from_an_injected_transport_stays_conservative(tmp_path):
    store = Store(tmp_path)
    net = Net(store, clock=lambda: NOW)

    def refused():
        raise SourceError('rate limited', 403, 60)

    with pytest.raises(SourceError):
        net.call('api.github.com', refused)
    assert store.gate('remote:api.github.com') == NOW + 60


def test_72_real_transport_classifies_from_the_http_response(tmp_path, monkeypatch):
    import pulse_rings.net as mod
    clock, body = [NOW], [PERMISSION]

    class Opener:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(request.full_url, 403, 'Forbidden', dict(QUOTA), io.BytesIO(body[0]))

    monkeypatch.setattr(mod.urllib.request, 'build_opener', lambda *_: Opener())
    store = Store(tmp_path)
    net = Net(store, clock=lambda: clock[0])
    with pytest.raises(NetworkError) as error:
        net.json(ACTIONS_URL)
    assert error.value.status == 403
    assert store.gate('remote:api.github.com') == 0
    clock[0] += 2
    body[0] = b'{"message":"You have exceeded a secondary rate limit."}'
    with pytest.raises(NetworkError) as error:
        net.json(ACTIONS_URL)
    assert error.value.status == 403
    assert store.gate('remote:api.github.com') == clock[0] + 600


def test_72_denied_actions_on_one_repo_leaves_the_next_repo_collecting(tmp_path, monkeypatch):
    clock, calls = [NOW], []
    engine = Engine(tmp_path, clock=lambda: clock[0], jitter=lambda: 0)
    monkeypatch.setattr('pulse_rings.net.fetch_bytes', transport(calls, denied=('denied',)))
    engine.activate(repo('denied', ci=True))
    engine.activate(repo('healthy', ci=True))
    viewed_ticks(engine, clock, count=6)
    assert len(calls) == 6
    denied = engine.store.history('denied', since=0)[-1]
    assert denied['metrics']['stars'] == 3
    assert denied['metrics']['ci_passing'] is None, 'Unknown, never a failed build or zero'
    assert denied['unknown_reasons']['ci_passing'] == 'needs Actions read access'
    assert engine.store.history('healthy', since=0)[-1]['metrics']['ci_passing'] == 1
    assert engine.store.gate('remote:api.github.com') == 0
    for row in engine.status()['pulses']:
        assert row['state'] not in ('backoff', 'error') and row['error'] is None, row['id']


# --- #71 -------------------------------------------------------------------

@pytest.fixture
def waiting_mcp(tmp_path, monkeypatch):
    clock, granted, calls = [NOW], [False], []
    flags = {'exists': True, 'connected': True, 'read_only': True, 'requires_approval': False}
    ctx = SimpleNamespace(tool_info=lambda name: flags,
                          call_mcp=lambda *a, **kw: calls.append(a) or {'ok': True, 'result': {'count': 7}})
    engine = Engine(tmp_path, clock=lambda: clock[0], jitter=lambda: 0)
    monkeypatch.setitem(mcp_access._BINDINGS, str(tmp_path.resolve()), (ctx, copy_context(), str(tmp_path)))
    monkeypatch.setattr(mcp_access, 'server_granted', lambda server: granted[0])
    monkeypatch.setattr(mcp_access, 'unattended_scope', contextlib.nullcontext)
    engine.activate(normalize({'pulse': 1, 'title': 'MCP state', 'icon': 'initials', 'source': {'kind': 'mcp.tool',
        'params': {'server': 'probe', 'tool': 'read_metrics', 'args': {}, 'metrics': {'count': '/count'}}}}))
    engine.poll_one_due(previews=False)
    return SimpleNamespace(engine=engine, clock=clock, granted=granted, flags=flags, calls=calls)


def stored_states(engine):
    row = engine.store.rows()[0]
    return [json.loads(row['source_state'])] + [json.loads(feed['source_state'])
                                                for feed in engine.store.feed_rows(row['id']).values()]


def test_71_revoked_grant_waits_again_after_the_marker_was_cleared(waiting_mcp):
    engine = waiting_mcp.engine
    assert stored_states(engine) == [{'needs_mcp_grant': True}] * 2
    waiting_mcp.granted[0], waiting_mcp.flags['read_only'] = True, False
    waiting_mcp.clock[0] += 61
    engine.poll_one_due(previews=False)
    row = engine.store.rows()[0]
    assert stored_states(engine) == [{}, {}]
    assert 'not marked read-only' in row['error'] and row['failures'] == 1
    waiting_mcp.granted[0] = False
    waiting_mcp.clock[0] = row['next_due'] + 1
    engine.poll_one_due(previews=False)
    status = engine.status()['pulses'][0]
    assert status['state'] == 'needs_mcp_grant' and status['error'] is None
    assert 'Not yet allowed' in status['mcp']['grant_message']
    assert engine.store.rows()[0]['failures'] == 0
    assert waiting_mcp.calls == [], 'No call may dispatch without both grant and read-only policy'


def test_71_only_the_grant_marker_is_removed_from_stored_state():
    clear = Engine._without_stale_grant
    assert clear({'source_state': '{"cursor": 5, "needs_mcp_grant": true}'}) == {'source_state': '{"cursor": 5}'}
    for untouched in ('{"cursor": 5}', '{}', '[]', 'not json'):
        assert clear({'source_state': untouched}) == {}


@pytest.mark.parametrize('failure', [Deferred('Source is pacing requests.', 429, 5),
                                     SourceError('Source unavailable.', 500, 60)])
def test_71_unrelated_source_state_survives_deferrals_and_errors(tmp_path, failure):
    clock, failing = [1000], [False]

    class Flaky:
        def poll(self, definition, previous, state, *, now, net):
            if failing[0]:
                raise failure
            return SourceResult(sample={'ts': now, 'metrics': {'online': 100, 'members': 1000}},
                                state={'count': 1}, next_due=now + 600)

    engine = Engine(tmp_path, clock=lambda: clock[0], jitter=lambda: 0, adapters={'discord.invite@1': Flaky()})
    engine.activate(PRESET)
    assert engine.poll_one_due(previews=False)
    failing[0] = True
    clock[0] += 601
    assert not engine.poll_one_due(previews=False)
    feeds = engine.store.feed_rows(engine.store.rows()[0]['id']).values()
    assert [json.loads(feed['source_state']) for feed in feeds] == [{'count': 1}]
