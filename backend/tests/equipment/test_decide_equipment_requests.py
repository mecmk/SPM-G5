"""Story 16.1 - accept or decline equipment requests.

As a Technical Support Staff member I want to accept an equipment request, reserving the equipment,
or decline it with a reason, so that the coordinator knows whether the equipment is secured or
another plan is needed.

AC1 Technical Support can accept a pending equipment request from the queue (15.2). Its hold is
    kept as the reservation for the event's period, the request moves to the Accepted tab, and the
    coordinator sees it as Accepted.
AC2 Technical Support can decline a pending request with a reason. The hold is released at once and
    the units are available again for that period. The coordinator sees Declined with the reason and
    can request that type again (15.1).
AC3 Each decision records who made it and when, and is saved on the server together with the
    change to the hold. If either fails, neither is saved.
AC4 A decline reason is required; a blank or spaces-only reason is refused and the request stays
    Pending.
AC5 Accepting succeeds when exactly the requested quantity is still available.
AC6 Accepting is refused when the quantity is no longer available for the period, for example after
    units were marked out of service (16.2), and the refusal shows the shortfall. The request stays
    Pending and can still be declined.
AC7 Only a Pending request can be decided. A request not yet sent, already decided, or on a
    cancelled or rejected event is refused.
AC8 Only Technical Support Staff can accept or decline. Other roles are refused, including through
    the API.
AC9 If two staff decide the same request at the same moment, only the first decision is saved and
    the second sees the current status. A double-click decides once.
AC10 Accepting or declining a request notifies the event's assigned coordinator, naming the
    event, the equipment and the quantity, with the reason for a decline. While that
    coordinator has an unread equipment decision notice for the event, the next decision
    replaces it with one notice listing every decision in it plus the new one, oldest first,
    which comes to the top of their list as unread. Once they have read it, the next decision
    starts a new notice.

A decision is a resource (backend/STYLE.md: a URL names a resource), so it is created with
``POST /equipment-requests/{id}/decision``; a second one on the same request is refused. The
refusal for a shortfall carries the figures as fields beside its sentence, since the sentence
itself never holds a runtime number (backend/STYLE.md).

The coordinator seeing Accepted, or Declined with the reason, on the event page (AC1, AC2), the
Accepted tab (AC1), a blank reason blocked before any request is sent (AC4) and a double-click on
Accept (AC9) and the coordinator finding two decisions in one notice, which opens the event
(AC10), are proven at e2e: tests/e2e/equipment-decisions.spec.ts.

Every case uses a fresh equipment type (``make_equipment_type``), so a test owns its whole stock,
on factory events dated October 2027, clear of every seeded hold.

Excluded, with reason:
* A length limit on the reason - no AC states one (as 13.2.1's reject reason).
* The event becoming Confirmed - old AC6, moved to 21.2, which confirms the event after its safety
  check.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from app.auth.models import User
from app.common.audit import AuditLog
from app.coordination.models import EventCoordinatorAssignment
from app.equipment import schemas, service
from app.events.models import (
    EquipmentReservation,
    EquipmentType,
    Event,
    EventEquipmentRequest,
    EventStatus,
)
from app.notifications.models import Notification
from app.notifications.service import NotificationType, notify
from tests.support.factories import (
    make_equipment_item,
    make_equipment_out_of_service,
    make_equipment_type,
    make_event,
    make_user,
)
from tests.support.seed import Users

TECH_SUPPORT_ROLE = "TECH_SUPPORT_STAFF"
PENDING, ACCEPTED, DECLINED = "PENDING", "ACCEPTED", "DECLINED"
RESERVED, RELEASED = "RESERVED", "RELEASED"
DECIDED = "EQUIPMENT_DECIDED"
REASON = "Every unit is booked for a client roadshow that week."

SGT = timezone(timedelta(hours=8))
START = datetime(2027, 10, 4, 9, 0, tzinfo=SGT)
END = datetime(2027, 10, 4, 17, 0, tzinfo=SGT)

NOT_FOUND_MESSAGE = "Equipment request not found."
NOT_ENOUGH_MESSAGE = "Not enough {name} is available for this event's dates to accept this request."
ALREADY_ACCEPTED_MESSAGE = "This equipment request has already been accepted."
ALREADY_DECLINED_MESSAGE = "This equipment request has already been declined."
NOT_SENT_MESSAGE = "This equipment request has not been sent to Technical Support yet."
UNAVAILABLE_MESSAGE = (
    "This equipment request no longer fits its event's dates and is waiting for the coordinator."
)
CANCELLED_MESSAGE = "This equipment request was cancelled with its event."
EVENT_CLOSED_MESSAGE = "This event is {status}, so its equipment requests can no longer be decided."


def _decision_path(item_id: uuid.UUID) -> str:
    return f"/equipment-requests/{item_id}/decision"


def _event(db: Session, **extra) -> Event:
    return make_event(
        db,
        status=extra.pop("status", EventStatus.PLANNING),
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=extra.pop("starts_at", START),
        ends_at=extra.pop("ends_at", END),
        **extra,
    )


def _pending(
    db: Session,
    *,
    quantity: int = 2,
    event: Event | None = None,
    equipment_type: EquipmentType | None = None,
    **extra,
) -> EventEquipmentRequest:
    """An item the coordinator has sent to Technical Support, holding its units."""
    return make_equipment_item(
        db,
        event=event if event is not None else _event(db),
        equipment_type=(equipment_type if equipment_type is not None else make_equipment_type(db)),
        quantity=quantity,
        status=extra.pop("status", PENDING),
        submitted_by_id=Users.COORDINATOR.id,
        submitted_at=datetime(2026, 10, 1, 9, 0, tzinfo=SGT),
        **extra,
    )


def _accept(client, item_id: uuid.UUID):
    return client.post(_decision_path(item_id), json={"outcome": ACCEPTED})


def _decline(client, item_id: uuid.UUID, reason: str = REASON):
    return client.post(_decision_path(item_id), json={"outcome": DECLINED, "reason": reason})


def _holds(db: Session, item: EventEquipmentRequest) -> list[EquipmentReservation]:
    db.expire_all()
    return list(
        db.scalars(
            select(EquipmentReservation).where(EquipmentReservation.equipment_request_id == item.id)
        ).all()
    )


def _status(db: Session, item: EventEquipmentRequest) -> str:
    db.expire_all()
    return db.get(EventEquipmentRequest, item.id).status


def _audit(db: Session, item: EventEquipmentRequest, action: str) -> list[AuditLog]:
    return [
        row
        for row in db.scalars(
            select(AuditLog).where(AuditLog.entity_id == item.event_id, AuditLog.action == action)
        ).all()
        if row.details.get("item_id") == str(item.id)
    ]


# --- AC1: accept, keeping the hold as the reservation -------------------------------------------
@pytest.mark.story("16.1", ac=1)
def test_technical_support_accepts_a_pending_request(tech_client, db):
    item = _pending(db, quantity=3)

    response = _accept(tech_client, item.id)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == str(item.id)
    assert body["status"] == ACCEPTED
    assert body["decision_reason"] is None
    assert _status(db, item) == ACCEPTED


@pytest.mark.story("16.1", ac=1)
def test_accepting_keeps_the_hold_as_the_reservation_for_the_events_period(tech_client, db):
    item = _pending(db, quantity=3)
    [hold_before] = _holds(db, item)

    assert _accept(tech_client, item.id).status_code == 201

    [hold] = _holds(db, item)
    assert hold.id == hold_before.id
    assert hold.status == RESERVED
    assert hold.quantity == 3
    assert hold.released_quantity == 0
    assert hold.starts_at == START
    assert hold.ends_at == END


@pytest.mark.story("16.1", ac=1)
def test_accepting_a_pending_request_that_holds_nothing_reserves_its_units(tech_client, db):
    """An item sent before holds existed (15.1) has none, so accepting places the reservation."""
    item = _pending(db, quantity=2, is_held=False)

    assert _accept(tech_client, item.id).status_code == 201

    [hold] = _holds(db, item)
    assert hold.status == RESERVED
    assert hold.quantity == 2
    assert (hold.starts_at, hold.ends_at) == (START, END)


# --- AC2: decline with a reason, releasing the hold ---------------------------------------------
@pytest.mark.story("16.1", ac=2)
def test_technical_support_declines_a_pending_request_with_a_reason(tech_client, db):
    item = _pending(db)

    response = _decline(tech_client, item.id)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == DECLINED
    assert body["decision_reason"] == REASON
    db.expire_all()
    row = db.get(EventEquipmentRequest, item.id)
    assert row.status == DECLINED
    assert row.status_notes == REASON


@pytest.mark.story("16.1", ac=2)
def test_declining_releases_the_hold_at_once(tech_client, db):
    item = _pending(db, quantity=3)

    assert _decline(tech_client, item.id).status_code == 201

    [hold] = _holds(db, item)
    assert hold.status == RELEASED
    assert hold.released_quantity == 3
    assert hold.released_at is not None


@pytest.mark.story("16.1", ac=2)
def test_declined_units_are_available_again_for_that_period(login_as, db):
    kit = make_equipment_type(db, total_quantity=3)
    item = _pending(db, quantity=3, equipment_type=kit)
    other_event = _event(db)
    coordinator = login_as(Users.COORDINATOR)

    def available_to_other_event() -> int:
        figures = coordinator.get(f"/events/{other_event.id}/equipment-availability").json()
        return {row["equipment_type_code"]: row["available"] for row in figures}[kit.code]

    assert available_to_other_event() == 0

    assert _decline(login_as(Users.TECH_SUPPORT), item.id).status_code == 201

    assert available_to_other_event() == 3


@pytest.mark.story("16.1", ac=2)
def test_after_a_decline_the_coordinator_can_request_that_type_again(login_as, db):
    kit = make_equipment_type(db, total_quantity=3)
    event = _event(db)
    item = _pending(db, quantity=3, event=event, equipment_type=kit)
    assert _decline(login_as(Users.TECH_SUPPORT), item.id).status_code == 201

    again = login_as(Users.COORDINATOR).post(
        f"/events/{event.id}/equipment", json={"equipment_type_code": kit.code, "quantity": 3}
    )

    assert again.status_code == 201, again.text


# --- AC3: who decided, and when, saved with the hold --------------------------------------------
@pytest.mark.story("16.1", ac=3)
@pytest.mark.parametrize("outcome", [ACCEPTED, DECLINED])
def test_a_decision_records_who_made_it_and_when(tech_client, db, outcome):
    item = _pending(db)
    before = datetime.now(UTC)

    if outcome == ACCEPTED:
        response = _accept(tech_client, item.id)
    else:
        response = _decline(tech_client, item.id)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["decided_by_name"] == Users.TECH_SUPPORT.full_name
    assert before <= datetime.fromisoformat(body["decided_at"]) <= datetime.now(UTC)
    db.expire_all()
    row = db.get(EventEquipmentRequest, item.id)
    assert row.decided_by_id == Users.TECH_SUPPORT.id
    assert row.decided_at is not None


@pytest.mark.story("16.1", ac=3)
@pytest.mark.parametrize(
    ("outcome", "action"),
    [(ACCEPTED, "EQUIPMENT_ACCEPTED"), (DECLINED, "EQUIPMENT_DECLINED")],
)
def test_a_decision_is_audited(tech_client, db, outcome, action):
    item = _pending(db)

    if outcome == ACCEPTED:
        assert _accept(tech_client, item.id).status_code == 201
    else:
        assert _decline(tech_client, item.id).status_code == 201

    [entry] = _audit(db, item, action)
    assert entry.actor_id == Users.TECH_SUPPORT.id


class _AuditFailed(RuntimeError):
    """A failure after the hold has changed and before the decision is saved."""


@pytest.mark.story("16.1", ac=3)
@pytest.mark.parametrize("outcome", [ACCEPTED, DECLINED])
def test_a_decision_that_fails_part_way_saves_neither_it_nor_the_hold(
    tech_client, db, monkeypatch, outcome
):
    """AC3: if either the decision or the change to the hold fails, neither is saved - as 5.2 AC3
    and 8.3 AC8 prove theirs, by making the audit entry, the last step before the commit, raise."""
    # Accepting an item that holds nothing places a hold; declining one releases its hold.
    item = _pending(db, quantity=2, is_held=outcome == DECLINED)
    # Committed, so the item outlives the rollback of the failed request below.
    db.commit()

    def fail_to_record(*_args, **_kwargs):
        raise _AuditFailed

    monkeypatch.setattr(service, "record_audit", fail_to_record)

    with pytest.raises(_AuditFailed):
        _accept(tech_client, item.id) if outcome == ACCEPTED else _decline(tech_client, item.id)
    # The request's session is rolled back when it closes; here the test shares that session.
    db.rollback()

    assert _status(db, item) == PENDING
    holds = _holds(db, item)
    if outcome == ACCEPTED:
        assert holds == []
    else:
        assert [(hold.status, hold.released_quantity) for hold in holds] == [(RESERVED, 0)]


@pytest.mark.story("16.1", ac=3)
@pytest.mark.parametrize("outcome", [ACCEPTED, DECLINED])
def test_the_coordinator_sees_when_and_by_whom_a_request_was_decided(login_as, db, outcome):
    event = _event(db)
    item = _pending(db, event=event)
    tech = login_as(Users.TECH_SUPPORT)
    decided = _accept(tech, item.id) if outcome == ACCEPTED else _decline(tech, item.id)
    assert decided.status_code == 201

    lines = login_as(Users.COORDINATOR).get(f"/events/{event.id}").json()["equipment"]

    [line] = [line for line in lines if line["id"] == str(item.id)]
    assert line["status"] == outcome
    assert line["decided_by_name"] == Users.TECH_SUPPORT.full_name
    assert line["decided_at"] == decided.json()["decided_at"]


@pytest.mark.story("16.1", ac=3)
def test_a_pending_request_on_the_event_page_names_no_decision(coordinator_client, db):
    event = _event(db)
    item = _pending(db, event=event)

    [line] = [
        line
        for line in coordinator_client.get(f"/events/{event.id}").json()["equipment"]
        if line["id"] == str(item.id)
    ]

    assert (line["decided_at"], line["decided_by_name"]) == (None, None)


@pytest.mark.story("16.1", ac=1)
def test_technical_support_sees_when_the_coordinator_sent_a_request(tech_client, db):
    """As Venue Staff see when a booking was requested, each request says when it was sent."""
    item = _pending(db)

    body = tech_client.get(f"/equipment-requests/{item.id}").json()

    assert datetime.fromisoformat(body["submitted_at"]) == datetime(2026, 10, 1, 9, 0, tzinfo=SGT)


@pytest.mark.story("16.1", ac=3)
def test_a_decision_undone_by_new_event_dates_no_longer_names_who_made_it(tech_client, db):
    """15.1 AC8 sends an accepted item back to Technical Support as Pending when its event's dates
    change, so the old decision must not stay recorded against it."""
    event = _event(db)
    item = _pending(db, event=event)
    assert _accept(tech_client, item.id).status_code == 201

    event.starts_at, event.ends_at = START + timedelta(days=7), END + timedelta(days=7)
    db.flush()
    service.recheck_equipment_for_new_dates(db, event, actor=db.get(User, Users.COORDINATOR.id))

    db.flush()
    db.expire_all()
    row = db.get(EventEquipmentRequest, item.id)
    assert row.status == PENDING
    assert row.decided_by_id is None
    assert row.decided_at is None


@pytest.mark.story("16.1", ac=3)
def test_a_decision_undone_by_new_dates_it_no_longer_fits_no_longer_names_who_made_it(
    tech_client, db
):
    """15.1 AC8 flags an accepted item UNAVAILABLE when its event's new dates are short of units;
    the decision for the old dates must not follow it there, or back to Pending once resent."""
    kit = make_equipment_type(db, total_quantity=4)
    event = _event(db)
    item = _pending(db, quantity=4, event=event, equipment_type=kit)
    assert _accept(tech_client, item.id).status_code == 201

    new_start, new_end = START + timedelta(days=7), END + timedelta(days=7)
    make_equipment_out_of_service(
        db, type_code=kit.code, quantity=2, starts_at=new_start, ends_at=new_end
    )
    event.starts_at, event.ends_at = new_start, new_end
    db.flush()
    service.recheck_equipment_for_new_dates(db, event, actor=db.get(User, Users.COORDINATOR.id))

    db.flush()
    db.expire_all()
    row = db.get(EventEquipmentRequest, item.id)
    assert row.status == "UNAVAILABLE"
    assert row.decided_by_id is None
    assert row.decided_at is None


# --- AC4: a decline reason is required ----------------------------------------------------------
@pytest.mark.story("16.1", ac=4)
@pytest.mark.parametrize(
    "body",
    [
        {"outcome": DECLINED},
        {"outcome": DECLINED, "reason": None},
        {"outcome": DECLINED, "reason": ""},
        {"outcome": DECLINED, "reason": "   "},
        {"outcome": DECLINED, "reason": "\t\n"},
    ],
    ids=["missing", "null", "empty", "spaces", "whitespace"],
)
def test_a_decline_without_a_reason_is_refused_and_the_request_stays_pending(tech_client, db, body):
    item = _pending(db, quantity=2)

    response = tech_client.post(_decision_path(item.id), json=body)

    assert response.status_code == 422
    assert _status(db, item) == PENDING
    [hold] = _holds(db, item)
    assert hold.status == RESERVED


@pytest.mark.story("16.1", ac=4)
def test_a_decline_reason_is_stored_trimmed(tech_client, db):
    item = _pending(db)

    response = _decline(tech_client, item.id, reason=f"  {REASON}  ")

    assert response.status_code == 201
    assert response.json()["decision_reason"] == REASON


@pytest.mark.story("16.1", ac=4)
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"outcome": "PENDING"},
        {"outcome": "accepted"},
        {"outcome": ACCEPTED, "reason": REASON},
        {"outcome": ACCEPTED, "note": "extra field"},
    ],
    ids=["no-outcome", "not-a-decision", "lower-case", "accept-with-reason", "unknown-field"],
)
def test_a_malformed_decision_is_refused(tech_client, db, body):
    """Only ACCEPTED or DECLINED is a decision, and only a decline carries a reason."""
    item = _pending(db)

    assert tech_client.post(_decision_path(item.id), json=body).status_code == 422
    assert _status(db, item) == PENDING


# --- AC5: exactly enough is enough --------------------------------------------------------------
@pytest.mark.story("16.1", ac=5)
def test_accepting_succeeds_when_exactly_the_quantity_is_still_available(tech_client, db):
    kit = make_equipment_type(db, total_quantity=5)
    item = _pending(db, quantity=3, equipment_type=kit)
    make_equipment_out_of_service(db, type_code=kit.code, quantity=2, starts_at=START, ends_at=END)

    assert _accept(tech_client, item.id).status_code == 201
    assert _status(db, item) == ACCEPTED


@pytest.mark.story("16.1", ac=5)
def test_out_of_service_units_only_touching_the_event_do_not_block_accepting(tech_client, db):
    kit = make_equipment_type(db, total_quantity=5)
    item = _pending(db, quantity=5, equipment_type=kit)
    make_equipment_out_of_service(
        db, type_code=kit.code, quantity=5, starts_at=END, ends_at=END + timedelta(days=2)
    )

    assert _accept(tech_client, item.id).status_code == 201


# --- AC6: refused when the units are no longer there --------------------------------------------
@pytest.mark.story("16.1", ac=6)
def test_accepting_is_refused_with_the_shortfall_after_units_go_out_of_service(tech_client, db):
    """Five units, four held for this item, then three out of service: two are left for it. Its
    own hold must not be counted as available on top of that."""
    kit = make_equipment_type(db, total_quantity=5, name="Laser projector")
    item = _pending(db, quantity=4, equipment_type=kit)
    make_equipment_out_of_service(db, type_code=kit.code, quantity=3, starts_at=START, ends_at=END)

    response = _accept(tech_client, item.id)

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "message": NOT_ENOUGH_MESSAGE.format(name="Laser projector"),
        "available": 2,
        "shortfall": 2,
    }


@pytest.mark.story("16.1", ac=6)
def test_a_refused_accept_changes_neither_the_request_nor_its_hold(tech_client, db):
    kit = make_equipment_type(db, total_quantity=5)
    item = _pending(db, quantity=4, equipment_type=kit)
    make_equipment_out_of_service(db, type_code=kit.code, quantity=3, starts_at=START, ends_at=END)

    assert _accept(tech_client, item.id).status_code == 409

    db.expire_all()
    row = db.get(EventEquipmentRequest, item.id)
    assert row.status == PENDING
    assert row.decided_by_id is None
    assert row.decided_at is None
    [hold] = _holds(db, item)
    assert (hold.status, hold.quantity, hold.released_quantity) == (RESERVED, 4, 0)
    assert _audit(db, item, "EQUIPMENT_ACCEPTED") == []


@pytest.mark.story("16.1", ac=6)
def test_open_ended_out_of_service_units_block_accepting(tech_client, db):
    kit = make_equipment_type(db, total_quantity=5)
    item = _pending(db, quantity=3, equipment_type=kit)
    make_equipment_out_of_service(
        db, type_code=kit.code, quantity=4, starts_at=START - timedelta(days=30), ends_at=None
    )

    response = _accept(tech_client, item.id)

    assert response.status_code == 409
    assert response.json()["detail"]["shortfall"] == 2


@pytest.mark.story("16.1", ac=6)
def test_a_request_that_cannot_be_accepted_can_still_be_declined(tech_client, db):
    kit = make_equipment_type(db, total_quantity=5)
    item = _pending(db, quantity=4, equipment_type=kit)
    make_equipment_out_of_service(db, type_code=kit.code, quantity=3, starts_at=START, ends_at=END)
    assert _accept(tech_client, item.id).status_code == 409

    assert _decline(tech_client, item.id).status_code == 201
    assert _status(db, item) == DECLINED


# --- AC7: only a Pending request can be decided -------------------------------------------------
@pytest.mark.story("16.1", ac=7)
@pytest.mark.parametrize(
    ("item_status", "is_held", "message"),
    [
        ("REQUESTED", True, NOT_SENT_MESSAGE),
        ("UNAVAILABLE", False, UNAVAILABLE_MESSAGE),
        ("CANCELLED", False, CANCELLED_MESSAGE),
        (ACCEPTED, True, ALREADY_ACCEPTED_MESSAGE),
        (DECLINED, False, ALREADY_DECLINED_MESSAGE),
    ],
)
@pytest.mark.parametrize("outcome", [ACCEPTED, DECLINED])
def test_a_request_that_is_not_pending_is_refused(
    tech_client, db, item_status, is_held, message, outcome
):
    item = _pending(db, status=item_status, is_held=is_held)

    if outcome == ACCEPTED:
        response = _accept(tech_client, item.id)
    else:
        response = _decline(tech_client, item.id)

    assert response.status_code == 409
    assert response.json()["detail"] == message
    assert _status(db, item) == item_status


@pytest.mark.story("16.1", ac=7)
@pytest.mark.parametrize("event_status", [EventStatus.CANCELLED, EventStatus.REJECTED])
@pytest.mark.parametrize("outcome", [ACCEPTED, DECLINED])
def test_a_request_on_a_cancelled_or_rejected_event_is_refused(
    tech_client, db, event_status, outcome
):
    item = _pending(db, event=_event(db, status=event_status))

    if outcome == ACCEPTED:
        response = _accept(tech_client, item.id)
    else:
        response = _decline(tech_client, item.id)

    assert response.status_code == 409
    assert response.json()["detail"] == EVENT_CLOSED_MESSAGE.format(status=event_status.lower())
    assert _status(db, item) == PENDING


@pytest.mark.story("16.1", ac=7)
def test_an_unknown_request_is_not_found(tech_client):
    response = _accept(tech_client, uuid.uuid4())

    assert response.status_code == 404
    assert response.json()["detail"] == NOT_FOUND_MESSAGE


# --- AC8: only Technical Support Staff ----------------------------------------------------------
@pytest.mark.story("16.1", ac=8)
@pytest.mark.parametrize(
    "user", [Users.ORGANISER, Users.COORDINATOR, Users.VENUE_STAFF, Users.ATTENDEE]
)
@pytest.mark.parametrize("outcome", [ACCEPTED, DECLINED])
def test_other_roles_cannot_decide(client, db, user, outcome):
    """Users.COORDINATOR is the event's own assigned coordinator, and is refused too."""
    item = _pending(db)
    client.login(user)

    if outcome == ACCEPTED:
        response = _accept(client, item.id)
    else:
        response = _decline(client, item.id)

    assert response.status_code == 403
    assert _status(db, item) == PENDING


