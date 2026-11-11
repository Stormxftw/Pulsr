"""Synthetic v0.3.0 import fixtures only; every source byte must remain unchanged."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from pulse_rings.migrate import DiscordPulseImporter, MigrationError
from pulse_rings.spec import normalize
from pulse_rings.store import Store

SCHEMA = (Path(__file__).parent / 'fixtures/migrate/v030.sql').read_text()
GUILDS = ['100000000000000001', '100000000000000002', '100000000000000003']
ICON = 'a' * 32
PNG = b'\x89PNG\r\n\x1a\nsynthetic-magic-only-fixture'


@pytest.fixture
def old(tmp_path):
    home = tmp_path / 'hermes'
    root = home / 'plugin-data/discord-pulse'
    root.mkdir(parents=True)
    with closing(sqlite3.connect(root / 'pulse.sqlite3')) as db, db:
        db.executescript(SCHEMA)
        for index, guild in enumerate(GUILDS):
            payload = {'id': guild, 'name': 'Synthetic ' + str(index), 'online': 4 + index,
                       'members': 100 + index, 'description': 'untrusted-sentinel', 'icon_hash': ICON}
            db.execute('INSERT INTO servers(id,code,payload) VALUES (?,?,?)',
                       (guild, ['FakeAlpha', 'FakeBeta', 'FakeGamma'][index], json.dumps(payload)))
            for step in range(index + 1):
                db.execute('INSERT INTO snapshots VALUES (?,?,?)',
                           (guild, 1000 + step * 600, json.dumps(payload)))
        db.execute("INSERT INTO gates VALUES ('discord',999999999)")
    (root / 'notes').mkdir()
    (root / 'notes' / (GUILDS[0] + '.md')).write_text('# Synthetic note\nNo real user data.\n', encoding='utf-8')
    (root / 'icons').mkdir()
    (root / 'icons' / (GUILDS[0] + '-' + ICON + '.image')).write_bytes(PNG)
    (root / 'icons' / (GUILDS[1] + '-' + ICON + '.image')).write_bytes(b'<svg onload="bad()"/>')
    return home, root


def hashes(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


def importer(tmp_path, old, **kwargs):
    home, _ = old
    return DiscordPulseImporter(Store(tmp_path / 'new'), hermes_home=home, clock=lambda: 3000, **kwargs)


def test_consent_plan_apply_samples_notes_icons_and_read_only_source(tmp_path, old, monkeypatch):
    _, source = old
    before = hashes(source)
    instance = importer(tmp_path, old)
    original = sqlite3.connect
    seen = []
    def connect(database, *args, **kwargs):
        if isinstance(database, str) and database.startswith('file:'):
            seen.append(database)
            assert 'mode=ro' in database and kwargs.get('uri') is True
        return original(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', connect)
    plan = instance.plan()
    assert plan['summary'] == 'Import 3 pulses · 6 samples · 1 note'
    assert plan['icons'] == 1 and plan['available'] and not plan['completed']
    assert len(plan['token']) == 64
    assert instance.store.rows() == [] and not (instance.store.root / 'notes').exists()
    with pytest.raises(MigrationError, match='consent'):
        instance.apply(token=plan['token'])
    result = instance.apply(consent=True, token=plan['token'])
    assert (result['pulses'], result['samples'], result['notes'], result['icons']) == (3, 6, 1, 1)
    rows = instance.store.rows()
    assert {r['id'] for r in rows} == {'discord-fakealpha', 'discord-fakebeta', 'discord-fakegamma'}
    for index, row in enumerate(rows):
        d = json.loads(row['definition'])
        assert d == normalize(d) and d['source']['kind'] == 'discord.invite'
        assert d['source']['params']['invite'] in ('FakeAlpha', 'FakeBeta', 'FakeGamma')
        assert row['approved_via'] == 'import'
        assert 'untrusted-sentinel' not in row['metadata']
        assert len(d['ring']['components']) == 3
        history = instance.store.history(row['id'])
        assert history and all(set(s['metrics']) == {'online', 'members'} for s in history)
        assert row['last_ok_ts'] == history[-1]['ts']
    assert (instance.store.root / 'notes/discord-fakealpha.md').read_bytes() == (source / 'notes' / (GUILDS[0] + '.md')).read_bytes()
    assert (instance.store.root / 'icons' / (GUILDS[0] + '-' + ICON + '.image')).read_bytes() == PNG
    assert not (instance.store.root / 'icons' / (GUILDS[1] + '-' + ICON + '.image')).exists()
    assert seen and hashes(source) == before
    with closing(instance.store.db()) as db:
        assert db.execute('SELECT count(*) FROM gates').fetchone()[0] == 0
    assert instance.plan()['completed']
    assert instance.offer() == {'available': False, 'completed': True}
    repeated = instance.apply(consent=True, token=plan['token'])
    assert repeated['pulses'] == repeated['samples'] == 0
    # Reopening preserves the one-time marker, even if a source server is added later.
    restarted = importer(tmp_path, old)
    assert restarted.plan()['completed']
    assert hashes(source) == before


def test_imported_pulse_has_generation_and_can_finish_poll(tmp_path, old):
    from pulse_rings.engine import Engine
    from pulse_rings.sources.base import SourceResult
    instance = importer(tmp_path, old)
    instance.apply(consent=True, token=instance.plan()['token'])
    # Reuse Store: no restart/schema reinitialization may repair missing feed rows.
    class Local:
        def poll(self, d, previous, state, *, now, net):
            assert previous is not None
            return SourceResult(sample={'ts': now, 'metrics': {'online': 99, 'members': 100}})
    e = Engine(instance.store.root, clock=lambda: 3001, adapters={'discord.invite': Local()})
    e.icon_resolver.resolve = lambda *a, **kw: None
    assert e.poll_one_due()
    assert e.store.history('discord-fakealpha')[-1]['metrics']['online'] == 99
    assert e.store.feed_rows('discord-fakealpha')['main']['generation']


def test_existing_ids_are_never_overwritten(tmp_path, old):
    instance = importer(tmp_path, old)
    d = normalize({'pulse': 1, 'id': 'discord-fakealpha', 'title': 'Keep me',
                   'source': {'kind': 'discord.invite', 'params': {'invite': 'AlreadyApproved'}}})
    instance.store.put_pulse(d, now=10, approved_via='rest')
    before = instance.store.rows()[0]
    plan = instance.plan()
    assert plan['pulses'] == 2 and plan['samples'] == 5 and plan['notes'] == 0
    assert plan['skipped_existing'] == 1
    instance.apply(consent=True, token=plan['token'])
    after = next(r for r in instance.store.rows() if r['id'] == before['id'])
    assert after == before
    assert not (instance.store.root / 'notes/discord-fakealpha.md').exists()


@pytest.mark.parametrize('ceiling,existing,expected', [(300, 23, 1), (15, 0, 1), (5, 0, 0)])
def test_cap_and_recurring_budget_admission(tmp_path, old, ceiling, existing, expected):
    instance = importer(tmp_path, old, ceiling=ceiling)
    for index in range(existing):
        instance.store.put_pulse(normalize({'pulse': 1, 'id': f'local-{index}', 'title': 'Local',
            'source': {'kind': 'hermes.activity', 'params': {}}}), now=1)
    plan = instance.plan()
    assert plan['pulses'] == expected
    instance.apply(consent=True, token=plan['token'])
    assert len(instance.store.rows()) == existing + expected


@pytest.mark.parametrize('mutation', ['source', 'note', 'destination'])
def test_stale_consent_card_fails_without_target_writes(tmp_path, old, mutation):
    instance = importer(tmp_path, old)
    plan = instance.plan()
    _, source = old
    if mutation == 'source':
        with closing(sqlite3.connect(source / 'pulse.sqlite3')) as db, db:
            db.execute("UPDATE servers SET code='ChangedInvite' WHERE id=?", (GUILDS[0],))
    elif mutation == 'note':
        (source / 'notes' / (GUILDS[0] + '.md')).write_text('Changed')
    else:
        instance.store.put_pulse(normalize({'pulse': 1, 'id': 'local-new', 'title': 'Local',
            'source': {'kind': 'hermes.activity', 'params': {}}}), now=1)
    before = instance.store.rows()
    with pytest.raises(MigrationError, match='changed'):
        instance.apply(consent=True, token=plan['token'])
    assert instance.store.rows() == before
    assert not instance.plan()['completed']


def test_corrupt_payload_bad_counts_orphans_and_path_traversal(tmp_path, old):
    _, root = old
    with closing(sqlite3.connect(root / 'pulse.sqlite3')) as db, db:
        db.execute('INSERT INTO servers(id,code,payload) VALUES (?,?,?)', ('../../escape', 'aa', '{}'))
        db.execute('INSERT INTO servers(id,code,payload) VALUES (?,?,?)', ('100000000000000099', 'bb', '{bad'))
        db.execute('INSERT INTO snapshots VALUES (?,?,?)', (GUILDS[0], 2400, '{"online":true,"members":NaN}'))
        db.execute('INSERT INTO snapshots VALUES (?,?,?)', (GUILDS[0], 2500, '{"online":true,"members":"12"}'))
        db.execute('INSERT INTO snapshots VALUES (?,?,?)', ('999999999999999999', 2500, '{"online":42}'))
    instance = importer(tmp_path, old)
    plan = instance.plan()
    assert plan['pulses'] == 3 and plan['samples'] == 7 and plan['skipped_invalid'] == 3
    instance.apply(consent=True, token=plan['token'])
    latest = instance.store.history('discord-fakealpha')[-1]
    assert latest['metrics'] == {'online': None, 'members': None}
    assert set(latest['unknown_reasons']) == {'online', 'members'}


def test_no_source_or_unsupported_schema_never_creates_old_data(tmp_path):
    home = tmp_path / 'home'
    instance = DiscordPulseImporter(Store(tmp_path / 'new'), hermes_home=home)
    plan = instance.plan()
    assert not plan['available'] and plan['pulses'] == 0
    assert not home.exists()
    with pytest.raises(MigrationError):
        instance.apply(consent=True, token=plan['token'])
    source = home / 'plugin-data/discord-pulse'
    source.mkdir(parents=True)
    with closing(sqlite3.connect(source / 'pulse.sqlite3')) as db:
        db.execute('CREATE TABLE alien(value)')
    before = hashes(source)
    with pytest.raises(MigrationError, match='schema'):
        instance.plan()
    assert hashes(source) == before


def test_source_wal_is_refused_rather_than_mutated_or_silently_ignored(tmp_path, old):
    _, root = old
    # Simulates an active/checkpoint-pending source without running its plugin.
    (root / 'pulse.sqlite3-wal').write_bytes(b'pending-source-wal')
    before = hashes(root)
    instance = importer(tmp_path, old)
    with pytest.raises(MigrationError, match='WAL'):
        instance.plan()
    assert hashes(root) == before


def test_existing_notes_icons_preserved_and_unsafe_copy_paths_refused(tmp_path, old, monkeypatch):
    instance = importer(tmp_path, old)
    (instance.store.root / 'notes').mkdir()
    (instance.store.root / 'notes/discord-fakealpha.md').write_text('Existing human note')
    plan = instance.plan()
    assert plan['notes'] == 0
    instance.apply(consent=True, token=plan['token'])
    assert (instance.store.root / 'notes/discord-fakealpha.md').read_text() == 'Existing human note'


def test_target_failure_rolls_back_pulses_marker_and_copies(tmp_path, old, monkeypatch):
    instance = importer(tmp_path, old)
    plan = instance.plan()
    original = instance._copy
    count = [0]
    def broken(*args):
        count[0] += 1
        if count[0] == 2:
            raise OSError('sentinel local detail')
        return original(*args)
    monkeypatch.setattr(instance, '_copy', broken)
    with pytest.raises(MigrationError) as error:
        instance.apply(consent=True, token=plan['token'])
    assert 'sentinel' not in str(error.value)
    assert not instance.store.rows() and not instance.plan()['completed']
    assert not list((instance.store.root / 'notes').glob('*.md'))


def test_banner_probe_never_opens_source_and_defaults_are_profile_aware(tmp_path, old, monkeypatch):
    import builtins
    from types import SimpleNamespace
    home, _ = old
    instance = importer(tmp_path, old)
    monkeypatch.setattr(instance, '_source_rows', lambda: pytest.fail('Banner read old database'))
    assert instance.offer() == {'available': True, 'completed': False}
    original = builtins.__import__
    monkeypatch.setattr(builtins, '__import__', lambda name, *a, **k:
        SimpleNamespace(get_hermes_home=lambda: home) if name == 'hermes_constants' else original(name, *a, **k))
    resolved = DiscordPulseImporter(instance.store)
    assert resolved.source == home / 'plugin-data/discord-pulse'


def test_destination_cannot_be_the_source_or_a_child(tmp_path, old):
    home, source = old
    with pytest.raises(MigrationError, match='destination'):
        DiscordPulseImporter(Store(source / 'child'), hermes_home=home)


def test_exclusive_create_race_preserves_other_writers_file(tmp_path, old, monkeypatch):
    instance = importer(tmp_path, old)
    target = instance.store.root / 'notes/race.md'
    target.parent.mkdir()
    original = Path.open
    def racing(path, mode='r', *args, **kwargs):
        if path == target and mode == 'xb':
            with original(path, 'wb') as stream:
                stream.write(b'Other human note')
        return original(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', racing)
    with pytest.raises(FileExistsError):
        instance._copy(Path('notes/race.md'), b'Import note')
    assert target.read_bytes() == b'Other human note'


def test_simultaneous_imports_and_same_plan_are_idempotent(tmp_path, old):
    from concurrent.futures import ThreadPoolExecutor
    instance = importer(tmp_path, old)
    token = instance.plan()['token']
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: instance.apply(consent=True, token=token), range(2)))
    assert sorted(result['pulses'] for result in results) == [0, 3]
    assert len(instance.store.rows()) == 3
    assert sum(len(instance.store.history(row['id'])) for row in instance.store.rows()) == 6


def test_invalid_allocation_fails_closed_and_case_colliding_slugs_stay_distinct(tmp_path, old):
    _, root = old
    with closing(sqlite3.connect(root / 'pulse.sqlite3')) as db, db:
        db.execute("UPDATE servers SET code='fakealpha' WHERE id=?", (GUILDS[1],))
    instance = importer(tmp_path, old)
    plan = instance.plan()
    assert len(set(plan['ids'])) == 3
    assert all(len(pulse_id) <= 48 for pulse_id in plan['ids'])
    instance.store.put_pulse(normalize({'pulse': 1, 'id': 'local-existing', 'title': 'Local',
        'source': {'kind': 'hermes.activity', 'params': {}}}), now=1)
    with instance.store.transaction() as db:
        db.execute("UPDATE pulses SET budget=NULL WHERE id='local-existing'")
    blocked = instance.plan()
    assert blocked['pulses'] == 0 and blocked['skipped_admission'] == 3


def test_documented_human_route_patch_executes_against_real_importer(tmp_path, old, monkeypatch):
    """Exercise the exact handoff patch without editing the parent's route module."""
    import importlib
    import re
    import sys
    from types import SimpleNamespace
    from fastapi import APIRouter, Depends, FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from pydantic import BaseModel, ConfigDict, Field, StrictBool
    from pulse_rings.engine import Engine
    home, _ = old
    monkeypatch.setitem(sys.modules, 'hermes_constants', SimpleNamespace(get_hermes_home=lambda: home))
    engine = Engine(tmp_path / 'new', clock=lambda: 3000)
    context = {'importlib': importlib, 'router': APIRouter(), 'Depends': Depends,
        'get_pulse': lambda: engine, 'BaseModel': BaseModel, 'ConfigDict': ConfigDict,
        'Field': Field, 'StrictBool': StrictBool, 'HTTPException': HTTPException}
    doc = (Path(__file__).parents[1] / 'pulse_rings/WP6-INTEGRATION.md').read_text(encoding='utf-8')
    route = next(block for block in re.findall(r'```python\n(.*?)```', doc, flags=re.S)
                 if block.startswith('def discord_importer'))
    exec(compile(route, 'WP6-INTEGRATION.md:human-routes', 'exec'), context)
    app = FastAPI()
    app.include_router(context['router'])
    with TestClient(app) as client:
        endpoint = '/migrate/discord-pulse'
        plan = client.get(endpoint)
        assert plan.status_code == 200 and plan.json()['pulses'] == 3
        token = plan.json()['token']
        assert not engine.store.rows()
        assert client.post(endpoint, json={}).status_code == 422
        assert client.post(endpoint, json={'consent': 'true', 'token': token}).status_code == 422
        assert client.post(endpoint, json={'consent': True, 'token': token, 'source': '/other'}).status_code == 422
        assert client.post(endpoint, json={'consent': False, 'token': token}).status_code == 400
        assert client.post(endpoint, json={'consent': True, 'token': '0' * 64}).status_code == 409
        assert not engine.store.rows()
        receipt = client.post(endpoint, json={'consent': True, 'token': token})
        assert receipt.status_code == 200 and receipt.json()['completed']
        assert receipt.json()['pulses'] == 3
        assert client.get(endpoint).json()['completed']
        assert {row['id'] for row in engine.status(poll=False)['pulses']} == set(plan.json()['ids'])
