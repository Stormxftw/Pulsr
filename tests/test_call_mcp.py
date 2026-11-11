"""Public call_mcp contract: no ambient grants, raw error leakage or partial parsing."""
import json
import sys
from types import SimpleNamespace

import pytest
from test_mcp import connector, poll, definition
from pulse_rings import mcp_access
from pulse_rings.engine import Engine


def test_structured_content_preferred_without_text_decode(connector):
    connector[0].call_mcp = lambda *a, **kw: {'ok': True, 'result': 'not json',
        'structuredContent': {'nested': [{'count': 19}]}}
    assert poll(connector).sample['metrics'] == {'count': 19}


def test_truncation_never_parses_even_complete_looking_prefix(connector):
    connector[0].call_mcp = lambda *a, **kw: {'ok': True, 'result': {'nested': [{'count': 99}]},
        'structuredContent': {'nested': [{'count': 98}]}, 'truncated': True}
    sample = poll(connector).sample
    assert sample['metrics'] == {'count': None}
    assert 'truncated' in sample['unknown_reasons']['count']


def test_permission_error_is_grant_state_without_backoff(connector, tmp_path):
    def refused(*a, **kw):
        raise PermissionError('SECRET_CANARY')
    connector[0].call_mcp = refused
    e = Engine(tmp_path, clock=lambda: 1000, jitter=lambda: 0)
    e.activate(definition())
    e.poll_one_due()
    stored = e.store.rows()[0]
    assert stored['failures'] == stored['backoff_until'] == 0
    row = e.status()['pulses'][0]
    assert row['state'] == 'needs_mcp_grant'
    assert 'plugins.entries.pulse-rings.mcp_allowlist' in row['mcp']['grant_message']
    assert 'CANARY' not in json.dumps(row)


def test_missing_grant_does_not_block_approval_or_call_tool(connector, tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_access, 'server_granted', lambda server: False)
    e = Engine(tmp_path, clock=lambda: 1000, jitter=lambda: 0)
    draft = e.create_draft(definition())
    disclosure = e.draft(draft['draft_id'])['disclosure']['feeds'][0]['mcp']
    assert disclosure['hermes_allowed'] is False and disclosure['read_only'] is True
    assert 'Not yet allowed' in disclosure['grant_message']
    e.decide_draft(draft['draft_id'], 'approve', via='command')
    assert e.status()['pulses'][0]['state'] == 'needs_mcp_grant'
    e.poll_one_due()
    assert connector[2] == [] and e.store.rows()[0]['failures'] == 0


def test_grant_accessor_reads_entry_not_plugin_settings(monkeypatch):
    monkeypatch.setitem(sys.modules, 'hermes_cli.config', SimpleNamespace(load_config=lambda: {
        'plugins': {'entries': {'pulse-rings': {'mcp_allowlist': ['probe'], 'settings': {'mcp_allowlist': ['wrong']}}}}}))
    assert mcp_access.server_granted('probe') is True
    assert mcp_access.server_granted('wrong') is False


def test_builder_permission_error_explains_grant(connector, tmp_path):
    from pulse_rings.builder_mcp import test_call, TestCallError
    connector[0].call_mcp = lambda *a, **kw: (_ for _ in ()).throw(PermissionError('SECRET_CANARY'))
    with pytest.raises(TestCallError) as error:
        test_call(tmp_path, 'probe', 'read_metrics', {})
    assert error.value.status == 403
    assert 'plugins.entries.pulse-rings.mcp_allowlist' in str(error.value)
    assert 'CANARY' not in str(error.value)


@pytest.mark.parametrize('outer', [
    {'ok': False, 'error': 'PRIVATE_CANARY'},
    {'ok': True, 'result': '{"error":"PRIVATE_CANARY"}'},
    {'ok': True, 'structuredContent': {'isError': True, 'private': 'PRIVATE_CANARY'}},
    {'ok': True, 'result': 'NaN'}, {'ok': True, 'result': '1e999'},
])
def test_new_envelope_failures_are_static(connector, outer):
    from pulse_rings.sources.base import SourceError
    connector[0].call_mcp = lambda *a, **kw: outer
    with pytest.raises(SourceError) as error:
        poll(connector)
    assert 'PRIVATE_CANARY' not in str(error.value)


def test_null_structured_content_is_not_fallback(connector):
    connector[0].call_mcp = lambda *a, **kw: {'ok': True, 'result': {'nested': [{'count': 9}]},
                                           'structuredContent': None}
    assert poll(connector).sample['metrics'] == {'count': None}


def test_grant_revocation_recovery_does_not_store_false_zero(connector, tmp_path, monkeypatch):
    clock, allowed = [1000], [False]
    monkeypatch.setattr(mcp_access, 'server_granted', lambda server: allowed[0])
    e = Engine(tmp_path, clock=lambda: clock[0], jitter=lambda: 0)
    e.activate(definition())
    assert not e.poll_one_due()
    assert e.status()['pulses'][0]['state'] == 'needs_mcp_grant'
    assert e.store.history('mcp-counts') == []
    allowed[0] = True
    clock[0] += 61
    assert e.poll_one_due()
    assert e.status()['pulses'][0]['state'] != 'needs_mcp_grant'
    assert e.status()['pulses'][0]['capsule']['label'] == '7'
    allowed[0] = False
    assert e.status()['pulses'][0]['state'] == 'needs_mcp_grant'


def test_explicit_feed_wait_state_is_independent_of_read_only(connector, tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_access, 'server_granted', lambda server: False)
    e = Engine(tmp_path, clock=lambda: 1000, jitter=lambda: 0)
    e.activate({'pulse': 1, 'title': 'Explicit MCP',
        'feeds': {'counts': {'kind': 'mcp.tool', 'params': definition()['source']['params']}},
        'display': [{'type': 'stat', 'value': 'counts.count'}]})
    assert not e.poll_one_due()
    row = e.status()['pulses'][0]
    assert row['state'] == row['feeds'][0]['state'] == 'needs_mcp_grant'
    assert row['feeds'][0]['mcp']['read_only'] is True
    assert row['feeds'][0]['mcp']['hermes_allowed'] is False
    assert e.store.feed_rows('explicit-mcp')['counts']['failures'] == 0
    assert not connector[2]
