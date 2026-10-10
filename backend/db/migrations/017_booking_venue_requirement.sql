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

-- Requests made before this story were each for their event's first requirement (2.7 AC13).
-- The oldest pending or approved one on each event is linked to it; any others become
-- additional venues, so the index below refuses none of them.
UPDATE venue_bookings AS b
SET venue_requirement_id = first_requirement.id
FROM (
    SELECT DISTINCT ON (event_id) id, event_id
    FROM venue_requirements
    ORDER BY event_id, position
) AS first_requirement
WHERE b.event_id = first_requirement.event_id
  AND b.id = (
      SELECT oldest.id
      FROM venue_bookings AS oldest
      WHERE oldest.event_id = b.event_id
        AND oldest.status IN ('PENDING', 'APPROVED')
      ORDER BY oldest.created_at, oldest.id
      LIMIT 1
  );

CREATE UNIQUE INDEX uq_venue_bookings_one_per_requirement
    ON venue_bookings (venue_requirement_id)
    WHERE status IN ('PENDING', 'APPROVED');

-- Migration 012 described the first requirement as the one every request copies.
COMMENT ON COLUMN venue_requirements.position IS
    'Order on the request, from 0: the order the event''s page and the catalogue''s banner list them in, and Find a venue selects the first that has no pending or approved request (story 12.5 AC2).';

COMMENT ON INDEX uq_venue_bookings_one_per_requirement IS
    'Story 12.5 AC10-AC12: at most one pending or approved request per venue requirement, so of two requests sent for one requirement at once only the first is written. Additional venues (NULL) are not limited.';
