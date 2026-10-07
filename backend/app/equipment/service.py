"""Business rules for an event's equipment items (story 15.1): the assigned coordinator records
them, starting from what the organiser asked for (story 2.1), and submits them to Technical
Support, who are told of each submission (story 20.1).

Story 15.1 - "As an Event Coordinator I want to record the equipment an event needs, starting from
what the organiser asked for, and submit it to Technical Support, with each item held for the
event's period until Technical Support decides, so that Technical Support can arrange it and
nothing is double-committed."

Holding (AC2, AC3). Every open item on a submitted event holds its quantity for the event's period
as an ``EquipmentReservation``: the organiser's from the event's submission (2.1 AC11), the
coordinator's from when they are saved. Availability is 2.1's calculation
(``events.service.available_by_type``), with the event's own holds counted as available to it, so
an item can always keep what it already has.

Concurrency (AC10). Writes are serialised by row locks, taken in one order - the event, then the
equipment types by id - so two of them cannot deadlock:

* the event row, so two writes to one event's equipment (a double-click on Save or Submit) run one
  after the other, and the second sees what the first did;
* each equipment type row, as 2.1's submission hold already does, so two events cannot both take
  the last units of a type.

The checks made under those locks cannot race, which is why "a type is open only once on an event"
(AC6) is checked rather than left to a unique index: such an index would also refuse 2.1's draft
edit that removes a line and adds the same type back, since the ORM inserts before it deletes
within one flush.

Who and when (AC9): only the event's assigned coordinator, and only while the event is Under
Review, Clarification Requested or Planning. A draft is private to its organiser (2.1 AC8), so it
is not found. Item statuses are ``EquipmentRequestStatus``; ACCEPTED and DECLINED are Technical
Support's to set (story 16.1), and an item in either is locked (AC7).

Story 15.2 - "As a Technical Support Staff member I want to see the equipment requests waiting for
me, with what is available for each, so that I can work through them in a sensible order." The
queue (``list_equipment_requests``) only reads: deciding a request is story 16.1.

Story 16.1 - "As a Technical Support Staff member I want to accept an equipment request, reserving
the equipment, or decline it with a reason, so that the coordinator knows whether the equipment is
secured or another plan is needed." ``decide_equipment_request`` keeps a Pending item's hold as its
reservation on accepting, or releases it on declining, in the same transaction as the decision.
It takes the event's row lock first, as every write above does, so a decision is serialised with
the coordinator's edits and with another decision on the same request (AC9), and the lock order -
the event, then the types - still holds.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from app.auth.models import User
from app.auth.permissions import RoleCode
from app.common.audit import record_audit
from app.equipment.schemas import (
    EquipmentDecisionIn,
    EquipmentDecisionOutcome,
    EquipmentItemIn,
    EquipmentItemUpdate,
    EquipmentQueueStatus,
    EventEquipmentAvailabilityOut,
)
from app.events import service as events_service
from app.events.models import (
    EquipmentHoldStatus,
    EquipmentRequestStatus,
    EquipmentReservation,
    EquipmentType,
    Event,
    EventEquipmentRequest,
    EventStatus,
)
from app.notifications.service import NotificationType, active_members, notify

NOT_ASSIGNED_COORDINATOR_MESSAGE = (
    "Only the coordinator assigned to this event can change its equipment."
)
EQUIPMENT_CLOSED_MESSAGE = "This event is {status}, so its equipment can no longer be changed."
ITEM_CLOSED_MESSAGE = "This equipment item is {status}, so it can no longer be changed."
TYPE_ALREADY_REQUESTED_MESSAGE = "This event already has an open request for {name}."
NOT_ENOUGH_AVAILABLE_MESSAGE = "Not enough {name} available for this event's dates."
NOTHING_TO_SUBMIT_MESSAGE = "There is no equipment waiting to be sent to Technical Support."
UNKNOWN_EQUIPMENT_TYPE_MESSAGE = "Unknown equipment type: {code}."
# Story 16.1 AC6. The shortfall's figures go beside the sentence, never in it (backend/STYLE.md).
NOT_ENOUGH_TO_ACCEPT_MESSAGE = (
    "Not enough {name} is available for this event's dates to accept this request."
)
DECISION_CLOSED_MESSAGE = (
    "This event is {status}, so its equipment requests can no longer be decided."
)
# AC7/AC9: why a request that is not Pending cannot be decided, one sentence per status.
NOT_PENDING_MESSAGES = {
    EquipmentRequestStatus.REQUESTED: (
        "This equipment request has not been sent to Technical Support yet."
    ),
    EquipmentRequestStatus.ACCEPTED: "This equipment request has already been accepted.",
    EquipmentRequestStatus.DECLINED: "This equipment request has already been declined.",
    EquipmentRequestStatus.UNAVAILABLE: (
        "This equipment request no longer fits its event's dates and is waiting for the "
        "coordinator."
    ),
    EquipmentRequestStatus.CANCELLED: "This equipment request was cancelled with its event.",
}

# AC9: the event statuses in which the assigned coordinator may change its equipment.
_OPEN_EVENT_STATUSES = frozenset(
    {EventStatus.UNDER_REVIEW, EventStatus.CLARIFICATION_REQUESTED, EventStatus.PLANNING}
)
# AC2/AC7: the items the coordinator may still edit or remove.
_EDITABLE_ITEM_STATUSES = frozenset(
    {
        EquipmentRequestStatus.REQUESTED,
        EquipmentRequestStatus.PENDING,
        EquipmentRequestStatus.UNAVAILABLE,
    }
)
# AC6: an item in one of these takes up its type on the event; a declined or cancelled one does not.
_OPEN_ITEM_STATUSES = _EDITABLE_ITEM_STATUSES | {EquipmentRequestStatus.ACCEPTED}
# AC8: a sent item whose decision was for the old dates goes back to Technical Support.
_SENT_ITEM_STATUSES = frozenset({EquipmentRequestStatus.PENDING, EquipmentRequestStatus.ACCEPTED})
# Story 15.2 AC5: an event that will not go ahead. Rejecting leaves its items as they were, so
# the queue leaves them out by the event's status rather than the item's.
_CLOSED_QUEUE_EVENT_STATUSES = (EventStatus.CANCELLED, EventStatus.REJECTED)
# Story 16.1 AC7: an event whose equipment can no longer be decided - the same events the queue
# leaves out (15.2 AC5).
_DECISION_CLOSED_EVENT_STATUSES = frozenset(_CLOSED_QUEUE_EVENT_STATUSES)
# Why each hold was placed, in ``equipment_reservations.notes``.
_RECORDED_HOLD_NOTE = "Held for the coordinator's equipment request."
_MOVED_HOLD_NOTE = "Held again for the event's new dates."
_ACCEPTED_HOLD_NOTE = "Reserved when Technical Support accepted the request."


def _as_words(status: str) -> str:
    """A status as it reads in a sentence: CLARIFICATION_REQUESTED -> "clarification requested"."""
    return status.lower().replace("_", " ")


class EventNotFound(LookupError):
    """AC9: no such event, or a draft, which is private to its organiser (2.1 AC8)."""


class EquipmentItemNotFound(LookupError):
    """No such item on this event."""


class NotAssignedCoordinator(PermissionError):
    """AC9: only the event's assigned coordinator may change its equipment. A relationship rule,
    not a role rule - every coordinator holds ``equipment:request`` - so it needs the event."""

    def __init__(self) -> None:
        super().__init__(NOT_ASSIGNED_COORDINATOR_MESSAGE)


class UnknownEquipmentType(ValueError):
    """AC6: the type does not exist, or is inactive and no longer offered (a 422)."""

    def __init__(self, code: str) -> None:
        super().__init__(UNKNOWN_EQUIPMENT_TYPE_MESSAGE.format(code=code))


class EquipmentConflict(RuntimeError):
    """The event, the item or the stock is not in the state this change needs (a 409)."""


class EquipmentClosed(EquipmentConflict):
    """AC9: the event is no longer Under Review, Clarification Requested or Planning."""

    def __init__(self, event: Event) -> None:
        super().__init__(EQUIPMENT_CLOSED_MESSAGE.format(status=_as_words(event.status)))


class ItemClosed(EquipmentConflict):
    """AC7: Technical Support has decided the item, or its event was cancelled."""

    def __init__(self, item: EventEquipmentRequest) -> None:
        super().__init__(ITEM_CLOSED_MESSAGE.format(status=_as_words(item.status)))


class TypeAlreadyRequested(EquipmentConflict):
    """AC6/AC10: the event already has an open item of this type."""

    def __init__(self, name: str) -> None:
        super().__init__(TYPE_ALREADY_REQUESTED_MESSAGE.format(name=name))


class EquipmentNotAvailable(EquipmentConflict):
    """AC3/AC4/AC6/AC10: the event cannot have that many of this type over its period. The figure
    itself is not in the sentence (backend/STYLE.md); the form shows it from the availability."""

    def __init__(self, name: str) -> None:
        super().__init__(NOT_ENOUGH_AVAILABLE_MESSAGE.format(name=name))


class NothingToSubmit(EquipmentConflict):
    """AC1/AC10: no item is waiting to be sent - including a second click on Submit."""

    def __init__(self) -> None:
        super().__init__(NOTHING_TO_SUBMIT_MESSAGE)


class EquipmentRequestNotFound(LookupError):
    """Story 16.1: no such equipment request."""


class DecisionClosed(EquipmentConflict):
    """Story 16.1 AC7: the request's event was cancelled or rejected."""

    def __init__(self, event: Event) -> None:
        super().__init__(DECISION_CLOSED_MESSAGE.format(status=_as_words(event.status)))


