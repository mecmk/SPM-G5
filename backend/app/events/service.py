"""Business logic for event requests (story 2.1), the organiser's own list of them (story 2.6),
event review (story 4.1), and the approve/reject decision (stories 4.4, 4.5).

Routers translate the exceptions raised here into HTTP statuses. A request belongs to the
organiser who created it: anyone else gets ``EventNotFound``, so a request's existence is not
revealed to people it is not theirs to see.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, lazyload

from app.auth.models import User
from app.auth.permissions import Permission, role_has
from app.common.audit import record_audit
from app.events.models import (
    EquipmentHoldStatus,
    EquipmentReservation,
    EquipmentType,
    EquipmentUnavailabilityPeriod,
    Event,
    EventAccessibilityNeed,
    EventEquipmentRequest,
    EventRequiredFacility,
    EventStatus,
    EventStatusHistory,
)
from app.events.schemas import (
    ACCESSIBILITY_CONTRADICTION_MESSAGE,
    VENUE_CONTRADICTION_MESSAGE,
    EquipmentAvailabilityOut,
    EventAccessibilityNeedIn,
    EventCreate,
    EventEquipmentIn,
    EventFacilityIn,
    EventReferenceData,
    EventUpdate,
    ReferenceItemOut,
    ReviewQueueSort,
)
from app.venues.models import AccessibilityFeature, Facility, RoomLayout

END_NOT_AFTER_START_MESSAGE = (
    "The proposed end date and time must be after the start date and time."
)
IN_THE_PAST_MESSAGE = "The proposed date and time cannot be in the past."
TOO_FAR_AHEAD_MESSAGE = "The proposed start cannot be more than 2 years from now."
TOO_LONG_MESSAGE = "An event cannot run for more than 14 days."
# How far ahead an event may start, and how long it may run (decided 20 Sep 2026). Keep these
# and their messages in step with the frontend's MAX_LEAD_YEARS and MAX_EVENT_DAYS.
_MAX_LEAD_YEARS = 2
_MAX_EVENT_DURATION = timedelta(days=14)
# Events run on Singapore time, which has no daylight saving.
_SINGAPORE = timezone(timedelta(hours=8))
NOT_EDITABLE_MESSAGE = "This request has been submitted and can no longer be edited."
ALREADY_SUBMITTED_MESSAGE = "This request has already been submitted."

# ``event_equipment_requests.status`` once the units are held for the event.
_LINE_RESERVED = "RESERVED"

_AWAITING_DECISION_STATUSES = (
    EventStatus.SUBMITTED,
    EventStatus.UNDER_REVIEW,
    EventStatus.CLARIFICATION_REQUESTED,
)
_SORT_COLUMNS = {
    ReviewQueueSort.SUBMITTED_AT: Event.submitted_at,
    ReviewQueueSort.STARTS_AT: Event.starts_at,
}

# Story 2.6 AC9: the most requests one call to the organiser's list returns, which is also what a
# call that names no limit gets. The offset stops at the largest value a database INTEGER holds.
MY_EVENTS_MAX_LIMIT = 100
MY_EVENTS_MAX_OFFSET = 2_147_483_647

# Columns copied straight from a request body onto the event (the lists are handled apart).
_DETAIL_FIELDS = (
    "name",
    "purpose",
    "description",
    "starts_at",
    "ends_at",
    "expected_attendance",
    "required_layout_code",
    "venue_requirement_notes",
    "venue_none_required",
    "accessibility_none_required",
    "accessibility_notes",
)

# AC10: the event details that must be filled in before a request can be submitted, and how to
# name each to the user. (The name is always required.) Venue requirements and accessibility
# needs must be answered too; see ``_missing_for_submission``.
_REQUIRED_DETAILS_FOR_SUBMISSION = (
    ("purpose", "purpose"),
    ("description", "description"),
    ("starts_at", "proposed start date and time"),
    ("ends_at", "proposed end date and time"),
    ("expected_attendance", "expected attendance"),
)
_VENUE_ANSWER_LABEL = "venue requirements (choose some, or mark none)"
_ACCESSIBILITY_ANSWER_LABEL = "accessibility needs (choose some, or mark none)"


class EventNotFound(LookupError):
    pass


class EventStateConflict(RuntimeError):
    """The request is not in the state this action needs (a 409)."""


class EventNotEditable(EventStateConflict):
    def __init__(self):
        super().__init__(NOT_EDITABLE_MESSAGE)


class EventAlreadySubmitted(EventStateConflict):
    def __init__(self):
        super().__init__(ALREADY_SUBMITTED_MESSAGE)


class InvalidEventRequest(ValueError):
    """What was sent cannot be recorded as it stands (a 422)."""


class InvalidSchedule(InvalidEventRequest):
    pass


class UnknownReference(InvalidEventRequest):
    pass


class UnknownEquipmentLine(InvalidEventRequest):
    def __init__(self):
        super().__init__("An equipment item does not belong to this request.")


class EquipmentNotAvailable(InvalidEventRequest):
    """AC6: more of an equipment type was asked for than is free for the event's dates."""

    def __init__(self, names: list[str]):
        super().__init__(f"Not enough {', '.join(names)} available for the proposed dates.")


