"""The Discord server card: member growth and people in voice across the last day.

Display only: nothing here feeds a score, an alert or a stored sample. Member growth is read
from the pulse's own history. People in voice come from the counts-only log the source keeps
of its public-widget checks, so a server whose widget is off has no voice figures at all, and
a server whose public list is full has a minimum, not a total.
"""
from .sources.discord import WIDGET_MEMBER_CAP, voice_summary

DAY = 86400


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _members(current, rows, now):
    value = current.get('metrics', {}).get('members')
    value = value if _number(value) else None
    points = sorted((row['ts'], row['value']) for row in rows
                    if isinstance(row, dict) and _number(row.get('ts')) and _number(row.get('value'))
                    and now - DAY <= row['ts'] <= now)
    stamp = current.get('ts')
    if value is not None and _number(stamp) and points and points[-1][0] <= stamp <= now:
        # The exact last measurement ends the line, replacing a bucket mean taken at the same time.
        points = [point for point in points if point[0] < stamp] + [(stamp, value)]
    if len(points) < 2:
        return {'value': value, 'delta': None, 'span_seconds': 0, 'points': []}
    base = round(points[0][1])
    drawn = [{'ts': int(round(ts)), 'value': int(round(count)) - base} for ts, count in points]
    return {'value': value, 'delta': drawn[-1]['value'], 'span_seconds': int(round(points[-1][0] - points[0][0])), 'points': drawn}


def _voice(definition, state, now):
    summary = voice_summary(definition, state, now=now)
    if summary is None:
        return None
    log = state.get('voice_log')
    entries = [entry for entry in (log if isinstance(log, list) else [])
               if isinstance(entry, list) and len(entry) == 4 and all(_number(part) for part in entry)
               and now - DAY <= entry[0] <= now and entry[1] >= 0]
    entries.sort(key=lambda entry: entry[0])
    points = [{'ts': int(round(ts)), 'value': int(users)} for ts, users, _channels, _listed in entries]
    peak = max(points, key=lambda point: (point['value'], -point['ts'])) if points else None
    return {**summary, 'floor': any(entry[3] >= WIDGET_MEMBER_CAP for entry in entries), 'points': points, 'peak': peak}


def summarize(definition, current, state, member_rows, *, now):
    """What the server card draws. ``member_rows`` are bucketed ``members`` readings of the last day."""
    return {'members': _members(current or {}, member_rows or [], now), 'voice': _voice(definition, state or {}, now)}
