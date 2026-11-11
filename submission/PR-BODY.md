# Add Pulsr — “Hermes, keep an eye on this.”

### WP17 opt-in repo activity disclosure

Existing github.repo normalization/preset and default 8 req/h stay unchanged.
`activity=true` adds commits_week with a source-declared prior-12-week mean and
hours_since_push computed/refreshed from cached pushed_at; `ci=true` adds
ci_passing/ci_running. Same api.github.com host: GET repo + pulls = 2 calls/poll;
GET stats/participation = hourly (+1 req/h, including 202 attempts) only with activity;
GET actions/runs?branch=<default_branch>&per_page=1 = 1 call/poll only with ci.
At 10m allocations are 12/13/18/19 req/h for neither/activity/CI/both; default 15m
allocations are 8/9/12/13. Push age costs no extra call. Bundled GitHub artwork is
offline; source avatars retain separately approved avatars.githubusercontent.com.
Private token remains only agent.secret_scope.get_secret('PULSE_RINGS_GITHUB_TOKEN');
user supplies fine-grained repo contents/metadata read plus Actions read. No new
credential storage, hosts, shell commands or background processes. 202/no runs/no
Actions access remain unknown; while newest CI runs, no older conclusion is fetched.
Builder has three opt-in checkboxes and Repo activity preset; states and duration
are validated data-only stat formats. Example: examples/e-repo-activity.pulse.yaml.


Full disclosure notes, kept with the source: https://github.com/Stormxftw/Pulsr.
Version: **0.5.0-dev**. The catalog pull request carries a shorter summary, the
pinned 40-hex commit and the screenshots; this file holds the detail behind it.

## What it does

An agent drafts a declarative pulse/1 definition, the human approves its source
and network allocation, and a right-side ring shows unusual activity beside the
actual measured count. Built-ins: public Discord, GitHub search/repo, Hermes
activity, human-approved public JSON and connected read-only MCP tools. Pulse
Rings makes no model calls/tokens per refresh; server-initiated MCP sampling is
a separate Hermes connector setting and may incur model use.
Includes an optional one-time Discord Pulse history/notes/icon importer, with
read-only plan, explicit consent/token, immutable source reads and cached readback.
See spec/PULSE-1.md for the data standard. No executable definitions/remote code.


## WP15 session-pulse delta (local implementation, not installed)

- `show_sessions` is default OFF. An authenticated human switch uses strict
  `PUT /settings` consent and a saved-setting readback; no agent decision tool.
- `GET /sessions` returns bounded, ephemeral session ids/hashes, states, counts
  and timestamps only. The reserved `hermes-sessions` group uses the normal
  arrangement (expanded rows/collapsed four-column rings), not a standalone section;
  subagents aggregate into parents and Done expires after 15m. Opt-out removes the
  group. Local layout may store hash references/group preferences, never raw ids,
  titles, counters or times. Rename/collapse/order use `/layout` save/readback.
- Local data access is disclosed in README: no prompts, transcripts, tool contents,
  goals or remote requests. Titles use public `session.list` RPC. Raw ids/titles
  are memory-only for chat focus/rendering; disabling clears them. Existing
  `background_collection` remains independent. `sessions.updated` is a local
  event name, **not an egress host**, carrying only an empty invalidation payload.
- Official hook union is now eleven hooks (the original eight plus
  `on_session_start`, `on_session_finalize`, `post_llm_call`). Missing hooks fail
  soft. Desktop uses SDK busy/focused identity atoms, React Query, `host.request`,
  documented `host.openSession` (missing API fails soft), and visibility cleanup.
- Host sources checked: `hermes-agent` at `v0.22.7-90-g29a61cb7ab5`, isolated
  `hermes-v0.23.0` at `v0.23.0`; no minimum-version install or live renderer claim.
  No new private imports. Real SDK tooltip focus requires keyboard modality plus
  `:focus-visible`; collapsed-circle tests enter with Tab and retain metadata assertions.
