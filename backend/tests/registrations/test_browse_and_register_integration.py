"""Story 18.1 - browse and register for an event. INTEGRATION tests: the service and the API on
PostgreSQL.

Level: integration. Each test drives ``app/registrations`` through the HTTP API (``*_client``
fixtures) or its service functions, against the real schema in the rolled-back test transaction.
The race tests at the end commit real concurrent transactions and clean up after themselves. The
pure rules (places left, the registration window, which state wins) are unit-tested in
``test_browse_and_register_unit.py``; the attendee's clicks are e2e-tested in
``tests/e2e/attendee-registration.spec.ts``. The AC2 boundaries are tested at both levels on
purpose: the unit tests pin each rule, and these catch the service wiring them up wrongly (a rule
handed the wrong time, a count of the wrong rows).

Service-level tests pass ``now=NOW``, a moment after every seeded event has started, so a listing
at NOW holds only the events the test made, and a boundary can be hit to the microsecond. API
tests run on the real clock, so they make events relative to today and find them by id.

AC1 Confirmed, Public events with registration enabled that have not started are listed soonest
    first, a page at a time, with name, description, date, time, each booked venue's name and
    location, the places left and the registration state (Open, Not yet open, Full, Closed,
    Registered). Registering creates a registration stamped with the moment it was made and shows
    a confirmation with that time; the event then shows as Registered.
AC2 Capacity is the event's expected attendance (2.1 AC17). The registration that takes the last
    place is accepted; the next is refused. A registration before the closing time is accepted;
    one at or after it is refused. When an opening time is set, a registration before it is
    refused and one at it is accepted. An event with no closing time recorded closes when it
    starts.
AC3 Full, closed and not-yet-open events stay listed until they start, with Register disabled.
    Cancelled events are not listed and refuse registration; notifying their registrants is part
    of cancelling (6.2 AC1).
AC4 Events that are not Confirmed, including one sent back to Planning after confirmation, and
    Private events are not listed and refuse registration. Registrations already made are kept.
AC5 Only signed-in Attendees can list events or register: other roles get 403 and signed-out
    users 401, through the API too. No internal planning information is sent: no organiser,
    coordinator, contact, purpose, expected attendance, equipment, accessibility needs or
    internal notes. (No field carries the expected attendance, but it shows through the places
    left until someone registers: capacity is the expected attendance, 2.1 AC17, and the places
    left are shown, decision 1.)
AC6 A second registration by the same attendee is refused, also when both arrive at once. Of two
    attendees competing for the last place, one succeeds and the other is told the event is full.
AC7 The server checks the event's status, the opening and closing times and capacity at the
    moment it records the registration, holding the event's row, and the database keeps one
    active registration per attendee per event, so simultaneous requests cannot exceed capacity or
    create duplicates.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings.models import BookingStatus
from app.common.audit import AuditLog
from app.events.models import Event, EventStatus
from app.registrations import service
from app.registrations.models import EventRegistration, RegistrationStatus
from app.registrations.schemas import RegistrationCreate
from app.registrations.service import RegistrationState
from tests.support.factories import future_datetime, make_booking, make_event, make_user, make_venue
from tests.support.seed import Users, Venues

EVENTS_PATH = "/registrations/events"
REGISTER_PATH = "/registrations"

# After every seeded event has started (the latest is in 2028), so a listing at NOW holds only the
# events a test made. Fixed, so a boundary can be hit exactly.
NOW = datetime(2030, 1, 15, 9, 0, tzinfo=UTC)
TICK = timedelta(microseconds=1)  # the smallest step a timestamptz stores

# AC5: everything a listed event may carry, and everything a registration answer may carry.
LISTED_EVENT_KEYS = {
    "id",
    "name",
    "description",
    "cover_image_url",
    "starts_at",
    "ends_at",
    "venues",
    "registration_opens_at",
    "registration_closes_at",
    "places_left",
    "state",
    "registered_at",
}
REGISTRATION_KEYS = {"id", "event_id", "status", "registered_at"}

REGISTERED = "registered"
NOT_FOUND = "not found"


def _fixed_id(n: int) -> uuid.UUID:
    """An id chosen by the test, so rows can be given ids in the opposite order to the one the
    test expects: an order that only ever followed the ids would then be caught, not lucky."""
    return uuid.UUID(f"18100000-0000-0000-0000-{n:012d}")


def _open_event(
    db: Session, *, starts_at: datetime = NOW + timedelta(days=30), **overrides
) -> Event:
    """A Confirmed, Public event taking registrations: open now, closing a day before it starts."""
    return make_event(
        db,
        status=overrides.pop("status", EventStatus.CONFIRMED),
        organiser_id=overrides.pop("organiser_id", Users.ORGANISER_2.id),
        assigned_coordinator_id=Users.COORDINATOR.id,
        registration_required=overrides.pop("registration_required", True),
        is_public=overrides.pop("is_public", True),
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=3),
        registration_closes_at=overrides.pop(
            "registration_closes_at", starts_at - timedelta(days=1)
        ),
        expected_attendance=overrides.pop("expected_attendance", 50),
        **overrides,
    )


def _attendee(db: Session) -> User:
    return make_user(db, role="ATTENDEE")


def _register(
    db: Session, event: Event, attendee: User, *, now: datetime = NOW
) -> EventRegistration:
    """As a request would: the test's rows are already saved when it arrives. A refused
    registration rolls its session back; committing first keeps that to the registration's own
    work. (The commit only releases a savepoint; the test's transaction still rolls back.)"""
    db.commit()
    return service.register(db, RegistrationCreate(event_id=event.id), attendee=attendee, now=now)


def _listing(
    db: Session, attendee: User, *, now: datetime = NOW, limit: int = 100, offset: int = 0
) -> service.RegistrationEventListing:
    return service.list_registration_events(
        db, attendee=attendee, now=now, limit=limit, offset=offset
    )


def _listed_ids(db: Session, attendee: User, *, now: datetime = NOW) -> list[uuid.UUID]:
    return [item.event.id for item in _listing(db, attendee, now=now).items]


def _item(
    db: Session, attendee: User, event: Event, *, now: datetime = NOW
) -> service.RegistrationEventItem:
    (item,) = [i for i in _listing(db, attendee, now=now).items if i.event.id == event.id]
    return item


def _active_count(db: Session, event_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count())
        .select_from(EventRegistration)
        .where(
            EventRegistration.event_id == event_id,
            EventRegistration.status == RegistrationStatus.REGISTERED,
        )
    )


