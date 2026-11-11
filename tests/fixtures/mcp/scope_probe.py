"""Run the real mcp_access.bind_context against the real Hermes tool registry.

argv: <hermes source> <pulse-rings root> <mixed-case scratch home>. Prints OK.
"""
import importlib.util
import sys
import types
from pathlib import Path

hermes, plugin_root, home = (Path(arg) for arg in sys.argv[1:4])
sys.path.insert(0, str(hermes))

import plugins.plugin_storage as storage  # noqa: E402
from hermes_constants import hermes_home_key  # noqa: E402
from tools.registry import registry  # noqa: E402

spec = importlib.util.spec_from_file_location('pr_mcp_access', plugin_root / 'pulse_rings' / 'mcp_access.py')
mcp_access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp_access)

data = home / 'plugin-data' / 'pulse-rings'
data.mkdir(parents=True, exist_ok=True)
storage.plugin_data_dir = lambda name: data
mcp_access.bind_context(types.SimpleNamespace(call_mcp=lambda *a, **kw: '{}'))
scope = mcp_access.binding_for(data)[2]
assert scope == hermes_home_key(home), (scope, hermes_home_key(home))

name = 'mcp__scopeprobe__read_metrics'
owner = hermes_home_key(home)  # how a profile-serving gateway keys MCP overlays
registry.register(name, 'mcp-scopeprobe', {'name': name, 'parameters': {'type': 'object'}},
                  lambda args, **kw: '{}', scope=owner)
assert registry.get_entry(name, scope=scope) is not None, 'profile-scoped MCP tool not visible'
print('OK')
