"""Story 9.5 - end the bookings a venue closure covers. The backlog's ACs, as written:

Happy path
1. Before saving a closure (9.4 AC1), Venue Staff see every pending request and approved booking
    whose occupied period (setup and turnaround included) overlaps the part of the closure still
    to come, a booking already under way included, and are told that saving rejects each pending
    request and cancels each approved booking. Saving needs their confirmation; closing the
    confirmation saves nothing. Extending a closure, or moving its end later, shows the same
    preview and confirmation for each booking it newly covers (extends 9.4 AC2).
2. Saving rejects each affected pending request and cancels each affected approved booking in the
    same step, with the closure's reason and description, who saved it and when. A cancelled
    booking is released through the shared release path with the cause VENUE_UNAVAILABLE (21.3),
    and shows on the event's booking list and in the Venue Staff queue's Cancelled tab as
    cancelled because the venue closed, with the reason; a rejected request shows in the Rejected
    tab with the same reason. The venue's other bookings, and the event's other venue bookings and
    equipment, do not change (replaces 9.4 AC3's mark).
3. Each venue requirement that lost its booking shows "Needs a venue" again (12.5). Only a
    cancelled approved booking sends an event that is Awaiting Safety Check or Confirmed back to
    Planning, so its safety check (21.2) is done again before it is confirmed again, as 12.8 AC5;
    a rejected pending request does not, since the event never relied on it. An event in Planning
    stays in Planning, and the event itself is never cancelled (replaces 9.4 AC3's status rule).
4. The assigned coordinator and the organiser of each affected event are notified (20.1) with the
    venue, the period, the reason, and which bookings were cancelled or requests rejected; the
    coordinator's notice also carries the description. The other Venue Staff are notified of each
    booking ended, but not the member who saved the closure (20.1 AC3, as 21.3 AC4). The Safety
    Officers are notified when an event goes back to Planning (as 12.8 AC5). Technical Support
    and registered attendees are not notified (Q61) (replaces 9.4 AC4).

Boundary
5. Only the part of a closure still to come counts: a booking that ends before it, or one whose
    period only touches it, is not affected (as 9.4 AC5, AC8), and bookings of events already
    completed or cancelled are not touched.

Edge
6. Shortening, ending early or removing a closure restores nothing: a rejected request or
    cancelled booking stays as it is, and the coordinator raises a new request. A rejected
    request or cancelled booking cannot be approved again, and a new request that overlaps a
    closure is refused (12.1 AC14) (replaces 9.4 AC6's clearing of marks).
7. Nothing is marked "Venue unavailable – alternative needed" any more. The mark, "Find a
    replacement venue" and "Find another venue" (12.6), the coordinator's "Venue unavailable" tab
    (12.6 AC11), the checks for a marked booking or a pending replacement on the safety review
    and Confirm (21.2 AC22, 12.6 AC12), and 12.8's marked and pending-replacement checks are
    removed. A booking already replaced keeps showing "Replaced by <venue>".
8. Bookings still marked when this ships are closed in one migration, with no notices: pending
    ones are rejected and approved ones cancelled with the cause VENUE_UNAVAILABLE. Their events
    are already in Planning (9.4 AC3, 21.2 AC22). A pending replacement of such a booking stays
    as a normal pending request for its requirement, and approving it later leaves the cancelled
    original as it is. The seed matches.

Permission
9. Only Venue Staff save closures (9.4 AC9). Nobody can undo a rejection or cancellation a
    closure made, and the API refuses anyone else.

Conflict
10. If a booking is approved, withdrawn, or its hold expires at the moment a closure is saved,
    whichever is saved first wins: a booking approved first is still cancelled, one withdrawn or
    expired first is left as it is, and nothing is rejected, cancelled or notified twice. A
    request raised at that same instant that is missed still cannot be approved while the
    closure stands (9.4 AC7) (replaces 9.4 AC10).
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings import service as booking_service
from app.bookings.models import VenueBooking
from app.common.audit import AuditLog
from app.events import service as events_service
from app.events.models import Event, EventStatus, EventStatusHistory
from app.notifications.models import Notification
from app.notifications.service import NotificationType
from app.venues import service as venue_service
from app.venues.models import Venue, VenueUnavailabilityPeriod
from app.venues.schemas import VenueUnavailabilityCreate, VenueUnavailabilityUpdate
from tests.support.factories import (
    approval_payload,
    make_booking,
    make_event,
    make_unavailability,
    make_venue,
)
from tests.support.seed import Users

SGT = timezone(timedelta(hours=8))


STAFF_ID = Users.VENUE_STAFF.id


def _days_from_now(days: float) -> datetime:
    """A moment that far from now, to the second - used only where the case is days away from
    any boundary, so the clock cannot change its answer."""
    return datetime.now(UTC).replace(microsecond=0) + timedelta(days=days)


def _url(venue_id: uuid.UUID, period_id: uuid.UUID | None = None) -> str:
    base = f"/venues/{venue_id}/unavailability"
    return base if period_id is None else f"{base}/{period_id}"


def _preview_url(venue_id: uuid.UUID) -> str:
    return f"/venues/{venue_id}/unavailability/affected-bookings"


def _body(starts_at: datetime, ends_at: datetime, **overrides) -> dict:
    body = {
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "reason": "MAINTENANCE",
        "description": "Scheduled servicing",
    }
    body.update(overrides)
    return body


def _future_body(**overrides) -> dict:
    """A period two days long that starts 10 days from now: not started, whatever the clock."""
    return _body(_days_from_now(10), _days_from_now(12), **overrides)


def _periods(db: Session, venue_id: uuid.UUID) -> list[VenueUnavailabilityPeriod]:
    db.expire_all()
    return list(
        db.scalars(
            select(VenueUnavailabilityPeriod).where(VenueUnavailabilityPeriod.venue_id == venue_id)
        )
    )


def _audit(db: Session, action: str, entity_id: uuid.UUID) -> list[AuditLog]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditLog).where(AuditLog.action == action, AuditLog.entity_id == entity_id)
        )
    )


def _staff(db: Session) -> User:
    return db.get(User, STAFF_ID)


def _period(
    db: Session, venue_id: uuid.UUID, starts_at: datetime, ends_at: datetime, **overrides
) -> VenueUnavailabilityPeriod:
    return make_unavailability(
        db, venue_id=venue_id, starts_at=starts_at, ends_at=ends_at, **overrides
    )


def _booking(db: Session, venue_id: uuid.UUID, starts_at: datetime, ends_at: datetime, **kwargs):
    """A booking of a Planning event of its own, so two never share an event."""
    event_status = kwargs.pop("event_status", EventStatus.PLANNING)
    event = make_event(
        db,
        status=event_status,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    return make_booking(
        db, venue_id=venue_id, starts_at=starts_at, ends_at=ends_at, event_id=event.id, **kwargs
    )


def _preview(client, venue_id: uuid.UUID, starts_at: datetime, ends_at: datetime, **extra):
    return client.get(
        _preview_url(venue_id),
        params={"starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat(), **extra},
    )


def _ids(response) -> set[str]:
    assert response.status_code == 200, response.text
    return {entry["booking_id"] for entry in response.json()}


def _write(client, method: str, venue_id: uuid.UUID, period_id: uuid.UUID):
    if method == "post":
        return client.post(_url(venue_id), json=_future_body())
    if method == "patch":
        return client.patch(_url(venue_id, period_id), json={"description": "x"})
    return client.delete(_url(venue_id, period_id))


MARKED = "BOOKING_VENUE_UNAVAILABLE_MARKED"


CLEARED = "BOOKING_VENUE_UNAVAILABLE_CLEARED"


def _day(days: float, hour: int = 10) -> datetime:
    """``hour`` o'clock UTC, that many days from now: a start well clear of the clock."""
    return (datetime.now(UTC) + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )


