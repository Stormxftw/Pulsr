# pulse/1 display extension: feeds, blocks, scales, style, icons (0.5.0-dev)

**Normative contract for WP8.** Additive to `PULSE-1.md` / `INTERFACE.md`: every
existing valid definition stays valid, normalizes identically, and renders identically.
Words MUST/MUST NOT are binding. Where this file and the design draft
(kept outside this repository) differ, this file wins.

## 1. Definition shape

New optional top-level keys: `feeds`, `display`, `theme`. `icon` gains object forms.

```yaml
pulse: 1
title: Metrics service health
feeds:                                  # 1–3 entries; mutually exclusive with `source`
  limits: {kind: mcp.tool, params: {server: metrics, tool: read_limits, args: {}, metrics: {used: /calls/used, limit: /calls/limit}}}
  orders: {kind: mcp.tool, params: {server: metrics, tool: read_queue, args: {}, metrics: {open: /open, late: /late}}, every: 30m}
display:                                # 1–4 blocks; first is the hero
  - {type: rings, rings: [{value: limits.used, max: limits.limit, label: API calls}, {value: orders.open, label: Open}]}
  - {type: bars, scale: shared, bars: [{value: orders.open, label: Open}, {value: orders.late, label: Late, zones: {warn: 2, crit: 5}}]}
  - {type: stat, value: orders.late, show: both, label: Late orders}
theme: {accent: "#7c5cff", density: cozy}
icon: {brand: shopify}
```

### 1.1 Feeds

- `feeds` is an object of 1–3 entries. Name: `^[a-z][a-z0-9_]{0,15}$`. Value:
  `{kind, params, every?}` with exactly the same kind/params/minimum rules as `source`;
  `every` defaults to the kind default and below-minimum is an error at
  `/feeds/<name>/every`.
- A definition MUST have exactly one of `source` or `feeds` (error at root otherwise).
- With `feeds`, top-level `every`, `ring`, `capsule`, `lines` MUST NOT appear (use
  `display` and per-feed `every`). `display` is REQUIRED with `feeds`.
- With `source`, the single feed is implicitly named `main`. `display` is OPTIONAL.
  `ring`/`capsule`/`lines` keep their current meaning and presets.
- `link` stays top-level.

### 1.2 Bindings (references)

A reference is `feed.metric` (`^[a-z][a-z0-9_]{0,15}\.[A-Za-z][A-Za-z0-9_]{0,39}$`).
The metric MUST be a declared metric of that feed's kind (or its `http_json`/`mcp.tool`
`metrics` map). When the definition has exactly one feed, a bare `metric` is accepted and
normalized to `feed.metric`. Errors name the exact path, e.g.
`/display/1/bars/0/value: unknown feed 'order'`. No arithmetic, no expressions.

Bindings count: every `value`, every metric-ref `min`/`max`, every score component.
Maximum 8 per definition.

### 1.3 Blocks

Common optional block fields: `label` (plain text ≤40), `style` (§3).
An **item** is `{value: ref, label?: ≤40, min?, max?, auto_window?, zones?, unit?, style?: {color?}}`.

| `type` | Fields | Rules |
|---|---|---|
| `score` | `components` (exactly like `ring.components`, refs instead of bare metrics) | 1–4 components, weights sum 100; all components from ONE feed |
| `rings` | `rings`: 1–3 items | each ring has its own scale |
| `bar` | item fields at block level (`value`, `min`, `max`, …) | — |
| `bars` | `bars`: 2–3 items; `scale: shared` (default) or `independent`; block-level `min`/`max`/`auto_window` | with `shared`, items MUST NOT set `min`/`max`/`auto_window` (error at the item); with `independent`, block-level `min`/`max`/`auto_window` MUST NOT appear |
| `stat` | `value`, `show: value\|delta\|both` (value), `delta_vs: usual\|previous` (usual), `auto_window`, `unit`, `decimals 0–3` | — |
| `spark` | `value`, `points 8–48` (24) | — |

`unit` is plain text ≤8 chars. `display` has 1–4 blocks.

### 1.3.1 Discrete stat labels and duration

A stat MAY declare `states: {"0": "Failing", "1": {label: "Passing", tone: ok}}`.
There MUST be 1–8 integer-string keys (optional minus, ≤10 digits); labels MUST be
nonempty plain text ≤24 characters with no markup or control/invisible characters.
Object entries contain `label` and optional `tone: ok|warn|crit` (plus ignored x-*).
Exact numeric values select a label; unmapped/noninteger/unknown values MUST stay
unknown, with no inherited tone. Renderer MUST use text nodes, never HTML or numeric
animation for labels, and use the selected tone colour. No expressions or callbacks.

A stat with `unit: duration` formats a nonnegative value **in hours**, rounded down
to minutes: `3.2` → `3h 12m ago`, `27.5` → `1d 3h 30m ago`, `0` → `0m ago`.
Negative/unknown durations remain unknown. `states` and `unit: duration` MUST NOT be
combined. Both modes suppress numeric deltas/learning captions and are measured
when their value is known. Computed rows add `discrete: true` plus optional `tone`,
or `duration: true`; `value_text` is the final text and numeric delta is null.
`layout_check` explains these modes instead of claiming an unused numeric delta.
Existing stat rows/formatting are unchanged without opt-in.

### 1.4 Scales

`min` and `max` each normalize to one of: a finite number; `"auto"`; a reference string
(contains `.`); and for `max` only `"usual"`. Defaults: `min: 0`, `max: "auto"`.
`auto_window`: duration 1h–7d, default `7d` (samples are retained 7 days).

