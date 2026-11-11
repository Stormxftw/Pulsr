"""Offline WP6 security boundary: real parser, resolver and pinned TLS connector."""
import builtins
import io
import socket
from types import SimpleNamespace

import pytest

from pulse_rings.sources import http_json as h
from pulse_rings.sources.base import Deferred, SourceError
from pulse_rings.net import Net
from pulse_rings.store import Store


class Gate:
    def __init__(self):
        self.hosts = []

    def call(self, host, callback):
        self.hosts.append(host)
        return callback()


def definition(url='https://public.example/data?view=counts', metrics=None):
    return {'source': {'kind': 'http_json', 'params': {
        'url': url, 'metrics': metrics or {'count': '/count'}}}}


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError('Live network forbidden')
    monkeypatch.setattr(socket, 'getaddrinfo', refused)
    monkeypatch.setattr(socket, 'socket', refused)
    # Offline public-API double, independent of the developer's Hermes install.
    original = builtins.__import__
    def importer(name, *args, **kwargs):
        if name == 'tools.url_safety':
            return SimpleNamespace(is_safe_url=lambda url: True, create_ssrf_safe_async_client=lambda: None)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', importer)


def public_dns(monkeypatch, addresses=('93.184.216.34',)):
    calls = []
    def resolve(host, port, *args, **kwargs):
        calls.append((host, port))
        return [(socket.AF_INET6 if ':' in addr else socket.AF_INET,
                 socket.SOCK_STREAM, socket.IPPROTO_TCP, '',
                 (addr, port, 0, 0) if ':' in addr else (addr, port)) for addr in addresses]
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    return calls


def fake_http(monkeypatch, raw=b'{"count":12}', status=200, headers=None):
    seen = []
    class Reply(io.BytesIO):
        def __init__(self):
            super().__init__(raw)
            self.status = status
            self.headers = headers or {'Content-Type': 'application/json'}
        def getheaders(self):
            return list(self.headers.items())
        def isclosed(self):
            return self.closed
    class Connection:
        def __init__(self, host, address, *, timeout):
            seen.append({'host': host, 'address': address, 'timeout': timeout})
            self.sock = SimpleNamespace(settimeout=lambda value: None)
        def request(self, method, target, headers):
            seen[-1].update(method=method, target=target, headers=headers)
        def getresponse(self):
            return Reply()
        def close(self):
            seen[-1]['closed'] = True
    monkeypatch.setattr(h, '_PinnedHTTPSConnection', Connection)
    return seen


@pytest.mark.parametrize('url', [
    'http://public.example/', 'https://user:secret@public.example/',
    'https://public.example:444/', 'https://public.example:80/',
    'https://localhost/', 'https://LOCALHOST./', 'https://thing.local/',
    'https://127.0.0.1/', 'https://10.1.2.3/', 'https://169.254.169.254/',
    'https://100.64.0.1/', 'https://224.0.0.1/', 'https://240.0.0.1/',
    'https://[::1]/', 'https://[fc00::1]/', 'https://[fe80::1]/',
    'https://[ff02::1]/', 'https://[::ffff:8.8.8.8]/',
    'https://[::ffff:127.0.0.1]/', 'https://public.example/#fragment',
    'https://public.example/\nheader', 'https://public.example\\@127.0.0.1/',
    'https://public.example/%0d%0a', 'https://public.example:0443/',
])
def test_unsafe_url_rejected_without_dispatch(url):
    net = Gate()
    with pytest.raises(SourceError):
        h.HttpJsonSource().poll(definition(url), None, {}, now=1000, net=net)
    assert net.hosts == []


@pytest.mark.parametrize('addresses', [
    ('10.0.0.1',), ('127.0.0.1',), ('169.254.169.254',), ('100.64.0.1',),
    ('fc00::1',), ('::ffff:8.8.8.8',), ('93.184.216.34', '192.168.1.1'),
])
def test_private_dns_or_mixed_answer_refused(monkeypatch, addresses):
    public_dns(monkeypatch, addresses)
    seen = fake_http(monkeypatch)
    with pytest.raises(SourceError):
        h.HttpJsonSource().poll(definition(), None, {}, now=1000, net=Gate())
    assert seen == []


