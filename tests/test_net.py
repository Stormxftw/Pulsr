"""Offline transport, persistent budgets/backoff, redirects and SSRF refusal."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import urllib.error

import pytest

from pulse_rings.engine import Engine
from pulse_rings.net import Net, NetworkError, fetch_json, validate_url, retry_delay
from pulse_rings.store import Store

PRESET = json.loads((Path(__file__).parent / 'fixtures/normalized/discord-reference.json').read_text())


def test_ceiling_is_global_cross_host_and_survives_restart(tmp_path):
    now = [1000]
    calls = []
    net = Net(Store(tmp_path), clock=lambda: now[0], ceiling=2)
    net.call('discord.com', lambda: calls.append('discord'))
    net.call('api.github.com', lambda: calls.append('github'))
    restarted = Net(Store(tmp_path), clock=lambda: now[0], ceiling=2)
    with pytest.raises(NetworkError, match='ceiling'):
        restarted.call('cdn.discordapp.com', lambda: calls.append('icon'))
    assert calls == ['discord', 'github']
    assert restarted.usage()['used'] == 2
    now[0] += 3600
    restarted.call('cdn.discordapp.com', lambda: calls.append('icon'))
    assert restarted.usage()['used'] == 1


def test_concurrent_budget_reservation_is_atomic(tmp_path):
    Store(tmp_path)
    def request(i):
        net = Net(Store(tmp_path), clock=lambda: 1000, ceiling=3)
        try:
            net.call(f'host-{i}.test', lambda: None)
            return True
        except NetworkError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(request, range(8))) == 3


def test_host_spacing_survives_restart(tmp_path):
    clock = lambda: 1000
    net = Net(Store(tmp_path), clock=clock)
    net.call('discord.com', lambda: None)
    with pytest.raises(NetworkError) as exc:
        Net(Store(tmp_path), clock=clock).call('discord.com', lambda: pytest.fail('pacing bypassed'))
    assert exc.value.retry_after == 2
    assert net.usage()['used'] == 1


def test_429_retry_after_survives_new_engine_and_blocks_other_pulses(tmp_path):
    now, calls = [1000], []
    class Limited:
        def poll(self, definition, previous, state, *, now, net):
            def limited():
                calls.append(definition['id'])
                raise NetworkError('Rate limited', 429, 1300)
            net.call('discord.com', limited)
    for i in range(2):
        engine = Engine(tmp_path, clock=lambda: now[0], adapters={'discord.invite@1': Limited()})
        engine.activate({**PRESET, 'id': f'rate-{i}'})
    assert engine.status(poll=True)['pulses'][0]['state'] == 'backoff'
    restarted = Engine(tmp_path, clock=lambda: now[0], adapters={'discord.invite@1': Limited()})
    now[0] += 1000
    restarted.status(poll=True)
    assert calls == ['rate-0']
    assert restarted.store.gate('host:discord.com') == 2300
    now[0] = 2301
    restarted.status(poll=True)
    assert len(calls) == 2


@pytest.mark.parametrize('url', ['http://example.com/x','https://user:secret@example.com/',
    'https://127.0.0.1/', 'https://[::1]/', 'https://169.254.169.254/latest/meta-data/',
    'https://localhost/', 'https://example.com:444/', 'https://example.com/#fragment',
    'https://example.com\\@evil.test/', 'https://example.com/\nheader'])
def test_unsafe_urls_fail_before_transport(url):
    with pytest.raises(ValueError):
        validate_url(url)


@pytest.mark.parametrize('headers,body,expected', [
    ({}, b'{"retry_after":1234.5}', 1234.5),
    ({'Retry-After':'90'}, b'', 90),
    ({'X-RateLimit-Reset':'2000','X-RateLimit-Remaining':'0'}, b'', 1000),
    ({}, b'{"retry_after":"nan"}', 600),
    ({}, b'{"retry_after":true}', 600),
    ({'Retry-After':'Fri, 01 Jan 2027 00:00:00 GMT'}, b'', 21600),
])
def test_retry_after_and_github_reset(headers, body, expected):
    assert retry_delay(429, headers, body, now=1000) == expected


def test_no_redirect_and_caps_content_type_strict_json(monkeypatch):
    import pulse_rings.net as mod
    class Reply(io.BytesIO):
        headers = {'Content-Type': 'application/json'}
    payload = [b'{"count":1}']
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == 'https://discord.com/api/test'
            assert timeout == 8
            assert request.get_method() == 'GET'
            assert request.get_header('Authorization') is None
            return Reply(payload[0])
    def build(handler):
        assert handler.redirect_request(None, None, 302, '', {}, 'https://127.0.0.1/') is None
        return Opener()
    monkeypatch.setattr(mod.urllib.request, 'build_opener', build)
    assert fetch_json('https://discord.com/api/test') == {'count':1}
    for raw in (b'x' * (mod.BODY_LIMIT + 1), b'{"count":NaN}', b'{"count":1e9999}', b'<html>'):
        payload[0] = raw
        with pytest.raises(NetworkError):
            fetch_json('https://discord.com/api/test')
    payload[0] = b'{}'
    Reply.headers = {'Content-Type': 'text/html'}
    with pytest.raises(NetworkError, match='content type'):
        fetch_json('https://discord.com/api/test')


def test_github_403_persists_reset_from_response(tmp_path, monkeypatch):
    import pulse_rings.net as mod
    now = [1000]
    class Opener:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(request.full_url, 403, 'limit', {'Retry-After': '1400'}, io.BytesIO(b'{}'))
    monkeypatch.setattr(mod.urllib.request, 'build_opener', lambda *_: Opener())
    net = Net(Store(tmp_path), clock=lambda: now[0])
    with pytest.raises(NetworkError):
        net.json('https://api.github.com/search/issues')
    assert Net(Store(tmp_path), clock=lambda: now[0]).store.gate('host:api.github.com') == 2400


def test_authorization_never_sent_to_other_hosts(tmp_path):
    with pytest.raises(ValueError, match='Authorization'):
        Net(Store(tmp_path)).bytes('https://discord.com/api/test', headers={'Authorization':'sentinel-secret'})


def test_fixed_avatar_host_and_no_unapproved_net_bytes(tmp_path):
    import pulse_rings.net as mod
    assert not hasattr(mod, '_safe_bytes')
    assert 'avatars.githubusercontent.com' in mod.FIXED_HOSTS
    with pytest.raises(ValueError, match='declared'):
        Net(Store(tmp_path)).bytes('https://example.com/public.json')
