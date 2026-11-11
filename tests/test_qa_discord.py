"""Discord QA: public counts, independent widget lifecycle, display and disclosure."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from pulse_rings.sources.discord import DiscordSource, DiscordError, normalize_invite, preset
from pulse_rings.sources.base import SourceError, Deferred
from pulse_rings.engine import compute_ring, compute_capsule
from pulse_rings.spec import normalize
from pulse_rings.display import compute_display
from pulse_rings.layout import layout_check
from pulse_rings.layout_presets import layouts

RAW = json.loads((Path(__file__).parent / 'fixtures/nousresearch.json').read_text())
GID = RAW['guild']['id']
CHANNEL = '123456789012345678'
DEFINITION = preset('nousresearch', pulse_id='qa-discord', title='Discord QA')
SAMPLE = {'ts': 1000, 'metrics': {'online': 16082, 'members': 149800}, 'metadata': {'id': GID}}


class Net:
    def call(self, host, fn):
        assert host == 'discord.com'
        return fn()


@pytest.mark.parametrize('value', [0, 1, 16082, 10**15, None, -1, True, False, 1.2, '12', {}, []])
def test_invite_counts_do_not_coerce_unknown(value):
    raw = deepcopy(RAW)
    raw['approximate_presence_count'] = value
    raw['approximate_member_count'] = value
    expected = value if type(value) is int and value >= 0 else None
    result = normalize_invite(raw)
    assert result['online'] == expected
    assert result['members'] == expected


@pytest.mark.parametrize('widget', [
    {'members': [None], 'channels': []},
    {'members': [], 'channels': [None]},
    {'members': [{'channel_id': {}}], 'channels': []},
    {'members': [{'channel_id': True}], 'channels': []},
    {'members': [{'channel_id': 'not-an-id'}], 'channels': []},
    {'id': '987654321098765432', 'members': [], 'channels': []},
])
def test_partial_or_wrong_guild_widget_never_becomes_measured_zero(widget):
    source = DiscordSource(fetch=lambda _: widget)
    result = source.poll(DEFINITION, SAMPLE, {'invite_due': 1600}, now=1001, net=Net())
    assert result.sample is None
    assert result.state['widget_state'] == 'backoff'
    assert source.current(SAMPLE, result.state, now=1001)['metrics']['voice_channels'] is None


@pytest.mark.parametrize('status,retry_after,expected,delay', [(403, 0, 'unavailable', 86400), (404, 0, 'unavailable', 86400), (429, 3600, 'backoff', 3600), (500, 0, 'backoff', 900), (0, 0, 'backoff', 900)])
def test_widget_error_does_not_refresh_primary_or_fake_zero(status, retry_after, expected, delay):
    def fail(_):
        raise SourceError('public widget failed', status, retry_after)
    source = DiscordSource(fetch=fail)
    result = source.poll(DEFINITION, SAMPLE, {'invite_due': 1600}, now=1001, net=Net())
    assert result.sample is None
    assert result.state['widget_state'] == expected
    assert result.state['widget_due'] == 1001 + delay
    assert source.current(SAMPLE, result.state, now=1001)['metrics']['voice_channels'] is None
    assert SAMPLE['metrics']['online'] == 16082


def test_widget_counts_distinct_active_channels_and_retains_no_member_data():
    widget = {'id': GID, 'presence_count': 400, 'channels': [{'id': CHANNEL, 'name': '声 🎙'}],
              'members': [{'channel_id': CHANNEL, 'username': 'never persist me'}, {'channel_id': CHANNEL}, {'channel_id': None}, {}]}
    source = DiscordSource(fetch=lambda _: widget)
    result = source.poll(DEFINITION, SAMPLE, {'invite_due': 1600}, now=1001, net=Net())
    assert result.sample is None
    assert result.state['widget']['voice_channels'] == 1
    assert result.state['widget']['channels'] == ['声 🎙']
    assert 'never persist me' not in json.dumps(result.state)
    current = source.current(SAMPLE, result.state, now=1001)
    assert current['metrics'] == {'online': 16082, 'members': 149800, 'voice_channels': 1}
    assert source.current(SAMPLE, result.state, now=2802)['metrics']['voice_channels'] is None


def test_genuine_empty_widget_is_measured_zero():
    source = DiscordSource(fetch=lambda _: {'channels': [], 'members': []})
    result = source.poll(DEFINITION, SAMPLE, {'invite_due': 1600}, now=1001, net=Net())
    assert source.current(SAMPLE, result.state, now=1001)['metrics']['voice_channels'] == 0


def test_reference_baseline_ratio_and_weighted_score_are_not_member_share():
    current = {'ts': 1000, 'metrics': {'online': 9700, 'members': 100000, 'voice_channels': None}}
    history = [{'ts': 400, 'metrics': {'online': 10000, 'members': 100000}}]
    ring = compute_ring(DEFINITION, current, history)
    capsule = compute_capsule(DEFINITION, current, ring)
    assert ring['score'] == 10.2  # 70 * 300 / (10000 + 300) / .2; unknown widget contributes nothing.
    assert capsule['caption'] == '97% of usual'
    assert capsule['fill'] == 48.5  # Tick at 50%, not 100% membership utilization.
    assert compute_capsule(DEFINITION, {'ts': 1, 'metrics': {'online': 0}}, compute_ring(DEFINITION, {'ts': 1, 'metrics': {'online': 0}}, []))['fill'] is None


@pytest.mark.parametrize('kind', ['score', 'rings', 'bar', 'bars', 'stat', 'spark'])
def test_every_discord_block_preserves_zero_missing_and_formatted_counts(kind):
    block = {'type': kind, 'label': 'Online'}
    if kind == 'score':
        block['components'] = [{'metric': 'online', 'type': 'level', 'weight': 100, 'full_at': 20000}]
    elif kind in ('rings', 'bars'):
        block[kind] = [{'value': 'online', 'label': 'Online', 'max': 'members'}]
        if kind == 'bars':
            block['scale'] = 'independent'
            block['bars'].append({'value': 'members', 'label': 'Members', 'max': 200000})
    else:
        block['value'] = 'online'
        if kind == 'bar':
            block['max'] = 'members'
    definition = normalize({'pulse': 1, 'title': '声 🎙 ' + 'Long server ' * 4, 'source': {'kind': 'discord.invite', 'params': {'invite': 'nousresearch'}}, 'display': [block]})
    for value in (None, 0, 1, 16082, 10**15):
        feed = {'current': {'ts': 4000, 'metrics': {'online': value, 'members': 200000}}, 'history': []}
        row = compute_display(definition, {'main': feed})[0]
        assert 'NaN' not in json.dumps(row)
        if kind in ('bar', 'bars', 'rings'):
            item = row['items'][0]
            assert item['unknown'] == (value is None)
            assert item['value_text'] == (None if value is None else f'{value:,}')
        elif kind == 'stat':
            assert row['unknown'] == (value is None)
            assert row['value_text'] == (None if value is None else f'{value:,}')


@pytest.mark.parametrize('status', [404, 429, 500, 0])
def test_primary_failure_preserves_previous_counts_and_state(status):
    def fail(_):
        raise SourceError('invite request failed', status, 60)
    state = {'invite_due': 999, 'widget_due': 800, 'widget_state': 'available'}
    original = deepcopy(state)
    with pytest.raises(SourceError) as error:
        DiscordSource(fetch=fail).poll(DEFINITION, SAMPLE, state, now=1001, net=Net())
    assert error.value.status == status
    assert state == original
    assert SAMPLE['metrics'] == {'online': 16082, 'members': 149800}


def test_voice_false_only_requests_invite_and_does_not_allocate_widget_budget():
    definition = deepcopy(DEFINITION)
    definition['source']['params']['voice'] = False
    paths = []
    def fetch(path):
        paths.append(path)
        return RAW
    result = DiscordSource(fetch=fetch).poll(definition, SAMPLE, {'invite_due': 1600}, now=1001, net=Net())
    assert len(paths) == 1 and '/invites/' in paths[0]
    assert result.next_due == 1601
    assert layout_check(normalize(definition))['budget']['req_per_hour'] == 6


def test_sanitized_current_public_fixture_extracts_exact_aggregate_values():
    fixture = json.loads((Path(__file__).parent / 'fixtures/discord-qa-public.json').read_text())
    for raw in fixture['invites']:
        result = normalize_invite(raw)
        assert result['online'] == raw['approximate_presence_count']
        assert result['members'] == raw['approximate_member_count']
        assert result['name'] == raw['guild']['name']


def test_recommended_discord_layouts_and_voice_budget():
    feeds = {'main': {'kind': 'discord.invite', 'params': {'invite': 'nousresearch', 'voice': True}, 'every': '10m'}}
    choices = layouts(feeds, ['main.online', 'main.members', 'main.voice_channels'])
    assert len(choices) >= 3
    for choice in choices:
        checked = layout_check(choice['definition'])
        assert checked['ok']
        assert checked['budget']['req_per_hour'] == 10
        assert set(checked['budget']['hosts']) == {'discord.com', 'cdn.discordapp.com'}