def _add_registration(
    db: Session, event: Event, *, status: str = RegistrationStatus.REGISTERED
) -> EventRegistration:
    """A registration written straight to the table, by a new attendee, as 18.2 later would."""
    row = EventRegistration(
        event_id=event.id, attendee_id=_attendee(db).id, status=status, registered_at=NOW
    )
    db.add(row)
    db.flush()
    return row


def _api_item(client, event_id: uuid.UUID) -> dict:
    response = client.get(EVENTS_PATH, params={"limit": 100})
    assert response.status_code == 200
    (item,) = [i for i in response.json()["items"] if i["id"] == str(event_id)]
    return item


# =============================================================================================
# AC1 - happy path: the list and a registration
# =============================================================================================
@pytest.mark.story("18.1", ac=1)
def test_an_open_event_is_listed_with_its_details_for_an_attendee(attendee_client, db: Session):
    starts_at = future_datetime(days=40)
    event = _open_event(
        db,
        starts_at=starts_at,
        name="Harbour Jazz 18.1",
        description="Jazz on the waterfront.",
        cover_image_url="/uploads/events/harbour-jazz-18-1.png",
    )
    hall = make_venue(db, name="Jazz Hall 18.1", location="Pier 1, Level 2")
    lawn = make_venue(db, name="Jazz Lawn 18.1", location="Pier 2")
    make_booking(
        db,
        event_id=event.id,
        venue_id=lawn.id,
        status=BookingStatus.APPROVED,
        starts_at=starts_at + timedelta(hours=1),
        ends_at=starts_at + timedelta(hours=3),
    )
    make_booking(
        db,
        event_id=event.id,
        venue_id=hall.id,
        status=BookingStatus.APPROVED,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=3),
    )

    item = _api_item(attendee_client, event.id)

    assert item["name"] == "Harbour Jazz 18.1"
    assert item["description"] == "Jazz on the waterfront."
    assert item["cover_image_url"] == "/uploads/events/harbour-jazz-18-1.png"  # f18.1.1, 2.1 AC14
    assert datetime.fromisoformat(item["starts_at"]) == starts_at
    assert datetime.fromisoformat(item["ends_at"]) == starts_at + timedelta(hours=3)
    assert item["venues"] == [
        {"name": "Jazz Hall 18.1", "location": "Pier 1, Level 2"},
        {"name": "Jazz Lawn 18.1", "location": "Pier 2"},
    ]
    assert item["registration_opens_at"] is None
    assert datetime.fromisoformat(item["registration_closes_at"]) == starts_at - timedelta(days=1)
    assert item["places_left"] == 50
    assert item["state"] == "OPEN"
    assert item["registered_at"] is None


@pytest.mark.story("18.1", ac=1)
def test_only_approved_bookings_name_the_venues_each_once_in_start_order(db: Session):
    """The bookings' ids run against their start times, so ordering by id would be caught."""
    event = _open_event(db)
    first, second, pending, rejected, withdrawn = (make_venue(db) for _ in range(5))
    day = NOW + timedelta(days=30)
    for n, venue, status, hour in (
        (1, second, BookingStatus.APPROVED, 12),
        (2, first, BookingStatus.APPROVED, 15),  # the same venue booked again later that day
        (3, first, BookingStatus.APPROVED, 9),
        (4, pending, BookingStatus.PENDING, 8),
        (5, rejected, BookingStatus.REJECTED, 8),
        (6, withdrawn, BookingStatus.WITHDRAWN, 8),
    ):
        make_booking(
            db,
            id=_fixed_id(n),
            event_id=event.id,
            venue_id=venue.id,
            status=status,
            starts_at=day.replace(hour=hour),
            ends_at=day.replace(hour=hour + 2),
        )

    venues = _item(db, _attendee(db), event).venues

    assert [venue.id for venue in venues] == [first.id, second.id]


