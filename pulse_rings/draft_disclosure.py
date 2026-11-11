"""Fresh approval-only feed disclosures. No dispatch or persisted policy claims."""
import json

from .feed_runtime import adapter_definition
from .layout import proposal_disclosure
from .sources.mcp import disclosure as mcp_disclosure


def draft_disclosure(definition, root):
    if not definition.get('source') and not definition.get('feeds'):
        return {'feeds': [], 'icon_hosts': []}  # corrupt/unsupported draft: fail closed
    result = proposal_disclosure(definition)
    for row in result['feeds']:
        projected = adapter_definition(definition, row['name'])
        row['params'] = projected['source']['params']
        if row['kind'] == 'mcp.tool':
            row['mcp'] = mcp_disclosure(projected, root)
            row['mcp']['args_full'] = json.dumps(row['params'].get('args', {}),
                ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    # Budget is the durable draft's allocation, not a newly trusted approval.
    return {'feeds': result['feeds'], 'icon_hosts': result['icon_hosts']}
