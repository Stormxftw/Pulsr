"""Bounded offline block toolkit, derived from the validator's actual schemas."""
import copy

from .display_spec import style_schema
from .spec import SCHEMA

RESPONSE_MAX_BYTES = 65536


def toolkit():
    examples = {
        'score': {'type': 'score', 'components': [{'metric': 'stars', 'type': 'delta', 'weight': 100}]},
        'rings': {'type': 'rings', 'rings': [{'value': 'stars'}]},
        'bar': {'type': 'bar', 'value': 'stars'},
        'bars': {'type': 'bars', 'bars': [{'value': 'stars'}, {'value': 'forks'}]},
        'stat': {'type': 'stat', 'value': 'stars'},
        'spark': {'type': 'spark', 'value': 'stars'},
    }
    scale_defaults = {'min': 0, 'max': 'auto', 'auto_window': '7d'}
    defaults = {'score': {'delta_component': {'baseline': 'median', 'window': '24h', 'floor': 1,
                    'sensitivity': 1.0, 'direction': 'both'}},
                'rings': {'item': scale_defaults}, 'bar': scale_defaults,
                'bars': {'scale': 'shared', 'shared': scale_defaults, 'independent_item': scale_defaults},
                'stat': {'show': 'value', 'delta_vs': 'usual', 'auto_window': '7d'},
                'spark': {'points': 24}}
    limits = {'score': {'components': [1, 4], 'weight_sum': 100, 'weight_tolerance': 0.01, 'feeds': 1},
              'rings': {'items': [1, 3]}, 'bar': {'items': 1}, 'bars': {'items': [2, 3]},
              'stat': {'decimals': [0, 3]}, 'spark': {'points': [8, 48]}}
    blocks = {}
    for branch in SCHEMA['properties']['display']['items']['allOf']:
        rule = branch['then']
        kind = rule['properties']['type']['const']
        blocks[kind] = {'fields': copy.deepcopy(rule['properties']), 'required': rule['required'][:],
                        'limits': limits[kind], 'defaults': copy.deepcopy(defaults[kind]), 'example': examples[kind]}
    return {'response_max_bytes': RESPONSE_MAX_BYTES, 'blocks': blocks,
        'block_default_rules': {'label': 'Items/stat/spark default to humanized metric; rings/bars/score block label omitted.',
            'zones_direction': 'up', 'style_theme': 'Not default-expanded; renderer owns defaults.',
            'stat_decimals': 'Omitted when unspecified; engine numeric formatter, not a fixed decimal count.'},
        'scales': {'forms': {'min': ['finite number', 'auto', 'feed.metric'],
                             'max': ['finite number', 'auto', 'usual', 'feed.metric']},
            'defaults': scale_defaults, 'auto_window_seconds': [3600, 604800],
            'auto': {'minimum_samples': 3, 'minimum_span_seconds': 3600,
                     'min': 'nice_down(min measured value in window)',
                     'max': 'nice_up(max measured value in window)',
                     'nice_steps': [1, 2, 2.5, 5, 10], 'nice_power_base': 10,
                     'relative_tolerance': 1e-9, 'significant_digits': 12,
                     'nice_up': 'Smallest nice step × 10^k >= x (within relative tolerance).',
                     'nice_down': 'Largest of 1/2/2.5/5 × 10^k <= x for x >= 0.',
                     'nice_up_nonpositive': 0, 'nice_down_negative': '-nice_up(-x)',
                     'nice_down_tiny_positive': '0 below 1e-12', 'zero_max_with_zero_min': 1,
                     'shared_bars': 'Union of distinct bound metrics, not repeated references.'},
            'usual': 'max = 2 × median of prior measured values in window; min must be 0; learning until a positive prior median.',
            'rules': ['Fixed min must be < max.', 'Ref bounds cannot equal their own value or any shared group value.',
                      'Unknown ref bound or resolved max <= min means range unavailable, never zero.',
                      'Shared bars use block-level bounds; independent bars use item-level bounds.'],
            'zones': {'fields': {'warn': 'finite number', 'crit': 'finite number', 'direction': ['up', 'down']},
                      'defaults': {'direction': 'up'}, 'rules': 'At least warn or crit; up warn < crit; down warn > crit.'}},
        'style': {'colors': ['#rgb', '#rrggbb', '#rrggbbaa'],
            'tokens': ['accent', 'ok', 'warn', 'crit', 'muted', 'ink'],
            'scopes': {'theme': copy.deepcopy(SCHEMA['properties']['theme']['properties']),
                       'item': style_schema(item=True)['properties'],
                       **{kind: style_schema(kind)['properties'] for kind in blocks}},
            'defaults': 'Renderer-owned; omitted style/theme keys are not default-expanded.',
            'rules': 'Unknown keys are errors except x-*. Style/theme never affect approval cards.'},
        'icons': {'forms': ['source', 'hermes', 'initials', 'one emoji', {'brand': 'slug'},
                            {'url': 'public HTTPS URL'}, {'emoji': 'one emoji'}],
            'brand_query': 'Optional catalog string, 1–80 characters; up to 10 slug/title matches, substring then difflib; bundled artwork, no network.',
            'url_max_chars': 300, 'object_keys': 'Exactly one form plus optional x-* metadata.',
            'network_rules': ['Brand/Hermes/initials/emoji are offline.',
                'URL: public HTTPS/443, no userinfo or credential query keys; runtime DNS/SSRF checks, no redirects, no remote SVG.',
                'Icon hosts join budget.hosts; one-off fetches do not add req/h. Raster PNG/JPEG/WebP ≤256 KiB; cached after approval only.',
                'Source GitHub avatars require avatars.githubusercontent.com in persisted budget; Discord uses disclosed CDN.',
                'Source MCP HTTPS icons require an already disclosed host; undisclosed hosts are skipped, raster data icons decode locally.',
                'Catalog, layout check, status and proposal never fetch icons.']},
        'feeds': {'min': 1, 'max': 3, 'name_pattern': '^[a-z][a-z0-9_]{0,15}$',
            'fields': ['kind', 'params', 'every'], 'cadence': 'Per-kind default/minimum; see kinds.',
            'source': 'Exactly one of source or feeds. source creates implicit main feed.',
            'display': 'Required with feeds; 1–4 blocks; first block is hero.',
            'forbidden_with_feeds': ['every', 'ring', 'capsule', 'lines'],
            'ref': 'feed.metric; declared metrics only; bare metric allowed only with one feed; no arithmetic.',
            'max_bindings': 8, 'binding_count': 'Each display value, ref min/max, score component; repeated refs count; alerts excluded.',
            'budget': 'Exact sum over feeds; sorted host union plus icon hosts; approval admission unchanged.'}}
