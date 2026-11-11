"""Small fail-closed Hermes metadata shim; never patches core or reads credentials.

Prefer ctx.tool_info if a host supplies it. Hermes 0.22.7 has no public annotation
API: the isolated fallback reads discovery's hint/cost metadata only.
See README rule-9 disclosure and submission/UPSTREAM-ISSUE-mcp-readonly.md.
"""
# Compatibility exceptions (Hermes 0.22.7 has no public equivalents):
# - _tool_is_read_only: discovered annotations are stripped from public schemas.
# - mcp_tool_scope keys: resolve the captured profile, never another profile's server.
# - _server_key/_server_cost_policies: refuse ALL declared spend gates.
# - _servers/_resolve_server_key remain for declared icons ONLY, not connectivity.
# - finite_turn_scope: decline server elicitation without prompting or auto-approval.
# - suppress_interactive_oauth: forbid browser/terminal sign-in from viewed ticks.
# Prefer public ctx.tool_info when supplied. Missing/changed seams fail closed;
# never mutate core tables, install dependencies, or read credential files here.
# Operator grants are read through the public config accessor, never written.
# - declared_icons: read _tools/initialize_result in the bound profile only; no I/O.
from contextvars import copy_context
from contextlib import contextmanager
from pathlib import Path
import threading

_BINDINGS = {}
_LOCK = threading.Lock()


def bind_context(ctx):
    """Called only from register(), in the plugin's profile scope, no storage I/O."""
    if not callable(getattr(ctx, 'call_mcp', None)):
        return
    from plugins.plugin_storage import plugin_data_dir
    from hermes_constants import hermes_home_key  # Public core module (validator allow-list).
    root = Path(plugin_data_dir('pulse-rings')).resolve()
    # Metadata registry overlays use the same canonical profile home key.
    # The public call_mcp runs under this captured profile context.
    binding = (ctx, copy_context(), hermes_home_key(root.parent.parent))
    with _LOCK:
        _BINDINGS[str(root)] = binding
    # Public lifecycle seam: do not retain a disposed context after disable/reload.
    unload = getattr(ctx, 'on_unload', None)
    if callable(unload):
        def remove():
            with _LOCK:
                if _BINDINGS.get(str(root)) is binding:
                    _BINDINGS.pop(str(root), None)
        unload(remove)


@contextmanager
def unattended_scope():
    """Request *denial*, never auto-approval, using host context managers.

    MCP elicitation can happen even inside a read-only call. A finite (not YOLO)
    scope makes Hermes decline it before presenting any prompt. OAuth reconnects
    must likewise fail instead of launching a browser. Missing seams disable MCP.
    """
    from gateway.session_finite import finite_turn_scope
    from tools.mcp_oauth import suppress_interactive_oauth
    with finite_turn_scope(True, unattended=False), suppress_interactive_oauth():
        yield


def binding_for(root):
    with _LOCK:
        return _BINDINGS.get(str(Path(root).resolve()))


def declared_icons(root, server, tool):
    """Read MCP SDK 2 Icon metadata in the captured profile; never reconnect.

    Kept beside the existing private-discovery compatibility shim so future Hermes
    public metadata APIs can replace both seams in one place. Fail closed.
    """
    binding = binding_for(root)
    if binding is None:
        return ([], [])
    _, context, _ = binding
    def read():
        from tools import mcp_tool
        from tools.mcp_tool_scope import _resolve_server_key
        from .icon_resolver import _icon_groups
        task = mcp_tool._servers.get(_resolve_server_key(server))
        return _icon_groups(task, tool)
    try:
        return context.copy().run(read)
    except Exception:
        return ([], [])


GRANT_KEY = 'plugins.entries.pulse-rings.mcp_allowlist'


def grant_message(server, allowed=False):
    return ('Allowed in Hermes settings' if allowed else
            f'Not yet allowed — add "{server}" to {GRANT_KEY}')


def server_granted(server):
    """Read only: same public accessor/tree as PluginContext.call_mcp.

    ctx.get_config is settings-relative, NOT the operator entry-level grant.
    Called inside the bound profile context; never write or auto-grant.
    """
    try:
        from hermes_cli.config import load_config
        cfg = load_config() or {}
        allowed = cfg.get('plugins', {}).get('entries', {}).get('pulse-rings', {}).get('mcp_allowlist')
        return isinstance(allowed, list) and server in [str(item) for item in allowed]
    except Exception:
        return False


def tool_policy(ctx, server, tool, scope):
    """Return trusted booleans and a static reason, no server messages/results.

    Run in the captured profile context, as does call_mcp. Costed servers are
    refused outright: even a read-only tool can otherwise prompt for spend.
    """
    name = f'mcp__{server}__{tool}'
    public = getattr(ctx, 'tool_info', None)
    if callable(public):
        try:
            info = public(name)
            if not isinstance(info, dict) or info.get('connected') is not True:
                return False, 'MCP server not connected.'
            if info.get('exists') is not True:
                return False, 'MCP tool not found.'
            if info.get('read_only') is not True:
                return False, 'MCP tool is not marked read-only.'
            if info.get('requires_approval') is not False:
                return False, 'MCP unattended safety unavailable; source disabled.'
            return True, None
        except Exception:
            return False, 'MCP policy unavailable; source disabled.'
    try:
        from tools.registry import registry  # Public registry methods; no table mutation.
        from tools.mcp_tool_handlers import _tool_is_read_only
        from tools.mcp_tool_scope import _server_key
        from tools import mcp_tool
        if registry.get_entry(name, scope=scope) is None:
            return False, 'MCP tool not found.'
        if _tool_is_read_only(server, tool) is not True:
            return False, 'MCP tool is not marked read-only.'
        # Refuse ALL cost policies, including nominally free calls, rather than
        # racing mutable spend tallies or entering Hermes's approval subsystem.
        if _server_key(server) in mcp_tool._server_cost_policies:
            return False, 'MCP spend policy requires interactive use; source disabled.'
        return True, None
    except Exception:
        return False, 'MCP policy unavailable; source disabled.'
