"""Inverted Opus N2/N3 probes: closes survive both kinds of contention."""
import sqlite3
from types import SimpleNamespace

import pytest

from pulse_rings.hooks import register_hooks
from pulse_rings.sources.hermes import HermesActivity
from pulse_rings.spec import normalize
from pulse_rings.store import Store

NOW = 1_794_000_000.0
DEFINITION = normalize({'pulse': 1, 'title': 'Hermes', 'source': {'kind': 'hermes.activity'}})


def rig(tmp_path):
    store = Store(tmp_path)
    hooks = {}
    recorder = register_hooks(SimpleNamespace(register_hook=lambda n, cb: hooks.update({n: cb})),
                              store=store, clock=lambda: NOW)
    return store, hooks, recorder


@pytest.mark.parametrize('opening,closing,kwargs,metric', [
    ('pre_llm_call', 'on_session_end', {'session_id': 's'}, 'turns_running'),
    ('on_human_input_request', 'on_human_input_resolved', {'kind': 'clarify', 'request_id': 'r'}, 'waiting_on_you'),
    ('subagent_start', 'subagent_stop', {'child_session_id': 'c'}, 'subagents_running'),
])
@pytest.mark.parametrize('contention', ['sqlite', 'callback'])
def test_closes_eventually_flush_after_contention(tmp_path, opening, closing, kwargs, metric, contention):
    store, hooks, recorder = rig(tmp_path)
    try:
        hooks[opening](**kwargs)
        if contention == 'sqlite':
            holder = sqlite3.connect(tmp_path / 'pulse.sqlite3', isolation_level=None)
            holder.execute('BEGIN IMMEDIATE')
        else:
            recorder.lock.acquire()
        try:
            assert hooks[closing](**kwargs) is None
        finally:
            if contention == 'sqlite':
                holder.rollback()
                holder.close()
            else:
                recorder.lock.release()
        sample = HermesActivity(store).poll(DEFINITION, None, {}, now=NOW + 1, net=None).sample
        assert sample['metrics'][metric] == 0
        assert not recorder.pending_closes
        assert recorder.db.execute('PRAGMA busy_timeout').fetchone()[0] == 1
    finally:
        recorder.close()


def test_pending_close_flushes_on_next_record(tmp_path):
    store, hooks, recorder = rig(tmp_path)
    try:
        hooks['pre_llm_call'](session_id='s')
        recorder.lock.acquire()
        try:
            hooks['on_session_end'](session_id='s')
        finally:
            recorder.lock.release()
        hooks['post_tool_call'](status='ok')
        assert recorder.db.execute('SELECT count(*) FROM hermes_open').fetchone()[0] == 0
        assert not recorder.pending_closes
    finally:
        recorder.close()


def test_timeout_is_counted_as_error_not_unknown(tmp_path):
    store, hooks, recorder = rig(tmp_path)
    try:
        hooks['post_tool_call'](status='timeout')
        sample = HermesActivity(store).poll(DEFINITION, None, {}, now=NOW + 3700, net=None).sample
        # Insert in the complete window rather than accidentally testing expiry.
        recorder.db.execute('UPDATE hermes_events SET ts=?', (NOW + 3700,))
        sample = HermesActivity(store).poll(DEFINITION, None, {}, now=NOW + 3700, net=None).sample
        assert sample['metrics']['tool_errors_1h'] == 1
        assert 'tool_errors_1h' not in sample['unknown_reasons']
    finally:
        recorder.close()
