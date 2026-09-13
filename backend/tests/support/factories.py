"""Small factories for rows tests need beyond the seed data.

Each returns a persisted ORM object (flushed, not committed - the test transaction is rolled
back anyway). Use unique names/emails so tests never collide with the seed.
"""

from __future__ import annotations

import itertools

from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.passwords import hash_password
from app.venues.models import Venue

_counter = itertools.count(1)


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


def venue_payload(**overrides) -> dict:
    """A valid POST /venues body (story 8.3 AC1 minimum) with optional overrides."""
    n = next(_counter)
    body = {"name": f"API Venue {n}", "location": "Tower Z, Level 9", "capacity": 40}
    body.update(overrides)
    return body


def event_payload(**overrides) -> dict:
    """A valid POST /events body (story 2.1 AC1 minimum: just a name) with optional overrides."""
    n = next(_counter)
    body = {"name": f"Test Event Request {n}"}
    body.update(overrides)
    return body
