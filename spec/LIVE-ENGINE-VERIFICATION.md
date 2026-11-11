# Live engine polish — Refs #58 #59 #60 #61 #66 #67 #68

Scope: `live-engine`, Python/spec/tests only. No installed plugin, live database,
approvals, live network polling, pushes or gateway restarts were performed. Status snapshots
copy the live database read-only, then compute with this worktree's code.

## Observed before / after

Evidence root: `$ARTIFACTS/pulse-rings/live-check/`.
Before: supplied `render/report.json` and `render/row-discord-notifications.png`;
also captured `engine-before/live-status.json` before changing code.
After: `engine-after/live-status.json` and `engine-after/render/report.json`.
The snapshots were taken at different times: time-since-notification and some
live counts naturally advanced between captures.

| Issue | Before | Engine-only result |
|---|---|---|
| #58 | Notifications `Change 100/100`, zero waiting vs usual one | `Change 20/100`; one-count noise has a minimum five-count effective denominator |
| #58 | Pulse repo `Change 100/100`, activity vs zero usual | `Learning baseline`; measured value/usual/signed delta retained, reason `No positive usual yet` |
| #58 | Race `182` vs source usual `53.5` | Still clearly high: `Change 100/100`; default-sensitivity full drops max out at 50 rather than 100 |
| #59 | Race `182 +17 vs usual` | `182 +128.5 vs usual`, using the source average; `previous` still compares against the previous local observation |
| #60 | `Normal: Median · 17,777.5` | Numeric baseline unchanged; component `baseline_text` is `17,778`. Renderer must consume it and replace its own static `Normal: Median` wording |
| #61 | `Open prs unknown` | `Open PRs unknown`, including the default display label |
| #66 | `0–0 · Learning baseline` | Learning item min/max/range_text null; `Baseline not ready`, no zero-width range in the live render |
| #67 | `Last notification 624.2 min` | Final duration `value_text`, e.g. `10h 37m ago` in the newer snapshot; final `range_text: 0m–16h 40m` and duration auto caption. Old renderer still formats its separate range in raw minutes |
| #68 | Full technical disclosure inline | Optional `notifications.summary` plus full unchanged privacy/window limitations in `notifications.details`, for UI disclosure integration |

## Optional additive renderer fields

- Ring component: `baseline_text: string|null`, `warming: bool`.
- Duration/learning item: `range_text: string|null`. Learning bounds are null;
  current numeric value, units, fill and evidence sample count retain their meaning.
- Any notification-source pulse, including explicit multi-feed status and previews:
  `notifications: {summary, details}`.
- Renderers must tolerate missing optional fields from older backends and use
  existing fallbacks. No definition/schema or stored-history format change.
- The engine does not change the source's zero average into an unknown value;
  it marks the proportional comparison as warming. Unknown siblings cannot make
  a zero-usual comparison look like measured calm.

## Regression test rationale

The initial nine focused cases failed on the reported behaviors before changes.
A subsequent mixed zero-usual/unknown-sibling case also failed before its fix.
Existing assertions were updated only where they encoded the intentionally changed
score formula, stat baseline, learning-bound exposure or acronym wording. Frozen
v0.3 source readings/oracle and renderer fixtures remain unchanged. Their raw
measurements still compare, with an independent reference for the corrected score;
fixture contribution comparisons tolerate only 12-decimal numerical rounding.

Screenshots reviewed: baseline notification row; engine-after expanded race,
notification and TypeSafe rows; light 320px and dark 480px live panes. Engine-only
rendering produced no page errors. The race delta fits without clipping. The wider
pane fits; the TypeSafe median duration still wraps in the unmodified renderer.
Remaining renderer-only work is explicitly called out above; no claim is made
that the installed UI changed.

## Verification results

- Final full Python suite: **1,784 passed, 1 skipped**, one dependency deprecation
  warning, 212.84 seconds. Log: `engine-after/python-release-tests.log`.
  The skip requires the MCP SDK in the isolated test Python; it is not a pass.
- Focused final engine/display/fixture regressions: **249 passed**.
- Ran **all 23** `scripts/test-*.mjs` suites except capsule. On the full pass,
  21 suites exited zero. JSON had one transient Steam sample-preview assertion;
  an isolated rerun exited zero. Notifications has six assertions of the old
  literal `Learning baseline` at `scripts/test-qa-notifications.mjs:48`; actual
  engine output is the required `Baseline not ready`. The assertion belongs to
  the UI agent's file scope and was not weakened or edited here.
- The old UI ignores the optional `range_text`/`baseline_text` and notification
  disclosure fields until the UI branch is integrated; its existing fallbacks remain.
- Restarted only this agent's preview server after Python changes; final builder2
  and JSON smoke runs both exited zero (`-final` artifact names). Thus 22 of 23
  browser suites pass after reruns; only the obsolete notification wording assertions
  remain for the UI agent.
- `git diff --check` clean. No push, install, live approval, network polling or
  gateway restart.
