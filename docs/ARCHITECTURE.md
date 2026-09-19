# Architecture

High-level view of how the pieces of ConnectSphere connect: a React SPA talking to a REST API
backed by PostgreSQL.

```text
┌────────────┐        HTTP (JSON, REST)        ┌──────────────┐        SQL        ┌────────────┐
│   Browser  │ ───────────────────────────────▶ │   Backend    │ ─────────────────▶ │ PostgreSQL │
│  (React +  │   session cookie on every call   │  (FastAPI)   │                    │  database  │
│    Vite)   │ ◀─────────────────────────────── │              │ ◀───────────────── │            │
└────────────┘                                   └──────────────┘                    └────────────┘
```

- **Frontend** (`frontend/`): a React + TypeScript SPA built with Vite, styled with the plain-CSS design system
  from story c3.
  Sign-in (story 1.1), the role-based sidebar and main page (1.2) and venue management (8.3)
  are built; every other section a role can use is listed and opens a page naming its story.
  Feature pages live in `src/<feature>/`, with a matching `src/api/<feature>.ts`. See
  [frontend/CLAUDE.md](../frontend/CLAUDE.md).
- **Backend** (`backend/`): a FastAPI service structured **by feature area**
  (`app/auth/`, `app/venues/`, ...). Each area has `router.py` (HTTP), `service.py` (rules),
  `schemas.py` (request/response shapes) and `models.py` (SQLAlchemy models). `app/common/` holds
  cross-cutting helpers (audit log). `app/dbtool/` is the migration/seed/docs tool.
- **Database**: PostgreSQL 16, defined by plain SQL migrations in `backend/db/migrations` and
  seeded from `backend/db/seed`. See [database/README.md](database/README.md), the generated
  [data dictionary](database/DATA_DICTIONARY.md) and [ERD](database/ERD.excalidraw).
- **Tests**: pytest against a throw-away database (`backend/tests/`), Playwright end-to-end
  (`tests/e2e/`). See [testing/README.md](testing/README.md).

## Domain model (summary)

```text
roles ──< users >── client_organisations
            │
            ├──< user_sessions
            │
            ├──< events (organiser) ──< event_required_facilities >── facilities
            │        │                ──< event_accessibility_needs >── accessibility_features
            │        │                ──< event_equipment_requests >── equipment_types
            │        │                ──< event_status_history / event_clarifications
            │        │                ──< event_coordinator_assignments / event_change_requests
            │        │                ──< event_registrations >── users (attendee)
            │        │
            │        └──< venue_bookings >── venues ──< venue_facilities / venue_layouts /
            │                  │                        venue_accessibility_features /
            │                  │                        venue_unavailability_periods
            │                  └── (EXCLUDE: no two APPROVED bookings overlap on one venue)
            │
            └──< equipment_reservations >── equipment_types ──< equipment_unavailability_periods
                 notifications, audit_log (cross-cutting)
```

Every table carries a `Stories:` comment naming the backlog items it serves; the data dictionary
lists them.

## How a request flows (example: Venue Staff edits a venue)

1. The venue form (`frontend/src/venues/VenueFormPage.tsx`) calls `PATCH /venues/{id}` through
   `src/api/venues.ts`, with the session cookie set by `POST /auth/login`.
2. `app/auth/deps.py:get_current_user` resolves the cookie to a live row in `user_sessions`
   (rejects if missing, revoked or expired) -> 401.
3. `require_permission(Permission.VENUES_MANAGE)` checks the user's role against the matrix in
   `app/auth/permissions.py` -> 403 if not permitted (story 1.2).
4. `app/venues/router.py` validates the body with the Pydantic schema (positive whole-number
   capacity etc.) -> 422, then calls `app/venues/service.py:update_venue`.
5. The service applies the change, checks cross-field rules, writes an `audit_log` row in the
   same transaction and commits. Uniqueness is enforced by the database (409 on conflict).
6. The response is the full venue record. The frontend's API client reports the result to the
   notification centre, and a refusal arrives as an `ApiError` whose code comes from
   `frontend/src/errors/registry.ts`.

Relationship-based rules ("an organiser sees only their own events") belong in the feature's
service, next to the record they need - not in the permission matrix.

## Authentication & sessions (story 1.1)

- Passwords are hashed with scrypt (`app/auth/passwords.py`); only the hash is stored.
- Login creates a `user_sessions` row holding the SHA-256 of a random token; the token itself
  goes to the browser in an `HttpOnly`, `SameSite=Lax` cookie.
- Logout sets `revoked_at`; expired or revoked sessions are refused. Deactivating a user
  (`users.is_active = false`) kills their sessions immediately.
- `POST /auth/login` and `GET /auth/me` return the user with their permission list, so a client
  can hide navigation and actions the role cannot use (story 1.2 AC2). The backend re-checks every
  call.

## Adding a feature (checklist)

1. Schema: new migration or, in Sprint 1, edit `001` + `npm run db:reset`; add `COMMENT ON`;
   `npm run db:docs`.
2. Backend: `app/<feature>/{models,schemas,service,router}.py`; add the router in
   `app/main.py`; add permissions to `app/auth/permissions.py` if the story introduces new
   functions.
3. Tests: `backend/tests/<feature>/test_<story>.py` with `@pytest.mark.story(...)` markers.
4. Frontend, once UI work resumes: `src/api/<feature>.ts` and `src/<feature>/<Page>.tsx`, hiding
   anything the role lacks the permission for (see `frontend/CLAUDE.md`).
5. E2E: one Playwright spec for the user-visible flow.
