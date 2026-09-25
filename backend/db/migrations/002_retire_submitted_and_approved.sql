-- =====================================================================
-- Migration 002 - retire SUBMITTED and APPROVED as event statuses.
--
-- Bug b6.1.1, confirmed team decision: SUBMITTED and APPROVED are no longer real states an
-- event can sit in - submitting a draft now goes straight to UNDER_REVIEW, and approving a
-- request now goes straight to PLANNING, with no separate in-between status. CONFIRMED is
-- unaffected. New final set (8): DRAFT, UNDER_REVIEW, CLARIFICATION_REQUESTED, PLANNING,
-- CONFIRMED, COMPLETED, CANCELLED, REJECTED.
--
-- Order matters, and this file runs as one transaction (see app/dbtool/migrate.py):
-- 1. Record the migration itself in event_status_history for every event it affects, while
--    events.status still holds the old value (so "from_status" reads correctly).
-- 2. Transform events.status.
-- 3. Tighten ck_events_status. Postgres validates a CHECK against every existing row the
--    moment it is (re)added, so doing this before step 2 would fail on any row still holding
--    SUBMITTED or APPROVED.
--
-- event_status_history.from_status/to_status carry no CHECK constraint of their own (see
-- 001_initial_schema.sql) and the table's own rows are never rewritten (story 6.4 AC2) - a
-- historical row that already recorded a transition through SUBMITTED or APPROVED is left
-- exactly as it is. It remains an accurate record of what the event's status genuinely was at
-- that time; nothing about removing the value from the CHECK constraint invalidates history
-- that predates this migration.
-- =====================================================================

INSERT INTO event_status_history (event_id, from_status, to_status, changed_by_id, changed_at, reason)
SELECT id, 'SUBMITTED', 'UNDER_REVIEW', NULL, now(),
       'Status model migration (002): SUBMITTED retired; existing SUBMITTED events moved to UNDER_REVIEW.'
FROM events WHERE status = 'SUBMITTED';

INSERT INTO event_status_history (event_id, from_status, to_status, changed_by_id, changed_at, reason)
SELECT id, 'APPROVED', 'PLANNING', NULL, now(),
       'Status model migration (002): APPROVED retired; existing APPROVED events moved to PLANNING.'
FROM events WHERE status = 'APPROVED';

UPDATE events SET status = 'UNDER_REVIEW' WHERE status = 'SUBMITTED';
UPDATE events SET status = 'PLANNING' WHERE status = 'APPROVED';

ALTER TABLE events DROP CONSTRAINT ck_events_status;
ALTER TABLE events ADD CONSTRAINT ck_events_status CHECK (status IN (
    'DRAFT', 'UNDER_REVIEW', 'CLARIFICATION_REQUESTED',
    'PLANNING', 'CONFIRMED', 'COMPLETED', 'CANCELLED', 'REJECTED'));

COMMENT ON COLUMN events.status IS
    'Current lifecycle stage: DRAFT, UNDER_REVIEW, CLARIFICATION_REQUESTED, PLANNING, CONFIRMED, COMPLETED, CANCELLED, REJECTED. SUBMITTED and APPROVED were retired by migration 002 (bug b6.1.1) - submitting now goes straight to UNDER_REVIEW and approving straight to PLANNING. Every transition is also written to event_status_history.';
