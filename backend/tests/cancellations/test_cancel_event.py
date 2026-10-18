"""Story 6.2 - cancel an event and release the resources it holds.

AC1  The Event Organiser cancels their own event from its details page with a reason; its status
     becomes Cancelled.
AC2  Its pending and approved venue bookings are released, so the venues are free again.
AC3  Its equipment holds and reservations are released, so the equipment is free again.
AC4  Its open equipment requests, pending change requests and attendee registrations are closed;
     their records stay.
AC5  The assigned coordinator (or the Event Coordinator Lead when none is assigned) and every
     registered attendee are told; Venue Staff and Technical Support are told of what was released.
     The reason, the organiser and the time are recorded.
AC6  Cancelling is allowed from Under Review, Clarification Requested, Planning, Awaiting Safety
     Check and Confirmed; Draft, Completed, Cancelled and Rejected events cannot be cancelled.
AC7  A reason is mandatory; an empty or whitespace-only one is refused.
AC8  An event holding nothing can still be cancelled.
AC9  The cancelled event stays visible, and planning, booking approvals, equipment decisions and
     registrations on it are refused.
AC10 Everything happens in one transaction: a failure part-way leaves the event unchanged.
AC11 Only the organiser who owns the event can cancel it.
AC12 An approval racing the cancellation leaves no active venue hold or equipment reservation.
AC13 Only the first of several cancellations succeeds, without repeating what it did.
AC14 Venue Staff see the cancelled event's bookings under a read-only Cancelled tab and under All.
AC15 Technical Support see the cancelled items that had been sent to them under a read-only
     Cancelled tab and under All; an item never sent is not shown. This replaces 15.2 AC5 for a
     cancelled event: a rejected event's items still disappear.
AC16 A cancelled booking or equipment item shows when it was cancelled, not its old approval time.

Most cases build a fresh event dated in 2030 on a fresh venue, owned by Olivia and coordinated
by Chloe, so no seeded booking or hold is in the way. The races (AC12, AC13) run real concurrent
transactions, so they commit and clean up after themselves.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings import service as bookings_service
from app.bookings.models import BookingStatus, VenueBooking
from app.bookings.schemas import BookingRequestIn
from app.cancellations import service as cancellations_service
from app.change_requests.models import EventChangeRequest
from app.common.audit import AuditLog
from app.equipment import service as equipment_service
from app.equipment.schemas import EquipmentDecisionIn
from app.events import service as events_service
from app.events.models import (
    EquipmentHoldStatus,
    EquipmentRequestStatus,
    EquipmentReservation,
    Event,
    EventEquipmentRequest,
    EventStatus,
    EventStatusHistory,
)
from app.events.schemas import EventEquipmentIn
from app.notifications.models import Notification
from app.registrations.models import EventRegistration, RegistrationStatus
from tests.support.factories import (
    approval_payload,
    make_booking,
    make_change_request,
    make_equipment_item,
    make_equipment_type,
    make_event,
    make_user,
    make_venue,
)
from tests.support.seed import Users

STARTS_AT = datetime(2030, 5, 6, 1, 0, tzinfo=UTC)
ENDS_AT = datetime(2030, 5, 6, 9, 0, tzinfo=UTC)
REASON = "Our sponsor withdrew the budget."
LOCK_WAIT_SECONDS = 20
# The statuses AC6 allows a cancellation from, and those it refuses.
CANCELLABLE = (
    EventStatus.UNDER_REVIEW,
    EventStatus.CLARIFICATION_REQUESTED,
    EventStatus.PLANNING,
    EventStatus.AWAITING_SAFETY_CHECK,
    EventStatus.CONFIRMED,
)
NOT_CANCELLABLE = (
    EventStatus.DRAFT,
    EventStatus.COMPLETED,
    EventStatus.CANCELLED,
    EventStatus.REJECTED,
)


def _event(db: Session, *, status: str = EventStatus.PLANNING, **overrides: Any) -> Event:
    """Olivia's event in ``status``, coordinated by Chloe unless said otherwise."""
    return make_event(
        db,
        status=status,
        starts_at=STARTS_AT,
        ends_at=ENDS_AT,
        assigned_coordinator_id=overrides.pop("assigned_coordinator_id", Users.COORDINATOR.id),
        **overrides,
    )


def _booking(db: Session, event: Event, *, status: str = BookingStatus.PENDING, **overrides: Any):
    """A booking of a fresh venue for ``event``'s period. An approved one carries a hold."""
    if status == BookingStatus.APPROVED:
        overrides.setdefault("hold_expires_at", datetime.now(UTC) + timedelta(days=30))
        overrides.setdefault("decided_by_id", Users.VENUE_STAFF.id)
        overrides.setdefault("decided_at", datetime.now(UTC))
    venue_id = overrides.pop("venue_id", None)
    return make_booking(
        db,
        event_id=event.id,
        venue_id=venue_id if venue_id is not None else make_venue(db).id,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        status=status,
        **overrides,
    )


def _item(db: Session, event: Event, *, status: str, is_held: bool = True):
    """An equipment item of a fresh type on ``event``, so nothing else holds that type."""
    return make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db),
        quantity=2,
        status=status,
        is_held=is_held,
    )


