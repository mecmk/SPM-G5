"""Business rules for story 19.1: raise an event change request, list them, withdraw one; for
story 19.2: the coordinator's queue and record of them, and approving or rejecting one; and for
story 19.3: the impact approving one would have.

A change request records one field of an event in Planning, its value now, the value proposed
and why. Raising one changes nothing on the event, its bookings or its equipment holds (AC1/AC3):
the coordinator decides it later (story 19.2).

Values are stored as canonical JSON text - keys sorted, moments in UTC - so the same value always
reads the same: a proposal identical to the current value is recognised and refused (AC4), and
story 19.2 can show both sides as they were when the request was raised.

Deciding (story 19.2). The assigned coordinator approves or rejects a pending request, in one
transaction under the event's row lock - the lock 19.1's raise and withdrawal take - so a
withdrawal, a reassignment and a second decision are each serialised with it (AC6, AC7). The
request is claimed first by a conditional update, so of two decisions only one lands; every check
made after the claim rolls it back with everything else when it refuses (AC2). Approving applies
the change by the creation rules, releases only the bookings and equipment it affects (AC5), and
returns an event past Planning to Planning (AC8). Rejecting changes nothing on the event (AC3). A
pending request whose recorded value the event no longer has - another request's approval moved
it - is marked out of date, and can only be rejected (AC7).

Assessing (story 19.3). The impact of a pending request is worked out from the records as they
stand, by 19.2's own rules - ``booking_misfits``, ``check_proposed_schedule_change`` and the
equipment plan and statuses in ``app.equipment`` - so it says what the approval will do, and
writes nothing (AC3). Approving re-assesses under the event's lock and refuses, applying nothing,
when the result no longer matches the fingerprint the coordinator approved on (AC7).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

from pydantic import ValidationError
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, contains_eager

from app.auth.models import User
from app.auth.permissions import RoleCode
from app.bookings import service as bookings_service
from app.bookings.models import VenueBooking
from app.change_requests.models import ChangeRequestField, ChangeRequestStatus, EventChangeRequest
from app.change_requests.schemas import (
    AttendanceChangeIn,
    BookingImpactOut,
    CapacityShortfallOut,
    CapacityWarningOut,
    ChangeRequestApprovalIn,
    ChangeRequestImpactOut,
    ChangeRequestIn,
    ChangeRequestRejectionIn,
    ClosureOut,
    CountedVenueOut,
    EquipmentChangeIn,
    EquipmentImpactOut,
    HoldingBookingOut,
    ProposedSchedule,
    RegistrationImpactOut,
    ScheduleChangeIn,
    ShortPeriodOut,
    VenueRequirementsChangeIn,
)
from app.common.audit import record_audit
from app.equipment import service as equipment_service
from app.events import service as events_service
from app.events.models import (
    EquipmentRequestStatus,
    EquipmentType,
    Event,
    EventStatus,
    VenueRequirement,
)
from app.events.schemas import EventEquipmentIn, VenueRequirementIn
from app.notifications.service import NotificationType, active_members, notify
from app.registrations import service as registrations_service
from app.venues import service as venue_service

# The events refusals this service lets through, named here so the router imports only this
# module (backend/CLAUDE.md), as bookings/router.py catches ``service.EventNotFound``.
EventNotFound = events_service.EventNotFound
EventStateConflict = events_service.EventStateConflict
InvalidEventRequest = events_service.InvalidEventRequest
InvalidVenueRequirement = events_service.InvalidVenueRequirement

# AC5/AC6: the partial unique index a second pending request on one field violates (migration 015).
PENDING_FIELD_INDEX = "uq_event_change_requests_pending_field"

# AC5: change requests are taken only while the event is in Planning. Before approval, changes go
# through clarification (stories 4.2/4.3); once Confirmed or closed, none are taken (CL-016).
_REQUESTABLE_STATUS = EventStatus.PLANNING
_BEFORE_APPROVAL_STATUSES = (
    EventStatus.DRAFT,
    EventStatus.UNDER_REVIEW,
    EventStatus.CLARIFICATION_REQUESTED,
)

# How each field is named to a person, in messages and notifications.
FIELD_LABELS = {
    ChangeRequestField.SCHEDULE: "date and time",
    ChangeRequestField.EXPECTED_ATTENDANCE: "expected attendance",
    ChangeRequestField.VENUE_REQUIREMENTS: "venue requirements",
    ChangeRequestField.EQUIPMENT: "equipment",
}

NOT_YET_APPROVED_MESSAGE = (
    "This event has not been approved yet, so changes go through clarification instead of a "
    "change request."
)
CHANGE_REQUESTS_CLOSED_MESSAGE = "This event is {status}, so it no longer takes change requests."
DUPLICATE_PENDING_MESSAGE = (
    "A change to the {label} is already waiting for a decision. Withdraw it before requesting "
    "another."
)
UNCHANGED_VALUE_MESSAGE = "The proposed {label} is the same as the current one."
NOT_RELATED_PARTY_MESSAGE = (
    "Only the organiser and the coordinator assigned to this event may view its change requests."
)
NOT_PENDING_MESSAGE = "This change request is {status}, so it can no longer be withdrawn."

_REQUESTED_TITLE = "Change requested for {event}"
_REQUESTED_MESSAGE = '{organiser} asked to change the {label}: "{reason}"'
_WITHDRAWN_TITLE = "Change request withdrawn for {event}"
_WITHDRAWN_MESSAGE = "{organiser} withdrew their request to change the {label}."


class ChangeRequestNotFound(LookupError):
    pass


class ChangeRequestsNotYetOpen(EventStateConflict):
    """AC5: the event has not been approved yet."""

    def __init__(self) -> None:
        super().__init__(NOT_YET_APPROVED_MESSAGE)


class ChangeRequestsClosed(EventStateConflict):
    """AC5/AC8: the event is Confirmed or closed - also when it got there while the request was
    being written."""

    def __init__(self, status: str) -> None:
        super().__init__(CHANGE_REQUESTS_CLOSED_MESSAGE.format(status=status))


class DuplicatePendingChange(EventStateConflict):
    """AC5/AC6: the field already has a pending request."""

    def __init__(self, field: str) -> None:
        super().__init__(DUPLICATE_PENDING_MESSAGE.format(label=FIELD_LABELS[field]))


class UnchangedValue(InvalidEventRequest):
    """AC4: the proposed value is the one the event already has."""

    def __init__(self, field: str) -> None:
        super().__init__(UNCHANGED_VALUE_MESSAGE.format(label=FIELD_LABELS[field]))


class NotRelatedParty(PermissionError):
    """AC1: an internal role may see the event, but its change requests are between the
    organiser and the assigned coordinator."""

    def __init__(self) -> None:
        super().__init__(NOT_RELATED_PARTY_MESSAGE)


class ChangeRequestNotPending(EventStateConflict):
    """AC10: only a pending request can be withdrawn."""

    def __init__(self, status: str) -> None:
        super().__init__(NOT_PENDING_MESSAGE.format(status=status))


# --- canonical values ------------------------------------------------------------------------


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _moment(value: datetime | None) -> str | None:
    """A moment as ISO 8601 in UTC, so the same instant sent with another offset reads the same."""
    return None if value is None else value.astimezone(UTC).isoformat()


def _schedule_value(starts_at: datetime | None, ends_at: datetime | None) -> dict:
    return {"starts_at": _moment(starts_at), "ends_at": _moment(ends_at)}


def _requirement_value(
    requirement: VenueRequirement | VenueRequirementIn, event: Event
) -> dict[str, Any]:
    """One venue requirement, stored or proposed, in one shape. A requirement given no times of
    its own is needed for the whole event (2.7 AC2), so it reads with the event's times. Story
    19.2: its ``id`` is kept - None for a new one - so an approval can tell an edited requirement
    from a removed one and a new one; it identifies a row, not part of what is being asked for,
    so ``_without_ids`` leaves it out wherever two values are compared. Equipment items keep
    theirs the same way (``_equipment_value``)."""
    if isinstance(requirement, VenueRequirement):
        facilities = [(f.facility_code, f.quantity, f.notes) for f in requirement.facilities]
    else:
        facilities = [(f.code, f.quantity, f.notes) for f in requirement.facilities]
    is_timed = requirement.starts_at is not None
    return {
        "id": None if requirement.id is None else str(requirement.id),
        "name": requirement.name,
        "capacity": requirement.capacity,
        "layout_code": requirement.layout_code,
        "notes": requirement.notes,
        "starts_at": _moment(requirement.starts_at if is_timed else event.starts_at),
        "ends_at": _moment(requirement.ends_at if is_timed else event.ends_at),
        "facilities": [
            {"code": code, "quantity": quantity, "notes": notes}
            for code, quantity, notes in sorted(facilities, key=lambda facility: facility[0])
        ],
    }


def _equipment_value(
    lines: list[tuple[uuid.UUID | None, str, int, str | None]],
) -> list[dict[str, Any]]:
    """Equipment items, stored or proposed, in one shape, ordered by type. Story 19.2: each keeps
    its ``id`` - None for a new one - as a venue requirement does, since a type can be listed
    twice once its item is Declined (15.1 AC6)."""
    return [
        {
            "id": None if item_id is None else str(item_id),
            "equipment_type_code": code,
            "quantity": quantity,
            "technical_notes": notes,
        }
        for item_id, code, quantity, notes in sorted(
            lines, key=lambda line: (line[1], str(line[0] or ""))
        )
    ]


def _current_value(event: Event, field: str) -> Any:
    """The field's value on ``event`` as it stands, canonical - what a request raised now would
    record, and what an approval checks is still there (story 19.2 AC7). An equipment item kept,
    Cancelled, after a change removed it (story 19.2 AC5) is no longer the event's."""
    if field == ChangeRequestField.SCHEDULE:
        return _schedule_value(event.starts_at, event.ends_at)
    if field == ChangeRequestField.EXPECTED_ATTENDANCE:
        return event.expected_attendance
    if field == ChangeRequestField.VENUE_REQUIREMENTS:
        return [_requirement_value(item, event) for item in event.venue_requirements]
    if field == ChangeRequestField.EQUIPMENT:
        return _equipment_value(
            [
                (line.id, line.equipment_type.code, line.quantity, line.technical_notes)
                for line in event.equipment_requests
                if line.status != EquipmentRequestStatus.CANCELLED
            ]
        )
    raise TypeError(f"unhandled change request field: {field}")


