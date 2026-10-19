"""ORM model for venue bookings (stories 12.x request, 13.x approval, 14.x conflicts).

Mirrors backend/db/migrations. Added by story 14.2, which is the first story that needs to
read booking rows; later stories in the 12.x / 13.x epics should extend this class rather than
mapping ``venue_bookings`` a second time - two declarative classes on one table raise
``InvalidRequestError``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.elements import ColumnElement

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


def marked_booking_conditions() -> tuple[ColumnElement[bool], ...]:
    """Story 9.4 AC3 / story 12.6 AC11, AC13: the booking still holds its venue - pending or
    approved - and is marked "Venue unavailable - alternative needed". One definition for every
    reader of the mark: the coordinator's list (``Venue unavailable`` tab) and the safety review
    and confirmation, which refuse while an event has such a booking. A mark left on a closed
    booking is history and is not one."""
    return (
        VenueBooking.status.in_((BookingStatus.PENDING, BookingStatus.APPROVED)),
        VenueBooking.venue_unavailable_marked_at.is_not(None),
    )


def pending_replacement_conditions() -> tuple[ColumnElement[bool], ...]:
    """Story 12.6: the booking is a replacement still waiting for Venue Staff's decision. Its
    approval releases the booking it replaces, so the event's safety review and confirmation wait
    for it, as they wait for a mark: the review saw the original venue, not this one."""
    return (
        VenueBooking.status == BookingStatus.PENDING,
        VenueBooking.replaces_booking_id.is_not(None),
    )


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
    # Story 12.6 AC2: the booking this one replaces, which Venue Staff's closure made unavailable -
    # a booking of the same event (composite FK fk_venue_bookings_replaces); None for any other.
    # AC3: on an original released by its replacement, the replacement whose approval released it,
    # set in that release and only on a CANCELLED booking. AC10: replaces_live_original is True
    # while the replacement's original still holds its venue, which the one-per-requirement index
    # leaves out while the replacement is pending; the database clears it when the original stops.
    replaces_booking_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    replaced_by_booking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venue_bookings.id")
    )
    replaces_live_original: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

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
    # Story 12.6: the three bookings a replacement links - the one this replaces, the one that
    # replaced this, and the pending replacement asked for this one. Read only, loaded when asked.
    replaced_booking: Mapped[VenueBooking | None] = relationship(
        primaryjoin="foreign(VenueBooking.replaces_booking_id) == remote(VenueBooking.id)",
        uselist=False,
        viewonly=True,
    )
    replaced_by_booking: Mapped[VenueBooking | None] = relationship(
        primaryjoin="foreign(VenueBooking.replaced_by_booking_id) == remote(VenueBooking.id)",
        uselist=False,
        viewonly=True,
    )
    pending_replacement: Mapped[VenueBooking | None] = relationship(
        primaryjoin=(
            "and_(VenueBooking.id == foreign(remote(VenueBooking.replaces_booking_id)),"
            " remote(VenueBooking.status) == 'PENDING')"
        ),
        uselist=False,
        viewonly=True,
    )

    @property
    def venue_unavailable_mark(self) -> datetime | None:
        """Story 9.4 AC3: the mark as readers see it - only on a booking still pending or
        approved. A value left on a rejected, withdrawn, cancelled or expired booking is history
        and is not reported."""
        holds_venue = self.status in (BookingStatus.PENDING, BookingStatus.APPROVED)
        return self.venue_unavailable_marked_at if holds_venue else None

    @property
    def replaces_venue_name(self) -> str | None:
        """Story 12.6 AC3: the venue of the booking this one replaces, whatever its state."""
        return None if self.replaced_booking is None else self.replaced_booking.venue.name

    @property
    def replaced_by_venue_name(self) -> str | None:
        """Story 12.6 AC3, AC8: the venue of the replacement whose approval released this booking
        - set only then, so a replacement never approved is never shown as having replaced it."""
        return None if self.replaced_by_booking is None else self.replaced_by_booking.venue.name

    @property
    def released_at(self) -> datetime | None:
        """Story 12.6 AC3: when this booking was released - the approval of the replacement that
        released it - or None for any other booking. ``decided_at`` stays the booking's own
        decision, so the time a released original closed is read from the replacement, which is
        what released it, and nothing is stored twice. A booking story 19.2 released has no
        replacement to read it from, so None: its close time is not recorded, and its
        ``decided_at`` is its approval, not when it closed."""
        return None if self.replaced_by_booking is None else self.replaced_by_booking.decided_at

    @property
    def pending_replacement_venue_name(self) -> str | None:
        """Story 12.6 AC4: the venue asked for as this booking's replacement, while pending."""
        return None if self.pending_replacement is None else self.pending_replacement.venue.name

    @property
    def approval_releases_venue_name(self) -> str | None:
        """Story 12.6 AC3: while this is a pending replacement, the venue its approval will
        release - only while that booking still holds its venue (nothing is released otherwise)."""
        original = self.replaced_booking
        holds_venue = original is not None and original.status in (
            BookingStatus.PENDING,
            BookingStatus.APPROVED,
        )
        if self.status != BookingStatus.PENDING or original is None or not holds_venue:
            return None
        return original.venue.name

    @property
    def original_is_marked(self) -> bool | None:
        """Story 12.6 AC6: for a replacement, whether the booking it replaces is still marked
        "Venue unavailable"; None for any other booking."""
        original = self.replaced_booking
        return None if original is None else original.venue_unavailable_mark is not None