class RequestNotPending(EquipmentConflict):
    """Story 16.1 AC7/AC9: only a Pending request can be decided - a second decision, a
    double-click included, is told the status the first one left."""

    def __init__(self, item: EventEquipmentRequest) -> None:
        super().__init__(NOT_PENDING_MESSAGES[item.status])


class NotEnoughToAccept(EquipmentConflict):
    """Story 16.1 AC6: the event's period no longer has the units, such as after some went out of
    service. Carries ``available`` and ``shortfall`` for the refusal to show."""

    def __init__(self, item: EventEquipmentRequest, *, available: int) -> None:
        super().__init__(NOT_ENOUGH_TO_ACCEPT_MESSAGE.format(name=item.equipment_type.name))
        self.available = available
        self.shortfall = item.quantity - available


# --- reads ---------------------------------------------------------------------------------------


def _visible_event(db: Session, event_id: uuid.UUID, *, viewer: User) -> Event:
    """AC9: the event as 2.1's ``get_event`` lets ``viewer`` see it - every internal role sees a
    submitted event, and a draft is not found."""
    try:
        return events_service.get_event(db, event_id, viewer=viewer)
    except events_service.EventNotFound:
        raise EventNotFound(event_id) from None


def _held_by_event(db: Session, event: Event) -> dict[uuid.UUID, int]:
    """AC3: the units of each type ``event``'s own holds take over its period."""
    rows = db.execute(
        select(
            EquipmentReservation.equipment_type_id,
            func.sum(EquipmentReservation.quantity - EquipmentReservation.released_quantity),
        )
        .where(
            EquipmentReservation.event_id == event.id,
            EquipmentReservation.status == EquipmentHoldStatus.RESERVED,
            EquipmentReservation.starts_at < event.ends_at,
            EquipmentReservation.ends_at > event.starts_at,
        )
        .group_by(EquipmentReservation.equipment_type_id)
    ).all()
    return {type_id: int(units) for type_id, units in rows}


