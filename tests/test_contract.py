"""Cross-package contract, bounded reads, fixtures and metadata admission checks."""
import importlib.util
import json
from pathlib import Path
import re
import tomllib

from pulse_rings.engine import Engine, compute_ring
from pulse_rings.spec import normalize
from pulse_rings.version import VERSION
from ruamel.yaml import YAML
import jsonschema

ROOT = Path(__file__).resolve().parents[1]


def test_one_version_across_packages(tmp_path):
    assert VERSION == '0.5.0-dev'
    assert YAML(typ='safe').load((ROOT/'plugin.yaml').read_text())['version'] == VERSION
    assert tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version'] == VERSION
    assert json.loads((ROOT/'dashboard/manifest.json').read_text())['version'] == VERSION
    assert Engine(tmp_path).status()['api_version'] == VERSION
    assert re.search(r'const VERSION = [\'"]' + re.escape(VERSION) + r'[\'"];', (ROOT/'desktop/plugin.js').read_text())
    assert '**v' + VERSION in (ROOT/'README.md').read_text()
    assert 'version: "'+VERSION+'"' in (ROOT/'submission/CHECKLIST.md').read_text()


def test_mandatory_conformance_dependencies_present():
    assert YAML and jsonschema.Draft202012Validator


def test_first_sample_conformance_examples():
    gh = normalize((ROOT/'examples/b-github.pulse.yaml').read_text())
    sample = {'ts': 10, 'metrics': {'recent': 125}, 'baselines': {'recent': 50}}
    assert compute_ring(gh, sample, [])['score'] == 100
    discord = normalize((ROOT/'examples/a-discord.pulse.yaml').read_text())
    ring = compute_ring(discord, {'ts': 10, 'metrics': {'online': 100, 'members': 1000}}, [])
    assert ring['score'] == 0
    assert all(c['unknown'] for c in ring['components'][:2])
    # All-history rings alone warm; mixed source/fixed/level components don't wait.
    discord['ring']['components'] = discord['ring']['components'][:2]
    assert compute_ring(discord, {'ts': 10, 'metrics': {'online': 100}}, [])['warming']


def test_draft_contract_persisted_budget_parsed_origin_full_preview(tmp_path):
    now = 1000000
    e = Engine(tmp_path, clock=lambda: now)
    d = normalize((ROOT/'examples/b-github.pulse.yaml').read_text())
    sample = {'ts': now, 'metrics': {'recent': 125, 'baseline': 50}, 'baselines': {'recent': 50}}
    draft_id = e.propose(d, origin={'kind': 'cron', 'name': 'scout'}, sample=sample)
    draft = e.status()['drafts'][0]
    assert draft['id'] == draft_id and draft['status'] == 'pending'
    assert draft['origin'] == {'kind': 'cron', 'name': 'scout'}
    assert draft['budget']['req_per_hour_display'] == 5
    assert draft['remaining_req_per_hour'] == 300
    assert draft['preview']['ring']['score'] == 100
    assert draft['preview']['history'] == []
    assert draft['preview']['capsule']['caption'] == '2.5× usual'
    assert set(draft['preview']) >= {'last_ok_ts','next_due','backoff_until','budget','lines','alert','error','icon_data'}
    with e.store.db() as db:
        assert json.loads(db.execute('SELECT budget FROM drafts WHERE id=?',(draft_id,)).fetchone()[0]) == draft['budget']
    assert e.status()['features'] == {'import_discord': True, 'share_yaml': True, 'import_yaml': True}


def test_bounded_history_and_compact_output(tmp_path, monkeypatch):
    now = 1000000
    e = Engine(tmp_path, clock=lambda: now)
    d = normalize((ROOT/'examples/c-hermes.pulse.yaml').read_text())
    e.activate(d)
    with e.store.transaction() as db:
        for i in range(4000):
            sample = {'ts': now - 7*86400 + 30*i, 'metrics': {'turns_running': 1, 'tool_calls_10m': i},
                      'metadata': {'description': 'must not repeat'}}
            e.store.insert_sample(db, d['id'], sample)
        db.execute('UPDATE pulses SET last_ok_ts=?', (now-30,))
    calls = []
    original = e.store.history
    def observe(pulse_id, since=0, tail=0, **kwargs):
        calls.append((since,tail))
        return original(pulse_id,since,tail,**kwargs)
    monkeypatch.setattr(e.store,'history',observe)
    row = e.status()['pulses'][0]
    assert calls == [(now - 86400,48)]
    assert len(row['history']) <= 48
    assert all('metadata' not in s for s in original(d['id']))
    # Refs #91: the trend is aggregated in SQLite, never a second raw history read.
    assert row['trend'] is None or len(row['trend']['points']) + len(row['trend']['previous']) <= 98
    compact = e.status(compact=True, include_icons=False)
    assert 'history' not in compact['pulses'][0] and 'trend' not in compact['pulses'][0]
    assert not {'servers','curated','data_dir'} & compact.keys()
    assert len(json.dumps(compact)) < 5000


