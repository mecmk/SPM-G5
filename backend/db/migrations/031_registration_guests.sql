-- =====================================================================
-- Migration 031 - story 18.5: the guests an attendee registers with them.
--
-- A registration and its guests are one group (AC1): the guests hang off the registration, so
-- withdrawing it or cancelling its event withdraws them too (AC7, AC8), and only a Registered
-- registration's guests take places (AC2). Each guest has a name and optional dietary
-- requirements, and no phone number or email (AC1): guests never become users (AC10). position
-- keeps them in the order the attendee gave them and caps a group at ten guests (AC6). The guests
-- are replaced whole when the attendee changes them (AC3).
-- =====================================================================

CREATE TABLE event_registration_guests (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    registration_id      UUID NOT NULL REFERENCES event_registrations (id) ON DELETE CASCADE,
    position             SMALLINT NOT NULL,
    full_name            TEXT NOT NULL,
    dietary_requirements TEXT,
    CONSTRAINT uq_event_registration_guests_position UNIQUE (registration_id, position),
    CONSTRAINT ck_event_registration_guests_position CHECK (position BETWEEN 1 AND 10),
    CONSTRAINT ck_event_registration_guests_full_name
        CHECK (btrim(full_name) <> '' AND char_length(full_name) <= 200),
    CONSTRAINT ck_event_registration_guests_dietary_requirements
        CHECK (btrim(dietary_requirements) <> '' AND char_length(dietary_requirements) <= 500)
);
COMMENT ON TABLE event_registration_guests IS
    'Stories: 18.5. The guests an attendee brings, registered with them as one group. Each takes a place at the event while the registration is Registered (AC2); written with the registration and replaced whole when the attendee changes them (AC1, AC3).';
COMMENT ON COLUMN event_registration_guests.registration_id IS 'FK -> event_registrations.id. The registration the guest came with; its status is the guest''s (AC7, AC8).';
COMMENT ON COLUMN event_registration_guests.position IS 'The guest''s place in the attendee''s list, from 1. At most 10, so a group is at most 11 (AC6); unique within a registration (uq_event_registration_guests_position).';
COMMENT ON COLUMN event_registration_guests.full_name IS 'The guest''s name, at most 200 characters; never blank (AC6). Guests have no phone number, email or account (AC1, AC10).';
COMMENT ON COLUMN event_registration_guests.dietary_requirements IS 'The guest''s dietary requirements, at most 500 characters (AC1). NULL when none were given, shown as "None"; never blank.';
