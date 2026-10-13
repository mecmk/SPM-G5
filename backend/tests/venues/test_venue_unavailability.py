"""Story 9.4: mark a venue temporarily unavailable.

Slice 1 (migration 020): the reasons a period can carry.

AC1  Venue Staff mark a venue unavailable from a start to an end with a reason: Maintenance,
     Equipment failure, Renovation, Safety concern or Other (a description is required for
     Other). It shows on the venue's calendar and is excluded from venue searches.

The table's own rules are what this slice proves: the CHECK constraints refuse a reason outside
the five and an Other without a description, migration 020 moves existing rows onto the new set,
and the calendar and the booking request name each reason. The add, edit and end endpoints are
slice 2's and are tested when they exist.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.events.models import EventStatus
from tests.support.factories import make_event, make_unavailability, make_venue
from tests.support.seed import Users

SGT = timezone(timedelta(hours=8))
MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"

REASON_CONSTRAINT = "ck_venue_unavailability_reason"
DESCRIPTION_CONSTRAINT = "ck_venue_unavailability_other_description"

# The table as it stood before migration 020: INTERNAL_USE allowed, no EQUIPMENT_FAILURE, and an
# Other that needs no description. IF EXISTS keeps this valid on a database 020 has not reached.
PRE_020_SCHEMA = (
    f"ALTER TABLE venue_unavailability_periods DROP CONSTRAINT IF EXISTS {DESCRIPTION_CONSTRAINT};"
    f" ALTER TABLE venue_unavailability_periods DROP CONSTRAINT {REASON_CONSTRAINT};"
    f" ALTER TABLE venue_unavailability_periods ADD CONSTRAINT {REASON_CONSTRAINT} CHECK"
    " (reason IN ('MAINTENANCE', 'RENOVATION', 'SAFETY', 'INTERNAL_USE', 'OTHER'));"
)

# Story 9.4 AC1: the five reasons, as the database stores them.
REASONS = ["MAINTENANCE", "EQUIPMENT_FAILURE", "RENOVATION", "SAFETY", "OTHER"]
# What the calendar calls a period when it has no description of its own.
REASON_NAMES = {
    "MAINTENANCE": "Maintenance",
    "EQUIPMENT_FAILURE": "Equipment failure",
    "RENOVATION": "Renovation",
    "SAFETY": "Safety concern",
}


def _at(day: int, hour: int = 0) -> datetime:
    """A Singapore-time moment in March 2027, a month no seed row touches."""
    return datetime(2027, 3, day, hour, tzinfo=SGT)


def _insert(
    db: Session, venue_id: uuid.UUID, reason: str, notes: str | None, day: int
) -> uuid.UUID:
    """A period written in SQL, so it is stored exactly as given, whatever the models say."""
    return db.execute(
        text(
            "INSERT INTO venue_unavailability_periods (venue_id, starts_at, ends_at, reason, notes)"
            " VALUES (:venue_id, :starts_at, :ends_at, :reason, :notes) RETURNING id"
        ),
        {
            "venue_id": venue_id,
            "starts_at": _at(day),
            "ends_at": _at(day + 1),
            "reason": reason,
            "notes": notes,
        },
    ).scalar_one()


def _refused(db: Session, reason: str, notes: str | None) -> IntegrityError | None:
    """The database's refusal of a period with ``reason`` and ``notes``, or None if it took it."""
    venue = make_venue(db)
    try:
        with db.begin_nested():
            _insert(db, venue.id, reason, notes, day=1)
    except IntegrityError as exc:
        return exc
    return None


@pytest.mark.story("9.4", ac=1)
@pytest.mark.parametrize("notes", [None, "Gym floor relaid"])
def test_internal_use_is_no_longer_a_reason(db, notes):
    """The five reasons are AC1's: a code outside them is refused by the table itself."""
    refusal = _refused(db, "INTERNAL_USE", notes)

    assert refusal is not None, "INTERNAL_USE was accepted"
    assert REASON_CONSTRAINT in str(refusal.orig)


@pytest.mark.story("9.4", ac=1)
@pytest.mark.parametrize("notes", [None, "", "   ", "\t\n"])
def test_other_needs_a_description_in_the_table_itself(db, notes):
    """AC1: Other without a description is refused whatever wrote it. A description makes it
    valid, and every other reason may go without one."""
    refusal = _refused(db, "OTHER", notes)

    assert refusal is not None, f"OTHER with notes {notes!r} was accepted"
    assert DESCRIPTION_CONSTRAINT in str(refusal.orig)
    assert _refused(db, "OTHER", "Gala stage being built") is None
    assert _refused(db, "MAINTENANCE", None) is None


