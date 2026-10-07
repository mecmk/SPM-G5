"""Response shapes for in-app notifications (story 20.1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationOut(BaseModel):
    """20.1 AC1/AC2: one notification as its recipient reads it - what happened (the type, title
    and message), about which event and record, and when. ``read_at`` is left out until story
    20.2 can set it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    notification_type: str
    title: str
    message: str
    event_id: uuid.UUID | None
    related_entity_type: str | None
    related_entity_id: uuid.UUID | None
    created_at: datetime
