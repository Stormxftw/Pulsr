"""MCP policy through Hermes's public plugin API only; fail closed.

Hermes has no public read-only or cost metadata for MCP tools yet, so the
mcp.tool source and MCP-declared icons stay off unless the host supplies
ctx.tool_info. They come back on their own once core adds it. Calls go through
the public ctx.call_mcp, which applies the operator's mcp_allowlist and core's
own trust, approval and sign-in gates. No private core module is imported here.
See submission/UPSTREAM-ISSUE-mcp-readonly.md for the requested public seam.
"""
from contextvars import copy_context
from pathlib import Path
import threading

_BINDINGS = {}
_LOCK = threading.Lock()

UNAVAILABLE = ('MCP pulses are off: this Hermes has no public read-only metadata '
               'for MCP tools yet. They turn on by themselves once it does.')


def bind_context(ctx):
    """Called only from register(), in the plugin's profile scope, no storage I/O."""
    if not callable(getattr(ctx, 'call_mcp', None)):
        return
    from plugins.plugin_storage import plugin_data_dir
    from hermes_constants import hermes_home_key  # Public core module (validator allow-list).
    root = Path(plugin_data_dir('pulse-rings')).resolve()
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


def binding_for(root):
    with _LOCK:
        return _BINDINGS.get(str(Path(root).resolve()))


def public_metadata(ctx):
    """The host's public tool_info, or None when this Hermes has none."""
    info = getattr(ctx, 'tool_info', None)
    return info if callable(info) else None


def available(ctx):
    return public_metadata(ctx) is not None


def declared_icons(root, server, tool):
    """MCP-declared icons from public tool_info only; never reconnects. Fail closed."""
    binding = binding_for(root)
    if binding is None:
        return ([], [])
    ctx, context, _ = binding
    public = public_metadata(ctx)
    if public is None:
        return ([], [])

    def read():
        info = public(f'mcp__{server}__{tool}')
        if not isinstance(info, dict) or info.get('exists') is not True:
            return ([], [])
        tool_icons, server_icons = info.get('icons'), info.get('server_icons')
        return (list(tool_icons) if isinstance(tool_icons, (list, tuple)) else [],
                list(server_icons) if isinstance(server_icons, (list, tuple)) else [])
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


def tool_policy(ctx, server, tool, scope=None):
    """Return trusted booleans and a static reason, no server messages/results.

    Only the public ctx.tool_info can say a tool is read-only and needs no
    approval or spend. Without it the source is off. Costed or approval-gated
    tools are refused outright.
    """
    public = public_metadata(ctx)
    if public is None:
        return False, UNAVAILABLE
    try:
        info = public(f'mcp__{server}__{tool}')
        if not isinstance(info, dict) or info.get('connected') is not True:
            return False, 'MCP server not connected.'
        if info.get('exists') is not True:
            return False, 'MCP tool not found.'
        if info.get('read_only') is not True:
            return False, 'MCP tool is not marked read-only.'
        if info.get('requires_approval') is not False:
            return False, 'MCP tool needs approval or spend; source disabled.'
        return True, None
    except Exception:
        return False, 'MCP policy unavailable; source disabled.'
