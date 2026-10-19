"""Business logic for event requests (story 2.1), the organiser's own list of them (story 2.6),
event review (story 4.1), requesting clarification from the organiser (story 4.2) and the
organiser's response (story 4.3), the approve/reject decision (stories 4.4, 4.5), the decision /
clarification history an organiser sees (story 4.6), routine information edits and corrections
to a request until it is confirmed (story 7.2, fix f7.2.4), the coordinator's assigned events in
any status (story 6.1), and the notifications a submission and a decision send (story 20.1).

Routers translate the exceptions raised here into HTTP statuses. A request belongs to the
organiser who created it: anyone else gets ``EventNotFound``, so a request's existence is not
revealed to people it is not theirs to see.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, lazyload

from app.auth.models import User
from app.auth.permissions import Permission, RoleCode, role_has
from app.bookings.models import BookingStatus, VenueBooking
from app.common.audit import record_audit
from app.config import settings
from app.events.models import (
    ClarificationKind,
    EquipmentHoldStatus,
    EquipmentRequestStatus,
    EquipmentReservation,
    EquipmentType,
    EquipmentUnavailabilityPeriod,
    Event,
    EventAccessibilityNeed,
    EventClarification,
    EventEquipmentRequest,
    EventStatus,
    EventStatusHistory,
    VenueRequirement,
    VenueRequirementFacility,
)
from app.events.schemas import (
    ACCESSIBILITY_CONTRADICTION_MESSAGE,
    REGISTRATION_CONTRADICTION_MESSAGE,
    EquipmentAvailabilityOut,
    EventAccessibilityNeedIn,
    EventCreate,
    EventEquipmentIn,
    EventReferenceData,
    EventReviewCorrection,
    EventRoutineUpdate,
    EventUpdate,
    PointOfContactUpdate,
    ReferenceItemOut,
    ReviewQueueSort,
    VenueRequirementIn,
)
from app.notifications.service import NotificationType, active_members, notify
from app.venues import service as venue_service
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
# Story 2.7: refusals that name the venue requirement at fault - by its name, or by its place in
# the list while it has none.
REQUIREMENT_END_NOT_AFTER_START_MESSAGE = "{requirement} must end after it starts."
REQUIREMENT_STARTS_BEFORE_EVENT_MESSAGE = "{requirement} cannot start before the event starts."
REQUIREMENT_ENDS_AFTER_EVENT_MESSAGE = "{requirement} cannot end after the event ends."
REQUIREMENT_OVER_ATTENDANCE_MESSAGE = (
    "{requirement} cannot need room for more people than the expected attendance."
)
# Story 19.2: the same rule, said of a change to the attendance rather than of the form's field.
ATTENDANCE_BELOW_REQUIREMENT_MESSAGE = (
    "{requirement} needs room for more people than the new expected attendance."
)
DUPLICATE_REQUIREMENT_NAME_MESSAGE = 'Two venue requirements cannot both be called "{name}".'
# AC9's database backstop knows only that the index refused a name, not which requirement held it.
DUPLICATE_REQUIREMENT_NAME_BACKSTOP_MESSAGE = (
    "Two venue requirements on this request cannot share a name."
)
UNKNOWN_REQUIREMENT_MESSAGE = "A venue requirement does not belong to this request."
# Fix f2.7.4 (story 2.7 AC14, AC20): no create, edit or 7.2 correction leaves a request without one.
NO_VENUE_REQUIREMENT_MESSAGE = "A request needs at least one venue requirement."
_UNNAMED_REQUIREMENT_LABEL = "Venue requirement {position}"
_REQUIREMENT_MISSING_NAME_LABEL = "venue requirement {position}: name"
_REQUIREMENT_MISSING_CAPACITY_LABEL = "venue requirement {position}: number of people"
ROUTINE_EDIT_CLOSED_MESSAGE = (
    "This event is {status}, so its routine information can no longer be edited."
)
DETAILS_LOCKED_MESSAGE = (
    "This event has been confirmed, so its details can no longer be edited directly. Further "
    "changes must go through a change request."
)
DETAILS_NOT_CORRECTABLE_MESSAGE = (
    "This event is {status}, so its details can only be edited before it is confirmed."
)
BOOKING_NO_LONGER_FITS_MESSAGE = (
    'This change no longer fits the booking of {venue} for "{requirement}". Keep the requirement '
    "within what was booked, or withdraw the booking first if it is still pending."
)
ADDITIONAL_VENUE_NO_LONGER_FITS_MESSAGE = (
    "This change no longer fits the booking of {venue} as an additional venue, which holds the "
    "event's own dates and attendance. Keep them within what was booked, or withdraw the booking "
    "first if it is still pending."
)
EQUIPMENT_CHANGED_AFTER_APPROVAL_MESSAGE = (
    "This event has been approved, so its equipment can no longer be changed here. While the "
    "event is in Planning, change it in the Equipment requirements section of the event page."
)
EQUIPMENT_HOLD_NOT_COVERING_MESSAGE = (
    "The new dates fall outside the period this equipment is held for: {items}. Keep the dates "
    "within the held period."
)
STALE_EVENT_EDIT_MESSAGE = (
    "This event has changed since you opened it. Reload it and make your changes again."
)
SUBMITTED_DETAILS_MISSING_MESSAGE = (
    "Add the following before saving this submitted request: {missing}."
)

# ``equipment_reservations.notes`` on a hold: why it was placed (2.1 AC11, 7.2 AC7).
_SUBMITTED_HOLD_NOTE = "Held when the request was submitted."
_CORRECTED_HOLD_NOTE = "Held again when the coordinator corrected the request."

# AC20: the partial unique index a duplicate name+dates violates (db/migrations/008_*.sql).
DUPLICATE_REQUEST_INDEX = "uq_events_organiser_name_dates"
DUPLICATE_REQUIREMENT_NAME_INDEX = "uq_venue_requirements_event_name"

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

# Story 7.2 AC4, AC10 (f7.2.4, Q32): the organiser's details may be corrected directly in every
# status before Confirmed. Clarification Requested was added to AC4 in the backlog's Change Log.
_DETAILS_CORRECTABLE_STATUSES = (
    EventStatus.UNDER_REVIEW,
    EventStatus.CLARIFICATION_REQUESTED,
    EventStatus.PLANNING,
    EventStatus.AWAITING_SAFETY_CHECK,
)
# Story 7.2 AC12: confirmed and still running - further changes go through a change request (19.1).
_DETAILS_LOCKED_STATUSES = (EventStatus.CONFIRMED,)
# Story 7.2 AC14/AC15: approved, so venue bookings and equipment decisions may exist that a
# correction has to keep fitting.
_ARRANGED_STATUSES = (EventStatus.PLANNING, EventStatus.AWAITING_SAFETY_CHECK)
# AC14: the bookings that hold a venue for a requirement (12.1 AC3).
_LIVE_BOOKING_STATUSES = (BookingStatus.PENDING, BookingStatus.APPROVED)
# AC15: the equipment items that hold stock for the event's period (15.1 AC2, 16.1).
_HELD_ITEM_STATUSES = (
    EquipmentRequestStatus.REQUESTED,
    EquipmentRequestStatus.PENDING,
    EquipmentRequestStatus.ACCEPTED,
)

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
# Fix f2.7.4 (story 2.7 AC15): "none" is no longer an answer for venues. The frontend's
# getMissingForSubmission repeats this word for word.
_VENUE_ANSWER_LABEL = "venue requirements (at least one)"
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
    """7.2 AC12: the event has been confirmed, so its details are read-only."""

    def __init__(self):
        super().__init__(DETAILS_LOCKED_MESSAGE)


class EventDetailsNotCorrectable(EventStateConflict):
    """7.2 AC10: details can be corrected only after submission and before confirmation."""

    def __init__(self, status: str):
        super().__init__(DETAILS_NOT_CORRECTABLE_MESSAGE.format(status=status))


class StaleEventEdit(EventStateConflict):
    """7.2 AC9: the event changed after the copy being saved was read."""

    def __init__(self):
        super().__init__(STALE_EVENT_EDIT_MESSAGE)


class InvalidEventRequest(ValueError):
    """What was sent cannot be recorded as it stands (a 422)."""


class BookingNoLongerFits(InvalidEventRequest):
    """7.2 AC14: the correction would leave a venue requirement, or for an additional venue
    (``requirement`` None) the event itself, outside what its pending or approved booking was
    requested for. A 422, not a 409: the copy on screen is not out of date, the change is what
    does not fit, so the coordinator fixes it rather than reloading."""

    def __init__(self, venue: str, requirement: str | None):
        super().__init__(
            ADDITIONAL_VENUE_NO_LONGER_FITS_MESSAGE.format(venue=venue)
            if requirement is None
            else BOOKING_NO_LONGER_FITS_MESSAGE.format(venue=venue, requirement=requirement)
        )


class EquipmentChangedAfterApproval(InvalidEventRequest):
    """7.2 AC15: an approved event's equipment is changed in its own section (15.1), where
    Technical Support's decisions are kept, never through a correction."""

    def __init__(self):
        super().__init__(EQUIPMENT_CHANGED_AFTER_APPROVAL_MESSAGE)


