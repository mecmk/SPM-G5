"""Story 12.1 (Sprint 2) - the venue hold, built as s12.1.

AC3  On submission, the venue is soft-locked for the booked period, and the request appears in
     Venue Staff's booking requests as Pending.
AC4  The hold is released automatically if the request is rejected or withdrawn.
AC6  Periods that only touch at a boundary are not a conflict; an overlap of one minute is.
AC7  A venue can hold several events on the same day as long as their booked periods do not
     overlap.
AC8  Partial overlaps are reported, not just full ones.
AC12 If two coordinators submit overlapping requests for the same venue at the same moment,
     only the first succeeds. The second is refused, naming the held period.
AC13 A double-click on Submit creates only one request.
AC14 The server re-runs the conflict check at submission and creates the request and its hold in
     one step. The database enforces the hold, so two overlapping requests cannot both succeed
     even if the form was bypassed.

The bug this fixes (27 Sep 2026): a coordinator could request a venue already booked for the
period, and Venue Staff could then never approve it. Setup and teardown stay 0 until the rest of
12.1, so a request's held period is its event's period. Most cases use a fresh venue and fresh
Planning events assigned to Chloe, so no seeded booking is in the way.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from psycopg.errors import ExclusionViolation
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings import service
from app.bookings.models import BookingStatus, VenueBooking
from app.bookings.schemas import BookingRequestIn
from app.common.audit import AuditLog
from app.events.models import Event, EventStatus
from app.venues.models import Venue
from tests.support.factories import make_booking, make_event, make_venue
from tests.support.seed import Events, Users, Venues

SGT = timezone(timedelta(hours=8))
MIGRATION_006 = (
    Path(__file__).resolve().parents[2] / "db" / "migrations" / "006_hold_venue_while_pending.sql"
)
# The constraint as it stood before migration 006: only APPROVED rows blocked a venue.
PRE_006_CONSTRAINT = (
    "ALTER TABLE venue_bookings ADD CONSTRAINT ex_venue_bookings_no_double_booking"
    " EXCLUDE USING gist (venue_id WITH =, tstzrange(held_from, held_until, '[)') WITH &&)"
    " WHERE (status = 'APPROVED')"
)


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    """A moment in December 2026, Singapore time."""
    return datetime(2026, 12, day, hour, minute, tzinfo=SGT)


def _event(db: Session, starts_at: datetime, ends_at: datetime, **overrides) -> Event:
    """A Planning event assigned to Chloe, so she may request a venue for it."""
    return make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=starts_at,
        ends_at=ends_at,
        **overrides,
    )


def _request(client, event_id: uuid.UUID, venue_id: uuid.UUID):
    return client.post("/bookings", json={"event_id": str(event_id), "venue_id": str(venue_id)})


def _bookings_at(db: Session, venue_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(VenueBooking).where(VenueBooking.venue_id == venue_id)
    )


# --- the reported bug ------------------------------------------------------------------------
@pytest.mark.story("12.1", ac=14)
def test_a_venue_already_booked_for_the_period_cannot_be_requested(coordinator_client, db):
    """Nimbus asked for Grand Hall, which Bookings.APPROVED_GRAND_HALL already holds for Nimbus
    itself, 08:00-19:00 with its setup and teardown. The refusal says so in Singapore time."""
    before = _bookings_at(db, Venues.GRAND_HALL)

    response = _request(coordinator_client, Events.APPROVED, Venues.GRAND_HALL)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Grand Hall is already booked for Nimbus Developer Conference on Wed 25 Nov 2026 from"
        " 08:00 to 19:00, including setup and teardown."
    )
    assert _bookings_at(db, Venues.GRAND_HALL) == before


# --- AC3: a pending request holds its venue --------------------------------------------------
@pytest.mark.story("12.1", ac=3)
def test_a_pending_request_holds_its_venue(coordinator_client, db):
    venue = make_venue(db, name="Hold Test Room")
    first = _event(db, _at(1, 9), _at(1, 12), name="First Hold Event")
    second = _event(db, _at(1, 10), _at(1, 13))

    assert _request(coordinator_client, first.id, venue.id).status_code == 201
    response = _request(coordinator_client, second.id, venue.id)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Hold Test Room is already held by a pending request for First Hold Event on Tue 1 Dec"
        " 2026 from 09:00 to 12:00."
    )


@pytest.mark.story("12.1", ac=3)
def test_the_hold_is_per_venue(coordinator_client, db):
    held, other = make_venue(db), make_venue(db)
    first = _event(db, _at(1, 9), _at(1, 12))
    second = _event(db, _at(1, 9), _at(1, 12))

    assert _request(coordinator_client, first.id, held.id).status_code == 201
    assert _request(coordinator_client, second.id, other.id).status_code == 201


@pytest.mark.story("12.1", ac=3)
def test_a_hold_over_two_days_names_both_dates(coordinator_client, db):
    venue = make_venue(db, name="Overnight Room")
    first = _event(db, _at(1, 18), _at(2, 10), name="Overnight Event")
    second = _event(db, _at(2, 9), _at(2, 11))

    assert _request(coordinator_client, first.id, venue.id).status_code == 201
    response = _request(coordinator_client, second.id, venue.id)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Overnight Room is already held by a pending request for Overnight Event from Tue 1 Dec"
        " 2026, 18:00 to Wed 2 Dec 2026, 10:00."
    )


# --- AC6 / AC7: boundaries -------------------------------------------------------------------
@pytest.mark.story("12.1", ac=6)
@pytest.mark.story("12.1", ac=7)
def test_touching_periods_do_not_clash(coordinator_client, db):
    """Held periods are half-open, so one that starts as another ends shares the day, not a
    minute."""
    venue = make_venue(db)
    morning = _event(db, _at(1, 9), _at(1, 12))
    afternoon = _event(db, _at(1, 12), _at(1, 14))

    assert _request(coordinator_client, morning.id, venue.id).status_code == 201
    assert _request(coordinator_client, afternoon.id, venue.id).status_code == 201


@pytest.mark.story("12.1", ac=6)
def test_one_minute_of_overlap_clashes(coordinator_client, db):
    venue = make_venue(db)
    morning = _event(db, _at(1, 9), _at(1, 12))
    overlapping = _event(db, _at(1, 11, 59), _at(1, 14))

    assert _request(coordinator_client, morning.id, venue.id).status_code == 201
    assert _request(coordinator_client, overlapping.id, venue.id).status_code == 409


# --- AC8: partial overlaps -------------------------------------------------------------------
@pytest.mark.story("12.1", ac=8)
@pytest.mark.parametrize(
    ("starts", "ends"),
    [
        ((9, 0), (11, 0)),  # ends inside the held 10:00-12:00
        ((11, 0), (13, 0)),  # starts inside it
        ((9, 0), (13, 0)),  # contains it
        ((10, 30), (11, 30)),  # lies inside it
    ],
)
def test_partial_overlaps_clash(coordinator_client, db, starts, ends):
    venue = make_venue(db)
    held = _event(db, _at(1, 10), _at(1, 12))
    overlapping = _event(db, _at(1, *starts), _at(1, *ends))

    assert _request(coordinator_client, held.id, venue.id).status_code == 201
    assert _request(coordinator_client, overlapping.id, venue.id).status_code == 409


# --- AC4: a released booking holds nothing ---------------------------------------------------
@pytest.mark.story("12.1", ac=4)
@pytest.mark.parametrize(
    "status", [BookingStatus.REJECTED, BookingStatus.WITHDRAWN, BookingStatus.CANCELLED]
)
def test_a_released_booking_does_not_hold_the_venue(coordinator_client, db, status):
    venue = make_venue(db)
    earlier = _event(db, _at(1, 9), _at(1, 12))
    make_booking(
        db,
        venue_id=venue.id,
        event_id=earlier.id,
        status=status,
        starts_at=earlier.starts_at,
        ends_at=earlier.ends_at,
    )
    later = _event(db, _at(1, 9), _at(1, 12))

    assert _request(coordinator_client, later.id, venue.id).status_code == 201


# --- permission ------------------------------------------------------------------------------
@pytest.mark.story("12.1", ac=11)
def test_an_unassigned_coordinator_is_refused_before_the_hold(client, db):
    """Carl is not Nimbus's coordinator. He is refused for that, and never told the slot is
    held (Sprint 1's AC4, Sprint 2's AC11)."""
    client.login(Users.COORDINATOR_2)

    response = _request(client, Events.APPROVED, Venues.GRAND_HALL)

    assert response.status_code == 403
    assert response.json()["detail"] == service.NOT_ASSIGNED_COORDINATOR_MESSAGE


# --- AC12 / AC13 / AC14: conflict --------------------------------------------------------------
@pytest.mark.story("12.1", ac=12)
@pytest.mark.story("12.1", ac=13)
def test_simultaneous_requests_for_one_slot_create_one_booking(engine):
    """Real concurrent transactions, so this test commits and cleans up after itself. Two
    requests for one slot at once - two tabs, or a double submit - leave exactly one booking;
    the other is refused naming the held period."""
    with Session(engine) as session:
        venue = make_venue(session, name=f"Race Room {uuid.uuid4().hex[:8]}")
        event = _event(session, _at(3, 9), _at(3, 12), name="Race Event")
        session.commit()
        venue_id, event_id, venue_name = venue.id, event.id, venue.name
    start = threading.Barrier(2)

    def attempt() -> str:
        with Session(engine) as session:
            actor = session.get(User, Users.COORDINATOR.id)
            request = BookingRequestIn(event_id=event_id, venue_id=venue_id)
            start.wait()
            try:
                service.create_booking_request(session, request, actor=actor)
            except service.VenueHeld as refusal:
                return str(refusal)
            return "created"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt) for _ in range(2)]
            outcomes = [future.result(timeout=30) for future in futures]

        assert outcomes.count("created") == 1
        assert f"{venue_name} is already held by a pending request for Race Event" in "".join(
            outcomes
        )
        with Session(engine) as session:
            assert _bookings_at(session, venue_id) == 1
    finally:
        with Session(engine) as session:
            booking_ids = session.scalars(
                select(VenueBooking.id).where(VenueBooking.venue_id == venue_id)
            ).all()
            session.execute(delete(AuditLog).where(AuditLog.entity_id.in_(booking_ids)))
            session.execute(delete(VenueBooking).where(VenueBooking.venue_id == venue_id))
            session.execute(delete(Event).where(Event.id == event_id))
            session.execute(delete(Venue).where(Venue.id == venue_id))
            session.commit()


@pytest.mark.story("12.1", ac=14)
def test_the_database_refuses_an_overlapping_hold(db):
    """Bypassing the service: a second overlapping PENDING row is refused by the database
    itself, while a REJECTED one, which holds nothing, is stored."""
    venue = make_venue(db)
    make_booking(db, venue_id=venue.id, starts_at=_at(1, 9), ends_at=_at(1, 12))
    make_booking(
        db,
        venue_id=venue.id,
        status=BookingStatus.REJECTED,
        starts_at=_at(1, 10),
        ends_at=_at(1, 13),
    )

    with pytest.raises(IntegrityError) as excinfo:
        with db.begin_nested():
            make_booking(db, venue_id=venue.id, starts_at=_at(1, 10), ends_at=_at(1, 13))

    assert isinstance(excinfo.value.orig, ExclusionViolation)


@pytest.mark.story("12.1", ac=14)
def test_migration_006_cancels_requests_that_could_never_be_approved(db):
    """Migration 006 runs on databases that already hold clashing pending requests (anyone who
    tried the old form twice). It cancels, oldest first, each pending request that overlaps an
    approved booking or an earlier pending request it keeps, and only then adds the widened
    constraint. Run here on pre-006 data inside the test's transaction, which is rolled back."""
    conn = db.connection()
    conn.exec_driver_sql(
        "ALTER TABLE venue_bookings DROP CONSTRAINT ex_venue_bookings_no_double_booking"
    )
    conn.exec_driver_sql(PRE_006_CONSTRAINT)
    venue, elsewhere = make_venue(db), make_venue(db)

    def booking(start, end, *, created: int, status=BookingStatus.PENDING, venue_id=venue.id):
        return make_booking(
            db,
            venue_id=venue_id,
            status=status,
            starts_at=start,
            ends_at=end,
            created_at=datetime(2026, 9, 20, 9, created, tzinfo=SGT),
        )

    approved = booking(_at(7, 9), _at(7, 12), created=0, status=BookingStatus.APPROVED)
    clashes_with_approved = booking(_at(7, 11), _at(7, 13), created=1)
    clashed_only_with_a_cancelled_one = booking(_at(7, 12), _at(7, 14), created=2)
    first_of_two = booking(_at(7, 15), _at(7, 17), created=3)
    second_of_two = booking(_at(7, 16), _at(7, 18), created=4)
    other_venue = booking(_at(7, 11), _at(7, 13), created=5, venue_id=elsewhere.id)

    conn.exec_driver_sql(MIGRATION_006.read_text(encoding="utf-8"))
    db.expire_all()

    def status_of(row: VenueBooking) -> str:
        return db.get(VenueBooking, row.id).status

    assert status_of(approved) == BookingStatus.APPROVED
    assert status_of(clashes_with_approved) == BookingStatus.CANCELLED
    assert status_of(clashed_only_with_a_cancelled_one) == BookingStatus.PENDING
    assert status_of(first_of_two) == BookingStatus.PENDING
    assert status_of(second_of_two) == BookingStatus.CANCELLED
    assert status_of(other_venue) == BookingStatus.PENDING

    cancelled_ids = {clashes_with_approved.id, second_of_two.id}
    for row_id in cancelled_ids:
        assert db.get(VenueBooking, row_id).decision_reason
    audited = db.scalars(
        select(AuditLog.entity_id).where(
            AuditLog.action == "BOOKING_CANCELLED", AuditLog.entity_id.in_(cancelled_ids)
        )
    ).all()
    assert set(audited) == cancelled_ids

    # The widened constraint is in place: a new overlapping pending row is refused.
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            booking(_at(7, 16), _at(7, 17), created=6)
