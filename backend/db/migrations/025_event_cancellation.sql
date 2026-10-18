-- =====================================================================
-- Migration 025 - story 6.2: the organiser cancels their own event.
--
-- 1. Who cancelled the event, when and why are recorded in columns of their own, so the review
--    decision (4.4/4.5) in decided_at / decided_by_id / decision_reason is kept beside them. The
--    three are written together, only on a CANCELLED event, and the reason is never blank (AC7).
--    An event cancelled before this migration has none of them, which the checks allow.
-- 2. Cancelling closes the event's pending change requests (AC4), so their status gains
--    CANCELLED.
-- =====================================================================

ALTER TABLE events
    ADD COLUMN cancelled_at TIMESTAMPTZ,
    ADD COLUMN cancelled_by_id UUID REFERENCES users (id),
    ADD COLUMN cancellation_reason TEXT,
    ADD CONSTRAINT ck_events_cancellation_complete
        CHECK (num_nonnulls(cancelled_at, cancelled_by_id, cancellation_reason) IN (0, 3)),
    ADD CONSTRAINT ck_events_cancellation_status
        CHECK (cancelled_at IS NULL OR status = 'CANCELLED'),
    ADD CONSTRAINT ck_events_cancellation_reason
        CHECK (btrim(cancellation_reason) <> '');

COMMENT ON COLUMN events.cancelled_at IS
    'When the organiser cancelled the event (story 6.2 AC5). Set with cancelled_by_id and cancellation_reason, and only on a CANCELLED event.';
COMMENT ON COLUMN events.cancelled_by_id IS
    'FK -> users.id. The organiser who cancelled the event (story 6.2 AC5, AC11).';
COMMENT ON COLUMN events.cancellation_reason IS
    'Why the organiser cancelled the event; mandatory, never blank (story 6.2 AC7).';
COMMENT ON COLUMN events.decided_at IS
    'When the review decision (approve/reject) was recorded (story 4.4 AC2, 4.5). A cancellation is recorded in cancelled_at.';
COMMENT ON COLUMN events.decision_reason IS
    'Reason given on rejection (mandatory, story 4.5 AC1). A cancellation''s reason is cancellation_reason.';

ALTER TABLE event_change_requests DROP CONSTRAINT ck_event_change_requests_status;
ALTER TABLE event_change_requests ADD CONSTRAINT ck_event_change_requests_status
    CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN', 'CANCELLED'));

COMMENT ON COLUMN event_change_requests.status IS
    'PENDING, APPROVED, REJECTED, WITHDRAWN or CANCELLED. The organiser may withdraw a PENDING request (story 19.1 AC9); cancelling the event closes it as CANCELLED (story 6.2 AC4).';
