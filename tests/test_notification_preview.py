"""Opt-in message preview for desktop.notifications: parsing, bounds, disclosure gating and
keeping the text away from samples, state, logs and the agent."""
import ast
import inspect
import json
import logging

import pytest

from pulse_rings import desktop_apps, notification_preview as np_, spec
from pulse_rings.authoring import catalog
from pulse_rings.engine import Engine
from pulse_rings.layout import proposal_disclosure
from pulse_rings.sources import desktop_notifications as dn
from pulse_rings.sources.desktop_notifications import (DesktopNotifications, Snapshot,
                                                       WindowsNotificationStore)
from pulse_rings.templates import from_template
from test_desktop_notifications import DISCORD, NOW, Registry, add, ft, make_store

SECRET = 'SECRET-TEXT-123'
LOWER = DISCORD.lower()


def toast(*texts, extra=''):
    lines = ''.join(f'<text>{t}</text>' for t in texts)
    return (f'<toast launch="x"><visual><binding template="ToastGeneric">{lines}{extra}'
            '</binding></visual></toast>').encode()


@pytest.fixture(autouse=True)
def fresh():
    np_.forget()
    yield
    np_.forget()


# ---------------------------------------------------------------- parsing

def test_parses_sender_and_text():
    assert np_.parse_toast(toast('Ada (#general, Server)', 'See you at four')) == ('Ada (#general, Server)', 'See you at four')


def test_one_text_is_the_message_without_a_sender():
    assert np_.parse_toast(toast('Only line')) == (None, 'Only line')


def test_only_first_two_texts_and_no_attribution():
    payload = toast('Ada', 'Hi', 'third', extra='<text placement="attribution">via Discord</text>')
    assert np_.parse_toast(payload) == ('Ada', 'Hi')
    payload = toast(extra='<text placement="attribution">via Discord</text><text>Body</text>')
    assert np_.parse_toast(payload) == (None, 'Body')


def test_text_is_plain_single_line_and_bounded():
    sender, text = np_.parse_toast(toast('A‮B​\x85 name', 'line one\n\n  line\ttwo ' + 'x' * 500))
    assert sender == 'AB name'
    assert text.startswith('line one line two ') and len(text) == np_.TEXT_LIMIT and text.endswith('…')


def test_markup_is_never_interpreted():
    assert np_.parse_toast(toast('&lt;b&gt;Ada&lt;/b&gt;', 'a &amp; b')) == ('<b>Ada</b>', 'a & b')


@pytest.mark.parametrize('payload', [
    b'', b'not xml', b'<toast><visual></visual></toast>', b'<other><visual><binding><text>x</text></binding></visual></other>',
    b'<!DOCTYPE toast [<!ENTITY a "aaaa">]><toast><visual><binding><text>&a;</text></binding></visual></toast>',
    b'<toast><visual><binding><text>' + b'x' * (np_.PAYLOAD_LIMIT + 1) + b'</text></binding></visual></toast>',
    None, 42,
])
def test_unusable_payloads_are_skipped(payload):
    assert np_.parse_toast(payload) is None


def test_bounded_rechecks_reader_output():
    raw = [{'from': 'x' * 400, 'text': 'y\n' * 400, 'ts': True}, 'junk', {'from': None, 'text': None}] + \
          [{'from': 'a', 'text': str(i), 'ts': NOW} for i in range(10)]
    out = np_.bounded(raw)
    assert len(out) == np_.MAX_ITEMS
    assert len(out[0]['from']) == np_.TEXT_LIMIT and len(out[0]['text']) <= np_.TEXT_LIMIT and out[0]['ts'] is None
    assert all(set(item) == {'from', 'text', 'ts'} for item in out)


# ---------------------------------------------------------------- the real store reader

@pytest.fixture
def store(tmp_path):
    path = tmp_path / 'wpndatabase.db'
    db = make_store(path)
    db.execute('ALTER TABLE Notification ADD COLUMN PayloadType TEXT')
    db.commit()
    yield db, path
    db.close()


