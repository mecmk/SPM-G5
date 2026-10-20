"""Business rules for story 18.1: the events an attendee can register for, and registering; and
for story 18.2: the attendee's own registrations, and withdrawing one (its section at the end).

An event is open to attendees when it is Confirmed (AC4, 21.2), Public (2.1 AC19: a Private
event is not listed) and needs registration (2.1 AC17). It is listed until it starts (AC3), and
its capacity is its expected attendance (2.1 AC17, AC2). Only a REGISTERED row takes a place.

AC7: ``register`` holds the event's row (``FOR NO KEY UPDATE``) while it checks the event and
counts the places, so two registrations for one event take turns, and an event cancelled or sent
back to Planning meanwhile is read as it now stands. It inserts first and counts after, so the
database's ``uq_event_registrations_active`` refuses a duplicate even from two tabs at once, and a
place over capacity is rolled back - no check runs ahead of the write it guards
(backend/STYLE.md).

Story 18.3: an event's registration list, for its organiser and assigned coordinator once it is
past draft - anyone else is told the event was not found (AC5/AC6), as an unknown event is. Every
registration is listed, a page at a time, each with 18.2's standing (AC4); only those still
Registered count, so a cancelled event counts none.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ColumnElement, Select, and_, case, func, null, or_, select, update
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
# 18.3 AC1: an event's registration list comes a page at a time too.
REGISTRATION_LIST_PAGE_SIZE = 50
REGISTRATION_LIST_MAX_LIMIT = 100
REGISTRATION_LIST_MAX_OFFSET = 2_147_483_647
# AC6/AC7: the index that keeps one active registration per attendee per event.
ACTIVE_REGISTRATION_INDEX = "uq_event_registrations_active"
REGISTRATION_CREATED_ACTION = "EVENT_REGISTRATION_CREATED"
_REGISTRATION_ENTITY = "event_registration"

REGISTRATION_EVENT_NOT_FOUND_MESSAGE = "This event is not open for registration."
REGISTRATION_NOT_YET_OPEN_MESSAGE = "Registration for this event has not opened yet."
REGISTRATION_CLOSED_MESSAGE = "Registration for this event has closed."
EVENT_FULL_MESSAGE = "This event is full."
ALREADY_REGISTERED_MESSAGE = "You are already registered for this event."
REGISTRATION_LIST_NOT_FOUND_MESSAGE = "This event was not found."


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


class RegistrationListNotFound(LookupError):
    """18.3 AC5/AC6: no event with this id whose list the viewer may view - unknown, someone
    else's, or still a draft. One answer for all, so the list gives nothing away."""

    def __init__(self) -> None:
        super().__init__(REGISTRATION_LIST_NOT_FOUND_MESSAGE)


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


@dataclass(frozen=True)
class AttendeeRegistration:
    """18.3 AC1/AC4: one row of an event's registration list - the registration, who made it,
    and where they stand (18.2's standing)."""

    registration: EventRegistration
    attendee: User
    standing: RegistrationStanding


@dataclass(frozen=True)
class EventRegistrationList:
    """18.3 AC1-AC3/AC7: one page of an event's registrations, oldest first; how many there are
    in all; how many are active against its capacity; and whether that count has reached it."""

    items: list[AttendeeRegistration]
    total: int
    active_count: int
    capacity: int
    is_full: bool


def places_left(*, capacity: int, registered: int) -> int:
    """AC2: the places not yet taken. Never below 0: a change request (19.2) can lower the
    expected attendance below the registrations already made, which leaves the event full."""
    return max(capacity - registered, 0)


def is_full(*, capacity: int, active: int) -> bool:
    """18.3 AC3: full once the active registrations reach the capacity. Beyond it is still full,
    as a change request (19.2) can lower the expected attendance."""
    return active >= capacity


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