def _register(db: Session, event: Event, attendee: Any, *, status: str = "REGISTERED"):
    registration = EventRegistration(
        event_id=event.id,
        attendee_id=attendee.id,
        status=status,
        withdrawn_at=datetime.now(UTC) if status == RegistrationStatus.WITHDRAWN else None,
    )
    db.add(registration)
    db.flush()
    return registration


def _cancel(client, event_id: uuid.UUID, reason: Any = REASON):
    return client.post(f"/events/{event_id}/cancel", json={"reason": reason})


def _notified(db: Session, notification_type: str, event_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(Notification.recipient_id).where(
                Notification.notification_type == notification_type,
                Notification.event_id == event_id,
            )
        )
    )


def _status(db: Session, model: Any, row_id: uuid.UUID) -> str:
    return db.scalar(select(model.status).where(model.id == row_id))


# --- AC1: the organiser cancels their own event ----------------------------------------------
@pytest.mark.story("6.2", ac=1)
def test_the_organiser_cancels_their_own_event(organiser_client, db: Session):
    event = _event(db)

    response = _cancel(organiser_client, event.id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == EventStatus.CANCELLED
    assert body["cancellation_reason"] == REASON
    assert body["cancelled_by_name"] == Users.ORGANISER.full_name
    assert body["cancelled_at"] is not None
    assert _status(db, Event, event.id) == EventStatus.CANCELLED


# --- AC2: venue bookings ----------------------------------------------------------------------
@pytest.mark.story("6.2", ac=2)
def test_pending_and_approved_bookings_are_released(organiser_client, db: Session):
    """Who approved a booking, and when, stay on it; a booking already closed is left alone."""
    event = _event(db)
    pending = _booking(db, event)
    approved = _booking(db, event, status=BookingStatus.APPROVED)
    withdrawn = _booking(db, event, status=BookingStatus.WITHDRAWN)
    decided_at = approved.decided_at

    assert _cancel(organiser_client, event.id).status_code == 200

    db.expire_all()
    assert db.get(VenueBooking, pending.id).status == BookingStatus.CANCELLED
    released = db.get(VenueBooking, approved.id)
    assert released.status == BookingStatus.CANCELLED
    assert (released.decided_by_id, released.decided_at) == (Users.VENUE_STAFF.id, decided_at)
    assert db.get(VenueBooking, withdrawn.id).status == BookingStatus.WITHDRAWN


@pytest.mark.story("6.2", ac=2)
def test_a_released_venue_can_be_booked_by_another_event(organiser_client, db: Session):
    """The database refuses two holding bookings of one venue that overlap, so this booking only
    goes in once the cancelled event's booking stopped holding the venue."""
    event = _event(db)
    held = _booking(db, event, status=BookingStatus.APPROVED)

    assert _cancel(organiser_client, event.id).status_code == 200

    other = _event(db)
    booking = _booking(db, other, venue_id=held.venue_id)
    assert booking.status == BookingStatus.PENDING


# --- AC3: equipment holds -----------------------------------------------------------------------
@pytest.mark.story("6.2", ac=3)
def test_equipment_holds_are_released(organiser_client, db: Session):
    event = _event(db)
    item = _item(db, event, status=EquipmentRequestStatus.ACCEPTED)

    assert _cancel(organiser_client, event.id).status_code == 200

    db.expire_all()
    holds = db.scalars(
        select(EquipmentReservation).where(EquipmentReservation.equipment_request_id == item.id)
    ).all()
    assert [hold.status for hold in holds] == [EquipmentHoldStatus.RELEASED]
    assert holds[0].released_quantity == holds[0].quantity
    free = events_service.available_by_type(db, STARTS_AT, ENDS_AT)
    assert free[item.equipment_type_id] == item.equipment_type.total_quantity


# --- AC4: open requests and registrations are closed ------------------------------------------
@pytest.mark.story("6.2", ac=4)
def test_open_equipment_items_are_cancelled_and_declined_ones_kept(organiser_client, db: Session):
    """D1: every item still open is closed; a declined one stays Technical Support's decision."""
    event = _event(db)
    items = {
        status: _item(db, event, status=status, is_held=status != "UNAVAILABLE")
        for status in ("REQUESTED", "PENDING", "ACCEPTED", "UNAVAILABLE")
    }
    declined = _item(db, event, status=EquipmentRequestStatus.DECLINED, is_held=False)

    assert _cancel(organiser_client, event.id).status_code == 200

    db.expire_all()
    for item in items.values():
        assert _status(db, EventEquipmentRequest, item.id) == EquipmentRequestStatus.CANCELLED
    assert _status(db, EventEquipmentRequest, declined.id) == EquipmentRequestStatus.DECLINED


@pytest.mark.story("6.2", ac=4)
def test_pending_change_requests_are_cancelled_and_decided_ones_kept(organiser_client, db: Session):
    event = _event(db)
    pending = make_change_request(db, event=event)
    decided = {
        status: make_change_request(
            db,
            event=event,
            field=field,
            status=status,
            decided_by_id=Users.COORDINATOR.id,
            decided_at=datetime.now(UTC),
        )
        for status, field in (("APPROVED", "schedule"), ("REJECTED", "equipment"))
    }
    withdrawn = make_change_request(db, event=event, field="venue_requirements", status="WITHDRAWN")

    assert _cancel(organiser_client, event.id).status_code == 200

    db.expire_all()
    assert _status(db, EventChangeRequest, pending.id) == "CANCELLED"
    for status, request in decided.items():
        assert _status(db, EventChangeRequest, request.id) == status
    assert _status(db, EventChangeRequest, withdrawn.id) == "WITHDRAWN"


@pytest.mark.story("6.2", ac=4)
def test_registrations_are_cancelled_and_withdrawn_ones_kept(organiser_client, db: Session):
    event = _event(db, status=EventStatus.CONFIRMED, is_public=True, registration_required=True)
    registered = _register(db, event, Users.ATTENDEE)
    withdrawn = _register(db, event, Users.ATTENDEE_2, status=RegistrationStatus.WITHDRAWN)

    assert _cancel(organiser_client, event.id).status_code == 200

    db.expire_all()
    assert _status(db, EventRegistration, registered.id) == RegistrationStatus.CANCELLED
    assert _status(db, EventRegistration, withdrawn.id) == RegistrationStatus.WITHDRAWN


@pytest.mark.story("6.2", ac=4)
def test_nothing_is_deleted(organiser_client, db: Session):
    event = _event(db, status=EventStatus.CONFIRMED, is_public=True, registration_required=True)
    _booking(db, event)
    _item(db, event, status=EquipmentRequestStatus.PENDING)
    make_change_request(db, event=event)
    _register(db, event, Users.ATTENDEE)
    tables = (
        VenueBooking,
        EventEquipmentRequest,
        EquipmentReservation,
        EventChangeRequest,
        EventRegistration,
    )

    def counts() -> list[int]:
        return [
            db.scalar(select(func.count()).select_from(table).where(table.event_id == event.id))
            for table in tables
        ]

    before = counts()
    assert _cancel(organiser_client, event.id).status_code == 200

    assert counts() == before


# --- AC5: recorded, and who is told ------------------------------------------------------------
@pytest.mark.story("6.2", ac=5)
def test_the_cancellation_is_recorded(organiser_client, db: Session):
    event = _event(db)

    assert _cancel(organiser_client, event.id).status_code == 200

    db.expire_all()
    cancelled = db.get(Event, event.id)
    assert cancelled.cancelled_by_id == Users.ORGANISER.id
    assert cancelled.cancellation_reason == REASON
    assert cancelled.cancelled_at is not None
    [history] = db.scalars(
        select(EventStatusHistory).where(
            EventStatusHistory.event_id == event.id,
            EventStatusHistory.to_status == EventStatus.CANCELLED,
        )
    ).all()
    assert (history.from_status, history.changed_by_id, history.reason) == (
        EventStatus.PLANNING,
        Users.ORGANISER.id,
        REASON,
    )
    [audit] = db.scalars(
        select(AuditLog).where(AuditLog.entity_id == event.id, AuditLog.action == "EVENT_CANCELLED")
    ).all()
    assert audit.actor_id == Users.ORGANISER.id
    assert audit.details["reason"] == REASON
    assert audit.details["from_status"] == EventStatus.PLANNING


@pytest.mark.story("6.2", ac=5)
def test_the_earlier_review_decision_is_kept(organiser_client, db: Session):
    decided_at = datetime(2026, 9, 14, 1, 0, tzinfo=UTC)
    event = _event(db, decided_by_id=Users.COORDINATOR.id, decided_at=decided_at)

    assert _cancel(organiser_client, event.id).status_code == 200

    db.expire_all()
    kept = db.get(Event, event.id)
    assert (kept.decided_by_id, kept.decided_at, kept.decision_reason) == (
        Users.COORDINATOR.id,
        decided_at,
        None,
    )


@pytest.mark.story("6.2", ac=5)
def test_the_assigned_coordinator_is_told(organiser_client, db: Session):
    event = _event(db)

    assert _cancel(organiser_client, event.id).status_code == 200

    assert _notified(db, "EVENT_CANCELLED", event.id) == [Users.COORDINATOR.id]
    message = db.scalar(select(Notification.message).where(Notification.event_id == event.id))
    assert REASON in message


@pytest.mark.story("6.2", ac=5)
def test_with_no_coordinator_every_active_lead_is_told(organiser_client, db: Session):
    event = _event(db, status=EventStatus.UNDER_REVIEW, assigned_coordinator_id=None)
    make_user(db, role="EVENT_COORDINATOR_LEAD", is_active=False)

    assert _cancel(organiser_client, event.id).status_code == 200

    assert _notified(db, "EVENT_CANCELLED", event.id) == [Users.LEAD.id]


@pytest.mark.story("6.2", ac=5)
def test_registered_attendees_are_told(organiser_client, db: Session):
    event = _event(db, status=EventStatus.CONFIRMED, is_public=True, registration_required=True)
    _register(db, event, Users.ATTENDEE)
    _register(db, event, Users.ATTENDEE_2, status=RegistrationStatus.WITHDRAWN)

    assert _cancel(organiser_client, event.id).status_code == 200

    assert _notified(db, "REGISTRATION_CANCELLED", event.id) == [Users.ATTENDEE.id]


@pytest.mark.story("6.2", ac=5)
def test_venue_staff_are_told_of_each_released_booking(organiser_client, db: Session):
    """Every active Venue Staff member, as 19.2 tells them of a booking it releases."""
    event = _event(db)
    booking = _booking(db, event)

    assert _cancel(organiser_client, event.id).status_code == 200

    [notice] = db.scalars(
        select(Notification).where(
            Notification.notification_type == "BOOKING_RELEASED",
            Notification.event_id == event.id,
        )
    ).all()
    assert notice.recipient_id == Users.VENUE_STAFF.id
    assert notice.related_entity_id == booking.id
    assert "was cancelled" in notice.message


@pytest.mark.story("6.2", ac=5)
@pytest.mark.parametrize(
    ("status", "is_told"),
    [
        (EquipmentRequestStatus.PENDING, True),
        (EquipmentRequestStatus.ACCEPTED, True),
        (EquipmentRequestStatus.REQUESTED, False),
    ],
)
def test_technical_support_are_told_only_of_items_sent_to_them(
    organiser_client, db: Session, status: str, is_told: bool
):
    """An item still only recorded was never sent to Technical Support, so nothing changed for
    them."""
    event = _event(db)
    _item(db, event, status=status)

    assert _cancel(organiser_client, event.id).status_code == 200

    expected = [Users.TECH_SUPPORT.id] if is_told else []
    assert _notified(db, "EQUIPMENT_WITHDRAWN", event.id) == expected


# --- AC6: which statuses can be cancelled ------------------------------------------------------
@pytest.mark.story("6.2", ac=6)
@pytest.mark.parametrize("status", CANCELLABLE)
def test_an_event_can_be_cancelled_from_each_open_status(organiser_client, db: Session, status):
    event = _event(db, status=status)

    response = _cancel(organiser_client, event.id)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == EventStatus.CANCELLED


@pytest.mark.story("6.2", ac=6)
@pytest.mark.parametrize("status", NOT_CANCELLABLE)
def test_a_closed_or_draft_event_cannot_be_cancelled(organiser_client, db: Session, status):
    event = _event(db, status=status)

    response = _cancel(organiser_client, event.id)

    assert response.status_code == 409, response.text
    words = status.lower().replace("_", " ")
    assert response.json()["detail"] == (
        f"This event is {words}, so it can no longer be cancelled."
    )
    db.expire_all()
    assert _status(db, Event, event.id) == status


# --- AC7: the reason is mandatory ------------------------------------------------------------
@pytest.mark.story("6.2", ac=7)
@pytest.mark.parametrize("reason", ["", "   ", None])
def test_a_missing_reason_is_refused(organiser_client, db: Session, reason):
    event = _event(db)

    response = _cancel(organiser_client, event.id, reason=reason)

    assert response.status_code == 422, response.text
    db.expire_all()
    assert _status(db, Event, event.id) == EventStatus.PLANNING


# --- AC8: nothing held -------------------------------------------------------------------------
@pytest.mark.story("6.2", ac=8)
def test_an_event_holding_nothing_can_be_cancelled(organiser_client, db: Session):
    event = _event(db, status=EventStatus.UNDER_REVIEW)

    response = _cancel(organiser_client, event.id)

    assert response.status_code == 200, response.text
    for notification_type in ("BOOKING_RELEASED", "EQUIPMENT_WITHDRAWN", "REGISTRATION_CANCELLED"):
        assert _notified(db, notification_type, event.id) == []


# --- AC9: kept as a record, closed to further work ----------------------------------------------
@pytest.mark.story("6.2", ac=9)
def test_a_cancelled_event_stays_visible(organiser_client, db: Session):
    event = _event(db)
    assert _cancel(organiser_client, event.id).status_code == 200

    detail = organiser_client.get(f"/events/{event.id}")
    mine = organiser_client.get("/events/mine", params={"limit": 100})

    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == EventStatus.CANCELLED
    assert detail.json()["cancellation_reason"] == REASON
    listed = {item["id"]: item["status"] for item in mine.json()["items"]}
    assert listed[str(event.id)] == EventStatus.CANCELLED


@pytest.mark.story("6.2", ac=9)
def test_a_cancelled_event_takes_no_new_booking_request(organiser_client, login_as, db: Session):
    event = _event(db)
    venue = make_venue(db)
    assert _cancel(organiser_client, event.id).status_code == 200

    response = login_as(Users.COORDINATOR).post(
        "/bookings", json={"event_id": str(event.id), "venue_id": str(venue.id)}
    )

    assert response.status_code == 409, response.text


@pytest.mark.story("6.2", ac=9)
def test_a_released_booking_cannot_be_approved(organiser_client, login_as, db: Session):
    event = _event(db)
    booking = _booking(db, event)
    assert _cancel(organiser_client, event.id).status_code == 200

    response = login_as(Users.VENUE_STAFF).post(
        f"/bookings/{booking.id}/approve", json=approval_payload()
    )

    assert response.status_code == 409, response.text


@pytest.mark.story("6.2", ac=9)
def test_equipment_on_a_cancelled_event_cannot_be_decided(organiser_client, login_as, db: Session):
    event = _event(db)
    item = _item(db, event, status=EquipmentRequestStatus.PENDING)
    assert _cancel(organiser_client, event.id).status_code == 200

    response = login_as(Users.TECH_SUPPORT).post(
        f"/equipment-requests/{item.id}/decision", json={"outcome": "ACCEPTED"}
    )

    assert response.status_code == 409, response.text


@pytest.mark.story("6.2", ac=9)
def test_a_cancelled_event_takes_no_registration(organiser_client, login_as, db: Session):
    event = _event(db, status=EventStatus.CONFIRMED, is_public=True, registration_required=True)
    assert _cancel(organiser_client, event.id).status_code == 200

    response = login_as(Users.ATTENDEE).post("/registrations", json={"event_id": str(event.id)})

    assert response.status_code == 404, response.text


@pytest.mark.story("6.2", ac=9)
def test_a_cancelled_event_takes_no_change_request(organiser_client, db: Session):
    event = _event(db)
    assert _cancel(organiser_client, event.id).status_code == 200

    response = organiser_client.post(
        f"/events/{event.id}/change-requests",
        json={"field": "expected_attendance", "proposed": 25, "reason": "More sign-ups."},
    )

    assert response.status_code == 409, response.text


# --- AC10: one transaction ---------------------------------------------------------------------
@pytest.mark.story("6.2", ac=10)
def test_a_failure_part_way_leaves_everything_as_it_was(
    organiser_client, db: Session, monkeypatch: pytest.MonkeyPatch
):
    """The event's own audit entry is written last, after every release, so failing it shows the
    releases before it are rolled back with it."""
    event = _event(db, status=EventStatus.CONFIRMED, is_public=True, registration_required=True)
    booking = _booking(db, event)
    item = _item(db, event, status=EquipmentRequestStatus.PENDING)
    request = make_change_request(db, event=event)
    registration = _register(db, event, Users.ATTENDEE)
    real_record_audit = cancellations_service.record_audit

    def record_audit(db: Session, *, action: str, **kwargs: Any) -> Any:
        if action == "EVENT_CANCELLED":
            raise RuntimeError("simulated failure recording the cancellation")
        return real_record_audit(db, action=action, **kwargs)

    monkeypatch.setattr(cancellations_service, "record_audit", record_audit)

    with pytest.raises(RuntimeError):
        _cancel(organiser_client, event.id)
    db.rollback()  # mirrors app.db.get_db's real teardown

    assert _status(db, Event, event.id) == EventStatus.CONFIRMED
    assert _status(db, VenueBooking, booking.id) == BookingStatus.PENDING
    assert _status(db, EventEquipmentRequest, item.id) == EquipmentRequestStatus.PENDING
    assert db.scalar(
        select(EquipmentReservation.status).where(
            EquipmentReservation.equipment_request_id == item.id
        )
    ) == (EquipmentHoldStatus.RESERVED)
    assert _status(db, EventChangeRequest, request.id) == "PENDING"
    assert _status(db, EventRegistration, registration.id) == RegistrationStatus.REGISTERED
    assert db.scalar(select(func.count()).where(Notification.event_id == event.id)) == 0


# --- AC11: only the owning organiser ----------------------------------------------------------
@pytest.mark.story("6.2", ac=11)
def test_signed_out_is_refused(client, db: Session):
    event = _event(db)

    assert _cancel(client, event.id).status_code == 401


@pytest.mark.story("6.2", ac=11)
@pytest.mark.parametrize(
    "user",
    [
        Users.COORDINATOR,
        Users.LEAD,
        Users.VENUE_STAFF,
        Users.TECH_SUPPORT,
        Users.SAFETY_OFFICER,
        Users.ATTENDEE,
    ],
    ids=lambda user: user.role,
)
def test_no_other_role_may_cancel(login_as, db: Session, user):
    """The assigned coordinator included: the organiser cancels their own event (PO decision)."""
    event = _event(db)

    response = _cancel(login_as(user), event.id)

    assert response.status_code == 403, response.text
    db.expire_all()
    assert _status(db, Event, event.id) == EventStatus.PLANNING


@pytest.mark.story("6.2", ac=11)
def test_another_organisers_event_is_not_found(login_as, db: Session):
    event = _event(db)

    response = _cancel(login_as(Users.ORGANISER_2), event.id)

    assert response.status_code == 404, response.text
    db.expire_all()
    assert _status(db, Event, event.id) == EventStatus.PLANNING


# --- AC12 / AC13: races ------------------------------------------------------------------------
def _backend_pid(session: Session) -> int:
    return session.connection().exec_driver_sql("SELECT pg_backend_pid()").scalar()


def _wait_until_waiting(engine: Engine, pids: dict[str, int], name: str) -> None:
    """Block until the connection ``name`` stands waiting on a row lock another holds."""
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while time.monotonic() < deadline:
        if name in pids:
            with engine.connect() as watcher:
                waiting_on = watcher.execute(
                    text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                    {"pid": pids[name]},
                ).scalar()
            if waiting_on == "Lock":
                return
        time.sleep(0.05)
    raise AssertionError(f"{name} never waited on a lock")


def _committed_event(engine: Engine) -> uuid.UUID:
    with Session(engine) as session:
        event = _event(session)
        session.commit()
        return event.id


def _delete_committed(
    engine: Engine,
    event_id: uuid.UUID,
    *entity_ids: uuid.UUID,
    venue_id: uuid.UUID | None = None,
    equipment_type_id: uuid.UUID | None = None,
) -> None:
    """Remove what a race committed: the event, whose bookings, equipment, history and
    notifications go with it (ON DELETE CASCADE), the audit entries, which have no foreign key,
    and the venue or equipment type made for the test."""
    with Session(engine) as session:
        session.execute(
            text("DELETE FROM audit_log WHERE entity_id = ANY(:ids)"),
            {"ids": [event_id, *entity_ids]},
        )
        session.execute(text("DELETE FROM events WHERE id = :id"), {"id": event_id})
        if venue_id is not None:
            session.execute(text("DELETE FROM venues WHERE id = :id"), {"id": venue_id})
        if equipment_type_id is not None:
            session.execute(
                text("DELETE FROM equipment_types WHERE id = :id"), {"id": equipment_type_id}
            )
        session.commit()


def _cancel_in(session: Session, event_id: uuid.UUID) -> None:
    organiser = session.get(User, Users.ORGANISER.id)
    cancellations_service.cancel_event(session, event_id, actor=organiser, reason=REASON)


@pytest.mark.story("6.2", ac=12)
def test_an_approval_racing_the_cancellation_ends_released(engine):
    """Venue Staff hold the booking to approve it; the cancellation waits on it. The approval then
    writes its notice, which needs the event row, and commits; the cancellation releases the
    booking as it now stands. Holding the event more strongly than an UPDATE needs would leave
    each waiting on the other: a deadlock."""
    event_id = _committed_event(engine)
    with Session(engine) as session:
        venue = make_venue(session)
        booking = _booking(session, session.get(Event, event_id), venue_id=venue.id)
        session.commit()
        booking_id, venue_id = booking.id, venue.id
    pids: dict[str, int] = {}
    holding, go = threading.Event(), threading.Event()

    def approve() -> None:
        with Session(engine) as session:
            locked = bookings_service.get_booking_for_decision(session, booking_id)
            holding.set()
            go.wait(LOCK_WAIT_SECONDS)
            bookings_service.approve_booking(
                session,
                locked,
                actor_id=Users.VENUE_STAFF.id,
                hold_expires_at=datetime.now(UTC) + timedelta(days=1),
            )

    def cancel() -> None:
        holding.wait(LOCK_WAIT_SECONDS)
        with Session(engine) as session:
            pids["cancel"] = _backend_pid(session)
            _cancel_in(session, event_id)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            approving = pool.submit(approve)
            cancelling = pool.submit(cancel)
            _wait_until_waiting(engine, pids, "cancel")
            go.set()
            approving.result(timeout=LOCK_WAIT_SECONDS)
            cancelling.result(timeout=LOCK_WAIT_SECONDS)

        with Session(engine) as session:
            released = session.get(VenueBooking, booking_id)
            assert released.status == BookingStatus.CANCELLED
            assert released.decided_by_id == Users.VENUE_STAFF.id
            assert session.get(Event, event_id).status == EventStatus.CANCELLED
    finally:
        go.set()
        _delete_committed(engine, event_id, booking_id, venue_id=venue_id)


@pytest.mark.story("6.2", ac=12)
def test_an_equipment_decision_racing_the_cancellation_leaves_no_reservation(engine):
    """Technical Support's decision holds the event, as it always does; the cancellation waits
    on it, then releases the reservation the acceptance made."""
    event_id = _committed_event(engine)
    with Session(engine) as session:
        item = _item(session, session.get(Event, event_id), status=EquipmentRequestStatus.PENDING)
        session.commit()
        item_id, type_id = item.id, item.equipment_type_id
    pids: dict[str, int] = {}
    holding, go = threading.Event(), threading.Event()

    def decide() -> None:
        with Session(engine) as session:
            session.execute(select(Event.id).where(Event.id == event_id).with_for_update())
            holding.set()
            go.wait(LOCK_WAIT_SECONDS)
            equipment_service.decide_equipment_request(
                session,
                item_id,
                EquipmentDecisionIn(outcome="ACCEPTED"),
                actor=session.get(User, Users.TECH_SUPPORT.id),
            )

    def cancel() -> None:
        holding.wait(LOCK_WAIT_SECONDS)
        with Session(engine) as session:
            pids["cancel"] = _backend_pid(session)
            _cancel_in(session, event_id)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            deciding = pool.submit(decide)
            cancelling = pool.submit(cancel)
            _wait_until_waiting(engine, pids, "cancel")
            go.set()
            deciding.result(timeout=LOCK_WAIT_SECONDS)
            cancelling.result(timeout=LOCK_WAIT_SECONDS)

        with Session(engine) as session:
            assert session.get(EventEquipmentRequest, item_id).status == "CANCELLED"
            reserved = session.scalar(
                select(func.count()).where(
                    EquipmentReservation.event_id == event_id,
                    EquipmentReservation.status == EquipmentHoldStatus.RESERVED,
                )
            )
            assert reserved == 0
    finally:
        go.set()
        _delete_committed(engine, event_id, item_id, equipment_type_id=type_id)


@pytest.mark.story("6.2", ac=12)
def test_a_booking_request_racing_the_cancellation_is_refused(engine):
    """The cancellation holds the event; a booking request for it waits, then reads it Cancelled
    and is refused, rather than leaving a new hold on a cancelled event."""
    event_id = _committed_event(engine)
    with Session(engine) as session:
        venue_id = make_venue(session).id
        session.commit()
    pids: dict[str, int] = {}
    holding, go = threading.Event(), threading.Event()

    def cancel() -> None:
        with Session(engine) as session:
            session.execute(
                select(Event.id).where(Event.id == event_id).with_for_update(key_share=True)
            )
            holding.set()
            go.wait(LOCK_WAIT_SECONDS)
            _cancel_in(session, event_id)

    def request() -> str:
        holding.wait(LOCK_WAIT_SECONDS)
        # The request commits once, expiring lapsed holds, before it reads the event; one
        # connection throughout keeps the pid watched the one that waits.
        with engine.connect() as connection, Session(bind=connection) as session:
            pids["request"] = _backend_pid(session)
            try:
                bookings_service.create_booking_request(
                    session,
                    BookingRequestIn(event_id=event_id, venue_id=venue_id),
                    actor=session.get(User, Users.COORDINATOR.id),
                )
            except bookings_service.EventNotBookable:
                return "refused"
            return "created"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            cancelling = pool.submit(cancel)
            requesting = pool.submit(request)
            _wait_until_waiting(engine, pids, "request")
            go.set()
            cancelling.result(timeout=LOCK_WAIT_SECONDS)
            assert requesting.result(timeout=LOCK_WAIT_SECONDS) == "refused"
    finally:
        go.set()
        _delete_committed(engine, event_id, venue_id=venue_id)


@pytest.mark.story("6.2", ac=13)
def test_a_second_cancellation_is_refused_and_repeats_nothing(organiser_client, db: Session):
    event = _event(db)
    _booking(db, event)
    assert _cancel(organiser_client, event.id).status_code == 200
    notices = db.scalar(select(func.count()).where(Notification.event_id == event.id))

    response = _cancel(organiser_client, event.id, reason="Cancelling again.")

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "This event is cancelled, so it can no longer be cancelled."
    assert db.scalar(select(func.count()).where(Notification.event_id == event.id)) == notices
    audits = db.scalar(
        select(func.count()).where(
            AuditLog.entity_id == event.id, AuditLog.action == "EVENT_CANCELLED"
        )
    )
    assert audits == 1
    db.expire_all()
    assert db.get(Event, event.id).cancellation_reason == REASON


@pytest.mark.story("6.2", ac=13)
def test_two_cancellations_at_once_cancel_once(engine):
    """A double click: both reach the server together; one cancels, the other is refused."""
    event_id = _committed_event(engine)
    start = threading.Barrier(2, timeout=LOCK_WAIT_SECONDS)

    def attempt() -> str:
        with Session(engine) as session:
            start.wait()
            try:
                _cancel_in(session, event_id)
            except cancellations_service.EventNotCancellable:
                return "refused"
            return "cancelled"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt) for _ in range(2)]
            outcomes = sorted(future.result(timeout=LOCK_WAIT_SECONDS) for future in futures)
        assert outcomes == ["cancelled", "refused"]
        with Session(engine) as session:
            history = session.scalar(
                select(func.count()).where(
                    EventStatusHistory.event_id == event_id,
                    EventStatusHistory.to_status == EventStatus.CANCELLED,
                )
            )
            assert history == 1
    finally:
        _delete_committed(engine, event_id)


