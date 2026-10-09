"""Request / response shapes for venue bookings: raising a request (story 12.1), the venue
staff queue (story 13.1), and approval / rejection / read (stories 13.2, 13.2.1).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.bookings.models import BookingStatus, VenueBooking


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


# Story 11.1 AC2: the longest justification for requesting an unsuitable venue, as long as a
# clarification message. Keep in step by hand with SUITABILITY_OVERRIDE_REASON_MAX_LENGTH in
# frontend/src/api/bookings.ts, which the request step's textarea uses.
SUITABILITY_OVERRIDE_REASON_MAX_LENGTH = 2000


class BookingRequestIn(BaseModel):
    """Story 12.1 AC1: one event, against one venue - so one ``venue_id``, not a list.

    AC2 requires the request to carry *the event's* schedule, attendance, layout and required
    facilities, so the service copies those from the event row; a client cannot book a period or
    an attendance the event was not approved for.

    Story 12.5 AC1: ``venue_requirement_id`` names the event's venue requirement the request is
    for, and the service copies that requirement's own period, number of people, layout and
    facilities. None makes an additional venue (AC5, AC7), which carries the event's own.

    The one other thing a client sends is story 11.1's ``suitability_override_reason``: why it is
    requesting a venue that does not suit the event. Trimmed, and blank counts as not given; the
    service decides whether one is needed.
    """

    event_id: uuid.UUID
    venue_id: uuid.UUID
    venue_requirement_id: uuid.UUID | None = None
    suitability_override_reason: str | None = Field(
        default=None, max_length=SUITABILITY_OVERRIDE_REASON_MAX_LENGTH
    )

    @field_validator("suitability_override_reason", mode="before")
    @classmethod
    def _blank_reason_is_none(cls, value: object) -> object:
        """Story 11.1 AC7: an empty or whitespace-only justification is no justification."""
        stripped = _strip(value)
        return None if stripped == "" else stripped


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
    # Story 12.5 AC1: the venue requirement the request is for; None for an additional venue.
    venue_requirement_id: uuid.UUID | None
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


# Story 13.1.2 AC1: the statuses the queue can be narrowed to - every value
# ``ck_venue_bookings_status`` allows, so an unknown one is a 422 rather than an empty tab. Built
# from ``BookingStatus`` so a status added there is a tab here without a second list to update.
BookingQueueStatus = StrEnum(
    "BookingQueueStatus",
    {name: value for name, value in vars(BookingStatus).items() if name.isupper()},
)


class BookingQueueEntry(BaseModel):
    """Story 13.1 AC2: event name, requested venue, period, expected attendance and stated
    requirements. Story 13.1.2 AC2: when the request was raised. 13.1.2 AC3: ``decision_reason``
    and ``decided_at``, so a decided entry shows why and when it was decided without a second
    request. No defaults (response schema)."""

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
    created_at: datetime
    decided_at: datetime | None

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
            created_at=booking.created_at,
            decided_at=booking.decided_at,
        )


class BookingStatusCounts(BaseModel):
    """Story 13.1.2 AC1: how many requests hold each status, for the tab labels. No defaults
    (response schema). ``extra="forbid"`` makes ``from_counts`` refuse a status with no field."""

    model_config = ConfigDict(extra="forbid")

    pending: int
    approved: int
    rejected: int
    withdrawn: int
    cancelled: int

    @classmethod
    def from_counts(cls, by_status: Mapping[str, int]) -> BookingStatusCounts:
        """A status with no field here fails validation, rather than dropping out of All's
        total unnoticed."""
        return cls(**{status.lower(): by_status.get(status, 0) for status in BookingQueueStatus})


class BookingQueue(BaseModel):
    """Story 13.1.2 AC4: one page of the queue and how many requests the chosen tab holds in all,
    so the page can say how many more there are. AC1: ``counts`` covers every status whatever tab
    or page was asked for. No defaults (response schema)."""

    items: list[BookingQueueEntry]
    total: int
    counts: BookingStatusCounts


class BookingOutcome(BaseModel):
    """13.2.1 AC4: one venue booking's outcome as the event page shows it - venue name/location
    rather than a raw id, since this is a read-only summary for that page, not the full record
    (``BookingOut``, which the decide/read endpoints already return)."""

    id: uuid.UUID
    venue_id: uuid.UUID
    venue_name: str
    venue_location: str
    # Story 12.5 AC2/AC4: the venue requirement the booking is for, so the event's page and the
    # catalogue's banner can say which requirements are covered. Both None for an additional
    # venue (AC5).
    venue_requirement_id: uuid.UUID | None
    venue_requirement_name: str | None
    starts_at: datetime
    ends_at: datetime
    setup_minutes: int
    teardown_minutes: int
    status: str
    decided_at: datetime | None
    decision_reason: str | None
    # Story 11.1 AC6: why the coordinator requested a venue that did not suit, for the assigned
    # coordinator on the event page. None when the venue suited.
    suitability_override_reason: str | None

    @classmethod
    def from_booking(cls, booking: VenueBooking) -> BookingOutcome:
        return cls(
            id=booking.id,
            venue_id=booking.venue_id,
            venue_name=booking.venue.name,
            venue_location=booking.venue.location,
            venue_requirement_id=booking.venue_requirement_id,
            venue_requirement_name=(
                None if booking.venue_requirement is None else booking.venue_requirement.name
            ),
            starts_at=booking.starts_at,
            ends_at=booking.ends_at,
            setup_minutes=booking.setup_minutes,
            teardown_minutes=booking.teardown_minutes,
            status=booking.status,
            decided_at=booking.decided_at,
            decision_reason=booking.decision_reason,
            suitability_override_reason=booking.suitability_override_reason,
        )
