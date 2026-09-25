"""Story 4.6 - be: an Event Organiser sees the decision and clarification history.

AC1 The event shows its current decision state and any decision reason.
AC2 Clarification messages and responses are listed in chronological order with author and
    timestamp.
AC3 Historical entries cannot be edited or removed.

Excluded, with reason:
* Nothing writes a clarification yet (stories 4.2/4.3 add the POST) - AC3 is proven here by the
  absence of any write route, not by attempting to undo a write.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.events.models import EventStatus
from app.main import app
from tests.support.factories import make_clarification, make_event
from tests.support.seed import Clarifications, Events, Users

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


# --- AC1: decision state and reason ---------------------------------------------------------
@pytest.mark.story("4.6", ac=1)
def test_a_rejected_requests_decision_is_shown(login_as):
    response = login_as(Users.ORGANISER_2).get(f"/events/{Events.REJECTED}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "REJECTED"
    assert body["decision_reason"] == "No outdoor venues are available after 22:00."
    assert body["decided_by_name"] == Users.COORDINATOR_2.full_name
    assert body["decided_at"].startswith("2026-09-07")


@pytest.mark.story("4.6", ac=1)
def test_an_approved_requests_decision_is_shown_without_a_reason(login_as):
    response = login_as(Users.ORGANISER_2).get(f"/events/{Events.APPROVED}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PLANNING"
    assert body["decision_reason"] is None
    assert body["decided_by_name"] == Users.COORDINATOR.full_name
    assert body["decided_at"].startswith("2026-09-03")


@pytest.mark.story("4.6", ac=1)
@pytest.mark.parametrize("event_id", [Events.SUBMITTED, Events.CLARIFICATION_REQUESTED])
def test_a_request_awaiting_decision_carries_no_decision_fields(organiser_client, event_id):
    body = organiser_client.get(f"/events/{event_id}").json()

    assert body["decided_by_name"] is None
    assert body["decided_at"] is None
    assert body["decision_reason"] is None


# --- AC2: clarifications, chronological order -------------------------------------------------
@pytest.mark.story("4.6", ac=2)
def test_the_seeded_conversation_is_listed_oldest_first_with_author_and_time(organiser_client):
    response = organiser_client.get(f"/events/{Events.CLARIFICATION_REQUESTED}/clarifications")

    assert response.status_code == 200
    body = response.json()
    assert [row["kind"] for row in body] == ["REQUEST", "RESPONSE"]
    assert body[0]["id"] == str(Clarifications.REQUEST)
    assert body[0]["author_name"] == Users.COORDINATOR.full_name
    assert body[0]["message"] == "Please add expected headcount by department."
    assert body[0]["created_at"].startswith("2026-09-04")
    assert body[1]["id"] == str(Clarifications.RESPONSE)
    assert body[1]["author_name"] == Users.ORGANISER.full_name
    assert body[1]["created_at"].startswith("2026-09-05")


@pytest.mark.story("4.6", ac=2)
def test_entries_are_ordered_by_time_regardless_of_insertion_order(coordinator_client, db: Session):
    event = make_event(
        db, status=EventStatus.UNDER_REVIEW, assigned_coordinator_id=Users.COORDINATOR.id
    )
    make_clarification(
        db,
        event_id=event.id,
        kind="NOTE",
        message="Third",
        created_at=datetime(2026, 9, 3, 9, 0, tzinfo=UTC),
    )
    make_clarification(
        db,
        event_id=event.id,
        kind="REQUEST",
        message="First",
        created_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
    )
    make_clarification(
        db,
        event_id=event.id,
        kind="RESPONSE",
        message="Second",
        created_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
    )

    body = coordinator_client.get(f"/events/{event.id}/clarifications").json()

    assert [row["message"] for row in body] == ["First", "Second", "Third"]


@pytest.mark.story("4.6", ac=2)
def test_tied_timestamps_still_return_a_stable_order(coordinator_client, db: Session):
    event = make_event(
        db, status=EventStatus.UNDER_REVIEW, assigned_coordinator_id=Users.COORDINATOR.id
    )
    tie = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    make_clarification(db, event_id=event.id, message="A", created_at=tie)
    make_clarification(db, event_id=event.id, message="B", created_at=tie)

    url = f"/events/{event.id}/clarifications"
    first_call = [row["id"] for row in coordinator_client.get(url).json()]
    second_call = [row["id"] for row in coordinator_client.get(url).json()]

    assert first_call == second_call


@pytest.mark.story("4.6", ac=2)
def test_a_request_with_no_clarifications_returns_an_empty_list(organiser_client):
    response = organiser_client.get(f"/events/{Events.SUBMITTED}/clarifications")

    assert response.status_code == 200
    assert response.json() == []


# --- AC2: access control (organiser or this event's assigned coordinator only - narrower than
# GET /events/{event_id}, which any internal role with events:read_all may read) --------------
@pytest.mark.story("4.6", ac=2)
def test_the_assigned_coordinator_can_read_clarifications_on_a_submitted_request(login_as):
    response = login_as(Users.COORDINATOR).get(
        f"/events/{Events.CLARIFICATION_REQUESTED}/clarifications"
    )
    assert response.status_code == 200


@pytest.mark.story("4.6", ac=2)
@pytest.mark.parametrize("user", [Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.COORDINATOR_2])
def test_an_unrelated_internal_role_cannot_read_clarifications(login_as, user):
    response = login_as(user).get(f"/events/{Events.CLARIFICATION_REQUESTED}/clarifications")
    assert response.status_code == 403


@pytest.mark.story("4.6", ac=2)
def test_another_organisers_request_is_not_found(login_as):
    response = login_as(Users.ORGANISER_2).get(
        f"/events/{Events.CLARIFICATION_REQUESTED}/clarifications"
    )
    assert response.status_code == 404


@pytest.mark.story("4.6", ac=2)
def test_a_drafts_clarifications_are_private_to_its_organiser(login_as):
    response = login_as(Users.COORDINATOR).get(f"/events/{Events.DRAFT}/clarifications")
    assert response.status_code == 404


@pytest.mark.story("4.6", ac=2)
def test_an_attendee_cannot_read_clarifications(attendee_client):
    response = attendee_client.get(f"/events/{Events.SUBMITTED}/clarifications")
    assert response.status_code == 403


@pytest.mark.story("4.6", ac=2)
def test_reading_clarifications_requires_sign_in_and_an_existing_request(client, login_as):
    assert client.get(f"/events/{Events.SUBMITTED}/clarifications").status_code == 401
    login_as(Users.COORDINATOR)
    assert client.get(f"/events/{uuid.uuid4()}/clarifications").status_code == 404


# --- AC3: historical entries cannot be edited or removed ---------------------------------------
@pytest.mark.story("4.6", ac=3)
def test_no_route_writes_to_the_clarifications_endpoint():
    """No POST/PUT/PATCH/DELETE exists on any clarifications path - proven from the route table
    itself, not by trying each verb and hoping the framework refuses it. ``iter_route_contexts``
    flattens the routers ``app.include_router`` wraps, which ``app.routes`` does not."""
    routes = [ctx.route for ctx in iter_route_contexts(app.routes)]
    offenders = [
        (route.path, sorted(route.methods & WRITE_METHODS))
        for route in routes
        if isinstance(route, APIRoute) and "/clarifications" in route.path
        if route.methods & WRITE_METHODS
    ]
    assert not offenders, offenders


@pytest.mark.story("4.6", ac=3)
@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_writing_to_the_clarifications_collection_is_refused(organiser_client, method):
    response = getattr(organiser_client, method)(
        f"/events/{Events.CLARIFICATION_REQUESTED}/clarifications"
    )
    assert response.status_code == 405


@pytest.mark.story("4.6", ac=3)
@pytest.mark.parametrize("method", ["patch", "delete"])
def test_no_route_addresses_a_single_clarification_entry(organiser_client, method):
    response = getattr(organiser_client, method)(
        f"/events/{Events.CLARIFICATION_REQUESTED}/clarifications/{Clarifications.REQUEST}"
    )
    assert response.status_code == 404


@pytest.mark.story("4.6", ac=3)
def test_the_seeded_clarifications_are_unchanged(db: Session):
    message = db.execute(
        text("SELECT message FROM event_clarifications WHERE id = :id"),
        {"id": Clarifications.REQUEST},
    ).scalar()
    assert message == "Please add expected headcount by department."
