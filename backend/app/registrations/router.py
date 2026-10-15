"""HTTP endpoints for story 18.1: the events an attendee can browse and register for, and
registering for one."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_permission
from app.auth.permissions import Permission
from app.db import get_db
from app.registrations import service
from app.registrations.schemas import (
    RegistrationCreate,
    RegistrationEventList,
    RegistrationEventOut,
    RegistrationOut,
)

router = APIRouter(prefix="/registrations", tags=["registrations"])

CanRegister = Depends(require_permission(Permission.REGISTRATIONS_SELF))
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/events", response_model=RegistrationEventList)
def list_registration_events(
    db: DbSession,
    attendee: Annotated[CurrentUser, CanRegister],
    limit: Annotated[
        int, Query(ge=1, le=service.REGISTRATION_EVENTS_MAX_LIMIT)
    ] = service.REGISTRATION_EVENTS_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0, le=service.REGISTRATION_EVENTS_MAX_OFFSET)] = 0,
) -> RegistrationEventList:
    """AC1: one page of the events the signed-in attendee can register for, soonest first, each
    with its places left and its state for this attendee, and how many there are in all. AC5:
    registrations:self only - other roles get 403 and signed-out users 401 from the
    dependency."""
    listing = service.list_registration_events(
        db, attendee=attendee, now=datetime.now(UTC), limit=limit, offset=offset
    )
    return RegistrationEventList(
        items=[
            RegistrationEventOut.from_event(
                item.event,
                venues=item.venues,
                closes_at=item.closes_at,
                places_left=item.places_left,
                state=item.state,
                registered_at=item.registered_at,
            )
            for item in listing.items
        ],
        total=listing.total,
    )


@router.post("", response_model=RegistrationOut, status_code=status.HTTP_201_CREATED)
def register(
    data: RegistrationCreate,
    db: DbSession,
    attendee: Annotated[CurrentUser, CanRegister],
) -> RegistrationOut:
    """AC1: register the signed-in attendee, stamped with this moment. AC3/AC4: an event not
    open for registration is a 404. AC2/AC6: not yet open, closed, full or already registered is
    a 409 naming which. AC5: registrations:self only."""
    try:
        registration = service.register(db, data, attendee=attendee, now=datetime.now(UTC))
    except service.RegistrationEventNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except service.RegistrationRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return RegistrationOut.from_registration(registration)
