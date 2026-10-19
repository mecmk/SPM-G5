"""Story 5.6 - be: the Event Coordinator Lead reassigns an event to a different coordinator.

Happy path
AC1  On an event that is not completed, cancelled or rejected, the Lead can choose another active
     Event Coordinator. The change records who made it and when, and the event moves to the new
     coordinator's list (6.1).
AC2  Both coordinators and the organiser are notified (20.1). The previous assignment is kept in
     the event's history.
Boundary
AC3  Only active Event Coordinators are offered, and the current coordinator is not in the list.
Edge
AC4  Pending booking requests, change requests and clarification threads move with the event.
Permission
AC5  Only the Lead can reassign. Event Coordinators can no longer reassign their own events: the
     API refuses it (403) (replaces 5.2 AC1 and AC6; Q16). The previous coordinator loses access
     immediately.
Conflict
AC6  If two reassignments are made at the same time, the second is refused because the assignment
     has changed.

Design decisions at Checkpoint 2 these tests rely on:
* 1A The existing ``PUT /events/{event_id}/coordinator`` is tightened to ``events:assign``; there
  is no second endpoint.
* 2A A reassignment names the coordinator the Lead saw, ``expected_coordinator_id``. Left out, the
  request is 5.4's assign, which an assigned event still refuses (5.4 AC8, tested there).
* Choosing the current coordinator stays 5.1's no-op: nothing is written and nobody is told.

Excluded, with reason:
* The Reassign action on the event page and the overview, its removal for coordinators, and how a
  refusal reads, are UI: tests/e2e/coordinator-reassignment.spec.ts.
* Assigning an unassigned event is 5.4's (test_unassigned_queue.py), unchanged.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.common.audit import AuditLog
from app.coordination import service as coordination_service
from app.coordination.models import EventCoordinatorAssignment
from app.coordination.schemas import AssignCoordinatorIn
from app.events.models import Event, EventStatus
from app.notifications.models import Notification
from tests.support.factories import make_clarification, make_event, make_user
from tests.support.seed import Bookings, Events, Users

COORDINATOR_ROLE = "EVENT_COORDINATOR"
LEAD_ROLE = "EVENT_COORDINATOR_LEAD"
ACTIVE_STATUSES = (
    EventStatus.UNDER_REVIEW,
    EventStatus.CLARIFICATION_REQUESTED,
    EventStatus.PLANNING,
    EventStatus.AWAITING_SAFETY_CHECK,
    EventStatus.CONFIRMED,
)
REASSIGNED_TYPES = (
    "EVENT_REASSIGNED_FROM",
    "EVENT_REASSIGNED_TO",
    "EVENT_REASSIGNED_ORGANISER",
)
# The server's sentence for a reassignment whose coordinator is no longer the one named (AC6).
_CHANGED = "This event's coordinator changed just now. Reload the event and try again."
# Every role but the Lead's, so a role added later is refused here without editing this list.
REFUSED_ROLES = [user for user in Users.ONE_PER_ROLE if user != Users.LEAD]


# --- helpers ---------------------------------------------------------------------------------
def _assigned_event(db: Session, coordinator_id: uuid.UUID, **overrides) -> Event:
    """An event with ``coordinator_id`` as its current coordinator, recorded the way an
    assignment is: the pointer on the event and an open row in its assignment history (which
    ``current_assignment`` reads). Dated safely in the future."""
    starts_at = overrides.pop("starts_at", datetime.now(UTC) + timedelta(days=90))
    event = make_event(
        db,
        status=overrides.pop("status", EventStatus.UNDER_REVIEW),
        starts_at=starts_at,
        ends_at=overrides.pop("ends_at", starts_at + timedelta(hours=6)),
        assigned_coordinator_id=coordinator_id,
        **overrides,
    )
    db.add(EventCoordinatorAssignment(event_id=event.id, coordinator_id=coordinator_id))
    db.flush()
    return event


def _reassign(client, event_id, coordinator_id, *, expected):
    """The Lead's reassignment (2A): hand the event to ``coordinator_id``, having seen
    ``expected`` as its coordinator."""
    return client.put(
        f"/events/{event_id}/coordinator",
        json={"coordinator_id": str(coordinator_id), "expected_coordinator_id": str(expected)},
    )


def _pointer(db: Session, event_id):
    return db.execute(
        text("SELECT assigned_coordinator_id FROM events WHERE id = :e"), {"e": event_id}
    ).scalar()


def _open_assignment(db: Session, event_id):
    return db.execute(
        text(
            "SELECT coordinator_id, assigned_by_id, assigned_at FROM event_coordinator_assignments"
            " WHERE event_id = :e AND unassigned_at IS NULL"
        ),
        {"e": event_id},
    ).one_or_none()


def _history(db: Session, event_id) -> list:
    """Every assignment the event has had, oldest first."""
    return db.execute(
        text(
            "SELECT coordinator_id, assigned_by_id, unassigned_at"
            " FROM event_coordinator_assignments WHERE event_id = :e ORDER BY assigned_at, id"
        ),
        {"e": event_id},
    ).all()


def _reassignment_notices(db: Session, event_id) -> dict[str, set[uuid.UUID]]:
    """Who was told of a reassignment of the event, by notification type."""
    rows = db.execute(
        text(
            "SELECT notification_type, recipient_id FROM notifications"
            " WHERE event_id = :e AND notification_type LIKE 'EVENT_REASSIGNED%'"
        ),
        {"e": event_id},
    ).all()
    notices: dict[str, set[uuid.UUID]] = {}
    for notification_type, recipient_id in rows:
        notices.setdefault(notification_type, set()).add(recipient_id)
    return notices


def _organiser_id(db: Session, event_id):
    return db.execute(
        text("SELECT organiser_id FROM events WHERE id = :e"), {"e": event_id}
    ).scalar()


def _assigned_ids(client) -> set[str]:
    """The ids on the signed-in coordinator's own list (6.1)."""
    response = client.get("/events/assigned-to-me")
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["items"]}


