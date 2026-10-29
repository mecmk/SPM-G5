"""Story 18.2 - view and withdraw my registrations. INTEGRATION tests: the service and the API on
PostgreSQL.

Level: integration. Each test drives ``app/registrations`` through the HTTP API (``*_client``
fixtures) or its service functions, against the real schema in the rolled-back test transaction.
The race tests at the end commit real concurrent transactions and clean up after themselves. The
pure rules (which status a registration shows, whether it can still be withdrawn, why a withdrawal
was refused) are unit-tested in ``test_view_and_withdraw_unit.py``; the attendee's clicks are
e2e-tested in ``tests/e2e/my-registrations.spec.ts``. The AC3 boundary - the event's start - is
tested at both backend levels on purpose: the unit tests pin the rule, and these catch the
service handing it the wrong moment or the wrong row. The e2e spec repeats none of them.

Service-level tests pass ``now=NOW``, a moment after every seeded event has started, so a boundary
can be hit to the microsecond. Their attendees are made by the test, so a list holds only the
registrations the test made. API tests run on the real clock, so they make events relative to
today and find rows by id.

AC1 The attendee sees their registrations - one per event, the latest - each card with its event's
    name, picture, date and status (Registered, Withdrawn or Event cancelled) and when they
    registered and withdrew, events not yet started first (soonest first), then those that have
    started (latest first). An active registration is withdrawn from its event's page (AC9) after
    confirmation, and the place returns to capacity.
AC2 Withdrawal updates the registration and frees the place in one step on the server: the status,
    the moment it was withdrawn and the audit entry are written together, or not at all.
AC3 Withdrawal is allowed until the event starts; the registration closing time does not stop it.
    Once the event has started, its page offers no Withdraw and says why.
AC4 Registering again after withdrawing creates a new active registration under 18.1's rules; only
    one can be active at a time. The earlier one stays Withdrawn.
AC5 Attendees see only their own registrations, on the list and on each event's page, and nothing
    internal to the event's planning.
AC6 The API returns only the caller's own registrations: 401 signed out, 403 for other roles, and
    another attendee's registration is answered as not found, as an unknown one is - as is the
    page of an unlisted event only another attendee registered for.
AC7 A double-click withdraws once: one status change, one withdrawal time, one audit entry, also
    when both requests arrive at once.
AC8 A registration shows as Event cancelled when its event was cancelled or it was cancelled with
    the event, and cannot be withdrawn. One on an event sent back to Planning stays Registered and
    can be withdrawn.

Event page (fix f18.2.1), waiting on the backlog's Change Log:
AC9 Clicking anywhere on a registration's card opens its event's page (18.1 AC9), which also shows
    where the attendee stands and when they registered and withdrew. Withdraw is only on this
    page; once withdrawn, it offers Register again while the event is open (AC4). A back link
    returns to My registrations.
AC10 The page of an event the attendee registered for opens even once it is no longer listed -
    started, cancelled, sent back to Planning or made Private - with no places left or Register,
    and venues only while it still has them booked. Withdraw is offered only while AC3 and AC8
    allow it.
AC11 A withdrawal refused because the event started or was cancelled while its page was open says
    why, and the page then shows where the attendee stands: no Withdraw once it started, Event
    cancelled once it was cancelled.
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
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings.models import BookingStatus
from app.common.audit import AuditLog
from app.events.models import Event, EventStatus
from app.registrations import service
from app.registrations.models import EventRegistration, RegistrationStatus
from app.registrations.schemas import RegistrationCreate
from app.registrations.service import (
    REGISTRATION_EVENT_NOT_FOUND_MESSAGE,
    RegistrationStanding,
    RegistrationState,
)
from tests.support.factories import (
    future_datetime,
    make_booking,
    make_event,
    make_user,
    make_venue,
)
from tests.support.seed import Users

MINE_PATH = "/registrations"
REGISTER_PATH = "/registrations"

# After every seeded event has started (the latest is in 2028). Fixed, so a boundary can be hit
# exactly.
NOW = datetime(2030, 1, 15, 9, 0, tzinfo=UTC)
TICK = timedelta(microseconds=1)  # the smallest step a timestamptz stores
EARLIER = NOW - timedelta(days=3)  # when a test's registrations were made
LATER = NOW + timedelta(minutes=5)  # a second step after NOW, e.g. registering again

# AC1/AC5: everything a registration in the list may carry.
MY_REGISTRATION_KEYS = {
    "id",
    "event_id",
    "event_name",
    "cover_image_url",
    "starts_at",
    "ends_at",
    "status",
    "registered_at",
    "withdrawn_at",
    "can_withdraw",
    "guest_name",  # story 18.4 AC14 (fix f18.4.1)
}

# AC9 (fix f18.2.1): everything an event's page carries - the event, what its card on Upcoming
# events shows while it is listed (18.1 AC9), and the attendee's own registration.
PAGE_KEYS = {
    "id",
    "name",
    "description",
    "cover_image_url",
    "starts_at",
    "ends_at",
    "venues",
    "listing",
    "registration",
}

# AC10 (fix f18.2.1): what takes a registered event off the list, as a change to its row.
_UNLISTING = {
    "started": {
        "starts_at": NOW - timedelta(hours=1),
        "ends_at": NOW + timedelta(hours=2),
        "registration_closes_at": NOW - timedelta(hours=2),
    },
    "cancelled": {"status": EventStatus.CANCELLED},
    "sent back to Planning": {"status": EventStatus.PLANNING},
    "made Private": {"is_public": False},
}

# The contract: the audit action and the sentences an attendee is shown.
WITHDRAWN_ACTION = "EVENT_REGISTRATION_WITHDRAWN"
NOT_FOUND_MESSAGE = "This registration was not found."
ALREADY_WITHDRAWN_MESSAGE = "You have already withdrawn from this event."
EVENT_STARTED_MESSAGE = "This event has started, so you can no longer withdraw."
EVENT_CANCELLED_MESSAGE = "This event was cancelled, so there is nothing to withdraw from."

WITHDRAWN = "withdrawn"  # a race attempt that withdrew

# Every signed-in role but the attendee's (AC6: 403).
NOT_ATTENDEES = [user for user in Users.ONE_PER_ROLE if user.role != "ATTENDEE"]


def _withdraw_path(registration_id: uuid.UUID | str) -> str:
    return f"/registrations/{registration_id}/withdraw"


def _page_path(event_id: uuid.UUID) -> str:
    """AC9 (fix f18.2.1): the address of an event's page (18.1 AC9)."""
    return f"/registrations/events/{event_id}"


