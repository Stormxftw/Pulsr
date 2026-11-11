"""Opt-in-by-availability real stdio MCP + actual Hermes plugin registry."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERMES = Path(os.environ.get('HERMES_SOURCE') or Path.home() / '.hermes' / 'hermes-agent')


@pytest.mark.integration
def test_real_mcp_plugin_end_to_end(tmp_path):
    if not (HERMES / 'hermes_cli/plugins.py').is_file() or importlib.util.find_spec('mcp') is None:
        pytest.skip('Requires Hermes checkout (HERMES_SOURCE) and MCP SDK in the test Python')
    output = tmp_path / 'evidence.json'
    env = dict(os.environ, HERMES_DISABLE_LAZY_INSTALLS='1')
    proc = subprocess.run([sys.executable, str(ROOT / 'scripts/verify-mcp-live.py'), '--hermes-root', str(HERMES),
                           '--output', str(output)], env=env, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['ok'] and len(report['steps']) >= 23
    assert all(step['ok'] for step in report['steps'])
    names = {step['name'] for step in report['steps']}
    assert {'public_call_mcp_default_deny', 'approved_waits_for_operator_grant',
            'builder_public_call_mcp_result', 'public_call_mcp_write_trust_gate_refused',
            'public_call_mcp_not_connected_envelope', 'write_tool_never_executed',
            'server_elicitation_declined_without_prompt'} <= names
