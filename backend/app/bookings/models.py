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
from app.events.models import Event, VenueRequirement
from app.venues.models import RoomLayout, Venue


class BookingStatus:
    """Values allowed by ``ck_venue_bookings_status``. PENDING and APPROVED hold the venue (story
    12.1 AC3); EXPIRED is an approved booking whose hold lapsed before its event was confirmed
    (story 12.7 AC3)."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


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
    # Story 12.5 AC1: the event's venue requirement this request is for; None for an
    # additional venue (AC5, AC7). uq_venue_bookings_one_per_requirement allows one pending or
    # approved request per requirement (AC10-AC12).
    venue_requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venue_requirements.id", ondelete="SET NULL")
    )
    # Story 12.7 AC1: when an approved booking's hold on its venue expires unless its event is
    # confirmed first - set by Venue Staff as they approve, changed only by them; never on a
    # pending request, always on an EXPIRED one (ck_venue_bookings_hold_expiry). AC2: when the
    # coordinator was warned it is about to, NULL until then. AC4: when the event's confirmation
    # completed it (trg_events_complete_venue_holds), NULL while it is open.
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hold_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hold_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Story 12.7 AC7, decided 12 Oct 2026: the latest change Venue Staff made to the expiry - its
    # reason, who made it and when, set together or not at all
    # (ck_venue_bookings_hold_expiry_change). NULL until the first change; the audit log keeps
    # every change.
    hold_expiry_change_reason: Mapped[str | None] = mapped_column(Text)
    hold_expiry_changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    hold_expiry_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Story 9.4 AC3/AC6: when the booking was marked "Venue unavailable - alternative needed",
    # while a period its venue is unavailable for overlaps its held period; NULL when unmarked.
    # Only the part of the held period still to come counts: it overlaps a period from the later
    # of now and the period's start to its end, so a period wholly in the past marks nothing
    # (PO decision, AC6/AC8). Read it through ``venue_unavailable_mark``, which leaves out a
    # booking that no longer holds the venue.
    venue_unavailable_marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Story 6.2 AC16: when the booking was cancelled - with its event, or by an approved change
    # (19.2); NULL otherwise, and for one cancelled before migration 025.
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Story 13.1: the queue's entry shape needs the event and venue names, not just their ids.
    # Not lazy="joined": Event's own eager relationships (e.g. assigned_coordinator, nullable)
    # would cascade into any query on this relationship, and postgres refuses FOR UPDATE
    # against the nullable side of an outer join - which get_booking_for_decision needs.
    # list_booking_requests asks for these explicitly with a joinedload option instead.
    event: Mapped[Event] = relationship()
    venue: Mapped[Venue] = relationship()
    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_id])
    hold_expiry_changed_by: Mapped[User | None] = relationship(
        foreign_keys=[hold_expiry_changed_by_id]
    )
    required_layout: Mapped[RoomLayout | None] = relationship(foreign_keys=[required_layout_code])
    venue_requirement: Mapped[VenueRequirement | None] = relationship()

    @property
    def venue_unavailable_mark(self) -> datetime | None:
        """Story 9.4 AC3: the mark as readers see it - only on a booking still pending or
        approved. A value left on a rejected, withdrawn, cancelled or expired booking is history
        and is not reported."""
        holds_venue = self.status in (BookingStatus.PENDING, BookingStatus.APPROVED)
        return self.venue_unavailable_marked_at if holds_venue else None
