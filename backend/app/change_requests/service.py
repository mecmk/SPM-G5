"""Business rules for story 19.1: raise an event change request, list them, withdraw one; and for
story 19.2: the coordinator's queue and record of them, and approving or rejecting one.

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
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, contains_eager

from app.auth.models import User
from app.auth.permissions import RoleCode
from app.bookings import service as bookings_service
from app.change_requests.models import ChangeRequestField, ChangeRequestStatus, EventChangeRequest
from app.change_requests.schemas import (
    AttendanceChangeIn,
    ChangeRequestIn,
    ChangeRequestRejectionIn,
    EquipmentChangeIn,
    ProposedSchedule,
    ScheduleChangeIn,
    VenueRequirementsChangeIn,
)
from app.common.audit import record_audit
from app.equipment import service as equipment_service
from app.events import service as events_service
from app.events.models import EquipmentRequestStatus, Event, EventStatus, VenueRequirement
from app.events.schemas import EventEquipmentIn, VenueRequirementIn
from app.notifications.service import NotificationType, active_members, notify

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
    db: Session, event_id: uuid.UUID, change_request_id: uuid.UUID, *, actor: User
) -> EventChangeRequest:
    """AC2: the assigned coordinator approves a pending change request. The decision, the change
    to the event, the notifications and the audit entries - the decision's, and the change's on
    the event's own history (7.4) - are written in one commit; a refusal after the request was
    claimed rolls all of it back, so the request stays pending and the event unchanged (AC5, AC7,
    AC8)."""
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
        change = _apply_approved_change(db, event, request, actor=actor)
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
