"""f11.1.1 - each catalogue result judged against the venue requirement selected in the banner.

Story 11.1 AC1 now reads "Suitable or Unsuitable for the venue requirement currently selected
(8.4)". Story 8.4 keeps that selection in the catalogue's address, and the catalogue sends it to
``GET /venues/search`` as ``requirement``, beside ``event``. Without it the search is finding an
additional venue (story 12.5), judged on the event's attendance alone
(``test_venue_suitability.py::test_with_no_requirement_chosen_only_the_attendance_is_judged``).

AC1  With ``requirement``, every result is judged against that requirement - its name and its
     number of people - and the search finds exactly the venues it finds without it.
AC3  A requirement that is not one of the event's is refused, as an event that does not exist is.
AC5  Without ``event`` there is nothing to judge, so ``requirement`` alone changes nothing.
AC6  Only the event's assigned coordinator is judged. For anyone else ``requirement`` is ignored,
     and one that does not exist is not refused either, so the search confirms nothing.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.events.models import Event, EventStatus
from app.venues import service as venue_service
from tests.support.factories import make_event, make_venue, make_venue_requirement
from tests.support.seed import Users

SEARCH_PATH = "/venues/search"


def _tag() -> str:
    """A name part no seed venue has, shared by the venues one test makes and searched for, so
    the seed venues never appear in its results."""
    return f"Requirement {uuid.uuid4().hex[:8]}"


def _assigned_event(db: Session) -> Event:
    return make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=Users.COORDINATOR.id,
        expected_attendance=200,
    )


def _search(client, **params) -> dict:
    response = client.get(SEARCH_PATH, params=params)
    assert response.status_code == 200, response.text
    return response.json()


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
def test_each_result_is_judged_against_the_selected_requirement(coordinator_client, db: Session):
    """The plenary (150) is first, so it is judged by default; the breakout (40) is selected. A
    room for 80 suits the breakout and one for 30 does not, by the breakout's own number."""
    tag = _tag()
    event = _assigned_event(db)
    make_venue_requirement(db, event.id, position=0, name="Plenary hall", capacity=150)
    breakout_id = make_venue_requirement(db, event.id, position=1, name="Breakout", capacity=40)
    make_venue(db, name=f"{tag} small", capacity=30)
    make_venue(db, name=f"{tag} roomy", capacity=80)

    selected = _search(
        coordinator_client, search=tag, event=str(event.id), requirement=str(breakout_id)
    )
    unselected = _search(coordinator_client, search=tag, event=str(event.id))

    hits = {hit["name"]: hit["suitability"] for hit in selected["venues"]}
    assert hits[f"{tag} small"] == {
        "requirement_id": str(breakout_id),
        "requirement_name": "Breakout",
        "is_suitable": False,
        "failures": [_capacity_failure(required=40, venue_value=30)],
    }
    assert hits[f"{tag} roomy"] == {
        "requirement_id": str(breakout_id),
        "requirement_name": "Breakout",
        "is_suitable": True,
        "failures": [],
    }
    # Judging another requirement changes no venue found, their order or the total.
    assert [hit["name"] for hit in selected["venues"]] == [
        hit["name"] for hit in unselected["venues"]
    ]
    assert selected["total"] == unselected["total"]


@pytest.mark.story("11.1", ac=3)
@pytest.mark.parametrize("whose", ["another event's", "none at all"])
def test_a_requirement_that_is_not_the_events_is_refused(coordinator_client, db: Session, whose):
    event = _assigned_event(db)
    make_venue_requirement(db, event.id, name="Plenary hall", capacity=150)
    if whose == "another event's":
        other = _assigned_event(db)
        requirement_id = make_venue_requirement(db, other.id, name="Plenary hall", capacity=150)
    else:
        requirement_id = uuid.uuid4()

    response = coordinator_client.get(
        SEARCH_PATH, params={"event": str(event.id), "requirement": str(requirement_id)}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == venue_service.SEARCH_REQUIREMENT_NOT_FOUND_MESSAGE


@pytest.mark.story("11.1", ac=6)
@pytest.mark.parametrize(
    "user",
    [Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.COORDINATOR_2],
    ids=["venue-staff", "tech-support", "unassigned-coordinator"],
)
def test_anyone_but_the_assigned_coordinator_is_not_judged_or_refused(login_as, db: Session, user):
    """The event is Chloe's. Its real requirement is not judged for anyone else, and one that does
    not exist is not refused, so the search says nothing about which requirements an event has."""
    tag = _tag()
    event = _assigned_event(db)
    requirement_id = make_venue_requirement(db, event.id, name="Plenary hall", capacity=150)
    make_venue(db, name=tag, capacity=10)
    client = login_as(user)

    for requirement in (requirement_id, uuid.uuid4()):
        result = _search(client, search=tag, event=str(event.id), requirement=str(requirement))
        assert [hit["suitability"] for hit in result["venues"]] == [None]


@pytest.mark.story("11.1", ac=5)
def test_a_requirement_without_its_event_judges_and_refuses_nothing(
    coordinator_client, db: Session
):
    tag = _tag()
    event = _assigned_event(db)
    requirement_id = make_venue_requirement(db, event.id, name="Plenary hall", capacity=150)
    make_venue(db, name=tag, capacity=10)

    for requirement in (requirement_id, uuid.uuid4()):
        result = _search(coordinator_client, search=tag, requirement=str(requirement))
        assert [hit["suitability"] for hit in result["venues"]] == [None]
