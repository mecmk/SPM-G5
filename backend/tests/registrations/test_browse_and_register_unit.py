"""Story 18.1 - browse and register for an event. UNIT tests: the registration rules alone.

Level: unit. Each test calls one pure function in ``app/registrations/service.py`` - no database,
no HTTP, no fixture - so the whole file runs in milliseconds without PostgreSQL. The integration
tests beside it (``test_browse_and_register_integration.py``) prove the service applies these rules
to real rows through the API, and ``tests/e2e/attendee-registration.spec.ts`` proves the flows an
attendee clicks through. No case is proven at more than one level.

AC2 Capacity is the event's expected attendance (2.1 AC17). The registration that takes the last
    place is accepted; the next is refused. A registration before the closing time is accepted;
    one at or after it is refused. When an opening time is set, a registration before it is
    refused and one at it is accepted. An event with no closing time recorded closes when it
    starts.
AC3 Full, closed and not-yet-open events stay listed until they start, with Register disabled.
    (Here: which state an event is listed in, and which wins when several apply.)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.registrations.service import (
    RegistrationState,
    closing_time,
    places_left,
    registration_state,
    window_state,
)

NOW = datetime(2030, 1, 15, 9, 0, tzinfo=UTC)
TICK = timedelta(microseconds=1)  # the smallest step a timestamptz stores
STARTS_AT = NOW + timedelta(days=10)


# --- AC2: places left -------------------------------------------------------------------------
@pytest.mark.story("18.1", ac=2)
def test_places_left_is_capacity_less_the_active_registrations():
    assert places_left(capacity=10, registered=3) == 7


@pytest.mark.story("18.1", ac=2)
def test_one_place_is_left_before_the_last_registration():
    assert places_left(capacity=10, registered=9) == 1


@pytest.mark.story("18.1", ac=2)
def test_no_place_is_left_once_capacity_is_reached():
    assert places_left(capacity=10, registered=10) == 0


@pytest.mark.story("18.1", ac=2)
def test_places_left_never_goes_below_zero_when_attendance_is_lowered_later():
    """A change request (19.2) can lower the expected attendance below the registrations already
    made; the event is then full, not owed a negative number of places."""
    assert places_left(capacity=10, registered=12) == 0


# --- AC2: when registration closes ------------------------------------------------------------
@pytest.mark.story("18.1", ac=2)
def test_registration_closes_at_the_recorded_closing_time():
    closes_at = STARTS_AT - timedelta(days=2)
    assert closing_time(closes_at=closes_at, starts_at=STARTS_AT) == closes_at


@pytest.mark.story("18.1", ac=2)
def test_registration_with_no_closing_time_closes_when_the_event_starts():
    assert closing_time(closes_at=None, starts_at=STARTS_AT) == STARTS_AT


# --- AC2: the registration window, by time alone ----------------------------------------------
@pytest.mark.story("18.1", ac=2)
def test_window_is_open_one_tick_before_it_closes():
    assert window_state(now=NOW, opens_at=None, closes_at=NOW + TICK) is RegistrationState.OPEN


@pytest.mark.story("18.1", ac=2)
def test_window_is_closed_at_the_closing_moment():
    assert window_state(now=NOW, opens_at=None, closes_at=NOW) is RegistrationState.CLOSED


@pytest.mark.story("18.1", ac=2)
def test_window_is_closed_after_the_closing_moment():
    assert window_state(now=NOW, opens_at=None, closes_at=NOW - TICK) is RegistrationState.CLOSED


@pytest.mark.story("18.1", ac=2)
def test_window_with_no_opening_time_is_open_straight_away():
    assert window_state(now=NOW, opens_at=None, closes_at=STARTS_AT) is RegistrationState.OPEN


@pytest.mark.story("18.1", ac=2)
def test_window_is_open_at_the_opening_moment():
    assert window_state(now=NOW, opens_at=NOW, closes_at=STARTS_AT) is RegistrationState.OPEN


@pytest.mark.story("18.1", ac=2)
def test_window_is_not_yet_open_one_tick_before_the_opening_moment():
    state = window_state(now=NOW, opens_at=NOW + TICK, closes_at=STARTS_AT)
    assert state is RegistrationState.NOT_YET_OPEN


# --- AC3: the state an event is listed in, and which wins -------------------------------------
@pytest.mark.story("18.1", ac=3)
def test_an_open_event_with_a_place_left_is_open():
    state = registration_state(
        now=NOW, opens_at=None, closes_at=STARTS_AT, places_left=1, is_registered=False
    )
    assert state is RegistrationState.OPEN


@pytest.mark.story("18.1", ac=3)
def test_an_open_event_with_no_place_left_is_full():
    state = registration_state(
        now=NOW, opens_at=None, closes_at=STARTS_AT, places_left=0, is_registered=False
    )
    assert state is RegistrationState.FULL


@pytest.mark.story("18.1", ac=3)
def test_a_closed_event_is_closed_even_with_places_left():
    state = registration_state(
        now=NOW, opens_at=None, closes_at=NOW, places_left=5, is_registered=False
    )
    assert state is RegistrationState.CLOSED


@pytest.mark.story("18.1", ac=3)
def test_a_closed_event_with_no_place_left_shows_as_closed_not_full():
    """Closed is final; Full could change if a place were freed (18.2), so Closed wins."""
    state = registration_state(
        now=NOW, opens_at=None, closes_at=NOW, places_left=0, is_registered=False
    )
    assert state is RegistrationState.CLOSED


@pytest.mark.story("18.1", ac=3)
def test_an_event_not_yet_open_shows_as_not_yet_open():
    state = registration_state(
        now=NOW, opens_at=NOW + TICK, closes_at=STARTS_AT, places_left=5, is_registered=False
    )
    assert state is RegistrationState.NOT_YET_OPEN


@pytest.mark.story("18.1", ac=3)
def test_an_event_the_attendee_registered_for_shows_as_registered_even_when_full_and_closed():
    """The attendee's own place matters more to them than whether anyone else can still join."""
    state = registration_state(
        now=NOW, opens_at=None, closes_at=NOW, places_left=0, is_registered=True
    )
    assert state is RegistrationState.REGISTERED
