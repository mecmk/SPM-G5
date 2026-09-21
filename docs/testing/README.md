# Testing guide

How to write, run and trace tests in ConnectSphere. The grading rubric asks for tests that
are *traceable* to stories and acceptance criteria and that cover normal, boundary, conflict and
failure cases, so the conventions below exist to make that cheap.

## Three layers

| Layer | Tool | Where | Runs against |
| --- | --- | --- | --- |
| Backend unit + API | pytest + FastAPI `TestClient` | `backend/tests/` | A throw-away `connectsphere_test` database rebuilt from migrations + seed each run, each test rolled back |
| Frontend build/lint | tsc + oxlint | `frontend/` | - |
| End-to-end | Playwright | `tests/e2e/` | A throw-away `connectsphere_e2e` database and its own servers, all started and removed by `npm run test:e2e` |

```powershell
npm run test:backend   # pytest
npm run test:trace     # pytest + writes docs/testing/TRACEABILITY.md
npm run test:frontend  # lint + type-check/build
npm run test:e2e       # rebuilds connectsphere_e2e, starts its own API + app, runs Playwright, cleans up
```

## Backend tests

### Layout mirrors the app

```text
backend/app/auth/...        <->  backend/tests/auth/test_login_logout.py, test_rbac.py
backend/app/venues/...      <->  backend/tests/venues/test_venue_records.py
backend/db/migrations/...   <->  backend/tests/test_schema.py
backend/tests/support/      seed constants + factories shared by all tests
backend/tests/conftest.py   fixtures + traceability plugin
```

One test file per story (or per closely related pair). Start the file with the story title and
its acceptance criteria copied from the backlog; name each test after the behaviour it proves.

### Fixtures you get for free

| Fixture | Gives you |
| --- | --- |
| `db` | SQLAlchemy `Session` inside a transaction that is rolled back after the test. Seed data is present. |
| `client` | `ApiClient` (a `TestClient`) wired to that same transaction. `client.login(Users.VENUE_STAFF)` / `client.logout()`. |
| `venue_staff_client`, `coordinator_client`, `organiser_client`, `tech_client`, `attendee_client` | `client` already signed in as that seed user. |
| `login_as` | Factory: `login_as(Users.COORDINATOR_2)`. |
| `engine` | Session-scoped engine for catalog inspection. |

**Time stands still inside a test.** PostgreSQL's `now()` is fixed for the whole transaction, so
every `created_at` / `updated_at` a test creates (and any the `set_updated_at` trigger stamps on an
update) is the same instant. A test of ordering by time must set the timestamps itself
(`make_event(db, updated_at=...)`); the trigger only fires on UPDATE, so an explicit value on insert
is kept. See `tests/events/test_my_event_requests.py`.

Seed rows have fixed IDs; refer to them through `tests/support/seed.py`
(`Users.COORDINATOR`, `Venues.GRAND_HALL`, `Events.APPROVED`, ...). Need something the seed
does not have? Use `tests/support/factories.py` (`make_user`, `make_venue`, `venue_payload`).

### Mark every test with its story

```python
@pytest.mark.story("8.3", ac=3)
def test_capacity_rejects_zero(venue_staff_client): ...
```

Multiple markers are fine when one test proves several ACs. `npm run test:trace` turns the
markers into `docs/testing/TRACEABILITY.md` - a story/AC -> test -> result table you can drop
straight into the Week 12 submission (deliverable 3). CI uploads it as an artifact on every PR.

### Pattern

```python
"""Story 4.5 - be: reject event request with reason.

AC1 A reason must be provided when rejecting.
...
"""


@pytest.mark.story("4.5", ac=1)
def test_rejection_without_reason_is_refused(coordinator_client):
    response = coordinator_client.post(f"/events/{Events.SUBMITTED}/reject", json={})
    assert response.status_code == 422
```

Cover, for each story: the happy path, each validation rule (boundary values), the
role/permission refusals (403 for other roles, 401 signed-out) and the conflict cases the
briefing cares about (double booking, over-committed equipment, ...).

### Database rules are tested too

`tests/test_schema.py` proves the schema story: required tables exist, every `*_id` column is a
real foreign key, the seed loads into an empty schema and is idempotent, ORM models match the
tables, and the DB-level guards (double-booking exclusion, mandatory fields once submitted) fire.

## End-to-end tests

One spec per story area lives in `tests/e2e/`, listed in [tests/README.md](../../tests/README.md).
Keep e2e specs to the flows a user would actually click through (login, role-gated navigation,
create/edit a venue, open one of my requests); put the detailed rule checks in backend tests where
they are fast and deterministic.

### Neither layer touches the development database

| | Database | Rebuilt | Guard |
| --- | --- | --- | --- |
| pytest | `connectsphere_test` (`TEST_DATABASE_URL`, default `<dev db>_test`) | Once per session; every test is rolled back | `conftest.py` exits if it would be the dev database |
| Playwright | `connectsphere_e2e` (`E2E_DATABASE_URL`) | Every `npm run test:e2e`; emptied afterwards | `scripts/e2e.mjs` refuses a name not ending `_e2e`; `tests/global-setup.ts` refuses to run at all without `E2E_ISOLATED_DB=1` |

Which command touches which database:

| Command | Database |
| --- | --- |
| `npm run test:backend`, `npm run test:trace` | `connectsphere_test` only |
| `npm run test:e2e` | `connectsphere_e2e` only |
| `npm run db:up`, `npm run db:down` | none — starts or stops the PostgreSQL container |
| `npm run db:status`, `npm run db:docs` | the development database, **read-only**. `db:docs` writes the generated data dictionary and ERD *from that schema*, so it is only as current as your dev database: run `db:reset` first if yours predates a schema change. The feature workflow's last step needs it |
| `npm run db:ready`, `db:reset`, `db:seed`, or a bare `python -m app.dbtool` | **the development database, and they change it** (`DATABASE_URL`). `reset` drops everything first. `--test` targets the test database instead |

Testing never needs the last row. Do not run it as part of a test workflow, and do not run it on
someone's behalf without asking.

`npm run test:e2e -- e2e/venues.spec.ts` passes extra arguments to Playwright. Set `E2E_LOG_DIR` to a
folder to keep each server's output (`backend.log`, `frontend.log`) when a run needs debugging. The runner uses
`127.0.0.1` on API port `8001` and app port `5174` (override with `E2E_BACKEND_PORT` /
`E2E_FRONTEND_PORT`), so a dev stack on `8000` / `5173` can keep running; it stops if either port
is already taken, because the specs would otherwise talk to whatever is listening. It needs
PostgreSQL up (`npm run db:up`) but never opens the dev database.

Specs share one database within a run and run in parallel, so still give every record they create
a unique name (`E2E Room ${Date.now()}`). Nothing survives the run. Running `npm test` by hand
inside `tests/` is refused unless you set `E2E_ISOLATED_DB=1` to say the stack behind
`FRONTEND_URL` uses a disposable database. CI does, because its PostgreSQL service container is
discarded with the job.

## Continuous integration

`.github/workflows/backend-ci.yml` starts a PostgreSQL service, applies the migrations to an
empty database, runs pytest with `--traceability`, and uploads the matrix. `e2e.yml` does the
same and then runs Playwright. Both only run when relevant paths change.
