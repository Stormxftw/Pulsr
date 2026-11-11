"""Pure authoring explanations. No runtime engine, policy lookup or store access."""
from urllib.parse import urlsplit

from . import desktop_apps
from .kinds import KINDS
from .spec import ValidationError, budget, feeds_of, normalize

NEW_POSTS = ('New posts: reads the feed at the approved address and shows post titles, times and https links '
             'from it in the pane. Titles are untrusted text and are never sent to the model.')
LOCAL_NOTIFICATIONS = ('No network. Reads notification counts and times from Windows on this PC '
                       '(notification store + per-app registry timestamps), read-only; never message text. '
                       'Waiting means selected entries still in Windows (toasts in Action Center), not unread messages. '
                       'New counts need a continuously watched full window; several arrivals that clear '
                       'between polls may count only once.')
NOTIFICATION_PREVIEWS = ('Message previews are on: for the newest waiting notifications of these apps (at most 5) '
                         'the pane shows who each is from and its text, cut to 120 characters. Read from Windows '
                         'only when the pane refreshes, kept in memory for a few seconds, never saved, logged or '
                         'sent to Hermes or the model.')


def _number_text(value):
    # Round-trip decimal form, not :g's implicit six-significant-digit rounding.
    return str(value).removesuffix('.0')


def feed_disclosures(definition):
    """All recurring allocations, with icon allocations separate from feed budgets."""
    rows = []
    for name, feed in feeds_of(definition).items():
        kind, params = feed['kind'], feed['params']
        target = (params['server'] + '/' + params['tool'] if kind == 'mcp.tool' else
                  desktop_apps.target(params) if kind == 'desktop.notifications' else
                  params['url'] if kind in ('http_json', 'web.feed') else params.get('repo') or
                  params.get('invite') or 'this profile')
        # Reuse the authoritative budget arithmetic; initials excludes icon egress.
        allocation = budget({'pulse': 1, 'title': 'Feed allocation', 'source':
            {'kind': kind, 'params': params}, 'every': feed['every'], 'icon': 'initials'})
        row = {'name': name, 'kind': kind, 'target': target, 'every': feed['every'],
               'hosts': allocation['hosts'], 'req_per_hour': allocation['req_per_hour']}
        if kind == 'github.repo' and (params.get('activity') or params.get('ci')):
            calls = ['GET /repos/{repo} + /pulls: 2 calls per poll']
            if params.get('activity'):
                calls.append('GET /repos/{repo}/stats/participation: 1 req/h (hourly, including 202); last push uses cached pushed_at, no extra call')
            if params.get('ci'):
                calls.append('GET /repos/{repo}/actions/runs?branch=<default_branch>&per_page=1: 1 call per poll; needs Actions read access')
            row['calls'] = '; '.join(calls)
        rows.append(row)
    return rows


def proposal_disclosure(definition):
    rows = feed_disclosures(definition)
    allocation = budget(definition)
    icon = definition.get('icon', 'source')
    icon_hosts = []
    if isinstance(icon, dict) and 'url' in icon:
        icon_hosts.append(urlsplit(icon['url']).hostname.lower().rstrip('.'))
    if icon == 'source':
        for row in rows:
            if row['kind'].startswith('github.'):
                icon_hosts.append('avatars.githubusercontent.com')
            elif row['kind'] == 'discord.invite':
                icon_hosts.append('cdn.discordapp.com')
    icon_hosts = sorted(set(icon_hosts))
    text = [f"Feed {r['name']}: {r['kind']} {r['target']} · every {r['every']} · {_number_text(r['req_per_hour'])} req/h"
            for r in rows]
    text.extend(r['calls'] for r in rows if 'calls' in r)
    text.append(f"Total: {_number_text(allocation['req_per_hour'])} req/h · hosts: {', '.join(allocation['hosts']) or 'none direct'}")
    text.append('Icon hosts (one-off, not req/h): ' + (', '.join(icon_hosts) or 'none explicit'))
    if icon == 'source' and any(r['kind'] == 'mcp.tool' for r in rows):
        text.append('MCP metadata HTTPS icons require an already disclosed host; undisclosed hosts are skipped. Raster data icons are offline.')
    if any(r['kind'] == 'mcp.tool' for r in rows):
        text.append('via Hermes MCP connector (Hermes handles sign-in); no automatic MCP previews. A separate builder Test call requires explicit human consent before pulse approval. Connector services/private data are not direct hosts. Review exact args in the definition.')
    if any(r['kind'] == 'desktop.notifications' for r in rows):
        text.append(LOCAL_NOTIFICATIONS)
        if any(r['kind'] == 'desktop.notifications' and r['target'].endswith(desktop_apps.PREVIEW_TARGET) for r in rows):
            text.append(NOTIFICATION_PREVIEWS)
    if any(r['kind'] == 'web.feed' for r in rows):
        text.append(NEW_POSTS)
    return {'feeds': rows, 'budget': allocation, 'icon_hosts': icon_hosts, 'summary': '\n'.join(text)}


def _feed_text(ref, feeds):
    name = ref.split('.')[0]
    row = feeds[name]
    return f"feed {name} ({row['kind']} {row['target']}, every {row['every']})"


