"""Today against yesterday for one metric. Display only: never feeds a score or an alert.

A count that follows a daily rhythm (people online, activity) reads badly against a
24-hour median, which mostly reports the time of day. The comparison that answers
"is this unusual right now?" is the same time one day earlier.
"""
from .engine import value_of

DAY = 86400
BUCKET = 1800        # one drawn point per half hour
MATCH = 2700         # "this time yesterday" means within 45 minutes of it


def _mean(values, integral):
    mean = sum(values) / len(values)
    return int(round(mean)) if integral else round(mean, 1)


def _buckets(pairs, start, integral):
    groups = {}
    for ts, value in pairs:
        groups.setdefault(int((ts - start) // BUCKET), []).append((ts, value))
    return [{'ts': int(round(sum(ts for ts, _ in group) / len(group))), 'value': _mean([v for _, v in group], integral)}
            for _, group in sorted(groups.items())]


def compute_trend(samples, metric, now, *, integral, latest=None):
    """Return the trend read model, or None when fewer than two points were measured.

    ``samples`` are stored samples covering at least the two days before the last
    measurement (older ones are ignored); pre-aggregated rows work the same way.
    ``latest`` is the exact last measurement ``(ts, value)`` when the caller has it.
    Gaps stay gaps: a bucket with no sample produces no point.
    """
    if not metric:
        return None
    pairs = sorted((s['ts'], value_of(s, metric)) for s in samples if isinstance(s.get('ts'), (int, float)))
    pairs = [(ts, value) for ts, value in pairs if value is not None and ts <= now]
    if not pairs or pairs[-1][0] < now - DAY:
        return None
    # The day ends at the last measurement, not at the wall clock: a pulse that has not
    # sampled for an hour still compares like with like, and the row says it is stale.
    if latest is not None and latest[1] is not None and pairs[-1][0] <= latest[0] <= now:
        latest_ts, latest = latest
    else:
        latest_ts, latest = pairs[-1]
    pairs = [(ts, value) for ts, value in pairs if ts >= latest_ts - 2 * DAY]
    today = [(ts, value) for ts, value in pairs if ts >= latest_ts - DAY]
    if len(today) < 2:
        return None
    points = _buckets(today, latest_ts - DAY, integral)
    if len(points) < 2:
        return None
    near = [value for ts, value in pairs if abs(ts - (latest_ts - DAY)) <= MATCH]
    yesterday = None
    if near:
        then = _mean(near, integral)
        yesterday = {'value': then, 'delta': latest - then if integral else round(latest - then, 1),
                     'ratio': round(latest / then, 4) if then > 0 else None}
    return {
        'metric': metric, 'window_seconds': DAY, 'bucket_seconds': BUCKET,
        'points': points,
        'previous': _buckets([(ts, value) for ts, value in pairs if ts < latest_ts - DAY], latest_ts - 2 * DAY, integral),
        'low': min(points, key=lambda p: p['value']), 'high': max(points, key=lambda p: p['value']),
        'latest': {'ts': latest_ts, 'value': latest},
        'yesterday': yesterday,
    }
