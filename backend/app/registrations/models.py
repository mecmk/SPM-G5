"""ORM model for attendees' registrations for events (story 18.1 writes them; 18.2 and 18.3 read
and withdraw them). Mirrors ``event_registrations`` in backend/db/migrations (001).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UUIDPrimaryKeyMixin


class RegistrationStatus:
    """Values allowed by ``ck_event_registrations_status``. Only REGISTERED holds a place
    (story 18.1 AC2) and counts towards ``uq_event_registrations_active`` (AC7)."""

    REGISTERED = "REGISTERED"
    WITHDRAWN = "WITHDRAWN"
    CANCELLED = "CANCELLED"


class EventRegistration(UUIDPrimaryKeyMixin, Base):
    """One attendee's registration for one event (story 18.1 AC1). ``registered_at`` is the moment
    the registration was made, the same moment its closing time was checked against (AC7).

    Story 18.4 AC12 (fix f18.4.1): the one guest the attendee brings, if any - their name and
    phone number together, and their dietary requirements (030). A guest takes a place too."""

    __tablename__ = "event_registrations"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    attendee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'REGISTERED'"))
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attended: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)
    guest_full_name: Mapped[str | None] = mapped_column(Text)
    guest_phone: Mapped[str | None] = mapped_column(Text)
    guest_dietary_requirements: Mapped[str | None] = mapped_column(Text)
