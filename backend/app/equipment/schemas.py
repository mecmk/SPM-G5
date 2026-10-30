"""Request and response models for an event's equipment items (story 15.1), Technical Support's
queue of them (story 15.2) and Technical Support's decision on each (story 16.1).

An item in a 15.1 response is ``EquipmentLineOut`` from ``app/events/schemas.py``, the shape the
event page already reads, so an item looks the same whichever of those endpoints returns it.

Story 16.2: an equipment type's units out of service - a record as Technical Support sends it and
as the type's page shows it, the catalogue, and the holds a record leaves short.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.events.models import (
    EquipmentRequestStatus,
    EquipmentUnavailabilityPeriod,
    Event,
    EventEquipmentRequest,
)
from app.events.schemas import PositiveWholeNumber

if TYPE_CHECKING:
    from app.equipment.service import CatalogueEntry, ShortHold, TypePage

# Story 15.1 AC5: the longest technical note, counted once surrounding spaces are trimmed. Keep in
# step with the frontend's TECHNICAL_NOTES_MAX_LENGTH.
TECHNICAL_NOTES_MAX_LENGTH = 1000
QUANTITY_REQUIRED_MESSAGE = "Enter a quantity of at least 1."
# Story 16.1 AC4. The frontend's EQUIPMENT_REASON_REQUIRED says the same before anything is sent.
DECLINE_REASON_REQUIRED_MESSAGE = "Enter a reason for declining this request."
ACCEPT_REASON_REFUSED_MESSAGE = "Give a reason only when declining a request."


def _trimmed_or_none(value: Any) -> Any:
    """AC5: spaces around a note are dropped, and a note of nothing but spaces is no note. Anything
    other than text is left for the field's own type check to refuse."""
    if isinstance(value, str):
        return value.strip() or None
    return value


class EquipmentItemIn(BaseModel):
    """AC1: a new item - its type, its quantity (AC4) and optional technical notes (AC5). The
    status is never the client's to set (AC7), so any other field is refused."""

    model_config = ConfigDict(extra="forbid")

    equipment_type_code: str = Field(min_length=1)
    quantity: PositiveWholeNumber
    technical_notes: str | None = Field(default=None, max_length=TECHNICAL_NOTES_MAX_LENGTH)

    @field_validator("technical_notes", mode="before")
    @classmethod
    def _normalize_notes(cls, value: Any) -> Any:
        return _trimmed_or_none(value)


class EquipmentItemUpdate(BaseModel):
    """AC2: a partial edit of an item - its quantity, its notes, or both. A field left out keeps its
    value, and ``technical_notes: null`` clears the notes. The type cannot change (remove the item
    and add the other type) and the status is never the client's to set, so any other field is
    refused."""

    model_config = ConfigDict(extra="forbid")

    quantity: PositiveWholeNumber | None = None
    technical_notes: str | None = Field(default=None, max_length=TECHNICAL_NOTES_MAX_LENGTH)

    @field_validator("technical_notes", mode="before")
    @classmethod
    def _normalize_notes(cls, value: Any) -> Any:
        return _trimmed_or_none(value)

    @model_validator(mode="after")
    def _quantity_is_not_cleared(self) -> EquipmentItemUpdate:
        """AC4: an item always has a quantity, so one sent as null is refused, not ignored."""
        if "quantity" in self.model_fields_set and self.quantity is None:
            raise ValueError(QUANTITY_REQUIRED_MESSAGE)
        return self


class EventEquipmentAvailabilityOut(BaseModel):
    """AC3: how many units of one active type an event can have over its period, counting what it
    already holds - the figure the form shows next to the type. No defaults (response schema)."""

    equipment_type_code: str
    equipment_type_name: str
    available: int


class EquipmentQueueStatus(StrEnum):
    """Story 15.2 AC3: the statuses Technical Support's queue has a tab for. Story 6.2 AC15:
    Cancelled, read-only, for the items once sent to them. Any other item status is not a tab, so
    asking for one is a 422 rather than an empty list."""

    PENDING = EquipmentRequestStatus.PENDING
    ACCEPTED = EquipmentRequestStatus.ACCEPTED
    DECLINED = EquipmentRequestStatus.DECLINED
    CANCELLED = EquipmentRequestStatus.CANCELLED


