"""Backend-only, hash-keyed static Discord icon cache. No renderer egress."""
import base64
import os
import re
import uuid

from .net import BODY_LIMIT, fetch_bytes
from .sources.base import SourceError

GUILD_RE = re.compile(r'[0-9]{15,22}\Z')
ICON_RE = re.compile(r'(a_)?[a-f0-9]{32}\Z')
ICON_LIMIT = min(BODY_LIMIT, 256 * 1024)


def image_type(raw):
    if len(raw) > ICON_LIMIT:
        return None
    if raw.startswith(b'\x89PNG\x0d\x0a\x1a\x0a'):
        return 'image/png'
    if raw.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if len(raw) >= 12 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        return 'image/webp'
    return None


def discord_icon_get(gid, icon_hash):
    if not GUILD_RE.fullmatch(gid) or not ICON_RE.fullmatch(icon_hash):
        raise ValueError('Invalid icon identity')
    raw, headers = fetch_bytes(f'https://cdn.discordapp.com/icons/{gid}/{icon_hash}.png?size=128',
                               headers={'Accept': 'image/png,image/webp,image/jpeg'}, timeout=4, limit=ICON_LIMIT)
    mime = next((v for k, v in headers.items() if k.lower() == 'content-type'), '').split(';')[0].strip().lower()
    if image_type(raw) is None or image_type(raw) != mime:
        raise SourceError('Server icon was not a supported image.')
    return raw


class IconCache:
    def __init__(self, store, net, fetch=discord_icon_get):
        self.store, self.net, self.fetch = store, net, fetch
        self.root = store.root

    def path(self, gid, icon_hash):
        if not GUILD_RE.fullmatch(gid) or not isinstance(icon_hash, str) or not ICON_RE.fullmatch(icon_hash):
            raise ValueError('Invalid icon identity')
        return self.root / 'icons' / f'{gid}-{icon_hash}.image'

    def url(self, data):
        gid, icon_hash = data.get('id'), data.get('icon_hash')
        if not isinstance(gid, str) or not isinstance(icon_hash, str):
            return None
        try:
            path = self.path(gid, icon_hash)
            return (f'/icons/{gid}-{icon_hash}' if path.is_file() and not path.is_symlink()
                    and not path.parent.is_symlink() and path.resolve().is_relative_to(self.root.resolve()) else None)
        except (ValueError, OSError):
            return None

    def data(self, data):
        if not data.get('icon_hash'):
            return None
        path = self.path(data['id'], data['icon_hash'])
        try:
            if path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()):
                return None
            with path.open('rb') as stream:
                raw = stream.read(ICON_LIMIT + 1)
            mime = image_type(raw)
            return 'data:' + mime + ';base64,' + base64.b64encode(raw).decode('ascii') if mime else None
        except OSError:
            return None

    def cache(self, data):
        if not data.get('icon_hash') or self.data(data):
            return
        key = 'icon:' + data['id'] + ':' + data['icon_hash']
        now = self.net.clock()
        with self.store.transaction() as db:
            gate = db.execute('SELECT until_ts FROM gates WHERE key=?', (key,)).fetchone()
            if gate and gate[0] > now:
                return
            db.execute('INSERT OR REPLACE INTO gates VALUES (?,?)', (key, now + 6 * 3600))
        temp = None
        try:
            raw = self.net.call('cdn.discordapp.com', lambda: self.fetch(data['id'], data['icon_hash']))
            if not isinstance(raw, bytes) or image_type(raw) is None:
                return
            path = self.path(data['id'], data['icon_hash'])
            path.parent.mkdir(exist_ok=True)
            if path.parent.is_symlink() or not path.parent.resolve().is_relative_to(self.root.resolve()):
                return
            temp = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
            temp.write_bytes(raw)
            os.replace(temp, path)
        except (SourceError, OSError, ValueError):
            pass
        finally:
            if temp is not None:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass
