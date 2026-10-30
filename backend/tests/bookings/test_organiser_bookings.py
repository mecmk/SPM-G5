"""Fix f7.1.2 (story 7.1) - GET /bookings/for-my-event/{event_id}.

The organiser of an event sees its venue bookings, read-only: which venue, where, for which
requirement, and when. Organisers do not hold ``bookings:read`` - ``/bookings/for-event`` checks
no ownership and returns Venue Staff's reasons and the hold's history - so this is its own
endpoint, behind ``bookings:read_own``, that answers only for the caller's own event.

AC1 The organiser sees each approved or pending booking of their event (Q91, CL-183 (3): a
    pending one shows a venue is being sought), with its venue name, location, requirement,
    start and end, and its setup and teardown. Closed bookings - rejected, withdrawn,
    cancelled, expired - hold nothing, so they are left out. Only those fields are returned.
AC2 Another organiser's event, or one that does not exist, is not found; every other role is
    refused, and an organiser is still refused ``/bookings/for-event``.
AC7 (CL-184, Q94-Q96) An open hold carries its expiry, so the page does not show it as confirmed,
    and a hold its event's confirmation completed says when; who changed the expiry, and why, is
    not returned. A booking marked under story 9.4 says when it was marked.

AC4, AC8 and AC9 are how the page shows these bookings: tests/e2e/events.spec.ts.

Conflict cases do not apply: the endpoint only reads.

Every case uses a fresh venue per booking and an event of Olivia's, so no seeded booking is in
the way of the one-booking-per-requirement index or the double-booking constraint.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.bookings.models import BookingStatus, VenueBooking
from app.bookings.router import EVENT_NOT_FOUND_MESSAGE
from app.events.models import Event, EventStatus
from tests.support.factories import make_booking, make_event, make_venue, make_venue_requirement
from tests.support.seed import Bookings, Events, Users

_STARTS_AT = datetime(2027, 3, 15, 1, 0, tzinfo=UTC)
_ENDS_AT = datetime(2027, 3, 15, 9, 0, tzinfo=UTC)

# Each requirement takes its own position on the event (uq_venue_requirements_event_position).
_positions = itertools.count()

_SAFE_FIELDS = {
    "id",
    "venue_name",
    "venue_location",
    "venue_requirement_name",
    "starts_at",
    "ends_at",
    "setup_minutes",
    "teardown_minutes",
    "status",
    "hold_expires_at",
    "hold_completed_at",
    "venue_unavailable_marked_at",
}


def _path(event_id: uuid.UUID) -> str:
    return f"/bookings/for-my-event/{event_id}"


def _event(db: Session, **overrides) -> Event:
    return make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=Users.COORDINATOR.id,
        **overrides,
    )


def _booking(
    db: Session,
    event: Event,
    *,
    status: str = BookingStatus.APPROVED,
    requirement: str | None = "Main venue",
    **overrides,
) -> VenueBooking:
    """A booking of a fresh venue on ``event``, for a requirement of its own unless
    ``requirement`` is None (an additional venue). An approved one is held for a week."""
    venue = make_venue(db, name=f"Hall {uuid.uuid4().hex[:6]}", location="Tower B, Level 3")
    requirement_id = (
        None
        if requirement is None
        else make_venue_requirement(db, event.id, position=next(_positions), name=requirement)
    )
    if status == BookingStatus.APPROVED:
        overrides.setdefault("decided_by_id", Users.VENUE_STAFF.id)
        overrides.setdefault("decided_at", datetime.now(UTC) - timedelta(days=1))
        overrides.setdefault("hold_expires_at", datetime.now(UTC) + timedelta(days=7))
    return make_booking(
        db,
        venue_id=venue.id,
        event_id=event.id,
        venue_requirement_id=requirement_id,
        starts_at=_STARTS_AT,
        ends_at=_ENDS_AT,
        status=status,
        **overrides,
    )


def _ids(response) -> set[str]:
    assert response.status_code == 200, response.text
    return {entry["id"] for entry in response.json()}


# --- AC1: the organiser sees their event's approved and pending bookings ---------------------
@pytest.mark.story("7.1", ac=1)
def test_the_organiser_sees_an_approved_booking_with_its_venue_requirement_and_times(
    organiser_client, db: Session
):
    event = _event(db)
    booking = _booking(db, event, requirement="Plenary hall")

    response = organiser_client.get(_path(event.id))

    assert response.status_code == 200, response.text
    [entry] = response.json()
    assert entry["id"] == str(booking.id)
    assert entry["venue_name"] == booking.venue.name
    assert entry["venue_location"] == "Tower B, Level 3"
    assert entry["venue_requirement_name"] == "Plenary hall"
    assert datetime.fromisoformat(entry["starts_at"]) == _STARTS_AT
    assert datetime.fromisoformat(entry["ends_at"]) == _ENDS_AT
    assert entry["setup_minutes"] == booking.setup_minutes
    assert entry["teardown_minutes"] == booking.teardown_minutes
    assert entry["status"] == BookingStatus.APPROVED


@pytest.mark.story("7.1", ac=1)
def test_a_pending_booking_is_shown_beside_an_approved_one(organiser_client, db: Session):
    event = _event(db)
    approved = _booking(db, event, requirement="Plenary hall")
    pending = _booking(db, event, status=BookingStatus.PENDING, requirement="Breakout room")

    response = organiser_client.get(_path(event.id))

    by_id = {entry["id"]: entry for entry in response.json()}
    assert set(by_id) == {str(approved.id), str(pending.id)}
    assert by_id[str(pending.id)]["status"] == BookingStatus.PENDING


@pytest.mark.story("7.1", ac=1)
@pytest.mark.parametrize(
    ("status", "extra"),
    [
        (BookingStatus.REJECTED, {"decision_reason": "The hall is closed."}),
        (BookingStatus.WITHDRAWN, {}),
        (BookingStatus.CANCELLED, {}),
        (BookingStatus.EXPIRED, {"hold_expires_at": datetime(2026, 10, 1, tzinfo=UTC)}),
    ],
)
def test_a_closed_booking_is_left_out(organiser_client, db: Session, status, extra):
    event = _event(db)
    live = _booking(db, event, requirement="Plenary hall")
    _booking(db, event, status=status, requirement="Breakout room", **extra)

    assert _ids(organiser_client.get(_path(event.id))) == {str(live.id)}


@pytest.mark.story("7.1", ac=1)
def test_an_additional_venue_has_no_requirement_name(organiser_client, db: Session):
    event = _event(db)
    _booking(db, event, requirement=None)

    [entry] = organiser_client.get(_path(event.id)).json()

    assert entry["venue_requirement_name"] is None


@pytest.mark.story("7.1", ac=1)
def test_an_event_with_no_bookings_has_an_empty_list(organiser_client, db: Session):
    event = _event(db)

    response = organiser_client.get(_path(event.id))

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.story("7.1", ac=1)
def test_a_hold_that_has_lapsed_is_not_shown_as_approved(organiser_client, db: Session):
    """Story 12.7 AC3: every booking endpoint expires lapsed holds before it answers, so a hold
    that lapsed an hour ago is EXPIRED by the time the list is read, and so left out."""
    event = _event(db)
    _booking(db, event, hold_expires_at=datetime.now(UTC) - timedelta(hours=1))

    assert _ids(organiser_client.get(_path(event.id))) == set()


@pytest.mark.story("7.1", ac=1)
def test_only_the_organisers_fields_are_returned(organiser_client, db: Session):
    """Venue Staff's reasons, the coordinator's suitability override and the hold's history are
    internal: none of them reaches the organiser."""
    event = _event(db)
    _booking(db, event, suitability_override_reason="Closest hall with a stage.")

    [entry] = organiser_client.get(_path(event.id)).json()

    assert set(entry) == _SAFE_FIELDS


# --- AC7: the hold, and a venue marked unavailable --------------------------------------------
@pytest.mark.story("7.1", ac=7)
def test_an_open_hold_carries_its_expiry(organiser_client, db: Session):
    event = _event(db)
    expires_at = datetime.now(UTC) + timedelta(days=3)
    _booking(db, event, hold_expires_at=expires_at)

    [entry] = organiser_client.get(_path(event.id)).json()

    assert datetime.fromisoformat(entry["hold_expires_at"]) == expires_at
    assert entry["hold_completed_at"] is None


@pytest.mark.story("7.1", ac=7)
def test_a_hold_its_events_confirmation_completed_says_when(organiser_client, db: Session):
    event = _event(db)
    completed_at = datetime.now(UTC) - timedelta(hours=2)
    _booking(db, event, hold_completed_at=completed_at)

    [entry] = organiser_client.get(_path(event.id)).json()

    assert datetime.fromisoformat(entry["hold_completed_at"]) == completed_at


@pytest.mark.story("7.1", ac=7)
def test_who_changed_a_holds_expiry_and_why_are_not_returned(organiser_client, db: Session):
    event = _event(db)
    _booking(
        db,
        event,
        hold_expiry_change_reason="The coordinator asked for two more days.",
        hold_expiry_changed_by_id=Users.VENUE_STAFF.id,
        hold_expiry_changed_at=datetime.now(UTC) - timedelta(hours=1),
    )

    [entry] = organiser_client.get(_path(event.id)).json()

    assert set(entry) == _SAFE_FIELDS


@pytest.mark.story("7.1", ac=7)
def test_a_booking_marked_unavailable_says_when(login_as):
    """Events.LANTERN_SHOWCASE is Omar's, its approved Exhibition Foyer booking marked "Venue
    unavailable - alternative needed" by the foyer's closure that day (story 9.4)."""
    client = login_as(Users.ORGANISER_2)

    by_id = {entry["id"]: entry for entry in client.get(_path(Events.LANTERN_SHOWCASE)).json()}

    assert by_id[str(Bookings.LANTERN_SHOWCASE_FOYER)]["venue_unavailable_marked_at"] is not None