def available_for_event(db: Session, event: Event) -> dict[uuid.UUID, int]:
    """AC3: the units of each type ``event`` can have over its period - what is free, plus what it
    already holds, so an item can always keep its own quantity."""
    free = events_service.available_by_type(db, event.starts_at, event.ends_at)
    own = _held_by_event(db, event)
    return {type_id: units + own.get(type_id, 0) for type_id, units in free.items()}


def list_event_equipment_availability(
    db: Session, event_id: uuid.UUID, *, viewer: User
) -> list[EventEquipmentAvailabilityOut]:
    """AC3: for each active type, the units the event can have over its period - the figures the
    form shows next to each type. AC6: an inactive type is not offered, so it is left out."""
    event = _visible_event(db, event_id, viewer=viewer)
    available = available_for_event(db, event)
    active_types = db.scalars(
        select(EquipmentType).where(EquipmentType.is_active.is_(True)).order_by(EquipmentType.name)
    ).all()
    return [
        EventEquipmentAvailabilityOut(
            equipment_type_code=equipment_type.code,
            equipment_type_name=equipment_type.name,
            available=available[equipment_type.id],
        )
        for equipment_type in active_types
    ]


@dataclass(frozen=True)
class EquipmentQueueRow:
    """Story 15.2 AC1/AC2: one request in Technical Support's queue, its event, and how many of its
    type the event's period has for it."""

    item: EventEquipmentRequest
    event: Event
    available: int


