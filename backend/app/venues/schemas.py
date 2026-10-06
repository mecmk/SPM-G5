"""Request / response shapes for the venue catalogue (story 8.3, read side reused by 8.1/8.2), a
venue's pictures (story 8.3 AC5-AC10), its search (story 8.1, Sprint 2) and its availability
calendar (story 9.1)."""

from __future__ import annotations

import uuid
from datetime import datetime, time
from decimal import Decimal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from app.venues.models import Venue
from app.venues.suitability import Suitability

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


def _blank_to_none(value: str | None) -> str | None:
    """Whitespace-only input becomes None, not a stored-but-invisible value (story 8.2 AC2:
    "not recorded" must mean null, never a blank string that renders empty)."""
    stripped = _strip(value)
    return stripped or None


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

    @field_validator("operating_notes", mode="before")
    @classmethod
    def _normalize_operating_notes(cls, value):
        return _blank_to_none(value)


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

    @field_validator("operating_notes", mode="before")
    @classmethod
    def _normalize_operating_notes(cls, value):
        return _blank_to_none(value)

    @model_validator(mode="after")
    def _check_operating_hours(self):
        # For a partial update the pair rule is checked in the service against the merged record.
        start, end = self.operating_hours_start, self.operating_hours_end
        if start is not None and end is not None and end <= start:
            raise ValueError("operating_hours_end must be after operating_hours_start")
        return self


class VenueSummary(BaseModel):
    """List entry (story 8.1 AC1: name, location, capacity). Story 8.3 AC6: ``cover_image_url`` is
    the venue's first picture, for its catalogue card; None shows the placeholder."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    location: str
    capacity: int
    status: str
    cover_image_url: str | None


class VenueImageOut(BaseModel):
    """Story 8.3 AC5/AC6: one of a venue's pictures, and where it is served from."""

    id: uuid.UUID
    url: str


class VenueImageOrder(BaseModel):
    """Story 8.3 AC5: every one of a venue's pictures, by id, in the order wanted - the first
    becomes the cover. AC10: each picture once, and the service checks they are exactly the venue's
    own."""

    model_config = ConfigDict(extra="forbid")

    image_ids: list[uuid.UUID]

    @field_validator("image_ids")
    @classmethod
    def _each_picture_once(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Name each picture once.")
        return value


class VenueOut(VenueSummary):
    """Full record (story 8.2 AC1). NULL means "not recorded" - show it as unknown, not absent.
    Story 8.3 AC6: ``images`` are the venue's pictures in their order, the first being the cover."""

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
    images: list[VenueImageOut]
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
            cover_image_url=venue.cover_image_url,
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
            images=[VenueImageOut(id=image.id, url=image.url) for image in venue.images],
            created_by_id=venue.created_by_id,
            created_at=venue.created_at,
            updated_at=venue.updated_at,
        )


# --- search (story 8.1, Sprint 2) --------------------------------------------------------
class VenueSearchQuery(BaseModel):
    """Story 8.1 AC3/AC4: the catalogue's filters, as ``GET /venues/search`` reads them from the
    query string. Every field is optional; the service checks how they combine (AC8)."""

    search: str | None = None
    # Plain int, not PositiveWholeNumber: a query string only carries text, so "50" must convert.
    capacity: int | None = Field(default=None, gt=0)
    capacity_max: int | None = Field(default=None, gt=0)
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    layout: str | None = None
    facility: list[str] = Field(default_factory=list)
    accessibility: list[str] = Field(default_factory=list)
    include_withdrawn: bool = False
    # Story 11.1 AC1: the event venues are being found for. Judges each result; filters nothing.
    event: uuid.UUID | None = None


class FailedCriterionOut(BaseModel):
    """Story 11.1 AC1: one criterion a venue fails - ``app.venues.suitability.FailedCriterion``
    as the catalogue reads it. ``outcome`` is NOT_MET or UNKNOWN (AC5)."""

    criterion: str
    outcome: str
    code: str | None
    name: str | None
    required: int | None
    venue_value: int | None


