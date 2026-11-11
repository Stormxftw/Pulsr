"""Review-3 P1-1: real draft reads disclose every feed and fresh MCP policy."""
from contextvars import copy_context
from types import SimpleNamespace
import json

import pytest

from pulse_rings import mcp_access
from pulse_rings.engine import Engine


def definition():
    return {'pulse': 1, 'id': 'disclosures', 'title': 'All sources', 'icon': {'url': 'https://icons.example.org/p.png'},
        'feeds': {
            'http': {'kind': 'http_json', 'every': '5m', 'params': {'url': 'https://example.org/sensitive/export?all=true', 'metrics': {'count': '/count'}}},
            'connector': {'kind': 'mcp.tool', 'every': '15m', 'params': {'server': 'private', 'tool': 'read_data', 'args': {'padding': 'x' * 600, 'tail': '<not-hidden>'}, 'metrics': {'count': '/count'}}},
            'second': {'kind': 'mcp.tool', 'every': '30m', 'params': {'server': 'other', 'tool': 'read_data', 'args': {}, 'metrics': {'count': '/count'}}}},
        'display': [{'type': 'bar', 'value': 'http.count'}]}


def test_real_draft_read_has_complete_per_feed_fresh_policy(tmp_path, monkeypatch):
    flags = {'exists': True, 'connected': True, 'read_only': True, 'requires_approval': False}
    calls = []
    ctx = SimpleNamespace(tool_info=lambda name: (calls.append(name) or dict(flags)))
    monkeypatch.setitem(mcp_access._BINDINGS, str(tmp_path.resolve()), (ctx, copy_context(), str(tmp_path)))
    engine = Engine(tmp_path, clock=lambda: 1000)
    id = engine.create_draft(definition(), origin={'kind': 'cron'})['draft_id']
    draft = engine.draft(id)
    disclosure = draft['disclosure']
    rows = disclosure['feeds']
    assert [r['name'] for r in rows] == ['http', 'connector', 'second']
    assert [r['req_per_hour'] for r in rows] == [12, 4, 2]
    assert [r['every'] for r in rows] == ['5m', '15m', '30m']
    assert rows[0]['target'] == 'https://example.org/sensitive/export?all=true'
    assert rows[1]['mcp']['read_only'] is True and rows[2]['mcp']['read_only'] is True
    assert json.loads(rows[1]['mcp']['args_full'])['tail'] == '<not-hidden>'
    assert disclosure['icon_hosts'] == ['icons.example.org']
    assert sum(r['req_per_hour'] for r in rows) == draft['budget']['req_per_hour']
    ctx.tool_info = lambda name: (calls.append(name) or dict(flags, read_only=flags['read_only'] and name != 'mcp__other__read_data'))
    separate = engine.draft(id)['disclosure']['feeds']
    assert separate[1]['mcp']['read_only'] is True and separate[2]['mcp']['read_only'] is False
    flags['read_only'] = False
    assert all(r['mcp']['read_only'] is False for r in engine.draft(id)['disclosure']['feeds'][1:])
    assert set(calls) == {'mcp__private__read_data', 'mcp__other__read_data'}
    assert engine.store.draft(id, 1000).get('disclosure') is None  # ephemeral, never trusted persistence


@pytest.mark.parametrize('kind,params,target', [
    ('github.repo', {'repo': 'NousResearch/hermes-agent'}, 'NousResearch/hermes-agent'),
    ('github.search', {'repo': 'NousResearch/hermes-agent', 'type': 'pr', 'title_contains': 'security', 'label': 'bug'}, 'NousResearch/hermes-agent'),
    ('discord.invite', {'invite': 'nousresearch'}, 'nousresearch'),
    ('hermes.activity', {'scope': 'profile'}, 'this profile'),
])
def test_all_kind_targets_and_params(tmp_path, kind, params, target):
    engine = Engine(tmp_path, clock=lambda: 1000)
    id = engine.create_draft({'pulse': 1, 'title': 'Legacy', 'source': {'kind': kind, 'params': params}}, origin={'kind': 'cron'})['draft_id']
    draft = engine.draft(id)
    row = draft['disclosure']['feeds'][0]
    assert row['name'] == 'main' and row['kind'] == kind and row['target'] == target
    assert row['params'].items() >= params.items()
    assert row['every'] and isinstance(row['req_per_hour'], (int, float))
    assert isinstance(row['hosts'], list)


def test_unavailable_connector_is_per_feed_and_never_trusted_from_definition(tmp_path):
    engine = Engine(tmp_path, clock=lambda: 1000)
    id = engine.create_draft(definition(), origin={'kind': 'cron'})['draft_id']
    rows = engine.draft(id)['disclosure']['feeds']
    assert all(r['mcp']['read_only'] is False and r['mcp']['reason'] for r in rows[1:])
