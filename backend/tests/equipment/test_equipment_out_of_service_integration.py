"""Story 16.2 - mark equipment out of service. INTEGRATION tests: the API on PostgreSQL.

Level: integration. Each test calls the ``/equipment-types`` endpoints, or an event's
``/equipment-shortages``, through a signed-in client against the real schema in the rolled-back
test transaction; the races at the end run real concurrent transactions, which commit, so they
clean up after themselves. The counting rules on their own are unit-tested in
``test_equipment_out_of_service_unit.py``; what Technical Support and a coordinator click through
is e2e-tested in ``tests/e2e/equipment-out-of-service.spec.ts``.

Each test makes an equipment type of its own (``make_equipment_type``), so it controls the whole
stock and no seeded hold or record shares it. The API runs on the real clock, so periods are set
relative to now.

AC1 Technical Support records units of an equipment type as out of service: how many, why
    (Damaged, Under maintenance, Lost or Other), an optional note, from when and, optionally,
    until when (left blank, until ended). For that period the units are not available: no hold
    can be placed on them, and Technical Support's queue counts them as gone. Each record, edit
    and end is audited.
AC2 Each equipment type has a page, opened from an Equipment catalogue listing every type with its
    stock and the units out of service now. The page shows the stock, an Out of service form and
    its current records - not yet ended, soonest first - each with Edit and End. Edit changes the
    quantity, reason, note and dates. End ends a record in force now; one not yet started is
    removed, as it never took effect. Ended records leave the list.
AC3 The quantity is a whole number from 1 up to the stock less the units other records already
    have out at any moment of its period. The end must be after the start. The start cannot be in
    the past, a record in force keeps its start, and an ended record cannot be edited.
AC4 When the units left cannot cover the holds on that type over the period, the holds that
    cannot be covered - the most recently placed first - are marked short on their event's
    equipment list, and each event's coordinator is notified with the event, the equipment and
    how many units are short. Only the part still to come counts, and the mark follows the
    records: an edit or End that frees enough units clears it.
AC5 Before saving, the server checks the quantity against the stock and returns the holds the
    record would leave short, so the page can show them and ask to confirm. Saving checks again.
AC6 Only Technical Support Staff can open the catalogue and the type pages, and record, edit or
    end records: others get 403 and signed-out users 401.
AC7 Records that overlap in time add up and never exceed the stock, also when two are saved at
    once, or one is saved as a hold is placed.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.common.audit import AuditLog
from app.equipment import schemas, service
from app.events.models import (
    EquipmentReservation,
    EquipmentType,
    EquipmentUnavailabilityPeriod,
    Event,
    EventEquipmentRequest,
    EventStatus,
)
from app.notifications.models import Notification
from app.notifications.service import NotificationType
from tests.support.factories import (
    make_equipment_item,
    make_equipment_type,
    make_event,
)
from tests.support.seed import Users

TYPES_PATH = "/equipment-types"
RECORD_KEYS = {"id", "quantity", "reason", "notes", "starts_at", "ends_at"}
CATALOGUE_KEYS = {"id", "code", "name", "total_quantity", "out_of_service_now"}
TYPE_PAGE_KEYS = CATALOGUE_KEYS | {"description", "storage_location", "records"}
SHORT_HOLD_KEYS = {
    "event_id",
    "event_name",
    "coordinator_name",
    "units_held",
    "units_short",
    "starts_at",
    "ends_at",
}
NOT_TECH_SUPPORT = [
    pytest.param(user, id=user.role) for user in Users.ONE_PER_ROLE if user != Users.TECH_SUPPORT
]


def _now() -> datetime:
    return datetime.now(UTC)


def _days(days: float) -> datetime:
    """A moment ``days`` from now, to the second, so it survives a round trip through JSON."""
    return (_now() + timedelta(days=days)).replace(microsecond=0)


def _records_path(type_id: uuid.UUID) -> str:
    return f"{TYPES_PATH}/{type_id}/out-of-service"


def _record_path(type_id: uuid.UUID, record_id: uuid.UUID) -> str:
    return f"{_records_path(type_id)}/{record_id}"


def _body(quantity: int = 1, *, start: float = 10, end: float | None = 12, **fields) -> dict:
    """What the form sends: ``quantity`` units, from ``start`` to ``end`` days from now."""
    return {
        "quantity": quantity,
        "reason": "MAINTENANCE",
        "starts_at": _days(start).isoformat(),
        "ends_at": None if end is None else _days(end).isoformat(),
    } | fields


def _check(client, type_id: uuid.UUID, **params):
    """The pre-save check (AC5) for ``params`` - quantity, starts_at, ends_at, record_id. One
    left as None is not sent, as the form sends no end for an open-ended record."""
    query = {
        key: value.isoformat() if isinstance(value, datetime) else str(value)
        for key, value in params.items()
        if value is not None
    }
    return client.get(f"{_records_path(type_id)}/check", params=query)


def _out(
    db: Session,
    equipment_type: EquipmentType,
    quantity: int,
    *,
    start: float,
    end: float | None,
    reason: str = "DAMAGED",
) -> EquipmentUnavailabilityPeriod:
    """A record already on file, from ``start`` to ``end`` days from now (``end`` None: open)."""
    record = EquipmentUnavailabilityPeriod(
        equipment_type_id=equipment_type.id,
        quantity=quantity,
        reason=reason,
        starts_at=_days(start),
        ends_at=None if end is None else _days(end),
        created_by_id=Users.TECH_SUPPORT.id,
    )
    db.add(record)
    db.flush()
    return record


def _event(
    db: Session,
    *,
    start: float = 10.5,
    end: float = 11,
    coordinator: uuid.UUID | None = Users.COORDINATOR.id,
    **overrides,
) -> Event:
    """An event in Planning from ``start`` to ``end`` days from now."""
    return make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=coordinator,
        starts_at=_days(start),
        ends_at=_days(end),
        **overrides,
    )


def _held(
    db: Session,
    event: Event,
    equipment_type: EquipmentType,
    units: int,
    *,
    placed_days_ago: float = 5,
) -> EquipmentReservation:
    """An accepted item of ``units`` on ``event``, held for the event's period, placed
    ``placed_days_ago`` days ago - the order holds are served in (AC4)."""
    item = make_equipment_item(
        db, event=event, equipment_type=equipment_type, quantity=units, status="ACCEPTED"
    )
    hold = db.scalar(
        select(EquipmentReservation).where(EquipmentReservation.equipment_request_id == item.id)
    )
    hold.reserved_at = _now() - timedelta(days=placed_days_ago)
    db.flush()
    return hold


def _audits(db: Session, record_id: uuid.UUID) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.entity_id == record_id)
            .order_by(AuditLog.occurred_at, AuditLog.id)
        )
    )


def _short_notices(db: Session, event: Event) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification).where(
                Notification.event_id == event.id,
                Notification.notification_type == NotificationType.EQUIPMENT_SHORT,
            )
        )
    )


def _shortages(client, event: Event) -> list[dict]:
    return client.get(f"/events/{event.id}/equipment-shortages").json()


def _item_of(db: Session, hold: EquipmentReservation) -> uuid.UUID:
    return hold.equipment_request_id


# =============================================================================================
# AC2 - the catalogue and each type's page
# =============================================================================================
@pytest.mark.story("16.2", ac=2)
def test_the_catalogue_lists_each_type_with_its_stock_and_the_units_out_of_service_now(
    tech_client, db: Session
):
    kit = make_equipment_type(db, total_quantity=7, name="Aaa catalogue kit")
    _out(db, kit, 2, start=-1, end=1)  # in force
    _out(db, kit, 1, start=-3, end=-2)  # ended
    _out(db, kit, 3, start=2, end=3)  # still to come

    bare = make_equipment_type(db, total_quantity=2)

    response = tech_client.get(TYPES_PATH)

    assert response.status_code == 200
    [entry] = [each for each in response.json() if each["id"] == str(kit.id)]
    [none_out] = [each for each in response.json() if each["id"] == str(bare.id)]
    assert none_out["out_of_service_now"] == 0
    assert set(entry) == CATALOGUE_KEYS
    assert (entry["name"], entry["code"]) == ("Aaa catalogue kit", kit.code)
    assert (entry["total_quantity"], entry["out_of_service_now"]) == (7, 2)


@pytest.mark.story("16.2", ac=2)
def test_the_catalogue_lists_active_types_by_name_and_leaves_out_inactive_ones(
    tech_client, db: Session
):
    hidden = make_equipment_type(db, is_active=False)

    names = [each["name"] for each in tech_client.get(TYPES_PATH).json()]

    assert hidden.name not in names
    assert names == sorted(names)
    assert "Wireless microphone" in names


@pytest.mark.story("16.2", ac=2)
def test_a_types_page_shows_its_stock_and_its_current_records_soonest_first(
    tech_client, db: Session
):
    kit = make_equipment_type(
        db, total_quantity=6, description="Pair with stands", storage_location="Level 2"
    )
    later = _out(db, kit, 1, start=5, end=6, reason="LOST")
    in_force = _out(db, kit, 2, start=-1, end=None)
    _out(db, kit, 3, start=-4, end=-1)  # ended: not current

    response = tech_client.get(f"{TYPES_PATH}/{kit.id}")

    assert response.status_code == 200
    page = response.json()
    assert set(page) == TYPE_PAGE_KEYS
    assert (page["description"], page["storage_location"]) == ("Pair with stands", "Level 2")
    assert (page["total_quantity"], page["out_of_service_now"]) == (6, 2)
    assert [record["id"] for record in page["records"]] == [str(in_force.id), str(later.id)]
    first = page["records"][0]
    assert set(first) == RECORD_KEYS
    assert (first["quantity"], first["reason"], first["ends_at"]) == (2, "DAMAGED", None)


@pytest.mark.story("16.2", ac=2)
def test_records_starting_together_are_listed_in_id_order(tech_client, db: Session):
    kit = make_equipment_type(db)
    records = [_out(db, kit, 1, start=2, end=3) for _ in range(3)]
    for record in records[1:]:
        record.starts_at = records[0].starts_at
    db.flush()

    listed = [each["id"] for each in tech_client.get(f"{TYPES_PATH}/{kit.id}").json()["records"]]

    assert listed == sorted(str(record.id) for record in records)


@pytest.mark.story("16.2", ac=2)
def test_an_unknown_or_inactive_type_is_not_found(tech_client, db: Session):
    hidden = make_equipment_type(db, is_active=False)

    for type_id in (uuid.uuid4(), hidden.id):
        response = tech_client.get(f"{TYPES_PATH}/{type_id}")
        assert response.status_code == 404
        assert response.json()["detail"] == service.EQUIPMENT_TYPE_NOT_FOUND_MESSAGE


# =============================================================================================
# AC1 - recording units out of service
# =============================================================================================
@pytest.mark.story("16.2", ac=1)
def test_recording_units_out_of_service_saves_them_and_answers_with_the_record(
    tech_client, db: Session
):
    kit = make_equipment_type(db, total_quantity=5)
    body = _body(2, start=3, end=4, reason="DAMAGED", notes="  Cracked lens  ")

    response = tech_client.post(_records_path(kit.id), json=body)

    assert response.status_code == 201
    answer = response.json()
    assert set(answer) == RECORD_KEYS
    record = db.get(EquipmentUnavailabilityPeriod, uuid.UUID(answer["id"]))
    assert (record.equipment_type_id, record.quantity, record.reason) == (kit.id, 2, "DAMAGED")
    assert record.notes == answer["notes"] == "Cracked lens"
    assert record.starts_at == datetime.fromisoformat(body["starts_at"])
    assert record.ends_at == datetime.fromisoformat(body["ends_at"])
    assert record.created_by_id == Users.TECH_SUPPORT.id


@pytest.mark.story("16.2", ac=1)
def test_a_record_with_no_end_is_out_of_service_until_ended(tech_client, db: Session):
    kit = make_equipment_type(db)

    response = tech_client.post(_records_path(kit.id), json=_body(1, start=1, end=None))

    assert response.status_code == 201
    assert response.json()["ends_at"] is None


@pytest.mark.story("16.2", ac=1)
def test_recording_is_audited_with_what_was_recorded(tech_client, db: Session):
    kit = make_equipment_type(db)

    answer = tech_client.post(_records_path(kit.id), json=_body(2, notes="Fan noise")).json()

    [audit] = _audits(db, uuid.UUID(answer["id"]))
    assert audit.action == service.OUT_OF_SERVICE_CREATED_ACTION
    assert audit.entity_type == service.OUT_OF_SERVICE_ENTITY_TYPE
    assert audit.actor_id == Users.TECH_SUPPORT.id
    details = dict(audit.details)
    starts_at, ends_at = details.pop("starts_at"), details.pop("ends_at")
    assert details == {
        "equipment_type_id": str(kit.id),
        "quantity": 2,
        "reason": "MAINTENANCE",
        "notes": "Fan noise",
    }
    assert datetime.fromisoformat(starts_at) == datetime.fromisoformat(answer["starts_at"])
    assert datetime.fromisoformat(ends_at) == datetime.fromisoformat(answer["ends_at"])


@pytest.mark.story("16.2", ac=1)
def test_units_out_of_service_cannot_be_held_for_an_event_over_the_period(tech_client, db: Session):
    """The coordinator's form (15.1) is offered only what is left, and a hold beyond it is
    refused; Technical Support's queue reads the same figure."""
    kit = make_equipment_type(db, total_quantity=4)
    event = _event(db, start=10.5, end=11)

    assert (
        tech_client.post(_records_path(kit.id), json=_body(3, start=10, end=12)).status_code == 201
    )

    tech_client.login(Users.COORDINATOR)
    figures = tech_client.get(f"/events/{event.id}/equipment-availability").json()
    [figure] = [each for each in figures if each["equipment_type_code"] == kit.code]
    assert figure["available"] == 1
    refused = tech_client.post(
        f"/events/{event.id}/equipment",
        json={"equipment_type_code": kit.code, "quantity": 2},
    )
    assert refused.status_code == 409


