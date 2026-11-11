# Live renderer polish verification

Scope: live-ui; Refs #60, #62, #63, #64, #65, #66. No engine edits, JSON contract changes, install, push, or gateway restart.

## Outcomes

- Score heroes use the first hero component's measured value/baseline/delta, not an unrelated legacy capsule or sibling stat value. Comparison direction is visible; score text is integer-rounded. Warming flags win over zero-baseline comparisons.
- Score rows share the title-line score placement and original 52px trigger rhythm (53px including divider). The idle feed dot is hidden; a transient update marker has a Feed updated accessible label and tooltip without adding a line.
- Source error reason/action appears once. The trigger references that reason with aria-describedby; duplicate block reasons become Not measured, while independent failures remain available.
- Error text wraps with a 44×28px minimum Fix target. Learning bars show Baseline not ready plus known sample count, without a range or striped rail.
- Legacy trend captions read First/Latest. Discord usual medians are integer-rounded and labelled Usual (median), with the duration kept together.

## Live evidence

Artifact root: `$ARTIFACTS/pulse-rings/live-check/`.

- Before: `live-ui-before/render/report.json`.
- Same-input after: `live-ui-after-same/render/report.json`.
- Final fresh-snapshot render: `live-ui-final-render/report.json`.
- Same-input collapsed catalog row: `Change 100/100` → `Change 100/100 185 PRs · ↑ 3.5× usual`.
- Fresh snapshot: `182 PRs · ↑ 3.4× usual`; repo: `108 commits · ↑ new`.
- Discord score: `Change 41.8/100` → `Change 42/100`.
- Error accessible name: repeated repository-moved reason → `Pulsr repo: Not measured; source error` (description references the single reason).
- Expanded TypeSafe baseline: `Normal: Median · 17,777.5 · 48 recorded samples over 23h 51m` → `Usual (median) 17,778 · 48 samples over 23h 51m`.
- Notification learning bar: `0–0 Learning baseline` → `Baseline not ready · 527 samples` in the fresh snapshot.

Reviewed dark/light 320/480 panes and all eight expanded rows. Final compact-pane review found no blocking visual defects. New snapshot readings naturally differ from the earlier same-input replay.

### Discord icon provenance

The raw status JSON has distinct icon_url values but no icon_data. The generic preview /icons/ mock returns the Nous fixture for every key, so its apparent repeated icon is not a product defect. The new `preview/render-live-status.mjs` hydrates exact raster bytes from the snapshot's copied icon cache. All three Discord images decoded: Hugging Face mascot, Nous wordmark, TypeSafe pink geometric logo; none is a generic letter avatar. No production icon behavior changed.

## Tests

- Python: **1,774 passed, 1 skipped**, one upstream FastAPI/Starlette deprecation warning. The skip requires an MCP SDK unavailable in the isolated test Python.
- All **24** scripts/test-*.mjs suites except capsule passed after focused reruns: **3,203 reported checks plus 2 builder smoke assertions**. New live-polish coverage: **85 checks**; blocks: 241; widget: 148; security: 602.
- Tests first reproduced the missing measurement/error/learning/caption defects. Existing tests were updated only where they required the old score decimals/captions; frozen legacy DOM and pixel comparisons remain exact after explicit intended wording normalization.
- Broad-run navigation/locator failures during Vite hot reload were rerun successfully with code held stable. Repository tooltip coverage caught loss of the distinct computing-stats reason; that reason is preserved outside the shared source-error case.
- Syntax checks and git diff --check passed.

Logs/results live in `live-ui-suites/`, with successful reruns under `live-ui-rerun/`, `live-ui-rerun3/`, `live-ui-final/`, and `live-ui-compact-final/`. No screenshots or real status data are committed.

## Remaining integration work

Engine score/baseline changes are owned by the sibling agent. The renamed repository remains an actual source error until a human approves a replacement. Installed-plugin verification belongs to the coordinator; this branch was not installed or pushed.
