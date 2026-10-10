"""Venue booking rules: raising a request (story 12.1), conflict detection (story 14.2),
withdrawing a request (story 12.2), and switching a requirement's pending request to another
venue (story 12.5, ``switch_booking_request``).

Story 12.1 - "As an Event Coordinator I want to request a venue booking for an event so
that Venue Staff can assess and confirm it":

* AC1 ``create_booking_request`` refuses an event that is not APPROVED or later, and takes
  exactly one ``venue_id``, so one request is one venue;
* AC2 the schedule, attendance, layout and required facilities are copied from the event
  rather than taken from the request body - see ``_requirement_notes``. Since story 2.7 an event
  lists several venue requirements, and since story 12.5 a request names the one it is for and
  carries that requirement's own; one that names none is an additional venue, which carries
  the event's own period and attendance;
* AC3 the row is written PENDING with no decision, which is what story 13.1's queue and
  story 13.2's ``approve_booking`` below both read;
* AC4 refused unless the actor is the event's ``assigned_coordinator_id``.

Setup and teardown minutes are left at the column default of 0, so the held period equals
the event period: recording them is the rest of Sprint 2's 12.1.

The venue hold - Sprint 2's 12.1 AC3/AC12/AC14, built as s12.1: a PENDING request holds
its venue for its held period, as an APPROVED booking does. ``create_booking_request`` refuses a
period that overlaps a pending or approved booking of the same venue (``VenueHeld``, naming it in
Singapore time), and since migration 010 the exclusion constraint covers PENDING rows too, so two
requests racing for one slot cannot both land - the loser's write is translated into the same
``VenueHeld``. A pending request can therefore never clash when it is approved.

Story 14.2 - "As a Venue Staff member, I want the system to block approval of a conflicting
request so that a venue cannot be double-booked":

* AC1 approval is refused where the requested period overlaps a confirmed booking for the
  same venue;
* AC2 the refusal identifies the conflicting booking - ``BookingConflict`` carries the
  conflicting ``VenueBooking`` row;
* AC3 approving one of two overlapping pending requests refuses the other - this follows
  directly from AC1: once the first request is APPROVED, the second's held period now
  overlaps a confirmed booking and the same check refuses it.

Race safety: ``find_conflicting_booking`` / ``assert_no_conflict`` are a fast, friendly
pre-check only - they do not by themselves close the race between two concurrent approvals
(two overlapping requests could both pass the check before either commits). Since the hold,
such a pair can no longer both be pending, so this approval-time check is a safety net. The
database's
``ex_venue_bookings_no_double_booking`` exclusion constraint is the actual last word, so
``approve_booking`` attempts the write directly and translates that constraint's
``IntegrityError`` into ``BookingConflict``, mirroring ``app/venues/service.py::create_venue``'s
write-then-catch pattern. That constraint only guards two *different* overlapping bookings; it
does nothing to stop two concurrent approvals of the *same* booking (both could read PENDING
and both write APPROVED). Story 13.2 closes that gap: its router fetches the booking through
``get_booking_for_decision`` (``SELECT ... FOR UPDATE``), so a second concurrent approval blocks
on the row lock and, once it proceeds, sees the already-APPROVED row and is refused by the
``BookingNotPending`` check below rather than racing the write.

Story 13.2 ("approve venue booking request") is what calls ``approve_booking`` and translates
``BookingNotPending`` / ``BookingConflict`` into the HTTP response its AC1/AC4 need.

Story 12.2 - "As an Event Coordinator I want to withdraw a venue I no longer need, so that I
don't hold a venue unnecessarily": ``withdraw_booking`` closes a PENDING request (AC7), releasing
its hold on the venue and notifying every active Venue Staff member, together in one call (AC2/
AC3). AC6 restricts it to the event's own assigned coordinator. AC8: it shares approve/reject's
row lock, so a withdrawal racing a Venue Staff decision on the same request is serialized by the
same mechanism, not a new one.

Story 20.1 - notifications: a new request tells every active Venue Staff member, and a decision
tells the event's coordinator - whoever holds the event now, not necessarily who asked (AC4).
Each is written before the action's audit entry and commit, so a refused or failed action sends
none, and a decision that loses the row lock to another sends none (AC6).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth.models import User
from app.auth.permissions import RoleCode
from app.bookings.models import BookingStatus, VenueBooking
from app.bookings.schemas import BookingRequestIn, BookingSwitchIn
from app.common.audit import record_audit
from app.events.models import Event, EventStatus, VenueRequirement, VenueRequirementFacility
from app.notifications.service import NotificationType, active_members, notify
from app.venues import service as venue_service
from app.venues.models import (
    Facility,
    UnavailabilityReason,
    Venue,
    VenueStatus,
    VenueUnavailabilityPeriod,
)

_CONFLICT_CONSTRAINT = "ex_venue_bookings_no_double_booking"

BOOKING_CONFLICT_MESSAGE = (
    "This request overlaps approved booking {conflicting_id} for the same venue, held from "
    "{held_from} to {held_until}."
)

BOOKING_NOT_PENDING_MESSAGE = "This request is already {status}, so it cannot be {action}."

EVENT_NOT_BOOKABLE_MESSAGE = (
    "A venue booking can only be requested for an approved event. This event is {status}."
)

VENUE_NOT_BOOKABLE_MESSAGE = (
    "This venue has been withdrawn from the catalogue and can no longer be booked."
)

NOT_ASSIGNED_COORDINATOR_MESSAGE = (
    "Only the coordinator assigned to this event can request a venue booking for it."
)
# Story 12.2 AC6: the withdraw endpoint's own wording for the same relationship rule.
WITHDRAW_NOT_ASSIGNED_COORDINATOR_MESSAGE = (
    "Only the coordinator assigned to this event can withdraw its booking requests."
)

# 12.1 AC3/AC12: why a request is refused when its venue is held, in words a coordinator can act
# on - the venue, whether it is booked or only requested, the event, and the held period in
# Singapore time, e.g. "Grand Hall is already booked for Nimbus Developer Conference on Wed 25
# Nov 2026 from 08:00 to 19:00, including setup and teardown."
VENUE_HELD_MESSAGE = "{venue} is already {state} for {event} {period}{turnaround}."
# Story 12.5 AC11: a request may only name one of its own event's venue requirements (404).
REQUIREMENT_NOT_OF_EVENT_MESSAGE = "This venue requirement is not one of the event's."
# Story 12.5 AC11/AC12: a requirement takes one pending or approved request at a time (409),
# naming the venue it already has.
REQUIREMENT_ALREADY_REQUESTED_MESSAGE = "{requirement} already has a venue {state}: {venue}."
REQUIREMENT_ALREADY_REQUESTED_STATES = {
    BookingStatus.PENDING: "requested",
    BookingStatus.APPROVED: "booked",
}
_ONE_PER_REQUIREMENT_INDEX = "uq_venue_bookings_one_per_requirement"
VENUE_HELD_STATES = {
    BookingStatus.APPROVED: "booked",
    BookingStatus.PENDING: "held by a pending request",
}
VENUE_HELD_TURNAROUND = ", including setup and teardown"
# The statuses that hold a venue - the same list as ex_venue_bookings_no_double_booking's WHERE.
_HOLDING_STATUSES = tuple(VENUE_HELD_STATES)
# Every event runs on Singapore time, which has no daylight saving (as in app/events/service.py).
_SINGAPORE = timezone(timedelta(hours=8))

# 12.1 AC14: why a request is refused when its venue stopped being available after the catalogue
# search - closed for a recorded period, e.g. "Seminar Room 2.1 is closed for maintenance from Mon
# 2 Nov 2026, 00:00 to Wed 4 Nov 2026, 00:00.", or at those hours.
VENUE_BLOCKED_MESSAGE = "{venue} is closed{reason} {period}."
VENUE_BLOCKED_REASONS = {
    UnavailabilityReason.MAINTENANCE: " for maintenance",
    UnavailabilityReason.RENOVATION: " for renovation",
    UnavailabilityReason.SAFETY: " for safety reasons",
    UnavailabilityReason.INTERNAL_USE: " for internal use",
    UnavailabilityReason.OTHER: "",
}
VENUE_CLOSED_MESSAGE = (
    "{venue} is open {opens:%H:%M} to {closes:%H:%M}, so it cannot take an event from "
    "{starts:%H:%M} to {ends:%H:%M}."
)

REQUIRED_FACILITIES_SENTENCE = "Required facilities: {facilities}."
# A facility may be needed in a quantity, with a note of its own ("3 breakout rooms, HDMI
# input needed"). Venue Staff read all of it as one sentence, so each is appended to the name.
FACILITY_QUANTITY_SUFFIX = " ×{quantity}"
FACILITY_NOTES_SUFFIX = " ({notes})"

# Story 11.1 AC2/AC7: requesting a venue that does not suit the event needs a reason.
JUSTIFICATION_REQUIRED_MESSAGE = (
    "This venue does not suit the event's venue requirement. Give a justification to request it "
    "anyway."
)

# AC1 is worded "an approved event"; the schema's rule is approved *or later* (see the
# venue_bookings.event_id comment in 001_initial_schema.sql), because an event already in
# planning or confirmed may still need a further venue booked. An approved request is in
# PLANNING, so PLANNING and CONFIRMED are the two statuses that qualify.
_BOOKABLE_EVENT_STATUSES = frozenset({EventStatus.PLANNING, EventStatus.CONFIRMED})

# Story 13.1.2 AC4: the queue's page size, and the furthest it can be paged - the same bounds as
# the Events inbox (``app.events.service.MY_EVENTS_MAX_LIMIT`` / ``MY_EVENTS_MAX_OFFSET``).
BOOKING_QUEUE_MAX_LIMIT = 100
BOOKING_QUEUE_MAX_OFFSET = 2_147_483_647


class BookingNotFound(LookupError):
    pass


class EventNotFound(LookupError):
    """12.1 AC1: the request names an event that does not exist."""


class VenueNotFound(LookupError):
    """12.1 AC1: the request names a venue that does not exist."""


class EventNotBookable(ValueError):
    """12.1 AC1: a booking may only be raised from an approved (or later) event."""

    def __init__(self, event: Event) -> None:
        super().__init__(EVENT_NOT_BOOKABLE_MESSAGE.format(status=event.status))
        self.event = event


class VenueNotBookable(ValueError):
    """12.1 AC1: a withdrawn venue is no longer offered for booking (story 8.4)."""

    def __init__(self, venue: Venue) -> None:
        super().__init__(VENUE_NOT_BOOKABLE_MESSAGE)
        self.venue = venue


class NotAssignedCoordinator(PermissionError):
    """12.1 AC4 / 12.2 AC6: only the event's assigned coordinator may raise or withdraw its
    booking requests.

    A relationship rule, not a role rule - every coordinator holds ``bookings:request``, so
    this needs the event row in hand and belongs here rather than in ``permissions.py``.
    """

    def __init__(self, *, message: str = NOT_ASSIGNED_COORDINATOR_MESSAGE) -> None:
        super().__init__(message)


class VenueHeld(ValueError):
    """12.1 AC3/AC12/AC14: the requested held period overlaps a pending or approved booking of
    the same venue, which holds it. Carries that booking; its venue and event must be loaded."""

    def __init__(self, holding_booking: VenueBooking) -> None:
        super().__init__(
            VENUE_HELD_MESSAGE.format(
                venue=holding_booking.venue.name,
                state=VENUE_HELD_STATES[holding_booking.status],
                event=holding_booking.event.name,
                period=_describe_held_period(holding_booking.held_from, holding_booking.held_until),
                turnaround=(
                    VENUE_HELD_TURNAROUND
                    if holding_booking.setup_minutes or holding_booking.teardown_minutes
                    else ""
                ),
            )
        )
        self.holding_booking = holding_booking


class VenueBlocked(ValueError):
    """12.1 AC14: an unavailability period (maintenance, renovation, ...) closes the venue for
    part of the requested period. Carries that period."""

    def __init__(self, venue: Venue, closure: VenueUnavailabilityPeriod) -> None:
        super().__init__(
            VENUE_BLOCKED_MESSAGE.format(
                venue=venue.name,
                reason=VENUE_BLOCKED_REASONS.get(closure.reason, ""),
                period=_describe_held_period(closure.starts_at, closure.ends_at),
            )
        )
        self.closure = closure


class VenueClosed(ValueError):
    """12.1 AC14: the requested period's daily window falls outside the venue's opening hours."""

    def __init__(self, venue: Venue, *, starts_at: datetime, ends_at: datetime) -> None:
        super().__init__(
            VENUE_CLOSED_MESSAGE.format(
                venue=venue.name,
                opens=venue.operating_hours_start,
                closes=venue.operating_hours_end,
                starts=starts_at.astimezone(_SINGAPORE),
                ends=ends_at.astimezone(_SINGAPORE),
            )
        )
        self.venue = venue


class RequirementNotOfEvent(LookupError):
    """Story 12.5 AC11: the request names a venue requirement that is not its event's."""

    def __init__(self) -> None:
        super().__init__(REQUIREMENT_NOT_OF_EVENT_MESSAGE)


