"""Story 4.5 - be: reject event request with reason.

AC1 A reason must be provided when rejecting.
AC2 The event's status changes to rejected and it leaves the review queue.
AC3 The reason and the deciding coordinator are visible to the organiser.
AC4 A rejected request cannot be approved afterwards without a new submission.

Excluded, with reason:
* A genuine multi-connection concurrency test - same reasoning as ``test_approve_event.py``.
* Organiser notification - no notification application code exists yet (see
  ``test_approve_event.py``).
* "without a new submission" (AC4) - re-submitting a fresh request is a different story (2.x
  epic); this file only proves the rejected request itself can no longer be approved.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.events import service
from app.events.models import EventStatus
from tests.support.factories import make_event
from tests.support.seed import Events, Users


# --- AC1: a reason must be provided when rejecting --------------------------------------------
@pytest.mark.story("4.5", ac=1)
def test_rejection_without_reason_is_refused(coordinator_client):
    response = coordinator_client.post(f"/events/{Events.SUBMITTED}/reject", json={})
    assert response.status_code == 422


@pytest.mark.story("4.5", ac=1)
def test_rejection_with_an_empty_reason_is_refused(coordinator_client):
    response = coordinator_client.post(f"/events/{Events.SUBMITTED}/reject", json={"reason": ""})
    assert response.status_code == 422


@pytest.mark.story("4.5", ac=1)
def test_rejection_with_a_whitespace_only_reason_is_refused(coordinator_client, db: Session):
    response = coordinator_client.post(f"/events/{Events.SUBMITTED}/reject", json={"reason": "   "})

    assert response.status_code == 422
    db.expire_all()
    row = db.execute(
        text("SELECT status, decision_reason FROM events WHERE id = :id"),
        {"id": Events.SUBMITTED},
    ).one()
    assert row.status == EventStatus.SUBMITTED
    assert row.decision_reason is None


@pytest.mark.story("4.5", ac=1)
def test_rejection_with_an_unknown_field_is_refused(coordinator_client):
    # Every sibling request schema sets extra="forbid" (schemas.py); EventRejection should too,
    # rather than silently drop a key like "status" that looks like it might do something.
    response = coordinator_client.post(
        f"/events/{Events.SUBMITTED}/reject",
        json={"reason": "Budget cut.", "status": "APPROVED"},
    )
    assert response.status_code == 422


@pytest.mark.story("4.5", ac=1)
def test_reject_event_refuses_a_blank_reason_even_bypassing_the_schema(db: Session):
    # AC1's mandatory-reason rule is enforced again in the service (service.py's reject_event),
    # not only by EventRejection's Pydantic validator, so a caller other than this HTTP endpoint
    # (a future 4.6 clarification flow, 6.5 cancellation, a seed script) cannot persist a
    # REJECTED request with no reason.
    event = make_event(
        db, status=EventStatus.SUBMITTED, assigned_coordinator_id=Users.COORDINATOR.id
    )
    coordinator = db.get(User, Users.COORDINATOR.id)

    with pytest.raises(service.MissingDecisionReason):
        service.reject_event(db, event, actor=coordinator, reason="   ")


@pytest.mark.story("4.5", ac=1)
def test_rejection_with_a_reason_succeeds_and_strips_it(coordinator_client, db: Session):
    response = coordinator_client.post(
        f"/events/{Events.SUBMITTED}/reject",
        json={"reason": "  Venue capacity insufficient.  "},
    )

    assert response.status_code == 200
    assert response.json()["decision_reason"] == "Venue capacity insufficient."

    db.expire_all()
    row = db.execute(
        text("SELECT decision_reason FROM events WHERE id = :id"), {"id": Events.SUBMITTED}
    ).one()
    assert row.decision_reason == "Venue capacity insufficient."


@pytest.mark.story("4.5", ac=1)
def test_rejecting_a_missing_event_is_404(coordinator_client):
    response = coordinator_client.post(
        f"/events/{uuid.uuid4()}/reject", json={"reason": "No reason needed for the check."}
    )
    assert response.status_code == 404


# --- AC2: status changes to REJECTED and leaves the review queue ------------------------------
@pytest.mark.story("4.5", ac=2)
@pytest.mark.parametrize(
    "event_id", [Events.SUBMITTED, Events.UNDER_REVIEW, Events.CLARIFICATION_REQUESTED]
)
def test_rejecting_any_awaiting_decision_status_is_allowed(coordinator_client, event_id):
    response = coordinator_client.post(
        f"/events/{event_id}/reject", json={"reason": "Does not fit the venue calendar."}
    )

    assert response.status_code == 200
    assert response.json()["status"] == EventStatus.REJECTED


@pytest.mark.story("4.5", ac=2)
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
def test_rejecting_a_request_not_awaiting_decision_is_refused(
    coordinator_client, db: Session, status
):
    event = make_event(db, status=status, assigned_coordinator_id=Users.COORDINATOR.id)

    response = coordinator_client.post(
        f"/events/{event.id}/reject", json={"reason": "Refused for the boundary check."}
    )

    assert response.status_code == 409
    db.expire_all()
    row = db.execute(
        text("SELECT status, decided_by_id, decision_reason FROM events WHERE id = :id"),
        {"id": event.id},
    ).one()
    assert row.status == status
    assert row.decided_by_id is None
    assert row.decision_reason is None


@pytest.mark.story("4.5", ac=2)
def test_rejecting_a_draft_is_not_found(coordinator_client, db: Session):
    # A draft is private to its organiser (service.get_event), so even the coordinator it names
    # cannot see it, let alone decide it.
    event = make_event(db, status=EventStatus.DRAFT, assigned_coordinator_id=Users.COORDINATOR.id)

    response = coordinator_client.post(
        f"/events/{event.id}/reject", json={"reason": "Refused for the boundary check."}
    )

    assert response.status_code == 404


@pytest.mark.story("4.5", ac=2)
def test_rejected_event_leaves_the_review_queue(coordinator_client):
    coordinator_client.post(
        f"/events/{Events.UNDER_REVIEW}/reject", json={"reason": "Duplicate of another request."}
    )

    ids = [row["id"] for row in coordinator_client.get("/events/review-queue").json()]

    assert str(Events.UNDER_REVIEW) not in ids


@pytest.mark.story("4.5", ac=2)
def test_rejection_is_recorded_in_status_history(coordinator_client, db: Session):
    coordinator_client.post(
        f"/events/{Events.UNDER_REVIEW}/reject", json={"reason": "Clashes with another event."}
    )

    row = db.execute(
        text(
            "SELECT from_status, to_status, changed_by_id, reason FROM event_status_history "
            "WHERE event_id = :id AND to_status = 'REJECTED'"
        ),
        {"id": Events.UNDER_REVIEW},
    ).one()
    assert row.from_status == EventStatus.UNDER_REVIEW
    assert row.changed_by_id == Users.COORDINATOR.id
    assert row.reason == "Clashes with another event."


# --- AC3: the reason and the deciding coordinator are visible to the organiser ----------------
@pytest.mark.story("4.5", ac=3)
def test_owning_organiser_can_read_the_rejection_reason(login_as):
    login_as(Users.COORDINATOR).post(
        f"/events/{Events.CLARIFICATION_REQUESTED}/reject",
        json={"reason": "Accessibility requirements cannot be met at any available venue."},
    )

    response = login_as(Users.ORGANISER).get(f"/events/{Events.CLARIFICATION_REQUESTED}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == EventStatus.REJECTED
    assert (
        body["decision_reason"]
        == "Accessibility requirements cannot be met at any available venue."
    )
    assert body["decided_by_name"] == Users.COORDINATOR.full_name


@pytest.mark.story("4.5", ac=3)
def test_rejection_is_recorded_in_the_audit_log(coordinator_client, db: Session):
    coordinator_client.post(
        f"/events/{Events.UNDER_REVIEW}/reject", json={"reason": "No suitable venue is free."}
    )

    row = db.execute(
        text(
            "SELECT actor_id, details FROM audit_log "
            "WHERE action = 'EVENT_REJECTED' AND entity_id = :id"
        ),
        {"id": Events.UNDER_REVIEW},
    ).one()
    assert row.actor_id == Users.COORDINATOR.id
    assert row.details["reason"] == "No suitable venue is free."


# --- AC4: a rejected request cannot be approved afterwards -------------------------------------
@pytest.mark.story("4.5", ac=4)
def test_a_rejected_request_cannot_then_be_approved(coordinator_client, db: Session):
    rejected = coordinator_client.post(
        f"/events/{Events.UNDER_REVIEW}/reject", json={"reason": "Budget was not approved."}
    )
    assert rejected.status_code == 200

    approved = coordinator_client.post(f"/events/{Events.UNDER_REVIEW}/approve")

    assert approved.status_code == 409
    db.expire_all()
    row = db.execute(
        text("SELECT status, decision_reason FROM events WHERE id = :id"),
        {"id": Events.UNDER_REVIEW},
    ).one()
    assert row.status == EventStatus.REJECTED
    assert row.decision_reason == "Budget was not approved."


@pytest.mark.story("4.5", ac=4)
def test_the_seeded_rejected_event_cannot_be_approved(login_as):
    response = login_as(Users.COORDINATOR_2).post(f"/events/{Events.REJECTED}/approve")
    assert response.status_code == 409


# --- Permissions / relationship refusals -------------------------------------------------------
@pytest.mark.story("4.5", ac=1)
def test_signed_out_visitors_cannot_reject_an_event(client):
    response = client.post(
        f"/events/{Events.SUBMITTED}/reject", json={"reason": "No session, should be refused."}
    )
    assert response.status_code == 401


@pytest.mark.story("4.5", ac=1)
@pytest.mark.parametrize(
    "user",
    [Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda u: u.role,
)
def test_other_roles_cannot_reject_an_event(client, user):
    client.login(user)
    response = client.post(
        f"/events/{Events.SUBMITTED}/reject", json={"reason": "Wrong role, should be refused."}
    )
    assert response.status_code == 403


@pytest.mark.story("4.5", ac=1)
def test_a_different_coordinator_cannot_reject_the_request(login_as, db: Session):
    response = login_as(Users.COORDINATOR_2).post(
        f"/events/{Events.UNDER_REVIEW}/reject", json={"reason": "Not my request to decide."}
    )

    assert response.status_code == 403
    db.expire_all()
    row = db.execute(
        text("SELECT status FROM events WHERE id = :id"), {"id": Events.UNDER_REVIEW}
    ).one()
    assert row.status == EventStatus.UNDER_REVIEW


@pytest.mark.story("4.5", ac=1)
def test_an_unassigned_request_cannot_be_rejected(coordinator_client, db: Session):
    event = make_event(db, status=EventStatus.SUBMITTED)  # no assigned_coordinator_id

    response = coordinator_client.post(
        f"/events/{event.id}/reject", json={"reason": "No coordinator is assigned yet."}
    )

    assert response.status_code == 403
