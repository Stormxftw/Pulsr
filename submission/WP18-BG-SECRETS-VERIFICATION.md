# WP18 — background profile secret scope

## Result

Confirmed the diagnosed failure: `Collector.tick` previously called the GitHub
adapter without installing a secret scope. Under multiplexing, the shared
`_optional_token` call raised `UnscopedSecretError`; both adapters replaced it with
“GitHub count is temporarily unavailable.”

Background collectors now capture the registering profile home and context,
keyed by plugin storage root. Each active tick rebuilds the profile mapping using
Hermes's documented `build_profile_secret_scope(home)` and installs it with
`set_secret_scope(..., profile_home=home)`, resetting the returned token in
`finally`. The standard plugin storage layout also identifies the owner for
unbound/viewer-fallback collectors. Custom roots capture `get_hermes_home()` at
registration. Missing scope-binding APIs retain the old path.

The shared GitHub token reader now translates an unscoped read into the sanitized,
actionable `SourceError`: “GitHub token unavailable to background collection;
open the Pulses pane or restart Hermes.” Both ordinary and activity/CI paths
preserve it. Token validation and fixed-host authorization remain unchanged.

Runtime audit found only one `get_secret` call, in `sources/github.py`, shared by
`github.search` and `github.repo`. Other runtime environment reads are execution
markers or the Windows local-data path, not credentials. No direct credential-file
or token-environment fallback was added. README/CHECKLIST disclose Hermes-mediated
per-profile scope reads.

## Verification

- Test-first offline regressions before the fix: **8 failed, 4 passed** after
  correcting the fixture's transport/icon boundary.
- Final regressions exercised against original `HEAD` background/GitHub modules
  loaded in an isolated Python process, without reverting files: **13 failed,
  8 passed**. Candidate: **21 passed**.
- Final full suite, `HERMES_SOURCE=$HERMES_SOURCE`: **1534 passed,
  1 skipped, 1 warning**. The skip requires the MCP SDK in the isolated test
  interpreter; the warning is the existing Starlette/httpx deprecation.
- Focused suites with `HERMES_SOURCE=$HERMES_SOURCE_V0_23_0`:
  `test_background_secrets.py`, `test_background.py`, `test_github.py`,
  `test_repo_activity.py`, `test_sessions.py`: **130 passed, 1 warning**.
- The new host compatibility test actually loads `agent/secret_scope.py` from
  `HERMES_SOURCE` and exercises its real build/set/get/reset APIs. Credential
  providers and HTTP transport are injected fakes; no real secrets are read.
- Coverage includes private-repository Authorization, both GitHub source kinds,
  daemon execution, root/profile separation, caller-scope restoration on success
  and exceptions, late-added/rotated/removed tokens, custom storage roots,
  missing-API compatibility and invalid-token refusal.
- One full run hit `test_mcp.py::test_timeout_no_duplicate_worker_or_late_storage`
  with its worker-start event still unset after the 50 ms timeout. It passed in
  isolation, then the complete suite passed on a sequential rerun. No MCP code or
  timing assertion was changed.

Full-suite command (with `TMPDIR` set to the Hermes scratch directory):

```bash
HERMES_SOURCE=$HERMES_SOURCE uv run --isolated --no-project --python 3.11 --with 'pytest>=8,<9' --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'jsonschema>=4,<5' --with 'ruamel.yaml>=0.18,<0.19' python -m pytest tests -q -p no:cacheprovider --basetemp "$TMPDIR/wp18-pt"
```

## Boundaries

No push, install, gateway restart or live private-repository request. Production
recovery and independent review remain parent/operator verification gates. An
initial fixture attempt left the automatic avatar-fetch boundary unfaked; it was
corrected with a local brand icon, injected transport and a network-denial guard
before the valid offline red/green runs. Final new tests make no real network
requests and use only synthetic credentials.
