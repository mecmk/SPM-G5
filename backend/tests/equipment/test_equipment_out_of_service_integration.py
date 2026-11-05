"""Story 16.2 - mark equipment out of service. INTEGRATION tests: the API on PostgreSQL.

Level: integration. Each test calls the ``/equipment-types`` endpoints, or an event's
``/equipment-shortages``, through a signed-in client against the real schema in the rolled-back
test transaction; AC7's races run real concurrent transactions, which commit, so they clean up
after themselves. The counting rules on their own are unit-tested in
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
    have out at any moment of its period still to come. The end must be after the start, and
    after now (End stops a record now). The start cannot be in the past, a record in force keeps
    its start, and an ended record cannot be edited.
AC4 When the units left cannot cover the holds on that type over the period, the holds that
    cannot be covered - the most recently placed first - are marked short on their event's
    equipment list. Each time a save leaves a hold short, or shorter than before, its event's
    coordinator is notified with the event, the equipment and how many units are short. Only the
    part still to come counts, and the mark follows the records: an edit or End that frees enough
    units clears it.
AC5 Before saving, the server checks the quantity against the stock and returns the holds the
    record would leave short, or shorter than they already are - the same holds whose coordinators
    saving tells - so the page can show them and ask to confirm. Saving re-runs AC3's checks, and
    counts a hold placed in between.
AC6 Only Technical Support Staff can open the catalogue and the type pages, and record, edit or
    end records: others get 403 and signed-out users 401.
AC7 Records that overlap in time add up and never exceed the stock, also when two are saved at
    once, or one is saved as a hold is placed or accepted.
AC9 (fix f16.2.2) Technical Support's holds schedule (17.3) marks each hold short by the units
    AC4 marks on its event, and none on a hold left whole. (AC8, the event page's wording, is
    e2e-tested.)
AC10 (fix f16.2.4) A save that leaves an item short of every unit it holds closes it as Out of
    service, whatever its stage - not yet sent, Pending or Accepted: its hold is released, it no
    longer takes up its type, and it is kept for the record, as a withdrawn one is. Its coordinator
    is told it was closed, not that it is short. An Accepted one on an event Awaiting Safety Check
    or Confirmed sends the event back to Planning, and the organiser and the Safety Officers are
    told, as a withdrawal does (17.2 AC9). A later edit, End or removal of the record does not
    reopen it, and it can no longer be decided, withdrawn or edited. The save takes the events
    holding the type before the type, as every other write does, so it waits for their writes.
AC11 (fix f16.2.4) An item left short of only some of its units keeps its status and its hold,
    and its coordinator is told how short it is (AC4). (Its wording on the event page is
    e2e-tested.)
AC12 (fix f16.2.4) Before saving, the check says which holds saving would close. Technical
    Support's queue lists an item closed after it was sent to them under Out of service, with no
    figures, as a withdrawn one is; one closed before it was ever sent is not theirs.
AC13 (fix f16.2.4) An event's shortages - what its equipment page says about units out of
    service - are read only by the event's own coordinator, the Event Coordinator Leads and
    Technical Support; anyone else is refused (403).
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.common.audit import AuditLog
from app.equipment import schemas, service
from app.events import service as events_service
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
HOLDS_PATH = "/equipment-holds"
RECORD_KEYS = {"id", "quantity", "reason", "notes", "starts_at", "ends_at"}
CATALOGUE_KEYS = {"id", "code", "name", "total_quantity", "out_of_service_now", "records"}
TYPE_PAGE_KEYS = CATALOGUE_KEYS | {"description", "storage_location", "records"}
SHORT_HOLD_KEYS = {
    "event_id",
    "event_name",
    "coordinator_name",
    "units_held",
    "units_short",
    "starts_at",
    "ends_at",
    "closes",
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
    status: str = EventStatus.PLANNING,
    **overrides,
) -> Event:
    """An event, in Planning unless ``status`` says otherwise, from ``start`` to ``end`` days from
    now."""
    return make_event(
        db,
        status=status,
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
    status: str = "ACCEPTED",
) -> EquipmentReservation:
    """An item of ``units`` on ``event`` - accepted unless ``status`` says otherwise - held for the
    event's period, placed ``placed_days_ago`` days ago - the order holds are served in (AC4)."""
    item = make_equipment_item(
        db, event=event, equipment_type=equipment_type, quantity=units, status=status
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
def test_the_catalogue_lists_each_types_current_records_so_a_scheduled_period_is_seen(
    tech_client, db: Session
):
    kit = make_equipment_type(db, total_quantity=9)
    later = _out(db, kit, 4, start=1, end=None)  # scheduled, no end
    in_force = _out(db, kit, 2, start=-1, end=3)
    _out(db, kit, 1, start=-4, end=-1)  # ended: not current
    bare = make_equipment_type(db, total_quantity=2)

    entries = {each["id"]: each for each in tech_client.get(TYPES_PATH).json()}

    entry = entries[str(kit.id)]
    assert entry["out_of_service_now"] == 2
    assert [record["id"] for record in entry["records"]] == [str(in_force.id), str(later.id)]
    assert set(entry["records"][0]) == RECORD_KEYS
    scheduled = entry["records"][1]
    assert (scheduled["quantity"], scheduled["ends_at"]) == (4, None)
    assert scheduled["starts_at"].replace("+00:00", "Z") == later.starts_at.isoformat().replace(
        "+00:00", "Z"
    )
    assert entries[str(bare.id)]["records"] == []


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


@pytest.mark.story("16.2", ac=1)
@pytest.mark.story("16.2", ac=7)
def test_records_one_after_another_hold_back_only_the_most_out_at_once(tech_client, db: Session):
    """Records that do not overlap do not add up (AC7), so an event across both is offered what
    the busier one leaves - 1 of 3 here - not the stock less the two together."""
    kit = make_equipment_type(db, total_quantity=3)
    event = _event(db, start=10, end=12)
    _out(db, kit, 1, start=10, end=10.9)
    _out(db, kit, 2, start=11, end=12)

    tech_client.login(Users.COORDINATOR)
    figures = tech_client.get(f"/events/{event.id}/equipment-availability").json()
    held = tech_client.post(
        f"/events/{event.id}/equipment", json={"equipment_type_code": kit.code, "quantity": 1}
    )

    [figure] = [each for each in figures if each["equipment_type_code"] == kit.code]
    assert figure["available"] == 1
    assert held.status_code == 201


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
    [
        {"quantity": 0},
        {"quantity": "two"},
        {"quantity": "2"},
        {"quantity": True},
        {"quantity": 1.5},
        {"reason": "STOLEN"},
        {"notes": "n" * 1001},
        {"starts_at": None},
    ],
    ids=[
        "quantity-0",
        "not-a-number",
        "number-in-quotes",
        "true",
        "fraction",
        "unknown-reason",
        "note-over-1000",
        "no-start",
    ],
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
def test_a_record_sent_with_no_start_is_refused(tech_client, db: Session):
    kit = make_equipment_type(db)
    body = _body()
    del body["starts_at"]

    response = tech_client.post(_records_path(kit.id), json=body)

    assert response.status_code == 422
    assert (
        db.scalar(
            select(func.count()).where(EquipmentUnavailabilityPeriod.equipment_type_id == kit.id)
        )
        == 0
    )


@pytest.mark.story("16.2", ac=3)
@pytest.mark.parametrize("quantity", ["2", True, 1.5], ids=["number-in-quotes", "true", "fraction"])
def test_an_edit_to_a_quantity_that_is_not_a_whole_number_is_refused(
    tech_client, db: Session, quantity
):
    kit = make_equipment_type(db, total_quantity=5)
    record = _out(db, kit, 1, start=3, end=4)

    response = tech_client.patch(_record_path(kit.id, record.id), json={"quantity": quantity})

    assert response.status_code == 422
    db.refresh(record)
    assert record.quantity == 1


@pytest.mark.story("16.2", ac=3)
def test_an_edit_ending_a_record_in_the_past_is_refused_and_points_to_end(tech_client, db: Session):
    """End brings a record's units back now; an edit cannot end it before now, which would take
    it off the list with no way to correct it. The check refuses it as saving would (AC5)."""
    kit = make_equipment_type(db)
    record = _out(db, kit, 1, start=-1, end=None)
    past = _days(-0.5)

    checked = _check(
        tech_client,
        kit.id,
        quantity=1,
        starts_at=record.starts_at,
        ends_at=past,
        record_id=record.id,
    )
    edited = tech_client.patch(_record_path(kit.id, record.id), json={"ends_at": past.isoformat()})

    assert (checked.status_code, checked.json()["detail"]) == (422, service.END_IN_THE_PAST_MESSAGE)
    assert (edited.status_code, edited.json()["detail"]) == (422, service.END_IN_THE_PAST_MESSAGE)
    db.refresh(record)
    assert record.ends_at is None


@pytest.mark.story("16.2", ac=3)
def test_raising_a_record_in_force_counts_only_the_records_still_to_come(tech_client, db: Session):
    """Units out before now cannot meet the units this record has out from now on."""
    kit = make_equipment_type(db, total_quantity=3)
    record = _out(db, kit, 1, start=-5, end=None)
    _out(db, kit, 2, start=-4, end=-2)  # over two days ago

    response = tech_client.patch(_record_path(kit.id, record.id), json={"quantity": 2})

    assert response.status_code == 200
    db.refresh(record)
    assert record.quantity == 2


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
def test_the_check_leaves_out_a_hold_another_record_left_short(tech_client, db: Session):
    """The list is the holds this record leaves short, or shorter - the ones whose coordinators
    saving it tells (AC4) - not every hold of the type already short."""
    kit = make_equipment_type(db, total_quantity=3)
    _held(db, _event(db), kit, 3)
    _out(db, kit, 1, start=10, end=12)  # already leaves the hold 1 short

    response = _check(tech_client, kit.id, quantity=1, starts_at=_days(30), ends_at=_days(31))

    assert response.json() == {"short_holds": []}


@pytest.mark.story("16.2", ac=5)
def test_the_check_lists_a_hold_already_short_that_the_record_leaves_shorter(
    tech_client, db: Session
):
    kit = make_equipment_type(db, total_quantity=3)
    _held(db, _event(db), kit, 3)
    _out(db, kit, 1, start=10, end=12)

    response = _check(tech_client, kit.id, quantity=1, starts_at=_days(10), ends_at=_days(12))

    [short] = response.json()["short_holds"]
    assert (short["units_held"], short["units_short"]) == (3, 2)


@pytest.mark.story("16.2", ac=5)
def test_the_check_of_an_edit_that_eases_a_shortage_lists_nothing(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=3)
    _held(db, _event(db), kit, 3)
    record = _out(db, kit, 2, start=10, end=12)  # leaves the hold 2 short

    response = _check(
        tech_client,
        kit.id,
        quantity=1,
        starts_at=record.starts_at,
        ends_at=record.ends_at,
        record_id=record.id,
    )

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
def test_a_hold_already_short_is_not_told_again_by_a_record_leaving_it_no_shorter(
    tech_client, db: Session
):
    kit = make_equipment_type(db, total_quantity=3)
    event = _event(db)
    _held(db, event, kit, 3)
    _out(db, kit, 1, start=10, end=12)  # already leaves it 1 short

    tech_client.post(_records_path(kit.id), json=_body(1, start=30, end=31))

    assert _short_notices(db, event) == []


@pytest.mark.story("16.2", ac=4)
def test_a_hold_left_shorter_is_told_again_how_short_it_now_is(tech_client, db: Session):
    # Fix f16.2.4: a unit is left, as a hold short of every unit is closed instead (AC10).
    kit = make_equipment_type(db, total_quantity=4, name="Mobile kit")
    event = _event(db)
    _held(db, event, kit, 4)
    tech_client.post(_records_path(kit.id), json=_body(1, start=10, end=12))

    tech_client.post(_records_path(kit.id), json=_body(2, start=10, end=12))

    assert sorted(notice.message for notice in _short_notices(db, event)) == [
        service.short_message(name="Mobile kit", short=1, held=4),
        service.short_message(name="Mobile kit", short=3, held=4),
    ]


@pytest.mark.story("16.2", ac=4)
def test_an_edit_that_leaves_a_hold_short_tells_its_coordinator(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=3)
    event = _event(db)
    _held(db, event, kit, 3)
    record = _out(db, kit, 1, start=20, end=21)  # clear of the event

    response = tech_client.patch(
        _record_path(kit.id, record.id),
        json={"starts_at": _days(10).isoformat(), "ends_at": _days(12).isoformat()},
    )

    assert response.status_code == 200
    [notice] = _short_notices(db, event)
    assert notice.recipient_id == Users.COORDINATOR.id


@pytest.mark.story("16.2", ac=4)
def test_an_edit_of_only_the_note_tells_nobody(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=3)
    event = _event(db)
    _held(db, event, kit, 3)
    record = _out(db, kit, 1, start=10, end=12)  # leaves the hold 1 short, as it did before

    response = tech_client.patch(
        _record_path(kit.id, record.id), json={"notes": "Sent away for repair"}
    )

    assert response.status_code == 200
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
    # Fix f16.2.4: a unit is left, as a hold short of every unit is closed instead (AC10).
    kit = make_equipment_type(db, total_quantity=2)
    event = _event(db, coordinator=None)
    hold = _held(db, event, kit, 2)

    tech_client.post(_records_path(kit.id), json=_body(1, start=10, end=12))

    assert _short_notices(db, event) == []
    # Fix f16.2.4 (AC13): read by the Lead, who assigns its coordinator; another coordinator is
    # refused.
    tech_client.login(Users.LEAD)
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
    record_path = _record_path(
        kit.id,
        uuid.UUID(
            tech_client.post(_records_path(kit.id), json=_body(2, start=10, end=12)).json()["id"]
        ),
    )
    item = str(_item_of(db, hold))

    tech_client.login(Users.COORDINATOR)
    assert _shortages(tech_client, event) == [{"item_id": item, "units_short": 2}]

    tech_client.login(Users.TECH_SUPPORT)
    tech_client.patch(record_path, json={"quantity": 1})
    tech_client.login(Users.COORDINATOR)
    assert _shortages(tech_client, event) == [{"item_id": item, "units_short": 1}]

    tech_client.login(Users.TECH_SUPPORT)
    moved = {"starts_at": _days(20).isoformat(), "ends_at": _days(21).isoformat()}
    assert tech_client.patch(record_path, json=moved).status_code == 200
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
# AC9 (fix f16.2.2) - the holds schedule marks a short hold as its event's equipment does
# =============================================================================================
def _schedule_shortfalls(client, kind: EquipmentType) -> dict[str, int]:
    """Each hold of ``kind`` on the holds schedule (17.3), by id, with the units it is short."""
    response = client.get(HOLDS_PATH, params={"type": kind.code})
    assert response.status_code == 200, response.text
    [group] = response.json()["groups"]
    return {hold["id"]: hold["units_short"] for hold in group["holds"]}


@pytest.mark.story("16.2", ac=9)
def test_the_holds_schedule_says_how_many_units_a_hold_is_short(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=3)
    hold = _held(db, _event(db), kit, 3)

    tech_client.post(_records_path(kit.id), json=_body(2, start=10, end=12))

    assert _schedule_shortfalls(tech_client, kit) == {str(hold.id): 2}


@pytest.mark.story("16.2", ac=9)
def test_the_schedule_marks_the_hold_its_event_shows_short_the_latest_placed_first(
    tech_client, db: Session
):
    kit = make_equipment_type(db, total_quantity=2)
    first_event, later_event = _event(db), _event(db)
    first = _held(db, first_event, kit, 1, placed_days_ago=9)
    later = _held(db, later_event, kit, 1, placed_days_ago=1)
    _out(db, kit, 1, start=1, end=None)

    assert _schedule_shortfalls(tech_client, kit) == {str(first.id): 0, str(later.id): 1}
    tech_client.login(Users.COORDINATOR)
    assert _shortages(tech_client, first_event) == []
    assert _shortages(tech_client, later_event) == [
        {"item_id": str(_item_of(db, later)), "units_short": 1}
    ]


@pytest.mark.story("16.2", ac=9)
def test_the_schedules_mark_follows_the_records(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=1)
    hold = _held(db, _event(db), kit, 1)
    record = _out(db, kit, 1, start=-1, end=None)
    assert _schedule_shortfalls(tech_client, kit) == {str(hold.id): 1}

    tech_client.patch(_record_path(kit.id, record.id), json={"end_now": True})

    assert _schedule_shortfalls(tech_client, kit) == {str(hold.id): 0}


@pytest.mark.story("16.2", ac=9)
def test_a_record_of_another_type_leaves_the_schedules_holds_whole(tech_client, db: Session):
    kit, other = make_equipment_type(db, total_quantity=1), make_equipment_type(db)
    hold = _held(db, _event(db), kit, 1)
    _out(db, other, 1, start=1, end=None)

    assert _schedule_shortfalls(tech_client, kit) == {str(hold.id): 0}


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


# --- AC7 - a save that finds the type taken waits for it, then counts what it wrote -------------
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


def _with_a_save_under_way(engine, kit_id: uuid.UUID, attempt: Callable[[Session], str]) -> str:
    """Run ``attempt`` while another save holds the type, as every save takes it, with 2 units
    recorded out over days 10-12 and not yet committed. ``attempt`` has to wait for that save,
    then count its units; this asserts the wait and returns what ``attempt`` returned."""
    rival = Session(engine)
    service.lock_types(rival, [kit_id])
    rival.add(
        EquipmentUnavailabilityPeriod(
            equipment_type_id=kit_id,
            quantity=2,
            reason="DAMAGED",
            starts_at=_days(10),
            ends_at=_days(12),
            created_by_id=Users.TECH_SUPPORT.id,
        )
    )
    rival.flush()
    pids: queue.Queue[int] = queue.Queue()
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(_in_own_session, engine, attempt, pids)
        try:
            assert _waited_on_a_lock(engine, waiting, pids)
            rival.commit()
        finally:
            rival.close()  # inside the pool: leaving it waits for whatever this holds up
        return waiting.result(timeout=10)


def _editor(kit_id: uuid.UUID, record_id: uuid.UUID, quantity: int):
    def attempt(session: Session) -> str:
        actor = session.get(User, Users.TECH_SUPPORT.id)
        data = schemas.OutOfServiceUpdate(quantity=quantity)
        try:
            service.edit_out_of_service(session, kit_id, record_id, data, actor=actor, now=_now())
        except service.TooManyOutOfService as refusal:
            return str(refusal)
        return CREATED

    return attempt


@pytest.mark.story("16.2", ac=7)
def test_a_record_waits_for_one_being_saved_and_counts_it(engine):
    with _committed_kit(engine, stock=3) as (kit_id, _event_id):
        outcome = _with_a_save_under_way(engine, kit_id, _recorder(kit_id, 2))

        assert outcome == service.too_many_out_message(most=1)


@pytest.mark.story("16.2", ac=7)
def test_an_edit_waits_for_a_record_being_saved_and_counts_it(engine):
    with _committed_kit(engine, stock=3) as (kit_id, _event_id):
        with Session(engine) as session:
            assert _recorder(kit_id, 1)(session) == CREATED
            [record_id] = session.scalars(
                select(EquipmentUnavailabilityPeriod.id).where(
                    EquipmentUnavailabilityPeriod.equipment_type_id == kit_id
                )
            ).all()

        outcome = _with_a_save_under_way(engine, kit_id, _editor(kit_id, record_id, 2))

        assert outcome == service.too_many_out_message(most=1)


def _accepter(item_id: uuid.UUID):
    def attempt(session: Session) -> str:
        actor = session.get(User, Users.TECH_SUPPORT.id)
        data = schemas.EquipmentDecisionIn(outcome="ACCEPTED")
        try:
            service.decide_equipment_request(session, item_id, data, actor=actor)
        except service.NotEnoughToAccept as refusal:
            return str(refusal)
        return CREATED

    return attempt


@pytest.mark.story("16.2", ac=7)
@pytest.mark.story("16.2", ac=4)
def test_an_accept_and_a_record_saved_at_once_take_turns_without_deadlock(engine):
    """Accept (16.1) takes the event's row, then the type's. Fix f16.2.4: so does a record, which
    may close the event's item (AC10), so the two queue on the event and never wait on each other
    in turn. The event is held first, so Accept is queued on it, and the record behind it, every
    time: Accept reserves all three, then the record leaves the accepted hold one short (AC11)."""
    with _committed_kit(engine, stock=3) as (kit_id, event_id):
        with Session(engine) as session:
            item_id = make_equipment_item(
                session,
                event=session.get(Event, event_id),
                equipment_type=session.get(EquipmentType, kit_id),
                quantity=3,
                status="PENDING",
            ).id
            session.commit()
        holder = Session(engine)
        holder.execute(select(Event.id).where(Event.id == event_id).with_for_update()).all()
        accepting_pids: queue.Queue[int] = queue.Queue()
        saving_pids: queue.Queue[int] = queue.Queue()
        with ThreadPoolExecutor(max_workers=2) as pool:
            try:
                accepting = pool.submit(_in_own_session, engine, _accepter(item_id), accepting_pids)
                assert _waited_on_a_lock(engine, accepting, accepting_pids)
                saving = pool.submit(_in_own_session, engine, _recorder(kit_id, 1), saving_pids)
                assert _waited_on_a_lock(engine, saving, saving_pids)
            finally:
                holder.close()  # inside the pool: leaving it waits for whatever this holds up
            saved, accepted = saving.result(timeout=20), accepting.result(timeout=20)

        assert (saved, accepted) == (CREATED, CREATED)
        with Session(engine) as session:
            item = session.get(EventEquipmentRequest, item_id)
            assert item.status == "ACCEPTED"
            assert [notice.message for notice in _short_notices(session, item.event)] == [
                service.short_message(name=item.equipment_type.name, short=1, held=3)
            ]


# Each lock on an event taken before a type: the two ends of the deadlock above, on every path.
_EVENT_LOCKS = {
    "accept": lambda db, event: service._locked_event_of(db, event.equipment_requests[0].id),
    "coordinators-equipment": lambda db, event: service._event_for_change(
        db, event.id, actor=event.assigned_coordinator
    ),
    "submission": lambda db, event: events_service._get_own_event(
        db, event.id, event.organiser, for_update=True
    ),
    "change-decision": lambda db, event: events_service.get_event_for_update(
        db, event.id, viewer=event.assigned_coordinator
    ),
    "cancellation": lambda db, event: events_service.lock_own_event(
        db, event.id, actor=event.organiser
    ),
}


@pytest.mark.story("16.2", ac=7)
@pytest.mark.parametrize("lock", _EVENT_LOCKS.values(), ids=_EVENT_LOCKS.keys())
def test_every_lock_taken_before_a_type_leaves_a_notice_free_to_name_the_event(engine, lock):
    """A record holds the type, then its notice needs a key-share lock on the event. Each of these
    locks is taken before a type, so each has to be FOR NO KEY UPDATE, which a key share does not
    wait for. NOWAIT says so at once, with nothing left waiting."""
    with _committed_kit(engine, stock=3) as (kit_id, event_id):
        with Session(engine) as session:
            make_equipment_item(
                session,
                event=session.get(Event, event_id),
                equipment_type=session.get(EquipmentType, kit_id),
                quantity=1,
            )
            session.commit()
        with Session(engine) as holder, Session(engine) as notice:
            lock(holder, holder.get(Event, event_id))
            notice.execute(
                select(Event.id)
                .where(Event.id == event_id)
                .with_for_update(read=True, key_share=True, nowait=True)
            )


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


@pytest.mark.story("16.2", ac=3)
def test_an_edit_ending_a_record_this_moment_is_refused_and_a_moment_later_is_not(db: Session):
    """End is how a record stops now, so an edit's end has to come after this moment, not at it."""
    kit = make_equipment_type(db)
    actor = db.get(User, Users.TECH_SUPPORT.id)
    moment = _days(1)
    record = _out_at(
        db, kit, 1, starts_at=moment - timedelta(days=1), ends_at=moment + timedelta(days=1)
    )

    with pytest.raises(service.InvalidOutOfService) as refused:
        service.edit_out_of_service(
            db,
            kit.id,
            record.id,
            schemas.OutOfServiceUpdate(ends_at=moment),
            actor=actor,
            now=moment,
        )
    assert str(refused.value) == service.END_IN_THE_PAST_MESSAGE
    later = moment + timedelta(minutes=1)
    edited = service.edit_out_of_service(
        db, kit.id, record.id, schemas.OutOfServiceUpdate(ends_at=later), actor=actor, now=moment
    )
    assert edited.ends_at == later


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


# =============================================================================================
# AC10 / AC11 (fix f16.2.4) - an item short of every unit is closed; one short of some is kept
# =============================================================================================
HOLDING_STATUSES = ["REQUESTED", "PENDING", "ACCEPTED"]


def _item(db: Session, hold: EquipmentReservation) -> EventEquipmentRequest:
    """The item ``hold`` is for, read as it now stands."""
    item = db.get(EventEquipmentRequest, hold.equipment_request_id)
    db.refresh(item)
    return item


def _returned_notices(db: Session, event: Event) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification).where(
                Notification.event_id == event.id,
                Notification.notification_type == NotificationType.EVENT_RETURNED_TO_PLANNING,
            )
        )
    )


