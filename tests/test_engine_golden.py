"""Replay recorded data and the old movement regressions against a frozen oracle."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('legacy_v030', ROOT / 'tests/legacy_v030.py')
legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(legacy)
from pulse_rings.spec import normalize
PRESET = normalize((ROOT / 'examples/a-discord.pulse.yaml').read_text(encoding='utf-8'))


def sequences():
    recorded = json.loads((ROOT / 'tests/fixtures/recorded-status.json').read_text())
    for server in recorded['servers']:
        history = [{'ts': s['ts'], 'online': s.get('online'), 'members': None}
                   for s in server['history'] if s['ts'] < server['ts']]
        # The recorded status omits member history but records the exact net
        # delta against its sole prior sample. Recover that value, not a guess.
        if len(history) == 1 and server['movement']['member_delta'] is not None:
            history[0]['members'] = server['members'] - server['movement']['member_delta']
        yield server['code'] + '-recorded', history + [server]
    real = json.loads((ROOT / 'tests/fixtures/golden/live-discord-series.json').read_text())
    for guild in sorted({s['guild'] for s in real}):
        yield guild + '-real', sorted([s for s in real if s['guild'] == guild], key=lambda s: s['ts'])
    # Every recorded invite fixture, without inventing missing history.
    for path in sorted((ROOT / 'tests/fixtures').glob('*.json')):
        raw = json.loads(path.read_text())
        if isinstance(raw, dict) and 'guild' in raw:
            yield path.stem + '-invite', [{'ts': 1, 'online': raw.get('approximate_presence_count'),
                                         'members': raw.get('approximate_member_count')}]
    yield 'falling', [{'ts': 100, 'online': 100, 'members': 1000},
                      {'ts': 700, 'online': 80, 'members': 1010, 'voice_channels': 5}]
    yield 'median-unknown', [{'ts': 1, 'online': 9000}, {'ts': 99000, 'online': 100},
                             {'ts': 99500, 'online': 100}, {'ts': 100000, 'online': 110, 'members': None}]
    yield 'zero-cap', [{'ts': 1, 'online': 0, 'members': 0},
                       {'ts': 2, 'online': 10000, 'members': 10000, 'voice_channels': 999}]
    yield 'unknown-zero-boundary', [{'ts': 1, 'online': None, 'members': None},
        {'ts': 601, 'online': 0, 'members': 0, 'voice_channels': 0},
        {'ts': 1201, 'online': 5, 'members': 1, 'voice_channels': None},
        {'ts': 87601, 'online': None, 'members': 0, 'voice_channels': 5}]


def revised_movement(current, history):
    """Refs #58: retain frozen raw-value oracle, independently update its score.

    The frozen v0.3 oracle intentionally contains the old saturating formula;
    never edit it or the recorded readings to make the new behavior pass.
    """
    result = legacy.movement(current, history)
    if result['warming']:
        return result
    for metric, key, weight, floor, sensitivity in [
            ('online', 'presence', 70, 25, .2), ('members', 'members', 20, 100, .01)]:
        delta = result['online_delta' if metric == 'online' else 'member_delta']
        if delta is None:
            continue
        usual = current[metric] - delta
        denominator = max(5, (max(abs(usual), floor) + max(-delta, 0)) * sensitivity)
        result['components'][key] = 0 if usual == 0 and current[metric] != 0 else weight * min(abs(delta) / denominator, 1)
    result['score'] = round(sum(result['components'].values()), 1)
    return result


def assert_movement(actual, expected):
    assert {k: v for k, v in actual.items() if k not in ('warming', 'components')} == {
        k: v for k, v in expected.items() if k not in ('warming', 'components')}
    assert actual['components'] == pytest.approx(expected['components'])


@pytest.mark.parametrize('name,sequence', list(sequences()), ids=lambda x: x if isinstance(x, str) else None)
def test_golden(name, sequence, tmp_path):
    from pulse_rings.engine import Engine, compute_ring, compute_capsule, legacy_movement
    from pulse_rings.sources.base import SourceResult
    now = [sequence[0]['ts']]
    class Replay:
        def poll(self, definition, previous, state, *, now, net):
            current = next(s for s in sequence if s['ts'] == now)
            metrics = {k: current.get(k) for k in ('online', 'members', 'voice_channels')}
            return SourceResult(sample={'ts': now, 'metrics': metrics}, next_due=now + 1)
    engine = Engine(tmp_path, clock=lambda: now[0], adapters={'discord.invite@1': Replay()})
    engine.activate(PRESET)
    history = []
    for current in sequence:
        expected = revised_movement(current, history)
        ring = compute_ring(PRESET, current, history)
        actual = legacy_movement(ring)
        assert_movement(actual, expected)
        capsule = compute_capsule(PRESET, current, ring)
        assert capsule['fill'] == legacy.capsule_metric(current, expected)['fill']
        now[0] = current['ts']
        persisted = engine.status(poll=True)['pulses'][0]
        persisted_numbers = legacy_movement(persisted['ring'])
        assert_movement(persisted_numbers, expected)
        assert persisted['capsule']['fill'] == legacy.capsule_metric(current, expected)['fill']
        history.append(copy.deepcopy(current))
    if name.endswith('-recorded'):
        # Recorded old scores are historical evidence, not the corrected formula.
        assert {k: v for k, v in actual.items() if k not in ('warming', 'score', 'components')} == {
            k: v for k, v in sequence[-1]['movement'].items() if k not in ('warming', 'score', 'components')}


def test_generalized_source_fixed_direction_and_unknown():
    from pulse_rings.engine import compute_ring, compute_capsule
    pulse = copy.deepcopy(PRESET)
    pulse['ring']['components'] = [{'metric': 'recent', 'weight': 100, 'type': 'delta',
                                   'baseline': 'source', 'direction': 'up', 'sensitivity': 1}]
    pulse['capsule'] = {'metric': 'recent', 'label': '{value} PRs', 'fill': 'baseline'}
    sample = {'ts': 10, 'metrics': {'recent': 25}, 'baselines': {'recent': 10}}
    ring = compute_ring(pulse, sample, [{'ts': 1, 'metrics': {'recent': 1}}])
    assert ring['score'] == 100
    assert ring['components'][0]['baseline_mode'] == 'source'
    assert compute_capsule(pulse, sample, ring)['fill'] == 100
    sample['metrics']['recent'] = 5
    assert compute_ring(pulse, sample, [{'ts': 1}])['score'] == 0
    sample['metrics']['recent'] = None
    assert compute_ring(pulse, sample, [{'ts': 1}])['components'][0]['unknown']
    assert compute_capsule(pulse, sample, ring)['caption'] == 'Not measured'


def test_fixed_level_and_warming():
    from pulse_rings.engine import compute_ring
    pulse = copy.deepcopy(PRESET)
    pulse['ring']['components'] = [
        {'metric': 'count', 'weight': 80, 'type': 'delta', 'baseline': 10, 'direction': 'down'},
        {'metric': 'errors', 'weight': 20, 'type': 'level', 'full_at': 5}]
    sample = {'ts': 10, 'metrics': {'count': 0, 'errors': 10}}
    assert compute_ring(pulse, sample, [])['score'] == 60
    assert compute_ring(pulse, sample, [{'ts': 1}])['score'] == 60


def test_partial_unknown_alert_and_fixed_capsule():
    from pulse_rings.engine import compute_ring, compute_capsule, compute_lines, compute_alert
    pulse = copy.deepcopy(PRESET)
    pulse['alert'] = {'ring_at_least': 70}
    sample = {'ts': 10, 'online': 200, 'members': None, 'voice_channels': None}
    ring = compute_ring(pulse, sample, [{'ts': 1, 'online': 100}])
    assert ring['score'] == 70
    assert compute_alert(pulse, sample, ring)['active']
    pulse['capsule']['fill'] = {'full_at': 400}
    assert compute_capsule(pulse, sample, ring)['fill'] == 50
    pulse['lines'] = [{'metric': 'online', 'label': '{value} online', 'hide_when_zero': True}]
    assert compute_lines(pulse, {**sample, 'online': 0}, ring) == []
    assert compute_lines(pulse, {**sample, 'online': None}, ring)[0]['unknown']


def test_general_capsule_ratio_is_kind_independent():
    from pulse_rings.engine import compute_ring, compute_capsule
    pulse = copy.deepcopy(PRESET)
    pulse['source']['kind'] = 'github.search@1'
    sample = {'ts': 10, 'online': 250}
    ring = compute_ring(pulse, sample, [{'ts': 1, 'online': 100}])
    assert compute_capsule(pulse, sample, ring)['caption'] == '2.5× usual'
    pulse['source']['kind'] = 'discord.invite@1'
    assert compute_capsule(pulse, sample, ring)['caption'] == '2.5× usual'


@pytest.mark.parametrize('value', [True, '25', float('nan'), float('inf'), 10 ** 1000])
def test_invalid_numbers_stay_unknown(value):
    from pulse_rings.engine import compute_ring, compute_capsule
    sample = {'ts': 10, 'online': value}
    ring = compute_ring(PRESET, sample, [{'ts': 1, 'online': 100}])
    assert ring['components'][0]['unknown']
    assert ring['score'] == 0
    assert compute_capsule(PRESET, sample, ring)['caption'] == 'Not measured'
