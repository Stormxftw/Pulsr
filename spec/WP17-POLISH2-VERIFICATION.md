# WP17-polish2 verification

Implemented on `wp17-polish2` from `6d53113`. Renderer-only polish; GitHub collectors/kinds and stat value/duration logic are unchanged. Stat changes are limited to suppressing its duplicated caption.

## Acceptance

1. **Duplicate captions:** hero ring status captions, block label/caption collisions, item label/value collisions, sibling-block captions, unknown reasons, capsule ratio/title and collapsed tooltip text are deduplicated. Independently measured equal numeric values remain visible. The focused suite first failed on the exact `Hermes at work` / repeated `Learning baseline` case, then passed after the fix.
2. **Sessions:** Done renders as `Finished 3m ago`; finished rows, tooltips and accessible names omit the duplicate Last activity age. Session metadata is 12px or larger and passes measured 4.5:1 contrast in light/dark. Static Working play, Idle filled dot and Done check remain distinguishable without animation.
3. **Done tick:** complete-path fade/scale over 650ms, beginning at 88% scale and 35% opacity; no dash draw-in. Actual zero-offset PNG visually reviewed as a recognizable complete check.
4. **Discoverability:** a calm dismissible line in normal panes with at least four approved pulses and no groups offers Group pulses and Show Hermes sessions. It starts arranging or opens the existing settings disclosure without enabling collection. Dismissal persists across remount and is profile-local. Both menu entries remain available. Compact ring-only panes retain their existing minimal chrome.
5. **Collapsed groups:** group/subgroup circles share identical four-column widths and x positions; only subgroup headers indent. Counts include subgroup membership, chevrons match effective collapse state, headers/counts are at least 12px.

## Automated evidence

All browser suites ran sequentially against `http://127.0.0.1:5471` with the actual Hermes SDK components and stylesheet from `$HERMES_SOURCE`. Groups and integrity had targeted successful reruns after the harness corrections below. Report counts were read and summed programmatically, not inferred from PASS-line counts.

| Suite | Passing checks |
|---|---:|
| widget | 148 |
| blocks | 241 |
| builder | 93 |
| builder2 | 75 |
| polish | 266 |
| background | 17 |
| security-ui | 602 |
| ui-nits | 274 |
| groups | 99 |
| sessions | 69 |
| builder-rework | 1 |
| rework-journeys | 174 |
| rework-integrity | 45 |
| builder-focused-polish | 206 |
| **Existing suites total** | **2310** |
| wp17-polish2 focused regressions | 69 |
| **Browser total** | **2379** |

The existing-suite result files report empty errors, remote requests and failures where those fields exist. JavaScript syntax and `git diff --check` pass.

Python command (the requested isolated environment and dependency bounds):

```bash
HERMES_SOURCE=$HERMES_SOURCE uv run --isolated --no-project --python 3.11 --with 'pytest>=8,<9' --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'jsonschema>=4,<5' --with 'ruamel.yaml>=0.18,<0.19' python -m pytest tests -q -p no:cacheprovider --basetemp "$TMPDIR/wp17b-pt"
```

Result: **1477 passed, 1 skipped, 1 warning**. Skip: `tests/test_mcp_integration.py:18`, requiring the MCP SDK in that test interpreter. Warning: FastAPI/Starlette's httpx deprecation. No dependency was installed to remove the skip.

## Visual evidence

Root: `$ARTIFACTS/pulse-rings/wp17-polish2/`

- `regressions/`: 16 requested full screenshots: `hint`, `groups-collapsed`, `sessions-expanded`, `sessions-collapsed`, each at 320/670px and light/dark. Exact-pane counterparts use the `-pane.png` suffix.
- `regressions/review-{320,670}-{dark,light}.png`: four native-size contact sheets covering all 16 scenarios. Image-reviewed, then re-reviewed after correcting the hollow/faint Idle-dot CSS specificity problem and replacing guessed crops with exact DOM screenshots. Final review found no concrete clipping/alignment defects.
- `motion/session-motion.webm`: real-time recording encoded from **347 actual CDP frames**, sorted by measured presentation time; no remote requests.
- `motion/done-frame-strip.png`: actual renderer PNGs at controlled CSS timeline offsets 0, 40, 80, 140, 220, 350, 500 and 650ms. Final image review confirms a complete recognizable check from zero offset, with no stray dash or clipping.
- `motion/motion-capture.json`: frame timestamps, phases, observed DOM completion time and controlled PNG offsets. Controlled screenshots are explicitly distinguished from real-time presentation frames.
- `<suite>.log` and per-suite JSON results: complete browser evidence. `groups-trace.log` preserves the geometry diagnosis before correcting the drag helper.

## Harness corrections and limits

- Row-density assertions subtract only the measured optional discovery line, preserving the original 53px-row and approximately 700px intrinsic-layout bounds.
- Old group test drops used coordinates 3px from a target edge. The trace showed those destinations inside the pane's autoscroll zones (for example, the ungrouped target ended near 1008px in a pane ending at 1021.5px). Autoscroll moved the target before mouse-up. The corrected helper chooses a visible point in the intended target half, or drives real edge autoscroll and remeasures. All original order/membership assertions remain.
- The shared demo folder now has a sibling work package's fifth demo. Integrity names its four frozen golden files explicitly and checks their existence instead of rejecting unrelated additions. No sibling demo or GitHub source was modified.
- These are controlled synthetic/recorded fixture checks with real SDK styling, not a live Hermes installation. No push, install, application restart or process kill was performed. Existing preview port 5471 was reused (PID 27236); no new server was started.
