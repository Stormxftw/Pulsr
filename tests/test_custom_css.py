"""Optional user-owned CSS is bounded local data, never a path service."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path):
    spec = importlib.util.spec_from_file_location('custom_css_api', ROOT / 'dashboard/plugin_api.py')
    assert spec is not None and spec.loader is not None
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_pulse] = lambda: SimpleNamespace(store=SimpleNamespace(root=tmp_path))
    with TestClient(app) as client:
        yield client


def test_custom_css_optional_bounded_and_text(client, tmp_path):
    assert client.get('/custom.css').status_code == 404
    target = tmp_path / 'custom.css'
    target.write_text('.pr-block { color: red; }', encoding='utf-8')
    response = client.get('/custom.css')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/css')
    assert response.text == target.read_text(encoding='utf-8')
    assert response.headers['x-content-type-options'] == 'nosniff'
    transported = client.get('/custom.css?format=json')
    assert transported.headers['content-type'].startswith('application/json')
    assert transported.json() == response.text
    target.write_bytes(b'\xff')
    assert client.get('/custom.css').status_code == 404
    assert client.get('/custom.css?format=json').status_code == 404
    target.write_bytes(b' ' * 65536)
    assert client.get('/custom.css').status_code == 200
    target.write_bytes(b' ' * 65537)
    assert client.get('/custom.css').status_code == 404
    target.unlink()
    target.mkdir()
    assert client.get('/custom.css').status_code == 404


def test_custom_css_symlinks_rejected(client, tmp_path):
    source = tmp_path / 'source.css'
    source.write_text('.pr-block { color: red; }')
    try:
        (tmp_path / 'custom.css').symlink_to(source)
    except OSError:
        pytest.skip('Symlink creation requires Windows Developer Mode or privilege')
    assert client.get('/custom.css').status_code == 404