- Calm tapered comet/breath/ripple/done tick, None/Lively and reduced motion;
  off-screen/hidden pause and bounded compositor usage have browser assertions.
  Screenshots plus frame strip are synthetic local preview evidence, not live data.

## Local arrangement disclosure (WP15)

`GET /layout` and strict `PUT /layout` read/write this profile's plugin-owned
`layout.json`: bounded group titles, collapsed flags and pulse-id order, never
pulse definitions or approvals. This is local UI state, not a network host.
Same-directory `layout-*.tmp` staging plus atomic replacement and the existing
SQLite write lock protect saves; a SHA-256 revision rejects stale writes (409).
Removed refs are pruned/new approvals append on read. No source calls, collector
startup, cross-profile reads, sharing, shell commands, processes or dependencies
are added. Pending human decisions remain outside groups. Invalid local files
are preserved and fail closed. Renderer persistence is optimistic with rollback,
quiet notification and GET readback. This is tested in the local preview harness,
not installed/live Desktop evidence.


## Public surfaces used

- register_tool: four tools — pulse_rings_status, pulse_rings_catalog,
  pulse_rings_propose, pulse_rings_layout_check.
- register_command: /rings (list/show/approve/reject); register_skill: authoring
  and pulse-notes. No approve/import tool or middleware.
- register_hook: the eight observer hooks listed in the disclosure below.
- Public PluginContext.call_mcp(server, tool, arguments, timeout=8), with the captured
  profile context; on_unload releases the binding. No direct MCP transport.
- Public plugin_storage, get_secret, get_hermes_home and plugin-event broadcast;
  public URL-safety helper/API availability plus independently pinned HTTP transport.
- Desktop SDK: right PANES_AREA (248 px), TRANSCRIPT_DIRECTIVE_AREA approval card,
  palette, status-bar chip, workspace details, React Query, visibility/event cleanup,
  unsent composer insertion, in-app alert toasts, clipboard and Open links.
- Namespace-scoped plain-def FastAPI handlers inherit Hermes's enabled/auth mount.
  POST import is human-only. Source/destination paths cannot be supplied by a body.
- The loader registers only this plugin's path-unique package in sys.modules for
  relative imports; no Hermes/core alias or private registry/function is modified.

## MCP connector feature / safety boundary

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


`mcp.tool` turns finite numeric JSON Pointers from a user-configured MCP tool into
a pulse. The agent calls the tool through its normal Hermes path first to learn
the shape, then proposes exact server/tool/args. Pulsr makes **no automatic
MCP previews**; the separate human-consented builder Test call is a pre-approval
exception. The human card shows those identifiers/escaped args, a
live-policy read-only badge and “via Hermes MCP connector (Hermes handles sign-in)”.
Args over 512 displayed characters are marked truncated; full-definition review
is required. Default cadence 15m, minimum 5m; one request per poll (4 req/h default).

Calls require a connected tool explicitly marked `readOnlyHint=true`; missing
policy, write-capable tools and any declared spend/cost policy are refused before
dispatch. Finite-turn and interactive-OAuth suppression decline elicitation and
interactive sign-in rather than prompting. Hermes retains MCP handler trust gates,
but **other plugins' `pre_tool_call` hooks do not run** on direct-dispatch polls,
including airlock-style guards. Mitigations: read-only-only plus user approval of
the exact server/tool/args; neither is a sandbox against a dishonest connector.
Sampling is not disabled by these scopes; configure it in Hermes if model-free
operation is required.

Only the polling process's own registered MCP connection is usable. A separate
agent/dashboard process does not inherit it; missing connections report unavailable.
Nous-gateway hosted connectors (Gmail etc. via `tool_search`/`tool_call`) are not
yet supported. Eight-second caller deadline, at most four concurrent call workers
per process, one in flight per plugin root/server/tool. A hung handler is not
forcibly killed and holds a slot until return/process exit; late results never
persist. Hermes flags envelopes over ~64K chars as truncated; metrics become unknown without parsing.
A secondary 256 KiB decoded-body cap is post-return, not a streaming host-memory limit. Errors are sanitized; cached values survive. Raw output/args/server errors
never enter samples/source state/metadata/errors; args **do** persist in definitions.

