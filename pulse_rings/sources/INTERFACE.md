# Engine/source integration contract — 0.5.0-dev

## Opt-in github.repo activity

One staged request/invocation to the existing safe _get/net boundary: repo, pulls,
optional hourly participation, optional Actions runs on the default branch. `state`
retains numeric pushed_at, periodic due/cache and a bounded staged sample, never
raw HTTP payloads/tokens. `current(sample, state, now=...)` refreshes push age without
I/O or changing sample ts. `activity=false`/`ci=false` use the unchanged legacy path.
Participation all[-1] + mean(all[-13:-1]) supply commits_week/source baseline;
202 is unknown and consumes the hourly slot. CI needs Actions read (403/404 unknown),
latest queued/in-progress is running=1 with unknown conclusion; completed success=1,
failure/cancelled/timed_out=0. See spec/PULSE-1.md for exact budgets and limitations.


The normative frozen read model is [spec/INTERFACE.md](../../spec/INTERFACE.md).
Definitions are parsed/normalized once on proposal/activation and stored using
bare canonical kind names; @1 remains an accepted input/adapter registration alias.
`Engine.activate` is an internal human-approval/import seam, never an agent tool.
`Store.put_pulse` atomically rechecks the cap and budget admission. Limits are in
`limits.py`: 24 active, 5 pending drafts, 300 req/h. Persisted budgets include exact
req_per_hour and ceil-rounded req_per_hour_display. Status never revalidates them.

## Adapter input/output

`Engine(..., adapters={'github.search': code_owned_adapter})` registers trusted
code, never executable definitions. An adapter implements:

- `poll(definition, previous_or_None, state, *, now, net) -> SourceResult`.
- Result fields: `sample` (dict or None), `state` (complete replacement dict),
  `metadata` (safe display replacement, empty retains existing), and absolute
  `next_due` (None uses interval plus injected positive jitter).
- `sample=None` is an auxiliary refresh: preserve the primary sample/last_ok_ts.
- Optional `current(sample_copy, state, *, now)` decorates a copy for freshness;
  it MUST NOT do I/O or mutate persisted history.

Samples: `{ts, metrics: {metric: number|null}, baselines: {metric: number},
unknown_reasons: {metric: text}}`. Finite numeric values only; bool is not a number.
Source baselines MUST be `sample.baselines[component.metric]`. KINDS documents
which metric has one. A GitHub source may also expose `metrics.baseline` for a
text line; the scorer never reads that display metric implicitly.

Metadata is persisted once on the pulse, stripped from new sample payloads, and
reattached to `previous.metadata` at the adapter boundary for compatibility. No
identities, prompts, messages, tool args/results, raw responses or secrets belong
in samples/state/metadata/errors. Same pulse/timestamp replaces rather than doubles.
History reads use the largest component window plus the last 48 sparkline points;
polls load only the latest primary sample. Seven days are retained.

History-derived median/oldest deltas alone need a prior observation. Source/fixed
baselines and measured level components score immediately. An entirely history-
derived ring warms as a whole; all-unknown rings expose `ring.unknown=true`.
Capsule captions are kind-independent, including 2.5× usual at ratio 2.5.

## Network and failure taxonomy

Every outbound attempt MUST use injected net, including icons and auxiliary calls:

- `net.json(https_url, headers=None, arbitrary=False)` returns parsed JSON.
- `net.bytes(https_url, headers=None, timeout=8, limit=524288, arbitrary=False)`
  returns raw bytes and response headers.
- `net.call(host, callback)` gates an injected/path-allowlisted transport. Do not
  nest it around json/bytes (double reservation).
- `net.usage()` returns used/ceiling/window_seconds. Sliding-hour reservations and
  ≥2s host spacing survive restarts. Fixed hosts: discord.com,
  cdn.discordapp.com, api.github.com, avatars.githubusercontent.com.
- Public HTTPS port 443 only, no userinfo/fragments/redirects. Arbitrary hosts
  require public Hermes is_safe_url and create_ssrf_safe_async_client APIs to
  be importable/callable; unavailable means closed (no standalone fallback).
  http_json checks the origin, independently vets every DNS answer and dials a
  numeric-IP-pinned TLS socket with approved SNI/Host, not the generic async client.
  Only api.github.com may receive Authorization. Credential access belongs to the
  integrating source via approved public Hermes capabilities, never token files.
- JSON requires application/json or +json, 512 KiB/8s cap; icons use 4s.
- SourceError is a sanitized remote failure. Remote 429 and GitHub 403 persist
  host gates; retries cap at 6h, 404 at 24h. Retry-After body/header is supported;
  x-ratelimit-reset applies only when remaining == '0'. Net passes the injected
  clock through both transports; never derive test delays from wall-clock time.
- Deferred is a local reservation delay, NOT a failure: adapters MUST propagate
  it (including auxiliary paths). The engine sets next_due plus jitter without
  increasing failures, setting error or creating backoff.
- Other exceptions are caught per poll and per row, logged by class only, and
  become sanitized error rows. Source errors must not contain credentials/URLs.

## Store/routes/readers

Store uses profile-aware public plugin_data_dir/plugin_db, WAL and BEGIN IMMEDIATE
for claims/admission. No network under a write transaction. A 90s claim recovers
from crashes. `db()` transfers close responsibility to the caller. Hooks should
retain one process-local connection or a tiny queue, not run schema/PRAGMA work
on every event; event persistence belongs to the separate source integration.

Schema version remains 1 with additive persisted budget columns on pulses/drafts;
old valid rows migrate once, corrupt rows stay visible and fail closed. No hot-path
validation. Engine.propose/Store.put_draft persist capped, expiring proposals;
WP5 owns human approve/reject endpoint transactions and must reuse admission.
Draft statuses are pending|approved|rejected|expired. Origin is a parsed object.
Preview is null or a complete computed status row, including one-sample previews.

GET /status defaults to at most one due poll; GET /status?poll=0 never collects.
PATCH /pulses/{id} accepts strict `{paused: bool}`; DELETE preserves history/notes.
Legacy human POST/DELETE servers aliases remain, never exposed as tools.
Tools use `status(poll=False, include_icons=False, compact=True)`, with no history,
images, servers or curated aliases. Optional UI actions require status.features.

The dashboard loader registers only a path-unique plugin package for relative
imports, never a Hermes/core module (see README's rule-9 justification).
Frozen tests/legacy_v030.py must remain independent. Golden numeric equivalence
covers recorded fixtures and the real counts-only export, not frozen presentation
strings or the deliberately corrected first-sample measured-level behavior.
