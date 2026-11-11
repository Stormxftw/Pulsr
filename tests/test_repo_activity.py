"""Opt-in repository telemetry: fixtures only, never live GitHub or credentials."""
import copy
import json
from pathlib import Path

import pytest

from pulse_rings.display import compute_display
from pulse_rings.draft_disclosure import draft_disclosure
from pulse_rings.layout import layout_check, proposal_disclosure
from pulse_rings.layout_presets import layouts
from pulse_rings.sources.base import SourceError
from pulse_rings.sources.github import GitHubRepo
from pulse_rings.spec import normalize, budget, ValidationError, schema
from pulse_rings.templates import from_template

NOW = 1794000000
ROOT = Path(__file__).resolve().parents[1]
REPO = dict(id=123, stargazers_count=3, forks_count=2, open_issues_count=1,
            pushed_at='2026-11-06T18:00:00Z', default_branch='main')


class Net:
    def __init__(self, stats=None, runs=None, error=None):
        self.calls = []
        self.stats = {'all': list(range(1, 53))} if stats is None else stats
        self.runs = {'workflow_runs': [{'status': 'completed', 'conclusion': 'success'}]} if runs is None else runs
        self.error = error or {}

    def bytes(self, url, **kwargs):
        self.calls.append((url, kwargs))
        key = 'stats' if '/stats/' in url else 'runs' if '/actions/' in url else 'pulls' if '/pulls?' in url else 'repo'
        if key in self.error:
            raise SourceError('private upstream text', status=self.error[key], retry_after=60)
        body = {'repo': REPO, 'pulls': [], 'stats': self.stats, 'runs': self.runs}[key]
        return json.dumps(body).encode(), {'content-type': 'application/json'}


@pytest.fixture(autouse=True)
def no_secret(monkeypatch):
    monkeypatch.setattr('pulse_rings.sources.github._optional_token', lambda: None)


def definition(**params):
    return normalize({'pulse': 1, 'title': 'Repo', 'source': {'kind': 'github.repo',
        'params': {'repo': 'Stormxftw/Pulse', **params}}, 'icon': {'brand': 'github'}})


def collect(d, net, state=None, start=NOW):
    adapter, state = GitHubRepo(), state or {}
    for i in range(8):
        result = adapter.poll(d, None, state, now=start + i * 2, net=net)
        state = result.state
        if result.sample is not None:
            return result
    pytest.fail('adapter never completed staged poll')


def test_legacy_golden():
    d = definition()
    assert d['source']['params'] == {'repo': 'Stormxftw/Pulse'}
    assert budget(d) == {'hosts': ['api.github.com'], 'req_per_hour': 8.0, 'req_per_hour_display': 8}
    result = collect(d, Net())
    assert result.sample == {'ts': NOW, 'metrics': {'stars': 3, 'forks': 2, 'open_issues': 1, 'open_prs': 0}, 'baselines': {}, 'unknown_reasons': {}}
    assert result.state == {}
    assert definition(activity=False, ci=False)['ring'] == d['ring']


def test_participation_baseline_push_current_and_hourly_cache():
    net = Net()
    d = definition(activity=True)
    result = collect(d, net)
    assert result.sample['metrics']['commits_week'] == 52
    assert result.sample['baselines']['commits_week'] == pytest.approx(sum(range(40, 52)) / 12)
    from datetime import datetime
    pushed = datetime.fromisoformat(REPO['pushed_at']).timestamp()
    assert result.sample['metrics']['hours_since_push'] == pytest.approx((NOW - pushed) / 3600)
    before = copy.deepcopy(result.sample)
    refreshed = GitHubRepo().current(result.sample, result.state, now=NOW + 3600)
    assert refreshed['metrics']['hours_since_push'] == pytest.approx((NOW + 3600 - pushed) / 3600)
    assert before == result.sample
    again = collect(d, net, result.state, start=NOW + 900)
    assert again.sample['baselines'] == result.sample['baselines']
    assert sum('/stats/participation' in u for u, _ in net.calls) == 1
    collect(d, net, again.state, start=NOW + 3608)
    assert sum('/stats/participation' in u for u, _ in net.calls) == 2


