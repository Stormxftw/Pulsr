# WP3 integration (new files only)

## Parent patches (not applied in this branch)

### Engine adapter registration

At Engine construction, after `self.store` exists, register code-owned instances
alongside Discord (or pass this map through the existing `adapters=` seam):

```python
from .sources.github import GitHubSearch, GitHubRepo
from .sources.hermes import HermesActivity

self.adapters = {
    'discord.invite@1': source,
    'github.search@1': GitHubSearch(),
    'github.repo@1': GitHubRepo(),
    'hermes.activity@1': HermesActivity(self.store),
    **(adapters or {}),
}
```

Preserve caller-injected adapter overrides (initialize defaults before updating
with caller adapters). Bare kinds are already resolved to @1 by the engine.

### Plugin registration / manifest

Inside the existing `register(ctx)`:

```python
from .pulse_rings.hooks import register_hooks
register_hooks(ctx)
```

Set `capabilities.provides_hooks` (or the manifest's existing equivalent) to:

```yaml
provides_hooks:
  - pre_llm_call
  - on_session_end
  - post_tool_call
  - on_human_input_request
  - on_human_input_resolved
  - subagent_start
  - subagent_stop
  - api_request_error
```

Do NOT additionally register pre/post_approval_*: the unified human-input pair
already covers human approval, clarify and sudo, without double counting. Smart
auxiliary approvals do not wait for a person and correctly do not count.

Keep the optional secret declaration from PLAN: `PULSE_RINGS_GITHUB_TOKEN`,
`config_schema` type `secret`, env of the same name; do not require it. The adapter
lazily calls `agent.secret_scope.get_secret('PULSE_RINGS_GITHUB_TOKEN')`. No env,
credential-file, core-internal or cross-plugin reads are used.

### Schema and kinds

**No new table or column is required.** Reuses existing `hermes_events`,
`hermes_open`, `meta`. New meta keys: `hermes_hash_salt` (32-byte random salt,
hex-encoded), `hermes_observed_since` (epoch). `hermes_open.kind` is `turn`,
`subagent`, or `waiting:{approval,clarify,sudo}`; `key` is a domain-separated HMAC
SHA-256 id. Origins are fixed enums (`interactive`, `cron`, `subagent`), never
job names, session routes, tool names, provider names or user text.

No kinds/schema/preset changes are required. `recent`'s native baseline is emitted
at `sample.baselines.recent`; `metrics.baseline` remains display-only. Apply the
parent's frozen first-source-sample warming fix before judging the hero ring.

### Net dependency: required review fixes

Keep the parallel review-fix package's transport changes:

* Pass the injected clock through to error parsing. Use `x-ratelimit-reset` only
  when `x-ratelimit-remaining == '0'`; otherwise ignore that header, including on
  422. Honor Retry-After and secondary-limit 403; clamp remote delays to <=6h
  **before extending the durable host gate**. 404 is a 24h retry.
* Local pacing/ceiling exceptions must have `deferred = True` and remain
  `SourceError` instances. Both GitHub adapters re-raise that object untouched;
  engine defers without incrementing failures. Other errors are re-sanitized and
  unexpected exceptions become `SourceError`.
* The old base branch's Net does not yet implement these fixes. The offline 403
  integration test explicitly supplies `now` to the existing `_http_error` seam;
  it proves persistence and adapter propagation, not that the old transport clock
  bug is fixed. Re-run the parallel package's retry/deferral tests after merging.
* Optional type-only cleanup in Store: annotate `db(timeout: float = 5)`; runtime
  already accepts the fractional timeout used by hooks/source.

## Staged requests and the approval preview

All egress is `net.bytes`, with fixed api.github.com URLs. There are **no sleeps,
background workers, direct requests, avatar fetches, Link traversals or redirects**.
A single source operation occurs per poll, respecting the shared >=2s host gate:

1. Cold/expired `github.search`: fetch baseline, return `sample=None`, complete
   replacement state and `next_due=now+2`.
2. Next due poll: fetch recent, return the **first actual sample with both counts
   and the native baseline**. Baseline state persists across adapter/engine restarts
   for six hours, invalidating on structured-param changes. Its historical interval
   precedes the recent window; the daily average scales to 7 days for a 7d pulse.
3. `github.repo`: stage numeric repo counts/id, then fetch per_page=1 pulls and
   read rel=last (or 0/1 when no Link exists). Real GitHub Link headers use
   `/repositories/<numeric-id>/pulls`; accept only the id from that repo response.

**Important create-flow integration:** a cold, one-call pre-approval preview is an
auxiliary baseline refresh, not a completed sample. Do not turn `sample=None` into
zero or claim a measured preview. Preserve the returned state if doing a second,
host-gated preview tick; otherwise show "Sampling after approval" and let normal
engine polling stage both operations after approval. A real hot approval-card
preview requires two paced GETs (or a preexisting cached baseline). Do not loop or
sleep inside the propose tool, and do not exceed its advertised pre-approval limit.
This is the unavoidable cold-cache tension between PLAN's one-call preview and
its two-query GitHub baseline. Each actual emitted search sample has its baseline.

## Observer facts verified against the actual Hermes source

Read-only verification used `$HERMES_SOURCE`:

* `hermes_cli/plugins.py:109-147`: all eight registered hooks are in VALID_HOOKS.
* `agent/turn_context.py:862-874`: pre_llm_call has `session_id`, `task_id`,
  `turn_id`, `parent_session_id`; sensitive user_message/conversation_history are
  ignored. It starts a user turn, not each physical provider request.
* `agent/turn_finalizer.py:886-897`: on_session_end has session_id/turn_id and
  completed/failed/interrupted; it fires at turn finalization. CLI shutdown can
  send an extra interrupted close; deletion is idempotent.
* `model_tools.py:687-708`: post_tool_call supplies status (`ok`, `error`,
  `blocked`, `cancelled`), ids, args/result/error_message. Only the enum status is
  recorded; missing/unrecognized status is `unknown`, never parsed from result.
* `tools/human_input_hooks.py:61-72` and hooks.md:1522-1560: unified hooks pair on
  `request_id`, have kind/session_id/session_key/platform/prompt, resolved adds
  outcome. Prompt/outcome content is not stored; only the known prompt kind and
  salted request id are used.
* `tools/delegate_tool.py:355-360` and delegate_tool_results.py:381-389:
  **both** subagent hooks have `child_session_id`. Only start has
  `child_subagent_id`; stop must NOT be paired by a guessed child id. Goal,
  summary, role and history are ignored.
* `agent/api_request_hooks.py:176-197`: api_request_error includes nested error
  and request payloads. Ignore all fields and increment one count.
* `ctx.current_cron_execution()` is public (plugins.py:411-414); only its
  presence is recorded, never CronExecution contents.
* Public plugin_storage.plugin_db uses check_same_thread=False. Registration
  keeps one connection per process/profile and on_unload closes it. No stat,
  connection-open or PRAGMA happens on the hot hook path.

TTL: turns/subagents 2h; waiting 30m. Event retention 48h, pruned on source reads
and at most once/minute by active hooks. With no activity/read, old disk rows are
removed on the next access, not by an undisclosed timer. Running counts are local
to the active profile's enabled processes; other profiles are never observed.
Rolling event metrics remain null until their first complete 10m/1h window. The
engine's observed-history median warms from actual samples; no baseline is invented.

The writer sets connection-local synchronous=NORMAL once (keeps host journal-mode
policy) to avoid an fsync per hook. Telemetry is best effort: callbacks drop rather
than block on lock contention/storage failure; recent counters may be lost on power
failure. Open-pair TTL bounds crash leftovers. No approval or definition writes use
this handle. Baseline observation starts at registration, not at a guessed install
time. A 300-event WAL benchmark is informational, not a hard real-time guarantee.

## Recorded measurement / verification

Four real unauthenticated GETs were recorded with the opt-in script; no retries.
`tests/fixtures/github/manifest.json` binds the files and exact timestamps/URLs.
As of **2026-11-07T05:17:57Z**, query `repo:NousResearch/hermes-agent is:pr catalog
in:title` returned **170 PRs / trailing 24h**; preceding **14 days: 794**, i.e.
**56.7142857/day**, ratio **2.9974811x**. These are catalog-in-title PRs, not a
claim that every one modifies a plugin-catalog file. Datetime-qualified inclusive
ranges were verified live; baseline ends one second before the recent window.
Repo fixture: 261258 stars, 57852 forks, 53378 open issues including PRs, **34528
open PRs** from the numeric-repository Link header. Avatar support is deliberately
cut (P1); kind budgets already omit that host.

Tests are offline and tests-after (not a claimed TDD red cycle). New tests cover
fixture replay/cache/scaling, real Net accounting, durable 403 reset, bounded
secondary limits, secret-route/leak sentinels, query and Link validation, local
exception identity, unknown vs zero, TTL/retention, cron, shared salt, real child
process writes, cross-thread use, failure containment and no hot-path DB/stat.
The parent's full command passes with explicit `--basetemp` on G: (C: is tight).
See `$ARTIFACTS/pulse-rings/wp3/pytest.txt` and `pytest.xml` for final
counts and the measured median. Live plugin installation/hook firing and the
post-merge first-sample ring are intentionally left to the parent's approved
integration; this worktree does not edit/register/install any live plugin.
