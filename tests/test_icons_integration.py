"""Exercise the activated engine, REST cache and captured MCP metadata seams."""
import base64
from contextvars import ContextVar, copy_context
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from pulse_rings import mcp_access
from pulse_rings.engine import Engine
from pulse_rings.icon_resolver import IconResolver
from pulse_rings.icons import IconCache
from pulse_rings.net import Net
from pulse_rings.sources.base import SourceResult
from pulse_rings.spec import normalize
from pulse_rings.store import Store

ROOT = Path(__file__).resolve().parents[1]
PNG = (ROOT / 'tests/fixtures/tiny.png').read_bytes()
DATA = 'data:image/png;base64,' + base64.b64encode(PNG).decode()


@pytest.fixture
def engine(tmp_path):
    return Engine(tmp_path, clock=lambda: 1000, jitter=lambda: 0, icon_fetch=lambda *_: PNG)


def gh():
    return normalize({'pulse': 1, 'id': 'owner', 'title': 'Owner avatar',
        'source': {'kind': 'github.repo', 'params': {'repo': 'NousResearch/hermes-agent'}}})


def test_engine_uses_persisted_approval_status_is_read_only(engine):
    calls = []
    engine.icon_resolver.fetch = lambda url, **kw: (calls.append(url) or PNG, {'Content-Type': 'image/png'})
    engine.activate(gh())
    with engine.store.transaction() as db:
        # Represents WP8-spec approval output, not runtime recomputation. This
        # branch deliberately does not modify the sibling validator work package.
        row = db.execute('SELECT budget FROM pulses WHERE id=?', ('owner',)).fetchone()
        budget = json.loads(row[0])
        budget['hosts'] = ['api.github.com', 'avatars.githubusercontent.com']
        db.execute('UPDATE pulses SET budget=?', (json.dumps(budget),))
    assert engine.status(poll=False)['pulses'][0]['icon_resolved']['kind'] == 'brand'
    assert not calls
    class Source:
        def poll(self, *args, **kwargs):
            return SourceResult(sample={'ts': 1000, 'metrics': {'stars': 3}})
    engine.adapters['github.repo'] = Source()
    engine.poll_one_due()
    got = engine.status(poll=False)['pulses'][0]['icon_resolved']
    assert got['kind'] == 'raster' and len(calls) == 1
    assert engine.status(poll=False)['pulses'][0]['icon_resolved'] == got
    assert len(calls) == 1
    assert engine.status(poll=False, include_icons=False)['pulses'][0]['icon_resolved']['kind'] == 'brand'


def test_preview_and_error_rows_have_offline_resolved_icon(engine):
    calls = []
    engine.icon_resolver.fetch = lambda *a, **k: calls.append(a)
    d = gh()
    d['icon'] = {'brand': 'ebay'}
    assert engine.preview(d, None, {'hosts': []})['icon_resolved']['slug'] == 'ebay'
    d['icon'] = {'url': 'https://icons.example.org/icon.png'}
    assert engine.preview(d, None, {'hosts': ['icons.example.org']})['icon_resolved']['kind'] == 'brand'
    assert engine._error_row({'id': 'broken'})['icon_resolved']['kind'] == 'initials'
    assert not calls


def test_hash_route_and_legacy_route_fail_closed(engine):
    spec = importlib.util.spec_from_file_location('resolved_icon_test_api', ROOT / 'dashboard/plugin_api.py')
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_pulse] = lambda: engine
    d = gh()
    d['icon'] = {'url': 'https://icons.example.org/icon.png'}
    engine.icon_resolver.fetch = lambda *a, **k: (PNG, {'Content-Type': 'image/png'})
    got = engine.icon_resolver.resolve(d, budget={'hosts': ['icons.example.org']}, approved=True, fetch=True)
    with TestClient(app) as client:
        response = client.get(got['url'])
        assert response.status_code == 200
        assert response.json() == {'icon_data': DATA}
        assert response.headers['cache-control'] == 'private, max-age=31536000, immutable'
        for identity in ['..%2Fsecret', '%2e%2e%5csecret', 'sha256-' + 'a' * 63,
                         'sha256-' + 'g' * 64, 'sha256-' + 'a' * 64 + '.image', 'bad']:
            assert client.get('/icons/' + identity).status_code == 404
        path = engine.icon_resolver.path(got['url'].split('/')[-1])
        path.write_bytes(b'<svg/>')
        assert client.get(got['url']).status_code == 404


