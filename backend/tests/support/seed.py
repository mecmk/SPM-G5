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
    SAFETY_OFFICER = SeedUser(_u(9), "safety@connectsphere.example", "SAFETY_OFFICER", "Sam Safety")
    # Story 5.4: reviews the unassigned queue and assigns events to coordinators.
    LEAD = SeedUser(_u(10), "lead@connectsphere.example", "EVENT_COORDINATOR_LEAD", "Lena Lead")
    # Story 18.1: holds the one place at Events.PORTFOLIO_REVIEW.
    ATTENDEE_2 = SeedUser(_u(11), "attendee2@example.com", "ATTENDEE", "Bella Attendee")

    ALL_ACTIVE = (
        ORGANISER,
        ORGANISER_2,
        COORDINATOR,
        COORDINATOR_2,
        VENUE_STAFF,
        TECH_SUPPORT,
        ATTENDEE,
        SAFETY_OFFICER,
        LEAD,
        ATTENDEE_2,
    )
    ONE_PER_ROLE = (
        ORGANISER,
        COORDINATOR,
        VENUE_STAFF,
        TECH_SUPPORT,
        ATTENDEE,
        SAFETY_OFFICER,
        LEAD,
    )


def _v(n: int) -> uuid.UUID:
    return uuid.UUID(f"22222222-0000-0000-0000-{n:012d}")


