"""Story 8.3 - fe/be: create and update venue records.

AC1 A venue can be created with, at minimum, a name, location, and capacity.
AC2 Existing venue characteristics can be edited and saved.
AC3 Capacity accepts positive whole numbers only.
AC4 Only Venue Staff can create or edit venue records.

The team meeting of 17 Sep 2026 widened this to full CRUD: Venue Staff can also delete a venue,
as long as no booking refers to it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.venues.service import VENUE_IN_USE_MESSAGE
from tests.support.factories import venue_payload
from tests.support.seed import Users, Venues


# --- AC1: create ---------------------------------------------------------------------------
@pytest.mark.story("8.3", ac=1)
def test_venue_can_be_created_with_minimum_fields(venue_staff_client, db: Session):
    payload = venue_payload(name="Studio 7", location="Tower C, Level 7", capacity=35)

    response = venue_staff_client.post("/venues", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Studio 7"
    assert body["location"] == "Tower C, Level 7"
    assert body["capacity"] == 35
    assert body["status"] == "ACTIVE"
    assert body["created_by_id"] == str(Users.VENUE_STAFF.id)
    # optional characteristics are "not recorded", not invented
    assert body["operating_hours_start"] is None
    assert (
        body["facilities"] == [] and body["layouts"] == [] and body["accessibility_features"] == []
    )
    assert db.execute(text("SELECT count(*) FROM venues WHERE name = 'Studio 7'")).scalar() == 1


@pytest.mark.story("8.3", ac=1)
def test_venue_can_be_created_with_full_characteristics(venue_staff_client):
    payload = venue_payload(
        description="Flexible studio",
        floor_area_sqm="120.50",
        operating_hours_start="08:30",
        operating_hours_end="21:00",
        operating_notes="Closed on public holidays",
        setup_minutes_default=30,
        teardown_minutes_default=15,
        facilities=[{"code": "PROJECTOR", "quantity": 2}, {"code": "WIFI"}],
        layouts=[{"code": "THEATRE"}, {"code": "BANQUET", "layout_capacity": 24}],
        accessibility_features=[{"code": "WHEELCHAIR_ACCESS", "notes": "Via side door"}],
    )

    response = venue_staff_client.post("/venues", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert {f["code"]: f["quantity"] for f in body["facilities"]} == {"PROJECTOR": 2, "WIFI": None}
    assert [lo["code"] for lo in body["layouts"]] == ["BANQUET", "THEATRE"]
    assert body["layouts"][0]["layout_capacity"] == 24
    assert body["accessibility_features"][0]["notes"] == "Via side door"
    assert body["operating_hours_start"] == "08:30:00"


@pytest.mark.story("8.3", ac=1)
@pytest.mark.parametrize("missing", ["name", "location", "capacity"])
def test_minimum_fields_are_mandatory(venue_staff_client, missing):
    payload = venue_payload()
    del payload[missing]
    assert venue_staff_client.post("/venues", json=payload).status_code == 422


@pytest.mark.story("8.3", ac=1)
@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_name_or_location_is_rejected(venue_staff_client, blank):
    assert venue_staff_client.post("/venues", json=venue_payload(name=blank)).status_code == 422
    assert venue_staff_client.post("/venues", json=venue_payload(location=blank)).status_code == 422


@pytest.mark.story("8.3", ac=1)
def test_duplicate_venue_name_is_refused(venue_staff_client):
    response = venue_staff_client.post("/venues", json=venue_payload(name="Grand Hall"))
    assert response.status_code == 409
    assert "Grand Hall" in response.json()["detail"]


@pytest.mark.story("8.3", ac=1)
def test_unknown_characteristic_code_is_refused(venue_staff_client):
    response = venue_staff_client.post(
        "/venues", json=venue_payload(facilities=[{"code": "HOLODECK"}])
    )
    assert response.status_code == 422
    assert "HOLODECK" in response.json()["detail"]


@pytest.mark.story("8.3", ac=1)
def test_operating_hours_must_be_a_valid_pair(venue_staff_client):
    only_start = venue_payload(operating_hours_start="09:00")
    backwards = venue_payload(operating_hours_start="18:00", operating_hours_end="09:00")
    assert venue_staff_client.post("/venues", json=only_start).status_code == 422
    assert venue_staff_client.post("/venues", json=backwards).status_code == 422


# --- AC2: update ---------------------------------------------------------------------------
@pytest.mark.story("8.3", ac=2)
def test_existing_characteristics_can_be_edited_and_saved(venue_staff_client):
    response = venue_staff_client.patch(
        f"/venues/{Venues.BOARDROOM}",
        json={"capacity": 18, "description": "Refurbished", "operating_hours_end": "20:00"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["capacity"] == 18
    assert body["description"] == "Refurbished"
    assert body["operating_hours_end"] == "20:00:00"
    # unchanged fields survive a partial update
    assert body["name"] == "Boardroom 3.4"
    assert body["operating_hours_start"] == "08:00:00"
    # and the change is persisted
    assert venue_staff_client.get(f"/venues/{Venues.BOARDROOM}").json()["capacity"] == 18


@pytest.mark.story("8.3", ac=2)
def test_characteristic_lists_are_replaced_when_supplied(venue_staff_client):
    before = venue_staff_client.get(f"/venues/{Venues.BOARDROOM}").json()
    assert [f["code"] for f in before["facilities"]] == ["VIDEO_CONFERENCING", "WHITEBOARD", "WIFI"]

    response = venue_staff_client.patch(
        f"/venues/{Venues.BOARDROOM}",
        json={"facilities": [{"code": "WIFI"}, {"code": "PROJECTOR", "quantity": 1}]},
    )

    assert response.status_code == 200
    assert [f["code"] for f in response.json()["facilities"]] == ["PROJECTOR", "WIFI"]
    assert [lo["code"] for lo in response.json()["layouts"]] == ["BOARDROOM"], "layouts untouched"


@pytest.mark.story("8.3", ac=2)
def test_update_can_clear_optional_characteristics(venue_staff_client):
    response = venue_staff_client.patch(
        f"/venues/{Venues.BOARDROOM}",
        json={"operating_hours_start": None, "operating_hours_end": None, "facilities": []},
    )
    assert response.status_code == 200
    assert response.json()["operating_hours_start"] is None
    assert response.json()["facilities"] == []


@pytest.mark.story("8.3", ac=2)
def test_update_cannot_leave_operating_hours_half_set(venue_staff_client):
    response = venue_staff_client.patch(
        f"/venues/{Venues.BOARDROOM}", json={"operating_hours_end": None}
    )
    assert response.status_code == 422


@pytest.mark.story("8.3", ac=2)
def test_renaming_to_an_existing_name_is_refused(venue_staff_client):
    response = venue_staff_client.patch(f"/venues/{Venues.BOARDROOM}", json={"name": "Grand Hall"})
    assert response.status_code == 409


@pytest.mark.story("8.3", ac=2)
def test_unknown_fields_are_rejected_rather_than_ignored(venue_staff_client):
    response = venue_staff_client.patch(f"/venues/{Venues.BOARDROOM}", json={"capcity": 99})
    assert response.status_code == 422


@pytest.mark.story("8.3", ac=2)
def test_updating_a_missing_venue_is_404(venue_staff_client):
    response = venue_staff_client.patch(
        "/venues/00000000-0000-0000-0000-000000000000", json={"capacity": 1}
    )
    assert response.status_code == 404


@pytest.mark.story("8.3", ac=2)
def test_update_is_recorded_in_the_audit_log(venue_staff_client, db: Session):
    venue_staff_client.patch(f"/venues/{Venues.BOARDROOM}", json={"capacity": 20})
    row = db.execute(
        text(
            "SELECT actor_id, details FROM audit_log WHERE action = 'VENUE_UPDATED' "
            "AND entity_id = :id ORDER BY occurred_at DESC LIMIT 1"
        ),
        {"id": Venues.BOARDROOM},
    ).one()
    assert row.actor_id == Users.VENUE_STAFF.id
    assert row.details["capacity"] == {"from": 16, "to": 20}


# --- AC3: capacity is a positive whole number ---------------------------------------------
@pytest.mark.story("8.3", ac=3)
@pytest.mark.parametrize("bad_capacity", [0, -1, 12.5, "12", "twelve", None, True])
def test_capacity_rejects_non_positive_or_non_integer_values_on_create(
    venue_staff_client, bad_capacity
):
    response = venue_staff_client.post("/venues", json=venue_payload(capacity=bad_capacity))
    assert response.status_code == 422, response.text


@pytest.mark.story("8.3", ac=3)
@pytest.mark.parametrize("bad_capacity", [0, -5, 3.3, "9"])
def test_capacity_rejects_non_positive_or_non_integer_values_on_update(
    venue_staff_client, bad_capacity
):
    response = venue_staff_client.patch(
        f"/venues/{Venues.BOARDROOM}", json={"capacity": bad_capacity}
    )
    assert response.status_code == 422, response.text


@pytest.mark.story("8.3", ac=3)
def test_capacity_accepts_positive_whole_numbers(venue_staff_client):
    assert venue_staff_client.post("/venues", json=venue_payload(capacity=1)).status_code == 201
    assert (
        venue_staff_client.patch(f"/venues/{Venues.BOARDROOM}", json={"capacity": 500}).status_code
        == 200
    )


# --- AC4: only Venue Staff -----------------------------------------------------------------
@pytest.mark.story("8.3", ac=4)
@pytest.mark.parametrize(
    "user",
    [Users.ORGANISER, Users.COORDINATOR, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda u: u.role,
)
def test_other_roles_cannot_create_or_edit_venues(client, user):
    client.login(user)
    assert client.post("/venues", json=venue_payload()).status_code == 403
    assert client.patch(f"/venues/{Venues.BOARDROOM}", json={"capacity": 1}).status_code == 403


@pytest.mark.story("8.3", ac=4)
def test_venue_staff_can_create_and_edit(venue_staff_client):
    created = venue_staff_client.post("/venues", json=venue_payload())
    assert created.status_code == 201
    edited = venue_staff_client.patch(f"/venues/{created.json()['id']}", json={"location": "Moved"})
    assert edited.status_code == 200 and edited.json()["location"] == "Moved"


@pytest.mark.story("8.3", ac=4)
def test_signed_out_visitors_cannot_create_or_edit_venues(client, db: Session):
    venue_count = db.execute(text("SELECT count(*) FROM venues")).scalar()

    assert client.post("/venues", json=venue_payload()).status_code == 401
    assert client.patch(f"/venues/{Venues.BOARDROOM}", json={"capacity": 1}).status_code == 401

    assert db.execute(text("SELECT count(*) FROM venues")).scalar() == venue_count
    boardroom_capacity = db.execute(
        text("SELECT capacity FROM venues WHERE id = :id"), {"id": Venues.BOARDROOM}
    ).scalar()
    assert boardroom_capacity == 16


# --- delete: Venue Staff have full CRUD (team decision, 17 Sep 2026) ------------------------
@pytest.mark.story("8.3")
def test_venue_staff_can_delete_an_unused_venue(venue_staff_client):
    created = venue_staff_client.post("/venues", json=venue_payload())
    venue_id = created.json()["id"]

    response = venue_staff_client.delete(f"/venues/{venue_id}")

    assert response.status_code == 204, response.text
    assert venue_staff_client.get(f"/venues/{venue_id}").status_code == 404


@pytest.mark.story("8.3")
def test_deleting_a_venue_removes_its_characteristics(venue_staff_client, db: Session):
    response = venue_staff_client.delete(f"/venues/{Venues.BOARDROOM}")

    assert response.status_code == 204, response.text
    for table in ("venue_facilities", "venue_layouts", "venue_accessibility_features"):
        remaining = db.execute(
            text(f"SELECT count(*) FROM {table} WHERE venue_id = :id"), {"id": Venues.BOARDROOM}
        ).scalar()
        assert remaining == 0, table


@pytest.mark.story("8.3")
def test_venue_with_bookings_cannot_be_deleted(venue_staff_client, db: Session):
    response = venue_staff_client.delete(f"/venues/{Venues.GRAND_HALL}")

    assert response.status_code == 409
    assert response.json() == {"detail": VENUE_IN_USE_MESSAGE}
    still_there = db.execute(
        text("SELECT count(*) FROM venues WHERE id = :id"), {"id": Venues.GRAND_HALL}
    ).scalar()
    assert still_there == 1


@pytest.mark.story("8.3")
def test_deleting_a_missing_venue_is_404(venue_staff_client):
    response = venue_staff_client.delete("/venues/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.story("8.3", ac=4)
@pytest.mark.parametrize(
    "user",
    [Users.ORGANISER, Users.COORDINATOR, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda u: u.role,
)
def test_other_roles_cannot_delete_venues(client, db: Session, user):
    client.login(user)

    assert client.delete(f"/venues/{Venues.BOARDROOM}").status_code == 403
    still_there = db.execute(
        text("SELECT count(*) FROM venues WHERE id = :id"), {"id": Venues.BOARDROOM}
    ).scalar()
    assert still_there == 1


@pytest.mark.story("8.3", ac=4)
def test_signed_out_visitors_cannot_delete_venues(client):
    assert client.delete(f"/venues/{Venues.BOARDROOM}").status_code == 401


@pytest.mark.story("8.3")
def test_delete_is_recorded_in_the_audit_log(venue_staff_client, db: Session):
    venue_staff_client.delete(f"/venues/{Venues.BOARDROOM}")
    row = db.execute(
        text(
            "SELECT actor_id, details FROM audit_log WHERE action = 'VENUE_DELETED' "
            "AND entity_id = :id"
        ),
        {"id": Venues.BOARDROOM},
    ).one()
    assert row.actor_id == Users.VENUE_STAFF.id
    assert row.details == {"name": "Boardroom 3.4"}


# --- read side, used by stories 8.1 / 8.2 ---------------------------------------------------
@pytest.mark.story("8.3")
@pytest.mark.story("8.1", ac=3)
def test_list_hides_withdrawn_venues_unless_asked(coordinator_client):
    names = [v["name"] for v in coordinator_client.get("/venues").json()]
    assert "Old Annex Room" not in names and "Grand Hall" in names

    with_withdrawn = coordinator_client.get("/venues", params={"include_withdrawn": "true"}).json()
    assert any(v["name"] == "Old Annex Room" and v["status"] == "WITHDRAWN" for v in with_withdrawn)


@pytest.mark.story("8.3")
@pytest.mark.story("8.2", ac=1)
def test_full_record_includes_all_characteristics(coordinator_client):
    body = coordinator_client.get(f"/venues/{Venues.GRAND_HALL}").json()
    assert body["capacity"] == 400
    assert {f["code"] for f in body["facilities"]} >= {"PROJECTOR", "SOUND_SYSTEM", "STAGE"}
    assert {lo["code"] for lo in body["layouts"]} >= {"THEATRE", "BANQUET"}
    assert {a["code"] for a in body["accessibility_features"]} >= {
        "WHEELCHAIR_ACCESS",
        "HEARING_LOOP",
    }
    assert body["operating_hours_start"] == "08:00:00"


@pytest.mark.story("8.3")
def test_reference_data_lists_pick_list_values(venue_staff_client):
    body = venue_staff_client.get("/venues/reference-data").json()
    assert {f["code"] for f in body["facilities"]} >= {"PROJECTOR", "WIFI"}
    assert {lo["code"] for lo in body["layouts"]} >= {"THEATRE", "BOARDROOM"}
    assert {a["code"] for a in body["accessibility_features"]} >= {"WHEELCHAIR_ACCESS"}
