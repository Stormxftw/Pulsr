# Pulsr UI lab

This harness mounts the **actual** `desktop/plugin.js`, replacing only the public
SDK boundary with local mocks. It never loads into a running Hermes Desktop,
installs dependencies, changes a profile, or sends requests to a source API.

## Reproduce

From this worktree, with the Hermes checkout's existing frontend dependencies:

```bash
node scripts/preview-server.mjs $HERMES_SOURCE 5198
# In a second terminal:
node scripts/test-widget.mjs $HERMES_SOURCE $ARTIFACTS/pulse-rings/wp4
```

Use `PULSE_PREVIEW_ORIGIN` to test a different local port. Server Vite caches stay
outside the repository under TMPDIR; screenshots/results go to the supplied
artifact directory. Stop the preview server when finished.

- `?mode=hero&width=248&theme=light`: normal pane.
- `?mode=twelve&width=248`: 12 rows, measured at 700px including header/footer.
- `?mode=states&width=200`: every required state.
- `?mode=pending`: collapsed and expandable approval row.
- `?mode=approval`: transcript directive card.
- `?mode=arbitrary-host`: unsampled cron draft with full URL disclosure.
- Widths below 176 automatically switch to rings-only; `width=56` exercises the rail.

Fixtures are Engine.status-generated: Discord rows and pending GitHub previews
replay recorded data; other GitHub/Hermes/edge-state inputs are explicitly synthetic.
`?mode=sampling` exercises the cold→measured card on the next 2.5s status tick.
The harness labels this provenance and says it is not live Hermes.
The raster icons are existing recorded fixtures, never renderer-fetched URLs.
Only the old-backend regression fixture intentionally has API version 0.3.0.

## Behavioral coverage

The browser suite checks layout and state coverage at 56/160/200/248/320px,
fixed-height scrolling, ring concentricity, real raster decoding, keyboard
navigation, reduced motion, WCAG text/arc contrast in both fixture themes,
pending/approve/reject flows with GET readback, failed and unconfirmed decisions,
expiry and profile switches, unsent composer actions, share/copy, pause/remove,
imports, stable sorting while hovered, cache-only status chip, hidden-pane
collection pause, compact-to-full workspace details, and disposal cleanup.
Requests outside the local harness origin are recorded **and blocked**; the
suite requires zero attempts, not merely zero successful remote responses.

## Display block lab (WP8)

- `?mode=blocks`: multi-feed store rings/shared bars/stat, GPU independent bars
  and gap-aware spark, score/bar, plus an unchanged `display:null` legacy pulse.
- `?mode=block-states`: six block types × eight pulse scenarios; only fields
  supported by each normative row shape are used (no invented spark scales).
- `?mode=styles`: validated CSS variables, independent pulse themes, motion:none.
- `?mode=live-blocks`: synthetic status values and feed timestamps tick every 1.6s.
- `&css`: enable an optional mock local stylesheet; absence exercises silent 404.
- `&baseline`: mount the frozen main `3b04572` renderer for legacy comparison.

These rows are **hand-authored synthetic** fixtures in `display-fixtures.js`,
not the engine-generated JSON fixtures above. The harness caption explicitly
marks that distinction. `test-blocks.mjs` exercises the row/state matrix,
CSS sanitization and ownership cleanup, approval immunity, 176/248/320px layout,
light/dark contrast, motion, held-element updates and exact legacy DOM/PNG bytes.
The pixel comparison isolates/aligns the legacy row on the same opaque pixel grid,
because preceding new-display rows intentionally have different heights.

```bash
node scripts/test-blocks.mjs $HERMES_SOURCE $ARTIFACTS/pulse-rings/wp8-render
```

## Read-only live snapshot replay

```bash
STATUS=$ARTIFACTS/pulse-rings/live-check/live-ui-after/live-status.json \
PULSE_PREVIEW_ORIGIN=http://127.0.0.1:5611 \
node preview/render-live-status.mjs $HERMES_SOURCE $ARTIFACTS/pulse-rings/live-check/live-ui-after/render
```

Supply an existing snapshot, never the live database. The renderer hydrates exact
icon keys from the snapshot's copied `snapshot-data/icons/*.image` cache; missing
icons remain explicit in `report.json`. This matters because the generic preview
`/icons/` mock deliberately returns the Nous fixture for every key, which is not
proof of real server artwork. Replay captures 320/480px dark/light panes and every
expanded row, with collapsed text, accessible names, and image decode evidence.
It blocks non-preview-origin network requests and performs no collection.

`test-live-polish.mjs` separately uses deterministic synthetic data to cover score
hero measurements/direction/zero/warming, integer scores, shared-error deduplication,
accessible error descriptions, learning bars, trend captions, baseline wrapping,
and equal collapsed-row heights. Existing frozen legacy comparisons normalize
only the deliberately changed wording before exact DOM/PNG comparison. Collapsed
rows retain the original 52px trigger rhythm (53px including the row divider);
comparisons still preserve measured values and original actions.

## Integration handoff

Read `desktop/CONTRACT.md` before wiring a backend. In particular, status must
include `pulses[]` and the specified `drafts[]` members. The plan did not define a
GET draft route, so cards resolve ids through the shared `/status` query. These
fixture checks are not proof of live Hermes create→approve integration.
