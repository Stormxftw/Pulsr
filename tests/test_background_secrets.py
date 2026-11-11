"""Multiplexed background credentials use only the documented Hermes boundary."""
import builtins
from contextvars import ContextVar
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from pulse_rings import background
from pulse_rings.engine import Engine
from pulse_rings.sources.base import SourceError
from pulse_rings.sources.github import GitHubRepo, GitHubSearch
from pulse_rings.spec import normalize


MESSAGE = ('GitHub token unavailable to background collection; '
           'open the Pulses pane or restart Hermes.')


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr('pulse_rings.net.fetch_bytes',
                        lambda *a, **k: pytest.fail('real network forbidden'))


@pytest.fixture
def secret_scope(monkeypatch):
    """No real credential reads: emulate multiplexing's fail-closed contract."""
    scope = ContextVar[tuple | None]('wp18-secret-scope', default=None)
    mappings, builds, installs = {}, [], []

    class UnscopedSecretError(RuntimeError):
        pass

    def get_secret(name):
        bound = scope.get()
        if bound is None:
            raise UnscopedSecretError('PRIVATE_EXCEPTION_SENTINEL')
        return bound[0].get(name)

    def build(home):
        builds.append(home)
        return dict(mappings.get(str(home), {}))

    def install(mapping, *, profile_home=None):
        installs.append(profile_home)
        return scope.set((mapping, profile_home))

    module = SimpleNamespace(get_secret=get_secret,
        UnscopedSecretError=UnscopedSecretError,
        build_profile_secret_scope=build, set_secret_scope=install,
        reset_secret_scope=scope.reset)
    original = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'agent.secret_scope':
            return module
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    return SimpleNamespace(module=module, scope=scope, mappings=mappings,
                           builds=builds, installs=installs)


def definition(kind='repo'):
    params = {'repo': 'private-owner/private-repo'}
    if kind == 'search':
        params['type'] = 'pr'
    return normalize({'pulse': 1, 'title': 'Private repository',
                      'icon': {'brand': 'github'},
                      'source': {'kind': 'github.' + kind, 'params': params}})


def bind(root):
    ctx = SimpleNamespace(get_config=lambda key, default=None:
                          True if key == 'background_collection' else default)
    background.bind_context(ctx, root=root, start=False)


def github_engine(root, calls, secret_scope, *, kind='repo'):
    now = [1794000000.0]

    def fetch(url, **kwargs):
        # This fake represents a private repository that requires its own token.
        home = root.parent.parent
        expected = secret_scope.mappings[str(home)].get('PULSE_RINGS_GITHUB_TOKEN')
        assert kwargs['headers'].get('Authorization') == ('Bearer ' + expected if expected else None)
        assert secret_scope.scope.get()[1] == home
        calls.append((url, kwargs))
        body = ({'total_count': 3, 'incomplete_results': False} if kind == 'search'
                else [] if '/pulls?' in url else
                {'id': 42, 'stargazers_count': 3, 'forks_count': 2, 'open_issues_count': 1})
        return json.dumps(body).encode(), {'content-type': 'application/json'}

    engine = Engine(root, clock=lambda: now[0], jitter=lambda: 0)
    engine.net.bytes = lambda url, **kwargs: engine.net.call('api.github.com', lambda: fetch(url, **kwargs))
    engine.activate(definition(kind))
    return engine, now


@pytest.mark.parametrize('kind', ['repo', 'search'])
def test_background_tick_authenticates_and_refreshes_registering_profile(tmp_path, monkeypatch, secret_scope, kind):
    # Root identity is authoritative even when a later request serves another home.
    root = tmp_path / 'profile-a' / 'plugin-data' / 'pulse-rings'
    home = root.parent.parent
    secret_scope.mappings[str(home)] = {'PULSE_RINGS_GITHUB_TOKEN': 'PRIVATE_A'}
    bind(root)
    monkeypatch.setattr('hermes_constants.get_hermes_home', lambda: tmp_path / 'request-b')
    calls = []
    engine, now = github_engine(root, calls, secret_scope, kind=kind)
    worker = background.Collector(engine)
    try:
        assert worker.tick()
        assert len(calls) == 1
        assert calls[0][1]['headers']['Authorization'] == 'Bearer PRIVATE_A'
        assert secret_scope.scope.get() is None
        # Rebuild per tick: added/rotated/revoked tokens must not stay frozen.
        secret_scope.mappings[str(home)]['PULSE_RINGS_GITHUB_TOKEN'] = 'ROTATED_A'
        now[0] += 5
        assert worker.tick()
        assert calls[-1][1]['headers']['Authorization'] == 'Bearer ROTATED_A'
        assert secret_scope.builds == [home, home]
        assert secret_scope.installs == [home, home]
        assert secret_scope.scope.get() is None
        assert not engine.store.rows()[0]['error']
        assert b'PRIVATE_A' not in (root / 'pulse.sqlite3').read_bytes()
        assert b'ROTATED_A' not in (root / 'pulse.sqlite3').read_bytes()
    finally:
        worker.stop()
        background.unbind_context(root)