@dataclass(frozen=True)
class EquipmentQueueListing:
    """Story 15.2 AC3: one tab's requests, and how many requests each tab holds."""

    rows: list[EquipmentQueueRow]
    counts_by_status: dict[str, int]


def list_equipment_requests(
    db: Session, *, status: EquipmentQueueStatus | None = None
) -> EquipmentQueueListing:
    """Story 15.2 AC1/AC3: the requests in one tab, or in all three when ``status`` is ``None`` (the
    All tab), soonest event first; ties fall back to the order the items were recorded in, then
    id, so the list is stable. AC5: an item the coordinator removed is gone, and every item on a
    cancelled or rejected event is left out, whatever its own status.
    Items in a status with no tab (not yet sent, flagged unavailable, cancelled) are left out too.

    AC2: each request's ``available`` is 2.1's calculation for its event's period with the event's
    own holds left out, since a Pending item already holds its units (15.1 AC2). AC7: worked out
    afresh on every call, once per event in the tab."""
    in_queue = (
        EventEquipmentRequest.status.in_(list(EquipmentQueueStatus)),
        Event.status.not_in(_CLOSED_QUEUE_EVENT_STATUSES),
    )
    tab = (
        select(EventEquipmentRequest, Event)
        .join(Event, Event.id == EventEquipmentRequest.event_id)
        .where(*in_queue)
        .order_by(Event.starts_at, EventEquipmentRequest.created_at, EventEquipmentRequest.id)
    )
    if status is not None:
        tab = tab.where(EventEquipmentRequest.status == status)
    found = db.execute(tab).all()
    counts_by_status = dict(
        db.execute(
            select(EventEquipmentRequest.status, func.count())
            .join(Event, Event.id == EventEquipmentRequest.event_id)
            .where(*in_queue)
            .group_by(EventEquipmentRequest.status)
        ).all()
    )

    available_by_event: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    rows = []
    for item, event in found:
        if event.id not in available_by_event:
            available_by_event[event.id] = events_service.available_by_type(
                db, event.starts_at, event.ends_at, exclude_event_id=event.id
            )
        available = available_by_event[event.id][item.equipment_type_id]
        rows.append(EquipmentQueueRow(item=item, event=event, available=available))
    return EquipmentQueueListing(rows=rows, counts_by_status=counts_by_status)


def get_equipment_request(db: Session, item_id: uuid.UUID) -> EquipmentQueueRow:
    """Story 16.1: one request as the queue shows it, for its own page, where it can be decided as
    from the queue. AC7: only what the queue lists (15.2 AC3/AC5) - a request not yet sent,
    flagged, cancelled or on a cancelled or rejected event is not found."""
    found = db.execute(
        select(EventEquipmentRequest, Event)
        .join(Event, Event.id == EventEquipmentRequest.event_id)
        .where(
            EventEquipmentRequest.id == item_id,
            EventEquipmentRequest.status.in_(list(EquipmentQueueStatus)),
            Event.status.not_in(_CLOSED_QUEUE_EVENT_STATUSES),
        )
    ).first()
    if found is None:
        raise EquipmentRequestNotFound(item_id)
    item, event = found
    return EquipmentQueueRow(
        item=item, event=event, available=_available_to_accept(db, event, item)
    )


# --- writes --------------------------------------------------------------------------------------


def _event_for_change(db: Session, event_id: uuid.UUID, *, actor: User) -> Event:
    """AC9/AC10: the event, its row locked until the transaction ends, once ``actor`` is known to
    be its assigned coordinator and its equipment can still change."""
    db.execute(select(Event.id).where(Event.id == event_id).with_for_update())
    event = _visible_event(db, event_id, viewer=actor)
    if event.assigned_coordinator_id != actor.id:
        raise NotAssignedCoordinator()
    if event.status not in _OPEN_EVENT_STATUSES:
        raise EquipmentClosed(event)
    return event


