"""Conflict-detection logic for venue bookings (story 14.2).

Story 14.2 - "As a Venue Staff member, I want the system to block approval of a conflicting
request so that a venue cannot be double-booked":

* AC1 approval is refused where the requested period overlaps a confirmed booking for the
  same venue - ``find_conflicting_booking`` / ``assert_no_conflict`` compare the *held* period
  (already inclusive of setup/teardown padding, trigger-maintained on the row - see
  app/bookings/models.py) against every other APPROVED booking for the same venue, with the
  same half-open-interval semantics as the database's ``ex_venue_bookings_no_double_booking``
  exclusion constraint: a period that only touches another at a boundary is not a conflict
  (story 14.1 AC3);
* AC2 the refusal identifies the conflicting booking - ``BookingConflict`` carries the
  conflicting ``VenueBooking`` row;
* AC3 approving one of two overlapping pending requests refuses the other - this follows
  directly from AC1: once the first request is APPROVED, the second's held period now
  overlaps a confirmed booking and the same check refuses it.

Scope note: this module is deliberately limited to the conflict check, not a full approve
endpoint. Story 13.2 ("approve venue booking request", teammate Yu Bing) does not exist yet;
once it does, its approve action should call ``assert_no_conflict`` before flipping a booking's
status to APPROVED, and translate ``BookingConflict`` into the HTTP response AC1/AC2 need.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bookings.models import BookingStatus, VenueBooking


class BookingConflict(ValueError):
    """AC1/AC2: the requested period overlaps an existing APPROVED booking for the venue."""

    def __init__(self, conflicting_booking: VenueBooking):
        super().__init__(
            f"This request overlaps approved booking {conflicting_booking.id} for the same "
            f"venue, held from {conflicting_booking.held_from.isoformat()} to "
            f"{conflicting_booking.held_until.isoformat()}."
        )
        self.conflicting_booking = conflicting_booking


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
    ).first()


def assert_no_conflict(db: Session, booking: VenueBooking) -> None:
    """Raise ``BookingConflict`` if approving ``booking`` would double-book its venue.

    Meant to be called by story 13.2's approve endpoint before it sets ``status`` to APPROVED.
    """
    conflict = find_conflicting_booking(db, booking)
    if conflict is not None:
        raise BookingConflict(conflict)