def cancel_for_event(db: Session, event_id: uuid.UUID) -> list[uuid.UUID]:
    """Story 6.2 AC4: the event was cancelled, so every registration still holding a place is
    closed as Cancelled - by ConnectSphere, not withdrawn by the attendee - and kept for the
    record. Returns the attendees whose place it was, to be told (AC5). The caller holds the
    event's row lock, which ``register`` also takes, so no registration lands meanwhile. Written,
    not committed."""
    return list(
        db.scalars(
            update(EventRegistration)
            .where(
                EventRegistration.event_id == event_id,
                EventRegistration.status == RegistrationStatus.REGISTERED,
            )
            .values(status=RegistrationStatus.CANCELLED)
            .returning(EventRegistration.attendee_id)
        )
    )


# =============================================================================================
# Story 18.2: the attendee's own registrations, and withdrawing one
# =============================================================================================
REGISTRATION_WITHDRAWN_ACTION = "EVENT_REGISTRATION_WITHDRAWN"

REGISTRATION_NOT_FOUND_MESSAGE = "This registration was not found."
ALREADY_WITHDRAWN_MESSAGE = "You have already withdrawn from this event."
EVENT_STARTED_MESSAGE = "This event has started, so you can no longer withdraw."
WITHDRAWAL_EVENT_CANCELLED_MESSAGE = (
    "This event was cancelled, so there is nothing to withdraw from."
)


class RegistrationStanding(StrEnum):
    """18.2 AC1/AC8: where the attendee stands with an event they registered for."""

    REGISTERED = "REGISTERED"
    WITHDRAWN = "WITHDRAWN"
    EVENT_CANCELLED = "EVENT_CANCELLED"


class RegistrationNotFound(LookupError):
    """18.2 AC6: no registration with this id is the attendee's - unknown, or another attendee's.
    One answer for both, so another attendee's registration is not given away."""

    def __init__(self) -> None:
        super().__init__(REGISTRATION_NOT_FOUND_MESSAGE)


class WithdrawalRefused(Exception):
    """18.2 AC3/AC7/AC8: the registration is the attendee's, but it cannot be withdrawn."""


class AlreadyWithdrawn(WithdrawalRefused):
    def __init__(self) -> None:
        super().__init__(ALREADY_WITHDRAWN_MESSAGE)


class WithdrawalEventCancelled(WithdrawalRefused):
    def __init__(self) -> None:
        super().__init__(WITHDRAWAL_EVENT_CANCELLED_MESSAGE)


class EventStarted(WithdrawalRefused):
    def __init__(self) -> None:
        super().__init__(EVENT_STARTED_MESSAGE)


@dataclass(frozen=True)
class MyRegistrationItem:
    """18.2 AC1: one of the attendee's registrations, with its event, where they stand, and
    whether it can be withdrawn now (AC3)."""

    registration: EventRegistration
    event: Event
    standing: RegistrationStanding
    can_withdraw: bool


def registration_standing(*, registration_status: str, event_status: str) -> RegistrationStanding:
    """18.2 AC1/AC8: Withdrawn when the attendee withdrew, whatever became of the event; Event
    cancelled when the registration was cancelled with its event (6.2), or the event was
    cancelled with it still active (an event sent back to Planning after confirmation keeps its
    registrations, 18.1 AC4); Registered otherwise, including an event sent back to Planning."""
    if registration_status == RegistrationStatus.WITHDRAWN:
        return RegistrationStanding.WITHDRAWN
    if registration_status == RegistrationStatus.CANCELLED or event_status == EventStatus.CANCELLED:
        return RegistrationStanding.EVENT_CANCELLED
    return RegistrationStanding.REGISTERED


def can_withdraw(*, standing: RegistrationStanding, now: datetime, starts_at: datetime) -> bool:
    """18.2 AC3/AC8: an active registration, until the moment its event starts."""
    return standing is RegistrationStanding.REGISTERED and now < starts_at


def withdrawal_refusal(*, standing: RegistrationStanding) -> WithdrawalRefused:
    """18.2 AC3/AC7/AC8: why an attendee's own registration could not be withdrawn - already
    withdrawn (a second click); its event cancelled, whether the registration was cancelled with
    it or is still active on it; or, being still active, because its event has started."""
    if standing is RegistrationStanding.WITHDRAWN:
        return AlreadyWithdrawn()
    if standing is RegistrationStanding.EVENT_CANCELLED:
        return WithdrawalEventCancelled()
    return EventStarted()


