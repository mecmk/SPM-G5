"""Story 12.1 AC16 and AC17 - f12.1.2: opening hours on the booking's own times.

AC16 A request is checked against the venue's opening hours on the event's own times, or its
     venue requirement's (12.5), not on the booked period: setup and teardown may run outside the
     hours (replaces the opening-hours part of AC2 and AC14) (Q28, Q51). Times that start exactly
     at opening or end exactly at closing are within the hours, and a request whose own times
     fall outside them is still refused, naming the hours (AC14).
AC17 When setup or teardown runs outside the opening hours, the request step says so before
     submitting, and Venue Staff see it on the request (13.1), so they decide when approving
     (13.2).

The customer's answers behind them (12 Oct 2026): an event's own times are agreed with the
organiser inside the venue's opening hours before it is requested (Q28), and whether its setup and
turnaround may run outside them is for Venue Staff to weigh when they approve (Q51).

AC16 moves only the opening-hours check. The booked period, setup and teardown included, is still
what the request holds and what it is checked on for the venue's other holds and recorded
closures (test_request_setup_and_teardown.py), and the request step still shows the server's
refusal as it shows any (12.1 AC14, tests/e2e/booking-requests.spec.ts).

AC17: the step's notice, and what Venue Staff see on the queue card and the request's page, are
tests/e2e/booking-requests.spec.ts's. Here: the queue gives each request what its card needs to
say so - its setup and teardown, the end of its booked period and its venue's opening hours. The
request's page already reads the booking and the venue.

Every request is Chloe's, for a Planning event on Monday 5 April 2027, Singapore time, at a fresh
venue open 08:00 to 18:00 unless a case says otherwise.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bookings.models import VenueBooking
from app.events.models import Event, EventStatus
from app.venues.models import Venue
from tests.support.factories import make_booking, make_event, make_venue, make_venue_requirement
from tests.support.seed import Users

SGT = timezone(timedelta(hours=8))
OPENS = time(8, 0)
CLOSES = time(18, 0)


def _at(hour: int, minute: int = 0, *, day: int = 5) -> datetime:
    """A moment in April 2027, Singapore time - on Monday the 5th unless ``day`` says otherwise."""
    return datetime(2027, 4, day, hour, minute, tzinfo=SGT)


def _event(db: Session, starts_at: datetime, ends_at: datetime) -> Event:
    """A Planning event assigned to Chloe, so she may request a venue for it."""
    return make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=starts_at,
        ends_at=ends_at,
    )


def _venue(db: Session, **overrides) -> Venue:
    """A fresh venue open 08:00 to 18:00, roomy enough for any event here (story 11.1)."""
    return make_venue(db, hours=(OPENS, CLOSES), **overrides)


def _request(client, event_id: uuid.UUID, venue_id: uuid.UUID, **extra):
    """Request ``venue_id`` for ``event_id``, with whatever else ``extra`` names (setup and
    teardown minutes, a venue requirement)."""
    return client.post(
        "/bookings", json={"event_id": str(event_id), "venue_id": str(venue_id), **extra}
    )


def _bookings_for(db: Session, event_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(VenueBooking).where(VenueBooking.event_id == event_id)
    )


# --- AC16: the booking's own times are checked against the hours, not its setup and teardown ----
@pytest.mark.story("12.1", ac=16)
def test_a_setup_before_opening_is_accepted(coordinator_client, db):
    """The event runs 09:00-12:00, inside the venue's 08:00-18:00. Two hours of setup start at
    07:00, before it opens: Venue Staff weigh that when they approve (Q51), so it is no refusal."""
    event = _event(db, _at(9), _at(12))

    response = _request(coordinator_client, event.id, _venue(db).id, setup_minutes=120)

    assert response.status_code == 201, response.text
    assert datetime.fromisoformat(response.json()["held_from"]) == _at(7)


@pytest.mark.story("12.1", ac=16)
def test_a_teardown_after_closing_is_accepted(coordinator_client, db):
    """The event runs 15:00-17:00; two hours of teardown run to 19:00, past the 18:00 closing."""
    event = _event(db, _at(15), _at(17))

    response = _request(coordinator_client, event.id, _venue(db).id, teardown_minutes=120)

    assert response.status_code == 201, response.text
    assert datetime.fromisoformat(response.json()["held_until"]) == _at(19)


@pytest.mark.story("12.1", ac=16)
@pytest.mark.parametrize(
    ("starts_at", "ends_at", "turnaround"),
    [
        (_at(8), _at(12), {"setup_minutes": 30}),
        (_at(14), _at(18), {"teardown_minutes": 30}),
    ],
    ids=["from exactly opening, with setup", "to exactly closing, with teardown"],
)
def test_own_times_from_opening_or_to_closing_are_within_the_hours(
    coordinator_client, db, starts_at, ends_at, turnaround
):
    """Own times starting exactly at opening, or ending exactly at closing, are within the hours,
    whatever setup runs before them or teardown after."""
    event = _event(db, starts_at, ends_at)

    response = _request(coordinator_client, event.id, _venue(db).id, **turnaround)

    assert response.status_code == 201, response.text


@pytest.mark.story("12.1", ac=16)
@pytest.mark.parametrize(
    ("starts_at", "ends_at", "named"),
    [
        (_at(7, 59), _at(12), "from 07:59 to 12:00"),
        (_at(14), _at(18, 1), "from 14:00 to 18:01"),
    ],
    ids=["a minute before opening", "a minute past closing"],
)
def test_own_times_a_minute_outside_the_hours_are_refused_naming_them(
    coordinator_client, db, starts_at, ends_at, named
):
    """AC14's refusal stands for the booking's own times: a minute either side is outside, and
    the refusal names the hours."""
    venue = _venue(db, name="Hours Room")
    event = _event(db, starts_at, ends_at)

    response = _request(coordinator_client, event.id, venue.id)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        f"Hours Room is open 08:00 to 18:00, so it cannot take an event {named}."
    )
    assert _bookings_for(db, event.id) == 0


@pytest.mark.story("12.1", ac=16)
def test_a_refusal_names_the_own_times_not_the_setups(coordinator_client, db):
    """Own times of 07:30-12:00 are outside 08:00-18:00 whatever the setup, and the refusal names
    them, not the 06:30 an hour of setup would start at."""
    venue = _venue(db, name="Early Room")
    event = _event(db, _at(7, 30), _at(12))

    response = _request(coordinator_client, event.id, venue.id, setup_minutes=60)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Early Room is open 08:00 to 18:00, so it cannot take an event from 07:30 to 12:00."
    )
    assert _bookings_for(db, event.id) == 0


@pytest.mark.story("12.1", ac=16)
def test_days_of_setup_at_a_venue_with_opening_hours_are_accepted(coordinator_client, db):
    """12.1 AC5's days of setup before a one-day event, at a venue with opening hours: two days
    and two hours start the booked period at 07:00 on the Saturday, so it runs through two nights
    and starts before the venue opens - but only the event's own 09:00-12:00 meets the hours."""
    event = _event(db, _at(9), _at(12))

    response = _request(
        coordinator_client, event.id, _venue(db).id, setup_minutes=2 * 24 * 60 + 2 * 60
    )

    assert response.status_code == 201, response.text
    assert datetime.fromisoformat(response.json()["held_from"]) == _at(7, day=3)


