"""Recorded public GitHub data; all network boundaries are offline."""
import builtins
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from pulse_rings.engine import Engine
from pulse_rings.net import Net, _http_error
from pulse_rings.sources.base import SourceError
from pulse_rings.sources.github import GitHubRepo, GitHubSearch, pulls_count, search_url, _optional_token
ORIGINAL_TOKEN = _optional_token
from pulse_rings.spec import normalize
from pulse_rings.store import Store

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/github'
MANIFEST = json.loads((FIXTURES / 'manifest.json').read_text())
NOW = MANIFEST['now']


def record(name):
    return json.loads((FIXTURES / MANIFEST['files'][name]).read_text(encoding='utf-8'))


def definition(kind='search'):
    if kind == 'search':
        return normalize((ROOT / 'examples/b-github.pulse.yaml').read_text(encoding='utf-8'))
    return normalize({'pulse': 1, 'title': 'Hermes repo', 'source': {'kind': 'github.repo', 'params': {'repo': MANIFEST['repo']}}})


class FixtureNet:
    def __init__(self, *names):
        self.responses = [record(name) for name in names]
        self.calls = []

    def bytes(self, url, **kwargs):
        self.calls.append((url, kwargs))
        assert urlsplit(url).netloc == 'api.github.com'
        response = self.responses.pop(0)
        assert response['status'] == 200
        return json.dumps(response['body']).encode(), response['headers']


@pytest.fixture(autouse=True)
def no_secret(monkeypatch):
    # Avoid loading Hermes or reading any real credential during tests.
    monkeypatch.setattr('pulse_rings.sources.github._optional_token', lambda: None)


def test_recorded_search_and_six_hour_cache_survive_adapter_restart():
    net = FixtureNet('baseline', 'recent', 'recent', 'baseline')
    source, d = GitHubSearch(), definition()
    first = source.poll(d, None, {}, now=NOW, net=net)
    assert first.sample is None and first.next_due == NOW + 2
    second = source.poll(d, None, first.state, now=NOW + 2, net=net)
    assert second.sample['metrics']['recent'] == record('recent')['body']['total_count'] == 170
    expected = record('baseline')['body']['total_count'] / 14
    assert second.sample['metrics']['baseline'] == second.sample['baselines']['recent'] == expected
    assert first.state['baseline_due'] == NOW + 21600
    restarted = GitHubSearch().poll(d, second.sample, json.loads(json.dumps(second.state)), now=NOW + 21599, net=net)
    assert restarted.sample['baselines']['recent'] == expected
    expired = source.poll(d, restarted.sample, restarted.state, now=NOW + 21600, net=net)
    assert expired.sample is None
    assert len(net.calls) == 4 and not net.responses


def test_recorded_queries_have_exact_disjoint_datetime_windows():
    params = definition()['source']['params']
    for name, start, end in [('recent', NOW - 86400, NOW), ('baseline', NOW - 15 * 86400, NOW - 86400 - 1)]:
        url = search_url(params, start, end)
        assert url == record(name)['url']
        query = parse_qs(urlsplit(url).query)['q'][0]
        assert 'repo:NousResearch/hermes-agent is:pr catalog in:title created:' in query
        assert 'T' in query and 'Z..' in query


def test_week_baseline_is_scaled_to_week_not_day():
    d = definition()
    d['source']['params']['window'] = '7d'
    result = GitHubSearch().poll(d, None, {}, now=NOW, net=FixtureNet('baseline'))
    assert result.state['baseline'] == 794 / 14 * 7


def test_parameter_change_invalidates_baseline():
    d, source = definition(), GitHubSearch()
    first = source.poll(d, None, {}, now=NOW, net=FixtureNet('baseline'))
    d['source']['params']['title_contains'] = 'new catalog'
    changed = source.poll(d, None, first.state, now=NOW + 3, net=FixtureNet('baseline'))
    assert changed.state['query_key'] != first.state['query_key']
    assert changed.sample is None


@pytest.mark.parametrize('mutate', [lambda b: b.update(total_count=True), lambda b: b.update(total_count=-1),
    lambda b: b.update(total_count=float('inf')), lambda b: b.update(total_count=1.5),
    lambda b: b.update(incomplete_results=True), lambda b: b.pop('total_count'),
    lambda b: b.pop('incomplete_results')])
