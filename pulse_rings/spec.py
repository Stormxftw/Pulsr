"""Pure, offline pulse/1 parsing, validation, normalization and egress budgeting.

Only ruamel.yaml is optional. JSON works with the standard library alone. This
module neither activates definitions nor resolves DNS nor makes network calls.
"""
from __future__ import annotations

from copy import deepcopy
import ipaddress
import json
import math
import re
import unicodedata
from urllib.parse import unquote, urlsplit
from typing import Any

from .kinds import KINDS, obj, metrics_for_params
from .mcp_params import valid_args
from . import display_spec
from . import desktop_apps
from .display_spec import feeds_of, bindings_of

MAX_BYTES = 16 * 1024
from .limits import MAX_ACTIVE, MAX_DRAFTS, DEFAULT_REQUESTS_PER_HOUR
PLACEHOLDERS = {'value', 'delta', 'ratio', 'baseline', 'window'}


class ValidationError(ValueError):
    """User-correctable errors, with JSON Pointer paths and plain-text messages."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__('; '.join(f"{e['path'] or '/'}: {e['message']}" for e in errors))


def _error(path, message):
    return {'path': path, 'message': message}


def _path(parent, key):
    return parent + '/' + str(key).replace('~', '~0').replace('/', '~1')


def duration_seconds(value):
    """Convert a positive s/m/h duration, with bounded integer parsing."""
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,12}[smh]', value):
        raise ValueError('Use a positive duration such as 30s, 10m or 24h.')
    seconds = int(value[:-1]) * {'s': 1, 'm': 60, 'h': 3600}[value[-1]]
    if seconds <= 0:
        raise ValueError('Duration must be greater than zero.')
    return seconds


def _duration(value):
    if not isinstance(value, str):
        return True  # type is checked separately by the shape schema
    try:
        duration_seconds(value)
        return True
    except ValueError:
        return False


def invite_code(value):
    """Accept a code or an HTTPS invite on exactly discord.gg/discord.com."""
    if not isinstance(value, str) or len(value) > 256:
        raise ValueError('Use a Discord invite code or HTTPS Discord invite URL.')
    value = value.strip()
    if re.fullmatch(r'[A-Za-z0-9_-]{2,64}', value):
        return value
    url = urlsplit(value)
    if url.scheme != 'https' or url.netloc not in ('discord.gg', 'discord.com') or url.fragment:
        raise ValueError('Use https://discord.gg/CODE or https://discord.com/invite/CODE.')
    prefix = '/' if url.netloc == 'discord.gg' else '/invite/'
    code = url.path[len(prefix):] if url.path.startswith(prefix) else ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{2,64}', code):
        raise ValueError('The invite path must contain only the original 2–64 character code.')
    return code


def _invite(value):
    if not isinstance(value, str):
        return True
    try:
        invite_code(value)
        return True
    except ValueError:
        return False


def _https_url(value, public=False):
    if not isinstance(value, str):
        return True
    # Reject parser differentials, interpolated URLs and encoded placeholders.
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or '\\' in value:
        return False
    if any(c in unquote(value) for c in '{}'):
        return False
    try:
        url = urlsplit(value)
        host = url.hostname
        if url.scheme != 'https' or not host or url.username is not None or url.password is not None:
            return False
        if url.port is not None and (url.port != 443 if public else not 1 <= url.port <= 65535):
            return False
        if '%' in host or url.fragment and public:
            return False
        host = host.rstrip('.').lower()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host):
                return False
            if any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-')
                   for label in host.split('.')) or len(host) > 253:
                return False
            if public:
                if '.' not in host or host.endswith(('.localhost', '.local', '.internal', '.test', '.invalid')):
                    return False
                if host in {'localhost', 'metadata.google.internal', 'metadata.google', 'instance-data.ec2.internal'}:
                    return False
                # Noncanonical IPv4 notations can otherwise become loopback at
                # the HTTP boundary (2130706433, 127.1, 0177.0.0.1, 0x7f000001).
                if all(re.fullmatch(r'(?:[0-9]+|0x[0-9a-f]+)', part) for part in host.split('.')):
                    return False
        else:
            if public and (not address.is_global or address.is_multicast
                           or getattr(address, 'ipv4_mapped', None) is not None):
                return False
        return True
    except (ValueError, UnicodeError):
        return False


def _display_text(value):
    return not isinstance(value, str) or all(unicodedata.category(c) not in ('Cf', 'Cc') for c in value)


def _label(value):
    if not isinstance(value, str):
        return True
    stripped = re.sub(r'\{(?:value|delta|ratio|baseline|window)\}', '', value)
    return '{' not in stripped and '}' not in stripped and _display_text(value)


def _pointer(value):
    return (not isinstance(value, str) or value == ''
            or (value.startswith('/') and re.search(r'~(?![01])', value) is None))


def _repo(value):
    return not isinstance(value, str) or value.split('/')[-1] not in {'.', '..'}


def _icon(value):
    if not isinstance(value, str) or value in {'source', 'hermes', 'initials'}:
        return True
    # One Unicode emoji cluster: a base with optional VS/modifier, joined bases,
    # a two-regional-indicator flag, or a keycap. Never an image/HTML string.
    if re.fullmatch('[0-9#*]\ufe0f?\u20e3', value):
        return True
    if len(value) == 2 and all(0x1F1E6 <= ord(c) <= 0x1F1FF for c in value):
        return True
    base = r'[\U0001F000-\U0001FAFF\u2600-\u27BF\u00A9\u00AE\u203C\u2049\u2122\u2139\u3030\u303D\u3297\u3299]'
    part = base + r'\ufe0f?[\U0001F3FB-\U0001F3FF]?'
    if not re.fullmatch(part + '(?:\u200d' + part + ')*', value):
        return False
    return not (0x1F1E6 <= ord(value[0]) <= 0x1F1FF or 0x1F3FB <= ord(value[0]) <= 0x1F3FF)


FORMAT_CHECKS = {
    'pulse-duration': _duration,
    'pulse-invite': _invite,
    'pulse-public-url': lambda value: _https_url(value, public=True),
    'pulse-https-url': _https_url,
    'pulse-template': _label,
    'pulse-display-text': _display_text,
    'pulse-json-pointer': _pointer,
    'pulse-mcp-args': lambda value: not isinstance(value, dict) or valid_args(value),
    'pulse-repo': _repo,
    'pulse-icon': _icon,
    'pulse-auto-window': display_spec.valid_window,
    'pulse-icon-url': display_spec.icon_url,
    'pulse-emoji': lambda value: not isinstance(value, str) or (value not in {'source', 'hermes', 'initials'} and _icon(value)),
}
for _kind, _meta in KINDS.items():
    def _interval(value, minimum=_meta['min_every']):
        return not isinstance(value, str) or (_duration(value) and duration_seconds(value) >= minimum)
    FORMAT_CHECKS['pulse-every-' + _kind] = _interval


def schema():
    """Build the published Draft 2020-12 shape schema from the kind table.

    Formats are assertions in this implementation. Other schema consumers MUST
    register FORMAT_CHECKS (or equivalent checks), then run semantic_errors().
    """
    metric = {'type': 'string', 'pattern': r'^[A-Za-z][A-Za-z0-9_]{0,39}$'}
    label = {'type': 'string', 'maxLength': 40, 'format': 'pulse-template'}
    positive = {'type': 'number', 'exclusiveMinimum': 0}
    duration = {'type': 'string', 'pattern': r'^[0-9]{1,12}[smh]$', 'format': 'pulse-duration'}
    component = obj({
        'metric': metric, 'weight': {'type': 'number', 'minimum': 0, 'maximum': 100},
        'type': {'enum': ['delta', 'level']},
        'baseline': {'anyOf': [{'enum': ['median', 'oldest', 'source']}, {'type': 'number', 'minimum': 0}]},
        'window': duration, 'floor': positive, 'sensitivity': positive,
        'direction': {'enum': ['both', 'up', 'down']}, 'full_at': positive,
    }, ['metric', 'weight', 'type'])
    component['allOf'] = [
        {'if': {'properties': {'type': {'const': 'level'}}},
         'then': {'required': ['full_at'], 'not': {'anyOf': [{'required': [key]} for key in
             ['baseline', 'window', 'floor', 'sensitivity', 'direction']]}}},
        {'if': {'properties': {'type': {'const': 'delta'}}},
         'then': {'not': {'required': ['full_at']}}},
    ]
    alert = obj({'ring_at_least': {'type': 'number', 'minimum': 0, 'maximum': 100},
                 'metric': metric, 'above': {'type': 'number'}, 'below': {'type': 'number'},
                 'notify': {'enum': ['none', 'toast', 'os', 'pet']} })
    alert['oneOf'] = [
        {'required': ['ring_at_least'], 'not': {'anyOf': [{'required': [key]} for key in ['metric', 'above', 'below']]}},
        {'required': ['metric', 'above'], 'not': {'anyOf': [{'required': ['below']}, {'required': ['ring_at_least']}] }},
        {'required': ['metric', 'below'], 'not': {'anyOf': [{'required': ['above']}, {'required': ['ring_at_least']}] }},
    ]
    result = obj({
        'pulse': {'type': 'integer', 'const': 1},
        'id': {'type': 'string', 'pattern': r'^[a-z0-9][a-z0-9-]{1,47}$'},
        'title': {'type': 'string', 'minLength': 1, 'maxLength': 60, 'format': 'pulse-display-text'},
        'source': obj({'kind': {'enum': [alias for kind in KINDS for alias in [kind, kind + '@1']]},
                       'params': {'type': 'object'}}, ['kind']),
        'every': duration,
        'ring': obj({'components': {'type': 'array', 'minItems': 1, 'maxItems': 4,
                                    'items': component}}, ['components']),
        'capsule': obj({'metric': metric, 'label': label,
                        'fill': {'anyOf': [{'enum': ['baseline', 'none']}, obj({'full_at': positive}, ['full_at'])]}},
                       ['metric', 'label', 'fill']),
        'lines': {'type': 'array', 'maxItems': 3, 'items': obj({
            'metric': metric, 'label': label, 'show': {'enum': ['value', 'delta']},
            'hide_when_zero': {'type': 'boolean'}}, ['metric', 'label'])},
        'alert': alert, 'icon': {'type': 'string', 'format': 'pulse-icon'},
        'link': {'type': 'string', 'maxLength': 300, 'format': 'pulse-https-url'},
    }, ['pulse', 'title', 'source'])
    result['$schema'] = 'https://json-schema.org/draft/2020-12/schema'
    result['$id'] = 'https://github.com/Stormxftw/Pulsr/blob/main/spec/pulse-1.schema.json'
    result['title'] = 'pulse/1 definition'
    result['$comment'] = ('Normative for shape; register the pulse-* format assertions and apply '
                          'PULSE-1.md semantics (weight sum, metric references, source baselines). '
                          'Input is capped at 16 KiB UTF-8 before schema validation.')
    result['allOf'] = []
    for kind, meta in KINDS.items():
        source_schema: dict[str, Any] = {'properties': {'params': deepcopy(meta['params_schema'])}}
        if meta['params_schema']['required']:
            source_schema['required'] = ['params']
        result['allOf'].append({
            'if': {'properties': {'source': {'properties': {'kind': {'enum': [kind, kind + '@1']}},
                                            'required': ['kind']}}, 'required': ['source']},
            'then': {'properties': {'source': source_schema,
                                     'every': {'format': 'pulse-every-' + kind}}},
        })
    return display_spec.extend_schema(result, component)


SCHEMA = schema()


def _matches_type(value, kind):
    return {
        'object': lambda: isinstance(value, dict),
        'array': lambda: isinstance(value, list),
        'string': lambda: isinstance(value, str),
        'boolean': lambda: isinstance(value, bool),
        'integer': lambda: isinstance(value, int) and not isinstance(value, bool),
        'number': lambda: (isinstance(value, int) and not isinstance(value, bool))
                         or (isinstance(value, float) and math.isfinite(value)),
        'null': lambda: value is None,
    }[kind]()


def _equal(left, right):
    # Python bool/int equality is not JSON bool/number equality.
    return type(left) is type(right) and left == right or (
        isinstance(left, (int, float)) and not isinstance(left, bool)
        and isinstance(right, (int, float)) and not isinstance(right, bool) and left == right)


def _shape(value, rule, path=''):
    """Evaluate only the schema vocabulary emitted by schema(), without deps."""
    errors = []
    if 'type' in rule and not _matches_type(value, rule['type']):
        return [_error(path, 'Expected ' + rule['type'] + '.')]
    if 'const' in rule and not _equal(value, rule['const']):
        errors.append(_error(path, 'Expected ' + json.dumps(rule['const']) + '.'))
    if 'enum' in rule and not any(_equal(value, choice) for choice in rule['enum']):
        errors.append(_error(path, 'Choose one of: ' + ', '.join(map(str, rule['enum'])) + '.'))
    if isinstance(value, dict):
        for key in rule.get('required', []):
            if key not in value:
                errors.append(_error(_path(path, key), 'Required field is missing.'))
        for limit, compare in [('minProperties', lambda n, lim: n < lim), ('maxProperties', lambda n, lim: n > lim)]:
            if limit in rule and compare(len(value), rule[limit]):
                errors.append(_error(path, f"Object requires {limit} {rule[limit]}."))
        properties = rule.get('properties', {})
        patterns = rule.get('patternProperties', {})
        for key, item in value.items():
            if 'propertyNames' in rule:
                errors.extend(_shape(key, rule['propertyNames'], _path(path, key)))
            matched = False
            if key in properties:
                errors.extend(_shape(item, properties[key], _path(path, key)))
                matched = True
            for pattern, child in patterns.items():
                if re.search(pattern, key):
                    errors.extend(_shape(item, child, _path(path, key)))
                    matched = True
            if not matched:
                additional = rule.get('additionalProperties', True)
                if additional is False:
                    errors.append(_error(_path(path, key), 'Unknown field; remove it or use an x- extension.'))
                elif isinstance(additional, dict):
                    errors.extend(_shape(item, additional, _path(path, key)))
    if isinstance(value, list):
        for limit, compare in [('minItems', lambda n, lim: n < lim), ('maxItems', lambda n, lim: n > lim)]:
            if limit in rule and compare(len(value), rule[limit]):
                errors.append(_error(path, f"Array requires {limit} {rule[limit]}."))
        if 'items' in rule:
            for index, item in enumerate(value):
                errors.extend(_shape(item, rule['items'], _path(path, index)))
    if isinstance(value, str):
        for limit, compare in [('minLength', lambda n, lim: n < lim), ('maxLength', lambda n, lim: n > lim)]:
            if limit in rule and compare(len(value), rule[limit]):
                errors.append(_error(path, f"Text requires {limit} {rule[limit]} characters."))
        if 'pattern' in rule and re.search(rule['pattern'], value) is None:
            errors.append(_error(path, 'Must match ' + rule['pattern'] + '.'))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for limit, compare in [('minimum', lambda n, lim: n < lim), ('maximum', lambda n, lim: n > lim),
                               ('exclusiveMinimum', lambda n, lim: n <= lim)]:
            if limit in rule and compare(value, rule[limit]):
                errors.append(_error(path, f"Number requires {limit} {rule[limit]}."))
    if 'format' in rule and not FORMAT_CHECKS[rule['format']](value):
        messages = {
            'pulse-duration': 'Use a positive s/m/h duration, e.g. 30s, 10m, 24h.',
            'pulse-invite': 'Use an invite code or an HTTPS discord.gg / discord.com invite link.',
            'pulse-public-url': 'Use an HTTPS public URL without userinfo, fragments or placeholders; private/local IPs are forbidden.',
            'pulse-https-url': 'Use an HTTPS URL without userinfo or placeholders.',
            'pulse-display-text': 'Titles and labels cannot contain invisible format or control characters.',
            'pulse-template': 'Only {value}, {delta}, {ratio}, {baseline}, {window} are allowed; no expressions or escaped braces.',
            'pulse-json-pointer': 'Use an RFC 6901 JSON Pointer (empty or /path; escapes ~0 and ~1 only).',
            'pulse-repo': 'Repository name cannot be . or ...',
            'pulse-icon': 'Choose source, hermes, initials, or one emoji.',
            'pulse-mcp-args': 'MCP args require JSON, <=2 KiB, <=32 total keys, depth <=6 and no credential-named fields.',
            'pulse-auto-window': 'Use a duration from 1h to 7d.',
            'pulse-icon-url': 'Use a public HTTPS icon URL on port 443 without userinfo or query secrets.',
            'pulse-emoji': 'Use one emoji cluster.',
        }
        message = messages.get(rule['format'])
        if message is None:
            kind = rule['format'].removeprefix('pulse-every-')
            minimum = KINDS[kind]['min_every']
            message = f'{kind} requires every >= {minimum}s; use {minimum}s or a longer s/m/h duration.'
        errors.append(_error(path, message))
    for child in rule.get('allOf', []):
        errors.extend(_shape(value, child, path))
    for union in ['anyOf', 'oneOf']:
        if union in rule:
            options = [_shape(value, child, path) for child in rule[union]]
            successes = sum(not option for option in options)
            if (union == 'anyOf' and not successes) or (union == 'oneOf' and successes != 1):
                # Keep field-level errors from an unambiguous matching type.
                typed = [option for child, option in zip(rule[union], options)
                         if 'type' in child and _matches_type(value, child['type'])]
                if len(typed) == 1 and typed[0]:
                    errors.extend(typed[0])
                else:
                    errors.append(_error(path, 'Use exactly one allowed form.' if union == 'oneOf' else 'Value does not match an allowed form.'))
    if 'not' in rule and not _shape(value, rule['not'], path):
        errors.append(_error(path, 'These fields cannot be combined.'))
    if 'if' in rule:
        branch = 'then' if not _shape(value, rule['if'], path) else 'else'
        if branch in rule:
            errors.extend(_shape(value, rule[branch], path))
    return errors


def _json_data(value):
    """Bounded tree walk rejects YAML objects, nonfinite numbers and cycles."""
    ancestors = set()
    count = 0
    def walk(node, path='', depth=0):
        nonlocal count
        count += 1
        if depth > 48 or count > 4096:
            raise ValidationError([_error(path, 'Definition is too deeply nested or contains too many values.')])
        if node is None or isinstance(node, (str, bool, int)):
            return
        if isinstance(node, float) and math.isfinite(node):
            return
        if not isinstance(node, (dict, list)):
            raise ValidationError([_error(path, 'Only JSON data values are allowed (no tags, dates, sets, tuples or nonfinite numbers).')])
        if id(node) in ancestors:
            raise ValidationError([_error(path, 'Recursive aliases/cycles are forbidden.')])
        ancestors.add(id(node))
        if isinstance(node, dict):
            for key, child in node.items():
                if not isinstance(key, str):
                    raise ValidationError([_error(path, 'Object keys must be strings.')])
                walk(child, _path(path, key), depth + 1)
        else:
            for index, child in enumerate(node):
                walk(child, _path(path, index), depth + 1)
        ancestors.remove(id(node))
    walk(value)


def _bounded(value):
    _json_data(value)
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    except (ValueError, UnicodeError, OverflowError) as exc:
        raise ValidationError([_error('', 'Definition must contain valid UTF-8 JSON data.')]) from exc
    if len(raw) > MAX_BYTES:
        raise ValidationError([_error('', 'Definition exceeds the 16 KiB UTF-8 limit.')])


def parse(text):
    """Parse one UTF-8 YAML/JSON object. Never open a filename or execute tags."""
    if not isinstance(text, (str, bytes)):
        raise ValidationError([_error('', 'Provide YAML or JSON text, not a file path or other value.')])
    try:
        raw = text.encode('utf-8') if isinstance(text, str) else text
        if len(raw) > MAX_BYTES:
            raise ValidationError([_error('', 'Definition exceeds the 16 KiB UTF-8 limit.')])
        text = raw.decode('utf-8')
    except UnicodeError as exc:
        raise ValidationError([_error('', 'Definition must be valid UTF-8.')]) from exc

    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('Duplicate object keys are forbidden.')
            out[key] = value
        return out

    def constant(_value):
        raise ValueError('Nonfinite numbers are forbidden.')

    try:
        try:
            value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        except json.JSONDecodeError:
            try:
                from ruamel.yaml import YAML
                from ruamel.yaml.tokens import AliasToken
            except ImportError as exc:
                raise ValidationError([_error('', 'YAML support is unavailable; provide JSON instead.')]) from exc
            yaml = YAML(typ='safe')
            yaml.allow_duplicate_keys = False
            # Aliases are unnecessary for small definitions and can amplify input.
            if any(isinstance(token, AliasToken) for token in yaml.scan(text)):
                raise ValueError('YAML aliases are forbidden; write values explicitly.')
            value = yaml.load(text)
    except ValidationError:
        raise
    except Exception as exc:
        # Parser exceptions can contain attacker-controlled input; never expose
        # arbitrary object reprs. Keep line/column when available for draft fixes.
        mark = getattr(exc, 'problem_mark', None)
        location = f' at line {mark.line + 1}, column {mark.column + 1}' if mark else ''
        raise ValidationError([_error('', 'Invalid YAML/JSON, duplicate keys, aliases or unsafe values' + location + '.')]) from exc
    if not isinstance(value, dict):
        raise ValidationError([_error('', 'A pulse definition must be one object.')])
    _bounded(value)
    return value


def _legacy_semantic_errors(definition):
    """Cross-field semantics beyond the normative shape schema. No I/O."""
    if not isinstance(definition, dict):
        return []
    errors = []
    source = definition.get('source')
    if not isinstance(source, dict) or not isinstance(source.get('kind'), str):
        return errors
    kind = source['kind'].removesuffix('@1')
    if kind not in KINDS:
        return errors
    meta = KINDS[kind]
    params = source.get('params', {})
    if not isinstance(params, dict):
        return errors
    metrics = metrics_for_params(kind, params)
    if kind in ('http_json', 'mcp.tool') and not isinstance(metrics, dict):
        return errors
    if not isinstance(metrics, (dict, list)):
        return errors

    def metric(item, path):
        if isinstance(item, dict) and isinstance(item.get('metric'), str) and item['metric'] not in metrics:
            errors.append(_error(path + '/metric', 'Unknown metric for ' + kind + '; choose: ' + ', '.join(metrics) + '.'))

    ring = definition.get('ring', {})
    components = ring.get('components', []) if isinstance(ring, dict) else []
    if isinstance(components, list):
        weights: list[Any] = [c.get('weight') for c in components if isinstance(c, dict)]
        if (weights and len(weights) == len(components)
                and all(_matches_type(w, 'number') and 0 <= w <= 100 for w in weights)):
            if abs(math.fsum(weights) - 100) > 0.010000000001:
                errors.append(_error('/ring/components', 'Component weights must sum to 100 (±0.01).'))
        for index, item in enumerate(components):
            path = f'/ring/components/{index}'
            metric(item, path)
            if (isinstance(item, dict) and item.get('baseline') == 'source'
                    and (not isinstance(item.get('metric'), str)
                         or item['metric'] not in meta['source_baselines'])):
                errors.append(_error(path + '/baseline', 'This metric has no source-declared baseline; use median, oldest, or a fixed number.'))
    metric(definition.get('capsule'), '/capsule')
    lines = definition.get('lines', [])
    if isinstance(lines, list):
        for index, item in enumerate(lines):
            metric(item, f'/lines/{index}')
    # Display-aware alert refs are checked by the extension semantic pass.
    alert = definition.get('alert')
    if 'display' not in definition and isinstance(alert, dict) and isinstance(alert.get('metric'), str) and '.' not in alert['metric']:
        metric(alert, '/alert')
    return errors


def _kind_param_errors(definition):
    """Cross-field params rules the shape schema cannot express. No I/O."""
    if not isinstance(definition, dict):
        return []
    if isinstance(definition.get('feeds'), dict):
        feeds = [('/feeds/' + name.replace('~', '~0').replace('/', '~1'), feed)
                 for name, feed in definition['feeds'].items()]
    else:
        feeds = [('/source', definition.get('source'))]
    errors = []
    for path, feed in feeds:
        if not isinstance(feed, dict) or not isinstance(feed.get('kind'), str):
            continue
        params = feed.get('params', {})
        if feed['kind'].removesuffix('@1') != 'desktop.notifications' or not isinstance(params, dict):
            continue
        apps, ids = params.get('apps', []), params.get('app_ids', [])
        if not isinstance(apps, list) or not isinstance(ids, list):
            continue
        if not apps and not ids:
            errors.append(_error(path + '/params', 'Choose at least one app in apps or app_ids.'))
        for key, values in [('apps', apps), ('app_ids', ids)]:
            folded = [v.lower() for v in values if isinstance(v, str)]
            if len(set(folded)) != len(folded):
                errors.append(_error(path + '/params/' + key, 'Each app may appear only once.'))
        types = params.get('types', [])
        if isinstance(types, list) and len(set(map(str, types))) != len(types):
            errors.append(_error(path + '/params/types', 'Each type may appear only once.'))
        if len(apps) + len(ids) > desktop_apps.MAX_APPS:
            errors.append(_error(path + '/params', f'Watch at most {desktop_apps.MAX_APPS} apps per feed.'))
    return errors


def semantic_errors(definition):
    return (_legacy_semantic_errors(definition) + _kind_param_errors(definition)
            + display_spec.semantic_errors(definition))


def validate(definition):
    """Return actionable {path,message} errors, or [] for a valid definition.

    Text is accepted as a convenience; normalization is deliberately separate.
    """
    if isinstance(definition, (str, bytes)):
        try:
            definition = parse(definition)
        except ValidationError as exc:
            return exc.errors
    try:
        _bounded(definition)
    except ValidationError as exc:
        return exc.errors
    errors = _shape(definition, SCHEMA) + semantic_errors(definition)
    # A JSON Schema integer may accept 1.0; pulse is explicitly an integer major.
    if isinstance(definition, dict) and type(definition.get('pulse')) is float:
        errors.append(_error('/pulse', 'Spec major must be an integer, not a float.'))
    return [dict(item) for item in { (e['path'], e['message']): e for e in errors }.values()]


def _slug(title):
    ascii_title = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode()
    slug = re.sub('[^a-z0-9]+', '-', ascii_title.lower()).strip('-')[:48].rstrip('-')
    return slug if len(slug) >= 2 else slug + '-pulse' if slug else 'pulse'


def normalize(definition):
    """Validate, expand presets/defaults and return a new idempotent dict."""
    if isinstance(definition, (str, bytes)):
        definition = parse(definition)
    errors = validate(definition)
    if errors:
        raise ValidationError(errors)
    out = deepcopy(definition)
    if 'feeds' in out:
        out['feeds'] = feeds_of(out)
        out.setdefault('id', _slug(out['title']))
        out.setdefault('icon', 'source')
        if 'alert' in out:
            out['alert'].setdefault('notify', 'none')
        display_spec.normalize_display(out)
        errors = validate(out)
        if errors:
            raise ValidationError(errors)
        return out
    kind = out['source']['kind'].removesuffix('@1')
    out['source']['kind'] = kind
    meta = KINDS[kind]
    params = out['source'].setdefault('params', {})
    for key, rule in meta['params_schema']['properties'].items():
        if 'default' in rule and not (kind == 'github.repo' and key in ('activity', 'ci')):
            params.setdefault(key, deepcopy(rule['default']))
    if kind == 'discord.invite':
        params['invite'] = invite_code(params['invite'])
    preset = deepcopy(meta['preset'])
    if kind in ('http_json', 'mcp.tool'):
        first = next(iter(params['metrics']))
        preset['ring']['components'][0]['metric'] = first
        preset['capsule']['metric'] = first
        if kind == 'http_json' and len(params['url']) <= 300:
            preset['link'] = params['url']
    elif kind == 'discord.invite':
        preset['link'] = 'https://discord.gg/' + params['invite']
    elif kind == 'github.search':
        suffix = 'pulls' if params['type'] == 'pr' else 'issues'
        preset['link'] = f"https://github.com/{params['repo']}/{suffix}"
        preset['capsule']['label'] = '{value} ' + ('PRs' if params['type'] == 'pr' else 'issues') + ' / ' + params['window']
        preset['lines'][0]['label'] = 'usual ≈{value}/' + params['window'] + f" · {params['baseline_days']}-day avg"
    elif kind == 'desktop.notifications' and 'badge' in params['types']:
        preset['capsule']['label'] = '{value} in Windows'
    elif kind == 'github.repo':
        preset['link'] = 'https://github.com/' + params['repo']
    out.setdefault('id', _slug(out['title']))
    out.setdefault('every', meta['default_every'])
    for key, value in preset.items():
        out.setdefault(key, value)
    for component in out['ring']['components']:
        if component['type'] == 'delta':
            for key, value in [('baseline', 'median'), ('window', '24h'), ('floor', 1),
                               ('sensitivity', 1.0), ('direction', 'both')]:
                component.setdefault(key, value)
    for line in out['lines']:
        line.setdefault('show', 'value')
        line.setdefault('hide_when_zero', False)
    if 'alert' in out:
        out['alert'].setdefault('notify', 'none')
    display_spec.normalize_display(out)
    errors = validate(out)
    if errors:
        raise ValidationError(errors)
    return out


def budget(definition):
    """Exact steady-state recurring egress, before positive polling jitter.

    One-off icons are excluded; hosts still include the icon CDN so approval
    declares all egress. Runtime gates enforce aggregate quotas, not this parser.
    """
    out = normalize(definition)
    hosts = set()
    requests = []
    for feed in feeds_of(out).values():
        kind = feed['kind']
        meta = KINDS[kind]
        params = feed['params']
        hosts.update(meta['hosts'])
        if kind in ('http_json', 'web.feed'):
            hosts.add(urlsplit(params['url']).hostname.lower().rstrip('.'))
        poll_calls = meta['calls_per_poll'] + sum(call['calls'] for call in meta.get('poll_calls', [])
            if params.get(call['when_param']) is True)
        requests.append(3600 / duration_seconds(feed['every']) * poll_calls)
        for periodic in meta['periodic_calls']:
            if 'when_param' not in periodic or params.get(periodic['when_param']):
                requests.append(3600 / periodic['every'] * periodic['calls'])
        if out.get('icon') == 'source' and kind.startswith('github.'):
            hosts.add('avatars.githubusercontent.com')
    icon = out.get('icon')
    if isinstance(icon, dict) and 'url' in icon:
        hosts.add(urlsplit(icon['url']).hostname.lower().rstrip('.'))
    total = math.fsum(requests)
    return {'hosts': sorted(hosts), 'req_per_hour': total, 'req_per_hour_display': math.ceil(total)}


def admission(active_budgets, draft_budget, ceiling=DEFAULT_REQUESTS_PER_HOUR):
    """Pure admission check. Never round before summing recurring requests."""
    remaining = max(0, ceiling - math.fsum(b['req_per_hour'] for b in active_budgets))
    if draft_budget['req_per_hour'] > remaining + 1e-9:
        return [_error('/budget', f'Request budget exceeded; {remaining:g} req/h remaining.')]
    return []
