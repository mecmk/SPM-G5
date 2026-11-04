"""Story 2.7 AC21-AC22 (fix f2.7.5) - only countable facilities take a quantity.

AC21 Projector & screen and Whiteboard / flipchart are counted: once ticked on a venue requirement,
     how many is needed must be given before the request is submitted (a draft may leave it blank,
     as AC8 allows). A venue requirements change (19.1) does not ask for it: its form does not
     edit facilities, so one recorded before the fix without a quantity is carried as it is.
AC22 Every other facility is either needed or not, so it takes no quantity, on a draft or not.
     Breakout rooms are no longer a facility: a breakout room is a venue requirement of its own.

What the form does - "How many" shown only beside a counted facility, and a submission with one
left blank stopped before anything is sent - is tests/e2e/event-request.spec.ts. A quantity of 1
being the smallest accepted, and 100,000 the largest, is 2.1's (fix f2.1.5), unchanged.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.events.models import EventStatus
from tests.support.factories import (
    create_event_request,
    create_submittable_event_request,
    event_request_payload,
    future_datetime,
    make_event,
    make_venue_requirement,
    submittable_event_request_payload,
)
from tests.support.seed import Users

# The server's sentences, compared word for word, so a run before the fix shows what it says
# instead.
_SUBMISSION_NEEDS_A_PROJECTOR_COUNT = (
    "Add the following before submitting: venue requirement 1: how many Projector & screen."
)
_WIFI_TAKES_NO_QUANTITY = "Main venue: Wi-Fi is either needed or not, so it takes no quantity."

_COUNTED = {"PROJECTOR", "WHITEBOARD"}


# --- helpers -----------------------------------------------------------------------------------
def _requirement(*facilities: dict) -> dict:
    """One complete venue requirement - a name and a number of people - with ``facilities``."""
    return {"name": "Main venue", "capacity": 40, "facilities": list(facilities)}


def _submit(client, event_id):
    return client.post(f"/events/{event_id}/submit")


def _issue_locations(response) -> list[list]:
    return [issue["loc"] for issue in response.json()["detail"]]


def _issue_messages(response) -> list[str]:
    return [issue["msg"] for issue in response.json()["detail"]]


# --- AC21 / AC22: the reference data says which facilities are counted ---------------------------
@pytest.mark.story("2.7", ac=21)
def test_the_form_is_told_which_facilities_are_counted(organiser_client):
    response = organiser_client.get("/events/reference-data")

    assert response.status_code == 200, response.text
    facilities = response.json()["facilities"]
    assert {f["code"] for f in facilities if f["is_countable"]} == _COUNTED
    assert all(f["is_countable"] is False for f in facilities if f["code"] not in _COUNTED)


@pytest.mark.story("2.7", ac=22)
def test_breakout_rooms_are_no_longer_a_facility(organiser_client):
    response = organiser_client.get("/events/reference-data")

    assert "BREAKOUT_ROOMS" not in {f["code"] for f in response.json()["facilities"]}


# --- AC21: a counted facility needs a quantity to submit -----------------------------------------
@pytest.mark.story("2.7", ac=21)
def test_a_request_with_counted_and_tick_only_facilities_can_be_submitted(organiser_client):
    created = create_submittable_event_request(
        organiser_client,
        venue_requirements=[
            _requirement({"code": "PROJECTOR", "quantity": 2}, {"code": "WIFI"}),
        ],
    )

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 200, response.text
    facilities = response.json()["venue_requirements"][0]["facilities"]
    assert {(f["code"], f["quantity"]) for f in facilities} == {("PROJECTOR", 2), ("WIFI", None)}


@pytest.mark.story("2.7", ac=21)
def test_a_draft_may_leave_a_counted_facility_without_a_quantity(organiser_client):
    created = create_event_request(
        organiser_client, venue_requirements=[_requirement({"code": "PROJECTOR"})]
    )

    assert created["venue_requirements"][0]["facilities"][0]["quantity"] is None


@pytest.mark.story("2.7", ac=21)
def test_a_counted_facility_without_a_quantity_cannot_be_submitted(organiser_client):
    created = create_submittable_event_request(
        organiser_client, venue_requirements=[_requirement({"code": "PROJECTOR"})]
    )

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _SUBMISSION_NEEDS_A_PROJECTOR_COUNT


# --- AC22: a tick-only facility takes no quantity -----------------------------------------------
@pytest.mark.story("2.7", ac=22)
@pytest.mark.parametrize("build", [event_request_payload, submittable_event_request_payload])
def test_a_tick_only_facility_with_a_quantity_is_refused(organiser_client, build):
    """Refused on a draft as well as on a request ready to submit: it is never a number."""
    payload = build(venue_requirements=[_requirement({"code": "WIFI", "quantity": 3})])

    response = organiser_client.post("/events", json=payload)

    assert response.status_code == 422, response.text
    assert _issue_messages(response) == [_WIFI_TAKES_NO_QUANTITY]
    assert _issue_locations(response) == [["body", "venue_requirements", 0, "facilities"]]


@pytest.mark.story("2.7", ac=22)
def test_an_edit_giving_a_tick_only_facility_a_quantity_is_refused(organiser_client):
    created = create_event_request(organiser_client, venue_requirements=[_requirement()])

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={"venue_requirements": [_requirement({"code": "STAGE", "quantity": 1})]},
    )

    assert response.status_code == 422, response.text
    assert _issue_messages(response) == [
        "Main venue: Stage is either needed or not, so it takes no quantity."
    ]


# --- AC21 / AC22: a venue requirements change (19.1) ---------------------------------------------
def _planning_event_with_hall(db: Session):
    starts_at = future_datetime(days=60)
    event = make_event(
        db,
        status=EventStatus.PLANNING,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=8),
        expected_attendance=100,
        assigned_coordinator_id=Users.COORDINATOR.id,
        contact_name="Olivia Organiser",
        contact_email="olivia.events@acme.example",
        contact_phone="+65 6111 2233",
    )
    hall_id = make_venue_requirement(db, event.id, name="Hall", capacity=80)
    db.commit()
    return event, hall_id


def _hall(event, hall_id, *facilities: dict) -> dict:
    return {
        "id": str(hall_id),
        "name": "Hall",
        "capacity": 80,
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat(),
        "layout_code": None,
        "facilities": list(facilities),
        "notes": None,
    }


def _raise_requirements(client, event, *requirements: dict):
    return client.post(
        f"/events/{event.id}/change-requests",
        json={
            "field": "venue_requirements",
            "proposed": list(requirements),
            "reason": "The workshop needs more.",
        },
    )


@pytest.mark.story("2.7", ac=21)
def test_a_change_carrying_a_counted_facility_without_a_quantity_is_raised(
    organiser_client, db: Session
):
    """The change form does not edit facilities, so a whiteboard recorded before the fix without a
    quantity does not stop a change to the requirement's size."""
    event, hall_id = _planning_event_with_hall(db)

    response = _raise_requirements(
        organiser_client, event, {**_hall(event, hall_id, {"code": "WHITEBOARD"}), "capacity": 90}
    )

    assert response.status_code == 201, response.text


@pytest.mark.story("2.7", ac=21)
def test_a_change_with_a_counted_quantity_and_a_tick_only_facility_is_raised(
    organiser_client, db: Session
):
    event, hall_id = _planning_event_with_hall(db)

    response = _raise_requirements(
        organiser_client,
        event,
        _hall(event, hall_id, {"code": "WHITEBOARD", "quantity": 4}, {"code": "WIFI"}),
    )

    assert response.status_code == 201, response.text


@pytest.mark.story("2.7", ac=22)
def test_a_change_giving_a_tick_only_facility_a_quantity_is_refused(organiser_client, db: Session):
    event, hall_id = _planning_event_with_hall(db)

    response = _raise_requirements(
        organiser_client, event, _hall(event, hall_id, {"code": "WIFI", "quantity": 2})
    )

    assert response.status_code == 422, response.text
    assert _issue_messages(response) == [
        "Hall: Wi-Fi is either needed or not, so it takes no quantity."
    ]