class RequirementAlreadyRequested(ValueError):
    """Story 12.5 AC11/AC12: the requirement already has a pending or approved request; the
    message names its venue."""

    def __init__(self, requirement: VenueRequirement, covering: VenueBooking) -> None:
        super().__init__(
            REQUIREMENT_ALREADY_REQUESTED_MESSAGE.format(
                requirement=requirement.name,
                state=REQUIREMENT_ALREADY_REQUESTED_STATES[covering.status],
                venue=covering.venue.name,
            )
        )


class JustificationRequired(ValueError):
    """Story 11.1 AC2/AC7: the venue does not suit the event and no justification was given."""

    def __init__(self) -> None:
        super().__init__(JUSTIFICATION_REQUIRED_MESSAGE)


class BookingConflict(ValueError):
    """14.2 AC1/AC2: the requested period overlaps an existing APPROVED booking for the
    venue."""

    def __init__(self, conflicting_booking: VenueBooking) -> None:
        super().__init__(
            BOOKING_CONFLICT_MESSAGE.format(
                conflicting_id=conflicting_booking.id,
                held_from=conflicting_booking.held_from.isoformat(),
                held_until=conflicting_booking.held_until.isoformat(),
            )
        )
        self.conflicting_booking = conflicting_booking


class BookingNotPending(ValueError):
    """13.2 AC1 / 13.2.1 AC5: only a PENDING request may be approved or rejected - refuses
    repeat or invalid-state decisions (e.g. a request that was already decided, or since
    withdrawn/cancelled). ``action`` names the refused verb ("approved"/"rejected") so the
    message stays accurate for whichever one was attempted."""

    def __init__(self, booking: VenueBooking, *, action: str) -> None:
        super().__init__(BOOKING_NOT_PENDING_MESSAGE.format(status=booking.status, action=action))
        self.booking = booking