@pytest.mark.story("18.1", ac=1)
def test_venues_booked_from_the_same_moment_are_listed_by_booking_id(db: Session):
    """Written in the opposite order to their ids, so only the id puts them in a stable order."""
    event = _open_event(db)
    lower, higher = make_venue(db), make_venue(db)
    start = NOW + timedelta(days=30)
    for n, venue in ((8, higher), (7, lower)):
        make_booking(
            db,
            id=_fixed_id(n),
            event_id=event.id,
            venue_id=venue.id,
            status=BookingStatus.APPROVED,
            starts_at=start,
            ends_at=start + timedelta(hours=2),
        )

    venues = _item(db, _attendee(db), event).venues

    assert [venue.id for venue in venues] == [lower.id, higher.id]


@pytest.mark.story("18.1", ac=1)
def test_an_event_with_no_approved_booking_lists_no_venue(db: Session):
    event = _open_event(db)

    assert _item(db, _attendee(db), event).venues == []


@pytest.mark.story("18.1", ac=1)
def test_events_are_listed_soonest_first_then_by_name_then_by_id(db: Session):
    """Ids run against the expected order: Bravo has the lowest, and the two Alphas are written
    highest id first, so an order that skipped the name or the id would be caught."""
    later = NOW + timedelta(days=9)
    bravo = _open_event(db, id=_fixed_id(1), starts_at=later, name="Bravo 18.1")
    soonest = _open_event(db, id=_fixed_id(9), starts_at=NOW + timedelta(days=3), name="Zulu 18.1")
    alpha_high = _open_event(db, id=_fixed_id(3), starts_at=later, name="Alpha 18.1")
    # Another organiser's: no organiser holds two live events of one name and dates (2.1 AC20).
    alpha_low = _open_event(
        db, id=_fixed_id(2), starts_at=later, name="Alpha 18.1", organiser_id=Users.ORGANISER.id
    )

    assert _listed_ids(db, _attendee(db)) == [soonest.id, alpha_low.id, alpha_high.id, bravo.id]


@pytest.mark.story("18.1", ac=1)
def test_the_list_comes_a_page_at_a_time_with_the_total(db: Session):
    events = [_open_event(db, starts_at=NOW + timedelta(days=d)) for d in (3, 4, 5)]
    attendee = _attendee(db)

    first_page = _listing(db, attendee, limit=2, offset=0)
    last_page = _listing(db, attendee, limit=2, offset=2)

    assert [item.event.id for item in first_page.items] == [events[0].id, events[1].id]
    assert [item.event.id for item in last_page.items] == [events[2].id]
    assert first_page.total == last_page.total == 3


@pytest.mark.story("18.1", ac=1)
def test_with_no_event_open_the_list_is_empty_with_a_total_of_0(db: Session):
    assert _listing(db, _attendee(db)) == service.RegistrationEventListing(items=[], total=0)


@pytest.mark.story("18.1", ac=1)
@pytest.mark.parametrize(
    ("params", "status_code"),
    [
        ({"limit": 1}, 200),
        ({"limit": 100}, 200),
        ({"limit": 0}, 422),
        ({"limit": 101}, 422),
        ({"offset": 0}, 200),
        ({"offset": -1}, 422),
    ],
)
def test_a_page_size_or_offset_outside_its_limits_is_refused(attendee_client, params, status_code):
    assert attendee_client.get(EVENTS_PATH, params=params).status_code == status_code


@pytest.mark.story("18.1", ac=1)
@pytest.mark.story("18.1", ac=5)
def test_registering_answers_201_with_the_registration_and_records_it(attendee_client, db: Session):
    event = _open_event(db, starts_at=future_datetime(days=40))
    before = datetime.now(UTC)

    response = attendee_client.post(REGISTER_PATH, json={"event_id": str(event.id)})

    after = datetime.now(UTC)
    assert response.status_code == 201
    body = response.json()
    assert set(body) == REGISTRATION_KEYS
    assert body["event_id"] == str(event.id)
    assert body["status"] == "REGISTERED"
    registration = db.get(EventRegistration, uuid.UUID(body["id"]))
    assert registration.attendee_id == Users.ATTENDEE.id
    assert registration.status == RegistrationStatus.REGISTERED
    assert before <= registration.registered_at <= after
    assert datetime.fromisoformat(body["registered_at"]) == registration.registered_at
    audit = db.scalar(select(AuditLog).where(AuditLog.entity_id == registration.id))
    assert audit.action == service.REGISTRATION_CREATED_ACTION
    assert audit.actor_id == Users.ATTENDEE.id
    assert audit.details == {"event_id": str(event.id)}
    # The list now shows the event as Registered, with the moment the confirmation gave.
    listed = _api_item(attendee_client, event.id)
    assert (listed["state"], listed["registered_at"]) == ("REGISTERED", body["registered_at"])


@pytest.mark.story("18.1", ac=1)
def test_a_registration_is_stamped_with_the_moment_it_was_made(db: Session):
    event = _open_event(db)

    registration = _register(db, event, _attendee(db), now=NOW)

    db.expire(registration)
    assert registration.registered_at == NOW


