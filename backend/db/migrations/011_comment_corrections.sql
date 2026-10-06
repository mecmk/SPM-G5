-- =====================================================================
-- Migration 011 - correct two events column comments.
--
-- COMMENT ON is the source npm run db:docs generates docs/database/DATA_DICTIONARY.md and
-- docs/database/ERD.excalidraw from, so these comments are the published documentation:
--   * cover_image_url - says what the column holds and nothing else. internal_notes is the only
--     routine field (see migration 003), so this column must not claim to be one.
--   * status - lists the values ck_events_status allows, and nothing else.
-- =====================================================================

COMMENT ON COLUMN events.cover_image_url IS
    'Root-relative path of the event picture, served by the frontend from frontend/public (e.g. /images/events/<file>); NULL shows the placeholder.';

COMMENT ON COLUMN events.status IS
    'Current lifecycle stage: DRAFT, UNDER_REVIEW, CLARIFICATION_REQUESTED, PLANNING, CONFIRMED, COMPLETED, CANCELLED, REJECTED. Every transition is also written to event_status_history.';
