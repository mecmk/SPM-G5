"""Fix f13.2.1.1 (story 13.2.1 AC7) - the venue's capacity on the event page's booking cards.

AC7 Each venue booking on the event page shows the booked venue's capacity: the coordinator's
    Venue booking card (``GET /bookings/for-event``, 13.2.1 AC4) and the organiser's Venue
    bookings section (``GET /bookings/for-my-event``, f7.1.2). When the booking asks for a room
    layout and the venue gives that layout a capacity of its own (8.6), that layout and its
    capacity are shown as well. The figures are the venue's as it stands, not a copy taken when
    the booking was raised.

The cards themselves are proven in tests/e2e/events.spec.ts.

Boundary cases do not apply: nothing is typed, and a venue's capacity is checked when it is saved
(8.3). Permission cases do not apply: both endpoints keep their permissions, which
test_booking_for_event.py and test_organiser_bookings.py prove. Conflict cases do not apply: the
endpoints only read.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.events.models import Event, EventStatus
from app.venues.models import Venue
from tests.support.factories import make_booking, make_event, make_venue
from tests.support.seed import Users

_STARTS_AT = datetime(2027, 3, 15, 1, 0, tzinfo=UTC)
_ENDS_AT = datetime(2027, 3, 15, 9, 0, tzinfo=UTC)


def _event(db: Session) -> Event:
    """An event of Olivia's that Chloe coordinates, so both endpoints answer for it."""
    return make_event(db, status=EventStatus.PLANNING, assigned_coordinator_id=Users.COORDINATOR.id)


def _book(db: Session, event: Event, venue: Venue, *, layout_code: str | None = None) -> None:
    make_booking(
        db,
        venue_id=venue.id,
        event_id=event.id,
        starts_at=_STARTS_AT,
        ends_at=_ENDS_AT,
        required_layout_code=layout_code,
    )


def _only_entry(client, path: str) -> dict:
    response = client.get(path)
    assert response.status_code == 200, response.text
    [entry] = response.json()
    return entry


@pytest.mark.story("13.2.1", ac=7)
def test_the_coordinators_card_carries_the_venues_capacity(coordinator_client, db: Session):
    event = _event(db)
    _book(db, event, make_venue(db, capacity=120))

    entry = _only_entry(coordinator_client, f"/bookings/for-event/{event.id}")

    assert entry["venue_capacity"] == 120
    assert entry["layout_name"] is None
    assert entry["layout_capacity"] is None


@pytest.mark.story("13.2.1", ac=7)
def test_the_coordinators_card_carries_the_booked_layouts_own_capacity(
    coordinator_client, db: Session
):
    event = _event(db)
    venue = make_venue(db, capacity=120, layouts={"THEATRE": 80, "BANQUET": 60})
    _book(db, event, venue, layout_code="THEATRE")

    entry = _only_entry(coordinator_client, f"/bookings/for-event/{event.id}")

    assert entry["venue_capacity"] == 120
    assert entry["layout_name"] == "Theatre"
    assert entry["layout_capacity"] == 80


@pytest.mark.story("13.2.1", ac=7)
def test_a_layout_with_no_capacity_of_its_own_names_the_layout_without_one(
    coordinator_client, db: Session
):
    event = _event(db)
    _book(db, event, make_venue(db, capacity=120, layouts={"THEATRE": None}), layout_code="THEATRE")

    entry = _only_entry(coordinator_client, f"/bookings/for-event/{event.id}")

    assert entry["venue_capacity"] == 120
    assert entry["layout_name"] == "Theatre"
    assert entry["layout_capacity"] is None


@pytest.mark.story("13.2.1", ac=7)
def test_the_capacity_is_the_venues_as_it_stands_now(coordinator_client, db: Session):
    event = _event(db)
    venue = make_venue(db, capacity=120, layouts={"THEATRE": 80})
    _book(db, event, venue, layout_code="THEATRE")
    venue.capacity = 150
    venue.layouts[0].layout_capacity = 90
    db.flush()

    entry = _only_entry(coordinator_client, f"/bookings/for-event/{event.id}")

    assert entry["venue_capacity"] == 150
    assert entry["layout_capacity"] == 90


@pytest.mark.story("13.2.1", ac=7)
def test_the_organisers_section_carries_the_venues_and_layouts_capacity(
    organiser_client, db: Session
):
    event = _event(db)
    venue = make_venue(db, capacity=120, layouts={"THEATRE": 80})
    _book(db, event, venue, layout_code="THEATRE")

    entry = _only_entry(organiser_client, f"/bookings/for-my-event/{event.id}")

    assert entry["venue_capacity"] == 120
    assert entry["layout_name"] == "Theatre"
    assert entry["layout_capacity"] == 80
