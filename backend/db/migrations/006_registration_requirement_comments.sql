-- =====================================================================
-- Migration 006 - correct which story the registration columns belong to.
--
-- Story 2.1 AC15/AC16: after product review, the registration-requirement capture that was
-- planned as a separate story was merged into 2.1 instead. registration_required and
-- registration_closes_at are built by 2.1 now, not story 2.4 (which no longer exists as a
-- separate story). registration_capacity and registration_opens_at are untouched by 2.1 -
-- registration_capacity is not a field the organiser sets at all (AC15: it is always
-- expected_attendance), and registration_opens_at remains a later story's concern - so their
-- comments keep their original story references.
-- =====================================================================

COMMENT ON TABLE events IS
    'Stories: 2.1, 2.6, 3.x, 4.x, 5.x, 6.x, 7.x, 19.x. An event request and, once approved, the event itself - one row for the whole lifecycle so history is never split across tables. Status drives what each role may do (story 6.1: exactly one current status). Only DRAFT rows may leave mandatory fields empty.';
COMMENT ON COLUMN events.registration_required IS
    'Whether attendees must register (story 2.1 AC15).';
COMMENT ON COLUMN events.registration_capacity IS
    'Not set by story 2.1: registration capacity is always expected_attendance (AC15), not a
    separate value. Reserved for a future story that lets it diverge (originally story 18.5).';
COMMENT ON COLUMN events.registration_closes_at IS
    'Registration deadline. Must not be after the proposed start (story 2.1 AC15), and is
    re-checked if the start is moved earlier than an already-saved deadline (AC16).';