# --- AC1: the Lead reassigns -----------------------------------------------------------------
@pytest.mark.story("5.6", ac=1)
def test_the_lead_reassigns_an_event_to_another_active_coordinator(login_as, db: Session):
    """Events.APPROVED is in Planning with Chloe. The Lead hands it to Carl; the change records
    the Lead as who made it, and when."""
    response = _reassign(
        login_as(Users.LEAD), Events.APPROVED, Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["coordinator_id"] == str(Users.COORDINATOR_2.id)
    assert body["assigned_by_id"] == str(Users.LEAD.id)
    assert body["assigned_at"] is not None
    assert _pointer(db, Events.APPROVED) == Users.COORDINATOR_2.id
    row = _open_assignment(db, Events.APPROVED)
    assert row.coordinator_id == Users.COORDINATOR_2.id
    assert row.assigned_by_id == Users.LEAD.id


@pytest.mark.story("5.6", ac=1)
@pytest.mark.parametrize("status", ACTIVE_STATUSES)
def test_the_lead_reassigns_an_event_in_any_active_status(login_as, db: Session, status):
    """Every status between submission and closure can be reassigned."""
    event = _assigned_event(db, Users.COORDINATOR.id, status=status)

    response = _reassign(
        login_as(Users.LEAD), event.id, Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id
    )

    assert response.status_code == 200, response.text
    assert _pointer(db, event.id) == Users.COORDINATOR_2.id


@pytest.mark.story("5.6", ac=1)
@pytest.mark.parametrize(
    "status", [EventStatus.COMPLETED, EventStatus.CANCELLED, EventStatus.REJECTED]
)
def test_a_closed_event_cannot_be_reassigned(login_as, db: Session, status):
    """A closed event needs no owner: it is refused (409) naming its status, and keeps Chloe."""
    event = _assigned_event(db, Users.COORDINATOR.id, status=status)

    response = _reassign(
        login_as(Users.LEAD), event.id, Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id
    )

    assert response.status_code == 409, response.text
    assert status in response.json()["detail"]
    assert _pointer(db, event.id) == Users.COORDINATOR.id
    assert len(_history(db, event.id)) == 1


@pytest.mark.story("5.6", ac=1)
def test_a_draft_cannot_be_reassigned(login_as, db: Session):
    """A draft has never been handed over, so it has no coordinator to reassign from: Olivia's
    seeded draft is refused (409) naming its status, and stays unassigned."""
    response = _reassign(
        login_as(Users.LEAD), Events.DRAFT, Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id
    )

    assert response.status_code == 409, response.text
    assert EventStatus.DRAFT in response.json()["detail"]
    assert _pointer(db, Events.DRAFT) is None


@pytest.mark.story("5.6", ac=1)
def test_reassigning_an_unknown_event_is_not_found(login_as):
    response = _reassign(
        login_as(Users.LEAD), uuid.uuid4(), Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id
    )

    assert response.status_code == 404, response.text


@pytest.mark.story("5.6", ac=1)
def test_a_reassigned_event_moves_to_the_new_coordinators_list(login_as, db: Session):
    """6.1: the event leaves Chloe's own list and joins Carl's on their next read."""
    event = _assigned_event(db, Users.COORDINATOR.id, status=EventStatus.PLANNING)
    assert str(event.id) in _assigned_ids(login_as(Users.COORDINATOR))

    reassigned = _reassign(
        login_as(Users.LEAD), event.id, Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id
    )

    assert reassigned.status_code == 200, reassigned.text
    assert str(event.id) not in _assigned_ids(login_as(Users.COORDINATOR))
    assert str(event.id) in _assigned_ids(login_as(Users.COORDINATOR_2))


@pytest.mark.story("5.6", ac=1)
def test_the_lead_reassigns_a_deactivated_coordinators_event(login_as, db: Session):
    """The reason 5.5 flags a deactivated coordinator who still holds events: the Lead hands each
    one to someone active."""
    gone = make_user(db, role=COORDINATOR_ROLE, full_name="Departed Coordinator", is_active=False)
    event = _assigned_event(db, gone.id)

    response = _reassign(login_as(Users.LEAD), event.id, Users.COORDINATOR_2.id, expected=gone.id)

    assert response.status_code == 200, response.text
    assert _pointer(db, event.id) == Users.COORDINATOR_2.id


# --- AC2: notified, and the history kept -----------------------------------------------------
@pytest.mark.story("5.6", ac=2)
def test_reassignment_notifies_both_coordinators_and_the_organiser(login_as, db: Session):
    """20.1: the previous coordinator, the new one and the organiser are each told - the
    previous coordinator too, now that someone else makes the change. Nobody is told of their own
    action, so the Lead is not."""
    response = _reassign(
        login_as(Users.LEAD), Events.APPROVED, Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id
    )

    assert response.status_code == 200, response.text
    assert _reassignment_notices(db, Events.APPROVED) == {
        "EVENT_REASSIGNED_FROM": {Users.COORDINATOR.id},
        "EVENT_REASSIGNED_TO": {Users.COORDINATOR_2.id},
        "EVENT_REASSIGNED_ORGANISER": {_organiser_id(db, Events.APPROVED)},
    }


@pytest.mark.story("5.6", ac=2)
def test_the_previous_assignment_is_kept_in_the_events_history(login_as, db: Session):
    """Chloe's assignment is closed, not deleted, and the Lead's opens after it."""
    event = _assigned_event(db, Users.COORDINATOR.id)

    response = _reassign(
        login_as(Users.LEAD), event.id, Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id
    )

    assert response.status_code == 200, response.text
    previous, current = _history(db, event.id)
    assert previous.coordinator_id == Users.COORDINATOR.id
    assert previous.unassigned_at is not None
    assert current.coordinator_id == Users.COORDINATOR_2.id
    assert current.assigned_by_id == Users.LEAD.id
    assert current.unassigned_at is None


# --- AC3: who can be chosen ------------------------------------------------------------------
@pytest.mark.story("5.6", ac=3)
def test_the_lead_is_offered_only_other_active_coordinators_with_their_counts(
    login_as, db: Session
):
    """The Lead's picker for Events.APPROVED: Carl, not Chloe (its coordinator), not an inactive
    coordinator, and Carl with his number of active events (5.4 AC3) - one more after he is given
    another."""
    inactive = make_user(db, role=COORDINATOR_ROLE, is_active=False)
    lead = login_as(Users.LEAD)
    path = f"/coordinators?exclude_event_id={Events.APPROVED}"
    carls_count = {o["id"]: o for o in lead.get(path).json()}[str(Users.COORDINATOR_2.id)][
        "active_event_count"
    ]
    _assigned_event(db, Users.COORDINATOR_2.id, status=EventStatus.PLANNING)

    response = lead.get(path)

    assert response.status_code == 200, response.text
    offered = {option["id"]: option for option in response.json()}
    assert str(Users.COORDINATOR.id) not in offered
    assert str(inactive.id) not in offered
    assert offered[str(Users.COORDINATOR_2.id)]["active_event_count"] == carls_count + 1


@pytest.mark.story("5.6", ac=3)
@pytest.mark.parametrize("target", ["an inactive coordinator", "an organiser", "nobody"])
def test_reassigning_to_someone_who_cannot_coordinate_is_refused(login_as, db: Session, target):
    """Only an active Event Coordinator can be chosen (422), and the refusal says why in a sentence
    of its own - not a malformed body. The event keeps Chloe."""
    coordinator_id, reason = {
        "an inactive coordinator": lambda: (
            make_user(db, role=COORDINATOR_ROLE, is_active=False).id,
            "is no longer an active user",
        ),
        "an organiser": lambda: (Users.ORGANISER.id, "can be assigned"),
        "nobody": lambda: (uuid.uuid4(), "No user with id"),
    }[target]()

    response = _reassign(
        login_as(Users.LEAD), Events.APPROVED, coordinator_id, expected=Users.COORDINATOR.id
    )

    assert response.status_code == 422, response.text
    assert reason in response.json()["detail"]
    assert _pointer(db, Events.APPROVED) == Users.COORDINATOR.id


@pytest.mark.story("5.6", ac=3)
def test_reassigning_to_the_current_coordinator_changes_nothing(login_as, db: Session):
    """The picker never offers the current coordinator; a direct request naming them is 5.1's
    no-op: nothing is written to the history and nobody is told."""
    before = _history(db, Events.APPROVED)

    response = _reassign(
        login_as(Users.LEAD), Events.APPROVED, Users.COORDINATOR.id, expected=Users.COORDINATOR.id
    )

    assert response.status_code == 200, response.text
    assert response.json()["coordinator_id"] == str(Users.COORDINATOR.id)
    assert _history(db, Events.APPROVED) == before
    assert _reassignment_notices(db, Events.APPROVED) == {}


# --- AC4: what moves with the event ----------------------------------------------------------
@pytest.mark.story("5.6", ac=4)
def test_a_pending_booking_request_moves_with_the_event(login_as):
    """Events.APPROVED's pending request for the Seminar Room can be withdrawn only by the event's
    coordinator (12.2 AC6): after the Lead hands the event to Carl, Chloe no longer can and Carl
    can."""
    reassigned = _reassign(
        login_as(Users.LEAD), Events.APPROVED, Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id
    )
    assert reassigned.status_code == 200, reassigned.text

    by_chloe = login_as(Users.COORDINATOR).post(
        f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/withdraw"
    )
    by_carl = login_as(Users.COORDINATOR_2).post(
        f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/withdraw"
    )

    assert by_chloe.status_code == 403, by_chloe.text
    assert by_carl.status_code == 200, by_carl.text


@pytest.mark.story("5.6", ac=4)
def test_a_pending_change_request_moves_with_the_event(login_as):
    """Omar asks to change Events.APPROVED's attendance (19.1). After the Lead hands the event to
    Carl, the pending request is Carl's to see, not Chloe's."""
    raised = login_as(Users.ORGANISER_2).post(
        f"/events/{Events.APPROVED}/change-requests",
        json={
            "field": "expected_attendance",
            "proposed": 360,
            "reason": "More guests confirmed.",
        },
    )
    assert raised.status_code == 201, raised.text

    reassigned = _reassign(
        login_as(Users.LEAD), Events.APPROVED, Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id
    )
    assert reassigned.status_code == 200, reassigned.text

    for_carl = login_as(Users.COORDINATOR_2).get(f"/events/{Events.APPROVED}/change-requests")
    for_chloe = login_as(Users.COORDINATOR).get(f"/events/{Events.APPROVED}/change-requests")

    assert for_carl.status_code == 200, for_carl.text
    assert raised.json()["id"] in {request["id"] for request in for_carl.json()}
    assert for_chloe.status_code == 403, for_chloe.text


@pytest.mark.story("5.6", ac=4)
def test_a_pending_change_request_is_decided_by_the_new_coordinator(login_as):
    """19.2: the pending request moves to Carl's decision queue and leaves Chloe's, and only Carl
    can decide it - Chloe's rejection is refused (403), Carl's is taken."""
    raised = login_as(Users.ORGANISER_2).post(
        f"/events/{Events.APPROVED}/change-requests",
        json={"field": "expected_attendance", "proposed": 360, "reason": "More guests confirmed."},
    )
    assert raised.status_code == 201, raised.text
    request_id = raised.json()["id"]
    reject_path = f"/events/{Events.APPROVED}/change-requests/{request_id}/reject"
    reason = {"reason": "The Grand Hall cannot hold that many."}

    reassigned = _reassign(
        login_as(Users.LEAD), Events.APPROVED, Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id
    )
    assert reassigned.status_code == 200, reassigned.text

    chloe = login_as(Users.COORDINATOR)
    assert request_id not in {entry["id"] for entry in chloe.get("/change-requests").json()}
    by_chloe = chloe.post(reject_path, json=reason)
    carl = login_as(Users.COORDINATOR_2)
    assert request_id in {entry["id"] for entry in carl.get("/change-requests").json()}
    by_carl = carl.post(reject_path, json=reason)

    assert by_chloe.status_code == 403, by_chloe.text
    assert by_carl.status_code == 200, by_carl.text


@pytest.mark.story("5.6", ac=4)
def test_the_clarification_thread_moves_with_the_event(login_as, db: Session):
    """The conversation Chloe started is Carl's to read once the event is his, not Chloe's."""
    make_clarification(db, event_id=Events.APPROVED, author_id=Users.COORDINATOR.id)

    reassigned = _reassign(
        login_as(Users.LEAD), Events.APPROVED, Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id
    )
    assert reassigned.status_code == 200, reassigned.text

    for_carl = login_as(Users.COORDINATOR_2).get(f"/events/{Events.APPROVED}/clarifications")
    for_chloe = login_as(Users.COORDINATOR).get(f"/events/{Events.APPROVED}/clarifications")

    assert for_carl.status_code == 200, for_carl.text
    assert len(for_carl.json()) >= 1
    assert for_chloe.status_code == 403, for_chloe.text


# --- AC5: only the Lead ----------------------------------------------------------------------
@pytest.mark.story("5.6", ac=5)
def test_an_event_coordinator_cannot_reassign_even_their_own_event(login_as, db: Session):
    """Q16, replacing 5.2 AC1 and AC6: Chloe holds Events.APPROVED, and is refused (403) all the
    same. Nothing changes."""
    before = _history(db, Events.APPROVED)

    response = login_as(Users.COORDINATOR).put(
        f"/events/{Events.APPROVED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    assert response.status_code == 403, response.text
    assert _pointer(db, Events.APPROVED) == Users.COORDINATOR.id
    assert _history(db, Events.APPROVED) == before


@pytest.mark.story("5.6", ac=5)
@pytest.mark.parametrize("user", REFUSED_ROLES, ids=lambda u: u.role)
def test_only_the_lead_can_reassign(login_as, db: Session, user):
    """Every role but the Lead's is refused (403), the coordinators included."""
    response = _reassign(
        login_as(user), Events.APPROVED, Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id
    )

    assert response.status_code == 403, response.text
    assert _pointer(db, Events.APPROVED) == Users.COORDINATOR.id


@pytest.mark.story("5.6", ac=5)
def test_signing_in_is_required_to_reassign(client):
    response = _reassign(
        client, Events.APPROVED, Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id
    )

    assert response.status_code == 401, response.text


@pytest.mark.story("5.6", ac=5)
def test_the_previous_coordinator_loses_access_immediately(login_as):
    """The moment the Lead hands Events.APPROVED to Carl, Chloe can no longer edit it or read its
    clarifications - access is checked against the current assignment on every request."""
    reassigned = _reassign(
        login_as(Users.LEAD), Events.APPROVED, Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id
    )
    assert reassigned.status_code == 200, reassigned.text

    chloe = login_as(Users.COORDINATOR)
    edit = chloe.patch(
        f"/events/{Events.APPROVED}/routine-information",
        json={"internal_notes": "Trying to keep it"},
    )
    clarifications = chloe.get(f"/events/{Events.APPROVED}/clarifications")

    assert edit.status_code == 403, edit.text
    assert clarifications.status_code == 403, clarifications.text


# --- AC6: two at once ------------------------------------------------------------------------
@pytest.mark.story("5.6", ac=6)
def test_a_reassignment_from_a_stale_view_is_refused(login_as, db: Session):
    """Two Leads both saw Chloe. The first hands the event to Carl; the second, still naming
    Chloe, is refused (409) instead of taking Carl's event away. Nothing more is written, and
    nobody else is told."""
    dana = make_user(db, role=COORDINATOR_ROLE, full_name="Dana Coordinator")
    lead = login_as(Users.LEAD)
    first = _reassign(lead, Events.APPROVED, Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id)
    assert first.status_code == 200, first.text
    history = _history(db, Events.APPROVED)

    second = _reassign(lead, Events.APPROVED, dana.id, expected=Users.COORDINATOR.id)

    assert second.status_code == 409, second.text
    assert second.json()["detail"] == _CHANGED
    assert _pointer(db, Events.APPROVED) == Users.COORDINATOR_2.id
    assert _history(db, Events.APPROVED) == history
    assert dana.id not in _reassignment_notices(db, Events.APPROVED).get(
        "EVENT_REASSIGNED_TO", set()
    )


@pytest.mark.story("5.6", ac=6)
def test_a_reassignment_of_an_unassigned_event_is_refused(login_as, db: Session):
    """A reassignment names the coordinator the Lead saw; an event with none is 5.4's to assign,
    so naming one is refused as changed (409), and the event stays unassigned."""
    event = make_event(
        db,
        status=EventStatus.UNDER_REVIEW,
        starts_at=datetime.now(UTC) + timedelta(days=90),
        ends_at=datetime.now(UTC) + timedelta(days=90, hours=6),
        assigned_coordinator_id=None,
    )

    response = _reassign(
        login_as(Users.LEAD), event.id, Users.COORDINATOR_2.id, expected=Users.COORDINATOR.id
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == _CHANGED
    assert _pointer(db, event.id) is None


@pytest.mark.story("5.6", ac=6)
def test_two_leads_reassigning_at_once_write_one(engine):
    """Real concurrent transactions, so this test commits and cleans up after itself, as 5.4's
    race test does. Two Leads, both having seen Chloe, hand one event to two different
    coordinators at the same moment: exactly one reassignment is written, and the other is
    refused because the assignment changed."""
    with Session(engine) as session:
        event = _assigned_event(session, Users.COORDINATOR.id, name="Reassign Race")
        second_lead = make_user(session, role=LEAD_ROLE, full_name="Racing Lead")
        dana = make_user(session, role=COORDINATOR_ROLE, full_name="Racing Coordinator")
        session.commit()
        event_id, second_lead_id, dana_id = event.id, second_lead.id, dana.id
    start = threading.Barrier(2)

    def attempt(lead_id: uuid.UUID, coordinator_id: uuid.UUID) -> str:
        with Session(engine) as session:
            actor = session.get(User, lead_id)
            start.wait()
            try:
                coordination_service.assign_coordinator(
                    session,
                    event_id,
                    AssignCoordinatorIn(
                        coordinator_id=coordinator_id,
                        expected_coordinator_id=Users.COORDINATOR.id,
                    ),
                    actor=actor,
                )
            except coordination_service.AssignmentChanged:
                session.rollback()
                return "refused"
            return "reassigned"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(attempt, Users.LEAD.id, Users.COORDINATOR_2.id),
                pool.submit(attempt, second_lead_id, dana_id),
            ]
            outcomes = [future.result(timeout=30) for future in futures]

        assert sorted(outcomes) == ["reassigned", "refused"], outcomes
        winner = Users.COORDINATOR_2.id if outcomes[0] == "reassigned" else dana_id
        with Session(engine) as session:
            rows = session.scalars(
                select(EventCoordinatorAssignment)
                .where(EventCoordinatorAssignment.event_id == event_id)
                .order_by(EventCoordinatorAssignment.assigned_at)
            ).all()
            assert [row.coordinator_id for row in rows] == [Users.COORDINATOR.id, winner]
            assert session.get(Event, event_id).assigned_coordinator_id == winner
    finally:
        with Session(engine) as session:
            session.execute(delete(Notification).where(Notification.event_id == event_id))
            session.execute(delete(AuditLog).where(AuditLog.entity_id == event_id))
            session.execute(
                delete(EventCoordinatorAssignment).where(
                    EventCoordinatorAssignment.event_id == event_id
                )
            )
            session.execute(delete(Event).where(Event.id == event_id))
            session.execute(delete(User).where(User.id.in_([second_lead_id, dana_id])))
            session.commit()
