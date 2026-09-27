"""Story 2.1 - the duplicate-request guard on an event request (AC20, added after product
review).

AC20 When an organiser saves a request (creating one, or editing an existing draft's name or
     dates), the save is refused if the name (trimmed, case-insensitive) and both the proposed
     start and end would then exactly match one of the organiser's own other live requests -
     DRAFT, UNDER_REVIEW, CLARIFICATION_REQUESTED, PLANNING or CONFIRMED. A REJECTED, CANCELLED
     or COMPLETED request never counts as a match, and neither does another organiser's request
     with the same name and dates. The check only applies once both proposed dates are set;
     reusing a name on a dateless draft is not flagged.

Enforced by a real database constraint (uq_events_organiser_name_dates), not a pre-check -
backend/STYLE.md's blocking rule.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.events.models import EventStatus
from tests.support.factories import (
    create_event_request,
    event_request_payload,
    future_datetime,
    make_event,
)
from tests.support.seed import Users


def _create(client, **overrides):
    return client.post("/events", json=event_request_payload(**overrides))


# --- AC20: creating a duplicate --------------------------------------------------------------
@pytest.mark.story("2.1", ac=20)
def test_two_requests_with_different_names_and_same_dates_are_both_saved(organiser_client):
    starts_at = future_datetime(days=30)
    common = {
        "starts_at": starts_at.isoformat(),
        "ends_at": (starts_at + timedelta(hours=8)).isoformat(),
    }
    assert _create(organiser_client, name="Event A", **common).status_code == 201
    assert _create(organiser_client, name="Event B", **common).status_code == 201


@pytest.mark.story("2.1", ac=20)
def test_two_requests_with_the_same_name_and_different_dates_are_both_saved(organiser_client):
    first_start = future_datetime(days=30)
    second_start = future_datetime(days=45)
    assert (
        _create(
            organiser_client,
            name="Weekly Standup",
            starts_at=first_start.isoformat(),
            ends_at=(first_start + timedelta(hours=1)).isoformat(),
        ).status_code
        == 201
    )
    assert (
        _create(
            organiser_client,
            name="Weekly Standup",
            starts_at=second_start.isoformat(),
            ends_at=(second_start + timedelta(hours=1)).isoformat(),
        ).status_code
        == 201
    )


@pytest.mark.story("2.1", ac=20)
def test_a_duplicate_name_and_dates_is_refused_on_create(organiser_client):
    starts_at = future_datetime(days=30)
    common = {
        "name": "Q1 Kick-off",
        "starts_at": starts_at.isoformat(),
        "ends_at": (starts_at + timedelta(hours=8)).isoformat(),
    }
    assert _create(organiser_client, **common).status_code == 201

    response = _create(organiser_client, **common)

    assert response.status_code == 422
    assert "already have a request" in response.text.lower()


@pytest.mark.story("2.1", ac=20)
def test_the_duplicate_check_ignores_case_and_surrounding_spaces(organiser_client):
    starts_at = future_datetime(days=30)
    common = {
        "starts_at": starts_at.isoformat(),
        "ends_at": (starts_at + timedelta(hours=8)).isoformat(),
    }
    assert _create(organiser_client, name="Q1 Kick-off", **common).status_code == 201

    response = _create(organiser_client, name="  q1 KICK-OFF  ", **common)

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=20)
def test_only_one_matching_date_does_not_block(organiser_client):
    starts_at = future_datetime(days=30)
    ends_at = starts_at + timedelta(hours=8)
    assert (
        _create(
            organiser_client,
            name="Q1 Kick-off",
            starts_at=starts_at.isoformat(),
            ends_at=ends_at.isoformat(),
        ).status_code
        == 201
    )

    response = _create(
        organiser_client,
        name="Q1 Kick-off",
        starts_at=starts_at.isoformat(),
        ends_at=(ends_at + timedelta(hours=1)).isoformat(),
    )

    assert response.status_code == 201


@pytest.mark.story("2.1", ac=20)
def test_two_dateless_drafts_with_the_same_name_do_not_block(organiser_client):
    assert organiser_client.post("/events", json={"name": "Untitled"}).status_code == 201
    assert organiser_client.post("/events", json={"name": "Untitled"}).status_code == 201


@pytest.mark.story("2.1", ac=20)
def test_a_refused_duplicate_leaves_the_original_saved(organiser_client, db: Session):
    starts_at = future_datetime(days=30)
    common = {
        "name": "Q1 Kick-off",
        "starts_at": starts_at.isoformat(),
        "ends_at": (starts_at + timedelta(hours=8)).isoformat(),
    }
    first = _create(organiser_client, **common).json()

    response = _create(organiser_client, **common)

    assert response.status_code == 422
    kept = organiser_client.get(f"/events/{first['id']}").json()
    assert kept["name"] == "Q1 Kick-off"


# --- AC20: editing into a collision --------------------------------------------------------
@pytest.mark.story("2.1", ac=20)
def test_editing_a_drafts_name_into_a_collision_is_refused(organiser_client):
    starts_at = future_datetime(days=30)
    common = {
        "starts_at": starts_at.isoformat(),
        "ends_at": (starts_at + timedelta(hours=8)).isoformat(),
    }
    _create(organiser_client, name="Q1 Kick-off", **common)
    other = _create(organiser_client, name="Q2 Kick-off", **common).json()

    response = organiser_client.patch(f"/events/{other['id']}", json={"name": "Q1 Kick-off"})

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=20)
def test_editing_a_drafts_dates_into_a_collision_is_refused(organiser_client):
    starts_at = future_datetime(days=30)
    _create(
        organiser_client,
        name="Q1 Kick-off",
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
    )
    other = _create(
        organiser_client,
        name="Q1 Kick-off",
        starts_at=future_datetime(days=45).isoformat(),
        ends_at=(future_datetime(days=45) + timedelta(hours=8)).isoformat(),
    ).json()

    response = organiser_client.patch(
        f"/events/{other['id']}",
        json={
            "starts_at": starts_at.isoformat(),
            "ends_at": (starts_at + timedelta(hours=8)).isoformat(),
        },
    )

    assert response.status_code == 422


@pytest.mark.story("2.1", ac=20)
def test_editing_a_draft_without_touching_name_or_dates_is_unaffected(organiser_client):
    created = create_event_request(organiser_client, name="Q1 Kick-off")

    response = organiser_client.patch(f"/events/{created['id']}", json={"purpose": "Updated"})

    assert response.status_code == 200, response.text


# --- AC20: scoping - per organiser, live statuses only --------------------------------------
@pytest.mark.story("2.1", ac=20)
def test_a_different_organisers_matching_request_does_not_block(login_as):
    starts_at = future_datetime(days=30)
    common = {
        "name": "Shared Name Coincidence",
        "starts_at": starts_at.isoformat(),
        "ends_at": (starts_at + timedelta(hours=8)).isoformat(),
    }
    assert _create(login_as(Users.ORGANISER), **common).status_code == 201

    response = _create(login_as(Users.ORGANISER_2), **common)

    assert response.status_code == 201


@pytest.mark.story("2.1", ac=20)
@pytest.mark.parametrize(
    "status",
    [
        pytest.param(EventStatus.REJECTED, id="rejected"),
        pytest.param(EventStatus.CANCELLED, id="cancelled"),
        pytest.param(EventStatus.COMPLETED, id="completed"),
    ],
)
def test_a_dead_requests_name_and_dates_can_be_reused(organiser_client, db: Session, status):
    starts_at = future_datetime(days=30)
    make_event(
        db,
        organiser_id=Users.ORGANISER.id,
        name="Annual Gala",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=8),
        status=status,
    )
    db.flush()

    response = _create(
        organiser_client,
        name="Annual Gala",
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
    )

    assert response.status_code == 201, response.text


@pytest.mark.story("2.1", ac=20)
@pytest.mark.parametrize(
    "status",
    [
        pytest.param(EventStatus.UNDER_REVIEW, id="under-review"),
        pytest.param(EventStatus.CLARIFICATION_REQUESTED, id="clarification-requested"),
        pytest.param(EventStatus.PLANNING, id="planning"),
        pytest.param(EventStatus.CONFIRMED, id="confirmed"),
    ],
)
def test_a_live_requests_name_and_dates_cannot_be_reused(organiser_client, db: Session, status):
    starts_at = future_datetime(days=30)
    make_event(
        db,
        organiser_id=Users.ORGANISER.id,
        name="Annual Gala",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=8),
        status=status,
    )
    db.flush()

    response = _create(
        organiser_client,
        name="Annual Gala",
        starts_at=starts_at.isoformat(),
        ends_at=(starts_at + timedelta(hours=8)).isoformat(),
    )

    assert response.status_code == 422