_FIELDS_WITH_IDS = (ChangeRequestField.VENUE_REQUIREMENTS, ChangeRequestField.EQUIPMENT)


def _without_ids(field: str, value: Any) -> Any:
    """``value`` with each venue requirement's or equipment item's id left out, so two values
    compare on what they ask for (AC4) - and a value stored before ids were kept compares with
    one stored after."""
    if field not in _FIELDS_WITH_IDS or value is None:
        return value
    return [{key: item[key] for key in item if key != "id"} for item in value]


def _current_and_proposed(db: Session, event: Event, data: ChangeRequestIn) -> tuple[Any, Any]:
    """AC3/AC4: check the proposed value by the creation rules for its field, then return the
    field's current value and the proposed one, both canonical."""
    current = _current_value(event, data.field)
    if isinstance(data, ScheduleChangeIn):
        proposed = data.proposed
        events_service.check_proposed_schedule(proposed.starts_at, proposed.ends_at)
        return current, _schedule_value(proposed.starts_at, proposed.ends_at)
    if isinstance(data, AttendanceChangeIn):
        events_service.check_proposed_attendance(event, data.proposed)
        return current, data.proposed
    if isinstance(data, VenueRequirementsChangeIn):
        events_service.check_proposed_venue_requirements(db, event, data.proposed)
        return current, [_requirement_value(item, event) for item in data.proposed]
    if isinstance(data, EquipmentChangeIn):
        events_service.check_proposed_equipment(db, event, data.proposed)
        proposed = [
            (item.id, item.equipment_type_code, item.quantity, item.technical_notes)
            for item in data.proposed
        ]
        return current, _equipment_value(proposed)
    raise TypeError(f"unhandled change request field: {data.field}")


def _matches_event(request: EventChangeRequest, event: Event) -> bool:
    """Story 19.2 AC7: the field still holds the value the organiser asked to change."""
    field = request.field_name
    recorded = None if request.current_value is None else json.loads(request.current_value)
    return _without_ids(field, recorded) == _without_ids(field, _current_value(event, field))


def is_out_of_date(request: EventChangeRequest) -> bool:
    """Story 19.2 AC7: a pending request whose field has changed since it was raised - deciding
    another request moved it (new dates move the venue requirements' times), or the coordinator
    corrected it. Approving it would overwrite that change, so it can only be rejected."""
    return request.status == ChangeRequestStatus.PENDING and not _matches_event(
        request, request.event
    )


# --- raise -------------------------------------------------------------------------------------


def _refuse_unless_requestable(event: Event) -> None:
    """AC5/AC8: read under the event's row lock, so a confirm or cancel landing first is seen."""
    if event.status in _BEFORE_APPROVAL_STATUSES:
        raise ChangeRequestsNotYetOpen()
    if event.status != _REQUESTABLE_STATUS:
        raise ChangeRequestsClosed(event.status)


def _notify_coordinator(
    db: Session,
    event: Event,
    request: EventChangeRequest,
    *,
    actor: User,
    kind: NotificationType,
    title: str,
    message: str,
) -> None:
    """AC1/AC9: tell whoever is assigned to the event now (story 5.2 may have changed it), as
    story 20.1's ``notify`` does it: nothing is written when no coordinator is assigned."""
    notify(
        db,
        recipient=event.assigned_coordinator,
        actor=actor,
        notification_type=kind,
        event_id=event.id,
        title=title,
        message=message,
        related_entity_type="event_change_request",
        related_entity_id=request.id,
        commit=False,
    )


def raise_change_request(
    db: Session, event_id: uuid.UUID, data: ChangeRequestIn, *, actor: User
) -> EventChangeRequest:
    """AC1-AC8: the owning organiser asks for one field of their Planning event to change.

    The event row is locked first, so a status change racing this request either lands before
    it (and is seen: AC8) or waits until it is saved. The proposal is checked by the creation
    rules and compared with the current value (AC3/AC4), then inserted; a second pending request
    for the field is refused by the database's own index (AC6), never by a check beforehand
    (backend/STYLE.md). The request, the coordinator's notification and the audit entry are
    saved together. The event itself is not touched (AC1/AC3)."""
    event = events_service.get_own_event_for_update(db, event_id, actor=actor)
    _refuse_unless_requestable(event)
    current, proposed = _current_and_proposed(db, event, data)
    if _without_ids(data.field, current) == _without_ids(data.field, proposed):
        raise UnchangedValue(data.field)

    request = EventChangeRequest(
        event_id=event.id,
        requested_by_id=actor.id,
        field_name=data.field,
        current_value=_dump(current),
        proposed_value=_dump(proposed),
        reason=data.reason,
        # Stamped here, not left to the column's now(): now() is fixed for a whole transaction,
        # and newest-first must stay well ordered (as _replace_equipment's lines do).
        created_at=datetime.now(UTC),
    )
    db.add(request)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if PENDING_FIELD_INDEX in str(exc.orig):
            raise DuplicatePendingChange(data.field) from exc
        raise

    label = FIELD_LABELS[data.field]
    _notify_coordinator(
        db,
        event,
        request,
        actor=actor,
        kind=NotificationType.EVENT_CHANGE_REQUESTED,
        title=_REQUESTED_TITLE.format(event=event.name),
        message=_REQUESTED_MESSAGE.format(
            organiser=actor.full_name, label=label, reason=data.reason
        ),
    )
    record_audit(
        db,
        actor=actor,
        action="EVENT_CHANGE_REQUESTED",
        entity_type="event_change_request",
        entity_id=request.id,
        details={"event_id": str(event.id), "field": data.field},
        commit=False,
    )
    db.commit()
    db.refresh(request)
    return request


