-- =====================================================================
-- Migration 034 - story 12.8: the coordinator cancels an approved venue booking.
--
-- The assigned coordinator may release one approved booking of their event, with a reason,
-- without cancelling the event. It goes through the release every other path uses (story 21.3),
-- so it is one more release_cause, COORDINATOR_CANCELLED, and like the safety review's it always
-- records why (AC1, AC9).
-- =====================================================================

ALTER TABLE venue_bookings
    DROP CONSTRAINT ck_venue_bookings_release_cause,
    ADD CONSTRAINT ck_venue_bookings_release_cause
        CHECK (release_cause IS NULL OR release_cause IN
               ('EVENT_CANCELLED', 'CHANGE_APPROVED', 'REPLACED', 'SAFETY_REVIEW',
                'COORDINATOR_CANCELLED')),
    ADD CONSTRAINT ck_venue_bookings_coordinator_cancel_reason
        CHECK (release_cause IS DISTINCT FROM 'COORDINATOR_CANCELLED' OR release_reason IS NOT NULL);

COMMENT ON COLUMN venue_bookings.release_cause IS
    'Why a CANCELLED booking was released: EVENT_CANCELLED (its event was cancelled, story 6.2), CHANGE_APPROVED (an approved change no longer fits it, story 19.2), REPLACED (its replacement was approved, story 12.6), SAFETY_REVIEW (the Safety Officer named it in a finding, story 21.3) or COORDINATOR_CANCELLED (its event''s coordinator cancelled it, story 12.8). Set in the release, only on a CANCELLED booking (ck_venue_bookings_release_fields). NULL for a booking never released, and for a CANCELLED row written without one; migration 030 gave every booking cancelled before it a cause.';
COMMENT ON COLUMN venue_bookings.release_reason IS
    'Why the release happened, in the words of whoever caused it: for SAFETY_REVIEW, the required change of each finding that named the booking, in finding order, joined with " | " (story 21.3 AC2, AC9); for COORDINATOR_CANCELLED, the coordinator''s reason (story 12.8 AC1). Required for both (ck_venue_bookings_safety_release_reason, ck_venue_bookings_coordinator_cancel_reason). NULL for every other cause.';
COMMENT ON COLUMN venue_bookings.released_by_id IS
    'FK -> users.id. Who released the booking: the Safety Officer for SAFETY_REVIEW, the organiser who cancelled the event for EVENT_CANCELLED, the coordinator whose decision applied the change for CHANGE_APPROVED, the Venue Staff member who approved the replacement for REPLACED (story 21.3), the coordinator who cancelled it for COORDINATOR_CANCELLED (story 12.8). NULL when not released, and for a booking whose releaser migration 030 could not know.';
COMMENT ON CONSTRAINT ck_venue_bookings_release_cause ON venue_bookings IS
    'Story 21.3, story 12.8: release_cause is one of the five causes a booking can be released for.';
COMMENT ON CONSTRAINT ck_venue_bookings_coordinator_cancel_reason ON venue_bookings IS
    'Story 12.8 AC1: a booking its coordinator cancelled always records the reason they gave.';
