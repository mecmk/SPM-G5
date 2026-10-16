"""Story 19.2 - be: review and decide event change requests (Phase 1).

AC1 Assigned coordinators can view pending change requests for their events, including current
    and proposed values, reason, requester and date.
AC2 Approving a request applies the change, records who decided and when, and notifies the
    organiser. The decision and event update must be atomic.
AC3 Rejecting requires a non-blank reason, leaves the event unchanged and notifies the organiser.
AC4 Whitespace-only rejection reasons must be rejected.
AC5 Approving venue/equipment changes releases only affected bookings or reservations.
AC6 Only the assigned coordinator can decide requests, enforced on the backend.
AC7 Conflicting pending requests on the same field, withdrawn requests and duplicate decisions
    are handled safely.
AC8 Approving a change request on a Confirmed event returns it to Planning.

Phase 1 (agreed 16 Oct 2026) built the queue, both decisions, who may make them, the reason, and
the decision's record, notification and atomicity, approving only an attendance change on a
Planning event. Phase 2 (agreed 16 Oct 2026) approves every field on any event still going ahead:
* Venue requirements are matched by id, which 19.1 now keeps in the proposal; an older proposal
  without ids is matched by name.
* A venue booking the approved change no longer fits (f7.2.4's fit rule) is cancelled, and every
  active Venue Staff member is told; a booking that still fits is left exactly as it is.
* Changed or added equipment is held again if stock allows, else flagged Unavailable, and goes
  back to Requested for the coordinator to resubmit; removed equipment releases its hold, and
  Technical Support is told of any item they had pending or accepted that is withdrawn. A date
  change re-checks every item, as 15.1 AC8 does.
* New dates move every requirement that covered the whole old period to the new one, and shift
  the others by the same amount; one that no longer fits inside the event refuses the approval.
* Approving on a Confirmed or Awaiting safety check event returns it to Planning, recording the
  move, and clears its confirmation, so it must pass a new safety check (21.2) to be confirmed.

Excluded, with reason:
* What the queue and dialogs show, and the reason box blocking a blank reason before sending
  (AC4's client-side half), are UI behaviour, proven in tests/e2e/change-request-decisions.spec.ts.
* Two decisions truly at once need two database connections; these tests share the test's one
  connection, so the other decision is simulated by changing the request just before deciding,
  as 19.1 AC10 does. The event's row lock, which 19.1's withdrawal also takes, serialises the
  real race.
* Nothing moves an event to Confirmed or Awaiting safety check yet (21.2), so those tests set the
  status directly, after the request was raised in Planning, as it would be in practice.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, object_session

from app.change_requests.models import EventChangeRequest
from app.events.models import Event, EventStatus
from tests.support.factories import (
    future_datetime,
    make_booking,
    make_change_request,
    make_equipment_item,
    make_equipment_type,
    make_event,
    make_user,
    make_venue,
    make_venue_requirement,
)
from tests.support.seed import Users

_REJECTION_REASON = "The hall cannot take more people on that day."
# The service's own refusals, so a 404 is never confused with a route that does not exist.
_EVENT_NOT_FOUND = "Event not found."
_CHANGE_REQUEST_NOT_FOUND = "Change request not found."
_MAX_REASON = 2000


# --- helpers ---------------------------------------------------------------------------------


def _planning_event(db: Session, **overrides) -> Event:
    """Olivia's event in Planning, assigned to Chloe, dated safely in the future, for 100 people."""
    starts_at = overrides.pop("starts_at", future_datetime(days=60))
    return make_event(
        db,
        status=overrides.pop("status", EventStatus.PLANNING),
        starts_at=starts_at,
        ends_at=overrides.pop("ends_at", starts_at + timedelta(hours=8)),
        expected_attendance=overrides.pop("expected_attendance", 100),
        assigned_coordinator_id=overrides.pop("assigned_coordinator_id", Users.COORDINATOR.id),
        **overrides,
    )


def _decision_url(event_id: uuid.UUID, request_id: uuid.UUID, decision: str) -> str:
    return f"/events/{event_id}/change-requests/{request_id}/{decision}"


def _approve(client, request):
    """Approve ``request`` as ``client``. The test's rows are committed first - to the test's own
    transaction, which is still rolled back at the end - so a refused decision's rollback cannot
    undo them as well (as tests/events/test_correct_event_under_review.py does)."""
    object_session(request).commit()
    return client.post(_decision_url(request.event_id, request.id, "approve"))


def _reject(client, request, reason: str | None = _REJECTION_REASON):
    """Reject ``request`` as ``client``, the test's rows committed first as for ``_approve``."""
    object_session(request).commit()
    body = {} if reason is None else {"reason": reason}
    return client.post(_decision_url(request.event_id, request.id, "reject"), json=body)


def _row(db: Session, request_id: uuid.UUID):
    return db.execute(
        text(
            "SELECT status, decided_by_id, decided_at, decision_reason"
            " FROM event_change_requests WHERE id = :id"
        ),
        {"id": request_id},
    ).one()


def _attendance(db: Session, event_id: uuid.UUID) -> int:
    return db.execute(
        text("SELECT expected_attendance FROM events WHERE id = :e"), {"e": event_id}
    ).scalar_one()


def _event_status(db: Session, event_id: uuid.UUID) -> str:
    return db.execute(text("SELECT status FROM events WHERE id = :e"), {"e": event_id}).scalar_one()


def _notifications(db: Session, event_id: uuid.UUID, notification_type: str) -> list:
    return list(
        db.execute(
            text(
                "SELECT recipient_id, related_entity_type, related_entity_id, message"
                " FROM notifications WHERE event_id = :e AND notification_type = :t"
            ),
            {"e": event_id, "t": notification_type},
        )
    )


def _audit(db: Session, request_id: uuid.UUID, action: str) -> list:
    return list(
        db.execute(
            text(
                "SELECT actor_id, details FROM audit_log"
                " WHERE entity_type = 'event_change_request' AND entity_id = :id"
                " AND action = :a"
            ),
            {"id": request_id, "a": action},
        )
    )


def _assert_undecided(db: Session, request) -> None:
    """The request is still waiting: nothing about a decision was saved."""
    row = _row(db, request.id)
    assert row.status == "PENDING"
    assert row.decided_by_id is None
    assert row.decided_at is None
    assert row.decision_reason is None


def _assert_nothing_sent_or_logged(db: Session, request) -> None:
    for kind in ("EVENT_CHANGE_APPROVED", "EVENT_CHANGE_REJECTED"):
        assert _notifications(db, request.event_id, kind) == []
    for action in ("EVENT_CHANGE_APPROVED", "EVENT_CHANGE_REJECTED"):
        assert _audit(db, request.id, action) == []


