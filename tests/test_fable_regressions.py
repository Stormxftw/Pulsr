"""Acceptance regressions for Fable findings #69, #71 and #72. Offline only."""
from contextvars import copy_context
import json
from types import SimpleNamespace

import pytest

from pulse_rings import mcp_access
from pulse_rings.engine import Engine
from pulse_rings.net import _http_error
from pulse_rings.sources import mcp
from pulse_rings.sources.base import Deferred
from pulse_rings.sources.github import GitHubRepo
from pulse_rings.spec import normalize

NOW = 1794000000
REPO = {'id': 123, 'stargazers_count': 3, 'forks_count': 2,
        'open_issues_count': 1, 'pushed_at': '2026-11-06T18:00:00Z', 'default_branch': 'main'}


def repo_definition(index=0):
    return normalize({'pulse': 1, 'title': f'Repo {index}',
        'source': {'kind': 'github.repo', 'params': {'repo': f'offline/repo{index}', 'ci': True}},
        'icon': 'initials'})


def fake_transport(calls, denied=False, rate_limited=False):
    def fetch(url, **kwargs):
        calls.append(url)
        if '/actions/' in url:
            if denied:
                headers = {'Retry-After': '60'} if rate_limited else {'x-ratelimit-remaining': '4999'}
                body = b'{"message":"You have exceeded a secondary rate limit"}' if rate_limited else b'{"message":"Resource not accessible by integration"}'
                raise _http_error(403, headers, body, now=kwargs.get('now'))
            body = {'workflow_runs': [{'status': 'completed', 'conclusion': 'success'}]}
        else:
            body = [] if '/pulls?' in url else REPO
        return json.dumps(body).encode(), {'content-type': 'application/json'}
    return fetch


@pytest.mark.parametrize('count', [3, 4, 8])
def test_69_due_ci_repos_complete_with_viewed_cadence(tmp_path, monkeypatch, count):
    clock, calls = [NOW], []
    engine = Engine(tmp_path, clock=lambda: clock[0], jitter=lambda: 0)
    monkeypatch.setattr('pulse_rings.sources.github._optional_token', lambda: None)
    monkeypatch.setattr('pulse_rings.net.fetch_bytes', fake_transport(calls))
    for i in range(count):
        engine.activate(repo_definition(i))
    for _ in range(40):
        engine.poll_one_due(previews=False)
        clock[0] += 15
    samples = {row['id']: engine.store.history(row['id'], since=0) for row in engine.store.rows()}
    assert all(samples.values()), f'Due staged feeds never completed: { {k: len(v) for k, v in samples.items()} }; calls={len(calls)}'
    assert len(calls) == 3 * count, 'A completed collection must not repeatedly spend its approval budget restarting'


@pytest.mark.parametrize('rate_limited', [False, True])
def test_72_optional_actions_permission_does_not_gate_other_repos(tmp_path, monkeypatch, rate_limited):
    clock, calls = [NOW], []
    engine = Engine(tmp_path, clock=lambda: clock[0], jitter=lambda: 0)
    monkeypatch.setattr('pulse_rings.sources.github._optional_token', lambda: None)
    monkeypatch.setattr('pulse_rings.net.fetch_bytes', fake_transport(calls, denied=True, rate_limited=rate_limited))
    adapter, definition, state = GitHubRepo(), repo_definition(), {}
    result = None
    for _ in range(3):
        result = adapter.poll(definition, None, state, now=clock[0], net=engine.net)
        state = result.state
        if result.sample is not None:
            break
        clock[0] += 2
    assert result is not None
    assert result.sample is not None
    assert result.sample['metrics']['ci_passing'] is None
    gate = engine.store.gate('remote:api.github.com')
    if rate_limited:
        assert gate >= clock[0] + 60, 'Genuine rate limits must retain shared backoff'
        with pytest.raises(Deferred):
            engine.net.reserve('api.github.com')
    else:
        assert gate <= clock[0], 'A permission-only Actions 403 must not set shared remote backoff'
        clock[0] += 2  # Normal two-second host pacing still applies.
        engine.net.reserve('api.github.com')


@pytest.mark.parametrize('explicit_feeds', [False, True])
@pytest.mark.parametrize('failure', ['policy', 'busy'])
def test_71_granted_mcp_clears_stale_missing_grant(tmp_path, monkeypatch, explicit_feeds, failure):
    clock, granted, calls = [NOW], [False], []
    flags = {'exists': True, 'connected': True, 'read_only': True, 'requires_approval': False}
    ctx = SimpleNamespace(tool_info=lambda name: flags, call_mcp=lambda *a, **kw: calls.append(a) or {'ok': True, 'result': {'count': 7}})
    engine = Engine(tmp_path, clock=lambda: clock[0], jitter=lambda: 0)
    monkeypatch.setitem(mcp_access._BINDINGS, str(tmp_path.resolve()), (ctx, copy_context(), str(tmp_path)))
    monkeypatch.setattr(mcp_access, 'server_granted', lambda server: granted[0])
    source = {'kind': 'mcp.tool', 'params': {'server': 'probe', 'tool': 'read_metrics', 'args': {}, 'metrics': {'count': '/count'}}}
    raw = {'pulse': 1, 'title': 'MCP state', 'icon': 'initials'}
    if explicit_feeds:
        raw.update(feeds={'main': source}, display=[{'type': 'stat', 'value': 'main.count'}])
    else:
        raw['source'] = source
    engine.activate(normalize(raw))
    engine.poll_one_due(previews=False)
    assert engine.status()['pulses'][0]['state'] == 'needs_mcp_grant'
    granted[0] = True
    if failure == 'policy':
        flags['read_only'] = False
    else:
        monkeypatch.setattr(mcp, '_SLOTS', SimpleNamespace(acquire=lambda **kw: False, release=lambda: None))
    clock[0] += 61
    engine.poll_one_due(previews=False)
    row = engine.status()['pulses'][0]
    status = row['feeds'][0] if explicit_feeds else row
    assert status['mcp']['hermes_allowed'] is True
    assert row['state'] != 'needs_mcp_grant', 'Fresh permission must not be masked by stale source state'
    assert 'Not yet allowed' not in status['mcp']['grant_message']
    if failure == 'policy':
        assert 'not marked read-only' in status['error']
    assert calls == [], 'Refused or busy calls must never dispatch'
