"""Story 9.1: venue availability calendar.

AC1 a calendar view shows availability for one venue across a selectable range of dates.
AC2 each period is shown as available or unavailable - approved bookings and unavailability
    periods both count, applying the same half-open overlap logic as the database's own
    ex_venue_bookings_no_double_booking exclusion constraint (a period that only touches the
    range's edge is not a conflict).
AC3 the view is restricted to authorised internal users. VENUE_CALENDAR_READ is granted to
    Event Coordinator, Venue Staff and Technical Support Staff; Event Organiser and Attendee
    do not hold it (see VENUES_READ's own team decision, 20 Sep 2026, for the same pattern).
"""

from __future__ import annotations

import pytest

from tests.support.seed import Venues


def _calendar(client, venue_id, starts_at: str, ends_at: str):
    return client.get(
        f"/venues/{venue_id}/calendar", params={"starts_at": starts_at, "ends_at": ends_at}
    )


@pytest.mark.story("9.1", ac=1)
@pytest.mark.story("9.1", ac=2)
def test_calendar_shows_an_approved_booking_as_unavailable(coordinator_client):
    response = _calendar(
        coordinator_client,
        Venues.GRAND_HALL,
        "2026-11-24T00:00:00+08:00",
        "2026-11-26T00:00:00+08:00",
    )
    assert response.status_code == 200, response.text
    windows = response.json()
    assert len(windows) == 1
    assert windows[0]["reason"] == "BOOKED"
    assert windows[0]["label"] == "Nimbus Developer Conference"
    # held_from/held_until = starts_at/ends_at adjusted by 60 min setup and teardown.
    assert windows[0]["starts_at"].startswith("2026-11-25T00:00:00")  # 08:00+08 = 00:00Z
    assert windows[0]["ends_at"].startswith("2026-11-25T11:00:00")  # 19:00+08 = 11:00Z


@pytest.mark.story("9.1", ac=1)
@pytest.mark.story("9.1", ac=2)
def test_calendar_shows_an_unavailability_period_as_unavailable(coordinator_client):
    response = _calendar(
        coordinator_client,
        Venues.SEMINAR_ROOM,
        "2026-11-01T00:00:00+08:00",
        "2026-11-05T00:00:00+08:00",
    )
    assert response.status_code == 200, response.text
    windows = response.json()
    assert len(windows) == 1
    assert windows[0]["reason"] == "MAINTENANCE"
    assert windows[0]["label"] == "Annual air-con servicing"


@pytest.mark.story("9.1", ac=1)
def test_calendar_is_empty_when_nothing_overlaps(coordinator_client):
    response = _calendar(
        coordinator_client,
        Venues.BOARDROOM,
        "2026-11-01T00:00:00+08:00",
        "2026-12-01T00:00:00+08:00",
    )
    assert response.status_code == 200, response.text
    assert response.json() == []


@pytest.mark.story("9.1", ac=2)
def test_calendar_ignores_a_pending_booking(coordinator_client):
    """Only APPROVED bookings occupy the venue; the PENDING Seminar Room booking on this exact
    window must not appear."""
    response = _calendar(
        coordinator_client,
        Venues.SEMINAR_ROOM,
        "2026-11-25T12:00:00+08:00",
        "2026-11-25T19:00:00+08:00",
    )
    assert response.status_code == 200, response.text
    assert response.json() == []


@pytest.mark.story("9.1", ac=2)
def test_calendar_excludes_a_booking_that_only_touches_the_range_edge(coordinator_client):
    """Mirrors the database's own half-open [) exclusion: touching is not overlapping."""
    response = _calendar(
        coordinator_client,
        Venues.GRAND_HALL,
        "2026-11-24T00:00:00+08:00",
        "2026-11-25T08:00:00+08:00",  # ends exactly when the booking's held_from starts
    )
    assert response.status_code == 200, response.text
    assert response.json() == []


@pytest.mark.story("9.1", ac=2)
def test_calendar_excludes_an_unavailability_period_that_only_touches_the_range_edge(
    coordinator_client,
):
    """Same half-open exclusivity applied to venue_unavailability_periods, which has no DB-level
    constraint of its own - this is the only thing proving the two sources behave alike."""
    response = _calendar(
        coordinator_client,
        Venues.SEMINAR_ROOM,
        "2026-11-01T00:00:00+08:00",
        "2026-11-02T00:00:00+08:00",  # ends exactly when the period starts
    )
    assert response.status_code == 200, response.text
    assert response.json() == []


@pytest.mark.story("9.1", ac=1)
def test_calendar_rejects_an_inverted_range(coordinator_client):
    response = _calendar(
        coordinator_client,
        Venues.GRAND_HALL,
        "2026-11-26T00:00:00+08:00",
        "2026-11-24T00:00:00+08:00",
    )
    assert response.status_code == 422


@pytest.mark.story("9.1", ac=1)
def test_calendar_for_a_missing_venue_is_404(coordinator_client):
    response = _calendar(
        coordinator_client,
        "00000000-0000-0000-0000-000000000000",
        "2026-11-24T00:00:00+08:00",
        "2026-11-26T00:00:00+08:00",
    )
    assert response.status_code == 404


@pytest.mark.story("9.1", ac=3)
@pytest.mark.parametrize(
    ("client_fixture", "expected_status"),
    [
        ("coordinator_client", 200),
        ("venue_staff_client", 200),
        ("tech_client", 200),
        ("organiser_client", 403),
        ("attendee_client", 403),
    ],
)
def test_calendar_is_restricted_to_internal_roles(request, client_fixture, expected_status):
    client = request.getfixturevalue(client_fixture)
    response = _calendar(
        client, Venues.GRAND_HALL, "2026-11-24T00:00:00+08:00", "2026-11-26T00:00:00+08:00"
    )
    assert response.status_code == expected_status, response.text


@pytest.mark.story("9.1", ac=3)
def test_calendar_requires_a_session(client):
    response = _calendar(
        client, Venues.GRAND_HALL, "2026-11-24T00:00:00+08:00", "2026-11-26T00:00:00+08:00"
    )
    assert response.status_code == 401
