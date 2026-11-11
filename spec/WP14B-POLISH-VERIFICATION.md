# WP14b — focused Builder polish verification

## Candidate and scope

- Worktree: `../pulse-rings-wp14b-polish`; branch `wp14b-polish`, base `eec00d9`.
- Product commits: `b7680a1`, `95963ed`, `05cea24`.
- Real-host source revision: `29a61cb7ab509cda0c376bf3860edb87210b0755`.
- Existing preview: `http://127.0.0.1:5421`. No preview server started, restarted or killed.
- Only builder product code changed, except the explicitly permitted shared ApprovalCard wording `Normal means` → `What counts as normal:`. No pulse list/pane changes, core restyling, import changes, live installation, push, or live approval action.

## Requested polish

| Item | Result |
|---|---|
| Empty Source preview | One-line placeholder, without an empty preview card. Narrow Source places the choices/details before the preview. |
| Source selection | Whole-card SDK buttons, visible radio-style indicator, pressed semantics, strong selected frame, hover and keyboard focus. Clicking an already-selected card preserves its fields. |
| Details placement | `Details · <source>` follows the selected card and Change template action. Footer explicitly locates Details. Unsent-chat assistance remains available below the form. |
| Footer clearance and disabled navigation | ResizeObserver measures the actual footer and sets equal bottom scroll padding. Source/layout cards scroll completely above it. Disabled text is opaque and tested at ≥4.5:1; Source hides Back. |
| Design fidelity | Gallery and large preview use the same fixed sample seed and engine inputs. All selected layouts match on block types, complete text/value content and accessible labels, including after refetch. No old-layout placeholder data during a layout transition. Narrow compact mode shows the matching hero; Expand reveals the full selected layout. |
| Deltas | Zero and rounded signed-zero deltas read `No change vs usual` (or previous). Other deltas include comparison context and units/metric context; an online-person delta can be fractional because it is compared with a learned median. This formatter is builder-owned; live pulse rendering is untouched. |
| Design controls | Separate Selected radio state and Recommended badge; Preview settings label; icon+label Expand/Collapse controls; fewer outer preview boxes; space below the gallery. |
| Review summary | Builder-owned Approving will / It will not paragraphs above the shared card. Rendered hosts, cadence, rate and service derive only from the frozen draft disclosure; a readback with deliberately different cadence/rate proves editor state is not used. Unknown/incomplete disclosures and MCP/local-only sources omit this no-sign-in network reassurance rather than guessing. |
| 320px approval reachability | Persistent builder-owned Jump to Approve scrolls and focuses the original decision control, never submits a decision. Approve and Reject are center hit-tested at every width/theme and in a 320px short pane. Technical disclosures remain expanded. |
| Locked ApprovalCard | Same component and original controls/disclosures. Only the expressly allowed `What counts as normal:` wording changed, with a regression assertion. Security UI suite retains all 602 checks. |

## Passing evidence

Artifact root: `$ARTIFACTS/pulse-rings/wp14b-polish/`.

| Suite | Passing checks | Authoritative log |
|---|---:|---|
| widget | 148 | `widget-isolated.log` |
| blocks | 241 | `verified/blocks-final.log` |
| builder | 93 | `builder-isolated.log` |
| builder2 | 75 | `verified/builder2-final.log` |
| polish | 266 | `verified/polish-final.log` |
| background | 17 | `verified/background-final.log` |
| security-ui | 602 | `verified/security-ui-final.log` |
| ui-nits | 274 | `verified/ui-nits-final.log` |
| builder-rework | 1 | `verified/builder-rework-final.log` |
| rework-journeys | 174 | `verified/rework-journeys-final.log` |
| rework-integrity | 45 | `verified/rework-integrity-final.log` |
| **Existing browser total** | **1936** | `browser-final-summary.json` |
| **New focused polish** | **206** | `focused.log`, `focused-polish-results.json` |
| **All browser checks** | **2142** | Programmatically summed from actual success logs |

All listed suite processes exited 0. Focused suite reports zero console errors and zero external requests. The original focused test failed on the oversized empty preview before implementation. Additional edge/contrast/transition assertions were added during iteration, not all test-first.

**Python: 1394 passed in 208.87s**, exit 0; no failed/skipped tests reported. `backend-isolated.log` includes the real MCP end-to-end and whole-shipped-tree admission scanner tests. No standalone clean-clone admission run was performed for this polish pass.

**Real API replay: 8 templates passed**, zero network connection attempts and zero activated pulses. Evidence: `final-gate/frontend-real-api-results.json`. Actual converter, FastAPI/Store draft creation, exact GET readback and pending state were exercised, not fabricated responses.