class EquipmentNoLongerAvailable(EventStateConflict):
    """AC11: the stock a draft asked for went before it was submitted."""

    def __init__(self, names: list[str]):
        super().__init__(
            f"Not enough {', '.join(names)} available for the proposed dates any more."
        )


class ContradictoryAccessibility(InvalidEventRequest):
    def __init__(self):
        super().__init__(ACCESSIBILITY_CONTRADICTION_MESSAGE)


class ContradictoryVenueRequirements(InvalidEventRequest):
    def __init__(self):
        super().__init__(VENUE_CONTRADICTION_MESSAGE)


class MissingSubmissionDetails(InvalidEventRequest):
    def __init__(self, missing: list[str]):
        super().__init__(f"Add the following before submitting: {', '.join(missing)}.")
        self.missing = missing


NOT_ASSIGNED_COORDINATOR_MESSAGE = "Only the coordinator assigned to this request may decide it."
EVENT_NOT_AWAITING_DECISION_MESSAGE = (
    "This request is {status}, so it cannot be approved or rejected."
)
DECISION_REASON_REQUIRED_MESSAGE = "A reason is required to reject this request."

# --- reads -------------------------------------------------------------------------------


def list_review_queue(
    db: Session,
    *,
    sort: ReviewQueueSort = ReviewQueueSort.SUBMITTED_AT,
    coordinator_id: uuid.UUID | None = None,
) -> list[Event]:
    """AC1/AC4: only undecided submissions. AC3: ordered by submission or proposed date."""
    query = (
        select(Event)
        .where(Event.status.in_(_AWAITING_DECISION_STATUSES))
        .order_by(_SORT_COLUMNS[sort], Event.id)
    )
    if coordinator_id is not None:
        query = query.where(Event.assigned_coordinator_id == coordinator_id)
    return list(db.scalars(query).all())


@dataclass(frozen=True)
class MyEventsListing:
    """One page of an organiser's requests, and how many they own in all."""

    events: list[Event]
    total: int


def list_my_events(
    db: Session,
    *,
    organiser: User,
    limit: int = MY_EVENTS_MAX_LIMIT,
    offset: int = 0,
) -> MyEventsListing:
    """AC1/AC3: every request ``organiser`` owns, in any status, and nobody else's - owned by the
    organiser, not by their organisation. AC4: drafts included. AC6: most recently updated first,
    ties broken by id so the order is stable, and so are the pages cut from it (AC9).
    ``organiser`` and ``assigned_coordinator`` are joined eagerly on ``Event`` for the review
    queue, which shows their names; this list shows neither, so they are left unloaded rather than
    joining ``users`` twice for every row."""
    is_owned = Event.organiser_id == organiser.id
    page = (
        select(Event)
        .options(lazyload(Event.organiser), lazyload(Event.assigned_coordinator))
        .where(is_owned)
        .order_by(Event.updated_at.desc(), Event.id)
        .limit(limit)
        .offset(offset)
    )
    total = db.scalar(select(func.count()).select_from(Event).where(is_owned))
    return MyEventsListing(events=list(db.scalars(page).all()), total=total or 0)