# --- list ----------------------------------------------------------------------------------


def list_change_requests(
    db: Session, event_id: uuid.UUID, *, viewer: User
) -> list[EventChangeRequest]:
    """AC1: an event's change requests, newest first, for its organiser and its assigned
    coordinator. Anyone who cannot see the event at all is told it is not found, as
    ``get_event`` does; an internal role who can see it, but is not assigned, is refused."""
    event = events_service.get_event(db, event_id, viewer=viewer)
    if viewer.id not in (event.organiser_id, event.assigned_coordinator_id):
        raise NotRelatedParty()
    return list(
        db.scalars(
            select(EventChangeRequest)
            .where(EventChangeRequest.event_id == event.id)
            .order_by(EventChangeRequest.created_at.desc(), EventChangeRequest.id)
        ).all()
    )


# --- withdraw ------------------------------------------------------------------------------


def withdraw_change_request(
    db: Session, event_id: uuid.UUID, change_request_id: uuid.UUID, *, actor: User
) -> EventChangeRequest:
    """AC9/AC10: the owning organiser withdraws a pending change request. It is kept, marked
    Withdrawn, so the history stays whole and the field is free again (the pending index ignores
    it). The update is conditional on the request still being pending, so a decision that lands
    first (19.4/19.5) makes it match no row, and the withdrawal is refused rather than undoing
    that decision. Withdrawing never changes the event, so its status does not matter."""
    event = events_service.get_own_event_for_update(db, event_id, actor=actor)
    request = db.scalar(
        select(EventChangeRequest).where(
            EventChangeRequest.id == change_request_id,
            EventChangeRequest.event_id == event.id,
        )
    )
    if request is None:
        raise ChangeRequestNotFound(change_request_id)

    withdrawn = db.execute(
        update(EventChangeRequest)
        .where(
            EventChangeRequest.id == request.id,
            EventChangeRequest.status == ChangeRequestStatus.PENDING,
        )
        .values(status=ChangeRequestStatus.WITHDRAWN)
    )
    if withdrawn.rowcount == 0:
        # Nothing was written; re-read the decision that landed first to name it.
        db.refresh(request)
        raise ChangeRequestNotPending(request.status)

    _notify_coordinator(
        db,
        event,
        request,
        actor=actor,
        kind=NotificationType.EVENT_CHANGE_REQUEST_WITHDRAWN,
        title=_WITHDRAWN_TITLE.format(event=event.name),
        message=_WITHDRAWN_MESSAGE.format(
            organiser=actor.full_name, label=FIELD_LABELS[request.field_name]
        ),
    )
    record_audit(
        db,
        actor=actor,
        action="EVENT_CHANGE_REQUEST_WITHDRAWN",
        entity_type="event_change_request",
        entity_id=request.id,
        details={"event_id": str(event.id), "field": request.field_name},
        commit=False,
    )
    db.commit()
    db.refresh(request)
    return request


# --- decide (story 19.2) -----------------------------------------------------------------------

# AC7: a decision is taken while the event is still going ahead - Planning, or past it but not
# yet over. A cancelled, completed or rejected event's requests can no longer be decided.
_DECIDABLE_STATUSES = (
    EventStatus.PLANNING,
    EventStatus.AWAITING_SAFETY_CHECK,
    EventStatus.CONFIRMED,
)
# AC8: an approved change sends an event past Planning back to it, for a new safety check (21.2).
_RETURNED_TO_PLANNING_REASON = "Change to the {label} approved."

NOT_ASSIGNED_COORDINATOR_MESSAGE = (
    "Only the coordinator assigned to this event can decide its change requests."
)
# AC7: why a request that is no longer pending cannot be decided, one sentence per status.
ALREADY_DECIDED_MESSAGES = {
    ChangeRequestStatus.APPROVED: "This change request has already been approved.",
    ChangeRequestStatus.REJECTED: "This change request has already been rejected.",
    ChangeRequestStatus.WITHDRAWN: "This change request was withdrawn by the organiser.",
}
DECISIONS_CLOSED_MESSAGE = (
    "This event is {status}, so its change requests can no longer be decided."
)
CHANGED_SINCE_REQUESTED_MESSAGE = (
    "The {label} changed since this request was raised, so it cannot be approved. Reject it so "
    "the organiser can ask again."
)
PROPOSAL_UNREADABLE_MESSAGE = (
    "This change request can no longer be applied as it was stored. Reject it so the organiser "
    "can ask again."
)

_APPROVED_TITLE = "Change approved for {event}"
_APPROVED_MESSAGE = "{coordinator} approved your request to change the {label}."
# AC8, and 21.2 AC8's "every status change notifies": said when the approval de-confirmed it.
_BACK_IN_PLANNING_MESSAGE = (
    " The event is back in Planning and needs a new safety check before it is confirmed again."
)
_RETURNED_TITLE = '"{event}" is back in Planning'
_RETURNED_MESSAGE = (
    '{coordinator} approved a change to the {label} of "{event}" while it was {status}, so it is '
    "back in Planning and needs a new safety check before it is confirmed again."
)
_REJECTED_TITLE = "Change rejected for {event}"
_REJECTED_MESSAGE = '{coordinator} rejected your request to change the {label}: "{reason}"'


class ProposalUnreadable(EventStateConflict):
    """AC2: the stored proposal no longer reads as the field's value - corrupted, or stored by a
    schema since changed - so it cannot be applied; it can still be rejected."""

    def __init__(self) -> None:
        super().__init__(PROPOSAL_UNREADABLE_MESSAGE)


class NotAssignedCoordinator(PermissionError):
    """AC6: any coordinator holds the permission to decide; only this event's may use it."""

    def __init__(self) -> None:
        super().__init__(NOT_ASSIGNED_COORDINATOR_MESSAGE)


class ChangeRequestAlreadyDecided(EventStateConflict):
    """AC7: the request was decided or withdrawn - before this decision, or while it was made."""

    def __init__(self, status: str) -> None:
        super().__init__(ALREADY_DECIDED_MESSAGES[status])


class DecisionsClosed(EventStateConflict):
    """AC7: the event is cancelled, completed or rejected, so nothing on it is decided any more."""

    def __init__(self, status: str) -> None:
        super().__init__(DECISIONS_CLOSED_MESSAGE.format(status=equipment_service.as_words(status)))


class ChangedSinceRequested(EventStateConflict):
    """AC7: the field no longer holds the value the organiser asked to change, so approving would
    overwrite a change made since (another request, or the coordinator's correction)."""

    def __init__(self, field: str) -> None:
        super().__init__(CHANGED_SINCE_REQUESTED_MESSAGE.format(label=FIELD_LABELS[field]))


