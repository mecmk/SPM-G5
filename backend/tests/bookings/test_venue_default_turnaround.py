"""Story 12.1 AC19, AC21 and AC22 - f12.1.3: a venue's configured setup and turnaround times on a
booking request.

AC19 Venue Staff see the requested setup and teardown beside the venue's defaults on the queue
     card and the request page (13.1), with any difference marked, so they take it into account
     when approving (13.2).
AC21 The pre-fill happens when the request step opens, from the venue record as it stands.
     Changing a venue's defaults afterwards changes no request already raised: the figures on a
     booking are its own (AC3). Switch to this venue (12.5 AC10) pre-fills from the new venue.
AC22 No new permission: the defaults are read with the venue record (8.2), and only Venue Staff
     set them (8.3 AC4). The server still accepts whatever setup and teardown the request sends,
     within AC5.

What the server does, decided for f12.1.3 (4 Nov 2026): Venue Staff's queue gives each request its
venue's ``setup_minutes_default`` and ``teardown_minutes_default`` as they stand now, beside the
request's own ``setup_minutes`` and ``teardown_minutes``, so the card can mark a difference. The
request page reads the venue record itself (8.2), which already carries both.

Proven elsewhere: the request step's pre-fill, its marking of a changed figure, the 0 and 14-day
boundaries (AC18, AC20) and the switch's pre-fill from the new venue (AC21) are the step's own and
are tests/e2e/booking-requests.spec.ts's, as is what the card and the page show (AC19). AC5's
refusals are test_request_setup_and_teardown.py's; only Venue Staff changing a venue's defaults is
story 8.3's (tests/venues/).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.events.models import Event, EventStatus
from tests.support.factories import make_booking, make_event, make_venue
from tests.support.seed import Users

SGT = timezone(timedelta(hours=8))


def _at(hour: int) -> datetime:
    """A moment on Monday 5 April 2027, Singapore time."""
    return datetime(2027, 4, 5, hour, tzinfo=SGT)


def _event(db: Session) -> Event:
    """A Planning event assigned to Chloe, 09:00-12:00, so she may request a venue for it."""
    return make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=_at(9),
        ends_at=_at(12),
    )


def _queue_entry(client, booking_id: uuid.UUID) -> dict:
    """``booking_id``'s entry in Venue Staff's Pending tab (story 13.1)."""
    response = client.get("/bookings", params={"status": "PENDING"})
    assert response.status_code == 200
    return next(entry for entry in response.json()["items"] if entry["id"] == str(booking_id))


# --- AC19: the queue gives each request its venue's defaults beside its own figures -------------
@pytest.mark.story("12.1", ac=19)
def test_the_queue_gives_each_request_its_venues_defaults(venue_staff_client, db):
    """90 minutes of setup asked for at a venue whose default is 60, and 15 of teardown at its
    default of 15: the entry carries both pairs, so the card can mark the setup."""
    venue = make_venue(db, setup_minutes_default=60, teardown_minutes_default=15)
    booking = make_booking(
        db,
        event_id=_event(db).id,
        venue_id=venue.id,
        starts_at=_at(9),
        ends_at=_at(12),
        setup_minutes=90,
        teardown_minutes=15,
    )

    entry = _queue_entry(venue_staff_client, booking.id)

    assert (entry["setup_minutes"], entry["teardown_minutes"]) == (90, 15)
    assert (entry["venue_setup_minutes_default"], entry["venue_teardown_minutes_default"]) == (
        60,
        15,
    )


@pytest.mark.story("12.1", ac=19)
def test_a_venue_with_defaults_of_0_gives_0_on_the_queue(venue_staff_client, db):
    """AC20's boundary on the queue: a venue with no setup or turnaround configured gives 0, not
    nothing, so a request with none matches it."""
    booking = make_booking(
        db,
        event_id=_event(db).id,
        venue_id=make_venue(db).id,
        starts_at=_at(9),
        ends_at=_at(12),
    )

    entry = _queue_entry(venue_staff_client, booking.id)

    assert (entry["venue_setup_minutes_default"], entry["venue_teardown_minutes_default"]) == (
        0,
        0,
    )


# --- AC21: later changes to the defaults leave a raised request's figures alone ----------------
@pytest.mark.story("12.1", ac=21)
def test_changing_a_venues_defaults_leaves_a_raised_request_alone(login_as, db):
    """Chloe requests with the venue's 30 and 15 minutes; Venue Staff then raise its defaults to
    60 and 45. The request keeps 30 and 15, and its card now shows them against 60 and 45."""
    venue = make_venue(db, setup_minutes_default=30, teardown_minutes_default=15)
    raised = login_as(Users.COORDINATOR).post(
        "/bookings",
        json={
            "event_id": str(_event(db).id),
            "venue_id": str(venue.id),
            "setup_minutes": 30,
            "teardown_minutes": 15,
        },
    )
    assert raised.status_code == 201, raised.text

    venue_staff_client = login_as(Users.VENUE_STAFF)
    changed = venue_staff_client.patch(
        f"/venues/{venue.id}",
        json={"setup_minutes_default": 60, "teardown_minutes_default": 45},
    )
    assert changed.status_code == 200, changed.text

    entry = _queue_entry(venue_staff_client, uuid.UUID(raised.json()["id"]))
    assert (entry["setup_minutes"], entry["teardown_minutes"]) == (30, 15)
    assert datetime.fromisoformat(entry["held_from"]) == _at(9) - timedelta(minutes=30)
    assert (entry["venue_setup_minutes_default"], entry["venue_teardown_minutes_default"]) == (
        60,
        45,
    )


# --- AC22: the server takes what the request sends, whatever the venue's defaults ---------------
@pytest.mark.story("12.1", ac=22)
def test_a_request_away_from_the_venues_defaults_is_accepted_as_sent(coordinator_client, db):
    """The coordinator may change either figure (AC18), so 0 of setup and 120 of teardown at a
    venue whose defaults are 60 and 30 are stored as sent, not replaced by the defaults."""
    venue = make_venue(db, setup_minutes_default=60, teardown_minutes_default=30)

    response = coordinator_client.post(
        "/bookings",
        json={
            "event_id": str(_event(db).id),
            "venue_id": str(venue.id),
            "setup_minutes": 0,
            "teardown_minutes": 120,
        },
    )

    assert response.status_code == 201, response.text
    assert (response.json()["setup_minutes"], response.json()["teardown_minutes"]) == (0, 120)


@pytest.mark.story("12.1", ac=22)
def test_a_request_that_sends_no_setup_or_teardown_is_not_given_the_venues_defaults(
    coordinator_client, db
):
    """The pre-fill is the request step's: a request sent without either figure still stores 0
    (AC1), whatever the venue's defaults."""
    venue = make_venue(db, setup_minutes_default=60, teardown_minutes_default=30)

    response = coordinator_client.post(
        "/bookings", json={"event_id": str(_event(db).id), "venue_id": str(venue.id)}
    )

    assert response.status_code == 201, response.text
    assert (response.json()["setup_minutes"], response.json()["teardown_minutes"]) == (0, 0)