@pytest.mark.parametrize('stats,error,reason', [({}, {'stats': 202}, 'GitHub is still computing commit stats'), ({'all': []}, {}, 'Commit stats unavailable'), ({'all': [1]}, {}, 'Commit stats unavailable'), ({'all': [True] * 52}, {}, 'Commit stats unavailable')])
def test_participation_unknown(stats, error, reason):
    result = collect(definition(activity=True), Net(stats=stats, error=error))
    assert result.sample['metrics']['commits_week'] is None
    assert result.sample['unknown_reasons']['commits_week'] == reason
    assert result.sample['baselines'] == {}


@pytest.mark.parametrize('status,conclusion,passing,running', [('completed', 'success', 1, 0), ('completed', 'failure', 0, 0), ('completed', 'cancelled', 0, 0), ('completed', 'timed_out', 0, 0), ('in_progress', None, None, 1), ('queued', None, None, 1), ('completed', 'skipped', None, 0)])
def test_ci_states(status, conclusion, passing, running):
    net = Net(runs={'workflow_runs': [{'status': status, 'conclusion': conclusion}]})
    result = collect(definition(ci=True), net)
    assert result.sample['metrics']['ci_passing'] == passing
    assert result.sample['metrics']['ci_running'] == running
    assert sum('/actions/runs?branch=main&per_page=1' in u for u, _ in net.calls) == 1
    assert not any('/stats/' in u for u, _ in net.calls)


@pytest.mark.parametrize('error,reason', [({}, 'No CI runs on the default branch'), ({'runs': 403}, 'needs Actions read access'), ({'runs': 404}, 'needs Actions read access')])
def test_ci_unknown(error, reason):
    result = collect(definition(ci=True), Net(runs={'workflow_runs': []}, error=error))
    assert result.sample['metrics']['ci_passing'] is None
    assert result.sample['unknown_reasons']['ci_passing'] == reason


@pytest.mark.parametrize('activity,ci,rate', [(False, False, 12), (True, False, 13), (False, True, 18), (True, True, 19)])
def test_budgets_and_disclosures(activity, ci, rate, tmp_path):
    d = definition(activity=activity, ci=ci)
    d['every'] = '10m'
    assert budget(d)['req_per_hour'] == rate
    assert f'Total: {rate} req/h' in proposal_disclosure(d)['summary']
    row = draft_disclosure(d, tmp_path)['feeds'][0]
    assert row['req_per_hour'] == rate
    if activity:
        assert 'participation' in row['calls'] and '1 req/h' in row['calls']
    if ci:
        assert 'actions/runs' in row['calls'] and '1 call per poll' in row['calls']


def test_token_new_endpoints_and_no_persistence(monkeypatch):
    sentinel = 'ghp_OFFLINE_SENTINEL'
    monkeypatch.setattr('pulse_rings.sources.github._optional_token', lambda: sentinel)
    net = Net()
    result = collect(definition(activity=True, ci=True), net)
    assert len(net.calls) == 4
    assert all(kwargs['headers']['Authorization'] == 'Bearer ' + sentinel for _, kwargs in net.calls)
    assert sentinel not in json.dumps(result.state)


def test_template_preset_and_schema():
    out = from_template('github-repo', {'repo': 'Stormxftw/Pulse', 'commits': True, 'last_push': True, 'ci': True})
    assert out['ok'], out
    assert out['feeds']['main']['params']['activity'] is True
    assert out['feeds']['main']['params']['ci'] is True
    selected = [m['ref'] for m in out['metrics'] if m['default_selected']]
    assert selected == ['main.commits_week', 'main.hours_since_push', 'main.ci_passing']
    preset = next(p for p in layouts(out['feeds'], selected) if p['id'] == 'repo-activity')
    assert layout_check(preset['definition'])['ok']
    assert preset['definition']['display'][0]['components'][0]['baseline'] == 'source'
    assert json.loads((ROOT / 'spec/pulse-1.schema.json').read_text()) == schema()


def stat(block, value):
    d = normalize({'pulse': 1, 'title': 'Stat', 'source': {'kind': 'github.repo', 'params': {'repo': 'a/b', 'activity': True, 'ci': True}}, 'display': [dict(type='stat', value='ci_passing', **block)]})
    return compute_display(d, {'main': {'current': {'ts': NOW, 'metrics': {'ci_passing': value}}, 'history': []}})[0]


