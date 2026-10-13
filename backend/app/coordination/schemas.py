"""Request / response shapes for coordinator assignment (stories 5.1, 5.2 and 5.4)."""

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
    model_config = ConfigDict(extra="forbid")

    coordinator_id: uuid.UUID
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
    starts_at: datetime | None
    ends_at: datetime | None
    expected_attendance: int | None
    organiser_name: str
    submitted_at: datetime | None

    @classmethod
    def from_event(cls, event: Event) -> UnassignedEventEntry:
        return cls(
            id=event.id,
            name=event.name,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            expected_attendance=event.expected_attendance,
            organiser_name=event.organiser.full_name,
            submitted_at=event.submitted_at,
        )
