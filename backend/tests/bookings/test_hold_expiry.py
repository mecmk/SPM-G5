"""Story 12.7 - expire tentative venue holds.

AC1  Every pending request's hold on its venue has an expiry: by default 7 days after the request
     is raised, never after its booked period starts. It is on the request, its queue entry, the
     event's booking list and the venue calendar, and Venue Staff can change it.
AC2  The event's coordinator is warned 24 hours before a hold expires, once, and told when it
     expires.
AC3  At its expiry an unapproved request becomes Expired: it leaves the pending queue, and its
     venue is free for that period at once - before any timer runs.
AC4  A hold approved a minute before its expiry is booked; from its expiry on it cannot be approved.
AC5  An expiry must be in the future and no later than the start of the booked period; a request
     whose booked period has already started cannot be held at all.
AC6  An expired request holds nothing and covers no venue requirement (12.5).
AC7  Venue Staff can extend a hold that has not expired, and the coordinator is told the new
     expiry; an expired one is never given a new one.
AC8  Expired requests stay in the event's booking list.
AC9  Only Venue Staff can change an expiry.
AC10 Of an approval and an expiry at the same moment, only the first lands.
AC11 An expired hold leaves the venue calendar and no longer keeps its venue out of a search.

Decided 12 Oct 2026 (constitution s12.7, Q12, Q17, Q26 to Q31): switching a hold past its expiry
(12.5) is refused as approving one is, a switched request gets the default expiry of any new
request, every change Venue Staff make to an expiry carries a reason - required, blank refused, kept
on the request with who made it and when, told to the coordinator and audited - and the seeded
holds expire at the start of their booked period.

Also migration 018, which gives the pending requests already in the database an expiry, and the
timer that sweeps lapsed holds while the API runs. The page flows are
tests/e2e/venue-hold-expiry.spec.ts.

Until the customer answers Q15 (constitution s12.7): Venue Staff's approval is the action a hold
waits for, the default is 7 days and the warning comes 24 hours before. ``shipped_hold_settings``
pins both, so a local .env cannot change what these tests mean.

Every case uses fresh venues and Planning events assigned to Chloe, held in March 2027, and
expiries a few days from now, so no seeded booking is held, warned or expired in the way.
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
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app import main
from app.auth.models import User
from app.bookings import service
from app.bookings.models import BookingStatus, VenueBooking
from app.bookings.schemas import BookingRequestIn, BookingSwitchIn
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
# The schema as it stood before migration 018: no expiry, and no EXPIRED status - so no expired
# request either, such as the one seeded for the e2e spec.
PRE_018_SCHEMA = (
    "DELETE FROM venue_bookings WHERE status = 'EXPIRED';"
    " ALTER TABLE venue_bookings DROP COLUMN hold_expires_at, DROP COLUMN hold_reminded_at,"
    " DROP COLUMN hold_expiry_change_reason, DROP COLUMN hold_expiry_changed_by_id,"
    " DROP COLUMN hold_expiry_changed_at;"
    " ALTER TABLE venue_bookings DROP CONSTRAINT ck_venue_bookings_status;"
    " ALTER TABLE venue_bookings ADD CONSTRAINT ck_venue_bookings_status CHECK"
    " (status IN ('PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN', 'CANCELLED'));"
)
# The reason every change of an expiry carries (Q27), unless a case leaves it out on purpose.
CHANGE_REASON = "The organiser asked for more time to confirm the layout."
# The seeded pending requests (Q17); the approved and expired ones have no hold to expire.
SEEDED_PENDING = [
    Bookings.PENDING_SEMINAR_ROOM,
    Bookings.PENDING_EXHIBITION_FOYER,
    Bookings.PENDING_GRAND_HALL,
    Bookings.PENDING_APPROVE_E2E_CARD,
    Bookings.PENDING_APPROVE_E2E_DETAIL,
    Bookings.PENDING_REJECT_E2E_CARD,
    Bookings.PENDING_REJECT_E2E_DETAIL,
]
NOT_PENDING_STATUSES = [
    BookingStatus.APPROVED,
    BookingStatus.REJECTED,
    BookingStatus.WITHDRAWN,
    BookingStatus.CANCELLED,
    BookingStatus.EXPIRED,
]


@pytest.fixture(autouse=True)
def shipped_hold_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The defaults this story ships with (decisions 2 and 3), whatever a local .env says."""
    monkeypatch.setattr(settings, "hold_expiry_default_hours", 168)
    monkeypatch.setattr(settings, "hold_expiry_reminder_hours", 24)


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    """A moment in March 2027, Singapore time."""
    return datetime(2027, 3, day, hour, minute, tzinfo=SGT)


