"""Story 12.1 AC1, AC5 and AC9 - f12.1.2: setup and teardown on a venue booking request.

AC1 From the catalogue in event context, the coordinator enters setup and teardown durations in
    days, hours and minutes (both default to 0). The booked period (event start minus setup, to
    event end plus teardown) is shown before submitting.
AC5 A setup or teardown of 0 is allowed; negative values are refused. Setup can extend into
    earlier days and teardown into later days (e.g. 2 days of setup before a 1-day event).
AC9 Setup that would push the booked start into the past is refused.

That is the backlog's current numbering. The older 12.1 tests (test_raise_booking_request.py) keep
Sprint 1's AC1-AC4 numbering, so their AC1 is another criterion.

What the server does with them, decided for f12.1.2 (14 Oct 2026): ``POST /bookings`` and
``POST /bookings/{id}/switch`` take ``setup_minutes`` and ``teardown_minutes`` in whole minutes,
0 when not sent and each at most 14 days (20160 minutes, the longest an event may run; assumed,
not in the backlog), so a negative, fractional or longer value is refused (422). Both are stored
on the booking, whose booked period (``held_from`` to ``held_until``, set by the database's
trigger) runs from the setup before its own start to the teardown after its own end. A switch
carries what it sends, never the replaced request's. AC9 has a sentence of its own, for a setup
that would start in the past while the booking's own start is still ahead; an own start already
past keeps 12.7's.

The booked period, setup and teardown included, is also what the request holds (12.1 AC3) and
what the venue is checked on again at submission, for its other holds and recorded closures
(AC14); periods that only touch do not clash (AC6). test_venue_hold.py and
test_request_rechecks_venue.py prove those on the booking's own period, and the cases tagged with
them here prove them on its setup.

Proven elsewhere: the request step's Setup and Teardown inputs, the booked period it shows and
its refusals before anything is sent are tests/e2e/booking-requests.spec.ts; AC16 (opening hours
on the booking's own times) and AC17 (saying when setup or teardown runs outside them) are
test_request_opening_hours.py; a request that sends neither is test_raise_booking_request.py's
``test_setup_and_teardown_default_to_0_so_the_held_period_is_the_event_period``.

Every case is a Planning event assigned to Chloe, at a fresh venue with no opening hours recorded:
an additional venue is judged on its number of people alone (story 11.1), which a fresh venue
holds, and the opening-hours rule, which AC16 changes, decides nothing here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bookings.models import VenueBooking
from app.events.models import Event, EventStatus
from tests.support.factories import make_booking, make_event, make_unavailability, make_venue
from tests.support.seed import Users

SGT = timezone(timedelta(hours=8))
# Decided for f12.1.2 (14 Oct 2026): setup and teardown are each at most 14 days, the longest an
# event may run.
LONGEST_TURNAROUND_MINUTES = 14 * 24 * 60


def _at(hour: int, minute: int = 0) -> datetime:
    """A moment on Monday 5 April 2027, Singapore time."""
    return datetime(2027, 4, 5, hour, minute, tzinfo=SGT)


def _in(*, hours: float) -> datetime:
    """A moment that many hours from now, to the second."""
    return datetime.now(UTC).replace(microsecond=0) + timedelta(hours=hours)


def _event(db: Session, starts_at: datetime, ends_at: datetime, **overrides) -> Event:
    """A Planning event assigned to Chloe, so she may request a venue for it."""
    return make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=starts_at,
        ends_at=ends_at,
        **overrides,
    )


def _request(client, event_id: uuid.UUID, venue_id: uuid.UUID, **turnaround):
    """Request ``venue_id`` for ``event_id`` as an additional venue, with whichever of
    ``setup_minutes`` and ``teardown_minutes`` ``turnaround`` gives."""
    return client.post(
        "/bookings", json={"event_id": str(event_id), "venue_id": str(venue_id), **turnaround}
    )


def _bookings_for(db: Session, event_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(VenueBooking).where(VenueBooking.event_id == event_id)
    )


# --- AC1: sent and stored with the request, and the booked period runs from one to the other ---
@pytest.mark.story("12.1", ac=1)
def test_setup_and_teardown_are_stored_and_hold_the_venue_before_and_after_the_event(
    coordinator_client, db
):
    """90 minutes of setup and 45 of teardown around a 09:00-12:00 event: the venue is held from
    07:30 to 12:45, while the booking's own times stay the event's."""
    event = _event(db, _at(9), _at(12))

    response = _request(
        coordinator_client, event.id, make_venue(db).id, setup_minutes=90, teardown_minutes=45
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["setup_minutes"], body["teardown_minutes"]) == (90, 45)
    assert datetime.fromisoformat(body["starts_at"]) == _at(9)
    assert datetime.fromisoformat(body["ends_at"]) == _at(12)
    assert datetime.fromisoformat(body["held_from"]) == _at(7, 30)
    assert datetime.fromisoformat(body["held_until"]) == _at(12, 45)


@pytest.mark.story("12.1", ac=1)
def test_a_switch_stores_the_setup_and_teardown_sent_with_it(coordinator_client, db):
    """A switch is a new request (story 12.5), so it carries the setup and teardown it sends, not
    the 30 and 15 minutes of the request it replaces."""
    event = _event(db, _at(9), _at(12))
    replaced = make_booking(
        db,
        event_id=event.id,
        venue_id=make_venue(db).id,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        setup_minutes=30,
        teardown_minutes=15,
    )

    response = coordinator_client.post(
        f"/bookings/{replaced.id}/switch",
        json={"venue_id": str(make_venue(db).id), "setup_minutes": 60, "teardown_minutes": 20},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["setup_minutes"], body["teardown_minutes"]) == (60, 20)
    assert datetime.fromisoformat(body["held_from"]) == _at(8)
    assert datetime.fromisoformat(body["held_until"]) == _at(12, 20)


# --- AC3 / AC6 / AC14: the booked period, setup included, is what is held and checked ----------
@pytest.mark.story("12.1", ac=3)
def test_a_setup_reaching_into_another_requests_held_period_is_refused_naming_it(
    coordinator_client, db
):
    """Another event's pending request holds the room from 09:00 to 11:00. This event starts at
    12:00, clear of it, but 90 minutes of setup would start at 10:30."""
    venue = make_venue(db, name="Setup Clash Room")
    briefing = _event(db, _at(9), _at(11), name="Morning Briefing")
    make_booking(db, venue_id=venue.id, event_id=briefing.id, starts_at=_at(9), ends_at=_at(11))
    event = _event(db, _at(12), _at(14))

    response = _request(coordinator_client, event.id, venue.id, setup_minutes=90)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Setup Clash Room is already held by a pending request for Morning Briefing on Mon 5 Apr"
        " 2027 from 09:00 to 11:00."
    )
    assert _bookings_for(db, event.id) == 0


@pytest.mark.story("12.1", ac=6)
def test_a_setup_that_only_touches_another_requests_held_period_is_accepted(coordinator_client, db):
    """The other request holds the room until 11:00, and an hour of setup before the 12:00 start
    begins exactly then: touching is no clash, so the booked period starts at 11:00."""
    venue = make_venue(db)
    briefing = _event(db, _at(9), _at(11))
    make_booking(db, venue_id=venue.id, event_id=briefing.id, starts_at=_at(9), ends_at=_at(11))
    event = _event(db, _at(12), _at(14))

    response = _request(coordinator_client, event.id, venue.id, setup_minutes=60)

    assert response.status_code == 201, response.text
    assert datetime.fromisoformat(response.json()["held_from"]) == _at(11)


@pytest.mark.story("12.1", ac=14)
def test_a_closure_covering_only_the_setup_blocks_the_request(coordinator_client, db):
    """The room is closed until 09:00, when the event starts, so the closure only touches the
    event's own period (AC6), but an hour of setup would start at 08:00."""
    venue = make_venue(db, name="Setup Closure Room")
    make_unavailability(db, venue_id=venue.id, starts_at=_at(7), ends_at=_at(9))
    event = _event(db, _at(9), _at(12))

    response = _request(coordinator_client, event.id, venue.id, setup_minutes=60)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Setup Closure Room is closed for maintenance on Mon 5 Apr 2027 from 07:00 to 09:00."
    )
    assert _bookings_for(db, event.id) == 0


