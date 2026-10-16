"""Story 21.2 - the coordinator requests a safety review (AC1, AC6, AC11-AC13, AC17-AC19).

AC1  The assigned coordinator requests a review of a Planning event whose every venue requirement
     has an approved booking and every equipment item is accepted; it moves to Awaiting Safety
     Check, and the Safety Officers and organiser are told (AC8).
AC6  After rebooking a flagged arrangement, resubmitting raises no warning.
AC11 An event with no equipment can be submitted; one with no approved booking cannot.
AC12 Resubmitting with a flagged arrangement unchanged is refused with a warning, unless the
     coordinator acknowledges it.
AC13 An unflagged arrangement, or a finding tied to no arrangement, never warns.
AC17 Only the event's assigned coordinator may request the review.
AC18 Signed out is a 401.
AC19 Not in Planning, or arrangements not secured, is a 409 naming what is missing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.bookings.models import BookingStatus, VenueBooking
from app.events.models import EquipmentRequestStatus, EventStatus, EventStatusHistory
from app.notifications.models import Notification
from app.safety.models import (
    EventSafetyReview,
    SafetyArrangement,
    SafetyReviewFinding,
    SafetyReviewOutcome,
)
from app.safety.service import current_facts
from tests.support.factories import (
    make_booking,
    make_equipment_item,
    make_equipment_type,
    make_secured_event,
    make_venue_requirement,
)
from tests.support.seed import Users, Venues


def _request_path(event_id: uuid.UUID) -> str:
    return f"/safety-checks/{event_id}/request"


def _recipients(db: Session, event_id: uuid.UUID, kind: str) -> set[uuid.UUID]:
    return set(
        db.scalars(
            select(Notification.recipient_id).where(
                Notification.event_id == event_id, Notification.notification_type == kind
            )
        )
    )


def _changes_requested(db: Session, event, *, arrangement: str | None) -> EventSafetyReview:
    """A review that sent ``event`` back, seeing the facts it has now, with one finding."""
    review = EventSafetyReview(
        event_id=event.id,
        reviewed_by_id=Users.SAFETY_OFFICER.id,
        reviewed_at=datetime(2026, 10, 1, tzinfo=UTC),
        outcome=SafetyReviewOutcome.CHANGES_REQUESTED,
        facts=current_facts(db, event),
        findings=[
            SafetyReviewFinding(
                position=0,
                factor_code="CAPACITY_AND_LAYOUT",
                arrangement=arrangement,
                required_change="Book a bigger room.",
            )
        ],
    )
    db.add(review)
    db.flush()
    return review


# --- AC1: the happy path -------------------------------------------------------------------------
@pytest.mark.story("21.2", ac=1)
def test_secured_event_moves_to_awaiting_safety_check(coordinator_client, db: Session):
    secured = make_secured_event(db)

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == EventStatus.AWAITING_SAFETY_CHECK
    db.refresh(secured.event)
    assert secured.event.status == EventStatus.AWAITING_SAFETY_CHECK
    history = db.scalar(
        select(EventStatusHistory).where(EventStatusHistory.event_id == secured.event.id)
    )
    assert history is not None
    assert (history.from_status, history.to_status) == (
        EventStatus.PLANNING,
        EventStatus.AWAITING_SAFETY_CHECK,
    )
    assert history.changed_by_id == Users.COORDINATOR.id


@pytest.mark.story("21.2", ac=8)
def test_request_tells_the_safety_officers_and_organiser(coordinator_client, db: Session):
    secured = make_secured_event(db)

    coordinator_client.post(_request_path(secured.event.id), json={})

    assert _recipients(db, secured.event.id, "SAFETY_REVIEW_REQUESTED") == {
        Users.SAFETY_OFFICER.id,
        Users.ORGANISER.id,
    }


# --- AC11: the secured threshold -----------------------------------------------------------------
@pytest.mark.story("21.2", ac=11)
def test_event_with_no_equipment_can_be_submitted(coordinator_client, db: Session):
    secured = make_secured_event(db)
    db.delete(secured.equipment)
    db.flush()

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 200, response.text


@pytest.mark.story("21.2", ac=11)
def test_event_with_no_approved_booking_is_refused(coordinator_client, db: Session):
    secured = make_secured_event(db)
    db.execute(
        update(VenueBooking)
        .where(VenueBooking.id == secured.booking.id)
        .values(status=BookingStatus.WITHDRAWN)
    )

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 409
    assert "No venue is booked." in response.json()["detail"]
    db.refresh(secured.event)
    assert secured.event.status == EventStatus.PLANNING


# --- AC19: not secured, or not in Planning -------------------------------------------------------
@pytest.mark.story("21.2", ac=19)
def test_missing_booking_and_pending_equipment_are_each_named(coordinator_client, db: Session):
    secured = make_secured_event(db)
    make_venue_requirement(db, secured.event.id, position=1, name="Breakout room")
    make_equipment_item(
        db,
        event=secured.event,
        equipment_type=make_equipment_type(db, name="Fog machine"),
        quantity=1,
        status=EquipmentRequestStatus.PENDING,
    )

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "Breakout room has no approved venue booking." in detail
    assert "Fog machine is not accepted yet." in detail
    db.refresh(secured.event)
    assert secured.event.status == EventStatus.PLANNING


@pytest.mark.story("21.2", ac=19)
def test_pending_booking_does_not_count_as_booked(coordinator_client, db: Session):
    secured = make_secured_event(db)
    second = make_venue_requirement(db, secured.event.id, position=1, name="Breakout room")
    make_booking(
        db,
        event_id=secured.event.id,
        venue_id=Venues.BOARDROOM,
        starts_at=secured.event.starts_at,
        ends_at=secured.event.ends_at,
        status=BookingStatus.PENDING,
        venue_requirement_id=second,
    )

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 409
    assert "Breakout room has no approved venue booking." in response.json()["detail"]


@pytest.mark.story("21.2", ac=19)
@pytest.mark.parametrize(
    "status",
    [EventStatus.AWAITING_SAFETY_CHECK, EventStatus.CONFIRMED, EventStatus.CANCELLED],
)
def test_event_not_in_planning_is_refused(coordinator_client, db: Session, status):
    secured = make_secured_event(db, status=status)

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 409
    db.refresh(secured.event)
    assert secured.event.status == status


@pytest.mark.story("21.2", ac=19)
def test_a_second_request_is_refused(coordinator_client, db: Session):
    secured = make_secured_event(db)
    assert coordinator_client.post(_request_path(secured.event.id), json={}).status_code == 200

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 409
    assert len(_recipients(db, secured.event.id, "SAFETY_REVIEW_REQUESTED")) == 2


# --- AC12, AC13, AC6: the unchanged-arrangement warning ------------------------------------------
@pytest.mark.story("21.2", ac=12)
def test_resubmitting_with_flagged_venue_unchanged_warns(coordinator_client, db: Session):
    secured = make_secured_event(db)
    _changes_requested(db, secured.event, arrangement=SafetyArrangement.VENUE_BOOKINGS)

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["unchanged_arrangements"] == [SafetyArrangement.VENUE_BOOKINGS]
    assert detail["message"].endswith(".")
    db.refresh(secured.event)
    assert secured.event.status == EventStatus.PLANNING


@pytest.mark.story("21.2", ac=12)
def test_acknowledging_the_warning_submits_anyway(coordinator_client, db: Session):
    secured = make_secured_event(db)
    _changes_requested(db, secured.event, arrangement=SafetyArrangement.EQUIPMENT)

    response = coordinator_client.post(
        _request_path(secured.event.id), json={"acknowledge_unchanged": True}
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == EventStatus.AWAITING_SAFETY_CHECK


@pytest.mark.story("21.2", ac=6)
def test_rebooking_the_flagged_venue_submits_without_warning(coordinator_client, db: Session):
    secured = make_secured_event(db)
    _changes_requested(db, secured.event, arrangement=SafetyArrangement.VENUE_BOOKINGS)
    secured.booking.status = BookingStatus.WITHDRAWN
    db.flush()
    make_booking(
        db,
        event_id=secured.event.id,
        venue_id=Venues.EXHIBITION_FOYER,
        starts_at=secured.event.starts_at,
        ends_at=secured.event.ends_at,
        status=BookingStatus.APPROVED,
        venue_requirement_id=secured.requirement_id,
        expected_attendance=secured.event.expected_attendance,
        hold_expires_at=datetime(2030, 1, 1, tzinfo=UTC),
    )

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 200, response.text


@pytest.mark.story("21.2", ac=13)
@pytest.mark.parametrize("arrangement", [SafetyArrangement.VENUE_BOOKINGS, None])
def test_no_warning_unless_a_flagged_arrangement_is_unchanged(
    coordinator_client, db: Session, arrangement
):
    """The equipment is unchanged but was never flagged; the venue was flagged (first case) and
    has changed, or nothing was flagged at all (second case)."""
    secured = make_secured_event(db)
    _changes_requested(db, secured.event, arrangement=arrangement)
    secured.booking.expected_attendance += 5
    db.flush()

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 200, response.text


@pytest.mark.story("21.2", ac=12)
def test_only_the_latest_review_flags_count(coordinator_client, db: Session):
    """An approval after the flagging review clears the flags."""
    secured = make_secured_event(db)
    _changes_requested(db, secured.event, arrangement=SafetyArrangement.VENUE_BOOKINGS)
    db.add(
        EventSafetyReview(
            event_id=secured.event.id,
            reviewed_by_id=Users.SAFETY_OFFICER.id,
            reviewed_at=datetime(2026, 10, 2, tzinfo=UTC),
            outcome=SafetyReviewOutcome.APPROVED,
            facts={},
        )
    )
    db.flush()

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 200, response.text


# --- AC17, AC18: who may request ------------------------------------------------------------------
@pytest.mark.story("21.2", ac=17)
def test_another_coordinator_is_refused(login_as, db: Session):
    secured = make_secured_event(db)

    response = login_as(Users.COORDINATOR_2).post(_request_path(secured.event.id), json={})

    assert response.status_code == 403
    db.refresh(secured.event)
    assert secured.event.status == EventStatus.PLANNING


@pytest.mark.story("21.2", ac=17)
@pytest.mark.parametrize("user", [Users.ORGANISER, Users.SAFETY_OFFICER, Users.VENUE_STAFF])
def test_other_roles_are_refused(login_as, db: Session, user):
    secured = make_secured_event(db)

    response = login_as(user).post(_request_path(secured.event.id), json={})

    assert response.status_code == 403


@pytest.mark.story("21.2", ac=18)
def test_signed_out_is_refused(client, db: Session):
    secured = make_secured_event(db)

    assert client.post(_request_path(secured.event.id), json={}).status_code == 401


@pytest.mark.story("21.2", ac=19)
def test_unknown_event_is_not_found(coordinator_client):
    assert coordinator_client.post(_request_path(uuid.uuid4()), json={}).status_code == 404
