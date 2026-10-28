"""Request and response models for story 21.1 (the Safety Officer's safety check queue and
detail) and story 21.2 (requesting a review, the officer's decision, confirming)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.bookings.models import VenueBooking
from app.events.models import Event, EventEquipmentRequest
from app.events.schemas import AccessibilityNeedOut, EquipmentLineOut
from app.safety.models import (
    EventSafetyReview,
    SafetyArrangement,
    SafetyReviewFactor,
    SafetyReviewFinding,
    SafetyReviewOutcome,
)
from app.venues.schemas import VenueOut


class SafetyQueueEntry(BaseModel):
    """AC2: name, dates, expected attendance, approved venues and status. No defaults (response
    schema)."""

    id: uuid.UUID
    name: str
    starts_at: datetime  # non-null for every non-DRAFT row (ck_events_submitted_fields_complete)
    ends_at: datetime
    expected_attendance: int
    venue_names: list[str]
    status: str
    safety_status: str  # PENDING, ACCEPTED or DECLINED: the queue tab it belongs to

    @classmethod
    def from_event(
        cls, event: Event, *, approved_bookings: list[VenueBooking], safety_status: str
    ) -> SafetyQueueEntry:
        # ck_events_submitted_fields_complete guarantees these for every non-DRAFT status.
        assert event.starts_at is not None
        assert event.ends_at is not None
        assert event.expected_attendance is not None
        return cls(
            id=event.id,
            name=event.name,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            expected_attendance=event.expected_attendance,
            venue_names=[booking.venue.name for booking in approved_bookings],
            status=event.status,
            safety_status=safety_status,
        )


def booked_capacity(booking: VenueBooking) -> int:
    """AC4: how many people the venue holds in the booked layout - the layout's recorded capacity
    (``venue_layouts.layout_capacity``), else the venue's own, as Find a venue (8.1 AC6) and the
    suitability check (11.1 AC4) judge it."""
    layout_capacity = next(
        (
            layout.layout_capacity
            for layout in booking.venue.layouts
            if layout.layout_code == booking.required_layout_code
        ),
        None,
    )
    return booking.venue.capacity if layout_capacity is None else layout_capacity


def people_to_hold(event: Event, booking: VenueBooking) -> int:
    """AC4: what the venue must hold - a requirement's booking its own number (2.7), an additional
    venue the event's attendance now (12.5). Fix f19.2.1 (CL-176): an approved change can raise the
    attendance past what an additional venue was booked for and keep the booking."""
    if booking.venue_requirement_id is not None:
        return booking.expected_attendance
    assert event.expected_attendance is not None
    return event.expected_attendance


class ReleasedBookingOut(BaseModel):
    """21.3 AC9: a booking a finding named, which the decision released: its venue and the
    requirement it was for (None for an additional venue)."""

    booking_id: uuid.UUID
    venue_name: str
    requirement_name: str | None


class SafetyVenueOut(BaseModel):
    """AC3: one approved venue with its full record (story 8.2), nulls passed through for AC5's
    "Not recorded". AC4: ``over_capacity`` when the booking's ``people_to_hold`` (what this room
    must hold, stories 2.7 and 12.5) is more than ``capacity``, the venue's in the booked layout."""

    venue: VenueOut
    layout: str | None
    capacity: int
    people_to_hold: int
    over_capacity: bool
    # Story 21.3 AC1: what the officer chooses a booking to release by - which booking, the
    # requirement it is for (None for an additional venue), its own times and its setup and
    # teardown.
    booking_id: uuid.UUID
    requirement_name: str | None
    starts_at: datetime
    ends_at: datetime
    setup_minutes: int
    teardown_minutes: int


class SafetyFactorOut(BaseModel):
    """21.2 AC2: a factor the review considers."""

    code: str
    name: str
    description: str | None

    @classmethod
    def from_factor(cls, factor: SafetyReviewFactor) -> SafetyFactorOut:
        return cls(code=factor.code, name=factor.name, description=factor.description)


