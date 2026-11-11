# Groups, arrangement and Hermes session pulses (WP15) — shared contract

Two features built in parallel on separate branches (wp15-groups, wp15-sessions) and merged after the
Builder 2 rework (wp14). Both edit desktop/plugin.js: keep new code in NEW, clearly delimited sections
(`// === Groups & arrangement ===`, `// === Session pulses ===`) and make the touch points in the existing
pane rendering minimal, so the merge stays mechanical.

## A. Groups & arrangement (wp15-groups)
- **Model** (persisted per Hermes profile in the plugin's own data, NOT in pulse definitions, never
  shared and never part of approval):
  `layout = {version: 1, groups: [{id, title, collapsed, children: [ItemRef | Subgroup]}], ungrouped: [ItemRef]}`
  where `ItemRef = {pulse: <pulse id>}` and `Subgroup = {id, title, collapsed, children: [ItemRef]}`.
  Nesting is limited to ONE level of subgroups. Unknown or removed pulse ids are dropped on read; newly
  approved pulses append to `ungrouped` (or to their reserved group, see C). Order = array order.
- **Backend:** `GET /layout` and `PUT /layout` (plain def handlers; validated, size-capped, atomic write, an
  `etag` or revision to reject stale writes). Pure, with no network. Disclosed as local UI state.
- **Expanded group:** a header (chevron, title, count, a compact status summary) above the normal pulse rows.
  **Collapsed group:** each pulse renders as its ring circle in a grid of **4 per row**, wrapping. Each
  subgroup renders as its own labelled row set inside the group, using the **same column widths and x
  positions** as the parent grid. Express depth in the subgroup header only, never by indenting circles.
  Headers and metadata are at least 12px; a parent count includes subgroup membership explicitly (for
  example, `8 pulses · 3 in Developer tools`). Chevron direction matches the effective expanded state,
  including an inherited collapsed state. Hovering or focusing a circle shows the
  SAME info tooltip/card the full row would show; click or Enter opens or expands that pulse.
- **Drag and drop:** pointer-based (no new dependencies; rule 8 allows only @hermes/plugin-sdk and react).
  Drag any pulse above or below another pulse, into or out of a group or subgroup, and reorder whole groups.
  A clear insertion indicator, FLIP-style smooth reflow (transform and opacity only), autoscroll near the edges,
  Escape cancels, and a small movement threshold so clicks still work. 60fps with ~40 pulses, no layout
  thrash. Optimistic update, then PUT; roll back with a quiet toast if the PUT fails.
- **Keyboard and accessibility:** focusable rows; Alt+↑/↓ moves within a list; a "Move to…" menu (group,
  subgroup, ungrouped, new group); live-region announcements; reduced-motion disables the animations.
- **Group management:** New group, Rename, New subgroup, Collapse/expand, Ungroup (pulses return to
  ungrouped), and Delete group (with confirmation, never deletes pulses). Everything stays usable at
  248–320px.
- **Discoverability:** in a non-compact pane with at least four approved pulses and no groups, show a
  small dismissible line containing `Group pulses` and `Show Hermes sessions`. Grouping starts arranging;
  sessions opens the existing settings disclosure, never grants consent automatically. Dismissal is local
  to the profile and survives component remount. Keep both existing options-menu entries available.
- Must not change pulse polling, approval, or drafts. Pending draft cards stay outside the arrangement.

## B. Hermes session pulses (wp15-sessions)
- **Setting:** `show_sessions` (default **off**), toggled in the plugin settings next to background collection
  (same strict-confirmation GET/PUT pattern). Disclosed: local only, no network; shows session titles and
  activity from this Hermes; nothing is stored beyond what's needed to render.
- **Data:** official hooks only (`on_session_start`, `on_session_end`, `on_session_finalize`, `pre_llm_call`,
  `post_llm_call`, `post_tool_call`, `subagent_start`/`subagent_stop`, as available in VALID_HOOKS), plus
  public Desktop SDK state (`host.state.busyBySession`, the session list via `host.request` or the documented
  session APIs) for titles and live busy state. No private imports. Fail soft if a hook or field is missing.
