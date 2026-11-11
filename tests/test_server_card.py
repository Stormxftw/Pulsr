"""The Discord server card: people in voice over the day and member growth over the day. Display only."""
import json
from pathlib import Path

import pytest

from pulse_rings import server
from pulse_rings.sources.discord import DiscordSource, VOICE_LOG_KEEP, preset

RAW = json.loads((Path(__file__).parent / 'fixtures/nousresearch.json').read_text())
GID = RAW['guild']['id']
CHANNEL, OTHER = '123456789012345678', '223456789012345678'
DEFINITION = preset('nousresearch', pulse_id='qa-server', title='Server QA')
SAMPLE = {'ts': 1000, 'metrics': {'online': 16082, 'members': 149800}, 'metadata': {'id': GID}}
HOUR, DAY, NOW = 3600, 86400, 10 * 86400


class Net:
    def call(self, host, fn):
        return fn()


def widget(in_voice, listed=None, channels=(CHANNEL, OTHER)):
    members = [{'username': f'person{i}', 'channel_id': channels[i % len(channels)]} for i in range(in_voice)]
    members += [{'username': f'idle{i}'} for i in range((listed or in_voice + 2) - in_voice)]
    return {'id': GID, 'channels': [{'id': c, 'name': 'Voice'} for c in channels], 'members': members, 'presence_count': 9}


def poll_widget(document, state, now):
    return DiscordSource(fetch=lambda _: document).poll(
        DEFINITION, SAMPLE, {**state, 'invite_due': now + 600, 'widget_due': 0}, now=now, net=Net()).state


# The voice log kept in source state

def test_each_widget_check_adds_one_counts_only_entry():
    state = poll_widget(widget(3), {}, 1000)
    state = poll_widget(widget(5, channels=(CHANNEL,)), state, 1900)
    assert state['voice_log'] == [[1000, 3, 2, 5], [1900, 5, 1, 7]]
    assert 'person' not in json.dumps(state['voice_log'])


def test_the_voice_log_keeps_about_a_day_and_is_bounded():
    state = {}
    for step in range(200):
        state = poll_widget(widget(step % 7), state, 1000 + step * 900)
    log = state['voice_log']
    assert len(log) <= VOICE_LOG_KEEP and log[-1][0] == 1000 + 199 * 900
    assert log[0][0] >= log[-1][0] - 26 * HOUR


def test_a_failed_widget_check_adds_nothing_and_keeps_the_log():
    state = poll_widget(widget(3), {}, 1000)
    state = poll_widget({'channels': 'broken'}, state, 1900)
    assert state['voice_log'] == [[1000, 3, 2, 5]]


# The read model

def members(points):
    return [{'ts': ts, 'value': value} for ts, value in points]


def state_with(log, status='available'):
    last = log[-1] if log else None
    out = {'widget_state': status, 'voice_log': log}
    if last:
        out['widget'] = {'ts': last[0], 'voice_users': last[1], 'voice_channels': last[2], 'listed': last[3], 'channels': []}
    return out


def test_member_growth_is_the_net_change_since_the_start_of_the_day():
    rows = members([(NOW - DAY + i * 1800, 1000 + i * 2) for i in range(49)])
    card = server.summarize(DEFINITION, {'ts': NOW, 'metrics': {'online': 50, 'members': 1100}}, state_with([]), rows, now=NOW)
    growth = card['members']
    assert growth['value'] == 1100 and growth['delta'] == 100 and growth['span_seconds'] == DAY
    assert growth['points'][0] == {'ts': NOW - DAY, 'value': 0} and growth['points'][-1] == {'ts': NOW, 'value': 100}
    assert all(b['value'] >= a['value'] for a, b in zip(growth['points'], growth['points'][1:]))


def test_member_growth_can_be_negative_and_needs_two_points():
    rows = members([(NOW - 6 * HOUR, 1000), (NOW - 3 * HOUR, 990), (NOW - 600, 980)])
    growth = server.summarize(DEFINITION, {'ts': NOW, 'metrics': {'members': 975}}, state_with([]), rows, now=NOW)['members']
    assert growth['delta'] == -25 and growth['span_seconds'] == 6 * HOUR and growth['points'][-1]['value'] == -25
    alone = server.summarize(DEFINITION, {'ts': NOW, 'metrics': {'members': 975}}, state_with([]), members([(NOW, 975)]), now=NOW)['members']
    assert alone['value'] == 975 and alone['delta'] is None and alone['points'] == []


def test_member_growth_ignores_samples_older_than_a_day():
    rows = members([(NOW - 3 * DAY, 10), (NOW - DAY + 60, 1000), (NOW - 60, 1010)])
    growth = server.summarize(DEFINITION, {'ts': NOW, 'metrics': {'members': 1010}}, state_with([]), rows, now=NOW)['members']
    assert growth['delta'] == 10 and growth['points'][0]['value'] == 0


