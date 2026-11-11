"""New-posts pulses: reading RSS, Atom and JSON feeds, and the summary the cell is drawn from."""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json

import pytest

from pulse_rings import posts
from pulse_rings.engine import Engine
from pulse_rings.layout import proposal_disclosure
from pulse_rings.spec import ValidationError, budget, normalize
from pulse_rings.templates import from_template
from pulse_rings.sources import http_json
from pulse_rings.sources.base import Deferred, SourceError
from pulse_rings.sources.web_feed import WebFeedSource

NOW = 1_794_189_600.0
HOUR, DAY = 3600, 86400
URL = 'https://example.org/feed.xml'



def when(ago, zone=0):
    return datetime.fromtimestamp(NOW - ago, timezone(timedelta(hours=zone)))


def rfc(ago, zone=0):
    return format_datetime(when(ago, zone))


def iso(ago, zone=0):
    return when(ago, zone).isoformat()


RSS = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Example &amp; Co. blog</title>
  <link>https://example.org/</link>
  <item><title>Third post</title><link>https://example.org/3</link>
    <pubDate>{rfc(3 * HOUR)}</pubDate></item>
  <item><title><![CDATA[Second <b>post</b> &amp; more]]></title><link>https://example.org/2</link>
    <pubDate>{rfc(23 * HOUR, zone=1)}</pubDate></item>
  <item><title>First post</title><link>http://example.org/1</link>
    <pubDate>{rfc(6 * DAY)}</pubDate></item>
</channel></rss>""".encode()

ATOM = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Releases</title>
  <entry><title type="html">v2.0 &lt;em&gt;stable&lt;/em&gt;</title>
    <link rel="alternate" type="text/html" href="https://example.org/releases/v2.0"/>
    <updated>{iso(1800).replace('+00:00', 'Z')}</updated></entry>
  <entry><title>v1.9</title>
    <link rel="self" href="https://example.org/api/v1.9"/>
    <link href="https://example.org/releases/v1.9"/>
    <published>{iso(7 * DAY)}</published><updated>{iso(HOUR)}</updated></entry>
</feed>""".encode()


def definition(url=URL):
    return {'source': {'kind': 'web.feed', 'params': {'url': url}}}


class Net:
    def __init__(self):
        self.hosts = []

    def call(self, host, callback):
        self.hosts.append(host)
        return callback()


def serve(monkeypatch, raw, headers=None):
    seen = []

    def fake(url, host, target, **kw):
        seen.append({'url': url, 'host': host, **kw})
        return raw, headers or {'content-type': 'application/rss+xml'}
    monkeypatch.setattr(http_json, '_fetch', fake)
    return seen


def poll(monkeypatch, raw, now=NOW, state=None):
    serve(monkeypatch, raw)
    return WebFeedSource().poll(definition(), None, state or {}, now=now, net=Net())


# Reading feeds

def test_rss_titles_dates_and_links():
    feed = posts.parse(RSS)
    assert feed['title'] == 'Example & Co. blog' and feed['total'] == 3
    assert [p['title'] for p in feed['items']] == ['Third post', 'Second post & more', 'First post']
    assert feed['items'][0]['ts'] == NOW - 3 * HOUR
    assert feed['items'][1]['ts'] == NOW - 23 * HOUR    # the +0100 offset is honoured
    assert feed['items'][0]['link'] == 'https://example.org/3'
    assert feed['items'][2]['link'] is None             # http links are never offered


def test_atom_prefers_the_published_date_and_the_page_link():
    feed = posts.parse(ATOM)
    assert feed['title'] == 'Releases'
    assert [p['title'] for p in feed['items']] == ['v2.0 stable', 'v1.9']
    assert feed['items'][0]['ts'] == NOW - 30 * 60
    assert feed['items'][1]['ts'] == NOW - 7 * DAY      # published, not the later updated
    assert feed['items'][1]['link'] == 'https://example.org/releases/v1.9'


