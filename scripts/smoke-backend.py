"""Opt-in live smoke, five invites and at most five public widgets."""
import datetime
import importlib.util
import json
import pathlib
import time
import sys

root = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pulse_smoke', root / 'dashboard/pulse.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else 'artifacts')
out.mkdir(parents=True, exist_ok=True)
p = core.Pulse(out / 'smoke-data')
for entry in core.CURATED:
    result = p.add(entry['code'])
    # Previous real invite observation, NOT a fabricated trend or test sample.
    old = core.normalize_invite(json.loads((root / 'tests/fixtures' / (entry['code'] + '.json')).read_text(encoding='utf-8')))
    old['ts'] = datetime.datetime.fromisoformat(entry['verified_at']).timestamp()
    with p.db() as db:
        db.execute('INSERT OR IGNORE INTO snapshots VALUES (?,?,?)', (old['id'], old['ts'], json.dumps(old)))
    time.sleep(2.2)
    p.poll_one()
    time.sleep(2.2)
status = p.status()
(out / 'live-status.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
for s in status['servers']:
    print(json.dumps({k:s[k] for k in ['name','code','online','members','movement','widget_state','voice_channels']}), flush=True)

# Exercise the real API against the isolated live data, not the user's watchlist.
from fastapi import FastAPI
from fastapi.testclient import TestClient
import base64
api_spec = importlib.util.spec_from_file_location('smoke_api', root / 'dashboard/plugin_api.py')
api = importlib.util.module_from_spec(api_spec)
api_spec.loader.exec_module(api)
app = FastAPI()
app.include_router(api.router, prefix='/api/plugins/pulse-rings')
app.dependency_overrides[api.get_pulse] = lambda: p
results = []
with TestClient(app) as client:
    response = client.get('/api/plugins/pulse-rings/status')
    assert response.status_code == 200
    served = response.json()['servers']
    assert len(served) == len(core.CURATED) == 5
    for server in served:
        image = server['icon_data']
        assert image and image.startswith('data:image/png;base64,')
        raw = base64.b64decode(image.split(',', 1)[1])
        cached = p.icon_path(server['id'], server['icon_hash'])
        assert cached.read_bytes() == raw
        results.append({'code':server['code'], 'guild_id':server['id'], 'icon_hash':server['icon_hash'], 'cache':str(cached), 'bytes':len(raw), 'served_in_status':True})
# Same hash must be entirely cache-served, even with the CDN unavailable.
p.icon_fetch = lambda *_: (_ for _ in ()).throw(AssertionError('unexpected CDN refetch'))
for server in served:
    p.cache_icon(server)
(out / 'icon-smoke.json').write_text(json.dumps({'api_status':200,'servers':results,'same_hash_no_refetch':True}, indent=2), encoding='utf-8')
print('LIVE ICON SMOKE: 5/5 downloaded, validated, cached and API-served; unchanged hashes do not refetch.', flush=True)
