"""Story 2.1 - event visibility on an event request (AC19, added after product review).

AC19 The organiser can mark the event's visibility: Public or Private, a two-way choice shown as
     its own control. It defaults to Private until changed, and is not required to save a draft
     or to submit. It is recorded with the request, shown to the reviewing Event Coordinator once
     submitted (AC8), and editable only while the request is a draft (AC7). This AC only captures
     and displays the choice - no public listing page or link-sharing mechanism exists yet.
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


def _stored_is_public(db: Session, event_id) -> bool:
    return db.execute(
        text("SELECT is_public FROM events WHERE id = :id"), {"id": str(event_id)}
    ).scalar_one()


# --- AC19: recording it --------------------------------------------------------------------
@pytest.mark.story("2.1", ac=19)
def test_a_draft_defaults_to_private(organiser_client):
    response = organiser_client.post("/events", json={"name": "Name only"})

    assert response.status_code == 201, response.text
    assert response.json()["is_public"] is False


@pytest.mark.story("2.1", ac=19)
def test_a_request_can_be_marked_public(organiser_client, db: Session):
    response = _create(organiser_client, is_public=True)

    assert response.status_code == 201, response.text
    assert response.json()["is_public"] is True
    assert _stored_is_public(db, response.json()["id"]) is True


@pytest.mark.story("2.1", ac=19)
def test_editing_a_draft_changes_the_visibility(organiser_client):
    created = create_event_request(organiser_client, is_public=False)

    response = organiser_client.patch(f"/events/{created['id']}", json={"is_public": True})

    assert response.status_code == 200, response.text
    assert response.json()["is_public"] is True


@pytest.mark.story("2.1", ac=19)
def test_editing_other_details_leaves_the_visibility_alone(organiser_client):
    created = create_event_request(organiser_client, is_public=True)

    response = organiser_client.patch(f"/events/{created['id']}", json={"name": "Renamed"})

    assert response.status_code == 200, response.text
    assert response.json()["is_public"] is True


@pytest.mark.story("2.1", ac=19)
def test_sending_null_for_is_public_is_refused(organiser_client):
    created = create_event_request(organiser_client)

    response = organiser_client.patch(f"/events/{created['id']}", json={"is_public": None})

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=19)
def test_visibility_is_not_needed_to_submit(organiser_client):
    created = create_submittable_event_request(organiser_client)

    assert _submit(organiser_client, created["id"]).status_code == 200


# --- AC19: once submitted -------------------------------------------------------------------
@pytest.mark.story("2.1", ac=19)
def test_a_submitted_request_refuses_a_visibility_edit(organiser_client, db: Session):
    created = create_submittable_event_request(organiser_client, is_public=True)
    assert _submit(organiser_client, created["id"]).status_code == 200

    response = organiser_client.patch(f"/events/{created['id']}", json={"is_public": False})

    assert response.status_code == 409
    assert _stored_is_public(db, created["id"]) is True


# --- AC19/AC8: who can write it, who can read it --------------------------------------------
@pytest.mark.story("2.1", ac=19)
@pytest.mark.parametrize("user", NON_ORGANISERS)
def test_only_an_organiser_can_set_visibility(login_as, user):
    assert _create(login_as(user), is_public=True).status_code == 403


@pytest.mark.story("2.1", ac=19)
def test_an_organiser_cannot_edit_the_visibility_of_someone_elses_request(login_as, db: Session):
    created = create_event_request(login_as(Users.ORGANISER), is_public=False)

    response = login_as(Users.ORGANISER_2).patch(
        f"/events/{created['id']}", json={"is_public": True}
    )

    assert response.status_code == 404
    assert _stored_is_public(db, created["id"]) is False


@pytest.mark.story("2.1", ac=19)
def test_the_coordinator_sees_the_visibility_of_a_submitted_request(login_as):
    created = create_submittable_event_request(login_as(Users.ORGANISER), is_public=True)
    assert _submit(login_as(Users.ORGANISER), created["id"]).status_code == 200

    response = login_as(Users.COORDINATOR).get(f"/events/{created['id']}")

    assert response.status_code == 200, response.text
    assert response.json()["is_public"] is True


@pytest.mark.story("2.1", ac=19)
def test_the_coordinator_cannot_see_the_visibility_of_a_draft(login_as):
    created = create_event_request(login_as(Users.ORGANISER), is_public=True)

    assert login_as(Users.COORDINATOR).get(f"/events/{created['id']}").status_code == 404
