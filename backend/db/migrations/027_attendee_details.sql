-- =====================================================================
-- Migration 027 - story 18.4: an attendee's details, kept on their profile and filled in when
-- they register.
--
-- 1. users.phone (001) is also the attendee's contact phone, which their events' organiser and
--    coordinator see on the registration list (AC5). Only its comment changes.
-- 2. users.dietary_requirements: free text of up to 500 characters (AC6). None recorded is NULL,
--    never a blank string, so the page shows "None" for one value only.
-- 3. users.attendee_details_confirmed_at: when the attendee first gave their details, on their
--    first registration or on My profile. NULL means they were never asked, so their first
--    registration asks (AC2). Phone and dietary requirements may both be NULL once confirmed:
--    both are optional.
-- =====================================================================

ALTER TABLE users
    ADD COLUMN dietary_requirements TEXT,
    ADD COLUMN attendee_details_confirmed_at TIMESTAMPTZ,
    ADD CONSTRAINT ck_users_dietary_requirements
        CHECK (btrim(dietary_requirements) <> '' AND char_length(dietary_requirements) <= 500);

COMMENT ON COLUMN users.phone IS
    'Contact phone number (optional). For an attendee, the number their events'' organiser and assigned coordinator see on the registration list (story 18.4 AC5); when given, 8 to 15 digits with an optional leading "+", spaces and dashes (the 2.1 AC13 rule, checked by app/common/phone.py).';
COMMENT ON COLUMN users.dietary_requirements IS
    'Attendee only: dietary requirements as free text, at most 500 characters (story 18.4 AC6). NULL when none were given, shown as "None"; never blank (ck_users_dietary_requirements).';
COMMENT ON COLUMN users.attendee_details_confirmed_at IS
    'Attendee only: when the attendee first gave their phone number and dietary requirements, on their first registration or on My profile (story 18.4 AC2). NULL: never asked, so their next registration asks first.';
