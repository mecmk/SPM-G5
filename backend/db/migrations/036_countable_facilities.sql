-- =====================================================================
-- Migration 036 - fix f2.7.5: only countable facilities take a quantity.
--
-- 1. facilities.is_countable says whether a facility is counted (2 projectors) or simply there or
--    not (Wi-Fi). A counted facility needs a quantity on a venue (story 8.3 AC11) and before a
--    request is submitted (story 2.7 AC21); any other takes none (2.7 AC22, 8.3 AC12). The seed
--    sets the flag on a new database; here it is set on the rows an existing one already holds.
-- 2. A quantity already recorded against a facility that is not counted is cleared.
-- 3. Breakout rooms stop being a facility: a breakout room is a venue requirement of its own, with
--    its own number of people and times (story 2.7). A request that asked for them keeps the ask
--    in its requirement's other requirements; a venue's record of them is dropped.
-- =====================================================================

ALTER TABLE facilities ADD COLUMN IF NOT EXISTS is_countable BOOLEAN NOT NULL DEFAULT FALSE;
COMMENT ON COLUMN facilities.is_countable IS
    'TRUE = counted (e.g. 2 projectors): a venue offering it, and a submitted venue requirement asking for it, state how many. FALSE = there or not: no quantity is recorded against it (fix f2.7.5).';

UPDATE facilities SET is_countable = TRUE WHERE code IN ('PROJECTOR', 'WHITEBOARD');

UPDATE venue_facilities vf SET quantity = NULL
FROM facilities f
WHERE f.code = vf.facility_code AND NOT f.is_countable AND vf.quantity IS NOT NULL
    AND vf.facility_code <> 'BREAKOUT_ROOMS';

UPDATE venue_requirement_facilities rf SET quantity = NULL
FROM facilities f
WHERE f.code = rf.facility_code AND NOT f.is_countable AND rf.quantity IS NOT NULL
    AND rf.facility_code <> 'BREAKOUT_ROOMS';

UPDATE venue_requirements r
SET notes = concat_ws(
    E'\n',
    r.notes,
    'Breakout rooms' || coalesce(' x' || rf.quantity, '') || coalesce(' (' || rf.notes || ')', '')
        || '.'
)
FROM venue_requirement_facilities rf
WHERE rf.requirement_id = r.id AND rf.facility_code = 'BREAKOUT_ROOMS';

DELETE FROM venue_requirement_facilities WHERE facility_code = 'BREAKOUT_ROOMS';
DELETE FROM venue_facilities WHERE facility_code = 'BREAKOUT_ROOMS';
DELETE FROM facilities WHERE code = 'BREAKOUT_ROOMS';
