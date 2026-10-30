"""HTTP endpoints for an event's equipment items (story 15.1): the availability figures the form
shows, and the assigned coordinator recording, editing, removing and submitting items. And
Technical Support's queue of the items sent to it (story 15.2), searched and ordered (story 13.3).

The items are a sub-resource of the event, so the paths sit under ``/events/{event_id}``; an item
is returned as ``EquipmentLineOut``, the shape the event page already reads. Submitting creates an
equipment submission rather than calling an action on the event (backend/STYLE.md: a URL names a
resource). The queue spans every event, so it has a path of its own, ``/equipment-requests``.
Technical Support's decision on a request is likewise a resource of its own (story 16.1),
``/equipment-requests/{item_id}/decision``, created once.

Story 16.2: the equipment types, under ``/equipment-types`` - the catalogue, each type's page, and
its out-of-service records as a sub-resource, with a read-only ``check`` of a record before it is
saved. Ending a record in force is ``{"end_now": true}`` on its PATCH, as 9.4's venue closures
are; one not yet started is removed with DELETE. An event's items left short by them are
``/events/{event_id}/equipment-shortages``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_permission
from app.auth.permissions import Permission
from app.common.search import QUEUE_SEARCH_MAX_LENGTH
from app.db import get_db
from app.equipment import service
from app.equipment.schemas import (
    EquipmentCatalogueEntryOut,
    EquipmentDecisionIn,
    EquipmentItemIn,
    EquipmentItemUpdate,
    EquipmentQueue,
    EquipmentQueueCounts,
    EquipmentQueueEntry,
    EquipmentQueueOrder,
    EquipmentQueueStatus,
    EquipmentShortageOut,
    EquipmentTypePageOut,
    EventEquipmentAvailabilityOut,
    OutOfServiceCheckOut,
    OutOfServiceIn,
    OutOfServiceOut,
    OutOfServiceUpdate,
    ShortHoldOut,
)
from app.events.schemas import EquipmentLineOut

router = APIRouter(prefix="/events", tags=["equipment"])
queue_router = APIRouter(prefix="/equipment-requests", tags=["equipment"])
types_router = APIRouter(prefix="/equipment-types", tags=["equipment"])

CanRead = Depends(require_permission(Permission.EQUIPMENT_READ))
CanRequest = Depends(require_permission(Permission.EQUIPMENT_REQUEST))
# Story 15.2 AC6: only Technical Support. Every internal role holds EQUIPMENT_READ, so the queue
# is guarded by the permission only Technical Support holds.
CanManage = Depends(require_permission(Permission.EQUIPMENT_MANAGE))
DbSession = Annotated[Session, Depends(get_db)]

EVENT_NOT_FOUND_MESSAGE = "Event not found."
ITEM_NOT_FOUND_MESSAGE = "Equipment item not found."
REQUEST_NOT_FOUND_MESSAGE = "Equipment request not found."


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
    search: Annotated[str | None, Query(max_length=QUEUE_SEARCH_MAX_LENGTH)] = None,
    order: EquipmentQueueOrder = EquipmentQueueOrder.DATE,
) -> EquipmentQueue:
    """Story 15.2 AC1-AC3: ``?status=`` picks the Pending, Accepted or Declined tab, and no status
    is the All tab; soonest event first, each request with its figures. ``counts`` labels every
    tab. AC6: Technical Support only. ``request_status`` is aliased so it does not shadow
    FastAPI's ``status`` module.

    Story 13.3 AC1-AC4: ``?search=`` and ``?order=`` search and order the tab, and the counts are
    the matching requests'. AC5: a search longer than 100 characters, or an order the queue does
    not offer, is a 422. AC8: Technical Support only, as the queue is."""
    listing = service.list_equipment_requests(db, status=request_status, search=search, order=order)
    return EquipmentQueue(
        items=[
            EquipmentQueueEntry.from_item(row.item, row.event, available=row.available)
            for row in listing.rows
        ],
        counts=EquipmentQueueCounts.from_counts(listing.counts_by_status),
    )


@queue_router.get("/{item_id}", response_model=EquipmentQueueEntry, dependencies=[CanManage])
def get_equipment_request(item_id: uuid.UUID, db: DbSession) -> EquipmentQueueEntry:
    """Story 16.1: one request as the queue shows it, for its own page. AC7: one the queue does
    not list is not found. AC8: Technical Support only."""
    try:
        row = service.get_equipment_request(db, item_id)
    except service.EquipmentRequestNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, REQUEST_NOT_FOUND_MESSAGE) from None
    return EquipmentQueueEntry.from_item(row.item, row.event, available=row.available)


@queue_router.post(
    "/{item_id}/decision",
    response_model=EquipmentQueueEntry,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CanManage],
)
def decide_equipment_request(
    item_id: uuid.UUID,
    payload: EquipmentDecisionIn,
    db: DbSession,
    actor: CurrentUser,
) -> EquipmentQueueEntry:
    """Story 16.1 AC1/AC2: accept a Pending request, or decline it with a reason (AC4); returns
    the request as the queue shows it. AC6: a shortfall is refused with its figures beside the
    sentence. AC7/AC9: a request that is not Pending, or whose event was cancelled or rejected, is
    refused with why. AC8: Technical Support only."""
    try:
        row = service.decide_equipment_request(db, item_id, payload, actor=actor)
    except service.EquipmentRequestNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, REQUEST_NOT_FOUND_MESSAGE) from None
    except service.NotEnoughToAccept as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": str(exc), "available": exc.available, "shortfall": exc.shortfall},
        ) from None
    except service.EquipmentConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return EquipmentQueueEntry.from_item(row.item, row.event, available=row.available)


# =============================================================================================
# Story 16.2: the equipment types, and their units out of service
# =============================================================================================
@router.get(
    "/{event_id}/equipment-shortages",
    response_model=list[EquipmentShortageOut],
)
def list_event_shortages(
    event_id: uuid.UUID, db: DbSession, viewer: Annotated[CurrentUser, CanRead]
) -> list[EquipmentShortageOut]:
    """Story 16.2 AC4: the event's items that units out of service leave short, and by how many,
    for its equipment list. Any internal role reading the event may read it."""
    try:
        return service.list_event_shortages(db, event_id, viewer=viewer, now=datetime.now(UTC))
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None


def _out_of_service_refusal(exc: Exception) -> HTTPException:
    """Story 16.2: the answer to each refusal - not found (404), outside the rules (422), or in
    conflict with the stock or with the record as it stands (409)."""
    if isinstance(exc, (service.EquipmentTypeNotFound, service.OutOfServiceNotFound)):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, service.InvalidOutOfService):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


_REFUSALS = (
    service.EquipmentTypeNotFound,
    service.OutOfServiceNotFound,
    service.InvalidOutOfService,
    service.OutOfServiceConflict,
)


@types_router.get("", response_model=list[EquipmentCatalogueEntryOut], dependencies=[CanManage])
def list_equipment_catalogue(db: DbSession) -> list[EquipmentCatalogueEntryOut]:
    """Story 16.2 AC2/AC6: every active type with its stock and the units out of service now -
    Technical Support only."""
    return [
        EquipmentCatalogueEntryOut.from_entry(entry)
        for entry in service.list_equipment_catalogue(db, now=datetime.now(UTC))
    ]


@types_router.get("/{type_id}", response_model=EquipmentTypePageOut, dependencies=[CanManage])
def get_equipment_type(type_id: uuid.UUID, db: DbSession) -> EquipmentTypePageOut:
    """Story 16.2 AC2: one type's page - its stock, the units out now and its current records."""
    try:
        page = service.get_equipment_type_page(db, type_id, now=datetime.now(UTC))
    except _REFUSALS as exc:
        raise _out_of_service_refusal(exc) from None
    return EquipmentTypePageOut.from_page(page)


