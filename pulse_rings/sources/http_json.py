"""Approved arbitrary-host JSON counts, with real DNS-to-socket IP pinning.

Every outbound attempt goes through injected Net.call (one durable reservation).
Hermes's public URL-safety helper and safe-client API must be available; absent
APIs disable this source (no standalone fallback). Our pinned transport never
delegates DNS, proxies, redirects or TLS policy to
urllib/environment settings. It dials a vetted numeric sockaddr directly and keeps
TLS certificate verification/SNI and the HTTP Host bound to the approved hostname.
"""
import http.client
import ipaddress
import math
import queue
import re
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit

from .base import Deferred, SourceError, SourceResult
from ..net import BODY_LIMIT, retry_delay, strict_json
from ..version import VERSION

TIMEOUT = 8
_METRIC = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,39}\Z')
_ERROR = 'Public JSON source is unavailable. Cached values are preserved.'
_SAFE_ERRORS = frozenset((
    'Public JSON source timed out.',
    'Public JSON source returned an unsupported content type.',
    'Public JSON source returned unsupported compression.',
    'Public JSON response exceeded the size limit.',
    'Public JSON response was incomplete.',
    'Public JSON source returned invalid JSON.',
    'Public URL safety check refused this address.',
    'Public DNS resolver is busy.',
    'Public JSON requires Hermes URL-safety APIs; source disabled.',
))
_DNS_SLOTS = threading.BoundedSemaphore(4)  # Bound stuck OS resolver calls, not HTTP workers.


def _public_ip(text):
    if '%' in text:
        raise SourceError('Public URL safety check refused this address.')
    address = ipaddress.ip_address(text)
    # is_global alone includes multicast on some Python versions. Mapped and
    # transition wrappers are refused even if their embedded IPv4 is public.
    if (not address.is_global or address.is_private or address.is_reserved
            or address.is_multicast or address.is_loopback or address.is_link_local
            or address.is_unspecified or getattr(address, 'ipv4_mapped', None) is not None
            or (address.version == 6 and (address.sixtofour is not None or address.teredo is not None))):
        raise SourceError('Public URL safety check refused this address.')
    return address


def _url(url):
    if (not isinstance(url, str) or len(url) > 512
            or re.search(r'[\s\\\x00-\x1f\x7f{}]', url)
            or re.search(r'%(?:0[0-9a-f]|1[0-9a-f]|7f)', url, re.I)):
        raise SourceError('Invalid approved public HTTPS URL.')
    u = urlsplit(url)
    if (u.scheme != 'https' or not u.hostname or u.username is not None
            or u.password is not None or u.port not in (None, 443) or u.fragment
            or '%' in u.netloc):
        raise SourceError('Only public HTTPS on port 443 is supported.')
    # Refuse unusual port spellings rather than quietly repairing approval data.
    authority = u.netloc
    suffix = authority[authority.index(']') + 1:] if authority.startswith('[') else (
        ':' + authority.rsplit(':', 1)[1] if ':' in authority else '')
    if suffix not in ('', ':443'):
        raise SourceError('Only public HTTPS on port 443 is supported.')
    host = u.hostname.encode('idna').decode('ascii').lower().rstrip('.')
    check = host.rstrip('.')
    if (check in ('localhost', 'metadata.google.internal', 'metadata.goog')
            or check.endswith(('.localhost', '.local', '.internal'))):
        raise SourceError('Public URL safety check refused this address.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if len(host) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part)
                                      for part in check.split('.')):
            raise SourceError('Invalid approved public HTTPS host.')
    else:
        _public_ip(host)
    target = (u.path or '/') + ('?' + u.query if u.query else '')
    target.encode('ascii')  # Approved URLs must already be URI encoded.
    return host, target


def _hermes_check(url):
    """Documented public API; failure is never mistaken for an absent dependency."""
    try:
        from tools.url_safety import is_safe_url, create_ssrf_safe_async_client
    except ImportError:
        raise SourceError('Public JSON requires Hermes URL-safety APIs; source disabled.') from None
    if not callable(is_safe_url) or not callable(create_ssrf_safe_async_client):
        raise SourceError('Public JSON requires Hermes URL-safety APIs; source disabled.')
    # Availability is mandatory; the request itself uses our stricter numeric-IP
    # pinned socket, not a helper-only DNS preflight or the generic async client.
    if not is_safe_url(url):
        raise SourceError('Public URL safety check refused this address.')