def _editable_item(db: Session, event: Event, item_id: uuid.UUID) -> EventEquipmentRequest:
    """AC2/AC7: the item on ``event``, if the coordinator may still change it."""
    item = db.scalar(
        select(EventEquipmentRequest).where(
            EventEquipmentRequest.id == item_id, EventEquipmentRequest.event_id == event.id
        )
    )
    if item is None:
        raise EquipmentItemNotFound(item_id)
    if item.status not in _EDITABLE_ITEM_STATUSES:
        raise ItemClosed(item)
    return item


def _lock_types(db: Session, type_ids: Iterable[uuid.UUID]) -> None:
    """AC10: hold every other write to these types' stock until this transaction ends - in id
    order, as 2.1's submission hold takes them."""
    db.execute(
        select(EquipmentType.id)
        .where(EquipmentType.id.in_(set(type_ids)))
        .order_by(EquipmentType.id)
        .with_for_update()
    )


def _ensure_available(
    db: Session, event: Event, equipment_type: EquipmentType, quantity: int
) -> None:
    """AC3/AC4/AC10: lock the type, then refuse ``quantity`` if the event cannot have that many."""
    _lock_types(db, [equipment_type.id])
    if quantity > available_for_event(db, event)[equipment_type.id]:
        raise EquipmentNotAvailable(equipment_type.name)


def _new_hold(
    event: Event, item: EventEquipmentRequest, *, actor: User, notes: str
) -> EquipmentReservation:
    return EquipmentReservation(
        event_id=event.id,
        equipment_request_id=item.id,
        equipment_type_id=item.equipment_type_id,
        quantity=item.quantity,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        status=EquipmentHoldStatus.RESERVED,
        reserved_by_id=actor.id,
        notes=notes,
    )


def _hold(db: Session, event: Event, item: EventEquipmentRequest, *, actor: User) -> None:
    """AC2: make ``item``'s hold its quantity, placing one if it has none - a flagged item (AC8),
    or one recorded before holds existed."""
    hold = db.scalar(
        select(EquipmentReservation).where(
            EquipmentReservation.equipment_request_id == item.id,
            EquipmentReservation.status == EquipmentHoldStatus.RESERVED,
        )
    )
    if hold is None:
        db.add(_new_hold(event, item, actor=actor, notes=_RECORDED_HOLD_NOTE))
    else:
        hold.quantity = item.quantity


def _release_holds(db: Session, which: ColumnElement[bool]) -> None:
    """AC2/AC8: give back every unit the matching holds still take, at once."""
    db.execute(
        update(EquipmentReservation)
        .where(which, EquipmentReservation.status == EquipmentHoldStatus.RESERVED)
        .values(
            status=EquipmentHoldStatus.RELEASED,
            released_quantity=EquipmentReservation.quantity,
            released_at=datetime.now(UTC),
        )
    )


def add_equipment_item(
    db: Session, event_id: uuid.UUID, data: EquipmentItemIn, *, actor: User
) -> EventEquipmentRequest:
    """AC1/AC2: record an item on the event, not yet sent, and hold its quantity in the same step.
    AC3/AC4: refused, saving nothing, if the event cannot have that many. AC6: an unknown or
    inactive type, or one already open on the event, is refused."""
    event = _event_for_change(db, event_id, actor=actor)
    equipment_type = db.scalar(
        select(EquipmentType).where(
            EquipmentType.code == data.equipment_type_code, EquipmentType.is_active.is_(True)
        )
    )
    if equipment_type is None:
        raise UnknownEquipmentType(data.equipment_type_code)
    already_open = db.scalar(
        select(EventEquipmentRequest.id).where(
            EventEquipmentRequest.event_id == event.id,
            EventEquipmentRequest.equipment_type_id == equipment_type.id,
            EventEquipmentRequest.status.in_(_OPEN_ITEM_STATUSES),
        )
    )
    if already_open is not None:
        raise TypeAlreadyRequested(equipment_type.name)
    _ensure_available(db, event, equipment_type, data.quantity)

    # Stamped here rather than by the database's now(), which stands still for a whole
    # transaction, so the event lists its items in the order they were added (as 2.1 does).
    item = EventEquipmentRequest(
        event_id=event.id,
        equipment_type=equipment_type,
        quantity=data.quantity,
        technical_notes=data.technical_notes,
        status=EquipmentRequestStatus.REQUESTED,
        created_by_id=actor.id,
        created_at=datetime.now(UTC),
    )
    db.add(item)
    db.flush()
    _hold(db, event, item, actor=actor)
    record_audit(
        db,
        actor=actor,
        action="EQUIPMENT_ITEM_ADDED",
        entity_type="event",
        entity_id=event.id,
        details={
            "item_id": str(item.id),
            "equipment_type_code": equipment_type.code,
            "quantity": item.quantity,
        },
        commit=False,
    )
    db.commit()
    db.refresh(item)
    return item