### Rule 9 — read-only metadata shim, not a runtime override

The existing path-unique package loader only registers this plugin's package for
relative imports; it does not replace core modules or alter sys.path.

**MCP metadata compatibility shim (before → after WP12):** Hermes 0.22.7+
and v0.23.0 document public `ctx.call_mcp`; both polling and builder Test call now
use it instead of `dispatch_tool`. Neither version exposes the discovered
read-only/cost policy through a public plugin metadata API. Prefer future
`ctx.tool_info(name)`; missing/changed private safety seams still fail closed.

| Private seam | Before WP12 | After WP12 |
|---|---|---|
| `tools.mcp_tool_handlers._tool_is_read_only` | Positive discovered hint | Retained; no public equivalent |
| `tools.mcp_tool_scope._server_key` + `tools.mcp_tool._server_cost_policies` | Refuse every cost policy | Retained; host spend gates may charge within budget and prompt over budget |
| `tools.mcp_tool_scope._resolve_server_key` + `tools.mcp_tool._servers` | Connection-presence check **and** declared icon lookup | Connection-presence check removed; **icons only** remain |
| `gateway.session_finite.finite_turn_scope` | Decline elicitation | Retained; public call_mcp does not install a noninteractive scope |
| `tools.mcp_oauth.suppress_interactive_oauth` | Suppress interactive sign-in | Retained; public call_mcp can reconnect/auth-recover |
| MCP task `_tools` / `initialize_result` (icon_resolver.py) | Declared icon metadata | Unchanged; no transport/connection authority |

Public scoped registry lookup is retained for tool existence. `call_mcp` handles
connection failures/reconnects through its error envelope; we no longer inspect a
private connection table to decide if invocation is possible. Grant disclosure
reads `hermes_cli.config.load_config`, the same public accessor/tree used by
`call_mcp`: `ctx.get_config` is **settings-relative** and cannot read this
entry-level operator grant. Reads execute inside the captured profile context.

