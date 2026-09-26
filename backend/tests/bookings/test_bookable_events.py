"""Story 12.1 - the pick-list the booking request form is built from.

``GET /bookings/reference-data`` answers "which events may I raise a booking for?". It is the
same two rules the write endpoint enforces (AC1 approved-or-later, AC4 assigned coordinator),
read instead of written, so the form can only ever offer a choice that ``POST /bookings`` will
accept. ``tests/bookings/test_raise_booking_request.py`` proves the refusals themselves; this
file proves the list agrees with them.

Why this lives in the bookings module rather than the events module: it is a pick-list for one
form, the way ``GET /venues/reference-data`` serves the venue form. Story 5.3 ("fe: list events
assigned to me") owns the general coordinator-facing event list, and this deliberately is not
that - it is filtered to what is bookable and carries only the four fields the form needs.

Excluded, with reason:
* Venue choices - the form reads them from ``GET /venues`` (story 8.1), already tested.
* Pagination / search over the list - not in any 12.x AC, and a coordinator has a handful of
  approved events at a time.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.events.models import EventStatus
from tests.support.factories import make_event, make_user
from tests.support.seed import Events, Users

PICK_LIST_PATH = "/bookings/reference-data"

# The earliest of the seeded events APPROVED and assigned to Users.COORDINATOR, so it is always
# first in the pick-list's soonest-first order.
NIMBUS_NAME = "Nimbus Developer Conference"


def event_ids(response) -> list[str]:
    return [event["id"] for event in response.json()["events"]]


# --- AC1 + AC4 as a read: what the form may offer -------------------------------------------
@pytest.mark.story("12.1", ac=1)
def test_the_pick_list_offers_the_coordinators_approved_events(coordinator_client):
    """Chloe (Users.COORDINATOR) is assigned three approved events, plus a PLANNING and a
    CONFIRMED one (story 6.1's seed data) and a PLANNING one dedicated to the story 13.2.1
    reject e2e test - "approved or later" includes both. The pick-list offers all six, soonest
    first."""
    response = coordinator_client.get(PICK_LIST_PATH)

    assert response.status_code == 200
    assert event_ids(response) == [
        str(Events.APPROVED),
        str(Events.PLANNING),
        str(Events.APPROVED_3),
        str(Events.CONFIRMED),
        str(Events.APPROVED_4),
        str(Events.APPROVED_6),
    ]


@pytest.mark.story("12.1", ac=2)
def test_each_entry_carries_what_the_form_needs_to_show(coordinator_client):
    """The form shows the coordinator which event they are booking for, so the entry needs the
    name and the period and attendance that will be copied onto the request."""
    entry = coordinator_client.get(PICK_LIST_PATH).json()["events"][0]

    assert entry["name"] == NIMBUS_NAME
    assert datetime.fromisoformat(entry["starts_at"]) == datetime(
        2026, 11, 25, 1, 0, tzinfo=timezone.utc
    )
    assert datetime.fromisoformat(entry["ends_at"]) == datetime(
        2026, 11, 25, 10, 0, tzinfo=timezone.utc
    )
    assert entry["expected_attendance"] == 350


@pytest.mark.story("12.1", ac=1)
@pytest.mark.parametrize(
    "event_id",
    [Events.SUBMITTED, Events.UNDER_REVIEW, Events.CLARIFICATION_REQUESTED, Events.SUBMITTED_2],
    ids=["submitted", "under review", "clarification requested", "submitted 2"],
)
def test_the_coordinators_undecided_events_are_not_offered(coordinator_client, event_id):
    """All four are assigned to this coordinator, so only the status keeps them out - this is
    AC1 ("only from an approved event") seen from the form's side."""
    assert str(event_id) not in event_ids(coordinator_client.get(PICK_LIST_PATH))


@pytest.mark.story("12.1", ac=1)
@pytest.mark.parametrize("status", [EventStatus.PLANNING, EventStatus.CONFIRMED])
def test_an_event_past_approval_is_still_offered(coordinator_client, db: Session, status):
    event = make_event(db, status=status, assigned_coordinator_id=Users.COORDINATOR.id)

    assert str(event.id) in event_ids(coordinator_client.get(PICK_LIST_PATH))


@pytest.mark.story("12.1", ac=1)
@pytest.mark.parametrize(
    "status",
    [
        EventStatus.DRAFT,
        EventStatus.REJECTED,
        EventStatus.CANCELLED,
        EventStatus.COMPLETED,
    ],
)
def test_an_event_that_cannot_raise_a_booking_is_not_offered(
    coordinator_client, db: Session, status
):
    event = make_event(db, status=status, assigned_coordinator_id=Users.COORDINATOR.id)

    assert str(event.id) not in event_ids(coordinator_client.get(PICK_LIST_PATH))


@pytest.mark.story("12.1", ac=4)
def test_another_coordinators_approved_event_is_not_offered(coordinator_client, db: Session):
    event = make_event(
        db, status=EventStatus.PLANNING, assigned_coordinator_id=Users.COORDINATOR_2.id
    )

    assert str(event.id) not in event_ids(coordinator_client.get(PICK_LIST_PATH))


@pytest.mark.story("12.1", ac=4)
def test_an_unassigned_approved_event_is_not_offered(coordinator_client, db: Session):
    event = make_event(db, status=EventStatus.PLANNING, assigned_coordinator_id=None)

    assert str(event.id) not in event_ids(coordinator_client.get(PICK_LIST_PATH))


@pytest.mark.story("12.1", ac=4)
def test_a_coordinator_with_nothing_approved_is_offered_an_empty_list(client, db: Session):
    """A freshly created coordinator, assigned to nothing, so their form has nothing to offer -
    the empty state the page has to render rather than an error."""
    coordinator = make_user(db, role="EVENT_COORDINATOR")
    client.login(coordinator.email)

    response = client.get(PICK_LIST_PATH)

    assert response.status_code == 200
    assert response.json()["events"] == []


@pytest.mark.story("12.1", ac=1)
def test_the_list_is_ordered_by_when_the_event_starts(coordinator_client, db: Session):
    """Soonest first: the event most in need of a venue is the one at the top of the form."""
    later = make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=datetime(2027, 6, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 6, 1, 17, 0, tzinfo=timezone.utc),
    )
    earlier = make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 10, 1, 17, 0, tzinfo=timezone.utc),
    )

    ids = event_ids(coordinator_client.get(PICK_LIST_PATH))

    assert ids.index(str(earlier.id)) < ids.index(str(Events.APPROVED)) < ids.index(str(later.id))


# --- Permissions -----------------------------------------------------------------------------
@pytest.mark.story("12.1", ac=4)
@pytest.mark.parametrize(
    "user",
    [Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda u: u.role,
)
def test_roles_that_cannot_raise_a_request_cannot_read_the_pick_list(client, user):
    client.login(user)

    assert client.get(PICK_LIST_PATH).status_code == 403


@pytest.mark.story("12.1", ac=4)
def test_signed_out_visitors_cannot_read_the_pick_list(client):
    assert client.get(PICK_LIST_PATH).status_code == 401
