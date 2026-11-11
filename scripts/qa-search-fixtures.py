"""Build real Engine rows from controlled counts for the browser QA boundary."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pulse_rings.engine import Engine
from pulse_rings.spec import budget, normalize

NOW = 1794186152


def fixtures():
    demo_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'tests/fixtures/github/hackathon-race.pulse.yaml'
    d = normalize(demo_path.read_text(encoding='utf-8'))
    # This helper never reads live storage or polls a remote adapter.
    d['id'] = 'hackathon-race'
    rows = {}
    with tempfile.TemporaryDirectory(prefix='search-qa-', dir=os.environ.get('TMPDIR')) as folder:
        engine = Engine(folder, clock=lambda: NOW + 60)
        for key, recent, baseline in [('measured', 173, 46), ('million', 1234567, 42),
                                      ('singular', 1, 1), ('zero', 0, 0)]:
            sample = {'ts': NOW, 'metrics': {'recent': recent, 'baseline': baseline}, 'baselines': {'recent': baseline}}
            rows[key] = engine.preview(d, sample, budget(d))
        engine.activate(d, sample={'ts': NOW, 'metrics': {'recent': 173, 'baseline': 46}, 'baselines': {'recent': 46}})
        for key, error, backoff, last_ok in [
            ('error', 'GitHub search count is incomplete.', 0, NOW),
            ('backoff', 'GitHub rate limited. Waiting before retry.', NOW + 600, NOW),
            ('credential', 'GitHub credential rejected. Check the configured token.', 0, NOW),
            ('query', 'GitHub rejected the approved search parameters.', 0, NOW),
            ('network', 'Could not reach GitHub. Cached history is preserved.', 0, NOW),
            ('stale', None, 0, NOW - 1800)]:
            with engine.store.transaction() as db:
                db.execute('UPDATE pulses SET error=?,backoff_until=?,last_ok_ts=? WHERE id=?', (error, backoff, last_ok, d['id']))
            rows[key] = engine.status(poll=False, include_icons=False)['pulses'][0]
        rows['warming'] = engine.preview(d, None, budget(d))
        # Legacy capsule path shares the same measured-zero formatter.
        legacy = copy.deepcopy(d)
        legacy.pop('display', None)
        rows['singular_capsule'] = engine.preview(legacy, {'ts': NOW, 'metrics': {'recent': 1, 'baseline': 1}, 'baselines': {'recent': 1}}, budget(legacy))
        rows['zero_capsule'] = engine.preview(legacy, {'ts': NOW, 'metrics': {'recent': 0, 'baseline': 0}, 'baselines': {'recent': 0}}, budget(legacy))
    return {'as_of': NOW + 60, 'definition': d, 'rows': rows}


if __name__ == '__main__':
    print(json.dumps(fixtures(), allow_nan=False))
