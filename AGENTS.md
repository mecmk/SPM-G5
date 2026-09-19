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
adjusting values as needed. A local PostgreSQL instance can be started with
`docker compose up -d` from the repo root.

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

# E2E — test command (requires both dev servers running)
cd tests
npm test
```

Run the relevant lint/test commands for whatever you touched before opening a PR — CI will
also run them, but don't rely on CI to catch what you could catch locally.

## Repository Structure

```text
backend/
  app/                  # FastAPI app source, structured by feature as stories are added
  tests/                # backend tests, mirrors the app's feature layout
  pyproject.toml
frontend/
  src/
    <pages/components>    # one file per feature area, added as stories are picked up
    api/                   # calls to the backend
tests/                  # e2e tests, separate from backend/frontend
docs/
  ARCHITECTURE.md
AGENTS.md
CONTRIBUTING.md
README.md
```

Branches, commits, and PRs reference a ticket/story ID (e.g. `A1`, `B2`) from whatever backlog
tool the team is using that sprint. This file doesn't track backlog content itself — just the
convention of referencing IDs so code can be traced back to a story. Don't scaffold a new
feature area speculatively; add one only when a real story needs it.

## Branching & PR Rules (hard constraints)

```text
main                    ← stable, protected. Only merges at sprint end.
└── sprint/<N>           ← sprint integration branch (e.g. sprint/1)
    ├── story/<ID>-<slug> ← feature branch, e.g. story/A1-login
    ├── fix/<ID>-<slug>   ← bug fix
    ├── refactor/<slug>   ← restructuring, no behavior change
    └── test/<slug>       ← test-only changes
```

- **Never commit directly to `main` or `sprint/<N>`.** Always branch off the current
  `sprint/<N>` using `story/<ID>-<slug>`, `fix/<ID>-<slug>`, `refactor/<slug>`, or `test/<slug>`.
- Run tests locally before pushing.
- Open the PR against `sprint/<N>` (not `main`). PRs into `main` only happen at sprint end,
  from `sprint/<N>`.
- PRs require **one approving review** before merge.
- **Squash merge** — no merge commits, no rebase merges — to keep `sprint/<N>` history to one
  commit per story/fix.
- If you don't know the current sprint number or don't see a matching `sprint/<N>` branch, ask
  before creating one.

## Commit & PR Conventions

- Conventional Commits style: `feat: add login form (A1)`, `fix: correct venue availability query (D3)`.
  Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`.
- Reference the story ID in the commit/PR title, e.g. `feat: submit event request (B2)`.
- PR description should state which story/AC it addresses and how it was tested.

## Definition of Done

A story isn't done until:

- [ ] Acceptance criteria from the backlog are met.
- [ ] Backend tests pass for the touched area; lint/format checks are clean.
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
