# Draft issue: expose discovered MCP read-only and cost metadata beside call_mcp

**Unposted**, no issue number/maintainer endorsement implied. This is a narrow
public metadata request, not a request for another invocation API: public
`PluginContext.call_mcp` already exists in v0.22.7+ and v0.23.0/main.

## Concrete consumer and gap

Pulsr is a data-only Desktop numeric tracker. A person reviews a feed such
as server `metrics`, tool `read_counts`, args `{}`, pointers `/used` and `/limit`,
then approves recurring viewed/opt-in-background polling. Both its polls and its
separately human-consented builder Test call now use
`ctx.call_mcp(server, tool, arguments, timeout=8)`. The operator separately grants
`plugins.entries.pulse-rings.mcp_allowlist: ["metrics"]`; the plugin never grants
itself access. Pulse approval may come first and waits in `needs_mcp_grant`.

We need an explicit **discovered readOnlyHint=true** and **no declared cost/spend
policy** before invocation. The public tool schema strips the annotation, and
call_mcp's per-server grant intentionally includes write-capable tools subject to
host trust gates. A name beginning with `get_` or a successful probe cannot prove
read-only safety. Sampling remains a separate host setting and may use tokens.

## Requested surface (names open to maintainers)

Expose a side-effect-free snapshot alongside call_mcp, e.g.:

```python
ctx.mcp_tool_info("metrics", "read_counts") -> {
    "exists": True,
    "read_only": True,          # explicit discovered readOnlyHint, not a name heuristic
    "has_cost_policy": False,   # any declared policy, even nominally free calls
    "requires_approval": False, # conservative static policy, not future dynamic consent
}
```

