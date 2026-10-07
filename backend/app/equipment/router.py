"""HTTP endpoints for an event's equipment items (story 15.1): the availability figures the form
shows, and the assigned coordinator recording, editing, removing and submitting items. And
Technical Support's queue of the items sent to it (story 15.2).

The items are a sub-resource of the event, so the paths sit under ``/events/{event_id}``; an item
is returned as ``EquipmentLineOut``, the shape the event page already reads. Submitting creates an
equipment submission rather than calling an action on the event (backend/STYLE.md: a URL names a
resource). The queue spans every event, so it has a path of its own, ``/equipment-requests``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_permission
from app.auth.permissions import Permission
from app.db import get_db
from app.equipment import service
from app.equipment.schemas import (
    EquipmentItemIn,
    EquipmentItemUpdate,
    EquipmentQueue,
    EquipmentQueueCounts,
    EquipmentQueueEntry,
    EquipmentQueueStatus,
    EventEquipmentAvailabilityOut,
)
from app.events.schemas import EquipmentLineOut

router = APIRouter(prefix="/events", tags=["equipment"])
queue_router = APIRouter(prefix="/equipment-requests", tags=["equipment"])

CanRead = Depends(require_permission(Permission.EQUIPMENT_READ))
CanRequest = Depends(require_permission(Permission.EQUIPMENT_REQUEST))
# Story 15.2 AC6: only Technical Support. Every internal role holds EQUIPMENT_READ, so the queue
# is guarded by the permission only Technical Support holds.
CanManage = Depends(require_permission(Permission.EQUIPMENT_MANAGE))
DbSession = Annotated[Session, Depends(get_db)]

EVENT_NOT_FOUND_MESSAGE = "Event not found."
ITEM_NOT_FOUND_MESSAGE = "Equipment item not found."


@router.get(
    "/{event_id}/equipment-availability", response_model=list[EventEquipmentAvailabilityOut]
)
def list_event_equipment_availability(
    event_id: uuid.UUID, db: DbSession, viewer: Annotated[CurrentUser, CanRead]
) -> list[EventEquipmentAvailabilityOut]:
    """AC3: for each active type, how many units the event can have over its period, counting
    what it already holds. Any internal role may read it (AC9 restricts changes, not figures)."""
    try:
        return service.list_event_equipment_availability(db, event_id, viewer=viewer)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None


@router.post(
    "/{event_id}/equipment", response_model=EquipmentLineOut, status_code=status.HTTP_201_CREATED
)
def add_equipment_item(
    event_id: uuid.UUID,
    payload: EquipmentItemIn,
    db: DbSession,
    actor: Annotated[CurrentUser, CanRequest],
) -> EquipmentLineOut:
    """AC1/AC2: record an item, held at once and not yet sent. AC3/AC4/AC6: refused, saving
    nothing, if the event cannot have it. AC9: only the assigned coordinator, while it can
    change."""
    try:
        item = service.add_equipment_item(db, event_id, payload, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.NotAssignedCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.UnknownEquipmentType as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except service.EquipmentConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return EquipmentLineOut.from_line(item)


@router.patch("/{event_id}/equipment/{item_id}", response_model=EquipmentLineOut)
def update_equipment_item(
    event_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: EquipmentItemUpdate,
    db: DbSession,
    actor: Annotated[CurrentUser, CanRequest],
) -> EquipmentLineOut:
    """AC2: edit an item's quantity or notes, adjusting its hold in the same step. AC7: a decided
    item is locked. AC9: only the assigned coordinator, while the event's equipment can change."""
    try:
        item = service.update_equipment_item(db, event_id, item_id, payload, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.EquipmentItemNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, ITEM_NOT_FOUND_MESSAGE) from None
    except service.NotAssignedCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.EquipmentConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return EquipmentLineOut.from_line(item)


@router.delete("/{event_id}/equipment/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_equipment_item(
    event_id: uuid.UUID,
    item_id: uuid.UUID,
    db: DbSession,
    actor: Annotated[CurrentUser, CanRequest],
) -> None:
    """AC2: remove an item and release its hold at once. AC7: a decided item is locked. AC9: only
    the assigned coordinator, while the event's equipment can change."""
    try:
        service.remove_equipment_item(db, event_id, item_id, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.EquipmentItemNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, ITEM_NOT_FOUND_MESSAGE) from None
    except service.NotAssignedCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.EquipmentConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None


@router.post(
    "/{event_id}/equipment-submissions",
    response_model=list[EquipmentLineOut],
    status_code=status.HTTP_201_CREATED,
)
def submit_equipment(
    event_id: uuid.UUID, db: DbSession, actor: Annotated[CurrentUser, CanRequest]
) -> list[EquipmentLineOut]:
    """AC1: send every item not yet sent to Technical Support as Pending; returns the items sent.
    AC10: a second submission with nothing waiting is refused. AC9: only the assigned coordinator,
    while the event's equipment can change."""
    try:
        items = service.submit_equipment(db, event_id, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.NotAssignedCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.EquipmentConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return [EquipmentLineOut.from_line(item) for item in items]


@queue_router.get("", response_model=EquipmentQueue, dependencies=[CanManage])
def list_equipment_requests(
    db: DbSession,
    request_status: Annotated[EquipmentQueueStatus | None, Query(alias="status")] = None,
) -> EquipmentQueue:
    """Story 15.2 AC1-AC3: ``?status=`` picks the Pending, Accepted or Declined tab, and no status
    is the All tab; soonest event first, each request with its figures. ``counts`` labels every
    tab. AC6: Technical Support only. ``request_status`` is aliased so it does not shadow
    FastAPI's ``status`` module."""
    listing = service.list_equipment_requests(db, status=request_status)
    return EquipmentQueue(
        items=[
            EquipmentQueueEntry.from_item(row.item, row.event, available=row.available)
            for row in listing.rows
        ],
        counts=EquipmentQueueCounts.from_counts(listing.counts_by_status),
    )
