"""Story 11.1 - venue suitability with reasons and override: the suitability check itself, and the
indicator on each catalogue search result.

``judge_suitability`` judges ONE venue requirement against ONE venue's recorded characteristics.
It is pure - the catalogue search and the booking request both call it with plain values - so
the tests of the check itself need no database. The tests of ``GET /venues/search?event=`` below
them do.

AC1  Suitable or Unsuitable for one requirement, based only on that requirement and the venue's
     recorded characteristics. Each failed criterion carries the requirement's value and the
     venue's (e.g. "Capacity 80 < 120 people").
AC3  Suitability is worked out on the server and returned with each search result.
AC4  Capacity equal to the number of people counts as suitable; one less does not. A required
     facility quantity of 3 is met by 3 and not by 2.
AC5  A characteristic the venue has not recorded is Unknown and never treated as met. An event
     with "No venue requirements" is judged on capacity only. No indicator outside event context.
AC6  Only the event's assigned coordinator sees indicators.
AC7  If the event's requirements change, indicators are recalculated on the next search.

Until story 8.4 lets the coordinator choose one, the requirement judged is the event's first.

``GET /venues/{id}/suitability?event=`` is the request step's read of one venue (AC2, AC3),
for the event's assigned coordinator only (AC6). It and the search share one check, so they
cannot disagree. An event with no expected attendance yet (a draft) cannot be judged, in either.

AC8 is not covered here. The check judges one requirement at a time, which AC8 builds on, but
each booking request carrying its own result and justification waits for story 12.5.

Decided for this story (6 Oct 2026):
- With a layout required, capacity is that layout's recorded capacity, else the venue's maximum.
  A layout the venue does not offer is a failure of its own.
- A missing accessibility feature is a failed criterion.
- A list the venue recorded nothing in is Unknown; a recorded list without the required item is
  Not met; a facility quantity the venue did not record, where one is required, is Unknown.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.events.models import Event, EventStatus
from app.venues import service as venue_service
from app.venues.suitability import (
    Criterion,
    FailedCriterion,
    Outcome,
    RequiredFacility,
    RequiredItem,
    RequirementNeeds,
    VenueCharacteristics,
    judge_suitability,
)
from tests.support.factories import make_event, make_venue, make_venue_requirement
from tests.support.seed import Users

THEATRE = RequiredItem(code="THEATRE", name="Theatre")
BANQUET = RequiredItem(code="BANQUET", name="Banquet")
CLASSROOM = RequiredItem(code="CLASSROOM", name="Classroom")
WHEELCHAIR_ACCESS = RequiredItem(code="WHEELCHAIR_ACCESS", name="Wheelchair access")
HEARING_LOOP = RequiredItem(code="HEARING_LOOP", name="Hearing loop")


def _projector(quantity: int | None = None) -> RequiredFacility:
    return RequiredFacility(code="PROJECTOR", name="Projector & screen", quantity=quantity)


def _needs(
    *,
    people: int = 100,
    layout: RequiredItem | None = None,
    facilities: tuple[RequiredFacility, ...] = (),
    accessibility: tuple[RequiredItem, ...] = (),
    name: str = "Main venue",
) -> RequirementNeeds:
    return RequirementNeeds(
        name=name,
        people=people,
        layout=layout,
        facilities=facilities,
        accessibility=accessibility,
    )


def _venue(
    *,
    capacity: int = 400,
    layouts: dict[str, int | None] | None = None,
    facilities: dict[str, int | None] | None = None,
    accessibility: frozenset[str] | None = None,
) -> VenueCharacteristics:
    """A venue that recorded something in every list unless a test says otherwise, so a test
    about one characteristic is not also judged Unknown on another."""
    return VenueCharacteristics(
        capacity=capacity,
        layouts={"THEATRE": None} if layouts is None else layouts,
        facilities={"WIFI": None} if facilities is None else facilities,
        accessibility=(
            frozenset({"WHEELCHAIR_ACCESS"}) if accessibility is None else accessibility
        ),
    )


@pytest.mark.story("11.1", ac=1)
def test_a_venue_meeting_every_criterion_is_suitable():
    needs = _needs(
        people=300,
        layout=THEATRE,
        facilities=(_projector(2),),
        accessibility=(WHEELCHAIR_ACCESS,),
    )
    venue = _venue(
        capacity=400,
        layouts={"THEATRE": None},
        facilities={"PROJECTOR": 2},
        accessibility=frozenset({"WHEELCHAIR_ACCESS"}),
    )

    result = judge_suitability(needs, venue)

    assert result.requirement_name == "Main venue"
    assert result.is_suitable is True
    assert result.failures == ()


@pytest.mark.story("11.1", ac=1)
def test_short_capacity_fails_with_the_people_needed_and_the_venues_capacity():
    result = judge_suitability(_needs(people=120), _venue(capacity=80))

    assert result.is_suitable is False
    assert result.failures == (
        FailedCriterion(
            criterion=Criterion.CAPACITY,
            outcome=Outcome.NOT_MET,
            code=None,
            name=None,
            required=120,
            venue_value=80,
        ),
    )


@pytest.mark.story("11.1", ac=1)
def test_every_failed_criterion_is_listed_in_a_fixed_order():
    needs = _needs(
        people=300,
        layout=THEATRE,
        facilities=(_projector(),),
        accessibility=(HEARING_LOOP,),
    )
    venue = _venue(
        capacity=80,
        layouts={"CLASSROOM": None},
        facilities={"WIFI": None},
        accessibility=frozenset({"WHEELCHAIR_ACCESS"}),
    )

    result = judge_suitability(needs, venue)

    assert [failure.criterion for failure in result.failures] == [
        Criterion.CAPACITY,
        Criterion.LAYOUT,
        Criterion.FACILITY,
        Criterion.ACCESSIBILITY,
    ]


@pytest.mark.story("11.1", ac=1)
def test_a_layout_the_venue_does_not_offer_fails_and_capacity_is_its_maximum():
    """The venue's Banquet capacity of 100 is not what Theatre is compared with: it does not
    offer Theatre at all, so its maximum (400) holds the 300 people and only the layout fails."""
    needs = _needs(people=300, layout=THEATRE)
    venue = _venue(capacity=400, layouts={"BANQUET": 100})

    result = judge_suitability(needs, venue)

    assert result.failures == (
        FailedCriterion(
            criterion=Criterion.LAYOUT,
            outcome=Outcome.NOT_MET,
            code="THEATRE",
            name="Theatre",
            required=None,
            venue_value=None,
        ),
    )


@pytest.mark.story("11.1", ac=1)
def test_a_required_facility_the_venue_does_not_offer_fails():
    result = judge_suitability(
        _needs(facilities=(_projector(),)), _venue(facilities={"WIFI": None})
    )

    assert result.failures == (
        FailedCriterion(
            criterion=Criterion.FACILITY,
            outcome=Outcome.NOT_MET,
            code="PROJECTOR",
            name="Projector & screen",
            required=None,
            venue_value=None,
        ),
    )


@pytest.mark.story("11.1", ac=1)
def test_a_needed_accessibility_feature_the_venue_lacks_fails():
    result = judge_suitability(
        _needs(accessibility=(HEARING_LOOP,)),
        _venue(accessibility=frozenset({"WHEELCHAIR_ACCESS"})),
    )

    assert result.failures == (
        FailedCriterion(
            criterion=Criterion.ACCESSIBILITY,
            outcome=Outcome.NOT_MET,
            code="HEARING_LOOP",
            name="Hearing loop",
            required=None,
            venue_value=None,
        ),
    )


@pytest.mark.story("11.1", ac=1)
def test_with_a_layout_its_recorded_capacity_is_compared_not_the_maximum():
    """Banquet seats 240 in a 400-person hall, so 250 people in Banquet do not fit."""
    result = judge_suitability(
        _needs(people=250, layout=BANQUET), _venue(capacity=400, layouts={"BANQUET": 240})
    )

    assert result.failures == (
        FailedCriterion(
            criterion=Criterion.CAPACITY,
            outcome=Outcome.NOT_MET,
            code="BANQUET",
            name="Banquet",
            required=250,
            venue_value=240,
        ),
    )


@pytest.mark.story("11.1", ac=1)
def test_a_layout_with_no_capacity_of_its_own_uses_the_venues_maximum():
    result = judge_suitability(
        _needs(people=400, layout=THEATRE), _venue(capacity=400, layouts={"THEATRE": None})
    )

    assert result.is_suitable is True


@pytest.mark.story("11.1", ac=1)
def test_a_layout_with_no_capacity_of_its_own_fails_on_the_maximum_naming_no_layout():
    """Theatre is offered with no capacity of its own, so the venue's maximum (300) is what was
    compared - the failure names no layout, since no layout's capacity was involved."""
    result = judge_suitability(
        _needs(people=350, layout=THEATRE), _venue(capacity=300, layouts={"THEATRE": None})
    )

    assert result.failures == (
        FailedCriterion(
            criterion=Criterion.CAPACITY,
            outcome=Outcome.NOT_MET,
            code=None,
            name=None,
            required=350,
            venue_value=300,
        ),
    )


