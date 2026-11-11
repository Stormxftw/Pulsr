"""Notification mode: what a notifications pulse shows, as one small read model.

Built from the latest sample and the adapter's own observation state. Counts and
times only: nothing here can carry a sender, a title or message text, because the
adapter never reads them. Display only: never feeds a score or an alert.
"""
import math

DAY = 86400
HOURS = 24


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _count(value):
    return int(value) if _number(value) and value >= 0 else None


def summarize(sample, state):
    """Return the summary for one desktop.notifications sample, or None before the first sample.

    ``waiting``  notifications still in Windows for the selected apps (None = not measured).
    ``reason``   why ``waiting`` is not measured, in the adapter's words.
    ``last_ts``  when the most recent one arrived, even if it has since been cleared.
    ``hour``/``day``  arrivals in the last hour / 24 hours, None until that window was watched in full.
    ``seen``/``since``  arrivals counted since watching began (at most a day back), for a part-watched day.
    ``marks``    arrivals per hour for the 24 hours ending at ``ts``, oldest first.
    """
    if not isinstance(sample, dict) or not _number(sample.get('ts')):
        return None
    end = sample['ts']
    metrics = sample.get('metrics') or {}
    state = state if isinstance(state, dict) else {}
    waiting = _count(metrics.get('waiting'))
    minutes = metrics.get('minutes_since_last')
    start = end - DAY
    watched = state.get('observed_since')
    since = max(start, watched) if _number(watched) and watched <= end else None
    arrivals = state.get('arrivals')
    marks = [0] * HOURS
    seen = 0
    for stamp in arrivals if isinstance(arrivals, list) else []:
        if not _number(stamp) or not start < stamp <= end:
            continue
        marks[min(HOURS - 1, int((stamp - start) // 3600))] += 1
        seen += 1
    return {
        'waiting': waiting,
        'reason': None if waiting is not None else (sample.get('unknown_reasons') or {}).get('waiting'),
        'last_ts': end - minutes * 60 if _number(minutes) and minutes >= 0 else None,
        'hour': _count(metrics.get('new_1h')),
        'day': _count(metrics.get('new_24h')),
        'seen': seen,
        'since': since,
        'complete': since is not None and since <= start,
        'marks': marks,
        'ts': end,
    }
