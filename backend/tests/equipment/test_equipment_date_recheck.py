"""Story 15.1 AC8 - re-checking an event's equipment when its dates change during review.

AC8  If the event's dates change during review (7.2, 4.3), every item is re-checked against the
     new dates. An item that still fits has its hold moved to the new dates, and if it was Pending
     or Accepted it goes back to Technical Support as Pending, because the decision was for the
     old dates. An item that no longer fits loses its hold and is flagged Unavailable with the
     available figure, and the coordinator lowers its quantity or removes it, then submits again.
     A shortage of equipment never blocks the date change.

The dates of a submitted event are changed by story 7.2 (the coordinator corrects a request under
review) and story 4.3 (the organiser answers a clarification). Neither is on main yet, so the
re-check is tested here at the service level (unit): ``recheck_equipment_for_new_dates`` is what
those stories call, in the same transaction as the date change, once the new dates are set on the
event. The API cases at the end cover what the coordinator then does with a flagged item.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.common.audit import AuditLog
from app.equipment import service
from app.events.models import EquipmentReservation, Event, EventEquipmentRequest, EventStatus
from tests.support.factories import make_equipment_item, make_equipment_type, make_event
from tests.support.seed import Users

SGT = timezone(timedelta(hours=8))
OLD_START = datetime(2027, 8, 2, 9, 0, tzinfo=SGT)
OLD_END = datetime(2027, 8, 2, 17, 0, tzinfo=SGT)
NEW_START = datetime(2027, 9, 6, 9, 0, tzinfo=SGT)
NEW_END = datetime(2027, 9, 6, 17, 0, tzinfo=SGT)
EARLIER_SENT = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)


def _event(db: Session, *, starts_at: datetime = OLD_START, ends_at: datetime = OLD_END) -> Event:
    return make_event(
        db,
        status=EventStatus.UNDER_REVIEW,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=starts_at,
        ends_at=ends_at,
    )


def _move_and_recheck(
    db: Session, event: Event, *, starts_at: datetime = NEW_START, ends_at: datetime = NEW_END
) -> list[EventEquipmentRequest]:
    """What 7.2 and 4.3 do: set the new dates, then re-check the equipment in the same step."""
    event.starts_at, event.ends_at = starts_at, ends_at
    db.flush()
    actor = db.get(User, Users.COORDINATOR.id)
    return service.recheck_equipment_for_new_dates(db, event, actor=actor)


def _active_holds(db: Session, event: Event) -> list[EquipmentReservation]:
    db.flush()
    db.expire_all()
    return list(
        db.scalars(
            select(EquipmentReservation).where(
                EquipmentReservation.event_id == event.id,
                EquipmentReservation.status == "RESERVED",
            )
        )
    )


def _hold_of(db: Session, item: EventEquipmentRequest) -> EquipmentReservation:
    return db.scalar(
        select(EquipmentReservation).where(EquipmentReservation.equipment_request_id == item.id)
    )


def _flagged_item(db: Session) -> tuple[Event, EventEquipmentRequest]:
    """An item flagged Unavailable: 3 wanted, with 3 of the 4 units held by another event."""
    event = _event(db, starts_at=NEW_START, ends_at=NEW_END)
    kit = make_equipment_type(db, total_quantity=4)
    make_equipment_item(
        db, event=_event(db, starts_at=NEW_START, ends_at=NEW_END), equipment_type=kit, quantity=3
    )
    item = make_equipment_item(
        db, event=event, equipment_type=kit, quantity=3, status="UNAVAILABLE", is_held=False
    )
    return event, item


# --- unit: the re-check itself -------------------------------------------------------------------
@pytest.mark.story("15.1", ac=8)
def test_an_item_that_still_fits_moves_its_hold_to_the_new_dates(db: Session):
    event = _event(db)
    item = make_equipment_item(
        db, event=event, equipment_type=make_equipment_type(db, total_quantity=5), quantity=3
    )
    old_hold_id = _hold_of(db, item).id

    flagged = _move_and_recheck(db, event)

    assert flagged == []
    assert item.status == "REQUESTED"
    old_hold = db.get(EquipmentReservation, old_hold_id)
    assert (old_hold.status, old_hold.released_quantity) == ("RELEASED", 3)
    [new_hold] = _active_holds(db, event)
    assert (new_hold.starts_at, new_hold.ends_at, new_hold.quantity) == (NEW_START, NEW_END, 3)
    assert new_hold.equipment_request_id == item.id


@pytest.mark.story("15.1", ac=8)
@pytest.mark.parametrize("status", ["PENDING", "ACCEPTED"])
def test_a_sent_item_that_fits_goes_back_to_technical_support_as_pending(db: Session, status):
    event = _event(db)
    item = make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db),
        quantity=1,
        status=status,
        submitted_at=EARLIER_SENT,
        submitted_by_id=Users.COORDINATOR_2.id,
    )

    _move_and_recheck(db, event)

    assert item.status == "PENDING"
    assert item.submitted_at > EARLIER_SENT
    assert item.submitted_by_id == Users.COORDINATOR_2.id
    assert [hold.starts_at for hold in _active_holds(db, event)] == [NEW_START]


@pytest.mark.story("15.1", ac=8)
@pytest.mark.parametrize("status", ["REQUESTED", "PENDING", "ACCEPTED"])
def test_an_item_that_no_longer_fits_loses_its_hold_and_is_flagged(db: Session, status):
    event = _event(db)
    kit = make_equipment_type(db, total_quantity=4)
    make_equipment_item(
        db, event=_event(db, starts_at=NEW_START, ends_at=NEW_END), equipment_type=kit, quantity=3
    )
    item = make_equipment_item(db, event=event, equipment_type=kit, quantity=2, status=status)

    flagged = _move_and_recheck(db, event)

    assert flagged == [item]
    assert item.status == "UNAVAILABLE"
    assert _active_holds(db, event) == []
    assert service.available_for_event(db, event)[kit.id] == 1


@pytest.mark.story("15.1", ac=8)
def test_a_shortage_never_blocks_the_date_change(db: Session):
    event = _event(db)
    scarce = make_equipment_type(db, total_quantity=2)
    plentiful = make_equipment_type(db, total_quantity=9)
    make_equipment_item(
        db,
        event=_event(db, starts_at=NEW_START, ends_at=NEW_END),
        equipment_type=scarce,
        quantity=2,
    )
    short = make_equipment_item(db, event=event, equipment_type=scarce, quantity=1)
    fine = make_equipment_item(db, event=event, equipment_type=plentiful, quantity=4)

    flagged = _move_and_recheck(db, event)

    assert flagged == [short]
    assert (event.starts_at, event.ends_at) == (NEW_START, NEW_END)
    assert (short.status, fine.status) == ("UNAVAILABLE", "REQUESTED")
    assert [(hold.equipment_request_id, hold.starts_at) for hold in _active_holds(db, event)] == [
        (fine.id, NEW_START)
    ]


@pytest.mark.story("15.1", ac=8)
def test_a_flagged_item_that_fits_again_is_held_and_waits_to_be_sent(db: Session):
    event = _event(db)
    item = make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db),
        quantity=2,
        status="UNAVAILABLE",
        is_held=False,
    )

    flagged = _move_and_recheck(db, event)

    assert flagged == []
    assert item.status == "REQUESTED"
    assert [(hold.equipment_request_id, hold.quantity) for hold in _active_holds(db, event)] == [
        (item.id, 2)
    ]


@pytest.mark.story("15.1", ac=8)
@pytest.mark.parametrize("status", ["DECLINED", "CANCELLED"])
def test_declined_and_cancelled_items_are_left_alone(db: Session, status):
    event = _event(db)
    item = make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db),
        quantity=1,
        status=status,
        is_held=False,
    )

    flagged = _move_and_recheck(db, event)

    assert flagged == []
    assert item.status == status
    assert _active_holds(db, event) == []


@pytest.mark.story("15.1", ac=8)
def test_the_events_own_old_holds_do_not_count_against_its_new_dates(db: Session):
    """Moving the event four hours later overlaps its old period. Its old hold is released before
    the check, so the whole stock it already had is still its to take."""
    event = _event(db)
    kit = make_equipment_type(db, total_quantity=3)
    item = make_equipment_item(db, event=event, equipment_type=kit, quantity=3)
    later_start, later_end = OLD_START + timedelta(hours=4), OLD_END + timedelta(hours=4)

    flagged = _move_and_recheck(db, event, starts_at=later_start, ends_at=later_end)

    assert flagged == []
    assert item.status == "REQUESTED"
    assert [(hold.starts_at, hold.quantity) for hold in _active_holds(db, event)] == [
        (later_start, 3)
    ]


@pytest.mark.story("15.1", ac=8)
def test_the_recheck_is_written_to_the_audit_log(db: Session):
    event = _event(db)
    kit = make_equipment_type(db, total_quantity=1)
    make_equipment_item(
        db, event=_event(db, starts_at=NEW_START, ends_at=NEW_END), equipment_type=kit, quantity=1
    )
    make_equipment_item(db, event=event, equipment_type=kit, quantity=1)

    _move_and_recheck(db, event)

    [entry] = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == event.id, AuditLog.action == "EQUIPMENT_RECHECKED"
        )
    ).all()
    assert (entry.entity_type, entry.actor_id) == ("event", Users.COORDINATOR.id)
    assert entry.details == {"flagged": [kit.code]}


@pytest.mark.story("15.1", ac=8)
def test_an_event_without_equipment_has_nothing_to_recheck(db: Session):
    event = _event(db)

    flagged = _move_and_recheck(db, event)

    assert flagged == []
    assert db.scalars(select(AuditLog).where(AuditLog.entity_id == event.id)).all() == []


# --- API: what the coordinator does with a flagged item ------------------------------------------
@pytest.mark.story("15.1", ac=8)
def test_the_coordinator_lowers_a_flagged_item_and_submits_it_again(
    coordinator_client, db: Session
):
    event, item = _flagged_item(db)

    lowered = coordinator_client.patch(
        f"/events/{event.id}/equipment/{item.id}", json={"quantity": 1}
    )
    sent = coordinator_client.post(f"/events/{event.id}/equipment-submissions")

    assert lowered.status_code == 200, lowered.text
    assert (lowered.json()["quantity"], lowered.json()["status"]) == (1, "REQUESTED")
    assert sent.status_code == 201, sent.text
    assert [(line["id"], line["status"]) for line in sent.json()] == [(str(item.id), "PENDING")]
    assert [hold.quantity for hold in _active_holds(db, event)] == [1]


@pytest.mark.story("15.1", ac=8)
def test_a_flagged_item_lowered_too_little_stays_flagged(coordinator_client, db: Session):
    event, item = _flagged_item(db)

    response = coordinator_client.patch(
        f"/events/{event.id}/equipment/{item.id}", json={"quantity": 2}
    )

    assert response.status_code == 409
    db.expire_all()
    assert db.get(EventEquipmentRequest, item.id).status == "UNAVAILABLE"
    assert _active_holds(db, event) == []


@pytest.mark.story("15.1", ac=8)
def test_editing_only_the_notes_of_a_flagged_item_keeps_it_flagged(coordinator_client, db: Session):
    event, item = _flagged_item(db)

    response = coordinator_client.patch(
        f"/events/{event.id}/equipment/{item.id}", json={"technical_notes": "Any model will do"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "UNAVAILABLE"
    assert _active_holds(db, event) == []


@pytest.mark.story("15.1", ac=8)
def test_a_flagged_item_can_be_removed(coordinator_client, db: Session):
    event, item = _flagged_item(db)

    response = coordinator_client.delete(f"/events/{event.id}/equipment/{item.id}")

    assert response.status_code == 204, response.text
    assert db.get(EventEquipmentRequest, item.id) is None