class EquipmentHoldNotCovering(InvalidEventRequest):
    """7.2 AC15: the correction moves the event outside the period an open item is held for."""

    def __init__(self, names: list[str]):
        super().__init__(EQUIPMENT_HOLD_NOT_COVERING_MESSAGE.format(items=", ".join(names)))


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
        self.names = names


class ContradictoryAccessibility(InvalidEventRequest):
    def __init__(self):
        super().__init__(ACCESSIBILITY_CONTRADICTION_MESSAGE)


class MissingVenueRequirement(InvalidEventRequest):
    """Fix f2.7.4 (story 2.7 AC14, AC16, AC20): a create, an edit or a 7.2 correction would leave
    the request with no venue requirement - one sent with none, the last one removed, or one saved
    before the fix with none, saved again without adding one."""

    def __init__(self):
        super().__init__(NO_VENUE_REQUIREMENT_MESSAGE)


class AttendanceBelowRequirement(InvalidEventRequest):
    """Story 19.2 AC2: a proposed attendance smaller than a venue requirement needs room for
    (2.7 AC6). A plain 422, not located on a requirement: the form changing is the attendance."""

    def __init__(self, requirement: str) -> None:
        super().__init__(ATTENDANCE_BELOW_REQUIREMENT_MESSAGE.format(requirement=requirement))


class InvalidVenueRequirement(InvalidEventRequest):
    """Story 2.7 AC11: a venue requirement that breaks a rule, and the field the form should mark
    - its place in the list and the field's name, as a FastAPI validation error locates it."""

    def __init__(self, message: str, *, index: int, field: str):
        super().__init__(message)
        self.index = index
        self.field = field

    @property
    def location(self) -> list[str | int]:
        return ["body", "venue_requirements", self.index, self.field]


class UnknownVenueRequirement(InvalidEventRequest):
    def __init__(self):
        super().__init__(UNKNOWN_REQUIREMENT_MESSAGE)


class DuplicateVenueRequirementName(InvalidEventRequest):
    """AC9's backstop: the database refused a second requirement with the same name. Review of
    PR #84: the index does not say which requirement it was, so the message names none - never
    the event, which is the only name to hand where this is raised."""

    def __init__(self):
        super().__init__(DUPLICATE_REQUIREMENT_NAME_BACKSTOP_MESSAGE)


class ContradictoryRegistration(InvalidEventRequest):
    def __init__(self):
        super().__init__(REGISTRATION_CONTRADICTION_MESSAGE)


class DuplicateEventRequest(InvalidEventRequest):
    """AC20: another of this organiser's own live requests already has this name and these
    dates."""

    def __init__(self, name: str):
        super().__init__(f'You already have a request named "{name}" for these dates.')
        self.name = name


class DuplicateCorrectedRequest(InvalidEventRequest):
    """Story 7.2 AC4: AC20 on a correction - it is the organiser, not the coordinator correcting the
    request, who already has one with this name and these dates."""

    def __init__(self, name: str):
        super().__init__(f'The organiser already has a request named "{name}" for these dates.')


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
# Fix f2.7.4 (story 2.7 AC17): a request submitted with no venue requirement, before the fix.
NO_VENUE_REQUIREMENT_TO_APPROVE_MESSAGE = (
    "This request has no venue requirement, so it cannot be approved."
)
DECISION_REASON_REQUIRED_MESSAGE = "A reason is required to reject this request."
EVENT_NOT_AWAITING_CLARIFICATION_MESSAGE = (
    "You can no longer ask for clarification on this request."
)
CLARIFICATION_MESSAGE_REQUIRED_MESSAGE = "A message is required."
EVENT_NOT_AWAITING_RESPONSE_MESSAGE = "This request is no longer awaiting your response."

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


def _get_own_event(
    db: Session, event_id: uuid.UUID, actor: User, *, for_update: bool = False
) -> Event:
    """``actor``'s own request. ``for_update`` holds the row until the transaction ends, so a
    save and a submission of the same request run one after the other (story 2.7 AC12): the
    second waits, then reads what the first committed."""
    # Only the request's own row is held, and in a statement of its own: the coordinator Event
    # joins in eagerly is read afterwards, so a handover that landed while this waited is seen
    # (``lock_event`` explains why one statement would miss it).
    if for_update:
        db.execute(select(Event.id).where(Event.id == event_id).with_for_update())
    event = db.get(Event, event_id, populate_existing=for_update)
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


def latest_end_allowed(now: datetime) -> datetime:
    """Story 9.4 AC5: the latest an event can end - it starts at most two years ahead
    (``latest_start_allowed``) and runs at most 14 days - so the latest a period a venue is
    unavailable for has any use being asked to end."""
    return latest_start_allowed(now) + _MAX_EVENT_DURATION


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


def _check_has_venue_requirement(
    requirements: Sequence[VenueRequirementIn | VenueRequirement],
) -> None:
    """Fix f2.7.4 (story 2.7 AC14, AC16, AC20): every request keeps at least one venue requirement,
    which a draft may still leave empty (AC8). ``requirements`` are the ones the save would leave.
    "No venue requirements" itself is refused by the request schemas."""
    if not requirements:
        raise MissingVenueRequirement()


def _describe_requirement(name: str | None, index: int) -> str:
    return name or _UNNAMED_REQUIREMENT_LABEL.format(position=index + 1)


def _check_venue_requirement_rules(
    requirements: Sequence[VenueRequirementIn | VenueRequirement],
    *,
    event_starts_at: datetime | None,
    event_ends_at: datetime | None,
    attendance: int | None,
) -> None:
    """Story 2.7: each requirement's times end after they start (AC5) and fall within the
    event's, inclusive (AC5, AC10); it needs room for no more than the expected attendance (AC6);
    and no two share a name, trimmed and case-insensitive (AC9). ``requirements`` and the event's
    values are the ones the request will end up with, so moving the event and its requirements in
    one save is judged on the result. A rule is skipped while a value it compares is still
    empty on a draft."""
    seen_names: dict[str, int] = {}
    for index, requirement in enumerate(requirements):
        label = _describe_requirement(requirement.name, index)
        starts_at, ends_at = requirement.starts_at, requirement.ends_at
        if starts_at is not None and ends_at is not None:
            if ends_at <= starts_at:
                raise InvalidVenueRequirement(
                    REQUIREMENT_END_NOT_AFTER_START_MESSAGE.format(requirement=label),
                    index=index,
                    field="ends_at",
                )
            if event_starts_at is not None and starts_at < event_starts_at:
                raise InvalidVenueRequirement(
                    REQUIREMENT_STARTS_BEFORE_EVENT_MESSAGE.format(requirement=label),
                    index=index,
                    field="starts_at",
                )
            if event_ends_at is not None and ends_at > event_ends_at:
                raise InvalidVenueRequirement(
                    REQUIREMENT_ENDS_AFTER_EVENT_MESSAGE.format(requirement=label),
                    index=index,
                    field="ends_at",
                )
        capacity = requirement.capacity
        if capacity is not None and attendance is not None and capacity > attendance:
            raise InvalidVenueRequirement(
                REQUIREMENT_OVER_ATTENDANCE_MESSAGE.format(requirement=label),
                index=index,
                field="capacity",
            )
        if requirement.name is not None:
            key = requirement.name.strip().lower()
            if key in seen_names:
                first = requirements[seen_names[key]]
                raise InvalidVenueRequirement(
                    DUPLICATE_REQUIREMENT_NAME_MESSAGE.format(name=first.name),
                    index=index,
                    field="name",
                )
            seen_names[key] = index


