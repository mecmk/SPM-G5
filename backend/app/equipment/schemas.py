"""Request and response models for an event's equipment items (story 15.1).

An item in a response is ``EquipmentLineOut`` from ``app/events/schemas.py``, the shape the event
page already reads, so an item looks the same whichever endpoint returns it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