@dataclass(frozen=True)
class BookingQueueListing:
    """One page of the queue, how many requests its tab holds, and how many hold each status."""

    bookings: list[VenueBooking]
    total: int
    counts_by_status: dict[str, int]


def list_booking_requests(
    db: Session,
    *,
    status: str | None = None,
    limit: int = BOOKING_QUEUE_MAX_LIMIT,
    offset: int = 0,
) -> BookingQueueListing:
    """Story 13.1 AC1/AC3: ``status=PENDING`` is the pending queue, so a decided request never
    appears in it. AC1's "responsible for" is every venue: there is no per-venue staff
    responsibility table in the schema, and BOOKINGS_DECIDE is a role-wide permission today,
    same as VENUES_MANAGE.

    Story 13.1.2 AC1: ``status`` narrows the queue to one tab; ``None`` is the All tab.
    ``counts_by_status`` ignores both the tab and the page, so every tab label stays right.
    AC4: soonest first, ties broken by id so the pages cut from it are stable. The tab's total
    comes from the same per-status count, so it costs no query of its own."""
    page = (
        select(VenueBooking)
        .options(
            joinedload(VenueBooking.event),
            joinedload(VenueBooking.venue),
            joinedload(VenueBooking.requested_by),
            joinedload(VenueBooking.required_layout),
        )
        .order_by(VenueBooking.starts_at, VenueBooking.id)
        .limit(limit)
        .offset(offset)
    )
    if status is not None:
        page = page.where(VenueBooking.status == status)
    counts_by_status = dict(
        db.execute(select(VenueBooking.status, func.count()).group_by(VenueBooking.status)).all()
    )
    total = sum(counts_by_status.values()) if status is None else counts_by_status.get(status, 0)
    return BookingQueueListing(
        bookings=list(db.scalars(page).all()), total=total, counts_by_status=counts_by_status
    )


