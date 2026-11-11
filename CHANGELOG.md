# Changelog

## 0.5.0-dev — Unreleased

### Added

- Message previews (opt-in): a notifications pulse approved with `preview: true`
  (a **Show message previews** checkbox in the builder) shows who each waiting
  notification is from and its text, one at a time under the inbox line, the
  next every 4 seconds, and lists them all in the expanded card. Hover or focus
  holds it, reduced motion keeps the newest. At most 5, each line cut to 120
  characters, plain text. Read from the Windows notification store only when the
  pane refreshes, kept in memory for 4 seconds, never saved, logged or sent to
  Hermes; the agent's status and `/rings` output never carry it. Off by default;
  the approval target gains `· message previews`, so turning it on is a new,
  disclosed approval. Pulses without it stay counts and times only.
- Open the app: on Windows, clicking a notifications pulse that watches one app
  opens that app (Discord, Teams, Outlook, WhatsApp, Telegram, Chrome, Edge,
  Claude or Hermes); details move to a small button at the right of the row, and
  in the rings-only rail the tooltip says the ring opens it. The target is the
  app's code-owned Windows identity, used only once the pulse has seen that app's
  notifications on this PC, launched through the same activation as the Start
  menu: no arguments, no network, nothing read back, and never from `app_ids`, the
  request or the agent. Pulses that watch several apps, other platforms and older
  backends keep the click-to-expand row. (#109)
- Discord server card: a server pulse now opens to three figures across the cell
  (online, people in voice, members) and three charts of the last day: online today
  against yesterday, net member growth, and people in voice with the day's peak
  marked. The row reads `3,369 online · 11 in voice · +164 in 24h`. Voice history
  comes from a counts-only log of the public-widget checks the pulse already makes,
  so it starts from the update and adds no requests. A server whose widget is off
  says `Not public`; one whose public list is full shows a minimum, or `None seen`
  rather than a zero. Member growth is the net change in the total, not a count of
  joins. Pulses with their own display blocks are unchanged.
- New posts: a `web.feed` kind reads an RSS, Atom or JSON feed you approve and the
  cell shows what was published. The row reads `2 new · <latest headline>` with a
  count pill; expanded, the newest six posts fill the width of the cell with a
  mark on new ones and their ages, and a post with an https link opens in the
  browser. The builder offers it as **New posts (RSS / Atom)** and, by repository
  name, as **GitHub releases**. A feed pulse without its own icon gets the bundled
  feed mark, or the site's bundled logo for a few well-known hosts. One request per
  check to the approved host, 15 minute minimum, nothing fetched before approval.
  Titles are plain bounded text shown in the pane only: samples hold numbers and
  the agent's status tool gets counts and times, never titles.
- Denser cells: expanded display blocks use the width of the pane. Two stats in a
  row become two tiles, a stat's change sits beside its value, a bar's range and
  caption share a line, and a moving trend names its low and high. A collapsed
  row with a stat hero adds up to three more facts after the number (`48 °F ·
  Wind 5.7 mph · Rain 0 in`). On the sample rows at 320px the weather blocks went
  from 456px to 345px tall and the repository blocks from 220px to 141px. Layout
  only.
- README gallery: six sample-data renders in `docs/screens/`, captioned as sample data.
- Notification mode: a `desktop.notifications` pulse now reads as an inbox. The
  row says `2 waiting · latest 3h ago` with a count pill, or `Nothing waiting ·
  last 1d 3h ago`, and counts in the attention strip while something is
  waiting. Expanded, one card gives the count, the time of the last
  notification and the last 24 hours hour by hour; a day watched only in part
  says since when instead of claiming a day count. Counts and times only, as
  before. Display only: scores, alerts and stored definitions are unchanged.
- Discord trend rethought: today's line over yesterday's on a real time axis, low
  and peak with their times, and a headline comparing now with the same time
  yesterday (`+2% vs this time yesterday`) instead of First/Latest, which mostly
  reported the time of day. Applies to any pulse without display blocks. Display
  only: scores, alerts and stored definitions are unchanged.
- People in voice: `7 in voice · 2 channels` where a server's public widget is on
  (`At least N` when the public member list is full), and `Voice not public for
  this server` where it is not. No new request and no member data stored: the
  count comes from the widget response already fetched.

- Attention strip and lens in the Pulses pane: a one-line count of what needs the
  owner (active alerts, sources that cannot recover alone, drafts to review) that
  toggles a view showing only those. View state only: no reordering, no writes,
  no requests. Alerting rows are tinted.
- Narrow panes (below 240px): row titles get the full line and a measured value
  is never cut short; the arrangement toolbar drops its scope note before it
  would wrap.

- `desktop.notifications` / `desktop.notifications@1` (Windows): count waiting and
  newly arrived notifications from chosen desktop apps (Discord, Teams, Outlook,
  WhatsApp, Chrome, … or an exact app ID), plus minutes since the last one. Local
  read-only access to the Windows notification store and per-app registry
  timestamps; counts and times only, never message text; no network, no previews.
  Builder template **Desktop notifications**; disclosure lines in README/PR body.

- Offline agent block/scale/style/icon/feed catalog (65,536-byte response cap),
  bounded brand slug/title search and pure `pulse_rings_layout_check` for all
  execution origins. Proposal summaries disclose every feed and total allocation,
  separately identifying one-off icon hosts; human-only approval is unchanged.
- Block-oriented authoring skill with checked multi-feed, GitHub comparison and
  percent/zone examples; source-limit-first scale selection and replacement drafts.

- `mcp.tool` / `mcp.tool@1`: select 1–6 finite numeric JSON Pointers from a
  configured, connected, explicitly read-only Hermes MCP tool. Bounded JSON args,
  15-minute default / five-minute minimum cadence and one counted call per poll.
- Human approval disclosure of exact server/tool/args, live read-only availability
  and Hermes-managed transport/sign-in. No Pulsr MCP preview before approval.
- Fail-closed policy checks for connection, annotations and all declared server
  spend policies; finite-turn/interactive-OAuth suppression declines prompts.
- Eight-second caller deadline, four concurrent call slots per process,
  profile/server/tool in-flight deduplication, sanitized errors and cached-value
  preservation. Late results never persist; stuck handlers retain their slots.
- Normative MCP source/read-model documentation, authoring guidance, submission
  disclosures and an unposted upstream issue draft requesting public tool policy
  and unattended invocation seams.

### Fixed

- Discord and notifications pulses no longer show `Change N/100` or the score arc
  around their icon. The score is an internal "how unusual is this" measure and
  read as noise next to people online and messages waiting; the icon now stands
  on its own. An active alert still fills the ring in the warning colour. Pulses
  with their own display blocks are unchanged. Scores and alerts themselves are
  unchanged.
- Discord server card says each figure once: the net member change sits on the
  Members tile only (the growth chart no longer repeats it), and the growth and
  voice charts share one `24h ago · 12h ago · now` axis under the last chart.
- Builder: nothing is folded away on start. **New pulse** lists all eleven sources
  at once (Desktop notifications, Any website JSON and MCP tool were under **More
  sources**), and the option sections (More source options, Customize pieces, All
  appearance controls, Ask Hermes for help, Draft a request in chat) start open.
  Each can still be folded. The raw **Edit YAML** editor and **About this preview**
  stay folded.
- Approval card: the `Parameters:` line breaks between parameters instead of
  inside them. A repository name or URL host is no longer split across lines
  (`NousResearch/her` / `mes-` / `agent`). The text itself is unchanged.
- Expanded rows no longer overflow a narrow pane: below 280px the action buttons
  use two columns and a long label wraps, instead of `Edit pulse` and `Remove`
  running past the edge (14px at 231px, 45px at 200px).
- `Usual (median) … · N samples` now reports the samples the median was computed
  from. It reported the number of chart points, which is capped at 48.
- The footer shortens instead of cutting off: below a 370px pane it drops the
  format and version, below 310px it says `While open · 0 tokens · ≈62 req/h`.
  A comparison that wraps (`144 commits` / `Learning baseline`)
  no longer starts its line with an orphaned `·`.
- A stat with nothing measured (`Not measured`, or the reason) is shown as quiet
  body text instead of at the 28px headline size of a real value.
- Averages and differences from averages no longer show noise decimals: the
  usual line reads `usual ≈56/24h` instead of `≈55.929`, and a count compared
  with its usual reads `+138` instead of `+138.071`. Below ten one decimal is
  kept (`+0.4`). Stored numbers, explicit `decimals` and fractional measurements
  are unchanged.
- A rate-limited pulse no longer reads `Paused · retry …`; its state line is
  `Rate limited · retry in …`, so an automatic retry delay is not mistaken for a
  manual pause.
- The header beacon no longer announces `Live` when background collection is on
  but no collector lease is alive; it shows a hollow beacon labelled `Background
  collection not confirmed` until a running collector is confirmed.

### Compatibility and disclosures

- Requires Hermes `>=0.22.7`; connector and plugin context must exist in the same
  process that polls. Hosted Nous-gateway `tool_search`/`tool_call` connectors are
  not supported. Pulsr delegates to public `PluginContext.call_mcp`;
  it has no direct MCP transport or connector credential storage.
- Hermes 0.22.7 lacks public annotation/connection-policy metadata. A read-only
  fail-closed shim prefers future `ctx.tool_info`, otherwise reads private host
  discovery metadata and enters two host safety scopes. Validator private-import
  warnings require review; no core tables/functions are patched or rebound.
- MCP handler trust policy remains, but other plugins' `pre_tool_call` hooks do
  not run on direct-dispatch polls. Read-only annotations are server claims, not
  a sandbox; server-initiated sampling remains a separate Hermes setting.
- Only numeric metrics persist in samples; raw output/server errors are discarded.
  Args persist in definitions/drafts, never samples/state/metadata/errors: no secrets.

No publication, catalog admission, live Desktop certification or new connector
integration is implied by this unreleased entry. Prior verification receipts in
README/submission remain explicitly historical where labelled FIX-1–FIX-8.

### WP12 MCP public invocation

Polling and human builder Test calls now use public ctx.call_mcp with an 8s timeout.
Operator mcp_allowlist grants are separate from pulse approval; missing grants wait
in needs_mcp_grant. Structured content is preferred; truncated envelopes never parse.
Private connection-presence checks removed (declared icon metadata unchanged).