def _my_registration_item(
    registration: EventRegistration, event: Event, *, now: datetime
) -> MyRegistrationItem:
    # Registrations are only taken for Confirmed events, and ck_events_submitted_fields_complete
    # keeps a start on every event past Draft.
    assert event.starts_at is not None
    standing = registration_standing(
        registration_status=registration.status, event_status=event.status
    )
    return MyRegistrationItem(
        registration=registration,
        event=event,
        standing=standing,
        can_withdraw=can_withdraw(standing=standing, now=now, starts_at=event.starts_at),
    )


def _latest_per_event(attendee: User) -> Select[tuple[uuid.UUID]]:
    """18.2 AC1/AC4: the id of ``attendee``'s newest registration for each event - the active one
    once they have registered again, since it was made after the withdrawal. The id settles a
    tie, so the same one is listed every time."""
    return (
        select(EventRegistration.id)
        .where(EventRegistration.attendee_id == attendee.id)
        .distinct(EventRegistration.event_id)
        .order_by(
            EventRegistration.event_id,
            EventRegistration.registered_at.desc(),
            EventRegistration.id.desc(),
        )
    )


def list_my_registrations(
    db: Session, *, attendee: User, now: datetime
) -> list[MyRegistrationItem]:
    """18.2 AC1: ``attendee``'s registrations, one per event - the latest - with each event and
    where they stand. Events not yet started come first, soonest first; then those that have
    started (one starting at ``now`` has, AC3), latest first; then by name, then id. AC5/AC6:
    only ``attendee``'s own. Chosen and ordered in SQL. Not paged: the list grows by one entry for
    each event the attendee registers for, and one attendee's list stays short."""
    # Events not yet started by their start; those that have started have none here, so they come
    # after them all, and then go latest first.
    upcoming_start = case((Event.starts_at <= now, null()), else_=Event.starts_at)
    rows = db.execute(
        select(EventRegistration, Event)
        .join(Event, Event.id == EventRegistration.event_id)
        .where(EventRegistration.id.in_(_latest_per_event(attendee)))
        .order_by(
            upcoming_start.asc().nulls_last(),
            Event.starts_at.desc(),
            Event.name,
            Event.id,
        )
    ).all()
    return [_my_registration_item(registration, event, now=now) for registration, event in rows]


def _is_withdrawable(now: datetime) -> ColumnElement[bool]:
    """18.2 AC3/AC8: the registration's event is not cancelled and has not started."""
    return (
        select(Event.id)
        .where(
            Event.id == EventRegistration.event_id,
            Event.status != EventStatus.CANCELLED,
            Event.starts_at > now,
        )
        .exists()
    )


def withdraw_registration(
    db: Session, registration_id: uuid.UUID, *, attendee: User, now: datetime
) -> MyRegistrationItem:
    """18.2 AC1/AC2: withdraw ``attendee``'s registration, stamped ``now``, and audit it, all in
    one commit: the place is free once the row is no longer REGISTERED (18.1 AC2), and if the
    audit entry cannot be written nothing is.

    AC7: the update itself is conditional on the registration still being active, so of two
    withdrawals at once the second waits on the first's row lock and then matches nothing - no
    check runs ahead of the write it guards (backend/STYLE.md). The registration is read after
    the update, for the answer, and when nothing was written to say why: ``RegistrationNotFound``
    when it is not ``attendee``'s (AC6), else ``withdrawal_refusal`` (AC3/AC7/AC8)."""
    withdrawn = db.execute(
        update(EventRegistration)
        .where(
            EventRegistration.id == registration_id,
            EventRegistration.attendee_id == attendee.id,
            EventRegistration.status == RegistrationStatus.REGISTERED,
            _is_withdrawable(now),
        )
        .values(status=RegistrationStatus.WITHDRAWN, withdrawn_at=now)
    )
    found = db.execute(
        select(EventRegistration, Event)
        .join(Event, Event.id == EventRegistration.event_id)
        .where(
            EventRegistration.id == registration_id,
            EventRegistration.attendee_id == attendee.id,
        )
    ).one_or_none()
    if found is None:
        raise RegistrationNotFound()
    registration, event = found
    item = _my_registration_item(registration, event, now=now)
    if withdrawn.rowcount == 0:
        raise withdrawal_refusal(standing=item.standing)

    record_audit(
        db,
        actor=attendee,
        action=REGISTRATION_WITHDRAWN_ACTION,
        entity_type=_REGISTRATION_ENTITY,
        entity_id=registration.id,
        details={"event_id": str(event.id)},
        commit=False,
    )
    db.commit()
    return item


