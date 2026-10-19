"""Story 18.3 - the registration list for my event. INTEGRATION tests: the API on PostgreSQL.

Level: integration. Each test calls ``GET /events/{event_id}/registrations`` - or, in the picker
section at the end, ``GET /registrations/managed`` - through a signed-in ``*_client`` fixture
against the real schema in the rolled-back test transaction. Whether an event is full is
unit-tested in ``test_registration_list_unit.py``; the organiser's and coordinator's view of the
list is e2e-tested in ``tests/e2e/registration-list.spec.ts``.

AC1 Shows attendee name, email, registration time and status, plus the active count against
    capacity.
AC2 The list and count are worked out on the server from active registrations.
AC3 No registrations shows an empty message. When the count reaches capacity, the list shows
    "Full".
AC4 Withdrawn registrations are marked as such and not counted.
AC5 Only the organiser and assigned coordinator can view the list; anyone else gets "not found".
AC6 The API returns "not found" to users with no relationship to the event.
AC7 The count always matches the list as loaded.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.auth.models import User
from app.events.models import Event, EventStatus
from app.registrations import service
from app.registrations.models import EventRegistration, RegistrationStatus
from tests.support.factories import make_event, make_user
from tests.support.seed import Users

REGISTERED_AT = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
NOT_FOUND = service.REGISTRATION_LIST_NOT_FOUND_MESSAGE
ROW_KEYS = {"id", "attendee_name", "attendee_email", "registered_at", "status", "withdrawn_at"}


def _path(event_id: uuid.UUID) -> str:
    return f"/events/{event_id}/registrations"


def _my_event(db: Session, *, capacity: int = 10) -> Event:
    """A Confirmed event of Users.ORGANISER's, assigned to Users.COORDINATOR."""
    return make_event(
        db,
        status=EventStatus.CONFIRMED,
        registration_required=True,
        is_public=True,
        expected_attendance=capacity,
        assigned_coordinator_id=Users.COORDINATOR.id,
    )


def _register(
    db: Session,
    event: Event,
    *,
    status: str = RegistrationStatus.REGISTERED,
    minutes: int = 0,
    attendee: User | None = None,
) -> EventRegistration:
    attendee = attendee or make_user(db, role="ATTENDEE")
    registration = EventRegistration(
        event_id=event.id,
        attendee_id=attendee.id,
        status=status,
        registered_at=REGISTERED_AT + timedelta(minutes=minutes),
        withdrawn_at=REGISTERED_AT + timedelta(days=1)
        if status == RegistrationStatus.WITHDRAWN
        else None,
    )
    db.add(registration)
    db.flush()
    return registration


# --- AC1/AC2: what the list shows -------------------------------------------------------------
@pytest.mark.story("18.3", ac=1)
def test_the_organiser_sees_each_attendee_with_the_count_against_capacity(
    organiser_client, db: Session
):
    event = _my_event(db, capacity=5)
    attendee = make_user(
        db, role="ATTENDEE", full_name="Rita Registrant", email="rita@test.example"
    )
    registration = _register(db, event, attendee=attendee)

    response = organiser_client.get(_path(event.id))

    assert response.status_code == 200
    body = response.json()
    assert body["active_count"] == 1
    assert body["capacity"] == 5
    assert body["is_full"] is False
    assert body["total"] == 1
    [row] = body["items"]
    assert set(row) == ROW_KEYS
    assert row["id"] == str(registration.id)
    assert row["attendee_name"] == "Rita Registrant"
    assert row["attendee_email"] == "rita@test.example"
    assert datetime.fromisoformat(row["registered_at"]) == REGISTERED_AT
    assert row["status"] == "REGISTERED"
    assert row["withdrawn_at"] is None


@pytest.mark.story("18.3", ac=1)
def test_the_assigned_coordinator_sees_the_list_too(coordinator_client, db: Session):
    event = _my_event(db)
    _register(db, event)

    response = coordinator_client.get(_path(event.id))

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


