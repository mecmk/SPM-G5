"""HTTP endpoint for story 6.2: the Event Organiser cancels their own event, releasing what it
holds. It sits under the event it cancels (``/events/{event_id}/cancel``), beside 4.4/4.5's
approve and reject."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_permission
from app.auth.permissions import Permission
from app.bookings.deps import ReleaseLapsedHolds
from app.cancellations import service
from app.cancellations.schemas import EventCancellationIn
from app.db import get_db
from app.events import service as events_service
from app.events.schemas import EventDetailOut

router = APIRouter(prefix="/events", tags=["cancellations"])

EVENT_NOT_FOUND_MESSAGE = "Event not found."

CanCancel = Depends(require_permission(Permission.EVENTS_CANCEL))
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/{event_id}/cancel", response_model=EventDetailOut, dependencies=[ReleaseLapsedHolds])
def cancel_event(
    event_id: uuid.UUID,
    payload: EventCancellationIn,
    db: DbSession,
    actor: Annotated[CurrentUser, CanCancel],
) -> EventDetailOut:
    """AC1: cancels the organiser's own event with a reason and returns it, now Cancelled. AC7: a
    blank reason is refused (422) by ``EventCancellationIn``. AC11: another role is refused (403)
    by the permission, another organiser's event is not found (404). AC6/AC13: an event that can
    no longer be cancelled, a second cancellation included, is refused (409). Story 12.7: lapsed
    holds are expired first, so a hold that already ended is recorded as expired, not released."""
    try:
        event = service.cancel_event(db, event_id, actor=actor, reason=payload.reason)
    except events_service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.EventNotCancellable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return EventDetailOut.from_event(event, viewer=actor)