def find_conflicting_booking(db: Session, booking: VenueBooking) -> VenueBooking | None:
    """The existing APPROVED booking (if any) whose held period overlaps ``booking``'s.

    Two half-open periods [a, b) and [c, d) overlap iff a < d and c < b - the same test the
    database's exclusion constraint applies, so a booking that merely touches another at a
    boundary is not reported as a conflict (story 14.1 AC3).
    """
    return db.scalars(
        select(VenueBooking)
        .where(
            VenueBooking.venue_id == booking.venue_id,
            VenueBooking.status == BookingStatus.APPROVED,
            VenueBooking.id != booking.id,
            VenueBooking.held_from < booking.held_until,
            VenueBooking.held_until > booking.held_from,
        )
        .order_by(VenueBooking.held_from)
        .limit(1)
    ).first()


def get_booking(db: Session, booking_id: uuid.UUID) -> VenueBooking:
    """13.2 AC3: plain read, e.g. for the requesting coordinator to check the outcome."""
    booking = db.get(VenueBooking, booking_id)
    if booking is None:
        raise BookingNotFound(booking_id)
    return booking


def list_bookings_for_event(db: Session, event_id: uuid.UUID) -> list[VenueBooking]:
    """13.2.1 AC4: every venue booking ever raised for this event, most recent first - lets a
    coordinator read the full history directly on the event page without knowing any booking's
    id up front. An event may accumulate more than one row over time (a rejected request
    followed by a fresh one, possibly for a different venue), so this is a history, not a single
    outcome; deciding a booking updates that same row in place, it never creates a new one.
    ``id`` breaks a tie on ``created_at`` - two bookings inserted in the same statement or
    transaction (seed data, or two rapid test factory calls) can share one timestamp, which
    would otherwise leave their relative order undefined."""
    return list(
        db.scalars(
            select(VenueBooking)
            .where(VenueBooking.event_id == event_id)
            .options(joinedload(VenueBooking.venue))
            .order_by(VenueBooking.created_at.desc(), VenueBooking.id.desc())
        ).all()
    )


def get_booking_for_decision(db: Session, booking_id: uuid.UUID) -> VenueBooking:
    """Row-locked read for an approve/reject action - see the module docstring's concurrency
    note. Two simultaneous decisions on the same booking serialize on this lock instead of
    racing the write."""
    booking = db.scalar(select(VenueBooking).where(VenueBooking.id == booking_id).with_for_update())
    if booking is None:
        raise BookingNotFound(booking_id)
    return booking


def assert_no_conflict(db: Session, booking: VenueBooking) -> None:
    """Fast, friendly pre-check only - see the module docstring's "Race safety" note.

    Useful for a UI that wants to show an error before the user even submits, but
    ``approve_booking`` (not this) is what must actually guard an approval.
    """
    conflict = find_conflicting_booking(db, booking)
    if conflict is not None:
        raise BookingConflict(conflict)


def _notify_coordinator_of_decision(db: Session, booking: VenueBooking, *, actor: User) -> None:
    """Story 20.1 AC1/AC4: the event's coordinator - whoever holds the event now, not necessarily
    who asked - is told 13.2's approval with the held period, or 13.2.1's rejection with its
    reason."""
    venue_name, event = booking.venue.name, booking.event
    if booking.status == BookingStatus.REJECTED:
        notification_type = NotificationType.BOOKING_REJECTED
        title = f'{venue_name} rejected for "{event.name}"'
        message = (
            f"{actor.full_name} rejected the request for {venue_name}. "
            f"Reason: {booking.decision_reason}"
        )
    else:
        notification_type = NotificationType.BOOKING_APPROVED
        title = f'{venue_name} approved for "{event.name}"'
        period = _describe_held_period(booking.held_from, booking.held_until)
        message = f"{actor.full_name} approved the request for {venue_name} {period}."
    notify(
        db,
        recipient=event.assigned_coordinator,
        actor=actor,
        notification_type=notification_type,
        event_id=event.id,
        title=title,
        message=message,
        related_entity_type="venue_booking",
        related_entity_id=booking.id,
        commit=False,
    )