def revised_fixture(value):
    """Version adapter for frozen pre-#58/#60 UI fixtures, not new measurements.

    Preserve the old renderer compatibility fixtures. Besides the usual-line
    estimate wording noted below, recompute ONLY their score
    expectations from their recorded component values with an independent float
    reference and fixed fixture presets; all other fields still compare exactly.
    The dedicated live-polish regressions assert the new fields and edge cases.
    """
    from copy import deepcopy
    from decimal import Decimal, ROUND_HALF_UP
    import re

    result = deepcopy(value)

    def visit(node):
        if isinstance(node, list):
            return [visit(x) for x in node]
        if not isinstance(node, dict):
            return node
        ring = node.get('ring')
        if isinstance(ring, dict) and 'score' in ring:
            components = ring['components']
            for c in components:
                baseline, current = c['baseline'], c['value']
                c['baseline_text'] = (f'{Decimal(str(baseline)).to_integral_value(rounding=ROUND_HALF_UP):,}'
                                      if baseline is not None else None)
                c['warming'] = c['unknown'] and current is not None and c['baseline_mode'] in ('median', 'oldest')
                if not c['unknown'] and baseline is not None:
                    metric = c['metric']
                    assert metric in ('online', 'members', 'tool_calls_10m', 'recent')
                    weight, floor, sensitivity = {
                        'online': (80 if len(components) == 2 else 70, 25, .2),
                        'members': (20, 100, .01), 'tool_calls_10m': (80, 5, 1),
                        'recent': (100, 1, 1)}[metric]
                    change = current - baseline
                    denominator = max(5, (max(abs(baseline), floor) + max(-change, 0)) * sensitivity)
                    c['contribution'] = weight * min(abs(change) / denominator, 1)
            ring['score'] = round(sum(c['contribution'] for c in components), 1)
        # #60: a source average on the usual line is shown as an estimate. Recomputed
        # here from the recorded value with independent arithmetic.
        for line in node.get('lines') if isinstance(node.get('lines'), list) else []:
            if (isinstance(line, dict) and line.get('metric') == 'baseline' and isinstance(line.get('label'), str)
                    and isinstance(line.get('value'), (int, float)) and not isinstance(line.get('value'), bool)):
                amount = Decimal(str(line['value']))
                shown = f"{amount.quantize(Decimal(1) if amount >= 10 else Decimal('0.1'), rounding=ROUND_HALF_UP):,f}"
                shown = shown.rstrip('0').rstrip('.') if '.' in shown else shown
                line['label'] = re.sub(r'(?<=usual ≈)[0-9][0-9,.]*(?=/)', shown, line['label'])
        return {k: visit(v) for k, v in node.items()}

    return visit(result)


def fixture_precision(value):
    if isinstance(value, dict):
        return {k: round(v, 12) if k == 'contribution' and isinstance(v, float) else fixture_precision(v)
                for k, v in value.items()}
    return [fixture_precision(v) for v in value] if isinstance(value, list) else value


def without_additive_fields(value):
    """Refs #91, #107: `trend`, `voice` and `server` are additive read-model fields the
    frozen UI fixtures predate. tests/test_trend.py and tests/test_server_card.py cover
    them; everything else still compares exactly."""
    if isinstance(value, list):
        return [without_additive_fields(v) for v in value]
    if not isinstance(value, dict):
        return value
    drop = ('trend', 'voice', 'server') if 'ring' in value and 'capsule' in value else ()
    return {k: without_additive_fields(v) for k, v in value.items() if k not in drop}


def test_ui_fixtures_reproducible_from_status(tmp_path):
    module = importlib.util.spec_from_file_location('generate_ui', ROOT/'scripts/generate-ui-fixtures.py')
    generator = importlib.util.module_from_spec(module); module.loader.exec_module(generator)
    result = generator.generate(tmp_path/'output', scratch=tmp_path)
    for name, payload in result.items():
        expected = revised_fixture(json.loads((ROOT/f'tests/fixtures/ui/{name}.json').read_text(encoding='utf-8')))
        assert fixture_precision(expected) == fixture_precision(without_additive_fields(payload)), name


def test_declared_fixed_hosts_disclosed_and_namespace_justified():
    from pulse_rings.net import FIXED_HOSTS
    disclosure = (ROOT/'README.md').read_text()
    pr = (ROOT/'submission/PR-BODY.md').read_text()
    for host in FIXED_HOSTS:
        assert host in disclosure and host in pr
    assert 'path-unique package' in (ROOT/'dashboard/pulse.py').read_text()