def list_reference_data(db: Session) -> EventReferenceData:
    """AC4-AC6: the pick-lists for the request form. Inactive equipment types are hidden."""

    def items(query: Any) -> list[ReferenceItemOut]:
        return [ReferenceItemOut.model_validate(row) for row in db.scalars(query).all()]

    return EventReferenceData(
        layouts=items(select(RoomLayout).order_by(RoomLayout.sort_order, RoomLayout.code)),
        facilities=items(select(Facility).order_by(Facility.sort_order, Facility.code)),
        accessibility_features=items(
            select(AccessibilityFeature).order_by(
                AccessibilityFeature.sort_order, AccessibilityFeature.code
            )
        ),
        equipment_types=items(
            select(EquipmentType)
            .where(EquipmentType.is_active.is_(True))
            .order_by(EquipmentType.name)
        ),
    )


def _can_view(viewer: User, event: Event) -> bool:
    if event.organiser_id == viewer.id:
        return True
    is_submitted = event.status != EventStatus.DRAFT
    return is_submitted and role_has(viewer.role_code, Permission.EVENTS_READ_ALL)


def get_event(db: Session, event_id: uuid.UUID, *, viewer: User) -> Event:
    """AC8 / 4.4 AC1 / 4.5 AC2: the organiser sees their own request; internal roles see every
    submitted one. A draft is private to its organiser, and anything else the viewer may not
    see is simply not found."""
    event = db.get(Event, event_id)
    if event is None or not _can_view(viewer, event):
        raise EventNotFound(event_id)
    return event


def _get_own_event(db: Session, event_id: uuid.UUID, actor: User) -> Event:
    event = db.get(Event, event_id)
    if event is None or event.organiser_id != actor.id:
        raise EventNotFound(event_id)
    return event


# --- validation ----------------------------------------------------------------------------


def latest_start_allowed(now: datetime) -> datetime:
    """AC2: two calendar years after ``now`` on Singapore's clock, so leap days and month lengths
    are counted, never a fixed 730 days. From 29 February the next 1 March, as the form does."""
    local = now.astimezone(_SINGAPORE)
    try:
        return local.replace(year=local.year + _MAX_LEAD_YEARS)
    except ValueError:  # 29 February, two years on, is not a date
        return local.replace(year=local.year + _MAX_LEAD_YEARS, day=28) + timedelta(days=1)


def _check_schedule(
    starts_at: datetime | None,
    ends_at: datetime | None,
    *,
    supplied_start: datetime | None,
    supplied_end: datetime | None,
) -> None:
    """AC2: the end is after the start, no date the organiser just supplied is in the past, the
    start is at most 2 years ahead, and the event runs at most 14 days.
    ``starts_at`` / ``ends_at`` are the values the request will end up with; ``supplied_start`` /
    ``supplied_end`` are the ones this call sets, so an edit to something else does not re-judge
    an old date."""
    if starts_at is not None and ends_at is not None and ends_at <= starts_at:
        raise InvalidSchedule(END_NOT_AFTER_START_MESSAGE)
    now = datetime.now(UTC)
    if any(moment is not None and moment < now for moment in (supplied_start, supplied_end)):
        raise InvalidSchedule(IN_THE_PAST_MESSAGE)
    if supplied_start is not None and supplied_start > latest_start_allowed(now):
        raise InvalidSchedule(TOO_FAR_AHEAD_MESSAGE)
    # Last: a start in the year 1 is "in the past", and fixing it fixes the length too.
    if starts_at is not None and ends_at is not None and ends_at - starts_at > _MAX_EVENT_DURATION:
        raise InvalidSchedule(TOO_LONG_MESSAGE)


