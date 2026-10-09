-- =====================================================================
-- Migration 017 - story 12.5: a booking request names the venue requirement it is for.
--
-- Since story 2.7 an event lists several venue requirements, and until now every booking request
-- carried the event's first (2.7 AC13). A request now names its requirement (12.5 AC1); one that
-- names none is an additional venue (AC5, AC7). An event may hold one pending or approved request
-- per requirement, plus any number of additional venues (AC10-AC12), which the index enforces.
-- =====================================================================

ALTER TABLE venue_bookings
    ADD COLUMN venue_requirement_id UUID REFERENCES venue_requirements (id) ON DELETE SET NULL;

COMMENT ON COLUMN venue_bookings.venue_requirement_id IS
    'FK -> venue_requirements.id. The event''s venue requirement this request is for (story 12.5 AC1), always one of the same event''s requirements (checked in the service). NULL for an additional venue (AC5, AC7), and if the requirement is removed.';

CREATE UNIQUE INDEX uq_venue_bookings_one_per_requirement
    ON venue_bookings (venue_requirement_id)
    WHERE status IN ('PENDING', 'APPROVED');

COMMENT ON INDEX uq_venue_bookings_one_per_requirement IS
    'Story 12.5 AC10-AC12: at most one pending or approved request per venue requirement, so of two requests sent for one requirement at once only the first is written. Additional venues (NULL) are not limited.';
