-- =====================================================================
-- Migration 015 - story 19.1: guards on event change requests.
--
-- The table has existed since 001, unused until now. Story 19.1 adds two rules the database
-- itself must hold, so they stand even when two submits race (backend/STYLE.md's blocking rule:
-- attempt the write and catch the failure, as uq_events_organiser_name_dates does in 008):
-- 1. AC5/AC6: at most one PENDING request per event and field. Decided or withdrawn requests
--    are excluded by the partial WHERE, so withdrawing one frees its field (AC9).
-- 2. Only the fields an organiser may request (PO decision, Checkpoint 1): schedule (start and
--    end together), expected_attendance, venue_requirements and equipment. The point of contact
--    is not among them - it is updated directly (AC2).
-- No row exists yet, so neither rule can be broken by existing data.
-- =====================================================================

CREATE UNIQUE INDEX uq_event_change_requests_pending_field
    ON event_change_requests (event_id, field_name)
    WHERE status = 'PENDING';

COMMENT ON INDEX uq_event_change_requests_pending_field IS
    'Story 19.1 AC5/AC6: one PENDING change request per event and field.';

ALTER TABLE event_change_requests
    ADD CONSTRAINT ck_event_change_requests_field_name CHECK (field_name IN (
        'schedule', 'expected_attendance', 'venue_requirements', 'equipment'));

COMMENT ON TABLE event_change_requests IS
    'Stories: 7.3, 19.x. A request by the organiser to change an important field (date and time, attendance, venue requirements or equipment) of an event in Planning (story 19.1). The event row is only updated when the coordinator approves (story 19.4 AC1). Values are stored as canonical JSON text, so 19.2 can show them before and after without a column per field.';
COMMENT ON COLUMN event_change_requests.field_name IS
    'Which part of the event the request would change: schedule (starts_at and ends_at together), expected_attendance, venue_requirements or equipment (story 19.1 AC1).';
COMMENT ON COLUMN event_change_requests.current_value IS
    'The value when the request was raised, as canonical JSON text, for display (story 19.2 AC2).';
COMMENT ON COLUMN event_change_requests.proposed_value IS
    'The requested new value, as canonical JSON text, validated by the creation rules (story 19.1 AC3/AC4).';
COMMENT ON COLUMN event_change_requests.status IS
    'PENDING, APPROVED, REJECTED or WITHDRAWN. The organiser may withdraw a PENDING request (story 19.1 AC9).';
