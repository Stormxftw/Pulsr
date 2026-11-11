"""Deterministic ranked, fully validated layouts; no observations or network calls."""
from copy import deepcopy
from urllib.parse import urlsplit

from .kinds import KINDS
from .spec import normalize, ValidationError, bindings_of
from .layout import layout_check
from .templates import metrics_for


def _error(message):
    raise ValidationError([{'path': '/metrics', 'message': message}])


def _limit(ref, feeds):
    name, metric = ref.split('.')
    feed = feeds[name]
    declared = list(feed['params']['metrics']) if feed['kind'] in ('http_json', 'mcp.tool') else KINDS[feed['kind']]['metrics']
    if feed['kind'] == 'discord.invite' and metric == 'online':
        return name + '.members'
    candidates = [metric + '_' + suffix for suffix in ('limit', 'total', 'capacity', 'quota', 'max')]
    if metric.endswith('_used'):
        candidates = [metric[:-5] + '_' + suffix for suffix in ('limit', 'total', 'capacity', 'quota', 'max')] + candidates
    if metric in ('used', 'count', 'active'):
        candidates += ['limit', 'total', 'capacity', 'quota', 'max']
    return next((name + '.' + m for m in candidates if m in declared and m != metric), None)


def _zones(info, feeds):
    if info['hint'] == 'percent':
        return {'warn': 80, 'crit': 95}
    name, metric = info['ref'].split('.')
    feed = feeds[name]
    if feed['kind'] != 'http_json':
        return None
    params = feed['params']
    u = urlsplit(params['url'])
    pointer = params['metrics'][metric]
    if u.hostname == 'air-quality-api.open-meteo.com' and u.path == '/v1/air-quality' and pointer == '/current/us_aqi':
        return {'warn': 100, 'crit': 150}
    if u.hostname == 'api.open-meteo.com' and u.path == '/v1/forecast' and pointer == '/current/temperature_2m':
        return {'warn': 90, 'crit': 100} if info['unit'] == '°F' else {'warn': 32, 'crit': 38}
    return None


