"""Story 15.1 - submit equipment requests for an event (the API cases).

As an Event Coordinator I want to record the equipment an event needs, starting from what the
organiser asked for, and submit it to Technical Support, with each item held for the event's
period until Technical Support decides, so that Technical Support can arrange it and nothing is
double-committed.

AC1  On the event page's Equipment requirements section (there is no separate equipment request
     page), the assigned coordinator sees the equipment the organiser asked for (2.1). The
     coordinator can add more items, each with a type, a quantity and optional technical notes.
     Submitting sends every item not yet sent to Technical Support as a Pending equipment request,
     recording which coordinator submitted it and when.
AC2  Every recorded item holds its quantity for the event's period: the organiser's items from the
     event's submission (2.1 AC11), the coordinator's from when they are saved. Editing an item
     that is not yet sent or Pending adjusts its hold, and removing it releases the hold. If
     Technical Support declines an item (16.1), its hold is released and the coordinator can
     request that type again.
AC3  The form shows, next to each type, how many are available for the event's period, counting
     the item's own hold. The server re-checks availability and creates, adjusts or releases the
     hold in the same step as the save. If the check fails, nothing is saved.
AC4  Quantity must be a whole number from 1 to the quantity available. Exactly the available
     amount is accepted; one more is refused and the available figure is shown. Holds whose
     periods only touch the event's period at a boundary are not counted.
AC5  Technical notes are optional, up to 1,000 characters.
AC6  A type with none available cannot be chosen. Each type can appear only once among the
     event's open items (not yet sent, Pending or Accepted). A declined item stays listed as
     history and does not count.
AC7  An Accepted item is locked: the coordinator can no longer edit or remove it.
AC8  (test_equipment_date_recheck.py) If the event's dates change during review, every item is
     re-checked against the new dates.
AC9  Only the assigned coordinator can record, edit, remove or submit equipment, and only while the
     event is Under Review, Clarification Requested or Planning. Once the event is Confirmed,
     Completed, Cancelled or Rejected, no equipment changes can be made. The API refuses anyone
     else, including direct requests.
AC10 (test_equipment_request_conflicts.py) If two coordinators try to hold the last units at the
     same moment, only the first succeeds. A double-click on Save or Submit acts once.

Item statuses: REQUESTED is recorded but not yet sent, PENDING is sent and awaiting Technical
Support, ACCEPTED and DECLINED are Technical Support's decisions (16.1), UNAVAILABLE is an item
flagged by AC8, and CANCELLED belongs to a cancelled event (6.2). The 16.1 and 6.2 statuses are
made by the factory here, since nothing in this story writes them.

Most cases use a fresh equipment type (``make_equipment_type``), so a test owns its whole stock,
on factory events dated August 2027, clear of every seeded hold.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.audit import AuditLog
from app.equipment import router, service
from app.events.models import (
    EquipmentReservation,
    EquipmentType,
    Event,
    EventEquipmentRequest,
    EventStatus,
)
from tests.support.factories import (
    create_submittable_event_request,
    future_datetime,
    make_equipment_item,
    make_equipment_out_of_service,
    make_equipment_type,
    make_event,
)
from tests.support.seed import Users

SGT = timezone(timedelta(hours=8))
START = datetime(2027, 8, 2, 9, 0, tzinfo=SGT)
END = datetime(2027, 8, 2, 17, 0, tzinfo=SGT)
NOTES_LIMIT = 1000
WRITE_ACTIONS = ("add", "edit", "remove", "submit")
OPEN_STATUSES = (
    EventStatus.UNDER_REVIEW,
    EventStatus.CLARIFICATION_REQUESTED,
    EventStatus.PLANNING,
)
CLOSED_STATUSES = (
    EventStatus.CONFIRMED,
    EventStatus.COMPLETED,
    EventStatus.CANCELLED,
    EventStatus.REJECTED,
)


def _event(
    db: Session,
    *,
    status: str = EventStatus.PLANNING,
    coordinator_id: uuid.UUID = Users.COORDINATOR.id,
    starts_at: datetime = START,
    ends_at: datetime = END,
) -> Event:
    return make_event(
        db,
        status=status,
        assigned_coordinator_id=coordinator_id,
        starts_at=starts_at,
        ends_at=ends_at,
    )


def _add(client, event_id, code: str, quantity, **extra):
    return client.post(
        f"/events/{event_id}/equipment",
        json={"equipment_type_code": code, "quantity": quantity, **extra},
    )


def _edit(client, event_id, item_id, **changes):
    return client.patch(f"/events/{event_id}/equipment/{item_id}", json=changes)


def _remove(client, event_id, item_id):
    return client.delete(f"/events/{event_id}/equipment/{item_id}")


def _submit(client, event_id):
    return client.post(f"/events/{event_id}/equipment-submissions")


def _available(client, event_id) -> dict[str, int]:
    response = client.get(f"/events/{event_id}/equipment-availability")
    assert response.status_code == 200, response.text
    return {row["equipment_type_code"]: row["available"] for row in response.json()}


def _lines(client, event_id) -> list[dict]:
    response = client.get(f"/events/{event_id}")
    assert response.status_code == 200, response.text
    return response.json()["equipment"]


def _active_holds(db: Session, event_id) -> list[EquipmentReservation]:
    db.expire_all()
    return list(
        db.scalars(
            select(EquipmentReservation).where(
                EquipmentReservation.event_id == event_id,
                EquipmentReservation.status == "RESERVED",
            )
        )
    )


def _snapshot(db: Session, event_id) -> tuple[list, list]:
    """Every item and hold on the event, to prove a refused call changed nothing."""
    db.expire_all()
    items = db.scalars(
        select(EventEquipmentRequest).where(EventEquipmentRequest.event_id == event_id)
    )
    holds = db.scalars(
        select(EquipmentReservation).where(EquipmentReservation.event_id == event_id)
    )
    return (
        sorted((str(i.id), i.quantity, i.status, i.technical_notes) for i in items),
        sorted((str(h.id), h.quantity, h.status, h.released_quantity) for h in holds),
    )


def _is_recent(moment: str) -> bool:
    return abs(datetime.fromisoformat(moment) - datetime.now(UTC)) < timedelta(minutes=5)


def _call(client, action: str, event: Event, item: EventEquipmentRequest, spare: EquipmentType):
    """One of the four writes the coordinator makes, aimed at ``event``."""
    if action == "add":
        return _add(client, event.id, spare.code, 1)
    if action == "edit":
        return _edit(client, event.id, item.id, quantity=2)
    if action == "remove":
        return _remove(client, event.id, item.id)
    return _submit(client, event.id)


def _ready(db: Session, **event_overrides) -> tuple[Event, EventEquipmentRequest, EquipmentType]:
    """An event with one item not yet sent, and a second type free to add."""
    event = _event(db, **event_overrides)
    item = make_equipment_item(
        db, event=event, equipment_type=make_equipment_type(db, total_quantity=5), quantity=1
    )
    return event, item, make_equipment_type(db, total_quantity=5)


# --- AC1: record items, see the organiser's, submit them -----------------------------------------
@pytest.mark.story("15.1", ac=1)
def test_coordinator_records_an_item_which_waits_to_be_sent(coordinator_client, db: Session):
    event = _event(db)
    kit = make_equipment_type(db)

    response = _add(coordinator_client, event.id, kit.code, 2, technical_notes="HDMI and USB-C")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body == {
        "id": body["id"],
        "equipment_type_code": kit.code,
        "equipment_type_name": kit.name,
        "quantity": 2,
        "technical_notes": "HDMI and USB-C",
        "status": "REQUESTED",
        "submitted_at": None,
        "submitted_by_name": None,
        "decision_reason": None,
        "decided_at": None,
        "decided_by_name": None,
    }
    assert _lines(coordinator_client, event.id) == [body]


@pytest.mark.story("15.1", ac=1)
def test_several_items_are_listed_in_the_order_they_were_added(coordinator_client, db: Session):
    event = _event(db)
    kits = [make_equipment_type(db) for _ in range(3)]

    for kit in kits:
        assert _add(coordinator_client, event.id, kit.code, 1).status_code == 201

    assert [line["equipment_type_code"] for line in _lines(coordinator_client, event.id)] == [
        kit.code for kit in kits
    ]


@pytest.mark.story("15.1", ac=1)
def test_the_coordinator_sees_and_submits_what_the_organiser_asked_for(login_as, db: Session):
    kit = make_equipment_type(db, total_quantity=10)
    start = future_datetime(days=45)
    organiser = login_as(Users.ORGANISER)
    created = create_submittable_event_request(
        organiser,
        starts_at=start.isoformat(),
        ends_at=(start + timedelta(hours=4)).isoformat(),
        equipment=[{"equipment_type_code": kit.code, "quantity": 3, "technical_notes": "Stage"}],
    )
    submitted = organiser.post(f"/events/{created['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    coordinator_id = uuid.UUID(submitted.json()["assigned_coordinator_id"])
    coordinator = next(u for u in Users.ALL_ACTIVE if u.id == coordinator_id)

    client = login_as(coordinator)
    [line] = _lines(client, created["id"])
    assert (line["equipment_type_code"], line["quantity"], line["status"]) == (
        kit.code,
        3,
        "REQUESTED",
    )
    sent = _submit(client, created["id"])

    assert sent.status_code == 201, sent.text
    assert [(line["id"], line["status"]) for line in sent.json()] == [(line["id"], "PENDING")]
    assert sent.json()[0]["submitted_by_name"] == coordinator.full_name


@pytest.mark.story("15.1", ac=1)
def test_submitting_sends_every_item_not_yet_sent_and_records_who_and_when(
    coordinator_client, db: Session
):
    event = _event(db)
    waiting = [
        make_equipment_item(db, event=event, equipment_type=make_equipment_type(db), quantity=1)
        for _ in range(2)
    ]
    earlier_sent = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
    already_sent = make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db),
        quantity=1,
        status="PENDING",
        submitted_at=earlier_sent,
        submitted_by_id=Users.COORDINATOR_2.id,
    )

    response = _submit(coordinator_client, event.id)

    assert response.status_code == 201, response.text
    sent = response.json()
    assert sorted(line["id"] for line in sent) == sorted(str(item.id) for item in waiting)
    assert {line["status"] for line in sent} == {"PENDING"}
    assert {line["submitted_by_name"] for line in sent} == {Users.COORDINATOR.full_name}
    assert all(_is_recent(line["submitted_at"]) for line in sent)
    unchanged = next(
        line for line in _lines(coordinator_client, event.id) if line["id"] == str(already_sent.id)
    )
    assert datetime.fromisoformat(unchanged["submitted_at"]) == earlier_sent
    assert unchanged["submitted_by_name"] == Users.COORDINATOR_2.full_name


@pytest.mark.story("15.1", ac=1)
def test_submitting_leaves_items_that_are_not_waiting_alone(coordinator_client, db: Session):
    event = _event(db)
    waiting = make_equipment_item(
        db, event=event, equipment_type=make_equipment_type(db), quantity=1
    )
    others = {
        status: make_equipment_item(
            db,
            event=event,
            equipment_type=make_equipment_type(db),
            quantity=1,
            status=status,
            is_held=status == "ACCEPTED",
        )
        for status in ("ACCEPTED", "DECLINED", "UNAVAILABLE", "CANCELLED")
    }

    response = _submit(coordinator_client, event.id)

    assert response.status_code == 201, response.text
    assert [line["id"] for line in response.json()] == [str(waiting.id)]
    statuses = {line["id"]: line["status"] for line in _lines(coordinator_client, event.id)}
    assert {status: statuses[str(item.id)] for status, item in others.items()} == {
        "ACCEPTED": "ACCEPTED",
        "DECLINED": "DECLINED",
        "UNAVAILABLE": "UNAVAILABLE",
        "CANCELLED": "CANCELLED",
    }


@pytest.mark.story("15.1", ac=1)
@pytest.mark.story("15.1", ac=10)
def test_submitting_with_nothing_waiting_is_refused(coordinator_client, db: Session):
    event = _event(db)
    make_equipment_item(
        db, event=event, equipment_type=make_equipment_type(db), quantity=1, status="PENDING"
    )
    before = _snapshot(db, event.id)

    response = _submit(coordinator_client, event.id)

    assert response.status_code == 409
    assert response.json()["detail"] == service.NOTHING_TO_SUBMIT_MESSAGE
    assert _snapshot(db, event.id) == before


@pytest.mark.story("15.1", ac=10)
def test_submitting_twice_sends_once(coordinator_client, db: Session):
    event = _event(db)
    make_equipment_item(db, event=event, equipment_type=make_equipment_type(db), quantity=1)

    first = _submit(coordinator_client, event.id)
    second = _submit(coordinator_client, event.id)

    assert (first.status_code, second.status_code) == (201, 409)
    assert [line["status"] for line in _lines(coordinator_client, event.id)] == ["PENDING"]


@pytest.mark.story("15.1", ac=1)
@pytest.mark.story("15.1", ac=2)
def test_each_change_is_written_to_the_audit_log(coordinator_client, db: Session):
    event = _event(db)
    kit = make_equipment_type(db)
    item_id = _add(coordinator_client, event.id, kit.code, 1).json()["id"]
    _edit(coordinator_client, event.id, item_id, quantity=2)
    _submit(coordinator_client, event.id)
    spare_id = _add(coordinator_client, event.id, make_equipment_type(db).code, 1).json()["id"]
    _remove(coordinator_client, event.id, spare_id)

    # Time stands still inside a test (docs/testing/README.md), so the entries are compared as a
    # set of actions rather than in the order they were written.
    entries = db.scalars(select(AuditLog).where(AuditLog.entity_id == event.id)).all()

    assert sorted(entry.action for entry in entries) == [
        "EQUIPMENT_ITEM_ADDED",
        "EQUIPMENT_ITEM_ADDED",
        "EQUIPMENT_ITEM_REMOVED",
        "EQUIPMENT_ITEM_UPDATED",
        "EQUIPMENT_SUBMITTED",
    ]
    assert {(entry.entity_type, entry.actor_id) for entry in entries} == {
        ("event", Users.COORDINATOR.id)
    }
    added = next(
        entry
        for entry in entries
        if entry.action == "EQUIPMENT_ITEM_ADDED" and entry.details["item_id"] == item_id
    )
    assert added.details == {"item_id": item_id, "equipment_type_code": kit.code, "quantity": 1}


# --- AC2: every recorded item holds its quantity --------------------------------------------------
@pytest.mark.story("15.1", ac=2)
def test_a_recorded_item_holds_its_quantity_for_the_events_period(coordinator_client, db: Session):
    event = _event(db)
    kit = make_equipment_type(db, total_quantity=5)

    item_id = _add(coordinator_client, event.id, kit.code, 2).json()["id"]

    [hold] = _active_holds(db, event.id)
    assert (hold.equipment_type_id, hold.quantity, hold.released_quantity) == (kit.id, 2, 0)
    assert (hold.starts_at, hold.ends_at) == (START, END)
    assert str(hold.equipment_request_id) == item_id
    assert hold.reserved_by_id == Users.COORDINATOR.id


@pytest.mark.story("15.1", ac=2)
def test_the_hold_takes_the_units_away_from_other_events(coordinator_client, db: Session):
    event, other = _event(db), _event(db)
    kit = make_equipment_type(db, total_quantity=5)

    _add(coordinator_client, event.id, kit.code, 2)

    assert _available(coordinator_client, other.id)[kit.code] == 3


@pytest.mark.story("15.1", ac=2)
@pytest.mark.parametrize("status", ["REQUESTED", "PENDING"])
@pytest.mark.parametrize("new_quantity", [1, 4])
def test_editing_the_quantity_adjusts_the_hold(
    coordinator_client, db: Session, status, new_quantity
):
    event, other = _event(db), _event(db)
    kit = make_equipment_type(db, total_quantity=5)
    item = make_equipment_item(db, event=event, equipment_type=kit, quantity=2, status=status)

    response = _edit(coordinator_client, event.id, item.id, quantity=new_quantity)

    assert response.status_code == 200, response.text
    assert (response.json()["quantity"], response.json()["status"]) == (new_quantity, status)
    assert [hold.quantity for hold in _active_holds(db, event.id)] == [new_quantity]
    assert _available(coordinator_client, other.id)[kit.code] == 5 - new_quantity


@pytest.mark.story("15.1", ac=2)
def test_editing_only_the_notes_leaves_the_hold_alone(coordinator_client, db: Session):
    event = _event(db)
    item = make_equipment_item(db, event=event, equipment_type=make_equipment_type(db), quantity=2)
    [hold_before] = _active_holds(db, event.id)
    hold_id = hold_before.id

    response = _edit(coordinator_client, event.id, item.id, technical_notes="Spare batteries")

    assert response.status_code == 200, response.text
    assert (response.json()["quantity"], response.json()["technical_notes"]) == (
        2,
        "Spare batteries",
    )
    assert [(hold.id, hold.quantity) for hold in _active_holds(db, event.id)] == [(hold_id, 2)]


@pytest.mark.story("15.1", ac=2)
@pytest.mark.story("15.1", ac=5)
def test_notes_can_be_cleared_and_an_empty_edit_changes_nothing(coordinator_client, db: Session):
    event = _event(db)
    item = make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db),
        quantity=2,
        technical_notes="Old note",
    )

    unchanged = _edit(coordinator_client, event.id, item.id)
    cleared = _edit(coordinator_client, event.id, item.id, technical_notes=None)

    assert unchanged.status_code == 200, unchanged.text
    assert (unchanged.json()["quantity"], unchanged.json()["technical_notes"]) == (2, "Old note")
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["technical_notes"] is None
    assert [hold.quantity for hold in _active_holds(db, event.id)] == [2]


@pytest.mark.story("15.1", ac=2)
@pytest.mark.parametrize("status", ["REQUESTED", "PENDING"])
def test_removing_an_item_releases_its_hold_at_once(coordinator_client, db: Session, status):
    event, other = _event(db), _event(db)
    kit = make_equipment_type(db, total_quantity=5)
    item = make_equipment_item(db, event=event, equipment_type=kit, quantity=3, status=status)
    [hold] = _active_holds(db, event.id)
    hold_id = hold.id

    response = _remove(coordinator_client, event.id, item.id)

    assert response.status_code == 204, response.text
    assert _lines(coordinator_client, event.id) == []
    assert _active_holds(db, event.id) == []
    released = db.get(EquipmentReservation, hold_id)
    assert (released.status, released.released_quantity) == ("RELEASED", 3)
    assert released.released_at is not None
    assert _available(coordinator_client, other.id)[kit.code] == 5


@pytest.mark.story("15.1", ac=2)
def test_the_type_of_an_item_cannot_be_changed(coordinator_client, db: Session):
    event = _event(db)
    item = make_equipment_item(db, event=event, equipment_type=make_equipment_type(db), quantity=1)
    before = _snapshot(db, event.id)

    response = _edit(
        coordinator_client, event.id, item.id, equipment_type_code=make_equipment_type(db).code
    )

    assert response.status_code == 422
    assert _snapshot(db, event.id) == before


@pytest.mark.story("15.1", ac=2)
@pytest.mark.story("15.1", ac=6)
def test_a_declined_type_can_be_requested_again(coordinator_client, db: Session):
    event = _event(db)
    kit = make_equipment_type(db, total_quantity=5)
    declined = make_equipment_item(
        db,
        event=event,
        equipment_type=kit,
        quantity=2,
        status="DECLINED",
        is_held=False,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    response = _add(coordinator_client, event.id, kit.code, 2)

    assert response.status_code == 201, response.text
    assert [(line["id"], line["status"]) for line in _lines(coordinator_client, event.id)] == [
        (str(declined.id), "DECLINED"),
        (response.json()["id"], "REQUESTED"),
    ]
    assert [hold.quantity for hold in _active_holds(db, event.id)] == [2]


@pytest.mark.story("15.1", ac=2)
def test_an_item_recorded_before_holds_existed_gains_one_when_edited(
    coordinator_client, db: Session
):
    """Rows saved before 2.1's hold (and the seed's older lines) have no hold. Editing one holds
    it, rather than leaving an item that takes nothing out of stock."""
    event = _event(db)
    item = make_equipment_item(
        db, event=event, equipment_type=make_equipment_type(db), quantity=1, is_held=False
    )

    response = _edit(coordinator_client, event.id, item.id, quantity=2)

    assert response.status_code == 200, response.text
    [hold] = _active_holds(db, event.id)
    assert (str(hold.equipment_request_id), hold.quantity) == (str(item.id), 2)


@pytest.mark.story("15.1", ac=2)
@pytest.mark.story("15.1", ac=3)
def test_submitting_holds_an_item_that_has_no_hold_yet(coordinator_client, db: Session):
    event = _event(db)
    item = make_equipment_item(
        db, event=event, equipment_type=make_equipment_type(db), quantity=2, is_held=False
    )

    response = _submit(coordinator_client, event.id)

    assert response.status_code == 201, response.text
    [hold] = _active_holds(db, event.id)
    assert (str(hold.equipment_request_id), hold.quantity) == (str(item.id), 2)


@pytest.mark.story("15.1", ac=3)
def test_submitting_an_unheld_item_that_no_longer_fits_sends_nothing(
    coordinator_client, db: Session
):
    event, other = _event(db), _event(db)
    kit = make_equipment_type(db, total_quantity=3, name="Fog machine")
    make_equipment_item(db, event=other, equipment_type=kit, quantity=2)
    make_equipment_item(db, event=event, equipment_type=make_equipment_type(db), quantity=1)
    make_equipment_item(db, event=event, equipment_type=kit, quantity=2, is_held=False)
    before = _snapshot(db, event.id)

    response = _submit(coordinator_client, event.id)

    assert response.status_code == 409
    assert response.json()["detail"] == service.NOT_ENOUGH_AVAILABLE_MESSAGE.format(
        name="Fog machine"
    )
    assert _snapshot(db, event.id) == before


# --- AC3: the figures the form shows, and the server's own re-check -------------------------------
@pytest.mark.story("15.1", ac=3)
def test_availability_counts_the_events_own_hold(coordinator_client, db: Session):
    event, other = _event(db), _event(db)
    kit = make_equipment_type(db, total_quantity=5)
    make_equipment_item(db, event=event, equipment_type=kit, quantity=2)

    assert _available(coordinator_client, event.id)[kit.code] == 5
    assert _available(coordinator_client, other.id)[kit.code] == 3


@pytest.mark.story("15.1", ac=3)
def test_availability_deducts_other_holds_and_units_out_of_service(coordinator_client, db: Session):
    event, other = _event(db), _event(db)
    kit = make_equipment_type(db, total_quantity=10)
    make_equipment_item(db, event=other, equipment_type=kit, quantity=3)
    make_equipment_out_of_service(db, type_code=kit.code, quantity=2, starts_at=START, ends_at=END)

    assert _available(coordinator_client, event.id)[kit.code] == 5


@pytest.mark.story("15.1", ac=3)
@pytest.mark.story("15.1", ac=6)
def test_availability_names_every_active_type_and_leaves_out_inactive_ones(
    coordinator_client, db: Session
):
    event = _event(db)
    active = make_equipment_type(db, total_quantity=4, name="Smoke machine")
    retired = make_equipment_type(db, total_quantity=4, is_active=False)

    response = coordinator_client.get(f"/events/{event.id}/equipment-availability")

    assert response.status_code == 200, response.text
    rows = {row["equipment_type_code"]: row for row in response.json()}
    assert rows[active.code] == {
        "equipment_type_code": active.code,
        "equipment_type_name": "Smoke machine",
        "available": 4,
    }
    assert retired.code not in rows
    assert {"LAPTOP", "WIRELESS_MIC"} <= rows.keys()


@pytest.mark.story("15.1", ac=3)
def test_a_refused_save_saves_nothing(coordinator_client, db: Session):
    event = _event(db)
    kit = make_equipment_type(db, total_quantity=5)
    item = make_equipment_item(db, event=event, equipment_type=kit, quantity=2)
    before = _snapshot(db, event.id)

    too_many_added = _add(
        coordinator_client, event.id, make_equipment_type(db, total_quantity=1).code, 2
    )
    too_many_edited = _edit(coordinator_client, event.id, item.id, quantity=6, technical_notes="x")

    assert (too_many_added.status_code, too_many_edited.status_code) == (409, 409)
    assert _snapshot(db, event.id) == before


# --- AC4: quantity boundaries -------------------------------------------------------------------
@pytest.mark.story("15.1", ac=4)
def test_exactly_the_available_quantity_is_accepted(coordinator_client, db: Session):
    event, other = _event(db), _event(db)
    kit = make_equipment_type(db, total_quantity=5)
    make_equipment_item(db, event=other, equipment_type=kit, quantity=2)

    response = _add(coordinator_client, event.id, kit.code, 3)

    assert response.status_code == 201, response.text
    assert _available(coordinator_client, other.id)[kit.code] == 2


@pytest.mark.story("15.1", ac=4)
def test_one_more_than_available_is_refused_and_the_figure_is_current(
    coordinator_client, db: Session
):
    event, other = _event(db), _event(db)
    kit = make_equipment_type(db, total_quantity=5, name="Wireless presenter")
    make_equipment_item(db, event=other, equipment_type=kit, quantity=2)

    response = _add(coordinator_client, event.id, kit.code, 4)

    assert response.status_code == 409
    assert response.json()["detail"] == service.NOT_ENOUGH_AVAILABLE_MESSAGE.format(
        name="Wireless presenter"
    )
    assert _available(coordinator_client, event.id)[kit.code] == 3


@pytest.mark.story("15.1", ac=4)
def test_an_edit_may_use_the_free_units_plus_its_own_hold_and_no_more(
    coordinator_client, db: Session
):
    event, other = _event(db), _event(db)
    kit = make_equipment_type(db, total_quantity=7)
    make_equipment_item(db, event=other, equipment_type=kit, quantity=2)
    item = make_equipment_item(db, event=event, equipment_type=kit, quantity=2)

    at_the_limit = _edit(coordinator_client, event.id, item.id, quantity=5)
    one_more = _edit(coordinator_client, event.id, item.id, quantity=6)

    assert at_the_limit.status_code == 200, at_the_limit.text
    assert one_more.status_code == 409
    assert [hold.quantity for hold in _active_holds(db, event.id)] == [5]


@pytest.mark.story("15.1", ac=4)
@pytest.mark.parametrize("quantity", [0, -1, 1.5, "3", None, True, 2_147_483_648])
def test_a_new_items_quantity_must_be_a_positive_whole_number(
    coordinator_client, db: Session, quantity
):
    event = _event(db)

    response = _add(coordinator_client, event.id, make_equipment_type(db).code, quantity)

    assert response.status_code == 422
    assert _lines(coordinator_client, event.id) == []


@pytest.mark.story("15.1", ac=4)
def test_a_new_item_needs_a_quantity(coordinator_client, db: Session):
    event = _event(db)

    response = coordinator_client.post(
        f"/events/{event.id}/equipment",
        json={"equipment_type_code": make_equipment_type(db).code},
    )

    assert response.status_code == 422


@pytest.mark.story("15.1", ac=4)
@pytest.mark.parametrize("quantity", [0, -1, 1.5, "3", None, True])
def test_an_edited_quantity_must_be_a_positive_whole_number(
    coordinator_client, db: Session, quantity
):
    event = _event(db)
    item = make_equipment_item(db, event=event, equipment_type=make_equipment_type(db), quantity=2)
    before = _snapshot(db, event.id)

    response = _edit(coordinator_client, event.id, item.id, quantity=quantity)

    assert response.status_code == 422
    assert _snapshot(db, event.id) == before


@pytest.mark.story("15.1", ac=4)
def test_holds_that_only_touch_the_events_period_are_not_counted(coordinator_client, db: Session):
    event = _event(db)
    kit = make_equipment_type(db, total_quantity=4)
    ends_as_it_starts = _event(db, starts_at=START - timedelta(hours=8), ends_at=START)
    starts_as_it_ends = _event(db, starts_at=END, ends_at=END + timedelta(hours=4))
    overlaps_a_minute = _event(
        db, starts_at=END - timedelta(minutes=1), ends_at=END + timedelta(hours=4)
    )
    make_equipment_item(db, event=ends_as_it_starts, equipment_type=kit, quantity=4)
    make_equipment_item(db, event=starts_as_it_ends, equipment_type=kit, quantity=3)
    make_equipment_item(db, event=overlaps_a_minute, equipment_type=kit, quantity=1)

    assert _available(coordinator_client, event.id)[kit.code] == 3


# --- AC5: technical notes ------------------------------------------------------------------------
@pytest.mark.story("15.1", ac=5)
def test_technical_notes_are_optional(coordinator_client, db: Session):
    event = _event(db)

    response = _add(coordinator_client, event.id, make_equipment_type(db).code, 1)

    assert response.status_code == 201, response.text
    assert response.json()["technical_notes"] is None


@pytest.mark.story("15.1", ac=5)
@pytest.mark.parametrize(
    ("notes", "stored"),
    [("   ", None), ("  Two on stands  ", "Two on stands"), ("n" * NOTES_LIMIT, "n" * NOTES_LIMIT)],
)
def test_notes_are_trimmed_and_up_to_the_limit_is_accepted(
    coordinator_client, db: Session, notes, stored
):
    event = _event(db)
    kit = make_equipment_type(db)

    added = _add(coordinator_client, event.id, kit.code, 1, technical_notes=notes)
    edited = _edit(coordinator_client, event.id, added.json()["id"], technical_notes=notes)

    assert (added.status_code, edited.status_code) == (201, 200)
    assert added.json()["technical_notes"] == stored
    assert edited.json()["technical_notes"] == stored


@pytest.mark.story("15.1", ac=5)
@pytest.mark.parametrize("notes", ["n" * (NOTES_LIMIT + 1), 123])
def test_notes_over_the_limit_or_not_text_are_refused(coordinator_client, db: Session, notes):
    event = _event(db)
    kit = make_equipment_type(db)
    item = make_equipment_item(db, event=event, equipment_type=make_equipment_type(db), quantity=1)
    before = _snapshot(db, event.id)

    added = _add(coordinator_client, event.id, kit.code, 1, technical_notes=notes)
    edited = _edit(coordinator_client, event.id, item.id, technical_notes=notes)

    assert (added.status_code, edited.status_code) == (422, 422)
    assert _snapshot(db, event.id) == before


# --- AC6: which types can be chosen --------------------------------------------------------------
@pytest.mark.story("15.1", ac=6)
def test_a_type_with_none_available_cannot_be_chosen(coordinator_client, db: Session):
    event, other = _event(db), _event(db)
    kit = make_equipment_type(db, total_quantity=2, name="Hazer")
    make_equipment_item(db, event=other, equipment_type=kit, quantity=2)

    response = _add(coordinator_client, event.id, kit.code, 1)

    assert _available(coordinator_client, event.id)[kit.code] == 0
    assert response.status_code == 409
    assert response.json()["detail"] == service.NOT_ENOUGH_AVAILABLE_MESSAGE.format(name="Hazer")


@pytest.mark.story("15.1", ac=6)
@pytest.mark.parametrize("kind", ["inactive", "unknown", "blank"])
def test_an_inactive_or_unknown_type_cannot_be_chosen(coordinator_client, db: Session, kind):
    event = _event(db)
    code = {
        "inactive": make_equipment_type(db, is_active=False).code,
        "unknown": "NO_SUCH_KIT",
        "blank": "",
    }[kind]

    response = _add(coordinator_client, event.id, code, 1)

    assert response.status_code == 422
    if kind != "blank":
        assert response.json()["detail"] == service.UNKNOWN_EQUIPMENT_TYPE_MESSAGE.format(code=code)
    assert _lines(coordinator_client, event.id) == []


@pytest.mark.story("15.1", ac=6)
@pytest.mark.parametrize("status", ["REQUESTED", "PENDING", "ACCEPTED", "UNAVAILABLE"])
def test_a_type_already_open_on_the_event_cannot_be_added_again(
    coordinator_client, db: Session, status
):
    event = _event(db)
    kit = make_equipment_type(db, total_quantity=9, name="Spotlight")
    make_equipment_item(
        db,
        event=event,
        equipment_type=kit,
        quantity=1,
        status=status,
        is_held=status != "UNAVAILABLE",
    )
    before = _snapshot(db, event.id)

    response = _add(coordinator_client, event.id, kit.code, 1)

    assert response.status_code == 409
    assert response.json()["detail"] == service.TYPE_ALREADY_REQUESTED_MESSAGE.format(
        name="Spotlight"
    )
    assert _snapshot(db, event.id) == before


@pytest.mark.story("15.1", ac=6)
@pytest.mark.parametrize("status", ["DECLINED", "CANCELLED"])
def test_a_closed_item_does_not_stop_its_type_being_added(coordinator_client, db: Session, status):
    event = _event(db)
    kit = make_equipment_type(db)
    make_equipment_item(
        db, event=event, equipment_type=kit, quantity=1, status=status, is_held=False
    )

    response = _add(coordinator_client, event.id, kit.code, 1)

    assert response.status_code == 201, response.text


# --- AC7: decided items are locked ---------------------------------------------------------------
@pytest.mark.story("15.1", ac=7)
@pytest.mark.parametrize("status", ["ACCEPTED", "DECLINED", "CANCELLED"])
@pytest.mark.parametrize("action", ["edit", "remove"])
def test_an_accepted_or_declined_item_cannot_be_edited_or_removed(
    coordinator_client, db: Session, status, action
):
    event = _event(db)
    item = make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db),
        quantity=1,
        status=status,
        is_held=status == "ACCEPTED",
    )
    before = _snapshot(db, event.id)

    if action == "edit":
        response = _edit(coordinator_client, event.id, item.id, quantity=2)
    else:
        response = _remove(coordinator_client, event.id, item.id)

    assert response.status_code == 409
    assert response.json()["detail"] == service.ITEM_CLOSED_MESSAGE.format(status=status.lower())
    assert _snapshot(db, event.id) == before


@pytest.mark.story("15.1", ac=7)
@pytest.mark.story("15.1", ac=9)
def test_the_coordinator_cannot_set_an_items_status(coordinator_client, db: Session):
    """The status is Technical Support's (16.1) or the server's to set, never the client's."""
    event = _event(db)
    item = make_equipment_item(db, event=event, equipment_type=make_equipment_type(db), quantity=1)
    before = _snapshot(db, event.id)

    added = _add(coordinator_client, event.id, make_equipment_type(db).code, 1, status="ACCEPTED")
    edited = _edit(coordinator_client, event.id, item.id, status="ACCEPTED")

    assert (added.status_code, edited.status_code) == (422, 422)
    assert _snapshot(db, event.id) == before


