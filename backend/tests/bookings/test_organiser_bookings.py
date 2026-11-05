"""Fix f7.1.2 (story 7.1) - GET /bookings/for-my-event/{event_id}.

The organiser of an event sees its venue bookings, read-only: which venue, where, for which
requirement, and when. Organisers do not hold ``bookings:read`` - ``/bookings/for-event`` checks
no ownership and returns Venue Staff's reasons and the hold's history - so this is its own
endpoint, behind ``bookings:read_own``, that answers only for the caller's own event.

AC4 The organiser sees each approved or pending booking of their event (Q91, CL-183 (3): a
    pending one shows a venue is being sought), with its venue name, location, requirement,
    start and end, its setup and teardown, and when it was requested (f21.2.1). Only those
    fields are returned.
AC5 Rejected, withdrawn, cancelled and expired bookings are not shown to the organiser, except
    the cancelled ones AC10 names. (f7.1.2, CL-183; 9.5, CL-194; f7.1.3, CL-210)
AC7 An approved booking whose hold is still open (12.7 AC1) is not shown as confirmed: it says the
    venue is held for the event until the event is confirmed or the hold expires, with the expiry
    date and time, as the coordinator's card does. Who changed the expiry, and why, is not shown.
    Nothing is marked "Venue unavailable – alternative needed" any more (9.5 AC7): a booking a
    venue closure ends is rejected or cancelled, so it leaves this section (AC5), and the
    organiser learns of it from the closure's notice (9.5 AC4). A cancelled one shows again as
    AC10 says. (f7.1.2, CL-184; 9.5, CL-194)
AC10 (f7.1.3, CL-210) A booking the safety review released (21.3), the coordinator cancelled
    (12.8) or a venue closure cancelled (9.5) is returned too, Cancelled, with its cause and why:
    the finding's required change or the coordinator's reason, or the closure's reason but not
    its description. Who released it is not returned.
AC6 Another organiser's event, or one that does not exist, is not found; every other role is
    refused, and an organiser is still refused ``/bookings/for-event``.
AC11 A request a venue closure rejected stays hidden, and so does every other cancelled booking:
    replaced (12.6), released by an approved change (19.2), or released with its event (6.2).

The backlog numbers these as 7.1's own ACs since CL-183; f7.1.2 first called AC4 and AC6 its
AC1 and AC2. How the page shows the bookings (AC4, AC8, AC9, AC10) is tests/e2e/events.spec.ts.

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

from app.bookings.models import BookingStatus, ReleaseCause, VenueBooking
from app.bookings.router import EVENT_NOT_FOUND_MESSAGE
from app.events.models import Event, EventStatus
from app.venues.models import VenueImage
from tests.support.factories import make_booking, make_event, make_venue, make_venue_requirement
from tests.support.seed import Bookings, Events, Users

_STARTS_AT = datetime(2027, 3, 15, 1, 0, tzinfo=UTC)
_ENDS_AT = datetime(2027, 3, 15, 9, 0, tzinfo=UTC)

# Story 9.5 AC2: the closure's description, which only staff see.
_CLOSURE_DESCRIPTION = "Floor resurfacing"

# Each requirement takes its own position on the event (uq_venue_requirements_event_position).
_positions = itertools.count()

_SAFE_FIELDS = {
    "id",
    "venue_name",
    "venue_location",
    "venue_cover_image_url",
    # Fix f13.2.1.1 (13.2.1 AC7): the venue's capacity and the booked layout's.
    "venue_capacity",
    "layout_name",
    "layout_capacity",
    "venue_requirement_name",
    "starts_at",
    "ends_at",
    "setup_minutes",
    "teardown_minutes",
    "status",
    "hold_expires_at",
    "hold_completed_at",
    "release_cause",
    "release_reason",
    "closure_reason",
    # Fix f21.2.1: when it was requested, so the page can tell a booking a safety review saw from
    # one requested after it (story 21.2 AC23/AC24).
    "created_at",
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


# --- AC4, AC5: the organiser sees their event's approved and pending bookings ----------------
@pytest.mark.story("7.1", ac=4)
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


@pytest.mark.story("7.1", ac=4)
def test_a_pending_booking_is_shown_beside_an_approved_one(organiser_client, db: Session):
    event = _event(db)
    approved = _booking(db, event, requirement="Plenary hall")
    pending = _booking(db, event, status=BookingStatus.PENDING, requirement="Breakout room")

    response = organiser_client.get(_path(event.id))

    by_id = {entry["id"]: entry for entry in response.json()}
    assert set(by_id) == {str(approved.id), str(pending.id)}
    assert by_id[str(pending.id)]["status"] == BookingStatus.PENDING


@pytest.mark.story("7.1", ac=5)
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


@pytest.mark.story("7.1", ac=4)
def test_an_additional_venue_has_no_requirement_name(organiser_client, db: Session):
    event = _event(db)
    _booking(db, event, requirement=None)

    [entry] = organiser_client.get(_path(event.id)).json()

    assert entry["venue_requirement_name"] is None


@pytest.mark.story("7.1", ac=4)
def test_an_event_with_no_bookings_has_an_empty_list(organiser_client, db: Session):
    event = _event(db)

    response = organiser_client.get(_path(event.id))

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.story("7.1", ac=5)
def test_a_hold_that_has_lapsed_is_not_shown_as_approved(organiser_client, db: Session):
    """Story 12.7 AC3: every booking endpoint expires lapsed holds before it answers, so a hold
    that lapsed an hour ago is EXPIRED by the time the list is read, and so left out."""
    event = _event(db)
    _booking(db, event, hold_expires_at=datetime.now(UTC) - timedelta(hours=1))

    assert _ids(organiser_client.get(_path(event.id))) == set()


@pytest.mark.story("7.1", ac=4)
def test_only_the_organisers_fields_are_returned(organiser_client, db: Session):
    """Venue Staff's reasons, the coordinator's suitability override and the hold's history are
    internal: none of them reaches the organiser."""
    event = _event(db)
    _booking(db, event, suitability_override_reason="Closest hall with a stage.")

    [entry] = organiser_client.get(_path(event.id)).json()

    assert set(entry) == _SAFE_FIELDS


@pytest.mark.story("7.1", ac=4)
def test_a_booking_carries_its_venues_first_picture(organiser_client, db: Session):
    """The card shows the same picture as the venue's catalogue card, or none if it has none."""
    event = _event(db)
    with_picture = _booking(db, event, requirement="Main hall")
    without_picture = _booking(db, event, requirement="Side room")
    db.add_all(
        [
            VenueImage(venue_id=with_picture.venue_id, url="/images/venues/b.jpg", position=2),
            VenueImage(venue_id=with_picture.venue_id, url="/images/venues/a.jpg", position=1),
        ]
    )
    db.flush()
    db.expire_all()

    entries = organiser_client.get(_path(event.id)).json()

    by_id = {entry["id"]: entry for entry in entries}
    assert by_id[str(with_picture.id)]["venue_cover_image_url"] == "/images/venues/a.jpg"
    assert by_id[str(without_picture.id)]["venue_cover_image_url"] is None