# --- AC5: whole minutes, from 0 to 14 days ------------------------------------------------------
@pytest.mark.story("12.1", ac=5)
@pytest.mark.parametrize(
    "turnaround",
    [{"setup_minutes": -1}, {"teardown_minutes": -1}],
    ids=["negative setup", "negative teardown"],
)
def test_a_negative_setup_or_teardown_is_refused(coordinator_client, db, turnaround):
    event = _event(db, _at(9), _at(12))

    response = _request(coordinator_client, event.id, make_venue(db).id, **turnaround)

    assert response.status_code == 422
    assert _bookings_for(db, event.id) == 0


@pytest.mark.story("12.1", ac=5)
def test_a_fractional_setup_is_refused(coordinator_client, db):
    event = _event(db, _at(9), _at(12))

    response = _request(coordinator_client, event.id, make_venue(db).id, setup_minutes=1.5)

    assert response.status_code == 422
    assert _bookings_for(db, event.id) == 0


@pytest.mark.story("12.1", ac=5)
@pytest.mark.parametrize("field", ["setup_minutes", "teardown_minutes"])
def test_14_days_of_setup_or_teardown_is_accepted(coordinator_client, db, field):
    """The event is on 5 April 2027, so even 14 days of setup starts in the future and only the
    length is judged. Setup runs into earlier days, and teardown into later ones."""
    event = _event(db, _at(9), _at(12))

    response = _request(
        coordinator_client, event.id, make_venue(db).id, **{field: LONGEST_TURNAROUND_MINUTES}
    )

    assert response.status_code == 201, response.text
    assert response.json()[field] == LONGEST_TURNAROUND_MINUTES