def _in(days: float = 0, hours: float = 0) -> datetime:
    """A moment that far from now, to the second."""
    return datetime.now(UTC).replace(microsecond=0) + timedelta(days=days, hours=hours)


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


def _hold(
    db: Session,
    *,
    expires_at: datetime,
    event: Event | None = None,
    venue: Venue | None = None,
    status: str = BookingStatus.PENDING,
    **overrides,
) -> VenueBooking:
    """A request for 15 March 2027, 09:00-17:00, whose hold expires at ``expires_at``."""
    event = _event(db) if event is None else event
    venue = _venue(db) if venue is None else venue
    return make_booking(
        db,
        venue_id=venue.id,
        event_id=event.id,
        starts_at=overrides.pop("starts_at", _at(15, 9)),
        ends_at=overrides.pop("ends_at", _at(15, 17)),
        status=status,
        hold_expires_at=expires_at,
        **overrides,
    )


def _raise(client, event: Event, venue: Venue, requirement_id: uuid.UUID | None = None):
    body = {"event_id": str(event.id), "venue_id": str(venue.id)}
    if requirement_id is not None:
        body["venue_requirement_id"] = str(requirement_id)
    return client.post(BOOKINGS_PATH, json=body)


def _created(response) -> dict:
    assert response.status_code == 201, response.text
    return response.json()


def _change(client, booking_id: uuid.UUID, expires_at: Any, reason: Any = CHANGE_REASON):
    """Give a request's hold a new expiry, with a reason (Q27) unless ``reason`` is None."""
    value = expires_at.isoformat() if isinstance(expires_at, datetime) else expires_at
    body = {"hold_expires_at": value}
    if reason is not None:
        body["hold_expiry_change_reason"] = reason
    return client.patch(f"{BOOKINGS_PATH}/{booking_id}", json=body)


def _switch(client, booking_id: uuid.UUID, venue: Venue):
    """Switch a pending request to ``venue`` (story 12.5, decided 11 Oct 2026)."""
    return client.post(f"{BOOKINGS_PATH}/{booking_id}/switch", json={"venue_id": str(venue.id)})


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


# --- AC1: a default expiry, shown wherever the request is ---------------------------------------
@pytest.mark.story("12.7", ac=1)
def test_a_new_request_holds_its_venue_for_seven_days(login_as, db):
    """The same expiry on the request, its queue entry, the event's booking list and the held
    window on the venue's calendar."""
    event, venue = _event(db), _venue(db)
    coordinator = login_as(Users.COORDINATOR)
    raised_from = datetime.now(UTC)
    booking = _created(_raise(coordinator, event, venue))
    raised_by = datetime.now(UTC)

    expiry = _moment(booking["hold_expires_at"])
    assert raised_from + timedelta(days=7) <= expiry <= raised_by + timedelta(days=7)
    assert _moment(
        coordinator.get(f"{BOOKINGS_PATH}/{booking['id']}").json()["hold_expires_at"]
    ) == (expiry)
    (outcome,) = coordinator.get(f"{BOOKINGS_PATH}/for-event/{event.id}").json()
    assert _moment(outcome["hold_expires_at"]) == expiry
    (window,) = coordinator.get(
        f"/venues/{venue.id}/calendar",
        params={"starts_at": _at(15, 0).isoformat(), "ends_at": _at(16, 0).isoformat()},
    ).json()
    assert window["reason"] == "HELD"
    assert _moment(window["hold_expires_at"]) == expiry

    queue = login_as(Users.VENUE_STAFF).get(BOOKINGS_PATH, params={"status": "PENDING"}).json()
    (entry,) = [item for item in queue["items"] if item["id"] == booking["id"]]
    assert _moment(entry["hold_expires_at"]) == expiry


@pytest.mark.story("12.7", ac=1)
def test_the_default_comes_from_the_setting(coordinator_client, db, monkeypatch):
    """Q15 may change the 7 days: the default is the setting's, not a number in the code."""
    monkeypatch.setattr(settings, "hold_expiry_default_hours", 48)
    raised_from = datetime.now(UTC)

    booking = _created(_raise(coordinator_client, _event(db), _venue(db)))

    expiry = _moment(booking["hold_expires_at"])
    assert raised_from + timedelta(hours=48) <= expiry <= datetime.now(UTC) + timedelta(hours=48)