def approve_booking(db: Session, booking: VenueBooking, *, actor_id: uuid.UUID) -> None:
    """13.2 AC1: approve ``booking``, recording the approver and time. Refuses a request that
    is not PENDING (``BookingNotPending``) or whose period would double-book its venue
    (``BookingConflict``, AC4 / 14.2 AC1-AC2).

    Since the venue hold (migration 010) a pending request already holds its slot, so no other
    pending or approved booking can overlap it and the conflict branch below is a safety net
    that should never fire. Callers must fetch ``booking`` via ``get_booking_for_decision`` -
    see the module docstring's concurrency note.
    """
    if booking.status != BookingStatus.PENDING:
        raise BookingNotPending(booking, action="approved")

    booking.status = BookingStatus.APPROVED
    booking.decided_by_id = actor_id
    booking.decided_at = datetime.now(UTC)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _CONFLICT_CONSTRAINT not in str(exc.orig):
            raise
        conflict = find_conflicting_booking(db, booking)
        if conflict is None:
            raise
        raise BookingConflict(conflict) from exc

    actor = db.get(User, actor_id)
    _notify_coordinator_of_decision(db, booking, actor=actor)
    record_audit(
        db,
        actor=actor,
        action="BOOKING_APPROVED",
        entity_type="venue_booking",
        entity_id=booking.id,
        details={"venue_id": str(booking.venue_id), "event_id": str(booking.event_id)},
        commit=False,
    )
    db.commit()
    db.refresh(booking)


def reject_booking(
    db: Session, booking: VenueBooking, *, actor_id: uuid.UUID, decision_reason: str
) -> None:
    """13.2.1 AC1: reject ``booking``, recording the rejecter, time and reason. Refuses a
    request that is not PENDING (``BookingNotPending``).

    AC6: unlike ``approve_booking``, this can never trip the exclusion constraint - rejecting
    only takes a request out of the venue hold (12.1 AC4), so it cannot double-book anything and
    there is no conflict to translate. Callers must fetch ``booking`` via
    ``get_booking_for_decision`` - see the module docstring's concurrency note.
    """
    if booking.status != BookingStatus.PENDING:
        raise BookingNotPending(booking, action="rejected")

    booking.status = BookingStatus.REJECTED
    booking.decided_by_id = actor_id
    booking.decided_at = datetime.now(UTC)
    booking.decision_reason = decision_reason
    db.flush()

    actor = db.get(User, actor_id)
    _notify_coordinator_of_decision(db, booking, actor=actor)
    record_audit(
        db,
        actor=actor,
        action="BOOKING_REJECTED",
        entity_type="venue_booking",
        entity_id=booking.id,
        details={
            "venue_id": str(booking.venue_id),
            "event_id": str(booking.event_id),
            "reason": decision_reason,
        },
        commit=False,
    )
    db.commit()
    db.refresh(booking)


def _notify_venue_staff_of_request(
    db: Session,
    booking: VenueBooking,
    *,
    actor: User,
    held_from: datetime,
    held_until: datetime,
) -> None:
    """Story 20.1 AC1: a new request waits in the queue, so every active Venue Staff member is
    told the venue, the event and the held period - the audience 12.2's withdrawal tells. The held
    period is passed in, because the database trigger sets it on the row only."""
    venue_name = booking.venue.name
    message = (
        f'{actor.full_name} requested {venue_name} for "{booking.event.name}" '
        f"{_describe_held_period(held_from, held_until)}."
    )
    for member in active_members(db, role_code=RoleCode.VENUE_STAFF):
        notify(
            db,
            recipient=member,
            actor=actor,
            notification_type=NotificationType.BOOKING_REQUESTED,
            event_id=booking.event_id,
            title=f"New booking request for {venue_name}",
            message=message,
            related_entity_type="venue_booking",
            related_entity_id=booking.id,
            commit=False,
        )


def _notify_venue_staff_of_withdrawal(db: Session, booking: VenueBooking, *, actor: User) -> None:
    """12.2 AC2: every active Venue Staff member is told - the same role-wide, active-only
    audience ``list_booking_requests`` already serves for the queue itself."""
    for member in active_members(db, role_code=RoleCode.VENUE_STAFF):
        notify(
            db,
            recipient=member,
            actor=actor,
            notification_type=NotificationType.BOOKING_WITHDRAWN,
            event_id=booking.event_id,
            title="A venue booking request was withdrawn",
            message=f"The request for {booking.venue.name} was withdrawn and its hold released.",
            related_entity_type="venue_booking",
            related_entity_id=booking.id,
            commit=False,
        )


def withdraw_booking(db: Session, booking: VenueBooking, *, actor: User) -> None:
    """12.2 AC2/AC3: withdraw a pending request - the status change, hold release and
    notification all happen together, inside this one call.

    AC6: refused (``NotAssignedCoordinator``) unless ``actor`` is the coordinator currently
    assigned to the booking's event - a relationship rule, not a role check, since every
    coordinator holds ``bookings:request``.
    AC7: refused (``BookingNotPending``) unless the request is still PENDING.
    AC8: reuses the same ``SELECT ... FOR UPDATE`` row lock 13.2/13.2.1 already use for
    decide-vs-decide races - callers must fetch ``booking`` via ``get_booking_for_decision``, the
    same as ``approve_booking``/``reject_booking``, so a withdrawal racing a Venue Staff decision
    on the same request serializes on it exactly like two decisions already do.

    Releasing the hold is implicit: since s12.1 only a PENDING or APPROVED booking holds its
    venue, so flipping the status away from PENDING here is the release - there is no separate
    field to clear.
    """
    if booking.event.assigned_coordinator_id != actor.id:
        raise NotAssignedCoordinator(message=WITHDRAW_NOT_ASSIGNED_COORDINATOR_MESSAGE)
    if booking.status != BookingStatus.PENDING:
        raise BookingNotPending(booking, action="withdrawn")

    _mark_withdrawn(db, booking, actor=actor)
    db.commit()
    db.refresh(booking)


