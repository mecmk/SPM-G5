"""HTTP endpoints for story 18.1: the events an attendee can browse and register for, and
registering for one; and for story 18.2: the attendee's own registrations, and withdrawing one.

18.2's withdrawal is ``POST .../withdraw``, an action URL like 12.2's booking and 19.1's change
request withdrawals: a state transition with its own rules and audit record.

Story 18.3: an event's registration list, under ``/events``, and the events whose list the viewer
may open.

Story 18.4: the attendee's own profile, under ``/profile``. The URL names no attendee: it is always
the signed-in one's (AC10).

Story 18.5: the guests registered with an attendee, sent with the registration and replaced whole
afterwards with ``PUT /registrations/{registration_id}/guests`` (AC3).
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
    AttendeeDetailsIn,
    EventRegistrationListOut,
    EventRegistrationOut,
    GuestsUpdate,
    ManagedRegistrationEventOut,
    MyRegistrationOut,
    ProfileOut,
    RegistrationCreate,
    RegistrationEventList,
    RegistrationEventOut,
    RegistrationOut,
)

router = APIRouter(prefix="/registrations", tags=["registrations"])
events_router = APIRouter(prefix="/events", tags=["registrations"])
profile_router = APIRouter(prefix="/profile", tags=["registrations"])

CanRegister = Depends(require_permission(Permission.REGISTRATIONS_SELF))
CanViewRegistrations = Depends(require_permission(Permission.REGISTRATIONS_VIEW))
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


@router.get("/managed", response_model=list[ManagedRegistrationEventOut])
def list_managed_registration_events(
    db: DbSession, viewer: Annotated[CurrentUser, CanViewRegistrations]
) -> list[ManagedRegistrationEventOut]:
    """18.3 AC5: the events, past draft, that the signed-in organiser or coordinator manages and
    that take or hold registrations, for the registrations report to pick from.
    registrations:view only - other roles get 403 and signed-out users 401 from the
    dependency."""
    return [
        ManagedRegistrationEventOut.from_event(event)
        for event in service.list_managed_registration_events(db, viewer=viewer)
    ]


@router.post("", response_model=RegistrationOut, status_code=status.HTTP_201_CREATED)
def register(
    data: RegistrationCreate,
    db: DbSession,
    attendee: Annotated[CurrentUser, CanRegister],
) -> RegistrationOut:
    """AC1: register the signed-in attendee, stamped with this moment. AC3/AC4: an event not
    open for registration is a 404. AC2/AC6: not yet open, closed, full or already registered is
    a 409 naming which. AC5: registrations:self only. 18.4 AC7: details that would leave no phone
    number on file are a 422. 18.5 AC1: the guests sent with it are registered with it, and named
    back; AC1/AC6: guests outside the rules are a 422, and AC2: a group that does not fit a 409."""
    try:
        registration = service.register(db, data, attendee=attendee, now=datetime.now(UTC))
    except service.PhoneNumberRequired as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except service.RegistrationEventNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except service.RegistrationRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return RegistrationOut.from_registration(
        registration, guests=service.list_guests(db, registration.id)
    )


def _my_registration_out(item: service.MyRegistrationItem) -> MyRegistrationOut:
    return MyRegistrationOut.from_registration(
        item.registration,
        event=item.event,
        status=item.standing,
        can_withdraw=item.can_withdraw,
        guests=item.guests,
        can_change_guests=item.can_change_guests,
        max_guests=item.max_guests,
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


@router.put("/{registration_id}/guests", response_model=MyRegistrationOut)
def update_guests(
    registration_id: uuid.UUID,
    data: GuestsUpdate,
    db: DbSession,
    attendee: Annotated[CurrentUser, CanRegister],
) -> MyRegistrationOut:
    """18.5 AC3: replace the guests of the signed-in attendee's registration, and answer with it
    as My registrations shows it. AC1/AC6: guests outside the rules are a 422. AC3: closed,
    withdrawn, cancelled or more guests than the places left is a 409 naming which. AC10: another
    attendee's registration is a 404, as an unknown one is; registrations:self only - other roles
    get 403 and signed-out users 401 from the dependency."""
    try:
        item = service.update_guests(
            db, registration_id, data, attendee=attendee, now=datetime.now(UTC)
        )
    except service.RegistrationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except service.GuestsChangeRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return _my_registration_out(item)


@events_router.get("/{event_id}/registrations", response_model=EventRegistrationListOut)
def list_event_registrations(
    event_id: uuid.UUID,
    db: DbSession,
    viewer: CurrentUser,
    limit: Annotated[
        int, Query(ge=1, le=service.REGISTRATION_LIST_MAX_LIMIT)
    ] = service.REGISTRATION_LIST_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0, le=service.REGISTRATION_LIST_MAX_OFFSET)] = 0,
) -> EventRegistrationListOut:
    """18.3 AC1-AC4/AC7: one page of the event's registrations, how many there are, and its
    active count against capacity. 18.4 AC5/AC9: each Registered row with the attendee's phone
    number and dietary requirements. 18.5 AC4/AC9: each row with its guests, counted as places.
    AC5/AC6: any signed-in user may ask, but only the organiser and the assigned coordinator of an
    event past draft get an answer - anyone else, like an unknown id, a 404. Signed out is a
    401."""
    try:
        listing = service.list_event_registrations(
            db, event_id, viewer=viewer, limit=limit, offset=offset
        )
    except service.RegistrationListNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return EventRegistrationListOut(
        items=[
            EventRegistrationOut.from_registration(
                item.registration,
                attendee=item.attendee,
                status=item.standing,
                shows_details=item.shows_details,
                guests=item.guests,
            )
            for item in listing.items
        ],
        total=listing.total,
        active_count=listing.active_count,
        capacity=listing.capacity,
        is_full=listing.is_full,
    )


@profile_router.get("", response_model=ProfileOut)
def get_profile(attendee: Annotated[CurrentUser, CanRegister]) -> ProfileOut:
    """18.4 AC1: the signed-in attendee's name, email and details. AC10: their own only, and
    registrations:self only - other roles get 403 and signed-out users 401 from the dependency."""
    return ProfileOut.from_user(attendee)


@profile_router.patch("", response_model=ProfileOut)
def update_profile(
    data: AttendeeDetailsIn,
    db: DbSession,
    attendee: Annotated[CurrentUser, CanRegister],
) -> ProfileOut:
    """18.4 AC4: change the signed-in attendee's details - their name among them (AC1) - and
    answer with the profile as saved. AC1/AC6/AC7: details outside the rules are a 422 naming the
    field, and so is a save that would leave no phone number on file. AC10: an email or an id sent
    with them is a 422 too."""
    try:
        saved = service.update_profile(db, data, attendee=attendee, now=datetime.now(UTC))
    except service.PhoneNumberRequired as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return ProfileOut.from_user(saved)
