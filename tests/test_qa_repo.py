"""github.repo QA: captured public responses plus explicit offline edge cases."""
import copy
import json
import math
from pathlib import Path

import pytest

from pulse_rings.display import compute_display
from pulse_rings.sources.base import SourceError
from pulse_rings.sources.github import GitHubRepo, pulls_count
from pulse_rings.spec import normalize

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = json.loads((ROOT / 'tests/fixtures/github/qa-repo-public.json').read_text())
PUBLIC = {row['path']: row for row in CAPTURE['records']}
NOW = 1794189600
REPO = {'id': 123, 'stargazers_count': 0, 'forks_count': 0, 'open_issues_count': 0,
        'pushed_at': None, 'default_branch': 'main', 'archived': True}


@pytest.fixture(autouse=True)
def no_secret(monkeypatch):
    monkeypatch.setattr('pulse_rings.sources.github._optional_token', lambda: None)


def definition(**params):
    return normalize({'pulse': 1, 'title': 'QA repo', 'source': {'kind': 'github.repo',
                      'params': {'repo': 'NousResearch/hermes-agent', **params}}})


class Net:
    def __init__(self, **responses):
        self.calls = []
        self.responses = {'repo': REPO, 'pulls': [], 'stats': {'all': [0] * 52},
                          'ci': {'total_count': 0, 'workflow_runs': []}, **responses}

    def bytes(self, url, **kwargs):
        self.calls.append(url)
        kind = 'stats' if '/stats/' in url else 'ci' if '/actions/' in url else 'pulls' if '/pulls?' in url else 'repo'
        value = self.responses[kind]
        if isinstance(value, Exception):
            raise value
        return (value if isinstance(value, bytes) else json.dumps(value).encode()), {'content-type': 'application/json'}


def collect(net, **params):
    source, state = GitHubRepo(), {}
    for step in range(8):
        result = source.poll(definition(**params), None, state, now=NOW + 2 * step, net=net)
        state = result.state
        if result.sample is not None:
            return result
    pytest.fail('staged collection did not complete')


@pytest.mark.parametrize('optional', ['stats', 'ci'])
@pytest.mark.parametrize('payload', [b'{bad json', b'', b'\xff', b'{"all":[NaN]}'])
def test_invalid_optional_json_preserves_repository_measurements(optional, payload):
    result = collect(Net(**{optional: payload}), activity=True, ci=True)
    assert result.sample['metrics']['stars'] == 0
    assert result.sample['metrics']['open_prs'] == 0
    unknown = 'commits_week' if optional == 'stats' else 'ci_passing'
    assert result.sample['metrics'][unknown] is None
    assert 'unavailable' in result.sample['unknown_reasons'][unknown].lower()


@pytest.mark.parametrize('body', [{}, {'workflow_runs': None}, {'workflow_runs': [None]},
                                  {'workflow_runs': 'invalid'}])
def test_malformed_ci_is_not_reported_as_no_runs(body):
    sample = collect(Net(ci=body), ci=True).sample
    assert sample['metrics']['ci_passing'] is None
    assert sample['metrics']['ci_running'] is None
    assert sample['unknown_reasons']['ci_passing'] == 'CI status unavailable'


@pytest.mark.parametrize('status', [301, 302, 307, 308])
def test_renamed_repo_has_actionable_safe_message(status):
    net = Net(repo=SourceError('private redirect target', status=status))
    with pytest.raises(SourceError) as error:
        collect(net)
    assert 'moved or was renamed' in str(error.value)
    assert 'approved repository' in str(error.value)
    assert 'private redirect target' not in str(error.value)
    assert len(net.calls) == 1


def test_private_or_missing_repo_not_misrepresented_as_public_only():
    with pytest.raises(SourceError) as error:
        collect(Net(repo=SourceError('private', status=404)))
    assert 'access' in str(error.value).lower()
    assert error.value.status == 404


@pytest.mark.parametrize('body', [[None], [1], ['bad'], []])
def test_bad_pull_payload_never_fabricates_count(body):
    headers = {'link': '<https://api.github.com/repos/a/b/pulls?state=open&per_page=1&page=4>; rel="last"'}
    with pytest.raises(SourceError):
        pulls_count(body, headers, 'a/b')


def test_zero_commits_empty_archived_repo_remain_measured_zero_not_unknown():
    result = collect(Net(), activity=True, ci=True)
    assert result.sample['metrics']['commits_week'] == 0
    assert result.sample['baselines']['commits_week'] == 0
    assert result.sample['metrics']['hours_since_push'] is None
    assert result.sample['metrics']['ci_passing'] is None
    assert result.sample['unknown_reasons']['ci_passing'] == 'No CI runs on the default branch'
    d = normalize((ROOT / 'examples/e-repo-activity.pulse.yaml').read_text())
    display = compute_display(d, {'main': {'current': result.sample, 'history': []}})
    assert display[0]['ring']['warming'] is False
    assert display[0]['ring']['unknown'] is False
    assert display[0]['ring']['score'] == 0
    assert math.isfinite(display[0]['ring']['score'])


@pytest.mark.parametrize('stats', [{}, SourceError('private', status=202)])
def test_202_computing_keeps_other_metrics_and_hourly_retry(stats):
    result = collect(Net(stats=stats), activity=True, ci=True)
    assert result.sample['metrics']['commits_week'] is None
    assert result.sample['unknown_reasons']['commits_week'] == 'GitHub is still computing commit stats'
    assert result.sample['metrics']['stars'] == 0
    assert result.state['stats_due'] > NOW + 3500


@pytest.mark.parametrize('status', [403, 404, 429, 500])
def test_optional_ci_errors_do_not_destroy_measured_counts(status):
    result = collect(Net(ci=SourceError('sensitive upstream', status=status, retry_after=60)), ci=True)
    assert result.sample['metrics']['stars'] == 0
    assert result.sample['metrics']['ci_passing'] is None
    assert 'sensitive upstream' not in json.dumps(result.sample)


def test_captured_public_data_matches_api_counts_and_prior_twelve_weeks():
    class Recorded(Net):
        def bytes(self, url, **kwargs):
            self.calls.append(url)
            row = PUBLIC[url.removeprefix('https://api.github.com')]
            return json.dumps(row['body']).encode(), row['headers']
    result = collect(Recorded(), activity=True, ci=True)
    raw = PUBLIC['/repos/NousResearch/hermes-agent']['body']
    metrics = result.sample['metrics']
    for metric, key in [('stars', 'stargazers_count'), ('forks', 'forks_count'), ('open_issues', 'open_issues_count')]:
        assert metrics[metric] == raw[key]
    assert metrics['open_prs'] == 34853
    weeks = PUBLIC['/repos/NousResearch/hermes-agent/stats/participation']['body']['all']
    assert metrics['commits_week'] == weeks[-1]
    assert result.sample['baselines']['commits_week'] == pytest.approx(sum(weeks[-13:-1]) / 12)
    # Actual latest run was skipped: neither Passing nor Failing.
    assert metrics['ci_passing'] is None
    assert metrics['ci_running'] == 0


def test_archived_public_repo_is_still_readable():
    raw = copy.deepcopy(PUBLIC['/repos/atom/atom']['body'])
    assert raw['archived'] is True
    result = collect(Net(repo=raw))
    assert result.sample['metrics']['stars'] == raw['stargazers_count']


@pytest.mark.parametrize('value', [None, True, -1, 1.5, '0'])
def test_invalid_repo_counts_never_turn_into_zero(value):
    repo = {**REPO, 'stargazers_count': value}
    with pytest.raises(SourceError):
        collect(Net(repo=repo))
