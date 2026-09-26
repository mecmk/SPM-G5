"""Request / response shapes for venue bookings: raising a request (story 12.1), the venue
staff queue (story 13.1), and approval / rejection / read (stories 13.2, 13.2.1).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.bookings.models import VenueBooking


def _strip(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) else value


class BookableEvent(BaseModel):
    """One choice in the booking form's event pick-list (story 12.1 AC1/AC4).

    Deliberately not the whole event: the form needs to name the event and show the period and
    attendance that AC2 will copy onto the request. The full record is story 7.1's.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    starts_at: datetime
    ends_at: datetime
    expected_attendance: int


class BookingReferenceData(BaseModel):
    """Pick-list values for the booking request form. Venue choices come from ``GET /venues``
    (story 8.1), so they are not repeated here."""

    events: list[BookableEvent]


class BookingRequestIn(BaseModel):
    """Story 12.1 AC1: one event, against one venue - so one ``venue_id``, not a list.

    There is deliberately nothing else to send. AC2 requires the request to carry *the event's*
    schedule, attendance, layout and required facilities, so the service copies those from the
    event row; a client cannot book a period or an attendance the event was not approved for.
    """

    event_id: uuid.UUID
    venue_id: uuid.UUID


class BookingRejection(BaseModel):
    """13.2.1 AC2: a reason is mandatory - blank or whitespace-only does not count. Mirrors
    events.schemas.EventRejection (story 4.5)."""

    model_config = ConfigDict(extra="forbid")

    decision_reason: str = Field(min_length=1)

    @field_validator("decision_reason", mode="before")
    @classmethod
    def _strip_reason(cls, value):
        return _strip(value)


class BookingOut(BaseModel):
    """Full booking record, including the decision fields story 13.2 AC1/AC3 need."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    venue_id: uuid.UUID
    requested_by_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    setup_minutes: int
    teardown_minutes: int
    held_from: datetime
    held_until: datetime
    expected_attendance: int
    required_layout_code: str | None
    requirement_notes: str | None
    suitability_override_reason: str | None
    status: str
    decided_by_id: uuid.UUID | None
    decided_at: datetime | None
    decision_reason: str | None
    alternative_suggestion: str | None
    created_at: datetime
    updated_at: datetime


class BookingQueueEntry(BaseModel):
    """AC2: event name, requested venue, period, expected attendance and stated requirements.
    AC3: also carries ``decision_reason``, so a decided entry's All / Pending / Approved /
    Rejected tabs can show why it was rejected without a second request. No defaults (response
    schema)."""

    id: uuid.UUID
    event_id: uuid.UUID
    event_name: str
    venue_id: uuid.UUID
    venue_name: str
    venue_location: str
    starts_at: datetime
    ends_at: datetime
    expected_attendance: int
    required_layout_code: str | None
    required_layout_name: str | None
    requirement_notes: str | None
    requested_by_name: str
    status: str
    decision_reason: str | None

    @classmethod
    def from_booking(cls, booking: VenueBooking) -> BookingQueueEntry:
        return cls(
            id=booking.id,
            event_id=booking.event_id,
            event_name=booking.event.name,
            venue_id=booking.venue_id,
            venue_name=booking.venue.name,
            venue_location=booking.venue.location,
            starts_at=booking.starts_at,
            ends_at=booking.ends_at,
            expected_attendance=booking.expected_attendance,
            required_layout_code=booking.required_layout_code,
            required_layout_name=booking.required_layout.name if booking.required_layout else None,
            requirement_notes=booking.requirement_notes,
            requested_by_name=booking.requested_by.full_name,
            status=booking.status,
            decision_reason=booking.decision_reason,
        )


class BookingOutcome(BaseModel):
    """13.2.1 AC4: one venue booking's outcome as the event page shows it - venue name/location
    rather than a raw id, since this is a read-only summary for that page, not the full record
    (``BookingOut``, which the decide/read endpoints already return)."""

    id: uuid.UUID
    venue_id: uuid.UUID
    venue_name: str
    venue_location: str
    starts_at: datetime
    ends_at: datetime
    setup_minutes: int
    teardown_minutes: int
    status: str
    decided_at: datetime | None
    decision_reason: str | None

    @classmethod
    def from_booking(cls, booking: VenueBooking) -> BookingOutcome:
        return cls(
            id=booking.id,
            venue_id=booking.venue_id,
            venue_name=booking.venue.name,
            venue_location=booking.venue.location,
            starts_at=booking.starts_at,
            ends_at=booking.ends_at,
            setup_minutes=booking.setup_minutes,
            teardown_minutes=booking.teardown_minutes,
            status=booking.status,
            decided_at=booking.decided_at,
            decision_reason=booking.decision_reason,
        )
