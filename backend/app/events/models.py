"""ORM models for event requests (story 2.1). Mirrors backend/db/migrations.

Only the columns story 2.1 touches are mapped here - the events table has many more columns
(registration_*, contact_*, decision_* etc.) reserved for later stories (2.4, 7.2, 4.x) that add
them to this model when they need them. tests/test_schema.py::test_orm_models_match_database only
checks the columns a model declares, so a partial mapping is safe.

Facility, RoomLayout and AccessibilityFeature are imported from app.venues.models rather than
redefined here: the migration's own section comment calls these "REFERENCE LISTS shared by
venues and events", and this keeps event/venue requirement line items resolving to the same
human-readable name through the same code path (see EventOut / VenueOut).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.venues.models import AccessibilityFeature, Facility, RoomLayout


class EventStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"


class EquipmentRequestStatus:
    REQUESTED = "REQUESTED"


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
    starts_at: Mapped[datetime | None] = mapped_column()
    ends_at: Mapped[datetime | None] = mapped_column()
    expected_attendance: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'DRAFT'"))
    assigned_coordinator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    preferred_location: Mapped[str | None] = mapped_column(Text)
    required_layout_code: Mapped[str | None] = mapped_column(Text, ForeignKey("room_layouts.code"))
    venue_requirement_notes: Mapped[str | None] = mapped_column(Text)
    accessibility_none_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    accessibility_notes: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column()

    required_layout: Mapped[RoomLayout | None] = relationship(lazy="joined")
    required_facilities: Mapped[list[EventRequiredFacility]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="EventRequiredFacility.facility_code",
    )
    accessibility_features: Mapped[list[EventAccessibilityNeed]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="EventAccessibilityNeed.feature_code",
    )
    equipment_requests: Mapped[list[EventEquipmentRequest]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="EventEquipmentRequest.created_at",
    )


class EventRequiredFacility(Base):
    __tablename__ = "event_required_facilities"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    facility_code: Mapped[str] = mapped_column(
        Text, ForeignKey("facilities.code"), primary_key=True
    )
    notes: Mapped[str | None] = mapped_column(Text)

    facility: Mapped[Facility] = relationship(lazy="joined")


class EventAccessibilityNeed(Base):
    __tablename__ = "event_accessibility_needs"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    feature_code: Mapped[str] = mapped_column(
        Text, ForeignKey("accessibility_features.code"), primary_key=True
    )
    notes: Mapped[str | None] = mapped_column(Text)

    feature: Mapped[AccessibilityFeature] = relationship(lazy="joined")


class EquipmentType(Base):
    """Equipment catalogue (stories 2.1, 15.x-17.x). Not owned by any feature package yet, so it
    is mapped here, minimally, for the fields event requests need (code, name for display).
    """

    __tablename__ = "equipment_types"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class EventEquipmentRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
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
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    equipment_type: Mapped[EquipmentType] = relationship(lazy="joined")
