"""New posts from an approved public RSS, Atom or JSON feed.

One GET per poll to the approved host, through the same pinned, no-redirect, size-capped transport
as public JSON pulses. The body is read by posts.parse; only bounded plain titles, https links and
entry times are kept, in this feed's source state. Samples hold numbers only.
"""
import copy
import ssl

from . import http_json
from .base import Deferred, SourceError, SourceResult
from .. import posts

ACCEPT = ('application/atom+xml, application/rss+xml, application/feed+json, '
          'application/xml;q=0.9, text/xml;q=0.9, application/json;q=0.8, */*;q=0.1')
_KEEP = ' Cached values are preserved.'
_UNAVAILABLE = 'Feed is unavailable.'
_NOT_FEED = 'This address is not an RSS, Atom or JSON feed.'
# Transport failures are reworded for feeds; nothing from the response crosses this boundary.
_TRANSPORT = {
    'Public JSON source timed out.': 'Feed timed out.',
    'Public JSON source returned unsupported compression.': 'Feed uses unsupported compression.',
    'Public JSON response exceeded the size limit.': 'Feed is larger than 512 KB.',
    'Public JSON response was incomplete.': 'Feed response was incomplete.',
    'Public URL safety check refused this address.': 'Public URL safety check refused this address.',
    'Public DNS resolver is busy.': 'Public DNS resolver is busy.',
    'Public JSON requires Hermes URL-safety APIs; source disabled.':
        'New-posts pulses require Hermes URL-safety APIs; source disabled.',
    'Invalid approved public HTTPS URL.': 'Feed address is not a valid public HTTPS URL.',
    'Unsupported approved feed parameters.': 'Unsupported approved feed parameters.',
    _NOT_FEED: _NOT_FEED,
}


class WebFeedSource:
    arbitrary_host = True
    pre_approval_sample = False

    def poll(self, definition, previous, state, *, now, net):
        """Approval belongs to the human activation seam, never proposal preview."""
        try:
            params = definition['source']['params']
            if set(params) - {'url'} - {key for key in params if key.startswith('x-')}:
                raise SourceError('Unsupported approved feed parameters.')
            host, target = http_json._url(params['url'])
            raw, _headers = net.call(host, lambda: http_json._fetch(
                params['url'], host, target, now=now, raw_response=True, accept=ACCEPT))
            try:
                feed = posts.parse(raw)
            except (ValueError, UnicodeError, RecursionError):
                raise SourceError(_NOT_FEED) from None
            stamps = [min(stamp, now) for stamp in feed['stamps']]
            kept = [dict(post, ts=min(post['ts'], now) if post['ts'] is not None else None) for post in feed['items']]
            metrics, reasons = posts.counts(stamps, feed['total'], feed['undated'], now)
            return SourceResult(
                sample={'ts': now, 'metrics': metrics, 'baselines': {}, 'unknown_reasons': reasons},
                state={'posts': kept, 'stamps': stamps, 'total': feed['total'],
                       'undated': feed['undated'], 'title': feed['title']})
        except Deferred:
            raise  # Local pacing/ceiling is never a remote failure.
        except SourceError as exc:
            status = exc.status if type(exc.status) is int and 100 <= exc.status <= 599 else 0
            message = ('Feed redirect refused. Use the final HTTPS address in a replacement definition.'
                       if 300 <= status < 400 else {
                           404: 'Feed not found. Check its address.',
                           429: 'Feed host rate limited. Waiting before retry.',
                       }.get(status, _TRANSPORT.get(str(exc), _UNAVAILABLE)))
            raise SourceError(message + _KEEP, status=status, retry_after=exc.retry_after) from None
        except TimeoutError:
            raise SourceError('Feed timed out.' + _KEEP) from None
        except ssl.SSLCertVerificationError:
            raise SourceError("The feed host's certificate could not be verified." + _KEEP) from None
        except Exception:
            raise SourceError(_UNAVAILABLE + _KEEP) from None

    def current(self, sample, state, *, now):
        """Counts by age move between polls; recompute them from the stored entry times."""
        sample = copy.deepcopy(sample)
        if 'items' not in sample.get('metrics', {}) or not isinstance(state.get('stamps'), list):
            return sample
        metrics, reasons = posts.counts(state['stamps'], sample['metrics']['items'], state.get('undated', 0), now)
        sample['metrics'].update(metrics)
        kept = {name: text for name, text in sample.get('unknown_reasons', {}).items() if name not in metrics}
        sample['unknown_reasons'] = {**kept, **reasons}
        return sample
