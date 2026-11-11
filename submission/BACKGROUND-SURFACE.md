# Background collection: public surface research and lifecycle

## Host contract checked before implementation

Sources are the supplied read-only Hermes checkout at
`$HERMES_SOURCE`; online plugin documentation
was also fetched from <https://hermes-agent.nousresearch.com/docs/developer-guide/plugins>.
No host code was changed, wrapped, rebound or imported through private scheduler APIs.

- **Registration is synchronous and called at startup:** plugin guide
  `website/docs/developer-guide/plugins/index.md:893–936` describes `register(ctx)`
  and the supported registration surfaces. Hook table `:1526–1556` has agent/turn
  lifecycle hooks, not a periodic service or gateway process shutdown hook.
- **There is a public supervised async task API:**
  `hermes_cli/plugins.py:425–435`, `PluginContext.spawn_task(coro, *, name=None)`.
  It explicitly calls `asyncio.get_running_loop()`; unload/force reload cancels
  the task. It is source-public, but not currently described in the plugin guide's
  prose. Synchronous plugin discovery/dashboard dependency execution does not
  guarantee a running asyncio loop in its calling thread. Treating this as a
  periodic service registration would be incorrect. No such service API was
  found in the inspected public context methods or documentation.
- **Public cleanup callback:** `hermes_cli/plugins.py:416–423`,
  `PluginContext.on_unload(callback)`. Cleanup is run in reverse acquisition order
  and exceptions are logged rather than propagated. This source-public lifecycle
  method was already used for the plugin's MCP binding before WP10. It is not an
  `on_session_end` hook: sessions end after turns and must not stop a process worker.
- **Gateway hooks are a different, trusted-by-placement package surface:**
  `website/docs/user-guide/features/hooks.md:26–30,85–98` documents
  `HOOK.yaml` + `handler.py`, gateway-only loading and `gateway:startup`.
  There is no matching documented gateway shutdown event in that event table.
  Writing a user's hooks directory or assuming it runs inside the Desktop host
  would broaden this plugin's install/enable boundary. No hook files are installed.
- **Documented plugin configuration:** plugin guide `index.md:957–1026`
  specifies `ctx.get_config` / `ctx.set_config`, the profile-scoped
  `plugins.entries.<id>.settings` namespace, and `config_schema` Desktop switches.
  `index.md:1050–1055` documents `hermes_cli.config.load_config_readonly()` for a
  dashboard half. Actual context implementations are `plugins.py:266–280`.
  The setting writer never imports the private configuration writer.
- **Plugin-owned durable root:** plugin guide `index.md:1153–1173` documents
  `plugins.plugin_storage.plugin_data_dir` / `plugin_db`. Existing Store remains
  the SQLite owner; the lease is an additive table in its existing database.

## Chosen compliant fallback

A plugin-owned **daemon thread**, not a fabricated Hermes periodic service.
`register(ctx)` binds the profile context into the same path-unique plugin-owned
package the dashboard uses. If already opted in, it starts the collector. A
first dashboard request can also start it lazily. Python stdlib `Thread`, `Event`,
`contextvars.copy_context`, `atexit`, SQLite, and nonblocking OS file locking are
used; no cron/model turns, shell children, credential access or private host
scheduler is added. `ctx.on_unload` and `atexit` call the bounded stop method.

One registered collector per process/profile root is protected by a process lock.
Every tick also acquires a process/OS fence before atomically obtaining/renewing
a SQLite lease. The lease has a 30-second expiry, last-tick timestamp and a
five-second minimum tick gap. The OS fence is necessary: a TTL alone cannot
prevent simultaneous polls if a paused process resumes after its lease expires.
No SQLite write transaction is held during networking. The file lock stays held
through the poll, so a slow or stuck holder cannot overlap a replacement.

A tick calls only `poll_one_due(previews=False)` for approved, unpaused pulses.
The ordinary adapter budgets, ceiling, pacing, jitter, deferrals, backoff and MCP
read-only/unattended refusal policy remain in charge. Background collection does
not make an unavailable MCP connection available or relax the existing disclosed
MCP compatibility shim. Draft preview work remains viewer-only.

## Exact settings and status contract

`background_collection` is a `config_schema` bool, default `false`. The pane
switch human-clicks `PUT /settings` with exactly
`{background_collection: <boolean>, confirm: true}`. Both fields are StrictBool;
extra keys are forbidden. The route uses captured `ctx.set_config`, reads the
exact setting back, then the renderer GETs `/settings` before refreshing status.
No agent tool can toggle it. The host mount owns auth/enablement/origin checks.
If no enabled agent-plugin context is bound in this process, writing returns 503
with Plugins-settings instructions; there is no undocumented config-write fallback.
The generic Plugins form persists the same key; OFF→ON there starts on the next
plugin load/dashboard access, whereas pane ON starts immediately.

