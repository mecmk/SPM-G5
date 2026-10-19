"""Story 12.6 - Request a replacement venue for an affected booking

Happy path
1. On an approved booking marked "Venue unavailable – alternative needed" (9.4), the assigned
    coordinator selects "Find a replacement venue" on the event page. The catalogue opens
    pre-filled from that booking's venue requirement (8.4), or, for an additional venue, from the
    event's own period and attendance, with the unavailable venue excluded. The banner names the
    booking being replaced, and stays while the coordinator changes or clears the filters.
2. "Request this venue" raises a new booking request linked to the original booking as its
    replacement, carrying the original's setup and teardown (still editable on the request step).
    The event's details, status and other venue bookings are not changed.
3. When Venue Staff approve the replacement (13.2), the original booking is released (Cancelled)
    in the same step. The event's booking list shows the original as "Replaced by <venue>", closed
    at the time of the release, and the replacement as "Replaces <venue>". Before approving, Venue
    Staff see "Replaces <venue>" and "Approving this releases <venue>". The coordinator's approval
    notice says the original was released and Venue Staff are told of the release; the organiser
    is not notified.

Boundary
4. Until a replacement is approved, the original booking stays approved and on record. The banner
    (12.5) shows its requirement as "Venue unavailable: <venue>", or "Replacement requested:
    <venue>" while one is pending. The event page does not show "All required venues booked" while
    a requirement's only booking is marked, and Find a venue skips marked requirements.

Edge
5. If the replacement is rejected or withdrawn, the original booking stays marked and another
    replacement can be requested.
6. If the unavailability ends before a replacement is approved (9.4 AC6), the mark clears and
    "Find a replacement venue" disappears; the coordinator can withdraw the pending replacement
    and keep the original booking. If Venue Staff approve it anyway, it still replaces the
    original.
7. A replacement caused by venue unavailability does not need an organiser change request (19.1),
    including when its suitability is overridden with a justification (11.1).
8. No replacement can be requested on a cancelled event (6.2). A replacement that was never
    approved is never shown as having replaced the original.

Permission
9. Only the event's assigned coordinator can request a replacement venue. Only an approved marked
    booking can be replaced. A marked pending booking for a requirement offers "Find another
    venue", which leads to "Switch to this venue" (12.5); a marked pending additional venue is
    withdrawn and requested again.

Conflict
10. Only one pending replacement request is allowed per original booking: while one is pending,
    "Find a replacement venue" is not offered, a second request is refused naming the venue
    already requested, and the pending replacement cannot be switched (withdraw it first). A
    replacement at the original booking's own venue is refused. If two replacements are sent at
    once, only the first succeeds.

Coordinator event list
11. The assigned coordinator's Events inbox has a "Venue unavailable" tab listing only their
    events with a booking marked "Venue unavailable – alternative needed", with the number of such
    events on the tab (0 when none). An event with a pending replacement stays listed and shows
    "Replacement requested: <venue>". Opening an event shows the marked booking. An event leaves
    the tab once no booking on it is marked.

Safety review and confirmation
12. While any booking on an event is marked "Venue unavailable – alternative needed" (9.4), or has
    a pending replacement, the coordinator cannot send the event for safety review (21.2) or
    confirm it. The refusal names each such venue together with any other missing arrangement.
    Once the replacement is approved or withdrawn, or the unavailability ends with no replacement
    pending, the event can be sent and confirmed as usual.

This file tries the database's own guards for a replacement in SQL, below the service: the
composite foreign key with ``event_id`` and the self-link check (AC2), ``replaced_by_booking_id``
only on a CANCELLED booking and one replacement per original (AC3), and the one-pending index, the
narrowed one-per-requirement index and the trigger that puts the carve-out back the moment the
original stops holding by any path (AC10). The service-level rules are test_request_replacement.py
and test_replacement_approval.py.
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