@pytest.mark.story("12.7", ac=1)
def test_an_approved_booking_shows_no_hold_on_the_calendar(coordinator_client, db):
    """Only a pending request is held; a confirmed booking has nothing left to expire."""
    venue = _venue(db)
    _hold(db, venue=venue, expires_at=_in(days=2), status=BookingStatus.APPROVED)

    (window,) = coordinator_client.get(
        f"/venues/{venue.id}/calendar",
        params={"starts_at": _at(15, 0).isoformat(), "ends_at": _at(16, 0).isoformat()},
    ).json()

    assert window["reason"] == "BOOKED"
    assert window["hold_expires_at"] is None


@pytest.mark.story("12.7", ac=1)
@pytest.mark.story("12.7", ac=5)
def test_the_default_never_outlasts_the_start_of_the_booked_period(coordinator_client, db):
    """A period starting two days from now: 7 days would be after it starts, so the hold expires
    as the booked period begins."""
    starts_at = _in(days=2)
    event = _event(db, starts_at=starts_at, ends_at=starts_at + timedelta(hours=3))

    booking = _created(_raise(coordinator_client, event, _venue(db)))

    assert _moment(booking["hold_expires_at"]) == starts_at == _moment(booking["held_from"])


@pytest.mark.story("12.7", ac=5)
def test_a_request_whose_booked_period_has_started_is_refused(coordinator_client, db):
    """No expiry can be both in the future and no later than a start already past."""
    starts_at = _in(hours=-1)
    event = _event(db, starts_at=starts_at, ends_at=starts_at + timedelta(hours=4))

    response = _raise(coordinator_client, event, _venue(db))

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This booked period has already started, so the venue cannot be held for it."
    )
    assert db.scalar(select(func.count()).where(VenueBooking.event_id == event.id)) == 0


@pytest.mark.story("12.7", ac=1)
@pytest.mark.story("12.7", ac=5)
def test_seeded_pending_requests_hold_their_venue_until_their_booked_period_starts(db):
    """Q17: a seeded hold expires at the start of its booked period, setup included - AC5's
    latest - so a development database that is not re-seeded keeps its sample requests pending.
    The one seeded expired request keeps the expiry it lapsed at."""
    seeded = db.scalars(select(VenueBooking).where(VenueBooking.id.in_(SEEDED_PENDING))).all()
    expired = db.get(VenueBooking, Bookings.EXPIRED_CRAFT_FAIR_FOYER)

    assert {row.status for row in seeded} == {BookingStatus.PENDING}
    assert [row.hold_expires_at for row in seeded] == [row.held_from for row in seeded]
    assert (expired.status, expired.hold_expires_at, expired.decided_at) == (
        BookingStatus.EXPIRED,
        datetime(2026, 10, 5, 10, 0, tzinfo=SGT),
        datetime(2026, 10, 5, 10, 0, tzinfo=SGT),
    )


