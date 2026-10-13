"""Response models for story 21.1: the Safety Officer's safety check queue and detail."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.bookings.models import VenueBooking
from app.events.models import Event, EventEquipmentRequest
from app.events.schemas import AccessibilityNeedOut, EquipmentLineOut
from app.safety.models import EventSafetyReview
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


class SafetyVenueOut(BaseModel):
    """AC3: one approved venue with its full record (story 8.2), nulls passed through for AC5's
    "Not recorded". AC4: ``over_capacity`` when the event expects more than the venue holds."""

    venue: VenueOut
    layout: str | None
    over_capacity: bool


class SafetyReviewOut(BaseModel):
    """AC3: one previous review of the event."""

    id: uuid.UUID
    reviewed_at: datetime
    reviewed_by_name: str
    outcome: str
    notes: str | None


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

    @classmethod
    def from_event(
        cls,
        event: Event,
        *,
        approved_bookings: list[VenueBooking],
        accepted_equipment: list[EventEquipmentRequest],
        reviews: list[EventSafetyReview],
        changes: list[FactChangeOut],
    ) -> SafetyCheckDetail:
        # ck_events_submitted_fields_complete guarantees these for every non-DRAFT status.
        assert event.starts_at is not None
        assert event.ends_at is not None
        assert event.expected_attendance is not None
        attendance = event.expected_attendance
        return cls(
            id=event.id,
            name=event.name,
            description=event.description,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            expected_attendance=attendance,
            status=event.status,
            venues=[
                SafetyVenueOut(
                    venue=VenueOut.from_venue(booking.venue),
                    layout=(
                        booking.required_layout.name
                        if booking.required_layout is not None
                        else None
                    ),
                    over_capacity=attendance > booking.venue.capacity,
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
            previous_reviews=[
                SafetyReviewOut(
                    id=review.id,
                    reviewed_at=review.reviewed_at,
                    reviewed_by_name=review.reviewed_by.full_name,
                    outcome=review.outcome,
                    notes=review.notes,
                )
                for review in reviews
            ],
        )
