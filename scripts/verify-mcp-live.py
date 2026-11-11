"""Real Hermes registry/PluginContext + stdio MCP verification, never a live home.

Use Hermes's Python (MCP SDK and core deps), --hermes-root CHECKOUT --output JSON.
The parent process creates a throwaway scratch home, copies this worktree there,
and spawns an isolated worker. There are no fake registry/dispatch/adapter seams.
"""
import argparse
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def worker(args):
    import faulthandler
    import jsonschema  # Exercise the SDK's real structured-result validator before discovery.
    faulthandler.dump_traceback_later(45, repeat=True)
    sys.path.insert(0, str(Path(args.hermes_root).resolve()))
    home = Path(os.environ['HERMES_HOME'])
    plugin = home / 'plugins/pulse-rings'
    marker = home / 'WRITE_TOOL_MUST_NOT_RUN'
    config = ('plugins:\n  enabled: [pulse-rings]\nmcp_servers:\n  probe:\n'
              f'    command: {json.dumps(Path(sys.executable).as_posix())}\n'
              f'    args: [{json.dumps((plugin / "tests/fixtures/mcp/server.py").as_posix())}, {json.dumps(marker.as_posix())}]\n'
              '    trust: untrusted\n    connect_timeout: 30\n'
              '    sampling:\n      enabled: false\n')
    config += '  priced:\n' + config.split('  probe:\n', 1)[1] + '    tool_costs:\n      read_metrics: 1\n    spend_limit: 1\n'
    (home / 'config.yaml').write_text(config, encoding='utf-8')
    from hermes_cli.plugins import discover_plugins
    from tools.mcp_tool_discovery import discover_mcp_tools
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers
    from tools.registry import registry
    report = {'ok': False, 'home': str(home), 'source': str(ROOT), 'steps': [],
              'python': sys.executable, 'mcp_sdk': importlib.metadata.version('mcp'),
              'lazy_installs_disabled': os.getenv('HERMES_DISABLE_LAZY_INSTALLS') == '1'}
    def check(name, okay, **details):
        report['steps'].append({'name': name, 'ok': bool(okay), **details})
        assert okay, name + ': ' + json.dumps(details)
    prompt_attempts = []
    # Observe forbidden terminal input, NOT tool dispatch or its result.
    import builtins
    original_input = builtins.input
    def forbidden_input(*a, **kw):
        prompt_attempts.append(True)
        raise AssertionError('Background call attempted a terminal prompt')
    builtins.input = forbidden_input
    try:
        print('discover plugins', flush=True)
        discover_plugins(force=True)
        print('discover mcp', flush=True)
        names = discover_mcp_tools()
        check('real_mcp_discovery', 'mcp__probe__read_metrics' in names, tools=names)
        schema = registry.get_entry('mcp__probe__read_metrics').schema
        check('hint_not_in_public_schema', 'readOnlyHint' not in json.dumps(schema))
        spec = importlib.util.spec_from_file_location('pulse_integration_routes', plugin / 'dashboard/plugin_api.py')
        routes = importlib.util.module_from_spec(spec); spec.loader.exec_module(routes)
        e = routes.get_pulse()
        clock = [time.time()]
        e.clock = e.net.clock = lambda: clock[0]
        e.jitter = lambda: 0
        definition = {'pulse': 1, 'title': 'MCP integration', 'source': {'kind': 'mcp.tool', 'params': {
            'server': 'probe', 'tool': 'read_metrics', 'args': {'offset': 3}, 'metrics': {'count': '/count', 'score': '/nested/score'}}},
            'ring': {'components': [{'metric': 'score', 'weight': 100, 'type': 'level', 'full_at': 100}]},
            'capsule': {'metric': 'count', 'label': '{value} items', 'fill': {'full_at': 100}}}
        raw = registry.dispatch('pulse_rings_propose', {'definition': definition})
        draft = json.loads(raw)
        check('real_plugin_agent_proposal', draft.get('status') == 'pending', result=draft)
        check('agent_context_binding', draft['mcp']['read_only'] is True)
        check('zero_preview_calls', draft['preview_calls'] == 0 and draft['preview_state'] == 'after_approval')
        check('dashboard_context_binding', e.draft(draft['draft_id'])['mcp']['read_only'] is True)
        routes.approve(draft['draft_id'], routes.DecisionBody(confirm=True), e)
        # No grant yet: actual public host method refuses without dispatch.
        module = routes.builder_module(e, 'builder_mcp')
        ctx = module.mcp_access.binding_for(e.root)[0]
        try:
            ctx.call_mcp('probe', 'read_metrics', {}, timeout=8)
        except PermissionError as exc:
            check('public_call_mcp_default_deny', 'plugins.entries.pulse-rings.mcp_allowlist' in str(exc))
        else:
            check('public_call_mcp_default_deny', False)
        clock[0] += 2
        routes.status(True, e)
        waiting = e.status()['pulses'][0]
        check('approved_waits_for_operator_grant', waiting['state'] == 'needs_mcp_grant' and
              e.store.rows()[0]['failures'] == 0 and e.net.usage()['used'] == 0)
        try:
            module.test_call(e.root, 'probe', 'read_metrics', {})
        except module.TestCallError as exc:
            check('builder_missing_grant_explained', exc.status == 403 and
                  'plugins.entries.pulse-rings.mcp_allowlist' in str(exc))
        else:
            check('builder_missing_grant_explained', False)
        # Only this disposable synthetic profile is changed; never a live grant.
        config = config.replace('  enabled: [pulse-rings]\n',
            '  enabled: [pulse-rings]\n  entries:\n    pulse-rings:\n      mcp_allowlist: [probe, priced, disconnected]\n')
        (home / 'config.yaml').write_text(config, encoding='utf-8')
        from hermes_cli.config import load_config
        check('scratch_grant_readback', load_config()['plugins']['entries']['pulse-rings']['mcp_allowlist'] ==
              ['probe', 'priced', 'disconnected'])
        inspected = module.test_call(e.root, 'probe', 'read_metrics', {'offset': 3})
        check('builder_public_call_mcp_result', inspected['body']['count'] == 45 and inspected['calls'] == 1)
        clock[0] += 61
        status = routes.status(True, e)
        row = next(p for p in status['pulses'] if p['id'] == 'mcp-integration')
        check('approved_dashboard_poll_numeric_ring_capsule', row['ring']['score'] == 87.5 and row['capsule']['label'] == '45 items', row=row)
        check('cached_agent_status_same_values', '45 items' in registry.dispatch('pulse_rings_status', {}))
        check('no_raw_output_persisted', 'MCP_RESULT_CANARY' not in json.dumps(e.store.history(row['id'])) + json.dumps(e.store.rows()))
        # Policy refusals use the same real adapter/registry, no handler is replaced.
        for tool, server, reason in [('bump_counter', 'probe', 'not marked read-only'),
                                     ('missing_tool', 'probe', 'not found'),
                                     ('read_metrics', 'disconnected', 'not found'),
                                     ('read_metrics', 'priced', 'spend policy')]:
            d = json.loads(json.dumps(definition)); d['id'] = tool.replace('_', '-') + '-' + server
            d['source']['params'].update(server=server, tool=tool, args={})
            pending = e.create_draft(d, origin={'kind': 'cron'})
            e.decide_draft(pending['draft_id'], 'approve', via='command')
            clock[0] += 2
            e.poll_one_due()
            failed = next(p for p in e.status()['pulses'] if p['id'] == d['id'])
            check('refuse_' + tool + '_' + server, reason in (failed['error'] or ''), error=failed['error'])
        # Exercise the native public handler's trust/connection envelopes too,
        # without bypassing the plugin's own stricter pre-invocation refusal.
        with module.mcp_access.unattended_scope():
            native_write = ctx.call_mcp('probe', 'bump_counter', {}, timeout=8)
            disconnected = ctx.call_mcp('disconnected', 'read_metrics', {}, timeout=8)
        check('public_call_mcp_write_trust_gate_refused', native_write.get('ok') is False)
        check('public_call_mcp_not_connected_envelope', disconnected.get('ok') is False)
        check('write_tool_never_executed', not marker.exists())
        consent = {'pulse': 1, 'id': 'mcp-consent', 'title': 'Read-only consent fixture', 'source': {'kind': 'mcp.tool', 'params': {
            'server': 'probe', 'tool': 'ask_consent', 'args': {}, 'metrics': {'accepted': '/accepted'}}}}
        e.activate(consent)
        clock[0] += 2
        e.poll_one_due()
        c = next(p for p in e.status()['pulses'] if p['id'] == 'mcp-consent')
        check('server_elicitation_declined_without_prompt', c['capsule']['label'] == '0', row=c)
        check('no_terminal_prompt_attempts', not prompt_attempts, attempts=len(prompt_attempts))
        report['ok'] = True
    except Exception as exc:
        report['failure'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        builtins.input = original_input
        try:
            shutdown_mcp_servers()
        finally:
            faulthandler.cancel_dump_traceback_later()
            # Disposable homes are removed by the parent. Preserve fixture-server
            # stderr so an empty discovery result is diagnosable, not a mystery.
            logs = home / 'logs'
            if logs.is_dir():
                target = Path(args.output).with_suffix('.server-logs')
                shutil.copytree(logs, target, dirs_exist_ok=True)
                report['server_logs'] = str(target)
            Path(args.output).write_text(json.dumps(report, indent=2, default=str) + '\n', encoding='utf-8')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hermes-root', default=os.getenv('HERMES_SOURCE') or str(Path.home() / '.hermes' / 'hermes-agent'))
    parser.add_argument('--output', required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        return worker(args)
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    scratch = (Path.home() / 'AppData/Local/hermes/cache/scratch' if sys.platform == 'win32' else Path(os.environ.get('TMPDIR') or tempfile.gettempdir())).resolve()
    with tempfile.TemporaryDirectory(prefix='pulse-mcp-integration-', dir=scratch) as temporary:
        home = Path(temporary)
        shutil.copytree(ROOT, home / 'plugins/pulse-rings', ignore=shutil.ignore_patterns('.git', '__pycache__', '.pytest_cache'))
        env = {k: v for k, v in os.environ.items() if not k.startswith('HERMES_')}
        env['HERMES_HOME'] = str(home)
        env['HERMES_DISABLE_LAZY_INSTALLS'] = '1'  # Never repair/relaunch a managed runtime from a test.
        env['TMPDIR'] = env['TMP'] = env['TEMP'] = str(scratch)
        with output.with_suffix('.log').open('w', encoding='utf-8') as log:
            proc = subprocess.run([sys.executable, '-u', str(Path(__file__).resolve()), '--worker', '--hermes-root', args.hermes_root,
                                   '--output', str(output)], env=env, stdout=log, stderr=log, text=True, timeout=150)
        if proc.returncode:
            print(output.with_suffix('.log').read_text(encoding='utf-8')[-10000:])
        print(json.dumps({'exit_code': proc.returncode, 'evidence': str(output)}))
        return proc.returncode


if __name__ == '__main__':
    raise SystemExit(main())
