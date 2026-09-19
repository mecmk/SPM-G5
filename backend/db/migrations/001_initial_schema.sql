-- =====================================================================
-- ConnectSphere Event Planning & Venue Booking System
-- Migration 001 - initial schema (Sprint 1, story 1 "chore: set up database schema")
--
-- HOW TO READ THIS FILE
--   * Every table and column carries a COMMENT. Those comments ARE the
--     data dictionary: `npm run db:docs` regenerates
--     docs/database/DATA_DICTIONARY.md and docs/database/ERD.excalidraw
--     straight from the live database, so keep the comments accurate.
--   * Each table comment starts with the backlog story IDs it serves
--     ("Stories: 1.1, 1.2") so code, schema and backlog stay traceable.
--   * Status columns are TEXT + CHECK constraints rather than Postgres
--     ENUMs. Changing an allowed value later is a one-line
--     `ALTER TABLE ... DROP CONSTRAINT / ADD CONSTRAINT` in a new
--     migration, whereas ENUM values can never be removed.
--   * Extensible lists (facilities, layouts, accessibility features,
--     equipment types, roles) are reference tables, seeded from
--     backend/db/seed/010_reference_data.sql, so the customer can add
--     values without a schema change.
--   * Primary keys are UUIDs (gen_random_uuid(), built into PG13+).
--     Seed data uses fixed, human-readable UUIDs so tests can refer to
--     rows by constant, and teammates' sample rows never collide.
--
-- CHANGE POLICY
--   Sprint 1: this file may be edited in place; run `npm run db:reset`
--   after editing (the tool detects the checksum change and tells you).
--   Sprint 2 onwards: never edit an applied migration - add
--   002_<change>.sql etc. so everyone's database evolves the same way.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS btree_gist;   -- venue double-booking exclusion constraint
CREATE EXTENSION IF NOT EXISTS citext;       -- case-insensitive e-mail addresses

-- ---------------------------------------------------------------------
-- Shared trigger: keep updated_at current on every UPDATE
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- =====================================================================
-- 1. IDENTITY & ACCESS  (stories 1.1 login/logout, 1.2 role-based access)
-- =====================================================================

CREATE TABLE roles (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    is_internal BOOLEAN NOT NULL,
    description TEXT
);
COMMENT ON TABLE roles IS
    'Stories: 1.2. The user roles named in the customer briefing. Reference table - the permission matrix for each role lives in backend/app/auth/permissions.py and can move here later if roles must become editable at runtime.';
COMMENT ON COLUMN roles.code IS 'Stable identifier used in code, e.g. EVENT_ORGANISER, VENUE_STAFF.';
COMMENT ON COLUMN roles.name IS 'Human-readable role name shown in the UI.';
COMMENT ON COLUMN roles.is_internal IS 'TRUE for ConnectSphere staff roles, FALSE for external users (organisers, attendees).';
COMMENT ON COLUMN roles.description IS 'What the role is responsible for (from the customer briefing).';

CREATE TABLE client_organisations (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL UNIQUE,
    contact_email CITEXT,
    contact_phone TEXT,
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE client_organisations IS
    'Stories: 2.x, 7.1 (organiser context). External client organisations that Event Organisers belong to. One organisation may have many organisers and many events.';
COMMENT ON COLUMN client_organisations.name IS 'Legal / trading name of the client organisation. Unique.';
COMMENT ON COLUMN client_organisations.contact_email IS 'General contact e-mail for the organisation (case-insensitive).';
COMMENT ON COLUMN client_organisations.contact_phone IS 'General contact phone number.';
COMMENT ON COLUMN client_organisations.notes IS 'Free-text internal notes about the client.';
COMMENT ON COLUMN client_organisations.created_at IS 'Row creation time.';
COMMENT ON COLUMN client_organisations.updated_at IS 'Last modification time (maintained by trigger).';

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           CITEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    full_name       TEXT NOT NULL,
    role_code       TEXT NOT NULL REFERENCES roles (code),
    organisation_id UUID REFERENCES client_organisations (id),
    phone           TEXT,
    department      TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_users_email_format CHECK (email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$')
);
COMMENT ON TABLE users IS
    'Stories: 1.1, 1.2. Every person who can sign in - internal staff and external organisers/attendees. A user holds exactly one role (the briefing describes users by a single role; switch to a user_roles join table if multi-role users are ever required).';
COMMENT ON COLUMN users.email IS 'Login identifier. Case-insensitive and unique.';
COMMENT ON COLUMN users.password_hash IS 'Salted password hash in the form "<algorithm>$<params>$<salt>$<hash>" (see backend/app/auth/passwords.py). Never plain text (story 1.1 AC3).';
COMMENT ON COLUMN users.full_name IS 'Display name.';
COMMENT ON COLUMN users.role_code IS 'FK -> roles.code. Drives role-based access control (story 1.2).';
COMMENT ON COLUMN users.organisation_id IS 'FK -> client_organisations.id. Set for Event Organisers; NULL for internal staff and attendees.';
COMMENT ON COLUMN users.phone IS 'Contact phone number (optional).';
COMMENT ON COLUMN users.department IS 'Internal staff only: department or team (optional).';
COMMENT ON COLUMN users.is_active IS 'FALSE blocks login without deleting history that references the user.';
COMMENT ON COLUMN users.created_at IS 'Row creation time.';
COMMENT ON COLUMN users.updated_at IS 'Last modification time (maintained by trigger).';

CREATE TABLE user_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    user_agent  TEXT
);
COMMENT ON TABLE user_sessions IS
    'Stories: 1.1. Server-side login sessions. The browser holds an opaque random token in an HttpOnly cookie; only its SHA-256 hash is stored here, so a database leak cannot be replayed. Logout sets revoked_at (story 1.1 AC5).';
COMMENT ON COLUMN user_sessions.user_id IS 'FK -> users.id. Owner of the session.';
COMMENT ON COLUMN user_sessions.token_hash IS 'SHA-256 hex digest of the session token held by the browser.';
COMMENT ON COLUMN user_sessions.created_at IS 'Login time.';
COMMENT ON COLUMN user_sessions.expires_at IS 'Hard expiry; the session is invalid after this instant even if not revoked.';
COMMENT ON COLUMN user_sessions.revoked_at IS 'Set on logout. NULL while the session is live.';
COMMENT ON COLUMN user_sessions.user_agent IS 'Browser user-agent string at login (troubleshooting aid).';
CREATE INDEX ix_user_sessions_user_id ON user_sessions (user_id);

-- =====================================================================
-- 2. REFERENCE LISTS shared by venues and events
-- =====================================================================

CREATE TABLE facilities (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 100
);
COMMENT ON TABLE facilities IS
    'Stories: 8.2, 8.3, 10.3, 11.1. Facilities a venue can offer and an event can require (projector, sound system, video conferencing, ...). Reference table maintained by seed data.';