def _set_request_status(db: Session, request_id: uuid.UUID, status: str) -> None:
    """Another transaction deciding or withdrawing the request (simulated on the test's
    connection)."""
    db.execute(
        text("UPDATE event_change_requests SET status = :s WHERE id = :id"),
        {"s": status, "id": request_id},
    )
    db.expire_all()


def _set_event(db: Session, event_id: uuid.UUID, **values) -> None:
    assignments = ", ".join(f"{column} = :{column}" for column in values)
    db.execute(text(f"UPDATE events SET {assignments} WHERE id = :e"), {"e": event_id, **values})
    db.expire_all()


def _raise(login_as, db: Session, event: Event, field: str, proposed) -> EventChangeRequest:
    """Olivia raises a change through 19.1's own endpoint, so the stored values are exactly what
    19.1 writes. Leaves the client signed in as her."""
    response = login_as(Users.ORGANISER).post(
        f"/events/{event.id}/change-requests",
        json={"field": field, "proposed": proposed, "reason": "Plans have changed."},
    )
    assert response.status_code == 201, response.text
    return db.get(EventChangeRequest, uuid.UUID(response.json()["id"]))


def _requirement_body(
    requirement_id: uuid.UUID | None,
    *,
    name: str,
    capacity: int,
    starts_at: datetime,
    ends_at: datetime,
    layout_code: str | None = None,
) -> dict:
    """One venue requirement as 19.1's change form sends it."""
    return {
        "id": None if requirement_id is None else str(requirement_id),
        "name": name,
        "capacity": capacity,
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "layout_code": layout_code,
        "facilities": [],
        "notes": None,
    }


def _requirements(db: Session, event_id: uuid.UUID) -> dict[str, tuple]:
    """The event's venue requirements by name: (id, capacity, starts_at, ends_at)."""
    rows = db.execute(
        text(
            "SELECT id, name, capacity, starts_at, ends_at FROM venue_requirements"
            " WHERE event_id = :e"
        ),
        {"e": event_id},
    )
    return {row.name: (row.id, row.capacity, row.starts_at, row.ends_at) for row in rows}


def _booking(db: Session, booking_id: uuid.UUID):
    return db.execute(
        text(
            "SELECT status, venue_requirement_id, hold_completed_at FROM venue_bookings"
            " WHERE id = :b"
        ),
        {"b": booking_id},
    ).one()


def _book(db: Session, event: Event, *, requirement_id=None, people: int, **overrides):
    """An approved booking of a fresh venue for ``event``'s requirement (or an additional venue),
    over the requirement's or the event's period."""
    venue = make_venue(db, name=overrides.pop("venue_name", None) or f"Room {uuid.uuid4().hex[:6]}")
    return make_booking(
        db,
        event_id=event.id,
        venue_id=venue.id,
        starts_at=overrides.pop("starts_at", event.starts_at),
        ends_at=overrides.pop("ends_at", event.ends_at),
        expected_attendance=people,
        status=overrides.pop("status", "APPROVED"),
        venue_requirement_id=requirement_id,
        hold_expires_at=overrides.pop("hold_expires_at", event.starts_at - timedelta(days=1)),
        **overrides,
    )


def _item(db: Session, item_id: uuid.UUID):
    return db.execute(
        text("SELECT status, quantity, decided_by_id FROM event_equipment_requests WHERE id = :i"),
        {"i": item_id},
    ).one_or_none()


def _holds(db: Session, item_id: uuid.UUID) -> list:
    return list(
        db.execute(
            text(
                "SELECT status, quantity, starts_at, ends_at FROM equipment_reservations"
                " WHERE equipment_request_id = :i ORDER BY reserved_at, status"
            ),
            {"i": item_id},
        )
    )


def _reserved(db: Session, item_id: uuid.UUID) -> list:
    return [hold for hold in _holds(db, item_id) if hold.status == "RESERVED"]


def _history(db: Session, event_id: uuid.UUID) -> list:
    return list(
        db.execute(
            text(
                "SELECT from_status, to_status, changed_by_id, reason FROM event_status_history"
                " WHERE event_id = :e ORDER BY changed_at"
            ),
            {"e": event_id},
        )
    )


# --- AC1: the coordinator's queue of pending change requests ---------------------------------


@pytest.mark.story("19.2", ac=1)
def test_queue_lists_pending_requests_with_what_was_asked(coordinator_client, db: Session):
    event = _planning_event(db, name="Queue Summit")
    request = make_change_request(db, event=event, current=100, proposed=150)

    response = coordinator_client.get("/change-requests")

    assert response.status_code == 200, response.text
    [entry] = [row for row in response.json() if row["id"] == str(request.id)]
    assert entry["event_id"] == str(event.id)
    assert entry["event_name"] == "Queue Summit"
    assert entry["event_status"] == "PLANNING"
    assert datetime.fromisoformat(entry["event_starts_at"]) == event.starts_at
    assert datetime.fromisoformat(entry["event_ends_at"]) == event.ends_at
    assert entry["field"] == "expected_attendance"
    assert entry["current_value"] == 100
    assert entry["proposed_value"] == 150
    assert entry["reason"] == "More sign-ups than expected."
    assert entry["status"] == "PENDING"
    assert entry["requested_by_id"] == str(Users.ORGANISER.id)
    assert entry["requested_by_name"] == Users.ORGANISER.full_name
    assert datetime.fromisoformat(entry["created_at"]) == request.created_at


@pytest.mark.story("19.2", ac=1)
def test_queue_lists_my_requests_of_every_status(coordinator_client, db: Session):
    """The queue is also the coordinator's record of what they decided (team request, 16 Oct
    2026): approved, rejected and withdrawn requests stay listed with their status, each tab of
    the page filtered from the one list. Another coordinator's events are never in it."""
    mine = _planning_event(db)
    waiting = make_change_request(db, event=mine)
    decided = [
        make_change_request(db, event=mine, field=field, status=status)
        for field, status in (
            ("schedule", "APPROVED"),
            ("equipment", "REJECTED"),
            ("venue_requirements", "WITHDRAWN"),
        )
    ]
    others = make_change_request(
        db, event=_planning_event(db, assigned_coordinator_id=Users.COORDINATOR_2.id)
    )

    listed = {row["id"]: row["status"] for row in coordinator_client.get("/change-requests").json()}

    assert listed[str(waiting.id)] == "PENDING"
    assert [listed[str(request.id)] for request in decided] == ["APPROVED", "REJECTED", "WITHDRAWN"]
    assert str(others.id) not in listed