@pytest.mark.story("16.2", ac=10)
@pytest.mark.parametrize("status", HOLDING_STATUSES)
def test_a_record_taking_every_unit_an_item_holds_closes_it_whatever_its_stage(
    tech_client, db: Session, status: str
):
    kit = make_equipment_type(db, total_quantity=2)
    event = _event(db)
    hold = _held(db, event, kit, 2, status=status)

    response = tech_client.post(_records_path(kit.id), json=_body(2, start=10, end=12))

    assert response.status_code == 201
    item = _item(db, hold)
    assert (item.status, item.out_of_service_from) == ("OUT_OF_SERVICE", status)
    assert item.out_of_service_at is not None
    db.refresh(hold)
    assert (hold.status, hold.released_quantity) == ("RELEASED", 2)
    tech_client.login(Users.COORDINATOR)
    assert _shortages(tech_client, event) == []
    [line] = [
        each
        for each in tech_client.get(f"/events/{event.id}").json()["equipment"]
        if each["id"] == str(item.id)
    ]
    assert line["status"] == "OUT_OF_SERVICE"
    assert datetime.fromisoformat(line["out_of_service_at"]) == item.out_of_service_at


@pytest.mark.story("16.2", ac=11)
@pytest.mark.parametrize("status", HOLDING_STATUSES)
def test_an_item_left_short_of_all_but_one_unit_keeps_its_status_and_its_hold(
    tech_client, db: Session, status: str
):
    kit = make_equipment_type(db, total_quantity=3, name="Mobile kit")
    event = _event(db)
    hold = _held(db, event, kit, 3, status=status)

    tech_client.post(_records_path(kit.id), json=_body(2, start=10, end=12))

    item = _item(db, hold)
    assert (item.status, item.out_of_service_at, item.out_of_service_from) == (status, None, None)
    db.refresh(hold)
    assert hold.status == "RESERVED"
    [notice] = _short_notices(db, event)
    assert notice.message == service.short_message(name="Mobile kit", short=2, held=3)