class EquipmentQueueOrder(StrEnum):
    """Story 13.3 AC3: the orders the equipment queue offers - its event's date, soonest (the
    default) or latest first; when it was sent to Technical Support, oldest or newest first; its
    event's name and its equipment type's name, A to Z. AC5: any other is a 422."""

    DATE = "date"
    DATE_DESC = "date_desc"
    REQUESTED = "requested"
    REQUESTED_DESC = "requested_desc"
    EVENT_NAME = "event_name"
    EQUIPMENT_TYPE = "equipment_type"


class EquipmentDecisionOutcome(StrEnum):
    """Story 16.1 AC1/AC2: what Technical Support may decide. Anything else is a 422."""

    ACCEPTED = EquipmentRequestStatus.ACCEPTED
    DECLINED = EquipmentRequestStatus.DECLINED


class EquipmentDecisionIn(BaseModel):
    """Story 16.1: Technical Support's decision on one request. AC4: declining needs a reason,
    counted once surrounding spaces are trimmed; accepting takes none, so a reason sent with it is
    refused rather than dropped."""

    model_config = ConfigDict(extra="forbid")

    outcome: EquipmentDecisionOutcome
    reason: str | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def _normalize_reason(cls, value: Any) -> Any:
        return _trimmed_or_none(value)

    @model_validator(mode="after")
    def _reason_matches_outcome(self) -> EquipmentDecisionIn:
        if self.outcome == EquipmentDecisionOutcome.DECLINED and self.reason is None:
            raise ValueError(DECLINE_REASON_REQUIRED_MESSAGE)
        if self.outcome == EquipmentDecisionOutcome.ACCEPTED and self.reason is not None:
            raise ValueError(ACCEPT_REASON_REFUSED_MESSAGE)
        return self


class EquipmentQueueEntry(BaseModel):
    """Story 15.2 AC1: the event's name and dates, the item's type, quantity and technical notes,
    and who sent it and when - ``None`` when that was never recorded (an item sent before
    migration 014).
    AC2: ``available`` for the event's period, not counting the event's own hold, and
    ``shortfall``, how many more were requested than that. Story 16.1 AC2/AC3: who decided it and
    when, and the reason for declining - each ``None`` until decided, and for items decided
    before migration 016. No defaults (response schema)."""

    id: uuid.UUID
    event_id: uuid.UUID
    event_name: str
    starts_at: datetime
    ends_at: datetime
    equipment_type_code: str
    equipment_type_name: str
    quantity: int
    technical_notes: str | None
    requested_by_name: str | None
    submitted_at: datetime | None
    status: EquipmentQueueStatus
    # Story 6.2 AC15: None for a cancelled request, which holds nothing.
    available: int | None
    shortfall: int | None
    decided_by_name: str | None
    decided_at: datetime | None
    decision_reason: str | None
    # Story 6.2 AC16: when a cancelled item was cancelled; None otherwise, and for one cancelled
    # before migration 026.
    cancelled_at: datetime | None

    @classmethod
    def from_item(
        cls, item: EventEquipmentRequest, event: Event, *, available: int | None
    ) -> EquipmentQueueEntry:
        return cls(
            id=item.id,
            event_id=event.id,
            event_name=event.name,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            equipment_type_code=item.equipment_type.code,
            equipment_type_name=item.equipment_type.name,
            quantity=item.quantity,
            technical_notes=item.technical_notes,
            requested_by_name=None if item.submitted_by is None else item.submitted_by.full_name,
            submitted_at=item.submitted_at,
            status=EquipmentQueueStatus(item.status),
            available=available,
            shortfall=None if available is None else max(0, item.quantity - available),
            decided_by_name=None if item.decided_by is None else item.decided_by.full_name,
            decided_at=item.decided_at,
            decision_reason=item.status_notes,
            cancelled_at=item.cancelled_at,
        )


