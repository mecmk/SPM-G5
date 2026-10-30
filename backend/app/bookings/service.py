"""Venue booking rules: raising a request (story 12.1), conflict detection (story 14.2),
withdrawing a request (story 12.2), switching a requirement's pending request to another
venue (story 12.5, ``switch_booking_request``), and asking for a replacement of an approved
booking whose venue became unavailable (story 12.6, ``request_replacement_booking``).

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

Setup and teardown - Sprint 2's 12.1 AC1/AC5/AC9, built as f12.1.2: a request carries the setup
and teardown minutes sent with it - 0 when not sent, and whole minutes up to 14 days, which
``BookingRequestIn`` enforces (AC5) - and its held period is its own times widened by them, from
the setup before its start to the teardown after its end (AC1). A setup that would start that
period in the past is refused (``SetupStartsInThePast``, AC9) while the request's own start is
still ahead; once that has passed too, the refusal is 12.7's ``HoldPeriodStarted``. The
venue's opening hours are checked on the request's own times alone (12.1 AC16): its setup and
teardown may run outside them, for Venue Staff to weigh when they approve (Q28, Q51).

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

Story 12.6 - "Request a replacement venue for an affected booking": when Venue Staff close a venue
over an approved booking (9.4 marks it) the event's coordinator asks for another venue for the same
requirement, or, for an additional venue, the event's own period. ``request_replacement_booking``
raises a new PENDING request linked to the original by ``replaces_booking_id``; the original stays
approved, holding its venue, and the event is not touched (AC2, AC4). Approving the replacement
(``approve_booking``) releases the original in the same transaction - CANCELLED, with
``replaced_by_booking_id`` and a reason - only when it still holds its venue (AC3, AC6). The
one-per-requirement rule of 12.5 leaves out a pending replacement whose original still holds its
venue (``replaces_live_original``), which the database clears when the original stops holding by
any path, so the rule is otherwise as it was (AC10). Only the event's assigned coordinator, only
for an APPROVED booking still marked (AC9); one pending replacement per original (AC10).

Story 12.7 - "As a Venue Staff member I want every tentative venue hold to have an expiry date
and time", as the customer described the hold on 12 Oct 2026 (Q34, Q44, Q45, Q48, Q51): the hold
is an approved booking waiting for its event to be confirmed. Venue Staff set its expiry,
``hold_expires_at``, as they approve (``approve_booking``, AC1, AC5) - there is no default - and
may move it (``change_hold_expiry``, AC7, AC9), with a reason each time, kept on the booking with
who made the change and when (decided 12 Oct 2026, Q27-Q31). The coordinator confirming the event
completes it: migration 018's trigger sets ``hold_completed_at`` when the event becomes CONFIRMED
(AC4). A pending request still blocks its slot (12.1 AC3) but has no hold to expire.
``expire_lapsed_holds`` makes an approved booking whose open hold lapsed EXPIRED, which, like
REJECTED, holds nothing and covers no requirement (AC3, AC6, AC11), and tells its coordinator;
``remind_expiring_holds`` warns the coordinator once, a set time before (AC2). Both run together as
``sweep_holds``, on a timer while the API runs (``app/main.py``) and before any request whose answer
a lapsed hold would change (``app/bookings/deps.py``), so a hold is released at its expiry, not at
the next tick. Changing an expiry checks the row it locks as well, on its own clock: a hold that
lapsed since that sweep is expired there and then (AC7). Rows are taken ``FOR UPDATE SKIP LOCKED``,
so two sweeps never expire or warn about one booking twice, and the event's confirmation and the
expiry of one hold are serialized by the row lock (AC10).

Story 13.3 - "As a Venue Staff or Technical Support Staff member I want to search and sort the
requests in my queue so that I can find a particular request quickly and work through them in the
order I need": ``list_booking_requests`` searches the event name, the venue name and who submitted
the request, and orders by the offered ``BookingQueueOrder``, in the one statement that cuts the
page, so every page follows one order across the whole tab (AC4).
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, contains_eager, joinedload

from app.auth.models import User
from app.auth.permissions import RoleCode
from app.bookings.models import BookingStatus, ReleaseCause, VenueBooking
from app.bookings.schemas import (
    BookingQueueOrder,
    BookingReplacementIn,
    BookingRequestIn,
    BookingSwitchIn,
)
from app.common.audit import record_audit
from app.common.search import by_name, matches_any, search_term
from app.config import settings
from app.events import service as events_service
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

# Story 12.6 AC9: only the event's assigned coordinator asks for a replacement.
REPLACEMENT_NOT_ASSIGNED_COORDINATOR_MESSAGE = (
    "Only the coordinator assigned to this event can request a replacement for its booking."
)
# Story 12.6 AC9: only an approved booking that is still marked can be replaced. A pending one
# is switched to another venue (12.5); any other has nothing left to replace.
REPLACEMENT_FOR_PENDING_MESSAGE = (
    "This request is still pending, so choose another venue with Switch to this venue instead of "
    "asking for a replacement."
)
REPLACEMENT_FOR_CLOSED_MESSAGE = "This booking is {status}, so it cannot be replaced."
REPLACEMENT_FOR_UNMARKED_MESSAGE = (
    "This booking is no longer marked as having an unavailable venue, so it cannot be replaced."
)
# Story 12.6 AC10: never the venue being replaced, and one pending replacement per original.
REPLACEMENT_AT_ORIGINAL_VENUE_MESSAGE = (
    "A replacement cannot be at {venue}, the venue it replaces. Choose another venue."
)
REPLACEMENT_ALREADY_PENDING_MESSAGE = (
    "A replacement for this booking is already requested: {venue}. Withdraw it to choose "
    "another venue."
)
_ONE_PENDING_REPLACEMENT_INDEX = "uq_venue_bookings_one_pending_replacement"
# Story 12.6 AC10: 12.5's Switch would withdraw the replacement and ask for a normal request the
# original still blocks, so a pending replacement is withdrawn instead.
REPLACEMENT_CANNOT_BE_SWITCHED_MESSAGE = (
    "Withdraw the pending replacement first to choose another venue."
)
# Story 12.6 AC3: why an original released by its replacement is closed, as the queue and the
# booking's page word it.
REPLACED_BY_REASON = "Replaced by {venue}"
# Story 12.6 AC3: the sentence the coordinator's approval notice adds when it released the booking
# the approved replacement replaces - and does not, when there was nothing to release (AC3).
ORIGINAL_RELEASED_SENTENCE = "The booking of {venue} it replaces was released."
# Story 21.3 AC4: what Venue Staff are told when the Safety Officer's finding released a booking:
# the booked period (setup and teardown included, 12.1 AC1) and the finding's required change.
SAFETY_RELEASE_NOTICE = (
    'The booking of {venue} for "{event}" {period} was released by the safety review. '
    "Required change: {reason}"
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
    UnavailabilityReason.EQUIPMENT_FAILURE: " for equipment failure",
    UnavailabilityReason.RENOVATION: " for renovation",
    UnavailabilityReason.SAFETY: " for safety reasons",
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

# Story 12.1 AC9 (f12.1.2): a request whose setup would start its booked period in the past, while
# its own start is still ahead, is refused in words of its own; once that start has passed too,
# 12.7's sentence below is the one given.
SETUP_STARTS_IN_THE_PAST_MESSAGE = (
    "This setup would start in the past, so the venue cannot be held for it."
)
# Story 12.7 AC5: a hold expires in the future and no later than its booked period starts, so a
# request whose booked period has already started can be neither raised nor approved.
HOLD_PERIOD_STARTED_MESSAGE = (
    "This booked period has already started, so the venue cannot be held for it."
)
HOLD_EXPIRY_IN_PAST_MESSAGE = "The hold must expire in the future."
HOLD_EXPIRY_AFTER_START_MESSAGE = "The hold must expire by the start of the booked period, {start}."
# Story 12.7 AC7: only an approved booking's open hold takes a new expiry.
NO_HOLD_MESSAGE = "This request is {status}, so it has no hold to give a new expiry."
HOLD_COMPLETED_MESSAGE = (
    "This booking's hold was completed when its event was confirmed, so it has no expiry to change."
)
NO_HOLD_SINCE_APPROVAL_MESSAGE = (
    "This booking was approved before holds expired, so it has no expiry to change."
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

# Story 13.3 AC3: what each of the queue's orders sorts by first. Requests that tie are then put in
# date order, soonest first, and by id, so the pages cut from any order are stable (AC4).
_QUEUE_ORDERS = {
    BookingQueueOrder.DATE: VenueBooking.starts_at,
    BookingQueueOrder.DATE_DESC: VenueBooking.starts_at.desc(),
    BookingQueueOrder.REQUESTED: VenueBooking.created_at,
    BookingQueueOrder.REQUESTED_DESC: VenueBooking.created_at.desc(),
    BookingQueueOrder.EVENT_NAME: by_name(Event.name),
    BookingQueueOrder.VENUE_NAME: by_name(Venue.name),
}


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
    """12.1 AC14: the request's daily window falls outside the venue's opening hours - since
    f12.1.2 (12.1 AC16), the window of its own times, its requirement's or the event's, not of
    its booked period: setup and teardown may run outside the hours."""

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


class BookingNotReplaceable(ValueError):
    """Story 12.6 AC9: only an APPROVED booking still marked "Venue unavailable" can be replaced;
    the message says which it is not - pending (use Switch), closed, or no longer marked."""


class ReplacementAtOriginalVenue(ValueError):
    """Story 12.6 AC10: a replacement is never at the venue it replaces."""

    def __init__(self, venue: Venue) -> None:
        super().__init__(REPLACEMENT_AT_ORIGINAL_VENUE_MESSAGE.format(venue=venue.name))


class ReplacementAlreadyPending(ValueError):
    """Story 12.6 AC10: the original already has a pending replacement; the message names its
    venue."""

    def __init__(self, pending: VenueBooking) -> None:
        super().__init__(REPLACEMENT_ALREADY_PENDING_MESSAGE.format(venue=pending.venue.name))


class ReplacementCannotBeSwitched(ValueError):
    """Story 12.6 AC10: a pending replacement is withdrawn, not switched to another venue."""

    def __init__(self) -> None:
        super().__init__(REPLACEMENT_CANNOT_BE_SWITCHED_MESSAGE)


class JustificationRequired(ValueError):
    """Story 11.1 AC2/AC7: the venue does not suit the event and no justification was given."""

    def __init__(self) -> None:
        super().__init__(JUSTIFICATION_REQUIRED_MESSAGE)


class SetupStartsInThePast(ValueError):
    """Story 12.1 AC9 (f12.1.2): the setup would start the booked period in the past, while the
    request's own start is still ahead."""

    def __init__(self) -> None:
        super().__init__(SETUP_STARTS_IN_THE_PAST_MESSAGE)