def _check_accessibility(*, is_none_required: bool, has_needs: bool, notes: str | None) -> None:
    """AC5: "none required" cannot sit beside a stated need."""
    if is_none_required and (has_needs or notes):
        raise ContradictoryAccessibility()


def _check_venue_requirements(
    *, is_none_required: bool, layout_code: str | None, has_facilities: bool, notes: str | None
) -> None:
    """AC4: "no venue requirements" cannot sit beside a stated requirement."""
    if is_none_required and (layout_code or has_facilities or notes):
        raise ContradictoryVenueRequirements()


def _check_equipment_lines(
    items: list[EventEquipmentIn], *, owned_line_ids: set[uuid.UUID]
) -> None:
    """AC7: an item may carry only the ``id`` of a line this request already has."""
    if any(item.id is not None and item.id not in owned_line_ids for item in items):
        raise UnknownEquipmentLine()


def _known(
    db: Session, model: Any, codes: Iterable[str], *, label: str, is_active_only: bool = False
) -> dict[str, Any]:
    """The rows for ``codes``, or ``UnknownReference`` naming the ones that do not exist."""
    wanted = set(codes)
    if not wanted:
        return {}
    query = select(model).where(model.code.in_(wanted))
    if is_active_only:
        query = query.where(model.is_active.is_(True))
    found = {row.code: row for row in db.scalars(query).all()}
    missing = sorted(wanted - found.keys())
    if missing:
        raise UnknownReference(f"Unknown {label}: {', '.join(missing)}.")
    return found


# --- writes --------------------------------------------------------------------------------


def _available_by_type(
    db: Session, period_start: datetime, period_end: datetime
) -> dict[uuid.UUID, int]:
    """AC6: units free for a period, per equipment type: the stock, less units held for other
    events over the period (a hold's quantity less what was released), less units out of service.
    Overlap is half-open, so a hold ending exactly as the period starts does not count."""
    held = dict(
        db.execute(
            select(
                EquipmentReservation.equipment_type_id,
                func.sum(EquipmentReservation.quantity - EquipmentReservation.released_quantity),
            )
            .where(
                EquipmentReservation.status == EquipmentHoldStatus.RESERVED,
                EquipmentReservation.starts_at < period_end,
                EquipmentReservation.ends_at > period_start,
            )
            .group_by(EquipmentReservation.equipment_type_id)
        ).all()
    )
    out_of_service = dict(
        db.execute(
            select(
                EquipmentUnavailabilityPeriod.equipment_type_id,
                func.sum(EquipmentUnavailabilityPeriod.quantity),
            )
            .where(
                EquipmentUnavailabilityPeriod.starts_at < period_end,
                or_(
                    EquipmentUnavailabilityPeriod.ends_at.is_(None),
                    EquipmentUnavailabilityPeriod.ends_at > period_start,
                ),
            )
            .group_by(EquipmentUnavailabilityPeriod.equipment_type_id)
        ).all()
    )
    stock = db.execute(select(EquipmentType.id, EquipmentType.total_quantity)).all()
    return {
        type_id: max(0, total - int(held.get(type_id, 0)) - int(out_of_service.get(type_id, 0)))
        for type_id, total in stock
    }


def list_equipment_availability(
    db: Session, *, starts_at: datetime, ends_at: datetime
) -> list[EquipmentAvailabilityOut]:
    """AC6: how many of each active equipment type are free for the proposed dates."""
    if ends_at <= starts_at:
        raise InvalidSchedule(END_NOT_AFTER_START_MESSAGE)
    available = _available_by_type(db, starts_at, ends_at)
    active_types = db.scalars(
        select(EquipmentType).where(EquipmentType.is_active.is_(True)).order_by(EquipmentType.name)
    ).all()
    return [
        EquipmentAvailabilityOut(equipment_type_code=t.code, available=available[t.id])
        for t in active_types
    ]