@pytest.mark.story("18.1", ac=1)
def test_after_registering_the_event_shows_as_registered_for_that_attendee_only(db: Session):
    event = _open_event(db, expected_attendance=50)
    registered, other = _attendee(db), _attendee(db)
    _register(db, event, registered)

    mine = _item(db, registered, event)
    theirs = _item(db, other, event)

    assert (mine.state, mine.registered_at, mine.places_left) == (
        RegistrationState.REGISTERED,
        NOW,
        49,
    )
    assert (theirs.state, theirs.registered_at, theirs.places_left) == (
        RegistrationState.OPEN,
        None,
        49,
    )


@pytest.mark.story("18.1", ac=1)
def test_registering_for_one_event_leaves_the_others_open_for_that_attendee(db: Session):
    chosen = _open_event(db, starts_at=NOW + timedelta(days=3))
    other = _open_event(db, starts_at=NOW + timedelta(days=4))
    attendee = _attendee(db)
    _register(db, chosen, attendee)

    listing = _listing(db, attendee)

    states = {item.event.id: (item.state, item.registered_at) for item in listing.items}
    assert states == {
        chosen.id: (RegistrationState.REGISTERED, NOW),
        other.id: (RegistrationState.OPEN, None),
    }


@pytest.mark.story("18.1", ac=1)
def test_a_withdrawn_registration_does_not_show_the_event_as_registered(db: Session):
    """Only an active registration is the attendee's place; one withdrawn (18.2) is not."""
    event = _open_event(db)
    attendee = _attendee(db)
    db.add(
        EventRegistration(
            event_id=event.id,
            attendee_id=attendee.id,
            status=RegistrationStatus.WITHDRAWN,
            registered_at=NOW - timedelta(days=1),
        )
    )
    db.flush()

    item = _item(db, attendee, event)

    assert (item.state, item.registered_at) == (RegistrationState.OPEN, None)


# =============================================================================================
# AC2 - boundary: the last place, the closing time, the opening time
# =============================================================================================
@pytest.mark.story("18.1", ac=2)
def test_the_last_place_is_accepted_and_the_next_registration_refused(db: Session):
    event = _open_event(db, expected_attendance=2)
    _add_registration(db, event)
    last, too_late = _attendee(db), _attendee(db)

    _register(db, event, last)
    with pytest.raises(service.EventFull) as refusal:
        _register(db, event, too_late)

    assert str(refusal.value) == service.EVENT_FULL_MESSAGE
    assert _active_count(db, event.id) == 2
    assert (
        db.scalar(select(EventRegistration).where(EventRegistration.attendee_id == too_late.id))
        is None
    )


@pytest.mark.story("18.1", ac=2)
def test_withdrawn_and_cancelled_registrations_take_no_place(db: Session):
    event = _open_event(db, expected_attendance=1)
    _add_registration(db, event, status=RegistrationStatus.WITHDRAWN)
    _add_registration(db, event, status=RegistrationStatus.CANCELLED)
    attendee = _attendee(db)

    assert _item(db, attendee, event).places_left == 1
    _register(db, event, attendee)
    assert _active_count(db, event.id) == 1


@pytest.mark.story("18.1", ac=2)
def test_an_event_registered_beyond_its_capacity_is_full_and_refuses_more(db: Session):
    """A change request (19.2) can lower the attendance below the registrations already made."""
    event = _open_event(db, expected_attendance=1)
    _add_registration(db, event)
    _add_registration(db, event)
    attendee = _attendee(db)

    item = _item(db, attendee, event)
    assert (item.state, item.places_left) == (RegistrationState.FULL, 0)
    with pytest.raises(service.EventFull):
        _register(db, event, attendee)
    assert _active_count(db, event.id) == 2


@pytest.mark.story("18.1", ac=2)
def test_a_registration_one_tick_before_the_closing_time_is_accepted(db: Session):
    event = _open_event(db, registration_closes_at=NOW + TICK)

    _register(db, event, _attendee(db), now=NOW)

    assert _active_count(db, event.id) == 1


@pytest.mark.story("18.1", ac=2)
def test_a_registration_at_the_closing_time_is_refused(db: Session):
    event = _open_event(db, registration_closes_at=NOW)

    with pytest.raises(service.RegistrationClosed) as refusal:
        _register(db, event, _attendee(db), now=NOW)

    assert str(refusal.value) == service.REGISTRATION_CLOSED_MESSAGE
    assert _active_count(db, event.id) == 0


@pytest.mark.story("18.1", ac=2)
def test_a_registration_at_the_opening_time_is_accepted(db: Session):
    event = _open_event(db, registration_opens_at=NOW)

    _register(db, event, _attendee(db), now=NOW)

    assert _active_count(db, event.id) == 1


@pytest.mark.story("18.1", ac=2)
def test_a_registration_one_tick_before_the_opening_time_is_refused(db: Session):
    event = _open_event(db, registration_opens_at=NOW + TICK)

    with pytest.raises(service.RegistrationNotYetOpen) as refusal:
        _register(db, event, _attendee(db), now=NOW)

    assert str(refusal.value) == service.REGISTRATION_NOT_YET_OPEN_MESSAGE
    assert _active_count(db, event.id) == 0