def _fixed_id(n: int) -> uuid.UUID:
    """An id chosen by the test, so rows can be given ids in the opposite order to the one the
    test expects: an order that only ever followed the ids would then be caught, not lucky."""
    return uuid.UUID(f"18200000-0000-0000-0000-{n:012d}")


def _when(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _event(db: Session, *, starts_at: datetime = NOW + timedelta(days=30), **overrides) -> Event:
    """A Confirmed, Public event taking registrations, closing a day before it starts."""
    return make_event(
        db,
        status=overrides.pop("status", EventStatus.CONFIRMED),
        organiser_id=overrides.pop("organiser_id", Users.ORGANISER_2.id),
        assigned_coordinator_id=Users.COORDINATOR.id,
        registration_required=True,
        is_public=True,
        starts_at=starts_at,
        ends_at=overrides.pop("ends_at", starts_at + timedelta(hours=3)),
        registration_closes_at=overrides.pop(
            "registration_closes_at", starts_at - timedelta(days=1)
        ),
        expected_attendance=overrides.pop("expected_attendance", 50),
        **overrides,
    )


def _attendee(db: Session) -> User:
    return make_user(db, role="ATTENDEE")


def _registration(
    db: Session,
    event: Event,
    attendee_id: uuid.UUID,
    *,
    status: str = RegistrationStatus.REGISTERED,
    registered_at: datetime = EARLIER,
    withdrawn_at: datetime | None = None,
    **overrides,
) -> EventRegistration:
    """A registration written straight to the table, as 18.1 or the seed would leave it."""
    row = EventRegistration(
        event_id=event.id,
        attendee_id=attendee_id,
        status=status,
        registered_at=registered_at,
        withdrawn_at=withdrawn_at,
        **overrides,
    )
    db.add(row)
    db.flush()
    return row


def _withdraw(
    db: Session, registration_id: uuid.UUID, attendee: User, *, now: datetime = NOW
) -> service.MyRegistrationItem:
    """As a request would: the test's rows are already saved when it arrives. (The commit only
    releases a savepoint; the test's transaction still rolls back.)"""
    db.commit()
    return service.withdraw_registration(db, registration_id, attendee=attendee, now=now)


def _register(
    db: Session, event: Event, attendee: User, *, now: datetime = LATER
) -> EventRegistration:
    """18.1's registration, as a request would make it."""
    db.commit()
    return service.register(db, RegistrationCreate(event_id=event.id), attendee=attendee, now=now)


def _mine(db: Session, attendee: User, *, now: datetime = NOW) -> list[service.MyRegistrationItem]:
    return service.list_my_registrations(db, attendee=attendee, now=now)


def _page(
    db: Session, attendee: User, event: Event, *, now: datetime = NOW
) -> service.AttendeeEvent:
    """AC9 (fix f18.2.1): the event as its page shows it to ``attendee``."""
    return service.get_attendee_event(db, event.id, attendee=attendee, now=now)


def _row(db: Session, registration_id: uuid.UUID) -> tuple[str, datetime | None]:
    """The registration's status and withdrawal time as the database holds them."""
    return db.execute(
        select(EventRegistration.status, EventRegistration.withdrawn_at).where(
            EventRegistration.id == registration_id
        )
    ).one()


def _active_count(db: Session, event_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count())
        .select_from(EventRegistration)
        .where(
            EventRegistration.event_id == event_id,
            EventRegistration.status == RegistrationStatus.REGISTERED,
        )
    )


def _withdrawal_audits(db: Session, registration_id: uuid.UUID) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.entity_id == registration_id, AuditLog.action == WITHDRAWN_ACTION
            )
        )
    )


def _api_item(client, registration_id: uuid.UUID) -> dict:
    response = client.get(MINE_PATH)
    assert response.status_code == 200
    (item,) = [i for i in response.json() if i["id"] == str(registration_id)]
    return item


# =============================================================================================
# AC1 - happy path: the list, and a withdrawal
# =============================================================================================
@pytest.mark.story("18.2", ac=1)
@pytest.mark.story("18.2", ac=5)
def test_an_attendee_sees_their_registration_with_its_event_and_status(
    attendee_client, db: Session
):
    starts_at = future_datetime(days=40)
    event = _event(
        db,
        starts_at=starts_at,
        name="Poetry Night 18.2",
        cover_image_url="/uploads/events/poetry-night-18-2.png",
    )
    registered_at = datetime(2026, 10, 12, 2, 0, tzinfo=UTC)
    registration = _registration(db, event, Users.ATTENDEE.id, registered_at=registered_at)

    item = _api_item(attendee_client, registration.id)

    assert set(item) == MY_REGISTRATION_KEYS  # AC5: nothing about the event's planning
    assert item["event_id"] == str(event.id)
    assert item["event_name"] == "Poetry Night 18.2"
    assert item["cover_image_url"] == "/uploads/events/poetry-night-18-2.png"  # 2.1 AC14
    assert _when(item["starts_at"]) == starts_at
    assert _when(item["ends_at"]) == starts_at + timedelta(hours=3)
    assert item["status"] == "REGISTERED"
    assert _when(item["registered_at"]) == registered_at
    assert item["withdrawn_at"] is None
    assert item["can_withdraw"] is True


