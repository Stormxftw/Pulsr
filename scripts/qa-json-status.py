"""Offline QA rows from recorded raw bodies + actual display/icon computation."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pulse_rings.builder import sample_preview
from pulse_rings.display import compute_display
from pulse_rings.spec import normalize, feeds_of
from pulse_rings.sources.http_json import json_pointer, _number

fixture = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/qa-json.json').read_text(encoding='utf-8'))
rows = []
for definition in fixture['definitions']:
    # The frozen legacy fixture crawler predates display; these are post-display bodies.
    d = normalize(dict(pulse=1, **definition))
    row = sample_preview(d)
    feeds = {}
    for name, feed in feeds_of(d).items():
        body = fixture[name if name in ('weather', 'air') else 'steam']
        metrics = {metric: _number(json_pointer(body, pointer)) for metric, pointer in feed['params']['metrics'].items()}
        history = [{'ts':1794186000 - 3600 * (23-i), 'metrics':dict(metrics) if name != 'main' else {'players':500000}} for i in range(24)]
        feeds[name] = {'current':{'ts':1794189600,'metrics':metrics}, 'history':history}
    row.update(display=compute_display(d, feeds), state='active', sample=False,
               last_ok_ts=1794189600, next_due=1794190200, backoff_until=0,
               ring={'score':0,'warming':False,'unknown':True,'components':[]},
               capsule={'label':'5.7 mph' if 'feeds' in d else '459,907', 'caption':'14% of 40' if 'feeds' in d else '92% of usual'},
               history=[], alert={'active':False}, kind='http_json', error=None)
    rows.append(row)
print(json.dumps(rows, ensure_ascii=True))
