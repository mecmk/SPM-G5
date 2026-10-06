-- =====================================================================
-- Migration 012 - story 2.7: an event lists several venue requirements, each with its own times.
--
-- Until now an event held one set of venue requirements on its own row (required_layout_code,
-- venue_requirement_notes) plus event_required_facilities. Story 2.7 AC1 gives each requirement
-- its own name, number of people, times, layout, facilities and notes, so they move to a table of
-- their own: venue_requirements, with venue_requirement_facilities beneath it. Each has a stable
-- id, so a later story (8.4, 12.5) can point a booking at the requirement it is for.
--
-- This file runs as one transaction (app/dbtool/migrate.py). Order matters:
-- 1. Create the two tables.
-- 2. Story 2.7 AC7: every request that recorded venue requirements keeps them as one requirement
--    named "Main venue", with the event's times and expected attendance. A request marked
--    "No venue requirements", or with nothing recorded, gets none (PO decision, 2 Oct 2026).
--    Times are copied only when the event has both, since a requirement has both or neither.
--    The seed runs after migrations, so on a fresh database this step finds nothing to copy and
--    020_sample_data.sql writes the sample requirements itself.
-- 3. Drop the old columns and table, so there is one place venue requirements live.
-- =====================================================================

-- 1. The tables ------------------------------------------------------------------------------
CREATE TABLE venue_requirements (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id    UUID NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    name        TEXT,
    capacity    INTEGER,
    starts_at   TIMESTAMPTZ,
    ends_at     TIMESTAMPTZ,
    layout_code TEXT REFERENCES room_layouts (code),
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Deferred: removing the first requirement renumbers the rest within one save.
    CONSTRAINT uq_venue_requirements_event_position UNIQUE (event_id, position)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT ck_venue_requirements_position CHECK (position >= 0),
    CONSTRAINT ck_venue_requirements_name CHECK (
        name IS NULL OR (btrim(name) <> '' AND char_length(name) <= 100)),
    CONSTRAINT ck_venue_requirements_capacity CHECK (capacity IS NULL OR capacity > 0),
    CONSTRAINT ck_venue_requirements_times_together CHECK ((starts_at IS NULL) = (ends_at IS NULL)),
    CONSTRAINT ck_venue_requirements_period CHECK (starts_at IS NULL OR ends_at > starts_at)
);
-- Story 2.7 AC9: no two requirements on one request share a name, trimmed and case-insensitive.
-- The service checks the list it is sent first, to name the clash; this index is the backstop
-- (backend/STYLE.md: attempt the write and catch the failure). Unnamed draft rows never collide.
CREATE UNIQUE INDEX uq_venue_requirements_event_name
    ON venue_requirements (event_id, lower(btrim(name)))
    WHERE name IS NOT NULL;

COMMENT ON TABLE venue_requirements IS
    'Stories: 2.7, 7.1, 12.1, 8.4, 12.5. One venue an event needs: a name, how many people it must hold, when, and what the room must offer. An event has none (venue_none_required, or not yet specified) or several, in position order. Drafts may hold incomplete rows; submission needs a name and a number of people on each (story 2.7 AC8). Each row has a stable id a booking can later point at.';
COMMENT ON COLUMN venue_requirements.event_id IS 'FK -> events.id. The event that needs this venue.';
COMMENT ON COLUMN venue_requirements.position IS 'Order on the request, from 0. The first requirement (0) is what a booking request copies until story 12.5 lets a booking name its requirement.';
COMMENT ON COLUMN venue_requirements.name IS 'Short name, e.g. "Plenary hall" (story 2.7 AC1). Unique per event, trimmed and case-insensitive (AC9). NULL only while the request is a draft.';
COMMENT ON COLUMN venue_requirements.capacity IS 'How many people the venue must hold: a positive whole number, at most the event''s expected attendance (story 2.7 AC6). NULL only while the request is a draft.';
COMMENT ON COLUMN venue_requirements.starts_at IS 'When the venue is needed from, within the event''s proposed period (story 2.7 AC2, AC5). Set together with ends_at; NULL on a draft takes the event''s times on submission.';
COMMENT ON COLUMN venue_requirements.ends_at IS 'When the venue is needed until. After starts_at, and no later than the event''s end (story 2.7 AC5).';
COMMENT ON COLUMN venue_requirements.layout_code IS 'FK -> room_layouts.code. Required room layout; NULL = no preference.';
COMMENT ON COLUMN venue_requirements.notes IS 'Other requirements in free text (story 2.7 AC1).';
COMMENT ON COLUMN venue_requirements.created_at IS 'Row creation time.';
COMMENT ON COLUMN venue_requirements.updated_at IS 'Last modification time (maintained by trigger).';
COMMENT ON INDEX uq_venue_requirements_event_name IS
    'Story 2.7 AC9: two requirements on one event cannot share a name (trimmed, case-insensitive).';

