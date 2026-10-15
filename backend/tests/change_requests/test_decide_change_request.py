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

Phase 1 (agreed 16 Oct 2026): the queue, both decisions, who may make them, the reason, and the
decision's record, notification and atomicity. Only an expected attendance change can be approved
yet, and only on a Planning event. Every other approval would have to move bookings, equipment
holds or the event's status, which is Phase 2, so until then it is refused with 409 and changes
nothing (AC5, AC8 below), rather than applied without those checks. An attendance change is
judged by the rules that hold today: a venue requirement may not need more room than the
attendance (2.7 AC6), and a rise a live booking was not made for waits for Phase 2. Rejecting
works for every field and on Confirmed events too, since it changes nothing.

Excluded, with reason:
* What the queue and dialogs show, and the reason box blocking a blank reason before sending
  (AC4's client-side half), are UI behaviour, proven in tests/e2e/change-request-decisions.spec.ts.
* Two decisions truly at once need two database connections; these tests share the test's one
  connection, so the other decision is simulated by changing the request just before deciding,
  as 19.1 AC10 does. The event's row lock, which 19.1's withdrawal also takes, serialises the
  real race.
* Releasing affected bookings and holds (AC5), and returning a Confirmed event to Planning (AC8),
  are Phase 2.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, object_session

from app.events.models import Event, EventStatus
from tests.support.factories import (
    future_datetime,
    make_booking,
    make_change_request,
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
def test_queue_holds_only_pending_requests_on_my_open_events(coordinator_client, db: Session):
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
    cancelled = make_change_request(db, event=_planning_event(db, status=EventStatus.CANCELLED))
    confirmed = make_change_request(db, event=_planning_event(db, status=EventStatus.CONFIRMED))

    listed = {row["id"] for row in coordinator_client.get("/change-requests").json()}

    assert str(waiting.id) in listed
    assert str(confirmed.id) in listed  # it can still be rejected (Phase 1) and decided (Phase 2)
    for left_out in (*decided, others, cancelled):
        assert str(left_out.id) not in listed


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


# --- AC5: approvals that would move arrangements wait for Phase 2 ----------------------------


@pytest.mark.story("19.2", ac=5)
@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("schedule", "A change to the date and time cannot be approved yet."),
        ("venue_requirements", "A change to the venue requirements cannot be approved yet."),
        ("equipment", "A change to the equipment cannot be approved yet."),
    ],
)
def test_changes_that_move_arrangements_cannot_be_approved_yet(
    coordinator_client, db: Session, field, message
):
    event = _planning_event(db)
    request = make_change_request(db, event=event, field=field, current=[], proposed=[])

    response = _approve(coordinator_client, request)

    assert response.status_code == 409
    assert response.json()["detail"] == message
    _assert_undecided(db, request)
    _assert_nothing_sent_or_logged(db, request)


@pytest.mark.story("19.2", ac=5)
@pytest.mark.parametrize("is_for_requirement", [True, False])
def test_attendance_rise_a_booking_was_not_made_for_cannot_be_approved_yet(
    coordinator_client, db: Session, is_for_requirement
):
    """A requirement with no number of its own, or an additional venue, holds the event's
    attendance (12.1 AC2), so a rise past what was booked would need the booking released."""
    event = _planning_event(db, expected_attendance=100)
    requirement_id = (
        make_venue_requirement(db, event.id, capacity=None) if is_for_requirement else None
    )
    venue = make_venue(db, name="Harbour Room", capacity=300)
    booking = make_booking(
        db,
        event_id=event.id,
        venue_id=venue.id,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        expected_attendance=100,
        status="APPROVED",
        venue_requirement_id=requirement_id,
        hold_expires_at=event.starts_at - timedelta(days=1),
    )
    request = make_change_request(db, event=event, current=100, proposed=150)

    response = _approve(coordinator_client, request)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "The booking of Harbour Room holds fewer people than the proposed attendance, so this "
        "change cannot be approved yet."
    )
    assert _attendance(db, event.id) == 100
    assert (
        db.execute(
            text("SELECT status FROM venue_bookings WHERE id = :b"), {"b": booking.id}
        ).scalar_one()
        == "APPROVED"
    )
    _assert_undecided(db, request)


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
        "The expected attendance has changed since this request was raised, so it cannot be "
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


# --- AC8: Confirmed and Awaiting safety check events wait for Phase 2 ------------------------


@pytest.mark.story("19.2", ac=8)
@pytest.mark.parametrize("status", ["CONFIRMED", "AWAITING_SAFETY_CHECK"])
def test_approval_past_planning_cannot_be_made_yet(coordinator_client, db: Session, status):
    """Approving here must return the event to Planning for a new safety check (AC8), which is
    Phase 2, so for now it is refused and the event keeps its status."""
    event = _planning_event(db, status=status, expected_attendance=100)
    request = make_change_request(db, event=event, current=100, proposed=80)

    response = _approve(coordinator_client, request)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        f"This event is {status}, so its change requests cannot be approved yet."
    )
    assert _event_status(db, event.id) == status
    assert _attendance(db, event.id) == 100
    _assert_undecided(db, request)


@pytest.mark.story("19.2", ac=8)
@pytest.mark.parametrize("status", ["CONFIRMED", "AWAITING_SAFETY_CHECK"])
def test_rejecting_past_planning_leaves_the_status(coordinator_client, db: Session, status):
    event = _planning_event(db, status=status)
    request = make_change_request(db, event=event)

    assert _reject(coordinator_client, request).status_code == 200
    assert _event_status(db, event.id) == status
