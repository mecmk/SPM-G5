# backend/CLAUDE.md

FastAPI + SQLAlchemy over PostgreSQL. Setup, branching and Definition of Done are in
[AGENTS.md](../AGENTS.md); database rules in detail are in
[docs/database/README.md](../docs/database/README.md). This file holds only what is specific to
`backend/` and not obvious from reading the code.

**Before writing or reviewing code in `backend/`, read [STYLE.md](STYLE.md)** — the graded
coding rules for this subsystem, with the sites in this repo each one is anchored to.

@STYLE.md

## Setup and commands

```bash
uv sync                                    # install; re-run after pyproject.toml / uv.lock change
uv run uvicorn app.main:app --reload --port 8000
uv run pytest                              # needs PostgreSQL running (npm run db:up from root)
uv run ruff check . && uv run ruff format --check .
uv run python -m app.dbtool ready          # create + migrate + seed + verify
uv run python -m app.dbtool reset          # drop all, then migrate + seed + docs  (local only)
uv run python -m app.dbtool docs           # regenerate data dictionary + ERD
uv run pytest --traceability=../docs/testing/TRACEABILITY.md   # regenerate the story matrix
```

The root `npm run db:*` scripts wrap these and reach uv through `scripts/uv.mjs`. Regenerating
the data dictionary and ERD is **manual and unenforced** — no hook or CI step runs it, so a
schema change leaves them stale until someone re-runs the command. The traceability matrix is
git-ignored: generate it locally, or download the `traceability-matrix` artifact from a PR's
Backend CI run.

## Environment variables

Read by `app/config.py` from `backend/.env` (copy `backend/.env.sample`). Pydantic maps each
setting to its upper-case name.

**Required: none** — every setting has a working local default.

| Optional | Default | Note |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://connectsphere:connectsphere@localhost:5433/connectsphere` | Port **5433**, not 5432 |
| `TEST_DATABASE_URL` | `<DATABASE_URL>_test` | Dropped and rebuilt every pytest session. Must differ from `DATABASE_URL`; `conftest.py` exits rather than wipe dev data |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | JSON array string — comma-separated is not supported |
| `SESSION_COOKIE_NAME` | `connectsphere_session` | |
| `SESSION_TTL_HOURS` | `12` | |
| `SESSION_COOKIE_SECURE` | `False` | Set `True` only when serving over HTTPS |

## Domain

`db/migrations/001_initial_schema.sql` defines **27 tables covering the entire product backlog**
— events, bookings, equipment, registrations, notifications — while only `auth` and `venues`
have application code. **The schema running ahead of the app is deliberate: a table existing is
not a licence to build the feature.** Add code when a story asks for it.

- `roles` → `users` → `user_sessions`. `users.role_code` is the RBAC key; external users also
  belong to a `client_organisations` row.
- `venues`, plus reference tables `facilities`, `room_layouts`, `accessibility_features`, joined
  through `venue_facilities`, `venue_layouts`, `venue_accessibility_features`.
- `audit_log` — append-only, written only through `app/common/audit.py`.

Statuses are `text` columns with named `CHECK` constraints, never PostgreSQL ENUMs (there are 33
checks and zero `CREATE TYPE`). Pick-lists are reference *tables* seeded from
`db/seed/010_reference_data.sql`, never Python constants.

## Architecture

One package per feature area under `app/`, always the same four files:

| File | Holds | May import |
| --- | --- | --- |
| `router.py` | HTTP only — paths, status codes, permission dependencies. Translates service exceptions into `HTTPException` | `schemas`, `service`, `app.auth.deps` |
| `service.py` | Business rules. Raises plain Python exceptions, never `HTTPException` | `models`, `schemas`, other features' services |
| `schemas.py` | Pydantic request/response models | `models`, for `from_*` constructors |
| `models.py` | SQLAlchemy ORM mirroring the SQL tables | `app.db` |

Exemplar: `app/venues/` has all four. `app/auth/` adds `deps.py`, `permissions.py`,
`passwords.py`. Register each new router in `app/main.py`.

Authorisation: `CurrentUser` means "signed in", `require_permission(Permission.X)` means "role
holds this permission". Relationship rules — *"an organiser sees only their own events"* — need
the record in hand, so they belong in the feature's service, never in `permissions.py`.

### `db/migrations/` and `db/seed/` — the schema is SQL, not ORM

The SQL is the source of truth and the ORM mirrors it;
`tests/test_schema.py::test_orm_models_match_database` fails when the two drift. Sprint 1 only:
`001_initial_schema.sql` may be edited in place, followed by `npm run db:reset`. From sprint 2,
add `NNN_*.sql` and never edit a file that has been applied.

### `app/dbtool/` — tooling, not feature code

Migration runner, seeder and documentation generator behind `python -m app.dbtool`. It does not
follow the four-file feature layout and should not be reshaped to.

## Do not

- Do not create tables with `Base.metadata.create_all()`, and do not add Alembic.
- Do not hand-edit `docs/database/DATA_DICTIONARY.md` or `docs/database/ERD.excalidraw`.
- Do not raise `HTTPException` from a service, or run a query from a router.
- Do not add a table or column without a `COMMENT ON` — the data dictionary is generated from them.
- Do not add rows to `db/seed/020_sample_data.sql` without mirroring them in `tests/support/seed.py`.
- Do not point `TEST_DATABASE_URL` at the development database.
- Do not add an auth dependency (passlib, python-jose, an OAuth SDK) — sessions are stdlib
  scrypt hashes plus an httponly cookie, and story 1.1 AC3 is already satisfied.
- Do not branch on role names in feature code; check a `Permission` member instead.

## Feature dev workflow

Adding `<feature>` end to end:

1. `db/migrations/NNN_*.sql` — tables plus `COMMENT ON` (sprint 1: edit `001` and `npm run db:reset`)
2. `db/seed/010_reference_data.sql` — any new pick-list values
3. `app/<feature>/models.py` — ORM mirroring that SQL
4. `app/<feature>/schemas.py` — request/response models
5. `app/<feature>/service.py` — rules, plus `record_audit(...)` for significant writes
6. `app/auth/permissions.py` — new `Permission` members, granted in `ROLE_PERMISSIONS`
7. `app/<feature>/router.py` — endpoints guarded by `require_permission`
8. `app/main.py` — `include_router`
9. `tests/<feature>/test_*.py` — every test marked `@pytest.mark.story("<id>", ac=<n>)`
10. From the repo root: `npm run db:docs` (commit the result) and `npm run test:trace` (check
    your story's ACs appear; the matrix itself is git-ignored)

Fixtures from `tests/conftest.py`: `db`, `client`, the pre-signed-in `organiser_client`,
`coordinator_client`, `venue_staff_client`, `tech_client`, `attendee_client`, and
`login_as(Users.X)`. Seed users live in `tests/support/seed.py::Users`. Every test runs inside a
transaction that is rolled back, so no clean-up code is needed.

## Git and PR workflow

No backend-specific rules — see [AGENTS.md](../AGENTS.md).
