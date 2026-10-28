"""Business rules for story 21.1 (the Safety Officer's queue of events awaiting the safety check)
and story 21.2 (the coordinator requests a review, the officer decides, the coordinator confirms).

Story 21.2's flow::

    PLANNING --request (everything secured)--> AWAITING_SAFETY_CHECK
    AWAITING --approve--> PLANNING --confirm (the approval still matches)--> CONFIRMED
    AWAITING --request changes, with findings--> PLANNING --rebook, request again--> AWAITING
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql.elements import ColumnElement

from app.auth.models import User
from app.auth.permissions import RoleCode
from app.bookings import service as bookings_service
from app.bookings.models import (
    BookingStatus,
    ReleaseCause,
    VenueBooking,
    marked_booking_conditions,
    pending_replacement_conditions,
)
from app.change_requests.models import ChangeRequestStatus, EventChangeRequest
from app.common.audit import record_audit
from app.events.models import (
    EquipmentRequestStatus,
    Event,
    EventEquipmentRequest,
    EventStatus,
    EventStatusHistory,
)
from app.events.service import NotAssignedCoordinator, lock_event, record_transition
from app.notifications.service import NotificationType, active_members, notify
from app.safety.models import (
    EventSafetyReview,
    SafetyArrangement,
    SafetyReviewFactor,
    SafetyReviewFinding,
    SafetyReviewOutcome,
)
from app.safety.schemas import FactChangeOut, SafetyDecisionIn, booked_capacity


class SafetyQueueStatus(StrEnum):
    """The queue's tabs (21.1 AC2, a team request beyond the AC). PENDING is an event awaiting the
    check; ACCEPTED and DECLINED are events no longer awaiting it, by their latest review."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


@dataclass(frozen=True)
class SafetyQueueItem:
    """An event in the queue, with its approved bookings (21.1 AC2) and its tab."""

    event: Event
    approved_bookings: list[VenueBooking]
    safety_status: SafetyQueueStatus


def _approved_bookings(
    db: Session, event_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[VenueBooking]]:
    """Only an APPROVED booking is a booked venue: a pending, withdrawn or expired one is not."""
    bookings = db.scalars(
        select(VenueBooking)
        .options(joinedload(VenueBooking.venue))
        .where(VenueBooking.event_id.in_(event_ids), VenueBooking.status == BookingStatus.APPROVED)
        .order_by(VenueBooking.starts_at, VenueBooking.id)
    ).all()
    by_event: dict[uuid.UUID, list[VenueBooking]] = defaultdict(list)
    for booking in bookings:
        by_event[booking.event_id].append(booking)
    return by_event


def _safety_status(event: Event, latest_outcome: str | None) -> SafetyQueueStatus:
    if event.status == EventStatus.AWAITING_SAFETY_CHECK:
        return SafetyQueueStatus.PENDING
    if latest_outcome == SafetyReviewOutcome.APPROVED:
        return SafetyQueueStatus.ACCEPTED
    return SafetyQueueStatus.DECLINED


def list_safety_queue(db: Session, *, status: SafetyQueueStatus | None) -> list[SafetyQueueItem]:
    """AC2: the events in one tab, or every tab when ``status`` is None, oldest first by when
    each last entered the check."""
    entered = (
        select(
            EventStatusHistory.event_id,
            func.max(EventStatusHistory.changed_at).label("entered_at"),
        )
        .where(EventStatusHistory.to_status == EventStatus.AWAITING_SAFETY_CHECK)
        .group_by(EventStatusHistory.event_id)
        .subquery()
    )
    latest = (
        select(EventSafetyReview.event_id, EventSafetyReview.outcome)
        .distinct(EventSafetyReview.event_id)
        .order_by(
            EventSafetyReview.event_id,
            EventSafetyReview.reviewed_at.desc(),
            EventSafetyReview.id.desc(),
        )
        .subquery()
    )
    is_awaiting = Event.status == EventStatus.AWAITING_SAFETY_CHECK
    tab_filter = {
        None: or_(is_awaiting, latest.c.outcome.is_not(None)),
        SafetyQueueStatus.PENDING: is_awaiting,
        SafetyQueueStatus.ACCEPTED: ~is_awaiting
        & (latest.c.outcome == SafetyReviewOutcome.APPROVED),
        SafetyQueueStatus.DECLINED: ~is_awaiting
        & (latest.c.outcome == SafetyReviewOutcome.CHANGES_REQUESTED),
    }[status]
    rows = db.execute(
        select(Event, latest.c.outcome)
        .outerjoin(entered, entered.c.event_id == Event.id)
        .outerjoin(latest, latest.c.event_id == Event.id)
        .where(tab_filter)
        .order_by(entered.c.entered_at, Event.id)
    ).all()
    bookings = _approved_bookings(db, [event.id for event, _ in rows])
    return [
        SafetyQueueItem(
            event=event,
            approved_bookings=bookings[event.id],
            safety_status=_safety_status(event, outcome),
        )
        for event, outcome in rows
    ]


