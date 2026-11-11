# Builder 2 rework brief (WP14) — supersedes the 4-step parts of spec/BUILDER-2.md

Decided by the user after an independent review ($ARTIFACTS/pulse-rings/review-sol-builder/REVIEW.md).
Where this file and BUILDER-2.md disagree, THIS FILE WINS. Read REVIEW.md in full; its findings are requirements
unless listed under "Not adopted".

## 0. Host fidelity first (release blocker)
- Main now has `fix-host-tokens`: the plugin no longer reads the nonexistent `--ui-bg` token; it uses
  `--ui-bg-editor` / `--ui-bg-elevated`. `tests/test_host_tokens.py` fails if the plugin reads a token the host
  lacks or the harness invents one. Merge it first and keep it green. Never re-add `--ui-bg` anywhere,
  including the Builder 2 harness (`preview/builder2-sdk.js`, `preview/index.html`, theme fixtures).
- The visual harness must render with Hermes's REAL SDK components and REAL global stylesheet
  ($HERMES_SOURCE/apps/desktop/src). Mock data/REST only, never appearance. Pin and report the host
  revision. Add computed-style assertions run WITHOUT any harness content CSS: inputs/selects have visible
  1px borders and an input background; the active step is visibly distinct; secondary buttons have no
  dashed or 3px borders; focus-visible is visible on every plugin-owned control.
- The plugin owns layout, galleries, selection frames, preview bounds and its own focus treatment. Let SDK
  components own their chrome (explicit `variant`s). Remove broad `.pr-builder button,input,select` resets
  that fight the SDK. Plugin portal content gets explicit `pr-*` classes; no global Radix selectors.

## 1. Flow: Source → Design → Review (3 steps)
- **Source — "What would you like to watch?"** Featured templates: Hermes activity, Discord server,
  GitHub repo, GitHub PRs/issues, Weather & air, Game players (Steam). "More sources": Any website JSON,
  MCP tool, Start from YAML. One necessary identifier per template; metric checkboxes with sensible defaults;
  cadence and where it connects shown here. "Draft a request in chat" (the old Ask Hermes) is secondary,
  and its label says it only inserts an unsent message.
- **Design — "Choose how it looks."** The recommended layout is PRESELECTED; show up to 3 alternatives with a
  one-line purpose. The user can go straight to Review. Title, icon and accent are inline and optional.
  "Customize pieces" (a disclosure) reveals the selected-piece editor (Shows / Range / Warnings / Style) INLINE,
  never as a popover at narrow widths, plus add, remove and reorder with a labelled list and a keyboard path.
  "Edit YAML" is another local disclosure with a round trip.
- **Review — "Review permissions."** The primary button text is **Review permissions**: POST /drafts, read it back,
  then render the SAME shared locked ApprovalCard and focus it. Remove the creation button once the card shows.
  After approval, show the accurate state (Added to Pulses · waiting for MCP grant / first check / collecting
  while the pane is open / background on) and **Back to Pulses**. Copy: "No recurring checks start before you
  approve. Lookups and test calls only happen when you click them." Never use "Add to Pulses" before approval,
  and never "Nothing is checked until you approve".
- **Edit pulse / Edit proposal** open at Design, with sections rather than a mandatory wizard. Show the
  replacement notice ("Your current pulse keeps running until you approve the change").
- **Remove the global persisted Advanced switch.** Use the local disclosures instead (More source options,
  Customize pieces, Edit YAML). Every existing capability (3 feeds, all block types, scales, zones, styles,
  theme, icons) stays reachable through them.
- **Back to Pulses** replaces Close. Track dirty state, and confirm with Keep editing / Discard changes.

## 2. Data integrity
- Changing the source, choosing a layout and making cosmetic edits are distinct operations. Preserve unrelated
  fields (link, alert, `x-*`, theme, custom pieces) by construction. Back→Next must not reset anything.
  Regenerate layouts only when source or metric inputs changed. Confirm genuinely destructive changes.
- Once a draft exists, the review shows that frozen snapshot; "Change draft" returns to editing and needs a new
  readback before Approve. Never show an old approval card under an edited preview.

## 3. Contract reconciliation with the real API (wp13-builder-api, a902286)
- Use the REAL Python routes in the harness bridge for /builder/templates, /builder/from-template and
  /builder/layouts (scripts/preview-server.mjs currently only allows the old pure routes; extend it).
  The UX-side mocks for these three must go.
- **Delete the website-JSON "Test" button and the `/builder/json-test-call` mock.** No such endpoint exists or
  will be added. The JSON template asks for the URL plus a named number pointer (with a short example); the
  value is measured after approval. The MCP test call stays (the existing consented read-only path).
- Project lookup results into accepted template fields only (weather: latitude/longitude/city label/units;
  steam: appid/name). Keep transient display/search fields out of submitted values. Parse structured MCP
  args/metrics explicitly as JSON, with errors.
- Add a front-to-back test per featured template: the frontend-produced payload goes to the real route and
  yields a valid draft definition (offline transports).

## 4. Visual quality
- Body ≥13px, secondary ≥12px, AA contrast with REAL host tokens in both themes; clearly visible field borders;
  one dominant primary action per step; spacing instead of nested boxes; no duplicated labels; human
  durations. Provenance pill "Sample · not live" is always visible (not tooltip-only). Preview options
  (Preview data, Simulate condition, Appearance, Compact row) live in one popover marked "preview only".
- Widths: ~320 and ~480 are one column with a compact preview (main piece, plus "Expand preview") above the
  controls. At ~670+, two columns only when both stay usable (a container query on the pane, not the viewport).
  Respect short heights. Use a single main scroll surface.
- Remove harness-only lab text from any screenshot presented as the product.

## 5. Not adopted from the review
- Keep the consented city lookup (geocoding-api.open-meteo.com) and Steam search if their tests are solid; the
  offline appid/URL and coordinates paths remain as fallbacks.

## 6. Gates
All existing suites (Python, widget, blocks, builder, builder2, polish, background, security-ui, ui-nits), the
real admission validator, no remote requests, zero console errors. Screenshots at 320/480/670/1280 in light
and dark for each step plus the approval state, produced with the real-host-styled harness and self-reviewed.
No push, no live install, no restarts (the parent does the live install with the user).
