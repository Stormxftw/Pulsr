"""Integrated human routes and no preapproval egress; synthetic source only."""
import builtins
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pulse_rings.authoring import RunContexts, register_tools
from pulse_rings.engine import Engine
from pulse_rings.sources import http_json
from pulse_rings.sources.base import SourceError
from test_authoring import Context
from test_migrate import old, hashes

ROOT = Path(__file__).resolve().parents[1]
HTTP = {'pulse': 1, 'title': 'Public count', 'source': {'kind': 'http_json',
        'params': {'url': 'https://public.example/count', 'metrics': {'count': '/count'}}}}


def test_default_http_adapter_and_no_preapproval_fetch_at_engine_and_tool_layers(tmp_path, monkeypatch):
    e = Engine(tmp_path, clock=lambda: 3000)
    assert isinstance(e.adapter(HTTP), http_json.HttpJsonSource)
    alias = {**HTTP, 'source': {**HTTP['source'], 'kind': 'http_json@1'}}
    assert e.adapter(alias) is e.adapter(HTTP)
    for key in ('http_json', 'http_json@1'):
        injected = object()
        override = Engine(tmp_path / key.replace('@', '-'), adapters={key: injected})
        assert override.adapter(HTTP) is injected
    fetch = Mock(side_effect=AssertionError('No arbitrary-host preapproval egress'))
    monkeypatch.setattr(http_json.HttpJsonSource, 'poll', fetch)
    ctx = Context()
    contexts = RunContexts(ctx)
    contexts.observe('pre_llm_call', session_id='interactive')
    register_tools(ctx, contexts, lambda: e)
    for via in ('engine', 'tool'):
        d = {**HTTP, 'id': via}
        result = (e.create_draft(d, origin={'kind': 'session'}) if via == 'engine' else
                  json.loads(ctx.tools['pulse_rings_propose']['handler']({'definition': d}, session_id='interactive')))
        assert result['preview_calls'] == 0 and result['preview'] is None
        assert result['budget']['hosts'] == ['public.example']
    for _ in range(3):
        e.status(poll=True)
    fetch.assert_not_called()
    assert not e.store.rows() and e.net.usage()['used'] == 0
    # Defense in depth: even corrupt stored preview eligibility must not dispatch.
    with e.store.transaction() as db:
        db.execute('UPDATE drafts SET preview_allowed=1,preview_due=0')
    e.status(poll=True)
    fetch.assert_not_called()
    first = e.status()['drafts'][0]['id']
    e.decide_draft(first, 'approve')
    fetch.assert_not_called()  # approval itself does not poll
    e.clock = lambda: 3002  # activation deliberately paces the first active request
    for _ in range(3):
        e.poll_one_due()  # another pending preview may take the first tick
    assert fetch.call_count == 1  # only the human-approved active source reaches adapter


@pytest.mark.parametrize('missing', ['module', 'client', 'helper'])
def test_http_fails_closed_without_hermes_safety_apis(monkeypatch, missing):
    original = builtins.__import__
    helpers = SimpleNamespace(is_safe_url=lambda url: True, create_ssrf_safe_async_client=lambda: None)
    if missing != 'module':
        delattr(helpers, 'is_safe_url' if missing == 'helper' else 'create_ssrf_safe_async_client')
    def importer(name, *args, **kwargs):
        if name == 'tools.url_safety':
            if missing == 'module':
                raise ImportError('Hermes unavailable')
            return helpers
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', importer)
    dns = Mock(side_effect=AssertionError('Do not resolve without Hermes APIs'))
    monkeypatch.setattr(http_json, '_resolve', dns)
    with pytest.raises(SourceError):
        http_json._hermes_check('https://public.example/')
    connector = Mock(side_effect=AssertionError('No socket without Hermes APIs'))
    monkeypatch.setattr(http_json, '_PinnedHTTPSConnection', connector)
    with pytest.raises(SourceError):
        http_json.HttpJsonSource().poll(HTTP, None, {}, now=1,
            net=SimpleNamespace(call=lambda host, callback: callback()))
    dns.assert_not_called()
    connector.assert_not_called()