def put(db, nid, payload, arrival=NOW, expiry=None, kind='toast', payload_type='Xml', handler=149):
    expiry = arrival + 3 * 86400 if expiry is None else expiry
    db.execute('INSERT INTO Notification (Id, HandlerId, Type, Payload, PayloadType, ArrivalTime, ExpiryTime) '
               'VALUES (?,?,?,?,?,?,?)', (nid, handler, kind, payload, payload_type, ft(arrival), ft(expiry)))
    db.commit()


def test_store_reader_lists_waiting_toasts_newest_first(store):
    db, path = store
    put(db, 1, toast('Old', 'first'), arrival=NOW - 600)
    put(db, 2, toast('New', 'second'), arrival=NOW - 60)
    put(db, 3, toast('Gone', 'expired'), arrival=NOW - 300, expiry=NOW - 1)
    put(db, 4, toast('Badge', 'x'), kind='badge')
    put(db, 5, b'raw-bytes', payload_type='Raw')
    put(db, 6, toast('Teams', 'other app'), handler=300)
    items = WindowsNotificationStore(path, Registry()).preview([DISCORD], NOW)
    assert [(i['from'], i['text']) for i in items] == [('New', 'second'), ('Old', 'first')]
    assert items[0]['ts'] == pytest.approx(NOW - 60)


def test_store_reader_caps_items(store):
    db, path = store
    for nid in range(1, 12):
        put(db, nid, toast(f'P{nid}', 'hi'), arrival=NOW - nid)
    assert len(WindowsNotificationStore(path, Registry()).preview([DISCORD], NOW)) == np_.MAX_ITEMS


def test_store_reader_is_read_only_and_fails_closed(store, tmp_path):
    db, path = store
    put(db, 1, toast('Ada', 'hi'))
    before = path.read_bytes()
    WindowsNotificationStore(path, Registry()).preview([DISCORD], NOW)
    assert path.read_bytes() == before
    old = tmp_path / 'old.db'
    make_store(old).close()  # no PayloadType column: an unknown layout shows no preview
    assert WindowsNotificationStore(old, Registry()).preview([DISCORD], NOW) == []
    assert WindowsNotificationStore(tmp_path / 'missing.db', Registry()).preview([DISCORD], NOW) == []


def test_polling_never_reads_text_even_with_preview(store):
    db, path = store
    put(db, 1, toast('Ada', SECRET))
    add(db, 2, secret=SECRET)
    adapter = DesktopNotifications(reader=WindowsNotificationStore(path, Registry()))
    defn = spec.normalize({'pulse': 1, 'title': 'p', 'source': {'kind': 'desktop.notifications',
                                                                'params': {'apps': ['discord'], 'preview': True}}})
    result = adapter.poll(defn, None, {}, now=NOW, net=None)
    assert SECRET not in json.dumps([result.sample, result.state, result.metadata])


def test_only_the_preview_module_selects_payloads():
    source = inspect.getsource(np_)
    queries = [ast.unparse(node) for node in ast.walk(ast.parse(source))
               if isinstance(node, (ast.Constant, ast.JoinedStr)) and 'SELECT' in ast.unparse(node)]
    assert queries and all('NotificationData' not in q and '*' not in q and 'Tag' not in q for q in queries)
    # The adapter's own poll SQL never names Payload (test_adapter_sql_never_selects_content);
    # this module's query is the only one that does, and only for the preview.
    assert any('Payload' in q for q in queries)


# ---------------------------------------------------------------- engine: pane only

class Reader:
    def __init__(self, items=None, fail=False):
        self.items = items if items is not None else [{'from': 'Ada', 'text': SECRET, 'ts': NOW - 60}]
        self.fail = fail
        self.calls = 0

    def read(self, aumids, types, now):
        return Snapshot(registered={LOWER}, rows=[(LOWER, 1, 'toast', NOW - 60, None)],
                        last_added={LOWER: NOW - 60}, current_id=1)

    def preview(self, aumids, now):
        self.calls += 1
        if self.fail:
            raise RuntimeError(SECRET)
        return self.items


