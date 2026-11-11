# Desktop contract — Pulsr 0.5.0-dev

The renderer imports only `@hermes/plugin-sdk` and `react`. Every route below is
passed to `ctx.rest` **relative to** `/api/plugins/pulse-rings`. No fetch, remote
image URL, private app store, or core markup selector is used by the plugin.
Preview-only fetches load local fixtures and previously recorded raster icons.

## Read model

`GET /status` → `{api_version: "0.5.0-dev", as_of: <Unix seconds>, pulses: [], drafts: []}`.
The same React Query key `['pulse-rings', profile, 'status']` is shared by the
pane, transcript cards, and cache-only status chip. The pane polls every 15s
(2.5s while a pending draft has preview_state=sampling),
only while `host.paneVisibility('pulse-rings:pane')` is true when supported.
A visible transcript draft card also polls; a chip alone never collects data.
`plugin.pulse-rings.draft.created`, `.draft.updated`, `.draft.decided`, and `.hermes.waiting`
invalidate the status query. Backend icons are never needed by the tools.

Each `pulses[]` item consumes the plan §3.12 fields:

- `id`, `title`, `kind`, `state` (`active`, `paused`, `warming`, `error`,
  `backoff`, `stale`, `unsupported_version`).
- `ring: {score, warming, components: [{metric, value, baseline, baseline_mode,
  observed_seconds, unknown, contribution}]}`. Scores/unknowns are **not
  recomputed** by the renderer. `baseline_mode` is `median`, `oldest`, `source`,
  or `fixed` (numeric mode also renders as fixed).
- `capsule: {label, fill: <0–100 or null>, caption}`. The engine expands
  templates and preserves units/unknown labels. The renderer clamps only
  drawing geometry. It never turns a null metric into zero.
- `lines`: rendered text strings; `{label: string}` is also accepted for an
  already-expanded line. No HTML, Markdown, or expressions are evaluated.
- `icon_url`: optional immutable relative `/icons/{guild_id}-{hash}` route loaded through SDK REST and cached per hash/profile. Status does not inline icon bytes.
- `icon_data`: null or a raster `data:image/(png|webp|jpeg);base64,...` URL.
  Anything else gets a local glyph/initials fallback without a request.
- `last_ok_ts`, `next_due`, `backoff_until`: Unix seconds or null; `error`:
  human-readable string or null. A `backoff` row reads `Rate limited · retry in
  <duration>` and still offers Pause; only the manual `paused` state is called
  paused (it offers Resume).
- `alert: {active, reason, notify}`, `history: [{ts, value}]` (up to 48),
  `budget: {hosts: string[], req_per_hour: number}`.

**Optional enrichment, not present in the minimal §3.12 shape:** `every` (the
normalized interval string) and `link` (HTTPS destination, opened only through
`ctx.os.openExternal`). Without these the cadence is called source-scheduled
and Open is omitted. Observed sample counts use the returned history length,
explicitly called "recorded samples", **not** an invented total baseline count.
A source baseline is called source-declared; the UI does not invent its day
window. Draft definitions can supply the exact `baseline_days`.

## Attention strip and lens

Every row and rings-only circle carries `data-attention`: `alert` (an active
alert), `problem` (`error`, `unsupported_version` or `needs_mcp_grant`), `review`
(a draft awaiting approval), `notice` (a notifications pulse with something
waiting; see Notification mode) or `none`. Automatic retries (`backoff`), `stale`
caches and manual pauses are `none`: they resolve without the owner. A stale or
paused notifications pulse is `none` too: its count is old.

When at least one item is not `none`, a strip above the list counts them in plain
words (`1 alert · 2 problems · 3 with notifications · 1 to review`). It is a toggle button: pressed, the
pane hides `none` rows, quiet groups and the arrangement toolbar, and reads
`Showing N of M`. The lens is view state only. It is CSS-driven, never reorders or
writes the saved arrangement, makes no request, is not persisted, and releases
itself when nothing needs the owner. The strip is absent in the rings-only rail
and while the status query is failing.

Below a 240px pane the row title takes the whole line (the `Change N/100` text is
hidden; the ring, tooltip and accessible name still carry it), and a capsule
shows its measured value whole, dropping the comparison when both do not fit.

A measured summary (`213 PRs · ↑ 3.7× usual`) that wraps starts its second line
flush, without the separator. The footer never ends in an ellipsis: below a 370px
pane it drops ` · pulse/1 · v…`, and below a 310px pane it also uses a short form
(`While open · 0 tokens · ≈N req/h`, or `Background · …`). The full sentence,
protocol and version stay in its tooltip.

## Trend and voice (legacy rows)

When a row carries `trend`, Details draws today's line over yesterday's (dashed,
muted) on one real time scale ending at the last measurement, with `24h ago /
12h ago / now` under it, a legend when yesterday exists, and `Low … at … / Peak …
at …`. The headline is the comparison with the same time yesterday: `+3% vs this
time yesterday (13,477)`, `About the same as this time yesterday`, a signed
difference when yesterday was zero, or `No sample from this time yesterday yet`.
More than two hours without a point breaks the line; nothing is interpolated.
The chart's accessible name carries the same facts. Without `trend` (older
backend, fewer than two points) the First/Latest sparkline is used as before.

When a Discord row carries `voice`, its `voice_channels` line reads `7 in voice ·
2 channels`, `At least 12 in voice · 3 channels` when the public member list is
full, `No one in voice right now`, `Voice not public for this server`, or `Voice
not checked yet`. Without it the stored line label is shown unchanged.

