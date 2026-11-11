"""New-posts pulses: read an RSS, Atom or JSON feed into a short list of titles and times.

Pure functions, no I/O. A feed is untrusted text: titles become plain bounded strings, links are
offered only as https URLs, document type declarations are refused, and every scan is linear in
the size of the (already capped) body. Nothing here evaluates markup or resolves entities beyond
the fixed HTML character references.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import html
import re
from urllib.parse import urlsplit

from .net import strict_json

KEEP = 8            # posts kept with their titles
STAMPS = 200        # entries read and entry times kept for counting
TITLE_LIMIT = 140
LINK_LIMIT = 512
DAY = 86400
UNTITLED = 'Untitled post'
_ENCODINGS = frozenset(('utf-8', 'utf8', 'us-ascii', 'ascii', 'iso-8859-1', 'latin-1', 'latin1',
                        'iso-8859-15', 'windows-1252', 'cp1252'))
_TAG = re.compile(r'<[^<>]{0,300}>')
_CONTROL = re.compile(r'[\x00-\x1f\x7f-\x9f]')
# Zero-width and bidirectional controls can reorder or hide text in a title.
_INVISIBLE = re.compile('[\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]')
_ROOT = re.compile(r'<([A-Za-z][A-Za-z0-9:._-]{0,40})')
_LINK = re.compile(r'<link\b([^<>]{0,1000})>')
_HREF = re.compile(r'''\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')''')
_REL = re.compile(r'''\brel\s*=\s*(?:"([^"]*)"|'([^']*)')''')
_SPACE = (' ', '\n', '\t', '\r')


def _decode(raw):
    if raw[:3] == b'\xef\xbb\xbf':
        return raw[3:].decode('utf-8', 'replace')
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode('utf-16', 'replace')
    declared = re.search(r'''encoding=["']([A-Za-z0-9._-]{1,30})["']''', raw[:200].decode('ascii', 'replace'))
    name = declared[1].lower() if declared else 'utf-8'
    return raw.decode(name if name in _ENCODINGS else 'utf-8', 'replace')


def clean(value, limit=TITLE_LIMIT):
    """Plain single-line text: no markup, control or direction characters, at most limit long."""
    if not isinstance(value, str):
        return ''
    text = value[:4000].replace('<![CDATA[', '').replace(']]>', '')
    text = _TAG.sub('', html.unescape(text))
    text = _INVISIBLE.sub('', _CONTROL.sub(' ', text))
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def https_link(value):
    """The link if it is a plain https URL, else None. Other schemes are never offered."""
    if not isinstance(value, str):
        return None
    url = html.unescape(value.replace('<![CDATA[', '').replace(']]>', '')).strip()
    if not url or len(url) > LINK_LIMIT or re.search(r'[\s\\\x00-\x1f\x7f<>"\'`{}]', url):
        return None
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return None
    return url if parts.scheme == 'https' and host and '@' not in parts.netloc else None


def when(value):
    """Seconds since the epoch for an RFC 822 or ISO 8601 date, else None."""
    text = clean(value, 64)
    if not text:
        return None
    try:
        if re.match(r'\d{4}-\d{2}-\d{2}', text):
            moment = datetime.fromisoformat(text[:-1] + '+00:00' if text[-1] in 'Zz' else text)
        else:
            moment = parsedate_to_datetime(text)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        stamp = moment.timestamp()
    except (TypeError, ValueError, IndexError, OverflowError, OSError):
        return None
    return float(stamp) if 0 < stamp < 4102444800 else None


def _blocks(text, tag):
    """Complete <tag>…</tag> spans, left to right. Each character is visited a bounded number of times."""
    opening, closing, spans, position = '<' + tag, '</' + tag + '>', [], 0
    while len(spans) < STAMPS:
        start = text.find(opening, position)
        if start < 0:
            break
        body = start + len(opening)
        if text[body:body + 1] not in ('>',) + _SPACE:
            position = body
            continue
        end = text.find(closing, body)
        if end < 0:
            break
        spans.append((start, text[body:end]))
        position = end + len(closing)
    return spans


def _field(block, names):
    """Text of the first <name>…</name> among names, in order of preference."""
    for name in names:
        opening, start = '<' + name, block.find('<' + name)
        while start >= 0:
            after = start + len(opening)
            if block[after:after + 1] in ('>', '/') + _SPACE:
                close = block.find('>', after)
                end = block.find('</' + name + '>', close) if close >= 0 and block[close - 1] != '/' else -1
                if end >= 0:
                    return block[close + 1:end]
                break
            start = block.find(opening, after)
    return None


def _link(block):
    for match in _LINK.finditer(block[:20000]):
        href = _HREF.search(match[1])
        if href:
            rel = _REL.search(match[1])
            if rel is None or (rel[1] or rel[2]) == 'alternate':
                return https_link(href[1] if href[1] is not None else href[2])
            continue
        end = block.find('</link>', match.end())
        if end >= 0:
            return https_link(block[match.end():end])
    return None


def _xml(text):
    upper = text.upper()
    if '<!DOCTYPE' in upper or '<!ENTITY' in upper:
        raise ValueError('document type declarations are refused')
    root = _ROOT.search(text)
    name = root[1].split(':')[-1] if root else ''
    if name in ('rss', 'RDF'):
        tag, dates = 'item', ('pubDate', 'dc:date', 'date')
    elif name == 'feed':
        tag, dates = 'entry', ('published', 'updated')
    else:
        raise ValueError('not a feed')
    spans = _blocks(text, tag)
    head = text[:spans[0][0]] if spans else text
    entries = [{'title': clean(_field(block, ('title',))) or UNTITLED,
                'ts': when(_field(block, dates)), 'link': _link(block)} for _start, block in spans]
    return clean(_field(head[head.find(root[0]):], ('title',))) or None, entries


def _json(raw):
    data = strict_json(raw)
    if (not isinstance(data, dict) or not isinstance(data.get('items'), list)
            or not str(data.get('version', '')).startswith('https://jsonfeed.org/version/')):
        raise ValueError('not a feed')
    entries = [{'title': clean(item.get('title')) or UNTITLED,
                'ts': when(item.get('date_published') or item.get('date_modified')),
                'link': https_link(item.get('url'))}
               for item in data['items'][:STAMPS] if isinstance(item, dict)]
    return clean(data.get('title')) or None, entries


def parse(raw):
    """Read a feed body. Raises ValueError when the body is not an RSS, Atom or JSON feed."""
    if not isinstance(raw, (bytes, bytearray)) or not raw.strip():
        raise ValueError('not a feed')
    title, entries = _json(bytes(raw)) if raw.lstrip()[:1] == b'{' else _xml(_decode(bytes(raw)))
    # Newest first; entries without a date keep their feed order after the dated ones.
    dated = sorted((e for e in entries if e['ts'] is not None), key=lambda e: -e['ts'])
    ordered = dated + [e for e in entries if e['ts'] is None]
    return {'title': title, 'items': ordered[:KEEP], 'total': len(entries),
            'stamps': [e['ts'] for e in dated], 'undated': len(entries) - len(dated)}


def counts(stamps, total, undated, now):
    """Metrics and the reasons any of them are unknown, from entry times alone."""
    stamps = [min(t, now) for t in stamps if isinstance(t, (int, float)) and not isinstance(t, bool)]
    metrics = {'new_24h': sum(1 for t in stamps if now - t < DAY),
               'new_7d': sum(1 for t in stamps if now - t < 7 * DAY),
               'hours_since_last': int((now - max(stamps)) // 3600) if stamps else None,
               'items': total}
    reasons = {}
    if not stamps and total:
        reason = 'Feed entries carry no dates.'
        metrics.update(new_24h=None, new_7d=None)
        reasons.update(new_24h=reason, new_7d=reason, hours_since_last=reason)
    elif not stamps:
        reasons['hours_since_last'] = 'No posts in the feed yet.'
    return metrics, reasons


def summarize(sample, state, *, now, text=True):
    """What a new-posts cell draws. text=False is the agent's view: counts and times, never titles."""
    if not sample or not isinstance(sample.get('metrics'), dict) or 'items' not in sample['metrics']:
        return None
    metrics = sample['metrics']
    stamps = [min(t, now) for t in state.get('stamps', []) if isinstance(t, (int, float)) and not isinstance(t, bool)]
    out = {'new': metrics.get('new_24h'), 'week': metrics.get('new_7d'), 'total': metrics.get('items'),
           'last_ts': max(stamps) if stamps else None, 'ts': sample.get('ts')}
    if text:
        out['title'] = state.get('title') if isinstance(state.get('title'), str) else None
        out['posts'] = [{'title': clean(post.get('title')) or UNTITLED,
                         'ts': post.get('ts') if isinstance(post.get('ts'), (int, float)) else None,
                         'link': https_link(post.get('link')),
                         'new': isinstance(post.get('ts'), (int, float)) and now - post['ts'] < DAY}
                        for post in state.get('posts', [])[:KEEP] if isinstance(post, dict)]
    return out