@pytest.mark.story("19.2", ac=1)
def test_queue_leaves_out_what_can_no_longer_be_decided_but_keeps_decisions(
    coordinator_client, db: Session
):
    """A request still pending on a cancelled event can never be decided, so it is not waiting
    for the coordinator; one decided before the event closed is still part of their record. A
    Confirmed event's request can still be decided (AC8)."""
    cancelled = _planning_event(db, status=EventStatus.CANCELLED)
    stuck = make_change_request(db, event=cancelled)
    decided_before = make_change_request(db, event=cancelled, field="schedule", status="APPROVED")
    confirmed = make_change_request(db, event=_planning_event(db, status=EventStatus.CONFIRMED))

    listed = {row["id"] for row in coordinator_client.get("/change-requests").json()}

    assert str(stuck.id) not in listed
    assert str(decided_before.id) in listed
    assert str(confirmed.id) in listed


@pytest.mark.story("19.2", ac=1)
def test_queue_lists_the_oldest_request_first(coordinator_client, db: Session):
    event = _planning_event(db)
    older = make_change_request(db, event=event, field="expected_attendance")
    newer = make_change_request(
        db, event=_planning_event(db), created_at=older.created_at + timedelta(minutes=1)
    )

    listed = [row["id"] for row in coordinator_client.get("/change-requests").json()]

    assert listed.index(str(older.id)) < listed.index(str(newer.id))


@pytest.mark.story("19.2", ac=1)
def test_queue_lists_pending_requests_before_decisions_latest_first(
    coordinator_client, db: Session
):
    """What waits comes first, oldest first; below it the record, most recently decided first."""
    event = _planning_event(db)
    decided_at = future_datetime(days=-3)
    earlier = make_change_request(
        db,
        event=event,
        field="schedule",
        status="REJECTED",
        decided_by_id=Users.COORDINATOR.id,
        decided_at=decided_at,
        decision_reason="Not this time.",
    )
    later = make_change_request(
        db,
        event=event,
        field="equipment",
        status="APPROVED",
        decided_by_id=Users.COORDINATOR.id,
        decided_at=decided_at + timedelta(days=1),
    )
    waiting = make_change_request(db, event=event)

    listed = [row["id"] for row in coordinator_client.get("/change-requests").json()]
    mine = [entry for entry in listed if entry in {str(r.id) for r in (earlier, later, waiting)}]

    assert mine == [str(waiting.id), str(later.id), str(earlier.id)]


@pytest.mark.story("19.2", ac=1)
def test_queue_is_empty_when_nothing_waits(client, db: Session):
    newcomer = make_user(db, role="EVENT_COORDINATOR")
    client.login(newcomer.email)

    response = client.get("/change-requests")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.story("19.2", ac=1)
def test_event_list_shows_who_decided_when_and_why(login_as, db: Session):
    event = _planning_event(db)
    request = make_change_request(db, event=event)
    assert _reject(login_as(Users.COORDINATOR), request).status_code == 200

    response = login_as(Users.ORGANISER).get(f"/events/{event.id}/change-requests")

    [entry] = response.json()
    assert entry["status"] == "REJECTED"
    assert entry["decided_by_id"] == str(Users.COORDINATOR.id)
    assert entry["decided_by_name"] == Users.COORDINATOR.full_name
    assert entry["decided_at"] is not None
    assert entry["decision_reason"] == _REJECTION_REASON


# --- AC2: approving applies the change, records and notifies ---------------------------------


@pytest.mark.story("19.2", ac=2)
def test_approving_applies_the_change_and_records_the_decision(coordinator_client, db: Session):
    event = _planning_event(db, expected_attendance=100)
    request = make_change_request(db, event=event, current=100, proposed=150)

    response = _approve(coordinator_client, request)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "APPROVED"
    assert body["decided_by_id"] == str(Users.COORDINATOR.id)
    assert body["decided_by_name"] == Users.COORDINATOR.full_name
    assert body["decision_reason"] is None
    assert _attendance(db, event.id) == 150
    row = _row(db, request.id)
    assert row.status == "APPROVED"
    assert row.decided_by_id == Users.COORDINATOR.id
    assert row.decided_at is not None
    assert _event_status(db, event.id) == "PLANNING"


@pytest.mark.story("19.2", ac=2)
def test_approving_notifies_the_organiser(coordinator_client, db: Session):
    event = _planning_event(db)
    request = make_change_request(db, event=event)

    _approve(coordinator_client, request)

    [notice] = _notifications(db, event.id, "EVENT_CHANGE_APPROVED")
    assert notice.recipient_id == Users.ORGANISER.id
    assert notice.related_entity_type == "event_change_request"
    assert notice.related_entity_id == request.id


@pytest.mark.story("19.2", ac=2)
def test_approving_is_logged_with_the_old_and_new_value(coordinator_client, db: Session):
    event = _planning_event(db, expected_attendance=100)
    request = make_change_request(db, event=event, current=100, proposed=150)

    _approve(coordinator_client, request)

    [entry] = _audit(db, request.id, "EVENT_CHANGE_APPROVED")
    assert entry.actor_id == Users.COORDINATOR.id
    assert entry.details == {
        "event_id": str(event.id),
        "field": "expected_attendance",
        "from": 100,
        "to": 150,
        "released_booking_ids": [],
    }


@pytest.mark.story("19.2", ac=2)
def test_approving_one_request_leaves_the_others_pending(coordinator_client, db: Session):
    event = _planning_event(db)
    attendance = make_change_request(db, event=event)
    equipment = make_change_request(db, event=event, field="equipment", current=[], proposed=[])

    assert _approve(coordinator_client, attendance).status_code == 200

    assert _row(db, equipment.id).status == "PENDING"


@pytest.mark.story("19.2", ac=2)
@pytest.mark.parametrize("capacity", [150, 120])
def test_requirement_within_the_new_attendance_is_approved(
    coordinator_client, db: Session, capacity
):
    """2.7 AC6 at its limit: a requirement may need room for exactly the expected attendance."""
    event = _planning_event(db, expected_attendance=200)
    make_venue_requirement(db, event.id, capacity=capacity)
    request = make_change_request(db, event=event, current=200, proposed=150)

    assert _approve(coordinator_client, request).status_code == 200
    assert _attendance(db, event.id) == 150


@pytest.mark.story("19.2", ac=2)
def test_approval_refused_by_a_creation_rule_changes_nothing(coordinator_client, db: Session):
    """Atomic: the request is claimed before the change is judged, so a refusal after the claim
    must roll the claim back with everything else."""
    event = _planning_event(db, expected_attendance=200)
    make_venue_requirement(db, event.id, name="Main hall", capacity=151)
    request = make_change_request(db, event=event, current=200, proposed=150)

    response = _approve(coordinator_client, request)

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Main hall cannot need room for more people than the expected attendance."
    )
    assert _attendance(db, event.id) == 200
    _assert_undecided(db, request)
    _assert_nothing_sent_or_logged(db, request)


