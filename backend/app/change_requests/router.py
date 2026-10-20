"""HTTP endpoints for story 19.1: raise, list and withdraw an event's change requests, and say when
they close (fix f19.1.1); and for story 19.2: the coordinator's queue of pending ones, and
approving or rejecting one.

They sit under the event they belong to (``/events/{event_id}/change-requests``, and
``/events/{event_id}/change-request-window`` for when they close - outside ``/change-requests/``
so it can never be read as a request's id), except the queue, which spans the coordinator's events
(``/change-requests``). Withdrawing, approving and
rejecting are ``POST .../withdraw``, ``.../approve`` and ``.../reject``, action URLs like story
12.2's booking withdrawal and 4.4/4.5's event decisions - each a state transition with its own
rules, notification and audit record (see backend/STYLE.md, Standing divergences).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_any_permission, require_permission
from app.auth.permissions import Permission
from app.change_requests import service
from app.change_requests.schemas import (
    ChangeRequestIn,
    ChangeRequestOut,
    ChangeRequestQueueEntryOut,
    ChangeRequestRejectionIn,
    ChangeRequestWindowOut,
)
from app.db import get_db

router = APIRouter(prefix="/events", tags=["change requests"])
queue_router = APIRouter(prefix="/change-requests", tags=["change requests"])

# AC7: only an organiser holds this; the service then checks the event is their own.
CanRequestChanges = Depends(require_permission(Permission.EVENT_CHANGE_REQUESTS_CREATE))
# Story 19.2 AC6: only a coordinator holds this; the service then checks the event is theirs.
CanDecide = Depends(require_permission(Permission.EVENT_CHANGE_REQUESTS_DECIDE))
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


def _change_request_out(request: service.EventChangeRequest) -> ChangeRequestOut:
    """Story 19.2 AC7: every change request is returned saying whether it is out of date."""
    return ChangeRequestOut.from_change_request(
        request, is_out_of_date=service.is_out_of_date(request)
    )


@router.post(
    "/{event_id}/change-requests",
    response_model=ChangeRequestOut,
    status_code=status.HTTP_201_CREATED,
)
def raise_change_request(
    event_id: uuid.UUID,
    # Not wrapped in Body(): FastAPI keeps only the last field info, which would drop the
    # union's discriminator and report every kind of request's errors (PR #94 review).
    payload: ChangeRequestIn,
    db: DbSession,
    actor: Annotated[CurrentUser, CanRequestChanges],
) -> ChangeRequestOut:
    """AC1-AC8, AC11-AC13: the owning organiser asks for one field of their Planning or
    Confirmed event to change, until 24 hours before its set-up time. 409 otherwise (AC5, AC12,
    AC13)."""
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
    return _change_request_out(request)


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
    return [_change_request_out(request) for request in requests]


@router.get("/{event_id}/change-request-window", response_model=ChangeRequestWindowOut)
def get_change_request_window(
    event_id: uuid.UUID,
    db: DbSession,
    viewer: Annotated[CurrentUser, CanRead],
) -> ChangeRequestWindowOut:
    """AC12 (fix f19.1.1): when the event stops taking change requests - 24 hours before its set-up
    time - for its organiser and assigned coordinator."""
    try:
        window = service.get_change_request_window(db, event_id, viewer=viewer)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.NotRelatedParty as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    return ChangeRequestWindowOut(closes_at=window.closes_at, is_open=window.is_open)


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
    return _change_request_out(request)


@queue_router.get("", response_model=list[ChangeRequestQueueEntryOut])
def list_coordinator_change_requests(
    db: DbSession,
    viewer: Annotated[CurrentUser, CanDecide],
) -> list[ChangeRequestQueueEntryOut]:
    """Story 19.2 AC1: the change requests on the coordinator's own events - pending ones first,
    oldest first, then those decided or withdrawn, latest first."""
    requests = service.list_coordinator_change_requests(db, viewer=viewer)
    return [
        ChangeRequestQueueEntryOut.from_queued_request(
            request, is_out_of_date=service.is_out_of_date(request)
        )
        for request in requests
    ]


@router.post(
    "/{event_id}/change-requests/{change_request_id}/approve",
    response_model=ChangeRequestOut,
)
def approve_change_request(
    event_id: uuid.UUID,
    change_request_id: uuid.UUID,
    db: DbSession,
    actor: Annotated[CurrentUser, CanDecide],
) -> ChangeRequestOut:
    """Story 19.2 AC2: the assigned coordinator (AC6) approves a pending request, applying it.
    409 when it was already decided or withdrawn, has gone stale, or its event is closed (AC7);
    422 when the change breaks a creation rule."""
    try:
        request = service.approve_change_request(db, event_id, change_request_id, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.ChangeRequestNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CHANGE_REQUEST_NOT_FOUND_MESSAGE) from None
    except service.NotAssignedCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.EventStateConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.InvalidEventRequest as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return _change_request_out(request)


@router.post(
    "/{event_id}/change-requests/{change_request_id}/reject",
    response_model=ChangeRequestOut,
)
def reject_change_request(
    event_id: uuid.UUID,
    change_request_id: uuid.UUID,
    payload: ChangeRequestRejectionIn,
    db: DbSession,
    actor: Annotated[CurrentUser, CanDecide],
) -> ChangeRequestOut:
    """Story 19.2 AC3/AC4: the assigned coordinator (AC6) rejects a pending request with a
    non-blank reason, leaving the event as it is. 409 when it was already decided or withdrawn,
    or its event is closed (AC7)."""
    try:
        request = service.reject_change_request(
            db, event_id, change_request_id, payload, actor=actor
        )
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.ChangeRequestNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CHANGE_REQUEST_NOT_FOUND_MESSAGE) from None
    except service.NotAssignedCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.EventStateConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.InvalidEventRequest as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return _change_request_out(request)
