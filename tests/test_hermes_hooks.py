"""Observer privacy, actual hook kwargs, TTL, process-local reuse and latency."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import multiprocessing
from pathlib import Path
import sqlite3
import statistics
import time
from types import SimpleNamespace

import pytest

from pulse_rings.hooks import HOOKS, HookRecorder, register_hooks
from pulse_rings.sources.base import SourceError
from pulse_rings.sources.hermes import HermesActivity, METRICS
from pulse_rings.spec import normalize
from pulse_rings.store import Store

ROOT = Path(__file__).resolve().parents[1]


def definition():
    return normalize((ROOT / 'examples/c-hermes.pulse.yaml').read_text(encoding='utf-8'))


def poll(store, now):
    # Any attempted networking fails immediately: this source has no egress.
    return HermesActivity(store).poll(definition(), None, {}, now=now, net=object())


@pytest.fixture
def observer(tmp_path):
    store = Store(tmp_path)
    now = [10000.0]
    recorder = HookRecorder(store, clock=lambda: now[0])
    yield store, recorder, now
    recorder.close()


def test_no_observer_means_unknown_not_measured_zero(tmp_path):
    result = poll(Store(tmp_path), 10000)
    assert all(result.sample['metrics'][key] is None for key in METRICS)
    assert all(result.sample['unknown_reasons'][key] for key in METRICS)


def test_pairs_use_real_kwargs_and_are_idempotent(observer):
    store, recorder, now = observer
    cb = recorder.callbacks
    for _ in range(2):
        assert cb['pre_llm_call'](session_id='session', task_id='task', turn_id='turn', user_message='NEVER STORE') is None
        cb['on_human_input_request'](kind='clarify', request_id='req', session_id='session', session_key='chat', platform='desktop', prompt='NEVER STORE')
        cb['subagent_start'](parent_session_id='session', child_session_id='child', child_subagent_id='task-1', child_role='research', child_goal='NEVER STORE')
    metrics = poll(store, now[0]).sample['metrics']
    assert metrics['turns_running'] == metrics['waiting_on_you'] == metrics['subagents_running'] == 1
    cb['on_human_input_resolved'](kind='clarify', request_id='req', outcome='submitted')
    cb['subagent_stop'](parent_session_id='session', child_session_id='child', child_summary='NEVER STORE', child_status='completed')
    cb['on_session_end'](session_id='session', completed=True, interrupted=False)
    cb['on_session_end'](session_id='session', completed=True)  # duplicate close harmless
    metrics = poll(store, now[0]).sample['metrics']
    assert metrics['turns_running'] == metrics['waiting_on_you'] == metrics['subagents_running'] == 0


@pytest.mark.parametrize('kind', ['approval', 'clarify', 'sudo'])
def test_unified_human_hooks_cover_approval_without_double_count(observer, kind):
    store, recorder, now = observer
    recorder.callbacks['on_human_input_request'](kind=kind, request_id='r')
    assert poll(store, now[0]).sample['metrics']['waiting_on_you'] == 1
    recorder.callbacks['on_human_input_resolved'](kind=kind, request_id='r')
    assert poll(store, now[0]).sample['metrics']['waiting_on_you'] == 0
    assert 'pre_approval_request' not in HOOKS  # unified pair already includes approvals


def test_missing_and_future_ids_are_not_merged_or_persisted(observer):
    store, recorder, now = observer
    for kwargs in [{}, {'session_id': ''}, {'session_id': {}}, {'session_id': 'x' * 4097}]:
        recorder.callbacks['pre_llm_call'](**kwargs)
    recorder.callbacks['on_human_input_request'](kind='future_SECRET', request_id='r')
    recorder.callbacks['subagent_start'](child_subagent_id='unpairable', child_session_id=None)
    assert poll(store, now[0]).sample['metrics']['turns_running'] == 0
    with closing(store.db()) as db:
        assert db.execute('SELECT count(*) FROM hermes_open').fetchone()[0] == 0


def test_sentinels_never_reach_db_wal_status_or_logs(observer, caplog):
    store, recorder, now = observer
    sentinels = ['PROMPT_SECRET_4815', 'COMMAND_SECRET_1623', 'ARGS_SECRET_4242', 'RESULT_SECRET_81516',
                 'SUMMARY_SECRET_92342', 'GOAL_SECRET_9382']
    kwargs = dict(session_id='RAW_SESSION_ID_12848', request_id='RAW_REQUEST_ID_67382', child_session_id='RAW_CHILD_ID_6464',
        parent_session_id='RAW_PARENT_ID_87382', kind='approval', status='error', command=sentinels[1], prompt=sentinels[0],
        args={'secret': sentinels[2]}, result=sentinels[3], child_summary=sentinels[4], child_goal=sentinels[5],
        user_message=sentinels[0], conversation_history=[{'content': sentinels[0]}],
        request={'prompt': sentinels[0]}, error={'message': sentinels[1]})
    for name in HOOKS:
        recorder.callbacks[name](**kwargs)
    # Leave open rows so the raw-id assertion actually exercises hashing.
    for name in ('pre_llm_call', 'on_human_input_request', 'subagent_start'):
        recorder.callbacks[name](**kwargs)
    with closing(store.db()) as db:
        text = '\n'.join(db.iterdump())
        keys = db.execute('SELECT key FROM hermes_open').fetchall()
        assert len(keys) == 3 and all(len(row[0]) == 64 for row in keys)
    raw = b''.join(path.read_bytes() for path in store.root.glob('pulse.sqlite3*'))
    output = text + json.dumps(poll(store, now[0]).sample) + caplog.text
    for value in sentinels + [kwargs[key] for key in ('session_id', 'request_id', 'child_session_id', 'parent_session_id')]:
        assert value not in output
        assert value.encode() not in raw


def test_salt_is_durable_per_profile_but_not_shared_between_profiles(tmp_path):
    first, second = Store(tmp_path / 'a'), Store(tmp_path / 'b')
    a = HookRecorder(first, clock=lambda: 1000)
    b = HookRecorder(second, clock=lambda: 1000)
    key = a._hash('session', 'same')
    assert key != b._hash('session', 'same')
    a.close()
    a2 = HookRecorder(Store(tmp_path / 'a'), clock=lambda: 1001)
    assert a2._hash('session', 'same') == key
    a2.close()
    b.close()


def test_ttl_expiry_exact_boundary(observer):
    store, recorder, now = observer
    recorder.callbacks['pre_llm_call'](session_id='s')
    recorder.callbacks['on_human_input_request'](kind='sudo', request_id='r')
    recorder.callbacks['subagent_start'](child_session_id='child')
    assert poll(store, now[0] + 1799).sample['metrics']['waiting_on_you'] == 1
    assert poll(store, now[0] + 1800).sample['metrics']['waiting_on_you'] == 0
    last = poll(store, now[0] + 7200).sample['metrics']
    assert last['turns_running'] == last['subagents_running'] == 0


def test_windows_retention_unknown_errors_and_no_future_events(observer):
    store, recorder, now = observer
    start = now[0]
    now[0] += 3600
    cb = recorder.callbacks
    cb['post_tool_call'](status='ok')
    cb['post_tool_call'](status='error', result='ignored')
    cb['post_tool_call'](status='blocked')
    cb['post_tool_call'](status='cancelled')
    cb['api_request_error'](api_request_id='x', error={'message': 'ignored'}, request={'body': 'ignored'})
    sample = poll(store, now[0]).sample
    assert sample['metrics']['tool_calls_10m'] == 4
    assert sample['metrics']['tool_errors_1h'] == sample['metrics']['provider_errors_1h'] == 1
    assert poll(store, now[0] - 1).sample['metrics']['tool_calls_10m'] == 0
    assert poll(store, now[0] + 600).sample['metrics']['tool_calls_10m'] == 0
    assert poll(store, now[0] + 3600).sample['metrics']['tool_errors_1h'] == 0
    assert poll(store, now[0] + 48 * 3600).sample['metrics']['provider_errors_1h'] == 0
    with closing(store.db()) as db:
        assert db.execute('SELECT count(*) FROM hermes_events').fetchone()[0] == 0
    assert poll(store, start).sample['metrics']['tool_calls_10m'] is None


def test_missing_status_is_unknown_not_a_fake_success(observer):
    store, recorder, now = observer
    now[0] += 3600
    recorder.callbacks['post_tool_call'](tool_name='ignored', result='no parsing')
    sample = poll(store, now[0]).sample
    assert sample['metrics']['tool_calls_10m'] == 1
    assert sample['metrics']['tool_errors_1h'] is None
    assert sample['unknown_reasons']['tool_errors_1h']


def test_cron_origin_is_enum_only_and_subagents_are_tagged(tmp_path):
    store, now = Store(tmp_path), [1000]
    cron = [SimpleNamespace(job_name='SECRET_JOB', prompt='SECRET_PROMPT')]
    recorder = HookRecorder(store, clock=lambda: now[0], cron_provider=lambda: cron[0])
    recorder.callbacks['pre_llm_call'](session_id='cron_session')
    cron[0] = None
    recorder.callbacks['pre_llm_call'](session_id='child_session', parent_session_id='parent')
    result = poll(store, now[0])
    assert result.metadata['cron_turns_running'] == result.metadata['subagent_turns_running'] == 1
    with closing(store.db()) as db:
        assert {row[0] for row in db.execute('SELECT origin FROM hermes_open')} == {'cron', 'subagent'}
        assert 'SECRET_' not in '\n'.join(db.iterdump())
    recorder.close()


def test_callbacks_never_raise_on_closed_db_bad_kwargs_or_clock(observer):
    store, recorder, now = observer
    recorder.db.close()
    for callback in recorder.callbacks.values():
        assert callback(session_id='s', request_id='r', child_session_id='c', kind=['bad'], status=['bad']) is None
    assert recorder.dropped > 0
    recorder.closed = True
    assert recorder.callbacks['post_tool_call'](status='ok') is None


def test_locked_db_drops_quickly_without_blocking_agent(observer):
    store, recorder, now = observer
    with closing(store.db()) as other:
        other.execute('BEGIN IMMEDIATE')
        started = time.perf_counter()
        assert recorder.callbacks['post_tool_call'](status='ok') is None
        elapsed = time.perf_counter() - started
        other.rollback()
    assert recorder.dropped == 1
    assert elapsed < 0.25


def test_persistent_connection_no_per_hook_open_or_stat(observer, monkeypatch):
    store, recorder, now = observer
    def forbidden(*args, **kwargs):
        raise AssertionError('hot path opened DB or performed stat')
    monkeypatch.setattr(store, 'db', forbidden)
    monkeypatch.setattr(sqlite3, 'connect', forbidden)
    monkeypatch.setattr('os.stat', forbidden)
    for _ in range(100):
        recorder.callbacks['post_tool_call'](status='ok')
    assert recorder.dropped == 0
    assert recorder.db.execute('SELECT count(*) FROM hermes_events').fetchone()[0] == 100


def test_cross_thread_callbacks_share_connection(observer):
    store, recorder, now = observer
    with ThreadPoolExecutor(max_workers=1) as pool:
        list(pool.map(lambda _: recorder.callbacks['post_tool_call'](status='ok'), range(20)))
    assert recorder.dropped == 0
    assert recorder.db.execute('SELECT count(*) FROM hermes_events').fetchone()[0] == 20


def _process_write(root):
    recorder = HookRecorder(Store(root), clock=lambda: 1000)
    recorder.callbacks['pre_llm_call'](session_id='child process session')
    for _ in range(20):
        recorder.callbacks['post_tool_call'](status='ok')
    recorder.close()


def test_real_process_shared_counts_and_salt(tmp_path):
    store = Store(tmp_path)
    context = multiprocessing.get_context('spawn')
    process = context.Process(target=_process_write, args=(str(tmp_path),))
    process.start()
    process.join(timeout=30)
    if process.is_alive():
        process.terminate()
        process.join()
        pytest.fail('child process did not finish')
    assert process.exitcode == 0
    recorder = HookRecorder(store, clock=lambda: 1001)
    recorder.callbacks['on_session_end'](session_id='child process session')
    assert poll(store, 1001).sample['metrics']['turns_running'] == 0
    assert recorder.db.execute('SELECT count(*) FROM hermes_events').fetchone()[0] == 20
    recorder.close()


def test_register_only_official_hooks_reuses_connection_and_closes_on_unload(tmp_path):
    hooks, unload = {}, []
    ctx = SimpleNamespace(register_hook=lambda name, cb: hooks.update({name: cb}), on_unload=unload.append,
                          current_cron_execution=lambda: None)
    first = register_hooks(ctx, store=Store(tmp_path), clock=lambda: 1000)
    second = register_hooks(ctx, store=Store(tmp_path), clock=lambda: 1000)
    assert first is second
    assert set(hooks) == set(HOOKS)
    assert all(hooks[name].__name__ == name for name in HOOKS)
    hooks['pre_llm_call'](session_id='s')
    assert poll(Store(tmp_path), 1000).sample['metrics']['turns_running'] == 1
    for callback in unload:
        callback()
    assert first.closed


def test_initialization_failure_never_breaks_plugin(tmp_path):
    class Broken:
        root = tmp_path
        managed = True
        def db(self, **kwargs):
            raise RuntimeError('PRIVATE_DB_ERROR')
    assert register_hooks(SimpleNamespace(), store=Broken()) is None


def test_source_wraps_unexpected_storage_errors():
    class Broken:
        def db(self, **kwargs):
            raise RuntimeError('PRIVATE_DB_ERROR')
    with pytest.raises(SourceError) as exc:
        poll(Broken(), 1000)
    assert 'PRIVATE_DB_ERROR' not in str(exc.value)


def test_hook_median_informational(observer, record_property):
    store, recorder, now = observer
    # Warm schema/pages; measure actual WAL commits, not an in-memory mock.
    recorder.callbacks['post_tool_call'](status='ok')
    durations = []
    for _ in range(300):
        started = time.perf_counter_ns()
        recorder.callbacks['post_tool_call'](status='ok')
        durations.append((time.perf_counter_ns() - started) / 1_000_000)
    median = statistics.median(durations)
    record_property('hook_median_ms', median)
    print(f'\nhook median: {median:.4f} ms (informational; target <=1 ms)')
    assert recorder.dropped == 0
