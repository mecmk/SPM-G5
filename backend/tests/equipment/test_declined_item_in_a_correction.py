"""Story 15.1 - submit equipment requests for an event: fix f15.1.1, a declined item in a story
7.2 correction.

AC2 If Technical Support declines an item (16.1), its hold is released and the coordinator can
    request that type again.
AC6 Each type can appear only once among the event's open items (not yet sent, Pending or
    Accepted). A declined item stays listed as history and does not count.

A correction leaves a declined item alone: it is not counted against the stock when the dates
move, cannot be edited, and is not removed by a list that leaves it out. A form opened before the
item was declined is out of date, so its save is refused with 7.2 AC9's reload message.

The form does not list one, so what it sends is the list these tests send. That the form stops
offering it, and that its own stock and one-line-per-type checks no longer stop a save, happens
before any request fires, so those cases are in tests/e2e/event-correction.spec.ts.

Excluded, with reason:
* Who can correct (permission) - no endpoint or role is new; story 7.2 AC8 covers it.
* A Clarification Requested event - it takes the same path as Under Review, which is the path
  tested here.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.auth.models import User
from app.common.audit import AuditLog
from app.equipment.schemas import EquipmentDecisionIn
from app.equipment.service import decide_equipment_request
from app.events.models import (
    EquipmentReservation,
    EquipmentType,
    Event,
    EventEquipmentRequest,
    EventStatus,
)
from app.events.schemas import EventEquipmentIn, EventReviewCorrection
from app.events.service import StaleEventEdit, correct_event_under_review
from tests.events.test_correct_event_under_review import (
    LAPTOP_STOCK,
    _correct,
    _equipment,
    _held,
    _holds,
    _item_status,
    _moved_to,
    _period,
    _planning_event,
    _read,
    _submitted_with_equipment,
)
from tests.support.factories import (
    make_equipment_hold,
    make_equipment_item,
    make_equipment_type,
)
from tests.support.seed import Users

REQUESTED, PENDING, ACCEPTED, DECLINED = "REQUESTED", "PENDING", "ACCEPTED", "DECLINED"
REASON = "None spare that week."
CORRECTED = "Corrected while Technical Support was deciding."
NOT_ENOUGH_LAPTOPS = "Not enough Presentation laptop available for the proposed dates."
NOT_ON_THE_REQUEST = "An equipment item does not belong to this request."


def _decline(login_as, line: dict) -> None:
    decided = login_as(Users.TECH_SUPPORT).post(
        f"/equipment-requests/{line['id']}/decision",
        json={"outcome": DECLINED, "reason": REASON},
    )
    assert decided.status_code == 201, decided.text


def _sent(login_as, db: Session, period, *, quantity: int = 4) -> dict:
    """A submitted event with one laptop line sent to Technical Support, as the coordinator reads
    it."""
    event = _submitted_with_equipment(login_as, db, period, _equipment("LAPTOP", quantity))
    coordinator = login_as(Users.COORDINATOR)
    submitted = coordinator.post(f"/events/{event['id']}/equipment-submissions")
    assert submitted.status_code == 201, submitted.text
    return _read(coordinator, event["id"])


def _declined(login_as, db: Session, period) -> tuple[dict, dict]:
    """A submitted event whose one laptop line Technical Support declined, as the coordinator
    reads it, and that line."""
    event = _sent(login_as, db, period)
    _decline(login_as, event["equipment"][0])
    event = _read(login_as(Users.COORDINATOR), event["id"])
    return event, event["equipment"][0]


def _requested_again(login_as, db: Session, period, *, quantity: int) -> tuple[dict, dict]:
    """``_declined``'s event with laptops asked for again (AC2), as the coordinator reads it, and
    the new line."""
    event, _ = _declined(login_as, db, period)
    coordinator = login_as(Users.COORDINATOR)
    added = coordinator.post(
        f"/events/{event['id']}/equipment", json=_equipment("LAPTOP", quantity)
    )
    assert added.status_code == 201, added.text
    event = _read(coordinator, event["id"])
    [line] = [line for line in event["equipment"] if line["status"] == REQUESTED]
    return event, line


def _leave_one_laptop_free(db: Session, period) -> None:
    """Another event holds every laptop but one over ``period``."""
    make_equipment_hold(
        db, type_code="LAPTOP", quantity=LAPTOP_STOCK - 1, starts_at=period[0], ends_at=period[1]
    )
    db.commit()


def _resent(line: dict) -> dict:
    """A line as the event returns it, as a correction sends it back."""
    return {
        "id": line["id"],
        "equipment_type_code": line["equipment_type_code"],
        "quantity": line["quantity"],
        "technical_notes": line["technical_notes"],
    }


def _decided(line: dict) -> tuple:
    """What stays on a declined item as its history."""
    return line["id"], line["quantity"], line["status"], line["decision_reason"]


# --- a declined item does not count ----------------------------------------------------------
@pytest.mark.story("15.1", ac=6)
@pytest.mark.parametrize(
    "equipment", [{}, {"equipment": []}], ids=["list left out", "list sent, as the form sends it"]
)
def test_a_declined_items_shortage_does_not_refuse_a_date_move(login_as, db: Session, equipment):
    old, new = _period(200), _period(220)
    event, line = _declined(login_as, db, old)
    _leave_one_laptop_free(db, new)
    coordinator = login_as(Users.COORDINATOR)

    response = _correct(coordinator, event, **_moved_to(event, new), **equipment)

    assert response.status_code == 200, response.text
    after = _read(coordinator, event["id"])
    assert datetime.fromisoformat(after["starts_at"]) == new[0]
    assert [_decided(kept) for kept in after["equipment"]] == [_decided(line)]
    assert _held(db, event["id"]) == set()


@pytest.mark.story("15.1", ac=2)
def test_a_correction_can_request_a_declined_type_again(login_as, db: Session):
    period = _period(200)
    event, line = _declined(login_as, db, period)
    coordinator = login_as(Users.COORDINATOR)

    response = _correct(coordinator, event, equipment=[_equipment("LAPTOP", 1)])

    assert response.status_code == 200, response.text
    after = _read(coordinator, event["id"])["equipment"]
    [new_line] = [kept for kept in after if kept["id"] != line["id"]]
    assert (new_line["status"], new_line["quantity"]) == (REQUESTED, 1)
    assert [_decided(kept) for kept in after if kept["id"] == line["id"]] == [_decided(line)]
    assert _held(db, event["id"]) == {("LAPTOP", 1, period[0], period[1])}


@pytest.mark.story("15.1", ac=6)
@pytest.mark.parametrize(
    "is_list_sent", [False, True], ids=["list left out", "list sent, as the form sends it"]
)
def test_the_line_beside_a_declined_item_can_have_exactly_what_is_free(
    login_as, db: Session, is_list_sent
):
    old, new = _period(200), _period(220)
    event, line = _requested_again(login_as, db, old, quantity=1)
    _leave_one_laptop_free(db, new)
    coordinator = login_as(Users.COORDINATOR)
    equipment = {"equipment": [_resent(line)]} if is_list_sent else {}

    response = _correct(coordinator, event, **_moved_to(event, new), **equipment)

    assert response.status_code == 200, response.text
    assert _held(db, event["id"]) == {("LAPTOP", 1, new[0], new[1])}
    after = _read(coordinator, event["id"])["equipment"]
    assert sorted(kept["status"] for kept in after) == [DECLINED, REQUESTED]


@pytest.mark.story("15.1", ac=6)
def test_one_more_than_is_free_beside_a_declined_item_is_refused_naming_the_type_once(
    login_as, db: Session
):
    old, new = _period(200), _period(220)
    event, _ = _requested_again(login_as, db, old, quantity=2)
    _leave_one_laptop_free(db, new)
    held = _held(db, event["id"])
    coordinator = login_as(Users.COORDINATOR)

    response = _correct(coordinator, event, **_moved_to(event, new))

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == NOT_ENOUGH_LAPTOPS
    assert _read(coordinator, event["id"])["starts_at"] == event["starts_at"]
    assert _held(db, event["id"]) == held


# --- a correction leaves a declined item alone -------------------------------------------------
@pytest.mark.story("15.1", ac=6)
def test_a_correction_that_leaves_a_declined_item_out_keeps_it(login_as, db: Session):
    event, line = _declined(login_as, db, _period(200))
    coordinator = login_as(Users.COORDINATOR)

    response = _correct(coordinator, event, name=f"{event['name']} y", equipment=[])

    assert response.status_code == 200, response.text
    after = _read(coordinator, event["id"])["equipment"]
    assert [_decided(kept) for kept in after] == [_decided(line)]


@pytest.mark.story("15.1", ac=6)
def test_a_correction_cannot_edit_a_declined_item(login_as, db: Session):
    event, line = _declined(login_as, db, _period(200))
    coordinator = login_as(Users.COORDINATOR)

    response = _correct(coordinator, event, equipment=[{**_resent(line), "quantity": 2}])

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == NOT_ON_THE_REQUEST
    after = _read(coordinator, event["id"])["equipment"]
    assert [_decided(kept) for kept in after] == [_decided(line)]


@pytest.mark.story("15.1", ac=6)
def test_a_correction_beside_a_declined_item_leaves_the_other_holds_alone(login_as, db: Session):
    event, line = _requested_again(login_as, db, _period(200), quantity=1)
    before = _holds(db, event["id"])

    response = _correct(
        login_as(Users.COORDINATOR),
        event,
        name=f"{event['name']} y",
        equipment=[_resent(line)],
    )

    assert response.status_code == 200, response.text
    assert _holds(db, event["id"]) == before


@pytest.mark.story("15.1", ac=6)
@pytest.mark.story("7.2", ac=15)
def test_an_approved_events_equipment_resent_without_a_declined_item_is_not_a_change(
    login_as, db: Session
):
    event, _ = _planning_event(db)
    projector = make_equipment_type(db)
    declined = make_equipment_item(
        db, event=event, equipment_type=projector, quantity=1, status=DECLINED, is_held=False
    )
    requested = make_equipment_item(db, event=event, equipment_type=projector, quantity=1)
    db.commit()
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)
    [line] = [line for line in read["equipment"] if line["status"] == REQUESTED]

    response = _correct(
        client, read, name="Renamed beside a declined item", equipment=[_resent(line)]
    )

    assert response.status_code == 200, response.text
    assert (_item_status(db, declined.id), _item_status(db, requested.id)) == (DECLINED, REQUESTED)


@pytest.mark.story("15.1", ac=6)
def test_the_change_history_leaves_out_a_declined_item(login_as, db: Session):
    event, _ = _declined(login_as, db, _period(200))
    coordinator = login_as(Users.COORDINATOR)

    response = _correct(coordinator, event, equipment=[_equipment("WIRELESS_MIC", 1)])

    assert response.status_code == 200, response.text
    changes = coordinator.get(f"/events/{event['id']}/changes").json()
    [change] = [row for row in changes if row["field"] == "equipment"]
    assert change["old_value"] == []
    assert [line["equipment_type_code"] for line in change["new_value"]] == ["WIRELESS_MIC"]


# --- Conflict: decided while the correction is open --------------------------------------------
@dataclass(frozen=True)
class _OpenForm:
    """What a coordinator's open form holds: the version it was read at and its one line."""

    event_id: uuid.UUID
    item_id: uuid.UUID
    expected_updated_at: datetime
    line: EventEquipmentIn