@pytest.mark.story("16.2", ac=10)
def test_a_hold_whose_item_is_past_closing_is_reported_short_not_closed(tech_client, db: Session):
    """Only a not-yet-sent, Pending or Accepted item is closed. A declined, withdrawn or cancelled
    item releases its hold in the same step, so real data never leaves one holding units; the
    hold is placed on a declined item directly to prove the save leaves that item as it is and
    tells the coordinator the hold is short, as for any other hold it cannot close."""
    kit = make_equipment_type(db, total_quantity=2, name="Mobile kit")
    event = _event(db)
    hold = _held(db, event, kit, 2, status="DECLINED")

    response = tech_client.post(_records_path(kit.id), json=_body(2, start=10, end=12))

    assert response.status_code == 201
    item = _item(db, hold)
    assert (item.status, item.out_of_service_at, item.out_of_service_from) == (
        "DECLINED",
        None,
        None,
    )
    db.refresh(hold)
    assert hold.status == "RESERVED"
    [notice] = _short_notices(db, event)
    assert notice.message == service.short_message(name="Mobile kit", short=2, held=2)


@pytest.mark.story("16.2", ac=10)
def test_the_coordinator_is_told_the_item_was_closed_not_that_it_is_short(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=2, name="Mobile kit")
    event = _event(db, name="Harbour Lights")
    hold = _held(db, event, kit, 2)

    tech_client.post(_records_path(kit.id), json=_body(2, start=10, end=12))

    [notice] = _short_notices(db, event)
    assert notice.recipient_id == Users.COORDINATOR.id
    assert notice.title == "Equipment out of service: Harbour Lights"
    assert notice.message == (
        "Mobile kit: all 2 held for this event are out of service, so the item was closed and"
        " nothing is held for it. Request another type if you still need one."
    )
    assert (notice.related_entity_type, notice.related_entity_id) == (
        "equipment_reservation",
        hold.id,
    )


