"""Approved backend-only icon resolution. Status reads never perform egress.

Remote SVG/XML is never accepted. A renderer receives a local cache identity or
bundled, strictly validated path data, never a remote URL or server SVG markup.
"""
import base64
import binascii
import hashlib
import os
import re
import uuid
from urllib.parse import urlsplit

from . import brands, desktop_apps, mcp_access, net as network
from .icons import image_type
from .net import validate_url
from .sources.base import Deferred, SourceError

LIMIT = 256 * 1024
FAILURE_SECONDS = 6 * 3600
KEY_RE = re.compile(r'sha256-[a-f0-9]{64}\Z')
RASTER = ('image/png', 'image/webp', 'image/jpeg')
# Sites whose feeds get their own bundled logo: the name directly before .com, never a subdomain.
FEED_SITES = frozenset(('github', 'gitlab', 'reddit', 'youtube', 'ycombinator', 'medium', 'substack', 'wordpress', 'blogger'))
# Original, bundled winged H monogram; not a Simple Icons asset/trademark grant.
HERMES = {'kind': 'brand', 'slug': 'hermes', 'hex': '8B7CF8',
          'path': 'M5 3h4v7h6V3h4v18h-4v-7H9v7H5V3ZM0 4h4v3H2L0 4Zm24 0-2 3h-2V4h4Z'}


