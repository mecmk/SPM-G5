"""Business rules for story 21.1: the Safety Officer's queue of events awaiting the safety check."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC
from enum import StrEnum
from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.bookings.models import BookingStatus, VenueBooking
from app.events.models import (
    EquipmentRequestStatus,
    Event,
    EventEquipmentRequest,
    EventStatus,
    EventStatusHistory,
)
from app.safety.models import EventSafetyReview, SafetyReviewOutcome
from app.safety.schemas import FactChangeOut


class SafetyQueueStatus(StrEnum):
    """The queue's tabs (21.1 AC2, a team request beyond the AC). PENDING is an event awaiting the
    check; ACCEPTED and DECLINED are events no longer awaiting it, by their latest review."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


@dataclass(frozen=True)
class SafetyQueueItem:
    """An event in the queue, with its approved bookings (21.1 AC2) and its tab."""

    event: Event
    approved_bookings: list[VenueBooking]
    safety_status: SafetyQueueStatus


def _approved_bookings(
    db: Session, event_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[VenueBooking]]:
    """Only an APPROVED booking is a booked venue: a pending, withdrawn or expired one is not."""
    bookings = db.scalars(
        select(VenueBooking)
        .options(joinedload(VenueBooking.venue))
        .where(VenueBooking.event_id.in_(event_ids), VenueBooking.status == BookingStatus.APPROVED)
        .order_by(VenueBooking.starts_at, VenueBooking.id)
    ).all()
    by_event: dict[uuid.UUID, list[VenueBooking]] = defaultdict(list)
    for booking in bookings:
        by_event[booking.event_id].append(booking)
    return by_event


def _safety_status(event: Event, latest_outcome: str | None) -> SafetyQueueStatus:
    if event.status == EventStatus.AWAITING_SAFETY_CHECK:
        return SafetyQueueStatus.PENDING
    if latest_outcome == SafetyReviewOutcome.APPROVED:
        return SafetyQueueStatus.ACCEPTED
    return SafetyQueueStatus.DECLINED


def list_safety_queue(db: Session, status: SafetyQueueStatus | None) -> list[SafetyQueueItem]:
    """AC2: the events in one tab, or every tab when ``status`` is None, oldest first by when
    each last entered the check."""
    entered = (
        select(
            EventStatusHistory.event_id,
            func.max(EventStatusHistory.changed_at).label("entered_at"),
        )
        .where(EventStatusHistory.to_status == EventStatus.AWAITING_SAFETY_CHECK)
        .group_by(EventStatusHistory.event_id)
        .subquery()
    )
    latest = (
        select(EventSafetyReview.event_id, EventSafetyReview.outcome)
        .distinct(EventSafetyReview.event_id)
        .order_by(
            EventSafetyReview.event_id,
            EventSafetyReview.reviewed_at.desc(),
            EventSafetyReview.id.desc(),
        )
        .subquery()
    )
    is_awaiting = Event.status == EventStatus.AWAITING_SAFETY_CHECK
    tab_filter = {
        None: or_(is_awaiting, latest.c.outcome.is_not(None)),
        SafetyQueueStatus.PENDING: is_awaiting,
        SafetyQueueStatus.ACCEPTED: ~is_awaiting
        & (latest.c.outcome == SafetyReviewOutcome.APPROVED),
        SafetyQueueStatus.DECLINED: ~is_awaiting
        & (latest.c.outcome == SafetyReviewOutcome.CHANGES_REQUESTED),
    }[status]
    rows = db.execute(
        select(Event, latest.c.outcome)
        .outerjoin(entered, entered.c.event_id == Event.id)
        .outerjoin(latest, latest.c.event_id == Event.id)
        .where(tab_filter)
        .order_by(entered.c.entered_at, Event.id)
    ).all()
    bookings = _approved_bookings(db, [event.id for event, _ in rows])
    return [
        SafetyQueueItem(
            event=event,
            approved_bookings=bookings[event.id],
            safety_status=_safety_status(event, outcome),
        )
        for event, outcome in rows
    ]


