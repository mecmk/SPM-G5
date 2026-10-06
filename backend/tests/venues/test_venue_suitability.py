"""Story 11.1 - venue suitability with reasons and override: the suitability check itself.

``judge_suitability`` judges ONE venue requirement against ONE venue's recorded characteristics.
It is pure - the catalogue search and the booking request will both call it with plain values -
so these tests need no database.

AC1  Suitable or Unsuitable for one requirement, based only on that requirement and the venue's
     recorded characteristics. Each failed criterion carries the requirement's value and the
     venue's (e.g. "Capacity 80 < 120 people").
AC4  Capacity equal to the number of people counts as suitable; one less does not. A required
     facility quantity of 3 is met by 3 and not by 2.
AC5  A characteristic the venue has not recorded is Unknown and never treated as met. An event
     with "No venue requirements" is judged on capacity only.

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

import pytest

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
