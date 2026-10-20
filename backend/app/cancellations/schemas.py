"""Request body for story 6.2: the organiser cancels their own event. The response is the event as
its details page shows it, ``app.events.schemas.EventDetailOut``."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventCancellationIn(BaseModel):
    """AC7: a reason is mandatory - blank or whitespace-only does not count, as for a rejection
    (4.5 AC1). Trimmed before it is recorded."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)

    @field_validator("reason", mode="before")
    @classmethod
    def _strip_reason(cls, value):
        return value.strip() if isinstance(value, str) else value
