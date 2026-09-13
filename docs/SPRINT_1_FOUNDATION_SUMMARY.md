# Sprint 1 foundation - summary and next steps

Prepared for the ConnectSphere team (IS212 G5) on 2026-09-10 from Joshua's Sprint 1 stories.
Everything below is on the branch `story/1-database-schema` (created from `sprint/1`),
**uncommitted**, so it can be reviewed and split into per-story PRs.

## What was delivered

| Story | Title | Status | Where |
| --- | --- | --- | --- |
| 1 | chore: set up database schema | Done | `backend/db/migrations/001_initial_schema.sql`, `backend/db/seed/*.sql`, `backend/app/dbtool/`, `docs/database/` |
| 1.1 | fe/be: implement user login and logout | Done | `backend/app/auth/`, `frontend/src/auth/`, `tests/e2e/auth.spec.ts` |
| 1.2 | fe/be: enforce role-based access control | Done | `backend/app/auth/permissions.py`, `deps.py`, `frontend/src/auth/RequireAuth.tsx`, `layout/AppLayout.tsx` |
| 8.3 | fe/be: create and update venue records | Done | `backend/app/venues/`, `frontend/src/venues/`, `tests/e2e/venues.spec.ts` |
| 12.1 | fe/be: raise venue booking request | **Skipped - blocked** | see "Story 12.1" below |

### Acceptance criteria evidence

Run `npm run test:trace` and open `docs/testing/TRACEABILITY.md`: every automated test is
tagged with the story and AC it proves. Current state:

| Suite | Result |
| --- | --- |
| Backend (pytest, real PostgreSQL) | 114 passed |
| End-to-end (Playwright) | 14 passed |
| Backend lint/format (ruff), frontend lint/format/build (oxlint, prettier, tsc), markdownlint | clean |

Story 1 AC3 ("schema can be populated with sample data without integrity errors") is proven by
`tests/test_schema.py::test_seed_loads_into_empty_schema_without_integrity_errors`.

## The three artefacts you asked for

1. **Data dictionary** - `docs/database/DATA_DICTIONARY.md`. Generated from the `COMMENT ON`
   text in the SQL, so it can never drift from the real schema. Regenerate with `npm run db:docs`.