def list_coordinator_change_requests(db: Session, *, viewer: User) -> list[EventChangeRequest]:
    """AC1: the change requests on the events ``viewer`` is assigned to, each with its event -
    what waits for their decision first, oldest first, the order to work through it in; then their
    record of what was decided or withdrawn, latest first (team request, 16 Oct 2026). A request
    still pending on an event no longer going ahead can never be decided, so it is left out; one
    decided before the event closed stays in the record. Each event's venue requirements and
    equipment are loaded with it, since every row says whether it is out of date (AC7)."""
    is_pending = EventChangeRequest.status == ChangeRequestStatus.PENDING
    with_event = contains_eager(EventChangeRequest.event)
    return list(
        db.scalars(
            select(EventChangeRequest)
            .join(EventChangeRequest.event)
            .options(
                with_event.selectinload(Event.venue_requirements).selectinload(
                    VenueRequirement.facilities
                ),
                with_event.selectinload(Event.equipment_requests),
            )
            .where(
                Event.assigned_coordinator_id == viewer.id,
                or_(~is_pending, Event.status.in_(_DECIDABLE_STATUSES)),
            )
            .order_by(
                case((is_pending, 0), else_=1),
                case((is_pending, EventChangeRequest.created_at)).asc(),
                func.coalesce(EventChangeRequest.decided_at, EventChangeRequest.updated_at).desc(),
                EventChangeRequest.id,
            )
        ).all()
    )


@dataclass(frozen=True)
class _Claim:
    """A change request just marked decided, and its event, locked until the transaction ends."""

    event: Event
    request: EventChangeRequest


def _claim_for_decision(
    db: Session,
    event_id: uuid.UUID,
    change_request_id: uuid.UUID,
    *,
    actor: User,
    to_status: str,
    reason: str | None,
) -> _Claim:
    """AC6/AC7: lock the event, check ``actor`` is its assigned coordinator and the event is still
    going ahead, then mark the request decided - who, when, and the reason for a rejection - by an
    update conditional on it still being pending, so a decision or withdrawal that landed first
    makes it match no row and this one is refused, naming what happened. Nothing is committed."""
    event = events_service.get_event_for_update(db, event_id, viewer=actor)
    if event.assigned_coordinator_id != actor.id:
        raise NotAssignedCoordinator()
    request = db.scalar(
        select(EventChangeRequest).where(
            EventChangeRequest.id == change_request_id,
            EventChangeRequest.event_id == event.id,
        )
    )
    if request is None:
        raise ChangeRequestNotFound(change_request_id)
    if event.status not in _DECIDABLE_STATUSES:
        raise DecisionsClosed(event.status)

    claimed = db.execute(
        update(EventChangeRequest)
        .where(
            EventChangeRequest.id == request.id,
            EventChangeRequest.status == ChangeRequestStatus.PENDING,
        )
        .values(
            status=to_status,
            decided_by_id=actor.id,
            decided_at=datetime.now(UTC),
            decision_reason=reason,
        )
    )
    db.refresh(request)
    if claimed.rowcount == 0:
        raise ChangeRequestAlreadyDecided(request.status)
    return _Claim(event=event, request=request)


def _proposed_requirements(
    event: Event, proposed: list[dict[str, Any]]
) -> list[VenueRequirementIn]:
    """AC2: the stored proposal as the requirements 2.7 edits. Each keeps the id 19.1 recorded;
    one stored before ids were kept is matched to the event's requirement of the same name - names
    are unique on an event (2.7 AC9) - or else is new."""
    by_name = {
        (requirement.name or "").strip().lower(): requirement.id
        for requirement in event.venue_requirements
    }
    items = []
    for value in proposed:
        if "id" in value:
            requirement_id = value["id"]
        else:
            requirement_id = by_name.get((value.get("name") or "").strip().lower())
        items.append(VenueRequirementIn.model_validate({**value, "id": requirement_id}))
    return items


def _proposed_equipment(event: Event, proposed: list[dict[str, Any]]) -> list[EventEquipmentIn]:
    """AC2: the stored proposal as the items 15.1 edits. Each keeps the id 19.1 recorded; one
    stored before ids were kept is matched to the event's current item of the same type - one an
    older proposal could name, since it was then listed once - or else is new."""
    by_type = {
        item.equipment_type.code: item.id
        for item in event.equipment_requests
        if item.status not in (EquipmentRequestStatus.CANCELLED, EquipmentRequestStatus.DECLINED)
    }
    items = []
    for value in proposed:
        item_id = value["id"] if "id" in value else by_type.get(value.get("equipment_type_code"))
        items.append(EventEquipmentIn.model_validate({**value, "id": item_id}))
    return items


def _apply_field(db: Session, event: Event, request: EventChangeRequest, *, actor: User) -> None:
    """AC2: write what ``request`` asks for to ``event``, re-checked against the event as it now
    stands by the same creation rules 19.1 checked when it was raised. A stored proposal that no
    longer reads as the field's value is refused (``ProposalUnreadable``)."""
    try:
        _write_field(db, event, request, actor=actor)
    except ValidationError as exc:
        raise ProposalUnreadable() from exc


def _write_field(db: Session, event: Event, request: EventChangeRequest, *, actor: User) -> None:
    proposed = json.loads(request.proposed_value)
    field = request.field_name
    if field == ChangeRequestField.EXPECTED_ATTENDANCE:
        events_service.check_proposed_attendance(event, proposed)
        event.expected_attendance = proposed
        db.flush()
    elif field == ChangeRequestField.SCHEDULE:
        schedule = ProposedSchedule.model_validate(proposed)
        events_service.apply_proposed_schedule(db, event, schedule.starts_at, schedule.ends_at)
        # 15.1 AC8: every item is re-checked, and held again, for the new dates.
        equipment_service.recheck_equipment_for_new_dates(db, event, actor=actor)
    elif field == ChangeRequestField.VENUE_REQUIREMENTS:
        events_service.apply_proposed_venue_requirements(
            db, event, _proposed_requirements(event, proposed)
        )
    else:
        equipment_service.apply_equipment_change(
            db, event, _proposed_equipment(event, proposed), actor=actor
        )


@dataclass(frozen=True)
class _AppliedChange:
    """What an approval did: the field's value before and after, the bookings it released, and
    the status the event left for Planning (None when it was already there)."""

    before: Any
    after: Any
    released_booking_ids: list[str]
    returned_from_status: str | None


def _apply_approved_change(
    db: Session, event: Event, request: EventChangeRequest, *, actor: User
) -> _AppliedChange:
    """AC2/AC5/AC7/AC8: apply what ``request`` asks for, releasing only what it affects.

    Refused, changing nothing, when the field no longer holds the value the organiser asked to
    change (AC7), or the change breaks a creation rule. The event's bookings are read before the
    change and judged after it by f7.2.4's fit rule: each one it no longer fits is released and
    Venue Staff told (AC5); equipment is released and held again by the equipment service. An
    event past Planning goes back to it (AC8), as story 9.4 sends one back."""
    field = request.field_name
    if not _matches_event(request, event):
        raise ChangedSinceRequested(field)
    before = _without_ids(field, _current_value(event, field))

    booked = events_service.live_bookings(db, event)
    _apply_field(db, event, request, actor=actor)
    label = FIELD_LABELS[field]
    released = [
        str(booking.id)
        for booking in events_service.bookings_no_longer_fitting(event, booked)
        if bookings_service.release_booking(db, booking, actor=actor, change=label)
    ]
    from_status = event.status
    is_returned = events_service.return_event_to_planning(
        db,
        event,
        actor=actor,
        at=datetime.now(UTC),
        reason=_RETURNED_TO_PLANNING_REASON.format(label=label),
        details={"change_request_id": str(request.id)},
    )
    return _AppliedChange(
        before=before,
        after=_without_ids(field, json.loads(request.proposed_value)),
        released_booking_ids=released,
        returned_from_status=from_status if is_returned else None,
    )


