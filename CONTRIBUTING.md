# Contributing

## Table of Contents

- [Branching Strategy](#branching-strategy)
- [Daily Workflow](#daily-workflow)
- [Commit & PR Conventions](#commit--pr-conventions)
- [Code Review Checklist](#code-review-checklist)
- [General Best Practices](#general-best-practices)

## Branching Strategy

```text
main                     ← stable, protected. Only merges at sprint end, from sprint/<N>.
└── sprint/<N>            ← sprint integration branch (e.g. sprint/1). Protected, PR-only.
    ├── story/<ID>-<slug>  ← feature branch, e.g. story/A1-login
    ├── fix/<ID>-<slug>    ← bug fix, e.g. fix/B1-draft-not-saving
    ├── refactor/<slug>    ← restructuring, no behavior change
    └── test/<slug>        ← test-only changes
```

- **`main`** — always stable and deployable. Protected. Only receives merges from a
  `sprint/<N>` branch at the end of that sprint.
- **`sprint/<N>`** — the integration branch for the current sprint (e.g. `sprint/1`,
  `sprint/2`). Protected, PR-only — nobody commits to it directly. All story/fix/refactor/test
  branches for that sprint branch off of it and merge back into it.
- **`story/<ID>-<slug>`** — a feature branch implementing one backlog story, e.g.
  `story/A1-login`.
- **`fix/<ID>-<slug>`** — a bug fix branch, e.g. `fix/B1-draft-not-saving`.
- **`refactor/<slug>`** — restructuring code with no behavior change.
- **`test/<slug>`** — test-only changes.

**There is no `staging`, `release/*`, or `hotfix/*` branch in this project.** This is a
sprint-trunk model, not GitFlow — keep it that way.

## Daily Workflow

1. Branch off the current `sprint/<N>` using the appropriate prefix
   (`story/`, `fix/`, `refactor/`, or `test/`).
2. Implement the change.
3. Run tests and lint locally (see [AGENTS.md](AGENTS.md) for exact commands).
4. Push your branch.
5. Open a PR **into `sprint/<N>`** (never `main`).
6. Get **one approving review**.
7. **Squash merge** the PR.

At the end of a sprint, a single PR from `sprint/<N>` into `main` is opened and merged with a
regular merge (not squash), preserving the sprint's squashed story commits.

### Local pre-commit hooks (required)

The repository ships a `.pre-commit-config.yaml` (lint/format checks, secret detection, and
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
Commits format below (e.g. `wip fix stuff` gets rejected, `fix: correct venue capacity check`
passes) — that check only runs if you ran the second `install` line above. It's a local
convenience: your commits on a feature branch get squash-merged into one commit anyway, and
`pr-title-check.yml` already enforces this same format on the **PR title** in CI regardless of
whether you have this hook installed.

## Commit & PR Conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat` — a new feature
- `fix` — a bug fix
- `docs` — documentation only
- `style` — formatting, no code change
- `refactor` — restructuring without behavior change
- `test` — adding or fixing tests
- `chore` — tooling, dependencies, build config

Optionally reference the backlog ticket ID in the title, e.g.:

```text
feat: add login form (A1)
```

## Code Review Checklist

Before approving a PR, check:

- [ ] Does it meet the story's acceptance criteria?
- [ ] Is it tested (backend tests for backend changes, manual verification for UI changes)?
- [ ] Does lint and format check pass (`npm run lint` from the repo root)?
- [ ] Is the PR scoped to one story/fix, not a grab-bag of unrelated changes?

## General Best Practices

- Never commit secrets or `.env` files — only `.env.sample` with placeholder values.
- Keep PRs small and scoped to one story or fix.
- Ask before adding a new dependency — check with the team first.