# =============================================================================================
# Story 18.3: an event's registration list, for its organiser and assigned coordinator
# =============================================================================================
def _registration_list_viewable_by(viewer: User) -> ColumnElement[bool]:
    """18.3 AC5/AC6: an event whose registration list ``viewer`` may view - past draft, and
    organised or coordinated by them. The list, the report's picker and the event page's card
    (EventDetailPage's ``canSeeRegistrations``) all apply this one rule."""
    return and_(
        Event.status != EventStatus.DRAFT,
        or_(Event.organiser_id == viewer.id, Event.assigned_coordinator_id == viewer.id),
    )


def _takes_or_holds_registrations() -> ColumnElement[bool]:
    """18.3 AC5: an event taking registrations, or holding some from when it did - 9.4 sends a
    Confirmed event back to Planning with its registrations, and 7.2 can then turn Registration
    required off. The picker and the event page's card both show such an event."""
    return or_(
        Event.registration_required.is_(True),
        select(EventRegistration.id).where(EventRegistration.event_id == Event.id).exists(),
    )


def _active_count() -> ColumnElement[int]:
    """18.3 AC1/AC7: how many of the counted registrations are REGISTERED."""
    return func.count().filter(EventRegistration.status == RegistrationStatus.REGISTERED)


def list_event_registrations(
    db: Session, event_id: uuid.UUID, *, viewer: User, limit: int, offset: int
) -> EventRegistrationList:
    """18.3 AC1/AC2/AC4: one page of the event's registrations, oldest first, each with its
    attendee and 18.2's standing. AC5/AC6: ``RegistrationListNotFound`` unless the event is
    viewable by ``viewer``.

    AC7: the total and active count are window counts over every row of the event, in the
    statement that reads the page, so a registration made meanwhile can never leave the count
    and the list apart. A page past the end has no row to carry them, so they are counted
    alone. A cancelled event's registrations, still active or not, count for none (18.2)."""
    event = db.scalar(
        select(Event).where(Event.id == event_id, _registration_list_viewable_by(viewer))
    )
    if event is None:
        raise RegistrationListNotFound()
    # ck_events_submitted_fields_complete: an event past draft has its expected attendance.
    assert event.expected_attendance is not None
    is_this_event = EventRegistration.event_id == event.id
    rows = db.execute(
        select(EventRegistration, User, func.count().over(), _active_count().over())
        .join(User, User.id == EventRegistration.attendee_id)
        .where(is_this_event)
        .order_by(EventRegistration.registered_at, EventRegistration.id)
        .limit(limit)
        .offset(offset)
    ).all()
    if rows:
        total, active = rows[0][2], rows[0][3]
    else:
        total, active = db.execute(select(func.count(), _active_count()).where(is_this_event)).one()
    if event.status == EventStatus.CANCELLED:
        active = 0
    return EventRegistrationList(
        items=[
            AttendeeRegistration(
                registration=registration,
                attendee=attendee,
                standing=registration_standing(
                    registration_status=registration.status, event_status=event.status
                ),
            )
            for registration, attendee, _, _ in rows
        ],
        total=total,
        active_count=active,
        capacity=event.expected_attendance,
        is_full=is_full(capacity=event.expected_attendance, active=active),
    )


def list_managed_registration_events(db: Session, *, viewer: User) -> list[Event]:
    """18.3 AC5: the events whose registration list ``viewer`` may view that take or hold
    registrations, soonest first, for the registrations report to pick from. Not paged: one
    organiser's or coordinator's events stay few, as 18.2's own registrations do."""
    return list(
        db.scalars(
            select(Event)
            .where(_registration_list_viewable_by(viewer), _takes_or_holds_registrations())
            .order_by(Event.starts_at, Event.id)
        )
    )
