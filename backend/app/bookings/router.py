"""HTTP endpoints for venue bookings: raising a request (story 12.1), the venue staff queue
(story 13.1), approval and rejection (stories 13.2, 13.2.1) and the read endpoints 13.2 AC3 /
13.2.1 AC4 need to make the outcome visible to the requesting coordinator.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_permission
from app.auth.permissions import Permission
from app.bookings import service
from app.bookings.schemas import (
    BookableEvent,
    BookingOut,
    BookingOutcome,
    BookingQueueEntry,
    BookingReferenceData,
    BookingRejection,
    BookingRequestIn,
)
from app.db import get_db

router = APIRouter(prefix="/bookings", tags=["bookings"])

CanRead = Depends(require_permission(Permission.BOOKINGS_READ))
CanRequest = Depends(require_permission(Permission.BOOKINGS_REQUEST))
CanDecide = Depends(require_permission(Permission.BOOKINGS_DECIDE))
DbSession = Annotated[Session, Depends(get_db)]

BOOKING_NOT_FOUND_MESSAGE = "Booking request not found."
EVENT_NOT_FOUND_MESSAGE = "Event not found."
VENUE_NOT_FOUND_MESSAGE = "Venue not found."


@router.get("/reference-data", response_model=BookingReferenceData)
def reference_data(
    db: DbSession, actor: Annotated[CurrentUser, CanRequest]
) -> BookingReferenceData:
    """Story 12.1 AC1/AC4: the events this coordinator may raise a booking for. Declared above
    ``/{booking_id}`` so the literal path is not read as a booking id."""
    data = service.list_reference_data(db, actor=actor)
    return BookingReferenceData(
        events=[BookableEvent.model_validate(event) for event in data["events"]]
    )


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
def create_booking_request(
    payload: BookingRequestIn,
    db: DbSession,
    actor: Annotated[CurrentUser, CanRequest],
) -> BookingOut:
    """Story 12.1 AC1/AC2/AC3: raises one PENDING request for one venue, carrying the event's
    period, attendance, layout and required facilities. AC4: only the event's assigned
    coordinator may raise it.
    """
    try:
        booking = service.create_booking_request(db, payload, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.VenueNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, VENUE_NOT_FOUND_MESSAGE) from None
    except service.NotAssignedCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.EventNotBookable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.VenueNotBookable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return BookingOut.model_validate(booking)


@router.get("", response_model=list[BookingQueueEntry], dependencies=[CanDecide])
def list_bookings(db: DbSession) -> list[BookingQueueEntry]:
    """Story 13.1 AC1-AC3: every pending request, for Venue Staff to decide."""
    return [BookingQueueEntry.from_booking(b) for b in service.list_booking_requests(db)]


@router.get("/for-event/{event_id}", response_model=list[BookingOutcome], dependencies=[CanRead])
def list_bookings_for_event(event_id: uuid.UUID, db: DbSession) -> list[BookingOutcome]:
    """13.2.1 AC4: every venue booking ever raised for this event, most recent first - lets a
    coordinator read the full history directly on the event page, without knowing any booking's
    id up front. Declared above ``/{booking_id}`` so the literal path is not read as a booking
    id, same as ``/reference-data`` above."""
    return [BookingOutcome.from_booking(b) for b in service.list_bookings_for_event(db, event_id)]


@router.get("/{booking_id}", response_model=BookingOut, dependencies=[CanRead])
def get_booking(booking_id: uuid.UUID, db: DbSession) -> BookingOut:
    """AC3: lets the requesting coordinator (and other internal staff) read the outcome."""
    try:
        return BookingOut.model_validate(service.get_booking(db, booking_id))
    except service.BookingNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, BOOKING_NOT_FOUND_MESSAGE) from None


@router.post("/{booking_id}/approve", response_model=BookingOut)
def approve_booking(
    booking_id: uuid.UUID,
    db: DbSession,
    actor: Annotated[CurrentUser, CanDecide],
) -> BookingOut:
    """AC1: sets the booking to confirmed, recording the approver and time. AC4: refused where
    the period conflicts with an existing confirmed booking.
    """
    try:
        booking = service.get_booking_for_decision(db, booking_id)
    except service.BookingNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, BOOKING_NOT_FOUND_MESSAGE) from None
    try:
        service.approve_booking(db, booking, actor_id=actor.id)
    except service.BookingNotPending as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.BookingConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return BookingOut.model_validate(booking)


@router.post("/{booking_id}/reject", response_model=BookingOut)
def reject_booking(
    booking_id: uuid.UUID,
    payload: BookingRejection,
    db: DbSession,
    actor: Annotated[CurrentUser, CanDecide],
) -> BookingOut:
    """13.2.1 AC1/AC2: rejects the booking with a mandatory reason. AC6: never runs the
    venue-conflict check - a rejected request never reserves the venue.
    """
    try:
        booking = service.get_booking_for_decision(db, booking_id)
    except service.BookingNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, BOOKING_NOT_FOUND_MESSAGE) from None
    try:
        service.reject_booking(
            db, booking, actor_id=actor.id, decision_reason=payload.decision_reason
        )
    except service.BookingNotPending as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return BookingOut.model_validate(booking)
