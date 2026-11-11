"""Offline icon resolution contract: no test uses a live endpoint."""
import base64
import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from pulse_rings.icons import IconCache
from pulse_rings.net import Net
from pulse_rings.store import Store
from pulse_rings.sources.base import SourceError

PNG = (Path(__file__).parent / 'fixtures/tiny.png').read_bytes()
DATA = 'data:image/png;base64,' + base64.b64encode(PNG).decode()


def resolver(tmp_path, fetch=None, servers=None):
    assert importlib.util.find_spec('pulse_rings.icon_resolver') is not None, 'icon resolution API is not implemented'
    module = importlib.import_module('pulse_rings.icon_resolver')
    store = Store(tmp_path)
    now, calls = [1000], []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return fetch(url, **kwargs) if fetch else (PNG, {'Content-Type': 'image/png'})
    net = Net(store, clock=lambda: now[0])
    return module.IconResolver(store, net, IconCache(store, net, lambda *_: PNG),
                               fetch=get, mcp_servers=lambda: servers or {}), calls, now


def definition(icon='source', kind='github.repo', **params):
    return {'title': 'Example pulse', 'icon': icon,
            'source': {'kind': kind, 'params': {'repo': 'NousResearch/hermes-agent', **params}}}


def resolve(r, d=None, hosts=(), **kwargs):
    return r.resolve(d or definition(), metadata={}, budget={'hosts': list(hosts)}, **kwargs)


def test_offline_forms_and_fallbacks(tmp_path):
    r, calls, _ = resolver(tmp_path)
    assert resolve(r, definition({'brand': 'ebay'}))['slug'] == 'ebay'
    assert resolve(r, definition({'emoji': '🎉'})) == {'kind': 'emoji', 'text': '🎉'}
    assert resolve(r, definition('🎉')) == {'kind': 'emoji', 'text': '🎉'}
    assert resolve(r, definition('initials')) == {'kind': 'initials', 'text': 'EP'}
    assert resolve(r)['slug'] == 'github'
    assert resolve(r, definition(kind='discord.invite'))['slug'] == 'discord'
    assert resolve(r, definition(kind='hermes.activity'))['slug'] == 'hermes'
    assert resolve(r, definition('hermes'))['slug'] == 'hermes'
    assert resolve(r, definition(kind='http_json')) == {'kind': 'initials', 'text': 'EP'}
    assert calls == []


def test_explicit_url_requires_approval_disclosure_and_cache(tmp_path):
    r, calls, _ = resolver(tmp_path)
    d = definition({'url': 'https://icons.example.org/a.png'})
    assert resolve(r, d, hosts=['icons.example.org'], fetch=True)['kind'] == 'brand'
    assert resolve(r, d, approved=True, fetch=True)['kind'] == 'brand'
    assert not calls
    got = resolve(r, d, hosts=['icons.example.org'], approved=True, fetch=True)
    assert got['kind'] == 'raster' and got['url'].startswith('/icons/sha256-')
    assert len(calls) == 1
    assert calls[0][1]['limit'] == 256 * 1024
    assert resolve(r, d, hosts=['icons.example.org'], approved=True, fetch=True) == got
    assert len(calls) == 1
    assert r.data(got['url'].split('/')[-1]) == DATA


def test_github_owner_avatar_not_repository_or_foreign_host(tmp_path):
    r, calls, _ = resolver(tmp_path)
    got = resolve(r, hosts=['avatars.githubusercontent.com'], approved=True, fetch=True)
    assert got['kind'] == 'raster'
    assert calls[0][0] == 'https://avatars.githubusercontent.com/NousResearch?s=128'
    assert resolve(r, approved=True, fetch=True)['kind'] == 'brand'
    assert len(calls) == 1


def test_discord_cached_icon_precedes_brand_and_no_refetch(tmp_path):
    r, calls, _ = resolver(tmp_path)
    meta = {'id': '123456789012345678', 'icon_hash': 'a' * 32}
    r.discord.cache(meta)
    got = r.resolve(definition(kind='discord.invite'), metadata=meta, budget={'hosts': []})
    assert got == {'kind': 'raster', 'url': '/icons/' + meta['id'] + '-' + meta['icon_hash']}
    assert not calls


def server(tool_icons, server_icons):
    return NS(_tools=[NS(name='counts', icons=tool_icons)],
              initialize_result=NS(serverInfo=NS(icons=server_icons)))


def mcpdef():
    return definition(kind='mcp.tool', server='probe', tool='counts')