# --- AC3: rejecting needs a reason and changes nothing ---------------------------------------


@pytest.mark.story("19.2", ac=3)
def test_rejecting_records_the_reason_and_leaves_the_event_unchanged(
    coordinator_client, db: Session
):
    event = _planning_event(db, expected_attendance=100)
    request = make_change_request(db, event=event, current=100, proposed=150)
    updated_at = db.execute(
        text("SELECT updated_at FROM events WHERE id = :e"), {"e": event.id}
    ).scalar_one()

    response = _reject(coordinator_client, request, f"  {_REJECTION_REASON}  ")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "REJECTED"
    assert body["decision_reason"] == _REJECTION_REASON
    assert body["decided_by_id"] == str(Users.COORDINATOR.id)
    row = _row(db, request.id)
    assert row.status == "REJECTED"
    assert row.decided_by_id == Users.COORDINATOR.id
    assert row.decided_at is not None
    assert row.decision_reason == _REJECTION_REASON
    assert _attendance(db, event.id) == 100
    assert (
        db.execute(
            text("SELECT updated_at FROM events WHERE id = :e"), {"e": event.id}
        ).scalar_one()
        == updated_at
    )


@pytest.mark.story("19.2", ac=3)
def test_rejecting_notifies_the_organiser_with_the_reason(coordinator_client, db: Session):
    event = _planning_event(db)
    request = make_change_request(db, event=event)

    _reject(coordinator_client, request)

    [notice] = _notifications(db, event.id, "EVENT_CHANGE_REJECTED")
    assert notice.recipient_id == Users.ORGANISER.id
    assert notice.related_entity_id == request.id
    assert _REJECTION_REASON in notice.message


@pytest.mark.story("19.2", ac=3)
def test_rejecting_is_logged_with_the_reason(coordinator_client, db: Session):
    event = _planning_event(db)
    request = make_change_request(db, event=event)

    _reject(coordinator_client, request)

    [entry] = _audit(db, request.id, "EVENT_CHANGE_REJECTED")
    assert entry.actor_id == Users.COORDINATOR.id
    assert entry.details == {
        "event_id": str(event.id),
        "field": "expected_attendance",
        "reason": _REJECTION_REASON,
    }


@pytest.mark.story("19.2", ac=3)
@pytest.mark.parametrize("field", ["schedule", "venue_requirements", "equipment"])
def test_any_field_can_be_rejected(coordinator_client, db: Session, field):
    request = make_change_request(
        db, event=_planning_event(db), field=field, current=[], proposed=[]
    )

    assert _reject(coordinator_client, request).status_code == 200
    assert _row(db, request.id).status == "REJECTED"


@pytest.mark.story("19.2", ac=3)
@pytest.mark.parametrize(
    ("length", "expected_status"), [(_MAX_REASON, 200), (_MAX_REASON + 1, 422)]
)
def test_rejection_reason_length_limit(coordinator_client, db: Session, length, expected_status):
    request = make_change_request(db, event=_planning_event(db))

    response = _reject(coordinator_client, request, "x" * length)

    assert response.status_code == expected_status


# --- AC4: a blank reason is no reason --------------------------------------------------------


@pytest.mark.story("19.2", ac=4)
@pytest.mark.parametrize("reason", ["", "   ", "\n\t ", None])
def test_rejection_needs_a_non_blank_reason(coordinator_client, db: Session, reason):
    request = make_change_request(db, event=_planning_event(db))

    response = _reject(coordinator_client, request, reason)

    assert response.status_code == 422
    _assert_undecided(db, request)
    _assert_nothing_sent_or_logged(db, request)


# --- AC5: only the arrangements a change affects are released --------------------------------


@pytest.mark.story("19.2", ac=5)
@pytest.mark.parametrize(("booked", "proposed"), [(150, 150), (200, 150), (100, 80)])
def test_attendance_change_that_every_booking_still_holds_is_approved(
    coordinator_client, db: Session, booked, proposed
):
    """Only unaffected bookings exist, so nothing is released and the booking stays as it was."""
    event = _planning_event(db, expected_attendance=100)
    venue = make_venue(db, capacity=300)
    booking = make_booking(
        db,
        event_id=event.id,
        venue_id=venue.id,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        expected_attendance=booked,
        status="PENDING",
    )
    request = make_change_request(db, event=event, current=100, proposed=proposed)

    assert _approve(coordinator_client, request).status_code == 200
    assert _attendance(db, event.id) == proposed
    row = db.execute(
        text("SELECT status, expected_attendance FROM venue_bookings WHERE id = :b"),
        {"b": booking.id},
    ).one()
    assert (row.status, row.expected_attendance) == ("PENDING", booked)


@pytest.mark.story("19.2", ac=5)
def test_closed_bookings_do_not_hold_up_an_attendance_rise(coordinator_client, db: Session):
    event = _planning_event(db, expected_attendance=100)
    venue = make_venue(db, capacity=300)
    for status in ("REJECTED", "WITHDRAWN"):
        make_booking(
            db,
            event_id=event.id,
            venue_id=venue.id,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            expected_attendance=100,
            status=status,
        )
    request = make_change_request(db, event=event, current=100, proposed=150)

    assert _approve(coordinator_client, request).status_code == 200


# --- AC6: only the assigned coordinator decides ----------------------------------------------


@pytest.mark.story("19.2", ac=6)
@pytest.mark.parametrize("decide", [_approve, _reject], ids=["approve", "reject"])
@pytest.mark.parametrize(
    ("user", "expected_status"),
    [
        (Users.COORDINATOR_2, 403),  # a coordinator, not this event's
        (Users.ORGANISER, 403),  # the event's own organiser
        (Users.LEAD, 403),
        (Users.VENUE_STAFF, 403),
        (Users.SAFETY_OFFICER, 403),
    ],
)
def test_only_the_assigned_coordinator_decides(
    login_as, db: Session, decide, user, expected_status
):
    event = _planning_event(db)
    request = make_change_request(db, event=event)

    response = decide(login_as(user), request)

    assert response.status_code == expected_status
    _assert_undecided(db, request)
    assert _attendance(db, event.id) == 100


@pytest.mark.story("19.2", ac=6)
@pytest.mark.parametrize("decide", [_approve, _reject], ids=["approve", "reject"])
def test_signed_out_cannot_decide(client, db: Session, decide):
    request = make_change_request(db, event=_planning_event(db))

    assert decide(client, request).status_code == 401
    _assert_undecided(db, request)


@pytest.mark.story("19.2", ac=6)
def test_another_coordinator_is_told_why(login_as, db: Session):
    request = make_change_request(db, event=_planning_event(db))

    response = _approve(login_as(Users.COORDINATOR_2), request)

    assert response.json()["detail"] == (
        "Only the coordinator assigned to this event can decide its change requests."
    )