def update_equipment_item(
    db: Session,
    event_id: uuid.UUID,
    item_id: uuid.UUID,
    data: EquipmentItemUpdate,
    *,
    actor: User,
) -> EventEquipmentRequest:
    """AC2: edit an item's quantity, its notes, or both. A new quantity is re-checked (AC3/AC4)
    and the item's hold adjusted in the same step; a flagged item lowered to what the event's dates
    allow is held again and waits to be sent (AC8). AC7: a decided item is locked."""
    event = _event_for_change(db, event_id, actor=actor)
    item = _editable_item(db, event, item_id)
    sent = data.model_fields_set
    if "quantity" in sent:
        _ensure_available(db, event, item.equipment_type, data.quantity)
        item.quantity = data.quantity
        _hold(db, event, item, actor=actor)
        if item.status == EquipmentRequestStatus.UNAVAILABLE:
            item.status = EquipmentRequestStatus.REQUESTED
    if "technical_notes" in sent:
        item.technical_notes = data.technical_notes
    record_audit(
        db,
        actor=actor,
        action="EQUIPMENT_ITEM_UPDATED",
        entity_type="event",
        entity_id=event.id,
        details={"item_id": str(item.id), "fields": sorted(sent)},
        commit=False,
    )
    db.commit()
    db.refresh(item)
    return item


def remove_equipment_item(
    db: Session, event_id: uuid.UUID, item_id: uuid.UUID, *, actor: User
) -> None:
    """AC2: remove an item, releasing its hold at once. AC7: a decided item is locked."""
    event = _event_for_change(db, event_id, actor=actor)
    item = _editable_item(db, event, item_id)
    _release_holds(db, EquipmentReservation.equipment_request_id == item.id)
    record_audit(
        db,
        actor=actor,
        action="EQUIPMENT_ITEM_REMOVED",
        entity_type="event",
        entity_id=event.id,
        details={
            "item_id": str(item.id),
            "equipment_type_code": item.equipment_type.code,
            "quantity": item.quantity,
        },
        commit=False,
    )
    db.delete(item)
    db.commit()


def _describe_items(items: Iterable[EventEquipmentRequest]) -> str:
    """The items as one phrase, in the order given: "Wireless microphone ×6, Presentation
    laptop ×2", as the event page shows a quantity."""
    return ", ".join(f"{item.equipment_type.name} ×{item.quantity}" for item in items)


def _notify_technical_support(
    db: Session, event: Event, items: Iterable[EventEquipmentRequest], *, actor: User
) -> None:
    """Story 20.1 AC1: the items now wait for Technical Support (15.2's queue), so every active
    Technical Support member is told which event they are for, what they are and who sent them -
    as Venue Staff are told of a new booking request."""
    message = f'{actor.full_name} requested equipment for "{event.name}": {_describe_items(items)}.'
    for member in active_members(db, role_code=RoleCode.TECH_SUPPORT_STAFF):
        notify(
            db,
            recipient=member,
            actor=actor,
            notification_type=NotificationType.EQUIPMENT_SUBMITTED,
            event_id=event.id,
            title=f'New equipment request for "{event.name}"',
            message=message,
            related_entity_type="event",
            related_entity_id=event.id,
            commit=False,
        )


