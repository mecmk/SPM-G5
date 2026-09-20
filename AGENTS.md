# AGENTS.md

Instructions for any coding agent (Claude Code, Copilot, etc.) working in this repository.

## Project Overview

**ConnectSphere** is an SMU IS212 Scrum coursework project, built for a (mock) customer,
ConnectSphere Event Services — an event-planning and venue-booking company. The product
backlog and sprint scope are decided by the team separately (see the team's backlog tool, not
this file) and change over time — do not assume any particular feature exists yet just because
it's plausible for an event-booking system.

This is a **traditional CRUD web app** — plain REST endpoints, a relational-ish data model,
form-driven UI. There is no AI/agentic functionality in this project; do not introduce LLM
calls, agents, or AI SDKs unless a story explicitly asks for one.

## Coding Conventions

This file is the source of truth for process — stack, commands, branching, Definition of Done.
The rules for writing the code itself live beside the code:

| Path | File | Holds |
| --- | --- | --- |
| root | `CLAUDE.md` | Layout, cross-subsystem facts, and the resolution rule |
| `backend/`, `frontend/`, `tests/` | `CLAUDE.md` | Setup, domain, architecture, hard prohibitions, feature workflow |
| `backend/`, `frontend/`, `tests/` | `STYLE.md` | Graded coding rules, each anchored to a real file and line in this repo |

**Read the `CLAUDE.md` and `STYLE.md` of the subsystem you are touching before writing code**, and
defer to the most specific `CLAUDE.md` for the code in front of you. A rule graded `blocking` in a
`STYLE.md` is one a reviewer will block the pull request on.

Some rules are enforced by tooling rather than review — `ruff` for the backend, `oxlint` and
`prettier` for the frontend, `markdownlint` for documentation. Each `STYLE.md` states exactly what
its linter owns, so nothing below that line needs restating in review.

## Tech Stack & Commands

- **Backend**: Python 3.12+ with FastAPI, PostgreSQL (via SQLAlchemy + psycopg3)
- **Frontend**: React 19 + TypeScript, built with Vite
- **E2E tests**: Playwright
- **Backend tests**: pytest
- **Package managers**: uv (backend), npm (frontend, e2e tests)

### Setup

```bash
# Backend
cd backend
uv sync

# Frontend
cd frontend
npm install

# E2E
cd tests
npm install
npx playwright install --with-deps chromium
```

Copy `backend/.env.sample` to `backend/.env` and `frontend/.env.sample` to `frontend/.env`,
adjusting values as needed. From the repo root, `npm run setup` installs all packages,
`npm run db:ready` starts PostgreSQL in Docker on host port **5433** and migrates + seeds it, and
`npm run dev` starts both servers. Root npm scripts call uv through `scripts/uv.mjs`, which
locates or installs uv, so use that wrapper in any new root script too.

### Run (two terminals)

```bash
# Terminal 1 — backend
cd backend
uv run uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm run dev
```

Open `http://localhost:5173`.

### Test & lint

```bash
# Backend — test command, lint/format check command(s)
cd backend
uv run pytest
uv run ruff check .
uv run ruff format --check .

# Frontend — lint/format-check/test command(s)
cd frontend
npm run lint
npm run format:check
npm run build

# From the repo root instead: npm run lint (backend + frontend lint/format-check),
# npm run format (auto-fixes backend + frontend formatting)

# E2E — from the repo root. Needs PostgreSQL up (npm run db:up) but not your dev servers: it
# rebuilds a throwaway connectsphere_e2e database and starts its own API and app on it.
# Never run specs against the development database.
npm run test:e2e
npm run test:e2e -- e2e/venues.spec.ts   # one spec
```

Backend tests likewise run on their own `connectsphere_test` database. Neither suite touches the
development database (see [docs/testing/README.md](docs/testing/README.md)).

Run the relevant lint/test commands for whatever you touched before opening a PR — CI will
also run them, but don't rely on CI to catch what you could catch locally.

## Database & Auth Conventions

