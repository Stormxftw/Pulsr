"""HTTPS GETs only: capped bodies, no redirects, durable cross-process budgets.

Fixed-host adapters can run without Hermes using the stdlib transport. Arbitrary
hosts use the shared IP-pinned transport and fail closed unless Hermes's public
URL-safety APIs are available. Icon callers must first enforce approval and exact
persisted host disclosure; Net.bytes remains fixed-host-only.
No network I/O holds a SQLite write transaction.
"""
from contextlib import closing
from email.utils import parsedate_to_datetime
import http.client
import ipaddress
import json
import math
from .version import VERSION
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .sources.base import SourceError, Deferred
from .limits import DEFAULT_REQUESTS_PER_HOUR, MAX_RETRY_SECONDS, NOT_FOUND_RETRY_SECONDS

BODY_LIMIT = 512 * 1024
FIXED_HOSTS = frozenset(('discord.com', 'cdn.discordapp.com', 'api.github.com', 'avatars.githubusercontent.com'))
NetworkError = SourceError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def strict_json(raw):
    def invalid(_):
        raise ValueError('Nonfinite JSON number')
    def finite_float(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError('Nonfinite JSON number')
        return value
    return json.loads(raw, parse_constant=invalid, parse_float=finite_float)


def validate_url(url):
    if not isinstance(url, str) or len(url) > 2048 or re.search(r'[\s\\\x00-\x1f\x7f]', url):
        raise ValueError('Invalid HTTPS URL')
    u = urllib.parse.urlsplit(url)
    if (u.scheme != 'https' or not u.hostname or u.username is not None or u.password is not None
            or u.port not in (None, 443) or u.fragment or '%' in u.netloc):
        raise ValueError('Only public HTTPS URLs without credentials or fragments are accepted')
    host = u.hostname.lower()
    if host in ('localhost', 'metadata.google.internal') or host.endswith(('.localhost', '.local', '.internal')):
        raise ValueError('Private and metadata hosts are refused')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError('Private and metadata addresses are refused')
    return host


def retry_delay(status, headers, raw=b'', now=None):
    """Discord retry_after, HTTP Retry-After and GitHub reset; sanitized and finite."""
    now = time.time() if now is None else now
    h = {k.lower(): v for k, v in headers.items()}
    delays = []
    try:
        body = strict_json(raw)
        value = body.get('retry_after') if isinstance(body, dict) else None
        if value is not None and not isinstance(value, bool):
            delays.append(float(value))
    except (ValueError, TypeError, UnicodeError):
        pass
    if 'retry-after' in h:
        try:
            delays.append(float(h['retry-after']))
        except (ValueError, TypeError):
            try:
                delays.append(parsedate_to_datetime(h['retry-after']).timestamp() - now)
            except (ValueError, TypeError, OverflowError):
                pass
    if h.get('x-ratelimit-remaining') == '0' and 'x-ratelimit-reset' in h:
        try:
            delays.append(float(h['x-ratelimit-reset']) - now)
        except (ValueError, TypeError):
            pass
    delays = [d for d in delays if math.isfinite(d) and d >= 0]
    return min(NOT_FOUND_RETRY_SECONDS if status == 404 else MAX_RETRY_SECONDS, max([2] + delays) if delays else 600)


# Fixed GitHub authorization refusals (integration/token scope, organization SAML).
_PERMISSION_403 = ('resource not accessible by ', 'resource protected by organization saml enforcement')
_LIMIT_EVIDENCE = re.compile(r'rate.?limit|abuse|retry', re.IGNORECASE)


def permission_denied(status, headers, raw):
    """True only for an affirmative authorization refusal, never an inferred one.

    Requires every one of: status 403, a JSON object whose message is a
    recognized fixed permission refusal, and no retry or rate-limit evidence
    anywhere in the headers or body. The recognized message is the affirmative
    evidence; quota headers can only veto it. An absent x-ratelimit-remaining
    is not rate-limit evidence (GitHub omits it on some permission refusals),
    but a present one must be a positive integer: exhausted ('0'), empty or
    malformed values stay False. Secondary limits may also omit rate headers,
    but they never carry a permission message, so an empty, non-JSON, unknown
    or ambiguous body keeps the conservative shared backoff with or without
    headers. Returns a boolean; no body is kept.
    """
    if status != 403:
        return False
    remaining = []  # Every occurrence: a repeated header must not hide a bad value.
    for key, value in headers.items():
        name = str(key).lower()
        if name == 'retry-after':
            return False
        if name == 'x-ratelimit-remaining':
            remaining.append(str(value).strip())
    if any(not re.fullmatch(r'[0-9]{1,12}', value) or int(value) < 1 for value in remaining):
        return False
    try:
        body = strict_json(raw)
        if not isinstance(body, dict) or 'retry_after' in body:
            return False
        message = body.get('message')
        if not isinstance(message, str) or not message.strip().casefold().startswith(_PERMISSION_403):
            return False
        # Scan the whole object (keys and nested values), not just top-level strings.
        return not _LIMIT_EVIDENCE.search(json.dumps(body, ensure_ascii=False))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return False


def _http_error(status, headers, raw, now=None):
    # Secondary GitHub 403 limits may omit rate headers. Conservatively back off
    # every 403 except an affirmative permission refusal (permission_denied),
    # which is recognized by its fixed message with or without quota headers; a
    # Discord widget adapter handles its 403 as unavailable instead.
    delay = retry_delay(status, headers, raw, now)
    message = {404: 'Public source not found. Check its approved definition.',
               403: 'Public source unavailable or rate limited.',
               429: 'Source rate limited. Waiting before retry.'}.get(status, 'Public source is temporarily unavailable.')
    error = NetworkError(message, status, delay)
    # Boolean classification only: upstream text never crosses this boundary.
    error.permission_denied = permission_denied(status, headers, raw)
    return error


def _headers(host, headers=None, accept='application/json'):
    result = {'User-Agent': f'PulseRings/{VERSION} (Hermes public signals)', 'Accept': accept,
              'Accept-Encoding': 'identity'}
    for key, value in (headers or {}).items():
        if key.lower() == 'authorization' and host != 'api.github.com':
            raise ValueError('Authorization is bound to api.github.com')
        if key.lower() not in ('authorization', 'accept', 'x-github-api-version'):
            raise ValueError('Unsupported request header')
        result[key] = value
    return result


def fetch_bytes(url, *, headers=None, timeout=8, limit=BODY_LIMIT, json_response=False, now=None):
    """Capped no-redirect GET; arbitrary hosts use the shared pinned safe transport.

    Authorization/disclosure is enforced by callers before reaching this transport.
    """
    host = validate_url(url)
    limit, timeout = min(limit, BODY_LIMIT), min(timeout, 8)
    if host not in FIXED_HOSTS:
        from .sources.http_json import _url, _fetch
        host, target = _url(url)
        request_headers = _headers(host, headers)
        try:
            raw, response_headers = _fetch(url, host, target, now=now, raw_response=True,
                limit=limit, timeout=timeout, accept=request_headers['Accept'])
        except (OSError, ValueError, http.client.HTTPException):
            raise NetworkError('Could not reach public icon source. Cached values are preserved.') from None
        mime = response_headers.get('content-type', '').split(';')[0].strip().lower()
        if json_response and not (mime == 'application/json' or mime.endswith('+json')):
            raise NetworkError('Public source returned an unsupported content type')
        return raw, response_headers
    request = urllib.request.Request(url, headers=_headers(host, headers), method='GET')
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(limit + 1)
            if len(raw) > limit:
                raise NetworkError('Public response exceeded size limit')
            mime = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
            if json_response and not (mime == 'application/json' or mime.endswith('+json')):
                raise NetworkError('Public source returned an unsupported content type')
            return raw, dict(response.headers)
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read(4096)
        except (OSError, ValueError, http.client.HTTPException):
            raw = b''
        finally:
            exc.close()
        raise _http_error(exc.code, exc.headers or {}, raw, now=now) from None
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise NetworkError('Could not reach public source. Cached values are preserved.') from None


def fetch_json(url, *, headers=None):
    raw, _ = fetch_bytes(url, headers=headers, json_response=True)
    try:
        return strict_json(raw)
    except (ValueError, UnicodeError):
        raise NetworkError('Public source returned invalid JSON') from None


class Net:
    def __init__(self, store, *, clock=time.time, ceiling=DEFAULT_REQUESTS_PER_HOUR):
        if isinstance(ceiling, bool) or not isinstance(ceiling, int) or ceiling < 1:
            raise ValueError('Request ceiling must be a positive integer')
        self.store, self.clock, self.ceiling = store, clock, ceiling
        self.cancelled = lambda: False

    def reserve(self, host):
        if self.cancelled():
            raise Deferred('Collection stopped.', 0, 5)
        now = self.clock()
        with self.store.transaction() as db:
            db.execute("DELETE FROM gates WHERE key LIKE 'request:%' AND until_ts<=?", (now,))
            row = db.execute('SELECT until_ts FROM gates WHERE key=?', ('host:' + host,)).fetchone()
            if row and row[0] > now:
                raise Deferred('Source is pacing requests. Try again shortly.', 429, row[0] - now)
            count, earliest = db.execute("SELECT count(*), MIN(until_ts) FROM gates WHERE key LIKE 'request:%'").fetchone()
            if count >= self.ceiling:
                raise Deferred('Profile request ceiling reached. Waiting before retry.', 429, max(2, earliest - now))
            db.execute('INSERT OR REPLACE INTO gates VALUES (?,?)', ('host:' + host, now + 2))
            db.execute('INSERT INTO gates VALUES (?,?)', ('request:' + uuid.uuid4().hex, now + 3600))

    def call(self, host, callback):
        """Gate even injected transports and icon requests, never bypass the budget."""
        self.reserve(host)
        if self.cancelled():
            raise Deferred('Collection stopped.', 0, 5)
        try:
            return callback()
        except Deferred:
            raise
        except SourceError as exc:
            # One repository or endpoint refusing access is not a host-wide limit.
            # Only the transport boundary sets this flag; unclassified, ambiguous
            # and rate-limited 403s (and every 429) keep the shared backoff.
            refused = exc.status == 403 and getattr(exc, 'permission_denied', False) is True
            if exc.status == 429 or (exc.status == 403 and host == 'api.github.com' and not refused):
                self.store.extend_gate('host:' + host, self.clock() + exc.retry_after)
                self.store.extend_gate('remote:' + host, self.clock() + exc.retry_after)
            raise

    def bytes(self, url, *, headers=None, timeout=8, limit=BODY_LIMIT):
        host = validate_url(url)
        limit, timeout = min(limit, BODY_LIMIT), min(timeout, 8)
        _headers(host, headers)  # Reject header/credential scope before reserving a request.
        if host not in FIXED_HOSTS:
            raise ValueError('Host is not declared by a built-in source')
        callback = lambda: fetch_bytes(url, headers=headers, timeout=timeout, limit=limit, now=self.clock())
        return self.call(host, callback)

    def json(self, url, *, headers=None):
        raw, response_headers = self.bytes(url, headers=headers)
        mime = next((v for k, v in response_headers.items() if k.lower() == 'content-type'), '').split(';')[0].strip().lower()
        if not (mime == 'application/json' or mime.endswith('+json')):
            raise NetworkError('Public source returned an unsupported content type')
        try:
            return strict_json(raw)
        except (ValueError, UnicodeError):
            raise NetworkError('Public source returned invalid JSON') from None

    def usage(self, *, db=None):
        now = self.clock()
        with self.store.read(db) as db:
            used = db.execute("SELECT count(*) FROM gates WHERE key LIKE 'request:%' AND until_ts>?", (now,)).fetchone()[0]
        return {'used': used, 'ceiling': self.ceiling, 'window_seconds': 3600}
