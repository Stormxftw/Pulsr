# WP1 → engine interface

## GitHub repo activity interface

`github.repo` adds opt-in boolean params `activity` and `ci` (default false,
missing flags are not inserted into normalized legacy definitions). `metric_params`
restricts commits_week/hours_since_push to activity and ci_passing/ci_running to ci.
`source_baselines.commits_week = sample.baselines.commits_week` declares the prior
12-week participation mean. `poll_calls: [{calls: 1, when_param: ci}]` adds only the
enabled Actions allocation; `periodic_calls: [{every: 3600, calls: 1, when_param: activity}]`
adds hourly participation. Base calls_per_poll stays 2. Minimum is 10m; default
stays 15m. At 10m both enabled is exactly 19 req/h; legacy default stays 8 req/h.
Feed disclosures add plain-text `calls` only on opt-in; the approval card displays
that explanation alongside exact params/hosts/allocations. No new hosts/secrets.


`parse(text: str | bytes) -> dict` reads JSON or safe YAML, bounded to 16 KiB UTF-8. `validate(definition) -> list[{path, message}]` never normalizes/mutates its input. Paths use JSON Pointer (`/source/params/repo`); root is the empty string. `normalize(definition_or_text) -> dict` raises `ValidationError` (`.errors`) on invalid input. `parse` also raises this error. `budget(definition_or_text) -> {hosts: list[str], req_per_hour: float, req_per_hour_display: int}` validates and expands first.

Normalized definitions retain the published `pulse/1` shape (not status rows): `pulse`, `id`, `title`, `source: {kind, params}`, `every`, `ring: {components}`, `capsule`, `lines`, `icon`, optional `link`/`alert`, and preserved `x-*` extensions. Kind aliases `kind@1` normalize to the bare canonical kind; only major 1 is supported. `every` and delta `window` remain duration strings; use `duration_seconds(value)` to obtain integer seconds. Defaults are fully expanded, including component direction/window/floor/sensitivity, line `show`/`hide_when_zero`, and alert `notify`. No approval/state/sample data is added. Normalization is idempotent and makes a deep copy.

`KINDS[kind]` exposes `params_schema`, `metrics`, `preset`, `min_every` (seconds), `default_every` (duration), `hosts`, `calls_per_poll`, `periodic_calls` (`{every, calls}`), and `pre_approval_sample` (`True`/`False`/`None` for local). Presets are deep-copied before use; `http_json` and `mcp.tool` use their first declared metric. Discord budgets include one widget call per 15 minutes only when `voice` is true. GitHub search includes one baseline call per 6 hours. Icon/avatar fetches are one-off, not recurring requests/hour. GitHub avatar hosts are declared when `icon: source` under the display extension (0.5.0-dev). Hosts are declared, not contacted here; runtime DNS/connect-time SSRF checks remain mandatory for direct HTTP adapters. `mcp.tool` has dynamic metric names from params, minimum 300s, default 15m, hosts `[]`, one call/poll, no periodic calls and `pre_approval_sample=False`; it delegates transport to Hermes, not the HTTP client. `desktop.notifications` has fixed metrics `waiting`, `new_1h`, `new_24h`, `minutes_since_last`, minimum 30s, default 1m, hosts `[]`, zero calls/poll, no periodic calls and `pre_approval_sample=None`; its adapter reads the local Windows notification store/registry read-only (counts and times only) and never uses `net`. Its disclosure target is exactly `this PC · ` followed by the `apps` then `app_ids` entries joined by `, `.

Ambiguity resolved: intervals below a kind's minimum are draft errors (WP1 acceptance criterion), not silently raised (§3.2). The schema is normative for shape; cross-field semantic constraints (weight sum, metric references, source baseline support, public-address checks) require `validate` as well. `pulse: 2` is a validation error; persisted unsupported-version rows must be preserved by the store/status layer, not silently imported by this parser.


## MCP disclosure enrichment (0.5.0-dev)