def test_json_feed():
    raw = json.dumps({'version': 'https://jsonfeed.org/version/1.1', 'title': 'Notes', 'items': [
        {'id': '2', 'title': 'Newer', 'url': 'https://example.org/n/2', 'date_published': iso(2 * HOUR)},
        {'id': '1', 'content_text': 'no title', 'date_published': iso(26 * HOUR)}]}).encode()
    feed = posts.parse(raw)
    assert feed['title'] == 'Notes' and feed['total'] == 2
    assert feed['items'][0] == {'title': 'Newer', 'ts': NOW - 2 * HOUR, 'link': 'https://example.org/n/2'}
    assert feed['items'][1]['title'] == 'Untitled post'


def test_posts_are_ordered_newest_first_and_undated_ones_last():
    raw = (f'<rss><channel><item><title>old</title><pubDate>{rfc(6 * DAY)}</pubDate></item>'
           '<item><title>undated</title></item>'
           f'<item><title>new</title><pubDate>{rfc(HOUR)}</pubDate></item></channel></rss>').encode()
    assert [p['title'] for p in posts.parse(raw)['items']] == ['new', 'old', 'undated']


def test_titles_are_plain_bounded_text():
    nasty = ('<rss><channel><item><title>&lt;script&gt;alert(1)&lt;/script&gt; Hello\u202e\x07 \n  world '
             + 'x' * 400 + '</title></item></channel></rss>').encode()
    title = posts.parse(nasty)['items'][0]['title']
    assert title.startswith('alert(1) Hello world x') and '<' not in title
    assert '\u202e' not in title and '\x07' not in title and '\n' not in title
    assert len(title) <= posts.TITLE_LIMIT and title.endswith('…')


def test_only_the_newest_posts_are_kept_but_all_are_counted():
    items = ''.join(f'<item><title>p{i}</title><pubDate>{rfc(i * HOUR)}</pubDate></item>'
                    for i in range(40))
    feed = posts.parse(f'<rss><channel>{items}</channel></rss>'.encode())
    assert feed['total'] == 40 and len(feed['items']) == posts.KEEP and len(feed['stamps']) == 40


@pytest.mark.parametrize('raw', [
    b'<html><body><h1>Blog</h1></body></html>',
    b'not a feed at all',
    b'{"hello": "world"}',
    b'',
])
def test_pages_that_are_not_feeds_are_refused(raw):
    with pytest.raises(ValueError):
        posts.parse(raw)


def test_document_type_declarations_are_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><rss><channel><item><title>&lol;</title></item></channel></rss>'
    with pytest.raises(ValueError):
        posts.parse(bomb)


def test_unclosed_entries_do_not_hang_or_invent_posts():
    raw = b'<rss><channel>' + b'<item><title>x' * 20000
    assert posts.parse(raw)['items'] == []


def test_declared_encodings_are_read():
    raw = '<?xml version="1.0" encoding="ISO-8859-1"?><rss><channel><item><title>Caf\u00e9</title></item></channel></rss>'.encode('latin-1')
    assert posts.parse(raw)['items'][0]['title'] == 'Caf\u00e9'


# The adapter

def test_poll_counts_new_posts_and_keeps_the_newest(monkeypatch):
    result = poll(monkeypatch, RSS)
    m = result.sample['metrics']
    assert m == {'new_24h': 2, 'new_7d': 3, 'hours_since_last': 3, 'items': 3}
    assert result.sample['unknown_reasons'] == {}
    assert [p['title'] for p in result.state['posts']] == ['Third post', 'Second post & more', 'First post']
    assert result.state['title'] == 'Example & Co. blog'


def test_poll_makes_one_call_to_the_approved_host_and_asks_for_feeds(monkeypatch):
    seen, net = serve(monkeypatch, RSS), Net()
    WebFeedSource().poll(definition(), None, {}, now=NOW, net=net)
    assert net.hosts == ['example.org'] and len(seen) == 1
    assert seen[0]['raw_response'] is True and 'atom+xml' in seen[0]['accept']


