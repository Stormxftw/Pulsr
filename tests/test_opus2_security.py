"""Inverted Opus security probes and decision-boundary regressions."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pulse_rings.authoring import rings_command
from pulse_rings.engine import Engine
from pulse_rings.spec import normalize, ValidationError, budget
from pulse_rings.sources.http_json import _url

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_794_000_000.0
DEF = {'pulse': 1, 'title': 'Hermes', 'source': {'kind': 'hermes.activity'}}


@pytest.fixture
def api_client(tmp_path):
    spec = importlib.util.spec_from_file_location('security_test_api', ROOT / 'dashboard/plugin_api.py')
    api = importlib.util.module_from_spec(spec); spec.loader.exec_module(api)
    engine = Engine(tmp_path, clock=lambda: NOW)
    app = FastAPI(); app.include_router(api.router)
    app.dependency_overrides[api.get_pulse] = lambda: engine
    with TestClient(app) as client:
        yield client, engine


def test_legacy_activation_routes_are_gone(api_client):
    client, engine = api_client
    assert client.post('/servers', json={'invite': 'nousresearch'}).status_code == 404
    assert client.delete('/servers/100000000000000000').status_code == 404
    assert not hasattr(engine, 'add') and not hasattr(engine, 'remove')
    assert not engine.store.rows()


@pytest.mark.parametrize('decision', ['approve', 'reject'])
def test_decision_requires_explicit_json_confirmation(api_client, decision):
    client, engine = api_client
    id = engine.create_draft(DEF)['draft_id']
    path = f'/drafts/{id}/{decision}'
    for body in (None, {}, {'confirm': False}, {'confirm': 'true'}, {'confirm': True, 'extra': 1}):
        response = client.post(path) if body is None else client.post(path, json=body)
        assert response.status_code in (400, 422)
        assert engine.draft(id)['status'] == 'pending'
    assert client.post(path, json={'confirm': True}).status_code == 200
    assert engine.draft(id)['status'] == ('approved' if decision == 'approve' else 'rejected')


@pytest.mark.parametrize('field,value', [('definition', '{'), ('source_state', 'null')])
def test_corrupt_drafts_map_to_conflict(api_client, field, value):
    client, engine = api_client
    id = engine.create_draft(DEF)['draft_id']
    with engine.store.transaction() as db:
        db.execute(f'UPDATE drafts SET {field}=? WHERE id=?', (value, id))
    if field == 'source_state':
        # Valid JSON but wrong shape must also fail closed.
        with engine.store.transaction() as db:
            db.execute("UPDATE drafts SET origin='null' WHERE id=?", (id,))
    assert client.get('/drafts/' + id).status_code == 409
    assert client.post('/drafts/' + id + '/approve', json={'confirm': True}).status_code == 409


@pytest.mark.parametrize('control', ['\u202e', '\u200b', '\x00', '\n'])
@pytest.mark.parametrize('field', ['title', 'capsule', 'line'])
def test_display_text_rejects_invisible_controls(field, control):
    d = normalize(DEF)
    if field == 'title': d['title'] = 'GitHub' + control
    elif field == 'capsule': d['capsule']['label'] = '{value}' + control
    else: d['lines'][0]['label'] = '{value}' + control
    with pytest.raises(ValidationError):
        normalize(d)


def test_scalar_approver_ids_cannot_grant_substring_identity():
    engine = SimpleNamespace(decide_draft=lambda *a, **kw: {'draft': {'status': 'approved'}, 'row': None})
    user = SimpleNamespace(platform=SimpleNamespace(value='telegram'), user_id='1234')
    for ids in ('telegram:123456789', {'telegram:1234': True}, None):
        assert rings_command(lambda: engine, approver_ids=ids)('approve pd_0123456789', platform='telegram', source=user).startswith('Decision refused')
    assert rings_command(lambda: engine, approver_ids=['telegram:1234', 42])('approve pd_0123456789', platform='telegram', source=user).endswith('approved')


def test_compact_notes_and_origin_never_carry_stored_instructions_or_session_id(tmp_path):
    engine = Engine(tmp_path, clock=lambda: NOW)
    engine.activate(normalize(DEF))
    pulse_id = engine.store.rows()[0]['id']
    (tmp_path / 'notes').mkdir()
    (tmp_path / 'notes' / (pulse_id + '.md')).write_text('untrusted-note-' * 1000)
    engine.create_draft(DEF, origin={'kind': 'session', 'session_id': 'RAW_PRIVATE_ID'})
    result = engine.status(compact=True, include_icons=False)
    assert 'note' not in result['pulses'][0]
    assert 'RAW_PRIVATE_ID' not in json.dumps(result)
    with engine.store.db() as db:
        assert 'RAW_PRIVATE_ID' not in '\n'.join(db.iterdump())


def test_trailing_dot_budget_and_gate_hosts_agree():
    d = normalize({'pulse': 1, 'title': 'x', 'source': {'kind': 'http_json',
                  'params': {'url': 'https://example.com./x', 'metrics': {'n': '/n'}}}})
    assert budget(d)['hosts'] == [_url(d['source']['params']['url'])[0]] == ['example.com']
