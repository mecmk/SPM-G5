"""HTTP endpoints for coordinator assignment (stories 5.1, 5.2, 5.4 and 5.5).

``GET /coordination/unassigned-events`` - the Lead's unassigned queue (5.4 AC2)
``GET /coordination/active-events``     - the Lead's overview of every active event (5.5 AC1)
``GET /coordination/workloads``         - each coordinator's active events (5.5 AC2, AC4, AC5)
``GET /coordinators``                   - the selectable coordinators, with their active events
                                          (5.1 AC2, 5.4 AC3)
``GET /events/{event_id}/coordinator``  - who currently owns the event (5.1 AC4)
``PUT /events/{event_id}/coordinator``  - the Lead assigns an unassigned event (5.4 AC3), or its
                                          coordinator hands it to another (5.2)

Assigning an unassigned event needs ``events:assign`` (the Lead, 5.4 AC7); reassigning needs
``events:review`` (a coordinator, 5.2). The service decides which one a request is.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_any_permission, require_permission
from app.auth.permissions import Permission
from app.coordination import service
from app.coordination.schemas import (
    ActiveEventEntry,
    AssignCoordinatorIn,
    CoordinatorOption,
    CoordinatorWorkloadEntry,
    EventCoordinatorOut,
    UnassignedEventEntry,
)
from app.db import get_db

router = APIRouter(tags=["coordination"])

CanReadInternalUsers = Depends(require_permission(Permission.USERS_READ_INTERNAL))
CanAssign = Depends(require_permission(Permission.EVENTS_ASSIGN))
# 5.4 AC7 / 5.2: the Lead assigns and a coordinator reassigns; the service decides which a
# request is, so the door lets either permission in.
CanAssignOrReassign = Depends(
    require_any_permission(Permission.EVENTS_ASSIGN, Permission.EVENTS_REVIEW)
)
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/coordination/unassigned-events", response_model=list[UnassignedEventEntry])
def list_unassigned_events(
    db: DbSession,
    _actor: Annotated[CurrentUser, CanAssign],
) -> list[UnassignedEventEntry]:
    """Story 5.4 AC2: the submitted events waiting for a coordinator, oldest submission first.
    AC7: only the Lead (``events:assign``); everyone else gets 403 from the dependency."""
    return [UnassignedEventEntry.from_event(event) for event in service.list_unassigned_events(db)]


@router.get("/coordination/active-events", response_model=list[ActiveEventEntry])
def list_active_events(
    db: DbSession,
    actor: Annotated[CurrentUser, CanAssign],
    coordinator: Annotated[uuid.UUID | Literal["unassigned"] | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    assigned_by: Annotated[Literal["me"] | None, Query()] = None,
) -> list[ActiveEventEntry]:
    """Story 5.5 AC1: every active event with its coordinator and the Lead who assigned it,
    narrowed by coordinator (an id, or ``unassigned``), by one active status, and to the events
    this Lead assigned (``assigned_by=me``). A malformed filter is 422. AC6: only the Lead
    (``events:assign``); everyone else gets 403 from the dependency."""
    try:
        active = service.list_active_events(
            db,
            coordinator=coordinator,
            status=status_filter,
            assigned_by=actor if assigned_by == "me" else None,
        )
    except service.NotAnActiveStatus as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return [
        ActiveEventEntry.from_event(item.event, assigning_lead=item.assigning_lead)
        for item in active
    ]


@router.get("/coordination/workloads", response_model=list[CoordinatorWorkloadEntry])
def list_workloads(
    db: DbSession,
    _actor: Annotated[CurrentUser, CanAssign],
) -> list[CoordinatorWorkloadEntry]:
    """Story 5.5 AC2/AC4: every Event Coordinator with their active events, 0 included. AC5: a
    deactivated coordinator still holding events is listed and flagged. AC6: only the Lead
    (``events:assign``); everyone else gets 403 from the dependency."""
    return [
        CoordinatorWorkloadEntry.from_coordinator(
            item.coordinator, active_event_count=item.active_event_count, events=item.events
        )
        for item in service.list_workloads(db)
    ]


@router.get("/coordinators", response_model=list[CoordinatorOption])
def list_coordinators(
    db: DbSession,
    _actor: Annotated[CurrentUser, CanReadInternalUsers],
    exclude_event_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[CoordinatorOption]:
    """5.1 AC2: the pick-list for the assignment form holds Event Coordinators and nobody else.
    5.4 AC3: each with their number of active events.
    5.2 AC4: pass ``exclude_event_id`` for the reassignment picker, which leaves that event's
    current coordinator out of its own eligible list."""
    coordinators = service.list_coordinators(db, exclude_event_id=exclude_event_id)
    return [
        CoordinatorOption.from_coordinator(
            workload.coordinator, active_event_count=workload.active_event_count
        )
        for workload in coordinators
    ]


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
    actor: Annotated[CurrentUser, CanAssignOrReassign],
) -> EventCoordinatorOut:
    """5.1 AC1/AC3: record the event's single current coordinator, with who assigned it and when.
    5.4 AC3/AC7/AC9: an unassigned event is assigned by the Lead; anyone else gets 403.
    5.4 AC8: a Lead who finds it already assigned gets 409, naming the coordinator.
    5.2 AC6: an assigned event is refused with 403 for anyone but its current coordinator.
    5.2 AC7: refused with 409 if the coordinator changed since the caller last read it."""
    try:
        assignment = service.assign_coordinator(db, event_id, payload, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found.") from None
    except service.NotPermittedToAssign as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.NotCurrentCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.AlreadyAssigned as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
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
