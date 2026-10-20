"""In-app notifications: generated and routed for story 20.1, listed for their recipient.

Every notification is written through ``notify``, inside the transaction of the action it reports,
before that action commits::

    notify(db, recipient=event.organiser, actor=coordinator,
           notification_type=NotificationType.EVENT_APPROVED, event_id=event.id,
           title='"Nimbus Developer Conference" was approved',
           message="Chloe Coordinator approved your request. It is now being planned.",
           related_entity_type="event", related_entity_id=event.id, commit=False)

Story 20.1:

* AC1 each action sends one ``NotificationType``, recording the action (the type), the event
  (``event_id``), the record to open (``related_entity_type`` / ``related_entity_id``) and the
  time (``created_at``);
* AC2 ``list_notifications`` is the recipient's list, filled the moment the action commits;
* AC3 ``notify`` writes nothing for the user who performed the action;
* AC4 written in the action's transaction, so an action that fails or is refused leaves none,
  and the services work the recipient out when they send it, so after a reassignment "the
  coordinator" is the new one;
* AC5 ``NotificationType`` names who receives each type, ``active_members`` is a role's audience,
  and ``notify`` refuses any other type;
* AC6 ``created_at`` is stamped from the clock and the list is newest first, so actions in quick
  succession keep their order. A repeated action is refused by the action's own guard, so it
  notifies once.

The list in the app - unread marking, the count, opening an item, marking read - is story 20.2.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.notifications.models import Notification

# AC2: the most of a recipient's notifications the list returns, newest first - the bell's own cap.
NOTIFICATION_LIST_LIMIT = 50


class NotificationType(StrEnum):
    """AC5: every kind of notification, and who receives it. ``notify`` refuses any other type,
    so a story that sends a new kind adds it here, with its recipients, in the same change.
    "The coordinator" is always the event's coordinator when the notification is sent (AC4), and
    "Venue Staff" and "Technical Support" every active member of that role (``active_members``)."""

    EVENT_SUBMITTED = "EVENT_SUBMITTED"  # 2.1: every active Event Coordinator Lead (5.4)
    EVENT_CLARIFICATION_REQUESTED = "EVENT_CLARIFICATION_REQUESTED"  # 4.2: the organiser
    EVENT_CLARIFICATION_RESPONDED = "EVENT_CLARIFICATION_RESPONDED"  # 4.3: the coordinator
    EVENT_APPROVED = "EVENT_APPROVED"  # 4.4: the organiser
    EVENT_REJECTED = "EVENT_REJECTED"  # 4.5: the organiser
    EVENT_ASSIGNED_TO = "EVENT_ASSIGNED_TO"  # 5.4: the coordinator the Lead assigned
    EVENT_ASSIGNED_ORGANISER = "EVENT_ASSIGNED_ORGANISER"  # 5.4: the organiser
    EVENT_REASSIGNED_FROM = "EVENT_REASSIGNED_FROM"  # 5.2: the previous coordinator
    EVENT_REASSIGNED_TO = "EVENT_REASSIGNED_TO"  # 5.2: the new coordinator
    EVENT_REASSIGNED_ORGANISER = "EVENT_REASSIGNED_ORGANISER"  # 5.2: the organiser
    BOOKING_REQUESTED = "BOOKING_REQUESTED"  # 12.1: Venue Staff
    BOOKING_WITHDRAWN = "BOOKING_WITHDRAWN"  # 12.2: Venue Staff
    # 12.6: every other active Venue Staff member, when approving a replacement released the
    # booking it replaces
    BOOKING_REPLACED = "BOOKING_REPLACED"
    BOOKING_RELEASED = "BOOKING_RELEASED"  # 19.2: Venue Staff, when an approved change unfits it
    BOOKING_APPROVED = "BOOKING_APPROVED"  # 13.2: the coordinator
    BOOKING_REJECTED = "BOOKING_REJECTED"  # 13.2.1: the coordinator
    BOOKING_HOLD_EXPIRING = "BOOKING_HOLD_EXPIRING"  # 12.7: the coordinator, from the system
    BOOKING_HOLD_EXPIRED = "BOOKING_HOLD_EXPIRED"  # 12.7: the coordinator, from the system
    BOOKING_HOLD_EXPIRY_CHANGED = "BOOKING_HOLD_EXPIRY_CHANGED"  # 12.7: the coordinator
    EQUIPMENT_SUBMITTED = "EQUIPMENT_SUBMITTED"  # 15.1: Technical Support
    EQUIPMENT_WITHDRAWN = "EQUIPMENT_WITHDRAWN"  # 19.2: Technical Support, items changed or removed
    EVENT_CHANGE_REQUESTED = "EVENT_CHANGE_REQUESTED"  # 19.1: the coordinator
    EVENT_CHANGE_REQUEST_WITHDRAWN = "EVENT_CHANGE_REQUEST_WITHDRAWN"  # 19.1: the coordinator
    EVENT_CHANGE_APPROVED = "EVENT_CHANGE_APPROVED"  # 19.2: the organiser
    EVENT_CHANGE_REJECTED = "EVENT_CHANGE_REJECTED"  # 19.2: the organiser
    # 19.2: Safety Officers - an approved change sent a Confirmed or Awaiting event to Planning
    EVENT_RETURNED_TO_PLANNING = "EVENT_RETURNED_TO_PLANNING"
    # 9.4: the event's coordinator, if it has one, and its organiser - a venue it has booked was
    # marked unavailable for the period of a booking
    BOOKING_VENUE_UNAVAILABLE = "BOOKING_VENUE_UNAVAILABLE"
    # 21.2: Safety Officers and the organiser
    SAFETY_REVIEW_REQUESTED = "SAFETY_REVIEW_REQUESTED"
    SAFETY_APPROVED = "SAFETY_APPROVED"  # 21.2: the coordinator and the organiser
    SAFETY_CHANGES_REQUESTED = "SAFETY_CHANGES_REQUESTED"  # 21.2: the coordinator and organiser
    EVENT_CONFIRMED = "EVENT_CONFIRMED"  # 21.2: the organiser and Safety Officers
    # 6.2: the event's coordinator, or every Event Coordinator Lead when it has none
    EVENT_CANCELLED = "EVENT_CANCELLED"
    REGISTRATION_CANCELLED = "REGISTRATION_CANCELLED"  # 6.2: each registered attendee


def notify(
    db: Session,
    *,
    recipient: User | None,
    actor: User | None,
    notification_type: NotificationType,
    title: str,
    message: str,
    event_id: uuid.UUID | None = None,
    related_entity_type: str | None = None,
    related_entity_id: uuid.UUID | None = None,
    commit: bool = True,
) -> Notification | None:
    """Tell ``recipient`` about an action ``actor`` performed - ``None`` when the system acted.
    Returns the notification, or ``None`` when nothing was written: AC3, the recipient is the
    actor, or nobody is related yet (``recipient`` is ``None``, an event with no coordinator).

    AC5: ``notification_type`` must be a ``NotificationType`` member, or ``ValueError``.
    AC6: ``created_at`` is the moment of writing, not the column's ``now()``, which is the
    transaction's start and would give every notification one transaction writes the same time.
    """
    known_type = NotificationType(notification_type)
    if recipient is None or (actor is not None and recipient.id == actor.id):
        return None
    entry = Notification(
        recipient_id=recipient.id,
        event_id=event_id,
        notification_type=known_type,
        title=title,
        message=message,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        created_at=datetime.now(UTC),
    )
    db.add(entry)
    if commit:
        db.commit()
    else:
        db.flush()
    return entry


def active_members(db: Session, *, role_code: str) -> list[User]:
    """AC5: a whole role as an audience - its active members, the people who can act on the
    notification now, as 12.2's withdrawal first told Venue Staff. A named person (the organiser,
    the coordinator) is told whatever their state; a role is never told through an inactive
    account."""
    return list(
        db.scalars(select(User).where(User.role_code == role_code, User.is_active.is_(True)))
    )


def list_notifications(db: Session, *, recipient: User) -> list[Notification]:
    """AC2: ``recipient``'s own notifications, newest first, at most ``NOTIFICATION_LIST_LIMIT``.
    Written in the action's transaction, so one is here as soon as its action commits. The id
    breaks a tie between two written at the same instant, so the order is stable."""
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.recipient_id == recipient.id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(NOTIFICATION_LIST_LIMIT)
        )
    )
