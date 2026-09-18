"""ORM models for the venue catalogue (stories 8.x). Mirrors backend/db/migrations."""

from __future__ import annotations

import uuid
from datetime import time
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, Text, Time, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Facility(Base):
    __tablename__ = "facilities"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))


class RoomLayout(Base):
    __tablename__ = "room_layouts"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))


class AccessibilityFeature(Base):
    __tablename__ = "accessibility_features"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))


class VenueStatus:
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class Venue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venues"

    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    floor_area_sqm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    operating_hours_start: Mapped[time | None] = mapped_column(Time)
    operating_hours_end: Mapped[time | None] = mapped_column(Time)
    operating_notes: Mapped[str | None] = mapped_column(Text)
    setup_minutes_default: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    teardown_minutes_default: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ACTIVE'"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    facilities: Mapped[list[VenueFacility]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="VenueFacility.facility_code"
    )
    layouts: Mapped[list[VenueLayout]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="VenueLayout.layout_code"
    )
    accessibility_features: Mapped[list[VenueAccessibilityFeature]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="VenueAccessibilityFeature.feature_code",
    )


class VenueFacility(Base):
    __tablename__ = "venue_facilities"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id", ondelete="CASCADE"), primary_key=True
    )
    facility_code: Mapped[str] = mapped_column(
        Text, ForeignKey("facilities.code"), primary_key=True
    )
    quantity: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    facility: Mapped[Facility] = relationship(lazy="joined")


class VenueLayout(Base):
    __tablename__ = "venue_layouts"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id", ondelete="CASCADE"), primary_key=True
    )
    layout_code: Mapped[str] = mapped_column(
        Text, ForeignKey("room_layouts.code"), primary_key=True
    )
    layout_capacity: Mapped[int | None] = mapped_column(Integer)

    layout: Mapped[RoomLayout] = relationship(lazy="joined")


class VenueAccessibilityFeature(Base):
    __tablename__ = "venue_accessibility_features"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id", ondelete="CASCADE"), primary_key=True
    )
    feature_code: Mapped[str] = mapped_column(
        Text, ForeignKey("accessibility_features.code"), primary_key=True
    )
    notes: Mapped[str | None] = mapped_column(Text)

    feature: Mapped[AccessibilityFeature] = relationship(lazy="joined")
