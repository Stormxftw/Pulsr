# Submission checklist — local evidence, not published

## WP17 repo activity disclosure delta

- [x] github.repo activity/ci default false; omitted flags stay omitted. Legacy
  preset/sample shape/default 8 req/h unchanged.
- [x] Same api.github.com host: repo + pulls 2/poll; participation hourly only
  with activity (+1 req/h even on 202); Actions runs on default branch 1/poll
  only with ci. Push age updates locally with no call. At 10m: 12/13/18/19 req/h;
  at 15m: 8/9/12/13 (neither/activity/CI/both). Bundled artwork adds no host;
  source avatars still separately disclose avatars.githubusercontent.com.
- [x] Token only via scoped Hermes secret PULSE_RINGS_GITHUB_TOKEN; private repo
  needs fine-grained repo contents/metadata read and Actions read for CI. No new
  credential stores, hosts, shell commands, approvals or background processes.
- [x] Source baseline excludes current week, uses previous 12 GitHub weeks;
  202/no runs/Actions 403/404 are unknown, not zero. Latest running build has no
  completed conclusion; no older run is fetched with the one-call endpoint.
- [x] Builder checkboxes + Repo activity preset; data-only states/tone and hours
  duration stat; ready private-repo definition contains no credentials.
- [ ] Live private repository validation awaits the user's token/approval.


Version label: `version: "0.5.0-dev"`. Manifest, Python metadata, dashboard,
renderer, status and catalog draft agree. Source target:
https://github.com/Stormxftw/Pulsr (private; made public for submission).

**Local WP11 core admission passes with cautions (receipt below); final merged
independent review and publication/live gates remain open.** This is not a claim
that a catalog entry with a placeholder SHA is admissible or that a maintainer
has reviewed/merged anything. No pushes, installs into live Hermes, restart,
service/config changes or live source-network calls were authorized/performed.


## WP15 sessions verification delta

- [x] Default-off strict `show_sessions` confirmation/readback; no agent tool,
  implicit collection, approval draft or pulse definition.
- [x] Process/profile-scoped bounded memory; counters/timestamps/ids only;
  no transcript, prompt, tool-name/args/result or goal reads. Title projection
  from public session-list RPC stays in renderer memory. OFF clears observations.
- [x] Parent/subagent aggregation, turn/session counters, Done finish timestamp,
  15-minute linger, missing-hook/config fail-soft, no network or persistence.
- [x] Reserved `hermes-sessions` is the real arrangement group, not a standalone
  section: expanded session rows, collapsed four circles per row, identical full
  keyboard/hover metadata; rename/collapse/group-order use `/layout` save/readback.
  Opt-out removes the group; sessions cannot be moved out or nested.
  Activity/titles are memory-only; customized layout can retain opaque hashed refs
  and group preferences, not raw ids/titles/counters/times. 248/320/670px, light/dark.
- [x] Theme-token-only tapered comet, soft breath, tool ripple and done tick;
  None/Calm/Lively, system reduced motion, off-screen/hidden pause, allowed animated
  properties only and at most one ring-owned compositor layer (Edge/CDP fixture).
- [x] Public hook/API source checks: `hermes-agent` at
  `v0.22.7-90-g29a61cb7ab5` and isolated `hermes-v0.23.0` at tag `v0.23.0`.
  Eleven-hook union matches manifest/catalog draft.
  Added hooks: `on_session_start`, `on_session_finalize`, `post_llm_call`.
  Reused hooks: `pre_llm_call`, `on_session_end`, `post_tool_call`,
  `subagent_start`, `subagent_stop`. `on_session_end` is a turn boundary;
  `post_llm_call` is not completion. Titles: `host.request('session.list', {limit:128})`;
  focus: documented `host.openSession(id,{profile})`; missing navigation fails
  soft with a notice (no guessed legacy route).
  Runtime identity: `focusedSessionId` + `focusedStoredSessionId`, busyBySession.
  Event: public `broadcast_plugin_event` via existing helper, empty
  `sessions.updated` invalidation; local three-second query fallback.
