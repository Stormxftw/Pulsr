"""Registered pulse/1 kinds. Declarative metadata only; no I/O or Hermes imports."""
from copy import deepcopy
import re

from .desktop_apps import ALIASES as APP_ALIASES, MAX_APPS


# Built-in count metrics have integer readings even when their usual is a mean.
COUNT_METRICS = frozenset(('online', 'members', 'voice_channels', 'recent', 'baseline',
    'stars', 'forks', 'open_issues', 'open_prs', 'commits_week', 'turns_running',
    'waiting_on_you', 'tool_calls_10m', 'tool_errors_1h', 'subagents_running',
    'provider_errors_1h', 'waiting', 'new_1h', 'new_24h', 'new_7d',
    'count', 'errors', 'requests', 'calls', 'items', 'players'))


def metric_label(metric):
    """Humanize unknown readings without destroying familiar metric acronyms."""
    text = metric.replace('_', ' ').capitalize()
    acronyms = {'prs': 'PRs', 'ci': 'CI', 'api': 'API', 'cpu': 'CPU', 'gpu': 'GPU', 'aqi': 'AQI'}
    return re.sub(r'\b(?:prs|ci|api|cpu|gpu|aqi)\b', lambda m: acronyms[m[0].lower()], text, flags=re.I)



def obj(properties, required=()):
    """Strict objects reserve x-* keys at every definition level."""
    return {'type': 'object', 'properties': properties, 'required': list(required),
            'patternProperties': {'^x-': {}}, 'additionalProperties': False}


REPO = {'type': 'string', 'pattern': r'^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$',
        'format': 'pulse-repo'}
SEARCH_TEXT = {'type': 'string', 'pattern': r'^[A-Za-z0-9 ._-]{1,40}$'}
DISCORD_PRESET = {
    'ring': {'components': [
        {'metric': 'online', 'weight': 70, 'type': 'delta', 'baseline': 'median',
         'window': '24h', 'floor': 25, 'sensitivity': 0.20},
        {'metric': 'members', 'weight': 20, 'type': 'delta', 'baseline': 'oldest',
         'window': '24h', 'floor': 100, 'sensitivity': 0.01},
        {'metric': 'voice_channels', 'weight': 10, 'type': 'level', 'full_at': 5}]},
    'capsule': {'metric': 'online', 'label': '{value} online', 'fill': 'baseline'},
    'lines': [
        {'metric': 'members', 'show': 'delta', 'label': 'Net {delta} members · {window}'},
        {'metric': 'voice_channels', 'label': '{value} active voice channels'}],
    'icon': 'source',
}
SEARCH_PRESET = {
    'ring': {'components': [{'metric': 'recent', 'weight': 100, 'type': 'delta',
                            'baseline': 'source', 'sensitivity': 1.0, 'direction': 'both'}]},
    'capsule': {'metric': 'recent', 'label': '{value} items / {window}', 'fill': 'baseline'},
    'lines': [{'metric': 'baseline', 'label': 'usual ≈{value}/window'}], 'icon': 'source',
}
REPO_PRESET = {
    'ring': {'components': [{'metric': 'stars', 'weight': 100, 'type': 'delta', 'baseline': 'oldest'}]},
    'capsule': {'metric': 'stars', 'label': '{value} stars', 'fill': 'baseline'},
    'lines': [{'metric': 'forks', 'label': '{value} forks'},
              {'metric': 'open_issues', 'label': '{value} open issues (incl. PRs)'},
              {'metric': 'open_prs', 'label': '{value} open PRs'}], 'icon': 'source',
}
HERMES_PRESET = {
    'ring': {'components': [
        {'metric': 'tool_calls_10m', 'weight': 80, 'type': 'delta', 'baseline': 'median',
         'window': '24h', 'floor': 5, 'sensitivity': 1.0},
        {'metric': 'tool_errors_1h', 'weight': 20, 'type': 'level', 'full_at': 5}]},
    'capsule': {'metric': 'turns_running', 'label': '{value} turns running', 'fill': {'full_at': 4}},
    'lines': [{'metric': 'waiting_on_you', 'label': '{value} waiting on you', 'hide_when_zero': True},
              {'metric': 'subagents_running', 'label': '{value} subagents', 'hide_when_zero': True}],
    'icon': 'hermes',
}
NOTIFY_PRESET = {
    'ring': {'components': [
        {'metric': 'waiting', 'weight': 70, 'type': 'level', 'full_at': 5},
        {'metric': 'new_1h', 'weight': 30, 'type': 'delta', 'baseline': 'median',
         'window': '24h', 'floor': 2, 'sensitivity': 1.0, 'direction': 'up'}]},
    'capsule': {'metric': 'waiting', 'label': '{value} in Action Center', 'fill': {'full_at': 5}},
    'lines': [{'metric': 'new_1h', 'label': '{value} observed · last hour', 'hide_when_zero': True},
              {'metric': 'minutes_since_last', 'label': 'Last one {value} min ago'}],
    'icon': 'source',
}
FEED_PRESET = {
    'ring': {'components': [{'metric': 'new_24h', 'weight': 100, 'type': 'level', 'full_at': 5}]},
    'capsule': {'metric': 'new_24h', 'label': '{value} new · 24h', 'fill': {'full_at': 5}},
    'lines': [{'metric': 'new_7d', 'label': '{value} this week'}], 'icon': 'source',
}
# Exact Windows AUMIDs: printable ASCII, alphanumeric/brace first, no trailing space.
APP_ID = {'type': 'string', 'maxLength': 200, 'pattern': r'^[A-Za-z0-9{](?:[ -~]{0,198}[!-~])?$'}
HTTP_PRESET = {
    'ring': {'components': [{'metric': '$first', 'weight': 100, 'type': 'delta', 'baseline': 'median'}]},
    'capsule': {'metric': '$first', 'label': '{value}', 'fill': 'baseline'},
    'lines': [], 'icon': 'source',
}