## Notification mode

A row whose main feed is `desktop.notifications` and which carries `inbox` is
drawn as an inbox instead of a generic metric. `inbox` is counts and times only
(plus `items` when message preview was approved; see below):
`waiting` (null = not measured, with `reason`), `last_ts`, `hour` and `day`
(null until that window was watched in full), `seen` and `since` (arrivals
counted since watching began, at most a day back), `complete`, `marks` (24
hourly counts ending at `ts`) and `ts`.

- Collapsed: `2 waiting · latest 3h 6m ago` or `Nothing waiting · last 1d 3h
  ago` (`Not measured` when the store cannot be read), a count pill on the
  title line while something is waiting (`99+` above 99), and no `Change
  N/100` text or score arc around the icon (an active alert fills the ring in
  the warning colour). Names and tooltips say `2 waiting in Windows`.
- Expanded: one card. Headline (`2 waiting in Windows`), `Last notification 3h
  6m ago · 10:53 PM` (weekday added after 20 hours), a 24-slot strip of
  arrivals per hour over `24h ago / 12h ago / now`, and `4 in the last 24 hours
  · none in the last hour`. A day watched only in part shades the unwatched
  span and reads `3 since watching began at 9:12 AM`; it never claims a day
  count. An empty watched day keeps the axis without the chart's height.
- A pulse without its own display shows the card in place of the trend, lines
  and usual-sentence. A pulse with display blocks keeps every block, under the
  card.
- While `waiting` is above zero the row is `data-attention="notice"` and counts
  in the attention strip; in the rings-only rail it shows the dot.

Without `inbox` (older backend, never sampled, draft preview) the row renders
exactly as before. Display only: scores, alerts and stored definitions are
unchanged, and no request is added.

### Open the app

A notifications row may also carry `open_app: {name}` (for example
`{name: "Discord"}`). The backend sends it only on Windows, only when the
adapter reads the real notification store, and only for a pulse whose
notifications feed watches exactly one launchable curated alias (no `app_ids`)
whose AUMID the store has reported on this PC. It is a display name, never a
target.

- Clicking the row (or Enter on it) sends `POST /pulses/{id}/open-app` with
  body `{confirm: true}` and nothing else. The row is not a disclosure button:
  no `aria-expanded`; its name ends `; opens Discord` and its title is `Open
  Discord`. The row is `data-opens="true"`.
- Details move to a small `▸`/`▾` button at the right of the row
  (`.pr-details-toggle`, named `<title> details`, with `aria-expanded` and
  `aria-controls`). It never covers the title, count pill or inbox line.
- A refusal shows one warning, `Could not open Discord. <reason>`, and the next
  click tries again. A second open of the same app within two seconds is
  dropped by the backend.
- In the rings-only rail there is no details button; the ring opens the app and
  the tooltip adds `Click to open Discord`.

The backend takes no app from the request (an extra field is a 422), resolves
the AUMID from the code-owned table and hands Windows
`shell:AppsFolder\<AUMID>`. Without `open_app` (older backend, other platform,
several apps, `app_ids`, an app never seen here) the row behaves exactly as
above.

### Message preview (opt-in)

A pulse approved with `preview: true` on its main notifications feed may also
carry `inbox.items`: up to 5 of `{from, text, ts}`, newest first. `from` is the
toast's first text line (often the sender; null when the toast had one line),
`text` the next, each plain text of at most 120 characters; `ts` is the arrival
time or null. `items` is `[]` while nothing is waiting or the store cannot be
read. Its `notifications` disclosure then carries `preview: true`.

- Collapsed: under the inbox line, one item at a time (`Ada: See you at four? ·
  1/3`), the next every 4 seconds. Hovering or focusing the row holds it; with
  reduced motion it stays on the newest. It is one line, cut with an ellipsis,
  `aria-live="off"`, and never part of the row's accessible name. Not drawn in
  the rings-only rail.
- Expanded: the card lists every item (`Ada: See you at four? · 1m ago`) under
  its headline, as a list named `Waiting notifications`.
- The row disclosure reads `… Never saved · No network.` instead of `Counts and
  times only, never message text`.
- Approval: the feed's target is `this PC · <apps> · message previews`, so a
  renderer that does not recompute that suffix cannot approve it. The card says
  what is read and that it is never sent to Hermes.

Text is drawn as text only and re-bounded by the renderer. The backend sends
`items` only in the pane's own status: never in the compact status the agent
reads, a draft preview, or the `/rings` command. Without `items` (preview off,
older backend) everything above is unchanged.

## New posts

A row whose main feed is `web.feed` and which carries `posts` shows what was
published. `posts` is `new` and `week` (entries dated in the last 24 hours and 7
days; null when the feed carries no dates), `total`, `last_ts`, `ts`, the feed's own
`title`, and `posts`: up to eight of `{title, ts, link, new}`, newest first. Titles
are untrusted text and are drawn as text only. `link` is offered by the backend
only for plain `https` URLs, and the renderer checks the scheme again before it
makes a post clickable.

- Collapsed: `2 new · <latest headline>` with a count pill on the title line, or
  `3d 2h ago · <latest headline>` when nothing is new, `2 posts · <headline>` for a
  feed without dates and `No posts yet` for an empty one. The headline stays on one
  line and is cut with an ellipsis; its tooltip has the full title. No `Change
  N/100` text. Names and tooltips say `2 new posts; latest 2h 10m ago`.