@pytest.mark.story("18.1", ac=2)
def test_with_no_closing_time_registration_stays_open_until_the_event_starts(db: Session):
    starting_soon = _open_event(db, starts_at=NOW + TICK, registration_closes_at=None)
    starting_now = _open_event(db, starts_at=NOW, registration_closes_at=None)

    _register(db, starting_soon, _attendee(db), now=NOW)
    with pytest.raises(service.RegistrationClosed):
        _register(db, starting_now, _attendee(db), now=NOW)

    assert (_active_count(db, starting_soon.id), _active_count(db, starting_now.id)) == (1, 0)


# =============================================================================================
# AC3 - edge: what stays listed, and what is removed
# =============================================================================================
@pytest.mark.story("18.1", ac=3)
def test_full_closed_and_not_yet_open_events_stay_listed_in_their_state(db: Session):
    full = _open_event(db, expected_attendance=1)
    _add_registration(db, full)
    closed = _open_event(db, registration_closes_at=NOW)
    not_yet_open = _open_event(db, registration_opens_at=NOW + timedelta(days=1))
    attendee = _attendee(db)

    states = {item.event.id: item.state for item in _listing(db, attendee).items}

    assert states == {
        full.id: RegistrationState.FULL,
        closed.id: RegistrationState.CLOSED,
        not_yet_open.id: RegistrationState.NOT_YET_OPEN,
    }


@pytest.mark.story("18.1", ac=3)
def test_an_event_drops_off_the_list_when_it_starts(db: Session):
    starting_soon = _open_event(db, starts_at=NOW + TICK, registration_closes_at=None)
    _open_event(db, starts_at=NOW, registration_closes_at=None)

    assert _listed_ids(db, _attendee(db)) == [starting_soon.id]


@pytest.mark.story("18.1", ac=3)
def test_a_cancelled_event_is_not_listed_and_refuses_registration(db: Session):
    event = _open_event(db, status=EventStatus.CANCELLED)
    attendee = _attendee(db)

    assert _listed_ids(db, attendee) == []
    with pytest.raises(service.RegistrationEventNotFound) as refusal:
        _register(db, event, attendee)
    assert str(refusal.value) == service.REGISTRATION_EVENT_NOT_FOUND_MESSAGE


@pytest.mark.story("18.1", ac=1)
@pytest.mark.story("18.1", ac=3)
def test_an_event_not_yet_open_is_sent_with_when_it_opens(attendee_client, db: Session):
    opens_at = future_datetime(days=5)
    event = _open_event(db, starts_at=future_datetime(days=40), registration_opens_at=opens_at)

    item = _api_item(attendee_client, event.id)

    assert item["state"] == "NOT_YET_OPEN"
    assert datetime.fromisoformat(item["registration_opens_at"]) == opens_at


# =============================================================================================
# AC4 - edge: not Confirmed, not taking registrations, or Private
# =============================================================================================
@pytest.mark.story("18.1", ac=4)
@pytest.mark.parametrize(
    "status",
    [
        EventStatus.DRAFT,
        EventStatus.UNDER_REVIEW,
        EventStatus.CLARIFICATION_REQUESTED,
        EventStatus.PLANNING,
        EventStatus.AWAITING_SAFETY_CHECK,
        EventStatus.COMPLETED,
        EventStatus.REJECTED,
    ],
)
def test_an_event_that_is_not_confirmed_is_not_listed_and_refuses_registration(
    db: Session, status: str
):
    event = _open_event(db, status=status)
    attendee = _attendee(db)

    assert _listed_ids(db, attendee) == []
    with pytest.raises(service.RegistrationEventNotFound):
        _register(db, event, attendee)
    assert _active_count(db, event.id) == 0


@pytest.mark.story("18.1", ac=4)
def test_an_event_not_taking_registrations_is_not_listed_and_refuses_registration(db: Session):
    event = _open_event(db, registration_required=False, registration_closes_at=None)
    attendee = _attendee(db)

    assert _listed_ids(db, attendee) == []
    with pytest.raises(service.RegistrationEventNotFound):
        _register(db, event, attendee)


@pytest.mark.story("18.1", ac=4)
def test_a_private_event_is_not_listed_and_refuses_registration(db: Session):
    event = _open_event(db, is_public=False)
    attendee = _attendee(db)

    assert _listed_ids(db, attendee) == []
    with pytest.raises(service.RegistrationEventNotFound):
        _register(db, event, attendee)


@pytest.mark.story("18.1", ac=4)
def test_an_event_sent_back_to_planning_keeps_its_registrations_but_takes_no_more(db: Session):
    event = _open_event(db)
    registered = _attendee(db)
    registration = _register(db, event, registered)
    db.execute(update(Event).where(Event.id == event.id).values(status=EventStatus.PLANNING))

    newcomer = _attendee(db)
    assert _listed_ids(db, newcomer) == []
    with pytest.raises(service.RegistrationEventNotFound):
        _register(db, event, newcomer)
    db.refresh(registration)
    assert registration.status == RegistrationStatus.REGISTERED
    assert _active_count(db, event.id) == 1


