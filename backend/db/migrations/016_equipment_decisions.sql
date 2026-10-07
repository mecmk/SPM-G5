-- =====================================================================
-- Migration 015 - story 16.1: Technical Support accepts or declines an equipment item.
--
-- Migration 014 already allows ACCEPTED and DECLINED, and status_notes holds the reason for
-- declining. This adds who made the decision and when (16.1 AC3). Items decided before this
-- migration, such as the seeded ones, have neither.
-- =====================================================================

ALTER TABLE event_equipment_requests
    ADD COLUMN decided_by_id UUID REFERENCES users (id),
    ADD COLUMN decided_at    TIMESTAMPTZ;

COMMENT ON COLUMN event_equipment_requests.decided_by_id IS
    'FK -> users.id. The Technical Support Staff member who accepted or declined the item (story 16.1 AC3). NULL until it is decided.';
COMMENT ON COLUMN event_equipment_requests.decided_at IS
    'When the item was accepted or declined (story 16.1 AC3). NULL until it is decided.';