def test_stat_states_and_duration():
    block = {'states': {'0': {'label': 'Failing', 'tone': 'crit'}, '1': {'label': 'Passing', 'tone': 'ok'}}}
    assert stat(block, 1)['value_text'] == 'Passing'
    assert stat(block, 1)['tone'] == 'ok'
    assert stat(block, 0)['tone'] == 'crit'
    assert stat(block, 2)['unknown'] is True
    assert stat(block, None)['unknown'] is True
    assert stat({'states': {'1': 'Passing'}}, 1)['value_text'] == 'Passing'
    assert stat({'unit': 'duration'}, 3.2)['value_text'] == '3h 12m ago'
    assert stat({'unit': 'duration'}, 27.5)['value_text'] == '1d 3h 30m ago'
    assert stat({'unit': 'duration'}, -1)['unknown'] is True


def test_actual_net_staging_and_202_hourly_retry(tmp_path, monkeypatch):
    from pulse_rings.net import Net as RealNet
    from pulse_rings.store import Store
    clock = [NOW]
    fixture = Net(stats={}, error={'stats': 202})
    monkeypatch.setattr('pulse_rings.net.fetch_bytes', fixture.bytes)
    net = RealNet(Store(tmp_path), clock=lambda: clock[0])
    source, d, state, previous = GitHubRepo(), definition(activity=True, ci=True), {}, None
    for _ in range(3):
        for step in range(8):
            result = source.poll(d, previous, state, now=clock[0], net=net)
            state = result.state
            if result.sample:
                previous = result.sample
                break
            clock[0] = result.next_due
        else:
            pytest.fail('Staged real-Net poll never finished')
        clock[0] += 900
    assert sum('/stats/' in url for url, _ in fixture.calls) == 1
    assert len(fixture.calls) == 10  # three repo/PR/CI polls plus one stats request
    assert previous['unknown_reasons']['commits_week'] == 'GitHub is still computing commit stats'
    assert net.usage()['used'] == 10


@pytest.mark.parametrize('pushed', [None, 'invalid', '2099-01-01T00:00:00Z', '2026-01-01T00:00:00'])
def test_push_unknown_is_not_zero(pushed):
    result = collect(definition(activity=True), Net())
    result.state['pushed_at'] = GitHubRepo._push_time(pushed)
    sample = GitHubRepo().current(result.sample, result.state, now=NOW)
    assert sample['metrics']['hours_since_push'] is None
    assert sample['unknown_reasons']['hours_since_push'] == 'Last push unavailable'


def test_sample_preview_respects_opt_in_and_renders_repo_semantics():
    from pulse_rings.builder import sample_preview
    legacy = sample_preview(definition())
    assert set(legacy['synthetic_feeds']['main']['current']['metrics']) == {'stars', 'forks', 'open_issues', 'open_prs'}
    preview = sample_preview((ROOT / 'examples/e-repo-activity.pulse.yaml').read_text())
    assert preview['sample'] is True
    assert preview['display'][0]['ring']['warming'] is False
    assert preview['display'][2]['value_text'] == 'Passing'
    assert preview['display'][2]['tone'] == 'ok'
    assert preview['display'][1]['duration'] is True


def test_ready_example():
    example = (ROOT / 'examples/e-repo-activity.pulse.yaml').read_text()
    d = normalize(example)
    assert normalize(d) == d
    check = layout_check(d)
    assert check['ok']
    assert 'elapsed hours' in check['blocks'][1]
    assert 'discrete plain-text states' in check['blocks'][2]
    assert budget(d)['req_per_hour'] == 19
    assert d['source']['params']['repo'] == 'Stormxftw/Pulse'
    assert d['display'][2]['states']['1']['label'] == 'Passing'



@pytest.mark.parametrize('block', [{'states': {str(i): 'x' for i in range(9)}}, {'states': {'1': 'x' * 25}}, {'states': {'1': '<b>Passing</b>'}}, {'states': {'1': {'label': 'OK', 'tone': 'red'}}}, {'states': {'no': 'No'}}, {'states': {'1': 'OK'}, 'unit': 'duration'}])
def test_invalid_states(block):
    with pytest.raises(ValidationError):
        stat(block, 1)
