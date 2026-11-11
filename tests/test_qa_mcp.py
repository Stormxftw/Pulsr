"""MCP QA matrix. All connector calls are controlled fakes, never user services."""
import copy
import json

import pytest

from test_mcp import connector, definition, poll
from pulse_rings import builder_mcp, mcp_access, templates
from pulse_rings.engine import Engine
from pulse_rings.sources.base import SourceError


@pytest.mark.parametrize('body,expected', [
    ({'nested': [{'count': 0}]}, 0),
    ({'nested': [{'count': 1234567890123}]}, 1234567890123),
    ({'nested': [{'count': -2.5}]}, -2.5),
    ({'nested': [{'count': '123'}]}, None),
    ({'nested': [{'count': True}]}, None),
    ({'nested': [{'count': None}]}, None),
    ({'nested': []}, None),
    ({'nested': [{'count': 1e309}]}, None),
])
def test_six_metric_partial_mapping(connector, body, expected):
    body.update({'a/b': {'~': [[12.25]]}, '零': 0})
    connector[0].call_mcp = lambda *a, **kw: {'ok': True, 'structuredContent': body, 'result': 'prose ignored'}
    result = poll(connector, definition(metrics={
        'main': '/nested/0/count', 'escaped': '/a~1b/~0/0/0', 'zero': '/零',
        'missing': '/not-present', 'array': '/nested', 'invalidIndex': '/nested/00/count'}))
    assert result.sample['metrics'] == {'main': expected, 'escaped': 12.25, 'zero': 0,
                                       'missing': None, 'array': None, 'invalidIndex': None}
    assert set(result.sample['unknown_reasons']) == {k for k, v in result.sample['metrics'].items() if v is None}
    assert result.sample['baselines'] == {}


@pytest.mark.parametrize('envelope', [
    {'ok': True, 'result': '{"nested":[{"count":7}]}'},  # Hermes flattens content[].text.
    {'ok': True, 'result': {'nested': [{'count': 7}]}},
    {'ok': True, 'structuredContent': {'nested': [{'count': 7}]}, 'result': 'status prose'},
])
def test_poll_and_builder_use_same_decoded_body(connector, tmp_path, envelope):
    connector[0].call_mcp = lambda *a, **kw: copy.deepcopy(envelope)
    assert poll(connector).sample['metrics']['count'] == 7
    inspected = builder_mcp.test_call(tmp_path, 'probe', 'read_metrics', {})
    assert inspected['body'] == {'nested': [{'count': 7}]}
    assert inspected['numeric'] == [{'pointer': '/nested/0/count', 'value': 7}]
    assert inspected['calls'] == 1 and inspected['persisted'] is False


@pytest.mark.parametrize('envelope', [
    {'ok': True, 'isError': True, 'result': '{"nested":[{"count":999}]}'},
    {'ok': True, 'result': 'not JSON PRIVATE_CANARY'},
    {'ok': False, 'error': 'PRIVATE_CANARY'},
])
def test_errors_never_become_metrics_or_leak(connector, envelope):
    connector[0].call_mcp = lambda *a, **kw: envelope
    with pytest.raises(SourceError) as error:
        poll(connector)
    assert 'PRIVATE_CANARY' not in str(error.value)


def test_template_preserves_exact_array_and_escaped_pointers():
    values = {'server': 'probe', 'tool': 'read_metrics', 'args': {},
              'metrics': {'count': '/nested/0/count', 'escaped': '/a~1b/~0/0/0'}}
    out = templates.from_template('mcp', values)
    assert out['ok'], out['errors']
    assert out['feeds']['main']['params'] == values
    assert out['feeds']['main']['every'] == '15m'