def _notify_safety_officers_of_return(
    db: Session, event: Event, request: EventChangeRequest, *, actor: User, from_status: str
) -> None:
    """AC8, and 21.2 AC8's "every status change notifies": the event left the Safety Officers'
    check, or lost the confirmation their approval allowed, so every active one is told."""
    for officer in active_members(db, role_code=RoleCode.SAFETY_OFFICER):
        notify(
            db,
            recipient=officer,
            actor=actor,
            notification_type=NotificationType.EVENT_RETURNED_TO_PLANNING,
            event_id=event.id,
            title=_RETURNED_TITLE.format(event=event.name),
            message=_RETURNED_MESSAGE.format(
                coordinator=actor.full_name,
                label=FIELD_LABELS[request.field_name],
                event=event.name,
                status=equipment_service.as_words(from_status),
            ),
            related_entity_type="event",
            related_entity_id=event.id,
            commit=False,
        )


def _notify_organiser(
    db: Session,
    event: Event,
    request: EventChangeRequest,
    *,
    actor: User,
    kind: NotificationType,
    title: str,
    message: str,
) -> None:
    """AC2/AC3: the organiser is told the outcome, in the decision's transaction (story 20.1)."""
    notify(
        db,
        recipient=event.organiser,
        actor=actor,
        notification_type=kind,
        event_id=event.id,
        title=title,
        message=message,
        related_entity_type="event_change_request",
        related_entity_id=request.id,
        commit=False,
    )


def approve_change_request(
    db: Session,
    event_id: uuid.UUID,
    change_request_id: uuid.UUID,
    data: ChangeRequestApprovalIn,
    *,
    actor: User,
) -> EventChangeRequest:
    """AC2: the assigned coordinator approves a pending change request. The decision, the change
    to the event, the notifications and the audit entries - the decision's, and the change's on
    the event's own history (7.4) - are written in one commit; a refusal after the request was
    claimed rolls all of it back, so the request stays pending and the event unchanged (AC5, AC7,
    AC8). Story 19.3 AC7: before anything is applied, the impact is re-assessed and compared
    with the assessment the coordinator approved on (``data``); a different one refuses the
    approval (``ImpactChanged``) the same way."""
    claim = _claim_for_decision(
        db,
        event_id,
        change_request_id,
        actor=actor,
        to_status=ChangeRequestStatus.APPROVED,
        reason=None,
    )
    event, request = claim.event, claim.request
    try:
        _check_impact_unchanged(db, event, request, data.assessment_fingerprint)
        change = _apply_approved_change(db, event, request, actor=actor)
    except ImpactChanged:
        db.rollback()
        raise
    except InvalidEventRequest:
        db.rollback()
        raise
    except EventStateConflict:
        db.rollback()
        raise

    field = request.field_name
    message = _APPROVED_MESSAGE.format(coordinator=actor.full_name, label=FIELD_LABELS[field])
    if change.returned_from_status is not None:
        message += _BACK_IN_PLANNING_MESSAGE
        _notify_safety_officers_of_return(
            db, event, request, actor=actor, from_status=change.returned_from_status
        )
    _notify_organiser(
        db,
        event,
        request,
        actor=actor,
        kind=NotificationType.EVENT_CHANGE_APPROVED,
        title=_APPROVED_TITLE.format(event=event.name),
        message=message,
    )
    details: dict[str, Any] = {
        "event_id": str(event.id),
        "field": field,
        "from": change.before,
        "to": change.after,
        "released_booking_ids": change.released_booking_ids,
    }
    if change.returned_from_status is not None:
        details["returned_from_status"] = change.returned_from_status
    record_audit(
        db,
        actor=actor,
        action="EVENT_CHANGE_APPROVED",
        entity_type="event_change_request",
        entity_id=request.id,
        details=details,
        commit=False,
    )
    record_audit(
        db,
        actor=actor,
        action="EVENT_CHANGE_APPLIED",
        entity_type="event",
        entity_id=event.id,
        details={
            "change_request_id": str(request.id),
            field: {"from": change.before, "to": change.after},
        },
        commit=False,
    )
    db.commit()
    db.refresh(request)
    return request


def reject_change_request(
    db: Session,
    event_id: uuid.UUID,
    change_request_id: uuid.UUID,
    data: ChangeRequestRejectionIn,
    *,
    actor: User,
) -> EventChangeRequest:
    """AC3/AC4: the assigned coordinator rejects a pending change request with a reason. The
    event is not touched; the decision, the organiser's notification (with the reason) and the
    audit entry are written in one commit. ``ChangeRequestRejectionIn`` has already refused a
    blank reason (AC4)."""
    claim = _claim_for_decision(
        db,
        event_id,
        change_request_id,
        actor=actor,
        to_status=ChangeRequestStatus.REJECTED,
        reason=data.reason,
    )
    event, request = claim.event, claim.request

    label = FIELD_LABELS[request.field_name]
    _notify_organiser(
        db,
        event,
        request,
        actor=actor,
        kind=NotificationType.EVENT_CHANGE_REJECTED,
        title=_REJECTED_TITLE.format(event=event.name),
        message=_REJECTED_MESSAGE.format(
            coordinator=actor.full_name, label=label, reason=data.reason
        ),
    )
    record_audit(
        db,
        actor=actor,
        action="EVENT_CHANGE_REJECTED",
        entity_type="event_change_request",
        entity_id=request.id,
        details={"event_id": str(event.id), "field": request.field_name, "reason": data.reason},
        commit=False,
    )
    db.commit()
    db.refresh(request)
    return request


# --- impact (story 19.3) -----------------------------------------------------------------------

NOT_ASSIGNED_TO_ASSESS_MESSAGE = (
    "Only the coordinator assigned to this event can view the impact of its changes."
)
IMPACT_CHANGED_MESSAGE = (
    "The impact of this change has changed since you opened it. Review the updated impact, then "
    "approve again."
)

# AC1: why 19.2 would cancel a booking, one sentence per reason.
_REQUIREMENT_REMOVED_REASON = "The change removes the venue requirement it was booked for."
_TIMES_REASON = "Its booked times no longer cover the times the change needs."
_PEOPLE_REASON = "It was booked for {booked} people; the change needs room for {needed}."
_LAYOUT_REASON = "It was booked for a different layout from the one the change asks for."

# AC2: what the approval does to each booking, as 19.2 does it.
_BOOKING_CANCELLED = (
    "Cancelled when the change is approved, freeing the venue. Venue Staff are told, and need do "
    "nothing; request a replacement from the event page."
)
_BOOKING_KEPT = "Stays as it is."

# AC2: what the approval does to each equipment item, as 19.2 does it.
_ITEM_CANCELLED = "Removed: its hold is released, and it is kept as Cancelled for the record."
_ITEM_DELETED = "Removed: its hold is released and the item deleted."
_ITEM_REQUESTED = "Held again, and back to Requested for you to send to Technical Support."
_ITEM_RESENT = (
    "Held again for the new dates, and back with Technical Support as Pending, to decide for the "
    "new dates."
)
_ITEM_MOVED = "Held again for the new dates."
_ITEM_UNAVAILABLE = (
    "Not enough available: flagged Unavailable, holding nothing, for you to lower or remove."
)
_TOLD_TECHNICAL_SUPPORT = " Technical Support are told it was withdrawn."