def test_rebinding_dials_only_vetted_address_and_keeps_host(monkeypatch):
    calls = public_dns(monkeypatch)
    seen = fake_http(monkeypatch)
    net = Gate()
    result = h.HttpJsonSource().poll(definition(), None, {'raw': 'discard'}, now=1000, net=net)
    assert result.sample == {'ts': 1000, 'metrics': {'count': 12}, 'baselines': {}, 'unknown_reasons': {}}
    assert result.state == result.metadata == {}
    assert calls == [('public.example', 443)]
    assert seen[0]['address'][1][0] == '93.184.216.34'
    assert seen[0]['host'] == 'public.example'
    assert seen[0]['headers']['Host'] == 'public.example'
    assert seen[0]['target'] == '/data?view=counts'
    assert seen[0]['method'] == 'GET' and seen[0]['closed']
    assert net.hosts == ['public.example']
    # The next poll re-resolves and refuses a newly private answer.
    public_dns(monkeypatch, ('10.0.0.1',))
    with pytest.raises(SourceError):
        h.HttpJsonSource().poll(definition(), None, {}, now=1300, net=net)
    assert len(seen) == 1


def test_actual_connector_does_not_resolve_again_preserves_sni(monkeypatch):
    seen = []
    class Sock:
        def settimeout(self, timeout):
            seen.append(('timeout', timeout))
        def connect(self, address):
            seen.append(('connect', address))
        def close(self):
            seen.append(('close',))
    sock = Sock()
    monkeypatch.setattr(socket, 'socket', lambda *args: sock)
    context = SimpleNamespace(wrap_socket=lambda raw, server_hostname: seen.append(('sni', server_hostname)) or raw)
    conn = h._PinnedHTTPSConnection('public.example', (socket.AF_INET, ('93.184.216.34', 443)), timeout=8)
    assert conn._context.check_hostname and conn._context.verify_mode == h.ssl.CERT_REQUIRED
    conn._context = context
    conn.connect()
    assert ('connect', ('93.184.216.34', 443)) in seen
    assert ('sni', 'public.example') in seen
    conn.close()


@pytest.mark.parametrize('raw,status,headers', [
    (b'{}', 302, {'Location': 'https://127.0.0.1/', 'Content-Type': 'application/json'}),
    (b'{}', 200, {'Content-Type': 'text/html'}),
    (b'{}', 200, {'Content-Type': 'text/not+json'}),
    (b'{}', 200, {'Content-Type': 'application/json', 'Content-Encoding': 'gzip'}),
    (b'x' * (512 * 1024 + 1), 200, None),
    (b'{"count":NaN}', 200, None), (b'{"count":Infinity}', 200, None),
    (b'{"count":1e9999}', 200, None), (b'<html>', 200, None),
], ids=['redirect', 'html', 'bad-json-suffix', 'compression', 'oversize', 'nan', 'infinity', 'overflow', 'malformed'])
def test_response_caps_redirects_mime_and_json(monkeypatch, raw, status, headers):
    public_dns(monkeypatch)
    seen = fake_http(monkeypatch, raw, status, headers)
    with pytest.raises(SourceError):
        h.HttpJsonSource().poll(definition(), None, {}, now=1000, net=Gate())
    assert len(seen) == 1 and seen[0]['closed']


def test_pointer_rfc6901_arrays_root_escaped_keys_and_strict_numbers(monkeypatch):
    public_dns(monkeypatch)
    fake_http(monkeypatch, b'{"a/b":{"~key":[-2.5]},"bool":true,"str":"12","nil":null}')
    metrics = {'value': '/a~1b/~0key/0', 'boolean': '/bool', 'text': '/str', 'nil': '/nil',
               'missing': '/absent', 'bad_index': '/a~1b/~0key/01'}
    sample = h.HttpJsonSource().poll(definition(metrics=metrics), None, {}, now=1, net=Gate()).sample
    assert sample['metrics'] == {'value': -2.5, **{key: None for key in metrics if key != 'value'}}
    assert set(sample['unknown_reasons']) == set(metrics) - {'value'}
    assert h.json_pointer(42, '') == 42
    for pointer in ('/a~2b', 'bad', '/a~'):
        with pytest.raises(SourceError):
            h.json_pointer({}, pointer)


