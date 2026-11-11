"""Bounded, profile-local arrangement. No source calls, definitions or approvals.

validate/reconcile are pure. Persistence uses the store's cross-process SQLite
write lock solely as a mutex; layout.json is replaced atomically on the same disk.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

MAX_BYTES = 65536
MAX_ITEMS = 512
RESERVED = 'hermes-sessions'
ID = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}\Z')


class StaleLayout(ValueError):
    pass


def empty():
    return {'version': 1, 'groups': [], 'ungrouped': []}


def validate(value):
    """Reject malformed/duplicate refs, unsafe ids, depth and unknown properties."""
    if not isinstance(value, dict) or set(value) != {'version', 'groups', 'ungrouped'}:
        raise ValueError('Layout needs version, groups and ungrouped only.')
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('Unsupported layout version.')
    try:
        if len(json.dumps(value, ensure_ascii=False).encode('utf-8')) > MAX_BYTES:
            raise ValueError('Layout exceeds 64 KiB.')
    except (RecursionError, TypeError, UnicodeError):
        raise ValueError('Invalid layout encoding.') from None
    groups, pulses, count = set(), set(), [0]

    def items(rows, depth, reserved=False):
        if not isinstance(rows, list):
            raise ValueError('Layout children must be arrays.')
        for row in rows:
            count[0] += 1
            if count[0] > MAX_ITEMS or not isinstance(row, dict):
                raise ValueError('Too many layout items or invalid item.')
            if set(row) == {'pulse'}:
                pid = row['pulse']
                if not isinstance(pid, str) or not ID.fullmatch(pid) or pid in pulses:
                    raise ValueError('Invalid or repeated pulse reference.')
                if pid.startswith('session:') and not reserved:
                    raise ValueError('Sessions stay inside Hermes sessions.')
                if reserved and not pid.startswith('session:'):
                    raise ValueError('Hermes sessions contains sessions only.')
                pulses.add(pid)
            else:
                group(row, depth, reserved)

    def group(row, depth, parent_reserved=False):
        if depth > 1 or parent_reserved or set(row) != {'id', 'title', 'collapsed', 'children'}:
            raise ValueError('Only one level of subgroups is supported.')
        gid = row['id']
        if not isinstance(gid, str) or not ID.fullmatch(gid) or gid in groups or (gid == RESERVED and depth != 0):
            raise ValueError('Invalid or repeated group id.')
        if not isinstance(row['title'], str) or not row['title'].strip() or len(row['title']) > 80 or any(ord(c) < 32 for c in row['title']):
            raise ValueError('Group title must be 1–80 printable characters.')
        if type(row['collapsed']) is not bool:
            raise ValueError('Collapsed must be a boolean.')
        groups.add(gid)
        items(row['children'], depth + 1, gid == RESERVED)

    if not isinstance(value['groups'], list):
        raise ValueError('Groups must be an array.')
    for row in value['groups']:
        count[0] += 1
        if count[0] > MAX_ITEMS or not isinstance(row, dict):
            raise ValueError('Too many layout items or invalid group.')
        group(row, 0)
    # A subgroup cannot appear in ungrouped.
    items(value['ungrouped'], 2)
    return copy.deepcopy(value)


def reconcile(value, pulse_ids, *, show_sessions=False):
    out = validate(value)
    ids = list(dict.fromkeys(pulse_ids))
    live = set(ids)
    seen = set()
    def prune(rows):
        result = []
        for row in rows:
            if 'pulse' in row:
                if row['pulse'] in live:
                    result.append(row)
                    seen.add(row['pulse'])
            else:
                row['children'] = prune(row['children'])
                result.append(row)
        return result
    out['groups'] = [g for g in out['groups'] if g['id'] != RESERVED or show_sessions]
    for g in out['groups']:
        g['children'] = prune(g['children'])
    out['ungrouped'] = prune(out['ungrouped'])
    reserved = next((g for g in out['groups'] if g['id'] == RESERVED), None)
    if show_sessions and reserved is None:
        reserved = {'id': RESERVED, 'title': 'Hermes sessions', 'collapsed': False, 'children': []}
        out['groups'].append(reserved)
    for pid in ids:
        if pid not in seen and (not pid.startswith('session:') or show_sessions):
            if pid.startswith('session:'):
                assert reserved is not None
                reserved['children'].append({'pulse': pid})
            else:
                out['ungrouped'].append({'pulse': pid})
    return validate(out)


def _load(root):
    target = Path(root) / 'layout.json'
    try:
        before = target.lstat()
    except FileNotFoundError:
        return empty()
    if target.is_symlink() or not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
        raise ValueError('Local layout is not a bounded regular file.')
    fd = os.open(target, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError('Local layout changed during read.')
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or target.is_symlink():
        raise ValueError('Local layout exceeds 64 KiB.')
    try:
        return validate(json.loads(data))
    except (UnicodeError, RecursionError):
        raise ValueError('Invalid local layout.') from None


def _envelope(layout):
    data = json.dumps(layout, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return {'layout': layout, 'revision': hashlib.sha256(data).hexdigest()}


def read(store, pulse_ids, *, show_sessions=False):
    return {**_envelope(reconcile(_load(store.root), pulse_ids, show_sessions=show_sessions)),
            'customized': (Path(store.root) / 'layout.json').exists()}


def write(store, layout, revision, pulse_ids, *, show_sessions=False):
    value = reconcile(layout, pulse_ids, show_sessions=show_sessions)
    with store.transaction():
        current = read(store, pulse_ids, show_sessions=show_sessions)
        if revision != current['revision']:
            raise StaleLayout('Arrangement changed. Refresh and try again.')
        data = json.dumps(value, ensure_ascii=False).encode('utf-8')
        if len(data) > MAX_BYTES:
            raise ValueError('Layout exceeds 64 KiB.')
        fd, name = tempfile.mkstemp(prefix='layout-', suffix='.tmp', dir=store.root)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, Path(store.root) / 'layout.json')
        finally:
            if os.path.exists(name):
                os.unlink(name)
    return {**_envelope(value), 'customized': True}


def inventory(pulse):
    """Read approved ids only, never status(poll=True). Optional sessions seam."""
    from contextlib import closing
    with closing(pulse.store.db()) as db:
        ids = [row['id'] for row in db.execute('SELECT id FROM pulses ORDER BY created_ts,id')]
    # Optional sibling feature; official hooks supply these ephemeral ids. No
    # status/poll, session DB, or network is consulted by arrangement itself.
    try:
        from . import sessions
    except ImportError:
        return ids, False
    state = sessions.status(pulse)
    if state.get('show_sessions') is True:
        ids.extend(p['id'] for p in state.get('sessions', []))
        return ids, True
    return ids, False
