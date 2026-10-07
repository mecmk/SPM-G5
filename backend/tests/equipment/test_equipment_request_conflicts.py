"""Story 15.1 AC10 - two people, or two clicks, at the same moment.

AC10 If two coordinators try to hold the last units at the same moment, only the first succeeds.
     The second is refused with the updated available figure. A double-click on Save or Submit
     acts once.

The sequential case runs through the API in the usual rolled-back transaction. The races need
real concurrent transactions, so they call the service from two threads with their own sessions,
commit, and clean up after themselves (as tests/bookings/test_venue_hold.py does). Two holds for
one type are serialised by a row lock on the equipment type, as 2.1's submission hold already is;
two writes to one event's equipment are serialised by a row lock on the event.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select
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
from tests.support.factories import make_equipment_item, make_equipment_type, make_event
from tests.support.seed import Users

SGT = timezone(timedelta(hours=8))
START = datetime(2027, 8, 2, 9, 0, tzinfo=SGT)
END = datetime(2027, 8, 2, 17, 0, tzinfo=SGT)
CREATED = "created"


def _event(db: Session, coordinator: uuid.UUID = Users.COORDINATOR.id) -> Event:
    return make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=coordinator,
        starts_at=START,
        ends_at=END,
    )


@pytest.mark.story("15.1", ac=10)
def test_the_second_coordinator_is_refused_once_the_first_holds_the_last_units(
    login_as, db: Session
):
    chloes, carls = _event(db), _event(db, Users.COORDINATOR_2.id)
    kit = make_equipment_type(db, total_quantity=3, name="Laser projector")

    first = login_as(Users.COORDINATOR).post(
        f"/events/{chloes.id}/equipment", json={"equipment_type_code": kit.code, "quantity": 3}
    )
    carl = login_as(Users.COORDINATOR_2)
    second = carl.post(
        f"/events/{carls.id}/equipment", json={"equipment_type_code": kit.code, "quantity": 1}
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 409
    assert second.json()["detail"] == service.NOT_ENOUGH_AVAILABLE_MESSAGE.format(
        name="Laser projector"
    )
    figures = carl.get(f"/events/{carls.id}/equipment-availability").json()
    assert {row["equipment_type_code"]: row["available"] for row in figures}[kit.code] == 0


# --- real races ----------------------------------------------------------------------------------
@contextmanager
def _committed_events(engine, *coordinators: uuid.UUID) -> Iterator[tuple[list, uuid.UUID]]:
    """Events and a fresh three-unit type, committed so other connections see them, then removed
    with everything the race wrote."""
    with Session(engine) as session:
        kit = make_equipment_type(
            session, total_quantity=3, name=f"Race kit {uuid.uuid4().hex[:8]}"
        )
        events = [_event(session, coordinator) for coordinator in coordinators]
        session.commit()
        event_ids, kit_id = [event.id for event in events], kit.id
    try:
        yield event_ids, kit_id
    finally:
        with Session(engine) as session:
            session.execute(delete(AuditLog).where(AuditLog.entity_id.in_(event_ids)))
            session.execute(
                delete(EquipmentReservation).where(EquipmentReservation.event_id.in_(event_ids))
            )
            session.execute(
                delete(EventEquipmentRequest).where(EventEquipmentRequest.event_id.in_(event_ids))
            )
            session.execute(delete(Event).where(Event.id.in_(event_ids)))
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


def _adder(event_id: uuid.UUID, code: str, quantity: int, coordinator: uuid.UUID):
    def attempt(session: Session) -> str:
        actor = session.get(User, coordinator)
        item = schemas.EquipmentItemIn(equipment_type_code=code, quantity=quantity)
        try:
            service.add_equipment_item(session, event_id, item, actor=actor)
        except service.EquipmentNotAvailable as refusal:
            return str(refusal)
        except service.TypeAlreadyRequested as refusal:
            return str(refusal)
        return CREATED

    return attempt


def _submitter(event_id: uuid.UUID):
    def attempt(session: Session) -> str:
        actor = session.get(User, Users.COORDINATOR.id)
        try:
            service.submit_equipment(session, event_id, actor=actor)
        except service.NothingToSubmit as refusal:
            return str(refusal)
        return "sent"

    return attempt


@pytest.mark.story("15.1", ac=10)
def test_two_coordinators_racing_for_the_last_units_only_the_first_succeeds(engine):
    coordinators = (Users.COORDINATOR.id, Users.COORDINATOR_2.id)
    with _committed_events(engine, *coordinators) as (event_ids, kit_id):
        with Session(engine) as session:
            kit = session.get(EquipmentType, kit_id)
            code, name = kit.code, kit.name

        outcomes = _race(
            engine,
            [_adder(event_id, code, 3, who) for event_id, who in zip(event_ids, coordinators)],
        )

        assert sorted(outcomes) == sorted(
            [CREATED, service.NOT_ENOUGH_AVAILABLE_MESSAGE.format(name=name)]
        )
        with Session(engine) as session:
            holds = session.scalars(
                select(EquipmentReservation).where(EquipmentReservation.equipment_type_id == kit_id)
            ).all()
            assert [hold.quantity for hold in holds] == [3]


@pytest.mark.story("15.1", ac=10)
def test_a_double_click_on_save_adds_the_item_once(engine):
    with _committed_events(engine, Users.COORDINATOR.id) as ([event_id], kit_id):
        with Session(engine) as session:
            kit = session.get(EquipmentType, kit_id)
            code, name = kit.code, kit.name

        outcomes = _race(engine, [_adder(event_id, code, 1, Users.COORDINATOR.id)] * 2)

        assert sorted(outcomes) == sorted(
            [CREATED, service.TYPE_ALREADY_REQUESTED_MESSAGE.format(name=name)]
        )
        with Session(engine) as session:
            items = session.scalars(
                select(EventEquipmentRequest).where(EventEquipmentRequest.event_id == event_id)
            ).all()
            assert len(items) == 1


@pytest.mark.story("15.1", ac=10)
def test_a_double_click_on_submit_sends_once(engine):
    with _committed_events(engine, Users.COORDINATOR.id) as ([event_id], kit_id):
        with Session(engine) as session:
            event = session.get(Event, event_id)
            make_equipment_item(
                session, event=event, equipment_type=session.get(EquipmentType, kit_id), quantity=1
            )
            session.commit()

        outcomes = _race(engine, [_submitter(event_id)] * 2)

        assert sorted(outcomes) == sorted(["sent", service.NOTHING_TO_SUBMIT_MESSAGE])
        with Session(engine) as session:
            submissions = session.scalars(
                select(AuditLog).where(
                    AuditLog.entity_id == event_id, AuditLog.action == "EQUIPMENT_SUBMITTED"
                )
            ).all()
            assert len(submissions) == 1
