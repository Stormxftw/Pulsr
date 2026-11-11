# Pulse Builder 2 — UX + API contract (WP13)

Owner of this contract: parent. Helpers: WP13-builder-api (backend) and WP13-builder-ux (renderer).
Goal: make creating a new pulse obvious and premium for a first-time user, without losing any
existing power (multi-feed, all blocks, full style inspector, YAML) or any safety rule.

## Problems to fix (from a design review of the current builder)
- Opens as a raw property inspector ("Title/Icon/Feeds/Kind/Every/scope/Blocks/Binding/Inspector")
  with defaults that look ready to submit; no purpose, no steps, no destination.
- Jargon: feeds, kind, every, scope, blocks, bindings, hero, zones, score/stat/spark,
  "Definition · what gets approved", "1 / 3", "1 / 4 · 1 / 8 BINDINGS".
- Block buttons ("+ score", "+ bar", "+ bars") don't show what they look like or when to use them.
- Preview tools (Sample/Cached/Measured, Show state, Appearance, Compact row) are mixed up with
  saved settings; raw "168h"; duplicate labels; boxes inside boxes; small text; weak primary action;
  "Create draft" doesn't say how the pulse becomes live.

## New flow (one builder, two modes)
**Guided (default for New pulse)** — a 4-step flow with a progress header
`1 What to watch → 2 Pick a look → 3 Make it yours → 4 Review & add`, Back/Next, preview always visible.
**Editor (default for Edit / Open in builder)** — the same 4 sections as tabs, jumping straight to 3.
An "Advanced" toggle (persisted via ctx.storage) reveals the full current inspector and YAML.

### Step 1 — What do you want to keep an eye on?
- Large "Describe it" field + **Ask Hermes** (existing Ask Hermes path; never sends/approves itself).
- Template gallery (cards with official icon, title, one-line description), from `GET /builder/templates`:
  Discord server · GitHub repo · GitHub PRs/issues search · Weather & air · Game players (Steam) ·
  Any website JSON · MCP tool (connected servers) · Hermes activity · Start blank.
- Choosing a template shows a short plain-language form (e.g. "Paste a Discord invite link",
  "Repository (owner/name or URL)", "City", "Steam store link or game name", "URL").
  Lookups that need the network (city search, Steam game search, JSON test fetch, MCP test call)
  are explicit buttons ("Find", "Test") that state the exact host first; one call per click.
- Result: friendly metric list with checkboxes ("Members", "Online now", "Stars"...), at least one
  pre-selected sensibly. Next is disabled until valid, with the reason shown.

### Step 2 — Pick a look
- `POST /builder/layouts` returns 3–6 ready layouts for the chosen metrics, each a complete valid
  definition. Show them as large cards rendered with the REAL Block components on seeded sample
  data (/builder/preview), titled in plain words: "Big number + trend", "Gauge ring",
  "Comparison bars", "Warning bars", "Change vs usual", "Dashboard". Each has a one-line "why".
- Picking one loads it into the preview; the user can still add/remove pieces later.

### Step 3 — Make it yours
- Title (pre-filled suggestion), icon (official logo suggested first; brand search; emoji),
  accent swatches + custom colour, density (Compact/Cozy/Roomy), corner style, motion.
- Click any piece in the preview (or its row in a "Pieces" list with drag handle) to open a
  popover/inspector with tabs **Shows** (metric, label, unit) · **Range** (Auto / Fixed / Out of
  another value / Compared to usual — with plain explanations) · **Warnings** (amber/red levels,
  direction) · **Style** (all DISPLAY.md §3 parameters as sliders/swatches/segmented controls).
- "Add a piece" opens a visual gallery with thumbnails + "good for…" text, not "+ stat".
- Plain renames everywhere: Data source(s), Check every, Shows, Pieces, Main piece (hero),
  Warning levels, Big number (stat), Trend line (spark), Change ring (score), Rings, Bar, Bar group.
  Limits as words: "2 of 4 pieces · up to 3 data sources".

### Step 4 — Review & add
- Plain summary: what it watches, where it connects (hosts), how often, requests/hour (≈ format),
  sign-in (none / Hermes MCP grant), and **What happens next**: "You approve it below, then it
  appears in your Pulses panel and starts updating. Nothing is checked until you approve."
- Primary button **Add to Pulses** = POST /drafts (human origin), then the SAME locked approval card
  inline (Approve / Reject). Edits of a live pulse say "Your current pulse keeps running until you
  approve the change." Definition YAML behind "Show definition".

### Preview (always visible)
- Wide: two columns (controls left ≈ 44%, preview right, sticky). Narrow (≤ 480px, the normal
  pane): preview pinned at the top as a compact card (collapsible), steps below; primary action
  bar sticky at the bottom.
- A small "Preview tools" popover holds Sample/Cached/Measured, Simulate state, Light/Dark,
  Compact row — clearly labelled "preview only, not saved". A compact pill "Sample data" replaces
  the big banner (tooltip explains). Durations human ("7 days"). No duplicate labels.

## Visual system
- Use the Desktop SDK UI components where available (Button, Input, Select, SegmentedControl,
  Tabs, Switch, Tooltip, Popover, Badge, ScrollArea, EmptyState) so it looks native; theme vars only.
- One spacing scale (4/8/12/16/24), body ≥ 13px, secondary ≥ 12px, AA contrast, 32px min hit
  targets, visible focus rings, a single dominant primary action per step, fewer borders
  (group with spacing/background), consistent radii.

## API (WP13-builder-api; pure unless stated; tests required)
- `GET /builder/templates` → `[{id, title, description, icon: icon_resolved-shape, kind,
  fields: [{key, label, help, type: text|url|select|number, placeholder, required, options?}],
  lookup: null|'city'|'steam', test: null|'json'|'mcp'}]`.
- `POST /builder/from-template {template, values}` → `{ok, errors: [{field, message}],
  feeds: {name: {kind, params, every}}, metrics: [{ref, label, unit, hint, default_selected}],
  suggested_title, suggested_icon}`. hints: count|percent|ratio|limit|temperature|money|
  duration|size|score|other. Pure: uses only the submitted values (and, for json/mcp, the metric
  pointers the user picked from a prior consented test).
- `POST /builder/layouts {feeds, metrics: [refs], title?, icon?}` → `[{id, title, description,
  why, definition}]` — every definition passes spec.normalize + layout_check; smart ranges:
  metric-bound when a limit/total sibling exists, 0–100 for percent, 'usual' for counts with
  history semantics, auto otherwise; zones only for known safety metrics (AQI, temperature, %).
- `POST /builder/lookup {kind: 'city'|'steam', q, confirm: true}` → consented one-off fetch from a
  FIXED host (`geocoding-api.open-meteo.com`, `store.steampowered.com`), StrictBool confirm,
  rate-limited (1 per 3 s per kind), 3 s timeout, via existing net/http_json safety code, results
  capped at 8 (city: name, admin1, country, latitude/longitude rounded to 2 dp; steam: name,
  appid), never stored, errors sanitized. Also accept Steam store URLs/appids offline (no call).
- Disclose both lookup hosts in README/PR-BODY/CHECKLIST as builder-only, human-click calls.
