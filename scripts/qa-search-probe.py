"""Opt-in bounded unauthenticated GitHub probe; prints counts, never payloads.

Run with the project's QA Python environment. Eight read-only search requests,
seven seconds apart. No credentials, redirects, persistence or production writes.
"""
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pulse_rings.sources import github
from pulse_rings.sources.base import SourceError
from pulse_rings.spec import normalize

github._optional_token = lambda: None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class PublicNet:
    def __init__(self):
        self.calls = []

    def bytes(self, url, headers):
        if self.calls:
            time.sleep(7)
        req = urllib.request.Request(url, headers={**headers, 'User-Agent': 'PulseRings-search-QA'})
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as response:
                raw = response.read(200000)
                body = json.loads(raw)
                self.calls.append({'url': url, 'status': response.status,
                                   'total_count': body.get('total_count'),
                                   'incomplete_results': body.get('incomplete_results')})
                return raw, dict(response.headers)
        except urllib.error.HTTPError as exc:
            self.calls.append({'url': url, 'status': exc.code})
            raise SourceError('Upstream HTTP failure', exc.code) from None


def main():
    net, checks = PublicNet(), []
    now = int(time.time())
    for window, extra in [('24h', {'title_contains': 'plugin-catalog'}),
                          ('7d', {'title_contains': 'plugin-catalog'}),
                          ('24h', {'title_contains': 'fix', 'label': 'bug'}),
                          ('7d', {'title_contains': 'qa-zero-unique-7cd621e3'})]:
        d = normalize({'pulse': 1, 'title': 'Search QA', 'source': {'kind': 'github.search',
                       'params': {'repo': 'NousResearch/hermes-agent', 'type': 'pr',
                                  'window': window, **extra}}})
        try:
            first = github.GitHubSearch().poll(d, None, {}, now=now, net=net)
            second = github.GitHubSearch().poll(d, None, first.state, now=now + 2, net=net)
            baseline, recent = net.calls[-2:]
            expected = baseline['total_count'] * (7 if window == '7d' else 1) / 14
            assert second.sample['metrics'] == {'recent': recent['total_count'], 'baseline': expected}
            checks.append({'window': window, 'filters': extra, 'metrics': second.sample['metrics'], 'matched_raw_api': True})
        except SourceError as exc:
            checks.append({'window': window, 'filters': extra, 'error': str(exc), 'status': exc.status})
    print(json.dumps({'now': now, 'requests': len(net.calls), 'checks': checks, 'responses': net.calls}, indent=2))


if __name__ == '__main__':
    main()
