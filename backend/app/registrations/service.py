"""Business rules for story 18.1: the events an attendee can register for, each one's page, and
registering; and for story 18.2: the attendee's own registrations, each one's event page, and
withdrawing one (its section at the end).

An event is open to attendees when it is Confirmed (AC4, 21.2), Public (2.1 AC19: a Private
event is not listed) and needs registration (2.1 AC17). It is listed until it starts (AC3), and
its capacity is its expected attendance (2.1 AC17, AC2). Only a REGISTERED row takes a place. A
listed event has a page (AC9, fix f18.1.2) showing what its entry in the list does, and so does
one the attendee registered for (18.2 AC10, fix f18.2.1); any other has none (AC10).

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

Story 18.4: the attendee's details - name, phone number and dietary requirements - live on their
user row, so a change shows everywhere at once (AC4). They are written on My profile and with a
registration, and the first registration needs them (AC2).

Story 18.5: an attendee registers with up to ten guests, as one group (AC1). Each guest takes a
place (AC2), so every count of places here - 18.1's places left, 18.3's active count and 19.3's
count of those affected (AC5) - is the Registered registrations plus their guests. Guests are
written with the registration and checked against the places as 18.1's place is: inserted first,
counted after, the event's row held (AC2, AC11). Changed afterwards with ``update_guests``
(AC3), their own section at the end.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    ColumnElement,
    Integer,
    Row,
    Select,
    and_,
    case,
    cast,
    delete,
    func,
    null,
    or_,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth.models import User
from app.bookings.models import BookingStatus, VenueBooking
from app.common.audit import record_audit
from app.events.models import Event, EventStatus
from app.registrations.models import EventRegistration, RegistrationGuest, RegistrationStatus
from app.registrations.schemas import (
    MAX_GUESTS,
    PHONE_NUMBER_REQUIRED_MESSAGE,
    AttendeeDetailsIn,
    GuestIn,
    GuestsUpdate,
    RegistrationCreate,
)
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
# Story 18.5 AC2: a group that does not fit. An attendee alone is still told EVENT_FULL_MESSAGE.
NOT_ENOUGH_PLACES_MESSAGE = "There are not enough places left for you and your guests."
ALREADY_REGISTERED_MESSAGE = "You are already registered for this event."
REGISTRATION_LIST_NOT_FOUND_MESSAGE = "This event was not found."
# Story 18.4: the attendee's details.
ATTENDEE_DETAILS_UPDATED_ACTION = "ATTENDEE_DETAILS_UPDATED"
_USER_ENTITY = "user"
ATTENDEE_DETAILS_REQUIRED_MESSAGE = (
    "Give your name and phone number before your first registration. Dietary requirements may be"
    " left blank."
)
# A first registration answers the questions, so the name and phone number travel with it even when
# the account already has them (story 18.4 AC2, review of #129).
_FIRST_REGISTRATION_FIELDS = frozenset({"full_name", "phone"})


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


class NotEnoughPlaces(RegistrationRefused):
    """Story 18.5 AC2: the attendee and their guests together need more places than are left."""

    def __init__(self) -> None:
        super().__init__(NOT_ENOUGH_PLACES_MESSAGE)


class PhoneNumberRequired(ValueError):
    """Story 18.4 AC7: the details sent would leave the attendee with no phone number on file - one
    who has never given one, sending none."""

    def __init__(self) -> None:
        super().__init__(PHONE_NUMBER_REQUIRED_MESSAGE)


class AttendeeDetailsRequired(RegistrationRefused):
    """Story 18.4 AC2: the attendee has never given their details, and their first registration
    did not send their name and phone number."""

    def __init__(self) -> None:
        super().__init__(ATTENDEE_DETAILS_REQUIRED_MESSAGE)


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
    and where they stand (18.2's standing). Story 18.4 AC5/AC9: whether the row shows the
    attendee's details - only while they are registered."""

    registration: EventRegistration
    attendee: User
    standing: RegistrationStanding
    shows_details: bool
    guests: list[RegistrationGuest]  # story 18.5 AC4, in the attendee's order


