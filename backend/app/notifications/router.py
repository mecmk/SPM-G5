"""HTTP endpoints for in-app notifications (stories 20.1, 20.2).

``GET /notifications`` - the signed-in user's own notifications, newest first (20.1 AC2), each
with its ``read_at`` and where opening it goes (20.2 AC1, AC4)
``GET /notifications/unread-count`` - how many they have not read (20.2 AC2, AC3)
``PATCH /notifications/{notification_id}`` - mark one of their own read (20.2 AC1)
``PATCH /notifications`` - mark read everything up to the newest they had loaded (20.2 AC1)

Every role holds ``notifications:read_own``. Who receives what is decided where each action is
taken, through ``service.notify``; these endpoints read and mark only the caller's own rows.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_permission
from app.auth.permissions import Permission
from app.db import get_db
from app.notifications import service, targets
from app.notifications.schemas import (
    MarkAllReadIn,
    MarkedOut,
    MarkReadIn,
    NotificationOut,
    UnreadCountOut,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])

CanReadOwn = Depends(require_permission(Permission.NOTIFICATIONS_READ_OWN))
DbSession = Annotated[Session, Depends(get_db)]

NOTIFICATION_NOT_FOUND_MESSAGE = "Notification not found."


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    db: DbSession,
    viewer: Annotated[CurrentUser, CanReadOwn],
) -> list[NotificationOut]:
    """AC2: a notification is listed for its recipient as soon as its action commits, with
    nothing for them to do first. AC5: only the viewer's own; 401 when signed out."""
    return [
        NotificationOut.from_listed(listed)
        for listed in targets.with_targets(
            db, viewer=viewer, notifications=service.list_notifications(db, recipient=viewer)
        )
    ]


@router.get("/unread-count", response_model=UnreadCountOut)
def unread_count(
    db: DbSession,
    viewer: Annotated[CurrentUser, CanReadOwn],
) -> UnreadCountOut:
    """20.2 AC2/AC3: every unread notification of the viewer, not capped at the list's 50."""
    return UnreadCountOut(count=service.unread_count(db, recipient=viewer))


@router.patch("/{notification_id}", response_model=NotificationOut)
def mark_read(
    notification_id: uuid.UUID,
    payload: MarkReadIn,
    db: DbSession,
    viewer: Annotated[CurrentUser, CanReadOwn],
) -> NotificationOut:
    """20.2 AC1/AC6: mark one read; again changes nothing. AC5: someone else's, or an id that
    is none, is the same 404."""
    try:
        notification = service.mark_read(db, notification_id, recipient=viewer)
    except service.NotificationNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOTIFICATION_NOT_FOUND_MESSAGE) from None
    [listed] = targets.with_targets(db, viewer=viewer, notifications=[notification])
    return NotificationOut.from_listed(listed)


@router.patch("", response_model=MarkedOut)
def mark_all_read(
    payload: MarkAllReadIn,
    db: DbSession,
    viewer: Annotated[CurrentUser, CanReadOwn],
) -> MarkedOut:
    """20.2 AC1: mark read everything up to ``through_id``, which must be the viewer's own."""
    try:
        marked = service.mark_all_read(db, payload.through_id, recipient=viewer)
    except service.NotificationNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOTIFICATION_NOT_FOUND_MESSAGE) from None
    return MarkedOut(marked=marked)
