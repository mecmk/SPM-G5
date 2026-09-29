"""Story 5.2 - be: reassign a coordinator-holding event to a different coordinator.

Reuses story 5.1's ``PUT /events/{event_id}/coordinator`` and its ``_create_assignment`` helper
rather than adding a second endpoint - a reassignment is simply an assignment made by the event's
*current* coordinator, which 5.1 already lets happen, just without 5.2's tighter permission rule
(AC6) or its concurrency guard (AC7).

AC1  On a non-terminal event, the assigned coordinator can choose another active coordinator.
     The change records who made it and when; both coordinators and the organiser are notified.
AC2  The previous assignment is kept in the event's history.
AC3  The event page has a Reassign action (e2e, tests/e2e/coordinator-reassignment.spec.ts); the
     assignment change and its history entry are saved together, and access checks use the new
     assignment immediately.
AC4  Only active Event Coordinators are offered, and the current coordinator is excluded.
AC5  Pending booking requests and clarification threads move with the event (change requests,
     story 19.x, have no application code yet - nothing exists to verify moving).
AC6  Only the currently assigned coordinator can reassign; the previous coordinator loses
     assignment access immediately.
AC7  Two simultaneous reassignments: the second is refused because the assignment has changed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.coordination import service as coordination_service
from app.coordination.schemas import AssignCoordinatorIn
from tests.support.factories import make_clarification, make_user
from tests.support.seed import Events, Users


def _open_assignment_row(db: Session, event_id):
    return db.execute(
        text(
            "SELECT coordinator_id, assigned_by_id, assigned_at, note"
            " FROM event_coordinator_assignments"
            " WHERE event_id = :e AND unassigned_at IS NULL"
        ),
        {"e": event_id},
    ).one_or_none()


def _history_row_count(db: Session, event_id) -> int:
    return db.execute(
        text("SELECT count(*) FROM event_coordinator_assignments WHERE event_id = :e"),
        {"e": event_id},
    ).scalar()


def _notification_recipients(db: Session, event_id) -> set:
    return set(
        db.execute(
            text(
                "SELECT recipient_id FROM notifications"
                " WHERE event_id = :e AND notification_type LIKE 'EVENT_REASSIGN%'"
            ),
            {"e": event_id},
        ).scalars()
    )


# --- AC1: happy path -------------------------------------------------------------------------
@pytest.mark.story("5.2", ac=1)
def test_reassignment_updates_pointer_and_records_who_and_when(coordinator_client, db: Session):
    """Events.APPROVED is in PLANNING, assigned to Chloe - a valid reassignment target."""
    response = coordinator_client.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id), "note": "Covering while I'm on leave"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["coordinator_id"] == str(Users.COORDINATOR_2.id)
    assert body["assigned_by_id"] == str(Users.COORDINATOR.id)
    assert body["assigned_at"] is not None
    row = _open_assignment_row(db, Events.APPROVED)
    assert row.coordinator_id == Users.COORDINATOR_2.id
    assert row.assigned_by_id == Users.COORDINATOR.id


@pytest.mark.story("5.2", ac=1)
def test_reassignment_notifies_both_coordinators_and_the_organiser(coordinator_client, db: Session):
    response = coordinator_client.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    assert response.status_code == 200, response.text
    event_organiser_id = db.execute(
        text("SELECT organiser_id FROM events WHERE id = :e"), {"e": Events.APPROVED}
    ).scalar()
    recipients = _notification_recipients(db, Events.APPROVED)
    assert recipients == {Users.COORDINATOR.id, Users.COORDINATOR_2.id, event_organiser_id}


# --- AC2: history is kept, not deleted --------------------------------------------------------
@pytest.mark.story("5.2", ac=2)
def test_previous_assignment_is_kept_in_history_not_deleted(coordinator_client, db: Session):
    before = _history_row_count(db, Events.APPROVED)

    response = coordinator_client.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    assert response.status_code == 200, response.text
    assert _history_row_count(db, Events.APPROVED) == before + 1
    closed = db.execute(
        text(
            "SELECT coordinator_id, unassigned_at FROM event_coordinator_assignments"
            " WHERE event_id = :e AND unassigned_at IS NOT NULL ORDER BY assigned_at DESC LIMIT 1"
        ),
        {"e": Events.APPROVED},
    ).one()
    assert closed.coordinator_id == Users.COORDINATOR.id
    assert closed.unassigned_at is not None


# --- AC3: atomic save, and access checks use the new assignment immediately -------------------
@pytest.mark.story("5.2", ac=3)
def test_reassignment_failure_rolls_back_the_whole_change(
    coordinator_client, db: Session, monkeypatch
):
    """If writing the history entry fails unexpectedly, the pointer must not have moved either -
    the two are "saved together" (AC3)."""
    before_pointer = db.execute(
        text("SELECT assigned_coordinator_id FROM events WHERE id = :e"), {"e": Events.APPROVED}
    ).scalar()

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated failure writing the history entry")

    monkeypatch.setattr(coordination_service, "record_audit", _boom)

    with pytest.raises(RuntimeError):
        coordinator_client.put(
            f"/events/{Events.APPROVED}/coordinator",
            json={"coordinator_id": str(Users.COORDINATOR_2.id)},
        )
    db.rollback()  # mirrors app.db.get_db's real teardown; see test_auto_assign_coordinator.py

    after_pointer = db.execute(
        text("SELECT assigned_coordinator_id FROM events WHERE id = :e"), {"e": Events.APPROVED}
    ).scalar()
    assert after_pointer == before_pointer
    assert _open_assignment_row(db, Events.APPROVED).coordinator_id == before_pointer


@pytest.mark.story("5.2", ac=3)
def test_new_coordinator_can_act_on_the_event_right_after_reassignment(
    coordinator_client, login_as
):
    coordinator_client.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    carl = login_as(Users.COORDINATOR_2)
    response = carl.patch(
        f"/events/{Events.APPROVED}/routine-information",
        json={"internal_notes": "Handed off to me"},
    )

    assert response.status_code == 200, response.text


# --- AC4: eligible list -----------------------------------------------------------------------
@pytest.mark.story("5.2", ac=4)
def test_only_active_event_coordinators_are_offered_to_reassign_to(coordinator_client, db: Session):
    inactive = make_user(db, role="EVENT_COORDINATOR", is_active=False)

    response = coordinator_client.get(f"/coordinators?exclude_event_id={Events.APPROVED}")

    assert response.status_code == 200, response.text
    offered = {u["id"] for u in response.json()}
    assert str(inactive.id) not in offered


@pytest.mark.story("5.2", ac=4)
def test_current_coordinator_is_excluded_from_the_reassignment_list(coordinator_client):
    """Events.APPROVED is assigned to Chloe (COORDINATOR)."""
    response = coordinator_client.get(f"/coordinators?exclude_event_id={Events.APPROVED}")

    assert response.status_code == 200, response.text
    offered = {u["id"] for u in response.json()}
    assert str(Users.COORDINATOR.id) not in offered
    assert str(Users.COORDINATOR_2.id) in offered


@pytest.mark.story("5.2", ac=4)
def test_reassigning_to_an_inactive_or_non_coordinator_is_refused(coordinator_client, db: Session):
    inactive = make_user(db, role="EVENT_COORDINATOR", is_active=False)

    response = coordinator_client.put(
        f"/events/{Events.APPROVED}/coordinator", json={"coordinator_id": str(inactive.id)}
    )

    assert response.status_code == 422, response.text
    assert _open_assignment_row(db, Events.APPROVED).coordinator_id == Users.COORDINATOR.id


# --- AC5: bookings and clarifications follow the event ----------------------------------------
@pytest.mark.story("5.2", ac=5)
def test_pending_booking_request_follows_the_new_coordinator(coordinator_client, login_as):
    """Events.APPROVED is PLANNING - a bookable status. Reassigning it must move who may raise a
    booking request for it, the same way it moves who may decide the event itself."""
    coordinator_client.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    chloe = login_as(Users.COORDINATOR)
    still_offered_to_chloe = chloe.get("/bookings/reference-data").json()
    assert str(Events.APPROVED) not in {e["id"] for e in still_offered_to_chloe["events"]}

    carl = login_as(Users.COORDINATOR_2)
    offered_to_carl = carl.get("/bookings/reference-data").json()
    assert str(Events.APPROVED) in {e["id"] for e in offered_to_carl["events"]}


@pytest.mark.story("5.2", ac=5)
def test_clarification_thread_stays_visible_after_reassignment(
    coordinator_client, login_as, db: Session
):
    make_clarification(db, event_id=Events.APPROVED, author_id=Users.COORDINATOR.id)

    coordinator_client.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    carl = login_as(Users.COORDINATOR_2)
    response = carl.get(f"/events/{Events.APPROVED}/clarifications")
    assert response.status_code == 200, response.text
    assert len(response.json()) >= 1


# --- AC6: only the current coordinator may reassign --------------------------------------------
@pytest.mark.story("5.2", ac=6)
def test_a_different_coordinator_cannot_reassign_someone_elses_event(login_as, db: Session):
    """Events.APPROVED belongs to Chloe; Carl holds the Event Coordinator role too, but is not
    its current coordinator, so AC6 refuses him."""
    carl = login_as(Users.COORDINATOR_2)

    response = carl.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    assert response.status_code == 403, response.text
    assert _open_assignment_row(db, Events.APPROVED).coordinator_id == Users.COORDINATOR.id


@pytest.mark.story("5.2", ac=6)
@pytest.mark.parametrize(
    "user",
    [Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda u: u.role,
)
def test_non_coordinator_roles_cannot_reassign(login_as, user):
    actor = login_as(user)

    response = actor.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    assert response.status_code == 403, response.text


@pytest.mark.story("5.2", ac=6)
def test_previous_coordinator_immediately_loses_all_assignment_rights(coordinator_client, login_as):
    coordinator_client.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    chloe = login_as(Users.COORDINATOR)
    reassign_again = chloe.put(
        f"/events/{Events.APPROVED}/coordinator", json={"coordinator_id": str(Users.COORDINATOR.id)}
    )
    edit_routine = chloe.patch(
        f"/events/{Events.APPROVED}/routine-information",
        json={"internal_notes": "Trying to keep it"},
    )

    assert reassign_again.status_code == 403, reassign_again.text
    assert edit_routine.status_code == 403, edit_routine.text


@pytest.mark.story("5.2", ac=6)
def test_signed_out_cannot_reassign(client):
    response = client.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    assert response.status_code == 401, response.text


# --- AC7: concurrent reassignment ---------------------------------------------------------------
@pytest.mark.story("5.2", ac=7)
def test_second_reassignment_against_a_stale_assignment_is_refused(db: Session, monkeypatch):
    """Two reassignments 'at the same time' (e.g. a double submit) both read Chloe as current
    before either writes: Chloe -> Carl, and, from a second tab, Chloe -> Dana. The second write
    must be refused rather than silently overwrite the first.

    A single test session can't host two genuinely overlapping transactions (see the advisory-lock
    test in test_auto_assign_coordinator.py for the same limitation and why this repo tests the
    guard mechanism directly instead). The interleaving is injected deterministically: the moment
    the reassignment-in-progress reads "who is current" via ``current_assignment``, a second,
    already-authorised reassignment (Chloe -> Carl) is made and committed first, simulating the
    other request winning the race.

    Uses the seeded Events.APPROVED rather than a hand-built event: ``make_event`` sets
    ``assigned_coordinator_id`` on the event row directly but does not create a matching open
    ``event_coordinator_assignments`` row, which ``current_assignment`` reads - the mismatch
    would make the interloper's own (legitimate) reassignment spuriously fail this guard, since
    there would be no history row to match against.
    """
    event_id = Events.APPROVED
    chloe = db.get(User, Users.COORDINATOR.id)
    dana = make_user(db, role="EVENT_COORDINATOR", full_name="Dana Coordinator")

    real_current_assignment = coordination_service.current_assignment
    interloper_has_run = False

    def _interloper_wins_first(db_, event_id_):
        nonlocal interloper_has_run
        result = real_current_assignment(db_, event_id_)
        if not interloper_has_run:
            interloper_has_run = True
            coordination_service.assign_coordinator(
                db_,
                event_id_,
                AssignCoordinatorIn(coordinator_id=Users.COORDINATOR_2.id),
                actor=chloe,
            )
        return result

    monkeypatch.setattr(coordination_service, "current_assignment", _interloper_wins_first)

    with pytest.raises(coordination_service.AssignmentChanged):
        coordination_service.assign_coordinator(
            db, event_id, AssignCoordinatorIn(coordinator_id=dana.id), actor=chloe
        )

    monkeypatch.undo()
    winner = coordination_service.current_assignment(db, event_id)
    assert winner.coordinator_id == Users.COORDINATOR_2.id


@pytest.mark.story("5.2", ac=7)
def test_a_refused_reassignment_leaves_history_and_pointer_unchanged(db: Session, monkeypatch):
    """See the previous test's docstring for why Events.APPROVED (a fully-seeded event, with a
    real open assignment row) is used rather than a hand-built one."""
    event_id = Events.APPROVED
    chloe = db.get(User, Users.COORDINATOR.id)
    dana = make_user(db, role="EVENT_COORDINATOR", full_name="Dana Coordinator 2")

    real_current_assignment = coordination_service.current_assignment
    interloper_has_run = False

    def _interloper_wins_first(db_, event_id_):
        nonlocal interloper_has_run
        result = real_current_assignment(db_, event_id_)
        if not interloper_has_run:
            interloper_has_run = True
            coordination_service.assign_coordinator(
                db_,
                event_id_,
                AssignCoordinatorIn(coordinator_id=Users.COORDINATOR_2.id),
                actor=chloe,
            )
        return result

    monkeypatch.setattr(coordination_service, "current_assignment", _interloper_wins_first)
    before = _history_row_count(db, event_id)

    with pytest.raises(coordination_service.AssignmentChanged):
        coordination_service.assign_coordinator(
            db, event_id, AssignCoordinatorIn(coordinator_id=dana.id), actor=chloe
        )

    monkeypatch.undo()
    # exactly one new row from the interloper's own (legitimate) reassignment - none from the
    # refused attempt
    assert _history_row_count(db, event_id) == before + 1
    assert _open_assignment_row(db, event_id).coordinator_id == Users.COORDINATOR_2.id
