# tests/STYLE.md

Personal coding idioms for the Playwright specs in `tests/`. Follow these when writing or
reviewing specs. This document only contains things Claude would get wrong without being told:
not standard Playwright or TypeScript conventions, and not patterns already covered in
[CLAUDE.md](CLAUDE.md) or [docs/testing/README.md](../docs/testing/README.md).

**Automated enforcement: none.** No linter or formatter runs on this directory. `ruff` is scoped
to `^backend/`, the `oxlint` and `prettier` pre-commit hooks to `^frontend/`, the root
`npm run lint` covers only backend and frontend, and `.github/workflows/e2e.yml` has no lint
step. The only hooks that touch these files are the repo-wide whitespace ones
(`trailing-whitespace`, `end-of-file-fixer`). Everything below — including formatting — is on the
author and the reviewer.

**Rule strength.** Every rule carries its weight, and a non-blocking weight is genuinely the
author's call. Never flatten a `taste` into a "must".

| Grade | Meaning |
| --- | --- |
| `blocking` | A reviewer blocks the PR on it. |
| `expected` | The default. Deviating needs a reason stated in the PR. |
| `taste` | Raised as a suggestion, the author decides. |

## Formatting

- `expected` — **Match the frontend's prettier settings by hand: no semicolons, single quotes,
  trailing commas, 100 columns.**
  Nothing here reformats on save or on commit, so the only thing keeping these five files
  consistent with the rest of the repo is the person writing them. A file that drifts will not be
  caught by any check.

  *`expected` · every file in `e2e/` currently follows it; settings mirrored from
  `frontend/.prettierrc.json`*

## Standing divergences

None currently known.

## Maintaining this file

This file is deliberately short. The e2e conventions that matter — story-titled tests, unique
record names, role and label selectors, what belongs here versus in `backend/tests/` — are
prohibitions and facts rather than idioms, so they live in [CLAUDE.md](CLAUDE.md) and
[docs/testing/README.md](../docs/testing/README.md) instead of being restated here.

- **Every rule describes something real.** If nobody has ever got it wrong, it is not a rule
  yet. A new rule needs a site in this repo it can point at — an exemplar that does it right or
  a counter-site that does not. Record a correction in the PR thread; add it here only when a
  second, independent case appears.
- **A dead anchor gets a marker, not a deletion.** Mark it *(path since deleted)* and give a live
  substitute. The rule does not depend on the anchor.