@dataclass(frozen=True)
class EventRegistrationList:
    """18.3 AC1-AC3/AC7: one page of an event's registrations, oldest first; how many there are
    in all; how many places the active ones take against its capacity, guests included (18.5
    AC4); and whether that count has reached it."""

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


def _guest_count() -> ColumnElement[int]:
    """Story 18.5 AC2: how many guests came with the registration in the enclosing statement."""
    return (
        select(func.count())
        .where(RegistrationGuest.registration_id == EventRegistration.id)
        .correlate(EventRegistration)
        .scalar_subquery()
    )


def _places_held() -> ColumnElement[int]:
    """AC2: the places one registration takes - one while REGISTERED, and story 18.5 AC2 one more
    for each of its guests; none otherwise. Summed over rows, as a total or a window."""
    return case(
        (EventRegistration.status == RegistrationStatus.REGISTERED, 1 + _guest_count()),
        else_=0,
    )


def _places() -> ColumnElement[int]:
    """AC2: the places the counted registrations take, 0 for none. Cast, as PostgreSQL sums a
    count as ``numeric``."""
    return func.coalesce(cast(func.sum(_places_held()), Integer), 0)


def _places_taken(event_id: ColumnElement[uuid.UUID] | uuid.UUID) -> Select[tuple[int]]:
    """AC2: the places taken at the event - its REGISTERED registrations and their guests."""
    return select(_places()).where(EventRegistration.event_id == event_id)


def count_places_taken(db: Session, event_id: uuid.UUID) -> int:
    """AC2: how many places ``event_id``'s registrations take, guests included (18.5 AC2). Story
    19.3 reports it beside a change request, so a coordinator sees who an approval would affect -
    each attendee and their guests (18.5 AC5)."""
    return db.scalar(_places_taken(event_id))


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


def _is_listed(now: datetime) -> ColumnElement[bool]:
    """AC1/AC3: open to attendees and not yet started."""
    return and_(_is_open_to_attendees(), Event.starts_at > now)


def _listed_events(*, attendee: User, now: datetime) -> Select[tuple[Event, int, datetime | None]]:
    """AC1: the listed events, each with how many places its registrations take, guests included
    (18.5 AC2), and when ``attendee`` registered for it, if they have."""
    registered = _places_taken(Event.id).correlate(Event).scalar_subquery()
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
    return select(Event, registered, mine).where(_is_listed(now))


def _registration_event_items(
    db: Session, rows: Sequence[Row[tuple[Event, int, datetime | None]]], *, now: datetime
) -> list[RegistrationEventItem]:
    """AC1-AC3: each listed event with its venues, places left and its state for the attendee."""
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
    return items


def list_registration_events(
    db: Session, *, attendee: User, now: datetime, limit: int, offset: int
) -> RegistrationEventListing:
    """AC1: one page of the events open to attendees that have not started, soonest first (then
    by name, then id, so pages never overlap), each with its venues, places left and its state
    for ``attendee``. AC3: full, closed and not-yet-open events stay listed until they start.
    Filtered, ordered, paged and counted in SQL."""
    rows = db.execute(
        _listed_events(attendee=attendee, now=now)
        .order_by(Event.starts_at, Event.name, Event.id)
        .limit(limit)
        .offset(offset)
    ).all()
    total = db.scalar(select(func.count()).select_from(Event).where(_is_listed(now)))
    return RegistrationEventListing(
        items=_registration_event_items(db, rows, now=now), total=total or 0
    )


def get_registration_event(
    db: Session, event_id: uuid.UUID, *, attendee: User, now: datetime
) -> RegistrationEventItem:
    """AC9 (fix f18.1.2): one listed event as its page shows it to ``attendee`` - its entry in the
    list (AC1), whose description the page shows and the card does not. AC10: an event that is
    not listed - unknown, not open to attendees (AC3/AC4) or started - is not found, one answer
    for all, so a Private event's existence is not given away."""
    row = db.execute(
        _listed_events(attendee=attendee, now=now).where(Event.id == event_id)
    ).one_or_none()
    if row is None:
        raise RegistrationEventNotFound()
    (item,) = _registration_event_items(db, [row], now=now)
    return item