def _field(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _icon_groups(server, tool):
    """MCPServerTask-shaped metadata only; no calls, discovery or reconnects."""
    tools = _field(server, '_tools', []) or []
    selected = next((item for item in tools if _field(item, 'name') == tool), None)
    info = _field(_field(server, 'initialize_result'), 'serverInfo')
    return (_field(selected, 'icons', []) or [], _field(info, 'icons', []) or [])


def _rank(icon):
    mime = _field(icon, 'mimeType')
    sizes = _field(icon, 'sizes', []) or []
    distances = []
    for size in sizes if isinstance(sizes, list) else []:
        match = re.fullmatch(r'([0-9]{1,5})x([0-9]{1,5})', size) if isinstance(size, str) else None
        if match:
            width, height = int(match[1]), int(match[2])
            distances.append(max(64 - width, width - 128, 64 - height, height - 128, 0))
    return (0 if mime in RASTER else 1, min(distances, default=100000))


def _feeds(definition):
    return list(definition['feeds'].values()) if 'feeds' in definition else [definition.get('source', {})]


def _brand(slug):
    value = brands.brand(slug)
    return {'kind': 'brand', 'slug': slug, 'hex': value['hex'], 'path': value['path']} if value else None


class IconResolver:
    def __init__(self, store, net, discord, *, fetch=None, mcp_servers=None):
        self.store, self.net, self.discord = store, net, discord
        self.root = store.root
        self.fetch = fetch
        self.mcp_servers = mcp_servers

    def path(self, key):
        if not isinstance(key, str) or not KEY_RE.fullmatch(key):
            raise ValueError('Invalid icon identity')
        return self.root / 'icons' / (key + '.image')

    def _raw(self, key):
        try:
            path = self.path(key)
            if (path.is_symlink() or path.parent.is_symlink()
                    or not path.resolve().is_relative_to(self.root.resolve())):
                return None
            with path.open('rb') as stream:
                raw = stream.read(LIMIT + 1)
            return raw if len(raw) <= LIMIT and image_type(raw) else None
        except (ValueError, OSError):
            return None

    def data(self, key):
        raw = self._raw(key)
        return ('data:' + image_type(raw) + ';base64,' + base64.b64encode(raw).decode('ascii')) if raw else None

    def _write(self, key, raw):
        path = self.path(key)
        path.parent.mkdir(exist_ok=True)
        if (path.is_symlink() or path.parent.is_symlink()
                or not path.resolve().is_relative_to(self.root.resolve())):
            return False
        temp = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        try:
            # Exclusive creation also refuses pre-existing temp symlinks.
            with temp.open('xb') as stream:
                stream.write(raw)
            os.replace(temp, path)
            return True
        finally:
            temp.unlink(missing_ok=True)

    def _raster(self, src, hosts, approved, fetch, declared_mime=None):
        if not approved or not isinstance(src, str):
            return None
        local = src.startswith('data:')
        if local:
            if len(src) > (LIMIT + 2) // 3 * 4 + 64:
                return None
        else:
            try:
                host = validate_url(src)
            except (ValueError, UnicodeError):
                return None
            # Require EXACT persisted host membership, including for cache reads.
            if host not in hosts:
                return None
        key = 'sha256-' + hashlib.sha256(src.encode('utf-8')).hexdigest()
        cached = self._raw(key)
        result = {'kind': 'raster', 'url': '/icons/' + key}
        if cached is not None:
            return result if declared_mime is None or image_type(cached) == declared_mime else None
        if not fetch:
            return None
        gate_key, now = 'icon:' + key, self.net.clock()
        with self.store.transaction() as db:
            gate = db.execute('SELECT until_ts FROM gates WHERE key=?', (gate_key,)).fetchone()
            if gate and gate[0] > now:
                return None
            db.execute('INSERT OR REPLACE INTO gates VALUES (?,?)', (gate_key, now + FAILURE_SECONDS))
        try:
            if local:
                header, payload = src.split(',', 1)
                match = re.fullmatch(r'data:(image/(?:png|webp|jpeg));base64', header)
                if not match:
                    return None
                raw, mime = base64.b64decode(payload, validate=True), match[1]
            else:
                raw, headers = self.net.call(host, lambda: (self.fetch or network.fetch_bytes)(src,
                    headers={'Accept': ','.join(RASTER)}, timeout=4, limit=LIMIT))
                mime = next((v for k, v in headers.items() if k.lower() == 'content-type'), '').split(';')[0].strip().lower()
            actual = image_type(raw) if isinstance(raw, bytes) and len(raw) <= LIMIT else None
            if not actual or actual != mime or (declared_mime is not None and actual != declared_mime):
                return None
            return result if self._write(key, raw) else None
        except Deferred:
            # Local pacing isn't a failed fetch. Permit another viewed tick.
            with self.store.transaction() as db:
                db.execute('DELETE FROM gates WHERE key=? AND until_ts=?', (gate_key, now + FAILURE_SECONDS))
            return None
        except (SourceError, ValueError, OSError, binascii.Error, UnicodeError):
            return None

    def resolve(self, definition, *, metadata=None, budget=None, approved=False, fetch=False):
        metadata, budget = metadata or {}, budget or {}
        hosts = budget.get('hosts', [])
        feeds = _feeds(definition)
        kinds = [f.get('kind', '').split('@')[0] for f in feeds]
        initials = ''.join(part[0] for part in str(definition.get('title', '?')).split()[:2]).upper() or '?'
        fallback = next((_brand(k.split('.')[0]) for k in kinds if k.startswith(('github.', 'discord.'))), None)
        fallback = fallback or {'kind': 'initials', 'text': initials}
        icon = definition.get('icon', 'source')
        if isinstance(icon, dict):
            if 'brand' in icon:
                return _brand(icon['brand']) or fallback
            if 'emoji' in icon:
                return {'kind': 'emoji', 'text': icon['emoji']}
            if 'url' in icon:
                return self._raster(icon['url'], hosts, approved, fetch) or fallback
            return fallback
        if icon == 'initials':
            return {'kind': 'initials', 'text': initials}
        if icon == 'hermes':
            return dict(HERMES)
        if icon != 'source':
            return {'kind': 'emoji', 'text': icon}
        if any(k.startswith('discord.') for k in kinds):
            url = self.discord.url(metadata)
            if url and self.discord.data(metadata):
                return {'kind': 'raster', 'url': url}
        for feed, kind in zip(feeds, kinds):
            if kind.startswith('github.'):
                # github.repo currently exposes counts only. The approved repo
                # owner's login is sufficient; never trust an arbitrary avatar_url.
                owner = feed.get('params', {}).get('repo', '').split('/')[0]
                if re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})', owner):
                    got = self._raster('https://avatars.githubusercontent.com/' + owner + '?s=128', hosts, approved, fetch)
                    if got:
                        return got
        for feed, kind in zip(feeds, kinds):
            if kind == 'mcp.tool':
                params = feed.get('params', {})
                if self.mcp_servers is not None:
                    groups = _icon_groups(self.mcp_servers().get(params.get('server')), params.get('tool'))
                else:
                    groups = mcp_access.declared_icons(self.root, params.get('server'), params.get('tool'))
                for group in groups:
                    for item in sorted(group, key=_rank):
                        mime = _field(item, 'mimeType')
                        if mime is not None and mime not in RASTER:
                            continue
                        got = self._raster(_field(item, 'src'), hosts, approved, fetch, mime)
                        if got:
                            return got
        for feed, kind in zip(feeds, kinds):
            if kind == 'desktop.notifications':
                slug = desktop_apps.brand(feed.get('params', {}))
                got = _brand(slug) if slug else None
                if got:
                    return got
        for feed, kind in zip(feeds, kinds):
            if kind == 'web.feed':
                # A bundled logo for a well-known site, else the feed mark. No request is made.
                try:
                    labels = (urlsplit(str(feed.get('params', {}).get('url', ''))).hostname or '').lower().split('.')
                except ValueError:
                    labels = []
                site = labels[-2] if len(labels) >= 2 and labels[-1] == 'com' and labels[-2] in FEED_SITES else 'rss'
                got = _brand(site) or _brand('rss')
                if got:
                    return got
        if 'hermes.activity' in kinds:
            return dict(HERMES)
        return fallback
