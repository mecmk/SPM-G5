"""ORM models for the event lifecycle (stories 2.x-7.x). Mirrors backend/db/migrations.

Added by story 14.2, which is the first story on this branch that needs to reference an event
row (a venue booking always belongs to one). The mapping covers the whole ``events`` table so
later stories in the 2.x / 3.x / 4.x / 5.x / 6.x / 7.x epics **extend this class** rather than
mapping ``events`` a second time - two declarative classes on one table raise
``InvalidRequestError``.

Story 2.1 adds the request's child rows: required facilities, accessibility needs, equipment
lines (with the equipment catalogue they point at) and the append-only status history.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.auth.models import User
from app.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.venues.models import AccessibilityFeature, Facility, RoomLayout


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


class EquipmentType(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The equipment catalogue an event's equipment lines point at (stories 2.1, 15.x, 16.x)."""

    __tablename__ = "equipment_types"

    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    storage_location: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class EventRequiredFacility(Base):
    """A facility the event requires of its venue (story 2.1 AC4)."""

    __tablename__ = "event_required_facilities"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    facility_code: Mapped[str] = mapped_column(
        Text, ForeignKey("facilities.code"), primary_key=True
    )
    quantity: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    facility: Mapped[Facility] = relationship(lazy="joined")


class EventAccessibilityNeed(Base):
    """An accessibility feature the event needs (story 2.1 AC5)."""

    __tablename__ = "event_accessibility_needs"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    feature_code: Mapped[str] = mapped_column(
        Text, ForeignKey("accessibility_features.code"), primary_key=True
    )
    notes: Mapped[str | None] = mapped_column(Text)

    feature: Mapped[AccessibilityFeature] = relationship(lazy="joined")


class EventEquipmentRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One equipment line on a request: a type and a quantity (story 2.1 AC6)."""

    __tablename__ = "event_equipment_requests"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    equipment_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_types.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    technical_notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'REQUESTED'"))
    status_notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    equipment_type: Mapped[EquipmentType] = relationship(lazy="joined")


class EventStatusHistory(UUIDPrimaryKeyMixin, Base):
    """Append-only log of every status transition (stories 6.1, 6.4)."""

    __tablename__ = "event_status_history"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    reason: Mapped[str | None] = mapped_column(Text)


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
    venue_none_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

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
    required_layout: Mapped[RoomLayout | None] = relationship(foreign_keys=[required_layout_code])
    required_facilities: Mapped[list[EventRequiredFacility]] = relationship(
        cascade="all, delete-orphan", order_by=EventRequiredFacility.facility_code
    )
    accessibility_needs: Mapped[list[EventAccessibilityNeed]] = relationship(
        cascade="all, delete-orphan", order_by=EventAccessibilityNeed.feature_code
    )
    equipment_requests: Mapped[list[EventEquipmentRequest]] = relationship(
        cascade="all, delete-orphan",
        order_by=(EventEquipmentRequest.created_at, EventEquipmentRequest.id),
    )