# --- AC9: who, and when --------------------------------------------------------------------
@pytest.mark.story("15.1", ac=9)
@pytest.mark.parametrize("action", [*WRITE_ACTIONS, "availability"])
def test_signed_out_callers_are_refused(client, db: Session, action):
    event, item, spare = _ready(db)

    if action == "availability":
        response = client.get(f"/events/{event.id}/equipment-availability")
    else:
        response = _call(client, action, event, item, spare)

    assert response.status_code == 401


@pytest.mark.story("15.1", ac=9)
@pytest.mark.parametrize(
    "user", [Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE]
)
@pytest.mark.parametrize("action", WRITE_ACTIONS)
def test_other_roles_cannot_change_equipment(login_as, db: Session, user, action):
    event, item, spare = _ready(db, status=EventStatus.UNDER_REVIEW)
    before = _snapshot(db, event.id)

    response = _call(login_as(user), action, event, item, spare)

    assert response.status_code == 403
    assert _snapshot(db, event.id) == before


@pytest.mark.story("15.1", ac=9)
@pytest.mark.parametrize(
    ("user", "status_code"),
    [
        (Users.ORGANISER, 403),
        (Users.ATTENDEE, 403),
        (Users.VENUE_STAFF, 200),
        (Users.TECH_SUPPORT, 200),
        (Users.COORDINATOR_2, 200),
    ],
)
def test_only_internal_staff_can_read_the_availability(login_as, db: Session, user, status_code):
    event = _event(db)

    response = login_as(user).get(f"/events/{event.id}/equipment-availability")

    assert response.status_code == status_code