def test_a_post_dated_in_the_future_counts_as_just_published(monkeypatch):
    raw = f'<rss><channel><item><title>soon</title><pubDate>{rfc(-DAY)}</pubDate></item></channel></rss>'.encode()
    m = poll(monkeypatch, raw).sample['metrics']
    assert m['hours_since_last'] == 0 and m['new_24h'] == 1


def test_a_feed_without_dates_reports_unknown_not_zero(monkeypatch):
    result = poll(monkeypatch, b'<rss><channel><item><title>a</title></item></channel></rss>')
    m = result.sample['metrics']
    assert m['items'] == 1 and m['new_24h'] is None and m['hours_since_last'] is None
    assert 'no dates' in result.sample['unknown_reasons']['new_24h']


def test_an_empty_feed_is_zero_posts_not_an_error(monkeypatch):
    m = poll(monkeypatch, b'<rss><channel><title>Quiet</title></channel></rss>').sample['metrics']
    assert m == {'new_24h': 0, 'new_7d': 0, 'hours_since_last': None, 'items': 0}


def test_counts_age_between_polls(monkeypatch):
    result = poll(monkeypatch, RSS)
    later = WebFeedSource().current(result.sample, result.state, now=NOW + 20 * HOUR)
    assert later['metrics']['new_24h'] == 1 and later['metrics']['hours_since_last'] == 23
    assert result.sample['metrics']['new_24h'] == 2     # the stored sample is not changed


def test_a_page_that_is_not_a_feed_is_a_plain_error(monkeypatch):
    serve(monkeypatch, b'<html><body>hi</body></html>')
    with pytest.raises(SourceError) as error:
        WebFeedSource().poll(definition(), None, {}, now=NOW, net=Net())
    assert str(error.value) == 'This address is not an RSS, Atom or JSON feed. Cached values are preserved.'


@pytest.mark.parametrize('status,text', [
    (404, 'Feed not found. Check its address. Cached values are preserved.'),
    (301, 'Feed redirect refused. Use the final HTTPS address in a replacement definition. Cached values are preserved.'),
    (429, 'Feed host rate limited. Waiting before retry. Cached values are preserved.'),
    (500, 'Feed is unavailable. Cached values are preserved.'),
])
def test_http_failures_use_fixed_wording(monkeypatch, status, text):
    def fail(*a, **kw):
        raise SourceError('Public JSON endpoint refused the request. secret-body', status, 120)
    monkeypatch.setattr(http_json, '_fetch', fail)
    with pytest.raises(SourceError) as error:
        WebFeedSource().poll(definition(), None, {}, now=NOW, net=Net())
    assert str(error.value) == text and error.value.status == status


def test_an_oversized_feed_says_so(monkeypatch):
    def fail(*a, **kw):
        raise SourceError('Public JSON response exceeded the size limit.')
    monkeypatch.setattr(http_json, '_fetch', fail)
    with pytest.raises(SourceError) as error:
        WebFeedSource().poll(definition(), None, {}, now=NOW, net=Net())
    assert str(error.value) == 'Feed is larger than 512 KB. Cached values are preserved.'


def test_a_certificate_that_does_not_verify_is_named_and_never_bypassed(monkeypatch):
    import ssl

    def fail(*a, **kw):
        raise ssl.SSLCertVerificationError(1, 'certificate verify failed: certificate has expired')
    monkeypatch.setattr(http_json, '_fetch', fail)
    with pytest.raises(SourceError) as error:
        WebFeedSource().poll(definition(), None, {}, now=NOW, net=Net())
    assert str(error.value) == "The feed host's certificate could not be verified. Cached values are preserved."


def test_local_pacing_is_not_a_failure(monkeypatch):
    class Gate:
        def call(self, host, callback):
            raise Deferred('Waiting for request budget.', retry_after=30)
    with pytest.raises(Deferred):
        WebFeedSource().poll(definition(), None, {}, now=NOW, net=Gate())


