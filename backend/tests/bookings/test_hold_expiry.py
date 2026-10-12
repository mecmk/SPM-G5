"""Story 12.7 - expire tentative venue holds, as the customer has them (constitution s12.7, the
rework of 12 Oct 2026: R1 to R16, after the customer's Q34, Q44, Q45, Q48 and Q51).

The hold is an approved booking waiting for its event to be confirmed. Venue Staff set its expiry
when they approve the request - there is no default - and the coordinator confirming the event
completes it. A pending request still blocks its slot (12.1 AC3) but has no hold to expire.

AC1  Venue Staff give the hold its expiry when they approve, and can change it. It is on the
     booking, its queue entry, the event's booking list and the venue calendar.
AC2  The event's coordinator is warned 24 hours before a hold expires, once, and told when it
     expires.
AC3  At its expiry, a hold whose event is not confirmed expires: the booking becomes Expired, and
     its venue is free for that period at once - before any timer runs.
AC4  An event confirmed a minute before a hold expires keeps the booking; from the expiry on, the
     hold has expired.
AC5  An expiry must be in the future and no later than the start of the booked period, so a
     request whose booked period has started can be neither raised nor approved.
AC6  An expired booking holds nothing and covers no venue requirement (12.5).
AC7  Venue Staff can change the expiry of a hold that has not expired, with a reason, and the
     coordinator is told; an expired hold is never revived, nor is a completed one changed.
AC8  Expired bookings stay in the event's booking list.
AC9  Only Venue Staff can change an expiry.
AC10 Of the event's confirmation and the hold's expiry at the same moment, only the first lands.
AC11 An expired hold leaves the venue calendar and no longer keeps its venue out of a search.

Also migration 018, which gives no booking already in the database a hold, its trigger that
completes an event's holds when the event becomes Confirmed (R4) - written here as a plain status
change, since 21.2 AC12's Confirm is not built yet - and the timer that sweeps lapsed holds while
the API runs. The page flows are tests/e2e/venue-hold-expiry.spec.ts.

Until the customer says otherwise (constitution s12.7, Q6) the warning comes 24 hours before:
``shipped_hold_settings`` pins it, so a local .env cannot change what these tests mean.

Every case uses fresh venues and Planning events assigned to Chloe, held in March 2027, and
expiries a few days from now, so no seeded booking is held, warned or expired in the way.
Postgres's ``now()``, which the trigger reads, is when the test's transaction began, so a hold the
trigger must find lapsed lapsed an hour before the test.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app import main
from app.auth.models import User
from app.bookings import service
from app.bookings.models import BookingStatus, VenueBooking
from app.bookings.schemas import BookingRequestIn
from app.common.audit import AuditLog
from app.config import settings
from app.events.models import Event, EventStatus
from app.notifications.models import Notification
from app.venues.models import Venue
from tests.support.factories import make_booking, make_event, make_venue, make_venue_requirement
from tests.support.seed import Bookings, Users

SGT = timezone(timedelta(hours=8))
BOOKINGS_PATH = "/bookings"
MIGRATION_018 = (
    Path(__file__).resolve().parents[2] / "db" / "migrations" / "018_venue_hold_expiry.sql"
)
# The schema as it stood before migration 018: no hold, no trigger and no EXPIRED status - so no
# expired booking either, such as the one seeded for the e2e spec.
PRE_018_SCHEMA = (
    "DELETE FROM venue_bookings WHERE status = 'EXPIRED';"
    " DROP TRIGGER trg_events_complete_venue_holds ON events;"
    " DROP FUNCTION complete_venue_holds();"
    " ALTER TABLE venue_bookings DROP COLUMN hold_expires_at, DROP COLUMN hold_reminded_at,"
    " DROP COLUMN hold_completed_at, DROP COLUMN hold_expiry_change_reason,"
    " DROP COLUMN hold_expiry_changed_by_id, DROP COLUMN hold_expiry_changed_at;"
    " ALTER TABLE venue_bookings DROP CONSTRAINT ck_venue_bookings_status;"
    " ALTER TABLE venue_bookings ADD CONSTRAINT ck_venue_bookings_status CHECK"
    " (status IN ('PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN', 'CANCELLED'));"
)
# The reason every change of an expiry carries (Q27), unless a case leaves it out on purpose.
CHANGE_REASON = "The organiser asked for more time to confirm the layout."
# The seeded bookings (R11): the approved ones hold their venue, the pending ones hold nothing.
SEEDED_APPROVED = [Bookings.APPROVED_GRAND_HALL, Bookings.APPROVED_WORKSHOP_SEMINAR_ROOM]
SEEDED_PENDING = [
    Bookings.PENDING_SEMINAR_ROOM,
    Bookings.PENDING_EXHIBITION_FOYER,
    Bookings.PENDING_GRAND_HALL,
    Bookings.PENDING_APPROVE_E2E_CARD,
    Bookings.PENDING_APPROVE_E2E_DETAIL,
    Bookings.PENDING_REJECT_E2E_CARD,
    Bookings.PENDING_REJECT_E2E_DETAIL,
]
# R7: every status but APPROVED has no hold whose expiry could change.
NO_HOLD_STATUSES = [
    BookingStatus.PENDING,
    BookingStatus.REJECTED,
    BookingStatus.WITHDRAWN,
    BookingStatus.CANCELLED,
    BookingStatus.EXPIRED,
]


@pytest.fixture(autouse=True)
def shipped_hold_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The warning this story ships with (Q6), whatever a local .env says."""
    monkeypatch.setattr(settings, "hold_expiry_reminder_hours", 24)


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    """A moment in March 2027, Singapore time."""
    return datetime(2027, 3, day, hour, minute, tzinfo=SGT)


def _in(days: float = 0, hours: float = 0, minutes: float = 0) -> datetime:
    """A moment that far from now, to the second."""
    return datetime.now(UTC).replace(microsecond=0) + timedelta(
        days=days, hours=hours, minutes=minutes
    )


def _moment(value: str | None) -> datetime | None:
    """A timestamp from a response body, which the API writes in UTC."""
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


def _event(db: Session, **overrides) -> Event:
    """A Planning event for 40 people on 15 March 2027, assigned to Chloe unless said otherwise."""
    return make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=overrides.pop("assigned_coordinator_id", Users.COORDINATOR.id),
        starts_at=overrides.pop("starts_at", _at(15, 9)),
        ends_at=overrides.pop("ends_at", _at(15, 17)),
        expected_attendance=overrides.pop("expected_attendance", 40),
        **overrides,
    )


def _venue(db: Session) -> Venue:
    """A venue for 100 with no opening hours recorded, so it suits and is open any time."""
    return make_venue(db, name=f"Hold Hall {uuid.uuid4().hex[:8]}", capacity=100)


