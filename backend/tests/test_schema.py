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
import app.events.models  # noqa: F401
import app.registrations.models  # noqa: F401
import app.safety.models  # noqa: F401
import app.venues.models  # noqa: F401
from app.db import Base
from app.dbtool import migrate
from tests.support.seed import (
    Bookings,
    Clarifications,
    EquipmentHolds,
    EquipmentItems,
    EquipmentOutOfService,
    Events,
    Notifications,
    Registrations,
    Unavailability,
    Users,
    Venues,
)

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


@pytest.mark.story("1", ac=3)
@pytest.mark.story("18.2", ac=4)
@pytest.mark.parametrize(
    ("registration_id", "event_id", "attendee_id"),
    [
        (Registrations.PORTFOLIO_REVIEW, Events.PORTFOLIO_REVIEW, Users.ATTENDEE_2.id),
        (Registrations.SKETCHING_WALK, Events.SKETCHING_WALK, Users.ATTENDEE.id),
    ],
    ids=["18.1-bella-portfolio-review", "18.2-aiden-sketching-walk"],
)
def test_reseeding_leaves_a_newer_active_registration_alone(
    db: Session, registration_id, event_id, attendee_id
):
    """`npm run db:ready` re-applies the seed to a database people have used. Once a seeded
    registration was withdrawn and its attendee registered again (18.2 AC4), making the seeded one
    REGISTERED again would give them two active registrations, which
    uq_event_registrations_active refuses, and the seed would fail."""
    conn = db.connection()
    conn.execute(
        text(
            "UPDATE event_registrations SET status = 'WITHDRAWN', withdrawn_at = now()"
            " WHERE id = :id"
        ),
        {"id": registration_id},
    )
    newer = conn.execute(
        text(
            "INSERT INTO event_registrations (event_id, attendee_id) VALUES (:event, :attendee)"
            " RETURNING id"
        ),
        {"event": event_id, "attendee": attendee_id},
    ).scalar_one()

    for seed_file in migrate.list_seeds():
        conn.exec_driver_sql(seed_file.read())

    statuses = dict(
        conn.execute(
            text(
                "SELECT id, status FROM event_registrations"
                " WHERE event_id = :event AND attendee_id = :attendee"
            ),
            {"event": event_id, "attendee": attendee_id},
        ).all()
    )
    assert statuses == {registration_id: "WITHDRAWN", newer: "REGISTERED"}