def test_unexpected_parameters_are_refused_before_any_network(monkeypatch):
    seen = serve(monkeypatch, RSS)
    bad = {'source': {'kind': 'web.feed', 'params': {'url': URL, 'headers': {'Authorization': 'x'}}}}
    with pytest.raises(SourceError):
        WebFeedSource().poll(bad, None, {}, now=NOW, net=Net())
    assert seen == []


# The summary the cell draws

def test_summary_lists_posts_with_new_ones_marked(monkeypatch):
    result = poll(monkeypatch, RSS)
    summary = posts.summarize(result.sample, result.state, now=NOW)
    assert summary['new'] == 2 and summary['week'] == 3 and summary['last_ts'] == NOW - 3 * HOUR
    assert summary['title'] == 'Example & Co. blog' and summary['total'] == 3
    assert [(p['title'], p['new']) for p in summary['posts']] == [
        ('Third post', True), ('Second post & more', True), ('First post', False)]
    assert summary['posts'][0]['link'] == 'https://example.org/3'


def test_summary_for_the_agent_carries_counts_and_times_only(monkeypatch):
    result = poll(monkeypatch, RSS)
    compact = posts.summarize(result.sample, result.state, now=NOW, text=False)
    assert compact['new'] == 2 and compact['last_ts'] == NOW - 3 * HOUR
    assert 'posts' not in compact and 'title' not in compact
    assert 'Third post' not in json.dumps(compact)


def test_summary_before_the_first_sample_is_none():
    assert posts.summarize(None, {}, now=NOW) is None


# Through the engine

SOURCE = {'kind': 'web.feed', 'params': {'url': URL}}


@pytest.fixture
def engine(tmp_path, monkeypatch):
    serve(monkeypatch, RSS)
    made = Engine(tmp_path, clock=lambda: NOW, jitter=lambda: 0)
    monkeypatch.setattr(made.net, 'call', lambda host, callback: callback())
    return made


def test_status_carries_posts_for_a_plain_pulse_and_the_agent_view_has_no_titles(engine):
    engine.activate({'pulse': 1, 'id': 'blog', 'title': 'Example blog', 'source': SOURCE})
    engine.poll_one_due(previews=False)
    row = engine.status(poll=False)['pulses'][0]
    assert row['state'] in ('active', 'warming') and row['error'] is None
    assert row['posts']['new'] == 2 and row['posts']['posts'][0]['title'] == 'Third post'
    compact = engine.status(poll=False, compact=True)['pulses'][0]
    assert compact['posts']['new'] == 2 and compact['posts']['last_ts'] == NOW - 3 * HOUR
    assert 'Third post' not in json.dumps(compact) and 'Example & Co.' not in json.dumps(compact)


def test_status_carries_posts_for_a_designed_pulse(engine):
    engine.activate({'pulse': 1, 'id': 'designed', 'title': 'Example blog', 'feeds': {'main': {**SOURCE, 'every': '30m'}},
                     'display': [{'type': 'stat', 'value': 'main.new_24h', 'label': 'New'}]})
    engine.poll_one_due(previews=False)
    row = engine.status(poll=False)['pulses'][0]
    assert row['posts']['week'] == 3 and len(row['posts']['posts']) == 3
    assert 'Third post' not in json.dumps(engine.status(poll=False, compact=True)['pulses'][0])


def test_samples_in_history_hold_numbers_only(engine):
    engine.activate({'pulse': 1, 'id': 'blog', 'title': 'Example blog', 'source': SOURCE})
    engine.poll_one_due(previews=False)
    history = engine.store.history('blog', since=0)
    assert history and 'Third post' not in json.dumps(history)
    assert history[-1]['metrics'] == {'new_24h': 2, 'new_7d': 3, 'hours_since_last': 3, 'items': 3}


