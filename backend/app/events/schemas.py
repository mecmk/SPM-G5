"""Request and response shapes for event requests (story 2.1), the organiser's own list of
them (story 2.6), the review queue (story 4.1), and the approve/reject decision (stories 4.4,
4.5)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from app.auth.models import User
from app.auth.permissions import Permission, role_has
from app.events.models import Event, EventEquipmentRequest

# "Positive whole numbers only" (story 2.1 AC3): StrictInt rejects 1.5, "20" and true; gt=0
# rejects 0 and below; the ceiling is the largest value the INTEGER columns can hold.
_INT32_MAX = 2_147_483_647
PositiveWholeNumber = Annotated[StrictInt, Field(gt=0, le=_INT32_MAX)]

ACCESSIBILITY_CONTRADICTION_MESSAGE = (
    "Accessibility cannot be marked none required while needs or notes are recorded."
)
VENUE_CONTRADICTION_MESSAGE = (
    "Venue requirements cannot be marked none required while a layout, facilities or notes are "
    "recorded."
)
DUPLICATE_EQUIPMENT_MESSAGE = "Each equipment type can appear only once on a request."
DUPLICATE_ENTRY_MESSAGE = "Each option can be chosen only once."
CANNOT_BE_REMOVED_MESSAGE = "This field cannot be removed; send a value or leave it out."


# --- review queue (story 4.1) --------------------------------------------------------------
class ReviewQueueSort(StrEnum):
    """AC3: order by submission date (default) or proposed event date."""

    SUBMITTED_AT = "submitted_at"
    STARTS_AT = "starts_at"


class ReviewQueueEntry(BaseModel):
    """AC2: name, organiser, proposed date, submission date, and the optional picture.
    No defaults (response schema)."""

    id: uuid.UUID
    name: str
    organiser_name: str
    starts_at: datetime  # non-null for every non-DRAFT row (ck_events_submitted_fields_complete)
    ends_at: datetime
    submitted_at: datetime | None  # not covered by that CHECK, so honest about NULL
    status: str
    cover_image_url: str | None

    @classmethod
    def from_event(cls, event: Event) -> ReviewQueueEntry:
        # ck_events_submitted_fields_complete guarantees these for every non-DRAFT status, and
        # the review queue never returns DRAFT rows.
        starts_at, ends_at = event.starts_at, event.ends_at
        assert starts_at is not None
        assert ends_at is not None
        return cls(
            id=event.id,
            name=event.name,
            organiser_name=event.organiser.full_name,
            starts_at=starts_at,
            ends_at=ends_at,
            submitted_at=event.submitted_at,
            status=event.status,
            cover_image_url=event.cover_image_url,
        )


# --- my event requests (story 2.6) ---------------------------------------------------------
class MyEventEntry(BaseModel):
    """AC1: name, proposed date and current status, plus the optional picture. AC4: a draft can
    be saved with only a name, so the dates may be null. No defaults (response schema)."""

    id: uuid.UUID
    name: str
    starts_at: datetime | None
    ends_at: datetime | None
    status: str
    cover_image_url: str | None

    @classmethod
    def from_event(cls, event: Event) -> MyEventEntry:
        return cls(
            id=event.id,
            name=event.name,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            status=event.status,
            cover_image_url=event.cover_image_url,
        )


class MyEventList(BaseModel):
    """AC9: one page of the list, and how many requests the organiser owns in all, so a page can
    say how many more there are. No defaults (response schema)."""

    items: list[MyEventEntry]
    total: int


# --- reference data (story 2.1) ------------------------------------------------------------
class ReferenceItemOut(BaseModel):
    """One pick-list option. No defaults (response schema)."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    description: str | None


class EquipmentAvailabilityOut(BaseModel):
    """AC6: how many units of one equipment type are free for a period. No defaults."""

    equipment_type_code: str
    available: int


class EventReferenceData(BaseModel):
    """The pick-lists for the request form (AC4-AC6)."""

    layouts: list[ReferenceItemOut]
    facilities: list[ReferenceItemOut]
    accessibility_features: list[ReferenceItemOut]
    equipment_types: list[ReferenceItemOut]


# --- request bodies (story 2.1) ------------------------------------------------------------
def _strip(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) else value


def _blank_to_none(value: str | None) -> str | None:
    """Whitespace-only input becomes None, so "not filled in" is one thing, never a blank string."""
    return _strip(value) or None


def _has_duplicates(values: list[str] | list[uuid.UUID]) -> bool:
    return len(set(values)) != len(values)


