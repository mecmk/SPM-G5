"""Story 8.3, fix f8.3.4 - a venue's operating information is required.

AC13 A venue's opening and closing times are required: a venue cannot be created without both, and
     an edit cannot clear them. A venue saved earlier without them keeps them unrecorded until it
     is edited. The server refuses a venue without them.
AC14 Setup and teardown are required whole minutes from 0 to 14 days; a new venue starts with both
     at 0.
AC15 (the form names each problem under its field) is proven by tests/e2e/venues.spec.ts.

Sign-in and permission refusals are the same endpoints as AC4's, proven in test_venue_records.py.
"""

from __future__ import annotations

import pytest

from tests.support.factories import venue_payload
from tests.support.seed import Venues

# AC14: the longest setup or teardown, as for a booking's own (12.1 AC5).
FOURTEEN_DAYS = 14 * 24 * 60
START, END = "operating_hours_start", "operating_hours_end"
# AC13/AC14 (fix f8.3.5): what an edit sending one of these fields empty is told.
CANNOT_CLEAR = {
    START: "You cannot clear the venue's opening time.",
    END: "You cannot clear the venue's closing time.",
    "setup_minutes_default": "You cannot clear the venue's setup time.",
    "teardown_minutes_default": "You cannot clear the venue's teardown time.",
}


def refused_fields(response) -> set[str]:
    """The body fields a 422 names, so a test pins why the request was refused."""
    assert response.status_code == 422, response.text
    return {problem["loc"][1] for problem in response.json()["detail"]}


def refusal_messages(response) -> dict[str, str]:
    """Each refused body field with the sentence it was refused with."""
    assert response.status_code == 422, response.text
    return {problem["loc"][1]: problem["msg"] for problem in response.json()["detail"]}


# --- AC13: opening hours required ----------------------------------------------------------
@pytest.mark.story("8.3", ac=13)
def test_venue_is_created_with_its_opening_hours(venue_staff_client):
    payload = venue_payload(operating_hours_start="07:30", operating_hours_end="22:00")

    response = venue_staff_client.post("/venues", json=payload)

    assert response.status_code == 201, response.text
    assert response.json()["operating_hours_start"] == "07:30:00"
    assert response.json()["operating_hours_end"] == "22:00:00"


@pytest.mark.story("8.3", ac=13)
@pytest.mark.parametrize(
    ("hours", "refused"),
    [
        ({}, {START, END}),
        ({START: None, END: None}, {START, END}),
        ({START: "09:00"}, {END}),
        ({END: "18:00"}, {START}),
    ],
    ids=["omitted", "null", "only-opens", "only-closes"],
)
def test_venue_without_both_opening_hours_is_refused(venue_staff_client, hours, refused):
    payload = venue_payload()
    del payload[START], payload[END]
    payload.update(hours)

    assert refused_fields(venue_staff_client.post("/venues", json=payload)) == refused


@pytest.mark.story("8.3", ac=13)
def test_closing_at_the_opening_time_is_refused(venue_staff_client):
    payload = venue_payload(operating_hours_start="09:00", operating_hours_end="09:00")

    response = venue_staff_client.post("/venues", json=payload)

    assert response.status_code == 422
    assert "must be after" in response.json()["detail"][0]["msg"]


@pytest.mark.story("8.3", ac=13)
def test_an_edit_cannot_clear_the_opening_hours(venue_staff_client):
    response = venue_staff_client.patch(
        f"/venues/{Venues.BOARDROOM}",
        json={START: None, END: None},
    )

    assert refusal_messages(response) == {START: CANNOT_CLEAR[START], END: CANNOT_CLEAR[END]}
    after = venue_staff_client.get(f"/venues/{Venues.BOARDROOM}").json()
    assert after["operating_hours_start"] == "08:00:00"


@pytest.mark.story("8.3", ac=13)
def test_a_venue_saved_without_hours_can_still_change_other_details(venue_staff_client):
    response = venue_staff_client.patch(
        f"/venues/{Venues.EXHIBITION_FOYER}", json={"description": "Glass-fronted foyer"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["description"] == "Glass-fronted foyer"
    assert response.json()["operating_hours_start"] is None


# --- AC14: setup and teardown required ---------------------------------------------------
@pytest.mark.story("8.3", ac=14)
def test_setup_and_teardown_start_at_zero(venue_staff_client):
    response = venue_staff_client.post("/venues", json=venue_payload())

    assert response.status_code == 201, response.text
    assert response.json()["setup_minutes_default"] == 0
    assert response.json()["teardown_minutes_default"] == 0


@pytest.mark.story("8.3", ac=14)
@pytest.mark.parametrize("field", ["setup_minutes_default", "teardown_minutes_default"])
def test_setup_and_teardown_cannot_be_cleared(venue_staff_client, field):
    created = venue_staff_client.post("/venues", json=venue_payload(**{field: None}))
    edited = venue_staff_client.patch(f"/venues/{Venues.BOARDROOM}", json={field: None})

    assert refused_fields(created) == {field}
    assert refusal_messages(edited) == {field: CANNOT_CLEAR[field]}


@pytest.mark.story("8.3", ac=14)
@pytest.mark.parametrize("field", ["setup_minutes_default", "teardown_minutes_default"])
@pytest.mark.parametrize("bad", [-1, 1.5, "ten"])
def test_setup_and_teardown_take_whole_minutes_only(venue_staff_client, field, bad):
    created = venue_staff_client.post("/venues", json=venue_payload(**{field: bad}))
    edited = venue_staff_client.patch(f"/venues/{Venues.BOARDROOM}", json={field: bad})

    assert refused_fields(created) == {field}
    assert refused_fields(edited) == {field}


@pytest.mark.story("8.3", ac=14)
@pytest.mark.parametrize("field", ["setup_minutes_default", "teardown_minutes_default"])
def test_setup_and_teardown_are_at_most_fourteen_days(venue_staff_client, field):
    created = venue_staff_client.post("/venues", json=venue_payload(**{field: FOURTEEN_DAYS}))
    edited = venue_staff_client.patch(f"/venues/{Venues.BOARDROOM}", json={field: FOURTEEN_DAYS})

    assert created.status_code == 201, created.text
    assert created.json()[field] == FOURTEEN_DAYS
    assert edited.status_code == 200, edited.text


@pytest.mark.story("8.3", ac=14)
@pytest.mark.parametrize("field", ["setup_minutes_default", "teardown_minutes_default"])
@pytest.mark.parametrize("too_long", [FOURTEEN_DAYS + 1, 2**31])
def test_setup_and_teardown_over_fourteen_days_are_refused(venue_staff_client, field, too_long):
    created = venue_staff_client.post("/venues", json=venue_payload(**{field: too_long}))
    edited = venue_staff_client.patch(f"/venues/{Venues.BOARDROOM}", json={field: too_long})

    assert refused_fields(created) == {field}
    assert refused_fields(edited) == {field}