COMMENT ON COLUMN facilities.code IS 'Stable identifier, e.g. PROJECTOR.';
COMMENT ON COLUMN facilities.name IS 'Display name.';
COMMENT ON COLUMN facilities.description IS 'Optional longer description.';
COMMENT ON COLUMN facilities.sort_order IS 'Display ordering in pick-lists (ascending).';

CREATE TABLE room_layouts (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 100
);
COMMENT ON TABLE room_layouts IS
    'Stories: 2.1, 8.2, 8.3, 12.1. Room layouts (theatre, classroom, boardroom, banquet, exhibition, ...) that a venue supports and an event may require.';
COMMENT ON COLUMN room_layouts.code IS 'Stable identifier, e.g. THEATRE.';
COMMENT ON COLUMN room_layouts.name IS 'Display name.';
COMMENT ON COLUMN room_layouts.description IS 'Optional longer description.';
COMMENT ON COLUMN room_layouts.sort_order IS 'Display ordering in pick-lists (ascending).';

CREATE TABLE accessibility_features (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 100
);
COMMENT ON TABLE accessibility_features IS
    'Stories: 2.1, 8.2, 8.3, 11.1. Accessibility features a venue provides and an event may need (wheelchair access, hearing loop, ...).';
COMMENT ON COLUMN accessibility_features.code IS 'Stable identifier, e.g. WHEELCHAIR_ACCESS.';
COMMENT ON COLUMN accessibility_features.name IS 'Display name.';
COMMENT ON COLUMN accessibility_features.description IS 'Optional longer description.';
COMMENT ON COLUMN accessibility_features.sort_order IS 'Display ordering in pick-lists (ascending).';

CREATE TABLE equipment_types (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code             TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    description      TEXT,
    total_quantity   INTEGER NOT NULL DEFAULT 0,
    storage_location TEXT,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_equipment_types_total_quantity CHECK (total_quantity >= 0)
);
COMMENT ON TABLE equipment_types IS
    'Stories: 2.1, 15.x, 16.x, 17.x. The equipment catalogue, modelled as pooled stock per type (e.g. 12 wireless microphones) rather than individually tracked items - this matches how the backlog talks about "quantity available for a period". Individual asset tracking can be added later as a child table.';
COMMENT ON COLUMN equipment_types.code IS 'Stable identifier, e.g. WIRELESS_MIC. Unique.';
COMMENT ON COLUMN equipment_types.name IS 'Display name.';
COMMENT ON COLUMN equipment_types.description IS 'Specification / notes.';
COMMENT ON COLUMN equipment_types.total_quantity IS 'Total units owned. Available = total - reserved for overlapping periods - out of service for the period (story 16.1).';
COMMENT ON COLUMN equipment_types.storage_location IS 'Where the stock is normally kept.';
COMMENT ON COLUMN equipment_types.is_active IS 'FALSE hides the type from new requests without deleting history.';
COMMENT ON COLUMN equipment_types.created_at IS 'Row creation time.';
COMMENT ON COLUMN equipment_types.updated_at IS 'Last modification time (maintained by trigger).';

-- =====================================================================
-- 3. VENUES  (stories 8.x catalogue, 9.x availability)
-- =====================================================================

CREATE TABLE venues (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                     TEXT NOT NULL,
    location                 TEXT NOT NULL,
    capacity                 INTEGER NOT NULL,
    description              TEXT,
    floor_area_sqm           NUMERIC(8,2),
    operating_hours_start    TIME,
    operating_hours_end      TIME,
    operating_notes          TEXT,
    setup_minutes_default    INTEGER NOT NULL DEFAULT 0,
    teardown_minutes_default INTEGER NOT NULL DEFAULT 0,
    status                   TEXT NOT NULL DEFAULT 'ACTIVE',
    created_by_id            UUID REFERENCES users (id),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_venues_name UNIQUE (name),
    CONSTRAINT ck_venues_capacity_positive CHECK (capacity > 0),
    CONSTRAINT ck_venues_status CHECK (status IN ('ACTIVE', 'WITHDRAWN')),
    CONSTRAINT ck_venues_operating_hours CHECK (
        (operating_hours_start IS NULL AND operating_hours_end IS NULL)
        OR (operating_hours_start IS NOT NULL AND operating_hours_end IS NOT NULL
            AND operating_hours_end > operating_hours_start)),
    CONSTRAINT ck_venues_turnaround_non_negative CHECK (setup_minutes_default >= 0 AND teardown_minutes_default >= 0)
);
COMMENT ON TABLE venues IS
    'Stories: 8.1, 8.2, 8.3, 8.4, 9.x, 10.x, 11.x. The venue catalogue: rooms and spaces ConnectSphere owns. Characteristics that are lists (facilities, layouts, accessibility) live in the venue_* join tables. NULL in an optional column means "not recorded" (story 8.2 AC2 shows it as unknown, not absent).';
COMMENT ON COLUMN venues.name IS 'Venue name, unique across the catalogue (story 8.3 AC1).';
COMMENT ON COLUMN venues.location IS 'Building / address / floor description (story 8.3 AC1).';
COMMENT ON COLUMN venues.capacity IS 'Maximum headcount. Positive whole number (story 8.3 AC3). Used by suitability checks (story 11.1).';
COMMENT ON COLUMN venues.description IS 'Free-text description shown in the catalogue.';
COMMENT ON COLUMN venues.floor_area_sqm IS 'Floor area in square metres (optional).';
COMMENT ON COLUMN venues.operating_hours_start IS 'Daily opening time (local). NULL = not recorded. Story 9.4 will treat times outside the window as unavailable.';
COMMENT ON COLUMN venues.operating_hours_end IS 'Daily closing time (local). Must be after operating_hours_start when both are set.';
COMMENT ON COLUMN venues.operating_notes IS 'Other operating information, e.g. "closed on public holidays", access instructions.';
COMMENT ON COLUMN venues.setup_minutes_default IS 'Default preparation time Venue Staff need before an event here (story 12.2 pre-fills booking requests from this).';
COMMENT ON COLUMN venues.teardown_minutes_default IS 'Default reset time after an event here.';
COMMENT ON COLUMN venues.status IS 'ACTIVE = in service and bookable; WITHDRAWN = withdrawn from service (story 8.4). Withdrawn venues are excluded or clearly marked in the catalogue (story 8.1 AC3).';
COMMENT ON COLUMN venues.created_by_id IS 'FK -> users.id. Venue Staff member who created the record.';
COMMENT ON COLUMN venues.created_at IS 'Row creation time.';
COMMENT ON COLUMN venues.updated_at IS 'Last modification time (maintained by trigger).';