- [x] Self-reviewed initial and revised screenshots: removed misleading empty-pulse
  onboarding above active sessions, wrapped full titles, enlarged metadata, refined
  the comet into a tapered three-part accent trail. Actual offset progression and
  frame strip reviewed; calm and contained, not a spinner flood.
- [ ] Live install/auth mount, clean minimum-host admission, groups/builder sibling
  merge and post-merge tests remain integration gates. No live install, config edit,
  service restart, push or additional preview server was performed.

Artifacts: `$ARTIFACTS/pulse-rings/wp15-sessions/` —
`sessions-results.json`, 248/320 light/dark expanded/collapsed screenshots,
`sessions-done.png`, `sessions-reduced-motion.png`, `animation-frame-0.png` through
`animation-frame-5.png`, and reviewed `animation-frame-strip.png`.

## WP15 groups / arrangement disclosure

- Local-only UI state in this profile's plugin data: **layout.json**, max 64 KiB;
  group ids/titles/collapse flags and pulse refs, one subgroup level. Not a host,
  pulse definition, shared payload or approval. Same-directory `layout-*.tmp`
  staging is removed on ordinary success/failure; crash leftovers are inert.
- GET/PUT `/layout` use plain-def handlers, no source poll/collector startup,
  strict envelope/model validation, atomic replacement and cross-process SQLite
  write-lock fencing. Content revisions reject stale writes with 409.
- Draft cards stay outside groups; group removal never removes pulses. Reserved
  Hermes sessions remain in `hermes-sessions`. No extra processes/dependencies.
- Source tests and local mock-transport browser/screenshot evidence only. Live
  installation and sibling session-renderer integration require separate gates.
- WP15 source gate: **1341 passed, 1 skipped** (`pytest tests`); browser checks:
  groups **98**, widget **148**, blocks **241**, builder **93**, polish **298**,
  background **17**, security-ui **602**, ui-nits **290**. Reports are under
  `$ARTIFACTS/pulse-rings/wp15-groups/`.
- Twelve image-tool-reviewed screenshots: `{expanded,collapsed,mid-drag}-`
  `{320,670}-{light,dark}.png` in that evidence directory. The group suite also
  verifies 248px usability, four columns, ghost/marker separation, reserved-session
  restrictions, source-update liveness, reduced motion and nested FLIP behavior.
- Forty-pulse active-drag RAF p95: **6.2ms**, same as idle, on the last run.
  The regression gate is `p95 <= max(20ms, idleP95 + 8ms)` with >=20 samples.
  Shared Windows/headless scheduling also produced **42.4ms idle and drag**;
  absolute samples and the calibrated budget are retained in `frame-times.json`.
  This is not a fixed 60fps guarantee or installed-host performance claim.


## Current release contract (0.5.0-dev)

- Exactly four agent tools: `pulse_rings_catalog`, `pulse_rings_layout_check`,
  `pulse_rings_propose`, `pulse_rings_status`. No decision/activation tool.
- Automatic previews: up to 2 dispatches per eligible fixed-host feed, so up to 6
  for three feeds; at most one during propose and one per later viewed tick.
  Only interactive fixed Discord/GitHub feeds are eligible. MCP/http_json and
  unattended proposals never automatically preview.
- **Builder Test call:** a separate human checkbox + button, strict literal
  consent, before pulse approval. Exactly one read-only/no-spend MCP dispatch;
  no retries, activation or persistence. Raw decoded output may contain private
  data and is shown transiently in Desktop, not secret-redacted. A 10-second
  per-profile/server/tool ephemeral gate applies; it shares four MCP worker slots,
  one-in-flight exclusion, the eight-second caller deadline, live refusal policy
  and 256 KiB secondary decoded-body cap (Hermes envelopes cap at ~64K chars). Text is capped at 64 KiB; truncated results expose no
  bindable numeric body. There is **no ordinary Net budget reservation** for this
  inspection; the local test gate, not recurring request accounting, limits it.
  Do not use agent tools to imitate that human consent.
