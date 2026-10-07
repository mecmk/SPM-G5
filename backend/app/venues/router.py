"""HTTP endpoints for the venue catalogue and its availability calendar.

Story 8.3 (create / update, Venue Staff only), delete (story 8.1 AC12), plus the read endpoints
stories 8.1 / 8.2 need, 8.1's search, and the calendar endpoint story 9.1 needs. Story 8.3
AC5-AC10 (bug f8.3.2): a venue's pictures, added, arranged and removed by Venue Staff and served
from /uploads/venues/.
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_permission
from app.auth.permissions import Permission
from app.db import get_db
from app.venues import service
from app.venues.schemas import (
    ReferenceItem,
    VenueCreate,
    VenueImageOrder,
    VenueOut,
    VenueReferenceData,
    VenueSearchQuery,
    VenueSearchResult,
    VenueSummary,
    VenueUnavailableWindowOut,
    VenueUpdate,
)

router = APIRouter(prefix="/venues", tags=["venues"])
# Story 8.3 AC6: uploaded venue pictures are served from here. Public, like an event's cover
# picture: a picture is only ever reached by its generated name.
uploads_router = APIRouter(prefix="/uploads/venues", tags=["uploads"])

CanRead = Depends(require_permission(Permission.VENUES_READ))
CanReadCalendar = Depends(require_permission(Permission.VENUE_CALENDAR_READ))
CanManage = Depends(require_permission(Permission.VENUES_MANAGE))
DbSession = Annotated[Session, Depends(get_db)]

VENUE_NOT_FOUND_MESSAGE = "Venue not found."
PICTURE_NOT_FOUND_MESSAGE = "Picture not found."
EMPTY_PICTURE_MESSAGE = "Choose a picture to upload."
# A name the server generated: a UUID and one of the accepted extensions, nothing else.
_STORED_PICTURE_NAME = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(png|jpg|webp)$"
)
# The name never changes what it points at, so a browser may keep a picture indefinitely.
_PICTURE_CACHE_CONTROL = "public, max-age=31536000, immutable"


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
    """Story 8.1 AC12: only Venue Staff may remove a venue."""
    try:
        service.delete_venue(db, venue_id, actor=actor)
    except service.VenueNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, VENUE_NOT_FOUND_MESSAGE) from None
    except service.VenueInUse as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None


@router.post("/{venue_id}/images", response_model=VenueOut, status_code=status.HTTP_201_CREATED)
def add_venue_image(
    venue_id: uuid.UUID,
    file: UploadFile,
    db: DbSession,
    actor: Annotated[CurrentUser, CanManage],
) -> VenueOut:
    """Story 8.3 AC5/AC7/AC9: Venue Staff add a picture to a venue, after its others."""
    # The upload has already been received and spooled by the time this runs, so this bounds what
    # is read into memory, not what is transferred. One byte past the limit is enough to know the
    # file is too large.
    content = file.file.read(service.MAX_VENUE_IMAGE_BYTES + 1)
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, EMPTY_PICTURE_MESSAGE)
    try:
        venue = service.add_venue_image(db, venue_id, content, actor=actor)
    except service.VenueNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, VENUE_NOT_FOUND_MESSAGE) from None
    except service.VenueImageTooLarge as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from None
    except service.UnsupportedVenueImage as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except service.TooManyVenueImages as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return VenueOut.from_venue(venue)


@router.delete("/{venue_id}/images/{image_id}", response_model=VenueOut)
def remove_venue_image(
    venue_id: uuid.UUID,
    image_id: uuid.UUID,
    db: DbSession,
    actor: Annotated[CurrentUser, CanManage],
) -> VenueOut:
    """Story 8.3 AC5/AC8/AC9: Venue Staff take a picture off a venue; the rest keep their order."""
    try:
        venue = service.remove_venue_image(db, venue_id, image_id, actor=actor)
    except service.VenueNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, VENUE_NOT_FOUND_MESSAGE) from None
    except service.VenueImageNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, PICTURE_NOT_FOUND_MESSAGE) from None
    return VenueOut.from_venue(venue)


@router.put("/{venue_id}/images/order", response_model=VenueOut)
def reorder_venue_images(
    venue_id: uuid.UUID,
    payload: VenueImageOrder,
    db: DbSession,
    actor: Annotated[CurrentUser, CanManage],
) -> VenueOut:
    """Story 8.3 AC5/AC9/AC10: Venue Staff put a venue's pictures in a new order."""
    try:
        venue = service.reorder_venue_images(db, venue_id, payload.image_ids, actor=actor)
    except service.VenueNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, VENUE_NOT_FOUND_MESSAGE) from None
    except service.VenueImagesChanged as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return VenueOut.from_venue(venue)


@uploads_router.get("/{filename}")
def get_venue_image(filename: str) -> FileResponse:
    """Story 8.3 AC6: the stored venue picture called ``filename``."""
    if _STORED_PICTURE_NAME.match(filename) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, PICTURE_NOT_FOUND_MESSAGE)
    path = service.venue_image_path(filename)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, PICTURE_NOT_FOUND_MESSAGE)
    return FileResponse(
        path,
        media_type=service.VENUE_IMAGE_MEDIA_TYPES[path.suffix],
        headers={"Cache-Control": _PICTURE_CACHE_CONTROL},
    )