# --- AC14 / AC15 / AC16: what Venue Staff and Technical Support see afterwards ----------------
def _queue_ids(client, path: str, **params: Any) -> list[str]:
    """Every id in one tab of a queue, page by page where the queue pages."""
    ids: list[str] = []
    while True:
        body = client.get(path, params={**params, "offset": len(ids)}).json()
        ids += [item["id"] for item in body["items"]]
        if len(ids) >= body.get("total", len(ids)):
            return ids


def _sent_item(db: Session, event: Event, *, status: str) -> EventEquipmentRequest:
    """An item the coordinator has sent to Technical Support."""
    item = _item(db, event, status=status, is_held=status != EquipmentRequestStatus.DECLINED)
    item.submitted_by_id = Users.COORDINATOR.id
    item.submitted_at = datetime.now(UTC)
    db.flush()
    return item


def _cancelled_by_organiser(login_as, event: Event) -> None:
    assert _cancel(login_as(Users.ORGANISER), event.id).status_code == 200


@pytest.mark.story("6.2", ac=14)
def test_venue_staff_see_a_released_booking_under_cancelled_and_all(login_as, db: Session):
    """The bookings queue already had a Cancelled tab (13.1.2), so this passed before AC14's
    change, which is the page's tab."""
    event = _event(db)
    booking = _booking(db, event, status=BookingStatus.APPROVED)
    before = login_as(Users.VENUE_STAFF).get("/bookings").json()["counts"]["cancelled"]

    _cancelled_by_organiser(login_as, event)

    staff = login_as(Users.VENUE_STAFF)
    assert str(booking.id) in _queue_ids(staff, "/bookings", status="CANCELLED")
    assert str(booking.id) in _queue_ids(staff, "/bookings")
    assert staff.get("/bookings").json()["counts"]["cancelled"] == before + 1


