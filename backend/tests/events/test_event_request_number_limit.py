"""Story 2.1 AC21-AC23 (fix f2.1.5) - a number above 100,000 is refused with a message that fits.

AC21 An equipment quantity above 100,000, the largest number a request accepts, is refused on the
     form as more than is available, not as a wrong number: once the dates are chosen it gets AC6's
     "Request no more than is available for these dates.", and before then "Equipment quantity
     must be 100,000 or less." (AC22). It is never told it must be a positive whole number.
AC22 Expected attendance and a facility quantity accept at most 100,000, since no venue holds more
     people; 100,000 itself is accepted. Above it they are refused with a message giving the
     largest number accepted, such as "Expected attendance must be 100,000 or less.", as typed and
     when the server refuses the save, instead of being told they must be positive whole numbers.
AC23 (Permission) The server refuses an expected attendance, a facility quantity or an equipment
     quantity above 100,000, with a message giving the largest number accepted, wherever a
     request's numbers are saved: creating or editing a request, the coordinator's correction
     (7.2) and a change request (19.1, AC4).

What the form says - all of AC21, and AC22 as typed - is tests/e2e/event-request.spec.ts, where the
form stops the save before anything is sent. This file is the server's half: AC22's refused save,
for all three numbers (an equipment quantity too, since the server refuses it before it looks at the
stock), and AC23's other ways in. That 100,000 itself is accepted for attendance and a facility
quantity is 2.1 AC3's test_attendance_accepts_the_boundary_values and
test_facility_quantity_accepts_the_boundary_values, in test_event_request_details.py.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.events.models import Event, EventStatus
from tests.support.factories import (
    create_event_request,
    event_request_payload,
    future_datetime,
    make_event,
)
from tests.support.seed import Events, Users

LARGEST_ACCEPTED = 100_000
# The server's sentences, compared word for word, so a run before the fix shows what it says.
ATTENDANCE_TOO_LARGE = "Expected attendance must be 100,000 or less."
FACILITY_QUANTITY_TOO_LARGE = "A facility quantity must be 100,000 or less."
EQUIPMENT_QUANTITY_TOO_LARGE = "Equipment quantity must be 100,000 or less."
CORRECTION_ROUTE = "/events/{event_id}/review-details"
CHANGE_REQUEST_ROUTE = "/events/{event_id}/change-requests"
_REASON = "The guest list has grown."

TOO_LARGE = [
    pytest.param(LARGEST_ACCEPTED + 1, id="just-above"),
    # The number from the bug report, also above the 2,147,483,647 an INTEGER column holds.
    pytest.param(11_111_111_111, id="beyond-int32"),
]


def _rooms(quantity: int) -> dict:
    """One venue requirement asking for ``quantity`` breakout rooms, otherwise complete: 20 people
    fits every event here, and a submitted request needs the number (story 7.2 AC4)."""
    return {
        "name": "Main venue",
        "capacity": 20,
        "facilities": [{"code": "BREAKOUT_ROOMS", "quantity": quantity}],
    }


def _laptops(quantity: int) -> dict:
    return {"equipment_type_code": "LAPTOP", "quantity": quantity}


# Each number a request records: the fields that carry it, where the server says it is refused (the
# location without "body"), and the sentence it gives.
NUMBERS = [
    pytest.param(
        lambda n: {"expected_attendance": n},
        ("expected_attendance",),
        ATTENDANCE_TOO_LARGE,
        id="attendance",
    ),
    pytest.param(
        lambda n: {"venue_requirements": [_rooms(n)]},
        ("venue_requirements", 0, "facilities", 0, "quantity"),
        FACILITY_QUANTITY_TOO_LARGE,
        id="facility-quantity",
    ),
    pytest.param(
        lambda n: {"equipment": [_laptops(n)]},
        ("equipment", 0, "quantity"),
        EQUIPMENT_QUANTITY_TOO_LARGE,
        id="equipment-quantity",
    ),
]

# What a change request (19.1) proposes for each number: the field it names, and the value.
PROPOSALS = [
    pytest.param("expected_attendance", lambda n: n, ATTENDANCE_TOO_LARGE, id="attendance"),
    pytest.param(
        "venue_requirements",
        lambda n: [_rooms(n)],
        FACILITY_QUANTITY_TOO_LARGE,
        id="facility-quantity",
    ),
    pytest.param(
        "equipment", lambda n: [_laptops(n)], EQUIPMENT_QUANTITY_TOO_LARGE, id="equipment"
    ),
]


def _issues(response) -> list[tuple[tuple, str]]:
    """Each refused field's location, without "body", and the sentence given for it. A refusal that
    names no field, such as "Not enough ... available", is one sentence with no location."""
    detail = response.json()["detail"]
    if isinstance(detail, str):
        return [((), detail)]
    return [(tuple(issue["loc"][1:]), issue["msg"]) for issue in detail]


def _read(client, event_id) -> dict:
    response = client.get(f"/events/{event_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _planning_event(db: Session) -> Event:
    """Olivia's event in Planning, assigned to Chloe: one a change request can be raised on."""
    starts_at = future_datetime(days=60)
    return make_event(
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


# --- AC22: the server refuses a save with the largest number accepted ---------------------------
@pytest.mark.story("2.1", ac=22)
@pytest.mark.parametrize("number", TOO_LARGE)
@pytest.mark.parametrize(("fields", "location", "sentence"), NUMBERS)
def test_a_new_request_with_a_number_above_100000_is_refused_with_the_largest_accepted(
    organiser_client, fields, location, sentence, number
):
    """The request has dates, so an equipment quantity this large is refused by its size before the
    stock is looked at - never as "not enough available", never as a wrong number."""
    response = organiser_client.post("/events", json=event_request_payload(**fields(number)))

    assert response.status_code == 422
    assert _issues(response) == [(location, sentence)]


@pytest.mark.story("2.1", ac=22)
@pytest.mark.parametrize("number", TOO_LARGE)
@pytest.mark.parametrize(("fields", "location", "sentence"), NUMBERS)
def test_an_edit_with_a_number_above_100000_is_refused_and_nothing_is_saved(
    organiser_client, fields, location, sentence, number
):
    draft = create_event_request(organiser_client)

    response = organiser_client.patch(f"/events/{draft['id']}", json=fields(number))

    assert response.status_code == 422
    assert _issues(response) == [(location, sentence)]
    assert _read(organiser_client, draft["id"])["updated_at"] == draft["updated_at"]


# --- AC23: every other way a request's numbers are saved ----------------------------------------
@pytest.mark.story("2.1", ac=23)
@pytest.mark.parametrize("number", TOO_LARGE)
@pytest.mark.parametrize(("fields", "location", "sentence"), NUMBERS)
def test_the_coordinators_correction_refuses_a_number_above_100000(
    coordinator_client, fields, location, sentence, number
):
    """Story 7.2 AC4: the coordinator corrects the request with the organiser's own rules."""
    event = _read(coordinator_client, Events.SUBMITTED)

    response = coordinator_client.patch(
        CORRECTION_ROUTE.format(event_id=event["id"]),
        json={"expected_updated_at": event["updated_at"], **fields(number)},
    )

    assert response.status_code == 422
    assert _issues(response) == [(location, sentence)]
    assert _read(coordinator_client, Events.SUBMITTED)["updated_at"] == event["updated_at"]


@pytest.mark.story("2.1", ac=23)
@pytest.mark.parametrize("number", TOO_LARGE)
@pytest.mark.parametrize(("field", "proposed", "sentence"), PROPOSALS)
def test_a_change_request_proposing_a_number_above_100000_is_refused(
    organiser_client, db: Session, field, proposed, sentence, number
):
    """Story 19.1 AC4: a proposed value follows the rules a request is created with."""
    event = _planning_event(db)

    response = organiser_client.post(
        CHANGE_REQUEST_ROUTE.format(event_id=event.id),
        json={"field": field, "proposed": proposed(number), "reason": _REASON},
    )

    assert response.status_code == 422
    assert [message for _, message in _issues(response)] == [sentence]


@pytest.mark.story("2.1", ac=23)
def test_an_equipment_quantity_of_100000_is_accepted_on_a_draft_without_dates(organiser_client):
    """The largest number accepted is not refused for its size. A draft with no dates yet has no
    stock to be judged against (2.1 AC6), so only the limit applies."""
    draft = create_event_request(
        organiser_client, starts_at=None, ends_at=None, equipment=[_laptops(LARGEST_ACCEPTED)]
    )

    assert draft["equipment"][0]["quantity"] == LARGEST_ACCEPTED
