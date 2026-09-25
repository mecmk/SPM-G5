"""Business logic for coordinator assignment (story 5.1).

Story 5.1 originally read "As an Event Coordinator, I want to assign a coordinator to a
submitted event so that it has a clear internal owner" (manual assignment, ``assign_coordinator``
below). The requirement was later extended: a submitted event now gets a coordinator
automatically, in round-robin order, and manual assign/reassign becomes how a human overrides
that choice. Both paths share ``_create_assignment`` so "close the old row, open the new one,
update the denormalised pointer, write the audit entry" is written once.

Manual assignment (``assign_coordinator``):

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

Automatic assignment (``auto_assign_next_coordinator``, called once from
``events.service.submit_event`` - see AC1/AC7):

* AC2/AC6 coordinators take turns in a fixed order (creation time, then id, so deactivating one
  does not reshuffle the rest); the next turn is whoever comes after the coordinator named by the
  most recent *automatic* assignment (AC10), wrapping around and skipping anyone inactive;
* AC3 the row is written with ``assigned_by_id IS NULL`` ("the system") and a note identifying it
  as a round-robin auto-assignment;
* AC5/AC9 an event that already has a coordinator, or a system with no active coordinators at
  all, is left exactly as it is - no override, no error;
* AC11 only users holding the Event Coordinator role are ever in the rotation;
* AC14 the whole pick is made under ``pg_advisory_xact_lock(ROUND_ROBIN_LOCK_KEY)``, released
  automatically at the end of the caller's transaction, so two submissions racing for "whose turn
  is it" are serialised rather than both reading the same answer.

Routers translate the exceptions raised here into HTTP statuses (see router.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

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
# those two ends is assignable, which is also what story 5.2 (reassignment) needs.
ASSIGNABLE_STATUSES = frozenset(
    {
        EventStatus.SUBMITTED,
        EventStatus.UNDER_REVIEW,
        EventStatus.CLARIFICATION_REQUESTED,
        EventStatus.APPROVED,
        EventStatus.PLANNING,
        EventStatus.CONFIRMED,
    }
)

# AC3: the note stored on a round-robin auto-assignment, distinguishing it in the history from a
# human's manual (re)assignment.
AUTO_ASSIGNMENT_NOTE = "Automatically assigned by round-robin rotation."

# AC14: the key for the transaction-scoped advisory lock that serialises picking "whose turn is
# it" across concurrent submissions. Arbitrary but fixed and distinctive (story 5.1); Postgres
# advisory locks share one namespace per database, so this must never collide with another
# feature's lock key.
ROUND_ROBIN_LOCK_KEY = 51001


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


def _create_assignment(
    db: Session, event: Event, coordinator: User, *, assigned_by: User | None, note: str | None
) -> EventCoordinatorAssignment:
    """Shared machinery behind both ``assign_coordinator`` (``assigned_by`` is who chose it) and
    ``auto_assign_next_coordinator`` (``assigned_by=None`` - AC3 "the system"): close any open
    assignment, open the new one, keep ``events.assigned_coordinator_id`` in step, and write the
    audit entry. Does not commit - the caller owns the transaction.

    Re-assigning the coordinator who already holds the event is a no-op: it returns the existing
    assignment rather than closing and re-opening it, so the history in
    ``event_coordinator_assignments`` stays meaningful.
    """
    previous = current_assignment(db, event.id)
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
        assigned_by_id=assigned_by.id if assigned_by is not None else None,
        # Stamped from Python, not the column's server_default: ``now()`` is transaction-start
        # time, so several assignments made in one transaction would otherwise tie on
        # ``assigned_at`` and make "the most recent automatic assignment" (AC6/AC10's rotation
        # cursor) ambiguous. Same pattern as ``submitted_at``/``decided_at`` in events/service.py.
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
            "auto_assigned": assigned_by is None,
        },
        commit=False,
    )
    return assignment


def assign_coordinator(
    db: Session, event_id: uuid.UUID, data: AssignCoordinatorIn, *, actor: User
) -> EventCoordinatorAssignment:
    """Give ``event_id`` a coordinator, replacing whoever held it before (AC1)."""
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

    assignment = _create_assignment(db, event, coordinator, assigned_by=actor, note=data.note)
    db.commit()
    db.refresh(assignment)
    return assignment


def _coordinators_in_rotation_order(db: Session) -> list[User]:
    """AC2/AC6: every Event Coordinator, active or not, ordered by when their account was made
    and then by id. This is the fixed sequence the rotation walks; deactivating someone leaves
    their slot in place (skipped, not removed) so reactivating them resumes where they left off."""
    return list(
        db.scalars(
            select(User)
            .where(User.role_code == RoleCode.EVENT_COORDINATOR)
            .order_by(User.created_at, User.id)
        ).all()
    )


def _last_auto_assigned_coordinator_id(db: Session) -> uuid.UUID | None:
    """AC10: whose turn was last, counting only automatic assignments - a manual (re)assignment
    has ``assigned_by_id`` set and is invisible here, so it cannot shift the rotation."""
    last = db.scalars(
        select(EventCoordinatorAssignment)
        .where(EventCoordinatorAssignment.assigned_by_id.is_(None))
        .order_by(
            EventCoordinatorAssignment.assigned_at.desc(), EventCoordinatorAssignment.id.desc()
        )
        .limit(1)
    ).one_or_none()
    return last.coordinator_id if last is not None else None


def _next_in_rotation(db: Session) -> User | None:
    """AC2/AC5/AC6/AC11/AC14: the coordinator whose turn is next, or ``None`` when nobody is
    eligible. Takes ``ROUND_ROBIN_LOCK_KEY`` for the rest of the caller's transaction first, so a
    second submission picking concurrently blocks until this one commits or rolls back, rather
    than both reading the same "next" answer."""
    db.execute(select(func.pg_advisory_xact_lock(ROUND_ROBIN_LOCK_KEY)))

    ordered = _coordinators_in_rotation_order(db)
    if not any(coordinator.is_active for coordinator in ordered):
        return None

    start = 0
    last_id = _last_auto_assigned_coordinator_id(db)
    if last_id is not None:
        ids = [coordinator.id for coordinator in ordered]
        if last_id in ids:
            start = ids.index(last_id) + 1

    for offset in range(len(ordered)):
        candidate = ordered[(start + offset) % len(ordered)]
        if candidate.is_active:
            return candidate
    return None  # unreachable: the ``any(...)`` check above guarantees an active candidate


def auto_assign_next_coordinator(db: Session, event: Event) -> EventCoordinatorAssignment | None:
    """AC1-AC3/AC5/AC6/AC9/AC11/AC14: give ``event`` the next coordinator in round-robin order,
    as part of the caller's transaction (no commit here - ``events.service.submit_event`` commits
    once, so a failure here rolls the whole submission back, AC15).

    Returns ``None``, leaving the event exactly as it was, when it already has a coordinator
    (AC9 - also what covers AC8's "don't reassign on resubmission", once a resubmit exists) or
    when there is nobody eligible to assign (AC5).
    """
    if current_assignment(db, event.id) is not None:
        return None
    coordinator = _next_in_rotation(db)
    if coordinator is None:
        return None
    return _create_assignment(db, event, coordinator, assigned_by=None, note=AUTO_ASSIGNMENT_NOTE)
