"""Story 12.1 AC14 (built as s8.1) - the request step re-checks the venue.

A venue can stop being available between the catalogue search and Send request, so
``POST /bookings`` applies the search's availability rules again and refuses, naming why:

* booked or held - s12.1's ``VenueHeld`` (test_venue_hold.py), not repeated here;
* blocked - an unavailability period overlapping the event's period;
* closed at those hours - the event's daily window falls outside the venue's opening hours.

A venue with no recorded hours can still be requested, and a closure that only touches the
event's period does not block it (AC6). Every event here is a Planning event assigned to Chloe,
so nothing but the venue stands in the request's way.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bookings.models import VenueBooking
from app.events.models import Event, EventStatus
from tests.support.factories import make_event, make_unavailability, make_venue
from tests.support.seed import Users, Venues

SGT = timezone(timedelta(hours=8))


def _event(db: Session, starts_at: datetime, ends_at: datetime) -> Event:
    """A Planning event assigned to Chloe, so she may request a venue for it."""
    return make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=starts_at,
        ends_at=ends_at,
    )


def _request(client, event_id: uuid.UUID, venue_id: uuid.UUID):
    return client.post("/bookings", json={"event_id": str(event_id), "venue_id": str(venue_id)})


def _bookings_for(db: Session, event_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(VenueBooking).where(VenueBooking.event_id == event_id)
    )


@pytest.mark.story("12.1", ac=14)
def test_a_blocked_venue_cannot_be_requested(coordinator_client, db):
    # Seminar Room 2.1 is closed for air-con servicing from 2 Nov 00:00 to 4 Nov 00:00 (seed).
    event = _event(
        db, datetime(2026, 11, 3, 9, 0, tzinfo=SGT), datetime(2026, 11, 3, 12, 0, tzinfo=SGT)
    )

    response = _request(coordinator_client, event.id, Venues.SEMINAR_ROOM)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Seminar Room 2.1 is closed for maintenance from Mon 2 Nov 2026, 00:00 to "
        "Wed 4 Nov 2026, 00:00."
    )
    assert _bookings_for(db, event.id) == 0


@pytest.mark.story("12.1", ac=14)
def test_a_venue_closed_at_those_hours_cannot_be_requested(coordinator_client, db):
    # Boardroom 3.4 opens 08:00 to 18:00 (seed) and has no bookings.
    event = _event(
        db, datetime(2027, 3, 4, 17, 0, tzinfo=SGT), datetime(2027, 3, 4, 19, 0, tzinfo=SGT)
    )

    response = _request(coordinator_client, event.id, Venues.BOARDROOM)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Boardroom 3.4 is open 08:00 to 18:00, so it cannot take an event from 17:00 to 19:00."
    )
    assert _bookings_for(db, event.id) == 0


@pytest.mark.story("12.1", ac=14)
def test_a_venue_without_recorded_hours_can_be_requested(coordinator_client, db):
    # Exhibition Foyer's hours are not recorded (seed), and it is free on 10 Dec 2026.
    event = _event(
        db, datetime(2026, 12, 10, 20, 0, tzinfo=SGT), datetime(2026, 12, 10, 23, 30, tzinfo=SGT)
    )

    response = _request(coordinator_client, event.id, Venues.EXHIBITION_FOYER)

    assert response.status_code == 201, response.text
    assert _bookings_for(db, event.id) == 1


@pytest.mark.story("12.1", ac=6)
def test_touching_unavailability_does_not_block_a_request(coordinator_client, db):
    starts_at = datetime(2027, 3, 5, 10, 0, tzinfo=SGT)
    ends_at = datetime(2027, 3, 5, 12, 0, tzinfo=SGT)
    venue = make_venue(db, hours=(time(8, 0), time(18, 0)))
    make_unavailability(
        db, venue_id=venue.id, starts_at=starts_at - timedelta(days=1), ends_at=starts_at
    )
    make_unavailability(
        db, venue_id=venue.id, starts_at=ends_at, ends_at=ends_at + timedelta(days=1)
    )
    event = _event(db, starts_at, ends_at)

    response = _request(coordinator_client, event.id, venue.id)

    assert response.status_code == 201, response.text
