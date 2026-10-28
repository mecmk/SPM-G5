"""Request and response models for story 18.1: the events an attendee can browse and register
for, and a registration; and for story 18.2: the attendee's own registrations.

AC5: an attendee gets only what these models declare - an event's name, description, cover picture,
dates, booked venues, places left and registration state - never its organiser, coordinator,
contact, purpose, equipment, accessibility needs or internal notes. No field carries its expected
attendance, but that shows through the places left until someone registers, since capacity is
the expected attendance (2.1 AC17) and the places left are shown (decision 1, 14 Oct 2026).

Story 18.2 AC5: of their own registrations, an attendee is sent each one's event name, cover
picture and dates, where they stand, when they registered and withdrew, and whether they can
withdraw now - nothing more of the event.

Story 18.3: an event's registration list, as its organiser and assigned coordinator see it.

Story 18.4: the attendee's details - their name, phone number and dietary requirements - as they
send them, on My profile or with their first registration, and as My profile shows them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.auth.models import User
from app.common.phone import PHONE_NUMBER_INVALID_MESSAGE, is_phone_number
from app.events.models import Event
from app.registrations.models import EventRegistration
from app.venues.models import Venue

# Story 18.4 AC6. Mirrored by the field's maxLength in frontend/src/api/registrations.ts - keep the
# two in step; ck_users_dietary_requirements holds the database to it too.
DIETARY_REQUIREMENTS_MAX_LENGTH = 500
DIETARY_REQUIREMENTS_TOO_LONG_MESSAGE = "Dietary requirements must be 500 characters or fewer."
# Story 18.4 AC7 (CL-166): the phone number is required. AC1 (CL-166): the name
# is the attendee's to change, required and as long as an event's contact name may be (2.1 AC13).
# Mirrored by the form's maxLength and checks in frontend/src/registrations/ - keep them in step.
PHONE_NUMBER_REQUIRED_MESSAGE = "Enter your phone number."
FULL_NAME_MAX_LENGTH = 200
FULL_NAME_REQUIRED_MESSAGE = "Enter your name."
FULL_NAME_TOO_LONG_MESSAGE = "Your name must be 200 characters or fewer."


class AttendeeDetailsIn(BaseModel):
    """Story 18.4: the details an attendee sends, on My profile (AC4) or with a registration (AC2,
    AC3). Only the fields sent are changed. Blank or spaces only is no value: refused for the name
    (AC1) and the phone number (AC7), which are required when sent, and None - shown as "None" -
    for dietary requirements (AC6). AC10: nothing else can be sent - not an email, nor whose
    profile it is (the signed-in attendee's, always) - so ``extra="forbid"`` refuses them."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    phone: str | None = None
    dietary_requirements: str | None = None

    @field_validator("full_name", "phone", "dietary_requirements", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip() or None

    @field_validator("full_name")
    @classmethod
    def _check_full_name(cls, value: str | None) -> str:
        """AC1: required when sent, and at most 200 characters once trimmed."""
        if value is None:
            raise ValueError(FULL_NAME_REQUIRED_MESSAGE)
        if len(value) > FULL_NAME_MAX_LENGTH:
            raise ValueError(FULL_NAME_TOO_LONG_MESSAGE)
        return value

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, value: str | None) -> str:
        """AC7: required when sent, and the event contact phone's rule (2.1 AC13)."""
        if value is None:
            raise ValueError(PHONE_NUMBER_REQUIRED_MESSAGE)
        if not is_phone_number(value):
            raise ValueError(PHONE_NUMBER_INVALID_MESSAGE)
        return value

    @field_validator("dietary_requirements")
    @classmethod
    def _check_dietary_requirements(cls, value: str | None) -> str | None:
        """AC6: at most 500 characters, counted once trimmed."""
        if value is not None and len(value) > DIETARY_REQUIREMENTS_MAX_LENGTH:
            raise ValueError(DIETARY_REQUIREMENTS_TOO_LONG_MESSAGE)
        return value


class ProfileOut(BaseModel):
    """Story 18.4 AC1: My profile - the email, which the attendee cannot change, and the details
    they keep up to date: their name, phone number and dietary requirements.
    ``has_confirmed_details`` is false until they first give them, so their first registration
    asks (AC2). No defaults (response schema)."""

    full_name: str
    email: str
    phone: str | None
    dietary_requirements: str | None
    has_confirmed_details: bool

    @classmethod
    def from_user(cls, user: User) -> ProfileOut:
        return cls(
            full_name=user.full_name,
            email=user.email,
            phone=user.phone,
            dietary_requirements=user.dietary_requirements,
            has_confirmed_details=user.attendee_details_confirmed_at is not None,
        )


class RegistrationCreate(BaseModel):
    """AC1: the event to register for. The attendee is the signed-in user, never a value sent
    with the request. Story 18.4 AC2/AC3: the attendee's details, needed with their first
    registration and saved to their profile with any."""

    event_id: uuid.UUID
    details: AttendeeDetailsIn | None = None


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
    cover_image_url: str | None  # 18.1 AC8 (fix f18.1.1): the event's cover picture, if any
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


class EventRegistrationOut(BaseModel):
    """18.3 AC1/AC4: one registration in an event's list - who, when, and where they stand, as
    18.2 tells the attendee: withdrawn ones, with when, and cancelled ones included. Story 18.4
    AC5: the attendee's phone number and dietary requirements, read from their profile, so a
    change shows at once (AC4); null when they gave none (shown as "None", AC6) and on every row
    no longer Registered (AC9). No defaults (response schema)."""

    id: uuid.UUID
    attendee_name: str
    attendee_email: str
    attendee_phone: str | None
    dietary_requirements: str | None
    registered_at: datetime
    status: str  # REGISTERED, WITHDRAWN or EVENT_CANCELLED (service.RegistrationStanding)
    withdrawn_at: datetime | None

    @classmethod
    def from_registration(
        cls, registration: EventRegistration, *, attendee: User, status: str, shows_details: bool
    ) -> EventRegistrationOut:
        return cls(
            id=registration.id,
            attendee_name=attendee.full_name,
            attendee_email=attendee.email,
            attendee_phone=attendee.phone if shows_details else None,
            dietary_requirements=attendee.dietary_requirements if shows_details else None,
            registered_at=registration.registered_at,
            status=status,
            withdrawn_at=registration.withdrawn_at,
        )


class EventRegistrationListOut(BaseModel):
    """18.3 AC1-AC3/AC7: one page of the list, how many registrations there are in all, and how
    many are active against the capacity. No defaults (response schema)."""

    items: list[EventRegistrationOut]
    total: int
    active_count: int
    capacity: int
    is_full: bool


class ManagedRegistrationEventOut(BaseModel):
    """18.3 AC5: one event on the registrations report's picker. No defaults (response schema)."""

    id: uuid.UUID
    name: str
    starts_at: datetime
    ends_at: datetime

    @classmethod
    def from_event(cls, event: Event) -> ManagedRegistrationEventOut:
        return cls(id=event.id, name=event.name, starts_at=event.starts_at, ends_at=event.ends_at)