@pytest.mark.story("12.1", ac=5)
@pytest.mark.parametrize("field", ["setup_minutes", "teardown_minutes"])
def test_14_days_and_a_minute_of_setup_or_teardown_is_refused(coordinator_client, db, field):
    event = _event(db, _at(9), _at(12))

    response = _request(
        coordinator_client, event.id, make_venue(db).id, **{field: LONGEST_TURNAROUND_MINUTES + 1}
    )

    assert response.status_code == 422
    assert _bookings_for(db, event.id) == 0


# --- AC9: a setup may not start in the past -----------------------------------------------------
@pytest.mark.story("12.1", ac=9)
def test_a_setup_that_would_start_in_the_past_is_refused(coordinator_client, db):
    """The event starts in two hours, but three hours of setup would have started an hour ago.
    Its own start is still ahead, so this is AC9's refusal, not 12.7's for a booked period whose
    own start has passed."""
    starts_at = _in(hours=2)
    event = _event(db, starts_at, starts_at + timedelta(hours=3))

    response = _request(coordinator_client, event.id, make_venue(db).id, setup_minutes=180)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This setup would start in the past, so the venue cannot be held for it."
    )
    assert _bookings_for(db, event.id) == 0


@pytest.mark.story("12.1", ac=9)
def test_a_setup_that_still_starts_in_the_future_is_accepted(coordinator_client, db):
    """The same event with an hour of setup: the booked period starts an hour from now."""
    starts_at = _in(hours=2)
    event = _event(db, starts_at, starts_at + timedelta(hours=3))

    response = _request(coordinator_client, event.id, make_venue(db).id, setup_minutes=60)

    assert response.status_code == 201, response.text
    assert datetime.fromisoformat(response.json()["held_from"]) == starts_at - timedelta(hours=1)
