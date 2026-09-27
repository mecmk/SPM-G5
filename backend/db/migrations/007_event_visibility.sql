-- =====================================================================
-- Migration 007 - event visibility (story 2.1 AC17), and correct the registration_opens_at
-- comment migration 006 missed.
--
-- AC17: the organiser marks the event Public or Private. Public/Private is a new capability
-- built now, unlike the registration columns (which already existed, reserved for a later
-- story) - so this one needs an actual new column, not just a corrected comment.
--
-- registration_opens_at is now also built by 2.1 AC15 (the organiser may optionally set it),
-- not left for a later story - migration 006 updated registration_required/closes_at's comments
-- but missed this one.
-- =====================================================================

ALTER TABLE events ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN events.is_public IS
    'Whether the event is publicly listed (TRUE) or reachable only by a shared link (FALSE),
    story 2.1 AC17. Defaults to private. No public listing page or link-sharing mechanism exists
    yet - this only captures and displays the organiser''s choice.';
COMMENT ON COLUMN events.registration_opens_at IS
    'When attendees may start registering. Optional (story 2.1 AC15): left blank, registration
    opens immediately once the event is approved. Must be no later than registration_closes_at
    and the proposed start, and is re-checked if the start is moved earlier than an already-saved
    value (AC16).';