def test_bad_counts_never_become_zero(mutate):
    net = FixtureNet('baseline')
    mutate(net.responses[0]['body'])
    with pytest.raises(SourceError):
        GitHubSearch().poll(definition(), None, {}, now=NOW, net=net)


def test_repo_link_count_and_no_remote_avatar_following():
    d, source, net = definition('repo'), GitHubRepo(), FixtureNet('repo', 'pulls')
    first = source.poll(d, None, {}, now=NOW, net=net)
    second = source.poll(d, None, first.state, now=NOW + 2, net=net)
    repo = record('repo')['body']
    metrics = second.sample['metrics']
    assert metrics['stars'] == repo['stargazers_count']
    assert metrics['forks'] == repo['forks_count']
    assert metrics['open_issues'] == repo['open_issues_count']
    assert metrics['open_prs'] == pulls_count(record('pulls')['body'],
        {k.lower(): v for k, v in record('pulls')['headers'].items()}, MANIFEST['repo'], repo['id'])
    assert metrics['open_prs'] > 1
    assert len(net.calls) == 2
    assert second.state == {}


@pytest.mark.parametrize('body,headers,expected', [([], {}, 0), ([{}], {}, 1),
    ([{}], {'link': '<https://api.github.com/repos/a/b/pulls?state=open&per_page=1&page=1234>; rel="last"'}, 1234)])
def test_link_counts(body, headers, expected):
    assert pulls_count(body, headers, 'a/b') == expected


@pytest.mark.parametrize('url', ['https://evil.example/repos/a/b/pulls?state=open&per_page=1&page=4',
    'https://api.github.com/repos/a/b/pulls?state=open&per_page=100&page=4',
    'https://api.github.com/repos/a/c/pulls?state=open&per_page=1&page=4',
    'https://api.github.com/repos/a/b/pulls?state=open&per_page=1&page=-1'])
def test_untrusted_link_never_followed_or_counted(url):
    with pytest.raises(SourceError):
        pulls_count([{}], {'link': '<' + url + '>; rel="last"'}, 'a/b')


def test_next_without_last_is_unknown_not_zero():
    with pytest.raises(SourceError):
        pulls_count([{}], {'link': '<https://api.github.com/anything>; rel="next"'}, 'a/b')


@pytest.mark.parametrize('kind', ['search', 'repo'])
@pytest.mark.parametrize('error', [RuntimeError('PRIVATE_TOKEN'), ValueError('PRIVATE_TOKEN'), KeyError('PRIVATE_TOKEN')])
def test_unexpected_errors_are_sanitized_sourceerrors(kind, error):
    class Broken:
        def bytes(self, *args, **kwargs):
            raise error
    with pytest.raises(SourceError) as exc:
        (GitHubSearch() if kind == 'search' else GitHubRepo()).poll(definition(kind), None, {}, now=NOW, net=Broken())
    assert 'PRIVATE_TOKEN' not in str(exc.value)


def test_rate_limit_reset_with_injected_clock_and_durable_host_gate(tmp_path, monkeypatch):
    now = [NOW]
    store = Store(tmp_path)
    net = Net(store, clock=lambda: now[0])
    def limited(*args, **kwargs):
        raise _http_error(403, {'x-ratelimit-remaining': '0', 'x-ratelimit-reset': str(NOW + 1234)}, b'', now=now[0])
    monkeypatch.setattr('pulse_rings.net.fetch_bytes', limited)
    with pytest.raises(SourceError) as exc:
        GitHubSearch().poll(definition(), None, {}, now=now[0], net=net)
    assert exc.value.status == 403 and exc.value.retry_after == 1234
    assert Store(tmp_path).gate('host:api.github.com') == NOW + 1234


@pytest.mark.parametrize('status,delay,expected', [(403, 60, 60), (429, 10**12, 21600), (403, float('inf'), 600)])
def test_backoff_is_bounded_and_secondary_limits_preserved(status, delay, expected):
    class Limited:
        def bytes(self, *args, **kwargs):
            raise SourceError('private response', status=status, retry_after=delay)
    with pytest.raises(SourceError) as exc:
        GitHubSearch().poll(definition(), None, {}, now=NOW, net=Limited())
    assert exc.value.retry_after == expected
    assert 'private response' not in str(exc.value)


