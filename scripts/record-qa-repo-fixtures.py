"""Bounded public GitHub QA capture; no credentials, redirects, or retries."""
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


paths = [
    '/repos/NousResearch/hermes-agent',
    '/repos/NousResearch/hermes-agent/pulls?state=open&per_page=1',
    '/repos/NousResearch/hermes-agent/stats/participation',
    '/repos/NousResearch/hermes-agent/actions/runs?branch=main&per_page=1',
    '/repos/Stormxftw/Pulse',
    '/repos/Stormxftw/Pulse/stats/participation',
    '/repos/Stormxftw/Pulse/actions/runs?branch=main&per_page=1',
    '/repos/octocat/Hello-World/actions/runs?branch=master&per_page=1',
    '/repos/atom/atom',
    '/repos/twitter/bootstrap',
]
opener = urllib.request.build_opener(NoRedirect())
records = []
for target in paths:
    request = urllib.request.Request('https://api.github.com' + target, headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': 'PulseRings-QA',
        'X-GitHub-Api-Version': '2022-11-28'})
    try:
        response = opener.open(request, timeout=8)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read(512 * 1024 + 1)
        assert len(raw) <= 512 * 1024
        headers = {k.lower(): v for k, v in response.headers.items() if k.lower() in (
            'content-type', 'link', 'location', 'x-ratelimit-remaining')}
        body = json.loads(raw) if raw else None
        # Only retain public numeric/state evidence, never unrelated text/user data.
        if target.endswith('/participation'):
            safe = body
        elif '/actions/runs?' in target:
            safe = {key: body.get(key) for key in ('total_count',) if key in body}
            safe['workflow_runs'] = [{key: run.get(key) for key in ('id', 'status', 'conclusion', 'head_branch')}
                                     for run in body.get('workflow_runs', [])]
        elif '/pulls?' in target:
            safe = [{'number': item.get('number')} for item in body]
        else:
            safe = {key: body.get(key) for key in ('id', 'full_name', 'stargazers_count', 'forks_count',
                    'open_issues_count', 'pushed_at', 'default_branch', 'archived', 'size') if key in body}
        records.append({'path': target, 'status': response.code, 'headers': headers, 'body': safe,
                        'empty_body': not raw})
        print(target, response.code, json.dumps(safe)[:350])
    time.sleep(2)
output = Path(__file__).resolve().parents[1] / 'tests/fixtures/github/qa-repo-public.json'
output.write_text(json.dumps({'captured_at': datetime.now(timezone.utc).isoformat(),
                             'requests': len(records), 'records': records}, indent=2) + '\n', encoding='utf-8')
print('Saved', len(records), 'sanitized public responses')
