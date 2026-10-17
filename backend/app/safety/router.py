"""HTTP endpoints for story 21.1 (the Safety Officer's safety check queue and detail) and story
21.2 (the coordinator requests a review, the officer decides, the coordinator confirms, and the
event page's safety summary)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, require_any_permission, require_permission
from app.auth.permissions import Permission
from app.bookings.deps import ReleaseLapsedHolds
from app.db import get_db
from app.events import service as events_service
from app.events.models import Event
from app.safety import service
from app.safety.schemas import (
    EventSafetyOut,
    SafetyCheckDetail,
    SafetyDecisionIn,
    SafetyQueueEntry,
    SafetyReviewOut,
    SafetyReviewRequestIn,
)

router = APIRouter(prefix="/safety-checks", tags=["safety"])
# Story 21.2: the coordinator's side of the review lives on the event.
events_router = APIRouter(prefix="/events", tags=["safety"])

SAFETY_CHECK_NOT_FOUND_MESSAGE = "No event awaiting a safety check was found."
EVENT_NOT_FOUND_MESSAGE = "Event not found."

CanReviewSafety = Depends(require_permission(Permission.SAFETY_REVIEW))
# 21.2 AC17: only a coordinator requests a review or confirms; which one is the service's rule.
CanCoordinate = Depends(require_permission(Permission.EVENTS_REVIEW))
# Story 12.7 AC4/AC6: a lapsed hold counts for nothing from its expiry, so every route here sweeps
# before answering - the timer only runs once a minute.
CanReadEvent = Depends(
    require_any_permission(Permission.EVENTS_READ_OWN, Permission.EVENTS_READ_ALL)
)
DbSession = Annotated[Session, Depends(get_db)]


@router.get(
    "",
    response_model=list[SafetyQueueEntry],
    dependencies=[CanReviewSafety, ReleaseLapsedHolds],
)
def list_safety_queue(
    db: DbSession,
    queue_status: Annotated[service.SafetyQueueStatus | None, Query(alias="status")] = None,
) -> list[SafetyQueueEntry]:
    """AC2: the events in one tab (Pending is the queue itself), or every tab without ``status``,
    oldest first. AC6: safety:review only - other roles get 403 from the dependency."""
    return [
        SafetyQueueEntry.from_event(
            item.event,
            approved_bookings=item.approved_bookings,
            safety_status=item.safety_status,
        )
        for item in service.list_safety_queue(db, status=queue_status)
    ]


def _safety_check_detail(db: Session, event_id: uuid.UUID) -> SafetyCheckDetail:
    try:
        check = service.get_safety_check(db, event_id)
    except service.SafetyCheckNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, SAFETY_CHECK_NOT_FOUND_MESSAGE) from None
    return SafetyCheckDetail.from_event(
        check.event,
        approved_bookings=check.approved_bookings,
        accepted_equipment=check.accepted_equipment,
        reviews=check.reviews,
        changes=check.changes,
        factors=check.factors,
        facts_fingerprint=check.facts_fingerprint,
    )


@router.get(
    "/{event_id}",
    response_model=SafetyCheckDetail,
    dependencies=[CanReviewSafety, ReleaseLapsedHolds],
)
def get_safety_check(event_id: uuid.UUID, db: DbSession) -> SafetyCheckDetail:
    """AC3-AC5: everything about one event that affects safety, with what changed since its last
    review. An event neither awaiting the check nor reviewed is a 404. AC6: safety:review only.
    21.2 AC2: with the review factors."""
    return _safety_check_detail(db, event_id)


@router.post(
    "/{event_id}/decision",
    response_model=SafetyCheckDetail,
    dependencies=[CanReviewSafety, ReleaseLapsedHolds],
)
def decide_safety_check(
    event_id: uuid.UUID,
    payload: SafetyDecisionIn,
    db: DbSession,
    actor: CurrentUser,
) -> SafetyCheckDetail:
    """21.2 AC2-AC5: approve, or request changes with findings. AC9/AC10: an invalid
    payload is a 422 before this runs. AC16: safety:review only. AC20: 404 unknown, 409 not
    awaiting the check."""
    try:
        service.decide_safety_check(db, event_id, payload, actor=actor)
    except service.SafetyEventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None
    except service.SafetyStateConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.UnknownSafetyFactor as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return _safety_check_detail(db, event_id)


def _event_safety(db: Session, event: Event, viewer: CurrentUser) -> EventSafetyOut:
    summary = service.get_event_safety(db, event, viewer=viewer)
    return EventSafetyOut(
        event_id=event.id,
        status=event.status,
        latest_review=(
            None
            if summary.latest_review is None
            else SafetyReviewOut.from_review(summary.latest_review)
        ),
        request_blockers=summary.request_blockers,
        confirm_blockers=summary.confirm_blockers,
        unchanged_warning=summary.unchanged_warning,
    )


def _get_event(db: Session, event_id: uuid.UUID, viewer: CurrentUser) -> Event:
    try:
        return events_service.get_event(db, event_id, viewer=viewer)
    except events_service.EventNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, EVENT_NOT_FOUND_MESSAGE) from None


@router.post(
    "/{event_id}/request", response_model=EventSafetyOut, dependencies=[ReleaseLapsedHolds]
)
def request_safety_review(
    event_id: uuid.UUID,
    payload: SafetyReviewRequestIn,
    db: DbSession,
    actor: Annotated[CurrentUser, CanCoordinate],
) -> EventSafetyOut:
    """21.2 AC1: send a secured Planning event for the safety check. AC17: the assigned
    coordinator only (403). AC19: 409 naming what is missing. AC12: 409 whose ``detail`` holds
    ``unchanged_arrangements`` when a flagged arrangement is unchanged and not acknowledged."""
    event = _get_event(db, event_id, actor)
    try:
        service.request_safety_review(
            db, event, actor=actor, acknowledge_unchanged=payload.acknowledge_unchanged
        )
    except events_service.NotAssignedCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.FlaggedArrangementsUnchanged as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": str(exc), "unchanged_arrangements": exc.arrangements},
        ) from None
    except service.SafetyStateConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return _event_safety(db, event, actor)


@events_router.get(
    "/{event_id}/safety-review",
    response_model=EventSafetyOut,
    dependencies=[CanReadEvent, ReleaseLapsedHolds],
)
def get_event_safety(event_id: uuid.UUID, db: DbSession, viewer: CurrentUser) -> EventSafetyOut:
    """21.2 AC4: the latest review and its findings, for anyone who may see the event. AC1/AC7:
    what stops the assigned coordinator requesting a review or confirming, and AC12 the warning a
    request would raise; AC18: no one else gets them."""
    return _event_safety(db, _get_event(db, event_id, viewer), viewer)


@events_router.post(
    "/{event_id}/confirm", response_model=EventSafetyOut, dependencies=[ReleaseLapsedHolds]
)
def confirm_event(
    event_id: uuid.UUID,
    db: DbSession,
    actor: Annotated[CurrentUser, CanCoordinate],
) -> EventSafetyOut:
    """21.2 AC7: confirm a safety-approved event. AC17: the assigned coordinator only (403).
    AC14/AC21: 409 naming each blocker."""
    event = _get_event(db, event_id, actor)
    try:
        service.confirm_event(db, event, actor=actor)
    except events_service.NotAssignedCoordinator as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.SafetyStateConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return _event_safety(db, event, actor)
