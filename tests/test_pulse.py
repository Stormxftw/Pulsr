"""Recorded Discord responses only. Tests never contact the network."""
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

core = load('pulse_test_core', ROOT / 'dashboard/pulse.py')
api = load('pulse_test_api', ROOT / 'dashboard/plugin_api.py')
RAW = json.loads((ROOT / 'tests/fixtures/nousresearch.json').read_text(encoding='utf-8'))

@pytest.fixture
def rig(tmp_path):
    now = [1000000.0]
    calls = []
    responses = [RAW]
    def fetch(path):
        calls.append(path)
        item = responses[-1]
        if isinstance(item, Exception):
            raise item
        return item
    pulse = core.Pulse(tmp_path, fetch, lambda: now[0], lambda: 0, icon_fetch=lambda *_: b'')
    return pulse, now, calls, responses

@pytest.mark.parametrize('value,expected', [
    ('nousresearch', 'nousresearch'), ('https://discord.gg/nousresearch', 'nousresearch'),
    ('https://discord.com/invite/6EbMcWJHdb?utm_source=web', '6EbMcWJHdb'),
    ('discord.gg/TypeSafe', 'TypeSafe'), ('  typesafe  ', 'typesafe')])
def test_invites(value, expected):
    assert core.parse_invite(value) == expected

@pytest.mark.parametrize('bad', ['https://evil.test/abc', 'https://discord.gg.evil/abc',
    'https://discord.com@evil.test/invite/abc', 'http://discord.gg/abc',
    'https://discord.gg/abc/extra', 'https://discord.com/invite/%61bc',
    'https://discord.com/channels/abc', '../x', '', 'a', 'ab#fragment', 'a' * 65])
def test_reject_invites(bad):
    with pytest.raises(ValueError):
        core.parse_invite(bad)

def test_first_sample_scores_measured_level_not_history_deltas():
    assert core.movement({'ts': 1, 'online': 200, 'members': 1000, 'voice_channels': 5}, [])['score'] == 10

def test_score_components_and_falling_presence():
    base = {'ts': 100, 'online': 100, 'members': 1000}
    out = core.movement({'ts': 700, 'online': 80, 'members': 1010, 'voice_channels': 5}, [base])
    assert out['score'] == 88.3  # Decrease denominator includes the lost 20.
    assert out['online_delta'] == -20
    assert out['member_delta'] == 10
    assert out['components'] == pytest.approx({'presence': 70 * 20 / 120 / .2, 'members': 20, 'voice': 10})

def test_rolling_median_and_unknown_counts():
    out = core.movement({'ts': 100000, 'online': 110, 'members': None}, [
        {'ts': 1, 'online': 9000}, {'ts': 99000, 'online': 100}, {'ts': 99500, 'online': 100}])
    assert out['score'] == 35
    assert out['baseline_samples'] == 2
    assert out['member_delta'] is None
    assert out['components']['voice'] == 0


def test_zero_baselines_and_score_caps():
    out = core.movement({'ts': 2, 'online': 10000, 'members': 10000, 'voice_channels': 999},
                        [{'ts': 1, 'online': 0, 'members': 0}])
    assert out['score'] == 10  # Zero-usual deltas wait; measured voice still scores.
    assert out['online_delta'] == 10000


def test_transport_parses_discord_retry_after(monkeypatch):
    import io
    import urllib.error
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == 'https://discord.com/api/v10/invites/nousresearch?with_counts=true'
            assert request.get_header('Authorization') is None
            raise urllib.error.HTTPError(request.full_url, 429, 'Rate limited', {},
                                         io.BytesIO(b'{"retry_after": 1234.5, "global": true}'))
    monkeypatch.setattr(core.urllib.request, 'build_opener', lambda *_: Opener())
    with pytest.raises(core.DiscordError) as error:
        core.discord_get('/api/v10/invites/nousresearch?with_counts=true')
    assert error.value.retry_after == 1234.5
    assert error.value.status == 429