CREATE TABLE venue_facilities (
    venue_id      UUID NOT NULL REFERENCES venues (id) ON DELETE CASCADE,
    facility_code TEXT NOT NULL REFERENCES facilities (code),
    quantity      INTEGER,
    notes         TEXT,
    PRIMARY KEY (venue_id, facility_code),
    CONSTRAINT ck_venue_facilities_quantity CHECK (quantity IS NULL OR quantity > 0)
);
COMMENT ON TABLE venue_facilities IS 'Stories: 8.2, 8.3, 10.3, 11.1. Which facilities each venue offers (many-to-many).';
COMMENT ON COLUMN venue_facilities.venue_id IS 'FK -> venues.id.';
COMMENT ON COLUMN venue_facilities.facility_code IS 'FK -> facilities.code.';
COMMENT ON COLUMN venue_facilities.quantity IS 'How many of the facility the venue has, where countable (e.g. 2 projectors). NULL = not applicable / not recorded.';
COMMENT ON COLUMN venue_facilities.notes IS 'Free text, e.g. model or limitations.';

CREATE TABLE venue_layouts (
    venue_id        UUID NOT NULL REFERENCES venues (id) ON DELETE CASCADE,
    layout_code     TEXT NOT NULL REFERENCES room_layouts (code),
    layout_capacity INTEGER,
    PRIMARY KEY (venue_id, layout_code),
    CONSTRAINT ck_venue_layouts_capacity CHECK (layout_capacity IS NULL OR layout_capacity > 0)
);
COMMENT ON TABLE venue_layouts IS 'Stories: 8.2, 8.3, 10.3, 11.1. Which room layouts each venue supports (many-to-many).';
COMMENT ON COLUMN venue_layouts.venue_id IS 'FK -> venues.id.';
COMMENT ON COLUMN venue_layouts.layout_code IS 'FK -> room_layouts.code.';
COMMENT ON COLUMN venue_layouts.layout_capacity IS 'Capacity in this layout if lower than the venue maximum (e.g. banquet seats fewer than theatre). NULL = same as venues.capacity.';

CREATE TABLE venue_accessibility_features (
    venue_id     UUID NOT NULL REFERENCES venues (id) ON DELETE CASCADE,
    feature_code TEXT NOT NULL REFERENCES accessibility_features (code),
    notes        TEXT,
    PRIMARY KEY (venue_id, feature_code)
);
COMMENT ON TABLE venue_accessibility_features IS 'Stories: 8.2, 8.3, 10.3, 11.1. Which accessibility features each venue provides (many-to-many).';
COMMENT ON COLUMN venue_accessibility_features.venue_id IS 'FK -> venues.id.';
COMMENT ON COLUMN venue_accessibility_features.feature_code IS 'FK -> accessibility_features.code.';
COMMENT ON COLUMN venue_accessibility_features.notes IS 'Free text, e.g. "lift to level 3 only".';