@pytest.mark.story("11.1", ac=1)
def test_each_requirement_is_judged_on_its_own():
    """One venue, two requirements of one event: the plenary fails, the breakout does not, and
    neither result carries the other's failures. Groundwork for AC8, which is not tagged here:
    its booking-level part (each request carrying its own result) waits for story 12.5."""
    venue = _venue(capacity=80, layouts={"CLASSROOM": None}, facilities={"PROJECTOR": 1})
    plenary = _needs(name="Plenary hall", people=300, layout=THEATRE)
    breakout = _needs(name="Breakout", people=40, layout=CLASSROOM, facilities=(_projector(1),))

    plenary_result = judge_suitability(plenary, venue)
    breakout_result = judge_suitability(breakout, venue)

    assert plenary_result.requirement_name == "Plenary hall"
    assert [failure.criterion for failure in plenary_result.failures] == [
        Criterion.CAPACITY,
        Criterion.LAYOUT,
    ]
    assert breakout_result.requirement_name == "Breakout"
    assert breakout_result.is_suitable is True
    assert breakout_result.failures == ()


@pytest.mark.story("11.1", ac=4)
@pytest.mark.parametrize(("capacity", "is_suitable"), [(120, True), (119, False)])
def test_capacity_equal_to_the_people_is_suitable_and_one_less_is_not(capacity, is_suitable):
    result = judge_suitability(_needs(people=120), _venue(capacity=capacity))

    assert result.is_suitable is is_suitable


