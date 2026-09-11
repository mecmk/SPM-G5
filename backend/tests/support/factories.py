"""Small factories for rows tests need beyond the seed data.

Each returns a persisted ORM object (flushed, not committed - the test transaction is rolled
back anyway). Use unique names/emails so tests never collide with the seed.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.passwords import hash_password
from app.events.models import Event, EventStatus
from app.venues.models import Venue
from tests.support.seed import Users

_counter = itertools.count(1)
_EVENT_PERIOD = (
    datetime(2026, 12, 1, 9, 0, tzinfo=timezone.utc),
    datetime(2026, 12, 1, 17, 0, tzinfo=timezone.utc),
)


def make_user(
    db: Session,
    *,
    role: str = "EVENT_ORGANISER",
    password: str = "Password123!",
    is_active: bool = True,
    **overrides,
) -> User:
    n = next(_counter)
    user = User(
        email=overrides.pop("email", f"user{n}@test.example"),
        password_hash=hash_password(password),
        full_name=overrides.pop("full_name", f"Test User {n}"),
        role_code=role,
        is_active=is_active,
        **overrides,
    )
    db.add(user)
    db.flush()
    return user


def make_venue(db: Session, **overrides) -> Venue:
    n = next(_counter)
    venue = Venue(
        name=overrides.pop("name", f"Test Venue {n}"),
        location=overrides.pop("location", "Test Tower"),
        capacity=overrides.pop("capacity", 50),
        **overrides,
    )
    db.add(venue)
    db.flush()
    return venue


def make_event(db: Session, *, status: str = EventStatus.SUBMITTED, **overrides) -> Event:
    """An event in any lifecycle status.

    Non-DRAFT rows must carry the mandatory fields (``ck_events_submitted_fields_complete``),
    so those are filled in unless the caller overrides them.
    """
    n = next(_counter)
    starts_at, ends_at = _EVENT_PERIOD
    event = Event(
        organiser_id=overrides.pop("organiser_id", Users.ORGANISER.id),
        name=overrides.pop("name", f"Test Event {n}"),
        status=status,
        purpose=overrides.pop("purpose", "Testing"),
        starts_at=overrides.pop("starts_at", starts_at),
        ends_at=overrides.pop("ends_at", ends_at),
        expected_attendance=overrides.pop("expected_attendance", 25),
        **overrides,
    )
    db.add(event)
    db.flush()
    return event


def venue_payload(**overrides) -> dict:
    """A valid POST /venues body (story 8.3 AC1 minimum) with optional overrides."""
    n = next(_counter)
    body = {"name": f"API Venue {n}", "location": "Tower Z, Level 9", "capacity": 40}
    body.update(overrides)
    return body