# Definition, budget and disclosure

def test_defaults_budget_and_the_approved_host():
    made = normalize({'pulse': 1, 'title': 'Example blog', 'source': SOURCE})
    assert made['every'] == '30m' and made['capsule']['metric'] == 'new_24h'
    cost = budget(made)
    assert cost['hosts'] == ['example.org'] and cost['req_per_hour'] == 2


def test_polling_faster_than_every_15_minutes_is_refused():
    with pytest.raises(ValidationError):
        normalize({'pulse': 1, 'title': 'Example blog', 'source': SOURCE, 'every': '5m'})


@pytest.mark.parametrize('url', ['http://example.org/feed.xml', 'https://127.0.0.1/feed.xml', 'file:///etc/passwd', 'https://user:pw@example.org/f'])
def test_only_public_https_addresses_are_accepted(url):
    with pytest.raises(ValidationError):
        normalize({'pulse': 1, 'title': 'Bad', 'source': {'kind': 'web.feed', 'params': {'url': url}}})


def test_approval_text_says_titles_are_shown_and_not_sent_to_the_model():
    text = proposal_disclosure(normalize({'pulse': 1, 'title': 'Example blog', 'source': SOURCE}))['summary']
    assert 'example.org' in text and 'post titles' in text and 'never sent to the model' in text


def test_builder_template_makes_a_new_posts_pulse():
    made = from_template('posts', {'url': 'https://www.example.org/feed.xml'})
    assert made['ok'] is True and made['suggested_title'] == 'example.org · new posts'
    assert made['feeds']['main'] == {'kind': 'web.feed', 'params': {'url': 'https://www.example.org/feed.xml'}, 'every': '30m'}
    assert [m['ref'] for m in made['metrics'] if m['default_selected']] == ['main.new_24h', 'main.new_7d']
    named = from_template('posts', {'url': URL, 'name': 'Hermes releases'})
    assert named['suggested_title'] == 'Hermes releases'
    assert from_template('posts', {'url': 'http://example.org/feed.xml'})['ok'] is False


def test_releases_template_reads_a_repository_release_feed():
    made = from_template('releases', {'repo': 'https://github.com/NousResearch/hermes-agent'})
    assert made['ok'] is True and made['suggested_title'] == 'hermes-agent · releases'
    assert made['feeds']['main'] == {'kind': 'web.feed', 'every': '30m',
                                     'params': {'url': 'https://github.com/NousResearch/hermes-agent/releases.atom'}}
    assert made['suggested_icon'] == {'brand': 'github'}
    cost = budget({'pulse': 1, 'title': 'Releases', 'feeds': made['feeds'], 'icon': 'initials',
                   'display': [{'type': 'stat', 'value': 'main.new_24h'}]})
    assert cost['hosts'] == ['github.com'] and cost['req_per_hour'] == 2
    assert from_template('releases', {'repo': 'not a repository'})['ok'] is False
    assert from_template('releases', {'repo': 'https://gitlab.com/a/b'})['ok'] is False


@pytest.mark.parametrize('url,slug', [
    ('https://github.com/NousResearch/hermes-agent/releases.atom', 'github'),
    ('https://www.reddit.com/r/LocalLLaMA/.rss', 'reddit'),
    ('https://example.org/feed.xml', 'rss'),
    ('https://github.com.evil.example/feed.xml', 'rss'),      # a look-alike host gets no site logo
    ('https://not-github.com/feed.xml', 'rss'),
])
def test_feed_icons_are_bundled_logos_chosen_from_the_host(engine, url, slug):
    engine.activate({'pulse': 1, 'id': 'icon', 'title': 'Icon', 'source': {'kind': 'web.feed', 'params': {'url': url}}})
    engine.poll_one_due(previews=False)
    icon = engine.status(poll=False)['pulses'][0]['icon_resolved']
    assert icon['kind'] == 'brand' and icon['slug'] == slug