@pytest.mark.story("11.1", ac=4)
@pytest.mark.parametrize(("layout_capacity", "is_suitable"), [(120, True), (119, False)])
def test_layout_capacity_equal_to_the_people_is_suitable_and_one_less_is_not(
    layout_capacity, is_suitable
):
    result = judge_suitability(
        _needs(people=120, layout=BANQUET),
        _venue(capacity=400, layouts={"BANQUET": layout_capacity}),
    )

    assert result.is_suitable is is_suitable


@pytest.mark.story("11.1", ac=4)
def test_a_facility_quantity_of_3_is_met_by_3():
    result = judge_suitability(
        _needs(facilities=(_projector(3),)), _venue(facilities={"PROJECTOR": 3})
    )

    assert result.is_suitable is True


@pytest.mark.story("11.1", ac=4)
def test_a_facility_quantity_of_3_is_not_met_by_2():
    result = judge_suitability(
        _needs(facilities=(_projector(3),)), _venue(facilities={"PROJECTOR": 2})
    )

    assert result.failures == (
        FailedCriterion(
            criterion=Criterion.FACILITY_QUANTITY,
            outcome=Outcome.NOT_MET,
            code="PROJECTOR",
            name="Projector & screen",
            required=3,
            venue_value=2,
        ),
    )


@pytest.mark.story("11.1", ac=5)
def test_an_unrecorded_facility_quantity_is_unknown_and_never_met():
    result = judge_suitability(
        _needs(facilities=(_projector(2),)), _venue(facilities={"PROJECTOR": None})
    )

    assert result.is_suitable is False
    assert result.failures == (
        FailedCriterion(
            criterion=Criterion.FACILITY_QUANTITY,
            outcome=Outcome.UNKNOWN,
            code="PROJECTOR",
            name="Projector & screen",
            required=2,
            venue_value=None,
        ),
    )


@pytest.mark.story("11.1", ac=5)
def test_a_facility_needing_no_quantity_is_met_when_offered():
    result = judge_suitability(
        _needs(facilities=(_projector(),)), _venue(facilities={"PROJECTOR": None})
    )

    assert result.is_suitable is True


