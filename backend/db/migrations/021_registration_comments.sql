-- =====================================================================
-- Migration 021 - story 18.1: bring the registration comments up to date. Comments only; no
-- table, column or constraint changes. (021, not 020: fix f2.7.4, PR #108, adds its own 020.)
--
-- Migration 001 wrote event_registrations' comments for the stories as first numbered (18.2 AC2,
-- 18.4 AC4, 18.2 AC3). Those stories were merged into 18.1 (browse and register) and 18.2 (view
-- and withdraw my registrations), so the comments name the criteria as they now stand.
--
-- registration_opens_at said registration opens "once the event is approved". Story 18.1 AC4:
-- registration opens only once the event is Confirmed (21.2), so a blank opening date now reads
-- that way. Applied migrations are never edited (backend/CLAUDE.md), so the correction is here.
-- =====================================================================

COMMENT ON TABLE event_registrations IS
    'Stories: 18.1 (browse and register), 18.2 (view and withdraw), 18.3 (the organiser''s list). An attendee''s registration for an event. An attendee holds at most one active (REGISTERED) registration per event (story 18.1 AC6/AC7) but may register again after withdrawing (story 18.2 AC4), hence the partial unique index rather than a plain unique constraint.';
COMMENT ON COLUMN event_registrations.status IS
    'REGISTERED, WITHDRAWN (by the attendee, story 18.2) or CANCELLED (by ConnectSphere, e.g. the event was cancelled). Only REGISTERED takes a place (story 18.1 AC2).';
COMMENT ON COLUMN event_registrations.registered_at IS
    'When the attendee registered: the moment the closing time and capacity were checked against (story 18.1 AC1, AC7).';
COMMENT ON COLUMN event_registrations.withdrawn_at IS
    'When the attendee withdrew (story 18.2).';
COMMENT ON INDEX uq_event_registrations_active IS
    'Story 18.1 AC6/AC7: one active (REGISTERED) registration per attendee per event, so two registrations sent at once cannot both be kept.';

COMMENT ON COLUMN events.registration_opens_at IS
    'When attendees may start registering. Optional (story 2.1 AC17): left blank, registration opens as soon as the event is Confirmed (story 18.1 AC4). Must be no later than registration_closes_at and the proposed start, and is re-checked if the start is moved earlier than an already-saved value (2.1 AC18).';
