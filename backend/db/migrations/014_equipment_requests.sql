-- =====================================================================
-- Migration 014 - story 15.1: the coordinator submits an event's equipment to Technical Support.
--
-- Until now story 2.1 marked an equipment line RESERVED the moment it held the units, when the
-- organiser submitted the request, and the status check allowed values no code ever wrote. Story
-- 15.1 separates a held item that is not yet sent (REQUESTED) from one sent to Technical Support
-- and awaiting its decision (PENDING); Technical Support's decisions are ACCEPTED and DECLINED
-- (story 16.1); UNAVAILABLE flags an item the event's new dates can no longer cover (15.1 AC8);
-- CANCELLED belongs to a cancelled event (story 6.2). Whether an item holds stock is recorded by
-- its equipment_reservations row, not by its status.
--
-- This file runs as one transaction (app/dbtool/migrate.py). Order matters:
-- 1. Drop the old check, so the rows can take their new values.
-- 2. Map the old values: a RESERVED line was held but never sent, so it becomes REQUESTED; the
--    unused UNDER_REVIEW and PARTIALLY_RESERVED become PENDING. The seed has none of these, so on
--    a clean or freshly reset database this step does nothing.
-- 3. Add the new check, and who sent each item and when (15.1 AC1). Items sent before this
--    migration have neither.
-- 4. Refresh the comments npm run db:docs generates docs/database/DATA_DICTIONARY.md from.
-- =====================================================================

ALTER TABLE event_equipment_requests DROP CONSTRAINT ck_event_equipment_requests_status;

UPDATE event_equipment_requests SET status = 'REQUESTED' WHERE status = 'RESERVED';
UPDATE event_equipment_requests SET status = 'PENDING'
WHERE status IN ('UNDER_REVIEW', 'PARTIALLY_RESERVED');

ALTER TABLE event_equipment_requests ADD CONSTRAINT ck_event_equipment_requests_status CHECK (
    status IN ('REQUESTED', 'PENDING', 'ACCEPTED', 'DECLINED', 'UNAVAILABLE', 'CANCELLED'));

ALTER TABLE event_equipment_requests
    ADD COLUMN submitted_by_id UUID REFERENCES users (id),
    ADD COLUMN submitted_at    TIMESTAMPTZ;

COMMENT ON TABLE event_equipment_requests IS
    'Stories: 2.1 (AC6), 15.1, 15.2, 16.1, 17.1. One item per equipment type an event needs, with quantity and technical notes. The organiser records them on the request (2.1); the assigned coordinator adds, edits and removes them and submits them to Technical Support (15.1), who accept or decline each (16.1). The units an item holds are separate rows in equipment_reservations.';
COMMENT ON COLUMN event_equipment_requests.quantity IS
    'Units requested. Positive whole number (story 2.1 AC3, 15.1 AC4).';
COMMENT ON COLUMN event_equipment_requests.technical_notes IS
    'Technical requirements for this item. Optional; at most 1,000 characters when the coordinator records it (story 15.1 AC5).';
COMMENT ON COLUMN event_equipment_requests.status IS
    'REQUESTED: recorded, not yet sent to Technical Support. PENDING: sent, awaiting Technical Support. ACCEPTED or DECLINED: Technical Support''s decision (story 16.1). UNAVAILABLE: the event''s new dates can no longer cover it (story 15.1 AC8). CANCELLED: its event was cancelled (story 6.2).';
COMMENT ON COLUMN event_equipment_requests.status_notes IS
    'Technical Support''s note on its decision, such as the reason for declining (story 16.1).';
COMMENT ON COLUMN event_equipment_requests.created_by_id IS
    'FK -> users.id. Who recorded the item: the organiser (story 2.1) or the coordinator (story 15.1).';
COMMENT ON COLUMN event_equipment_requests.submitted_by_id IS
    'FK -> users.id. The coordinator who sent the item to Technical Support (story 15.1 AC1). NULL until it is sent.';
COMMENT ON COLUMN event_equipment_requests.submitted_at IS
    'When the item was last sent to Technical Support: on submission, or again when the event''s dates changed (story 15.1 AC1, AC8). NULL until it is sent.';

COMMENT ON TABLE equipment_reservations IS
    'Stories: 2.1, 15.1, 16.1, 16.2, 17.1. A hold of N units of an equipment type for an event over a period: placed when an item is recorded on a submitted event (2.1 AC11, 15.1 AC2) and kept, as the reservation, once Technical Support accepts it (16.1). Availability for a period = equipment_types.total_quantity - SUM(quantity - released_quantity) of overlapping RESERVED rows - overlapping out-of-service quantities. Never over-committing is enforced in the service layer under a row lock on the equipment type, because SQL constraints cannot sum across rows.';
COMMENT ON COLUMN equipment_reservations.equipment_request_id IS
    'FK -> event_equipment_requests.id. The item this hold is for. NULL once the item is removed (its hold is released first, story 15.1 AC2).';
COMMENT ON COLUMN equipment_reservations.starts_at IS
    'Start of the hold: the event''s start (story 15.1 AC2).';
COMMENT ON COLUMN equipment_reservations.reserved_by_id IS
    'FK -> users.id. Who placed the hold: the organiser on submitting (story 2.1 AC11) or the coordinator (story 15.1).';
COMMENT ON COLUMN equipment_reservations.status IS
    'RESERVED while any units are still held; RELEASED once released_quantity = quantity (an item removed, declined or moved to new dates, story 15.1 AC2/AC8).';