@pytest.mark.story("16.1", ac=8)
def test_a_signed_out_user_cannot_decide(client, db):
    item = _pending(db)

    assert _accept(client, item.id).status_code == 401
    assert _status(db, item) == PENDING


# --- AC9: the first decision wins ---------------------------------------------------------------
@pytest.mark.story("16.1", ac=9)
@pytest.mark.parametrize(
    ("first", "second", "message"),
    [
        (ACCEPTED, ACCEPTED, ALREADY_ACCEPTED_MESSAGE),
        (ACCEPTED, DECLINED, ALREADY_ACCEPTED_MESSAGE),
        (DECLINED, ACCEPTED, ALREADY_DECLINED_MESSAGE),
        (DECLINED, DECLINED, ALREADY_DECLINED_MESSAGE),
    ],
)
def test_a_second_decision_is_refused_with_the_current_status(client, db, first, second, message):
    item = _pending(db)
    other_staff = make_user(db, role=TECH_SUPPORT_ROLE)

    def decide(outcome: str):
        return _accept(client, item.id) if outcome == ACCEPTED else _decline(client, item.id)

    client.login(Users.TECH_SUPPORT)
    assert decide(first).status_code == 201
    client.login(other_staff.email)
    response = decide(second)

    assert response.status_code == 409
    assert response.json()["detail"] == message
    assert _status(db, item) == first


