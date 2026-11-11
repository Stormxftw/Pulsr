"""Regression coverage for public transport, route edge cases and icon delivery."""
import importlib.util
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reliability_api', ROOT / 'dashboard/plugin_api.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
core = api._core
RAW = json.loads((ROOT / 'tests/fixtures/nousresearch.json').read_text())
PNG = (ROOT / 'tests/fixtures/tiny.png').read_bytes()


@pytest.mark.parametrize('body', [b'null', b'[]', b'{"retry_after":null}', b'{"retry_after":"nan"}'])
def test_malformed_429_body_does_not_become_500(monkeypatch, body):
    class Opener:
        def open(self, request, timeout):
            raise core.urllib.error.HTTPError(request.full_url, 429, 'limit', {}, io.BytesIO(body))
    monkeypatch.setattr(core.urllib.request, 'build_opener', lambda *_: Opener())
    with pytest.raises(core.DiscordError) as error:
        core.discord_get('/api/v10/invites/nousresearch?with_counts=true')
    assert error.value.status == 429 and error.value.retry_after == 600