- Fixed numbers: `min < max` required (error at `max`).
- `max: usual` requires `min: 0`.
- A metric-ref bound MUST NOT reference the item's own `value`.
- `zones`: `{warn?: number, crit?: number, direction: up|down}` (up); at least one of
  warn/crit; with both, `warn < crit` for up and `warn > crit` for down.

### 1.5 Icon

Existing string forms (`source`, `hermes`, `initials`, one emoji) unchanged.
New object forms (exactly one key):
- `{brand: slug}`: `^[a-z0-9][a-z0-9._-]{0,63}$`, MUST exist in the bundled brand set
  (`pulse_rings/brands.json`); unknown slug is a validation error with a "did you mean".
- `{url: "https://…"}`: ≤300 chars, HTTPS, port 443, no userinfo/query secrets, public
  host by the same static checks as `http_json` URLs. Its host is added to `budget.hosts`
  (one-off fetch, not req/h).
- `{emoji: "…"}`: same rule as the emoji string.

### 1.6 Alerts

`alert.metric` accepts a reference (normalized to `feed.metric`). Unchanged otherwise.

## 2. Normalization

- `source` definitions: `source`, `every`, `ring`, `capsule`, `lines` normalize exactly
  as today (golden-tested byte-identical). If `display` is present its refs normalize to
  `main.<metric>`.
- `feeds` definitions: each feed gets `every` expanded; no `source`/`every`/`ring`/
  `capsule`/`lines` are added.
- Blocks get defaults expanded: item `min: 0`, `max: "auto"`, `auto_window: "7d"`;
  `bars.scale: "shared"`; stat `show`/`delta_vs`; spark `points`; zones `direction`;
  score components exactly as ring components today. `label` defaults to the metric name
  humanized (`late_orders` → `Late orders`) for items/stat/spark; block label for
  rings/bars/score defaults to omitted.
- `style` and `theme` are canonicalized (hex lowercased) but **not** default-expanded;
  renderer owns style defaults.
- `helpers`: `feeds_of(defn) -> {name: {kind, params, every}}` (returns `{'main': …}` for
  `source` definitions) and `bindings_of(defn) -> list[(json_pointer, ref)]`.
- Budget: sum over feeds of exact `req_per_hour`; `hosts` = sorted union of feed hosts
  plus the icon URL host (if any) plus the icon host implied by `icon: source` for GitHub
  kinds (`avatars.githubusercontent.com`). Admission is unchanged (one pulse, summed budget).

## 3. Style parameters

Colour value: `#rgb`, `#rrggbb`, `#rrggbbaa`, or token `accent|ok|warn|crit|muted|ink`.

| Where | Key: allowed values |
|---|---|
| `theme` | `accent`, `surface`, `text`: colour; `density`: compact\|cozy\|roomy; `radius`: int 0–24; `font`: system\|rounded\|mono; `motion`: none\|calm\|lively |
| any block `style` | `color`, `color2` (gradient end), `track`: colour; `thickness`: int 2–24; `radius`: int 0–12; `glow`: int 0–16; `text`: s\|m\|l; `label`: above\|inline\|hidden |
| `rings` style | + `gap`: int 0–6; `cap`: round\|flat; `direction`: cw\|ccw |
| `bar`/`bars` style | + `ticks`: none\|usual\|zones; `show_range`: bool |
| `stat` style | + `delta_colors`: semantic\|neutral |
| `spark` style | + `fill`: none\|area; `dot`: last\|none |
| item `style` | `color` only |

Unknown keys are errors except `x-*`. Style never affects approval cards (§6).

## 4. Engine computation (`pulse_rings/display.py`, pure)

`compute_display(definition, feeds) -> list[block_row]` where `feeds` is
`{name: {current: sample|None, history: [samples, oldest first, excluding current], status: feed_row}}`
and a sample is `{ts, metrics: {bare_name: number|None}, baselines, unknown_reasons}`.
Returns `None` when the normalized definition has no `display`.

### 4.1 Scale resolution for an item (or shared group)

