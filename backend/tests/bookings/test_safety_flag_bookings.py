"""Fix f21.2.1 (story 21.2) - when each of an event's venue bookings was requested.

The event page highlights the bookings a safety review flagged, not the whole Venue booking
section. A finding names the bookings it is about (21.3 AC7), and naming one releases it; a finding
that names none is about the bookings the review saw. So the page compares when each booking was
requested with when the review was made, and both booking lists it reads return that time.

AC23 A finding about venue bookings that names none flags the event's pending and approved
     bookings requested before the review - and so not one requested after it (AC24) - which the
     page can tell only from when each was requested.

AC22 and AC24-AC27 are how the page shows the flags: tests/e2e/safety-flags.spec.ts.

Permission and conflict cases do not apply: both endpoints keep their guards, only read, and gain
one field. Events.STUDIO_SHOWCASE's two bookings straddle its review of 6 Oct 2026, 09:00 (+08).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from tests.support.seed import Bookings, Events

_RELEASED = str(Bookings.SAFETY_RELEASED_STUDIO_SHOWCASE_SEMINAR_ROOM)
_REQUESTED_AFTER = str(Bookings.PENDING_STUDIO_SHOWCASE_FOYER)


def _requested_at(body: list[dict]) -> dict[str, datetime]:
    return {entry["id"]: datetime.fromisoformat(entry["created_at"]) for entry in body}


@pytest.mark.story("21.2", ac=23)
def test_the_coordinators_list_says_when_each_booking_was_requested(coordinator_client):
    response = coordinator_client.get(f"/bookings/for-event/{Events.STUDIO_SHOWCASE}")

    assert response.status_code == 200
    requested_at = _requested_at(response.json())
    assert requested_at[_RELEASED] == datetime.fromisoformat("2026-10-02T12:00:00+08:00")
    assert requested_at[_REQUESTED_AFTER] == datetime.fromisoformat("2026-10-08T10:00:00+08:00")


@pytest.mark.story("21.2", ac=23)
def test_the_organisers_list_says_when_each_booking_was_requested(organiser_client):
    response = organiser_client.get(f"/bookings/for-my-event/{Events.STUDIO_SHOWCASE}")

    assert response.status_code == 200
    requested_at = _requested_at(response.json())
    assert requested_at[_RELEASED] == datetime.fromisoformat("2026-10-02T12:00:00+08:00")
    assert requested_at[_REQUESTED_AFTER] == datetime.fromisoformat("2026-10-08T10:00:00+08:00")
