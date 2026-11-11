#!/usr/bin/env python
"""Opt-in, four unauthenticated GitHub GETs. Never used by tests.

Run from the repository: python scripts/record-github-fixtures.py --record
All responses (including errors) are recorded; no automatic retries or redirects.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', action='store_true', help='authorize exactly four public GETs')
    args = parser.parse_args()
    if not args.record:
        parser.error('No network without --record')
    from datetime import timedelta
    now = datetime.now(timezone.utc).replace(microsecond=0)
    iso = lambda value: value.isoformat().replace('+00:00', 'Z')
    end = now - timedelta(days=1)
    start = end - timedelta(days=14)
    # GitHub ranges are inclusive at second precision. Keep the windows disjoint.
    common = 'repo:NousResearch/hermes-agent is:pr catalog in:title'
    queries = {
        'recent': common + ' created:' + iso(end) + '..' + iso(now),
        'baseline': common + ' created:' + iso(start) + '..' + iso(end - timedelta(seconds=1)),
    }
    urls = {name: 'https://api.github.com/search/issues?' + urllib.parse.urlencode({'q': query, 'per_page': 1})
            for name, query in queries.items()}
    urls.update(repo='https://api.github.com/repos/NousResearch/hermes-agent',
                pulls='https://api.github.com/repos/NousResearch/hermes-agent/pulls?state=open&per_page=1')
    root = Path(__file__).resolve().parents[1] / 'tests/fixtures/github'
    root.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime('%Y%m%dT%H%M%SZ')
    opener = urllib.request.build_opener(NoRedirect())
    files = {}
    for index, (name, url) in enumerate(urls.items()):
        if index:
            time.sleep(2.1)
        request = urllib.request.Request(url, headers={'User-Agent': 'PulseRings-fixture-recorder/0.4.0',
            'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}, method='GET')
        try:
            response = opener.open(request, timeout=8)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read(524289)
            if len(raw) > 524288:
                raise RuntimeError('Response too large; no retries performed')
            record = {'recorded_at': iso(datetime.now(timezone.utc)), 'url': url,
                      'status': response.code, 'headers': dict(response.headers),
                      'body': json.loads(raw)}
        filename = stamp + '-' + name + '.json'
        (root / filename).write_text(json.dumps(record, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        files[name] = filename
        print(name, record['status'], record['body'].get('total_count') if isinstance(record['body'], dict) else len(record['body']))
    manifest = {'as_of': iso(now), 'now': now.timestamp(), 'repo': 'NousResearch/hermes-agent',
                'title_contains': 'catalog', 'window': '24h', 'baseline_days': 14,
                'recent_start': iso(end), 'baseline_start': iso(start),
                'baseline_end': iso(end - timedelta(seconds=1)), 'files': files,
                'requests': 4, 'authenticated': False}
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