def _request(
    db: Session,
    *,
    status: str = BookingStatus.PENDING,
    event: Event | None = None,
    venue: Venue | None = None,
    **overrides,
) -> VenueBooking:
    """A request for 15 March 2027, 09:00-17:00, with no hold: pending unless said otherwise. An
    APPROVED one is a booking approved before holds expired (R12)."""
    event = _event(db) if event is None else event
    venue = _venue(db) if venue is None else venue
    return make_booking(
        db,
        venue_id=venue.id,
        event_id=event.id,
        starts_at=overrides.pop("starts_at", _at(15, 9)),
        ends_at=overrides.pop("ends_at", _at(15, 17)),
        status=status,
        **overrides,
    )


def _hold(
    db: Session,
    *,
    expires_at: datetime,
    status: str = BookingStatus.APPROVED,
    **overrides,
) -> VenueBooking:
    """A request for 15 March 2027, 09:00-17:00, approved by Vera a day ago with a hold that
    expires at ``expires_at`` - or, with ``status=EXPIRED``, one whose hold already has."""
    return _request(
        db,
        status=status,
        decided_by_id=overrides.pop("decided_by_id", Users.VENUE_STAFF.id),
        decided_at=overrides.pop("decided_at", _in(days=-1)),
        hold_expires_at=expires_at,
        **overrides,
    )


def _confirm(db: Session, event: Event) -> None:
    """The event becomes Confirmed. 21.2 AC12's Confirm is not built yet, so the status is written
    directly; the trigger completes the event's holds as it would for any route (R4)."""
    event.status = EventStatus.CONFIRMED
    db.flush()
    db.expire_all()


def _raise(client, event: Event, venue: Venue, requirement_id: uuid.UUID | None = None):
    body = {"event_id": str(event.id), "venue_id": str(venue.id)}
    if requirement_id is not None:
        body["venue_requirement_id"] = str(requirement_id)
    return client.post(BOOKINGS_PATH, json=body)


def _created(response) -> dict:
    assert response.status_code == 201, response.text
    return response.json()


def _approve(client, booking_id: uuid.UUID, expires_at: Any):
    """Approve a request, giving its hold ``expires_at`` (R2)."""
    value = expires_at.isoformat() if isinstance(expires_at, datetime) else expires_at
    return client.post(f"{BOOKINGS_PATH}/{booking_id}/approve", json={"hold_expires_at": value})


def _change(client, booking_id: uuid.UUID, expires_at: Any, reason: Any = CHANGE_REASON):
    """Give a hold a new expiry, with a reason (Q27) unless ``reason`` is None."""
    value = expires_at.isoformat() if isinstance(expires_at, datetime) else expires_at
    body = {"hold_expires_at": value}
    if reason is not None:
        body["hold_expiry_change_reason"] = reason
    return client.patch(f"{BOOKINGS_PATH}/{booking_id}", json=body)


def _switch(client, booking_id: uuid.UUID, venue: Venue):
    """Switch a pending request to ``venue`` (story 12.5, decided 11 Oct 2026)."""
    return client.post(f"{BOOKINGS_PATH}/{booking_id}/switch", json={"venue_id": str(venue.id)})


def _calendar(client, venue: Venue) -> list[dict]:
    """The venue's calendar for 15 March 2027, Singapore time."""
    response = client.get(
        f"/venues/{venue.id}/calendar",
        params={"starts_at": _at(15, 0).isoformat(), "ends_at": _at(16, 0).isoformat()},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _reloaded(db: Session, booking: VenueBooking) -> VenueBooking:
    db.expire_all()
    return db.get(VenueBooking, booking.id)


def _notifications(db: Session, notification_type: str, booking_id: uuid.UUID) -> list:
    """Every ``notification_type`` about one booking, oldest first."""
    return list(
        db.scalars(
            select(Notification)
            .where(
                Notification.notification_type == notification_type,
                Notification.related_entity_id == booking_id,
            )
            .order_by(Notification.created_at)
        ).all()
    )


def _audits(db: Session, action: str, booking_id: uuid.UUID) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog).where(AuditLog.action == action, AuditLog.entity_id == booking_id)
        ).all()
    )


# --- AC1: Venue Staff set the expiry when they approve; it shows wherever the booking does ----
@pytest.mark.story("12.7", ac=1)
def test_venue_staff_set_the_holds_expiry_as_they_approve_and_it_shows_everywhere(login_as, db):
    """R1, R2, R8, R13: the expiry Venue Staff give is on the booking, its queue entry, the event's
    booking list and the booked window on the venue's calendar, and the coordinator's approval
    notice says the event must be confirmed by then."""
    event, venue = _event(db), _venue(db)
    request = _request(db, event=event, venue=venue)
    expiry = datetime(2027, 3, 1, 18, 30, tzinfo=SGT)
    staff = login_as(Users.VENUE_STAFF)

    response = _approve(staff, request.id, expiry)

    assert response.status_code == 200, response.text
    approved = response.json()
    assert (approved["status"], _moment(approved["hold_expires_at"])) == (
        BookingStatus.APPROVED,
        expiry,
    )
    assert approved["hold_completed_at"] is None
    queue = staff.get(BOOKINGS_PATH, params={"status": "APPROVED"}).json()
    (entry,) = [item for item in queue["items"] if item["id"] == str(request.id)]
    assert _moment(entry["hold_expires_at"]) == expiry
    coordinator = login_as(Users.COORDINATOR)
    (outcome,) = coordinator.get(f"{BOOKINGS_PATH}/for-event/{event.id}").json()
    assert _moment(outcome["hold_expires_at"]) == expiry
    (window,) = _calendar(coordinator, venue)
    assert (window["reason"], _moment(window["hold_expires_at"])) == ("BOOKED", expiry)
    (told,) = _notifications(db, "BOOKING_APPROVED", request.id)
    assert told.recipient_id == Users.COORDINATOR.id
    assert told.message == (
        f"Vera Venue approved the request for {venue.name} on Mon 15 Mar 2027 from 09:00 to 17:00."
        " It is held for the event until Mon 1 Mar 2027 at 18:30: if the event is not confirmed by"
        " then, the hold expires and the venue is released."
    )


@pytest.mark.story("12.7", ac=1)
@pytest.mark.parametrize(
    "body",
    [None, {}, {"hold_expires_at": None}],
    ids=["no body", "no expiry", "a null expiry"],
)
def test_an_approval_needs_the_holds_expiry(venue_staff_client, db, body):
    """R2: the system dictates no default (Q45), so Venue Staff must give one."""
    request = _request(db)

    response = venue_staff_client.post(f"{BOOKINGS_PATH}/{request.id}/approve", json=body)

    assert response.status_code == 422, response.text
    assert _reloaded(db, request).status == BookingStatus.PENDING
    assert _notifications(db, "BOOKING_APPROVED", request.id) == []


@pytest.mark.story("12.7", ac=1)
def test_an_approval_expiry_without_a_time_zone_is_refused(venue_staff_client, db):
    """A wall-clock time names no moment until it names its zone."""
    request = _request(db)

    response = _approve(venue_staff_client, request.id, "2027-03-01T18:30:00")

    assert response.status_code == 422
    assert _reloaded(db, request).status == BookingStatus.PENDING


