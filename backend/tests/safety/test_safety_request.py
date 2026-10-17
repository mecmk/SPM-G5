"""Story 21.2 - the coordinator requests a safety review. The backlog's ACs, as written:

AC1  The assigned coordinator sends a safety review request for a Planning event whose every venue
     requirement has an approved booking and every equipment item is accepted. The event moves to
     Awaiting Safety Check.
AC6  After rebooking the flagged arrangements, the coordinator resubmits with no warning. [...]
AC8  Every status change notifies.
AC11 An event with no equipment items can be submitted; an event with zero approved bookings
     cannot.
AC12 Resubmitting with a flagged arrangement unchanged shows a warning; the coordinator can go back
     or submit anyway.
AC13 An unflagged arrangement left unchanged, or a finding with no arrangement (e.g. crowd
     movement), never triggers the warning.
AC17 Only the event's assigned coordinator requests a review or confirms; another coordinator, the
     organiser or the officer gets 403.
AC18 Signed out -> 401 on every new endpoint. [...]
AC19 A request for an event not in Planning (already awaiting, confirmed, cancelled), or a double
     submit -> 409. Arrangements not secured -> 409 naming each missing one.

A declined equipment item no longer counts towards "every equipment item" (it can never be
accepted, and story 15.1 AC7 locks it); only an open one - requested, pending or unavailable -
blocks the request.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
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
    sent = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.event_id == secured.event.id,
            Notification.notification_type == "SAFETY_REVIEW_REQUESTED",
        )
    )
    assert sent == 2


@pytest.mark.story("21.2", ac=19)
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (EquipmentRequestStatus.REQUESTED, 409),
        (EquipmentRequestStatus.PENDING, 409),
        (EquipmentRequestStatus.UNAVAILABLE, 409),
        (EquipmentRequestStatus.DECLINED, 200),
    ],
)
def test_each_open_equipment_item_blocks_and_a_declined_one_does_not(
    coordinator_client, db: Session, status, expected
):
    """A declined item can never be accepted (story 15.1 AC7 locks it), so it no longer counts."""
    secured = make_secured_event(db)
    make_equipment_item(
        db,
        event=secured.event,
        equipment_type=make_equipment_type(db, name="Fog machine"),
        quantity=1,
        status=status,
        is_held=status != EquipmentRequestStatus.DECLINED,
    )

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == expected, response.text
    if expected == 409:
        assert "Fog machine is not accepted yet." in response.json()["detail"]


@pytest.mark.story("21.2", ac=19)
def test_a_lapsed_hold_not_yet_swept_does_not_count(coordinator_client, db: Session):
    """Story 12.7 AC4/AC6: from its expiry the hold has expired, though the timer has not run."""
    secured = make_secured_event(db)
    secured.booking.hold_expires_at = datetime.now(UTC) - timedelta(minutes=5)
    db.flush()

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 409
    assert "Main venue has no approved venue booking." in response.json()["detail"]
    db.refresh(secured.booking)
    assert secured.booking.status == BookingStatus.EXPIRED


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
    warned = coordinator_client.post(_request_path(secured.event.id), json={})
    assert warned.status_code == 409
    assert warned.json()["detail"]["unchanged_arrangements"] == [SafetyArrangement.EQUIPMENT]

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
    """The equipment is unchanged but was never flagged; the venue was flagged and has changed
    (first case), or the finding flags no arrangement and nothing has changed (second case)."""
    secured = make_secured_event(db)
    _changes_requested(db, secured.event, arrangement=arrangement)
    if arrangement is not None:
        secured.booking.expected_attendance += 5
        db.flush()

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 200, response.text


@pytest.mark.story("21.2", ac=12)
def test_event_page_carries_the_warning_before_sending(coordinator_client, db: Session):
    """The page asks before sending, so the warning never arrives as a failed request."""
    secured = make_secured_event(db)
    _changes_requested(db, secured.event, arrangement=SafetyArrangement.VENUE_BOOKINGS)
    summary_path = f"/events/{secured.event.id}/safety-review"

    warning = coordinator_client.get(summary_path).json()["unchanged_warning"]

    assert warning == (
        "The venue bookings the Safety Officer flagged have not changed since their review."
    )
    secured.booking.expected_attendance += 5
    db.flush()
    assert coordinator_client.get(summary_path).json()["unchanged_warning"] is None


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