# --- one request's own page, where it can be decided too ----------------------------------------
def _request_path(item_id: uuid.UUID) -> str:
    return f"/equipment-requests/{item_id}"


@pytest.mark.story("16.1", ac=1)
def test_technical_support_opens_a_pending_request_with_its_figures(tech_client, db):
    kit = make_equipment_type(db, total_quantity=5, name="Stage monitor")
    event = _event(db, name="Harbour Gala Dinner")
    item = _pending(db, quantity=4, event=event, equipment_type=kit, technical_notes="Stage left")
    make_equipment_out_of_service(db, type_code=kit.code, quantity=3, starts_at=START, ends_at=END)

    response = tech_client.get(_request_path(item.id))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(item.id)
    assert body["event_id"] == str(event.id)
    assert body["event_name"] == "Harbour Gala Dinner"
    assert body["equipment_type_name"] == "Stage monitor"
    assert body["quantity"] == 4
    assert body["technical_notes"] == "Stage left"
    assert body["requested_by_name"] == Users.COORDINATOR.full_name
    assert body["status"] == PENDING
    assert (body["available"], body["shortfall"]) == (2, 2)
    assert (body["decided_by_name"], body["decided_at"], body["decision_reason"]) == (
        None,
        None,
        None,
    )


@pytest.mark.story("16.1", ac=3)
def test_a_decided_request_shows_who_decided_it_when_and_why(tech_client, db):
    item = _pending(db)
    assert _decline(tech_client, item.id).status_code == 201

    body = tech_client.get(_request_path(item.id)).json()

    assert body["status"] == DECLINED
    assert body["decided_by_name"] == Users.TECH_SUPPORT.full_name
    assert body["decided_at"] is not None
    assert body["decision_reason"] == REASON