@pytest.mark.story("16.2", ac=1)
def test_units_out_of_service_outside_the_events_period_leave_it_whole(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=4)
    event = _event(db, start=10.5, end=11)
    _out(db, kit, 4, start=11, end=12)  # starts as the event ends

    tech_client.login(Users.COORDINATOR)
    figures = tech_client.get(f"/events/{event.id}/equipment-availability").json()

    [figure] = [each for each in figures if each["equipment_type_code"] == kit.code]
    assert figure["available"] == 4


# =============================================================================================
# AC2 - editing, ending and removing a record
# =============================================================================================
@pytest.mark.story("16.2", ac=2)
def test_editing_a_record_changes_only_what_is_sent_and_is_audited(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=5)
    record = _out(db, kit, 1, start=3, end=4, reason="DAMAGED")
    before = (record.starts_at, record.ends_at)

    response = tech_client.patch(
        _record_path(kit.id, record.id), json={"quantity": 3, "notes": "Two more failed"}
    )

    assert response.status_code == 200
    db.refresh(record)
    assert (record.quantity, record.reason, record.notes) == (3, "DAMAGED", "Two more failed")
    assert (record.starts_at, record.ends_at) == before
    [audit] = _audits(db, record.id)
    assert audit.action == service.OUT_OF_SERVICE_UPDATED_ACTION
    assert audit.actor_id == Users.TECH_SUPPORT.id
    assert audit.details["before"]["quantity"] == 1
    assert audit.details["after"]["quantity"] == 3


