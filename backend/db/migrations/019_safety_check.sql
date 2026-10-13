-- =====================================================================
-- Migration 019 - story 21.1: the Safety Officer's safety check queue.
--
-- Adds AWAITING_SAFETY_CHECK, the status an event sits in while the Safety Officer checks it.
-- Story 21.1 only reads events in it; the transition into it is story 21.2's.
--
-- event_safety_reviews keeps every safety review of an event. facts is a snapshot of the
-- safety-relevant facts the officer reviewed, so a later check can show what has changed since
-- (21.1 AC5). Story 21.1 only reads the table; the review and decision story writes it.
-- =====================================================================

ALTER TABLE events DROP CONSTRAINT ck_events_status;
ALTER TABLE events ADD CONSTRAINT ck_events_status CHECK (status IN (
    'DRAFT', 'UNDER_REVIEW', 'CLARIFICATION_REQUESTED',
    'PLANNING', 'AWAITING_SAFETY_CHECK', 'CONFIRMED', 'COMPLETED', 'CANCELLED', 'REJECTED'));

COMMENT ON COLUMN events.status IS
    'Current lifecycle stage: DRAFT, UNDER_REVIEW, CLARIFICATION_REQUESTED, PLANNING, AWAITING_SAFETY_CHECK, CONFIRMED, COMPLETED, CANCELLED, REJECTED. Every transition is also written to event_status_history.';

CREATE TABLE event_safety_reviews (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id       UUID NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    reviewed_by_id UUID NOT NULL REFERENCES users (id),
    reviewed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    outcome        TEXT NOT NULL,
    notes          TEXT,
    facts          JSONB NOT NULL,
    CONSTRAINT ck_event_safety_reviews_outcome CHECK (outcome IN ('APPROVED', 'CHANGES_REQUESTED'))
);

CREATE INDEX ix_event_safety_reviews_event ON event_safety_reviews (event_id, reviewed_at);

COMMENT ON TABLE event_safety_reviews IS
    'Stories: 21.1. One row per safety review of an event by the Safety Officer, kept so a later check shows the previous reviews and what has changed since the latest (21.1 AC3, AC5). Append-only.';
COMMENT ON COLUMN event_safety_reviews.id IS
    'Primary key.';
COMMENT ON COLUMN event_safety_reviews.event_id IS
    'FK -> events.id. The event reviewed.';
COMMENT ON COLUMN event_safety_reviews.reviewed_by_id IS
    'FK -> users.id. The Safety Officer who made the review.';
COMMENT ON COLUMN event_safety_reviews.reviewed_at IS
    'When the review was made. Previous reviews are listed newest first by it (story 21.1 AC3).';
COMMENT ON COLUMN event_safety_reviews.outcome IS
    'APPROVED: the event passed the check. CHANGES_REQUESTED: the officer sent it back for changes.';
COMMENT ON COLUMN event_safety_reviews.notes IS
    'The officer''s notes on the review. Optional.';
COMMENT ON COLUMN event_safety_reviews.facts IS
    'Snapshot of the safety-relevant facts reviewed: expected_attendance, starts_at, ends_at, venues (approved bookings: id, name, capacity, layout), accessibility (feature codes) and equipment (accepted items: equipment_type, quantity, technical_notes). The next check lists the top-level keys that differ (story 21.1 AC5).';