def _mark_withdrawn(db: Session, booking: VenueBooking, *, actor: User) -> None:
    """12.2 AC2/AC3: the withdrawal itself - the status, who withdrew it and when, the audit
    entry and Venue Staff's notice - flushed but not committed, so story 12.5's switch writes
    it in the same commit as the request that replaces it."""
    booking.status = BookingStatus.WITHDRAWN
    booking.decided_by_id = actor.id
    booking.decided_at = datetime.now(UTC)
    db.flush()

    record_audit(
        db,
        actor=actor,
        action="BOOKING_WITHDRAWN",
        entity_type="venue_booking",
        entity_id=booking.id,
        details={"venue_id": str(booking.venue_id), "event_id": str(booking.event_id)},
        commit=False,
    )
    _notify_venue_staff_of_withdrawal(db, booking, actor=actor)


# --- 12.1: raising a request ----------------------------------------------------------------
def list_reference_data(db: Session, *, actor: User) -> dict[str, list[Event]]:
    """AC1 and AC4 as a read: the events ``actor`` may raise a booking for, soonest first.

    The same two rules ``create_booking_request`` enforces, so the form cannot offer a choice
    the write would refuse. Story 5.3 owns the general "events assigned to me" list; this is
    narrower on purpose.
    """
    return {
        "events": list(
            db.scalars(
                select(Event)
                .where(
                    Event.assigned_coordinator_id == actor.id,
                    Event.status.in_(_BOOKABLE_EVENT_STATUSES),
                )
                .order_by(Event.starts_at, Event.id)
            ).all()
        )
    }


def _bookable_event(db: Session, event_id: uuid.UUID, *, actor: User) -> Event:
    """The event a request may be raised for, or the reason it may not be.

    AC1 is checked before AC4 on purpose: an event nobody can book is refused on its status
    whether or not the asker happens to be its coordinator.

    A bookable event always has its period and attendance recorded, so AC2 can copy them
    unconditionally: ``ck_events_submitted_fields_complete`` only lets a DRAFT row leave
    ``purpose`` / ``starts_at`` / ``ends_at`` / ``expected_attendance`` null, and DRAFT is
    not a bookable status.
    """
    event = db.get(Event, event_id)
    if event is None:
        raise EventNotFound(event_id)
    if event.status not in _BOOKABLE_EVENT_STATUSES:
        raise EventNotBookable(event)
    if event.assigned_coordinator_id != actor.id:
        raise NotAssignedCoordinator()
    return event


def _bookable_venue(db: Session, venue_id: uuid.UUID) -> Venue:
    venue = db.get(Venue, venue_id)
    if venue is None:
        raise VenueNotFound(venue_id)
    if venue.status != VenueStatus.ACTIVE:
        raise VenueNotBookable(venue)
    return venue


def _describe_facility(required: VenueRequirementFacility) -> str:
    """One facility as Venue Staff should read it: name, how many, and its own note.

    The quantity and note are the difference between "Breakout rooms" and "Breakout rooms ×3
    (HDMI input needed)" - without them the request understates what the venue has to provide.
    """
    described = required.facility.name
    if required.quantity is not None:
        described += FACILITY_QUANTITY_SUFFIX.format(quantity=required.quantity)
    notes = (required.notes or "").strip()
    if notes:
        described += FACILITY_NOTES_SUFFIX.format(notes=notes)
    return described


def _requirement_notes(db: Session, requirement: VenueRequirement | None) -> str | None:
    """12.1 AC2: the venue requirement's facilities, stated to Venue Staff by name rather than
    by code and with the quantity and note recorded against each, followed by its other
    requirements in free text.

    ``venue_bookings.requirement_notes`` is the field Venue Staff read ("required facilities and
    other requirements, as stated to Venue Staff"), and story 13.1 AC2 shows it on the queue.
    """
    if requirement is None:
        return None
    required_facilities = db.scalars(
        select(VenueRequirementFacility)
        .join(Facility, Facility.code == VenueRequirementFacility.facility_code)
        .where(VenueRequirementFacility.requirement_id == requirement.id)
        .order_by(Facility.sort_order, Facility.name)
    ).all()
    sentences = []
    if required_facilities:
        sentences.append(
            REQUIRED_FACILITIES_SENTENCE.format(
                facilities=", ".join(_describe_facility(each) for each in required_facilities)
            )
        )
    other_requirements = (requirement.notes or "").strip()
    if other_requirements:
        sentences.append(other_requirements)
    if not sentences:
        return None
    return "\n".join(sentences)