@pytest.mark.story("16.1", ac=7)
@pytest.mark.parametrize(
    ("item_status", "event_status"),
    [
        ("REQUESTED", EventStatus.PLANNING),
        ("UNAVAILABLE", EventStatus.PLANNING),
        (PENDING, EventStatus.CANCELLED),
        (PENDING, EventStatus.REJECTED),
    ],
)
def test_a_request_outside_the_queue_is_not_found(tech_client, db, item_status, event_status):
    """Only what the queue lists (15.2 AC3/AC5) has a page of its own. A cancelled item once sent
    is listed, read-only, since story 6.2 AC15, so it is covered there."""
    item = _pending(
        db,
        status=item_status,
        is_held=item_status in ("REQUESTED", PENDING),
        event=_event(db, status=event_status),
    )

    response = tech_client.get(_request_path(item.id))

    assert response.status_code == 404
    assert response.json()["detail"] == NOT_FOUND_MESSAGE


@pytest.mark.story("16.1", ac=7)
def test_an_unknown_request_has_no_page(tech_client):
    assert tech_client.get(_request_path(uuid.uuid4())).status_code == 404


@pytest.mark.story("16.1", ac=8)
@pytest.mark.parametrize(
    "user", [Users.ORGANISER, Users.COORDINATOR, Users.VENUE_STAFF, Users.ATTENDEE]
)
def test_other_roles_cannot_open_a_request(client, db, user):
    item = _pending(db)
    client.login(user)

    assert client.get(_request_path(item.id)).status_code == 403


