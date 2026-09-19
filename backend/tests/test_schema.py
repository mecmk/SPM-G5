"""Story 1 - chore: set up database schema.

AC1 Schema covers users, events, venues, bookings, equipment.
AC2 Foreign key constraints defined.
AC3 Schema can be populated with sample data without integrity errors.

Plus guard-rails that keep the ORM models, the seed constants and the SQL in step.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

import app.auth.models  # noqa: F401  (register models on Base.metadata)
import app.common.audit  # noqa: F401
import app.venues.models  # noqa: F401
from app.db import Base
from app.dbtool import migrate
from tests.support.seed import Events, Users, Venues

CORE_TABLES = {
    "users": "users",
    "events": "events",
    "venues": "venues",
    "bookings": "venue_bookings",
    "equipment": "equipment_types",
}

# *_id columns that intentionally have no FK (polymorphic references).
POLYMORPHIC_ID_COLUMNS = {("notifications", "related_entity_id"), ("audit_log", "entity_id")}


@pytest.mark.story("1", ac=1)
def test_schema_covers_core_entities(engine):
    """AC1: the tables for users, events, venues, bookings and equipment all exist."""
    tables = set(inspect(engine).get_table_names())
    missing = {label: name for label, name in CORE_TABLES.items() if name not in tables}
    assert not missing, f"missing tables: {missing}"


@pytest.mark.story("1", ac=2)
@pytest.mark.parametrize(
    ("table", "column", "referenced_table"),
    [
        ("users", "role_code", "roles"),
        ("events", "organiser_id", "users"),
        ("events", "assigned_coordinator_id", "users"),
        ("venue_bookings", "event_id", "events"),
        ("venue_bookings", "venue_id", "venues"),
        ("event_equipment_requests", "equipment_type_id", "equipment_types"),
        ("equipment_reservations", "event_id", "events"),
        ("event_registrations", "attendee_id", "users"),
    ],
)
def test_key_foreign_keys_are_defined(engine, table, column, referenced_table):
    """AC2: the relationships that hold the domain together are real FK constraints."""
    fks = inspect(engine).get_foreign_keys(table)
    assert any(
        fk["constrained_columns"] == [column] and fk["referred_table"] == referenced_table
        for fk in fks
    ), f"{table}.{column} -> {referenced_table} is not a foreign key"


@pytest.mark.story("1", ac=2)
def test_every_id_column_is_a_foreign_key(engine):
    """AC2 (discipline): every *_id column must be a FK unless listed as polymorphic."""
    inspector = inspect(engine)
    offenders = []
    for table in inspector.get_table_names():
        fk_columns = {
            c for fk in inspector.get_foreign_keys(table) for c in fk["constrained_columns"]
        }
        for col in inspector.get_columns(table):
            name = col["name"]
            if name.endswith("_id") and name not in fk_columns:
                if (table, name) not in POLYMORPHIC_ID_COLUMNS:
                    offenders.append(f"{table}.{name}")
    assert not offenders, f"*_id columns without a foreign key: {offenders}"


@pytest.mark.story("1", ac=3)
def test_seed_loads_into_empty_schema_without_integrity_errors(db: Session):
    """AC3: truncate everything, then load reference + sample data from scratch."""
    conn = db.connection()
    tables = [
        r[0]
        for r in conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND tablename <> 'schema_migrations'"
            )
        )
    ]
    conn.exec_driver_sql("TRUNCATE " + ", ".join(tables) + " CASCADE")
    for seed_file in migrate.list_seeds():
        conn.exec_driver_sql(seed_file.read())  # raises on any integrity error
    counts = {
        t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in CORE_TABLES.values()
    }
    assert all(n > 0 for n in counts.values()), counts


@pytest.mark.story("1", ac=3)
def test_seed_is_idempotent_over_existing_data(db: Session):
    """AC3: re-running the seed on an already-seeded database neither fails nor duplicates rows."""
    conn = db.connection()
    before = conn.execute(text("SELECT count(*) FROM users")).scalar()
    for seed_file in migrate.list_seeds():
        conn.exec_driver_sql(seed_file.read())
    after = conn.execute(text("SELECT count(*) FROM users")).scalar()
    assert before == after


@pytest.mark.story("1")
def test_seed_constants_match_database(db: Session):
    """tests/support/seed.py must describe rows that really exist."""
    for user in Users.ALL_ACTIVE + (Users.INACTIVE,):
        row = db.execute(
            text("SELECT email, role_code FROM users WHERE id = :id"), {"id": user.id}
        ).one_or_none()
        assert row is not None, f"seed user {user.email} missing"
        assert (row.email, row.role_code) == (user.email, user.role)
    for venue_id in (Venues.GRAND_HALL, Venues.SEMINAR_ROOM, Venues.BOARDROOM, Venues.OLD_ANNEX):
        assert db.execute(text("SELECT 1 FROM venues WHERE id = :id"), {"id": venue_id}).scalar()
    for event_id, status in (
        (Events.DRAFT, "DRAFT"),
        (Events.SUBMITTED, "SUBMITTED"),
        (Events.APPROVED, "APPROVED"),
        (Events.REJECTED, "REJECTED"),
    ):
        assert (
            db.execute(text("SELECT status FROM events WHERE id = :id"), {"id": event_id}).scalar()
            == status
        )


@pytest.mark.story("1")
def test_orm_models_match_database(engine):
    """Every SQLAlchemy model column exists in the real table with the same nullability."""
    inspector = inspect(engine)
    problems = []
    for table in Base.metadata.sorted_tables:
        if table.name not in inspector.get_table_names():
            problems.append(f"table {table.name} missing from database")
            continue
        db_columns = {c["name"]: c for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in db_columns:
                problems.append(f"{table.name}.{column.name} missing from database")
            elif bool(db_columns[column.name]["nullable"]) != bool(column.nullable):
                problems.append(f"{table.name}.{column.name} nullability differs")
    assert not problems, "\n".join(problems)


@pytest.mark.story("1")
@pytest.mark.story("14.2", ac=1)
def test_database_refuses_overlapping_approved_bookings(db: Session):
    """The exclusion constraint blocks a second APPROVED booking overlapping Grand Hall."""
    from psycopg.errors import ExclusionViolation
    from sqlalchemy.exc import IntegrityError

    conn = db.connection()
    with pytest.raises(IntegrityError) as excinfo:
        conn.execute(
            text(
                "INSERT INTO venue_bookings (event_id, venue_id, requested_by_id, starts_at,"
                " ends_at,"
                " expected_attendance, status) VALUES (:e, :v, :u, '2026-11-25 18:30+08',"
                " '2026-11-25 20:00+08', 10, 'APPROVED')"
            ),
            {"e": Events.SUBMITTED, "v": Venues.GRAND_HALL, "u": Users.COORDINATOR.id},
        )
    assert isinstance(excinfo.value.orig, ExclusionViolation)


@pytest.mark.story("1")
@pytest.mark.story("14.1", ac=3)
def test_database_allows_booking_that_touches_at_boundary(db: Session):
    """Seed booking is held until 19:00 (+60 min teardown); a booking from 19:00 is fine."""
    conn = db.connection()
    conn.execute(
        text(
            "INSERT INTO venue_bookings (event_id, venue_id, requested_by_id, starts_at, ends_at,"
            " expected_attendance, status) VALUES (:e, :v, :u, '2026-11-25 19:00+08',"
            " '2026-11-25 20:00+08', 10, 'APPROVED')"
        ),
        {"e": Events.SUBMITTED, "v": Venues.GRAND_HALL, "u": Users.COORDINATOR.id},
    )


@pytest.mark.story("1")
@pytest.mark.story("3.1", ac=1)
def test_only_drafts_may_omit_mandatory_event_fields(db: Session):
    from psycopg.errors import CheckViolation
    from sqlalchemy.exc import IntegrityError

    conn = db.connection()
    conn.execute(
        text("INSERT INTO events (organiser_id, name, status) VALUES (:u, 'Draft only', 'DRAFT')"),
        {"u": Users.ORGANISER.id},
    )
    with pytest.raises(IntegrityError) as excinfo:
        conn.execute(
            text(
                "INSERT INTO events (organiser_id, name, status)"
                " VALUES (:u, 'Incomplete', 'SUBMITTED')"
            ),
            {"u": Users.ORGANISER.id},
        )
    assert isinstance(excinfo.value.orig, CheckViolation)


@pytest.mark.story("1")
def test_updated_at_is_maintained_by_trigger(db: Session):
    conn = db.connection()
    before = conn.execute(
        text("SELECT updated_at FROM venues WHERE id = :id"), {"id": Venues.BOARDROOM}
    ).scalar()
    conn.execute(
        text("UPDATE venues SET capacity = capacity + 1 WHERE id = :id"), {"id": Venues.BOARDROOM}
    )
    after = conn.execute(
        text("SELECT updated_at FROM venues WHERE id = :id"), {"id": Venues.BOARDROOM}
    ).scalar()
    assert after > before