def submit_equipment(
    db: Session, event_id: uuid.UUID, *, actor: User
) -> list[EventEquipmentRequest]:
    """AC1: send every item not yet sent to Technical Support as Pending, recording who sent it
    and when. An item without a hold yet (recorded before holds existed) is held first, and if any
    no longer fits, nothing is sent (AC3). AC10: with nothing waiting - a second click - it is
    refused. Story 20.1 AC1/AC4: Technical Support are notified in the same transaction, so a
    refused or failed send tells nobody."""
    event = _event_for_change(db, event_id, actor=actor)
    waiting = db.scalars(
        select(EventEquipmentRequest)
        .where(
            EventEquipmentRequest.event_id == event.id,
            EventEquipmentRequest.status == EquipmentRequestStatus.REQUESTED,
        )
        .order_by(EventEquipmentRequest.created_at, EventEquipmentRequest.id)
    ).all()
    if not waiting:
        raise NothingToSubmit()
    held = select(EquipmentReservation.equipment_request_id).where(
        EquipmentReservation.status == EquipmentHoldStatus.RESERVED,
        EquipmentReservation.equipment_request_id.is_not(None),
    )
    unheld = db.scalars(
        select(EventEquipmentRequest).where(
            EventEquipmentRequest.id.in_([item.id for item in waiting]),
            EventEquipmentRequest.id.not_in(held),
        )
    ).all()
    if unheld:
        _lock_types(db, [item.equipment_type_id for item in unheld])
        available = available_for_event(db, event)
        for item in unheld:
            if item.quantity > available[item.equipment_type_id]:
                raise EquipmentNotAvailable(item.equipment_type.name)
        for item in unheld:
            _hold(db, event, item, actor=actor)

    submitted_at = datetime.now(UTC)
    for item in waiting:
        item.status = EquipmentRequestStatus.PENDING
        item.submitted_at = submitted_at
        item.submitted_by_id = actor.id
    _notify_technical_support(db, event, waiting, actor=actor)
    record_audit(
        db,
        actor=actor,
        action="EQUIPMENT_SUBMITTED",
        entity_type="event",
        entity_id=event.id,
        details={"item_ids": [str(item.id) for item in waiting]},
        commit=False,
    )
    db.commit()
    for item in waiting:
        db.refresh(item)
    return list(waiting)


def _locked_event_of(db: Session, item_id: uuid.UUID) -> Event:
    """Story 16.1 AC9: the event the item belongs to, its row locked until the transaction ends."""
    event_id = db.scalar(
        select(EventEquipmentRequest.event_id).where(EventEquipmentRequest.id == item_id)
    )
    if event_id is None:
        raise EquipmentRequestNotFound(item_id)
    return db.scalar(
        select(Event)
        .where(Event.id == event_id)
        .with_for_update(of=Event)
        .execution_options(populate_existing=True)
    )


def _fresh_item(db: Session, item_id: uuid.UUID) -> EventEquipmentRequest:
    """Story 16.1 AC9: the item as it stands now, so a decision made while this one waited on the
    event's lock is seen."""
    item = db.scalar(
        select(EventEquipmentRequest)
        .where(EventEquipmentRequest.id == item_id)
        .execution_options(populate_existing=True)
    )
    if item is None:
        raise EquipmentRequestNotFound(item_id)
    return item


def _available_to_accept(db: Session, event: Event, item: EventEquipmentRequest) -> int:
    """Story 16.1 AC5/AC6: the units of the item's type the event's period has for it, leaving the
    event's own holds out - the queue's figure (15.2 AC2). Adding the own hold back to an
    already-floored free count, as ``available_for_event`` does, would hide a shortfall."""
    available = events_service.available_by_type(
        db, event.starts_at, event.ends_at, exclude_event_id=event.id
    )
    return available[item.equipment_type_id]


def _reserve(db: Session, event: Event, item: EventEquipmentRequest, *, actor: User) -> None:
    """Story 16.1 AC1: keep the item's hold as its reservation, placing one if it holds nothing (an
    item sent before holds existed)."""
    hold = db.scalar(
        select(EquipmentReservation).where(
            EquipmentReservation.equipment_request_id == item.id,
            EquipmentReservation.status == EquipmentHoldStatus.RESERVED,
        )
    )
    if hold is None:
        db.add(_new_hold(event, item, actor=actor, notes=_ACCEPTED_HOLD_NOTE))