class Venues:
    GRAND_HALL = _v(1)  # 400 seats, APPROVED booking on 2026-11-25
    SEMINAR_ROOM = _v(2)  # 80 seats, maintenance 2-4 Nov 2026
    BOARDROOM = _v(3)  # 16 seats
    EXHIBITION_FOYER = _v(4)  # 250, operating hours not recorded
    OLD_ANNEX = _v(5)  # WITHDRAWN
    # Story 9.4's e2e spec; each dedicated to it, with no operating hours.
    GARDEN_ATRIUM = _v(6)  # no booking: a closure is added, edited and ended here
    HARBOUR_PAVILION = _v(7)  # one pending request (Events.CHOIR_SHOWCASE), for the preview
    SUNRISE_STUDIO = _v(8)  # one pending request (Events.ART_MARKET), for the marked request


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
    PARTNER_BRIEFING = _e(18)  # organiser 2, coordinator 1, 11.1's e2e spec, no request written
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
    # Story 17.1's e2e event: organiser 2, coordinator 1, PLANNING, 19 January 2028.
    WATERFRONT_DEMO = _e(80)  # one pending item (EquipmentItems.DEMO_LAPTOPS), accepted by the spec
    SMART_CITIES_EXPO = _e(28)  # organiser 2, coordinator 1, three requirements, for 8.4's e2e
    MOBILITY_FORUM = _e(29)  # organiser 2, coordinator 1, three requirements, for 12.5's e2e
    RESILIENCE_WORKSHOP = _e(30)  # organiser 2, coordinator 1, its one requirement booked
    ONBOARDING_DAY = _e(31)  # organiser 2, coordinator 1, 12.1's real send since 12.5
    TRADE_FAIR = _e(32)  # organiser 2, coordinator 1, 12.5's withdraw and switch e2e flow
    PRICING_CLINIC = _e(33)  # organiser 2, coordinator 1, 11.1's justified send since 12.5
    CRAFT_FAIR = _e(34)  # organiser 2, coordinator 1, its one request expired, for 12.7's e2e
    # Story 21.1's, both organiser 2, coordinator 2 and AWAITING_SAFETY_CHECK, August 2028.
    HARBOUR_CONCERT = _e(35)  # 300 expected at the 250-seat Exhibition Foyer; first in the queue
    BOOK_FAIR = _e(36)  # within capacity; sent back once (SafetyReviews.BOOK_FAIR_CHANGES)
    # Story 21.1's reviewed events, organiser 2, coordinator 2, no venue booked.
    FOOD_FESTIVAL = _e(37)  # CONFIRMED; approved (SafetyReviews.FOOD_FESTIVAL_APPROVED)
    NIGHT_WALK = _e(38)  # PLANNING; sent back and not resent (SafetyReviews.NIGHT_WALK_CHANGES)
    # Story 18.1's, all CONFIRMED, Public and taking registrations: organiser 2, coordinator 2.
    # Each is one case of tests/e2e/attendee-registration.spec.ts. Only the jazz evening has venues
    # booked.
    JAZZ_EVENING = _e(39)  # open, 120 places, two venues; only read
    DESIGN_MASTERCLASS = _e(40)  # open, 60 places; the spec registers for it
    FOUNDERS_FIRESIDE = _e(41)  # open, 80 places; the spec double-clicks Register
    MENTORING_SLOT = _e(42)  # open, 1 place; the spec's two attendees race for it
    PORTFOLIO_REVIEW = _e(43)  # 1 place, held by Users.ATTENDEE_2 (Registrations.PORTFOLIO_REVIEW)
    WINE_APPRECIATION = _e(44)  # registration closed on 1 Oct 2026
    LUNAR_NEW_YEAR_MARKET = _e(45)  # registration opens on 10 Jan 2028
    # Fix f12.1.2's real send with a setup, PLANNING, dated 3 February 2027.
    SUPPLIER_INDUCTION = _e(46)  # organiser 2, coordinator 1, one Main venue (Classroom, 30)
    # Story 9.4's e2e events, organiser 2, coordinator 1, PLANNING, October 2028, one pending
    # request each at a venue dedicated to that spec.
    CHOIR_SHOWCASE = _e(60)  # Harbour Pavilion
    ART_MARKET = _e(61)  # Sunrise Studio
    # Story 21.2's e2e events: organiser 1, coordinator 1, Seminar Room 2.1 booked, Nov 2028.
    CODING_BOOTCAMP = _e(50)  # PLANNING, secured, never reviewed
    CYBER_CLINIC = _e(47)  # AWAITING_SAFETY_CHECK; the spec requests changes
    DATA_SUMMIT = _e(48)  # PLANNING; sent back with its venue flagged, venue unchanged
    AI_WORKSHOP = _e(49)  # AWAITING_SAFETY_CHECK; the spec approves, then confirms
    # Story 19.2 AC8's e2e event, set up as CODING_BOOTCAMP: PLANNING, secured, never reviewed.
    DESIGN_SPRINT = _e(51)
    # Story 18.2's: organiser 2, coordinator 2, each with one of Users.ATTENDEE's registrations
    # (Registrations below), for tests/e2e/my-registrations.spec.ts. Each case that withdraws has
    # one of its own; the cases that only read share them, the yoga's most of all.
    POETRY_NIGHT = _e(70)  # CONFIRMED, 1 place, his: Full; the spec withdraws and it comes back
    SKETCHING_WALK = _e(71)  # CONFIRMED; the spec withdraws and registers again
    BOARD_GAMES_SOCIAL = _e(72)  # CONFIRMED; the spec double-clicks Withdraw
    SUNSET_YOGA = _e(73)  # CONFIRMED; only read
    HERITAGE_TRAIL = _e(74)  # CONFIRMED; he withdrew
    CHARITY_FUN_RUN = _e(75)  # CANCELLED, his registration still active
    BOOK_SWAP = _e(76)  # CONFIRMED, started on 3 Oct 2026
    LANTERN_PAINTING = _e(77)  # CONFIRMED; the spec withdraws once the server answers again


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
    # Story 12.5: Events.RESILIENCE_WORKSHOP's Meeting room, Seminar Room 2.1, approved.
    APPROVED_WORKSHOP_SEMINAR_ROOM = uuid.UUID("44444444-0000-0000-0000-000000000009")
    # Story 12.7: Events.CRAFT_FAIR's Craft hall, Exhibition Foyer, expired on 5 Oct 2026.
    EXPIRED_CRAFT_FAIR_FOYER = uuid.UUID("44444444-0000-0000-0000-000000000010")
    # Story 21.1: each safety-check event's one venue, approved.
    APPROVED_CONCERT_FOYER = uuid.UUID("44444444-0000-0000-0000-000000000011")
    APPROVED_BOOK_FAIR_GRAND_HALL = uuid.UUID("44444444-0000-0000-0000-000000000012")
    # Story 18.1: Events.JAZZ_EVENING's two venues, approved, each hold completed.
    APPROVED_JAZZ_GRAND_HALL = uuid.UUID("44444444-0000-0000-0000-000000000013")
    APPROVED_JAZZ_FOYER = uuid.UUID("44444444-0000-0000-0000-000000000014")  # extra venue
    # Story 21.2's, each at Seminar Room 2.1.
    APPROVED_BOOTCAMP_SEMINAR_ROOM = uuid.UUID("44444444-0000-0000-0000-000000000015")
    APPROVED_CYBER_CLINIC_SEMINAR_ROOM = uuid.UUID("44444444-0000-0000-0000-000000000016")
    APPROVED_DATA_SUMMIT_SEMINAR_ROOM = uuid.UUID("44444444-0000-0000-0000-000000000017")
    APPROVED_AI_WORKSHOP_SEMINAR_ROOM = uuid.UUID("44444444-0000-0000-0000-000000000018")
    # Story 19.2: Events.DESIGN_SPRINT's Studio, at Seminar Room 2.1.
    APPROVED_DESIGN_SPRINT_SEMINAR_ROOM = uuid.UUID("44444444-0000-0000-0000-000000000019")


