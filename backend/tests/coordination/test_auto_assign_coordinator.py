"""Story 5.1 (extended) - be: automatically assign a coordinator on submission, round robin.

The requirement changed from "a coordinator assigns themselves or another coordinator by hand"
to "the system assigns one automatically, in round-robin order, the moment a request is
submitted" - manual assign/reassign (tested in test_coordinator_assignment.py) keeps working
unchanged and is now just how a human overrides the rotation's choice.

AC1  Submitting an event automatically assigns one Event Coordinator, in the same transaction.
AC2  Coordinators are assigned in a fixed, deterministic (round-robin) order.
AC3  The automatic assignment is recorded as the system (assigned_by_id NULL), with a note
     identifying it as a round-robin auto-assignment; the name is visible on the event.
AC4  Exactly one coordinator -> every submission goes to them.
AC5  Zero coordinators -> submission still succeeds, unassigned, no error.
AC6  Coordinators added/removed -> rotation continues from the next after the last
     auto-assigned one, wrapping around; an inactive coordinator is skipped.
AC7  Saving or editing a draft never assigns a coordinator.
AC8  Resubmitting after a clarification request does not reassign (no resubmit endpoint exists
     yet - the clarification round-trip isn't built - so this is exercised as AC9's guarantee
     directly against the service layer, which is what any future resubmit would rely on).
AC9  An event that already has a coordinator is never overridden by auto-assignment.
AC10 Manual reassignments do not affect the rotation - only automatic assignments count.
AC11 Only EVENT_COORDINATOR-role users are ever auto-assigned.
AC12 An organiser cannot choose the coordinator through the submit request.
AC13 Manual assign/reassign stays restricted to the roles already allowed (see also
     test_coordinator_assignment.py, which carries the AC2 version of this same check).
AC14 Two submissions at the same moment never race to pick the same "next" coordinator - the
     pick is serialised with a transaction-scoped advisory lock.
AC15 An unexpected assignment failure rolls back the whole submission.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.coordination import service as coordination_service
from app.coordination.schemas import AssignCoordinatorIn
from app.events.models import Event, EventStatus
from tests.support.factories import (
    create_event_request,
    create_submittable_event_request,
    make_event,
    make_user,
)
from tests.support.seed import Events, Users


def _coord_id(n: int) -> uuid.UUID:
    """A coordinator id that always sorts after every seeded user (``11111111...``), so tests
    that add coordinators can reason about rotation order without depending on timing."""
    return uuid.UUID(f"cccccccc-0000-0000-0000-{n:012d}")


def _deactivate(db: Session, user_id: uuid.UUID) -> None:
    db.get(User, user_id).is_active = False
    db.flush()


def _open_assignment_row(db: Session, event_id):
    return db.execute(
        text(
            "SELECT coordinator_id, assigned_by_id, assigned_at, note"
            " FROM event_coordinator_assignments"
            " WHERE event_id = :e AND unassigned_at IS NULL"
        ),
        {"e": event_id},
    ).one_or_none()


def _submit(client, event: dict) -> dict:
    response = client.post(f"/events/{event['id']}/submit")
    assert response.status_code == 200, response.text
    return response.json()


# --- AC1: assigned automatically, in the same transaction as submission --------------------
@pytest.mark.story("5.1", ac=1)
def test_submission_automatically_assigns_a_coordinator(organiser_client, db: Session):
    draft = create_submittable_event_request(organiser_client)

    body = _submit(organiser_client, draft)

    assert body["assigned_coordinator_id"] is not None
    assert body["assigned_coordinator_name"] is not None
    row = _open_assignment_row(db, draft["id"])
    assert row is not None
    assert str(row.coordinator_id) == body["assigned_coordinator_id"]


# --- AC2: fixed, deterministic round-robin order --------------------------------------------
@pytest.mark.story("5.1", ac=2)
def test_coordinators_are_assigned_in_round_robin_order(organiser_client, db: Session):
    """With coordinators A, B, C, consecutive submissions go A, B, C, A. The two seed
    coordinators are deactivated so the rotation is exercised over a clean, readable pool of
    three, added with explicit ids so the expected order does not depend on timing."""
    _deactivate(db, Users.COORDINATOR.id)
    _deactivate(db, Users.COORDINATOR_2.id)
    a = make_user(db, role="EVENT_COORDINATOR", id=_coord_id(1), full_name="Coordinator A")
    b = make_user(db, role="EVENT_COORDINATOR", id=_coord_id(2), full_name="Coordinator B")
    c = make_user(db, role="EVENT_COORDINATOR", id=_coord_id(3), full_name="Coordinator C")

    order = []
    for _ in range(4):
        draft = create_submittable_event_request(organiser_client)
        order.append(_submit(organiser_client, draft)["assigned_coordinator_id"])

    assert order == [str(a.id), str(b.id), str(c.id), str(a.id)]


# --- AC3: recorded as the system, with a note, name visible ---------------------------------
@pytest.mark.story("5.1", ac=3)
def test_automatic_assignment_is_recorded_as_the_system(organiser_client, db: Session):
    draft = create_submittable_event_request(organiser_client)

    body = _submit(organiser_client, draft)

    row = _open_assignment_row(db, draft["id"])
    assert row.assigned_by_id is None
    assert row.assigned_at is not None
    assert row.note is not None
    assert "round" in row.note.lower() or "automat" in row.note.lower()
    coordinator_name = db.execute(
        text("SELECT full_name FROM users WHERE id = :c"), {"c": row.coordinator_id}
    ).scalar()
    assert body["assigned_coordinator_name"] == coordinator_name


@pytest.mark.story("5.1", ac=3)
def test_automatic_assignment_is_visible_via_the_coordinator_endpoint(organiser_client, login_as):
    draft = create_submittable_event_request(organiser_client)
    body = _submit(organiser_client, draft)

    coordinator = login_as(Users.COORDINATOR)
    response = coordinator.get(f"/events/{draft['id']}/coordinator")

    assert response.status_code == 200, response.text
    assert response.json()["coordinator_name"] == body["assigned_coordinator_name"]
    assert response.json()["assigned_by_id"] is None


# --- AC4: exactly one coordinator gets every submission -------------------------------------
@pytest.mark.story("5.1", ac=4)
def test_single_coordinator_gets_every_submission(organiser_client, db: Session):
    _deactivate(db, Users.COORDINATOR_2.id)

    for _ in range(3):
        draft = create_submittable_event_request(organiser_client)
        body = _submit(organiser_client, draft)
        assert body["assigned_coordinator_id"] == str(Users.COORDINATOR.id)


# --- AC5: zero coordinators -> unassigned, no error ------------------------------------------
@pytest.mark.story("5.1", ac=5)
def test_no_coordinators_leaves_the_event_unassigned(organiser_client, db: Session):
    _deactivate(db, Users.COORDINATOR.id)
    _deactivate(db, Users.COORDINATOR_2.id)
    draft = create_submittable_event_request(organiser_client)

    body = _submit(organiser_client, draft)

    assert body["status"] == EventStatus.UNDER_REVIEW
    assert body["assigned_coordinator_id"] is None
    assert _open_assignment_row(db, draft["id"]) is None


# --- AC6: rotation survives coordinators being added, removed and reactivated ---------------
@pytest.mark.story("5.1", ac=6)
def test_rotation_continues_and_skips_inactive_coordinators(organiser_client, db: Session):
    carl = db.get(User, Users.COORDINATOR_2.id)
    carl.is_active = False
    db.flush()

    draft1 = create_submittable_event_request(organiser_client)
    body1 = _submit(organiser_client, draft1)
    assert body1["assigned_coordinator_id"] == str(Users.COORDINATOR.id), "Carl is inactive"

    carl.is_active = True
    dana = make_user(db, role="EVENT_COORDINATOR", id=_coord_id(4), full_name="Dana Coordinator")

    draft2 = create_submittable_event_request(organiser_client)
    body2 = _submit(organiser_client, draft2)
    assert body2["assigned_coordinator_id"] == str(Users.COORDINATOR_2.id), "next after Chloe"

    chloe = db.get(User, Users.COORDINATOR.id)
    chloe.is_active = False
    db.flush()

    draft3 = create_submittable_event_request(organiser_client)
    body3 = _submit(organiser_client, draft3)
    assert body3["assigned_coordinator_id"] == str(dana.id), "Chloe now inactive, skip to Dana"


# --- AC7: a draft is never assigned, saved or edited -----------------------------------------
@pytest.mark.story("5.1", ac=7)
def test_creating_a_draft_never_assigns_a_coordinator(organiser_client, db: Session):
    draft = create_event_request(organiser_client)

    assert draft["assigned_coordinator_id"] is None
    assert _open_assignment_row(db, draft["id"]) is None


@pytest.mark.story("5.1", ac=7)
def test_editing_a_draft_never_assigns_a_coordinator(organiser_client, db: Session):
    draft = create_event_request(organiser_client)

    response = organiser_client.patch(f"/events/{draft['id']}", json={"description": "Updated."})

    assert response.status_code == 200, response.text
    assert response.json()["assigned_coordinator_id"] is None
    assert _open_assignment_row(db, draft["id"]) is None


# --- AC8: resubmitting after clarification keeps the current coordinator --------------------
@pytest.mark.story("5.1", ac=8)
def test_resubmission_after_clarification_keeps_the_current_coordinator(db: Session):
    """There is no resubmit endpoint yet - stories 4.2/4.3's clarification round-trip only
    records the conversation so far (see app/events/service.py:list_clarifications) and never
    moves a CLARIFICATION_REQUESTED event back to UNDER_REVIEW. Until that exists, this proves the
    guarantee a future resubmit would rely on directly at the service layer: auto-assign never
    touches an event that already has a coordinator (the same rule AC9 states)."""
    event = make_event(db, status=EventStatus.CLARIFICATION_REQUESTED)
    actor = db.get(User, Users.COORDINATOR.id)
    coordination_service.assign_coordinator(
        db, event.id, AssignCoordinatorIn(coordinator_id=Users.COORDINATOR_2.id), actor=actor
    )

    result = coordination_service.auto_assign_next_coordinator(db, event)

    assert result is None
    assert event.assigned_coordinator_id == Users.COORDINATOR_2.id


# --- AC9: an event with a coordinator is never overridden ------------------------------------
@pytest.mark.story("5.1", ac=9)
def test_event_with_a_coordinator_is_never_overridden(db: Session):
    event = db.get(Event, Events.SUBMITTED)
    before = event.assigned_coordinator_id
    assert before is not None, "seed: Events.SUBMITTED (UNDER_REVIEW) already has a coordinator"

    result = coordination_service.auto_assign_next_coordinator(db, event)

    assert result is None
    assert event.assigned_coordinator_id == before


# --- AC10: manual reassignment does not steer the rotation -----------------------------------
@pytest.mark.story("5.1", ac=10)
def test_manual_reassignment_does_not_affect_the_rotation(
    coordinator_client, login_as, db: Session
):
    extra = make_user(db, role="EVENT_COORDINATOR", id=_coord_id(5), full_name="Extra Coordinator")
    # A manual reassignment, most recent by assigned_at - if it counted toward the rotation, the
    # next automatic pick would wrap to Chloe (first in order) instead of Carl.
    response = coordinator_client.put(
        f"/events/{Events.APPROVED}/coordinator", json={"coordinator_id": str(extra.id)}
    )
    assert response.status_code == 200, response.text

    # organiser_client and coordinator_client share one session (tests/conftest.py), so switch
    # identity on the same client via login_as rather than requesting both fixtures at once.
    organiser = login_as(Users.ORGANISER)
    draft = create_submittable_event_request(organiser)
    body = _submit(organiser, draft)

    assert body["assigned_coordinator_id"] == str(Users.COORDINATOR_2.id)
    assert body["assigned_coordinator_id"] != str(extra.id)


# --- AC11: only Event Coordinators are ever auto-assigned ------------------------------------
@pytest.mark.story("5.1", ac=11)
def test_only_event_coordinators_are_ever_auto_assigned(organiser_client, db: Session):
    make_user(db, role="VENUE_STAFF", id=_coord_id(6), full_name="Not A Coordinator")

    draft = create_submittable_event_request(organiser_client)
    body = _submit(organiser_client, draft)

    assert body["assigned_coordinator_id"] in {
        str(Users.COORDINATOR.id),
        str(Users.COORDINATOR_2.id),
    }


# --- AC12: an organiser cannot choose the coordinator through submit -------------------------
@pytest.mark.story("5.1", ac=12)
def test_submit_ignores_a_coordinator_chosen_by_the_organiser(organiser_client):
    draft = create_submittable_event_request(organiser_client)

    response = organiser_client.post(
        f"/events/{draft['id']}/submit", json={"coordinator_id": str(Users.COORDINATOR.id)}
    )

    assert response.status_code == 200, response.text
    # Rotation picks Carl next (seed history's last auto-assignment was Chloe); the organiser's
    # attempt to name Chloe in the body must have no effect.
    assert response.json()["assigned_coordinator_id"] == str(Users.COORDINATOR_2.id)


# --- AC13: manual assign/reassign stays restricted to the roles already allowed -------------
@pytest.mark.story("5.1", ac=13)
@pytest.mark.parametrize(
    "user",
    [Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda u: u.role,
)
def test_manual_assignment_stays_restricted_to_allowed_roles(login_as, user):
    actor = login_as(user)

    response = actor.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR.id)},
    )

    assert response.status_code == 403, response.text


# --- AC14: concurrent submissions never race the same pick -----------------------------------
@pytest.mark.story("5.1", ac=14)
def test_the_coordinator_pick_is_serialised_with_an_advisory_lock(db: Session, engine):
    """The shared ``db`` fixture wraps every test in one savepoint-based transaction (see
    conftest.py), so it cannot itself host two genuinely concurrent connections the way a real
    race between two submissions would. What can be verified directly is the serialisation
    mechanism itself: a transaction that has just picked a coordinator must still be holding a
    lock that stops any other transaction from picking concurrently, for as long as it is open -
    the same guarantee ``submit_event``'s own conditional UPDATE relies on for the status
    transition."""
    event = make_event(db, assigned_coordinator_id=None)

    coordination_service.auto_assign_next_coordinator(db, event)

    with engine.connect() as other_connection:
        acquired_elsewhere = other_connection.execute(
            select(func.pg_try_advisory_xact_lock(coordination_service.ROUND_ROBIN_LOCK_KEY))
        ).scalar()
    assert acquired_elsewhere is False, (
        "a second connection could take the round-robin lock while the transaction that just "
        "picked a coordinator was still open - the pick is not serialised"
    )


# --- AC15: an unexpected failure rolls back the whole submission -----------------------------
@pytest.mark.story("5.1", ac=15)
def test_unexpected_assignment_failure_rolls_back_the_whole_submission(
    organiser_client, db: Session, monkeypatch
):
    draft = create_submittable_event_request(organiser_client)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated auto-assign failure")

    monkeypatch.setattr(coordination_service, "auto_assign_next_coordinator", _boom)

    with pytest.raises(RuntimeError):
        organiser_client.post(f"/events/{draft['id']}/submit")
    # Mirrors what app.db.get_db's real `finally: db.close()` does on an unhandled exception -
    # the test harness shares one long-lived session across a whole test (conftest.py), so this
    # test does that rollback itself instead of relying on a per-request session teardown.
    db.rollback()

    status = db.execute(
        text("SELECT status FROM events WHERE id = :e"), {"e": draft["id"]}
    ).scalar()
    assert status == EventStatus.DRAFT
    assert _open_assignment_row(db, draft["id"]) is None
