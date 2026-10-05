"""Business logic for event requests (story 2.1), the organiser's own list of them (story 2.6),
event review (story 4.1), requesting clarification from the organiser (story 4.2), the
approve/reject decision (stories 4.4, 4.5), the decision / clarification history an organiser
sees (story 4.6), routine information edits and corrections to a request under review (story
7.2), and the coordinator's assigned events in any status (story 6.1).

Routers translate the exceptions raised here into HTTP statuses. A request belongs to the
organiser who created it: anyone else gets ``EventNotFound``, so a request's existence is not
revealed to people it is not theirs to see.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, lazyload

from app.auth.models import User
from app.auth.permissions import Permission, role_has
from app.common.audit import record_audit
from app.common.notifications import notify
from app.config import settings
from app.coordination import service as coordination_service
from app.events.models import (
    ClarificationKind,
    EquipmentHoldStatus,
    EquipmentReservation,
    EquipmentType,
    EquipmentUnavailabilityPeriod,
    Event,
    EventAccessibilityNeed,
    EventClarification,
    EventEquipmentRequest,
    EventRequiredFacility,
    EventStatus,
    EventStatusHistory,
)
from app.events.schemas import (
    ACCESSIBILITY_CONTRADICTION_MESSAGE,
    REGISTRATION_CONTRADICTION_MESSAGE,
    VENUE_CONTRADICTION_MESSAGE,
    EquipmentAvailabilityOut,
    EventAccessibilityNeedIn,
    EventCreate,
    EventEquipmentIn,
    EventFacilityIn,
    EventReferenceData,
    EventReviewCorrection,
    EventRoutineUpdate,
    EventUpdate,
    ReferenceItemOut,
    ReviewQueueSort,
)
from app.venues.models import AccessibilityFeature, Facility, RoomLayout

_log = logging.getLogger(__name__)

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
REGISTRATION_OPENS_IN_PAST_MESSAGE = "The registration opening date cannot be in the past."
REGISTRATION_CLOSES_IN_PAST_MESSAGE = "The registration closing date cannot be in the past."
REGISTRATION_OPENS_AFTER_START_MESSAGE = "Registration must open no later than the proposed start."
REGISTRATION_CLOSES_AFTER_START_MESSAGE = (
    "Registration must close no later than the proposed start."
)
REGISTRATION_OPENS_AFTER_CLOSES_MESSAGE = "Registration must open before it closes."
NOT_EDITABLE_MESSAGE = "This request has been submitted and can no longer be edited."
ALREADY_SUBMITTED_MESSAGE = "This request has already been submitted."
ROUTINE_EDIT_CLOSED_MESSAGE = (
    "This event is {status}, so its routine information can no longer be edited."
)
DETAILS_LOCKED_MESSAGE = (
    "This event has been approved, so its details can no longer be edited directly. Further "
    "changes must go through a change request."
)
DETAILS_NOT_UNDER_REVIEW_MESSAGE = (
    "This event is {status}, so its details can only be edited while it is under review."
)
STALE_EVENT_EDIT_MESSAGE = (
    "This event has changed since you opened it. Reload it and make your changes again."
)
SUBMITTED_DETAILS_MISSING_MESSAGE = (
    "Add the following before saving this submitted request: {missing}."
)

# ``event_equipment_requests.status`` once the units are held for the event.
_LINE_RESERVED = "RESERVED"
# ``equipment_reservations.notes`` on a hold: why it was placed (2.1 AC11, 7.2 AC7).
_SUBMITTED_HOLD_NOTE = "Held when the request was submitted."
_CORRECTED_HOLD_NOTE = "Held again when the coordinator corrected the request."

# AC20: the partial unique index a duplicate name+dates violates (db/migrations/008_*.sql).
DUPLICATE_REQUEST_INDEX = "uq_events_organiser_name_dates"

_AWAITING_DECISION_STATUSES = (
    EventStatus.UNDER_REVIEW,
    EventStatus.CLARIFICATION_REQUESTED,
)
_SORT_COLUMNS = {
    ReviewQueueSort.SUBMITTED_AT: Event.submitted_at,
    ReviewQueueSort.STARTS_AT: Event.starts_at,
}

# Story 7.2 AC1: the only columns a routine-information edit may touch. Deliberately narrow -
# never widen this to accept arbitrary Event fields (important fields go through story 7.3).
_ROUTINE_FIELDS = ("internal_notes",)

# Story 7.2 AC3: routine editing is refused once the event has reached one of these statuses.
_ROUTINE_EDIT_CLOSED_STATUSES = (EventStatus.COMPLETED, EventStatus.CANCELLED, EventStatus.REJECTED)

# Story 7.2 AC4: the organiser's details may be corrected directly only in this status.
# CLARIFICATION_REQUESTED is deliberately not included: that round-trip belongs to 4.2/4.3.
_DETAILS_CORRECTABLE_STATUS = EventStatus.UNDER_REVIEW
# Story 7.2 AC5: approved and still running - further changes go through a change request (19.1).
_DETAILS_LOCKED_STATUSES = (EventStatus.PLANNING, EventStatus.CONFIRMED)
# Story 7.2 AC7: a correction to any of these places the event's equipment holds again.
_HOLD_FIELDS = frozenset({"starts_at", "ends_at", "equipment"})

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
    "contact_name",
    "contact_email",
    "contact_phone",
    "required_layout_code",
    "venue_requirement_notes",
    "venue_none_required",
    "accessibility_none_required",
    "accessibility_notes",
    "registration_required",
    "registration_opens_at",
    "registration_closes_at",
    "is_public",
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
    # Story 2.1 AC13: all three parts of the point of contact.
    ("contact_name", "point of contact name"),
    ("contact_email", "point of contact email"),
    ("contact_phone", "point of contact phone number"),
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


class RoutineEditClosed(EventStateConflict):
    """7.2 AC3: the event has reached a status where routine information is frozen."""

    def __init__(self, status: str):
        super().__init__(ROUTINE_EDIT_CLOSED_MESSAGE.format(status=status))


class EventDetailsLocked(EventStateConflict):
    """7.2 AC5/AC6: the event has been approved, so its details are read-only."""

    def __init__(self):
        super().__init__(DETAILS_LOCKED_MESSAGE)


class EventNotUnderReview(EventStateConflict):
    """7.2 AC4: details can be corrected only while the event is under review."""

    def __init__(self, status: str):
        super().__init__(DETAILS_NOT_UNDER_REVIEW_MESSAGE.format(status=status))


class StaleEventEdit(EventStateConflict):
    """7.2 AC9: the event changed after the copy being saved was read."""

    def __init__(self):
        super().__init__(STALE_EVENT_EDIT_MESSAGE)


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


class ContradictoryRegistration(InvalidEventRequest):
    def __init__(self):
        super().__init__(REGISTRATION_CONTRADICTION_MESSAGE)


class DuplicateEventRequest(InvalidEventRequest):
    """AC20: another of this organiser's own live requests already has this name and these
    dates."""

    def __init__(self, name: str):
        super().__init__(f'You already have a request named "{name}" for these dates.')


class MissingSubmissionDetails(InvalidEventRequest):
    def __init__(self, missing: list[str]):
        super().__init__(f"Add the following before submitting: {', '.join(missing)}.")
        self.missing = missing


class SubmittedDetailsMissing(InvalidEventRequest):
    """7.2 AC4: a corrected request must still have everything 2.1 AC10 required for submission."""

    def __init__(self, missing: list[str]):
        super().__init__(SUBMITTED_DETAILS_MISSING_MESSAGE.format(missing=", ".join(missing)))
        self.missing = missing


NOT_ASSIGNED_COORDINATOR_MESSAGE = "Only the coordinator assigned to this request may {verb} it."
EVENT_NOT_AWAITING_DECISION_MESSAGE = "This request is {status}, so it cannot be {verb}."
DECISION_REASON_REQUIRED_MESSAGE = "A reason is required to reject this request."
EVENT_NOT_AWAITING_CLARIFICATION_MESSAGE = (
    "You can no longer ask for clarification on this request."
)
CLARIFICATION_MESSAGE_REQUIRED_MESSAGE = "A message is required to request clarification."

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


def list_assigned_events(
    db: Session,
    *,
    coordinator: User,
    limit: int = MY_EVENTS_MAX_LIMIT,
    offset: int = 0,
) -> MyEventsListing:
    """Story 6.1 AC1/AC2: every event assigned to ``coordinator``, in any status - unlike the
    review queue (story 4.1), which only ever returns the three awaiting-decision statuses. A
    draft is never assigned to a coordinator, so it can never appear here. AC3: most recently
    updated first, ties broken by id, paged the same way as the organiser's own list
    (``list_my_events``) - both lists grow across a person's whole history rather than staying
    small like the review queue, so the same shape fits. ``assigned_coordinator`` is the caller
    themselves and needs no name, so only ``organiser`` is left to load eagerly."""
    is_assigned = Event.assigned_coordinator_id == coordinator.id
    page = (
        select(Event)
        .options(lazyload(Event.assigned_coordinator))
        .where(is_assigned)
        .order_by(Event.updated_at.desc(), Event.id)
        .limit(limit)
        .offset(offset)
    )
    total = db.scalar(select(func.count()).select_from(Event).where(is_assigned))
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


NOT_RELATED_PARTY_MESSAGE = (
    "Only the organiser and the coordinator assigned to this request may view its clarifications."
)


class NotRelatedParty(PermissionError):
    """Only the organiser and the event's assigned coordinator may read the clarification
    conversation - narrower than ``get_event``'s visibility, which any internal role with
    ``events:read_all`` satisfies."""

    def __init__(self) -> None:
        super().__init__(NOT_RELATED_PARTY_MESSAGE)


def _can_view_clarifications(viewer: User, event: Event) -> bool:
    return event.organiser_id == viewer.id or event.assigned_coordinator_id == viewer.id


def list_clarifications(
    db: Session, event_id: uuid.UUID, *, viewer: User
) -> list[EventClarification]:
    """4.6 AC2: the clarification conversation on a request, oldest first - visible only to the
    organiser and to the coordinator assigned to this event, not to internal roles generally,
    even though they can read the event record itself via ``get_event``. A viewer who cannot see
    the event at all gets ``EventNotFound``, same as ``get_event``; one who can see the event but
    is not organiser or assigned coordinator gets ``NotRelatedParty`` instead."""
    event = get_event(db, event_id, viewer=viewer)
    if not _can_view_clarifications(viewer, event):
        raise NotRelatedParty()
    return list(
        db.scalars(
            select(EventClarification)
            .where(EventClarification.event_id == event_id)
            .order_by(EventClarification.created_at, EventClarification.id)
        ).all()
    )


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


def _check_registration(
    *,
    required: bool,
    opens_at: datetime | None,
    closes_at: datetime | None,
    starts_at: datetime | None,
    supplied_opens_at: datetime | None,
    supplied_closes_at: datetime | None,
) -> None:
    """AC17: neither date can be recorded unless registration is required. Each must be no later
    than the proposed start (equal is fine), and - only when it is the value this call is
    actually setting, not one merely carried over - each must not be in the past. The opening
    date, when given alongside a closing date, must be strictly before it: the schema's own
    ``ck_events_registration_window`` requires a registration window of positive width, since a
    window open and closed at the same instant could never be used, so equal is refused here
    too rather than left for the database to reject. Checking both dates against the effective
    ``starts_at`` rather than only a freshly supplied one is what makes AC18 work: moving the
    start earlier than an already-saved date is refused through this same check, the same way
    ``_check_schedule`` already checks ``ends_at`` against a freshly supplied ``starts_at``."""
    if not required:
        if opens_at is not None or closes_at is not None:
            raise ContradictoryRegistration()
        return
    if supplied_opens_at is not None and supplied_opens_at < datetime.now(UTC):
        raise InvalidSchedule(REGISTRATION_OPENS_IN_PAST_MESSAGE)
    if supplied_closes_at is not None and supplied_closes_at < datetime.now(UTC):
        raise InvalidSchedule(REGISTRATION_CLOSES_IN_PAST_MESSAGE)
    if opens_at is not None and closes_at is not None and opens_at >= closes_at:
        raise InvalidSchedule(REGISTRATION_OPENS_AFTER_CLOSES_MESSAGE)
    if starts_at is not None:
        if opens_at is not None and opens_at > starts_at:
            raise InvalidSchedule(REGISTRATION_OPENS_AFTER_START_MESSAGE)
        if closes_at is not None and closes_at > starts_at:
            raise InvalidSchedule(REGISTRATION_CLOSES_AFTER_START_MESSAGE)


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
    db: Session,
    period_start: datetime,
    period_end: datetime,
    *,
    exclude_event_id: uuid.UUID | None = None,
) -> dict[uuid.UUID, int]:
    """AC6: units free for a period, per equipment type: the stock, less units held for other
    events over the period (a hold's quantity less what was released), less units out of service.
    Overlap is half-open, so a hold ending exactly as the period starts does not count.
    Story 7.2 AC7: ``exclude_event_id`` leaves that event's own holds out, so an event being
    corrected is not counted against itself."""
    held_query = (
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
    )
    if exclude_event_id is not None:
        held_query = held_query.where(EquipmentReservation.event_id != exclude_event_id)
    held = dict(db.execute(held_query).all())
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
    db: Session,
    *,
    starts_at: datetime,
    ends_at: datetime,
    exclude_event_id: uuid.UUID | None = None,
    viewer: User,
) -> list[EquipmentAvailabilityOut]:
    """AC6: how many of each active equipment type are free for the proposed dates. Story 7.2
    AC7: with ``exclude_event_id``, as the request being corrected sees it - its own holds left
    out. Only an event the viewer can see may be named, so nothing is learnt about any other."""
    if ends_at <= starts_at:
        raise InvalidSchedule(END_NOT_AFTER_START_MESSAGE)
    if exclude_event_id is not None:
        get_event(db, exclude_event_id, viewer=viewer)
    available = _available_by_type(db, starts_at, ends_at, exclude_event_id=exclude_event_id)
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
    *,
    exclude_event_id: uuid.UUID | None = None,
) -> None:
    """AC6: no more of a type than is free for the dates. Until both dates are known there is no
    period to check, and submission needs them anyway, where it is checked again.
    ``exclude_event_id`` leaves that event's own holds out (story 7.2 AC7)."""
    if starts_at is None or ends_at is None or not lines:
        return
    available = _available_by_type(db, starts_at, ends_at, exclude_event_id=exclude_event_id)
    short = [t.name for t, quantity in lines if quantity > available[t.id]]
    if short:
        raise EquipmentNotAvailable(short)


def _hold_equipment(db: Session, event: Event, actor: User, *, notes: str) -> None:
    """AC11: hold the request's equipment for its dates. The types are locked first, so two
    requests for the last units cannot both be held; the loser is refused and nothing is held.
    ``notes`` says why the hold was placed: on submission, or again after a 7.2 correction."""
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
                notes=notes,
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
    _check_registration(
        required=data.registration_required,
        opens_at=data.registration_opens_at,
        closes_at=data.registration_closes_at,
        starts_at=data.starts_at,
        supplied_opens_at=data.registration_opens_at,
        supplied_closes_at=data.registration_closes_at,
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
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if DUPLICATE_REQUEST_INDEX in str(exc.orig):
            raise DuplicateEventRequest(data.name) from exc
        raise
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


def _resent_unchanged(value: datetime | None, stored: datetime | None) -> datetime | None:
    """``None`` when ``value`` is exactly what is already stored - the edit form always resends
    every field (frontend/CLAUDE.md: "the form always sends every field"), so ``field in sent``
    alone cannot tell "the organiser just typed this" apart from "this rode along unchanged".
    Without this, a date that was fine when saved but has since drifted into the past blocks
    saving anything else on the request, forever, since every edit resends it. A value the
    organiser did genuinely change to match what is already stored is indistinguishable from one
    that merely rode along - and is correctly not re-judged either way, the same as any other
    no-op edit."""
    return None if value == stored else value


@dataclass(frozen=True)
class _RequestEdit:
    """A request edit that has passed every 2.1 check: the columns to set, and the equipment types
    its equipment lines name."""

    details: dict[str, Any]
    equipment_types: dict[str, EquipmentType]


def _validate_request_edit(db: Session, event: Event, data: EventUpdate) -> _RequestEdit:
    """AC2-AC7/AC17/AC18: every 2.1 check on an edit to ``event``, before anything is changed, so
    a refused edit leaves the request as it was. Shared by the organiser's draft edit (AC7) and the
    coordinator's correction under review (story 7.2 AC4), so the two can never drift apart.
    Equipment availability leaves ``event``'s own holds out (story 7.2 AC7); a draft has none."""
    sent = data.model_fields_set
    details = {field: getattr(data, field) for field in _DETAIL_FIELDS if field in sent}
    starts_at = details.get("starts_at", event.starts_at)
    ends_at = details.get("ends_at", event.ends_at)
    if sent & {"starts_at", "ends_at"}:
        _check_schedule(
            starts_at,
            ends_at,
            supplied_start=_resent_unchanged(details.get("starts_at"), event.starts_at),
            supplied_end=_resent_unchanged(details.get("ends_at"), event.ends_at),
        )
    # AC18: re-checked whenever the start moves too, not just when a registration date itself is
    # edited - a saved date that a start change would put after it is refused here, unlike AC2's
    # own dates, which are not re-judged when something else is edited.
    if sent & {
        "starts_at",
        "registration_required",
        "registration_opens_at",
        "registration_closes_at",
    }:
        _check_registration(
            required=details.get("registration_required", event.registration_required),
            opens_at=details.get("registration_opens_at", event.registration_opens_at),
            closes_at=details.get("registration_closes_at", event.registration_closes_at),
            starts_at=starts_at,
            supplied_opens_at=_resent_unchanged(
                details.get("registration_opens_at"), event.registration_opens_at
            ),
            supplied_closes_at=_resent_unchanged(
                details.get("registration_closes_at"), event.registration_closes_at
            ),
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
        _check_equipment_available(db, starts_at, ends_at, lines, exclude_event_id=event.id)
    return _RequestEdit(details=details, equipment_types=types)


def _apply_request_edit(
    event: Event, data: EventUpdate, edit: _RequestEdit, *, actor: User
) -> None:
    """AC7: set what ``edit`` validated. Only the fields sent change; a list sent replaces that
    list."""
    for field, value in edit.details.items():
        setattr(event, field, value)
    if data.required_facilities is not None:
        _replace_facilities(event, data.required_facilities)
    if data.accessibility_needs is not None:
        _replace_accessibility_needs(event, data.accessibility_needs)
    if data.equipment is not None:
        _replace_equipment(event, data.equipment, edit.equipment_types, actor=actor)
    # A change to a list alone would not touch the events row; stamping it makes updated_at the
    # request's last-modified time whatever was edited (the trigger sets the real value).
    event.updated_at = datetime.now(UTC)


def _flush_request_edit(db: Session, event: Event) -> None:
    """Write an applied edit, translating AC20's duplicate-request index into
    ``DuplicateEventRequest``."""
    # Read before the flush: a rollback below expires this object, so event.name read afterwards
    # would re-fetch the pre-update value instead of the one the failed write attempted.
    attempted_name = event.name
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if DUPLICATE_REQUEST_INDEX in str(exc.orig):
            raise DuplicateEventRequest(attempted_name) from exc
        raise


def update_event(db: Session, event_id: uuid.UUID, data: EventUpdate, *, actor: User) -> Event:
    """AC7: edit or remove any recorded detail, requirement or equipment item while a draft.
    Only the fields sent change; a list sent replaces that list."""
    event = _get_own_event(db, event_id, actor)
    if event.status != EventStatus.DRAFT:
        raise EventNotEditable()

    edit = _validate_request_edit(db, event, data)
    _apply_request_edit(event, data, edit, actor=actor)
    _flush_request_edit(db, event)
    record_audit(
        db,
        actor=actor,
        action="EVENT_UPDATED",
        entity_type="event",
        entity_id=event.id,
        details={"fields": sorted(data.model_fields_set)},
        commit=False,
    )
    db.commit()
    db.refresh(event)
    return event


def _missing_for_submission(event: Event) -> list[str]:
    """AC10/AC13/AC17: every event detail and the point of contact must be filled in, venue
    requirements and accessibility needs each answered - something chosen or written, or marked
    "none required" - and, only when Registration required is Yes, a registration closing date.
    Registration capacity needs no check of its own: it is always expected attendance, already
    covered by the event-detail check above."""
    missing = [
        label for field, label in _REQUIRED_DETAILS_FOR_SUBMISSION if getattr(event, field) is None
    ]
    if event.registration_required and event.registration_closes_at is None:
        missing.append("registration closing date")
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
    """AC9-AC12: submit ``actor``'s own draft once its four mandatory details are filled in.
    Story 5.1 AC1: submitting also auto-assigns the next coordinator in round robin, in this
    same transaction - see ``coordination.service.auto_assign_next_coordinator``."""
    event = _get_own_event(db, event_id, actor)
    if event.status != EventStatus.DRAFT:
        raise EventAlreadySubmitted()
    missing = _missing_for_submission(event)
    if missing:
        raise MissingSubmissionDetails(missing)
    _check_schedule(
        event.starts_at, event.ends_at, supplied_start=event.starts_at, supplied_end=None
    )
    # AC17: a registration date that was fine when saved but has since passed also blocks
    # submission, the same way AC2 treats the start - forced by treating the stored values as
    # supplied.
    _check_registration(
        required=event.registration_required,
        opens_at=event.registration_opens_at,
        closes_at=event.registration_closes_at,
        starts_at=event.starts_at,
        supplied_opens_at=event.registration_opens_at,
        supplied_closes_at=event.registration_closes_at,
    )

    _hold_equipment(db, event, actor, notes=_SUBMITTED_HOLD_NOTE)
    submitted_at = datetime.now(UTC)
    # Conditional on still being a draft, so two submissions racing cannot both succeed.
    # Goes straight to UNDER_REVIEW (migration 002, bug b6.1.1) - SUBMITTED is no longer a
    # status an event can sit in.
    submitted = db.execute(
        update(Event)
        .where(Event.id == event.id, Event.status == EventStatus.DRAFT)
        .values(status=EventStatus.UNDER_REVIEW, submitted_at=submitted_at)
    )
    if submitted.rowcount == 0:
        db.rollback()
        raise EventAlreadySubmitted()
    _record_transition(
        db,
        event,
        from_status=EventStatus.DRAFT,
        to_status=EventStatus.UNDER_REVIEW,
        actor=actor,
        at=submitted_at,
        reason=None,
    )
    coordination_service.auto_assign_next_coordinator(db, event)
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


# --- cover picture (story 2.1 AC14) ---------------------------------------------------------
COVER_IMAGE_TOO_LARGE_MESSAGE = "The picture must be 5 MB or smaller."
COVER_IMAGE_UNSUPPORTED_MESSAGE = "Choose a JPEG, PNG or WebP picture."
# The most a cover picture may weigh. Keep in step with the frontend's MAX_COVER_IMAGE_BYTES.
MAX_COVER_IMAGE_BYTES = 5 * 1024 * 1024
# Where uploads are served from: ``/uploads/events/<file>``, under ``settings.upload_dir``. A
# picture at any other address (a seeded one under the frontend) is not ours to delete.
COVER_IMAGE_URL_PREFIX = "/uploads/events/"
_COVER_IMAGE_FOLDER = "events"
# What each accepted format starts with, and the extension and content type it is stored as.
# The bytes decide the type: a file's name and declared type are the client's word only.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"
COVER_IMAGE_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}


class CoverImageTooLarge(ValueError):
    def __init__(self):
        super().__init__(COVER_IMAGE_TOO_LARGE_MESSAGE)


class UnsupportedCoverImage(InvalidEventRequest):
    def __init__(self):
        super().__init__(COVER_IMAGE_UNSUPPORTED_MESSAGE)


def _cover_image_extension(content: bytes) -> str | None:
    if content.startswith(_PNG_SIGNATURE):
        return ".png"
    if content.startswith(_JPEG_SIGNATURE):
        return ".jpg"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return None


def cover_image_path(filename: str) -> Path:
    """Where the stored picture called ``filename`` lives. The caller has already checked the
    name is one the server generated, so it cannot climb out of the folder."""
    return settings.upload_dir / _COVER_IMAGE_FOLDER / filename


def _delete_cover_image_file(url: str | None) -> None:
    """Remove the file behind ``url`` when it is one of ours. An absent file is not an error, and
    neither is one that cannot be removed (locked on Windows, say): this runs after the change was
    committed, so failing here would report a save that worked as a failure. It is logged, and the
    file is left behind."""
    if url is None or not url.startswith(COVER_IMAGE_URL_PREFIX):
        return
    path = cover_image_path(url.removeprefix(COVER_IMAGE_URL_PREFIX))
    try:
        path.unlink(missing_ok=True)
    except OSError:
        _log.warning("Could not delete the replaced cover picture %s", path, exc_info=True)


def _cover_image_extension_or_refuse(content: bytes) -> str:
    """AC14: the extension ``content`` is stored as, or the reason it is refused."""
    if len(content) > MAX_COVER_IMAGE_BYTES:
        raise CoverImageTooLarge()
    extension = _cover_image_extension(content)
    if extension is None:
        raise UnsupportedCoverImage()
    return extension


def _replace_cover_image(
    db: Session, event: Event, content: bytes, extension: str, *, actor: User, action: str
) -> None:
    """Store ``content`` as ``event``'s cover picture and commit, recording the old and new
    address (story 7.4). The file is written first and the old one deleted only once the new
    address is stored, so a failure never leaves the request pointing at a file that is gone."""
    filename = f"{uuid.uuid4()}{extension}"
    path = cover_image_path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    previous_url = event.cover_image_url
    new_url = f"{COVER_IMAGE_URL_PREFIX}{filename}"
    try:
        event.cover_image_url = new_url
        event.updated_at = datetime.now(UTC)
        record_audit(
            db,
            actor=actor,
            action=action,
            entity_type="event",
            entity_id=event.id,
            details={"cover_image_url": {"from": previous_url, "to": new_url}},
            commit=False,
        )
        db.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    _delete_cover_image_file(previous_url)
    db.refresh(event)


def _clear_cover_image(db: Session, event: Event, *, actor: User, action: str) -> None:
    """Take ``event``'s cover picture off and commit, recording the old address (story 7.4), then
    delete its file."""
    previous_url = event.cover_image_url
    event.cover_image_url = None
    event.updated_at = datetime.now(UTC)
    record_audit(
        db,
        actor=actor,
        action=action,
        entity_type="event",
        entity_id=event.id,
        details={"cover_image_url": {"from": previous_url, "to": None}},
        commit=False,
    )
    db.commit()
    _delete_cover_image_file(previous_url)
    db.refresh(event)


def set_cover_image(db: Session, event_id: uuid.UUID, content: bytes, *, actor: User) -> Event:
    """AC14: give ``actor``'s own draft a cover picture, replacing any it had."""
    event = _get_own_event(db, event_id, actor)
    if event.status != EventStatus.DRAFT:
        raise EventNotEditable()
    extension = _cover_image_extension_or_refuse(content)
    _replace_cover_image(db, event, content, extension, actor=actor, action="EVENT_COVER_IMAGE_SET")
    return event


def remove_cover_image(db: Session, event_id: uuid.UUID, *, actor: User) -> Event:
    """AC14: take the cover picture off ``actor``'s own draft, and delete its file."""
    event = _get_own_event(db, event_id, actor)
    if event.status != EventStatus.DRAFT:
        raise EventNotEditable()
    if event.cover_image_url is None:
        return event
    _clear_cover_image(db, event, actor=actor, action="EVENT_COVER_IMAGE_REMOVED")
    return event


class NotAssignedCoordinator(PermissionError):
    """Only the coordinator ``events.assigned_coordinator_id`` names may act on the request.
    ``verb`` names the refused action (``"decide"``, ``"edit"``) so 4.4/4.5's decision and 7.2's
    routine edit do not share one message - backend/STYLE.md: two messages never share one
    string."""

    def __init__(self, verb: str) -> None:
        super().__init__(NOT_ASSIGNED_COORDINATOR_MESSAGE.format(verb=verb))


class EventNotAwaitingDecision(EventStateConflict):
    """4.4 AC1 / 4.5 AC2: only a request in ``_AWAITING_DECISION_STATUSES`` may be decided -
    refuses repeat or invalid-state decisions (e.g. a request already decided, or past
    PLANNING). ``verb`` names the refused action purely so the sentence reads naturally for
    whichever decision was attempted (two messages never share one string - backend/STYLE.md), not
    because approve and reject differ in which statuses they allow. A draft never reaches this
    guard: ``get_event`` hides it from the coordinator first, so that case is a 404, not a 409."""

    def __init__(self, event: Event, *, verb: str) -> None:
        super().__init__(EVENT_NOT_AWAITING_DECISION_MESSAGE.format(status=event.status, verb=verb))
        self.event = event


class MissingDecisionReason(InvalidEventRequest):
    """4.5 AC1: a reason is mandatory to reject. ``EventRejection`` already refuses a blank body
    with a 422 before ``reject_event`` runs; this is the guard for any other caller (4.6's
    clarification flow, 6.5's cancellation, a seed script, a test factory)."""

    def __init__(self) -> None:
        super().__init__(DECISION_REASON_REQUIRED_MESSAGE)


class EventNotAwaitingClarification(EventStateConflict):
    """4.2 AC6/AC7: only a request currently Under Review, or already awaiting the organiser's
    response to an earlier round (AC4 - several rounds are allowed), may have clarification
    requested on it. Covers both the ordinary case (the request had already moved on before this
    call started) and the race where it moves on between opening the page and pressing Send - a
    reassignment or a decision landing while the coordinator was still composing their message.
    Carries no ``{status}`` the way ``EventNotAwaitingDecision`` does: after a reassignment race
    the status may still read UNDER_REVIEW (reassignment changes ``assigned_coordinator_id``, not
    status), so printing it would contradict the sentence."""

    def __init__(self, event: Event) -> None:
        super().__init__(EVENT_NOT_AWAITING_CLARIFICATION_MESSAGE)
        self.event = event


class MissingClarificationMessage(InvalidEventRequest):
    """4.2 AC3: a message is mandatory. ``ClarificationRequest`` already refuses a blank body
    with a 422 before ``request_clarification`` runs; this is the guard for any other caller,
    mirroring ``MissingDecisionReason``."""

    def __init__(self) -> None:
        super().__init__(CLARIFICATION_MESSAGE_REQUIRED_MESSAGE)


# --- decisions -----------------------------------------------------------------------------


def _assert_assigned_coordinator(event: Event, actor: User, *, verb: str) -> None:
    if event.assigned_coordinator_id != actor.id:
        raise NotAssignedCoordinator(verb)


def _assert_awaiting_decision(
    event: Event, allowed_statuses: tuple[str, ...], *, verb: str
) -> None:
    if event.status not in allowed_statuses:
        raise EventNotAwaitingDecision(event, verb=verb)


def _decide(
    db: Session,
    event: Event,
    *,
    actor: User,
    to_status: str,
    reason: str | None,
    action: str,
    allowed_statuses: tuple[str, ...],
    verb: str,
) -> None:
    """Shared machinery for 4.4's approve and 4.5's reject: only the assigned coordinator may
    decide, and only while the request is in one of ``allowed_statuses`` - both callers pass
    ``_AWAITING_DECISION_STATUSES``, so a request sent back for clarification may be decided
    either way. The update is conditional on the event still being in an allowed status, so two
    concurrent decisions on the
    same request cannot both succeed - the same shape as ``submit_event``'s guard against a
    racing double-submit. ``reason`` is written unconditionally, which is what clears a stale
    ``decision_reason`` left by an earlier rejection when a later approval reuses this path
    (relevant once 4.6's clarification round-trip can return a request here more than once).
    """
    _assert_assigned_coordinator(event, actor, verb="decide")
    _assert_awaiting_decision(event, allowed_statuses, verb=verb)

    from_status = event.status
    decided_at = datetime.now(UTC)
    decided = db.execute(
        update(Event)
        .where(Event.id == event.id, Event.status.in_(allowed_statuses))
        .values(
            status=to_status, decided_by_id=actor.id, decided_at=decided_at, decision_reason=reason
        )
    )
    if decided.rowcount == 0:
        db.rollback()
        db.refresh(event)
        raise EventNotAwaitingDecision(event, verb=verb)
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
    """4.4 AC1-AC3: approve ``event``, recording the deciding coordinator and time. Goes straight
    to PLANNING (migration 002, bug b6.1.1) - APPROVED is no longer a status an event can sit
    in."""
    _decide(
        db,
        event,
        actor=actor,
        to_status=EventStatus.PLANNING,
        reason=None,
        action="EVENT_APPROVED",
        allowed_statuses=_AWAITING_DECISION_STATUSES,
        verb="approved",
    )


def reject_event(db: Session, event: Event, *, actor: User, reason: str) -> None:
    """4.5 AC1-AC3: reject ``event`` with ``reason``, recording the deciding coordinator and
    time. Rejecting is now allowed from the same statuses as approving (bug b6.1.1's narrower
    reject rule has been reversed): a request sent back for clarification may be rejected
    outright, the same as approving it."""
    if not reason.strip():
        raise MissingDecisionReason()
    _decide(
        db,
        event,
        actor=actor,
        to_status=EventStatus.REJECTED,
        allowed_statuses=_AWAITING_DECISION_STATUSES,
        verb="rejected",
        reason=reason,
        action="EVENT_REJECTED",
    )


# --- request clarification (story 4.2) -------------------------------------------------------


def request_clarification(
    db: Session, event: Event, *, actor: User, message: str
) -> EventClarification:
    """4.2 AC1/AC2/AC4-AC7: the assigned coordinator asks the organiser a question while the
    request is Under Review, or asks a follow-up while it already awaits a response to an earlier
    round (AC4) - the event moves to, or stays at, CLARIFICATION_REQUESTED. Nothing until story
    4.3 ever moves the event back to Under Review on its own, so a second round has to work
    directly from CLARIFICATION_REQUESTED rather than waiting for a trip back. The new
    ``EventClarification`` row and the organiser's notification are always written; the
    status-history row only when the status is actually changing (the first round) - a follow-up
    is a new message, not a new transition. All of it is written in one transaction (AC2).
    Whether this is the first round is taken from the first UPDATE's ``rowcount``, never from the
    already-loaded ``event``: two requests that both read Under Review before either writes would
    otherwise both record the transition into the append-only status history (AC7). Both UPDATEs
    repeat the assigned-coordinator check in their WHERE clause, so a reassignment or a decision
    racing this call between the checks above and the write is refused too (AC7) - those checks
    only give the ordinary, non-racing case its own accurate exception rather than a generic
    409."""
    stripped = message.strip()
    if not stripped:
        raise MissingClarificationMessage()
    _assert_assigned_coordinator(event, actor, verb="request clarification on")
    if event.status not in _AWAITING_DECISION_STATUSES:
        raise EventNotAwaitingClarification(event)

    changed_at = datetime.now(UTC)
    moved = db.execute(
        update(Event)
        .where(
            Event.id == event.id,
            Event.status == EventStatus.UNDER_REVIEW,
            Event.assigned_coordinator_id == actor.id,
        )
        .values(status=EventStatus.CLARIFICATION_REQUESTED)
    )
    is_first_round = moved.rowcount == 1
    if not is_first_round:
        # Not the first round, so the row has to still be awaiting a response to an earlier one.
        # Re-writing the status it already holds is that check: a SELECT would race the very
        # reassignment or decision this guards against.
        still_awaiting = db.execute(
            update(Event)
            .where(
                Event.id == event.id,
                Event.status == EventStatus.CLARIFICATION_REQUESTED,
                Event.assigned_coordinator_id == actor.id,
            )
            .values(status=EventStatus.CLARIFICATION_REQUESTED)
        )
        if still_awaiting.rowcount == 0:
            db.rollback()
            db.refresh(event)
            raise EventNotAwaitingClarification(event)

    entry = EventClarification(
        event_id=event.id, author_id=actor.id, kind=ClarificationKind.REQUEST, message=stripped
    )
    db.add(entry)
    if is_first_round:
        _record_transition(
            db,
            event,
            from_status=EventStatus.UNDER_REVIEW,
            to_status=EventStatus.CLARIFICATION_REQUESTED,
            actor=actor,
            at=changed_at,
            reason=stripped,
        )
    notify(
        db,
        recipient=event.organiser,
        notification_type="EVENT_CLARIFICATION_REQUESTED",
        event_id=event.id,
        title=f'Clarification requested on "{event.name}"',
        message=stripped,
        related_entity_type="event",
        related_entity_id=event.id,
        commit=False,
    )
    record_audit(
        db,
        actor=actor,
        action="EVENT_CLARIFICATION_REQUESTED",
        entity_type="event",
        entity_id=event.id,
        details={"message": stripped},
        commit=False,
    )
    db.commit()
    db.refresh(event)
    db.refresh(entry)
    return entry


# --- routine information edit (story 7.2) ---------------------------------------------------


def update_routine_information(
    db: Session, event: Event, data: EventRoutineUpdate, *, actor: User
) -> None:
    """AC1-AC3: the coordinator assigned to ``event`` edits its routine fields directly. Only
    the fields sent change, and only ``_ROUTINE_FIELDS`` may ever be touched - never the
    important fields story 7.3 owns. AC3's status gate is checked before the assignment check,
    so a closed event always refuses with 409 regardless of who is asking, rather than a 403
    that names the wrong reason. The write itself stays conditional on the event not yet being
    in a closed status, so a routine edit racing another request's status change still cannot
    land on a request AC3 says is frozen - the same shape as ``submit_event``'s and ``_decide``'s
    guard against a racing status change. A body with nothing to change is a no-op: no write, no
    audit entry, ``updated_at`` untouched."""
    if event.status in _ROUTINE_EDIT_CLOSED_STATUSES:
        raise RoutineEditClosed(event.status)
    _assert_assigned_coordinator(event, actor, verb="edit")

    sent = data.model_fields_set
    changed = {field: getattr(data, field) for field in _ROUTINE_FIELDS if field in sent}
    if not changed:
        return
    updated = db.execute(
        update(Event)
        .where(Event.id == event.id, Event.status.notin_(_ROUTINE_EDIT_CLOSED_STATUSES))
        .values(**changed, updated_at=datetime.now(UTC))
    )
    if updated.rowcount == 0:
        db.rollback()
        db.refresh(event)
        raise RoutineEditClosed(event.status)
    record_audit(
        db,
        actor=actor,
        action="EVENT_ROUTINE_INFO_UPDATED",
        entity_type="event",
        entity_id=event.id,
        details={"fields": sorted(changed)},
        commit=False,
    )
    db.commit()
    db.refresh(event)


# --- correcting details under review (story 7.2 AC4-AC9) -------------------------------------


def _refuse_unless_correctable(event: Event) -> None:
    """AC4/AC5: only an event under review takes corrections; an approved one is locked."""
    if event.status in _DETAILS_LOCKED_STATUSES:
        raise EventDetailsLocked()
    if event.status != _DETAILS_CORRECTABLE_STATUS:
        raise EventNotUnderReview(event.status)


def _claim_for_correction(db: Session, event: Event, *, expected_updated_at: datetime) -> None:
    """AC6/AC9: take the event row for this correction, provided it is still under review and
    still exactly the copy the coordinator read. The update is conditional, the same shape as
    ``_decide``'s guard: an approval or any other change that landed first makes it match no row,
    and the correction is refused. Once taken, the row stays locked until this transaction ends,
    so an approval arriving meanwhile waits and then approves the corrected event."""
    claimed = db.execute(
        update(Event)
        .where(
            Event.id == event.id,
            Event.status == _DETAILS_CORRECTABLE_STATUS,
            Event.updated_at == expected_updated_at,
        )
        .values(updated_at=datetime.now(UTC))
    )
    if claimed.rowcount == 0:
        db.rollback()
        db.refresh(event)
        _refuse_unless_correctable(event)
        raise StaleEventEdit()


def _audit_value(value: Any) -> Any:
    """A column value as JSON the audit log can hold: a moment as ISO 8601 in UTC, so the same
    instant sent with another offset never reads as a change."""
    return value.astimezone(UTC).isoformat() if isinstance(value, datetime) else value


def _request_values(event: Event) -> dict[str, Any]:
    """AC4 / story 7.4: every organiser-provided value on the request, comparable before and after
    a correction. Lists are sorted by code, so a reordering alone is not a change."""
    values = {field: _audit_value(getattr(event, field)) for field in _DETAIL_FIELDS}
    values["required_facilities"] = sorted(
        (
            {"code": f.facility_code, "quantity": f.quantity, "notes": f.notes}
            for f in event.required_facilities
        ),
        key=lambda item: item["code"],
    )
    values["accessibility_needs"] = sorted(
        ({"code": n.feature_code, "notes": n.notes} for n in event.accessibility_needs),
        key=lambda item: item["code"],
    )
    values["equipment"] = sorted(
        (
            {
                "equipment_type_code": line.equipment_type.code,
                "quantity": line.quantity,
                "technical_notes": line.technical_notes,
            }
            for line in event.equipment_requests
        ),
        key=lambda item: item["equipment_type_code"],
    )
    return values


def _replace_equipment_holds(db: Session, event: Event, *, actor: User) -> None:
    """AC7: release the holds 2.1 AC11 placed for ``event`` and hold its equipment again for its
    current lines and dates. Releasing first means the event's own units are free to it again;
    ``_hold_equipment`` then locks the types and refuses if anything is short, and the caller's
    rollback restores the old holds. An event seeded with lines but no holds simply gains them."""
    db.execute(
        update(EquipmentReservation)
        .where(
            EquipmentReservation.event_id == event.id,
            EquipmentReservation.status == EquipmentHoldStatus.RESERVED,
        )
        .values(
            status=EquipmentHoldStatus.RELEASED,
            released_quantity=EquipmentReservation.quantity,
            released_at=datetime.now(UTC),
        )
    )
    _hold_equipment(db, event, actor, notes=_CORRECTED_HOLD_NOTE)


def _apply_correction(
    db: Session, event: Event, data: EventReviewCorrection, *, actor: User
) -> dict[str, dict[str, Any]]:
    """AC4/AC7: validate and apply ``data`` with the 2.1 checks, write it, and hold the equipment
    again when the dates or the equipment changed. Returns each changed field as
    ``{"from": ..., "to": ...}``; an empty result means nothing changed and nothing was written.
    A correction that changes something must leave the request with everything 2.1 AC10 requires
    for submission - including a detail that was already missing (a seeded request predating the
    point of contact), so a field marked required on the form always is."""
    before = _request_values(event)
    edit = _validate_request_edit(db, event, data)
    _apply_request_edit(event, data, edit, actor=actor)
    after = _request_values(event)
    changes = {
        field: {"from": before[field], "to": value}
        for field, value in after.items()
        if value != before[field]
    }
    if not changes:
        return changes
    missing = _missing_for_submission(event)
    if missing:
        raise SubmittedDetailsMissing(missing)
    _flush_request_edit(db, event)
    if changes.keys() & _HOLD_FIELDS:
        _replace_equipment_holds(db, event, actor=actor)
    return changes


def correct_event_under_review(
    db: Session, event: Event, data: EventReviewCorrection, *, actor: User
) -> None:
    """AC4-AC9: the coordinator assigned to ``event`` corrects the organiser's request while it is
    under review, without the organiser's approval and without changing its status.

    The status gate comes first, as with the internal-notes edit (AC3), so a locked or closed
    event refuses with 409 whoever asks; then only the assigned coordinator may go on (AC8).
    ``_claim_for_correction`` is the real guard for AC6/AC9 - the status check above it only picks
    the message. Any refusal after the claim rolls the whole correction back, so the event, its
    equipment lines and its holds are left exactly as they were (AC7). Each saved correction
    writes one ``EVENT_DETAILS_CORRECTED`` audit row holding every changed field's old and new
    value, for story 7.4 to read; one that changes nothing writes nothing.

    AC9's organiser-vs-coordinator case needs story 4.3, which will let an organiser edit a
    submitted request; that edit must claim the row the same way."""
    _refuse_unless_correctable(event)
    _assert_assigned_coordinator(event, actor, verb="edit")
    _claim_for_correction(db, event, expected_updated_at=data.expected_updated_at)
    try:
        changes = _apply_correction(db, event, data, actor=actor)
    except InvalidEventRequest:
        db.rollback()
        raise
    except EventStateConflict:
        db.rollback()
        raise
    if not changes:
        db.rollback()  # gives back the claim, which only stamped updated_at
        return
    record_audit(
        db,
        actor=actor,
        action="EVENT_DETAILS_CORRECTED",
        entity_type="event",
        entity_id=event.id,
        details=changes,
        commit=False,
    )
    db.commit()
    db.refresh(event)


def set_cover_image_under_review(
    db: Session, event: Event, content: bytes, *, actor: User, expected_updated_at: datetime
) -> None:
    """AC4: the coordinator assigned to ``event`` replaces its cover picture while it is under
    review, under the same checks as the organiser's (2.1 AC14). Refused once approved or closed
    (AC5/AC6) or when the copy being saved is stale (AC9), exactly as a JSON correction is; the
    picture is checked before the row is taken, so a refused file changes nothing. Recorded as a
    correction, with the old and new address, for story 7.4."""
    _refuse_unless_correctable(event)
    _assert_assigned_coordinator(event, actor, verb="edit")
    extension = _cover_image_extension_or_refuse(content)
    _claim_for_correction(db, event, expected_updated_at=expected_updated_at)
    _replace_cover_image(
        db, event, content, extension, actor=actor, action="EVENT_DETAILS_CORRECTED"
    )


def remove_cover_image_under_review(
    db: Session, event: Event, *, actor: User, expected_updated_at: datetime
) -> None:
    """AC4: the coordinator assigned to ``event`` takes its cover picture off while it is under
    review, under the same rules as ``set_cover_image_under_review``. Nothing to take off is a
    no-op: no write, no audit entry."""
    _refuse_unless_correctable(event)
    _assert_assigned_coordinator(event, actor, verb="edit")
    _claim_for_correction(db, event, expected_updated_at=expected_updated_at)
    if event.cover_image_url is None:
        db.rollback()  # gives back the claim, which only stamped updated_at
        return
    _clear_cover_image(db, event, actor=actor, action="EVENT_DETAILS_CORRECTED")
