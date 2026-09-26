"""Story 13.1 - be: display the venue staff booking queue.

AC1 The queue lists all requests for venues the staff member is responsible for.
AC2 Each entry shows event name, requested venue, period, expected attendance and stated
    requirements.
AC3 Decided requests also appear in the queue, with their decision reason, so Venue Staff can
    review past decisions through the All / Pending / Approved / Rejected tabs - broadened the
    same way story 6.1 widened the coordinator's queue from a review-only endpoint to every
    assigned event.

Excluded, with reason:
* "Venue Staff outside the venue's responsibility scope" - same reason as
  test_approve_booking.py: there is no per-venue staff responsibility table in the schema, and
  BOOKINGS_DECIDE is a role-wide permission today. AC1's "responsible for" is every venue.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.bookings.models import BookingStatus
from tests.support.factories import make_booking
from tests.support.seed import Bookings, Users, Venues


# --- AC1: which bookings appear -------------------------------------------------------------
@pytest.mark.story("13.1", ac=1)
def test_seeded_pending_booking_is_listed(venue_staff_client):
    ids = [row["id"] for row in venue_staff_client.get("/bookings").json()]
    assert str(Bookings.PENDING_SEMINAR_ROOM) in ids


@pytest.mark.story("13.1", ac=1)
def test_a_newly_created_pending_booking_is_listed(venue_staff_client, db):
    booking = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        starts_at=datetime(2027, 2, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 2, 1, 11, 0, tzinfo=timezone.utc),
    )

    ids = [row["id"] for row in venue_staff_client.get("/bookings").json()]

    assert str(booking.id) in ids


# --- AC2: entry shape ----------------------------------------------------------------------
@pytest.mark.story("13.1", ac=2)
def test_entry_shows_event_venue_period_attendance_and_requirements(venue_staff_client):
    body = venue_staff_client.get("/bookings").json()
    entry = next(row for row in body if row["id"] == str(Bookings.PENDING_SEMINAR_ROOM))

    assert entry["event_name"] == "Nimbus Developer Conference"
    assert entry["venue_name"] == "Seminar Room 2.1"
    assert entry["starts_at"].startswith("2026-11-25")
    assert entry["ends_at"].startswith("2026-11-25")
    assert entry["expected_attendance"] == 60
    assert entry["requirement_notes"] == "Breakout track B."


# --- AC3: decided requests are included, with their reason, for the tabs -------------------
@pytest.mark.story("13.1", ac=3)
def test_a_decided_booking_is_listed(venue_staff_client):
    ids = [row["id"] for row in venue_staff_client.get("/bookings").json()]
    assert str(Bookings.APPROVED_GRAND_HALL) in ids


@pytest.mark.story("13.1", ac=3)
@pytest.mark.parametrize(
    "status",
    [
        BookingStatus.APPROVED,
        BookingStatus.REJECTED,
        BookingStatus.WITHDRAWN,
        BookingStatus.CANCELLED,
    ],
)
def test_a_booking_in_any_decided_state_is_listed(venue_staff_client, db, status):
    booking = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        status=status,
        starts_at=datetime(2027, 2, 2, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 2, 2, 11, 0, tzinfo=timezone.utc),
    )

    ids = [row["id"] for row in venue_staff_client.get("/bookings").json()]

    assert str(booking.id) in ids


@pytest.mark.story("13.1", ac=3)
def test_a_rejected_booking_carries_its_decision_reason(venue_staff_client, db):
    booking = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        status=BookingStatus.REJECTED,
        decision_reason="The venue is under maintenance that week.",
        starts_at=datetime(2027, 2, 3, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 2, 3, 11, 0, tzinfo=timezone.utc),
    )

    body = venue_staff_client.get("/bookings").json()
    entry = next(row for row in body if row["id"] == str(booking.id))

    assert entry["decision_reason"] == "The venue is under maintenance that week."


# --- access control --------------------------------------------------------------------------
@pytest.mark.story("13.1")
@pytest.mark.story("1.2", ac=4)
@pytest.mark.parametrize(
    "user", [Users.ORGANISER, Users.COORDINATOR, Users.TECH_SUPPORT, Users.ATTENDEE]
)
def test_other_roles_cannot_see_the_queue(client, user):
    client.login(user)
    assert client.get("/bookings").status_code == 403


@pytest.mark.story("13.1")
def test_signed_out_user_is_rejected(client):
    assert client.get("/bookings").status_code == 401
