"""Request and response models for an event's equipment items (story 15.1) and Technical
Support's queue of them (story 15.2).

An item in a 15.1 response is ``EquipmentLineOut`` from ``app/events/schemas.py``, the shape the
event page already reads, so an item looks the same whichever of those endpoints returns it.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.events.models import EquipmentRequestStatus, Event, EventEquipmentRequest
from app.events.schemas import PositiveWholeNumber

# Story 15.1 AC5: the longest technical note, counted once surrounding spaces are trimmed. Keep in
# step with the frontend's TECHNICAL_NOTES_MAX_LENGTH.
TECHNICAL_NOTES_MAX_LENGTH = 1000
QUANTITY_REQUIRED_MESSAGE = "Enter a quantity of at least 1."


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
    """Story 15.2 AC3: the statuses Technical Support's queue has a tab for. Any other item status
    is not a tab, so asking for one is a 422 rather than an empty list."""

    PENDING = EquipmentRequestStatus.PENDING
    ACCEPTED = EquipmentRequestStatus.ACCEPTED
    DECLINED = EquipmentRequestStatus.DECLINED


class EquipmentQueueEntry(BaseModel):
    """Story 15.2 AC1: the event's name and dates, the item's type, quantity and technical notes,
    and who sent it - ``None`` when that was never recorded (an item sent before migration 014).
    AC2: ``available`` for the event's period, not counting the event's own hold, and
    ``shortfall``, how many more were requested than that. No defaults (response schema)."""

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
    status: EquipmentQueueStatus
    available: int
    shortfall: int

    @classmethod
    def from_item(
        cls, item: EventEquipmentRequest, event: Event, *, available: int
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
            status=EquipmentQueueStatus(item.status),
            available=available,
            shortfall=max(0, item.quantity - available),
        )


class EquipmentQueueCounts(BaseModel):
    """Story 15.2 AC3: how many requests each tab holds, for the tab labels. No defaults
    (response schema). ``extra="forbid"`` makes ``from_counts`` refuse a tab with no field."""

    model_config = ConfigDict(extra="forbid")

    pending: int
    accepted: int
    declined: int

    @classmethod
    def from_counts(cls, by_status: Mapping[str, int]) -> EquipmentQueueCounts:
        return cls(**{status.lower(): by_status.get(status, 0) for status in EquipmentQueueStatus})


class EquipmentQueue(BaseModel):
    """Story 15.2 AC1-AC3: one tab of the queue, soonest event first, and every tab's count."""

    items: list[EquipmentQueueEntry]
    counts: EquipmentQueueCounts
