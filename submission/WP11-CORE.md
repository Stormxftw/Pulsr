# WP11 core — Review-3 remediation receipt

Scope: branch `wp11-fix-core`, based on `3230ea9`. No changes to
`desktop/plugin.js` or `desktop/CONTRACT.md` (sibling UI ownership). No push,
live plugin installation/restart, live connector call or publication. The catalog
SHA is deliberately still a publication placeholder. This is implementation and
self-review evidence, not independent review or live Desktop acceptance.

## Findings and regressions

| Finding | Fix | Regression evidence |
|---|---|---|
| P1-3 | Explicit two-category ARTWORK SCOPE removes entire matching artwork records by unchanged slug/title/upstream-source text. Literal scanner patterns are read from the Hermes AST when HERMES_SOURCE is set, otherwise from the documented checked-in mirror with source lines. No upstream code execution, name encoding/renaming, ignore file or scanner change. | `test_build_brands.py` tests slug/title/source exclusion, full reasons/notices, changed source-scanner patterns and no-overwrite cap. `test_review3_core.py` always tests the mirror/scope and scans actual brands plus the entire shipped tree with the real scanner when importable. Both real-scanner checks ran here. |
| P2-1 | Persist feed generations; retain only compatible same-name canonical kind/params identities. Source/metric-meaning changes or removed/reused names start unknown/warming/learning. Archived history is excluded from every current/previous/baseline/range query. Old-generation success/error/deferral completions cannot write. Legacy unchanged identities and style/title/cadence edits retain samples/state. Import creates its generation before samples. | Real REST propose/strict approve/cached-status tests reproduce the old endpoint's 30 / 60% contamination and verify reset. URL, kind, MCP server/tool/args/pointer, rename/reuse, unchanged sibling/style/cadence, restart, implicit/explicit main and blocked old in-flight outcomes are covered. Import polls immediately without reopening. Actual baseline-code DB migration is independently exercised in the artifact script. |
| P2-2 | README, PR body, catalog draft, checklist, authoring skill, INTERFACE/PULSE-1/DISPLAY and icon contract now state per-feed preview limits, separately consented MCP inspection, four tools, actual builder/share actions, icon facts/hosts and default-off background collection. Tool description/summary copy agrees. Historical receipts are labeled historical and superseded. | Presubmit derives tool names/count from manifest and artwork count/version/byte size from actual shipped files, checks maintained documents and rejects obsolete preview/MCP claims. Existing registration/host-disclosure tests remain. |

## Artwork result

- Simple Icons **16.36.0**: **3,467 input / 3,465 accepted / 0 invalid paths /
  2 excluded**; final JSON **4,811,947 bytes**, one literal record per line.
- Excluded slug `monero`: `crypto_mining`; excluded slug `ngrok`:
  `tunnel_service`. Every reason is retained in BRANDS-LICENSE.md and the JSON
  build report. The mirror itself remains plainly readable and scanned.
- Source archive and SHA256 plus verbatim upstream CC0/trademark notices remain
  in `pulse_rings/BRANDS-LICENSE.md`. No trademark rights/endorsement granted.
- Rebuild into artifact scratch compared byte-identical for brands and license.
  `.gitattributes` pins generated files to LF so Windows clones preserve the
  published byte count.

## Actual commands and results

Run in `../pulse-rings-wp11-fix-core` (Git Bash).
Artifacts: `$ARTIFACTS/pulse-rings/wp11-fix-core/`.

```sh
HERMES_SOURCE=$HERMES_SOURCE python scripts/build-brands.py $TMPDIR/si/simple-icons-16.36.0.tgz

HERMES_SOURCE=$HERMES_SOURCE uv run --isolated --no-project --python 3.11 --with 'pytest>=8,<9' --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'jsonschema>=4,<5' --with 'ruamel.yaml>=0.18,<0.19' python -m pytest tests -q -p no:cacheprovider --basetemp "$TMPDIR/wp11-core-final-pt"

python $ARTIFACTS/pulse-rings/wp11-fix-core/validate-admission.py

uv run --isolated --no-project --python 3.11 --with 'ruamel.yaml>=0.18,<0.19' python $ARTIFACTS/pulse-rings/wp11-fix-core/verify-migration.py
```