@pytest.mark.story("11.1", ac=5)
def test_capacity_only_needs_are_judged_on_capacity_alone():
    """An event with "No venue requirements" needs only its people held. A venue that recorded
    nothing in any list is not Unknown for it, since nothing is asked of those lists."""
    bare_venue = _venue(capacity=60, layouts={}, facilities={}, accessibility=frozenset())

    fits = judge_suitability(_needs(people=60), bare_venue)
    too_small = judge_suitability(_needs(people=61), bare_venue)

    assert fits.is_suitable is True
    assert [failure.criterion for failure in too_small.failures] == [Criterion.CAPACITY]


@pytest.mark.story("11.1", ac=5)
@pytest.mark.parametrize(
    ("needs", "venue", "expected"),
    [
        pytest.param(
            _needs(layout=THEATRE),
            _venue(layouts={}),
            FailedCriterion(
                criterion=Criterion.LAYOUT,
                outcome=Outcome.UNKNOWN,
                code="THEATRE",
                name="Theatre",
                required=None,
                venue_value=None,
            ),
            id="layouts",
        ),
        pytest.param(
            _needs(facilities=(_projector(3),)),
            _venue(facilities={}),
            FailedCriterion(
                criterion=Criterion.FACILITY,
                outcome=Outcome.UNKNOWN,
                code="PROJECTOR",
                name="Projector & screen",
                required=3,
                venue_value=None,
            ),
            id="facilities",
        ),
        pytest.param(
            _needs(accessibility=(HEARING_LOOP,)),
            _venue(accessibility=frozenset()),
            FailedCriterion(
                criterion=Criterion.ACCESSIBILITY,
                outcome=Outcome.UNKNOWN,
                code="HEARING_LOOP",
                name="Hearing loop",
                required=None,
                venue_value=None,
            ),
            id="accessibility",
        ),
    ],
)
def test_a_list_the_venue_recorded_nothing_in_is_unknown(needs, venue, expected):
    result = judge_suitability(needs, venue)

    assert result.is_suitable is False
    assert result.failures == (expected,)


@pytest.mark.story("11.1", ac=5)
def test_a_requirement_with_no_name_is_judged_and_names_none():
    """An event with "No venue requirements" has no requirement to name, so its needs carry no
    name and neither does the verdict."""
    needs = RequirementNeeds(name=None, people=50)

    result = judge_suitability(needs, _venue(capacity=50))

    assert result.requirement_name is None
    assert result.is_suitable is True


# --- GET /venues/search?event= : the indicator on each result (AC1, AC3, AC5-AC7) -------------
SEARCH_PATH = "/venues/search"


def _tag() -> str:
    """A name part no seed venue has, shared by the venues one test makes and searched for, so
    the seed venues never appear in its results."""
    return f"Suitability {uuid.uuid4().hex[:8]}"


def _assigned_event(db: Session, *, coordinator=Users.COORDINATOR, **overrides) -> Event:
    return make_event(
        db, status=EventStatus.PLANNING, assigned_coordinator_id=coordinator.id, **overrides
    )


def _need_accessibility(db: Session, event_id: uuid.UUID, *codes: str) -> None:
    for code in codes:
        db.execute(
            text(
                "INSERT INTO event_accessibility_needs (event_id, feature_code)"
                " VALUES (:event_id, :code)"
            ),
            {"event_id": event_id, "code": code},
        )
    db.expire_all()


