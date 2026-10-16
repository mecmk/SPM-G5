"""Business logic for coordinator assignment (stories 5.1, 5.2, 5.4 and 5.5).

A submitted event waits unassigned until the Event Coordinator Lead assigns it from the unassigned
queue (story 5.4, which replaced 5.1's automatic round-robin assignment - 5.4 AC9). Once it has a
coordinator, only that coordinator may hand it to another (story 5.2). Both writes share
``_create_assignment``, so "close the old row, open the new one, update the denormalised pointer,
write the audit entry" is written once.

``assign_coordinator``:

* 5.1 AC1 an event has exactly one coordinator at a time - assigning closes the previous open
  assignment before opening the new one, so ``uq_event_coordinator_assignments_current`` always
  sees at most one open row per event, and ``events.assigned_coordinator_id`` is updated in the
  same transaction;
* 5.1 AC2 only active users holding the Event Coordinator role can be selected - the pick-list
  offers only those, each with their number of active events (5.4 AC3), and the role is
  re-checked on the way in;
* 5.1 AC3 / 5.4 AC3 the assignment records who made it and when - ``assigned_by_id`` /
  ``assigned_at``, plus an ``EVENT_COORDINATOR_ASSIGNED`` audit entry;
* 5.4 AC7/AC9 an unassigned event is assigned only by a holder of ``events:assign`` (the Lead);
  5.2 AC6 an assigned one is reassigned only by its current coordinator;
* 5.4 AC8 of two Leads assigning one event at once, the conditional update in
  ``_create_assignment`` lets only the first through, and the second is told who got it.

Story 5.5 reads it all back for the Lead: every active event with its coordinator and the Lead
who assigned it (``list_active_events``), and each coordinator's active events
(``list_workloads``).

Routers translate the exceptions raised here into HTTP statuses (see router.py).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Subquery, and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.permissions import Permission, RoleCode, role_has
from app.common.audit import record_audit
from app.coordination.models import EventCoordinatorAssignment
from app.coordination.schemas import AssignCoordinatorIn
from app.events.models import Event, EventStatus
from app.notifications.service import NotificationType, notify

# AC1 says a *submitted* event gets a coordinator: a DRAFT has not been handed over yet, and a
# closed event (rejected / cancelled / completed) no longer needs an owner. Everything between
# those two ends is assignable, which is also what story 5.2 (reassignment) needs.
ASSIGNABLE_STATUSES = frozenset(
    {
        EventStatus.UNDER_REVIEW,
        EventStatus.CLARIFICATION_REQUESTED,
        EventStatus.PLANNING,
        EventStatus.AWAITING_SAFETY_CHECK,
        EventStatus.CONFIRMED,
    }
)


# Story 5.4 AC7/AC9 and AC8: the refusals a Lead's or a coordinator's assignment can meet.
NOT_PERMITTED_TO_ASSIGN_MESSAGE = (
    "Only the Event Coordinator Lead can assign an event that has no coordinator yet."
)
ALREADY_ASSIGNED_MESSAGE = "This event has already been assigned to {coordinator}."
NOT_AN_ACTIVE_STATUS_MESSAGE = "Filter by one of the active statuses: {statuses}."

# Story 5.5 AC1 (PO decision P5): the coordinator filter's value for events with no coordinator.
UNASSIGNED = "unassigned"


class EventNotFound(LookupError):
    pass


class EventAccessDenied(PermissionError):
    pass


class EventNotAssignable(ValueError):
    """The event is in a status that may not be given a coordinator (AC1)."""

    def __init__(self, status: str):
        super().__init__(
            f"An event with status {status} cannot be assigned a coordinator; "
            f"allowed statuses are {', '.join(sorted(ASSIGNABLE_STATUSES))}."
        )
        self.status = status


class CoordinatorNotFound(LookupError):
    def __init__(self, coordinator_id: uuid.UUID):
        super().__init__(f"No user with id {coordinator_id}.")
        self.coordinator_id = coordinator_id


class NotACoordinator(ValueError):
    """AC2: the chosen user does not hold the Event Coordinator role."""

    def __init__(self, user: User):
        super().__init__(
            f"{user.full_name} holds the {user.role_code} role; "
            f"only {RoleCode.EVENT_COORDINATOR} users can be assigned."
        )
        self.user = user


class CoordinatorInactive(ValueError):
    def __init__(self, user: User):
        super().__init__(f"{user.full_name} is no longer an active user.")
        self.user = user


class NotCurrentCoordinator(PermissionError):
    """Story 5.2 AC6: once an event has a coordinator, only that coordinator may reassign it. An
    unassigned event is the Lead's to assign (story 5.4 AC9: ``NotPermittedToAssign``)."""

    def __init__(self) -> None:
        super().__init__("Only the coordinator currently assigned to this event may reassign it.")