@pytest.mark.story("18.2", ac=1)
def test_a_withdrawn_registration_is_listed_with_when_it_was_withdrawn(
    attendee_client, db: Session
):
    event = _event(db, starts_at=future_datetime(days=40))
    withdrawn_at = datetime(2026, 10, 13, 2, 0, tzinfo=UTC)
    registration = _registration(
        db,
        event,
        Users.ATTENDEE.id,
        status=RegistrationStatus.WITHDRAWN,
        withdrawn_at=withdrawn_at,
    )

    item = _api_item(attendee_client, registration.id)

    assert item["status"] == "WITHDRAWN"
    assert _when(item["withdrawn_at"]) == withdrawn_at
    assert item["can_withdraw"] is False


@pytest.mark.story("18.2", ac=1)
def test_events_not_yet_started_come_first_soonest_first_then_started_ones_latest_first(
    db: Session,
):
    """Ties go by name, then by id. An event starting exactly now has started (AC3). The rows are
    made in neither order, with ids against the expected order. (The two events of the same name
    and dates have different organisers: one organiser cannot hold both, 2.1 AC20.) One event in
    each group runs for days, so ending later than the next one starts: ordered by their ends,
    either group would come out differently."""
    attendee = _attendee(db)
    hours, days = timedelta(hours=3), timedelta(days=8)
    expected = [
        # (fixed id, name, starts_at, how long it runs, organiser), in the order the list must
        # give them
        (_fixed_id(9), "Soonest", NOW + timedelta(days=1), days, Users.ORGANISER_2),
        (_fixed_id(8), "Alpha", NOW + timedelta(days=3), hours, Users.ORGANISER_2),
        (_fixed_id(7), "Beta", NOW + timedelta(days=3), hours, Users.ORGANISER_2),
        (_fixed_id(1), "Same name", NOW + timedelta(days=4), hours, Users.ORGANISER_2),
        (_fixed_id(2), "Same name", NOW + timedelta(days=4), hours, Users.ORGANISER),
        (_fixed_id(6), "Furthest", NOW + timedelta(days=5), hours, Users.ORGANISER_2),
        (_fixed_id(5), "Starting now", NOW, hours, Users.ORGANISER_2),
        (_fixed_id(4), "Yesterday", NOW - timedelta(days=1), hours, Users.ORGANISER_2),
        (_fixed_id(3), "Last week", NOW - timedelta(days=7), days, Users.ORGANISER_2),
    ]
    for event_id, name, starts_at, runs_for, organiser in [
        *reversed(expected[3:]),
        *expected[:3],
    ]:
        event = _event(
            db,
            id=event_id,
            name=name,
            starts_at=starts_at,
            ends_at=starts_at + runs_for,
            organiser_id=organiser.id,
        )
        _registration(db, event, attendee.id)

    listed = [(item.event.id, item.event.name) for item in _mine(db, attendee)]

    assert listed == [(event_id, name) for event_id, name, *_ in expected]


@pytest.mark.story("18.2", ac=1)
def test_an_attendee_with_no_registrations_has_an_empty_list(db: Session):
    _registration(db, _event(db), _attendee(db).id)  # someone else's

    assert _mine(db, _attendee(db)) == []


@pytest.mark.story("18.2", ac=1)
def test_withdrawing_answers_200_with_the_registration_now_withdrawn(attendee_client, db: Session):
    event = _event(db, starts_at=future_datetime(days=40))
    registration = _registration(db, event, Users.ATTENDEE.id)

    before = datetime.now(UTC)
    response = attendee_client.post(_withdraw_path(registration.id))
    after = datetime.now(UTC)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == MY_REGISTRATION_KEYS
    assert body["id"] == str(registration.id)
    assert body["event_id"] == str(event.id)
    assert body["status"] == "WITHDRAWN"
    assert body["can_withdraw"] is False
    assert before <= _when(body["withdrawn_at"]) <= after
    assert _row(db, registration.id) == (RegistrationStatus.WITHDRAWN, _when(body["withdrawn_at"]))


@pytest.mark.story("18.2", ac=1)
def test_a_withdrawal_is_stamped_with_the_moment_it_was_made(db: Session):
    attendee = _attendee(db)
    registration = _registration(db, _event(db), attendee.id)

    item = _withdraw(db, registration.id, attendee, now=NOW)

    assert item.standing is RegistrationStanding.WITHDRAWN
    assert item.can_withdraw is False
    assert _row(db, registration.id) == (RegistrationStatus.WITHDRAWN, NOW)
    assert db.get(EventRegistration, registration.id).registered_at == EARLIER


