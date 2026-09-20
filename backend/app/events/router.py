"""HTTP endpoints for story 2.1 (event requests) and story 4.1 (coordinator review queue)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_any_permission, require_permission
from app.auth.permissions import Permission
from app.db import get_db
from app.events import service
from app.events.schemas import (
    EventCreate,
    EventDetailOut,
    EventReferenceData,
    EventUpdate,
    ReviewQueueEntry,
    ReviewQueueSort,
)

router = APIRouter(prefix="/events", tags=["events"])

CanReview = Depends(require_permission(Permission.EVENTS_REVIEW))
CanCreate = Depends(require_permission(Permission.EVENTS_CREATE))
CanRead = Depends(require_any_permission(Permission.EVENTS_READ_OWN, Permission.EVENTS_READ_ALL))
DbSession = Annotated[Session, Depends(get_db)]

EVENT_NOT_FOUND_MESSAGE = "Event not found."


@router.get("/review-queue", response_model=list[ReviewQueueEntry], dependencies=[CanReview])
def list_review_queue(
    db: DbSession,
    sort: Annotated[ReviewQueueSort, Query()] = ReviewQueueSort.SUBMITTED_AT,
    coordinator_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ReviewQueueEntry]:
    """AC1-AC4. events:review only - other roles get 403 from the dependency (1.2 AC4)."""
    events = service.list_review_queue(db, sort=sort, coordinator_id=coordinator_id)
    return [ReviewQueueEntry.from_event(e) for e in events]


# The fixed paths above and below stay ahead of "/{event_id}" so they are not read as an id.
@router.get("/reference-data", response_model=EventReferenceData, dependencies=[CanCreate])
def list_reference_data(db: DbSession) -> EventReferenceData:
    """Story 2.1 AC4-AC6: the pick-lists for the request form."""
    return service.list_reference_data(db)


@router.post("", response_model=EventDetailOut, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: EventCreate,
    db: DbSession,
    actor: Annotated[CurrentUser, CanCreate],
) -> EventDetailOut:
    """Story 2.1 AC1-AC6: an organiser records a request; it starts as a draft."""
    try:
        event = service.create_event(db, payload, actor=actor)
    except service.InvalidEventRequest as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return EventDetailOut.from_event(event)


@router.get("/{event_id}", response_model=EventDetailOut, dependencies=[CanRead])
def get_event(
    event_id: uuid.UUID,
    db: DbSession,
    viewer: CurrentUser,
) -> EventDetailOut:
    """Story 2.1 AC8: the organiser reads their own request; internal roles read submitted ones."""
    try:
        return EventDetailOut.from_event(service.get_event(db, event_id, viewer=viewer))
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None


@router.patch("/{event_id}", response_model=EventDetailOut)
def update_event(
    event_id: uuid.UUID,
    payload: EventUpdate,
    db: DbSession,
    actor: Annotated[CurrentUser, CanCreate],
) -> EventDetailOut:
    """Story 2.1 AC7: an organiser edits their own request until it is submitted."""
    try:
        event = service.update_event(db, event_id, payload, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.EventStateConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.InvalidEventRequest as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return EventDetailOut.from_event(event)


@router.post("/{event_id}/submit", response_model=EventDetailOut)
def submit_event(
    event_id: uuid.UUID,
    db: DbSession,
    actor: Annotated[CurrentUser, CanCreate],
) -> EventDetailOut:
    """Story 2.1 AC9-AC12: an organiser submits their own draft for review."""
    try:
        event = service.submit_event(db, event_id, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.EventStateConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.InvalidEventRequest as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return EventDetailOut.from_event(event)
