"""Set-up shared by story 12.6's backend tests (a replacement for a booking whose venue became
unavailable): a Planning event with an approved booking that Venue Staff's closure has marked
"Venue unavailable - alternative needed", and the rows a replacement leaves behind.

The columns 12.6 adds to ``venue_bookings`` are written in SQL here, never through the ORM, so a
test can place a replacement in any state the way ``make_venue_requirement`` writes a requirement:

* ``replaces_booking_id`` - on a replacement, the booking it replaces (composite FK with
  ``event_id``, so the two share an event);
* ``replaces_live_original`` - on a replacement, set when it is requested; the one-per-requirement
  index leaves a PENDING row with it set out, and a trigger clears it on a PENDING replacement when
  the original stops holding (a decided replacement keeps what it had);
* ``replaced_by_booking_id`` - on an original, the replacement that released it (CANCELLED only).

Nothing here is a fixture: each helper takes the session.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.bookings.models import BookingStatus, VenueBooking
from app.events.models import Event, EventStatus
from app.venues.models import Venue
from tests.support.factories import (
    approval_payload,
    make_booking,
    make_event,
    make_venue,
    make_venue_requirement,
)
from tests.support.seed import Users

BOOKINGS_PATH = "/bookings"
SETUP_MINUTES = 30
TEARDOWN_MINUTES = 30


def when(days: int = 45, hour: int = 2) -> datetime:
    """A moment ``days`` from now at ``hour`` UTC (10:00 in Singapore for the default): far enough
    ahead that no hold, setup or expiry rule has started."""
    return (datetime.now(UTC) + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )


def hall(db: Session, **overrides) -> Venue:
    """A venue that suits the scenario's requirement (40 people, a classroom): no hours recorded,
    so it is never closed, and no facilities required."""
    return make_venue(
        db,
        name=overrides.pop("name", f"Replacement Hall {uuid.uuid4().hex[:8]}"),
        capacity=overrides.pop("capacity", 100),
        layouts={"CLASSROOM": None},
        **overrides,
    )


@dataclass
class Scenario:
    """An event, its approved (or other) booking, and a second venue free for the same period."""

    event: Event
    requirement_id: uuid.UUID | None
    original: VenueBooking
    original_venue: Venue
    alternative: Venue
    starts_at: datetime
    ends_at: datetime


def make_scenario(
    db: Session,
    *,
    status: str = BookingStatus.APPROVED,
    marked: bool = True,
    additional: bool = False,
    event_status: str = EventStatus.PLANNING,
    coordinator_id: uuid.UUID = Users.COORDINATOR.id,
    days: int = 45,
    **booking_overrides,
) -> Scenario:
    """The scene of 12.6: a Planning event for 40 people, assigned to Chloe, 10:00-16:00 in
    Singapore ``days`` from now, with one booking of a venue of its own - 30 minutes of setup and
    teardown, approved with its hold running until two days before - for its one requirement
    ("Main hall"), or an additional venue with ``additional``. ``marked`` is the 9.4 mark.
    ``alternative`` is a second venue that suits the requirement and is free for the period."""
    starts_at, ends_at = when(days, 2), when(days, 8)
    event = make_event(
        db,
        status=event_status,
        assigned_coordinator_id=coordinator_id,
        starts_at=starts_at,
        ends_at=ends_at,
        expected_attendance=40,
    )
    requirement_id = None
    if not additional:
        requirement_id = make_venue_requirement(
            db,
            event.id,
            name="Main hall",
            capacity=40,
            starts_at=starts_at,
            ends_at=ends_at,
            layout_code="CLASSROOM",
        )
    original_venue = hall(db, name=f"Unavailable Hall {uuid.uuid4().hex[:8]}")
    is_approved = status in (BookingStatus.APPROVED, BookingStatus.CANCELLED, BookingStatus.EXPIRED)
    fields = {
        "venue_requirement_id": requirement_id,
        "setup_minutes": SETUP_MINUTES,
        "teardown_minutes": TEARDOWN_MINUTES,
        "expected_attendance": 40,
        "required_layout_code": None if additional else "CLASSROOM",
        "venue_unavailable_marked_at": datetime.now(UTC) - timedelta(hours=1) if marked else None,
    }
    if is_approved:
        fields |= {
            "decided_by_id": Users.VENUE_STAFF.id,
            "decided_at": datetime.now(UTC) - timedelta(days=1),
            "hold_expires_at": starts_at - timedelta(days=2),
        }
    original = make_booking(
        db,
        event_id=event.id,
        venue_id=original_venue.id,
        starts_at=starts_at,
        ends_at=ends_at,
        status=status,
        **(fields | booking_overrides),
    )
    return Scenario(
        event=event,
        requirement_id=requirement_id,
        original=original,
        original_venue=original_venue,
        alternative=hall(db),
        starts_at=starts_at,
        ends_at=ends_at,
    )


def replace(client, original_id: uuid.UUID, venue: Venue, **extra):
    """``POST /bookings/{id}/replacements``: ask for ``venue`` to replace the booking."""
    return client.post(
        f"{BOOKINGS_PATH}/{original_id}/replacements", json={"venue_id": str(venue.id), **extra}
    )


def approve(client, booking_id: uuid.UUID, **extra):
    """``POST /bookings/{id}/approve`` as Venue Staff, with a valid hold expiry."""
    return client.post(f"{BOOKINGS_PATH}/{booking_id}/approve", json=approval_payload() | extra)


def created(response) -> dict:
    assert response.status_code == 201, response.text
    return response.json()


def add_pending_replacement(
    db: Session, scenario: Scenario, *, venue: Venue | None = None, status: str = "PENDING"
) -> VenueBooking:
    """A replacement for the scenario's original as the API leaves it: a booking of ``venue`` (the
    scenario's alternative) for the same requirement and period, linked to the original, with the
    carve-out on while it is pending. One INSERT, so a schema without the columns fails here, with
    the missing column - not further on."""
    target = scenario.alternative if venue is None else venue
    original = scenario.original
    row = db.execute(
        text(
            "INSERT INTO venue_bookings (event_id, venue_id, requested_by_id, starts_at, ends_at,"
            " setup_minutes, teardown_minutes, expected_attendance, required_layout_code,"
            " venue_requirement_id, status, replaces_booking_id, replaces_live_original)"
            " VALUES (:event_id, :venue_id, :requested_by_id, :starts_at, :ends_at, :setup,"
            " :teardown, :attendance, :layout, :requirement_id, :status, :original_id, TRUE)"
            " RETURNING id"
        ),
        {
            "event_id": original.event_id,
            "venue_id": target.id,
            "requested_by_id": Users.COORDINATOR.id,
            "starts_at": original.starts_at,
            "ends_at": original.ends_at,
            "setup": original.setup_minutes,
            "teardown": original.teardown_minutes,
            "attendance": original.expected_attendance,
            "layout": original.required_layout_code,
            "requirement_id": original.venue_requirement_id,
            "status": status,
            "original_id": original.id,
        },
    ).scalar_one()
    db.expire_all()
    return db.get(VenueBooking, row)


def column(db: Session, booking_id: uuid.UUID, name: str):
    """One column of a booking, read in SQL after the trigger has written it, so the value is the
    database's and not a session's stale one."""
    db.expire_all()
    return db.execute(
        text(f"SELECT {name} FROM venue_bookings WHERE id = :id"), {"id": booking_id}
    ).scalar_one()


def set_status(db: Session, booking_id: uuid.UUID, status: str) -> None:
    """Move a booking to ``status`` the way a sweep, a release or a cancellation would, in SQL.
    An expired booking keeps the expiry it lapsed at (ck_venue_bookings_hold_expiry)."""
    db.execute(
        text(
            "UPDATE venue_bookings SET status = :status,"
            " hold_expires_at = COALESCE(hold_expires_at, now()) WHERE id = :id"
        ),
        {"id": booking_id, "status": status},
    )
    db.expire_all()


def end_the_closure(login_as, scene: Scenario) -> None:
    """Venue Staff close the original's venue over the booking and then remove that closure, as
    9.4 AC6 allows while it has not started: the booking's mark clears. Leaves the session signed
    in as Venue Staff."""
    staff = login_as(Users.VENUE_STAFF)
    url = f"/venues/{scene.original_venue.id}/unavailability"
    period = staff.post(
        url,
        json={
            "starts_at": (scene.starts_at - timedelta(days=1)).isoformat(),
            "ends_at": (scene.ends_at + timedelta(days=1)).isoformat(),
            "reason": "MAINTENANCE",
            "description": "Floor resurfacing",
        },
    )
    assert period.status_code == 201, period.text
    assert staff.delete(f"{url}/{period.json()['id']}").status_code == 204


def notifications_of(db: Session, recipient_id: uuid.UUID, *, event_id: uuid.UUID) -> list:
    """The notifications ``recipient_id`` holds about ``event_id``, oldest first."""
    from app.notifications.models import Notification

    db.expire_all()
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.recipient_id == recipient_id, Notification.event_id == event_id)
            .order_by(Notification.created_at, Notification.id)
        )
    )


def purge(engine, *, event_ids, venue_ids, period_ids=()) -> None:
    """Remove what a test that commits (two sessions racing) left behind: the notifications and
    audit rows its bookings wrote, the bookings, requirements and events, the closures and
    venues. A booking and its replacement go in one statement, so their link never blocks it."""
    from sqlalchemy.orm import Session as OrmSession

    with OrmSession(engine) as session:
        booking_ids = (
            session.execute(
                text("SELECT id FROM venue_bookings WHERE event_id = ANY(:events)"),
                {"events": list(event_ids)},
            )
            .scalars()
            .all()
        )
        entity_ids = list(booking_ids) + list(period_ids)
        session.execute(
            text("DELETE FROM notifications WHERE event_id = ANY(:events)"),
            {"events": list(event_ids)},
        )
        session.execute(
            text("DELETE FROM audit_log WHERE entity_id = ANY(:ids)"), {"ids": entity_ids}
        )
        session.execute(
            text("DELETE FROM venue_bookings WHERE event_id = ANY(:events)"),
            {"events": list(event_ids)},
        )
        session.execute(
            text("DELETE FROM venue_unavailability_periods WHERE id = ANY(:ids)"),
            {"ids": list(period_ids)},
        )
        session.execute(
            text("DELETE FROM venue_requirements WHERE event_id = ANY(:events)"),
            {"events": list(event_ids)},
        )
        session.execute(
            text("DELETE FROM events WHERE id = ANY(:events)"), {"events": list(event_ids)}
        )
        session.execute(text("DELETE FROM venues WHERE id = ANY(:ids)"), {"ids": list(venue_ids)})
        session.commit()