class NotPermittedToAssign(PermissionError):
    """Story 5.4 AC7/AC9: an unassigned event is assigned only by the Event Coordinator Lead -
    Event Coordinators no longer claim one by hand."""

    def __init__(self) -> None:
        super().__init__(NOT_PERMITTED_TO_ASSIGN_MESSAGE)


class AlreadyAssigned(RuntimeError):
    """Story 5.4 AC8: the event already has a coordinator - assigned just now by another Lead, or
    before - and the message says who."""

    def __init__(self, coordinator: User) -> None:
        super().__init__(ALREADY_ASSIGNED_MESSAGE.format(coordinator=coordinator.full_name))
        self.coordinator = coordinator


class NotAnActiveStatus(ValueError):
    """Story 5.5 AC1: the overview's status filter offers only the active statuses (P1)."""

    def __init__(self, status: str) -> None:
        super().__init__(
            NOT_AN_ACTIVE_STATUS_MESSAGE.format(statuses=", ".join(sorted(ASSIGNABLE_STATUSES)))
        )
        self.status = status


class AssignmentChanged(RuntimeError):
    """Story 5.2 AC7: the event's coordinator changed between when this request read it and when
    it tried to write - another (re)assignment won the race. Never partially applied: nothing
    about the event or its history is touched when this is raised."""

    def __init__(self, event_id: uuid.UUID) -> None:
        super().__init__(
            "This event's coordinator changed just now. Reload the event and try again."
        )
        self.event_id = event_id


# --- reads -------------------------------------------------------------------------------
@dataclass(frozen=True)
class CoordinatorWorkload:
    """Story 5.4 AC3: a selectable coordinator, and how many active events they hold now."""

    coordinator: User
    active_event_count: int


def _active_event_counts() -> Subquery:
    """Each coordinator's number of active events (``ASSIGNABLE_STATUSES``, PO decision), as a
    subquery to outer-join users onto (5.4 AC3, 5.5 AC2). Counted per coordinator here rather than
    by grouping the users, which would clash with the role ``User`` loads eagerly by a join."""
    return (
        select(Event.assigned_coordinator_id, func.count().label("active_event_count"))
        .where(Event.status.in_(ASSIGNABLE_STATUSES))
        .group_by(Event.assigned_coordinator_id)
        .subquery()
    )


def list_coordinators(
    db: Session, *, exclude_event_id: uuid.UUID | None = None
) -> list[CoordinatorWorkload]:
    """5.1 AC2: the users that may be selected - active holders of the Event Coordinator role.
    Story 5.4 AC3: each with their number of active events - assigned to them and still open
    (``ASSIGNABLE_STATUSES``, PO decision) - counted in the same query, so it is never stale.

    Story 5.2 AC4: pass ``exclude_event_id`` for the reassignment picker, which must leave that
    event's current coordinator out - they are not a valid target for their own event.
    """
    counts = _active_event_counts()
    query = (
        select(User, func.coalesce(counts.c.active_event_count, 0))
        .outerjoin(counts, counts.c.assigned_coordinator_id == User.id)
        .where(User.role_code == RoleCode.EVENT_COORDINATOR, User.is_active.is_(True))
    )
    if exclude_event_id is not None:
        current = current_assignment(db, exclude_event_id)
        if current is not None:
            query = query.where(User.id != current.coordinator_id)
    return [
        CoordinatorWorkload(coordinator=user, active_event_count=count)
        for user, count in db.execute(query.order_by(User.full_name)).all()
    ]


def list_unassigned_events(db: Session) -> list[Event]:
    """Story 5.4 AC2: every submitted event that is still open and has no coordinator, oldest
    submission first (ties broken by id, so the order is stable). A draft is not submitted, and a
    rejected, cancelled or completed event needs no owner, so neither waits here."""
    return list(
        db.scalars(
            select(Event)
            .where(
                Event.assigned_coordinator_id.is_(None),
                Event.status.in_(ASSIGNABLE_STATUSES),
            )
            .order_by(Event.submitted_at, Event.id)
        ).all()
    )


@dataclass(frozen=True)
class ActiveEvent:
    """Story 5.5 AC1: an active event, and the Lead who assigned its current coordinator - None
    when nobody is assigned, or when the assigner was not a Lead (PO decision P3)."""

    event: Event
    assigning_lead: User | None