def test_failure_gate_dedupes_simultaneous_readers(tmp_path):
    store = Store(tmp_path)
    net = Net(store, clock=lambda: 1000)
    calls = []
    resolver = IconResolver(store, net, IconCache(store, net),
        fetch=lambda *a, **k: (calls.append(a) or b'<svg/>', {'Content-Type': 'image/svg+xml'}))
    d = gh()
    d['icon'] = {'url': 'https://icons.example.org/icon'}
    def resolve(_):
        return resolver.resolve(d, budget={'hosts': ['icons.example.org']}, approved=True, fetch=True)
    with ThreadPoolExecutor(max_workers=5) as pool:
        got = list(pool.map(resolve, range(5)))
    assert all(icon['kind'] == 'brand' for icon in got)
    assert len(calls) == 1


def test_mcp_icons_come_from_public_tool_info_only(tmp_path):
    scope = ContextVar('icon-test-profile', default='wrong')
    scope.set('correct')
    captured = copy_context()
    scope.set('wrong')
    def tool_info(name):
        if scope.get() != 'correct' or name != 'mcp__probe__counts':
            return {'exists': False}
        return {'exists': True, 'icons': [NS(src=DATA, mimeType='image/png')],
                'server_icons': [NS(src='https://server.example.org/logo')]}
    key = str(tmp_path.resolve())
    mcp_access._BINDINGS[key] = (NS(), captured, 'correct')
    try:
        assert mcp_access.declared_icons(tmp_path, 'probe', 'counts') == ([], [])  # no public API: off
    finally:
        mcp_access._BINDINGS.pop(key, None)
    mcp_access._BINDINGS[key] = (NS(tool_info=tool_info), captured, 'correct')
    try:
        groups = mcp_access.declared_icons(tmp_path, 'probe', 'counts')
        assert groups[0][0].src == DATA
        assert groups[1][0].src == 'https://server.example.org/logo'
        assert mcp_access.declared_icons(tmp_path / 'other-profile', 'probe', 'counts') == ([], [])
        _resolve_mcp_icon_without_requests(tmp_path)
    finally:
        mcp_access._BINDINGS.pop(key, None)


def _resolve_mcp_icon_without_requests(tmp_path):
    store = Store(tmp_path)
    net = Net(store, clock=lambda: 1000)
    calls = []
    r = IconResolver(store, net, IconCache(store, net), fetch=lambda *a, **k: calls.append(a))
    d = {'title': 'MCP counts', 'source': {'kind': 'mcp.tool', 'params': {'server': 'probe', 'tool': 'counts'}}}
    assert r.resolve(d, approved=True, fetch=True)['kind'] == 'raster'
    assert calls == []


def test_cache_refuses_parent_and_file_symlinks(tmp_path):
    store = Store(tmp_path / 'data')
    net = Net(store, clock=lambda: 1000)
    r = IconResolver(store, net, IconCache(store, net))
    key = 'sha256-' + 'a' * 64
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / (key + '.image')).write_bytes(PNG)
    try:
        (store.root / 'icons').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Symlink privilege unavailable')
    assert r.data(key) is None
    assert not r._write(key, PNG)
    (store.root / 'icons').unlink()
    (store.root / 'icons').mkdir()
    r.path(key).symlink_to(outside / (key + '.image'))
    assert r.data(key) is None
    assert not r._write(key, PNG)
