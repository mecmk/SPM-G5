-- =====================================================================
-- Migration 024 - story 21.2: the Safety Officer's decision on a safety review.
--
-- The officer approves or requests changes (019's outcomes). When requesting changes the
-- officer records findings: for one of the
-- review factors (safety_review_factors), exactly what must change, optionally tied to the
-- event's venue bookings or its equipment so the coordinator knows which arrangement to rebook.
-- =====================================================================

COMMENT ON TABLE event_safety_reviews IS
    'Stories: 21.1, 21.2. One row per safety review of an event by the Safety Officer, kept so a later check shows the previous reviews and what has changed since the latest (21.1 AC3, AC5), and so confirming checks the latest approval still matches the event (21.2 AC7). Append-only.';
COMMENT ON COLUMN event_safety_reviews.outcome IS
    'APPROVED: the event passed the check and may be confirmed. CHANGES_REQUESTED: sent back to Planning, with findings (event_safety_review_findings).';
-- The decision is the outcome and its findings alone: no free-text notes (story 21.2 AC9).
ALTER TABLE event_safety_reviews DROP COLUMN notes;

CREATE TABLE safety_review_factors (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 100
);

COMMENT ON TABLE safety_review_factors IS
    'Stories: 21.2. The factors a safety review considers (expected attendance, venue capacity and layout, emergency access, ...). Each finding names one.';
COMMENT ON COLUMN safety_review_factors.code IS 'Stable identifier, e.g. EMERGENCY_ACCESS.';
COMMENT ON COLUMN safety_review_factors.name IS 'Display name.';
COMMENT ON COLUMN safety_review_factors.description IS 'Optional longer description: what the officer checks.';
COMMENT ON COLUMN safety_review_factors.sort_order IS 'Display ordering on the review page (ascending).';

CREATE TABLE event_safety_review_findings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id       UUID NOT NULL REFERENCES event_safety_reviews (id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,
    factor_code     TEXT NOT NULL REFERENCES safety_review_factors (code),
    arrangement     TEXT,
    required_change TEXT NOT NULL,
    CONSTRAINT uq_event_safety_review_findings_position UNIQUE (review_id, position),
    CONSTRAINT ck_event_safety_review_findings_arrangement
        CHECK (arrangement IN ('VENUE_BOOKINGS', 'EQUIPMENT')),
    CONSTRAINT ck_event_safety_review_findings_required_change
        CHECK (btrim(required_change) <> '' AND char_length(required_change) <= 2000)
);

COMMENT ON TABLE event_safety_review_findings IS
    'Stories: 21.2. What the Safety Officer requires changed, one row per finding of a CHANGES_REQUESTED review (21.2 AC4). Append-only, with its review.';
COMMENT ON COLUMN event_safety_review_findings.id IS 'Primary key.';
COMMENT ON COLUMN event_safety_review_findings.review_id IS 'FK -> event_safety_reviews.id. The review the finding belongs to.';
COMMENT ON COLUMN event_safety_review_findings.position IS 'Order the officer entered the findings in, from 0.';
COMMENT ON COLUMN event_safety_review_findings.factor_code IS 'FK -> safety_review_factors.code. The factor the finding is about.';
COMMENT ON COLUMN event_safety_review_findings.arrangement IS
    'VENUE_BOOKINGS or EQUIPMENT: the arrangement the officer says must change, flagged on the event page; resubmitting with it unchanged warns the coordinator (21.2 AC12). NULL when the finding needs no rebooking.';
COMMENT ON COLUMN event_safety_review_findings.required_change IS 'Exactly what must change, in the officer''s words. Non-blank, at most 2000 characters (21.2 AC10).';