- **Per session pulse:** title, engine state **Working / Idle / Done**, tool calls (this turn and session
  total), and time since last activity while unfinished. Render Done as **`Finished 3m ago`**, with no
  duplicate `Last activity` age in the row, accessible name or tooltip. Session metadata is at least 12px
  and meets AA contrast in both themes. Working has a static outlined play glyph, Idle a visible filled
  dot, and Done a check; state must not depend on colour or motion alone. Subagents count toward their
  parent session. Ignore explicitly mismatched completion `turn_id`s so late end/finalize hooks cannot
  finish a newer turn. Subagent starts wake a parent without resetting its observed turn count.
  Trim SDK titles and use `Untitled chat` for blank/missing titles. Use the same plural-aware, grouped
  tool-count string in rows, accessible names and focus/hover tips; omit known all-zero counts, never
  unknown counts. On observer refresh failure, show a last-observed warning with cached rows, include
  it in collapsed-circle tips and pause their working animation until the observer recovers.
  An ended session lingers as Done for 15 minutes, then disappears. It is ephemeral: never a pulse definition,
  never needs approval (the setting is the consent), and never polls the network.
- **Ids and grouping:** session pulses use ids `session:<stable hash>` and belong by default to the reserved
  group `{id: 'hermes-sessions', title: 'Hermes sessions'}` (auto-created when the setting turns on and
  removed when it turns off; the user may collapse or rename it, or move it in the arrangement; sessions
  always render inside it). Until wp15-groups merges, render them as their own simple section with the same
  id and title.
- **Clicking** a session pulse focuses that chat (documented navigation API).
- **Working animation — "minimalist splurging":** while a session is Working, its ring comes alive in a way
  that feels premium and on-brand for Hermes, not noisy: a soft accent comet sweeping around the ring,
  a gentle breathing glow, and a brief ripple on each tool call; it settles with a satisfying "done" tick
  when the turn finishes. Use theme accent tokens only; animate transform/opacity/stroke-dashoffset only;
  ≤ 1 composite layer per ring; pause when off-screen or the pane is hidden; honour prefers-reduced-motion
  and the pulse motion setting (None/Calm/Lively). It must read well in collapsed 4-per-row circles too.
  The completion check fades/scales as a complete path over 650ms, starting visibly at 88% scale; never
  draw an isolated leading dash.

## C. Renderer-polish verification

- Deduplicate repeated status captions across a hero's rings, its own label/value and caption, and
  expanded sibling blocks. Preserve independently measured values, including equal numeric scores.
  Capsule ratio/title and collapsed tooltip text must not echo identical labels.
- Run browser suites sequentially against the real-SDK preview; do not edit renderer modules during
  the run. A Vite hot reload can invalidate hidden-pane polling and warning assertions.
- Use actual keyboard Tab focus for SDK tooltips, not pointer focus followed by `.focus()`.
- Capture full scenes and exact `.pr-shell` PNGs at 320/670px in both themes. Build native-size review
  sheets with `scripts/capture-wp17-polish2-sheets.py`; never guess crop coordinates from lab framing.
- `scripts/capture-session-motion.mjs` records measured CDP presentation frames to video, then samples
  the actual tick's CSS animation at controlled offsets into lossless PNGs. Keep these evidence types
  distinct: CDP can deliver a stale compositor frame just after the DOM state changes, and its JPEGs
  can soften a small glyph. Inspect the zero-offset PNG as well as the real-time recording.
- Keep baseline row-density checks excluding the explicitly measured discovery-line height, rather
  than loosening row geometry. Check the hint's own one-line fit separately.
- Drop test drags on a visible point in the intended upper/lower half, outside the pane's autoscroll
  zones. If the destination is outside that region, drive real edge autoscroll and remeasure before
  releasing; old 3px-from-edge coordinates can move underneath the pointer as readable headers grow.
- Name the four golden demo files explicitly. Shared artifact folders may gain independent demos;
  assert required files exist instead of rejecting unrelated additions or deleting sibling work.
