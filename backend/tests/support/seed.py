"""Python mirror of the fixed IDs in backend/db/seed/020_sample_data.sql.

Keep the two files in step: tests/test_schema.py::test_seed_constants_match_database fails if
any of these rows is missing from the seeded database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

SEED_PASSWORD = "Password123!"


@dataclass(frozen=True)
class SeedUser:
    id: uuid.UUID
    email: str
    role: str
    full_name: str


def _u(n: int) -> uuid.UUID:
    return uuid.UUID(f"11111111-0000-0000-0000-{n:012d}")


class Users:
    ORGANISER = SeedUser(_u(1), "organiser@acme.example", "EVENT_ORGANISER", "Olivia Organiser")
    ORGANISER_2 = SeedUser(_u(2), "organiser@nimbus.example", "EVENT_ORGANISER", "Omar Organiser")
    COORDINATOR = SeedUser(
        _u(3), "coordinator@connectsphere.example", "EVENT_COORDINATOR", "Chloe Coordinator"
    )
    COORDINATOR_2 = SeedUser(
        _u(4), "coordinator2@connectsphere.example", "EVENT_COORDINATOR", "Carl Coordinator"
    )
    VENUE_STAFF = SeedUser(_u(5), "venue@connectsphere.example", "VENUE_STAFF", "Vera Venue")
    TECH_SUPPORT = SeedUser(_u(6), "tech@connectsphere.example", "TECH_SUPPORT_STAFF", "Theo Tech")
    ATTENDEE = SeedUser(_u(7), "attendee@example.com", "ATTENDEE", "Aiden Attendee")
    INACTIVE = SeedUser(_u(8), "inactive@connectsphere.example", "VENUE_STAFF", "Ian Inactive")

    ALL_ACTIVE = (
        ORGANISER,
        ORGANISER_2,
        COORDINATOR,
        COORDINATOR_2,
        VENUE_STAFF,
        TECH_SUPPORT,
        ATTENDEE,
    )
    ONE_PER_ROLE = (ORGANISER, COORDINATOR, VENUE_STAFF, TECH_SUPPORT, ATTENDEE)


def _v(n: int) -> uuid.UUID:
    return uuid.UUID(f"22222222-0000-0000-0000-{n:012d}")


class Venues:
    GRAND_HALL = _v(1)  # 400 seats, APPROVED booking on 2026-11-25
    SEMINAR_ROOM = _v(2)  # 80 seats, maintenance 2-4 Nov 2026
    BOARDROOM = _v(3)  # 16 seats
    EXHIBITION_FOYER = _v(4)  # 250, operating hours not recorded
    OLD_ANNEX = _v(5)  # WITHDRAWN


def _e(n: int) -> uuid.UUID:
    return uuid.UUID(f"33333333-0000-0000-0000-{n:012d}")


class Events:
    DRAFT = _e(1)  # organiser 1, incomplete
    SUBMITTED = _e(2)  # organiser 1, no coordinator yet
    APPROVED = _e(3)  # organiser 2, coordinator 1, approved booking of Grand Hall
    REJECTED = _e(4)  # organiser 2, coordinator 2


class Bookings:
    APPROVED_GRAND_HALL = uuid.UUID("44444444-0000-0000-0000-000000000001")
    PENDING_SEMINAR_ROOM = uuid.UUID("44444444-0000-0000-0000-000000000002")
