"""Request and response shapes for event change requests (story 19.1), their decisions (story
19.2), and the impact approving one would have (story 19.3).

A change request names one field and the value proposed for it. The body is a union tagged by
``field``, so each field's value is checked by the very types story 2.1/2.7 use when a request is
created - ``ExpectedAttendance``, ``VenueRequirementIn``, ``EventEquipmentIn`` - rather than by
rules of its own (19.1 AC4). An unknown ``field`` matches no member and is refused with a 422.

The impact (story 19.3) lists each booking, equipment item and the registrations the approval
would touch, with what it does to each, and a fingerprint the approval sends back (AC7).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.change_requests.models import EventChangeRequest
from app.events.schemas import (
    DUPLICATE_ENTRY_MESSAGE,
    DUPLICATE_EQUIPMENT_MESSAGE,
    MAX_VENUE_REQUIREMENTS,
    EventEquipmentIn,
    ExpectedAttendance,
    VenueRequirementIn,
)
from app.venues.schemas import FailedCriterionOut

# AC4: a reason is mandatory; the ceiling matches a clarification message's (story 4.2).
CHANGE_REASON_MAX_LENGTH = 2000


def _has_duplicates(values: list[Any]) -> bool:
    return len(values) != len(set(values))


class _ChangeRequestIn(BaseModel):
    """AC4: every change request carries a reason; blank or whitespace-only does not count."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=CHANGE_REASON_MAX_LENGTH)

    @field_validator("reason", mode="before")
    @classmethod
    def _strip_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProposedSchedule(BaseModel):
    """The event's new start and end, requested together so "end after start" can always be
    judged (PO decision, Checkpoint 1). The 2.1 AC2 date rules are checked in the service, which
    knows the current time."""

    model_config = ConfigDict(extra="forbid")

    starts_at: AwareDatetime
    ends_at: AwareDatetime


class ScheduleChangeIn(_ChangeRequestIn):
    field: Literal["schedule"]
    proposed: ProposedSchedule


class AttendanceChangeIn(_ChangeRequestIn):
    field: Literal["expected_attendance"]
    proposed: ExpectedAttendance


class VenueRequirementsChangeIn(_ChangeRequestIn):
    """The whole list of venue requirements the event should have, as on the 2.7 form."""

    field: Literal["venue_requirements"]
    proposed: list[VenueRequirementIn] = Field(max_length=MAX_VENUE_REQUIREMENTS)

    @model_validator(mode="after")
    def _check_ids(self):
        if _has_duplicates([item.id for item in self.proposed if item.id is not None]):
            raise ValueError(DUPLICATE_ENTRY_MESSAGE)
        return self


class EquipmentChangeIn(_ChangeRequestIn):
    """The whole list of equipment the event should have, each type once (2.1 AC6)."""

    field: Literal["equipment"]
    proposed: list[EventEquipmentIn]

    @model_validator(mode="after")
    def _check_types(self):
        if _has_duplicates([item.equipment_type_code for item in self.proposed]):
            raise ValueError(DUPLICATE_EQUIPMENT_MESSAGE)
        return self


ChangeRequestIn = Annotated[
    ScheduleChangeIn | AttendanceChangeIn | VenueRequirementsChangeIn | EquipmentChangeIn,
    Field(discriminator="field"),
]


class ChangeRequestRejectionIn(_ChangeRequestIn):
    """Story 19.2 AC3/AC4: rejecting needs a reason, trimmed, and blank or whitespace-only does
    not count - the same rule, and the same ceiling, as the organiser's reason for asking."""


def _change_request_fields(request: EventChangeRequest, *, is_out_of_date: bool) -> dict[str, Any]:
    """Every ``ChangeRequestOut`` field of ``request``, so the queue entry repeats none of them."""
    return {
        "id": request.id,
        "event_id": request.event_id,
        "field": request.field_name,
        "current_value": (
            None if request.current_value is None else json.loads(request.current_value)
        ),
        "proposed_value": json.loads(request.proposed_value),
        "reason": request.reason,
        "status": request.status,
        "requested_by_id": request.requested_by_id,
        "requested_by_name": request.requested_by.full_name,
        "decided_by_id": request.decided_by_id,
        "decided_by_name": None if request.decided_by is None else request.decided_by.full_name,
        "decided_at": request.decided_at,
        "decision_reason": request.decision_reason,
        "is_out_of_date": is_out_of_date,
        "created_at": request.created_at,
        "updated_at": request.updated_at,
    }


