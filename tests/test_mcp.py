"""MCP definitions and adapter security boundary; no configured live tools."""
import copy
import json
import time
from types import SimpleNamespace

import pytest

from pulse_rings.spec import normalize, validate, budget


def definition(**params):
    return {'pulse': 1, 'title': 'MCP counts', 'source': {'kind': 'mcp.tool', 'params': {
        'server': 'probe', 'tool': 'read_metrics', 'args': {}, 'metrics': {'count': '/nested/0/count'}, **params}}}


from contextlib import nullcontext
from contextvars import copy_context
import threading

from pulse_rings import mcp_access
from pulse_rings.engine import Engine
from pulse_rings.sources import mcp
from pulse_rings.sources.base import SourceError, Deferred
from pulse_rings.net import Net
from pulse_rings.store import Store


@pytest.fixture
def connector(tmp_path, monkeypatch):
    calls = []
    flags = {'exists': True, 'connected': True, 'read_only': True, 'requires_approval': False}
    ctx = SimpleNamespace(tool_info=lambda name: flags, call_mcp=lambda server, tool, args, *, timeout: (
        calls.append((server, tool, args, timeout)) or {'ok': True, 'result': json.dumps({'nested': [{'count': 7}], 'private': 'RESULT_CANARY'})}))
    monkeypatch.setitem(mcp_access._BINDINGS, str(tmp_path.resolve()), (ctx, copy_context(), str(tmp_path)))
    monkeypatch.setattr(mcp_access, 'unattended_scope', nullcontext)
    monkeypatch.setattr(mcp_access, 'server_granted', lambda server: True, raising=False)
    net = Net(Store(tmp_path), clock=lambda: 1000)
    return ctx, flags, calls, mcp.McpToolSource(tmp_path), net


def poll(connector, d=None):
    return connector[3].poll(normalize(d or definition()), None, {}, now=1000, net=connector[4])


def test_numeric_pointer_and_no_raw_leak(connector):
    result = poll(connector)
    assert result.sample['metrics'] == {'count': 7}
    assert result.state == result.metadata == {}
    assert 'RESULT_CANARY' not in repr(result)
    assert connector[2] == [('probe', 'read_metrics', {}, 8)]
    assert connector[4].usage()['used'] == 1


@pytest.mark.parametrize('field,reason', [('exists', 'not found'), ('connected', 'not connected'),
    ('read_only', 'not marked read-only'), ('requires_approval', 'safety unavailable')])
def test_fail_closed_before_dispatch(connector, field, reason):
    connector[1][field] = field == 'requires_approval'
    with pytest.raises(SourceError, match=reason):
        poll(connector)
    assert connector[2] == []
    assert connector[4].usage()['used'] == 0


@pytest.mark.parametrize('flags', [{}, {'read_only': 1}, None, {'read_only': True}])
def test_unknown_metadata_is_not_permission(connector, flags):
    connector[0].tool_info = lambda name: flags
    with pytest.raises(SourceError):
        poll(connector)
    assert not connector[2]


@pytest.mark.parametrize('raw', [
    {'ok': False, 'error': 'SECRET_CANARY'}, '{"result":"{\\"error\\":\\"SECRET_CANARY\\"}"}',
    '{"result":"NaN"}', '{"result":"Infinity"}', '{"result":"1e999"}',
    '{"isError":true,"result":"{}"}', '{"result":"not JSON SECRET_CANARY"}',
    '[]', '{}', 'SECRET_CANARY' + 'a' * mcp.OUTPUT_LIMIT, '{', None,
], ids=lambda raw: 'oversize' if isinstance(raw, str) and len(raw) > 100 else repr(raw))
def test_malformed_oversize_and_error_results_are_sanitized(connector, raw):
    def host_result(*a, **kw):
        if isinstance(raw, str) and raw.startswith('{'):
            try:
                value = json.loads(raw)
                if isinstance(value, dict):
                    return {'ok': True, **value}
            except ValueError:
                pass
        return raw
    connector[0].call_mcp = host_result
    with pytest.raises(SourceError) as error:
        poll(connector)
    assert 'SECRET_CANARY' not in str(error.value)
    assert len(str(error.value)) < 150


@pytest.mark.parametrize('value', [True, False, None, '7', {}, [], 10 ** 400])
def test_non_numbers_remain_unknown(connector, value):
    connector[0].call_mcp = lambda *a, **kw: {'ok': True, 'result': {'nested': [{'count': value}]}}
    result = poll(connector)
    assert result.sample['metrics']['count'] is None
    assert 'finite number' in result.sample['unknown_reasons']['count']


def test_missing_and_escaped_nested_pointers(connector):
    connector[0].call_mcp = lambda *a, **kw: {'ok': True, 'result': {'a/b': {'~': [0, 2.5]}}}
    result = poll(connector, definition(metrics={'yes': '/a~1b/~0/1', 'no': '/not-here'}))
    assert result.sample['metrics'] == {'yes': 2.5, 'no': None}


