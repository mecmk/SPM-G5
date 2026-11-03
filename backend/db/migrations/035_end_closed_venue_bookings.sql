-- =====================================================================
-- Migration 035 - story 9.5: end the bookings a venue closure covers.
--
-- Saving a closure (story 9.4) now rejects each pending request and cancels each approved booking
-- it covers, instead of marking them "Venue unavailable - alternative needed" and waiting for a
-- replacement (story 12.6, retired by CL-193). So:
--
-- * closure_reason and closure_description record, on the REJECTED request or CANCELLED booking a
--   closure ended, the reason and description of that closure, copied at the save so a later edit
--   or removal of the closure does not change them. A cancelled booking has the release cause
--   VENUE_UNAVAILABLE exactly when they are set; a rejected request says why in decision_reason
--   as well. release_reason stays NULL for VENUE_UNAVAILABLE.
-- * release_cause takes a sixth cause, VENUE_UNAVAILABLE.
-- * A pending replacement raised before 9.5 whose original stops holding its venue, by any path,
--   becomes a normal pending request: the trigger clears replaces_booking_id as well as
--   replaces_live_original (CL-194 (8)). The replacement whose own approval released the original
--   is skipped - it is pending at that moment and keeps its link, as the record of what it
--   replaced.
-- * The bookings still marked when this ships are closed here, with no notices: the marked
--   pending requests are rejected first (so a rejected replacement keeps its link as history),
--   then the marked approved bookings are cancelled with the cause VENUE_UNAVAILABLE. Only those
--   of an event that is Planning, Awaiting Safety Check or Confirmed (story 9.5 AC5); a marked
--   booking of a Cancelled event is left as it is. Who, the reason and the description are the
--   earliest overlapping closure's (by created_at, starts_at, id); when is this moment. With no
--   closure left on record the reason is OTHER with an apology for the missing description.
--   Each booking ended leaves one audit row by the system.
-- * venue_unavailable_marked_at (migration 023) is dropped, last.
-- =====================================================================

-- IF [NOT] EXISTS keeps this safe to run again; tests/venues/test_closure_ends_bookings.py runs it
-- on a database already at 035, taken back to the schema before it.
ALTER TABLE venue_bookings
    ADD COLUMN IF NOT EXISTS closure_reason      TEXT,
    ADD COLUMN IF NOT EXISTS closure_description TEXT;

ALTER TABLE venue_bookings
    DROP CONSTRAINT IF EXISTS ck_venue_bookings_release_cause,
    DROP CONSTRAINT IF EXISTS ck_venue_bookings_closure_reason,
    DROP CONSTRAINT IF EXISTS ck_venue_bookings_closure_fields,
    DROP CONSTRAINT IF EXISTS ck_venue_bookings_closure_release;
ALTER TABLE venue_bookings
    ADD CONSTRAINT ck_venue_bookings_release_cause
        CHECK (release_cause IS NULL OR release_cause IN
               ('EVENT_CANCELLED', 'CHANGE_APPROVED', 'REPLACED', 'SAFETY_REVIEW',
                'COORDINATOR_CANCELLED', 'VENUE_UNAVAILABLE')),
    ADD CONSTRAINT ck_venue_bookings_closure_reason
        CHECK (closure_reason IS NULL OR closure_reason IN
               ('MAINTENANCE', 'EQUIPMENT_FAILURE', 'RENOVATION', 'SAFETY', 'OTHER')),
    ADD CONSTRAINT ck_venue_bookings_closure_fields
        CHECK (num_nonnulls(closure_reason, closure_description) IN (0, 2)
           AND (closure_reason IS NULL OR status IN ('REJECTED', 'CANCELLED'))),
    ADD CONSTRAINT ck_venue_bookings_closure_release
        CHECK (status <> 'CANCELLED'
            OR ((release_cause IS NOT DISTINCT FROM 'VENUE_UNAVAILABLE')
                = (closure_reason IS NOT NULL)));

-- The carve-out and the link end with the original, by any path - except for the replacement whose
-- approval released it, which is still pending while the original is written.
CREATE OR REPLACE FUNCTION clear_replacement_carve_out() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE venue_bookings
    SET replaces_live_original = FALSE,
        replaces_booking_id = NULL
    WHERE replaces_booking_id = NEW.id
      AND status = 'PENDING'
      AND id IS DISTINCT FROM NEW.replaced_by_booking_id;
    RETURN NEW;
END;
$$;

-- Replacements whose original had already stopped holding before this migration keep a link the
-- new trigger would have cleared.
UPDATE venue_bookings AS replacement
SET replaces_live_original = FALSE,
    replaces_booking_id = NULL
FROM venue_bookings AS original
WHERE replacement.status = 'PENDING'
  AND replacement.replaces_booking_id = original.id
  AND original.status NOT IN ('PENDING', 'APPROVED');

