# Contributing to Pulsr

Pulsr is a Hermes Agent plugin and a Hackathon entry, and more than one person or agent
may work on it at the same time. These rules keep that safe.

## 1. Every change starts with an issue

- Find or open an issue on <https://github.com/Stormxftw/Pulsr/issues> before writing code.
  Use the **Bug** or **Task** form.
- Put it in the **Hackathon submission** milestone if it must land before the deadline.
- Label it: one `source: …` or `area: …` label, plus `bug` / `qa` / `submission` / `upstream`
  as fits. Add `priority: high` only for things that block submission, and `needs: user` when it
  waits on the owner.
- One issue per problem. If you find a second bug while working, open a second issue.
- The pinned **Tracking: hackathon readiness** issue lists everything that has to be done.

## 2. Branches

- Branch from the latest `main`. Name it `<type>/<issue>-<short-name>`, for example
  `fix/9-bg-secret-scope` or `qa/1-discord`.
- Work in a separate git worktree if you run several branches at once.
- Never commit to `main` directly. Every change goes through a pull request.

## 3. Commits

- Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`,
  `test:`, `refactor:`, `chore:`.
- Reference the issue with **`Refs #N`** in every commit message.
- **Never write `Fixes #N` or `Closes #N`.** GitHub closes the issue as soon as that reaches
  `main`, before anyone has checked it in a real Hermes install.

## 4. Pull requests

- Open a PR into `main` using the template. Link the issue with `Refs #N`.
- List any **shared code** you touched (the `desktop/plugin.js` renderer and formatting, the engine,
  the store, the display spec), because parallel branches often conflict there.
- CI must be green. The workflow runs the offline Python suite, the pre-submit checks and a
  renderer syntax check.
- For UI changes, also run the browser suites that cover the change (see below) and attach or link
  the screenshots you reviewed.
- At least one review before merging. The owner (@Stormxftw) reviews changes to approval,
  disclosure, network, secrets or MCP code.
- Use **merge commits** (no squashing) so the `Refs #N` history on the branch is kept. The branch
  is deleted after merge.

## 5. Closing issues

An issue is closed by hand, with a comment, once:

1. the fix is merged to `main`,
2. the full test suite passes on the merged tree, and
3. for anything visible or live, it has been checked in a real Hermes Desktop install.

## 6. Tests

Python (run from the repository root):

```bash
HERMES_SOURCE=<path to a hermes-agent checkout> uv run --isolated --no-project --python 3.11 \
  --with 'pytest>=8,<9' --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' \
  --with 'jsonschema>=4,<5' --with 'ruamel.yaml>=0.18,<0.19' \
  python -m pytest tests -q -p no:cacheprovider
```

Browser suites, rendered with the real Hermes Desktop UI kit:

```bash
node scripts/preview-server.mjs <hermes-agent checkout> <port>          # keep running
PULSE_PREVIEW_ORIGIN=http://127.0.0.1:<port> node scripts/test-<suite>.mjs <hermes-agent checkout> <out-dir>
```

- Add tests for every fix, ideally written before the fix.
- Never weaken an existing test to make a change pass. If a test is wrong, say why in the PR.
- Tests must not make real network calls. Use recorded, sanitized fixtures.

## 7. Rules that don't bend

- **No secrets anywhere:** not in code, fixtures, issues, PRs, screenshots or logs. Tokens are
  read only through Hermes secrets (`agent.secret_scope.get_secret`).
- **Approval is human-only.** No code path may approve a draft on its own.
- **Pulse definitions stay data-only.** No executable content, and raw CSS stays out of shared
  definitions.
- **Keep the plugin ID `pulse-rings`.** The repository is called Pulse, but renaming the plugin
  ID would break installed data and configuration.
- **Don't change a user's live install** (plugin folder, plugin data, gateway) unless the owner
  asks. Back up `pulse.sqlite3` before any install.
- **Hermes compatibility:** support Hermes 0.22.7 and later. Use public plugin APIs where they
  exist, and disclose any use of private ones in `submission/CHECKLIST.md`.