@pytest.mark.story("16.2", ac=10)
def test_closing_an_item_is_audited_on_its_event(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=1)
    event = _event(db)
    hold = _held(db, event, kit, 1, status="PENDING")

    record_id = tech_client.post(_records_path(kit.id), json=_body(1, start=10, end=12)).json()[
        "id"
    ]

    [entry] = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == event.id, AuditLog.action == "EQUIPMENT_OUT_OF_SERVICE"
        )
    ).all()
    assert entry.actor_id == Users.TECH_SUPPORT.id
    assert entry.details == {
        "item_id": str(hold.equipment_request_id),
        "equipment_type_code": kit.code,
        "quantity": 1,
        "from_status": "PENDING",
        "record_id": record_id,
    }


@pytest.mark.story("16.2", ac=10)
@pytest.mark.story("16.2", ac=11)
def test_only_the_hold_placed_last_is_closed_and_the_one_before_is_told_how_short_it_is(
    tech_client, db: Session
):
    """Four units, two holds of two, three taken out: the one unit left goes to the hold placed
    first, so the later one has none and is closed, and the earlier is one short. Closing the
    later hold gives nothing back over the record's period, so the earlier is told it is short by
    one, once."""
    kit = make_equipment_type(db, total_quantity=4, name="Mobile kit")
    earlier, later = _event(db), _event(db, coordinator=Users.COORDINATOR_2.id)
    earlier_hold = _held(db, earlier, kit, 2, placed_days_ago=9)
    later_hold = _held(db, later, kit, 2, placed_days_ago=1)

    tech_client.post(_records_path(kit.id), json=_body(3, start=10, end=12))

    assert _item(db, earlier_hold).status == "ACCEPTED"
    assert _item(db, later_hold).status == "OUT_OF_SERVICE"
    assert [notice.message for notice in _short_notices(db, earlier)] == [
        service.short_message(name="Mobile kit", short=1, held=2)
    ]
    assert [notice.title for notice in _short_notices(db, later)] == [
        f"Equipment out of service: {later.name}"
    ]