@pytest.mark.story("18.2", ac=1)
@pytest.mark.story("18.2", ac=2)
def test_withdrawing_from_a_full_event_gives_its_place_back(db: Session):
    event = _event(db, expected_attendance=1)
    holder, waiting = _attendee(db), _attendee(db)
    registration = _registration(db, event, holder.id)
    (before,) = service.list_registration_events(
        db, attendee=waiting, now=NOW, limit=100, offset=0
    ).items
    assert (before.places_left, before.state) == (0, RegistrationState.FULL)

    _withdraw(db, registration.id, holder)

    (after,) = service.list_registration_events(
        db, attendee=waiting, now=NOW, limit=100, offset=0
    ).items
    assert (after.places_left, after.state) == (1, RegistrationState.OPEN)
    _register(db, event, waiting, now=NOW)
    assert _active_count(db, event.id) == 1


@pytest.mark.story("18.2", ac=1)
@pytest.mark.parametrize("registration_id", ["not-a-uuid", "123"])
def test_withdrawing_a_registration_id_that_is_not_a_uuid_is_refused(
    attendee_client, registration_id
):
    assert attendee_client.post(_withdraw_path(registration_id)).status_code == 422


# =============================================================================================
# AC2 - one step on the server
# =============================================================================================
@pytest.mark.story("18.2", ac=2)
def test_a_withdrawal_is_recorded_in_the_audit_log_by_the_attendee(db: Session):
    attendee = _attendee(db)
    event = _event(db)
    registration = _registration(db, event, attendee.id)

    _withdraw(db, registration.id, attendee)

    (entry,) = _withdrawal_audits(db, registration.id)
    assert entry.actor_id == attendee.id
    assert entry.entity_type == "event_registration"
    assert entry.details == {"event_id": str(event.id)}


class _AuditLogUnavailable(Exception):
    """Raised only by the stand-in audit writer below, so nothing else can satisfy the test."""


@pytest.mark.story("18.2", ac=2)
def test_when_the_audit_entry_cannot_be_written_the_registration_is_not_withdrawn(
    db: Session, monkeypatch: pytest.MonkeyPatch
):
    attendee = _attendee(db)
    event = _event(db, expected_attendance=1)
    registration = _registration(db, event, attendee.id)
    audits_attempted: list[str] = []

    def audit_log_unavailable(*_args, action: str, **_kwargs):
        audits_attempted.append(action)
        raise _AuditLogUnavailable

    monkeypatch.setattr(service, "record_audit", audit_log_unavailable)
    with pytest.raises(_AuditLogUnavailable):
        _withdraw(db, registration.id, attendee)
    db.rollback()  # as the request's session does when it ends

    assert audits_attempted == [WITHDRAWN_ACTION]
    assert _row(db, registration.id) == (RegistrationStatus.REGISTERED, None)
    assert _active_count(db, event.id) == 1


@pytest.mark.story("18.2", ac=2)
def test_a_withdrawal_changes_that_registration_and_no_other(db: Session):
    attendee, neighbour = _attendee(db), _attendee(db)
    event, other_event = _event(db), _event(db)
    registration = _registration(db, event, attendee.id)
    other_registration = _registration(db, other_event, attendee.id)
    neighbours_registration = _registration(db, event, neighbour.id)

    _withdraw(db, registration.id, attendee)

    assert _row(db, registration.id) == (RegistrationStatus.WITHDRAWN, NOW)
    assert _row(db, other_registration.id) == (RegistrationStatus.REGISTERED, None)
    assert _row(db, neighbours_registration.id) == (RegistrationStatus.REGISTERED, None)


# =============================================================================================
# AC3 - until the event starts
# =============================================================================================
@pytest.mark.story("18.2", ac=3)
def test_a_withdrawal_a_moment_before_the_event_starts_is_accepted(db: Session):
    attendee = _attendee(db)
    registration = _registration(db, _event(db, starts_at=NOW + TICK), attendee.id)

    _withdraw(db, registration.id, attendee, now=NOW)

    assert _row(db, registration.id) == (RegistrationStatus.WITHDRAWN, NOW)


@pytest.mark.story("18.2", ac=3)
@pytest.mark.parametrize("starts_at", [NOW, NOW - TICK], ids=["as-it-starts", "after-it-started"])
def test_a_withdrawal_once_the_event_has_started_is_refused_and_changes_nothing(
    db: Session, starts_at: datetime
):
    attendee = _attendee(db)
    registration = _registration(db, _event(db, starts_at=starts_at), attendee.id)

    with pytest.raises(service.EventStarted) as refusal:
        _withdraw(db, registration.id, attendee, now=NOW)

    assert str(refusal.value) == EVENT_STARTED_MESSAGE
    assert _row(db, registration.id) == (RegistrationStatus.REGISTERED, None)
    assert _withdrawal_audits(db, registration.id) == []


@pytest.mark.story("18.2", ac=3)
def test_withdrawing_from_an_event_that_has_started_answers_409_saying_so(
    attendee_client, db: Session
):
    started = datetime.now(UTC) - timedelta(hours=1)
    registration = _registration(db, _event(db, starts_at=started), Users.ATTENDEE.id)

    response = attendee_client.post(_withdraw_path(registration.id))

    assert response.status_code == 409
    assert response.json() == {"detail": EVENT_STARTED_MESSAGE}
    assert _row(db, registration.id) == (RegistrationStatus.REGISTERED, None)


@pytest.mark.story("18.2", ac=3)
def test_a_withdrawal_after_registration_has_closed_but_before_the_event_is_accepted(db: Session):
    attendee = _attendee(db)
    event = _event(
        db, starts_at=NOW + timedelta(days=2), registration_closes_at=NOW - timedelta(days=1)
    )
    registration = _registration(db, event, attendee.id)

    _withdraw(db, registration.id, attendee, now=NOW)

    assert _row(db, registration.id) == (RegistrationStatus.WITHDRAWN, NOW)


