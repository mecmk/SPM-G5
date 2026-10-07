"""HTTP endpoint for in-app notifications (story 20.1).

``GET /notifications`` - the signed-in user's own notifications, newest first (AC2)

Every role holds ``notifications:read_own``. Who receives what is decided where each action is
taken, through ``service.notify``; this endpoint only reads.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_permission
from app.auth.permissions import Permission
from app.db import get_db
from app.notifications import service
from app.notifications.schemas import NotificationOut

router = APIRouter(prefix="/notifications", tags=["notifications"])

CanReadOwn = Depends(require_permission(Permission.NOTIFICATIONS_READ_OWN))
DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    db: DbSession,
    viewer: Annotated[CurrentUser, CanReadOwn],
) -> list[NotificationOut]:
    """AC2: a notification is listed for its recipient as soon as its action commits, with
    nothing for them to do first. AC5: only the viewer's own; 401 when signed out."""
    return [
        NotificationOut.model_validate(notification)
        for notification in service.list_notifications(db, recipient=viewer)
    ]
