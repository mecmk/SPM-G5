-- =====================================================================
-- Migration 037 - fix f16.2.4 (story 16.2 AC10): an equipment item that a record of units out of
-- service leaves short of every unit it holds is closed as Out of service.
--
-- 1. The status gains OUT_OF_SERVICE: closed and kept for the record, as WITHDRAWN is.
-- 2. When it was closed, and the status it was closed from - REQUESTED (never sent to Technical
--    Support), PENDING or ACCEPTED - are recorded with it. Both are written together, and exactly
--    when the item is OUT_OF_SERVICE: no item was closed so before this migration.
-- =====================================================================

ALTER TABLE event_equipment_requests DROP CONSTRAINT ck_event_equipment_requests_status;
ALTER TABLE event_equipment_requests ADD CONSTRAINT ck_event_equipment_requests_status CHECK (
    status IN ('REQUESTED', 'PENDING', 'ACCEPTED', 'DECLINED', 'UNAVAILABLE', 'CANCELLED', 'WITHDRAWN',
               'OUT_OF_SERVICE'));

ALTER TABLE event_equipment_requests
    ADD COLUMN out_of_service_at   TIMESTAMPTZ,
    ADD COLUMN out_of_service_from TEXT,
    ADD CONSTRAINT ck_event_equipment_requests_out_of_service CHECK (
        (status = 'OUT_OF_SERVICE') = (out_of_service_at IS NOT NULL AND out_of_service_from IS NOT NULL)
        AND num_nonnulls(out_of_service_at, out_of_service_from) IN (0, 2)
        AND (out_of_service_from IS NULL OR out_of_service_from IN ('REQUESTED', 'PENDING', 'ACCEPTED')));

COMMENT ON TABLE event_equipment_requests IS
    'Stories: 2.1 (AC6), 15.1, 15.2, 16.1, 16.2, 17.1, 17.2. One item per equipment type an event needs, with quantity and technical notes. The organiser records them on the request (2.1); the assigned coordinator adds, edits and removes them and submits them to Technical Support (15.1), who accept or decline each (16.1); the coordinator withdraws a sent item no longer needed (17.2); a record of units out of service that leaves an item none of its units closes it (16.2, fix f16.2.4). The units an item holds are separate rows in equipment_reservations.';
COMMENT ON COLUMN event_equipment_requests.status IS
    'REQUESTED: recorded, not yet sent to Technical Support. PENDING: sent, awaiting Technical Support. ACCEPTED or DECLINED: Technical Support''s decision (story 16.1). UNAVAILABLE: the event''s new dates can no longer cover it (story 15.1 AC8). CANCELLED: its event was cancelled (story 6.2), or an approved change removed it once sent (19.2). WITHDRAWN: the coordinator withdrew it once sent, Pending or Accepted (story 17.2). OUT_OF_SERVICE: a record of units out of service left it none of the units it held, so it was closed (story 16.2 AC10, fix f16.2.4).';
COMMENT ON COLUMN event_equipment_requests.out_of_service_at IS
    'When a record of units out of service closed the item (story 16.2 AC10, fix f16.2.4). Set with out_of_service_from, exactly when the item is OUT_OF_SERVICE.';
COMMENT ON COLUMN event_equipment_requests.out_of_service_from IS
    'The status the item was closed from: REQUESTED, PENDING or ACCEPTED (story 16.2 AC10, fix f16.2.4). Technical Support''s queue lists it only if it had been sent to them. Set with out_of_service_at, exactly when the item is OUT_OF_SERVICE.';
