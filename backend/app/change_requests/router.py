"""HTTP endpoints for story 19.1: raise, list and withdraw an event's change requests.

They sit under the event they belong to (``/events/{event_id}/change-requests``). Withdrawing is
``POST .../withdraw``, an action URL like story 12.2's booking withdrawal - a state transition with
its own rules, notification and audit record (see backend/STYLE.md, Standing divergences).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_any_permission, require_permission
from app.auth.permissions import Permission
from app.change_requests import service
from app.change_requests.schemas import ChangeRequestIn, ChangeRequestOut
from app.db import get_db

router = APIRouter(prefix="/events", tags=["change requests"])

# AC7: only an organiser holds this; the service then checks the event is their own.
CanRequestChanges = Depends(require_permission(Permission.EVENT_CHANGE_REQUESTS_CREATE))
CanRead = Depends(require_any_permission(Permission.EVENTS_READ_OWN, Permission.EVENTS_READ_ALL))
DbSession = Annotated[Session, Depends(get_db)]

EVENT_NOT_FOUND_MESSAGE = "Event not found."
CHANGE_REQUEST_NOT_FOUND_MESSAGE = "Change request not found."


def _requirement_refusal(exc: service.InvalidVenueRequirement) -> HTTPException:
    """AC4: a refused venue requirement, located the way FastAPI locates a validation error (as
    story 2.7 AC11 does on the request form), so the change form can mark the field to fix."""
    location = ["body", "proposed", exc.index, exc.field]
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        [{"loc": location, "msg": str(exc), "type": "value_error"}],
    )


@router.post(
    "/{event_id}/change-requests",
    response_model=ChangeRequestOut,
    status_code=status.HTTP_201_CREATED,
)
def raise_change_request(
    event_id: uuid.UUID,
    payload: Annotated[ChangeRequestIn, Body()],
    db: DbSession,
    actor: Annotated[CurrentUser, CanRequestChanges],
) -> ChangeRequestOut:
    """AC1-AC8: the owning organiser asks for one field of their Planning event to change."""
    try:
        request = service.raise_change_request(db, event_id, payload, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.EventStateConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.InvalidVenueRequirement as exc:
        raise _requirement_refusal(exc) from None
    except service.InvalidEventRequest as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return ChangeRequestOut.from_change_request(request)


@router.get("/{event_id}/change-requests", response_model=list[ChangeRequestOut])
def list_change_requests(
    event_id: uuid.UUID,
    db: DbSession,
    viewer: Annotated[CurrentUser, CanRead],
) -> list[ChangeRequestOut]:
    """AC1: the event's change requests, newest first, for its organiser and assigned
    coordinator."""
    try:
        requests = service.list_change_requests(db, event_id, viewer=viewer)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.NotRelatedParty as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    return [ChangeRequestOut.from_change_request(request) for request in requests]


@router.post(
    "/{event_id}/change-requests/{change_request_id}/withdraw",
    response_model=ChangeRequestOut,
)
def withdraw_change_request(
    event_id: uuid.UUID,
    change_request_id: uuid.UUID,
    db: DbSession,
    actor: Annotated[CurrentUser, CanRequestChanges],
) -> ChangeRequestOut:
    """AC9/AC10: the owning organiser withdraws one of their pending change requests."""
    try:
        request = service.withdraw_change_request(db, event_id, change_request_id, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.ChangeRequestNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CHANGE_REQUEST_NOT_FOUND_MESSAGE) from None
    except service.EventStateConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return ChangeRequestOut.from_change_request(request)
