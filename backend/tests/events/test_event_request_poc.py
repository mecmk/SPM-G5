"""Story 2.1 - be: the point of contact (POC) on an event request (AC13, added after customer
feedback).

AC13 The organiser records a POC name, email and phone on the request. All three are optional
     when saving a draft and all three are required to submit, so a refused submission names
     each one that is missing. The email must be an address (at most 254 characters) and the
     phone 8-15 digits with an optional leading "+" and spaces or dashes (at most 50
     characters); the name is at most 200 characters. The POC can be edited while the request is
     a draft and not once it is submitted. Reviewing internal roles see it on a submitted
     request; a draft is visible only to its organiser.

The form's as-you-type messages and the "still needed" list are e2e cases:
tests/e2e/event-request.spec.ts. Submitting in general is test_event_request_submission.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.support.factories import (
    create_event_request,
    create_submittable_event_request,
    event_request_payload,
)
from tests.support.seed import Users

POC = {
    "contact_name": "Priya Nair",
    "contact_email": "priya.nair@example.com",
    "contact_phone": "+65 9123 4567",
}
# Each thing the submit gate requires of the POC: how the refusal names it, and how to leave just
# that one out of an otherwise submittable request.
REQUIRED = {
    "contact_name": ("point of contact name", {"contact_name": None}),
    "contact_email": ("point of contact email", {"contact_email": None}),
    "contact_phone": ("point of contact phone number", {"contact_phone": None}),
}
NON_ORGANISERS = [
    pytest.param(Users.COORDINATOR, id="coordinator"),
    pytest.param(Users.VENUE_STAFF, id="venue-staff"),
    pytest.param(Users.TECH_SUPPORT, id="tech-support"),
    pytest.param(Users.ATTENDEE, id="attendee"),
]
_LOCAL_PART = "a" * 64
# 254 characters in all: the longest address the column and the form both allow.
_LONGEST_EMAIL = f"{_LOCAL_PART}@{'b' * 63}.{'c' * 63}.{'d' * 57}.com"


def _create(client, **overrides):
    return client.post("/events", json=event_request_payload(**overrides))


def _submit(client, event_id):
    return client.post(f"/events/{event_id}/submit")


def _stored_poc(db: Session, event_id) -> tuple[str | None, str | None, str | None]:
    row = db.execute(
        text("SELECT contact_name, contact_email, contact_phone FROM events WHERE id = :id"),
        {"id": str(event_id)},
    ).one()
    return row.contact_name, row.contact_email, row.contact_phone


# --- AC13: recording it -------------------------------------------------------------------------
@pytest.mark.story("2.1", ac=13)
def test_a_new_request_records_the_poc(organiser_client, db: Session):
    response = _create(organiser_client, **POC)

    assert response.status_code == 201, response.text
    body = response.json()
    assert {key: body[key] for key in POC} == POC
    assert _stored_poc(db, body["id"]) == tuple(POC.values())


@pytest.mark.story("2.1", ac=13)
def test_a_draft_saves_without_any_poc(organiser_client):
    response = organiser_client.post("/events", json={"name": "Name only"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["contact_name"], body["contact_email"], body["contact_phone"]) == (
        None,
        None,
        None,
    )


@pytest.mark.story("2.1", ac=13)
def test_a_draft_saves_with_only_part_of_the_poc(organiser_client):
    response = _create(organiser_client, contact_email=POC["contact_email"])

    assert response.status_code == 201, response.text
    assert response.json()["contact_email"] == POC["contact_email"]
    assert response.json()["contact_phone"] is None


@pytest.mark.story("2.1", ac=13)
def test_editing_a_draft_changes_the_poc(organiser_client):
    created = create_event_request(organiser_client, **POC)

    response = organiser_client.patch(
        f"/events/{created['id']}", json={"contact_phone": "91234567"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["contact_phone"] == "91234567"
    assert response.json()["contact_email"] == POC["contact_email"]


@pytest.mark.story("2.1", ac=13)
def test_editing_other_details_leaves_the_poc_alone(organiser_client):
    created = create_event_request(organiser_client, **POC)

    response = organiser_client.patch(f"/events/{created['id']}", json={"name": "Renamed"})

    assert response.status_code == 200, response.text
    assert {key: response.json()[key] for key in POC} == POC


@pytest.mark.story("2.1", ac=13)
def test_an_optional_poc_field_can_be_cleared_on_a_draft(organiser_client):
    created = create_event_request(organiser_client, **POC)

    response = organiser_client.patch(f"/events/{created['id']}", json={"contact_phone": None})

    assert response.status_code == 200, response.text
    assert response.json()["contact_phone"] is None


@pytest.mark.story("2.1", ac=13)
def test_surrounding_spaces_are_trimmed_and_blank_counts_as_not_given(organiser_client):
    response = _create(
        organiser_client,
        contact_name="  Priya Nair  ",
        contact_email="  priya.nair@example.com ",
        contact_phone="   ",
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["contact_name"] == "Priya Nair"
    assert body["contact_email"] == "priya.nair@example.com"
    assert body["contact_phone"] is None


# --- AC13: the values are checked --------------------------------------------------------------
@pytest.mark.story("2.1", ac=13)
@pytest.mark.parametrize(
    "email",
    ["plainaddress", "missing-at.example.com", "@example.com", "a@", "a b@example.com", "a@b"],
)
def test_a_malformed_email_is_refused(organiser_client, email):
    response = _create(organiser_client, contact_email=email)

    assert response.status_code == 422
    assert "email" in response.text.lower()


@pytest.mark.story("2.1", ac=13)
@pytest.mark.parametrize(
    "phone", ["not a number", "9123-abcd", "12345", "1234567", "+65 (9123) 4567", "91234567x"]
)
def test_a_malformed_phone_is_refused(organiser_client, phone):
    response = _create(organiser_client, contact_phone=phone)

    assert response.status_code == 422
    assert "phone" in response.text.lower()


@pytest.mark.story("2.1", ac=13)
@pytest.mark.parametrize(
    "phone", ["91234567", "9123 4567", "9123-4567", "+6591234567", "+65 9123 4567", "1" * 15]
)
def test_the_phone_formats_people_type_are_accepted(organiser_client, phone):
    response = _create(organiser_client, contact_phone=phone)

    assert response.status_code == 201, response.text
    assert response.json()["contact_phone"] == phone


@pytest.mark.story("2.1", ac=13)
def test_the_phone_length_boundaries(organiser_client):
    assert _create(organiser_client, contact_phone="1" * 7).status_code == 422
    assert _create(organiser_client, contact_phone="1" * 8).status_code == 201
    assert _create(organiser_client, contact_phone="1" * 15).status_code == 201
    assert _create(organiser_client, contact_phone="1" * 16).status_code == 422


@pytest.mark.story("2.1", ac=13)
def test_the_phone_field_is_capped_at_50_characters(organiser_client):
    assert _create(organiser_client, contact_phone="1" + " " * 48 + "1").status_code == 422
    assert _create(organiser_client, contact_phone="1" * 51).status_code == 422


@pytest.mark.story("2.1", ac=13)
def test_the_name_boundaries(organiser_client):
    assert _create(organiser_client, contact_name="n" * 200).status_code == 201
    assert _create(organiser_client, contact_name="n" * 201).status_code == 422


@pytest.mark.story("2.1", ac=13)
def test_the_email_boundaries(organiser_client):
    assert len(_LONGEST_EMAIL) == 254
    assert _create(organiser_client, contact_email=_LONGEST_EMAIL).status_code == 201
    assert _create(organiser_client, contact_email="e" + _LONGEST_EMAIL).status_code == 422


@pytest.mark.story("2.1", ac=13)
def test_a_refused_edit_leaves_the_stored_poc_unchanged(organiser_client, db: Session):
    created = create_event_request(organiser_client, **POC)

    response = organiser_client.patch(
        f"/events/{created['id']}", json={"contact_email": "not-an-email"}
    )

    assert response.status_code == 422
    assert _stored_poc(db, created["id"]) == tuple(POC.values())


# --- AC13: needed to submit --------------------------------------------------------------------
@pytest.mark.story("2.1", ac=13)
def test_a_request_with_a_full_poc_submits(organiser_client):
    created = create_submittable_event_request(organiser_client, **POC)

    assert _submit(organiser_client, created["id"]).status_code == 200


@pytest.mark.story("2.1", ac=13)
@pytest.mark.parametrize("missing", list(REQUIRED))
def test_each_missing_poc_item_is_named_and_refused(organiser_client, db: Session, missing):
    label, leave_out = REQUIRED[missing]
    created = create_submittable_event_request(organiser_client, **{**POC, **leave_out})

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 422
    detail = response.text.lower()
    assert label in detail
    for other, (other_label, _) in REQUIRED.items():
        if other != missing:
            assert other_label not in detail, f"{other_label} was given but is named as missing"
    assert (
        db.execute(
            text("SELECT status FROM events WHERE id = :id"), {"id": created["id"]}
        ).scalar_one()
        == "DRAFT"
    )


@pytest.mark.story("2.1", ac=13)
def test_every_missing_poc_item_is_named_together(organiser_client):
    created = create_submittable_event_request(
        organiser_client, contact_name=None, contact_email=None, contact_phone=None
    )

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 422
    assert all(label in response.text.lower() for label, _ in REQUIRED.values())


@pytest.mark.story("2.1", ac=13)
def test_the_poc_is_named_alongside_other_missing_details(organiser_client):
    created = create_event_request(organiser_client, purpose=None, **POC)
    organiser_client.patch(f"/events/{created['id']}", json={"contact_email": None})

    response = _submit(organiser_client, created["id"])

    detail = response.text.lower()
    assert response.status_code == 422
    assert "purpose" in detail
    assert "point of contact email" in detail


@pytest.mark.story("2.1", ac=13)
def test_a_refused_submission_keeps_the_poc_saved_on_the_draft(organiser_client):
    created = create_submittable_event_request(organiser_client, **{**POC, "contact_phone": None})

    assert _submit(organiser_client, created["id"]).status_code == 422

    kept = organiser_client.get(f"/events/{created['id']}").json()
    assert kept["status"] == "DRAFT"
    assert kept["contact_name"] == POC["contact_name"]
    assert kept["contact_email"] == POC["contact_email"]


# --- AC13: once submitted ----------------------------------------------------------------------
@pytest.mark.story("2.1", ac=13)
@pytest.mark.parametrize("field", list(POC))
def test_a_submitted_request_refuses_a_poc_edit(organiser_client, db: Session, field):
    created = create_submittable_event_request(organiser_client, **POC)
    assert _submit(organiser_client, created["id"]).status_code == 200

    changed = {
        "contact_name": "Someone Else",
        "contact_email": "someone.else@example.com",
        "contact_phone": "99999999",
    }

    response = organiser_client.patch(f"/events/{created['id']}", json={field: changed[field]})

    assert response.status_code == 409
    assert _stored_poc(db, created["id"]) == tuple(POC.values())


# --- AC13: who can write it, who can read it ---------------------------------------------------
@pytest.mark.story("2.1", ac=13)
@pytest.mark.parametrize("user", NON_ORGANISERS)
def test_only_an_organiser_can_record_a_poc(login_as, user):
    assert _create(login_as(user), **POC).status_code == 403


@pytest.mark.story("2.1", ac=13)
def test_recording_a_poc_requires_sign_in(client):
    assert _create(client, **POC).status_code == 401


@pytest.mark.story("2.1", ac=13)
def test_an_organiser_cannot_edit_the_poc_of_someone_elses_request(login_as, db: Session):
    created = create_event_request(login_as(Users.ORGANISER), **POC)

    response = login_as(Users.ORGANISER_2).patch(
        f"/events/{created['id']}", json={"contact_phone": "91234567"}
    )

    assert response.status_code == 404
    assert _stored_poc(db, created["id"]) == tuple(POC.values())


@pytest.mark.story("2.1", ac=13)
def test_the_coordinator_sees_the_poc_of_a_submitted_request(login_as):
    created = create_submittable_event_request(login_as(Users.ORGANISER), **POC)
    assert _submit(login_as(Users.ORGANISER), created["id"]).status_code == 200

    response = login_as(Users.COORDINATOR).get(f"/events/{created['id']}")

    assert response.status_code == 200, response.text
    assert {key: response.json()[key] for key in POC} == POC


@pytest.mark.story("2.1", ac=13)
def test_the_coordinator_cannot_see_the_poc_of_a_draft(login_as):
    created = create_event_request(login_as(Users.ORGANISER), **POC)

    assert login_as(Users.COORDINATOR).get(f"/events/{created['id']}").status_code == 404