class SafetyFindingOut(BaseModel):
    """21.2 AC4: one thing the officer requires changed."""

    factor_code: str
    factor_name: str
    required_change: str
    arrangement: str | None
    released_bookings: list[ReleasedBookingOut]  # 21.3 AC9

    @classmethod
    def from_finding(cls, finding: SafetyReviewFinding) -> SafetyFindingOut:
        return cls(
            factor_code=finding.factor_code,
            factor_name=finding.factor.name,
            required_change=finding.required_change,
            arrangement=finding.arrangement,
            released_bookings=[
                ReleasedBookingOut(
                    booking_id=booking.id,
                    venue_name=booking.venue.name,
                    requirement_name=booking.requirement_label,
                )
                for booking in finding.released_bookings
            ],
        )


class SafetyReviewOut(BaseModel):
    """21.1 AC3: one previous review of the event. 21.2 AC4: with its findings and the
    arrangements they flag."""

    id: uuid.UUID
    reviewed_at: datetime
    reviewed_by_name: str
    outcome: str
    findings: list[SafetyFindingOut]
    flagged_arrangements: list[str]

    @classmethod
    def from_review(cls, review: EventSafetyReview) -> SafetyReviewOut:
        return cls(
            id=review.id,
            reviewed_at=review.reviewed_at,
            reviewed_by_name=review.reviewed_by.full_name,
            outcome=review.outcome,
            findings=[SafetyFindingOut.from_finding(f) for f in review.findings],
            flagged_arrangements=review.flagged_arrangements,
        )


class FactChangeOut(BaseModel):
    """AC5: one fact as the last review saw it and as it stands now."""

    fact: str
    before: Any
    after: Any


class SafetyCheckDetail(BaseModel):
    """AC3-AC5: everything about the event that affects safety. No defaults (response schema)."""

    id: uuid.UUID
    name: str
    description: str | None
    starts_at: datetime
    ends_at: datetime
    expected_attendance: int
    status: str
    venues: list[SafetyVenueOut]
    accessibility_notes: str | None
    accessibility_needs: list[AccessibilityNeedOut]
    equipment: list[EquipmentLineOut]
    changes_since_last_review: list[FactChangeOut]
    previous_reviews: list[SafetyReviewOut]
    factors: list[SafetyFactorOut]  # 21.2 AC2
    facts_fingerprint: str  # 21.2 AC20: returned with the decision, as what the officer read

    @classmethod
    def from_event(
        cls,
        event: Event,
        *,
        approved_bookings: list[VenueBooking],
        accepted_equipment: list[EventEquipmentRequest],
        reviews: list[EventSafetyReview],
        changes: list[FactChangeOut],
        factors: list[SafetyReviewFactor],
        facts_fingerprint: str,
    ) -> SafetyCheckDetail:
        # ck_events_submitted_fields_complete guarantees these for every non-DRAFT status.
        assert event.starts_at is not None
        assert event.ends_at is not None
        assert event.expected_attendance is not None
        return cls(
            id=event.id,
            name=event.name,
            description=event.description,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            expected_attendance=event.expected_attendance,
            status=event.status,
            venues=[
                SafetyVenueOut(
                    venue=VenueOut.from_venue(booking.venue),
                    layout=(
                        booking.required_layout.name
                        if booking.required_layout is not None
                        else None
                    ),
                    capacity=booked_capacity(booking),
                    people_to_hold=people_to_hold(event, booking),
                    over_capacity=people_to_hold(event, booking) > booked_capacity(booking),
                    booking_id=booking.id,
                    requirement_name=booking.requirement_label,
                    starts_at=booking.starts_at,
                    ends_at=booking.ends_at,
                    setup_minutes=booking.setup_minutes,
                    teardown_minutes=booking.teardown_minutes,
                )
                for booking in approved_bookings
            ],
            accessibility_notes=event.accessibility_notes,
            accessibility_needs=[
                AccessibilityNeedOut(
                    code=need.feature_code, name=need.feature.name, notes=need.notes
                )
                for need in event.accessibility_needs
            ],
            equipment=[EquipmentLineOut.from_line(item) for item in accepted_equipment],
            changes_since_last_review=changes,
            previous_reviews=[SafetyReviewOut.from_review(review) for review in reviews],
            factors=[SafetyFactorOut.from_factor(factor) for factor in factors],
            facts_fingerprint=facts_fingerprint,
        )