@pytest.mark.story("18.2", ac=3)
def test_the_list_offers_withdrawal_only_for_active_registrations_on_events_not_started(
    db: Session,
):
    attendee = _attendee(db)
    upcoming = _event(db, starts_at=NOW + TICK)
    starting = _event(db, starts_at=NOW)  # still running at NOW: it ends three hours later
    withdrawn = _event(db, starts_at=NOW + timedelta(days=9))
    _registration(db, upcoming, attendee.id)
    _registration(db, starting, attendee.id)
    _registration(
        db, withdrawn, attendee.id, status=RegistrationStatus.WITHDRAWN, withdrawn_at=EARLIER
    )

    offered = {item.event.id: item.can_withdraw for item in _mine(db, attendee, now=NOW)}

    assert offered == {upcoming.id: True, starting.id: False, withdrawn.id: False}


# =============================================================================================
# AC4 - registering again after withdrawing
# =============================================================================================
@pytest.mark.story("18.2", ac=4)
@pytest.mark.story("18.2", ac=1)
def test_registering_again_after_withdrawing_makes_a_new_active_registration_listed_once(
    attendee_client, db: Session
):
    event = _event(db, starts_at=future_datetime(days=40))
    first = _registration(
        db, event, Users.ATTENDEE.id, registered_at=datetime.now(UTC) - timedelta(days=1)
    )
    withdrawal = attendee_client.post(_withdraw_path(first.id))
    assert withdrawal.status_code == 200

    again = attendee_client.post(REGISTER_PATH, json={"event_id": str(event.id)})

    assert again.status_code == 201
    second_id = again.json()["id"]
    assert second_id != str(first.id)
    assert _row(db, first.id) == (
        RegistrationStatus.WITHDRAWN,
        _when(withdrawal.json()["withdrawn_at"]),
    )
    assert _active_count(db, event.id) == 1
    listed = [i for i in attendee_client.get(MINE_PATH).json() if i["event_id"] == str(event.id)]
    assert [(i["id"], i["status"]) for i in listed] == [(second_id, "REGISTERED")]


@pytest.mark.story("18.2", ac=4)
def test_registering_again_while_the_new_registration_is_active_is_refused(db: Session):
    attendee = _attendee(db)
    event = _event(db)
    first = _registration(db, event, attendee.id)
    _withdraw(db, first.id, attendee)
    _register(db, event, attendee, now=LATER)

    with pytest.raises(service.AlreadyRegistered):
        _register(db, event, attendee, now=LATER + timedelta(minutes=1))

    assert _active_count(db, event.id) == 1


@pytest.mark.story("18.2", ac=4)
@pytest.mark.story("18.2", ac=1)
def test_an_attendee_who_withdraws_twice_has_both_kept_and_the_latest_listed(db: Session):
    """The database keeps one active registration per attendee per event, but any number of
    withdrawn ones."""
    attendee = _attendee(db)
    event = _event(db)
    first = _registration(db, event, attendee.id)
    _withdraw(db, first.id, attendee, now=NOW)
    second = _register(db, event, attendee, now=LATER)
    withdrawn_again_at = LATER + timedelta(minutes=1)

    _withdraw(db, second.id, attendee, now=withdrawn_again_at)

    assert _row(db, first.id) == (RegistrationStatus.WITHDRAWN, NOW)
    assert _row(db, second.id) == (RegistrationStatus.WITHDRAWN, withdrawn_again_at)
    (item,) = _mine(db, attendee, now=withdrawn_again_at)
    assert (item.registration.id, item.standing) == (second.id, RegistrationStanding.WITHDRAWN)


@pytest.mark.story("18.2", ac=1)
@pytest.mark.story("18.2", ac=4)
def test_the_registration_made_last_is_the_one_listed_whatever_its_id(db: Session):
    """After registering again, the new registration is listed rather than the withdrawn one,
    by when each was made. The new one has the lower id, so an order by id would list the other."""
    attendee = _attendee(db)
    event = _event(db)
    _registration(
        db,
        event,
        attendee.id,
        id=_fixed_id(2),
        status=RegistrationStatus.WITHDRAWN,
        registered_at=EARLIER,
        withdrawn_at=EARLIER + timedelta(hours=1),
    )
    _registration(
        db, event, attendee.id, id=_fixed_id(1), registered_at=EARLIER + timedelta(days=1)
    )

    (item,) = _mine(db, attendee)

    assert (item.registration.id, item.standing) == (_fixed_id(1), RegistrationStanding.REGISTERED)


@pytest.mark.story("18.2", ac=1)
def test_registrations_for_one_event_made_at_the_same_moment_list_the_same_one_every_time(
    db: Session,
):
    """A stable list: of two withdrawn registrations stamped alike, the higher id is shown. It is
    written last, so a scan in the order the rows were written would give the other one."""
    attendee = _attendee(db)
    event = _event(db)
    for n in (1, 2):
        _registration(
            db,
            event,
            attendee.id,
            id=_fixed_id(n),
            status=RegistrationStatus.WITHDRAWN,
            withdrawn_at=EARLIER,
        )

    (item,) = _mine(db, attendee)

    assert item.registration.id == _fixed_id(2)


@pytest.mark.story("18.2", ac=4)
def test_a_place_taken_by_someone_else_meanwhile_cannot_be_registered_for_again(db: Session):
    event = _event(db, expected_attendance=1)
    leaver, newcomer = _attendee(db), _attendee(db)
    registration = _registration(db, event, leaver.id)
    _withdraw(db, registration.id, leaver)
    _register(db, event, newcomer, now=LATER)

    with pytest.raises(service.EventFull):
        _register(db, event, leaver, now=LATER + timedelta(minutes=1))

    assert _active_count(db, event.id) == 1