def _search(client, **params) -> dict:
    response = client.get(SEARCH_PATH, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _hits(client, **params) -> dict[str, dict]:
    """The search's results by venue name."""
    return {hit["name"]: hit for hit in _search(client, **params)["venues"]}


def _capacity_failure(required: int, venue_value: int) -> dict:
    return {
        "criterion": "CAPACITY",
        "outcome": "NOT_MET",
        "code": None,
        "name": None,
        "required": required,
        "venue_value": venue_value,
    }


@pytest.mark.story("11.1", ac=1)
@pytest.mark.story("11.1", ac=3)
def test_the_assigned_coordinator_gets_each_result_judged_against_the_requirement(
    coordinator_client, db: Session
):
    tag = _tag()
    event = _assigned_event(db, expected_attendance=120)
    requirement_id = make_venue_requirement(db, event.id, name="Plenary hall", capacity=120)
    make_venue(db, name=f"{tag} small", capacity=80)
    make_venue(db, name=f"{tag} large", capacity=200)

    hits = _hits(coordinator_client, search=tag, event=str(event.id))

    assert hits[f"{tag} small"]["suitability"] == {
        "requirement_id": str(requirement_id),
        "requirement_name": "Plenary hall",
        "is_suitable": False,
        "failures": [_capacity_failure(required=120, venue_value=80)],
    }
    assert hits[f"{tag} large"]["suitability"] == {
        "requirement_id": str(requirement_id),
        "requirement_name": "Plenary hall",
        "is_suitable": True,
        "failures": [],
    }


@pytest.mark.story("11.1", ac=1)
@pytest.mark.parametrize("has_requirement", [True, False], ids=["requirement", "no-requirement"])
def test_people_come_from_the_requirement_else_the_attendance_as_for_the_booking_request(
    coordinator_client, db: Session, has_requirement
):
    """With a requirement, the people to hold are its number (50), not the event's attendance
    (120); with none, the attendance. The booking request carries the same number, from the same
    helper, so the indicator and the request cannot disagree."""
    tag = _tag()
    event = _assigned_event(db, expected_attendance=120, venue_none_required=not has_requirement)
    if has_requirement:
        make_venue_requirement(db, event.id, capacity=50)
    people = 50 if has_requirement else 120
    make_venue(db, name=f"{tag} too small", capacity=40)
    roomy = make_venue(db, name=f"{tag} roomy", capacity=400)

    hits = _hits(coordinator_client, search=tag, event=str(event.id))
    booking = coordinator_client.post(
        "/bookings", json={"event_id": str(event.id), "venue_id": str(roomy.id)}
    )

    assert hits[f"{tag} too small"]["suitability"]["failures"] == [
        _capacity_failure(required=people, venue_value=40)
    ]
    assert hits[f"{tag} roomy"]["suitability"]["is_suitable"] is True
    assert booking.status_code == 201, booking.text
    assert booking.json()["expected_attendance"] == people
    db.expire_all()
    requirement = venue_service.first_venue_requirement(event)
    assert venue_service.people_to_hold(event, requirement) == people


@pytest.mark.story("11.1", ac=1)
def test_only_the_first_requirement_is_judged_until_one_can_be_chosen(
    coordinator_client, db: Session
):
    """The breakout (40) would fit; the plenary (150), first by position, is the one judged. The
    breakout is recorded first, so being first in the table does not make it the one."""
    tag = _tag()
    event = _assigned_event(db, expected_attendance=200)
    make_venue_requirement(db, event.id, position=1, name="Breakout", capacity=40)
    make_venue_requirement(db, event.id, position=0, name="Plenary hall", capacity=150)
    make_venue(db, name=tag, capacity=80)

    suitability = _hits(coordinator_client, search=tag, event=str(event.id))[tag]["suitability"]

    assert suitability["requirement_name"] == "Plenary hall"
    assert suitability["failures"] == [_capacity_failure(required=150, venue_value=80)]


@pytest.mark.story("11.1", ac=1)
def test_failures_come_out_in_reference_order_whatever_order_they_were_recorded(
    coordinator_client, db: Session
):
    """Facilities and accessibility needs come out in the reference lists' own order (Projector
    before Breakout rooms; Wheelchair access before Hearing loop) - not as recorded, and not by
    code, either of which would put each pair the other way round."""
    tag = _tag()
    event = _assigned_event(db, expected_attendance=20)
    make_venue_requirement(
        db,
        event.id,
        capacity=20,
        facilities=(("BREAKOUT_ROOMS", None, None), ("PROJECTOR", None, None)),
    )
    _need_accessibility(db, event.id, "HEARING_LOOP", "WHEELCHAIR_ACCESS")
    make_venue(db, name=tag, capacity=50, facilities=("WIFI",), accessibility=("LIFT_ACCESS",))

    suitability = _hits(coordinator_client, search=tag, event=str(event.id))[tag]["suitability"]

    assert [(failure["criterion"], failure["code"]) for failure in suitability["failures"]] == [
        ("FACILITY", "PROJECTOR"),
        ("FACILITY", "BREAKOUT_ROOMS"),
        ("ACCESSIBILITY", "WHEELCHAIR_ACCESS"),
        ("ACCESSIBILITY", "HEARING_LOOP"),
    ]


@pytest.mark.story("11.1", ac=1)
def test_the_search_judges_the_requirements_layout_and_facility_quantities(
    coordinator_client, db: Session
):
    """The venue holds 400 but only 240 in Banquet, and has 2 projectors: 250 people in Banquet
    with 3 projectors fail on both. Each failure appears only if the search passes the check
    everything it needs - the requirement's layout and quantity, and the venue's layout capacity
    and quantity."""
    tag = _tag()
    event = _assigned_event(db, expected_attendance=250)
    make_venue_requirement(
        db,
        event.id,
        capacity=250,
        layout_code="BANQUET",
        facilities=(("PROJECTOR", 3, None),),
    )
    venue = make_venue(
        db, name=tag, capacity=400, layouts={"BANQUET": 240}, facilities=("PROJECTOR",)
    )
    venue.facilities[0].quantity = 2
    db.flush()

    suitability = _hits(coordinator_client, search=tag, event=str(event.id))[tag]["suitability"]

    assert suitability["failures"] == [
        {
            "criterion": "CAPACITY",
            "outcome": "NOT_MET",
            "code": "BANQUET",
            "name": "Banquet",
            "required": 250,
            "venue_value": 240,
        },
        {
            "criterion": "FACILITY_QUANTITY",
            "outcome": "NOT_MET",
            "code": "PROJECTOR",
            "name": "Projector & screen",
            "required": 3,
            "venue_value": 2,
        },
    ]


@pytest.mark.story("11.1", ac=5)
def test_no_suitability_outside_event_context(coordinator_client, db: Session):
    tag = _tag()
    make_venue(db, name=tag, capacity=10)

    hits = _hits(coordinator_client, search=tag)

    assert [hit.get("suitability", "no such field") for hit in hits.values()] == [None]


@pytest.mark.story("11.1", ac=5)
@pytest.mark.parametrize(
    "venue_none_required", [True, False], ids=["no-venue-requirements", "never-specified"]
)
def test_an_event_without_requirements_is_judged_on_capacity_alone(
    coordinator_client, db: Session, venue_none_required
):
    """No requirement rows, whether marked "No venue requirements" or never specified: only the
    expected attendance is judged - not even the event's accessibility needs, which the venue
    here lacks."""
    tag = _tag()
    event = _assigned_event(db, expected_attendance=100, venue_none_required=venue_none_required)
    _need_accessibility(db, event.id, "HEARING_LOOP")
    make_venue(db, name=f"{tag} fits", capacity=100)
    make_venue(db, name=f"{tag} short", capacity=99, accessibility=("LIFT_ACCESS",))

    hits = _hits(coordinator_client, search=tag, event=str(event.id))

    assert hits[f"{tag} fits"]["suitability"]["is_suitable"] is True
    assert hits[f"{tag} short"]["suitability"]["failures"] == [
        _capacity_failure(required=100, venue_value=99)
    ]


@pytest.mark.story("11.1", ac=5)
def test_a_result_judged_without_a_requirement_names_no_requirement(
    coordinator_client, db: Session
):
    tag = _tag()
    event = _assigned_event(db, expected_attendance=30, venue_none_required=True)
    make_venue(db, name=tag, capacity=400)

    suitability = _hits(coordinator_client, search=tag, event=str(event.id))[tag]["suitability"]

    assert suitability["requirement_id"] is None
    assert suitability["requirement_name"] is None
    assert suitability["is_suitable"] is True


@pytest.mark.story("11.1", ac=6)
@pytest.mark.parametrize(
    "user", [Users.VENUE_STAFF, Users.TECH_SUPPORT], ids=["venue-staff", "tech-support"]
)
def test_other_roles_get_no_suitability_in_event_context(login_as, db: Session, user):
    """Even named as the event's coordinator, a role without bookings:request sees no indicator:
    the permission is checked, not only the assignment."""
    tag = _tag()
    event = _assigned_event(db, coordinator=user, expected_attendance=500)
    make_venue(db, name=tag, capacity=10)

    hits = _hits(login_as(user), search=tag, event=str(event.id))

    assert hits[tag].get("suitability", "no such field") is None


@pytest.mark.story("11.1", ac=6)
def test_a_coordinator_not_assigned_to_the_event_gets_no_suitability(login_as, db: Session):
    tag = _tag()
    event = _assigned_event(db, coordinator=Users.COORDINATOR, expected_attendance=500)
    make_venue(db, name=tag, capacity=10)

    hits = _hits(login_as(Users.COORDINATOR_2), search=tag, event=str(event.id))

    assert hits[tag].get("suitability", "no such field") is None


@pytest.mark.story("11.1", ac=3)
def test_an_unknown_event_is_refused(coordinator_client):
    response = coordinator_client.get(SEARCH_PATH, params={"event": str(uuid.uuid4())})

    assert response.status_code == 422
    assert response.json()["detail"] == venue_service.SEARCH_EVENT_NOT_FOUND_MESSAGE


@pytest.mark.story("11.1", ac=3)
def test_event_context_changes_neither_which_venues_are_found_nor_their_order(
    coordinator_client, db: Session
):
    """With and without the event: the same venues in the same order and the same total, and -
    when nothing matches - the same suggestions of filters to remove. Only the judging differs."""
    tag = _tag()
    event = _assigned_event(db, expected_attendance=60)
    make_venue_requirement(db, event.id, capacity=60)
    for suffix, capacity in (("c", 30), ("a", 300), ("b", 60)):
        make_venue(db, name=f"{tag} {suffix}", capacity=capacity)
    in_context = {"event": str(event.id)}

    for params in ({"search": tag, "capacity": 50}, {"search": tag, "capacity": 1000}):
        plain = _search(coordinator_client, **params)
        judged = _search(coordinator_client, **params, **in_context)
        assert [hit["id"] for hit in judged["venues"]] == [hit["id"] for hit in plain["venues"]]
        assert (judged["total"], judged["relax"]) == (plain["total"], plain["relax"])

    found = _search(coordinator_client, search=tag, capacity=50, **in_context)["venues"]
    assert [hit["name"] for hit in found] == [f"{tag} a", f"{tag} b"]
    assert [hit.get("suitability") is not None for hit in found] == [True, True]
    assert _search(coordinator_client, search=tag, capacity=1000, **in_context)["relax"] != []


@pytest.mark.story("11.1", ac=7)
def test_changed_requirements_change_the_next_searchs_indicator(coordinator_client, db: Session):
    tag = _tag()
    event = _assigned_event(db, expected_attendance=150)
    requirement_id = make_venue_requirement(db, event.id, capacity=60)
    make_venue(db, name=tag, capacity=80)

    before = _hits(coordinator_client, search=tag, event=str(event.id))[tag]["suitability"]
    db.execute(
        text("UPDATE venue_requirements SET capacity = 120 WHERE id = :id"),
        {"id": requirement_id},
    )
    db.expire_all()
    after = _hits(coordinator_client, search=tag, event=str(event.id))[tag]["suitability"]

    assert before["is_suitable"] is True
    assert after["failures"] == [_capacity_failure(required=120, venue_value=80)]


def _draft_without_attendance(db: Session) -> Event:
    """A draft assigned to Chloe with no expected attendance and no venue requirement: there is no
    number of people to judge a venue against. Drafts are not normally assigned, but nothing in
    the schema stops it, and indicators are shown whatever the event's status."""
    return make_event(
        db,
        status=EventStatus.DRAFT,
        assigned_coordinator_id=Users.COORDINATOR.id,
        expected_attendance=None,
    )


@pytest.mark.story("11.1", ac=3)
def test_an_event_with_no_attendance_yet_cannot_be_judged_by_the_search(
    coordinator_client, db: Session
):
    """Refused whether or not any venue matches: the event is checked before any venue is
    judged."""
    tag = _tag()
    event = _draft_without_attendance(db)
    make_venue(db, name=tag, capacity=50)

    matching = coordinator_client.get(SEARCH_PATH, params={"search": tag, "event": str(event.id)})
    matching_none = coordinator_client.get(
        SEARCH_PATH, params={"search": f"{tag} no such venue", "event": str(event.id)}
    )

    for response in (matching, matching_none):
        assert response.status_code == 422
        assert response.json()["detail"] == venue_service.EVENT_NOT_JUDGEABLE_MESSAGE


# --- GET /venues/{id}/suitability?event= : the request step's read (AC2, AC3, AC6) -------------
def _suitability_path(venue_id: uuid.UUID) -> str:
    return f"/venues/{venue_id}/suitability"


@pytest.mark.story("11.1", ac=2)
@pytest.mark.story("11.1", ac=3)
def test_the_request_step_reads_whether_one_venue_suits_the_event(coordinator_client, db: Session):
    event = _assigned_event(db, expected_attendance=120)
    requirement_id = make_venue_requirement(db, event.id, name="Plenary hall", capacity=120)
    small = make_venue(db, capacity=80)
    large = make_venue(db, capacity=200)

    small_read = coordinator_client.get(
        _suitability_path(small.id), params={"event": str(event.id)}
    )
    large_read = coordinator_client.get(
        _suitability_path(large.id), params={"event": str(event.id)}
    )

    assert small_read.status_code == 200, small_read.text
    assert small_read.json() == {
        "requirement_id": str(requirement_id),
        "requirement_name": "Plenary hall",
        "is_suitable": False,
        "failures": [_capacity_failure(required=120, venue_value=80)],
    }
    assert large_read.json()["is_suitable"] is True
    assert large_read.json()["failures"] == []


@pytest.mark.story("11.1", ac=6)
@pytest.mark.parametrize(
    "user",
    [Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ORGANISER],
    ids=["venue-staff", "tech-support", "organiser"],
)
def test_roles_that_cannot_request_a_venue_cannot_read_its_suitability(login_as, db: Session, user):
    """Even named as the event's coordinator, a role without bookings:request is refused: the
    permission is checked, not only the assignment."""
    event = _assigned_event(db, coordinator=user, expected_attendance=50)
    venue = make_venue(db)

    response = login_as(user).get(_suitability_path(venue.id), params={"event": str(event.id)})

    assert response.status_code == 403


@pytest.mark.story("11.1", ac=6)
def test_a_coordinator_not_assigned_to_the_event_cannot_read_its_suitability(login_as, db: Session):
    event = _assigned_event(db, coordinator=Users.COORDINATOR, expected_attendance=50)
    venue = make_venue(db)

    response = login_as(Users.COORDINATOR_2).get(
        _suitability_path(venue.id), params={"event": str(event.id)}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == venue_service.SUITABILITY_NOT_ASSIGNED_MESSAGE


@pytest.mark.story("11.1", ac=6)
def test_signed_out_visitors_cannot_read_a_venues_suitability(client, db: Session):
    event = _assigned_event(db, expected_attendance=50)
    venue = make_venue(db)

    response = client.get(_suitability_path(venue.id), params={"event": str(event.id)})

    assert response.status_code == 401


@pytest.mark.story("11.1", ac=3)
def test_an_unknown_venue_is_not_found_and_an_unknown_event_is_refused(
    coordinator_client, db: Session
):
    """The venue is the resource read (404 when it does not exist); the event is a query value,
    refused as the search refuses it (422)."""
    event = _assigned_event(db, expected_attendance=50)
    venue = make_venue(db)

    unknown_venue = coordinator_client.get(
        _suitability_path(uuid.uuid4()), params={"event": str(event.id)}
    )
    unknown_event = coordinator_client.get(
        _suitability_path(venue.id), params={"event": str(uuid.uuid4())}
    )

    assert unknown_venue.status_code == 404
    assert unknown_event.status_code == 422
    assert unknown_event.json()["detail"] == venue_service.SEARCH_EVENT_NOT_FOUND_MESSAGE


@pytest.mark.story("11.1", ac=3)
def test_an_event_with_no_attendance_yet_cannot_be_judged_by_the_read(
    coordinator_client, db: Session
):
    event = _draft_without_attendance(db)
    venue = make_venue(db, capacity=50)

    response = coordinator_client.get(_suitability_path(venue.id), params={"event": str(event.id)})

    assert response.status_code == 422
    assert response.json()["detail"] == venue_service.EVENT_NOT_JUDGEABLE_MESSAGE


@pytest.mark.story("11.1", ac=3)
def test_the_read_and_the_search_judge_a_venue_the_same_way(coordinator_client, db: Session):
    """The same pair through both: the request step and the catalogue give one answer."""
    tag = _tag()
    event = _assigned_event(db, expected_attendance=250)
    make_venue_requirement(
        db,
        event.id,
        capacity=250,
        layout_code="BANQUET",
        facilities=(("PROJECTOR", 3, None),),
    )
    venue = make_venue(
        db, name=tag, capacity=400, layouts={"BANQUET": 240}, facilities=("PROJECTOR",)
    )
    venue.facilities[0].quantity = 2
    db.flush()

    read = coordinator_client.get(_suitability_path(venue.id), params={"event": str(event.id)})
    searched = _hits(coordinator_client, search=tag, event=str(event.id))[tag]["suitability"]

    assert read.status_code == 200, read.text
    assert read.json() == searched
    assert read.json()["is_suitable"] is False