# =============================================================================================
# AC5 - permission: signed-in attendees only, and nothing internal
# =============================================================================================
@pytest.mark.story("18.1", ac=5)
def test_signed_out_users_can_neither_list_nor_register(client, db: Session):
    event = _open_event(db, starts_at=future_datetime(days=40))

    assert client.get(EVENTS_PATH).status_code == 401
    assert client.post(REGISTER_PATH, json={"event_id": str(event.id)}).status_code == 401
    assert _active_count(db, event.id) == 0


@pytest.mark.story("18.1", ac=5)
@pytest.mark.parametrize(
    "user",
    [
        Users.ORGANISER,
        Users.COORDINATOR,
        Users.VENUE_STAFF,
        Users.TECH_SUPPORT,
        Users.SAFETY_OFFICER,
        Users.LEAD,
    ],
    ids=lambda user: user.role,
)
def test_other_roles_can_neither_list_nor_register(login_as, db: Session, user):
    event = _open_event(db, starts_at=future_datetime(days=40))
    client = login_as(user)

    listing = client.get(EVENTS_PATH)
    registering = client.post(REGISTER_PATH, json={"event_id": str(event.id)})

    assert (listing.status_code, registering.status_code) == (403, 403)
    assert _active_count(db, event.id) == 0


@pytest.mark.story("18.1", ac=5)
def test_a_listed_event_carries_no_internal_planning_information(attendee_client, db: Session):
    event = _open_event(
        db,
        starts_at=future_datetime(days=40),
        purpose="Purpose-18.1-internal",
        internal_notes="Internal-notes-18.1",
        contact_name="Contact-18.1",
        contact_email="contact-18-1@example.com",
        contact_phone="+65 6000 1801",
        accessibility_notes="Accessibility-18.1",
        expected_attendance=73,
    )

    response = attendee_client.get(EVENTS_PATH, params={"limit": 100})

    item = _api_item(attendee_client, event.id)
    # No field carries the expected attendance as such. It does show through the places left
    # until someone registers, since capacity is the expected attendance (2.1 AC17) and the places
    # left are shown (decision 1, 14 Oct 2026).
    assert set(item) == LISTED_EVENT_KEYS
    assert item["places_left"] == 73
    for internal in (
        "Purpose-18.1-internal",
        "Internal-notes-18.1",
        "Contact-18.1",
        "contact-18-1@example.com",
        "+65 6000 1801",
        "Accessibility-18.1",
        Users.ORGANISER_2.full_name,
        Users.COORDINATOR.full_name,
    ):
        assert internal not in response.text


@pytest.mark.story("18.1", ac=4)
def test_registering_for_an_unknown_event_is_not_found(attendee_client):
    """The same answer as for an event that is not open to attendees (AC4)."""
    response = attendee_client.post(REGISTER_PATH, json={"event_id": str(uuid.uuid4())})

    assert response.status_code == 404
    assert response.json()["detail"] == service.REGISTRATION_EVENT_NOT_FOUND_MESSAGE


@pytest.mark.story("18.1", ac=1)
@pytest.mark.parametrize("body", [{"event_id": "not-a-uuid"}, {}])
def test_a_registration_without_a_valid_event_id_is_refused(attendee_client, body):
    assert attendee_client.post(REGISTER_PATH, json=body).status_code == 422


@pytest.mark.story("18.1", ac=5)
def test_an_attendee_named_in_the_request_is_ignored(attendee_client, db: Session):
    """The attendee is the signed-in user. One named in the body registers nobody else."""
    event = _open_event(db, starts_at=future_datetime(days=40))
    someone_else = _attendee(db)

    response = attendee_client.post(
        REGISTER_PATH, json={"event_id": str(event.id), "attendee_id": str(someone_else.id)}
    )

    assert response.status_code == 201
    registration = db.get(EventRegistration, uuid.UUID(response.json()["id"]))
    assert registration.attendee_id == Users.ATTENDEE.id
    assert _active_count(db, event.id) == 1


# =============================================================================================
# AC6 - conflict: one registration per attendee, one winner for the last place
# =============================================================================================
@pytest.mark.story("18.1", ac=6)
def test_a_second_registration_by_the_same_attendee_is_refused(attendee_client, db: Session):
    event = _open_event(db, starts_at=future_datetime(days=40))
    body = {"event_id": str(event.id)}

    first = attendee_client.post(REGISTER_PATH, json=body)
    second = attendee_client.post(REGISTER_PATH, json=body)

    assert (first.status_code, second.status_code) == (201, 409)
    assert second.json()["detail"] == service.ALREADY_REGISTERED_MESSAGE
    assert _active_count(db, event.id) == 1


@pytest.mark.story("18.1", ac=6)
def test_an_attendee_registered_for_a_full_event_is_told_they_are_registered(db: Session):
    event = _open_event(db, expected_attendance=1)
    attendee = _attendee(db)
    _register(db, event, attendee)

    with pytest.raises(service.AlreadyRegistered) as refusal:
        _register(db, event, attendee)

    assert str(refusal.value) == service.ALREADY_REGISTERED_MESSAGE


@pytest.mark.story("18.1", ac=6)
def test_an_integrity_error_other_than_a_duplicate_is_not_reported_as_one(db: Session):
    """Only the one-active-registration index means "already registered"; any other refusal by
    the database (here an attendee who does not exist) is a fault, not a duplicate."""
    event = _open_event(db)
    ghost = User(id=uuid.uuid4(), email="ghost@test.example", full_name="Ghost")

    with pytest.raises(IntegrityError):
        _register(db, event, ghost)
    assert _active_count(db, event.id) == 0


