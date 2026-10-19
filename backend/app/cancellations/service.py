"""Business rules for story 6.2: the Event Organiser cancels their own event, and everything it
holds is released.

``cancel_event`` does it all in one transaction (AC10): the event's pending and approved venue
bookings are released (AC2, with story 19.2's ``release_booking``), its equipment holds released
and open items closed (AC3/AC4), its registrations and pending change requests closed (AC4), and
the event marked Cancelled with who, when and why (AC5). Nothing is deleted.

Concurrency (AC12/AC13). Locks are taken in the order every other write takes them - the event,
then its bookings in id order, then the equipment types in id order - so a cancellation cannot
deadlock with any of them. The event is held ``FOR NO KEY UPDATE`` (``lock_own_event``): that
serialises the cancellation with every other write to the event (a second cancellation, a
registration, a change request decision, Technical Support's decision, a booking request), each of
which either lands first and is then released, or waits and is refused once the event reads
Cancelled. A Venue Staff approval holds only its booking, which the cancellation waits on before
releasing it as it then stands.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.permissions import RoleCode
from app.bookings import service as bookings_service
from app.change_requests import service as change_requests_service
from app.common.audit import record_audit
from app.equipment import service as equipment_service
from app.events import service as events_service
from app.events.models import Event, EventStatus
from app.notifications.service import NotificationType, active_members, notify
from app.registrations import service as registrations_service

# AC6: the statuses an event can be cancelled from. A draft was never submitted, and a
# completed, cancelled or rejected event is already over.
_CANCELLABLE_STATUSES = frozenset(
    {
        EventStatus.UNDER_REVIEW,
        EventStatus.CLARIFICATION_REQUESTED,
        EventStatus.PLANNING,
        EventStatus.AWAITING_SAFETY_CHECK,
        EventStatus.CONFIRMED,
    }
)
NOT_CANCELLABLE_MESSAGE = "This event is {status}, so it can no longer be cancelled."
# A draft was never submitted, so there was never anything to cancel.
DRAFT_NOT_CANCELLABLE_MESSAGE = "This event is still a draft, so there is nothing to cancel."

# AC5: what Venue Staff, the coordinator (or Lead) and each attendee are told.
_BOOKING_RELEASED_BECAUSE = "its event was cancelled"
_CANCELLED_TITLE = '"{event}" was cancelled'
_COORDINATOR_MESSAGE = '{organiser} cancelled "{event}". Reason: {reason}'
_ATTENDEE_MESSAGE = (
    'The organiser cancelled "{event}", so your registration was cancelled. Reason: {reason}'
)


class EventNotCancellable(events_service.EventStateConflict):
    """AC6/AC13: the event is not in a status it can be cancelled from - a second cancellation
    finds it already Cancelled."""

    def __init__(self, event: Event) -> None:
        super().__init__(
            DRAFT_NOT_CANCELLABLE_MESSAGE
            if event.status == EventStatus.DRAFT
            else NOT_CANCELLABLE_MESSAGE.format(status=equipment_service.as_words(event.status))
        )


def _notify_coordinator(db: Session, event: Event, *, actor: User, reason: str) -> None:
    """AC5: the event's assigned coordinator is told; an event nobody coordinates yet waits in
    the Lead's queue (story 5.4), so every active Event Coordinator Lead is told instead."""
    recipients = (
        [event.assigned_coordinator]
        if event.assigned_coordinator is not None
        else active_members(db, role_code=RoleCode.EVENT_COORDINATOR_LEAD)
    )
    for recipient in recipients:
        notify(
            db,
            recipient=recipient,
            actor=actor,
            notification_type=NotificationType.EVENT_CANCELLED,
            event_id=event.id,
            title=_CANCELLED_TITLE.format(event=event.name),
            message=_COORDINATOR_MESSAGE.format(
                organiser=actor.full_name, event=event.name, reason=reason
            ),
            related_entity_type="event",
            related_entity_id=event.id,
            commit=False,
        )


def _notify_attendees(
    db: Session, event: Event, attendee_ids: list[uuid.UUID], *, actor: User, reason: str
) -> None:
    """AC5: every attendee whose registration was cancelled is told why."""
    for attendee in db.scalars(select(User).where(User.id.in_(attendee_ids))):
        notify(
            db,
            recipient=attendee,
            actor=actor,
            notification_type=NotificationType.REGISTRATION_CANCELLED,
            event_id=event.id,
            title=_CANCELLED_TITLE.format(event=event.name),
            message=_ATTENDEE_MESSAGE.format(event=event.name, reason=reason),
            related_entity_type="event",
            related_entity_id=event.id,
            commit=False,
        )


def cancel_event(db: Session, event_id: uuid.UUID, *, actor: User, reason: str) -> Event:
    """AC1-AC13: ``actor`` cancels their own event with ``reason``.

    AC11: another organiser's event is not found (``EventNotFound``), as it is everywhere else;
    the permission keeps every other role out. AC6/AC13: an event not in ``_CANCELLABLE_STATUSES``
    is refused (``EventNotCancellable``), read under the event's row lock, so of two cancellations
    at once the second waits and finds it Cancelled. Then, in one transaction (AC10): the bookings
    are released (AC2), the equipment released and closed (AC3/AC4), the registrations and
    pending change requests closed (AC4), the event marked Cancelled - its review decision kept
    beside the cancellation - with a status history row and an audit entry, and the coordinator
    (or Lead) and attendees told (AC5). See the module docstring for the locking."""
    event = events_service.lock_own_event(db, event_id, actor=actor)
    if event.status not in _CANCELLABLE_STATUSES:
        raise EventNotCancellable(event)
    from_status = event.status
    cancelled_at = datetime.now(UTC)

    released_booking_ids = [
        str(booking.id)
        for booking in bookings_service.lock_holding_bookings(db, event.id)
        if bookings_service.release_booking(
            db,
            booking,
            actor=actor,
            because=_BOOKING_RELEASED_BECAUSE,
            details={"cause": "EVENT_CANCELLED"},
            at=cancelled_at,
        )
    ]
    closed_items = equipment_service.release_for_cancelled_event(
        db, event, actor=actor, at=cancelled_at
    )
    attendee_ids = registrations_service.cancel_for_event(db, event.id)
    closed_request_ids = change_requests_service.cancel_pending_for_event(db, event.id)

    event.status = EventStatus.CANCELLED
    event.cancelled_at = cancelled_at
    event.cancelled_by_id = actor.id
    event.cancellation_reason = reason
    db.flush()
    events_service.record_transition(
        db,
        event,
        from_status=from_status,
        to_status=EventStatus.CANCELLED,
        actor=actor,
        at=cancelled_at,
        reason=reason,
    )
    _notify_coordinator(db, event, actor=actor, reason=reason)
    _notify_attendees(db, event, attendee_ids, actor=actor, reason=reason)
    record_audit(
        db,
        actor=actor,
        action="EVENT_CANCELLED",
        entity_type="event",
        entity_id=event.id,
        details={
            "from_status": from_status,
            "reason": reason,
            "released_booking_ids": released_booking_ids,
            "cancelled_equipment_ids": [str(item.id) for item in closed_items],
            "cancelled_change_request_ids": [str(each) for each in closed_request_ids],
            "cancelled_registrations": len(attendee_ids),
        },
        commit=False,
    )
    db.commit()
    db.refresh(event)
    return event
