"""Story 5.2 - be: reassign a coordinator-holding event to a different coordinator.

Story 5.6 replaced 5.2 AC1 and AC6's first sentence (Q16, CL-144): only the Event Coordinator Lead
reassigns, naming the coordinator they saw (``expected_coordinator_id``), and coordinators are
refused. The tests for what was replaced went with it - 5.6's own cases, in
test_lead_reassign_coordinator.py, prove who may reassign, the notifications and every active
status - as story 5.4 did for 5.1's round robin (#107). The reassignments below are the Lead's.

What remains true of 5.2, and is tested here:
AC2  The previous assignment is kept in the event's history.
AC3  The assignment change and its history entry are saved together, and access checks use the
     new assignment immediately. (The event page's Reassign action is now 5.6's, in
     tests/e2e/coordinator-reassignment.spec.ts.)
AC4  Only active Event Coordinators are offered, and the current coordinator is excluded.
AC5  Pending booking requests and clarification threads move with the event. (Change requests
     are 5.6 AC4's, in test_lead_reassign_coordinator.py.)
AC6  (its second sentence) The previous coordinator loses assignment access immediately.
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
from tests.support.seed import Bookings, Events, Users


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


# --- AC2: history is kept, not deleted --------------------------------------------------------
@pytest.mark.story("5.2", ac=2)
def test_previous_assignment_is_kept_in_history_not_deleted(login_as, db: Session):
    before = _history_row_count(db, Events.APPROVED)

    response = login_as(Users.LEAD).put(
        f"/events/{Events.APPROVED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
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
def test_reassignment_failure_rolls_back_the_whole_change(login_as, db: Session, monkeypatch):
    """If writing the history entry fails unexpectedly, the pointer must not have moved either -
    the two are "saved together" (AC3)."""
    before_pointer = db.execute(
        text("SELECT assigned_coordinator_id FROM events WHERE id = :e"), {"e": Events.APPROVED}
    ).scalar()

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated failure writing the history entry")

    lead = login_as(Users.LEAD)
    monkeypatch.setattr(coordination_service, "record_audit", _boom)

    with pytest.raises(RuntimeError):
        lead.put(
            f"/events/{Events.APPROVED}/coordinator",
            json={
                "coordinator_id": str(Users.COORDINATOR_2.id),
                "expected_coordinator_id": str(Users.COORDINATOR.id),
            },
        )
    # A real request's session is closed after the error, discarding its work; rolling back here
    # does the same for the test's session before the pointer is read again.
    db.rollback()

    after_pointer = db.execute(
        text("SELECT assigned_coordinator_id FROM events WHERE id = :e"), {"e": Events.APPROVED}
    ).scalar()
    assert after_pointer == before_pointer
    assert _open_assignment_row(db, Events.APPROVED).coordinator_id == before_pointer


@pytest.mark.story("5.2", ac=3)
def test_new_coordinator_can_act_on_the_event_right_after_reassignment(login_as):
    login_as(Users.LEAD).put(
        f"/events/{Events.APPROVED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
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
def test_reassigning_to_an_inactive_or_non_coordinator_is_refused(login_as, db: Session):
    inactive = make_user(db, role="EVENT_COORDINATOR", is_active=False)

    response = login_as(Users.LEAD).put(
        f"/events/{Events.APPROVED}/coordinator",
        json={
            "coordinator_id": str(inactive.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    assert response.status_code == 422, response.text
    assert _open_assignment_row(db, Events.APPROVED).coordinator_id == Users.COORDINATOR.id


# --- AC5: bookings and clarifications follow the event ----------------------------------------
@pytest.mark.story("5.2", ac=5)
def test_pending_booking_request_follows_the_new_coordinator(login_as):
    """Events.APPROVED is PLANNING - a bookable status. Reassigning it must move who may raise a
    booking request for it, the same way it moves who may decide the event itself."""
    login_as(Users.LEAD).put(
        f"/events/{Events.APPROVED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    chloe = login_as(Users.COORDINATOR)
    still_offered_to_chloe = chloe.get("/bookings/reference-data").json()
    assert str(Events.APPROVED) not in {e["id"] for e in still_offered_to_chloe["events"]}

    carl = login_as(Users.COORDINATOR_2)
    offered_to_carl = carl.get("/bookings/reference-data").json()
    assert str(Events.APPROVED) in {e["id"] for e in offered_to_carl["events"]}


@pytest.mark.story("5.2", ac=5)
def test_an_existing_pending_booking_stays_tied_to_the_event_after_reassignment(login_as):
    """The previous test proves *future* eligibility moves; this proves the request Events.APPROVED
    already carries (Bookings.PENDING_SEMINAR_ROOM, seeded PENDING) is not hidden, detached or
    otherwise disturbed by the reassignment - it is still readable through the event's own
    history for whoever the new assignment holds BOOKINGS_READ."""
    login_as(Users.LEAD).put(
        f"/events/{Events.APPROVED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    carl = login_as(Users.COORDINATOR_2)
    response = carl.get(f"/bookings/for-event/{Events.APPROVED}")
    assert response.status_code == 200, response.text
    assert str(Bookings.PENDING_SEMINAR_ROOM) in {b["id"] for b in response.json()}


@pytest.mark.story("5.2", ac=5)
def test_clarification_thread_stays_visible_after_reassignment(login_as, db: Session):
    make_clarification(db, event_id=Events.APPROVED, author_id=Users.COORDINATOR.id)

    login_as(Users.LEAD).put(
        f"/events/{Events.APPROVED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    carl = login_as(Users.COORDINATOR_2)
    response = carl.get(f"/events/{Events.APPROVED}/clarifications")
    assert response.status_code == 200, response.text
    assert len(response.json()) >= 1


# --- AC6, its second sentence: the previous coordinator loses assignment access immediately --
@pytest.mark.story("5.2", ac=6)
def test_previous_coordinator_immediately_loses_all_assignment_rights(login_as):
    """Once the Lead hands Events.APPROVED to Carl, Chloe can no longer edit it - she is no longer
    its coordinator. Nor can she reassign it, as no coordinator can since 5.6."""
    login_as(Users.LEAD).put(
        f"/events/{Events.APPROVED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
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


# --- AC7: concurrent reassignment ---------------------------------------------------------------
@pytest.mark.story("5.2", ac=7)
def test_second_reassignment_against_a_stale_assignment_is_refused(db: Session, monkeypatch):
    """Two reassignments 'at the same time' (e.g. a double submit) both read Chloe as current
    before either writes: Chloe -> Carl, and, from a second tab, Chloe -> Dana. Since 5.6 both are
    the Lead's. The second write must be refused rather than silently overwrite the first.

    A single test session can't host two genuinely overlapping transactions (5.4's
    test_two_leads_assigning_at_once_write_one needs real sessions, its own commits and a clean-up
    for that), so this tests the guard mechanism directly. The interleaving is injected
    deterministically: the moment
    the reassignment-in-progress reads "who is current" via ``current_assignment``, a second,
    already-authorised reassignment (Chloe -> Carl) is made and committed first, simulating the
    other request winning the race. Committed inside this request's own transaction, it gets past
    the row lock 5.6 added, which a real second request would wait on, and is refused by the read
    check (``_refuse_if_changed``). So what this reaches is the guarded UPDATE, the backstop
    behind that check.

    Uses the seeded Events.APPROVED rather than a hand-built event: ``make_event`` sets
    ``assigned_coordinator_id`` on the event row directly but does not create a matching open
    ``event_coordinator_assignments`` row, which ``current_assignment`` reads - the mismatch
    would make the interloper's own (legitimate) reassignment spuriously fail this guard, since
    there would be no history row to match against.
    """
    event_id = Events.APPROVED
    lead = db.get(User, Users.LEAD.id)
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
                AssignCoordinatorIn(
                    coordinator_id=Users.COORDINATOR_2.id,
                    expected_coordinator_id=Users.COORDINATOR.id,
                ),
                actor=lead,
            )
        return result

    monkeypatch.setattr(coordination_service, "current_assignment", _interloper_wins_first)

    with pytest.raises(coordination_service.AssignmentChanged):
        coordination_service.assign_coordinator(
            db,
            event_id,
            AssignCoordinatorIn(
                coordinator_id=dana.id, expected_coordinator_id=Users.COORDINATOR.id
            ),
            actor=lead,
        )

    monkeypatch.undo()
    winner = coordination_service.current_assignment(db, event_id)
    assert winner.coordinator_id == Users.COORDINATOR_2.id


@pytest.mark.story("5.2", ac=7)
def test_a_refused_reassignment_leaves_history_and_pointer_unchanged(db: Session, monkeypatch):
    """See the previous test's docstring for why Events.APPROVED (a fully-seeded event, with a
    real open assignment row) is used rather than a hand-built one."""
    event_id = Events.APPROVED
    lead = db.get(User, Users.LEAD.id)
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
                AssignCoordinatorIn(
                    coordinator_id=Users.COORDINATOR_2.id,
                    expected_coordinator_id=Users.COORDINATOR.id,
                ),
                actor=lead,
            )
        return result

    monkeypatch.setattr(coordination_service, "current_assignment", _interloper_wins_first)
    before = _history_row_count(db, event_id)

    with pytest.raises(coordination_service.AssignmentChanged):
        coordination_service.assign_coordinator(
            db,
            event_id,
            AssignCoordinatorIn(
                coordinator_id=dana.id, expected_coordinator_id=Users.COORDINATOR.id
            ),
            actor=lead,
        )

    monkeypatch.undo()
    # exactly one new row from the interloper's own (legitimate) reassignment - none from the
    # refused attempt
    assert _history_row_count(db, event_id) == before + 1
    assert _open_assignment_row(db, event_id).coordinator_id == Users.COORDINATOR_2.id


@pytest.mark.story("5.2", ac=7)
def test_a_stale_reassignment_over_http_is_refused_with_409(login_as, db: Session, monkeypatch):
    """The two tests above prove the guard by calling ``assign_coordinator`` directly and
    catching ``AssignmentChanged`` as a Python exception - neither exercises the router's own
    translation of that exception into an HTTP response. This drives the identical race through
    the real ``PUT /events/{event_id}/coordinator`` endpoint instead, to prove that translation
    (409, not 500 or an unhandled exception) actually happens."""
    event_id = Events.APPROVED
    lead = db.get(User, Users.LEAD.id)
    dana = make_user(db, role="EVENT_COORDINATOR", full_name="Dana Coordinator HTTP")

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
                AssignCoordinatorIn(
                    coordinator_id=Users.COORDINATOR_2.id,
                    expected_coordinator_id=Users.COORDINATOR.id,
                ),
                actor=lead,
            )
        return result

    monkeypatch.setattr(coordination_service, "current_assignment", _interloper_wins_first)

    response = login_as(Users.LEAD).put(
        f"/events/{event_id}/coordinator",
        json={"coordinator_id": str(dana.id), "expected_coordinator_id": str(Users.COORDINATOR.id)},
    )

    assert response.status_code == 409, response.text