@pytest.mark.story("16.2", ac=2)
def test_editing_can_move_a_records_dates_change_its_reason_and_leave_it_open_ended(
    tech_client, db: Session
):
    kit = make_equipment_type(db)
    record = _out(db, kit, 1, start=3, end=4)
    moved_to = _days(5)

    response = tech_client.patch(
        _record_path(kit.id, record.id),
        json={"reason": "LOST", "starts_at": moved_to.isoformat(), "ends_at": None},
    )

    assert response.status_code == 200
    db.refresh(record)
    assert (record.reason, record.starts_at, record.ends_at) == ("LOST", moved_to, None)


@pytest.mark.story("16.2", ac=2)
def test_ending_a_record_in_force_ends_it_now_and_it_leaves_the_list(tech_client, db: Session):
    kit = make_equipment_type(db)
    record = _out(db, kit, 2, start=-1, end=None)
    before = _now()

    response = tech_client.patch(_record_path(kit.id, record.id), json={"end_now": True})

    assert response.status_code == 200
    db.refresh(record)
    assert before <= record.ends_at <= _now()
    assert tech_client.get(f"{TYPES_PATH}/{kit.id}").json()["records"] == []
    [audit] = _audits(db, record.id)
    assert audit.action == service.OUT_OF_SERVICE_ENDED_ACTION
    assert audit.actor_id == Users.TECH_SUPPORT.id
    assert audit.details["before"]["ends_at"] is None
    assert datetime.fromisoformat(audit.details["after"]["ends_at"]) == record.ends_at


@pytest.mark.story("16.2", ac=2)
def test_ending_a_record_not_yet_started_is_refused_as_it_is_removed_instead(
    tech_client, db: Session
):
    kit = make_equipment_type(db)
    record = _out(db, kit, 2, start=1, end=2)
    planned_end = record.ends_at

    response = tech_client.patch(_record_path(kit.id, record.id), json={"end_now": True})

    assert response.status_code == 409
    assert response.json()["detail"] == service.RECORD_NOT_STARTED_MESSAGE
    db.refresh(record)
    assert record.ends_at == planned_end


@pytest.mark.story("16.2", ac=2)
def test_removing_a_record_not_yet_started_deletes_it_and_is_audited(tech_client, db: Session):
    kit = make_equipment_type(db)
    record = _out(db, kit, 2, start=1, end=2, reason="LOST")
    record_id = record.id

    response = tech_client.delete(_record_path(kit.id, record_id))

    assert response.status_code == 204
    assert db.get(EquipmentUnavailabilityPeriod, record_id) is None
    [audit] = _audits(db, record_id)
    assert audit.action == service.OUT_OF_SERVICE_REMOVED_ACTION
    assert audit.actor_id == Users.TECH_SUPPORT.id
    assert audit.details["reason"] == "LOST"


@pytest.mark.story("16.2", ac=2)
def test_removing_a_record_in_force_is_refused_as_it_is_ended_instead(tech_client, db: Session):
    kit = make_equipment_type(db)
    record = _out(db, kit, 2, start=-1, end=2)

    response = tech_client.delete(_record_path(kit.id, record.id))

    assert response.status_code == 409
    assert response.json()["detail"] == service.RECORD_STARTED_MESSAGE
    assert db.get(EquipmentUnavailabilityPeriod, record.id) is not None


