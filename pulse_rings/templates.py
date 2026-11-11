"""Offline, data-only Builder 2 forms and source conversion; never fetch or store."""
from copy import deepcopy
from typing import Any
import math
import re
from urllib.parse import urlencode, urlsplit, parse_qs

from . import brands, desktop_apps
from .icon_resolver import HERMES
from .kinds import KINDS, metrics_for_params
from .net import strict_json
from .spec import normalize, ValidationError, invite_code


def _field(key, label, help, type='text', placeholder='', required=True, options=None):
    out: dict[str, Any] = dict(key=key, label=label, help=help, type=type, placeholder=placeholder, required=required)
    if options:
        out['options'] = [{'value': value, 'label': title} for value, title in options]
    return out


_REPO = _field('repo', 'Repository', 'Paste a GitHub repository URL or owner/name. No network call.', placeholder='NousResearch/hermes-agent')
_METRICS = _field('metrics', 'Numbers to watch', 'JSON object mapping names to JSON Pointers you picked from an inspected result; 1–6 numbers.', placeholder='{"used":"/used","limit":"/limit"}')
_URL = _field('url', 'Public JSON URL', 'Public HTTPS only. Paste pointers from a result you inspected; this form never fetches the URL.', 'url', 'https://example.org/metrics.json')
_ROWS = [
    ('discord', 'Discord server', 'Members, people online and active voice channels.', {'brand': 'discord'}, 'discord.invite', [
        _field('invite', 'Discord invite link', 'Paste an invite link or the original invite code. Parsed offline.', placeholder='https://discord.gg/hermes')], None, None),
    ('github-repo', 'GitHub repo', 'Stars, forks, issues; optional commits, last push and CI.', {'brand': 'github'}, 'github.repo', [_REPO,
        _field('commits', 'Commits this week', 'Opt in to hourly participation stats and a previous-12-week baseline (+1 req/h).', 'checkbox', required=False),
        _field('last_push', 'Last push', 'Uses pushed_at from the repo response. Enables activity stats (+1 req/h shared with commits).', 'checkbox', required=False),
        _field('ci', 'CI build status', 'Latest default-branch Actions run; requires Actions read access (+1 call per poll).', 'checkbox', required=False)], None, None),
    ('github-search', 'GitHub PRs/issues search', 'Recent work compared with its usual pace.', {'brand': 'github'}, 'github.search', [_REPO,
        _field('type', 'What to count', 'Choose pull requests or issues.', 'select', options=[('pr', 'Pull requests'), ('issue', 'Issues')]),
        _field('title_contains', 'Words in the title', 'Optional plain words, not a search expression.', required=False),
        _field('label', 'Label', 'Optional exact GitHub label.', required=False),
        _field('window', 'Time to count', 'Compare equal time windows.', 'select', required=False, options=[('24h', '24 hours'), ('7d', '7 days')])], None, None),
    ('weather', 'Weather & air', 'Current weather and air quality from Open-Meteo.', {'emoji': '🌦️'}, 'http_json', [
        _field('city', 'City', 'Find sends this text to geocoding-api.open-meteo.com once; select a result or enter coordinates.', required=False),
        _field('latitude', 'Latitude', 'Selected city coordinate, from −90 to 90.', 'number'),
        _field('longitude', 'Longitude', 'Selected city coordinate, from −180 to 180.', 'number'),
        _field('units', 'Units', 'US units by default; air quality always uses US AQI.', 'select', required=False, options=[('imperial', 'Fahrenheit · mph · inches'), ('metric', 'Celsius · km/h · mm')])], 'city', None),
    ('steam', 'Game players (Steam)', 'How many people are playing right now.', {'brand': 'steam'}, 'http_json', [
        _field('appid', 'Steam store link or app ID', 'Paste a store link or app ID offline. Find game names sends one call to store.steampowered.com.', placeholder='https://store.steampowered.com/app/730/'),
        _field('name', 'Game name', 'Optional display title from your chosen result.', required=False)], 'steam', None),
    ('json', 'Any website JSON', 'Watch numbers from a public HTTPS JSON response.', {'emoji': '🌐'}, 'http_json', [_URL, _METRICS], None, 'json'),
    ('mcp', 'MCP tool', 'Read numbers from a connected, read-only Hermes tool.', {'emoji': '🔌'}, 'mcp.tool', [
        _field('server', 'Connected server', 'Exact server name from the connected tools list.'),
        _field('tool', 'Read-only tool', 'Exact tool name. Hermes grant and read-only policy still apply.'),
        _field('args', 'Tool inputs', 'Optional JSON object; no secrets. Inputs are saved in the definition.', placeholder='{}', required=False), _METRICS], None, 'mcp'),
    ('hermes', 'Hermes activity', 'Running work, tool calls and errors in this profile.', 'hermes', 'hermes.activity', [
        _field('scope', 'Watch', 'Local counters only; no network call.', 'select', required=False, options=[('profile', 'This profile')])], None, None),
    ('notifications', 'Desktop notifications', 'Notifications still in Action Center, not unread messages (Windows).', {'emoji': '🔔'}, 'desktop.notifications', [
        _field('app', 'App', 'Counts and times only; never message text. Reads the local Windows notification store read-only, no network. New counts need a continuously watched full window.', 'select', required=False,
               options=[(alias, desktop_apps.APPS[alias][0]) for alias in desktop_apps.ALIASES]),
        _field('app_id', 'Other app ID', 'Optional exact Windows app ID (AUMID) for an app not in the list.', required=False),
        _field('preview', 'Show message previews', 'Off by default. Shows who waiting notifications are from and their text in this pane only, cut short; never saved or sent to Hermes. Shown on the approval card.', 'checkbox', required=False)], None, None),
    ('releases', 'GitHub releases', 'New releases of a repository, by name.', {'brand': 'github'}, 'web.feed', [
        _field('repo', 'Repository', 'Paste a GitHub repository URL or owner/name. After approval this reads the public release feed on github.com; no network call now.',
               placeholder='NousResearch/hermes-agent')], None, None),
    ('posts', 'New posts (RSS / Atom)', 'Latest posts from a blog, release page, channel or subreddit feed.', {'brand': 'rss'}, 'web.feed', [
        _field('url', 'Feed address', 'Public HTTPS RSS, Atom or JSON feed. Post titles are shown in the pane and never sent to the model. This form never fetches the address.', 'url',
               'https://example.org/feed.xml'),
        _field('name', 'Name', 'Optional title for the pulse.', required=False)], None, None),
    ('blank', 'Start blank', 'Choose your own public JSON source and numbers; nothing is preconfigured.', {'emoji': '✨'}, 'http_json', [_URL, _METRICS], None, 'json'),
]