@pytest.mark.story("16.2", ac=10)
def test_an_edit_raising_a_record_to_every_unit_closes_the_item(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=3)
    hold = _held(db, _event(db), kit, 3)
    record = _out(db, kit, 1, start=10, end=12)  # leaves the hold 1 short

    response = tech_client.patch(_record_path(kit.id, record.id), json={"quantity": 3})

    assert response.status_code == 200
    assert _item(db, hold).status == "OUT_OF_SERVICE"


@pytest.mark.story("16.2", ac=10)
def test_an_item_already_short_that_a_record_leaves_no_shorter_is_not_closed(
    tech_client, db: Session
):
    """Only a save that leaves a hold short of every unit, or shorter than it was, closes it: one
    left so before this fix, by a record of another period, is marked as it was."""
    kit = make_equipment_type(db, total_quantity=1)
    hold = _held(db, _event(db), kit, 1)
    _out(db, kit, 1, start=10, end=12)  # on file before this fix: the hold is short of its unit

    tech_client.post(_records_path(kit.id), json=_body(1, start=30, end=31))

    assert _item(db, hold).status == "ACCEPTED"


@pytest.mark.story("16.2", ac=10)
def test_an_item_of_an_event_with_no_coordinator_is_closed_and_nobody_is_told(
    tech_client, db: Session
):
    kit = make_equipment_type(db, total_quantity=1)
    event = _event(db, coordinator=None)
    hold = _held(db, event, kit, 1, status="REQUESTED")

    tech_client.post(_records_path(kit.id), json=_body(1, start=10, end=12))

    assert _item(db, hold).status == "OUT_OF_SERVICE"
    assert _short_notices(db, event) == []