- Builder actions: New (`+`), Edit replacement, Open pending in builder, Import
  YAML/JSON, two-way definition editing, block ordering and sample/cached/measured
  previews. Sample is explicitly synthetic; cached/measured do not poll merely
  to preview edits. Save creates a draft for review; only the human approves.
  Share YAML copies a saved normalized definition, not private test output.
- Offline artwork: Simple Icons **16.36.0**, **3,465** icons, **4,811,947 bytes**;
  CC0-1.0 grants no trademark rights or endorsement. Explicit ARTWORK SCOPE
  excludes entire slug/title/upstream-source matches for crypto_mining and
  tunnel_service, not renamed/encoded artwork. Every excluded slug and reason
  is in `pulse_rings/BRANDS-LICENSE.md`; this is not a complete upstream set.
- Source icons follow the hero block's first metric/component feed. Destinations
  include `discord.com`, `cdn.discordapp.com`, `api.github.com`,
  `avatars.githubusercontent.com`, user-approved HTTPS JSON/icon URL hosts, and
  MCP HTTPS icon hosts **only when disclosed in the persisted approval budget**.
  Undisclosed MCP icon hosts are skipped; data rasters and bundled paths are local.
  Open-link hosts are separate from polling/icon consent.
- Background collection is default OFF. Opt-in collects approved feeds through a
  five-second daemon, not draft previews; toasts still need a visible Desktop.

## Catalog rules 3, 6–14 and 17 (historical baseline; MCP delta below)

