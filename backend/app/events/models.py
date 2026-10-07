"""ORM models for the event lifecycle (stories 2.x-7.x). Mirrors backend/db/migrations.

Added by story 14.2, which is the first story on this branch that needs to reference an event
row (a venue booking always belongs to one). The mapping covers the whole ``events`` table so
later stories in the 2.x / 3.x / 4.x / 5.x / 6.x / 7.x epics **extend this class** rather than
mapping ``events`` a second time - two declarative classes on one table raise
``InvalidRequestError``.

Story 2.1 adds the request's child rows: accessibility needs, equipment lines (with the
equipment catalogue they point at) and the append-only status history. Story 2.7 adds the venue
requirements, each with its own facilities. Story 15.1 (``app/equipment/``) works on the
same equipment tables, which stay mapped here because ``Event`` holds its equipment
items.
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
    UNDER_REVIEW = "UNDER_REVIEW"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
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


class VenueRequirementFacility(Base):
    """A facility one venue requirement needs, optionally how many (story 2.7 AC1)."""

    __tablename__ = "venue_requirement_facilities"

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("venue_requirements.id", ondelete="CASCADE"),
        primary_key=True,
    )
    facility_code: Mapped[str] = mapped_column(
        Text, ForeignKey("facilities.code"), primary_key=True
    )
    quantity: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    facility: Mapped[Facility] = relationship(lazy="joined")


class VenueRequirement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One venue an event needs: a name, how many people, when, and what the room must offer
    (story 2.7 AC1, AC2). Every column but the event and position may be empty on a draft
    (AC8). The id stays the same when the requirement is edited, so a booking can later point at
    it (stories 8.4, 12.5)."""

    __tablename__ = "venue_requirements"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    capacity: Mapped[int | None] = mapped_column(Integer)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    layout_code: Mapped[str | None] = mapped_column(Text, ForeignKey("room_layouts.code"))
    notes: Mapped[str | None] = mapped_column(Text)

    layout: Mapped[RoomLayout | None] = relationship(lazy="joined")
    facilities: Mapped[list[VenueRequirementFacility]] = relationship(
        cascade="all, delete-orphan", order_by=VenueRequirementFacility.facility_code
    )


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


class EquipmentRequestStatus:
    """Values allowed by ``ck_event_equipment_requests_status`` (migration 014, story 15.1).
    Whether an item holds stock is its ``EquipmentReservation``'s business, not its status's."""

    REQUESTED = "REQUESTED"  # recorded, not yet sent to Technical Support
    PENDING = "PENDING"  # sent, awaiting Technical Support's decision
    ACCEPTED = "ACCEPTED"  # Technical Support reserved it (story 16.1)
    DECLINED = "DECLINED"  # Technical Support declined it (story 16.1)
    UNAVAILABLE = "UNAVAILABLE"  # the event's new dates can no longer cover it (15.1 AC8)
    CANCELLED = "CANCELLED"  # its event was cancelled (story 6.2)


class EventEquipmentRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One equipment item on an event: a type and a quantity (story 2.1 AC6), which the assigned
    coordinator submits to Technical Support (story 15.1)."""

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
    submitted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    equipment_type: Mapped[EquipmentType] = relationship(lazy="joined")
    submitted_by: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[submitted_by_id])


class EquipmentHoldStatus:
    """Values allowed by ``ck_equipment_reservations_status``."""

    RESERVED = "RESERVED"
    RELEASED = "RELEASED"


class EquipmentReservation(UUIDPrimaryKeyMixin, Base):
    """A hold of units of an equipment type for an event over a period. Story 2.1 places one per
    equipment line when a request is submitted; the equipment stories (16.x, 17.x) release them."""

    __tablename__ = "equipment_reservations"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    equipment_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("event_equipment_requests.id", ondelete="SET NULL")
    )
    equipment_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_types.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'RESERVED'"))
    reserved_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    reserved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    notes: Mapped[str | None] = mapped_column(Text)


class EquipmentUnavailabilityPeriod(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Units of an equipment type out of service for a period; ``ends_at`` NULL is open-ended."""

    __tablename__ = "equipment_unavailability_periods"

    equipment_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_types.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )


class EventStatusHistory(UUIDPrimaryKeyMixin, Base):
    """Append-only log of every event status transition (stories 4.6, 6.1, 6.4). Written by
    story 4.4/4.5's approve/reject and, later, 6.1/6.4's other transitions - never updated or
    deleted. No ``created_at``/``updated_at``: ``changed_at`` is the only timestamp.
    """

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


class ClarificationKind:
    """Values allowed by ``ck_event_clarifications_kind`` (story 4.6 AC2)."""

    REQUEST = "REQUEST"
    RESPONSE = "RESPONSE"
    NOTE = "NOTE"


class EventClarification(UUIDPrimaryKeyMixin, Base):
    """One message in the clarification conversation on a request (stories 4.2, 4.3, 4.6).
    Append-only: no write endpoint exists beyond creation (story 4.6 AC3)."""

    __tablename__ = "event_clarifications"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    author: Mapped[User] = relationship(lazy="joined")


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

    # venue requirements (story 2.1 AC4): each one is a VenueRequirement row (story 2.7), or the
    # organiser marks none required
    preferred_location: Mapped[str | None] = mapped_column(Text)
    venue_none_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    # accessibility (story 2.1 AC5)
    accessibility_none_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    accessibility_notes: Mapped[str | None] = mapped_column(Text)

    # registration (story 2.1 AC17/AC18; capacity remains reserved for a future story - AC17
    # always uses expected_attendance instead)
    registration_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    registration_capacity: Mapped[int | None] = mapped_column(Integer)
    registration_opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registration_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # visibility (story 2.1 AC19)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

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
    venue_requirements: Mapped[list[VenueRequirement]] = relationship(
        cascade="all, delete-orphan", order_by=VenueRequirement.position
    )
    accessibility_needs: Mapped[list[EventAccessibilityNeed]] = relationship(
        cascade="all, delete-orphan", order_by=EventAccessibilityNeed.feature_code
    )
    equipment_requests: Mapped[list[EventEquipmentRequest]] = relationship(
        cascade="all, delete-orphan",
        order_by=(EventEquipmentRequest.created_at, EventEquipmentRequest.id),
    )
    # Default lazy="select": only EventDetailOut's single-row read needs the decider, unlike
    # organiser/assigned_coordinator above, which every review-queue row also needs joined.
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id])