def test_voice_series_peak_and_current_count():
    log = [[NOW - 5 * HOUR, 2, 1, 40], [NOW - 3 * HOUR, 9, 3, 40], [NOW - HOUR, 4, 2, 40], [NOW - 300, 6, 2, 40]]
    voice = server.summarize(DEFINITION, {'ts': NOW, 'metrics': {}}, state_with(log), [], now=NOW)['voice']
    assert voice['state'] == 'available' and voice['users'] == 6 and voice['channels'] == 2 and voice['capped'] is False
    assert voice['points'] == [{'ts': ts, 'value': users} for ts, users, _, _ in log]
    assert voice['peak'] == {'ts': NOW - 3 * HOUR, 'value': 9}


def test_voice_is_a_floor_when_any_check_hit_the_member_list_cap():
    log = [[NOW - 2 * HOUR, 3, 1, 100], [NOW - 300, 4, 1, 60]]
    voice = server.summarize(DEFINITION, {'ts': NOW, 'metrics': {}}, state_with(log), [], now=NOW)['voice']
    assert voice['capped'] is False and voice['floor'] is True      # the current count is exact; the day's line is not


def test_voice_not_public_and_not_checked_are_said_plainly():
    off = server.summarize(DEFINITION, {'ts': NOW, 'metrics': {}}, {'widget_state': 'unavailable'}, [], now=NOW)['voice']
    assert off == {'state': 'unavailable', 'users': None, 'channels': None, 'capped': False, 'floor': False, 'points': [], 'peak': None}
    waiting = server.summarize(DEFINITION, {'ts': NOW, 'metrics': {}}, {'widget_state': 'unchecked'}, [], now=NOW)['voice']
    assert waiting['state'] == 'pending' and waiting['points'] == []


def test_voice_log_entries_older_than_a_day_or_malformed_are_left_out():
    log = [[NOW - 2 * DAY, 50, 5, 60], ['bad'], [NOW - HOUR, True, 1, 5], [NOW - 600, 3, 1, 5]]
    voice = server.summarize(DEFINITION, {'ts': NOW, 'metrics': {}}, state_with(log), [], now=NOW)['voice']
    assert voice['points'] == [{'ts': NOW - 600, 'value': 3}]


def test_a_pulse_that_does_not_watch_voice_has_no_voice_part():
    quiet = json.loads(json.dumps(DEFINITION))
    quiet['source']['params']['voice'] = False
    assert server.summarize(quiet, {'ts': NOW, 'metrics': {'members': 5}}, {}, [], now=NOW)['voice'] is None


# Through the engine

def activated(tmp_path, definition=DEFINITION):
    from pulse_rings.engine import Engine
    engine = Engine(tmp_path, clock=lambda: NOW)
    engine.activate(definition)
    return engine


def fill(engine, pulse_id, state):
    with engine.store.transaction() as db:
        for i in range(97):
            ts = NOW - DAY + i * 900
            engine.store.insert_sample(db, pulse_id, {'ts': ts, 'metrics': {'online': 100 + i, 'members': 5000 + i}})
        db.execute('UPDATE pulses SET last_ok_ts=?, source_state=?', (NOW, json.dumps(state)))


def test_status_carries_the_server_card_and_the_agent_view_drops_it(tmp_path):
    engine = activated(tmp_path)
    fill(engine, DEFINITION['id'], state_with([[NOW - HOUR, 2, 1, 9], [NOW - 300, 5, 2, 9]]))
    row = engine.status()['pulses'][0]
    assert row['server']['members']['delta'] == 96 and row['server']['members']['value'] == 5096
    assert row['server']['voice']['users'] == 5 and len(row['server']['voice']['points']) == 2
    # Display only: the ring scores exactly as before.
    assert row['ring']['components'][0]['baseline_mode'] == 'median'
    compact = engine.status(compact=True, include_icons=False)['pulses'][0]
    assert 'server' not in compact and compact['voice']['users'] == 5


def test_status_has_no_server_card_before_the_first_sample(tmp_path):
    assert activated(tmp_path).status()['pulses'][0].get('server') is None


def test_a_pulse_with_its_own_display_blocks_has_no_server_card(tmp_path):
    designed = {'pulse': 1, 'id': 'qa-designed', 'title': 'Designed',
                'feeds': {'main': {**DEFINITION['source'], 'every': '10m'}},
                'display': [{'type': 'stat', 'value': 'main.online', 'label': 'Online now'}]}
    engine = activated(tmp_path, designed)
    fill(engine, 'qa-designed', state_with([[NOW - 300, 5, 2, 9]]))
    row = engine.status()['pulses'][0]
    assert row.get('server') is None and row['display']