def _describe_held_period(held_from: datetime, held_until: datetime) -> str:
    """A held period in Singapore time, as a sentence ending: "on Wed 25 Nov 2026 from 08:00 to
    19:00", or with both dates when it runs over midnight."""
    start, end = held_from.astimezone(_SINGAPORE), held_until.astimezone(_SINGAPORE)
    if start.date() == end.date():
        return f"on {_describe_day(start)} from {start:%H:%M} to {end:%H:%M}"
    return f"from {_describe_day(start)}, {start:%H:%M} to {_describe_day(end)}, {end:%H:%M}"


def _describe_day(moment: datetime) -> str:
    """The day as Wed 25 Nov 2026: the day of the month unpadded, which strftime cannot do
    portably."""
    return f"{moment:%a} {moment.day} {moment:%b %Y}"


def find_holding_booking(
    db: Session, venue_id: uuid.UUID, held_from: datetime, held_until: datetime
) -> VenueBooking | None:
    """12.1 AC3: the pending or approved booking (if any) holding ``venue_id`` during part of
    ``held_from``..``held_until``. Half-open periods, as in the exclusion constraint: touching at
    a boundary is not an overlap (AC6); any partial overlap is (AC8)."""
    return db.scalars(
        select(VenueBooking)
        .options(joinedload(VenueBooking.venue), joinedload(VenueBooking.event))
        .where(
            VenueBooking.venue_id == venue_id,
            VenueBooking.status.in_(_HOLDING_STATUSES),
            VenueBooking.held_from < held_until,
            VenueBooking.held_until > held_from,
        )
        .order_by(VenueBooking.held_from, VenueBooking.id)
        .limit(1)
    ).first()


def _requested_requirement(
    event: Event, requirement_id: uuid.UUID | None
) -> VenueRequirement | None:
    """Story 12.5 AC1/AC11: the venue requirement a request names - one of ``event``'s, or
    ``RequirementNotOfEvent`` - or None, an additional venue."""
    if requirement_id is None:
        return None
    named = next((each for each in event.venue_requirements if each.id == requirement_id), None)
    if named is None:
        raise RequirementNotOfEvent()
    return named


def find_covering_booking(db: Session, requirement_id: uuid.UUID) -> VenueBooking | None:
    """Story 12.5 AC10/AC11: the pending or approved request a venue requirement already has,
    if any - one that was rejected, withdrawn or cancelled covers nothing (AC8)."""
    return db.scalar(
        select(VenueBooking).where(
            VenueBooking.venue_requirement_id == requirement_id,
            VenueBooking.status.in_(tuple(REQUIREMENT_ALREADY_REQUESTED_STATES)),
        )
    )


def create_booking_request(db: Session, data: BookingRequestIn, *, actor: User) -> VenueBooking:
    """12.1 AC1: raises one request, for one venue, from an approved event. AC2: the period,
    attendance, layout and required facilities are copied from the event. AC3: the row is
    PENDING and undecided, ready for Venue Staff, and holds the venue: a period overlapping a
    pending or approved booking of the same venue is refused (``VenueHeld``). AC4: refused unless
    ``actor`` is the event's assigned coordinator - checked first, so nobody else learns whether
    a slot is held.

    AC12/AC14: the hold check runs again inside the database. Two requests racing for one slot
    can both pass the check above; the exclusion constraint then makes the second write wait for
    the first and fail, and that failure becomes the same ``VenueHeld``.

    Story 12.1 AC14: the venue may have stopped being available since the catalogue search, so
    the search's other two rules are checked again after the hold - a closure overlapping the
    period (``VenueBlocked``) and opening hours that leave part of it out (``VenueClosed``).

    Story 11.1 AC2/AC7: then, after availability, whether the venue suits the event - judged as
    the venue and the event's requirement stand now, with the catalogue's own check. One that
    does not is refused without a justification (``JustificationRequired``); with one, the
    justification is stored. For a venue that suits, nothing is stored, even if one was sent
    (Q9). The audit entry records whether the check was overridden, never the text.

    Story 20.1 AC1: Venue Staff are told the request is waiting, once it is written - a refused
    request tells nobody (AC4).

    Story 12.5: the request names the venue requirement it is for - one of the event's
    (``RequirementNotOfEvent`` otherwise, AC11) with no pending or approved request yet
    (``RequirementAlreadyRequested``, AC11) - and carries that requirement's own terms and
    suitability (AC1, AC14); none is an additional venue. AC12: two requests for one requirement
    at once can both pass that check, and ``uq_venue_bookings_one_per_requirement`` then refuses
    the second, which becomes the same ``RequirementAlreadyRequested``.
    """
    event = _bookable_event(db, data.event_id, actor=actor)
    venue = _bookable_venue(db, data.venue_id)
    requirement = _requested_requirement(event, data.venue_requirement_id)
    return _request_venue(
        db, event, venue, requirement, data.suitability_override_reason, actor=actor
    )


