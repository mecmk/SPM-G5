"""ORM model for event change requests (story 19.1 raises and withdraws them; story 19.2 reviews
and decides them).

Mirrors ``event_change_requests`` in backend/db/migrations (001, guarded by 015). Later stories in
epic 19 should extend this class rather than mapping the table a second time - two declarative
classes on one table raise ``InvalidRequestError``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.auth.models import User
from app.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.events.models import Event


class ChangeRequestStatus:
    """Values allowed by ``ck_event_change_requests_status``."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    CANCELLED = "CANCELLED"  # its event was cancelled while it was pending (story 6.2 AC4)


class ChangeRequestField:
    """Values allowed by ``ck_event_change_requests_field_name`` (migration 015)."""

    SCHEDULE = "schedule"
    EXPECTED_ATTENDANCE = "expected_attendance"
    VENUE_REQUIREMENTS = "venue_requirements"
    EQUIPMENT = "equipment"


class EventChangeRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "event_change_requests"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    field_name: Mapped[str] = mapped_column(Text, nullable=False)
    # Canonical JSON text (story 19.1): read and written only through the service's helpers.
    current_value: Mapped[str | None] = mapped_column(Text)
    proposed_value: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'PENDING'"))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)

    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_id], lazy="joined")
    # Story 19.2 AC2/AC3: who decided, shown beside the decision.
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id], lazy="joined")
    # Story 19.2 AC1: the queue names each request's event. Not joined by default: the queue asks
    # for it with contains_eager, and the per-event list already has the event in hand.
    event: Mapped[Event] = relationship()
