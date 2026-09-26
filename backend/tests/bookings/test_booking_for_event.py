"""Story 13.2.1 AC4 - GET /bookings/for-event/{event_id}.

Lets a coordinator (or other internal staff) read every venue booking ever raised for an event,
without knowing any booking's id up front. An event may accumulate more than one row over time -
a rejected request followed by a fresh one, possibly for a different venue - so this is a
history, most recent first, not a single outcome. ``Events.APPROVED`` itself already seeds two
bookings (see ``020_sample_data.sql``'s note above the ``venue_bookings`` insert), which is what
first showed the old "latest only" endpoint was silently hiding one of them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from tests.support.factories import make_booking
from tests.support.seed import Bookings, Events, Users, Venues


def _booking_ids(body: list[dict]) -> set[str]:
    return {entry["id"] for entry in body}


@pytest.mark.story("13.2.1", ac=4)
def test_returns_every_seeded_booking_for_the_event(venue_staff_client):
    response = venue_staff_client.get(f"/bookings/for-event/{Events.APPROVED}")

    assert response.status_code == 200
    body = response.json()
    assert _booking_ids(body) == {
        str(Bookings.APPROVED_GRAND_HALL),
        str(Bookings.PENDING_SEMINAR_ROOM),
    }
    by_id = {entry["id"]: entry for entry in body}
    approved = by_id[str(Bookings.APPROVED_GRAND_HALL)]
    assert approved["venue_name"] == "Grand Hall"
    assert approved["venue_location"] == "Tower A, Level 1"
    assert approved["status"] == "APPROVED"
    assert approved["decision_reason"] is None


@pytest.mark.story("13.2.1", ac=4)
def test_a_freshly_raised_booking_appears_first(venue_staff_client, db):
    """A booking made just now sorts ahead of the seeded rows already on this event - the page
    reads the list as a history, newest first."""
    fresh = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        event_id=Events.APPROVED,
        status="REJECTED",
        starts_at=datetime(2027, 3, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 3, 1, 11, 0, tzinfo=timezone.utc),
        decision_reason="The boardroom is too small for this event.",
    )
    db.commit()

    response = venue_staff_client.get(f"/bookings/for-event/{Events.APPROVED}")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3
    assert body[0]["id"] == str(fresh.id)
    assert body[0]["venue_name"] == "Boardroom 3.4"
    assert body[0]["status"] == "REJECTED"
    assert body[0]["decision_reason"] == "The boardroom is too small for this event."
    assert _booking_ids(body[1:]) == {
        str(Bookings.APPROVED_GRAND_HALL),
        str(Bookings.PENDING_SEMINAR_ROOM),
    }


@pytest.mark.story("13.2.1", ac=4)
def test_ignores_an_unrelated_booking_for_a_different_event(venue_staff_client, db):
    """Only this event's own bookings come back - a booking on a different event, even for the
    same venue, is not part of this event's history."""
    make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        event_id=Events.PLANNING,
        status="REJECTED",
        starts_at=datetime(2027, 3, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 3, 1, 11, 0, tzinfo=timezone.utc),
    )
    db.commit()

    response = venue_staff_client.get(f"/bookings/for-event/{Events.PLANNING}")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["venue_name"] == "Boardroom 3.4"


@pytest.mark.story("13.2.1", ac=4)
def test_an_event_with_no_booking_returns_an_empty_list(venue_staff_client):
    response = venue_staff_client.get(f"/bookings/for-event/{Events.DRAFT}")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.story("13.2.1", ac=4)
def test_an_unknown_event_returns_an_empty_list(venue_staff_client):
    """No event-existence check here - an id that matches no booking looks the same as an event
    with none, and the caller already knows the event exists (they just read it)."""
    response = venue_staff_client.get(f"/bookings/for-event/{uuid.uuid4()}")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.story("13.2.1", ac=4)
def test_the_requesting_coordinator_can_read_it(coordinator_client):
    response = coordinator_client.get(f"/bookings/for-event/{Events.APPROVED}")
    assert response.status_code == 200
    assert len(response.json()) == 2


@pytest.mark.story("13.2.1", ac=4)
def test_signed_out_visitors_cannot_read_it(client):
    assert client.get(f"/bookings/for-event/{Events.APPROVED}").status_code == 401


@pytest.mark.story("13.2.1", ac=4)
def test_a_role_without_bookings_read_cannot_read_it(client):
    client.login(Users.ORGANISER)
    assert client.get(f"/bookings/for-event/{Events.APPROVED}").status_code == 403