class ImpactChanged(RuntimeError):
    """AC7: the assessment the coordinator approved on is no longer what the records give."""

    def __init__(self) -> None:
        super().__init__(IMPACT_CHANGED_MESSAGE)


class NotAssignedToAssess(PermissionError):
    """AC6: any coordinator may hold the permission; only this event's sees its assessments."""

    def __init__(self) -> None:
        super().__init__(NOT_ASSIGNED_TO_ASSESS_MESSAGE)


@dataclass(frozen=True)
class _ProposedEvent:
    """The event as the approval would leave it - its period, attendance, venue requirements by
    id and, for an equipment change, the plan - read without writing anything."""

    starts_at: datetime
    ends_at: datetime
    attendance: int
    requirements: dict[uuid.UUID, events_service.RequirementTerms]
    is_rescheduled: bool
    equipment: equipment_service.EquipmentChangePlan | None


def _proposed_event(db: Session, event: Event, request: EventChangeRequest) -> _ProposedEvent:
    """AC3: what ``request`` proposes, checked by the same rules 19.2's ``_write_field`` applies
    before it writes - ``InvalidEventRequest`` when the approval would be refused, and a pydantic
    ``ValidationError`` when the stored proposal no longer reads."""
    proposed = json.loads(request.proposed_value)
    field = request.field_name
    current = {
        requirement.id: events_service.RequirementTerms.of(requirement)
        for requirement in event.venue_requirements
    }
    unchanged = _ProposedEvent(
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        attendance=event.expected_attendance,
        requirements=current,
        is_rescheduled=False,
        equipment=None,
    )
    if field == ChangeRequestField.EXPECTED_ATTENDANCE:
        events_service.check_proposed_attendance(event, proposed)
        return replace(unchanged, attendance=proposed)
    if field == ChangeRequestField.SCHEDULE:
        schedule = ProposedSchedule.model_validate(proposed)
        moved = events_service.check_proposed_schedule_change(
            event, schedule.starts_at, schedule.ends_at
        )
        return replace(
            unchanged,
            starts_at=schedule.starts_at,
            ends_at=schedule.ends_at,
            requirements=moved,
            is_rescheduled=True,
        )
    if field == ChangeRequestField.VENUE_REQUIREMENTS:
        items = _proposed_requirements(event, proposed)
        events_service.check_proposed_venue_requirements(db, event, items)
        # A requirement given no times is needed for the whole event (2.7 AC2), as
        # _fill_requirement_times leaves it once approved.
        terms = {
            item.id: events_service.RequirementTerms(
                id=item.id,
                name=item.name,
                capacity=item.capacity,
                layout_code=item.layout_code,
                starts_at=event.starts_at if item.starts_at is None else item.starts_at,
                ends_at=event.ends_at if item.starts_at is None else item.ends_at,
            )
            for item in items
            if item.id is not None
        }
        return replace(unchanged, requirements=terms)
    plan = equipment_service.plan_equipment_change(event, _proposed_equipment(event, proposed))
    return replace(unchanged, equipment=plan)


def _misfit_reason(
    misfit: events_service.BookingMisfit, booking: VenueBooking, people: int | None
) -> str:
    if misfit == events_service.BookingMisfit.REQUIREMENT_REMOVED:
        return _REQUIREMENT_REMOVED_REASON
    if misfit == events_service.BookingMisfit.TIMES:
        return _TIMES_REASON
    if misfit == events_service.BookingMisfit.PEOPLE:
        return _PEOPLE_REASON.format(booked=booking.expected_attendance, needed=people)
    return _LAYOUT_REASON


@dataclass(frozen=True)
class _NeededTerms:
    """What a booking would have to hold once approved: its period and people. None for a
    booking whose requirement the change removes."""

    starts_at: datetime
    ends_at: datetime
    people: int


def _needed_terms(
    booking: VenueBooking,
    requirements: dict[uuid.UUID, events_service.RequirementTerms],
    *,
    starts_at: datetime,
    ends_at: datetime,
    attendance: int,
    is_additional: bool,
) -> _NeededTerms | None:
    """AC1: an additional venue (12.5) holds the event's period and attendance; a requirement's
    booking, its requirement's times and people (``people_needed``, as 12.1 booked it)."""
    if is_additional:
        return _NeededTerms(starts_at=starts_at, ends_at=ends_at, people=attendance)
    terms = requirements.get(booking.venue_requirement_id)
    if terms is None:
        return None
    return _NeededTerms(
        starts_at=terms.starts_at,
        ends_at=terms.ends_at,
        people=venue_service.people_needed(capacity=terms.capacity, attendance=attendance),
    )


def _capacity_warning(booking: VenueBooking, people: int) -> CapacityWarningOut | None:
    """AC1/AC4: story 11.1's capacity check of the booked venue, in the booked layout."""
    failure = venue_service.capacity_failure(
        booking.venue, people=people, layout=booking.required_layout
    )
    if failure is None:
        return None
    return CapacityWarningOut(
        people_needed=failure.required,
        venue_capacity=failure.venue_value,
        layout_name=failure.name,
    )


@dataclass(frozen=True)
class _VenueImpact:
    """The bookings the change affects, and every live booking the approval keeps - the venues
    the event still holds afterwards."""

    affected: list[BookingImpactOut]
    kept: list[VenueBooking]


def _booking_impacts(db: Session, event: Event, proposed: _ProposedEvent) -> _VenueImpact:
    """AC1/AC2/AC4/AC5: each live booking, judged by 19.2's own fit rule
    (``events_service.booking_misfits``) against the event as the approval would leave it. One
    the rule fails is cancelled on approval; for it, the same venue is checked for the period a
    replacement would need - another booking holding it (12.1's ``find_holding_booking``, in SQL,
    half-open), a closure (9.4) and opening hours (12.1 AC16), setup and teardown widening the
    period as 12.1 widens it. Separately, a booking whose people change gets 11.1's capacity
    check. Bookings neither cancelled nor warned about are left out."""
    booked = events_service.live_bookings(db, event)
    current = {
        requirement.id: events_service.RequirementTerms.of(requirement)
        for requirement in event.venue_requirements
    }
    judged = [
        (
            item,
            events_service.booking_misfits(
                item,
                requirements=proposed.requirements,
                starts_at=proposed.starts_at,
                ends_at=proposed.ends_at,
                attendance=proposed.attendance,
            ),
        )
        for item in booked
    ]
    cancelled_ids = {item.booking.id for item, misfits in judged if misfits}
    kept = [item.booking for item, misfits in judged if not misfits]

    impacts = []
    for item, misfits in judged:
        booking = item.booking
        is_additional = item.requirement_name is None
        before = _needed_terms(
            booking,
            current,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            attendance=event.expected_attendance,
            is_additional=is_additional,
        )
        after = _needed_terms(
            booking,
            proposed.requirements,
            starts_at=proposed.starts_at,
            ends_at=proposed.ends_at,
            attendance=proposed.attendance,
            is_additional=is_additional,
        )
        is_people_changed = after is not None and (before is None or after.people != before.people)
        warning = _capacity_warning(booking, after.people) if is_people_changed else None
        if not misfits and warning is None:
            continue

        holding = closure = None
        is_closed = False
        needed = after if misfits else None
        if needed is not None:
            held_from = needed.starts_at - timedelta(minutes=booking.setup_minutes)
            held_until = needed.ends_at + timedelta(minutes=booking.teardown_minutes)
            holding = bookings_service.find_holding_booking(
                db, booking.venue_id, held_from, held_until, exclude_ids=cancelled_ids
            )
            closure = venue_service.find_blocking_unavailability(
                db, booking.venue_id, starts_at=held_from, ends_at=held_until
            )
            is_closed = venue_service.closed_for(
                booking.venue, starts_at=needed.starts_at, ends_at=needed.ends_at
            )
        people = None if after is None else after.people
        impacts.append(
            BookingImpactOut(
                booking_id=booking.id,
                venue_id=booking.venue_id,
                venue_name=item.venue_name,
                requirement_name=item.requirement_name,
                status=booking.status,
                starts_at=booking.starts_at,
                ends_at=booking.ends_at,
                will_be_cancelled=bool(misfits),
                reasons=[_misfit_reason(misfit, booking, people) for misfit in misfits],
                capacity_warning=warning,
                needed_starts_at=None if needed is None else needed.starts_at,
                needed_ends_at=None if needed is None else needed.ends_at,
                held_by=None
                if holding is None
                else HoldingBookingOut(
                    event_name=holding.event.name,
                    held_from=holding.held_from,
                    held_until=holding.held_until,
                ),
                closure=None
                if closure is None
                else ClosureOut(
                    reason=closure.reason,
                    notes=closure.notes,
                    starts_at=closure.starts_at,
                    ends_at=closure.ends_at,
                ),
                is_outside_opening_hours=is_closed,
                after_approval=_BOOKING_CANCELLED if misfits else _BOOKING_KEPT,
            )
        )
    return _VenueImpact(affected=impacts, kept=kept)