@pytest.mark.story("19.2", ac=6)
def test_after_reassignment_only_the_new_coordinator_decides(login_as, db: Session):
    event = _planning_event(db)
    request = make_change_request(db, event=event)
    _set_event(db, event.id, assigned_coordinator_id=Users.COORDINATOR_2.id)

    assert _approve(login_as(Users.COORDINATOR), request).status_code == 403
    assert _approve(login_as(Users.COORDINATOR_2), request).status_code == 200


@pytest.mark.story("19.2", ac=6)
@pytest.mark.parametrize(
    ("user", "expected_status"),
    [(Users.ORGANISER, 403), (Users.LEAD, 403), (Users.VENUE_STAFF, 403), (None, 401)],
)
def test_queue_is_only_for_coordinators(login_as, client, user, expected_status):
    viewer = client if user is None else login_as(user)

    assert viewer.get("/change-requests").status_code == expected_status


@pytest.mark.story("19.2", ac=6)
@pytest.mark.parametrize(
    ("decision", "body"), [("approve", None), ("reject", {"reason": _REJECTION_REASON})]
)
def test_deciding_on_an_unknown_event_or_request_is_not_found(
    coordinator_client, db: Session, decision, body
):
    event = _planning_event(db)
    request = make_change_request(db, event=event)
    elsewhere = make_change_request(db, event=_planning_event(db))
    cases = [
        (uuid.uuid4(), request.id, _EVENT_NOT_FOUND),
        (event.id, elsewhere.id, _CHANGE_REQUEST_NOT_FOUND),
        (event.id, uuid.uuid4(), _CHANGE_REQUEST_NOT_FOUND),
    ]

    for event_id, request_id, message in cases:
        response = coordinator_client.post(_decision_url(event_id, request_id, decision), json=body)
        assert (response.status_code, response.json()["detail"]) == (404, message)
    _assert_undecided(db, request)
    _assert_undecided(db, elsewhere)


# --- AC7: duplicate decisions, withdrawn requests and stale requests -------------------------


@pytest.mark.story("19.2", ac=7)
@pytest.mark.parametrize(
    ("first", "second", "message"),
    [
        (_approve, _approve, "This change request has already been approved."),
        (_approve, _reject, "This change request has already been approved."),
        (_reject, _approve, "This change request has already been rejected."),
        (_reject, _reject, "This change request has already been rejected."),
    ],
    ids=["approve-approve", "approve-reject", "reject-approve", "reject-reject"],
)
def test_a_request_is_decided_only_once(coordinator_client, db: Session, first, second, message):
    event = _planning_event(db, expected_attendance=100)
    request = make_change_request(db, event=event, current=100, proposed=150)
    assert first(coordinator_client, request).status_code == 200
    decided = _row(db, request.id)

    response = second(coordinator_client, request)

    assert response.status_code == 409
    assert response.json()["detail"] == message
    assert _row(db, request.id) == decided
    sent = _notifications(db, event.id, "EVENT_CHANGE_APPROVED") + _notifications(
        db, event.id, "EVENT_CHANGE_REJECTED"
    )
    assert len(sent) == 1


@pytest.mark.story("19.2", ac=7)
@pytest.mark.parametrize("decide", [_approve, _reject], ids=["approve", "reject"])
def test_a_withdrawn_request_cannot_be_decided(coordinator_client, db: Session, decide):
    event = _planning_event(db)
    request = make_change_request(db, event=event, status="WITHDRAWN")

    response = decide(coordinator_client, request)

    assert response.status_code == 409
    assert response.json()["detail"] == "This change request was withdrawn by the organiser."
    assert _row(db, request.id).status == "WITHDRAWN"
    assert _attendance(db, event.id) == 100


@pytest.mark.story("19.2", ac=7)
@pytest.mark.parametrize("decide", [_approve, _reject], ids=["approve", "reject"])
@pytest.mark.parametrize("meanwhile", ["APPROVED", "REJECTED", "WITHDRAWN"])
def test_decision_refused_when_the_request_closed_meanwhile(
    coordinator_client, db: Session, decide, meanwhile
):
    event = _planning_event(db)
    request = make_change_request(db, event=event)
    _set_request_status(db, request.id, meanwhile)

    response = decide(coordinator_client, request)

    assert response.status_code == 409
    assert _row(db, request.id).status == meanwhile
    assert _row(db, request.id).decided_by_id is None
    _assert_nothing_sent_or_logged(db, request)


@pytest.mark.story("19.2", ac=7)
def test_a_request_the_event_has_moved_on_from_cannot_be_approved(coordinator_client, db: Session):
    """The attendance was changed since the request was raised (e.g. by another approved request
    or a coordinator's correction), so the "current" the organiser saw is no longer current."""
    event = _planning_event(db, expected_attendance=100)
    request = make_change_request(db, event=event, current=100, proposed=150)
    _set_event(db, event.id, expected_attendance=120)

    response = _approve(coordinator_client, request)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "The expected attendance changed since this request was raised, so it cannot be "
        "approved. Reject it so the organiser can ask again."
    )
    assert _attendance(db, event.id) == 120
    _assert_undecided(db, request)
    _assert_nothing_sent_or_logged(db, request)


@pytest.mark.story("19.2", ac=7)
def test_a_moved_on_request_can_still_be_rejected(coordinator_client, db: Session):
    event = _planning_event(db, expected_attendance=100)
    request = make_change_request(db, event=event, current=100, proposed=150)
    _set_event(db, event.id, expected_attendance=120)

    assert _reject(coordinator_client, request).status_code == 200
    assert _attendance(db, event.id) == 120


@pytest.mark.story("19.2", ac=7)
@pytest.mark.parametrize("decide", [_approve, _reject], ids=["approve", "reject"])
@pytest.mark.parametrize("status", ["CANCELLED", "COMPLETED"])
def test_requests_on_a_closed_event_cannot_be_decided(
    coordinator_client, db: Session, decide, status
):
    event = _planning_event(db, status=status)
    request = make_change_request(db, event=event)

    response = decide(coordinator_client, request)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        f"This event is {status}, so its change requests can no longer be decided."
    )
    _assert_undecided(db, request)


@pytest.mark.story("19.2", ac=7)
def test_one_pending_request_per_field_still_holds_after_a_decision(login_as, db: Session):
    """The same-field conflict cannot arise: 19.1's index allows one pending request per field.
    Deciding one frees the field, so the organiser can ask again."""
    event = _planning_event(db, expected_attendance=100)
    request = make_change_request(db, event=event, current=100, proposed=150)
    assert _reject(login_as(Users.COORDINATOR), request).status_code == 200

    again = login_as(Users.ORGANISER).post(
        f"/events/{event.id}/change-requests",
        json={"field": "expected_attendance", "proposed": 140, "reason": "Fewer, then."},
    )

    assert again.status_code == 201, again.text


