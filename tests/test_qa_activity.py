"""Activity/session QA regressions using controlled official observer inputs."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from pulse_rings.hooks import HookRecorder
from pulse_rings.sessions import SessionTracker
from pulse_rings.sources.hermes import HermesActivity, METRICS
from pulse_rings.store import Store


@pytest.mark.parametrize('since', [2000, 'nan', 'inf'])
def test_current_does_not_turn_invalid_observation_coverage_into_zero(tmp_path, since):
    store = Store(tmp_path)
    with store.db() as db:
        db.execute("INSERT INTO meta VALUES ('hermes_observed_since',?)", (str(since),))
    sample = {'ts': 1000, 'metrics': {key: None for key in METRICS},
              'unknown_reasons': {key: 'Not observed' for key in METRICS}}
    before = deepcopy(sample)
    assert HermesActivity(store).current(sample, {}, now=1000) == before
    assert sample == before


def test_current_matches_poll_for_future_open_events(tmp_path):
    store = Store(tmp_path)
    recorder = HookRecorder(store, clock=lambda: 1000)
    try:
        recorder.callbacks['pre_llm_call'](session_id='future')
        adapter = HermesActivity(store)
        with store.db() as db:
            db.execute("UPDATE meta SET value='0' WHERE key='hermes_observed_since'")
        definition = {'source': {'params': {'scope': 'profile'}}}
        sample = adapter.poll(definition, None, {}, now=999, net=None).sample
        assert sample['metrics']['turns_running'] == 0
        assert adapter.current(sample, {}, now=999)['metrics']['turns_running'] == 0
    finally:
        recorder.close()


def test_late_previous_turn_end_cannot_finish_current_turn():
    tracker = SessionTracker(clock=lambda: 1000)
    tracker.enabled = True
    tracker.observe('pre_llm_call', session_id='one', turn_id='old')
    tracker.observe('on_session_end', session_id='one', turn_id='old')
    tracker.observe('pre_llm_call', session_id='one', turn_id='new')
    tracker.observe('post_tool_call', session_id='one', turn_id='new')
    tracker.observe('on_session_finalize', session_id='one', turn_id='old')
    tracker.observe('on_session_end', session_id='one', turn_id='old')
    row = tracker.snapshot()[0]
    assert row['state'] == 'Working'
    assert row['finished_ts'] is None
    assert row['tool_calls_turn'] == 1


def test_child_activity_does_not_erase_parent_turn_tools_after_idle():
    now = [1000]
    tracker = SessionTracker(clock=lambda: now[0])
    tracker.enabled = True
    tracker.observe('pre_llm_call', session_id='parent', turn_id='one')
    tracker.observe('post_tool_call', session_id='parent', turn_id='one')
    tracker.observe('subagent_start', parent_session_id='parent', child_session_id='child')
    now[0] += 7201
    tracker.observe('subagent_start', parent_session_id='parent', child_session_id='child-2')
    assert tracker.snapshot()[0]['tool_calls_turn'] == 1


def test_activity_zero_and_complete_windows_no_network(tmp_path):
    store = Store(tmp_path)
    recorder = HookRecorder(store, clock=lambda: 1000)
    try:
        adapter = HermesActivity(store)
        definition = {'source': {'params': {'scope': 'profile'}}}
        cold = adapter.poll(definition, None, {}, now=1000, net=object()).sample
        assert cold['metrics']['turns_running'] == 0
        assert cold['metrics']['tool_calls_10m'] is None
        assert cold['metrics']['tool_errors_1h'] is None
        mature = adapter.poll(definition, None, {}, now=4600, net=object()).sample
        assert mature['metrics'] == dict.fromkeys(METRICS, 0)
    finally:
        recorder.close()


@pytest.mark.parametrize('kind', ['score', 'rings', 'bar', 'bars', 'stat', 'spark'])
@pytest.mark.parametrize('value', [None, 0, 1, 123456789])
def test_activity_all_blocks_keep_unknown_zero_and_large_values_distinct(kind, value):
    from pulse_rings.display import compute_display
    from pulse_rings.spec import normalize
    item = {'value': 'turns_running', 'max': 4, 'label': 'Running turns'}
    blocks = {
        'score': {'type': 'score', 'components': [{'metric': 'turns_running', 'type': 'level', 'weight': 100, 'full_at': 4}]},
        'rings': {'type': 'rings', 'rings': [item]},
        'bar': {'type': 'bar', **item},
        'bars': {'type': 'bars', 'max': 4, 'bars': [{'value': 'turns_running', 'label': 'Running turns'}, {'value': 'waiting_on_you', 'label': 'Waiting'}]},
        'stat': {'type': 'stat', 'value': 'turns_running', 'label': 'Running turns'},
        'spark': {'type': 'spark', 'value': 'turns_running', 'label': 'Turn trend'},
    }
    definition = normalize({'pulse': 1, 'title': 'Hermes · 长标题',
        'source': {'kind': 'hermes.activity', 'params': {'scope': 'profile'}}, 'display': [blocks[kind]]})
    sample = {'ts': 10000, 'metrics': dict.fromkeys(METRICS, value),
              'unknown_reasons': dict.fromkeys(METRICS, 'Observer not initialized') if value is None else {}}
    data = {'main': {'current': sample, 'history': [], 'status': {'state': 'active'}}}
    block = compute_display(definition, data)[0]
    assert 'NaN' not in json.dumps(block, allow_nan=False)
    if kind == 'score':
        assert block['ring']['unknown'] == (value is None)
        if value is not None:
            assert 0 <= block['ring']['score'] <= 100
    elif kind in ('rings', 'bar', 'bars'):
        row = block['items'][0]
        assert row['value'] == value and row['unknown'] == (value is None)
        if value is None:
            assert row['fill'] is None and row['reason']
        else:
            assert row['fill'] == (0 if value == 0 else 25 if value == 1 else 100)
            if value == 123456789:
                assert row['value_text'] == '123,456,789'
    elif kind == 'stat':
        assert block['value'] == value and block['unknown'] == (value is None)
        assert block['delta'] is None  # no previous/usual evidence yet
    else:
        assert block['unknown'] == (value is None)
        assert block['points'][-1]['value'] == value


def test_activity_auto_and_usual_range_learning_never_divides_by_zero():
    from pulse_rings.display import compute_display
    from pulse_rings.spec import normalize
    definition = normalize({'pulse': 1, 'title': 'Hermes',
        'source': {'kind': 'hermes.activity', 'params': {'scope': 'profile'}},
        'display': [{'type': 'bar', 'value': 'turns_running'},
                    {'type': 'bar', 'value': 'tool_calls_10m', 'max': 'usual'}]})
    def sample(ts):
        return {'ts': ts, 'metrics': dict.fromkeys(METRICS, 0), 'unknown_reasons': {}}
    data = {'main': {'current': sample(10000), 'history': [], 'status': {}}}
    cold = compute_display(definition, data)
    assert cold[0]['items'][0]['learning']
    assert cold[1]['items'][0]['fill'] is None
    data['main']['history'] = [sample(6000), sample(8000)]
    learned = compute_display(definition, data)
    assert learned[0]['items'][0]['max'] > 0
    assert learned[0]['items'][0]['fill'] == 0
    assert learned[1]['items'][0]['fill'] is None
    json.dumps(learned, allow_nan=False)


def test_activity_builder_draft_discloses_local_reads_without_polling(tmp_path, monkeypatch):
    from pulse_rings.engine import Engine
    from pulse_rings.layout_presets import layouts
    from pulse_rings.templates import from_template
    template = from_template('hermes', {})
    selected = [m['ref'] for m in template['metrics'] if m['default_selected']]
    definition = layouts(template['feeds'], selected)[0]['definition']
    engine = Engine(tmp_path, clock=lambda: 10000)
    monkeypatch.setattr(engine, 'fetch', lambda *a, **k: pytest.fail('network'))
    created = engine.create_draft(definition, origin={'kind': 'session', 'surface': 'desktop'})
    assert created['preview_calls'] == 0 and created['preview'] is None
    assert created['budget']['hosts'] == [] and created['budget']['req_per_hour'] == 0
    draft = engine.draft(created['draft_id'])
    feed = draft['disclosure']['feeds'][0]
    assert feed['kind'] == 'hermes.activity' and feed['params']['scope'] == 'profile'
    assert feed['every'] == '30s'
    assert not engine.store.rows()  # only a draft, never activated


def test_bundled_activity_example_normalizes_and_renders(tmp_path):
    from pulse_rings.engine import Engine
    from pulse_rings.spec import normalize
    root = Path(__file__).resolve().parents[1]
    definition = normalize((root / 'examples/c-hermes.pulse.yaml').read_text(encoding='utf-8'))
    engine = Engine(tmp_path, clock=lambda: 10000)
    engine.activate(definition)
    assert engine.poll_one_due()
    pulse = engine.status()['pulses'][0]
    assert pulse['ring']['unknown']
    assert pulse['budget']['req_per_hour'] == 0
    assert pulse['capsule']['fill'] is None