CREATE TRIGGER trg_venue_requirements_set_updated_at BEFORE UPDATE ON venue_requirements
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE venue_requirement_facilities (
    requirement_id UUID NOT NULL REFERENCES venue_requirements (id) ON DELETE CASCADE,
    facility_code  TEXT NOT NULL REFERENCES facilities (code),
    quantity       INTEGER,
    notes          TEXT,
    PRIMARY KEY (requirement_id, facility_code),
    CONSTRAINT ck_venue_requirement_facilities_quantity CHECK (quantity IS NULL OR quantity > 0)
);
COMMENT ON TABLE venue_requirement_facilities IS
    'Stories: 2.7, 10.3, 11.1, 12.1. Facilities one venue requirement needs, optionally how many. Replaces event_required_facilities (migration 012).';
COMMENT ON COLUMN venue_requirement_facilities.requirement_id IS 'FK -> venue_requirements.id.';
COMMENT ON COLUMN venue_requirement_facilities.facility_code IS 'FK -> facilities.code.';
COMMENT ON COLUMN venue_requirement_facilities.quantity IS 'How many are needed, e.g. 3 breakout rooms. NULL = not stated. Positive whole number.';
COMMENT ON COLUMN venue_requirement_facilities.notes IS 'Free text, e.g. "needs HDMI input".';

-- 2. Story 2.7 AC7: keep what each request recorded, as its "Main venue" ----------------------
INSERT INTO venue_requirements
    (event_id, position, name, capacity, starts_at, ends_at, layout_code, notes)
SELECT
    e.id,
    0,
    'Main venue',
    e.expected_attendance,
    CASE WHEN e.starts_at IS NOT NULL AND e.ends_at IS NOT NULL THEN e.starts_at END,
    CASE WHEN e.starts_at IS NOT NULL AND e.ends_at IS NOT NULL THEN e.ends_at END,
    e.required_layout_code,
    e.venue_requirement_notes
FROM events AS e
WHERE NOT e.venue_none_required
  AND (
      e.required_layout_code IS NOT NULL
      OR e.venue_requirement_notes IS NOT NULL
      OR EXISTS (SELECT 1 FROM event_required_facilities AS f WHERE f.event_id = e.id)
  )
  AND NOT EXISTS (SELECT 1 FROM venue_requirements AS r WHERE r.event_id = e.id);

INSERT INTO venue_requirement_facilities (requirement_id, facility_code, quantity, notes)
SELECT r.id, f.facility_code, f.quantity, f.notes
FROM event_required_facilities AS f
JOIN venue_requirements AS r ON r.event_id = f.event_id AND r.position = 0
ON CONFLICT DO NOTHING;

-- 3. One place for venue requirements --------------------------------------------------------
DROP TABLE event_required_facilities;
ALTER TABLE events DROP COLUMN required_layout_code;
ALTER TABLE events DROP COLUMN venue_requirement_notes;

COMMENT ON COLUMN events.venue_none_required IS
    'TRUE = organiser explicitly stated the event needs no venue, and it has no venue_requirements rows. FALSE with no rows = not yet specified. A request cannot be submitted until one or the other is given (story 2.1 AC10, story 2.7 AC8).';