@pytest.mark.parametrize('guard', ['kind', 'arbitrary', 'adapter'])
def test_fixed_kind_adapter_guards_also_fail_closed(tmp_path, monkeypatch, guard):
    from pulse_rings.kinds import KINDS
    from pulse_rings.previews import tick
    adapter = SimpleNamespace(poll=Mock(side_effect=AssertionError('Must not preview')),
                              arbitrary_host=guard == 'arbitrary',
                              pre_approval_sample=guard != 'adapter')
    e = Engine(tmp_path, clock=lambda: 3000, adapters={'discord.invite': adapter})
    if guard == 'kind':
        monkeypatch.setitem(KINDS['discord.invite'], 'pre_approval_sample', False)
    draft = e.create_draft({'pulse': 1, 'title': 'Safe test',
                          'source': {'kind': 'discord.invite', 'params': {'invite': 'FakeAlpha'}}},
                          origin={'kind': 'session'})
    assert draft['preview_calls'] == 0
    with e.store.transaction() as db:
        db.execute('UPDATE drafts SET preview_allowed=1,preview_due=0')
    tick(e)
    adapter.poll.assert_not_called()


def test_actual_import_routes_consent_readback_banner_and_no_source_changes(tmp_path, old, monkeypatch):
    home, source = old
    before = hashes(source)
    monkeypatch.setitem(sys.modules, 'hermes_constants', SimpleNamespace(get_hermes_home=lambda: home))
    spec = importlib.util.spec_from_file_location('wp7_routes', ROOT / 'dashboard/plugin_api.py')
    assert spec is not None and spec.loader is not None
    routes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(routes)
    e = Engine(tmp_path / 'new', clock=lambda: 3000)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_pulse] = lambda: e
    e.poll_one_due = Mock(side_effect=AssertionError('Import must not poll'))
    with TestClient(app) as client:
        endpoint = '/migrate/discord-pulse'
        status = client.get('/status?poll=0').json()
        assert status['features']['import_discord'] is True
        assert status['migration'] == {'available': True, 'completed': False}
        assert 'migration' not in e.status(compact=True)
        plan = client.get(endpoint)
        assert plan.status_code == 200 and plan.json()['pulses'] == 3
        token = plan.json()['token']
        assert not e.store.rows()
        for body, code in [({}, 422), ({'consent': 'true', 'token': token}, 422),
                           ({'consent': True, 'token': token, 'source': '/other'}, 422),
                           ({'consent': False, 'token': token}, 400),
                           ({'consent': True, 'token': '0' * 64}, 409)]:
            assert client.post(endpoint, json=body).status_code == code
        assert not e.store.rows()
        note = source / 'notes/100000000000000001.md'
        original_note = note.read_bytes()
        note.write_text('Changed note requires fresh consent', encoding='utf-8')
        assert client.post(endpoint, json={'consent': True, 'token': token}).status_code == 409
        note.write_bytes(original_note)
        token = client.get(endpoint).json()['token']
        receipt = client.post(endpoint, json={'consent': True, 'token': token})
        assert receipt.status_code == 200 and receipt.json()['completed']
        cached = client.get('/status?poll=0').json()
        assert cached['migration']['completed'] and not cached['migration']['available']
        assert set(plan.json()['ids']) <= {p['id'] for p in cached['pulses']}
        assert client.post(endpoint, json={'consent': True, 'token': token}).json()['pulses'] == 0
    assert hashes(source) == before
    e.poll_one_due.assert_not_called()


def test_status_offer_is_cheap_and_failure_isolated(tmp_path, monkeypatch):
    e = Engine(tmp_path)
    offer = Mock(return_value={'available': True, 'completed': False})
    importer = Mock(return_value=SimpleNamespace(offer=offer, plan=Mock(side_effect=AssertionError('No plan in status'))))
    monkeypatch.setattr('pulse_rings.engine.DiscordPulseImporter', importer)
    assert e.status()['migration']['available']
    e.status(compact=True)
    assert importer.call_count == 1
    offer.side_effect = RuntimeError('bad source')
    assert e.status()['migration'] == {'available': False, 'completed': False}
