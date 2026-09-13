"""Request / response shapes for event requests (story 2.1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from app.events.models import Event

# "Positive whole numbers only" (story 2.1 AC3): StrictInt rejects 12.5 and "12"; gt=0 rejects 0.
# Duplicated from venues/schemas.py rather than imported - the two features have no shared
# dependency today; worth consolidating into a shared module if a third feature needs the same
# pattern.
PositiveWholeNumber = StrictInt
POSITIVE = Field(gt=0)

INVALID_PERIOD_MESSAGE = "The event's end date and time must be after its start date and time."
PAST_START_MESSAGE = "The event's start date and time must be in the future."
ACCESSIBILITY_CONFLICT_MESSAGE = (
    "An event cannot both require specific accessibility features and be marked as needing none."
)


# --- line items --------------------------------------------------------------------------
class EventFacilityIn(BaseModel):
    code: str = Field(min_length=1)
    notes: str | None = None


class EventAccessibilityNeedIn(BaseModel):
    code: str = Field(min_length=1)
    notes: str | None = None


class EventEquipmentRequestIn(BaseModel):
    equipment_type_id: uuid.UUID
    quantity: PositiveWholeNumber = POSITIVE
    technical_notes: str | None = None


class EventFacilityOut(BaseModel):
    code: str
    name: str
    notes: str | None


class EventAccessibilityNeedOut(BaseModel):
    code: str
    name: str
    notes: str | None


class EventEquipmentRequestOut(BaseModel):
    id: uuid.UUID
    equipment_type_id: uuid.UUID
    code: str
    name: str
    quantity: int
    technical_notes: str | None
    status: str


# --- event ---------------------------------------------------------------------------------
def _strip(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) else value


class _EventValidationMixin(BaseModel):
    """AC2 (period, no past start) and AC5 (none-required is exclusive of a features list)."""

    @model_validator(mode="after")
    def _check_period(self):
        starts_at = getattr(self, "starts_at", None)
        ends_at = getattr(self, "ends_at", None)
        if starts_at is not None and ends_at is not None and ends_at <= starts_at:
            raise ValueError(INVALID_PERIOD_MESSAGE)
        return self

    @model_validator(mode="after")
    def _check_start_not_in_past(self):
        starts_at = getattr(self, "starts_at", None)
        if starts_at is not None and starts_at < datetime.now(UTC):
            raise ValueError(PAST_START_MESSAGE)
        return self

    @model_validator(mode="after")
    def _check_accessibility_exclusive(self):
        none_required = getattr(self, "accessibility_none_required", False)
        features = getattr(self, "accessibility_features", None) or []
        if none_required and len(features) > 0:
            raise ValueError(ACCESSIBILITY_CONFLICT_MESSAGE)
        return self


class EventCreate(_EventValidationMixin):
    """AC1: name is the only field required even for a draft."""

    name: str = Field(min_length=1, max_length=300)
    purpose: str | None = None
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    expected_attendance: PositiveWholeNumber | None = Field(default=None, gt=0)
    preferred_location: str | None = None
    required_layout_code: str | None = None
    venue_requirement_notes: str | None = None
    accessibility_none_required: bool = False
    accessibility_notes: str | None = None
    accessibility_features: list[EventAccessibilityNeedIn] = Field(default_factory=list)
    required_facilities: list[EventFacilityIn] = Field(default_factory=list)
    equipment_requests: list[EventEquipmentRequestIn] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_required(cls, value):
        return _strip(value)


class EventUpdate(_EventValidationMixin):
    """AC7: partial update - only fields present in the request change.

    Sending a list (accessibility_features / required_facilities / equipment_requests) replaces
    that whole list; omitting it leaves the list untouched, matching VenueUpdate.

    The period, past-start and accessibility-exclusivity checks below are deliberately lighter
    than EventCreate's: a partial update may touch only one side of a relationship (e.g. a
    PATCH that sends only `ends_at`), so this schema can only validate what is actually present
    in *this* payload. The authoritative check against the merged, final record happens in
    `service.update_event`, exactly like VenueUpdate's operating-hours pair - see
    `venues/schemas.py`'s own `_check_operating_hours` override and `venues/service.py:142-153`.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=300)
    purpose: str | None = None
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    expected_attendance: PositiveWholeNumber | None = Field(default=None, gt=0)
    preferred_location: str | None = None
    required_layout_code: str | None = None
    venue_requirement_notes: str | None = None
    accessibility_none_required: bool | None = None
    accessibility_notes: str | None = None
    accessibility_features: list[EventAccessibilityNeedIn] | None = None
    required_facilities: list[EventFacilityIn] | None = None
    equipment_requests: list[EventEquipmentRequestIn] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _strip_required(cls, value):
        return _strip(value)

    @model_validator(mode="after")
    def _check_period(self):
        if (
            "starts_at" in self.model_fields_set
            and "ends_at" in self.model_fields_set
            and self.starts_at is not None
            and self.ends_at is not None
            and self.ends_at <= self.starts_at
        ):
            raise ValueError(INVALID_PERIOD_MESSAGE)
        return self

    @model_validator(mode="after")
    def _check_start_not_in_past(self):
        # Self-sufficient at the schema level (unlike the period check): whether a single date
        # is in the past never depends on any other field, so no merged-record re-check is
        # needed in the service for this one.
        if (
            "starts_at" in self.model_fields_set
            and self.starts_at is not None
            and self.starts_at < datetime.now(UTC)
        ):
            raise ValueError(PAST_START_MESSAGE)
        return self

    @model_validator(mode="after")
    def _check_accessibility_exclusive(self):
        if (
            "accessibility_none_required" in self.model_fields_set
            and "accessibility_features" in self.model_fields_set
            and self.accessibility_none_required
            and self.accessibility_features
        ):
            raise ValueError(ACCESSIBILITY_CONFLICT_MESSAGE)
        return self