def _check_venue_requirement_references(
    db: Session, items: list[VenueRequirementIn], *, owned_ids: set[uuid.UUID]
) -> None:
    """2.7 AC1/AC3: every layout and facility exists, and an item may carry only the ``id`` of a
    requirement this request already has."""
    layouts = [item.layout_code for item in items if item.layout_code is not None]
    _known(db, RoomLayout, layouts, label="room layout")
    _known(db, Facility, [f.code for item in items for f in item.facilities], label="facility")
    if any(item.id is not None and item.id not in owned_ids for item in items):
        raise UnknownVenueRequirement()


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


def available_by_type(
    db: Session,
    period_start: datetime,
    period_end: datetime,
    *,
    exclude_event_id: uuid.UUID | None = None,
) -> dict[uuid.UUID, int]:
    """AC6: units free for a period, per equipment type: the stock, less units held for other
    events over the period (a hold's quantity less what was released), less units out of service.
    Overlap is half-open, so a hold ending exactly as the period starts does not count. Story 15.1
    (``app/equipment/service.py``) uses the same calculation for the coordinator's items.
    Story 7.2 AC7: ``exclude_event_id`` leaves that event's own holds out, so an event being
    corrected is not counted against itself. Story 15.2 AC2 uses it the same way: the holds are
    left out before the figure is floored at zero, so units lost after the event was held show as
    a shortfall against it."""
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
    available = available_by_type(db, starts_at, ends_at, exclude_event_id=exclude_event_id)
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
    available = available_by_type(db, starts_at, ends_at, exclude_event_id=exclude_event_id)
    short = [t.name for t, quantity in lines if quantity > available[t.id]]
    if short:
        raise EquipmentNotAvailable(short)


def _hold_equipment(db: Session, event: Event, actor: User, *, notes: str) -> None:
    """AC11: hold the request's equipment for its dates. The types are locked first, so two
    requests for the last units cannot both be held; the loser is refused and nothing is held.
    Story 15.1 AC1/AC2: the lines stay REQUESTED - held, but not yet sent to Technical Support,
    which is the assigned coordinator's step.
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
    available = available_by_type(db, event.starts_at, event.ends_at)
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


def _replace_venue_requirements(db: Session, event: Event, items: list[VenueRequirementIn]) -> None:
    """2.7 AC3: make the request's venue requirements match ``items``, in that order. One whose
    ``id`` is sent is kept and edited, so its id never changes (a booking may later point at it,
    stories 8.4/12.5); one left out is removed; one without an ``id`` is new.

    The unique name index (AC9) is checked row by row, so the removals and the names being
    changed are written first: otherwise two requirements swapping names, or a removed one's
    name reused, would clash with a row that is about to change. Positions clash the same way,
    which is why their constraint is checked only at commit.

    Fix f2.7.4 (story 2.7 AC17): a request given a venue requirement no longer holds a "No venue
    requirements" saved before the fix, so it is cleared here, wherever the list is written from -
    and a 7.2 correction's change history records it going."""
    if items:
        event.venue_none_required = False
    existing = {requirement.id: requirement for requirement in event.venue_requirements}
    kept_ids = {item.id for item in items if item.id is not None}
    for removed in [r for r in event.venue_requirements if r.id not in kept_ids]:
        event.venue_requirements.remove(removed)
    for item in items:
        if item.id is not None:
            existing[item.id].name = None
    if existing:
        db.flush()
    for position, item in enumerate(items):
        if item.id is not None:
            requirement = existing[item.id]
        else:
            requirement = VenueRequirement()
            event.venue_requirements.append(requirement)
        requirement.position = position
        requirement.name = item.name
        requirement.capacity = item.capacity
        requirement.starts_at = item.starts_at
        requirement.ends_at = item.ends_at
        requirement.layout_code = item.layout_code
        requirement.notes = item.notes
        requirement.facilities = [
            VenueRequirementFacility(facility_code=f.code, quantity=f.quantity, notes=f.notes)
            for f in item.facilities
        ]


def _fill_requirement_times(event: Event) -> None:
    """2.7 AC2 (PO decision, 2 Oct 2026): a requirement never given times of its own is needed for
    the whole event, so a submitted requirement always has a period a booking can copy - at
    submission, and when story 7.2's coordinator corrects a submitted request."""
    for requirement in event.venue_requirements:
        if requirement.starts_at is None:
            requirement.starts_at, requirement.ends_at = event.starts_at, event.ends_at


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
    """AC1-AC6: record a new request as a draft owned by ``actor``. Fix f2.7.4 (story 2.7 AC14,
    AC20): with at least one venue requirement - checked after every 2.1 check made before the
    insert, so those refusals come first (AC20's duplicate index still fires only at the insert)."""
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
    _check_venue_requirement_references(db, data.venue_requirements, owned_ids=set())
    _check_venue_requirement_rules(
        data.venue_requirements,
        event_starts_at=data.starts_at,
        event_ends_at=data.ends_at,
        attendance=data.expected_attendance,
    )
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
    _check_has_venue_requirement(data.venue_requirements)

    event = Event(
        organiser_id=actor.id,
        organisation_id=actor.organisation_id,
        status=EventStatus.DRAFT,
        **{field: getattr(data, field) for field in _DETAIL_FIELDS},
    )
    _replace_venue_requirements(db, event, data.venue_requirements)
    _replace_accessibility_needs(event, data.accessibility_needs)
    _replace_equipment(event, data.equipment, types, actor=actor)
    db.add(event)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if DUPLICATE_REQUEST_INDEX in str(exc.orig):
            raise DuplicateEventRequest(data.name) from exc
        if DUPLICATE_REQUIREMENT_NAME_INDEX in str(exc.orig):
            raise DuplicateVenueRequirementName() from exc
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
    """A request edit that has passed every 2.1 check: the columns to set, the equipment types its
    equipment lines name, and whether it changes what the event's equipment holds cover (story
    7.2 AC7)."""

    details: dict[str, Any]
    equipment_types: dict[str, EquipmentType]
    is_hold_changed: bool


def _is_hold_changed(
    event: Event,
    starts_at: datetime | None,
    ends_at: datetime | None,
    items: list[EventEquipmentIn] | None,
    types: dict[str, EquipmentType],
) -> bool:
    """Story 7.2 AC7: whether an edit moves the dates or changes a line's type or quantity - the
    only edits the event's existing holds can be short for. A hold belongs to one line, so lines
    are compared by ``id`` too: a line removed and an identical one added still needs holding.
    Technical notes are left out, since no hold depends on them. Counted rather than sorted,
    because every new line's ``id`` is None."""
    if starts_at != event.starts_at or ends_at != event.ends_at:
        return True
    if items is None:
        return False
    stored = Counter(
        (line.id, line.equipment_type_id, line.quantity) for line in event.equipment_requests
    )
    edited = Counter((item.id, types[item.equipment_type_code].id, item.quantity) for item in items)
    return edited != stored


