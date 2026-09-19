"""ORM model for the event lifecycle (stories 2.x-7.x). Mirrors backend/db/migrations.

Added by story 14.2, which is the first story on this branch that needs to reference an event
row (a venue booking always belongs to one). The mapping covers the whole ``events`` table so
later stories in the 2.x / 3.x / 4.x / 5.x / 6.x / 7.x epics **extend this class** rather than
mapping ``events`` a second time - two declarative classes on one table raise
``InvalidRequestError``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.auth.models import User
from app.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EventStatus:
    """Values allowed by ``ck_events_status`` (story 6.1: exactly one current status)."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    APPROVED = "APPROVED"
    PLANNING = "PLANNING"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class Event(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "events"

    organiser_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_organisations.id")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    cover_image_url: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_attendance: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'DRAFT'"))
    assigned_coordinator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    # venue requirements captured on the request (story 2.1 AC4)
    preferred_location: Mapped[str | None] = mapped_column(Text)
    required_layout_code: Mapped[str | None] = mapped_column(Text, ForeignKey("room_layouts.code"))
    venue_requirement_notes: Mapped[str | None] = mapped_column(Text)

    # accessibility (story 2.1 AC5)
    accessibility_none_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    accessibility_notes: Mapped[str | None] = mapped_column(Text)

    # registration (stories 2.4, 18.x)
    registration_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    registration_capacity: Mapped[int | None] = mapped_column(Integer)
    registration_opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registration_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # routine / contact fields (story 7.2)
    contact_name: Mapped[str | None] = mapped_column(Text)
    contact_email: Mapped[str | None] = mapped_column(CITEXT)
    contact_phone: Mapped[str | None] = mapped_column(Text)
    internal_notes: Mapped[str | None] = mapped_column(Text)

    # lifecycle bookkeeping
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    decision_reason: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organiser: Mapped[User] = relationship(lazy="joined", foreign_keys=[organiser_id])
    assigned_coordinator: Mapped[User | None] = relationship(
        lazy="joined", foreign_keys=[assigned_coordinator_id]
    )