def decide_equipment_request(
    db: Session, item_id: uuid.UUID, data: EquipmentDecisionIn, *, actor: User
) -> EquipmentQueueRow:
    """Story 16.1 AC1: accept a Pending request, keeping its hold as the reservation. AC2: decline
    it with a reason, releasing its hold at once. AC3: who decided and when, saved with the hold in
    one transaction. AC5/AC6: accepting is refused, changing nothing, when the event's period no
    longer has the units. AC7: only a Pending request on an event still going ahead. AC9: the
    event's row lock serialises two decisions, so the second sees the first's status."""
    event = _locked_event_of(db, item_id)
    item = _fresh_item(db, item_id)
    if event.status in _DECISION_CLOSED_EVENT_STATUSES:
        raise DecisionClosed(event)
    if item.status != EquipmentRequestStatus.PENDING:
        raise RequestNotPending(item)

    if data.outcome == EquipmentDecisionOutcome.ACCEPTED:
        _lock_types(db, [item.equipment_type_id])
        available = _available_to_accept(db, event, item)
        if item.quantity > available:
            raise NotEnoughToAccept(item, available=available)
        _reserve(db, event, item, actor=actor)
        item.status_notes = None
        action = "EQUIPMENT_ACCEPTED"
    else:
        _release_holds(db, EquipmentReservation.equipment_request_id == item.id)
        item.status_notes = data.reason
        action = "EQUIPMENT_DECLINED"
    item.status = data.outcome
    item.decided_by_id = actor.id
    item.decided_at = datetime.now(UTC)
    record_audit(
        db,
        actor=actor,
        action=action,
        entity_type="event",
        entity_id=event.id,
        details={
            "item_id": str(item.id),
            "equipment_type_code": item.equipment_type.code,
            "quantity": item.quantity,
            "reason": data.reason,
        },
        commit=False,
    )
    db.commit()
    db.refresh(item)
    return EquipmentQueueRow(
        item=item, event=event, available=_available_to_accept(db, event, item)
    )


def recheck_equipment_for_new_dates(
    db: Session, event: Event, *, actor: User
) -> list[EventEquipmentRequest]:
    """AC8: re-check every open item against ``event``'s new dates, which the caller (story 7.2's
    correction, story 4.3's clarification answer) has just set. Runs in the caller's transaction
    and neither commits nor refuses: a shortage never blocks the date change.

    Every hold is released first, so the event's old holds do not count against its new dates.
    An item that still fits is held again for them; if it was Pending or Accepted it goes back to
    Technical Support as Pending, since that decision was for the old dates, and a flagged one
    waits to be sent again. An item that no longer fits is flagged UNAVAILABLE, holding nothing,
    for the coordinator to lower or remove. Returns the flagged items."""
    items = db.scalars(
        select(EventEquipmentRequest)
        .where(
            EventEquipmentRequest.event_id == event.id,
            EventEquipmentRequest.status.in_(_OPEN_ITEM_STATUSES),
        )
        .order_by(EventEquipmentRequest.created_at, EventEquipmentRequest.id)
    ).all()
    if not items:
        return []
    _lock_types(db, [item.equipment_type_id for item in items])
    _release_holds(db, EquipmentReservation.event_id == event.id)
    available = events_service.available_by_type(db, event.starts_at, event.ends_at)

    flagged: list[EventEquipmentRequest] = []
    resent_at = datetime.now(UTC)
    for item in items:
        if item.quantity > available[item.equipment_type_id]:
            item.status = EquipmentRequestStatus.UNAVAILABLE
            flagged.append(item)
            continue
        available[item.equipment_type_id] -= item.quantity
        db.add(_new_hold(event, item, actor=actor, notes=_MOVED_HOLD_NOTE))
        if item.status in _SENT_ITEM_STATUSES:
            item.status = EquipmentRequestStatus.PENDING
            item.submitted_at = resent_at
            # Story 16.1 AC3: a decision for the old dates no longer stands.
            item.decided_by_id = None
            item.decided_at = None
        elif item.status == EquipmentRequestStatus.UNAVAILABLE:
            item.status = EquipmentRequestStatus.REQUESTED
    record_audit(
        db,
        actor=actor,
        action="EQUIPMENT_RECHECKED",
        entity_type="event",
        entity_id=event.id,
        details={"flagged": [item.equipment_type.code for item in flagged]},
        commit=False,
    )
    return flagged
