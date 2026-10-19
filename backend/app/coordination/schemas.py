"""Request / response shapes for coordinator assignment (stories 5.1, 5.2, 5.4, 5.5 and 5.6)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.auth.models import User
from app.coordination.models import EventCoordinatorAssignment
from app.events.models import Event


class CoordinatorOption(BaseModel):
    """One selectable coordinator (story 5.1 AC2: only Event Coordinators are offered), with how
    many active events they hold (story 5.4 AC3), so the Lead can weigh the team's workload."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str
    department: str | None = None
    active_event_count: int

    @classmethod
    def from_coordinator(cls, user: User, *, active_event_count: int) -> CoordinatorOption:
        return cls(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            department=user.department,
            active_event_count=active_event_count,
        )


class AssignCoordinatorIn(BaseModel):
    """The coordinator to give the event (5.1 AC1). Story 5.6 AC6: ``expected_coordinator_id`` is
    the coordinator the Lead saw - set to reassign from them, left out to assign an event that has
    none yet (5.4) - so a request made from a view that has since changed is refused."""

    model_config = ConfigDict(extra="forbid")

    coordinator_id: uuid.UUID
    expected_coordinator_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)


class EventCoordinatorOut(BaseModel):
    """The event's current coordinator, who assigned them and when (AC3, AC4)."""

    assignment_id: uuid.UUID
    event_id: uuid.UUID
    coordinator_id: uuid.UUID
    coordinator_name: str
    coordinator_email: str
    assigned_by_id: uuid.UUID | None
    assigned_by_name: str | None
    assigned_at: datetime
    note: str | None

    @classmethod
    def from_assignment(cls, assignment: EventCoordinatorAssignment) -> EventCoordinatorOut:
        return cls(
            assignment_id=assignment.id,
            event_id=assignment.event_id,
            coordinator_id=assignment.coordinator_id,
            coordinator_name=assignment.coordinator.full_name,
            coordinator_email=assignment.coordinator.email,
            assigned_by_id=assignment.assigned_by_id,
            assigned_by_name=assignment.assigned_by.full_name if assignment.assigned_by else None,
            assigned_at=assignment.assigned_at,
            note=assignment.note,
        )


class UnassignedEventEntry(BaseModel):
    """Story 5.4 AC2: one submitted event waiting in the Lead's unassigned queue - what the Lead
    needs to choose a coordinator for it."""

    id: uuid.UUID
    name: str
    starts_at: datetime  # non-null for every non-DRAFT row (ck_events_submitted_fields_complete)
    ends_at: datetime
    expected_attendance: int
    organiser_name: str
    submitted_at: datetime | None  # no constraint guarantees it, so the page allows for none

    @classmethod
    def from_event(cls, event: Event) -> UnassignedEventEntry:
        # The queue holds no drafts, so ck_events_submitted_fields_complete guarantees these.
        starts_at, ends_at = event.starts_at, event.ends_at
        expected_attendance = event.expected_attendance
        assert starts_at is not None
        assert ends_at is not None
        assert expected_attendance is not None
        return cls(
            id=event.id,
            name=event.name,
            starts_at=starts_at,
            ends_at=ends_at,
            expected_attendance=expected_attendance,
            organiser_name=event.organiser.full_name,
            submitted_at=event.submitted_at,
        )


class ActiveEventEntry(BaseModel):
    """Story 5.5 AC1: one active event in the Lead's overview - name, dates, status, its
    coordinator (all null when nobody is assigned yet) and the Lead who assigned them (null when
    the assigner was not a Lead, PO decision P3). AC5: ``coordinator_is_active`` false flags a
    deactivated coordinator whose events need reassigning. No defaults (response schema)."""

    id: uuid.UUID
    name: str
    starts_at: datetime  # non-null for every non-DRAFT row (ck_events_submitted_fields_complete)
    ends_at: datetime
    status: str
    coordinator_id: uuid.UUID | None
    coordinator_name: str | None
    coordinator_is_active: bool | None
    assigned_by_name: str | None

    @classmethod
    def from_event(cls, event: Event, *, assigning_lead: User | None) -> ActiveEventEntry:
        # The overview holds no drafts, so ck_events_submitted_fields_complete guarantees these.
        starts_at, ends_at = event.starts_at, event.ends_at
        assert starts_at is not None
        assert ends_at is not None
        coordinator = event.assigned_coordinator
        return cls(
            id=event.id,
            name=event.name,
            starts_at=starts_at,
            ends_at=ends_at,
            status=event.status,
            coordinator_id=coordinator.id if coordinator is not None else None,
            coordinator_name=coordinator.full_name if coordinator is not None else None,
            coordinator_is_active=coordinator.is_active if coordinator is not None else None,
            assigned_by_name=assigning_lead.full_name if assigning_lead is not None else None,
        )


class WorkloadEvent(BaseModel):
    """Story 5.5 AC2: one of a coordinator's active events. No defaults (response schema)."""

    id: uuid.UUID
    name: str
    starts_at: datetime  # non-null for every non-DRAFT row (ck_events_submitted_fields_complete)
    ends_at: datetime
    status: str

    @classmethod
    def from_event(cls, event: Event) -> WorkloadEvent:
        # Only active events are listed, so ck_events_submitted_fields_complete guarantees these.
        starts_at, ends_at = event.starts_at, event.ends_at
        assert starts_at is not None
        assert ends_at is not None
        return cls(
            id=event.id, name=event.name, starts_at=starts_at, ends_at=ends_at, status=event.status
        )


class CoordinatorWorkloadEntry(BaseModel):
    """Story 5.5 AC2: one Event Coordinator, their number of active events (AC4: 0 included) and
    the events themselves. AC5: ``is_active`` false flags a deactivated coordinator who still holds
    events. No defaults (response schema)."""

    coordinator_id: uuid.UUID
    coordinator_name: str
    is_active: bool
    active_event_count: int
    events: list[WorkloadEvent]

    @classmethod
    def from_coordinator(
        cls, user: User, *, active_event_count: int, events: list[Event]
    ) -> CoordinatorWorkloadEntry:
        return cls(
            coordinator_id=user.id,
            coordinator_name=user.full_name,
            is_active=user.is_active,
            active_event_count=active_event_count,
            events=[WorkloadEvent.from_event(event) for event in events],
        )
