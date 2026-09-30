"""In-app notifications (table scaffolded for story 20.x; this module only writes to it, for
story 5.2 AC1 and story 12.2 AC2 - the read/list side, e.g. ``GET /notifications`` and a bell
that shows someone else's actions, is not built and stays out of scope here). One row per
recipient, written inside the same transaction as the triggering action, matching the table's
own ``COMMENT ON`` in ``backend/db/migrations/001_initial_schema.sql``.

Call ``notify`` from a service after a significant action, inside the same transaction::

    notify(db, recipient=coordinator, notification_type="EVENT_REASSIGNED_TO", event_id=event.id,
           title="You're now assigned to Nimbus Developer Conference",
           message="Chloe Coordinator handed you this event.")
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.auth.models import User
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


def notify(
    db: Session,
    *,
    recipient: User,
    notification_type: str,
    title: str,
    message: str,
    event_id: uuid.UUID | None = None,
    related_entity_type: str | None = None,
    related_entity_id: uuid.UUID | None = None,
    commit: bool = True,
) -> Notification:
    entry = Notification(
        recipient_id=recipient.id,
        event_id=event_id,
        notification_type=notification_type,
        title=title,
        message=message,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
    )
    db.add(entry)
    if commit:
        db.commit()
    else:
        db.flush()
    return entry