- Schema = plain SQL in `backend/db/migrations/` (source of truth), applied by
  `python -m app.dbtool` (`npm run db:*`). Every table/column has a `COMMENT ON`; the data
  dictionary and ERD in `docs/database/` are **generated** from them (`npm run db:docs`) -
  never edit those two files by hand.
- Sprint 1: `001_initial_schema.sql` may be edited in place, then `npm run db:reset`. Later
  sprints: add `NNN_*.sql`, never edit applied files. Full rules: `docs/database/README.md`.
- Seed files are idempotent upserts with fixed UUIDs; mirror rows tests use in
  `backend/tests/support/seed.py`.
- Statuses are `text` + named `CHECK` constraints, not ENUMs. Lists (facilities, layouts,
  accessibility features, equipment types, roles) are reference tables seeded from
  `backend/db/seed/010_reference_data.sql`.
- Each feature's SQLAlchemy models live in `app/<feature>/models.py` and must match the SQL
  (`tests/test_schema.py::test_orm_models_match_database` enforces it).
- Auth: cookie sessions (`app/auth`), `CurrentUser` dependency for "signed in",
  `require_permission(Permission.X)` for role checks. Add new permissions to
  `app/auth/permissions.py`; relationship rules ("only my events") go in the feature service.
- Tests: one file per story under `backend/tests/<feature>/`, every test tagged
  `@pytest.mark.story("<id>", ac=<n>)`; `npm run test:trace` produces the traceability matrix.

## Repository Structure

```text
backend/
  app/
    auth/               # login/logout, sessions, permission matrix (stories 1.1, 1.2)
    venues/             # venue catalogue (stories 8.x)
    common/             # cross-cutting helpers (audit log)
    dbtool/             # migrate / seed / reset / ready / docs
    <feature>/          # router.py, service.py, schemas.py, models.py per feature area
  db/
    migrations/         # NNN_*.sql schema, applied once in order
    seed/               # idempotent reference + sample data
  tests/                # mirrors app/ by feature; support/ has seed constants + factories
  pyproject.toml
frontend/
  src/
    api/                # calls to the backend (health.ts today)
    <feature>/          # pages for one feature area, added as stories are picked up
tests/                  # Playwright e2e specs, separate from backend/frontend
scripts/                # repo-root Node helpers: uv.mjs (uv wrapper for root npm scripts)
docs/
  ARCHITECTURE.md
  database/             # README + generated DATA_DICTIONARY.md and ERD.excalidraw
  testing/              # README + generated TRACEABILITY.md
AGENTS.md
CONTRIBUTING.md
README.md
```

Branches, commits, and PRs reference a ticket/story ID (e.g. `1.1`, `8.3`) from whatever backlog
tool the team is using that sprint. This file doesn't track backlog content itself — just the
convention of referencing IDs so code can be traced back to a story. Don't scaffold a new
feature area speculatively; add one only when a real story needs it.

## Branching & PR Rules (hard constraints)

```text
main                    ← stable, protected. Only merges at sprint end.
└── sprint/<N>           ← sprint integration branch (e.g. sprint/1)
    ├── story/<ID>-<slug> ← feature branch, e.g. story/1.1-login
    ├── fix/<ID>-<slug>   ← bug fix
    ├── refactor/<slug>   ← restructuring, no behavior change
    ├── test/<slug>       ← test-only changes
    └── docs/<slug>       ← documentation only
```

- **Never commit directly to `main` or `sprint/<N>`.** Always branch off the current
  `sprint/<N>` using `story/<ID>-<slug>`, `fix/<ID>-<slug>`, `refactor/<slug>`, `test/<slug>`,
  or `docs/<slug>`.
- Run tests locally before pushing.
- Open the PR against `sprint/<N>` (not `main`). PRs into `main` only happen at sprint end,
  from `sprint/<N>`.
- PRs require **one approving review** before merge.
- **Squash merge** — no merge commits, no rebase merges — to keep `sprint/<N>` history to one
  commit per story/fix.
- If you don't know the current sprint number or don't see a matching `sprint/<N>` branch, ask
  before creating one.

## Feature Development Workflow (Test-First)

Every story starts with a test plan, not code — across whichever subsystems it touches (backend,
frontend, e2e).