Full MCP pulse rows, MCP draft reads and MCP create-draft results add an ephemeral
`mcp` object, recomputed from host policy rather than stored in samples/state or
metadata:

```text
{server: string, tool: string, read_only: boolean, args_display: string,
 hermes_allowed: boolean, grant_message: string, reason: string | null,
 transport: "via Hermes MCP connector (Hermes handles sign-in)"}
```

`read_only=true` means the live availability/read-only/no-approval policy passed,
not merely that a definition requested a badge. Unavailable host metadata yields
false plus a sanitized static reason; no dispatch occurs during enrichment.
`args_display` serializes the definition's args with sorted keys, compact JSON
and `ensure_ascii=True`; after 512 characters it appends
`… [truncated; review full definition]`. It is text, not HTML; full args persist
in the normalized definition. MCP `budget.hosts=[]` MUST be labelled **no direct
network hosts**, not **local only**. MCP drafts have no automatic MCP preview
dispatch; builder Test call is a separate consented inspection. The compact agent status tool keeps its
existing whitelist; do not assume it includes `mcp` enrichment.

The MCP adapter returns `SourceResult(sample={ts, metrics, baselines: {},
unknown_reasons})`, with no output/args in source state or metadata. Numeric
selection, host requirements, deadlines/deferrals and result envelopes follow
PULSE-1.md's MCP tool section. The adapter calls public `ctx.call_mcp(server, tool, arguments, timeout=8)`, not
`net.call`: a `net.reserve('mcp:' + server)` reservation accounts for each call
without implying direct HTTP egress or invoking other plugins' pre-tool hooks.

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

## Replacement observation identity

Samples are keyed by `(pulse_id, feed, generation, ts)`. A persisted generation
belongs to the feed name and the canonical kind/params fingerprint (including
URL, server/tool/args and numeric JSON-pointer meaning). Changed identity, removal,
rename, or reuse after removal starts a new generation: no old current, previous,
spark, baseline, auto-range or learning evidence is used. Until compatible measured
samples exist the feed is warming/unknown and auto scales are learning. Archived
samples remain on disk under their old generation until ordinary seven-day pruning;
they are not exposed as current history. Every poll claim carries its generation;
late successes, failures and deferrals from replaced/removed generations are
ignored atomically before state/sample writes. No fabricated zero is inserted.

Unchanged identity retains samples and source state for layout/theme/title/cadence
edits, including legacy single-source `main` replacements. Switching between
implicit `source` and explicit `feeds.main` with the same identity preserves those
observations. Existing pre-generation databases migrate their payload bytes to
the initial generation without rewriting history; this cannot retrospectively
identify source contamination that predates this migration. New approvals and
imports allocate a generation before inserting their observations.

## Frozen runtime contract

Adapters emit source baselines only as `sample.baselines[metric]` (finite numeric
value). `KINDS[kind].source_baselines` documents those metrics and their sample
path; another metric named `baseline` is display-only, never read implicitly.
Storage and status use bare canonical kind names. Activation and proposal persist
normalized definitions and server-computed budgets; neither validates on a read.
`admission(active_budgets, draft_budget, ceiling=300) -> list[{path,message}]` is
pure; activation rechecks it within its cap transaction, excluding the replaced ID.

`GET /status?poll=0` is a pure cached read; default poll refreshes at most one due
source while background collection is OFF (the default). The opt-in plugin setting
`background_collection` uses a five-second daemon loop, at most one approved due
feed/tick through the same `poll_one_due(previews=False)` path. Drafts/previews
never run on this worker. A process mutex, nonblocking OS file lock and SQLite
lease fence duplicate scheduling (including a call that outlives the 30s lease).
When ON and the lease is alive, viewed status uses cached approved samples; an
eligible preview can still use the single viewed operation. A stale lease permits
at most one ordinary due claim. Empty/paused sets make no source/icon calls;
locked DB claims use a 50ms busy timeout and 5–60s backoff. Default-OFF viewed
polling and an in-flight draining worker also share the OS fence.