- Test-first source/scanner run: **20 failed, 2 passed** (`red.txt`). The rename
  test's feed-order assertion was corrected to select by name; its new empty
  history/learning assertions already passed before the fix. URL/pointer/kind
  contamination, retained-state loss, stale completions and actual brand scanner
  failures were observed. Docs fact test failed before reconciliation
  (`docs-red.txt`).
- First focused green attempt: 69 passed / 2 failed: mirrored raw regex in a
  Python literal was itself dangerous; unsupported future pulse lacked source.
  The literal mirror is now explicit scanned documentation, retaining its
  caution, and unsupported stored shapes remain supported. Next focused run:
  **71 passed** (`green2.txt`).
- Additional importer/implicit-explicit boundary tests: **2 failed, 1 passed**
  before their fixes (`red-boundary.txt`).
- First broad run: **1 failed, 1,287 passed, 1 skipped** (`pytest-full.txt`). The
  existing corrupt-row regression inserted into an obsolete default generation;
  it now deliberately corrupts the current generation and still requires an
  isolated error row, not a route failure. No production guard was weakened.
- Final broad run: **1,295 passed, 1 skipped, 1 warning**, exit 0, 169.59s
  (`pytest-final.txt`). Skip: real MCP integration needs MCP SDK in the isolated
  test Python; HERMES_SOURCE was supplied. Warning: Starlette/httpx TestClient
  deprecation. Real scanner tests ran and passed. New archive/source-pattern tests
  are supplemental tests-after; source replacement and primary scanner regression
  followed the recorded red/green cycle.
- Migration script, exit 0: creates the database by executing actual `3230ea9`
  Store in a separate process, then opens it with the candidate. Original sample
  payload/definition bytes remain equal; initial history readable; source-changing
  replacement has empty compatible history and one archived sample
  (`migration-result.json`). Preexisting contamination cannot be retrospectively
  attributed by a generation migration; only future replacements are separated.
- Scratch rebuild, exit 0: both generated files byte-identical (`rebuild.json`).
- Final post-documentation focused rerun: **57 passed, 1 warning**, exit 0,
  covering core/scanner, presubmit, artwork builder and importer. `git diff
  --check` also passed.
- Actual admission engine: **exit 0 / ok:true**, all checks pass, security scan
  **caution**, not dangerous (`validate-engine.json` / `validate-engine.txt`).

## Admission method and warnings

`validate-admission.py` explicitly sets
`HERMES_HOME=$ARTIFACTS/pulse-rings/wp11-fix-core/validator-home`,
imports the unmodified validator from
`$HERMES_SOURCE`, and directly calls
`hermes_cli.plugin_validate.validate_plugin_dir` against this worktree. It runs
actual capability registration and install-scanner checks. This is Review-3 §1's
real direct-engine alternative, **not** a successful CLI `--install-deps`
dependency-preparation receipt or a clean minimum-Hermes installation claim.

Two report warnings remain for human review:

1. Security caution: the documented literal `crypto_mining` exclusion regex in
   `scripts/ARTWORK-SCOPE.md`; the two `sudo_usage` hits in
   `pulse_rings/sources/hermes.py:32,65` are the existing activity metric enum,
   not shell/elevation. No dangerous finding remains. The documented mirror is
   intentionally not hidden or renamed just to make the caution disappear.
2. Private core imports: MCP policy/refusal compatibility seams in
   `pulse_rings/mcp_access.py` and developer `scripts/verify-mcp-live.py`
   (both removed after the catalog review; MCP now uses public APIs only).
   The engine-provided file/line/symbol list is retained verbatim in `validate-engine.json`.
   No core mutation was added. Missing seams fail closed; maintainer review and
   the unposted public-seam issue remain open.

The isolation report is informational (`host_ready:true`), not a third warning.
Final merged sibling renderer changes still need their own browser checks,
admission rerun and independent review before any authorized live installation.
No UI fixtures were edited here, so browser suites were not rerun in this core
worktree.
