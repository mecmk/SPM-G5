"""Business logic for event review (story 4.1: the coordinator review queue)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events.models import Event, EventStatus
from app.events.schemas import ReviewQueueSort

_AWAITING_DECISION_STATUSES = (
    EventStatus.SUBMITTED,
    EventStatus.UNDER_REVIEW,
    EventStatus.CLARIFICATION_REQUESTED,
)
_SORT_COLUMNS = {
    ReviewQueueSort.SUBMITTED_AT: Event.submitted_at,
    ReviewQueueSort.STARTS_AT: Event.starts_at,
}

# --- reads -------------------------------------------------------------------------------


def list_review_queue(
    db: Session,
    *,
    sort: ReviewQueueSort = ReviewQueueSort.SUBMITTED_AT,
    coordinator_id: uuid.UUID | None = None,
) -> list[Event]:
    """AC1/AC4: only undecided submissions. AC3: ordered by submission or proposed date."""
    query = (
        select(Event)
        .where(Event.status.in_(_AWAITING_DECISION_STATUSES))
        .order_by(_SORT_COLUMNS[sort], Event.id)
    )
    if coordinator_id is not None:
        query = query.where(Event.assigned_coordinator_id == coordinator_id)
    return list(db.scalars(query).all())