def _resolved(icon):
    if icon == 'hermes':
        return dict(HERMES)
    if 'brand' in icon:
        record = brands.brand(icon['brand'])
        assert record is not None  # Catalog slugs are shipped artwork, not user input.
        return {'kind': 'brand', 'slug': icon['brand'], **record}
    return {'kind': 'emoji', 'text': icon['emoji']}


def catalog():
    return [dict(id=id, title=title, description=description, icon=_resolved(icon), kind=kind,
                 fields=deepcopy(fields), lookup=lookup, test=test)
            for id, title, description, icon, kind, fields, lookup, test in _ROWS]


def _link_text(value):
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Paste the original link or identifier without control characters.')
    value = value.strip()
    if any(c.isspace() for c in value) or '\\' in value:
        raise ValueError('Use an identifier or URL without whitespace or backslashes.')
    return value


def repo_name(value):
    if not isinstance(value, str):
        raise ValueError('Paste a GitHub URL or owner/name.')
    value = _link_text(value)
    if '://' in value:
        u = urlsplit(value)
        if u.scheme != 'https' or u.netloc != 'github.com' or u.query or u.fragment:
            raise ValueError('Use an HTTPS repository URL on github.com.')
        value = u.path.removeprefix('/').removesuffix('/')
    if not re.fullmatch(KINDS['github.repo']['params_schema']['properties']['repo']['pattern'], value) or value.split('/')[-1] in ('.', '..'):
        raise ValueError('Use exactly owner/name, not a search, issue or pull request URL.')
    return value


def steam_appid(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str):
        raise ValueError('Use a positive Steam app ID or HTTPS store link.')
    value = _link_text(value)
    if '://' in value:
        u = urlsplit(value)
        if u.scheme != 'https' or u.netloc != 'store.steampowered.com' or u.fragment:
            raise ValueError('Use an HTTPS app link on store.steampowered.com.')
        match = re.fullmatch(r'/app/([1-9][0-9]{0,9})(?:/[^/]*)?/?', u.path)
        if not match:
            raise ValueError('Use a Steam /app/ID/ link, not a bundle or search URL.')
        value = match[1]
    if not re.fullmatch(r'[1-9][0-9]{0,9}', value) or int(value) > 4294967295:
        raise ValueError('Use a positive Steam app ID (up to 4294967295).')
    return int(value)