@pytest.mark.story("12.7", ac=1)
def test_a_pending_request_blocks_its_venue_with_no_hold_to_expire(login_as, db):
    """R1: the request has no expiry - not when it is raised, not on its queue entry, not on its
    held window - and however long it waits it is neither warned about nor expired: it waits for
    Venue Staff's decision."""
    event, venue = _event(db), _venue(db)
    coordinator = login_as(Users.COORDINATOR)

    raised = _created(_raise(coordinator, event, venue))

    assert raised["hold_expires_at"] is None
    (window,) = _calendar(coordinator, venue)
    assert (window["reason"], window["hold_expires_at"]) == ("HELD", None)
    queue = login_as(Users.VENUE_STAFF).get(BOOKINGS_PATH, params={"status": "PENDING"}).json()
    (entry,) = [item for item in queue["items"] if item["id"] == raised["id"]]
    assert entry["hold_expires_at"] is None
    booking_id = uuid.UUID(raised["id"])
    service.sweep_holds(db, now=_in(days=3650))
    assert db.get(VenueBooking, booking_id).status == BookingStatus.PENDING
    assert _notifications(db, "BOOKING_HOLD_EXPIRING", booking_id) == []
    assert _notifications(db, "BOOKING_HOLD_EXPIRED", booking_id) == []


@pytest.mark.story("12.7", ac=1)
@pytest.mark.story("12.7", ac=5)
def test_seeded_bookings_hold_their_venue_as_the_customer_has_it(db):
    """R11: each seeded approved booking holds its venue until the start of its booked period,
    setup included - AC5's latest - so a development database that is not re-seeded keeps them
    booked. The seeded pending requests hold nothing to expire, and the Craft Fair's expired
    booking keeps who approved it, when, and the expiry it lapsed at."""
    approved = [db.get(VenueBooking, booking_id) for booking_id in SEEDED_APPROVED]
    pending = db.scalars(select(VenueBooking).where(VenueBooking.id.in_(SEEDED_PENDING))).all()
    expired = db.get(VenueBooking, Bookings.EXPIRED_CRAFT_FAIR_FOYER)

    assert [(row.status, row.hold_expires_at, row.hold_completed_at) for row in approved] == [
        (BookingStatus.APPROVED, row.held_from, None) for row in approved
    ]
    assert {(row.status, row.hold_expires_at) for row in pending} == {(BookingStatus.PENDING, None)}
    assert (
        expired.status,
        expired.decided_by_id,
        expired.decided_at,
        expired.hold_expires_at,
    ) == (
        BookingStatus.EXPIRED,
        Users.VENUE_STAFF.id,
        datetime(2026, 9, 29, 10, 0, tzinfo=SGT),
        datetime(2026, 10, 5, 10, 0, tzinfo=SGT),
    )


# --- AC5: at approval, in the future and no later than the booked start -----------------------
@pytest.mark.story("12.7", ac=5)
@pytest.mark.parametrize(
    ("expires_at", "detail"),
    [
        (lambda: _in() - timedelta(seconds=1), "The hold must expire in the future."),
        (
            lambda: _at(15, 9, 1),
            "The hold must expire by the start of the booked period, Mon 15 Mar 2027 at 09:00.",
        ),
    ],
    ids=["a second ago", "a minute after the booked start"],
)
def test_an_approvals_expiry_must_be_in_the_future_and_by_the_booked_start(
    venue_staff_client, db, expires_at, detail
):
    request = _request(db)

    response = _approve(venue_staff_client, request.id, expires_at())

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    row = _reloaded(db, request)
    assert (row.status, row.hold_expires_at) == (BookingStatus.PENDING, None)
    assert _notifications(db, "BOOKING_APPROVED", request.id) == []


@pytest.mark.story("12.7", ac=5)
def test_an_approval_may_hold_the_venue_until_exactly_the_booked_start(venue_staff_client, db):
    """The booked period starts at 08:30 here: 30 minutes of setup before the 09:00 event."""
    request = _request(db, setup_minutes=30)

    response = _approve(venue_staff_client, request.id, _at(15, 8, 30))

    assert response.status_code == 200, response.text
    assert _reloaded(db, request).hold_expires_at == _at(15, 8, 30)


@pytest.mark.story("12.7", ac=5)
def test_a_request_whose_booked_period_has_started_cannot_be_approved(venue_staff_client, db):
    """R3: no expiry can be both in the future and no later than a start already past, so Venue
    Staff were too late for this one; it stays pending."""
    starts_at = _in(hours=-1)
    request = _request(db, starts_at=starts_at, ends_at=starts_at + timedelta(hours=4))

    response = _approve(venue_staff_client, request.id, _in(hours=1))

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This booked period has already started, so the venue cannot be held for it."
    )
    assert _reloaded(db, request).status == BookingStatus.PENDING


@pytest.mark.story("12.7", ac=5)
def test_a_request_whose_booked_period_has_started_is_refused(coordinator_client, db):
    """R3 with Q8: such a request could never be approved, so it is not raised."""
    starts_at = _in(hours=-1)
    event = _event(db, starts_at=starts_at, ends_at=starts_at + timedelta(hours=4))

    response = _raise(coordinator_client, event, _venue(db))

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This booked period has already started, so the venue cannot be held for it."
    )
    assert db.scalar(select(func.count()).where(VenueBooking.event_id == event.id)) == 0


@pytest.mark.story("12.7", ac=5)
def test_a_switch_for_a_booked_period_that_has_started_is_refused(coordinator_client, db):
    """R3 with Q26: the new request takes the requirement's period as it stands now, which here
    has started since the old request was raised, so the switch is refused and the old request
    stays pending."""
    event = _event(db)
    requirement_id = make_venue_requirement(
        db, event.id, capacity=40, starts_at=_in(hours=-1), ends_at=_in(hours=3)
    )
    request = _request(db, event=event, venue_requirement_id=requirement_id)

    response = _switch(coordinator_client, request.id, _venue(db))

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This booked period has already started, so the venue cannot be held for it."
    )
    assert _reloaded(db, request).status == BookingStatus.PENDING


