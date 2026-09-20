"""ORM model for coordinator assignment (stories 5.x). Mirrors backend/db/migrations.

``event_coordinator_assignments`` is the *history*: one row per period a coordinator was
responsible for an event. The row with ``unassigned_at IS NULL`` is the current one, and the
partial unique index ``uq_event_coordinator_assignments_current`` guarantees there is at most
one of those per event (story 5.1 AC1). ``events.assigned_coordinator_id`` denormalises the
same fact for fast filtering and is kept in step by the service.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.auth.models import User
from app.db import Base, UUIDPrimaryKeyMixin


class EventCoordinatorAssignment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "event_coordinator_assignments"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    coordinator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)

    coordinator: Mapped[User] = relationship(lazy="joined", foreign_keys=[coordinator_id])
    assigned_by: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[assigned_by_id])
