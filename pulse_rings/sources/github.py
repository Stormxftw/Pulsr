"""Count-only GitHub adapters. No transport outside the injected net boundary.

A cold search stages its baseline first, then its recent count >=2 seconds later.
This avoids sleeping or tripping the shared host gate, and the first *sample*
already has a real source baseline. State contains counts, never HTTP payloads.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from .base import SourceError, SourceResult, Deferred

API = 'https://api.github.com'
BASELINE_TTL = 21600
# A staged repository snapshot older than this is discarded and read again.
STAGE_TTL = 90
_REPO = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}')
_TEXT = re.compile(r'[A-Za-z0-9 ._-]{1,40}')


def _number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value >= 0)


class _GitHubDataError(SourceError):
    """Fixed local diagnostics, never text supplied by the network boundary."""


def _count(value):
    if not _number(value) or int(value) != value:
        raise _GitHubDataError('GitHub did not return a valid count.')
    return int(value)


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def search_url(params, start, end):
    """Build a bounded structured query; no user-supplied GitHub query language."""
    repo = params['repo']
    if not _REPO.fullmatch(repo) or '..' in repo.split('/')[1] or params['type'] not in ('pr', 'issue'):
        raise _GitHubDataError('Invalid approved GitHub parameters.')
    query = [f'repo:{repo}', 'is:' + params['type']]
    for key in ('title_contains', 'label'):
        if key in params and not _TEXT.fullmatch(params[key]):
            raise _GitHubDataError('Invalid approved GitHub parameters.')
    if params.get('title_contains'):
        title = params['title_contains']
        # Quote phrases and operator-shaped terms, keeping simple historical
        # queries stable. Validation above excludes quotes/query qualifiers.
        if ' ' in title or title in ('AND', 'OR', 'NOT') or title.startswith('-'):
            title = '"' + title + '"'
        query.extend([title, 'in:title'])
    if params.get('label'):
        query.append('label:"' + params['label'] + '"')
    query.append('created:' + _iso(start) + '..' + _iso(end))
    return API + '/search/issues?' + urlencode({'q': ' '.join(query), 'per_page': 1})


class _TokenUnavailable(SourceError):
    """Locally sanitized credential-scope error, not an upstream response."""


def _optional_token():
    try:
        from agent.secret_scope import get_secret
    except ImportError:
        return None
    try:
        from agent.secret_scope import UnscopedSecretError
    except ImportError:
        UnscopedSecretError = ()  # Older hosts can still supply get_secret.
    # Fail closed, but preserve an actionable error instead of a network diagnosis.
    try:
        return get_secret('PULSE_RINGS_GITHUB_TOKEN')
    except UnscopedSecretError:
        raise _TokenUnavailable('GitHub token unavailable to background collection; '
                                'open the Pulses pane or restart Hermes.') from None


def _headers():
    headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    token = _optional_token()
    if token:
        if not isinstance(token, str) or len(token) > 1024 or re.search(r'[\s\x00-\x1f\x7f]', token):
            raise _GitHubDataError('GitHub credential configuration is invalid.')
        headers['Authorization'] = 'Bearer ' + token
    return headers


def _get(net, url):
    # Never follow response links or avatar URLs, and never send secrets elsewhere.
    if urlsplit(url).netloc != 'api.github.com' or urlsplit(url).scheme != 'https':
        raise SourceError('GitHub request host refused.')
    raw, headers = net.bytes(url, headers=_headers())
    h = {key.lower(): value for key, value in headers.items()}
    mime = h.get('content-type', '').split(';')[0].strip().lower()
    if not (mime == 'application/json' or mime.endswith('+json')):
        raise _GitHubDataError('GitHub returned an unsupported content type.')
    from ..net import strict_json
    try:
        return strict_json(raw), h
    except (ValueError, UnicodeError):
        # Optional repo endpoints must degrade their own metrics, not discard
        # already measured stars/forks/PRs because decoding escaped the boundary.
        raise _GitHubDataError('GitHub returned invalid JSON data.') from None


def _public_error(exc):
    # The network layer owns arrival-time reset/Retry-After interpretation, with
    # its injected clock. Never retain the upstream exception/body/URL/token.
    if isinstance(exc, _GitHubDataError):
        return exc
    status = exc.status if isinstance(exc.status, int) else 0
    delay = exc.retry_after
    if not _number(delay):
        delay = 600
    delay = min(86400 if status == 404 else 21600, max(2, delay))
    message = {401: 'GitHub credential rejected. Check the configured token.',
               403: 'GitHub unavailable or rate limited. Waiting before retry.',
               429: 'GitHub rate limited. Waiting before retry.',
               404: 'GitHub public repository not found.',
               422: 'GitHub rejected the approved search parameters.'}.get(status,
                   'GitHub server error. Waiting before retry.' if status >= 500 else
                   'Could not reach GitHub. Cached history is preserved.' if status == 0 else
                   'GitHub count is temporarily unavailable.')
    return SourceError(message, status=status, retry_after=delay)


class GitHubSearch:
    def poll(self, definition, previous, state, *, now, net):
        try:
            return self._poll(definition, previous, state, now=now, net=net)
        except (Deferred, _TokenUnavailable):
            raise
        except SourceError as exc:
            raise _public_error(exc) from None
        except Exception:
            raise SourceError('GitHub count is temporarily unavailable.') from None

    def _poll(self, definition, previous, state, *, now, net):
        params = definition['source']['params']
        window = {'24h': 86400, '7d': 604800}[params.get('window', '24h')]
        days = params.get('baseline_days', 14)
        if isinstance(days, bool) or not isinstance(days, int) or not 7 <= days <= 30:
            raise _GitHubDataError('Invalid approved GitHub parameters.')
        key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        cache = dict(state) if state.get('query_key') == key else {}
        valid = (_number(cache.get('baseline')) and _number(cache.get('baseline_due'))
                 and cache['baseline_due'] > now and cache['baseline_due'] <= now + BASELINE_TTL)
        if not valid:
            end = math.floor(now) - window
            start = end - days * 86400
            body, _ = _get(net, search_url(params, start, end - 1))
            if not isinstance(body, dict) or body.get('incomplete_results') is not False:
                raise _GitHubDataError('GitHub search count is incomplete.')
            count = _count(body.get('total_count'))
            cache = {'query_key': key, 'baseline': count * window / (days * 86400),
                     'baseline_count': count, 'baseline_start': start, 'baseline_end': end - 1,
                     'baseline_due': now + BASELINE_TTL}
            return SourceResult(state=cache, next_due=now + 2)
        body, _ = _get(net, search_url(params, math.floor(now) - window, math.floor(now)))
        if not isinstance(body, dict) or body.get('incomplete_results') is not False:
            raise _GitHubDataError('GitHub search count is incomplete.')
        sample = {'ts': now, 'metrics': {'recent': _count(body.get('total_count')), 'baseline': cache['baseline']},
                  'baselines': {'recent': cache['baseline']}, 'unknown_reasons': {}}
        return SourceResult(sample=sample, state=cache, metadata={'baseline_days': days,
            'baseline_count': cache['baseline_count'], 'baseline_start': cache['baseline_start'],
            'baseline_end': cache['baseline_end'], 'window_seconds': window})


def pulls_count(body, headers, repo, repo_id=None):
    """Count per_page=1 without traversing Link URLs. An absent last is not 0."""
    if (not isinstance(body, list) or len(body) > 1
            or any(not isinstance(item, dict) for item in body)):
        raise SourceError('GitHub returned an invalid pull request count.')
    link = headers.get('link', '')
    for part in link.split(','):
        match = re.fullmatch(r'\s*<([^>]+)>\s*;\s*rel="last"\s*', part)
        if not match:
            continue
        url = urlsplit(match[1])
        query = parse_qs(url.query)
        paths = {'/repos/' + repo + '/pulls'}
        if isinstance(repo_id, int) and not isinstance(repo_id, bool) and repo_id > 0:
            paths.add('/repositories/' + str(repo_id) + '/pulls')
        if (not body or url.scheme != 'https' or url.netloc != 'api.github.com' or url.fragment
                or url.path not in paths or query.get('per_page') != ['1']
                or query.get('state') != ['open'] or not re.fullmatch(r'[1-9][0-9]{0,9}', query.get('page', [''])[0])):
            raise SourceError('GitHub returned an invalid pagination count.')
        return int(query['page'][0])
    if link:  # e.g. next with no last; never fabricate a complete count
        raise SourceError('GitHub pagination did not disclose a complete count.')
    return len(body)


class GitHubRepo:
    """Stage one fixed-host request per invocation, respecting the shared gate."""

    @staticmethod
    def _push_time(value):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed.timestamp() if parsed.tzinfo is not None else None
        except (ValueError, TypeError, AttributeError, OverflowError):
            return None

    def current(self, sample, state, *, now):
        from copy import deepcopy
        sample = deepcopy(sample)
        if 'hours_since_push' in sample.get('metrics', {}):
            pushed = state.get('pushed_at')
            value = max(0, (now - pushed) / 3600) if _number(pushed) and pushed <= now else None
            sample['metrics']['hours_since_push'] = value
            if value is None:
                sample.setdefault('unknown_reasons', {})['hours_since_push'] = 'Last push unavailable'
        return sample

    def staged(self, definition, state, *, now):
        """True while a fresh snapshot still awaits its remaining one-request stages.

        Claim-order hint only (no I/O, no state change). The engine finishes such
        bounded work before starting another collection, so feeds that become due
        together cannot expire each other's snapshots and restart forever. It is
        bounded by STAGE_TTL from the first stage and by the fixed stage count.
        """
        if not isinstance(state, dict):
            return False
        params = definition['source']['params']
        repo = params.get('repo')
        if params.get('activity') is True or params.get('ci') is True:
            pending = state.get('activity_pending')
            ts = pending.get('ts') if isinstance(pending, dict) else None
            current = state.get('activity_key') == [repo, params.get('activity') is True, params.get('ci') is True]
        else:
            ts = state.get('pending_ts') if isinstance(state.get('pending'), dict) else None
            current = state.get('repo') == repo
        return bool(current and _number(ts) and 0 <= now - ts <= STAGE_TTL)

    def _activity_poll(self, definition, state, *, now, net):
        from copy import deepcopy
        params = definition['source']['params']
        repo = params['repo']
        if not _REPO.fullmatch(repo) or '..' in repo.split('/')[1]:
            raise SourceError('Invalid approved GitHub repository.')
        key = (repo, params.get('activity') is True, params.get('ci') is True)
        cache = deepcopy(state) if state.get('activity_key') == list(key) else {'activity_key': list(key)}
        pending = cache.get('activity_pending')
        if not isinstance(pending, dict) or not 0 <= now - pending.get('ts', 0) <= STAGE_TTL:
            body, _ = _get(net, API + '/repos/' + repo)
            metrics = {name: _count(body.get(field)) for name, field in
                       [('stars', 'stargazers_count'), ('forks', 'forks_count'), ('open_issues', 'open_issues_count')]}
            cache.update(repo_id=_count(body.get('id')), pushed_at=self._push_time(body.get('pushed_at')),
                         default_branch=body.get('default_branch'))
            cache['activity_pending'] = {'ts': now, 'metrics': metrics, 'baselines': {}, 'unknown_reasons': {}}
            cache['phase'] = 'pulls'
            return SourceResult(state=cache, next_due=now + 2)
        metrics, reasons = pending['metrics'], pending['unknown_reasons']
        phase = cache['phase']
        if phase == 'pulls':
            body, headers = _get(net, API + '/repos/' + repo + '/pulls?state=open&per_page=1')
            metrics['open_prs'] = pulls_count(body, headers, repo, cache.get('repo_id'))
            cache['phase'] = 'stats'
        elif phase == 'stats':
            # Every attempted participation request (including 202) consumes its
            # hourly slot. A restart retains this due time; never retry on each poll.
            due = cache.get('stats_due', 0)
            if params.get('activity') and not now < due <= now + 3600:
                value, baseline, reason = None, None, 'Commit stats unavailable'
                try:
                    body, _ = _get(net, API + '/repos/' + repo + '/stats/participation')
                    weeks = body.get('all') if isinstance(body, dict) else None
                    if isinstance(weeks, list) and len(weeks) >= 13:
                        counts = [_count(v) for v in weeks[-13:]]
                        value, baseline, reason = counts[-1], math.fsum(counts[:-1]) / 12, None
                    elif body == {}:
                        reason = 'GitHub is still computing commit stats'
                except (Deferred, _TokenUnavailable):
                    raise
                except SourceError as exc:
                    reason = ('GitHub is still computing commit stats' if exc.status == 202
                              else 'Commit stats unavailable')
                cache.update(stats_due=now + 3600, commits_week=value, commits_baseline=baseline, commits_reason=reason)
                cache['phase'] = 'ci'
                return SourceResult(state=cache, next_due=now + 2)
            cache['phase'] = 'ci'
        if cache['phase'] == 'stats':
            # Skip the scheduling-only phase when stats are cached/off.
            if params.get('activity') and cache.get('stats_due', 0) <= now:
                return SourceResult(state=cache, next_due=now + 2)
            cache['phase'] = 'ci'
        if cache['phase'] == 'ci' and params.get('ci'):
            # Never make two requests in an invocation (repo/PR/Actions share a
            # two-second host gate). Missing branch means unknown, not all branches.
            if phase == 'pulls':
                return SourceResult(state=cache, next_due=now + 2)
            branch = cache.get('default_branch')
            passing, running, reason = None, None, 'Default branch unavailable'
            if isinstance(branch, str) and 0 < len(branch) <= 255:
                reason = 'CI status unavailable'
                try:
                    body, _ = _get(net, API + '/repos/' + repo + '/actions/runs?' + urlencode({'branch': branch, 'per_page': 1}))
                    runs = body.get('workflow_runs') if isinstance(body, dict) else None
                    if isinstance(runs, list) and not runs:
                        reason = 'No CI runs on the default branch'
                    if isinstance(runs, list) and runs and isinstance(runs[0], dict):
                        status, conclusion = runs[0].get('status'), runs[0].get('conclusion')
                        running = 1 if status in ('queued', 'in_progress', 'waiting', 'pending', 'requested') else 0 if status == 'completed' else None
                        passing = (1 if conclusion == 'success' else 0 if conclusion in ('failure', 'cancelled', 'timed_out') else None) if status == 'completed' else None
                        reason = 'CI run is still running' if running else 'CI conclusion unavailable'
                except (Deferred, _TokenUnavailable):
                    raise
                except SourceError as exc:
                    reason = 'needs Actions read access' if exc.status in (403, 404) else 'CI status unavailable'
            metrics.update(ci_passing=passing, ci_running=running)
            for metric in ('ci_passing', 'ci_running'):
                if metrics[metric] is None:
                    reasons[metric] = reason
        if params.get('activity'):
            metrics.update(commits_week=cache.get('commits_week'), hours_since_push=None)
            if metrics['commits_week'] is None:
                reasons['commits_week'] = cache.get('commits_reason') or 'Commit stats unavailable'
            if _number(cache.get('commits_baseline')):
                pending['baselines']['commits_week'] = cache['commits_baseline']
            pending = self.current(pending, cache, now=pending['ts'])
        cache.pop('activity_pending', None)
        cache.pop('phase', None)
        return SourceResult(sample=pending, state=cache)

    def poll(self, definition, previous, state, *, now, net):
        try:
            params = definition['source']['params']
            repo = params['repo']
            if params.get('activity') is True or params.get('ci') is True:
                return self._activity_poll(definition, state, now=now, net=net)
            if not _REPO.fullmatch(repo) or '..' in repo.split('/')[1]:
                raise SourceError('Invalid approved GitHub repository.')
            cache = dict(state)
            pending = cache.get('pending')
            if (cache.get('repo') != repo or not isinstance(pending, dict)
                    or not _number(cache.get('pending_ts')) or not 0 <= now - cache['pending_ts'] <= STAGE_TTL):
                body, _ = _get(net, API + '/repos/' + repo)
                metrics = {name: _count(body.get(field)) for name, field in
                           [('stars', 'stargazers_count'), ('forks', 'forks_count'), ('open_issues', 'open_issues_count')]}
                return SourceResult(state={'repo': repo, 'repo_id': _count(body.get('id')), 'pending': metrics, 'pending_ts': now}, next_due=now + 2)
            body, headers = _get(net, API + '/repos/' + repo + '/pulls?state=open&per_page=1')
            metrics = {name: _count(pending[name]) for name in ('stars', 'forks', 'open_issues')}
            metrics['open_prs'] = pulls_count(body, headers, repo, cache.get('repo_id'))
            return SourceResult(sample={'ts': cache['pending_ts'], 'metrics': metrics, 'baselines': {}, 'unknown_reasons': {}}, state={})
        except (Deferred, _TokenUnavailable):
            raise
        except SourceError as exc:
            public = _public_error(exc)
            if exc.status in (301, 302, 303, 307, 308):
                raise SourceError('GitHub repository moved or was renamed. Update the approved repository.',
                                  status=public.status, retry_after=public.retry_after) from None
            if exc.status == 404:
                raise SourceError('GitHub repository not found or read access unavailable. Check the approved repository and token permissions.',
                                  status=public.status, retry_after=public.retry_after) from None
            raise public from None
        except Exception:
            raise SourceError('GitHub count is temporarily unavailable.') from None
