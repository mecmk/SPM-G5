"""Story 4.5 - be: reject event request with reason.

AC1 A reason must be provided when rejecting.
AC2 The event's status changes to rejected and it leaves the review queue.
AC3 The reason and the deciding coordinator are visible to the organiser.
AC4 A rejected request cannot be approved afterwards without a new submission.
AC5 (Fix f4.5.1) Rejecting releases the event's equipment in the same transaction: every hold is
    released, every open equipment request is closed as Cancelled at the decision time (a declined
    one stays Declined), and Technical Support are told of the requests they had been sent. A
    refused rejection releases nothing.

Excluded, with reason:
* A genuine multi-connection concurrency test - same reasoning as ``test_approve_event.py``.
* Organiser notification - story 20.1's, tested in
  ``tests/notifications/test_generate_and_route_notifications.py``.
* "without a new submission" (AC4) - re-submitting a fresh request is a different story (2.x
  epic); this file only proves the rejected request itself can no longer be approved.

AC5 releases a rejected event's equipment as story 6.2 releases a cancelled one's, and deletes
nothing. Approval (4.4) shares the decision with rejection and releases nothing. Technical Support
keep the items they were sent in their queue, under Cancelled or Declined - 15.2 AC5 as amended
by f4.5.1, tested here as 15.2's.
No venue booking or registration can exist before approval, so there is nothing else to release.
Excluded: a real two-connection race with Technical Support's decision - the rejection's guarded
update waits on the event row lock that decision holds, as the approval's does (see above).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.events import service
from app.events.models import (
    EquipmentHoldStatus,
    EquipmentRequestStatus,
    EquipmentReservation,
    Event,
    EventEquipmentRequest,
    EventStatus,
)
from app.notifications.models import Notification
from tests.support.factories import (
    make_equipment_item,
    make_equipment_type,
    make_event,
    make_venue_requirement,
)
from tests.support.seed import Events, Users


# --- AC1: a reason must be provided when rejecting --------------------------------------------
@pytest.mark.story("4.5", ac=1)
def test_rejection_without_reason_is_refused(coordinator_client):
    response = coordinator_client.post(f"/events/{Events.SUBMITTED}/reject", json={})
    assert response.status_code == 422


@pytest.mark.story("4.5", ac=1)
def test_rejection_with_an_empty_reason_is_refused(coordinator_client):
    response = coordinator_client.post(f"/events/{Events.SUBMITTED}/reject", json={"reason": ""})
    assert response.status_code == 422


@pytest.mark.story("4.5", ac=1)
def test_rejection_with_a_whitespace_only_reason_is_refused(coordinator_client, db: Session):
    response = coordinator_client.post(f"/events/{Events.SUBMITTED}/reject", json={"reason": "   "})

    assert response.status_code == 422
    db.expire_all()
    row = db.execute(
        text("SELECT status, decision_reason FROM events WHERE id = :id"),
        {"id": Events.SUBMITTED},
    ).one()
    assert row.status == EventStatus.UNDER_REVIEW
    assert row.decision_reason is None


@pytest.mark.story("4.5", ac=1)
def test_rejection_with_an_unknown_field_is_refused(coordinator_client):
    # Every sibling request schema sets extra="forbid" (schemas.py); EventRejection should too,
    # rather than silently drop a key like "status" that looks like it might do something.
    response = coordinator_client.post(
        f"/events/{Events.SUBMITTED}/reject",
        json={"reason": "Budget cut.", "status": "PLANNING"},
    )
    assert response.status_code == 422


@pytest.mark.story("4.5", ac=1)
def test_reject_event_refuses_a_blank_reason_even_bypassing_the_schema(db: Session):
    # AC1's mandatory-reason rule is enforced again in the service (service.py's reject_event),
    # not only by EventRejection's Pydantic validator, so a caller other than this HTTP endpoint
    # (a future 4.6 clarification flow, 6.5 cancellation, a seed script) cannot persist a
    # REJECTED request with no reason.
    event = make_event(
        db, status=EventStatus.UNDER_REVIEW, assigned_coordinator_id=Users.COORDINATOR.id
    )
    coordinator = db.get(User, Users.COORDINATOR.id)

    with pytest.raises(service.MissingDecisionReason):
        service.reject_event(db, event, actor=coordinator, reason="   ")


@pytest.mark.story("4.5", ac=1)
def test_rejection_with_a_reason_succeeds_and_strips_it(coordinator_client, db: Session):
    response = coordinator_client.post(
        f"/events/{Events.SUBMITTED}/reject",
        json={"reason": "  Venue capacity insufficient.  "},
    )

    assert response.status_code == 200
    assert response.json()["decision_reason"] == "Venue capacity insufficient."

    db.expire_all()
    row = db.execute(
        text("SELECT decision_reason FROM events WHERE id = :id"), {"id": Events.SUBMITTED}
    ).one()
    assert row.decision_reason == "Venue capacity insufficient."


@pytest.mark.story("4.5", ac=1)
def test_rejecting_a_missing_event_is_404(coordinator_client):
    response = coordinator_client.post(
        f"/events/{uuid.uuid4()}/reject", json={"reason": "No reason needed for the check."}
    )
    assert response.status_code == 404


# --- AC2: status changes to REJECTED and leaves the review queue ------------------------------
@pytest.mark.story("4.5", ac=2)
def test_rejecting_from_under_review_is_allowed(coordinator_client):
    response = coordinator_client.post(
        f"/events/{Events.UNDER_REVIEW}/reject", json={"reason": "Does not fit the venue calendar."}
    )

    assert response.status_code == 200
    assert response.json()["status"] == EventStatus.REJECTED


@pytest.mark.story("4.5", ac=2)
def test_rejecting_from_clarification_requested_is_allowed(coordinator_client):
    # Rejecting is allowed from the same statuses as approving (service.reject_event).
    response = coordinator_client.post(
        f"/events/{Events.CLARIFICATION_REQUESTED}/reject",
        json={"reason": "Clarification did not resolve the clash."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == EventStatus.REJECTED


@pytest.mark.story("4.5", ac=2)
@pytest.mark.parametrize(
    "status",
    [
        EventStatus.PLANNING,
        EventStatus.CONFIRMED,
        EventStatus.COMPLETED,
        EventStatus.CANCELLED,
        EventStatus.REJECTED,
    ],
)
def test_rejecting_a_request_not_awaiting_decision_is_refused(
    coordinator_client, db: Session, status
):
    event = make_event(db, status=status, assigned_coordinator_id=Users.COORDINATOR.id)

    response = coordinator_client.post(
        f"/events/{event.id}/reject", json={"reason": "Refused for the boundary check."}
    )

    assert response.status_code == 409
    db.expire_all()
    row = db.execute(
        text("SELECT status, decided_by_id, decision_reason FROM events WHERE id = :id"),
        {"id": event.id},
    ).one()
    assert row.status == status
    assert row.decided_by_id is None
    assert row.decision_reason is None


@pytest.mark.story("4.5", ac=2)
def test_rejecting_a_draft_is_not_found(coordinator_client, db: Session):
    # A draft is private to its organiser (service.get_event), so even the coordinator it names
    # cannot see it, let alone decide it.
    event = make_event(db, status=EventStatus.DRAFT, assigned_coordinator_id=Users.COORDINATOR.id)

    response = coordinator_client.post(
        f"/events/{event.id}/reject", json={"reason": "Refused for the boundary check."}
    )

    assert response.status_code == 404


@pytest.mark.story("4.5", ac=2)
def test_rejected_event_leaves_the_review_queue(coordinator_client):
    coordinator_client.post(
        f"/events/{Events.UNDER_REVIEW}/reject", json={"reason": "Duplicate of another request."}
    )

    ids = [row["id"] for row in coordinator_client.get("/events/review-queue").json()]

    assert str(Events.UNDER_REVIEW) not in ids


@pytest.mark.story("4.5", ac=2)
def test_rejection_is_recorded_in_status_history(coordinator_client, db: Session):
    coordinator_client.post(
        f"/events/{Events.UNDER_REVIEW}/reject", json={"reason": "Clashes with another event."}
    )

    row = db.execute(
        text(
            "SELECT from_status, to_status, changed_by_id, reason FROM event_status_history "
            "WHERE event_id = :id AND to_status = 'REJECTED'"
        ),
        {"id": Events.UNDER_REVIEW},
    ).one()
    assert row.from_status == EventStatus.UNDER_REVIEW
    assert row.changed_by_id == Users.COORDINATOR.id
    assert row.reason == "Clashes with another event."


# --- AC3: the reason and the deciding coordinator are visible to the organiser ----------------
@pytest.mark.story("4.5", ac=3)
def test_owning_organiser_can_read_the_rejection_reason(login_as):
    # Events.SUBMITTED is an UNDER_REVIEW event (migration 002) owned by this organiser.
    login_as(Users.COORDINATOR).post(
        f"/events/{Events.SUBMITTED}/reject",
        json={"reason": "Accessibility requirements cannot be met at any available venue."},
    )

    response = login_as(Users.ORGANISER).get(f"/events/{Events.SUBMITTED}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == EventStatus.REJECTED
    assert (
        body["decision_reason"]
        == "Accessibility requirements cannot be met at any available venue."
    )
    assert body["decided_by_name"] == Users.COORDINATOR.full_name


@pytest.mark.story("4.5", ac=3)
def test_rejection_is_recorded_in_the_audit_log(coordinator_client, db: Session):
    coordinator_client.post(
        f"/events/{Events.UNDER_REVIEW}/reject", json={"reason": "No suitable venue is free."}
    )

    row = db.execute(
        text(
            "SELECT actor_id, details FROM audit_log "
            "WHERE action = 'EVENT_REJECTED' AND entity_id = :id"
        ),
        {"id": Events.UNDER_REVIEW},
    ).one()
    assert row.actor_id == Users.COORDINATOR.id
    assert row.details["reason"] == "No suitable venue is free."


# --- AC4: a rejected request cannot be approved afterwards -------------------------------------
@pytest.mark.story("4.5", ac=4)
def test_a_rejected_request_cannot_then_be_approved(coordinator_client, db: Session):
    rejected = coordinator_client.post(
        f"/events/{Events.UNDER_REVIEW}/reject", json={"reason": "Budget was not approved."}
    )
    assert rejected.status_code == 200

    approved = coordinator_client.post(f"/events/{Events.UNDER_REVIEW}/approve")

    assert approved.status_code == 409
    db.expire_all()
    row = db.execute(
        text("SELECT status, decision_reason FROM events WHERE id = :id"),
        {"id": Events.UNDER_REVIEW},
    ).one()
    assert row.status == EventStatus.REJECTED
    assert row.decision_reason == "Budget was not approved."


@pytest.mark.story("4.5", ac=4)
def test_the_seeded_rejected_event_cannot_be_approved(login_as):
    response = login_as(Users.COORDINATOR_2).post(f"/events/{Events.REJECTED}/approve")
    assert response.status_code == 409


# --- Permissions / relationship refusals -------------------------------------------------------
@pytest.mark.story("4.5", ac=1)
def test_signed_out_visitors_cannot_reject_an_event(client):
    response = client.post(
        f"/events/{Events.SUBMITTED}/reject", json={"reason": "No session, should be refused."}
    )
    assert response.status_code == 401


@pytest.mark.story("4.5", ac=1)
@pytest.mark.parametrize(
    "user",
    [Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda u: u.role,
)
def test_other_roles_cannot_reject_an_event(client, user):
    client.login(user)
    response = client.post(
        f"/events/{Events.SUBMITTED}/reject", json={"reason": "Wrong role, should be refused."}
    )
    assert response.status_code == 403


@pytest.mark.story("4.5", ac=1)
def test_a_different_coordinator_cannot_reject_the_request(login_as, db: Session):
    response = login_as(Users.COORDINATOR_2).post(
        f"/events/{Events.UNDER_REVIEW}/reject", json={"reason": "Not my request to decide."}
    )

    assert response.status_code == 403
    db.expire_all()
    row = db.execute(
        text("SELECT status FROM events WHERE id = :id"), {"id": Events.UNDER_REVIEW}
    ).one()
    assert row.status == EventStatus.UNDER_REVIEW


@pytest.mark.story("4.5", ac=1)
def test_an_unassigned_request_cannot_be_rejected(coordinator_client, db: Session):
    event = make_event(db, status=EventStatus.UNDER_REVIEW)  # no assigned_coordinator_id

    response = coordinator_client.post(
        f"/events/{event.id}/reject", json={"reason": "No coordinator is assigned yet."}
    )

    assert response.status_code == 403


# --- Fix f4.5.1: a rejection releases the event's equipment, as 6.2's cancellation does ---------
STARTS_AT = datetime(2030, 5, 6, 1, 0, tzinfo=UTC)
ENDS_AT = datetime(2030, 5, 6, 9, 0, tzinfo=UTC)
REASON = "No suitable venue is free."
# The item statuses that hold units.
HELD_ITEM_STATUSES = (
    EquipmentRequestStatus.REQUESTED,
    EquipmentRequestStatus.PENDING,
    EquipmentRequestStatus.ACCEPTED,
)


def _awaiting(db: Session, status: str = EventStatus.UNDER_REVIEW) -> Event:
    """Olivia's request awaiting Chloe's decision, dated in 2030 so no seeded hold is in the way."""
    return make_event(
        db,
        status=status,
        starts_at=STARTS_AT,
        ends_at=ENDS_AT,
        assigned_coordinator_id=Users.COORDINATOR.id,
    )


def _item(db: Session, event: Event, *, status: str, is_held: bool = True):
    """An equipment item of a fresh type on ``event``, so nothing else holds that type. A sent
    one records when it was sent, as 15.1's submission does."""
    sent = {} if status == EquipmentRequestStatus.REQUESTED else {"submitted_at": datetime.now(UTC)}
    return make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db),
        quantity=2,
        status=status,
        is_held=is_held,
        **sent,
    )