| Rule | Verdict | Evidence / qualification |
|---|---|---|
| **3 — no self-update** | **PASS** | Runtime sources contain no downloader, eval/exec, shell/subprocess or fetch-and-replace path. Definitions are validated data, not adapters/code. `tests/test_presubmit.py::test_runtime_has_no_self_updater_or_credential_file_reads`; source review. |
| **6 — matching capabilities** | **PASS** | Real entrypoint registration is introspected in `test_authoring.py::test_real_entry_registrations_match_manifest`: exactly 4 tools (including pulse_rings_layout_check), 8 hooks, no middleware/required env. `test_presubmit.py` compares the catalog block to plugin.yaml. Validator explicitly reports tools/hooks/middleware match. |
| **7 — install scanner** | **PASS, caution reviewed** | `hermes plugins validate ... --install-deps`, exit 0, “Validation passed”; `validate.txt`. One warning: `sudo_usage (hermes.py:32)` and `(hermes.py:65)` is the literal `waiting:sudo` enum, not a command. See warnings below. No dangerous finding. |
| **8 — Desktop SDK only** | **PASS** | Validator desktop-surface pass; static greps reject eval/new Function/dynamic imports/remote URLs/core markup selectors/prototype writes. Imports only SDK/React; own `.pr-*` closest selectors. Browser harness reports zero remote requests and runtime/React warnings. No SDK sandbox claim. |
| **9 — no core overrides** | **No mutation; MCP warnings require review** | Path-unique package only; no core rebinding/table writes. MCP metadata shim reads private read-only/cost policy (connection-table reads now icons-only) and enters finite/OAuth safety scopes, preferring future ctx.tool_info and failing closed. Undocumented-core imports produce validator warnings; the historical clean-private-import receipt does not cover MCP. README/PR justify them; UPSTREAM-ISSUE-mcp-readonly.md requests a public seam (unposted). Final-tree validator/maintainer review pending. |
| **10 — dependency policy** | **PASS** | `python_dependencies: []`, project `dependencies = []`; runtime uses stdlib plus host-provided public APIs/FastAPI/YAML. Isolated test-only dependencies have upper bounds, CI excludes releases newer than three days. Validator dependency check passes. No fetched/bundled native runtime component. |
| **11 — Hermes credentials** | **PASS** | Optional Settings secret `PULSE_RINGS_GITHUB_TOKEN`, read via agent.secret_scope.get_secret, sent only to api.github.com. Background ticks rebuild and bind the registering profile's scope via documented build_profile_secret_scope/set_secret_scope, reset in finally; hosts lacking these APIs retain the existing path. No direct credential-file or env-token reads. requires_env empty. Tests assert token host binding and sentinel non-leakage; pre-submit grep forbids credential-file/env-token reads. Worker environment markers are noncredential execution metadata only. |
| **12 — approvals / unattended** | **PASS locally** | Tools cannot activate/import; strict human decision endpoints and typed local command. Messaging requires explicit stable sender grant plus host ACL. Cron/subagent/kanban/unknown-origin drafts never prefetch or wait; 7-day TTL/5-pending cap. HTTP tests exercise both engine and registered-tool zero-egress paths, corrupted eligibility and kind/adapter fail-closed guards. Actual gateway identity/auth integration remains a separate live gate. |
| **13 — disclosures** | **PASS locally; live behavior unverified** | README/PR-BODY disclose opt-in long-running daemon collection (default OFF), five-second ticks over approved HTTP/MCP/local sources, lease/OS-lock fencing, no background previews, 1.5s bounded stop and in-flight drain/no late persistence, context/Plugins-settings limits, off controls and visible-view-only toast delivery. `collection.lock` is a local lock file, not a host. Existing third-party hosts, eight count-only hooks, local DB/notes/icons, optional token, consented import, DNS/MCP workers, no shell/cron-model turns/telemetry/self-update remain disclosed. Public-surface evidence: BACKGROUND-SURFACE.md; controlled tests, not installed/live evidence. |
| **14 — truthful compatibility/version** | **PASS locally; remote verification open** | Both manifests declare >=0.22.7. Supplied Hermes checkout at 29a61cb7ab5 has nearest release tag v0.22.7; public APIs were checked in that checkout/tag. This floor is not newer than that known release. No online latest-release lookup (network forbidden) or clean minimum-version install claimed. One version-consistency gate covers maintained metadata; old recorded/legacy fixtures and intentional old-backend fault retain their original versions. |
| **17 — reviewable payloads** | **PASS** | MIT LICENSE exists. git tracked/nonignored candidate files are scanned for PE/MZ, ELF, Mach-O, wasm and bytecode/archive extensions/magic. No shipped .pyc/.pyo/executables/opaque archives. PNG test fixtures/screenshots are raster data, not executables. Ignored test caches/runtime dependencies are not in a clone at the pin. |

## WP13 Builder 2 API / lookup disclosure

- [x] Nine offline templates, field-level errors, offline Discord/GitHub/Steam
  link parsing, weather + air with imperial/metric units, complete validated
  ranked layouts and human-only lookup routes. Contract: desktop/CONTRACT.md,
  **Builder 2 API**. No new agent tool or approval path.
- **Builder-only city/game lookups (WP13):** a human Find click with literal
  confirmation sends exactly one query to `geocoding-api.open-meteo.com` (city)
  or `store.steampowered.com` (Steam game search). No request on mount, typing,
  template conversion, preview, or layout selection. These are pre-approval
  one-off lookups, not recurring feed hosts or a pulse approval. Each service sees
  your IP and query. One call per 3 seconds per profile/kind, 3-second deadline,
  256KiB cap, no redirects/retries/credentials; existing public-DNS-vetted,
  IP-pinned JSON safety path fails closed without Hermes safety APIs. At most
  eight projected results; city coordinates rounded to 2dp. Queries/results are
  response-local, never saved in plugin DB/files/logs; only profile/kind pacing
  timestamps live briefly in memory. Steam store links/app IDs parse offline
  with zero calls. The lookup does not approve the weather/air/Steam player
  polling URLs; those remain ordinary `http_json` drafts requiring review.