def _require_phone(details: AttendeeDetailsIn, *, attendee: User) -> None:
    """Story 18.4 AC7: the phone number may be left out of what is sent only when one is already
    on file - so ``PhoneNumberRequired`` before anything is written. A licensed pre-check
    (backend/STYLE.md, Standing divergences): it answers with a 422 naming the fix, and nothing can
    race it, since no write clears an attendee's phone number. The database's
    ck_users_attendee_details_have_phone stays as the backstop."""
    if "phone" not in details.model_fields_set and attendee.phone is None:
        raise PhoneNumberRequired()


def _apply_details(
    db: Session, details: AttendeeDetailsIn, *, attendee: User, now: datetime
) -> None:
    """Story 18.4: write the details ``attendee`` sent - only the fields sent (AC4) - and record
    that they have now given them, so no later registration asks (AC2). The audit names the fields
    that changed, never their values: phone numbers and dietary needs stay out of the append-only
    log. Written, not committed, so a registration refused after it takes the details back."""
    changed = sorted(
        field
        for field in details.model_fields_set
        if getattr(attendee, field) != getattr(details, field)
    )
    for field in changed:
        setattr(attendee, field, getattr(details, field))
    if attendee.attendee_details_confirmed_at is None:
        attendee.attendee_details_confirmed_at = now
    if changed:
        record_audit(
            db,
            actor=attendee,
            action=ATTENDEE_DETAILS_UPDATED_ACTION,
            entity_type=_USER_ENTITY,
            entity_id=attendee.id,
            details={"fields": changed},
            commit=False,
        )


def _add_guests(
    db: Session, registration: EventRegistration, guests: list[GuestIn]
) -> list[RegistrationGuest]:
    """Story 18.5 AC1/AC3: write ``guests`` to ``registration``, numbered in the order given.
    Flushed, not committed, so the places can be counted with them and a refusal takes them
    back."""
    rows = [
        RegistrationGuest(
            registration_id=registration.id,
            position=position,
            full_name=guest.full_name,
            dietary_requirements=guest.dietary_requirements,
        )
        for position, guest in enumerate(guests, start=1)
    ]
    db.add_all(rows)
    db.flush()
    return rows


def _guests_by_registration(
    db: Session, registration_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[RegistrationGuest]]:
    """Story 18.5 AC4/AC5: each registration's guests, in the attendee's order, read at once for
    a whole list. A registration with none is absent: read it with ``.get(id, [])``."""
    guests = db.scalars(
        select(RegistrationGuest)
        .where(RegistrationGuest.registration_id.in_(registration_ids))
        .order_by(RegistrationGuest.registration_id, RegistrationGuest.position)
    ).all()
    by_registration: dict[uuid.UUID, list[RegistrationGuest]] = defaultdict(list)
    for guest in guests:
        by_registration[guest.registration_id].append(guest)
    return by_registration


def list_guests(db: Session, registration_id: uuid.UUID) -> list[RegistrationGuest]:
    """Story 18.5 AC1: the guests registered with one registration, in the attendee's order."""
    return _guests_by_registration(db, [registration_id]).get(registration_id, [])


