"""Print actual offline Builder 2 response examples; never calls lookup services.

Run with the same isolated test dependencies as pytest. Lookup example is an
app-ID parse (calls:0), not a simulated service response. No Engine/store needed.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pulse_rings.templates import catalog, from_template
from pulse_rings.layout_presets import layouts
from pulse_rings.builder_lookup import lookup

converted = from_template('steam', {'appid': '730'})
examples = {
    'GET /builder/templates': {'response': catalog()},
    'POST /builder/from-template': {
        'request': {'template': 'steam', 'values': {'appid': '730'}},
        'response': converted,
    },
    'POST /builder/layouts': {
        'request': {'feeds': converted['feeds'], 'metrics': ['main.players'], 'title': converted['suggested_title'], 'icon': converted['suggested_icon']},
        'response': layouts(converted['feeds'], ['main.players'], converted['suggested_title'], converted['suggested_icon']),
    },
    'POST /builder/lookup': {
        'request': {'kind': 'steam', 'q': '730', 'confirm': True},
        'response': lookup(Path(__file__).parent, 'steam', '730', True, fetch=lambda *a, **k: (_ for _ in ()).throw(AssertionError('Examples must stay offline'))),
    },
}
print(json.dumps(examples, ensure_ascii=False, indent=2, allow_nan=False))