@pytest.mark.story("15.1", ac=9)
@pytest.mark.parametrize("action", WRITE_ACTIONS)
def test_a_coordinator_not_assigned_to_the_event_is_refused(login_as, db: Session, action):
    event, item, spare = _ready(db)
    before = _snapshot(db, event.id)

    response = _call(login_as(Users.COORDINATOR_2), action, event, item, spare)

    assert response.status_code == 403
    assert response.json()["detail"] == service.NOT_ASSIGNED_COORDINATOR_MESSAGE
    assert _snapshot(db, event.id) == before


@pytest.mark.story("15.1", ac=9)
@pytest.mark.parametrize("status", OPEN_STATUSES)
@pytest.mark.parametrize(
    ("action", "expected"), [("add", 201), ("edit", 200), ("remove", 204), ("submit", 201)]
)
def test_equipment_can_change_while_the_event_is_in_review_or_planning(
    coordinator_client, db: Session, status, action, expected
):
    event, item, spare = _ready(db, status=status)

    response = _call(coordinator_client, action, event, item, spare)

    assert response.status_code == expected, response.text


@pytest.mark.story("15.1", ac=9)
@pytest.mark.parametrize("status", CLOSED_STATUSES)
@pytest.mark.parametrize("action", WRITE_ACTIONS)
def test_equipment_cannot_change_once_the_event_is_closed(
    coordinator_client, db: Session, status, action
):
    event, item, spare = _ready(db, status=status)
    before = _snapshot(db, event.id)

    response = _call(coordinator_client, action, event, item, spare)

    assert response.status_code == 409
    assert response.json()["detail"] == service.EQUIPMENT_CLOSED_MESSAGE.format(
        status=status.lower()
    )
    assert _snapshot(db, event.id) == before