@pytest.mark.parametrize('kind', ['repo', 'search'])
def test_unscoped_secret_has_clear_sanitized_source_error(secret_scope, kind):
    net = SimpleNamespace(bytes=lambda *a, **k: pytest.fail('unscoped request'))
    source = GitHubRepo() if kind == 'repo' else GitHubSearch()
    with pytest.raises(SourceError) as exc:
        source.poll(definition(kind), None, {}, now=1794000000, net=net)
    assert str(exc.value) == MESSAGE
    assert 'PRIVATE_EXCEPTION_SENTINEL' not in str(exc.value)
    assert 'temporarily unavailable' not in str(exc.value)


@pytest.mark.parametrize('raises', [False, True])
def test_scope_restores_caller_after_tick_or_exception(tmp_path, monkeypatch, secret_scope, raises):
    root = tmp_path / 'profile-a' / 'plugin-data' / 'pulse-rings'
    home = root.parent.parent
    secret_scope.mappings[str(home)] = {'PULSE_RINGS_GITHUB_TOKEN': 'PRIVATE_A'}
    bind(root)
    engine, _ = github_engine(root, [], secret_scope)
    worker = background.Collector(engine)
    caller = ({'PULSE_RINGS_GITHUB_TOKEN': 'CALLER_B'}, tmp_path / 'profile-b')
    token = secret_scope.scope.set(caller)

    def poll(**kwargs):
        assert secret_scope.scope.get() == (secret_scope.mappings[str(home)], home)
        if raises:
            raise RuntimeError('injected tick failure')
        return True

    monkeypatch.setattr(engine, 'poll_one_due', poll)
    try:
        if raises:
            with pytest.raises(RuntimeError, match='injected tick failure'):
                worker.tick()
        else:
            assert worker.tick()
        assert secret_scope.scope.get() is caller
    finally:
        secret_scope.scope.reset(token)
        worker.stop()
        background.unbind_context(root)


def test_two_profile_ticks_do_not_share_secrets(tmp_path, secret_scope):
    workers, calls = [], []
    try:
        for name in ('a', 'b'):
            root = tmp_path / name / 'plugin-data' / 'pulse-rings'
            home = root.parent.parent
            secret_scope.mappings[str(home)] = {'PULSE_RINGS_GITHUB_TOKEN': 'PRIVATE_' + name}
            bind(root)
            engine, _ = github_engine(root, calls, secret_scope)
            workers.append(background.Collector(engine))
        for worker in workers:
            assert worker.tick()
            assert secret_scope.scope.get() is None
        assert [kwargs['headers']['Authorization'] for _, kwargs in calls] == ['Bearer PRIVATE_a', 'Bearer PRIVATE_b']
    finally:
        for worker in workers:
            worker.stop()
            background.unbind_context(worker.engine.root)


def test_daemon_tick_binds_scope_and_resets_in_worker_context(tmp_path, monkeypatch, secret_scope):
    import threading
    root = tmp_path / 'a' / 'plugin-data' / 'pulse-rings'
    home = root.parent.parent
    secret_scope.mappings[str(home)] = {'PULSE_RINGS_GITHUB_TOKEN': 'PRIVATE_A'}
    bind(root)
    calls, after = [], []
    engine, _ = github_engine(root, calls, secret_scope)
    worker = background.Collector(engine)
    finished = threading.Event()
    tick = worker.tick

    def once():
        try:
            tick()
        finally:
            after.append(secret_scope.scope.get())
            worker.stop_event.set()
            finished.set()

    monkeypatch.setattr(worker, 'tick', once)
    try:
        worker.start()
        assert finished.wait(5)
        assert worker.stop()
        assert len(calls) == 1
        assert after == [None]
        assert secret_scope.scope.get() is None
    finally:
        worker.stop()
        background.unbind_context(root)


