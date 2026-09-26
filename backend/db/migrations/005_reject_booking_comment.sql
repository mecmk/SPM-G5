-- =====================================================================
-- Migration 005 - correct the decision_reason column comment for story 13.2.1.
--
-- Story 13.2.1: rejecting a venue booking with a mandatory reason is now implemented (it was
-- described as future story 13.3 AC1 when 001_initial_schema.sql was written). Update the
-- column comment - the source npm run db:docs generates docs/database/DATA_DICTIONARY.md from -
-- so it no longer describes shipped behaviour as a future story.
--
-- alternative_suggestion (old story 13.3 AC2) is left alone: it is still optional and
-- unimplemented, so its comment is still accurate.
-- =====================================================================

COMMENT ON COLUMN venue_bookings.decision_reason IS
    'Mandatory when rejected (story 13.2.1 AC1/AC2).';