class SafetyCheckNotFound(LookupError):
    """No event with this id is awaiting the safety check or has been reviewed (21.1 AC3)."""


@dataclass(frozen=True)
class SafetyCheck:
    """Everything the officer reads for one event (21.1 AC3-AC5). ``facts`` is the snapshot the
    review story stores on ``event_safety_reviews.facts``."""

    event: Event
    approved_bookings: list[VenueBooking]
    accepted_equipment: list[EventEquipmentRequest]
    reviews: list[EventSafetyReview]  # newest first
    facts: dict[str, Any]
    changes: list[FactChangeOut]
    factors: list[SafetyReviewFactor]  # 21.2 AC2
    facts_fingerprint: str  # 21.2 AC20: what the officer's decision says it read


def safety_facts(
    event: Event,
    *,
    approved_bookings: list[VenueBooking],
    accepted_equipment: list[EventEquipmentRequest],
) -> dict[str, Any]:
    """The facts a safety review is judged on, as JSON: what story 21.2 stores on
    ``event_safety_reviews.facts`` and AC5 compares. Times are UTC so a stored snapshot compares
    equal to a fresh one. Each code is stored with its name, so a change reads in words."""
    assert event.starts_at is not None  # ck_events_submitted_fields_complete
    assert event.ends_at is not None
    return {
        "description": event.description,  # the idea itself is judged, not only the logistics
        "expected_attendance": event.expected_attendance,
        "starts_at": event.starts_at.astimezone(UTC).isoformat(),
        "ends_at": event.ends_at.astimezone(UTC).isoformat(),
        "venues": [
            {
                "id": str(booking.venue_id),
                "name": booking.venue.name,
                "capacity": booked_capacity(booking),
                "people_to_hold": booking.expected_attendance,
                "layout": booking.required_layout_code,
                "layout_name": (
                    booking.required_layout.name if booking.required_layout is not None else None
                ),
            }
            for booking in approved_bookings
        ],
        "accessibility": [
            {"feature": need.feature_code, "feature_name": need.feature.name, "notes": need.notes}
            for need in event.accessibility_needs
        ],
        "accessibility_notes": event.accessibility_notes,
        "equipment": [
            {
                "equipment_type": item.equipment_type.code,
                "equipment_type_name": item.equipment_type.name,
                "quantity": item.quantity,
                "technical_notes": item.technical_notes,
            }
            for item in accepted_equipment
        ],
    }


def _accepted_equipment(db: Session, event_id: uuid.UUID) -> list[EventEquipmentRequest]:
    return list(
        db.scalars(
            select(EventEquipmentRequest)
            .where(
                EventEquipmentRequest.event_id == event_id,
                EventEquipmentRequest.status == EquipmentRequestStatus.ACCEPTED,
            )
            .order_by(EventEquipmentRequest.created_at, EventEquipmentRequest.id)
        )
    )


# The names stored beside each code, for the change list to read in words. A rename is not a change
# to what was reviewed, so comparisons leave them out (``comparable_facts``).
_DISPLAY_NAME_KEYS = frozenset({"name", "layout_name", "feature_name", "equipment_type_name"})


def comparable_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """``facts`` without the display names: the ids, codes and figures a review judged, so a
    renamed venue, layout, feature or equipment type compares equal (21.2 AC14)."""
    return {
        key: (
            [
                {k: v for k, v in item.items() if k not in _DISPLAY_NAME_KEYS}
                if isinstance(item, dict)
                else item
                for item in value
            ]
            if isinstance(value, list)
            else value
        )
        for key, value in facts.items()
    }