@pytest.mark.story("9.4", ac=1)
def test_migration_020_moves_existing_periods_onto_the_five_reasons(db):
    """Run on pre-020 rows inside the test's transaction, which is rolled back: Internal use
    becomes Other, saying so and keeping what was written; an Other with nothing written gets a
    description; everything else is left as it was. Afterwards the table refuses what AC1
    refuses."""
    migration = next(MIGRATIONS.glob("020_*.sql"), None)
    assert migration is not None, "migration 020 has not been written"
    conn = db.connection()
    conn.exec_driver_sql(PRE_020_SCHEMA)
    venue = make_venue(db)
    internal_bare = _insert(db, venue.id, "INTERNAL_USE", None, day=1)
    internal_noted = _insert(db, venue.id, "INTERNAL_USE", "Gym floor relaid", day=2)
    other_null = _insert(db, venue.id, "OTHER", None, day=3)
    other_blank = _insert(db, venue.id, "OTHER", "   ", day=4)
    other_described = _insert(db, venue.id, "OTHER", "Gala stage being built", day=5)
    maintenance = _insert(db, venue.id, "MAINTENANCE", None, day=6)

    conn.exec_driver_sql(migration.read_text(encoding="utf-8"))

    def stored(period_id: uuid.UUID) -> tuple[str, str | None]:
        return tuple(
            db.execute(
                text("SELECT reason, notes FROM venue_unavailability_periods WHERE id = :id"),
                {"id": period_id},
            ).one()
        )

    assert stored(internal_bare) == ("OTHER", "Internal use")
    assert stored(internal_noted) == ("OTHER", "Internal use - Gym floor relaid")
    assert stored(other_null) == ("OTHER", "No description recorded.")
    assert stored(other_blank) == ("OTHER", "No description recorded.")
    assert stored(other_described) == ("OTHER", "Gala stage being built")
    assert stored(maintenance) == ("MAINTENANCE", None)
    refusal = _refused(db, "INTERNAL_USE", "x")
    assert refusal is not None and REASON_CONSTRAINT in str(refusal.orig)
    refusal = _refused(db, "OTHER", None)
    assert refusal is not None and DESCRIPTION_CONSTRAINT in str(refusal.orig)


@pytest.mark.story("9.4", ac=1)
def test_the_calendar_names_each_reason(db, venue_staff_client):
    """AC1: a period shows with its reason, and Equipment failure is one of them. Safety is the
    code SAFETY, named Safety concern. A description, where given, is what the entry reads."""
    venue = make_venue(db)
    for day, reason in enumerate(REASON_NAMES, start=1):
        make_unavailability(
            db, venue_id=venue.id, starts_at=_at(day), ends_at=_at(day + 1), reason=reason
        )
    make_unavailability(
        db,
        venue_id=venue.id,
        starts_at=_at(10),
        ends_at=_at(11),
        reason="OTHER",
        notes="Gala stage being built",
    )

    response = venue_staff_client.get(
        f"/venues/{venue.id}/calendar",
        params={"starts_at": _at(1).isoformat(), "ends_at": _at(28).isoformat()},
    )

    assert response.status_code == 200, response.text
    labels = {window["reason"]: window["label"] for window in response.json()}
    assert labels == {**REASON_NAMES, "OTHER": "Gala stage being built"}


@pytest.mark.story("9.4", ac=1)
def test_a_venue_closed_for_equipment_failure_cannot_be_requested(db, coordinator_client):
    """12.1 AC14 for the new reason: the refusal says why the venue is closed."""
    venue = make_venue(db)
    make_unavailability(
        db,
        venue_id=venue.id,
        starts_at=_at(4),
        ends_at=_at(6),
        reason="EQUIPMENT_FAILURE",
    )
    event = make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=_at(5, 10),
        ends_at=_at(5, 12),
    )

    response = coordinator_client.post(
        "/bookings", json={"event_id": str(event.id), "venue_id": str(venue.id)}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        f"{venue.name} is closed for equipment failure from Thu 4 Mar 2027, 00:00 to "
        "Sat 6 Mar 2027, 00:00."
    )
