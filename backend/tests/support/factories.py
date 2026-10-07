"""Small factories for rows tests need beyond the seed data.

Each returns a persisted ORM object (flushed, not committed - the test transaction is rolled
back anyway). Use unique names/emails so tests never collide with the seed.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.passwords import hash_password
from app.bookings.models import VenueBooking
from app.events.models import (
    EquipmentReservation,
    EquipmentType,
    EquipmentUnavailabilityPeriod,
    Event,
    EventClarification,
    EventEquipmentRequest,
    EventStatus,
)
from app.venues.models import (
    Venue,
    VenueAccessibilityFeature,
    VenueFacility,
    VenueLayout,
    VenueUnavailabilityPeriod,
)
from tests.support.seed import Events, Users

_counter = itertools.count(1)


def make_user(
    db: Session,
    *,
    role: str = "EVENT_ORGANISER",
    password: str = "Password123!",
    is_active: bool = True,
    **overrides,
) -> User:
    n = next(_counter)
    user = User(
        email=overrides.pop("email", f"user{n}@test.example"),
        password_hash=hash_password(password),
        full_name=overrides.pop("full_name", f"Test User {n}"),
        role_code=role,
        is_active=is_active,
        **overrides,
    )
    db.add(user)
    db.flush()
    return user


def make_event(db: Session, *, status: str = EventStatus.UNDER_REVIEW, **overrides) -> Event:
    """A persisted event that satisfies ck_events_submitted_fields_complete for any non-DRAFT
    status. Pass e.g. ``assigned_coordinator_id=`` or ``submitted_at=`` to override."""
    n = next(_counter)
    event = Event(
        organiser_id=overrides.pop("organiser_id", Users.ORGANISER.id),
        name=overrides.pop("name", f"Test Event {n}"),
        purpose=overrides.pop("purpose", "Testing"),
        starts_at=overrides.pop("starts_at", datetime(2026, 12, 1, 9, 0, tzinfo=UTC)),
        ends_at=overrides.pop("ends_at", datetime(2026, 12, 1, 17, 0, tzinfo=UTC)),
        expected_attendance=overrides.pop("expected_attendance", 20),
        submitted_at=overrides.pop("submitted_at", datetime(2026, 9, 10, 9, 0, tzinfo=UTC)),
        status=status,
        **overrides,
    )
    db.add(event)
    db.flush()
    return event


def make_venue_requirement(
    db: Session,
    event_id: uuid.UUID,
    *,
    position: int = 0,
    name: str | None = "Main venue",
    capacity: int | None = 20,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    layout_code: str | None = None,
    notes: str | None = None,
    facilities: tuple[tuple[str, int | None, str | None], ...] = (),
) -> uuid.UUID:
    """A venue requirement on an event (story 2.7), with its facilities as (code, quantity, notes).
    Written in SQL rather than through the ORM so a test can place one on an event in any status,
    the way the seed and migration 012 do. Returns the requirement's id."""
    requirement_id = db.execute(
        text(
            "INSERT INTO venue_requirements"
            " (event_id, position, name, capacity, starts_at, ends_at, layout_code, notes)"
            " VALUES (:event_id, :position, :name, :capacity, :starts_at, :ends_at,"
            " :layout_code, :notes) RETURNING id"
        ),
        {
            "event_id": event_id,
            "position": position,
            "name": name,
            "capacity": capacity,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "layout_code": layout_code,
            "notes": notes,
        },
    ).scalar_one()
    for code, quantity, facility_notes in facilities:
        db.execute(
            text(
                "INSERT INTO venue_requirement_facilities"
                " (requirement_id, facility_code, quantity, notes)"
                " VALUES (:requirement_id, :code, :quantity, :notes)"
            ),
            {
                "requirement_id": requirement_id,
                "code": code,
                "quantity": quantity,
                "notes": facility_notes,
            },
        )
    db.expire_all()
    return requirement_id