@pytest.mark.story("16.1", ac=8)
def test_a_signed_out_user_cannot_open_a_request(client, db):
    assert client.get(_request_path(_pending(db).id)).status_code == 401


# --- real races ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class _RaceRows:
    item_id: uuid.UUID
    other_staff_id: uuid.UUID


@contextmanager
def _committed_pending_item(engine) -> Iterator[_RaceRows]:
    """A pending item and a second Technical Support member, committed so other connections see
    them, then removed with everything the race wrote."""
    with Session(engine) as session:
        kit = make_equipment_type(
            session, total_quantity=3, name=f"Race kit {uuid.uuid4().hex[:8]}"
        )
        event = _event(session)
        item = _pending(session, quantity=2, event=event, equipment_type=kit)
        other_staff = make_user(
            session, role=TECH_SUPPORT_ROLE, email=f"race-{uuid.uuid4().hex[:8]}@test.example"
        )
        session.commit()
        event_id, kit_id, item_id = event.id, kit.id, item.id
        other_staff_id = other_staff.id
    try:
        yield _RaceRows(item_id=item_id, other_staff_id=other_staff_id)
    finally:
        with Session(engine) as session:
            session.execute(delete(AuditLog).where(AuditLog.entity_id == event_id))
            session.execute(
                delete(EquipmentReservation).where(EquipmentReservation.event_id == event_id)
            )
            session.execute(
                delete(EventEquipmentRequest).where(EventEquipmentRequest.event_id == event_id)
            )
            session.execute(delete(Event).where(Event.id == event_id))
            session.execute(delete(EquipmentType).where(EquipmentType.id == kit_id))
            session.execute(delete(User).where(User.id == other_staff_id))
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


def _decider(item_id: uuid.UUID, outcome: str, staff: uuid.UUID):
    def attempt(session: Session) -> str:
        decision = schemas.EquipmentDecisionIn(
            outcome=outcome, reason=REASON if outcome == DECLINED else None
        )
        try:
            service.decide_equipment_request(
                session, item_id, decision, actor=session.get(User, staff)
            )
        except service.EquipmentConflict as refusal:
            return str(refusal)
        return outcome

    return attempt


