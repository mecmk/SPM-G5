"""Request and response models for story 18.1: the events an attendee can browse and register
for, and a registration; and for story 18.2: the attendee's own registrations.

AC5: what an attendee is sent is only what these models declare - an event's name, description,
dates, booked venues, places left and registration state - never its organiser, coordinator,
contact, purpose, equipment, accessibility needs or internal notes. No field carries its expected
attendance, but that shows through the places left until someone registers, since capacity is
the expected attendance (2.1 AC17) and the places left are shown (decision 1, 14 Oct 2026).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.events.models import Event
from app.registrations.models import EventRegistration
from app.venues.models import Venue


class RegistrationCreate(BaseModel):
    """AC1: the event to register for. The attendee is the signed-in user, never a value sent
    with the request."""

    event_id: uuid.UUID


class RegistrationVenueOut(BaseModel):
    """AC1: a venue booked for the event, as an attendee needs it: its name and where it is. No
    defaults (response schema)."""

    name: str
    location: str


class RegistrationEventOut(BaseModel):
    """AC1: one event in the attendee's list. ``registration_closes_at`` is when registration
    closes - the closing time, or the event's start where none was recorded (AC2).
    ``registered_at`` is when the signed-in attendee registered, null unless ``state`` is
    REGISTERED. AC5: nothing internal. No defaults (response schema)."""

    id: uuid.UUID
    name: str
    description: str | None
    cover_image_url: str | None  # 2.1 AC14: the event's cover picture, if it has one
    starts_at: datetime
    ends_at: datetime
    venues: list[RegistrationVenueOut]
    registration_opens_at: datetime | None
    registration_closes_at: datetime
    places_left: int
    state: str  # OPEN, NOT_YET_OPEN, FULL, CLOSED or REGISTERED (service.RegistrationState)
    registered_at: datetime | None

    @classmethod
    def from_event(
        cls,
        event: Event,
        *,
        venues: list[Venue],
        closes_at: datetime,
        places_left: int,
        state: str,
        registered_at: datetime | None,
    ) -> RegistrationEventOut:
        # ck_events_submitted_fields_complete guarantees these for every non-DRAFT status, and
        # only CONFIRMED events are listed.
        assert event.starts_at is not None
        assert event.ends_at is not None
        return cls(
            id=event.id,
            name=event.name,
            description=event.description,
            cover_image_url=event.cover_image_url,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            venues=[
                RegistrationVenueOut(name=venue.name, location=venue.location) for venue in venues
            ],
            registration_opens_at=event.registration_opens_at,
            registration_closes_at=closes_at,
            places_left=places_left,
            state=state,
            registered_at=registered_at,
        )


class RegistrationEventList(BaseModel):
    """AC1: one page of the list, and how many events it holds in all, so the page can say how
    many more there are. No defaults (response schema)."""

    items: list[RegistrationEventOut]
    total: int


class RegistrationOut(BaseModel):
    """AC1: the registration just made, with the moment it was made, for the confirmation. AC5:
    nothing but the registration itself. No defaults (response schema)."""

    id: uuid.UUID
    event_id: uuid.UUID
    status: str
    registered_at: datetime

    @classmethod
    def from_registration(cls, registration: EventRegistration) -> RegistrationOut:
        return cls(
            id=registration.id,
            event_id=registration.event_id,
            status=registration.status,
            registered_at=registration.registered_at,
        )


class MyRegistrationOut(BaseModel):
    """Story 18.2 AC1: one of the attendee's own registrations - its event's name and dates, where
    they stand, when they registered and withdrew, and whether it can be withdrawn now (AC3), so
    the page never decides that on the browser's clock. AC5: nothing internal to the event's
    planning. No defaults (response schema)."""

    id: uuid.UUID
    event_id: uuid.UUID
    event_name: str
    cover_image_url: str | None  # 2.1 AC14: the event's cover picture, if it has one
    starts_at: datetime
    ends_at: datetime
    status: str  # REGISTERED, WITHDRAWN or EVENT_CANCELLED (service.RegistrationStanding)
    registered_at: datetime
    withdrawn_at: datetime | None
    can_withdraw: bool

    @classmethod
    def from_registration(
        cls, registration: EventRegistration, *, event: Event, status: str, can_withdraw: bool
    ) -> MyRegistrationOut:
        # Registrations are only taken for Confirmed events, and
        # ck_events_submitted_fields_complete guarantees these for every non-DRAFT status.
        assert event.starts_at is not None
        assert event.ends_at is not None
        return cls(
            id=registration.id,
            event_id=event.id,
            event_name=event.name,
            cover_image_url=event.cover_image_url,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            status=status,
            registered_at=registration.registered_at,
            withdrawn_at=registration.withdrawn_at,
            can_withdraw=can_withdraw,
        )
