# pulse/1 — data-only sampled signals

**Version 1.** `pulse-1.schema.json` is normative for shape; this document is
normative for semantics. Examples A–D are conformance fixtures. A minimal pulse
contains `pulse: 1`, a plain-text `title`, and `source: {kind, params}`.

## Five MUST rules

1. **Data only.** Definitions MUST contain only JSON-compatible data: no code,
   expressions, scripts, executable YAML tags or HTML rendering. Every displayed
   string MUST render as text. Templates MUST use only the fixed placeholders below.
2. **Unknown ≠ zero.** A sampled metric MUST be a finite number, or `null` with
   a reason. Renderers MUST NOT turn unknown into zero or measured calm.
3. **Normal is observed or declared.** A baseline MUST be observed history
   (`median`/`oldest`), source-declared, or a fixed number. Renderers MUST identify
   which and show the actual observed span, never invent a full observation window.
4. **Declared egress.** Before approval, a definition MUST resolve to exact direct
   hosts and recurring requests/hour (or the exact Hermes MCP server/tool/args for
   delegated connector calls). `mcp.tool` MUST NOT automatically preview before
   approval. A separately human-consented builder **Test call** may inspect exactly
   one read-only/no-spend result before pulse approval, without persistence/retry
   or ordinary Net reservation; see INTERFACE.md for transient private-output bounds.
   Arbitrary-host `http_json` MUST NOT fetch before approval. Fixed-host Discord/GitHub
   may dispatch one gated call during propose and up to 2 per eligible fixed-host feed
   across viewed ticks, so up to 6 for three feeds, with counts shown; unattended
   cron/subagent/worker drafts MUST NOT make any pre-approval requests.
5. **Human activation.** Agents MUST create drafts only. Activation MUST require
   a human Desktop click or typed `/rings approve`. Changes MUST be new drafts.

## Shape, kinds and limits

`pulse` MUST be integer `1`. Unknown major versions are draft errors; existing
stored rows MUST remain visible as `unsupported_version`, not disappear. Kinds
accept bare names or `@1` pins; other kind majors are unsupported. Non-`x-` unknown
keys MUST be rejected; `x-*` values are preserved and ignored. YAML aliases,
duplicate keys, nonfinite values and non-JSON types are rejected.

| Field | Rule/default |
|---|---|
| `id` | `^[a-z0-9][a-z0-9-]{1,47}$`; defaults to title slug; collisions are change proposals |
| `title` | required, 1–60 characters, plain text |
| `source` | registered `kind`, strict `params` with kind defaults |
| `every` | positive integer `s`/`m`/`h` duration; kind default; below-minimum drafts are rejected |
| `ring`, `capsule`, `lines` | kind presets unless supplied; 1–4 components, ≤3 lines |
| `icon`, `link` | source/hermes/initials/one emoji; optional HTTPS click-only link ≤300 chars, never fetched |
| `alert` | optional threshold and `notify`; no alert otherwise |

| Kind | Params / minimum / declared egress |
|---|---|
| `discord.invite` | invite code or HTTPS discord.gg/discord.com invite; `voice=true`; 10m; discord.com + cdn.discordapp.com; 1/poll + optional widget/15m |
| `github.search` | `repo=owner/name`, `type=pr|issue`, optional safe `title_contains`/`label`, `window=24h|7d` (24h), `baseline_days=7..30` (14); 10m; api.github.com; 1/poll + baseline/6h |
| `github.repo` | `repo`, opt-in `activity=false`, `ci=false`; 10m minimum / 15m default; api.github.com; 2/poll + CI 1/poll when enabled + participation 1/hour when enabled |
| `hermes.activity` | `scope=profile`; 30s; no hosts or requests |
| `mcp.tool` | connected read-only `server`, `tool`, optional bounded JSON `args={}`, 1–6 named numeric JSON Pointers in `metrics`; 5m minimum / 15m default; no direct hosts; 1 Hermes MCP call/poll |
| `http_json` | HTTPS public `url` (port 443 only) ≤512 chars, no userinfo/headers/secrets/placeholders; 1–6 named RFC 6901 metric pointers; 5m; exact URL host; 1/poll |
| `web.feed` | HTTPS public `url` (port 443 only) ≤512 chars of an RSS, Atom or JSON feed, no userinfo/headers/secrets; fixed metrics; 15m minimum / 30m default; exact URL host; 1/poll |
| `desktop.notifications` | 1–8 curated `apps` aliases and/or exact Windows `app_ids`; `types=[toast]` (or `badge`); 30s minimum / 1m default; no hosts or requests; reads the local Windows notification store read-only |

