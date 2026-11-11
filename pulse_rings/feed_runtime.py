"""Runtime projections of already-normalized definitions; no validation on reads."""
from .display_spec import feeds_of


def adapter_definition(definition, name):
    """Keep the frozen adapter shape and pulse identity, scoped to one feed."""
    if 'feeds' not in definition:
        return definition
    feed = definition['feeds'][name]
    return {'pulse': 1, 'id': definition['id'], 'title': definition['title'],
            'source': {'kind': feed['kind'], 'params': feed['params']}, 'every': feed['every']}


def source_fingerprint(definition, name):
    """Metric meaning: kind + all normalized params, excluding cadence/style."""
    import hashlib
    import json
    projected = adapter_definition(definition, name)['source']
    source = {key: projected[key] for key in ('kind', 'params')}
    return hashlib.sha256(json.dumps(source, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode('utf-8')).hexdigest()


def feed_budgets(definition):
    """Approval-time only. Icons belong to the pulse, not each recurring feed."""
    from .spec import budget
    return {name: budget(dict(adapter_definition(definition, name), icon='initials'))
            for name in feeds_of(definition)}


def hero_ref(definition):
    block = definition['display'][0]
    if block['type'] == 'score':
        return block['components'][0]['metric']
    if block['type'] in ('rings', 'bars'):
        return block[block['type']][0]['value']
    return block['value']


def icon_definition(definition):
    """Source icon follows hero, not resolver's multi-source precedence policy."""
    if 'feeds' not in definition:
        return definition
    projected = dict(definition)
    projected['feeds'] = {hero_ref(definition).split('.')[0]: definition['feeds'][hero_ref(definition).split('.')[0]]}
    return projected
