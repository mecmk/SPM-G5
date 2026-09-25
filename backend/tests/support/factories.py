"""Small factories for rows tests need beyond the seed data.

Each returns a persisted ORM object (flushed, not committed - the test transaction is rolled
back anyway). Use unique names/emails so tests never collide with the seed.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
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
    EventStatus,
)
from app.venues.models import Venue
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


def make_venue(db: Session, **overrides) -> Venue:
    n = next(_counter)
    venue = Venue(
        name=overrides.pop("name", f"Test Venue {n}"),
        location=overrides.pop("location", "Test Tower"),
        capacity=overrides.pop("capacity", 50),
        **overrides,
    )
    db.add(venue)
    db.flush()
    return venue


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
    and accessibility answered with "none required" (story 2.1 AC10). Override a flag to False
    when the test supplies real requirements instead."""
    answers = {"venue_none_required": True, "accessibility_none_required": True}
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