# =============================================================================================
# AC8 - a cancelled event, and one sent back to Planning
# =============================================================================================
@pytest.mark.story("18.2", ac=8)
def test_a_registration_on_a_cancelled_event_shows_as_cancelled_and_cannot_be_withdrawn(
    attendee_client, db: Session
):
    """The event Cancelled with its registrations untouched: a Confirmed event sent back to
    Planning (9.4 AC3, 19.2 AC8) keeps its registrations (18.1 AC4), and may then be cancelled
    (6.2) with them still active."""
    event = _event(db, starts_at=future_datetime(days=40), status=EventStatus.CANCELLED)
    registration = _registration(db, event, Users.ATTENDEE.id)

    item = _api_item(attendee_client, registration.id)
    response = attendee_client.post(_withdraw_path(registration.id))

    assert (item["status"], item["can_withdraw"]) == ("EVENT_CANCELLED", False)
    assert response.status_code == 409
    assert response.json() == {"detail": EVENT_CANCELLED_MESSAGE}
    assert _row(db, registration.id) == (RegistrationStatus.REGISTERED, None)


@pytest.mark.story("18.2", ac=8)
def test_a_registration_cancelled_with_its_event_shows_as_cancelled_and_cannot_be_withdrawn(
    db: Session,
):
    """The registration itself marked CANCELLED: ConnectSphere cancelled it, as when its event is
    cancelled (event_registrations.status)."""
    attendee = _attendee(db)
    registration = _registration(db, _event(db), attendee.id, status=RegistrationStatus.CANCELLED)

    (item,) = _mine(db, attendee)
    with pytest.raises(service.WithdrawalEventCancelled):
        _withdraw(db, registration.id, attendee)

    assert (item.standing, item.can_withdraw) == (RegistrationStanding.EVENT_CANCELLED, False)
    assert _row(db, registration.id) == (RegistrationStatus.CANCELLED, None)


@pytest.mark.story("18.2", ac=8)
def test_a_registration_on_an_event_sent_back_to_planning_is_still_listed_and_withdrawable(
    db: Session,
):
    attendee = _attendee(db)
    event = _event(db, status=EventStatus.PLANNING)
    registration = _registration(db, event, attendee.id)

    (item,) = _mine(db, attendee)
    assert (item.standing, item.can_withdraw) == (RegistrationStanding.REGISTERED, True)

    _withdraw(db, registration.id, attendee)

    assert _row(db, registration.id) == (RegistrationStatus.WITHDRAWN, NOW)


# =============================================================================================
# AC5 / AC6 - only the caller's own
# =============================================================================================
@pytest.mark.story("18.2", ac=6)
def test_signed_out_users_can_neither_list_nor_withdraw(client, db: Session):
    registration = _registration(db, _event(db), Users.ATTENDEE.id)

    assert client.get(MINE_PATH).status_code == 401
    assert client.post(_withdraw_path(registration.id)).status_code == 401
    assert _row(db, registration.id) == (RegistrationStatus.REGISTERED, None)


@pytest.mark.story("18.2", ac=6)
@pytest.mark.parametrize("user", NOT_ATTENDEES, ids=lambda user: user.role)
def test_other_roles_can_neither_list_nor_withdraw(login_as, db: Session, user):
    registration = _registration(db, _event(db), Users.ATTENDEE.id)
    signed_in = login_as(user)

    assert signed_in.get(MINE_PATH).status_code == 403
    assert signed_in.post(_withdraw_path(registration.id)).status_code == 403
    assert _row(db, registration.id) == (RegistrationStatus.REGISTERED, None)


@pytest.mark.story("18.2", ac=5)
@pytest.mark.story("18.2", ac=6)
def test_an_attendee_is_sent_only_their_own_registrations(client, db: Session):
    event = _event(db, starts_at=future_datetime(days=40))
    mine, theirs = _attendee(db), _attendee(db)
    my_registration = _registration(db, event, mine.id)
    _registration(db, event, theirs.id)
    client.login(mine.email)

    for params in ({}, {"attendee_id": str(theirs.id)}):
        response = client.get(MINE_PATH, params=params)
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [str(my_registration.id)]


@pytest.mark.story("18.2", ac=6)
def test_another_attendees_registration_is_not_found_just_as_an_unknown_one_is(
    attendee_client, db: Session
):
    theirs = _registration(db, _event(db, starts_at=future_datetime(days=40)), _attendee(db).id)

    response = attendee_client.post(_withdraw_path(theirs.id))
    unknown = attendee_client.post(_withdraw_path(uuid.uuid4()))

    assert response.status_code == unknown.status_code == 404
    assert response.json() == unknown.json() == {"detail": NOT_FOUND_MESSAGE}
    assert _row(db, theirs.id) == (RegistrationStatus.REGISTERED, None)


# =============================================================================================
# AC7 - a double-click withdraws once
# =============================================================================================
@pytest.mark.story("18.2", ac=7)
def test_a_second_withdrawal_is_refused_and_leaves_the_first_one_as_it_was(
    attendee_client, db: Session
):
    registration = _registration(
        db, _event(db, starts_at=future_datetime(days=40)), Users.ATTENDEE.id
    )
    first = attendee_client.post(_withdraw_path(registration.id))

    second = attendee_client.post(_withdraw_path(registration.id))

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json() == {"detail": ALREADY_WITHDRAWN_MESSAGE}
    assert _row(db, registration.id) == (
        RegistrationStatus.WITHDRAWN,
        _when(first.json()["withdrawn_at"]),
    )
    assert len(_withdrawal_audits(db, registration.id)) == 1


