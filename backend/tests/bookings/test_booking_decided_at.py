"""Story 13.2.2 AC1 - ``decided_at`` on GET /bookings/for-event/{event_id}.

The event page shows when Venue Staff decided a booking, from the ``decided_at`` this endpoint
returns. The frontend's ``VenueBooking`` type is a hand-written mirror, so nothing else ties that
line to the API: these tests do. Who may read the endpoint at all is story 13.2.1's, in
``test_booking_for_event.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.support.seed import Bookings, Events

SINGAPORE = timezone(timedelta(hours=8))


def _booking(client, booking_id) -> dict:
    response = client.get(f"/bookings/for-event/{Events.APPROVED}")
    assert response.status_code == 200
    return next(entry for entry in response.json() if entry["id"] == str(booking_id))


@pytest.mark.story("13.2.2", ac=1)
def test_a_pending_booking_has_no_decision_time(coordinator_client):
    assert _booking(coordinator_client, Bookings.PENDING_SEMINAR_ROOM)["decided_at"] is None


@pytest.mark.story("13.2.2", ac=1)
def test_a_decided_booking_carries_its_decision_time(coordinator_client):
    booking = _booking(coordinator_client, Bookings.APPROVED_GRAND_HALL)

    assert datetime.fromisoformat(booking["decided_at"]) == datetime(
        2026, 9, 4, 10, 0, tzinfo=SINGAPORE
    )


@pytest.mark.story("13.2.2", ac=1)
def test_rejecting_a_booking_sets_its_decision_time(venue_staff_client):
    before = datetime.now(timezone.utc)
    response = venue_staff_client.post(
        f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/reject",
        json={"decision_reason": "The seminar room is being refitted."},
    )
    assert response.status_code == 200

    decided_at = _booking(venue_staff_client, Bookings.PENDING_SEMINAR_ROOM)["decided_at"]

    assert before <= datetime.fromisoformat(decided_at) <= datetime.now(timezone.utc)
