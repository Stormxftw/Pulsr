"""Preview-lab only: newline JSON -> REAL pure builder; no network or storage."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pulse_rings import builder
from pulse_rings.authoring import catalog

for line in sys.stdin:
    try:
        request = json.loads(line)
        path, body = request['path'], request.get('body', {})
        if path == '/layout-check':
            result = builder.layout_check(body['definition'])
        elif path == '/builder/preview':
            result = builder.sample_preview(body['definition'], body.get('state', 'measured'), body.get('seed', 0))
        elif path == '/builder/templates':
            from pulse_rings.templates import catalog as templates_catalog
            result = templates_catalog()
        elif path == '/builder/from-template':
            from pulse_rings.templates import from_template
            result = from_template(body['template'], body.get('values', {}))
        elif path == '/builder/layouts':
            from pulse_rings.layout_presets import layouts
            result = layouts(body['feeds'], body['metrics'], body.get('title'), body.get('icon'))
        elif path == '/fixture-disclosure':
            from pulse_rings.draft_disclosure import draft_disclosure
            from pulse_rings.spec import normalize
            # Offline fixture enrichment only, no connector binding or dispatch.
            result = draft_disclosure(normalize(body['definition']), Path(__file__).parent)
        elif path == '/brands':
            result = {'brands': builder.search_brands(body.get('q', ''))}
        elif path == '/catalog':
            result = catalog()
        else:
            raise ValueError('Unknown pure route')
        print(json.dumps({'id': request['id'], 'result': result}, allow_nan=False), flush=True)
    except Exception as exc:
        print(json.dumps({'id': request.get('id'), 'error': str(exc)}), flush=True)