def _counted_venue(booking: VenueBooking) -> CountedVenueOut:
    """Story 11.1 AC4: how many people ``booking``'s venue holds, in its booked layout."""
    return CountedVenueOut(
        venue_id=booking.venue_id,
        venue_name=booking.venue.name,
        capacity=venue_service.venue_capacity(booking.venue, layout=booking.required_layout),
        layout_name=_counted_layout_name(booking),
    )


def _capacity_shortfall(
    request: EventChangeRequest, proposed: _ProposedEvent, kept: list[VenueBooking]
) -> CapacityShortfallOut | None:
    """AC1/AC4 (decided 19 Oct 2026): an attendance change is judged, moment by moment, against
    what the venues the approval keeps hold between them while they are in use - each by 11.1's
    capacity in its booked layout, a venue booked for several requirements (12.5 AC9) counted
    once. A requirement's own booking can still fit its requirement while the event outgrows it,
    and venues booked at different times never hold the same people. The event is split wherever
    a booking starts or ends, on the bookings' own times (setup and teardown hold nobody); a span
    no venue is booked for is a break and needs no room. Equal fits. Neighbouring short spans
    with the same venues are one period. Nothing is judged without a kept booking, nor for any
    other field."""
    if request.field_name != ChangeRequestField.EXPECTED_ATTENDANCE or not kept:
        return None
    moments = sorted(
        {booking.starts_at for booking in kept} | {booking.ends_at for booking in kept}
    )
    periods: list[ShortPeriodOut] = []
    for starts_at, ends_at in pairwise(moments):
        in_use = {
            booking.venue_id: booking
            for booking in kept
            if booking.starts_at <= starts_at and ends_at <= booking.ends_at
        }
        if not in_use:
            continue
        venues = [_counted_venue(booking) for booking in in_use.values()]
        capacity = sum(venue.capacity for venue in venues)
        if proposed.attendance <= capacity:
            continue
        previous = periods[-1] if periods else None
        if previous is not None and previous.ends_at == starts_at and previous.venues == venues:
            periods[-1] = previous.model_copy(update={"ends_at": ends_at})
            continue
        periods.append(
            ShortPeriodOut(
                starts_at=starts_at,
                ends_at=ends_at,
                capacity=capacity,
                shortfall=proposed.attendance - capacity,
                venues=venues,
            )
        )
    if not periods:
        return None
    return CapacityShortfallOut(proposed_attendance=proposed.attendance, periods=periods)


def _counted_layout_name(booking: VenueBooking) -> str | None:
    """The booked layout's name when the venue records that layout's own capacity - the figure
    counted - else None, its maximum."""
    layout = booking.required_layout
    if layout is None:
        return None
    recorded = {item.layout_code: item.layout_capacity for item in booking.venue.layouts}
    return layout.name if recorded.get(layout.code) is not None else None


def _equipment_row(
    *,
    item_id: uuid.UUID | None,
    equipment_type: EquipmentType,
    change: str,
    current_status: str | None,
    required: int | None,
    available: int | None,
    status_after: str | None,
    technical_support_told: bool,
    after_approval: str,
) -> EquipmentImpactOut:
    told = _TOLD_TECHNICAL_SUPPORT if technical_support_told else ""
    return EquipmentImpactOut(
        item_id=item_id,
        equipment_type_code=equipment_type.code,
        equipment_type_name=equipment_type.name,
        change=change,
        current_status=current_status,
        required=required,
        available=available,
        shortfall=0 if required is None or available is None else max(0, required - available),
        status_after=status_after,
        technical_support_told=technical_support_told,
        after_approval=after_approval + told,
    )


def _rechecked_equipment(
    db: Session, event: Event, proposed: _ProposedEvent
) -> list[EquipmentImpactOut]:
    """AC2/AC5: new dates, as ``recheck_equipment_for_new_dates`` treats them - every hold the
    event has is released, then each open item, oldest first, is held again from what the new
    dates leave, or flagged Unavailable. The event's own holds are left out of the figure the way
    releasing them leaves them out."""
    available = events_service.available_by_type(
        db, proposed.starts_at, proposed.ends_at, exclude_event_id=event.id
    )
    rows = []
    for item in equipment_service.open_items(db, event):
        before = available.get(item.equipment_type_id, 0)
        is_held = equipment_service.take_units(available, item.equipment_type_id, item.quantity)
        status_after = equipment_service.status_after_new_dates(item.status, is_held=is_held)
        if not is_held:
            after_approval = _ITEM_UNAVAILABLE
        elif status_after == EquipmentRequestStatus.PENDING:
            after_approval = _ITEM_RESENT
        elif status_after != item.status:
            after_approval = _ITEM_REQUESTED
        else:
            after_approval = _ITEM_MOVED
        rows.append(
            _equipment_row(
                item_id=item.id,
                equipment_type=item.equipment_type,
                change="rechecked",
                current_status=item.status,
                required=item.quantity,
                available=before,
                status_after=status_after,
                technical_support_told=False,
                after_approval=after_approval,
            )
        )
    return rows