def _reject(client, event_id: uuid.UUID, reason: str = REASON):
    return client.post(f"/events/{event_id}/reject", json={"reason": reason})


def _held(db: Session, event_id: uuid.UUID) -> list[str]:
    db.expire_all()
    return list(
        db.scalars(
            select(EquipmentReservation.status).where(EquipmentReservation.event_id == event_id)
        )
    )


@pytest.mark.story("4.5", ac=5)
@pytest.mark.parametrize("status", [EventStatus.UNDER_REVIEW, EventStatus.CLARIFICATION_REQUESTED])
def test_rejecting_releases_every_equipment_hold(coordinator_client, db: Session, status):
    event = _awaiting(db, status)
    items = [_item(db, event, status=item_status) for item_status in HELD_ITEM_STATUSES]

    assert _reject(coordinator_client, event.id).status_code == 200, "rejection refused"

    assert _held(db, event.id) == [EquipmentHoldStatus.RELEASED] * len(items)
    free = service.available_by_type(db, STARTS_AT, ENDS_AT)
    for item in items:
        assert free[item.equipment_type_id] == item.equipment_type.total_quantity


@pytest.mark.story("4.5", ac=5)
def test_rejecting_closes_open_items_and_keeps_declined_ones(coordinator_client, db: Session):
    """Every open item is closed as Cancelled at the decision's time, and kept for the record; a
    declined one stays Technical Support's decision. Nothing is deleted."""
    event = _awaiting(db)
    open_items = [_item(db, event, status=item_status) for item_status in HELD_ITEM_STATUSES]
    open_items.append(_item(db, event, status=EquipmentRequestStatus.UNAVAILABLE, is_held=False))
    declined = _item(db, event, status=EquipmentRequestStatus.DECLINED, is_held=False)

    def counts() -> list[int]:
        return [
            db.scalar(select(func.count()).select_from(table).where(table.event_id == event.id))
            for table in (EventEquipmentRequest, EquipmentReservation)
        ]

    before = counts()
    assert _reject(coordinator_client, event.id).status_code == 200

    db.expire_all()
    decided_at = db.get(Event, event.id).decided_at
    for item in open_items:
        closed = db.get(EventEquipmentRequest, item.id)
        assert (closed.status, closed.cancelled_at) == (
            EquipmentRequestStatus.CANCELLED,
            decided_at,
        )
    assert db.get(EventEquipmentRequest, declined.id).status == EquipmentRequestStatus.DECLINED
    assert counts() == before