# --- AC1/AC7: Venue Staff change the expiry; the coordinator is told -------------------------
@pytest.mark.story("12.7", ac=7)
@pytest.mark.story("12.7", ac=1)
def test_venue_staff_extend_a_hold_and_the_coordinator_is_told(login_as, db):
    """The coordinator told is whoever holds the event now (20.1 AC4) - Carl, since the hand-over.
    The expiry is written in Singapore time, as every event's times are. Q27/Q30: the change
    carries a reason, and the reason, who made the change and when are on the request, on the
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
    request = response.json()
    assert _moment(request["hold_expires_at"]) == extended
    assert request["hold_expiry_change_reason"] == CHANGE_REASON
    assert request["hold_expiry_changed_by"] == {
        "id": str(Users.VENUE_STAFF.id),
        "full_name": "Vera Venue",
    }
    assert changed_from <= _moment(request["hold_expiry_changed_at"]) <= changed_by
    assert _reloaded(db, hold).hold_expires_at == extended
    (outcome,) = login_as(Users.COORDINATOR_2).get(f"{BOOKINGS_PATH}/for-event/{event.id}").json()
    assert (
        outcome["hold_expires_at"],
        outcome["hold_expiry_change_reason"],
        outcome["hold_expiry_changed_by"],
        outcome["hold_expiry_changed_at"],
    ) == (
        request["hold_expires_at"],
        CHANGE_REASON,
        request["hold_expiry_changed_by"],
        request["hold_expiry_changed_at"],
    )
    (told,) = _notifications(db, "BOOKING_HOLD_EXPIRY_CHANGED", hold.id)
    assert told.recipient_id == Users.COORDINATOR_2.id
    assert told.event_id == event.id
    assert told.message == (
        f'Vera Venue changed when the hold on {venue.name} for "{event.name}" expires, to Mon 1'
        " Mar 2027 at 18:30. Venue Staff must approve the request by then. Reason: "
        f"{CHANGE_REASON}"
    )
    (audit,) = _audits(db, "BOOKING_HOLD_EXPIRY_CHANGED", hold.id)
    assert audit.actor_id == Users.VENUE_STAFF.id
    changed = audit.details["hold_expires_at"]
    assert (_moment(changed["from"]), _moment(changed["to"])) == (was, extended)
    assert audit.details["reason"] == CHANGE_REASON


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
def test_a_second_change_replaces_the_first_on_the_request_and_the_audit_log_keeps_both(
    venue_staff_client, db
):
    """Q30: the request shows its latest change; every change is in the audit log."""
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


@pytest.mark.story("12.7", ac=1)
def test_venue_staff_may_also_bring_a_hold_forward(venue_staff_client, db):
    """AC1 lets Venue Staff change it, not only extend it."""
    hold = _hold(db, expires_at=_in(days=5))
    sooner = _in(days=1)

    response = _change(venue_staff_client, hold.id, sooner)

    assert response.status_code == 200, response.text
    assert _reloaded(db, hold).hold_expires_at == sooner


# --- AC5: in the future, and no later than the booked start ---------------------------------
@pytest.mark.story("12.7", ac=5)
@pytest.mark.parametrize(
    ("new_expiry", "detail"),
    [
        (lambda: _in(hours=0) - timedelta(seconds=1), "The hold must expire in the future."),
        (
            lambda: _at(15, 9, 1),
            "The hold must expire by the start of the booked period, Mon 15 Mar 2027 at 09:00.",
        ),
    ],
    ids=["a second ago", "a minute after the booked start"],
)
def test_an_expiry_must_be_in_the_future_and_by_the_booked_start(
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
def test_an_expiry_exactly_at_the_booked_start_is_allowed(venue_staff_client, db):
    """The booked period starts at 08:30 here: 30 minutes of setup before the 09:00 event."""
    hold = _hold(db, expires_at=_in(days=2), setup_minutes=30)

    response = _change(venue_staff_client, hold.id, _at(15, 8, 30))

    assert response.status_code == 200, response.text
    assert _reloaded(db, hold).hold_expires_at == _at(15, 8, 30)


@pytest.mark.story("12.7", ac=5)
def test_an_expiry_without_a_time_zone_is_refused(venue_staff_client, db):
    """A wall-clock time names no moment until it names its zone."""
    was = _in(days=2)
    hold = _hold(db, expires_at=was)

    response = _change(venue_staff_client, hold.id, "2027-03-01T18:30:00")

    assert response.status_code == 422
    assert _reloaded(db, hold).hold_expires_at == was


# --- AC7: only a hold that has not expired takes a new expiry ------------------------------
@pytest.mark.story("12.7", ac=7)
@pytest.mark.parametrize("status", NOT_PENDING_STATUSES)
def test_a_request_that_is_no_longer_pending_takes_no_new_expiry(venue_staff_client, db, status):
    was = _in(days=2)
    hold = _hold(db, expires_at=was, status=status)

    response = _change(venue_staff_client, hold.id, _in(days=4))

    assert response.status_code == 409
    assert response.json()["detail"] == (
        f"This request is already {status}, so it cannot be given a new expiry."
    )
    assert _reloaded(db, hold).hold_expires_at == was


@pytest.mark.story("12.7", ac=7)
def test_a_lapsed_hold_cannot_be_revived(venue_staff_client, db):
    """Lapsed a second ago and not yet swept by any timer: it expires instead of being extended."""
    hold = _hold(db, expires_at=_in(hours=0) - timedelta(seconds=1))

    response = _change(venue_staff_client, hold.id, _in(days=4))

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This request is already EXPIRED, so it cannot be given a new expiry."
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

    with pytest.raises(service.BookingNotPending) as refusal:
        service.change_hold_expiry(
            db,
            booking,
            hold_expires_at=expiry + timedelta(days=2),
            reason=CHANGE_REASON,
            actor=staff,
            now=expiry,
        )

    assert str(refusal.value) == (
        "This request is already EXPIRED, so it cannot be given a new expiry."
    )
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
    moments, so they may warn seeded requests as well: only this one's warnings are counted."""
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
        f'The request for {venue.name} for "{event.name}" holds the venue until Fri 4 Dec 2026 at'
        " 10:00. If Venue Staff have not approved it by then, the hold expires and the venue is"
        " released."
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
def test_one_sweep_expires_lapsed_holds_and_warns_the_rest_without_warning_those(db):
    """A request already approved is never warned, nor is one whose hold has lapsed: that one is
    told it expired instead."""
    expiry = _in(days=3)
    approved = _hold(db, expires_at=expiry, status=BookingStatus.APPROVED)
    lapsed = _hold(db, expires_at=expiry - timedelta(hours=2))
    due = _hold(db, expires_at=expiry + timedelta(hours=2))

    service.sweep_holds(db, now=expiry - timedelta(hours=1))

    assert _notifications(db, "BOOKING_HOLD_EXPIRING", approved.id) == []
    assert _notifications(db, "BOOKING_HOLD_EXPIRING", lapsed.id) == []
    assert len(_notifications(db, "BOOKING_HOLD_EXPIRED", lapsed.id)) == 1
    assert len(_notifications(db, "BOOKING_HOLD_EXPIRING", due.id)) == 1