@pytest.mark.story("16.2", ac=10)
@pytest.mark.parametrize("event_status", [EventStatus.CONFIRMED, EventStatus.AWAITING_SAFETY_CHECK])
def test_an_accepted_item_closed_on_an_event_past_planning_sends_it_back_to_planning(
    tech_client, db: Session, event_status: str
):
    confirmed_at = _now() - timedelta(days=1) if event_status == EventStatus.CONFIRMED else None
    kit = make_equipment_type(db, total_quantity=2, name="Mobile kit")
    event = _event(db, status=event_status, confirmed_at=confirmed_at, name="Harbour Lights")
    _held(db, event, kit, 2)

    tech_client.post(_records_path(kit.id), json=_body(2, start=10, end=12))

    db.refresh(event)
    assert (event.status, event.confirmed_at) == (EventStatus.PLANNING, None)
    told = _returned_notices(db, event)
    assert {notice.recipient_id for notice in told} == {
        Users.ORGANISER.id,
        Users.SAFETY_OFFICER.id,
    }
    assert {notice.message for notice in told} == {
        'Mobile kit on "Harbour Lights" went out of service, so the event is back in Planning and'
        " needs a new safety check before it is confirmed again."
    }


@pytest.mark.story("16.2", ac=10)
@pytest.mark.parametrize("status", ["REQUESTED", "PENDING"])
def test_an_item_never_accepted_closed_on_a_confirmed_event_leaves_it_confirmed(
    tech_client, db: Session, status: str
):
    """The safety check reads accepted items only (21.2), so only losing one undoes it."""
    confirmed_at = (_now() - timedelta(days=1)).replace(microsecond=0)
    kit = make_equipment_type(db, total_quantity=1)
    event = _event(db, status=EventStatus.CONFIRMED, confirmed_at=confirmed_at)
    hold = _held(db, event, kit, 1, status=status)

    tech_client.post(_records_path(kit.id), json=_body(1, start=10, end=12))

    assert _item(db, hold).status == "OUT_OF_SERVICE"
    db.refresh(event)
    assert (event.status, event.confirmed_at) == (EventStatus.CONFIRMED, confirmed_at)
    assert _returned_notices(db, event) == []