@pytest.mark.story("4.5", ac=5)
@pytest.mark.parametrize(
    ("status", "is_told"),
    [
        (EquipmentRequestStatus.PENDING, True),
        (EquipmentRequestStatus.ACCEPTED, True),
        (EquipmentRequestStatus.REQUESTED, False),
    ],
)
def test_technical_support_are_told_of_items_sent_to_them(
    coordinator_client, db: Session, status, is_told
):
    """An item only recorded was never sent to Technical Support, so nothing changed for them.
    The notice says the rejection withdrew it, not a cancellation."""
    event = _awaiting(db)
    item = _item(db, event, status=status)

    assert _reject(coordinator_client, event.id).status_code == 200

    notices = db.scalars(
        select(Notification).where(
            Notification.notification_type == "EQUIPMENT_WITHDRAWN",
            Notification.event_id == event.id,
        )
    ).all()
    assert [notice.recipient_id for notice in notices] == (
        [Users.TECH_SUPPORT.id] if is_told else []
    )
    for notice in notices:
        assert notice.message == (
            f'Rejecting "{event.name}" withdrew equipment sent to you: '
            f"{item.equipment_type.name} ×2."
        )


@pytest.mark.story("4.5", ac=5)
def test_the_rejection_audit_names_the_equipment_it_released(coordinator_client, db: Session):
    event = _awaiting(db)
    item = _item(db, event, status=EquipmentRequestStatus.PENDING)

    assert _reject(coordinator_client, event.id).status_code == 200

    row = db.execute(
        text("SELECT details FROM audit_log WHERE action = 'EVENT_REJECTED' AND entity_id = :id"),
        {"id": event.id},
    ).one()
    assert row.details["cancelled_equipment_ids"] == [str(item.id)]