def _resolve(host):
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    vetted = []
    for family, socktype, proto, _, sockaddr in answers:
        if family not in (socket.AF_INET, socket.AF_INET6) or socktype != socket.SOCK_STREAM:
            raise SourceError('Public DNS answer was unsupported.')
        address = _public_ip(sockaddr[0])
        if sockaddr[1] != 443 or (family == socket.AF_INET6 and (len(sockaddr) != 4 or sockaddr[3] != 0)):
            raise SourceError('Public DNS answer was unsupported.')
        if (family == socket.AF_INET) != (address.version == 4):
            raise SourceError('Public DNS answer was unsupported.')
        vetted.append((family, sockaddr))
    if not vetted:
        raise SourceError('Public DNS did not return a usable address.')
    # Validate ALL answers before dialing ANY. A mixed public/private answer fails.
    return vetted[0]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, *, timeout):
        super().__init__(host, port=443, timeout=timeout, context=ssl.create_default_context())
        self._address = address

    def connect(self):
        family, sockaddr = self._address
        raw = socket.socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        try:
            deadline = time.monotonic() + self.timeout
            raw.settimeout(_remaining(deadline))
            raw.connect(sockaddr)  # Numeric vetted tuple; NO second name lookup.
            raw.settimeout(_remaining(deadline))
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SourceError('Public JSON source timed out.')
    return remaining


def _vetted_address(host, deadline):
    # OS getaddrinfo has no portable timeout. A bounded daemon resolver cannot
    # initiate HTTP; late DNS results are discarded, never dialed in background.
    if not _DNS_SLOTS.acquire(blocking=False):
        raise SourceError('Public DNS resolver is busy.')
    result = queue.Queue(maxsize=1)
    def resolve():
        try:
            origin = 'https://' + ('[' + host + ']' if ':' in host else host) + '/'
            _hermes_check(origin)  # Do not send a path/query into helper logs.
            result.put((True, _resolve(host)))
        except Exception:
            result.put((False, None))
        finally:
            _DNS_SLOTS.release()
    worker = threading.Thread(target=resolve, name='pulse-json-dns', daemon=True)
    try:
        worker.start()
    except Exception:
        _DNS_SLOTS.release()
        raise
    try:
        okay, address = result.get(timeout=_remaining(deadline))
    except queue.Empty:
        raise SourceError('Public JSON source timed out.') from None
    if not okay:
        raise SourceError('Public URL safety check refused this address.')
    return address


