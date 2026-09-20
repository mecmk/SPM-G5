"""Story 4.4 - be: approve event request.

AC1 Approval is only available for requests currently under review.
AC2 The approval records the deciding coordinator and the decision time.
AC3 The event's status changes to reflect approval.
AC4 The outcome is visible to the organiser.

"Currently under review" is read as the whole review queue - the same
``_AWAITING_DECISION_STATUSES`` set (SUBMITTED, UNDER_REVIEW, CLARIFICATION_REQUESTED) story
4.1's queue already filters on, not literally the UNDER_REVIEW status alone. See the module
docstring of ``app/events/service.py``.

Excluded, with reason:
* A genuine multi-connection concurrency test (two simultaneous approvals of the *same*
  request) - judged not worth guarding against for this feature, so there is no lock to
  exercise. The repeated-approval test below still proves the status guard in the ordinary
  sequential case.
* Organiser notification - there is no notification application code anywhere in the backend
  yet (epic 20 is unbuilt), and story 13.2's approve-booking precedent does not write one either.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.events.models import EventStatus
from tests.support.factories import make_event
from tests.support.seed import Events, Users


# --- AC1: only a request awaiting decision may be approved -----------------------------------
@pytest.mark.story("4.4", ac=1)
def test_coordinator_can_approve_a_request_under_review(coordinator_client, db: Session):
    before = datetime.now(timezone.utc)

    response = coordinator_client.post(f"/events/{Events.UNDER_REVIEW}/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == EventStatus.APPROVED
    assert body["decided_by"]["id"] == str(Users.COORDINATOR.id)
    decided_at = datetime.fromisoformat(body["decided_at"])
    assert before <= decided_at <= datetime.now(timezone.utc) + timedelta(seconds=5)

    db.expire_all()
    row = db.execute(
        text("SELECT status, decided_by_id, decided_at FROM events WHERE id = :id"),
        {"id": Events.UNDER_REVIEW},
    ).one()
    assert row.status == EventStatus.APPROVED
    assert row.decided_by_id == Users.COORDINATOR.id
    assert row.decided_at is not None


@pytest.mark.story("4.4", ac=1)
@pytest.mark.parametrize("event_id", [Events.SUBMITTED, Events.CLARIFICATION_REQUESTED])
def test_approving_any_awaiting_decision_status_is_allowed(coordinator_client, event_id):
    response = coordinator_client.post(f"/events/{event_id}/approve")

    assert response.status_code == 200
    assert response.json()["status"] == EventStatus.APPROVED


@pytest.mark.story("4.4", ac=1)
@pytest.mark.parametrize(
    "status",
    [
        EventStatus.APPROVED,
        EventStatus.PLANNING,
        EventStatus.CONFIRMED,
        EventStatus.COMPLETED,
        EventStatus.CANCELLED,
        EventStatus.REJECTED,
    ],
)
def test_approving_a_request_not_awaiting_decision_is_refused(
    coordinator_client, db: Session, status
):
    event = make_event(db, status=status, assigned_coordinator_id=Users.COORDINATOR.id)

    response = coordinator_client.post(f"/events/{event.id}/approve")

    assert response.status_code == 409
    db.expire_all()
    row = db.execute(
        text("SELECT status, decided_by_id, decided_at FROM events WHERE id = :id"),
        {"id": event.id},
    ).one()
    assert row.status == status
    assert row.decided_by_id is None
    assert row.decided_at is None


@pytest.mark.story("4.4", ac=1)
def test_approving_a_draft_is_not_found(coordinator_client, db: Session):
    # A draft is private to its organiser (service.get_event), so even the coordinator it names
    # cannot see it, let alone decide it.
    event = make_event(db, status=EventStatus.DRAFT, assigned_coordinator_id=Users.COORDINATOR.id)

    response = coordinator_client.post(f"/events/{event.id}/approve")

    assert response.status_code == 404


@pytest.mark.story("4.4", ac=1)
def test_approving_the_same_request_twice_is_refused_the_second_time(coordinator_client):
    first = coordinator_client.post(f"/events/{Events.UNDER_REVIEW}/approve")
    assert first.status_code == 200

    second = coordinator_client.post(f"/events/{Events.UNDER_REVIEW}/approve")

    assert second.status_code == 409
    # The first decision stands; the refused second attempt did not overwrite it.
    unchanged = coordinator_client.get(f"/events/{Events.UNDER_REVIEW}")
    assert unchanged.json()["decided_by"] == first.json()["decided_by"]
    assert unchanged.json()["decided_at"] == first.json()["decided_at"]


@pytest.mark.story("4.4", ac=1)
def test_approving_a_missing_event_is_404(coordinator_client):
    assert coordinator_client.post(f"/events/{uuid.uuid4()}/approve").status_code == 404


# --- AC2: records the deciding coordinator and the decision time -----------------------------
@pytest.mark.story("4.4", ac=2)
def test_approval_records_the_decider_full_name(coordinator_client):
    response = coordinator_client.post(f"/events/{Events.UNDER_REVIEW}/approve")
    assert response.json()["decided_by"]["full_name"] == Users.COORDINATOR.full_name


@pytest.mark.story("4.4", ac=2)
def test_approval_is_recorded_in_the_audit_log(coordinator_client, db: Session):
    coordinator_client.post(f"/events/{Events.UNDER_REVIEW}/approve")

    row = db.execute(
        text("SELECT actor_id FROM audit_log WHERE action = 'EVENT_APPROVED' AND entity_id = :id"),
        {"id": Events.UNDER_REVIEW},
    ).one()
    assert row.actor_id == Users.COORDINATOR.id


@pytest.mark.story("4.4", ac=2)
def test_approval_is_recorded_in_status_history(coordinator_client, db: Session):
    coordinator_client.post(f"/events/{Events.UNDER_REVIEW}/approve")

    row = db.execute(
        text(
            "SELECT from_status, to_status, changed_by_id FROM event_status_history "
            "WHERE event_id = :id AND to_status = 'APPROVED'"
        ),
        {"id": Events.UNDER_REVIEW},
    ).one()
    assert row.from_status == EventStatus.UNDER_REVIEW
    assert row.changed_by_id == Users.COORDINATOR.id


# --- AC3: the event's status changes to reflect approval --------------------------------------
@pytest.mark.story("4.4", ac=3)
def test_approved_event_leaves_the_review_queue(coordinator_client):
    coordinator_client.post(f"/events/{Events.UNDER_REVIEW}/approve")

    ids = [row["id"] for row in coordinator_client.get("/events/review-queue").json()]

    assert str(Events.UNDER_REVIEW) not in ids


# --- AC4: the outcome is visible to the organiser ---------------------------------------------
@pytest.mark.story("4.4", ac=4)
def test_owning_organiser_can_read_the_approved_outcome(login_as):
    login_as(Users.COORDINATOR).post(f"/events/{Events.UNDER_REVIEW}/approve")

    response = login_as(Users.ORGANISER_2).get(f"/events/{Events.UNDER_REVIEW}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == EventStatus.APPROVED
    assert body["decided_by"]["full_name"] == Users.COORDINATOR.full_name
    assert body["decided_at"] is not None


@pytest.mark.story("4.4", ac=4)
def test_a_different_organiser_cannot_read_the_event(login_as):
    # Existence is not revealed to an organiser it does not belong to (see the module docstring
    # of app/events/service.py) - same 404, not 403, as test_event_request_details.py:1184.
    response = login_as(Users.ORGANISER).get(f"/events/{Events.UNDER_REVIEW}")
    assert response.status_code == 404


@pytest.mark.story("4.4", ac=4)
def test_internal_staff_can_read_any_event(venue_staff_client, tech_client):
    assert venue_staff_client.get(f"/events/{Events.UNDER_REVIEW}").status_code == 200
    assert tech_client.get(f"/events/{Events.UNDER_REVIEW}").status_code == 200


@pytest.mark.story("4.4", ac=4)
def test_signed_out_visitors_cannot_read_an_event(client):
    assert client.get(f"/events/{Events.UNDER_REVIEW}").status_code == 401


@pytest.mark.story("4.4", ac=4)
def test_reading_a_missing_event_is_404(coordinator_client):
    assert coordinator_client.get(f"/events/{uuid.uuid4()}").status_code == 404


# --- Permissions / relationship refusals -------------------------------------------------------
@pytest.mark.story("4.4", ac=1)
def test_signed_out_visitors_cannot_approve_an_event(client):
    assert client.post(f"/events/{Events.UNDER_REVIEW}/approve").status_code == 401


@pytest.mark.story("4.4", ac=1)
@pytest.mark.parametrize(
    "user",
    [Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda u: u.role,
)
def test_other_roles_cannot_approve_an_event(client, user):
    client.login(user)
    assert client.post(f"/events/{Events.UNDER_REVIEW}/approve").status_code == 403


@pytest.mark.story("4.4", ac=1)
def test_a_different_coordinator_cannot_approve_the_request(login_as, db: Session):
    response = login_as(Users.COORDINATOR_2).post(f"/events/{Events.UNDER_REVIEW}/approve")

    assert response.status_code == 403
    db.expire_all()
    row = db.execute(
        text("SELECT status FROM events WHERE id = :id"), {"id": Events.UNDER_REVIEW}
    ).one()
    assert row.status == EventStatus.UNDER_REVIEW


@pytest.mark.story("4.4", ac=1)
def test_an_unassigned_request_cannot_be_approved(coordinator_client, db: Session):
    event = make_event(db, status=EventStatus.SUBMITTED)  # no assigned_coordinator_id

    response = coordinator_client.post(f"/events/{event.id}/approve")

    assert response.status_code == 403