class SafetyCheckNotFound(Exception):
    """No event with this id is awaiting the safety check or has been reviewed (21.1 AC3)."""


@dataclass(frozen=True)
class SafetyCheck:
    """Everything the officer reads for one event (21.1 AC3-AC5). ``facts`` is the snapshot the
    review story stores on ``event_safety_reviews.facts``."""

    event: Event
    approved_bookings: list[VenueBooking]
    accepted_equipment: list[EventEquipmentRequest]
    reviews: list[EventSafetyReview]  # newest first
    facts: dict[str, Any]
    changes: list[FactChangeOut]


def safety_facts(
    event: Event,
    *,
    approved_bookings: list[VenueBooking],
    accepted_equipment: list[EventEquipmentRequest],
) -> dict[str, Any]:
    """The facts a safety review is judged on, as JSON. Times are UTC so a stored snapshot
    compares equal to a fresh one."""
    assert event.starts_at is not None  # ck_events_submitted_fields_complete
    assert event.ends_at is not None
    return {
        "description": event.description,  # the idea itself is judged, not only the logistics
        "expected_attendance": event.expected_attendance,
        "starts_at": event.starts_at.astimezone(UTC).isoformat(),
        "ends_at": event.ends_at.astimezone(UTC).isoformat(),
        "venues": [
            {
                "id": str(booking.venue_id),
                "name": booking.venue.name,
                "capacity": booking.venue.capacity,
                "layout": booking.required_layout_code,
            }
            for booking in approved_bookings
        ],
        "accessibility": [
            {"feature": need.feature_code, "notes": need.notes}
            for need in event.accessibility_needs
        ],
        "equipment": [
            {
                "equipment_type": item.equipment_type.code,
                "quantity": item.quantity,
                "technical_notes": item.technical_notes,
            }
            for item in accepted_equipment
        ],
    }


def get_safety_check(db: Session, event_id: uuid.UUID) -> SafetyCheck:
    """AC3: the event's safety facts and previous reviews. AC5: what changed since the latest
    review. Raises ``SafetyCheckNotFound`` unless the event is awaiting the check or has been
    reviewed (the Accepted and Declined tabs open it too)."""
    event = db.scalar(
        select(Event).where(
            Event.id == event_id,
            or_(
                Event.status == EventStatus.AWAITING_SAFETY_CHECK,
                exists().where(EventSafetyReview.event_id == Event.id),
            ),
        )
    )
    if event is None:
        raise SafetyCheckNotFound(event_id)
    approved_bookings = _approved_bookings(db, [event.id])[event.id]
    accepted_equipment = list(
        db.scalars(
            select(EventEquipmentRequest)
            .where(
                EventEquipmentRequest.event_id == event.id,
                EventEquipmentRequest.status == EquipmentRequestStatus.ACCEPTED,
            )
            .order_by(EventEquipmentRequest.created_at, EventEquipmentRequest.id)
        )
    )
    reviews = list(
        db.scalars(
            select(EventSafetyReview)
            .where(EventSafetyReview.event_id == event.id)
            .order_by(EventSafetyReview.reviewed_at.desc(), EventSafetyReview.id.desc())
        )
    )
    facts = safety_facts(
        event, approved_bookings=approved_bookings, accepted_equipment=accepted_equipment
    )
    # ponytail: diffs whole top-level facts, so one venue edit marks the whole venue list as
    # changed; compare item by item if the officer needs finer detail.
    changes = (
        [
            FactChangeOut(fact=key, before=reviews[0].facts.get(key), after=value)
            for key, value in facts.items()
            if reviews[0].facts.get(key) != value
        ]
        if reviews
        else []
    )
    return SafetyCheck(
        event=event,
        approved_bookings=approved_bookings,
        accepted_equipment=accepted_equipment,
        reviews=reviews,
        facts=facts,
        changes=changes,
    )
