"""Business logic for the venue catalogue (story 8.3 create/update/delete; reads for 8.1/8.2).

Routers translate the exceptions raised here into HTTP statuses; keeping the rules in plain
functions makes them easy to unit-test and to reuse from other features (e.g. booking
suitability checks in stories 11.x).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.common.audit import record_audit
from app.venues.models import (
    AccessibilityFeature,
    Facility,
    RoomLayout,
    Venue,
    VenueAccessibilityFeature,
    VenueFacility,
    VenueLayout,
    VenueStatus,
)
from app.venues.schemas import VenueCreate, VenueUpdate


class VenueNotFound(LookupError):
    pass


class VenueNameTaken(ValueError):
    def __init__(self, name: str):
        super().__init__(f'A venue named "{name}" already exists.')
        self.name = name


class UnknownReferenceCode(ValueError):
    def __init__(self, kind: str, codes: list[str]):
        super().__init__(f"Unknown {kind} code(s): {', '.join(codes)}")
        self.kind = kind
        self.codes = codes


class InvalidOperatingHours(ValueError):
    pass


# Name PostgreSQL gives the only foreign key that blocks deleting a venue.
_BOOKINGS_VENUE_FOREIGN_KEY = "venue_bookings_venue_id_fkey"

VENUE_IN_USE_MESSAGE = (
    "You cannot delete a venue that has bookings. Withdraw it from service instead."
)


class VenueInUse(ValueError):
    """Raised when a venue still has booking rows, which the database refuses to orphan."""

    def __init__(self) -> None:
        super().__init__(VENUE_IN_USE_MESSAGE)


# --- reads -------------------------------------------------------------------------------
def list_reference_data(db: Session) -> dict[str, list[Any]]:
    return {
        "facilities": db.scalars(
            select(Facility).order_by(Facility.sort_order, Facility.name)
        ).all(),
        "layouts": db.scalars(
            select(RoomLayout).order_by(RoomLayout.sort_order, RoomLayout.name)
        ).all(),
        "accessibility_features": db.scalars(
            select(AccessibilityFeature).order_by(
                AccessibilityFeature.sort_order, AccessibilityFeature.name
            )
        ).all(),
    }


def list_venues(db: Session, *, include_withdrawn: bool = False) -> list[Venue]:
    query = select(Venue).order_by(Venue.name)
    if not include_withdrawn:
        query = query.where(Venue.status == VenueStatus.ACTIVE)
    return list(db.scalars(query).all())


def get_venue(db: Session, venue_id: uuid.UUID) -> Venue:
    venue = db.get(Venue, venue_id)
    if venue is None:
        raise VenueNotFound(venue_id)
    return venue


# --- writes ------------------------------------------------------------------------------
_SCALAR_FIELDS = (
    "name",
    "location",
    "capacity",
    "description",
    "floor_area_sqm",
    "operating_hours_start",
    "operating_hours_end",
    "operating_notes",
    "setup_minutes_default",
    "teardown_minutes_default",
)


def create_venue(db: Session, data: VenueCreate, *, actor: User) -> Venue:
    """AC1: a venue can be created with at minimum name, location and capacity."""
    _validate_reference_codes(db, data)
    venue = Venue(
        **{f: getattr(data, f) for f in _SCALAR_FIELDS},
        status=VenueStatus.ACTIVE,
        created_by_id=actor.id,
    )
    _replace_characteristics(venue, data)
    db.add(venue)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if "uq_venues_name" in str(exc.orig):
            raise VenueNameTaken(data.name) from exc
        raise
    record_audit(
        db,
        actor=actor,
        action="VENUE_CREATED",
        entity_type="venue",
        entity_id=venue.id,
        details={"name": venue.name},
        commit=False,
    )
    db.commit()
    db.refresh(venue)
    return venue


def update_venue(db: Session, venue_id: uuid.UUID, data: VenueUpdate, *, actor: User) -> Venue:
    """AC2: existing characteristics can be edited and saved. Only supplied fields change."""
    venue = get_venue(db, venue_id)
    changes = data.model_dump(exclude_unset=True)
    _validate_reference_codes(db, data)

    before: dict[str, Any] = {}
    for field in _SCALAR_FIELDS + ("status",):
        if field in changes and getattr(venue, field) != changes[field]:
            before[field] = _jsonable(getattr(venue, field))
            setattr(venue, field, changes[field])

    if (venue.operating_hours_start is None) != (venue.operating_hours_end is None):
        db.rollback()
        raise InvalidOperatingHours(
            "operating_hours_start and operating_hours_end must be given together"
        )
    if (
        venue.operating_hours_start is not None
        and venue.operating_hours_end is not None
        and venue.operating_hours_end <= venue.operating_hours_start
    ):
        db.rollback()
        raise InvalidOperatingHours("operating_hours_end must be after operating_hours_start")

    if "facilities" in changes:
        before["facilities"] = [f.facility_code for f in venue.facilities]
    if "layouts" in changes:
        before["layouts"] = [lo.layout_code for lo in venue.layouts]
    if "accessibility_features" in changes:
        before["accessibility_features"] = [a.feature_code for a in venue.accessibility_features]
    _replace_characteristics(venue, data, only_present=True)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if "uq_venues_name" in str(exc.orig):
            raise VenueNameTaken(changes.get("name", venue.name)) from exc
        raise
    after = {k: _jsonable(changes[k]) if k in changes else None for k in before}
    record_audit(
        db,
        actor=actor,
        action="VENUE_UPDATED",
        entity_type="venue",
        entity_id=venue.id,
        details={k: {"from": before[k], "to": after[k]} for k in before},
        commit=False,
    )
    db.commit()
    db.refresh(venue)
    return venue


def delete_venue(db: Session, venue_id: uuid.UUID, *, actor: User) -> None:
    """Remove a venue nothing refers to (team decision, 17 Sep 2026: Venue Staff have full CRUD).

    Facilities, layouts, accessibility features and unavailability periods go with it. A venue
    with booking rows is refused by the database's foreign key, translated to VenueInUse.
    """
    venue = get_venue(db, venue_id)
    name = venue.name
    db.delete(venue)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _BOOKINGS_VENUE_FOREIGN_KEY in str(exc.orig):
            raise VenueInUse() from exc
        raise
    record_audit(
        db,
        actor=actor,
        action="VENUE_DELETED",
        entity_type="venue",
        entity_id=venue_id,
        details={"name": name},
        commit=False,
    )
    db.commit()


# --- helpers -----------------------------------------------------------------------------
def _validate_reference_codes(db: Session, data: VenueCreate | VenueUpdate) -> None:
    checks = (
        ("facility", Facility, getattr(data, "facilities", None)),
        ("layout", RoomLayout, getattr(data, "layouts", None)),
        (
            "accessibility feature",
            AccessibilityFeature,
            getattr(data, "accessibility_features", None),
        ),
    )
    for kind, model, items in checks:
        if not items:
            continue
        wanted = {item.code for item in items}
        known = set(db.scalars(select(model.code).where(model.code.in_(wanted))).all())
        missing = sorted(wanted - known)
        if missing:
            raise UnknownReferenceCode(kind, missing)


def _replace_characteristics(
    venue: Venue, data: VenueCreate | VenueUpdate, *, only_present: bool = False
) -> None:
    present = data.model_dump(exclude_unset=True) if only_present else None
    if present is None or "facilities" in present:
        venue.facilities = [
            VenueFacility(facility_code=f.code, quantity=f.quantity, notes=f.notes)
            for f in _dedupe(data.facilities or [])
        ]
    if present is None or "layouts" in present:
        venue.layouts = [
            VenueLayout(layout_code=lo.code, layout_capacity=lo.layout_capacity)
            for lo in _dedupe(data.layouts or [])
        ]
    if present is None or "accessibility_features" in present:
        venue.accessibility_features = [
            VenueAccessibilityFeature(feature_code=a.code, notes=a.notes)
            for a in _dedupe(data.accessibility_features or [])
        ]


def _dedupe(items):
    seen: set[str] = set()
    for item in items:
        if item.code not in seen:
            seen.add(item.code)
            yield item


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool, list)):
        return value
    return str(value)