@pytest.mark.story("6.2", ac=15)
@pytest.mark.parametrize(
    "status", [EquipmentRequestStatus.PENDING, EquipmentRequestStatus.ACCEPTED]
)
def test_technical_support_see_a_sent_item_under_cancelled_and_all(
    login_as, db: Session, status: str
):
    event = _event(db)
    item = _sent_item(db, event, status=status)
    before = login_as(Users.TECH_SUPPORT).get("/equipment-requests").json()["counts"]

    _cancelled_by_organiser(login_as, event)

    tech = login_as(Users.TECH_SUPPORT)
    cancelled = tech.get("/equipment-requests", params={"status": "CANCELLED"})
    assert cancelled.status_code == 200, cancelled.text
    assert str(item.id) in [row["id"] for row in cancelled.json()["items"]]
    assert str(item.id) in _queue_ids(tech, "/equipment-requests")
    after = tech.get("/equipment-requests").json()["counts"]
    assert after["cancelled"] == before["cancelled"] + 1
    assert after[status.lower()] == before[status.lower()] - 1
    page = tech.get(f"/equipment-requests/{item.id}")
    assert page.status_code == 200, page.text
    assert page.json()["status"] == EquipmentRequestStatus.CANCELLED


@pytest.mark.story("6.2", ac=15)
def test_technical_support_never_see_an_item_never_sent_to_them(login_as, db: Session):
    event = _event(db)
    item = _item(db, event, status=EquipmentRequestStatus.REQUESTED)
    before = login_as(Users.TECH_SUPPORT).get("/equipment-requests").json()["counts"]

    _cancelled_by_organiser(login_as, event)

    tech = login_as(Users.TECH_SUPPORT)
    assert str(item.id) not in _queue_ids(tech, "/equipment-requests")
    assert tech.get("/equipment-requests").json()["counts"] == before
    assert tech.get(f"/equipment-requests/{item.id}").status_code == 404