@pytest.mark.story("16.2", ac=10)
def test_an_accepted_item_closed_on_an_event_in_planning_leaves_it_there(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=1)
    event = _event(db)
    hold = _held(db, event, kit, 1)

    tech_client.post(_records_path(kit.id), json=_body(1, start=10, end=12))

    assert _item(db, hold).status == "OUT_OF_SERVICE"
    db.refresh(event)
    assert event.status == EventStatus.PLANNING
    assert _returned_notices(db, event) == []


@pytest.mark.story("16.2", ac=10)
@pytest.mark.parametrize("undo", ["removed", "ended", "eased"])
def test_a_closed_item_stays_closed_once_the_record_is_removed_ended_or_eased(
    tech_client, db: Session, undo: str
):
    kit = make_equipment_type(db, total_quantity=2)
    event = _event(db, start=0.5, end=1)
    hold = _held(db, event, kit, 2)
    if undo == "removed":  # a record not yet started, which is removed
        record_id = tech_client.post(_records_path(kit.id), json=_body(2, start=0.25, end=None))
    else:  # a record in force from this minute, which is ended or eased
        body = _body(2, start=0, end=None) | {"starts_at": _now().replace(second=0).isoformat()}
        record_id = tech_client.post(_records_path(kit.id), json=body)
    assert record_id.status_code == 201, record_id.text
    path = _record_path(kit.id, uuid.UUID(record_id.json()["id"]))

    response = {
        "removed": lambda: tech_client.delete(path),
        "ended": lambda: tech_client.patch(path, json={"end_now": True}),
        "eased": lambda: tech_client.patch(path, json={"quantity": 1}),
    }[undo]()

    assert response.status_code in (200, 204), response.text
    assert _item(db, hold).status == "OUT_OF_SERVICE"
    db.refresh(hold)
    assert hold.status == "RELEASED"


