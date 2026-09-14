"""Story 14.2 - be: block approval of conflicting bookings.

Scope note: story 13.2 ("approve venue booking request", teammate Yu Bing) does not exist
yet, so there is no HTTP endpoint to test here - these tests exercise the conflict-detection
service directly (app/bookings/service.py). The ``_approve`` helper below is test scaffolding
standing in for that future endpoint - it delegates to ``service.approve_booking``, which is
what 13.2's real endpoint must call, so AC3 can be demonstrated end-to-end here.

AC1 Approval is refused where the requested period overlaps a confirmed booking for the same
    venue.
AC2 The refusal identifies the conflicting booking.
AC3 Where two pending requests overlap, approving one causes the other's approval to be
    refused.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.bookings import service
from app.bookings.models import BookingStatus, VenueBooking
from tests.support.factories import make_booking
from tests.support.seed import Bookings, Users, Venues


def _approve(db: Session, booking: VenueBooking, *, actor_id: uuid.UUID) -> None:
    """Stand-in for story 13.2's approve action - delegates to service.approve_booking."""
    service.approve_booking(db, booking, actor_id=actor_id)


# --- AC1: overlap with a confirmed booking is refused ---------------------------------------
@pytest.mark.story("14.2", ac=1)
def test_pending_request_overlapping_an_approved_booking_is_refused(db: Session):
    """Bookings.APPROVED_GRAND_HALL holds Grand Hall 08:00-19:00 incl. setup/teardown."""
    overlapping = make_booking(
        db,
        venue_id=Venues.GRAND_HALL,
        starts_at=datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(service.BookingConflict):
        service.assert_no_conflict(db, overlapping)


@pytest.mark.story("14.2", ac=1)
def test_request_that_does_not_overlap_any_approved_booking_is_not_refused(db: Session):
    clear = make_booking(
        db,
        venue_id=Venues.GRAND_HALL,
        starts_at=datetime(2026, 12, 10, 10, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 10, 12, 0, tzinfo=timezone.utc),
    )

    service.assert_no_conflict(db, clear)  # does not raise


@pytest.mark.story("14.2", ac=1)
def test_request_touching_the_boundary_of_an_approved_booking_is_not_refused(db: Session):
    """Bookings.APPROVED_GRAND_HALL is held until 2026-11-25 19:00+08 (11:00 UTC) once its
    60-minute teardown is added. Held periods are half-open [) (story 14.1 AC3), so a request
    starting exactly when another ends is not a conflict.
    """
    touching = make_booking(
        db,
        venue_id=Venues.GRAND_HALL,
        starts_at=datetime(2026, 11, 25, 11, 0, tzinfo=timezone.utc),  # == held_until
        ends_at=datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc),
    )

    service.assert_no_conflict(db, touching)  # does not raise


@pytest.mark.story("14.2", ac=1)
def test_request_starting_one_minute_before_the_boundary_is_refused(db: Session):
    """Pins the same boundary from the other side - one minute earlier and it does overlap."""
    just_inside = make_booking(
        db,
        venue_id=Venues.GRAND_HALL,
        starts_at=datetime(2026, 11, 25, 10, 59, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(service.BookingConflict):
        service.assert_no_conflict(db, just_inside)


@pytest.mark.story("14.2", ac=1)
def test_overlap_with_a_non_approved_booking_is_not_refused(db: Session):
    """Only an APPROVED ('confirmed') booking blocks the venue - a rejected one does not."""
    rejected = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        status=BookingStatus.REJECTED,
        starts_at=datetime(2026, 12, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 1, 11, 0, tzinfo=timezone.utc),
    )
    overlapping = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        starts_at=datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc),
    )

    service.assert_no_conflict(db, overlapping)  # does not raise: REJECTED doesn't block

    # Prove the check is status-sensitive, not just blind to `rejected`: the identical
    # overlap IS refused once that same booking becomes APPROVED.
    rejected.status = BookingStatus.APPROVED
    db.flush()
    db.refresh(rejected)

    with pytest.raises(service.BookingConflict):
        service.assert_no_conflict(db, overlapping)


@pytest.mark.story("14.2", ac=1)
def test_overlap_on_a_different_venue_is_not_refused(db: Session):
    """AC1 is scoped to 'the same venue' - an overlapping period elsewhere is irrelevant."""
    elsewhere = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        starts_at=datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc),
    )

    service.assert_no_conflict(db, elsewhere)  # does not raise: Grand Hall booking is elsewhere


# --- AC2: the refusal identifies the conflicting booking -------------------------------------
@pytest.mark.story("14.2", ac=2)
def test_refusal_identifies_the_conflicting_booking(db: Session):
    overlapping = make_booking(
        db,
        venue_id=Venues.GRAND_HALL,
        starts_at=datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(service.BookingConflict) as excinfo:
        service.assert_no_conflict(db, overlapping)

    assert excinfo.value.conflicting_booking.id == Bookings.APPROVED_GRAND_HALL
    assert str(Bookings.APPROVED_GRAND_HALL) in str(excinfo.value)


@pytest.mark.story("14.2", ac=2)
def test_find_conflicting_booking_returns_none_when_clear(db: Session):
    clear = make_booking(
        db,
        venue_id=Venues.GRAND_HALL,
        starts_at=datetime(2026, 12, 10, 10, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 10, 12, 0, tzinfo=timezone.utc),
    )

    assert service.find_conflicting_booking(db, clear) is None


# --- AC3: approving one of two overlapping pending requests refuses the other ---------------
@pytest.mark.story("14.2", ac=3)
def test_approving_one_of_two_overlapping_pending_requests_refuses_the_other(db: Session):
    first = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        starts_at=datetime(2026, 12, 3, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 3, 11, 0, tzinfo=timezone.utc),
    )
    second = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        starts_at=datetime(2026, 12, 3, 10, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 3, 12, 0, tzinfo=timezone.utc),
    )

    _approve(db, first, actor_id=Users.VENUE_STAFF.id)  # succeeds: nothing APPROVED yet
    db.commit()  # the two approvals are separate requests in production, each its own transaction

    with pytest.raises(service.BookingConflict) as excinfo:
        _approve(db, second, actor_id=Users.VENUE_STAFF.id)

    assert excinfo.value.conflicting_booking.id == first.id
    assert second.status == BookingStatus.PENDING  # refused: the second request is left untouched


@pytest.mark.story("14.2", ac=3)
def test_approving_non_overlapping_pending_requests_both_succeed(db: Session):
    first = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        starts_at=datetime(2026, 12, 4, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 4, 11, 0, tzinfo=timezone.utc),
    )
    second = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        starts_at=datetime(2026, 12, 4, 12, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 4, 14, 0, tzinfo=timezone.utc),
    )

    _approve(db, first, actor_id=Users.VENUE_STAFF.id)
    _approve(db, second, actor_id=Users.VENUE_STAFF.id)

    assert first.status == BookingStatus.APPROVED
    assert second.status == BookingStatus.APPROVED