@pytest.mark.parametrize('block', [
    {'type': 'score', 'components': [{'metric': 'count', 'weight': 100, 'type': 'level', 'full_at': 100}]},
    {'type': 'rings', 'rings': [{'value': 'count', 'max': 100}]},
    {'type': 'bar', 'value': 'count', 'max': 100},
    {'type': 'bars', 'bars': [{'value': 'count'}, {'value': 'missing'}], 'max': 100},
    {'type': 'stat', 'value': 'count'},
    {'type': 'spark', 'value': 'count'},
])
@pytest.mark.parametrize('count', [0, None])
def test_unknown_and_real_zero_through_all_blocks(connector, tmp_path, block, count):
    connector[0].call_mcp = lambda *a, **kw: {'ok': True, 'result': {'count': count}}
    d = definition(metrics={'count': '/count', 'missing': '/missing'})
    d['title'] = ('工具 / café — ' + 'Long name ' * 6)[:60]
    d['display'] = [block]
    engine = Engine(tmp_path, clock=lambda: 1000, jitter=lambda: 0)
    engine.activate(d)
    assert engine.poll_one_due()
    rendered = engine.status()['pulses'][0]['display'][0]
    if block['type'] == 'score':
        assert rendered['ring']['unknown'] is (count is None)
    elif block['type'] in ('rings', 'bar', 'bars'):
        assert rendered['items'][0]['unknown'] is (count is None)
        if count == 0:
            assert rendered['items'][0]['value_text'] == '0'
            assert rendered['items'][0]['fill'] == 0
    elif block['type'] == 'stat':
        assert rendered['unknown'] is (count is None)
        if count == 0:
            assert rendered['value_text'] == '0'
    else:
        assert rendered['points'][-1]['value'] == count
    assert 'NaN' not in json.dumps(rendered, allow_nan=False)


def test_grant_and_policy_refusal_never_dispatch_or_consume_budget(connector, tmp_path, monkeypatch):
    engine = Engine(tmp_path, clock=lambda: 1000, jitter=lambda: 0)
    engine.activate(definition())
    monkeypatch.setattr(mcp_access, 'server_granted', lambda server: False)
    assert not engine.poll_one_due()
    row = engine.status()['pulses'][0]
    assert row['state'] == 'needs_mcp_grant'
    assert '"probe"' in row['mcp']['grant_message']
    assert engine.store.rows()[0]['failures'] == 0
    assert not connector[2] and engine.net.usage()['used'] == 0
    monkeypatch.setattr(mcp_access, 'server_granted', lambda server: True)
    connector[1]['read_only'] = False
    with pytest.raises(SourceError, match='not marked read-only'):
        poll(connector)
    assert not connector[2] and engine.net.usage()['used'] == 0


def test_mcp_auto_range_and_usual_learn_only_from_prior_observations(connector, tmp_path):
    clock, value = [1000], [0]
    connector[0].call_mcp = lambda *a, **kw: {'ok': True, 'result': {'count': value[0]}}
    d = definition(metrics={'count': '/count'})
    d['every'] = '30m'
    d['display'] = [{'type': 'bar', 'value': 'count'},
                    {'type': 'bar', 'value': 'count', 'max': 'usual'},
                    {'type': 'stat', 'value': 'count', 'delta_vs': 'previous'}]
    engine = Engine(tmp_path, clock=lambda: clock[0], jitter=lambda: 0)
    engine.activate(d)
    rows = []
    for ts, count in [(1000, 0), (2800, 20), (4600, 30), (6400, 40)]:
        clock[0], value[0] = ts, count
        assert engine.poll_one_due()
        rows.append(engine.status()['pulses'][0]['display'])
    assert [r[0]['items'][0]['learning'] for r in rows] == [True, True, False, False]
    assert [r[0]['items'][0]['range']['samples'] for r in rows] == [1, 2, 3, 4]
    assert [r[2]['delta'] for r in rows] == [None, 20, 10, 10]
    assert rows[1][1]['items'][0]['fill'] is None  # Previous median is exactly zero.
    assert rows[2][1]['items'][0]['max'] == 20  # Twice prior median (0, 20).
    assert rows[3][1]['items'][0]['max'] == 40  # Twice prior median (0, 20, 30).
    assert 'NaN' not in json.dumps(rows, allow_nan=False)