# --- AC8: approving past Planning returns the event to Planning ------------------------------


@pytest.mark.story("19.2", ac=8)
@pytest.mark.parametrize("status", ["CONFIRMED", "AWAITING_SAFETY_CHECK"])
def test_rejecting_past_planning_leaves_the_status(coordinator_client, db: Session, status):
    event = _planning_event(db, status=status)
    request = make_change_request(db, event=event)

    assert _reject(coordinator_client, request).status_code == 200
    assert _event_status(db, event.id) == status


# --- Phase 2, AC2: every field is applied ------------------------------------------------------


@pytest.mark.story("19.2", ac=2)
def test_approving_new_dates_moves_the_event_and_its_requirements(login_as, db: Session):
    """Whole-event requirements follow the new dates; one for part of the event shifts with the
    start, keeping its length."""
    event = _planning_event(db)
    start, end = event.starts_at, event.ends_at
    make_venue_requirement(
        db, event.id, name="Main hall", capacity=50, starts_at=start, ends_at=end
    )
    make_venue_requirement(
        db,
        event.id,
        position=1,
        name="Breakout",
        capacity=20,
        starts_at=start + timedelta(hours=2),
        ends_at=start + timedelta(hours=4),
    )
    new_start, new_end = start + timedelta(days=1), end + timedelta(days=1, hours=1)
    request = _raise(
        login_as,
        db,
        event,
        "schedule",
        {"starts_at": new_start.isoformat(), "ends_at": new_end.isoformat()},
    )

    response = _approve(login_as(Users.COORDINATOR), request)

    assert response.status_code == 200, response.text
    moved = db.execute(
        text("SELECT starts_at, ends_at FROM events WHERE id = :e"), {"e": event.id}
    ).one()
    assert (moved.starts_at, moved.ends_at) == (new_start, new_end)
    requirements = _requirements(db, event.id)
    assert requirements["Main hall"][2:] == (new_start, new_end)
    assert requirements["Breakout"][2:] == (
        new_start + timedelta(hours=2),
        new_start + timedelta(hours=4),
    )


@pytest.mark.story("19.2", ac=2)
def test_new_dates_a_shifted_requirement_no_longer_fits_are_refused(login_as, db: Session):
    """A shorter event can leave a part-time requirement outside it: refused by 2.7's rule, and
    nothing changes."""
    event = _planning_event(db)
    start, end = event.starts_at, event.ends_at
    make_venue_requirement(
        db,
        event.id,
        name="Breakout",
        capacity=20,
        starts_at=start + timedelta(hours=5),
        ends_at=start + timedelta(hours=7),
    )
    request = _raise(
        login_as,
        db,
        event,
        "schedule",
        {
            "starts_at": (start + timedelta(hours=1)).isoformat(),
            "ends_at": (end - timedelta(hours=2)).isoformat(),
        },
    )

    response = _approve(login_as(Users.COORDINATOR), request)

    assert response.status_code == 422
    assert response.json()["detail"] == "Breakout cannot end after the event ends."
    assert _requirements(db, event.id)["Breakout"][2] == start + timedelta(hours=5)
    _assert_undecided(db, request)
    _assert_nothing_sent_or_logged(db, request)


@pytest.mark.story("19.2", ac=2)
def test_new_dates_before_registration_closes_are_refused(login_as, db: Session):
    """2.1 AC18: registration must close no later than the start, so moving the start before the
    closing date is refused, as moving it on the request would be."""
    event = _planning_event(
        db,
        registration_required=True,
        registration_opens_at=future_datetime(days=10),
        registration_closes_at=future_datetime(days=50),
    )
    request = _raise(
        login_as,
        db,
        event,
        "schedule",
        {
            "starts_at": future_datetime(days=40).isoformat(),
            "ends_at": future_datetime(days=40, hours=8).isoformat(),
        },
    )

    response = _approve(login_as(Users.COORDINATOR), request)

    assert response.status_code == 422
    _assert_undecided(db, request)


@pytest.mark.story("19.2", ac=2)
def test_approving_venue_requirements_edits_keeps_and_removes_them(login_as, db: Session):
    event = _planning_event(db)
    start, end = event.starts_at, event.ends_at
    kept = make_venue_requirement(
        db, event.id, name="Main hall", capacity=50, starts_at=start, ends_at=end
    )
    make_venue_requirement(
        db, event.id, position=1, name="Breakout", capacity=20, starts_at=start, ends_at=end
    )
    request = _raise(
        login_as,
        db,
        event,
        "venue_requirements",
        [
            _requirement_body(kept, name="Grand hall", capacity=60, starts_at=start, ends_at=end),
            _requirement_body(None, name="Workshop", capacity=30, starts_at=start, ends_at=end),
        ],
    )

    assert _approve(login_as(Users.COORDINATOR), request).status_code == 200

    requirements = _requirements(db, event.id)
    assert set(requirements) == {"Grand hall", "Workshop"}
    assert requirements["Grand hall"][:2] == (kept, 60)


@pytest.mark.story("19.2", ac=2)
def test_proposed_venue_requirements_keep_their_ids(login_as, db: Session):
    """So an approval can tell an edited requirement from a removed one and a new one."""
    event = _planning_event(db)
    kept = make_venue_requirement(
        db,
        event.id,
        name="Main hall",
        capacity=50,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
    )
    body = _requirement_body(
        kept, name="Main hall", capacity=60, starts_at=event.starts_at, ends_at=event.ends_at
    )

    request = _raise(login_as, db, event, "venue_requirements", [body])

    assert [item["id"] for item in json.loads(request.proposed_value)] == [str(kept)]
    assert [item["id"] for item in json.loads(request.current_value)] == [str(kept)]


@pytest.mark.story("19.2", ac=2)
def test_an_older_proposal_without_ids_is_matched_by_name(coordinator_client, db: Session):
    """Requests raised before ids were kept still apply, the requirement found by its name."""
    event = _planning_event(db)
    kept = make_venue_requirement(
        db,
        event.id,
        name="Main hall",
        capacity=50,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
    )
    stored = {
        "name": "Main hall",
        "capacity": 50,
        "layout_code": None,
        "notes": None,
        "starts_at": event.starts_at.astimezone(UTC).isoformat(),
        "ends_at": event.ends_at.astimezone(UTC).isoformat(),
        "facilities": [],
    }
    request = make_change_request(
        db,
        event=event,
        field="venue_requirements",
        current=[stored],
        proposed=[{**stored, "capacity": 70}],
    )

    assert _approve(coordinator_client, request).status_code == 200
    assert _requirements(db, event.id)["Main hall"][:2] == (kept, 70)


