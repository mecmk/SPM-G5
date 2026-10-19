-- =====================================================================
-- Migration 025 - story 12.6: a replacement venue for a booking whose venue became unavailable.
--
-- When Venue Staff close a venue over an approved booking (story 9.4) the event's coordinator may
-- request a replacement: a new booking request, linked to the original, which stays approved and
-- holds its venue until Venue Staff approve the replacement - and is released, in the same
-- transaction, the moment they do (AC2-AC4).
--
-- * replaces_booking_id links the replacement to its original. It is a composite foreign key with
--   event_id, so the two are always bookings of one event, and a booking cannot replace itself.
-- * replaced_by_booking_id, on the original, names the replacement whose approval released it. It
--   is set in that release and only on a CANCELLED booking, so "Replaced by" is shown only for a
--   replacement that was approved (AC3, AC8); a booking is the replacement of at most one original.
-- * One pending replacement per original (AC10): a partial unique index.
-- * 12.5's one pending or approved request per venue requirement (migration 017) must let a
--   pending replacement sit beside its original, which still holds the requirement. The index
--   leaves out a PENDING booking whose replaces_live_original is set - and leaves out nothing
--   else, so a normal second request is still refused, and an approved replacement counts.
--   replaces_live_original is set on a replacement when it is requested, and a trigger clears it
--   on a PENDING replacement when its original stops being PENDING or APPROVED, by whatever route
--   (the hold sweep, a release, a cancellation), so the pending replacement is then the
--   requirement's request and no normal request can be written beside it. The index reads it
--   only for a PENDING row; on a decided replacement it keeps what it had and means nothing.
-- =====================================================================

ALTER TABLE venue_bookings
    ADD COLUMN replaces_booking_id     UUID,
    ADD COLUMN replaced_by_booking_id  UUID,
    ADD COLUMN replaces_live_original  BOOLEAN NOT NULL DEFAULT FALSE;

-- A composite foreign key needs a unique target. (id, event_id) is unique whenever id is.
ALTER TABLE venue_bookings
    ADD CONSTRAINT uq_venue_bookings_id_event UNIQUE (id, event_id);

ALTER TABLE venue_bookings
    ADD CONSTRAINT fk_venue_bookings_replaces
        FOREIGN KEY (replaces_booking_id, event_id) REFERENCES venue_bookings (id, event_id),
    ADD CONSTRAINT fk_venue_bookings_replaced_by
        FOREIGN KEY (replaced_by_booking_id) REFERENCES venue_bookings (id),
    ADD CONSTRAINT uq_venue_bookings_replaced_by UNIQUE (replaced_by_booking_id),
    ADD CONSTRAINT ck_venue_bookings_not_self_replacement
        CHECK (replaces_booking_id IS DISTINCT FROM id),
    ADD CONSTRAINT ck_venue_bookings_replaced_by_cancelled
        CHECK (replaced_by_booking_id IS NULL OR status = 'CANCELLED'),
    ADD CONSTRAINT ck_venue_bookings_live_original_is_a_replacement
        CHECK (NOT replaces_live_original OR replaces_booking_id IS NOT NULL);

-- AC10: one pending replacement per original.
CREATE UNIQUE INDEX uq_venue_bookings_one_pending_replacement
    ON venue_bookings (replaces_booking_id)
    WHERE status = 'PENDING' AND replaces_booking_id IS NOT NULL;

-- AC10 / story 12.5 AC10-AC12: the one-per-requirement index, narrowed for a pending replacement
-- of an original that still holds its venue.
DROP INDEX uq_venue_bookings_one_per_requirement;
CREATE UNIQUE INDEX uq_venue_bookings_one_per_requirement
    ON venue_bookings (venue_requirement_id)
    WHERE status IN ('PENDING', 'APPROVED') AND NOT (status = 'PENDING' AND replaces_live_original);

-- The carve-out ends with the original, by any path.
CREATE OR REPLACE FUNCTION clear_replacement_carve_out() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE venue_bookings
    SET replaces_live_original = FALSE
    WHERE replaces_booking_id = NEW.id
      AND replaces_live_original
      AND status = 'PENDING';
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_venue_bookings_clear_replacement_carve_out
    AFTER UPDATE OF status ON venue_bookings
    FOR EACH ROW
    WHEN (OLD.status IN ('PENDING', 'APPROVED') AND NEW.status NOT IN ('PENDING', 'APPROVED'))
    EXECUTE FUNCTION clear_replacement_carve_out();

COMMENT ON COLUMN venue_bookings.replaces_booking_id IS
    'FK -> venue_bookings.id, with event_id (fk_venue_bookings_replaces), so always a booking of the same event. The booking this one was requested to replace, because Venue Staff made its venue unavailable (story 12.6 AC2); NULL for every other booking. Set when the replacement is requested and never cleared, so a rejected or withdrawn replacement still says what it was for. The original stays approved until the replacement is approved (AC3, AC4).';
