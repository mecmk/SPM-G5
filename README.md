# ConnectSphere

ConnectSphere Event Services is an event-planning and venue-booking system, developed as the
first release for a customer as part of SMU's IS212 (Software Project Management) module,
following a Scrum process. The technology stack and feature scope were finalized at project
setup; the stack is documented below, and feature scope is tracked in the team's backlog.

## Tech Stack

| Layer    | Choice                        |
| -------- | ----------------------------- |
| Backend  | Python 3.12+ / FastAPI        |
| Frontend | React 19 + TypeScript / Vite  |
| Database | PostgreSQL 16                 |
| E2E      | Playwright                    |
| Tests    | pytest (backend)              |

## Prerequisites

Install the following before proceeding. Windows commands use
[winget](https://learn.microsoft.com/en-us/windows/package-manager/winget/) (built into Windows
10/11); macOS/Linux equivalents are listed alongside.

### Python 3.12 or later

```powershell
winget install Python.Python.3.12
```

macOS: `brew install python@3.12` — Linux: use your distribution's package manager or
[pyenv](https://github.com/pyenv/pyenv).

### uv (Python dependency and virtual environment manager)

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`. Full instructions:
[uv installation docs](https://docs.astral.sh/uv/getting-started/installation/).

### Node.js 22 or later (includes npm)

```powershell
winget install OpenJS.NodeJS.LTS
```

macOS: `brew install node@22` — Linux: use [nvm](https://github.com/nvm-sh/nvm) or your
distribution's package manager.

### Docker Desktop (optional — only required to run a local PostgreSQL instance)

```powershell
winget install -e --id Docker.DockerDesktop
```

macOS: `brew install --cask docker-desktop`. Or download it from
[docker.com](https://www.docker.com/products/docker-desktop/), or use an existing PostgreSQL 16
server instead. After installing, open Docker Desktop once and wait for "Engine running".

### DBeaver Community (optional — database viewer)

```powershell
winget install -e --id DBeaver.DBeaver.Community
```

macOS: `brew install --cask dbeaver-community`. Or download it from
[dbeaver.io](https://dbeaver.io/download/). Connection settings are in
[docs/database/README.md](docs/database/README.md#viewing-the-data).

## Setup

```powershell
git clone <repo-url>
cd SPM-G5
npm run setup
Copy-Item backend\.env.sample backend\.env
Copy-Item frontend\.env.sample frontend\.env
docker compose up -d
pip install pre-commit
pre-commit install
pre-commit install --hook-type commit-msg
```

`npm run setup` installs the backend (via uv), frontend, and end-to-end test dependencies in a
single step. See [docs/UV_GUIDE.md](docs/UV_GUIDE.md) for a detailed explanation of what this
does to the backend environment.

**The last three commands are required, not optional.** They enable this repository's
pre-commit hooks (lint, formatting, secret detection, and commit-message format), which run
automatically on every `git commit` from this point on. Skipping this step means violations are
only caught later in CI, after a pull request is already open. See
[CONTRIBUTING.md](CONTRIBUTING.md#local-pre-commit-hooks-required) for what
each hook does and how to resolve a failed commit.

### What `docker compose up -d` does

[`docker-compose.yml`](docker-compose.yml) at the repository root defines one service, `db`: a
PostgreSQL 16 container pre-configured with a username, password, and database name that match
`backend/.env.sample`'s `DATABASE_URL`, so the backend can connect to it without additional
configuration.

- `docker compose up -d` pulls the `postgres:16-alpine` image on first run and starts the
  container in the background (`-d` for detached mode).
- The database is reachable at `localhost:5433` (host port 5433 is used on purpose so the container
  does not clash with a PostgreSQL service already installed on a teammate's machine on 5432).
- Data is stored in a named Docker volume (`connectsphere_db_data`) rather than inside the
  container itself, so removing or recreating the container does not delete existing data;
  only removing the volume does.
- `npm run db:ready` runs `docker compose up -d` for you, so you rarely need these commands directly.

Common commands:

```powershell
docker compose up -d       # start the database (downloads the image on first run)
docker compose down        # stop the database (data is preserved)
docker compose down -v     # stop the database and delete its data volume
docker compose logs -f db  # view the database's logs
```

Without Docker, any PostgreSQL 16 server works — set `backend/.env`'s `DATABASE_URL` to point
at it instead.

## Running the App

With Docker Desktop open, run these from the repo root:

```powershell
npm run db:ready
npm run dev
```

1. `npm run db:ready` starts PostgreSQL in Docker, creates the database if it is missing, applies
   pending migrations, reloads the sample data and verifies it. It never duplicates data, so run
   it at the start of every session.
2. `npm run dev` starts the backend and frontend together. Press Ctrl+C to stop both.

Run `npm run setup` again whenever a pull adds or updates packages.

The frontend is served at [http://localhost:5173](http://localhost:5173) and currently displays a
placeholder page that calls the backend's `GET /health` endpoint, pending the rebuilt UI. The
backend's API documentation (Swagger UI) is available at
[http://localhost:8000/docs](http://localhost:8000/docs).

Sample accounts for signing in through the API with `POST /auth/login`, for example from Swagger
UI (password `Password123!` for all):

| Role | Email |
| --- | --- |
| Event Organiser | `organiser@acme.example` |
| Event Coordinator | `coordinator@connectsphere.example` |
| Venue Staff | `venue@connectsphere.example` |
| Technical Support Staff | `tech@connectsphere.example` |
| Attendee | `attendee@example.com` |

### Database commands

```powershell
npm run db:ready    # start Postgres, migrate, seed, verify
npm run db:status   # applied / pending / drifted migrations
npm run db:reset    # wipe the local database and rebuild it from migrations + seed
npm run db:docs     # regenerate docs/database/DATA_DICTIONARY.md and ERD.excalidraw
```

Schema, seed data, data dictionary and ERD are explained in
[docs/database/README.md](docs/database/README.md).

To run the backend and frontend in separate terminals instead, see
[backend/README.md](backend/README.md) and [frontend/README.md](frontend/README.md).

## Running Tests

```powershell
npm run lint         # lint and format-check the backend and frontend
npm run format       # auto-fix formatting issues in the backend and frontend
npm run test         # backend tests (needs Postgres running) and a frontend build check
npm run test:trace   # backend tests + docs/testing/TRACEABILITY.md (story/AC -> test matrix)
npm run test:e2e     # end-to-end tests on a throwaway database and their own servers
```

Neither kind of test touches your development data. Backend tests build their own
`connectsphere_test` database from the real migrations and seed. `npm run test:e2e` rebuilds
`connectsphere_e2e` on the same PostgreSQL server (it only needs `npm run db:up`), starts its own
API on `:8001` and app on `:5174`, and empties the database afterwards, so your `npm run dev`
stack can stay up. Conventions (fixtures, story markers, traceability) are in
[docs/testing/README.md](docs/testing/README.md).

## Branching Model

This project uses a sprint-trunk model, not GitFlow. There is no `staging`, `release/*`, or
`hotfix/*` branch.

```text
main                     ← stable, protected. Only merges at sprint end, from sprint/<N>.
└── sprint/<N>            ← sprint integration branch (e.g. sprint/1). Protected, PR-only.
    ├── story/<ID>-<slug>  ← feature branch, e.g. story/A1-login
    ├── fix/<ID>-<slug>    ← bug fix, e.g. fix/B1-draft-not-saving
    ├── refactor/<slug>    ← restructuring, no behavior change
    ├── test/<slug>        ← test-only changes
    └── docs/<slug>        ← documentation only
```

Branches are created from the current `sprint/<N>` using the appropriate prefix
(`story/<ID>-<slug>`, `fix/<ID>-<slug>`, `refactor/<slug>`, `test/<slug>`, or `docs/<slug>`).
Pull requests are
opened against `sprint/<N>`, never `main`, and require one approving review before a squash
merge. At the end of a sprint, `sprint/<N>` is merged into `main` with a regular merge.

For the full workflow, commit conventions, and review checklist, see
[CONTRIBUTING.md](CONTRIBUTING.md). For instructions directed at coding agents working in this
repository, see [AGENTS.md](AGENTS.md). For a description of how the system's components fit
together, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
