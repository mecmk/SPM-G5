"""HTTP endpoints for the venue catalogue.

Story 8.3 (create / update, Venue Staff only) plus the read endpoints stories 8.1 / 8.2 need.
Delete was added for Venue Staff by the team decision of 17 Sep 2026 (full CRUD on venues).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    VenueSummary,
    VenueUpdate,
)

router = APIRouter(prefix="/venues", tags=["venues"])

CanRead = Depends(require_permission(Permission.VENUES_READ))
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


@router.get("/{venue_id}", response_model=VenueOut, dependencies=[CanRead])
def get_venue(venue_id: uuid.UUID, db: DbSession) -> VenueOut:
    try:
        return VenueOut.from_venue(service.get_venue(db, venue_id))
    except service.VenueNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, VENUE_NOT_FOUND_MESSAGE) from None


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
