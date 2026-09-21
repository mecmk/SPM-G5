"""HTTP endpoints for venue bookings: raising a request (story 12.1), approval (story 13.2)
and the read endpoint 13.2 AC3 needs to make the outcome visible to the requesting coordinator.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_permission
from app.auth.permissions import Permission
from app.bookings import service
from app.bookings.schemas import BookingOut, BookingRequestIn
from app.db import get_db

router = APIRouter(prefix="/bookings", tags=["bookings"])

CanRead = Depends(require_permission(Permission.BOOKINGS_READ))
CanRequest = Depends(require_permission(Permission.BOOKINGS_REQUEST))
CanDecide = Depends(require_permission(Permission.BOOKINGS_DECIDE))
DbSession = Annotated[Session, Depends(get_db)]

BOOKING_NOT_FOUND_MESSAGE = "Booking request not found."
EVENT_NOT_FOUND_MESSAGE = "Event not found."
VENUE_NOT_FOUND_MESSAGE = "Venue not found."


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