- Expanded: a headline (`2 new in the last 24 hours`, or `No new posts · last 3d 2h
  ago`), then up to six posts across the width of the cell: a dot for posts from the
  last 24 hours, the title on at most two lines, and a short age (`2h`, `3d`, `2w`)
  in a right-hand column. A post with a link is a button that opens it in the
  browser. A foot line gives `4 this week · 12 in the feed · <feed title>`.
- A pulse without its own display shows the card in place of the trend, lines and
  usual-sentence. A pulse with display blocks keeps every block; the list follows
  them without the headline.
- A posts row never raises the attention strip by itself.
- `icon: source` resolves offline to a bundled logo: the site's own when the host is
  exactly `<site>.com` or a subdomain of it for a short fixed list (GitHub, GitLab,
  Reddit, YouTube and a few blog hosts), otherwise the feed mark.

Without `posts` (older backend, never sampled, draft preview) the row renders as a
plain metric. The agent-facing compact status drops `title` and `posts` and keeps
the counts and times.

## Server card

A `discord.invite` pulse without its own `display` gets `server` on its status row once it
has a sample. Display only: scores, alerts, stored samples and request budgets are unchanged.

Any `discord.invite` pulse without its own `display` (with or without `server`) shows no
`Change N/100` text and no score arc around its icon, in rows and collapsed-group circles:
the score is engine-internal and reads as noise next to people and members. An active alert
fills the ring in the warning colour. A pulse whose owner designed a score block keeps it.

Inside the card each figure is said once. When the Members tile shows the net change, the
Member growth heading is the label alone. When a voice chart follows the growth chart, the
`24h ago · 12h ago · now` axis is drawn only under the voice chart.

```json
"server": {
  "members": {"value": 48210, "delta": 164, "span_seconds": 86400, "points": [{"ts": 0, "value": 0}]},
  "voice": {"state": "available", "users": 11, "channels": 3, "capped": false, "floor": false,
            "points": [{"ts": 0, "value": 9}], "peak": {"ts": 0, "value": 14}}
}
```

- `members.points` is the net change in the member count since the first reading of the
  last 24 hours (15 minute buckets, ending on the exact latest reading). It is joins minus
  leaves: Discord's public invite gives a total, not who joined. `delta` is null and
  `points` empty until there are two readings.
- `voice` is null when the pulse does not watch voice. `points` is one entry per public-widget
  check of the last 24 hours, from a counts-only log in the source state (at most 120
  entries of time, people in voice, active channels, members listed; never names or channel
  names). `floor` is true when any of those checks hit the widget's 100-member list limit,
  so the line is a minimum. `state` is `unavailable` when the server's widget is off.