-- Close the marked bookings: the pending requests first, then the approved bookings.
WITH marked AS (
    SELECT b.id, b.event_id, b.venue_id, closure.id AS closure_id, closure.created_by_id,
           COALESCE(closure.reason, 'OTHER') AS reason,
           COALESCE(closure.notes,
                    'The closure was no longer on record when story 9.5 shipped.') AS description
    FROM venue_bookings AS b
    JOIN events AS e ON e.id = b.event_id
    LEFT JOIN LATERAL (
        SELECT p.id, p.created_by_id, p.reason, p.notes
        FROM venue_unavailability_periods AS p
        WHERE p.venue_id = b.venue_id
          AND p.starts_at < b.held_until
          AND p.ends_at > b.held_from
        ORDER BY p.created_at, p.starts_at, p.id
        LIMIT 1
    ) AS closure ON TRUE
    WHERE b.status = 'PENDING'
      AND b.venue_unavailable_marked_at IS NOT NULL
      AND e.status IN ('PLANNING', 'AWAITING_SAFETY_CHECK', 'CONFIRMED')
), ended AS (
    UPDATE venue_bookings AS b
    SET status = 'REJECTED',
        decided_by_id = m.created_by_id,
        decided_at = clock_timestamp(),
        decision_reason = 'Venue closed: ' || CASE m.reason
            WHEN 'MAINTENANCE' THEN 'Maintenance'
            WHEN 'EQUIPMENT_FAILURE' THEN 'Equipment failure'
            WHEN 'RENOVATION' THEN 'Renovation'
            WHEN 'SAFETY' THEN 'Safety concern'
            ELSE 'Other' END,
        closure_reason = m.reason,
        closure_description = m.description
    FROM marked AS m
    WHERE b.id = m.id
    RETURNING b.id, b.venue_id, b.event_id, m.closure_id, m.reason
)
INSERT INTO audit_log (actor_id, action, entity_type, entity_id, details)
SELECT NULL, 'BOOKING_REJECTED', 'venue_booking', id,
       jsonb_build_object('venue_id', venue_id, 'event_id', event_id, 'closure_id', closure_id,
                          'reason', reason, 'migration', '035')
FROM ended;

WITH marked AS (
    SELECT b.id, b.event_id, b.venue_id, closure.id AS closure_id, closure.created_by_id,
           COALESCE(closure.reason, 'OTHER') AS reason,
           COALESCE(closure.notes,
                    'The closure was no longer on record when story 9.5 shipped.') AS description
    FROM venue_bookings AS b
    JOIN events AS e ON e.id = b.event_id
    LEFT JOIN LATERAL (
        SELECT p.id, p.created_by_id, p.reason, p.notes
        FROM venue_unavailability_periods AS p
        WHERE p.venue_id = b.venue_id
          AND p.starts_at < b.held_until
          AND p.ends_at > b.held_from
        ORDER BY p.created_at, p.starts_at, p.id
        LIMIT 1
    ) AS closure ON TRUE
    WHERE b.status = 'APPROVED'
      AND b.venue_unavailable_marked_at IS NOT NULL
      AND e.status IN ('PLANNING', 'AWAITING_SAFETY_CHECK', 'CONFIRMED')
), ended AS (
    UPDATE venue_bookings AS b
    SET status = 'CANCELLED',
        cancelled_at = clock_timestamp(),
        release_cause = 'VENUE_UNAVAILABLE',
        released_by_id = m.created_by_id,
        closure_reason = m.reason,
        closure_description = m.description
    FROM marked AS m
    WHERE b.id = m.id
    RETURNING b.id, b.venue_id, b.event_id, m.closure_id, m.reason
)
INSERT INTO audit_log (actor_id, action, entity_type, entity_id, details)
SELECT NULL, 'BOOKING_RELEASED', 'venue_booking', id,
       jsonb_build_object('venue_id', venue_id, 'event_id', event_id, 'closure_id', closure_id,
                          'reason', reason, 'cause', 'VENUE_UNAVAILABLE', 'migration', '035')
FROM ended;

ALTER TABLE venue_bookings DROP COLUMN IF EXISTS venue_unavailable_marked_at;

COMMENT ON COLUMN venue_bookings.closure_reason IS
    'The reason of the venue closure (venue_unavailability_periods.reason) that ended this booking: MAINTENANCE, EQUIPMENT_FAILURE, RENOVATION, SAFETY or OTHER (story 9.5 AC2). Set, with closure_description, on a REJECTED request or a CANCELLED booking a closure ended, copied at the save so a later edit or removal of the closure does not change it; a CANCELLED booking has the release cause VENUE_UNAVAILABLE exactly when it is set (ck_venue_bookings_closure_release). NULL for every other booking.';
COMMENT ON COLUMN venue_bookings.closure_description IS
    'The description of the venue closure that ended this booking (venue_unavailability_periods.notes), copied with closure_reason (story 9.5 AC2). Shown to Venue Staff and the event''s coordinator, never to the organiser. Set or null together with closure_reason (ck_venue_bookings_closure_fields).';