class EquipmentQueueCounts(BaseModel):
    """Story 15.2 AC3: how many requests each tab holds, for the tab labels. No defaults
    (response schema). ``extra="forbid"`` makes ``from_counts`` refuse a tab with no field."""

    model_config = ConfigDict(extra="forbid")

    pending: int
    accepted: int
    declined: int
    # Story 6.2 AC15.
    cancelled: int

    @classmethod
    def from_counts(cls, by_status: Mapping[str, int]) -> EquipmentQueueCounts:
        return cls(**{status.lower(): by_status.get(status, 0) for status in EquipmentQueueStatus})


class EquipmentQueue(BaseModel):
    """Story 15.2 AC1-AC3: one tab of the queue, soonest event first, and every tab's count."""

    items: list[EquipmentQueueEntry]
    counts: EquipmentQueueCounts


# =============================================================================================
# Story 16.2: units of an equipment type out of service
# =============================================================================================
OUT_OF_SERVICE_NOTES_MAX_LENGTH = 1000
OUT_OF_SERVICE_QUANTITY_MESSAGE = "Enter a whole number of at least 1."
OUT_OF_SERVICE_NOTES_TOO_LONG_MESSAGE = "The note must be 1,000 characters or fewer."
OUT_OF_SERVICE_END_NOT_AFTER_START_MESSAGE = "The end must be after the start."
# Story 16.2 AC1: why units are out of service - the four values
# ck_equipment_unavailability_reason allows. Mirrored by frontend/src/api/equipment.ts.
OutOfServiceReason = Literal["DAMAGED", "MAINTENANCE", "LOST", "OTHER"]


def _at_least_one(quantity: int) -> int:
    """Story 16.2 AC3: a whole number of units, at least 1 (the most is the stock's to say)."""
    if quantity < 1:
        raise ValueError(OUT_OF_SERVICE_QUANTITY_MESSAGE)
    return quantity


def _note(notes: object) -> object:
    """Story 16.2 AC1: a note without the spaces around it; blank is no note."""
    return notes.strip() or None if isinstance(notes, str) else notes


def _note_within_limit(notes: str | None) -> str | None:
    """Story 16.2 AC1: at most 1,000 characters, counted once trimmed."""
    if notes is not None and len(notes) > OUT_OF_SERVICE_NOTES_MAX_LENGTH:
        raise ValueError(OUT_OF_SERVICE_NOTES_TOO_LONG_MESSAGE)
    return notes


def _end_after_start(starts_at: datetime | None, ends_at: datetime | None) -> None:
    """Story 16.2 AC3: the end, if there is one, after the start."""
    if starts_at is not None and ends_at is not None and ends_at <= starts_at:
        raise ValueError(OUT_OF_SERVICE_END_NOT_AFTER_START_MESSAGE)


class OutOfServiceIn(BaseModel):
    """Story 16.2 AC1/AC3: units of an equipment type out of service, as Technical Support records
    them - how many, why, an optional note, from when and, optionally, until when (None: until
    ended). Times carry their zone. Whether the start is in the past, and how many units the
    period can spare, are the server's to judge when it saves. ``extra="forbid"``: nothing else
    can be sent, not even the type, which is the record's path."""

    model_config = ConfigDict(extra="forbid")

    quantity: int
    reason: OutOfServiceReason
    notes: str | None = None
    starts_at: AwareDatetime
    ends_at: AwareDatetime | None = None

    _check_quantity = field_validator("quantity")(_at_least_one)
    _trim_notes = field_validator("notes", mode="before")(_note)
    _check_notes = field_validator("notes")(_note_within_limit)

    @model_validator(mode="after")
    def _check_period(self) -> OutOfServiceIn:
        _end_after_start(self.starts_at, self.ends_at)
        return self


