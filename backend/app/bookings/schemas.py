"""Request / response shapes for venue bookings (story 12.1 raise, 13.2 approve/read; the
response is reused as-is by story 13.1's queue and 13.4's outcome display once those exist).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BookingRequestIn(BaseModel):
    """Story 12.1 AC1: one event, against one venue - so one ``venue_id``, not a list.

    There is deliberately nothing else to send. AC2 requires the request to carry *the event's*
    schedule, attendance, layout and required facilities, so the service copies those from the
    event row; a client cannot book a period or an attendance the event was not approved for.
    """

    event_id: uuid.UUID
    venue_id: uuid.UUID


class BookingOut(BaseModel):
    """Full booking record, including the decision fields story 13.2 AC1/AC3 need."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    venue_id: uuid.UUID
    requested_by_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    setup_minutes: int
    teardown_minutes: int
    held_from: datetime
    held_until: datetime
    expected_attendance: int
    required_layout_code: str | None
    requirement_notes: str | None
    suitability_override_reason: str | None
    status: str
    decided_by_id: uuid.UUID | None
    decided_at: datetime | None
    decision_reason: str | None
    alternative_suggestion: str | None
    created_at: datetime
    updated_at: datetime