class HoldPeriodStarted(ValueError):
    """Story 12.7 AC5: the booked period has already started, so no expiry could be both in the
    future and no later than its start."""

    def __init__(self) -> None:
        super().__init__(HOLD_PERIOD_STARTED_MESSAGE)


class InvalidHoldExpiry(ValueError):
    """Story 12.7 AC5: an expiry is not in the future, or is after the booked period starts; the
    message says which."""


class NoOpenHold(ValueError):
    """Story 12.7 AC7: the booking has no open hold whose expiry could change - it is not
    approved, its event's confirmation completed the hold, or it was approved before holds
    expired. The message says which."""


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


def _queue_rows(statement: Select, search: str | None) -> Select:
    """Story 13.3 AC2: ``statement`` joined to each request's event, venue and requester, and kept
    to the requests whose event name, venue name or requester's name contains ``search`` - every
    request, when there is no search (AC5)."""
    statement = (
        statement.join(VenueBooking.event).join(VenueBooking.venue).join(VenueBooking.requested_by)
    )
    term = search_term(search)
    if term is None:
        return statement
    return statement.where(matches_any(term, Event.name, Venue.name, User.full_name))


def list_booking_requests(
    db: Session,
    *,
    status: str | None = None,
    search: str | None = None,
    order: BookingQueueOrder = BookingQueueOrder.DATE,
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
    comes from the same per-status count, so it costs no query of its own.

    Story 13.3 AC1/AC2: ``search`` narrows every tab, and so every count, to the matching
    requests. AC3: ``order`` sorts them, ties falling back to soonest first. AC4: both are part of
    the statement the page is cut from, so a match on any page is found and the total counts only
    the matches."""
    page = (
        _queue_rows(select(VenueBooking), search)
        .options(
            contains_eager(VenueBooking.event),
            contains_eager(VenueBooking.venue),
            contains_eager(VenueBooking.requested_by),
            joinedload(VenueBooking.required_layout),
        )
        .order_by(_QUEUE_ORDERS[order], VenueBooking.starts_at, VenueBooking.id)
        .limit(limit)
        .offset(offset)
    )
    if status is not None:
        page = page.where(VenueBooking.status == status)
    counts_by_status = dict(
        db.execute(
            _queue_rows(select(VenueBooking.status, func.count()), search).group_by(
                VenueBooking.status
            )
        ).all()
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


def existing_booking_ids(db: Session, booking_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """The ids among ``booking_ids`` that ``get_booking`` would find, in one query (story 20.2's
    notification targets: a booking request page opens for any booking that exists)."""
    return set(db.scalars(select(VenueBooking.id).where(VenueBooking.id.in_(list(booking_ids)))))


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
            .options(
                joinedload(VenueBooking.venue), joinedload(VenueBooking.hold_expiry_changed_by)
            )
            .order_by(VenueBooking.created_at.desc(), VenueBooking.id.desc())
        ).all()
    )


def _notify_venue_staff_of_release(
    db: Session, booking: VenueBooking, *, actor: User, cause: str, because: str, reason: str
) -> None:
    """Story 19.2 AC5, story 6.2 AC5: every active Venue Staff member is told a booking was
    released, and ``because`` says why, as they are of a withdrawal (12.2 AC2), since their
    schedule changes with it. Story 21.3 AC4: a booking the safety review released is told with its
    booked period and the finding's required change, ``reason``."""
    if cause == ReleaseCause.SAFETY_REVIEW:
        message = SAFETY_RELEASE_NOTICE.format(
            venue=booking.venue.name,
            event=booking.event.name,
            period=_describe_held_period(booking.held_from, booking.held_until),
            reason=reason,
        )
    else:
        message = (
            f'The booking of {booking.venue.name} for "{booking.event.name}" was released: '
            f"{because}."
        )
    for member in active_members(db, role_code=RoleCode.VENUE_STAFF):
        notify(
            db,
            recipient=member,
            actor=actor,
            notification_type=NotificationType.BOOKING_RELEASED,
            event_id=booking.event_id,
            title="A venue booking was released",
            message=message,
            related_entity_type="venue_booking",
            related_entity_id=booking.id,
            commit=False,
        )


def _notify_venue_staff_of_replacement(
    db: Session, original: VenueBooking, replacement: VenueBooking, *, actor: User
) -> None:
    """Story 12.6 AC3: every other active Venue Staff member is told the booking was released
    because its replacement was approved - the person who approved it is not (20.1 AC3). The
    organiser is not told."""
    for member in active_members(db, role_code=RoleCode.VENUE_STAFF):
        notify(
            db,
            recipient=member,
            actor=actor,
            notification_type=NotificationType.BOOKING_REPLACED,
            event_id=original.event_id,
            title=f"A booking of {original.venue.name} was released",
            message=(
                f'The booking of {original.venue.name} for "{original.event.name}" was released: '
                f"{replacement.venue.name} was approved as its replacement."
            ),
            related_entity_type="venue_booking",
            related_entity_id=original.id,
            commit=False,
        )


def release_booking(
    db: Session,
    booking: VenueBooking,
    *,
    actor: User,
    cause: str,
    reason: str | None = None,
    because: str | None = None,
    details: dict[str, str] | None = None,
    at: datetime | None = None,
    replacement: VenueBooking | None = None,
) -> bool:
    """Releases ``booking``, cancelling it so its venue is free, and tells Venue Staff - the one
    release every story makes. Who approved it and when stay on the record. The update is
    conditional on the booking still holding its venue, so one Venue Staff rejected, or the sweep
    expired, meanwhile is left alone; returns whether it was released. Written, not committed:
    the caller commits.

    Story 21.3: ``cause`` (``ReleaseCause``) says which path released it, and with ``actor`` and
    ``reason`` it is recorded on the booking beside the status. Every path names its own, with no
    default: 6.2 EVENT_CANCELLED, 19.2 CHANGE_APPROVED, 12.6 REPLACED, 21.3 SAFETY_REVIEW, which
    takes ``reason`` (the finding's required change) for its notice and its record instead of
    ``because``.

    Story 19.2 AC5: an approved change to its event no longer fits ``booking``; story 6.2 AC2: its
    event was cancelled. Either way Venue Staff are told ``because``, the clause that ends their
    notice; ``details`` join the venue and event in the ``BOOKING_RELEASED`` audit entry, and
    ``at`` is recorded as when it was cancelled (6.2 AC16).

    Story 12.6 AC3: ``replacement`` is the booking whose approval releases it - the original is
    closed "Replaced by <venue>" and linked to it (``replaced_by_booking_id``, which is how an
    original's ``released_at`` is read), audited ``BOOKING_REPLACED``, Venue Staff told which
    venue replaced it.

    What a path gives: a replacement, for REPLACED and only for it; ``reason`` and ``at``, for a
    safety release (21.3 AC2); ``because`` and ``at``, for any other cause."""
    if (cause == ReleaseCause.REPLACED) != (replacement is not None):
        raise ValueError("release_booking takes a replacement for REPLACED, and only for it.")
    if replacement is None and at is None:
        raise ValueError("release_booking needs the time of a release that has no replacement.")
    if cause == ReleaseCause.SAFETY_REVIEW:
        if reason is None:
            raise ValueError("release_booking needs the required change of a safety release.")
    elif cause != ReleaseCause.REPLACED and because is None:
        raise ValueError("release_booking needs the clause its notice ends with.")
    values: dict[str, object] = {
        "status": BookingStatus.CANCELLED,
        "release_cause": cause,
        "release_reason": reason,
        "released_by_id": actor.id,
    }
    if replacement is not None:
        values["decision_reason"] = REPLACED_BY_REASON.format(venue=replacement.venue.name)
        values["replaced_by_booking_id"] = replacement.id
    else:
        values["cancelled_at"] = at
    # Story 21.3 AC7: the safety review releases an approved booking only, never a pending one.
    releasable = (
        (BookingStatus.APPROVED,) if cause == ReleaseCause.SAFETY_REVIEW else _HOLDING_STATUSES
    )
    released = db.execute(
        update(VenueBooking)
        .where(VenueBooking.id == booking.id, VenueBooking.status.in_(releasable))
        .values(**values)
    )
    if released.rowcount == 0:
        return False
    db.refresh(booking)
    base_details = {"venue_id": str(booking.venue_id), "event_id": str(booking.event_id)}
    if replacement is not None:
        record_audit(
            db,
            actor=actor,
            action="BOOKING_REPLACED",
            entity_type="venue_booking",
            entity_id=booking.id,
            details={**base_details, "replaced_by_booking_id": str(replacement.id)},
            commit=False,
        )
        _notify_venue_staff_of_replacement(db, booking, replacement, actor=actor)
        return True
    record_audit(
        db,
        actor=actor,
        action="BOOKING_RELEASED",
        entity_type="venue_booking",
        entity_id=booking.id,
        details={**base_details, **(details or {})},
        commit=False,
    )
    _notify_venue_staff_of_release(
        db, booking, actor=actor, cause=cause, because=str(because), reason=str(reason)
    )
    return True


def lock_holding_bookings(db: Session, event_id: uuid.UUID) -> list[VenueBooking]:
    """Story 6.2 AC2/AC12: the event's pending and approved bookings, each row locked until the
    transaction ends and read as it now stands, in id order, as story 9.4's re-check takes them.
    A Venue Staff decision holding one is waited for, so the booking is released as it lands."""
    return list(
        db.scalars(
            select(VenueBooking)
            .where(
                VenueBooking.event_id == event_id,
                VenueBooking.status.in_(_HOLDING_STATUSES),
            )
            .order_by(VenueBooking.id)
            .with_for_update(of=VenueBooking)
            .execution_options(populate_existing=True)
        )
    )


def lock_named_bookings(
    db: Session, event_id: uuid.UUID, booking_ids: Collection[uuid.UUID]
) -> list[VenueBooking]:
    """Story 21.3 AC11: the bookings of ``event_id`` among ``booking_ids``, whatever their status,
    each row locked until the transaction ends and read as it now stands, in id order, as
    ``lock_holding_bookings`` takes the event's holding ones. A booking another transaction holds
    - Venue Staff deciding it, the sweep expiring it - is waited for. An id that is not returned
    is not a booking of this event."""
    return list(
        db.scalars(
            select(VenueBooking)
            .where(VenueBooking.event_id == event_id, VenueBooking.id.in_(list(booking_ids)))
            .order_by(VenueBooking.id)
            .with_for_update(of=VenueBooking)
            .execution_options(populate_existing=True)
        )
    )


def get_booking_for_switch(db: Session, booking_id: uuid.UUID) -> VenueBooking:
    """Story 12.5's switch, row-locked as ``get_booking_for_decision`` locks it, with its event
    locked first. The switch requests another venue for the event, so it must read the event under
    lock (``_bookable_event``); taking the event before the booking, as story 6.2's cancellation
    and story 9.4's re-check do, means the two can never each hold what the other waits for."""
    event_id = db.scalar(select(VenueBooking.event_id).where(VenueBooking.id == booking_id))
    if event_id is None:
        raise BookingNotFound(booking_id)
    db.execute(select(Event.id).where(Event.id == event_id).with_for_update(key_share=True))
    return get_booking_for_decision(db, booking_id)


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


def _notify_coordinator_of_decision(
    db: Session, booking: VenueBooking, *, actor: User, released: VenueBooking | None = None
) -> None:
    """Story 20.1 AC1/AC4: the event's coordinator - whoever holds the event now, not necessarily
    who asked - is told 13.2's approval with the held period, or 13.2.1's rejection with its
    reason. Story 12.6 AC3: the approval of a replacement also says the booking it replaces,
    ``released``, was released - and nothing of the kind when it was not (AC3)."""
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
        # Story 12.7 AC1 (R13): the approval starts the hold, so the coordinator is told its
        # expiry and that the event must be confirmed by then - unless the event already is (AC4).
        if booking.hold_completed_at is None:
            message += (
                f" It is held for the event until {_describe_moment(booking.hold_expires_at)}: if "
                "the event is not confirmed by then, the hold expires and the venue is released."
            )
        if released is not None:
            message += " " + ORIGINAL_RELEASED_SENTENCE.format(venue=released.venue.name)
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


def get_booking_for_approval(db: Session, booking_id: uuid.UUID) -> VenueBooking:
    """Story 12.6 AC3: the row-locked read of ``get_booking_for_decision`` for an approval, which
    may release another booking. The booking is read unlocked to find the one it replaces; the
    original is locked first and the replacement second, and both are read afresh, so the status
    and the link are the committed ones whichever lock was waited for. That is the order the
    paths that close the original take among the two bookings (the hold sweep, 19.2's release),
    where the trigger then updates the replacement; taking them in id order instead could
    deadlock with them. 19.2's decision locks the event before either, which approval does not
    take: it locks no event row itself."""
    booking = db.get(VenueBooking, booking_id)
    if booking is None:
        raise BookingNotFound(booking_id)
    if booking.replaces_booking_id is not None:
        db.scalar(
            select(VenueBooking.id)
            .where(VenueBooking.id == booking.replaces_booking_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return db.scalars(
        select(VenueBooking)
        .where(VenueBooking.id == booking_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()


def _release_replaced_booking(
    db: Session, replacement: VenueBooking, *, actor: User
) -> VenueBooking | None:
    """Story 12.6 AC3: approving ``replacement`` releases the booking it replaces, through the one
    ``release_booking``. The original was locked with the replacement by
    ``get_booking_for_approval`` and is read afresh; it is released only while it still holds its
    venue, so one that expired or was cancelled meanwhile is left alone (AC3). Returns the
    booking it released, or None when it released nothing."""
    if replacement.replaces_booking_id is None:
        return None
    original = db.get(VenueBooking, replacement.replaces_booking_id)
    if original is None or not release_booking(
        db, original, actor=actor, cause=ReleaseCause.REPLACED, replacement=replacement
    ):
        return None
    return original


def approve_booking(
    db: Session,
    booking: VenueBooking,
    *,
    actor_id: uuid.UUID,
    hold_expires_at: datetime,
) -> None:
    """13.2 AC1: approve ``booking``, recording the approver and time. Refuses a request that
    is not PENDING (``BookingNotPending``), whose venue is unavailable for part of its held period
    (``VenueBlocked``, story 9.4 AC7: the same refusal the request step gives, read in a query of
    its own once the row is locked so a period saved a moment ago is seen, and from the live
    periods, not the mark) or whose period would double-book its venue (``BookingConflict``,
    AC4 / 14.2 AC1-AC2). The refusals come in that order, then the hold's own (12.7 AC5).

    Since the venue hold (migration 010) a pending request already holds its slot, so no other
    pending or approved booking can overlap it and the conflict branch below is a safety net
    that should never fire. Callers must fetch ``booking`` via ``get_booking_for_decision`` -
    see the module docstring's concurrency note.

    Story 12.7 AC1/AC5 (the customer's hold, 12 Oct 2026): approval starts the booking's
    tentative hold, which expires at ``hold_expires_at`` unless the event is confirmed first. A
    booked period that has started can no longer be held (``HoldPeriodStarted``), and the expiry
    must be in the future and no later than the booked start (``InvalidHoldExpiry``). AC2: an
    expiry inside the warning period counts as warned, since the approval notice names it. AC4
    (review of #103): for an event already Confirmed - an extra venue - there is no confirmation
    left to wait for, and migration 018's trigger fires only as an event becomes Confirmed, so the
    approval completes the hold itself.

    Story 12.6 AC3: approving a replacement releases the booking it replaces in this same
    transaction, after every refusal above and before the replacement is written approved, so the
    one-per-requirement index never sees two live bookings; a refusal after it (the write's own
    conflict) rolls the release back with everything else. AC3: when that booking no longer holds
    its venue nothing is released, and the approval says nothing of one. Callers fetch a
    replacement with ``get_booking_for_approval``.
    """
    moment = datetime.now(UTC)
    if booking.status != BookingStatus.PENDING:
        raise BookingNotPending(booking, action="approved")
    closure = venue_service.find_blocking_unavailability(
        db, booking.venue_id, starts_at=booking.held_from, ends_at=booking.held_until
    )
    if closure is not None:
        raise VenueBlocked(booking.venue, closure)
    if booking.held_from <= moment:
        raise HoldPeriodStarted()
    _check_hold_expiry(booking, hold_expires_at, now=moment)

    actor = db.get(User, actor_id)
    released = _release_replaced_booking(db, booking, actor=actor)
    booking.status = BookingStatus.APPROVED
    booking.decided_by_id = actor_id
    booking.decided_at = moment
    booking.hold_expires_at = hold_expires_at
    if booking.event.status == EventStatus.CONFIRMED:
        booking.hold_completed_at = moment
    else:
        booking.hold_reminded_at = (
            moment if _is_inside_warning(hold_expires_at, now=moment) else None
        )
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

    _notify_coordinator_of_decision(db, booking, actor=actor, released=released)
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
    replaces: VenueBooking | None = None,
) -> None:
    """Story 20.1 AC1: a new request waits in the queue, so every active Venue Staff member is
    told the venue, the event and the held period - the audience 12.2's withdrawal tells. The held
    period is passed in, because the database trigger sets it on the row only. Story 12.6 AC2: a
    replacement says so, and which booking it is for."""
    venue_name = booking.venue.name
    message = (
        f'{actor.full_name} requested {venue_name} for "{booking.event.name}" '
        f"{_describe_held_period(held_from, held_until)}."
    )
    if replaces is not None:
        message += (
            f" It is a replacement for the booking of {replaces.venue.name}, whose venue is "
            "unavailable."
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

    Story 6.2 AC12: the event's row is held until the transaction ends and read as it now stands,
    ``FOR NO KEY UPDATE`` as the cancellation takes it, so a request racing a cancellation waits
    for it and is then refused, rather than leaving a new hold on a cancelled event.
    """
    event = events_service.lock_event(db, event_id)
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


def earliest_setup_start(db: Session, event_id: uuid.UUID) -> datetime | None:
    """When set-up begins at the first of ``event_id``'s venues: the earliest ``held_from`` - the
    booking's start less its set-up minutes (12.1 AC1) - among its bookings that hold a venue,
    pending or approved (12.1 AC3). None when no venue is held. Story 19.1 AC12 closes change
    requests 24 hours before it (fix f19.1.1)."""
    return db.scalar(
        select(func.min(VenueBooking.held_from)).where(
            VenueBooking.event_id == event_id, VenueBooking.status.in_(_HOLDING_STATUSES)
        )
    )


def find_holding_booking(
    db: Session,
    venue_id: uuid.UUID,
    held_from: datetime,
    held_until: datetime,
    *,
    exclude_ids: Collection[uuid.UUID] = (),
) -> VenueBooking | None:
    """12.1 AC3: the pending or approved booking (if any) holding ``venue_id`` during part of
    ``held_from``..``held_until``. Half-open periods, as in the exclusion constraint: touching at
    a boundary is not an overlap (AC6); any partial overlap is (AC8). Story 19.3:
    ``exclude_ids`` leaves out bookings an approval would release, which hold nothing after it."""
    query = (
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
    )
    if exclude_ids:
        query = query.where(VenueBooking.id.not_in(exclude_ids))
    return db.scalars(query).first()


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
    if any - one that was rejected, withdrawn or cancelled covers nothing (AC8).

    Story 12.6 AC10: a pending replacement whose original still holds its venue covers nothing
    either - the original does - exactly as ``uq_venue_bookings_one_per_requirement`` leaves it
    out. Once the original stops holding, the database clears the flag and the replacement is the
    requirement's request."""
    return db.scalar(
        select(VenueBooking).where(
            VenueBooking.venue_requirement_id == requirement_id,
            VenueBooking.status.in_(tuple(REQUIREMENT_ALREADY_REQUESTED_STATES)),
            or_(
                VenueBooking.status != BookingStatus.PENDING,
                VenueBooking.replaces_live_original.is_(False),
            ),
        )
    )


def find_pending_replacement(db: Session, original_id: uuid.UUID) -> VenueBooking | None:
    """Story 12.6 AC10: the pending replacement asked for ``original_id``, if any."""
    return db.scalar(
        select(VenueBooking)
        .options(joinedload(VenueBooking.venue))
        .where(
            VenueBooking.replaces_booking_id == original_id,
            VenueBooking.status == BookingStatus.PENDING,
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
    booked period (``VenueBlocked``) and opening hours that leave out part of the request's own
    times (``VenueClosed``; f12.1.2, AC16).

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

    f12.1.2 (story 12.1 AC1/AC5 in the backlog's current numbering): the request carries the
    setup and teardown sent with it, and its booked period is its own times widened by them, from
    the setup before its start to the teardown after its end. That is the period it holds, and
    the one the hold and closure checks above are made on. AC16: the opening hours are checked
    on its own times alone, since its setup and teardown may run outside them, for Venue Staff
    to weigh when they approve (Q28, Q51).

    Story 12.7: lapsed holds are expired first, so one never blocks the request (AC3, AC6, AC11).
    A booked period that has already started is refused: the request could never be approved,
    since its hold would need an expiry before that start (AC5). The refusal is
    ``HoldPeriodStarted``, or 12.1 AC9's ``SetupStartsInThePast`` (f12.1.2) when only the setup
    would start in the past, the request's own start still ahead.
    """
    now = datetime.now(UTC)
    expire_lapsed_holds(db, now=now)
    event = _bookable_event(db, data.event_id, actor=actor)
    venue = _bookable_venue(db, data.venue_id)
    requirement = _requested_requirement(event, data.venue_requirement_id)
    return _request_venue(
        db,
        event,
        venue,
        requirement,
        data.suitability_override_reason,
        setup_minutes=data.setup_minutes,
        teardown_minutes=data.teardown_minutes,
        actor=actor,
        now=now,
    )


def switch_booking_request(
    db: Session, replaced: VenueBooking, data: BookingSwitchIn, *, actor: User
) -> VenueBooking:
    """Story 12.5, decided 11 Oct 2026: switch the pending request ``replaced`` to another
    venue, for the same venue requirement (an additional venue stays one). Callers fetch
    ``replaced`` with ``get_booking_for_switch``, which locks it as 12.2's withdrawal does, so two
    tabs switching it at once wait on its row lock and the second finds it withdrawn; its event is
    locked first, so a cancellation (story 6.2) is waited for, not raced.

    Withdrawal's checks come first: only the event's assigned coordinator
    (``NotAssignedCoordinator``, before anything about the request is said), and only while it
    is pending (``BookingNotPending``). Then the new venue is checked as any request is (12.1,
    11.1, 12.5), with the old request taken as released. Only when every check passes are the
    withdrawal and the new request written, in one commit, so a venue that cannot take the
    request leaves the old one as it was.

    f12.1.2 (story 12.1 AC1/AC5): the new request carries the setup and teardown sent with the
    switch - 0 when none is sent, never the replaced request's - and its booked period is its own
    times widened by them.

    Story 12.7 (Q26): the new request is refused, as any new request is, when its booked period
    has started - with 12.1 AC9's ``SetupStartsInThePast`` (f12.1.2) when only its setup would
    start in the past.
    """
    if replaced.event.assigned_coordinator_id != actor.id:
        raise NotAssignedCoordinator()
    if replaced.status == BookingStatus.PENDING and replaced.replaces_booking_id is not None:
        # Story 12.6 AC10: the original still blocks the requirement a normal request would take.
        raise ReplacementCannotBeSwitched()
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
        setup_minutes=data.setup_minutes,
        teardown_minutes=data.teardown_minutes,
        actor=actor,
        replacing=replaced,
        now=datetime.now(UTC),
    )


def _assert_replaceable(original: VenueBooking) -> None:
    """Story 12.6 AC9: only an APPROVED booking still marked "Venue unavailable" is replaced. A
    pending one is switched (12.5), a closed one has nothing to replace, and one whose mark has
    cleared (9.4 AC6) is no longer affected. The mark is read as readers see it: a value left on
    a closed booking is history."""
    if original.status == BookingStatus.PENDING:
        raise BookingNotReplaceable(REPLACEMENT_FOR_PENDING_MESSAGE)
    if original.status != BookingStatus.APPROVED:
        raise BookingNotReplaceable(REPLACEMENT_FOR_CLOSED_MESSAGE.format(status=original.status))
    if original.venue_unavailable_mark is None:
        raise BookingNotReplaceable(REPLACEMENT_FOR_UNMARKED_MESSAGE)


def request_replacement_booking(
    db: Session, original: VenueBooking, data: BookingReplacementIn, *, actor: User
) -> VenueBooking:
    """Story 12.6 AC2: raise a PENDING request for another venue, linked to ``original`` as its
    replacement. The event's details, status and other bookings are not touched (AC2); the
    original stays approved and on record until the replacement is approved (AC4). The period,
    attendance, layout and facilities are the requirement's - or, for an additional venue, the
    event's - as for any request; the setup and teardown are the original's unless ``data`` sends
    its own. Callers fetch ``original`` with ``get_booking_for_decision``, so two tabs asking at
    once wait on its row lock, and a closure ending beside this request is serialised with it.

    Refusals come in this order: not the event's assigned coordinator (``NotAssignedCoordinator``,
    before anything about the booking is said, AC9); an event that takes no booking, a cancelled
    one included (``EventNotBookable``, AC8); a booking that is not an approved, still marked one
    (``BookingNotReplaceable``, AC9); an unknown or withdrawn venue; the original's own venue
    (``ReplacementAtOriginalVenue``); then every check a new request meets (12.1, 11.1; 12.5's
    one-per-requirement leaves the original out), and the insert itself, where the database's
    one-pending-replacement index refuses a second one (``ReplacementAlreadyPending``, naming the
    venue already requested, AC10) - attempted, not looked for first."""
    if original.event.assigned_coordinator_id != actor.id:
        raise NotAssignedCoordinator(message=REPLACEMENT_NOT_ASSIGNED_COORDINATOR_MESSAGE)
    event = _bookable_event(db, original.event_id, actor=actor)
    _assert_replaceable(original)
    venue = _bookable_venue(db, data.venue_id)
    if venue.id == original.venue_id:
        raise ReplacementAtOriginalVenue(venue)
    return _request_venue(
        db,
        event,
        venue,
        original.venue_requirement,
        data.suitability_override_reason,
        setup_minutes=(
            original.setup_minutes if data.setup_minutes is None else data.setup_minutes
        ),
        teardown_minutes=(
            original.teardown_minutes if data.teardown_minutes is None else data.teardown_minutes
        ),
        actor=actor,
        replaces=original,
        now=datetime.now(UTC),
    )


def _request_venue(
    db: Session,
    event: Event,
    venue: Venue,
    requirement: VenueRequirement | None,
    override_reason: str | None,
    *,
    setup_minutes: int,
    teardown_minutes: int,
    actor: User,
    replacing: VenueBooking | None = None,
    replaces: VenueBooking | None = None,
    now: datetime,
) -> VenueBooking:
    """The checks and the write ``create_booking_request`` and ``switch_booking_request``
    share, once the event, the venue and the requirement are known: the requirement's other
    request (story 12.5 AC11), the hold, closures and opening hours (12.1), suitability
    (11.1), then the row, Venue Staff's notice and the audit entry. ``replacing`` is the
    request a switch withdraws: it does not count as the requirement's request, and it is
    withdrawn only after every check has passed, in the same commit as the new request.

    f12.1.2 (story 12.1 AC1/AC5): ``setup_minutes`` and ``teardown_minutes`` are stored on the
    row, and the booked period - held, and checked for holds and closures - is the booking's
    own times widened by them, from the setup before its start to the teardown after its end.
    AC16: the venue's opening hours are checked on the booking's own times alone.

    Story 12.7 AC5: a booked period that has already started by ``now``, the moment the caller
    acts on, cannot be held, so the request is refused (``HoldPeriodStarted``). 12.1 AC9
    (f12.1.2): when only its setup would start in the past, the booking's own start still ahead,
    the refusal is ``SetupStartsInThePast`` instead.

    Story 12.6 AC2: ``replaces`` is the approved booking this request asks to replace. The
    original still holds the requirement, so it is not a reason to refuse; the row is written
    linked to it, with ``replaces_live_original`` set so the one-per-requirement index leaves it
    out while it is pending. One pending replacement per original (AC10) is caught after the
    insert as ``uq_venue_bookings_one_pending_replacement``. Venue Staff are told it is a
    replacement."""
    replacing_id = None if replacing is None else replacing.id
    replaces_id = None if replaces is None else replaces.id
    if requirement is not None:
        covering = find_covering_booking(db, requirement.id)
        if covering is not None and covering.id not in (replacing_id, replaces_id):
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
        setup_minutes=setup_minutes,
        teardown_minutes=teardown_minutes,
        expected_attendance=venue_service.people_to_hold(event, requirement),
        required_layout_code=requirement.layout_code if requirement else None,
        requirement_notes=_requirement_notes(db, requirement),
        status=BookingStatus.PENDING,
        replaces_booking_id=replaces_id,
        replaces_live_original=replaces is not None,
    )
    # The held period as the database trigger will compute it: the booking's own times widened by
    # the setup and teardown sent with the request (12.1 AC1).
    held_from = booking.starts_at - timedelta(minutes=booking.setup_minutes)
    held_until = booking.ends_at + timedelta(minutes=booking.teardown_minutes)
    if held_from <= now:
        # 12.1 AC9: only the setup would start in the past, so it has its own refusal; a booked
        # period whose own start has passed too is 12.7's.
        if booking.starts_at > now:
            raise SetupStartsInThePast()
        raise HoldPeriodStarted()
    holding = find_holding_booking(db, venue.id, held_from, held_until)
    if holding is not None:
        raise VenueHeld(holding)
    # A closure is checked on the booked period, setup and teardown included (12.1 AC14), as the
    # hold is.
    closure = venue_service.find_blocking_unavailability(
        db, venue.id, starts_at=held_from, ends_at=held_until
    )
    if closure is not None:
        raise VenueBlocked(venue, closure)
    # The opening hours on the booking's own times alone (story 12.5 AC1: its requirement's, or
    # the event's for an additional venue): its setup and teardown may run outside them, for
    # Venue Staff to weigh when they approve (f12.1.2, 12.1 AC16; Q28, Q51).
    if venue_service.closed_for(venue, starts_at=booking.starts_at, ends_at=booking.ends_at):
        raise VenueClosed(venue, starts_at=booking.starts_at, ends_at=booking.ends_at)
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
        if replaces_id is not None and _ONE_PENDING_REPLACEMENT_INDEX in str(exc.orig):
            pending = find_pending_replacement(db, replaces_id)
            if pending is None:
                raise
            raise ReplacementAlreadyPending(pending) from exc
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
        db, booking, actor=actor, held_from=held_from, held_until=held_until, replaces=replaces
    )
    details = {
        "event_id": str(event.id),
        "venue_id": str(venue.id),
        "venue_requirement_id": None if requirement_id is None else str(requirement_id),
        "suitability_overridden": booking.suitability_override_reason is not None,
    }
    if replacing_id is not None:
        details["replaces_booking_id"] = str(replacing_id)
    if replaces_id is not None:
        details["replaces_booking_id"] = str(replaces_id)
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


# --- 12.7: tentative holds expire ---------------------------------------------------------------
def _describe_moment(moment: datetime) -> str:
    """A moment in Singapore time, as "Fri 4 Dec 2026 at 10:00"."""
    local = moment.astimezone(_SINGAPORE)
    return f"{_describe_day(local)} at {local:%H:%M}"


def _reminder_lead() -> timedelta:
    """Story 12.7 AC2: how long before a hold expires its coordinator is warned."""
    return timedelta(hours=settings.hold_expiry_reminder_hours)


def _is_inside_warning(hold_expires_at: datetime, *, now: datetime) -> bool:
    """Story 12.7 AC2: whether a hold expiring at ``hold_expires_at`` is already within the
    warning period at ``now`` - an approval or a change that sets it there names the expiry, which
    counts as the warning (Q21, R6)."""
    return hold_expires_at - _reminder_lead() <= now


def _check_hold_expiry(booking: VenueBooking, hold_expires_at: datetime, *, now: datetime) -> None:
    """Story 12.7 AC5: an expiry Venue Staff give - as they approve, or later - must be after
    ``now`` and no later than the booked period starts (``InvalidHoldExpiry``)."""
    if hold_expires_at <= now:
        raise InvalidHoldExpiry(HOLD_EXPIRY_IN_PAST_MESSAGE)
    if hold_expires_at > booking.held_from:
        raise InvalidHoldExpiry(
            HOLD_EXPIRY_AFTER_START_MESSAGE.format(start=_describe_moment(booking.held_from))
        )


def _notify_coordinator_of_hold(
    db: Session,
    booking: VenueBooking,
    *,
    notification_type: NotificationType,
    title: str,
    message: str,
    actor: User | None,
) -> None:
    """Story 12.7 AC2/AC7: the event's coordinator - whoever holds the event now (20.1 AC4) - is
    told what happened to the hold. The system is the actor of a warning or an expiry."""
    notify(
        db,
        recipient=booking.event.assigned_coordinator,
        actor=actor,
        notification_type=notification_type,
        event_id=booking.event_id,
        title=title,
        message=message,
        related_entity_type="venue_booking",
        related_entity_id=booking.id,
        commit=False,
    )


def _expire(db: Session, booking: VenueBooking) -> None:
    """Story 12.7 AC3: ``booking``'s hold lapsed before its event was confirmed, so it is EXPIRED -
    closed by the system, whenever this runs, while who approved it and when stay on the record
    (R5) - and its coordinator is told (AC2). The caller commits."""
    booking.status = BookingStatus.EXPIRED
    db.flush()
    venue_name, event_name = booking.venue.name, booking.event.name
    _notify_coordinator_of_hold(
        db,
        booking,
        notification_type=NotificationType.BOOKING_HOLD_EXPIRED,
        title=f"Hold on {venue_name} expired",
        message=(
            f'The hold on {venue_name} for "{event_name}" expired on '
            f"{_describe_moment(booking.hold_expires_at)}, before the event was confirmed, so the "
            "venue was released. Request a venue again if the event still needs one."
        ),
        actor=None,
    )
    record_audit(
        db,
        actor=None,
        action="BOOKING_EXPIRED",
        entity_type="venue_booking",
        entity_id=booking.id,
        details={
            "venue_id": str(booking.venue_id),
            "event_id": str(booking.event_id),
            "hold_expires_at": booking.hold_expires_at.isoformat(),
        },
        commit=False,
    )


def _has_open_hold(booking: VenueBooking) -> bool:
    """Story 12.7: an approved booking whose hold has an expiry and was not completed by its
    event's confirmation (AC4) - the only kind that can expire or take a new expiry."""
    return (
        booking.status == BookingStatus.APPROVED
        and booking.hold_expires_at is not None
        and booking.hold_completed_at is None
    )


def _expire_if_lapsed(db: Session, booking: VenueBooking, *, now: datetime) -> bool:
    """Story 12.7 AC7: whether ``booking``, locked by the caller, has an open hold that lapsed by
    ``now`` - if so it is expired and committed here, before the caller refuses to act on it."""
    if not _has_open_hold(booking) or booking.hold_expires_at > now:
        return False
    _expire(db, booking)
    db.commit()
    return True


def _open_holds() -> Select[tuple[VenueBooking]]:
    """The approved bookings whose hold is open (``_has_open_hold``), as a query to narrow."""
    return select(VenueBooking).where(
        VenueBooking.status == BookingStatus.APPROVED,
        VenueBooking.hold_expires_at.is_not(None),
        VenueBooking.hold_completed_at.is_(None),
    )


def expire_lapsed_holds(db: Session, *, now: datetime) -> list[VenueBooking]:
    """Story 12.7 AC3: every approved booking whose open hold expired by ``now`` becomes EXPIRED,
    and its coordinator is told (AC2). Its venue is free from then on (AC11), and it covers its
    requirement no longer (AC6). A row another transaction has locked - its event being confirmed,
    or its expiry being changed - is skipped: that action decides it (AC10), and the next sweep
    sees it."""
    lapsed = list(
        db.scalars(
            _open_holds()
            .where(VenueBooking.hold_expires_at <= now)
            .order_by(VenueBooking.hold_expires_at, VenueBooking.id)
            .with_for_update(skip_locked=True)
        ).all()
    )
    for booking in lapsed:
        _expire(db, booking)
    db.commit()
    return lapsed


def remind_expiring_holds(db: Session, *, now: datetime) -> list[VenueBooking]:
    """Story 12.7 AC2: the coordinator of each approved booking whose open hold expires within the
    warning period of ``now`` is warned, once - ``hold_reminded_at`` marks it, and only a new
    expiry outside that period clears it (``change_hold_expiry``). A lapsed hold is told it
    expired instead (``expire_lapsed_holds``)."""
    due = list(
        db.scalars(
            _open_holds()
            .where(
                VenueBooking.hold_reminded_at.is_(None),
                VenueBooking.hold_expires_at > now,
                VenueBooking.hold_expires_at <= now + _reminder_lead(),
            )
            .order_by(VenueBooking.hold_expires_at, VenueBooking.id)
            .with_for_update(skip_locked=True)
        ).all()
    )
    for booking in due:
        booking.hold_reminded_at = now
        venue_name = booking.venue.name
        _notify_coordinator_of_hold(
            db,
            booking,
            notification_type=NotificationType.BOOKING_HOLD_EXPIRING,
            title=f"Hold on {venue_name} expires soon",
            message=(
                f'{venue_name} is held for "{booking.event.name}" until '
                f"{_describe_moment(booking.hold_expires_at)}. If the event is not confirmed by "
                "then, the hold expires and the venue is released."
            ),
            actor=None,
        )
    db.commit()
    return due


def sweep_holds(db: Session, *, now: datetime) -> None:
    """Story 12.7 AC2/AC3: bring every hold up to ``now`` - expire the lapsed ones, then warn the
    coordinators of those about to lapse. The API runs it on a timer and before answering any
    request a lapsed hold would change (``app/bookings/deps.py``)."""
    expire_lapsed_holds(db, now=now)
    remind_expiring_holds(db, now=now)


def _refuse_without_open_hold(booking: VenueBooking) -> None:
    """Story 12.7 AC7: ``NoOpenHold``, saying why, unless ``booking`` has an open hold."""
    if booking.status != BookingStatus.APPROVED:
        raise NoOpenHold(NO_HOLD_MESSAGE.format(status=booking.status))
    if booking.hold_completed_at is not None:
        raise NoOpenHold(HOLD_COMPLETED_MESSAGE)
    if booking.hold_expires_at is None:
        raise NoOpenHold(NO_HOLD_SINCE_APPROVAL_MESSAGE)


def change_hold_expiry(
    db: Session,
    booking: VenueBooking,
    *,
    hold_expires_at: datetime,
    reason: str,
    actor: User,
    now: datetime | None = None,
) -> None:
    """Story 12.7 AC1/AC7: Venue Staff give an approved booking's open hold a new expiry, later or
    earlier, with a ``reason`` (decided 12 Oct 2026, Q27), and the event's coordinator is told
    both. AC5: it must be after ``now`` - the current time unless the caller gives one - and no
    later than the booked period starts (``InvalidHoldExpiry``). AC7: a booking with no open hold
    is refused (``NoOpenHold``) - not approved, completed by its event's confirmation, or
    approved before holds expired - and so is one whose hold lapsed since the last sweep, which
    is expired instead: an expired hold is never revived. AC2: a new expiry inside the warning
    period counts as the warning, since the coordinator is told it now; one outside it is warned
    about again later. Q30/Q31: the booking keeps this change - reason, who and when - until the
    next one; the audit entry keeps every change.

    Callers must fetch ``booking`` via ``get_booking_for_decision``: a sweep or the event's
    confirmation touching the same booking waits for this one, or this one for them.
    """
    moment = datetime.now(UTC) if now is None else now
    _refuse_without_open_hold(booking)
    if _expire_if_lapsed(db, booking, now=moment):
        _refuse_without_open_hold(booking)
    _check_hold_expiry(booking, hold_expires_at, now=moment)

    previous = booking.hold_expires_at
    booking.hold_expires_at = hold_expires_at
    booking.hold_reminded_at = moment if _is_inside_warning(hold_expires_at, now=moment) else None
    booking.hold_expiry_change_reason = reason
    booking.hold_expiry_changed_by_id = actor.id
    booking.hold_expiry_changed_at = moment
    db.flush()
    venue_name = booking.venue.name
    _notify_coordinator_of_hold(
        db,
        booking,
        notification_type=NotificationType.BOOKING_HOLD_EXPIRY_CHANGED,
        title=f"New expiry for the hold on {venue_name}",
        message=(
            f'{actor.full_name} changed when the hold on {venue_name} for "{booking.event.name}" '
            f"expires, to {_describe_moment(hold_expires_at)}. The event must be confirmed by "
            f"then. Reason: {reason}"
        ),
        actor=actor,
    )
    record_audit(
        db,
        actor=actor,
        action="BOOKING_HOLD_EXPIRY_CHANGED",
        entity_type="venue_booking",
        entity_id=booking.id,
        details={
            "venue_id": str(booking.venue_id),
            "event_id": str(booking.event_id),
            "hold_expires_at": {"from": previous.isoformat(), "to": hold_expires_at.isoformat()},
            "reason": reason,
        },
        commit=False,
    )
    db.commit()
    db.refresh(booking)
