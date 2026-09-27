-- =====================================================================
-- Migration 008 - story 2.1 AC20: an organiser cannot have two live requests with the same
-- name (trimmed, case-insensitive) and the same proposed start and end.
--
-- A real constraint, not a pre-check in application code (backend/STYLE.md's blocking rule:
-- attempt the write and catch the failure) - the same shape as uq_venues_name. Scoped to one
-- organiser via organiser_id in the index; REJECTED/CANCELLED/COMPLETED are excluded via the
-- partial WHERE, since a dead request should never block a fresh, legitimate resubmission.
-- NULL starts_at/ends_at (a dateless draft) never collides - Postgres never treats two NULLs as
-- equal in a unique index - which is exactly right: the check only applies once both dates are
-- set (AC20).
-- =====================================================================

CREATE UNIQUE INDEX uq_events_organiser_name_dates
    ON events (organiser_id, lower(trim(name)), starts_at, ends_at)
    WHERE status NOT IN ('REJECTED', 'CANCELLED', 'COMPLETED');

COMMENT ON INDEX uq_events_organiser_name_dates IS
    'Story 2.1 AC20: one organiser cannot have two live requests (any status except REJECTED,
    CANCELLED or COMPLETED) with the same name and the same proposed start/end.';
