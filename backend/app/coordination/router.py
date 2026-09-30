"""HTTP endpoints for coordinator assignment (story 5.1).

``GET /coordinators``                  - the selectable coordinators (AC2)
``GET /events/{event_id}/coordinator`` - who currently owns the event (AC4)
``PUT /events/{event_id}/coordinator`` - assign / replace the coordinator (AC1, AC3)

Assignment is an event-review action, so it uses the existing ``EVENTS_REVIEW`` permission.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_permission
from app.auth.permissions import Permission
from app.coordination import service
from app.coordination.schemas import (
    AssignCoordinatorIn,
    CoordinatorOption,
    EventCoordinatorOut,
)
from app.db import get_db

router = APIRouter(tags=["coordination"])

CanReadInternalUsers = Depends(require_permission(Permission.USERS_READ_INTERNAL))
CanReview = Depends(require_permission(Permission.EVENTS_REVIEW))
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/coordinators", response_model=list[CoordinatorOption])
def list_coordinators(
    db: DbSession,
    _actor: Annotated[CurrentUser, CanReadInternalUsers],
    exclude_event_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[CoordinatorOption]:
    """5.1 AC2: the pick-list for the assignment form holds Event Coordinators and nobody else.
    5.2 AC4: pass ``exclude_event_id`` for the reassignment picker, which leaves that event's
    current coordinator out of its own eligible list."""
    coordinators = service.list_coordinators(db, exclude_event_id=exclude_event_id)
    return [CoordinatorOption.model_validate(u) for u in coordinators]


@router.get("/events/{event_id}/coordinator", response_model=EventCoordinatorOut | None)
def get_event_coordinator(
    event_id: uuid.UUID,
    db: DbSession,
    actor: CurrentUser,
) -> EventCoordinatorOut | None:
    """AC4: the assigned coordinator's name, shown on the event. ``null`` when unassigned."""
    try:
        assignment = service.get_event_coordinator(db, event_id, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found.") from None
    except service.EventAccessDenied:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Your role does not permit this action."
        ) from None
    return None if assignment is None else EventCoordinatorOut.from_assignment(assignment)


@router.put("/events/{event_id}/coordinator", response_model=EventCoordinatorOut)
def assign_coordinator(
    event_id: uuid.UUID,
    payload: AssignCoordinatorIn,
    db: DbSession,
    actor: Annotated[CurrentUser, CanReview],
) -> EventCoordinatorOut:
    """5.1 AC1/AC3: record the event's single current coordinator, with who assigned it and when.
    5.2 AC6: refused with 403 for anyone but the event's current coordinator, once it has one.
    5.2 AC7: refused with 409 if the coordinator changed since the caller last read it."""
    try:
        assignment = service.assign_coordinator(db, event_id, payload, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found.") from None
    except service.NotCurrentCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.AssignmentChanged as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.EventNotAssignable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except (
        service.CoordinatorNotFound,
        service.NotACoordinator,
        service.CoordinatorInactive,
    ) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return EventCoordinatorOut.from_assignment(assignment)
