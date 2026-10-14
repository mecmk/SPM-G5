"""Business rules for story 18.1: the events an attendee can register for, and registering.

An event is open to attendees when it is Confirmed (AC4, 21.2), Public (2.1 AC19: Private events
are reachable only by a shared link, which no story has built yet) and needs registration (2.1
AC17). It is listed until it starts (AC3), and its capacity is its expected attendance (2.1 AC17,
AC2). Only a REGISTERED row takes a place.

AC7: ``register`` holds the event's row (``FOR NO KEY UPDATE``) while it checks the event and
counts the places, so two registrations for one event take turns, and an event cancelled or sent
back to Planning meanwhile is read as it now stands. It inserts first and counts after, so the
database's ``uq_event_registrations_active`` refuses a duplicate even from two tabs at once, and a
place over capacity is rolled back - no check runs ahead of the write it guards
(backend/STYLE.md).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ColumnElement, Select, and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth.models import User
from app.bookings.models import BookingStatus, VenueBooking
from app.common.audit import record_audit
from app.events.models import Event, EventStatus
from app.registrations.models import EventRegistration, RegistrationStatus
from app.registrations.schemas import RegistrationCreate
from app.venues.models import Venue

# AC1: the list comes a page at a time; the page asks for this many unless it says otherwise.
REGISTRATION_EVENTS_PAGE_SIZE = 20
REGISTRATION_EVENTS_MAX_LIMIT = 100
REGISTRATION_EVENTS_MAX_OFFSET = 2_147_483_647
# AC6/AC7: the index that keeps one active registration per attendee per event.
ACTIVE_REGISTRATION_INDEX = "uq_event_registrations_active"
REGISTRATION_CREATED_ACTION = "EVENT_REGISTRATION_CREATED"
_REGISTRATION_ENTITY = "event_registration"

REGISTRATION_EVENT_NOT_FOUND_MESSAGE = "This event is not open for registration."
REGISTRATION_NOT_YET_OPEN_MESSAGE = "Registration for this event has not opened yet."
REGISTRATION_CLOSED_MESSAGE = "Registration for this event has closed."
EVENT_FULL_MESSAGE = "This event is full."
ALREADY_REGISTERED_MESSAGE = "You are already registered for this event."


class RegistrationState(StrEnum):
    """AC1/AC3: where an event stands for the attendee looking at it."""

    OPEN = "OPEN"
    NOT_YET_OPEN = "NOT_YET_OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"
    REGISTERED = "REGISTERED"


class RegistrationEventNotFound(LookupError):
    """AC3/AC4: no event with this id is open to attendees - unknown, not Confirmed, Private, or
    not taking registrations. One answer for all, so a Private event's existence is not given
    away."""

    def __init__(self) -> None:
        super().__init__(REGISTRATION_EVENT_NOT_FOUND_MESSAGE)


class RegistrationRefused(Exception):
    """AC2/AC6: the event is open to attendees, but this registration cannot be taken."""


class RegistrationNotYetOpen(RegistrationRefused):
    def __init__(self) -> None:
        super().__init__(REGISTRATION_NOT_YET_OPEN_MESSAGE)


class RegistrationClosed(RegistrationRefused):
    def __init__(self) -> None:
        super().__init__(REGISTRATION_CLOSED_MESSAGE)


class EventFull(RegistrationRefused):
    def __init__(self) -> None:
        super().__init__(EVENT_FULL_MESSAGE)


class AlreadyRegistered(RegistrationRefused):
    def __init__(self) -> None:
        super().__init__(ALREADY_REGISTERED_MESSAGE)


@dataclass(frozen=True)
class RegistrationEventItem:
    """AC1: one listed event, with what the attendee sees of it."""

    event: Event
    venues: list[Venue]
    closes_at: datetime
    places_left: int
    state: RegistrationState
    registered_at: datetime | None  # when this attendee registered, if they have


@dataclass(frozen=True)
class RegistrationEventListing:
    """AC1: one page of the list, and how many events it holds in all."""

    items: list[RegistrationEventItem]
    total: int


def places_left(*, capacity: int, registered: int) -> int:
    """AC2: the places not yet taken. Never below 0: a change request (19.2) can lower the
    expected attendance below the registrations already made, which leaves the event full."""
    return max(capacity - registered, 0)


def closing_time(*, closes_at: datetime | None, starts_at: datetime) -> datetime:
    """AC2: when registration closes - the closing time, or the event's start where none was
    recorded. ``ck_events_registration_closes_before_start`` keeps a recorded one no later."""
    return starts_at if closes_at is None else closes_at


def window_state(
    *, now: datetime, opens_at: datetime | None, closes_at: datetime
) -> RegistrationState:
    """AC2: OPEN, NOT_YET_OPEN or CLOSED by time alone. Open from the opening moment, if one was
    set; closed from the closing moment on."""
    if now >= closes_at:
        return RegistrationState.CLOSED
    if opens_at is not None and now < opens_at:
        return RegistrationState.NOT_YET_OPEN
    return RegistrationState.OPEN


def registration_state(
    *,
    now: datetime,
    opens_at: datetime | None,
    closes_at: datetime,
    places_left: int,
    is_registered: bool,
) -> RegistrationState:
    """AC3: the state an event is listed in for one attendee. Their own registration comes first;
    then time, since a closed event stays closed whatever places it has; then places."""
    if is_registered:
        return RegistrationState.REGISTERED
    by_time = window_state(now=now, opens_at=opens_at, closes_at=closes_at)
    if by_time is not RegistrationState.OPEN:
        return by_time
    if places_left == 0:
        return RegistrationState.FULL
    return RegistrationState.OPEN


def _is_open_to_attendees() -> ColumnElement[bool]:
    """AC3/AC4: Confirmed, Public and taking registrations."""
    return and_(
        Event.status == EventStatus.CONFIRMED,
        Event.is_public.is_(True),
        Event.registration_required.is_(True),
    )


def _active_registrations(event_id: ColumnElement[uuid.UUID] | uuid.UUID) -> Select[tuple[int]]:
    """AC2: the registrations that take a place at the event - REGISTERED ones only. Counted
    from ``uq_event_registrations_active``, whose rows are exactly these."""
    return select(func.count()).where(
        EventRegistration.event_id == event_id,
        EventRegistration.status == RegistrationStatus.REGISTERED,
    )


def _booked_venues(db: Session, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Venue]]:
    """AC1: each event's venues - those of its approved bookings, in the order they start, each
    venue once even when booked more than once."""
    bookings = db.scalars(
        select(VenueBooking)
        .options(joinedload(VenueBooking.venue))
        .where(VenueBooking.event_id.in_(event_ids), VenueBooking.status == BookingStatus.APPROVED)
        .order_by(VenueBooking.starts_at, VenueBooking.id)
    ).all()
    venues: dict[uuid.UUID, list[Venue]] = defaultdict(list)
    for booking in bookings:
        if booking.venue not in venues[booking.event_id]:
            venues[booking.event_id].append(booking.venue)
    return venues


def list_registration_events(
    db: Session, *, attendee: User, now: datetime, limit: int, offset: int
) -> RegistrationEventListing:
    """AC1: one page of the events open to attendees that have not started, soonest first (then
    by name, then id, so pages never overlap), each with its venues, places left and its state
    for ``attendee``. AC3: full, closed and not-yet-open events stay listed until they start.
    Filtered, ordered, paged and counted in SQL."""
    is_listed = and_(_is_open_to_attendees(), Event.starts_at > now)
    registered = _active_registrations(Event.id).correlate(Event).scalar_subquery()
    mine = (
        select(EventRegistration.registered_at)
        .where(
            EventRegistration.event_id == Event.id,
            EventRegistration.attendee_id == attendee.id,
            EventRegistration.status == RegistrationStatus.REGISTERED,
        )
        .correlate(Event)
        .scalar_subquery()
    )
    rows = db.execute(
        select(Event, registered, mine)
        .where(is_listed)
        .order_by(Event.starts_at, Event.name, Event.id)
        .limit(limit)
        .offset(offset)
    ).all()
    total = db.scalar(select(func.count()).select_from(Event).where(is_listed))
    venues = _booked_venues(db, [event.id for event, _, _ in rows])
    items = []
    for event, taken, registered_at in rows:
        # ck_events_submitted_fields_complete: a Confirmed event has its dates and attendance.
        assert event.starts_at is not None
        assert event.expected_attendance is not None
        closes_at = closing_time(closes_at=event.registration_closes_at, starts_at=event.starts_at)
        left = places_left(capacity=event.expected_attendance, registered=taken)
        items.append(
            RegistrationEventItem(
                event=event,
                venues=venues[event.id],
                closes_at=closes_at,
                places_left=left,
                state=registration_state(
                    now=now,
                    opens_at=event.registration_opens_at,
                    closes_at=closes_at,
                    places_left=left,
                    is_registered=registered_at is not None,
                ),
                registered_at=registered_at,
            )
        )
    return RegistrationEventListing(items=items, total=total or 0)


def register(
    db: Session, data: RegistrationCreate, *, attendee: User, now: datetime
) -> EventRegistration:
    """AC1: register ``attendee`` for the event, stamped ``now``, and audit it. AC7: holding the
    event's row, so every check below reads the event and its places as they stand at this moment.

    Raises ``RegistrationEventNotFound`` (AC3/AC4) unless the event is open to attendees, then
    ``RegistrationClosed`` or ``RegistrationNotYetOpen`` (AC2), ``AlreadyRegistered`` (AC6) and
    ``EventFull`` (AC2/AC6), in that order. A refused registration leaves nothing written."""
    event = db.execute(
        select(
            Event.id,
            Event.expected_attendance,
            Event.starts_at,
            Event.registration_opens_at,
            Event.registration_closes_at,
        )
        .where(Event.id == data.event_id, _is_open_to_attendees())
        .with_for_update(key_share=True)
    ).one_or_none()
    if event is None:
        raise RegistrationEventNotFound()
    by_time = window_state(
        now=now,
        opens_at=event.registration_opens_at,
        closes_at=closing_time(closes_at=event.registration_closes_at, starts_at=event.starts_at),
    )
    if by_time is RegistrationState.CLOSED:
        raise RegistrationClosed()
    if by_time is RegistrationState.NOT_YET_OPEN:
        raise RegistrationNotYetOpen()

    registration = EventRegistration(event_id=event.id, attendee_id=attendee.id, registered_at=now)
    db.add(registration)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if ACTIVE_REGISTRATION_INDEX in str(exc.orig):
            raise AlreadyRegistered() from exc
        raise
    if db.scalar(_active_registrations(event.id)) > event.expected_attendance:
        db.rollback()
        raise EventFull()

    record_audit(
        db,
        actor=attendee,
        action=REGISTRATION_CREATED_ACTION,
        entity_type=_REGISTRATION_ENTITY,
        entity_id=registration.id,
        details={"event_id": str(event.id)},
        commit=False,
    )
    db.commit()
    return registration