- [x] Verification: **74 Builder 2 tests passed**; full isolated suite
  **1,387 passed, 3 skipped**, one Starlette/httpx test-stack deprecation warning.
  Skips: MCP integration requires Hermes checkout + MCP SDK; two real scanner
  tests require HERMES_SOURCE. No fresh admission/live-service pass is claimed.
  Test-first route 404, limit-only default-selection, and malformed-link failures
  were observed before their fixes. Property-style checks cover every nonempty
  metric subset of all nine templates and selections through eight bindings.
  All five redirect codes exercise the real shared transport parser offline.
  Real preview Python bridge returned 9 templates / successful conversion /
  4 Steam layouts. `node --check preview/sdk-mock.js` and `git diff --check` pass.
  Complete reproducible offline responses: BUILDER-2-API-EXAMPLES.json, generated
  by scripts/builder-api-examples.py and checked against real FastAPI responses.
- [ ] Final merged renderer/API integration and fresh independent security review;
  no live install, Hermes restart, remote source query, push or publication here.

## WP12 public call_mcp / grant delta

### Hermes per-server grant (separate from pulse approval)

The operator must add the exact server, for example `metrics`, to
`plugins.entries.pulse-rings.mcp_allowlist` in Hermes `config.yaml`:

```yaml
plugins:
  entries:
    pulse-rings:
      mcp_allowlist: ["metrics"]
```

This is an operator setting, **not** `settings.mcp_allowlist`. Pulsr never
writes it or calls `ctx.set_config` to grant access. Approval and the Hermes grant
can happen in either order. Cards and the builder show **Hermes grant: Allowed in
Hermes settings** or **Not yet allowed — add "metrics" to
plugins.entries.pulse-rings.mcp_allowlist**. An approved pulse waits in
`needs_mcp_grant` without remote-failure/exponential-backoff spam. Builder Test call
explains the same requirement when refused. Hermes rechecks the grant on every
`ctx.call_mcp(server, tool, arguments, timeout=8)` call; revocation is respected.
The per-server grant permits more than read-only tools at the host level, so
Pulsr still independently refuses unmarked/write-capable or costed tools.

**MCP uses the public plugin API only (after the catalog review).** Polls and the
builder Test call go through public `ctx.call_mcp`. No private MCP module is
imported. Hermes has no public read-only/cost metadata for MCP tools yet, so the
`mcp.tool` source and MCP-declared icons stay off unless the host provides
`ctx.tool_info`, and turn on by themselves once it does. The earlier private
read-only, cost, no-prompt and icon lookups are removed; see
UPSTREAM-ISSUE-mcp-readonly.md for the requested public seam.

## MCP documentation / feature gates (0.5.0-dev)

- [x] README, normative source/read-model spec, authoring skill, changelog and
  submission disclosures describe `mcp.tool` against implementation at `afc6865`.
- [x] Bounds checked against kinds.py/mcp_params.py: exact names, JSON args ≤2 KiB,
  ≤32 keys/depth 6/128 nodes, 1–6 numeric pointers; minimum 5m/default 15m; one
  profile-counted call/poll, zero direct hosts and no automatic pre-approval MCP preview
  dispatch. Builder Test call is a separate human-consented exception, described below.
- [x] Disclose same-process connection requirement; no hosted Nous-gateway support;
  Hermes owns transport/sign-in, including OAuth. No connector credential reads.
- [x] Disclose explicit readOnlyHint, refusal of all declared spend policy, fail-closed
  metadata, no prompts/interactive OAuth, and other plugins' pre_tool_call hook
  bypass despite retained handler trust gates. Read-only is not a sandbox.
- [x] Disclose eight-second caller deadline, four worker slots/process, in-flight
  deduplication, non-killable stuck handlers, ignored late results and 256 KiB
  secondary post-return decoded-body cap; Hermes envelopes cap at ~64K chars. Raw output/args/errors excluded from sample state;
  args still persist in drafts/definitions, so never include secrets.