@pytest.mark.story("18.3", ac=2)
def test_the_list_is_in_registration_order_and_holds_only_this_events_rows(
    organiser_client, db: Session
):
    event = _my_event(db)
    other = _my_event(db)
    later = _register(db, event, minutes=30)
    earlier = _register(db, event, minutes=5)
    _register(db, other)

    body = organiser_client.get(_path(event.id)).json()

    assert [row["id"] for row in body["items"]] == [str(earlier.id), str(later.id)]
    assert body["active_count"] == 2


# --- AC3: empty and full ----------------------------------------------------------------------
@pytest.mark.story("18.3", ac=3)
def test_an_event_with_no_registrations_gives_an_empty_list(organiser_client, db: Session):
    event = _my_event(db)

    body = organiser_client.get(_path(event.id)).json()

    assert body["items"] == []
    assert body["active_count"] == 0
    assert body["is_full"] is False


@pytest.mark.story("18.3", ac=3)
def test_one_place_short_of_capacity_is_not_full(organiser_client, db: Session):
    event = _my_event(db, capacity=2)
    _register(db, event)

    assert organiser_client.get(_path(event.id)).json()["is_full"] is False


@pytest.mark.story("18.3", ac=3)
def test_reaching_capacity_is_full(organiser_client, db: Session):
    event = _my_event(db, capacity=2)
    _register(db, event)
    _register(db, event)

    body = organiser_client.get(_path(event.id)).json()

    assert body["active_count"] == 2
    assert body["is_full"] is True


@pytest.mark.story("18.3", ac=3)
def test_more_registrations_than_a_lowered_capacity_is_still_full(organiser_client, db: Session):
    # A change request (19.2) can lower the expected attendance below the places already taken.
    event = _my_event(db, capacity=3)
    for _ in range(3):
        _register(db, event)
    event.expected_attendance = 2
    db.flush()

    body = organiser_client.get(_path(event.id)).json()

    assert body["active_count"] == 3
    assert body["capacity"] == 2
    assert body["is_full"] is True


# --- AC4: withdrawn registrations -------------------------------------------------------------
@pytest.mark.story("18.3", ac=4)
def test_a_withdrawn_registration_is_listed_with_when_it_was_withdrawn_and_not_counted(
    organiser_client, db: Session
):
    event = _my_event(db, capacity=1)
    registration = _register(db, event, status=RegistrationStatus.WITHDRAWN)

    body = organiser_client.get(_path(event.id)).json()

    [row] = body["items"]
    assert row["status"] == "WITHDRAWN"
    assert datetime.fromisoformat(row["withdrawn_at"]) == registration.withdrawn_at
    assert body["active_count"] == 0
    assert body["is_full"] is False


@pytest.mark.story("18.3", ac=4)
def test_a_registration_cancelled_with_its_event_reads_event_cancelled_and_is_not_counted(
    organiser_client, db: Session
):
    event = _my_event(db, capacity=1)
    _register(db, event, status=RegistrationStatus.CANCELLED)

    body = organiser_client.get(_path(event.id)).json()

    [row] = body["items"]
    assert row["status"] == "EVENT_CANCELLED"
    assert body["active_count"] == 0
    assert body["is_full"] is False


@pytest.mark.story("18.3", ac=4)
def test_a_cancelled_events_still_active_registration_reads_event_cancelled_and_is_not_counted(
    organiser_client, db: Session
):
    # As 18.2's registration_standing tells the attendee, so the two pages agree.
    event = _my_event(db, capacity=1)
    _register(db, event)
    event.status = EventStatus.CANCELLED
    db.flush()

    body = organiser_client.get(_path(event.id)).json()

    [row] = body["items"]
    assert row["status"] == "EVENT_CANCELLED"
    assert body["active_count"] == 0
    assert body["is_full"] is False