Alternatively attach these facts to the declared capability/per-tool ro/rw model
referenced by **TODO(#64228)** in
[plugins.py:511–513](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/hermes_cli/plugins.py#L511-L513).
No discovery, network, invocation, OAuth, credentials or approval requests during
lookup. Resolve only the calling plugin/profile; absent/ambiguous fields must be
unknown/denial, not permission. Return plain immutable-by-copy flags, never raw
config/task objects. State snapshot/race semantics: handler checks at call time
remain authoritative. A policy mutation after the snapshot cannot be ruled out by
metadata alone. `requires_approval` must not promise a future mutable spend tally.

## Exact private symbols this would retire

From `pulse_rings/mcp_access.py::tool_policy`:

- `tools.mcp_tool_handlers._tool_is_read_only(server, tool)`.
- `tools.mcp_tool_scope._server_key(server)`.
- `tools.mcp_tool._server_cost_policies`.
- The extra public scoped `registry.get_entry` existence lookup could also go.

Our old connection-presence `_resolve_server_key` / `_servers` read was removed:
call_mcp already returns failures/reconnects. **Those symbols still exist solely
for declared icon metadata** (`MCPServerTask._tools` / `initialize_result`); this
metadata request would not retire icon lookup or these separate no-prompt scopes:
`gateway.session_finite.finite_turn_scope` and
`tools.mcp_oauth.suppress_interactive_oauth`. A future supported no-prompt option
and declared-icon surface could address those independently. A future
`ctx.tool_info(name)` with the required booleans is already preferred by our shim.
No host functions/tables are patched or mutated; missing seams fail closed.

## Why call_mcp's existing safety gates do not replace this metadata

The public method [plugins.py:502–566](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/hermes_cli/plugins.py#L502-L566)
checks the grant, makes the native handler, normalizes errors/structured/truncated
results. It does not impose a read-only-only or noninteractive call context.
[handlers:123–208](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/tools/mcp_tool_handlers.py#L123-L208)
may reserve charges within the limit and ask above it, so spend-limit preservation
is not a no-cost/no-prompt guarantee. We refuse every declared cost policy rather
than race mutable tallies or enter the approval subsystem.

The native handler [692–744](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/tools/mcp_tool_handlers.py#L692-L744)
forwards calling context for server elicitation and performs reconnect/auth
recovery. Finite scope makes [approval_prompt:316–319](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/tools/approval_prompt.py#L316-L319)
decline via [approval_context:207–212](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/tools/approval_context.py#L207-L212).
OAuth is otherwise interactive by default and may launch browser authorization
([mcp_oauth:334–374](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/tools/mcp_oauth.py#L334-L374),
[811–820](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/tools/mcp_oauth.py#L811-L820)).
We retain these denial scopes even for a viewed poll; viewed is not per-call
interactive consent. No auto-approval, privilege escalation or second MCP client.

Grant disclosure uses `hermes_cli.config.load_config`, the same public accessor
as call_mcp. `ctx.get_config` reads `.settings`/legacy `.config` only
([plugins.py:266–276](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/hermes_cli/plugins.py#L266-L276));
the operator grant is entry-level, not plugin-owned settings.

## Approximate implementation + tests sketch (~50 lines; doc only)

This is intentionally a sketch in this issue, **not a Hermes patch**. Reuse the
host's own resolution helpers inside PluginContext's profile scope and copy
metadata under the discovery lock; never return the task or table itself.

```python
# plugins.py: about 30 lines including validation/scope and conservative policy.
def mcp_tool_info(self, server, tool):
    # Validate exact names with the same native MCP name rules.
    # Enter this manager's public/profile-bound resolution scope.
    # No discovery/reconnect/client creation from a metadata lookup.
    from tools import mcp_tool
    from tools.mcp_tool_handlers import _tool_is_read_only
    from tools.mcp_tool_scope import _server_key, _resolve_server_key
    with plugin_profile_scope(self):  # illustrative existing-scope adapter
        with mcp_tool._lock:
            key = _resolve_server_key(server)
            task = mcp_tool._servers.get(key)
            found = next((t for t in getattr(task, "_tools", ())
                          if t.name == tool), None)
            # If schema-cache/lazy metadata exists, use its actual hint;
            # otherwise return unknown, never infer from the name.
            if found is None:
                return {"exists": False, "read_only": None,
                        "has_cost_policy": None, "requires_approval": None}
            read_only = _tool_is_read_only(server, tool) is True
            costed = _server_key(server) in mcp_tool._server_cost_policies
            # Static conservative requirement, not a spend-tally prediction.
            needs_consent = costed or not read_only
            return {"exists": True, "read_only": read_only,
                    "has_cost_policy": costed,
                    "requires_approval": needs_consent}

# About 20 lines of parametrized tests in the existing host test harness.
@pytest.mark.parametrize("hint, expected", [(True, True), (False, False), (None, False)])
def test_discovered_hint_not_name_heuristic(host, hint, expected):
    host.discover("metrics", "get_counts", read_only_hint=hint)
    assert host.ctx.mcp_tool_info("metrics", "get_counts")["read_only"] is expected

def test_metadata_never_calls_or_prompts(host):
    host.ctx.mcp_tool_info("missing", "read_counts")
    assert host.invocations == host.prompts == host.reconnects == []

def test_cost_and_profile_boundaries(host):
    host.discover("metrics", "read_counts", read_only_hint=True, cost=0)
    assert host.ctx.mcp_tool_info("metrics", "read_counts")["has_cost_policy"] is True
    assert host.other_profile.ctx.mcp_tool_info("metrics", "read_counts")["exists"] is False
```

Also test unknown/stale/lazy discovery, returned-dict mutation isolation, policy
change before call, and entry grant revocation with real call_mcp. Native handler
trust gates and spend checks must stay intact. Our isolated stdio fixture covers
actual call_mcp grant denial, approve-before-grant wait, granted numeric polling,
consented builder inspection, write-tool refusal with no marker, cost refusal,
no raw persisted payload and server elicitation declined with zero stdin prompts.
It is not remote OAuth/live connector certification. No live user MCP is used.
