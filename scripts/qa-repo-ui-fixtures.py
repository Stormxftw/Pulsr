"""Print deterministic engine-computed repo UI evidence; no I/O beyond fixtures."""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pulse_rings.builder import sample_preview
from pulse_rings.display import compute_display
from pulse_rings.engine import compute_capsule, compute_ring
from pulse_rings.spec import normalize

NOW = 1794189600
raw = json.loads((ROOT / 'tests/fixtures/github/qa-repo-public.json').read_text())
public = {r['path']: r for r in raw['records']}
repo = public['/repos/NousResearch/hermes-agent']['body']
weeks = public['/repos/NousResearch/hermes-agent/stats/participation']['body']['all']
metrics = {'stars': repo['stargazers_count'], 'forks': repo['forks_count'],
           'open_issues': repo['open_issues_count'], 'open_prs': 34853,
           'commits_week': weeks[-1], 'hours_since_push': 3.2, 'ci_passing': 1, 'ci_running': 0}
base = {'pulse': 1, 'title': 'Hermes repository · 漢字 🚀 an intentionally long title',
        'source': {'kind': 'github.repo', 'params': {'repo': 'NousResearch/hermes-agent', 'activity': True, 'ci': True}},
        'icon': {'brand': 'github'}}
activity = normalize((ROOT / 'examples/e-repo-activity.pulse.yaml').read_text())
activity.update(title=base['title'], id='synthetic-ebay')
blocks = {
    'counts': [{'type': 'stat', 'value': 'stars', 'label': 'Stars', 'show': 'both'},
               {'type': 'bars', 'bars': [{'value': m, 'label': label} for m, label in
                 [('forks', 'Forks'), ('open_issues', 'Open issues (including PRs)'), ('open_prs', 'Open pull requests')]]},
               {'type': 'spark', 'value': 'stars', 'label': 'Stars trend'}],
    'rings': [{'type': 'rings', 'rings': [{'value': 'stars', 'label': 'Stars'}, {'value': 'forks', 'label': 'Forks'}]},
              {'type': 'bar', 'value': 'open_prs', 'label': 'Open pull requests'}],
    'value': [{'type': 'stat', 'value': 'stars', 'label': 'Stars', 'show': 'value'}],
    'delta': [{'type': 'stat', 'value': 'stars', 'label': 'Stars', 'show': 'delta'}],
    'large': [{'type': 'stat', 'value': 'stars', 'label': 'Stars', 'show': 'both'},
              {'type': 'bar', 'value': 'stars', 'label': 'Stars', 'max': 1000000000000}],
}


def row(name, definition, values=None, reasons=None, history=True):
    d = normalize(definition)
    d['id'] = 'synthetic-ebay'
    current = {'ts': NOW, 'metrics': {**metrics, **(values or {})},
               'baselines': {'commits_week': sum(weeks[-13:-1]) / 12}, 'unknown_reasons': reasons or {}}
    prior = [{'ts': NOW - age, 'metrics': {**current['metrics'], 'stars': 260000 + i * 500},
              'baselines': current['baselines'], 'unknown_reasons': {}} for i, age in enumerate([7200, 3600])]
    if not history:
        prior = []
    ring = compute_ring(d, current, prior)
    preview = sample_preview(d)
    preview.update(id=d['id'], kind='github.repo', state='active', sample=False, icon_data=None,
                   last_ok_ts=NOW, every=d.get('every', '15m'), error=None, history=prior,
                   ring=ring, capsule=compute_capsule(d, current, ring),
                   display=compute_display(d, {'main': {'current': current, 'history': prior}}))
    return preview


rows = {name: row(name, {**base, 'display': display}, {'stars': 123456789012} if name == 'large' else None)
        for name, display in blocks.items()}
rows['activity'] = row('activity', activity)
rows['first'] = row('first', {**base, 'display': blocks['counts']}, history=False)
rows['computing'] = row('computing', activity, {'commits_week': None, 'ci_passing': None, 'ci_running': None},
                        {'commits_week': 'GitHub is still computing commit stats', 'ci_passing': 'No CI runs on the default branch'})
rows['queued'] = row('queued', activity, {'ci_passing': None, 'ci_running': 1}, {'ci_passing': 'CI run is still running'})
rows['failing'] = row('failing', activity, {'ci_passing': 0})
rows['no-access'] = row('no-access', activity, {'ci_passing': None}, {'ci_passing': 'needs Actions read access'})
for state in ('stale', 'degraded', 'backoff', 'error'):
    rows[state] = copy.deepcopy(rows['activity'])
    rows[state].update(state=state, error='GitHub rate limited. Waiting before retry.' if state == 'backoff'
                       else 'GitHub repository moved or was renamed. Update the approved repository.', backoff_until=NOW + 600)
print(json.dumps(rows, ensure_ascii=True))
