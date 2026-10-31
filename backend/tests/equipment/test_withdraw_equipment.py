"""Story 17.2 - withdraw booked equipment.

As an Event Coordinator, I want to be able to withdraw my booked equipment so that I can remove the
equipment that I do not need anymore.

AC1  On the event page's Equipment requirements section, the assigned coordinator can withdraw an
     item Technical Support has accepted, after confirming. The reserved units are released at
     once and become available to other events over that period.
AC2  An item sent to Technical Support and still awaiting their decision (Pending) can be withdrawn
     the same way, rather than deleted, so Technical Support know it is no longer needed. Items not
     yet sent are still simply removed (15.1 AC2).
AC3  A withdrawn item stays on the event page as Withdrawn, with who withdrew it and when. It no
     longer counts towards the event's equipment, and the coordinator can request that equipment
     type again (15.1).
AC4  Technical Support are notified of each withdrawal, naming the event, the equipment and the
     quantity. In their queue the item shows as Withdrawn, read-only, with no Accept or Decline.
AC5  Equipment can be withdrawn while the event is Under Review, Clarification Requested or
     Planning. Once it is Awaiting Safety Check, Confirmed, Completed, Cancelled or Rejected,
     Withdraw is not offered and an attempt is refused.
AC6  Only Pending and Accepted items can be withdrawn. Declined, cancelled and already-withdrawn
     items hold nothing to release.
AC7  Closing the confirmation leaves the item unchanged.
AC8  Withdrawing the event's last item leaves it with no equipment, which does not stop it going
     for its safety check (21.2 AC11).
AC9  If the event already has a safety approval, withdrawing equipment changes what was approved,
     so the event needs a new safety review before it can be confirmed (21.2 AC14).
AC10 Only the event's assigned coordinator can withdraw equipment. The organiser sees withdrawn
     items read-only; other users are refused.
AC11 If Technical Support accept or decline an item at the moment it is withdrawn, whichever is
     saved first wins and the other is shown the item's current status. A double-click withdraws
     once.

A withdrawal is a resource (backend/STYLE.md: a URL names a resource), created with
``POST /events/{id}/equipment/{item_id}/withdrawal``, as 16.1's decision is. It names the status
the coordinator saw (``expected_status``), so a decision Technical Support saved meanwhile is not
withdrawn over unseen (AC11).

The confirmation and closing it (AC1, AC7), Withdraw replacing Remove on a sent item (AC2), the
type offered again in the Add equipment list (AC3), the queue card with no Accept or Decline (AC4)
and the organiser's read-only view (AC10) are proven at e2e: tests/e2e/equipment-withdrawal.spec.ts.
Withdraw not being offered on a closed event (AC5) is the event page's existing ``canChange``,
which 15.1's e2e spec already covers; the refusal of a direct request is here.

Every case uses a fresh equipment type (``make_equipment_type``), so a test owns its whole stock,
on factory events dated November 2027, clear of every seeded hold.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.common.audit import AuditLog
from app.equipment import schemas, service
from app.events.models import (
    EquipmentReservation,
    EquipmentType,
    Event,
    EventEquipmentRequest,
    EventStatus,
)
from app.notifications.models import Notification
from app.safety.models import EventSafetyReview, SafetyReviewOutcome
from app.safety.service import current_facts
from tests.support.change_requests import approve_as_seen
from tests.support.factories import (
    make_equipment_item,
    make_equipment_type,
    make_event,
    make_secured_event,
    make_user,
)
from tests.support.seed import Users

TECH_SUPPORT_ROLE = "TECH_SUPPORT_STAFF"
PENDING, ACCEPTED, DECLINED, WITHDRAWN = "PENDING", "ACCEPTED", "DECLINED", "WITHDRAWN"
RESERVED = "RESERVED"

SGT = timezone(timedelta(hours=8))
START = datetime(2027, 11, 8, 9, 0, tzinfo=SGT)
END = datetime(2027, 11, 8, 17, 0, tzinfo=SGT)

OPEN_EVENT_STATUSES = (
    EventStatus.UNDER_REVIEW,
    EventStatus.CLARIFICATION_REQUESTED,
    EventStatus.PLANNING,
)
CLOSED_EVENT_STATUSES = (
    EventStatus.AWAITING_SAFETY_CHECK,
    EventStatus.CONFIRMED,
    EventStatus.COMPLETED,
    EventStatus.CANCELLED,
    EventStatus.REJECTED,
)

EVENT_CLOSED_MESSAGE = "This event is {status}, so its equipment can no longer be changed."
NOT_ASSIGNED_MESSAGE = "Only the coordinator assigned to this event can change its equipment."
ALREADY_WITHDRAWN_MESSAGE = "This equipment item has already been withdrawn."
NOT_WITHDRAWABLE_MESSAGES = {
    "REQUESTED": (
        "This equipment item has not been sent to Technical Support yet, so remove it instead."
    ),
    "UNAVAILABLE": (
        "This equipment item no longer fits the event's dates and holds nothing, so remove it "
        "instead."
    ),
    DECLINED: "Technical Support declined this equipment item, so there is nothing to withdraw.",
    "CANCELLED": "This equipment item was cancelled, so there is nothing to withdraw.",
    WITHDRAWN: ALREADY_WITHDRAWN_MESSAGE,
}
STATUS_CHANGED_MESSAGE = "This equipment item is now {status}. Check it before you withdraw it."
WITHDRAW_INSTEAD_MESSAGE = (
    "This equipment item has been sent to Technical Support, so withdraw it instead of removing it."
)
DECISION_ON_WITHDRAWN_MESSAGE = "This equipment request was withdrawn by its coordinator."


def _withdrawal_path(event_id: uuid.UUID, item_id: uuid.UUID) -> str:
    return f"/events/{event_id}/equipment/{item_id}/withdrawal"


def _event(db: Session, **extra) -> Event:
    return make_event(
        db,
        status=extra.pop("status", EventStatus.PLANNING),
        assigned_coordinator_id=extra.pop("assigned_coordinator_id", Users.COORDINATOR.id),
        starts_at=START,
        ends_at=END,
        **extra,
    )


def _sent(
    db: Session,
    *,
    status: str = ACCEPTED,
    quantity: int = 3,
    event: Event | None = None,
    equipment_type: EquipmentType | None = None,
) -> EventEquipmentRequest:
    """An item the coordinator sent to Technical Support, holding its units, Pending or Accepted."""
    return make_equipment_item(
        db,
        event=event if event is not None else _event(db),
        equipment_type=equipment_type if equipment_type is not None else make_equipment_type(db),
        quantity=quantity,
        status=status,
        is_held=status in (PENDING, ACCEPTED),
        submitted_by_id=Users.COORDINATOR.id,
        submitted_at=datetime(2026, 10, 1, 9, 0, tzinfo=SGT),
    )


def _withdraw(client, item: EventEquipmentRequest, *, expected_status: str | None = None):
    """Withdraw ``item`` as ``client``, naming the status the coordinator saw - by default the
    one it has."""
    return client.post(
        _withdrawal_path(item.event_id, item.id),
        json={"expected_status": expected_status or item.status},
    )


def _fresh(db: Session, item: EventEquipmentRequest) -> EventEquipmentRequest:
    db.expire_all()
    return db.get(EventEquipmentRequest, item.id)


def _reserved(db: Session, item: EventEquipmentRequest) -> list[EquipmentReservation]:
    db.expire_all()
    return list(
        db.scalars(
            select(EquipmentReservation).where(
                EquipmentReservation.equipment_request_id == item.id,
                EquipmentReservation.status == RESERVED,
            )
        )
    )


def _available_to(client, event_id: uuid.UUID, code: str) -> int:
    response = client.get(f"/events/{event_id}/equipment-availability")
    assert response.status_code == 200, response.text
    return {row["equipment_type_code"]: row["available"] for row in response.json()}[code]


def _assert_unchanged(db: Session, item: EventEquipmentRequest, status: str) -> None:
    """A refused withdrawal changed nothing: the status, the hold and the audit log are as they
    were, and nobody was told."""
    after = _fresh(db, item)
    assert after.status == status
    assert after.withdrawn_at is None
    assert len(_reserved(db, item)) == (1 if status in (PENDING, ACCEPTED) else 0)
    assert _withdrawal_audits(db, item) == []
    assert _withdrawal_notices(db, item.event_id) == []


def _withdrawal_audits(db: Session, item: EventEquipmentRequest) -> list[AuditLog]:
    return [
        row
        for row in db.scalars(
            select(AuditLog).where(
                AuditLog.entity_id == item.event_id, AuditLog.action == "EQUIPMENT_WITHDRAWN"
            )
        )
        if row.details.get("item_id") == str(item.id)
    ]


def _withdrawal_notices(db: Session, event_id: uuid.UUID) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification).where(
                Notification.event_id == event_id,
                Notification.notification_type == "EQUIPMENT_WITHDRAWN",
            )
        )
    )


def _active_tech_support_ids(db: Session) -> set[uuid.UUID]:
    return set(
        db.scalars(
            select(User.id).where(User.role_code == TECH_SUPPORT_ROLE, User.is_active.is_(True))
        )
    )


# --- AC1/AC2: withdraw an accepted or pending item, releasing its units at once -------------------
@pytest.mark.story("17.2", ac=1)
@pytest.mark.story("17.2", ac=2)
@pytest.mark.parametrize("status", [ACCEPTED, PENDING])
def test_withdrawing_releases_the_units_to_other_events_at_once(
    coordinator_client, db: Session, status
):
    kit = make_equipment_type(db, total_quantity=3)
    item = _sent(db, status=status, quantity=3, equipment_type=kit)
    other = _event(db)
    assert _available_to(coordinator_client, other.id, kit.code) == 0

    response = _withdraw(coordinator_client, item)

    assert response.status_code == 201, response.text
    assert response.json()["status"] == WITHDRAWN
    assert _fresh(db, item).status == WITHDRAWN
    assert _reserved(db, item) == []
    assert _available_to(coordinator_client, other.id, kit.code) == 3


@pytest.mark.story("17.2", ac=2)
def test_a_pending_item_cannot_be_deleted_and_must_be_withdrawn(coordinator_client, db: Session):
    item = _sent(db, status=PENDING)

    response = coordinator_client.delete(f"/events/{item.event_id}/equipment/{item.id}")

    assert response.status_code == 409
    assert response.json()["detail"] == WITHDRAW_INSTEAD_MESSAGE
    _assert_unchanged(db, item, PENDING)


# --- AC3: kept on the event page, no longer counted -----------------------------------------------
@pytest.mark.story("17.2", ac=3)
@pytest.mark.story("17.2", ac=10)
def test_a_withdrawn_item_stays_listed_with_who_withdrew_it_and_when(login_as, db: Session):
    item = _sent(db)

    assert _withdraw(login_as(Users.COORDINATOR), item).status_code == 201

    organiser = login_as(Users.ORGANISER)
    [line] = organiser.get(f"/events/{item.event_id}").json()["equipment"]
    assert line["id"] == str(item.id)
    assert line["status"] == WITHDRAWN
    assert line["withdrawn_by_name"] == Users.COORDINATOR.full_name
    withdrawn_at = datetime.fromisoformat(line["withdrawn_at"])
    assert abs(withdrawn_at - datetime.now(UTC)) < timedelta(minutes=5)
    [audit] = _withdrawal_audits(db, item)
    assert audit.actor_id == Users.COORDINATOR.id
    assert audit.details["quantity"] == item.quantity


@pytest.mark.story("17.2", ac=3)
def test_the_type_can_be_requested_again_once_withdrawn(coordinator_client, db: Session):
    kit = make_equipment_type(db, total_quantity=3)
    item = _sent(db, quantity=3, equipment_type=kit)
    assert _withdraw(coordinator_client, item).status_code == 201

    again = coordinator_client.post(
        f"/events/{item.event_id}/equipment", json={"equipment_type_code": kit.code, "quantity": 3}
    )

    assert again.status_code == 201, again.text
    assert again.json()["status"] == "REQUESTED"


@pytest.mark.story("17.2", ac=3)
def test_a_withdrawn_item_is_not_the_events_equipment_for_a_change_request(login_as, db: Session):
    """19.1's current value leaves it out, so asking to remove it is no change, and an approved
    change that does not name it leaves it Withdrawn rather than deleting it (19.2 AC5)."""
    kit = make_equipment_type(db, total_quantity=10)
    item = _sent(db, equipment_type=kit)
    assert _withdraw(login_as(Users.COORDINATOR), item).status_code == 201
    organiser = login_as(Users.ORGANISER)
    url = f"/events/{item.event_id}/change-requests"

    removed = organiser.post(
        url, json={"field": "equipment", "proposed": [], "reason": "Plans have changed."}
    )
    added = organiser.post(
        url,
        json={
            "field": "equipment",
            "proposed": [{"equipment_type_code": kit.code, "quantity": 1}],
            "reason": "Plans have changed.",
        },
    )

    assert removed.status_code == 422, removed.text
    assert added.status_code == 201, added.text
    assert added.json()["current_value"] == []
    db.commit()  # the approval's own rollback on a refusal must not undo the rows above
    approved = approve_as_seen(
        login_as(Users.COORDINATOR), item.event_id, uuid.UUID(added.json()["id"])
    )
    assert approved.status_code == 200, approved.text
    assert _fresh(db, item).status == WITHDRAWN


# --- AC4: Technical Support are told, and see it read-only ----------------------------------------
@pytest.mark.story("17.2", ac=4)
def test_every_active_technical_support_member_is_told_what_was_withdrawn(
    coordinator_client, db: Session
):
    inactive = make_user(db, role=TECH_SUPPORT_ROLE, is_active=False)
    event = _event(db, name="Harbour Lights Gala")
    withdrawn = _sent(db, event=event, equipment_type=make_equipment_type(db, name="Stage monitor"))
    kept = _sent(db, event=event, quantity=2)

    assert _withdraw(coordinator_client, withdrawn).status_code == 201

    notices = _withdrawal_notices(db, event.id)
    assert {notice.recipient_id for notice in notices} == _active_tech_support_ids(db)
    assert inactive.id not in {notice.recipient_id for notice in notices}
    notice = notices[0]
    assert "Harbour Lights Gala" in notice.title
    assert "Stage monitor ×3" in notice.message
    assert kept.equipment_type.name not in notice.message


@pytest.mark.story("17.2", ac=4)
def test_the_queue_lists_it_under_withdrawn_holding_nothing(login_as, db: Session):
    item = _sent(db, status=PENDING)
    before = login_as(Users.TECH_SUPPORT).get("/equipment-requests").json()["counts"]
    assert _withdraw(login_as(Users.COORDINATOR), item).status_code == 201

    tech_client = login_as(Users.TECH_SUPPORT)
    tab = tech_client.get("/equipment-requests?status=WITHDRAWN").json()
    pending = tech_client.get("/equipment-requests?status=PENDING").json()

    [entry] = [row for row in tab["items"] if row["id"] == str(item.id)]
    assert entry["status"] == WITHDRAWN
    assert (entry["available"], entry["shortfall"]) == (None, None)
    assert entry["withdrawn_by_name"] == Users.COORDINATOR.full_name
    assert entry["withdrawn_at"] is not None
    assert str(item.id) not in [row["id"] for row in pending["items"]]
    assert tab["counts"] == {
        **before,
        "pending": before["pending"] - 1,
        "withdrawn": before["withdrawn"] + 1,
    }
    assert tech_client.get(f"/equipment-requests/{item.id}").json()["status"] == WITHDRAWN


@pytest.mark.story("17.2", ac=4)
@pytest.mark.parametrize("outcome", [ACCEPTED, DECLINED])
def test_a_withdrawn_request_cannot_be_decided(login_as, db: Session, outcome):
    item = _sent(db, status=PENDING)
    assert _withdraw(login_as(Users.COORDINATOR), item).status_code == 201
    decision = {"outcome": outcome, "reason": "Not needed." if outcome == DECLINED else None}

    response = login_as(Users.TECH_SUPPORT).post(
        f"/equipment-requests/{item.id}/decision", json=decision
    )

    assert response.status_code == 409
    assert response.json()["detail"] == DECISION_ON_WITHDRAWN_MESSAGE
    assert _fresh(db, item).status == WITHDRAWN


# --- AC5: only while the event's equipment can change ---------------------------------------------
@pytest.mark.story("17.2", ac=5)
@pytest.mark.parametrize("event_status", OPEN_EVENT_STATUSES)
def test_withdrawing_is_allowed_while_the_event_is_open(coordinator_client, db, event_status):
    item = _sent(db, event=_event(db, status=event_status))

    assert _withdraw(coordinator_client, item).status_code == 201


@pytest.mark.story("17.2", ac=5)
@pytest.mark.parametrize("event_status", CLOSED_EVENT_STATUSES)
def test_withdrawing_is_refused_once_the_event_is_closed(coordinator_client, db, event_status):
    item = _sent(db, event=_event(db, status=event_status))

    response = _withdraw(coordinator_client, item)

    assert response.status_code == 409
    assert response.json()["detail"] == EVENT_CLOSED_MESSAGE.format(
        status=event_status.lower().replace("_", " ")
    )
    _assert_unchanged(db, item, ACCEPTED)


# --- AC6: only Pending and Accepted ---------------------------------------------------------------
@pytest.mark.story("17.2", ac=6)
@pytest.mark.parametrize("status", sorted(NOT_WITHDRAWABLE_MESSAGES))
def test_only_a_pending_or_accepted_item_can_be_withdrawn(coordinator_client, db, status):
    item = make_equipment_item(
        db,
        event=_event(db),
        equipment_type=make_equipment_type(db),
        quantity=1,
        status=status,
        is_held=status == "REQUESTED",
    )

    response = _withdraw(coordinator_client, item, expected_status=ACCEPTED)

    assert response.status_code == 409
    assert response.json()["detail"] == NOT_WITHDRAWABLE_MESSAGES[status]
    after = _fresh(db, item)
    assert after.status == status
    assert _withdrawal_audits(db, item) == []


@pytest.mark.story("17.2", ac=6)
@pytest.mark.parametrize("expected_status", ["REQUESTED", "WITHDRAWN", "accepted", None])
def test_the_status_seen_must_be_one_that_can_be_withdrawn(coordinator_client, db, expected_status):
    item = _sent(db)

    response = coordinator_client.post(
        _withdrawal_path(item.event_id, item.id), json={"expected_status": expected_status}
    )

    assert response.status_code == 422
    _assert_unchanged(db, item, ACCEPTED)


# --- AC8/AC9: the safety check --------------------------------------------------------------------
@pytest.mark.story("17.2", ac=8)
def test_withdrawing_the_last_item_does_not_stop_the_safety_check(coordinator_client, db):
    secured = make_secured_event(db)
    assert _withdraw(coordinator_client, secured.equipment).status_code == 201

    response = coordinator_client.post(f"/safety-checks/{secured.event.id}/request", json={})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == EventStatus.AWAITING_SAFETY_CHECK


@pytest.mark.story("17.2", ac=9)
def test_withdrawing_after_a_safety_approval_needs_a_new_review(coordinator_client, db):
    secured = make_secured_event(db)
    db.add(
        EventSafetyReview(
            event_id=secured.event.id,
            reviewed_by_id=Users.SAFETY_OFFICER.id,
            reviewed_at=datetime(2026, 10, 1, tzinfo=UTC),
            outcome=SafetyReviewOutcome.APPROVED,
            facts=current_facts(db, secured.event),
        )
    )
    db.flush()
    assert _withdraw(coordinator_client, secured.equipment).status_code == 201

    response = coordinator_client.post(f"/events/{secured.event.id}/confirm")

    assert response.status_code == 409
    assert "The event's equipment changed after the safety approval" in response.json()["detail"]


# --- AC10: only the assigned coordinator ----------------------------------------------------------
@pytest.mark.story("17.2", ac=10)
def test_another_coordinator_is_refused(login_as, db: Session):
    item = _sent(db)

    response = _withdraw(login_as(Users.COORDINATOR_2), item)

    assert response.status_code == 403
    assert response.json()["detail"] == NOT_ASSIGNED_MESSAGE
    _assert_unchanged(db, item, ACCEPTED)


@pytest.mark.story("17.2", ac=10)
@pytest.mark.parametrize(
    "user", [Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE]
)
def test_other_roles_are_refused(login_as, db: Session, user):
    item = _sent(db)

    assert _withdraw(login_as(user), item).status_code == 403
    _assert_unchanged(db, item, ACCEPTED)


@pytest.mark.story("17.2", ac=10)
def test_a_signed_out_user_is_refused(client, db: Session):
    item = _sent(db)

    assert _withdraw(client, item).status_code == 401
    _assert_unchanged(db, item, ACCEPTED)


@pytest.mark.story("17.2", ac=10)
def test_an_item_of_another_event_or_no_item_is_not_found(coordinator_client, db: Session):
    item = _sent(db)
    other = _event(db)

    elsewhere = coordinator_client.post(
        _withdrawal_path(other.id, item.id), json={"expected_status": ACCEPTED}
    )
    missing = coordinator_client.post(
        _withdrawal_path(item.event_id, uuid.uuid4()), json={"expected_status": ACCEPTED}
    )

    assert (elsewhere.status_code, elsewhere.json()["detail"]) == (404, "Equipment item not found.")
    assert (missing.status_code, missing.json()["detail"]) == (404, "Equipment item not found.")
    _assert_unchanged(db, item, ACCEPTED)


# --- AC11: a decision saved meanwhile, and a double-click -----------------------------------------
@pytest.mark.story("17.2", ac=11)
def test_an_item_accepted_since_it_was_seen_is_not_withdrawn(coordinator_client, db: Session):
    """The coordinator saw it Pending; Technical Support accepted it before the withdrawal was
    saved, so the coordinator is told it is now accepted rather than withdrawing it unseen."""
    item = _sent(db, status=ACCEPTED)

    response = _withdraw(coordinator_client, item, expected_status=PENDING)

    assert response.status_code == 409
    assert response.json()["detail"] == STATUS_CHANGED_MESSAGE.format(status="accepted")
    _assert_unchanged(db, item, ACCEPTED)


@pytest.mark.story("17.2", ac=11)
def test_a_second_withdrawal_is_refused_and_tells_once(coordinator_client, db: Session):
    item = _sent(db)

    first = _withdraw(coordinator_client, item, expected_status=ACCEPTED)
    second = _withdraw(coordinator_client, item, expected_status=ACCEPTED)

    assert first.status_code == 201, first.text
    assert (second.status_code, second.json()["detail"]) == (409, ALREADY_WITHDRAWN_MESSAGE)
    assert len(_withdrawal_audits(db, item)) == 1
    assert len(_withdrawal_notices(db, item.event_id)) == len(_active_tech_support_ids(db))


# --- real races -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class _RaceRows:
    event_id: uuid.UUID
    item_id: uuid.UUID


@contextmanager
def _committed_pending_item(engine) -> Iterator[_RaceRows]:
    """A pending item, committed so other connections see it, then removed with everything the
    race wrote."""
    with Session(engine) as session:
        kit = make_equipment_type(session, name=f"Race kit {uuid.uuid4().hex[:8]}")
        item = _sent(session, status=PENDING, quantity=2, equipment_type=kit)
        session.commit()
        rows = _RaceRows(event_id=item.event_id, item_id=item.id)
        kit_id = kit.id
    try:
        yield rows
    finally:
        with Session(engine) as session:
            session.execute(delete(Notification).where(Notification.event_id == rows.event_id))
            session.execute(delete(AuditLog).where(AuditLog.entity_id == rows.event_id))
            session.execute(
                delete(EquipmentReservation).where(EquipmentReservation.event_id == rows.event_id)
            )
            session.execute(
                delete(EventEquipmentRequest).where(EventEquipmentRequest.event_id == rows.event_id)
            )
            session.execute(delete(Event).where(Event.id == rows.event_id))
            session.execute(delete(EquipmentType).where(EquipmentType.id == kit_id))
            session.commit()


def _race(engine, attempts: list[Callable[[Session], str]]) -> list[str]:
    """Run each attempt in its own thread and session, released together at a barrier."""
    start = threading.Barrier(len(attempts))

    def run(attempt: Callable[[Session], str]) -> str:
        with Session(engine) as session:
            start.wait()
            return attempt(session)

    with ThreadPoolExecutor(max_workers=len(attempts)) as pool:
        futures = [pool.submit(run, attempt) for attempt in attempts]
        return [future.result(timeout=30) for future in futures]


def _withdrawer(rows: _RaceRows):
    def attempt(session: Session) -> str:
        try:
            service.withdraw_equipment_item(
                session,
                rows.event_id,
                rows.item_id,
                schemas.EquipmentWithdrawalIn(expected_status=PENDING),
                actor=session.get(User, Users.COORDINATOR.id),
            )
        except service.EquipmentConflict as refusal:
            return str(refusal)
        return WITHDRAWN

    return attempt


def _decider(rows: _RaceRows, outcome: str):
    def attempt(session: Session) -> str:
        decision = schemas.EquipmentDecisionIn(
            outcome=outcome, reason="Not needed." if outcome == DECLINED else None
        )
        try:
            service.decide_equipment_request(
                session, rows.item_id, decision, actor=session.get(User, Users.TECH_SUPPORT.id)
            )
        except service.EquipmentConflict as refusal:
            return str(refusal)
        return outcome

    return attempt


def _final_state(engine, rows: _RaceRows) -> tuple[str, list[str], int]:
    """The item's status, its holds' statuses and how many withdrawals were audited."""
    with Session(engine) as session:
        status = session.get(EventEquipmentRequest, rows.item_id).status
        holds = session.scalars(
            select(EquipmentReservation.status).where(
                EquipmentReservation.equipment_request_id == rows.item_id
            )
        ).all()
        audits = session.execute(
            text(
                "SELECT count(*) FROM audit_log"
                " WHERE entity_id = :e AND action = 'EQUIPMENT_WITHDRAWN'"
            ),
            {"e": rows.event_id},
        ).scalar_one()
    return status, sorted(holds), audits


@pytest.mark.story("17.2", ac=11)
@pytest.mark.parametrize("outcome", [ACCEPTED, DECLINED])
def test_a_decision_and_a_withdrawal_at_once_save_only_the_first(engine, outcome):
    with _committed_pending_item(engine) as rows:
        outcomes = _race(engine, [_withdrawer(rows), _decider(rows, outcome)])

        status, holds, audits = _final_state(engine, rows)
        if status == WITHDRAWN:
            assert sorted(outcomes) == sorted([WITHDRAWN, DECISION_ON_WITHDRAWN_MESSAGE])
            assert (holds, audits) == (["RELEASED"], 1)
        else:
            refusal = (
                STATUS_CHANGED_MESSAGE.format(status="accepted")
                if outcome == ACCEPTED
                else NOT_WITHDRAWABLE_MESSAGES[DECLINED]
            )
            assert status == outcome
            assert sorted(outcomes) == sorted([outcome, refusal])
            assert audits == 0


@pytest.mark.story("17.2", ac=11)
def test_a_double_click_on_withdraw_withdraws_once(engine):
    with _committed_pending_item(engine) as rows:
        outcomes = _race(engine, [_withdrawer(rows)] * 2)

        assert sorted(outcomes) == sorted([WITHDRAWN, ALREADY_WITHDRAWN_MESSAGE])
        assert _final_state(engine, rows) == (WITHDRAWN, ["RELEASED"], 1)