# --- AC7: the hold ------------------------------------------------------------------------------
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


# --- AC10, AC11: bookings released by the safety review, the coordinator or a venue closure ---
def _released(db: Session, event: Event, cause: str, **overrides) -> VenueBooking:
    """A booking of ``event`` that ``cause`` released, as ``release_booking`` leaves one."""
    if cause == ReleaseCause.VENUE_UNAVAILABLE:
        overrides.setdefault("closure_reason", "MAINTENANCE")
        overrides.setdefault("closure_description", _CLOSURE_DESCRIPTION)
    return _booking(
        db,
        event,
        status=BookingStatus.CANCELLED,
        requirement="Breakout room",
        decided_by_id=Users.VENUE_STAFF.id,
        decided_at=datetime.now(UTC) - timedelta(days=2),
        cancelled_at=datetime.now(UTC) - timedelta(hours=1),
        release_cause=cause,
        released_by_id=Users.SAFETY_OFFICER.id,
        **overrides,
    )


@pytest.mark.story("7.1", ac=10)
@pytest.mark.parametrize(
    ("cause", "reason"),
    [
        (ReleaseCause.SAFETY_REVIEW, "Move the breakout to a room with a second fire exit."),
        (ReleaseCause.COORDINATOR_CANCELLED, "The client moved the breakout online."),
    ],
    ids=["safety review", "coordinator"],
)
def test_a_released_booking_is_shown_as_cancelled_with_its_reason(
    organiser_client, db: Session, cause, reason
):
    event = _event(db)
    live = _booking(db, event, requirement="Plenary hall")
    released = _released(db, event, cause, release_reason=reason)

    by_id = {entry["id"]: entry for entry in organiser_client.get(_path(event.id)).json()}

    assert set(by_id) == {str(live.id), str(released.id)}
    entry = by_id[str(released.id)]
    assert entry["status"] == BookingStatus.CANCELLED
    assert entry["release_cause"] == cause
    assert entry["release_reason"] == reason
    assert entry["closure_reason"] is None
    assert by_id[str(live.id)]["release_cause"] is None


