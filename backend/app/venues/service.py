"""Business logic for the venue catalogue (story 8.3 create/update/delete; reads for 8.1/8.2),
its search (story 8.1, Sprint 2) and its availability calendar (story 9.1).

Routers translate the exceptions raised here into HTTP statuses; keeping the rules in plain
functions makes them easy to unit-test and to reuse from other features (e.g. booking
suitability checks in stories 11.x).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta, timezone
from itertools import chain
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings.models import BookingStatus, VenueBooking
from app.common.audit import record_audit
from app.events.models import Event
from app.venues.models import (
    AccessibilityFeature,
    Facility,
    RoomLayout,
    Venue,
    VenueAccessibilityFeature,
    VenueFacility,
    VenueLayout,
    VenueStatus,
    VenueUnavailabilityPeriod,
)
from app.venues.schemas import (
    BOOKING_REASON,
    RelaxHint,
    VenueCreate,
    VenueSearchHit,
    VenueSearchQuery,
    VenueSearchResult,
    VenueUnavailableWindowOut,
    VenueUpdate,
)


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


class InvalidDateRange(ValueError):
    pass


END_NOT_AFTER_START_MESSAGE = "The end of the range must be after its start."

# Story 8.1 AC8: why a search is refused.
SEARCH_NEEDS_BOTH_ENDS_MESSAGE = "Choose both a start and an end, or neither."
SEARCH_IN_THE_PAST_MESSAGE = "Searches cannot start in the past."
CAPACITY_RANGE_BACKWARDS_MESSAGE = "Capacity to must not be below capacity from."


class InvalidVenueSearch(ValueError):
    """Story 8.1 AC8: the filters cannot be searched as they stand; the message says why."""


# Story 8.1 AC9: the filter groups a search can relax, and their names on the panel, in the
# order the panel shows them - which is also the order of equal suggestions.
SEARCH_GROUP_LABELS = {
    "search": "Name or location",
    "capacity": "Capacity",
    "dates": "Dates",
    "layout": "Layout",
    "facilities": "Facilities",
    "accessibility": "Accessibility",
}

# Story 8.1 AC3: the bookings that take a venue out of a search - the hold's rule (s12.1), the
# same list as ex_venue_bookings_no_double_booking's WHERE since migration 010.
_HOLDING_STATUSES = (BookingStatus.PENDING, BookingStatus.APPROVED)
# Every event runs on Singapore time, which has no daylight saving (as in app/events/service.py).
_SINGAPORE = timezone(timedelta(hours=8))
# The escape character that makes a LIKE wildcard in the search text literal (story 8.1 AC3).
_LIKE_ESCAPE = "\\"


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


def get_venue_calendar(
    db: Session, venue_id: uuid.UUID, *, starts_at: datetime, ends_at: datetime
) -> list[VenueUnavailableWindowOut]:
    """Story 9.1 AC1/AC2: every approved booking and unavailability period overlapping the
    range, as a flat list of periods (not pre-expanded per day). Overlap mirrors the database's
    own half-open exclusion constraint on venue_bookings
    (ex_venue_bookings_no_double_booking): a period that only touches the range's edge is not a
    conflict. venue_unavailability_periods has no such DB constraint, but is checked the same
    way for consistency.
    """
    get_venue(db, venue_id)
    if ends_at <= starts_at:
        raise InvalidDateRange(END_NOT_AFTER_START_MESSAGE)

    bookings = db.execute(
        select(VenueBooking.held_from, VenueBooking.held_until, Event.name)
        .join(Event, Event.id == VenueBooking.event_id)
        .where(
            VenueBooking.venue_id == venue_id,
            VenueBooking.status == BookingStatus.APPROVED,
            VenueBooking.held_from < ends_at,
            VenueBooking.held_until > starts_at,
        )
    ).all()
    windows = [
        VenueUnavailableWindowOut(
            starts_at=held_from, ends_at=held_until, reason=BOOKING_REASON, label=event_name
        )
        for held_from, held_until, event_name in bookings
    ]

    closures = db.scalars(
        select(VenueUnavailabilityPeriod).where(
            VenueUnavailabilityPeriod.venue_id == venue_id,
            VenueUnavailabilityPeriod.starts_at < ends_at,
            VenueUnavailabilityPeriod.ends_at > starts_at,
        )
    ).all()
    windows += [
        VenueUnavailableWindowOut(
            starts_at=period.starts_at,
            ends_at=period.ends_at,
            reason=period.reason,
            label=period.notes or period.reason,
        )
        for period in closures
    ]

    windows.sort(key=lambda w: w.starts_at)
    return windows


# --- search (story 8.1, Sprint 2) --------------------------------------------------------
def search_venues(db: Session, query: VenueSearchQuery) -> VenueSearchResult:
    """Story 8.1 AC1/AC3: the venues matching every filter, by name - in service only, unless
    ``include_withdrawn`` (AC12's Show withdrawn venues). With a period, only venues free for all
    of it: not booked or held, not blocked, and not closed at those hours (AC3, AC7).

    AC8 refuses a search that cannot be run (``InvalidVenueSearch``, ``UnknownReferenceCode``).
    AC9: when nothing matches, ``relax`` names each filter group whose removal alone would give
    results, with the count, largest first.
    """
    period = _search_period(query)
    if (
        query.capacity is not None
        and query.capacity_max is not None
        and query.capacity_max < query.capacity
    ):
        raise InvalidVenueSearch(CAPACITY_RANGE_BACKWARDS_MESSAGE)
    _check_search_codes(db, query)

    scope = [] if query.include_withdrawn else [Venue.status == VenueStatus.ACTIVE]
    groups = _search_groups(query, period)
    venues = db.scalars(
        select(Venue).where(*scope, *chain.from_iterable(groups.values())).order_by(Venue.name)
    ).all()
    return VenueSearchResult(
        venues=[VenueSearchHit.model_validate(venue) for venue in venues],
        total=_count_venues(db, scope),
        relax=[] if venues else _relax_hints(db, scope, query, period, active=groups),
    )


def find_blocking_unavailability(
    db: Session, venue_id: uuid.UUID, *, starts_at: datetime, ends_at: datetime
) -> VenueUnavailabilityPeriod | None:
    """Story 8.1 AC3 and 12.1 AC14: the earliest unavailability period (if any) blocking
    ``venue_id`` during part of ``starts_at``..``ends_at``. Half-open, as bookings are: a closure
    that only touches the period does not block it (8.1 AC7, 12.1 AC6)."""
    return db.scalars(
        select(VenueUnavailabilityPeriod)
        .where(VenueUnavailabilityPeriod.venue_id == venue_id, _blocks_venue(starts_at, ends_at))
        .order_by(VenueUnavailabilityPeriod.starts_at, VenueUnavailabilityPeriod.id)
        .limit(1)
    ).first()


def closed_for(venue: Venue, *, starts_at: datetime, ends_at: datetime) -> bool:
    """Story 8.1 AC3 and 12.1 AC14: whether ``venue``'s recorded opening hours leave out part
    of the period's daily window. A venue with no recorded hours is never closed: no rule can
    apply."""
    if venue.operating_hours_start is None or venue.operating_hours_end is None:
        return False
    window = daily_window(starts_at, ends_at)
    return (
        window is None
        or window[0] < venue.operating_hours_start
        or window[1] > venue.operating_hours_end
    )


def daily_window(starts_at: datetime, ends_at: datetime) -> tuple[time, time] | None:
    """Story 8.1 AC3: a period read as daily sessions, from its start time to its end time in
    Singapore time - the schema stores one continuous period, and reading a two-day event as
    continuous would close every venue overnight. None when the end time is not after the start
    time: the period passes midnight, which no daily opening hours can cover."""
    start, end = starts_at.astimezone(_SINGAPORE).time(), ends_at.astimezone(_SINGAPORE).time()
    return (start, end) if end > start else None


def _search_period(query: VenueSearchQuery) -> tuple[datetime, datetime] | None:
    """AC8: both ends or neither, the end after the start, and the start not in the past."""
    if query.starts_at is None and query.ends_at is None:
        return None
    if query.starts_at is None or query.ends_at is None:
        raise InvalidVenueSearch(SEARCH_NEEDS_BOTH_ENDS_MESSAGE)
    if query.ends_at <= query.starts_at:
        raise InvalidVenueSearch(END_NOT_AFTER_START_MESSAGE)
    if query.starts_at < datetime.now(UTC):
        raise InvalidVenueSearch(SEARCH_IN_THE_PAST_MESSAGE)
    return query.starts_at, query.ends_at


def _check_search_codes(db: Session, query: VenueSearchQuery) -> None:
    checks = (
        ("layout", RoomLayout, [query.layout] if query.layout else []),
        ("facility", Facility, query.facility),
        ("accessibility feature", AccessibilityFeature, query.accessibility),
    )
    for kind, model, codes in checks:
        missing = _unknown_codes(db, model, codes)
        if missing:
            raise UnknownReferenceCode(kind, missing)


def _search_groups(
    query: VenueSearchQuery,
    period: tuple[datetime, datetime] | None,
    *,
    without: str | None = None,
) -> dict[str, list[ColumnElement[bool]]]:
    """The SQL conditions of each filter group the query sets, leaving out ``without`` (AC9).

    AC6: with a layout, capacity is that layout's (``venue_layouts.layout_capacity``, or the
    venue's own where it is NULL). Relaxing the layout compares the venue's capacity instead.
    """
    groups: dict[str, list[ColumnElement[bool]]] = {}
    term = (query.search or "").strip()
    if term:
        pattern = f"%{_escape_like(term)}%"
        groups["search"] = [
            or_(
                Venue.name.ilike(pattern, escape=_LIKE_ESCAPE),
                Venue.location.ilike(pattern, escape=_LIKE_ESCAPE),
            )
        ]
    capacity_layout = query.layout if without != "layout" else None
    if query.capacity is not None or query.capacity_max is not None:
        groups["capacity"] = [_capacity_fits(query.capacity, query.capacity_max, capacity_layout)]
    if period is not None:
        groups["dates"] = _free_for(*period)
    if query.layout:
        groups["layout"] = [_has_layout(query.layout)]
    if query.facility:
        groups["facilities"] = [_has_facility(code) for code in dict.fromkeys(query.facility)]
    if query.accessibility:
        groups["accessibility"] = [
            _has_accessibility_feature(code) for code in dict.fromkeys(query.accessibility)
        ]
    groups.pop(without, None)
    return groups


def _relax_hints(
    db: Session,
    scope: list[ColumnElement[bool]],
    query: VenueSearchQuery,
    period: tuple[datetime, datetime] | None,
    *,
    active: dict[str, list[ColumnElement[bool]]],
) -> list[RelaxHint]:
    """AC9: for each filter group set, how many venues the search would find without it - one
    count per group, six at most. Groups that would still find nothing are left out; the rest
    come largest first."""
    hints = []
    for group, label in SEARCH_GROUP_LABELS.items():
        if group not in active:
            continue
        others = _search_groups(query, period, without=group)
        count = _count_venues(db, [*scope, *chain.from_iterable(others.values())])
        if count > 0:
            hints.append(RelaxHint(filter=group, label=label, count=count))
    return sorted(hints, key=lambda hint: -hint.count)


def _count_venues(db: Session, conditions: Iterable[ColumnElement[bool]]) -> int:
    return db.scalar(select(func.count()).select_from(Venue).where(*conditions))


def _capacity_fits(
    minimum: int | None, maximum: int | None, layout: str | None
) -> ColumnElement[bool]:
    """AC6: the capacity range, both ends included, in ``layout`` when one is chosen."""

    def within(capacity: ColumnElement[int]) -> list[ColumnElement[bool]]:
        limits = []
        if minimum is not None:
            limits.append(capacity >= minimum)
        if maximum is not None:
            limits.append(capacity <= maximum)
        return limits

    if layout is None:
        return and_(*within(Venue.capacity))
    layout_capacity = func.coalesce(VenueLayout.layout_capacity, Venue.capacity)
    return (
        select(VenueLayout.venue_id)
        .where(
            VenueLayout.venue_id == Venue.id,
            VenueLayout.layout_code == layout,
            *within(layout_capacity),
        )
        .exists()
    )


def _free_for(starts_at: datetime, ends_at: datetime) -> list[ColumnElement[bool]]:
    """AC3: free for the whole period - not booked or held, not blocked, and not closed at those
    hours (``daily_window``). A venue with no recorded hours is kept."""
    held = (
        select(VenueBooking.id)
        .where(
            VenueBooking.venue_id == Venue.id,
            VenueBooking.status.in_(_HOLDING_STATUSES),
            VenueBooking.held_from < ends_at,
            VenueBooking.held_until > starts_at,
        )
        .exists()
    )
    blocked = (
        select(VenueUnavailabilityPeriod.id)
        .where(VenueUnavailabilityPeriod.venue_id == Venue.id, _blocks_venue(starts_at, ends_at))
        .exists()
    )
    hours_unknown = Venue.operating_hours_start.is_(None)
    window = daily_window(starts_at, ends_at)
    if window is None:
        return [~held, ~blocked, hours_unknown]
    open_then = and_(
        Venue.operating_hours_start <= window[0], Venue.operating_hours_end >= window[1]
    )
    return [~held, ~blocked, or_(hours_unknown, open_then)]


def _blocks_venue(starts_at: datetime, ends_at: datetime) -> ColumnElement[bool]:
    """An unavailability period overlapping ``starts_at``..``ends_at``; touching is not."""
    return and_(
        VenueUnavailabilityPeriod.starts_at < ends_at,
        VenueUnavailabilityPeriod.ends_at > starts_at,
    )


def _has_layout(code: str) -> ColumnElement[bool]:
    return (
        select(VenueLayout.venue_id)
        .where(VenueLayout.venue_id == Venue.id, VenueLayout.layout_code == code)
        .exists()
    )


def _has_facility(code: str) -> ColumnElement[bool]:
    return (
        select(VenueFacility.venue_id)
        .where(VenueFacility.venue_id == Venue.id, VenueFacility.facility_code == code)
        .exists()
    )


def _has_accessibility_feature(code: str) -> ColumnElement[bool]:
    return (
        select(VenueAccessibilityFeature.venue_id)
        .where(
            VenueAccessibilityFeature.venue_id == Venue.id,
            VenueAccessibilityFeature.feature_code == code,
        )
        .exists()
    )


def _escape_like(text: str) -> str:
    """AC3: ``%`` and ``_`` in the search text match themselves, not any characters."""
    escape = _LIKE_ESCAPE
    return text.replace(escape, escape * 2).replace("%", f"{escape}%").replace("_", f"{escape}_")


def _unknown_codes(db: Session, model: Any, codes: list[str]) -> list[str]:
    wanted = set(codes)
    if not wanted:
        return []
    known = set(db.scalars(select(model.code).where(model.code.in_(wanted))).all())
    return sorted(wanted - known)


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