def test_no_context_is_honestly_unavailable(tmp_path):
    source = mcp.McpToolSource(tmp_path)
    with pytest.raises(SourceError, match='unavailable here'):
        source.poll(normalize(definition()), None, {}, now=1000, net=None)
    assert mcp.disclosure(normalize(definition()), tmp_path)['read_only'] is False


def test_local_ceiling_deferred_without_dispatch(connector, monkeypatch):
    def defer(*a):
        raise Deferred('Local pacing', 429, 2)
    monkeypatch.setattr(connector[4], 'reserve', defer)
    with pytest.raises(Deferred):
        poll(connector)
    assert not connector[2]


def test_timeout_no_duplicate_worker_or_late_storage(connector, monkeypatch):
    started, finish = threading.Event(), threading.Event()
    def hung(*args, **kw):
        started.set(); finish.wait(3)
        return {'ok': True, 'result': {'nested': [{'count': 999}]}}
    connector[0].call_mcp = hung
    monkeypatch.setattr(mcp, 'TIMEOUT', .05)
    start = time.monotonic()
    try:
        with pytest.raises(SourceError, match='timed out'):
            poll(connector)
        assert started.is_set() and time.monotonic() - start < .5
        with pytest.raises(Deferred, match='still in flight'):
            poll(connector)
        assert connector[4].usage()['used'] == 1
    finally:
        finish.set()
        for _ in range(100):
            with mcp._LOCK:
                if not mcp._INFLIGHT: break
            time.sleep(.005)
    assert connector[4].store.history('mcp-counts') == []


@pytest.mark.parametrize('origin', ['session', 'cron', 'subagent', 'kanban', 'unattended'])
def test_no_preapproval_dispatch_even_interactive(connector, tmp_path, origin):
    e = Engine(tmp_path, clock=lambda: 1000, jitter=lambda: 0)
    d = e.create_draft(definition(), origin={'kind': origin})
    assert d['preview_state'] == 'after_approval' and d['preview_calls'] == 0
    assert not e.store.rows() and not connector[2]
    e.status(poll=True)
    assert not connector[2]


def test_engine_approval_poll_cached_status_and_failure_backoff(connector, tmp_path):
    clock = [1000]
    e = Engine(tmp_path, clock=lambda: clock[0], jitter=lambda: 0)
    draft = e.create_draft(definition())
    e.decide_draft(draft['draft_id'], 'approve', via='command')
    clock[0] += 2  # Frozen activation seam's initial pacing delay.
    assert e.net.usage()['used'] == 0, json.dumps(e.net.usage())
    assert e.poll_one_due(), json.dumps({'rows': e.store.rows(), 'calls': connector[2], 'usage': e.net.usage()})
    row = e.status(poll=False)['pulses'][0]
    assert row['capsule']['label'] == '7' and row['mcp']['read_only'] is True
    assert row['mcp']['server'] == 'probe'
    for field in ('source_state', 'metadata', 'error'):
        assert 'RESULT_CANARY' not in str(e.store.rows()[0][field])
    assert 'RESULT_CANARY' not in json.dumps(e.store.history(row['id']))
    e.status(poll=False); assert len(connector[2]) == 1
    clock[0] += 900
    connector[0].call_mcp = lambda *args, **kw: {'ok': False, 'error': 'SECRET_CANARY'}
    assert e.poll_one_due() is False
    stored = e.store.rows()[0]
    assert stored['failures'] == 1 and stored['next_due'] >= clock[0] + 3600
    assert 'SECRET_CANARY' not in json.dumps(e.status(poll=False))
    assert e.status()['pulses'][0]['capsule']['label'] == '7'


def test_engine_deferred_does_not_increment_failure(connector, tmp_path):
    e = Engine(tmp_path, clock=lambda: 1000, jitter=lambda: 0, ceiling=1)
    d = definition(); d['every'] = '1h'
    e.activate(d)
    e.net.reserve('other')
    assert e.poll_one_due() is False
    row = e.store.rows()[0]
    assert row['failures'] == 0 and row['error'] is None and row['backoff_until'] == 0


def test_badge_is_host_policy_not_definition_text(connector, tmp_path):
    d = normalize(definition(**{'x-read-only': True}))
    connector[1]['read_only'] = False
    assert mcp.disclosure(d, tmp_path)['read_only'] is False
    assert 'args_display' in mcp.disclosure(d, tmp_path)