@pytest.mark.story("6.2", ac=15)
def test_a_cancelled_item_still_cannot_be_decided(login_as, db: Session):
    """Listed for the record only: the Cancelled tab is read-only."""
    event = _event(db)
    item = _sent_item(db, event, status=EquipmentRequestStatus.PENDING)
    _cancelled_by_organiser(login_as, event)

    response = login_as(Users.TECH_SUPPORT).post(
        f"/equipment-requests/{item.id}/decision", json={"outcome": "ACCEPTED"}
    )

    assert response.status_code == 409, response.text
    assert _status(db, EventEquipmentRequest, item.id) == EquipmentRequestStatus.CANCELLED


@pytest.mark.story("6.2", ac=16)
def test_a_released_booking_records_when_it_was_cancelled(login_as, db: Session):
    """Who approved it and when stay beside the new time, on every view of the booking."""
    event = _event(db)
    booking = _booking(db, event, status=BookingStatus.APPROVED)
    kept = _booking(db, event, status=BookingStatus.WITHDRAWN)
    approved_at = booking.decided_at
    before = datetime.now(UTC)

    _cancelled_by_organiser(login_as, event)

    db.expire_all()
    released = db.get(VenueBooking, booking.id)
    assert released.cancelled_at >= before
    assert released.decided_at == approved_at
    assert db.get(VenueBooking, kept.id).cancelled_at is None
    staff = login_as(Users.VENUE_STAFF)
    full = staff.get(f"/bookings/{booking.id}").json()
    assert full["cancelled_at"] is not None
    assert full["decided_at"] is not None
    tab = staff.get("/bookings", params={"status": "CANCELLED"}).json()["items"]
    [entry] = [row for row in tab if row["id"] == str(booking.id)]
    assert entry["cancelled_at"] == full["cancelled_at"]
    outcomes = login_as(Users.COORDINATOR).get(f"/bookings/for-event/{event.id}").json()
    by_id = {row["id"]: row for row in outcomes}
    assert by_id[str(booking.id)]["cancelled_at"] == full["cancelled_at"]
    assert by_id[str(kept.id)]["cancelled_at"] is None