# --- AC1/AC7: Venue Staff change the expiry of an open hold; the coordinator is told ----------
@pytest.mark.story("12.7", ac=7)
@pytest.mark.story("12.7", ac=1)
def test_venue_staff_extend_a_hold_and_the_coordinator_is_told(login_as, db):
    """The coordinator told is whoever holds the event now (20.1 AC4) - Carl, since the hand-over.
    The expiry is written in Singapore time, as every event's times are. Q27/Q30: the change
    carries a reason, and the reason, who made the change and when are on the booking, on the
    event's booking list, in Carl's notice and in the audit entry."""
    event = _event(db, assigned_coordinator_id=Users.COORDINATOR_2.id)
    venue = _venue(db)
    was = _in(days=2)
    hold = _hold(db, event=event, venue=venue, expires_at=was)
    extended = datetime(2027, 3, 1, 18, 30, tzinfo=SGT)
    changed_from = datetime.now(UTC)

    response = _change(login_as(Users.VENUE_STAFF), hold.id, extended)

    changed_by = datetime.now(UTC)
    assert response.status_code == 200, response.text
    booking = response.json()
    assert _moment(booking["hold_expires_at"]) == extended
    assert booking["hold_expiry_change_reason"] == CHANGE_REASON
    assert booking["hold_expiry_changed_by"] == {
        "id": str(Users.VENUE_STAFF.id),
        "full_name": "Vera Venue",
    }
    assert changed_from <= _moment(booking["hold_expiry_changed_at"]) <= changed_by
    assert _reloaded(db, hold).hold_expires_at == extended
    (outcome,) = login_as(Users.COORDINATOR_2).get(f"{BOOKINGS_PATH}/for-event/{event.id}").json()
    assert (
        outcome["hold_expires_at"],
        outcome["hold_expiry_change_reason"],
        outcome["hold_expiry_changed_by"],
        outcome["hold_expiry_changed_at"],
    ) == (
        booking["hold_expires_at"],
        CHANGE_REASON,
        booking["hold_expiry_changed_by"],
        booking["hold_expiry_changed_at"],
    )
    (told,) = _notifications(db, "BOOKING_HOLD_EXPIRY_CHANGED", hold.id)
    assert told.recipient_id == Users.COORDINATOR_2.id
    assert told.event_id == event.id
    assert told.message == (
        f'Vera Venue changed when the hold on {venue.name} for "{event.name}" expires, to Mon 1'
        f" Mar 2027 at 18:30. The event must be confirmed by then. Reason: {CHANGE_REASON}"
    )
    (audit,) = _audits(db, "BOOKING_HOLD_EXPIRY_CHANGED", hold.id)
    assert audit.actor_id == Users.VENUE_STAFF.id
    changed = audit.details["hold_expires_at"]
    assert (_moment(changed["from"]), _moment(changed["to"])) == (was, extended)
    assert audit.details["reason"] == CHANGE_REASON


@pytest.mark.story("12.7", ac=1)
def test_venue_staff_may_also_bring_a_hold_forward(venue_staff_client, db):
    """AC1 lets Venue Staff change it, not only extend it - and so release the venue sooner
    (Q19)."""
    hold = _hold(db, expires_at=_in(days=5))
    sooner = _in(days=1)

    response = _change(venue_staff_client, hold.id, sooner)

    assert response.status_code == 200, response.text
    assert _reloaded(db, hold).hold_expires_at == sooner


@pytest.mark.story("12.7", ac=5)
@pytest.mark.parametrize(
    ("new_expiry", "detail"),
    [
        (lambda: _in() - timedelta(seconds=1), "The hold must expire in the future."),
        (
            lambda: _at(15, 9, 1),
            "The hold must expire by the start of the booked period, Mon 15 Mar 2027 at 09:00.",
        ),
    ],
    ids=["a second ago", "a minute after the booked start"],
)
def test_a_new_expiry_must_be_in_the_future_and_by_the_booked_start(
    venue_staff_client, db, new_expiry, detail
):
    was = _in(days=2)
    hold = _hold(db, expires_at=was)

    response = _change(venue_staff_client, hold.id, new_expiry())

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    assert _reloaded(db, hold).hold_expires_at == was
    assert _notifications(db, "BOOKING_HOLD_EXPIRY_CHANGED", hold.id) == []


@pytest.mark.story("12.7", ac=5)
def test_a_new_expiry_exactly_at_the_booked_start_is_allowed(venue_staff_client, db):
    """The booked period starts at 08:30 here: 30 minutes of setup before the 09:00 event."""
    hold = _hold(db, expires_at=_in(days=2), setup_minutes=30)

    response = _change(venue_staff_client, hold.id, _at(15, 8, 30))

    assert response.status_code == 200, response.text
    assert _reloaded(db, hold).hold_expires_at == _at(15, 8, 30)


@pytest.mark.story("12.7", ac=5)
def test_a_new_expiry_without_a_time_zone_is_refused(venue_staff_client, db):
    was = _in(days=2)
    hold = _hold(db, expires_at=was)

    response = _change(venue_staff_client, hold.id, "2027-03-01T18:30:00")

    assert response.status_code == 422
    assert _reloaded(db, hold).hold_expires_at == was


@pytest.mark.story("12.7", ac=7)
@pytest.mark.parametrize(
    ("reason", "refusal"),
    [(None, "missing"), ("", "string_too_short"), ("   ", "string_too_short")],
    ids=["missing", "empty", "spaces only"],
)
def test_a_new_expiry_needs_a_reason(venue_staff_client, db, reason, refusal):
    """Q29: as a rejection's reason - required, and blank or spaces only does not count."""
    was = _in(days=2)
    hold = _hold(db, expires_at=was)

    response = _change(venue_staff_client, hold.id, _in(days=4), reason=reason)

    assert response.status_code == 422, response.text
    (error,) = response.json()["detail"]
    assert (error["type"], error["loc"]) == (refusal, ["body", "hold_expiry_change_reason"])
    assert _reloaded(db, hold).hold_expires_at == was
    assert _notifications(db, "BOOKING_HOLD_EXPIRY_CHANGED", hold.id) == []


@pytest.mark.story("12.7", ac=7)
def test_a_second_change_replaces_the_first_on_the_booking_and_the_audit_log_keeps_both(
    venue_staff_client, db
):
    """Q30: the booking shows its latest change; every change is in the audit log."""
    hold = _hold(db, expires_at=_in(days=2))

    first = _change(venue_staff_client, hold.id, _in(days=4), reason="The organiser asked.")
    second = _change(venue_staff_client, hold.id, _in(days=3), reason="Another event needs it.")

    assert (first.status_code, second.status_code) == (200, 200), second.text
    assert second.json()["hold_expiry_change_reason"] == "Another event needs it."
    audited = sorted(
        entry.details["reason"] for entry in _audits(db, "BOOKING_HOLD_EXPIRY_CHANGED", hold.id)
    )
    assert audited == ["Another event needs it.", "The organiser asked."]


@pytest.mark.story("12.7", ac=7)
def test_a_changes_reason_who_and_when_are_stored_together(db):
    """Q31: the latest change is three columns set together, or not at all, so no page shows a
    reason with nobody behind it."""
    with pytest.raises(IntegrityError) as excinfo:
        _hold(
            db, expires_at=_in(days=2), hold_expiry_change_reason="A reason with nobody behind it."
        )

    assert "ck_venue_bookings_hold_expiry_change" in str(excinfo.value.orig)


