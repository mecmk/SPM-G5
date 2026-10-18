"""Story 12.6 - the database's own guards for a replacement, tried in SQL, below the service.

AC2  A replacement is linked to its original by ``replaces_booking_id``, a composite foreign key
     with ``event_id`` so the two share an event; a booking cannot replace itself.
AC3  ``replaced_by_booking_id`` on the original is set only on a CANCELLED booking, and one
     booking replaces at most one original.
AC10 One pending replacement per original (a partial unique index). The one-per-requirement index
     of 12.5 leaves out a pending replacement whose original still holds its venue, and a trigger
     puts it back the moment the original stops holding, by any path - the hold sweep, a release,
     a cancellation - so a normal request can never land beside it.

The service-level rules are test_request_replacement.py and test_replacement_approval.py.
"""

from __future__ import annotations

import pytest
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.bookings.models import BookingStatus
from tests.support.factories import make_booking
from tests.support.replacement import (
    add_pending_replacement,
    column,
    hall,
    make_scenario,
    set_status,
)


def _index_definition(db, name: str) -> str | None:
    return db.scalar(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"), {"name": name}
    )


@pytest.mark.story("12.6", ac=2)
def test_the_composite_foreign_key_refuses_a_link_across_events(db):
    """A replacement of another event's booking is no replacement: the FK is on (id, event_id)."""
    ours, theirs = make_scenario(db), make_scenario(db)

    with pytest.raises(IntegrityError) as refused:
        db.execute(
            text(
                "INSERT INTO venue_bookings (event_id, venue_id, requested_by_id, starts_at,"
                " ends_at, expected_attendance, status, replaces_booking_id)"
                " VALUES (:event_id, :venue_id, :requested_by_id, :starts_at, :ends_at, 40,"
                " 'PENDING', :other)"
            ),
            {
                "event_id": ours.event.id,
                "venue_id": ours.alternative.id,
                "requested_by_id": ours.original.requested_by_id,
                "starts_at": ours.starts_at,
                "ends_at": ours.ends_at,
                "other": theirs.original.id,
            },
        )

    assert isinstance(refused.value.orig, ForeignKeyViolation)


@pytest.mark.story("12.6", ac=2)
def test_a_booking_cannot_replace_itself(db):
    scene = make_scenario(db)

    with pytest.raises(IntegrityError) as refused:
        db.execute(
            text("UPDATE venue_bookings SET replaces_booking_id = id WHERE id = :id"),
            {"id": scene.original.id},
        )

    assert isinstance(refused.value.orig, CheckViolation)


@pytest.mark.story("12.6", ac=3)
def test_replaced_by_may_only_be_set_on_a_cancelled_booking(db):
    scene = make_scenario(db)
    replacement = add_pending_replacement(db, scene)

    with pytest.raises(IntegrityError) as refused:
        db.execute(
            text("UPDATE venue_bookings SET replaced_by_booking_id = :new WHERE id = :id"),
            {"new": replacement.id, "id": scene.original.id},
        )

    assert isinstance(refused.value.orig, CheckViolation)


@pytest.mark.story("12.6", ac=3)
def test_one_booking_replaces_at_most_one_original(db):
    """Two cancelled originals cannot both name the same booking as the one that replaced them."""
    first, second = make_scenario(db), make_scenario(db)
    replacement = add_pending_replacement(db, first)
    set_status(db, first.original.id, BookingStatus.CANCELLED)
    set_status(db, second.original.id, BookingStatus.CANCELLED)
    db.execute(
        text("UPDATE venue_bookings SET replaced_by_booking_id = :new WHERE id = :id"),
        {"new": replacement.id, "id": first.original.id},
    )

    with pytest.raises(IntegrityError) as refused:
        db.execute(
            text("UPDATE venue_bookings SET replaced_by_booking_id = :new WHERE id = :id"),
            {"new": replacement.id, "id": second.original.id},
        )

    assert isinstance(refused.value.orig, UniqueViolation)


@pytest.mark.story("12.6", ac=10)
def test_the_one_per_requirement_index_excludes_only_a_pending_replacement(db):
    """A pending replacement sits beside its approved original; a normal pending request for the
    same requirement still hits the index."""
    scene = make_scenario(db)
    add_pending_replacement(db, scene)
    assert "replaces_live_original" in _index_definition(
        db, "uq_venue_bookings_one_per_requirement"
    )

    with pytest.raises(IntegrityError) as refused:
        make_booking(
            db,
            event_id=scene.event.id,
            venue_id=hall(db).id,
            starts_at=scene.starts_at,
            ends_at=scene.ends_at,
            status=BookingStatus.PENDING,
            venue_requirement_id=scene.requirement_id,
        )

    assert isinstance(refused.value.orig, UniqueViolation)
    assert "uq_venue_bookings_one_per_requirement" in str(refused.value.orig)


@pytest.mark.story("12.6", ac=10)
def test_a_second_pending_replacement_of_one_original_is_refused_by_the_database(db):
    scene = make_scenario(db)
    add_pending_replacement(db, scene)

    with pytest.raises(IntegrityError) as refused:
        add_pending_replacement(db, scene, venue=hall(db))

    assert isinstance(refused.value.orig, UniqueViolation)
    assert "uq_venue_bookings_one_pending_replacement" in str(refused.value.orig)


@pytest.mark.story("12.6", ac=10)
@pytest.mark.parametrize(
    "stops_as", [BookingStatus.EXPIRED, BookingStatus.CANCELLED, BookingStatus.WITHDRAWN]
)
def test_the_trigger_clears_the_carve_out_when_the_original_stops_holding(db, stops_as):
    """By any path: the pending replacement then counts as the requirement's request, so the index
    refuses a normal one beside it."""
    scene = make_scenario(db)
    replacement = add_pending_replacement(db, scene)
    assert column(db, replacement.id, "replaces_live_original") is True

    set_status(db, scene.original.id, stops_as)

    assert column(db, replacement.id, "replaces_live_original") is False
    with pytest.raises(IntegrityError) as refused:
        make_booking(
            db,
            event_id=scene.event.id,
            venue_id=hall(db).id,
            starts_at=scene.starts_at,
            ends_at=scene.ends_at,
            status=BookingStatus.PENDING,
            venue_requirement_id=scene.requirement_id,
        )
    assert "uq_venue_bookings_one_per_requirement" in str(refused.value.orig)


@pytest.mark.story("12.6", ac=10)
def test_the_trigger_leaves_the_carve_out_while_the_original_still_holds(db):
    """A change to the original that leaves it approved - a new hold expiry - clears nothing."""
    scene = make_scenario(db)
    replacement = add_pending_replacement(db, scene)

    db.execute(
        text(
            "UPDATE venue_bookings SET hold_expires_at = hold_expires_at + interval '1 hour'"
            " WHERE id = :id"
        ),
        {"id": scene.original.id},
    )

    assert column(db, replacement.id, "replaces_live_original") is True


@pytest.mark.story("12.6", ac=10)
def test_the_trigger_touches_only_the_closed_originals_replacements(db):
    closing, staying = make_scenario(db), make_scenario(db)
    closed_one = add_pending_replacement(db, closing)
    other = add_pending_replacement(db, staying)

    set_status(db, closing.original.id, BookingStatus.EXPIRED)

    assert column(db, closed_one.id, "replaces_live_original") is False
    assert column(db, other.id, "replaces_live_original") is True
