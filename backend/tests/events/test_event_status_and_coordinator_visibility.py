"""Story 2.6 (ACs 10-16, added per product owner decision) - be: the status shown on an
organiser's own request, and who the assigned coordinator is.

AC10 The status GET /events/{id} returns for a request is the same one GET /events/mine already
     showed for it (AC1) - both read ``events.status`` directly, so they cannot disagree.
AC11 (status tab filtering on the list) is a client-side filter over data AC1 already proves, no
     backend case of its own: tests/e2e/my-event-requests.spec.ts.
AC12 Opening a non-draft request's details also returns the assigned coordinator's name and
     email.
AC13 A draft has no coordinator; neither does a submitted request nobody has assigned yet - the
     API returns null either way, so the frontend tells the two apart using ``status``, not two
     different encodings of "no coordinator".
AC14 After a reassignment, the next read reflects the new coordinator.
AC15 The coordinator's name and email reach only the owning organiser and internal roles -
     anyone else cannot read the event at all (2.1 AC8), so they never reach this payload either.
AC16 A reassignment leaves no trace of the previous coordinator on a later read.

A separate story (6.1) covers status display for the coordinator's own list, and elsewhere any
role can see an event's status - this file covers only the organiser's own list/detail flow.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.events.models import EventStatus
from tests.support.factories import create_event_request, make_event
from tests.support.seed import Events, Users

MY_EVENTS_PATH = "/events/mine"


# --- AC10: the list and the details endpoint agree on status -----------------------------------
@pytest.mark.story("2.6", ac=10)
def test_the_list_and_the_details_endpoint_report_the_same_status(organiser_client):
    created = create_event_request(organiser_client)

    listed = organiser_client.get(MY_EVENTS_PATH).json()["items"]
    entry = next(item for item in listed if item["id"] == created["id"])
    detail = organiser_client.get(f"/events/{created['id']}").json()

    assert entry["status"] == detail["status"] == "DRAFT"


# --- AC12: the assigned coordinator's name and email are both returned -------------------------
@pytest.mark.story("2.6", ac=12)
def test_event_details_include_the_assigned_coordinators_name_and_email(
    coordinator_client, login_as
):
    coordinator_client.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    organiser = login_as(Users.ORGANISER)
    response = organiser.get(f"/events/{Events.SUBMITTED}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assigned_coordinator_name"] == Users.COORDINATOR_2.full_name
    assert body["assigned_coordinator_email"] == Users.COORDINATOR_2.email


# --- AC13: no coordinator looks the same whether it is a draft or an unassigned submission ------
@pytest.mark.story("2.6", ac=13)
def test_no_coordinator_is_null_whether_draft_or_unassigned_submission(
    organiser_client, db: Session
):
    draft = create_event_request(organiser_client)
    unassigned = make_event(
        db,
        status=EventStatus.UNDER_REVIEW,
        organiser_id=Users.ORGANISER.id,
        assigned_coordinator_id=None,
    )

    unassigned_body = organiser_client.get(f"/events/{unassigned.id}").json()

    assert draft["assigned_coordinator_id"] is None
    assert draft["assigned_coordinator_name"] is None
    assert draft["assigned_coordinator_email"] is None
    assert unassigned_body["assigned_coordinator_id"] is None
    assert unassigned_body["assigned_coordinator_name"] is None
    assert unassigned_body["assigned_coordinator_email"] is None
    # the API does not distinguish them - the frontend must use `status` to tell "not applicable
    # yet" (DRAFT) apart from "not yet assigned" (anything else)
    assert draft["status"] != unassigned_body["status"]


# --- AC14: a reassignment is reflected on the next read -----------------------------------------
@pytest.mark.story("2.6", ac=14)
def test_a_reassignment_is_reflected_on_the_next_read(login_as):
    # `login_as` re-signs-in the one shared test client each time, so every actor switch in this
    # test goes through it - mixing it with a separately-fixtured client (e.g. `coordinator_client`)
    # would log that other client out from under itself.
    organiser = login_as(Users.ORGANISER)
    before = organiser.get(f"/events/{Events.SUBMITTED}").json()
    assert before["assigned_coordinator_name"] == Users.COORDINATOR.full_name  # seeded default

    coordinator = login_as(Users.COORDINATOR)
    coordinator.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    organiser = login_as(Users.ORGANISER)
    after = organiser.get(f"/events/{Events.SUBMITTED}").json()
    assert after["assigned_coordinator_name"] == Users.COORDINATOR_2.full_name


# --- AC15: only the owning organiser and internal roles ever see it -----------------------------
@pytest.mark.story("2.6", ac=15)
def test_an_uninvolved_organiser_cannot_read_the_coordinator_fields(login_as):
    # Events.SUBMITTED belongs to Users.ORGANISER, not ORGANISER_2 - the whole record is refused,
    # coordinator fields included, matching 2.1 AC8's "not found" for anyone unrelated.
    response = login_as(Users.ORGANISER_2).get(f"/events/{Events.SUBMITTED}")

    assert response.status_code == 404


@pytest.mark.story("2.6", ac=15)
def test_an_attendee_cannot_read_the_coordinator_fields(attendee_client):
    response = attendee_client.get(f"/events/{Events.SUBMITTED}")

    assert response.status_code == 403


# --- AC16: a reassignment leaves no trace of the previous coordinator ---------------------------
@pytest.mark.story("2.6", ac=16)
def test_a_reassignment_leaves_no_trace_of_the_previous_coordinator(coordinator_client, login_as):
    coordinator_client.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR.id)},
    )
    coordinator_client.put(
        f"/events/{Events.SUBMITTED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    organiser = login_as(Users.ORGANISER)
    body = organiser.get(f"/events/{Events.SUBMITTED}").json()

    assert body["assigned_coordinator_id"] == str(Users.COORDINATOR_2.id)
    assert body["assigned_coordinator_name"] == Users.COORDINATOR_2.full_name
    assert body["assigned_coordinator_email"] == Users.COORDINATOR_2.email
    assert Users.COORDINATOR.full_name not in str(body)
    assert Users.COORDINATOR.email not in str(body)