class EventFacilityIn(BaseModel):
    """AC4: a facility the venue must have, optionally how many (3 breakout rooms)."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    quantity: PositiveWholeNumber | None = None
    notes: str | None = None

    @field_validator("notes", mode="before")
    @classmethod
    def _normalize_notes(cls, value):
        return _blank_to_none(value)


class EventAccessibilityNeedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    notes: str | None = None

    @field_validator("notes", mode="before")
    @classmethod
    def _normalize_notes(cls, value):
        return _blank_to_none(value)


class EventEquipmentIn(BaseModel):
    """AC6: a type and a quantity. ``id`` names an existing line to keep and edit (AC7)."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID | None = None
    equipment_type_code: str = Field(min_length=1)
    quantity: PositiveWholeNumber
    technical_notes: str | None = None

    @field_validator("technical_notes", mode="before")
    @classmethod
    def _normalize_notes(cls, value):
        return _blank_to_none(value)


class _EventRequestRules(BaseModel):
    """Rules shared by creating and editing a request. Dates are checked in the service, which
    knows the current time and, on an edit, the stored values."""

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "purpose",
        "description",
        "venue_requirement_notes",
        "accessibility_notes",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def _normalize_optional_text(cls, value):
        return _blank_to_none(value)

    @field_validator("name", mode="before", check_fields=False)
    @classmethod
    def _strip_name(cls, value):
        return _strip(value)

    @model_validator(mode="after")
    def _check_lists(self):
        facilities = getattr(self, "required_facilities", None) or []
        needs = getattr(self, "accessibility_needs", None) or []
        equipment = getattr(self, "equipment", None) or []
        if _has_duplicates([f.code for f in facilities]) or _has_duplicates(
            [n.code for n in needs]
        ):
            raise ValueError(DUPLICATE_ENTRY_MESSAGE)
        if _has_duplicates([e.equipment_type_code for e in equipment]):
            raise ValueError(DUPLICATE_EQUIPMENT_MESSAGE)
        if _has_duplicates([e.id for e in equipment if e.id is not None]):
            raise ValueError(DUPLICATE_ENTRY_MESSAGE)
        return self