@pytest.mark.story("1", ac=3)
@pytest.mark.story("18.2", ac=4)
def test_reseeding_leaves_a_registration_alone_once_a_newer_one_was_withdrawn_too(db: Session):
    """Aiden withdrew from the seeded walk, registered again, and withdrew that too. Nothing is
    active, but the newer registration is the one My registrations shows (18.2 AC1), as
    Withdrawn: making the seeded one REGISTERED again would hold a place that page cannot
    withdraw, while Upcoming events says he is registered."""
    conn = db.connection()
    conn.execute(
        text(
            "UPDATE event_registrations SET status = 'WITHDRAWN', withdrawn_at = now()"
            " WHERE id = :id"
        ),
        {"id": Registrations.SKETCHING_WALK},
    )
    newer = conn.execute(
        text(
            "INSERT INTO event_registrations (event_id, attendee_id, status, withdrawn_at)"
            " VALUES (:event, :attendee, 'WITHDRAWN', now()) RETURNING id"
        ),
        {"event": Events.SKETCHING_WALK, "attendee": Users.ATTENDEE.id},
    ).scalar_one()

    for seed_file in migrate.list_seeds():
        conn.exec_driver_sql(seed_file.read())

    statuses = dict(
        conn.execute(
            text(
                "SELECT id, status FROM event_registrations"
                " WHERE event_id = :event AND attendee_id = :attendee"
            ),
            {"event": Events.SKETCHING_WALK, "attendee": Users.ATTENDEE.id},
        ).all()
    )
    assert statuses == {Registrations.SKETCHING_WALK: "WITHDRAWN", newer: "WITHDRAWN"}


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
        # The Events.* names identify rows, not statuses (see support/seed.py): several rows
        # share a status, and this table is what pins down which status each one carries.
        (Events.SUBMITTED, "UNDER_REVIEW"),
        (Events.APPROVED, "PLANNING"),
        (Events.REJECTED, "REJECTED"),
        (Events.UNDER_REVIEW, "UNDER_REVIEW"),
        (Events.CLARIFICATION_REQUESTED, "CLARIFICATION_REQUESTED"),
        (Events.SUBMITTED_2, "UNDER_REVIEW"),
        (Events.APPROVED_2, "PLANNING"),
        (Events.APPROVED_3, "PLANNING"),
        (Events.APPROVED_4, "PLANNING"),
        (Events.APPROVED_5, "PLANNING"),
        (Events.APPROVED_6, "PLANNING"),
        (Events.APPROVED_7, "PLANNING"),
        (Events.PLANNING, "PLANNING"),
        (Events.CONFIRMED, "CONFIRMED"),
        (Events.COMPLETED, "COMPLETED"),
        (Events.CANCELLED, "CANCELLED"),
        (Events.PARTNER_BRIEFING, "PLANNING"),
        (Events.EQUIPMENT_WORKSHOP, "PLANNING"),
        (Events.EQUIPMENT_SHOWCASE, "PLANNING"),
        (Events.EQUIPMENT_ROADSHOW, "PLANNING"),
        (Events.FINTECH_BREAKFAST, "PLANNING"),
        (Events.CUSTOMER_FORUM, "PLANNING"),
        (Events.SALES_KICKOFF, "PLANNING"),
        (Events.RECRUITMENT_FAIR, "PLANNING"),
        (Events.PARTNER_GALA, "PLANNING"),
        (Events.EQUIPMENT_DECISIONS, "PLANNING"),
        (Events.WATERFRONT_DEMO, "PLANNING"),
        (Events.SMART_CITIES_EXPO, "PLANNING"),
        (Events.MOBILITY_FORUM, "PLANNING"),
        (Events.RESILIENCE_WORKSHOP, "PLANNING"),
        (Events.ONBOARDING_DAY, "PLANNING"),
        (Events.TRADE_FAIR, "PLANNING"),
        (Events.PRICING_CLINIC, "PLANNING"),
        (Events.CRAFT_FAIR, "PLANNING"),
        (Events.HARBOUR_CONCERT, "AWAITING_SAFETY_CHECK"),
        (Events.BOOK_FAIR, "AWAITING_SAFETY_CHECK"),
        (Events.JAZZ_EVENING, "CONFIRMED"),
        (Events.DESIGN_MASTERCLASS, "CONFIRMED"),
        (Events.FOUNDERS_FIRESIDE, "CONFIRMED"),
        (Events.MENTORING_SLOT, "CONFIRMED"),
        (Events.PORTFOLIO_REVIEW, "CONFIRMED"),
        (Events.WINE_APPRECIATION, "CONFIRMED"),
        (Events.LUNAR_NEW_YEAR_MARKET, "CONFIRMED"),
        (Events.SUPPLIER_INDUCTION, "PLANNING"),
        (Events.POETRY_NIGHT, "CONFIRMED"),
        (Events.SKETCHING_WALK, "CONFIRMED"),
        (Events.BOARD_GAMES_SOCIAL, "CONFIRMED"),
        (Events.SUNSET_YOGA, "CONFIRMED"),
        (Events.HERITAGE_TRAIL, "CONFIRMED"),
        (Events.CHARITY_FUN_RUN, "CANCELLED"),
        (Events.BOOK_SWAP, "CONFIRMED"),
        (Events.LANTERN_PAINTING, "CONFIRMED"),
        # Story 12.6's e2e events: all Planning but the heritage walk, which was cancelled.
        (Events.LANTERN_SHOWCASE, "PLANNING"),
        (Events.MAKER_FAIRE, "PLANNING"),
        (Events.SPRING_EXPO, "PLANNING"),
        (Events.AWARDS_EVENING, "PLANNING"),
        (Events.PITCH_NIGHT, "PLANNING"),
        (Events.NEIGHBOURHOOD_SUMMIT, "PLANNING"),
        (Events.HERITAGE_WALK, "CANCELLED"),
        (Events.PRODUCT_SHOWCASE, "PLANNING"),
        (Events.ROBOTICS_OPEN_HOUSE, "PLANNING"),
        (Events.WELLNESS_EXPO, "PLANNING"),
        (Events.CRAFT_MARKET, "PLANNING"),
        (Events.HARVEST_FAIR, "PLANNING"),
        (Events.OPEN_STUDIOS, "PLANNING"),
        (Events.NIGHT_BAZAAR, "PLANNING"),
        (Events.SPRING_FAIR, "PLANNING"),
        (Events.GARDEN_FAIR, "PLANNING"),
        (Events.LEADERSHIP_RETREAT, "PLANNING"),
    ):
        assert (
            db.execute(text("SELECT status FROM events WHERE id = :id"), {"id": event_id}).scalar()
            == status
        )
    # Story 12.6's e2e bookings: each marked, bar the maker faire's requirement booking, with the
    # closure of its day; the product showcase's is pending and the rest approved.
    for booking_id, status, is_marked in (
        (Bookings.LANTERN_SHOWCASE_FOYER, "APPROVED", True),
        (Bookings.MAKER_FAIRE_SEMINAR_ROOM, "APPROVED", False),
        (Bookings.MAKER_FAIRE_ADDITIONAL_FOYER, "APPROVED", True),
        (Bookings.SPRING_EXPO_FOYER, "APPROVED", True),
        (Bookings.AWARDS_EVENING_FOYER, "APPROVED", True),
        (Bookings.PITCH_NIGHT_FOYER, "APPROVED", True),
        (Bookings.NEIGHBOURHOOD_SUMMIT_FOYER, "APPROVED", True),
        (Bookings.HERITAGE_WALK_FOYER, "APPROVED", True),
        (Bookings.PRODUCT_SHOWCASE_FOYER, "PENDING", True),
        (Bookings.ROBOTICS_OPEN_HOUSE_FOYER, "APPROVED", True),
        (Bookings.WELLNESS_EXPO_FOYER, "APPROVED", True),
        (Bookings.CRAFT_MARKET_SEMINAR_ROOM, "APPROVED", False),
        (Bookings.CRAFT_MARKET_ADDITIONAL_FOYER, "APPROVED", True),
        (Bookings.HARVEST_FAIR_SEMINAR_ROOM, "APPROVED", False),
        (Bookings.HARVEST_FAIR_ADDITIONAL_FOYER, "APPROVED", True),
        (Bookings.OPEN_STUDIOS_HARBOUR, "APPROVED", False),
        (Bookings.OPEN_STUDIOS_REPLACEMENT_FOYER, "PENDING", True),
        (Bookings.NIGHT_BAZAAR_SEMINAR_ROOM, "APPROVED", False),
        (Bookings.NIGHT_BAZAAR_ADDITIONAL_FOYER, "PENDING", True),
        (Bookings.SPRING_FAIR_FOYER, "APPROVED", True),
        (Bookings.GARDEN_FAIR_PENDING, "PENDING", False),
        (Bookings.GARDEN_FAIR_WITHDRAWN, "WITHDRAWN", False),
    ):
        row = db.execute(
            text(
                "SELECT status, venue_unavailable_marked_at IS NOT NULL AS is_marked"
                " FROM venue_bookings WHERE id = :id"
            ),
            {"id": booking_id},
        ).one()
        assert (row.status, row.is_marked) == (status, is_marked)
    for period_id in (
        Unavailability.FOYER_LANTERN_SHOWCASE,
        Unavailability.FOYER_NEIGHBOURHOOD_SUMMIT,
    ):
        assert db.execute(
            text("SELECT 1 FROM venue_unavailability_periods WHERE id = :id"), {"id": period_id}
        ).scalar()
    # Story 18.1: Bella's place, the only one at the Portfolio Review Slot.
    assert (
        db.execute(
            text(
                "SELECT attendee_id FROM event_registrations WHERE id = :id AND event_id = :event"
            ),
            {"id": Registrations.PORTFOLIO_REVIEW, "event": Events.PORTFOLIO_REVIEW},
        ).scalar()
        == Users.ATTENDEE_2.id
    )
    # Story 18.2: Aiden's registrations, one for each of 18.2's events.
    for registration_id, event_id, status in (
        (Registrations.POETRY_NIGHT, Events.POETRY_NIGHT, "REGISTERED"),
        (Registrations.SKETCHING_WALK, Events.SKETCHING_WALK, "REGISTERED"),
        (Registrations.BOARD_GAMES_SOCIAL, Events.BOARD_GAMES_SOCIAL, "REGISTERED"),
        (Registrations.SUNSET_YOGA, Events.SUNSET_YOGA, "REGISTERED"),
        (Registrations.HERITAGE_TRAIL, Events.HERITAGE_TRAIL, "WITHDRAWN"),
        (Registrations.CHARITY_FUN_RUN, Events.CHARITY_FUN_RUN, "REGISTERED"),
        (Registrations.BOOK_SWAP, Events.BOOK_SWAP, "REGISTERED"),
        (Registrations.LANTERN_PAINTING, Events.LANTERN_PAINTING, "REGISTERED"),
    ):
        assert db.execute(
            text(
                "SELECT attendee_id, status FROM event_registrations"
                " WHERE id = :id AND event_id = :event"
            ),
            {"id": registration_id, "event": event_id},
        ).one() == (Users.ATTENDEE.id, status)
    for clarification_id in (Clarifications.REQUEST, Clarifications.RESPONSE):
        assert db.execute(
            text("SELECT 1 FROM event_clarifications WHERE id = :id"), {"id": clarification_id}
        ).scalar()
    # Story 15.1's e2e rows: an item not yet sent and a pending one, each with its hold, and the
    # out-of-service record that leaves no video camera free for the showcase. Story 15.2's: one
    # item per Technical Support tab, and the out-of-service record that leaves the pending one
    # short. Story 17.1's: three released items on a cancelled event, holding nothing, and a
    # pending one with its hold.
    for item_id, status in (
        (EquipmentItems.WORKSHOP_PROJECTORS, "REQUESTED"),
        (EquipmentItems.SHOWCASE_SPEAKERS, "PENDING"),
        (EquipmentItems.ROADSHOW_LAPEL_MICS, "PENDING"),
        (EquipmentItems.ROADSHOW_WIRELESS_MICS, "ACCEPTED"),
        (EquipmentItems.ROADSHOW_PROJECTORS, "DECLINED"),
        (EquipmentItems.OFFSITE_SPEAKERS, "PENDING"),
        (EquipmentItems.OFFSITE_LED_SCREEN, "PENDING"),
        (EquipmentItems.OFFSITE_CONF_PHONES, "PENDING"),
        (EquipmentItems.OFFSITE_LAPTOPS, "PENDING"),
        (EquipmentItems.OFFSITE_PROJECTORS, "PENDING"),
        (EquipmentItems.OFFSITE_WIRELESS_MICS, "PENDING"),
        (EquipmentItems.OFFSITE_CAMERAS, "PENDING"),
        (EquipmentItems.MIXER_SPEAKERS, "CANCELLED"),
        (EquipmentItems.MIXER_WIRELESS_MICS, "CANCELLED"),
        (EquipmentItems.MIXER_PROJECTOR, "CANCELLED"),
        (EquipmentItems.DEMO_LAPTOPS, "PENDING"),
    ):
        assert (
            db.execute(
                text("SELECT status FROM event_equipment_requests WHERE id = :id"), {"id": item_id}
            ).scalar()
            == status
        )
    for hold_id, item_id in (
        (EquipmentHolds.WORKSHOP_PROJECTORS, EquipmentItems.WORKSHOP_PROJECTORS),
        (EquipmentHolds.SHOWCASE_SPEAKERS, EquipmentItems.SHOWCASE_SPEAKERS),
        (EquipmentHolds.ROADSHOW_LAPEL_MICS, EquipmentItems.ROADSHOW_LAPEL_MICS),
        (EquipmentHolds.ROADSHOW_WIRELESS_MICS, EquipmentItems.ROADSHOW_WIRELESS_MICS),
        (EquipmentHolds.OFFSITE_SPEAKERS, EquipmentItems.OFFSITE_SPEAKERS),
        (EquipmentHolds.OFFSITE_LED_SCREEN, EquipmentItems.OFFSITE_LED_SCREEN),
        (EquipmentHolds.OFFSITE_CONF_PHONES, EquipmentItems.OFFSITE_CONF_PHONES),
        (EquipmentHolds.OFFSITE_LAPTOPS, EquipmentItems.OFFSITE_LAPTOPS),
        (EquipmentHolds.OFFSITE_PROJECTORS, EquipmentItems.OFFSITE_PROJECTORS),
        (EquipmentHolds.OFFSITE_WIRELESS_MICS, EquipmentItems.OFFSITE_WIRELESS_MICS),
        (EquipmentHolds.OFFSITE_CAMERAS, EquipmentItems.OFFSITE_CAMERAS),
        (EquipmentHolds.DEMO_LAPTOPS, EquipmentItems.DEMO_LAPTOPS),
    ):
        assert (
            db.execute(
                text(
                    "SELECT equipment_request_id FROM equipment_reservations"
                    " WHERE id = :id AND status = 'RESERVED'"
                ),
                {"id": hold_id},
            ).scalar()
            == item_id
        )
    for period_id in (
        EquipmentOutOfService.SHOWCASE_CAMERAS,
        EquipmentOutOfService.ROADSHOW_LAPEL_MICS,
    ):
        assert db.execute(
            text("SELECT 1 FROM equipment_unavailability_periods WHERE id = :id"),
            {"id": period_id},
        ).scalar()
    # Story 20.2: Nadia Notice, her event and her nine notifications, newest first.
    assert db.execute(
        text("SELECT email, role_code FROM users WHERE id = :id"), {"id": Users.NOTICE.id}
    ).one() == (Users.NOTICE.email, Users.NOTICE.role)
    assert db.execute(
        text("SELECT organiser_id, status FROM events WHERE id = :id"), {"id": Events.NOTICE_GALA}
    ).one() == (Users.NOTICE.id, "PLANNING")
    listed = db.execute(
        text(
            "SELECT id, notification_type, title, read_at IS NOT NULL FROM notifications"
            " WHERE recipient_id = :id ORDER BY created_at DESC"
        ),
        {"id": Users.NOTICE.id},
    ).all()
    assert [tuple(row) for row in listed] == [
        tuple(notification) for notification in Notifications.NEWEST_FIRST
    ]


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
                " VALUES (:u, 'Incomplete', 'UNDER_REVIEW')"
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