Definitions MUST be ≤16 KiB UTF-8. Labels ≤40 chars. Metrics MUST reference the
kind's declared metric names (or the `http_json` / `mcp.tool` metric map). Durations contain at most
12 digits. Profile limits: 24 active pulses, 5 drafts, default ceiling 300 outbound
requests/hour, ≥2s host spacing. Poll jitter is positive 0–20%. Recurring budgets
exclude one-off icon fetches; declared hosts still include the enabled icon CDN.
Direct HTTP adapters MUST reject redirects and unsafe DNS/connect-time addresses; static URL
validation is not a DNS safety guarantee. JSON-only operation MUST work without YAML.

The checked-in schema includes `mcp.tool` and the display/feeds extension;
conformance tests compare it with the Python shape and semantic validator.

## GitHub repo activity (opt in)

`activity` and `ci` MUST be booleans, default false. Missing options MUST remain
omitted during normalization so existing source identities, presets and budgets
are unchanged. Stars/forks/open_issues/open_prs retain their meaning.

- `activity=true` declares `commits_week` from `GET /repos/{repo}/stats/participation`
  `all[-1]` (GitHub's current week, not a rolling seven-day count), plus source
  baseline `sample.baselines.commits_week`: arithmetic mean of exactly the previous
  12 entries, excluding the current week. Fewer than 13 valid counts means unknown.
  A 202/empty computation response MUST report **GitHub is still computing commit stats**.
  Attempts, including 202, are cached for at least one hour; no eager retries.
- `hours_since_push` is elapsed hours since `pushed_at` from the already fetched
  repo response. `current()` refreshes age without I/O or changing the measured
  sample timestamp. Missing/invalid/future timestamps remain unknown.
- `ci=true` declares `ci_passing` and `ci_running`, using exactly one call/poll to
  `GET /repos/{repo}/actions/runs?branch=<default_branch>&per_page=1`. Success on
  a completed latest run is 1; failure/cancelled/timed_out is 0. Queued/in-progress
  is running=1, completed is running=0. Other conclusions, no runs or an unfinished
  conclusion are unknown, never failures. Only the latest returned run is inspected;
  an older completed run is not fetched when a new run is pending. 403/404 MUST
  report **needs Actions read access**, without losing repo/activity measurements.
- Budget: `(2 + (1 if ci else 0)) * 3600 / every_seconds + (1 if activity else 0)`
  req/h. At 10m: neither=12, activity=13, CI=18, both=19; at unchanged default
  15m: neither=8, activity=9, CI=12, both=13. One-off icons are separate.
  No new host: API remains `api.github.com`; source avatars alone additionally
  disclose `avatars.githubusercontent.com`. Bundled GitHub artwork is offline.
- Private repos require the user's read-only fine-grained token through
  `agent.secret_scope.get_secret('PULSE_RINGS_GITHUB_TOKEN')` only. Repository
  metadata/contents read and, for CI, Actions read are needed. Never put tokens in
  definitions, definition-supplied headers, environment reads, fixtures or persisted adapter state.

## MCP tool

`source.kind: mcp.tool` (or `mcp.tool@1`) dispatches a tool already registered in
Hermes, never a definition-supplied URL, executable or connector configuration.
The params object MUST have `server`, `tool`, `metrics`; `args` defaults to `{}`.
Unknown non-`x-` params MUST be rejected. `x-*` extensions grant no authority.

| Param | Normative bounds |
|---|---|
| `server`, `tool` | Each 1–64 ASCII characters: first `[A-Za-z0-9]`, remainder `[A-Za-z0-9_-]`; no `__` anywhere; no normalization of identifiers. Together select `mcp__<server>__<tool>`. |
| `args` | JSON object; canonical compact, sorted-key JSON with `ensure_ascii=False` MUST be ≤2048 UTF-8 bytes. Across the complete tree: ≤32 object keys, depth ≤6 (root depth 0), ≤128 value/container nodes (root included). Keys MUST be strings. Only JSON null/string/bool/int/finite-float/array/object values. |
| Credential-key guard | At any nesting level, args keys matching `password`, `secret`, `token`, `authorization`, `api[_-]?key`, `cookie` or `credential` case-insensitively as substrings MUST be rejected. Authors MUST NOT put secrets in args, including under innocuous names; this guard does not inspect values for secrets. |
| `metrics` | Object with 1–6 entries. Names match `^[A-Za-z][A-Za-z0-9_]{0,39}$`. Values MUST be RFC 6901 JSON Pointer strings ≤512 characters: empty string selects root; otherwise `/`-prefixed, with only `~0` / `~1` escapes. Not JSONPath, fragments, expressions or array-count operators. |

The minimum `every` is 300 seconds; default `15m`. Below-minimum intervals MUST be
draft errors, not silently clamped. The first declared metric supplies the default
100-weight median-delta ring and baseline-fill capsule; lines default to `[]`,
icon to `source`. There is no inferred link or source-provided baseline.

**Consent and host policy.** MCP proposals/ticks MUST make zero pre-approval
connector calls (`pre_approval_sample=false`, `preview_calls=0`,
`preview_state=after_approval`). Shape validation is offline: an unavailable tool
may be drafted, but MUST NOT be polled without fresh host permission. The live
policy MUST confirm existence and explicit discovered `readOnlyHint=true` before
dispatch, and MUST refuse every declared server spend/cost policy. Missing or
ambiguous metadata MUST disable dispatch. The adapter prefers a future public
`ctx.tool_info`; its compatibility fallback and validator warnings are disclosed
in README. Definitions and their `x-*` claims MUST NOT supply permission.

Calls MUST use public `ctx.call_mcp(server, tool, arguments, timeout=8)` with
the exact approved server/tool and a deep copy of approved args. The operator MUST
separately grant the server in `plugins.entries.pulse-rings.mcp_allowlist`; pulse
approval MUST NOT grant that access. A pulse MAY be approved first, then wait in
`needs_mcp_grant` with no failure/backoff increments. Missing grants and host
PermissionError MUST return the exact key with sanitized local copy. The plugin
MUST NOT call set_config to write a grant. Connection/reconnect errors come from
the public host envelope, not a private connection-presence test. Polls enter a finite-turn
scope and suppress interactive OAuth: elicitation/sign-in requiring a person is
declined, never auto-approved. Missing safety context managers MUST disable the
source. Hermes's handler trust gate still applies; other plugins' `pre_tool_call`
hooks are not invoked by this native-handler path. Read-only annotations are claims, not
sandboxing. Server-initiated sampling is governed by Hermes's connector settings,
not disabled by this adapter.

**Budget and disclosure.** `budget.hosts=[]` means no **direct Pulsr** MCP
network transport, not local-only data or no downstream egress. One reservation
per dispatched call counts against the profile request ceiling, using pacing key
`mcp:<server>` (≥2 seconds). Exact recurring budget is `3600 / every_seconds`,
displayed rounded up; default is 4 req/h. No periodic or preview calls are added.
Hermes owns connector transport and sign-in/OAuth. Before approval and in Details,
renderers MUST disclose server/tool/args, a per-feed Hermes grant line,
live-policy read-only availability and
“via Hermes MCP connector (Hermes handles sign-in)”. Args disclosure is escaped,
sorted compact JSON (`ensure_ascii=True`), truncated after 512 characters with
`… [truncated; review full definition]`; the full approved definition remains the
authority. Runtime disclosure fields are specified in INTERFACE.md.

**Result and failure semantics.** Public call_mcp returns a dict envelope with
`ok` and `result`, optionally `structuredContent` and `truncated`. The adapter
MUST prefer `structuredContent` **when present**, including null/empty bodies;
otherwise `result` is decoded once if it is a JSON string. Pointers address that
body, **not** the outer envelope. Hermes flags results over ~64K characters
(documented ~64 KB); any truncated envelope MUST produce unknown metrics with
`MCP result truncated by Hermes; metrics unknown.`, never partial parsing or
binding. The secondary decoded-body limit is 256 KiB UTF-8, applied after Hermes
returns, not a transport memory cap. `ok` other than literal true, any outer/body
`error` key or `isError=true` is a sanitized SourceError (no server error text).
Malformed/oversize/nonfinite JSON also fails with sanitized local copy.
No MCP content-block unwrapping is inferred.
Array indices MUST be nonnegative decimal with no leading zero except `0`.
Missing/non-numeric/nonfinite selected metrics become `null` with reason
`MCP metric missing or not a finite number.`; booleans and numeric strings are
not numbers. Samples contain timestamp, selected metrics, empty baselines and
unknown reasons. Raw tool output, args and server error text MUST NOT be stored
in samples/source state/metadata/errors. Args are retained in definitions/drafts;
this is why authors MUST NOT embed secrets in them.

The caller waits at most eight seconds for a daemon worker; there are at most
four simultaneous MCP calls per process and one in flight per resolved plugin
root/server/tool. A timeout does not kill a host handler: it retains its slot
until return/process exit, but late results MUST NOT be persisted. Busy/in-flight
calls defer for 300 seconds without incrementing failures. Policy failure,
malformed results and foreign exceptions produce sanitized errors preserving the
last sample; no missing/error sample is replaced with zero. The adapter requests
900-second retry after timeout, 3600 seconds for error envelopes, otherwise the
standard 600 seconds. Engine retry delay is the maximum of that request and
`every_seconds × 2^min(previous_failures,5)`, capped at six hours. Local ceiling
and pacing deferrals MUST NOT increment failures. Cached status MUST NOT dispatch.

A connected MCP server and bound plugin context are required in the same Hermes
process that polls; otherwise the pulse reports unavailable. Nous-gateway hosted
connectors reached via `tool_search`/`tool_call` are outside this source kind.

## New posts

`source.kind: web.feed` (or `web.feed@1`) reads one public RSS 2.0, RSS 1.0, Atom or
JSON Feed document from the approved HTTPS `url`. It is an additive pulse/1 kind
with the same transport rules as `http_json`: the exact URL host is the only host,
one GET per poll, no redirects, no request headers or credentials, a 512 KiB body
cap, and `pre_approval_sample=False` (nothing is fetched before approval). The
minimum `every` is 15 minutes; default `30m`.

Metrics are fixed: `new_24h` and `new_7d` (entries dated within the window),
`hours_since_last` and `items` (entries in the document, at most 200 read). A feed
whose entries carry no dates reports `items` and leaves the others unknown; it is
never reported as zero. An entry dated in the future counts as published at the
poll time.

The feed is untrusted text. A document with a document type declaration is refused.
Titles are stored as plain single-line text of at most 140 characters, with markup,
control and direction characters removed; a link is kept only when it is a plain
`https` URL. The newest eight titles are kept in the feed's source state for the
pane. Samples and history hold numbers only. The agent-facing status carries counts
and times, never titles or links.

## Desktop notifications

`source.kind: desktop.notifications` (or `desktop.notifications@1`) counts local
desktop-app notifications on the polling host. It is an additive pulse/1 kind:
no network hosts, zero requests/hour, `pre_approval_sample=None` (local, never
previewed). The minimum `every` is 30 seconds; default `1m`.

| Param | Normative bounds |
|---|---|
| `apps` | Optional array of 1–8 curated aliases (`discord`, `teams`, `outlook`, `slack`, `whatsapp`, `telegram`, `signal`, `spotify`, `chrome`, `edge`, `claude`, `hermes`, `phone_discord`). Each alias maps in code to a fixed list of exact Windows AppUserModelIDs (`pulse_rings/desktop_apps.py`); definitions cannot extend it. |
| `app_ids` | Optional array of 1–8 exact Windows AUMIDs: 1–200 printable ASCII characters, first `[A-Za-z0-9{]`, no trailing space. Matched case-insensitively and exactly; no wildcards or prefixes. |
| `types` | `toast` and/or `badge`; default `[toast]`. Tiles are excluded. |

At least one of `apps`/`app_ids` MUST be present; together at most 8 entries;
duplicates (case-insensitive) are errors. Validation is offline: an unregistered
app is a valid draft that reports unknown at runtime.

Metrics are summed over the selected apps that are registered and enabled:

- `waiting`: notifications of the selected types still in Windows' notification
  store (not expired). Measured 0 is real 0.
- `new_1h`, `new_24h`: arrivals observed by this feed in the window. An arrival
  is a new notification id seen between polls, or an advance of the app's
  `LastNotificationAddedTime` without a new row (apps such as Discord remove their
  own toasts once read). Several arrivals that appear and clear within one poll
  count once, so these are lower bounds. They MUST be `null` until the feed has
  observed continuously for the whole window; a gap longer than
  `max(3 × every, 300s)` or a backwards clock restarts observation.
- `minutes_since_last`: minutes since the newest arrival known for the selected
  apps; `null` if none is known.

**Privacy and reads.** This kind reads outside the plugin's own data and MUST be
disclosed as such (catalog rule 13). Adapters MUST open the store read-only, MUST
select only handler/notification ids, types, arrival/expiry times and on/off
settings, and MUST NOT query, store or log payloads, tags, groups, notification
data, message text or senders. Samples hold numbers only; state holds numbers and
the definition's own app ids. Approval cards MUST show the exact target
`this PC · <apps…, app_ids…>` and that no network is used.

**Fail closed.** Unknown store versions or columns, implausible timestamps, a
missing store, notifications switched off globally or for every selected app,
unregistered apps and non-Windows hosts produce unknown metrics with a static
reason, never zero. A busy store is a local deferral, not a failure.

## Ring, capsule and lines

Weights `w` MUST sum to 100 (±0.01); each is 0–100. Score is
`round(sum(contribution), 1)`, clamped 0–100:

- **delta:** let `d = x − B`, and `D` be `abs(d)` (`both`), `max(d, 0)`
  (`up`), or `max(−d, 0)` (`down`). The contribution is
  `w × min(D / S, 1)`, where
  `S = (max(abs(B), floor) + max(−d, 0)) × sensitivity`.
  Built-in count metrics additionally use `S = max(S, 5)` so one-count noise
  cannot saturate the score. The extra decrease magnitude keeps a full drop
  to zero at at most half weight with default sensitivity; direction remains
  available in the unchanged numeric `value`, `baseline`, and signed `delta`.
  A built-in count with `B = 0` and nonzero `x` contributes zero with
  component `warming: true`, reason `No positive usual yet`, not unknown:
  its measured zero usual cannot support a proportional comparison. A ring
  whose available components are all warming also has `warming: true` (unknown
  siblings cannot turn missing comparison evidence into measured calm). The count floor
  also applies to explicit count names `count`, `errors`, `requests`, `calls`,
  `items`, and `players`; arbitrary fractional metrics retain their declared floor.
  `baseline` is `median` of prior samples, `oldest` prior sample, `source`, or a
  nonnegative fixed number. Prior observations are within `window` (default 24h).
  `floor=1`, `sensitivity=1.0` MUST be positive. `direction=both|up|down` (both)
  zeros movement in the opposite direction. GitHub search's `recent` and
  opted-in repository activity's `commits_week` have source-declared baselines.
  The separate search `baseline` metric is display-only.
- **level:** `w × min(x / full_at, 1)`; `full_at` MUST be positive.
- Unknown `x` or `B` contributes zero **with `unknown: true`**, never calm.
  A component is history-derived only when `type: delta` and baseline is
  `median` or `oldest`. Without a prior observation those components contribute
  zero and are unknown. Source/fixed-baseline deltas and measured level components
  score from the very first sample, except nonzero counts with a zero usual as
  described above. A ring with ALL components history-derived
  sets `warming=true` before a prior sample; all-component zero-usual warming
  also propagates to the ring. `ring.unknown=true` means every
  component is unknown: say **Not measured**, never measured calm.

A capsule requires `metric`, `label`, `fill`. `baseline` fill is
`min(100, 50 × x/B)%`: the 50% tick means usual, full means 2×. `{full_at: N}`
fill is `min(100, 100 × x/N)%`, with positive N; `none` has no fill. Zero/unknown
B cannot define a ratio: show **Learning baseline**, not infinity or invented calm.
Captions are automatic: **97% of usual**, **2.5× usual**, **Learning baseline**,
or **Not measured**. Unknown values replace the label with **<metric> unknown**;
measured zero MUST still say **0 …**. Only `{value} {delta} {ratio} {baseline}
{window}` are template placeholders; formatting belongs to the renderer, with
no expressions, format directives, attribute access or escaped-brace syntax.

Lines are `{metric, label, show: value|delta, hide_when_zero?: bool}`; defaults
are `value` and false. Alert is exactly one of `{ring_at_least: 0..100}` or
`{metric, above: number}` or `{metric, below: number}`. Optional
`notify=none|toast|os|pet` defaults to none; notifications MUST be throttled to
once/profile/pulse/30m on an alert rising edge. The changing measured value or
reason text MUST NOT create a new alert identity or rising edge. In this version `os` and `pet`
are rendered as an in-app toast, just like `toast`; there is no OS or pet API integration.

Upgrade note (one-time reset). Throttle state MUST be held per profile and pulse.
State written by earlier renderers was keyed by pulse and reason text with no
owning profile, and its last-reason pointer is cleared when an alert goes
inactive; it cannot be attributed to a profile, so a consumer MUST NOT adopt it
and MUST NOT delete, enumerate or extend it. A profile/pulse with no
profile-scoped state starts fresh on first observation. At most once per
profile and pulse after upgrade, the first notification (for an alert already
active at that first observation, or otherwise at its first rising edge) MAY
repeat an alert an earlier renderer announced and MAY fall within 30 minutes
of a pre-upgrade notification, because the earlier timestamp is not preserved.
Thereafter the rising-edge and 30-minute rules above apply without exception.

## Conformance

Consumers MUST enforce schema shape **and** these cross-field semantics, including
weight sums, metric references and source-baseline support. The schema's custom
`pulse-*` formats MUST be asserted (the Python `FORMAT_CHECKS` mapping supplies
reference checks); generic JSON Schema's default annotation-only mode is insufficient.
The offline validator returns `{path, message}` errors using JSON Pointer paths;
normalization expands presets/defaults without adding runtime state or authority.
See `INTERFACE.md` for the engine-facing dict and public function signatures.

## Admission and first-sample conformance

Approval MUST atomically refuse when the sum of active exact recurring budgets
plus the proposed budget exceeds the profile ceiling (300 req/h by default).
Twelve Discord pulses cost 120 req/h; 24 cost 240 req/h. The remaining room is
shown on approval cards. Displayed req/h is `ceil(req_per_hour)`; admission never
uses the rounded display values. Limits live in `pulse_rings/limits.py`.

- GitHub search first sample: `metrics.recent=125`, `baselines.recent=50` gives
  score 100, fill 100, caption **2.5× usual**, `warming=false`.
- Discord first sample without widget: online 100, members 1000 gives score 0;
  both history-derived deltas are unknown. A measured level still scores immediately.
- A ring of only history-derived deltas stays warming with score 0 on its first sample.

Status/draft fields and baseline encoding are frozen in INTERFACE.md.
