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


class ReleaseCause:
    """Values allowed by ``ck_venue_bookings_release_cause``: why a CANCELLED booking was released
    (story 21.3). Each path that closes an approved booking through ``release_booking`` names
    its own."""

    EVENT_CANCELLED = "EVENT_CANCELLED"  # story 6.2: its event was cancelled
    CHANGE_APPROVED = "CHANGE_APPROVED"  # story 19.2: an approved change no longer fits it
    REPLACED = "REPLACED"  # story 12.6: its replacement was approved
    SAFETY_REVIEW = "SAFETY_REVIEW"  # story 21.3: the Safety Officer named it in a finding
    COORDINATOR_CANCELLED = "COORDINATOR_CANCELLED"  # story 12.8: its coordinator cancelled it
    VENUE_UNAVAILABLE = "VENUE_UNAVAILABLE"  # story 9.5: a closure of its venue was saved


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
    # Story 6.2 AC16: when the booking was cancelled - with its event, or by an approved change
    # (19.2); NULL otherwise, and for one cancelled before migration 026.
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Story 12.6 AC2, retired by story 9.5: the booking this one was requested to replace, a booking
    # of the same event (composite FK fk_venue_bookings_replaces); None for any other. A request
    # raised before 9.5 keeps it while its original holds the venue; the database clears it, with
    # replaces_live_original, when the original stops holding (9.5 AC8), except on the replacement
    # whose approval released the original. AC3: on an original released by its replacement, the
    # replacement whose approval released it, set in that release and only on a CANCELLED booking.
    # AC10: replaces_live_original is set on a replacement, which the one-per-requirement index
    # reads only while the replacement is pending, leaving it out.
    replaces_booking_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    replaced_by_booking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venue_bookings.id")
    )
    replaces_live_original: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Story 21.3: how a CANCELLED booking was released (``ReleaseCause``), the reason, and who
    # released it, set together with the status by ``release_booking``. NULL for a booking never
    # released, and for a CANCELLED row written without a cause (ck_venue_bookings_release_fields).
    release_cause: Mapped[str | None] = mapped_column(Text)
    release_reason: Mapped[str | None] = mapped_column(Text)
    released_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    # Story 9.5 AC2: the reason and description of the venue closure that ended the booking -
    # REJECTED for a pending request, CANCELLED (release_cause VENUE_UNAVAILABLE) for an approved
    # booking - copied at the save; both set or both NULL.
    closure_reason: Mapped[str | None] = mapped_column(Text)
    closure_description: Mapped[str | None] = mapped_column(Text)

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
    def requirement_label(self) -> str | None:
        """Story 21.3 AC1: the venue requirement this booking is for, as the safety review names
        it - its name, or "Venue n" by its place when it has none, as story 21.2's blockers do -
        or None for an additional venue."""
        requirement = self.venue_requirement
        if requirement is None:
            return None
        return requirement.name or f"Venue {requirement.position + 1}"

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
