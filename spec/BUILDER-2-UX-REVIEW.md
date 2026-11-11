# Builder 2 UX verification (WP13)

## Shipped renderer changes

- New pulse starts with purpose: Describe it / unsent Ask Hermes, nine template cards, a short source form, consented lookup/test, and selected metrics. Source and data setup share step 1, as required by the four-step contract.
- Pick a look and Add a piece render the actual `Block` component with the real Python sample engine. Gallery-only gauge geometry stacks the real ring and its legend so labels remain readable in small thumbnails.
- Make it yours has title/icon, accent swatches/custom accent, density, motion, corner style, click-to-edit preview pieces, plain-language inspector tabs, and visual piece management. Mouse, drag/drop, and Alt+Arrow keys reorder pieces. Limits remain enforced.
- Edit / Open in builder enter section 3. Advanced persists through `ctx.storage` and retains the source inspector, MCP tool/argument/test/pointer controls, all block/style controls, and YAML/JSON round-trip. Editor also retains unsent Ask Hermes.
- Review lists source targets, hosts, human cadence, approximate request rate, sign-in, and What happens next. Add to Pulses creates and reads back a draft; the existing `ApprovalCard` remains the only approval UI. Renderer creation never approves. Existing collection, grants, and background consent behavior are unchanged.
- Preview tools are a separate SDK Popover, labelled preview-only / not saved. Sample remains watermarked; cached/measured provenance stays separate from simulated state. Captions humanize day durations; repeated per-piece labels are suppressed.

## Real-host styling correction

The earlier lab was misleading: bare SDK stand-ins plus auto-height and unqualified footer rules made it differ from Hermes. The preview now imports the actual Button, Input, Select, Switch, SegmentedControl, and Popover implementations from the supplied Hermes source checkout. Vite compiles the actual Desktop global stylesheet with the source's Tailwind plugin. Only runtime/data services remain mocked. No host source or dependencies were modified or installed.

The plugin owns root-scoped field borders/fills, selected states, solid button variants, and focus rings using theme variables. These are not supplied by page CSS. Generic builder styling explicitly excludes the locked approval subtree. Portal styling uses plugin-owned classes, not core DOM selectors.

The fixture frame now has a constrained host-like height; the harness no longer changes `.pr-shell` sizing or styles plugin footers. The builder keeps its header/progress and action bar visible around a scrolling workspace. At <=480px, a compact labelled preview is pinned above the controls; above that it stays beside them, including 670px. Tests exercise actual scroll, not only the `position: sticky` property.

`test-builder2.mjs` strips harness content CSS while keeping theme tokens and the real host stylesheet. It verifies real SDK markup, solid one-pixel input/select/action borders, nontransparent fills, selected editor-section styling, >=32px control targets, and focus rings. This verifies source-based host styling parity, NOT an installation or screenshot in the user's running Hermes. Live Hermes was not changed or restarted.

## Verification

Preview command:

```bash
node scripts/preview-server.mjs $HERMES_SOURCE 5351
```

Each suite was run with:

```bash
PULSE_PREVIEW_ORIGIN=http://127.0.0.1:5351 node scripts/test-<suite>.mjs $HERMES_SOURCE $ARTIFACTS/pulse-rings/wp13-builder-ux/<suite>
```

For `builder2`, the output directory is `.../after`.

| Suite | Passing checks |
|---|---:|
| widget | 148 |
| blocks | 241 |
| builder | 93 |
| builder2 | 195 |
| polish | 266 |
| background | 17 |
| security-ui | 602 |
| ui-nits | 274 |
| **Total** | **1836** |

All result files report no runtime errors or remote requests; security-ui and UI-nits have no failures. `node --check desktop/plugin.js` and `git diff --check` also pass. Safety assertions remain: explicit one-call consent and consumption, read-only MCP gating, late-result invalidation, sample watermark, provenance, locked approval, hostile-CSS pixel isolation/hit targets, and no implicit approval. Legacy tab-specific presentation assertions were ported to the new sections/tools; test totals are not expected to match obsolete tab counts.

One security fixture correction is documented in its test: a ceil-rounded screenshot included one pixel of an adjacent row's antialiased outline. Differences were confined to the last row (8–10 pixels), not card content. Flooring the bottom keeps the crop inside the approval card; all content, button, hit-target, and raw-paint tests still run.

## Screenshot evidence and review

Root: `$ARTIFACTS/pulse-rings/wp13-builder-ux/`

- `before/step-{1..4}-{320,480,900,1280}-{light,dark}.png`: 32 baseline captures, recaptured from `57434d7` **after** wiring the real SDK/host CSS and removing harness content styling. `?builder-baseline=1` loads that fixed Git revision. The old builder had no guided steps, so the four step labels deliberately repeat the old inspector view rather than inventing old guided screens. The supplied live-host screenshot was also inspected as the authoritative styling-failure baseline; source parity is not a claim that every installed-host detail matches.
- `after/step-{1..4}-{320,480,900,1280}-{light,dark}.png`: all 32 required final captures, plus eight at 670px.
- `after/templates-{320,480,670,900,1280}-{light,dark}.png`: template-gallery captures.
- `after/guided-{discord,weather,any}.png`: draft handoff screens for the three required template journeys.
- `verification-summary.json`, suite result JSONs, and `*.log`: actual counts and execution evidence.

Image-tool reviews covered narrow forms/gallery/review, intermediate two-column authoring, wide light authoring, dark layout gallery, and inline approval. Iteration fixed host-style mismatch, invisible controls, missing fixed actions, duplicate compact labels, gauge-thumbnail wrapping, and clipped lab footer. Lower form/gallery content intentionally scrolls; actual scroll tests verify preview/action persistence and accessibility of later controls.

## Integration boundaries

- Four Builder 2 routes are clearly labelled lab mocks in `preview/builder2-mock.js`; definitions still go through real layout validation and sample computation. No Python files changed.
- JSON one-shot testing uses a clearly labelled additional MOCK `/builder/json-test-call`. That endpoint is NOT present in this worktree's Python API. The renderer explains backend support is required and never falls back to renderer fetch. Backend integration must implement that consented route or agree an equivalent existing endpoint before claiming live Any website JSON click-to-bind readiness.
- Merge with the sibling API branch and rerun backend plus browser suites against its real response shapes. Mock passing results do not prove API integration or real lookup/connector execution.
- No live install, reload, push, gateway restart, or real network/tool test was performed. Independent integration/security review remains the parent's responsibility; this branch has implementation self-review and browser evidence.
