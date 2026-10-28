-- =====================================================================
-- Migration 029 - story 21.3: release the venue bookings a safety finding names.
--
-- When the Safety Officer requests changes, a finding about venue bookings may name some of the
-- event's approved bookings. Recording the decision releases each one: it becomes CANCELLED, as a
-- booking released by story 6.2 or 19.2 does, and now records how and why.
--
-- * release_cause says which path released a CANCELLED booking, release_reason why (the finding's
--   required change, for a safety release) and released_by_id who. They are set together with the
--   status, only on a CANCELLED booking. A CANCELLED booking is not required to have a cause: the
--   backfill below gives every existing one, but a row written by a test or a script may lack one.
-- * event_safety_finding_bookings links a finding to the bookings it named, so each review round
--   can show what it released (AC9). A booking may be named by two findings of one decision.
-- =====================================================================

ALTER TABLE venue_bookings
    ADD COLUMN release_cause   TEXT,
    ADD COLUMN release_reason  TEXT,
    ADD COLUMN released_by_id  UUID REFERENCES users (id);

-- backfill start
-- A booking cancelled before this migration gets the cause its release has always had: the
-- replacement whose approval released it, else its event's cancellation, else an approved change.
-- Only a replacement's approver and an event's canceller are on record, so the releaser of any
-- other booking stays NULL. Safe to run again: it touches only a CANCELLED booking with no cause.
UPDATE venue_bookings AS original
SET release_cause = 'REPLACED', released_by_id = replacement.decided_by_id
FROM venue_bookings AS replacement
WHERE original.status = 'CANCELLED'
  AND original.release_cause IS NULL
  AND original.replaced_by_booking_id = replacement.id;

UPDATE venue_bookings AS booking
SET release_cause = 'EVENT_CANCELLED', released_by_id = ev.cancelled_by_id
FROM events AS ev
WHERE booking.event_id = ev.id
  AND booking.status = 'CANCELLED'
  AND booking.release_cause IS NULL
  AND ev.status = 'CANCELLED';

UPDATE venue_bookings
SET release_cause = 'CHANGE_APPROVED'
WHERE status = 'CANCELLED'
  AND release_cause IS NULL;
-- backfill end

ALTER TABLE venue_bookings
    ADD CONSTRAINT ck_venue_bookings_release_cause
        CHECK (release_cause IS NULL OR release_cause IN
               ('EVENT_CANCELLED', 'CHANGE_APPROVED', 'REPLACED', 'SAFETY_REVIEW')),
    ADD CONSTRAINT ck_venue_bookings_release_fields
        CHECK ((release_cause IS NULL AND release_reason IS NULL AND released_by_id IS NULL)
            OR (release_cause IS NOT NULL AND status = 'CANCELLED')),
    ADD CONSTRAINT ck_venue_bookings_safety_release_reason
        CHECK (release_cause IS DISTINCT FROM 'SAFETY_REVIEW' OR release_reason IS NOT NULL);

CREATE TABLE event_safety_finding_bookings (
    finding_id UUID NOT NULL
        REFERENCES event_safety_review_findings (id) ON DELETE CASCADE,
    booking_id UUID NOT NULL
        REFERENCES venue_bookings (id) ON DELETE CASCADE,
    CONSTRAINT pk_event_safety_finding_bookings PRIMARY KEY (finding_id, booking_id)
);
CREATE INDEX ix_event_safety_finding_bookings_booking ON event_safety_finding_bookings (booking_id);

COMMENT ON COLUMN venue_bookings.release_cause IS
    'Why a CANCELLED booking was released: EVENT_CANCELLED (its event was cancelled, story 6.2), CHANGE_APPROVED (an approved change no longer fits it, story 19.2), REPLACED (its replacement was approved, story 12.6) or SAFETY_REVIEW (the Safety Officer named it in a finding, story 21.3). Set in the release, only on a CANCELLED booking (ck_venue_bookings_release_fields). NULL for a booking never released, and for a CANCELLED row written without one; migration 029 gave every booking cancelled before it a cause.';
COMMENT ON COLUMN venue_bookings.release_reason IS
    'Why the release happened, in the words of whoever caused it: for SAFETY_REVIEW, the required change of each finding that named the booking, in finding order, joined with " | " (story 21.3 AC2, AC9); required then (ck_venue_bookings_safety_release_reason). NULL for every other cause.';
COMMENT ON COLUMN venue_bookings.released_by_id IS
    'FK -> users.id. Who released the booking: the Safety Officer for SAFETY_REVIEW, the organiser who cancelled the event for EVENT_CANCELLED, the coordinator whose decision applied the change for CHANGE_APPROVED, the Venue Staff member who approved the replacement for REPLACED (story 21.3). NULL when not released, and for a booking whose releaser migration 029 could not know.';
COMMENT ON CONSTRAINT ck_venue_bookings_release_cause ON venue_bookings IS
    'Story 21.3: release_cause is one of the four causes a booking can be released for.';
COMMENT ON CONSTRAINT ck_venue_bookings_release_fields ON venue_bookings IS
    'Story 21.3: a release cause is recorded only on a CANCELLED booking, and a reason or releaser only with a cause.';
COMMENT ON CONSTRAINT ck_venue_bookings_safety_release_reason ON venue_bookings IS
    'Story 21.3 AC2: a booking released by the safety review always records the required change.';

COMMENT ON TABLE event_safety_finding_bookings IS
    'Story 21.3 AC1, AC9. The venue bookings a safety finding named, which the decision released in the same step. Written only by the Safety Officer''s decision and append-only with its finding; a booking may be named by two findings of one decision and is released once. The service, not the database, checks that the booking belongs to the finding''s event.';
COMMENT ON COLUMN event_safety_finding_bookings.finding_id IS
    'FK -> event_safety_review_findings.id (cascade). The finding that named the booking.';
COMMENT ON COLUMN event_safety_finding_bookings.booking_id IS
    'FK -> venue_bookings.id (cascade). The booking the finding named; an APPROVED booking of the reviewed event when named.';
COMMENT ON CONSTRAINT pk_event_safety_finding_bookings ON event_safety_finding_bookings IS
    'Story 21.3 AC9: a finding names a booking once.';
COMMENT ON INDEX ix_event_safety_finding_bookings_booking IS
    'Story 21.3: the findings that named a booking.';
