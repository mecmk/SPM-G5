"""ORM model for venue bookings (stories 12.x request, 13.x approval, 14.x conflicts).

Mirrors backend/db/migrations. Added by story 14.2, which is the first story that needs to
read booking rows; later stories in the 12.x / 13.x epics should extend this class rather than
mapping ``venue_bookings`` a second time - two declarative classes on one table raise
``InvalidRequestError``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.auth.models import User
from app.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.events.models import Event
from app.venues.models import RoomLayout, Venue


class BookingStatus:
    """Values allowed by ``ck_venue_bookings_status``. Only APPROVED occupies the venue."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    CANCELLED = "CANCELLED"


class VenueBooking(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venue_bookings"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False
    )
    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    setup_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    teardown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Trigger-maintained from starts_at/ends_at +/- setup/teardown minutes - never set these
    # directly (see the migration's trg_venue_bookings_set_held_period). This is the period
    # story 14.2's conflict check compares.
    held_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    held_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_attendance: Mapped[int] = mapped_column(Integer, nullable=False)
    required_layout_code: Mapped[str | None] = mapped_column(Text, ForeignKey("room_layouts.code"))
    requirement_notes: Mapped[str | None] = mapped_column(Text)
    suitability_override_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'PENDING'"))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    alternative_suggestion: Mapped[str | None] = mapped_column(Text)

    # Story 13.1: the queue's entry shape needs the event and venue names, not just their ids.
    # Not lazy="joined": Event's own eager relationships (e.g. assigned_coordinator, nullable)
    # would cascade into any query on this relationship, and postgres refuses FOR UPDATE
    # against the nullable side of an outer join - which get_booking_for_decision needs.
    # list_booking_requests asks for these explicitly with a joinedload option instead.
    event: Mapped[Event] = relationship()
    venue: Mapped[Venue] = relationship()
    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_id])
    required_layout: Mapped[RoomLayout | None] = relationship(foreign_keys=[required_layout_code])