def _mark_in_sql(db: Session, booking_id: uuid.UUID, at: datetime) -> None:
    """A mark written in SQL, so it is stored exactly as given whatever the models say."""
    db.execute(
        text("UPDATE venue_bookings SET venue_unavailable_marked_at = :at WHERE id = :id"),
        {"at": at, "id": booking_id},
    )


def _marked_at(db: Session, booking_id: uuid.UUID) -> datetime | None:
    db.expire_all()
    return db.get(VenueBooking, booking_id).venue_unavailable_marked_at


def _live(
    db: Session,
    venue_id: uuid.UUID,
    starts_at: datetime,
    hours: float = 2,
    **kwargs,
) -> VenueBooking:
    """A pending booking of a Planning event of its own, ``hours`` long."""
    return _booking(
        db, venue_id, starts_at, starts_at + timedelta(hours=hours), status="PENDING", **kwargs
    )


def _add(client, venue_id: uuid.UUID, starts_at: datetime, ends_at: datetime, **overrides):
    response = client.post(_url(venue_id), json=_body(starts_at, ends_at, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


VENUE_UNAVAILABLE = "BOOKING_VENUE_UNAVAILABLE"


RETURNED_TO_PLANNING = "EVENT_RETURNED_TO_PLANNING"


def _event_for(db: Session, status: str = EventStatus.PLANNING, **overrides) -> Event:
    """An event with the seed coordinator and organiser, unless overridden."""
    overrides.setdefault("assigned_coordinator_id", Users.COORDINATOR.id)
    return make_event(db, status=status, **overrides)


def _pending_of(
    db: Session, event: Event, venue_id: uuid.UUID, starts_at: datetime, **kwargs
) -> VenueBooking:
    return make_booking(
        db,
        venue_id=venue_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        event_id=event.id,
        **kwargs,
    )


def _told(db: Session, event_id: uuid.UUID) -> list[Notification]:
    db.expire_all()
    return list(
        db.scalars(
            select(Notification)
            .where(
                Notification.notification_type == VENUE_UNAVAILABLE,
                Notification.event_id == event_id,
            )
            .order_by(Notification.created_at, Notification.id)
        )
    )


def _recipients(notices: list[Notification]) -> list[uuid.UUID]:
    return sorted(notice.recipient_id for notice in notices)


def _status_of(db: Session, event_id: uuid.UUID) -> str:
    db.expire_all()
    return db.get(Event, event_id).status


def _history(db: Session, event_id: uuid.UUID) -> list[EventStatusHistory]:
    db.expire_all()
    return list(
        db.scalars(
            select(EventStatusHistory)
            .where(EventStatusHistory.event_id == event_id)
            .order_by(EventStatusHistory.changed_at, EventStatusHistory.id)
        )
    )


def _returned(db: Session, event_id: uuid.UUID) -> list[EventStatusHistory]:
    return [
        row
        for row in _history(db, event_id)
        if (row.from_status, row.to_status) == (EventStatus.CONFIRMED, EventStatus.PLANNING)
    ]


def _on_singapore_date(moment: datetime) -> str:
    """The date as a notice words it: ``4 Mar 2027``, in Singapore time."""
    local = moment.astimezone(SGT)
    return f"{local.day} {local:%b %Y}"


LOCK_WAIT_SECONDS = 20


def _approve(client, booking_id: uuid.UUID, **overrides):
    return client.post(f"/bookings/{booking_id}/approve", json=approval_payload(**overrides))


def _stored(db: Session, booking_id: uuid.UUID) -> VenueBooking:
    db.expire_all()
    return db.get(VenueBooking, booking_id)


def _backend_pid(session: Session) -> int:
    return session.connection().exec_driver_sql("SELECT pg_backend_pid()").scalar()


def _is_waiting_on_a_lock(engine, pid: int) -> bool:
    with engine.connect() as watcher:
        waiting_on = watcher.execute(
            text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"), {"pid": pid}
        ).scalar()
        watcher.rollback()  # pg_stat_activity is a per-transaction snapshot
    return waiting_on == "Lock"


def _wait_until(engine, pids: dict[str, int], name: str) -> None:
    """Block until the connection ``name`` stands waiting on a row lock another holds."""
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while time.monotonic() < deadline:
        if name in pids and _is_waiting_on_a_lock(engine, pids[name]):
            return
        time.sleep(0.05)
    raise AssertionError(f"{name} never waited on the booking's lock")


def _committed_pending_request(engine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A venue, and a pending request of a Planning event for it three days away, committed."""
    with Session(engine) as session:
        venue = make_venue(session)
        event = _event_for(session)
        booking = _pending_of(session, event, venue.id, _day(3))
        session.commit()
        return venue.id, event.id, booking.id


def _remove_race_rows(engine, venue_id, event_id, booking_id) -> None:
    with Session(engine) as session:
        session.execute(
            delete(AuditLog).where(
                AuditLog.entity_id.in_([booking_id, event_id])
                | (AuditLog.details["venue_id"].astext == str(venue_id))
            )
        )
        session.execute(delete(Notification).where(Notification.event_id == event_id))
        session.execute(delete(VenueBooking).where(VenueBooking.id == booking_id))
        session.execute(delete(Event).where(Event.id == event_id))
        session.execute(delete(Venue).where(Venue.id == venue_id))
        session.commit()


def _save_period(session: Session, venue_id: uuid.UUID):
    """The save, in the two steps whose lock a race needs held between them: the period, then the
    re-check that marks and so locks the venue's bookings. The caller commits."""
    session.add(
        VenueUnavailabilityPeriod(
            venue_id=venue_id,
            starts_at=_day(2),
            ends_at=_day(7),
            reason="MAINTENANCE",
            notes="Servicing",
            created_by_id=STAFF_ID,
        )
    )
    session.flush()
    return venue_service.recheck_venue_bookings(
        session, venue_id, now=datetime.now(UTC), actor=session.get(User, STAFF_ID)
    )


def _unmarked_booking_under_a_period(
    db: Session, venue_id: uuid.UUID, status=EventStatus.CONFIRMED
):
    """A booking in 3 days of an event with the given status, and a period over it written
    straight to the table, so the booking is overlapped and not marked: the state a request that
    slipped in during a save leaves, which the next change to the venue's periods settles."""
    event = _event_for(db, status)
    booking = _pending_of(db, event, venue_id, _day(3))
    over = _period(db, venue_id, _day(2), _day(7), notes="Wiring")
    assert _marked_at(db, booking.id) is None
    return event, booking, over


@pytest.mark.story("9.4", ac=2)
def test_a_period_may_be_saved_with_bookings_in_the_way(db, venue_staff_client):
    """AC2: "saving is allowed even when there are some". The period is saved and the booking
    is not cancelled or moved; its mark is AC3's and is asserted there."""
    venue = make_venue(db)
    day = _days_from_now(20).replace(hour=9, minute=0, second=0)
    booking = _booking(db, venue.id, day, day + timedelta(hours=2), status="APPROVED")

    response = venue_staff_client.post(
        _url(venue.id), json=_body(day - timedelta(hours=1), day + timedelta(hours=3))
    )

    assert response.status_code == 201, response.text
    assert len(_periods(db, venue.id)) == 1
    db.expire_all()
    assert db.get(VenueBooking, booking.id).status == "APPROVED"


@pytest.mark.story("9.4", ac=3)
def test_saving_a_period_marks_each_booking_it_overlaps(db, venue_staff_client):
    """AC3: pending and approved alike. Status, venue and period are untouched, and the
    event is not cancelled."""
    venue = make_venue(db)
    pending = _live(db, venue.id, _day(3))
    approved = _booking(db, venue.id, _day(5), _day(5) + timedelta(hours=2), status="APPROVED")
    before = {
        booking.id: (booking.status, booking.venue_id, booking.starts_at, booking.ends_at)
        for booking in (pending, approved)
    }

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    for booking in (pending, approved):
        assert _marked_at(db, booking.id) is not None
        stored = db.get(VenueBooking, booking.id)
        assert (stored.status, stored.venue_id, stored.starts_at, stored.ends_at) == before[
            booking.id
        ]
        assert db.get(Event, stored.event_id).status == EventStatus.PLANNING


@pytest.mark.story("9.4", ac=3)
def test_two_bookings_of_one_event_are_both_marked(db, venue_staff_client):
    """AC3: the event has two bookings on the venue; both carry the mark."""
    venue = make_venue(db)
    event = make_event(
        db, status=EventStatus.PLANNING, assigned_coordinator_id=Users.COORDINATOR.id
    )
    first = make_booking(
        db, venue_id=venue.id, starts_at=_day(3), ends_at=_day(3, 12), event_id=event.id
    )
    second = make_booking(
        db, venue_id=venue.id, starts_at=_day(4), ends_at=_day(4, 12), event_id=event.id
    )

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _marked_at(db, first.id) is not None
    assert _marked_at(db, second.id) is not None


@pytest.mark.story("9.4", ac=3)
def test_a_booking_outside_the_period_is_not_marked(db, venue_staff_client):
    """AC3. cannot fail first: it passes on an implementation that marks nothing; it is
    paired with the marking case above, which carries the red. Another event's booking on the
    same venue, and the same venue's booking on another venue, are left alone."""
    venue, elsewhere = make_venue(db), make_venue(db)
    inside = _live(db, venue.id, _day(3))
    outside = _live(db, venue.id, _day(20))
    other_venue = _live(db, elsewhere.id, _day(3))

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _marked_at(db, inside.id) is not None
    assert _marked_at(db, outside.id) is None
    assert _marked_at(db, other_venue.id) is None


@pytest.mark.story("9.4", ac=3)
def test_marking_and_clearing_each_leave_an_audit_row(db, venue_staff_client):
    """AC3: one row per booking marked, one per booking cleared, naming the actor, the
    venue and the event."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3))
    period = _add(venue_staff_client, venue.id, _day(2), _day(7))

    (marked,) = _audit(db, MARKED, booking.id)
    venue_staff_client.delete(_url(venue.id, uuid.UUID(period["id"])))
    (cleared,) = _audit(db, CLEARED, booking.id)

    for entry in (marked, cleared):
        assert entry.actor_id == Users.VENUE_STAFF.id
        assert entry.entity_type == "venue_booking"
        assert entry.details["venue_id"] == str(venue.id)
        assert entry.details["event_id"] == str(booking.event_id)


@pytest.mark.story("9.4", ac=5)
def test_overlapping_a_held_period_by_one_minute_marks_the_booking(db, venue_staff_client):
    """AC5: the least overlap there is."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3, 10))

    _add(venue_staff_client, venue.id, _day(3, 8), _day(3, 10) + timedelta(minutes=1))

    assert _marked_at(db, booking.id) is not None


@pytest.mark.story("9.4", ac=5)
def test_a_period_that_only_touches_the_booking_does_not_mark_it(db, venue_staff_client):
    """AC5. cannot fail first: it passes on an implementation that marks nothing;
    paired with the one-minute case above. A period ending exactly where the booking's held
    period starts, and one starting exactly where it ends, leave it unmarked."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3, 10))

    _add(venue_staff_client, venue.id, _day(3, 6), _day(3, 10))
    _add(venue_staff_client, venue.id, _day(3, 12), _day(3, 18))

    assert _marked_at(db, booking.id) is None


@pytest.mark.story("9.4", ac=5)
@pytest.mark.parametrize(
    ("period", "expected_marked"),
    [
        # booking 10:00-12:00 with 60 minutes' setup and 30 minutes' teardown: held 09:00-12:30
        (((9, 15), (9, 45)), True),  # only the setup
        (((12, 15), (13, 0)), True),  # only the teardown
        (((8, 0), (9, 0)), False),  # touches held_from
        (((12, 30), (14, 0)), False),  # touches held_until
    ],
)
def test_the_overlap_is_measured_against_the_held_period(
    db, venue_staff_client, period, expected_marked
):
    """AC5: setup and teardown count, and the held period's own edges are half-open."""
    venue = make_venue(db)
    booking = _booking(
        db,
        venue.id,
        _day(3, 10),
        _day(3, 12),
        status="PENDING",
        setup_minutes=60,
        teardown_minutes=30,
    )
    (start_h, start_m), (end_h, end_m) = period

    _add(
        venue_staff_client,
        venue.id,
        _day(3, start_h) + timedelta(minutes=start_m),
        _day(3, end_h) + timedelta(minutes=end_m),
    )

    assert (_marked_at(db, booking.id) is not None) is expected_marked


@pytest.mark.story("9.4", ac=6)
def test_extending_marks_the_bookings_it_newly_reaches(db, venue_staff_client):
    """AC6: the booking already marked keeps its timestamp; the one reached is marked."""
    venue = make_venue(db)
    inside = _live(db, venue.id, _day(3))
    beyond = _live(db, venue.id, _day(8))
    period = _add(venue_staff_client, venue.id, _day(2), _day(5))
    inside_since = _marked_at(db, inside.id)
    assert inside_since is not None and _marked_at(db, beyond.id) is None

    extended = venue_staff_client.patch(
        _url(venue.id, uuid.UUID(period["id"])), json={"ends_at": _day(10).isoformat()}
    )

    assert extended.status_code == 200, extended.text
    assert _marked_at(db, inside.id) == inside_since
    assert _marked_at(db, beyond.id) is not None


@pytest.mark.story("9.4", ac=8)
def test_a_booking_in_progress_is_marked(db, venue_staff_client):
    """AC8: its held period began an hour ago and ends in two, and it is still to come."""
    venue = make_venue(db)
    now = datetime.now(UTC)
    booking = _booking(
        db,
        venue.id,
        now - timedelta(hours=1),
        now + timedelta(hours=2),
        status="APPROVED",
        event_status=EventStatus.CONFIRMED,
    )

    _add(venue_staff_client, venue.id, _day(-1), _day(1))

    assert _marked_at(db, booking.id) is not None


@pytest.mark.story("9.4", ac=8)
def test_a_completed_events_booking_is_not_marked(db, venue_staff_client):
    """AC8. cannot fail first: it passes on an implementation that marks nothing; paired
    with the in-progress case above, whose period covers both."""
    venue = make_venue(db)
    now = datetime.now(UTC)
    completed = _booking(
        db,
        venue.id,
        now - timedelta(hours=1),
        now + timedelta(hours=2),
        status="APPROVED",
        event_status=EventStatus.COMPLETED,
    )

    _add(venue_staff_client, venue.id, _day(-1), _day(1))

    assert _marked_at(db, completed.id) is None


@pytest.mark.story("9.4", ac=8)
def test_a_booking_whose_held_period_is_over_is_not_marked(db, venue_staff_client):
    """AC8. cannot fail first, as above: a period saved over days already gone
    marks nothing, though the booking was inside it."""
    venue = make_venue(db)
    gone = _booking(db, venue.id, _day(-6), _day(-6, 12), status="APPROVED")

    _add(venue_staff_client, venue.id, _day(-8), _day(-4))

    assert _marked_at(db, gone.id) is None


@pytest.mark.story("9.4", ac=3)
def test_a_planning_event_stays_in_planning(db, venue_staff_client):
    """AC3. cannot fail first: nothing changes an event's status today, so it passes before
    the change; it is paired with the Confirmed case below, which carries the red. No history
    row, no audit entry."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.PLANNING)
    _pending_of(db, event, venue.id, _day(3))
    history_before = len(_history(db, event.id))

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _status_of(db, event.id) == EventStatus.PLANNING
    assert len(_history(db, event.id)) == history_before
    assert _audit(db, RETURNED_TO_PLANNING, event.id) == []


@pytest.mark.story("9.4", ac=3)
def test_a_confirmed_event_goes_back_to_planning(db, venue_staff_client):
    """AC3: with a status-history row naming the venue, written by the Venue Staff member,
    and an audit entry that says where it came from. Its booking is still approved: the event is
    not cancelled and keeps its details."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.CONFIRMED, name="Nimbus Developer Conference")
    booking = _pending_of(db, event, venue.id, _day(3), status="APPROVED")

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _status_of(db, event.id) == EventStatus.PLANNING
    (row,) = _returned(db, event.id)
    assert row.changed_by_id == Users.VENUE_STAFF.id
    assert venue.name in row.reason
    (entry,) = _audit(db, RETURNED_TO_PLANNING, event.id)
    assert entry.actor_id == Users.VENUE_STAFF.id
    assert entry.details["from_status"] == EventStatus.CONFIRMED
    assert entry.details["venue_id"] == str(venue.id)
    db.expire_all()
    assert db.get(VenueBooking, booking.id).status == "APPROVED"
    assert db.get(Event, event.id).name == "Nimbus Developer Conference"


@pytest.mark.story("9.4", ac=3)
def test_an_event_awaiting_its_safety_check_goes_back_to_planning_and_its_people_are_told(
    db, venue_staff_client
):
    """AC3 (21.1): the same as for a Confirmed event - once, with a history row naming the
    venue and an EVENT_RETURNED_TO_PLANNING audit entry saying where it came from - and its
    coordinator and organiser are told exactly as for a Confirmed one."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.AWAITING_SAFETY_CHECK)
    _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    _pending_of(db, event, venue.id, _day(4), status="APPROVED")
    starts_at, ends_at = _day(2), _day(7)

    _add(venue_staff_client, venue.id, starts_at, ends_at, reason="SAFETY", description="Wiring")

    assert _status_of(db, event.id) == EventStatus.PLANNING
    returned = [
        row
        for row in _history(db, event.id)
        if (row.from_status, row.to_status)
        == (EventStatus.AWAITING_SAFETY_CHECK, EventStatus.PLANNING)
    ]
    (row,) = returned
    assert row.changed_by_id == Users.VENUE_STAFF.id
    assert venue.name in row.reason
    (entry,) = _audit(db, RETURNED_TO_PLANNING, event.id)
    assert entry.details["from_status"] == EventStatus.AWAITING_SAFETY_CHECK
    assert entry.details["venue_id"] == str(venue.id)
    notices = _told(db, event.id)
    assert _recipients(notices) == sorted([Users.COORDINATOR.id, Users.ORGANISER.id])
    for notice in notices:
        for text_wanted in (venue.name, "Safety concern"):
            assert text_wanted in notice.message
    # The description is the coordinator's to read; the organiser's notice leaves it out.
    by_recipient = {notice.recipient_id: notice.message for notice in notices}
    assert "Wiring" in by_recipient[Users.COORDINATOR.id]
    assert "Wiring" not in by_recipient[Users.ORGANISER.id]


@pytest.mark.story("9.4", ac=3)
def test_two_marked_bookings_of_one_event_move_it_once(db, venue_staff_client):
    """AC3: one status change, one history row, one audit entry."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.CONFIRMED)
    _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    _pending_of(db, event, venue.id, _day(4), status="APPROVED")

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _status_of(db, event.id) == EventStatus.PLANNING
    assert len(_returned(db, event.id)) == 1
    assert len(_audit(db, RETURNED_TO_PLANNING, event.id)) == 1


@pytest.mark.story("9.4", ac=4)
def test_the_coordinator_and_the_organiser_are_each_told_naming_venue_period_and_reason(
    db, venue_staff_client
):
    """AC4: the type is defined, one notice each, about the event, with the venue, the period
    and the reason - and the description when there is one."""
    venue = make_venue(db)
    event = _event_for(db)
    _pending_of(db, event, venue.id, _day(3))
    starts_at, ends_at = _day(2), _day(7)

    _add(
        venue_staff_client,
        venue.id,
        starts_at,
        ends_at,
        reason="RENOVATION",
        description="Floor relaid",
    )

    assert NotificationType.BOOKING_VENUE_UNAVAILABLE.value == VENUE_UNAVAILABLE
    notices = _told(db, event.id)
    assert _recipients(notices) == sorted([Users.COORDINATOR.id, Users.ORGANISER.id])
    for notice in notices:
        assert venue.name in notice.title
        for text_wanted in (
            venue.name,
            _on_singapore_date(starts_at),
            _on_singapore_date(ends_at),
            "Renovation",
        ):
            assert text_wanted in notice.message
        assert (notice.related_entity_type, notice.related_entity_id) == ("event", event.id)
    by_recipient = {notice.recipient_id: notice.message for notice in notices}
    assert "Floor relaid" in by_recipient[Users.COORDINATOR.id]
    assert "Floor relaid" not in by_recipient[Users.ORGANISER.id]


@pytest.mark.story("9.4", ac=4)
def test_two_newly_marked_bookings_of_one_event_tell_it_once(db, venue_staff_client):
    """AC4: one notice each to the coordinator and the organiser, not one per
    booking."""
    venue = make_venue(db)
    event = _event_for(db)
    _pending_of(db, event, venue.id, _day(3))
    _pending_of(db, event, venue.id, _day(4))

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert len(_told(db, event.id)) == 2


@pytest.mark.story("9.4", ac=4)
def test_an_event_with_no_coordinator_still_tells_its_organiser(db, venue_staff_client):
    """AC4: nobody is assigned yet, so the organiser alone is told, and nothing fails."""
    venue = make_venue(db)
    event = _event_for(db, assigned_coordinator_id=None)
    _pending_of(db, event, venue.id, _day(3))

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _recipients(_told(db, event.id)) == [Users.ORGANISER.id]


@pytest.mark.story("9.4", ac=4)
def test_after_a_reassignment_the_new_coordinator_is_told(db, venue_staff_client):
    """AC4 (20.1 AC4): whoever coordinates the event when the period is saved, not whoever
    did when the booking was requested."""
    venue = make_venue(db)
    event = _event_for(db)
    _pending_of(db, event, venue.id, _day(3))
    event.assigned_coordinator_id = Users.COORDINATOR_2.id
    db.flush()

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _recipients(_told(db, event.id)) == sorted([Users.COORDINATOR_2.id, Users.ORGANISER.id])


@pytest.mark.story("9.4", ac=4)
def test_only_the_events_own_people_are_told_and_never_the_one_who_saved(db, venue_staff_client):
    """AC4. cannot fail first: nothing notifies today; paired with the notice above. Other
    users get none, and when the Venue Staff member who saves is also the event's assigned
    coordinator, they are not told of their own action."""
    venue = make_venue(db)
    event = _event_for(db, assigned_coordinator_id=Users.VENUE_STAFF.id)
    _pending_of(db, event, venue.id, _day(3))

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _recipients(_told(db, event.id)) == [Users.ORGANISER.id]
    everyone_else = [
        Users.ORGANISER_2.id,
        Users.COORDINATOR.id,
        Users.COORDINATOR_2.id,
        Users.TECH_SUPPORT.id,
        Users.ATTENDEE.id,
        Users.VENUE_STAFF.id,
    ]
    told = db.scalars(
        select(Notification.recipient_id).where(
            Notification.notification_type == VENUE_UNAVAILABLE,
            Notification.recipient_id.in_(everyone_else),
        )
    ).all()
    assert list(told) == []


@pytest.mark.story("9.4", ac=4)
def test_a_reason_only_edit_tells_nobody_and_a_later_save_tells_again(db, venue_staff_client):
    """AC4: editing the reason or description of a period that affects the same
    bookings sends nothing; a later save that newly affects another booking of the same event
    sends that event's people another notice; bookings already marked are not told twice."""
    venue = make_venue(db)
    event = _event_for(db)
    _pending_of(db, event, venue.id, _day(3))
    later = _pending_of(db, event, venue.id, _day(12))
    period = _add(venue_staff_client, venue.id, _day(2), _day(7))
    period_id = uuid.UUID(period["id"])
    assert len(_told(db, event.id)) == 2

    venue_staff_client.patch(_url(venue.id, period_id), json={"reason": "SAFETY"})
    venue_staff_client.patch(_url(venue.id, period_id), json={"description": "Rewiring"})
    assert len(_told(db, event.id)) == 2

    extended = venue_staff_client.patch(
        _url(venue.id, period_id), json={"ends_at": _day(14).isoformat()}
    )

    assert extended.status_code == 200, extended.text
    assert _marked_at(db, later.id) is not None
    assert len(_told(db, event.id)) == 4
    assert _recipients(_told(db, event.id)) == sorted(
        [Users.COORDINATOR.id, Users.ORGANISER.id] * 2
    )


@pytest.mark.story("9.4", ac=4)
@pytest.mark.story("9.4", ac=6)
def test_extending_tells_only_the_event_of_the_booking_it_newly_reaches(db, venue_staff_client):
    """AC6: the event already told is not told again."""
    venue = make_venue(db)
    inside = _event_for(db)
    beyond = _event_for(db)
    _pending_of(db, inside, venue.id, _day(3))
    _pending_of(db, beyond, venue.id, _day(8))
    period = _add(venue_staff_client, venue.id, _day(2), _day(5))
    assert len(_told(db, inside.id)) == 2 and _told(db, beyond.id) == []

    venue_staff_client.patch(
        _url(venue.id, uuid.UUID(period["id"])), json={"ends_at": _day(10).isoformat()}
    )

    assert len(_told(db, inside.id)) == 2
    assert len(_told(db, beyond.id)) == 2


@pytest.mark.story("9.4", ac=8)
def test_a_completed_events_status_and_notices_are_untouched(db, venue_staff_client):
    """AC8. cannot fail first: its booking is not a candidate, so nothing reaches the
    event; paired with the notice above, whose period covers both."""
    venue = make_venue(db)
    now = datetime.now(UTC)
    completed = _event_for(db, EventStatus.COMPLETED)
    _pending_of(db, completed, venue.id, now - timedelta(hours=1), status="APPROVED")
    reached = _event_for(db)
    _pending_of(db, reached, venue.id, _day(1))

    _add(venue_staff_client, venue.id, _day(-1), _day(3))

    assert _status_of(db, completed.id) == EventStatus.COMPLETED
    assert _told(db, completed.id) == []
    assert len(_told(db, reached.id)) == 2


@pytest.mark.story("9.4", ac=10)
def test_an_approval_that_wins_the_lock_is_approved_and_the_save_then_marks_it(engine):
    """AC10, approve first. The approval holds the request's row; the save, which
    loaded the request as pending, waits on it; the approval commits and the save marks the
    request as it now stands - approved - rather than as it loaded it. cannot fail first: the
    save's re-read (``populate_existing``) is already in place; it pins the order the guard
    must keep."""
    venue_id, event_id, booking_id = _committed_pending_request(engine)
    pids: dict[str, int] = {}
    holding = threading.Event()

    def approve() -> None:
        with Session(engine) as session:
            pids["approve"] = _backend_pid(session)
            booking = booking_service.get_booking_for_approval(session, booking_id)
            holding.set()
            _wait_until(engine, pids, "save")
            booking_service.approve_booking(
                session,
                booking,
                actor_id=STAFF_ID,
                hold_expires_at=datetime.now(UTC) + timedelta(days=1),
            )

    def save() -> list[tuple[uuid.UUID, str]]:
        with Session(engine) as session:
            pids["save"] = _backend_pid(session)
            assert holding.wait(LOCK_WAIT_SECONDS)
            loaded = session.get(VenueBooking, booking_id)
            assert loaded.status == "PENDING"
            marked = _save_period(session, venue_id).newly_marked
            seen = [(booking.id, booking.status) for booking in marked]
            session.commit()
            return seen

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            approving = pool.submit(approve)
            saving = pool.submit(save)
            approving.result(timeout=40)
            seen = saving.result(timeout=40)

        assert seen == [(booking_id, "APPROVED")]
        with Session(engine) as session:
            row = session.get(VenueBooking, booking_id)
            assert (row.status, row.venue_unavailable_marked_at is not None) == ("APPROVED", True)
    finally:
        _remove_race_rows(engine, venue_id, event_id, booking_id)


@pytest.mark.story("9.4", ac=10)
def test_a_save_that_wins_the_lock_refuses_the_approval_that_waited(engine):
    """AC10, save first. The save marks the request and holds its row; the approval waits on
    it; the save commits the period and the mark together, and the approval, reading the period
    in a query of its own once the lock is its, is refused as the request step would: still
    pending, still marked, nobody's decision."""
    venue_id, event_id, booking_id = _committed_pending_request(engine)
    pids: dict[str, int] = {}
    holding = threading.Event()

    def save() -> None:
        with Session(engine) as session:
            pids["save"] = _backend_pid(session)
            _save_period(session, venue_id)
            holding.set()
            _wait_until(engine, pids, "approve")
            session.commit()

    def approve() -> Exception | None:
        with Session(engine) as session:
            pids["approve"] = _backend_pid(session)
            assert holding.wait(LOCK_WAIT_SECONDS)
            booking = booking_service.get_booking_for_approval(session, booking_id)
            try:
                booking_service.approve_booking(
                    session,
                    booking,
                    actor_id=STAFF_ID,
                    hold_expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            except booking_service.VenueBlocked as refusal:
                return refusal
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            saving = pool.submit(save)
            approving = pool.submit(approve)
            saving.result(timeout=40)
            refusal = approving.result(timeout=40)

        assert isinstance(refusal, booking_service.VenueBlocked), "the approval was not refused"
        with Session(engine) as session:
            row = session.get(VenueBooking, booking_id)
            assert row.status == "PENDING"
            assert row.venue_unavailable_marked_at is not None
            assert (row.decided_by_id, row.hold_expires_at) == (None, None)
    finally:
        _remove_race_rows(engine, venue_id, event_id, booking_id)


@pytest.mark.story("9.4", ac=10)
def test_a_save_and_the_events_confirmation_at_the_same_moment_both_finish(engine):
    """AC10. Real concurrent transactions, so this test commits and cleans up after itself. The
    confirmation holds the event's row (it sets the event to Confirmed again, which fires
    trg_events_complete_venue_holds and updates its approved bookings); the save, which returns a
    Confirmed event to Planning, waits on that row; the confirmation commits and the save goes on.
    The save locks the event before its bookings, as the confirmation does, so neither waits on
    the other for ever: both finish, the booking is marked, the event's return to Planning is
    recorded once, and the hold the confirmation completed stays completed."""
    expiry = datetime.now(UTC) + timedelta(days=1)
    with Session(engine) as session:
        venue = make_venue(session)
        event = _event_for(session, EventStatus.CONFIRMED)
        booking = _pending_of(
            session, event, venue.id, _day(3), status="APPROVED", hold_expires_at=expiry
        )
        session.commit()
        venue_id, event_id, booking_id = venue.id, event.id, booking.id
    data = VenueUnavailabilityCreate(
        starts_at=_day(2), ends_at=_day(7), reason="MAINTENANCE", description="Servicing"
    )
    pids: dict[str, int] = {}
    holding = threading.Event()

    def confirm() -> None:
        with Session(engine) as session:
            pids["confirm"] = _backend_pid(session)
            for status in (EventStatus.PLANNING, EventStatus.CONFIRMED):
                session.execute(update(Event).where(Event.id == event_id).values(status=status))
            holding.set()
            _wait_until(engine, pids, "save")
            session.commit()

    def save() -> None:
        with Session(engine) as session:
            pids["save"] = _backend_pid(session)
            assert holding.wait(LOCK_WAIT_SECONDS)
            venue_service.add_unavailability(
                session, venue_id, data, actor=session.get(User, STAFF_ID), now=datetime.now(UTC)
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            confirming = pool.submit(confirm)
            saving = pool.submit(save)
            confirming.result(timeout=40)
            saving.result(timeout=40)

        with Session(engine) as session:
            row = session.get(VenueBooking, booking_id)
            assert row.venue_unavailable_marked_at is not None
            assert row.hold_completed_at is not None
            assert session.get(Event, event_id).status == EventStatus.PLANNING
            returned = [
                history
                for history in session.scalars(
                    select(EventStatusHistory).where(EventStatusHistory.event_id == event_id)
                )
                if history.changed_by_id == STAFF_ID
                and (history.from_status, history.to_status)
                == (EventStatus.CONFIRMED, EventStatus.PLANNING)
            ]
            assert len(returned) == 1
    finally:
        _remove_race_rows(engine, venue_id, event_id, booking_id)


@pytest.mark.story("9.4", ac=10)
def test_two_saves_at_once_leave_a_booking_flagged_while_a_period_still_covers_it(engine):
    """AC10, two saves on one venue. cannot fail first: the events are locked in a statement of
    their own before the overlap is read, so a save that waited reads what the other committed.
    One save adds a second period over a flagged booking and holds; the other shortens the first
    period off the booking and waits; once the first commits, the booking stays flagged, for the
    second period still covers it."""
    venue_id, event_id, booking_id = _committed_pending_request(engine)
    with Session(engine) as session:
        first = VenueUnavailabilityPeriod(
            venue_id=venue_id,
            starts_at=_day(1),
            ends_at=_day(8),
            reason="MAINTENANCE",
            notes="Floors",
            created_by_id=STAFF_ID,
        )
        session.add(first)
        session.flush()
        first_id = first.id
        _mark_in_sql(session, booking_id, datetime.now(UTC))
        session.commit()
    pids: dict[str, int] = {}
    holding = threading.Event()

    def add_second() -> None:
        with Session(engine) as session:
            pids["add"] = _backend_pid(session)
            _save_period(session, venue_id)
            holding.set()
            _wait_until(engine, pids, "shorten")
            session.commit()

    def shorten_first() -> None:
        with Session(engine) as session:
            pids["shorten"] = _backend_pid(session)
            assert holding.wait(LOCK_WAIT_SECONDS)
            venue_service.edit_unavailability(
                session,
                venue_id,
                first_id,
                VenueUnavailabilityUpdate(ends_at=_day(2)),
                actor=session.get(User, STAFF_ID),
                now=datetime.now(UTC),
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            adding = pool.submit(add_second)
            shortening = pool.submit(shorten_first)
            adding.result(timeout=40)
            shortening.result(timeout=40)

        with Session(engine) as session:
            assert session.get(VenueBooking, booking_id).venue_unavailable_marked_at is not None
    finally:
        _remove_race_rows(engine, venue_id, event_id, booking_id)


@pytest.mark.story("9.4", ac=10)
def test_a_request_that_slipped_in_unmarked_cannot_be_approved_and_the_next_save_marks_it(
    db, login_as
):
    """AC10, the known gap, on one connection: a request raised at the instant of a save
    sits pending inside the period, unmarked. Its approval is refused; the next save on the venue
    - any - marks it."""
    venue = make_venue(db)
    _period(db, venue.id, _day(2), _day(7))
    slipped = _live(db, venue.id, _day(3))
    assert _marked_at(db, slipped.id) is None
    staff = login_as(Users.VENUE_STAFF)

    refused = _approve(staff, slipped.id)
    _add(staff, venue.id, _day(30), _day(31))

    assert refused.status_code == 409, refused.text
    assert _stored(db, slipped.id).status == "PENDING"
    assert _marked_at(db, slipped.id) is not None


@pytest.mark.story("9.4", ac=4)
def test_the_organisers_notice_leaves_out_the_description_and_the_coordinators_keeps_it(
    db, venue_staff_client
):
    """AC4 (PO decision): the organiser's notice names the venue, the period and the reason;
    the coordinator's names the description too."""
    venue = make_venue(db)
    event = _event_for(db)
    _pending_of(db, event, venue.id, _day(3))

    _add(venue_staff_client, venue.id, _day(2), _day(7), description="Asbestos found in ceiling")

    by_recipient = {notice.recipient_id: notice.message for notice in _told(db, event.id)}
    coordinator, organiser = by_recipient[Users.COORDINATOR.id], by_recipient[event.organiser_id]
    assert "Asbestos found in ceiling" in coordinator
    assert "Asbestos" not in organiser
    assert venue.name in organiser and "Maintenance" in organiser
    assert _on_singapore_date(_day(2)) in organiser


@pytest.mark.story("9.4", ac=8)
@pytest.mark.parametrize(
    "event_status",
    [
        EventStatus.DRAFT,
        EventStatus.UNDER_REVIEW,
        EventStatus.CLARIFICATION_REQUESTED,
        EventStatus.CANCELLED,
        EventStatus.REJECTED,
    ],
)
def test_only_planning_awaiting_and_confirmed_events_are_candidates(
    db, venue_staff_client, event_status
):
    """AC8: a booking of an event in any other status is neither listed nor marked - a list of
    the statuses that count, so a status added later is left out until someone says it counts."""
    venue = make_venue(db)
    booking = _booking(
        db, venue.id, _day(3), _day(3, 12), status="PENDING", event_status=event_status
    )

    preview = _preview(venue_staff_client, venue.id, _day(2), _day(7))
    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert preview.status_code == 200, preview.text
    assert str(booking.id) not in _ids(preview)
    assert _marked_at(db, booking.id) is None


@pytest.mark.story("9.4", ac=8)
@pytest.mark.parametrize(
    "event_status",
    [EventStatus.PLANNING, EventStatus.AWAITING_SAFETY_CHECK, EventStatus.CONFIRMED],
)
def test_planning_awaiting_and_confirmed_events_are_candidates(
    db, venue_staff_client, event_status
):
    """AC8. cannot fail first: they are marked today; pinned beside the exclusions above."""
    venue = make_venue(db)
    booking = _booking(
        db, venue.id, _day(3), _day(3, 12), status="PENDING", event_status=event_status
    )

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _marked_at(db, booking.id) is not None


@pytest.mark.story("9.4", ac=3)
def test_a_save_leaves_another_venues_unmarked_booking_alone(db, venue_staff_client):
    """AC3. cannot fail first: the re-check is scoped to its venue; pinned so a change to its
    query cannot sweep the whole table. Another venue's booking sits inside a closure of its own
    that was written without a re-check, so it is overlapped and unmarked."""
    venue, elsewhere = make_venue(db), make_venue(db)
    stranger = _live(db, elsewhere.id, _day(3))
    _period(db, elsewhere.id, _day(2), _day(7))

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _marked_at(db, stranger.id) is None


@pytest.mark.story("9.4", ac=2)
@pytest.mark.story("9.4", ac=3)
def test_a_lapsed_hold_is_released_before_the_preview_and_the_save_look(db, venue_staff_client):
    """AC2 and AC3: an approved booking whose hold has lapsed holds nothing, as the calendar already
    treats it; the preview does not list it and the save does not flag it, whichever request
    comes first - the routes release lapsed holds as the calendar's does."""
    venue = make_venue(db)
    event = _event_for(db)
    lapsed = _pending_of(
        db,
        event,
        venue.id,
        _day(3),
        status="APPROVED",
        hold_expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    preview = _preview(venue_staff_client, venue.id, _day(2), _day(7))
    assert str(lapsed.id) not in _ids(preview)
    # A second venue's lapsed hold meets the save, with no preview before it.
    other_venue = make_venue(db)
    lapsed2 = _pending_of(
        db,
        _event_for(db),
        other_venue.id,
        _day(4),
        status="APPROVED",
        hold_expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    _add(venue_staff_client, other_venue.id, _day(2), _day(7))

    assert _marked_at(db, lapsed2.id) is None
    assert _stored(db, lapsed.id).status == "EXPIRED"
    assert _stored(db, lapsed2.id).status == "EXPIRED"


@pytest.mark.story("9.4", ac=4)
def test_the_notice_does_not_name_whoever_saved(db, venue_staff_client):
    """AC4: when a save flags a booking an earlier closure covers, the closure is not the
    saver's, so the notice says the venue is unavailable - not that someone marked it."""
    venue = make_venue(db)
    event, _booking_, _over = _unmarked_booking_under_a_period(db, venue.id)
    saver = _staff(db).full_name

    _add(venue_staff_client, venue.id, _day(1), _day(2))

    notices = _told(db, event.id)
    assert len(notices) == 2
    for notice in notices:
        assert saver not in notice.message
        assert f"{venue.name} is unavailable " in notice.message


@pytest.mark.story("9.4", ac=2)
@pytest.mark.story("9.4", ac=3)
@pytest.mark.parametrize("method", ["patch", "delete"])
def test_a_lapsed_hold_is_released_before_an_edit_or_a_removal(db, venue_staff_client, method):
    """AC2 and AC3: the edit and the removal release lapsed holds as the add and the preview do.
    cannot fail first: the dependency is on every write route today; it is pinned beside the
    add's."""
    venue = make_venue(db)
    period = _period(db, venue.id, _days_from_now(10), _days_from_now(12))
    lapsed = _pending_of(
        db,
        _event_for(db),
        make_venue(db).id,
        _day(3),
        status="APPROVED",
        hold_expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    response = _write(venue_staff_client, method, venue.id, period.id)

    assert response.status_code in (200, 204), response.text
    assert _stored(db, lapsed.id).status == "EXPIRED"


@pytest.mark.story("9.4", ac=10)
def test_a_save_that_holds_the_event_first_and_a_confirmation_that_follows_both_finish(
    engine, monkeypatch
):
    """AC10, save first. The save re-checks and so holds the event's row, then pauses before it
    settles the event; the confirmation starts and blocks on that row; once it is waiting, the
    save settles (the event goes back to Planning) and commits; the confirmation then goes
    through. Both finish. Without the save's lock on the event the confirmation took the event
    first, its trigger then waited on the bookings the save held, and the save's own update of the
    event waited on the confirmation: a deadlock."""
    expiry = datetime.now(UTC) + timedelta(days=1)
    with Session(engine) as session:
        venue = make_venue(session)
        event = _event_for(session, EventStatus.CONFIRMED)
        booking = _pending_of(
            session, event, venue.id, _day(3), status="APPROVED", hold_expires_at=expiry
        )
        session.commit()
        venue_id, event_id, booking_id = venue.id, event.id, booking.id
    data = VenueUnavailabilityCreate(
        starts_at=_day(2), ends_at=_day(7), reason="MAINTENANCE", description="Servicing"
    )
    pids: dict[str, int] = {}
    holding = threading.Event()
    original = events_service.return_event_to_planning

    def paused(*args, **kwargs):
        holding.set()
        _wait_until(engine, pids, "confirm")
        return original(*args, **kwargs)

    monkeypatch.setattr(events_service, "return_event_to_planning", paused)

    def save() -> None:
        with Session(engine) as session:
            pids["save"] = _backend_pid(session)
            venue_service.add_unavailability(
                session, venue_id, data, actor=session.get(User, STAFF_ID), now=datetime.now(UTC)
            )

    def confirm() -> None:
        with Session(engine) as session:
            pids["confirm"] = _backend_pid(session)
            assert holding.wait(LOCK_WAIT_SECONDS)
            for status in (EventStatus.PLANNING, EventStatus.CONFIRMED):
                session.execute(update(Event).where(Event.id == event_id).values(status=status))
            session.commit()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            saving = pool.submit(save)
            confirming = pool.submit(confirm)
            saving.result(timeout=40)
            confirming.result(timeout=40)

        with Session(engine) as session:
            row = session.get(VenueBooking, booking_id)
            assert row.venue_unavailable_marked_at is not None
            assert row.hold_completed_at is not None
            assert session.get(Event, event_id).status == EventStatus.CONFIRMED
            returned = [
                history
                for history in session.scalars(
                    select(EventStatusHistory).where(EventStatusHistory.event_id == event_id)
                )
                if history.changed_by_id == STAFF_ID
                and (history.from_status, history.to_status)
                == (EventStatus.CONFIRMED, EventStatus.PLANNING)
            ]
            assert len(returned) == 1
    finally:
        _remove_race_rows(engine, venue_id, event_id, booking_id)
