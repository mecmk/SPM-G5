"""Story 2.1 - fe/be: capture event details, requirements and equipment on a request.

AC1 The organiser can record the event name, purpose, description, proposed date and time, and
    expected attendance.
AC2 The proposed end date/time must be after the start date/time, and a date in the past is
    rejected with an explanatory message.
AC3 Expected attendance and equipment quantities accept positive whole numbers only.
AC4 Venue requirements (e.g. preferred location, capacity, room layout) can be recorded on the
    request.
AC5 One or more accessibility needs can be selected or described; leaving them empty is
    permitted and is stored distinguishably from "none required".
AC6 Multiple equipment items can be added, each with a type and quantity.
AC7 Any recorded detail, requirement or equipment item can be edited or removed before the
    request is submitted.
AC8 All recorded details, requirements and equipment items are visible to the reviewing Event
    Coordinator.
AC9 An organiser can submit their own request only while it is still a draft.
AC10 Submitting requires purpose, proposed start/end date-time and expected attendance to
    already be filled in; if any is missing, submission is refused with a message naming what's
    missing.
AC11 On successful submission, the request's status changes to "submitted" and the submission
    date/time is recorded.
AC12 An organiser cannot submit someone else's request, and cannot submit a request that has
    already been submitted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.support.factories import event_payload
from tests.support.seed import EquipmentTypes, Events, Users

FUTURE_START = (datetime.now(UTC) + timedelta(days=30)).isoformat()
FUTURE_END = (datetime.now(UTC) + timedelta(days=30, hours=3)).isoformat()


# --- AC1: create -----------------------------------------------------------------------
@pytest.mark.story("2.1", ac=1)
def test_event_can_be_created_with_only_a_name(organiser_client):
    response = organiser_client.post("/events", json=event_payload())

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"].startswith("Test Event Request")
    assert body["status"] == "DRAFT"
    assert body["organiser_id"] == str(Users.ORGANISER.id)
    # nothing else was invented for a bare draft
    assert body["purpose"] is None
    assert body["starts_at"] is None
    assert body["required_facilities"] == []


@pytest.mark.story("2.1", ac=1)
def test_event_can_be_created_with_full_fields(organiser_client):
    payload = event_payload(
        purpose="Annual conference",
        description="All-hands kickoff",
        starts_at=FUTURE_START,
        ends_at=FUTURE_END,
        expected_attendance=120,
    )

    response = organiser_client.post("/events", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["purpose"] == "Annual conference"
    assert body["expected_attendance"] == 120


@pytest.mark.story("2.1", ac=1)
def test_name_is_mandatory(organiser_client):
    payload = event_payload()
    del payload["name"]
    assert organiser_client.post("/events", json=payload).status_code == 422


@pytest.mark.story("2.1", ac=1)
@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_name_is_rejected(organiser_client, blank):
    response = organiser_client.post("/events", json=event_payload(name=blank))
    assert response.status_code == 422


# --- AC2: period and no past start ------------------------------------------------------
@pytest.mark.story("2.1", ac=2)
def test_end_before_start_is_rejected(organiser_client):
    payload = event_payload(starts_at=FUTURE_END, ends_at=FUTURE_START)  # swapped
    assert organiser_client.post("/events", json=payload).status_code == 422


@pytest.mark.story("2.1", ac=2)
def test_end_equal_to_start_is_rejected(organiser_client):
    payload = event_payload(starts_at=FUTURE_START, ends_at=FUTURE_START)
    assert organiser_client.post("/events", json=payload).status_code == 422


@pytest.mark.story("2.1", ac=2)
def test_a_past_start_date_is_rejected_with_an_explanatory_message(organiser_client):
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    response = organiser_client.post("/events", json=event_payload(starts_at=past))
    assert response.status_code == 422
    assert "future" in response.text.lower()


@pytest.mark.story("2.1", ac=2)
def test_future_period_is_accepted(organiser_client):
    payload = event_payload(starts_at=FUTURE_START, ends_at=FUTURE_END)
    assert organiser_client.post("/events", json=payload).status_code == 201


# --- AC3: positive whole numbers only ---------------------------------------------------
@pytest.mark.story("2.1", ac=3)
@pytest.mark.parametrize("bad_attendance", [0, -1, 12.5, "12", True])
def test_expected_attendance_rejects_non_positive_or_non_integer_values(
    organiser_client, bad_attendance
):
    response = organiser_client.post(
        "/events", json=event_payload(expected_attendance=bad_attendance)
    )
    assert response.status_code == 422, response.text


@pytest.mark.story("2.1", ac=3)
def test_expected_attendance_accepts_a_positive_whole_number(organiser_client):
    response = organiser_client.post("/events", json=event_payload(expected_attendance=1))
    assert response.status_code == 201


@pytest.mark.story("2.1", ac=3)
@pytest.mark.parametrize("bad_quantity", [0, -1, 2.5, "2"])
def test_equipment_quantity_rejects_non_positive_or_non_integer_values(
    organiser_client, bad_quantity
):
    payload = event_payload(
        equipment_requests=[
            {"equipment_type_id": str(EquipmentTypes.WIRELESS_MIC), "quantity": bad_quantity}
        ]
    )
    assert organiser_client.post("/events", json=payload).status_code == 422


# --- AC4: venue requirements -------------------------------------------------------------
@pytest.mark.story("2.1", ac=4)
def test_venue_requirements_round_trip(organiser_client):
    payload = event_payload(
        preferred_location="Tower B",
        required_layout_code="THEATRE",
        venue_requirement_notes="Need a stage",
        required_facilities=[{"code": "PROJECTOR", "notes": "HDMI"}, {"code": "WIFI"}],
    )

    response = organiser_client.post("/events", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["preferred_location"] == "Tower B"
    assert body["required_layout_code"] == "THEATRE"
    assert body["required_layout_name"] == "Theatre"
    assert {f["code"]: f["notes"] for f in body["required_facilities"]} == {
        "PROJECTOR": "HDMI",
        "WIFI": None,
    }


@pytest.mark.story("2.1", ac=4)
def test_unknown_layout_code_is_refused(organiser_client):
    response = organiser_client.post("/events", json=event_payload(required_layout_code="HOLODECK"))
    assert response.status_code == 422
    assert "HOLODECK" in response.json()["detail"]


@pytest.mark.story("2.1", ac=4)
def test_unknown_facility_code_is_refused(organiser_client):
    response = organiser_client.post(
        "/events", json=event_payload(required_facilities=[{"code": "HOLODECK"}])
    )
    assert response.status_code == 422
    assert "HOLODECK" in response.json()["detail"]


# --- AC5: accessibility needs, distinguishable from "none required" ---------------------
@pytest.mark.story("2.1", ac=5)
def test_accessibility_features_round_trip(organiser_client):
    payload = event_payload(
        accessibility_features=[{"code": "WHEELCHAIR_ACCESS", "notes": "Via side door"}],
        accessibility_notes="Please confirm lift access",
    )

    response = organiser_client.post("/events", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["accessibility_features"][0]["notes"] == "Via side door"
    assert body["accessibility_none_required"] is False


@pytest.mark.story("2.1", ac=5)
def test_none_required_and_selected_features_are_mutually_exclusive(organiser_client):
    payload = event_payload(
        accessibility_none_required=True,
        accessibility_features=[{"code": "WHEELCHAIR_ACCESS"}],
    )
    assert organiser_client.post("/events", json=payload).status_code == 422


@pytest.mark.story("2.1", ac=5)
def test_leaving_accessibility_blank_is_distinguishable_from_none_required(organiser_client):
    not_yet_specified = organiser_client.post("/events", json=event_payload()).json()
    none_required = organiser_client.post(
        "/events", json=event_payload(accessibility_none_required=True)
    ).json()

    assert not_yet_specified["accessibility_none_required"] is False
    assert not_yet_specified["accessibility_features"] == []
    assert none_required["accessibility_none_required"] is True
    assert none_required["accessibility_features"] == []


# --- AC6: multiple equipment items ---------------------------------------------------------
@pytest.mark.story("2.1", ac=6)
def test_multiple_equipment_lines_round_trip(organiser_client):
    payload = event_payload(
        equipment_requests=[
            {"equipment_type_id": str(EquipmentTypes.WIRELESS_MIC), "quantity": 2},
            {
                "equipment_type_id": str(EquipmentTypes.PROJECTOR_PORTABLE),
                "quantity": 1,
                "technical_notes": "Needs HDMI",
            },
        ]
    )

    response = organiser_client.post("/events", json=payload)

    assert response.status_code == 201, response.text
    lines = {e["code"]: e["quantity"] for e in response.json()["equipment_requests"]}
    assert lines == {"WIRELESS_MIC": 2, "PROJECTOR_PORTABLE": 1}


@pytest.mark.story("2.1", ac=6)
def test_unknown_equipment_type_is_refused(organiser_client):
    payload = event_payload(
        equipment_requests=[
            {"equipment_type_id": "00000000-0000-0000-0000-000000000000", "quantity": 1}
        ]
    )
    assert organiser_client.post("/events", json=payload).status_code == 422


# --- AC7: edit or remove before submission -----------------------------------------------
@pytest.mark.story("2.1", ac=7)
def test_a_scalar_field_can_be_edited(organiser_client):
    created = organiser_client.post("/events", json=event_payload()).json()

    response = organiser_client.patch(f"/events/{created['id']}", json={"purpose": "Updated"})

    assert response.status_code == 200, response.text
    assert response.json()["purpose"] == "Updated"
    assert organiser_client.get(f"/events/{created['id']}").json()["purpose"] == "Updated"


@pytest.mark.story("2.1", ac=7)
def test_equipment_lines_can_be_added_and_removed(organiser_client):
    created = organiser_client.post(
        "/events",
        json=event_payload(
            equipment_requests=[
                {"equipment_type_id": str(EquipmentTypes.WIRELESS_MIC), "quantity": 1}
            ]
        ),
    ).json()

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={
            "equipment_requests": [{"equipment_type_id": str(EquipmentTypes.LAPTOP), "quantity": 3}]
        },
    )

    assert response.status_code == 200, response.text
    lines = {e["code"]: e["quantity"] for e in response.json()["equipment_requests"]}
    assert lines == {"LAPTOP": 3}


@pytest.mark.story("2.1", ac=7)
def test_a_list_can_be_cleared_to_empty(organiser_client):
    created = organiser_client.post(
        "/events",
        json=event_payload(required_facilities=[{"code": "PROJECTOR"}]),
    ).json()

    response = organiser_client.patch(f"/events/{created['id']}", json={"required_facilities": []})

    assert response.status_code == 200
    assert response.json()["required_facilities"] == []


@pytest.mark.story("2.1", ac=7)
def test_editing_someone_elses_request_is_refused(client):
    client.login(Users.ORGANISER)
    created = client.post("/events", json=event_payload()).json()
    client.login(Users.ORGANISER_2)

    response = client.patch(f"/events/{created['id']}", json={"purpose": "Hijacked"})

    assert response.status_code == 403


@pytest.mark.story("2.1", ac=7)
def test_editing_a_request_that_is_no_longer_a_draft_is_refused(organiser_client, db: Session):
    # ck_events_submitted_fields_complete requires these fields once status != DRAFT.
    created = organiser_client.post(
        "/events",
        json=event_payload(
            purpose="x", starts_at=FUTURE_START, ends_at=FUTURE_END, expected_attendance=1
        ),
    ).json()
    db.execute(text("UPDATE events SET status = 'SUBMITTED' WHERE id = :id"), {"id": created["id"]})
    db.commit()

    response = organiser_client.patch(f"/events/{created['id']}", json={"purpose": "Too late"})

    assert response.status_code == 409


@pytest.mark.story("2.1", ac=7)
def test_updating_a_missing_event_is_404(organiser_client):
    response = organiser_client.patch(
        "/events/00000000-0000-0000-0000-000000000000", json={"purpose": "x"}
    )
    assert response.status_code == 404


@pytest.mark.story("2.1", ac=7)
def test_partial_update_period_is_checked_against_the_existing_record(organiser_client):
    created = organiser_client.post(
        "/events", json=event_payload(starts_at=FUTURE_START, ends_at=FUTURE_END)
    ).json()

    # only ends_at supplied; must still be checked against the existing starts_at
    before_start = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    response = organiser_client.patch(f"/events/{created['id']}", json={"ends_at": before_start})

    assert response.status_code == 422


# --- AC8: visible to the reviewing Event Coordinator --------------------------------------
@pytest.mark.story("2.1", ac=8)
def test_coordinator_can_view_any_draft_with_every_recorded_field(coordinator_client):
    response = coordinator_client.get(f"/events/{Events.DRAFT}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(Events.DRAFT)
    assert "required_facilities" in body and "equipment_requests" in body


@pytest.mark.story("2.1", ac=8)
def test_a_different_organiser_cannot_view_someone_elses_draft(client):
    client.login(Users.ORGANISER_2)
    response = client.get(f"/events/{Events.DRAFT}")  # belongs to ORGANISER
    assert response.status_code == 403


@pytest.mark.story("2.1", ac=8)
def test_unauthenticated_request_is_refused(client):
    response = client.get(f"/events/{Events.DRAFT}")
    assert response.status_code == 401


@pytest.mark.story("2.1")
def test_organiser_list_shows_only_their_own_requests(organiser_client):
    ids = {e["id"] for e in organiser_client.get("/events").json()}
    assert str(Events.DRAFT) in ids  # ORGANISER's own
    assert str(Events.APPROVED) not in ids  # belongs to ORGANISER_2


@pytest.mark.story("2.1")
def test_coordinator_list_shows_every_request(coordinator_client):
    ids = {e["id"] for e in coordinator_client.get("/events").json()}
    assert {str(Events.DRAFT), str(Events.APPROVED)} <= ids


# --- AC9-12: submit ------------------------------------------------------------------------
def _complete_payload(**overrides) -> dict:
    return event_payload(
        purpose="Kickoff",
        starts_at=FUTURE_START,
        ends_at=FUTURE_END,
        expected_attendance=10,
        **overrides,
    )


@pytest.mark.story("2.1", ac=9)
def test_a_complete_draft_can_be_submitted(organiser_client):
    created = organiser_client.post("/events", json=_complete_payload()).json()

    response = organiser_client.post(f"/events/{created['id']}/submit")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "SUBMITTED"


@pytest.mark.story("2.1", ac=10)
@pytest.mark.parametrize(
    "missing_field", ["purpose", "starts_at", "ends_at", "expected_attendance"]
)
def test_submitting_with_a_mandatory_field_missing_is_refused(organiser_client, missing_field):
    payload = _complete_payload()
    del payload[missing_field]
    created = organiser_client.post("/events", json=payload).json()

    response = organiser_client.post(f"/events/{created['id']}/submit")

    assert response.status_code == 422, response.text


@pytest.mark.story("2.1", ac=11)
def test_submission_records_status_and_timestamp(organiser_client):
    created = organiser_client.post("/events", json=_complete_payload()).json()
    assert created["submitted_at"] is None

    organiser_client.post(f"/events/{created['id']}/submit")

    body = organiser_client.get(f"/events/{created['id']}").json()
    assert body["status"] == "SUBMITTED"
    assert body["submitted_at"] is not None


@pytest.mark.story("2.1", ac=12)
def test_submitting_someone_elses_request_is_refused(client):
    client.login(Users.ORGANISER)
    created = client.post("/events", json=_complete_payload()).json()
    client.login(Users.ORGANISER_2)

    response = client.post(f"/events/{created['id']}/submit")

    assert response.status_code == 403


@pytest.mark.story("2.1", ac=12)
def test_submitting_an_already_submitted_request_is_refused(organiser_client):
    created = organiser_client.post("/events", json=_complete_payload()).json()
    first = organiser_client.post(f"/events/{created['id']}/submit")
    assert first.status_code == 200

    second = organiser_client.post(f"/events/{created['id']}/submit")

    assert second.status_code == 409


@pytest.mark.story("2.1", ac=9)
def test_submitting_a_missing_event_is_404(organiser_client):
    response = organiser_client.post("/events/00000000-0000-0000-0000-000000000000/submit")
    assert response.status_code == 404