def facts_fingerprint(facts: dict[str, Any]) -> str:
    """21.2 AC20: a digest of ``comparable_facts``, sent with the officer's page and returned with
    the decision, so the facts stored as reviewed are the facts the officer read."""
    canonical = json.dumps(comparable_facts(facts), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def current_facts(db: Session, event: Event) -> dict[str, Any]:
    """The event's safety facts as they stand now (``safety_facts``): what a review stores
    (21.2 AC2) and what a resubmission (AC12) or a confirmation (AC14) compares with it."""
    return safety_facts(
        event,
        approved_bookings=_approved_bookings(db, [event.id])[event.id],
        accepted_equipment=_accepted_equipment(db, event.id),
    )


def safety_check_is_open() -> ColumnElement[bool]:
    """When an event's safety check can be opened (``get_safety_check``, and story 20.2's
    notification targets): it is awaiting the check, or it has been reviewed (the Accepted and
    Declined tabs open it too)."""
    return or_(
        Event.status == EventStatus.AWAITING_SAFETY_CHECK,
        exists().where(EventSafetyReview.event_id == Event.id),
    )


def get_safety_check(db: Session, event_id: uuid.UUID) -> SafetyCheck:
    """AC3: the event's safety facts and previous reviews. AC5: what changed since the latest
    review. Raises ``SafetyCheckNotFound`` unless the event is awaiting the check or has been
    reviewed (the Accepted and Declined tabs open it too)."""
    event = db.scalar(select(Event).where(Event.id == event_id, safety_check_is_open()))
    if event is None:
        raise SafetyCheckNotFound(event_id)
    approved_bookings = _approved_bookings(db, [event.id])[event.id]
    accepted_equipment = _accepted_equipment(db, event.id)
    reviews = list(
        db.scalars(
            select(EventSafetyReview)
            .where(EventSafetyReview.event_id == event.id)
            .order_by(EventSafetyReview.reviewed_at.desc(), EventSafetyReview.id.desc())
        )
    )
    facts = safety_facts(
        event, approved_bookings=approved_bookings, accepted_equipment=accepted_equipment
    )
    # Limitation: diffs whole top-level facts, so one venue edit marks the whole venue list as
    # changed; compare item by item if the officer needs finer detail.
    changes = (
        [
            FactChangeOut(fact=key, before=reviews[0].facts.get(key), after=value)
            for key, value in facts.items()
            if reviews[0].facts.get(key) != value
        ]
        if reviews
        else []
    )
    return SafetyCheck(
        event=event,
        approved_bookings=approved_bookings,
        accepted_equipment=accepted_equipment,
        reviews=reviews,
        facts=facts,
        changes=changes,
        factors=list(
            db.scalars(select(SafetyReviewFactor).order_by(SafetyReviewFactor.sort_order))
        ),
        facts_fingerprint=facts_fingerprint(facts),
    )


# --- story 21.2 ----------------------------------------------------------------------------------
NOT_IN_PLANNING_FOR_REVIEW_MESSAGE = "Only an event in Planning can be sent for a safety review."
NOT_IN_PLANNING_FOR_CONFIRM_MESSAGE = "Only an event in Planning can be confirmed."
NOT_AWAITING_SAFETY_CHECK_MESSAGE = "Only an event awaiting the safety check can be decided."
STATUS_CHANGED_MESSAGE = "This event changed while you were acting on it. Reload and try again."
ARRANGEMENTS_NOT_SECURED_MESSAGE = "Secure every arrangement before requesting a safety review."
NOT_CONFIRMABLE_MESSAGE = "This event cannot be confirmed yet."
# Story 12.6 AC12 (PO decision; the customer's Q12 and Q37): while a booking of the event is marked
# "Venue unavailable - alternative needed", or a replacement for one is waiting for Venue Staff's
# decision, the event is neither sent for a review nor confirmed. Each refusal says what it
# refuses, then every blocker - these venues and whatever else 21.2 names - in one 409.
VENUE_UNAVAILABLE_FOR_REVIEW_MESSAGE = (
    "This event cannot be sent for a safety review while a booked venue is unavailable or a "
    "replacement for it is waiting for a decision."
)
VENUE_UNAVAILABLE_FOR_CONFIRM_MESSAGE = (
    "This event cannot be confirmed while a booked venue is unavailable or a replacement for it "
    "is waiting for a decision."
)
VENUE_UNAVAILABLE_SENTENCE = (
    "{venue} is unavailable for part of its booked period: replace it, or wait for it to reopen."
)
REPLACEMENT_PENDING_SENTENCE = (
    "{venue} is requested as a replacement and not approved yet: wait for the decision, or "
    "withdraw it."
)
NO_VENUE_BOOKED = "No venue is booked."
REQUIREMENT_NOT_BOOKED = "{name} has no approved venue booking."
EQUIPMENT_NOT_ACCEPTED = "{name} is not accepted yet."
NOT_SAFETY_APPROVED = "The event has not been approved by the Safety Officer."
APPROVAL_OUT_OF_DATE = (
    "The event's {facts} changed after the safety approval; request a safety review again."
)
# Story 19.2 AC8: an approved change request can leave every compared fact as it was (fewer people
# in a room every booking still fits, say), but the officer still has not seen it.
CHANGE_APPROVED_SINCE_REVIEW = (
    "A change to the event was approved after its safety approval; request a safety review again."
)
# AC14: each fact a stale approval names, in words.
_FACT_NAMES = {
    "description": "description",
    "expected_attendance": "expected attendance",
    "starts_at": "start",
    "ends_at": "end",
    "venues": "venue bookings",
    "accessibility": "accessibility needs",
    "accessibility_notes": "accessibility notes",
    "equipment": "equipment",
}
# AC1/AC19: the equipment items still open and not accepted. A declined one can never be accepted
# and is locked (15.1 AC7), and a cancelled one takes up nothing, so neither blocks.
_UNSECURED_ITEM_STATUSES = frozenset(
    {
        EquipmentRequestStatus.REQUESTED,
        EquipmentRequestStatus.PENDING,
        EquipmentRequestStatus.UNAVAILABLE,
    }
)
UNKNOWN_FACTOR_MESSAGE = "Choose a review factor from the list."
UNCHANGED_MESSAGE = "The {names} the Safety Officer flagged have not changed since their review."
_UNCHANGED_NAMES = {
    SafetyArrangement.VENUE_BOOKINGS: "venue bookings",
    SafetyArrangement.EQUIPMENT: "equipment",
}
# Story 21.3: what the officer's decision says of the bookings it released, and what it refuses.
# AC4: the coordinator is told once, naming every released booking as its venue and requirement.
RELEASED_DECISION_MESSAGE = (
    "{officer} asked for changes before it can pass and released these venue bookings: "
    "{bookings}. What must change: {changes}"
)
ADDITIONAL_VENUE_NAME = "Additional venue"
# AC2, AC9: a booking two findings name is released once, and its reason is each finding's change.
RELEASE_REASON_SEPARATOR = " | "
# AC7: an id that is not a booking of the event is refused (422); a booking of the event that is
# not approved when the decision is recorded is refused too (409), since the page is out of date.
BOOKING_NOT_OF_EVENT_MESSAGE = "Only this event's bookings can be named."
NAMED_BOOKINGS_NOT_APPROVED_MESSAGE = (
    "Not approved now: {bookings}. Your decision was not recorded. "
    "Reload the review and decide again."
)
_DECISION_NOTIFICATION = {
    SafetyReviewOutcome.APPROVED: NotificationType.SAFETY_APPROVED,
    SafetyReviewOutcome.CHANGES_REQUESTED: NotificationType.SAFETY_CHANGES_REQUESTED,
}


class SafetyEventNotFound(LookupError):
    """No event with this id (a 404)."""


class SafetyStateConflict(RuntimeError):
    """The event is not in the state this action needs (a 409)."""


class EventStatusChanged(SafetyStateConflict):
    """AC20: another request moved the event between reading it and updating it."""

    def __init__(self) -> None:
        super().__init__(STATUS_CHANGED_MESSAGE)


class ArrangementsNotSecured(SafetyStateConflict):
    """AC19: what stops the event being sent for a review, each named."""

    def __init__(self, blockers: list[str]) -> None:
        super().__init__(" ".join([ARRANGEMENTS_NOT_SECURED_MESSAGE, *blockers]))
        self.blockers = blockers


class BookedVenueUnavailable(SafetyStateConflict):
    """Story 12.6 AC12: a live booking of the event is marked unavailable, or a replacement for one
    is still pending, so it is neither sent for a review nor confirmed; ``refusal`` says which,
    then every blocker is named - the venues and whatever else 21.2 names - in this one refusal."""

    def __init__(self, refusal: str, sentences: list[str]) -> None:
        super().__init__(" ".join([refusal, *sentences]))
        self.sentences = sentences


class FlaggedArrangementsUnchanged(SafetyStateConflict):
    """AC12: a flagged arrangement is as the flagging review saw it; the coordinator may
    acknowledge it and submit anyway."""

    def __init__(self, arrangements: list[str]) -> None:
        names = " and ".join(_UNCHANGED_NAMES[a] for a in arrangements)
        super().__init__(UNCHANGED_MESSAGE.format(names=names))
        self.arrangements = arrangements


class EventNotConfirmable(SafetyStateConflict):
    """AC14/AC21: what stops the event being confirmed, each named."""

    def __init__(self, blockers: list[str]) -> None:
        super().__init__(" ".join([NOT_CONFIRMABLE_MESSAGE, *blockers]))
        self.blockers = blockers


class BookingNotOfEvent(ValueError):
    """AC7: a finding names an id that is not a booking of the event (a 422)."""

    def __init__(self) -> None:
        super().__init__(BOOKING_NOT_OF_EVENT_MESSAGE)


def _in_booked_order(bookings: list[VenueBooking]) -> list[VenueBooking]:
    """Bookings as every sentence about them lists them: by booked start, then id."""
    return sorted(bookings, key=lambda booking: (booking.starts_at, booking.id))


def _booking_label(booking: VenueBooking) -> str:
    """AC4, AC11: a booking as the officer's decision names it - its venue and, in brackets, the
    requirement it is for, or "Additional venue"."""
    return f"{booking.venue.name} ({booking.requirement_label or ADDITIONAL_VENUE_NAME})"


class NamedBookingsNotApproved(SafetyStateConflict):
    """AC11: named bookings that were not approved when the decision was recorded - expired,
    cancelled, withdrawn, rejected or never approved - so nothing is released, the review is
    out of date, and the officer reloads it."""

    def __init__(self, bookings: list[VenueBooking]) -> None:
        listed = ", ".join(_booking_label(booking) for booking in _in_booked_order(bookings))
        super().__init__(NAMED_BOOKINGS_NOT_APPROVED_MESSAGE.format(bookings=listed))


class UnknownSafetyFactor(ValueError):
    """AC10: a finding names a factor that is not in ``safety_review_factors`` (a 422)."""

    def __init__(self) -> None:
        super().__init__(UNKNOWN_FACTOR_MESSAGE)


def missing_arrangements(db: Session, event: Event) -> list[str]:
    """AC1/AC11: what is not yet secured - each venue requirement without an approved booking,
    no approved booking at all, and each equipment item still open and not accepted. ``[]`` is
    secured."""
    approved = _approved_bookings(db, [event.id])[event.id]
    booked = {booking.venue_requirement_id for booking in approved}
    missing = [
        REQUIREMENT_NOT_BOOKED.format(name=requirement.name or f"Venue {index}")
        for index, requirement in enumerate(event.venue_requirements, start=1)
        if requirement.id not in booked
    ]
    if not approved:
        missing.append(NO_VENUE_BOOKED)
    missing += [
        EQUIPMENT_NOT_ACCEPTED.format(name=item.equipment_type.name)
        for item in event.equipment_requests
        if item.status in _UNSECURED_ITEM_STATUSES
    ]
    return missing


def latest_review(db: Session, event_id: uuid.UUID) -> EventSafetyReview | None:
    return db.scalar(
        select(EventSafetyReview)
        .where(EventSafetyReview.event_id == event_id)
        .order_by(EventSafetyReview.reviewed_at.desc(), EventSafetyReview.id.desc())
        .limit(1)
    )


def booked_venue_blockers(db: Session, event: Event) -> list[str]:
    """Story 12.6 AC12: one sentence for each venue of ``event`` that holds the review back - a
    live booking marked "Venue unavailable" (replace it, or wait for it to reopen), then each
    replacement still pending (wait for the decision, or withdraw it) - naming the venue; ``[]``
    when there is none. Read with the one definition of each (``marked_booking_conditions``,
    ``pending_replacement_conditions``), so a mark left on a closed booking, or on another event's
    booking, is not here. A replacement counts after the mark clears too: its approval would
    change the venue the review saw."""
    marked = db.scalars(
        select(VenueBooking)
        .options(joinedload(VenueBooking.venue))
        .where(VenueBooking.event_id == event.id, *marked_booking_conditions())
        .order_by(VenueBooking.starts_at, VenueBooking.id)
    ).all()
    replacements = db.scalars(
        select(VenueBooking)
        .options(joinedload(VenueBooking.venue))
        .where(VenueBooking.event_id == event.id, *pending_replacement_conditions())
        .order_by(VenueBooking.starts_at, VenueBooking.id)
    ).all()
    unavailable = dict.fromkeys(booking.venue.name for booking in marked)
    requested = dict.fromkeys(booking.venue.name for booking in replacements)
    return [
        *(VENUE_UNAVAILABLE_SENTENCE.format(venue=name) for name in unavailable),
        *(REPLACEMENT_PENDING_SENTENCE.format(venue=name) for name in requested),
    ]


def request_blockers(db: Session, event: Event) -> list[str]:
    """AC1/AC19: what stops a review being requested now; ``[]`` offers it. Story 12.6 AC12: each
    unavailable booked venue, and each venue with a replacement still pending, is named too, so the
    event page says why before anything is sent."""
    if event.status != EventStatus.PLANNING:
        return [NOT_IN_PLANNING_FOR_REVIEW_MESSAGE]
    return [*missing_arrangements(db, event), *booked_venue_blockers(db, event)]


def _change_approved_since(db: Session, event: Event, review: EventSafetyReview) -> bool:
    """Story 19.2 AC8: a change request on ``event`` was approved after ``review``, so the event
    must go through its safety check again before it is confirmed - whether the approval sent it
    back to Planning or found it there."""
    return db.scalar(
        select(
            exists().where(
                EventChangeRequest.event_id == event.id,
                EventChangeRequest.status == ChangeRequestStatus.APPROVED,
                EventChangeRequest.decided_at > review.reviewed_at,
            )
        )
    )


def confirm_blockers(db: Session, event: Event) -> list[str]:
    """AC7/AC14/AC21: what stops the event being confirmed now; ``[]`` offers it. The latest
    review must be an approval that saw the facts the event has now, with no change request
    approved since (story 19.2 AC8). Story 12.6 AC12: a booking marked unavailable, or with a
    replacement pending, is named here as it is for the review's request."""
    if event.status != EventStatus.PLANNING:
        return [NOT_IN_PLANNING_FOR_CONFIRM_MESSAGE]
    blockers = [*missing_arrangements(db, event), *booked_venue_blockers(db, event)]
    review = latest_review(db, event.id)
    if review is None or review.outcome != SafetyReviewOutcome.APPROVED:
        blockers.append(NOT_SAFETY_APPROVED)
        return blockers
    approved = comparable_facts(review.facts)
    now = comparable_facts(current_facts(db, event))
    changed = [_FACT_NAMES[key] for key in _FACT_NAMES if approved.get(key) != now.get(key)]
    if changed:
        blockers.append(APPROVAL_OUT_OF_DATE.format(facts=" and ".join(changed)))
    if _change_approved_since(db, event, review):
        blockers.append(CHANGE_APPROVED_SINCE_REVIEW)
    return blockers


@dataclass(frozen=True)
class EventSafety:
    """The event page's safety summary (AC4, AC7). The blockers and the warning are ``None``
    unless the viewer is the assigned coordinator (AC18)."""

    event: Event
    latest_review: EventSafetyReview | None
    request_blockers: list[str] | None
    confirm_blockers: list[str] | None
    unchanged_warning: str | None  # AC12, asked before the request is sent


def get_event_safety(db: Session, event: Event, *, viewer: User) -> EventSafety:
    """AC4: the latest review and its findings, for anyone who may see the event. AC1/AC7: what
    stops the assigned coordinator requesting a review or confirming; AC18: no one else is
    offered either. AC12: the warning the request would raise, so the page asks first."""
    if event.assigned_coordinator_id != viewer.id:
        return EventSafety(
            event=event,
            latest_review=latest_review(db, event.id),
            request_blockers=None,
            confirm_blockers=None,
            unchanged_warning=None,
        )
    unchanged = _unchanged_flags(db, event) if event.status == EventStatus.PLANNING else []
    return EventSafety(
        event=event,
        latest_review=latest_review(db, event.id),
        request_blockers=request_blockers(db, event),
        confirm_blockers=confirm_blockers(db, event),
        unchanged_warning=str(FlaggedArrangementsUnchanged(unchanged)) if unchanged else None,
    )


def _change_status(
    db: Session,
    event: Event,
    *,
    from_status: str,
    to_status: str,
    actor: User,
    reason: str | None,
) -> None:
    """Move ``event`` on, conditional on it still being in ``from_status``, so of two requests at
    once only one succeeds (AC20, AC21); the other is rolled back and refused."""
    changed = db.execute(
        update(Event)
        .where(Event.id == event.id, Event.status == from_status)
        .values(status=to_status)
    )
    if changed.rowcount == 0:
        db.rollback()
        raise EventStatusChanged()
    record_transition(
        db,
        event,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        at=datetime.now(UTC),
        reason=reason,
    )


def _tell(
    db: Session,
    event: Event,
    recipients: list[User | None],
    *,
    actor: User,
    kind: NotificationType,
    title: str,
    message: str,
) -> None:
    """AC8: tell each recipient once; ``notify`` skips the actor and a missing coordinator."""
    for recipient in {r.id: r for r in recipients if r is not None}.values():
        notify(
            db,
            recipient=recipient,
            actor=actor,
            notification_type=kind,
            event_id=event.id,
            title=title,
            message=message,
            related_entity_type="event",
            related_entity_id=event.id,
            commit=False,
        )


def _assert_assigned_coordinator(event: Event, actor: User, *, verb: str) -> None:
    if event.assigned_coordinator_id != actor.id:
        raise NotAssignedCoordinator(verb)


def _unchanged_flags(db: Session, event: Event) -> list[str]:
    """AC12/AC13: the arrangements the latest review flagged that are still as it saw them."""
    review = latest_review(db, event.id)
    if review is None or review.outcome != SafetyReviewOutcome.CHANGES_REQUESTED:
        return []
    now = comparable_facts(current_facts(db, event))
    flagged = comparable_facts(review.facts)
    return [
        arrangement
        for arrangement in review.flagged_arrangements
        if now[SafetyArrangement.FACT_KEY[arrangement]]
        == flagged.get(SafetyArrangement.FACT_KEY[arrangement])
    ]


def request_safety_review(
    db: Session, event: Event, *, actor: User, acknowledge_unchanged: bool
) -> None:
    """AC1: the assigned coordinator sends a secured Planning event for the safety check; the
    Safety Officers and the organiser are told (AC8). AC19: refused unless it is in Planning and
    secured, naming what is missing. AC12: refused with a warning when a flagged arrangement is
    unchanged, unless ``acknowledge_unchanged``. Story 12.6 AC12: refused
    (``BookedVenueUnavailable``) while a booking of the event is marked unavailable or a
    replacement for one is pending, in one refusal naming those venues and what is missing."""
    _assert_assigned_coordinator(event, actor, verb="request a safety review of")
    if event.status != EventStatus.PLANNING:
        raise SafetyStateConflict(NOT_IN_PLANNING_FOR_REVIEW_MESSAGE)
    missing = missing_arrangements(db, event)
    venues = booked_venue_blockers(db, event)
    if venues:
        raise BookedVenueUnavailable(VENUE_UNAVAILABLE_FOR_REVIEW_MESSAGE, [*missing, *venues])
    if missing:
        raise ArrangementsNotSecured(missing)
    unchanged = _unchanged_flags(db, event)
    if unchanged and not acknowledge_unchanged:
        raise FlaggedArrangementsUnchanged(unchanged)

    _change_status(
        db,
        event,
        from_status=EventStatus.PLANNING,
        to_status=EventStatus.AWAITING_SAFETY_CHECK,
        actor=actor,
        reason=None,
    )
    _tell(
        db,
        event,
        [*active_members(db, role_code=RoleCode.SAFETY_OFFICER), event.organiser],
        actor=actor,
        kind=NotificationType.SAFETY_REVIEW_REQUESTED,
        title=f'"{event.name}" is awaiting a safety review',
        message=f'{actor.full_name} requested a safety review of "{event.name}".',
    )
    record_audit(
        db,
        actor=actor,
        action="SAFETY_REVIEW_REQUESTED",
        entity_type="event",
        entity_id=event.id,
        details={"acknowledged_unchanged": unchanged},
        commit=False,
    )
    db.commit()
    db.refresh(event)


@dataclass(frozen=True)
class _Notice:
    title: str
    message: str


def _decision_notice(event: Event, data: SafetyDecisionIn, actor: User) -> _Notice:
    if data.outcome == SafetyReviewOutcome.APPROVED:
        return _Notice(
            f'"{event.name}" passed the safety review',
            f"{actor.full_name} approved it. The coordinator can now confirm the event.",
        )
    return _Notice(
        f'Safety changes requested for "{event.name}"',
        f"{actor.full_name} asked for changes before it can pass: "
        + "; ".join(finding.required_change for finding in data.findings),
    )


def _lock_named_bookings(
    db: Session, event: Event, data: SafetyDecisionIn
) -> dict[uuid.UUID, VenueBooking]:
    """AC11: the bookings the findings name, each locked after the event, in id order. An id that
    is not a booking of the event is refused (``BookingNotOfEvent``, AC7)."""
    wanted = list(dict.fromkeys(id_ for finding in data.findings for id_ in finding.booking_ids))
    if not wanted:
        return {}
    named = {
        booking.id: booking
        for booking in bookings_service.lock_named_bookings(db, event.id, wanted)
    }
    if set(wanted) != set(named):
        raise BookingNotOfEvent()
    return named


def _release_reasons(
    data: SafetyDecisionIn, named: dict[uuid.UUID, VenueBooking]
) -> dict[uuid.UUID, str]:
    """AC2, AC9: why each named booking is released - the required change of every finding that
    names it, in finding order."""
    changes: dict[uuid.UUID, list[str]] = {booking_id: [] for booking_id in named}
    for finding in data.findings:
        for booking_id in finding.booking_ids:
            changes[booking_id].append(finding.required_change)
    return {booking_id: RELEASE_REASON_SEPARATOR.join(each) for booking_id, each in changes.items()}


def decide_safety_check(
    db: Session, event_id: uuid.UUID, data: SafetyDecisionIn, *, actor: User
) -> None:
    """AC2-AC5: record the officer's decision with the facts reviewed - Approve or Request
    changes, each returning the event to Planning. AC6: the round keeps who, when and the facts.
    AC8: the coordinator and organiser are told. AC20: refused unless awaiting the check, or if
    the facts moved since the officer read them (``data.facts_fingerprint``), and of two
    decisions at once only one is written.

    Story 21.3: each booking a finding names is released in the same transaction (AC2). The event
    is locked first and then the named bookings in id order, as a cancellation and a confirmation
    take them, so whichever of the decision, an expiry or a cancellation is saved first wins
    (AC11): a booking not approved by then, or an event no longer awaiting, refuses the decision
    and releases and notifies nothing. The releases are attempted, all or none: ``release_booking``
    releases an approved booking only, so a named booking it does not release is the refusal."""
    event = lock_event(db, event_id)
    if event is None:
        raise SafetyEventNotFound(event_id)
    if event.status != EventStatus.AWAITING_SAFETY_CHECK:
        raise SafetyStateConflict(NOT_AWAITING_SAFETY_CHECK_MESSAGE)
    named = _lock_named_bookings(db, event, data)
    facts = current_facts(db, event)  # read while still awaiting: what was reviewed
    decided_at = datetime.now(UTC)
    review_id = uuid.uuid4()
    reasons = _release_reasons(data, named)
    savepoint = db.begin_nested()
    not_approved = [
        booking
        for booking in named.values()
        if not bookings_service.release_booking(
            db,
            booking,
            actor=actor,
            cause=ReleaseCause.SAFETY_REVIEW,
            reason=reasons[booking.id],
            at=decided_at,
            details={
                "cause": ReleaseCause.SAFETY_REVIEW,
                "reason": reasons[booking.id],
                "review_id": str(review_id),
            },
        )
    ]
    if not_approved:
        savepoint.rollback()
        raise NamedBookingsNotApproved(not_approved)
    if facts_fingerprint(facts) != data.facts_fingerprint:
        savepoint.rollback()
        raise EventStatusChanged()
    savepoint.commit()

    _change_status(
        db,
        event,
        from_status=EventStatus.AWAITING_SAFETY_CHECK,
        to_status=EventStatus.PLANNING,
        actor=actor,
        reason=None,
    )
    db.add(
        EventSafetyReview(
            id=review_id,
            event_id=event.id,
            reviewed_by_id=actor.id,
            reviewed_at=decided_at,
            outcome=data.outcome,
            facts=facts,
            findings=[
                SafetyReviewFinding(
                    position=position,
                    factor_code=finding.factor_code,
                    arrangement=finding.arrangement,
                    required_change=finding.required_change,
                    released_bookings=[named[booking_id] for booking_id in finding.booking_ids],
                )
                for position, finding in enumerate(data.findings)
            ],
        )
    )
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if "event_safety_review_findings_factor_code_fkey" in str(exc.orig):
            raise UnknownSafetyFactor() from exc
        raise
    notice = _decision_notice(event, data, actor)
    kind = _DECISION_NOTIFICATION[data.outcome]
    if named:
        # AC4: the coordinator is told once what was released; the organiser, the decision only.
        released = ", ".join(_booking_label(b) for b in _in_booked_order(list(named.values())))
        coordinator_message = RELEASED_DECISION_MESSAGE.format(
            officer=actor.full_name,
            bookings=released,
            changes="; ".join(finding.required_change for finding in data.findings),
        )
        _tell(
            db,
            event,
            [event.assigned_coordinator],
            actor=actor,
            kind=kind,
            title=notice.title,
            message=coordinator_message,
        )
        _tell(
            db,
            event,
            [event.organiser],
            actor=actor,
            kind=kind,
            title=notice.title,
            message=notice.message,
        )
    else:
        _tell(
            db,
            event,
            [event.assigned_coordinator, event.organiser],
            actor=actor,
            kind=kind,
            title=notice.title,
            message=notice.message,
        )
    record_audit(
        db,
        actor=actor,
        action=f"SAFETY_{data.outcome}",
        entity_type="event",
        entity_id=event.id,
        details={"findings": len(data.findings)},
        commit=False,
    )
    db.commit()
    db.refresh(event)


def confirm_event(db: Session, event: Event, *, actor: User) -> None:
    """AC7: the assigned coordinator confirms an event the latest review approved, with the facts
    it still has; it moves to Confirmed and ``trg_events_complete_venue_holds`` completes its
    venue holds. AC14/AC21: refused, naming each blocker. AC8: the organiser and Safety Officers
    are told. Story 12.6 AC12: refused (``BookedVenueUnavailable``) while a booking of the event
    is marked unavailable or a replacement for one is pending, in one refusal naming those venues
    and every other blocker - read after the bookings are locked."""
    _assert_assigned_coordinator(event, actor, verb="confirm")
    # Story 6.2: the event first, then its bookings, the order a cancellation takes them, so the
    # two take turns instead of each holding what the other waits for. FOR NO KEY UPDATE, as
    # ``lock_own_event`` takes it, so a Venue Staff approval's notice never waits on it. Read as it
    # now stands: a cancellation waited for leaves it Cancelled, which ``confirm_blockers``
    # refuses ("Only an event in Planning can be confirmed.").
    db.execute(select(Event.id).where(Event.id == event.id).with_for_update(key_share=True))
    db.refresh(event)
    # 12.7 AC10: then the approved bookings, so a sweep at the same moment either waits for
    # this confirmation (and the trigger completes their holds) or has already expired them (and
    # the blockers name the lost booking). Whichever is saved first wins.
    db.scalars(
        select(VenueBooking.id)
        .where(VenueBooking.event_id == event.id, VenueBooking.status == BookingStatus.APPROVED)
        .with_for_update()
    ).all()
    blockers = confirm_blockers(db, event)
    if blockers and booked_venue_blockers(db, event):
        raise BookedVenueUnavailable(VENUE_UNAVAILABLE_FOR_CONFIRM_MESSAGE, blockers)
    if blockers:
        raise EventNotConfirmable(blockers)

    _change_status(
        db,
        event,
        from_status=EventStatus.PLANNING,
        to_status=EventStatus.CONFIRMED,
        actor=actor,
        reason=None,
    )
    _tell(
        db,
        event,
        [event.organiser, *active_members(db, role_code=RoleCode.SAFETY_OFFICER)],
        actor=actor,
        kind=NotificationType.EVENT_CONFIRMED,
        title=f'"{event.name}" is confirmed',
        message=f"{actor.full_name} confirmed the event after it passed the safety review.",
    )
    record_audit(
        db,
        actor=actor,
        action="EVENT_CONFIRMED",
        entity_type="event",
        entity_id=event.id,
        commit=False,
    )
    db.commit()
    db.refresh(event)
