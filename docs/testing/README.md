# Testing guide

How to write, run and trace tests in ConnectSphere. The grading rubric asks for tests that
are *traceable* to stories and acceptance criteria and that cover normal, boundary, conflict and
failure cases, so the conventions below exist to make that cheap.

## Three layers

| Layer | Tool | Where | Runs against |
| --- | --- | --- | --- |
| Backend unit + API | pytest + FastAPI `TestClient` | `backend/tests/` | A throw-away `connectsphere_test` database rebuilt from migrations + seed each run |
| Frontend build/lint | tsc + oxlint | `frontend/` | - |
| End-to-end | Playwright | `tests/e2e/` | The running dev servers (`npm run dev`) and your dev database (`npm run db:ready`) |

```powershell
npm run test:backend   # pytest
npm run test:trace     # pytest + writes docs/testing/TRACEABILITY.md
npm run test:frontend  # lint + type-check/build
npm run test:e2e       # needs `npm run dev` running in another terminal
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

Seed rows have fixed IDs; refer to them through `tests/support/seed.py`
(`Users.COORDINATOR`, `Venues.GRAND_HALL`, `Events.APPROVED`, ...). Need something the seed
does not have? Use `tests/support/factories.py` (`make_user`, `make_venue`, `venue_payload`).

### Mark every test with its story

```python
@pytest.mark.story("8.3", ac=3)
def test_capacity_rejects_zero(venue_staff_client):
    ...
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

`tests/e2e/support.ts` has `signIn(page, ACCOUNTS.venueStaff)`. Keep e2e specs to the flows a
user would actually click through (login, role-gated navigation, create/edit a venue); put the
detailed rule checks in backend tests where they are fast and deterministic.

Because e2e runs against your dev database, use unique names (`E2E Room ${Date.now()}`) and
`npm run db:reset` when you want to clear the leftovers.

## Continuous integration

`.github/workflows/backend-ci.yml` starts a PostgreSQL service, applies the migrations to an
empty database, runs pytest with `--traceability`, and uploads the matrix. `e2e.yml` does the
same and then runs Playwright. Both only run when relevant paths change.