Every status includes `collection: {mode: viewed|background,
lease_holder_alive: boolean, last_tick_ts: number|null}`. Liveness is lease
freshness, not proof of source success. The footer reads “Collecting in background”
or “Collecting while open”. Approved-feed polling is suppressed while a holder's
lease is alive; a stale lease admits at most one viewed fallback poll. Background
samples update the usual baseline/alert read model; visible Desktop views still
own toast delivery, not the headless collector.

## Shutdown limitations (not hidden by the timeout)

Idle stop joins promptly. Stop signals cancellation and joins for **at most 1.5s**;
Python cannot forcibly interrupt an already executing socket/MCP call. It may drain
on the daemon after stop returns, retaining its OS fence. Cancellation prevents a
subsequent gated request and discards late samples. A stuck existing MCP handler
retains its bounded worker slot until return/process exit. This cannot keep the
process alive. A false stop result means a draining thread remains, not a claim
that it joined. SQLite claim contention backs off 5–60s with a 50ms busy timeout.

README and PR body explicitly disclose the long-running thread, its source calls,
turn-off controls, process/context requirement, bounded stop/drain and notification
limitation (catalog rules 9, 12 and 13). An installed live Desktop/gateway smoke
and independent concurrency/security review remain separate acceptance gates.

## WP10 verification receipt

All work and tests ran in the isolated `wp10-background` worktree; no installation,
restart, push, production feed access or live configuration change was performed.

```sh
uv run --isolated --no-project --python 3.11 --with 'pytest>=8,<9' --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'jsonschema>=4,<5' --with 'ruamel.yaml>=0.18,<0.19' python -m pytest tests -q -p no:cacheprovider --basetemp $TMPDIR/wp10-bg-final2-pt
```

**1247 passed, 1 skipped, 1 dependency warning**, exit 0. The skip needs the
Hermes checkout/MCP SDK integration environment; the warning is Starlette/httpx
TestClient deprecation. Earlier runs under concurrent browser load exposed the
existing 50ms DNS/MCP startup timing assertions and a too-short new spawned-test
startup wait; the new test wait was corrected, focused retries passed, and the
final full run was serial and green. These were not hidden with deselection.

```sh
node scripts/preview-server.mjs $HERMES_SOURCE 5261
PULSE_PREVIEW_ORIGIN=http://127.0.0.1:5261 node scripts/test-widget.mjs $HERMES_SOURCE $TMPDIR/wp10-bg-widget
PULSE_PREVIEW_ORIGIN=http://127.0.0.1:5261 node scripts/test-blocks.mjs $HERMES_SOURCE $TMPDIR/wp10-bg-blocks
PULSE_PREVIEW_ORIGIN=http://127.0.0.1:5261 node scripts/test-builder.mjs $HERMES_SOURCE $TMPDIR/wp10-bg-builder
PULSE_PREVIEW_ORIGIN=http://127.0.0.1:5261 node scripts/test-background.mjs $HERMES_SOURCE $TMPDIR/wp10-bg-browser
```

**145 widget / 241 block / 91 builder / 17 background checks passed**; no remote
requests or renderer errors/warnings. New toggle/late-profile/readback/error/footer
checks use the explicit mock settings boundary, not live Hermes. Screenshot
`wp10-bg-browser/background-on.png` was visually reviewed: full collection mode
is visible; trailing footer metadata is ellipsized with a full native title so
narrow panes do not overflow. The preview server was stopped afterwards. Renderer
and new test-script Node syntax checks plus `git diff --check` passed.
Eleven UI fixtures were regenerated with the existing engine generator; their only
changes are the additive default-OFF collection object.

### Catalog validation blocker, independently reproduced at base

```sh
HERMES_HOME=$TMPDIR/wp10-bg-validate-home UV_OFFLINE=1 hermes plugins validate ../pulse-rings-wp10-background --install-deps
```

**Exit 1, Validation failed**, not an admission pass. Registration, config schema,
capability declarations, no-core-override and Desktop SDK checks all passed.
Security scan reports `crypto_mining (brands.json:1)` and
`tunnel_service (brands.json:1)` as dangerous, plus the existing
`sudo_usage (hermes.py:32,65)` names. Existing MCP private-import warnings remain;
there is no new background module private import warning.

The same command against an isolated `git archive cd8fee9` snapshot with a
separate scratch HERMES_HOME produced **the exact same failure and warning list**.
The current and base `pulse_rings/brands.json` SHA-256 are identical:
`5da37c2ed0ab958c12a7152463287f9efe61768941f6d4df0f1e07aee2d3156f`.
WP10 does not modify or obscure the brand catalog to evade lexical findings.
The parent must resolve/review that existing catalog blocker and MCP compatibility
warnings before submission. Source-public `on_unload` and loop-dependent
`spawn_task` are not a claim of a warning-free catalog pass.
