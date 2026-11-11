"""Search QA: deterministic adapter -> persisted status -> renderer fixtures."""
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from pulse_rings.engine import Engine, compute_capsule, compute_ring
from pulse_rings.sources.base import SourceError
from pulse_rings.sources.github import GitHubSearch, search_url
from pulse_rings.spec import normalize, budget
from pulse_rings.templates import from_template

NOW = 1794186152


def definition(window='24h', days=14, display=False, feeds=False):
    source = {'kind': 'github.search', 'params': {'repo': 'NousResearch/hermes-agent',
        'type': 'pr', 'title_contains': 'plugin-catalog', 'window': window, 'baseline_days': days}}
    value = {'pulse': 1, 'id': 'search-qa', 'title': 'Hackathon race · catalog PRs',
             'source': source, 'every': '10m', 'alert': {'ring_at_least': 70}}
    if display or feeds:
        value['display'] = [
            {'type': 'score', 'components': [{'metric': 'recent', 'weight': 100,
                'type': 'delta', 'baseline': 'source'}]},
            {'type': 'stat', 'value': 'recent', 'show': 'both'},
            {'type': 'spark', 'value': 'recent'}]
    if feeds:
        value.pop('source')
        source['every'] = value.pop('every')
        value['feeds'] = {'main': source}
    return normalize(value)


class Counts:
    def __init__(self, *bodies):
        self.bodies, self.calls = list(bodies), []

    def bytes(self, url, **kwargs):
        self.calls.append(url)
        value = self.bodies.pop(0)
        if isinstance(value, Exception):
            raise value
        return json.dumps(value).encode(), {'content-type': 'application/json'}


def count(value, incomplete=False):
    return {'total_count': value, 'incomplete_results': incomplete}


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    monkeypatch.setattr('pulse_rings.sources.github._optional_token', lambda: None)


@pytest.mark.parametrize('window,seconds', [('24h', 86400), ('7d', 604800)])
@pytest.mark.parametrize('days', [7, 14, 30])
@pytest.mark.parametrize('recent,baseline', [(0, 0), (1, 0), (0, 42), (1234567, 42)])
def test_exact_windows_and_first_sample_source_average(window, seconds, days, recent, baseline):
    d, net, adapter = definition(window, days), Counts(count(baseline), count(recent)), GitHubSearch()
    first = adapter.poll(d, None, {}, now=NOW, net=net)
    assert first.sample is None
    assert first.state['baseline_start'] == NOW - seconds - days * 86400
    assert first.state['baseline_end'] == NOW - seconds - 1
    second = adapter.poll(d, None, first.state, now=NOW + 2, net=net)
    assert second.sample['metrics'] == {'recent': recent, 'baseline': baseline * seconds / (days * 86400)}
    ring = compute_ring(d, second.sample, [])
    assert not ring['unknown'] and 0 <= ring['score'] <= 100
    assert ring['warming'] == (baseline == 0 and recent != 0)
    assert second.sample['baselines']['recent'] == second.sample['metrics']['baseline']
    assert 'created:' in parse_qs(urlsplit(net.calls[-1]).query)['q'][0]
    json.dumps(second.sample, allow_nan=False)


@pytest.mark.parametrize('text', ['catalog OR security', 'OR', 'NOT', '-catalog', 'catalog AND fixes'])
def test_plain_title_words_cannot_become_query_operators(text):
    params = definition()['source']['params'] | {'title_contains': text, 'label': 'help wanted'}
    query = parse_qs(urlsplit(search_url(params, NOW - 86400, NOW)).query)['q'][0]
    assert f'"{text}" in:title' in query
    assert 'label:"help wanted"' in query
    assert query.startswith('repo:NousResearch/hermes-agent is:pr ')


@pytest.mark.parametrize('text', ['修复', 'café', '🚀', 'x\nOR', 'catalog"', 'a:b'])
def test_unsupported_unicode_and_query_syntax_fail_before_network(text):
    d = definition()
    d['source']['params']['title_contains'] = text
    net = Counts(count(0))
    with pytest.raises(SourceError):
        GitHubSearch().poll(d, None, {}, now=NOW, net=net)
    assert not net.calls


@pytest.mark.parametrize('body,message', [(count(0, True), 'incomplete'),
    (count(True), 'valid count'), (count(-1), 'valid count'), ({}, 'incomplete')])
def test_known_bad_data_has_specific_sanitized_error(body, message):
    with pytest.raises(SourceError, match=message):
        GitHubSearch().poll(definition(), None, {}, now=NOW, net=Counts(body))


@pytest.mark.parametrize('status,message', [(401, 'credential'), (403, 'rate limited'),
    (429, 'rate limited'), (422, 'rejected'), (500, 'server')])