`collection.mode` is the saved opt-in; lease_holder_alive means lease expiry is
in the future, not guaranteed source availability. last_tick_ts marks an admitted
tick (possibly empty), not a successful fetch. Actual feed freshness remains
last_ok_ts. Public ctx.get_config/set_config persist the config_schema bool;
human PUT `/settings` requires strict bool background_collection plus literal
confirm:true, rejects extra keys, reads back the setting, and starts/stops collection.
GET `/settings` returns saved bool and process-local writer availability. No
context means 503 on writes; no private config writer. Stop/unload/atexit signal
cancellation and wait at most 1.5s; an in-flight call may drain but cannot launch
another gated request or persist a late sample. Background alert data derives from
samples; Desktop toast delivery still requires a visible view.

Each source poll and each status row is isolated. Local pacing/ceiling
429s are deferrals with `next_due`, not failures, errors or backoff. Remote rate
limits preserve the last arc; catch-all failures use sanitized internal-error copy.

Top-level: `api_version`, `as_of`, `pulses`, `drafts`, `budget` (used, ceiling,
active_req_per_hour, remaining_req_per_hour, admission_unknown), `features` (boolean import_discord,
share_yaml, import_yaml), `collection` (mode: viewed|background, lease_holder_alive: boolean,
last_tick_ts: Unix seconds|null), `error` (poll boundary error or null), `source` (trust label).
No legacy servers/curated aliases are emitted. Compact tools omit notes, histories and icons, but keep exact id/note_path for the registered pulse-notes workflow.
Each pulse has id/title/kind/state, ring/capsule/lines/alert, history (last 48),
optional `trend` and `voice` (below),
icon_url (hash-keyed relative REST route), null icon_data, last_ok_ts/next_due/backoff_until/error, budget, every/link/icon/note/note_path.
`ring.unknown` is true iff every component is unknown; unknown is never calm.

`trend` (pulses without `display`; null until two points exist; omitted by compact
tools) compares today with yesterday for the capsule metric. It is display only and
never feeds a score or an alert: `{metric, window_seconds: 86400, bucket_seconds:
1800, points, previous, low, high, latest, yesterday}`. `points` covers the 24 hours
ending at the last measurement and `previous` the 24 hours before that, each a
list of `{ts, value}` half-hour means in time order; a half hour with no sample has
no point. `low`/`high` are points of `points`; `latest` is the exact last
measurement. `yesterday` is `{value, delta, ratio}` from samples within 45 minutes
of one day before `latest`, or null when none exist; `ratio` is null when that
value is zero. Read through one bounded SQLite aggregate, not raw history.

`voice` (`discord.invite` with voice on) is `{state, users, channels, capped}`:
`available` with counts of listed members in a voice channel and of distinct
active channels; `unavailable` when the server's public widget is off; `pending`
when not checked yet, stale or retrying. `capped` is true when the widget returned
its full member list (100), making `users` a minimum. `users` is null for state
saved before people were counted. It is a summary, not a metric: it is not stored
in samples, scored or alertable, and no member data is kept.

Every draft has `id`, `status` = pending|approved|rejected|expired, normalized
`definition`, persisted server `budget` (hosts, exact req_per_hour, integer
req_per_hour_display), parsed object `origin`, created_ts/expires_ts/decided_ts,
replaces/note/sample, remaining_req_per_hour, and `preview`: a full pulse status
row computed with the same engine functions (even for a single sample), or null
when unavailable. Optional yaml/auth/diff are display enrichment. Missing budget
fails closed: **Network: unknown — cannot approve**. Decided/expired rows are
retained in the bounded draft readback, never shown as actionable pending cards.

Draft reads additionally return ephemeral `disclosure: {feeds, icon_hosts}`. Each
feed row has `name`, canonical `kind`, exact `target` (HTTP full URL, GitHub repo,
Discord invite, MCP server/tool, or this profile), complete normalized `params`,
`every`, exact `req_per_hour`, and `hosts`. GitHub search type/query/filter/window
are in `params`, not inferred from a preview. Legacy source definitions have a
single `main` row. Rates reuse the authoritative budget arithmetic (including
periodic calls); icon hosts are separately identified as one-off and remain in
the durable draft budget's host union.