CREATE TABLE venue_unavailability_periods (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    venue_id      UUID NOT NULL REFERENCES venues (id) ON DELETE CASCADE,
    starts_at     TIMESTAMPTZ NOT NULL,
    ends_at       TIMESTAMPTZ NOT NULL,
    reason        TEXT NOT NULL,
    notes         TEXT,
    created_by_id UUID REFERENCES users (id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_venue_unavailability_period CHECK (ends_at > starts_at),
    CONSTRAINT ck_venue_unavailability_reason CHECK (reason IN ('MAINTENANCE', 'RENOVATION', 'SAFETY', 'INTERNAL_USE', 'OTHER'))
);
COMMENT ON TABLE venue_unavailability_periods IS
    'Stories: 9.1, 9.3, 10.1, 14.1. Blocks of time a venue cannot be booked for reasons other than an event booking (maintenance, renovation, safety, internal use). Shown as unavailable on the calendar and excluded from availability searches.';
COMMENT ON COLUMN venue_unavailability_periods.venue_id IS 'FK -> venues.id.';
COMMENT ON COLUMN venue_unavailability_periods.starts_at IS 'Start of the blocked period (inclusive).';
COMMENT ON COLUMN venue_unavailability_periods.ends_at IS 'End of the blocked period (exclusive). Must be after starts_at (story 9.3 AC3).';
COMMENT ON COLUMN venue_unavailability_periods.reason IS 'Why the venue is blocked: MAINTENANCE, RENOVATION, SAFETY, INTERNAL_USE or OTHER.';
COMMENT ON COLUMN venue_unavailability_periods.notes IS 'Free-text detail.';
COMMENT ON COLUMN venue_unavailability_periods.created_by_id IS 'FK -> users.id. Venue Staff member who recorded it.';
COMMENT ON COLUMN venue_unavailability_periods.created_at IS 'Row creation time.';
COMMENT ON COLUMN venue_unavailability_periods.updated_at IS 'Last modification time (maintained by trigger).';
CREATE INDEX ix_venue_unavailability_venue_period ON venue_unavailability_periods (venue_id, starts_at, ends_at);

-- =====================================================================
-- 4. EVENTS  (stories 2.x request, 3.x drafts, 4.x review, 5.x assignment,
--             6.x status, 7.x information, 19.x change requests)
-- =====================================================================

CREATE TABLE events (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organiser_id                UUID NOT NULL REFERENCES users (id),
    organisation_id             UUID REFERENCES client_organisations (id),
    name                        TEXT NOT NULL,
    purpose                     TEXT,
    description                 TEXT,
    starts_at                   TIMESTAMPTZ,
    ends_at                     TIMESTAMPTZ,
    expected_attendance         INTEGER,
    status                      TEXT NOT NULL DEFAULT 'DRAFT',
    assigned_coordinator_id     UUID REFERENCES users (id),
    -- venue requirements captured on the request (story 2.1 AC4)
    preferred_location          TEXT,
    required_layout_code        TEXT REFERENCES room_layouts (code),
    venue_requirement_notes     TEXT,
    -- accessibility (story 2.1 AC5): selected features live in event_accessibility_needs
    accessibility_none_required BOOLEAN NOT NULL DEFAULT FALSE,
    accessibility_notes         TEXT,
    -- registration (story 2.4, 18.x)
    registration_required       BOOLEAN NOT NULL DEFAULT FALSE,
    registration_capacity       INTEGER,
    registration_opens_at       TIMESTAMPTZ,
    registration_closes_at      TIMESTAMPTZ,
    -- routine / contact fields (story 7.2)
    contact_name                TEXT,
    contact_email               CITEXT,
    contact_phone               TEXT,
    internal_notes              TEXT,
    -- lifecycle bookkeeping
    submitted_at                TIMESTAMPTZ,
    decided_at                  TIMESTAMPTZ,
    decided_by_id               UUID REFERENCES users (id),
    decision_reason             TEXT,
    confirmed_at                TIMESTAMPTZ,
    completed_at                TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_events_status CHECK (status IN (
        'DRAFT', 'SUBMITTED', 'UNDER_REVIEW', 'CLARIFICATION_REQUESTED', 'APPROVED',
        'PLANNING', 'CONFIRMED', 'COMPLETED', 'CANCELLED', 'REJECTED')),
    CONSTRAINT ck_events_period CHECK (starts_at IS NULL OR ends_at IS NULL OR ends_at > starts_at),
    CONSTRAINT ck_events_attendance_positive CHECK (expected_attendance IS NULL OR expected_attendance > 0),
    CONSTRAINT ck_events_registration_capacity CHECK (registration_capacity IS NULL OR registration_capacity > 0),
    CONSTRAINT ck_events_registration_closes_before_start CHECK (
        registration_closes_at IS NULL OR starts_at IS NULL OR registration_closes_at <= starts_at),
    CONSTRAINT ck_events_registration_window CHECK (
        registration_opens_at IS NULL OR registration_closes_at IS NULL OR registration_closes_at > registration_opens_at),
    -- Drafts may be incomplete (story 3.1 AC1); anything that has left DRAFT must carry the mandatory fields.
    CONSTRAINT ck_events_submitted_fields_complete CHECK (
        status = 'DRAFT' OR (
            purpose IS NOT NULL AND starts_at IS NOT NULL AND ends_at IS NOT NULL
            AND expected_attendance IS NOT NULL))
);
COMMENT ON TABLE events IS
    'Stories: 2.1, 2.4, 2.6, 3.x, 4.x, 5.x, 6.x, 7.x, 19.x. An event request and, once approved, the event itself - one row for the whole lifecycle so history is never split across tables. Status drives what each role may do (story 6.1: exactly one current status). Only DRAFT rows may leave mandatory fields empty.';
COMMENT ON COLUMN events.organiser_id IS 'FK -> users.id. The Event Organiser who owns the request (story 2.6 lists by this).';
COMMENT ON COLUMN events.organisation_id IS 'FK -> client_organisations.id. Client organisation on whose behalf the event is held (copied from the organiser at creation).';
COMMENT ON COLUMN events.name IS 'Event name. The only field required even for a draft.';
COMMENT ON COLUMN events.purpose IS 'Why the event is held (story 2.1 AC1). Mandatory once submitted.';
COMMENT ON COLUMN events.description IS 'Longer description / general programme (story 2.1 AC1). Routine field (story 7.2).';
COMMENT ON COLUMN events.starts_at IS 'Proposed start date-time (story 2.1 AC1). Mandatory once submitted. Important field (story 7.3) - changes go through change requests once arrangements exist.';
COMMENT ON COLUMN events.ends_at IS 'Proposed end date-time. Must be after starts_at (story 2.1 AC2).';
COMMENT ON COLUMN events.expected_attendance IS 'Expected number of attendees. Positive whole number (story 2.1 AC3). Compared with venue capacity (story 11.1).';
COMMENT ON COLUMN events.status IS 'Current lifecycle stage: DRAFT, SUBMITTED, UNDER_REVIEW, CLARIFICATION_REQUESTED, APPROVED, PLANNING, CONFIRMED, COMPLETED, CANCELLED, REJECTED. Every transition is also written to event_status_history.';
COMMENT ON COLUMN events.assigned_coordinator_id IS 'FK -> users.id. Current Event Coordinator (story 5.1). History of assignments is in event_coordinator_assignments.';
COMMENT ON COLUMN events.preferred_location IS 'Venue requirement: preferred building/area (story 2.1 AC4).';
COMMENT ON COLUMN events.required_layout_code IS 'FK -> room_layouts.code. Venue requirement: required room layout (story 2.1 AC4).';
COMMENT ON COLUMN events.venue_requirement_notes IS 'Free-text venue requirements not captured elsewhere.';
COMMENT ON COLUMN events.accessibility_none_required IS 'TRUE = organiser explicitly stated no accessibility needs. FALSE with no rows in event_accessibility_needs = not yet specified (story 2.1 AC5 requires these to be distinguishable).';
COMMENT ON COLUMN events.accessibility_notes IS 'Free-text accessibility needs beyond the selectable features.';
COMMENT ON COLUMN events.registration_required IS 'Whether attendees must register (story 2.4 AC1).';
COMMENT ON COLUMN events.registration_capacity IS 'Maximum active registrations; NULL = no cap, only the closing date applies (story 18.5 AC4).';
COMMENT ON COLUMN events.registration_opens_at IS 'When attendees may start registering (story 18.1).';
COMMENT ON COLUMN events.registration_closes_at IS 'Registration deadline. Must not be after the event start (story 2.4 AC4).';
COMMENT ON COLUMN events.contact_name IS 'On-the-day contact person. Routine field (story 7.2).';
COMMENT ON COLUMN events.contact_email IS 'Contact e-mail. Routine field.';
COMMENT ON COLUMN events.contact_phone IS 'Contact phone. Routine field.';
COMMENT ON COLUMN events.internal_notes IS 'Coordinator-only notes; never shown to organisers or attendees. Routine field.';
COMMENT ON COLUMN events.submitted_at IS 'When the organiser submitted the request (NULL while DRAFT).';
COMMENT ON COLUMN events.decided_at IS 'When the review decision (approve/reject) or cancellation was recorded (story 4.4 AC2, 4.5).';
COMMENT ON COLUMN events.decided_by_id IS 'FK -> users.id. Coordinator who made the decision.';
COMMENT ON COLUMN events.decision_reason IS 'Reason given on rejection (mandatory, story 4.5 AC1) or cancellation (story 6.5 AC2).';
COMMENT ON COLUMN events.confirmed_at IS 'When the coordinator confirmed the event (status CONFIRMED).';
COMMENT ON COLUMN events.completed_at IS 'When the event was marked COMPLETED.';
COMMENT ON COLUMN events.created_at IS 'Row creation time.';
COMMENT ON COLUMN events.updated_at IS 'Last modification time (maintained by trigger). Also serves as the draft last-modified time (story 3.3 AC3).';
CREATE INDEX ix_events_organiser ON events (organiser_id);
CREATE INDEX ix_events_coordinator ON events (assigned_coordinator_id);
CREATE INDEX ix_events_status ON events (status);
CREATE INDEX ix_events_starts_at ON events (starts_at);

CREATE TABLE event_required_facilities (
    event_id      UUID NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    facility_code TEXT NOT NULL REFERENCES facilities (code),
    notes         TEXT,
    PRIMARY KEY (event_id, facility_code)
);
COMMENT ON TABLE event_required_facilities IS 'Stories: 2.1, 10.3, 11.1, 12.1. Facilities the event requires of its venue (many-to-many).';
COMMENT ON COLUMN event_required_facilities.event_id IS 'FK -> events.id.';
COMMENT ON COLUMN event_required_facilities.facility_code IS 'FK -> facilities.code.';
COMMENT ON COLUMN event_required_facilities.notes IS 'Free text, e.g. "needs HDMI input".';

CREATE TABLE event_accessibility_needs (
    event_id     UUID NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    feature_code TEXT NOT NULL REFERENCES accessibility_features (code),
    notes        TEXT,
    PRIMARY KEY (event_id, feature_code)
);
COMMENT ON TABLE event_accessibility_needs IS 'Stories: 2.1, 11.1. Accessibility features the event needs (many-to-many). See events.accessibility_none_required for the "none required" case.';
COMMENT ON COLUMN event_accessibility_needs.event_id IS 'FK -> events.id.';
COMMENT ON COLUMN event_accessibility_needs.feature_code IS 'FK -> accessibility_features.code.';
COMMENT ON COLUMN event_accessibility_needs.notes IS 'Free text detail.';

CREATE TABLE event_equipment_requests (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id          UUID NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    equipment_type_id UUID NOT NULL REFERENCES equipment_types (id),
    quantity          INTEGER NOT NULL,
    technical_notes   TEXT,
    status            TEXT NOT NULL DEFAULT 'REQUESTED',
    status_notes      TEXT,
    created_by_id     UUID REFERENCES users (id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_event_equipment_requests_quantity CHECK (quantity > 0),
    CONSTRAINT ck_event_equipment_requests_status CHECK (status IN (
        'REQUESTED', 'UNDER_REVIEW', 'RESERVED', 'PARTIALLY_RESERVED', 'UNAVAILABLE', 'CANCELLED'))
);
COMMENT ON TABLE event_equipment_requests IS
    'Stories: 2.1 (AC6), 15.x, 16.4, 17.3. One line per equipment type an event asks for, with quantity and technical notes. Technical Support Staff move each line through statuses as they arrange it (story 15.4). Actual holds on stock are separate rows in equipment_reservations.';
COMMENT ON COLUMN event_equipment_requests.event_id IS 'FK -> events.id.';
COMMENT ON COLUMN event_equipment_requests.equipment_type_id IS 'FK -> equipment_types.id.';
COMMENT ON COLUMN event_equipment_requests.quantity IS 'Units requested. Positive whole number (story 2.1 AC3, 15.1 AC3).';
COMMENT ON COLUMN event_equipment_requests.technical_notes IS 'Technical requirements for this item (story 15.1 AC2).';
COMMENT ON COLUMN event_equipment_requests.status IS 'Progress of the request line: REQUESTED, UNDER_REVIEW, RESERVED, PARTIALLY_RESERVED, UNAVAILABLE, CANCELLED (story 15.4 AC1).';
COMMENT ON COLUMN event_equipment_requests.status_notes IS 'Note from Technical Support Staff when the item cannot be provided as requested (story 15.4 AC2).';
COMMENT ON COLUMN event_equipment_requests.created_by_id IS 'FK -> users.id. Who added the line (organiser or coordinator).';
COMMENT ON COLUMN event_equipment_requests.created_at IS 'Row creation time.';
COMMENT ON COLUMN event_equipment_requests.updated_at IS 'Last modification time (maintained by trigger).';
CREATE INDEX ix_event_equipment_requests_event ON event_equipment_requests (event_id);

CREATE TABLE event_status_history (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id      UUID NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    from_status   TEXT,
    to_status     TEXT NOT NULL,
    changed_by_id UUID REFERENCES users (id),
    changed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason        TEXT
);
COMMENT ON TABLE event_status_history IS
    'Stories: 4.6, 6.1, 6.4. Append-only log of every event status transition (previous status, new status, actor, time, reason). Rows are never updated or deleted (story 6.4 AC2).';
COMMENT ON COLUMN event_status_history.event_id IS 'FK -> events.id.';
COMMENT ON COLUMN event_status_history.from_status IS 'Status before the change. NULL for the initial creation.';
COMMENT ON COLUMN event_status_history.to_status IS 'Status after the change.';
COMMENT ON COLUMN event_status_history.changed_by_id IS 'FK -> users.id. Who performed the action (NULL for system actions).';
COMMENT ON COLUMN event_status_history.changed_at IS 'When the transition happened.';
COMMENT ON COLUMN event_status_history.reason IS 'Reason supplied with the action (e.g. rejection or cancellation reason).';
CREATE INDEX ix_event_status_history_event ON event_status_history (event_id, changed_at);

CREATE TABLE event_coordinator_assignments (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id       UUID NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    coordinator_id UUID NOT NULL REFERENCES users (id),
    assigned_by_id UUID REFERENCES users (id),
    assigned_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    unassigned_at  TIMESTAMPTZ,
    note           TEXT
);
COMMENT ON TABLE event_coordinator_assignments IS
    'Stories: 5.1, 5.2, 5.3. History of which coordinator was responsible for an event and when. The current coordinator is also denormalised onto events.assigned_coordinator_id for fast filtering; the row with unassigned_at IS NULL must match it.';
COMMENT ON COLUMN event_coordinator_assignments.event_id IS 'FK -> events.id.';
COMMENT ON COLUMN event_coordinator_assignments.coordinator_id IS 'FK -> users.id. Must hold the EVENT_COORDINATOR role (enforced in the service layer, story 5.1 AC2).';
COMMENT ON COLUMN event_coordinator_assignments.assigned_by_id IS 'FK -> users.id. Who made the assignment (story 5.1 AC3).';
COMMENT ON COLUMN event_coordinator_assignments.assigned_at IS 'When the assignment started.';
COMMENT ON COLUMN event_coordinator_assignments.unassigned_at IS 'When the assignment ended (reassignment, story 5.2). NULL = current.';
COMMENT ON COLUMN event_coordinator_assignments.note IS 'Optional reason for the (re)assignment.';
CREATE UNIQUE INDEX uq_event_coordinator_assignments_current
    ON event_coordinator_assignments (event_id) WHERE unassigned_at IS NULL;

CREATE TABLE event_clarifications (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id   UUID NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    author_id  UUID NOT NULL REFERENCES users (id),
    kind       TEXT NOT NULL,
    message    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_event_clarifications_kind CHECK (kind IN ('REQUEST', 'RESPONSE', 'NOTE'))
);
COMMENT ON TABLE event_clarifications IS
    'Stories: 4.2, 4.3, 4.6. The clarification conversation between coordinator and organiser, kept with the event record. Append-only (story 4.6 AC3).';
COMMENT ON COLUMN event_clarifications.event_id IS 'FK -> events.id.';
COMMENT ON COLUMN event_clarifications.author_id IS 'FK -> users.id. Who wrote the message.';
COMMENT ON COLUMN event_clarifications.kind IS 'REQUEST = coordinator asking for clarification; RESPONSE = organiser answering; NOTE = other comment.';
COMMENT ON COLUMN event_clarifications.message IS 'The message text (mandatory, story 4.2 AC1).';
COMMENT ON COLUMN event_clarifications.created_at IS 'Timestamp shown in the chronological history (story 4.6 AC2).';
CREATE INDEX ix_event_clarifications_event ON event_clarifications (event_id, created_at);

CREATE TABLE event_change_requests (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id        UUID NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    requested_by_id UUID NOT NULL REFERENCES users (id),
    field_name      TEXT NOT NULL,
    current_value   TEXT,
    proposed_value  TEXT NOT NULL,
    reason          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    decided_by_id   UUID REFERENCES users (id),
    decided_at      TIMESTAMPTZ,
    decision_reason TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_event_change_requests_status CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN'))
);
COMMENT ON TABLE event_change_requests IS
    'Stories: 7.3, 19.x. A request by the organiser to change an important field (date, time, attendance, venue or equipment requirements) after submission. The event row is only updated when the coordinator approves (story 19.4 AC1). Values are stored as text so any field can be requested without schema changes.';
COMMENT ON COLUMN event_change_requests.event_id IS 'FK -> events.id.';
COMMENT ON COLUMN event_change_requests.requested_by_id IS 'FK -> users.id. Organiser raising the change.';
COMMENT ON COLUMN event_change_requests.field_name IS 'Name of the event field to change, e.g. starts_at, expected_attendance (story 19.1 AC2).';
COMMENT ON COLUMN event_change_requests.current_value IS 'Value at the time of the request, as text, for display (story 19.2 AC2).';
COMMENT ON COLUMN event_change_requests.proposed_value IS 'Requested new value, as text.';
COMMENT ON COLUMN event_change_requests.reason IS 'Why the change is needed (mandatory).';
COMMENT ON COLUMN event_change_requests.status IS 'PENDING, APPROVED, REJECTED or WITHDRAWN.';
COMMENT ON COLUMN event_change_requests.decided_by_id IS 'FK -> users.id. Coordinator who decided.';
COMMENT ON COLUMN event_change_requests.decided_at IS 'Decision time (story 19.4 AC2).';
COMMENT ON COLUMN event_change_requests.decision_reason IS 'Mandatory when rejected (story 19.5 AC1).';
COMMENT ON COLUMN event_change_requests.created_at IS 'Row creation time.';
COMMENT ON COLUMN event_change_requests.updated_at IS 'Last modification time (maintained by trigger).';
CREATE INDEX ix_event_change_requests_event ON event_change_requests (event_id, status);

-- =====================================================================
-- 5. VENUE BOOKINGS  (stories 12.x request, 13.x approval, 14.x conflicts)
-- =====================================================================

CREATE TABLE venue_bookings (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id                    UUID NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    venue_id                    UUID NOT NULL REFERENCES venues (id),
    requested_by_id             UUID NOT NULL REFERENCES users (id),
    starts_at                   TIMESTAMPTZ NOT NULL,
    ends_at                     TIMESTAMPTZ NOT NULL,
    setup_minutes               INTEGER NOT NULL DEFAULT 0,
    teardown_minutes            INTEGER NOT NULL DEFAULT 0,
    held_from                   TIMESTAMPTZ NOT NULL,
    held_until                  TIMESTAMPTZ NOT NULL,
    expected_attendance         INTEGER NOT NULL,
    required_layout_code        TEXT REFERENCES room_layouts (code),
    requirement_notes           TEXT,
    suitability_override_reason TEXT,
    status                      TEXT NOT NULL DEFAULT 'PENDING',
    decided_by_id               UUID REFERENCES users (id),
    decided_at                  TIMESTAMPTZ,
    decision_reason             TEXT,
    alternative_suggestion      TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_venue_bookings_period CHECK (ends_at > starts_at),
    CONSTRAINT ck_venue_bookings_turnaround CHECK (setup_minutes >= 0 AND teardown_minutes >= 0),
    CONSTRAINT ck_venue_bookings_attendance CHECK (expected_attendance > 0),
    CONSTRAINT ck_venue_bookings_status CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN', 'CANCELLED')),
    -- Defence in depth for story 14.2: the database itself refuses two APPROVED bookings whose held
    -- periods overlap on the same venue. Half-open ranges [) mean periods that merely touch at a
    -- boundary are NOT conflicts (story 14.1 AC3). The service layer checks first and reports the
    -- conflicting booking; this constraint is the last line of defence against races.
    CONSTRAINT ex_venue_bookings_no_double_booking EXCLUDE USING gist (
        venue_id WITH =,
        tstzrange(held_from, held_until, '[)') WITH &&
    ) WHERE (status = 'APPROVED')
);
COMMENT ON TABLE venue_bookings IS
    'Stories: 12.x, 13.x, 14.x, 9.2. A request by the assigned coordinator to book one venue for an event, and its outcome. PENDING = awaiting Venue Staff; APPROVED = confirmed booking that blocks the venue; REJECTED / WITHDRAWN / CANCELLED free the venue. The held period (held_from..held_until) includes setup and teardown time (story 12.2).';
COMMENT ON COLUMN venue_bookings.event_id IS 'FK -> events.id. Only APPROVED (or later) events may raise a booking (story 12.1 AC1, enforced in the service).';
COMMENT ON COLUMN venue_bookings.venue_id IS 'FK -> venues.id. Exactly one venue per request (story 12.1 AC1).';
COMMENT ON COLUMN venue_bookings.requested_by_id IS 'FK -> users.id. Coordinator who raised the request (must be the assigned coordinator, story 12.1 AC4).';
COMMENT ON COLUMN venue_bookings.starts_at IS 'Event start time the venue is requested for (story 12.1 AC2).';
COMMENT ON COLUMN venue_bookings.ends_at IS 'Event end time. Must be after starts_at.';
COMMENT ON COLUMN venue_bookings.setup_minutes IS 'Preparation minutes before starts_at during which the venue is also held (story 12.2).';
COMMENT ON COLUMN venue_bookings.teardown_minutes IS 'Reset minutes after ends_at during which the venue is also held.';
COMMENT ON COLUMN venue_bookings.held_from IS 'Maintained by trigger = starts_at minus setup_minutes (never set it directly). Start of the period used for conflict and availability checks.';
COMMENT ON COLUMN venue_bookings.held_until IS 'Maintained by trigger = ends_at plus teardown_minutes (never set it directly). End (exclusive) of the period used for conflict and availability checks.';
COMMENT ON COLUMN venue_bookings.expected_attendance IS 'Attendance stated on the request (story 12.1 AC2, 13.1 AC2).';
COMMENT ON COLUMN venue_bookings.required_layout_code IS 'FK -> room_layouts.code. Layout requested (story 12.1 AC2).';
COMMENT ON COLUMN venue_bookings.requirement_notes IS 'Required facilities and other requirements, as stated to Venue Staff.';
COMMENT ON COLUMN venue_bookings.suitability_override_reason IS 'Justification recorded when the coordinator books a venue the suitability check flagged as unsuitable (story 11.3 AC2). NULL when no override.';
COMMENT ON COLUMN venue_bookings.status IS 'PENDING, APPROVED, REJECTED, WITHDRAWN or CANCELLED. Only APPROVED bookings occupy the venue calendar.';
COMMENT ON COLUMN venue_bookings.decided_by_id IS 'FK -> users.id. Venue Staff member who approved or rejected (story 13.2 AC1).';
COMMENT ON COLUMN venue_bookings.decided_at IS 'Decision time.';
COMMENT ON COLUMN venue_bookings.decision_reason IS 'Mandatory when rejected (story 13.3 AC1).';
COMMENT ON COLUMN venue_bookings.alternative_suggestion IS 'Optional alternative dates/venues suggested on rejection (story 13.3 AC2).';
COMMENT ON COLUMN venue_bookings.created_at IS 'Row creation time.';
COMMENT ON COLUMN venue_bookings.updated_at IS 'Last modification time (maintained by trigger).';
-- held_from / held_until cannot be GENERATED columns (timestamptz +/- interval is only STABLE in
-- PostgreSQL because of time-zone rules), so a trigger derives them on every INSERT/UPDATE.
CREATE OR REPLACE FUNCTION set_venue_booking_held_period() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.held_from  := NEW.starts_at - make_interval(mins => NEW.setup_minutes);
    NEW.held_until := NEW.ends_at + make_interval(mins => NEW.teardown_minutes);
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_venue_bookings_set_held_period
    BEFORE INSERT OR UPDATE OF starts_at, ends_at, setup_minutes, teardown_minutes ON venue_bookings
    FOR EACH ROW EXECUTE FUNCTION set_venue_booking_held_period();
CREATE INDEX ix_venue_bookings_event ON venue_bookings (event_id);
CREATE INDEX ix_venue_bookings_venue_period ON venue_bookings (venue_id, held_from, held_until);
CREATE INDEX ix_venue_bookings_status ON venue_bookings (status);

-- =====================================================================
-- 6. EQUIPMENT RESERVATIONS & OUT-OF-SERVICE  (stories 16.x, 17.x)
-- =====================================================================

CREATE TABLE equipment_reservations (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id             UUID NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    equipment_request_id UUID REFERENCES event_equipment_requests (id) ON DELETE SET NULL,
    equipment_type_id    UUID NOT NULL REFERENCES equipment_types (id),
    quantity             INTEGER NOT NULL,
    starts_at            TIMESTAMPTZ NOT NULL,
    ends_at              TIMESTAMPTZ NOT NULL,
    status               TEXT NOT NULL DEFAULT 'RESERVED',
    reserved_by_id       UUID NOT NULL REFERENCES users (id),
    reserved_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_at          TIMESTAMPTZ,
    released_quantity    INTEGER NOT NULL DEFAULT 0,
    notes                TEXT,
    CONSTRAINT ck_equipment_reservations_quantity CHECK (quantity > 0),
    CONSTRAINT ck_equipment_reservations_released CHECK (released_quantity >= 0 AND released_quantity <= quantity),
    CONSTRAINT ck_equipment_reservations_period CHECK (ends_at > starts_at),
    CONSTRAINT ck_equipment_reservations_status CHECK (status IN ('RESERVED', 'RELEASED'))
);
COMMENT ON TABLE equipment_reservations IS
    'Stories: 16.2, 17.x. A hold of N units of an equipment type for an event over a period. Availability for a period = equipment_types.total_quantity - SUM(quantity - released_quantity) of overlapping RESERVED rows - overlapping out-of-service quantities. The "never over-commit" rule (story 17.2 AC3) is enforced in the service layer inside a transaction, because SQL constraints cannot sum across rows.';
COMMENT ON COLUMN equipment_reservations.event_id IS 'FK -> events.id. The event the stock is held for (story 17.1 AC3).';
COMMENT ON COLUMN equipment_reservations.equipment_request_id IS 'FK -> event_equipment_requests.id. The request line this reservation satisfies (optional).';
COMMENT ON COLUMN equipment_reservations.equipment_type_id IS 'FK -> equipment_types.id.';
COMMENT ON COLUMN equipment_reservations.quantity IS 'Units reserved. Positive.';
COMMENT ON COLUMN equipment_reservations.starts_at IS 'Start of the hold (normally the event start, story 17.1 AC1).';
COMMENT ON COLUMN equipment_reservations.ends_at IS 'End (exclusive) of the hold.';
COMMENT ON COLUMN equipment_reservations.status IS 'RESERVED while any units are still held; RELEASED once released_quantity = quantity (story 17.4).';
COMMENT ON COLUMN equipment_reservations.reserved_by_id IS 'FK -> users.id. Technical Support Staff member who reserved (story 17.1 AC3).';
COMMENT ON COLUMN equipment_reservations.reserved_at IS 'When the reservation was made.';
COMMENT ON COLUMN equipment_reservations.released_at IS 'When the reservation was last (partly) released.';
COMMENT ON COLUMN equipment_reservations.released_quantity IS 'Units already released back to stock (supports partial release, story 17.4 AC1).';
COMMENT ON COLUMN equipment_reservations.notes IS 'Free text.';
CREATE INDEX ix_equipment_reservations_type_period ON equipment_reservations (equipment_type_id, starts_at, ends_at);
CREATE INDEX ix_equipment_reservations_event ON equipment_reservations (event_id);

CREATE TABLE equipment_unavailability_periods (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    equipment_type_id UUID NOT NULL REFERENCES equipment_types (id) ON DELETE CASCADE,
    quantity          INTEGER NOT NULL,
    reason            TEXT NOT NULL,
    starts_at         TIMESTAMPTZ NOT NULL,
    ends_at           TIMESTAMPTZ,
    notes             TEXT,
    created_by_id     UUID REFERENCES users (id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_equipment_unavailability_quantity CHECK (quantity > 0),
    CONSTRAINT ck_equipment_unavailability_period CHECK (ends_at IS NULL OR ends_at > starts_at),
    CONSTRAINT ck_equipment_unavailability_reason CHECK (reason IN ('DAMAGED', 'MAINTENANCE', 'LOST', 'OTHER'))
);
COMMENT ON TABLE equipment_unavailability_periods IS
    'Stories: 16.1, 16.3. Units of an equipment type that are out of service (damaged, under maintenance, ...) for a period, so they are excluded from availability.';
COMMENT ON COLUMN equipment_unavailability_periods.equipment_type_id IS 'FK -> equipment_types.id.';
COMMENT ON COLUMN equipment_unavailability_periods.quantity IS 'Units out of service. Positive.';
COMMENT ON COLUMN equipment_unavailability_periods.reason IS 'DAMAGED, MAINTENANCE, LOST or OTHER.';
COMMENT ON COLUMN equipment_unavailability_periods.starts_at IS 'Start of the out-of-service period.';
COMMENT ON COLUMN equipment_unavailability_periods.ends_at IS 'End (exclusive). NULL = open-ended until Technical Support Staff end it (story 16.3 AC3).';
COMMENT ON COLUMN equipment_unavailability_periods.notes IS 'Free text.';
COMMENT ON COLUMN equipment_unavailability_periods.created_by_id IS 'FK -> users.id.';
COMMENT ON COLUMN equipment_unavailability_periods.created_at IS 'Row creation time.';
COMMENT ON COLUMN equipment_unavailability_periods.updated_at IS 'Last modification time (maintained by trigger).';
CREATE INDEX ix_equipment_unavailability_type_period ON equipment_unavailability_periods (equipment_type_id, starts_at, ends_at);

-- =====================================================================
-- 7. ATTENDEE REGISTRATION  (stories 18.x)
-- =====================================================================

CREATE TABLE event_registrations (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id      UUID NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    attendee_id   UUID NOT NULL REFERENCES users (id),
    status        TEXT NOT NULL DEFAULT 'REGISTERED',
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    withdrawn_at  TIMESTAMPTZ,
    attended      BOOLEAN,
    notes         TEXT,
    CONSTRAINT ck_event_registrations_status CHECK (status IN ('REGISTERED', 'WITHDRAWN', 'CANCELLED'))
);
COMMENT ON TABLE event_registrations IS
    'Stories: 18.x. An attendee''s registration for an event. An attendee may hold only one active (REGISTERED) registration per event (story 18.2 AC2) but may register again after withdrawing (story 18.4 AC4), hence the partial unique index rather than a plain unique constraint.';
COMMENT ON COLUMN event_registrations.event_id IS 'FK -> events.id.';
COMMENT ON COLUMN event_registrations.attendee_id IS 'FK -> users.id (role ATTENDEE).';
COMMENT ON COLUMN event_registrations.status IS 'REGISTERED, WITHDRAWN (by the attendee) or CANCELLED (by ConnectSphere, e.g. event cancelled).';
COMMENT ON COLUMN event_registrations.registered_at IS 'Registration timestamp (story 18.2 AC3).';
COMMENT ON COLUMN event_registrations.withdrawn_at IS 'When the attendee withdrew.';
COMMENT ON COLUMN event_registrations.attended IS 'Recorded after the event; NULL = not recorded (attendance recording is outside the first release).';
COMMENT ON COLUMN event_registrations.notes IS 'Free text (dietary needs etc.).';
CREATE UNIQUE INDEX uq_event_registrations_active
    ON event_registrations (event_id, attendee_id) WHERE status = 'REGISTERED';
CREATE INDEX ix_event_registrations_attendee ON event_registrations (attendee_id);

-- =====================================================================
-- 8. NOTIFICATIONS & AUDIT  (stories 20.x; auditability NFR)
-- =====================================================================

CREATE TABLE notifications (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_id        UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    event_id            UUID REFERENCES events (id) ON DELETE CASCADE,
    notification_type   TEXT NOT NULL,
    title               TEXT NOT NULL,
    message             TEXT NOT NULL,
    related_entity_type TEXT,
    related_entity_id   UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at             TIMESTAMPTZ
);
COMMENT ON TABLE notifications IS
    'Stories: 20.x. In-app notifications, one row per recipient. Generated inside the same transaction as the triggering action (story 20.1 AC3). notification_type is free text validated in code so new types need no migration.';
COMMENT ON COLUMN notifications.recipient_id IS 'FK -> users.id. Who sees the notification (story 20.2 restricts to related users).';
COMMENT ON COLUMN notifications.event_id IS 'FK -> events.id. The related event, if any.';
COMMENT ON COLUMN notifications.notification_type IS 'Machine-readable trigger, e.g. EVENT_SUBMITTED, BOOKING_APPROVED (story 20.1 AC2).';
COMMENT ON COLUMN notifications.title IS 'Short heading shown in the list.';
COMMENT ON COLUMN notifications.message IS 'Full text.';
COMMENT ON COLUMN notifications.related_entity_type IS 'Type of the record to open from the notification, e.g. venue_booking, event_registration (story 20.4 AC1).';
COMMENT ON COLUMN notifications.related_entity_id IS 'ID of that record.';
COMMENT ON COLUMN notifications.created_at IS 'When generated (list is reverse-chronological, story 20.3 AC1).';
COMMENT ON COLUMN notifications.read_at IS 'NULL = unread (story 20.3 AC2/AC3).';
CREATE INDEX ix_notifications_recipient_unread ON notifications (recipient_id, created_at DESC) WHERE read_at IS NULL;
CREATE INDEX ix_notifications_recipient ON notifications (recipient_id, created_at DESC);

CREATE TABLE audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id    UUID REFERENCES users (id),
    action      TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id   UUID,
    details     JSONB,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE audit_log IS
    'Stories: 7.4 and the auditability requirement (who changed what, when). Generic append-only record of significant actions. details holds field-level before/after values as JSON so any entity can be audited without schema changes.';
COMMENT ON COLUMN audit_log.actor_id IS 'FK -> users.id. Who performed the action (NULL for system).';
COMMENT ON COLUMN audit_log.action IS 'Verb, e.g. LOGIN, VENUE_UPDATED, EVENT_APPROVED.';
COMMENT ON COLUMN audit_log.entity_type IS 'Table / entity name the action concerns, e.g. venue, event.';
COMMENT ON COLUMN audit_log.entity_id IS 'Primary key of that entity.';
COMMENT ON COLUMN audit_log.details IS 'JSON payload, typically {"field": {"from": ..., "to": ...}}.';
COMMENT ON COLUMN audit_log.occurred_at IS 'When it happened.';
CREATE INDEX ix_audit_log_entity ON audit_log (entity_type, entity_id, occurred_at DESC);

-- =====================================================================
-- updated_at triggers
-- =====================================================================
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'client_organisations', 'users', 'equipment_types', 'venues',
        'venue_unavailability_periods', 'events', 'event_equipment_requests',
        'event_change_requests', 'venue_bookings', 'equipment_unavailability_periods']
    LOOP
        EXECUTE format(
            'CREATE TRIGGER trg_%1$s_set_updated_at BEFORE UPDATE ON %1$I
             FOR EACH ROW EXECUTE FUNCTION set_updated_at()', t);
    END LOOP;
END $$;