def test_token_only_from_lazy_secret_route_and_never_in_status_errors_logs(tmp_path, monkeypatch, caplog):
    sentinel = 'ghp_PRIVATE_SENTINEL_DO_NOT_PERSIST'
    original = builtins.__import__
    requested = []
    def fake_import(name, *args, **kwargs):
        if name == 'agent.secret_scope':
            return SimpleNamespace(get_secret=lambda key: requested.append(key) or sentinel)
        return original(name, *args, **kwargs)
    from pulse_rings.sources import github
    # Undo autouse replacement for this one boundary test.
    monkeypatch.setattr(github, '_optional_token', ORIGINAL_TOKEN)
    monkeypatch.setattr(builtins, '__import__', fake_import)
    net = FixtureNet('baseline', 'recent')
    adapter = GitHubSearch()
    engine = Engine(tmp_path, adapters={'github.search@1': adapter}, clock=lambda: NOW)
    d = definition()
    first = adapter.poll(d, None, {}, now=NOW, net=net)
    second = adapter.poll(d, None, first.state, now=NOW + 2, net=net)
    engine.activate(d, sample=second.sample)
    assert requested == ['PULSE_RINGS_GITHUB_TOKEN'] * 2
    assert all(kwargs['headers']['Authorization'] == 'Bearer ' + sentinel for _, kwargs in net.calls)
    status = engine.status(poll=False, include_icons=False)
    class Bad:
        def bytes(self, *args, **kwargs):
            raise SourceError('server echoed ' + sentinel, 403, 60)
    with pytest.raises(SourceError) as exc:
        adapter.poll(d, None, {}, now=NOW, net=Bad())
    outputs = json.dumps({'status': status, 'state': second.state, 'metadata': second.metadata, 'error': str(exc.value)}) + caplog.text
    assert sentinel not in outputs
    assert sentinel.encode() not in (tmp_path / 'pulse.sqlite3').read_bytes()


@pytest.mark.parametrize('kind', ['search', 'repo'])
def test_real_net_local_deferral_is_not_remote_failure(tmp_path, kind):
    now = 1_794_000_000.0
    engine = Engine(tmp_path, clock=lambda: now, jitter=lambda: 3)
    engine.activate(definition(kind))
    engine.store.extend_gate('host:api.github.com', now + 2)
    assert not engine.poll_one_due()
    row = engine.store.rows()[0]
    assert row['failures'] == 0
    assert row['backoff_until'] == 0
    assert row['error'] is None
    assert now + 2 < row['next_due'] < now + 8


@pytest.mark.parametrize('kind', ['search', 'repo'])
def test_real_net_preview_deferral_keeps_sampling(tmp_path, kind):
    now = 1_794_000_000.0
    engine = Engine(tmp_path, clock=lambda: now, jitter=lambda: 0)
    engine.store.extend_gate('host:api.github.com', now + 2)
    result = engine.create_draft(definition(kind), origin={'kind': 'session'})
    draft = engine.draft(result['draft_id'])
    assert draft['preview_calls'] == 0
    assert draft['preview_error'] is None
    assert draft['preview_state'] == 'sampling'


@pytest.mark.parametrize('bad', ['catalog OR secret:yes', 'catalog\nmalicious', 'catalog"', 'x' * 41])
def test_unstructured_query_injection_refused_before_egress(bad):
    d = definition()
    d['source']['params']['title_contains'] = bad
    net = FixtureNet('baseline')
    with pytest.raises(SourceError):
        GitHubSearch().poll(d, None, {}, now=NOW, net=net)
    assert net.calls == []


def test_numeric_repository_link_requires_matching_recorded_repo_id():
    headers = {k.lower(): v for k, v in record('pulls')['headers'].items()}
    with pytest.raises(SourceError):
        pulls_count(record('pulls')['body'], headers, MANIFEST['repo'], 999)
    assert pulls_count(record('pulls')['body'], headers, MANIFEST['repo'], record('repo')['body']['id']) == 34528


def test_actual_net_pacing_two_phase_poll_without_sleep(tmp_path, monkeypatch):
    clock = [NOW]
    net, fixture = Net(Store(tmp_path), clock=lambda: clock[0]), FixtureNet('baseline', 'recent')
    monkeypatch.setattr('pulse_rings.net.fetch_bytes', fixture.bytes)
    source = GitHubSearch()
    staged = source.poll(definition(), None, {}, now=clock[0], net=net)
    clock[0] = staged.next_due
    result = source.poll(definition(), None, staged.state, now=clock[0], net=net)
    assert result.sample['metrics']['recent'] == 170
    assert net.usage()['used'] == 2
