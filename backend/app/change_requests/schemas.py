"""Request and response shapes for event change requests (story 19.1), and their decisions (story
19.2).

A change request names one field and the value proposed for it. The body is a union tagged by
``field``, so each field's value is checked by the very types story 2.1/2.7 use when a request is
created - ``PositiveWholeNumber``, ``VenueRequirementIn``, ``EventEquipmentIn`` - rather than by
rules of its own (19.1 AC4). An unknown ``field`` matches no member and is refused with a 422.
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
    PositiveWholeNumber,
    VenueRequirementIn,
)

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
    proposed: PositiveWholeNumber


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


def _change_request_fields(request: EventChangeRequest) -> dict[str, Any]:
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
        "created_at": request.created_at,
        "updated_at": request.updated_at,
    }


class ChangeRequestOut(BaseModel):
    """AC1: a change request as the organiser and the assigned coordinator see it. The values are
    returned as JSON, in the same canonical shape they are stored in (see the service). Story 19.2
    AC2/AC3: once decided, who decided, when, and the reason for a rejection; all None while it
    waits or once withdrawn."""

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
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_change_request(cls, request: EventChangeRequest) -> ChangeRequestOut:
        return cls(**_change_request_fields(request))


class ChangeRequestQueueEntryOut(ChangeRequestOut):
    """Story 19.2 AC1: a pending change request in the coordinator's queue, with the event it is
    for, so the queue reads without opening each event."""

    event_name: str
    event_status: str
    event_starts_at: datetime | None
    event_ends_at: datetime | None

    @classmethod
    def from_queued_request(cls, request: EventChangeRequest) -> ChangeRequestQueueEntryOut:
        event = request.event
        return cls(
            **_change_request_fields(request),
            event_name=event.name,
            event_status=event.status,
            event_starts_at=event.starts_at,
            event_ends_at=event.ends_at,
        )