@pytest.mark.parametrize('missing', ['module', 'build_profile_secret_scope', 'set_secret_scope', 'reset_secret_scope'])
def test_old_hermes_without_scope_binding_apis_keeps_current_behavior(tmp_path, monkeypatch, secret_scope, missing):
    if missing == 'module':
        original = builtins.__import__

        def unavailable(name, *args, **kwargs):
            if name == 'agent.secret_scope':
                raise ImportError('old Hermes')
            return original(name, *args, **kwargs)

        monkeypatch.setattr(builtins, '__import__', unavailable)
    else:
        delattr(secret_scope.module, missing)
        monkeypatch.setattr(secret_scope.module, 'get_secret', lambda key: 'LEGACY_TOKEN')
        delattr(secret_scope.module, 'UnscopedSecretError')
    root = tmp_path / 'a' / 'plugin-data' / 'pulse-rings'
    bind(root)
    calls = []

    def fetch(url, **kwargs):
        calls.append(kwargs['headers'].get('Authorization'))
        return b'{"id":42,"stargazers_count":3,"forks_count":2,"open_issues_count":1}', {'content-type': 'application/json'}

    engine = Engine(root, clock=lambda: 1794000000, jitter=lambda: 0)
    engine.net.bytes = lambda url, **kwargs: engine.net.call('api.github.com', lambda: fetch(url, **kwargs))
    engine.activate(definition())
    worker = background.Collector(engine)
    try:
        assert worker.tick()
        assert calls == [None if missing == 'module' else 'Bearer LEGACY_TOKEN']
        assert secret_scope.builds == []
        assert secret_scope.scope.get() is None
    finally:
        worker.stop()
        background.unbind_context(root)


def test_late_added_and_removed_token_without_registration_or_restart(tmp_path, secret_scope):
    root = tmp_path / 'a' / 'plugin-data' / 'pulse-rings'
    home = root.parent.parent
    secret_scope.mappings[str(home)] = {}
    calls = []
    engine, now = github_engine(root, calls, secret_scope)
    worker = background.Collector(engine, enabled=lambda: True)
    try:
        assert worker.tick()
        assert 'Authorization' not in calls[-1][1]['headers']
        secret_scope.mappings[str(home)]['PULSE_RINGS_GITHUB_TOKEN'] = 'ADDED_A'
        now[0] += 5
        assert worker.tick()
        assert calls[-1][1]['headers']['Authorization'] == 'Bearer ADDED_A'
        secret_scope.mappings[str(home)].clear()
        now[0] += 3600
        assert worker.tick()
        assert 'Authorization' not in calls[-1][1]['headers']
        assert secret_scope.scope.get() is None
    finally:
        worker.stop()


def test_custom_root_captures_home_at_registration(tmp_path, monkeypatch, secret_scope):
    home, root = tmp_path / 'owner', tmp_path / 'custom-store'
    secret_scope.mappings[str(home)] = {'PULSE_RINGS_GITHUB_TOKEN': 'OWNER_TOKEN'}
    monkeypatch.setattr('hermes_constants.get_hermes_home', lambda: home)
    bind(root)
    monkeypatch.setattr('hermes_constants.get_hermes_home', lambda: tmp_path / 'viewer')
    engine = Engine(root, clock=lambda: 1794000000)
    engine.activate(definition())

    def poll(**kwargs):
        assert secret_scope.module.get_secret('PULSE_RINGS_GITHUB_TOKEN') == 'OWNER_TOKEN'
        assert secret_scope.scope.get()[1] == home
        return True

    monkeypatch.setattr(engine, 'poll_one_due', poll)
    worker = background.Collector(engine)
    try:
        assert worker.tick()
        assert secret_scope.builds == [home]
        assert secret_scope.scope.get() is None
    finally:
        worker.stop()
        background.unbind_context(root)