class EventCreate(_EventRequestRules):
    """AC1/AC4-AC6: only the name is required, so a draft can be saved half-finished. Status,
    organiser and submission time are set by the server, and sending them is refused. What a
    request needs before it can be submitted is checked at submission (AC10)."""

    name: str = Field(min_length=1)
    purpose: str | None = None
    description: str | None = None
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    expected_attendance: PositiveWholeNumber | None = None
    required_layout_code: str | None = None
    venue_requirement_notes: str | None = None
    required_facilities: list[EventFacilityIn] = Field(default_factory=list)
    venue_none_required: bool = False
    accessibility_none_required: bool = False
    accessibility_needs: list[EventAccessibilityNeedIn] = Field(default_factory=list)
    accessibility_notes: str | None = None
    equipment: list[EventEquipmentIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_none_required(self):
        if self.venue_none_required and (
            self.required_layout_code or self.required_facilities or self.venue_requirement_notes
        ):
            raise ValueError(VENUE_CONTRADICTION_MESSAGE)
        if self.accessibility_none_required and (
            self.accessibility_needs or self.accessibility_notes
        ):
            raise ValueError(ACCESSIBILITY_CONTRADICTION_MESSAGE)
        return self


class EventUpdate(_EventRequestRules):
    """AC7: partial update. Only the fields sent change; ``null`` clears an optional field, and a
    list sent replaces that whole list (an equipment item keeps its line when it carries its
    ``id``). The name, the lists and the "none required" flags cannot be set to ``null``."""

    name: str | None = Field(default=None, min_length=1)
    purpose: str | None = None
    description: str | None = None
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    expected_attendance: PositiveWholeNumber | None = None
    required_layout_code: str | None = None
    venue_requirement_notes: str | None = None
    required_facilities: list[EventFacilityIn] | None = None
    venue_none_required: bool | None = None
    accessibility_none_required: bool | None = None
    accessibility_needs: list[EventAccessibilityNeedIn] | None = None
    accessibility_notes: str | None = None
    equipment: list[EventEquipmentIn] | None = None

    @field_validator(
        "name",
        "required_facilities",
        "venue_none_required",
        "accessibility_none_required",
        "accessibility_needs",
        "equipment",
        mode="before",
    )
    @classmethod
    def _reject_null(cls, value):
        if value is None:
            raise ValueError(CANNOT_BE_REMOVED_MESSAGE)
        return value


# --- response bodies (story 2.1) -----------------------------------------------------------
class RequiredFacilityOut(BaseModel):
    code: str
    name: str
    quantity: int | None
    notes: str | None


class AccessibilityNeedOut(BaseModel):
    code: str
    name: str
    notes: str | None


class EquipmentLineOut(BaseModel):
    id: uuid.UUID
    equipment_type_code: str
    equipment_type_name: str
    quantity: int
    technical_notes: str | None
    status: str

    @classmethod
    def from_line(cls, line: EventEquipmentRequest) -> EquipmentLineOut:
        return cls(
            id=line.id,
            equipment_type_code=line.equipment_type.code,
            equipment_type_name=line.equipment_type.name,
            quantity=line.quantity,
            technical_notes=line.technical_notes,
            status=line.status,
        )


class EventDetailOut(BaseModel):
    """AC1/AC4-AC6/AC8: everything recorded on a request, as the organiser and the reviewing
    coordinator both see it. No defaults (response schema).

    ``accessibility_none_required`` true means the organiser said none are needed; false with no
    needs and no notes means it has not been specified (AC5). ``venue_none_required`` works the
    same way for the venue requirements (AC4).

    ``internal_notes`` is coordinator-only (story 7.2): ``from_event`` nulls it out for a viewer
    without ``events:review``, so neither an organiser nor Venue Staff / Tech Support Staff
    receives it.
    """

    id: uuid.UUID
    name: str
    purpose: str | None
    description: str | None
    cover_image_url: str | None
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    internal_notes: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    expected_attendance: int | None
    status: str
    organiser_id: uuid.UUID
    organiser_name: str
    assigned_coordinator_id: uuid.UUID | None
    assigned_coordinator_name: str | None
    submitted_at: datetime | None
    required_layout_code: str | None
    required_layout_name: str | None
    required_facilities: list[RequiredFacilityOut]
    venue_requirement_notes: str | None
    venue_none_required: bool
    accessibility_none_required: bool
    accessibility_needs: list[AccessibilityNeedOut]
    accessibility_notes: str | None
    equipment: list[EquipmentLineOut]
    decided_by_name: str | None
    decided_at: datetime | None
    decision_reason: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_event(cls, event: Event, *, viewer: User) -> EventDetailOut:
        coordinator = event.assigned_coordinator
        layout = event.required_layout
        can_see_internal_notes = role_has(viewer.role_code, Permission.EVENTS_REVIEW)
        return cls(
            id=event.id,
            name=event.name,
            purpose=event.purpose,
            description=event.description,
            cover_image_url=event.cover_image_url,
            contact_name=event.contact_name,
            contact_email=event.contact_email,
            contact_phone=event.contact_phone,
            internal_notes=event.internal_notes if can_see_internal_notes else None,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            expected_attendance=event.expected_attendance,
            status=event.status,
            organiser_id=event.organiser_id,
            organiser_name=event.organiser.full_name,
            assigned_coordinator_id=event.assigned_coordinator_id,
            assigned_coordinator_name=coordinator.full_name if coordinator else None,
            submitted_at=event.submitted_at,
            required_layout_code=event.required_layout_code,
            required_layout_name=layout.name if layout else None,
            required_facilities=[
                RequiredFacilityOut(
                    code=f.facility_code, name=f.facility.name, quantity=f.quantity, notes=f.notes
                )
                for f in event.required_facilities
            ],
            venue_requirement_notes=event.venue_requirement_notes,
            venue_none_required=event.venue_none_required,
            accessibility_none_required=event.accessibility_none_required,
            accessibility_needs=[
                AccessibilityNeedOut(code=n.feature_code, name=n.feature.name, notes=n.notes)
                for n in event.accessibility_needs
            ],
            accessibility_notes=event.accessibility_notes,
            equipment=[EquipmentLineOut.from_line(line) for line in event.equipment_requests],
            decided_by_name=event.decided_by.full_name if event.decided_by else None,
            decided_at=event.decided_at,
            decision_reason=event.decision_reason,
            created_at=event.created_at,
            updated_at=event.updated_at,
        )


# --- routine information edit (story 7.2) --------------------------------------------------
class EventRoutineUpdate(BaseModel):
    """AC1: only the routine fields - description, contact details and internal notes. Partial
    update like ``EventUpdate``: only the fields sent change. Unlike ``EventUpdate``, every field
    here may be cleared with ``null`` - none of them are load-bearing for submission."""

    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    internal_notes: str | None = None

    @field_validator(
        "description",
        "contact_name",
        "contact_email",
        "contact_phone",
        "internal_notes",
        mode="before",
    )
    @classmethod
    def _normalize(cls, value):
        return _blank_to_none(value)


# --- decision (4.4 approve, 4.5 reject) ---------------------------------------------------
class EventRejection(BaseModel):
    """4.5 AC1: a reason is mandatory - blank or whitespace-only does not count."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)

    @field_validator("reason", mode="before")
    @classmethod
    def _strip_reason(cls, value):
        return _strip(value)
