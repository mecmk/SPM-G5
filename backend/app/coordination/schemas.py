"""Request / response shapes for coordinator assignment (story 5.1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.coordination.models import EventCoordinatorAssignment


class CoordinatorOption(BaseModel):
    """One selectable coordinator (story 5.1 AC2: only Event Coordinators are offered)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str
    department: str | None = None


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
