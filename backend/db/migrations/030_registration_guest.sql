-- =====================================================================
-- Migration 030 - story 18.4 (fix f18.4.1): an attendee may bring one guest when they register.
-- (030, not 028: open PRs #131 and #134 each add a 028, one of which will take 029.)
--
-- The guest is recorded on the registration itself: one at most, so no table of their own. Their
-- name and phone number are required together (AC12); their dietary requirements are optional,
-- and only with a guest. Each guest takes a place (AC13): a registration with one takes two.
-- =====================================================================

ALTER TABLE event_registrations
    ADD COLUMN guest_full_name TEXT,
    ADD COLUMN guest_phone TEXT,
    ADD COLUMN guest_dietary_requirements TEXT,
    ADD CONSTRAINT ck_event_registrations_guest_complete
        CHECK ((guest_full_name IS NULL) = (guest_phone IS NULL)
               AND (guest_dietary_requirements IS NULL OR guest_full_name IS NOT NULL)),
    ADD CONSTRAINT ck_event_registrations_guest_full_name
        CHECK (btrim(guest_full_name) <> '' AND char_length(guest_full_name) <= 200),
    ADD CONSTRAINT ck_event_registrations_guest_phone
        CHECK (btrim(guest_phone) <> '' AND char_length(guest_phone) <= 50),
    ADD CONSTRAINT ck_event_registrations_guest_dietary_requirements
        CHECK (btrim(guest_dietary_requirements) <> ''
               AND char_length(guest_dietary_requirements) <= 500);

COMMENT ON COLUMN event_registrations.guest_full_name IS
    'Story 18.4 AC12: the name of the one guest the attendee brings, at most 200 characters, typed in when they register and never saved to their profile. NULL: no guest. A guest takes a place too (AC13). Never blank (ck_event_registrations_guest_full_name).';
COMMENT ON COLUMN event_registrations.guest_phone IS
    'Story 18.4 AC12: the guest''s phone number, by the attendee''s own rule (AC7, app/common/phone.py). Set exactly when guest_full_name is (ck_event_registrations_guest_complete); never blank.';
COMMENT ON COLUMN event_registrations.guest_dietary_requirements IS
    'Story 18.4 AC12: the guest''s dietary requirements, at most 500 characters (AC6). NULL when none were given, and always when there is no guest (ck_event_registrations_guest_complete); never blank.';
COMMENT ON CONSTRAINT ck_event_registrations_guest_complete ON event_registrations IS
    'Story 18.4 AC12: a guest has both a name and a phone number, or neither; dietary requirements only with a guest.';