@pytest.mark.story("19.2", ac=2)
def test_approving_equipment_updates_the_items(login_as, db: Session):
    event = _planning_event(db)
    kit = make_equipment_type(db, total_quantity=10)
    item = make_equipment_item(db, event=event, equipment_type=kit, quantity=2)
    request = _raise(
        login_as,
        db,
        event,
        "equipment",
        [{"id": str(item.id), "equipment_type_code": kit.code, "quantity": 5}],
    )

    assert _approve(login_as(Users.COORDINATOR), request).status_code == 200
    assert _item(db, item.id).quantity == 5


@pytest.mark.story("19.2", ac=7)
def test_venue_requirements_changed_since_the_request_cannot_be_approved(login_as, db: Session):
    event = _planning_event(db)
    kept = make_venue_requirement(
        db,
        event.id,
        name="Main hall",
        capacity=50,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
    )
    request = _raise(
        login_as,
        db,
        event,
        "venue_requirements",
        [
            _requirement_body(
                kept,
                name="Main hall",
                capacity=60,
                starts_at=event.starts_at,
                ends_at=event.ends_at,
            )
        ],
    )
    db.execute(text("UPDATE venue_requirements SET capacity = 55 WHERE id = :r"), {"r": kept})
    db.expire_all()

    response = _approve(login_as(Users.COORDINATOR), request)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "The venue requirements changed since this request was raised, so it cannot be "
        "approved. Reject it so the organiser can ask again."
    )
    assert _requirements(db, event.id)["Main hall"][1] == 55


# --- Phase 2, AC5: only affected bookings and holds are released ---------------------------------


@pytest.mark.story("19.2", ac=5)
def test_attendance_rise_releases_only_the_bookings_too_small_for_it(login_as, db: Session):
    """An additional venue holds the event's attendance (12.5), so a rise past it releases it; a
    requirement with its own number of people is unaffected, so its booking stays."""
    event = _planning_event(db, expected_attendance=100)
    own_number = make_venue_requirement(
        db,
        event.id,
        name="Main hall",
        capacity=40,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
    )
    stays = _book(db, event, requirement_id=own_number, people=40)
    released = _book(db, event, people=100, venue_name="Harbour Room")
    request = _raise(login_as, db, event, "expected_attendance", 150)

    assert _approve(login_as(Users.COORDINATOR), request).status_code == 200

    assert _booking(db, stays.id).status == "APPROVED"
    assert _booking(db, released.id).status == "CANCELLED"
    [notice] = _notifications(db, event.id, "BOOKING_RELEASED")
    assert notice.recipient_id == Users.VENUE_STAFF.id
    assert notice.related_entity_id == released.id
    assert "Harbour Room" in notice.message


@pytest.mark.story("19.2", ac=5)
def test_venue_requirement_change_releases_only_the_bookings_it_affects(login_as, db: Session):
    event = _planning_event(db)
    start, end = event.starts_at, event.ends_at
    renamed = make_venue_requirement(
        db, event.id, name="Main hall", capacity=50, starts_at=start, ends_at=end
    )
    grown = make_venue_requirement(
        db, event.id, position=1, name="Breakout", capacity=20, starts_at=start, ends_at=end
    )
    dropped = make_venue_requirement(
        db, event.id, position=2, name="Quiet room", capacity=10, starts_at=start, ends_at=end
    )
    renamed_booking = _book(db, event, requirement_id=renamed, people=50)
    grown_booking = _book(db, event, requirement_id=grown, people=20)
    dropped_booking = _book(db, event, requirement_id=dropped, people=10)
    request = _raise(
        login_as,
        db,
        event,
        "venue_requirements",
        [
            _requirement_body(
                renamed, name="Grand hall", capacity=50, starts_at=start, ends_at=end
            ),
            _requirement_body(grown, name="Breakout", capacity=40, starts_at=start, ends_at=end),
        ],
    )

    assert _approve(login_as(Users.COORDINATOR), request).status_code == 200

    kept = _booking(db, renamed_booking.id)
    assert (kept.status, kept.venue_requirement_id) == ("APPROVED", renamed)
    assert _booking(db, grown_booking.id).status == "CANCELLED"
    assert _booking(db, dropped_booking.id).status == "CANCELLED"
    assert len(_notifications(db, event.id, "BOOKING_RELEASED")) == 2


@pytest.mark.story("19.2", ac=5)
def test_new_dates_release_the_bookings_and_move_the_equipment(login_as, db: Session):
    """The booking was for the old period, so it no longer covers the event; the equipment is
    re-checked for the new dates as 15.1 AC8 does - held again there, and an accepted item goes
    back to Technical Support, since their decision was for the old dates."""
    event = _planning_event(db)
    start, end = event.starts_at, event.ends_at
    hall = make_venue_requirement(
        db, event.id, name="Main hall", capacity=50, starts_at=start, ends_at=end
    )
    booking = _book(db, event, requirement_id=hall, people=50)
    kit = make_equipment_type(db, total_quantity=10)
    item = make_equipment_item(db, event=event, equipment_type=kit, quantity=2, status="ACCEPTED")
    new_start, new_end = start + timedelta(days=2), end + timedelta(days=2)
    request = _raise(
        login_as,
        db,
        event,
        "schedule",
        {"starts_at": new_start.isoformat(), "ends_at": new_end.isoformat()},
    )

    assert _approve(login_as(Users.COORDINATOR), request).status_code == 200

    assert _booking(db, booking.id).status == "CANCELLED"
    [hold] = _reserved(db, item.id)
    assert (hold.starts_at, hold.ends_at) == (new_start, new_end)
    assert _item(db, item.id).status == "PENDING"


@pytest.mark.story("19.2", ac=5)
def test_changed_equipment_is_held_again_and_waits_to_be_resent(login_as, db: Session):
    event = _planning_event(db)
    steady = make_equipment_type(db, total_quantity=10)
    changing = make_equipment_type(db, total_quantity=10)
    untouched = make_equipment_item(
        db, event=event, equipment_type=steady, quantity=2, status="ACCEPTED"
    )
    changed = make_equipment_item(
        db,
        event=event,
        equipment_type=changing,
        quantity=2,
        status="ACCEPTED",
        decided_by_id=Users.TECH_SUPPORT.id,
        decided_at=future_datetime(days=-1),
    )
    request = _raise(
        login_as,
        db,
        event,
        "equipment",
        [
            {"id": str(untouched.id), "equipment_type_code": steady.code, "quantity": 2},
            {"id": str(changed.id), "equipment_type_code": changing.code, "quantity": 4},
        ],
    )

    assert _approve(login_as(Users.COORDINATOR), request).status_code == 200

    assert _item(db, untouched.id).status == "ACCEPTED"
    assert [hold.quantity for hold in _reserved(db, untouched.id)] == [2]
    row = _item(db, changed.id)
    assert (row.status, row.quantity, row.decided_by_id) == ("REQUESTED", 4, None)
    assert [hold.quantity for hold in _reserved(db, changed.id)] == [4]
    [notice] = _notifications(db, event.id, "EQUIPMENT_WITHDRAWN")
    assert notice.recipient_id == Users.TECH_SUPPORT.id
    assert changing.name in notice.message