def _check_equipment_available(
    db: Session,
    starts_at: datetime | None,
    ends_at: datetime | None,
    lines: list[tuple[EquipmentType, int]],
) -> None:
    """AC6: no more of a type than is free for the dates. Until both dates are known there is no
    period to check, and submission needs them anyway, where it is checked again."""
    if starts_at is None or ends_at is None or not lines:
        return
    available = _available_by_type(db, starts_at, ends_at)
    short = [t.name for t, quantity in lines if quantity > available[t.id]]
    if short:
        raise EquipmentNotAvailable(short)


def _hold_equipment(db: Session, event: Event, actor: User) -> None:
    """AC11: hold the request's equipment for its dates. The types are locked first, so two
    requests for the last units cannot both be held; the loser is refused and nothing is held."""
    lines = list(event.equipment_requests)
    if not lines or event.starts_at is None or event.ends_at is None:
        return
    type_ids = sorted({line.equipment_type_id for line in lines})
    db.execute(
        select(EquipmentType.id)
        .where(EquipmentType.id.in_(type_ids))
        .order_by(EquipmentType.id)
        .with_for_update()
    )
    available = _available_by_type(db, event.starts_at, event.ends_at)
    short = [
        line.equipment_type.name
        for line in lines
        if line.quantity > available[line.equipment_type_id]
    ]
    if short:
        raise EquipmentNoLongerAvailable(short)
    for line in lines:
        db.add(
            EquipmentReservation(
                event_id=event.id,
                equipment_request_id=line.id,
                equipment_type_id=line.equipment_type_id,
                quantity=line.quantity,
                starts_at=event.starts_at,
                ends_at=event.ends_at,
                status=EquipmentHoldStatus.RESERVED,
                reserved_by_id=actor.id,
                notes="Held when the request was submitted.",
            )
        )
        line.status = _LINE_RESERVED


def _replace_facilities(event: Event, items: list[EventFacilityIn]) -> None:
    event.required_facilities = [
        EventRequiredFacility(facility_code=item.code, quantity=item.quantity, notes=item.notes)
        for item in items
    ]


def _replace_accessibility_needs(event: Event, items: list[EventAccessibilityNeedIn]) -> None:
    event.accessibility_needs = [
        EventAccessibilityNeed(feature_code=item.code, notes=item.notes) for item in items
    ]


def _replace_equipment(
    event: Event, items: list[EventEquipmentIn], types: dict[str, EquipmentType], *, actor: User
) -> None:
    """AC6/AC7: make the request's equipment lines match ``items``. A line whose ``id`` is sent is
    kept and edited; one left out is removed; one without an ``id`` is new. New lines get
    increasing creation times so the request lists them in the order they were added."""
    existing = {line.id: line for line in event.equipment_requests}
    kept_ids = {item.id for item in items if item.id is not None}
    for line in [line for line in event.equipment_requests if line.id not in kept_ids]:
        event.equipment_requests.remove(line)
    added_at = datetime.now(UTC)
    for position, item in enumerate(items):
        equipment_type = types[item.equipment_type_code]
        if item.id is not None:
            line = existing[item.id]
            line.equipment_type = equipment_type
            line.quantity = item.quantity
            line.technical_notes = item.technical_notes
        else:
            event.equipment_requests.append(
                EventEquipmentRequest(
                    equipment_type=equipment_type,
                    quantity=item.quantity,
                    technical_notes=item.technical_notes,
                    created_by_id=actor.id,
                    created_at=added_at + timedelta(microseconds=position),
                )
            )