def switch_booking_request(
    db: Session, replaced: VenueBooking, data: BookingSwitchIn, *, actor: User
) -> VenueBooking:
    """Story 12.5, decided 11 Oct 2026: switch the pending request ``replaced`` to another
    venue, for the same venue requirement (an additional venue stays one). Callers fetch
    ``replaced`` with ``get_booking_for_decision``, as 12.2's withdrawal does, so two tabs
    switching it at once wait on its row lock and the second finds it withdrawn.

    Withdrawal's checks come first: only the event's assigned coordinator
    (``NotAssignedCoordinator``, before anything about the request is said), and only while it
    is pending (``BookingNotPending``). Then the new venue is checked as any request is (12.1,
    11.1, 12.5), with the old request taken as released. Only when every check passes are the
    withdrawal and the new request written, in one commit, so a venue that cannot take the
    request leaves the old one as it was.
    """
    if replaced.event.assigned_coordinator_id != actor.id:
        raise NotAssignedCoordinator()
    if replaced.status != BookingStatus.PENDING:
        raise BookingNotPending(replaced, action="switched")
    event = _bookable_event(db, replaced.event_id, actor=actor)
    venue = _bookable_venue(db, data.venue_id)
    return _request_venue(
        db,
        event,
        venue,
        replaced.venue_requirement,
        data.suitability_override_reason,
        actor=actor,
        replacing=replaced,
    )


def _request_venue(
    db: Session,
    event: Event,
    venue: Venue,
    requirement: VenueRequirement | None,
    override_reason: str | None,
    *,
    actor: User,
    replacing: VenueBooking | None = None,
) -> VenueBooking:
    """The checks and the write ``create_booking_request`` and ``switch_booking_request``
    share, once the event, the venue and the requirement are known: the requirement's other
    request (story 12.5 AC11), the hold, closures and opening hours (12.1), suitability
    (11.1), then the row, Venue Staff's notice and the audit entry. ``replacing`` is the
    request a switch withdraws: it does not count as the requirement's request, and it is
    withdrawn only after every check has passed, in the same commit as the new request."""
    replacing_id = None if replacing is None else replacing.id
    if requirement is not None:
        covering = find_covering_booking(db, requirement.id)
        if covering is not None and covering.id != replacing_id:
            raise RequirementAlreadyRequested(requirement, covering)

    # The requirement's own terms, each falling back to the event's, which a submitted event
    # always has (ck_events_submitted_fields_complete), so the booking's NOT NULL period and
    # attendance are always filled; an additional venue carries the event's own.
    has_own_times = requirement is not None and requirement.starts_at is not None
    booking = VenueBooking(
        event_id=event.id,
        venue_id=venue.id,
        venue_requirement_id=None if requirement is None else requirement.id,
        requested_by_id=actor.id,
        starts_at=requirement.starts_at if has_own_times else event.starts_at,
        ends_at=requirement.ends_at if has_own_times else event.ends_at,
        expected_attendance=venue_service.people_to_hold(event, requirement),
        required_layout_code=requirement.layout_code if requirement else None,
        requirement_notes=_requirement_notes(db, requirement),
        status=BookingStatus.PENDING,
    )
    # The held period as the database trigger will compute it (setup and teardown default to 0).
    held_from = booking.starts_at - timedelta(minutes=booking.setup_minutes or 0)
    held_until = booking.ends_at + timedelta(minutes=booking.teardown_minutes or 0)
    holding = find_holding_booking(db, venue.id, held_from, held_until)
    if holding is not None:
        raise VenueHeld(holding)
    # The held period is the booking's own (story 12.5 AC1: its requirement's times, or the
    # event's for an additional venue) plus setup and teardown, which default to 0 (12.1 AC1).
    closure = venue_service.find_blocking_unavailability(
        db, venue.id, starts_at=held_from, ends_at=held_until
    )
    if closure is not None:
        raise VenueBlocked(venue, closure)
    if venue_service.closed_for(venue, starts_at=held_from, ends_at=held_until):
        raise VenueClosed(venue, starts_at=held_from, ends_at=held_until)
    # No EventNotJudgeable: only PLANNING/CONFIRMED events book, and the DB requires attendance.
    judged = venue_service.judge_venue_for_requirement(event, requirement, venue)
    if not judged.suitability.is_suitable and override_reason is None:
        raise JustificationRequired()
    booking.suitability_override_reason = (
        None if judged.suitability.is_suitable else override_reason
    )

    venue_id = venue.id
    requirement_id = None if requirement is None else requirement.id
    if replacing is not None:
        _mark_withdrawn(db, replacing, actor=actor)
    db.add(booking)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if requirement_id is not None and _ONE_PER_REQUIREMENT_INDEX in str(exc.orig):
            covering = find_covering_booking(db, requirement_id)
            if covering is None:
                raise
            named = db.get(VenueRequirement, requirement_id)
            raise RequirementAlreadyRequested(named, covering) from exc
        if _CONFLICT_CONSTRAINT not in str(exc.orig):
            raise
        holding = find_holding_booking(db, venue_id, held_from, held_until)
        if holding is None:
            raise
        raise VenueHeld(holding) from exc
    _notify_venue_staff_of_request(
        db, booking, actor=actor, held_from=held_from, held_until=held_until
    )
    details = {
        "event_id": str(event.id),
        "venue_id": str(venue.id),
        "venue_requirement_id": None if requirement_id is None else str(requirement_id),
        "suitability_overridden": booking.suitability_override_reason is not None,
    }
    if replacing_id is not None:
        details["replaces_booking_id"] = str(replacing_id)
    record_audit(
        db,
        actor=actor,
        action="BOOKING_REQUESTED",
        entity_type="venue_booking",
        entity_id=booking.id,
        details=details,
        commit=False,
    )
    db.commit()
    # held_from / held_until are set by a database trigger, so they are only on the object
    # after a reload - same reason tests/support/factories.py::make_booking refreshes.
    db.refresh(booking)
    return booking