def _assigning_lead(assignment: EventCoordinatorAssignment | None) -> User | None:
    """P3: the assigner, if they hold ``events:assign`` - checked by permission, not role name."""
    if assignment is None or assignment.assigned_by is None:
        return None
    assigner = assignment.assigned_by
    return assigner if role_has(assigner.role_code, Permission.EVENTS_ASSIGN) else None


def list_active_events(
    db: Session,
    *,
    coordinator: uuid.UUID | str | None = None,
    status: str | None = None,
    assigned_by: User | None = None,
) -> list[ActiveEvent]:
    """Story 5.5 AC1: every active event (P1: ``ASSIGNABLE_STATUSES``), soonest first, ties broken
    by id. Each filter narrows the list, and they combine:

    * ``coordinator`` - one coordinator's events, or ``UNASSIGNED`` for those with none (P5);
    * ``status`` - one of the active statuses; anything else raises ``NotAnActiveStatus``;
    * ``assigned_by`` - the events whose current assignment this Lead made (P2).

    The current assignment row is joined on in the same query, for who made it."""
    if status is not None and status not in ASSIGNABLE_STATUSES:
        raise NotAnActiveStatus(status)
    current = and_(
        EventCoordinatorAssignment.event_id == Event.id,
        EventCoordinatorAssignment.unassigned_at.is_(None),
    )
    query = (
        select(Event, EventCoordinatorAssignment)
        .outerjoin(EventCoordinatorAssignment, current)
        .where(Event.status.in_(ASSIGNABLE_STATUSES))
    )
    if coordinator == UNASSIGNED:
        query = query.where(Event.assigned_coordinator_id.is_(None))
    elif coordinator is not None:
        query = query.where(Event.assigned_coordinator_id == coordinator)
    if status is not None:
        query = query.where(Event.status == status)
    if assigned_by is not None:
        query = query.where(EventCoordinatorAssignment.assigned_by_id == assigned_by.id)
    rows = db.execute(query.order_by(Event.starts_at, Event.id)).all()
    return [
        ActiveEvent(event=event, assigning_lead=_assigning_lead(assignment))
        for event, assignment in rows
    ]


@dataclass(frozen=True)
class CoordinatorEvents:
    """Story 5.5 AC2: a coordinator, how many active events they hold, and those events."""

    coordinator: User
    active_event_count: int
    events: list[Event]


def list_workloads(db: Session) -> list[CoordinatorEvents]:
    """Story 5.5 AC2: every Event Coordinator with their active events, by name. AC4: one with
    none is listed with 0 (the outer join keeps them). AC5 (PO decision P4): a deactivated
    coordinator is listed only while they still hold active events, so the Lead can reassign them;
    ``is_active`` on the user flags them.

    One query whatever the team's size: each coordinator outer-joined to their active events, so
    the count is the number of events listed and the two cannot disagree, even while an
    assignment lands between reads."""
    is_active_event = and_(
        Event.assigned_coordinator_id == User.id, Event.status.in_(ASSIGNABLE_STATUSES)
    )
    rows = db.execute(
        select(User, Event)
        .outerjoin(Event, is_active_event)
        .where(
            User.role_code == RoleCode.EVENT_COORDINATOR,
            or_(User.is_active.is_(True), Event.id.is_not(None)),
        )
        .order_by(User.full_name, User.id, Event.starts_at, Event.id)
    ).all()
    by_coordinator: dict[uuid.UUID, tuple[User, list[Event]]] = {}
    for user, event in rows:
        _, events = by_coordinator.setdefault(user.id, (user, []))
        if event is not None:
            events.append(event)
    return [
        CoordinatorEvents(coordinator=user, active_event_count=len(events), events=events)
        for user, events in by_coordinator.values()
    ]


def get_event(db: Session, event_id: uuid.UUID) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        raise EventNotFound(event_id)
    return event


def current_assignment(db: Session, event_id: uuid.UUID) -> EventCoordinatorAssignment | None:
    """The open assignment for an event (``unassigned_at IS NULL``), or None."""
    return db.scalars(
        select(EventCoordinatorAssignment).where(
            EventCoordinatorAssignment.event_id == event_id,
            EventCoordinatorAssignment.unassigned_at.is_(None),
        )
    ).one_or_none()


def assert_can_view(user: User, event: Event) -> None:
    """Internal staff see every event; an organiser sees their own (relationship rule)."""
    if role_has(user.role_code, Permission.EVENTS_READ_ALL):
        return
    if role_has(user.role_code, Permission.EVENTS_READ_OWN) and event.organiser_id == user.id:
        return
    raise EventAccessDenied(event.id)


