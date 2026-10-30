"""ORM models for the Safety Officer's reviews of an event: story 21.1 reads them, story 21.2
writes them with their findings, and story 21.3 (AC1, AC2, AC9) links each finding to the venue
bookings its decision released. Mirrors ``event_safety_reviews``, ``safety_review_factors``,
``event_safety_review_findings`` and ``event_safety_finding_bookings`` in backend/db/migrations
(019, 024, 029).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Table, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.auth.models import User
from app.bookings.models import VenueBooking
from app.db import Base, UUIDPrimaryKeyMixin


class SafetyReviewOutcome:
    """Values allowed by ``ck_event_safety_reviews_outcome``."""

    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class SafetyArrangement:
    """Values allowed by ``ck_event_safety_review_findings_arrangement``: the arrangement a finding
    says must change (21.2 AC4), each compared on resubmission with the fact of the same name in
    the review's snapshot (``FACT_KEY``, 21.2 AC12)."""

    VENUE_BOOKINGS = "VENUE_BOOKINGS"
    EQUIPMENT = "EQUIPMENT"

    FACT_KEY = {VENUE_BOOKINGS: "venues", EQUIPMENT: "equipment"}


class SafetyReviewFactor(Base):
    """A factor a safety review considers (21.2 AC2). Reference data."""

    __tablename__ = "safety_review_factors"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))


# Story 21.3 AC1, AC9: the bookings a finding named, which the decision released. Mirrors
# ``event_safety_finding_bookings`` (migration 029); written through ``released_bookings``.
finding_bookings = Table(
    "event_safety_finding_bookings",
    Base.metadata,
    Column(
        "finding_id",
        UUID(as_uuid=True),
        ForeignKey("event_safety_review_findings.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "booking_id",
        UUID(as_uuid=True),
        ForeignKey("venue_bookings.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class SafetyReviewFinding(UUIDPrimaryKeyMixin, Base):
    """One thing the officer requires changed (21.2 AC4). Append-only, with its review."""

    __tablename__ = "event_safety_review_findings"

    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("event_safety_reviews.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    factor_code: Mapped[str] = mapped_column(
        Text, ForeignKey("safety_review_factors.code"), nullable=False
    )
    arrangement: Mapped[str | None] = mapped_column(Text)
    required_change: Mapped[str] = mapped_column(Text, nullable=False)

    factor: Mapped[SafetyReviewFactor] = relationship(lazy="joined")
    # Story 21.3 AC9: the bookings this finding named, in booked-start order.
    released_bookings: Mapped[list[VenueBooking]] = relationship(
        secondary=finding_bookings, order_by="VenueBooking.starts_at, VenueBooking.id"
    )


class EventSafetyReview(UUIDPrimaryKeyMixin, Base):
    """One safety review of an event, with a snapshot of the facts reviewed (21.1 AC3, AC5) and,
    when it requested changes, its findings (21.2 AC4). Append-only, so no
    ``created_at``/``updated_at``: ``reviewed_at`` is the only timestamp."""

    __tablename__ = "event_safety_reviews"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    reviewed_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    reviewed_by: Mapped[User] = relationship(lazy="joined")
    findings: Mapped[list[SafetyReviewFinding]] = relationship(
        order_by=SafetyReviewFinding.position, cascade="all, delete-orphan"
    )

    @property
    def flagged_arrangements(self) -> list[str]:
        """21.2 AC4: the arrangements any finding says must change, in the order first named."""
        return list(
            dict.fromkeys(f.arrangement for f in self.findings if f.arrangement is not None)
        )