@pytest.mark.story("16.1", ac=9)
def test_a_double_click_on_accept_decides_once(engine):
    with _committed_pending_item(engine) as rows:
        outcomes = _race(engine, [_decider(rows.item_id, ACCEPTED, Users.TECH_SUPPORT.id)] * 2)

        assert sorted(outcomes) == sorted([ACCEPTED, ALREADY_ACCEPTED_MESSAGE])
        with Session(engine) as session:
            item = session.get(EventEquipmentRequest, rows.item_id)
            accepted = session.scalars(
                select(AuditLog).where(
                    AuditLog.entity_id == item.event_id, AuditLog.action == "EQUIPMENT_ACCEPTED"
                )
            ).all()
            assert len(accepted) == 1


@pytest.mark.story("16.1", ac=9)
def test_two_staff_deciding_at_once_save_only_the_first_decision(engine):
    with _committed_pending_item(engine) as rows:
        outcomes = _race(
            engine,
            [
                _decider(rows.item_id, ACCEPTED, Users.TECH_SUPPORT.id),
                _decider(rows.item_id, DECLINED, rows.other_staff_id),
            ],
        )

        with Session(engine) as session:
            item = session.get(EventEquipmentRequest, rows.item_id)
            holds = session.scalars(
                select(EquipmentReservation).where(
                    EquipmentReservation.equipment_request_id == rows.item_id
                )
            ).all()
        refusal = {ACCEPTED: ALREADY_ACCEPTED_MESSAGE, DECLINED: ALREADY_DECLINED_MESSAGE}
        assert sorted(outcomes) == sorted([item.status, refusal[item.status]])
        assert [hold.status for hold in holds] == [
            RESERVED if item.status == ACCEPTED else RELEASED
        ]


# --- AC10: the coordinator is told, in one notice while it is unread ------------------------------
def _notices(db: Session, event_id: uuid.UUID) -> list[Notification]:
    """Every equipment decision notice about the event, oldest first."""
    db.expire_all()
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.event_id == event_id, Notification.notification_type == DECIDED)
            .order_by(Notification.created_at, Notification.id)
        ).all()
    )


def _accepted_line(item: EventEquipmentRequest) -> str:
    return f"Theo Tech accepted {item.quantity} × {item.equipment_type.name}."


def _declined_line(item: EventEquipmentRequest, reason: str = REASON) -> str:
    return f"Theo Tech declined {item.quantity} × {item.equipment_type.name}. Reason: {reason}"


@pytest.mark.story("16.1", ac=10)
@pytest.mark.story("20.1", ac=1)
def test_accepting_tells_the_coordinator_the_event_the_equipment_and_the_quantity(tech_client, db):
    item = _pending(db, quantity=3)
    before = datetime.now(UTC)

    response = _accept(tech_client, item.id)

    assert response.status_code == 201, response.text
    [notice] = _notices(db, item.event_id)
    assert notice.recipient_id == Users.COORDINATOR.id
    assert notice.title == f'Equipment update for "{item.event.name}"'
    assert notice.message == _accepted_line(item)
    assert "3 ×" in notice.message
    assert (notice.related_entity_type, notice.related_entity_id) == ("event", item.event_id)
    assert notice.read_at is None
    assert before <= notice.created_at <= datetime.now(UTC)


@pytest.mark.story("16.1", ac=10)
@pytest.mark.story("20.1", ac=1)
def test_declining_tells_the_coordinator_the_trimmed_reason(tech_client, db):
    item = _pending(db, quantity=2)

    response = _decline(tech_client, item.id, f"   {REASON}   ")

    assert response.status_code == 201, response.text
    [notice] = _notices(db, item.event_id)
    assert notice.recipient_id == Users.COORDINATOR.id
    assert notice.title == f'Equipment update for "{item.event.name}"'
    assert notice.message == _declined_line(item)


@pytest.mark.story("16.1", ac=10)
@pytest.mark.story("20.1", ac=3)
@pytest.mark.story("20.1", ac=5)
@pytest.mark.parametrize("outcome", [ACCEPTED, DECLINED])
def test_only_the_coordinator_is_told_of_a_decision(tech_client, db, outcome):
    """Not the organiser (Q24), another coordinator, or Technical Support, who decided."""
    item = _pending(db)

    _accept(tech_client, item.id) if outcome == ACCEPTED else _decline(tech_client, item.id)

    db.expire_all()
    told = db.scalars(select(Notification).where(Notification.event_id == item.event_id)).all()
    assert [notice.recipient_id for notice in told] == [Users.COORDINATOR.id]


@pytest.mark.story("16.1", ac=10)
def test_each_decision_joins_the_unread_notice_oldest_first(tech_client, db):
    event = _event(db)
    first, second, third = (_pending(db, event=event) for _ in range(3))

    _accept(tech_client, first.id)
    [earlier] = _notices(db, event.id)
    earlier_id, earlier_at = earlier.id, earlier.created_at
    _decline(tech_client, second.id)
    _accept(tech_client, third.id)

    [notice] = _notices(db, event.id)
    assert notice.message == "\n".join(
        [_accepted_line(first), _declined_line(second), _accepted_line(third)]
    )
    assert notice.id != earlier_id
    assert notice.created_at > earlier_at
    assert notice.read_at is None


@pytest.mark.story("16.1", ac=10)
def test_every_unread_notice_is_carried_over_oldest_first(tech_client, db):
    """Decisions take the event's lock, so one notice is all they leave. Should two ever stand, for
    instance written before a change to this rule, neither is lost and their order holds."""
    item = _pending(db)
    for message in ("Oldest.", "Newer."):
        notify(
            db,
            recipient=db.get(User, Users.COORDINATOR.id),
            actor=None,
            notification_type=NotificationType.EQUIPMENT_DECIDED,
            title="Equipment update",
            message=message,
            event_id=item.event_id,
            commit=False,
        )

    _accept(tech_client, item.id)

    [notice] = _notices(db, item.event_id)
    assert notice.message == f"Oldest.\nNewer.\n{_accepted_line(item)}"


@pytest.mark.story("16.1", ac=10)
def test_a_decision_brings_the_unread_notice_to_the_top_without_raising_the_count(login_as, db):
    """A decision on A, then another event's notice above it, then a second decision on A: A's
    notice is the newest again, and there are still two unread, not three."""
    event_a, event_b = _event(db), _event(db)
    first, second = _pending(db, event=event_a), _pending(db, event=event_a)
    other = _pending(db, event=event_b)
    tech = login_as(Users.TECH_SUPPORT)
    _accept(tech, first.id)
    _accept(tech, other.id)
    _accept(tech, second.id)

    coordinator = login_as(Users.COORDINATOR)
    listed = coordinator.get("/notifications").json()
    assert [row["event_id"] for row in listed[:2]] == [str(event_a.id), str(event_b.id)]
    assert listed[0]["message"] == f"{_accepted_line(first)}\n{_accepted_line(second)}"
    unread = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.event_id.in_([event_a.id, event_b.id]), Notification.read_at.is_(None))
    )
    assert unread == 2


