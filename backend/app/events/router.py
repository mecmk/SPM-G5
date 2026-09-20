"""HTTP endpoints for story 4.1 (coordinator review queue)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.deps import require_permission
from app.auth.permissions import Permission
from app.db import get_db
from app.events import service
from app.events.schemas import (
    ReviewQueueEntry,
    ReviewQueueSort,
)

router = APIRouter(prefix="/events", tags=["events"])

CanReview = Depends(require_permission(Permission.EVENTS_REVIEW))
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/review-queue", response_model=list[ReviewQueueEntry], dependencies=[CanReview])
def list_review_queue(
    db: DbSession,
    sort: Annotated[ReviewQueueSort, Query()] = ReviewQueueSort.SUBMITTED_AT,
    coordinator_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ReviewQueueEntry]:
    """AC1-AC4. events:review only - other roles get 403 from the dependency (1.2 AC4)."""
    events = service.list_review_queue(db, sort=sort, coordinator_id=coordinator_id)
    return [ReviewQueueEntry.from_event(e) for e in events]