@pytest.mark.story("4.5", ac=5)
@pytest.mark.parametrize(
    ("user", "status", "reason", "code"),
    [
        (Users.COORDINATOR_2, EventStatus.UNDER_REVIEW, REASON, 403),
        (Users.COORDINATOR, EventStatus.PLANNING, REASON, 409),
        (Users.COORDINATOR, EventStatus.UNDER_REVIEW, "   ", 422),
    ],
    ids=["another_coordinator", "not_awaiting_decision", "blank_reason"],
)
def test_a_refused_rejection_releases_nothing(login_as, db: Session, user, status, reason, code):
    event = _awaiting(db, status)
    item = _item(db, event, status=EquipmentRequestStatus.PENDING)

    assert _reject(login_as(user), event.id, reason).status_code == code

    assert _held(db, event.id) == [EquipmentHoldStatus.RESERVED]
    assert db.get(EventEquipmentRequest, item.id).status == EquipmentRequestStatus.PENDING


@pytest.mark.story("4.5", ac=5)
def test_approving_keeps_the_equipment_held(coordinator_client, db: Session):
    """``_decide`` is shared with approval (4.4), and only a rejection releases: an approved
    event goes on to planning with its holds and items as they were."""
    event = _awaiting(db)
    make_venue_requirement(db, event.id)  # approval needs one (f2.7.4)
    items = [_item(db, event, status=item_status) for item_status in HELD_ITEM_STATUSES]

    assert coordinator_client.post(f"/events/{event.id}/approve").status_code == 200

    assert _held(db, event.id) == [EquipmentHoldStatus.RESERVED] * len(items)
    assert [db.get(EventEquipmentRequest, item.id).status for item in items] == list(
        HELD_ITEM_STATUSES
    )


