-- =====================================================================
-- Migration 028 - story 7.4: the event's change history.
--
-- One row per field a save changed on a submitted event: a coordinator's correction or internal
-- notes (7.2), the organiser's point of contact (19.1) or an approved change request (19.2).
-- Written in the save's own transaction (AC2). seq is drawn as the row is inserted, while the
-- save holds the event's row lock, so saves to one event read in the order they happened (AC7);
-- changed_at is the transaction's time, shared by every field of one save (AC4).
-- =====================================================================

CREATE TABLE event_change_history (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seq                  BIGINT GENERATED ALWAYS AS IDENTITY,
    event_id             UUID NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    field_name           TEXT NOT NULL,
    old_value            JSONB,
    new_value            JSONB,
    changed_by_id        UUID NOT NULL REFERENCES users (id),
    changed_by_role_code TEXT NOT NULL REFERENCES roles (code),
    change_request_id    UUID REFERENCES event_change_requests (id),
    changed_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE event_change_history IS
    'Stories: 7.4. Append-only record of each field changed on an event after submission: old and new value, who changed it with their role, and when. Rows are never updated or deleted (story 7.4 AC5).';
COMMENT ON COLUMN event_change_history.seq IS 'Insertion order. The history is read newest first by this, not by changed_at, which one save''s fields share (story 7.4 AC1, AC7).';
COMMENT ON COLUMN event_change_history.event_id IS 'FK -> events.id.';
COMMENT ON COLUMN event_change_history.field_name IS 'The event field that changed, e.g. expected_attendance, internal_notes, venue_requirements. internal_notes rows are shown only to coordinators (story 7.4 AC5, AC6).';
COMMENT ON COLUMN event_change_history.old_value IS 'The value before the save, as JSON (a list for venue requirements, accessibility needs and equipment). NULL when the field was empty.';
COMMENT ON COLUMN event_change_history.new_value IS 'The value after the save, as JSON. NULL when the field was cleared.';
COMMENT ON COLUMN event_change_history.changed_by_id IS 'FK -> users.id. Who saved the change.';
COMMENT ON COLUMN event_change_history.changed_by_role_code IS 'FK -> roles.code. Their role when they saved it (story 7.4 AC1).';
COMMENT ON COLUMN event_change_history.change_request_id IS 'FK -> event_change_requests.id. The change request whose approval made the change (story 7.4 AC4); NULL for a direct edit.';
COMMENT ON COLUMN event_change_history.changed_at IS 'When the save was made; the same for every field of one save (story 7.4 AC4).';
CREATE INDEX ix_event_change_history_event ON event_change_history (event_id, seq);
