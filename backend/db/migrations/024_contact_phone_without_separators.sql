-- =====================================================================
-- Migration 024 - the point of contact's phone is saved without spaces or dashes (fix f2.1.4).
--
-- Story 2.1 AC21, AC23: the phone is typed after a country or region picker and saved as "+", the
-- calling code and the number, with the spaces and dashes typed removed, e.g. +6591234567 - the
-- server removes them on every save (app/events/schemas.py, _check_contact_phone). This cleans the
-- phones saved before the fix the same way, so a saved phone has one form and the same number
-- typed again compares equal to it. Only spaces and dashes go: a phone saved without a calling
-- code keeps its digits as they are. Other tables' phones (users, client_organisations) are not
-- the point of contact's and are left alone.
-- =====================================================================

UPDATE events
SET contact_phone = translate(contact_phone, ' -', '')
WHERE contact_phone ~ '[ -]';

COMMENT ON COLUMN events.contact_phone IS
    'The point of contact''s phone (story 2.1 AC13): "+", its calling code and the number, without spaces or dashes, e.g. +6591234567 (fix f2.1.4, AC21). 8 to 15 digits, calling code included. One saved before the fix with no calling code keeps its digits; migration 024 removed the spaces and dashes from those saved before it.';
