"""Small factories for rows tests need beyond the seed data.

Each returns a persisted ORM object (flushed, not committed - the test transaction is rolled
back anyway). Use unique names/emails so tests never collide with the seed.
"""

from __future__ import annotations

import itertools
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.passwords import hash_password
from app.bookings.models import VenueBooking
from app.change_requests.models import EventChangeRequest
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
from tests.support.seed import Events, Users, Venues

_counter = itertools.count(1)
# Story 18.4 AC2: when a made attendee gave their details, so they register without being asked,
# and the phone number they gave - one is required once they have (AC7).
ATTENDEE_DETAILS_CONFIRMED_AT = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
ATTENDEE_PHONE = "+65 9000 0000"


def make_user(
    db: Session,
    *,
    role: str = "EVENT_ORGANISER",
    password: str = "Password123!",
    is_active: bool = True,
    **overrides,
) -> User:
    """A persisted user. An ATTENDEE has given their details before, as one who has registered
    already has (story 18.4 AC2), a phone number among them (AC7); pass
    ``attendee_details_confirmed_at=None`` for one who never has, whose first registration asks
    for them."""
    n = next(_counter)
    if role == "ATTENDEE":
        overrides.setdefault("attendee_details_confirmed_at", ATTENDEE_DETAILS_CONFIRMED_AT)
        if overrides["attendee_details_confirmed_at"] is not None:
            overrides.setdefault("phone", ATTENDEE_PHONE)
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
    """A period a venue is closed (story 9.1's calendar, 8.1's availability filter). Without
    ``notes`` it is given a description, as story 9.4 AC1 requires one of every closure."""
    if notes is None:
        notes = "Closed for testing"
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


def approval_payload(*, expires_in: timedelta = timedelta(days=1)) -> dict:
    """A valid POST /bookings/{id}/approve body (story 13.2). Since story 12.7 Venue Staff give
    the approved booking's hold its expiry as they approve: a day from now unless said
    otherwise, before any booking a test approves starts."""
    return {"hold_expires_at": (datetime.now(UTC) + expires_in).isoformat()}


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
    """A valid, complete POST /events body (story 2.1) with optional overrides. It has one venue
    requirement, named only, since no request is saved without one (story 2.7 AC14, fix
    f2.7.4); pass ``venue_requirements`` to give it others."""
    n = next(_counter)
    starts_at = future_datetime(days=30)
    body = {
        "name": f"API Event {n}",
        "purpose": "Staff training",
        "description": "One-day hands-on workshop.",
        "starts_at": starts_at.isoformat(),
        "ends_at": (starts_at + timedelta(hours=8)).isoformat(),
        "expected_attendance": 40,
        "venue_requirements": [{"name": "Main venue"}],
    }
    body.update(overrides)
    return body


def submittable_event_request_payload(**overrides) -> dict:
    """A request that can be submitted: every event detail filled in, venue requirements answered
    with one complete requirement - "Main venue", for as many people as the expected attendance,
    or 40 when that is not an integer (story 2.7 AC15, fix f2.7.4) - accessibility answered with
    "none required", and a full point of contact (story 2.1 AC10, AC13). Pass
    ``venue_requirements`` when the test supplies its own."""
    answers = {
        "accessibility_none_required": True,
        "contact_name": "Priya Nair",
        "contact_email": "priya.nair@example.com",
        "contact_phone": "+65 9123 4567",
    }
    body = event_request_payload(**{**answers, **overrides})
    if "venue_requirements" not in overrides:
        attendance = body["expected_attendance"]
        is_integer = isinstance(attendance, int) and not isinstance(attendance, bool)
        body["venue_requirements"] = [
            {"name": "Main venue", "capacity": attendance if is_integer else 40}
        ]
    return body


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
    item has on a submitted event, for the event's period; an item that was declined, cancelled,
    withdrawn or flagged unavailable holds nothing, so pass ``is_held=False`` for those. A
    withdrawn one is stamped as withdrawn now by Users.COORDINATOR unless told otherwise (story
    17.2 AC3, ck_event_equipment_requests_withdrawal)."""
    if status == "WITHDRAWN":
        overrides.setdefault("withdrawn_at", datetime.now(UTC))
        overrides.setdefault("withdrawn_by_id", Users.COORDINATOR.id)
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


def make_change_request(
    db: Session,
    *,
    event: Event,
    field: str = "expected_attendance",
    current: Any = 100,
    proposed: Any = 150,
    status: str = "PENDING",
    **overrides,
) -> EventChangeRequest:
    """A change request on ``event`` (story 19.1), its values given as Python and stored as the
    canonical JSON 19.1 writes, so a test can start from any status (story 19.2). Stamped with a
    fresh time, so several made in one test keep the order they were made in."""
    request = EventChangeRequest(
        event_id=event.id,
        requested_by_id=overrides.pop("requested_by_id", event.organiser_id),
        field_name=field,
        current_value=json.dumps(current, sort_keys=True, separators=(",", ":")),
        proposed_value=json.dumps(proposed, sort_keys=True, separators=(",", ":")),
        reason=overrides.pop("reason", "More sign-ups than expected."),
        status=status,
        created_at=overrides.pop("created_at", datetime.now(UTC)),
        **overrides,
    )
    db.add(request)
    db.flush()
    db.refresh(request)
    return request


@dataclass(frozen=True)
class SecuredEvent:
    """A Planning event whose every arrangement is secured (story 21.2 AC1): one venue
    requirement with its approved booking, and one accepted equipment item."""

    event: Event
    requirement_id: uuid.UUID
    booking: VenueBooking
    equipment: EventEquipmentRequest


def make_secured_event(
    db: Session, *, status: str = EventStatus.PLANNING, **overrides
) -> SecuredEvent:
    """A secured event (``SecuredEvent``) in ``status``, coordinated by Users.COORDINATOR, dated
    in 2030 so no seeded booking holds its venue."""
    starts_at = overrides.pop("starts_at", datetime(2030, 3, 4, 1, 0, tzinfo=UTC))
    ends_at = overrides.pop("ends_at", datetime(2030, 3, 4, 9, 0, tzinfo=UTC))
    venue_id = overrides.pop("venue_id", Venues.GRAND_HALL)
    event = make_event(
        db,
        status=status,
        starts_at=starts_at,
        ends_at=ends_at,
        assigned_coordinator_id=overrides.pop("assigned_coordinator_id", Users.COORDINATOR.id),
        **overrides,
    )
    requirement_id = make_venue_requirement(
        db, event.id, starts_at=starts_at, ends_at=ends_at, capacity=event.expected_attendance
    )
    booking = make_booking(
        db,
        event_id=event.id,
        venue_id=venue_id,
        starts_at=starts_at,
        ends_at=ends_at,
        status="APPROVED",
        venue_requirement_id=requirement_id,
        expected_attendance=event.expected_attendance,
        hold_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    equipment = make_equipment_item(
        db, event=event, equipment_type=make_equipment_type(db), quantity=2, status="ACCEPTED"
    )
    db.refresh(event)
    return SecuredEvent(
        event=event, requirement_id=requirement_id, booking=booking, equipment=equipment
    )
