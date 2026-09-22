"""HTTP endpoints for story 2.1 (event requests), story 2.6 (list my event requests), story 4.1
(coordinator review queue), stories 4.4/4.5 (approve / reject an event request), and story 4.6
(the decision /clarification history an organiser sees),
and story 7.2 (routine information edits)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_any_permission, require_permission
from app.auth.permissions import Permission
from app.db import get_db
from app.events import service
from app.events.schemas import (
    ClarificationOut,
    EquipmentAvailabilityOut,
    EventCreate,
    EventDetailOut,
    EventReferenceData,
    EventRejection,
    EventRoutineUpdate,
    EventUpdate,
    MyEventEntry,
    MyEventList,
    ReviewQueueEntry,
    ReviewQueueSort,
)

router = APIRouter(prefix="/events", tags=["events"])

CanReview = Depends(require_permission(Permission.EVENTS_REVIEW))
CanCreate = Depends(require_permission(Permission.EVENTS_CREATE))
CanEditRoutine = Depends(require_permission(Permission.EVENTS_EDIT_ROUTINE))
CanReadOwn = Depends(require_permission(Permission.EVENTS_READ_OWN))
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
@router.get("/mine", response_model=MyEventList)
def list_my_events(
    db: DbSession,
    actor: Annotated[CurrentUser, CanReadOwn],
    limit: Annotated[
        int, Query(ge=1, le=service.MY_EVENTS_MAX_LIMIT)
    ] = service.MY_EVENTS_MAX_LIMIT,
    offset: Annotated[int, Query(ge=0, le=service.MY_EVENTS_MAX_OFFSET)] = 0,
) -> MyEventList:
    """Story 2.6 AC1-AC6: the signed-in organiser's own requests, newest activity first. AC9: a
    page of them and the total. AC7: events:read_own only - other roles get 403 from the
    dependency (1.2 AC4). Nothing here names another organiser, so nobody else's can be asked
    for (AC3)."""
    listing = service.list_my_events(db, organiser=actor, limit=limit, offset=offset)
    return MyEventList(
        items=[MyEventEntry.from_event(e) for e in listing.events], total=listing.total
    )


@router.get("/reference-data", response_model=EventReferenceData, dependencies=[CanCreate])
def list_reference_data(db: DbSession) -> EventReferenceData:
    """Story 2.1 AC4-AC6: the pick-lists for the request form."""
    return service.list_reference_data(db)


@router.get(
    "/equipment-availability",
    response_model=list[EquipmentAvailabilityOut],
    dependencies=[CanCreate],
)
def list_equipment_availability(
    db: DbSession,
    starts_at: Annotated[AwareDatetime, Query()],
    ends_at: Annotated[AwareDatetime, Query()],
) -> list[EquipmentAvailabilityOut]:
    """Story 2.1 AC6: how many of each equipment type are free for the proposed dates."""
    try:
        return service.list_equipment_availability(db, starts_at=starts_at, ends_at=ends_at)
    except service.InvalidEventRequest as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


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
    return EventDetailOut.from_event(event, viewer=actor)


@router.get("/{event_id}", response_model=EventDetailOut, dependencies=[CanRead])
def get_event(
    event_id: uuid.UUID,
    db: DbSession,
    viewer: CurrentUser,
) -> EventDetailOut:
    """Story 2.1 AC8: the organiser reads their own request; internal roles read submitted ones."""
    try:
        event = service.get_event(db, event_id, viewer=viewer)
        return EventDetailOut.from_event(event, viewer=viewer)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None


@router.get(
    "/{event_id}/clarifications", response_model=list[ClarificationOut], dependencies=[CanRead]
)
def list_clarifications(
    event_id: uuid.UUID,
    db: DbSession,
    viewer: CurrentUser,
) -> list[ClarificationOut]:
    """Story 4.6 AC2: the clarification conversation, oldest first. AC3: read-only - no route
    edits or removes an entry."""
    try:
        rows = service.list_clarifications(db, event_id, viewer=viewer)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.NotRelatedParty as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    return [ClarificationOut.from_clarification(row) for row in rows]


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
    return EventDetailOut.from_event(event, viewer=actor)


@router.patch("/{event_id}/routine-information", response_model=EventDetailOut)
def update_routine_information(
    event_id: uuid.UUID,
    payload: EventRoutineUpdate,
    db: DbSession,
    actor: Annotated[CurrentUser, CanEditRoutine],
) -> EventDetailOut:
    """Story 7.2 AC1-AC3: the coordinator assigned to this event edits its routine fields
    (description, contact details, internal notes) directly, while the event is not completed,
    cancelled or rejected."""
    try:
        event = service.get_event(db, event_id, viewer=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    try:
        service.update_routine_information(db, event, payload, actor=actor)
    except service.NotAssignedCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.EventStateConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return EventDetailOut.from_event(event, viewer=actor)


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
    return EventDetailOut.from_event(event, viewer=actor)


@router.post("/{event_id}/approve", response_model=EventDetailOut)
def approve_event(
    event_id: uuid.UUID,
    db: DbSession,
    actor: Annotated[CurrentUser, CanReview],
) -> EventDetailOut:
    """4.4 AC1-AC3: approves the request, recording the deciding coordinator and time."""
    try:
        event = service.get_event(db, event_id, viewer=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    try:
        service.approve_event(db, event, actor=actor)
    except service.NotAssignedCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.EventStateConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return EventDetailOut.from_event(event, viewer=actor)


@router.post("/{event_id}/reject", response_model=EventDetailOut)
def reject_event(
    event_id: uuid.UUID,
    payload: EventRejection,
    db: DbSession,
    actor: Annotated[CurrentUser, CanReview],
) -> EventDetailOut:
    """4.5 AC1-AC3: rejects the request with a reason, recording the deciding coordinator and
    time. AC1 (reason mandatory) is enforced by ``EventRejection`` - a blank body is a 422
    before this function runs.
    """
    try:
        event = service.get_event(db, event_id, viewer=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    try:
        service.reject_event(db, event, actor=actor, reason=payload.reason)
    except service.NotAssignedCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.EventStateConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.InvalidEventRequest as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return EventDetailOut.from_event(event, viewer=actor)
