"""Story 2.1 - fe/be: capture event details, requirements and equipment on a request (AC1-AC8).

AC1 The organiser can record the event name, purpose, description, proposed date and time, and
    expected attendance.
AC2 The proposed end must be after the start, and a date in the past is rejected with an
    explanatory message.
AC3 Expected attendance, equipment quantities and facility quantities accept positive whole
    numbers only.
AC4 Venue requirements (room layout, facilities with a quantity, other requirements) can be
    recorded, or marked "no venue requirements", which is stored distinguishably from left empty.
AC5 Accessibility needs can be selected or described, or marked "none required"; leaving them
    empty is stored distinguishably from "none required" (a draft may stay unanswered; a
    submitted request may not, AC10).
AC6 Multiple equipment items can be added, each with a type and quantity.
AC7 Any recorded detail, requirement or equipment item can be edited or removed before the
    request is submitted.
AC8 All recorded details, requirements and equipment items are visible to the reviewing Event
    Coordinator.

Submission (AC9-AC12) is in test_event_request_submission.py. "Capacity" in AC4 is the expected
attendance of AC1: there is no separate capacity column, and the venue is matched against it
(story 11.1). A "preferred location" was dropped from the request on 20 Sep 2026 as too broad.
Equipment availability is not checked here (stories 15.x / 16.x).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.common.audit import AuditLog
from tests.support.factories import (
    create_event_request,
    create_submittable_event_request,
    event_request_payload,
    future_datetime,
)
from tests.support.seed import Events, Users

INT32_MAX = 2_147_483_647
NOT_WHOLE_POSITIVE = [
    pytest.param(0, id="zero"),
    pytest.param(-5, id="negative"),
    pytest.param(1.5, id="fraction"),
    pytest.param("20", id="string"),
    pytest.param(True, id="boolean"),
    pytest.param(INT32_MAX + 1, id="beyond-int32"),
]
NON_ORGANISERS = [
    pytest.param(Users.COORDINATOR, id="coordinator"),
    pytest.param(Users.VENUE_STAFF, id="venue-staff"),
    pytest.param(Users.TECH_SUPPORT, id="tech-support"),
    pytest.param(Users.ATTENDEE, id="attendee"),
]


def _detail(response) -> str:
    """The whole error body, lower-cased, so tests assert on wording without pinning the shape."""
    return response.text.lower()


def _equipment(code: str, quantity: int = 1, **extra) -> dict:
    return {"equipment_type_code": code, "quantity": quantity, **extra}


def _ids(items: list[dict]) -> dict[str, str]:
    return {item["equipment_type_code"]: item["id"] for item in items}


# --- AC1: record the details -----------------------------------------------------------------
@pytest.mark.story("2.1", ac=1)
def test_organiser_records_name_purpose_description_dates_and_attendance(
    organiser_client, db: Session
):
    payload = event_request_payload(name="Data Literacy Day", expected_attendance=60)

    response = organiser_client.post("/events", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Data Literacy Day"
    assert body["purpose"] == payload["purpose"]
    assert body["description"] == payload["description"]
    assert body["expected_attendance"] == 60
    assert datetime.fromisoformat(body["starts_at"]) == datetime.fromisoformat(payload["starts_at"])
    assert datetime.fromisoformat(body["ends_at"]) == datetime.fromisoformat(payload["ends_at"])
    assert body["status"] == "DRAFT"
    assert body["submitted_at"] is None
    assert body["organiser_id"] == str(Users.ORGANISER.id)
    # what was saved is what comes back on a later read
    assert organiser_client.get(f"/events/{body['id']}").json() == body


@pytest.mark.story("2.1", ac=1)
def test_a_name_alone_is_enough_for_a_draft(organiser_client):
    response = organiser_client.post("/events", json={"name": "Just a name"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["purpose"] is None and body["starts_at"] is None
    assert body["expected_attendance"] is None


@pytest.mark.story("2.1", ac=1)
@pytest.mark.parametrize("name", [None, "", "   "], ids=["missing", "empty", "blank"])
def test_the_event_name_is_mandatory(organiser_client, name):
    payload = event_request_payload()
    if name is None:
        del payload["name"]
    else:
        payload["name"] = name

    assert organiser_client.post("/events", json=payload).status_code == 422


@pytest.mark.story("2.1", ac=1)
@pytest.mark.parametrize(
    "field, value",
    [
        ("status", "APPROVED"),
        ("organiser_id", str(Users.ORGANISER_2.id)),
        ("organisation_id", str(uuid.uuid4())),
        ("submitted_at", "2026-01-01T00:00:00+00:00"),
        ("assigned_coordinator_id", str(Users.COORDINATOR.id)),
    ],
)
def test_the_client_cannot_set_server_controlled_fields(organiser_client, field, value):
    response = organiser_client.post("/events", json=event_request_payload(**{field: value}))

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=1)
def test_the_request_belongs_to_the_organiser_and_their_organisation(organiser_client, db: Session):
    created = create_event_request(organiser_client)

    row = db.execute(
        text("SELECT organiser_id, organisation_id FROM events WHERE id = :id"),
        {"id": created["id"]},
    ).one()
    organisation = db.execute(
        text("SELECT organisation_id FROM users WHERE id = :id"), {"id": Users.ORGANISER.id}
    ).scalar()
    assert row.organiser_id == Users.ORGANISER.id
    assert row.organisation_id == organisation is not None


@pytest.mark.story("2.1", ac=1)
@pytest.mark.parametrize("user", NON_ORGANISERS)
def test_only_an_organiser_can_create_a_request(login_as, user):
    response = login_as(user).post("/events", json=event_request_payload())

    assert response.status_code == 403


@pytest.mark.story("2.1", ac=1)
def test_creating_a_request_requires_sign_in(client):
    assert client.post("/events", json=event_request_payload()).status_code == 401


@pytest.mark.story("2.1", ac=1)
def test_creation_is_written_to_the_status_history_and_audit_log(organiser_client, db: Session):
    created = create_event_request(organiser_client)

    history = db.execute(
        text(
            "SELECT from_status, to_status, changed_by_id FROM event_status_history"
            " WHERE event_id = :id"
        ),
        {"id": created["id"]},
    ).all()
    assert [tuple(row) for row in history] == [(None, "DRAFT", Users.ORGANISER.id)]
    audit = db.scalars(select(AuditLog).where(AuditLog.entity_id == uuid.UUID(created["id"]))).all()
    assert [(a.action, a.entity_type, a.actor_id) for a in audit] == [
        ("EVENT_CREATED", "event", Users.ORGANISER.id)
    ]


# --- AC2: end after start, no dates in the past ------------------------------------------------
@pytest.mark.story("2.1", ac=2)
@pytest.mark.parametrize(
    "end_offset_minutes", [0, -1, -600], ids=["equal", "one-minute", "earlier"]
)
def test_end_must_be_after_start(organiser_client, end_offset_minutes):
    start = future_datetime(days=10)
    payload = event_request_payload(
        starts_at=start.isoformat(),
        ends_at=(start + timedelta(minutes=end_offset_minutes)).isoformat(),
    )

    response = organiser_client.post("/events", json=payload)

    assert response.status_code == 422
    assert "after the start" in _detail(response)


@pytest.mark.story("2.1", ac=2)
def test_an_end_one_minute_after_the_start_is_accepted(organiser_client):
    start = future_datetime(days=10)
    payload = event_request_payload(
        starts_at=start.isoformat(), ends_at=(start + timedelta(minutes=1)).isoformat()
    )

    assert organiser_client.post("/events", json=payload).status_code == 201


@pytest.mark.story("2.1", ac=2)
def test_a_start_in_the_past_is_rejected_with_an_explanation(organiser_client):
    start = datetime.now(UTC) - timedelta(seconds=1)
    payload = event_request_payload(
        starts_at=start.isoformat(), ends_at=(start + timedelta(hours=2)).isoformat()
    )

    response = organiser_client.post("/events", json=payload)

    assert response.status_code == 422
    assert "in the past" in _detail(response)


@pytest.mark.story("2.1", ac=2)
def test_a_start_just_in_the_future_is_accepted(organiser_client):
    start = datetime.now(UTC) + timedelta(minutes=1)
    payload = event_request_payload(
        starts_at=start.isoformat(), ends_at=(start + timedelta(hours=2)).isoformat()
    )

    assert organiser_client.post("/events", json=payload).status_code == 201


@pytest.mark.story("2.1", ac=2)
def test_a_past_end_on_its_own_is_rejected(organiser_client):
    payload = event_request_payload(starts_at=None)
    payload["ends_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()

    response = organiser_client.post("/events", json=payload)

    assert response.status_code == 422
    assert "in the past" in _detail(response)


@pytest.mark.story("2.1", ac=2)
def test_a_time_without_a_timezone_is_rejected(organiser_client):
    start = future_datetime(days=10).replace(tzinfo=None)
    payload = event_request_payload(
        starts_at=start.isoformat(), ends_at=(start + timedelta(hours=1)).isoformat()
    )

    assert organiser_client.post("/events", json=payload).status_code == 422


@pytest.mark.story("2.1", ac=2)
@pytest.mark.parametrize(
    "change_field, delta_days",
    [("ends_at", -60), ("starts_at", 60)],
    ids=["end-before-stored-start", "start-after-stored-end"],
)
def test_an_edit_is_checked_against_the_stored_other_date(
    organiser_client, change_field, delta_days
):
    created = create_event_request(organiser_client)
    stored = datetime.fromisoformat(created[change_field])
    new_value = (stored + timedelta(days=delta_days)).isoformat()

    response = organiser_client.patch(f"/events/{created['id']}", json={change_field: new_value})

    assert response.status_code == 422
    assert "after the start" in _detail(response)


@pytest.mark.story("2.1", ac=2)
def test_an_unrelated_edit_is_not_rejected_because_the_saved_start_has_since_passed(
    organiser_client, db: Session
):
    created = create_event_request(organiser_client)
    db.execute(
        text(
            "UPDATE events SET starts_at = now() - interval '2 days',"
            " ends_at = now() - interval '1 day' WHERE id = :id"
        ),
        {"id": created["id"]},
    )
    db.expire_all()

    response = organiser_client.patch(f"/events/{created['id']}", json={"name": "Renamed"})

    assert response.status_code == 200, response.text


# --- AC3: positive whole numbers only -----------------------------------------------------------
@pytest.mark.story("2.1", ac=3)
@pytest.mark.parametrize("attendance", NOT_WHOLE_POSITIVE)
def test_attendance_rejects_anything_but_a_positive_whole_number(organiser_client, attendance):
    response = organiser_client.post(
        "/events", json=event_request_payload(expected_attendance=attendance)
    )

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=3)
@pytest.mark.parametrize("attendance", [1, INT32_MAX], ids=["smallest", "largest"])
def test_attendance_accepts_the_boundary_values(organiser_client, attendance):
    response = organiser_client.post(
        "/events", json=event_request_payload(expected_attendance=attendance)
    )

    assert response.status_code == 201, response.text
    assert response.json()["expected_attendance"] == attendance


@pytest.mark.story("2.1", ac=3)
def test_attendance_can_be_left_empty_on_a_draft(organiser_client):
    body = create_event_request(organiser_client, expected_attendance=None)

    assert body["expected_attendance"] is None


@pytest.mark.story("2.1", ac=3)
@pytest.mark.parametrize("attendance", NOT_WHOLE_POSITIVE)
def test_an_edit_also_rejects_a_bad_attendance(organiser_client, attendance):
    created = create_event_request(organiser_client)

    response = organiser_client.patch(
        f"/events/{created['id']}", json={"expected_attendance": attendance}
    )

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=3)
@pytest.mark.parametrize("quantity", NOT_WHOLE_POSITIVE)
def test_equipment_quantity_rejects_anything_but_a_positive_whole_number(
    organiser_client, quantity
):
    response = organiser_client.post(
        "/events", json=event_request_payload(equipment=[_equipment("LAPTOP", quantity)])
    )

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=3)
def test_an_edit_also_rejects_a_bad_equipment_quantity(organiser_client):
    created = create_event_request(organiser_client, equipment=[_equipment("LAPTOP", 2)])
    line = created["equipment"][0]

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={"equipment": [{**_equipment("LAPTOP", 0), "id": line["id"]}]},
    )

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=3)
@pytest.mark.parametrize("quantity", [1, INT32_MAX], ids=["smallest", "largest"])
def test_equipment_quantity_accepts_the_boundary_values(organiser_client, quantity):
    created = create_event_request(organiser_client, equipment=[_equipment("LAPTOP", quantity)])

    assert created["equipment"][0]["quantity"] == quantity


@pytest.mark.story("2.1", ac=3)
@pytest.mark.parametrize("quantity", NOT_WHOLE_POSITIVE)
def test_facility_quantity_rejects_anything_but_a_positive_whole_number(organiser_client, quantity):
    payload = event_request_payload(
        required_facilities=[{"code": "BREAKOUT_ROOMS", "quantity": quantity}]
    )

    assert organiser_client.post("/events", json=payload).status_code == 422


@pytest.mark.story("2.1", ac=3)
@pytest.mark.parametrize("quantity", [1, INT32_MAX], ids=["smallest", "largest"])
def test_facility_quantity_accepts_the_boundary_values(organiser_client, quantity):
    created = create_event_request(
        organiser_client, required_facilities=[{"code": "BREAKOUT_ROOMS", "quantity": quantity}]
    )

    assert created["required_facilities"][0]["quantity"] == quantity


@pytest.mark.story("2.1", ac=3)
def test_an_edit_also_rejects_a_bad_facility_quantity(organiser_client):
    created = create_event_request(organiser_client)

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={"required_facilities": [{"code": "BREAKOUT_ROOMS", "quantity": 0}]},
    )

    assert response.status_code == 422


# --- AC4: venue requirements ------------------------------------------------------------------
@pytest.mark.story("2.1", ac=4)
def test_venue_requirements_are_recorded_with_their_names(organiser_client):
    created = create_event_request(
        organiser_client,
        required_layout_code="THEATRE",
        venue_requirement_notes="Close to the lifts",
        expected_attendance=120,
        required_facilities=[
            {"code": "PROJECTOR", "notes": "HDMI input"},
            {"code": "BREAKOUT_ROOMS", "quantity": 3},
            {"code": "WIFI"},
        ],
    )

    assert created["required_layout_code"] == "THEATRE"
    assert created["required_layout_name"] == "Theatre"
    assert created["venue_requirement_notes"] == "Close to the lifts"
    assert created["venue_none_required"] is False
    assert created["expected_attendance"] == 120
    facilities = {
        f["code"]: (f["name"], f["quantity"], f["notes"]) for f in created["required_facilities"]
    }
    assert facilities == {
        "PROJECTOR": ("Projector & screen", None, "HDMI input"),
        "BREAKOUT_ROOMS": ("Breakout rooms", 3, None),
        "WIFI": ("Wi-Fi", None, None),
    }


@pytest.mark.story("2.1", ac=4)
def test_leaving_venue_requirements_empty_is_stored_as_not_yet_specified(organiser_client):
    created = create_event_request(organiser_client)

    assert created["venue_none_required"] is False
    assert created["required_layout_code"] is None and created["required_layout_name"] is None
    assert created["required_facilities"] == []
    assert created["venue_requirement_notes"] is None


@pytest.mark.story("2.1", ac=4)
def test_no_venue_requirements_is_stored_distinguishably_from_left_empty(organiser_client):
    unspecified = create_event_request(organiser_client)
    none_required = create_event_request(organiser_client, venue_none_required=True)

    assert none_required["venue_none_required"] is True
    assert none_required["required_layout_code"] is None
    assert none_required["required_facilities"] == []
    assert none_required["venue_requirement_notes"] is None
    assert none_required["venue_none_required"] != unspecified["venue_none_required"]
    assert organiser_client.get(f"/events/{none_required['id']}").json() == none_required


@pytest.mark.story("2.1", ac=4)
@pytest.mark.parametrize(
    "extra",
    [
        {"required_layout_code": "THEATRE"},
        {"required_facilities": [{"code": "WIFI"}]},
        {"venue_requirement_notes": "Near the lifts"},
    ],
    ids=["with-layout", "with-facility", "with-notes"],
)
def test_no_venue_requirements_contradicts_a_stated_requirement(organiser_client, extra):
    payload = event_request_payload(venue_none_required=True, **extra)

    response = organiser_client.post("/events", json=payload)

    assert response.status_code == 422
    assert "none required" in _detail(response)


@pytest.mark.story("2.1", ac=4)
def test_an_edit_is_checked_against_the_stored_venue_none_required(organiser_client):
    created = create_event_request(organiser_client, venue_none_required=True)

    contradiction = organiser_client.patch(
        f"/events/{created['id']}", json={"required_layout_code": "THEATRE"}
    )
    consistent = organiser_client.patch(
        f"/events/{created['id']}",
        json={"venue_none_required": False, "required_layout_code": "THEATRE"},
    )

    assert contradiction.status_code == 422
    assert consistent.status_code == 200, consistent.text
    assert consistent.json()["venue_none_required"] is False


@pytest.mark.story("2.1", ac=4)
def test_venue_requirements_can_be_returned_to_not_yet_specified(organiser_client):
    created = create_event_request(organiser_client, venue_none_required=True)

    response = organiser_client.patch(
        f"/events/{created['id']}", json={"venue_none_required": False}
    )

    assert response.status_code == 200, response.text
    assert response.json()["venue_none_required"] is False
    assert response.json()["required_facilities"] == []


@pytest.mark.story("2.1", ac=4)
@pytest.mark.parametrize("via", ["create", "edit"])
def test_a_preferred_location_is_no_longer_accepted(organiser_client, via):
    if via == "create":
        response = organiser_client.post(
            "/events", json=event_request_payload(preferred_location="Tower A")
        )
    else:
        created = create_event_request(organiser_client)
        response = organiser_client.patch(
            f"/events/{created['id']}", json={"preferred_location": "Tower A"}
        )

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=4)
@pytest.mark.parametrize(
    "overrides",
    [
        {"required_layout_code": "NO_SUCH_LAYOUT"},
        {"required_facilities": [{"code": "NO_SUCH_FACILITY"}]},
        {"required_facilities": [{"code": "WIFI"}, {"code": "WIFI"}]},
    ],
    ids=["unknown-layout", "unknown-facility", "duplicate-facility"],
)
def test_venue_requirements_must_name_real_options(organiser_client, overrides):
    response = organiser_client.post("/events", json=event_request_payload(**overrides))

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=4)
def test_reference_data_lists_the_pick_lists_for_the_form(organiser_client):
    response = organiser_client.get("/events/reference-data")

    assert response.status_code == 200, response.text
    body = response.json()
    assert "THEATRE" in {item["code"] for item in body["layouts"]}
    assert "PROJECTOR" in {item["code"] for item in body["facilities"]}
    assert "HEARING_LOOP" in {item["code"] for item in body["accessibility_features"]}
    assert "WIRELESS_MIC" in {item["code"] for item in body["equipment_types"]}


@pytest.mark.story("2.1", ac=4)
@pytest.mark.parametrize("user", NON_ORGANISERS)
def test_reference_data_is_for_organisers_only(login_as, user):
    assert login_as(user).get("/events/reference-data").status_code == 403


@pytest.mark.story("2.1", ac=4)
def test_reference_data_requires_sign_in(client):
    assert client.get("/events/reference-data").status_code == 401


# --- AC5: accessibility needs, and "none required" versus left empty ---------------------------
@pytest.mark.story("2.1", ac=5)
def test_leaving_accessibility_empty_is_stored_as_not_yet_specified(organiser_client):
    created = create_event_request(organiser_client)

    assert created["accessibility_none_required"] is False
    assert created["accessibility_needs"] == []
    assert created["accessibility_notes"] is None


@pytest.mark.story("2.1", ac=5)
def test_none_required_is_stored_distinguishably_from_left_empty(organiser_client):
    unspecified = create_event_request(organiser_client)
    none_required = create_event_request(organiser_client, accessibility_none_required=True)

    assert none_required["accessibility_none_required"] is True
    assert none_required["accessibility_needs"] == []
    assert (
        none_required["accessibility_none_required"] != unspecified["accessibility_none_required"]
    )
    fetched = organiser_client.get(f"/events/{none_required['id']}").json()
    assert fetched["accessibility_none_required"] is True


@pytest.mark.story("2.1", ac=5)
def test_several_accessibility_needs_can_be_selected_with_notes(organiser_client):
    created = create_event_request(
        organiser_client,
        accessibility_needs=[
            {"code": "WHEELCHAIR_ACCESS", "notes": "Two wheelchair users"},
            {"code": "HEARING_LOOP"},
        ],
    )

    assert created["accessibility_none_required"] is False
    assert {n["code"]: (n["name"], n["notes"]) for n in created["accessibility_needs"]} == {
        "WHEELCHAIR_ACCESS": ("Wheelchair access", "Two wheelchair users"),
        "HEARING_LOOP": ("Hearing loop", None),
    }


@pytest.mark.story("2.1", ac=5)
def test_accessibility_needs_can_be_described_in_words_alone(organiser_client):
    created = create_event_request(organiser_client, accessibility_notes="Guide dog attending")

    assert created["accessibility_notes"] == "Guide dog attending"
    assert created["accessibility_needs"] == []
    assert created["accessibility_none_required"] is False


@pytest.mark.story("2.1", ac=5)
@pytest.mark.parametrize(
    "extra",
    [
        {"accessibility_needs": [{"code": "LIFT_ACCESS"}]},
        {"accessibility_notes": "Ramp needed"},
    ],
    ids=["with-selected-need", "with-notes"],
)
def test_none_required_contradicts_a_stated_need(organiser_client, extra):
    payload = event_request_payload(accessibility_none_required=True, **extra)

    response = organiser_client.post("/events", json=payload)

    assert response.status_code == 422
    assert "none required" in _detail(response)


@pytest.mark.story("2.1", ac=5)
def test_an_edit_is_checked_against_the_stored_none_required(organiser_client):
    created = create_event_request(organiser_client, accessibility_none_required=True)

    contradiction = organiser_client.patch(
        f"/events/{created['id']}", json={"accessibility_needs": [{"code": "LIFT_ACCESS"}]}
    )
    consistent = organiser_client.patch(
        f"/events/{created['id']}",
        json={
            "accessibility_none_required": False,
            "accessibility_needs": [{"code": "LIFT_ACCESS"}],
        },
    )

    assert contradiction.status_code == 422
    assert consistent.status_code == 200, consistent.text
    assert consistent.json()["accessibility_none_required"] is False


@pytest.mark.story("2.1", ac=5)
def test_accessibility_can_be_returned_to_not_yet_specified(organiser_client):
    created = create_event_request(organiser_client, accessibility_none_required=True)

    response = organiser_client.patch(
        f"/events/{created['id']}", json={"accessibility_none_required": False}
    )

    assert response.status_code == 200, response.text
    assert response.json()["accessibility_none_required"] is False
    assert response.json()["accessibility_needs"] == []


@pytest.mark.story("2.1", ac=5)
@pytest.mark.parametrize(
    "needs",
    [
        [{"code": "NO_SUCH_FEATURE"}],
        [{"code": "LIFT_ACCESS"}, {"code": "LIFT_ACCESS"}],
    ],
    ids=["unknown-feature", "duplicate-feature"],
)
def test_accessibility_needs_must_name_real_features_once_each(organiser_client, needs):
    response = organiser_client.post(
        "/events", json=event_request_payload(accessibility_needs=needs)
    )

    assert response.status_code == 422


# --- AC6: several equipment items, each with a type and quantity -------------------------------
@pytest.mark.story("2.1", ac=6)
def test_several_equipment_items_are_added_each_with_type_and_quantity(
    organiser_client, db: Session
):
    created = create_event_request(
        organiser_client,
        equipment=[
            _equipment("WIRELESS_MIC", 6, technical_notes="Two per breakout room"),
            _equipment("LAPTOP", 2),
            _equipment("SPEAKER_SET", 1),
        ],
    )

    lines = {line["equipment_type_code"]: line for line in created["equipment"]}
    assert set(lines) == {"WIRELESS_MIC", "LAPTOP", "SPEAKER_SET"}
    assert lines["WIRELESS_MIC"]["equipment_type_name"] == "Wireless microphone"
    assert lines["WIRELESS_MIC"]["quantity"] == 6
    assert lines["WIRELESS_MIC"]["technical_notes"] == "Two per breakout room"
    assert lines["LAPTOP"]["technical_notes"] is None
    assert {line["status"] for line in created["equipment"]} == {"REQUESTED"}
    creators = db.execute(
        text("SELECT DISTINCT created_by_id FROM event_equipment_requests WHERE event_id = :id"),
        {"id": created["id"]},
    ).all()
    assert [row.created_by_id for row in creators] == [Users.ORGANISER.id]


@pytest.mark.story("2.1", ac=6)
def test_a_request_may_have_no_equipment(organiser_client):
    assert create_event_request(organiser_client)["equipment"] == []


@pytest.mark.story("2.1", ac=6)
def test_the_same_equipment_type_cannot_appear_twice(organiser_client):
    payload = event_request_payload(equipment=[_equipment("LAPTOP", 1), _equipment("LAPTOP", 2)])

    response = organiser_client.post("/events", json=payload)

    assert response.status_code == 422
    assert "once" in _detail(response)


@pytest.mark.story("2.1", ac=6)
def test_equipment_must_be_a_known_type(organiser_client):
    payload = event_request_payload(equipment=[_equipment("NO_SUCH_TYPE", 1)])

    assert organiser_client.post("/events", json=payload).status_code == 422


@pytest.mark.story("2.1", ac=6)
def test_an_inactive_equipment_type_is_hidden_and_cannot_be_requested(
    organiser_client, db: Session
):
    db.execute(text("UPDATE equipment_types SET is_active = FALSE WHERE code = 'LAPTOP'"))

    listed = organiser_client.get("/events/reference-data").json()["equipment_types"]
    response = organiser_client.post(
        "/events", json=event_request_payload(equipment=[_equipment("LAPTOP", 1)])
    )

    assert "LAPTOP" not in {item["code"] for item in listed}
    assert response.status_code == 422


@pytest.mark.story("2.1", ac=6)
def test_equipment_needs_a_type_and_a_quantity(organiser_client):
    without_quantity = event_request_payload(equipment=[{"equipment_type_code": "LAPTOP"}])
    without_type = event_request_payload(equipment=[{"quantity": 2}])

    assert organiser_client.post("/events", json=without_quantity).status_code == 422
    assert organiser_client.post("/events", json=without_type).status_code == 422


# --- AC7: edit or remove anything before submission ---------------------------------------------
@pytest.mark.story("2.1", ac=7)
def test_recorded_details_can_be_edited(organiser_client):
    created = create_event_request(organiser_client)
    start = future_datetime(days=90)

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={
            "name": "Renamed event",
            "purpose": "New purpose",
            "description": "New description",
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(hours=3)).isoformat(),
            "expected_attendance": 75,
            "required_layout_code": "BOARDROOM",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["name"], body["purpose"], body["description"]) == (
        "Renamed event",
        "New purpose",
        "New description",
    )
    assert body["expected_attendance"] == 75
    assert body["required_layout_name"] == "Boardroom"
    assert datetime.fromisoformat(body["starts_at"]) == start
    assert organiser_client.get(f"/events/{created['id']}").json() == body


@pytest.mark.story("2.1", ac=7)
def test_an_optional_detail_can_be_removed_with_null(organiser_client):
    created = create_event_request(
        organiser_client, venue_requirement_notes="Near the lifts", required_layout_code="THEATRE"
    )

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={"description": None, "venue_requirement_notes": None, "required_layout_code": None},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["description"] is None and body["venue_requirement_notes"] is None
    assert body["required_layout_code"] is None and body["required_layout_name"] is None
    assert body["purpose"] == created["purpose"]  # fields not sent are untouched


@pytest.mark.story("2.1", ac=7)
@pytest.mark.parametrize("name", [None, "", "   "], ids=["null", "empty", "blank"])
def test_the_name_cannot_be_removed(organiser_client, name):
    created = create_event_request(organiser_client)

    response = organiser_client.patch(f"/events/{created['id']}", json={"name": name})

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=7)
def test_equipment_can_be_edited_added_and_removed_in_one_save(organiser_client):
    created = create_event_request(
        organiser_client, equipment=[_equipment("WIRELESS_MIC", 2), _equipment("LAPTOP", 1)]
    )
    ids = _ids(created["equipment"])

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={
            "equipment": [
                _equipment("WIRELESS_MIC", 5, id=ids["WIRELESS_MIC"]),  # edited
                _equipment("SPEAKER_SET", 1),  # added; LAPTOP is left out, so removed
            ]
        },
    )

    assert response.status_code == 200, response.text
    lines = {line["equipment_type_code"]: line for line in response.json()["equipment"]}
    assert set(lines) == {"WIRELESS_MIC", "SPEAKER_SET"}
    assert lines["WIRELESS_MIC"]["quantity"] == 5
    assert lines["WIRELESS_MIC"]["id"] == ids["WIRELESS_MIC"]  # the line itself is kept


@pytest.mark.story("2.1", ac=7)
def test_all_equipment_can_be_removed_with_an_empty_list(organiser_client):
    created = create_event_request(organiser_client, equipment=[_equipment("LAPTOP", 1)])

    response = organiser_client.patch(f"/events/{created['id']}", json={"equipment": []})

    assert response.status_code == 200, response.text
    assert response.json()["equipment"] == []


@pytest.mark.story("2.1", ac=7)
def test_an_equipment_line_of_another_request_cannot_be_claimed(organiser_client):
    other = create_event_request(organiser_client, equipment=[_equipment("LAPTOP", 1)])
    mine = create_event_request(organiser_client)

    response = organiser_client.patch(
        f"/events/{mine['id']}",
        json={"equipment": [_equipment("LAPTOP", 1, id=other["equipment"][0]["id"])]},
    )

    assert response.status_code == 422
    assert organiser_client.get(f"/events/{other['id']}").json()["equipment"] == other["equipment"]


@pytest.mark.story("2.1", ac=7)
def test_facilities_and_accessibility_needs_can_be_replaced_or_cleared(organiser_client):
    created = create_event_request(
        organiser_client,
        required_facilities=[{"code": "PROJECTOR"}, {"code": "WIFI"}],
        accessibility_needs=[{"code": "HEARING_LOOP"}],
    )

    replaced = organiser_client.patch(
        f"/events/{created['id']}",
        json={"required_facilities": [{"code": "STAGE"}], "accessibility_needs": []},
    ).json()

    assert [f["code"] for f in replaced["required_facilities"]] == ["STAGE"]
    assert replaced["accessibility_needs"] == []


@pytest.mark.story("2.1", ac=7)
def test_a_list_left_out_of_an_edit_is_untouched(organiser_client):
    created = create_event_request(
        organiser_client,
        required_facilities=[{"code": "WIFI"}],
        accessibility_needs=[{"code": "HEARING_LOOP"}],
        equipment=[_equipment("LAPTOP", 3)],
    )

    body = organiser_client.patch(f"/events/{created['id']}", json={"name": "Renamed"}).json()

    assert body["required_facilities"] == created["required_facilities"]
    assert body["accessibility_needs"] == created["accessibility_needs"]
    assert body["equipment"] == created["equipment"]


@pytest.mark.story("2.1", ac=7)
def test_the_client_cannot_change_server_controlled_fields_on_edit(organiser_client):
    created = create_event_request(organiser_client)

    for field, value in (("status", "APPROVED"), ("organiser_id", str(Users.ORGANISER_2.id))):
        response = organiser_client.patch(f"/events/{created['id']}", json={field: value})
        assert response.status_code == 422, field


@pytest.mark.story("2.1", ac=7)
def test_a_submitted_request_can_no_longer_be_edited(organiser_client):
    created = create_submittable_event_request(
        organiser_client, equipment=[_equipment("LAPTOP", 1)]
    )
    assert organiser_client.post(f"/events/{created['id']}/submit").status_code == 200

    for change in (
        {"name": "Too late"},
        {"required_facilities": [{"code": "WIFI"}]},
        {"equipment": []},
    ):
        response = organiser_client.patch(f"/events/{created['id']}", json=change)
        assert response.status_code == 409, change
        assert "can no longer be edited" in _detail(response)
    assert organiser_client.get(f"/events/{created['id']}").json()["name"] == created["name"]


@pytest.mark.story("2.1", ac=7)
def test_another_organisers_request_cannot_be_edited(login_as):
    created = create_event_request(login_as(Users.ORGANISER))

    response = login_as(Users.ORGANISER_2).patch(f"/events/{created['id']}", json={"name": "Mine"})

    assert response.status_code == 404


@pytest.mark.story("2.1", ac=7)
@pytest.mark.parametrize("user", NON_ORGANISERS)
def test_only_an_organiser_can_edit_a_request(login_as, user):
    created = create_event_request(login_as(Users.ORGANISER))

    response = login_as(user).patch(f"/events/{created['id']}", json={"name": "Nope"})

    assert response.status_code == 403


@pytest.mark.story("2.1", ac=7)
def test_editing_requires_sign_in_and_an_existing_request(client, login_as):
    created = create_event_request(login_as(Users.ORGANISER))
    client.logout()

    assert client.patch(f"/events/{created['id']}", json={"name": "x"}).status_code == 401
    login_as(Users.ORGANISER)
    assert client.patch(f"/events/{uuid.uuid4()}", json={"name": "x"}).status_code == 404
    assert client.patch("/events/not-a-uuid", json={"name": "x"}).status_code == 422


# --- AC8: everything recorded is visible to the reviewing coordinator --------------------------
def _full_request(client) -> dict:
    return create_event_request(
        client,
        name="Nimbus Summit",
        required_layout_code="THEATRE",
        venue_requirement_notes="Near the loading bay",
        required_facilities=[
            {"code": "STAGE", "notes": "Keynote riser"},
            {"code": "BREAKOUT_ROOMS", "quantity": 3},
        ],
        accessibility_needs=[{"code": "WHEELCHAIR_ACCESS", "notes": "Two users"}],
        accessibility_notes="Quiet room for one attendee",
        equipment=[
            _equipment("WIRELESS_MIC", 6, technical_notes="Two per room"),
            _equipment("LAPTOP", 2),
        ],
    )


@pytest.mark.story("2.1", ac=8)
def test_the_coordinator_sees_every_detail_requirement_and_equipment_item(login_as):
    organiser = login_as(Users.ORGANISER)
    created = _full_request(organiser)
    assert organiser.post(f"/events/{created['id']}/submit").status_code == 200

    response = login_as(Users.COORDINATOR).get(f"/events/{created['id']}")

    assert response.status_code == 200, response.text
    body = response.json()
    for field in ("name", "purpose", "description", "expected_attendance"):
        assert body[field] == created[field], field
    assert datetime.fromisoformat(body["starts_at"]) == datetime.fromisoformat(created["starts_at"])
    assert datetime.fromisoformat(body["ends_at"]) == datetime.fromisoformat(created["ends_at"])
    assert body["status"] == "SUBMITTED"
    assert body["organiser_name"] == Users.ORGANISER.full_name
    assert body["required_layout_name"] == "Theatre"
    assert body["venue_requirement_notes"] == "Near the loading bay"
    assert body["venue_none_required"] is False
    assert {(f["name"], f["quantity"], f["notes"]) for f in body["required_facilities"]} == {
        ("Stage", None, "Keynote riser"),
        ("Breakout rooms", 3, None),
    }
    assert [(n["name"], n["notes"]) for n in body["accessibility_needs"]] == [
        ("Wheelchair access", "Two users")
    ]
    assert body["accessibility_notes"] == "Quiet room for one attendee"
    assert body["accessibility_none_required"] is False
    assert {
        (e["equipment_type_name"], e["quantity"], e["technical_notes"]) for e in body["equipment"]
    } == {("Wireless microphone", 6, "Two per room"), ("Presentation laptop", 2, None)}


@pytest.mark.story("2.1", ac=8)
@pytest.mark.parametrize(
    "user",
    [
        pytest.param(Users.COORDINATOR_2, id="another-coordinator"),
        pytest.param(Users.VENUE_STAFF, id="venue-staff"),
        pytest.param(Users.TECH_SUPPORT, id="tech-support"),
    ],
)
def test_other_internal_roles_can_read_a_submitted_request(login_as, user):
    organiser = login_as(Users.ORGANISER)
    created = create_submittable_event_request(organiser)
    assert organiser.post(f"/events/{created['id']}/submit").status_code == 200

    assert login_as(user).get(f"/events/{created['id']}").status_code == 200


@pytest.mark.story("2.1", ac=8)
def test_a_draft_is_private_to_its_organiser(login_as):
    created = create_event_request(login_as(Users.ORGANISER))

    assert login_as(Users.ORGANISER).get(f"/events/{created['id']}").status_code == 200
    assert login_as(Users.COORDINATOR).get(f"/events/{created['id']}").status_code == 404
    assert login_as(Users.ORGANISER_2).get(f"/events/{created['id']}").status_code == 404


@pytest.mark.story("2.1", ac=8)
def test_another_organiser_cannot_read_a_submitted_request(login_as):
    organiser = login_as(Users.ORGANISER)
    created = create_submittable_event_request(organiser)
    assert organiser.post(f"/events/{created['id']}/submit").status_code == 200

    assert login_as(Users.ORGANISER_2).get(f"/events/{created['id']}").status_code == 404


@pytest.mark.story("2.1", ac=8)
def test_an_attendee_cannot_read_a_request(attendee_client):
    assert attendee_client.get(f"/events/{Events.SUBMITTED}").status_code == 403


@pytest.mark.story("2.1", ac=8)
def test_reading_a_request_requires_sign_in_and_an_existing_request(client, login_as):
    assert client.get(f"/events/{Events.SUBMITTED}").status_code == 401
    login_as(Users.COORDINATOR)
    assert client.get(f"/events/{uuid.uuid4()}").status_code == 404
    assert client.get("/events/not-a-uuid").status_code == 422
