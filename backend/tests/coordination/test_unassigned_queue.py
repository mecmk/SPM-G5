"""Story 5.4 - be: an unassigned event queue that the Event Coordinator Lead assigns from.

Happy path
AC1  A new Event Coordinator Lead role exists with its own set of permitted functions (1.2).
AC2  Every submitted event with no coordinator is in the Lead's unassigned queue, oldest
     submission first, with name, proposed dates, expected attendance, organiser and submission
     time.
AC3  The Lead assigns the event to an active Event Coordinator, picked from a list showing each
     one's number of active events. The assignment records who made it and when; the event
     leaves the queue and is in that coordinator's list (6.1).
AC4  The assigned coordinator and the organiser are notified (20.1).
Boundary
AC5  An empty queue lists nothing. With no active Event Coordinators, assigning is not possible.
Edge
AC6  An unassigned event cannot be decided or have clarification requested (4.2, 4.4, 4.5).
Permission
AC7  Only the Lead sees the queue and assigns events; everyone else is refused (403).
Conflict
AC8  Of two Leads assigning one event at the same moment, only the first succeeds; the second is
     told it is already assigned, and to whom.
Replacing automatic assignment
AC9  Submitting no longer assigns a coordinator (5.1's round robin is off), and Event
     Coordinators can no longer assign an unassigned event by hand. They still reassign their own
     events (story 5.2 - PO decision, Checkpoint 1).
AC10 Events assigned before this change keep their coordinator (assumption Q17).

PO decisions at Checkpoint 1 these tests rely on:
* A coordinator's "active events" are those assigned to them in Under Review, Clarification
  Requested, Planning, Awaiting Safety Check (added with story 21.1, PO decision at review) or
  Confirmed.
* A new submission notifies every active Lead (20.1 AC1's notice, which went to the
  round-robin coordinator before).
* The Lead holds ``events:assign`` and reads every event, but does not decide them.

Excluded, with reason:
* What the queue page says when it is empty or no coordinator is active, the read-only event
  page, the direct-URL refusal, the navigation and the phone/desktop layout are UI behaviour:
  tests/e2e/unassigned-queue.spec.ts.
* A coordinator reassigning their own event (5.2) is unchanged and stays proven by
  test_reassign_coordinator.py.
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
from app.auth.permissions import Permission, permissions_for
from app.common.audit import AuditLog
from app.coordination import service as coordination_service
from app.coordination.models import EventCoordinatorAssignment
from app.coordination.schemas import AssignCoordinatorIn
from app.events.models import Event, EventStatus
from app.notifications.models import Notification
from tests.support.factories import create_submittable_event_request, make_event, make_user
from tests.support.seed import Events, Users

QUEUE_PATH = "/coordination/unassigned-events"
COORDINATORS_PATH = "/coordinators"
LEAD_ROLE = "EVENT_COORDINATOR_LEAD"
ASSIGN = "events:assign"
READ_ALL = "events:read_all"
REVIEW = "events:review"
ACTIVE_STATUSES = (
    EventStatus.UNDER_REVIEW,
    EventStatus.CLARIFICATION_REQUESTED,
    EventStatus.PLANNING,
    EventStatus.AWAITING_SAFETY_CHECK,
    EventStatus.CONFIRMED,
)


# --- helpers ---------------------------------------------------------------------------------
def _unassigned_event(db: Session, **overrides) -> Event:
    """A submitted event waiting for a coordinator, dated safely in the future."""
    starts_at = overrides.pop("starts_at", datetime.now(UTC) + timedelta(days=60))
    return make_event(
        db,
        status=overrides.pop("status", EventStatus.UNDER_REVIEW),
        starts_at=starts_at,
        ends_at=overrides.pop("ends_at", starts_at + timedelta(hours=6)),
        assigned_coordinator_id=None,
        **overrides,
    )


def _assign(client, event_id, coordinator_id):
    return client.put(
        f"/events/{event_id}/coordinator", json={"coordinator_id": str(coordinator_id)}
    )


def _queue_ids(client) -> list[str]:
    response = client.get(QUEUE_PATH)
    assert response.status_code == 200, response.text
    return [entry["id"] for entry in response.json()]


def _pointer(db: Session, event_id):
    return db.execute(
        text("SELECT assigned_coordinator_id FROM events WHERE id = :e"), {"e": event_id}
    ).scalar()


def _open_assignments(db: Session, event_id) -> list:
    return db.execute(
        text(
            "SELECT coordinator_id, assigned_by_id, assigned_at FROM event_coordinator_assignments"
            " WHERE event_id = :e AND unassigned_at IS NULL"
        ),
        {"e": event_id},
    ).all()


def _notified(db: Session, event_id, notification_type: str) -> list[uuid.UUID]:
    return sorted(
        db.execute(
            text(
                "SELECT recipient_id FROM notifications"
                " WHERE event_id = :e AND notification_type = :t"
            ),
            {"e": event_id, "t": notification_type},
        ).scalars()
    )


# --- AC1: the Lead role ------------------------------------------------------------------
@pytest.mark.story("5.4", ac=1)
def test_the_lead_role_exists_with_its_own_permissions(db: Session):
    role = db.execute(
        text("SELECT name, is_internal FROM roles WHERE code = :c"), {"c": LEAD_ROLE}
    ).one_or_none()

    assert role is not None, "the Event Coordinator Lead role is missing"
    assert role.name == "Event Coordinator Lead"
    assert role.is_internal is True
    granted = permissions_for(LEAD_ROLE)
    assert ASSIGN in granted
    assert READ_ALL in granted  # reads any event, to review it before assigning (AC2)
    assert REVIEW not in granted  # never decides an event itself


@pytest.mark.story("5.4", ac=1)
def test_a_lead_signs_in_and_holds_the_assign_permission(login_as):
    body = login_as(Users.LEAD).get("/auth/me").json()

    assert body["role_code"] == LEAD_ROLE
    assert ASSIGN in body["permissions"]
    assert REVIEW not in body["permissions"]


@pytest.mark.story("5.4", ac=1)
def test_the_lead_holds_exactly_the_read_permissions_and_assigning():
    """Reads like every internal role, and assigns; nothing else - no deciding events or bookings,
    no editing, no equipment management."""
    assert permissions_for(LEAD_ROLE) == {
        Permission.VENUES_READ,
        Permission.VENUE_CALENDAR_READ,
        Permission.EVENTS_READ_ALL,
        Permission.BOOKINGS_READ,
        Permission.EQUIPMENT_READ,
        Permission.NOTIFICATIONS_READ_OWN,
        Permission.USERS_READ_INTERNAL,
        Permission.EVENTS_ASSIGN,
    }


@pytest.mark.story("5.4", ac=1)
@pytest.mark.parametrize("action", ["approve", "reject", "clarification"])
def test_the_lead_opens_an_assigned_event_but_cannot_decide_it(login_as, db: Session, action):
    """The Lead reads any event, assigned ones included, and decides none (AC2: read-only)."""
    lead = login_as(Users.LEAD)
    calls = {
        "approve": lambda: lead.post(f"/events/{Events.SUBMITTED}/approve"),
        "reject": lambda: lead.post(
            f"/events/{Events.SUBMITTED}/reject", json={"reason": "Not a fit."}
        ),
        "clarification": lambda: lead.post(
            f"/events/{Events.SUBMITTED}/clarifications", json={"message": "Which room?"}
        ),
    }

    opened = lead.get(f"/events/{Events.SUBMITTED}")
    refused = calls[action]()

    assert opened.status_code == 200, opened.text
    assert refused.status_code == 403, refused.text
    db.expire_all()
    assert db.get(Event, Events.SUBMITTED).status == EventStatus.UNDER_REVIEW


# --- AC2: the queue ------------------------------------------------------------------------
@pytest.mark.story("5.4", ac=2)
def test_the_queue_lists_every_unassigned_submission_oldest_first(login_as, db: Session):
    newer = _unassigned_event(
        db, name="Queue Newer", submitted_at=datetime(2026, 10, 2, 9, tzinfo=UTC)
    )
    older = _unassigned_event(
        db,
        name="Queue Older",
        organiser_id=Users.ORGANISER_2.id,
        expected_attendance=120,
        submitted_at=datetime(2026, 10, 1, 9, tzinfo=UTC),
    )

    response = login_as(Users.LEAD).get(QUEUE_PATH)

    assert response.status_code == 200, response.text
    mine = [entry for entry in response.json() if entry["id"] in {str(newer.id), str(older.id)}]
    assert [entry["id"] for entry in mine] == [str(older.id), str(newer.id)]
    first = mine[0]
    assert first["name"] == "Queue Older"
    assert first["expected_attendance"] == 120
    assert first["organiser_name"] == Users.ORGANISER_2.full_name
    assert datetime.fromisoformat(first["starts_at"]) == older.starts_at
    assert datetime.fromisoformat(first["ends_at"]) == older.ends_at
    assert datetime.fromisoformat(first["submitted_at"]) == older.submitted_at


@pytest.mark.story("5.4", ac=2)
@pytest.mark.parametrize(
    "case",
    ["draft", "rejected", "cancelled", "completed", "already assigned"],
)
def test_the_queue_leaves_out_drafts_closed_and_assigned_events(login_as, db: Session, case):
    statuses = {
        "draft": EventStatus.DRAFT,
        "rejected": EventStatus.REJECTED,
        "cancelled": EventStatus.CANCELLED,
        "completed": EventStatus.COMPLETED,
    }
    if case == "already assigned":
        left_out = _unassigned_event(db)
        db.execute(
            text("UPDATE events SET assigned_coordinator_id = :c WHERE id = :e"),
            {"c": Users.COORDINATOR.id, "e": left_out.id},
        )
    else:
        left_out = _unassigned_event(db, status=statuses[case])

    assert str(left_out.id) not in _queue_ids(login_as(Users.LEAD))


# --- AC3: the Lead assigns ----------------------------------------------------------------
@pytest.mark.story("5.4", ac=3)
def test_the_lead_assigns_an_active_coordinator(login_as, db: Session):
    event = _unassigned_event(db)

    response = _assign(login_as(Users.LEAD), event.id, Users.COORDINATOR_2.id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["coordinator_id"] == str(Users.COORDINATOR_2.id)
    assert body["assigned_by_id"] == str(Users.LEAD.id)
    assert body["assigned_by_name"] == Users.LEAD.full_name
    assert body["assigned_at"] is not None
    assert _pointer(db, event.id) == Users.COORDINATOR_2.id
    [row] = _open_assignments(db, event.id)
    assert (row.coordinator_id, row.assigned_by_id) == (Users.COORDINATOR_2.id, Users.LEAD.id)
    assert row.assigned_at is not None
    audited = (
        db.execute(
            text(
                "SELECT actor_id FROM audit_log"
                " WHERE action = 'EVENT_COORDINATOR_ASSIGNED' AND entity_id = :e"
            ),
            {"e": event.id},
        )
        .scalars()
        .all()
    )
    assert audited == [Users.LEAD.id]


@pytest.mark.story("5.4", ac=3)
def test_an_assigned_event_leaves_the_queue_and_reaches_the_coordinator(login_as, db: Session):
    event = _unassigned_event(db)
    lead = login_as(Users.LEAD)
    assert str(event.id) in _queue_ids(lead)

    assert _assign(lead, event.id, Users.COORDINATOR_2.id).status_code == 200
    assert str(event.id) not in _queue_ids(lead)

    listed = login_as(Users.COORDINATOR_2).get("/events/assigned-to-me")
    assert listed.status_code == 200, listed.text
    assert str(event.id) in {entry["id"] for entry in listed.json()["items"]}


@pytest.mark.story("5.4", ac=3)
def test_the_picker_shows_each_active_coordinators_active_event_count(login_as, db: Session):
    """Only the active statuses count (PO decision, with 21.1's Awaiting Safety Check added):
    completed, rejected and cancelled events do not. An inactive coordinator is not offered."""
    busy = make_user(db, role="EVENT_COORDINATOR", full_name="Busy Coordinator")
    resting = make_user(db, role="EVENT_COORDINATOR", full_name="Resting Coordinator")
    gone = make_user(db, role="EVENT_COORDINATOR", full_name="Gone Coordinator", is_active=False)
    closed = (EventStatus.COMPLETED, EventStatus.REJECTED, EventStatus.CANCELLED)
    for status in (*ACTIVE_STATUSES, *closed):
        make_event(db, status=status, assigned_coordinator_id=busy.id)

    response = login_as(Users.LEAD).get(COORDINATORS_PATH)

    assert response.status_code == 200, response.text
    by_id = {entry["id"]: entry for entry in response.json()}
    assert by_id[str(busy.id)]["active_event_count"] == len(ACTIVE_STATUSES)
    assert by_id[str(resting.id)]["active_event_count"] == 0
    assert str(gone.id) not in by_id


@pytest.mark.story("5.4", ac=3)
@pytest.mark.parametrize("who", ["inactive coordinator", "not a coordinator", "no such user"])
def test_the_lead_cannot_assign_someone_who_is_not_an_active_coordinator(
    login_as, db: Session, who
):
    event = _unassigned_event(db)
    chosen = {
        "inactive coordinator": lambda: make_user(db, role="EVENT_COORDINATOR", is_active=False).id,
        "not a coordinator": lambda: Users.VENUE_STAFF.id,
        "no such user": uuid.uuid4,
    }[who]()

    response = _assign(login_as(Users.LEAD), event.id, chosen)

    assert response.status_code == 422, response.text
    assert _pointer(db, event.id) is None
    assert _open_assignments(db, event.id) == []


@pytest.mark.story("5.4", ac=3)
@pytest.mark.parametrize(
    ("case", "expected"),
    [("draft", 409), ("completed", 409), ("unknown", 404)],
)
def test_the_lead_cannot_assign_a_draft_closed_or_unknown_event(
    login_as, db: Session, case, expected
):
    if case == "unknown":
        event_id = uuid.uuid4()
    else:
        status = EventStatus.DRAFT if case == "draft" else EventStatus.COMPLETED
        event_id = _unassigned_event(db, status=status).id

    response = _assign(login_as(Users.LEAD), event_id, Users.COORDINATOR.id)

    assert response.status_code == expected, response.text
    if case != "unknown":
        assert _pointer(db, event_id) is None


# --- AC4: notifications ---------------------------------------------------------------------
@pytest.mark.story("5.4", ac=4)
def test_assigning_notifies_the_coordinator_and_the_organiser(login_as, db: Session):
    event = _unassigned_event(db, organiser_id=Users.ORGANISER.id)

    assert _assign(login_as(Users.LEAD), event.id, Users.COORDINATOR_2.id).status_code == 200

    assert _notified(db, event.id, "EVENT_ASSIGNED_TO") == [Users.COORDINATOR_2.id]
    assert _notified(db, event.id, "EVENT_ASSIGNED_ORGANISER") == [Users.ORGANISER.id]
    to_coordinator, to_organiser = (
        db.scalars(
            select(Notification).where(
                Notification.event_id == event.id, Notification.notification_type == kind
            )
        ).one()
        for kind in ("EVENT_ASSIGNED_TO", "EVENT_ASSIGNED_ORGANISER")
    )
    # The coordinator is told who assigned it; the organiser is told who their coordinator is.
    assert event.name in to_coordinator.title
    assert Users.LEAD.full_name in to_coordinator.message
    assert event.name in to_organiser.title
    assert Users.COORDINATOR_2.full_name in to_organiser.message
    assert Users.LEAD.full_name not in to_organiser.message
    for notice in (to_coordinator, to_organiser):
        assert (notice.related_entity_type, notice.related_entity_id) == ("event", event.id)
    everyone = (
        db.execute(
            text("SELECT recipient_id FROM notifications WHERE event_id = :e"), {"e": event.id}
        )
        .scalars()
        .all()
    )
    assert Users.LEAD.id not in everyone  # nobody is told of their own action (20.1 AC3)


# --- AC5: boundaries ------------------------------------------------------------------------
@pytest.mark.story("5.4", ac=5)
def test_an_empty_queue_lists_nothing(login_as):
    """Every seeded submitted event has a coordinator (AC10), so the seeded queue is empty."""
    response = login_as(Users.LEAD).get(QUEUE_PATH)

    assert response.status_code == 200, response.text
    assert response.json() == []


@pytest.mark.story("5.4", ac=5)
def test_assigning_is_refused_when_no_coordinator_is_active(login_as, db: Session):
    event = _unassigned_event(db)
    db.execute(text("UPDATE users SET is_active = FALSE WHERE role_code = 'EVENT_COORDINATOR'"))
    lead = login_as(Users.LEAD)

    offered = lead.get(COORDINATORS_PATH)
    refused = _assign(lead, event.id, Users.COORDINATOR.id)

    assert offered.status_code == 200, offered.text
    assert offered.json() == []
    assert refused.status_code == 422, refused.text
    assert _pointer(db, event.id) is None


# --- AC6: nothing is decided before assignment ------------------------------------------------
@pytest.mark.story("5.4", ac=6)
@pytest.mark.parametrize("action", ["approve", "reject", "clarification"])
def test_an_unassigned_event_cannot_be_decided_or_clarified(
    coordinator_client, db: Session, action
):
    event = _unassigned_event(db)
    calls = {
        "approve": lambda: coordinator_client.post(f"/events/{event.id}/approve"),
        "reject": lambda: coordinator_client.post(
            f"/events/{event.id}/reject", json={"reason": "Not a fit."}
        ),
        "clarification": lambda: coordinator_client.post(
            f"/events/{event.id}/clarifications", json={"message": "Which room?"}
        ),
    }

    response = calls[action]()

    assert response.status_code == 403, response.text
    db.expire_all()
    assert db.get(Event, event.id).status == EventStatus.UNDER_REVIEW


# --- AC7: only the Lead -----------------------------------------------------------------------
# Every role but the Lead's, so a role added later is refused here without editing this list.
REFUSED_ROLES = [user for user in Users.ONE_PER_ROLE if user != Users.LEAD]


@pytest.mark.story("5.4", ac=7)
@pytest.mark.parametrize("user", REFUSED_ROLES, ids=lambda u: u.role)
def test_only_the_lead_sees_the_queue(login_as, user):
    response = login_as(user).get(QUEUE_PATH)

    assert response.status_code == 403, response.text


@pytest.mark.story("5.4", ac=7)
def test_signing_in_is_required_for_the_queue(client):
    assert client.get(QUEUE_PATH).status_code == 401


@pytest.mark.story("5.4", ac=7)
@pytest.mark.story("5.4", ac=9)
@pytest.mark.parametrize("user", REFUSED_ROLES, ids=lambda u: u.role)
def test_only_the_lead_assigns_an_unassigned_event(login_as, db: Session, user):
    """Chloe is refused even assigning the event to herself: coordinators no longer claim
    unassigned events (AC9)."""
    event = _unassigned_event(db)

    response = _assign(login_as(user), event.id, Users.COORDINATOR.id)

    assert response.status_code == 403, response.text
    assert _pointer(db, event.id) is None
    assert _open_assignments(db, event.id) == []


@pytest.mark.story("5.4", ac=7)
def test_signing_in_is_required_to_assign(client, db: Session):
    event = _unassigned_event(db)

    assert _assign(client, event.id, Users.COORDINATOR.id).status_code == 401


# --- AC8: two Leads at once ---------------------------------------------------------------
@pytest.mark.story("5.4", ac=8)
def test_a_second_lead_is_told_it_is_already_assigned_and_to_whom(login_as, db: Session):
    event = _unassigned_event(db)
    other_lead = make_user(db, role=LEAD_ROLE, full_name="Second Lead")
    first = _assign(login_as(Users.LEAD), event.id, Users.COORDINATOR.id)

    second = _assign(login_as(other_lead.email), event.id, Users.COORDINATOR_2.id)

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    detail = second.json()["detail"]
    assert "already" in detail.lower()
    assert Users.COORDINATOR.full_name in detail
    assert _pointer(db, event.id) == Users.COORDINATOR.id


@pytest.mark.story("5.4", ac=8)
@pytest.mark.parametrize(
    "chosen", ["an unknown user", "not a coordinator", "an inactive coordinator"]
)
def test_already_assigned_is_said_before_anything_about_the_chosen_user(
    login_as, db: Session, chosen
):
    """AC8's refusal comes first, as it did before story 5.6: a Lead assigning an event that
    already has a coordinator is told who has it, whoever they chose, rather than a 422 about the
    user (review of #124). Only a direct API call names such a user - the picker offers only
    active coordinators."""
    event = _unassigned_event(db)
    lead = login_as(Users.LEAD)
    assert _assign(lead, event.id, Users.COORDINATOR.id).status_code == 200
    chosen_id = {
        "an unknown user": uuid.uuid4,
        "not a coordinator": lambda: Users.ORGANISER.id,
        "an inactive coordinator": lambda: (
            make_user(db, role="EVENT_COORDINATOR", is_active=False).id
        ),
    }[chosen]()

    response = _assign(lead, event.id, chosen_id)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == (
        f"This event has already been assigned to {Users.COORDINATOR.full_name}."
    )
    assert _pointer(db, event.id) == Users.COORDINATOR.id


@pytest.mark.story("5.4", ac=8)
def test_two_leads_assigning_at_once_write_one(engine):
    """Real concurrent transactions, so this test commits and cleans up after itself. Two Leads
    assign one unassigned event at the same moment, to two different coordinators: exactly one
    assignment is written, and the other is refused naming the coordinator who got it."""
    with Session(engine) as session:
        event = _unassigned_event(session, name="Lead Race")
        second_lead = make_user(session, role=LEAD_ROLE, full_name="Racing Lead")
        session.commit()
        event_id, second_lead_id = event.id, second_lead.id
    start = threading.Barrier(2)

    def attempt(lead_id: uuid.UUID, coordinator_id: uuid.UUID) -> str:
        with Session(engine) as session:
            actor = session.get(User, lead_id)
            start.wait()
            try:
                coordination_service.assign_coordinator(
                    session,
                    event_id,
                    AssignCoordinatorIn(coordinator_id=coordinator_id),
                    actor=actor,
                )
            except coordination_service.AlreadyAssigned as refusal:  # AC8: told who got it
                session.rollback()
                return f"refused: {refusal}"
            return "assigned"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(attempt, Users.LEAD.id, Users.COORDINATOR.id),
                pool.submit(attempt, second_lead_id, Users.COORDINATOR_2.id),
            ]
            outcomes = [future.result(timeout=30) for future in futures]

        assert outcomes.count("assigned") == 1, outcomes
        with Session(engine) as session:
            rows = session.scalars(
                select(EventCoordinatorAssignment).where(
                    EventCoordinatorAssignment.event_id == event_id
                )
            ).all()
            assert len(rows) == 1
            winner = session.get(User, rows[0].coordinator_id).full_name
        refusal = next(outcome for outcome in outcomes if outcome != "assigned")
        assert winner in refusal
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
            session.execute(delete(User).where(User.id == second_lead_id))
            session.commit()


@pytest.mark.story("5.4", ac=8)
def test_a_lead_whose_write_finds_the_event_taken_is_told_who_got_it(db: Session, monkeypatch):
    """The race test above relies on timing. This one forces the interleaving, as 5.2's
    stale-reassignment test does: the moment this Lead has read "no coordinator yet", a second
    Lead assigns Carl. The guarded update then matches no row, and the refusal names Carl."""
    event = _unassigned_event(db)
    lena = db.get(User, Users.LEAD.id)
    second_lead = make_user(db, role=LEAD_ROLE, full_name="Second Lead")
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
                actor=second_lead,
            )
        return result

    monkeypatch.setattr(coordination_service, "current_assignment", _interloper_wins_first)

    with pytest.raises(coordination_service.AlreadyAssigned) as refusal:
        coordination_service.assign_coordinator(
            db, event.id, AssignCoordinatorIn(coordinator_id=Users.COORDINATOR.id), actor=lena
        )

    monkeypatch.undo()
    assert Users.COORDINATOR_2.full_name in str(refusal.value)
    assert _pointer(db, event.id) == Users.COORDINATOR_2.id
    assert len(_open_assignments(db, event.id)) == 1


# --- AC9: no automatic assignment ---------------------------------------------------------
@pytest.mark.story("5.4", ac=9)
def test_a_submitted_request_waits_unassigned_in_the_queue(login_as, db: Session):
    organiser = login_as(Users.ORGANISER)
    draft = create_submittable_event_request(organiser)

    submitted = organiser.post(f"/events/{draft['id']}/submit")

    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["assigned_coordinator_id"] is None
    assert _open_assignments(db, draft["id"]) == []
    assert draft["id"] in _queue_ids(login_as(Users.LEAD))


@pytest.mark.story("5.4", ac=4)
@pytest.mark.story("5.4", ac=9)
def test_a_submission_notifies_every_active_lead(login_as, db: Session):
    """20.1 AC1's notice now goes to the Leads, who assign the request (PO decision). Two are
    active, so telling only the first would fail; an inactive one is not told."""
    second_lead = make_user(db, role=LEAD_ROLE, full_name="Second Lead")
    resting_lead = make_user(db, role=LEAD_ROLE, full_name="Resting Lead", is_active=False)
    organiser = login_as(Users.ORGANISER)
    draft = create_submittable_event_request(organiser)

    assert organiser.post(f"/events/{draft['id']}/submit").status_code == 200

    told = _notified(db, uuid.UUID(draft["id"]), "EVENT_SUBMITTED")
    assert told == sorted([Users.LEAD.id, second_lead.id])
    assert resting_lead.id not in told


# --- AC10: earlier assignments are kept ---------------------------------------------------
@pytest.mark.story("5.4", ac=10)
def test_events_assigned_before_keep_their_coordinator(login_as, db: Session):
    """Q17: nothing is undone. The seeded events assigned before this story keep their
    coordinator, and none of them is waiting in the queue."""
    queued = set(_queue_ids(login_as(Users.LEAD)))

    for event_id in (Events.SUBMITTED, Events.UNDER_REVIEW, Events.APPROVED, Events.PLANNING):
        assert _pointer(db, event_id) is not None
        assert len(_open_assignments(db, event_id)) == 1
        assert str(event_id) not in queued
