-- =====================================================================
-- Migration 010 - a pending venue booking request holds its venue.
--
-- Story 12.1 (Sprint 2) AC3, AC12 and AC14, built as s12.1. Until now only an APPROVED
-- booking blocked a venue, so a coordinator could request a venue already booked or requested
-- for the period, and Venue Staff could then never approve it (found on 27 Sep 2026: Nimbus was
-- able to request Grand Hall, which was already booked for Nimbus itself). From here on a
-- PENDING request holds the venue for its held period too: ex_venue_bookings_no_double_booking
-- covers PENDING and APPROVED rows, so no two of them on one venue can overlap, however they are
-- written. REJECTED, WITHDRAWN and CANCELLED still free the venue. The ranges stay half-open, so
-- periods that only touch are not a clash (AC6).
--
-- Order matters, and this file runs as one transaction (see app/dbtool/migrate.py):
-- 1. Cancel the pending requests that already clash: those overlapping an approved booking, or
--    an earlier pending request that is kept, on the same venue. They could never be approved.
--    Oldest first, so the earliest of several clashing requests keeps its place, and a request
--    that only overlapped one cancelled here is kept. Each gets a reason and an audit row. The
--    seed has no such rows, so on a clean or freshly reset database this step does nothing.
-- 2. Swap the constraint. Postgres checks an exclusion constraint against every existing row
--    when it is added, so this must follow step 1.
-- 3. Refresh the comments npm run db:docs generates docs/database/DATA_DICTIONARY.md from.
-- =====================================================================

DO $$
DECLARE
    pending RECORD;
BEGIN
    FOR pending IN
        SELECT id, event_id, venue_id, held_from, held_until, created_at
        FROM venue_bookings
        WHERE status = 'PENDING'
        ORDER BY created_at, id
    LOOP
        IF EXISTS (
            SELECT 1
            FROM venue_bookings AS other
            WHERE other.venue_id = pending.venue_id
              AND other.id <> pending.id
              AND tstzrange(other.held_from, other.held_until, '[)')
                  && tstzrange(pending.held_from, pending.held_until, '[)')
              AND (
                  other.status = 'APPROVED'
                  OR (other.status = 'PENDING'
                      AND (other.created_at, other.id) < (pending.created_at, pending.id))
              )
        ) THEN
            UPDATE venue_bookings
            SET status = 'CANCELLED',
                decided_at = now(),
                decision_reason = 'Cancelled when pending requests began to hold their venue: '
                    || 'the venue was already booked or requested for this period, so this '
                    || 'request could never have been approved.'
            WHERE id = pending.id;

            INSERT INTO audit_log (actor_id, action, entity_type, entity_id, details)
            VALUES (
                NULL, 'BOOKING_CANCELLED', 'venue_booking', pending.id,
                jsonb_build_object(
                    'event_id', pending.event_id,
                    'venue_id', pending.venue_id,
                    'reason', 'migration 010: overlapped a booking or earlier request of the same venue'
                )
            );
        END IF;
    END LOOP;
END
$$;

ALTER TABLE venue_bookings DROP CONSTRAINT ex_venue_bookings_no_double_booking;
ALTER TABLE venue_bookings ADD CONSTRAINT ex_venue_bookings_no_double_booking EXCLUDE USING gist (
    venue_id WITH =,
    tstzrange(held_from, held_until, '[)') WITH &&
) WHERE (status IN ('PENDING', 'APPROVED'));

COMMENT ON TABLE venue_bookings IS
    'Stories: 12.x, 13.x, 14.x, 9.2. A request by the assigned coordinator to book one venue for an event, and its outcome. PENDING = awaiting Venue Staff, holding the venue (story 12.1 AC3); APPROVED = confirmed booking. No two PENDING or APPROVED bookings of one venue may overlap (ex_venue_bookings_no_double_booking). REJECTED / WITHDRAWN / CANCELLED free the venue. The held period (held_from..held_until) includes setup and teardown time (story 12.2).';
COMMENT ON COLUMN venue_bookings.status IS
    'PENDING, APPROVED, REJECTED, WITHDRAWN or CANCELLED. PENDING and APPROVED hold the venue for the held period (story 12.1 AC3). Only APPROVED bookings appear on the venue calendar (story 9.1).';
