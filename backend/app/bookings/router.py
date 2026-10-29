"""HTTP endpoints for venue bookings: raising a request (story 12.1), the venue staff queue
(story 13.1), searched and ordered (story 13.3), approval and rejection (stories 13.2, 13.2.1),
the read endpoints 13.2 AC3 / 13.2.1 AC4 need to make the outcome visible to the requesting
coordinator, withdrawing a request (story 12.2), an approved booking's hold expiry (story 12.7),
a replacement for an approved booking whose venue became unavailable (story 12.6), and an
organiser's read-only view of their own event's bookings (fix f7.1.2).

Story 12.7 AC3: every endpoint here expires the holds that have lapsed before it answers
(``ReleaseLapsedHolds``), so none of them shows or acts on a lapsed one as approved.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_permission
from app.auth.permissions import Permission
from app.bookings import service
from app.bookings.deps import ReleaseLapsedHolds
from app.bookings.schemas import (
    BookableEvent,
    BookingApproval,
    BookingHoldUpdate,
    BookingOut,
    BookingOutcome,
    BookingQueue,
    BookingQueueEntry,
    BookingQueueOrder,
    BookingQueueStatus,
    BookingReferenceData,
    BookingRejection,
    BookingReplacementIn,
    BookingRequestIn,
    BookingStatusCounts,
    BookingSwitchIn,
    OrganiserBooking,
)
from app.common.search import QUEUE_SEARCH_MAX_LENGTH
from app.db import get_db

router = APIRouter(prefix="/bookings", tags=["bookings"], dependencies=[ReleaseLapsedHolds])

CanRead = Depends(require_permission(Permission.BOOKINGS_READ))
CanReadOwn = Depends(require_permission(Permission.BOOKINGS_READ_OWN))
CanRequest = Depends(require_permission(Permission.BOOKINGS_REQUEST))
CanDecide = Depends(require_permission(Permission.BOOKINGS_DECIDE))
DbSession = Annotated[Session, Depends(get_db)]

BOOKING_NOT_FOUND_MESSAGE = "Booking request not found."
EVENT_NOT_FOUND_MESSAGE = "Event not found."
VENUE_NOT_FOUND_MESSAGE = "Venue not found."


@router.get("/reference-data", response_model=BookingReferenceData)
def reference_data(
    db: DbSession, actor: Annotated[CurrentUser, CanRequest]
) -> BookingReferenceData:
    """Story 12.1 AC1/AC4: the events this coordinator may raise a booking for. Declared above
    ``/{booking_id}`` so the literal path is not read as a booking id."""
    data = service.list_reference_data(db, actor=actor)
    return BookingReferenceData(
        events=[BookableEvent.model_validate(event) for event in data["events"]]
    )


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
def create_booking_request(
    payload: BookingRequestIn,
    db: DbSession,
    actor: Annotated[CurrentUser, CanRequest],
) -> BookingOut:
    """Story 12.1 AC1/AC2/AC3: raises one PENDING request for one venue, carrying the event's
    period, attendance, layout and required facilities. AC4: only the event's assigned
    coordinator may raise it. Story 11.1 AC2/AC7: a venue that does not suit the event needs a
    justification (422 without one). Story 12.5 AC11/AC12: the venue requirement it names must
    be the event's (404) and have no pending or approved request yet (409). Story 12.7 AC5: a
    pending request has no expiry - its hold starts when Venue Staff approve it - but a booked
    period already started cannot be requested, since it could never be approved (409).
    f12.1.2 (story 12.1 AC1/AC5/AC9 in the backlog's current numbering): it carries the setup and
    teardown sent with it, whole minutes up to 14 days (422 otherwise), which widen its booked
    period; a setup that would start in the past is refused (409).
    """
    try:
        booking = service.create_booking_request(db, payload, actor=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.VenueNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, VENUE_NOT_FOUND_MESSAGE) from None
    except service.NotAssignedCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.EventNotBookable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.VenueNotBookable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.RequirementNotOfEvent as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except service.RequirementAlreadyRequested as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.VenueHeld as exc:
        # 12.1 AC3/AC12/AC14: the venue is already booked or held for part of the period.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.VenueBlocked as exc:
        # 12.1 AC14: a recorded closure covers part of the period.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.VenueClosed as exc:
        # 12.1 AC14/AC16: the venue is not open at the request's own hours.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.SetupStartsInThePast as exc:
        # 12.1 AC9: the setup would start the booked period in the past.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.HoldPeriodStarted as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.JustificationRequired as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return BookingOut.model_validate(booking)


@router.get("", response_model=BookingQueue, dependencies=[CanDecide])
def list_bookings(
    db: DbSession,
    booking_status: Annotated[BookingQueueStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=QUEUE_SEARCH_MAX_LENGTH)] = None,
    order: BookingQueueOrder = BookingQueueOrder.DATE,
    limit: Annotated[
        int, Query(ge=1, le=service.BOOKING_QUEUE_MAX_LIMIT)
    ] = service.BOOKING_QUEUE_MAX_LIMIT,
    offset: Annotated[int, Query(ge=0, le=service.BOOKING_QUEUE_MAX_OFFSET)] = 0,
) -> BookingQueue:
    """Story 13.1 AC1-AC3: ``?status=PENDING`` is the pending queue Venue Staff decide from.
    Story 13.1.2 AC1: any other status is its tab, and no status is All; ``counts`` labels every
    tab. AC4: a page of the tab and its total. ``booking_status`` is aliased so it does not
    shadow FastAPI's ``status`` module, used for the status codes below.

    Story 13.3 AC1-AC4: ``?search=`` and ``?order=`` search and order the tab before it is paged,
    and the counts and total are the matching requests'. AC5: a search longer than 100 characters,
    or an order the queue does not offer, is a 422. AC8: Venue Staff only, as the queue is."""
    listing = service.list_booking_requests(
        db, status=booking_status, search=search, order=order, limit=limit, offset=offset
    )
    return BookingQueue(
        items=[BookingQueueEntry.from_booking(b) for b in listing.bookings],
        total=listing.total,
        counts=BookingStatusCounts.from_counts(listing.counts_by_status),
    )


@router.get("/for-event/{event_id}", response_model=list[BookingOutcome], dependencies=[CanRead])
def list_bookings_for_event(event_id: uuid.UUID, db: DbSession) -> list[BookingOutcome]:
    """13.2.1 AC4: every venue booking ever raised for this event, most recent first - lets a
    coordinator read the full history directly on the event page, without knowing any booking's
    id up front. Declared above ``/{booking_id}`` so the literal path is not read as a booking
    id, same as ``/reference-data`` above."""
    return [BookingOutcome.from_booking(b) for b in service.list_bookings_for_event(db, event_id)]


@router.get("/for-my-event/{event_id}", response_model=list[OrganiserBooking])
def list_bookings_for_own_event(
    event_id: uuid.UUID, db: DbSession, actor: Annotated[CurrentUser, CanReadOwn]
) -> list[OrganiserBooking]:
    """Fix f7.1.2 (story 7.1): AC1 the organiser reads their own event's approved and pending
    bookings, without the internal detail ``/for-event`` returns; AC2 another organiser's event
    is not found. Declared above ``/{booking_id}``, as ``/for-event`` is."""
    try:
        bookings = service.list_bookings_for_own_event(db, event_id, viewer=actor)
    except service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    return [OrganiserBooking.from_booking(b) for b in bookings]


@router.get("/{booking_id}", response_model=BookingOut, dependencies=[CanRead])
def get_booking(booking_id: uuid.UUID, db: DbSession) -> BookingOut:
    """AC3: lets the requesting coordinator (and other internal staff) read the outcome."""
    try:
        return BookingOut.model_validate(service.get_booking(db, booking_id))
    except service.BookingNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, BOOKING_NOT_FOUND_MESSAGE) from None


@router.patch("/{booking_id}", response_model=BookingOut)
def change_hold_expiry(
    booking_id: uuid.UUID,
    payload: BookingHoldUpdate,
    db: DbSession,
    actor: Annotated[CurrentUser, CanDecide],
) -> BookingOut:
    """Story 12.7 AC1/AC7: Venue Staff give an approved booking's open hold a new expiry, with a
    reason (decided 12 Oct 2026; 422 without one), and its coordinator is told both. AC5: it must
    be in the future and no later than the booked period starts (422). AC7: a booking with no open
    hold - not approved, an expired one included, or completed by its event's confirmation - is
    refused (409), saying why. AC9: Venue Staff only (403).
    """
    try:
        booking = service.get_booking_for_decision(db, booking_id)
    except service.BookingNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, BOOKING_NOT_FOUND_MESSAGE) from None
    try:
        service.change_hold_expiry(
            db,
            booking,
            hold_expires_at=payload.hold_expires_at,
            reason=payload.hold_expiry_change_reason,
            actor=actor,
        )
    except service.NoOpenHold as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.InvalidHoldExpiry as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return BookingOut.model_validate(booking)


@router.post("/{booking_id}/approve", response_model=BookingOut)
def approve_booking(
    booking_id: uuid.UUID,
    payload: BookingApproval,
    db: DbSession,
    actor: Annotated[CurrentUser, CanDecide],
) -> BookingOut:
    """AC1: sets the booking to confirmed, recording the approver and time. AC4: refused where
    the period conflicts with an existing confirmed booking.

    Story 12.7 AC1/AC5: the approval starts the booking's hold, with the expiry Venue Staff give
    (422 without one, or with one in the past or after the booked period starts); a booked period
    that has already started can no longer be held (409).

    Story 9.4 AC7: refused (409) while a period its venue is unavailable for overlaps the
    request's held period, with the sentence the request step gives; it is approved once the
    period no longer overlaps it.

    Story 12.6 AC3: approving a replacement releases the booking it replaces, in the same
    transaction - the original is locked first and the replacement second
    (``get_booking_for_approval``), the order the paths that close the original take.
    """
    try:
        booking = service.get_booking_for_approval(db, booking_id)
    except service.BookingNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, BOOKING_NOT_FOUND_MESSAGE) from None
    try:
        service.approve_booking(
            db, booking, actor_id=actor.id, hold_expires_at=payload.hold_expires_at
        )
    except service.BookingNotPending as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.VenueBlocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.HoldPeriodStarted as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.InvalidHoldExpiry as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except service.BookingConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return BookingOut.model_validate(booking)


@router.post("/{booking_id}/reject", response_model=BookingOut)
def reject_booking(
    booking_id: uuid.UUID,
    payload: BookingRejection,
    db: DbSession,
    actor: Annotated[CurrentUser, CanDecide],
) -> BookingOut:
    """13.2.1 AC1/AC2: rejects the booking with a mandatory reason. AC6: never runs the
    venue-conflict check - a rejected request never reserves the venue.
    """
    try:
        booking = service.get_booking_for_decision(db, booking_id)
    except service.BookingNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, BOOKING_NOT_FOUND_MESSAGE) from None
    try:
        service.reject_booking(
            db, booking, actor_id=actor.id, decision_reason=payload.decision_reason
        )
    except service.BookingNotPending as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return BookingOut.model_validate(booking)


@router.post("/{booking_id}/withdraw", response_model=BookingOut)
def withdraw_booking(
    booking_id: uuid.UUID,
    db: DbSession,
    actor: Annotated[CurrentUser, CanRequest],
) -> BookingOut:
    """12.2 AC2/AC3: withdraw a pending request - status, hold release and notification all
    together. AC6: refused (403) for anyone but the event's assigned coordinator. AC7: refused
    (409) unless the request is still pending. AC8: refused (409), naming the current status, if
    a Venue Staff decision already landed.
    """
    try:
        booking = service.get_booking_for_decision(db, booking_id)
    except service.BookingNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, BOOKING_NOT_FOUND_MESSAGE) from None
    try:
        service.withdraw_booking(db, booking, actor=actor)
    except service.NotAssignedCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.BookingNotPending as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return BookingOut.model_validate(booking)


@router.post(
    "/{booking_id}/replacements", response_model=BookingOut, status_code=status.HTTP_201_CREATED
)
def request_replacement_booking(
    booking_id: uuid.UUID,
    payload: BookingReplacementIn,
    db: DbSession,
    actor: Annotated[CurrentUser, CanRequest],
) -> BookingOut:
    """Story 12.6 AC2: asks for another venue as the replacement of an approved booking whose venue
    Venue Staff made unavailable - a new PENDING request linked to it, the original and the
    event left as they are (AC4); its setup and teardown are the original's unless sent. AC9:
    refused (403) for anyone but the event's assigned coordinator, (409) for a booking that is
    not approved and still marked - a pending one is switched instead - and for an event that
    takes no booking, a cancelled one included (AC8), and (404) for an unknown booking. AC10: one
    pending replacement per original (409, naming its venue) and never the original's own venue
    (409). As for any new request: (409, or 422 for a venue that does not suit without a
    justification, AC7) when the new venue cannot take it.
    """
    try:
        original = service.get_booking_for_decision(db, booking_id)
    except service.BookingNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, BOOKING_NOT_FOUND_MESSAGE) from None
    try:
        booking = service.request_replacement_booking(db, original, payload, actor=actor)
    except service.VenueNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, VENUE_NOT_FOUND_MESSAGE) from None
    except service.NotAssignedCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.EventNotBookable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.BookingNotReplaceable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.VenueNotBookable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.ReplacementAtOriginalVenue as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.ReplacementAlreadyPending as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.RequirementAlreadyRequested as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.VenueHeld as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.VenueBlocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.VenueClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.SetupStartsInThePast as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.HoldPeriodStarted as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.JustificationRequired as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return BookingOut.model_validate(booking)


@router.post("/{booking_id}/switch", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
def switch_booking_request(
    booking_id: uuid.UUID,
    payload: BookingSwitchIn,
    db: DbSession,
    actor: Annotated[CurrentUser, CanRequest],
) -> BookingOut:
    """Story 12.5, decided 11 Oct 2026: switches a pending request to another venue for the
    same venue requirement - the old one withdrawn and the new one requested together, or
    neither. Refused (403) for anyone but the event's assigned coordinator, (409) once the
    request is no longer pending, and as a new request is (409, or 422 for a venue that does
    not suit without a justification) when the new venue cannot take it. Story 12.7 (Q26): a
    booked period that has started is refused too (409), as for any new request. f12.1.2 (story
    12.1 AC1/AC5/AC9): the new request carries the setup and teardown sent with the switch, never
    the replaced request's (422 when out of range), and a setup that would start in the past is
    refused (409).
    """
    try:
        replaced = service.get_booking_for_switch(db, booking_id)
    except service.BookingNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, BOOKING_NOT_FOUND_MESSAGE) from None
    try:
        booking = service.switch_booking_request(db, replaced, payload, actor=actor)
    except service.VenueNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, VENUE_NOT_FOUND_MESSAGE) from None
    except service.NotAssignedCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.ReplacementCannotBeSwitched as exc:
        # Story 12.6 AC10: a pending replacement is withdrawn, not switched.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.BookingNotPending as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.EventNotBookable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.VenueNotBookable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.RequirementAlreadyRequested as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.VenueHeld as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.VenueBlocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.VenueClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.SetupStartsInThePast as exc:
        # 12.1 AC9: the setup would start the booked period in the past.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.HoldPeriodStarted as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.JustificationRequired as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return BookingOut.model_validate(booking)