def make_clarification(
    db: Session,
    *,
    event_id: uuid.UUID,
    author_id: uuid.UUID = Users.COORDINATOR.id,
    kind: str = "NOTE",
    message: str = "Test clarification message.",
    created_at: datetime | None = None,
) -> EventClarification:
    """A clarification entry (story 4.6). ``created_at=None`` lets the DB default (now()) apply;
    pass an explicit value to test ordering."""
    row = EventClarification(
        event_id=event_id,
        author_id=author_id,
        kind=kind,
        message=message,
        **({"created_at": created_at} if created_at is not None else {}),
    )
    db.add(row)
    db.flush()
    return row


def make_venue(
    db: Session,
    *,
    facilities: tuple[str, ...] = (),
    layouts: dict[str, int | None] | None = None,
    accessibility: tuple[str, ...] = (),
    hours: tuple[time, time] | None = None,
    **overrides,
) -> Venue:
    """A venue, with its characteristics as reference codes: ``layouts`` maps a layout code to its
    own capacity (None: the venue's), ``hours`` is the daily (opening, closing) window."""
    n = next(_counter)
    opening, closing = hours if hours is not None else (None, None)
    venue = Venue(
        name=overrides.pop("name", f"Test Venue {n}"),
        location=overrides.pop("location", "Test Tower"),
        capacity=overrides.pop("capacity", 50),
        operating_hours_start=opening,
        operating_hours_end=closing,
        facilities=[VenueFacility(facility_code=code) for code in facilities],
        layouts=[
            VenueLayout(layout_code=code, layout_capacity=capacity)
            for code, capacity in (layouts or {}).items()
        ],
        accessibility_features=[
            VenueAccessibilityFeature(feature_code=code) for code in accessibility
        ],
        **overrides,
    )
    db.add(venue)
    db.flush()
    return venue


def make_unavailability(
    db: Session,
    *,
    venue_id: uuid.UUID,
    starts_at: datetime,
    ends_at: datetime,
    reason: str = "MAINTENANCE",
    notes: str | None = None,
) -> VenueUnavailabilityPeriod:
    """A period a venue is closed (story 9.1's calendar, 8.1's availability filter)."""
    period = VenueUnavailabilityPeriod(
        venue_id=venue_id, starts_at=starts_at, ends_at=ends_at, reason=reason, notes=notes
    )
    db.add(period)
    db.flush()
    return period


def make_booking(
    db: Session,
    *,
    venue_id: uuid.UUID,
    starts_at: datetime,
    ends_at: datetime,
    status: str = "PENDING",
    **overrides,
) -> VenueBooking:
    """A venue booking. Refreshed after flush so the trigger-computed held_from/held_until
    (see app/bookings/models.py) are populated on the returned object, not just in the row -
    the conflict check compares those fields in Python.
    """
    booking = VenueBooking(
        event_id=overrides.pop("event_id", Events.APPROVED),
        venue_id=venue_id,
        requested_by_id=overrides.pop("requested_by_id", Users.COORDINATOR.id),
        starts_at=starts_at,
        ends_at=ends_at,
        expected_attendance=overrides.pop("expected_attendance", 10),
        status=status,
        **overrides,
    )
    db.add(booking)
    db.flush()
    db.refresh(booking)
    return booking


def venue_payload(**overrides) -> dict:
    """A valid POST /venues body (story 8.3 AC1 minimum) with optional overrides."""
    n = next(_counter)
    body = {"name": f"API Venue {n}", "location": "Tower Z, Level 9", "capacity": 40}
    body.update(overrides)
    return body


def future_datetime(*, days: int = 30, hours: int = 0) -> datetime:
    """A timezone-aware moment safely after "now" (story 2.1 AC2 rejects the past)."""
    return datetime.now(UTC).replace(microsecond=0) + timedelta(days=days, hours=hours)


def event_request_payload(**overrides) -> dict:
    """A valid, complete POST /events body (story 2.1) with optional overrides."""
    n = next(_counter)
    starts_at = future_datetime(days=30)
    body = {
        "name": f"API Event {n}",
        "purpose": "Staff training",
        "description": "One-day hands-on workshop.",
        "starts_at": starts_at.isoformat(),
        "ends_at": (starts_at + timedelta(hours=8)).isoformat(),
        "expected_attendance": 40,
    }
    body.update(overrides)
    return body