@pytest.mark.story("18.3", ac=4)
def test_an_attendee_who_withdrew_and_registered_again_is_listed_twice_and_counted_once(
    organiser_client, db: Session
):
    event = _my_event(db)
    attendee = make_user(db, role="ATTENDEE")
    _register(db, event, attendee=attendee, status=RegistrationStatus.WITHDRAWN)
    _register(db, event, attendee=attendee, minutes=60)

    body = organiser_client.get(_path(event.id)).json()

    assert [row["status"] for row in body["items"]] == ["WITHDRAWN", "REGISTERED"]
    assert body["active_count"] == 1


# --- AC5/AC6: who may see it ------------------------------------------------------------------
@pytest.mark.story("18.3", ac=5)
@pytest.mark.parametrize(
    "user",
    [
        Users.ORGANISER_2,
        Users.COORDINATOR_2,
        Users.LEAD,
        Users.VENUE_STAFF,
        Users.TECH_SUPPORT,
        Users.SAFETY_OFFICER,
        Users.ATTENDEE,
    ],
    ids=lambda user: user.role + ":" + user.email,
)
def test_anyone_but_the_organiser_and_assigned_coordinator_is_told_not_found(
    login_as, db: Session, user
):
    event = _my_event(db)
    _register(db, event, attendee=db.get(User, Users.ATTENDEE.id))

    response = login_as(user).get(_path(event.id))

    assert response.status_code == 404
    assert response.json()["detail"] == NOT_FOUND


@pytest.mark.story("18.3", ac=6)
def test_an_unknown_event_gets_the_same_not_found(organiser_client):
    response = organiser_client.get(_path(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["detail"] == NOT_FOUND


@pytest.mark.story("18.3", ac=6)
def test_the_organisers_own_draft_gets_the_same_not_found(organiser_client, db: Session):
    # A draft takes no registrations yet, and may not have the expected attendance to count against.
    draft = make_event(
        db,
        status=EventStatus.DRAFT,
        registration_required=True,
        expected_attendance=None,
        submitted_at=None,
    )

    response = organiser_client.get(_path(draft.id))

    assert response.status_code == 404
    assert response.json()["detail"] == NOT_FOUND


@pytest.mark.story("18.3", ac=6)
def test_signed_out_users_get_401(client, db: Session):
    event = _my_event(db)

    assert client.get(_path(event.id)).status_code == 401


# --- AC7: the count matches the list ----------------------------------------------------------
@pytest.mark.story("18.3", ac=7)
def test_the_count_is_the_number_of_registered_rows_in_the_list(organiser_client, db: Session):
    event = _my_event(db, capacity=10)
    statuses = [
        RegistrationStatus.REGISTERED,
        RegistrationStatus.WITHDRAWN,
        RegistrationStatus.REGISTERED,
        RegistrationStatus.CANCELLED,
        RegistrationStatus.REGISTERED,
    ]
    for minutes, status in enumerate(statuses):
        _register(db, event, status=status, minutes=minutes)

    body = organiser_client.get(_path(event.id)).json()

    assert len(body["items"]) == len(statuses)
    assert body["active_count"] == sum(row["status"] == "REGISTERED" for row in body["items"]) == 3


@pytest.mark.story("18.3", ac=7)
def test_a_page_of_the_list_carries_the_count_and_total_of_the_whole_list(
    organiser_client, db: Session
):
    event = _my_event(db, capacity=10)
    statuses = [
        RegistrationStatus.REGISTERED,
        RegistrationStatus.WITHDRAWN,
        RegistrationStatus.REGISTERED,
    ]
    rows = [
        _register(db, event, status=status, minutes=minutes)
        for minutes, status in enumerate(statuses)
    ]

    first = organiser_client.get(_path(event.id), params={"limit": 2}).json()
    rest = organiser_client.get(_path(event.id), params={"limit": 2, "offset": 2}).json()

    assert [row["id"] for row in first["items"]] == [str(rows[0].id), str(rows[1].id)]
    assert [row["id"] for row in rest["items"]] == [str(rows[2].id)]
    for page in (first, rest):
        assert page["total"] == 3
        assert page["active_count"] == 2


@pytest.mark.story("18.3", ac=7)
def test_a_page_past_the_end_still_carries_the_count(organiser_client, db: Session):
    event = _my_event(db, capacity=1)
    _register(db, event)

    body = organiser_client.get(_path(event.id), params={"offset": 5}).json()

    assert body["items"] == []
    assert body["total"] == 1
    assert body["active_count"] == 1
    assert body["is_full"] is True


@pytest.mark.story("18.3", ac=2)
@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": service.REGISTRATION_LIST_MAX_LIMIT + 1},
        {"offset": -1},
        {"offset": service.REGISTRATION_LIST_MAX_OFFSET + 1},
    ],
    ids=str,
)
def test_a_page_outside_the_bounds_is_refused(organiser_client, db: Session, params):
    event = _my_event(db)

    assert organiser_client.get(_path(event.id), params=params).status_code == 422