def test_http_failures_are_specific_and_never_echo_payload(status, message):
    with pytest.raises(SourceError, match=message) as caught:
        GitHubSearch().poll(definition(), None, {}, now=NOW,
            net=Counts(SourceError('PRIVATE upstream payload', status, 123)))
    assert caught.value.status == status and caught.value.retry_after == 123
    assert 'PRIVATE' not in str(caught.value)


def test_network_error_is_not_replaced_by_unexplained_count_error():
    with pytest.raises(SourceError, match='reach GitHub'):
        GitHubSearch().poll(definition(), None, {}, now=NOW,
            net=Counts(SourceError('Could not reach public source. Cached values are preserved.')))


@pytest.mark.parametrize('display,feeds', [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize('failure', ['error', 'backoff'])
def test_failed_search_never_presents_last_good_score_as_current(tmp_path, display, feeds, failure):
    engine = Engine(tmp_path, clock=lambda: NOW + 60)
    d = definition(display=display, feeds=feeds)
    sample = {'ts': NOW, 'metrics': {'recent': 173, 'baseline': 46}, 'baselines': {'recent': 46}}
    engine.activate(d, sample={'main': sample} if feeds else sample)
    with engine.store.transaction() as db:
        table = 'feeds' if feeds else 'pulses'
        key = 'pulse_id' if feeds else 'id'
        if failure == 'error':
            db.execute(f'UPDATE {table} SET error=? WHERE {key}=?', ('GitHub search count is incomplete.', d['id']))
        else:
            db.execute(f'UPDATE {table} SET backoff_until=? WHERE {key}=?', (NOW + 600, d['id']))
    row = engine.status(poll=False, include_icons=False)['pulses'][0]
    assert row['ring']['unknown'], row
    assert not row['alert']['active']
    assert row['history'][-1]['value'] == 173
    if display:
        assert row['display'][0]['ring']['unknown']
        assert row['display'][1]['unknown'] and row['display'][1]['value_text'] is None
        assert row['display'][2]['points'][-1]['value'] is None
    else:
        assert row['capsule']['fill'] is None
    assert engine.store.history(d['id'])[-1]['metrics']['recent'] == 173
    # Recover using the same persisted history; masking must never be destructive.
    with engine.store.transaction() as db:
        db.execute(f'UPDATE {table} SET error=NULL,backoff_until=0 WHERE {key}=?', (d['id'],))
    recovered = engine.status(poll=False, include_icons=False)['pulses'][0]
    assert not recovered['ring']['unknown'] and recovered['alert']['active']
    if display:
        assert recovered['display'][1]['value'] == 173


@pytest.mark.parametrize('recent', [0, 1, 1000000])
def test_observed_zero_source_baseline_does_not_claim_to_be_learning(recent):
    d = definition()
    sample = {'ts': NOW, 'metrics': {'recent': recent, 'baseline': 0}, 'baselines': {'recent': 0}}
    capsule = compute_capsule(d, sample, compute_ring(d, sample, []))
    assert capsule['caption'] == 'Usual activity is zero'
    assert capsule['fill'] is None
    assert 'NaN' not in json.dumps(capsule)


def test_template_budget_and_unattended_draft_are_accurate(tmp_path):
    result = from_template('github-search', {'repo': 'NousResearch/hermes-agent', 'type': 'issue', 'window': '7d'})
    assert result['ok'], result['errors']
    # Conversion returns feeds/metadata, not a ready-to-save definition.
    d = normalize({'pulse': 1, 'title': result['suggested_title'], 'icon': result['suggested_icon'],
                   'feeds': result['feeds'], 'display': [{'type': 'stat', 'value': 'main.recent'}]})
    assert d['feeds']['main']['params']['window'] == '7d'
    assert d['feeds']['main']['params']['baseline_days'] == 14
    assert budget(d)['req_per_hour'] == pytest.approx(4 + 1 / 6)
    assert budget(d)['hosts'] == ['api.github.com']
    engine = Engine(tmp_path, clock=lambda: NOW)
    draft = engine.create_draft(d, origin={'kind': 'unattended'})
    assert draft['preview_calls'] == 0 and draft['preview'] is None
    disclosed = engine.draft(draft['draft_id'])['disclosure']['feeds'][0]
    assert disclosed['req_per_hour'] == pytest.approx(4 + 1 / 6)
    assert disclosed['hosts'] == ['api.github.com']


def test_search_first_stat_does_not_claim_its_known_source_baseline_is_learning(tmp_path):
    engine = Engine(tmp_path, clock=lambda: NOW)
    d = definition(display=True)
    sample = {'ts': NOW, 'metrics': {'recent': 173, 'baseline': 46}, 'baselines': {'recent': 46}}
    row = engine.preview(d, sample, budget(d))
    assert row['display'][0]['ring']['warming'] is False
    # Refs #59: default usual now uses the same source mean as the score.
    stat = row['display'][1]
    assert stat['value'] == 173 and stat['delta'] == 127
    assert stat['caption'] == 'vs usual'
