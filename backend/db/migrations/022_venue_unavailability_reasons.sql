-- =====================================================================
-- Migration 022 - story 9.4 (slice 1): the reasons a venue can be marked unavailable.
--
-- Story 9.4 AC1 gives Venue Staff exactly five reasons: Maintenance, Equipment failure,
-- Renovation, Safety concern and Other, each with a description (PO decision, 13 Oct 2026: the
-- description was first required for Other only). Until now the table allowed MAINTENANCE,
-- RENOVATION, SAFETY, INTERNAL_USE and OTHER, and no period needed a description. From here on:
--
-- 1. INTERNAL_USE is gone. Existing rows become OTHER, and say so: the description is "Internal
--    use", or "Internal use - " followed by what the row already said.
-- 2. EQUIPMENT_FAILURE is added. SAFETY stays the code for "Safety concern".
-- 3. Every row must carry a description (ck_venue_unavailability_description). Existing rows
--    with nothing written get "No description recorded." so the constraint can be added over
--    them.
--
-- Order matters, and this file runs as one transaction (see app/dbtool/migrate.py): the rows
-- are moved before either constraint is swapped in, since Postgres checks a CHECK against every
-- existing row when it is added. The seed has no INTERNAL_USE row and none without a
-- description, so on a clean or freshly reset database the two UPDATEs do nothing.
--
-- The comments from migration 001 are corrected here, not in place: that file has been applied.
-- They named story 9.3 for what is story 9.4, and said 9.4 would treat times outside a venue's
-- operating hours as unavailable, which it does not.
-- =====================================================================

UPDATE venue_unavailability_periods
SET reason = 'OTHER',
    notes = CASE
        WHEN notes IS NULL OR notes !~ '\S' THEN 'Internal use'
        ELSE 'Internal use - ' || notes
    END
WHERE reason = 'INTERNAL_USE';

UPDATE venue_unavailability_periods
SET notes = 'No description recorded.'
WHERE notes IS NULL OR notes !~ '\S';

ALTER TABLE venue_unavailability_periods DROP CONSTRAINT ck_venue_unavailability_reason;
ALTER TABLE venue_unavailability_periods ADD CONSTRAINT ck_venue_unavailability_reason
    CHECK (reason IN ('MAINTENANCE', 'EQUIPMENT_FAILURE', 'RENOVATION', 'SAFETY', 'OTHER'));
ALTER TABLE venue_unavailability_periods ADD CONSTRAINT ck_venue_unavailability_description
    CHECK (notes IS NOT NULL AND notes ~ '\S');

COMMENT ON TABLE venue_unavailability_periods IS
    'Stories: 9.1, 9.4, 10.1, 14.1. Blocks of time a venue cannot be booked, set by Venue Staff even while events are booked there (maintenance, equipment failure, renovation, safety concern or another stated reason), each with a description. Shown as unavailable on the calendar and excluded from availability searches. Periods of one venue may overlap.';
COMMENT ON COLUMN venue_unavailability_periods.ends_at IS
    'End of the blocked period (exclusive). Must be after starts_at (story 9.4 AC5).';
COMMENT ON COLUMN venue_unavailability_periods.reason IS
    'Why the venue is blocked: MAINTENANCE, EQUIPMENT_FAILURE, RENOVATION, SAFETY (shown as Safety concern) or OTHER (story 9.4 AC1).';
COMMENT ON COLUMN venue_unavailability_periods.notes IS
    'The description Venue Staff gave, which every period needs (ck_venue_unavailability_description, story 9.4 AC1).';
COMMENT ON COLUMN venue_unavailability_periods.created_by_id IS
    'FK -> users.id. Venue Staff member who recorded it (story 9.4 AC9). NULL for a period written by the seed.';
COMMENT ON COLUMN venues.operating_hours_start IS
    'Daily opening time (local). NULL = not recorded. Booking requests and venue searches refuse times outside the window (stories 8.1 AC3, 12.1 AC14).';
