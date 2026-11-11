"""Offline transport/cache and malformed public-response regressions."""
import base64
import importlib.util
import io
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('icons_core', ROOT / 'dashboard/pulse.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
RAW = json.loads((ROOT / 'tests/fixtures/nousresearch.json').read_text())
PNG = (ROOT / 'tests/fixtures/tiny.png').read_bytes()


def test_icon_cache_is_local_hash_keyed_and_read_only(tmp_path):
    calls = []
    now = [1000]
    def fetch_icon(gid, icon_hash):
        calls.append((gid, icon_hash))
        return PNG
    raw = [RAW]
    p = core.Pulse(tmp_path, fetch=lambda _: raw[0], clock=lambda: now[0], jitter=lambda: 0, icon_fetch=fetch_icon)
    d = core._discord.preset('nousresearch', pulse_id='nous', title='Nous')
    p.activate(d)
    p.poll_one_due()
    row = p.status()['pulses'][0]
    s = core.normalize_invite(RAW)
    s['icon_data'] = p.icon_data(s)
    assert s['icon_data'] == 'data:image/png;base64,' + base64.b64encode(PNG).decode()
    assert p.icon_path(s['id'], s['icon_hash']).read_bytes() == PNG
    p.status()
    now[0] += 601
    p.poll_one()
    assert len(calls) == 1
    raw[0] = {**RAW, 'guild': {**RAW['guild'], 'icon': 'a_' + 'f' * 32}}
    now[0] += 601
    p.poll_one()
    assert len(calls) == 2
    assert calls[-1][1].startswith('a_')


def test_icon_failure_is_deduped_and_never_hides_counts(tmp_path):
    calls = []
    def fail(*args):
        calls.append(args)
        raise OSError('offline')
    p = core.Pulse(tmp_path, fetch=lambda _: RAW, clock=lambda: 1000, icon_fetch=fail)
    d = core._discord.preset('nousresearch', pulse_id='nous', title='Nous')
    p.activate(d)
    p.poll_one_due()
    row = p.status()['pulses'][0]
    s = core.normalize_invite(RAW)
    s['icon_data'] = p.icon_data(s)
    assert s['online'] is not None and s['icon_data'] is None
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda _: p.cache_icon(s), range(5)))
    assert len(calls) == 1


@pytest.mark.parametrize('raw', [None, [], {}, {'guild': None}, {'guild': {'id': RAW['guild']['id'], 'name': 7}}])
def test_malformed_invite_is_actionable(raw):
    with pytest.raises(core.DiscordError):
        core.normalize_invite(raw)


def test_optional_invite_fields_have_safe_types():
    raw = {**RAW, 'guild': {**RAW['guild'], 'description': 42, 'features': None}}
    s = core.normalize_invite(raw)
    assert s['description'] == '' and s['features'] == []


@pytest.mark.parametrize('kind,payload', [('text/html', PNG), ('image/png', b'<html>'), ('image/png', PNG + b'x' * 524288), ('image/jpeg', PNG)], ids=['html-type','html-body','oversize','mime-mismatch'])
def test_icon_transport_rejects_unsafe_content(monkeypatch, kind, payload):
    class Reply(io.BytesIO):
        headers = {'Content-Type': kind}
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == 'https://cdn.discordapp.com/icons/' + RAW['guild']['id'] + '/' + RAW['guild']['icon'] + '.png?size=128'
            assert not request.get_header('Authorization')
            return Reply(payload)
    monkeypatch.setattr(core.urllib.request, 'build_opener', lambda *_: Opener())
    with pytest.raises(core.DiscordError):
        core.discord_icon_get(RAW['guild']['id'], RAW['guild']['icon'])


def test_icon_transport_accepts_png_and_refuses_path_injection(monkeypatch):
    class Reply(io.BytesIO):
        headers = {'Content-Type': 'image/png'}
    class Opener:
        def open(self, request, timeout):
            return Reply(PNG)
    monkeypatch.setattr(core.urllib.request, 'build_opener', lambda *_: Opener())
    assert core.discord_icon_get(RAW['guild']['id'], RAW['guild']['icon']) == PNG
    with pytest.raises(ValueError):
        core.discord_icon_get('../evil', RAW['guild']['icon'])


def test_malformed_widget_preserves_cache(tmp_path):
    responses = [RAW]
    now = [1000]
    p = core.Pulse(tmp_path, lambda _: responses[0], lambda: now[0], icon_fetch=lambda *_: PNG)
    d = core._discord.preset('nousresearch', pulse_id='nous', title='Nous')
    p.activate(d)
    p.poll_one_due()
    now[0] += 3
    responses[0] = {'members': None, 'channels': None}
    p.poll_one()
    with p.db() as db:
        assert json.loads(db.execute('SELECT source_state FROM pulses').fetchone()[0])['widget_state'] == 'backoff'
    assert p.status()['pulses'][0]['capsule']['label'] != 'Online unknown'
