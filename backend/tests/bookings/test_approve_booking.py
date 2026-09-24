"""Story 13.2 - be: approve venue booking request.

AC1 Approval sets the booking to confirmed (APPROVED) and records the approver and time.
AC2 The confirmed period is marked unavailable on the venue's calendar.
AC3 The outcome is visible to the requesting coordinator.
AC4 Approval is refused where the period conflicts with an existing confirmed booking.

AC2 is proven at the mechanism story 14.2 already built and tested (the exclusion constraint
keys off ``status``): once this endpoint flips a booking to APPROVED, that same constraint and
``find_conflicting_booking`` treat its held period as occupied - see
``test_a_newly_approved_booking_blocks_a_later_overlapping_request`` below. There is no
calendar UI to click through yet (stories 9.2 / 14.3), so AC2 stops at that backend proof, not
an end-to-end one.

AC4's conflict *matrix* (which periods count as overlapping, boundary touches, different
venues, etc.) is story 14.2's ``tests/bookings/test_booking_conflicts.py`` and is not repeated
here - this file only proves the approve endpoint reaches that same, already-proven mechanism
and translates its refusal into an HTTP response.

Excluded, with reason:
* "Venue Staff outside the venue's responsibility scope" - there is no per-venue staff
  responsibility table in the schema (checked backend/db/migrations/001_initial_schema.sql);
  BOOKINGS_DECIDE is a role-wide permission today, same as VENUES_MANAGE. Nothing to test.
* A genuine multi-connection concurrency test (two simultaneous approvals of the *same*
  booking) - the fix is a ``SELECT ... FOR UPDATE`` row lock, which a single-session test can't
  exercise meaningfully. The sequential repeated-approval tests below prove the guard the lock
  protects; the locking itself is a documented mechanism (see service.py), not covered by an
  automated multi-threaded test.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bookings.models import BookingStatus
from tests.support.factories import make_booking
from tests.support.seed import Bookings, Users, Venues


# --- AC1: approval confirms the booking and records approver + time -------------------------
@pytest.mark.story("13.2", ac=1)
def test_venue_staff_can_approve_a_pending_request(venue_staff_client, db: Session):
    before = datetime.now(timezone.utc)

    response = venue_staff_client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == BookingStatus.APPROVED
    assert body["decided_by_id"] == str(Users.VENUE_STAFF.id)
    decided_at = datetime.fromisoformat(body["decided_at"])
    assert before <= decided_at <= datetime.now(timezone.utc) + timedelta(seconds=5)

    db.expire_all()
    row = db.execute(
        text("SELECT status, decided_by_id, decided_at FROM venue_bookings WHERE id = :id"),
        {"id": Bookings.PENDING_SEMINAR_ROOM},
    ).one()
    assert row.status == BookingStatus.APPROVED
    assert row.decided_by_id == Users.VENUE_STAFF.id
    assert row.decided_at is not None


@pytest.mark.story("13.2")
def test_approval_is_recorded_in_the_audit_log(venue_staff_client, db: Session):
    venue_staff_client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/approve")

    row = db.execute(
        text(
            "SELECT actor_id FROM audit_log WHERE action = 'BOOKING_APPROVED' AND entity_id = :id"
        ),
        {"id": Bookings.PENDING_SEMINAR_ROOM},
    ).one()
    assert row.actor_id == Users.VENUE_STAFF.id


@pytest.mark.story("13.2", ac=1)
@pytest.mark.parametrize(
    "status",
    [
        BookingStatus.APPROVED,
        BookingStatus.REJECTED,
        BookingStatus.WITHDRAWN,
        BookingStatus.CANCELLED,
    ],
)
def test_approving_a_request_that_is_not_pending_is_refused(
    venue_staff_client, db: Session, status
):
    booking = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        status=status,
        starts_at=datetime(2027, 1, 10, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 1, 10, 11, 0, tzinfo=timezone.utc),
    )

    response = venue_staff_client.post(f"/bookings/{booking.id}/approve")

    assert response.status_code == 409
    db.expire_all()
    row = db.execute(
        text("SELECT status, decided_by_id, decided_at FROM venue_bookings WHERE id = :id"),
        {"id": booking.id},
    ).one()
    assert row.status == status
    assert row.decided_by_id is None
    assert row.decided_at is None


@pytest.mark.story("13.2", ac=1)
def test_approving_the_same_request_twice_is_refused_the_second_time(venue_staff_client):
    first = venue_staff_client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/approve")
    assert first.status_code == 200

    second = venue_staff_client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/approve")

    assert second.status_code == 409
    # The first decision stands; the refused second attempt did not overwrite it.
    unchanged = venue_staff_client.get(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}")
    assert unchanged.json()["decided_by_id"] == first.json()["decided_by_id"]
    assert unchanged.json()["decided_at"] == first.json()["decided_at"]


# --- AC2: the confirmed period blocks the venue calendar (mechanism, not UI) -----------------
@pytest.mark.story("13.2", ac=2)
def test_a_newly_approved_booking_blocks_a_later_overlapping_request(
    venue_staff_client, db: Session
):
    """Proves the approve endpoint reaches the same held-period mechanism 14.2 already tests -
    the newly-approved booking now blocks a later request the same way the seeded one does."""
    later = make_booking(
        db,
        venue_id=Venues.SEMINAR_ROOM,
        # PENDING_SEMINAR_ROOM is held 04:30-10:15 UTC (13:00-18:00+08, +/-30/15 min setup/
        # teardown) - this overlaps that once it's approved.
        starts_at=datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 25, 11, 0, tzinfo=timezone.utc),
    )

    approved = venue_staff_client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/approve")
    assert approved.status_code == 200

    refused = venue_staff_client.post(f"/bookings/{later.id}/approve")
    assert refused.status_code == 409
    assert str(Bookings.PENDING_SEMINAR_ROOM) in refused.json()["detail"]


# --- AC3: the outcome is visible to the requesting coordinator -------------------------------
@pytest.mark.story("13.2", ac=3)
def test_requesting_coordinator_can_read_the_approved_outcome(client, login_as):
    approved = login_as(Users.VENUE_STAFF).post(
        f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/approve"
    )
    assert approved.status_code == 200

    response = login_as(Users.COORDINATOR).get(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == BookingStatus.APPROVED
    assert body["decided_by_id"] == str(Users.VENUE_STAFF.id)
    assert body["decided_at"] is not None


@pytest.mark.story("13.2", ac=3)
def test_venue_staff_can_also_read_a_booking(venue_staff_client):
    response = venue_staff_client.get(f"/bookings/{Bookings.APPROVED_GRAND_HALL}")
    assert response.status_code == 200
    assert response.json()["status"] == BookingStatus.APPROVED


@pytest.mark.story("13.2", ac=3)
def test_reading_a_missing_booking_is_404(coordinator_client):
    assert coordinator_client.get(f"/bookings/{uuid.uuid4()}").status_code == 404


@pytest.mark.story("13.2", ac=3)
def test_signed_out_visitors_cannot_read_a_booking(client):
    assert client.get(f"/bookings/{Bookings.APPROVED_GRAND_HALL}").status_code == 401


# --- AC4: refused where the period conflicts with a confirmed booking ------------------------
@pytest.mark.story("13.2", ac=4)
def test_approval_is_refused_when_the_period_conflicts_with_a_confirmed_booking(
    venue_staff_client, db: Session
):
    """Same-venue overlap with the seeded APPROVED Grand Hall booking. The overlap matrix
    itself (boundaries, different venues, non-approved statuses) is 14.2's coverage; this just
    proves the endpoint is wired to it."""
    conflicting = make_booking(
        db,
        venue_id=Venues.GRAND_HALL,
        starts_at=datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc),
    )
    db.commit()  # this request already exists as committed data before the approve request

    response = venue_staff_client.post(f"/bookings/{conflicting.id}/approve")

    assert response.status_code == 409
    assert str(Bookings.APPROVED_GRAND_HALL) in response.json()["detail"]

    db.expire_all()
    row = db.execute(
        text("SELECT status, decided_by_id FROM venue_bookings WHERE id = :id"),
        {"id": conflicting.id},
    ).one()
    assert row.status == BookingStatus.PENDING
    assert row.decided_by_id is None


# --- Permissions -------------------------------------------------------------------------
@pytest.mark.story("13.2", ac=1)
def test_signed_out_visitors_cannot_approve_a_booking(client):
    assert client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/approve").status_code == 401


@pytest.mark.story("13.2", ac=1)
@pytest.mark.parametrize(
    "user",
    [Users.ORGANISER, Users.COORDINATOR, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda u: u.role,
)
def test_other_roles_cannot_approve_a_booking(client, user):
    client.login(user)
    assert client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/approve").status_code == 403


@pytest.mark.story("13.2", ac=1)
def test_approving_a_missing_booking_is_404(venue_staff_client):
    assert venue_staff_client.post(f"/bookings/{uuid.uuid4()}/approve").status_code == 404
