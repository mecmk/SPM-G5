-- =====================================================================
-- Migration 018 - story 12.7: tentative venue holds expire.
--
-- Week 7 customer change #4 (CL-063). Since migration 010 a pending booking request holds its
-- venue, and until now it held it until Venue Staff decided or the coordinator withdrew it. Every
-- hold now has an expiry (12.7 AC1): the request is raised with a default one, which only Venue
-- Staff can change, and never later than the start of its booked period (AC5, checked in the
-- service). Venue Staff must approve the request before then; at its expiry the request becomes
-- EXPIRED (AC3). Like REJECTED, WITHDRAWN and CANCELLED, an EXPIRED request holds nothing and
-- covers no venue requirement (AC6, AC11): ex_venue_bookings_no_double_booking and
-- uq_venue_bookings_one_per_requirement still cover only PENDING and APPROVED, so neither changes.
--
-- Pending requests already in the database get the default the service applies, 7 days, counted
-- from this migration, but never later than their booked period's start. One whose period has
-- already started expires the first time the API sweeps.
--
-- Decided 12 Oct 2026 (Q27, Q29 to Q31): every change Venue Staff make to an expiry carries a
-- reason. The request keeps its latest change - the reason, who made it and when, set together or
-- not at all (ck_venue_bookings_hold_expiry_change) - and the audit log keeps every change.
-- =====================================================================

ALTER TABLE venue_bookings DROP CONSTRAINT ck_venue_bookings_status;
ALTER TABLE venue_bookings ADD CONSTRAINT ck_venue_bookings_status
    CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN', 'CANCELLED', 'EXPIRED'));

ALTER TABLE venue_bookings
    ADD COLUMN hold_expires_at TIMESTAMPTZ,
    ADD COLUMN hold_reminded_at TIMESTAMPTZ;

UPDATE venue_bookings
SET hold_expires_at = LEAST(now() + INTERVAL '7 days', held_from)
WHERE status = 'PENDING';

-- AC1: every hold has an expiry, and an expired request keeps the one it expired at.
ALTER TABLE venue_bookings ADD CONSTRAINT ck_venue_bookings_hold_expiry
    CHECK (status NOT IN ('PENDING', 'EXPIRED') OR hold_expires_at IS NOT NULL);

CREATE INDEX ix_venue_bookings_hold_expiry ON venue_bookings (hold_expires_at)
    WHERE status = 'PENDING';

ALTER TABLE venue_bookings
    ADD COLUMN hold_expiry_change_reason TEXT,
    ADD COLUMN hold_expiry_changed_by_id UUID REFERENCES users (id),
    ADD COLUMN hold_expiry_changed_at    TIMESTAMPTZ;

ALTER TABLE venue_bookings ADD CONSTRAINT ck_venue_bookings_hold_expiry_change
    CHECK (num_nonnulls(hold_expiry_change_reason, hold_expiry_changed_by_id, hold_expiry_changed_at) IN (0, 3));

COMMENT ON TABLE venue_bookings IS
    'Stories: 12.x, 13.x, 14.x, 9.2. A request by the assigned coordinator to book one venue for an event, and its outcome. PENDING = awaiting Venue Staff, holding the venue until hold_expires_at (stories 12.1 AC3, 12.7); APPROVED = confirmed booking. No two PENDING or APPROVED bookings of one venue may overlap (ex_venue_bookings_no_double_booking). REJECTED / WITHDRAWN / CANCELLED / EXPIRED free the venue. The held period (held_from..held_until) includes setup and teardown time (story 12.2).';
COMMENT ON COLUMN venue_bookings.status IS
    'PENDING, APPROVED, REJECTED, WITHDRAWN, CANCELLED or EXPIRED. PENDING and APPROVED hold the venue for the held period (story 12.1 AC3); a PENDING request not approved by hold_expires_at becomes EXPIRED (story 12.7 AC3).';
COMMENT ON COLUMN venue_bookings.hold_expires_at IS
    'When a pending request''s hold on its venue expires (story 12.7 AC1): set when it is raised, 7 days later by default but never after held_from (AC5), and changed only by Venue Staff (AC7, AC9). Required for a PENDING or EXPIRED request (ck_venue_bookings_hold_expiry); kept once a request is decided.';
COMMENT ON COLUMN venue_bookings.hold_reminded_at IS
    'When the event''s coordinator was warned that the hold is about to expire (story 12.7 AC2). NULL until then, and again when Venue Staff move the expiry back outside the warning period.';
COMMENT ON COLUMN venue_bookings.hold_expiry_change_reason IS
    'Why Venue Staff last changed hold_expires_at (story 12.7 AC7, decided 12 Oct 2026): required for every change, shown with who made it on the request and the event''s booking list. NULL until the first change; the audit log keeps every change''s reason.';
COMMENT ON COLUMN venue_bookings.hold_expiry_changed_by_id IS
    'FK -> users.id. The Venue Staff member who last changed hold_expires_at (story 12.7 AC7, AC9). Set with hold_expiry_change_reason and hold_expiry_changed_at, or not at all (ck_venue_bookings_hold_expiry_change).';
COMMENT ON COLUMN venue_bookings.hold_expiry_changed_at IS
    'When hold_expires_at was last changed by Venue Staff (story 12.7 AC7). Set with hold_expiry_change_reason and hold_expiry_changed_by_id, or not at all.';
COMMENT ON COLUMN venue_bookings.decided_by_id IS
    'FK -> users.id. Venue Staff member who approved or rejected (story 13.2 AC1), or the coordinator who withdrew the request (story 12.2). NULL when the system closed it: CANCELLED by migration 010, or EXPIRED (story 12.7).';
COMMENT ON COLUMN venue_bookings.decided_at IS
    'Decision time; for a WITHDRAWN or CANCELLED request, when it was closed, and for an EXPIRED one, its hold_expires_at (story 12.7).';
COMMENT ON INDEX ix_venue_bookings_hold_expiry IS
    'Story 12.7 AC2/AC3: the pending requests by expiry, which the API sweeps to warn coordinators and expire lapsed holds.';