@pytest.mark.story("12.7", ac=2)
@pytest.mark.story("12.7", ac=7)
def test_a_new_expiry_inside_the_last_day_is_its_own_warning(venue_staff_client, db):
    """The change notice already names the expiry, so no second warning follows it."""
    hold = _hold(db, expires_at=_in(days=3))
    soon = _in(hours=12)

    assert _change(venue_staff_client, hold.id, soon).status_code == 200
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


# --- AC3: at its expiry the request becomes Expired, and the coordinator is told -------------
@pytest.mark.story("12.7", ac=3)
@pytest.mark.story("12.7", ac=2)
def test_at_its_expiry_an_unapproved_request_expires(db):
    """It closed when its hold lapsed, whenever the sweep ran, and the system closed it: no
    decider, no reason, and an audit entry with no actor."""
    event, venue = _event(db), _venue(db)
    expiry = datetime(2026, 12, 4, 2, 0, tzinfo=UTC)  # Fri 4 Dec 2026, 10:00 in Singapore
    hold = _hold(db, event=event, venue=venue, expires_at=expiry)
    a_second_left = _hold(db, expires_at=expiry + timedelta(seconds=1))

    expired = service.expire_lapsed_holds(db, now=expiry + timedelta(seconds=0.5))

    assert hold.id in {each.id for each in expired}
    assert a_second_left.id not in {each.id for each in expired}
    row = _reloaded(db, hold)
    assert (row.status, row.decided_at, row.decided_by_id, row.decision_reason) == (
        BookingStatus.EXPIRED,
        expiry,
        None,
        None,
    )
    assert _reloaded(db, a_second_left).status == BookingStatus.PENDING
    (audit,) = _audits(db, "BOOKING_EXPIRED", hold.id)
    assert audit.actor_id is None
    (told,) = _notifications(db, "BOOKING_HOLD_EXPIRED", hold.id)
    assert told.recipient_id == Users.COORDINATOR.id
    assert told.message == (
        f'Venue Staff did not approve the request for {venue.name} for "{event.name}" by Fri 4'
        " Dec 2026 at 10:00, so its hold expired and the venue was released. Request a venue"
        " again if the event still needs one."
    )