def _changed_equipment(
    db: Session, event: Event, plan: equipment_service.EquipmentChangePlan
) -> list[EquipmentImpactOut]:
    """AC2/AC5: an equipment change, as ``apply_equipment_change`` carries out the same plan -
    removed items release their holds and are kept Cancelled or deleted; changed items, in the
    event's order, then added ones, are held again from what ``available_for_event`` gives once
    the changing items' holds are released, or flagged Unavailable. Unchanged items are left
    out."""
    codes = {
        planned.line.equipment_type_code
        for planned in plan.items
        if planned.change == equipment_service.EquipmentChange.CHANGED
    } | {line.equipment_type_code for line in plan.added}
    types = {
        equipment_type.code: equipment_type
        for equipment_type in db.scalars(select(EquipmentType).where(EquipmentType.code.in_(codes)))
    }
    available = equipment_service.available_for_event(db, event, releasing=plan.releasing_ids)

    def held_row(
        item_id: uuid.UUID | None,
        equipment_type: EquipmentType,
        quantity: int,
        *,
        change: str,
        current_status: str | None,
        is_told: bool,
    ) -> EquipmentImpactOut:
        before = available.get(equipment_type.id, 0)
        is_held = equipment_service.take_units(available, equipment_type.id, quantity)
        return _equipment_row(
            item_id=item_id,
            equipment_type=equipment_type,
            change=change,
            current_status=current_status,
            required=quantity,
            available=before,
            status_after=equipment_service.status_after_change(is_held=is_held),
            technical_support_told=is_told,
            after_approval=_ITEM_REQUESTED if is_held else _ITEM_UNAVAILABLE,
        )

    rows = []
    for planned in plan.items:
        item = planned.item
        is_told = item.status in equipment_service.WITH_TECHNICAL_SUPPORT
        if planned.change == equipment_service.EquipmentChange.CHANGED:
            line = planned.line
            rows.append(
                held_row(
                    item.id,
                    types[line.equipment_type_code],
                    line.quantity,
                    change="changed",
                    current_status=item.status,
                    is_told=is_told,
                )
            )
        elif (
            planned.change == equipment_service.EquipmentChange.REMOVED
            and item.status != EquipmentRequestStatus.CANCELLED
        ):
            status_after = equipment_service.status_after_removal(item.status)
            rows.append(
                _equipment_row(
                    item_id=item.id,
                    equipment_type=item.equipment_type,
                    change="removed",
                    current_status=item.status,
                    required=None,
                    available=None,
                    status_after=status_after,
                    technical_support_told=is_told,
                    after_approval=_ITEM_DELETED if status_after is None else _ITEM_CANCELLED,
                )
            )
    for line in plan.added:
        rows.append(
            held_row(
                None,
                types[line.equipment_type_code],
                line.quantity,
                change="added",
                current_status=None,
                is_told=False,
            )
        )
    return rows


def _equipment_impacts(
    db: Session, event: Event, proposed: _ProposedEvent
) -> list[EquipmentImpactOut]:
    """AC1/AC5: only new dates and an equipment change touch the equipment."""
    if proposed.is_rescheduled:
        return _rechecked_equipment(db, event, proposed)
    if proposed.equipment is not None:
        return _changed_equipment(db, event, proposed.equipment)
    return []


def _registration_impact(
    db: Session, event: Event, request: EventChangeRequest, proposed: _ProposedEvent
) -> RegistrationImpactOut | None:
    """AC1: the registrations taking a place (18.1), counted - affected when new dates move
    them, or when a lowered attendance leaves more registered than it allows. Nothing is
    written to any registration."""
    count = registrations_service.count_active_registrations(db, event.id)
    is_attendance = request.field_name == ChangeRequestField.EXPECTED_ATTENDANCE
    over_by = max(0, count - proposed.attendance) if is_attendance else 0
    if count == 0 or (over_by == 0 and not proposed.is_rescheduled):
        return None
    return RegistrationImpactOut(
        active_count=count,
        proposed_attendance=proposed.attendance if is_attendance else None,
        over_by=over_by,
        dates_change=proposed.is_rescheduled,
    )


def _fingerprint(impact: ChangeRequestImpactOut) -> str:
    """AC7: everything the assessment says but when it was made, as one digest."""
    content = impact.model_dump(mode="json", exclude={"assessed_at", "fingerprint"})
    return hashlib.sha256(_dump(content).encode()).hexdigest()


def _assess(db: Session, event: Event, request: EventChangeRequest) -> ChangeRequestImpactOut:
    """AC1-AC5: what approving ``request`` would do to ``event``'s arrangements, from the
    records as they stand. An out-of-date request (19.2 AC7) or one 19.2 would refuse is said to
    be so, and nothing else is predicted for it. Reads only."""
    bookings: list[BookingImpactOut] = []
    equipment: list[EquipmentImpactOut] = []
    registrations = None
    capacity_shortfall = None
    refused_because = None
    is_out_of_date = not _matches_event(request, event)
    if not is_out_of_date:
        try:
            proposed = _proposed_event(db, event, request)
        except ValidationError:
            refused_because = PROPOSAL_UNREADABLE_MESSAGE
        except InvalidEventRequest as exc:
            refused_because = str(exc)
        else:
            venues = _booking_impacts(db, event, proposed)
            bookings = venues.affected
            capacity_shortfall = _capacity_shortfall(request, proposed, venues.kept)
            equipment = _equipment_impacts(db, event, proposed)
            registrations = _registration_impact(db, event, request, proposed)
    impact = ChangeRequestImpactOut(
        change_request_id=request.id,
        assessed_at=datetime.now(UTC),
        fingerprint="",
        is_out_of_date=is_out_of_date,
        refused_because=refused_because,
        venue_bookings=bookings,
        equipment=equipment,
        registrations=registrations,
        capacity_shortfall=capacity_shortfall,
        has_impact=bool(
            bookings or equipment or registrations is not None or capacity_shortfall is not None
        ),
    )
    return impact.model_copy(update={"fingerprint": _fingerprint(impact)})


def get_change_request_impact(
    db: Session, event_id: uuid.UUID, change_request_id: uuid.UUID, *, viewer: User
) -> ChangeRequestImpactOut:
    """AC3/AC6: the assessment of a pending change request, for the event's assigned
    coordinator only - anyone who cannot see the event is told it is not found, as
    ``get_event`` does. Worked out afresh from the records each time it is asked for, and
    changes nothing: no lock is taken and nothing is written."""
    event = events_service.get_event(db, event_id, viewer=viewer)
    if event.assigned_coordinator_id != viewer.id:
        raise NotAssignedToAssess()
    request = db.scalar(
        select(EventChangeRequest).where(
            EventChangeRequest.id == change_request_id,
            EventChangeRequest.event_id == event.id,
        )
    )
    if request is None:
        raise ChangeRequestNotFound(change_request_id)
    if event.status not in _DECIDABLE_STATUSES:
        raise DecisionsClosed(event.status)
    if request.status != ChangeRequestStatus.PENDING:
        raise ChangeRequestAlreadyDecided(request.status)
    return _assess(db, event, request)


def _lock_equipment_types(db: Session, event: Event, request: EventChangeRequest) -> None:
    """AC7: the equipment types the approval may hold or release - the event's items' and, for
    an equipment change, those it proposes - locked as every hold takes them, so the stock the
    re-assessment reads cannot move before the approval commits."""
    type_ids = {item.equipment_type_id for item in event.equipment_requests}
    if request.field_name == ChangeRequestField.EQUIPMENT:
        proposed = json.loads(request.proposed_value)
        codes = {line.get("equipment_type_code") for line in proposed if isinstance(line, dict)}
        type_ids |= set(db.scalars(select(EquipmentType.id).where(EquipmentType.code.in_(codes))))
    equipment_service.lock_types(db, type_ids)


def _check_impact_unchanged(
    db: Session, event: Event, request: EventChangeRequest, fingerprint: str
) -> None:
    """Story 19.3 AC7: re-assess the change under the event's lock, already held by the claim,
    and with the equipment types locked too, and refuse the approval (``ImpactChanged``) when the
    assessment is not the one the coordinator saw. A request the event has moved on from is left
    to 19.2's own refusal (``ChangedSinceRequested``), which names why. Venues need no lock: an
    approval only ever releases bookings, and a replacement is re-checked by 12.1 when it is
    requested."""
    if not _matches_event(request, event):
        return
    _lock_equipment_types(db, event, request)
    if _assess(db, event, request).fingerprint != fingerprint:
        raise ImpactChanged()