@pytest.mark.story("16.2", ac=10)
def test_a_closed_item_no_longer_takes_up_its_type_so_it_can_be_requested_again(
    tech_client, db: Session
):
    kit = make_equipment_type(db, total_quantity=2)
    event = _event(db)
    _held(db, event, kit, 2)
    record_id = tech_client.post(_records_path(kit.id), json=_body(2, start=10, end=12)).json()[
        "id"
    ]
    tech_client.delete(_record_path(kit.id, uuid.UUID(record_id)))  # the units are back

    tech_client.login(Users.COORDINATOR)
    response = tech_client.post(
        f"/events/{event.id}/equipment", json={"equipment_type_code": kit.code, "quantity": 2}
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "REQUESTED"


@pytest.mark.story("16.2", ac=10)
@pytest.mark.parametrize("status", ["PENDING", "ACCEPTED"])
def test_a_closed_item_can_no_longer_be_withdrawn_decided_or_edited(
    tech_client, db: Session, status: str
):
    kit = make_equipment_type(db, total_quantity=2)
    event = _event(db)
    hold = _held(db, event, kit, 2, status=status)
    tech_client.post(_records_path(kit.id), json=_body(2, start=10, end=12))
    item_id = hold.equipment_request_id

    decided = tech_client.post(
        f"/equipment-requests/{item_id}/decision", json={"outcome": "ACCEPTED"}
    )
    tech_client.login(Users.COORDINATOR)
    withdrawn = tech_client.post(
        f"/events/{event.id}/equipment/{item_id}/withdrawal", json={"expected_status": status}
    )
    edited = tech_client.patch(f"/events/{event.id}/equipment/{item_id}", json={"quantity": 1})

    assert (decided.status_code, decided.json()["detail"]) == (
        409,
        "This equipment request was closed, as its units are out of service.",
    )
    assert (withdrawn.status_code, withdrawn.json()["detail"]) == (
        409,
        "This equipment item was closed, as its units are out of service, so there is nothing"
        " to withdraw.",
    )
    assert (edited.status_code, edited.json()["detail"]) == (
        409,
        "This equipment item is out of service, so it can no longer be changed.",
    )
    assert _item(db, hold).status == "OUT_OF_SERVICE"


# --- AC10 - the save takes the events holding the type before the type -------------------------
@pytest.mark.story("16.2", ac=10)
def test_a_record_waits_for_a_write_to_an_event_holding_the_type_then_closes_its_item(engine):
    """Closing an item writes to its event's equipment, so the save takes the event first, as the
    coordinator's writes and a decision do (event, then type), and waits for one under way. Taking
    the type first would leave it waiting on the event while the write waited on the type: here
    the write takes the type while the save waits, which a save holding the type would deadlock."""
    with _committed_kit(engine, stock=2) as (kit_id, event_id):
        with Session(engine) as session:
            item_id = make_equipment_item(
                session,
                event=session.get(Event, event_id),
                equipment_type=session.get(EquipmentType, kit_id),
                quantity=2,
                status="PENDING",
            ).id
            session.commit()
        holder = Session(engine)
        pids: queue.Queue[int] = queue.Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                coordinator = holder.get(User, Users.COORDINATOR.id)
                service._event_for_change(holder, event_id, actor=coordinator)
                saving = pool.submit(_in_own_session, engine, _recorder(kit_id, 2), pids)
                assert _waited_on_a_lock(engine, saving, pids)
                holder.execute(
                    select(EquipmentType.id)
                    .where(EquipmentType.id == kit_id)
                    .with_for_update(nowait=True)
                )
            finally:
                holder.close()  # inside the pool: leaving it waits for whatever this holds up
            assert saving.result(timeout=20) == CREATED

        with Session(engine) as session:
            assert session.get(EventEquipmentRequest, item_id).status == "OUT_OF_SERVICE"


# =============================================================================================
# AC12 (fix f16.2.4) - Technical Support sees which holds a save closes, and the closed items
# =============================================================================================
@pytest.mark.story("16.2", ac=12)
def test_the_check_says_which_holds_saving_would_close(tech_client, db: Session):
    kit = make_equipment_type(db, total_quantity=3)
    _held(db, _event(db), kit, 3)

    some = _check(tech_client, kit.id, quantity=2, starts_at=_days(10), ends_at=_days(12))
    every = _check(tech_client, kit.id, quantity=3, starts_at=_days(10), ends_at=_days(12))

    [short] = some.json()["short_holds"]
    assert (short["units_short"], short["closes"]) == (2, False)
    [closing] = every.json()["short_holds"]
    assert (closing["units_short"], closing["closes"]) == (3, True)


def _closed(db: Session, event: Event, kit: EquipmentType, *, was: str) -> EventEquipmentRequest:
    """An item closed as Out of service from ``was``, sent to Technical Support unless it was
    never sent."""
    sent = (
        {}
        if was == "REQUESTED"
        else {"submitted_at": _now() - timedelta(days=2), "submitted_by_id": Users.COORDINATOR.id}
    )
    return make_equipment_item(
        db,
        event=event,
        equipment_type=kit,
        quantity=1,
        status="OUT_OF_SERVICE",
        is_held=False,
        out_of_service_from=was,
        **sent,
    )


@pytest.mark.story("16.2", ac=12)
def test_the_queue_lists_items_closed_after_they_were_sent_under_out_of_service(
    tech_client, db: Session
):
    event = _event(db, name="Out of service fair")
    pending = _closed(db, event, make_equipment_type(db), was="PENDING")
    accepted = _closed(db, event, make_equipment_type(db), was="ACCEPTED")
    never_sent = _closed(db, event, make_equipment_type(db), was="REQUESTED")

    response = tech_client.get(
        "/equipment-requests", params={"status": "OUT_OF_SERVICE", "search": "Out of service fair"}
    )

    assert response.status_code == 200
    body = response.json()
    listed = {entry["id"]: entry for entry in body["items"]}
    assert set(listed) == {str(pending.id), str(accepted.id)}
    assert str(never_sent.id) not in listed
    entry = listed[str(pending.id)]
    assert (entry["status"], entry["available"], entry["shortfall"]) == (
        "OUT_OF_SERVICE",
        None,
        None,
    )
    assert datetime.fromisoformat(entry["out_of_service_at"]) == pending.out_of_service_at
    assert body["counts"]["out_of_service"] == 2
    every_tab = tech_client.get("/equipment-requests", params={"search": "Out of service fair"})
    assert {each["id"] for each in every_tab.json()["items"]} == set(listed)


@pytest.mark.story("16.2", ac=12)
def test_a_closed_request_opens_on_its_own_page_with_no_figures(tech_client, db: Session):
    item = _closed(db, _event(db), make_equipment_type(db), was="ACCEPTED")

    response = tech_client.get(f"/equipment-requests/{item.id}")

    assert response.status_code == 200
    assert (response.json()["status"], response.json()["available"]) == ("OUT_OF_SERVICE", None)


# =============================================================================================
# AC13 (fix f16.2.4) - who reads an event's shortages: its coordinator, the Leads and Technical
# Support
# =============================================================================================
@pytest.mark.story("16.2", ac=13)
@pytest.mark.parametrize(
    ("user", "expected"),
    [
        pytest.param(Users.COORDINATOR, 200, id="its-coordinator"),
        pytest.param(Users.LEAD, 200, id="lead"),
        pytest.param(Users.TECH_SUPPORT, 200, id="technical-support"),
        pytest.param(Users.COORDINATOR_2, 403, id="another-coordinator"),
        pytest.param(Users.VENUE_STAFF, 403, id="venue-staff"),
        pytest.param(Users.SAFETY_OFFICER, 403, id="safety-officer"),
    ],
)
def test_an_events_shortages_are_read_only_by_its_coordinator_the_leads_and_technical_support(
    login_as, db: Session, user, expected: int
):
    kit = make_equipment_type(db, total_quantity=2)
    event = _event(db)
    _held(db, event, kit, 2)
    _out(db, kit, 1, start=10, end=12)

    response = login_as(user).get(f"/events/{event.id}/equipment-shortages")

    assert response.status_code == expected, response.text
    if expected == 200:
        assert [each["units_short"] for each in response.json()] == [1]
    else:
        assert response.json()["detail"] == service.SHORTAGES_NOT_YOURS_MESSAGE


@pytest.mark.story("16.2", ac=13)
def test_an_event_with_no_coordinator_has_its_shortages_read_by_the_leads_and_technical_support(
    login_as, db: Session
):
    event = _event(db, coordinator=None)

    path = f"/events/{event.id}/equipment-shortages"

    assert login_as(Users.LEAD).get(path).status_code == 200
    assert login_as(Users.TECH_SUPPORT).get(path).status_code == 200
    assert login_as(Users.COORDINATOR).get(path).status_code == 403