@pytest.mark.story("16.1", ac=10)
def test_a_notice_already_read_is_left_and_the_next_decision_starts_a_new_one(login_as, db):
    event = _event(db)
    first, second = _pending(db, event=event), _pending(db, event=event)
    _accept(login_as(Users.TECH_SUPPORT), first.id)
    [read] = _notices(db, event.id)
    read_id = read.id
    marked = login_as(Users.COORDINATOR).patch(f"/notifications/{read_id}", json={"is_read": True})
    assert marked.status_code == 200, marked.text

    _decline(login_as(Users.TECH_SUPPORT), second.id)

    older, newer = _notices(db, event.id)
    assert older.id == read_id
    assert older.read_at is not None
    assert older.message == _accepted_line(first)
    assert newer.read_at is None
    assert newer.message == _declined_line(second)


@pytest.mark.story("16.1", ac=10)
def test_decisions_on_another_event_keep_a_notice_of_their_own(tech_client, db):
    one, other = _pending(db), _pending(db)

    _accept(tech_client, one.id)
    _accept(tech_client, other.id)

    assert [notice.message for notice in _notices(db, one.event_id)] == [_accepted_line(one)]
    assert [notice.message for notice in _notices(db, other.event_id)] == [_accepted_line(other)]


@pytest.mark.story("16.1", ac=10)
def test_a_decision_leaves_another_kind_of_unread_notice_alone(tech_client, db):
    item = _pending(db)
    short = notify(
        db,
        recipient=db.get(User, Users.COORDINATOR.id),
        actor=None,
        notification_type=NotificationType.EQUIPMENT_SHORT,
        title="Equipment short",
        message="Units are short.",
        event_id=item.event_id,
        commit=False,
    )

    _accept(tech_client, item.id)

    db.expire_all()
    assert db.get(Notification, short.id).message == "Units are short."
    assert [notice.message for notice in _notices(db, item.event_id)] == [_accepted_line(item)]


@pytest.mark.story("16.1", ac=10)
def test_an_item_decided_again_is_listed_again_the_latest_last(tech_client, db):
    """New dates send an accepted item back to Pending (15.1 AC8), so it can be decided twice."""
    item = _pending(db)
    _accept(tech_client, item.id)
    db.expire_all()
    db.get(EventEquipmentRequest, item.id).status = PENDING
    db.flush()

    _decline(tech_client, item.id)

    [notice] = _notices(db, item.event_id)
    assert notice.message == f"{_accepted_line(item)}\n{_declined_line(item)}"