def _fetch(url, host, target, *, now, raw_response=False, limit=BODY_LIMIT,
           accept='application/json', timeout=TIMEOUT):
    if raw_response and now is None:
        now = time.time()
    deadline = time.monotonic() + min(timeout, TIMEOUT)
    limit = min(limit, BODY_LIMIT)
    address = _vetted_address(host, deadline)
    connection = _PinnedHTTPSConnection(host, address, timeout=_remaining(deadline))
    response, network_socket = None, None
    def abort():
        try:
            active = network_socket if network_socket is not None else connection.sock
            active.shutdown(socket.SHUT_RDWR)
            active.close()
        except (AttributeError, OSError):
            pass
    # A socket timeout alone resets on every header line and permits slowloris.
    watchdog = threading.Timer(_remaining(deadline), abort)
    watchdog.daemon = True
    watchdog.start()
    try:
        # http.client neither follows redirects nor uses proxy/cookie/netrc state.
        connection.request('GET', target, headers={
            'Host': '[' + host + ']' if ':' in host else host,
            'User-Agent': f'PulseRings/{VERSION} (Hermes public signals)',
            'Accept': accept, 'Accept-Encoding': 'identity', 'Connection': 'close'})
        network_socket = connection.sock
        network_socket.settimeout(_remaining(deadline))
        response = connection.getresponse()
        headers = {key.lower(): value for key, value in response.getheaders()}
        status = response.status
        if not 200 <= status < 300:
            # Redirects are never followed or consumed. Bounded error JSON may
            # carry retry_after (no body or remote message crosses the boundary).
            raw_error = b''
            if status in (403, 429):
                raw_error = response.read(4096)
            raise SourceError('Public JSON endpoint refused the request.', status,
                              retry_delay(status, headers, raw_error, now=now))
        mime = headers.get('content-type', '').split(';', 1)[0].strip().lower()
        if not raw_response and not (mime == 'application/json' or re.fullmatch(r'application/[a-z0-9!#$&^_.+-]+\+json', mime)):
            raise SourceError('Public JSON source returned an unsupported content type.')
        if headers.get('content-encoding', 'identity').strip().lower() not in ('', 'identity'):
            raise SourceError('Public JSON source returned unsupported compression.')
        if 'content-length' in headers:
            if not re.fullmatch(r'[0-9]+', headers['content-length']) or int(headers['content-length']) > limit:
                raise SourceError('Public JSON response exceeded the size limit.')
        raw = bytearray()
        # http.client closes the response (and, once its makefile reference
        # drops, the real socket) as soon as a Content-Length or chunked body
        # is complete. Re-arming the timeout after that raises WinError 10038
        # on Windows / EBADF on POSIX, so stop at a closed response.
        while not response.isclosed():
            network_socket.settimeout(_remaining(deadline))
            chunk = response.read1(min(65536, limit + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > limit:
                raise SourceError('Public JSON response exceeded the size limit.')
        _remaining(deadline)
        # read1() accepts premature EOF without raising IncompleteRead. Do not
        # mistake a parseable prefix for a complete declared-length response.
        if ('content-length' in headers and not getattr(response, 'chunked', False)
                and len(raw) != int(headers['content-length'])):
            raise SourceError('Public JSON response was incomplete.')
        if raw_response:
            return bytes(raw), headers
        try:
            return strict_json(bytes(raw))
        except (ValueError, UnicodeError, RecursionError):
            raise SourceError('Public JSON source returned invalid JSON.') from None
    finally:
        watchdog.cancel()
        if response is not None:
            response.close()
        connection.close()


def json_pointer(document, pointer):
    """RFC 6901, no expressions, URL fragments, attribute traversal or eval."""
    if (not isinstance(pointer, str) or len(pointer) > 512
            or (pointer and not pointer.startswith('/')) or re.search(r'~(?![01])', pointer)):
        raise SourceError('Invalid approved JSON Pointer.')
    value = document
    for token in pointer.split('/')[1:] if pointer else ():
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict):
            value = value.get(token)
        elif isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*', token):
            # Bound before int conversion; malicious indexes cannot exceed a capped body.
            if len(token) > 9 or int(token) >= len(value):
                return None
            value = value[int(token)]
        else:
            return None
    return value


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


class HttpJsonSource:
    arbitrary_host = True
    pre_approval_sample = False

    def poll(self, definition, previous, state, *, now, net):
        """Approval belongs to the human activation seam, NEVER proposal preview."""
        try:
            params = definition['source']['params']
            if set(params) - {'url', 'metrics'} - {key for key in params if key.startswith('x-')}:
                raise SourceError('Unsupported approved public JSON parameters.')
            host, target = _url(params['url'])
            pointers = params['metrics']
            if (not isinstance(pointers, dict) or not 1 <= len(pointers) <= 6
                    or not all(isinstance(name, str) and _METRIC.fullmatch(name) for name in pointers)):
                raise SourceError('Invalid approved public JSON metrics.')
            for pointer in pointers.values():
                json_pointer(None, pointer)  # Validate all selectors before any network.
            body = net.call(host, lambda: _fetch(params['url'], host, target, now=now))
            metrics = {name: _number(json_pointer(body, pointer)) for name, pointer in pointers.items()}
            return SourceResult(sample={'ts': now, 'metrics': metrics, 'baselines': {},
                'unknown_reasons': {name: 'JSON metric missing or not a finite number.'
                                    for name, value in metrics.items() if value is None}})
        except Deferred:
            raise  # Local pacing/ceiling is never a remote failure.
        except SourceError as exc:
            # Only locally authored, exact allowlisted messages cross this boundary.
            status = exc.status if type(exc.status) is int and 100 <= exc.status <= 599 else 0
            message = ('Public JSON redirect refused. Use the final HTTPS endpoint in a replacement definition.'
                       if 300 <= status < 400 else {
                           404: 'Public JSON endpoint not found. Check its approved definition.',
                           429: 'Public JSON source rate limited. Waiting before retry.',
                       }.get(status, str(exc) if str(exc) in _SAFE_ERRORS else None))
            raise SourceError(message + ' Cached values are preserved.' if message else _ERROR,
                              status=status, retry_after=exc.retry_after) from None
        except TimeoutError:
            raise SourceError('Public JSON source timed out. Cached values are preserved.') from None
        except Exception:
            raise SourceError(_ERROR) from None
