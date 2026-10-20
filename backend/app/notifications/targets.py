"""Where opening a notification goes (story 20.2 AC1, AC4).

A notification is sent to one person, so where it goes is worked out for that reader: the page
where their role acts on it, otherwise the event. ``with_targets`` answers for a whole page of
notifications at once, with one query each for the events, the bookings and the safety checks
they name, never one per row. It is its own module, not part of ``service.py``, because the
services of events, bookings and safety import ``notify`` from there, and this one imports them
for the rules that decide whether a page opens.

The server sends a kind of page and the record's id, never an address (the frontend owns its
routes). A reader who has no page for the type, cannot open the item, or finds it gone gets no
target (AC4).
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.permissions import Permission, permissions_for
from app.bookings import service as bookings_service
from app.events import service as events_service
from app.events.models import Event
from app.notifications.models import Notification
from app.notifications.service import NotificationType
from app.safety import service as safety_service

_VENUE_BOOKING = "venue_booking"


class TargetKind(StrEnum):
    """The pages a notification can open. The frontend maps each to a route."""

    EVENT = "event"  # the event's page: id = the event
    BOOKING_REQUEST = "booking_request"  # Venue Staff's page for one request: id = the booking
    EQUIPMENT_REQUESTS = "equipment_requests"  # Technical Support's queue: no id
    SAFETY_CHECK = "safety_check"  # the Safety Officer's check of one event: id = the event
    REGISTRATIONS = "registrations"  # the attendee's registrations: no id
    UNASSIGNED_EVENTS = "unassigned_events"  # the Lead's queue: no id
    CHANGE_REQUEST_QUEUE = "change_request_queue"  # the coordinator's queue: no id


# Where one notification goes: its kind of page and the record's id (``None`` for a page that
# needs none), or ``None`` for nowhere.
Target = tuple[TargetKind, uuid.UUID | None]


_T = NotificationType

# Who is sent where, by the permission that makes a role the audience (backend/STYLE.md: check a
# Permission, not a role name). A (permission, type) pair not listed here has no target.
_RULES: tuple[tuple[Permission, TargetKind, frozenset[NotificationType]], ...] = (
    (
        Permission.EVENTS_CREATE,  # the organiser: the event
        TargetKind.EVENT,
        frozenset(
            {
                _T.EVENT_CLARIFICATION_REQUESTED,
                _T.EVENT_APPROVED,
                _T.EVENT_REJECTED,
                _T.EVENT_ASSIGNED_ORGANISER,
                _T.EVENT_REASSIGNED_ORGANISER,
                _T.EVENT_CHANGE_APPROVED,
                _T.EVENT_CHANGE_REJECTED,
                _T.BOOKING_VENUE_UNAVAILABLE,
                _T.SAFETY_REVIEW_REQUESTED,
                _T.SAFETY_APPROVED,
                _T.SAFETY_CHANGES_REQUESTED,
                _T.EVENT_CONFIRMED,
            }
        ),
    ),
    (
        Permission.EVENTS_REVIEW,  # the coordinator: the event, except a new change request
        TargetKind.EVENT,
        frozenset(
            {
                _T.EVENT_CLARIFICATION_RESPONDED,
                _T.EVENT_ASSIGNED_TO,
                _T.EVENT_REASSIGNED_FROM,
                _T.EVENT_REASSIGNED_TO,
                _T.BOOKING_APPROVED,
                _T.BOOKING_REJECTED,
                _T.BOOKING_HOLD_EXPIRING,
                _T.BOOKING_HOLD_EXPIRED,
                _T.BOOKING_HOLD_EXPIRY_CHANGED,
                _T.BOOKING_VENUE_UNAVAILABLE,
                _T.SAFETY_APPROVED,
                _T.SAFETY_CHANGES_REQUESTED,
                _T.EVENT_CHANGE_REQUEST_WITHDRAWN,
            }
        ),
    ),
    (
        Permission.EVENTS_REVIEW,
        TargetKind.CHANGE_REQUEST_QUEUE,
        frozenset({_T.EVENT_CHANGE_REQUESTED}),
    ),
    (
        Permission.BOOKINGS_DECIDE,  # Venue Staff: the booking request
        TargetKind.BOOKING_REQUEST,
        frozenset(
            {_T.BOOKING_REQUESTED, _T.BOOKING_WITHDRAWN, _T.BOOKING_REPLACED, _T.BOOKING_RELEASED}
        ),
    ),
    (
        Permission.EQUIPMENT_MANAGE,  # Technical Support: their queue
        TargetKind.EQUIPMENT_REQUESTS,
        frozenset({_T.EQUIPMENT_SUBMITTED, _T.EQUIPMENT_WITHDRAWN}),
    ),
    (
        Permission.SAFETY_REVIEW,  # the Safety Officer: the check, if it opens, else the event
        TargetKind.SAFETY_CHECK,
        frozenset({_T.SAFETY_REVIEW_REQUESTED, _T.EVENT_CONFIRMED, _T.EVENT_RETURNED_TO_PLANNING}),
    ),
    (
        Permission.EVENTS_ASSIGN,  # the Lead: the queue while unassigned, else the event
        TargetKind.UNASSIGNED_EVENTS,
        frozenset({_T.EVENT_SUBMITTED}),
    ),
)

_KIND_BY_PERMISSION_AND_TYPE: dict[tuple[Permission, str], TargetKind] = {
    (permission, notification_type): kind
    for permission, kind, notification_types in _RULES
    for notification_type in notification_types
}


def _kind_for(reader: User, notification: Notification) -> TargetKind | None:
    for permission in permissions_for(reader.role_code):
        kind = _KIND_BY_PERMISSION_AND_TYPE.get((permission, notification.notification_type))
        if kind is not None:
            return kind
    return None


_NEEDS_THE_EVENT = frozenset(
    {TargetKind.EVENT, TargetKind.UNASSIGNED_EVENTS, TargetKind.SAFETY_CHECK}
)


def with_targets(
    db: Session, *, viewer: User, notifications: list[Notification]
) -> list[tuple[Notification, Target | None]]:
    """20.2 AC1/AC4: ``notifications`` (all ``viewer``'s own) with where each goes for ``viewer``.
    The events they name are read in one query and judged by the rule ``get_event`` applies, the
    bookings in one query, and the safety checks that open in one query by the rule
    ``get_safety_check`` applies."""
    kinds = {notification.id: _kind_for(viewer, notification) for notification in notifications}

    def event_ids_of(*wanted: TargetKind) -> set[uuid.UUID]:
        return {
            notification.event_id
            for notification in notifications
            if kinds[notification.id] in wanted and notification.event_id is not None
        }

    event_ids = event_ids_of(*_NEEDS_THE_EVENT)
    events: dict[uuid.UUID, Event] = {}
    if event_ids:
        events = {
            event.id: event for event in db.scalars(select(Event).where(Event.id.in_(event_ids)))
        }
    check_ids = event_ids_of(TargetKind.SAFETY_CHECK)
    open_checks: set[uuid.UUID] = set()
    if check_ids:
        open_checks = set(
            db.scalars(
                select(Event.id).where(
                    Event.id.in_(check_ids), safety_service.safety_check_is_open()
                )
            )
        )
    booking_ids = {
        notification.related_entity_id
        for notification in notifications
        if kinds[notification.id] is TargetKind.BOOKING_REQUEST
        and notification.related_entity_type == _VENUE_BOOKING
        and notification.related_entity_id is not None
    }
    bookings = bookings_service.existing_booking_ids(db, booking_ids) if booking_ids else set()

    def event_target(notification: Notification) -> Target | None:
        event = events.get(notification.event_id) if notification.event_id else None
        if event is None or not events_service.can_view_event(viewer, event):
            return None
        return (TargetKind.EVENT, event.id)

    def target_of(notification: Notification) -> Target | None:
        kind = kinds[notification.id]
        match kind:
            case None:
                return None
            case TargetKind.EVENT:
                return event_target(notification)
            case TargetKind.UNASSIGNED_EVENTS:
                event = events.get(notification.event_id) if notification.event_id else None
                if event is not None and event.assigned_coordinator_id is None:
                    return (kind, None)
                return event_target(notification)
            case TargetKind.SAFETY_CHECK:
                if notification.event_id in open_checks:
                    return (kind, notification.event_id)
                return event_target(notification)
            case TargetKind.BOOKING_REQUEST:
                if notification.related_entity_id in bookings:
                    return (kind, notification.related_entity_id)
                return None
            case _:
                return (kind, None)

    return [(notification, target_of(notification)) for notification in notifications]
