"""Clicking a notifications pulse opens the one curated app it watches (#109)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pulse_rings import app_open, desktop_apps
from pulse_rings.engine import Engine
from pulse_rings.sources.desktop_notifications import DesktopNotifications, Snapshot

NOW = 1_794_189_600.0
DISCORD = 'com.squirrel.discord.discord'
AUMID = 'com.squirrel.Discord.Discord'


class Reader:
    def read(self, aumids, types, now):
        return Snapshot(registered={DISCORD}, rows=[(DISCORD, 1, 'toast', NOW - 600, None)],
                        last_added={DISCORD: NOW - 600}, current_id=40)


def source(**params):
    return {'kind': 'desktop.notifications', 'params': params}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(app_open, '_recent', {})


@pytest.fixture
def engine(tmp_path):
    adapter = DesktopNotifications(reader=Reader())
    adapter.can_open = True  # stands in for the real Windows store, which no test reads
    return Engine(tmp_path, clock=lambda: NOW, jitter=lambda: 0, adapters={'desktop.notifications@1': adapter})


def watch(engine, pulse_id='pings', **params):
    engine.activate({'pulse': 1, 'id': pulse_id, 'title': 'Discord pings', 'source': source(**(params or {'apps': ['discord']}))})
    engine.poll_one_due(previews=False)
    return next(p for p in engine.status(poll=False)['pulses'] if p['id'] == pulse_id)


def test_only_the_real_windows_store_offers_to_open():
    assert DesktopNotifications(platform='win32').can_open is True
    assert DesktopNotifications(platform='linux').can_open is False
    assert DesktopNotifications(reader=Reader(), platform='win32').can_open is False


def test_one_curated_app_seen_on_this_pc_is_the_target():
    assert desktop_apps.launch_target({'apps': ['discord']}, [DISCORD]) == ('Discord', AUMID)
    assert desktop_apps.launch_target({'apps': ['discord']}, []) is None            # never seen here
    assert desktop_apps.launch_target({'apps': ['discord', 'teams']}, [DISCORD]) is None  # a click would be a guess
    assert desktop_apps.launch_target({'apps': ['discord'], 'app_ids': ['x.y']}, [DISCORD]) is None
    assert desktop_apps.launch_target({'app_ids': [AUMID]}, [DISCORD]) is None        # exact ids are never opened
    assert desktop_apps.launch_target({'apps': ['phone_discord']},
                                      [desktop_apps.APPS['phone_discord'][2][0].lower()]) is None


def test_every_launchable_alias_is_curated():
    assert desktop_apps.LAUNCHABLE <= set(desktop_apps.APPS)


def test_status_names_the_app_a_click_opens(engine):
    assert watch(engine)['open_app'] == {'name': 'Discord'}
    assert engine.status(poll=False, compact=True)['pulses'][0]['open_app'] == {'name': 'Discord'}


def test_a_designed_pulse_names_it_too(engine):
    engine.activate({'pulse': 1, 'id': 'designed', 'title': 'Discord pings',
                     'feeds': {'main': {**source(apps=['discord']), 'every': '1m'}},
                     'display': [{'type': 'stat', 'value': 'main.waiting', 'label': 'In Action Center'}]})
    engine.poll_one_due(previews=False)
    assert engine.status(poll=False)['pulses'][0]['open_app'] == {'name': 'Discord'}
    opened = []
    assert app_open.open_for_pulse(engine, 'designed', starter=opened.append) == {'opened': 'Discord'}
    assert opened == ['shell:AppsFolder\\' + AUMID]


def test_status_is_unchanged_without_the_capability(tmp_path):
    plain = Engine(tmp_path, clock=lambda: NOW, jitter=lambda: 0,
                   adapters={'desktop.notifications@1': DesktopNotifications(reader=Reader())})
    row = watch(plain)
    assert row['inbox']['waiting'] == 1 and 'open_app' not in row
    with pytest.raises(app_open.OpenError) as refused:
        app_open.open_for_pulse(plain, 'pings', starter=lambda _: pytest.fail('opened'))
    assert refused.value.status == 409


def test_opening_hands_windows_the_exact_curated_identity(engine):
    watch(engine)
    opened = []
    assert app_open.open_for_pulse(engine, 'pings', starter=opened.append) == {'opened': 'Discord'}
    assert opened == ['shell:AppsFolder\\' + AUMID]


def test_a_double_click_opens_once(engine):
    watch(engine)
    opened = []
    app_open.open_for_pulse(engine, 'pings', starter=opened.append)
    app_open.open_for_pulse(engine, 'pings', starter=opened.append)
    assert len(opened) == 1


def test_nothing_else_can_be_opened(engine):
    with pytest.raises(app_open.OpenError) as unknown:
        app_open.open_for_pulse(engine, 'nope', starter=lambda _: pytest.fail('opened'))
    assert unknown.value.status == 404
    with pytest.raises(app_open.OpenError) as uncurated:
        app_open.launch('C:\\Windows\\System32\\cmd.exe', starter=lambda _: pytest.fail('opened'))
    assert uncurated.value.status == 403


def test_a_windows_refusal_is_a_plain_error_and_can_be_retried(engine):
    watch(engine)

    def refuse(_):
        raise OSError('secret path detail')
    with pytest.raises(app_open.OpenError) as failed:
        app_open.open_for_pulse(engine, 'pings', starter=refuse)
    assert failed.value.status == 502 and 'secret' not in str(failed.value)
    opened = []
    app_open.open_for_pulse(engine, 'pings', starter=opened.append)
    assert len(opened) == 1


def test_route_needs_confirmation_and_takes_no_target(engine, monkeypatch):
    import dashboard.plugin_api as api
    watch(engine)
    opened = []
    monkeypatch.setattr(app_open.os, 'startfile', opened.append, raising=False)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_arrangement_pulse] = lambda: engine
    with TestClient(app) as c:
        assert c.post('/pulses/pings/open-app', json={}).status_code == 422
        assert c.post('/pulses/pings/open-app', json={'confirm': False}).status_code == 400
        assert c.post('/pulses/pings/open-app', json={'confirm': True, 'app': 'cmd.exe'}).status_code == 422
        assert opened == []
        reply = c.post('/pulses/pings/open-app', json={'confirm': True})
        assert reply.status_code == 200 and reply.json() == {'opened': 'Discord'}
        assert reply.headers['cache-control'] == 'no-store'
        assert opened == ['shell:AppsFolder\\' + AUMID]
        assert c.post('/pulses/missing/open-app', json={'confirm': True}).status_code == 404