def test_public_helper_is_used_lazily_without_weakening_strict_policy(monkeypatch):
    original = builtins.__import__
    calls = []
    helpers = SimpleNamespace(is_safe_url=lambda url: calls.append(url) or False,
                              create_ssrf_safe_async_client=lambda: None)
    monkeypatch.setattr(builtins, '__import__', lambda name, *a, **k: helpers if name == 'tools.url_safety' else original(name, *a, **k))
    public_dns(monkeypatch)
    seen = fake_http(monkeypatch)
    with pytest.raises(SourceError):
        h.HttpJsonSource().poll(definition(), None, {}, now=1000, net=Gate())
    assert len(calls) == 1 and seen == []
    helpers.is_safe_url = lambda url: True  # Hermes allow_private_urls must not override pulse policy.
    public_dns(monkeypatch, ('10.1.2.3',))
    with pytest.raises(SourceError):
        h.HttpJsonSource().poll(definition(), None, {}, now=1000, net=Gate())
    assert seen == []


def test_arbitrary_flag_sanitization_deferral_and_durable_budget(tmp_path, monkeypatch):
    adapter = h.HttpJsonSource()
    assert adapter.arbitrary_host is True and adapter.pre_approval_sample is False
    class Broken:
        def call(self, *args):
            raise RuntimeError('sentinel-secret https://evil.test/private')
    with pytest.raises(SourceError) as error:
        adapter.poll(definition(), None, {}, now=1000, net=Broken())
    assert 'sentinel' not in str(error.value) and 'https://' not in str(error.value)
    class Pacing:
        def call(self, *args):
            raise Deferred('Local pacing', 429, 2)
    with pytest.raises(Deferred):
        adapter.poll(definition(), None, {}, now=1000, net=Pacing())
    public_dns(monkeypatch)
    fake_http(monkeypatch)
    net = Net(Store(tmp_path), clock=lambda: 1000)
    adapter.poll(definition(), None, {}, now=1000, net=net)
    assert net.usage()['used'] == 1
    with pytest.raises(Deferred):
        adapter.poll(definition(), None, {}, now=1000, net=net)


def test_io_timeout_and_json_suffix(monkeypatch):
    public_dns(monkeypatch)
    seen = fake_http(monkeypatch, headers={'Content-Type': 'application/problem+json; charset=utf-8'})
    h.HttpJsonSource().poll(definition(), None, {}, now=1, net=Gate())
    assert 0 < seen[0]['timeout'] <= 8
    def timeout(*args, **kwargs):
        raise TimeoutError('secret URL')
    monkeypatch.setattr(h, '_PinnedHTTPSConnection', timeout)
    with pytest.raises(SourceError) as error:
        h.HttpJsonSource().poll(definition(), None, {}, now=1, net=Gate())
    assert 'secret' not in str(error.value)


def test_real_http_client_wire_close_response_and_tls_contract(monkeypatch):
    """Do not mock HTTPConnection: exercise its real will_close detach behavior."""
    public_dns(monkeypatch)
    sent, tls, sockets = [], [], []
    class Sock:
        def __init__(self, *args):
            self.timeout = None
            self.response = io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: 12\r\n\r\n{"count":12}')
            sockets.append(self)
        def settimeout(self, value):
            # Real sockets really close once http.client finishes a
            # Content-Length body (makefile refs drop to zero); Windows then
            # raises WinError 10038 and POSIX EBADF on any further settimeout.
            if self.response.closed:
                raise OSError(10038, 'An operation was attempted on something that is not a socket')
            self.timeout = value
        def connect(self, address):
            assert address == ('93.184.216.34', 443)
        def setsockopt(self, *args):
            pass
        def sendall(self, data):
            sent.append(data)
        def makefile(self, *args):
            return self.response
        def close(self):
            pass
    monkeypatch.setattr(socket, 'socket', Sock)
    def context():
        return SimpleNamespace(verify_mode=h.ssl.CERT_REQUIRED, check_hostname=True,
            wrap_socket=lambda raw, server_hostname: tls.append(server_hostname) or raw)
    monkeypatch.setattr(h.ssl, 'create_default_context', context)
    sample = h.HttpJsonSource().poll(definition(), None, {}, now=1, net=Gate()).sample
    assert sample['metrics'] == {'count': 12}
    assert tls == ['public.example']
    assert b'Host: public.example\r\n' in b''.join(sent)
    assert sockets[0].response.closed