@types_router.get(
    "/{type_id}/out-of-service/check",
    response_model=OutOfServiceCheckOut,
    dependencies=[CanManage],
)
def check_out_of_service(
    type_id: uuid.UUID,
    db: DbSession,
    quantity: Annotated[int, Query(ge=1)],
    starts_at: Annotated[AwareDatetime, Query()],
    ends_at: Annotated[AwareDatetime | None, Query()] = None,
    record_id: Annotated[uuid.UUID | None, Query()] = None,
) -> OutOfServiceCheckOut:
    """Story 16.2 AC5: the holds a record of ``quantity`` units over the period would leave short,
    for Technical Support to see before saving - refused as saving it would be (AC3). With
    ``record_id``, an edit of that record, which is not counted against itself. Reads only."""
    try:
        shorts = service.check_out_of_service(
            db,
            type_id,
            quantity=quantity,
            starts_at=starts_at,
            ends_at=ends_at,
            record_id=record_id,
            now=datetime.now(UTC),
        )
    except _REFUSALS as exc:
        raise _out_of_service_refusal(exc) from None
    return OutOfServiceCheckOut(short_holds=[ShortHoldOut.from_short(each) for each in shorts])


@types_router.post(
    "/{type_id}/out-of-service",
    response_model=OutOfServiceOut,
    status_code=status.HTTP_201_CREATED,
)
def add_out_of_service(
    type_id: uuid.UUID,
    payload: OutOfServiceIn,
    db: DbSession,
    actor: Annotated[CurrentUser, CanManage],
) -> OutOfServiceOut:
    """Story 16.2 AC1/AC3/AC4/AC6: record units out of service; the holds it leaves short are
    told to their coordinators."""
    try:
        record = service.add_out_of_service(
            db, type_id, payload, actor=actor, now=datetime.now(UTC)
        )
    except _REFUSALS as exc:
        raise _out_of_service_refusal(exc) from None
    return OutOfServiceOut.from_record(record)


@types_router.patch("/{type_id}/out-of-service/{record_id}", response_model=OutOfServiceOut)
def edit_out_of_service(
    type_id: uuid.UUID,
    record_id: uuid.UUID,
    payload: OutOfServiceUpdate,
    db: DbSession,
    actor: Annotated[CurrentUser, CanManage],
) -> OutOfServiceOut:
    """Story 16.2 AC2/AC3: change a record - only the fields sent - or end one in force with
    ``{"end_now": true}``."""
    try:
        record = service.edit_out_of_service(
            db, type_id, record_id, payload, actor=actor, now=datetime.now(UTC)
        )
    except _REFUSALS as exc:
        raise _out_of_service_refusal(exc) from None
    return OutOfServiceOut.from_record(record)


@types_router.delete(
    "/{type_id}/out-of-service/{record_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_out_of_service(
    type_id: uuid.UUID,
    record_id: uuid.UUID,
    db: DbSession,
    actor: Annotated[CurrentUser, CanManage],
) -> None:
    """Story 16.2 AC2: remove a record that has not started; one in force is ended instead."""
    try:
        service.remove_out_of_service(db, type_id, record_id, actor=actor, now=datetime.now(UTC))
    except _REFUSALS as exc:
        raise _out_of_service_refusal(exc) from None