- [x] Reviewed supplied isolated real-stdio receipt:
  `$ARTIFACTS/pulse-rings/wp7-mcp/mcp-integration.json` — actual plugin
  discovery/proposal/engine+dashboard numeric selection/cached status, no raw
  persistence, write/missing/disconnected refusal and elicitation declined with
  zero terminal prompts. Local fixture, not production connector/remote OAuth or
  live Desktop approval evidence. Fixture sampling is explicitly disabled.
- [x] Draft public annotation/connection/approval seam request in
  UPSTREAM-ISSUE-mcp-readonly.md, naming private symbols and removal path.
- [ ] Parent/fresh reviewer: inspect final merged code and rerun full pytest plus
  `hermes plugins validate ... --install-deps` in an isolated scratch profile;
  record new private-import warnings by file/line, no guessed warning count.
- [ ] Parent: verify generated spec/pulse-1.schema.json includes `mcp.tool` on the
  final code branch (schema changes are outside this documentation worktree).
- [ ] Parent: decide server-initiated sampling policy; current safety scopes do not
  disable it. Retain the qualified “no Pulsr model calls” claim unless a
  stronger policy is implemented/tested.
- [ ] Authorized remote-provider OAuth/unavailable-sign-in test and live Desktop
  card/Details/readback capture; no such claim follows from the fixture server.
- [ ] Owner/maintainer: review private seams and post upstream issue only with
  separate authorization; do not describe a draft as an accepted catalog exception.

## WP6 resolution / invariants

- `http_json` is a registered Engine adapter, but never previewed before consent.
  Both kind policy and adapter flags fail closed in proposal and later preview ticks.
- The older “Hermes client unavailable means disabled” policy wins over WP6's
  standalone fallback: is_safe_url and create_ssrf_safe_async_client must both be
  importable/callable. No fallback exists when absent. Actual requests still use
  independent stdlib DNS-vetted numeric-sockaddr pinning with verified TLS SNI/Host,
  not the generic Hermes async client. Docs/disclosures say exactly that.
- Import GET builds a read-only plan; strict POST requires literal true/exact token,
  forbids path overrides, rechecks source/destination/admission and persists one-time
  marker atomically. Source hashes unchanged in synthetic tests; WAL/journal refused.
  Banner only probes existence/marker. No source write/disable or import-network call.
- UI shows skipped counts/recurring allocation before consent; success requires
  cached marker and exact planned IDs. Stale plans need cancel/reopen. Keyed profile
  card cleanup discards late responses and avoids new-profile cached readback.

## Documentation verification on wp7-docs

- Requested check: `python -m pytest -q tests/test_presubmit.py tests/test_opus2_copy.py`
  using the supplied scratch virtualenv: **15 passed**.
- Focused docs/MCP/authoring/contract check (same command plus test_mcp.py,
  test_authoring.py, test_contract.py): **89 passed**.
- Broader run adding test_spec.py: **243 passed, 4 failed**. All four failures were
  reproduced by identity/cause in a clean `git archive afc6865` scratch snapshot:
  `test_minimal_presets[mcp.tool]`, `test_schema_shape_conformance`,
  `test_metadata_policies_and_copy_isolation`,
  `test_duration_minima_and_preset_isolation`. The test helper lacks MCP params
  and the old preview-policy assertion assumes only http_json has no preview.
  Code/test updates belong to the parallel code branch, not this docs commit.
- Static schema at afc6865 has no `mcp.tool` entry; parent must regenerate it.
  No final-schema conformance, fresh validator, browser or remote OAuth run is
  claimed by these checks. Documentation diff passes `git diff --check`.

## Historical pre-MCP validator receipt / warnings

Receipt root: `$ARTIFACTS/pulse-rings/fix2/`.
Command (run once for this remediation, offline, isolated artifact data root):