class EventSummary(BaseModel):
    """List entry."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: str
    starts_at: datetime | None
    ends_at: datetime | None
    expected_attendance: int | None
    organiser_id: uuid.UUID
    created_at: datetime


class EventOut(EventSummary):
    """Full record (AC8: everything recorded is visible)."""

    purpose: str | None
    description: str | None
    organisation_id: uuid.UUID | None
    assigned_coordinator_id: uuid.UUID | None
    preferred_location: str | None
    required_layout_code: str | None
    required_layout_name: str | None
    venue_requirement_notes: str | None
    accessibility_none_required: bool
    accessibility_notes: str | None
    accessibility_features: list[EventAccessibilityNeedOut]
    required_facilities: list[EventFacilityOut]
    equipment_requests: list[EventEquipmentRequestOut]
    submitted_at: datetime | None
    updated_at: datetime

    @classmethod
    def from_event(cls, event: Event) -> EventOut:
        return cls(
            id=event.id,
            name=event.name,
            status=event.status,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            expected_attendance=event.expected_attendance,
            organiser_id=event.organiser_id,
            created_at=event.created_at,
            purpose=event.purpose,
            description=event.description,
            organisation_id=event.organisation_id,
            assigned_coordinator_id=event.assigned_coordinator_id,
            preferred_location=event.preferred_location,
            required_layout_code=event.required_layout_code,
            required_layout_name=(
                event.required_layout.name if event.required_layout is not None else None
            ),
            venue_requirement_notes=event.venue_requirement_notes,
            accessibility_none_required=event.accessibility_none_required,
            accessibility_notes=event.accessibility_notes,
            accessibility_features=[
                EventAccessibilityNeedOut(code=a.feature_code, name=a.feature.name, notes=a.notes)
                for a in event.accessibility_features
            ],
            required_facilities=[
                EventFacilityOut(code=f.facility_code, name=f.facility.name, notes=f.notes)
                for f in event.required_facilities
            ],
            equipment_requests=[
                EventEquipmentRequestOut(
                    id=e.id,
                    equipment_type_id=e.equipment_type_id,
                    code=e.equipment_type.code,
                    name=e.equipment_type.name,
                    quantity=e.quantity,
                    technical_notes=e.technical_notes,
                    status=e.status,
                )
                for e in event.equipment_requests
            ],
            submitted_at=event.submitted_at,
            updated_at=event.updated_at,
        )
