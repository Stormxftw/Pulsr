"""Offline authoring contracts: no source values or runtime authority required."""
import copy
import json
from unittest.mock import Mock

import pytest

from pulse_rings.authoring import RunContexts, catalog, register_tools
from pulse_rings.spec import normalize, budget, validate
from test_authoring import Context


def definition():
    return {'pulse': 1, 'title': 'Store health', 'feeds': {
        'limits': {'kind': 'mcp.tool', 'params': {'server': 'ebay', 'tool': 'ebay_status',
            'metrics': {'used': '/used', 'limit': '/limit'}}},
        'orders': {'kind': 'mcp.tool', 'every': '30m', 'params': {'server': 'ebay', 'tool': 'ebay_orders',
            'metrics': {'open': '/open', 'late': '/late'}}}},
        'display': [{'type': 'bars', 'bars': [{'value': 'orders.open'},
            {'value': 'orders.late', 'label': 'Late', 'zones': {'warn': 2, 'crit': 5}}]}],
        'icon': {'url': 'https://example.org/store.png'}, 'theme': {'accent': '#ABC'}}


def tools(engine=None):
    ctx = Context()
    factory = Mock(return_value=engine, side_effect=None if engine else AssertionError('No engine/store/network'))
    origins = RunContexts(ctx)
    register_tools(ctx, origins, factory)
    return ctx, origins, factory


def test_catalog_toolkit_bound_and_valid_examples():
    result = catalog()
    assert set(result['blocks']) == {'score', 'rings', 'bar', 'bars', 'stat', 'spark'}
    for kind, block in result['blocks'].items():
        assert all(key in block for key in ('fields', 'limits', 'defaults', 'example'))
        d = {'pulse': 1, 'title': 'Example', 'source': {'kind': 'github.repo',
             'params': {'repo': 'NousResearch/hermes-agent'}}, 'display': [block['example']]}
        assert not validate(d), (kind, validate(d))
    assert result['scales']['defaults'] == {'min': 0, 'max': 'auto', 'auto_window': '7d'}
    assert result['scales']['auto']['minimum_samples'] == 3
    assert result['scales']['auto']['minimum_span_seconds'] == 3600
    assert result['style']['tokens'] == ['accent', 'ok', 'warn', 'crit', 'muted', 'ink']
    assert set(result['style']['scopes']) >= {'theme', 'item', 'rings', 'bar', 'bars', 'stat', 'spark', 'score'}
    assert result['feeds']['max'] == 3 and result['feeds']['max_bindings'] == 8
    assert result['icons']['network_rules']
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= result['response_max_bytes'] == 65536
    result['blocks']['bar']['example']['value'] = 'broken'
    assert catalog()['blocks']['bar']['example']['value'] != 'broken'


@pytest.mark.parametrize('query,slug', [('ebay', 'ebay'), ('GitHub', 'github'), ('githb', 'github'), ('Hugging Face', 'huggingface')])
def test_brand_search(query, slug):
    ctx, _, factory = tools()
    result = json.loads(ctx.tools['pulse_rings_catalog']['handler']({'brand_query': query}))
    assert slug in [r['slug'] for r in result['brands']]
    assert len(result['brands']) <= 10
    assert all(set(r) == {'slug', 'title'} for r in result['brands'])
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= 65536
    factory.assert_not_called()


@pytest.mark.parametrize('args', [{'brand_query': 5}, {'brand_query': 'a' * 81}, {'brand_query': ' ' * 81 + 'a'}, {'brand_query': ' '}, {'brand_query': None}, {'origin': 'session'}])
def test_catalog_rejects_bad_args(args):
    ctx, _, _ = tools()
    assert json.loads(ctx.tools['pulse_rings_catalog']['handler'](args))['status'] == 'invalid'


@pytest.mark.parametrize('origin', ['session', 'cron', 'subagent', 'kanban', 'unknown'])
def test_layout_check_is_offline_and_origin_independent(origin, monkeypatch):
    ctx, contexts, factory = tools()
    if origin == 'cron': ctx.cron = object()
    if origin == 'subagent': monkeypatch.setenv('HERMES_DELEGATED_CHILD_CONTEXT', '1')
    if origin == 'kanban': monkeypatch.setenv('HERMES_KANBAN_TASK', '1')
    if origin == 'session': contexts.observe('pre_llm_call', session_id='s')
    # Any attempt to construct runtime net/store fails, even for a malformed input.
    monkeypatch.setattr('pulse_rings.net.Net', Mock(side_effect=AssertionError('No network')))
    monkeypatch.setattr('pulse_rings.store.Store', Mock(side_effect=AssertionError('No store')))
    handler = ctx.tools['pulse_rings_layout_check']['handler']
    raw = definition(); saved = copy.deepcopy(raw)
    result = json.loads(handler({'definition': raw}, session_id='s'))
    assert result['ok'] and result['errors'] == []
    assert result['normalized'] == normalize(raw) and raw == saved
    assert result['budget'] == budget(raw)
    assert len(result['blocks']) == 2
    line = result['blocks'][1]
    for text in ('bars[1]', 'Late', 'learning until 3 samples over 1h', 'warn≥2', 'crit≥5',
                 'feed orders', 'mcp.tool ebay/ebay_orders', 'every 30m'):
        assert text in line
    bad = definition(); bad['display'][0]['bars'][1]['value'] = 'order.late'
    invalid = json.loads(handler({'definition': bad}))
    assert invalid['ok'] is False
    assert any(e['path'] == '/display/0/bars/1/value' for e in invalid['errors'])
    assert 'normalized' not in invalid
    factory.assert_not_called()