COMMENT ON COLUMN venue_bookings.replaced_by_booking_id IS
    'FK -> venue_bookings.id. On an original released by its replacement: the replacement whose approval released it (story 12.6 AC3), set in that same transaction and only on a CANCELLED booking (ck_venue_bookings_replaced_by_cancelled). The event page shows "Replaced by <venue>" only when this is set, so a replacement that was never approved is never shown as having replaced it (AC8). NULL otherwise; a booking replaces at most one original (uq_venue_bookings_replaced_by).';
COMMENT ON COLUMN venue_bookings.replaces_live_original IS
    'TRUE on a replacement (replaces_booking_id) from the moment it is requested, while its original still holds its venue (story 12.6 AC4, AC10): the one-per-requirement index leaves out such a booking while it is PENDING, so it can sit beside its original. trg_venue_bookings_clear_replacement_carve_out sets it FALSE on a PENDING replacement when the original stops being PENDING or APPROVED by any route - the hold sweep, a release, a cancellation - so the pending replacement is then the requirement''s request. The index reads it only for a PENDING booking: on a decided replacement it keeps what it had and means nothing. FALSE for every other booking.';
COMMENT ON CONSTRAINT uq_venue_bookings_id_event ON venue_bookings IS
    'Story 12.6: the target of fk_venue_bookings_replaces, which needs (id, event_id) to be unique.';
COMMENT ON CONSTRAINT fk_venue_bookings_replaces ON venue_bookings IS
    'Story 12.6 AC2: a replacement and its original are bookings of one event.';
COMMENT ON CONSTRAINT fk_venue_bookings_replaced_by ON venue_bookings IS
    'Story 12.6 AC3: the replacement that released this booking.';
COMMENT ON CONSTRAINT uq_venue_bookings_replaced_by ON venue_bookings IS
    'Story 12.6 AC3: a booking is the replacement of at most one original.';
COMMENT ON CONSTRAINT ck_venue_bookings_not_self_replacement ON venue_bookings IS
    'Story 12.6 AC2: a booking cannot replace itself.';
COMMENT ON CONSTRAINT ck_venue_bookings_replaced_by_cancelled ON venue_bookings IS
    'Story 12.6 AC3: only a CANCELLED booking is replaced_by another.';
COMMENT ON CONSTRAINT ck_venue_bookings_live_original_is_a_replacement ON venue_bookings IS
    'Story 12.6 AC10: replaces_live_original is set only on a replacement.';
COMMENT ON INDEX uq_venue_bookings_one_pending_replacement IS
    'Story 12.6 AC10: at most one pending replacement per original, so of two sent at once only the first is written.';
COMMENT ON INDEX uq_venue_bookings_one_per_requirement IS
    'Story 12.5 AC10-AC12, narrowed by story 12.6: at most one pending or approved request per venue requirement, so of two requests sent for one requirement at once only the first is written. A PENDING replacement whose original still holds its venue (replaces_live_original) is left out, so it can sit beside the original; an approved replacement is not, and nothing else is. Additional venues (NULL) are not limited.';
COMMENT ON FUNCTION clear_replacement_carve_out() IS
    'Story 12.6 AC10: clears replaces_live_original on the PENDING replacements of a booking that has just stopped being PENDING or APPROVED (trg_venue_bookings_clear_replacement_carve_out); a decided replacement is left as it was.';
COMMENT ON TRIGGER trg_venue_bookings_clear_replacement_carve_out ON venue_bookings IS
    'Story 12.6 AC10: when a booking stops holding its venue, by whatever route, its pending replacements start counting as the requirement''s request (clear_replacement_carve_out).';
COMMENT ON COLUMN venue_bookings.status IS
    'PENDING, APPROVED, REJECTED, WITHDRAWN, CANCELLED or EXPIRED. PENDING and APPROVED hold the venue for the held period (story 12.1 AC3); an APPROVED booking whose event is not confirmed by hold_expires_at becomes EXPIRED (story 12.7 AC3); an APPROVED booking whose replacement is approved becomes CANCELLED, with replaced_by_booking_id set (story 12.6 AC3), and one an approved change to its event no longer fits becomes CANCELLED with no replacement (story 19.2 AC5).';
COMMENT ON COLUMN venue_bookings.decision_reason IS
    'Mandatory when rejected (story 13.2.1 AC1/AC2). On an approved booking released by its replacement (story 12.6 AC3): "Replaced by <venue>".';
COMMENT ON COLUMN venue_bookings.decided_at IS
    'Decision time; for an EXPIRED booking, when it was approved (it expired at hold_expires_at), for a WITHDRAWN or CANCELLED request, when it was closed - except an approved booking a replacement released (story 12.6 AC3) or an approved change released (story 19.2 AC5), whose decided_at stays its approval: when a released original closed is its replacement''s decided_at, or is not recorded for a change.';