def _range(scale):
    lo, hi = scale['min'], scale['max']
    text = f'{lo}–{hi}'
    if 'auto' in (lo, hi):
        text += f" (learning until 3 samples over 1h; window {scale['auto_window']})"
    elif hi == 'usual':
        text += f" (2 × prior median; learning until positive baseline; window {scale['auto_window']})"
    return text


def _hex(value):
    if not isinstance(value, str) or not value.startswith('#'):
        return None
    value = value[1:]
    if len(value) == 3:
        value = ''.join(c * 2 for c in value)
    rgb = tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    alpha = int(value[6:8], 16) / 255 if len(value) == 8 else 1
    return rgb, alpha


def _contrast(foreground, background):
    rgb, alpha = foreground
    bg, _ = background
    composite = [c * alpha + b * (1 - alpha) for c, b in zip(rgb, bg)]
    def luminance(values):
        return sum(w * (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
                   for w, c in zip((0.2126, 0.7152, 0.0722), values))
    a, b = sorted((luminance(composite), luminance(bg)))
    return (b + 0.05) / (a + 0.05)


def _contrast_warnings(definition):
    theme = definition.get('theme', {})
    surface = _hex(theme.get('surface'))
    if surface is None or surface[1] != 1:
        return []  # No invented renderer/theme surface or token resolution.
    warnings = []
    scopes = [('/theme', theme)]
    for i, block in enumerate(definition.get('display', [])):
        scopes.append((f'/display/{i}/style', block.get('style', {})))
        for key in ('rings', 'bars'):
            scopes += [(f'/display/{i}/{key}/{j}/style', item.get('style', {}))
                       for j, item in enumerate(block.get(key, []))]
    for path, scope in scopes:
        for key in ('accent', 'text', 'color', 'color2', 'track'):
            color = _hex(scope.get(key))
            if color and _contrast(color, surface) < 3:
                warnings.append(f'{path}/{key}: hex colour contrast against theme.surface is below 3:1.')
    return warnings


def layout_check(definition):
    """Validate and describe intent, never simulate readings or resolve live ranges."""
    try:
        d = normalize(definition)
    except ValidationError as exc:
        return {'ok': False, 'errors': exc.errors, 'blocks': [], 'warnings': []}
    feeds = {r['name']: r for r in feed_disclosures(d)}
    warnings = _contrast_warnings(d)
    lines = []
    display = d.get('display', [])
    if display and display[0]['type'] == 'rings' and len(display[0]['rings']) > 2:
        warnings.append('/display/0/rings: more than 2 hero rings may be hard to scan.')
    for i, block in enumerate(display):
        kind = block['type']
        prefix = f'display[{i}] '
        if kind == 'score':
            components = block['components']
            detail = ', '.join(f"{c['metric']} {_number_text(c['weight'])}% {c['type']}" for c in components)
            lines.append(prefix + 'score — weighted unusualness: ' + detail + ' · ' + _feed_text(components[0]['metric'], feeds))
        elif kind in ('stat', 'spark'):
            detail = (f"headline {block['show']} · delta vs {block['delta_vs']} · window {block['auto_window']}"
                      if kind == 'stat' else f"trend · last {block['points']} samples; missing values are gaps")
            if kind == 'stat' and 'states' in block:
                detail = 'discrete plain-text states · optional semantic tone · unmapped values stay unknown'
            elif kind == 'stat' and block.get('unit') == 'duration':
                detail = 'elapsed hours as days/hours/minutes ago · no numeric delta'
            lines.append(prefix + kind + ' — ' + block['label'] + ' · ' + detail + ' · ' + _feed_text(block['value'], feeds))
        else:
            items = block[kind] if kind in ('rings', 'bars') else [block]
            for j, item in enumerate(items):
                shared = kind == 'bars' and block['scale'] == 'shared'
                scale = block if shared else item
                text = prefix + f"{kind}[{j}] {item['label']} — " + _range(scale)
                if shared:
                    text += ' · shared scale'
                zones = item.get('zones')
                if zones:
                    comparator = '≥' if zones['direction'] == 'up' else '≤'
                    text += ' · zones ' + ' '.join(f'{k}{comparator}{_number_text(zones[k])}' for k in ('warn', 'crit') if k in zones)
                if item.get('unit'):
                    text += ' · unit ' + item['unit']
                lines.append(text + ' · ' + _feed_text(item['value'], feeds))
                if scale['max'] == 'auto':
                    name, metric = item['value'].split('.')
                    feed = feeds_of(d)[name]
                    declared = (feed['params']['metrics'] if feed['kind'] in ('mcp.tool', 'http_json')
                                else KINDS[feed['kind']]['metrics'])
                    candidates = [m for m in declared if m != metric and
                                  (m.lower() in ('limit', 'total', 'capacity', 'max') or
                                   m.lower() in tuple(metric.lower() + '_' + suffix for suffix in ('limit', 'total', 'capacity', 'max')))]
                    if candidates:
                        refs = ', '.join(name + '.' + m for m in candidates)
                        warnings.append(f'/display/{i}: auto range for {item["value"]}; sibling metric {refs} looks like a limit. Consider a metric-bound max after verifying meaning.')
    if not display:
        lines.append('Legacy score ring, capsule and detail lines · ' + _feed_text('main.' + d['capsule']['metric'], feeds))
    return {'ok': True, 'errors': [], 'normalized': d, 'budget': budget(d),
            'blocks': lines, 'warnings': list(dict.fromkeys(warnings))}