# =============================================================================================
# AC9-AC11 - the event's page (fix f18.2.1)
# =============================================================================================
@pytest.mark.story("18.2", ac=5)
@pytest.mark.story("18.2", ac=9)
def test_an_events_page_carries_the_attendees_registration_as_their_list_does(
    attendee_client, db: Session
):
    event = _event(db, starts_at=future_datetime(days=40), name="Poetry Page 18.2")
    registration = _registration(db, event, Users.ATTENDEE.id)

    response = attendee_client.get(_page_path(event.id))

    assert response.status_code == 200
    page = response.json()
    assert set(page) == PAGE_KEYS  # AC5: nothing about the event's planning
    assert page["registration"] == _api_item(attendee_client, registration.id)
    assert (page["name"], page["listing"]["state"]) == ("Poetry Page 18.2", "REGISTERED")


@pytest.mark.story("18.2", ac=9)
def test_an_events_page_has_no_registration_for_an_attendee_who_never_registered(db: Session):
    event = _event(db)

    page = _page(db, _attendee(db), event)

    assert page.registration is None
    assert page.listing is not None
    assert page.listing.state == RegistrationState.OPEN


@pytest.mark.story("18.2", ac=4)
@pytest.mark.story("18.2", ac=9)
def test_an_events_page_shows_a_withdrawal_and_then_the_registration_made_again(db: Session):
    event = _event(db)
    attendee = _attendee(db)
    first = _registration(db, event, attendee.id)
    _withdraw(db, first.id, attendee)

    withdrawn = _page(db, attendee, event)
    again = _register(db, event, attendee)
    registered = _page(db, attendee, event, now=LATER)

    assert withdrawn.registration is not None
    assert (withdrawn.registration.registration.id, withdrawn.registration.standing) == (
        first.id,
        RegistrationStanding.WITHDRAWN,
    )
    assert withdrawn.registration.registration.withdrawn_at == NOW
    # AC4: open again, so it can be registered for from the page.
    assert withdrawn.listing is not None
    assert withdrawn.listing.state == RegistrationState.OPEN
    assert registered.registration is not None
    assert (registered.registration.registration.id, registered.registration.standing) == (
        again.id,
        RegistrationStanding.REGISTERED,
    )


@pytest.mark.story("18.2", ac=10)
@pytest.mark.parametrize(
    ("change", "standing", "can_withdraw"),
    [
        ("started", RegistrationStanding.REGISTERED, False),
        ("cancelled", RegistrationStanding.EVENT_CANCELLED, False),
        ("sent back to Planning", RegistrationStanding.REGISTERED, True),
        ("made Private", RegistrationStanding.REGISTERED, True),
    ],
)
def test_a_registered_events_page_opens_once_it_is_no_longer_listed(
    db: Session, change: str, standing: RegistrationStanding, can_withdraw: bool
):
    event = _event(db, name=f"No longer listed: {change}")
    attendee = _attendee(db)
    _registration(db, event, attendee.id)
    db.execute(update(Event).where(Event.id == event.id).values(**_UNLISTING[change]))
    db.expire(event)

    page = _page(db, attendee, event)

    assert page.event.name == f"No longer listed: {change}"
    assert page.listing is None  # no places left, no Register
    assert page.registration is not None
    assert (page.registration.standing, page.registration.can_withdraw) == (standing, can_withdraw)


@pytest.mark.story("18.2", ac=3)
@pytest.mark.story("18.2", ac=10)
def test_a_registered_events_page_offers_withdrawal_until_the_moment_the_event_starts(
    db: Session,
):
    attendee = _attendee(db)
    starting_soon = _event(db, starts_at=NOW + TICK, registration_closes_at=None)
    starting_now = _event(db, starts_at=NOW, registration_closes_at=None)
    _registration(db, starting_soon, attendee.id)
    _registration(db, starting_now, attendee.id)

    soon = _page(db, attendee, starting_soon)
    now = _page(db, attendee, starting_now)

    assert soon.listing is not None
    assert soon.registration is not None
    assert soon.registration.can_withdraw is True
    assert now.listing is None
    assert now.registration is not None
    assert now.registration.can_withdraw is False


@pytest.mark.story("18.2", ac=10)
def test_an_unlisted_events_page_names_only_the_venues_it_still_has_booked(db: Session):
    attendee = _attendee(db)
    cancelled = _event(db, status=EventStatus.CANCELLED)
    planning = _event(db, status=EventStatus.PLANNING)
    released = make_venue(db, name="Released Hall 18.2", location="Pier 3")
    kept = make_venue(db, name="Kept Hall 18.2", location="Pier 4")
    for event, venue, status in (
        (cancelled, released, BookingStatus.CANCELLED),
        (planning, kept, BookingStatus.APPROVED),
    ):
        make_booking(
            db,
            event_id=event.id,
            venue_id=venue.id,
            status=status,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
        )
        _registration(db, event, attendee.id)

    assert _page(db, attendee, cancelled).venues == []
    assert [venue.name for venue in _page(db, attendee, planning).venues] == ["Kept Hall 18.2"]


@pytest.mark.story("18.2", ac=5)
@pytest.mark.story("18.2", ac=6)
def test_an_events_page_never_shows_another_attendees_registration(db: Session):
    event = _event(db)
    mine, theirs = _attendee(db), _attendee(db)
    _registration(db, event, theirs.id)

    page = _page(db, mine, event)

    assert page.registration is None


