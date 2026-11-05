"""Story 5.1 - be: assign coordinator to event.

The criteria this file tests, as they stand since stories 5.4 and 5.6:

AC1  A submitted event has exactly one coordinator at a time; assigning by hand replaces the
     current one.
AC2  Only active Event Coordinators can be assigned.
AC3  Each assignment records who made it and when.
AC4  The assigned coordinator's name is visible on the event. The event page's tile is proven in
     tests/e2e/coordinator-assignment.spec.ts.
AC6  When coordinators are added or deactivated, the one added can be assigned and the one
     deactivated no longer can.
AC10 A hand reassignment changes only its own event: no other event's coordinator moves, and the
     next submission still waits unassigned.
AC11 Only Event Coordinators are ever assigned: every other role, the Lead's included, is refused.
AC13 Assigning by hand is refused (403) for roles that do not review events.

Story 5.4 AC9 switched off 5.1's automatic, round-robin assignment and replaced 5.1 AC1, AC2 and
AC13: since story 5.6 (Q16) only the Event Coordinator Lead writes an assignment - 5.4 gave the Lead
the first one, and 5.6 the reassignments, which name the coordinator the Lead saw
(``expected_coordinator_id``). The writes here are therefore the Lead's, and AC13's refusal now
covers every role but the Lead's (5.4 AC7). What submission does about a coordinator (AC5, AC7-AC9,
AC12, AC14, AC15) is in test_auto_assign_coordinator.py.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.events.models import EventStatus
from tests.support.factories import create_submittable_event_request, make_event, make_user
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
def test_submitted_event_can_be_assigned_a_coordinator(login_as, db: Session):
    lead = login_as(Users.LEAD)
    response = lead.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
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
def test_assigning_replaces_the_previous_coordinator(login_as, db: Session):
    """Events.APPROVED already belongs to Chloe; handing it to Carl leaves exactly one owner."""
    lead = login_as(Users.LEAD)
    assert _assigned_coordinator_id(db, Events.APPROVED) == Users.COORDINATOR.id

    response = lead.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
            "note": "Chloe is on leave",
        },
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
def test_reassigning_the_same_coordinator_does_not_duplicate_history(login_as, db: Session):
    lead = login_as(Users.LEAD)
    before = db.execute(
        text("SELECT count(*) FROM event_coordinator_assignments WHERE event_id = :e"),
        {"e": Events.APPROVED},
    ).scalar()

    response = lead.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["coordinator_id"] == str(Users.COORDINATOR.id)
    after = db.execute(
        text("SELECT count(*) FROM event_coordinator_assignments WHERE event_id = :e"),
        {"e": Events.APPROVED},
    ).scalar()
    assert after == before


@pytest.mark.story("5.6", ac=3)
def test_reassigning_the_same_coordinator_leaves_the_event_version_alone(login_as, db: Session):
    """5.6 AC3 (CL-147 (4)): re-choosing the coordinator who has the event writes nothing to it, so
    its ``updated_at`` - the version story 7.2's correction checks (AC9) - is unchanged, and a
    correction Chloe has open is not refused because of it (review of #124)."""
    version = text("SELECT updated_at FROM events WHERE id = :e")
    before = db.execute(version, {"e": Events.APPROVED}).scalar()

    response = login_as(Users.LEAD).put(
        f"/events/{Events.APPROVED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    assert response.status_code == 200, response.text
    assert db.execute(version, {"e": Events.APPROVED}).scalar() == before


@pytest.mark.story("5.1", ac=1)
def test_draft_event_cannot_be_assigned_a_coordinator(login_as, db: Session):
    """AC1 is about a *submitted* event - a draft has not been handed over yet."""
    lead = login_as(Users.LEAD)
    response = lead.put(
        f"/events/{Events.DRAFT}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR.id)},
    )

    assert response.status_code == 409, response.text
    assert "DRAFT" in response.json()["detail"]
    assert _open_assignments(db, Events.DRAFT) == []
    assert _assigned_coordinator_id(db, Events.DRAFT) is None


@pytest.mark.story("5.1", ac=1)
@pytest.mark.parametrize("status", [EventStatus.CANCELLED, EventStatus.COMPLETED])
def test_closed_event_cannot_be_assigned_a_coordinator(login_as, db: Session, status):
    lead = login_as(Users.LEAD)
    event = make_event(db, status=status)

    response = lead.put(
        f"/events/{event.id}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR.id)},
    )

    assert response.status_code == 409, response.text
    assert _open_assignments(db, event.id) == []


@pytest.mark.story("5.1", ac=1)
def test_unknown_event_is_not_found(login_as):
    lead = login_as(Users.LEAD)
    unknown = "33333333-0000-0000-0000-000000009999"

    response = lead.put(
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
def test_user_without_the_coordinator_role_cannot_be_assigned(login_as, db: Session, user):
    lead = login_as(Users.LEAD)
    before = _open_assignments(db, Events.SUBMITTED)

    response = lead.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={
            "coordinator_id": str(user.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    assert response.status_code == 422, response.text
    assert "EVENT_COORDINATOR" in response.json()["detail"]
    assert _open_assignments(db, Events.SUBMITTED) == before  # rejected attempt changed nothing


@pytest.mark.story("5.1", ac=2)
def test_inactive_coordinator_cannot_be_assigned(login_as, db: Session):
    lead = login_as(Users.LEAD)
    inactive = make_user(db, role="EVENT_COORDINATOR", is_active=False)
    before = _open_assignments(db, Events.SUBMITTED)

    response = lead.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={
            "coordinator_id": str(inactive.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    assert response.status_code == 422, response.text
    assert _open_assignments(db, Events.SUBMITTED) == before  # rejected attempt changed nothing


@pytest.mark.story("5.1", ac=2)
def test_unknown_user_cannot_be_assigned(login_as, db: Session):
    lead = login_as(Users.LEAD)
    before = _open_assignments(db, Events.SUBMITTED)

    response = lead.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={
            "coordinator_id": "11111111-0000-0000-0000-000000009999",
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    assert response.status_code == 422, response.text
    assert _open_assignments(db, Events.SUBMITTED) == before  # rejected attempt changed nothing


# --- AC3: who assigned it, and when --------------------------------------------------------
@pytest.mark.story("5.1", ac=3)
def test_assignment_records_who_assigned_it_and_when(login_as, db: Session):
    lead = login_as(Users.LEAD)
    response = lead.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
            "note": "Carl has the capacity",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assigned_by_id"] == str(Users.LEAD.id)
    assert body["assigned_by_name"] == Users.LEAD.full_name
    assert body["assigned_at"] is not None
    assert body["note"] == "Carl has the capacity"

    row = _open_assignments(db, Events.SUBMITTED)[0]
    assert row.assigned_by_id == Users.LEAD.id
    assert row.assigned_at is not None


@pytest.mark.story("5.1", ac=3)
def test_assignment_is_written_to_the_audit_log(login_as, db: Session):
    lead = login_as(Users.LEAD)
    lead.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    entry = db.execute(
        text(
            "SELECT actor_id, details FROM audit_log"
            " WHERE action = 'EVENT_COORDINATOR_ASSIGNED' AND entity_id = :e"
        ),
        {"e": Events.SUBMITTED},
    ).one()
    assert entry.actor_id == Users.LEAD.id
    assert entry.details["coordinator_id"] == str(Users.COORDINATOR_2.id)


# --- AC6: coordinators added or deactivated -----------------------------------------------
@pytest.mark.story("5.1", ac=6)
def test_a_coordinator_added_later_is_offered_and_can_be_assigned(login_as, db: Session):
    added = make_user(db, role="EVENT_COORDINATOR", full_name="Cara Coordinator")
    lead = login_as(Users.LEAD)

    offered = lead.get("/coordinators")
    response = lead.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={
            "coordinator_id": str(added.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    assert str(added.id) in {u["id"] for u in offered.json()}
    assert response.status_code == 200, response.text
    assert _assigned_coordinator_id(db, Events.SUBMITTED) == added.id


@pytest.mark.story("5.1", ac=6)
def test_a_coordinator_deactivated_later_is_no_longer_offered_or_assignable(login_as, db: Session):
    """Carl was active and offered; once deactivated he is skipped, and Chloe still is offered."""
    lead = login_as(Users.LEAD)
    assert str(Users.COORDINATOR_2.id) in {u["id"] for u in lead.get("/coordinators").json()}
    db.execute(
        text("UPDATE users SET is_active = FALSE WHERE id = :u"), {"u": Users.COORDINATOR_2.id}
    )
    before = _open_assignments(db, Events.SUBMITTED)

    offered = {u["id"] for u in lead.get("/coordinators").json()}
    response = lead.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    assert offered == {str(Users.COORDINATOR.id)}
    assert response.status_code == 422, response.text
    assert _open_assignments(db, Events.SUBMITTED) == before


# --- AC4: the coordinator's name is visible on the event -----------------------------------
@pytest.mark.story("5.1", ac=4)
def test_assigned_coordinator_name_is_returned_on_assignment(login_as):
    lead = login_as(Users.LEAD)
    response = lead.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["coordinator_name"] == Users.COORDINATOR_2.full_name


@pytest.mark.story("5.1", ac=4)
def test_assigned_coordinator_name_is_visible_on_the_event(login_as):
    lead = login_as(Users.LEAD)
    lead.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    response = lead.get(f"/events/{Events.SUBMITTED}/coordinator")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["coordinator_name"] == Users.COORDINATOR_2.full_name
    assert body["coordinator_email"] == Users.COORDINATOR_2.email


@pytest.mark.story("5.1", ac=4)
def test_organiser_sees_the_coordinator_of_their_own_event(login_as):
    lead = login_as(Users.LEAD)
    lead.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    organiser = login_as(Users.ORGANISER)  # owns Events.SUBMITTED
    response = organiser.get(f"/events/{Events.SUBMITTED}/coordinator")

    assert response.status_code == 200, response.text
    assert response.json()["coordinator_name"] == Users.COORDINATOR_2.full_name


@pytest.mark.story("5.1", ac=4)
def test_event_without_a_coordinator_reports_none(coordinator_client, db: Session):
    """Every seeded submitted event already has a coordinator (5.4 AC10), so this test uses a
    fresh event that genuinely has none yet."""
    event = make_event(db)

    response = coordinator_client.get(f"/events/{event.id}/coordinator")

    assert response.status_code == 200, response.text
    assert response.json() is None


@pytest.mark.story("5.1", ac=4)
def test_unrelated_organiser_cannot_see_another_organisers_event(login_as):
    other = login_as(Users.ORGANISER_2)  # Events.SUBMITTED belongs to ORGANISER

    response = other.get(f"/events/{Events.SUBMITTED}/coordinator")

    assert response.status_code == 403, response.text


@pytest.mark.story("5.1", ac=4)
def test_the_coordinator_of_an_unknown_event_is_not_found(login_as):
    """No such event: 404, not an empty answer that would read as "nobody assigned yet"."""
    response = login_as(Users.LEAD).get(f"/events/{uuid.uuid4()}/coordinator")

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Event not found."


# --- AC13: access control (story 1.2 AC4 applied to this endpoint) -------------------------
@pytest.mark.story("5.1", ac=13)
@pytest.mark.story("5.4", ac=7)
@pytest.mark.parametrize(
    "user",
    # Every role but the Lead's, so a role added later is refused here without editing this list.
    [user for user in Users.ONE_PER_ROLE if user != Users.LEAD],
    ids=lambda u: u.role,
)
def test_only_the_lead_may_assign(login_as, db: Session, user):
    """5.4 AC7: Event Coordinators and all other roles are refused (403). Chloe is included - the
    coordinator Events.SUBMITTED is assigned to - since story 5.6 (Q16) took reassignment from
    coordinators too."""
    before = _open_assignments(db, Events.SUBMITTED)
    actor = login_as(user)

    response = actor.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR.id)},
    )

    assert response.status_code == 403, response.text
    assert _open_assignments(db, Events.SUBMITTED) == before  # rejected attempt changed nothing


@pytest.mark.story("5.1", ac=2)
def test_signing_in_is_required_to_assign(client):
    response = client.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR.id)},
    )

    assert response.status_code == 401, response.text


# --- AC10: a hand reassignment changes only its own event ----------------------------------
@pytest.mark.story("5.1", ac=10)
def test_a_reassignment_moves_no_other_event_and_the_next_submission_waits(login_as, db: Session):
    pointers = text("SELECT id, assigned_coordinator_id FROM events WHERE id <> :e ORDER BY id")
    others_before = db.execute(pointers, {"e": Events.APPROVED}).all()

    reassigned = login_as(Users.LEAD).put(
        f"/events/{Events.APPROVED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )
    organiser = login_as(Users.ORGANISER)
    draft = create_submittable_event_request(organiser)
    submitted = organiser.post(f"/events/{draft['id']}/submit")

    assert reassigned.status_code == 200, reassigned.text
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["assigned_coordinator_id"] is None
    others_after = [
        row
        for row in db.execute(pointers, {"e": Events.APPROVED}).all()
        if str(row.id) != draft["id"]
    ]
    assert others_after == others_before


# --- AC11: only Event Coordinators are ever assigned ---------------------------------------
@pytest.mark.story("5.1", ac=11)
@pytest.mark.parametrize(
    "user",
    # Every role but the coordinator's, so a role added later is refused here without editing it.
    [user for user in Users.ONE_PER_ROLE if user.role != "EVENT_COORDINATOR"],
    ids=lambda u: u.role,
)
def test_no_role_but_the_event_coordinator_is_ever_assigned(login_as, db: Session, user):
    """The Lead, who assigns, cannot be given the event either."""
    lead = login_as(Users.LEAD)
    before = _open_assignments(db, Events.SUBMITTED)

    offered = {u["id"] for u in lead.get("/coordinators").json()}
    response = lead.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={
            "coordinator_id": str(user.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    assert str(user.id) not in offered
    assert response.status_code == 422, response.text
    assert _open_assignments(db, Events.SUBMITTED) == before