def create_event(db: Session, data: EventCreate, *, actor: User) -> Event:
    """AC1-AC6: record a new request as a draft owned by ``actor``."""
    _check_schedule(
        data.starts_at, data.ends_at, supplied_start=data.starts_at, supplied_end=data.ends_at
    )
    if data.required_layout_code is not None:
        _known(db, RoomLayout, [data.required_layout_code], label="room layout")
    _known(db, Facility, [f.code for f in data.required_facilities], label="facility")
    _known(
        db,
        AccessibilityFeature,
        [n.code for n in data.accessibility_needs],
        label="accessibility feature",
    )
    types = _known(
        db,
        EquipmentType,
        [e.equipment_type_code for e in data.equipment],
        label="equipment type",
        is_active_only=True,
    )
    _check_equipment_lines(data.equipment, owned_line_ids=set())
    _check_equipment_available(
        db,
        data.starts_at,
        data.ends_at,
        [(types[e.equipment_type_code], e.quantity) for e in data.equipment],
    )

    event = Event(
        organiser_id=actor.id,
        organisation_id=actor.organisation_id,
        status=EventStatus.DRAFT,
        **{field: getattr(data, field) for field in _DETAIL_FIELDS},
    )
    _replace_facilities(event, data.required_facilities)
    _replace_accessibility_needs(event, data.accessibility_needs)
    _replace_equipment(event, data.equipment, types, actor=actor)
    db.add(event)
    db.flush()
    db.add(
        EventStatusHistory(
            event_id=event.id, from_status=None, to_status=EventStatus.DRAFT, changed_by_id=actor.id
        )
    )
    record_audit(
        db,
        actor=actor,
        action="EVENT_CREATED",
        entity_type="event",
        entity_id=event.id,
        details={"name": event.name},
        commit=False,
    )
    db.commit()
    db.refresh(event)
    return event


def update_event(db: Session, event_id: uuid.UUID, data: EventUpdate, *, actor: User) -> Event:
    """AC7: edit or remove any recorded detail, requirement or equipment item while a draft.
    Only the fields sent change; a list sent replaces that list."""
    event = _get_own_event(db, event_id, actor)
    if event.status != EventStatus.DRAFT:
        raise EventNotEditable()

    sent = data.model_fields_set
    details = {field: getattr(data, field) for field in _DETAIL_FIELDS if field in sent}
    starts_at = details.get("starts_at", event.starts_at)
    ends_at = details.get("ends_at", event.ends_at)
    if sent & {"starts_at", "ends_at"}:
        _check_schedule(
            starts_at,
            ends_at,
            supplied_start=details.get("starts_at"),
            supplied_end=details.get("ends_at"),
        )
    _check_venue_requirements(
        is_none_required=details.get("venue_none_required", event.venue_none_required),
        layout_code=details.get("required_layout_code", event.required_layout_code),
        has_facilities=bool(data.required_facilities)
        if "required_facilities" in sent
        else bool(event.required_facilities),
        notes=details.get("venue_requirement_notes", event.venue_requirement_notes),
    )
    _check_accessibility(
        is_none_required=details.get(
            "accessibility_none_required", event.accessibility_none_required
        ),
        has_needs=bool(data.accessibility_needs)
        if "accessibility_needs" in sent
        else bool(event.accessibility_needs),
        notes=details.get("accessibility_notes", event.accessibility_notes),
    )
    if details.get("required_layout_code") is not None:
        _known(db, RoomLayout, [details["required_layout_code"]], label="room layout")
    if data.required_facilities is not None:
        _known(db, Facility, [f.code for f in data.required_facilities], label="facility")
    if data.accessibility_needs is not None:
        _known(
            db,
            AccessibilityFeature,
            [n.code for n in data.accessibility_needs],
            label="accessibility feature",
        )
    types: dict[str, EquipmentType] = {}
    if data.equipment is not None:
        types = _known(
            db,
            EquipmentType,
            [e.equipment_type_code for e in data.equipment],
            label="equipment type",
            is_active_only=True,
        )
        # Checked before anything is changed, so a refused edit leaves the request as it was.
        _check_equipment_lines(
            data.equipment, owned_line_ids={line.id for line in event.equipment_requests}
        )

    if sent & {"equipment", "starts_at", "ends_at"}:
        lines = (
            [(types[e.equipment_type_code], e.quantity) for e in data.equipment]
            if data.equipment is not None
            else [(line.equipment_type, line.quantity) for line in event.equipment_requests]
        )
        _check_equipment_available(db, starts_at, ends_at, lines)

    for field, value in details.items():
        setattr(event, field, value)
    if data.required_facilities is not None:
        _replace_facilities(event, data.required_facilities)
    if data.accessibility_needs is not None:
        _replace_accessibility_needs(event, data.accessibility_needs)
    if data.equipment is not None:
        _replace_equipment(event, data.equipment, types, actor=actor)
    # A change to a list alone would not touch the events row; stamping it makes updated_at the
    # draft's last-modified time whatever was edited (the trigger sets the real value).
    event.updated_at = datetime.now(UTC)
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="EVENT_UPDATED",
        entity_type="event",
        entity_id=event.id,
        details={"fields": sorted(sent)},
        commit=False,
    )
    db.commit()
    db.refresh(event)
    return event


