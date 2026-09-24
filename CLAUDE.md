# CLAUDE.md

Monorepo root. **Thin by design**: orientation, plus the few facts that live *between*
subsystems. Tech stack, setup and test commands, branching rules, Definition of Done, and the
database/auth conventions all live in [AGENTS.md](AGENTS.md) — the source of truth for every
agent and human on this repo. Read it first; this file deliberately does not repeat it.

## Layout

| Path | What it is | Conventions |
| --- | --- | --- |
| `backend/` | Python 3.12 + FastAPI + SQLAlchemy, PostgreSQL | `backend/CLAUDE.md`, `backend/STYLE.md` |
| `frontend/` | React 19 + TypeScript SPA, built with Vite | `frontend/CLAUDE.md`, `frontend/STYLE.md` |
| `tests/` | Playwright e2e. Own `package.json`; run from the root with `npm run test:e2e`, which builds a throwaway database and its own servers | `tests/CLAUDE.md`, `tests/STYLE.md` |
| `scripts/` | Repo-root Node helpers: `poc.mjs`, `uv.mjs` | Root scripts reach uv through `scripts/uv.mjs`, which locates or installs it. Use that wrapper in any new root script, never a bare `uv`. |
| `docs/` | Architecture, database and testing docs | `docs/database/DATA_DICTIONARY.md`, `docs/database/ERD.excalidraw` and `docs/testing/TRACEABILITY.md` are **generated — never hand-edit them.** Regenerate with `npm run db:docs` / `npm run test:trace`. `TRACEABILITY.md` is git-ignored — CI uploads it as an artifact instead. |

## Cross-subsystem facts

- **No shared type generation.** Frontend request/response types are hand-written mirrors of
  the backend's Pydantic schemas — `frontend/src/api/auth.ts:3` mirrors `UserOut` in
  `backend/app/auth/schemas.py`. Change an API contract and you update both sides by hand. The
  same applies to the permission codes in `backend/app/auth/permissions.py`: a frontend that
  gates on them compares plain strings, so a renamed code fails silently rather than at compile
  time.
- **E2E fixtures are backend seed rows.** Any account an e2e spec signs in with must be a row in
  `backend/db/seed/020_sample_data.sql` (see `tests/e2e/support.ts`). Change one, change the
  other.
- **Three ports have to agree.** Backend `:8000`, frontend `:5173`, PostgreSQL `:5433` — not
  the default 5432. `CORS_ORIGINS` in `backend/.env` must list the frontend's origin, and
  `VITE_API_BASE_URL` in `frontend/.env` must point at the backend.
- **Keep a change scoped to one subsystem** unless the task genuinely spans both.
- **Tests come before code.** Full process: [AGENTS.md](AGENTS.md#feature-development-workflow-test-first).

**Defer to the most specific `CLAUDE.md` for the code you are touching.**
