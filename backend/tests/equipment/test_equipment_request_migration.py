"""Story 15.1 - migration 014 and the item statuses the database allows (regression).

Before this story an equipment line on a submitted request was marked RESERVED the moment 2.1
held it, and the schema allowed statuses no code ever wrote. Story 15.1 separates "held but not yet
sent" (REQUESTED) from "sent, awaiting Technical Support" (PENDING) and adds who sent an item and
when (AC1). Migration 014 moves existing rows across; these tests run it on pre-014 rows inside
the test's transaction, which is rolled back, as tests/bookings/test_venue_hold.py does for 010.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from psycopg.errors import CheckViolation
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.events.models import EquipmentRequestStatus, EventStatus
from tests.support.factories import make_equipment_type, make_event

MIGRATION_014 = (
    Path(__file__).resolve().parents[2] / "db" / "migrations" / "014_equipment_requests.sql"
)
PRE_014_STATUSES = (
    "REQUESTED",
    "UNDER_REVIEW",
    "RESERVED",
    "PARTIALLY_RESERVED",
    "UNAVAILABLE",
    "CANCELLED",
)
STATUSES_AFTER_014 = {
    "REQUESTED": "REQUESTED",
    "RESERVED": "REQUESTED",
    "UNDER_REVIEW": "PENDING",
    "PARTIALLY_RESERVED": "PENDING",
    "UNAVAILABLE": "UNAVAILABLE",
    "CANCELLED": "CANCELLED",
}


def _insert_line(db: Session, *, event_id: uuid.UUID, type_id: uuid.UUID, status: str) -> uuid.UUID:
    line_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO event_equipment_requests"
            " (id, event_id, equipment_type_id, quantity, status)"
            " VALUES (:id, :event_id, :type_id, 1, :status)"
        ),
        {"id": line_id, "event_id": event_id, "type_id": type_id, "status": status},
    )
    return line_id


@pytest.mark.story("15.1", ac=1)
@pytest.mark.story("15.1", ac=2)
def test_migration_014_moves_existing_lines_to_the_new_statuses(db: Session):
    event = make_event(db, status=EventStatus.UNDER_REVIEW)
    conn = db.connection()
    conn.exec_driver_sql(
        "ALTER TABLE event_equipment_requests DROP CONSTRAINT ck_event_equipment_requests_status"
    )
    conn.exec_driver_sql(
        "ALTER TABLE event_equipment_requests DROP COLUMN submitted_by_id, DROP COLUMN submitted_at"
    )
    # The seed's PENDING items stand for lines pre-014 code would have left UNDER_REVIEW. Its
    # ACCEPTED and DECLINED items (story 15.2's e2e rows) are Technical Support's decisions, which
    # pre-014 rows could not hold, so they go.
    conn.exec_driver_sql(
        "UPDATE event_equipment_requests SET status = 'UNDER_REVIEW' WHERE status = 'PENDING'"
    )
    conn.exec_driver_sql(
        "DELETE FROM event_equipment_requests WHERE status IN ('ACCEPTED', 'DECLINED')"
    )
    conn.exec_driver_sql(
        "ALTER TABLE event_equipment_requests ADD CONSTRAINT ck_event_equipment_requests_status"
        f" CHECK (status IN ({', '.join(repr(s) for s in PRE_014_STATUSES)}))"
    )
    lines = {
        status: _insert_line(
            db, event_id=event.id, type_id=make_equipment_type(db).id, status=status
        )
        for status in PRE_014_STATUSES
    }

    conn.exec_driver_sql(MIGRATION_014.read_text(encoding="utf-8"))

    after = dict(
        db.execute(
            text("SELECT id, status FROM event_equipment_requests WHERE event_id = :id"),
            {"id": event.id},
        ).all()
    )
    assert {status: after[line_id] for status, line_id in lines.items()} == STATUSES_AFTER_014
    sent = db.execute(
        text(
            "SELECT count(*) FROM event_equipment_requests"
            " WHERE event_id = :id AND (submitted_by_id IS NOT NULL OR submitted_at IS NOT NULL)"
        ),
        {"id": event.id},
    ).scalar_one()
    assert sent == 0


@pytest.mark.story("15.1", ac=1)
@pytest.mark.parametrize("status", ["RESERVED", "UNDER_REVIEW", "PARTIALLY_RESERVED", "SENT"])
def test_the_database_refuses_a_status_this_story_retired(db: Session, status):
    event = make_event(db, status=EventStatus.UNDER_REVIEW)

    with pytest.raises(IntegrityError) as excinfo:
        with db.begin_nested():
            _insert_line(db, event_id=event.id, type_id=make_equipment_type(db).id, status=status)

    assert isinstance(excinfo.value.orig, CheckViolation)


@pytest.mark.story("15.1", ac=1)
def test_the_database_allows_every_status_the_application_uses(db: Session):
    event = make_event(db, status=EventStatus.UNDER_REVIEW)
    statuses = [
        value
        for name, value in vars(EquipmentRequestStatus).items()
        if name.isupper() and isinstance(value, str)
    ]

    for status in statuses:
        _insert_line(db, event_id=event.id, type_id=make_equipment_type(db).id, status=status)

    assert sorted(statuses) == sorted(
        ["REQUESTED", "PENDING", "ACCEPTED", "DECLINED", "UNAVAILABLE", "CANCELLED"]
    )
