"""Story 12.2 - be: track and withdraw a venue booking request.

AC2 A pending request can be withdrawn. It leaves the Venue Staff queue, its hold on the venue
    is released at once, and every active Venue Staff member is notified.
AC3 The status update, hold release and notification all happen together, inside the same
    service call - never partially applied.
AC5 A new request can be raised once the withdrawn one no longer holds the venue (the other
    half of AC5, "withdrawn requests stay in the list as history", is already proven generically
    by ``test_booking_for_event.py``, which returns every status - nothing new to test there).
AC6 Only the coordinator assigned to the request's event may withdraw it - a relationship rule,
    the same shape as 12.1 AC4's ``NotAssignedCoordinator``, not a role check (every coordinator
    holds ``bookings:request``).
AC7 Only a PENDING request may be withdrawn: approved, rejected, already-withdrawn and cancelled
    requests are all refused with 409, naming the current status.
AC8 A withdrawal racing a Venue Staff decision on the same request: whichever lands first wins,
    the other is refused. Reuses the exact ``get_booking_for_decision`` row lock 13.2/13.2.1
    already use for decide-vs-decide races, so this is a new caller of an existing mechanism,
    not a new one.

AC1 (viewing the full request and its decision reason) and AC4 (visual distinctness, the empty
state) are UI acceptance criteria proven at e2e (tests/e2e/booking-requests.spec.ts), not
repeated here.

Excluded, with reason:
* "Venue Staff outside the venue's responsibility scope" - as in test_approve_booking.py,
  BOOKINGS_DECIDE is role-wide; there is no per-venue responsibility table to test.
* A genuine multi-connection concurrency test (two simultaneous requests against the same
  booking) - same reasoning as test_approve_booking.py: the guard is the existing
  ``SELECT ... FOR UPDATE`` row lock, which a single-session test cannot meaningfully race.
  ``test_withdrawing_after_venue_staff_already_decided_is_refused`` below proves the guard the
  lock protects, the same way ``test_approving_after_rejecting_is_refused`` already does for
  13.2/13.2.1.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

import app.bookings.service as bookings_service
from app.bookings.models import BookingStatus
from app.events.models import Event, EventStatus
from tests.support.factories import make_booking, make_event, make_venue_requirement
from tests.support.seed import Bookings, Users, Venues

_SGT = timezone(timedelta(hours=8))


def _event_seminar_room_suits(db: Session) -> Event:
    """Chloe's event that Seminar Room 2.1 suits (story 11.1: 60 people, Classroom, a projector),
    at the time the seeded pending request holds the room (25 Nov 2026, 13:00-18:00, held
    12:30-18:15). Nimbus itself does not fit the room, and story 11.1 refuses a venue that does
    not suit unless the request carries a justification."""
    event = make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=datetime(2026, 11, 25, 13, 0, tzinfo=_SGT),
        ends_at=datetime(2026, 11, 25, 18, 0, tzinfo=_SGT),
        expected_attendance=60,
    )
    make_venue_requirement(
        db, event.id, capacity=60, layout_code="CLASSROOM", facilities=(("PROJECTOR", None, None),)
    )
    return event


# --- AC2/AC3: withdrawal records the coordinator and time, releases the hold, notifies -------
@pytest.mark.story("12.2", ac=2)
def test_the_assigned_coordinator_can_withdraw_a_pending_request(coordinator_client, db: Session):
    before = datetime.now(timezone.utc)

    response = coordinator_client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/withdraw")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == BookingStatus.WITHDRAWN
    assert body["decided_by_id"] == str(Users.COORDINATOR.id)
    decided_at = datetime.fromisoformat(body["decided_at"])
    assert before <= decided_at <= datetime.now(timezone.utc)


@pytest.mark.story("12.2", ac=3)
def test_withdrawing_is_recorded_in_the_audit_log(coordinator_client, db: Session):
    coordinator_client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/withdraw")

    row = db.execute(
        text(
            "SELECT actor_id FROM audit_log WHERE action = 'BOOKING_WITHDRAWN' AND entity_id = :id"
        ),
        {"id": Bookings.PENDING_SEMINAR_ROOM},
    ).one()
    assert row.actor_id == Users.COORDINATOR.id


@pytest.mark.story("12.2", ac=3)
def test_a_failed_withdrawal_leaves_the_booking_and_hold_unchanged(
    coordinator_client, db: Session, monkeypatch
):
    """If writing the notification fails unexpectedly, the status change must not have landed
    either - AC3's "all happen together" is only true if a failure partway leaves nothing
    applied."""

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated failure notifying Venue Staff")

    monkeypatch.setattr(bookings_service, "_notify_venue_staff_of_withdrawal", _boom)

    with pytest.raises(RuntimeError):
        coordinator_client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/withdraw")
    db.rollback()  # mirrors app.db.get_db's real teardown

    row = db.execute(
        text("SELECT status, decided_by_id, decided_at FROM venue_bookings WHERE id = :id"),
        {"id": Bookings.PENDING_SEMINAR_ROOM},
    ).one()
    assert row.status == BookingStatus.PENDING
    assert row.decided_by_id is None
    assert row.decided_at is None
    assert (
        db.execute(
            text(
                "SELECT count(*) FROM audit_log "
                "WHERE action = 'BOOKING_WITHDRAWN' AND entity_id = :id"
            ),
            {"id": Bookings.PENDING_SEMINAR_ROOM},
        ).scalar()
        == 0
    )


@pytest.mark.story("12.2", ac=2)
def test_withdrawing_releases_the_hold_and_a_new_request_can_be_raised(
    coordinator_client, db: Session
):
    """Since s12.1 a pending request holds its venue, so a fresh request for the same slot is
    refused while it stands. Withdrawing frees Seminar Room for that slot at once - the same
    proof ``test_rejecting_a_held_request_releases_the_venue`` uses for rejection (AC5's "a new
    request can be raised" is the same underlying guarantee, shown from the coordinator's side).
    The new request comes from an event the room suits (story 11.1), at a time the withdrawn
    request held."""
    event = _event_seminar_room_suits(db)
    withdrawn = coordinator_client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/withdraw")
    assert withdrawn.status_code == 200

    raised = coordinator_client.post(
        "/bookings",
        json={"event_id": str(event.id), "venue_id": str(Venues.SEMINAR_ROOM)},
    )
    assert raised.status_code == 201


@pytest.mark.story("12.2", ac=2)
def test_withdrawing_notifies_every_active_venue_staff_member(coordinator_client, db: Session):
    """Vera (active Venue Staff) is told; Ian (also role VENUE_STAFF, but seeded inactive) is
    not - the same "role-wide, active only" scope the pending queue itself already uses."""
    coordinator_client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/withdraw")

    recipients = set(
        db.execute(
            text(
                "SELECT recipient_id FROM notifications "
                "WHERE notification_type = 'BOOKING_WITHDRAWN' "
                "AND related_entity_type = 'venue_booking' "
                "AND related_entity_id = :id"
            ),
            {"id": Bookings.PENDING_SEMINAR_ROOM},
        ).scalars()
    )
    assert recipients == {Users.VENUE_STAFF.id}


# --- AC6: only the assigned coordinator may withdraw -----------------------------------------
@pytest.mark.story("12.2", ac=6)
def test_a_different_coordinator_cannot_withdraw_someone_elses_request(client, db: Session):
    """Carl is a coordinator - he holds bookings:request - but this request belongs to Chloe's
    event."""
    client.login(Users.COORDINATOR_2)

    response = client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/withdraw")

    assert response.status_code == 403
    db.expire_all()
    row = db.execute(
        text("SELECT status FROM venue_bookings WHERE id = :id"),
        {"id": Bookings.PENDING_SEMINAR_ROOM},
    ).one()
    assert row.status == BookingStatus.PENDING


@pytest.mark.story("12.2", ac=6)
@pytest.mark.parametrize(
    "user",
    [Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda u: u.role,
)
def test_other_roles_cannot_withdraw_a_booking(client, user):
    client.login(user)
    response = client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/withdraw")
    assert response.status_code == 403


@pytest.mark.story("12.2", ac=6)
def test_signed_out_visitors_cannot_withdraw_a_booking(client):
    response = client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/withdraw")
    assert response.status_code == 401


# --- AC7: only a PENDING request may be withdrawn --------------------------------------------
@pytest.mark.story("12.2", ac=7)
@pytest.mark.parametrize(
    "status",
    [
        BookingStatus.APPROVED,
        BookingStatus.REJECTED,
        BookingStatus.WITHDRAWN,
        BookingStatus.CANCELLED,
    ],
)
def test_withdrawing_a_request_that_is_not_pending_is_refused(
    coordinator_client, db: Session, status
):
    booking = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        status=status,
        starts_at=datetime(2027, 1, 10, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 1, 10, 11, 0, tzinfo=timezone.utc),
    )

    response = coordinator_client.post(f"/bookings/{booking.id}/withdraw")

    assert response.status_code == 409
    assert status in response.json()["detail"]
    db.expire_all()
    row = db.execute(
        text("SELECT status FROM venue_bookings WHERE id = :id"), {"id": booking.id}
    ).one()
    assert row.status == status


@pytest.mark.story("12.2", ac=7)
def test_withdrawing_a_missing_booking_is_404(coordinator_client):
    assert coordinator_client.post(f"/bookings/{uuid.uuid4()}/withdraw").status_code == 404


@pytest.mark.story("12.2", ac=7)
def test_withdrawing_with_a_malformed_booking_id_is_422(coordinator_client):
    assert coordinator_client.post("/bookings/not-a-uuid/withdraw").status_code == 422


# --- AC8: a withdrawal racing a Venue Staff decision --------------------------------------------
@pytest.mark.story("12.2", ac=8)
def test_withdrawing_after_venue_staff_already_decided_is_refused(client, db: Session):
    """Carl is the assigned coordinator for this event - the withdrawal is only ever refused for
    the AC8 reason (a decision already landed), never AC6's. Mirrors
    ``test_approving_after_rejecting_is_refused``'s sequential proof of the same row lock."""
    client.login(Users.VENUE_STAFF)
    approved = client.post(f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/approve")
    assert approved.status_code == 200

    client.login(Users.COORDINATOR_2)
    response = client.post(f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/withdraw")

    assert response.status_code == 409
    assert BookingStatus.APPROVED in response.json()["detail"]
