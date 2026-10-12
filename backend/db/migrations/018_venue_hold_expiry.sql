-- =====================================================================
-- Migration 018 - story 12.7: tentative venue holds expire.
--
-- Week 7 customer change #4 (CL-063), as the customer described the hold on 12 Oct 2026 (Q34,
-- Q44, Q45, Q48, Q51; CL-124). The tentative hold starts when Venue Staff approve a booking
-- request: they set its expiry then, from their own knowledge of the venue, with no default
-- (12.7 AC1), and may change it later (AC7). The coordinator confirming the event completes the
-- hold (21.2 AC12). If the event is not confirmed by the expiry, the hold expires: the booking
-- becomes EXPIRED and its venue is released (AC3). Like REJECTED, WITHDRAWN and CANCELLED, an
-- EXPIRED booking holds nothing and covers no venue requirement (AC6, AC11), so neither
-- ex_venue_bookings_no_double_booking nor uq_venue_bookings_one_per_requirement changes: both
-- still cover only PENDING and APPROVED.
--
-- A pending request still blocks its slot (12.1 AC3, migration 010) and has no expiry: it waits
-- for Venue Staff's decision. Nothing is backfilled: the system dictates no expiry, so a booking
-- approved before this migration has none, is not a hold, and never expires.
--
-- trg_events_complete_venue_holds completes the holds whenever an event becomes CONFIRMED, by
-- whatever route sets it, so a later return to PLANNING (stories 9.4, 19.2) does not reopen them.
-- A hold already past its expiry by then is left for the sweep to expire.
--
-- Decided 12 Oct 2026 (Q27, Q29 to Q31): every change Venue Staff make to an expiry carries a
-- reason. The booking keeps its latest change - the reason, who made it and when, set together or
-- not at all (ck_venue_bookings_hold_expiry_change) - and the audit log keeps every change.
-- =====================================================================

ALTER TABLE venue_bookings DROP CONSTRAINT ck_venue_bookings_status;
ALTER TABLE venue_bookings ADD CONSTRAINT ck_venue_bookings_status
    CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN', 'CANCELLED', 'EXPIRED'));

ALTER TABLE venue_bookings
    ADD COLUMN hold_expires_at   TIMESTAMPTZ,
    ADD COLUMN hold_reminded_at  TIMESTAMPTZ,
    ADD COLUMN hold_completed_at TIMESTAMPTZ;

-- AC1: a pending request has no hold yet, and an expired booking keeps the expiry it lapsed at.
ALTER TABLE venue_bookings ADD CONSTRAINT ck_venue_bookings_hold_expiry
    CHECK ((status <> 'PENDING' OR hold_expires_at IS NULL)
       AND (status <> 'EXPIRED' OR hold_expires_at IS NOT NULL));

-- AC4: only a hold with an expiry is completed, and a completed hold never expires.
ALTER TABLE venue_bookings ADD CONSTRAINT ck_venue_bookings_hold_completed
    CHECK (hold_completed_at IS NULL
        OR (hold_expires_at IS NOT NULL AND status <> 'EXPIRED'));

CREATE INDEX ix_venue_bookings_open_holds ON venue_bookings (hold_expires_at)
    WHERE status = 'APPROVED' AND hold_completed_at IS NULL;

ALTER TABLE venue_bookings
    ADD COLUMN hold_expiry_change_reason TEXT,
    ADD COLUMN hold_expiry_changed_by_id UUID REFERENCES users (id),
    ADD COLUMN hold_expiry_changed_at    TIMESTAMPTZ;

ALTER TABLE venue_bookings ADD CONSTRAINT ck_venue_bookings_hold_expiry_change
    CHECK (num_nonnulls(hold_expiry_change_reason, hold_expiry_changed_by_id, hold_expiry_changed_at) IN (0, 3));

-- AC4: the event's confirmation completes its open holds. now() is the confirming transaction's
-- start, so a hold that lapsed before it is left open for the sweep to expire.
CREATE OR REPLACE FUNCTION complete_venue_holds() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE venue_bookings
    SET hold_completed_at = now()
    WHERE event_id = NEW.id
      AND status = 'APPROVED'
      AND hold_completed_at IS NULL
      AND hold_expires_at > now();
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_events_complete_venue_holds
    AFTER UPDATE OF status ON events
    FOR EACH ROW
    WHEN (NEW.status = 'CONFIRMED' AND OLD.status IS DISTINCT FROM 'CONFIRMED')
    EXECUTE FUNCTION complete_venue_holds();