```sh
HERMES_HOME=$ARTIFACTS/pulse-rings/fix2/validate-home UV_CACHE_DIR=$ARTIFACTS/discord-pulse/uv-cache UV_OFFLINE=1 hermes plugins validate . --install-deps
```

**Exit 0, Validation passed; 0 failures, 1 caution warning.**
- `sudo_usage (hermes.py:32)` and `(hermes.py:65)`: enum `waiting:sudo` used to count an existing
  human-input wait kind. No sudo/elevated command or shell is invoked. Do not
  rename/obfuscate the enum merely to silence a lexical scanner.
- `Isolation — runs in the plugin host ... buffered responses` is informational,
  not a warning. The validator prepared its isolated dependencies in the artifact
  data root; nothing was installed into the user's live plugin/profile directories.
- The `0.5.0-dev` prerelease label is intentional. This validator did **not** emit
  a version warning; do not copy the earlier WP5 warning count into this report.

## Historical pre-MCP test/browser receipts

All counts below come from actual local receipts, not mock tool responses. The
Python warning is the test-stack Starlette/httpx TestClient deprecation, not a
source-network or production warning. The original WP7 test-first records remain under `wp7/`; FIX-1–FIX-8 red captures and final verification are under `fix2/`. Added regressions are inverted review probes, not a claim that every historical test followed a test-first cycle.

- Python: **509 passed, 0 failed, 0 skipped; 1 dependency warning** (`pytest-final.txt`, `pytest-final.xml`).
- Browser: **138 checks passed, 0 failed**, zero remote requests, zero runtime/React
  warnings (`screens/browser-results.json`, `browser-final.txt`); mocked SDK/REST.
- Golden: **17 sequences / 64 steps**, recorded fixtures plus **37 real snapshots
  in three guilds**; exact numeric oracle comparisons, not identical presentation
  strings or all synthetic first-sample behaviors.
- `fixtures.txt`: 10 Engine.status-generated fixtures, including real importer.plan
  on an explicitly synthetic old DB. No hand-edited counts/scores or live data reads.
- Node syntax, Prettier renderer check and git diff --check pass locally. CI is
  `.github/workflows/ci.yml` (isolated Python + pre-submit + node --check), not a
  claimed remote Actions execution. Browser screenshots are harness-only evidence.

## Publication / live gates (not silently checked off)

| Gate | Verdict | Next authorized action |
|---|---|---|
| Owner consent to create/publish repository | **FAIL / pending** | Explicit owner approval; no creation/push in this task. |
| Rule 2 exact public pin | **FAIL / pending** | Replace TODO_PUBLISHED_40_HEX_SHA in catalog-entry.yaml after publication. Placeholder is deliberately not a fake valid SHA. |
| Fresh independent security review | **FAIL / pending** | Parent/fresh reviewer must inspect final diff; focused subagent only self-reviewed. |
| Live minimum-version/gateway/Desktop hooks, create→approve and import | **FAIL / pending** | Separate authorization to install/enable/restart and use live data/network. |
| Messaging sender identity and real secret resolution | **FAIL / pending** | Live owner-approved integration checks; fixture tests are not this evidence. |
| User taste check / real screenshots / demo | **FAIL / pending** | Review harness then capture real Hermes window; record the actual demo. |
| Catalog image URLs | **FAIL / pending** | Upload reviewed images with consent; at most six pinned GitHub URLs. See SCREENSHOTS.md. |
| Catalog PR, Actions, hackathon submission | **FAIL / pending** | Publish exact pin and submit with approval; no posts/PR/remote CI claimed. |

## WP11 core receipt (supersedes the historical scanner failure)

The real `hermes_cli.plugin_validate.validate_plugin_dir` admission engine passed
with **exit 0 / ok:true**, using an isolated `HERMES_HOME` under
`$ARTIFACTS/pulse-rings/wp11-fix-core/validator-home`. This directly
executes all admission checks, including capability registration and the actual
install scanner; it is **not** a CLI `--install-deps` dependency-preparation receipt.
No live installation/restart or publication was performed.