def _validate_request_edit(
    db: Session,
    event: Event,
    data: EventUpdate,
    *,
    recheck_resent_equipment: bool,
    is_stock_checked: bool,
) -> _RequestEdit:
    """AC2-AC7/AC17/AC18: every 2.1 check on an edit to ``event``, and story 2.7's venue
    requirement checks, before anything is changed, so a refused edit leaves the request as it
    was. Shared by the organiser's draft edit (AC7) and the coordinator's correction under review
    (story 7.2 AC4), so the two can never drift apart.
    Equipment availability leaves ``event``'s own holds out (story 7.2 AC7); a draft has none.
    ``recheck_resent_equipment`` is True for a draft, whose equipment is checked on every save that
    sends it. A submitted request already holds its stock, so a correction that resends the same
    dates and equipment is not judged against stock it holds (story 7.2 AC7).
    ``is_stock_checked`` is False for a correction after approval (story 7.2 AC15): the equipment
    cannot change there, and its existing holds must already cover the new dates, so there is no
    new stock to find."""
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
    requirements = (
        data.venue_requirements if data.venue_requirements is not None else event.venue_requirements
    )
    if data.venue_requirements is not None:
        _check_venue_requirement_references(
            db,
            data.venue_requirements,
            owned_ids={requirement.id for requirement in event.venue_requirements},
        )
    # 2.7 AC5/AC6/AC10: re-judged whenever the event's period or attendance moves, as well as
    # when the requirements themselves are sent, against the values this save would leave.
    if sent & {"starts_at", "ends_at", "expected_attendance", "venue_requirements"}:
        _check_venue_requirement_rules(
            requirements,
            event_starts_at=starts_at,
            event_ends_at=ends_at,
            attendance=details.get("expected_attendance", event.expected_attendance),
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

    is_hold_changed = False
    if sent & {"equipment", "starts_at", "ends_at"}:
        lines = (
            [(types[e.equipment_type_code], e.quantity) for e in data.equipment]
            if data.equipment is not None
            else [(line.equipment_type, line.quantity) for line in event.equipment_requests]
        )
        is_hold_changed = _is_hold_changed(event, starts_at, ends_at, data.equipment, types)
        if is_stock_checked and (recheck_resent_equipment or is_hold_changed):
            _check_equipment_available(db, starts_at, ends_at, lines, exclude_event_id=event.id)
    # Fix f2.7.4 (story 2.7 AC14, AC16, AC20): after the other checks, as on a create, so their
    # refusals come first. A request saved before the fix with none is saved again only once it
    # has one.
    _check_has_venue_requirement(requirements)
    return _RequestEdit(details=details, equipment_types=types, is_hold_changed=is_hold_changed)


def _apply_request_edit(
    db: Session, event: Event, data: EventUpdate, edit: _RequestEdit, *, actor: User
) -> None:
    """AC7: set what ``edit`` validated. Only the fields sent change; a list sent replaces that
    list. The venue requirements go first (story 2.7 AC3): replacing them flushes, and at that
    point nothing on the request's own row has changed yet, so a value the caller has still to
    judge (story 7.2's correction) is never written before it is checked."""
    if data.venue_requirements is not None:
        _replace_venue_requirements(db, event, data.venue_requirements)
    for field, value in edit.details.items():
        setattr(event, field, value)
    if data.accessibility_needs is not None:
        _replace_accessibility_needs(event, data.accessibility_needs)
    if data.equipment is not None:
        _replace_equipment(event, data.equipment, edit.equipment_types, actor=actor)
    # A change to a list alone would not touch the events row; stamping it makes updated_at the
    # request's last-modified time whatever was edited (the trigger sets the real value).
    event.updated_at = datetime.now(UTC)


def _flush_request_edit(db: Session, event: Event) -> None:
    """Write an applied edit, translating AC20's duplicate-request index into
    ``DuplicateEventRequest`` and story 2.7 AC9's requirement-name index into
    ``DuplicateVenueRequirementName``."""
    # Read before the flush: a rollback below expires this object, so event.name read afterwards
    # would re-fetch the pre-update value instead of the one the failed write attempted.
    attempted_name = event.name
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if DUPLICATE_REQUEST_INDEX in str(exc.orig):
            raise DuplicateEventRequest(attempted_name) from exc
        if DUPLICATE_REQUIREMENT_NAME_INDEX in str(exc.orig):
            raise DuplicateVenueRequirementName() from exc
        raise


def update_event(db: Session, event_id: uuid.UUID, data: EventUpdate, *, actor: User) -> Event:
    """AC7: edit or remove any recorded detail, requirement or equipment item while a draft.
    Only the fields sent change; a list sent replaces that list. Story 2.7 AC12: the row is held
    from the moment it is read, so a submission in another tab either finishes first (and this
    save is refused) or waits for this save to finish."""
    event = _get_own_event(db, event_id, actor, for_update=True)
    if event.status != EventStatus.DRAFT:
        raise EventNotEditable()

    edit = _validate_request_edit(
        db, event, data, recheck_resent_equipment=True, is_stock_checked=True
    )
    _apply_request_edit(db, event, data, edit, actor=actor)
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
    """AC10/AC13/AC17: every event detail and the point of contact must be filled in, at least one
    venue requirement given, accessibility needs answered - something chosen or written, or marked
    "none required" - and, only when Registration required is Yes, a registration closing date.
    Registration capacity needs no check of its own: it is always expected attendance, already
    covered by the event-detail check above."""
    missing = [
        label for field, label in _REQUIRED_DETAILS_FOR_SUBMISSION if getattr(event, field) is None
    ]
    if event.registration_required and event.registration_closes_at is None:
        missing.append("registration closing date")
    # 2.7 AC8/AC15 (fix f2.7.4): at least one requirement - "No venue requirements" is no longer
    # an answer - and every requirement has a name and a number of people, each pointed out by
    # its place in the list.
    if not event.venue_requirements:
        missing.append(_VENUE_ANSWER_LABEL)
    for index, requirement in enumerate(event.venue_requirements):
        if requirement.name is None:
            missing.append(_REQUIREMENT_MISSING_NAME_LABEL.format(position=index + 1))
        if requirement.capacity is None:
            missing.append(_REQUIREMENT_MISSING_CAPACITY_LABEL.format(position=index + 1))
    has_accessibility_answer = (
        event.accessibility_none_required
        or bool(event.accessibility_needs)
        or event.accessibility_notes is not None
    )
    if not has_accessibility_answer:
        missing.append(_ACCESSIBILITY_ANSWER_LABEL)
    return missing


def record_transition(
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


# Story 9.4 AC3, story 19.2 AC8: the statuses an event is sent back to Planning from.
_RETURNED_TO_PLANNING_FROM = (EventStatus.CONFIRMED, EventStatus.AWAITING_SAFETY_CHECK)


def return_event_to_planning(
    db: Session,
    event: Event,
    *,
    actor: User,
    at: datetime,
    reason: str,
    details: dict[str, Any],
) -> bool:
    """A Confirmed event, or one Awaiting Safety Check (story 21.1), goes back to Planning: story
    9.4 AC3, because a venue it has booked was marked unavailable, and story 19.2 AC8, because a
    change to it was approved. Its confirmation is cleared, recorded in the status history with
    ``reason``, and in the audit log as EVENT_RETURNED_TO_PLANNING with ``details`` beside where it
    came from. Any other status is left as it is (Planning is already where it should be), and
    False says nothing changed. The caller holds the event's row lock, commits and tells whoever
    should know, so this leaves no notice of its own."""
    if event.status not in _RETURNED_TO_PLANNING_FROM:
        return False
    from_status = event.status
    event.status = EventStatus.PLANNING
    event.confirmed_at = None
    db.flush()
    record_transition(
        db,
        event,
        from_status=from_status,
        to_status=EventStatus.PLANNING,
        actor=actor,
        at=at,
        reason=reason,
    )
    record_audit(
        db,
        actor=actor,
        action="EVENT_RETURNED_TO_PLANNING",
        entity_type="event",
        entity_id=event.id,
        details={"from_status": from_status, **details},
        commit=False,
    )
    return True


def _notify_leads_of_submission(db: Session, event: Event, *, actor: User) -> None:
    """Story 20.1 AC1, since story 5.4: a submitted request waits unassigned (5.4 AC9), so every
    active Event Coordinator Lead - who assigns it - is told it is waiting. A role is told through
    its active members only (20.1 AC5). The organiser submitted it, so they are not (AC3)."""
    for lead in active_members(db, role_code=RoleCode.EVENT_COORDINATOR_LEAD):
        notify(
            db,
            recipient=lead,
            actor=actor,
            notification_type=NotificationType.EVENT_SUBMITTED,
            event_id=event.id,
            title=f'"{event.name}" is waiting for a coordinator',
            message=(
                f'{actor.full_name} submitted "{event.name}". Assign it from the unassigned queue.'
            ),
            related_entity_type="event",
            related_entity_id=event.id,
            commit=False,
        )


def submit_event(db: Session, event_id: uuid.UUID, *, actor: User) -> Event:
    """AC9-AC12: submit ``actor``'s own draft once its four mandatory details are filled in.
    Story 5.4 AC9: no coordinator is assigned here - the request waits in the Event Coordinator
    Lead's unassigned queue. Story 20.1 AC1/AC4: the active Leads are notified, in the same
    transaction.
    Story 2.7 AC12: the row is held from the moment it is read, so what is judged here is what
    an edit in another tab left, never what was there before it committed."""
    event = _get_own_event(db, event_id, actor, for_update=True)
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

    _fill_requirement_times(event)
    _hold_equipment(db, event, actor, notes=_SUBMITTED_HOLD_NOTE)
    submitted_at = datetime.now(UTC)
    # Conditional on still being a draft, so two submissions racing cannot both succeed.
    # A submitted draft moves to UNDER_REVIEW; there is no status in between.
    submitted = db.execute(
        update(Event)
        .where(Event.id == event.id, Event.status == EventStatus.DRAFT)
        .values(status=EventStatus.UNDER_REVIEW, submitted_at=submitted_at)
    )
    if submitted.rowcount == 0:
        db.rollback()
        raise EventAlreadySubmitted()
    record_transition(
        db,
        event,
        from_status=EventStatus.DRAFT,
        to_status=EventStatus.UNDER_REVIEW,
        actor=actor,
        at=submitted_at,
        reason=None,
    )
    _notify_leads_of_submission(db, event, actor=actor)
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


class NoVenueRequirementToApprove(EventStateConflict):
    """Fix f2.7.4 (story 2.7 AC17): a request submitted with no venue requirement, before the fix,
    waits for its coordinator to add one through a correction (7.2 AC4) before it can be
    approved. The body of the approval is fine; the request's state is what refuses it, as with
    ``EventNotAwaitingDecision``."""

    def __init__(self) -> None:
        super().__init__(NO_VENUE_REQUIREMENT_TO_APPROVE_MESSAGE)


class MissingDecisionReason(InvalidEventRequest):
    """4.5 AC1: a reason is mandatory to reject. ``EventRejection`` already refuses a blank body
    with a 422 before ``reject_event`` runs; this is the guard for any other caller (4.6's
    clarification flow, a seed script, a test factory). Story 6.2's cancellation has its own."""

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


class EventNotAwaitingResponse(EventStateConflict):
    """4.3 AC10/AC11: the organiser may respond only while the request is CLARIFICATION_REQUESTED.
    Covers both the ordinary case and the race where the request is cancelled, approved or
    rejected between opening the page and pressing Send."""

    def __init__(self, event: Event) -> None:
        super().__init__(EVENT_NOT_AWAITING_RESPONSE_MESSAGE)
        self.event = event


class MissingClarificationMessage(InvalidEventRequest):
    """4.2 AC3 / 4.3 AC4: a message is mandatory. ``ClarificationRequest`` already refuses a blank
    body with a 422 before ``request_clarification`` or ``respond_to_clarification`` runs; this is
    the guard for any other caller, mirroring ``MissingDecisionReason``."""

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


def _notify_organiser_of_decision(
    db: Session, event: Event, *, actor: User, to_status: str, reason: str | None
) -> None:
    """Story 20.1 AC1: the organiser is told the outcome of the two decisions ``_decide`` makes,
    4.5's rejection with its reason, or 4.4's approval."""
    if to_status == EventStatus.REJECTED:
        notification_type = NotificationType.EVENT_REJECTED
        title = f'"{event.name}" was rejected'
        message = f"{actor.full_name} rejected your request. Reason: {reason}"
    else:
        notification_type = NotificationType.EVENT_APPROVED
        title = f'"{event.name}" was approved'
        message = f"{actor.full_name} approved your request. It is now being planned."
    notify(
        db,
        recipient=event.organiser,
        actor=actor,
        notification_type=notification_type,
        event_id=event.id,
        title=title,
        message=message,
        related_entity_type="event",
        related_entity_id=event.id,
        commit=False,
    )


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
    extra_check: Callable[[Event], None] | None = None,
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
    Story 20.1: the organiser's notification is written in the same transaction, so a decision
    that is refused or fails sends none (AC4), and the losing one of two at once sends none (AC6).
    ``extra_check`` is one decision's own refusal (approval's, fix f2.7.4 story 2.7 AC17), raised
    after the coordinator and status refusals and before anything is written, so those two always
    come first and approve and reject give them alike.
    """
    _assert_assigned_coordinator(event, actor, verb="decide")
    _assert_awaiting_decision(event, allowed_statuses, verb=verb)
    if extra_check is not None:
        extra_check(event)

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
    record_transition(
        db,
        event,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        at=decided_at,
        reason=reason,
    )
    _notify_organiser_of_decision(db, event, actor=actor, to_status=to_status, reason=reason)
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


def _refuse_approval_without_venue_requirement(event: Event) -> None:
    """Fix f2.7.4 (story 2.7 AC17): a request with no venue requirement - only one submitted before
    the fix can have none - is not approved until its coordinator adds one. Nothing can take a
    submitted request's last requirement away (AC20), so no approval can race into one without."""
    if not event.venue_requirements:
        raise NoVenueRequirementToApprove()


def approve_event(db: Session, event: Event, *, actor: User) -> None:
    """4.4 AC1-AC3: approve ``event``, recording the deciding coordinator and time. Moves it to
    PLANNING; there is no status in between.

    Fix f2.7.4 (story 2.7 AC17): a request with no venue requirement is refused. ``_decide`` runs
    that check after its coordinator and status refusals, so a request that is not this
    coordinator's, or no longer awaiting a decision, is told that. Rejecting needs no venue
    requirement."""
    _decide(
        db,
        event,
        actor=actor,
        to_status=EventStatus.PLANNING,
        reason=None,
        action="EVENT_APPROVED",
        allowed_statuses=_AWAITING_DECISION_STATUSES,
        verb="approved",
        extra_check=_refuse_approval_without_venue_requirement,
    )


def reject_event(db: Session, event: Event, *, actor: User, reason: str) -> None:
    """4.5 AC1-AC3: reject ``event`` with ``reason``, recording the deciding coordinator and
    time. Rejecting is allowed from the same statuses as approving: a request sent back for
    clarification may be rejected outright, the same as approving it."""
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
    round (AC4) - the event moves to, or stays at, CLARIFICATION_REQUESTED. Nothing moves it back
    to Under Review - the organiser's response (story 4.3) leaves the status alone - so a second
    round has to work directly from CLARIFICATION_REQUESTED. The new
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
        record_transition(
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
        actor=actor,
        notification_type=NotificationType.EVENT_CLARIFICATION_REQUESTED,
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


# --- respond to a clarification request (story 4.3) -------------------------------------------


def respond_to_clarification(
    db: Session, event_id: uuid.UUID, *, actor: User, message: str
) -> EventClarification:
    """4.3 AC1-AC3/AC6-AC11: the organiser who owns the event answers while it is
    CLARIFICATION_REQUESTED. Anyone else gets ``EventNotFound`` (AC10). The status does not
    change, so the organiser may answer more than once (AC6) and the coordinator may still ask
    again or decide (AC9); no status-history row is written. The response, the currently assigned
    coordinator's notification (AC7) and the audit entry are one transaction (AC8). The UPDATE
    repeats the status and owner check in its WHERE clause, so a cancellation or decision landing
    after the event was loaded is refused too (AC11); the status check above it only refuses the
    ordinary case without a write."""
    stripped = message.strip()
    if not stripped:
        raise MissingClarificationMessage()
    event = _get_own_event(db, event_id, actor)
    if event.status != EventStatus.CLARIFICATION_REQUESTED:
        raise EventNotAwaitingResponse(event)

    # Re-writing the status the row already holds is the check: a SELECT would race the very
    # cancellation or decision this guards against.
    still_awaiting = db.execute(
        update(Event)
        .where(
            Event.id == event.id,
            Event.status == EventStatus.CLARIFICATION_REQUESTED,
            Event.organiser_id == actor.id,
        )
        .values(status=EventStatus.CLARIFICATION_REQUESTED)
    )
    if still_awaiting.rowcount == 0:
        db.rollback()
        db.refresh(event)
        raise EventNotAwaitingResponse(event)

    entry = EventClarification(
        event_id=event.id, author_id=actor.id, kind=ClarificationKind.RESPONSE, message=stripped
    )
    db.add(entry)
    notify(
        db,
        recipient=event.assigned_coordinator,
        actor=actor,
        notification_type=NotificationType.EVENT_CLARIFICATION_RESPONDED,
        event_id=event.id,
        title=f'Organiser responded on "{event.name}"',
        message=stripped,
        related_entity_type="event",
        related_entity_id=event.id,
        commit=False,
    )
    record_audit(
        db,
        actor=actor,
        action="EVENT_CLARIFICATION_RESPONDED",
        entity_type="event",
        entity_id=event.id,
        details={"message": stripped},
        commit=False,
    )
    db.commit()
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


# --- correcting details until the event is confirmed (story 7.2 AC4-AC18) ---------------------


def _refuse_unless_correctable(event: Event) -> None:
    """AC10/AC12: only an event that has been submitted and is not yet confirmed takes
    corrections; a confirmed one is locked."""
    if event.status in _DETAILS_LOCKED_STATUSES:
        raise EventDetailsLocked()
    if event.status not in _DETAILS_CORRECTABLE_STATUSES:
        raise EventDetailsNotCorrectable(event.status)


def _claim_for_correction(db: Session, event: Event, *, expected_updated_at: datetime) -> None:
    """AC6/AC9: take the event row for this correction, provided it is still correctable and
    still exactly the copy the coordinator read. The update is conditional, the same shape as
    ``_decide``'s guard: an approval or any other change that landed first makes it match no row,
    and the correction is refused. Once taken, the row stays locked until this transaction ends,
    so an approval arriving meanwhile waits and then approves the corrected event."""
    claimed = db.execute(
        update(Event)
        .where(
            Event.id == event.id,
            Event.status.in_(_DETAILS_CORRECTABLE_STATUSES),
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
    a correction. Lists are sorted by code, so a reordering alone is not a change - except the
    venue requirements, kept in their order (story 2.7 AC3), which is theirs to change."""
    values = {field: _audit_value(getattr(event, field)) for field in _DETAIL_FIELDS}
    values["venue_requirements"] = [
        {
            "name": requirement.name,
            "capacity": requirement.capacity,
            "starts_at": _audit_value(requirement.starts_at),
            "ends_at": _audit_value(requirement.ends_at),
            "layout_code": requirement.layout_code,
            "facilities": [
                {"code": f.facility_code, "quantity": f.quantity, "notes": f.notes}
                for f in sorted(requirement.facilities, key=lambda f: f.facility_code)
            ],
            "notes": requirement.notes,
        }
        # Sorted, not read in list order: a requirement added in memory is appended to the list
        # whatever its position until the event is loaded again.
        for requirement in sorted(event.venue_requirements, key=lambda r: r.position)
    ]
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


def _check_equipment_unchanged(event: Event, data: EventReviewCorrection) -> None:
    """AC15: an approved event's equipment, if sent at all, must come back exactly as it is. The
    form leaves it out once the event is approved; an API call that sends it unchanged is not an
    edit, and one that sends an empty list would remove every line, so it is refused."""
    if data.equipment is None:
        return
    stored = Counter(
        (line.id, line.equipment_type.code, line.quantity, line.technical_notes)
        for line in event.equipment_requests
    )
    sent = Counter(
        (item.id, item.equipment_type_code, item.quantity, item.technical_notes)
        for item in data.equipment
    )
    if sent != stored:
        raise EquipmentChangedAfterApproval()


def _check_equipment_holds_cover(db: Session, event: Event, data: EventReviewCorrection) -> None:
    """AC15: every open item that holds stock for the event must still be held for the whole of
    the event's new period. A move inside the held period keeps every hold and decision as it is;
    a move outside it is refused, naming the items. An open item with no hold (a seeded one that
    predates holds) has no period to keep inside, so it bounds nothing. A cleared date is left to
    ``_missing_for_submission``, which refuses it as it would before approval."""
    sent = data.model_fields_set
    starts_at = data.starts_at if "starts_at" in sent else event.starts_at
    ends_at = data.ends_at if "ends_at" in sent else event.ends_at
    if starts_at is None or ends_at is None:
        return
    if (starts_at, ends_at) == (event.starts_at, event.ends_at):
        return
    holds = db.scalars(
        select(EquipmentReservation).where(
            EquipmentReservation.event_id == event.id,
            EquipmentReservation.status == EquipmentHoldStatus.RESERVED,
        )
    ).all()
    held = {hold.equipment_request_id: hold for hold in holds}
    uncovered = [
        item.equipment_type.name
        for item in event.equipment_requests
        if item.status in _HELD_ITEM_STATUSES
        and item.id in held
        and (held[item.id].starts_at > starts_at or held[item.id].ends_at < ends_at)
    ]
    if uncovered:
        raise EquipmentHoldNotCovering(uncovered)


@dataclass(frozen=True)
class _LiveBooking:
    """AC14: a pending or approved booking of the event, read before the correction changes
    anything, so a requirement the correction removes is still known by its name.
    ``requirement_name`` is None for an additional venue (12.5), booked for no requirement."""

    booking: VenueBooking
    venue_name: str
    requirement_name: str | None


def _live_bookings(db: Session, event: Event) -> list[_LiveBooking]:
    """AC14/AC18: ``event``'s pending and approved bookings, as they stand now."""
    bookings = db.scalars(
        select(VenueBooking)
        .where(
            VenueBooking.event_id == event.id,
            VenueBooking.status.in_(_LIVE_BOOKING_STATUSES),
        )
        .order_by(VenueBooking.created_at, VenueBooking.id)
    ).all()
    return [
        _LiveBooking(
            booking=booking,
            venue_name=booking.venue.name,
            requirement_name=None
            if booking.venue_requirement is None
            else booking.venue_requirement.name or "",
        )
        for booking in bookings
    ]


def _fits_booking(
    event: Event, requirement: VenueRequirement | None, booking: VenueBooking
) -> bool:
    """AC13/AC14: the requirement still asks for no more than its booking was requested for: it
    still exists, its times fall inside the booked ones, it needs room for no more people, and it
    asks for the same layout. Exactly the booked values still fit (AC13). The people are counted
    as the booking counted them (``people_to_hold``): a requirement with no number of its own
    was booked for the event's attendance."""
    if requirement is None:
        return False
    if requirement.starts_at < booking.starts_at or requirement.ends_at > booking.ends_at:
        return False
    if venue_service.people_to_hold(event, requirement) > booking.expected_attendance:
        return False
    return requirement.layout_code == booking.required_layout_code


def _fits_additional_venue(event: Event, booking: VenueBooking) -> bool:
    """AC14: an additional venue (12.5) was booked for the event's own period and attendance, so
    those have to stay inside what it was booked for."""
    return (
        booking.starts_at <= event.starts_at
        and event.ends_at <= booking.ends_at
        and event.expected_attendance <= booking.expected_attendance
    )


def _unfitting_bookings(event: Event, booked: list[_LiveBooking]) -> list[_LiveBooking]:
    """AC14, story 19.2 AC5: the bookings in ``booked`` that the event and its requirements, as
    they now stand, no longer fit - a requirement removed, grown, retimed or relaid, or the event's
    own period or attendance outgrowing an additional venue. ``booked`` is read before the change,
    so a requirement removed meanwhile is still known by its name. A cleared date or attendance
    judges nothing: it is refused elsewhere first."""
    if event.starts_at is None or event.ends_at is None or event.expected_attendance is None:
        return []
    requirements = {requirement.id: requirement for requirement in event.venue_requirements}
    unfitting = []
    for item in booked:
        if item.requirement_name is None:
            if not _fits_additional_venue(event, item.booking):
                unfitting.append(item)
            continue
        requirement = requirements.get(item.booking.venue_requirement_id)
        if not _fits_booking(event, requirement, item.booking):
            unfitting.append(item)
    return unfitting


def _check_bookings_still_fit(event: Event, booked: list[_LiveBooking]) -> None:
    """AC14: judged on the event and its requirements as the correction leaves them, before the
    event itself is written. Requirements the correction removed have already been flushed, so
    AC16 rests on ``correct_event_under_review`` rolling the whole correction back when the first
    booking that no longer fits refuses it. A cleared date or attendance is left to
    ``_missing_for_submission``, which refuses it as it would before approval."""
    requirements = {requirement.id: requirement for requirement in event.venue_requirements}
    for item in _unfitting_bookings(event, booked):
        if item.requirement_name is None:
            raise BookingNoLongerFits(item.venue_name, None)
        requirement = requirements.get(item.booking.venue_requirement_id)
        name = item.requirement_name if requirement is None else requirement.name
        raise BookingNoLongerFits(item.venue_name, name or item.requirement_name)


def _apply_correction(
    db: Session, event: Event, data: EventReviewCorrection, *, actor: User
) -> dict[str, dict[str, Any]]:
    """AC4/AC7: validate and apply ``data`` with the 2.1 checks, write it, and hold the equipment
    again when the dates or the equipment changed. Returns each changed field as
    ``{"from": ..., "to": ...}``; an empty result means nothing changed and nothing was written.
    A correction that changes something must leave the request with everything 2.1 AC10 requires
    for submission - including a detail that was already missing (a seeded request predating the
    point of contact), so a field marked required on the form always is.
    After approval (AC14/AC15) the equipment cannot change here, the dates must stay inside its
    holds, and every booked requirement must still fit its booking; its holds are never touched.
    """
    is_arranged = event.status in _ARRANGED_STATUSES
    booked: list[_LiveBooking] = []
    if is_arranged:
        _check_equipment_unchanged(event, data)
        _check_equipment_holds_cover(db, event, data)
        booked = _live_bookings(db, event)
    before = _request_values(event)
    edit = _validate_request_edit(
        db, event, data, recheck_resent_equipment=False, is_stock_checked=not is_arranged
    )
    _apply_request_edit(db, event, data, edit, actor=actor)
    _fill_requirement_times(event)
    _check_bookings_still_fit(event, booked)
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
    try:
        _flush_request_edit(db, event)
    except DuplicateEventRequest as exc:
        raise DuplicateCorrectedRequest(exc.name) from exc
    if edit.is_hold_changed and not is_arranged:
        try:
            _replace_equipment_holds(db, event, actor=actor)
        except EquipmentNoLongerAvailable as exc:
            # Stock taken by another request after the 2.1 check: the copy on screen is not out of
            # date, the equipment is, so it is refused as 2.1's check would have refused it.
            raise EquipmentNotAvailable(exc.names) from exc
    return changes


def correct_event_under_review(
    db: Session, event: Event, data: EventReviewCorrection, *, actor: User
) -> None:
    """AC4-AC9, AC10-AC18 (f7.2.4): the coordinator assigned to ``event`` corrects the organiser's
    request at any point before it is confirmed, without the organiser's approval and without
    changing its status. After approval the correction must still fit the event's bookings and
    equipment holds (``_apply_correction``).

    The status gate comes first, as with the internal-notes edit (AC3), so a locked or closed
    event refuses with 409 whoever asks; then only the assigned coordinator may go on (AC8).
    ``_claim_for_correction`` is the real guard for AC9/AC12 - the status check above it only picks
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
    """AC4/AC10: the coordinator assigned to ``event`` replaces its cover picture at any point
    before it is confirmed, under the same checks as the organiser's (2.1 AC14).
    Refused once confirmed or closed (AC12) or when the copy being saved is stale (AC9), exactly
    as a JSON correction is; the picture is checked before the row is taken, so a refused file
    changes nothing. Recorded as a correction, with the old and new address, for story 7.4."""
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
    """AC4/AC10: the coordinator assigned to ``event`` takes its cover picture off at any point
    before it is confirmed, under the same rules as ``set_cover_image_under_review``.
    Nothing to take off is a no-op: no write, no audit entry."""
    _refuse_unless_correctable(event)
    _assert_assigned_coordinator(event, actor, verb="edit")
    _claim_for_correction(db, event, expected_updated_at=expected_updated_at)
    if event.cover_image_url is None:
        db.rollback()  # gives back the claim, which only stamped updated_at
        return
    _clear_cover_image(db, event, actor=actor, action="EVENT_DETAILS_CORRECTED")


# --- stories 19.1/19.2: what a change request may propose, and the point of contact ----------
# Change requests themselves live in app/change_requests/. These are the event's own rules it
# reuses, made public here so that package never reaches into this module's private helpers.

REQUIREMENT_NAME_REQUIRED_MESSAGE = "{requirement} needs a name."
REQUIREMENT_CAPACITY_REQUIRED_MESSAGE = "{requirement} needs a number of people."
# Fix f2.7.4 (story 2.7 AC18): a change proposing no venue requirements at all.
CHANGE_LEAVES_NO_VENUE_REQUIREMENT_MESSAGE = (
    "A change cannot leave this event without a venue requirement."
)
CONTACT_EDIT_CLOSED_MESSAGE = (
    "This event is {status}, so its point of contact cannot be updated directly."
)

# Story 19.1 AC2 (PO decision, Checkpoint 1): approved and not yet over. Before approval the
# organiser's request is edited as a draft or corrected through clarification instead.
_CONTACT_EDITABLE_STATUSES = (EventStatus.PLANNING, EventStatus.CONFIRMED)
_CONTACT_FIELDS = ("contact_email", "contact_phone")


class ChangeLeavesNoVenueRequirement(InvalidEventRequest):
    """Fix f2.7.4 (story 2.7 AC18, AC20): a change to the venue requirements proposes the event's
    whole list (19.1), so proposing none would remove the last one."""

    def __init__(self) -> None:
        super().__init__(CHANGE_LEAVES_NO_VENUE_REQUIREMENT_MESSAGE)


class PointOfContactClosed(EventStateConflict):
    """19.1 AC2: the point of contact is updated directly only once approved and until over."""

    def __init__(self, status: str):
        super().__init__(CONTACT_EDIT_CLOSED_MESSAGE.format(status=status))


def get_own_event_for_update(db: Session, event_id: uuid.UUID, *, actor: User) -> Event:
    """``actor``'s own event, its row held until the transaction ends, so a status change racing
    a story 19.1 write waits for it (AC8) - the lock story 2.7 AC12 already relies on."""
    return _get_own_event(db, event_id, actor, for_update=True)


def lock_event(db: Session, event_id: uuid.UUID) -> Event | None:
    """Story 6.2: the event, its row held until the transaction ends and read as it now stands, or
    None if there is none. A cancellation and the planning writes it races take the event this
    way, so each waits for the other. ``FOR NO KEY UPDATE``, not ``FOR UPDATE``: a Venue Staff
    approval holds its booking and then writes a notice that names the event, which only
    ``FOR UPDATE`` would make wait - while the cancellation waited on that booking: a deadlock
    (story 9.4's re-check takes the event the same way, for the same reason).

    The lock is taken in one statement and the event read in the next. A locking read that waits
    re-checks only the row it locks, so the coordinator ``Event`` joins in would come back as the
    statement first found it - none, under an assignment that landed while it waited. The second
    statement sees everything that landed."""
    db.execute(select(Event.id).where(Event.id == event_id).with_for_update(key_share=True))
    return db.get(Event, event_id, populate_existing=True)


def lock_own_event(db: Session, event_id: uuid.UUID, *, actor: User) -> Event:
    """Story 6.2: ``actor``'s own event, held and read as ``lock_event`` does, so a cancellation
    waits for any other write to the event already under way, and they for it."""
    event = lock_event(db, event_id)
    if event is None or event.organiser_id != actor.id:
        raise EventNotFound(event_id)
    return event


def get_event_for_update(db: Session, event_id: uuid.UUID, *, viewer: User) -> Event:
    """Story 19.2: the event as ``get_event`` shows it to ``viewer``, its row held until the
    transaction ends, so a decision on one of its change requests waits for a withdrawal or a
    reassignment already under way (and they for it), then reads what landed first. Only the
    event's own row is held, as in ``_get_own_event``."""
    event = db.get(Event, event_id, with_for_update={"of": Event}, populate_existing=True)
    if event is None or not _can_view(viewer, event):
        raise EventNotFound(event_id)
    return event


def check_proposed_attendance(event: Event, attendance: int) -> None:
    """Story 19.2 AC2: an approved attendance change keeps 2.7 AC6 - no venue requirement needs
    room for more people than the event's expected attendance - judged with the proposed
    figure against the requirements as they stand. Also checked when the request is raised."""
    ordered = sorted(event.venue_requirements, key=lambda item: item.position)
    for index, requirement in enumerate(ordered):
        if requirement.capacity is not None and requirement.capacity > attendance:
            raise AttendanceBelowRequirement(_describe_requirement(requirement.name, index))


def live_bookings(db: Session, event: Event) -> list[_LiveBooking]:
    """Story 19.2 AC5: ``event``'s pending and approved bookings as they stand, read before an
    approved change is applied, so ``bookings_no_longer_fitting`` can judge them after."""
    return _live_bookings(db, event)


def bookings_no_longer_fitting(event: Event, booked: list[_LiveBooking]) -> list[VenueBooking]:
    """Story 19.2 AC5: the bookings in ``booked`` an approved change has left unfitting, by
    f7.2.4's rule (``_fits_booking``, ``_fits_additional_venue``); every other one still fits and
    is left as it is."""
    return [item.booking for item in _unfitting_bookings(event, booked)]


def apply_proposed_schedule(
    db: Session, event: Event, starts_at: datetime, ends_at: datetime
) -> None:
    """Story 19.2 AC2: move ``event`` to an approved new start and end, checked by 2.1 AC2's date
    rules and AC18's registration window as a request's own dates are. A venue requirement that
    covered the whole old period covers the new one; any other keeps its length and shifts with
    the start (PO decision, 16 Oct 2026), and one that then falls outside the event refuses the
    change by 2.7's rule. Written, not committed."""
    check_proposed_schedule(starts_at, ends_at)
    _check_registration(
        required=event.registration_required,
        opens_at=event.registration_opens_at,
        closes_at=event.registration_closes_at,
        starts_at=starts_at,
        supplied_opens_at=None,
        supplied_closes_at=None,
    )
    old_starts_at, old_ends_at = event.starts_at, event.ends_at
    shift = starts_at - old_starts_at
    for requirement in event.venue_requirements:
        if requirement.starts_at is None or requirement.ends_at is None:
            continue
        if (requirement.starts_at, requirement.ends_at) == (old_starts_at, old_ends_at):
            requirement.starts_at, requirement.ends_at = starts_at, ends_at
        else:
            requirement.starts_at += shift
            requirement.ends_at += shift
    _check_venue_requirement_rules(
        sorted(event.venue_requirements, key=lambda requirement: requirement.position),
        event_starts_at=starts_at,
        event_ends_at=ends_at,
        attendance=event.expected_attendance,
    )
    event.starts_at, event.ends_at = starts_at, ends_at
    _flush_request_edit(db, event)


def apply_proposed_venue_requirements(
    db: Session, event: Event, items: list[VenueRequirementIn]
) -> None:
    """Story 19.2 AC2: give ``event`` an approved list of venue requirements, re-checked by 2.7's
    rules against the event as it stands. One with an ``id`` is kept and edited, so a booking
    for it stays linked (2.7 AC3); one left out is removed; one without is new. Written, not
    committed."""
    check_proposed_venue_requirements(db, event, items)
    _replace_venue_requirements(db, event, items)
    _fill_requirement_times(event)
    _flush_request_edit(db, event)


def check_proposed_schedule(starts_at: datetime, ends_at: datetime) -> None:
    """Story 19.1 AC4: a proposed date and time follows 2.1 AC2's rules - end after start, not in
    the past, at most 2 years ahead, at most 14 days long."""
    _check_schedule(starts_at, ends_at, supplied_start=starts_at, supplied_end=ends_at)


def check_proposed_venue_requirements(
    db: Session, event: Event, items: list[VenueRequirementIn]
) -> None:
    """Story 19.1 AC3/AC4: proposed venue requirements are complete, as a submitted request's must
    be (2.7 AC8), and follow 2.7's rules judged against the event as it stands (PO decision,
    Checkpoint 1: the effect of other pending changes is story 19.3's).

    Fix f2.7.4 (story 2.7 AC18): never an empty list, refused before anything else - and before
    19.1 AC4 compares the proposal with the current value - so an event approved before the fix
    with none is told why, not that nothing would change."""
    if not items:
        raise ChangeLeavesNoVenueRequirement()
    for index, item in enumerate(items):
        label = _describe_requirement(item.name, index)
        if item.name is None:
            raise InvalidVenueRequirement(
                REQUIREMENT_NAME_REQUIRED_MESSAGE.format(requirement=label),
                index=index,
                field="name",
            )
        if item.capacity is None:
            raise InvalidVenueRequirement(
                REQUIREMENT_CAPACITY_REQUIRED_MESSAGE.format(requirement=label),
                index=index,
                field="capacity",
            )
    _check_venue_requirement_references(
        db, items, owned_ids={requirement.id for requirement in event.venue_requirements}
    )
    _check_venue_requirement_rules(
        items,
        event_starts_at=event.starts_at,
        event_ends_at=event.ends_at,
        attendance=event.expected_attendance,
    )


def check_proposed_equipment(db: Session, event: Event, items: list[EventEquipmentIn]) -> None:
    """Story 19.1 AC4: proposed equipment names active types and only this event's own lines
    (2.1 AC6/AC7). Availability is not judged here - stock can change before a coordinator
    decides, so it belongs to the impact view and the decision (stories 19.3, 19.4)."""
    _known(
        db,
        EquipmentType,
        [item.equipment_type_code for item in items],
        label="equipment type",
        is_active_only=True,
    )
    _check_equipment_lines(items, owned_line_ids={line.id for line in event.equipment_requests})


def update_point_of_contact(
    db: Session, event_id: uuid.UUID, data: PointOfContactUpdate, *, actor: User
) -> Event:
    """Story 19.1 AC2: the organiser updates their approved event's point of contact directly,
    with no change request. Only the fields sent and actually different change; each change is
    logged with its old and new value for the change history (7.4 is not built yet, so the
    audit log holds it). Sending the current values is a no-op: no write, no audit entry."""
    event = get_own_event_for_update(db, event_id, actor=actor)
    if event.status not in _CONTACT_EDITABLE_STATUSES:
        raise PointOfContactClosed(event.status)

    sent = data.model_fields_set
    changes = {
        field: {"from": getattr(event, field), "to": getattr(data, field)}
        for field in _CONTACT_FIELDS
        if field in sent and getattr(data, field) != getattr(event, field)
    }
    if not changes:
        return event  # nothing to write; the row lock ends with the request's session
    for field, change in changes.items():
        setattr(event, field, change["to"])
    record_audit(
        db,
        actor=actor,
        action="EVENT_CONTACT_UPDATED",
        entity_type="event",
        entity_id=event.id,
        details=changes,
        commit=False,
    )
    db.commit()
    db.refresh(event)
    return event