@pytest.mark.parametrize('phase', ['enter', 'exit'])
def test_scope_failure_releases_exactly_one_slot(connector, monkeypatch, phase):
    from contextlib import contextmanager
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(mcp, '_SLOTS', slots)
    finished = threading.Event()
    @contextmanager
    def broken_scope():
        try:
            if phase == 'enter':
                raise RuntimeError('SECRET_CANARY')
            yield
            raise RuntimeError('SECRET_CANARY')
        finally:
            finished.set()
    monkeypatch.setattr(mcp_access, 'unattended_scope', broken_scope)
    with pytest.raises(SourceError, match='unattended safety unavailable'):
        poll(connector)
    assert finished.wait(1)
    assert slots.acquire(timeout=1)
    assert not slots.acquire(blocking=False)
    slots.release()
    assert not mcp._INFLIGHT


def test_busy_connector_is_deferred_without_dispatch(connector, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    assert slots.acquire(blocking=False)
    monkeypatch.setattr(mcp, '_SLOTS', slots)
    try:
        with pytest.raises(Deferred, match='busy'):
            poll(connector)
        assert not connector[2] and not mcp._INFLIGHT
        assert connector[4].usage()['used'] == 0
    finally:
        slots.release()


def test_worker_start_failure_releases_slot(connector, monkeypatch):
    def fail(*args, **kw):
        raise RuntimeError('SECRET_CANARY')
    monkeypatch.setattr(threading.Thread, 'start', fail)
    with pytest.raises(SourceError, match='worker unavailable'):
        poll(connector)
    assert not mcp._INFLIGHT and not connector[2]


def test_args_and_foreign_exceptions_never_enter_persisted_results(connector):
    d = definition(args={'query': 'ARGS_CANARY'})
    assert 'ARGS_CANARY' not in repr(poll(connector, d))
    def fail(*args, **kw):
        raise SourceError('SECRET_CANARY ARGS_CANARY')
    connector[0].call_mcp = fail
    with pytest.raises(SourceError) as error:
        poll(connector, d)
    assert 'CANARY' not in str(error.value)


def test_catalog_explains_registry_name_not_ui_namespace():
    from pulse_rings.authoring import catalog
    guidance = catalog()['guidance']
    assert 'mcp__<server>__<tool>' in guidance
    assert 'server=metrics, tool=read_counts' in guidance
    assert 'No MCP preview before human approval' in guidance


def test_kind_normalizes_and_budgets():
    d = normalize(definition())
    assert d['every'] == '15m'
    assert d['capsule']['metric'] == 'count'
    assert normalize(d) == d
    assert budget(d) == {'hosts': [], 'req_per_hour': 4, 'req_per_hour_display': 4}
    aliased = definition(); aliased['source']['kind'] += '@1'
    assert normalize(aliased) == d


@pytest.mark.parametrize('params', [
    {'server': '../bad'}, {'server': 'a__b'}, {'tool': 'x/y'}, {'tool': 'x\n'},
    {'server': ''}, {'tool': 'x' * 65}, {'args': []}, {'args': {'x': 'a' * 2048}},
    {'args': {str(i): i for i in range(33)}}, {'args': {'a': {'b': {'c': {'d': {'e': {'f': {'g': 1}}}}}}}},
    {'args': {'password': 'not-a-credential'}}, {'metrics': {}}, {'metrics': {'a': '/bad~2'}},
    {'metrics': {str(i): '/x' for i in range(7)}}, {'extra': True},
])
def test_invalid_params(params):
    assert validate(definition(**params))


def test_valid_nested_args_and_extensions():
    d = definition(args={'filters': [1, True, None, {'name': 'all'}]}, **{'x-note': 'data'})
    assert normalize(d)['source']['params']['args'] == d['source']['params']['args']
    d['every'] = '299s'
    assert validate(d)


@pytest.mark.integration
def test_binding_scope_matches_real_registry_profile_overlay(tmp_path):
    """Live regression: profile-scoped MCP tools live under hermes_home_key().

    A Windows gateway that serves profiles keys its MCP overlay with the
    normalized home ('c:/users/...'); binding the raw resolved path missed it
    and every live pulse read 'MCP tool not found'. Uses the real registry in a
    subprocess because conftest stubs hermes_constants.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path
    hermes = Path(os.environ.get('HERMES_SOURCE') or Path.home() / '.hermes' / 'hermes-agent')
    if not (hermes / 'tools/registry.py').is_file():
        pytest.skip('Requires Hermes checkout (HERMES_SOURCE)')
    root = Path(__file__).resolve().parents[1]
    home = tmp_path / 'MixedCase' / 'Hermes'
    proc = subprocess.run([sys.executable, str(root / 'tests/fixtures/mcp/scope_probe.py'), str(hermes), str(root), str(home)],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ, HERMES_DISABLE_LAZY_INSTALLS='1', HERMES_HOME=str(home)))
    assert proc.returncode == 0 and 'OK' in proc.stdout, proc.stdout[-2000:] + proc.stderr[-2000:]