def register(
    db: Session, data: RegistrationCreate, *, attendee: User, now: datetime
) -> EventRegistration:
    """AC1: register ``attendee`` for the event, stamped ``now``, and audit it. AC7: holding the
    event's row, so every check below reads the event and its places as they stand at this moment.

    Story 18.4 AC2/AC3: details sent with it are saved to the attendee's profile in the same
    transaction. With none, an attendee who has never given theirs is refused
    (``AttendeeDetailsRequired``) - last, so only one who would otherwise have a place is asked,
    and one who is already registered or facing a full event is told that instead.

    Details that would leave no phone number on file are refused first
    (``PhoneNumberRequired``, 18.4 AC7), before anything is read or written.

    Story 18.5 AC1/AC2: the guests sent with it are written with it, and counted with it: a group
    that does not fit is refused whole (``NotEnoughPlaces``, AC2) - an attendee alone, as before,
    with ``EventFull``.

    Raises ``RegistrationEventNotFound`` (AC3/AC4) unless the event is open to attendees, then
    ``RegistrationClosed`` or ``RegistrationNotYetOpen`` (AC2), ``AlreadyRegistered`` (AC6),
    ``EventFull`` or ``NotEnoughPlaces`` (AC2/AC6, 18.5 AC2) and ``AttendeeDetailsRequired``
    (18.4 AC2), in that order. A refused registration leaves nothing written - details and guests
    sent with it included."""
    if data.details is not None:
        _require_phone(data.details, attendee=attendee)
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
    guests = _add_guests(db, registration, data.guests)
    if db.scalar(_places_taken(event.id)) > event.expected_attendance:
        db.rollback()
        raise NotEnoughPlaces() if guests else EventFull()
    if attendee.attendee_details_confirmed_at is None and (
        data.details is None or not _FIRST_REGISTRATION_FIELDS <= data.details.model_fields_set
    ):
        db.rollback()
        raise AttendeeDetailsRequired()
    if data.details is not None:
        _apply_details(db, data.details, attendee=attendee, now=now)

    record_audit(
        db,
        actor=attendee,
        action=REGISTRATION_CREATED_ACTION,
        entity_type=_REGISTRATION_ENTITY,
        entity_id=registration.id,
        # Story 18.5 AC1: how many guests came with it, as update_guests records - never names.
        details={"event_id": str(event.id), "guest_count": len(guests)},
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
    whether it can be withdrawn now (AC3). Story 18.5 AC3: its guests, whether they can still be
    changed, and how many guests it may have, for the places left."""

    registration: EventRegistration
    event: Event
    standing: RegistrationStanding
    can_withdraw: bool
    guests: list[RegistrationGuest]
    can_change_guests: bool
    max_guests: int


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


def guest_limit(*, capacity: int, places_taken: int, guests: int) -> int:
    """Story 18.5 AC2/AC3/AC6: how many guests a registration holding ``guests``
    may have - those, and one more for each place left - but never more than ten. On an event
    already over its capacity (19.2) no place is left, so the limit is the guests it has."""
    return min(MAX_GUESTS, guests + places_left(capacity=capacity, registered=places_taken))


def _my_registration_item(
    registration: EventRegistration,
    event: Event,
    *,
    now: datetime,
    guests: list[RegistrationGuest],
    places_taken: int,
) -> MyRegistrationItem:
    # Registrations are only taken for Confirmed events, and ck_events_submitted_fields_complete
    # keeps a start and an expected attendance on every event past Draft.
    assert event.starts_at is not None
    assert event.expected_attendance is not None
    standing = registration_standing(
        registration_status=registration.status, event_status=event.status
    )
    return MyRegistrationItem(
        registration=registration,
        event=event,
        standing=standing,
        can_withdraw=can_withdraw(standing=standing, now=now, starts_at=event.starts_at),
        guests=guests,
        can_change_guests=guests_change_refusal(standing=standing, event=event, now=now) is None,
        max_guests=guest_limit(
            capacity=event.expected_attendance, places_taken=places_taken, guests=len(guests)
        ),
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
        select(
            EventRegistration,
            Event,
            _places_taken(Event.id).correlate(Event).scalar_subquery(),
        )
        .join(Event, Event.id == EventRegistration.event_id)
        .where(EventRegistration.id.in_(_latest_per_event(attendee)))
        .order_by(
            upcoming_start.asc().nulls_last(),
            Event.starts_at.desc(),
            Event.name,
            Event.id,
        )
    ).all()
    guests = _guests_by_registration(db, [registration.id for registration, _, _ in rows])
    return [
        _my_registration_item(
            registration,
            event,
            now=now,
            guests=guests.get(registration.id, []),
            places_taken=places_taken,
        )
        for registration, event, places_taken in rows
    ]


@dataclass(frozen=True)
class AttendeeEvent:
    """18.1 AC9 / 18.2 AC9 (fixes f18.1.2, f18.2.1): one event's page for an attendee - the event
    and the venues it has booked; what its card on Upcoming events shows, while it is listed, None
    once it is not (AC10); and the attendee's own latest registration for it (AC1/AC4), None if
    they never registered."""

    event: Event
    venues: list[Venue]
    listing: RegistrationEventItem | None
    registration: MyRegistrationItem | None


def _my_registration_for(
    db: Session, event_id: uuid.UUID, *, attendee: User, now: datetime
) -> MyRegistrationItem | None:
    """AC9: ``attendee``'s latest registration for the event - the one My registrations lists
    (AC1/AC4) - with where they stand, or None if they never registered for it. Story 18.5 AC3:
    with its guests and how many it may have, as My registrations has them."""
    row = db.execute(
        select(
            EventRegistration,
            Event,
            _places_taken(Event.id).correlate(Event).scalar_subquery(),
        )
        .join(Event, Event.id == EventRegistration.event_id)
        .where(
            EventRegistration.id.in_(_latest_per_event(attendee)),
            EventRegistration.event_id == event_id,
        )
    ).one_or_none()
    if row is None:
        return None
    registration, event, places_taken = row
    return _my_registration_item(
        registration,
        event,
        now=now,
        guests=list_guests(db, registration.id),
        places_taken=places_taken,
    )


def get_attendee_event(
    db: Session, event_id: uuid.UUID, *, attendee: User, now: datetime
) -> AttendeeEvent:
    """AC9 (fix f18.2.1): one event's page for ``attendee`` - 18.1's page of a listed event, with
    their own registration beside it. AC10: an event they registered for opens even once it is no
    longer listed - started, cancelled, sent back to Planning or made Private - with no listing and
    only the venues it still has booked. 18.1 AC10 / AC6: an event that is neither listed nor
    registered for by them is not found, as an unknown one is."""
    registration = _my_registration_for(db, event_id, attendee=attendee, now=now)
    try:
        listing = get_registration_event(db, event_id, attendee=attendee, now=now)
    except RegistrationEventNotFound:
        if registration is None:
            raise
        event = registration.event
        return AttendeeEvent(
            event=event,
            venues=_booked_venues(db, [event.id])[event.id],
            listing=None,
            registration=registration,
        )
    return AttendeeEvent(
        event=listing.event, venues=listing.venues, listing=listing, registration=registration
    )


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
    when it is not ``attendee``'s (AC6), else ``withdrawal_refusal`` (AC3/AC7/AC8).

    Story 18.5 AC7: the guests go with it. Their places are counted only while the registration
    is Registered, so they are freed with it, and they stay on it for the record."""
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
    guests = list_guests(db, registration.id)
    item = _my_registration_item(
        registration,
        event,
        now=now,
        guests=guests,
        places_taken=count_places_taken(db, event.id),
    )
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


def _attendee_registration(
    registration: EventRegistration,
    *,
    attendee: User,
    event_status: str,
    guests: list[RegistrationGuest],
) -> AttendeeRegistration:
    """18.3 AC4: one row, with 18.2's standing. 18.4 AC9: only a registration still Registered
    shows the attendee's details - not one withdrawn, nor any on a cancelled event (CL-163) -
    since only those attendees are being catered for and may need contacting. Story 18.5 AC4: the
    guests registered with them, whose dietary requirements follow the same rule (AC9)."""
    standing = registration_standing(
        registration_status=registration.status, event_status=event_status
    )
    return AttendeeRegistration(
        registration=registration,
        attendee=attendee,
        standing=standing,
        shows_details=standing is RegistrationStanding.REGISTERED,
        guests=guests,
    )


def list_event_registrations(
    db: Session, event_id: uuid.UUID, *, viewer: User, limit: int, offset: int
) -> EventRegistrationList:
    """18.3 AC1/AC2/AC4: one page of the event's registrations, oldest first, each with its
    attendee and 18.2's standing. AC5/AC6: ``RegistrationListNotFound`` unless the event is
    viewable by ``viewer``.

    AC7: the total and active count are window counts over every row of the event, in the
    statement that reads the page, so a registration made meanwhile can never leave the count
    and the list apart. A page past the end has no row to carry them, so they are counted
    alone. A cancelled event's registrations, still active or not, count for none (18.2). Story
    18.5 AC4: the active count is of places, so each active registration's guests count too."""
    event = db.scalar(
        select(Event).where(Event.id == event_id, _registration_list_viewable_by(viewer))
    )
    if event is None:
        raise RegistrationListNotFound()
    # ck_events_submitted_fields_complete: an event past draft has its expected attendance.
    assert event.expected_attendance is not None
    is_this_event = EventRegistration.event_id == event.id
    rows = db.execute(
        select(
            EventRegistration,
            User,
            func.count().over(),
            cast(func.sum(_places_held()).over(), Integer),
        )
        .join(User, User.id == EventRegistration.attendee_id)
        .where(is_this_event)
        .order_by(EventRegistration.registered_at, EventRegistration.id)
        .limit(limit)
        .offset(offset)
    ).all()
    if rows:
        total, active = rows[0][2], rows[0][3]
    else:
        total, active = db.execute(select(func.count(), _places()).where(is_this_event)).one()
    if event.status == EventStatus.CANCELLED:
        active = 0
    guests = _guests_by_registration(db, [registration.id for registration, _, _, _ in rows])
    return EventRegistrationList(
        items=[
            _attendee_registration(
                registration,
                attendee=attendee,
                event_status=event.status,
                guests=guests.get(registration.id, []),
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


# =============================================================================================
# Story 18.4: the attendee's details, on My profile
# =============================================================================================
def update_profile(
    db: Session, details: AttendeeDetailsIn, *, attendee: User, now: datetime
) -> User:
    """18.4 AC4: save the details ``attendee`` sent on My profile, which every page then reads
    from their one row - registrations made earlier included. AC10: only ever the signed-in
    attendee's own. AC11: a plain write, so of two saves the later wins. AC7: refused with
    ``PhoneNumberRequired`` when it would leave no phone number on file."""
    _require_phone(details, attendee=attendee)
    _apply_details(db, details, attendee=attendee, now=now)
    db.commit()
    return attendee


# =============================================================================================
# Story 18.5: changing the guests registered with an attendee
# =============================================================================================
REGISTRATION_GUESTS_UPDATED_ACTION = "EVENT_REGISTRATION_GUESTS_UPDATED"

GUESTS_REGISTRATION_CLOSED_MESSAGE = (
    "Registration for this event has closed, so your guests can no longer be changed."
)
GUESTS_WITHDRAWN_MESSAGE = (
    "You have withdrawn from this event, so your guests can no longer be changed."
)
GUESTS_EVENT_CANCELLED_MESSAGE = (
    "This event was cancelled, so your guests can no longer be changed."
)
GUESTS_NOT_ENOUGH_PLACES_MESSAGE = "There are not enough places left for these guests."


class GuestsChangeRefused(Exception):
    """AC3: the registration is the attendee's, but its guests cannot be changed so."""


class GuestsRegistrationClosed(GuestsChangeRefused):
    def __init__(self) -> None:
        super().__init__(GUESTS_REGISTRATION_CLOSED_MESSAGE)


class GuestsAfterWithdrawal(GuestsChangeRefused):
    def __init__(self) -> None:
        super().__init__(GUESTS_WITHDRAWN_MESSAGE)


class GuestsEventCancelled(GuestsChangeRefused):
    def __init__(self) -> None:
        super().__init__(GUESTS_EVENT_CANCELLED_MESSAGE)


class GuestsNotEnoughPlaces(GuestsChangeRefused):
    def __init__(self) -> None:
        super().__init__(GUESTS_NOT_ENOUGH_PLACES_MESSAGE)


def guests_change_refusal(
    *, standing: RegistrationStanding, event: Event, now: datetime
) -> GuestsChangeRefused | None:
    """AC3 (CL-185): why the guests of a registration standing so can no longer be changed, or
    None while they can - withdrawn; its event cancelled; or its registration no longer open:
    closed by time (18.1 AC2), or the event no longer taking registrations (sent back to Planning,
    9.4). The one rule behind both My registrations' ``can_change_guests`` and ``update_guests``."""
    if standing is RegistrationStanding.WITHDRAWN:
        return GuestsAfterWithdrawal()
    if standing is RegistrationStanding.EVENT_CANCELLED:
        return GuestsEventCancelled()
    # ck_events_submitted_fields_complete keeps a start on every event past Draft.
    assert event.starts_at is not None
    closes_at = closing_time(closes_at=event.registration_closes_at, starts_at=event.starts_at)
    is_taking_registrations = (
        event.status == EventStatus.CONFIRMED
        and event.is_public
        and event.registration_required
        and now < closes_at
    )
    if not is_taking_registrations:
        return GuestsRegistrationClosed()
    return None


def update_guests(
    db: Session, registration_id: uuid.UUID, data: GuestsUpdate, *, attendee: User, now: datetime
) -> MyRegistrationItem:
    """AC3: replace the guests of ``attendee``'s registration with ``data``'s, in order, and audit
    how many there now are - never their names. AC10: another attendee's registration, like an
    unknown one, is ``RegistrationNotFound``.

    AC11: the event's row is held first, as ``register`` holds it, then the registration's, so
    every change to an event's places takes turns and a withdrawal (18.2) waits for this one. The
    standing is read under those locks, so nothing changes between ``guests_change_refusal``
    and the write. The new guests are written first and the places counted after, as in
    ``register``: more guests than the places left is rolled back (``GuestsNotEnoughPlaces``).
    Fewer guests are never refused, even on an event already over its capacity (19.2)."""
    found = db.execute(
        select(EventRegistration.event_id).where(
            EventRegistration.id == registration_id,
            EventRegistration.attendee_id == attendee.id,
        )
    ).one_or_none()
    if found is None:
        raise RegistrationNotFound()
    event = db.scalar(
        select(Event).where(Event.id == found.event_id).with_for_update(key_share=True, of=Event)
    )
    registration = db.scalar(
        select(EventRegistration)
        .where(EventRegistration.id == registration_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    # The registration's event is its foreign key, and nothing deletes a registration.
    assert event is not None
    assert registration is not None
    standing = registration_standing(
        registration_status=registration.status, event_status=event.status
    )
    refusal = guests_change_refusal(standing=standing, event=event, now=now)
    if refusal is not None:
        raise refusal

    before = db.scalar(
        select(func.count()).where(RegistrationGuest.registration_id == registration.id)
    )
    db.execute(
        delete(RegistrationGuest).where(RegistrationGuest.registration_id == registration.id)
    )
    guests = _add_guests(db, registration, data.guests)
    # ck_events_submitted_fields_complete: a Confirmed event has its expected attendance.
    assert event.expected_attendance is not None
    if len(guests) > before and db.scalar(_places_taken(event.id)) > event.expected_attendance:
        db.rollback()
        raise GuestsNotEnoughPlaces()

    record_audit(
        db,
        actor=attendee,
        action=REGISTRATION_GUESTS_UPDATED_ACTION,
        entity_type=_REGISTRATION_ENTITY,
        entity_id=registration.id,
        details={"event_id": str(event.id), "guest_count": len(guests)},
        commit=False,
    )
    db.commit()
    return _my_registration_item(
        registration,
        event,
        now=now,
        guests=guests,
        places_taken=count_places_taken(db, event.id),
    )
