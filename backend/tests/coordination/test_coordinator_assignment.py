"""Story 5.1 - be: assign coordinator to event.

AC1 A submitted event can be assigned to exactly one coordinator at a time.
AC2 Only users holding the Event Coordinator role can be selected.
AC3 The assignment is recorded with who assigned it and when.
AC4 The assigned coordinator's name is visible on the event.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.events.models import EventStatus
from tests.support.factories import make_event, make_user
from tests.support.seed import Events, Users


def _open_assignments(db: Session, event_id) -> list:
    return db.execute(
        text(
            "SELECT coordinator_id, assigned_by_id, assigned_at, note"
            " FROM event_coordinator_assignments"
            " WHERE event_id = :e AND unassigned_at IS NULL"
        ),
        {"e": event_id},
    ).all()


def _assigned_coordinator_id(db: Session, event_id):
    return db.execute(
        text("SELECT assigned_coordinator_id FROM events WHERE id = :e"), {"e": event_id}
    ).scalar()


# --- AC1: one coordinator at a time on a submitted event -----------------------------------
@pytest.mark.story("5.1", ac=1)
def test_submitted_event_can_be_assigned_a_coordinator(coordinator_client, db: Session):
    response = coordinator_client.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["event_id"] == str(Events.SUBMITTED)
    assert body["coordinator_id"] == str(Users.COORDINATOR_2.id)
    # the denormalised pointer on the event and the history row agree
    assert _assigned_coordinator_id(db, Events.SUBMITTED) == Users.COORDINATOR_2.id
    rows = _open_assignments(db, Events.SUBMITTED)
    assert len(rows) == 1 and rows[0].coordinator_id == Users.COORDINATOR_2.id


@pytest.mark.story("5.1", ac=1)
def test_assigning_replaces_the_previous_coordinator(coordinator_client, db: Session):
    """Events.APPROVED already belongs to Chloe; handing it to Carl leaves exactly one owner."""
    assert _assigned_coordinator_id(db, Events.APPROVED) == Users.COORDINATOR.id

    response = coordinator_client.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id), "note": "Chloe is on leave"},
    )

    assert response.status_code == 200, response.text
    rows = _open_assignments(db, Events.APPROVED)
    assert len(rows) == 1, "an event must have exactly one open assignment"
    assert rows[0].coordinator_id == Users.COORDINATOR_2.id
    assert rows[0].note == "Chloe is on leave"
    assert _assigned_coordinator_id(db, Events.APPROVED) == Users.COORDINATOR_2.id
    # the earlier assignment is kept as history, closed off rather than deleted
    closed = db.execute(
        text(
            "SELECT coordinator_id, unassigned_at FROM event_coordinator_assignments"
            " WHERE event_id = :e AND unassigned_at IS NOT NULL"
        ),
        {"e": Events.APPROVED},
    ).all()
    assert [r.coordinator_id for r in closed] == [Users.COORDINATOR.id]
    assert closed[0].unassigned_at is not None


@pytest.mark.story("5.1", ac=1)
def test_reassigning_the_same_coordinator_does_not_duplicate_history(
    coordinator_client, db: Session
):
    before = db.execute(
        text("SELECT count(*) FROM event_coordinator_assignments WHERE event_id = :e"),
        {"e": Events.APPROVED},
    ).scalar()

    response = coordinator_client.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR.id)},
    )

    assert response.status_code == 200, response.text
    assert response.json()["coordinator_id"] == str(Users.COORDINATOR.id)
    after = db.execute(
        text("SELECT count(*) FROM event_coordinator_assignments WHERE event_id = :e"),
        {"e": Events.APPROVED},
    ).scalar()
    assert after == before


@pytest.mark.story("5.1", ac=1)
def test_draft_event_cannot_be_assigned_a_coordinator(coordinator_client, db: Session):
    """AC1 is about a *submitted* event - a draft has not been handed over yet."""
    response = coordinator_client.put(
        f"/events/{Events.DRAFT}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR.id)},
    )

    assert response.status_code == 409, response.text
    assert "DRAFT" in response.json()["detail"]
    assert _open_assignments(db, Events.DRAFT) == []
    assert _assigned_coordinator_id(db, Events.DRAFT) is None


@pytest.mark.story("5.1", ac=1)
@pytest.mark.parametrize("status", [EventStatus.CANCELLED, EventStatus.COMPLETED])
def test_closed_event_cannot_be_assigned_a_coordinator(coordinator_client, db: Session, status):
    event = make_event(db, status=status)

    response = coordinator_client.put(
        f"/events/{event.id}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR.id)},
    )

    assert response.status_code == 409, response.text
    assert _open_assignments(db, event.id) == []


@pytest.mark.story("5.1", ac=1)
def test_unknown_event_is_not_found(coordinator_client):
    unknown = "33333333-0000-0000-0000-000000009999"

    response = coordinator_client.put(
        f"/events/{unknown}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR.id)},
    )

    assert response.status_code == 404, response.text


# --- AC2: only Event Coordinators may be selected ------------------------------------------
@pytest.mark.story("5.1", ac=2)
def test_only_event_coordinators_are_offered_for_selection(coordinator_client):
    response = coordinator_client.get("/coordinators")

    assert response.status_code == 200, response.text
    offered = {u["id"] for u in response.json()}
    assert offered == {str(Users.COORDINATOR.id), str(Users.COORDINATOR_2.id)}
    assert [u["full_name"] for u in response.json()] == ["Carl Coordinator", "Chloe Coordinator"]


@pytest.mark.story("5.1", ac=2)
def test_inactive_coordinators_are_not_offered(coordinator_client, db: Session):
    inactive = make_user(db, role="EVENT_COORDINATOR", is_active=False)

    response = coordinator_client.get("/coordinators")

    assert response.status_code == 200, response.text
    assert str(inactive.id) not in {u["id"] for u in response.json()}


@pytest.mark.story("5.1", ac=2)
@pytest.mark.parametrize(
    "user",
    [Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda u: u.role,
)
def test_user_without_the_coordinator_role_cannot_be_assigned(
    coordinator_client, db: Session, user
):
    response = coordinator_client.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(user.id)},
    )

    assert response.status_code == 422, response.text
    assert "EVENT_COORDINATOR" in response.json()["detail"]
    assert _open_assignments(db, Events.SUBMITTED) == []
    assert _assigned_coordinator_id(db, Events.SUBMITTED) is None


@pytest.mark.story("5.1", ac=2)
def test_inactive_coordinator_cannot_be_assigned(coordinator_client, db: Session):
    inactive = make_user(db, role="EVENT_COORDINATOR", is_active=False)

    response = coordinator_client.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(inactive.id)},
    )

    assert response.status_code == 422, response.text
    assert _open_assignments(db, Events.SUBMITTED) == []


@pytest.mark.story("5.1", ac=2)
def test_unknown_user_cannot_be_assigned(coordinator_client, db: Session):
    response = coordinator_client.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": "11111111-0000-0000-0000-000000009999"},
    )

    assert response.status_code == 422, response.text
    assert _open_assignments(db, Events.SUBMITTED) == []


# --- AC3: who assigned it, and when --------------------------------------------------------
@pytest.mark.story("5.1", ac=3)
def test_assignment_records_who_assigned_it_and_when(coordinator_client, db: Session):
    response = coordinator_client.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id), "note": "Carl has the capacity"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assigned_by_id"] == str(Users.COORDINATOR.id)
    assert body["assigned_by_name"] == Users.COORDINATOR.full_name
    assert body["assigned_at"] is not None
    assert body["note"] == "Carl has the capacity"

    row = _open_assignments(db, Events.SUBMITTED)[0]
    assert row.assigned_by_id == Users.COORDINATOR.id
    assert row.assigned_at is not None


@pytest.mark.story("5.1", ac=3)
def test_assignment_is_written_to_the_audit_log(coordinator_client, db: Session):
    coordinator_client.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    entry = db.execute(
        text(
            "SELECT actor_id, details FROM audit_log"
            " WHERE action = 'EVENT_COORDINATOR_ASSIGNED' AND entity_id = :e"
        ),
        {"e": Events.SUBMITTED},
    ).one()
    assert entry.actor_id == Users.COORDINATOR.id
    assert entry.details["coordinator_id"] == str(Users.COORDINATOR_2.id)


# --- AC4: the coordinator's name is visible on the event -----------------------------------
@pytest.mark.story("5.1", ac=4)
def test_assigned_coordinator_name_is_returned_on_assignment(coordinator_client):
    response = coordinator_client.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    assert response.status_code == 200, response.text
    assert response.json()["coordinator_name"] == Users.COORDINATOR_2.full_name


@pytest.mark.story("5.1", ac=4)
def test_assigned_coordinator_name_is_visible_on_the_event(coordinator_client):
    coordinator_client.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    response = coordinator_client.get(f"/events/{Events.SUBMITTED}/coordinator")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["coordinator_name"] == Users.COORDINATOR_2.full_name
    assert body["coordinator_email"] == Users.COORDINATOR_2.email


@pytest.mark.story("5.1", ac=4)
def test_organiser_sees_the_coordinator_of_their_own_event(coordinator_client, login_as):
    coordinator_client.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    organiser = login_as(Users.ORGANISER)  # owns Events.SUBMITTED
    response = organiser.get(f"/events/{Events.SUBMITTED}/coordinator")

    assert response.status_code == 200, response.text
    assert response.json()["coordinator_name"] == Users.COORDINATOR_2.full_name


@pytest.mark.story("5.1", ac=4)
def test_event_without_a_coordinator_reports_none(coordinator_client):
    response = coordinator_client.get(f"/events/{Events.SUBMITTED}/coordinator")

    assert response.status_code == 200, response.text
    assert response.json() is None


@pytest.mark.story("5.1", ac=4)
def test_unrelated_organiser_cannot_see_another_organisers_event(login_as):
    other = login_as(Users.ORGANISER_2)  # Events.SUBMITTED belongs to ORGANISER

    response = other.get(f"/events/{Events.SUBMITTED}/coordinator")

    assert response.status_code == 403, response.text


# --- Access control (story 1.2 AC4 applied to this endpoint) -------------------------------
@pytest.mark.story("5.1", ac=2)
@pytest.mark.parametrize(
    "user",
    [Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda u: u.role,
)
def test_only_roles_that_review_events_may_assign(login_as, db: Session, user):
    actor = login_as(user)

    response = actor.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR.id)},
    )

    assert response.status_code == 403, response.text
    assert _open_assignments(db, Events.SUBMITTED) == []


@pytest.mark.story("5.1", ac=2)
def test_signing_in_is_required_to_assign(client):
    response = client.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR.id)},
    )

    assert response.status_code == 401, response.text
