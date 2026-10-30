-- =====================================================================
-- Migration 033 - story 17.2: the assigned coordinator withdraws equipment they no longer need.
-- (033: open PRs add a 030 and a 032; #138 added 031.)
--
-- 1. An item sent to Technical Support - Pending or Accepted - is withdrawn rather than deleted,
--    so their record keeps it (AC2, AC4): the status gains WITHDRAWN.
-- 2. Who withdrew it and when are recorded beside its earlier decision (AC3). Both are written
--    together, and exactly when the item is WITHDRAWN: no item was withdrawn before this
--    migration, so every withdrawn item has them.
-- =====================================================================

ALTER TABLE event_equipment_requests DROP CONSTRAINT ck_event_equipment_requests_status;
ALTER TABLE event_equipment_requests ADD CONSTRAINT ck_event_equipment_requests_status CHECK (
    status IN ('REQUESTED', 'PENDING', 'ACCEPTED', 'DECLINED', 'UNAVAILABLE', 'CANCELLED', 'WITHDRAWN'));

ALTER TABLE event_equipment_requests
    ADD COLUMN withdrawn_at    TIMESTAMPTZ,
    ADD COLUMN withdrawn_by_id UUID REFERENCES users (id),
    ADD CONSTRAINT ck_event_equipment_requests_withdrawal CHECK (
        (status = 'WITHDRAWN') = (withdrawn_at IS NOT NULL AND withdrawn_by_id IS NOT NULL)
        AND num_nonnulls(withdrawn_at, withdrawn_by_id) IN (0, 2));

COMMENT ON TABLE event_equipment_requests IS
    'Stories: 2.1 (AC6), 15.1, 15.2, 16.1, 17.1, 17.2. One item per equipment type an event needs, with quantity and technical notes. The organiser records them on the request (2.1); the assigned coordinator adds, edits and removes them and submits them to Technical Support (15.1), who accept or decline each (16.1); the coordinator withdraws a sent item no longer needed (17.2). The units an item holds are separate rows in equipment_reservations.';
COMMENT ON COLUMN event_equipment_requests.status IS
    'REQUESTED: recorded, not yet sent to Technical Support. PENDING: sent, awaiting Technical Support. ACCEPTED or DECLINED: Technical Support''s decision (story 16.1). UNAVAILABLE: the event''s new dates can no longer cover it (story 15.1 AC8). CANCELLED: its event was cancelled (story 6.2), or an approved change removed it once sent (19.2). WITHDRAWN: the coordinator withdrew it once sent, Pending or Accepted (story 17.2).';
COMMENT ON COLUMN event_equipment_requests.withdrawn_at IS
    'When the coordinator withdrew the item (story 17.2 AC3). Set with withdrawn_by_id, exactly when the item is WITHDRAWN.';
COMMENT ON COLUMN event_equipment_requests.withdrawn_by_id IS
    'FK -> users.id. The assigned coordinator who withdrew the item (story 17.2 AC3). Set with withdrawn_at, exactly when the item is WITHDRAWN.';
