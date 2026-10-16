-- =====================================================================
-- Migration 023 - story 9.4: marking the bookings an unavailability period affects.
--
-- Story 9.4 AC3: each pending or approved booking whose held period overlaps a period a venue is
-- unavailable for is marked "Venue unavailable - alternative needed", and the mark follows the
-- period (AC6): set when a booking becomes overlapped, kept while any period still overlaps it,
-- cleared when none does. The mark is a column of its own rather than a new booking status, so a
-- booking's status, venue and period never change, and the exclusion constraint and the
-- one-per-requirement index, which key on status, are untouched.
--
-- It records when the booking was first marked, not which period marked it: periods of one
-- venue may overlap, so the mark is re-evaluated against all of them (recheck_venue_bookings).
-- Nothing is backfilled: no booking has been marked before this migration, and the next change
-- to a venue's periods marks the bookings it overlaps.
-- =====================================================================

ALTER TABLE venue_bookings ADD COLUMN venue_unavailable_marked_at TIMESTAMPTZ;

COMMENT ON COLUMN venue_bookings.venue_unavailable_marked_at IS
    'When the booking was marked "Venue unavailable - alternative needed" (story 9.4 AC3): set while a pending or approved booking''s held period overlaps one of its venue''s unavailability periods, kept while any still does, and cleared when none does (AC6). NULL when unmarked. A value left on a booking that is no longer pending or approved is history: readers ignore it and nothing clears it.';
