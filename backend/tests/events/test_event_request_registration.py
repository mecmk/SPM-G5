"""Story 2.1 - the registration requirement on an event request (AC17, AC18; merged in from a
former standalone story 2.2 after product review).

AC17 The organiser can mark Registration required: Yes or No. Choosing Yes reveals a
     registration opening date/time and a registration closing date/time; choosing No hides both
     and stores nothing for them - defaults to not set and is not required to save a draft. The
     opening date is optional: left blank, registration opens immediately once the event is
     approved. When given, it must be in the future, no later than the closing date, and no later
     than the proposed start. The closing date must be in the future, no later than the proposed
     start, and not before the opening date (when given) - equal to the start is accepted for
     either, one minute after is refused. Registration capacity is not a separate field: it is
     always the event's expected attendance (AC3).

AC18 If an edit to the proposed start would move it to before a saved registration opening date
     or closing date, the update is refused, naming the conflict, and the dates stay as they
     were. A start moved to exactly the same moment as either date is accepted.

The form's checkbox, as-you-type messages and confirm-to-clear dialog are e2e cases:
tests/e2e/event-request.spec.ts. Submitting in general is test_event_request_submission.py.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.support.factories import (
    create_event_request,
    create_submittable_event_request,
    event_request_payload,
    future_datetime,
)
from tests.support.seed import Users

NON_ORGANISERS = [
    pytest.param(Users.COORDINATOR, id="coordinator"),
    pytest.param(Users.VENUE_STAFF, id="venue-staff"),
    pytest.param(Users.TECH_SUPPORT, id="tech-support"),
    pytest.param(Users.ATTENDEE, id="attendee"),
]


def _create(client, **overrides):
    return client.post("/events", json=event_request_payload(**overrides))


def _submit(client, event_id):
    return client.post(f"/events/{event_id}/submit")


def _stored_registration(db: Session, event_id) -> tuple[bool, object]:
    row = db.execute(
        text("SELECT registration_required, registration_closes_at FROM events WHERE id = :id"),
        {"id": str(event_id)},
    ).one()
    return row.registration_required, row.registration_closes_at


# --- AC17: recording the choice --------------------------------------------------------------
@pytest.mark.story("2.1", ac=17)
def test_a_draft_defaults_to_registration_not_required(organiser_client):
    response = organiser_client.post("/events", json={"name": "Name only"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["registration_required"] is False
    assert body["registration_closes_at"] is None


@pytest.mark.story("2.1", ac=17)
def test_a_request_records_registration_required_and_a_closing_date(organiser_client, db: Session):
    starts_at = future_datetime(days=30)
    closes_at = starts_at - timedelta(days=1)
    response = _create(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_closes_at=closes_at.isoformat(),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["registration_required"] is True
    assert body["registration_closes_at"] is not None
    assert _stored_registration(db, body["id"])[0] is True


@pytest.mark.story("2.1", ac=17)
def test_registration_required_can_be_saved_yes_without_a_closing_date_on_a_draft(
    organiser_client,
):
    response = _create(organiser_client, registration_required=True)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["registration_required"] is True
    assert body["registration_closes_at"] is None


@pytest.mark.story("2.1", ac=17)
def test_capacity_is_not_a_field_the_client_can_set(organiser_client):
    response = _create(organiser_client, registration_capacity=999)

    assert response.status_code == 422


# --- AC17: the closing date is checked -------------------------------------------------------
@pytest.mark.story("2.1", ac=17)
def test_a_closing_date_equal_to_the_start_is_accepted(organiser_client):
    starts_at = future_datetime(days=30)
    response = _create(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_closes_at=starts_at.isoformat(),
    )

    assert response.status_code == 201, response.text


@pytest.mark.story("2.1", ac=17)
def test_a_closing_date_one_minute_after_the_start_is_refused(organiser_client):
    starts_at = future_datetime(days=30)
    response = _create(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_closes_at=(starts_at + timedelta(minutes=1)).isoformat(),
    )

    assert response.status_code == 422
    assert "registration" in response.text.lower()


@pytest.mark.story("2.1", ac=17)
def test_a_closing_date_in_the_past_is_refused(organiser_client):
    starts_at = future_datetime(days=30)
    response = _create(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_closes_at="2020-01-01T00:00:00+08:00",
    )

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=17)
def test_a_closing_date_is_refused_when_registration_is_not_required(organiser_client):
    starts_at = future_datetime(days=30)
    response = _create(
        organiser_client,
        starts_at=starts_at.isoformat(),
        registration_required=False,
        registration_closes_at=starts_at.isoformat(),
    )

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=17)
def test_a_malformed_closing_date_is_refused(organiser_client):
    response = _create(organiser_client, registration_required=True, registration_closes_at="soon")

    assert response.status_code == 422


# --- AC17: the opening date is checked ---------------------------------------------------------
@pytest.mark.story("2.1", ac=17)
def test_registration_required_can_include_an_opening_date(organiser_client):
    starts_at = future_datetime(days=30)
    response = _create(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_opens_at=future_datetime(days=1).isoformat(),
        registration_closes_at=starts_at.isoformat(),
    )

    assert response.status_code == 201, response.text
    assert response.json()["registration_opens_at"] is not None


@pytest.mark.story("2.1", ac=17)
def test_the_opening_date_is_optional(organiser_client):
    starts_at = future_datetime(days=30)
    response = _create(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_closes_at=starts_at.isoformat(),
    )

    assert response.status_code == 201, response.text
    assert response.json()["registration_opens_at"] is None


@pytest.mark.story("2.1", ac=17)
def test_an_opening_date_after_the_closing_date_is_refused(organiser_client):
    starts_at = future_datetime(days=30)
    response = _create(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_opens_at=starts_at.isoformat(),
        registration_closes_at=future_datetime(days=1).isoformat(),
    )

    assert response.status_code == 422
    assert "open" in response.text.lower()


@pytest.mark.story("2.1", ac=17)
def test_an_opening_date_equal_to_the_closing_date_is_refused(organiser_client):
    """The registration window must have positive width - matches the database's own
    ``ck_events_registration_window``, checked here first for a proper message."""
    starts_at = future_datetime(days=30)
    response = _create(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_opens_at=starts_at.isoformat(),
        registration_closes_at=starts_at.isoformat(),
    )

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=17)
def test_an_opening_date_after_the_start_is_refused(organiser_client):
    starts_at = future_datetime(days=30)
    response = _create(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_opens_at=(starts_at + timedelta(minutes=1)).isoformat(),
    )

    assert response.status_code == 422
    assert "open" in response.text.lower()


@pytest.mark.story("2.1", ac=17)
def test_an_opening_date_equal_to_the_start_is_accepted(organiser_client):
    """No closing date on this one: an opening date equal to the closing date would fail the
    database's own ``ck_events_registration_window`` (the window must have positive width), and
    since the closing date can be no later than the start, an opening date exactly at the start
    can only coexist with no closing date at all."""
    starts_at = future_datetime(days=30)
    response = _create(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_opens_at=starts_at.isoformat(),
    )

    assert response.status_code == 201, response.text


@pytest.mark.story("2.1", ac=17)
def test_an_opening_date_in_the_past_is_refused(organiser_client):
    starts_at = future_datetime(days=30)
    response = _create(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_opens_at="2020-01-01T00:00:00+08:00",
        registration_closes_at=starts_at.isoformat(),
    )

    assert response.status_code == 422


# --- AC18: moving the start against a saved opening date ----------------------------------------
# No closing date on these: an opening date this close to the start can only coexist with no
# closing date, for the same reason as test_an_opening_date_equal_to_the_start_is_accepted.
@pytest.mark.story("2.1", ac=18)
def test_moving_the_start_to_before_a_saved_opening_date_is_refused(organiser_client):
    starts_at = future_datetime(days=30)
    created = create_event_request(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_opens_at=starts_at.isoformat(),
    )
    earlier_start = starts_at - timedelta(minutes=1)

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={
            "starts_at": earlier_start.isoformat(),
            "ends_at": (earlier_start + timedelta(hours=8)).isoformat(),
        },
    )

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=18)
def test_moving_the_start_to_exactly_a_saved_opening_date_is_accepted(organiser_client):
    starts_at = future_datetime(days=30)
    created = create_event_request(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_opens_at=starts_at.isoformat(),
    )

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={
            "starts_at": starts_at.isoformat(),
            "ends_at": (starts_at + timedelta(hours=8)).isoformat(),
        },
    )

    assert response.status_code == 200, response.text


# --- AC17: editing on a draft -----------------------------------------------------------------
@pytest.mark.story("2.1", ac=17)
def test_switching_to_yes_with_a_closing_date_is_accepted(organiser_client):
    created = create_event_request(organiser_client)
    starts_at_str = created["starts_at"]

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={"registration_required": True, "registration_closes_at": starts_at_str},
    )

    assert response.status_code == 200, response.text
    assert response.json()["registration_required"] is True


@pytest.mark.story("2.1", ac=17)
def test_switching_to_no_while_a_closing_date_is_still_sent_is_refused(organiser_client):
    created = create_event_request(organiser_client)
    starts_at_str = created["starts_at"]
    organiser_client.patch(
        f"/events/{created['id']}",
        json={"registration_required": True, "registration_closes_at": starts_at_str},
    )

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={"registration_required": False, "registration_closes_at": starts_at_str},
    )

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=17)
def test_switching_to_no_and_clearing_the_closing_date_together_is_accepted(organiser_client):
    created = create_event_request(organiser_client)
    starts_at_str = created["starts_at"]
    organiser_client.patch(
        f"/events/{created['id']}",
        json={"registration_required": True, "registration_closes_at": starts_at_str},
    )

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={"registration_required": False, "registration_closes_at": None},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["registration_required"] is False
    assert body["registration_closes_at"] is None


@pytest.mark.story("2.1", ac=17)
def test_sending_null_for_registration_required_is_refused(organiser_client):
    created = create_event_request(organiser_client)

    response = organiser_client.patch(
        f"/events/{created['id']}", json={"registration_required": None}
    )

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=17)
def test_a_refused_edit_leaves_stored_registration_unchanged(organiser_client, db: Session):
    starts_at = future_datetime(days=30)
    created = create_event_request(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_closes_at=starts_at.isoformat(),
    )

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={"registration_closes_at": (starts_at + timedelta(minutes=1)).isoformat()},
    )

    assert response.status_code == 422
    required, closes_at = _stored_registration(db, created["id"])
    assert required is True
    assert closes_at is not None


# --- AC18: moving the start against a saved closing date --------------------------------------
@pytest.mark.story("2.1", ac=18)
def test_moving_the_start_to_exactly_the_closing_date_is_accepted(organiser_client):
    starts_at = future_datetime(days=30)
    created = create_event_request(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_closes_at=starts_at.isoformat(),
    )

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={
            "starts_at": starts_at.isoformat(),
            "ends_at": (starts_at + timedelta(hours=8)).isoformat(),
        },
    )

    assert response.status_code == 200, response.text


@pytest.mark.story("2.1", ac=18)
def test_moving_the_start_to_before_the_closing_date_is_refused(organiser_client, db: Session):
    starts_at = future_datetime(days=30)
    created = create_event_request(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_closes_at=starts_at.isoformat(),
    )
    earlier_start = starts_at - timedelta(minutes=1)

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={
            "starts_at": earlier_start.isoformat(),
            "ends_at": (earlier_start + timedelta(hours=8)).isoformat(),
        },
    )

    assert response.status_code == 422
    assert "registration" in response.text.lower()
    required, closes_at = _stored_registration(db, created["id"])
    assert closes_at is not None


@pytest.mark.story("2.1", ac=18)
def test_moving_the_start_earlier_and_the_closing_date_in_the_same_edit_is_accepted(
    organiser_client,
):
    starts_at = future_datetime(days=30)
    created = create_event_request(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_closes_at=starts_at.isoformat(),
    )
    earlier_start = starts_at - timedelta(days=1)

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={
            "starts_at": earlier_start.isoformat(),
            "ends_at": (earlier_start + timedelta(hours=8)).isoformat(),
            "registration_closes_at": earlier_start.isoformat(),
        },
    )

    assert response.status_code == 200, response.text


@pytest.mark.story("2.1", ac=18)
def test_editing_unrelated_fields_does_not_re_check_a_stale_closing_date(
    organiser_client, db: Session
):
    """Same principle as AC2: a value already saved is not re-rejected just because something
    unrelated is edited. A closing date that has since passed (time alone, nothing touched it)
    must not block saving an unrelated field."""
    starts_at = future_datetime(days=30)
    created = create_event_request(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_closes_at=starts_at.isoformat(),
    )
    db.execute(
        text("UPDATE events SET registration_closes_at = now() - interval '2 days' WHERE id = :id"),
        {"id": created["id"]},
    )
    db.expire_all()

    response = organiser_client.patch(f"/events/{created['id']}", json={"purpose": "Updated"})

    assert response.status_code == 200, response.text


# --- AC10/AC17: needed to submit ---------------------------------------------------------------
@pytest.mark.story("2.1", ac=17)
def test_registration_required_without_a_closing_date_cannot_be_submitted(organiser_client):
    created = create_submittable_event_request(organiser_client, registration_required=True)

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 422
    assert "registration closing date" in response.text.lower()


@pytest.mark.story("2.1", ac=17)
def test_registration_not_required_submits_without_a_closing_date(organiser_client):
    created = create_submittable_event_request(organiser_client, registration_required=False)

    assert _submit(organiser_client, created["id"]).status_code == 200


@pytest.mark.story("2.1", ac=17)
def test_registration_required_with_a_closing_date_submits(organiser_client):
    starts_at = future_datetime(days=30)
    created = create_submittable_event_request(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_closes_at=starts_at.isoformat(),
    )

    assert _submit(organiser_client, created["id"]).status_code == 200


@pytest.mark.story("2.1", ac=17)
def test_a_closing_date_that_has_since_passed_cannot_be_submitted(organiser_client, db: Session):
    """Same principle as AC2's start date: a closing date valid when saved but now in the past
    blocks submission, even though nothing touched it since."""
    starts_at = future_datetime(days=30)
    created = create_submittable_event_request(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_closes_at=starts_at.isoformat(),
    )
    db.execute(
        text("UPDATE events SET registration_closes_at = now() - interval '2 days' WHERE id = :id"),
        {"id": created["id"]},
    )
    db.expire_all()

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 422
    assert (
        db.execute(
            text("SELECT status FROM events WHERE id = :id"), {"id": created["id"]}
        ).scalar_one()
        == "DRAFT"
    )


# --- AC8/AC17: visibility -----------------------------------------------------------------------
@pytest.mark.story("2.1", ac=17)
def test_the_coordinator_sees_the_registration_choice_of_a_submitted_request(login_as):
    starts_at = future_datetime(days=30)
    created = create_submittable_event_request(
        login_as(Users.ORGANISER),
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_closes_at=starts_at.isoformat(),
    )
    assert _submit(login_as(Users.ORGANISER), created["id"]).status_code == 200

    response = login_as(Users.COORDINATOR).get(f"/events/{created['id']}")

    assert response.status_code == 200, response.text
    assert response.json()["registration_required"] is True
    assert response.json()["registration_closes_at"] is not None


@pytest.mark.story("2.1", ac=17)
def test_the_coordinator_cannot_see_the_registration_choice_of_a_draft(login_as):
    created = create_event_request(login_as(Users.ORGANISER), registration_required=True)

    assert login_as(Users.COORDINATOR).get(f"/events/{created['id']}").status_code == 404


# --- AC17: once submitted -----------------------------------------------------------------------
@pytest.mark.story("2.1", ac=17)
def test_a_submitted_request_refuses_a_registration_edit(organiser_client, db: Session):
    starts_at = future_datetime(days=30)
    created = create_submittable_event_request(
        organiser_client,
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
        registration_required=True,
        registration_closes_at=starts_at.isoformat(),
    )
    assert _submit(organiser_client, created["id"]).status_code == 200

    response = organiser_client.patch(
        f"/events/{created['id']}", json={"registration_required": False}
    )

    assert response.status_code == 409
    assert _stored_registration(db, created["id"])[0] is True


# --- AC17: who can write it -----------------------------------------------------------------
@pytest.mark.story("2.1", ac=17)
@pytest.mark.parametrize("user", NON_ORGANISERS)
def test_only_an_organiser_can_set_registration_required(login_as, user):
    assert _create(login_as(user), registration_required=True).status_code == 403


@pytest.mark.story("2.1", ac=17)
def test_an_organiser_cannot_edit_the_registration_choice_of_someone_elses_request(
    login_as, db: Session
):
    created = create_event_request(login_as(Users.ORGANISER), registration_required=False)

    response = login_as(Users.ORGANISER_2).patch(
        f"/events/{created['id']}", json={"registration_required": True}
    )

    assert response.status_code == 404
    assert _stored_registration(db, created["id"])[0] is False