class VenueSuitabilityOut(BaseModel):
    """Story 11.1 AC1/AC3: whether a venue suits the venue requirement it was judged against,
    and every criterion it fails. ``requirement_id`` and ``requirement_name`` are None for an
    event with no venue requirements, judged on its attendance alone (AC5)."""

    requirement_id: uuid.UUID | None
    requirement_name: str | None
    is_suitable: bool
    failures: list[FailedCriterionOut]

    @classmethod
    def from_suitability(
        cls, suitability: Suitability, *, requirement_id: uuid.UUID | None
    ) -> VenueSuitabilityOut:
        return cls(
            requirement_id=requirement_id,
            requirement_name=suitability.requirement_name,
            is_suitable=suitability.is_suitable,
            failures=[
                FailedCriterionOut(
                    criterion=failure.criterion,
                    outcome=failure.outcome,
                    code=failure.code,
                    name=failure.name,
                    required=failure.required,
                    venue_value=failure.venue_value,
                )
                for failure in suitability.failures
            ],
        )


class VenueSearchHit(VenueSummary):
    """Story 8.1 AC1/AC3: one venue a search found. Its opening hours let the catalogue say they
    are not recorded when a period is searched, since such a venue is kept rather than refused.

    Story 11.1 AC1/AC3: ``suitability`` judges it against the event searched for. None outside
    event context (AC5) and for anyone but the event's assigned coordinator (AC6)."""

    operating_hours_start: time | None
    operating_hours_end: time | None
    suitability: VenueSuitabilityOut | None

    @classmethod
    def from_venue(cls, venue: Venue, *, suitability: VenueSuitabilityOut | None) -> VenueSearchHit:
        """Every field this model declares, read off ``venue`` by name, plus ``suitability`` - so
        a field later added to ``VenueSummary`` is carried without being listed here."""
        fields = {name: getattr(venue, name) for name in cls.model_fields if name != "suitability"}
        return cls(**fields, suitability=suitability)


class RelaxHint(BaseModel):
    """Story 8.1 AC9: a filter group whose removal alone would give results, and how many."""

    filter: str
    label: str
    count: int


class VenueSearchResult(BaseModel):
    """Story 8.1: what ``GET /venues/search`` answers. ``total`` counts every venue the search
    looked through (those in service, and withdrawn ones when asked for), for "Showing N of M
    venues"; ``relax`` is filled only when nothing matched (AC9)."""

    venues: list[VenueSearchHit]
    total: int
    relax: list[RelaxHint]


# --- calendar (story 9.1) ----------------------------------------------------------------
# Sentinel `reason` values for the two kinds of booking on the calendar: an approved booking
# (BOOKED) and a pending request that soft-locks the venue (HELD, story 9.1 AC2). Neither is a
# value of venue_unavailability_periods.reason (MAINTENANCE, RENOVATION, SAFETY, INTERNAL_USE,
# OTHER, see UnavailabilityReason in models.py) - the calendar's `reason` field carries either
# vocabulary, so it is not a single enum and a closure's reason is never BOOKED or HELD.
BOOKING_REASON = "BOOKED"
HELD_REASON = "HELD"


class VenueUnavailableWindowOut(BaseModel):
    """One blocked period on the venue calendar (story 9.1 AC2): an approved booking (BOOKED), a
    pending request (HELD) or a venue_unavailability_periods row. A flat list of periods, not
    pre-expanded per day - the frontend expands each into the calendar days it touches.

    ``starts_at`` / ``ends_at`` are the period the venue is blocked: for a booking, its held
    period (setup and teardown included). AC5: ``booking_starts_at`` / ``booking_ends_at`` are
    the booking's own requested period inside it - which may cover only part of its event's own
    schedule - so a day's list can show both; None for a closure, which has no booking."""

    starts_at: datetime
    ends_at: datetime
    booking_starts_at: datetime | None
    booking_ends_at: datetime | None
    reason: str
    label: str
