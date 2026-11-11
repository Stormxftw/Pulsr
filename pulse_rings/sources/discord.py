"""Discord reference source: public invite counts and optional redacted widget."""
import copy
import re
import urllib.parse

from .base import SourceError, SourceResult, Deferred
from ..icons import GUILD_RE
from ..net import fetch_json

CODE_RE = re.compile(r'[A-Za-z0-9_-]{2,64}\Z')
DiscordError = SourceError


def parse_invite(value):
    if not isinstance(value, str) or len(value) > 256:
        raise ValueError('Paste a Discord invite link or a 2–64 character invite code.')
    text = value.strip()
    if CODE_RE.fullmatch(text):
        return text
    if text.startswith(('discord.gg/', 'discord.com/invite/')):
        text = 'https://' + text
    u = urllib.parse.urlsplit(text)
    if u.scheme != 'https' or u.netloc not in ('discord.gg', 'discord.com', 'www.discord.com') or u.fragment:
        raise ValueError('Only https Discord invite links or invite codes are accepted.')
    prefix = '/' if u.netloc == 'discord.gg' else '/invite/'
    code = u.path[len(prefix):] if u.path.startswith(prefix) else ''
    if not CODE_RE.fullmatch(code):
        raise ValueError('Invalid Discord invite path. Paste the original invite, without extra path segments.')
    return code


def discord_get(path):
    if not re.fullmatch(r'/api/(v10/invites/[A-Za-z0-9_-]{2,64}\?with_counts=true|v10/guilds/[0-9]{15,22}/widget\.json)', path):
        raise ValueError('Unsupported public API path')
    try:
        return fetch_json('https://discord.com' + path)
    except SourceError as exc:
        if exc.status == 404:
            raise DiscordError('Invite expired or invalid. Replace it to resume polling.', 404, exc.retry_after) from None
        raise


def normalize_invite(raw):
    guild = raw.get('guild') if isinstance(raw, dict) else None
    if not isinstance(guild, dict):
        raise DiscordError('This invite does not resolve to a Discord server.')
    gid = str(guild.get('id', ''))
    if not GUILD_RE.fullmatch(gid) or not isinstance(guild.get('name'), str):
        raise DiscordError('This invite does not resolve to a Discord server.')
    def count(key):
        v = raw.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None
    icon = guild.get('icon')
    icon = icon if isinstance(icon, str) and re.fullmatch(r'(a_)?[a-f0-9]{32}', icon) else None
    description = guild.get('description')
    features = guild.get('features')
    return {'id': gid, 'name': guild['name'][:100], 'description': description[:1000] if isinstance(description, str) else '',
            'icon_hash': icon, 'online': count('approximate_presence_count'), 'members': count('approximate_member_count'),
            'features': [str(f)[:80] for f in features[:30]] if isinstance(features, list) else [],
            'boost_tier': guild.get('premium_tier'), 'boost_count': guild.get('premium_subscription_count')}


def preset(invite, *, pulse_id, title):
    """Compatibility helper for the old human Add route, not a validator/preset registry."""
    code = parse_invite(invite)
    return {'pulse': 1, 'id': pulse_id, 'title': title[:60],
            'source': {'kind': 'discord.invite@1', 'params': {'invite': code, 'voice': True}},
            'every': '10m', 'ring': {'components': [
                {'metric': 'online', 'weight': 70, 'type': 'delta', 'baseline': 'median', 'window': '24h', 'floor': 25, 'sensitivity': .2, 'direction': 'both'},
                {'metric': 'members', 'weight': 20, 'type': 'delta', 'baseline': 'oldest', 'window': '24h', 'floor': 100, 'sensitivity': .01, 'direction': 'both'},
                {'metric': 'voice_channels', 'weight': 10, 'type': 'level', 'full_at': 5}]},
            'capsule': {'metric': 'online', 'label': '{value} online', 'fill': 'baseline'},
            'lines': [{'metric': 'members', 'show': 'delta', 'label': 'Net {delta} members · {window}'},
                      {'metric': 'voice_channels', 'show': 'value', 'label': '{value} active voice channels'}],
            'icon': 'source', 'link': 'https://discord.gg/' + code}


WIDGET_MEMBER_CAP = 100

# Counts-only log of public-widget checks, for the day's line on the server card.
VOICE_LOG_KEEP = 120            # one check per 15 minutes: a day and a little more
VOICE_LOG_SECONDS = 26 * 3600


def voice_summary(definition, state, *, now):
    """Read model for the voice line: people and channels in voice, when the server makes that public.

    ``available`` carries counts (``users`` is None for state saved before people were
    counted); ``unavailable`` means the public widget is off; ``pending`` means not
    checked yet, stale or retrying. None when the pulse does not watch voice.
    """
    if not definition.get('source', {}).get('params', {}).get('voice', True):
        return None
    info, status = state.get('widget'), state.get('widget_state')
    if info and status == 'available' and now - info['ts'] <= 1800:
        return {'state': 'available', 'users': info.get('voice_users'), 'channels': info['voice_channels'],
                'capped': info.get('listed', 0) >= WIDGET_MEMBER_CAP}
    return {'state': 'unavailable' if status == 'unavailable' else 'pending', 'users': None, 'channels': None, 'capped': False}