def engine_with(tmp_path, reader):
    return Engine(tmp_path, clock=lambda: NOW, jitter=lambda: 0,
                  adapters={'desktop.notifications@1': DesktopNotifications(reader=reader)})


def watch(engine, pulse_id='pings', **params):
    engine.activate({'pulse': 1, 'id': pulse_id, 'title': 'Discord pings',
                     'source': {'kind': 'desktop.notifications', 'params': params or {'apps': ['discord']}}})
    engine.poll_one_due(previews=False)


def row(status, pulse_id='pings'):
    return next(p for p in status['pulses'] if p['id'] == pulse_id)


def test_pane_status_carries_items_only_with_preview(tmp_path):
    reader = Reader()
    e = engine_with(tmp_path, reader)
    watch(e, 'on', apps=['discord'], preview=True)
    watch(e, 'off', apps=['discord'])
    status = e.status(poll=False)
    assert row(status, 'on')['inbox']['items'] == [{'from': 'Ada', 'text': SECRET, 'ts': NOW - 60}]
    assert row(status, 'on')['notifications']['preview'] is True
    assert 'items' not in row(status, 'off')['inbox'] and 'preview' not in row(status, 'off')['notifications']
    assert reader.calls == 1  # the counts-only pulse never asks for text


def test_agent_status_and_command_output_never_carry_text(tmp_path):
    e = engine_with(tmp_path, Reader())
    watch(e, apps=['discord'], preview=True)
    compact = e.status(poll=False, include_icons=False, compact=True)
    assert SECRET not in json.dumps(compact) and 'items' not in row(compact)['inbox']
    assert SECRET not in json.dumps(e.status(poll=False, compact=True, text=True))  # compact always wins
    assert SECRET not in json.dumps(e.status(poll=False, text=False))


def test_text_never_reaches_the_store_or_logs(tmp_path, caplog):
    e = engine_with(tmp_path, Reader())
    watch(e, apps=['discord'], preview=True)
    with caplog.at_level(logging.DEBUG):
        e.status(poll=False)
    on_disk = b''.join(p.read_bytes() for p in tmp_path.rglob('*') if p.is_file())
    assert SECRET.encode() not in on_disk
    assert SECRET not in caplog.text


def test_reader_failure_shows_no_preview_and_logs_nothing(tmp_path, caplog):
    e = engine_with(tmp_path, Reader(fail=True))
    watch(e, apps=['discord'], preview=True)
    with caplog.at_level(logging.DEBUG):
        status = e.status(poll=False)
    assert row(status)['inbox']['items'] == [] and row(status)['state'] != 'error'
    assert SECRET not in caplog.text and SECRET not in json.dumps(status)


def test_nothing_waiting_means_no_read(tmp_path):
    class Quiet(Reader):
        def read(self, aumids, types, now):
            return Snapshot(registered={LOWER}, rows=[], last_added={}, current_id=1)
    reader = Quiet()
    e = engine_with(tmp_path, reader)
    watch(e, apps=['discord'], preview=True)
    assert row(e.status(poll=False))['inbox']['items'] == [] and reader.calls == 0


def test_cached_briefly_per_app_set(tmp_path):
    reader = Reader()
    e = engine_with(tmp_path, reader)
    watch(e, apps=['discord'], preview=True)
    e.status(poll=False)
    e.status(poll=False)
    assert reader.calls == 1
    np_.forget()
    e.status(poll=False)
    assert reader.calls == 2


def test_cached_text_expires_even_if_nothing_asks_again(tmp_path, monkeypatch):
    # The pane may close or previews may be turned off right after a status read: no later
    # lookup would ever sweep the cache, so the text must leave memory on its own.
    import time
    monkeypatch.setattr(np_, 'CACHE_SECONDS', 0.05)
    e = engine_with(tmp_path, Reader())
    watch(e, apps=['discord'], preview=True)
    assert row(e.status(poll=False))['inbox']['items']
    assert np_._cache
    deadline = time.monotonic() + 2
    while np_._cache and time.monotonic() < deadline:
        time.sleep(0.02)
    assert np_._cache == {}