def test_layout_check_all_blocks_and_warnings():
    ctx, _, _ = tools(); handler = ctx.tools['pulse_rings_layout_check']['handler']
    for block in catalog()['blocks'].values():
        d = {'pulse': 1, 'title': 'Example', 'source': {'kind': 'github.repo',
             'params': {'repo': 'NousResearch/hermes-agent'}}, 'display': [block['example']]}
        result = json.loads(handler({'definition': d}))
        assert result['ok'] and result['blocks']
        assert all(isinstance(line, str) for line in result['blocks'])
    d = definition()
    d['display'] = [{'type': 'rings', 'rings': [{'value': 'limits.used'}] * 3}]
    d['theme'] = {'surface': '#fff', 'accent': '#ffffff80'}
    result = json.loads(handler({'definition': d}))
    text = ' '.join(result['warnings'])
    assert 'limits.limit' in text and 'hero' in text and '3:1' in text
    for malformed in ({}, {'definition': d, 'approve': True}, {'definition': '{bad'}):
        assert json.loads(handler(malformed))['ok'] is False


def test_propose_validates_before_runtime_and_discloses_every_feed():
    engine = Mock()
    engine.create_draft.return_value = {'card': '::pulse-rings-draft{id="pd_test"}', 'preview_calls': 0}
    ctx, _, factory = tools(engine)
    handler = ctx.tools['pulse_rings_propose']['handler']
    d = definition()
    result = json.loads(handler({'definition': d, 'note': 'Scale follows source limit.'}))
    assert engine.create_draft.call_args.args[0] == normalize(d)
    assert result['card'] == '::pulse-rings-draft{id="pd_test"}'
    assert [f['name'] for f in result['feeds']] == ['limits', 'orders']
    for text in ('limits', 'mcp.tool', 'ebay/ebay_status', '15m', '4 req/h',
                 'orders', 'ebay/ebay_orders', '30m', '2 req/h', 'Total: 6 req/h', 'example.org', 'one-off'):
        assert text in result['summary']
    bad = definition(); bad['display'][0]['bars'][0]['value'] = 'orders.missing'
    invalid = json.loads(handler({'definition': bad}))
    assert {'path': '/display/0/bars/0/value', 'message': "Unknown metric 'missing' for feed 'orders'."} in invalid['errors']
    assert factory.call_count == 1


def test_propose_source_display_roundtrip_real_engine(tmp_path):
    from pulse_rings.engine import Engine
    e = Engine(tmp_path)
    e.fetch = Mock(side_effect=AssertionError('No MCP preview'))
    ctx, _, _ = tools(e)
    d = definition()
    d['source'] = d.pop('feeds')['limits']
    d['display'] = [{'type': 'bar', 'value': 'used', 'max': 'limit'}]
    result = json.loads(ctx.tools['pulse_rings_propose']['handler']({'definition': d}))
    assert result['preview_calls'] == 0
    assert e.draft(result['draft_id'])['definition'] == normalize(d)
    e.fetch.assert_not_called()


def test_propose_multifeed_roundtrip_real_engine(tmp_path, monkeypatch):
    """Integration gate: requires WP9-engine's multi-feed draft implementation."""
    from pulse_rings.engine import Engine
    e = Engine(tmp_path)
    e.fetch = Mock(side_effect=AssertionError('No MCP preview'))
    poll = Mock(side_effect=AssertionError('No MCP calls before approval'))
    monkeypatch.setattr('pulse_rings.sources.mcp.McpToolSource.poll', poll)
    ctx, contexts, _ = tools(e)
    contexts.observe('pre_llm_call', session_id='interactive')
    d = definition()
    result = json.loads(ctx.tools['pulse_rings_propose']['handler']({'definition': d}, session_id='interactive'))
    assert result['preview_calls'] == 0
    saved = e.draft(result['draft_id'])
    assert saved['definition'] == normalize(d)
    assert saved['budget'] == result['budget'] == budget(d)
    assert not e.store.rows()  # Still pending, never activation.
    e.fetch.assert_not_called()
    poll.assert_not_called()


