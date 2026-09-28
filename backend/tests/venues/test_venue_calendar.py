"""Story 9.1: venue availability calendar (the 14-criterion version; AC6, the Venue Schedule page
for Venue Staff, is a later step and is not covered here).

AC1  a calendar shows availability for one venue across a range of dates (the page asks for one
     month at a time).
AC2  confirmed bookings are unavailable for their full held period (setup and teardown included);
     a pending request soft-locks its venue and is returned as a HELD window, distinct from a
     BOOKED one. Overlap is the database's own half-open rule
     (ex_venue_bookings_no_double_booking): a period that only touches the range's edge is not
     in it. venue_unavailability_periods has no such constraint but is checked the same way.
AC3  every occupied period carries its event name, for everyone who can view the calendar.
AC4  the API returns the chosen venue's bookings and holds only, to the three internal roles.
AC5  each window also carries the event's own period, so a day's list can show it beside the
     held window (null for a closure).
AC7  several non-clashing events on one day come back as separate windows.
AC8  a booking ending at 12:00 and another starting at 12:00 are separate windows that meet.
AC9  a multi-day booking, setup and teardown included, is one window covering every day.
AC11 a rejected, withdrawn or cancelled booking no longer occupies the calendar.
AC12 a range with nothing in it comes back empty.
AC13 restricted to Event Coordinator, Venue Staff and Technical Support (the calendar's
     VENUE_CALENDAR_READ, see permissions.py); Event Organiser and Attendee are refused.
AC14 a booking approved or rejected while the calendar is open shows its new state on the next
     request: one window, never two.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.bookings import service as booking_service
from app.bookings.models import BookingStatus
from app.events.models import Event
from tests.support.factories import make_booking, make_venue
from tests.support.seed import Events, Users, Venues

SINGAPORE = timezone(timedelta(hours=8))

# Booked and held are the calendar's own values for `reason`; a closure carries its own reason
# (MAINTENANCE and so on), see app/venues/schemas.py.
BOOKED = "BOOKED"
HELD = "HELD"


def _calendar(client, venue_id, starts_at: str, ends_at: str):
    return client.get(
        f"/venues/{venue_id}/calendar", params={"starts_at": starts_at, "ends_at": ends_at}
    )


def _sgt(day: int, hour: int, minute: int = 0) -> datetime:
    """A Singapore-time moment in March 2027, a month no seed row touches."""
    return datetime(2027, 3, day, hour, minute, tzinfo=SINGAPORE)


def _windows(client, venue_id, starts_at: datetime, ends_at: datetime) -> list[dict]:
    response = _calendar(client, venue_id, starts_at.isoformat(), ends_at.isoformat())
    assert response.status_code == 200, response.text
    return response.json()


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _event_name(db: Session, event_id) -> str:
    return db.get(Event, event_id).name


@pytest.mark.story("9.1", ac=1)
@pytest.mark.story("9.1", ac=2)
@pytest.mark.story("9.1", ac=3)
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
    assert windows[0]["reason"] == BOOKED
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


@pytest.mark.story("9.1", ac=2)
@pytest.mark.story("9.1", ac=3)
def test_calendar_shows_a_pending_booking_as_held(coordinator_client):
    """The PENDING Seminar Room request holds the venue: 13:00-18:00 plus 30 min setup and
    15 min teardown, so held 12:30-18:15."""
    response = _calendar(
        coordinator_client,
        Venues.SEMINAR_ROOM,
        "2026-11-25T12:00:00+08:00",
        "2026-11-25T19:00:00+08:00",
    )
    assert response.status_code == 200, response.text
    windows = response.json()
    assert len(windows) == 1
    assert windows[0]["reason"] == HELD
    assert windows[0]["label"] == "Nimbus Developer Conference"
    assert _instant(windows[0]["starts_at"]) == datetime(2026, 11, 25, 12, 30, tzinfo=SINGAPORE)
    assert _instant(windows[0]["ends_at"]) == datetime(2026, 11, 25, 18, 15, tzinfo=SINGAPORE)


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
@pytest.mark.parametrize(
    ("starts_at", "ends_at"),
    [
        ("2026-11-25T08:00:00+08:00", "2026-11-25T12:30:00+08:00"),  # ends at held_from
        ("2026-11-25T18:15:00+08:00", "2026-11-25T23:00:00+08:00"),  # starts at held_until
    ],
)
def test_calendar_excludes_a_hold_that_only_touches_the_range_edge(
    coordinator_client, starts_at, ends_at
):
    response = _calendar(coordinator_client, Venues.SEMINAR_ROOM, starts_at, ends_at)
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


@pytest.mark.story("9.1", ac=3)
def test_calendar_labels_held_and_booked_windows_with_their_event_names(
    coordinator_client, db: Session
):
    venue = make_venue(db)
    make_booking(
        db,
        venue_id=venue.id,
        starts_at=_sgt(10, 9),
        ends_at=_sgt(10, 11),
        status=BookingStatus.APPROVED,
        event_id=Events.APPROVED,
    )
    make_booking(
        db,
        venue_id=venue.id,
        starts_at=_sgt(10, 14),
        ends_at=_sgt(10, 16),
        status=BookingStatus.PENDING,
        event_id=Events.PLANNING,
    )

    windows = _windows(coordinator_client, venue.id, _sgt(10, 0), _sgt(11, 0))

    assert [(w["reason"], w["label"]) for w in windows] == [
        (BOOKED, _event_name(db, Events.APPROVED)),
        (HELD, _event_name(db, Events.PLANNING)),
    ]


@pytest.mark.story("9.1", ac=4)
def test_calendar_returns_only_the_chosen_venues_bookings(coordinator_client, db: Session):
    venue = make_venue(db)
    other_venue = make_venue(db)
    make_booking(
        db,
        venue_id=venue.id,
        starts_at=_sgt(10, 9),
        ends_at=_sgt(10, 11),
        status=BookingStatus.APPROVED,
        event_id=Events.APPROVED,
    )
    make_booking(
        db,
        venue_id=other_venue.id,
        starts_at=_sgt(10, 9),
        ends_at=_sgt(10, 11),
        status=BookingStatus.APPROVED,
        event_id=Events.PLANNING,
    )

    windows = _windows(coordinator_client, venue.id, _sgt(10, 0), _sgt(11, 0))

    assert [w["label"] for w in windows] == [_event_name(db, Events.APPROVED)]


@pytest.mark.story("9.1", ac=5)
def test_calendar_window_carries_the_events_own_period_and_none_for_a_closure(
    coordinator_client,
):
    booking = _calendar(
        coordinator_client,
        Venues.GRAND_HALL,
        "2026-11-24T00:00:00+08:00",
        "2026-11-26T00:00:00+08:00",
    ).json()[0]
    closure = _calendar(
        coordinator_client,
        Venues.SEMINAR_ROOM,
        "2026-11-01T00:00:00+08:00",
        "2026-11-05T00:00:00+08:00",
    ).json()[0]

    # The event itself runs 09:00-18:00; the window also covers 60 min setup and teardown.
    assert _instant(booking["event_starts_at"]) == datetime(2026, 11, 25, 9, 0, tzinfo=SINGAPORE)
    assert _instant(booking["event_ends_at"]) == datetime(2026, 11, 25, 18, 0, tzinfo=SINGAPORE)
    assert _instant(booking["starts_at"]) == datetime(2026, 11, 25, 8, 0, tzinfo=SINGAPORE)
    assert closure["event_starts_at"] is None
    assert closure["event_ends_at"] is None


@pytest.mark.story("9.1", ac=7)
def test_calendar_lists_several_non_clashing_events_on_one_day_separately(
    coordinator_client, db: Session
):
    venue = make_venue(db)
    make_booking(
        db,
        venue_id=venue.id,
        starts_at=_sgt(10, 14),
        ends_at=_sgt(10, 16),
        status=BookingStatus.PENDING,
    )
    make_booking(
        db,
        venue_id=venue.id,
        starts_at=_sgt(10, 9),
        ends_at=_sgt(10, 11),
        status=BookingStatus.APPROVED,
    )

    windows = _windows(coordinator_client, venue.id, _sgt(10, 0), _sgt(11, 0))

    assert [(w["reason"], _instant(w["starts_at"])) for w in windows] == [
        (BOOKED, _sgt(10, 9)),
        (HELD, _sgt(10, 14)),
    ]


@pytest.mark.story("9.1", ac=8)
def test_calendar_shows_back_to_back_bookings_as_adjacent_not_overlapping(
    coordinator_client, db: Session
):
    venue = make_venue(db)
    make_booking(
        db,
        venue_id=venue.id,
        starts_at=_sgt(10, 10),
        ends_at=_sgt(10, 12),
        status=BookingStatus.APPROVED,
    )
    make_booking(
        db,
        venue_id=venue.id,
        starts_at=_sgt(10, 12),
        ends_at=_sgt(10, 14),
        status=BookingStatus.APPROVED,
    )

    first, second = _windows(coordinator_client, venue.id, _sgt(10, 0), _sgt(11, 0))

    assert _instant(first["ends_at"]) == _instant(second["starts_at"]) == _sgt(10, 12)


@pytest.mark.story("9.1", ac=9)
def test_calendar_returns_a_multi_day_booking_as_one_window_covering_every_day(
    coordinator_client, db: Session
):
    """The event runs 10 Mar 20:00 to 12 Mar 10:00, with a whole day of setup and of teardown, so
    the held window runs 9 Mar 20:00 to 13 Mar 10:00. A range starting mid-way still finds it."""
    venue = make_venue(db)
    make_booking(
        db,
        venue_id=venue.id,
        starts_at=_sgt(10, 20),
        ends_at=_sgt(12, 10),
        setup_minutes=24 * 60,
        teardown_minutes=24 * 60,
        status=BookingStatus.APPROVED,
    )

    for range_start, range_end in [(_sgt(9, 0), _sgt(14, 0)), (_sgt(11, 0), _sgt(12, 0))]:
        (window,) = _windows(coordinator_client, venue.id, range_start, range_end)
        assert _instant(window["starts_at"]) == _sgt(9, 20)
        assert _instant(window["ends_at"]) == _sgt(13, 10)
        assert _instant(window["event_starts_at"]) == _sgt(10, 20)
        assert _instant(window["event_ends_at"]) == _sgt(12, 10)


@pytest.mark.story("9.1", ac=11)
@pytest.mark.parametrize(
    "status",
    [BookingStatus.REJECTED, BookingStatus.WITHDRAWN, BookingStatus.CANCELLED],
)
def test_calendar_ignores_a_booking_that_no_longer_holds_the_venue(
    coordinator_client, db: Session, status
):
    venue = make_venue(db)
    make_booking(
        db,
        venue_id=venue.id,
        starts_at=_sgt(10, 9),
        ends_at=_sgt(10, 11),
        status=status,
    )

    assert _windows(coordinator_client, venue.id, _sgt(10, 0), _sgt(11, 0)) == []


@pytest.mark.story("9.1", ac=12)
def test_calendar_is_empty_when_nothing_overlaps(coordinator_client):
    response = _calendar(
        coordinator_client,
        Venues.BOARDROOM,
        "2026-11-01T00:00:00+08:00",
        "2026-12-01T00:00:00+08:00",
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


@pytest.mark.story("9.1", ac=13)
@pytest.mark.story("9.1", ac=4)
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


@pytest.mark.story("9.1", ac=13)
def test_calendar_requires_a_session(client):
    response = _calendar(
        client, Venues.GRAND_HALL, "2026-11-24T00:00:00+08:00", "2026-11-26T00:00:00+08:00"
    )
    assert response.status_code == 401


@pytest.mark.story("9.1", ac=14)
def test_approving_a_pending_booking_turns_its_held_window_into_one_booked_window(
    coordinator_client, db: Session
):
    venue = make_venue(db)
    booking = make_booking(
        db,
        venue_id=venue.id,
        starts_at=_sgt(10, 9),
        ends_at=_sgt(10, 11),
        status=BookingStatus.PENDING,
    )
    before = _windows(coordinator_client, venue.id, _sgt(10, 0), _sgt(11, 0))

    booking_service.approve_booking(db, booking, actor_id=Users.VENUE_STAFF.id)
    after = _windows(coordinator_client, venue.id, _sgt(10, 0), _sgt(11, 0))

    assert [w["reason"] for w in before] == [HELD]
    assert [w["reason"] for w in after] == [BOOKED]
    assert after[0]["starts_at"] == before[0]["starts_at"]


@pytest.mark.story("9.1", ac=14)
def test_rejecting_a_pending_booking_removes_its_window(coordinator_client, db: Session):
    venue = make_venue(db)
    booking = make_booking(
        db,
        venue_id=venue.id,
        starts_at=_sgt(10, 9),
        ends_at=_sgt(10, 11),
        status=BookingStatus.PENDING,
    )
    assert len(_windows(coordinator_client, venue.id, _sgt(10, 0), _sgt(11, 0))) == 1

    booking_service.reject_booking(
        db, booking, actor_id=Users.VENUE_STAFF.id, decision_reason="Double booked in error."
    )

    assert _windows(coordinator_client, venue.id, _sgt(10, 0), _sgt(11, 0)) == []