@pytest.mark.story("12.1", ac=16)
def test_a_venue_requirements_own_times_are_what_is_checked(coordinator_client, db):
    """Story 12.5: a request for a venue requirement carries the requirement's own times. The
    event runs 09:00-17:00 and its requirement 13:00-15:00; six hours of setup start at 07:00,
    before the venue opens, and are accepted, since 13:00-15:00 is inside its hours."""
    event = _event(db, _at(9), _at(17))
    requirement_id = make_venue_requirement(db, event.id, starts_at=_at(13), ends_at=_at(15))

    response = _request(
        coordinator_client,
        event.id,
        _venue(db).id,
        venue_requirement_id=str(requirement_id),
        setup_minutes=360,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert datetime.fromisoformat(body["starts_at"]) == _at(13)
    assert datetime.fromisoformat(body["held_from"]) == _at(7)


@pytest.mark.story("12.1", ac=16)
def test_a_refusal_for_a_venue_requirement_names_its_own_times(coordinator_client, db):
    """The requirement runs 16:30-18:30, past the venue's 18:00 closing. The refusal names its own
    16:30 to 18:30 - not the event's times, nor the 16:00 half an hour of setup would start at."""
    venue = _venue(db, name="Late Room")
    event = _event(db, _at(9), _at(19))
    requirement_id = make_venue_requirement(
        db, event.id, starts_at=_at(16, 30), ends_at=_at(18, 30)
    )

    response = _request(
        coordinator_client,
        event.id,
        venue.id,
        venue_requirement_id=str(requirement_id),
        setup_minutes=30,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Late Room is open 08:00 to 18:00, so it cannot take an event from 16:30 to 18:30."
    )
    assert _bookings_for(db, event.id) == 0


@pytest.mark.story("12.1", ac=16)
def test_a_switch_is_checked_on_its_own_times_too(coordinator_client, db):
    """A switch is checked as a new request is (story 12.5): moving to a venue whose hours leave
    out only the setup is accepted."""
    event = _event(db, _at(9), _at(12))
    replaced = make_booking(
        db,
        event_id=event.id,
        venue_id=make_venue(db).id,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
    )

    response = coordinator_client.post(
        f"/bookings/{replaced.id}/switch",
        json={"venue_id": str(_venue(db).id), "setup_minutes": 120},
    )

    assert response.status_code == 201, response.text
    assert datetime.fromisoformat(response.json()["held_from"]) == _at(7)


# --- AC17: Venue Staff see setup and teardown outside the hours on the request (13.1) -----------
def _queue_entry(client, booking_id: uuid.UUID) -> dict:
    """``booking_id``'s entry in Venue Staff's Pending tab (story 13.1)."""
    response = client.get("/bookings", params={"status": "PENDING"})
    assert response.status_code == 200
    return next(entry for entry in response.json()["items"] if entry["id"] == str(booking_id))


@pytest.mark.story("12.1", ac=17)
def test_the_queue_gives_each_request_its_setup_teardown_and_venue_hours(venue_staff_client, db):
    """What the queue card needs to say whether the setup or teardown runs outside the venue's
    hours: both durations, the booked period from its start to its end, and the hours. 90 minutes
    of setup before 09:00 start at 07:30, before the venue opens at 08:00."""
    booking = make_booking(
        db,
        event_id=_event(db, _at(9), _at(12)).id,
        venue_id=_venue(db).id,
        starts_at=_at(9),
        ends_at=_at(12),
        setup_minutes=90,
        teardown_minutes=45,
    )

    entry = _queue_entry(venue_staff_client, booking.id)

    assert (entry["setup_minutes"], entry["teardown_minutes"]) == (90, 45)
    assert datetime.fromisoformat(entry["held_from"]) == _at(7, 30)
    assert datetime.fromisoformat(entry["held_until"]) == _at(12, 45)
    assert (entry["venue_operating_hours_start"], entry["venue_operating_hours_end"]) == (
        "08:00:00",
        "18:00:00",
    )


@pytest.mark.story("12.1", ac=17)
def test_a_venue_with_no_recorded_hours_gives_none_on_the_queue(venue_staff_client, db):
    """No hours are recorded, so nothing can run outside them, and the card says nothing."""
    booking = make_booking(
        db,
        event_id=_event(db, _at(9), _at(12)).id,
        venue_id=make_venue(db).id,
        starts_at=_at(9),
        ends_at=_at(12),
        setup_minutes=90,
    )

    entry = _queue_entry(venue_staff_client, booking.id)

    assert (entry["venue_operating_hours_start"], entry["venue_operating_hours_end"]) == (
        None,
        None,
    )