@contextmanager
def _open_form(engine) -> Iterator[_OpenForm]:
    """A form open on an event under review with one Pending item. Committed, as the ``db``
    fixture's one transaction freezes now(), which the trigger stamps ``updated_at`` with; removed
    afterwards with everything the test wrote."""
    with Session(engine) as session:
        kit = make_equipment_type(session, name=f"Open form kit {uuid.uuid4().hex[:8]}")
        event, _ = _planning_event(session, status=EventStatus.UNDER_REVIEW)
        item = make_equipment_item(
            session, event=event, equipment_type=kit, quantity=2, status=PENDING
        )
        session.commit()
        form = _OpenForm(
            event_id=event.id,
            item_id=item.id,
            expected_updated_at=event.updated_at,
            line=EventEquipmentIn(id=item.id, equipment_type_code=kit.code, quantity=2),
        )
        kit_id = kit.id
    try:
        yield form
    finally:
        with Session(engine) as session:
            session.execute(delete(AuditLog).where(AuditLog.entity_id == form.event_id))
            session.execute(
                delete(EquipmentReservation).where(EquipmentReservation.event_id == form.event_id)
            )
            session.execute(
                delete(EventEquipmentRequest).where(EventEquipmentRequest.event_id == form.event_id)
            )
            session.execute(delete(Event).where(Event.id == form.event_id))
            session.execute(delete(EquipmentType).where(EquipmentType.id == kit_id))
            session.commit()


