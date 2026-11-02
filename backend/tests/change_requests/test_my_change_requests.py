"""Story 19.4 - view my change requests across all my events, as an organiser.

AC1 The "Change requests" page lists every change request the signed-in organiser has raised, on
    any of their events: the event name, what it changes, when it was raised and its status
    (Pending, Approved, Rejected, Withdrawn, Cancelled).
AC2 Pending requests come first, newest first within each status.
AC3 Each row opens that event's page.
AC4 The organiser sees only requests on their own events. Other roles can't open the page: the
    API returns 403.
AC5 With no requests, the page says so and points to My events.

Excluded, with reason:
* AC3, the "not permitted" page (AC4's frontend half) and AC5's message and link are UI
  behaviour, proven in tests/e2e/my-change-requests.spec.ts.
* No conflict cases: the endpoint only reads, so nothing can be double-booked or decided twice.
* No validation cases: the endpoint takes no input.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.auth.models import User
from app.change_requests import service as change_requests_service
from app.events.models import Event, EventStatus
from tests.support.factories import future_datetime, make_change_request, make_event, make_user
from tests.support.seed import Users

MINE_PATH = "/change-requests/mine"


def _planning_event(db: Session, **overrides) -> Event:
    """Olivia's event in Planning, dated safely in the future."""
    starts_at = future_datetime(days=60)
    return make_event(
        db,
        status=overrides.pop("status", EventStatus.PLANNING),
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=8),
        expected_attendance=100,
        assigned_coordinator_id=Users.COORDINATOR.id,
        **overrides,
    )


def _listed_ids(client, requests) -> list[str]:
    """The ids of ``requests`` in the order the endpoint lists them."""
    wanted = {str(request.id) for request in requests}
    return [row["id"] for row in client.get(MINE_PATH).json() if row["id"] in wanted]


# --- AC1: every request I raised, with its event ------------------------------------------------


@pytest.mark.story("19.4", ac=1)
def test_lists_my_request_with_its_event_field_date_and_status(organiser_client, db: Session):
    event = _planning_event(db, name="Harbour Summit")
    request = make_change_request(db, event=event)

    response = organiser_client.get(MINE_PATH)

    assert response.status_code == 200, response.text
    [entry] = [row for row in response.json() if row["id"] == str(request.id)]
    assert entry["event_id"] == str(event.id)
    assert entry["event_name"] == "Harbour Summit"
    assert entry["field"] == "expected_attendance"
    assert datetime.fromisoformat(entry["created_at"]) == request.created_at
    assert entry["status"] == "PENDING"


@pytest.mark.story("19.4", ac=1)
def test_lists_my_requests_of_every_status(organiser_client, db: Session):
    """Every status is listed. The list does not filter on the event's status either: the last row
    is a factory state the app cannot reach (cancelling an event cancels its pending requests, and
    none can be raised on a cancelled event), kept only to show no such filter exists."""
    event = _planning_event(db)
    by_status = {
        status: make_change_request(db, event=event, field=field, status=status)
        for field, status in (
            ("expected_attendance", "APPROVED"),
            ("schedule", "REJECTED"),
            ("equipment", "WITHDRAWN"),
            ("venue_requirements", "CANCELLED"),
        )
    }
    stuck = make_change_request(db, event=_planning_event(db, status=EventStatus.CANCELLED))

    listed = {row["id"]: row["status"] for row in organiser_client.get(MINE_PATH).json()}

    assert {status: listed[str(r.id)] for status, r in by_status.items()} == {
        status: status for status in by_status
    }
    assert listed[str(stuck.id)] == "PENDING"


@pytest.mark.story("19.4", ac=1)
def test_lists_requests_from_all_my_events(organiser_client, db: Session):
    first = make_change_request(db, event=_planning_event(db))
    second = make_change_request(db, event=_planning_event(db))

    assert set(_listed_ids(organiser_client, [first, second])) == {str(first.id), str(second.id)}


# --- AC2: pending first, newest first within each status ---------------------------------------


@pytest.mark.story("19.4", ac=2)
def test_pending_first_then_newest_first(organiser_client, db: Session):
    event = _planning_event(db)
    start = future_datetime(days=-10)
    old_pending = make_change_request(db, event=event, field="schedule", created_at=start)
    old_decided = make_change_request(
        db,
        event=event,
        field="equipment",
        status="REJECTED",
        created_at=start + timedelta(days=1),
    )
    new_decided = make_change_request(
        db,
        event=event,
        field="venue_requirements",
        status="APPROVED",
        created_at=start + timedelta(days=2),
    )
    new_pending = make_change_request(db, event=event, created_at=start + timedelta(days=3))

    listed = _listed_ids(organiser_client, [old_pending, old_decided, new_decided, new_pending])

    assert listed == [
        str(new_pending.id),
        str(old_pending.id),
        str(new_decided.id),
        str(old_decided.id),
    ]


# --- AC4: my events only, organisers only -------------------------------------------------------


@pytest.mark.story("19.4", ac=4)
def test_another_organisers_requests_never_come_back(db: Session):
    """Scoped in the service itself, not only by the route's permission."""
    olivias = make_change_request(db, event=_planning_event(db))
    omars = make_change_request(db, event=_planning_event(db, organiser_id=Users.ORGANISER_2.id))
    omar = db.get(User, Users.ORGANISER_2.id)

    listed = change_requests_service.list_organiser_change_requests(db, viewer=omar)

    assert omars.id in {request.id for request in listed}
    assert olivias.id not in {request.id for request in listed}


@pytest.mark.story("19.4", ac=4)
@pytest.mark.parametrize(
    ("user", "expected_status"),
    [
        (Users.COORDINATOR, 403),
        (Users.LEAD, 403),
        (Users.VENUE_STAFF, 403),
        (Users.TECH_SUPPORT, 403),
        (Users.SAFETY_OFFICER, 403),
        (Users.ATTENDEE, 403),
        (None, 401),
    ],
)
def test_only_organisers_may_list_their_requests(login_as, client, user, expected_status):
    viewer = client if user is None else login_as(user)

    assert viewer.get(MINE_PATH).status_code == expected_status


# --- AC5: nothing raised yet --------------------------------------------------------------------


@pytest.mark.story("19.4", ac=5)
def test_empty_when_i_have_raised_none(client, db: Session):
    newcomer = make_user(db, role="EVENT_ORGANISER")
    client.login(newcomer.email)

    response = client.get(MINE_PATH)

    assert response.status_code == 200
    assert response.json() == []
