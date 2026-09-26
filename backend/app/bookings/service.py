"""Venue booking rules: raising a request (story 12.1) and conflict detection (story 14.2).

Story 12.1 - "As an Event Coordinator I want to request a venue booking for an event so
that Venue Staff can assess and confirm it":

* AC1 ``create_booking_request`` refuses an event that is not APPROVED or later, and takes
  exactly one ``venue_id``, so one request is one venue;
* AC2 the schedule, attendance, layout and required facilities are copied from the event
  row rather than taken from the request body - see ``_requirement_notes``;
* AC3 the row is written PENDING with no decision, which is what story 13.1's queue and
  story 13.2's ``approve_booking`` below both read;
* AC4 refused unless the actor is the event's ``assigned_coordinator_id``.

Setup and teardown minutes are left at the column default of 0, so the held period equals
the event period: recording them is story 12.2. Nothing here checks the requested period
against existing bookings either - warning the coordinator at submission time is story
14.1, and an overlapping PENDING row is harmless because the exclusion constraint and
``approve_booking`` below only treat APPROVED rows as occupying the venue.

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
(two overlapping requests could both pass the check before either commits). The database's
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
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth.models import User
from app.bookings.models import BookingStatus, VenueBooking
from app.bookings.schemas import BookingRequestIn
from app.common.audit import record_audit
from app.events.models import Event, EventRequiredFacility, EventStatus
from app.venues.models import Facility, Venue, VenueStatus

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

REQUIRED_FACILITIES_SENTENCE = "Required facilities: {facilities}."
# A facility may be needed in a quantity, with a note of its own ("3 breakout rooms, HDMI
# input needed"). Venue Staff read all of it as one sentence, so each is appended to the name.
FACILITY_QUANTITY_SUFFIX = " ×{quantity}"
FACILITY_NOTES_SUFFIX = " ({notes})"

# AC1 is worded "an approved event"; the schema's rule is approved *or later* (see the
# venue_bookings.event_id comment in 001_initial_schema.sql), because an event already in
# planning or confirmed may still need a further venue booked. Bug b6.1.1: APPROVED itself was
# retired (migration 002) - approving now goes straight to PLANNING, so that status alone covers
# what used to be "APPROVED or PLANNING".
_BOOKABLE_EVENT_STATUSES = frozenset({EventStatus.PLANNING, EventStatus.CONFIRMED})


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
    """12.1 AC4: only the event's assigned coordinator may raise its booking request.

    A relationship rule, not a role rule - every coordinator holds ``bookings:request``, so
    this needs the event row in hand and belongs here rather than in ``permissions.py``.
    """

    def __init__(self) -> None:
        super().__init__(NOT_ASSIGNED_COORDINATOR_MESSAGE)


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


def list_booking_requests(db: Session) -> list[VenueBooking]:
    """Story 13.1 AC1/AC3: every pending request, soonest first. AC1's "responsible for" is
    every venue: there is no per-venue staff responsibility table in the schema, and
    BOOKINGS_DECIDE is a role-wide permission today, same as VENUES_MANAGE."""
    return list(
        db.scalars(
            select(VenueBooking)
            .options(
                joinedload(VenueBooking.event),
                joinedload(VenueBooking.venue),
                joinedload(VenueBooking.requested_by),
                joinedload(VenueBooking.required_layout),
            )
            .where(VenueBooking.status == BookingStatus.PENDING)
            .order_by(VenueBooking.starts_at, VenueBooking.id)
        ).all()
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
    ``id`` breaks a tie on ``created_at`` - seed rows inserted by the same statement share one
    transaction timestamp, so ``created_at`` alone leaves their relative order undefined."""
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


def approve_booking(db: Session, booking: VenueBooking, *, actor_id: uuid.UUID) -> None:
    """13.2 AC1: approve ``booking``, recording the approver and time. Refuses a request that
    is not PENDING (``BookingNotPending``) or whose period would double-book its venue
    (``BookingConflict``, AC4 / 14.2 AC1-AC2).

    14.2 AC3 falls out of this for free: whichever of two overlapping PENDING requests is
    approved first wins; approving the second one then hits the conflict check below. Callers
    must fetch ``booking`` via ``get_booking_for_decision`` - see the module docstring's
    concurrency note.
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

    record_audit(
        db,
        actor=db.get(User, actor_id),
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

    AC6: unlike ``approve_booking``, this never touches the exclusion constraint - only
    APPROVED occupies the venue, so a rejection cannot double-book anything and there is no
    conflict to translate. Callers must fetch ``booking`` via ``get_booking_for_decision`` -
    see the module docstring's concurrency note.
    """
    if booking.status != BookingStatus.PENDING:
        raise BookingNotPending(booking, action="rejected")

    booking.status = BookingStatus.REJECTED
    booking.decided_by_id = actor_id
    booking.decided_at = datetime.now(UTC)
    booking.decision_reason = decision_reason
    db.flush()

    record_audit(
        db,
        actor=db.get(User, actor_id),
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


def _describe_facility(required: EventRequiredFacility) -> str:
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


def _requirement_notes(db: Session, event: Event) -> str | None:
    """12.1 AC2: the event's required facilities, stated to Venue Staff by name rather than
    by code and with the quantity and note recorded against each, followed by whatever the event
    recorded as its own venue requirements.

    ``venue_bookings.requirement_notes`` is the field Venue Staff read ("required facilities and
    other requirements, as stated to Venue Staff"), and story 13.1 AC2 shows it on the queue.
    """
    required_facilities = db.scalars(
        select(EventRequiredFacility)
        .join(Facility, Facility.code == EventRequiredFacility.facility_code)
        .where(EventRequiredFacility.event_id == event.id)
        .order_by(Facility.sort_order, Facility.name)
    ).all()
    sentences = []
    if required_facilities:
        sentences.append(
            REQUIRED_FACILITIES_SENTENCE.format(
                facilities=", ".join(_describe_facility(each) for each in required_facilities)
            )
        )
    event_notes = (event.venue_requirement_notes or "").strip()
    if event_notes:
        sentences.append(event_notes)
    if not sentences:
        return None
    return "\n".join(sentences)


def create_booking_request(db: Session, data: BookingRequestIn, *, actor: User) -> VenueBooking:
    """12.1 AC1: raises one request, for one venue, from an approved event. AC2: the period,
    attendance, layout and required facilities are copied from the event. AC3: the row is
    PENDING and undecided, ready for Venue Staff. AC4: refused unless ``actor`` is the event's
    assigned coordinator.
    """
    event = _bookable_event(db, data.event_id, actor=actor)
    venue = _bookable_venue(db, data.venue_id)

    booking = VenueBooking(
        event_id=event.id,
        venue_id=venue.id,
        requested_by_id=actor.id,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        expected_attendance=event.expected_attendance,
        required_layout_code=event.required_layout_code,
        requirement_notes=_requirement_notes(db, event),
        status=BookingStatus.PENDING,
    )
    db.add(booking)
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="BOOKING_REQUESTED",
        entity_type="venue_booking",
        entity_id=booking.id,
        details={"event_id": str(event.id), "venue_id": str(venue.id)},
        commit=False,
    )
    db.commit()
    # held_from / held_until are set by a database trigger, so they are only on the object
    # after a reload - same reason tests/support/factories.py::make_booking refreshes.
    db.refresh(booking)
    return booking