# --- AC7: only an open hold takes a new expiry -----------------------------------------------
@pytest.mark.story("12.7", ac=7)
@pytest.mark.parametrize("status", NO_HOLD_STATUSES)
def test_a_request_with_no_hold_takes_no_new_expiry(venue_staff_client, db, status):
    """R7: a pending request has no hold yet (R1); a rejected, withdrawn or cancelled one never
    had one; an expired one is never revived."""
    if status == BookingStatus.EXPIRED:
        booking = _hold(db, expires_at=_in(days=-2), status=status)
    else:
        booking = _request(db, status=status)
    was = booking.hold_expires_at

    response = _change(venue_staff_client, booking.id, _in(days=4))

    assert response.status_code == 409
    assert response.json()["detail"] == (
        f"This request is {status}, so it has no hold to give a new expiry."
    )
    assert _reloaded(db, booking).hold_expires_at == was


@pytest.mark.story("12.7", ac=7)
def test_a_completed_hold_takes_no_new_expiry(venue_staff_client, db):
    """R4: once its event is confirmed the booking is held for good."""
    event = _event(db)
    was = _in(days=2)
    hold = _hold(db, event=event, expires_at=was)
    _confirm(db, event)

    response = _change(venue_staff_client, hold.id, _in(days=4))

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This booking's hold was completed when its event was confirmed, so it has no expiry to"
        " change."
    )
    assert _reloaded(db, hold).hold_expires_at == was


@pytest.mark.story("12.7", ac=7)
def test_a_booking_approved_before_holds_expired_takes_no_new_expiry(venue_staff_client, db):
    """R12: migration 018 gave the bookings already approved no hold, and none is made now."""
    approved = _request(db, status=BookingStatus.APPROVED)

    response = _change(venue_staff_client, approved.id, _in(days=4))

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This booking was approved before holds expired, so it has no expiry to change."
    )
    assert _reloaded(db, approved).hold_expires_at is None


@pytest.mark.story("12.7", ac=7)
def test_a_lapsed_hold_cannot_be_revived(venue_staff_client, db):
    """Lapsed a second ago and not yet swept by any timer: it expires instead of being extended."""
    hold = _hold(db, expires_at=_in() - timedelta(seconds=1))

    response = _change(venue_staff_client, hold.id, _in(days=4))

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This request is EXPIRED, so it has no hold to give a new expiry."
    )
    assert _reloaded(db, hold).status == BookingStatus.EXPIRED


@pytest.mark.story("12.7", ac=7)
def test_a_hold_lapsing_as_it_is_changed_expires_instead(db):
    """On the clock the change reads: a hold that lapses between the sweep and the change is
    expired there and then, never extended."""
    expiry = _in(days=3)
    hold = _hold(db, expires_at=expiry)
    booking = service.get_booking_for_decision(db, hold.id)
    staff = db.get(User, Users.VENUE_STAFF.id)

    with pytest.raises(service.NoOpenHold) as refusal:
        service.change_hold_expiry(
            db,
            booking,
            hold_expires_at=expiry + timedelta(days=2),
            reason=CHANGE_REASON,
            actor=staff,
            now=expiry,
        )

    assert str(refusal.value) == "This request is EXPIRED, so it has no hold to give a new expiry."
    row = _reloaded(db, hold)
    assert (row.status, row.hold_expires_at) == (BookingStatus.EXPIRED, expiry)


@pytest.mark.story("12.7", ac=7)
def test_changing_the_expiry_of_an_unknown_request_is_not_found(venue_staff_client):
    response = _change(venue_staff_client, uuid.uuid4(), _in(days=4))

    assert response.status_code == 404