def _missing_for_submission(event: Event) -> list[str]:
    """AC10: every event detail must be filled in, and venue requirements and accessibility
    needs each answered - something chosen or written, or marked "none required"."""
    missing = [
        label for field, label in _REQUIRED_DETAILS_FOR_SUBMISSION if getattr(event, field) is None
    ]
    has_venue_answer = (
        event.venue_none_required
        or event.required_layout_code is not None
        or bool(event.required_facilities)
        or event.venue_requirement_notes is not None
    )
    if not has_venue_answer:
        missing.append(_VENUE_ANSWER_LABEL)
    has_accessibility_answer = (
        event.accessibility_none_required
        or bool(event.accessibility_needs)
        or event.accessibility_notes is not None
    )
    if not has_accessibility_answer:
        missing.append(_ACCESSIBILITY_ANSWER_LABEL)
    return missing


def _record_transition(
    db: Session,
    event: Event,
    *,
    from_status: str,
    to_status: str,
    actor: User,
    at: datetime,
    reason: str | None,
) -> None:
    """Append one row to the append-only ``event_status_history`` log. ``to_status`` is taken
    as given, never read off ``event``, so this does not depend on being called before or after
    ``event`` itself is updated."""
    db.add(
        EventStatusHistory(
            event_id=event.id,
            from_status=from_status,
            to_status=to_status,
            changed_by_id=actor.id,
            changed_at=at,
            reason=reason,
        )
    )


def submit_event(db: Session, event_id: uuid.UUID, *, actor: User) -> Event:
    """AC9-AC12: submit ``actor``'s own draft once its four mandatory details are filled in."""
    event = _get_own_event(db, event_id, actor)
    if event.status != EventStatus.DRAFT:
        raise EventAlreadySubmitted()
    missing = _missing_for_submission(event)
    if missing:
        raise MissingSubmissionDetails(missing)
    _check_schedule(
        event.starts_at, event.ends_at, supplied_start=event.starts_at, supplied_end=None
    )

    _hold_equipment(db, event, actor)
    submitted_at = datetime.now(UTC)
    # Conditional on still being a draft, so two submissions racing cannot both succeed.
    submitted = db.execute(
        update(Event)
        .where(Event.id == event.id, Event.status == EventStatus.DRAFT)
        .values(status=EventStatus.SUBMITTED, submitted_at=submitted_at)
    )
    if submitted.rowcount == 0:
        db.rollback()
        raise EventAlreadySubmitted()
    _record_transition(
        db,
        event,
        from_status=EventStatus.DRAFT,
        to_status=EventStatus.SUBMITTED,
        actor=actor,
        at=submitted_at,
        reason=None,
    )
    record_audit(
        db,
        actor=actor,
        action="EVENT_SUBMITTED",
        entity_type="event",
        entity_id=event.id,
        commit=False,
    )
    db.commit()
    db.refresh(event)
    return event