### Commands

From this worktree, Git Bash:

```bash
PULSE_PREVIEW_ORIGIN=http://127.0.0.1:5421 PULSE_DEMO_DIR=$ARTIFACTS/pulse-rings/demo node scripts/verify-builder-rework.mjs $HERMES_SOURCE $ARTIFACTS/pulse-rings/wp14b-polish/verified

# Isolated final reruns, after other browser/Python workers completed:
PULSE_PREVIEW_ORIGIN=http://127.0.0.1:5421 node scripts/test-widget.mjs $HERMES_SOURCE $ARTIFACTS/pulse-rings/wp14b-polish/isolated/widget
PULSE_PREVIEW_ORIGIN=http://127.0.0.1:5421 node scripts/test-builder.mjs $HERMES_SOURCE $ARTIFACTS/pulse-rings/wp14b-polish/isolated/builder

PULSE_PREVIEW_ORIGIN=http://127.0.0.1:5421 node scripts/test-builder-focused-polish.mjs $HERMES_SOURCE $ARTIFACTS/pulse-rings/wp14b-polish
uv run --isolated --no-project --python 3.11 --with pillow python scripts/review-builder-polish.py $ARTIFACTS/pulse-rings/wp14b-polish

uv run --isolated --no-project --python 3.11 --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'jsonschema>=4,<5' --with 'ruamel.yaml>=0.18,<0.19' python scripts/verify-builder-api-payloads.py $ARTIFACTS/pulse-rings/wp14b-polish/final-gate/frontend-payloads.json

HERMES_SOURCE=$HERMES_SOURCE uv run --isolated --no-project --python 3.11 --with 'pytest>=8,<9' --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'jsonschema>=4,<5' --with 'ruamel.yaml>=0.18,<0.19' --with mcp --with rich --with pyyaml --with python-dotenv --with platformdirs --with requests --with tenacity python -m pytest tests -q -p no:cacheprovider --basetemp "$TMPDIR/wp14b-pt-isolated" --durations=10
```

### Earlier failures, not hidden

- `gate/` was interrupted by the tool's foreground timeout. A builder failure also caught a temporary regression where unsent-chat assistance was unavailable after source selection; that capability was restored below Details.
- Earlier runs overlapping source hot reload or several simultaneous browser/Python workers had missing DOM/call-array, 500ms pane-resume, theme-contrast timing and background-thread teardown failures. The concurrent Python run ended 1393 passed / 1 failed at `test_context_capture_unload_and_singleton`.
- After source changes stopped and other workers completed, unchanged full widget (148), builder (93) and Python (1394) suites passed in isolation. No assertions were removed, softened or skipped. The other nine browser suites passed in `verified/`. This is a complete set of passing individual suites, not a claim that the concurrent aggregate process itself exited green.
- The API replay emitted a Starlette/httpx deprecation warning; all eight cases passed.

## Screenshots and image-tool review

56 verified exact-width product PNGs, 7 labelled review matrices; original surface captures retained at the artifact root. Crop removes only the harness's 1px border, never alters product pixels.

```text
product/{source,source-selected,design,design-expanded,review,approval,approval-decisions}-{320,480,670,1280}-{light,dark}.png
review-sheet-{source,source-selected,design,design-expanded,review,approval,approval-decisions}.png
screenshot-manifest.json
```

All seven width/theme matrices were reviewed with the image tool. Native-size 320px source, source-selected, Design and approval and 670px Design were also inspected. Iteration moved Source's preview below the form on narrow panes, made delta context explicit, replaced the expand text glyph with an inline SVG icon, and removed screenshot-only keyboard focus from the unselected Source capture so focus is not confused with selection.

Final image review found no visible release blockers. Normal scroll-boundary cutoffs were distinguished from inaccessible overlap; automated footer clearance and after-jump hit tests prove the lower cards/actions are reachable. The 320px pre-draft Review footer reassurance still wraps narrowly; it remains readable and the primary action is reachable.

## Runtime and remaining limits

No server PIDs started. Bounded background verification wrappers started: 2568, 26136, 24380, 19948; all completed and were read back. No process was killed or handed off. Existing port 5421 is unchanged.

No live external connector/account, installed Desktop run or real human approval was exercised. The harness uses actual host SDK and CSS with offline data/REST fixtures; real API payload acceptance is checked separately. No fresh independent code reviewer was available; this pass has self-review, image-tool review and automated security/regression gates, not an independent security sign-off.