# --- AC2: only the event's own organiser -----------------------------------------------------
@pytest.mark.story("7.1", ac=2)
def test_another_organisers_event_is_not_found(organiser_client, db: Session):
    """Events.APPROVED is Omar's, with an approved and a pending booking."""
    response = organiser_client.get(_path(Events.APPROVED))

    assert response.status_code == 404
    assert response.json() == {"detail": EVENT_NOT_FOUND_MESSAGE}


@pytest.mark.story("7.1", ac=2)
def test_its_own_organiser_sees_a_seeded_events_bookings(login_as):
    client = login_as(Users.ORGANISER_2)

    ids = _ids(client.get(_path(Events.APPROVED)))

    assert {str(Bookings.APPROVED_GRAND_HALL), str(Bookings.PENDING_SEMINAR_ROOM)} <= ids


@pytest.mark.story("7.1", ac=2)
def test_an_unknown_event_is_not_found(organiser_client):
    response = organiser_client.get(_path(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json() == {"detail": EVENT_NOT_FOUND_MESSAGE}


@pytest.mark.story("7.1", ac=2)
def test_signed_out_visitors_are_refused(client, db: Session):
    event = _event(db)

    response = client.get(_path(event.id))

    assert response.status_code == 401


@pytest.mark.story("7.1", ac=2)
@pytest.mark.parametrize(
    "user",
    [user for user in Users.ONE_PER_ROLE if user.role != "EVENT_ORGANISER"],
    ids=lambda user: user.role,
)
def test_other_roles_are_refused(login_as, db: Session, user):
    """Coordinators and Venue Staff read bookings through ``/bookings/for-event`` instead."""
    event = _event(db)
    client = login_as(user)

    response = client.get(_path(event.id))

    assert response.status_code == 403


@pytest.mark.story("7.1", ac=2)
def test_an_organiser_is_still_refused_every_events_bookings(organiser_client, db: Session):
    """``/bookings/for-event`` checks no ownership, so organisers must never hold
    ``bookings:read``."""
    event = _event(db)

    response = organiser_client.get(f"/bookings/for-event/{event.id}")

    assert response.status_code == 403
