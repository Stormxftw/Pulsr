# Plugin API: read-only and approval metadata for MCP tools (`ctx.tool_info`)

**Status:** ready to file on NousResearch/hermes-agent (suggested in the catalog
review of pulse-rings).

## What a plugin needs

A plugin that polls an MCP tool on a schedule, with no person at the keyboard,
needs to know before each call that the tool is safe to run unattended: it is
connected, it exists, the server marked it read-only, and calling it can't
prompt for approval or spend. `PluginContext.call_mcp` already applies the
operator's `mcp_allowlist` and core's trust gates, but nothing public tells a
plugin those facts first. The tool schema a plugin sees drops the MCP
`readOnlyHint` annotation, and a per-server grant covers write tools too.

Pulsr (pulse-rings) is the concrete consumer: a person approves a pulse such as
server `metrics`, tool `read_counts`, args `{}`, pointer `/count`, and Pulsr
polls it every 15 minutes through `ctx.call_mcp`. To stay on the public plugin
surface, Pulsr now keeps its MCP source **off** unless the host offers this
metadata, and turns it on by itself once it does.

## Requested surface

A side-effect-free lookup on `PluginContext`, keyed by the registry name:

```python
ctx.tool_info("mcp__metrics__read_counts") -> {
    "exists": True,
    "connected": True,
    "read_only": True,           # the discovered readOnlyHint, never a name heuristic
    "requires_approval": False,  # True if any cost/spend policy or approval could apply
    "icons": [...],              # optional: the tool's declared MCP icons (src, mimeType, sizes)
    "server_icons": [...],       # optional: serverInfo icons
}
```

Names are open to maintainers; Pulsr feature-detects `ctx.tool_info` and these
keys today, so matching them means it works with no plugin release.

Expected behaviour:

- No discovery, reconnect, network, invocation, OAuth or prompt during lookup.
- Resolves in the calling plugin's profile only.
- Unknown or ambiguous fields come back missing or `None`, which plugins treat
  as "no". Returns plain copies, never live task or config objects.
- A snapshot only: the handler's checks at call time stay authoritative.

## Optional, related

A way to ask `call_mcp` to decline, rather than show, server elicitation and
interactive OAuth sign-in for unattended calls (for example
`ctx.call_mcp(..., interactive=False)`). Pulsr used to get this from private
scopes and has dropped them; today it relies on core's own handling inside
`call_mcp`.

## What this replaces

Before the catalog review, Pulsr read these private symbols to make the same
decisions. All are now removed from the plugin:

- `tools.mcp_tool_handlers._tool_is_read_only`
- `tools.mcp_tool_scope._server_key`, `_resolve_server_key`
- `tools.mcp_tool._servers`, `_server_cost_policies`
- `gateway.session_finite.finite_turn_scope`
- `tools.mcp_oauth.suppress_interactive_oauth`

## Sketch

Inside `PluginContext`, under the profile scope and the discovery lock: find the
server task and tool, copy its `readOnlyHint` and declared icons, set
`requires_approval` when the tool is not read-only or the server has any cost
policy, and return a fresh dict. Tests: hint true/false/missing; lookup never
calls, prompts or reconnects; cost policy forces `requires_approval`; another
profile's server is not visible; mutating the returned dict changes nothing.