Source justification ([v0.23.0 plugins.py:502–566](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/hermes_cli/plugins.py#L502-L566)):
`call_mcp` checks the grant, calls the native handler and normalizes its envelope;
it does not install no-prompt scopes. [mcp_tool_handlers.py:123–208](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/tools/mcp_tool_handlers.py#L123-L208)
reserves charges within a spend limit and asks over it: documented spend-limit
preservation is **not** a guarantee of no spend/no prompts for unattended polls.
The handler copies the calling context for elicitation and performs reconnect/auth
recovery ([692–744](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/tools/mcp_tool_handlers.py#L692-L744)).
Finite turns decline consent in [approval_prompt.py:316–319](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/tools/approval_prompt.py#L316-L319)
via [approval_context.py:207–212](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/tools/approval_context.py#L207-L212).
OAuth otherwise defaults interactive and may open a browser; suppression prevents
that ([mcp_oauth.py:334–374](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/tools/mcp_oauth.py#L334-L374),
[811–820](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/tools/mcp_oauth.py#L811-L820)).

No host table/function is modified or rebound. Undocumented-core imports remain
validator warnings needing maintainer review, not a warning-free admission claim.
The narrowed [upstream issue draft](UPSTREAM-ISSUE-mcp-readonly.md)
requests public discovered read-only/cost metadata beside `call_mcp`; not posted.
A public no-prompt scope and icon metadata would remove separate residual seams.

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

## Rule-13 disclosure lines

- **Network, only for pulses you approve (except fixed-host previews, a consented builder Test call and the builder lookups below):**
  `discord.com` (invite counts, optional public widget), `cdn.discordapp.com`
  (server icons), `api.github.com` (repository/search counts), `github.com` (a repository's public
  release feed, for a GitHub releases pulse), and for `http_json` and `web.feed`
  **user-approved HTTPS hosts**, exactly the full host/URL shown on the approval
  card. `avatars.githubusercontent.com` supplies GitHub owner/org avatars only
  after approval when disclosed in the persisted budget. Explicit icon URL hosts
  and MCP HTTPS icon hosts must be exactly disclosed too; undisclosed MCP hosts
  are skipped. MCP raster `data:` icons decode locally with zero requests.
  Bundled brands are offline CC0 Simple Icons artwork (trademarks remain owned;
  see `pulse_rings/BRANDS-LICENSE.md`). Network raster icons are PNG/WebP/JPEG, capped at
  256 KiB, MIME/magic checked, hash-keyed cached and failure-gated for six hours;
  remote SVG is refused. GETs are unauthenticated unless you add a GitHub token
  (never forwarded to icons). Redirects are refused, JSON responses capped at 512 KiB, arbitrary
  hosts use vetted public DNS answers and IP-pinned TLS. Services see your IP and URL
  identifiers. Interactive fixed-host previews dispatch **at most one gated call
  during propose and up to 2 per eligible fixed-host feed**, so **up to 6** for
  three eligible feeds across viewed ticks, only to discord.com or api.github.com,
  without icons/widget fallback. No arbitrary-HTTP or icon fetch before approval;
  a separately consented builder MCP Test call may reach its configured service.
  User-clicked **Open** links can open `github.com`,
  `discord.gg` or a definition's public ASCII-host HTTPS link in your browser; the Open host is disclosed separately from polling hosts. Legacy parsing also
  accepts `www.discord.com`, never as an automatic fetch destination.
- **MCP connectors:** no direct Pulsr network connection; public dispatch
  delegates the approved server/tool/args to Hermes's MCP client. The server may
  read private data/files or reach configured services; hosts `[]` is **no direct
  network hosts**, not local-only. Hermes owns stdio/HTTP transport, sign-in/OAuth
  and any server process; Pulsr never reads connector credentials. Read-only
  metadata/private compatibility imports and hook limitations are disclosed above.
- **Desktop notifications (`desktop.notifications`, Windows):** reads outside the
  plugin's own data, only for pulses you approve and never before approval: the
  per-user Windows notification store
  `%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db` (opened read-only:
  SQLite `mode=ro` + `query_only`, never copied or written) and per-app values under
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Notifications\Settings` and
  `...\PushNotifications` (`KEY_READ`). Only handler/notification ids, types,
  arrival/expiry times and on/off flags are selected; by default message text,
  senders, payloads, tags, groups and `NotificationData` are never queried,
  stored or logged. **No network requests.** Samples hold counts and minutes; source state
  holds notification ids, timestamps and the definition's own app ids. Unknown
  store formats, disabled notifications and non-Windows hosts report unknown, never zero.
  **Message previews (opt-in, off by default):** only a pulse approved with
  `preview: true`, whose approval card names `· message previews` in its target
  and says what is read, also reads the toast XML (`Payload`, `PayloadType = 'Xml'`)
  of the newest waiting toasts of its own apps: at most 5, the first two plain
  text lines (sender, text), each cut to 120 characters, payloads over 16 KiB or
  with a document type declaration skipped. This happens only when the pane asks
  for status, never during polling or before approval; the text is kept in memory
  for 4 seconds and goes to the pane only. It is never written to samples, source
  state, metadata, the plugin's database or files, logs or errors, and never
  appears in `pulse_rings_status`, the `/rings` command output or any other agent
  tool result. Turning it on (or off) is a new draft and a new approval.
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
  The weather/air template proposes `api.open-meteo.com` and
  `air-quality-api.open-meteo.com`; player counts propose `api.steampowered.com`.
  These hosts are contacted only after ordinary pulse approval, not by Find.
  `example.org` in form placeholders is illustrative, never fetched by the forms.
- **Budget:** every pulse shows hosts and requests/hour before approval. A
  profile-wide ceiling (default **300 requests/hour**) and per-host spacing apply.
  HTTP 429 and GitHub rate-limit resets are honoured and persisted.
- **Hermes activity:** observer hooks are `pre_llm_call`, `on_session_end`,
  `post_tool_call`, `on_human_input_request`, `on_human_input_resolved`,
  `subagent_start`, `subagent_stop`, `api_request_error`. Only event kinds,
  timestamps, enum outcomes, cron/subagent origin and salted hashes of session,
  request or child ids are recorded in this profile's database. Events retain
  48 hours and prune on next activity/read, not a worker; open pairs have TTLs.
  No prompts, commands, tool arguments/results or model output are stored by hooks.
  Only enabled processes in this profile are observed. Opening bookkeeping may drop under contention or lose recent counters on power failure. A bounded in-process queue retains hashed closing targets for replay when the recorder/database becomes available.
- **Reads/writes:** its own `<HERMES_HOME>/plugin-data/pulse-rings/` (SQLite,
  cached icons, Markdown notes) and shipped metadata. Samples retain seven days;
  history/notes survive unwatch. Banner checks old DB existence only. **Opening
  import review** reads `<HERMES_HOME>/plugin-data/discord-pulse/` read-only;
  **explicit confirmation** copies history/notes/validated icons. Never changes or
  disables its source; WAL/journal refusal prevents unsafe reads. No `.env`,
  `auth.json`, browser profile or other credential-store reads.
- **Credentials:** none required. Optional GitHub token in Settings → Plugins →
  Pulsr, stored by Hermes as `PULSE_RINGS_GITHUB_TOKEN`, read only through
  `agent.secret_scope.get_secret`, sent only to `api.github.com`, never logged,
  returned, embedded in definitions or sent to arbitrary hosts. MCP sign-in and
  refresh belong to Hermes; no connector tokens are received/stored by Pulsr.
  Never put secrets in MCP args: definitions/drafts retain them.
- **Agent authority:** four tools list cached status/the offline toolkit, validate
  layouts purely and propose drafts.
  No approve, import, change or remove tool. Activation is a human Desktop click
  or typed `/rings approve <id>`; messaging also requires explicit sender grants.
  Cron/subagent/kanban/unknown-origin drafts make no preapproval requests, even
  when later viewed, and expire after seven days. Human REST routes inherit
  Hermes authentication/enable/origin guards, never bypass them, and require a strict `{confirm: true}` body. `approver_ids` is a list of exact stable `platform:user_id` strings, never a substring-matched plain string.
- **Processes:** default OFF; optional **long-running daemon collection thread**
  wakes every five seconds for approved feeds only through the existing
  `poll_one_due(previews=False)` path. Same HTTP/MCP/local sources, budgets,
  ceiling, pacing/jitter/deferrals/backoff and MCP refusal gate; zero background
  draft previews and zero source calls with no active pulses. A SQLite lease plus
  process mutex and `collection.lock` OS lock fence overlapping polls, including
  slow calls beyond the 30-second lease. Locked claims back off 5–60s.
  Toggle off in Pulses → ⋯ → Background collection, or Settings → Plugins → Pulse
  Rings (`background_collection`, schema default false). Public `ctx.set_config`
  persists it, followed by exact readback; the human-only route requires StrictBool
  confirmation. Missing process-local plugin context returns 503, not a private
  config write. Generic Plugins OFF→ON takes effect at next plugin load/dashboard
  access; pane ON starts immediately. Public `on_unload` and `atexit` signal stop
  with a bounded 1.5s join. In-flight network waits may drain on the daemon, but
  cannot start another gated call or persist a late sample. No Python thread can
  forcibly kill a stuck MCP handler. Alert values derive from collected samples;
  toast delivery still requires a visible Desktop view. See BACKGROUND-SURFACE.md
  for why synchronous registration uses a plugin-owned daemon rather than
  loop-dependent public `spawn_task`. No runtime shell commands, subprocesses,
  cron/model turns, telemetry, analytics, usage reporting or self-updates.
  MCP polls use up to four daemon call workers per process; the
  caller deadline does not kill a hung handler (slot retained, late result ignored).
  Hermes manages its own configured MCP server processes.
  Temporary bounded DNS threads and a canceled per-request timer exist for
  approved http_json requests; late DNS never initiates HTTP. Sources refresh
  through viewed status requests by default or opt-in background collection;
  hooks record whenever your agents run.
  Developer-only preview/test commands launch local Node/browser processes.
- **Definitions are data (`pulse/1`):** nothing is executed, evaluated or rendered
  as HTML. Source text is untrusted data, not instructions.


### http_json contract resolution

WP6's standalone fallback was deliberately removed. Both public Hermes safety
APIs must exist and be callable; otherwise arbitrary HTTP is disabled. The helper
checks the origin; our own vetted numeric-IP/TLS-SNI/Host transport performs the
request, not the generic async client. This keeps fail-closed availability and
stronger DNS-to-connect pinning without implying transport delegation.

## MCP integration evidence (local, isolated fixture server)

`$ARTIFACTS/pulse-rings/wp7-mcp/mcp-integration.json` records real
stdio discovery/actual plugin registration, zero preview dispatch, approved
engine/dashboard numeric ring/capsule, cached agent status, no raw-result storage,
write/missing/disconnected refusal, and elicitation decline with zero terminal
prompt attempts. The server is a local test fixture, not a production connector
or a live Desktop acceptance click. The discovery spike at
`spikes/mcp-source/result.json` confirms the read-only hint is absent from public
schemas and the write tool was not executed. Neither receipt proves OAuth with
a remote provider, production connectivity or a final-tree catalog validator pass.

<!-- TODO(parent): review server-initiated sampling policy before retaining any
unqualified zero-token claim; the integration fixture explicitly disables it. -->

## Screenshots

Offline harness only; actual component, mocked SDK/REST. Recorded Discord/GitHub
inputs, synthetic edge/import scenarios. NOT live Hermes Desktop evidence.

- TODO attach screens/panel-dark-248.png and screens/panel-light-248.png.
- TODO attach screens/compact-56.png and screens/details-open-dark.png.
- TODO attach screens/approval-cold-sampling.png (Sampling…) and
  screens/approval-live-recorded-preview.png (recorded filled preview).
- TODO attach screens/import-consent-dark-248.png and screens/pending-248.png.

Full local inventory: submission/SCREENSHOTS.md. Keep the harness provenance labels.
The catalog allows up to six screenshots; pick six after review, pinning real
GitHub image URLs only once source/images have been published with consent.

## Documentation branch checks

Requested pre-submit/copy tests: **15 passed**. Focused pre-submit/copy/MCP/
authoring/contract run: **89 passed**. Broader run adding test_spec.py:
**243 passed, 4 failed**; the same four failures reproduced in an unmodified
`afc6865` scratch snapshot (missing MCP minimal helper and stale preview-policy
expectation). The static schema also lacks MCP at that base; parent code work must
update schema/tests before claiming final-tree conformance. Docs-only scope does
not modify code, tests or schema. `git diff --check` passes.

## Historical pre-MCP testing evidence (FIX-1–FIX-8)

Exact commands and receipts live under $ARTIFACTS/pulse-rings/fix2/.
The completed counts/validator warnings are recorded in submission/CHECKLIST.md.
- **509 Python tests passed, 0 failed/skipped**; one test-dependency warning
  (Starlette deprecates httpx TestClient), not a production warning. Isolated offline
  pytest with explicit pytest/FastAPI/httpx/jsonschema/ruamel.yaml.
- **138 browser checks passed, 0 failed**, zero runtime/React warnings and remote
  requests; **22 harness screenshots** regenerated from 10 Engine.status fixtures.
- **Final validator exit 0 / Validation passed**, one caution: `sudo_usage
  (hermes.py:32 and hermes.py:65)` is the literal count-only `waiting:sudo` enum, not execution.
  No core-override/desktop-surface failures. Full explanation in CHECKLIST.md.
- Registered capabilities introspection; pre-submit versions/hosts/renderer/payload
  greps; real import GET-plan/strict POST-consent/readback and source-hash tests.
- http_json wire-parser/pinned-connector, DNS/SSRF/redirect/deadline/cap tests; absent
  Hermes APIs disable fetching; engine and registered tools make zero preapproval
  HTTP calls even with corrupt draft preview eligibility.
- Golden oracle: 17 sequences / 64 steps, including all 37 real exported snapshots
  across three guilds. Exact numeric equivalence on recorded series; not a claim
  about all inputs or intentionally corrected first-sample level/presentation rules.
- Renderer syntax, formatter, engine-regenerated fixtures and offline browser
  harness covering consent, cached confirmation, stale plan, profile switches,
  widths/themes, accessibility/reduced motion and zero remote requests.
- hermes plugins validate --install-deps: local receipt, no install into Hermes.
- CI workflow runs isolated Python tests and node --check; no remote Actions run.

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

## Historical WP10 verification (superseded by WP11 receipt below)

Full isolated tests: **1247 passed, 1 skipped**, one dependency warning. Browser
checks: **145 widget / 241 blocks / 91 builder / 17 background**, no remote requests
or runtime warnings. No installed/live smoke or independent review is claimed.

**Catalog validation failed at that checkpoint**, including at an independently extracted
`cd8fee9` base: dangerous `crypto_mining` / `tunnel_service` lexical matches in
unchanged `brands.json:1`, existing `sudo_usage` names, and existing MCP private
import warnings. Background schema/registration/no-core-override/Desktop surface
checks pass, but this is **not** an admission pass. Resolve the existing scanner
blocker before posting. Exact commands and source evidence are in
[BACKGROUND-SURFACE.md](BACKGROUND-SURFACE.md).

## Still required before submission

Fresh independent security review (not available to this focused subagent), owner
UI taste check, authorized live gateway/hooks/create→approve/import/messaging and
secret-resolution checks; actual demo; public repo and published pin; image uploads.
This documentation work performs no push, repo creation, PR, install into the live
profile, restart or config change. The separate MCP fixture evidence above is not
a production-network/remote-auth test.

## Independent Opus re-review follow-up

FIX-1–FIX-8 are separate local commits: real GitHub deferrals, reliable observer closes/timeouts, bounded jitter/live activity, alert delivery and normalized Share YAML, singular/ratio copy, human-decision/URL/display hardening, registered pulse-notes with exact cached paths, and efficient status/schema/icon reads. Demo polish includes accessible approval-card grouping, calm breathing/reduced motion, and an honest one-sample details view. No legacy `/servers` activation surface remains.

Historical pre-MCP verification: **509 Python tests; 138 Chromium checks; plugin validation passed** (only the local `sudo.*` metric-name caution). Defect-present review probes: **47 fail (fixed), B7 alone passes by design**. Probes were retargeted by repository/temp paths only; review originals stayed read-only. Removed-entry-point probe failures are corroborated by inverted regressions on supported paths. Original 24-pulse workload: full **83 ms / 83 KiB**, compact **75 ms / 38.3 KiB**, construction **1.9 ms**. Status has no inline icon bytes or legacy aliases. Evidence: `$ARTIFACTS/pulse-rings/fix2/`; regenerated browser screenshots: `fix2/screens/`. No plugin installation, live-network smoke, restart, push or publication was performed.