KINDS = {
    'discord.invite': {
        'params_schema': obj({
            'invite': {'type': 'string', 'maxLength': 256, 'format': 'pulse-invite'},
            'voice': {'type': 'boolean', 'default': True}}, ['invite']),
        'metrics': ['online', 'members', 'voice_channels'], 'source_baselines': {},
        'preset': DISCORD_PRESET, 'min_every': 600, 'default_every': '10m',
        'hosts': ['discord.com', 'cdn.discordapp.com'], 'calls_per_poll': 1,
        'periodic_calls': [{'every': 900, 'calls': 1, 'when_param': 'voice'}],
        'pre_approval_sample': True,
    },
    'github.search': {
        'params_schema': obj({
            'repo': REPO, 'type': {'enum': ['pr', 'issue']},
            'title_contains': SEARCH_TEXT, 'label': SEARCH_TEXT,
            'window': {'enum': ['24h', '7d'], 'default': '24h'},
            'baseline_days': {'type': 'integer', 'minimum': 7, 'maximum': 30, 'default': 14}},
            ['repo', 'type']),
        'metrics': ['recent', 'baseline'], 'source_baselines': {'recent': 'sample.baselines.recent'},
        'preset': SEARCH_PRESET, 'min_every': 600, 'default_every': '15m',
        'hosts': ['api.github.com'], 'calls_per_poll': 1,
        'periodic_calls': [{'every': 21600, 'calls': 1}], 'pre_approval_sample': True,
    },
    'github.repo': {
        'params_schema': obj({'repo': REPO,
            'activity': {'type': 'boolean', 'default': False},
            'ci': {'type': 'boolean', 'default': False}}, ['repo']),
        'metrics': ['stars', 'forks', 'open_issues', 'open_prs', 'commits_week', 'hours_since_push', 'ci_passing', 'ci_running'],
        'metric_params': {'commits_week': 'activity', 'hours_since_push': 'activity', 'ci_passing': 'ci', 'ci_running': 'ci'},
        'source_baselines': {'commits_week': 'sample.baselines.commits_week'},
        'preset': REPO_PRESET, 'min_every': 600, 'default_every': '15m',
        'hosts': ['api.github.com'], 'calls_per_poll': 2,
        'poll_calls': [{'calls': 1, 'when_param': 'ci'}],
        'periodic_calls': [{'every': 3600, 'calls': 1, 'when_param': 'activity'}],
        'pre_approval_sample': True,
    },
    'hermes.activity': {
        'params_schema': obj({'scope': {'enum': ['profile'], 'default': 'profile'}}),
        'metrics': ['turns_running', 'waiting_on_you', 'tool_calls_10m', 'tool_errors_1h',
                    'subagents_running', 'provider_errors_1h'], 'source_baselines': {},
        'preset': HERMES_PRESET, 'min_every': 30, 'default_every': '30s',
        'hosts': [], 'calls_per_poll': 0, 'periodic_calls': [], 'pre_approval_sample': None,
    },
    'mcp.tool': {
        'params_schema': obj({
            'server': {'type': 'string', 'pattern': r'^(?!.*__)[A-Za-z0-9][A-Za-z0-9_-]{0,63}(?![\s\S])'},
            'tool': {'type': 'string', 'pattern': r'^(?!.*__)[A-Za-z0-9][A-Za-z0-9_-]{0,63}(?![\s\S])'},
            'args': {'type': 'object', 'default': {}, 'maxProperties': 32, 'format': 'pulse-mcp-args'},
            'metrics': {'type': 'object', 'minProperties': 1, 'maxProperties': 6,
                        'propertyNames': {'pattern': r'^[A-Za-z][A-Za-z0-9_]{0,39}$'},
                        'additionalProperties': {'type': 'string', 'maxLength': 512,
                                                 'format': 'pulse-json-pointer'}}}, ['server', 'tool', 'metrics']),
        'metrics': [], 'source_baselines': {}, 'preset': HTTP_PRESET,
        'min_every': 300, 'default_every': '15m', 'hosts': [],
        'calls_per_poll': 1, 'periodic_calls': [], 'pre_approval_sample': False,
    },
    'http_json': {
        'params_schema': obj({
            'url': {'type': 'string', 'maxLength': 512, 'format': 'pulse-public-url'},
            'metrics': {'type': 'object', 'minProperties': 1, 'maxProperties': 6,
                        'propertyNames': {'pattern': r'^[A-Za-z][A-Za-z0-9_]{0,39}$'},
                        'additionalProperties': {'type': 'string', 'maxLength': 512,
                                                 'format': 'pulse-json-pointer'}}}, ['url', 'metrics']),
        'metrics': [], 'source_baselines': {}, 'preset': HTTP_PRESET,
        'min_every': 300, 'default_every': '5m', 'hosts': [],
        'calls_per_poll': 1, 'periodic_calls': [], 'pre_approval_sample': False,
    },
    'web.feed': {
        # RSS, Atom or JSON Feed. Post titles are shown in the pane and never sent to the model.
        'params_schema': obj({'url': {'type': 'string', 'maxLength': 512, 'format': 'pulse-public-url'}}, ['url']),
        'metrics': ['new_24h', 'new_7d', 'hours_since_last', 'items'], 'source_baselines': {},
        'preset': FEED_PRESET, 'min_every': 900, 'default_every': '30m', 'hosts': [],
        'calls_per_poll': 1, 'periodic_calls': [], 'pre_approval_sample': False,
    },
    'desktop.notifications': {
        # At least one of apps/app_ids, <=8 distinct, no duplicates: semantic pass.
        'params_schema': obj({
            'apps': {'type': 'array', 'minItems': 1, 'maxItems': MAX_APPS,
                     'items': {'enum': list(APP_ALIASES)}},
            'app_ids': {'type': 'array', 'minItems': 1, 'maxItems': MAX_APPS, 'items': APP_ID},
            'types': {'type': 'array', 'minItems': 1, 'maxItems': 2,
                      'items': {'enum': ['toast', 'badge']}, 'default': ['toast']},
            # Opt-in, separately disclosed: the pane shows senders and text. Off when absent.
            'preview': {'type': 'boolean'}}),
        'metrics': ['waiting', 'new_1h', 'new_24h', 'minutes_since_last'], 'source_baselines': {},
        'preset': NOTIFY_PRESET, 'min_every': 30, 'default_every': '1m',
        'hosts': [], 'calls_per_poll': 0, 'periodic_calls': [], 'pre_approval_sample': None,
    },
}


def metrics_for_params(kind, params):
    meta = KINDS[kind.removesuffix('@1')]
    if kind.removesuffix('@1') in ('http_json', 'mcp.tool'):
        return params.get('metrics', {})
    return [m for m in meta['metrics'] if m not in meta.get('metric_params', {})
            or params.get(meta['metric_params'][m]) is True]


def get_kind(name):
    """Return isolated metadata for a bare kind or its supported @1 alias."""
    if name.endswith('@1'):
        name = name[:-2]
    return deepcopy(KINDS[name])
