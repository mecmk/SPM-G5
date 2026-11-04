"""Story 8.3, fix f8.3.4 - a venue's operating information is required.

AC11 A venue's opening and closing times are required: a venue cannot be created without both, and
     an edit cannot clear them. A venue saved earlier without them keeps them unrecorded until it
     is edited. The server refuses a venue without them.
AC12 Setup and teardown are required whole minutes of 0 or more; a new venue starts with both at 0.
AC13 (the form names each problem under its field) is proven by tests/e2e/venues.spec.ts.

Sign-in and permission refusals are the same endpoints as AC4's, proven in test_venue_records.py.
"""

from __future__ import annotations

import pytest

from tests.support.factories import venue_payload
from tests.support.seed import Venues


# --- AC11: opening hours required ----------------------------------------------------------
@pytest.mark.story("8.3", ac=11)
def test_venue_is_created_with_its_opening_hours(venue_staff_client):
    payload = venue_payload(operating_hours_start="07:30", operating_hours_end="22:00")

    response = venue_staff_client.post("/venues", json=payload)

    assert response.status_code == 201, response.text
    assert response.json()["operating_hours_start"] == "07:30:00"
    assert response.json()["operating_hours_end"] == "22:00:00"


@pytest.mark.story("8.3", ac=11)
@pytest.mark.parametrize(
    "hours",
    [
        {},
        {"operating_hours_start": None, "operating_hours_end": None},
        {"operating_hours_start": "09:00"},
        {"operating_hours_end": "18:00"},
    ],
    ids=["omitted", "null", "only-opens", "only-closes"],
)
def test_venue_without_both_opening_hours_is_refused(venue_staff_client, hours):
    payload = venue_payload()
    del payload["operating_hours_start"], payload["operating_hours_end"]
    payload.update(hours)

    assert venue_staff_client.post("/venues", json=payload).status_code == 422


@pytest.mark.story("8.3", ac=11)
def test_closing_at_the_opening_time_is_refused(venue_staff_client):
    payload = venue_payload(operating_hours_start="09:00", operating_hours_end="09:00")

    assert venue_staff_client.post("/venues", json=payload).status_code == 422


@pytest.mark.story("8.3", ac=11)
def test_an_edit_cannot_clear_the_opening_hours(venue_staff_client):
    response = venue_staff_client.patch(
        f"/venues/{Venues.BOARDROOM}",
        json={"operating_hours_start": None, "operating_hours_end": None},
    )

    assert response.status_code == 422
    after = venue_staff_client.get(f"/venues/{Venues.BOARDROOM}").json()
    assert after["operating_hours_start"] == "08:00:00"


@pytest.mark.story("8.3", ac=11)
def test_a_venue_saved_without_hours_can_still_change_other_details(venue_staff_client):
    response = venue_staff_client.patch(
        f"/venues/{Venues.EXHIBITION_FOYER}", json={"description": "Glass-fronted foyer"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["description"] == "Glass-fronted foyer"
    assert response.json()["operating_hours_start"] is None


# --- AC12: setup and teardown required ---------------------------------------------------
@pytest.mark.story("8.3", ac=12)
def test_setup_and_teardown_start_at_zero(venue_staff_client):
    response = venue_staff_client.post("/venues", json=venue_payload())

    assert response.status_code == 201, response.text
    assert response.json()["setup_minutes_default"] == 0
    assert response.json()["teardown_minutes_default"] == 0


@pytest.mark.story("8.3", ac=12)
@pytest.mark.parametrize("field", ["setup_minutes_default", "teardown_minutes_default"])
def test_setup_and_teardown_cannot_be_cleared(venue_staff_client, field):
    created = venue_staff_client.post("/venues", json=venue_payload(**{field: None}))
    edited = venue_staff_client.patch(f"/venues/{Venues.BOARDROOM}", json={field: None})

    assert created.status_code == 422
    assert edited.status_code == 422


@pytest.mark.story("8.3", ac=12)
@pytest.mark.parametrize("field", ["setup_minutes_default", "teardown_minutes_default"])
@pytest.mark.parametrize("bad", [-1, 1.5, "ten"])
def test_setup_and_teardown_take_whole_minutes_only(venue_staff_client, field, bad):
    assert venue_staff_client.post("/venues", json=venue_payload(**{field: bad})).status_code == 422
