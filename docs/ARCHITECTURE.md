# Architecture

High-level view of how the pieces of ConnectSphere connect: a React SPA talking to a REST API
backed by PostgreSQL.

```text
┌────────────┐        HTTP (JSON, REST)        ┌──────────────┐        SQL        ┌────────────┐
│   Browser  │ ───────────────────────────────▶ │   Backend    │ ─────────────────▶ │ PostgreSQL │
│  (React +  │                                   │  (FastAPI)   │                    │  database  │
│    Vite)   │ ◀─────────────────────────────── │              │ ◀───────────────── │            │
└────────────┘                                   └──────────────┘                    └────────────┘
```

- **Frontend** (`frontend/`): a React + TypeScript SPA built with Vite. Currently a single
  placeholder page that calls the backend's `GET /health` endpoint and displays the result,
  proving the frontend can reach the backend.
- **Backend** (`backend/`): a FastAPI service. Currently exposes one example endpoint,
  `GET /health`, returning `{"status": "ok"}`. Database connectivity (SQLAlchemy engine/session
  setup in `backend/app/db.py`) is wired up but not yet exercised by any route.
- **Database**: PostgreSQL. `docker-compose.yml` at the repo root runs a local instance for
  development.
- **E2E tests** (`tests/`): Playwright, run against the frontend and backend dev servers
  together.

## What's not here yet

No domain models, routes, or pages exist beyond the example above — the product backlog hasn't
been written yet. As real user stories are picked up, this document should grow to describe the
actual domain model (e.g. events, venues, bookings — whatever the backlog defines) and how
requests flow through the system for those features.
