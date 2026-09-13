"""HTTP endpoints for event requests (story 2.1)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_permission
from app.auth.permissions import Permission
from app.db import get_db
from app.events import service
from app.events.schemas import EventCreate, EventOut, EventSummary, EventUpdate

router = APIRouter(prefix="/events", tags=["events"])

CanCreate = Depends(require_permission(Permission.EVENTS_CREATE))
DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: EventCreate,
    db: DbSession,
    actor: Annotated[CurrentUser, CanCreate],
) -> EventOut:
    """AC1: only an Event Organiser can create a request, with at minimum a name."""
    try:
        event = service.create_event(db, payload, actor=actor)
    except (service.UnknownReferenceCode, service.UnknownEquipmentType) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return EventOut.from_event(event)


@router.get("", response_model=list[EventSummary])
def list_events(db: DbSession, actor: CurrentUser) -> list[EventSummary]:
    """AC7/AC8: an organiser lists their own requests; a coordinator lists every request."""
    try:
        events = service.list_events(db, actor=actor)
    except service.NotPermittedToView as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    return [EventSummary.model_validate(e) for e in events]


@router.get("/{event_id}", response_model=EventOut)
def get_event(event_id: uuid.UUID, db: DbSession, actor: CurrentUser) -> EventOut:
    """AC8: all recorded details, requirements and equipment items are visible to the
    reviewing Event Coordinator (or to the owning organiser)."""
    try:
        event = service.get_event(db, event_id, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event request not found.") from None
    except service.NotPermittedToView as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    return EventOut.from_event(event)


@router.patch("/{event_id}", response_model=EventOut)
def update_event(
    event_id: uuid.UUID,
    payload: EventUpdate,
    db: DbSession,
    actor: Annotated[CurrentUser, CanCreate],
) -> EventOut:
    """AC7: any recorded detail, requirement or equipment item can be edited or removed before
    the request is submitted."""
    try:
        event = service.update_event(db, event_id, payload, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event request not found.") from None
    except service.NotPermittedToEdit as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.EventNotEditable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except (service.UnknownReferenceCode, service.UnknownEquipmentType) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except (service.EventPeriodInvalid, service.AccessibilityConflict) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return EventOut.from_event(event)


@router.post("/{event_id}/submit", response_model=EventOut)
def submit_event(
    event_id: uuid.UUID,
    db: DbSession,
    actor: Annotated[CurrentUser, CanCreate],
) -> EventOut:
    """AC9-12: submitting is a state transition (DRAFT -> SUBMITTED) with its own validation
    (completeness, ownership, one-way), not a plain field update - hence its own action-suffixed
    endpoint rather than folding it into PATCH, the same reasoning auth/router.py's /login and
    /logout already carry (see backend/STYLE.md "A URL names a resource" standing divergence)."""
    try:
        event = service.submit_event(db, event_id, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event request not found.") from None
    except service.NotPermittedToEdit as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.EventAlreadySubmitted as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.EventIncompleteForSubmission as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return EventOut.from_event(event)
