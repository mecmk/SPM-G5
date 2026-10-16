"""Story 21.2 - the coordinator confirms a safety-approved event (AC7, AC8, AC14, AC17, AC18,
AC21).

AC7  The assigned coordinator confirms a Planning event whose latest review approved it with the
     facts it still has; it moves to Confirmed and its venue holds are completed.
AC8  The organiser and the Safety Officers are told.
AC14 If the facts changed after the approval, or an arrangement was lost, Confirm is refused,
     naming why.
AC17 Only the assigned coordinator may confirm.
AC18 Signed out is a 401.
AC21 No approval, a later request for changes, or a second confirm is a 409.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bookings.models import BookingStatus
from app.events.models import EventStatus, EventStatusHistory
from app.notifications.models import Notification
from app.safety.models import EventSafetyReview, SafetyReviewOutcome
from app.safety.service import current_facts
from tests.support.factories import SecuredEvent, make_secured_event
from tests.support.seed import Users


def _confirm_path(event_id: uuid.UUID) -> str:
    return f"/events/{event_id}/confirm"


def _review(db: Session, secured: SecuredEvent, outcome: str, *, day: int = 1) -> None:
    db.add(
        EventSafetyReview(
            event_id=secured.event.id,
            reviewed_by_id=Users.SAFETY_OFFICER.id,
            reviewed_at=datetime(2026, 10, day, tzinfo=UTC),
            outcome=outcome,
            facts=current_facts(db, secured.event),
        )
    )
    db.flush()


@pytest.fixture
def approved(db: Session) -> SecuredEvent:
    secured = make_secured_event(db)
    _review(db, secured, SafetyReviewOutcome.APPROVED)
    return secured


# --- AC7: confirm --------------------------------------------------------------------------------
@pytest.mark.story("21.2", ac=7)
def test_approved_event_is_confirmed(coordinator_client, db: Session, approved):
    response = coordinator_client.post(_confirm_path(approved.event.id))

    assert response.status_code == 200, response.text
    assert response.json()["status"] == EventStatus.CONFIRMED
    db.refresh(approved.event)
    assert approved.event.status == EventStatus.CONFIRMED
    history = db.scalar(
        select(EventStatusHistory).where(EventStatusHistory.event_id == approved.event.id)
    )
    assert history is not None
    assert (history.from_status, history.to_status) == (
        EventStatus.PLANNING,
        EventStatus.CONFIRMED,
    )


@pytest.mark.story("21.2", ac=7)
def test_confirming_completes_the_venue_holds(coordinator_client, db: Session, approved):
    coordinator_client.post(_confirm_path(approved.event.id))

    db.refresh(approved.booking)
    assert approved.booking.hold_completed_at is not None
    assert approved.booking.status == BookingStatus.APPROVED


@pytest.mark.story("21.2", ac=8)
def test_organiser_and_safety_officers_are_told(coordinator_client, db: Session, approved):
    coordinator_client.post(_confirm_path(approved.event.id))

    told = set(
        db.scalars(
            select(Notification.recipient_id).where(
                Notification.event_id == approved.event.id,
                Notification.notification_type == "EVENT_CONFIRMED",
            )
        )
    )
    assert told == {Users.ORGANISER.id, Users.SAFETY_OFFICER.id}


# --- AC14: a stale approval ----------------------------------------------------------------------
@pytest.mark.story("21.2", ac=14)
def test_attendance_changed_after_approval_blocks_confirm(coordinator_client, db, approved):
    approved.event.expected_attendance += 10
    db.flush()

    response = coordinator_client.post(_confirm_path(approved.event.id))

    assert response.status_code == 409
    assert "changed since the safety approval" in response.json()["detail"]
    db.refresh(approved.event)
    assert approved.event.status == EventStatus.PLANNING


@pytest.mark.story("21.2", ac=14)
def test_lost_booking_blocks_confirm_and_is_named(coordinator_client, db: Session, approved):
    approved.booking.status = BookingStatus.EXPIRED
    db.flush()

    response = coordinator_client.post(_confirm_path(approved.event.id))

    assert response.status_code == 409
    assert "Main venue has no approved venue booking." in response.json()["detail"]


@pytest.mark.story("21.2", ac=14)
def test_event_page_lists_the_confirm_blockers(coordinator_client, db: Session, approved):
    approved.event.expected_attendance += 10
    db.flush()

    summary = coordinator_client.get(f"/events/{approved.event.id}/safety-review").json()

    assert any("changed since the safety approval" in b for b in summary["confirm_blockers"])


# --- AC21: no valid approval, double confirm -----------------------------------------------------
@pytest.mark.story("21.2", ac=21)
def test_never_approved_is_refused(coordinator_client, db: Session):
    secured = make_secured_event(db)

    response = coordinator_client.post(_confirm_path(secured.event.id))

    assert response.status_code == 409
    assert "has not been approved" in response.json()["detail"]


@pytest.mark.story("21.2", ac=21)
def test_changes_requested_after_approval_is_refused(coordinator_client, db: Session, approved):
    _review(db, approved, SafetyReviewOutcome.CHANGES_REQUESTED, day=2)

    response = coordinator_client.post(_confirm_path(approved.event.id))

    assert response.status_code == 409


@pytest.mark.story("21.2", ac=21)
def test_awaiting_the_check_is_refused(coordinator_client, db: Session, approved):
    approved.event.status = EventStatus.AWAITING_SAFETY_CHECK
    db.flush()

    assert coordinator_client.post(_confirm_path(approved.event.id)).status_code == 409


@pytest.mark.story("21.2", ac=21)
def test_double_confirm_is_refused(coordinator_client, db: Session, approved):
    assert coordinator_client.post(_confirm_path(approved.event.id)).status_code == 200

    response = coordinator_client.post(_confirm_path(approved.event.id))

    assert response.status_code == 409
    transitions = db.scalars(
        select(EventStatusHistory).where(EventStatusHistory.event_id == approved.event.id)
    ).all()
    assert len(transitions) == 1


# --- AC17, AC18: who may confirm -----------------------------------------------------------------
@pytest.mark.story("21.2", ac=17)
@pytest.mark.parametrize(
    "user", [Users.COORDINATOR_2, Users.ORGANISER, Users.SAFETY_OFFICER, Users.VENUE_STAFF]
)
def test_others_cannot_confirm(login_as, db: Session, approved, user):
    response = login_as(user).post(_confirm_path(approved.event.id))

    assert response.status_code == 403
    db.refresh(approved.event)
    assert approved.event.status == EventStatus.PLANNING


@pytest.mark.story("21.2", ac=18)
def test_signed_out_cannot_confirm(client, approved):
    assert client.post(_confirm_path(approved.event.id)).status_code == 401


@pytest.mark.story("21.2", ac=21)
def test_unknown_event_is_not_found(coordinator_client):
    assert coordinator_client.post(_confirm_path(uuid.uuid4())).status_code == 404