Let `v` be the current value (None if no current sample or metric null).
`W` = measured `(ts, value)` pairs of the item's metric(s) with `ts ≥ now − auto_window`,
from history **and** the current sample (`now` = current sample ts, or the latest feed
sample ts in the pulse when the item's feed has no current sample).

- `min`: number → itself; ref → that metric's current value; `auto` → `nice_down(min(W))`.
- `max`: number → itself; ref → current value of the ref; `auto` → `nice_up(max(W))`;
  `usual` → `2 × median(prior measured values in window, excluding current)`.
- **Learning** (fill null, `learning: true`) when any `auto` bound has fewer than 3
  measured points in `W` or `W` spans < 3600 s; or `usual` has no prior measured value or
  median ≤ 0. Caption `Learning range · {n} samples` (`Baseline not ready` for usual).
  Item rows expose `min: null`, `max: null`, and `range_text: null` while learning:
  provisional ranges (especially `0–0`) are not measurements.
- **Range unavailable** (fill null, caption `Range unavailable`) when a ref bound is
  unknown, or the resolved `max ≤ min` (after auto resolution; see nice rules).
- Otherwise `fill = clamp(100 × (v − min)/(max − min), 0, 100)`, `over = v > max`,
  `under = v < min`.
- Shared `bars`: `W` is the union of all items' points; one resolved range for all items.

`nice_up(x)`: x ≤ 0 → 0 (then if min is 0 and max resolves to 0, use 1);
x > 0 → smallest of `{1, 2, 2.5, 5, 10} × 10^k` ≥ x (relative tolerance 1e-9), rounded to
12 significant digits. `nice_down(x)`: x ≥ 0 → largest of `{1, 2, 2.5, 5} × 10^k` ≤ x, and
0 when x == 0 or x < 1e-12; x < 0 → `−nice_up(−x)`.

### 4.2 Item row

```text
{ref, feed, metric, label, value, value_text, unit, unknown, reason,
 min, max, fill, over, under, learning, tone, ticks: [pct...],
 range: {min_form, max_form, window_seconds, samples},  # forms: fixed|ref|auto|usual
 caption}
```
- `value_text`: `_format` from engine (thousands separators, ≤3 decimals), then unit
  appended with a space when present. `None` when unknown. For `minutes_since_last`
  with `unit: min`, or `unit: duration` (hours), nonnegative readings use elapsed
  durations, e.g. `624.2` minutes → `10h 24m ago`; numeric value/fill stay unchanged.
  These items additionally expose final `range_text` without an `ago` suffix,
  e.g. `0m–16h 40m`, or null without a valid range. Auto captions use the same bounds.
  Renderers prefer `range_text` when present and fall back to existing formatting
  with older engine rows.
- `unknown = value is None`; `reason` = the sample's `unknown_reasons[metric]`, else the
  feed's error, else `Not measured`. Unknown NEVER yields a non-null fill or a tone.
- `tone`: none when no zones/unknown; `crit`/`warn`/`ok` by `direction`.
- `ticks`: `[50]` for `usual`; zone positions (pct of range, clamped) for zones; else `[]`.
- Captions (exact): learning/unavailable as above; fixed → `{pct}% of {max_text}`;
  ref → `{pct}% of {metric humanized lowercase}`; auto → `auto {min_text}–{max_text} · {window}`;
  usual → `{pct}% of usual`, or `{r:.1f}× usual` when ratio ≥ 2. `pct` = round half up of
  100 × v / max for fixed/ref/usual (not fill). When `over`, append ` · above max`;
  when `under`, ` · below min`. `{window}` uses engine `_window`.

### 4.3 Block rows

- `score` → `{type, label, ring}` where `ring` is exactly `compute_ring` output computed on
  that feed with bare metric names. Scoring follows `PULSE-1.md`'s count-noise floor,
  decrease denominator and zero-usual warming rules. Each component optionally
  provides `baseline_text` (integer half-up for built-in counts, e.g. `17,777.5` →
  `17,778`; never change the numeric baseline/delta) and `warming`. Renderers should
  label observed history `Usual (median)` / `Usual (oldest)`, not `Normal: Median`,
  prefer the final baseline text, and fall back to their existing numeric formatter.
- `rings` / `bars` → `{type, label, scale (bars only), items: [item rows]}`.
- `bar` → `{type, label, items: [one item row]}` (same shape as bars, for one renderer path).
- `stat` → `{type, label, ref, value, value_text, unit, unknown, reason,
  delta, delta_text, delta_vs, caption}`; `delta` vs the source-reported baseline
  when present (usual), else median of prior in window (usual), or the last prior
  measured value (previous). This makes `vs usual` consistent with source-baseline
  scores; `previous` never substitutes a source average. `None` without a baseline
  → caption `Learning baseline` (or `Waiting for previous sample` when the source
  usual is already available). `delta_text` signed with `+`/`−`.
- `spark` → `{type, label, ref, points: [{ts, value|null}] (last `points` samples, oldest
  first, current last), lo, hi, unknown}`; null points are gaps.

Every block row also carries `style` (normalized definition style, verbatim) and
`index`. Item rows carry their item `style`.

## 5. Status rows (additive)

Each pulse row gains:
- `display`: block rows or `null` (no `display` in definition → `null`; renderer uses the
  legacy ring/capsule/lines layout, unchanged).
- `feeds`: `[{name, kind, state, last_ok_ts, next_due, backoff_until, error, budget}]`;
  `source` pulses have one entry named `main` mirroring the row fields.
- `theme`: normalized theme or `null`.
- Pulses with any `desktop.notifications` feed (including legacy source/preview)
  add optional `notifications: {summary, details}`. The short summary is
  `Counts notifications still in Windows, not unread messages. Local only.`
  Full read-only/counts-and-times/privacy/window/cleared-arrival limitations stay
  in `details`, intended for a collapsed `How this works` disclosure. Older rows
  without this additive field keep the renderer's static disclosure fallback.
- `state` adds `degraded` (some but not all feeds failing).
- For `feeds` pulses, legacy fields are derived: `ring` = first `score` block's ring, else
  `{score: 0, warming: false, unknown: true, components: [], baseline_samples: 0,
  window_seconds: 0}`; `capsule` = `{label: "<label> <value_text>", fill, caption}` from the
  first item of the first rings/bar/bars block (or `{label: title, fill: null, caption: ''}`);
  `lines` = `[]`.
- `history` stays the legacy 48-sample list for `source` pulses; for `feeds` pulses it is
  the hero item's feed history.

## 6. Rendering rules (renderer)

- The renderer never recomputes fill, tone, learning, captions or unknown; it only clamps
  geometry and formats nothing beyond what the row gives.
- Style parameters map to CSS custom properties on `.pr-block` (`--pr-b-color`,
  `--pr-b-thickness`, …). Values come only from validated rows; the renderer re-validates
  colour strings with the same regex and drops anything else.
- Stable hooks for user CSS: `.pr-pulse[data-id]`, `.pr-block[data-type][data-index]`,
  `.pr-item[data-tone][data-state]` (state: measured|learning|unknown|unavailable),
  `.pr-bar__track`, `.pr-bar__fill`, `.pr-ring__arc`, `.pr-ring__track`, `.pr-stat__value`,
  `.pr-stat__delta`, `.pr-spark__line`, `.pr-spark__dot`, `.pr-caption`.
- `plugin-data/pulse-rings/custom.css` (optional, local, user-owned): served via
  `GET /custom.css` as text; the renderer strips `@import`, `url(`, `expression(`,
  `behavior:` and `-moz-binding` (case-insensitive) and scopes it under `.pr-shell` (rules
  outside are dropped). It is never applied inside `.pr-approval` and never to
  host/budget/approve/reject elements: approval surfaces render with a fixed style and
  ignore `theme`/`style`.
- Visual declarations on display hooks only: font-size (8–48px only),
  font-family (generic families or quoted local names; no remote
  fonts), letter-spacing (−2–8px), line-height (.5–3 or 8–64px), text-transform,
  opacity (0–1), padding/margins/gap/border-width/radius (0–32px; margins down
  to −8px), border-style, box/text shadows (finite decimal px lengths at most
  64px, nonnegative blur, at most four shadows), linear/radial gradients, and
  drop-shadow/brightness/saturate filters (at most three filters;
  brightness/saturate unitless 0–3). Every length token uses the same bounded
  px/unitless-zero grammar. Exponents, Q/relative/physical/viewport/% lengths,
  math/variable functions, comments and escapes are refused before CSSOM can
  normalize their tokens. CSSOM-expanded longhands are checked individually.
  Resource functions, CSS variables, escapes, @-rules, position,
  z-index, transform, inset, content and display remain forbidden. Pulse roots,
  approval cards, host/budget disclosures and controls are not targetable; the
  existing selector scope is not widened. Every customizable `.pr-pulse` card
  and `.pr-block` has paint containment and isolation. Pending cards and approval
  regions have their own plugin-local stacking contexts above active siblings,
  with solid theme backgrounds. The decoded approval/button pixels and hit
  targets must survive the original exponent/Q overlay attacks, even when the
  test harness deliberately bypasses the sanitizer. This is not a general CSS sandbox.
- Live: blocks update in place on refetch (no remount), with 700 ms transitions honoring
  `prefers-reduced-motion` and `theme.motion: none`; a beat marker when any feed's
  `last_ok_ts` advances.

## WP8-spec notes

- Legacy `source` definitions (including bare alert metrics) keep their normalized
  shape. Display-bearing source definitions canonicalize display/alert refs to
  `main.metric`; feeds definitions canonicalize to their sole feed when unambiguous.
- The eight-binding cap counts display values, metric-ref scale bounds and score
  components, not alerts or legacy ring/capsule/lines. `bindings_of` also reports
  alert refs for consumers; repeated references count separately.
- Shared bars expand scale defaults only on the block, never on their items (which
  would invalidate the normalized definition). Shared bounds cannot reference any
  value in the group. Independent bars expand defaults only on items.
- `auto_window` accepts s/m/h/d equivalents inclusively from 1h through 7d;
  cadence and score-component windows retain the existing s/m/h syntax. Use
  `display_spec.window_seconds` for auto windows. Stat decimals remain omitted
  when unspecified because the contract declares no decimals default.
- Budget hosts are always a sorted union, including legacy single-source budgets;
  this changes Discord host ordering but not host membership. The frozen old
  snapshot remains untouched; comparisons canonicalize host ordering and explicitly
  assert the intentional GitHub avatar-host addition. UI fixtures were regenerated
  offline to reflect those budget-only differences.
- Icon objects allow exactly one of brand/url/emoji plus preserved `x-*` data.
  URL query credential names use the MCP credential-key guard vocabulary; ordinary
  query data is allowed. Static public-host checks do not replace runtime SSRF checks.
- The five-entry brand JSON is a placeholder for WP8-icons (its marker is in
  `brands.py`; JSON stays a strict slug-to-record map without comment/metadata keys).
## WP8-display notes

Implementation choices where §4 leaves a detail implicit or conflicts with another
clause (all are covered by expected-value or invariant tests):

- **Usual caption denominator:** geometry uses `max = 2 × prior median`, but
  usual captions/ratio use the median itself, matching `engine.compute_capsule`:
  baseline-valued input is `100% of usual` at fill 50, not `50% of usual`.
  Ordinary `r:.1f` text retains the engine's float formatting (e.g. 2.55 → `2.5`).
- **Nice-number tolerance vs strict bounds:** the explicit 1e-9 relative tolerance
  wins over a literal `nice_up(x) >= x` assertion right above a boundary (e.g.
  `nice_up(1.0000000001) == 1`). Negative `nice_down` inherits that tolerance.
  Random invariants check strict inequalities away from those tolerance bands;
  dedicated boundary tests check the tolerated inequalities.
- **State/caption precedence:** unknown value → `Not measured` caption, even when
  range metadata is learning/unavailable; unknown ref bound → unavailable (not
  learning); insufficient auto evidence/nonpositive usual baseline → learning;
  only after learning completes does an inverted auto range become unavailable.
  `over`/`under` are false until a range is usable. Measured zone tones remain
  meaningful even during learning/unavailable; only unknown suppresses tone.
- **Empty and zero evidence:** an empty auto bound is null, not an invented zero.
  The 0→1 max fallback applies only to an auto maximum with resolved min zero;
  a zero usual baseline remains learning. `range.samples` counts measured `W`
  points including current (also for fixed/ref/usual); window_seconds is the
  configured window, not the observed span used by the learning gate.
- **Shared time/evidence:** use the latest effective item clock, with each missing
  current falling back to the latest sample anywhere in the pulse (or 0 when no
  samples exist). One cutoff/range is used for the whole group. Evidence pools
  distinct bindings, so equal values from different metrics count separately,
  but repeating one binding does not multiply its evidence. Shared usual pools
  prior values of those bindings, excluding every feed's current sample.
- **Prior:** history-only samples at `ts < now`, inside the inclusive lower window
  boundary; nulls do not count. Previous means the latest measured prior in that
  same window, not an unknown immediately preceding sample. No wall clock is read.
- **Ticks:** usual always yields `[50]`, even while learning; otherwise zone ticks
  are emitted in warn/crit order (descending for down zones), clamped independently
  without deduplication. Zone ticks require a usable range. Style tick visibility
  is a renderer choice; it does not change the calculated ticks or tone.
- **Stat:** measured captions are `vs usual` / `vs previous`; absent prior gives
  `Learning baseline`, absent current gives `Not measured`. The row additionally
  carries normalized `show` so the renderer can honor value/delta/both without
  recomputation. Both numeric values remain present regardless of show. Explicit
  decimals means fixed-width half-up precision with separators and unit suffix;
  omitted decimals uses engine `_format`. Zero delta has no sign, matching `_format`.
- **Output defaults:** omitted block label is null, style is `{}`, unit is `''`;
  styles are copied verbatim without renderer defaults. Unit is appended to value
  and stat delta text, not range-bound caption text. Spark unknown describes current
  value, not whether older measured points remain; absent current adds no fake gap.
- **Score without current:** call `compute_ring` with an empty-metrics sample at
  the pulse's latest timestamp, using feed error / `Not measured` for component
  reasons. With current present the returned ring is exactly the existing engine
  output after stripping feed prefixes from component metric names.
- **Finite numeric limits:** decimal intermediate arithmetic prevents overflow in
  fills, percentages and even-median sums. An unrepresentable nice bound or doubled
  usual baseline saturates at the largest finite float (no representable nice
  candidate exists beyond it). Overflowed stat delta is null with `Range unavailable`;
  valid negative-to-zero fixed/ref ranges retain their calculated fill but use
  `Range unavailable` for the undefined max-relative caption rather than divide by
  zero. These numerical fallback cases do not turn an unknown input into zero.

### Remaining inherited contract conflict

The exact-score requirement and an unconditional JSON-finite invariant cannot both
hold for every finite feed input with the existing `engine.compute_ring`. Opposing
`-1e308` prior / `1e308` current values produce a finite contribution but `delta: inf`.
The display adapter deliberately preserves the exact ring result rather than
silently changing legacy math (engine edits were excluded from WP8-display).
`test_inherited_score_overflow_cannot_satisfy_json_finite_invariant` is a strict
expected failure documenting this boundary. Resolve upstream by authorizing a
finite-derived-value policy for `compute_ring`, or explicitly permitting display
score sanitization. The seeded random-stream invariants otherwise pass for every
block type; item/stat extreme arithmetic is separately JSON-finite tested.
## WP8-icons notes

- Simple Icons **16.36.0**: 3,467 input records, **3,465 accepted**, zero invalid
  paths, two excluded by explicit ARTWORK SCOPE; **4,811,947 bytes** in reviewable
  per-record JSON. Hard cap: 5,000,000 bytes; oversize builds fail without writing.
  This is deliberately not a complete upstream bundle: slug/title/upstream-source
  matches for crypto_mining/tunnel_service are absent, never renamed or encoded.
  `scripts/ARTWORK-SCOPE.md` mirrors the real scanner patterns and source lines;
  HERMES_SOURCE reads them at build time. `scripts/build-brands.py` records every
  excluded slug/reason, version, archive SHA256, counts and verbatim legal notices
  in `pulse_rings/BRANDS-LICENSE.md`. CC0-1.0 does not grant trademark rights.
  Brands removed upstream at their owners' request remain absent too.
- SVG path validation is a grammar, not a markup stripper: command arity, finite
  numbers, initial moveto, arc radii/flags (including compact `01`) and separators.
  No network SVG is accepted. The Hermes source mark is an original bundled
  winged H monogram, not a Simple Icons entry or a claim to official logo rights.
- `icon_resolved` is additive; see `desktop/ICONS-CONTRACT.md` for the four shapes.
  The legacy Discord `icon_url` / `/icons/<guild>-<hash>` behavior and JSON data-URI
  route response remain unchanged. New cache keys are `sha256-<64 lowercase hex>`
  derived from the full source URI (never expose its query/path in status).
- Fetch only in the activated/claimed polling seam; read-only status, tools,
  previews and GET `/icons` do not fetch. Cache hits make zero requests. Failed
  keys are gated for six hours; local Net pacing is not a remote failure and may
  retry next tick. Icons are capped at 256 KiB, including existing Discord icons.
- GitHub adapters expose counts, not owner avatar metadata; derive the avatar URL
  from the approved repository's owner login and only use exactly
  `avatars.githubusercontent.com`. Old approvals lacking that host do not gain
  egress silently and fall back to the offline GitHub brand.
- MCP metadata is read from the connected MCPServerTask's `_tools` and
  `initialize_result.serverInfo` in the captured owning profile context; never
  discover, reconnect or dispatch for an icon. Try Tool.icons before server icons;
  within each list prefer raster MIME and sizes nearest the 64–128 px range.
  Theme is neutral. Decode raster base64 `data:` locally; HTTPS candidates,
  **including cache lookup**, require exact persisted budget.hosts membership.
  Undisclosed hosts are skipped, never added implicitly. Arbitrary icon hosts use
  `net.fetch_bytes` via the existing DNS-vetted, numeric-IP-pinned TLS transport;
  unavailable Hermes URL-safety APIs fail closed. Redirects are never followed.
- Multi-feed icon selection uses source-type precedence (Discord, GitHub, MCP,
  Hermes), then declaration order within each type. Feed polling/status assembly
  integration belongs to WP8-display; the resolver itself accepts both forms.
## WP8-render notes

- Renderer rows are exactly §4.2/§4.3, not normalized definitions. In particular,
  stat rows do not carry definition `show`, and spark rows carry no `learning`,
  `reason`, `over`, `under`, or resolved-range fields. Stat renders the supplied
  `value_text` and available `delta_text`; spark renders supplied points/lo/hi and
  only its supplied `unknown`. The scenario gallery exercises all block types in
  each pulse scenario, but does **not** invent unsupported per-block states for
  spark/score/stat. Range unavailable and over/under apply only to scaled items.
- Score reuses Ring and its supplied `warming`/`unknown`; unknown component reasons
  are shown when supplied. It has no engine caption field, so uses the existing
  Learning baseline / Not measured presentation, never an invented percentage.
- Range text uses the already-resolved item `min`, `max`, and `unit` literally;
  captions/value_text/tone/fill are never recalculated. Tick percentages are used
  verbatim with geometry-only clamping; `ticks:none` hides them.
- Theme properties live only on the active pulse's trigger and display group,
  not its disclosure/action region. Pending cards use the legacy fixed approval
  renderer and ignore display/theme. No theme variables are inherited by hosts,
  budgets, approval/rejection buttons, or management actions. Legacy `display:null`
  keeps the original DOM (including its original classes); `.pr-pulse` is additive
  only for new display rows so legacy DOM is byte-identical.
- User CSS is deliberately a **conservative hook-only subset**, not arbitrary
  application CSS. Accept simple hook-class/data selectors and descendant/child
  combinators; scope beneath `.pr-shell .pr-pulse:not(.pr-pending)` and exclude
  `.pr-approval` descendants. Reject non-hook/outside selectors, all at-rules
  (including @font-face/media), escapes, resource-bearing declarations,
  layout/overlay declarations and inherited variables. Allow bounded block vars
  and visual declarations; WP9's explicit bounded extension is listed in §6.
  This allowlist prevents outside/approval styling
  through ancestor rules, nesting, selector tricks, or inherited CSS variables.
- Synthetic display fixtures live in `preview/display-fixtures.js`, separate from
  engine-generated JSON fixtures. Their on-page caption says HAND-AUTHORED
  SYNTHETIC / NOT ENGINE OUTPUT. The connector-like feeds are local synthetic MCP rows,
  not real connector readings. Live mode mutates these rows every 1.6s only in the
  harness; production uses the existing shared query/refetch policy.
- Legacy pixel characterization mounts `3b04572:desktop/plugin.js` through a
  preview-only Vite virtual module. It aligns the legacy row on an identical
  pixel grid because neighboring new display rows intentionally have different
  heights, then compares exact DOM and PNG bytes in light/dark, collapsed/expanded.
- The installed Desktop SDK REST bridge JSON-decodes every response (verified in
  `apps/desktop/electron/main.ts`); raw `text/css` is otherwise inaccessible via
  `ctx.rest`. Canonical `GET /custom.css` remains text/css. The additive
  `GET /custom.css?format=json` returns the **same CSS text as a JSON string** for
  SDK transport; the renderer uses this representation, then the same sanitizer.

## WP9-engine notes

- **Compatibility vs additive rows:** §5's `display`, `feeds`, and `theme` keys are
  additive even on source-only rows. Byte-identical legacy means the old-key
  projection, not an unchanged JSON object with no new keys. Twenty frozen main
  status cases compare serialized old-key projections; regenerated UI fixtures
  differ only by these additive fields. Source normalization/presets remain intact.
- **Storage authority and migration:** retain additive schema family version 1 and
  schema-cookie/identity caching. Rebuild the old sample primary key atomically as
  `(pulse_id, feed, generation, ts)`, copying old payloads verbatim to initial `main`.
  Persist feed state and recurring budgets separately. Kind/params changes or
  removed/renamed feeds allocate a new generation; incompatible observations are
  archived, not used as current/history/range/baseline/learning evidence. Check
  the claim generation before every success/error/deferral completion write.
  Unchanged identity retains history/state on layout/theme/title/cadence edits,
  including legacy source-only main replacements; see INTERFACE.md for migration
  and implicit/explicit main compatibility. Legacy `pulses` columns stay authoritative
  for implicit `main` and mirror polls. The consented importer creates its main
  generation before samples, so it can poll immediately without reopening.
  future definitions are preserved, not admitted anew. Upgrade tests replay an SQL
  dump created with main's a19b0fd Store before implementation.
- **Scheduling:** retain preview-first behavior. Otherwise claim the single due
  feed ordered by `next_due`, pulse ID, then feed name (lexical tie-break, not
  declaration order), with the existing atomic 90-second lease. The adapter gets
  the pulse identity plus only that feed's source and cadence. Cadence jitter,
  adapter-provided due times, deferrals, exponential/404 retries and actual Net
  accounting are unchanged and scoped to the claimed feed. Shared remote-host
  gates still apply to every feed using that host; unrelated hosts keep working.
- **Budgets:** activation/approval admits one pulse against the summed persisted
  pulse budget. Per-feed status budgets describe recurring source egress (without
  pulse-level one-off icon hosts); legacy `main` mirrors its full persisted pulse
  budget. Cached status never revalidates definitions or recomputes budgets.
- **Current vs failure:** on explicit-feed failure/backoff, keep last-good samples
  in SQLite/history but supply an in-memory unknown current at the status clock,
  with that feed's error as the reason. Do not persist a fabricated failure sample.
  Other feeds remain measured. Some failing feeds means `degraded`; all means
  `error` (individual rows still distinguish backoff/error/unsupported). Paused
  takes precedence. Pure legacy source rows retain their last arc on failures.
- **Aggregate fields:** `last_ok_ts` is the newest feed success, `next_due` the
  earliest effective feed due, `backoff_until` the latest gate, and `error` a
  feed-labelled join. Without failures, any stale feed makes the pulse stale;
  otherwise an absent sample or warming score makes it warming, then active.
  Scale learning alone does not mean source failure or pulse warming.
- **Hero and legacy projections:** the hero is the first value/component of the
  first block (first item for rings/bars). Its feed/metric determines kind/every
  and the 48-point history. Ring is the first score block or §5's unknown fallback;
  capsule comes from the first scaled block anywhere, using `unknown` text when
  `value_text` is null, or the title fallback; lines are empty. `icon: source`
  follows that hero feed rather than WP8-icons' source-type precedence, while
  explicit icons still win. Resolver internals and its standalone precedence
  behavior are unchanged.
- **Windows/evidence:** read seven days of indexed per-feed history, capped at
  20,161 observations (seven inclusive days at the fastest supported 30s cadence),
  plus the legacy 48-point stale tail. Compute-display history excludes current
  exactly once; score/stat/spark/scales all use the same current and history.
  Source pulses with display get a separate seven-day display window without
  altering legacy ring/history windows. Read-only status uses one connection.
- **Alerts:** qualified metric alerts select the referenced feed's effective
  current, including failure masking; source-display `main.metric` refs work too.
  Ring alerts use the derived first score block. No failed feed's cached value
  creates a fresh metric alert.
- **Previews:** only session origins allow existing fixed-host Discord/GitHub
  previews. Each eligible feed has its own durable two-dispatch cap/lease/state;
  up to 2 per eligible fixed-host feed, so up to 6 for three feeds; a viewed
  refresh still performs at most one preview operation. MCP/http_json never
  automatically preview; builder Test call is separately human-consented, not a
  draft preview. Cron/subagent/kanban/unattended origins
  stay inert even under a later interactive poller. Partial previews are full
  status rows with unknown unsampled blocks; no observations means no preview.
  Parent `preview_calls` is the sum, with per-feed disclosure in `preview_feeds`.
  Readback rebuilds previews from aggregated samples so simultaneous finishers
  cannot lose another feed's block. Approval transfers all feed samples/state,
  preserves the usual +2-second initial due, and rechecks summed admission.
- **Verification scope:** the existing `scripts/smoke-backend.py` is the obsolete
  live Discord Pulse API (`CURATED`, `add`, `snapshots`, `servers`) and requires
  real network calls. It is not applicable to this backend and was not run.
  Offline SQLite/real FastAPI feed/definition/notes tests and both browser suites
  exercise the supported runtime without contacting live services.
## WP9-tools notes

- `pulse_rings_catalog` keeps source schemas/presets and adds machine-readable
  block fields (derived from the validator), defaults/limits/examples, scales,
  scoped styles, icons and feed rules. Successful default-JSON serialization is
  hard-capped at **65,536 UTF-8 bytes**, including search results. Optional
  `brand_query` is 1–80 nonblank characters; case-insensitive slug/title exact and
  substring matches precede difflib matches (cutoff 0.6). At most ten distinct
  `{slug,title}` rows are returned; no SVG paths or network discovery.
- `pulse_rings_layout_check(definition)` is independent of engine construction,
  execution origin and runtime MCP policy. It validates/normalizes with spec.py,
  reports exact budgets and describes each block/item without inventing readings.
  Invalid definitions return `{ok:false,errors:[{path,message}],blocks:[],warnings:[]}`
  without normalized output; valid ones add `normalized` and `budget`. Legacy
  definitions get a legacy-layout description rather than invented display blocks.
- Auto explanations describe the evidence gate, not a waiting promise: at least
  three measured points spanning an hour in the configured window. No source,
  icon, store, clock or MCP policy is fetched/written by layout check. Bundled
  brand metadata may be read locally by ordinary definition validation.
- Warnings are advisory strings, never validation errors: more than two rings in
  the first/hero block; an auto max with a same-feed metric named limit/total/
  capacity/max (or `<metric>_<suffix>`); and explicit hex foreground/track colours
  below **3:1** against an explicit opaque hex `theme.surface`. Foreground alpha
  composites onto that surface before WCAG sRGB contrast; unknown token/default
  surfaces and translucent surfaces are deliberately not guessed. Limit-like
  names are heuristics, not proof that a metric is the correct denominator.
- The propose tool normalizes before obtaining the engine, preserves the original
  exact card token, and adds `feeds`, `icon_hosts`, `summary` and the exact total
  `budget`. Each feed's allocation reuses spec.budget with offline initials to
  exclude icon egress. Summaries disclose every kind/target/cadence/exact req/h,
  the summed recurring budget and all direct hosts. Explicit/source icon hosts
  are listed separately as one-off, not req/h; MCP metadata icon hosts are never
  implicitly added. Connector network/private data is not represented by empty
  direct hosts. Human-only approval remains; no automatic pre-approval MCP preview
  dispatch. The explicit builder Test call exception below is separately consented.
- Multi-feed draft persistence is an engine integration seam owned by WP9-engine;
  `test_propose_multifeed_roundtrip_real_engine` is an unconditional integration
  gate, not a skipped/mock substitute. The tool layer does not bypass the engine
  or reach into its store to make a standalone branch appear integrated.
## WP9-builder notes

- Builder entry points are New pulse, live-pulse Edit, and pending Open in builder.
  The pane switches in place; a transcript card may use an SDK-owned workspace.
  Compose, real Block preview, and YAML/JSON definition are three independent
  scroll panes; widths at/below 640px use tabs. Block ordering has drag/drop,
  buttons, and Alt+ArrowUp/Down. Form edits validate after a short debounce;
  pasted YAML/JSON applies only after layout-check succeeds. Errors retain their
  JSON Pointer and are repeated beside the matching fields and in Definition.
- `POST /layout-check {definition}` normalizes/validates and returns budget and
  normalized YAML without source activity. `POST /builder/preview` accepts only
  `mode:sample`, an integer seed, and measured|learning|unknown|over|under|stale|
  degraded. Values come from a local seeded generator and **real** compute_display;
  sample rows expose `sample:true`. There is no clock, network dispatch, storage
  mutation or ambient-random mutation. URL icons do not fetch. Limit-like names
  receive plausible denominators; bundled brands/emoji/initials render offline.
- State names simulate feed conditions, not overrides of engine truth. Fixed/
  metric/usual scales can overflow; auto includes the current value by contract,
  so over/under cannot force overflow on an auto bound. Learning need not affect
  fixed bounds; spark/score/stat keep their existing engine semantics. Cached
  renders the original edit snapshot; Measured renders approved current rows,
  not a fictional recomputation of edited bindings against missing feed history.
- MCP inventory is metadata-only in the owning profile. The explicit Test call
  checkbox + button consents to exactly one dispatch, separately from approval.
  StrictBool confirm, source-schema args validation, fresh read-only/spend policy,
  captured profile context, refusal scope, shared semaphore/in-flight exclusion,
  source dispatcher and decoder are reused. A per-profile/tool monotonic 10s gate
  is ephemeral. No retry, source activation, reconnection or auto-approval occurs.
  Results are response-local; body text is capped at 64KiB, numeric RFC6901 leaves
  omit booleans/nonfinite numbers. Truncation disables binding. Timeout retains
  in-flight ownership until the worker ends and discards late results. Changing
  tool/args/profile discards test results and consumes/requires fresh consent.
- HTTP test fetch is intentionally omitted: arbitrary HTTP/URL icons require
  destination review and persisted approved-host state in existing net code.
  Relaxing that just for a preapproval test is not trivially safe. Users can
  author JSON Pointers and inspect after normal approval instead.
- Create draft posts the exact definition (replacement keeps id), reads back
  `/drafts/{id}`, then shows the normal locked approval card. The live pulse
  keeps running until human approval. Builder never posts approve. Ask Hermes
  uses documented `host.composer.insertText` (unsent); clipboard is the fallback.
- WP9 intentionally adds one Edit action to legacy expanded details. Pixel/DOM
  characterization removes only that new action to compare all original legacy
  measurement content and controls; separate widget tests retain the compact
  detail-height bound. No legacy display math or source/engine files are edited.
- The local preview bridge executes only pure builder/catalog functions. MCP,
  draft writes and explicit approvals in the browser lab are clearly local mocks,
  never proof of a live connector or production approval. Full backend and all
  three browser suites must be rerun after integrating sibling WP9 branches.

## WP10-polish notes

- Builder body is 13px and secondary copy at least 11.5px. Two balanced columns
  keep Compose independently scrollable and Preview visible; Definition is a
  closed disclosure beneath Preview. At ≤640px, existing keyboard-operable tabs
  remain. Data opens for the selected block; Range, Zones and Style are native
  disclosures. Technical notes live in About this preview. The unsent authoring
  request lives in Review draft; the lab's simulated composer is also collapsed.
  The synthetic Sample values watermark never disappears in Sample mode.
- BrandGlyph is shared by picker and live/preview icons. It measures WCAG sRGB
  contrast against the composited solid surface and switches paths below 3:1 to
  theme ink (then adaptive black/white if necessary), retaining the brand hex as
  an outline. See desktop/ICONS-CONTRACT.md. No network artwork or host selectors.
- Seeded synthetic values default to integers, including over/under scenarios.
  Decimal precision is opt-in from whole metric/JSON-pointer tokens (snake/camel
  case) or a bound unit: ratio, percent/percentage/pct/%, rate, temperature/temp,
  Celsius/Fahrenheit/°C/°F, GB/GiB/MB/MiB/TB, latency, seconds or ms. Display labels
  do not imply precision. Ratios center on .62, percentages on 62, memory on 7.1,
  temperatures on 24; decimals have at most two places. Unknown names stay counts.
  Limit/total/capacity/quota/max tokens are stable denominators; prefer a named
  sibling (including a singular/plural spelling), otherwise cover the feed's
  largest magnitude with headroom. Only explicit over/under scenarios exceed a
  denominator; they do not patch engine output. Same definition/seed stays exact.
- Number count-up animates a decorative copy of engine strings via rAF (700ms,
  lively 500ms); accessible names and settled strings are exact engine text. No
  captions, fill, tone, unknown or numeric readings are recomputed. Fixed-width
  tabular slots prevent digit-width jumps. Non-numeric/unknown/extreme strings
  snap rather than invent readings. Reduced motion and theme.motion:none snap
  immediately and suppress the subtle new-sample beat.
- scripts/test-polish.mjs adds actual computed-colour contrast checks in both
  themes/preview appearances, keyboard disclosures, integer samples, three ticks
  without element-bound layout shifts (plus digit boundaries), exact settled
  strings and reduced-motion checks. Artifacts cover 900/1280px and a 248px pane.
  These are local fixture checks, not proof of production connector behaviour.