1. **Sketch out a test plan before writing any test or implementation code.** For each acceptance
   criterion, cover every one of these categories, not just the happy path: the happy path
   itself, boundary/validation values, role/permission refusals (401/403), conflict cases
   (double-booking, over-committed equipment, etc.), and any other edge case the AC implies. Skip
   a category only when it genuinely doesn't apply to that AC, and say why. Assign each case to
   exactly **one** layer: `backend/tests/` for rule/boundary/permission/conflict detail;
   `tests/e2e/` for the flow a user would actually click through. One exception — a
   boundary/validation case that is purely client-side (blocks submit before any request fires)
   has no backend call to assert against and no other runner, so it lands in `tests/e2e/`
   instead (see [tests/CLAUDE.md](tests/CLAUDE.md)). Outside that exception, never split a case
   across both layers; a case proven at one is not repeated at the other. **Agree the plan
   before writing any test code** — cases can still get added, cut, or reprioritized at this
   point.
2. **Write the tests from the agreed plan before the implementation — e2e specs included, not
   just backend tests.** An e2e spec assigned in step 1 is added to `tests/e2e/` now, against the
   servers as they currently stand, not deferred until the page exists. Run every test written
   here and confirm each one fails for the right reason (the behavior doesn't exist yet — a
   missing route, a 404, an element `getByRole` can't find), not from a typo or missing fixture.
3. **Implement until the tests pass**, following the conventions in the touched subsystem's
   `CLAUDE.md`/`STYLE.md`.
4. **Once the implementation is done, re-run every test written in step 2** — plus the rest of
   the touched suite — and confirm they're all green.
5. **Leave every test in the repo, filed in its proper home**: `backend/tests/<feature>/`,
   tagged `@pytest.mark.story("<id>", ac=<n>)`; `tests/e2e/<feature>.spec.ts`, titled
   `'<story> AC<n>: <behaviour>'`. There is no frontend unit test runner (see
   [frontend/CLAUDE.md](frontend/CLAUDE.md)) — frontend behavior is proven through e2e specs or
   manual exercise in the browser, not a new test type of its own.

This sets the order the per-subsystem "Feature dev workflow" sections
(`backend/CLAUDE.md`, `frontend/CLAUDE.md`, `tests/CLAUDE.md`) run in — tests from the confirmed
plan first, then the steps they describe — it doesn't replace them.

## Commit & PR Conventions

- Conventional Commits style: `feat: add login form (1.1)`, `fix: correct venue availability query (8.3)`.
  Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`.
- Reference the story ID in the commit/PR title, e.g. `feat: assign coordinator to event (5.1)`.
- PR description should state which story/AC it addresses and how it was tested.

## Definition of Done

A story isn't done until:

- [ ] A test plan was sketched out and agreed before implementation, covering all of: happy
      path, boundary, edge, permission, and conflict cases (or noting why one doesn't apply) —
      see Feature Development Workflow above.
- [ ] Acceptance criteria from the backlog are met.
- [ ] The tests written from that plan exist, are filed in the right suite (`backend/tests/` or
      `tests/e2e/`), and pass; lint/format checks are clean.
- [ ] Frontend lint is clean (if applicable); the flow was manually exercised in the browser.
- [ ] No secrets, API keys, or `.env` values committed.
- [ ] PR opened against `sprint/<N>`, one review obtained, CI green.

## Things to Avoid

- Don't add authentication/session complexity beyond what a story asks for (no OAuth providers,
  no third-party auth SDKs, unless a story specifies it).
- Don't introduce a different framework, state management library, or ORM than what the team
  confirmed, without discussing it first — this is a small team project, consistency matters
  more than novelty.
- Don't add CI steps that require secrets/API keys (e.g. third-party bots) without asking —
  this is a student project without a budget for paid services.
- Don't restructure the backend/frontend feature-area layout without a good reason; other
  teammates rely on being able to find "their" story's code by feature area.
- Don't scaffold speculative domain models/routes/pages ahead of the backlog "because they'll
  probably be needed" — add them when a real story requires them.
