"""ORM model for the Safety Officer's reviews of an event (story 21.1 reads them; the review and
decision story writes them). Mirrors ``event_safety_reviews`` in backend/db/migrations (019).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.auth.models import User
from app.db import Base, UUIDPrimaryKeyMixin


class SafetyReviewOutcome:
    """Values allowed by ``ck_event_safety_reviews_outcome``."""

    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class EventSafetyReview(UUIDPrimaryKeyMixin, Base):
    """One safety review of an event, with a snapshot of the facts reviewed (21.1 AC3, AC5).
    Append-only, so no ``created_at``/``updated_at``: ``reviewed_at`` is the only timestamp."""

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
    notes: Mapped[str | None] = mapped_column(Text)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    reviewed_by: Mapped[User] = relationship(lazy="joined")
