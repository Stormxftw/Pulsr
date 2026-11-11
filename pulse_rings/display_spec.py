"""Offline pulse/1 display shapes and semantics; no network or runtime state."""
from copy import deepcopy
import math
import re
from urllib.parse import parse_qsl, unquote, urlsplit

from . import brands
from .kinds import KINDS, obj, metrics_for_params, metric_label

REF_PATTERN = r'^(?:[a-z][a-z0-9_]{0,15}\.)?[A-Za-z][A-Za-z0-9_]{0,39}(?![\s\S])'
COLOR_PATTERN = r'^(?:#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8}|accent|ok|warn|crit|muted|ink)(?![\s\S])'
COLOR_KEYS = {'accent', 'surface', 'text', 'color', 'color2', 'track'}


def window_seconds(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,12}[smhd]', value):
        raise ValueError('Use a duration from 1h to 7d.')
    seconds = int(value[:-1]) * {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[value[-1]]
    if not 3600 <= seconds <= 604800:
        raise ValueError('Use a duration from 1h to 7d.')
    return seconds


def valid_window(value):
    if not isinstance(value, str):
        return True
    try:
        window_seconds(value)
        return True
    except ValueError:
        return False


def icon_url(value):
    from .spec import _https_url
    if not isinstance(value, str):
        return True
    if not _https_url(value, public=True):
        return False
    # As with MCP args, reject credential-named fields, not arbitrary query data.
    secret = re.compile(r'password|secret|token|authorization|api[_-]?key|cookie|credential', re.I)
    return not any(secret.search(unquote(key)) for key, _ in parse_qsl(urlsplit(value).query, keep_blank_values=True))


def integer(low, high):
    return {'type': 'integer', 'minimum': low, 'maximum': high}


def style_schema(kind=None, item=False):
    color = {'type': 'string', 'pattern': COLOR_PATTERN}
    fields = {'color': color}
    if item:
        return obj(fields)
    fields.update({'color2': color, 'track': color, 'thickness': integer(2, 24),
                   'radius': integer(0, 12), 'glow': integer(0, 16),
                   'text': {'enum': ['s', 'm', 'l']}, 'label': {'enum': ['above', 'inline', 'hidden']}})
    extra = {
        'rings': {'gap': integer(0, 6), 'cap': {'enum': ['round', 'flat']}, 'direction': {'enum': ['cw', 'ccw']}},
        'bar': {'ticks': {'enum': ['none', 'usual', 'zones']}, 'show_range': {'type': 'boolean'}},
        'bars': {'ticks': {'enum': ['none', 'usual', 'zones']}, 'show_range': {'type': 'boolean'}},
        'stat': {'delta_colors': {'enum': ['semantic', 'neutral']}},
        'spark': {'fill': {'enum': ['none', 'area']}, 'dot': {'enum': ['last', 'none']}},
    }
    fields.update(extra.get(kind, {}))
    return obj(fields)


def extend_schema(result, component):
    """Extend the legacy schema in place, sharing exactly its component rules."""
    ref = {'type': 'string', 'pattern': REF_PATTERN}
    text = {'type': 'string', 'maxLength': 40, 'format': 'pulse-display-text'}
    unit = dict(text, maxLength=8)
    state_label = {'type': 'string', 'minLength': 1, 'maxLength': 24,
                   'pattern': r'^[^<>]*$', 'format': 'pulse-display-text'}
    states = {'type': 'object', 'minProperties': 1, 'maxProperties': 8,
              'propertyNames': {'pattern': r'^-?(?:0|[1-9][0-9]{0,9})(?![\s\S])'},
              'additionalProperties': {'anyOf': [state_label, obj({'label': state_label,
                  'tone': {'enum': ['ok', 'warn', 'crit']}}, ['label'])]}}
    window = {'type': 'string', 'format': 'pulse-auto-window'}
    zones = obj({'warn': {'type': 'number'}, 'crit': {'type': 'number'},
                 'direction': {'enum': ['up', 'down']}})
    zones['anyOf'] = [{'required': ['warn']}, {'required': ['crit']}]
    scales = {
        'min': {'anyOf': [{'type': 'number'}, {'enum': ['auto']},
                           {'type': 'string', 'pattern': REF_PATTERN, 'not': {'enum': ['usual']}}]},
        'max': {'anyOf': [{'type': 'number'}, {'enum': ['auto', 'usual']}, ref]},
        'auto_window': window,
    }
    item_fields = dict(scales, value=ref, label=text, unit=unit, zones=zones, style=style_schema(item=True))
    item = obj(item_fields, ['value'])
    score_component = deepcopy(component)
    score_component['properties']['metric'] = ref
    blocks = []
    for kind in ['score', 'rings', 'bar', 'bars', 'stat', 'spark']:
        fields = {'type': {'const': kind}, 'label': text, 'style': style_schema(kind)}
        required = ['type']
        if kind == 'score':
            fields['components'] = {'type': 'array', 'minItems': 1, 'maxItems': 4, 'items': score_component}
            required += ['components']
        elif kind == 'rings':
            fields['rings'] = {'type': 'array', 'minItems': 1, 'maxItems': 3, 'items': item}
            required += ['rings']
        elif kind == 'bar':
            fields.update(item_fields)
            fields['style'] = style_schema(kind)
            required += ['value']
        elif kind == 'bars':
            fields.update(scales)
            fields.update({'bars': {'type': 'array', 'minItems': 2, 'maxItems': 3, 'items': item},
                           'scale': {'enum': ['shared', 'independent']}})
            required += ['bars']
        else:
            fields['value'] = ref
            required += ['value']
            if kind == 'stat':
                fields.update({'show': {'enum': ['value', 'delta', 'both']},
                               'delta_vs': {'enum': ['usual', 'previous']},
                               'unit': unit, 'states': states, 'decimals': integer(0, 3), 'auto_window': window})
            else:
                fields['points'] = integer(8, 48)
        blocks.append(obj(fields, required))
    # A discriminator yields field-level errors rather than a generic union error.
    block = {'type': 'object', 'properties': {'type': {'enum': ['score', 'rings', 'bar', 'bars', 'stat', 'spark']}},
             'required': ['type'], 'allOf': [
                 {'if': {'properties': {'type': {'const': kind}}, 'required': ['type']}, 'then': rule}
                 for kind, rule in zip(['score', 'rings', 'bar', 'bars', 'stat', 'spark'], blocks)]}
    feed = deepcopy(result['properties']['source'])
    feed['properties']['every'] = deepcopy(result['properties']['every'])
    feed['allOf'] = []
    for kind, meta in KINDS.items():
        branch = {'properties': {'params': deepcopy(meta['params_schema']), 'every': {'format': 'pulse-every-' + kind}}}
        if meta['params_schema']['required']:
            branch['required'] = ['params']
        feed['allOf'].append({'if': {'properties': {'kind': {'enum': [kind, kind + '@1']}}, 'required': ['kind']}, 'then': branch})
    result['properties'].update({
        'feeds': {'type': 'object', 'minProperties': 1, 'maxProperties': 3,
                  'propertyNames': {'pattern': r'^[a-z][a-z0-9_]{0,15}(?![\s\S])'}, 'additionalProperties': feed},
        'display': {'type': 'array', 'minItems': 1, 'maxItems': 4, 'items': block},
        'theme': obj({'accent': {'type': 'string', 'pattern': COLOR_PATTERN},
                      'surface': {'type': 'string', 'pattern': COLOR_PATTERN},
                      'text': {'type': 'string', 'pattern': COLOR_PATTERN},
                      'density': {'enum': ['compact', 'cozy', 'roomy']}, 'radius': integer(0, 24),
                      'font': {'enum': ['system', 'rounded', 'mono']}, 'motion': {'enum': ['none', 'calm', 'lively']}}),
    })
    result['required'].remove('source')
    result['oneOf'] = [{'required': ['source'], 'not': {'required': ['feeds']}},
                       {'required': ['feeds'], 'not': {'required': ['source']}}]
    result['allOf'].append({'if': {'required': ['feeds']}, 'then': {'required': ['display'],
                            'not': {'anyOf': [{'required': [key]} for key in ['every', 'ring', 'capsule', 'lines']]}}})
    result['properties']['alert']['properties']['metric'] = ref
    icon = obj({'brand': {'type': 'string', 'pattern': r'^[a-z0-9][a-z0-9._-]{0,63}(?![\s\S])'},
                'url': {'type': 'string', 'maxLength': 300, 'format': 'pulse-icon-url'},
                'emoji': {'type': 'string', 'format': 'pulse-emoji'}})
    icon['oneOf'] = [{'required': [key], 'not': {'anyOf': [{'required': [other]} for other in ['brand', 'url', 'emoji'] if other != key]}}
                     for key in ['brand', 'url', 'emoji']]
    result['properties']['icon'] = {'anyOf': [result['properties']['icon'], icon]}
    return result


def feeds_of(definition):
    """Return isolated canonical feeds, with kind/params/cadence defaults expanded."""
    from .spec import invite_code
    feeds = definition.get('feeds')
    if feeds is None:
        feeds = {'main': dict(definition['source'], every=definition.get('every', KINDS[definition['source']['kind'].removesuffix('@1')]['default_every']))}
    out = deepcopy(feeds)
    for feed in out.values():
        kind = feed['kind'].removesuffix('@1')
        feed['kind'] = kind
        meta = KINDS[kind]
        params = feed.setdefault('params', {})
        for key, rule in meta['params_schema']['properties'].items():
            if 'default' in rule and not (kind == 'github.repo' and key in ('activity', 'ci')):
                params.setdefault(key, deepcopy(rule['default']))
        if kind == 'discord.invite':
            params['invite'] = invite_code(params['invite'])
        feed.setdefault('every', meta['default_every'])
    return out


def _bindings(definition):
    """Enumerate written display/alert bindings; never descend into x-* data."""
    display = definition.get('display', [])
    if isinstance(display, list):
        for index, block in enumerate(display):
            if not isinstance(block, dict):
                continue
            path = f'/display/{index}'
            if block.get('type') == 'score':
                components = block.get('components', [])
                if isinstance(components, list):
                    for j, component in enumerate(components):
                        if isinstance(component, dict) and 'metric' in component:
                            yield f'{path}/components/{j}/metric', component['metric']
            else:
                items = [(path, block)]
                for key in ['rings', 'bars']:
                    if isinstance(block.get(key), list):
                        items += [(f'{path}/{key}/{j}', item) for j, item in enumerate(block[key]) if isinstance(item, dict)]
                for item_path, item in items:
                    if 'value' in item:
                        yield item_path + '/value', item['value']
                    for key in ['min', 'max']:
                        value = item.get(key)
                        if isinstance(value, str) and value not in ('auto', 'usual'):
                            yield item_path + '/' + key, value
    alert = definition.get('alert')
    if isinstance(alert, dict) and 'metric' in alert:
        yield '/alert/metric', alert['metric']


def bindings_of(definition):
    """Return (JSON Pointer, canonical ref) pairs, including alert references.

    Legacy display fields are not display bindings and do not consume the new cap.
    """
    names = list(definition.get('feeds', {'main': {}}))
    return [(path, names[0] + '.' + ref if isinstance(ref, str) and '.' not in ref and len(names) == 1 else ref)
            for path, ref in _bindings(definition)]


def semantic_errors(definition):
    from .spec import _error, _matches_type
    errors = []
    if not isinstance(definition, dict):
        return errors
    if 'feeds' in definition:
        for key in ['every', 'ring', 'capsule', 'lines']:
            if key in definition:
                errors.append(_error('/' + key, 'With feeds, use display and per-feed every.'))
    raw = definition.get('feeds', {'main': definition.get('source')})
    feeds = raw if isinstance(raw, dict) else {}
    metrics = {}
    for name, feed in feeds.items():
        if not isinstance(feed, dict) or not isinstance(feed.get('kind'), str):
            continue
        kind = feed['kind'].removesuffix('@1')
        if kind not in KINDS:
            continue
        params = feed.get('params', {})
        if not isinstance(params, dict):
            continue
        declared = metrics_for_params(kind, params)
        if isinstance(declared, (list, dict)):
            metrics[name] = declared

    def resolve(ref, path):
        if not isinstance(ref, str) or not re.fullmatch(REF_PATTERN, ref):
            return None
        if '.' not in ref:
            if len(feeds) != 1:
                errors.append(_error(path, 'Use feed.metric when more than one feed is declared.'))
                return None
            ref = next(iter(feeds)) + '.' + ref
        feed, metric = ref.split('.')
        if feed not in feeds:
            errors.append(_error(path, f"Unknown feed '{feed}'."))
            return None
        if feed not in metrics:
            return None  # Shape errors already explain the malformed feed.
        if metric not in metrics[feed]:
            errors.append(_error(path, f"Unknown metric '{metric}' for feed '{feed}'."))
            return None
        return ref

    written = list(_bindings(definition))
    refs = {path: resolve(ref, path) for path, ref in written}
    # Alerts are thresholds, not score/value/scale bindings in the eight-binding cap.
    if sum(path.startswith('/display/') for path, _ in written) > 8:
        errors.append(_error('/display', 'At most 8 display bindings are allowed.'))
    display = definition.get('display', [])

    def scale(item, path, values=()):
        lo, hi = item.get('min', 0), item.get('max', 'auto')
        if _matches_type(lo, 'number') and _matches_type(hi, 'number') and lo >= hi:
            errors.append(_error(path + '/max', 'Fixed min must be less than max.'))
        if hi == 'usual' and (not _matches_type(lo, 'number') or lo != 0):
            errors.append(_error(path + '/max', 'max: usual requires min: 0.'))
        own = [refs.get(path + '/value')] + list(values)
        for key in ['min', 'max']:
            bound = refs.get(path + '/' + key)
            if bound is not None and bound in own:
                errors.append(_error(path + '/' + key, 'A bound cannot reference its own value.'))
        zones = item.get('zones')
        if isinstance(zones, dict) and all(_matches_type(zones.get(k), 'number') for k in ['warn', 'crit']):
            warn, crit = zones['warn'], zones['crit']
            if (zones.get('direction', 'up') == 'up' and warn >= crit
                    or zones.get('direction') == 'down' and warn <= crit):
                errors.append(_error(path + '/zones/crit', 'Zones must increase for up and decrease for down.'))

    if isinstance(display, list):
        for i, block in enumerate(display):
            if not isinstance(block, dict):
                continue
            path = f'/display/{i}'
            kind = block.get('type')
            if kind == 'stat' and 'states' in block and block.get('unit') == 'duration':
                errors.append(_error(path + '/states', 'Choose states or duration, not both.'))
            if kind == 'score':
                components = block.get('components', [])
                if not isinstance(components, list):
                    continue
                weights = [c.get('weight') for c in components if isinstance(c, dict)]
                if (weights and len(weights) == len(components)
                        and all(_matches_type(w, 'number') and 0 <= w <= 100 for w in weights)
                        and abs(math.fsum(weights) - 100) > 0.010000000001):
                    errors.append(_error(path + '/components', 'Component weights must sum to 100 (±0.01).'))
                bound_feeds = set()
                for j, component in enumerate(components):
                    ref = refs.get(f'{path}/components/{j}/metric')
                    if ref:
                        feed, metric = ref.split('.')
                        bound_feeds.add(feed)
                        if component.get('baseline') == 'source':
                            meta = KINDS[feeds[feed]['kind'].removesuffix('@1')]
                            if metric not in meta['source_baselines']:
                                errors.append(_error(f'{path}/components/{j}/baseline', 'This metric has no source-declared baseline.'))
                if len(bound_feeds) > 1:
                    errors.append(_error(path + '/components', 'All score components must use one feed.'))
            elif kind == 'bar':
                scale(block, path)
            elif kind in ('rings', 'bars'):
                items = block.get(kind, [])
                if not isinstance(items, list):
                    continue
                shared = kind == 'bars' and block.get('scale', 'shared') == 'shared'
                if kind == 'bars':
                    if shared:
                        scale(block, path, [refs.get(f'{path}/bars/{j}/value') for j in range(len(items))])
                    else:
                        for key in ['min', 'max', 'auto_window']:
                            if key in block:
                                errors.append(_error(path + '/' + key, 'Independent bars use item-level scales.'))
                for j, item in enumerate(items):
                    if not isinstance(item, dict):
                        continue
                    item_path = f'{path}/{kind}/{j}'
                    if shared and any(key in item for key in ['min', 'max', 'auto_window']):
                        errors.append(_error(item_path, 'Shared bars use the block-level scale.'))
                    scale(item, item_path)
    icon = definition.get('icon')
    if isinstance(icon, dict) and isinstance(icon.get('brand'), str) and not brands.has_brand(icon['brand']):
        suggestion = brands.suggest(icon['brand'])
        message = 'Unknown brand.' + (f" Did you mean '{suggestion}'?" if suggestion else ' No close bundled brand was found.')
        errors.append(_error('/icon/brand', message))
    return errors


def normalize_display(out):
    """Canonicalize display-only data on an already copied, validated definition."""
    def canonical_style(style):
        for key in COLOR_KEYS:
            if isinstance(style.get(key), str) and style[key].startswith('#'):
                style[key] = style[key].lower()

    for path, ref in bindings_of(out):
        # Existing source-only alerts retain their historical bare metric shape.
        if path == '/alert/metric' and 'source' in out and 'display' not in out and '.' not in out['alert']['metric']:
            continue
        node = out
        parts = path.strip('/').split('/')
        for part in parts[:-1]:
            node = node[int(part)] if isinstance(node, list) else node[part]
        node[parts[-1]] = ref

    def item_defaults(item, scales=True):
        item.setdefault('label', metric_label(item['value'].split('.')[1]))
        if scales:
            for key, value in [('min', 0), ('max', 'auto'), ('auto_window', '7d')]:
                item.setdefault(key, value)
        if 'zones' in item:
            item['zones'].setdefault('direction', 'up')
        if 'style' in item:
            canonical_style(item['style'])

    if 'theme' in out:
        canonical_style(out['theme'])
    for block in out.get('display', []):
        kind = block['type']
        if 'style' in block:
            canonical_style(block['style'])
        if kind == 'score':
            for component in block['components']:
                if component['type'] == 'delta':
                    for key, value in [('baseline', 'median'), ('window', '24h'), ('floor', 1), ('sensitivity', 1.0), ('direction', 'both')]:
                        component.setdefault(key, value)
        elif kind in ('rings', 'bars'):
            shared = kind == 'bars' and block.setdefault('scale', 'shared') == 'shared'
            if shared:
                for key, value in [('min', 0), ('max', 'auto'), ('auto_window', '7d')]:
                    block.setdefault(key, value)
            for item in block[kind]:
                item_defaults(item, not shared)
        else:
            item_defaults(block, kind == 'bar')
            if kind == 'stat':
                block.setdefault('show', 'value')
                block.setdefault('delta_vs', 'usual')
                block.setdefault('auto_window', '7d')
            elif kind == 'spark':
                block.setdefault('points', 24)
    return out
