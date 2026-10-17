-- =====================================================================
-- Migration 020 - every event request has at least one venue requirement (fix f2.7.4).
--
-- Story 2.7 AC14-AC18, AC20: "No venue requirements" is no longer an answer, so no request is
-- created, submitted or approved without a venue requirement, and no draft edit, correction or
-- change request leaves one with none. Comments only - no data or structure changes. COMMENT ON is
-- the source npm run db:docs generates docs/database/DATA_DICTIONARY.md from, and migration 012's
-- comments still describe a request with no venue requirement as one the organiser may choose:
--   * events.venue_none_required - TRUE only on a request saved with it before the fix and given
--     no venue requirement since; adding one clears it, and it is never accepted again.
--   * venue_requirements - every request has at least one; one with none is from before the fix.
-- =====================================================================

COMMENT ON COLUMN events.venue_none_required IS
    'TRUE only on a request saved with "No venue requirements" before fix f2.7.4, which made at least one venue requirement mandatory (story 2.7 AC14), and given no venue requirement since. It is no longer accepted, and the edit that gives the request its first venue requirement - the organiser''s draft edit (story 2.1 AC7) or the coordinator''s correction of its details (story 7.2 AC4) - clears it. FALSE otherwise. A request with no venue_requirements rows is one saved before the fix; it cannot be submitted or approved until it has one (story 2.7 AC15, AC17).';

COMMENT ON TABLE venue_requirements IS
    'Stories: 2.7, 7.1, 12.1, 8.4, 12.5. One venue an event needs: a name, how many people it must hold, when, and what the room must offer. Every request has at least one, in position order (story 2.7 AC14, fix f2.7.4); a request with none is one saved before that fix. Drafts may hold incomplete rows; submission needs a name and a number of people on each (story 2.7 AC8). Each row has a stable id a booking can later point at.';
