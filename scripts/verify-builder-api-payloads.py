"""Replay captured browser payloads through actual FastAPI + Store, fully offline."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pulse_rings.engine import Engine
from pulse_rings.sources.base import SourceError

payload_path = Path(sys.argv[1])
cases = json.loads(payload_path.read_text(encoding='utf-8'))
assert len(cases) == 8
assert len({case['fromTemplate']['template'] for case in cases}) == 8
spec = importlib.util.spec_from_file_location('builder_payload_api', ROOT / 'dashboard/plugin_api.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
report = []
network_attempts = []

class OfflineAdapter:
    def __init__(self, original):
        self.original = original

    def __getattr__(self, name):
        return getattr(self.original, name)

    def poll(self, *args, **kwargs):
        raise SourceError('Offline acceptance transport: no measured source data')

real_connect = socket.socket.connect

def forbidden(sock, address):
    # Windows asyncio constructs its self-pipe with a loopback socketpair.
    if isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1'}:
        return real_connect(sock, address)
    network_attempts.append(str(address))
    raise AssertionError('External connection attempted during offline acceptance')

with tempfile.TemporaryDirectory(prefix='wp14-api-', dir=os.environ.get('TMPDIR')) as temp:
    for index, case in enumerate(cases):
        engine = Engine(Path(temp) / str(index), clock=lambda: 10000, jitter=lambda: 0)
        engine.adapters = {kind: OfflineAdapter(adapter) for kind, adapter in engine.adapters.items()}
        app = FastAPI()
        app.include_router(api.router)
        app.dependency_overrides[api.get_pulse] = lambda: engine
        with patch.object(socket.socket, 'connect', forbidden), TestClient(app) as client:
            converted = client.post('/builder/from-template', json=case['fromTemplate'])
            assert converted.status_code == 200 and converted.json()['ok'], converted.text
            checked = client.post('/layout-check', json={'definition': case['definition']})
            assert checked.status_code == 200 and checked.json()['ok'], checked.text
            proposed = client.post('/drafts', json={'definition': case['definition']})
            assert proposed.status_code == 200, proposed.text
            draft_id = proposed.json()['draft_id']
            receipt = client.get('/drafts/' + draft_id)
            assert receipt.status_code == 200, receipt.text
            draft = receipt.json()
            assert draft['status'] == 'pending'
            assert draft['origin'] == {'kind': 'session', 'surface': 'desktop'}
            assert draft['definition']['feeds'] == checked.json()['normalized']['feeds']
            assert draft['definition']['display'] == checked.json()['normalized']['display']
            assert len(draft['disclosure']['feeds']) == len(draft['definition']['feeds'])
            assert not engine.store.rows(), 'Real API must not activate any pulse'
            report.append({'name': case['name'], 'template': case['fromTemplate']['template'],
                           'draft_id': draft_id, 'origin': draft['origin'],
                           'feed_count': len(draft['disclosure']['feeds']), 'pending': True})
            print('PASS ' + case['name'] + ' browser payload -> real converter -> real draft/readback')
assert not network_attempts
output = {'templates': len(report), 'network_attempts': len(network_attempts), 'results': report}
(payload_path.parent / 'frontend-real-api-results.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
print(json.dumps({'templates': len(report), 'network_attempts': len(network_attempts), 'activated_pulses': 0}))