@pytest.mark.parametrize('block,path', [
    ({'type': 'score', 'components': [{'metric': 'bad', 'weight': 100, 'type': 'delta'}]}, '/display/0/components/0/metric'),
    ({'type': 'rings', 'rings': [{'value': 'bad'}]}, '/display/0/rings/0/value'),
    ({'type': 'bar', 'value': 'stars', 'min': 10, 'max': 5}, '/display/0/max'),
    ({'type': 'bars', 'bars': [{'value': 'stars', 'max': 5}, {'value': 'forks'}]}, '/display/0/bars/0'),
    ({'type': 'stat', 'value': 'stars', 'decimals': 4}, '/display/0/decimals'),
    ({'type': 'spark', 'value': 'stars', 'points': 49}, '/display/0/points'),
])
def test_layout_check_error_paths_every_block(block, path):
    ctx, _, _ = tools()
    d = {'pulse': 1, 'title': 'Errors', 'source': {'kind': 'github.repo',
         'params': {'repo': 'NousResearch/hermes-agent'}}, 'display': [block]}
    result = json.loads(ctx.tools['pulse_rings_layout_check']['handler']({'definition': d}))
    assert result['ok'] is False
    assert any(e['path'] == path for e in result['errors'])
    assert all(set(e) == {'path', 'message'} for e in result['errors'])


@pytest.mark.parametrize('scales,expected', [
    ({'min': 0, 'max': 100}, '0–100'),
    ({'min': 'auto', 'max': 'auto', 'auto_window': '1h'}, 'window 1h'),
    ({'max': 'usual'}, '2 × prior median'),
    ({'max': 'limits.limit'}, '0–limits.limit'),
])
def test_layout_ranges_and_independent_bars(scales, expected):
    ctx, _, _ = tools()
    d = definition()
    d['display'] = [{'type': 'bars', 'scale': 'independent', 'bars': [
        dict(value='limits.used', **scales), {'value': 'orders.late', 'max': 100,
            'zones': {'warn': 20, 'crit': 10, 'direction': 'down'}}]}]
    result = json.loads(ctx.tools['pulse_rings_layout_check']['handler']({'definition': d}))
    assert result['ok']
    assert expected in result['blocks'][0]
    assert 'warn≤20 crit≤10' in result['blocks'][1]
    if scales.get('max') == 'limits.limit':
        assert not result['warnings']


@pytest.mark.parametrize('theme,warns', [
    ({'surface': '#fff', 'text': '#000'}, False),
    ({'surface': '#fff', 'text': '#fff'}, True),
    ({'surface': '#ffffff80', 'text': '#fff'}, False),
    ({'surface': 'muted', 'text': '#fff'}, False),
    ({'surface': '#fff', 'accent': '#00000000'}, True),
])
def test_contrast_no_guessed_surface_or_tokens(theme, warns):
    ctx, _, _ = tools(); d = definition(); d['theme'] = theme
    result = json.loads(ctx.tools['pulse_rings_layout_check']['handler']({'definition': d}))
    assert any('3:1' in w for w in result['warnings']) is warns


def test_catalog_bound_many_matches_and_schema_required():
    ctx, _, _ = tools()
    payload = ctx.tools['pulse_rings_catalog']['handler']({'brand_query': 'a'})
    result = json.loads(payload)
    assert len(result['brands']) == 10 and len(payload.encode()) <= 65536
    assert all(set(brand) == {'slug', 'title'} for brand in result['brands'])
    for tool in ('pulse_rings_layout_check', 'pulse_rings_propose'):
        schema = ctx.tools[tool]['schema']['parameters']
        assert schema['required'] == ['definition'] and schema['additionalProperties'] is False
    assert 'brand_query' in ctx.tools['pulse_rings_catalog']['schema']['parameters']['properties']


def test_skill_examples_are_valid_checked_data():
    from pathlib import Path
    import re
    text = (Path(__file__).resolve().parents[1] / 'skills/authoring/SKILL.md').read_text(encoding='utf-8')
    examples = [json.loads(s) for s in re.findall(r'```json\n(.*?)\n```', text, re.S)]
    assert len(examples) == 4
    ctx, _, _ = tools()
    for d in examples:
        result = json.loads(ctx.tools['pulse_rings_layout_check']['handler']({'definition': d}))
        assert result['ok'], result['errors']
    assert examples[0]['source']['kind'] == 'web.feed' and budget(examples[0])['req_per_hour'] == 2
    assert budget(examples[1])['req_per_hour'] == 6
    assert 'version: 0.3.0' in text and 'replacement draft' in text
    assert text.index('pulse_rings_layout_check') < text.index('pulse_rings_propose')


def test_proposal_budget_text_preserves_fractional_allocation():
    from pulse_rings.layout import proposal_disclosure
    d = normalize({'pulse': 1, 'title': 'GitHub fractional budget', 'source': {
        'kind': 'github.search', 'params': {'repo': 'NousResearch/hermes-agent', 'type': 'pr'}}})
    result = proposal_disclosure(d)
    exact = str(result['budget']['req_per_hour'])
    assert f'Total: {exact} req/h' in result['summary']
    assert result['feeds'][0]['req_per_hour'] == result['budget']['req_per_hour']