def _object(value):
    if isinstance(value, str):
        try:
            value = strict_json(value)
        except (ValueError, UnicodeError):
            raise ValueError('Use a JSON object, not executable expressions.') from None
    if not isinstance(value, dict):
        raise ValueError('Use a JSON object.')
    return deepcopy(value)


_LABELS = {'online': 'Online now', 'members': 'Members', 'voice_channels': 'Active voice channels',
           'stars': 'Stars', 'forks': 'Forks', 'open_issues': 'Open issues (including PRs)', 'open_prs': 'Open pull requests',
           'commits_week': 'Commits this week', 'hours_since_push': 'Last push', 'ci_passing': 'CI build status', 'ci_running': 'CI running',
           'recent': 'Recent items', 'baseline': 'Usual items per window', 'players': 'Playing right now',
           'turns_running': 'Running turns', 'waiting_on_you': 'Waiting on you', 'tool_calls_10m': 'Tool calls · 10 minutes',
           'tool_errors_1h': 'Tool errors · 1 hour', 'subagents_running': 'Running helpers', 'provider_errors_1h': 'Provider errors · 1 hour',
           'waiting': 'Waiting notifications', 'new_1h': 'New · 1 hour', 'new_24h': 'New · 24 hours', 'minutes_since_last': 'Minutes since last',
           'new_7d': 'New · 7 days', 'hours_since_last': 'Last post', 'items': 'Posts in the feed'}


def metric_info(name, metric, feed) -> dict[str, Any]:
    """Shared inferred metadata. No user-supplied hint can change the source semantics."""
    kind, params = feed['kind'].removesuffix('@1'), feed['params']
    semantic_name = metric + ' ' + str(params.get('metrics', {}).get(metric, ''))
    tokens = set(re.split(r'[^a-z0-9]+', re.sub(r'([a-z])([A-Z])', r'\1_\2', semantic_name).lower()))
    label, unit, hint = _LABELS.get(metric, metric.replace('_', ' ').capitalize()), '', 'other'
    if kind not in ('http_json', 'mcp.tool') or tokens & {'count', 'players', 'used', 'requests', 'calls', 'members', 'stars', 'errors', 'open'}:
        hint = 'count'
    if tokens & {'limit', 'total', 'capacity', 'quota', 'max'}:
        hint = 'limit'
    elif tokens & {'pct', 'percent', 'percentage'}:
        hint, unit = 'percent', '%'
    elif 'ratio' in tokens:
        hint = 'ratio'
    elif tokens & {'temperature', 'temp', 'celsius', 'fahrenheit'}:
        hint = 'temperature'
    elif tokens & {'money', 'usd', 'price', 'cost'}:
        hint = 'money'
    elif tokens & {'duration', 'latency', 'seconds', 'ms'}:
        hint = 'duration'
    elif tokens & {'bytes', 'size', 'gb', 'mb', 'gib', 'mib'}:
        hint = 'size'
    elif 'score' in tokens:
        hint = 'score'
    if kind == 'github.repo' and metric == 'hours_since_push':
        unit, hint = 'duration', 'duration'
    if kind == 'github.repo' and metric in ('ci_passing', 'ci_running'):
        hint = 'state'
    if kind == 'desktop.notifications':
        label = {'waiting': 'In Windows' if 'badge' in params.get('types', []) else 'In Action Center',
                 'new_1h': 'Observed · last hour', 'new_24h': 'Observed · last 24 hours',
                 'minutes_since_last': 'Last notification'}.get(metric, label)
        if metric == 'minutes_since_last':
            unit, hint = 'min', 'duration'
    if kind == 'web.feed':
        label = {'new_24h': 'New posts · 24 hours', 'new_7d': 'New posts · 7 days'}.get(metric, label)
        if metric == 'hours_since_last':
            unit, hint = 'duration', 'duration'
    if kind == 'http_json':
        u = urlsplit(params['url'])
        pointer = params.get('metrics', {}).get(metric)
        if u.hostname == 'api.open-meteo.com' and u.path == '/v1/forecast':
            query = parse_qs(u.query)
            temperature = '°F' if query.get('temperature_unit') == ['fahrenheit'] else '°C'
            wind = {'kmh': 'km/h', 'mph': 'mph', 'ms': 'm/s', 'kn': 'kn'}.get(
                query.get('wind_speed_unit', ['kmh'])[0], '')
            rain = {'mm': 'mm', 'inch': 'in'}.get(query.get('precipitation_unit', ['mm'])[0], '')
            known = {'/current/temperature_2m': ('Temperature', temperature, 'temperature'),
                     '/current/wind_speed_10m': ('Wind', wind, 'other'),
                     '/current/precipitation': ('Rain', rain, 'other')}
            label, unit, hint = known.get(pointer, (label, unit, hint))
        elif u.hostname == 'air-quality-api.open-meteo.com' and u.path == '/v1/air-quality':
            label, unit, hint = {'/current/us_aqi': ('Air quality (US AQI)', '', 'score'),
                                 '/current/pm2_5': ('Fine particles (PM2.5)', 'µg/m³', 'other')}.get(pointer, (label, unit, hint))
    return dict(ref=name + '.' + metric, label=label[:40], unit=unit, hint=hint, default_selected=metric not in {'baseline', 'limit', 'total', 'capacity'})