class OutOfServiceUpdate(BaseModel):
    """Story 16.2 AC2: an edit of a record - only the fields sent change, each by AC1/AC3's rules -
    or, with ``end_now``, the end of one in force at the server's now. A quantity, reason or start
    sent as null is refused; an end sent as null leaves the record out until ended. An end before
    a start sent with it is refused here; against the record's own start, by the server."""

    model_config = ConfigDict(extra="forbid")

    quantity: int = None  # type: ignore[assignment]
    reason: OutOfServiceReason = None  # type: ignore[assignment]
    notes: str | None = None
    starts_at: AwareDatetime = None  # type: ignore[assignment]
    ends_at: AwareDatetime | None = None
    end_now: bool = False

    _check_quantity = field_validator("quantity")(_at_least_one)
    _trim_notes = field_validator("notes", mode="before")(_note)
    _check_notes = field_validator("notes")(_note_within_limit)

    @model_validator(mode="after")
    def _check_period(self) -> OutOfServiceUpdate:
        _end_after_start(self.starts_at, self.ends_at)
        return self


class OutOfServiceOut(BaseModel):
    """Story 16.2 AC2: one record, as the type's page lists it. No defaults (response schema)."""

    id: uuid.UUID
    quantity: int
    reason: str
    notes: str | None
    starts_at: datetime
    ends_at: datetime | None

    @classmethod
    def from_record(cls, record: EquipmentUnavailabilityPeriod) -> OutOfServiceOut:
        return cls(
            id=record.id,
            quantity=record.quantity,
            reason=record.reason,
            notes=record.notes,
            starts_at=record.starts_at,
            ends_at=record.ends_at,
        )


class EquipmentCatalogueEntryOut(BaseModel):
    """Story 16.2 AC2: one type in the catalogue - its stock and the units out of service now.
    No defaults (response schema)."""

    id: uuid.UUID
    code: str
    name: str
    total_quantity: int
    out_of_service_now: int

    @classmethod
    def from_entry(cls, entry: CatalogueEntry) -> EquipmentCatalogueEntryOut:
        kind = entry.equipment_type
        return cls(
            id=kind.id,
            code=kind.code,
            name=kind.name,
            total_quantity=kind.total_quantity,
            out_of_service_now=entry.out_of_service_now,
        )


class EquipmentTypePageOut(EquipmentCatalogueEntryOut):
    """Story 16.2 AC2: one type's page - what the catalogue shows of it, its description and where
    it is kept, and its current records, soonest first. No defaults (response schema)."""

    description: str | None
    storage_location: str | None
    records: list[OutOfServiceOut]

    @classmethod
    def from_page(cls, page: TypePage) -> EquipmentTypePageOut:
        kind = page.equipment_type
        return cls(
            id=kind.id,
            code=kind.code,
            name=kind.name,
            total_quantity=kind.total_quantity,
            out_of_service_now=page.out_of_service_now,
            description=kind.description,
            storage_location=kind.storage_location,
            records=[OutOfServiceOut.from_record(record) for record in page.records],
        )


class ShortHoldOut(BaseModel):
    """Story 16.2 AC4/AC5: a hold a record leaves short - its event, the event's coordinator (None
    while it has none), the units it still holds and how many of those it cannot have, and its
    period. No defaults (response schema)."""

    event_id: uuid.UUID
    event_name: str
    coordinator_name: str | None
    units_held: int
    units_short: int
    starts_at: datetime
    ends_at: datetime

    @classmethod
    def from_short(cls, short: ShortHold) -> ShortHoldOut:
        coordinator = short.event.assigned_coordinator
        return cls(
            event_id=short.event.id,
            event_name=short.event.name,
            coordinator_name=None if coordinator is None else coordinator.full_name,
            units_held=short.units_held,
            units_short=short.units_short,
            starts_at=short.hold.starts_at,
            ends_at=short.hold.ends_at,
        )


class OutOfServiceCheckOut(BaseModel):
    """Story 16.2 AC5: the holds a record would leave short, soonest first, for Technical Support
    to see before saving. No defaults (response schema)."""

    short_holds: list[ShortHoldOut]


class EquipmentShortageOut(BaseModel):
    """Story 16.2 AC4: an event's item that units out of service leave short, and by how many,
    for its equipment list. No defaults (response schema)."""

    item_id: uuid.UUID
    units_short: int