@pytest.mark.story("16.1", ac=10)
@pytest.mark.story("20.1", ac=4)
def test_after_a_reassignment_the_new_coordinator_is_told_and_the_old_notice_stays(login_as, db):
    event = _event(db)
    first, second = _pending(db, event=event), _pending(db, event=event)
    db.add(
        EventCoordinatorAssignment(
            event_id=event.id, coordinator_id=Users.COORDINATOR.id, assigned_by_id=Users.LEAD.id
        )
    )
    db.flush()
    _accept(login_as(Users.TECH_SUPPORT), first.id)
    reassigned = login_as(Users.LEAD).put(
        f"/events/{event.id}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )
    assert reassigned.status_code == 200, reassigned.text

    _accept(login_as(Users.TECH_SUPPORT), second.id)

    told = {notice.recipient_id: notice.message for notice in _notices(db, event.id)}
    assert told == {
        Users.COORDINATOR.id: _accepted_line(first),
        Users.COORDINATOR_2.id: _accepted_line(second),
    }


def _refused_as_blank(login_as, db, item):
    return _decline(login_as(Users.TECH_SUPPORT), item.id, "   ")


def _refused_as_short(login_as, db, item):
    make_equipment_out_of_service(
        db, type_code=item.equipment_type.code, quantity=4, starts_at=START, ends_at=END
    )
    return _accept(login_as(Users.TECH_SUPPORT), item.id)


def _refused_as_already_decided(login_as, db, item):
    item.status = DECLINED
    db.flush()
    return _accept(login_as(Users.TECH_SUPPORT), item.id)


def _refused_as_a_closed_event(login_as, db, item):
    item.event.status = EventStatus.CANCELLED
    db.flush()
    return _accept(login_as(Users.TECH_SUPPORT), item.id)


def _refused_to_another_role(login_as, db, item):
    return _accept(login_as(Users.COORDINATOR), item.id)


def _refused_when_signed_out(login_as, db, item):
    client = login_as(Users.TECH_SUPPORT)
    client.logout()
    return _accept(client, item.id)


@pytest.mark.story("16.1", ac=10)
@pytest.mark.story("20.1", ac=4)
@pytest.mark.parametrize(
    ("refuse", "status"),
    [
        (_refused_as_blank, 422),
        (_refused_as_short, 409),
        (_refused_as_already_decided, 409),
        (_refused_as_a_closed_event, 409),
        (_refused_to_another_role, 403),
        (_refused_when_signed_out, 401),
    ],
)
def test_a_refused_decision_leaves_the_unread_notice_as_it_was(login_as, db, refuse, status):
    event = _event(db)
    decided, refused = _pending(db, event=event), _pending(db, event=event)
    _accept(login_as(Users.TECH_SUPPORT), decided.id)
    [notice] = _notices(db, event.id)
    notice_id = notice.id

    response = refuse(login_as, db, refused)

    assert response.status_code == status, response.text
    [after] = _notices(db, event.id)
    assert (after.id, after.message) == (notice_id, _accepted_line(decided))


@pytest.mark.story("16.1", ac=10)
@pytest.mark.story("20.1", ac=4)
@pytest.mark.parametrize("outcome", [ACCEPTED, DECLINED])
def test_a_decision_that_fails_part_way_tells_nobody_and_keeps_the_unread_notice(
    tech_client, db, monkeypatch, outcome
):
    """As AC3's test, by making the audit entry, the last step before the commit, raise."""
    event = _event(db)
    decided, failed = _pending(db, event=event), _pending(db, event=event)
    _accept(tech_client, decided.id)
    [notice] = _notices(db, event.id)
    notice_id = notice.id
    # Committed, so the first decision outlives the rollback of the failed request below.
    db.commit()

    def fail_to_record(*_args, **_kwargs):
        raise _AuditFailed

    monkeypatch.setattr(service, "record_audit", fail_to_record)

    with pytest.raises(_AuditFailed):
        _accept(tech_client, failed.id) if outcome == ACCEPTED else _decline(tech_client, failed.id)
    db.rollback()

    [after] = _notices(db, event.id)
    assert (after.id, after.message) == (notice_id, _accepted_line(decided))


@pytest.mark.story("16.1", ac=10)
def test_marking_a_replaced_notice_read_is_refused_and_leaves_the_new_one_unread(login_as, db):
    """A panel opened before the second decision still names the first notice. Its mark, and a
    "mark all as read" through it, must not reach a decision the coordinator has not seen."""
    event = _event(db)
    first, second = _pending(db, event=event), _pending(db, event=event)
    tech = login_as(Users.TECH_SUPPORT)
    _accept(tech, first.id)
    [replaced] = _notices(db, event.id)
    replaced_id = replaced.id
    _accept(tech, second.id)

    coordinator = login_as(Users.COORDINATOR)
    marked = coordinator.patch(f"/notifications/{replaced_id}", json={"is_read": True})
    marked_all = coordinator.patch(
        "/notifications", json={"is_read": True, "through_id": str(replaced_id)}
    )

    assert (marked.status_code, marked_all.status_code) == (404, 404)
    [notice] = _notices(db, event.id)
    assert notice.read_at is None


def _in_own_session(engine, attempt: Callable[[Session], str], pids: queue.Queue[int]) -> str:
    """``attempt`` in a session of its own, as one request would run it, its database process id
    put in ``pids`` first so a test can watch that session alone."""
    with Session(engine) as session:
        pids.put(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
        return attempt(session)


def _waited_on_a_lock(engine, attempt: Future, pids: queue.Queue[int]) -> bool:
    """Whether ``attempt``'s own session comes to wait on a lock. False if it finishes first, as
    one that took no lock would: nothing holds it up."""
    pid = pids.get(timeout=10)
    deadline = time.monotonic() + 10
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        while time.monotonic() < deadline:
            if attempt.done():
                return False
            waiting = conn.execute(
                text("SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": pid},
            ).scalar()
            if waiting:
                return True
            time.sleep(0.01)
    return False


def _with_a_rival_under_way(engine, rival: Session, attempt: Callable[[Session], str]) -> str:
    """Run ``attempt`` while ``rival`` holds what it needs, and let the rival commit once it is
    waiting. Asserts the wait and returns what ``attempt`` returned."""
    pids: queue.Queue[int] = queue.Queue()
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(_in_own_session, engine, attempt, pids)
        try:
            assert _waited_on_a_lock(engine, waiting, pids)
            rival.commit()
        finally:
            rival.close()  # inside the pool: leaving it waits for whatever this holds up
        return waiting.result(timeout=10)


@pytest.mark.story("16.1", ac=10)
@pytest.mark.story("20.1", ac=4)
def test_a_decision_that_waits_on_a_reassignment_tells_the_new_coordinator(engine):
    """The decision takes the event's row, which the reassignment holds. A read that took the lock
    and joined the coordinator in one statement would come back with the old one."""
    with _committed_pending_item(engine) as rows:
        rival = Session(engine)
        event_id = rival.scalar(
            select(EventEquipmentRequest.event_id).where(EventEquipmentRequest.id == rows.item_id)
        )
        rival.execute(
            update(Event)
            .where(Event.id == event_id)
            .values(assigned_coordinator_id=Users.COORDINATOR_2.id)
        )

        outcome = _with_a_rival_under_way(
            engine, rival, _decider(rows.item_id, ACCEPTED, Users.TECH_SUPPORT.id)
        )

        assert outcome == ACCEPTED
        with Session(engine) as session:
            told = [notice.recipient_id for notice in _notices(session, event_id)]
        assert told == [Users.COORDINATOR_2.id]


@pytest.mark.story("16.1", ac=10)
def test_a_notice_being_marked_read_stays_read_when_a_decision_waits_on_it(engine):
    """The coordinator's mark lands first, so that notice is theirs to keep as read, and the
    decision starts a new one. Without the row lock it would be replaced and show as unread."""
    with _committed_pending_item(engine) as rows:
        with Session(engine) as session:
            first = session.get(EventEquipmentRequest, rows.item_id)
            event_id = first.event_id
            second_id = _pending(
                session,
                quantity=1,
                event=session.get(Event, event_id),
                equipment_type=first.equipment_type,
            ).id
            session.commit()
            first_decision = _decider(rows.item_id, ACCEPTED, Users.TECH_SUPPORT.id)(session)
        assert first_decision == ACCEPTED
        rival = Session(engine)
        rival.execute(
            update(Notification)
            .where(Notification.event_id == event_id)
            .values(read_at=datetime.now(UTC))
        )

        outcome = _with_a_rival_under_way(
            engine, rival, _decider(second_id, DECLINED, Users.TECH_SUPPORT.id)
        )

        assert outcome == DECLINED
        with Session(engine) as session:
            older, newer = _notices(session, event_id)
            assert (older.read_at is None, newer.read_at is None) == (False, True)
            assert "accepted" in older.message
            assert "accepted" not in newer.message


@pytest.mark.story("16.1", ac=10)
@pytest.mark.story("20.1", ac=6)
def test_a_double_click_tells_the_coordinator_once(engine):
    with _committed_pending_item(engine) as rows:
        _race(engine, [_decider(rows.item_id, ACCEPTED, Users.TECH_SUPPORT.id)] * 2)

        with Session(engine) as session:
            item = session.get(EventEquipmentRequest, rows.item_id)
            [notice] = _notices(session, item.event_id)
            assert notice.message == _accepted_line(item)


@pytest.mark.story("16.1", ac=10)
@pytest.mark.story("20.1", ac=6)
def test_two_staff_deciding_at_once_tell_the_coordinator_once(engine):
    with _committed_pending_item(engine) as rows:
        _race(
            engine,
            [
                _decider(rows.item_id, ACCEPTED, Users.TECH_SUPPORT.id),
                _decider(rows.item_id, DECLINED, rows.other_staff_id),
            ],
        )

        with Session(engine) as session:
            item = session.get(EventEquipmentRequest, rows.item_id)
            [notice] = _notices(session, item.event_id)
            assert "\n" not in notice.message
