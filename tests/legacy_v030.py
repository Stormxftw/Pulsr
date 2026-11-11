"""FROZEN v0.3.0 movement oracle copied verbatim from a6269cc.

capsule_metric transcribes fill/scale from v0.3.0 desktop capsuleMetric,
including JS Math.round. Never share implementation with the new engine.
"""
import math
import statistics


def movement(current, history):
    """70 presence swing + 20 member change + 10 active voice; range 0–100."""
    prior = [s for s in history if current['ts'] - 86400 <= s['ts'] < current['ts']]
    result = {'score': 0.0, 'warming': not bool(prior), 'online_delta': None,
              'member_delta': None, 'baseline_online': None, 'baseline_samples': len(prior),
              'window_seconds': current['ts'] - min((s['ts'] for s in prior), default=current['ts']),
              'components': {'presence': 0.0, 'members': 0.0, 'voice': 0.0}}
    if not prior:
        return result
    online = [s['online'] for s in prior if s.get('online') is not None]
    members = [s for s in prior if s.get('members') is not None]
    if online and current.get('online') is not None:
        base = statistics.median(online)
        delta = current['online'] - base
        result.update(baseline_online=base, online_delta=delta)
        result['components']['presence'] = 70 * min(abs(delta) / max(base, 25) / .2, 1)
    if members and current.get('members') is not None:
        first = min(members, key=lambda s: s['ts'])['members']
        delta = current['members'] - first
        result['member_delta'] = delta
        result['components']['members'] = 20 * min(abs(delta) / max(first, 100) / .01, 1)
    if current.get('voice_channels') is not None:
        result['components']['voice'] = 10 * min(current['voice_channels'] / 5, 1)
    result['score'] = round(sum(result['components'].values()), 1)
    return result


def capsule_metric(current, metric):
    baseline, online = metric['baseline_online'], current.get('online')
    known = online is not None and baseline is not None and baseline > 0
    return {
        'fill': min(100, 50 * online / baseline) if known else None,
        'caption': (f'{math.floor(100 * online / baseline + 0.5)}% of usual' if known
                    else 'Not measured' if online is None else 'Learning baseline'),
    }