@pytest.mark.story("18.2", ac=6)
def test_an_unlisted_event_only_another_attendee_registered_for_is_not_found(
    attendee_client, db: Session
):
    """18.1 AC10: one answer for it and an unknown event, so whose registrations exist is not
    given away."""
    event = _event(db, starts_at=future_datetime(days=40), status=EventStatus.CANCELLED)
    _registration(db, event, _attendee(db).id)

    theirs = attendee_client.get(_page_path(event.id))
    unknown = attendee_client.get(_page_path(uuid.uuid4()))

    assert theirs.status_code == unknown.status_code == 404
    assert theirs.json() == unknown.json() == {"detail": REGISTRATION_EVENT_NOT_FOUND_MESSAGE}


@pytest.mark.story("18.2", ac=11)
def test_after_a_withdrawal_refused_because_the_event_was_cancelled_its_page_says_cancelled(
    db: Session,
):
    """What the page shows once it is loaded again after the refusal."""
    event = _event(db)
    attendee = _attendee(db)
    registration = _registration(db, event, attendee.id)
    db.execute(update(Event).where(Event.id == event.id).values(status=EventStatus.CANCELLED))
    db.expire(event)

    with pytest.raises(service.WithdrawalEventCancelled):
        _withdraw(db, registration.id, attendee)
    page = _page(db, attendee, event)

    assert page.listing is None
    assert page.registration is not None
    assert (page.registration.standing, page.registration.can_withdraw) == (
        RegistrationStanding.EVENT_CANCELLED,
        False,
    )


# --- real concurrent transactions. These commit, so each cleans up after itself. -------------
@dataclass(frozen=True)
class _Withdrawable:
    event_id: uuid.UUID
    attendee_id: uuid.UUID
    registration_id: uuid.UUID


def _withdrawable(engine: Engine) -> _Withdrawable:
    with Session(engine) as session:
        event = _event(session)
        attendee = _attendee(session)
        registration = _registration(session, event, attendee.id)
        session.commit()
        return _Withdrawable(
            event_id=event.id, attendee_id=attendee.id, registration_id=registration.id
        )


def _clean_up(engine: Engine, made: _Withdrawable) -> None:
    with Session(engine) as session:
        # By the registration as well as the actor, so a row written under the wrong actor goes too.
        session.execute(
            delete(AuditLog).where(
                or_(
                    AuditLog.actor_id == made.attendee_id,
                    AuditLog.entity_id == made.registration_id,
                )
            )
        )
        session.execute(
            delete(EventRegistration).where(EventRegistration.event_id == made.event_id)
        )
        session.execute(delete(Event).where(Event.id == made.event_id))
        session.execute(delete(User).where(User.id == made.attendee_id))
        session.commit()


def _attempt(
    engine: Engine,
    made: _Withdrawable,
    start: threading.Barrier | None = None,
    pids: queue.Queue[int] | None = None,
) -> str:
    """One withdrawal in a session of its own, as one request would make it. When ``pids`` is
    given, the session's database process id goes into it first, so a test can watch it alone."""
    with Session(engine) as session:
        attendee = session.get(User, made.attendee_id)
        if pids is not None:
            pids.put(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
        if start is not None:
            start.wait()
        try:
            service.withdraw_registration(session, made.registration_id, attendee=attendee, now=NOW)
        except service.WithdrawalRefused as refusal:
            return str(refusal)
        return WITHDRAWN


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
    raise AssertionError("the withdrawal neither finished nor waited for the registration's row")


def _audit_count(engine: Engine, made: _Withdrawable) -> int:
    with Session(engine) as session:
        return len(_withdrawal_audits(session, made.registration_id))


@pytest.mark.story("18.2", ac=7)
def test_two_withdrawals_arriving_at_once_withdraw_once(engine: Engine):
    """A double-click, or the same page open in two tabs."""
    made = _withdrawable(engine)
    start = threading.Barrier(2, timeout=10)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [pool.submit(_attempt, engine, made, start) for _ in range(2)]
            outcomes = sorted(attempt.result(timeout=30) for attempt in attempts)

        assert outcomes == sorted([WITHDRAWN, ALREADY_WITHDRAWN_MESSAGE])
        with Session(engine) as session:
            assert _row(session, made.registration_id) == (RegistrationStatus.WITHDRAWN, NOW)
        assert _audit_count(engine, made) == 1
    finally:
        _clean_up(engine, made)


@pytest.mark.story("18.2", ac=7)
def test_a_withdrawal_waits_for_one_in_progress_and_is_then_refused(engine: Engine):
    """Deterministic: another transaction has withdrawn the registration but not yet committed.
    The second withdrawal must wait for it, then find the registration already withdrawn. Had it
    read the status first and written after, it would have seen it still active and withdrawn it
    a second time."""
    made = _withdrawable(engine)
    first = Session(engine)
    pids: queue.Queue[int] = queue.Queue()
    try:
        first.execute(
            update(EventRegistration)
            .where(EventRegistration.id == made.registration_id)
            .values(status=RegistrationStatus.WITHDRAWN, withdrawn_at=EARLIER)
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            attempt = pool.submit(_attempt, engine, made, None, pids)
            try:
                _wait_until_blocked_or_done(engine, attempt, pids)
            finally:
                # Lets a withdrawal that is waiting go on even if the wait failed, so this fails
                # rather than hangs: leaving the pool waits for the attempt.
                first.commit()
            outcome = attempt.result(timeout=30)

        assert outcome == ALREADY_WITHDRAWN_MESSAGE
        with Session(engine) as session:
            assert _row(session, made.registration_id) == (RegistrationStatus.WITHDRAWN, EARLIER)
        assert _audit_count(engine, made) == 0
    finally:
        first.close()
        _clean_up(engine, made)
