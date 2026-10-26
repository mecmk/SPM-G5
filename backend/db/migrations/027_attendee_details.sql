-- =====================================================================
-- Migration 027 - story 18.4: an attendee's details, kept on their profile and filled in when
-- they register.
--
-- 1. users.phone (001) is also the attendee's contact phone, which their events' organiser and
--    coordinator see on the registration list (AC5). It is required once the attendee has given
--    their details (AC7 as changed by the PO, 25 Oct 2026): ck_users_attendee_details_have_phone.
-- 2. users.dietary_requirements: free text of up to 500 characters (AC6). None recorded is NULL,
--    never a blank string, so the page shows "None" for one value only.
-- 3. users.attendee_details_confirmed_at: when the attendee first gave their details, on their
--    first registration or on My profile. NULL means they were never asked, so their first
--    registration asks (AC2). Once set, the phone number is too; dietary requirements stay
--    optional.
-- users.full_name (001) is the attendee's to change on My profile (AC1 as changed, 25 Oct 2026);
-- the column is unchanged.
-- =====================================================================

ALTER TABLE users
    ADD COLUMN dietary_requirements TEXT,
    ADD COLUMN attendee_details_confirmed_at TIMESTAMPTZ,
    ADD CONSTRAINT ck_users_dietary_requirements
        CHECK (btrim(dietary_requirements) <> '' AND char_length(dietary_requirements) <= 500),
    ADD CONSTRAINT ck_users_attendee_details_have_phone
        CHECK (attendee_details_confirmed_at IS NULL OR phone IS NOT NULL);

COMMENT ON COLUMN users.phone IS
    'Contact phone number. For an attendee, the number their events'' organiser and assigned coordinator see on the registration list (story 18.4 AC5): required once they have given their details (ck_users_attendee_details_have_phone, AC7), with 8 to 15 digits, an optional leading "+", spaces and dashes (the 2.1 AC13 rule, checked by app/common/phone.py). Optional for everyone else.';
COMMENT ON COLUMN users.dietary_requirements IS
    'Attendee only: dietary requirements as free text, at most 500 characters (story 18.4 AC6). NULL when none were given, shown as "None"; never blank (ck_users_dietary_requirements).';
COMMENT ON COLUMN users.attendee_details_confirmed_at IS
    'Attendee only: when the attendee first gave their phone number and dietary requirements, on their first registration or on My profile (story 18.4 AC2). NULL: never asked, so their next registration asks first. Set only with a phone number (ck_users_attendee_details_have_phone).';
COMMENT ON COLUMN users.full_name IS
    'Display name. An attendee changes their own on My profile (story 18.4 AC1); required, at most 200 characters there.';
