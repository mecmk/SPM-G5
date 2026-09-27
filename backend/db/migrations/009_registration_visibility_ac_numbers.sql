-- =====================================================================
-- Migration 009 - correct the AC numbers in migrations 006/007's comments.
--
-- After 006/007 were applied, the registration-requirement and visibility ACs were renumbered
-- (17/18 and 19) to stop colliding with pre-existing story 2.1 ACs 15/16 (notification wording
-- and the post-submit redirect, already built in the frontend before this work started). 006 and
-- 007 themselves are not edited - once a migration is applied, its file must not change
-- (backend/CLAUDE.md) - so the correction lands here instead, re-issuing the same COMMENT ON
-- statements with the right numbers:
--   registration_required / registration_closes_at: AC15 -> AC17
--   registration_closes_at's AC16 cross-reference   -> AC18
--   is_public: AC17 -> AC19
--   registration_opens_at: AC15 -> AC17, AC16 -> AC18
-- =====================================================================

COMMENT ON COLUMN events.registration_required IS
    'Whether attendees must register (story 2.1 AC17).';
COMMENT ON COLUMN events.registration_capacity IS
    'Not set by story 2.1: registration capacity is always expected_attendance (AC17), not a
    separate value. Reserved for a future story that lets it diverge (originally story 18.5).';
COMMENT ON COLUMN events.registration_closes_at IS
    'Registration deadline. Must not be after the proposed start (story 2.1 AC17), and is
    re-checked if the start is moved earlier than an already-saved deadline (AC18).';
COMMENT ON COLUMN events.is_public IS
    'Whether the event is publicly listed (TRUE) or reachable only by a shared link (FALSE),
    story 2.1 AC19. Defaults to private. No public listing page or link-sharing mechanism exists
    yet - this only captures and displays the organiser''s choice.';
COMMENT ON COLUMN events.registration_opens_at IS
    'When attendees may start registering. Optional (story 2.1 AC17): left blank, registration
    opens immediately once the event is approved. Must be no later than registration_closes_at
    and the proposed start, and is re-checked if the start is moved earlier than an already-saved
    value (AC18).';