Every MCP row additionally has fresh server-side `mcp` policy enrichment:
`server`, `tool`, strict boolean `read_only`, `reason`, `transport`, `args_display`
(explicit truncation marker), and `args_full` (complete sorted, ASCII-escaped JSON).
This uses the feed's `adapter_definition` and current profile-bound policy, never
an `x-*` claim or persisted badge. Reads do not dispatch connector tools. Missing
or incomplete disclosures, unknown/mismatched allocations/hosts/cadences, absent
full MCP args, any MCP policy other than literal `read_only:true`, or a missing
budget disable Desktop Approve with a visible reason. Reject remains available.
This UI consent gate supplements, not replaces, backend approval/polling policy.

Cached status uses one SQLite connection and bounded histories. Schema DDL/migrations are cached per process/root/database identity and invalidated by a changed SQLite schema cookie. `GET /icons/{guild_id}-{hash}` returns validated cached raster data with an immutable cache policy; it never makes a remote request. Renderer SDK loading is cached by hash/profile. `GET /pulses/{id}/definition` returns `{yaml}` for the normalized saved definition without polling. Human decisions POST `{confirm: true}` to the draft approve/reject routes; legacy `/servers` activation routes are absent.

## Display extension (0.5.0-dev)

`DISPLAY.md` adds mutually exclusive `feeds` (1–3 named sources, each with its own
normalized `kind`, strict/defaulted `params`, and `every`) and `source`, plus optional
`display`, `theme`, and icon objects. `feeds` requires 1–4 display blocks and never
receives legacy `source`/`every`/`ring`/`capsule`/`lines` defaults. Source pulses keep
all legacy presets; display refs use implicit feed `main`. Single-feed bare refs
become `feed.metric`. Blocks are score/rings/bar/bars/stat/spark; their defaults,
scale ownership and style allowlists are specified in DISPLAY §§1–3. Style/theme
hex colours are lowercased without expanding renderer defaults. Shared bars keep
scale defaults on the block, independent bars and rings on items.

Public `spec.feeds_of(defn) -> {name: {kind, params, every}}` returns a deep-copied,
default-expanded feed map (including `main` for source pulses). It accepts valid
raw or normalized definitions. `spec.bindings_of(defn) -> list[(json_pointer, ref)]`
returns display value/bound/component refs and alert refs in document traversal
order, qualifying unambiguous bare refs without mutation. The eight-binding cap
counts only display bindings, including repetitions. Legacy source-only bare alert
metrics remain bare in stored normalization for compatibility; the helper still
reports their canonical refs. Both validation passes are offline and non-mutating;
normalization remains an idempotent deep copy.

`budget` sums exact recurring per-feed request rates (including periodic calls),
then rounds only the total display figure. Hosts are the sorted union of direct
feed hosts, optional icon URL host, and `avatars.githubusercontent.com` when any
GitHub feed uses `icon: source`. One-off icon fetches add no recurring requests.
Icon objects select one brand/url/emoji form (plus `x-*` extensions); brand validation
uses `brands.has_brand(slug)` and `brands.suggest(slug)`. Register the added
`pulse-auto-window`, `pulse-icon-url`, and `pulse-emoji` format assertions alongside
existing `FORMAT_CHECKS` when using the published JSON schema; semantic validation
is still required for refs, weights, scales, zones and bundled-brand existence.

### Hermes MCP grant and result envelope

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


MCP enrichment adds `hermes_allowed` (boolean) and `grant_message` (static copy).
Single-source and multi-feed status expose `needs_mcp_grant` while operator consent
is missing; failure counters/backoff are not incremented. Read-only policy and
Hermes grant are independent booleans; a missing grant never disables Approve.
Pointers select present `structuredContent`, else once-decoded `result`; truncated
call_mcp envelopes are all-unknown with a clear reason and no partial parsing.
