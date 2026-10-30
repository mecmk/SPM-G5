-- =====================================================================
-- Migration 032 - story 16.2: Technical Support records equipment out of service. Comments only;
-- no table, column or constraint changes. (032: main has 028; open PRs #134 and #136 each add a
-- 029, one of which will take 030; #138 adds 031.)
--
-- equipment_unavailability_periods (001) already holds what story 16.2 records, and 2.1's
-- availability already takes its units away. Its comments named stories 16.1 and 16.3, from the
-- backlog as first numbered; they now name 16.2 and its rules. Which holds a record leaves short
-- (AC4) is worked out when it is read, from the stock, the holds and these records, so nothing
-- is stored for it.
-- =====================================================================

COMMENT ON TABLE equipment_unavailability_periods IS
    'Stories: 16.2. Units of an equipment type out of service (damaged, under maintenance, lost, ...) for a period, recorded by Technical Support, so they are excluded from availability (2.1, 15.1, 15.2). Records that overlap in time add up and never exceed the stock, checked in the service layer under the equipment type''s row lock, because SQL constraints cannot sum across rows (AC3, AC7).';
COMMENT ON COLUMN equipment_unavailability_periods.quantity IS
    'Units out of service. At least 1, and at most the stock less the units other records have out at any moment of the period (story 16.2 AC3).';
COMMENT ON COLUMN equipment_unavailability_periods.reason IS
    'DAMAGED, MAINTENANCE (shown as Under maintenance), LOST or OTHER (story 16.2 AC1).';
COMMENT ON COLUMN equipment_unavailability_periods.starts_at IS
    'Start of the out-of-service period. Not in the past when recorded; kept once the record is in force (story 16.2 AC3).';
COMMENT ON COLUMN equipment_unavailability_periods.ends_at IS
    'End (exclusive), after the start. NULL = out of service until Technical Support end the record, which sets it to the moment they do (story 16.2 AC1, AC2).';
COMMENT ON COLUMN equipment_unavailability_periods.notes IS
    'Optional note, at most 1,000 characters (story 16.2 AC1).';
COMMENT ON COLUMN equipment_unavailability_periods.created_by_id IS
    'FK -> users.id. The Technical Support Staff member who recorded it (story 16.2 AC1).';
