-- =====================================================================
-- Migration 003 - correct which events columns are documented as "routine fields".
--
-- Story 7.2.2: the routine-information edit screen was narrowed to internal_notes only
-- (backend/app/events/service.py's _ROUTINE_FIELDS). description, contact_name, contact_email
-- and contact_phone are no longer editable through that screen, so their column comments -
-- which are the source npm run db:docs generates docs/database/DATA_DICTIONARY.md from - can no
-- longer say "Routine field". internal_notes is the only column that comment still applies to.
-- =====================================================================

COMMENT ON COLUMN events.description IS
    'Longer description / general programme (story 2.1 AC1).';
COMMENT ON COLUMN events.contact_name IS
    'On-the-day contact person.';
COMMENT ON COLUMN events.contact_email IS
    'Contact e-mail.';
COMMENT ON COLUMN events.contact_phone IS
    'Contact phone.';
