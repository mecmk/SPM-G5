"""Conflict-detection logic for venue bookings (story 14.2).

Story 14.2 - "As a Venue Staff member, I want the system to block approval of a conflicting
request so that a venue cannot be double-booked":

* AC1 approval is refused where the requested period overlaps a confirmed booking for the
  same venue;
* AC2 the refusal identifies the conflicting booking - ``BookingConflict`` carries the
  conflicting ``VenueBooking`` row;
* AC3 approving one of two overlapping pending requests refuses the other - this follows
  directly from AC1: once the first request is APPROVED, the second's held period now
  overlaps a confirmed booking and the same check refuses it.

Race safety: ``find_conflicting_booking`` / ``assert_no_conflict`` are a fast, friendly
pre-check only - they do not by themselves close the race between two concurrent approvals
(two overlapping requests could both pass the check before either commits). The database's
``ex_venue_bookings_no_double_booking`` exclusion constraint is the actual last word, so
``approve_booking`` attempts the write directly and translates that constraint's
``IntegrityError`` into ``BookingConflict``, mirroring ``app/venues/service.py::create_venue``'s
write-then-catch pattern. That constraint only guards two *different* overlapping bookings; it
does nothing to stop two concurrent approvals of the *same* booking (both could read PENDING
and both write APPROVED). Story 13.2 closes that gap: its router fetches the booking through
``get_booking_for_decision`` (``SELECT ... FOR UPDATE``), so a second concurrent approval blocks
on the row lock and, once it proceeds, sees the already-APPROVED row and is refused by the
``BookingNotPending`` check below rather than racing the write.

Story 13.2 ("approve venue booking request") is what calls ``approve_booking`` and translates
``BookingNotPending`` / ``BookingConflict`` into the HTTP response its AC1/AC4 need.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings.models import BookingStatus, VenueBooking
from app.common.audit import record_audit

_CONFLICT_CONSTRAINT = "ex_venue_bookings_no_double_booking"

BOOKING_CONFLICT_MESSAGE = (
    "This request overlaps approved booking {conflicting_id} for the same venue, held from "
    "{held_from} to {held_until}."
)

BOOKING_NOT_PENDING_MESSAGE = "This request is already {status}, so it cannot be approved."


class BookingNotFound(LookupError):
    pass


class BookingConflict(ValueError):
    """AC1/AC2: the requested period overlaps an existing APPROVED booking for the venue."""

    def __init__(self, conflicting_booking: VenueBooking) -> None:
        super().__init__(
            BOOKING_CONFLICT_MESSAGE.format(
                conflicting_id=conflicting_booking.id,
                held_from=conflicting_booking.held_from.isoformat(),
                held_until=conflicting_booking.held_until.isoformat(),
            )
        )
        self.conflicting_booking = conflicting_booking


class BookingNotPending(ValueError):
    """13.2 AC1: only a PENDING request may be approved - refuses repeat or invalid-state
    approval (e.g. a request that was already decided, or since withdrawn/cancelled)."""

    def __init__(self, booking: VenueBooking) -> None:
        super().__init__(BOOKING_NOT_PENDING_MESSAGE.format(status=booking.status))
        self.booking = booking


def find_conflicting_booking(db: Session, booking: VenueBooking) -> VenueBooking | None:
    """The existing APPROVED booking (if any) whose held period overlaps ``booking``'s.

    Two half-open periods [a, b) and [c, d) overlap iff a < d and c < b - the same test the
    database's exclusion constraint applies, so a booking that merely touches another at a
    boundary is not reported as a conflict (story 14.1 AC3).
    """
    return db.scalars(
        select(VenueBooking)
        .where(
            VenueBooking.venue_id == booking.venue_id,
            VenueBooking.status == BookingStatus.APPROVED,
            VenueBooking.id != booking.id,
            VenueBooking.held_from < booking.held_until,
            VenueBooking.held_until > booking.held_from,
        )
        .order_by(VenueBooking.held_from)
        .limit(1)
    ).first()


def get_booking(db: Session, booking_id: uuid.UUID) -> VenueBooking:
    """13.2 AC3: plain read, e.g. for the requesting coordinator to check the outcome."""
    booking = db.get(VenueBooking, booking_id)
    if booking is None:
        raise BookingNotFound(booking_id)
    return booking


def get_booking_for_decision(db: Session, booking_id: uuid.UUID) -> VenueBooking:
    """Row-locked read for an approve/reject action - see the module docstring's concurrency
    note. Two simultaneous decisions on the same booking serialize on this lock instead of
    racing the write."""
    booking = db.scalar(select(VenueBooking).where(VenueBooking.id == booking_id).with_for_update())
    if booking is None:
        raise BookingNotFound(booking_id)
    return booking


def assert_no_conflict(db: Session, booking: VenueBooking) -> None:
    """Fast, friendly pre-check only - see the module docstring's "Race safety" note.

    Useful for a UI that wants to show an error before the user even submits, but
    ``approve_booking`` (not this) is what must actually guard an approval.
    """
    conflict = find_conflicting_booking(db, booking)
    if conflict is not None:
        raise BookingConflict(conflict)


def approve_booking(db: Session, booking: VenueBooking, *, actor_id: uuid.UUID) -> None:
    """13.2 AC1: approve ``booking``, recording the approver and time. Refuses a request that
    is not PENDING (``BookingNotPending``) or whose period would double-book its venue
    (``BookingConflict``, AC4 / 14.2 AC1-AC2).

    14.2 AC3 falls out of this for free: whichever of two overlapping PENDING requests is
    approved first wins; approving the second one then hits the conflict check below. Callers
    must fetch ``booking`` via ``get_booking_for_decision`` - see the module docstring's
    concurrency note.
    """
    if booking.status != BookingStatus.PENDING:
        raise BookingNotPending(booking)

    booking.status = BookingStatus.APPROVED
    booking.decided_by_id = actor_id
    booking.decided_at = datetime.now(UTC)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _CONFLICT_CONSTRAINT not in str(exc.orig):
            raise
        conflict = find_conflicting_booking(db, booking)
        if conflict is None:
            raise
        raise BookingConflict(conflict) from exc

    record_audit(
        db,
        actor=db.get(User, actor_id),
        action="BOOKING_APPROVED",
        entity_type="venue_booking",
        entity_id=booking.id,
        details={"venue_id": str(booking.venue_id), "event_id": str(booking.event_id)},
        commit=False,
    )
    db.commit()
    db.refresh(booking)