COMMENT ON TABLE venue_bookings IS
    'Stories: 12.x, 13.x, 14.x, 9.2. A request by the assigned coordinator to book one venue for an event, and its outcome. PENDING = awaiting Venue Staff, blocking the venue (story 12.1 AC3); APPROVED = booked, held until hold_expires_at unless the event is confirmed first (story 12.7). No two PENDING or APPROVED bookings of one venue may overlap (ex_venue_bookings_no_double_booking). REJECTED / WITHDRAWN / CANCELLED / EXPIRED free the venue. The held period (held_from..held_until) includes setup and teardown time (story 12.2).';
COMMENT ON COLUMN venue_bookings.status IS
    'PENDING, APPROVED, REJECTED, WITHDRAWN, CANCELLED or EXPIRED. PENDING and APPROVED hold the venue for the held period (story 12.1 AC3); an APPROVED booking whose event is not confirmed by hold_expires_at becomes EXPIRED (story 12.7 AC3).';
COMMENT ON COLUMN venue_bookings.hold_expires_at IS
    'When an approved booking''s tentative hold on its venue expires unless the event is confirmed first (story 12.7 AC1, AC3): set by Venue Staff when they approve, never after held_from (AC5), and changed only by them (AC7, AC9). NULL for a pending request (ck_venue_bookings_hold_expiry) and for a booking approved before migration 018; required for an EXPIRED one, which keeps it.';
COMMENT ON COLUMN venue_bookings.hold_reminded_at IS
    'When the event''s coordinator was warned that the hold is about to expire (story 12.7 AC2). NULL until then, and again when Venue Staff move the expiry back outside the warning period.';
COMMENT ON COLUMN venue_bookings.hold_completed_at IS
    'When the event''s confirmation completed the hold (story 12.7 AC4): set by trg_events_complete_venue_holds when the event becomes CONFIRMED before hold_expires_at. From then on the booking is held for good: it never expires and its expiry no longer changes. NULL while the hold is open (ck_venue_bookings_hold_completed).';
COMMENT ON COLUMN venue_bookings.hold_expiry_change_reason IS
    'Why Venue Staff last changed hold_expires_at (story 12.7 AC7, decided 12 Oct 2026): required for every change, shown with who made it on the booking and the event''s booking list. NULL until the first change; the audit log keeps every change''s reason.';
COMMENT ON COLUMN venue_bookings.hold_expiry_changed_by_id IS
    'FK -> users.id. The Venue Staff member who last changed hold_expires_at (story 12.7 AC7, AC9). Set with hold_expiry_change_reason and hold_expiry_changed_at, or not at all (ck_venue_bookings_hold_expiry_change).';
COMMENT ON COLUMN venue_bookings.hold_expiry_changed_at IS
    'When hold_expires_at was last changed by Venue Staff (story 12.7 AC7). Set with hold_expiry_change_reason and hold_expiry_changed_by_id, or not at all.';
COMMENT ON COLUMN venue_bookings.decided_by_id IS
    'FK -> users.id. Venue Staff member who approved or rejected (story 13.2 AC1) - for an EXPIRED booking, who approved it - or the coordinator who withdrew the request (story 12.2). NULL when the system cancelled it (migration 010).';
COMMENT ON COLUMN venue_bookings.decided_at IS
    'Decision time; for an EXPIRED booking, when it was approved (it expired at hold_expires_at), and for a WITHDRAWN or CANCELLED request, when it was closed.';
COMMENT ON INDEX ix_venue_bookings_open_holds IS
    'Story 12.7 AC2/AC3: the approved bookings whose hold is still open, by expiry, which the API sweeps to warn coordinators and expire lapsed holds.';
COMMENT ON FUNCTION complete_venue_holds() IS
    'Story 12.7 AC4: completes the open holds of an event that has just become CONFIRMED (trg_events_complete_venue_holds).';
COMMENT ON TRIGGER trg_events_complete_venue_holds ON events IS
    'Story 12.7 AC4: when an event becomes CONFIRMED, its approved bookings'' holds still open are completed (complete_venue_holds), whatever route confirmed it.';