Final full isolated Python suite: **1,295 passed, 1 skipped**, one TestClient
stack deprecation warning. The real MCP integration skip requires the MCP SDK
in the isolated test Python; HERMES_SOURCE was supplied. The real scanner tests
ran, not skipped. Byte-identical scratch artwork rebuild passed. A database
created by actual `3230ea9` code migrated with original sample/definition bytes
preserved; a source-changing replacement then returned empty compatible history
while retaining the archived sample.

Remaining warnings are not dangerous: the literal exclusion-policy regex in
`scripts/ARTWORK-SCOPE.md` is a `crypto_mining` **caution**, `sudo_usage` identifies
the existing activity metric enum (not execution), and MCP private imports remain
explicit compatibility warnings needing maintainer review. No scanner guard was
modified/disabled, no files hidden from it, and no artwork names encoded/renamed.
Two records are genuinely absent: full exclusions/reasons are in BRANDS-LICENSE.md.

Commands, red/green evidence, warning details and limits:
[WP11-CORE.md](WP11-CORE.md). P1-1/P1-2 renderer fixes belong to the sibling UI
worktree and require final merged validation/browser review; this core receipt
is not an independent security review or live Desktop acceptance.

## Historical WP10 background collection checkpoint

- Default-OFF config_schema switch, human-only strict settings route and cached
  readback, per-root process/SQLite/OS-fenced collector, viewer fallback and status
  fields are implemented. README/PR disclose lifecycle, calls and shutdown limits.
- Final isolated full suite: **1247 passed, 1 skipped**, one TestClient dependency
  warning. Browser suites: **145 widget / 241 blocks / 91 builder / 17 background**,
  zero remote requests/runtime warnings. No installed/live integration claim.
- **Catalog validation FAILED at that checkpoint:** dangerous `crypto_mining` and
  `tunnel_service` matches in unchanged `brands.json:1`; existing `sudo_usage`
  names and MCP private imports also reported. The exact same validation failure
  was reproduced on a clean `git archive cd8fee9` scratch snapshot. This supersedes
  the historical clean scanner receipt for current admission purposes; do not
  submit until parent/maintainer resolves it. Background config/registrations,
  no-core-override and Desktop-surface checks passed. Full commands and source
  evidence: [BACKGROUND-SURFACE.md](BACKGROUND-SURFACE.md).
- Runtime uses only source-public context cleanup/config APIs plus stdlib owned
  lifecycle; no private host scheduler, core edits, cron/model turns or shell child.
  Independent concurrency/security review and live Desktop/gateway checks remain
  open, including process-local context availability for pane setting writes.

## Historical Opus re-review FIX-1–FIX-8 — local verification

- [x] Eight ordered local Conventional Commits, one per FIX; Share YAML implemented (option a).
- [x] Inverted regressions for deferral identity, queued closes/timeouts, jitter/live counts, sharing/toasts, copy, human decisions/public URLs/text/links, skill registration/paths and status/schema/icon performance.
- [x] Approval card grouping/ARIA, calm breathing in both themes/reduced motion, and honest one-sample details checked by the browser harness.
- [x] Main-only review probes, unchanged assertions and path-only retargeting: **47 fail (fixed), B7 alone passes intentionally**. Frozen review artifacts were not edited.
- [x] Original 24-pulse workload: construction **1.9 ms**, full status **83 ms / 83 KiB**, compact **75 ms / 38.3 KiB**; target <150 ms and <120 KiB met.
- [x] **509 pytest / 138 browser checks**, zero external renderer requests or runtime warnings.
- [x] `hermes plugins validate . --install-deps` passed once in isolated `fix2/validate-home` with offline caches. Only cautions are local `sudo` activity metric names.
- [x] Screens regenerated under `$ARTIFACTS/pulse-rings/fix2/screens/`; logs beside them.
- [x] Local-only changes: no installed plugin, gateway/Desktop restart, live network, push or publication.