@pytest.mark.story("7.1", ac=10)
def test_a_booking_a_closure_cancelled_is_shown_with_the_closures_reason_only(
    organiser_client, db: Session
):
    event = _event(db)
    cancelled = _released(db, event, ReleaseCause.VENUE_UNAVAILABLE)

    response = organiser_client.get(_path(event.id))

    [entry] = response.json()
    assert entry["id"] == str(cancelled.id)
    assert entry["status"] == BookingStatus.CANCELLED
    assert entry["release_cause"] == ReleaseCause.VENUE_UNAVAILABLE
    assert entry["closure_reason"] == "MAINTENANCE"
    assert entry["release_reason"] is None
    assert _CLOSURE_DESCRIPTION not in response.text


@pytest.mark.story("7.1", ac=10)
def test_who_released_a_booking_is_not_returned(organiser_client, db: Session):
    event = _event(db)
    _released(db, event, ReleaseCause.SAFETY_REVIEW, release_reason="Add a second fire exit.")

    [entry] = organiser_client.get(_path(event.id)).json()

    assert set(entry) == _SAFE_FIELDS


@pytest.mark.story("7.1", ac=11)
@pytest.mark.parametrize(
    "cause",
    [ReleaseCause.REPLACED, ReleaseCause.CHANGE_APPROVED, ReleaseCause.EVENT_CANCELLED],
)
def test_a_booking_cancelled_any_other_way_stays_hidden(organiser_client, db: Session, cause):
    event = _event(db)
    live = _booking(db, event, requirement="Plenary hall")
    _released(db, event, cause)

    assert _ids(organiser_client.get(_path(event.id))) == {str(live.id)}


@pytest.mark.story("7.1", ac=11)
def test_a_request_a_closure_rejected_stays_hidden(organiser_client, db: Session):
    """Story 9.5 AC2 rejects a pending request on a closed day and records the closure on it."""
    event = _event(db)
    live = _booking(db, event, requirement="Plenary hall")
    _booking(
        db,
        event,
        status=BookingStatus.REJECTED,
        requirement="Breakout room",
        decision_reason="Venue closed: Maintenance",
        closure_reason="MAINTENANCE",
        closure_description=_CLOSURE_DESCRIPTION,
    )

    assert _ids(organiser_client.get(_path(event.id))) == {str(live.id)}


# --- AC6: only the event's own organiser -----------------------------------------------------
@pytest.mark.story("7.1", ac=6)
def test_another_organisers_event_is_not_found(organiser_client, db: Session):
    """Events.APPROVED is Omar's, with an approved and a pending booking."""
    response = organiser_client.get(_path(Events.APPROVED))

    assert response.status_code == 404
    assert response.json() == {"detail": EVENT_NOT_FOUND_MESSAGE}


@pytest.mark.story("7.1", ac=4)
def test_its_own_organiser_sees_a_seeded_events_bookings(login_as):
    client = login_as(Users.ORGANISER_2)

    ids = _ids(client.get(_path(Events.APPROVED)))

    assert {str(Bookings.APPROVED_GRAND_HALL), str(Bookings.PENDING_SEMINAR_ROOM)} <= ids


@pytest.mark.story("7.1", ac=6)
def test_an_unknown_event_is_not_found(organiser_client):
    response = organiser_client.get(_path(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json() == {"detail": EVENT_NOT_FOUND_MESSAGE}


@pytest.mark.story("7.1", ac=6)
def test_signed_out_visitors_are_refused(client, db: Session):
    event = _event(db)

    response = client.get(_path(event.id))

    assert response.status_code == 401


@pytest.mark.story("7.1", ac=6)
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


@pytest.mark.story("7.1", ac=6)
def test_an_organiser_is_still_refused_every_events_bookings(organiser_client, db: Session):
    """``/bookings/for-event`` checks no ownership, so organisers must never hold
    ``bookings:read``."""
    event = _event(db)

    response = organiser_client.get(f"/bookings/for-event/{event.id}")

    assert response.status_code == 403