def _queue_ids(client, **params) -> list[str]:
    """Every id in one tab of Technical Support's queue, which is not paged."""
    return [item["id"] for item in client.get("/equipment-requests", params=params).json()["items"]]


@pytest.mark.story("15.2", ac=5)
@pytest.mark.parametrize(
    "status", [EquipmentRequestStatus.PENDING, EquipmentRequestStatus.ACCEPTED]
)
def test_technical_support_see_a_rejected_events_sent_item_under_cancelled_and_all(
    login_as, db: Session, status
):
    """As 6.2 AC15 keeps a cancelled event's sent items, for Technical Support's record."""
    event = _awaiting(db)
    item = _item(db, event, status=status)
    before = login_as(Users.TECH_SUPPORT).get("/equipment-requests").json()["counts"]

    assert _reject(login_as(Users.COORDINATOR), event.id).status_code == 200

    tech = login_as(Users.TECH_SUPPORT)
    assert str(item.id) in _queue_ids(tech, status="CANCELLED")
    assert str(item.id) in _queue_ids(tech)
    after = tech.get("/equipment-requests").json()["counts"]
    assert after["cancelled"] == before["cancelled"] + 1
    assert after[status.lower()] == before[status.lower()] - 1
    page = tech.get(f"/equipment-requests/{item.id}")
    assert page.status_code == 200, page.text
    assert page.json()["status"] == EquipmentRequestStatus.CANCELLED


@pytest.mark.story("15.2", ac=5)
def test_technical_support_keep_a_declined_item_on_a_rejected_event(login_as, db: Session):
    """A declined item stays Declined, and stays in their queue as the record of their decision,
    as 6.2 AC15 keeps one on a cancelled event."""
    event = _awaiting(db)
    item = _item(db, event, status=EquipmentRequestStatus.DECLINED, is_held=False)
    before = login_as(Users.TECH_SUPPORT).get("/equipment-requests").json()["counts"]

    assert _reject(login_as(Users.COORDINATOR), event.id).status_code == 200

    tech = login_as(Users.TECH_SUPPORT)
    assert str(item.id) in _queue_ids(tech, status="DECLINED")
    assert str(item.id) in _queue_ids(tech)
    assert str(item.id) not in _queue_ids(tech, status="CANCELLED")
    assert tech.get("/equipment-requests").json()["counts"] == before
    page = tech.get(f"/equipment-requests/{item.id}")
    assert page.status_code == 200, page.text
    assert page.json()["status"] == EquipmentRequestStatus.DECLINED
