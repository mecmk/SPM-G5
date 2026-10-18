"""Request / response shapes for venue bookings: raising a request (story 12.1), the venue
staff queue (story 13.1), and approval / rejection / read (stories 13.2, 13.2.1).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime, time
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, field_validator

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

# Story 12.1 AC5, decided for f12.1.2 (14 Oct 2026) and not in the backlog: setup and teardown are
# each at most 14 days, the longest an event may run. Keep in step by hand with
# TURNAROUND_MAX_MINUTES in frontend/src/api/bookings.ts, which the request step's Setup and
# Teardown inputs use.
TURNAROUND_MAX_MINUTES = 14 * 24 * 60


class BookingRequestIn(BaseModel):
    """Story 12.1 AC1: one event, against one venue - so one ``venue_id``, not a list.

    AC2 requires the request to carry *the event's* schedule, attendance, layout and required
    facilities, so the service copies those from the event row; a client cannot change the
    request's own times or its attendance, only widen its booked period around those times by the
    setup and teardown below (f12.1.2).

    Story 12.5 AC1: ``venue_requirement_id`` names the event's venue requirement the request is
    for, and the service copies that requirement's own period, number of people, layout and
    facilities. None makes an additional venue (AC5, AC7), which carries the event's own.

    A client also sends story 11.1's ``suitability_override_reason``: why it is requesting a
    venue that does not suit the event. Trimmed, and blank counts as not given; the service
    decides whether one is needed.

    f12.1.2 (story 12.1 AC1/AC5 in the backlog's current numbering): a client sends the setup and
    teardown as well, in whole minutes, which widen the booked period before the request's own
    start and after its own end. Each is 0 when not sent and at most ``TURNAROUND_MAX_MINUTES``
    (14 days), so a negative, fractional or longer value is refused (422) - and, as the event's
    own whole numbers are (story 2.1 AC3), ``StrictInt`` refuses "90" and true as well.
    """

    event_id: uuid.UUID
    venue_id: uuid.UUID
    venue_requirement_id: uuid.UUID | None = None
    suitability_override_reason: str | None = Field(
        default=None, max_length=SUITABILITY_OVERRIDE_REASON_MAX_LENGTH
    )
    setup_minutes: StrictInt = Field(default=0, ge=0, le=TURNAROUND_MAX_MINUTES)
    teardown_minutes: StrictInt = Field(default=0, ge=0, le=TURNAROUND_MAX_MINUTES)

    @field_validator("suitability_override_reason", mode="before")
    @classmethod
    def _blank_reason_is_none(cls, value: object) -> object:
        """Story 11.1 AC7: an empty or whitespace-only justification is no justification."""
        stripped = _strip(value)
        return None if stripped == "" else stripped


class BookingSwitchIn(BaseModel):
    """Story 12.5, decided 11 Oct 2026: the venue a pending request is switched to. The event and
    the venue requirement are the switched request's own, so neither is sent; the venue is, with
    story 11.1's justification when it does not suit, read as ``BookingRequestIn`` reads it.

    f12.1.2 (story 12.1 AC1/AC5): the new request's setup and teardown are sent as well, read as
    ``BookingRequestIn`` reads them. A switch is a new request, so it carries what it sends - 0
    when it sends none - never the replaced request's.
    """

    venue_id: uuid.UUID
    suitability_override_reason: str | None = Field(
        default=None, max_length=SUITABILITY_OVERRIDE_REASON_MAX_LENGTH
    )
    setup_minutes: StrictInt = Field(default=0, ge=0, le=TURNAROUND_MAX_MINUTES)
    teardown_minutes: StrictInt = Field(default=0, ge=0, le=TURNAROUND_MAX_MINUTES)

    @field_validator("suitability_override_reason", mode="before")
    @classmethod
    def _blank_reason_is_none(cls, value: object) -> object:
        """Story 11.1 AC7: an empty or whitespace-only justification is no justification."""
        stripped = _strip(value)
        return None if stripped == "" else stripped


class BookingReplacementIn(BaseModel):
    """Story 12.6 AC2: the venue asked for as the replacement of the booking in the address, whose
    venue Venue Staff made unavailable. The event, the venue requirement (or none, for an
    additional venue), the period and the attendance are the original's own, so none is sent; the
    venue is, with story 11.1's justification when it does not suit, read as ``BookingRequestIn``
    reads it.

    The setup and teardown default to the original's: a replacement carries what the original
    carried unless the request sends its own, and a ``0`` sent is a choice, not an omission. Each
    is whole minutes up to ``TURNAROUND_MAX_MINUTES``, as for any request (12.1 AC5).
    """

    venue_id: uuid.UUID
    suitability_override_reason: str | None = Field(
        default=None, max_length=SUITABILITY_OVERRIDE_REASON_MAX_LENGTH
    )
    setup_minutes: StrictInt | None = Field(default=None, ge=0, le=TURNAROUND_MAX_MINUTES)
    teardown_minutes: StrictInt | None = Field(default=None, ge=0, le=TURNAROUND_MAX_MINUTES)

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


class BookingApproval(BaseModel):
    """Story 13.2 AC1, with story 12.7 AC1 (the customer's hold, 12 Oct 2026): approving a request
    starts its tentative hold, and Venue Staff set when it expires - there is no default, so it is
    required (422 without one). It names its time zone, since a wall-clock time is no moment until
    it does. Whether it is in the future and before the booked period starts (AC5) needs the
    booking, so the service checks that."""

    model_config = ConfigDict(extra="forbid")

    hold_expires_at: AwareDatetime


class BookingHoldUpdate(BaseModel):
    """Story 12.7 AC1/AC7: the new expiry Venue Staff give an approved booking's open hold. It
    names its time zone (422 without one). Whether it is in the future and before the booked
    period starts (AC5) needs the booking, so the service checks that. Decided 12 Oct 2026 (Q27,
    Q29): a reason is mandatory, as a rejection's is - blank or whitespace-only does not count."""

    model_config = ConfigDict(extra="forbid")

    hold_expires_at: AwareDatetime
    hold_expiry_change_reason: str = Field(min_length=1)

    @field_validator("hold_expiry_change_reason", mode="before")
    @classmethod
    def _strip_reason(cls, value):
        return _strip(value)


class HoldExpiryChangedBy(BaseModel):
    """Story 12.7 AC7, decided 12 Oct 2026 (Q30): the Venue Staff member who last changed a hold's
    expiry, named beside the reason on the request and on the event's booking list. Read from the
    booking's ``hold_expiry_changed_by`` row, so ``BookingOut`` needs no constructor of its own."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str


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
    # Story 12.7 AC1: when an approved booking's hold expires unless its event is confirmed first,
    # and the moment it expired once EXPIRED; None while pending. AC4: when the event's
    # confirmation completed it; None while it is open.
    hold_expires_at: datetime | None
    hold_completed_at: datetime | None
    # Story 12.7 AC7, decided 12 Oct 2026 (Q30): the latest change to that expiry - why, by whom
    # and when; all None until Venue Staff make one.
    hold_expiry_change_reason: str | None
    hold_expiry_changed_by: HoldExpiryChangedBy | None
    hold_expiry_changed_at: datetime | None
    # Story 9.4 AC3: when the booking was marked "Venue unavailable - alternative needed"; None
    # when unmarked, and always None once the booking is no longer pending or approved.
    venue_unavailable_marked_at: datetime | None = Field(validation_alias="venue_unavailable_mark")
    # Story 12.6 AC2/AC3: the booking this one replaces and the one that replaced it, and what
    # Venue Staff read before approving a replacement (AC3, AC6): the venue replaced, the venue
    # approval will release - only while it still holds its venue - and whether the original is
    # still marked. All None for a booking that replaces and is replaced by nothing.
    replaces_booking_id: uuid.UUID | None
    replaced_by_booking_id: uuid.UUID | None
    replaces_venue_name: str | None
    approval_releases_venue_name: str | None
    original_is_marked: bool | None
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
    request. f12.1.2 (story 12.1 AC17): the setup and teardown, the booked period and the venue's
    opening hours, so the card can say when the setup or teardown runs outside them. No defaults
    (response schema)."""

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
    # Story 12.7 AC1: when an approved booking's hold expires, or an expired one's did, and when
    # the event's confirmation completed it; R14: the booked start, which the Approve dialog's
    # expiry may not pass (AC5).
    hold_expires_at: datetime | None
    hold_completed_at: datetime | None
    held_from: datetime
    # f12.1.2 (story 12.1 AC17): what the card needs to say whether the setup or teardown runs
    # outside the venue's opening hours, which Venue Staff weigh when approving (13.2; Q51), and
    # to name the booked period; the hours are None when the venue has none recorded.
    setup_minutes: int
    teardown_minutes: int
    held_until: datetime
    venue_operating_hours_start: time | None
    venue_operating_hours_end: time | None
    # Story 9.4 AC3: the mark, for Venue Staff deciding the request (AC7); None when unmarked.
    venue_unavailable_marked_at: datetime | None
    # Story 12.6 AC3, AC6: for a replacement, the venue it replaces, the venue approving it will
    # release (only while that booking still holds its venue) and whether the original is still
    # marked; None for any other request.
    replaces_venue_name: str | None
    approval_releases_venue_name: str | None
    original_is_marked: bool | None
    # Story 12.6 AC3: when a released original was released - its replacement's approval, shown as
    # "Closed at" in place of its own earlier approval; None for any other request.
    released_at: datetime | None

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
            hold_expires_at=booking.hold_expires_at,
            hold_completed_at=booking.hold_completed_at,
            held_from=booking.held_from,
            setup_minutes=booking.setup_minutes,
            teardown_minutes=booking.teardown_minutes,
            held_until=booking.held_until,
            venue_operating_hours_start=booking.venue.operating_hours_start,
            venue_operating_hours_end=booking.venue.operating_hours_end,
            venue_unavailable_marked_at=booking.venue_unavailable_mark,
            replaces_venue_name=booking.replaces_venue_name,
            approval_releases_venue_name=booking.approval_releases_venue_name,
            original_is_marked=booking.original_is_marked,
            released_at=booking.released_at,
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
    # Story 12.7 AC3: approved bookings whose hold lapsed before their event was confirmed.
    expired: int

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
    # Story 12.7 AC1/AC8: when an approved booking's hold expires, and when it expired once
    # EXPIRED; AC4: when the event's confirmation completed it.
    hold_expires_at: datetime | None
    hold_completed_at: datetime | None
    # Story 12.7 AC7, decided 12 Oct 2026 (Q30): the latest change to that expiry - why, by whom
    # and when - for the coordinator's card on the event page; all None until one is made.
    hold_expiry_change_reason: str | None
    hold_expiry_changed_by: HoldExpiryChangedBy | None
    hold_expiry_changed_at: datetime | None
    # Story 9.4 AC3: when the booking was marked "Venue unavailable - alternative needed", for
    # the event page; None when unmarked, and always None once the booking is closed.
    venue_unavailable_marked_at: datetime | None
    # Story 12.6 AC2-AC4: the booking this one replaces and the one that replaced it, and their
    # venues, for the event page: "Replaces <venue>" on a replacement, "Replaced by <venue>" on an
    # original released by an approved one (never for a replacement that was not approved, AC8),
    # and "Replacement requested: <venue>" on an original while one is pending.
    replaces_booking_id: uuid.UUID | None
    replaced_by_booking_id: uuid.UUID | None
    replaces_venue_name: str | None
    replaced_by_venue_name: str | None
    pending_replacement_venue_name: str | None
    # Story 12.6 AC3: when the original was released - its replacement's approval - which the card
    # shows as "Closed at" rather than the original's own, earlier approval; None otherwise.
    released_at: datetime | None

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
            hold_expires_at=booking.hold_expires_at,
            hold_completed_at=booking.hold_completed_at,
            hold_expiry_change_reason=booking.hold_expiry_change_reason,
            hold_expiry_changed_by=(
                None
                if booking.hold_expiry_changed_by is None
                else HoldExpiryChangedBy.model_validate(booking.hold_expiry_changed_by)
            ),
            hold_expiry_changed_at=booking.hold_expiry_changed_at,
            venue_unavailable_marked_at=booking.venue_unavailable_mark,
            replaces_booking_id=booking.replaces_booking_id,
            replaced_by_booking_id=booking.replaced_by_booking_id,
            replaces_venue_name=booking.replaces_venue_name,
            replaced_by_venue_name=booking.replaced_by_venue_name,
            pending_replacement_venue_name=booking.pending_replacement_venue_name,
            released_at=booking.released_at,
        )
