# Database guide

How the ConnectSphere database is defined, evolved, seeded, documented and tested. Read this
before touching anything under `backend/db/`.

## Files

| Path | What it is |
| --- | --- |
| `backend/db/migrations/NNN_*.sql` | The schema, as plain PostgreSQL DDL. Applied once, in order. **Source of truth.** |
| `backend/db/seed/010_reference_data.sql` | Roles, facilities, room layouts, accessibility features, equipment types. Idempotent upserts. |
| `backend/db/seed/020_sample_data.sql` | Sample organisations, users (one per role), venues, events, bookings. Fixed UUIDs. Idempotent upserts. |
| `backend/app/dbtool/` | The tool behind every `npm run db:*` script (migrate / seed / reset / ready / docs). |
| `docs/database/DATA_DICTIONARY.md` | **Generated** from the live database (`COMMENT ON` text). Never edit by hand. |
| `docs/database/ERD.excalidraw` | **Generated** entity-relationship diagram. Open at <https://excalidraw.com> or with the VS Code *Excalidraw* extension. Boxes can be dragged; arrows stay attached. |
| `backend/app/<feature>/models.py` | SQLAlchemy models mirroring the tables the app code uses. A test fails if they drift from the SQL. |

## Day-to-day commands (repo root)

| Command | What it does |
| --- | --- |
| `npm run db:ready` | **The one to remember.** Starts Postgres in Docker, creates the DB if missing, applies pending migrations, re-runs the seed, verifies key tables have rows and prints the sample logins. Run it at the start of every session, then `npm run dev`. |
| `npm run db:status` | Which migrations are applied / pending / edited-after-apply ("drifted"). |
| `npm run db:reset` | Drop every object in the **local** database and rebuild from migrations + seed. Refuses to run against a non-localhost URL. |
| `npm run db:seed` | Re-run the seed files only. |
| `npm run db:docs` | Regenerate the data dictionary and ERD from the live database. |
| `npm run db:down` | Stop the Postgres container (data is kept in the Docker volume). |

Under the hood these call `python -m app.dbtool <command>` through `scripts/uv.mjs`, which finds
uv even when it is not on PATH and installs it when it is missing. From `backend/` you can run
`uv run python -m app.dbtool <command>` directly. Add `--test` to target the test database, or
`--url ...` for any other.

## Viewing the data

Install DBeaver Community, a free desktop database viewer, with
`winget install -e --id DBeaver.DBeaver.Community` or from <https://dbeaver.io/download/>. MySQL
Workbench cannot open PostgreSQL. In DBeaver, create a PostgreSQL connection with:

| Setting | Value |
| --- | --- |
| Host | `localhost` |
| Port | `5433` |
| Database | `connectsphere` |
| Username | `connectsphere` |
| Password | `connectsphere` |

Use port 5433, not 5432. A PostgreSQL service installed directly on a laptop usually owns 5432
and rejects these credentials. For a quick look without a GUI, run
`docker compose exec db psql -U connectsphere -d connectsphere` from the repo root.

Ignore the `connectsphere_test` database. The backend tests delete and rebuild it on every run.

## Save state or fresh rebuild?

Both, deliberately:

- **Migrations are applied once and tracked** in `schema_migrations` (with a checksum), so your
  local data survives `npm run db:ready` day to day. Rows you add while developing stay.
- **Seed files are idempotent upserts**, so every `npm run db:ready` re-asserts the canonical
  sample rows (fixed UUIDs) without duplicating them or touching yours. If you mangle a sample
  venue, the next run heals it.
- **`npm run db:reset`** gives you a clean slate whenever you want one.
- **Tests never use your dev database.** `backend/tests/conftest.py` drops and rebuilds
  `connectsphere_test` from the same migrations + seed on every run, and wraps each test in a
  transaction that is rolled back.

## Changing the schema

### Sprint 1 (now)

`001_initial_schema.sql` may be edited in place. After editing:

```powershell
npm run db:reset      # the tool notices the checksum changed and refuses `ready` until you do this
```

Then update the matching SQLAlchemy model (`backend/app/<feature>/models.py`) and run
`npm run test:backend` - `test_orm_models_match_database` tells you if they disagree.

### Sprint 2 onwards

Once teammates have applied `001` you must **not** edit it. Add a new file:

```text
backend/db/migrations/002_add_event_categories.sql
```

containing only the change (`ALTER TABLE ...`, `CREATE TABLE ...`, plus `COMMENT ON` for every
new table/column). `npm run db:ready` applies it on every machine. Then `npm run db:docs` and
commit the regenerated dictionary + ERD with the migration.

### Changing an allowed status value

Statuses are `text` columns with named `CHECK` constraints (not Postgres ENUMs) precisely so
this is easy:

```sql
ALTER TABLE events DROP CONSTRAINT ck_events_status;
ALTER TABLE events ADD CONSTRAINT ck_events_status CHECK (status IN ('DRAFT', ..., 'NEW_VALUE'));
```

### Adding reference values (facilities, layouts, equipment types, ...)

Edit `backend/db/seed/010_reference_data.sql`. No migration needed. The next `npm run db:ready`
upserts it, and `npm run db:docs` lists it in the dictionary.

### Adding sample rows

Edit `backend/db/seed/020_sample_data.sql` using the fixed-UUID convention at the top of the
file, and mirror any row tests need in `backend/tests/support/seed.py`. Keep every statement an
`INSERT ... ON CONFLICT ... DO UPDATE` so re-running stays safe.

## Design decisions (and why)

| Decision | Reason |
| --- | --- |
| Plain SQL migrations instead of Alembic | Everybody can read SQL; no extra tool to learn; the `COMMENT ON` text doubles as the data dictionary. Alembic can be adopted later if autogeneration becomes worth it. |
| UUID primary keys | Fixed, readable IDs in seed data and tests; no collisions when teammates merge sample rows. |
| `text` + `CHECK` for statuses | ENUM values can never be removed; a CHECK is replaced in one statement. |
| Reference tables for facilities / layouts / accessibility / equipment types / roles | The customer said these lists will grow; adding a value is data, not a schema change. |
| One `events` row for the whole lifecycle (draft to completed) | Status history lives in `event_status_history`; nothing is copied between "request" and "event" tables, so information can never diverge (a pain point in the briefing). |
| `venue_bookings` exclusion constraint on APPROVED bookings | Story 14.2: the database itself makes double-booking impossible, even under concurrent requests. Half-open ranges mean back-to-back bookings are fine (14.1 AC3). |
| Held period = event time + setup/teardown (`held_from`/`held_until`, trigger-maintained) | Story 12.2 and the briefing's turnaround-time concern, without every query re-deriving it. |
| Pooled equipment stock per type, not per unit | Matches how the backlog phrases availability ("quantity available for a period"). Per-unit tracking can be added as a child table later. |
| `audit_log` with JSONB details | Auditability requirement; any entity can be audited without new tables. |
| Docker host port **5433** | A locally installed PostgreSQL commonly occupies 5432 and silently hijacks connections (that happened during setup). |

## Sample logins

All passwords are `Password123!`.

| Role | Email |
| --- | --- |
| Event Organiser | `organiser@acme.example`, `organiser@nimbus.example` |
| Event Coordinator | `coordinator@connectsphere.example`, `coordinator2@connectsphere.example` |
| Venue Staff | `venue@connectsphere.example` |
| Technical Support Staff | `tech@connectsphere.example` |
| Attendee | `attendee@example.com` |
| (inactive, for tests) | `inactive@connectsphere.example` |
