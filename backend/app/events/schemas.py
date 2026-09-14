"""Response shapes for the coordinator review queue (story 4.1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from app.events.models import Event


class ReviewQueueSort(StrEnum):
    """AC3: order by submission date (default) or proposed event date."""

    SUBMITTED_AT = "submitted_at"
    STARTS_AT = "starts_at"


class ReviewQueueEntry(BaseModel):
    """AC2: name, organiser, proposed date, submission date. No defaults (response schema)."""

    id: uuid.UUID
    name: str
    organiser_name: str
    starts_at: datetime  # non-null for every non-DRAFT row (ck_events_submitted_fields_complete)
    ends_at: datetime
    submitted_at: datetime | None  # not covered by that CHECK, so honest about NULL
    status: str

    @classmethod
    def from_event(cls, event: Event) -> ReviewQueueEntry:
        # ck_events_submitted_fields_complete guarantees these for every non-DRAFT status, and
        # the review queue never returns DRAFT rows.
        starts_at, ends_at = event.starts_at, event.ends_at
        assert starts_at is not None
        assert ends_at is not None
        return cls(
            id=event.id,
            name=event.name,
            organiser_name=event.organiser.full_name,
            starts_at=starts_at,
            ends_at=ends_at,
            submitted_at=event.submitted_at,
            status=event.status,
        )
