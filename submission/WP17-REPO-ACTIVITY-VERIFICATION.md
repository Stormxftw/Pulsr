# WP17 repo activity verification

Branch: `wp17-repo-activity`.

## Contract and compatibility

- `github.repo.params.activity` and `.ci` are strict booleans, default false.
  Absent options remain absent during normalization; the legacy preset, metrics,
  source identity and default 15-minute / 8 req/h budget are frozen by regressions.
- Activity exposes `commits_week` from participation `all[-1]`, source baseline
  `mean(all[-13:-1])`, and `hours_since_push` from existing repo metadata.
  Participation is attempted at most hourly, including after HTTP 202. Local
  `current()` refreshes push age without network or changing the sample timestamp.
- CI exposes `ci_passing` and `ci_running` from the newest default-branch run.
  Actions 403/404 gives an unknown value with an Actions-read-access explanation.
- Base: 2 requests/poll; CI: +1 request/poll; activity: +1 request/hour.
  At 10m: neither 12, activity 13, CI 18, both **19 req/h**.
  At default 15m: neither 8, activity 9, CI 12, both **13 req/h**.
- API host remains `api.github.com`; no new hosts or credential path.
  Only `agent.secret_scope.get_secret('PULSE_RINGS_GITHUB_TOKEN')` supplies a token.
  Sentinel-header tests use fake secrets; no live repository or credential access.
- Stat states are bounded data-only labels with optional ok/warn/crit tone;
  unknown/unmapped states never inherit a success tone. Duration values are hours,
  formatted down to whole minutes, without numeric animation or learning captions.
- Builder adds three checkboxes and a three-block `Repo activity` preset. Synthetic
  previews respect disabled metrics and provide semantic CI, push-age and baseline
  fixtures. `layout_check` describes the special stat modes truthfully.

## Executed checks

Python, using the prescribed isolated Python 3.11 dependencies and full `tests`
suite: **1513 passed, 1 skipped, 1 warning**. The skip is the existing MCP SDK
integration dependency gate; the warning is Starlette's httpx deprecation.
Fixture-only source tests also exercise the real Net throttle/accounting path,
including staged requests and hourly retry suppression after participation 202.

All 14 requested browser suites plus `repo-activity` passed sequentially. Fourteen
JSON reports contain **2325 named checks**, with empty `errors` and `remote` arrays;
`builder-rework` additionally passes its three-step-flow smoke assertions.

| Suite | Named checks |
| --- | ---: |
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
| rework-journeys | 174 |
| rework-integrity | 49 |
| builder-focused-polish | 206 |
| repo-activity | 12 |

Evidence root: `$ARTIFACTS/pulse-rings/wp17-repo-activity/`.
Latest repo-activity, builder2, groups, integrity and focused-polish evidence uses
`final-*` directories. A transient groups timing failure passed on a clean serial
rerun; no production workaround was added.

The external demo was read back, normalized idempotently, compared against the
checked-in example and passed `layout_check` with no warnings and a 19 req/h budget:
`$ARTIFACTS/pulse-rings/demo/5-pulse-rings-repo.pulse.yaml`.

## Operational notes and remaining limits

- No live GitHub test was performed. The user must supply their fine-grained,
  read-only token with repository Contents/Metadata and Actions read access.
- CI deliberately requests `per_page=1`. If the newest run is queued/in progress,
  `ci_running=1` and `ci_passing` is unknown; it does **not** fetch or infer an older
  completed result. This is the single-call-budget interpretation, not a claim to
  retrieve the latest historical completed run while a newer build is running.
- GitHub participation is the current GitHub week, not rolling seven days.
  The current week and baseline remain unknown until GitHub provides enough data.
- Existing preview processes were not stopped or restarted. Additional isolated
  preview listeners were started on 5462 (Node PID 24264) and 5463 (Node PID 42180)
  for dependency-equipped testing. No push or plugin install.
- Self-review and fixture/browser verification were completed. A fresh independent
  reviewer was not available through this subagent's tools; parent review remains
  necessary, especially for the newest-run versus historical-completed CI choice.