@pytest.mark.story("6.2", ac=16)
def test_a_cancelled_item_records_when_it_was_cancelled(login_as, db: Session):
    event = _event(db)
    item = _sent_item(db, event, status=EquipmentRequestStatus.PENDING)
    declined = _sent_item(db, event, status=EquipmentRequestStatus.DECLINED)
    before = datetime.now(UTC)

    _cancelled_by_organiser(login_as, event)

    db.expire_all()
    assert db.get(EventEquipmentRequest, item.id).cancelled_at >= before
    assert db.get(EventEquipmentRequest, declined.id).cancelled_at is None
    entry = login_as(Users.TECH_SUPPORT).get(f"/equipment-requests/{item.id}").json()
    assert entry["cancelled_at"] is not None


@pytest.mark.story("6.2", ac=16)
def test_a_change_removing_an_item_records_when_and_reviving_it_clears_it(db: Session):
    """19.2 closes a removed item as Cancelled too, and an approved change can bring it back."""
    event = _event(db)
    item = _sent_item(db, event, status=EquipmentRequestStatus.PENDING)
    actor = db.get(User, Users.COORDINATOR.id)
    db.refresh(event)

    equipment_service.apply_equipment_change(db, event, [], actor=actor)
    db.refresh(item)
    assert item.status == EquipmentRequestStatus.CANCELLED
    assert item.cancelled_at is not None

    line = EventEquipmentIn(
        id=item.id, equipment_type_code=item.equipment_type.code, quantity=item.quantity
    )
    equipment_service.apply_equipment_change(db, event, [line], actor=actor)
    db.refresh(item)
    assert item.status != EquipmentRequestStatus.CANCELLED
    assert item.cancelled_at is None