class NotAssignedCoordinator(PermissionError):
    """Only the coordinator ``events.assigned_coordinator_id`` names may decide the request."""

    def __init__(self) -> None:
        super().__init__(NOT_ASSIGNED_COORDINATOR_MESSAGE)


class EventNotAwaitingDecision(EventStateConflict):
    """4.4 AC1 / 4.5 AC2: only a request in ``_AWAITING_DECISION_STATUSES`` may be decided -
    refuses repeat or invalid-state decisions (e.g. a request already decided, or past
    PLANNING). A draft never reaches this guard: ``get_event`` hides it from the coordinator
    first, so that case is a 404, not a 409."""

    def __init__(self, event: Event) -> None:
        super().__init__(EVENT_NOT_AWAITING_DECISION_MESSAGE.format(status=event.status))
        self.event = event


class MissingDecisionReason(InvalidEventRequest):
    """4.5 AC1: a reason is mandatory to reject. ``EventRejection`` already refuses a blank body
    with a 422 before ``reject_event`` runs; this is the guard for any other caller (4.6's
    clarification flow, 6.5's cancellation, a seed script, a test factory)."""

    def __init__(self) -> None:
        super().__init__(DECISION_REASON_REQUIRED_MESSAGE)


# --- decisions -----------------------------------------------------------------------------


def _assert_assigned_coordinator(event: Event, actor: User) -> None:
    if event.assigned_coordinator_id != actor.id:
        raise NotAssignedCoordinator()


def _assert_awaiting_decision(event: Event) -> None:
    if event.status not in _AWAITING_DECISION_STATUSES:
        raise EventNotAwaitingDecision(event)


def _decide(
    db: Session, event: Event, *, actor: User, to_status: str, reason: str | None, action: str
) -> None:
    """Shared machinery for 4.4's approve and 4.5's reject: only the assigned coordinator may
    decide, and only while the request is awaiting decision. The update is conditional on the
    event still being in an awaiting-decision status, so two concurrent decisions on the same
    request cannot both succeed - the same shape as ``submit_event``'s guard against a racing
    double-submit. ``reason`` is written unconditionally, which is what clears a stale
    ``decision_reason`` left by an earlier rejection when a later approval reuses this path
    (relevant once 4.6's clarification round-trip can return a request here more than once).
    """
    _assert_assigned_coordinator(event, actor)
    _assert_awaiting_decision(event)

    from_status = event.status
    decided_at = datetime.now(UTC)
    decided = db.execute(
        update(Event)
        .where(Event.id == event.id, Event.status.in_(_AWAITING_DECISION_STATUSES))
        .values(
            status=to_status, decided_by_id=actor.id, decided_at=decided_at, decision_reason=reason
        )
    )
    if decided.rowcount == 0:
        db.rollback()
        db.refresh(event)
        raise EventNotAwaitingDecision(event)
    _record_transition(
        db,
        event,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        at=decided_at,
        reason=reason,
    )
    details: dict[str, Any] = {"from_status": from_status}
    if reason is not None:
        details["reason"] = reason
    record_audit(
        db,
        actor=actor,
        action=action,
        entity_type="event",
        entity_id=event.id,
        details=details,
        commit=False,
    )
    db.commit()
    db.refresh(event)


def approve_event(db: Session, event: Event, *, actor: User) -> None:
    """4.4 AC1-AC3: approve ``event``, recording the deciding coordinator and time."""
    _decide(
        db, event, actor=actor, to_status=EventStatus.APPROVED, reason=None, action="EVENT_APPROVED"
    )


def reject_event(db: Session, event: Event, *, actor: User, reason: str) -> None:
    """4.5 AC1-AC3: reject ``event`` with ``reason``, recording the deciding coordinator and
    time. Same guards as ``approve_event``."""
    if not reason.strip():
        raise MissingDecisionReason()
    _decide(
        db,
        event,
        actor=actor,
        to_status=EventStatus.REJECTED,
        reason=reason,
        action="EVENT_REJECTED",
    )