def test_multi_feed_main_feed_preview(tmp_path):
    e = engine_with(tmp_path, Reader())
    e.activate({'pulse': 1, 'id': 'designed', 'title': 'Discord · layout',
                'feeds': {'main': {'kind': 'desktop.notifications', 'params': {'apps': ['discord'], 'preview': True}, 'every': '1m'}},
                'display': [{'type': 'stat', 'value': 'main.waiting'}]})
    e.poll_one_due(previews=False)
    pane = row(e.status(poll=False), 'designed')
    assert pane['inbox']['items'][0]['text'] == SECRET and pane['notifications']['preview'] is True
    assert SECRET not in json.dumps(e.status(poll=False, compact=True))


def test_draft_preview_rows_never_carry_text(tmp_path):
    e = engine_with(tmp_path, Reader())
    defn = spec.normalize({'pulse': 1, 'title': 'p', 'source': {'kind': 'desktop.notifications',
                                                                'params': {'apps': ['discord'], 'preview': True}}})
    shown = e.preview(defn, {'ts': NOW, 'metrics': {'waiting': 1}}, spec.budget(defn))
    assert SECRET not in json.dumps(shown) and shown['notifications']['preview'] is True


def test_only_the_real_windows_store_or_an_injected_reader():
    assert DesktopNotifications(platform='linux').preview([DISCORD], NOW) == []

    class CountsOnly:
        def read(self, aumids, types, now):
            raise AssertionError
    assert DesktopNotifications(reader=CountsOnly()).preview([DISCORD], NOW) == []


# ---------------------------------------------------------------- disclosure and approval

def test_preview_is_off_unless_exactly_true():
    for params in ({'apps': ['discord']}, {'apps': ['discord'], 'preview': False}):
        assert not np_.enabled(params)
        assert desktop_apps.target(params) == 'this PC · discord'
    assert np_.enabled({'apps': ['discord'], 'preview': True})
    with pytest.raises(spec.ValidationError):
        spec.normalize({'pulse': 1, 'title': 'p', 'source': {'kind': 'desktop.notifications',
                                                             'params': {'apps': ['discord'], 'preview': 'yes'}}})


def test_preview_changes_the_approval_target_and_disclosure():
    def disclose(params):
        return proposal_disclosure(spec.normalize({'pulse': 1, 'title': 'p', 'source': {
            'kind': 'desktop.notifications', 'params': params}}))
    off, on = disclose({'apps': ['discord']}), disclose({'apps': ['discord'], 'preview': True})
    assert off['feeds'][0]['target'] == 'this PC · discord'
    assert on['feeds'][0]['target'] == 'this PC · discord · message previews'
    assert 'Message previews are on' in on['summary'] and 'never saved, logged or sent to Hermes' in on['summary']
    assert 'Message previews' not in off['summary']
    assert on['budget']['hosts'] == [] and on['budget']['req_per_hour'] == 0


def test_row_disclosure_switches_with_preview():
    assert dn.disclosure({'apps': ['discord']}) == dn.DISCLOSURE
    on = dn.disclosure({'apps': ['discord'], 'preview': True})
    assert on['preview'] is True and 'never message text' not in on['details']
    assert 'never saved, logged or sent to Hermes' in on['details']


def test_builder_checkbox_is_off_by_default():
    base = {'template': 'notifications', 'values': {'app': 'discord'}}
    assert 'preview' not in from_template(**base)['feeds']['main']['params']
    on = from_template('notifications', {'app': 'discord', 'preview': True})
    assert on['ok'] and on['feeds']['main']['params']['preview'] is True and on['suggested_title'] == 'Discord · notifications'


def test_catalog_offers_the_param():
    assert 'preview' in json.dumps(catalog())