def get_event_coordinator(
    db: Session, event_id: uuid.UUID, *, actor: User
) -> EventCoordinatorAssignment | None:
    """AC4: who currently owns this event. None when nobody is assigned yet."""
    event = get_event(db, event_id)
    assert_can_view(actor, event)
    return current_assignment(db, event_id)


# --- writes ------------------------------------------------------------------------------


def _notify_reassignment(
    db: Session,
    event: Event,
    *,
    previous_coordinator_id: uuid.UUID,
    new_coordinator: User,
    reassigned_by: User,
) -> None:
    """Story 5.2 AC1: the previous coordinator, the new one, and the organiser are each told.
    Only called for a genuine reassignment (there was a previous coordinator) - an event's first
    assignment, by the Lead, has nobody "previous" to tell and is told by ``_notify_assignment``
    instead (story 5.4 AC4). Story 20.1 AC3 tells nobody of their own
    action, and under 5.2 the previous coordinator is the one reassigning (AC6), so in practice
    they are skipped; they are told when someone else reassigns, as the Lead will (story 5.6)."""
    previous_coordinator = db.get(User, previous_coordinator_id)
    organiser = db.get(User, event.organiser_id)
    notify(
        db,
        recipient=previous_coordinator,
        actor=reassigned_by,
        notification_type=NotificationType.EVENT_REASSIGNED_FROM,
        event_id=event.id,
        title=f'"{event.name}" was reassigned',
        message=f'{reassigned_by.full_name} handed "{event.name}" to {new_coordinator.full_name}.',
        related_entity_type="event",
        related_entity_id=event.id,
        commit=False,
    )
    notify(
        db,
        recipient=new_coordinator,
        actor=reassigned_by,
        notification_type=NotificationType.EVENT_REASSIGNED_TO,
        event_id=event.id,
        title=f'You are now assigned to "{event.name}"',
        message=f'{reassigned_by.full_name} handed you "{event.name}".',
        related_entity_type="event",
        related_entity_id=event.id,
        commit=False,
    )
    notify(
        db,
        recipient=organiser,
        actor=reassigned_by,
        notification_type=NotificationType.EVENT_REASSIGNED_ORGANISER,
        event_id=event.id,
        title=f'"{event.name}" has a new coordinator',
        message=f'{new_coordinator.full_name} is now the coordinator for "{event.name}".',
        related_entity_type="event",
        related_entity_id=event.id,
        commit=False,
    )


def _notify_assignment(db: Session, event: Event, *, coordinator: User, assigned_by: User) -> None:
    """Story 5.4 AC4: an event's first coordinator, and its organiser, are each told of the Lead's
    assignment (20.1). Nobody is told of their own action (20.1 AC3)."""
    organiser = db.get(User, event.organiser_id)
    notify(
        db,
        recipient=coordinator,
        actor=assigned_by,
        notification_type=NotificationType.EVENT_ASSIGNED_TO,
        event_id=event.id,
        title=f'You are assigned to "{event.name}"',
        message=f'{assigned_by.full_name} assigned "{event.name}" to you for review.',
        related_entity_type="event",
        related_entity_id=event.id,
        commit=False,
    )
    notify(
        db,
        recipient=organiser,
        actor=assigned_by,
        notification_type=NotificationType.EVENT_ASSIGNED_ORGANISER,
        event_id=event.id,
        title=f'"{event.name}" has a coordinator',
        message=f'{coordinator.full_name} is now the coordinator for "{event.name}".',
        related_entity_type="event",
        related_entity_id=event.id,
        commit=False,
    )