2. **ERD (Excalidraw)** - `docs/database/ERD.excalidraw`. Also generated; open it at
   <https://excalidraw.com> (File > Open) or with the VS Code Excalidraw extension. Boxes are
   grouped and coloured by domain; drag them freely, arrows stay attached (crow's-foot = many side).
3. **SQL schema** - `backend/db/migrations/001_initial_schema.sql` (28 tables covering all 20
   core features, not just Sprint 1) plus idempotent seed files.

## Running it locally

`npm run setup` installs every package, and installs uv first if it is missing. With Docker
Desktop open, `npm run db:ready` runs `docker compose up -d`, creates the database if missing,
applies pending migrations (refusing if an applied file was edited - "drift"), re-runs the seed
upserts and verifies key tables are populated. It is safe to run every day; it never duplicates
data. `npm run dev` then starts backend + frontend. Docker Desktop and DBeaver are installed by
hand (see the README prerequisites).

### Save state vs fresh rebuild - the recommendation

Keep state by default, reset on demand:

- Migrations apply once and are tracked with a checksum, so local data survives restarts.
- Seed files are `INSERT ... ON CONFLICT DO UPDATE` with fixed UUIDs, so the canonical sample
  rows are healed on every start without touching rows you created.
- `npm run db:reset` drops everything and rebuilds when you want a clean slate (Sprint 1
  schema edits require it; the tool tells you).
- Tests always build their own `connectsphere_test` database and roll back after every test,
  so they are deterministic and never touch dev data.

## Design decisions worth explaining in the Week 13 Q&A

- **Plain SQL migrations + generated docs** instead of an ORM-first/Alembic approach: readable
  by everyone, and the comments are the documentation. Alembic can be adopted later.
- **UUID keys with fixed seed IDs** so tests read as `Venues.GRAND_HALL`, and merges of
  teammates' sample data never collide.
- **`text` + `CHECK` statuses, reference tables for lists** because the customer said the
  process and lists will evolve; both change without rebuilding anything.
- **Single `events` row across the whole lifecycle** with `event_status_history`,
  `event_clarifications`, `event_coordinator_assignments`, `event_change_requests` alongside,
  so the "several versions of the same event" pain point cannot recur.
- **Double-booking impossible at the database level** (`EXCLUDE USING gist` on approved
  bookings over the held period, half-open so back-to-back bookings are fine) - story 14.2's
  service check reports the conflict nicely, the constraint guarantees it under concurrency.
- **Held period includes setup/teardown** (trigger-maintained `held_from`/`held_until`) so
  turnaround time is built in from day one (story 12.2).
- **Sessions in the database, hashed token in an HttpOnly cookie**: logout genuinely
  invalidates (1.1 AC5), deactivating a user kills their session, no JWT library needed.
- **Permission matrix in code** (`app/auth/permissions.py`) with a test that every role and
  every permission is covered; relationship rules ("only my events") live in feature services.
- **Docker Postgres on host port 5433**: a locally installed PostgreSQL was silently answering
  on 5432 on Joshua's machine and would do the same on any teammate's laptop that has one.

## Story 12.1 - why it was skipped, and the corrected dependencies

The backlog lists 12.1 as depending on 4.4, 5.1 and 8.2. Verified against the ACs:

| Listed dependency | Owner | Real dependency? | Why |
| --- | --- | --- | --- |
| 4.4 approve event request | Cassia | **Yes** | AC1: a request can be raised only from an *approved* event |
| 5.1 assign coordinator | Amanda | **Yes** | AC4: only the *assigned* coordinator may raise it |
| 8.2 display venue characteristics | Warren | **No** | 12.1's backend needs venue *records* (8.3, done), not the display page |
| 2.1 capture event details (not listed) | Matthew | **Yes** | there must be an event to book for; the request copies its date/time/attendance |

So 12.1 genuinely waits on 2.1, 4.4 and 5.1. What is already in place for it: the
`venue_bookings` table (with `PENDING` status, requester, held period, layout/requirement
fields), the `bookings:request` permission granted to coordinators, and seed data containing an
approved event with an assigned coordinator and one pending booking. Once 2.1/4.4/5.1 land,
12.1 is a router + service + form on top of that.

## Decisions the team should confirm (made unilaterally to keep moving)

1. `react-router` v7 was added to the frontend - the only new dependency. CONTRIBUTING asks to
   check before adding one; please confirm at the next stand-up.
2. Docker host port moved from 5432 to 5433 (`docker-compose.yml`, `backend/.env.sample`,
   default in `config.py`). Existing `backend/.env` files need the port updated.
3. Password hashing uses scrypt from the Python standard library (no `bcrypt`/`argon2`
   dependency). The hash string is self-describing, so the algorithm can change later.
4. `.information/` (customer briefing, backlog export) is now listed in `.gitignore`.
5. Every root npm script reaches uv through `scripts/uv.mjs`, which installs uv if it is
   missing, so uv no longer has to be on PATH.

## Next steps for the team

### Joshua (this branch)

1. Review the diff, then split into PRs against `sprint/1` in this order so each is reviewable:
   `chore: set up database schema (1)` -> `feat: user login and logout (1.1)` ->
   `feat: role-based access control (1.2)` -> `feat: create and update venue records (8.3)`.
   The auth/venue PRs depend on the schema PR.
2. Update `backend/.env` on your machine to port 5433 (the sample is already updated).
3. Mark 1, 1.1, 1.2, 8.3 as "In Review" on the Sprint 1 sheet; move 12.1 to "Blocked" with
   the corrected dependencies above.

### Everyone, before starting a story

1. `git checkout sprint/1 && git pull`, then `npm run setup` (after package changes),
   `npm run db:ready` and `npm run dev` (daily).
2. Read `docs/database/README.md` (5 min), `docs/testing/README.md` (5 min) and the
   "Adding a feature" checklist at the end of `docs/ARCHITECTURE.md`.
3. Use the seed accounts (password `Password123!`) - one per role - for manual testing.

### Per teammate, how the foundation maps to your Sprint 1 stories

| Person | Stories | Ready-made pieces |
| --- | --- | --- |
| Matthew | 2.1, 2.6, 5.3, 13.3 | `events`, `event_required_facilities`, `event_accessibility_needs`, `event_equipment_requests` tables; `events:create` / `events:read_own` permissions; `Events.*` seed constants; `venue_bookings.decision_reason` + `alternative_suggestion` for 13.3 |
| Cassia | 4.1, 4.4, 4.5, 4.6 | `events.status` CHECK with `SUBMITTED` / `UNDER_REVIEW` / `APPROVED` / `REJECTED`; `event_status_history`, `event_clarifications`; `events:review` permission; seed events in each state |
| Amanda | 5.1, 14.2 | `event_coordinator_assignments` (+ partial unique index for "one current"); `users:read_internal` to list coordinators; the exclusion constraint already blocks conflicting approvals - 14.2's service should query for the conflicting booking first and report it |
| Yu Bing | 7.1, 7.2, 13.1, 13.2 | `events` routine fields (`description`, `contact_*`, `internal_notes`); `bookings:decide` permission; seed pending booking `Bookings.PENDING_SEMINAR_ROOM` |
| Warren | 6.1, 8.1, 8.2, 9.1 | `GET /venues` and `GET /venues/{id}` already return everything 8.1/8.2 need (name, location, capacity, facilities, layouts, accessibility, operating hours, `status`); `venue_unavailability_periods` + approved bookings for 9.1 |

### Process suggestions for the sprint

- Add `docs/testing/TRACEABILITY.md` (regenerated by CI on every PR) to the sprint review.
- Keep migration edits to `001` during Sprint 1 and announce them in the group chat (everyone
  runs `npm run db:reset`). From Sprint 2, only new `NNN_*.sql` files.
- When a story adds a status value or reference item, update the seed / CHECK in the same PR
  and regenerate the docs (`npm run db:docs`) so the dictionary and ERD stay current.
- Consider a short "walk through the ERD" at the next sprint planning so everyone can explain
  the model in the Week 13 Q&A.

## File map of what changed

```text
backend/db/migrations/001_initial_schema.sql   schema (28 tables, comments, constraints, triggers)
backend/db/seed/010_reference_data.sql          roles, facilities, layouts, accessibility, equipment types
backend/db/seed/020_sample_data.sql             users per role, venues, events, bookings (fixed UUIDs)
backend/app/dbtool/                             migrate / seed / reset / ready / docs tool
backend/app/db.py, config.py, main.py           engine mixins, settings (5433, sessions), routers
backend/app/auth/                               passwords, models, service, deps, permissions, schemas, router
backend/app/venues/                             models, schemas, service, router
backend/app/common/audit.py                     audit log helper
backend/tests/                                  conftest (fixtures + traceability), support/, test_schema, auth/, venues/
frontend/src/api/{client,auth,venues}.ts        API layer
frontend/src/auth/                              AuthProvider, context, guards, LoginPage, homeFor
frontend/src/layout/AppLayout.tsx               header + permission-filtered nav
frontend/src/pages/HomePage.tsx                 role landing page
frontend/src/venues/                            VenueManagePage, VenueFormPage
tests/e2e/{support,auth,rbac,venues,health}.spec.ts
.github/workflows/{backend-ci,e2e}.yml          Postgres service, db ready, traceability artifact
docker-compose.yml, backend/.env.sample         port 5433
docs/database/{README,DATA_DICTIONARY}.md, ERD.excalidraw
docs/testing/{README,TRACEABILITY}.md
docs/ARCHITECTURE.md, README.md, AGENTS.md, backend/README.md, tests/README.md
package.json                                    db:*, test:trace scripts (uv via scripts/uv.mjs)
scripts/uv.mjs, scripts/lib/                    the uv wrapper
.gitignore                                      .information/ (customer briefing, backlog export)
```