def layouts(feeds, metrics, title=None, icon=None):
    """All selected refs remain visible; spare bindings fund trend/denominator refs.

    At the eight-binding ceiling a natural/auto fallback is used rather than
    dropping a selected number to fit a denominator or repeating a trend.
    """
    if (not isinstance(metrics, list) or not 1 <= len(metrics) <= 8
            or not all(isinstance(ref, str) for ref in metrics) or len(set(metrics)) != len(metrics)):
        _error('Choose 1–8 different numbers to show.')
    # Real validation precedes any access to kind metadata or URL parsing.
    seed = normalize({'pulse': 1, 'title': title if title is not None else 'My pulse', 'icon': icon if icon is not None else 'initials',
                      'feeds': feeds, 'display': [{'type': 'stat', 'value': metrics[0]}]})
    feeds = seed['feeds']
    info = {m['ref']: m for m in metrics_for(feeds)}
    # Bare references are accepted only for a single feed, like spec.normalize.
    refs = [next(iter(feeds)) + '.' + ref if '.' not in ref and len(feeds) == 1 else ref for ref in metrics]
    if len(set(refs)) != len(refs) or any(ref not in info for ref in refs):
        _error('Choose numbers declared by these data sources.')
    selected = [info[ref] for ref in refs]
    if title is None:
        first = next(iter(feeds.values()))
        seed['title'] = first['params'].get('repo', '')[:40] or ('Hermes activity' if first['kind'] == 'hermes.activity' else
                                                                 'Desktop notifications' if first['kind'] == 'desktop.notifications' else
                                                                 'New posts' if first['kind'] == 'web.feed' else 'My pulse')
        seed.pop('id', None)
    if icon is None:
        first_kind = next(iter(feeds.values()))['kind']
        seed['icon'] = ({'brand': first_kind.split('.')[0]} if first_kind.startswith(('github.', 'discord.')) else 'hermes' if first_kind == 'hermes.activity' else
                        {'emoji': '🔔'} if first_kind == 'desktop.notifications' else {'brand': 'rss'} if first_kind == 'web.feed' else {'emoji': '📊'})

    def item(meta, *, scales=True, warnings=False, spare=None):
        out = {'value': meta['ref'], 'label': meta['label']}
        if meta['unit']:
            out['unit'] = meta['unit']
        if scales:
            bound = _limit(meta['ref'], feeds)
            if bound and spare is not None and spare[0] > 0:
                out['max'] = bound
                spare[0] -= 1
            elif meta['hint'] == 'percent':
                out['max'] = 100
            elif meta['hint'] == 'ratio':
                out['max'] = 1
            else:
                out['max'] = 'usual' if meta['hint'] == 'count' else 'auto'
                if meta['hint'] == 'temperature':
                    out['min'] = 'auto'
            zones = _zones(meta, feeds) if warnings else None
            if zones:
                out['zones'] = zones
        return out

    def groups(metas, spare, warnings=False):
        blocks = []
        for start in range(0, len(metas), 3):
            chunk = metas[start:start + 3]
            items = [item(m, warnings=warnings, spare=spare) for m in chunk]
            blocks.append({'type': 'bar', **items[0]} if len(items) == 1 else {'type': 'bars', 'scale': 'independent', 'bars': items})
        return blocks

    result = []
    def add(id, title, description, why, blocks):
        d = deepcopy(seed)
        d['display'] = blocks
        d = normalize(d)
        check = layout_check(d)
        if not check['ok']:
            raise ValidationError(check['errors'])
        assert len(bindings_of(d)) <= 8
        result.append(dict(id=id, title=title, description=description, why=why, definition=d))

    n = len(selected)
    first = selected[0]
    repo_refs = {m['ref'].split('.')[1]: m['ref'] for m in selected}
    if (set(repo_refs) == {'commits_week', 'hours_since_push', 'ci_passing'}
            and len({m['ref'].split('.')[0] for m in selected}) == 1
            and feeds[first['ref'].split('.')[0]]['kind'] == 'github.repo'):
        add('repo-activity', 'Repo activity', 'Commits vs usual, last push and the latest CI run.',
            'Commits use GitHub’s previous 12 weeks; push age uses cached time; CI is unknown until a completed conclusion is available.',
            [{'type': 'score', 'label': 'Commits this week vs usual', 'components': [
                {'metric': repo_refs['commits_week'], 'type': 'delta', 'weight': 100, 'baseline': 'source'}]},
             {'type': 'stat', 'value': repo_refs['hours_since_push'], 'label': 'Last push', 'unit': 'duration'},
             {'type': 'stat', 'value': repo_refs['ci_passing'], 'label': 'CI build', 'states': {
                 '0': {'label': 'Failing', 'tone': 'crit'}, '1': {'label': 'Passing', 'tone': 'ok'}}}])
    trend = n <= 6
    spare = [8 - n - int(trend)]
    blocks = [{'type': 'stat', 'show': 'both', **item(first, scales=False)}]
    blocks += groups(selected[1:], spare)
    if trend:
        blocks.append({'type': 'spark', 'value': first['ref'], 'label': 'Trend', 'points': 24})
    add('number-trend', 'Big number + trend' if trend else 'Numbers at a glance',
        'A headline number, supporting values and room for history.', 'Read the current value first; measured history supplies change, never an invented target.', blocks)
    spare = [8 - n]
    hero_count = min(2, n)
    blocks = [{'type': 'rings', 'rings': [item(m, spare=spare) for m in selected[:hero_count]]}] + groups(selected[hero_count:], spare)
    add('gauge', 'Gauge ring', 'A clear ring for the main numbers, with supporting bars.',
        'Uses matching source limits, natural ranges, then a learned usual or automatic range; full selections leave less room for denominator bindings.', blocks)
    if n >= 2:
        spare = [8 - n]
        blocks = groups(selected, spare)
        add('comparison', 'Comparison bars', 'Compare the selected values in a small stack.',
            'Independent scales keep different units honest; each range is shown separately.', blocks)
    else:
        spare = [6]
        add('bar-trend', 'Bar + trend', 'One horizontal gauge above the measured trend.',
            'A compact alternative to a ring with the same range rules.',
            [{'type': 'bar', **item(first, spare=spare)}, {'type': 'spark', 'value': first['ref'], 'points': 24}])
    baseline = next((m for m in selected if m['hint'] == 'count'), None)
    if baseline:
        name, metric = baseline['ref'].split('.')
        source_baseline = metric in KINDS[feeds[name]['kind']]['source_baselines']
        components = [{'metric': baseline['ref'], 'type': 'delta', 'weight': 100, 'baseline': 'source' if source_baseline else 'median'}]
        add('change', 'Change vs usual', 'A change ring with supporting numbers.',
            'Shows unusualness, not a measured percentage. Learns from history unless the source reports its own baseline.',
            [{'type': 'score', 'label': 'Change vs usual', 'components': components}] + groups([m for m in selected if m != baseline], [8 - n]))
    if any(_zones(m, feeds) for m in selected):
        add('warnings', 'Warning bars', 'Amber and red levels on recognized metrics.',
            'Suggested levels apply only to percent, US AQI and Open-Meteo heat; review them for your situation. These are not alerts.', groups(selected, [8 - n], warnings=True))
    # A fourth useful option even for an opaque single JSON number.
    if len(result) < 4:
        add('dashboard', 'Dashboard', 'A headline with a gauge and supporting values.',
            'Combine an exact value with a visual range; unknown readings remain unknown.',
            [{'type': 'stat', **item(first, scales=False)}] + groups(selected, [7 - n]) if n <= 7 else groups(selected, [0]))
    return result[:6]
