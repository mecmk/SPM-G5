"""HTTP endpoints for story 21.1: the Safety Officer's safety check queue and detail."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.deps import require_permission
from app.auth.permissions import Permission
from app.db import get_db
from app.safety import service
from app.safety.schemas import SafetyCheckDetail, SafetyQueueEntry

router = APIRouter(prefix="/safety-checks", tags=["safety"])

SAFETY_CHECK_NOT_FOUND_MESSAGE = "No event awaiting a safety check was found."

CanReviewSafety = Depends(require_permission(Permission.SAFETY_REVIEW))
DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[SafetyQueueEntry], dependencies=[CanReviewSafety])
def list_safety_queue(
    db: DbSession,
    queue_status: Annotated[service.SafetyQueueStatus | None, Query(alias="status")] = None,
) -> list[SafetyQueueEntry]:
    """AC2: the events in one tab (Pending is the queue itself), or every tab without ``status``,
    oldest first. AC6: safety:review only - other roles get 403 from the dependency."""
    return [
        SafetyQueueEntry.from_event(
            item.event,
            approved_bookings=item.approved_bookings,
            safety_status=item.safety_status,
        )
        for item in service.list_safety_queue(db, status=queue_status)
    ]


@router.get("/{event_id}", response_model=SafetyCheckDetail, dependencies=[CanReviewSafety])
def get_safety_check(event_id: uuid.UUID, db: DbSession) -> SafetyCheckDetail:
    """AC3-AC5: everything about one event that affects safety, with what changed since its last
    review. An event neither awaiting the check nor reviewed is a 404. AC6: safety:review only."""
    try:
        check = service.get_safety_check(db, event_id)
    except service.SafetyCheckNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, SAFETY_CHECK_NOT_FOUND_MESSAGE) from None
    return SafetyCheckDetail.from_event(
        check.event,
        approved_bookings=check.approved_bookings,
        accepted_equipment=check.accepted_equipment,
        reviews=check.reviews,
        changes=check.changes,
    )