@pytest.mark.parametrize('bound_caller', [False, True])
def test_scope_resets_on_tick_exception(tmp_path, monkeypatch, secret_scope, bound_caller):
    root = tmp_path / 'a' / 'plugin-data' / 'pulse-rings'
    home = root.parent.parent
    secret_scope.mappings[str(home)] = {}
    engine, _ = github_engine(root, [], secret_scope)
    worker = background.Collector(engine, enabled=lambda: True)
    caller = ({'PULSE_RINGS_GITHUB_TOKEN': 'CALLER'}, tmp_path / 'b') if bound_caller else None
    token = secret_scope.scope.set(caller)

    def broken(**kwargs):
        assert secret_scope.scope.get() == ({}, home)
        raise RuntimeError('injected failure')

    monkeypatch.setattr(engine, 'poll_one_due', broken)
    try:
        with pytest.raises(RuntimeError, match='injected failure'):
            worker.tick()
        assert secret_scope.scope.get() is caller
    finally:
        secret_scope.scope.reset(token)
        worker.stop()


@pytest.mark.parametrize('bad_token', ['bad token', 'bad\r\nheader', 'x' * 1025, 123])
def test_invalid_token_still_refused_before_network(secret_scope, bad_token):
    token = secret_scope.scope.set(({'PULSE_RINGS_GITHUB_TOKEN': bad_token}, None))
    net = SimpleNamespace(bytes=lambda *a, **k: pytest.fail('invalid credential egress'))
    try:
        with pytest.raises(SourceError):
            GitHubRepo().poll(definition(), None, {}, now=1794000000, net=net)
    finally:
        secret_scope.scope.reset(token)


def test_documented_scope_api_from_selected_hermes_source(tmp_path, monkeypatch):
    """Exercise real host build/set/get/reset, with all secret providers faked."""
    source = os.environ.get('HERMES_SOURCE')
    if not source:
        pytest.skip('Set HERMES_SOURCE to check the real Hermes secret-scope API')
    assert source is not None
    spec = importlib.util.spec_from_file_location('wp18_host_secret_scope', Path(source) / 'agent/secret_scope.py')
    assert spec is not None and spec.loader is not None
    host = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(host)
    monkeypatch.setattr(host, '_MULTIPLEX_ACTIVE', True)
    home = tmp_path / 'a'
    values = {'PULSE_RINGS_GITHUB_TOKEN': 'HOST_SCOPE_TOKEN'}
    reads = []

    def fake_load(path):
        assert path == home / '.env'
        reads.append(path)
        return dict(values)

    monkeypatch.setattr(host, 'load_env_file', fake_load)
    monkeypatch.setitem(sys.modules, 'hermes_cli.env_loader',
                        SimpleNamespace(get_secret_source_values=lambda home: {}))
    monkeypatch.setitem(sys.modules, 'gateway.config_loader',
                        SimpleNamespace(bridged_allow_all_users=lambda: None))
    monkeypatch.setitem(sys.modules, 'hermes_cli.managed_scope',
                        SimpleNamespace(load_managed_env=lambda: {}))
    original = builtins.__import__

    def use_host(name, *args, **kwargs):
        if name == 'agent.secret_scope':
            return host
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', use_host)
    root = home / 'plugin-data' / 'pulse-rings'
    bind(root)
    now = [1794000000.0]
    engine = Engine(root, clock=lambda: now[0], jitter=lambda: 0)
    engine.activate(definition())
    calls = []

    def fetch(url, **kwargs):
        assert kwargs['headers']['Authorization'] == 'Bearer ' + values['PULSE_RINGS_GITHUB_TOKEN']
        assert host.current_secret_scope_home() == str(home)
        calls.append(url)
        return b'{"id":42,"stargazers_count":3,"forks_count":2,"open_issues_count":1}', {'content-type': 'application/json'}

    # Keep the real Net's host validation, pacing and header checks as well.
    monkeypatch.setattr('pulse_rings.net.fetch_bytes', fetch)
    worker = background.Collector(engine)
    try:
        with pytest.raises(host.UnscopedSecretError):
            host.get_secret('PULSE_RINGS_GITHUB_TOKEN')
        assert worker.tick()
        assert host.current_secret_scope() is None
        values['PULSE_RINGS_GITHUB_TOKEN'] = 'HOST_ROTATED_TOKEN'
        now[0] += 3600
        assert worker.tick()
        assert host.current_secret_scope() is None
        assert len(calls) == 2 and reads == [home / '.env'] * 2
        with pytest.raises(SourceError, match=MESSAGE):
            GitHubRepo().poll(definition(), None, {}, now=now[0], net=engine.net)
    finally:
        worker.stop()
        background.unbind_context(root)
