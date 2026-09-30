# Contributing

## Table of Contents

- [Branching Strategy](#branching-strategy)
- [Daily Workflow](#daily-workflow)
- [Commit & PR Titles](#commit--pr-titles)
- [Reviewer Sign-off](#reviewer-sign-off)
- [General Best Practices](#general-best-practices)

## Branching Strategy

Trunk-based development on `main`, not GitFlow: every branch is cut from `main` and squash-merged
straight back into it. Branch names (`story/1.1-login`) and backlog IDs are defined in
[AGENTS.md](AGENTS.md#branching--pr-rules-hard-constraints); commit and PR titles have a quick
reference [below](#commit--pr-titles).

## Daily Workflow

1. Branch off the latest `main`, named as
   [AGENTS.md](AGENTS.md#branching--pr-rules-hard-constraints) says, e.g. `story/1.1-login`.
2. Implement the change.
3. Run tests and lint locally (see [AGENTS.md](AGENTS.md) for exact commands).
4. Push your branch.
5. Open a PR **into `main`**.
6. Get **one approving review** carrying the [reviewer sign-off](#reviewer-sign-off).
7. **Squash merge** the PR.

Keep branches short-lived: one backlog item per branch, merged as soon as it is reviewed and
green, then deleted. A branch that lives for weeks drifts from `main` and ends in merge
conflicts — if `main` moves on while you work, update your branch from it and re-run the tests.

### Local pre-commit hooks (required)

The repository ships a `.pre-commit-config.yaml` (lint/format checks, private-key detection, and
commit-message format), but it only runs automatically on `git commit` after being enabled once
per machine. Every contributor must run this as part of initial setup:

```bash
pip install pre-commit   # or: uv tool install pre-commit
pre-commit install
pre-commit install --hook-type commit-msg
```

Both `install` lines are required — the first wires up lint/format checks on `git commit`, the
second separately wires up the commit **message** check described below. Skipping either line
means that particular check will not run locally, and violations will only surface later in CI,
after a pull request is already open.

With it installed, `git commit` runs lint/format automatically. If a hook auto-fixes files
(formatting), that commit attempt is rejected on purpose so you can review the changes — just
run `git add .` and commit again. To skip the fail/fix/retry dance entirely, format everything
yourself first:

```bash
npm run format   # runs ruff format (backend) + prettier --write (frontend)
```

The `commit-msg` hook also rejects a commit whose **message** doesn't follow the Conventional
Commits format [below](#commit--pr-titles) (e.g. `wip fix stuff` gets rejected,
`fix: correct venue capacity check (b8.3)` passes) — that check only runs if you ran the
second `install` line above. It's a local convenience: your commits on a feature branch get
squash-merged into one commit anyway, and `pr-title-check.yml` already enforces this same format
on the **PR title** in CI regardless of whether you have this hook installed.

## Commit & PR Titles

A quick reference; [AGENTS.md](AGENTS.md#commit--pr-conventions) is the source of truth, and the
two are kept in step.

```text
<type>: <what changed> (<backlog ID>)

feat: reassign event to another coordinator (s5.2)
fix: keep the sign-in form steady while the session loads (b1.1)
chore: scan PRs for secrets (c1.1)
docs: correct the migration rule in the database guide
```

- `<type>` is one of `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`.
  `pr-title-check.yml` rejects any other type in a PR title.
- The backlog ID goes at the end, with its prefix: `s` for a story, `b` for a bug, `c` for a chore.
  Leave it out only when there is no backlog item, as for most `docs`, `refactor` or `test` work.
  Branch names use the number alone: `story/5.2-reassign-coordinator`.
- The PR title matters most. PRs are squash-merged, so it becomes the one commit on `main`.

## Reviewer Sign-off

A PR needs one approving review, and the approval must carry this sign-off as its review
comment. Green CI shows the tests pass, not that they test the right thing, so read the code
itself. Read every line as if it may be AI-generated, because it may be. Tick only what you
actually checked and write N/A beside anything that doesn't apply. Any ❌ or unticked box is a
**Request changes**, not an approval with a note.

Paste this as the review comment and fill it in:

````markdown
### Reviewer sign-off: <story ID>

#### Test cases

I read the code of every test below: one row per test in the PR's Test Plan.

| Test | AC | What it actually asserts | Verdict |
| --- | --- | --- | --- |
| `test_login.py::test_valid_login` | AC1 | 200, session cookie set, `UserOut` body | ✅ correct |
| `login.spec.ts` › `1.1 AC4: …` | AC4 | only the URL changes | ❌ the AC's error message is never checked |

- [ ] Every test in the Test Plan is listed above, and I read its code
- [ ] Each ✅ test asserts the behaviour its AC describes (not just a status code, a mocked value
      echoed back, or that the code ran) and would fail if that behaviour broke
- [ ] Each test's setup matches its title: the right role, seed row and starting state
- [ ] No AC is left without a test; no test is skipped, focused (`.only`), marked `xfail`, or
      loosened to pass
- [ ] Each case sits in one layer only (backend or e2e), as the Test Plan says

#### Code read-through, AI-generated code included

- [ ] I read every changed line, not only the files the summary mentions
- [ ] The logic does what the ACs ask, error paths and the Test Plan's edge cases included
- [ ] Every function, column, endpoint, permission code and import it uses exists; none is
      invented
- [ ] Nothing is special-cased to seed or fixture data (hard-coded IDs, names or dates)
- [ ] No error is swallowed: no bare `except`, empty `catch`, or silent fallback value
- [ ] Endpoints are guarded with `require_permission`; "only my own" rules sit in the service
- [ ] Frontend types and permission strings match the backend's schemas and `permissions.py`
- [ ] Comments, docstrings and story/AC tags describe what the code really does
- [ ] No dead code, leftover debugging, or scaffolding beyond the story
- [ ] The touched subsystem's `blocking` `STYLE.md` rules are followed

#### Ran it

- [ ] Checked out the branch and ran the touched suites locally; they pass
- [ ] Exercised the flow in the browser (if there is UI)

#### Scope

- [ ] One story or fix, with no unrelated changes
- [ ] No secrets; a schema change comes with its migration and regenerated docs
      (`npm run db:docs`)

I have read the test cases above and confirm each is correct, except any marked ❌.
````

## General Best Practices

- Never commit secrets or `.env` files — only `.env.sample` with placeholder values.
- Keep PRs small and scoped to one story or fix.
- Ask before adding a new dependency — check with the team first.