class ChangeRequestOut(BaseModel):
    """AC1: a change request as the organiser and the assigned coordinator see it. The values are
    returned as JSON, in the same canonical shape they are stored in (see the service). Story 19.2
    AC2/AC3: once decided, who decided, when, and the reason for a rejection; all None while it
    waits or once withdrawn. AC7: ``is_out_of_date`` when it waits but the event no longer has the
    value it recorded as current, so it can only be rejected (the service decides it)."""

    id: uuid.UUID
    event_id: uuid.UUID
    field: str
    current_value: Any
    proposed_value: Any
    reason: str
    status: str
    requested_by_id: uuid.UUID
    requested_by_name: str
    decided_by_id: uuid.UUID | None
    decided_by_name: str | None
    decided_at: datetime | None
    decision_reason: str | None
    is_out_of_date: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_change_request(
        cls, request: EventChangeRequest, *, is_out_of_date: bool
    ) -> ChangeRequestOut:
        return cls(**_change_request_fields(request, is_out_of_date=is_out_of_date))


class ChangeRequestQueueEntryOut(ChangeRequestOut):
    """Story 19.2 AC1: a change request in the coordinator's queue - pending, or in their record of
    decisions - with the event it is for, so the queue reads without opening each event."""

    event_name: str
    event_status: str
    event_starts_at: datetime | None
    event_ends_at: datetime | None

    @classmethod
    def from_queued_request(
        cls, request: EventChangeRequest, *, is_out_of_date: bool
    ) -> ChangeRequestQueueEntryOut:
        event = request.event
        return cls(
            **_change_request_fields(request, is_out_of_date=is_out_of_date),
            event_name=event.name,
            event_status=event.status,
            event_starts_at=event.starts_at,
            event_ends_at=event.ends_at,
        )


# --- story 19.3: the impact of a change request ------------------------------------------------

# AC7: the longest fingerprint taken back - a sha256 hex digest is 64 characters.
_FINGERPRINT_MAX_LENGTH = 128


class ChangeRequestApprovalIn(BaseModel):
    """Story 19.3 AC7: approving sends back the fingerprint of the assessment the coordinator
    saw, so an approval re-assessed under the event's lock is refused when it has changed."""

    model_config = ConfigDict(extra="forbid")

    assessment_fingerprint: str = Field(min_length=1, max_length=_FINGERPRINT_MAX_LENGTH)


class CapacityWarningOut(BaseModel):
    """AC1/AC4: the booked venue holds fewer people than the change needs it to - in the booked
    layout's capacity where the venue records one (``layout_name``), else its maximum (story 11.1
    AC4). A warning only: whether the booking is cancelled is ``will_be_cancelled``'s."""

    people_needed: int
    venue_capacity: int
    layout_name: str | None


class HoldingBookingOut(BaseModel):
    """AC4/AC5: another booking holding the venue over part of the period a replacement would
    need, setup and teardown included."""

    event_name: str
    held_from: datetime
    held_until: datetime


class ClosureOut(BaseModel):
    """AC5: a period the venue is unavailable for (story 9.4) over part of that period."""

    reason: str
    notes: str | None
    starts_at: datetime
    ends_at: datetime


class CountedVenueOut(BaseModel):
    """One booked venue counted towards a ``ShortPeriodOut``: how many it holds, in the booked
    layout (``layout_name``) where the venue records that layout's capacity (story 11.1 AC4).
    Each venue is counted once, however many of the event's requirements it is booked for."""

    venue_id: uuid.UUID
    venue_name: str
    capacity: int
    layout_name: str | None


