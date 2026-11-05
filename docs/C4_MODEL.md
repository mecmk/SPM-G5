# C4 model

How ConnectSphere is put together, described with the [C4 model](https://c4model.com): context,
containers, components, plus a dynamic and a deployment view. The scope is the **first release**,
the 20 core features listed in the Week 4 project instructions.

This file is written by hand. The data dictionary and ERD under `docs/database/` are generated
from the live schema and describe the data; this file describes the software.

## How to read it

- Each component names the package that implements it, such as `app/bookings`. A component with
  no package yet names the epics it serves instead: the backlog asks for it and the database
  already has its tables, but no application code exists. The schema deliberately runs ahead of
  the code, so a table is not evidence of a feature.
- Which stories are done is tracked in the backlog, not here. This file changes when a feature
  area, a container or a responsibility does.
- Diagrams are Mermaid flowcharts drawn in C4 notation, which lay out more cleanly than
  Mermaid's own C4 diagrams. Dark blue is a person inside ConnectSphere Event Services and grey
  one outside it; blue is the software system and its containers; light blue is a component of
  the container being zoomed into, and light grey anything outside that zoom. A dashed line is a
  boundary, and an arrow from a boundary applies to everything inside it.
- GitHub renders the diagrams in place. In VS Code, use the Markdown Preview Mermaid Support
  extension. To move things around visually, paste a diagram into
  [mermaid.live](https://mermaid.live), then copy the text back.

## Level 1: system context

Who uses ConnectSphere and what they use it for. The first release has no external system
dependencies: notifications are in-app only, and there is no e-mail, calendar or payment
integration.

```mermaid
flowchart TB
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef external fill:#686868,stroke:#4d4d4d,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff

    organiser(["<b>Event Organiser</b><br/><i>[Person, external]</i><br/>A client's contact, who<br/>requests an event and<br/>follows its progress"]):::external
    attendee(["<b>Attendee</b><br/><i>[Person, external]</i><br/>Signs up for a<br/>confirmed event"]):::external

    lead(["<b>Event Coordinator Lead</b><br/><i>[Person, internal]</i><br/>Gives each submitted<br/>request a coordinator;<br/>watches the workload"]):::person
    coordinator(["<b>Event Coordinator</b><br/><i>[Person, internal]</i><br/>Owns the planning<br/>of one event"]):::person
    venueStaff(["<b>Venue Staff</b><br/><i>[Person, internal]</i><br/>Keeps the venue catalogue<br/>accurate and decides<br/>booking requests"]):::person
    techStaff(["<b>Technical Support Staff</b><br/><i>[Person, internal]</i><br/>Looks after equipment<br/>and decides what can<br/>be reserved"]):::person
    safetyOfficer(["<b>Safety Officer</b><br/><i>[Person, internal]</i><br/>Checks an event is<br/>safe to run"]):::person

    connectsphere["<b>ConnectSphere</b><br/><i>[Software system]</i><br/>Event requests, review,<br/>venue bookings and<br/>equipment, safety checks,<br/>registration and<br/>notifications"]:::system

    organiser -->|"Submits requests, answers<br/>clarifications, asks for<br/>changes, cancels"| connectsphere
    attendee -->|"Registers for an event,<br/>withdraws"| connectsphere
    lead -->|"Assigns and reassigns<br/>events"| connectsphere
    coordinator -->|"Reviews requests, books<br/>venues, orders equipment,<br/>confirms events"| connectsphere
    venueStaff -->|"Maintains venues,<br/>approves or rejects<br/>bookings"| connectsphere
    techStaff -->|"Accepts or declines<br/>equipment, records units<br/>out of service"| connectsphere
    safetyOfficer -->|"Approves an event, or<br/>sends it back for changes"| connectsphere
```

## Level 2: containers

The parts that run separately and how they talk to each other.

```mermaid
flowchart TB
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef external fill:#686868,stroke:#4d4d4d,color:#ffffff
    classDef container fill:#2e77bc,stroke:#1f5a91,color:#ffffff

    organiser(["<b>Event Organiser</b><br/><i>[Person, external]</i>"]):::external
    staff(["<b>ConnectSphere staff</b><br/><i>[Person, internal]</i><br/>Every internal role"]):::person
    attendee(["<b>Attendee</b><br/><i>[Person, external]</i>"]):::external

    subgraph connectsphere["<b>ConnectSphere</b> [system]"]
        spa["<b>Single-page application</b><br/><i>[Container: React 19,<br/>TypeScript, Vite]</i><br/>Role-aware pages, one<br/>area per feature. A page<br/>is listed once a story<br/>delivers it"]:::container
        api["<b>API application</b><br/><i>[Container: Python 3.12,<br/>FastAPI, Uvicorn]</i><br/>REST endpoints, sessions,<br/>role checks and every<br/>business rule, plus a<br/>timer that expires<br/>lapsed venue holds.<br/>OpenAPI docs at /docs"]:::container
        db[("<b>Database</b><br/><i>[Container: PostgreSQL 16]</i><br/>Users and sessions,<br/>events, venues, bookings,<br/>equipment, registrations,<br/>notifications, audit log")]:::container
        uploads["<b>Upload storage</b><br/><i>[Container: folder on<br/>disk, UPLOAD_DIR]</i><br/>Event cover pictures<br/>and venue pictures"]:::container
        dbtool["<b>Schema and seed tool</b><br/><i>[Container: Python CLI,<br/>app.dbtool]</i><br/>Applies SQL migrations,<br/>loads reference and<br/>sample data, regenerates<br/>the data dictionary<br/>and the ERD"]:::container
    end

    organiser -->|"Uses<br/>[HTTP]"| spa
    staff -->|"Uses<br/>[HTTP]"| spa
    attendee -->|"Uses<br/>[HTTP]"| spa
    spa -->|"Calls<br/>[JSON over HTTP,<br/>session cookie]"| api
    api -->|"Reads and writes<br/>[SQLAlchemy 2<br/>over psycopg 3]"| db
    api -->|"Writes and serves<br/>pictures<br/>[files, /uploads/]"| uploads
    dbtool -->|"Creates the schema,<br/>seeds data<br/>[SQL and DDL]"| db

    style connectsphere fill:none,stroke:#666666,stroke-dasharray:6 4
```

Each container in one line:

| Container | Technology | Responsibility |
| --- | --- | --- |
| Single-page application | React 19, TypeScript, Vite on port 5173 | Shows each role only what its permissions allow. Holds no rules of its own |
| API application | FastAPI on port 8000 | Every rule and every access decision. One module per feature area, plus the timer that expires lapsed venue holds |
| Database | PostgreSQL 16 on port 5433 | The single copy of event, venue, equipment and registration data. Enforces the rules that must never be broken |
| Upload storage | A folder on disk, `UPLOAD_DIR` (`backend/uploads` by default) | Event cover pictures and venue pictures, written by the API and served at `/uploads/events/` and `/uploads/venues/` |
| Schema and seed tool | `python -m app.dbtool` | Migrations, seed data, and the generated data dictionary and ERD |

## Level 3: components of the API application

Inside the API application. Each feature area is one package with the same four files: a router
for HTTP, a service for rules, schemas for request and response shapes, and models for tables.
`app/main.py` registers every area's routers, so a request from the single-page application lands
in its area's `router.py`. The three workflows that act on an event across areas (safety check,
change requests, cancellations) are the darker blue, and every area uses the same shared
services.

```mermaid
flowchart TB
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef workflow fill:#5d9fe0,stroke:#3f78b3,color:#000000
    classDef outside fill:#e6e6e6,stroke:#b3b3b3,color:#333333

    spa["<b>Single-page application</b><br/><i>[Container: React 19]</i>"]:::outside

    subgraph api["<b>API application</b> [container]"]
        subgraph areas["<b>Feature areas</b>"]
            safety["<b>Safety check</b><br/><i>[app/safety]</i><br/>The officer's decision;<br/>confirming the event"]:::workflow
            changes["<b>Change requests</b><br/><i>[app/change_requests]</i><br/>Approving one applies<br/>the change"]:::workflow
            cancellations["<b>Cancellations</b><br/><i>[app/cancellations]</i><br/>Releases everything a<br/>cancelled event holds"]:::workflow
            coordination["<b>Coordination</b><br/><i>[app/coordination]</i><br/>The Lead's queue,<br/>assigning, reassigning"]:::component
            registrations["<b>Registrations</b><br/><i>[app/registrations]</i><br/>Attendees register and<br/>withdraw; the list"]:::component
            equipment["<b>Equipment</b><br/><i>[app/equipment]</i><br/>Requests, unit holds,<br/>Technical Support's<br/>queue and schedule"]:::component
            bookings["<b>Venue bookings</b><br/><i>[app/bookings]</i><br/>Requests, holds,<br/>decisions, conflicts,<br/>hold expiry"]:::component
            events["<b>Events</b><br/><i>[app/events]</i><br/>Requests, review, status,<br/>details and edits"]:::component
            venues["<b>Venues</b><br/><i>[app/venues]</i><br/>Catalogue, search,<br/>calendar, closures,<br/>room layouts"]:::component
        end
        timer["<b>Hold timer</b><br/><i>[asyncio task,<br/>app/main.py]</i><br/>Expires lapsed holds,<br/>warns coordinators first"]:::component
        subgraph shared["<b>Shared by every area</b>"]
            access["<b>Access control</b><br/><i>[app/auth]</i><br/>Sessions and permissions;<br/>answers 401 and 403"]:::component
            notifications["<b>Notification service</b><br/><i>[app/notifications]</i><br/>One notice per action,<br/>never to whoever acted"]:::component
            audit["<b>Audit log writer</b><br/><i>[app/common/audit.py]</i><br/>Who changed what, when,<br/>in the same transaction"]:::component
            session["<b>Database session</b><br/><i>[app/db.py]</i><br/>Engine, session factory,<br/>one session per request"]:::component
        end
    end

    db[("<b>Database</b><br/><i>[Container: PostgreSQL 16]</i>")]:::outside

    spa -->|"JSON over HTTP,<br/>session cookie"| areas
    safety -->|"confirms, or returns<br/>to Planning"| events
    changes -->|"applies an approved<br/>change to"| events
    cancellations -->|"cancels, releasing<br/>what it holds"| events
    coordination -->|"assigns a coordinator to"| events
    registrations -->|"registers attendees for"| events
    equipment -->|"holds units for"| events
    bookings -->|"books venues for"| events
    bookings -->|"checks hours and<br/>closures in"| venues
    timer -->|"sweep_holds()"| bookings
    areas -->|"require_permission(),<br/>notify(), record_audit(),<br/>get_db()"| shared
    timer -->|"opens its own session"| session
    session -->|"SQL over psycopg 3"| db
    events ~~~ notifications
    venues ~~~ audit

    style api fill:none,stroke:#666666,stroke-dasharray:6 4
    style areas fill:none,stroke:#888888,stroke-dasharray:3 3
    style shared fill:none,stroke:#888888,stroke-dasharray:3 3
```

Arrows show the main calls. The code has more: the workflows also release bookings, equipment and
registrations in their own areas, the notification service reads back into the areas to work out
where each notice opens, and venues, bookings and events read one another. The queue search and
the phone number rule in `app/common` are left out.

What each component does:

| Component | Package | Responsibility |
| --- | --- | --- |
| App entry point | `app/main.py` | Creates the FastAPI app, applies CORS, registers every feature area's routers, serves `GET /health` |
| Hold timer | `app/main.py` | Runs `bookings/service.py::sweep_holds` every `HOLD_SWEEP_INTERVAL_SECONDS` with its own session: warns coordinators of holds about to expire, then expires the lapsed ones |
| Safety check | `app/safety`, epic 21 | The Safety Officer's queue of events awaiting the operational safety check, and each event's safety facts: attendance, approved venues judged against their capacity in the booked layout, accessibility needs, accepted equipment, previous reviews and what changed since the latest. The coordinator's request for a review once every arrangement is secured, the officer's decision against the review factors with findings of what must change, and confirming an approved event no change request has been approved since |
| Change requests | `app/change_requests`, epic 19 | An organiser's requested changes to an approved event, one pending per field, and their withdrawal; the assigned coordinator's queue of them and decision on each. Approving applies the change by the event's own rules, reused from `app/events`, releases only the bookings and equipment it affects, and returns an event past Planning to Planning for a new safety check. Before deciding, the coordinator sees the impact approving would have, worked out by the same rules and checked again when approving |
| Cancellations | `app/cancellations`, epic 6 | The organiser cancelling their own event with a reason. One transaction, under the event's row lock: its pending and approved bookings and its equipment holds are released, its open equipment items, registrations and pending change requests closed and kept for the record, and who cancelled it, when and why recorded. The coordinator (or the Lead, before one is assigned), the attendees, Venue Staff and Technical Support are told |
| Coordination | `app/coordination`, epic 5 | The Lead's unassigned queue and first assignment, the Lead's overview of every active event and each coordinator's workload, and the Lead's reassignment of an event to another coordinator |
| Events | `app/events`, epics 2, 3, 4, 6, 7 | Drafts, submission, event details and requirements, status transitions, routine edits. The review queue, clarification conversation, approve or reject. The equipment an event request asks for, and its hold on submission. An event's registration settings |
| Venue bookings | `app/bookings`, epics 12, 13, 14 | Booking requests and the venue hold, withdrawals, decisions with reasons, conflict detection over the held period. An approved booking's hold until its event is confirmed: the expiry Venue Staff set as they approve and their changes to it, and the sweep that warns coordinators and expires lapsed holds, run on the API's timer and before any answer a lapsed hold would change. The database completes the holds when an event becomes Confirmed |
| Registrations | `app/registrations`, epic 18 | The Confirmed, Public events taking registrations, each with its booked venues, places left and state for the attendee, and registering: the opening and closing times, capacity and one registration per attendee checked while holding the event's row, with the database's one-active-registration index behind it. An attendee's own registrations, one per event, and withdrawing one until the event starts, in one conditional update with its audit entry. An event's registration list for its organiser and assigned coordinator once past draft, a page at a time, with its active count against capacity read in the same statement, each Registered attendee's phone number and dietary requirements, and the events whose list they can pick. The attendee's own profile: their name, phone number and dietary requirements, saved on My profile or with a registration, which confirms them every time and must give them the first time |
| Equipment | `app/equipment`, epics 15, 16, 17 | The coordinator's equipment requests: recording items, holding their units, submitting them to Technical Support, and re-checking them when an event's dates change. Technical Support's queue of the requests sent to it, with what is available for each, and its decision on each: accepting keeps the hold as the reservation, declining releases it. The equipment catalogue and the units recorded out of service. Technical Support's schedule of every hold still to end, by equipment type, filtered by type and dates |
| Venues | `app/venues`, epics 8, 9, 10, 11 | Listing, searching, reading, creating, updating and deleting venues, each venue's availability calendar, the pick-list reference data, and the room layouts Venue Staff add, rename and delete. Venue rules: required fields, unique name, known reference codes, valid operating hours, and refusing to delete a venue that bookings still refer to; a room layout's unique name, and refusing to delete one still in use. Search and filter, and suitability against capacity, facilities and layout. Venue Staff's closures: a saved closure, once Venue Staff confirm the bookings listed, rejects the venue's pending requests it covers and cancels its approved bookings, returns their Confirmed events to planning and tells their people |
| Access control | `app/auth`, epic 1 | Sign-in and sign-out (`POST /auth/login`, `POST /auth/logout`, `GET /auth/me`), scrypt password hashing with constant-time verification, server-side sessions, the permission list per role, and the dependencies that answer 401 and 403 |
| Notification service | `app/notifications`, epic 20 | One notification per significant action, to the related users and never to whoever acted; each user's own list, which of its notifications are read, the unread count, and where opening each one goes for its reader |
| Audit log writer | `app/common/audit.py` | Appends who changed what and when, inside the caller's transaction |
| Database session | `app/db.py` | Engine, session factory and the per-request session |

## Level 3: inside venue bookings

One feature area drawn file by file, `app/bookings`, as the worked example; every other area has
the same shape. The router speaks HTTP, the service holds every rule, and the database has the last
word on double booking.

```mermaid
flowchart LR
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef outside fill:#e6e6e6,stroke:#b3b3b3,color:#333333

    spa["<b>Single-page application</b><br/><i>[Container: React 19]</i>"]:::outside

    subgraph pkg["<b>Venue bookings</b> [package: app/bookings]"]
        router["<b>Booking endpoints</b><br/><i>[router.py]</i><br/>Raise, approve, reject,<br/>withdraw, cancel, switch;<br/>service errors become 4xx"]:::component
        deps["<b>Lapsed-hold check</b><br/><i>[deps.py:<br/>ReleaseLapsedHolds]</i><br/>Sweeps before any answer<br/>a lapsed hold changes"]:::component
        schemas["<b>Request and reply shapes</b><br/><i>[schemas.py: Pydantic]</i><br/>A bad body gets 422<br/>before the service runs"]:::component
        service["<b>Booking service</b><br/><i>[service.py]</i><br/>Every booking rule;<br/>raises plain exceptions,<br/>never HTTP ones"]:::component
        model["<b>Booking model</b><br/><i>[models.py: SQLAlchemy]</i><br/>VenueBooking mirrors<br/>the venue_bookings table"]:::component
    end

    access["<b>Access control</b><br/><i>[app/auth/deps.py]</i><br/>Signed in and permitted,<br/>else 401 or 403"]:::outside
    events["<b>Events service</b><br/><i>[app/events]</i><br/>Venue requirements and<br/>the event's status"]:::outside
    venues["<b>Venue service</b><br/><i>[app/venues]</i><br/>Opening hours, closures,<br/>capacity and layouts"]:::outside
    notifications["<b>Notification service</b><br/><i>[app/notifications]</i><br/>Tells the people involved,<br/>never whoever acted"]:::outside
    audit["<b>Audit log writer</b><br/><i>[app/common/audit.py]</i><br/>Each decision and expiry,<br/>in the same transaction"]:::outside
    db[("<b>Database</b><br/><i>[Container: PostgreSQL 16]</i><br/>ex_venue_bookings_no_double_booking<br/>refuses overlapping holds;<br/>trg_events_complete_venue_holds<br/>completes holds on Confirmed")]:::outside

    spa -->|"JSON over HTTP<br/>/bookings/…"| router
    router -->|"guarded by<br/>require_permission()"| access
    router -->|"Depends()"| deps
    router -->|"delegates to"| service
    deps -->|"sweep_holds()"| service
    router -->|"validates with"| schemas
    service -->|"builds replies with"| schemas
    service -->|"reads and writes"| model
    service -->|"reads requirements<br/>and status"| events
    service --->|"checks hours<br/>and closures"| venues
    service --->|"notify()"| notifications
    service --->|"record_audit()"| audit
    model -->|"SQL over psycopg 3"| db

    style pkg fill:none,stroke:#666666,stroke-dasharray:6 4
```

The hold timer in `app/main.py` (the Level 3 view above) calls the same `sweep_holds()` as the
lapsed-hold check, on its own schedule. A hold ends one of two ways: the timer or the lapsed-hold
check expires it, or `trg_events_complete_venue_holds` completes it when its event becomes
Confirmed. The dynamic view of approving a booking, further down, shows the exclusion constraint
at work when two staff approve at once.

## Dynamic view: Venue Staff updates a venue

Story 8.3. It shows where each kind of refusal comes from, which is the same pattern every
feature follows.

```mermaid
sequenceDiagram
    autonumber
    actor VS as Venue Staff
    participant R as Venue endpoints
    participant A as Access control
    participant S as Venue service
    participant AU as Audit log writer
    participant DB as PostgreSQL

    VS->>R: PATCH /venues/{id} with the session cookie
    R->>A: Resolve the session, require the venue management permission
    A->>DB: Read the session and the user's role
    DB-->>A: Live session, or nothing
    A-->>R: The signed-in user, or 401 and 403
    R->>R: Validate the body, for example capacity is a positive whole number, else 422
    R->>S: update_venue
    S->>DB: Update the venue and replace its facilities, layouts and accessibility rows
    DB-->>S: Unique name accepted, or a conflict
    S->>AU: Record the change with the old and new values
    AU->>DB: Append to the audit log in the same transaction
    S-->>R: The saved venue, or 409 for a duplicate name
    R-->>VS: 200 and the full record
```

## Dynamic view: approving a venue booking

Stories 12.1, 13.2 and 14.2. It is drawn because it is the design decision most worth
explaining. A pending request already holds its venue, so an overlapping request is refused when
it is raised. At approval the database still has the last word: its exclusion constraint refuses
any two pending or approved bookings that overlap, even when two staff members approve at the same
moment, and the service turns that refusal into a readable conflict.

```mermaid
sequenceDiagram
    autonumber
    actor VS as Venue Staff
    participant R as Booking endpoints
    participant S as Booking service
    participant AU as Audit log writer
    participant DB as PostgreSQL

    VS->>R: POST /bookings/{id}/approve with the session cookie
    R->>S: Fetch the booking, locking its row against a racing decision
    S-->>VS: 409 if the request is no longer pending
    S->>DB: Set the booking to approved
    Note over DB: The exclusion constraint refuses any two<br/>pending or approved bookings that overlap
    alt The held period overlaps another booking
        DB-->>S: Rejected by the constraint
        S->>DB: Find the booking that holds the venue
        S-->>VS: 409 naming the event that already holds the venue
    else No overlap
        DB-->>S: Accepted
        S->>AU: Record the decision
        AU->>DB: Append to the audit log in the same transaction
        S-->>VS: 200 and the approved booking
    end
```

## Deployment view

The first release is coursework and runs locally. Nothing is hosted, so this view covers a
developer machine and the CI runner.

```mermaid
C4Deployment
    title Supplementary - Deployment on a laptop and in CI

    Deployment_Node(dev, "Developer laptop", "Windows, macOS or Linux") {
        Deployment_Node(browser, "Web browser", "Chromium, Firefox or Safari") {
            Container(spaD, "Single-page application", "Vite dev server, port 5173", "")
        }
        Deployment_Node(py, "Python process", "uv-managed virtual environment") {
            Container(apiD, "API application", "Uvicorn, port 8000", "")
        }
        Deployment_Node(docker, "Docker Desktop", "Container runtime") {
            ContainerDb(dbD, "Database", "PostgreSQL 16 container, host port 5433", "")
        }
    }

    Deployment_Node(ci, "GitHub Actions runner", "ubuntu-latest") {
        Container(ciJobs, "CI jobs", "pytest, ruff, Vite build, Playwright, pre-commit", "")
        ContainerDb(ciDb, "Service database", "PostgreSQL 16 service container", "")
    }

    Rel(spaD, apiD, "Calls", "JSON over HTTP")
    Rel(apiD, dbD, "Reads and writes", "psycopg")
    Rel(ciJobs, ciDb, "Rebuilds from the migrations and seed", "SQL")

    UpdateLayoutConfig($c4ShapeInRow="2", $c4BoundaryInRow="1")
```

Host port 5433 is deliberate. A PostgreSQL installed directly on a laptop usually holds 5432 and
would answer instead of the project's container.

## Core features mapped to components and tables

The 20 core features from the Week 4 instructions, the component that owns each one, the tables
behind it, and the package whose code implements it so far ("—" where there is none yet). Epic
numbers match the product backlog story IDs, so feature 8 is story 8.x.

| # | Core feature | Component | Main tables | Code |
| --- | --- | --- | --- | --- |
| 1 | User authorisation and authentication | Access control | `roles`, `users`, `user_sessions` | `app/auth` |
| 2 | Event request creation | Events | `events`, `venue_requirements`, `venue_requirement_facilities`, `event_accessibility_needs`, `event_equipment_requests` | `app/events` |
| 3 | Draft event requests | Events | `events` with status `DRAFT` | `app/events` |
| 4 | Event review and approval | Events | `events`, `event_status_history`, `event_clarifications` | `app/events` |
| 5 | Coordinator assignment | Coordination | `event_coordinator_assignments`, `events.assigned_coordinator_id` | `app/coordination` |
| 6 | Event status management | Events, Cancellations | `events.status`, `event_status_history`, the `events.cancelled_*` columns | `app/events`; `app/cancellations` for the organiser cancelling an event and releasing what it holds |
| 7 | Event information management | Events, Audit log writer | `events`, `event_change_history`, `audit_log` | `app/events`; `app/change_requests` records an approved change in the history |
| 8 | Venue catalogue | Venues | `venues`, `venue_facilities`, `venue_layouts`, `venue_accessibility_features`, `room_layouts`, `deleted_room_layouts` | `app/venues` |
| 9 | Venue availability calendar | Venues | `venue_unavailability_periods`, `venue_bookings` | `app/venues` |
| 10 | Venue search and filtering | Venues | `venues` and its join tables, `venue_bookings` | `app/venues` |
| 11 | Venue suitability checking | Venues | `venues.capacity`, venue join tables against event requirements | `app/venues`, as search filters |
| 12 | Venue booking request | Venue bookings | `venue_bookings`, including the link between a replaced booking and its replacement | `app/bookings` |
| 13 | Venue booking approval | Venue bookings | `venue_bookings` decision columns | `app/bookings` |
| 14 | Booking conflict detection | Venue bookings, plus a database exclusion constraint | `venue_bookings.held_from` and `held_until` | `app/bookings`, and the constraint |
| 15 | Equipment request management | Equipment | `event_equipment_requests`, `equipment_types` | `app/equipment`; `app/events` for requests made with an event |
| 16 | Equipment availability checking | Equipment | `equipment_types.total_quantity`, `equipment_reservations`, `equipment_unavailability_periods` | `app/events` for any dates; `app/equipment` for an event, counting what it holds |
| 17 | Equipment reservation | Equipment | `equipment_reservations` | `app/events` for the hold made on submission; `app/equipment` for the coordinator's holds and Technical Support's schedule of them |
| 18 | Attendee registration | Registrations | `event_registrations`, `event_registration_guests`, registration columns on `events`, and the attendee's `users.phone`, `users.dietary_requirements` and `users.attendee_details_confirmed_at` | `app/registrations`; `app/events` for an event's registration settings; `app/common/phone.py` for the phone number rule |
| 19 | Event change requests | Change requests | `event_change_requests` | `app/change_requests`; `app/events` for the point of contact updated directly and for applying an approved change; `app/bookings` and `app/equipment` for what an approval releases; `app/safety` refuses to confirm on a safety approval older than an approved change; `app/registrations` and `app/venues` read for the impact of a pending change |
| 20 | Notification system | Notification service | `notifications` | `app/notifications` |

Auditability runs across all of them. Every significant action appends to `audit_log` through one
writer, so no feature has to invent its own history.

## Decisions these diagrams encode

- **One module per feature area, not one per technical layer.** A story touches a single folder,
  which keeps parallel work in a six-person team from colliding.
- **Rules live in services, never in routers or the UI.** A router validates shapes and maps
  errors to status codes. The single-page application decides only what to show.
- **Role permissions are a list in code; relationship rules sit in services.** "Which role may
  book a venue" is a permission. "A coordinator sees only their own events" needs the record, so
  it belongs next to it.
- **The database enforces what must never break.** Two overlapping bookings that hold a venue,
  pending or approved, are impossible because of an exclusion constraint, not because the service
  remembered to check.
- **Sessions live in the database.** Logging out revokes the row, so a stolen cookie stops
  working immediately.
- **The schema covers the whole backlog, the code does not.** That keeps later stories from
  needing migrations that reshape existing tables.

## Keeping this file honest

Update it when you add a feature area, change a container or move a responsibility between
components. A new feature area is a node in the Level 3 diagram and a row in the table under it.
Nothing regenerates it. The checklist in [ARCHITECTURE.md](ARCHITECTURE.md) and
[AGENTS.md → Keeping Docs Current](../AGENTS.md#keeping-docs-current) list the other places a new
feature has to appear.