@pytest.mark.story("16.2", ac=2)
@pytest.mark.parametrize("method", ["patch", "delete"])
def test_a_record_of_another_type_or_none_at_all_is_not_found(
    tech_client, db: Session, method: str
):
    kit, other = make_equipment_type(db), make_equipment_type(db)
    record = _out(db, other, 1, start=1, end=2)

    for path in (_record_path(kit.id, record.id), _record_path(kit.id, uuid.uuid4())):
        response = getattr(tech_client, method)(
            path, **({"json": {"quantity": 1}} if method == "patch" else {})
        )
        assert response.status_code == 404
        assert response.json()["detail"] == service.OUT_OF_SERVICE_NOT_FOUND_MESSAGE


@pytest.mark.story("16.2", ac=1)
def test_recording_against_an_unknown_type_is_not_found(tech_client):
    response = tech_client.post(_records_path(uuid.uuid4()), json=_body())

    assert response.status_code == 404
    assert response.json()["detail"] == service.EQUIPMENT_TYPE_NOT_FOUND_MESSAGE


# =============================================================================================
# AC3 - the boundaries
# =============================================================================================
@pytest.mark.story("16.2", ac=3)
def test_the_whole_stock_can_be_taken_out_but_not_a_unit_more(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=4)

    refused = tech_client.post(_records_path(kit.id), json=_body(5))
    taken = tech_client.post(_records_path(kit.id), json=_body(4))

    assert refused.status_code == 409
    assert refused.json()["detail"] == service.too_many_out_message(most=4)
    assert taken.status_code == 201


@pytest.mark.story("16.2", ac=3)
@pytest.mark.story("16.2", ac=7)
def test_units_other_records_have_out_over_the_period_are_not_offered_again(
    tech_client, db: Session
):
    kit = make_equipment_type(db, total_quantity=5)
    _out(db, kit, 2, start=9, end=11)
    _out(db, kit, 1, start=11.5, end=13)  # out at the same time as the record below, not the first

    refused = tech_client.post(_records_path(kit.id), json=_body(4, start=10, end=12))
    taken = tech_client.post(_records_path(kit.id), json=_body(3, start=10, end=12))

    assert refused.status_code == 409
    assert refused.json()["detail"] == service.too_many_out_message(most=3)
    assert taken.status_code == 201
    assert (
        db.scalar(
            select(func.count()).where(EquipmentUnavailabilityPeriod.equipment_type_id == kit.id)
        )
        == 3
    )


@pytest.mark.story("16.2", ac=3)
def test_a_record_after_the_others_can_take_the_whole_stock(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=5)
    _out(db, kit, 5, start=1, end=10)

    response = tech_client.post(_records_path(kit.id), json=_body(5, start=10, end=12))

    assert response.status_code == 201


@pytest.mark.story("16.2", ac=3)
def test_an_edited_record_is_not_counted_against_itself(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=4)
    record = _out(db, kit, 3, start=1, end=2)

    raised = tech_client.patch(_record_path(kit.id, record.id), json={"quantity": 4})
    too_many = tech_client.patch(_record_path(kit.id, record.id), json={"quantity": 5})

    assert raised.status_code == 200
    assert too_many.status_code == 409
    assert too_many.json()["detail"] == service.too_many_out_message(most=4)