def _decide(engine, form: _OpenForm, outcome: str) -> None:
    decision = EquipmentDecisionIn(outcome=outcome, reason=REASON if outcome == DECLINED else None)
    with Session(engine) as session:
        decide_equipment_request(
            session, form.item_id, decision, actor=session.get(User, Users.TECH_SUPPORT.id)
        )


def _save(engine, form: _OpenForm, *, quantity: int = 2) -> None:
    """The coordinator saves a new description from the form, which sends its line back."""
    correction = EventReviewCorrection(
        expected_updated_at=form.expected_updated_at,
        description=CORRECTED,
        equipment=[form.line.model_copy(update={"quantity": quantity})],
    )
    with Session(engine) as session:
        correct_event_under_review(
            session,
            session.get(Event, form.event_id),
            correction,
            actor=session.get(User, Users.COORDINATOR.id),
        )


@pytest.mark.story("15.1", ac=6)
@pytest.mark.story("7.2", ac=9)
@pytest.mark.parametrize("quantity", [2, 3], ids=["line sent back untouched", "line edited"])
def test_an_item_declined_while_the_form_is_open_is_refused_as_a_stale_copy(engine, quantity):
    with _open_form(engine) as form:
        _decide(engine, form, DECLINED)

        with pytest.raises(StaleEventEdit):
            _save(engine, form, quantity=quantity)

        with Session(engine) as session:
            item = session.get(EventEquipmentRequest, form.item_id)
            assert (item.quantity, item.status) == (2, DECLINED)
            assert session.get(Event, form.event_id).description != CORRECTED


@pytest.mark.story("7.2", ac=9)
def test_an_item_accepted_while_the_form_is_open_does_not_refuse_the_save(engine):
    """An accepted item stays on the form, so the copy the coordinator has is still good."""
    with _open_form(engine) as form:
        _decide(engine, form, ACCEPTED)

        _save(engine, form)

        with Session(engine) as session:
            assert session.get(Event, form.event_id).description == CORRECTED
            assert session.get(EventEquipmentRequest, form.item_id).status == ACCEPTED