# --- AC9: only Venue Staff --------------------------------------------------------------------
@pytest.mark.story("12.7", ac=9)
@pytest.mark.parametrize(
    "user",
    [Users.COORDINATOR, Users.ORGANISER, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda user: user.role,
)
def test_only_venue_staff_may_change_an_expiry(client, db, user):
    """Chloe is the event's own coordinator, and is still refused: the expiry is Venue Staff's."""
    was = _in(days=2)
    hold = _hold(db, expires_at=was)
    client.login(user)

    response = _change(client, hold.id, _in(days=4))

    assert response.status_code == 403
    assert _reloaded(db, hold).hold_expires_at == was


@pytest.mark.story("12.7", ac=9)
def test_signed_out_visitors_cannot_change_an_expiry(client, db):
    was = _in(days=2)
    hold = _hold(db, expires_at=was)

    response = _change(client, hold.id, _in(days=4))

    assert response.status_code == 401
    assert _reloaded(db, hold).hold_expires_at == was


# --- AC2: the coordinator is warned once, a day ahead -----------------------------------------
@pytest.mark.story("12.7", ac=2)
def test_the_coordinator_is_warned_once_when_a_day_remains(db):
    """Carl holds the event now, so the warning is his (20.1 AC4). The sweeps run at fixed
    moments, so they may warn seeded bookings as well: only this one's warnings are counted."""
    event = _event(db, assigned_coordinator_id=Users.COORDINATOR_2.id)
    venue = _venue(db)
    expiry = datetime(2026, 12, 4, 2, 0, tzinfo=UTC)  # Fri 4 Dec 2026, 10:00 in Singapore
    hold = _hold(db, event=event, venue=venue, expires_at=expiry)

    warned = service.remind_expiring_holds(db, now=expiry - timedelta(hours=24))
    warned_again = service.remind_expiring_holds(db, now=expiry - timedelta(hours=1))

    assert hold.id in {each.id for each in warned}
    assert hold.id not in {each.id for each in warned_again}
    (warning,) = _notifications(db, "BOOKING_HOLD_EXPIRING", hold.id)
    assert warning.recipient_id == Users.COORDINATOR_2.id
    assert warning.event_id == event.id
    assert warning.message == (
        f'{venue.name} is held for "{event.name}" until Fri 4 Dec 2026 at 10:00. If the event is'
        " not confirmed by then, the hold expires and the venue is released."
    )


@pytest.mark.story("12.7", ac=2)
@pytest.mark.parametrize(
    ("before_expiry", "is_warned"),
    [(timedelta(hours=24, seconds=1), False), (timedelta(hours=24), True)],
    ids=["a second early", "exactly a day ahead"],
)
def test_the_warning_comes_a_day_before_the_expiry(db, before_expiry, is_warned):
    expiry = _in(days=3)
    hold = _hold(db, expires_at=expiry)

    service.remind_expiring_holds(db, now=expiry - before_expiry)

    assert bool(_notifications(db, "BOOKING_HOLD_EXPIRING", hold.id)) is is_warned


@pytest.mark.story("12.7", ac=2)
def test_one_sweep_warns_only_the_open_holds_about_to_lapse(db):
    """A pending request, a hold its event's confirmation completed and a booking approved before
    holds expired have nothing to warn about; a lapsed hold is told it expired instead."""
    expiry = _in(days=3)
    pending = _request(db)
    confirmed_event = _event(db)
    completed = _hold(db, event=confirmed_event, expires_at=expiry + timedelta(hours=2))
    _confirm(db, confirmed_event)
    legacy = _request(db, status=BookingStatus.APPROVED)
    lapsed = _hold(db, expires_at=expiry - timedelta(hours=2))
    due = _hold(db, expires_at=expiry + timedelta(hours=2))

    service.sweep_holds(db, now=expiry - timedelta(hours=1))

    for quiet in (pending, completed, legacy, lapsed):
        assert _notifications(db, "BOOKING_HOLD_EXPIRING", quiet.id) == []
    assert len(_notifications(db, "BOOKING_HOLD_EXPIRED", lapsed.id)) == 1
    assert len(_notifications(db, "BOOKING_HOLD_EXPIRING", due.id)) == 1


@pytest.mark.story("12.7", ac=2)
@pytest.mark.story("12.7", ac=7)
def test_a_new_expiry_inside_the_last_day_is_its_own_warning(venue_staff_client, db):
    """The change notice already names the expiry, so no second warning follows it."""
    hold = _hold(db, expires_at=_in(days=3))

    assert _change(venue_staff_client, hold.id, _in(hours=12)).status_code == 200
    service.remind_expiring_holds(db, now=_in(hours=1))

    assert _notifications(db, "BOOKING_HOLD_EXPIRING", hold.id) == []


@pytest.mark.story("12.7", ac=2)
@pytest.mark.story("12.7", ac=7)
def test_an_extension_past_the_last_day_warns_again_before_the_new_expiry(venue_staff_client, db):
    expiry = _in(days=2)
    hold = _hold(db, expires_at=expiry)
    service.remind_expiring_holds(db, now=expiry - timedelta(hours=20))
    extended = _in(days=6)

    assert _change(venue_staff_client, hold.id, extended).status_code == 200
    service.remind_expiring_holds(db, now=extended - timedelta(hours=20))

    assert len(_notifications(db, "BOOKING_HOLD_EXPIRING", hold.id)) == 2


@pytest.mark.story("12.7", ac=2)
def test_an_approval_inside_the_last_day_is_its_own_warning(venue_staff_client, db):
    """R6: the approval notice already names the expiry, as a change's does."""
    request = _request(db)

    assert _approve(venue_staff_client, request.id, _in(hours=12)).status_code == 200
    service.remind_expiring_holds(db, now=_in(hours=1))

    assert _notifications(db, "BOOKING_HOLD_EXPIRING", request.id) == []


# --- AC3: at its expiry the booking becomes Expired, and the coordinator is told -------------
@pytest.mark.story("12.7", ac=3)
@pytest.mark.story("12.7", ac=2)
def test_at_its_expiry_a_hold_whose_event_is_not_confirmed_expires(db):
    """R5: it lapsed at its expiry, whenever the sweep ran, and the system closed it - with an
    audit entry that has no actor - but Venue Staff's approval stays on the record."""
    event, venue = _event(db), _venue(db)
    expiry = datetime(2026, 12, 4, 2, 0, tzinfo=UTC)  # Fri 4 Dec 2026, 10:00 in Singapore
    approved_at = datetime(2026, 11, 20, 2, 0, tzinfo=UTC)
    hold = _hold(db, event=event, venue=venue, expires_at=expiry, decided_at=approved_at)
    a_second_left = _hold(db, expires_at=expiry + timedelta(seconds=1))

    expired = service.expire_lapsed_holds(db, now=expiry + timedelta(seconds=0.5))

    assert hold.id in {each.id for each in expired}
    assert a_second_left.id not in {each.id for each in expired}
    row = _reloaded(db, hold)
    assert (row.status, row.decided_by_id, row.decided_at, row.hold_expires_at) == (
        BookingStatus.EXPIRED,
        Users.VENUE_STAFF.id,
        approved_at,
        expiry,
    )
    assert _reloaded(db, a_second_left).status == BookingStatus.APPROVED
    (audit,) = _audits(db, "BOOKING_EXPIRED", hold.id)
    assert audit.actor_id is None
    (told,) = _notifications(db, "BOOKING_HOLD_EXPIRED", hold.id)
    assert told.recipient_id == Users.COORDINATOR.id
    assert told.message == (
        f'The hold on {venue.name} for "{event.name}" expired on Fri 4 Dec 2026 at 10:00, before'
        " the event was confirmed, so the venue was released. Request a venue again if the event"
        " still needs one."
    )


@pytest.mark.story("12.7", ac=3)
def test_an_expired_booking_leaves_the_approved_tab(venue_staff_client, db):
    """Lapsed a second ago and not yet swept: the queue still never lists it as approved."""
    hold = _hold(db, expires_at=_in() - timedelta(seconds=1))

    approved = venue_staff_client.get(BOOKINGS_PATH, params={"status": "APPROVED"}).json()
    expired = venue_staff_client.get(BOOKINGS_PATH, params={"status": "EXPIRED"}).json()

    assert str(hold.id) not in {item["id"] for item in approved["items"]}
    (entry,) = [item for item in expired["items"] if item["id"] == str(hold.id)]
    assert entry["status"] == BookingStatus.EXPIRED
    assert (
        expired["counts"]["expired"]
        == expired["total"]
        == db.scalar(select(func.count()).where(VenueBooking.status == BookingStatus.EXPIRED))
    )


# --- AC3/AC11/AC6: the venue is free at once ------------------------------------------------
def _search_finds_it(client, venue: Venue, event: Event) -> None:
    result = client.get(
        "/venues/search",
        params={
            "search": venue.name,
            "starts_at": _at(15, 9).isoformat(),
            "ends_at": _at(15, 17).isoformat(),
        },
    ).json()
    assert [hit["id"] for hit in result["venues"]] == [str(venue.id)]


def _calendar_drops_it(client, venue: Venue, event: Event) -> None:
    assert _calendar(client, venue) == []


def _another_request_takes_it(client, venue: Venue, event: Event) -> None:
    _created(_raise(client, event, venue))


@pytest.mark.story("12.7", ac=3)
@pytest.mark.story("12.7", ac=11)
@pytest.mark.story("12.7", ac=6)
@pytest.mark.parametrize(
    "check",
    [_search_finds_it, _calendar_drops_it, _another_request_takes_it],
    ids=["search", "calendar", "request"],
)
def test_a_lapsed_hold_releases_its_venue_at_once(coordinator_client, db, check):
    """Lapsed a second ago, before any timer has swept it: the search finds the venue, its
    calendar shows nothing, and another event's request for the same period is accepted (12.1's
    conflict check no longer counts it). Each finds the old booking Expired."""
    venue = _venue(db)
    hold = _hold(db, venue=venue, expires_at=_in() - timedelta(seconds=1))

    check(coordinator_client, venue, _event(db))

    assert _reloaded(db, hold).status == BookingStatus.EXPIRED


@pytest.mark.story("12.7", ac=6)
def test_raising_a_request_expires_a_lapsed_hold_in_its_way_whoever_calls_it(db):
    """The rule is the service's own, not only its endpoint's: a lapsed hold left approved would
    still trip the database's no-double-booking constraint, so raising a request expires it
    first."""
    venue = _venue(db)
    hold = _hold(db, venue=venue, expires_at=_in() - timedelta(seconds=1))
    event = _event(db)
    chloe = db.get(User, Users.COORDINATOR.id)

    booking = service.create_booking_request(
        db, BookingRequestIn(event_id=event.id, venue_id=venue.id), actor=chloe
    )

    assert booking.status == BookingStatus.PENDING
    assert _reloaded(db, hold).status == BookingStatus.EXPIRED


# --- AC4: the event's confirmation completes the hold, up to its expiry ---------------------
@pytest.mark.story("12.7", ac=4)
def test_an_event_confirmed_a_minute_before_its_hold_expires_keeps_the_booking(
    coordinator_client, db
):
    """R4: completed when the event became Confirmed, the hold is never warned about or expired,
    even by a sweep long after its expiry, and the calendar shows a plain booking."""
    event, venue = _event(db), _venue(db)
    expiry = _in(minutes=1)
    hold = _hold(db, event=event, venue=venue, expires_at=expiry)

    _confirm(db, event)

    confirmed_at = db.scalar(select(func.now()))
    row = _reloaded(db, hold)
    assert (row.status, row.hold_completed_at) == (BookingStatus.APPROVED, confirmed_at)
    service.sweep_holds(db, now=_in())
    service.sweep_holds(db, now=expiry + timedelta(days=1))
    assert _reloaded(db, hold).status == BookingStatus.APPROVED
    assert _notifications(db, "BOOKING_HOLD_EXPIRING", hold.id) == []
    assert _notifications(db, "BOOKING_HOLD_EXPIRED", hold.id) == []
    (window,) = _calendar(coordinator_client, venue)
    assert (window["reason"], window["hold_expires_at"]) == ("BOOKED", None)


@pytest.mark.story("12.7", ac=4)
def test_an_event_confirmed_after_its_hold_lapsed_does_not_keep_it(db):
    """R4: lapsed an hour ago and not yet swept, the hold is not completed by the confirmation;
    the next sweep expires it, and 21.2's Confirm will find the booking lost (R15)."""
    event = _event(db)
    hold = _hold(db, event=event, expires_at=_in(hours=-1))

    _confirm(db, event)

    assert _reloaded(db, hold).hold_completed_at is None
    service.expire_lapsed_holds(db, now=_in())
    assert _reloaded(db, hold).status == BookingStatus.EXPIRED


@pytest.mark.story("12.7", ac=4)
def test_a_booking_approved_for_an_event_already_confirmed_is_held_for_good(venue_staff_client, db):
    """Review of #103 (Yu Bing, 12 Oct): an extra venue for an event already Confirmed has no
    confirmation left to wait for, and the trigger fires only as an event becomes Confirmed, so
    the approval completes the hold itself. The booking is never warned about or expired, even
    past the expiry Venue Staff gave, its expiry takes no change, and the approval notice
    promises no expiry."""
    event, venue = _event(db), _venue(db)
    event.status = EventStatus.CONFIRMED
    db.flush()
    request = _request(db, event=event, venue=venue)
    expiry = _in(hours=12)

    response = _approve(venue_staff_client, request.id, expiry)

    assert response.status_code == 200, response.text
    approved = response.json()
    assert approved["status"] == BookingStatus.APPROVED
    assert approved["hold_completed_at"] is not None
    service.sweep_holds(db, now=_in(hours=1))
    service.sweep_holds(db, now=expiry + timedelta(days=1))
    assert _reloaded(db, request).status == BookingStatus.APPROVED
    assert _notifications(db, "BOOKING_HOLD_EXPIRING", request.id) == []
    assert _notifications(db, "BOOKING_HOLD_EXPIRED", request.id) == []
    assert _change(venue_staff_client, request.id, _in(days=1)).status_code == 409
    (told,) = _notifications(db, "BOOKING_APPROVED", request.id)
    assert told.message == (
        f"Vera Venue approved the request for {venue.name} on Mon 15 Mar 2027 from 09:00 to 17:00."
    )


@pytest.mark.story("12.7", ac=4)
def test_confirming_an_event_completes_only_its_own_open_holds_for_good(db):
    """R4: not its pending request, its expired booking or its booking approved before holds
    expired, nor another event's hold. Sent back to Planning (9.4 AC3, 19.2 AC8), the event keeps
    its completed hold: a sweep past the old expiry leaves it booked."""
    event = _event(db)
    expiry = _in(days=2)
    open_hold = _hold(db, event=event, expires_at=expiry)
    pending = _request(db, event=event)
    expired = _hold(db, event=event, expires_at=_in(days=-2), status=BookingStatus.EXPIRED)
    legacy = _request(db, event=event, status=BookingStatus.APPROVED)
    other_events = _hold(db, expires_at=expiry)

    _confirm(db, event)

    completed = {
        booking.id
        for booking in (open_hold, pending, expired, legacy, other_events)
        if _reloaded(db, booking).hold_completed_at is not None
    }
    assert completed == {open_hold.id}
    db.get(Event, event.id).status = EventStatus.PLANNING
    db.flush()
    service.expire_lapsed_holds(db, now=expiry + timedelta(minutes=1))
    assert _reloaded(db, open_hold).status == BookingStatus.APPROVED
    assert _reloaded(db, other_events).status == BookingStatus.EXPIRED


# --- AC6: an expired booking covers no requirement -------------------------------------------
@pytest.mark.story("12.7", ac=6)
def test_an_expired_booking_does_not_cover_its_venue_requirement(coordinator_client, db):
    """12.5 AC10 allows one pending or approved request per requirement; an expired one is
    neither, so the requirement takes a new request - for the same venue, which it no longer
    holds."""
    event, venue = _event(db), _venue(db)
    requirement_id = make_venue_requirement(
        db, event.id, capacity=40, starts_at=_at(15, 9), ends_at=_at(15, 17)
    )
    _hold(
        db,
        event=event,
        venue=venue,
        expires_at=_in(days=-3),
        status=BookingStatus.EXPIRED,
        venue_requirement_id=requirement_id,
    )

    booking = _created(_raise(coordinator_client, event, venue, requirement_id))

    assert booking["venue_requirement_id"] == str(requirement_id)


# --- AC8: history ------------------------------------------------------------------------------
@pytest.mark.story("12.7", ac=8)
def test_expired_bookings_stay_in_the_events_booking_list(coordinator_client, db):
    """With when Venue Staff approved it and when its hold expired."""
    event = _event(db)
    expiry = _in() - timedelta(seconds=1)
    approved_at = _in(days=-2)
    hold = _hold(db, event=event, expires_at=expiry, decided_at=approved_at)

    (outcome,) = coordinator_client.get(f"{BOOKINGS_PATH}/for-event/{event.id}").json()

    assert outcome["id"] == str(hold.id)
    assert outcome["status"] == BookingStatus.EXPIRED
    assert (_moment(outcome["decided_at"]), _moment(outcome["hold_expires_at"])) == (
        approved_at,
        expiry,
    )


# --- AC10: the event's confirmation and the hold's expiry at the same moment -----------------
@pytest.mark.story("12.7", ac=10)
def test_a_confirmation_and_an_expiry_at_the_same_moment_land_once(engine):
    """Real concurrent transactions, so this test commits and cleans up after itself. The event is
    confirmed while the sweep runs at the hold's expiry: the trigger's update and the sweep take
    the booking's row lock, so one lands. Completed, the sweep expired nothing; expired, the
    confirmation completed nothing (R10)."""
    expiry = _in(hours=1)
    with Session(engine) as session:
        event, venue = _event(session), _venue(session)
        hold = _hold(session, event=event, venue=venue, expires_at=expiry)
        session.commit()
        hold_id, event_id, venue_id = hold.id, event.id, venue.id
    start = threading.Barrier(2)

    def confirm() -> None:
        with Session(engine) as session:
            start.wait()
            session.execute(
                update(Event).where(Event.id == event_id).values(status=EventStatus.CONFIRMED)
            )
            session.commit()

    def expire() -> list[uuid.UUID]:
        with Session(engine) as session:
            start.wait()
            return [each.id for each in service.expire_lapsed_holds(session, now=expiry)]

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            confirmation = pool.submit(confirm)
            sweep = pool.submit(expire)
            confirmation.result(timeout=30)
            expired = sweep.result(timeout=30)

        with Session(engine) as session:
            row = session.get(VenueBooking, hold_id)
            landed = (row.status, row.hold_completed_at is not None)
        if expired == [hold_id]:
            assert landed == (BookingStatus.EXPIRED, False)
        else:
            assert (expired, landed) == ([], (BookingStatus.APPROVED, True))
    finally:
        with Session(engine) as session:
            session.execute(delete(AuditLog).where(AuditLog.entity_id == hold_id))
            session.execute(delete(Notification).where(Notification.event_id == event_id))
            session.execute(delete(VenueBooking).where(VenueBooking.id == hold_id))
            session.execute(delete(Event).where(Event.id == event_id))
            session.execute(delete(Venue).where(Venue.id == venue_id))
            session.commit()


# --- migration 018 ---------------------------------------------------------------------------
@pytest.mark.story("12.7", ac=1)
def test_migration_018_gives_no_existing_booking_a_hold(db):
    """R12: the system sets no expiry, so a booking already approved stays a plain booking that
    never expires, and a pending one waits for Venue Staff as before. The trigger is installed:
    a hold approved after the migration is completed by its event's confirmation. Run on pre-018
    rows inside the test's transaction, which is rolled back."""
    conn = db.connection()
    conn.exec_driver_sql(PRE_018_SCHEMA)
    event = _event(db)

    def booking(status: str) -> uuid.UUID:
        """A pre-018 row, written in SQL since the model maps the columns 018 adds."""
        return db.execute(
            text(
                "INSERT INTO venue_bookings (event_id, venue_id, requested_by_id, starts_at,"
                " ends_at, expected_attendance, status) VALUES (:event_id, :venue_id, :actor,"
                " :starts_at, :ends_at, 10, :status) RETURNING id"
            ),
            {
                "event_id": event.id,
                "venue_id": _venue(db).id,
                "actor": Users.COORDINATOR.id,
                "starts_at": _at(15, 9),
                "ends_at": _at(15, 11),
                "status": status,
            },
        ).scalar_one()

    pending, approved = booking(BookingStatus.PENDING), booking(BookingStatus.APPROVED)

    conn.exec_driver_sql(MIGRATION_018.read_text(encoding="utf-8"))
    db.expire_all()

    for booking_id in (pending, approved):
        row = db.get(VenueBooking, booking_id)
        assert (
            row.hold_expires_at,
            row.hold_reminded_at,
            row.hold_completed_at,
            row.hold_expiry_change_reason,
            row.hold_expiry_changed_by_id,
            row.hold_expiry_changed_at,
        ) == (None, None, None, None, None, None)
    service.expire_lapsed_holds(db, now=_in(days=3650))
    assert db.get(VenueBooking, approved).status == BookingStatus.APPROVED
    hold = _hold(db, event=event, expires_at=_in(days=2))
    _confirm(db, event)
    assert _reloaded(db, hold).hold_completed_at is not None


# --- the timer -----------------------------------------------------------------------------------
@pytest.mark.story("12.7", ac=2)
@pytest.mark.story("12.7", ac=3)
def test_the_api_sweeps_lapsed_holds_on_a_timer_while_it_runs(monkeypatch):
    """Warnings and expiries go out on time with nobody using the app. The timer starts with the
    API and stops with it; each pass is counted here instead of touching a database."""
    passes: list[float] = []
    monkeypatch.setattr(main, "_sweep_holds_once", lambda: passes.append(time.monotonic()))
    monkeypatch.setattr(settings, "hold_sweep_interval_seconds", 0.01)

    with TestClient(main.app):
        deadline = time.monotonic() + 5
        while len(passes) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
    stopped_at = len(passes)
    time.sleep(0.1)

    assert stopped_at >= 3
    assert len(passes) == stopped_at


@pytest.mark.story("12.7", ac=3)
def test_an_unexpected_error_in_a_pass_is_logged_and_the_timer_carries_on(monkeypatch, caplog):
    """Review of #103 (Yu Bing, 12 Oct): an error that is not the database's - a notice that
    cannot be written, say - must not end the timer for the life of the process."""
    passes: list[float] = []

    def fails_once() -> None:
        passes.append(time.monotonic())
        if len(passes) == 1:
            raise RuntimeError("a notice could not be written")

    monkeypatch.setattr(main, "_sweep_holds_once", fails_once)
    monkeypatch.setattr(settings, "hold_sweep_interval_seconds", 0.01)

    with TestClient(main.app):
        deadline = time.monotonic() + 5
        while len(passes) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)

    assert len(passes) >= 3
    assert "The hold sweep failed" in caplog.text


@pytest.mark.story("12.7", ac=3)
def test_a_failed_sweep_is_logged_and_the_next_pass_still_runs(engine, monkeypatch, caplog):
    """A database that is briefly unreachable must not stop the timer: the pass is logged and
    left for the next one. Pointed at the test database, though it never reaches it."""

    def unreachable(db: Session, *, now: datetime) -> None:
        raise OperationalError("SELECT 1", {}, Exception("the database is restarting"))

    monkeypatch.setattr(main, "SessionLocal", lambda: Session(bind=engine))
    monkeypatch.setattr(service, "sweep_holds", unreachable)

    main._sweep_holds_once()

    assert "The hold sweep failed" in caplog.text