class DiscordSource:
    def __init__(self, *, fetch=discord_get, icons=None, jitter=lambda seconds: 0):
        self.fetch, self.icons, self.jitter = fetch, icons, jitter

    def request(self, net, path):
        return net.call('discord.com', lambda: self.fetch(path))

    def poll(self, definition, previous, state, *, now, net):
        # Only one endpoint per invocation. Widget refreshes never become fake
        # primary samples or turn stale invite counts into fresh counts.
        from ..engine import seconds
        state = copy.deepcopy(state)
        invite_due = state.get('invite_due', 0)
        voice = definition['source']['params'].get('voice', True)
        widget_due = state.get('widget_due', 0) if voice else float('inf')
        if previous is not None and invite_due > now and widget_due <= now:
            gid = previous['metadata']['id']
            try:
                raw = self.request(net, '/api/v10/guilds/' + gid + '/widget.json')
                if not isinstance(raw, dict) or not isinstance(raw.get('channels'), list) or not isinstance(raw.get('members'), list):
                    raise DiscordError('Public widget returned invalid data; cached counts are preserved.')
                # Reject partial/malformed collections instead of filtering them
                # into a plausible measured zero. Widget IDs, when supplied, must
                # belong to the same server as the invite.
                if (('id' in raw and str(raw['id']) != gid)
                        or any(not isinstance(c, dict) for c in raw['channels'])
                        or any(not isinstance(m, dict) for m in raw['members'])):
                    raise DiscordError('Public widget returned invalid data; cached counts are preserved.')
                channels, members = raw['channels'], raw['members']
                active_ids = set()
                for member in members:
                    channel_id = member.get('channel_id')
                    if channel_id is None:
                        continue
                    if (isinstance(channel_id, bool) or not isinstance(channel_id, (str, int))
                            or not GUILD_RE.fullmatch(str(channel_id))):
                        raise DiscordError('Public widget returned invalid data; cached counts are preserved.')
                    active_ids.add(str(channel_id))
                # Counts only. `listed` records how many members the widget returned,
                # because Discord caps that list and a full list makes the count a floor.
                info = {'ts': now, 'presence_count': raw.get('presence_count'),
                        'voice_channels': len(active_ids),
                        'voice_users': sum(1 for member in members if member.get('channel_id') is not None),
                        'listed': len(members),
                        'channels': [str(c.get('name', 'Voice'))[:100] for c in channels if str(c.get('id')) in active_ids]}
                # [time, people in voice, active channels, members listed]: numbers only, never names.
                log = [entry for entry in state.get('voice_log', []) if isinstance(entry, list) and len(entry) == 4
                       and isinstance(entry[0], (int, float)) and now - VOICE_LOG_SECONDS <= entry[0] <= now]
                log.append([now, info['voice_users'], info['voice_channels'], info['listed']])
                state.update(widget=info, widget_state='available', widget_due=now + 900 + self.jitter(900),
                             voice_log=log[-VOICE_LOG_KEEP:])
            except Deferred:
                raise
            except SourceError as exc:
                status = 'unavailable' if exc.status in (403, 404) else 'backoff'
                delay = 86400 if status == 'unavailable' else max(900, exc.retry_after)
                state.update(widget_state=status, widget_due=now + delay)
            return SourceResult(state=state, next_due=min(invite_due, state['widget_due']))
        code = parse_invite(definition['source']['params']['invite'])
        data = normalize_invite(self.request(net, '/api/v10/invites/' + code + '?with_counts=true'))
        if previous and data['id'] != previous.get('metadata', {}).get('id', data['id']):
            raise DiscordError('Invite now points to another server. Remove and re-add it.', 404)
        if self.icons:
            self.icons.cache(data)
        interval = max(600, seconds(definition['every']))
        state['invite_due'] = now + interval + self.jitter(interval)
        if voice:
            state.setdefault('widget_due', 0)
            state.setdefault('widget_state', 'unchecked')
        sample = {'ts': now, 'metrics': {k: data[k] for k in ('online', 'members')},
                  'baselines': {}, 'unknown_reasons': {k: 'Not measured by the public invite' for k in ('online', 'members') if data[k] is None},
                  'metadata': data}
        return SourceResult(sample=sample, state=state, metadata=data,
                            next_due=min(state['invite_due'], state['widget_due']) if voice else state['invite_due'])

    def current(self, sample, state, *, now):
        # voice_channels stays the only widget metric; people in voice are a
        # display summary (voice_summary), not a stored or scored metric.
        sample = copy.deepcopy(sample)
        info = state.get('widget')
        fresh = bool(info and now - info['ts'] <= 1800 and state.get('widget_state') == 'available')
        sample['metrics']['voice_channels'] = info['voice_channels'] if fresh else None
        if not fresh:
            sample.setdefault('unknown_reasons', {})['voice_channels'] = 'Public widget unavailable or stale'
        return sample
