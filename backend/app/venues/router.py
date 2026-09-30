"""HTTP endpoints for the venue catalogue and its availability calendar.

Story 8.3 (create / update / delete - Venue Staff have full CRUD on venues) plus the read
endpoints stories 8.1 / 8.2 need, 8.1's search, and the calendar endpoint story 9.1 needs.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_permission
from app.auth.permissions import Permission
from app.db import get_db
from app.venues import service
from app.venues.schemas import (
    ReferenceItem,
    VenueCreate,
    VenueOut,
    VenueReferenceData,
    VenueSearchQuery,
    VenueSearchResult,
    VenueSummary,
    VenueUnavailableWindowOut,
    VenueUpdate,
)

router = APIRouter(prefix="/venues", tags=["venues"])

CanRead = Depends(require_permission(Permission.VENUES_READ))
CanReadCalendar = Depends(require_permission(Permission.VENUE_CALENDAR_READ))
CanManage = Depends(require_permission(Permission.VENUES_MANAGE))
DbSession = Annotated[Session, Depends(get_db)]

VENUE_NOT_FOUND_MESSAGE = "Venue not found."


@router.get("/reference-data", response_model=VenueReferenceData, dependencies=[CanRead])
def reference_data(db: DbSession) -> VenueReferenceData:
    """Pick-list values for the venue form (facilities, layouts, accessibility features)."""
    data = service.list_reference_data(db)
    return VenueReferenceData(
        facilities=[ReferenceItem.model_validate(x) for x in data["facilities"]],
        layouts=[ReferenceItem.model_validate(x) for x in data["layouts"]],
        accessibility_features=[
            ReferenceItem.model_validate(x) for x in data["accessibility_features"]
        ],
    )


@router.get("", response_model=list[VenueSummary], dependencies=[CanRead])
def list_venues(
    db: DbSession,
    include_withdrawn: Annotated[bool, Query()] = False,
) -> list[VenueSummary]:
    return [
        VenueSummary.model_validate(v)
        for v in service.list_venues(db, include_withdrawn=include_withdrawn)
    ]


@router.get("/search", response_model=VenueSearchResult, dependencies=[CanRead])
def search_venues(db: DbSession, query: Annotated[VenueSearchQuery, Query()]) -> VenueSearchResult:
    """Story 8.1 AC3/AC4: the catalogue's filters, run on the server for any role that reads
    venues. AC8: a search that cannot be run is refused with a sentence saying why. Declared
    above ``/{venue_id}`` so the literal path is not read as a venue id."""
    try:
        return service.search_venues(db, query)
    except service.InvalidVenueSearch as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except service.UnknownReferenceCode as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.get("/{venue_id}", response_model=VenueOut, dependencies=[CanRead])
def get_venue(venue_id: uuid.UUID, db: DbSession) -> VenueOut:
    try:
        return VenueOut.from_venue(service.get_venue(db, venue_id))
    except service.VenueNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, VENUE_NOT_FOUND_MESSAGE) from None


@router.get(
    "/{venue_id}/calendar",
    response_model=list[VenueUnavailableWindowOut],
    dependencies=[CanReadCalendar],
)
def get_venue_calendar(
    venue_id: uuid.UUID,
    db: DbSession,
    starts_at: Annotated[AwareDatetime, Query()],
    ends_at: Annotated[AwareDatetime, Query()],
) -> list[VenueUnavailableWindowOut]:
    """Story 9.1 AC1/AC2: approved bookings, pending requests (held) and unavailability periods
    overlapping the range. AC13: Event Coordinator, Venue Staff and Technical Support only."""
    try:
        return service.get_venue_calendar(db, venue_id, starts_at=starts_at, ends_at=ends_at)
    except service.VenueNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, VENUE_NOT_FOUND_MESSAGE) from None
    except service.InvalidDateRange as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.post("", response_model=VenueOut, status_code=status.HTTP_201_CREATED)
def create_venue(
    payload: VenueCreate,
    db: DbSession,
    actor: Annotated[CurrentUser, CanManage],
) -> VenueOut:
    """Story 8.3 AC1 / AC4: only Venue Staff may create venues."""
    try:
        venue = service.create_venue(db, payload, actor=actor)
    except service.VenueNameTaken as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.UnknownReferenceCode as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return VenueOut.from_venue(venue)


@router.patch("/{venue_id}", response_model=VenueOut)
def update_venue(
    venue_id: uuid.UUID,
    payload: VenueUpdate,
    db: DbSession,
    actor: Annotated[CurrentUser, CanManage],
) -> VenueOut:
    """Story 8.3 AC2 / AC4: only Venue Staff may edit venues."""
    try:
        venue = service.update_venue(db, venue_id, payload, actor=actor)
    except service.VenueNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, VENUE_NOT_FOUND_MESSAGE) from None
    except service.VenueNameTaken as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except (service.UnknownReferenceCode, service.InvalidOperatingHours) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return VenueOut.from_venue(venue)


@router.delete("/{venue_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_venue(
    venue_id: uuid.UUID,
    db: DbSession,
    actor: Annotated[CurrentUser, CanManage],
) -> None:
    """Story 8.3 AC4 applied to delete: only Venue Staff may remove a venue."""
    try:
        service.delete_venue(db, venue_id, actor=actor)
    except service.VenueNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, VENUE_NOT_FOUND_MESSAGE) from None
    except service.VenueInUse as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
