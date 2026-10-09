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
    """Sample events by fixture name.

    A name identifies a row; it is not a promise about that row's status. Several of these
    carry the same status, and the SUBMITTED* and APPROVED* names are not statuses an event can
    hold at all (APPROVED_2 to APPROVED_7 are all PLANNING) - the status each row actually has
    is asserted in tests/test_schema.py.
    """

    DRAFT = _e(1)  # organiser 1, incomplete
    SUBMITTED = _e(2)  # organiser 1, coordinator 1, awaiting decision (UNDER_REVIEW)
    APPROVED = _e(3)  # organiser 2, coordinator 1, approved booking of Grand Hall (PLANNING)
    REJECTED = _e(4)  # organiser 2, coordinator 2
    UNDER_REVIEW = _e(5)  # organiser 2, coordinator 1, awaiting decision
    CLARIFICATION_REQUESTED = _e(6)  # organiser 1, coordinator 1, awaiting decision
    SUBMITTED_2 = _e(7)  # organiser 1, coordinator 1, awaiting decision (UNDER_REVIEW)
    APPROVED_2 = _e(8)  # organiser 1, coordinator 2, pending booking of Exhibition Foyer
    APPROVED_3 = _e(9)  # organiser 2, coordinator 1, pending booking of Grand Hall
    APPROVED_4 = _e(10)  # organiser 1, coordinator 1, pending booking dedicated to 13.2 e2e
    APPROVED_5 = _e(11)  # organiser 2, coordinator 2, pending booking dedicated to 13.2 e2e
    PLANNING = _e(12)  # organiser 1, coordinator 1
    CONFIRMED = _e(13)  # organiser 2, coordinator 1
    COMPLETED = _e(14)  # organiser 1, coordinator 1, dated in the past
    CANCELLED = _e(15)  # organiser 2, coordinator 1
    APPROVED_6 = _e(16)  # organiser 1, coordinator 1, pending booking dedicated to 13.2.1 e2e
    APPROVED_7 = _e(17)  # organiser 2, coordinator 2, pending booking dedicated to 13.2.1 e2e
    PARTNER_BRIEFING = _e(18)  # organiser 2, coordinator 1, dedicated to 12.1's e2e request
    EQUIPMENT_WORKSHOP = _e(19)  # organiser 1, coordinator 1, dedicated to 15.1's e2e flow
    EQUIPMENT_SHOWCASE = _e(20)  # organiser 1, coordinator 1, dedicated to 15.1's e2e picker
    EQUIPMENT_ROADSHOW = _e(21)  # organiser 2, coordinator 1, dedicated to 15.2's e2e queue
    # More of 15.2's e2e queue, all organiser 2 and PLANNING, dated July-November 2027.
    FINTECH_BREAKFAST = _e(22)  # coordinator 2; overlaps CUSTOMER_FORUM on 7 July 2027
    CUSTOMER_FORUM = _e(23)  # coordinator 1
    SALES_KICKOFF = _e(24)  # coordinator 2; video cameras short by one
    RECRUITMENT_FAIR = _e(25)  # coordinator 1
    PARTNER_GALA = _e(26)  # coordinator 2; accepted and declined items only
    EQUIPMENT_DECISIONS = _e(27)  # organiser 2, coordinator 1, dedicated to 16.1's e2e decisions
    SMART_CITIES_EXPO = _e(28)  # organiser 2, coordinator 1, three requirements, for 8.4's e2e


class Bookings:
    APPROVED_GRAND_HALL = uuid.UUID("44444444-0000-0000-0000-000000000001")
    PENDING_SEMINAR_ROOM = uuid.UUID("44444444-0000-0000-0000-000000000002")
    PENDING_EXHIBITION_FOYER = uuid.UUID("44444444-0000-0000-0000-000000000003")
    PENDING_GRAND_HALL = uuid.UUID("44444444-0000-0000-0000-000000000004")
    # Reserved for the story 13.2 approve e2e test - see 020_sample_data.sql's note. Do not
    # reference these from any other test; approving them would make them unusable there.
    PENDING_APPROVE_E2E_CARD = uuid.UUID("44444444-0000-0000-0000-000000000005")
    PENDING_APPROVE_E2E_DETAIL = uuid.UUID("44444444-0000-0000-0000-000000000006")
    # Reserved for the story 13.2.1 reject e2e test - see 020_sample_data.sql's note. Do not
    # reference these from any other test; rejecting them would make them unusable there.
    PENDING_REJECT_E2E_CARD = uuid.UUID("44444444-0000-0000-0000-000000000007")
    PENDING_REJECT_E2E_DETAIL = uuid.UUID("44444444-0000-0000-0000-000000000008")


class Unavailability:
    MAINTENANCE_SEMINAR_ROOM = uuid.UUID("88888888-0000-0000-0000-000000000001")


class Clarifications:
    REQUEST = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
    RESPONSE = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