class Registrations:
    """Story 18.1: Users.ATTENDEE_2's place at Events.PORTFOLIO_REVIEW, its only one. Story 18.2:
    Users.ATTENDEE's, one for each of 18.2's events, named after it."""

    PORTFOLIO_REVIEW = uuid.UUID("18181818-0000-0000-0000-000000000001")
    POETRY_NIGHT = uuid.UUID("18181818-0000-0000-0000-000000000002")
    SKETCHING_WALK = uuid.UUID("18181818-0000-0000-0000-000000000003")
    BOARD_GAMES_SOCIAL = uuid.UUID("18181818-0000-0000-0000-000000000004")
    SUNSET_YOGA = uuid.UUID("18181818-0000-0000-0000-000000000005")
    HERITAGE_TRAIL = uuid.UUID("18181818-0000-0000-0000-000000000006")  # WITHDRAWN
    CHARITY_FUN_RUN = uuid.UUID("18181818-0000-0000-0000-000000000007")
    BOOK_SWAP = uuid.UUID("18181818-0000-0000-0000-000000000008")
    LANTERN_PAINTING = uuid.UUID("18181818-0000-0000-0000-000000000009")


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
    # Story 12.5: Nimbus's second, which Bookings' pending Seminar Room 2.1 request is for.
    NIMBUS_BREAKOUT = uuid.UUID("cccccccc-0000-0000-0003-000000000002")  # CLASSROOM, PROJECTOR, 60
    PARTNER_BRIEFING_MAIN = _r(18)  # Events.PARTNER_BRIEFING: CLASSROOM, PROJECTOR, 60
    # Events.SMART_CITIES_EXPO, in the banner's order:
    EXPO_PLENARY_HALL = uuid.UUID("cccccccc-0000-0000-0028-000000000001")  # THEATRE, 300
    EXPO_BREAKOUT_ROOM = uuid.UUID("cccccccc-0000-0000-0028-000000000002")  # CLASSROOM, 40
    EXPO_EXHIBITION_SPACE = uuid.UUID("cccccccc-0000-0000-0028-000000000003")  # EXHIBITION, 150
    # Story 12.5: Events.MOBILITY_FORUM's, in the banner's order, and Events.RESILIENCE_WORKSHOP's.
    FORUM_EXPO_HALL = uuid.UUID("cccccccc-0000-0000-0029-000000000001")  # STANDING, 200
    FORUM_WORKSHOP_ROOM = uuid.UUID("cccccccc-0000-0000-0029-000000000002")  # CLASSROOM, 40
    FORUM_NETWORKING_LOUNGE = uuid.UUID("cccccccc-0000-0000-0029-000000000003")  # STANDING, 100
    WORKSHOP_MEETING_ROOM = uuid.UUID("cccccccc-0000-0000-0030-000000000001")  # CLASSROOM, 12
    ONBOARDING_TRAINING_ROOM = uuid.UUID("cccccccc-0000-0000-0031-000000000001")  # CLASSROOM
    # Story 12.7: Events.CRAFT_FAIR's one, whose request expired.
    CRAFT_FAIR_HALL = uuid.UUID("cccccccc-0000-0000-0034-000000000001")  # EXHIBITION, WIFI, 120


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
    # Story 21.1's, accepted, on Events.HARBOUR_CONCERT and Events.BOOK_FAIR in August 2028.
    CONCERT_SPEAKERS = uuid.UUID("66666666-0000-0000-0000-000000000032")
    BOOK_FAIR_WIRELESS_MICS = uuid.UUID("66666666-0000-0000-0000-000000000033")
    # Story 17.1's: cancelled with Events.CANCELLED, holding nothing - one had been accepted, one
    # was still pending, one declined - and the pending one on Events.WATERFRONT_DEMO.
    MIXER_SPEAKERS = uuid.UUID("66666666-0000-0000-0000-000000000034")
    MIXER_WIRELESS_MICS = uuid.UUID("66666666-0000-0000-0000-000000000035")
    MIXER_PROJECTOR = uuid.UUID("66666666-0000-0000-0000-000000000037")
    DEMO_LAPTOPS = uuid.UUID("66666666-0000-0000-0000-000000000036")


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
    CONCERT_SPEAKERS = uuid.UUID("eeeeeeee-0000-0000-0000-000000000025")
    BOOK_FAIR_WIRELESS_MICS = uuid.UUID("eeeeeeee-0000-0000-0000-000000000026")
    DEMO_LAPTOPS = uuid.UUID("eeeeeeee-0000-0000-0000-000000000027")


class EquipmentOutOfService:
    SHOWCASE_CAMERAS = uuid.UUID("dddddddd-0000-0000-0000-000000000001")  # every video camera
    ROADSHOW_LAPEL_MICS = uuid.UUID("dddddddd-0000-0000-0000-000000000002")  # 4 lapel microphones


class SafetyReviews:
    # Story 21.1: Events.BOOK_FAIR's earlier review, when it expected 120 and had 2 microphones.
    BOOK_FAIR_CHANGES = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
    FOOD_FESTIVAL_APPROVED = uuid.UUID("ffffffff-0000-0000-0000-000000000002")
    NIGHT_WALK_CHANGES = uuid.UUID("ffffffff-0000-0000-0000-000000000003")
    # Story 21.2: Events.DATA_SUMMIT's, with one finding flagging its venue bookings.
    DATA_SUMMIT_CHANGES = uuid.UUID("ffffffff-0000-0000-0000-000000000004")