def _create_assignment(
    db: Session,
    event: Event,
    coordinator: User,
    *,
    previous: EventCoordinatorAssignment | None,
    assigned_by: User,
    note: str | None,
) -> EventCoordinatorAssignment:
    """Shared machinery behind ``assign_coordinator`` - the Lead's first assignment (5.4) and a
    coordinator's reassignment (5.2), ``assigned_by`` being who chose it: close any open
    assignment, open the new one, keep ``events.assigned_coordinator_id`` in step, and write the
    audit entry. Does not commit - the caller owns the transaction.

    ``previous`` is the caller's *own* read of ``current_assignment`` - the same one it already
    used to decide the caller is allowed to do this (5.2 AC6) - not re-read here. Re-reading it
    fresh at this point would defeat AC7's guard below: it would let this call "self-heal" past
    exactly the staleness the guard exists to catch, silently adopting whatever changed instead
    of noticing it changed.

    Re-assigning the coordinator who already holds the event is a no-op: it returns the existing
    assignment rather than closing and re-opening it, so the history in
    ``event_coordinator_assignments`` stays meaningful.

    Story 5.2 AC7: the write is conditional on ``events.assigned_coordinator_id`` still holding
    whatever ``previous`` said it did (``NULL`` when there was no previous coordinator) - the
    same "attempt and catch the failure" shape as ``submit_event``'s conditional UPDATE. Two
    reassignments that both read the same ``previous`` cannot both succeed: the second finds 0
    rows match and raises ``AssignmentChanged`` before touching anything else, rather than
    silently overwriting the first.
    """
    if previous is not None and previous.coordinator_id == coordinator.id:
        return previous

    expected_coordinator_id = previous.coordinator_id if previous is not None else None
    claimed = db.execute(
        update(Event)
        .where(
            Event.id == event.id,
            Event.assigned_coordinator_id.is_(expected_coordinator_id)
            if expected_coordinator_id is None
            else Event.assigned_coordinator_id == expected_coordinator_id,
        )
        .values(assigned_coordinator_id=coordinator.id)
    )
    if claimed.rowcount == 0:
        raise AssignmentChanged(event.id)

    if previous is not None:
        # Close the old row *and flush it* before inserting the new one, otherwise the partial
        # unique index would briefly see two open assignments for this event. Safe unconditionally
        # here: the guarded UPDATE above already proved nobody else changed the pointer since we
        # read ``previous``, so this is still the one open row for this event.
        previous.unassigned_at = func.now()
        db.flush()

    assignment = EventCoordinatorAssignment(
        event_id=event.id,
        coordinator_id=coordinator.id,
        assigned_by_id=assigned_by.id,
        # Stamped from Python, not the column's server_default: ``now()`` is transaction-start
        # time, so several assignments made in one transaction would otherwise tie on
        # ``assigned_at`` and leave the history's order ambiguous. Same pattern as
        # ``submitted_at``/``decided_at`` in events/service.py.
        assigned_at=datetime.now(UTC),
        note=note,
    )
    db.add(assignment)
    event.assigned_coordinator_id = coordinator.id  # keep the denormalised pointer in step
    db.flush()

    record_audit(
        db,
        actor=assigned_by,
        action="EVENT_COORDINATOR_ASSIGNED",
        entity_type="event",
        entity_id=event.id,
        details={
            "coordinator_id": str(coordinator.id),
            "coordinator_name": coordinator.full_name,
            "previous_coordinator_id": (
                str(previous.coordinator_id) if previous is not None else None
            ),
            "note": note,
        },
        commit=False,
    )

    if previous is None:
        _notify_assignment(db, event, coordinator=coordinator, assigned_by=assigned_by)
    else:
        _notify_reassignment(
            db,
            event,
            previous_coordinator_id=previous.coordinator_id,
            new_coordinator=coordinator,
            reassigned_by=assigned_by,
        )

    return assignment


def assign_coordinator(
    db: Session, event_id: uuid.UUID, data: AssignCoordinatorIn, *, actor: User
) -> EventCoordinatorAssignment:
    """Give ``event_id`` a coordinator (5.1 AC1).

    Story 5.4 AC7/AC9: an unassigned event is assigned only by a holder of ``events:assign`` -
    the Event Coordinator Lead; coordinators no longer claim one. AC8: a Lead who finds it already
    assigned - before, or by another Lead a moment ago - is told so, and to whom (409).
    Story 5.2 AC6: an assigned event is handed on only by its current coordinator.
    """
    event = get_event(db, event_id)
    if event.status not in ASSIGNABLE_STATUSES:
        raise EventNotAssignable(event.status)

    is_lead = role_has(actor.role_code, Permission.EVENTS_ASSIGN)
    previous = current_assignment(db, event.id)
    if previous is None and not is_lead:
        raise NotPermittedToAssign()
    if previous is not None and is_lead:
        raise AlreadyAssigned(previous.coordinator)
    if previous is not None and previous.coordinator_id != actor.id:
        raise NotCurrentCoordinator()

    coordinator = db.get(User, data.coordinator_id)
    if coordinator is None:
        raise CoordinatorNotFound(data.coordinator_id)
    if coordinator.role_code != RoleCode.EVENT_COORDINATOR:
        raise NotACoordinator(coordinator)
    if not coordinator.is_active:
        raise CoordinatorInactive(coordinator)

    try:
        assignment = _create_assignment(
            db, event, coordinator, previous=previous, assigned_by=actor, note=data.note
        )
    except AssignmentChanged:
        # AC8: another Lead's assignment landed between this one's read and its write. The guarded
        # update changed nothing, so read who got the event (it is committed) and name them.
        winner = current_assignment(db, event.id) if is_lead else None
        if winner is None:
            raise
        raise AlreadyAssigned(winner.coordinator) from None
    db.commit()
    db.refresh(assignment)
    return assignment
