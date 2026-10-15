"""HTTP endpoints for story 18.1: the events an attendee can browse and register for, and
registering for one; and for story 18.2: the attendee's own registrations, and withdrawing one.

18.2's withdrawal is ``POST .../withdraw``, an action URL like 12.2's booking and 19.1's change
request withdrawals: a state transition with its own rules and audit record.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_permission
from app.auth.permissions import Permission
from app.db import get_db
from app.registrations import service
from app.registrations.schemas import (
    MyRegistrationOut,
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


def _my_registration_out(item: service.MyRegistrationItem) -> MyRegistrationOut:
    return MyRegistrationOut.from_registration(
        item.registration, event=item.event, status=item.standing, can_withdraw=item.can_withdraw
    )


@router.get("", response_model=list[MyRegistrationOut])
def list_my_registrations(
    db: DbSession,
    attendee: Annotated[CurrentUser, CanRegister],
) -> list[MyRegistrationOut]:
    """18.2 AC1: the signed-in attendee's registrations, one per event, events not yet started
    first. AC6: only the caller's - no query parameter can name another attendee - and
    registrations:self only: other roles get 403 and signed-out users 401 from the dependency."""
    items = service.list_my_registrations(db, attendee=attendee, now=datetime.now(UTC))
    return [_my_registration_out(item) for item in items]


@router.post("/{registration_id}/withdraw", response_model=MyRegistrationOut)
def withdraw_registration(
    registration_id: uuid.UUID,
    db: DbSession,
    attendee: Annotated[CurrentUser, CanRegister],
) -> MyRegistrationOut:
    """18.2 AC1/AC2: withdraw the signed-in attendee's registration, stamped with this moment.
    AC6: another attendee's registration is a 404, as an unknown one is. AC3/AC7/AC8: an event
    that has started, a registration already withdrawn or a cancelled event is a 409 naming
    which."""
    try:
        item = service.withdraw_registration(
            db, registration_id, attendee=attendee, now=datetime.now(UTC)
        )
    except service.RegistrationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except service.WithdrawalRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return _my_registration_out(item)
