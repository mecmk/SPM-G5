"""ORM model for in-app notifications (stories 20.1, 20.2). Mirrors backend/db/migrations.

One row per recipient. Rows are written only through ``app.notifications.service.notify``,
inside the transaction of the action they report.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UUIDPrimaryKeyMixin


class Notification(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "notifications"

    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE")
    )
    notification_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    related_entity_type: Mapped[str | None] = mapped_column(Text)
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