def test_resolver_timeout_never_starts_http_after_late_dns(monkeypatch):
    import threading
    import time
    release, entered, finished = threading.Event(), threading.Event(), threading.Event()
    def resolve(*args, **kwargs):
        entered.set()
        release.wait(2)
        finished.set()
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('93.184.216.34', 443))]
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(h, 'TIMEOUT', 0.05)
    seen = fake_http(monkeypatch)
    start = time.monotonic()
    try:
        with pytest.raises(SourceError):
            h.HttpJsonSource().poll(definition(), None, {}, now=1, net=Gate())
        assert time.monotonic() - start < 1
        assert entered.is_set() and not seen
    finally:
        release.set()
        assert finished.wait(1)
    assert not seen


def test_header_slowloris_watchdog_and_cleanup(monkeypatch):
    import threading
    public_dns(monkeypatch)
    monkeypatch.setattr(h, 'TIMEOUT', 0.05)
    closed = threading.Event()
    class Connection:
        def __init__(self, *args, **kwargs):
            self.sock = SimpleNamespace(settimeout=lambda value: None,
                shutdown=lambda *args: closed.set(), close=lambda: closed.set())
        def request(self, *args, **kwargs):
            pass
        def getresponse(self):
            assert closed.wait(1)
            raise OSError('socket shutdown')
        def close(self):
            closed.set()
    monkeypatch.setattr(h, '_PinnedHTTPSConnection', Connection)
    with pytest.raises(SourceError):
        h.HttpJsonSource().poll(definition(), None, {}, now=1, net=Gate())
    assert closed.is_set()


def test_remote_rate_limit_body_persists_gate_and_sanitized_retry(tmp_path, monkeypatch):
    public_dns(monkeypatch)
    fake_http(monkeypatch, b'{"retry_after":123,"message":"sentinel-private"}', status=429)
    store = Store(tmp_path)
    net = Net(store, clock=lambda: 1000)
    with pytest.raises(SourceError) as error:
        h.HttpJsonSource().poll(definition(), None, {}, now=1000, net=net)
    assert error.value.status == 429 and error.value.retry_after == 123
    assert 'sentinel' not in str(error.value)
    assert store.gate('remote:public.example') == 1123
    assert net.usage()['used'] == 1


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
def test_icon_fetch_bytes_uses_pinned_transport_and_never_follows_redirects(monkeypatch, status):
    from pulse_rings.net import fetch_bytes
    public_dns(monkeypatch)
    seen = fake_http(monkeypatch, b'', status=status, headers={'Location': 'https://evil.example/icon'})
    with pytest.raises(SourceError) as error:
        fetch_bytes('https://public.example/icon.png', headers={'Accept': 'image/png'}, limit=262144, timeout=4)
    assert error.value.status == status
    assert len(seen) == 1 and seen[0]['host'] == 'public.example'


def test_icon_fetch_bytes_raw_raster_and_size_cap(monkeypatch):
    from pulse_rings.net import fetch_bytes
    public_dns(monkeypatch)
    png = bytes.fromhex('89504e470d0a1a0a') + b'pixel'
    seen = fake_http(monkeypatch, png, headers={'Content-Type': 'image/png'})
    raw, headers = fetch_bytes('https://public.example/icon.png', headers={'Accept': 'image/png'}, limit=262144)
    assert raw == png and headers['content-type'] == 'image/png'
    assert seen[0]['headers']['Accept'] == 'image/png'
    assert seen[0]['address'][1] == ('93.184.216.34', 443)
    fake_http(monkeypatch, b'x' * 262145, headers={'Content-Type': 'image/png'})
    with pytest.raises(SourceError, match='size limit'):
        fetch_bytes('https://public.example/icon.png', limit=262144)


def test_icon_fetch_bytes_private_dns_fails_before_connect(monkeypatch):
    from pulse_rings.net import fetch_bytes
    public_dns(monkeypatch, ['127.0.0.1'])
    seen = fake_http(monkeypatch, b'', headers={'Content-Type': 'image/png'})
    with pytest.raises(SourceError):
        fetch_bytes('https://public.example/icon.png', limit=262144)
    assert not seen
