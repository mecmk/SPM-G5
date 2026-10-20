"""Request and response shapes for in-app notifications (stories 20.1, 20.2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.notifications.models import Notification


class NotificationTargetOut(BaseModel):
    """20.2 AC1: where opening a notification goes, for the reader it was sent to - a kind of page
    and, for a page of one record, that record's id (``None`` for a page that needs none). The
    frontend turns the kind into its own route; the server never sends an address."""

    kind: str
    id: uuid.UUID | None


class NotificationOut(BaseModel):
    """20.1 AC1/AC2: one notification as its recipient reads it - what happened (the type, title
    and message), about which event and record, and when. 20.2: ``read_at`` is when the recipient
    read it (``None`` while unread), and ``target`` is where opening it goes, or ``None`` when its
    reader has no page for it, cannot open its item, or the item is gone (AC4)."""

    id: uuid.UUID
    notification_type: str
    title: str
    message: str
    event_id: uuid.UUID | None
    related_entity_type: str | None
    related_entity_id: uuid.UUID | None
    created_at: datetime
    read_at: datetime | None
    target: NotificationTargetOut | None

    @classmethod
    def from_notification(
        cls, notification: Notification, target: NotificationTargetOut | None
    ) -> NotificationOut:
        return cls(
            id=notification.id,
            notification_type=notification.notification_type,
            title=notification.title,
            message=notification.message,
            event_id=notification.event_id,
            related_entity_type=notification.related_entity_type,
            related_entity_id=notification.related_entity_id,
            created_at=notification.created_at,
            read_at=notification.read_at,
            target=target,
        )


class UnreadCountOut(BaseModel):
    """20.2 AC2/AC3: how many notifications the caller has not read, all of them."""

    count: int


class MarkReadIn(BaseModel):
    """20.2 AC1: mark one notification read. Only ``true`` is accepted - there is no unread."""

    model_config = ConfigDict(extra="forbid")

    is_read: Literal[True]


class MarkAllReadIn(BaseModel):
    """20.2 AC1: mark read everything up to and including ``through_id``, the newest notification
    the client had loaded, so what arrived after stays unread."""

    model_config = ConfigDict(extra="forbid")

    is_read: Literal[True]
    through_id: uuid.UUID


class MarkedOut(BaseModel):
    """20.2 AC1: how many notifications a mark-all-read marked."""

    marked: int