def test_mcp_tool_before_server_data_zero_requests(tmp_path):
    r, calls, _ = resolver(tmp_path, servers={'probe': server(
        [NS(src=DATA, mimeType='image/png', sizes=['64x64'])],
        [NS(src='https://icons.example.org/server.png', mimeType='image/png', sizes=['128x128'])])})
    got = resolve(r, mcpdef(), hosts=['icons.example.org'], approved=True, fetch=True)
    assert got['kind'] == 'raster' and r.data(got['url'].split('/')[-1]) == DATA
    assert calls == []


def test_mcp_server_fallback_and_size_preference(tmp_path):
    icons = [NS(src='https://icons.example.org/large.png', mimeType='image/png', sizes=['1024x1024']),
             NS(src='https://icons.example.org/right.png', mimeType='image/png', sizes=['96x96'])]
    r, calls, _ = resolver(tmp_path, servers={'probe': server([], icons)})
    assert resolve(r, mcpdef(), approved=True, fetch=True)['kind'] == 'initials'
    assert not calls
    assert resolve(r, mcpdef(), hosts=['icons.example.org'], approved=True, fetch=True)['kind'] == 'raster'
    assert [c[0] for c in calls] == ['https://icons.example.org/right.png']
    resolve(r, mcpdef(), hosts=['icons.example.org'], approved=True, fetch=True)
    assert len(calls) == 1


@pytest.mark.parametrize('body,mime', [(b'<svg><script/></svg>', 'image/svg+xml'),
    (PNG + b'x' * (256 * 1024), 'image/png'), (b'garbage', 'image/png'), (PNG, 'image/jpeg')],
    ids=['svg', 'oversize', 'magic', 'mime-mismatch'])
def test_network_invalid_fallback_and_six_hour_gate(tmp_path, body, mime):
    r, calls, now = resolver(tmp_path, fetch=lambda *a, **kw: (body, {'Content-Type': mime}))
    d = definition({'url': 'https://icons.example.org/bad'})
    for _ in range(2):
        assert resolve(r, d, hosts=['icons.example.org'], approved=True, fetch=True)['kind'] == 'brand'
    assert len(calls) == 1
    now[0] += 21601
    resolve(r, d, hosts=['icons.example.org'], approved=True, fetch=True)
    assert len(calls) == 2


def test_redirect_failure_falls_back_and_is_gated(tmp_path):
    def redirect(*args, **kwargs):
        raise SourceError('Redirect refused', 302)
    r, calls, _ = resolver(tmp_path, fetch=redirect)
    d = definition({'url': 'https://icons.example.org/redirect'})
    for _ in range(2):
        assert resolve(r, d, hosts=['icons.example.org'], approved=True, fetch=True)['kind'] == 'brand'
    assert len(calls) == 1


@pytest.mark.parametrize('src', ['data:image/svg+xml;base64,PHN2Zy8+',
    'data:image/jpeg;base64,' + base64.b64encode(PNG).decode(),
    'data:image/png;base64,!!!!', 'data:image/png;base64,' + base64.b64encode(PNG + b'x' * 262144).decode()],
    ids=['svg', 'mime-mismatch', 'invalid-base64', 'oversize'])
def test_invalid_data_falls_back_without_network(tmp_path, src):
    r, calls, _ = resolver(tmp_path, servers={'probe': server([NS(src=src)], [])})
    assert resolve(r, mcpdef(), approved=True, fetch=True)['kind'] == 'initials'
    assert not calls


@pytest.mark.parametrize('key', ['../secret', '..', '/absolute', 'sha256-' + 'a' * 63,
    'sha256-' + 'a' * 64 + '.image', 'sha256-' + 'g' * 64, 'a/b'])
def test_cache_identity_path_traversal(tmp_path, key):
    r, _, _ = resolver(tmp_path)
    assert r.data(key) is None


def test_brand_bundle_and_strict_path_grammar():
    from pulse_rings import brands
    from pulse_rings.path_data import valid_path
    for slug in ('github', 'discord', 'ebay'):
        assert brands.has_brand(slug)
        assert set(brands.brand(slug)) == {'title', 'hex', 'path'}
        assert valid_path(brands.brand(slug)['path'])
    assert brands.suggest('githb') == 'github'
    assert brands.brand('not-a-real-brand') is None
    assert valid_path('M0 0h24v24H0z')
    for path in ('<script>', 'M0 0url(x)', 'M0 0R1 2', 'M0 0L1', '0 0', 'M0 0 A2 2 0 3 1 4 4', 'MNaN 0'):
        assert not valid_path(path), path
    p = Path(brands.__file__).with_name('brands.json')
    assert p.stat().st_size <= 5_000_000
    bundle = json.loads(p.read_text(encoding='utf-8'))
    assert all(valid_path(b['path']) for b in bundle.values())