class ShortPeriodOut(BaseModel):
    """AC1/AC4: a stretch of the event when the venues in use (``venues``) hold ``capacity``
    people between them, ``shortfall`` fewer than the proposed attendance."""

    starts_at: datetime
    ends_at: datetime
    capacity: int
    shortfall: int
    venues: list[CountedVenueOut]


class CapacityShortfallOut(BaseModel):
    """AC1/AC4 (decided 19 Oct 2026): an attendance change asks for more people than the venues
    still booked after approval hold, at some moments, between the ones in use then - the bookings
    it cancels hold nobody. ``periods`` are those moments, in order. A warning only: no booking is
    cancelled for it."""

    proposed_attendance: int
    periods: list[ShortPeriodOut]


class BookingImpactOut(BaseModel):
    """AC1/AC2: one venue booking the change affects - one 19.2 would cancel (``reasons`` say
    why), or one it keeps whose venue cannot hold the people now needed (``capacity_warning``) or
    lacks a facility its requirement would newly need (``facility_warnings``, story 11.1's
    failures). A warning never means the booking is cancelled: only ``will_be_cancelled`` says
    that. ``requirement_name`` is None for an additional venue (12.5), which is never judged on
    facilities (11.1 AC5). For a cancelled booking whose requirement remains,
    ``needed_starts_at``..``needed_ends_at`` is the period a replacement needs, and ``held_by``,
    ``closure`` and ``is_outside_opening_hours`` say whether the same venue is free for it.
    ``after_approval`` says what the approval does to it."""

    booking_id: uuid.UUID
    venue_id: uuid.UUID
    venue_name: str
    requirement_name: str | None
    status: str
    starts_at: datetime
    ends_at: datetime
    will_be_cancelled: bool
    reasons: list[str]
    capacity_warning: CapacityWarningOut | None
    facility_warnings: list[FailedCriterionOut]
    needed_starts_at: datetime | None
    needed_ends_at: datetime | None
    held_by: HoldingBookingOut | None
    closure: ClosureOut | None
    is_outside_opening_hours: bool
    after_approval: str


class EquipmentImpactOut(BaseModel):
    """AC1/AC2/AC5: one equipment item the change affects: ``removed``, ``changed`` or ``added``
    by an equipment change, or ``rechecked`` for new dates. ``item_id`` is None for an added one;
    ``required``/``available`` are None for a removed one, which needs nothing. ``status_after``
    is the item's status once approved (None: deleted), as 19.2 sets it."""

    item_id: uuid.UUID | None
    equipment_type_code: str
    equipment_type_name: str
    change: Literal["removed", "changed", "added", "rechecked"]
    current_status: str | None
    required: int | None
    available: int | None
    shortfall: int
    status_after: str | None
    technical_support_told: bool
    after_approval: str


class RegistrationImpactOut(BaseModel):
    """AC1: the attendees' registrations the change affects, counted, never named. ``over_by``
    is how many more are registered than a lowered attendance allows (0 when none);
    ``proposed_attendance`` is None unless the attendance is what changes."""

    active_count: int
    proposed_attendance: int | None
    over_by: int
    dates_change: bool


class ChangeRequestImpactOut(BaseModel):
    """Story 19.3: what approving a pending change request would affect, worked out from the
    records as they stand (AC3). ``capacity_shortfall`` when an attendance change outgrows the
    venues booked (AC1). ``refused_because`` when 19.2 would refuse the approval - nothing else
    is predicted then; ``is_out_of_date`` when it can only be rejected (19.2 AC7).
    ``fingerprint`` identifies everything else here, so an approval can tell whether it still
    holds (AC7)."""

    change_request_id: uuid.UUID
    assessed_at: datetime
    fingerprint: str
    is_out_of_date: bool
    refused_because: str | None
    venue_bookings: list[BookingImpactOut]
    equipment: list[EquipmentImpactOut]
    registrations: RegistrationImpactOut | None
    capacity_shortfall: CapacityShortfallOut | None
    has_impact: bool