@pytest.mark.story("12.7", ac=3)
def test_an_expired_request_leaves_the_pending_queue(venue_staff_client, db):
    """Lapsed a second ago and not yet swept: the queue still never lists it as pending."""
    hold = _hold(db, expires_at=_in(hours=0) - timedelta(seconds=1))

    pending = venue_staff_client.get(BOOKINGS_PATH, params={"status": "PENDING"}).json()
    expired = venue_staff_client.get(BOOKINGS_PATH, params={"status": "EXPIRED"}).json()

    assert str(hold.id) not in {item["id"] for item in pending["items"]}
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
    response = client.get(
        f"/venues/{venue.id}/calendar",
        params={"starts_at": _at(15, 0).isoformat(), "ends_at": _at(16, 0).isoformat()},
    )
    assert response.status_code == 200
    assert response.json() == []


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
    conflict check no longer counts it). Each finds the old request Expired."""
    venue = _venue(db)
    hold = _hold(db, venue=venue, expires_at=_in(hours=0) - timedelta(seconds=1))

    check(coordinator_client, venue, _event(db))

    assert _reloaded(db, hold).status == BookingStatus.EXPIRED


@pytest.mark.story("12.7", ac=6)
def test_raising_a_request_expires_a_lapsed_hold_in_its_way_whoever_calls_it(db):
    """The rule is the service's own, not only its endpoint's: a lapsed hold left pending would
    still trip the database's no-double-booking constraint, so raising a request expires it
    first."""
    venue = _venue(db)
    hold = _hold(db, venue=venue, expires_at=_in(hours=0) - timedelta(seconds=1))
    event = _event(db)
    chloe = db.get(User, Users.COORDINATOR.id)

    booking = service.create_booking_request(
        db, BookingRequestIn(event_id=event.id, venue_id=venue.id), actor=chloe
    )

    assert booking.status == BookingStatus.PENDING
    assert _reloaded(db, hold).status == BookingStatus.EXPIRED


# --- AC4: approved up to its expiry, never after ---------------------------------------------
@pytest.mark.story("12.7", ac=4)
def test_a_hold_approved_a_minute_before_it_expires_is_booked(venue_staff_client, db):
    hold = _hold(db, expires_at=_in(hours=0) + timedelta(minutes=1))

    response = venue_staff_client.post(f"{BOOKINGS_PATH}/{hold.id}/approve")

    assert response.status_code == 200, response.text
    assert _reloaded(db, hold).status == BookingStatus.APPROVED


@pytest.mark.story("12.7", ac=4)
@pytest.mark.parametrize(
    ("approved_at", "status"),
    [
        (-timedelta(minutes=1), BookingStatus.APPROVED),
        (timedelta(0), BookingStatus.EXPIRED),
        (timedelta(seconds=1), BookingStatus.EXPIRED),
    ],
    ids=["a minute before", "at the expiry", "a second after"],
)
def test_from_its_expiry_a_hold_can_no_longer_be_approved(db, approved_at, status):
    """On the clock the action reads, so the boundary is exact: refused from the expiry on, and
    the request is expired there and then rather than left pending."""
    expiry = _in(days=3)
    hold = _hold(db, expires_at=expiry)
    booking = service.get_booking_for_decision(db, hold.id)

    if status == BookingStatus.APPROVED:
        service.approve_booking(
            db, booking, actor_id=Users.VENUE_STAFF.id, now=expiry + approved_at
        )
    else:
        with pytest.raises(service.BookingNotPending) as refusal:
            service.approve_booking(
                db, booking, actor_id=Users.VENUE_STAFF.id, now=expiry + approved_at
            )
        assert str(refusal.value) == "This request is already EXPIRED, so it cannot be approved."
        assert len(_notifications(db, "BOOKING_HOLD_EXPIRED", hold.id)) == 1

    assert _reloaded(db, hold).status == status


@pytest.mark.story("12.7", ac=4)
@pytest.mark.story("12.7", ac=10)
def test_approving_a_lapsed_hold_is_refused_naming_its_status(venue_staff_client, db):
    hold = _hold(db, expires_at=_in(hours=0) - timedelta(seconds=1))

    response = venue_staff_client.post(f"{BOOKINGS_PATH}/{hold.id}/approve")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This request is already EXPIRED, so it cannot be approved."
    )


@pytest.mark.story("12.7", ac=3)
@pytest.mark.story("12.7", ac=10)
@pytest.mark.parametrize(
    ("user", "action", "body", "detail"),
    [
        (
            Users.VENUE_STAFF,
            "reject",
            lambda db: {"decision_reason": "The room is double-booked."},
            "This request is already EXPIRED, so it cannot be rejected.",
        ),
        (
            Users.COORDINATOR,
            "withdraw",
            lambda db: None,
            "This request is already EXPIRED, so it cannot be withdrawn.",
        ),
        (
            Users.COORDINATOR,
            "switch",
            lambda db: {"venue_id": str(_venue(db).id)},
            "This request is already EXPIRED, so it cannot be switched.",
        ),
    ],
    ids=["reject", "withdraw", "switch"],
)
def test_a_lapsed_hold_cannot_be_rejected_withdrawn_or_switched(
    login_as, db, user, action, body, detail
):
    """Q12: a switch (12.5) of a lapsed hold is refused as a rejection or withdrawal is, showing
    it Expired, and nothing is requested in its place."""
    hold = _hold(db, expires_at=_in(hours=0) - timedelta(seconds=1))

    response = login_as(user).post(f"{BOOKINGS_PATH}/{hold.id}/{action}", json=body(db))

    assert response.status_code == 409
    assert response.json()["detail"] == detail
    assert _reloaded(db, hold).status == BookingStatus.EXPIRED
    assert db.scalar(select(func.count()).where(VenueBooking.event_id == hold.event_id)) == 1


@pytest.mark.story("12.7", ac=7)
@pytest.mark.story("12.7", ac=10)
def test_a_hold_lapsing_as_it_is_switched_expires_instead(db):
    """Q12, on the clock the switch reads: a hold that lapses between the sweep and the row lock
    is expired there and then - never switched, so nothing is requested in its place."""
    expiry = _in(days=3)
    hold = _hold(db, expires_at=expiry)
    replaced = service.get_booking_for_decision(db, hold.id)
    chloe = db.get(User, Users.COORDINATOR.id)
    target = _venue(db)

    with pytest.raises(service.BookingNotPending) as refusal:
        service.switch_booking_request(
            db, replaced, BookingSwitchIn(venue_id=target.id), actor=chloe, now=expiry
        )

    assert str(refusal.value) == "This request is already EXPIRED, so it cannot be switched."
    row = _reloaded(db, hold)
    assert (row.status, row.hold_expires_at) == (BookingStatus.EXPIRED, expiry)
    assert db.scalar(select(func.count()).where(VenueBooking.venue_id == target.id)) == 0


# --- Q26: a switched request is a new request, hold and all -----------------------------------
@pytest.mark.story("12.7", ac=1)
@pytest.mark.story("12.7", ac=5)
@pytest.mark.parametrize("starts_in_days", [None, 2], ids=["a week", "the booked start"])
def test_a_switched_request_gets_a_fresh_default_hold(coordinator_client, db, starts_in_days):
    """Q26: the request a switch makes gets the default expiry, counted from the switch rather
    than carried over from the old hold, and never after its booked period starts. Pinned, not
    driven: on main the request and the switch share ``_request_venue``, so the rebase gave the
    switch this before the test did; the test keeps it."""
    if starts_in_days is None:
        event = _event(db)
    else:
        starts_at = _in(days=starts_in_days)
        event = _event(db, starts_at=starts_at, ends_at=starts_at + timedelta(hours=3))
    hold = _hold(db, event=event, expires_at=_in(days=1))
    switched_from = datetime.now(UTC)

    response = _switch(coordinator_client, hold.id, _venue(db))

    assert response.status_code == 201, response.text
    expiry = _moment(response.json()["hold_expires_at"])
    if starts_in_days is None:
        assert switched_from + timedelta(days=7) <= expiry <= datetime.now(UTC) + timedelta(days=7)
    else:
        assert expiry == event.starts_at
    assert _reloaded(db, hold).status == BookingStatus.WITHDRAWN


@pytest.mark.story("12.7", ac=5)
def test_a_switch_for_a_booked_period_that_has_started_is_refused(coordinator_client, db):
    """Q26 with Q8: the new request takes the requirement's period as it stands now, and one that
    has started cannot be held, so the switch is refused and the old request stays pending. The
    old hold is still unexpired because the requirement's period moved after it was raised.
    Pinned, not driven, as above."""
    event = _event(db)
    requirement_id = make_venue_requirement(
        db, event.id, capacity=40, starts_at=_in(hours=-1), ends_at=_in(hours=3)
    )
    hold = _hold(db, event=event, expires_at=_in(days=2), venue_requirement_id=requirement_id)

    response = _switch(coordinator_client, hold.id, _venue(db))

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This booked period has already started, so the venue cannot be held for it."
    )
    assert _reloaded(db, hold).status == BookingStatus.PENDING


# --- AC6: an expired request covers no requirement -------------------------------------------
@pytest.mark.story("12.7", ac=6)
def test_an_expired_request_does_not_cover_its_venue_requirement(coordinator_client, db):
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
def test_expired_requests_stay_in_the_events_booking_list(coordinator_client, db):
    event = _event(db)
    expiry = _in(hours=0) - timedelta(seconds=1)
    hold = _hold(db, event=event, expires_at=expiry)

    (outcome,) = coordinator_client.get(f"{BOOKINGS_PATH}/for-event/{event.id}").json()

    assert outcome["id"] == str(hold.id)
    assert outcome["status"] == BookingStatus.EXPIRED
    assert _moment(outcome["hold_expires_at"]) == _moment(outcome["decided_at"]) == expiry


# --- AC10: approval and expiry at the same moment ----------------------------------------------
@pytest.mark.story("12.7", ac=10)
def test_an_approval_and_an_expiry_at_the_same_moment_land_once(engine):
    """Real concurrent transactions, so this test commits and cleans up after itself. Venue Staff
    approve a second before the expiry while the sweep runs at it: the row lock lets one through.
    Approved, the sweep expired nothing; expired, the approval was refused naming EXPIRED."""
    expiry = _in(hours=1)
    with Session(engine) as session:
        venue = _venue(session)
        hold = _hold(session, venue=venue, expires_at=expiry)
        session.commit()
        hold_id, event_id, venue_id = hold.id, hold.event_id, venue.id
    start = threading.Barrier(2)

    def approve() -> str:
        with Session(engine) as session:
            start.wait()
            booking = service.get_booking_for_decision(session, hold_id)
            try:
                service.approve_booking(
                    session,
                    booking,
                    actor_id=Users.VENUE_STAFF.id,
                    now=expiry - timedelta(seconds=1),
                )
            except service.BookingNotPending as refusal:
                return str(refusal)
            return "approved"

    def expire() -> list[uuid.UUID]:
        with Session(engine) as session:
            start.wait()
            return [each.id for each in service.expire_lapsed_holds(session, now=expiry)]

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            approval = pool.submit(approve)
            sweep = pool.submit(expire)
            approved, expired = approval.result(timeout=30), sweep.result(timeout=30)

        with Session(engine) as session:
            status = session.get(VenueBooking, hold_id).status
        if approved == "approved":
            assert (expired, status) == ([], BookingStatus.APPROVED)
        else:
            assert approved == "This request is already EXPIRED, so it cannot be approved."
            assert (expired, status) == ([hold_id], BookingStatus.EXPIRED)
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
def test_migration_018_gives_each_pending_request_an_expiry(db):
    """Requests already pending get the default from the migration onwards, never past their
    booked start; one whose period has started expires at the first sweep. Decided ones get none.
    Run on pre-018 rows inside the test's transaction, which is rolled back."""
    conn = db.connection()
    conn.exec_driver_sql(PRE_018_SCHEMA)
    event, venue = _event(db), _venue(db)
    migrated_at = db.scalar(text("SELECT now()"))

    def booking(starts_at: datetime, status: str = BookingStatus.PENDING) -> uuid.UUID:
        """A pre-018 row, written in SQL since the model maps the columns 018 adds."""
        return db.execute(
            text(
                "INSERT INTO venue_bookings (event_id, venue_id, requested_by_id, starts_at,"
                " ends_at, expected_attendance, status) VALUES (:event_id, :venue_id, :actor,"
                " :starts_at, :ends_at, 10, :status) RETURNING id"
            ),
            {
                "event_id": event.id,
                "venue_id": venue.id,
                "actor": Users.COORDINATOR.id,
                "starts_at": starts_at,
                "ends_at": starts_at + timedelta(hours=2),
                "status": status,
            },
        ).scalar_one()

    far_off = booking(_at(15, 9))
    in_two_days = booking(_in(days=2))
    started = booking(_in(days=-1))
    approved = booking(_at(16, 9), BookingStatus.APPROVED)

    conn.exec_driver_sql(MIGRATION_018.read_text(encoding="utf-8"))
    db.expire_all()

    def expiry_of(booking_id: uuid.UUID) -> datetime | None:
        return db.get(VenueBooking, booking_id).hold_expires_at

    assert expiry_of(far_off) == migrated_at + timedelta(days=7)
    assert expiry_of(in_two_days) == db.get(VenueBooking, in_two_days).held_from
    assert expiry_of(started) == db.get(VenueBooking, started).held_from
    assert expiry_of(approved) is None
    # Q31: no change has been made to any of them yet.
    migrated = db.get(VenueBooking, far_off)
    assert (
        migrated.hold_expiry_change_reason,
        migrated.hold_expiry_changed_by_id,
        migrated.hold_expiry_changed_at,
    ) == (None, None, None)


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
def test_a_failed_sweep_is_logged_and_the_next_pass_still_runs(engine, monkeypatch, caplog):
    """A database that is briefly unreachable must not stop the timer: the pass is logged and
    left for the next one. Pointed at the test database, though it never reaches it."""

    def unreachable(db: Session, *, now: datetime) -> None:
        raise OperationalError("SELECT 1", {}, Exception("the database is restarting"))

    monkeypatch.setattr(main, "SessionLocal", lambda: Session(bind=engine))
    monkeypatch.setattr(service, "sweep_holds", unreachable)

    main._sweep_holds_once()

    assert "The hold sweep failed" in caplog.text
