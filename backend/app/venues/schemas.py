"""Request / response shapes for the venue catalogue (story 8.3, read side reused by 8.1/8.2)."""

from __future__ import annotations

import uuid
from datetime import datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from app.venues.models import Venue

# "Positive whole numbers only" (story 8.3 AC3): StrictInt rejects 12.5 and "12"; gt=0 rejects 0.
PositiveWholeNumber = StrictInt
POSITIVE = Field(gt=0)
NON_NEGATIVE = Field(ge=0)


# --- reference data ---------------------------------------------------------------------
class ReferenceItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    description: str | None = None


class VenueReferenceData(BaseModel):
    facilities: list[ReferenceItem]
    layouts: list[ReferenceItem]
    accessibility_features: list[ReferenceItem]


# --- characteristic line items -----------------------------------------------------------
class VenueFacilityIn(BaseModel):
    code: str = Field(min_length=1)
    quantity: PositiveWholeNumber | None = Field(default=None, gt=0)
    notes: str | None = None


class VenueLayoutIn(BaseModel):
    code: str = Field(min_length=1)
    layout_capacity: PositiveWholeNumber | None = Field(default=None, gt=0)


class VenueAccessibilityFeatureIn(BaseModel):
    code: str = Field(min_length=1)
    notes: str | None = None


class VenueFacilityOut(BaseModel):
    code: str
    name: str
    quantity: int | None
    notes: str | None


class VenueLayoutOut(BaseModel):
    code: str
    name: str
    layout_capacity: int | None


class VenueAccessibilityFeatureOut(BaseModel):
    code: str
    name: str
    notes: str | None


# --- venue -----------------------------------------------------------------------------
def _strip(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) else value


class _OperatingHoursMixin(BaseModel):
    @model_validator(mode="after")
    def _check_operating_hours(self):
        start = getattr(self, "operating_hours_start", None)
        end = getattr(self, "operating_hours_end", None)
        if (start is None) != (end is None):
            raise ValueError("operating_hours_start and operating_hours_end must be given together")
        if start is not None and end is not None and end <= start:
            raise ValueError("operating_hours_end must be after operating_hours_start")
        return self


class VenueCreate(_OperatingHoursMixin):
    """AC1: name, location and capacity are the minimum; everything else is optional."""

    name: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1, max_length=500)
    capacity: PositiveWholeNumber = POSITIVE
    description: str | None = None
    floor_area_sqm: Decimal | None = Field(default=None, gt=0, max_digits=8, decimal_places=2)
    operating_hours_start: time | None = None
    operating_hours_end: time | None = None
    operating_notes: str | None = None
    setup_minutes_default: PositiveWholeNumber = Field(default=0, ge=0)
    teardown_minutes_default: PositiveWholeNumber = Field(default=0, ge=0)
    facilities: list[VenueFacilityIn] = Field(default_factory=list)
    layouts: list[VenueLayoutIn] = Field(default_factory=list)
    accessibility_features: list[VenueAccessibilityFeatureIn] = Field(default_factory=list)

    @field_validator("name", "location", mode="before")
    @classmethod
    def _strip_required(cls, value):
        return _strip(value)


class VenueUpdate(_OperatingHoursMixin):
    """AC2: partial update - only the fields present in the request change.

    Sending a list (facilities / layouts / accessibility_features) replaces that whole list;
    omitting it leaves the list untouched. ``status`` allows WITHDRAWN / ACTIVE (story 8.4).
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, min_length=1, max_length=500)
    capacity: PositiveWholeNumber | None = Field(default=None, gt=0)
    description: str | None = None
    floor_area_sqm: Decimal | None = Field(default=None, gt=0, max_digits=8, decimal_places=2)
    operating_hours_start: time | None = None
    operating_hours_end: time | None = None
    operating_notes: str | None = None
    setup_minutes_default: PositiveWholeNumber | None = Field(default=None, ge=0)
    teardown_minutes_default: PositiveWholeNumber | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, pattern="^(ACTIVE|WITHDRAWN)$")
    facilities: list[VenueFacilityIn] | None = None
    layouts: list[VenueLayoutIn] | None = None
    accessibility_features: list[VenueAccessibilityFeatureIn] | None = None

    @field_validator("name", "location", mode="before")
    @classmethod
    def _strip_required(cls, value):
        return _strip(value)

    @model_validator(mode="after")
    def _check_operating_hours(self):
        # For a partial update the pair rule is checked in the service against the merged record.
        start, end = self.operating_hours_start, self.operating_hours_end
        if start is not None and end is not None and end <= start:
            raise ValueError("operating_hours_end must be after operating_hours_start")
        return self


class VenueSummary(BaseModel):
    """List entry (story 8.1 AC1: name, location, capacity)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    location: str
    capacity: int
    status: str


class VenueOut(VenueSummary):
    """Full record (story 8.2 AC1). NULL means "not recorded" - show it as unknown, not absent."""

    description: str | None
    floor_area_sqm: Decimal | None
    operating_hours_start: time | None
    operating_hours_end: time | None
    operating_notes: str | None
    setup_minutes_default: int
    teardown_minutes_default: int
    facilities: list[VenueFacilityOut]
    layouts: list[VenueLayoutOut]
    accessibility_features: list[VenueAccessibilityFeatureOut]
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_venue(cls, venue: Venue) -> VenueOut:
        return cls(
            id=venue.id,
            name=venue.name,
            location=venue.location,
            capacity=venue.capacity,
            status=venue.status,
            description=venue.description,
            floor_area_sqm=venue.floor_area_sqm,
            operating_hours_start=venue.operating_hours_start,
            operating_hours_end=venue.operating_hours_end,
            operating_notes=venue.operating_notes,
            setup_minutes_default=venue.setup_minutes_default,
            teardown_minutes_default=venue.teardown_minutes_default,
            facilities=[
                VenueFacilityOut(
                    code=f.facility_code, name=f.facility.name, quantity=f.quantity, notes=f.notes
                )
                for f in venue.facilities
            ],
            layouts=[
                VenueLayoutOut(
                    code=lo.layout_code, name=lo.layout.name, layout_capacity=lo.layout_capacity
                )
                for lo in venue.layouts
            ],
            accessibility_features=[
                VenueAccessibilityFeatureOut(
                    code=a.feature_code, name=a.feature.name, notes=a.notes
                )
                for a in venue.accessibility_features
            ],
            created_by_id=venue.created_by_id,
            created_at=venue.created_at,
            updated_at=venue.updated_at,
        )