# =============================================================================================
# AC6 / AC7 - real concurrent transactions. These commit, so each cleans up after itself.
# =============================================================================================
@dataclass(frozen=True)
class _Race:
    event_id: uuid.UUID
    attendee_ids: list[uuid.UUID]


def _race(engine: Engine, *, capacity: int, attendees: int) -> _Race:
    with Session(engine) as session:
        event = _open_event(session, expected_attendance=capacity)
        people = [_attendee(session) for _ in range(attendees)]
        session.commit()
        return _Race(event_id=event.id, attendee_ids=[person.id for person in people])


def _clean_up(engine: Engine, race: _Race) -> None:
    with Session(engine) as session:
        session.execute(delete(AuditLog).where(AuditLog.actor_id.in_(race.attendee_ids)))
        session.execute(
            delete(EventRegistration).where(EventRegistration.event_id == race.event_id)
        )
        session.execute(delete(Event).where(Event.id == race.event_id))
        session.execute(delete(User).where(User.id.in_(race.attendee_ids)))
        session.commit()


def _attempt(
    engine: Engine,
    event_id: uuid.UUID,
    attendee_id: uuid.UUID,
    start: threading.Barrier | None = None,
    pids: queue.Queue[int] | None = None,
) -> str:
    """One registration in a session of its own, as one request would make it. When ``pids`` is
    given, the session's database process id goes into it first, so a test can watch it alone."""
    with Session(engine) as session:
        attendee = session.get(User, attendee_id)
        if pids is not None:
            pids.put(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
        if start is not None:
            start.wait()
        try:
            service.register(
                session, RegistrationCreate(event_id=event_id), attendee=attendee, now=NOW
            )
        except service.RegistrationRefused as refusal:
            return str(refusal)
        except service.RegistrationEventNotFound:
            return NOT_FOUND
        return REGISTERED


def _wait_until_blocked_or_done(engine: Engine, attempt: Future, pids: queue.Queue[int]) -> None:
    """Until ``attempt``'s own session waits on a lock (or, were nothing locked, it has already
    finished). Only that session is watched, so another one's wait cannot pass for it."""
    pid = pids.get(timeout=10)
    deadline = time.monotonic() + 10
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        while time.monotonic() < deadline:
            if attempt.done():
                return
            waiting = conn.execute(
                text("SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": pid},
            ).scalar()
            if waiting:
                return
            time.sleep(0.01)
    raise AssertionError("the registration neither finished nor waited for the event's row")


@pytest.mark.story("18.1", ac=6)
@pytest.mark.story("18.1", ac=7)
def test_two_attendees_racing_for_the_last_place_leave_one_registration(engine: Engine):
    race = _race(engine, capacity=1, attendees=2)
    start = threading.Barrier(2, timeout=10)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [
                pool.submit(_attempt, engine, race.event_id, attendee_id, start)
                for attendee_id in race.attendee_ids
            ]
            outcomes = sorted(attempt.result(timeout=30) for attempt in attempts)

        assert outcomes == sorted([REGISTERED, service.EVENT_FULL_MESSAGE])
        with Session(engine) as session:
            assert _active_count(session, race.event_id) == 1
    finally:
        _clean_up(engine, race)


@pytest.mark.story("18.1", ac=6)
@pytest.mark.story("18.1", ac=7)
def test_two_registrations_by_one_attendee_at_once_leave_one(engine: Engine):
    """A double-click, or the same page open in two tabs."""
    race = _race(engine, capacity=10, attendees=1)
    (attendee_id,) = race.attendee_ids
    start = threading.Barrier(2, timeout=10)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [
                pool.submit(_attempt, engine, race.event_id, attendee_id, start) for _ in range(2)
            ]
            outcomes = sorted(attempt.result(timeout=30) for attempt in attempts)

        assert outcomes == sorted([REGISTERED, service.ALREADY_REGISTERED_MESSAGE])
        with Session(engine) as session:
            assert _active_count(session, race.event_id) == 1
    finally:
        _clean_up(engine, race)


@pytest.mark.story("18.1", ac=7)
def test_a_registration_waits_for_the_event_and_counts_a_place_taken_meanwhile(engine: Engine):
    """Deterministic: another transaction holds the event's row with the last place taken but not
    yet committed. The registration must wait for it, then see the place gone. Were the row not
    held, it would count the uncommitted place as free and take it too."""
    race = _race(engine, capacity=1, attendees=2)
    holder_id, waiter_id = race.attendee_ids
    holder = Session(engine)
    try:
        holder.execute(
            select(Event.id).where(Event.id == race.event_id).with_for_update(key_share=True)
        )
        holder.add(
            EventRegistration(event_id=race.event_id, attendee_id=holder_id, registered_at=NOW)
        )
        holder.flush()
        pids: queue.Queue[int] = queue.Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            attempt = pool.submit(_attempt, engine, race.event_id, waiter_id, None, pids)
            _wait_until_blocked_or_done(engine, attempt, pids)
            holder.commit()
            outcome = attempt.result(timeout=30)

        assert outcome == service.EVENT_FULL_MESSAGE
        with Session(engine) as session:
            assert _active_count(session, race.event_id) == 1
    finally:
        holder.close()
        _clean_up(engine, race)


@pytest.mark.story("18.1", ac=6)
@pytest.mark.story("18.1", ac=7)
def test_a_registration_waits_for_another_still_being_made_and_finds_the_event_full(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
):
    """Deterministic: a real registration takes the last place and is held just before it
    commits, still holding the event's row. The second must wait for it, then find the event full.
    A row lock two registrations could hold at once (FOR SHARE) would let the second count the
    first's uncommitted place as free and take it too, every time, not only when a race lines up."""
    race = _race(engine, capacity=1, attendees=2)
    first_id, second_id = race.attendee_ids
    first_held = threading.Event()
    let_first_commit = threading.Event()
    record_audit = service.record_audit

    def record_audit_then_hold_the_first(db: Session, **kwargs):
        entry = record_audit(db, **kwargs)
        if kwargs["actor"].id == first_id:
            first_held.set()
            let_first_commit.wait(timeout=30)
        return entry

    monkeypatch.setattr(service, "record_audit", record_audit_then_hold_the_first)
    pids: queue.Queue[int] = queue.Queue()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(_attempt, engine, race.event_id, first_id)
            assert first_held.wait(timeout=30), "the first registration never reached its commit"
            second = pool.submit(_attempt, engine, race.event_id, second_id, None, pids)
            _wait_until_blocked_or_done(engine, second, pids)
            waited = not second.done()
            let_first_commit.set()
            outcomes = (first.result(timeout=30), second.result(timeout=30))

        assert waited, "the second registration did not wait for the first"
        assert outcomes == (REGISTERED, service.EVENT_FULL_MESSAGE)
        with Session(engine) as session:
            assert _active_count(session, race.event_id) == 1
    finally:
        let_first_commit.set()
        _clean_up(engine, race)


@pytest.mark.story("18.1", ac=7)
def test_a_registration_waiting_on_an_event_being_cancelled_is_refused(engine: Engine):
    """Deterministic: the event is cancelled in a transaction not yet committed. The registration
    waits for it, then finds the event no longer open - its status is read when it registers,
    not before."""
    race = _race(engine, capacity=10, attendees=1)
    (attendee_id,) = race.attendee_ids
    canceller = Session(engine)
    try:
        canceller.execute(
            update(Event).where(Event.id == race.event_id).values(status=EventStatus.CANCELLED)
        )
        pids: queue.Queue[int] = queue.Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            attempt = pool.submit(_attempt, engine, race.event_id, attendee_id, None, pids)
            _wait_until_blocked_or_done(engine, attempt, pids)
            canceller.commit()
            outcome = attempt.result(timeout=30)

        assert outcome == NOT_FOUND
        with Session(engine) as session:
            assert _active_count(session, race.event_id) == 0
    finally:
        canceller.close()
        _clean_up(engine, race)


@pytest.mark.story("18.1", ac=7)
def test_a_registration_does_not_wait_for_a_booking_being_written_for_the_event(engine: Engine):
    """Deterministic: a registration's FOR NO KEY UPDATE on the event's row does not wait for a
    write that only refers to the event, nor hold one up. A booking being written for the event
    holds a key-share lock on the event's row until it commits; FOR NO KEY UPDATE goes past it,
    where FOR UPDATE would wait. (It does wait for a change to the event's own row, as AC7 needs:
    a status changed meanwhile is read as it now stands.)"""
    race = _race(engine, capacity=10, attendees=1)
    (attendee_id,) = race.attendee_ids
    booking = Session(engine)
    try:
        make_booking(
            booking,
            event_id=race.event_id,
            venue_id=Venues.GRAND_HALL,
            starts_at=NOW + timedelta(days=30),
            ends_at=NOW + timedelta(days=30, hours=2),
        )
        pids: queue.Queue[int] = queue.Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            attempt = pool.submit(_attempt, engine, race.event_id, attendee_id, None, pids)
            _wait_until_blocked_or_done(engine, attempt, pids)
            waited = not attempt.done()
            booking.rollback()  # lets a registration that did wait go on, so this fails, not hangs
            outcome = attempt.result(timeout=30)

        assert not waited, "the registration waited for the booking being written"
        assert outcome == REGISTERED
    finally:
        booking.rollback()
        booking.close()
        _clean_up(engine, race)


@pytest.mark.story("18.1", ac=7)
def test_the_database_alone_refuses_a_second_active_registration(db: Session):
    """Bypassing the service: the index uq_event_registrations_active refuses the duplicate."""
    event = _open_event(db)
    attendee = _attendee(db)
    db.add(EventRegistration(event_id=event.id, attendee_id=attendee.id, registered_at=NOW))
    db.flush()

    with pytest.raises(IntegrityError) as refusal:
        with db.begin_nested():
            db.add(EventRegistration(event_id=event.id, attendee_id=attendee.id, registered_at=NOW))
            db.flush()

    assert service.ACTIVE_REGISTRATION_INDEX in str(refusal.value.orig)