@pytest.mark.story("16.2", ac=3)
def test_widening_a_record_onto_another_counts_the_other(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=4)
    _out(db, kit, 3, start=5, end=6)
    record = _out(db, kit, 2, start=1, end=2)

    response = tech_client.patch(
        _record_path(kit.id, record.id), json={"ends_at": _days(5.5).isoformat()}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == service.too_many_out_message(most=1)


@pytest.mark.story("16.2", ac=3)
@pytest.mark.parametrize(
    "fields",
    [{"quantity": 0}, {"quantity": "two"}, {"reason": "STOLEN"}, {"notes": "n" * 1001}],
    ids=["quantity-0", "not-a-number", "unknown-reason", "note-over-1000"],
)
def test_a_record_outside_the_rules_is_refused_and_nothing_is_saved(
    tech_client, db: Session, fields: dict
):
    kit = make_equipment_type(db)

    response = tech_client.post(_records_path(kit.id), json=_body(**fields))

    assert response.status_code == 422
    assert (
        db.scalar(
            select(func.count()).where(EquipmentUnavailabilityPeriod.equipment_type_id == kit.id)
        )
        == 0
    )


@pytest.mark.story("16.2", ac=3)
def test_an_end_at_or_before_the_start_is_refused(tech_client, db: Session):
    kit = make_equipment_type(db)

    for end in (10, 9):
        response = tech_client.post(_records_path(kit.id), json=_body(start=10, end=end))
        assert response.status_code == 422
        assert schemas.OUT_OF_SERVICE_END_NOT_AFTER_START_MESSAGE in response.text


@pytest.mark.story("16.2", ac=3)
def test_a_start_in_the_past_is_refused_and_one_this_minute_is_taken(tech_client, db: Session):
    kit = make_equipment_type(db)
    this_minute = _now().replace(second=0, microsecond=0)
    body = _body(start=1)

    past = tech_client.post(
        _records_path(kit.id),
        json=body | {"starts_at": (this_minute - timedelta(minutes=1)).isoformat()},
    )
    taken = tech_client.post(
        _records_path(kit.id), json=body | {"starts_at": this_minute.isoformat()}
    )

    assert past.status_code == 422
    assert past.json()["detail"] == service.START_IN_THE_PAST_MESSAGE
    assert taken.status_code == 201


@pytest.mark.story("16.2", ac=3)
def test_an_edit_leaving_the_end_at_or_before_the_start_is_refused(tech_client, db: Session):
    kit = make_equipment_type(db)
    record = _out(db, kit, 1, start=3, end=4)

    response = tech_client.patch(
        _record_path(kit.id, record.id), json={"starts_at": _days(4).isoformat()}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == schemas.OUT_OF_SERVICE_END_NOT_AFTER_START_MESSAGE


@pytest.mark.story("16.2", ac=3)
def test_an_edit_moving_a_start_into_the_past_is_refused(tech_client, db: Session):
    kit = make_equipment_type(db)
    record = _out(db, kit, 1, start=3, end=4)

    response = tech_client.patch(
        _record_path(kit.id, record.id), json={"starts_at": _days(-1).isoformat()}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == service.START_IN_THE_PAST_MESSAGE


@pytest.mark.story("16.2", ac=3)
def test_a_record_in_force_keeps_its_start_but_its_end_and_quantity_can_change(
    tech_client, db: Session
):
    kit = make_equipment_type(db, total_quantity=5)
    record = _out(db, kit, 1, start=-1, end=2)
    started, new_end = record.starts_at, _days(3)

    moved = tech_client.patch(
        _record_path(kit.id, record.id), json={"starts_at": _days(1).isoformat()}
    )
    changed = tech_client.patch(
        _record_path(kit.id, record.id),
        json={"starts_at": started.isoformat(), "ends_at": new_end.isoformat(), "quantity": 2},
    )

    assert moved.status_code == 409
    assert moved.json()["detail"] == service.RECORD_START_LOCKED_MESSAGE
    assert changed.status_code == 200
    db.refresh(record)
    assert (record.starts_at, record.ends_at, record.quantity) == (started, new_end, 2)


@pytest.mark.story("16.2", ac=3)
@pytest.mark.parametrize("change", [{"quantity": 2}, {"end_now": True}])
def test_an_ended_record_cannot_be_edited_or_ended_again(tech_client, db: Session, change: dict):
    kit = make_equipment_type(db)
    record = _out(db, kit, 1, start=-3, end=-1)

    response = tech_client.patch(_record_path(kit.id, record.id), json=change)

    assert response.status_code == 409
    assert response.json()["detail"] == service.RECORD_ENDED_MESSAGE


@pytest.mark.story("16.2", ac=3)
def test_an_ended_record_cannot_be_removed(tech_client, db: Session):
    kit = make_equipment_type(db)
    record = _out(db, kit, 1, start=-3, end=-1)

    response = tech_client.delete(_record_path(kit.id, record.id))

    assert response.status_code == 409
    assert response.json()["detail"] == service.RECORD_ENDED_MESSAGE


# =============================================================================================
# AC4 / AC5 - the holds a record leaves short: checked first, then marked and told
# =============================================================================================
@pytest.mark.story("16.2", ac=5)
def test_the_check_lists_the_holds_a_record_would_leave_short_and_writes_nothing(
    tech_client, db: Session
):
    kit = make_equipment_type(db, total_quantity=3, name="Check kit")
    event = _event(db, name="Riverbank Fair")
    _held(db, event, kit, 3)

    response = _check(tech_client, kit.id, quantity=1, starts_at=_days(10), ends_at=_days(12))

    assert response.status_code == 200
    [short] = response.json()["short_holds"]
    assert set(short) == SHORT_HOLD_KEYS
    assert (short["event_id"], short["event_name"]) == (str(event.id), "Riverbank Fair")
    assert short["coordinator_name"] == Users.COORDINATOR.full_name
    assert (short["units_held"], short["units_short"]) == (3, 1)
    assert datetime.fromisoformat(short["starts_at"]) == event.starts_at
    assert (
        db.scalar(
            select(func.count()).where(EquipmentUnavailabilityPeriod.equipment_type_id == kit.id)
        )
        == 0
    )
    assert _short_notices(db, event) == []


@pytest.mark.story("16.2", ac=5)
def test_the_check_lists_nothing_when_the_holds_stay_covered(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=4)
    _held(db, _event(db), kit, 3)

    response = _check(tech_client, kit.id, quantity=1, starts_at=_days(10), ends_at=_days(12))

    assert response.json() == {"short_holds": []}


@pytest.mark.story("16.2", ac=5)
def test_the_check_lists_a_hold_of_an_event_with_no_coordinator_yet(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=1)
    _held(db, _event(db, coordinator=None), kit, 1)

    response = _check(tech_client, kit.id, quantity=1, starts_at=_days(10), ends_at=None)

    [short] = response.json()["short_holds"]
    assert short["coordinator_name"] is None


@pytest.mark.story("16.2", ac=5)
def test_the_check_lists_short_holds_soonest_first(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=1)
    later = _event(db, start=20, end=20.5, name="Later fair")
    sooner = _event(db, start=10.5, end=11, name="Sooner fair")
    _held(db, later, kit, 1)
    _held(db, sooner, kit, 1)

    response = _check(tech_client, kit.id, quantity=1, starts_at=_days(1), ends_at=None)

    assert [each["event_name"] for each in response.json()["short_holds"]] == [
        "Sooner fair",
        "Later fair",
    ]


@pytest.mark.story("16.2", ac=5)
@pytest.mark.story("16.2", ac=3)
def test_the_check_refuses_what_saving_would(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=2)

    too_many = _check(tech_client, kit.id, quantity=3, starts_at=_days(1), ends_at=_days(2))
    backwards = _check(tech_client, kit.id, quantity=1, starts_at=_days(2), ends_at=_days(1))
    past = _check(tech_client, kit.id, quantity=1, starts_at=_days(-1), ends_at=_days(2))
    nothing = _check(tech_client, kit.id, quantity=0, starts_at=_days(1), ends_at=_days(2))

    assert (too_many.status_code, too_many.json()["detail"]) == (
        409,
        service.too_many_out_message(most=2),
    )
    assert (backwards.status_code, backwards.json()["detail"]) == (
        422,
        schemas.OUT_OF_SERVICE_END_NOT_AFTER_START_MESSAGE,
    )
    assert (past.status_code, past.json()["detail"]) == (422, service.START_IN_THE_PAST_MESSAGE)
    assert nothing.status_code == 422


@pytest.mark.story("16.2", ac=5)
def test_the_check_of_an_edit_leaves_the_record_itself_out(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=3)
    _held(db, _event(db), kit, 2)
    record = _out(db, kit, 1, start=10, end=12)

    unchanged = _check(
        tech_client, kit.id, quantity=1, starts_at=_days(10), ends_at=_days(12), record_id=record.id
    )
    raised = _check(
        tech_client, kit.id, quantity=2, starts_at=_days(10), ends_at=_days(12), record_id=record.id
    )

    assert unchanged.json() == {"short_holds": []}
    [short] = raised.json()["short_holds"]
    assert short["units_short"] == 1


@pytest.mark.story("16.2", ac=5)
@pytest.mark.story("16.2", ac=3)
def test_the_check_of_an_edit_keeps_a_record_in_force_to_its_start(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=3)
    record = _out(db, kit, 1, start=-1, end=2)

    same_start = _check(
        tech_client,
        kit.id,
        quantity=2,
        starts_at=record.starts_at,
        ends_at=_days(2),
        record_id=record.id,
    )
    moved = _check(
        tech_client, kit.id, quantity=2, starts_at=_days(1), ends_at=_days(2), record_id=record.id
    )
    unknown = _check(
        tech_client,
        kit.id,
        quantity=1,
        starts_at=_days(1),
        ends_at=_days(2),
        record_id=uuid.uuid4(),
    )

    assert same_start.status_code == 200
    assert (moved.status_code, moved.json()["detail"]) == (409, service.RECORD_START_LOCKED_MESSAGE)
    assert unknown.status_code == 404


@pytest.mark.story("16.2", ac=4)
def test_saving_a_record_that_leaves_a_hold_short_tells_its_coordinator(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=3, name="Mobile kit")
    event = _event(db, name="Harbour Lights")
    hold = _held(db, event, kit, 3)

    assert (
        tech_client.post(_records_path(kit.id), json=_body(1, start=10, end=12)).status_code == 201
    )

    [notice] = _short_notices(db, event)
    assert notice.recipient_id == Users.COORDINATOR.id
    assert notice.title == "Equipment short: Harbour Lights"
    assert notice.message == (
        "Mobile kit: 1 of the 3 held for this event cannot be supplied, as they are out of service."
    )
    assert (notice.related_entity_type, notice.related_entity_id) == (
        "equipment_reservation",
        hold.id,
    )


@pytest.mark.story("16.2", ac=4)
def test_the_coordinators_notice_opens_the_event(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=1)
    event = _event(db)
    _held(db, event, kit, 1)
    tech_client.post(_records_path(kit.id), json=_body(1, start=10, end=12))

    tech_client.login(Users.COORDINATOR)
    notices = tech_client.get("/notifications").json()

    [notice] = [each for each in notices if each["event_id"] == str(event.id)]
    assert notice["target"] == {"kind": "event", "id": str(event.id)}


@pytest.mark.story("16.2", ac=4)
def test_only_the_hold_placed_last_is_short_and_only_its_coordinator_is_told(
    tech_client, db: Session
):
    kit = make_equipment_type(db, total_quantity=4)
    one = _event(db, coordinator=Users.COORDINATOR.id)
    two = _event(db, coordinator=Users.COORDINATOR_2.id)
    holds = {one.id: _held(db, one, kit, 2), two.id: _held(db, two, kit, 2)}
    # The hold placed first has the larger id, so serving them in id order would get it wrong.
    earlier, later = sorted((one, two), key=lambda event: holds[event.id].id, reverse=True)
    holds[earlier.id].reserved_at = _now() - timedelta(days=9)
    holds[later.id].reserved_at = _now() - timedelta(days=1)
    db.flush()

    tech_client.post(_records_path(kit.id), json=_body(1, start=10, end=12))

    assert _short_notices(db, earlier) == []
    [notice] = _short_notices(db, later)
    assert notice.recipient_id == later.assigned_coordinator_id


@pytest.mark.story("16.2", ac=4)
def test_a_hold_already_short_is_not_told_again(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=3)
    event = _event(db)
    _held(db, event, kit, 3)
    _out(db, kit, 1, start=10, end=12)  # already leaves it short

    tech_client.post(_records_path(kit.id), json=_body(1, start=10.6, end=12))

    assert _short_notices(db, event) == []


@pytest.mark.story("16.2", ac=4)
def test_a_record_leaving_every_hold_covered_tells_nobody(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=4)
    event = _event(db)
    _held(db, event, kit, 3)

    tech_client.post(_records_path(kit.id), json=_body(1, start=10, end=12))

    assert _short_notices(db, event) == []


@pytest.mark.story("16.2", ac=4)
def test_a_hold_of_an_event_with_no_coordinator_is_marked_but_nobody_is_told(
    tech_client, db: Session
):
    kit = make_equipment_type(db, total_quantity=1)
    event = _event(db, coordinator=None)
    hold = _held(db, event, kit, 1)

    tech_client.post(_records_path(kit.id), json=_body(1, start=10, end=12))

    assert _short_notices(db, event) == []
    tech_client.login(Users.COORDINATOR)
    assert _shortages(tech_client, event) == [
        {"item_id": str(_item_of(db, hold)), "units_short": 1}
    ]


@pytest.mark.story("16.2", ac=4)
def test_a_hold_released_or_in_the_past_is_never_short(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=2)
    gone = _event(db, start=-3, end=-2)
    released = _event(db)
    _held(db, gone, kit, 2)
    released_hold = _held(db, released, kit, 2)
    released_hold.status = "RELEASED"
    released_hold.released_quantity = 2
    db.flush()

    response = _check(tech_client, kit.id, quantity=2, starts_at=_days(0), ends_at=None)

    assert response.json() == {"short_holds": []}


@pytest.mark.story("16.2", ac=4)
def test_a_partly_released_hold_is_short_only_of_the_units_it_still_holds(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=3)
    hold = _held(db, _event(db), kit, 3)
    hold.released_quantity = 2
    db.flush()

    two = _check(tech_client, kit.id, quantity=2, starts_at=_days(10), ends_at=None)
    three = _check(tech_client, kit.id, quantity=3, starts_at=_days(10), ends_at=None)

    assert two.json() == {"short_holds": []}
    [short] = three.json()["short_holds"]
    assert (short["units_held"], short["units_short"]) == (1, 1)


@pytest.mark.story("16.2", ac=4)
def test_the_events_equipment_shows_the_item_short_until_an_edit_covers_it_again(
    tech_client, db: Session
):
    kit = make_equipment_type(db, total_quantity=3)
    event = _event(db)
    hold = _held(db, event, kit, 3)
    record_id = tech_client.post(_records_path(kit.id), json=_body(2, start=10, end=12)).json()[
        "id"
    ]
    item = str(_item_of(db, hold))

    tech_client.login(Users.COORDINATOR)
    assert _shortages(tech_client, event) == [{"item_id": item, "units_short": 2}]

    tech_client.login(Users.TECH_SUPPORT)
    tech_client.patch(_record_path(kit.id, uuid.UUID(record_id)), json={"quantity": 1})
    tech_client.login(Users.COORDINATOR)
    assert _shortages(tech_client, event) == [{"item_id": item, "units_short": 1}]

    tech_client.login(Users.TECH_SUPPORT)
    tech_client.delete(_record_path(kit.id, uuid.UUID(record_id)))
    tech_client.login(Users.COORDINATOR)
    assert _shortages(tech_client, event) == []


@pytest.mark.story("16.2", ac=4)
def test_ending_a_record_in_force_clears_the_mark(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=1)
    event = _event(db)
    _held(db, event, kit, 1)
    record = _out(db, kit, 1, start=-1, end=None)

    tech_client.login(Users.COORDINATOR)
    assert len(_shortages(tech_client, event)) == 1

    tech_client.login(Users.TECH_SUPPORT)
    tech_client.patch(_record_path(kit.id, record.id), json={"end_now": True})
    tech_client.login(Users.COORDINATOR)
    assert _shortages(tech_client, event) == []


@pytest.mark.story("16.2", ac=4)
def test_an_events_shortages_list_only_its_own_items(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=1)
    mine, theirs = _event(db), _event(db)
    _held(db, theirs, kit, 1, placed_days_ago=9)
    my_hold = _held(db, mine, kit, 1, placed_days_ago=1)
    _out(db, make_equipment_type(db), 1, start=1, end=None)  # another type: no effect here

    tech_client.login(Users.COORDINATOR)

    assert _shortages(tech_client, mine) == [
        {"item_id": str(_item_of(db, my_hold)), "units_short": 1}
    ]
    assert _shortages(tech_client, theirs) == []


@pytest.mark.story("16.2", ac=4)
def test_an_events_shortages_are_read_by_internal_roles_and_not_by_its_organiser(
    client, db: Session
):
    event = _event(db)

    for user, expected in (
        (Users.COORDINATOR, 200),
        (Users.TECH_SUPPORT, 200),
        (Users.ORGANISER, 403),
        (Users.ATTENDEE, 403),
    ):
        client.login(user)
        assert client.get(f"/events/{event.id}/equipment-shortages").status_code == expected
    client.login(Users.COORDINATOR)
    assert client.get(f"/events/{uuid.uuid4()}/equipment-shortages").status_code == 404


# =============================================================================================
# AC6 - Technical Support only
# =============================================================================================
def _every_call(type_id: uuid.UUID, record_id: uuid.UUID) -> list[tuple[str, str, dict]]:
    body = _body()
    return [
        ("get", TYPES_PATH, {}),
        ("get", f"{TYPES_PATH}/{type_id}", {}),
        (
            "get",
            f"{_records_path(type_id)}/check",
            {"params": {"quantity": 1, "starts_at": body["starts_at"]}},
        ),
        ("post", _records_path(type_id), {"json": body}),
        ("patch", _record_path(type_id, record_id), {"json": {"quantity": 1}}),
        ("delete", _record_path(type_id, record_id), {}),
    ]


@pytest.mark.story("16.2", ac=6)
@pytest.mark.parametrize("user", NOT_TECH_SUPPORT)
def test_every_other_role_is_refused_every_call(login_as, db: Session, user):
    kit = make_equipment_type(db)
    record = _out(db, kit, 1, start=1, end=2)
    signed_in = login_as(user)

    for method, path, options in _every_call(kit.id, record.id):
        assert getattr(signed_in, method)(path, **options).status_code == 403, (method, path)
    db.refresh(record)
    assert record.quantity == 1


@pytest.mark.story("16.2", ac=6)
def test_signed_out_users_are_refused_every_call(client, db: Session):
    kit = make_equipment_type(db)
    record = _out(db, kit, 1, start=1, end=2)

    for method, path, options in _every_call(kit.id, record.id):
        assert getattr(client, method)(path, **options).status_code == 401, (method, path)
    assert client.get(f"/events/{uuid.uuid4()}/equipment-shortages").status_code == 401


# =============================================================================================
# AC7 - real concurrent transactions. These commit, so each cleans up after itself.
# =============================================================================================
CREATED = "created"


@contextmanager
def _committed_kit(engine, *, stock: int) -> Iterator[tuple[uuid.UUID, uuid.UUID]]:
    """A fresh type of ``stock`` units and an event in Planning for coordinator 1, committed so
    other connections see them, then removed with everything the race wrote."""
    with Session(engine) as session:
        kit = make_equipment_type(session, total_quantity=stock)
        event = _event(session)
        session.commit()
        kit_id, event_id = kit.id, event.id
    try:
        yield kit_id, event_id
    finally:
        with Session(engine) as session:
            records = select(EquipmentUnavailabilityPeriod.id).where(
                EquipmentUnavailabilityPeriod.equipment_type_id == kit_id
            )
            items = select(EventEquipmentRequest.id).where(
                EventEquipmentRequest.event_id == event_id
            )
            session.execute(delete(AuditLog).where(AuditLog.entity_id.in_(records)))
            session.execute(delete(AuditLog).where(AuditLog.entity_id.in_(items)))
            session.execute(delete(AuditLog).where(AuditLog.entity_id == event_id))
            session.execute(
                delete(EquipmentUnavailabilityPeriod).where(
                    EquipmentUnavailabilityPeriod.equipment_type_id == kit_id
                )
            )
            session.execute(delete(Notification).where(Notification.event_id == event_id))
            session.execute(
                delete(EquipmentReservation).where(EquipmentReservation.event_id == event_id)
            )
            session.execute(
                delete(EventEquipmentRequest).where(EventEquipmentRequest.event_id == event_id)
            )
            session.execute(delete(Event).where(Event.id == event_id))
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
        return [future.result(timeout=30) for future in [pool.submit(run, a) for a in attempts]]


def _recorder(kit_id: uuid.UUID, quantity: int):
    def attempt(session: Session) -> str:
        actor = session.get(User, Users.TECH_SUPPORT.id)
        data = schemas.OutOfServiceIn(**_body(quantity, start=10, end=12))
        try:
            service.add_out_of_service(session, kit_id, data, actor=actor, now=_now())
        except service.TooManyOutOfService as refusal:
            return str(refusal)
        return CREATED

    return attempt


def _holder(event_id: uuid.UUID, kit_id: uuid.UUID, quantity: int):
    def attempt(session: Session) -> str:
        actor = session.get(User, Users.COORDINATOR.id)
        code = session.get(EquipmentType, kit_id).code
        item = schemas.EquipmentItemIn(equipment_type_code=code, quantity=quantity)
        try:
            service.add_equipment_item(session, event_id, item, actor=actor)
        except service.EquipmentNotAvailable as refusal:
            return str(refusal)
        return CREATED

    return attempt


@pytest.mark.story("16.2", ac=7)
def test_two_records_racing_for_the_last_units_never_exceed_the_stock(engine):
    with _committed_kit(engine, stock=3) as (kit_id, _event_id):
        outcomes = _race(engine, [_recorder(kit_id, 2), _recorder(kit_id, 2)])

        assert sorted(outcomes) == sorted([CREATED, service.too_many_out_message(most=1)])
        with Session(engine) as session:
            assert (
                session.scalar(
                    select(func.sum(EquipmentUnavailabilityPeriod.quantity)).where(
                        EquipmentUnavailabilityPeriod.equipment_type_id == kit_id
                    )
                )
                == 2
            )


@pytest.mark.story("16.2", ac=7)
@pytest.mark.story("16.2", ac=4)
def test_a_record_racing_a_hold_for_the_last_units_is_seen_by_it_or_sees_it(engine):
    """Records are bounded by the stock, not by holds (AC3), so the record is always saved. Each
    takes the type's row first, so the second sees the first: a hold placed after the record is
    refused, and a record saved after the hold leaves it short and tells its coordinator (AC4).
    Without the lock, both would go through and nobody would be told."""
    with _committed_kit(engine, stock=3) as (kit_id, event_id):
        record, hold = _race(engine, [_recorder(kit_id, 2), _holder(event_id, kit_id, 2)])

        assert record == CREATED
        with Session(engine) as session:
            name = session.get(EquipmentType, kit_id).name
            told = session.scalar(
                select(func.count()).where(
                    Notification.event_id == event_id,
                    Notification.notification_type == NotificationType.EQUIPMENT_SHORT,
                )
            )
        if hold == CREATED:
            assert told == 1
        else:
            assert hold == service.EquipmentNotAvailable(name).args[0]
            assert told == 0


# --- AC2 / AC3 / AC4 - at the very moment a record starts or ends ------------------------------
# The service is called with ``now`` given, so a record can start or end exactly then.
def _out_at(
    db: Session, equipment_type: EquipmentType, quantity: int, *, starts_at, ends_at
) -> EquipmentUnavailabilityPeriod:
    record = EquipmentUnavailabilityPeriod(
        equipment_type_id=equipment_type.id,
        quantity=quantity,
        reason="MAINTENANCE",
        starts_at=starts_at,
        ends_at=ends_at,
    )
    db.add(record)
    db.flush()
    return record


@pytest.mark.story("16.2", ac=2)
def test_a_record_starting_this_moment_is_out_now_and_one_ending_this_moment_is_not(
    db: Session,
):
    kit = make_equipment_type(db, total_quantity=5)
    moment = _days(1)
    starting = _out_at(db, kit, 2, starts_at=moment, ends_at=moment + timedelta(days=1))
    _out_at(db, kit, 1, starts_at=moment - timedelta(days=1), ends_at=moment)

    page = service.get_equipment_type_page(db, kit.id, now=moment)
    [entry] = [
        each
        for each in service.list_equipment_catalogue(db, now=moment)
        if each.equipment_type.id == kit.id
    ]

    assert [record.id for record in page.records] == [starting.id]
    assert page.out_of_service_now == entry.out_of_service_now == 2


@pytest.mark.story("16.2", ac=2)
@pytest.mark.story("16.2", ac=3)
def test_a_record_starting_this_moment_has_not_started(db: Session):
    """In force only once its start has passed: at that very moment it is not ended but moved or
    removed, as one still to come is."""
    kit = make_equipment_type(db)
    actor = db.get(User, Users.TECH_SUPPORT.id)
    moment = _days(1)
    record = _out_at(db, kit, 1, starts_at=moment, ends_at=moment + timedelta(days=1))

    with pytest.raises(service.RecordNotStarted):
        service.edit_out_of_service(
            db, kit.id, record.id, schemas.OutOfServiceUpdate(end_now=True), actor=actor, now=moment
        )
    later = moment + timedelta(hours=1)
    moved = service.edit_out_of_service(
        db, kit.id, record.id, schemas.OutOfServiceUpdate(starts_at=later), actor=actor, now=moment
    )
    assert moved.starts_at == later
    service.remove_out_of_service(db, kit.id, record.id, actor=actor, now=later)
    assert db.get(EquipmentUnavailabilityPeriod, record.id) is None


@pytest.mark.story("16.2", ac=3)
def test_a_record_ending_this_moment_has_ended(db: Session):
    kit = make_equipment_type(db)
    actor = db.get(User, Users.TECH_SUPPORT.id)
    moment = _days(1)
    record = _out_at(db, kit, 1, starts_at=moment - timedelta(days=1), ends_at=moment)

    with pytest.raises(service.RecordEnded):
        service.edit_out_of_service(
            db, kit.id, record.id, schemas.OutOfServiceUpdate(quantity=2), actor=actor, now=moment
        )


@pytest.mark.story("16.2", ac=2)
def test_types_sharing_a_name_are_listed_in_id_order(tech_client, db: Session):
    ids = sorted(uuid.uuid4() for _ in range(5))
    # Written in the reverse of id order, so the order cannot come from the order they were written.
    for type_id in reversed(ids):
        make_equipment_type(db, id=type_id, name="Twin kit")

    listed = [
        each["id"] for each in tech_client.get(TYPES_PATH).json() if each["name"] == "Twin kit"
    ]

    assert listed == [str(type_id) for type_id in ids]


@pytest.mark.story("16.2", ac=3)
def test_a_record_starting_after_the_period_ends_does_not_count(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=5)
    _out(db, kit, 5, start=20, end=None)

    response = tech_client.post(_records_path(kit.id), json=_body(5, start=10, end=12))

    assert response.status_code == 201


@pytest.mark.story("16.2", ac=5)
def test_the_check_leaves_out_a_hold_after_the_record_ends(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=1)
    _held(db, _event(db, start=20, end=20.5), kit, 1)

    response = _check(tech_client, kit.id, quantity=1, starts_at=_days(10), ends_at=_days(12))

    assert response.json() == {"short_holds": []}


@pytest.mark.story("16.2", ac=4)
def test_a_hold_already_short_does_not_stop_a_newly_short_one_being_told(tech_client, db: Session):
    """Holds are judged soonest first: the sooner one, short already, comes first and is passed
    over; the later one the new record leaves short is still told."""
    kit = make_equipment_type(db, total_quantity=2)
    sooner = _event(db, start=10.5, end=11)
    later = _event(db, start=20.25, end=20.75, coordinator=Users.COORDINATOR_2.id)
    _held(db, sooner, kit, 2)
    _held(db, later, kit, 2)
    _out(db, kit, 1, start=10, end=11.5)  # already leaves the sooner short

    tech_client.post(_records_path(kit.id), json=_body(1, start=20, end=21))

    assert _short_notices(db, sooner) == []
    [notice] = _short_notices(db, later)
    assert notice.recipient_id == Users.COORDINATOR_2.id
