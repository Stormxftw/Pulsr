# WP6 integration handoff

WP7 applied the parent patches on main. The snippets below preserve the handoff;
README and submission/CHECKLIST.md describe integrated behavior and current evidence.
The public-safety API absence policy was deliberately tightened as recorded below.

These files are additive on `wp6-httpjson` (base `86890d4`). No engine, route,
plugin manifest, renderer, Hermes configuration or user data was edited here.
The parent owns the integration patches below; adapt only surrounding WP5 context.

## Contracts and deliberate choices

- Adapter: `HttpJsonSource`, `poll(definition, previous, state, *, now, net)`.
  `arbitrary_host = True`, `pre_approval_sample = False`. Never call it to preview
  an unapproved definition. Use the normalized kind `http_json`; Engine already
  accepts its `@1` alias through adapter lookup.
- **IP pinning is real**, not a DNS preflight followed by an ordinary URL client.
  Every resolver answer must pass the strict stdlib public-address policy. The
  selected numeric sockaddr is passed to `socket.socket(...).connect(sockaddr)`;
  `HTTPSConnection.connect` is overridden, so there is no hostname re-resolution
  during dialing. TLS uses `ssl.create_default_context()` and the approved host
  for SNI/certificate checking. The HTTP Host is also the approved host.
- HTTPS / exactly port 443, no userinfo, fragments, redirects, cookies, auth,
  proxy environment, compression or executable selectors. No multicast, private,
  loopback, link-local, reserved, CGNAT, ULA, mapped or transition-wrapper IPs.
  Mixed public/private DNS fails closed. JSON is capped at 512 KiB, with an 8s
  deadline, bounded DNS waiting, a socket-shutdown watchdog against slow headers,
  strict JSON numbers, application/json or application/*+json, and RFC6901 pointers.
  Missing/non-numeric/bool values are unknown, never zero or string-coerced numbers.
- Every outbound attempt is exactly one `net.call(host, callback)` reservation;
  no nested `net.json` reservation. Local `Deferred` propagates unchanged. Remote
  failures are sanitized `SourceError`, preserving status/bounded Retry-After.
  Only numeric metrics persist; neither raw bodies, URLs nor headers enter state.
- Verified local authoritative Hermes docs/source:
  `website/docs/developer-guide/adding-platform-adapters.md` (public API table),
  `tools/url_safety.py` (`is_safe_url`, `create_ssrf_safe_async_client`).
  The adapter lazily uses the public `is_safe_url` as an additional origin-only
  check. Both public is_safe_url and create_ssrf_safe_async_client APIs must be
  available/callable or the source is disabled. The actual transport is our
  numeric-IP-pinned implementation, not the generic async client. The independent
  stricter policy cannot be weakened by Hermes's
  `allow_private_urls`/fake-IP/proxy exceptions. It never imports private helpers.
- **WP7 contract resolution:** preserve the stricter fail-closed availability
  policy: no standalone fallback if either Hermes public safety API is absent.
  The independent stdlib pinned transport remains mandatory when APIs exist.
  Net._safe_bytes is unchanged. README, PR and sources/INTERFACE.md now agree;
  no claim is made that this adapter delegates HTTP to the Hermes async client.
- Temporary bounded DNS helpers (at most four unresolved daemon calls) never do
  HTTP. Their late results are discarded. A per-request watchdog is cancelled on
  exit. There is no scheduler, continuing HTTP worker, shell or subprocess.

## Importer API and safety

```python
from .migrate import DiscordPulseImporter
importer = DiscordPulseImporter(engine.store, clock=engine.clock,
                               ceiling=engine.net.ceiling)
# Default source is get_hermes_home()/plugin-data/discord-pulse.
# hermes_home=... exists only for isolated tests/explicit offline scripts.
importer.offer()                       # cheap {available, completed}; no old DB read
plan = importer.plan()                 # read-only summary, counts, ids, budget, token
result = importer.apply(consent=True, token=plan['token'])
```

`apply()` requires literal `True` and the exact current plan token. No implicit
consent, startup import, agent import tool, or automatic old-plugin disable.
A stale source, note/icon, destination allocation/ID, or copy eligibility changes
the consent token; the human must review again. The import marker survives restart
and makes repeat/concurrent imports no-ops. Existing pulse IDs and human notes/icons
are never overwritten. Imported definitions use preset A, bare `discord.invite`,
original invite-code case, `discord-<invite-slug>`, and `approved_via='import'`.
Long/case-colliding slugs use a deterministic guild-hash suffix within 48 chars.
Samples contain only online/members; source gates, errors, identities and raw
payloads are not copied. Only watched servers import; orphan snapshots do not.

Cap and recurring-budget admission are recomputed under `BEGIN IMMEDIATE` using
`MAX_ACTIVE`, `budget` and `admission`, excluding pre-existing IDs. Candidates that
do not fit are counted in `skipped_admission` rather than silently exceeding limits.
Counts on the consent card describe the admitted import, not all source rows.
A successful consent consumes the one-time marker even if zero new pulses fit;
show the skipped counts before allowing consent.

The original is opened as a `file:.../pulse.sqlite3?mode=ro&immutable=1` SQLite URI,
with `query_only` as defense in depth. **A nonempty
WAL or rollback journal is refused**, asking the user to close the old plugin
first. This is necessary: `mode=ro` alone can create/change source `-shm` files;
`immutable=1` alone could silently ignore a live WAL. We neither checkpoint nor
modify/copy the user's live DB. Database hashes are checked around the read.
Notes are bounded UTF-8 copies; icons require PNG/JPEG/WebP magic bytes and the
existing 512 KiB cap. Symlink/junction paths are refused, and copies use exclusive
creation. Database changes and marker are atomic; ordinary copy failures roll back
DB changes and remove created files. Files and SQLite are not power-loss atomic.

## Exact parent patches

### 1. Engine adapter registration + feature/banner data

Add imports beside the other sources (retain all parallel adapter entries):

```diff
+from .sources.http_json import HttpJsonSource
+from .migrate import DiscordPulseImporter
```

Add this entry to `Engine.__init__`'s built-in adapter map **before** the injected
`**(adapters or {})` override. Use the @1 registration alias, consistent with
other defaults: it resolves both normalized bare kinds and direct @1 lookup and
preserves caller overrides under either key (a bare default masks @1 overrides):

```python
'http_json@1': HttpJsonSource(),
```

Change only the `import_discord` feature in the status result:

```diff
- 'features': {'import_discord': False, ...}
+ 'features': {'import_discord': True, ...}
```

In the noncompact branch of `status`, before returning the result:

```python
try:
    result['migration'] = DiscordPulseImporter(
        self.store, clock=self.clock, ceiling=self.net.ceiling).offer()
except Exception:
    result['migration'] = {'available': False, 'completed': False}
```

Do NOT run `plan()` from `/status` or compact tools; the banner probe only checks
source existence and the destination marker. Do not fetch http_json for previews:
WP5 must keep `KINDS[kind]['pre_approval_sample'] is False` fail-closed, as well as
`getattr(adapter, 'arbitrary_host', False)`, BEFORE any network attempt.

### 2. Authenticated human REST routes

In `dashboard/plugin_api.py`, add `import importlib` and append the following.
This resolves the adjacent path-unique plugin package already used by the loader,
without registering a core alias or modifying sys.path. Reuse WP5's human-route
host authentication/CSRF/origin dependency if it adds one; do not publish this as
an agent tool. No request field may override the source/destination filesystem path.

```python
def discord_importer(pulse):
    package = pulse.__class__.__module__.rsplit('.', 1)[0]
    module = importlib.import_module(package + '.migrate')
    return module.DiscordPulseImporter(pulse.store, clock=pulse.clock,
                                      ceiling=pulse.net.ceiling)


class DiscordImportBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    consent: StrictBool
    token: str = Field(pattern=r'^[a-f0-9]{64}$')


@router.get('/migrate/discord-pulse')
def plan_discord_import(pulse=Depends(get_pulse)):
    try:
        return discord_importer(pulse).plan()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    except Exception:
        raise HTTPException(503, 'Discord Pulse import is unavailable.') from None


@router.post('/migrate/discord-pulse')
def apply_discord_import(body: DiscordImportBody, pulse=Depends(get_pulse)):
    if body.consent is not True:
        raise HTTPException(400, 'Explicit human consent is required.')
    try:
        return discord_importer(pulse).apply(consent=True, token=body.token)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    except Exception:
        raise HTTPException(503, 'Discord Pulse import is unavailable.') from None
```

### 3. Renderer consent card, banner, menu and exact readback

The existing feature-gated **Import from Discord Pulse…** menu item already does
`setMigration(true); setMenu(false)`. Retain it; advertising the feature now makes
it usable. Remove obsolete `migrationBusy` and `migrationLock` parent state.
Add this component before `PulsePane` (uses existing h/hooks/Button/friendlyError):

```javascript
function DiscordImportCard({ ctx, profile, close, onConfirmed }) {
  const [plan, setPlan] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    let active = true;
    ctx.rest("/migrate/discord-pulse").then(
      (value) => { if (active) setPlan(value); },
      (err) => { if (active) setError(friendlyError(err)); },
    );
    return () => { active = false; mounted.current = false; };
  }, [ctx, profile]);
  const confirm = async () => {
    if (lock.current || !plan?.token || !plan.available || plan.completed) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const receipt = await ctx.rest("/migrate/discord-pulse", {
        method: "POST", body: { consent: true, token: plan.token },
      });
      const cached = await ctx.rest("/status?poll=0");
      if (!mounted.current) return;
      const ids = new Set((cached.pulses || []).map((pulse) => pulse.id));
      if (!receipt.completed || !cached.migration?.completed ||
          !(plan.ids || []).every((id) => ids.has(id))) {
        throw new Error("Import not yet confirmed. Refresh before retrying.");
      }
      queryClient.setQueryData(keyFor(profile), cached);
      onConfirmed(receipt.recommendation);
      close();
    } catch (err) {
      if (mounted.current) setError(friendlyError(err));
      // A changed-plan 409 needs a fresh card, never silently replace its token
      // and resubmit. Cancel/reopen to review the newly calculated counts.
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  };
  return h("section", { className: "pr-confirm", role: "region",
      "aria-label": "Import from Discord Pulse" },
    h("strong", null, plan?.summary || "Reviewing Discord Pulse import…"),
    h("p", null, "One-time read-only import. The original data stays untouched. No network request is made by importing."),
    plan ? h("p", null,
      `Skipped: ${plan.skipped_existing} existing · ${plan.skipped_admission} over cap/budget · ${plan.skipped_invalid} invalid. ` +
      `After approval: ${plan.budget?.hosts?.join(", ")} · ≈${plan.budget?.req_per_hour_display} req/h added while viewed.`) : null,
    h("p", null, "If the old plugin has a pending WAL, close it before importing. Afterwards, disable Discord Pulse yourself to avoid double polling; its data is kept."),
    error ? h("p", { role: "alert" }, error) : null,
    h("div", { className: "pr-actions" },
      h(Button, { className: "pr-btn", onClick: confirm,
        disabled: busy || !plan?.token || !plan?.available || plan?.completed },
        busy ? "Importing…" : "Confirm import"),
      h("button", { className: "pr-action", disabled: busy, onClick: close }, "Cancel")),
  );
}
```

The card is keyed by profile so a profile switch unmounts it. Its cleanup sets
`mounted.current = false`; late plan/apply/readback responses cannot update the
new profile's cache or report success there.

Replace the whole existing `migration && !compact ? ... : null` card with:

```javascript
migration && !compact
  ? h(DiscordImportCard, { key: `discord-import:${profile}`, ctx, profile,
      close: () => setMigration(false), onConfirmed: setImportNotice })
  : null,
```

In `PulsePane`, add state `const [importNotice, setImportNotice] = useState("");`
and reset it to `""` in the existing profile-change effect. Immediately before
the new card, insert the first-run banner and confirmation notice:

```javascript
data?.features?.import_discord && data?.migration?.available &&
!data?.migration?.completed && !(data.pulses || []).length && !migration && !compact
  ? h("div", { className: "pr-message", role: "status" },
      "Discord Pulse data found. Nothing has been imported. ",
      h("button", { className: "pr-action", onClick: () => setMigration(true) },
        "Review import…"))
  : null,
importNotice ? h("p", { className: "pr-message", role: "status" }, importNotice) : null,
```

No success claim from the POST alone, no post-import polling GET, no automatic old
plugin disable, and no import mutation while merely showing the first-run banner.

### 4. Manifest / README disclosures (copy exact text)

Add these comments to `plugin.yaml` (not invented capability keys):

```yaml
# http_json: human-approved public HTTPS GETs, exact approved host/full URL,
# port 443 only; DNS-vetted IP-pinned TLS, no redirects/headers/secrets/proxies.
# Optional human-only Discord Pulse import reads the old profile plugin DB
# read-only and copies notes/validated icons; never modifies or disables its source.
# No importer/activation tool is exposed to the agent.
```

Use the integrated fail-closed transport disclosure below with the fixed hosts:

> **http_json:** Only after human approval, HTTPS GETs go to the exact public
> host/full URL shown on the approval card, port 443 only. Every DNS answer is
> screened; the socket connects to a vetted IP with the original TLS SNI/Host.
> Hermes's public URL-safety helper and safe-client API must be available/callable,
> otherwise the source is disabled (no standalone fallback). The helper checks the
> origin; our independent stricter stdlib pinned transport performs the request,
> not the generic async client. Private/mapped addresses,
> redirects, authentication headers, cookies and proxy-environment routing are
> refused. Responses are limited to 512 KiB JSON and 8 seconds. Only finite numeric
> metrics are retained. Temporary bounded DNS helpers never initiate HTTP.
>
> **Optional Discord Pulse import:** Pulses → ⋯ → Import from Discord Pulse (or
> the first-run Review import banner) shows counts, skipped rows and recurring
> network allocation before consent. This reads
> `<HERMES_HOME>/plugin-data/discord-pulse/pulse.sqlite3` with SQLite `mode=ro`
> and immutable reads, then copies history, UTF-8 notes and magic-validated icons
> into this profile's Pulsr data directory. The source is never modified.
> Close the old plugin first if it has a pending WAL/journal. Import is one-time,
> idempotent, limited to available active/budget capacity, and makes no network
> request itself. Disable Discord Pulse yourself afterwards to prevent double
> polling; its original data remains available. No configuration/service change is
> performed for you.

## Verification and parent acceptance

Offline fixture tests exercise the real http.client wire parser, overridden socket
connector, DNS rebinding (public on one call, private on the next), mixed DNS,
wrong MIME/compression, oversized bodies, redirects, NaN/Infinity/overflow,
RFC6901 selectors, booleans/strings, timeouts, sanitized errors, durable Net
reservation/Deferred, and the mandatory public-helper/API availability boundaries.
Importer tests synthesize the v0.3.0 schema from `tests/fixtures/migrate/v030.sql`;
no live source DB has been read or copied. Source hashes include DB, notes, icons
and sidecars. They also cover stale consent, concurrent apply, cap/budget closure,
existing IDs/files, malformed payloads, slug collisions, rollback and exclusivity.

Run from the worktree (all caches/temp stay on G:):

```bash
UV_CACHE_DIR=$ARTIFACTS/discord-pulse/uv-cache uv run --isolated --no-project --with 'pytest>=8,<9' --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'jsonschema>=4,<5' --with 'ruamel.yaml>=0.18,<0.19' python -m pytest tests -q --basetemp $ARTIFACTS/pulse-rings/pytest-tmp-wp6
```

Parent must still run the integrated API/UI tests, including GET-plan / POST-consent
/ cached readback, missing/false consent, stale-token 409, profile switch, banner
and feature gating, plus an independent security review. These snippets are a
handoff, not a claim that untouched API/renderer code is already integrated.
No live network sanity GET was used.

Observed on this WP6 revision: **437 passed, no skips** in the complete isolated
suite; **69 WP6 cases** (50 http_json, 19 migration), including execution of the
exact documented route patch against the real importer. Full evidence is
`$ARTIFACTS/pulse-rings/wp6/pytest-final.txt` and `pytest-final.xml`.
The two warnings are dependency deprecation and an existing hook test's JUnit
`record_property` compatibility warning. The documented renderer component passed
`node --check`; this is syntax evidence, not a rendered/live UI test.
The initial new-adapter test attempt failed collection because the new module did
not exist yet; subsequent security/behavior checks passed. No false claim of a
meaningful pre-implementation assertion failure is made.

## Reusable engineering lessons

- Pin the numeric sockaddr at the actual TLS connect boundary, not just at URL
  validation. Preserve both SNI and Host and test the real HTTP client's lifecycle.
- `HTTPConnection.getresponse()` can detach `connection.sock` for Connection: close.
  Retain the transport reference for deadlines and explicitly close the response.
- Read-only SQLite can write SHM. An importer promising zero source writes must
  either handle WAL with a nonmutating snapshot strategy or refuse pending WAL;
  never silently pair immutable=1 with an unchecked WAL.
- Use concise parametrization IDs for large body fixtures: pytest's automatic ID
  can exceed Windows path limits and fail setup before exercising the transport.
- Exclusive-create failure does not confer ownership: never unlink a race winner's
  file while rolling back your own failed copy.
- Preserve fail-closed source availability separately from transport ownership:
  requiring Hermes public safety APIs does not mean claiming they perform a
  code-owned pinned request. Disclose and test both boundaries.
- Recheck kind and adapter preview flags at dispatch, not only proposal creation;
  stored draft eligibility must never grant arbitrary-host preapproval egress.
- After a human import POST, use cached marker plus exact planned-ID readback,
  not a polling status request; discard late responses when the profile unmounts.