def _r(n: int) -> uuid.UUID:
    return uuid.UUID(f"cccccccc-0000-0000-0000-{n:012d}")


class VenueRequirements:
    """Story 2.7: each sample event's "Main venue" is numbered like its event (3333..NN ->
    cccc..NN). These three are the ones that also require facilities. Story 8.4: the Smart Cities
    Expo's three requirements are numbered within their event (cccc..0028-..0N)."""

    DATA_LITERACY_MAIN = _r(2)  # Events.SUBMITTED: CLASSROOM, PROJECTOR + WIFI, 60 people
    NIMBUS_MAIN = _r(3)  # Events.APPROVED: THEATRE, PROJECTOR + SOUND_SYSTEM + STAGE, 350
    PARTNER_BRIEFING_MAIN = _r(18)  # Events.PARTNER_BRIEFING: CLASSROOM, PROJECTOR, 60
    # Events.SMART_CITIES_EXPO, in the banner's order:
    EXPO_PLENARY_HALL = uuid.UUID("cccccccc-0000-0000-0028-000000000001")  # THEATRE, 300
    EXPO_BREAKOUT_ROOM = uuid.UUID("cccccccc-0000-0000-0028-000000000002")  # CLASSROOM, 40
    EXPO_EXHIBITION_SPACE = uuid.UUID("cccccccc-0000-0000-0028-000000000003")  # EXHIBITION, 150


class EquipmentItems:
    """Story 15.1's e2e items. Their events are dated May 2027, clear of the periods backend tests
    build relative to today, so the holds below never change a figure another test asserts."""

    WORKSHOP_PROJECTORS = uuid.UUID("66666666-0000-0000-0000-000000000004")  # not yet sent
    SHOWCASE_SPEAKERS = uuid.UUID("66666666-0000-0000-0000-000000000005")  # pending
    # Story 15.2's e2e items on Events.EQUIPMENT_ROADSHOW, dated June 2027: one per tab.
    ROADSHOW_LAPEL_MICS = uuid.UUID("66666666-0000-0000-0000-000000000006")  # pending, short by 4
    ROADSHOW_WIRELESS_MICS = uuid.UUID("66666666-0000-0000-0000-000000000007")  # accepted
    ROADSHOW_PROJECTORS = uuid.UUID("66666666-0000-0000-0000-000000000008")  # declined, no hold
    # Story 16.1's e2e items on Events.EQUIPMENT_DECISIONS, 8-9 December 2027, all pending.
    OFFSITE_SPEAKERS = uuid.UUID("66666666-0000-0000-0000-000000000025")  # accepted by the spec
    OFFSITE_LED_SCREEN = uuid.UUID("66666666-0000-0000-0000-000000000026")  # declined by the spec
    OFFSITE_CONF_PHONES = uuid.UUID("66666666-0000-0000-0000-000000000027")  # double-clicked
    OFFSITE_LAPTOPS = uuid.UUID("66666666-0000-0000-0000-000000000028")  # never decided
    OFFSITE_PROJECTORS = uuid.UUID("66666666-0000-0000-0000-000000000029")  # accepted, own page
    OFFSITE_WIRELESS_MICS = uuid.UUID("66666666-0000-0000-0000-000000000030")  # declined, own page
    OFFSITE_CAMERAS = uuid.UUID("66666666-0000-0000-0000-000000000031")  # decided from 2 pages


class EquipmentHolds:
    WORKSHOP_PROJECTORS = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
    SHOWCASE_SPEAKERS = uuid.UUID("eeeeeeee-0000-0000-0000-000000000002")
    ROADSHOW_LAPEL_MICS = uuid.UUID("eeeeeeee-0000-0000-0000-000000000003")
    ROADSHOW_WIRELESS_MICS = uuid.UUID("eeeeeeee-0000-0000-0000-000000000004")
    OFFSITE_SPEAKERS = uuid.UUID("eeeeeeee-0000-0000-0000-000000000018")
    OFFSITE_LED_SCREEN = uuid.UUID("eeeeeeee-0000-0000-0000-000000000019")
    OFFSITE_CONF_PHONES = uuid.UUID("eeeeeeee-0000-0000-0000-000000000020")
    OFFSITE_LAPTOPS = uuid.UUID("eeeeeeee-0000-0000-0000-000000000021")
    OFFSITE_PROJECTORS = uuid.UUID("eeeeeeee-0000-0000-0000-000000000022")
    OFFSITE_WIRELESS_MICS = uuid.UUID("eeeeeeee-0000-0000-0000-000000000023")
    OFFSITE_CAMERAS = uuid.UUID("eeeeeeee-0000-0000-0000-000000000024")


class EquipmentOutOfService:
    SHOWCASE_CAMERAS = uuid.UUID("dddddddd-0000-0000-0000-000000000001")  # every video camera
    ROADSHOW_LAPEL_MICS = uuid.UUID("dddddddd-0000-0000-0000-000000000002")  # 4 lapel microphones