# --- story 21.2: requesting a review, the decision, the event page's summary ---------------------
# AC9: the longest required change the officer may write.
MAX_SAFETY_TEXT_LENGTH = 2000
FINDINGS_REQUIRED_MESSAGE = "Add at least one finding saying what must change."
FINDINGS_NOT_ALLOWED_MESSAGE = "Only a request for changes has findings."
REQUIRED_CHANGE_BLANK_MESSAGE = "Say what must change for each finding."
BOOKINGS_ON_OTHER_FINDING_MESSAGE = "Only a finding about venue bookings can name bookings."

SafetyText = Annotated[str, Field(max_length=MAX_SAFETY_TEXT_LENGTH)]


class SafetyReviewRequestIn(BaseModel):
    """21.2 AC1/AC12: ``acknowledge_unchanged`` submits even though an arrangement the last
    review flagged has not changed."""

    acknowledge_unchanged: bool = False


class SafetyFindingIn(BaseModel):
    """21.2 AC4/AC10: one finding - a factor, exactly what must change, and optionally the
    arrangement to rebook. An unknown factor is refused by the service (its foreign key)."""

    factor_code: str
    required_change: SafetyText
    arrangement: Literal["VENUE_BOOKINGS", "EQUIPMENT"] | None = None
    booking_ids: list[uuid.UUID] = []

    @field_validator("required_change")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(REQUIRED_CHANGE_BLANK_MESSAGE)
        return value

    @model_validator(mode="after")
    def _bookings_only_on_a_venue_finding(self) -> SafetyFindingIn:
        """21.3 AC7: bookings are named on a finding about venue bookings, and only there; a
        booking named twice on one finding is named once."""
        if self.booking_ids and self.arrangement != SafetyArrangement.VENUE_BOOKINGS:
            raise ValueError(BOOKINGS_ON_OTHER_FINDING_MESSAGE)
        self.booking_ids = list(dict.fromkeys(self.booking_ids))
        return self


class SafetyDecisionIn(BaseModel):
    """21.2 AC2-AC5, AC9, AC10: the officer's decision - approve or request changes, nothing
    else, with no notes. Only a request for changes carries findings, at least one. AC20:
    ``facts_fingerprint`` is the one on the page the officer read (``SafetyCheckDetail``)."""

    outcome: Literal["APPROVED", "CHANGES_REQUESTED"]
    findings: list[SafetyFindingIn] = []
    facts_fingerprint: str

    @model_validator(mode="after")
    def _check_outcome(self) -> SafetyDecisionIn:
        if self.outcome == SafetyReviewOutcome.CHANGES_REQUESTED and not self.findings:
            raise ValueError(FINDINGS_REQUIRED_MESSAGE)
        if self.outcome != SafetyReviewOutcome.CHANGES_REQUESTED and self.findings:
            raise ValueError(FINDINGS_NOT_ALLOWED_MESSAGE)
        return self


class EventSafetyOut(BaseModel):
    """21.2 AC4/AC7: the safety review as the event page shows it - the latest review with its
    findings, and for the assigned coordinator only (AC18), what stops them requesting a review or
    confirming (``[]`` offers the action; ``None`` for anyone else) and the AC12 warning a request
    would raise. No defaults (response schema)."""

    event_id: uuid.UUID
    status: str
    latest_review: SafetyReviewOut | None
    request_blockers: list[str] | None
    confirm_blockers: list[str] | None
    unchanged_warning: str | None