def submittable_event_request_payload(**overrides) -> dict:
    """A request that can be submitted: every event detail filled in, and both venue requirements
    and accessibility answered with "none required" and a full point of contact (story 2.1
    AC10, AC13). Override a flag to False
    when the test supplies real requirements instead."""
    answers = {
        "venue_none_required": True,
        "accessibility_none_required": True,
        "contact_name": "Priya Nair",
        "contact_email": "priya.nair@example.com",
        "contact_phone": "+65 9123 4567",
    }
    return event_request_payload(**{**answers, **overrides})


def create_event_request(client: Any, **overrides) -> dict:
    """POST /events as whoever ``client`` is signed in as; returns the created draft's body."""
    response = client.post("/events", json=event_request_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def create_submittable_event_request(client: Any, **overrides) -> dict:
    """Like ``create_event_request``, for a draft that is ready to submit."""
    response = client.post("/events", json=submittable_event_request_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def make_equipment_hold(
    db: Session,
    *,
    type_code: str,
    quantity: int,
    starts_at: datetime,
    ends_at: datetime,
    status: str = "RESERVED",
    released_quantity: int = 0,
    event_id: uuid.UUID = Events.APPROVED,
) -> EquipmentReservation:
    """Units of an equipment type held for another event over a period (2.1 availability)."""
    equipment_type = db.scalar(select(EquipmentType).where(EquipmentType.code == type_code))
    hold = EquipmentReservation(
        event_id=event_id,
        equipment_type_id=equipment_type.id,
        quantity=quantity,
        starts_at=starts_at,
        ends_at=ends_at,
        status=status,
        reserved_by_id=Users.TECH_SUPPORT.id,
        released_quantity=released_quantity,
    )
    db.add(hold)
    db.flush()
    return hold


def make_equipment_out_of_service(
    db: Session,
    *,
    type_code: str,
    quantity: int,
    starts_at: datetime,
    ends_at: datetime | None = None,
    reason: str = "MAINTENANCE",
) -> EquipmentUnavailabilityPeriod:
    """Units of an equipment type that are out of service; ``ends_at=None`` is open-ended."""
    equipment_type = db.scalar(select(EquipmentType).where(EquipmentType.code == type_code))
    period = EquipmentUnavailabilityPeriod(
        equipment_type_id=equipment_type.id,
        quantity=quantity,
        reason=reason,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    db.add(period)
    db.flush()
    return period


def make_equipment_type(
    db: Session, *, total_quantity: int = 5, is_active: bool = True, **overrides
) -> EquipmentType:
    """A fresh equipment type, so a test controls its whole stock and nothing else holds any."""
    n = next(_counter)
    equipment_type = EquipmentType(
        code=overrides.pop("code", f"TEST_KIT_{n}"),
        name=overrides.pop("name", f"Test kit {n}"),
        total_quantity=total_quantity,
        is_active=is_active,
        **overrides,
    )
    db.add(equipment_type)
    db.flush()
    return equipment_type


def make_equipment_item(
    db: Session,
    *,
    event: Event,
    equipment_type: EquipmentType,
    quantity: int,
    status: str = "REQUESTED",
    is_held: bool = True,
    **overrides,
) -> EventEquipmentRequest:
    """An equipment item on ``event`` (story 15.1). ``is_held`` also places the hold a recorded
    item has on a submitted event, for the event's period; an item that was declined, cancelled
    or flagged unavailable holds nothing, so pass ``is_held=False`` for those."""
    item = EventEquipmentRequest(
        event_id=event.id,
        equipment_type_id=equipment_type.id,
        quantity=quantity,
        status=status,
        created_by_id=overrides.pop("created_by_id", Users.COORDINATOR.id),
        **overrides,
    )
    db.add(item)
    db.flush()
    if is_held:
        db.add(
            EquipmentReservation(
                event_id=event.id,
                equipment_request_id=item.id,
                equipment_type_id=equipment_type.id,
                quantity=quantity,
                starts_at=event.starts_at,
                ends_at=event.ends_at,
                reserved_by_id=Users.COORDINATOR.id,
            )
        )
        db.flush()
    db.refresh(item)
    return item