COMMENT ON COLUMN venue_bookings.release_cause IS
    'Why a CANCELLED booking was released: EVENT_CANCELLED (its event was cancelled, story 6.2), CHANGE_APPROVED (an approved change no longer fits it, story 19.2), REPLACED (its replacement was approved, story 12.6), SAFETY_REVIEW (the Safety Officer named it in a finding, story 21.3), COORDINATOR_CANCELLED (its event''s coordinator cancelled it, story 12.8) or VENUE_UNAVAILABLE (a closure of its venue was saved, story 9.5). Set in the release, only on a CANCELLED booking (ck_venue_bookings_release_fields). NULL for a booking never released, and for a CANCELLED row written without one; migration 030 gave every booking cancelled before it a cause.';
COMMENT ON COLUMN venue_bookings.release_reason IS
    'Why the release happened, in the words of whoever caused it: for SAFETY_REVIEW, the required change of each finding that named the booking, in finding order, joined with " | " (story 21.3 AC2, AC9); for COORDINATOR_CANCELLED, the coordinator''s reason (story 12.8 AC1). Required for both (ck_venue_bookings_safety_release_reason, ck_venue_bookings_coordinator_cancel_reason). NULL for every other cause, VENUE_UNAVAILABLE included: its reason is closure_reason.';
COMMENT ON COLUMN venue_bookings.released_by_id IS
    'FK -> users.id. Who released the booking: the Safety Officer for SAFETY_REVIEW, the organiser who cancelled the event for EVENT_CANCELLED, the coordinator whose decision applied the change for CHANGE_APPROVED, the Venue Staff member who approved the replacement for REPLACED (story 21.3), the coordinator who cancelled it for COORDINATOR_CANCELLED (story 12.8), the Venue Staff member who saved the closure for VENUE_UNAVAILABLE (story 9.5). NULL when not released, and for a booking whose releaser migration 030 could not know.';
COMMENT ON COLUMN venue_bookings.decision_reason IS
    'Mandatory when rejected (story 13.2.1 AC1/AC2); for a request a venue closure rejected, "Venue closed: <reason name>" (story 9.5 AC2). On an approved booking released by its replacement (story 12.6 AC3): "Replaced by <venue>".';
COMMENT ON COLUMN venue_bookings.replaces_booking_id IS
    'FK -> venue_bookings.id, with event_id (fk_venue_bookings_replaces), so always a booking of the same event. The booking this one was requested to replace, because Venue Staff made its venue unavailable (story 12.6 AC2, retired by story 9.5, which no longer lets a replacement be requested); NULL for every other booking. Set on a replacement raised before 9.5 and kept on one that was approved or rejected, as the record of what it was for. Cleared, with replaces_live_original, on a PENDING replacement when its original stops holding its venue by any route, so it becomes a normal pending request (story 9.5 AC8); the replacement whose approval released the original is not cleared.';
COMMENT ON COLUMN venue_bookings.replaces_live_original IS
    'TRUE on a replacement raised before story 9.5 (replaces_booking_id) while its original still holds its venue (story 12.6 AC4, AC10): the one-per-requirement index leaves out such a booking while it is PENDING, so it can sit beside its original. trg_venue_bookings_clear_replacement_carve_out sets it FALSE, and clears the link, on a PENDING replacement when the original stops being PENDING or APPROVED by any route - the hold sweep, a release, a cancellation, a venue closure - so the pending replacement is then the requirement''s request (story 9.5 AC8). The index reads it only for a PENDING booking. FALSE for every other booking.';
COMMENT ON FUNCTION clear_replacement_carve_out() IS
    'Story 12.6 AC10, reworded by story 9.5 AC8: clears replaces_live_original and replaces_booking_id on the PENDING replacements of a booking that has just stopped being PENDING or APPROVED (trg_venue_bookings_clear_replacement_carve_out), except the replacement named in the booking''s replaced_by_booking_id, whose approval is releasing it. A decided replacement is left as it was.';
COMMENT ON TRIGGER trg_venue_bookings_clear_replacement_carve_out ON venue_bookings IS
    'Story 9.5 AC8: when a booking stops holding its venue, by whatever route, its pending replacements become normal pending requests for the requirement (clear_replacement_carve_out).';
COMMENT ON CONSTRAINT ck_venue_bookings_release_cause ON venue_bookings IS
    'Story 21.3, story 12.8, story 9.5: release_cause is one of the six causes a booking can be released for.';
COMMENT ON CONSTRAINT ck_venue_bookings_closure_reason ON venue_bookings IS
    'Story 9.5 AC2: closure_reason is one of the five reasons a venue can be closed for.';
COMMENT ON CONSTRAINT ck_venue_bookings_closure_fields ON venue_bookings IS
    'Story 9.5 AC2: closure_reason and closure_description are set together, and only on a REJECTED or CANCELLED booking.';
COMMENT ON CONSTRAINT ck_venue_bookings_closure_release ON venue_bookings IS
    'Story 9.5 AC2: a CANCELLED booking has the release cause VENUE_UNAVAILABLE exactly when a closure ended it, which is when closure_reason is set.';