def metrics_for(feeds):
    return [metric_info(name, metric, feed) for name, feed in feeds.items()
            for metric in metrics_for_params(feed['kind'], feed['params'])]


def from_template(template, values):
    row = next((r for r in _ROWS if r[0] == template), None)
    out: dict[str, Any] = dict(ok=False, errors=[], feeds={}, metrics=[], suggested_title='', suggested_icon='initials')
    if row is None:
        out['errors'] = [{'field': 'template', 'message': 'Choose a template from the catalog.'}]
        return out
    _, title, _, icon, kind, fields, *_ = row
    out.update(suggested_title=title, suggested_icon=deepcopy(icon))
    errors: list[dict[str, str]] = out['errors']
    if not isinstance(values, dict):
        errors.append({'field': 'values', 'message': 'Use an object of form values.'})
        return out
    allowed = {f['key'] for f in fields}
    errors.extend({'field': key, 'message': 'Unknown form field.'} for key in values if key not in allowed)
    errors.extend({'field': f['key'], 'message': 'Enter ' + f['label'].lower() + '.'}
                  for f in fields if f['required'] and f['key'] != 'type' and values.get(f['key']) in (None, ''))
    def get(key, default=None):
        return values.get(key, default)
    def convert(key, fn, default=None):
        try:
            return fn(get(key, default))
        except (ValueError, TypeError, OverflowError) as exc:
            errors.append({'field': key, 'message': str(exc)})
    params = {}
    feeds = None
    if template == 'discord':
        params['invite'] = convert('invite', lambda value: invite_code(_link_text(value)))
    elif template.startswith('github-'):
        params['repo'] = convert('repo', repo_name)
        if template == 'github-repo':
            for key in ('commits', 'last_push', 'ci'):
                if key in values and type(values[key]) is not bool:
                    errors.append({'field': key, 'message': 'Use a checkbox boolean.'})
            if get('commits') is True or get('last_push') is True:
                params['activity'] = True
            if get('ci') is True:
                params['ci'] = True
        if template == 'github-search':
            params.update(type=get('type', 'pr'), window=get('window', '24h'))
            params.update({k: get(k) for k in ('label', 'title_contains') if get(k) not in ('', None)})
        if params['repo']:
            title = params['repo'].split('/')[1] + (' · recent work' if template == 'github-search' else '')
    elif template == 'weather':
        def coordinate(value, bound):
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise ValueError('Enter a finite coordinate.')
            number = float(value)
            if not math.isfinite(number) or not -bound <= number <= bound:
                raise ValueError(f'Enter a coordinate from {-bound} to {bound}.')
            return round(number, 2)
        lat = convert('latitude', lambda v: coordinate(v, 90))
        lon = convert('longitude', lambda v: coordinate(v, 180))
        units = get('units', 'imperial')
        if units not in ('imperial', 'metric'):
            errors.append({'field': 'units', 'message': 'Choose imperial or metric units.'})
        imperial = units == 'imperial'
        query = dict(latitude=lat, longitude=lon, current='temperature_2m,wind_speed_10m,precipitation',
                     temperature_unit='fahrenheit' if imperial else 'celsius', wind_speed_unit='mph' if imperial else 'kmh', precipitation_unit='inch' if imperial else 'mm')
        feeds = {'weather': {'kind': 'http_json', 'params': {'url': 'https://api.open-meteo.com/v1/forecast?' + urlencode(query),
                          'metrics': {'temp': '/current/temperature_2m', 'wind': '/current/wind_speed_10m', 'rain': '/current/precipitation'}}, 'every': '15m'},
                 'air': {'kind': 'http_json', 'params': {'url': 'https://air-quality-api.open-meteo.com/v1/air-quality?' + urlencode(dict(latitude=lat, longitude=lon, current='us_aqi,pm2_5')),
                         'metrics': {'aqi': '/current/us_aqi', 'pm25': '/current/pm2_5'}}, 'every': '30m'}}
        city = get('city')
        if isinstance(city, str) and city.strip():
            title = city.strip()[:40] + ' · weather & air'
    elif template == 'steam':
        appid = convert('appid', steam_appid)
        params = {'url': f'https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={appid}', 'metrics': {'players': '/response/player_count'}}
        title = ((get('name') or f'Steam {appid}') if isinstance(get('name', ''), str) else 'Steam')[:40] + ' · live players'
    elif template in ('json', 'blank', 'mcp'):
        params['metrics'] = convert('metrics', _object)
        if template == 'mcp':
            params.update(server=get('server'), tool=get('tool'), args=convert('args', _object, {}))
        else:
            params['url'] = get('url')
    elif template == 'releases':
        repo = convert('repo', repo_name)
        if repo:
            params['url'] = f'https://github.com/{repo}/releases.atom'
            title = repo.split('/')[1][:40] + ' · releases'
    elif template == 'posts':
        params['url'] = get('url')
        name = get('name')
        try:
            host = urlsplit(params['url']).hostname if isinstance(params['url'], str) else None
        except ValueError:
            host = None
        title = (name.strip() if isinstance(name, str) and name.strip() else (host or 'Feed').removeprefix('www.') + ' · new posts')[:60]
    elif template == 'hermes':
        params['scope'] = get('scope', 'profile')
        title = 'Hermes at work'
    elif template == 'notifications':
        app, app_id = get('app'), get('app_id')
        if app not in (None, ''):
            params['apps'] = [app]
        if isinstance(app_id, str) and app_id.strip():
            params['app_ids'] = [app_id.strip()]
        if not params:
            errors.append({'field': 'app', 'message': 'Choose an app or enter its Windows app ID.'})
        elif get('preview') is True:
            params['preview'] = True
        names = desktop_apps.names(params) if all(isinstance(v, list) for k, v in params.items() if k != 'preview') else []
        title = (names[0][:40] if names else 'Desktop') + ' · notifications'
        brand = desktop_apps.brand(params) if isinstance(params.get('apps'), list) and all(a in desktop_apps.APPS for a in params['apps']) else None
        if brand:
            icon = {'brand': brand}
            out['suggested_icon'] = deepcopy(icon)
    if errors:
        return out
    if feeds is None:
        feeds = {'main': {'kind': kind, 'params': params, 'every': '10m' if template == 'steam' else KINDS[kind]['default_every']}}
    # Reuse the real source validators; even conversion never relaxes URL/args/pointer rules.
    first_name, first_feed = next(iter(feeds.items()))
    declared = first_feed['params'].get('metrics')
    first_metric = next(iter(declared), 'value') if isinstance(declared, dict) else KINDS[first_feed['kind']]['metrics'][0] if KINDS[first_feed['kind']]['metrics'] else 'value'
    try:
        d = normalize({'pulse': 1, 'title': title[:60], 'feeds': feeds, 'icon': icon,
                       'display': [{'type': 'stat', 'value': first_name + '.' + first_metric}]})
    except ValidationError as exc:
        for error in exc.errors:
            parts = error['path'].split('/')
            field = parts[4] if len(parts) > 4 and parts[1] == 'feeds' and parts[3] == 'params' else 'values'
            errors.append({'field': field, 'message': error['message']})
        return out
    out.update(ok=True, feeds=d['feeds'], metrics=metrics_for(d['feeds']), suggested_title=d['title'])
    if template == 'weather':
        for m in out['metrics']:
            m['default_selected'] = m['ref'] in ('weather.temp', 'air.aqi')
    elif template in ('github-repo', 'discord', 'hermes', 'notifications', 'posts', 'releases'):
        selected = {'github-repo': {'stars', 'forks'}, 'discord': {'online', 'members'}, 'hermes': {'turns_running', 'tool_calls_10m', 'tool_errors_1h'},
                    'notifications': {'waiting', 'new_1h'}, 'posts': {'new_24h', 'new_7d'}, 'releases': {'new_24h', 'new_7d'}}[template]
        if template == 'github-repo' and any(get(k) is True for k in ('commits', 'last_push', 'ci')):
            selected = {metric for key, metric in [('commits', 'commits_week'), ('last_push', 'hours_since_push'), ('ci', 'ci_passing')] if get(key) is True}
        for m in out['metrics']:
            m['default_selected'] = m['ref'].split('.')[1] in selected
    if out['metrics'] and not any(m['default_selected'] for m in out['metrics']):
        out['metrics'][0]['default_selected'] = True
    return out
