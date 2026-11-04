"""Story 8.3 AC11-AC12 (fix f2.7.5) - only countable facilities take a quantity on a venue record.

AC11 Projector & screen and Whiteboard / flipchart are counted: a venue that has one must say how
     many it has.
AC12 Every other facility is either there or not, so it takes no quantity.

What the venue form does - "How many" shown only beside a counted facility, and a save with one
left blank stopped before anything is sent - is tests/e2e/venues.spec.ts.
"""

from __future__ import annotations

import pytest

from tests.support.factories import venue_payload
from tests.support.seed import Venues

# The server's sentences, compared word for word, so a run before the fix shows what it says
# instead.
_NEEDS_A_PROJECTOR_COUNT = "Enter how many Projector & screen the venue has."
_WIFI_TAKES_NO_QUANTITY = "Wi-Fi is either there or not, so it takes no quantity."

_COUNTED = {"PROJECTOR", "WHITEBOARD"}


@pytest.mark.story("8.3", ac=11)
def test_the_venue_form_is_told_which_facilities_are_counted(venue_staff_client):
    response = venue_staff_client.get("/venues/reference-data")

    assert response.status_code == 200, response.text
    facilities = response.json()["facilities"]
    assert {f["code"] for f in facilities if f["is_countable"]} == _COUNTED
    assert all(f["is_countable"] is False for f in facilities if f["code"] not in _COUNTED)


@pytest.mark.story("8.3", ac=11)
def test_a_venue_with_counted_and_tick_only_facilities_is_saved(venue_staff_client):
    payload = venue_payload(
        facilities=[{"code": "WHITEBOARD", "quantity": 1}, {"code": "WIFI"}, {"code": "STAGE"}]
    )

    response = venue_staff_client.post("/venues", json=payload)

    assert response.status_code == 201, response.text
    assert {(f["code"], f["quantity"]) for f in response.json()["facilities"]} == {
        ("WHITEBOARD", 1),
        ("WIFI", None),
        ("STAGE", None),
    }


@pytest.mark.story("8.3", ac=11)
def test_a_new_venue_with_a_counted_facility_needs_a_quantity(venue_staff_client):
    response = venue_staff_client.post(
        "/venues", json=venue_payload(facilities=[{"code": "PROJECTOR"}])
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _NEEDS_A_PROJECTOR_COUNT


@pytest.mark.story("8.3", ac=11)
def test_an_edit_leaving_a_counted_facility_without_a_quantity_is_refused(venue_staff_client):
    response = venue_staff_client.patch(
        f"/venues/{Venues.EXHIBITION_FOYER}", json={"facilities": [{"code": "PROJECTOR"}]}
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _NEEDS_A_PROJECTOR_COUNT


@pytest.mark.story("8.3", ac=12)
@pytest.mark.parametrize("method", ["post", "patch"])
def test_a_tick_only_facility_with_a_quantity_is_refused(venue_staff_client, method):
    facilities = [{"code": "WIFI", "quantity": 2}]
    if method == "post":
        response = venue_staff_client.post("/venues", json=venue_payload(facilities=facilities))
    else:
        response = venue_staff_client.patch(
            f"/venues/{Venues.EXHIBITION_FOYER}", json={"facilities": facilities}
        )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _WIFI_TAKES_NO_QUANTITY