@pytest.mark.story("19.2", ac=5)
def test_removed_equipment_releases_its_hold(login_as, db: Session):
    """A sent item is kept as Cancelled, so Technical Support's record stays whole, and they are
    told; one never sent is simply removed."""
    event = _planning_event(db)
    sent_type = make_equipment_type(db, total_quantity=10)
    unsent_type = make_equipment_type(db, total_quantity=10)
    sent = make_equipment_item(
        db, event=event, equipment_type=sent_type, quantity=2, status="PENDING"
    )
    unsent = make_equipment_item(db, event=event, equipment_type=unsent_type, quantity=1)
    request = _raise(login_as, db, event, "equipment", [])

    assert _approve(login_as(Users.COORDINATOR), request).status_code == 200

    assert _item(db, sent.id).status == "CANCELLED"
    assert _reserved(db, sent.id) == []
    assert _item(db, unsent.id) is None
    assert len(_notifications(db, event.id, "EQUIPMENT_WITHDRAWN")) == 1


@pytest.mark.story("19.2", ac=5)
def test_removed_equipment_kept_as_cancelled_is_not_current_equipment(login_as, db: Session):
    """A removed item kept, Cancelled, for Technical Support's record is no longer the event's:
    the organiser may ask for it back as it was, and asking to remove it again changes nothing."""
    event = _planning_event(db)
    sent_type = make_equipment_type(db, total_quantity=10)
    make_equipment_item(db, event=event, equipment_type=sent_type, quantity=2, status="PENDING")
    removal = _raise(login_as, db, event, "equipment", [])
    assert _approve(login_as(Users.COORDINATOR), removal).status_code == 200
    organiser = login_as(Users.ORGANISER)
    url = f"/events/{event.id}/change-requests"

    removed_again = organiser.post(
        url, json={"field": "equipment", "proposed": [], "reason": "Plans have changed."}
    )
    added_back = organiser.post(
        url,
        json={
            "field": "equipment",
            "proposed": [{"equipment_type_code": sent_type.code, "quantity": 2}],
            "reason": "Plans have changed.",
        },
    )

    assert removed_again.status_code == 422, removed_again.text
    assert added_back.status_code == 201, added_back.text
    assert added_back.json()["current_value"] == []


@pytest.mark.story("19.2", ac=5)
def test_added_equipment_is_held_or_flagged_when_short(login_as, db: Session):
    event = _planning_event(db)
    plenty = make_equipment_type(db, total_quantity=10)
    scarce = make_equipment_type(db, total_quantity=2)
    request = _raise(
        login_as,
        db,
        event,
        "equipment",
        [
            {"equipment_type_code": plenty.code, "quantity": 3},
            {"equipment_type_code": scarce.code, "quantity": 3},
        ],
    )

    assert _approve(login_as(Users.COORDINATOR), request).status_code == 200

    added = {
        row.equipment_type_id: row
        for row in db.execute(
            text(
                "SELECT id, equipment_type_id, status FROM event_equipment_requests"
                " WHERE event_id = :e"
            ),
            {"e": event.id},
        )
    }
    assert added[plenty.id].status == "REQUESTED"
    assert [hold.quantity for hold in _reserved(db, added[plenty.id].id)] == [3]
    assert added[scarce.id].status == "UNAVAILABLE"
    assert _reserved(db, added[scarce.id].id) == []


@pytest.mark.story("19.2", ac=5)
def test_rejecting_releases_nothing(login_as, db: Session):
    event = _planning_event(db, expected_attendance=100)
    booking = _book(db, event, people=100)
    request = _raise(login_as, db, event, "expected_attendance", 150)

    assert _reject(login_as(Users.COORDINATOR), request).status_code == 200
    assert _booking(db, booking.id).status == "APPROVED"
    assert _notifications(db, event.id, "BOOKING_RELEASED") == []


# --- Phase 2, AC8: back to Planning for a new safety check --------------------------------------


@pytest.mark.story("19.2", ac=8)
@pytest.mark.parametrize("status", ["CONFIRMED", "AWAITING_SAFETY_CHECK"])
def test_approving_past_planning_returns_the_event_to_planning(login_as, db: Session, status):
    event = _planning_event(db, expected_attendance=100)
    hall = make_venue_requirement(
        db,
        event.id,
        name="Main hall",
        capacity=50,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
    )
    booking = _book(db, event, requirement_id=hall, people=50)
    request = _raise(login_as, db, event, "expected_attendance", 80)
    _set_event(db, event.id, status=status, confirmed_at=future_datetime(days=-1))
    db.execute(
        text("UPDATE venue_bookings SET hold_completed_at = now() WHERE id = :b"),
        {"b": booking.id},
    )
    db.execute(
        text(
            "INSERT INTO event_safety_reviews (event_id, reviewed_by_id, outcome, facts)"
            " VALUES (:e, :u, 'APPROVED', '{}')"
        ),
        {"e": event.id, "u": Users.SAFETY_OFFICER.id},
    )
    db.expire_all()

    response = _approve(login_as(Users.COORDINATOR), request)

    assert response.status_code == 200, response.text
    row = db.execute(
        text("SELECT status, confirmed_at, expected_attendance FROM events WHERE id = :e"),
        {"e": event.id},
    ).one()
    assert (row.status, row.confirmed_at, row.expected_attendance) == ("PLANNING", None, 80)
    [moved] = [entry for entry in _history(db, event.id) if entry.to_status == "PLANNING"]
    assert (moved.from_status, moved.changed_by_id) == (status, Users.COORDINATOR.id)
    assert moved.reason == "Change to the expected attendance approved."
    kept = _booking(db, booking.id)
    assert kept.status == "APPROVED"
    assert kept.hold_completed_at is not None
    assert (
        db.execute(
            text("SELECT count(*) FROM event_safety_reviews WHERE event_id = :e"), {"e": event.id}
        ).scalar_one()
        == 1
    )


@pytest.mark.story("19.2", ac=8)
def test_approving_on_a_planning_event_records_no_status_change(coordinator_client, db: Session):
    event = _planning_event(db)
    request = make_change_request(db, event=event)

    assert _approve(coordinator_client, request).status_code == 200
    assert _history(db, event.id) == []