@pytest.mark.story("15.1", ac=9)
@pytest.mark.parametrize("action", [*WRITE_ACTIONS, "availability"])
def test_a_draft_is_not_found(coordinator_client, db: Session, action):
    """A draft is private to its organiser (2.1 AC8), so its coordinator-to-be cannot find it."""
    event, item, spare = _ready(db, status=EventStatus.DRAFT)

    if action == "availability":
        response = coordinator_client.get(f"/events/{event.id}/equipment-availability")
    else:
        response = _call(coordinator_client, action, event, item, spare)

    assert response.status_code == 404
    assert response.json()["detail"] == router.EVENT_NOT_FOUND_MESSAGE


@pytest.mark.story("15.1", ac=9)
@pytest.mark.parametrize("action", [*WRITE_ACTIONS, "availability"])
def test_an_unknown_event_is_not_found(coordinator_client, db: Session, action):
    _, item, spare = _ready(db)
    missing = Event(id=uuid.uuid4())

    if action == "availability":
        response = coordinator_client.get(f"/events/{missing.id}/equipment-availability")
    else:
        response = _call(coordinator_client, action, missing, item, spare)

    assert response.status_code == 404
    assert response.json()["detail"] == router.EVENT_NOT_FOUND_MESSAGE


@pytest.mark.story("15.1", ac=9)
@pytest.mark.parametrize("action", ["edit", "remove"])
@pytest.mark.parametrize("whose", ["another event's", "nobody's"])
def test_an_item_not_on_the_event_is_not_found(coordinator_client, db: Session, action, whose):
    event = _event(db)
    _, elsewhere, _ = _ready(db)
    before = _snapshot(db, elsewhere.event_id)
    item_id = elsewhere.id if whose == "another event's" else uuid.uuid4()

    if action == "edit":
        response = _edit(coordinator_client, event.id, item_id, quantity=2)
    else:
        response = _remove(coordinator_client, event.id, item_id)

    assert response.status_code == 404
    assert response.json()["detail"] == router.ITEM_NOT_FOUND_MESSAGE
    assert _snapshot(db, elsewhere.event_id) == before


@pytest.mark.story("15.1", ac=9)
def test_the_organiser_sees_each_items_status_but_cannot_change_it(login_as, db: Session):
    event = _event(db, status=EventStatus.UNDER_REVIEW)
    item = make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db),
        quantity=1,
        status="PENDING",
        submitted_at=datetime(2026, 9, 4, 10, 0, tzinfo=UTC),
        submitted_by_id=Users.COORDINATOR.id,
    )
    organiser = login_as(Users.ORGANISER)

    [line] = _lines(organiser, event.id)

    assert (line["id"], line["status"], line["submitted_by_name"]) == (
        str(item.id),
        "PENDING",
        Users.COORDINATOR.full_name,
    )
    assert _edit(organiser, event.id, item.id, quantity=2).status_code == 403