The row reads `3,369 online · 11 in voice · +164 in 24h`. Expanded, three figures span the
cell (Online with its share of members, In voice with active channels, Members with the
day's net change), above three day charts with one heading style: online today against
yesterday, member growth from zero, and a stepped line of people in voice with a ring on
its peak. Below 250px Online leads on its own line. The card replaces the two text lines
and the usual-range sentence it restates.

What it never claims: a widget that is off shows a dash and `Not public`; a full public
list shows `≥` and says why; a full list with nobody in voice shows a dash and `None
seen`, draws no flat zero line and makes no voice claim on the row. A pulse with one
reading shows figures and no invented chart. Wrong types from a backend render as not
measured. Without `server` (older backend, designed pulse, never sampled) the row renders
exactly as before. The agent-facing compact status drops `server` and keeps `voice`.

## Dense details

Display blocks use the width of the cell. This is layout only: no block, value or
request changes, and builder previews, approval cards and legacy rows are unchanged.

- Expanded, two `stat` blocks in a row sit side by side as two tiles when the pane is
  at least 280px wide; narrower, they stack. An unpaired stat keeps the full width.
- A stat's change and caption sit beside its value and wrap under it only when they do
  not fit. A bar's range and caption share one line under the track.
- A `spark` whose values move names its low and high under the line (`Low 260,000` at
  the left, `High 261,781` at the right); a flat one shows no scale.
- Collapsed, a row whose first block is a measured `stat` adds up to three facts from
  the pulse's other blocks after the number (`48 °F · Wind 5.7 mph · Rain 0 in`). A
  fact that does not fit is hidden whole; unknown values are left out.

## Background collection and settings (WP10)

Top-level `collection` is always present, including compact cached status:
`{mode: "viewed" | "background", lease_holder_alive: boolean, last_tick_ts: number | null}`.
Mode reflects the saved opt-in, not an uptime promise; liveness means an unexpired
30-second SQLite lease, and last_tick_ts is the last admitted scheduler tick
(including empty ticks), not a source-success timestamp. Continue to use each
feed's last_ok_ts/error for actual freshness.

The header beacon follows that split. It is labelled `Live` in viewed mode, and
in background mode only while `lease_holder_alive` is true. Background mode
without a live lease shows a hollow beacon labelled `Background collection not
confirmed`. The beacon never speaks for source freshness, and the footer keeps
reporting the saved mode.

Default OFF preserves viewed single-operation polling. ON runs at most one
approved due feed per five-second tick through `poll_one_due(previews=False)`;
SQLite ownership/minimum tick gap plus process/OS locks prevent double scheduling
and fence in-flight polls beyond lease expiry. A viewed GET while the lease is
alive reads approved feeds from cache; it may still advance one eligible draft
preview. With a stale lease, it may claim one ordinary due poll. Drafts never run
in the background collector; tools and `poll=0` reads do not poll.

`GET /settings` returns `{background_collection: boolean, writable: boolean}`.
Human-only `PUT /settings` accepts exactly
`{background_collection: <StrictBool>, confirm: true}`. Missing/string/numeric
booleans and extra keys are rejected; literal false confirmation returns 400.
Writes use captured profile-scoped `ctx.set_config` and immediately read back
`ctx.get_config`. A missing process-local context returns 503 with Plugins
settings instructions, never a private writer. All inherit host authentication,
enablement and origin protection; there is no agent mutation tool.

The pane's options switch reads collection mode, writes only on a human click,
then GETs settings before refreshing status. Late profile-switch responses cannot
start another mutation/read on the new profile. Footer text is **Collecting in
background** or **Collecting while open**. No automatic opt-in occurs on mount,
refresh, draft approval or import. Schema setting defaults OFF in Plugins settings.
Toast delivery still requires a visible view; background samples update baseline
and alert calculations on cached status reads. Shutdown/unload signals stop and
joins for at most 1.5s; an in-flight call can drain without another gated request
or late sample persistence. See README and submission/BACKGROUND-SURFACE.md.

## Draft shape / plan ambiguity resolved

The original plan specifies `drafts[]` but does not spell out its member shape or
GET by-id. Transcript directives deliberately do not depend on `GET /drafts/{id}`.
A directive validates `^pd_[a-f0-9]{10}$`, then looks up that exact id
in `GET /status`'s `drafts[]`.

```json
{
  "id": "pd_0123456789",
  "status": "pending",
  "definition": {"pulse": 1, "id": "catalog-prs", "title": "Catalog PRs", "source": {"kind": "github.search", "params": {"repo": "NousResearch/hermes-agent", "type": "pr", "baseline_days": 14}}, "every": "15m"},
  "preview": null,
  "budget": {"hosts": ["api.github.com"], "req_per_hour": 5},
  "created_ts": 1794099600,
  "expires_ts": 1794704400,
  "origin": {"kind": "session", "name": "Hermes"},
  "replaces": null,
  "diff": null,
  "auth": "no sign-in",
  "yaml": "pulse: 1\n..."
}
```

`definition`, `id`, `expires_ts`, `budget` and parsed object `origin` are the
frozen draft contract. Status is pending|approved|rejected|expired. Only pending
is actionable (pending_approval is accepted temporarily as a legacy UI alias).
Missing budget MUST say **Network: unknown — cannot approve**, with Approve disabled.
The server persists exact recurring req_per_hour plus integer req_per_hour_display;
remaining_req_per_hour is computed from active allocations. Display rounds up.
Preview is null or a full status-row shape produced by the engine, including a
one-sample ring/capsule. Source baselines and measured levels score immediately.
`ring.unknown` means all components unknown; never present measured calm.
Optional yaml/auth/diff enrich display but cannot replace budget disclosure.
Unknown auth must never imply a credential was used. Full http_json URL is shown.
Status `features` explicitly gates import_discord, share_yaml, import_yaml; absent
or false flags hide their optional controls. Import YAML is implemented; the
Discord importer and Share YAML are implemented and advertised by their feature flags.
Drafts also expose preview_calls (0–2), preview_state (sampling|ready|after_approval)
and an optional sanitized preview_error. Cold previews are null; Sampling… is
a placeholder, not a fabricated status row. The card displays the call count.
One propose call cannot sleep or dispatch more than one request.

## Mutations / exact payloads

| User action | REST request | Confirmation |
|---|---|---|
| Approve | `POST /drafts/{pd_id}/approve`, body `{confirm: true}` | GET `/status?poll=0`; pulse with `preview.id` (or `definition.id`) must be present, and draft absent or `approved` |
| Reject | `POST /drafts/{pd_id}/reject`, body `{confirm: true}` | GET `/status?poll=0`; draft absent or `rejected` |
| Pause / resume | `PATCH /pulses/{id}`, body `{paused: true}` / `{paused: false}` | Refetch `/status`, render returned state |
| Remove | `DELETE /pulses/{id}`, no body, after an inline confirm | Refetch `/status`; backend keeps history and notes |
| Open the app (notifications row with `open_app`) | `POST /pulses/{id}/open-app`, body `{confirm: true}` | `{opened: name}`; nothing to read back, a failure shows one warning |
| Share YAML | `GET /pulses/{id}/definition` | Accept a YAML string, `{yaml: string}`, or `{definition: object}` (JSON fallback) |
| Import YAML / JSON | `POST /drafts`, body `{definition: "<pasted YAML or JSON>"}` | Refetch `/status`; never activate |
| Import Discord Pulse | `GET /migrate/discord-pulse` plan, then human `POST` with `{consent: true, token: "<64 hex>"}` | GET `/status?poll=0`; marker completed and every planned ID present; source remains read-only |

Mutation errors stay visible and controls recover. A per-draft cross-component
lock prevents simultaneous approve/reject. Decisions do not claim success from
POST alone: they read status back before changing the transcript to Live or
Rejected. No activation request runs on mount, event, import, or timer.

The header **New pulse** opens the in-pane builder (WP9); Edit and pending
Open in builder load data only. Fix and Keep notes **only insert unsent composer
text**. They never submit a message or create a scheduled job. Copy YAML uses
`ctx.os.writeClipboard`. Compact row clicks use `host.openWorkspace` when
available, or ask the user to widen the pane. All decisions remain human clicks.

## Pulse Builder (WP9)

All routes are relative SDK REST. Sample/validation requests never poll sources.

| Route | Input / result |
|---|---|
| `POST /layout-check` | `{definition: object or YAML/JSON string}` → `{ok,errors:[{path,message}],normalized,budget,yaml}` |
| `POST /builder/preview` | `{definition,mode:"sample",state,seed}` → `{ok,sample:true,display:[real engine rows],synthetic_feeds,definition,theme,icon_resolved,budget,...}` |
| `GET /brands?q=` | ≤20 offline `{slug,title,hex,path}` records in `brands` |
| `GET /builder/mcp-tools` | Profile-connected `{tools:[{server,tool,read_only,reason}],reason}`; metadata only |
| `POST /builder/mcp-test-call` | `{server,tool,args,confirm:true}` → `{body,text,truncated,numeric:[{pointer,value}],calls:1,persisted:false}` |

Preview state is measured|learning|unknown|over|under|stale|degraded. Seed is a
strict nonnegative 31-bit integer. Unsupported modes/extra keys are rejected.
Validation, preview and MCP inspection use `Cache-Control:no-store`.
MCP tests require StrictBool confirmation, source-schema parameters and the same
read-only policy/refusal scope/dispatch/decoder as the approved source; no retries,
no durable results. Rate limit: one call per ten seconds per profile/server/tool.
A late/timed-out result cannot bind or persist. At 64KiB truncation, the body is
null and numeric binding is disabled. JSON pointers escape `~`/`/` per RFC6901.
No preapproval HTTP test route is provided; its existing networking path depends
on approved exact destinations (see DISPLAY.md WP9-builder notes).

New pulse opens in the Pulses pane. Edit reads `/pulses/{id}/definition`; pending
cards load their proposed definition. Compose edits and Definition apply use the
same backend validation. Preview reuses Block, always watermarks Sample, and uses
the original cached/approved row for Cached/Measured instead of guessing metrics.
Widths ≤640px use Compose/Preview/Definition tabs. Creating a draft reads the exact
`GET /drafts/{id}` back before showing ApprovalCard; this additive by-id route is
only used for the creation receipt, not to change transcript lookup semantics.
Edits retain id and post `replaces`; the running pulse is untouched until approval.
Ask Hermes inserts an unsent SDK composer draft, falling back to SDK clipboard.
No test/validation/edit action approves or dispatches on mount or a timer.

WP10 retains the narrow tabs and uses a balanced two-column desktop workspace:
Compose scrolls independently, Preview remains visible, and Definition is a closed
native disclosure beneath it. Data (selected block) starts open; Range/Zones/Style,
About this preview and Review draft start closed. Body text is 13px, secondary copy
≥11.5px, including readable disabled states. Data source is a labelled Sample/Cached/Measured
segmented control. Sample mode keeps its persistent **Sample values** watermark
and a separate **Show state** selector, with **Simulate: normal** selected by default
(engine state `measured`); every option is explicitly simulated. Cached/Measured hide
this selector and explain that state comes from the approved pulse. Synthetic
stale/degraded labels never claim cached or measured data.
Number tweening uses only a decorative copy of exact engine strings; accessible
names and settled values stay exact. Tabular slots reserve digit width. Both reduced
motion and theme.motion:none skip count-up/beat. BrandGlyph is shared with the
picker and switches paths below 3:1 contrast to adaptive ink while retaining the
brand accent (ICONS-CONTRACT.md).

Run scripts/test-polish.mjs alongside widget/blocks/builder for contrast,
keyboard disclosures, three live ticks/digit boundaries without layout shifts,
integer count samples and motion preferences at 900/1280/248px.

Run `scripts/test-builder.mjs` against the local preview server, in addition to
widget/blocks suites. The preview server's Python bridge imports the real pure
builder; MCP calls and postapproval rows are explicit lab fixtures, not live data.

## Harness

```
node scripts/preview-server.mjs $HERMES_SOURCE 5198
node scripts/test-widget.mjs $HERMES_SOURCE $ARTIFACTS/pulse-rings/wp4
```

Use an absolute path to `node` if Node is not on PATH. The harness borrows the host's
existing React, React Query, Radix Tooltip, Vite, and Playwright; no installation
or running-Desktop modifications are involved. `tests/fixtures/ui/*.json` are
**engine-generated**, API `0.5.0-dev` fixtures (Discord recorded; other scenarios synthetic), except the intentional old-backend fixture.
`?mode=hero|states|pending|approval|arbitrary-host|twelve|empty|old-backend|offline`
and `&width=56|160|200|248|320` select scenarios. `&theme=light` selects light.
Screenshots retain the synthetic-fixture label and are not live integration
proof. The UI still needs the parent's live create→approve integration check.

Run `scripts/test-ui-nits.mjs` for approval rate formatting and the builder/card
248/320/900/1280px light/dark sweep. `PULSE_NITS_SECTION=matrix` or `edges` splits
screenshots/layout from malformed-rate and exact-sum cases; omit it to run both.
Its fixtures are synthetic and exact raw data in definitions/JSON stays untouched.

Generate every fixture with `scripts/generate-ui-fixtures.py`; never edit measured values by hand. See spec/INTERFACE.md for the complete frozen read model.

## Display blocks and local CSS (WP8)

`display:null` (or absent) preserves the legacy layout. Otherwise `display` is
an ordered array of DISPLAY.md §4.3 rows; `theme` is §3 theme or null, and `feeds`
contains §5 status metadata. Expanded details render all blocks; the first block
is the collapsed-row hero. `score` reuses Ring, `rings` uses concentric arcs,
`bar`/`bars` share one renderer, `stat` uses supplied value/delta strings, and
`spark` draws supplied points with null-delimited gaps. No range/fill/tone/unknown
or measurement captions are recomputed. Resolved numeric bounds are shown
literally when `show_range !== false`. See the WP8-render notes in DISPLAY.md
for fields deliberately absent from the row contract (notably stat `show`).

Stable new-display hooks (legacy DOM intentionally stays unchanged):

- `.pr-pulse[data-id]` identifies an active display pulse.
- `.pr-block[data-type][data-index]`, with `data-mini=true|false`.
- `.pr-item[data-tone][data-state]`; states measured|learning|unknown|unavailable.
- `.pr-bar__track`, `.pr-bar__fill`, `.pr-bar__tick`.
- `.pr-ring__track`, `.pr-ring__arc` (score and rings).
- `.pr-stat__value`, `.pr-stat__delta`, `.pr-spark__line`, `.pr-spark__dot`,
  `.pr-spark__area`, `.pr-caption`.

Style values are revalidated into `--pr-b-<key>` variables on each block;
underscores become hyphens (`show_range` → `--pr-b-show-range`). Integer lengths
are clamped then use px. Enum/boolean variables retain their validated literal
values. Theme variables `--pr-t-<key>` stay on that pulse's trigger/display
wrapper only. `theme.motion:none` and reduced-motion disable transitions;
otherwise geometry transitions take 700ms, including coordinate interpolation
for SVG polyline points. `.pr-beat[data-beat=true]` signals advancing feed time.

`GET /custom.css` is optional, SDK REST only, returning UTF-8 `text/css` from the
plugin-data root's regular non-symlink `custom.css`, at most 65,536 bytes. Missing,
invalid UTF-8, oversized and nonregular files return 404. Desktop's REST bridge
JSON-decodes all successful bodies, so the renderer requests the additive
`GET /custom.css?format=json` representation: the same CSS text as a JSON string.
Canonical `GET /custom.css` remains text/css. The renderer tolerates
absence silently, owns one reference-counted style node per context, ignores late
responses from disposed/profile-switched views, and removes it on final unmount.

User CSS is a conservative subset: simple stable hook class/data selectors,
descendant/child combinators, and safe visual declarations. Rules are scoped to
`.pr-shell .pr-pulse:not(.pr-pending)` and explicitly exclude approval descendants.
Outside/unknown selectors, escapes, all at-rules (including @font-face), URL,
expression, behavior and binding declarations, variables/functions with external
inheritance, and layout/overlay properties are dropped. Color/background-color,
border colors/radii, font-weight/style, text-decoration, stroke/fill and bounded
`--pr-b-color|color2|track|thickness|radius|glow|gap` are supported. WP9 additionally
allows bounded font-size/family, letter-spacing/line-height/text-transform,
opacity, padding/margin/gap, border width/style, shadows, gradient-only
backgrounds, and drop-shadow/brightness/saturate filters (see DISPLAY.md §6).
Shorthand-expanded longhands are checked, not blindly accepted. No generic
`.pr-shell`, host, budget, approve/reject, or `.pr-approval` rule is accepted.
Approval cards deliberately retain fixed styling and never inherit a pulse's
theme. Every `.pr-pulse` card and `.pr-block` has `contain:paint` and
`isolation:isolate`. Active cards are local z-index 0; pending cards and approval
regions are positioned local z-index 1 with solid theme surfaces. `.pr-shell`
isolates this stacking order from the host. No core app markup is touched.

Length-bearing CSS values use one exhaustive finite decimal grammar: bounded px
or unitless zero only, never exponent notation, Q/relative/viewport/physical/%
length units, math/variable functions, escapes, or comments (comments are refused
before CSSOM token normalization). Font sizes are 8–48px; letter spacing −2–8px;
margin −8–32px; padding/gap/border widths/radii 0–32px. Shadows have 2–4 lengths
(box) or 2–3 (text/drop), each −64–64px, with nonnegative blur; at most four
shadows or three filters. Filters only allow bounded drop-shadow and unitless
brightness/saturate 0–3. Outline/outline-offset remain forbidden. Parser limits
are not the paint boundary: containment and consent stacking are independent
defences, also tested with unsanitized review payloads injected by the lab only.
This is not a general-purpose CSS sandbox or a host skin.

All actionable draft surfaces (collapsed pending row, expanded approval,
transcript directive, builder Review draft handoff) render the same server-derived
`disclosure` feed list from INTERFACE.md, without HTML. Every feed's name, kind,
full target/params, cadence, estimated req/h and direct hosts are visible, followed by
icon hosts and estimated total allocation. Every rate display uses `≈` plus the
locale-formatted ceiling integer (e.g. `4.166666666666667` → `≈5 req/h`), including
zero and integer allocations. Missing/nonfinite/negative rates display `unknown
req/h`, never JS sentinels. The exact server allocations still govern disclosure
validation and admission; remaining capacity is conservatively floored, not rounded
up. Each MCP row has its own live policy badge.
Args over 512 characters show an explicit truncation marker and keyboard-operable
`Show full args` disclosure containing all escaped JSON as text. Approve fails
closed on incomplete/unknown disclosure or non-read-only MCP policy, with an
explanation beside the controls. Pending summary rows no longer hide consent data.
Run `scripts/test-security-ui.mjs` in addition to every existing browser suite;
it compares decoded pixels of the actual pending card and both decision buttons
(with at most two intensity levels per channel for antialiasing) in
light/dark themes with active adversarially styled siblings, and checks hit targets.

Preview modes `blocks`, `block-states`, `styles`, `live-blocks` use separately
hand-authored synthetic rows, clearly labelled NOT ENGINE OUTPUT. Run:

```bash
node scripts/test-blocks.mjs $HERMES_SOURCE $ARTIFACTS/pulse-rings/wp8-render
```

`&baseline` mounts the frozen main renderer at commit `3b04572` via a local Vite
virtual module, for exact legacy DOM/pixel characterization only. No live profile,
plugin installation, network source, or host renderer is touched.

Alert delivery uses SDK toasts only: toast/pet/os modes notify on an active rising edge, throttled for 30 minutes per profile and pulse; changing the measured value or reason while the alert stays active does not create a new rising edge, and repeated cached status does not repeat a notification. Calm rings breathe subtly in light and dark themes unless reduced motion is requested. One recorded sample is explicitly an early trend, never a fabricated sparkline. Draft approval groups include the visible untrusted Open-link URL/host separately from polling destinations.

**Alert gate storage and upgrade note (one-time reset, Refs #70).** The gate is one record per profile and pulse, `alert-state:{profile}:{pulse_id}` = `{active, at}`; the reason text is display-only and never part of a key. Earlier builds kept profileless per-reason records (`alerted-reason:{pulse_id}`, `alerted:{pulse_id}:{reason}`). Those records name no owning profile, and their last-reason pointer is cleared whenever the alert goes inactive, so neither their `active` flag nor their timestamp can be attributed to a profile. The renderer therefore MUST NOT read, adopt, rewrite, enumerate or delete them, and MUST NOT create new keys of that form: there is no migration. A profile/pulse gate with no new-format record initializes fresh on its first visible observation. Consequence, accepted deliberately: after upgrading, the first notification per profile and pulse (for an alert already active at that first observation, or otherwise at its first rising edge) MAY arrive inside 30 minutes of a notification sent by the earlier build, and MAY repeat an alert the earlier build already announced; the earlier timestamp is not preserved. This happens at most once per profile and pulse. From the first observation on, the rule above applies unchanged (no repeat while continuously active, at most one notification per 30 minutes on a genuine rising edge). The old records stay in storage as inert orphans. `scripts/test-alert-upgrade.mjs` pins this policy against records produced by the frozen pre-change effect in `tests/fixtures/alert-effect-f876f09.txt`.

## Hermes MCP server grant (WP12)

Every MCP feed on the approval card and in the builder shows a separate
**Hermes grant** line from fresh backend `hermes_allowed`: **Allowed in Hermes
settings** / **Not yet allowed — add "<server>" to
plugins.entries.pulse-rings.mcp_allowlist**. A missing grant does not disable
Approve: explain that the pulse will wait. Never write grants through the UI.
Read-only policy and operator grants are independent. Status `needs_mcp_grant`
is a setup state, not a failed poll/backoff; builder Test call reports the exact
grant key on refusal. Backend grant/policy remains authoritative at invocation.
Call_mcp prefers present structuredContent to decoded result; truncated envelopes
provide no bindable numeric body, and polls record unknown metrics with a reason.

## Builder 2 API (WP13)

These four plain-def routes inherit the namespace's Hermes authentication,
enablement and origin guards. Successful responses have `Cache-Control: no-store`.
The three pure routes do not construct an Engine or start background collection.
Complete executed offline requests/responses for all four routes are in
[BUILDER-2-API-EXAMPLES.json](../submission/BUILDER-2-API-EXAMPLES.json), generated
by `scripts/builder-api-examples.py`; tests compare them to real FastAPI responses.
Only the explicit lookup route performs network I/O; template conversion and
layout generation never poll, create a draft, approve, or store source readings.

### `GET /builder/templates`

Returns an array of `{id,title,description,icon,kind,fields,lookup,test}`.
`icon` is the existing **resolved** brand (`kind,slug,hex,path`, plus title when
present) or emoji (`kind,text`) shape, not a remote image. Fields are
`{key,label,help,type,placeholder,required,options?}`; types are text/url/select/number
and options are `{value,label}`. `lookup` is null/city/steam; `test` is null/json/mcp.
The json test marker describes pointer inspection, **not** an arbitrary-host test
endpoint: none is added. Use previously inspected pointers or Ask Hermes.

Stable IDs and form values:

| ID | Values | Defaults / behavior |
|---|---|---|
| `discord` | `invite` | Original code or HTTPS discord.gg / discord.com/invite link, parsed offline |
| `github-repo` | `repo` | owner/name or HTTPS github.com/owner/name; no issue/PR/deeper URLs |
| `github-search` | `repo,type,title_contains?,label?,window?` | type `pr` (or `issue`); window `24h` (or `7d`), source baseline default 14 days |
| `weather` | `latitude,longitude,city?,units?` | imperial (or metric); coordinates rounded to 2dp; weather and air feeds |
| `steam` | `appid,name?` | Positive integer/decimal app ID or HTTPS store.steampowered.com/app/ID/...; offline |
| `json` | `url,metrics` | Public HTTPS and 1–6 named JSON Pointers from an inspected response |
| `mcp` | `server,tool,metrics,args?` | Exact registered names; args default `{}`; live grant/read-only policy still applies |
| `hermes` | `scope?` | `profile`; local counters only |
| `blank` | `url,metrics` | No preconfigured source; incomplete inputs return field errors until supplied |

`metrics` and MCP `args` accept JSON objects or their JSON text representations.
Extra form fields are errors. Selects with defaults use their first listed option.

### `POST /builder/from-template`

Body: `{template: <catalog id>, values: {...}}`. Returns
`{ok,errors:[{field,message}],feeds,metrics,suggested_title,suggested_icon}`.
Each feed is `{kind,params,every}`; each metric is
`{ref,label,unit,hint,default_selected}`. Hints are
count/percent/ratio/limit/temperature/money/duration/size/score/other.
`suggested_icon` is a **definition** icon (`{brand:slug}`, `{emoji:text}`, or
`"hermes"`), unlike the resolved catalog icon. Invalid forms return HTTP 200 with
`ok:false`, field errors, empty feeds and metrics; schema/body errors return 422.
At least one metric is preselected on valid conversion. No placeholder readings.

Example body: `{"template":"steam","values":{"appid":"730"}}`.
Example response:

```json
{"ok":true,"errors":[],"feeds":{"main":{"kind":"http_json","params":{"url":"https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=730","metrics":{"players":"/response/player_count"}},"every":"10m"}},"metrics":[{"ref":"main.players","label":"Playing right now","unit":"","hint":"count","default_selected":true}],"suggested_title":"Steam 730 · live players","suggested_icon":{"brand":"steam"}}
```

Weather conversion uses `api.open-meteo.com/v1/forecast` (temperature/wind/rain,
15m) and `air-quality-api.open-meteo.com/v1/air-quality` (US AQI/PM2.5, 30m).
Imperial units are °F/mph/in; metric units °C/km/h/mm. Those polling destinations
are reviewed on the ordinary draft card; city lookup does not approve them.

### `POST /builder/layouts`

Body: `{feeds,metrics:[refs],title?,icon?}`. Returns an ordered array of 3–6
`{id,title,description,why,definition}`. Each definition is complete and normalized
by spec.normalize and checked by layout_check; includes suggested title/icon.
Selection: 1–8 different declared refs (bare refs only for one feed). Invalid
source/ref/title/icon inputs return 400 `{detail:{errors:[{path,message}]}}`;
invalid body shape/extra keys return 422. No metric is silently dropped.

Preset IDs: `number-trend`, `gauge`, `comparison` (2+ numbers) or `bar-trend`
(single number), `change` (count/history semantics), `warnings` (recognized safety
metrics), and `dashboard` as a fourth option when needed. Titles/descriptions/why
are display text; use array order as rank, not alphabetical order.

Ranges prefer matching same-feed limit/total/capacity/quota siblings (including
used → limit and Discord online → members), then percent 0–100, ratio 0–1,
counts compared with usual, auto otherwise; temperature min is auto. At the
8-binding ceiling, a learned/natural scale replaces a denominator binding rather
than dropping a selected number; trend repetition is omitted for large selections.
Change rings use source baseline for GitHub search recent, median history for
other counts, never components across feeds. Warnings are suggestions, not alerts:
percent 80/95, US AQI 100/150, Open-Meteo heat 90/100°F or 32/38°C. Nothing else
receives invented danger thresholds; review all suggested levels for your use.

### `POST /builder/lookup`

Body: `{kind:"city"|"steam",q:<1–100 plain-text characters>,confirm:true}`.
Confirmation is StrictBool: false → 400; missing/string/numeric → 422. Returns
`{results:[...],calls:1,persisted:false}` (or calls:0 for an offline Steam app ID).
A 3-second per-profile/per-kind monotonic gate is held in memory only; 429 on
rapid clicks, 503 with a fixed sanitized message on source/timeout/redirect errors.
No retries. The q string is URL-encoded as data and can never choose a host.

- city: exactly `geocoding-api.open-meteo.com/v1/search?name=...&count=8&language=en&format=json`;
  results `{name,admin1,country,latitude,longitude}`, coordinates rounded to 2dp.
- steam: exactly `store.steampowered.com/api/storesearch/?term=...&cc=us&l=english`;
  response `items[].{id,name}` maps to `{appid,name}`. Valid app IDs/store links
  parse offline to `{name:"Steam app <id>",appid}`, with no call or rate-slot use.

At most eight projected results, no upstream images/extra properties. Uses the
existing public-DNS-vetted, numeric-IP-pinned HTTPS JSON transport with a 3-second
wall deadline and 256KiB response cap; no redirects/proxies/credentials/cookies.
Absent Hermes URL-safety APIs fail closed. No SQLite, drafts, samples, logs, or
files store queries/results; ephemeral gate keys contain profile/kind only.
Services still see the submitted query and caller IP. One explicit human Find
click authorizes one call, **not** recurring polling or pulse approval.

Example response to city `Louisville` (**fixture, not a live service reading**):

```json
{"results":[{"name":"Louisville","admin1":"Kentucky","country":"US","latitude":38.25,"longitude":-85.76}],"calls":1,"persisted":false}
```

The preview lab forwards the three pure routes to real Python modules. Its city
and Steam lookup results are explicitly sample-labelled local fixtures; they do
not dispatch network calls. MCP fixture policy and approval mocks stay separate.
