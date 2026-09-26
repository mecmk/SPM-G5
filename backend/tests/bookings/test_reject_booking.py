"""Story 13.2.1 - reject venue booking request with a reason.

AC1 Rejection sets the booking to REJECTED and records the rejecter, time and a trimmed reason,
    without touching the event or any other booking.
AC2 A reason is mandatory: missing, null, empty, whitespace-only or wrongly-typed values are
    refused.
AC5 Permission and invalid-state refusals: 401/403/404, rejecting a booking that is not PENDING,
    repeat rejection, and approve/reject crossing each other.
AC6 Rejection never runs the venue-conflict check - an overlapping APPROVED booking does not
    block rejecting a PENDING one.

AC3 and AC4 are UI/navigation acceptance criteria proven at e2e (tests/e2e/bookings.spec.ts),
not repeated here.

Excluded, with reason:
* A length limit on the reason - no requirement states one; AC2 only asks that missing, null,
  empty and whitespace-only values be refused.
* "Venue Staff outside the venue's responsibility scope" - as in test_approve_booking.py,
  BOOKINGS_DECIDE is role-wide; there is no per-venue responsibility table to test.
* A genuine multi-connection concurrency test (two simultaneous decisions on the same booking) -
  same reasoning as test_approve_booking.py: the guard is a ``SELECT ... FOR UPDATE`` row lock,
  which a single-session test cannot meaningfully race. The sequential repeated-decision tests
  below prove the guard the lock protects, not the lock itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bookings.models import BookingStatus
from tests.support.factories import make_booking
from tests.support.seed import Bookings, Events, Users, Venues


# --- AC1: rejection records the rejecter, time and reason -------------------------------------
@pytest.mark.story("13.2.1", ac=1)
def test_venue_staff_can_reject_a_pending_request_with_a_reason(venue_staff_client, db: Session):
    before = datetime.now(timezone.utc)

    response = venue_staff_client.post(
        f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/reject",
        json={"decision_reason": "The venue is under maintenance that week."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == BookingStatus.REJECTED
    assert body["decision_reason"] == "The venue is under maintenance that week."
    assert body["decided_by_id"] == str(Users.VENUE_STAFF.id)
    decided_at = datetime.fromisoformat(body["decided_at"])
    assert before <= decided_at <= datetime.now(timezone.utc) + timedelta(seconds=5)

    db.expire_all()
    row = db.execute(
        text(
            "SELECT status, decided_by_id, decided_at, decision_reason "
            "FROM venue_bookings WHERE id = :id"
        ),
        {"id": Bookings.PENDING_EXHIBITION_FOYER},
    ).one()
    assert row.status == BookingStatus.REJECTED
    assert row.decided_by_id == Users.VENUE_STAFF.id
    assert row.decided_at is not None
    assert row.decision_reason == "The venue is under maintenance that week."


@pytest.mark.story("13.2.1", ac=1)
def test_rejection_reason_is_trimmed_before_storage(venue_staff_client):
    response = venue_staff_client.post(
        f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/reject",
        json={"decision_reason": "  The venue is under maintenance that week.  "},
    )

    assert response.status_code == 200
    assert response.json()["decision_reason"] == "The venue is under maintenance that week."


@pytest.mark.story("13.2.1", ac=1)
def test_rejection_is_recorded_in_the_audit_log(venue_staff_client, db: Session):
    venue_staff_client.post(
        f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/reject",
        json={"decision_reason": "The venue is under maintenance that week."},
    )

    row = db.execute(
        text(
            "SELECT actor_id, details FROM audit_log "
            "WHERE action = 'BOOKING_REJECTED' AND entity_id = :id"
        ),
        {"id": Bookings.PENDING_EXHIBITION_FOYER},
    ).one()
    assert row.actor_id == Users.VENUE_STAFF.id
    assert row.details["reason"] == "The venue is under maintenance that week."


@pytest.mark.story("13.2.1", ac=1)
def test_rejecting_a_booking_does_not_change_its_event_or_other_bookings(
    venue_staff_client, db: Session
):
    other_booking_before = venue_staff_client.get(f"/bookings/{Bookings.PENDING_GRAND_HALL}").json()

    response = venue_staff_client.post(
        f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/reject",
        json={"decision_reason": "The venue is under maintenance that week."},
    )
    assert response.status_code == 200

    db.expire_all()
    event_status = db.execute(
        text("SELECT status FROM events WHERE id = :id"),
        {"id": Events.APPROVED_2},
    ).scalar_one()
    assert event_status == "PLANNING"

    other_booking_after = venue_staff_client.get(f"/bookings/{Bookings.PENDING_GRAND_HALL}").json()
    assert other_booking_after == other_booking_before


@pytest.mark.story("13.2.1", ac=5)
def test_signed_out_visitors_cannot_reject_a_booking(client):
    response = client.post(
        f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/reject",
        json={"decision_reason": "Not available."},
    )
    assert response.status_code == 401


@pytest.mark.story("13.2.1", ac=5)
@pytest.mark.parametrize(
    "user",
    [Users.ORGANISER, Users.COORDINATOR, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda u: u.role,
)
def test_other_roles_cannot_reject_a_booking(client, user):
    client.login(user)
    response = client.post(
        f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/reject",
        json={"decision_reason": "Not available."},
    )
    assert response.status_code == 403


@pytest.mark.story("13.2.1", ac=5)
def test_rejecting_a_missing_booking_is_404(venue_staff_client):
    response = venue_staff_client.post(
        f"/bookings/{uuid.uuid4()}/reject",
        json={"decision_reason": "Not available."},
    )
    assert response.status_code == 404


@pytest.mark.story("13.2.1", ac=5)
def test_rejecting_with_a_malformed_booking_id_is_422(venue_staff_client):
    response = venue_staff_client.post(
        "/bookings/not-a-uuid/reject",
        json={"decision_reason": "Not available."},
    )
    assert response.status_code == 422


# --- AC2: a reason is mandatory ----------------------------------------------------------------
@pytest.mark.story("13.2.1", ac=2)
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"decision_reason": None},
        {"decision_reason": ""},
        {"decision_reason": "   "},
        {"decision_reason": 123},
        {"decision_reason": ["Not available."]},
    ],
    ids=["missing", "null", "empty", "whitespace_only", "wrong_type_int", "wrong_type_list"],
)
def test_rejecting_without_a_valid_reason_is_refused(venue_staff_client, payload):
    response = venue_staff_client.post(
        f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/reject", json=payload
    )

    assert response.status_code == 422
    db_check = venue_staff_client.get(f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}")
    assert db_check.json()["status"] == BookingStatus.PENDING


# --- AC5: invalid states ------------------------------------------------------------------------
@pytest.mark.story("13.2.1", ac=5)
@pytest.mark.parametrize(
    "status",
    [
        BookingStatus.APPROVED,
        BookingStatus.REJECTED,
        BookingStatus.WITHDRAWN,
        BookingStatus.CANCELLED,
    ],
)
def test_rejecting_a_request_that_is_not_pending_is_refused(
    venue_staff_client, db: Session, status
):
    booking = make_booking(
        db,
        venue_id=Venues.BOARDROOM,
        status=status,
        starts_at=datetime(2027, 2, 10, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2027, 2, 10, 11, 0, tzinfo=timezone.utc),
    )

    response = venue_staff_client.post(
        f"/bookings/{booking.id}/reject", json={"decision_reason": "Not available."}
    )

    assert response.status_code == 409
    db.expire_all()
    row = db.execute(
        text(
            "SELECT status, decided_by_id, decided_at, decision_reason "
            "FROM venue_bookings WHERE id = :id"
        ),
        {"id": booking.id},
    ).one()
    assert row.status == status
    assert row.decided_by_id is None
    assert row.decided_at is None
    assert row.decision_reason is None


@pytest.mark.story("13.2.1", ac=5)
def test_rejecting_the_same_request_twice_is_refused_the_second_time(venue_staff_client):
    first = venue_staff_client.post(
        f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/reject",
        json={"decision_reason": "The venue is under maintenance that week."},
    )
    assert first.status_code == 200

    second = venue_staff_client.post(
        f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/reject",
        json={"decision_reason": "A completely different reason."},
    )

    assert second.status_code == 409
    unchanged = venue_staff_client.get(f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}")
    assert unchanged.json()["decision_reason"] == "The venue is under maintenance that week."
    assert unchanged.json()["decided_at"] == first.json()["decided_at"]


@pytest.mark.story("13.2.1", ac=5)
def test_approving_after_rejecting_is_refused(venue_staff_client):
    rejected = venue_staff_client.post(
        f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/reject",
        json={"decision_reason": "The venue is under maintenance that week."},
    )
    assert rejected.status_code == 200

    approve_attempt = venue_staff_client.post(
        f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/approve"
    )

    assert approve_attempt.status_code == 409
    unchanged = venue_staff_client.get(f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}")
    assert unchanged.json()["status"] == BookingStatus.REJECTED
    assert unchanged.json()["decision_reason"] == "The venue is under maintenance that week."


@pytest.mark.story("13.2.1", ac=5)
def test_rejecting_after_approving_is_refused(venue_staff_client):
    approved = venue_staff_client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/approve")
    assert approved.status_code == 200

    reject_attempt = venue_staff_client.post(
        f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/reject",
        json={"decision_reason": "Changed my mind."},
    )

    assert reject_attempt.status_code == 409
    unchanged = venue_staff_client.get(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}")
    assert unchanged.json()["status"] == BookingStatus.APPROVED
    assert unchanged.json()["decision_reason"] is None


@pytest.mark.story("13.2.1", ac=5)
def test_a_failed_rejection_does_not_create_an_audit_entry(venue_staff_client, db: Session):
    approved = venue_staff_client.post(f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/approve")
    assert approved.status_code == 200

    reject_attempt = venue_staff_client.post(
        f"/bookings/{Bookings.PENDING_SEMINAR_ROOM}/reject",
        json={"decision_reason": "Changed my mind."},
    )
    assert reject_attempt.status_code == 409

    count = db.execute(
        text(
            "SELECT count(*) FROM audit_log WHERE action = 'BOOKING_REJECTED' AND entity_id = :id"
        ),
        {"id": Bookings.PENDING_SEMINAR_ROOM},
    ).scalar_one()
    assert count == 0


# --- AC6: rejection never runs the venue-conflict check ----------------------------------------
@pytest.mark.story("13.2.1", ac=6)
def test_rejecting_an_overlapping_pending_request_still_succeeds(venue_staff_client, db: Session):
    """Same-venue overlap with the seeded APPROVED Grand Hall booking - unlike approve, reject
    must succeed anyway, because a rejected request never reserves the venue (14.2's exclusion
    constraint only fires for APPROVED)."""
    overlapping = make_booking(
        db,
        venue_id=Venues.GRAND_HALL,
        starts_at=datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc),
    )
    db.commit()

    response = venue_staff_client.post(
        f"/bookings/{overlapping.id}/reject", json={"decision_reason": "No longer needed."}
    )

    assert response.status_code == 200
    assert response.json()["status"] == BookingStatus.REJECTED
