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

This file is the source of truth for process — stack, commands, branching, merge checklist.
The rules for writing the code itself live beside the code:

| Path | File | Holds |
| --- | --- | --- |
| root | `CLAUDE.md` | Layout, cross-subsystem facts, and the resolution rule |
| `backend/`, `frontend/`, `tests/` | `CLAUDE.md` | Setup, domain, architecture, hard prohibitions, feature workflow |
| `backend/`, `frontend/`, `tests/` | `STYLE.md` | Graded coding rules, each anchored to a real file and function in this repo |

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
- Never edit a migration once it has been applied. Change the schema with a new `NNN_*.sql`
  file, the next free number. One that has not merged into `main` is still yours to edit,
  followed by `npm run db:reset`. Full rules: `docs/database/README.md`.
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
  `@pytest.mark.story("<id>", ac=<n>)`; `npm run test:trace` produces the traceability matrix
  (git-ignored; CI uploads it as an artifact).

## Repository Structure

Folders, not files: the files inside a folder change with every story, so list the folder for
those. A new feature area gets its line here in the same PR (see
[Keeping Docs Current](#keeping-docs-current)).

```text
backend/
  app/                  # one package per feature area: router.py, service.py, schemas.py, models.py
    auth/               # sign-in, sessions, the permission matrix, the dependencies routers use
    bookings/           # venue booking requests, Venue Staff's decisions, withdrawals
    coordination/       # assigning and reassigning an event's coordinator
    equipment/          # an event's equipment requests: recording, holding, submitting to Technical Support
    events/             # event requests, review and decisions, event details, routine edits
    notifications/      # who is told of each action, and each user's own notifications
    venues/             # the venue catalogue, its search and its availability calendar
    common/             # shared by feature areas: the audit log
    dbtool/             # migrate / seed / reset / ready / docs (python -m app.dbtool)
  db/
    migrations/         # NNN_*.sql schema, applied once in order
    seed/               # idempotent reference + sample data
  tests/                # mirrors app/ by feature; support/ has seed constants + factories
frontend/
  src/
    api/                # one <feature>.ts per backend feature area, plus the shared client
    auth/               # the sign-in page, the session, route guards, permission codes
    bookings/, events/, venues/   # the pages of each feature area
    components/         # presentational pieces used by more than one page
    layout/             # the signed-in frame: sidebar, phone drawer, the navigation list
    notifications/      # the notification centre
    pages/              # pages of no feature area: home, not permitted, coming soon
    shared/             # helpers used by more than one page
    errors/             # the registry of every user-facing error
tests/
  e2e/                  # Playwright specs, one per story area
scripts/                # Node helpers behind the root npm scripts
docs/                   # architecture, database and testing guides; sprints/ holds sprint records
```

Don't scaffold a new feature area speculatively; add one only when a real story needs it.

## Backlog IDs

Every backlog item has an ID: a type prefix and a number. `s` is a story (`s8.1`), `f` a fix
(`f1.1.1`, a fix against story 1.1) and `c` a chore (`c1.0.1`). The same ID, prefix included, goes
in the branch name and at the end of the commit message and PR title:

- branch: `story/s8.1-venue-search`, `fix/f1.1.1-login-flash`, `chore/c1.0.1-secret-scan`;
- title: `feat: search and filter the venue catalogue (s8.1)`.

Tests are the exception. They use the story number alone, `@pytest.mark.story("1.1", ac=2)` and
`'1.1 AC2: …'`, because a test always proves a story's acceptance criterion, even when a fix adds
it. Older branches and commits use `b` for a fix; `f` replaces it. This file doesn't track backlog
content itself.

## Branching & PR Rules (hard constraints)

```text
main                   ← trunk. Stable, protected, PR-only.
├── story/<ID>-<slug>  ← a story, e.g. story/s8.1-venue-search
├── fix/<ID>-<slug>    ← a fix, e.g. fix/f1.1.1-login-flash
├── chore/<ID>-<slug>  ← a chore: tooling, CI, dependencies, e.g. chore/c1.0.1-secret-scan
├── refactor/<slug>    ← restructuring, no behavior change
├── test/<slug>        ← test-only changes
└── docs/<slug>        ← documentation only
```

- **Trunk-based: never commit directly to `main`.** Always branch off the latest `main` using
  `story/<ID>-<slug>`, `fix/<ID>-<slug>`, `chore/<ID>-<slug>`, `refactor/<slug>`,
  `test/<slug>`, or `docs/<slug>`. There are no `sprint/<N>` integration branches.
- Keep branches **short-lived**: one backlog item each, merged once reviewed and green, then
  deleted. If `main` moves on while you work, update your branch from it and re-run the tests.
- Run tests locally before pushing.
- Open the PR against `main`.
- PRs require **one approving review** before merge.
- **Squash merge** — no merge commits, no rebase merges — to keep `main` history to one commit
  per story/fix.

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

- Conventional Commits style, ending with the backlog ID when the change has one:
  `feat: search and filter the venue catalogue (s8.1)`,
  `fix: keep the sign-in form steady while the session loads (f1.1.1)`,
  `chore: scan PRs for secrets (c1.0.1)`. A `docs`, `refactor` or `test` change with no backlog
  item leaves it out. Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`.
- PR description should state which story/AC it addresses and how it was tested.

## Keeping Docs Current

Most docs describe a pattern and point at the code, so they stay true without upkeep. These are
the exceptions. Each is updated by hand, in the same PR as the change that affects it:

| When a PR… | Update |
| --- | --- |
| adds a migration (`NNN_*.sql`) | the data dictionary and ERD: run `npm run db:docs` and commit the result |
| adds, removes or renames a feature-area folder | the folder map in [Repository Structure](#repository-structure) |
| adds an e2e spec, or tests another story or AC in one | that spec's row in the table in [tests/README.md](tests/README.md) |
| changes an API request or response shape | its hand-written mirror in `frontend/src/api/<feature>.ts` |
| adds or renames a permission code | `frontend/src/auth/permissions.ts`, to match `backend/app/auth/permissions.py` |
| adds or changes a seed row that tests use | `backend/tests/support/seed.py`; `tests/e2e/support.ts` for an account or event a spec uses; the sample-login tables in [README.md](README.md) and [docs/database/README.md](docs/database/README.md) for a seed user |
| renames, moves or deletes a function or component a `STYLE.md` cites | that citation, and any code example there modelled on it |
| adds a violation of a `STYLE.md` rule, or fixes one | that file's Standing divergences table |
| changes a step of the merge checklist | both [Merge Checklist](#merge-checklist) below and `.github/PULL_REQUEST_TEMPLATE.md` |
| changes the commit or PR title format | both [Commit & PR Conventions](#commit--pr-conventions) above and the quick reference in [CONTRIBUTING.md](CONTRIBUTING.md#commit--pr-titles) |
| adds a feature area or moves a responsibility between components | [docs/C4_MODEL.md](docs/C4_MODEL.md), per its own "Keeping this file honest" |

**Generated — never edit by hand:** `docs/database/DATA_DICTIONARY.md` and
`docs/database/ERD.excalidraw` (`npm run db:docs`), and `docs/testing/TRACEABILITY.md`
(`npm run test:trace`; git-ignored). **Not kept current, on purpose:** `docs/sprints/`, a record of
each sprint as it stood.

When writing any doc, cite code by file and function name, never by line number, and leave out
counts ("27 tables") and progress ("built so far"). All three go stale with the next change;
progress belongs in the backlog.

## Merge Checklist

Gates every PR, not every story: a story can take several PRs. The author ticks the checklist in
[.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md), and the two must match:

- [ ] A test plan was sketched out and agreed before implementation, covering all of: happy
      path, boundary, edge, permission, and conflict cases (or noting why one doesn't apply) —
      see Feature Development Workflow above.
- [ ] Every acceptance criterion the PR addresses has at least one row in the Test Plan table,
      and is met.
- [ ] The tests written from that plan exist, are filed in the right suite (`backend/tests/` or
      `tests/e2e/`), failed before the implementation, and pass now.
- [ ] The author has read every changed line, including any AI-generated code and tests, and can
      explain it. It does what the acceptance criteria ask, the functions, fields and endpoints
      it uses exist, and no test was weakened, skipped or edited to match a bug.
- [ ] Lint/format checks are clean; the flow was manually exercised in the browser (if there is
      UI).
- [ ] No secrets, API keys, or `.env` values committed.
- [ ] PR opened against `main`, CI green, and approved with the
      [reviewer sign-off](CONTRIBUTING.md#reviewer-sign-off): every test case listed, its code
      read, and marked correct.

An agent that opens a PR fills in the template but leaves the read-through box unticked. Only the
human author can say they read and understood the code. An agent never posts a reviewer sign-off.

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