# --- AC5: the report page's picker - the events whose list this user may view ------------------
MANAGED_PATH = "/registrations/managed"


def _managed_ids(api_client) -> list[str]:
    response = api_client.get(MANAGED_PATH)
    assert response.status_code == 200
    return [row["id"] for row in response.json()]


@pytest.mark.story("18.3", ac=5)
def test_the_organiser_picks_from_their_own_events_that_take_registrations(
    organiser_client, db: Session
):
    mine = _my_event(db)
    no_registration = make_event(db, status=EventStatus.CONFIRMED, registration_required=False)
    draft = make_event(db, status=EventStatus.DRAFT, registration_required=True, submitted_at=None)
    someone_elses = make_event(
        db,
        status=EventStatus.CONFIRMED,
        registration_required=True,
        organiser_id=make_user(db, role="EVENT_ORGANISER").id,
    )

    ids = _managed_ids(organiser_client)

    assert str(mine.id) in ids
    assert {str(no_registration.id), str(draft.id), str(someone_elses.id)}.isdisjoint(ids)


@pytest.mark.story("18.3", ac=5)
def test_an_event_that_stopped_taking_registrations_is_still_picked_while_it_holds_some(
    organiser_client, db: Session
):
    # 9.4 sends a Confirmed event back to Planning with its registrations, and a 7.2 correction
    # can then turn Registration required off: who registered must stay readable.
    event = _my_event(db)
    _register(db, event)
    event.status = EventStatus.PLANNING
    event.registration_required = False
    db.flush()

    assert str(event.id) in _managed_ids(organiser_client)
    assert organiser_client.get(_path(event.id)).json()["active_count"] == 1


@pytest.mark.story("18.3", ac=5)
def test_the_assigned_coordinator_picks_from_the_events_assigned_to_them(
    coordinator_client, db: Session
):
    assigned = _my_event(db)
    unassigned = make_event(db, status=EventStatus.CONFIRMED, registration_required=True)

    ids = _managed_ids(coordinator_client)

    assert str(assigned.id) in ids
    assert str(unassigned.id) not in ids


@pytest.mark.story("18.3", ac=5)
def test_the_picker_rows_carry_what_the_page_shows_soonest_first(organiser_client, db: Session):
    later = _my_event(db)
    sooner = make_event(
        db,
        status=EventStatus.CONFIRMED,
        registration_required=True,
        starts_at=datetime(2026, 11, 1, 9, 0, tzinfo=UTC),
        ends_at=datetime(2026, 11, 1, 17, 0, tzinfo=UTC),
    )

    rows = [
        row
        for row in organiser_client.get(MANAGED_PATH).json()
        if row["id"] in {str(later.id), str(sooner.id)}
    ]

    assert [row["id"] for row in rows] == [str(sooner.id), str(later.id)]
    assert set(rows[0]) == {"id", "name", "starts_at", "ends_at"}


@pytest.mark.story("18.3", ac=5)
def test_an_attendee_cannot_open_the_picker(attendee_client):
    assert attendee_client.get(MANAGED_PATH).status_code == 403


@pytest.mark.story("18.3", ac=6)
def test_signed_out_users_cannot_open_the_picker(client):
    assert client.get(MANAGED_PATH).status_code == 401
