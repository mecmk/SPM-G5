"""Story 13.1 - be: display the venue staff booking queue.

AC1 The queue lists all pending requests for venues the staff member is responsible for.
AC2 Each entry shows event name, requested venue, period, expected attendance and stated
    requirements.
AC3 Decided requests do not appear in the pending queue.

Story 13.1.2 - be: booking status tabs and decision timing.

AC1 The queue can be narrowed to Pending, Approved or Rejected requests, or show All, and says
    how many requests each tab holds.
AC2 Each entry shows when the coordinator raised the request.
AC3 A decided entry shows when it was decided and, once rejected, why.
AC4 The queue is sent a page at a time, with the total, so the page can number its pages.

The pending queue is ``?status=PENDING``: leaving ``status`` out lists every request, which is
what 13.1.2's All tab asks for.

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

BOOKINGS_PATH = "/bookings"
PENDING_QUEUE_PATH = f"{BOOKINGS_PATH}?status={BookingStatus.PENDING}"
DECIDED_STATUSES = [
    BookingStatus.APPROVED,
    BookingStatus.REJECTED,
    BookingStatus.WITHDRAWN,
    BookingStatus.CANCELLED,
]


def _ids(client, path: str) -> list[str]:
    return [row["id"] for row in client.get(path).json()["items"]]


def _entry(client, path: str, booking_id) -> dict:
    return next(row for row in client.get(path).json()["items"] if row["id"] == str(booking_id))


# --- 13.1 AC1: which bookings appear in the pending queue ------------------------------------
@pytest.mark.story("13.1", ac=1)
def test_seeded_pending_booking_is_listed(venue_staff_client):
    assert str(Bookings.PENDING_SEMINAR_ROOM) in _ids(venue_staff_client, PENDING_QUEUE_PATH)


@pytest.mark.story("13.1", ac=1)
def test_a_newly_created_pending_booking_is_listed(venue_staff_client, db):
    booking = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        starts_at=datetime(2027, 2, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 2, 1, 11, 0, tzinfo=timezone.utc),
    )

    assert str(booking.id) in _ids(venue_staff_client, PENDING_QUEUE_PATH)


# --- 13.1 AC2: entry shape ---------------------------------------------------------------------
@pytest.mark.story("13.1", ac=2)
def test_entry_shows_event_venue_period_attendance_and_requirements(venue_staff_client):
    entry = _entry(venue_staff_client, PENDING_QUEUE_PATH, Bookings.PENDING_SEMINAR_ROOM)

    assert entry["event_name"] == "Nimbus Developer Conference"
    assert entry["venue_name"] == "Seminar Room 2.1"
    assert entry["starts_at"].startswith("2026-11-25")
    assert entry["ends_at"].startswith("2026-11-25")
    assert entry["expected_attendance"] == 60
    assert entry["requirement_notes"] == "Breakout track B."


# --- 13.1 AC3: decided requests are excluded from the pending queue --------------------------
@pytest.mark.story("13.1", ac=3)
def test_a_decided_booking_is_not_listed(venue_staff_client):
    assert str(Bookings.APPROVED_GRAND_HALL) not in _ids(venue_staff_client, PENDING_QUEUE_PATH)


@pytest.mark.story("13.1", ac=3)
@pytest.mark.parametrize("status", DECIDED_STATUSES)
def test_a_booking_in_any_decided_state_is_not_listed(venue_staff_client, db, status):
    booking = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        status=status,
        starts_at=datetime(2027, 2, 2, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 2, 2, 11, 0, tzinfo=timezone.utc),
    )

    assert str(booking.id) not in _ids(venue_staff_client, PENDING_QUEUE_PATH)


# --- 13.1.2 AC1: status tabs -------------------------------------------------------------------
@pytest.mark.story("13.1.2", ac=1)
@pytest.mark.parametrize("status", [BookingStatus.PENDING, *DECIDED_STATUSES])
def test_without_a_status_every_request_is_listed(venue_staff_client, db, status):
    booking = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        status=status,
        starts_at=datetime(2027, 2, 2, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 2, 2, 11, 0, tzinfo=timezone.utc),
    )

    assert str(booking.id) in _ids(venue_staff_client, BOOKINGS_PATH)


@pytest.mark.story("13.1.2", ac=1)
@pytest.mark.parametrize("status", [BookingStatus.APPROVED, BookingStatus.REJECTED])
def test_a_status_lists_only_requests_in_that_status(venue_staff_client, db, status):
    booking = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        status=status,
        starts_at=datetime(2027, 2, 2, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 2, 2, 11, 0, tzinfo=timezone.utc),
    )

    items = venue_staff_client.get(f"{BOOKINGS_PATH}?status={status}").json()["items"]

    assert str(booking.id) in [row["id"] for row in items]
    assert {row["status"] for row in items} == {status}


@pytest.mark.story("13.1.2", ac=1)
@pytest.mark.parametrize("status", ["pending", "DECIDED", ""])
def test_an_unknown_status_is_refused(venue_staff_client, status):
    assert venue_staff_client.get(f"{BOOKINGS_PATH}?status={status}").status_code == 422


@pytest.mark.story("13.1.2", ac=1)
def test_counts_cover_every_status_whatever_tab_or_page_is_asked_for(venue_staff_client, db):
    make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        status=BookingStatus.REJECTED,
        starts_at=datetime(2027, 2, 2, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 2, 2, 11, 0, tzinfo=timezone.utc),
    )

    unfiltered = venue_staff_client.get(BOOKINGS_PATH).json()
    narrowed = venue_staff_client.get(f"{PENDING_QUEUE_PATH}&limit=1").json()

    # Seed: 1 approved and 7 pending bookings; the factory adds the one rejected.
    assert unfiltered["counts"] == {
        "pending": 7,
        "approved": 1,
        "rejected": 1,
        "withdrawn": 0,
        "cancelled": 0,
    }
    assert narrowed["counts"] == unfiltered["counts"]


# --- 13.1.2 AC2: when the request was raised ---------------------------------------------------
@pytest.mark.story("13.1.2", ac=2)
def test_entry_shows_when_the_request_was_raised(venue_staff_client, db):
    booking = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        starts_at=datetime(2027, 2, 4, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 2, 4, 11, 0, tzinfo=timezone.utc),
    )

    entry = _entry(venue_staff_client, BOOKINGS_PATH, booking.id)

    assert datetime.fromisoformat(entry["created_at"]) == booking.created_at


# --- 13.1.2 AC3: when and why a request was decided --------------------------------------------
@pytest.mark.story("13.1.2", ac=3)
def test_a_rejected_booking_carries_its_decision_reason(venue_staff_client, db):
    booking = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        status=BookingStatus.REJECTED,
        decision_reason="The venue is under maintenance that week.",
        starts_at=datetime(2027, 2, 3, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 2, 3, 11, 0, tzinfo=timezone.utc),
    )

    entry = _entry(venue_staff_client, BOOKINGS_PATH, booking.id)

    assert entry["decision_reason"] == "The venue is under maintenance that week."


@pytest.mark.story("13.1.2", ac=3)
def test_a_decided_booking_carries_when_it_was_decided(venue_staff_client, db):
    decided_at = datetime(2026, 9, 25, 8, 30, tzinfo=timezone.utc)
    booking = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        status=BookingStatus.APPROVED,
        decided_by_id=Users.VENUE_STAFF.id,
        decided_at=decided_at,
        starts_at=datetime(2027, 2, 5, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 2, 5, 11, 0, tzinfo=timezone.utc),
    )

    entry = _entry(venue_staff_client, BOOKINGS_PATH, booking.id)

    assert datetime.fromisoformat(entry["decided_at"]) == decided_at


@pytest.mark.story("13.1.2", ac=3)
def test_a_pending_booking_has_no_decided_at(venue_staff_client):
    entry = _entry(venue_staff_client, PENDING_QUEUE_PATH, Bookings.PENDING_SEMINAR_ROOM)

    assert entry["decided_at"] is None


# --- 13.1.2 AC4: paging ------------------------------------------------------------------------
@pytest.mark.story("13.1.2", ac=4)
def test_limit_caps_the_page_and_total_counts_the_whole_tab(venue_staff_client):
    body = venue_staff_client.get(f"{PENDING_QUEUE_PATH}&limit=2").json()

    assert len(body["items"]) == 2
    assert body["total"] == 7


@pytest.mark.story("13.1.2", ac=4)
def test_the_next_page_continues_where_the_last_one_stopped(venue_staff_client):
    every_id = _ids(venue_staff_client, PENDING_QUEUE_PATH)
    first = _ids(venue_staff_client, f"{PENDING_QUEUE_PATH}&limit=3")
    second = _ids(venue_staff_client, f"{PENDING_QUEUE_PATH}&limit=3&offset=3")

    assert first + second == every_id[:6]


@pytest.mark.story("13.1.2", ac=4)
@pytest.mark.parametrize("query", ["?limit=1", "?limit=100", "?offset=0", "?offset=2147483647"])
def test_the_edges_of_the_allowed_range_are_accepted(venue_staff_client, query):
    assert venue_staff_client.get(f"{BOOKINGS_PATH}{query}").status_code == 200


@pytest.mark.story("13.1.2", ac=4)
@pytest.mark.parametrize(
    "query",
    ["?limit=0", "?limit=101", "?limit=-1", "?offset=-1", "?offset=2147483648", "?limit=ten"],
)
def test_a_limit_or_offset_outside_the_allowed_range_is_refused(venue_staff_client, query):
    assert venue_staff_client.get(f"{BOOKINGS_PATH}{query}").status_code == 422


# --- access control --------------------------------------------------------------------------
@pytest.mark.story("13.1")
@pytest.mark.story("1.2", ac=4)
@pytest.mark.parametrize(
    "user", [Users.ORGANISER, Users.COORDINATOR, Users.TECH_SUPPORT, Users.ATTENDEE]
)
def test_other_roles_cannot_see_the_queue(client, user):
    client.login(user)
    assert client.get(BOOKINGS_PATH).status_code == 403


@pytest.mark.story("13.1")
def test_signed_out_user_is_rejected(client):
    assert client.get(BOOKINGS_PATH).status_code == 401
