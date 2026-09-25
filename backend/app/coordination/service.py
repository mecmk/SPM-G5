"""Business logic for coordinator assignment (story 5.1).

Story 5.1 - "As an Event Coordinator, I want to assign a coordinator to a submitted event so
that it has a clear internal owner":

* AC1 a submitted event can be assigned to exactly one coordinator at a time - assigning
  closes the previous open assignment before opening the new one, so
  ``uq_event_coordinator_assignments_current`` always sees at most one open row per event, and
  ``events.assigned_coordinator_id`` is updated in the same transaction;
* AC2 only users holding the Event Coordinator role can be selected - ``list_coordinators``
  offers only those users and ``assign_coordinator`` re-checks the role on the way in;
* AC3 the assignment records who assigned it and when - ``assigned_by_id`` / ``assigned_at``,
  plus an ``EVENT_COORDINATOR_ASSIGNED`` audit entry;
* AC4 the assigned coordinator's name is visible on the event - ``current_assignment`` reads
  the open row with the coordinator eagerly loaded.

Routers translate the exceptions raised here into HTTP statuses (see router.py).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.permissions import Permission, RoleCode, role_has
from app.common.audit import record_audit
from app.coordination.models import EventCoordinatorAssignment
from app.coordination.schemas import AssignCoordinatorIn
from app.events.models import Event, EventStatus

# AC1 says a *submitted* event gets a coordinator: a DRAFT has not been handed over yet, and a
# closed event (rejected / cancelled / completed) no longer needs an owner. Everything between
# those two ends is assignable, which is also what story 5.2 (reassignment) needs. Bug b6.1.1:
# SUBMITTED and APPROVED were retired (migration 002) - UNDER_REVIEW and PLANNING already cover
# the ground they used to.
ASSIGNABLE_STATUSES = frozenset(
    {
        EventStatus.UNDER_REVIEW,
        EventStatus.CLARIFICATION_REQUESTED,
        EventStatus.PLANNING,
        EventStatus.CONFIRMED,
    }
)


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


# --- reads -------------------------------------------------------------------------------
def list_coordinators(db: Session) -> list[User]:
    """AC2: the users that may be selected - active holders of the Event Coordinator role."""
    return list(
        db.scalars(
            select(User)
            .where(User.role_code == RoleCode.EVENT_COORDINATOR, User.is_active.is_(True))
            .order_by(User.full_name)
        ).all()
    )


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
def assign_coordinator(
    db: Session, event_id: uuid.UUID, data: AssignCoordinatorIn, *, actor: User
) -> EventCoordinatorAssignment:
    """Give ``event_id`` a coordinator, replacing whoever held it before (AC1).

    Re-assigning the coordinator who already holds the event is a no-op: it returns the
    existing assignment rather than closing and re-opening it, so the history in
    ``event_coordinator_assignments`` stays meaningful.
    """
    event = get_event(db, event_id)
    if event.status not in ASSIGNABLE_STATUSES:
        raise EventNotAssignable(event.status)

    coordinator = db.get(User, data.coordinator_id)
    if coordinator is None:
        raise CoordinatorNotFound(data.coordinator_id)
    if coordinator.role_code != RoleCode.EVENT_COORDINATOR:
        raise NotACoordinator(coordinator)
    if not coordinator.is_active:
        raise CoordinatorInactive(coordinator)

    previous = current_assignment(db, event_id)
    if previous is not None and previous.coordinator_id == coordinator.id:
        return previous

    if previous is not None:
        # Close the old row *and flush it* before inserting the new one, otherwise the partial
        # unique index would briefly see two open assignments for this event.
        previous.unassigned_at = func.now()
        db.flush()

    assignment = EventCoordinatorAssignment(
        event_id=event.id,
        coordinator_id=coordinator.id,
        assigned_by_id=actor.id,  # AC3: who assigned it (assigned_at defaults to now()).
        note=data.note,
    )
    db.add(assignment)
    event.assigned_coordinator_id = coordinator.id  # keep the denormalised pointer in step
    db.flush()

    record_audit(
        db,
        actor=actor,
        action="EVENT_COORDINATOR_ASSIGNED",
        entity_type="event",
        entity_id=event.id,
        details={
            "coordinator_id": str(coordinator.id),
            "coordinator_name": coordinator.full_name,
            "previous_coordinator_id": (
                str(previous.coordinator_id) if previous is not None else None
            ),
            "note": data.note,
        },
        commit=False,
    )
    db.commit()
    db.refresh(assignment)
    return assignment
