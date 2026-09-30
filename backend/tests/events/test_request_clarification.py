"""Story 4.2 - be: request clarification from organiser.

AC1 The assigned coordinator writes a message and sends a clarification request; it is recorded
    with author and time, and the organiser is notified.
AC3 The status change, the message and the notification are all saved together.
AC4 The message is mandatory; blank or whitespace-only messages are refused.
AC5 Several clarification rounds are allowed, each kept in the thread in order - including a
    follow-up sent while the event already awaits a response to an earlier round: this branch
    implements only story 4.2, so nothing ever moves the event back to Under Review on its own,
    and a second round has to work directly from CLARIFICATION_REQUESTED.
AC6 Only the assigned coordinator can request clarification, and only while the event is Under
    Review or already CLARIFICATION_REQUESTED.
AC7 The API refuses the request if the event is not Under Review or CLARIFICATION_REQUESTED, or
    the caller is not its assigned coordinator.
AC8 If the event is reassigned or decided while the message is being written, sending is
    refused. A double-click sends once.

Excluded, with reason:
* AC2 ("Approve and Reject are unavailable meanwhile") was dropped as a product decision: the
  existing rule that lets a coordinator decide a CLARIFICATION_REQUESTED request outright (bug
  b6.1.1's reversal) is unchanged, and already covered by test_approve_event.py /
  test_reject_event.py.
* Reading the resulting thread in order is already proven by story 4.6's
  test_decision_history.py; this file only proves writing.
* Story 4.3 (the organiser's response to a clarification request) is out of scope for this
  branch, which implements only story 4.2.
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


# --- AC1: recorded with author and time, organiser notified -----------------------------------
@pytest.mark.story("4.2", ac=1)
def test_requesting_clarification_is_recorded_with_author_and_time(coordinator_client):
    response = coordinator_client.post(
        f"/events/{Events.SUBMITTED}/clarifications",
        json={"message": "Please share the expected headcount."},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "REQUEST"
    assert body["author_id"] == str(Users.COORDINATOR.id)
    assert body["author_name"] == Users.COORDINATOR.full_name
    assert body["message"] == "Please share the expected headcount."
    assert body["created_at"] is not None


@pytest.mark.story("4.2", ac=1)
def test_requesting_clarification_moves_the_event_to_clarification_requested(
    coordinator_client, db: Session
):
    response = coordinator_client.post(
        f"/events/{Events.SUBMITTED}/clarifications", json={"message": "Please confirm the dates."}
    )

    assert response.status_code == 201
    db.expire_all()
    row = db.execute(
        text("SELECT status FROM events WHERE id = :id"), {"id": Events.SUBMITTED}
    ).one()
    assert row.status == EventStatus.CLARIFICATION_REQUESTED


@pytest.mark.story("4.2", ac=1)
def test_the_organiser_is_notified(coordinator_client, db: Session):
    coordinator_client.post(
        f"/events/{Events.SUBMITTED}/clarifications", json={"message": "Please confirm the budget."}
    )

    row = db.execute(
        text(
            "SELECT recipient_id, message FROM notifications "
            "WHERE notification_type = 'EVENT_CLARIFICATION_REQUESTED' AND event_id = :id"
        ),
        {"id": Events.SUBMITTED},
    ).one()
    assert row.recipient_id == Users.ORGANISER.id
    assert row.message == "Please confirm the budget."


# --- AC3: status, message and notification are saved together ---------------------------------
@pytest.mark.story("4.2", ac=3)
def test_status_change_message_and_notification_are_all_recorded_together(
    coordinator_client, db: Session
):
    coordinator_client.post(
        f"/events/{Events.SUBMITTED}/clarifications", json={"message": "Please confirm the venue."}
    )

    db.expire_all()
    event_row = db.execute(
        text("SELECT status FROM events WHERE id = :id"), {"id": Events.SUBMITTED}
    ).one()
    assert event_row.status == EventStatus.CLARIFICATION_REQUESTED

    clarification = db.execute(
        text("SELECT message FROM event_clarifications WHERE event_id = :id AND kind = 'REQUEST'"),
        {"id": Events.SUBMITTED},
    ).one()
    assert clarification.message == "Please confirm the venue."

    notification = db.execute(
        text(
            "SELECT id FROM notifications "
            "WHERE notification_type = 'EVENT_CLARIFICATION_REQUESTED' AND event_id = :id"
        ),
        {"id": Events.SUBMITTED},
    ).one_or_none()
    assert notification is not None


@pytest.mark.story("4.2", ac=3)
def test_the_transition_is_recorded_in_status_history(coordinator_client, db: Session):
    coordinator_client.post(
        f"/events/{Events.SUBMITTED}/clarifications",
        json={"message": "Please confirm the AV needs."},
    )

    row = db.execute(
        text(
            "SELECT from_status, to_status, changed_by_id, reason FROM event_status_history "
            "WHERE event_id = :id AND to_status = 'CLARIFICATION_REQUESTED'"
        ),
        {"id": Events.SUBMITTED},
    ).one()
    assert row.from_status == EventStatus.UNDER_REVIEW
    assert row.changed_by_id == Users.COORDINATOR.id
    assert row.reason == "Please confirm the AV needs."


@pytest.mark.story("4.2", ac=3)
def test_request_clarification_is_recorded_in_the_audit_log(coordinator_client, db: Session):
    coordinator_client.post(
        f"/events/{Events.SUBMITTED}/clarifications",
        json={"message": "Please confirm the schedule."},
    )

    row = db.execute(
        text(
            "SELECT actor_id, details FROM audit_log "
            "WHERE action = 'EVENT_CLARIFICATION_REQUESTED' AND entity_id = :id"
        ),
        {"id": Events.SUBMITTED},
    ).one()
    assert row.actor_id == Users.COORDINATOR.id
    assert row.details["message"] == "Please confirm the schedule."


# --- AC4: the message is mandatory --------------------------------------------------------------
@pytest.mark.story("4.2", ac=4)
def test_requesting_clarification_without_a_message_is_refused(coordinator_client):
    response = coordinator_client.post(f"/events/{Events.SUBMITTED}/clarifications", json={})
    assert response.status_code == 422


@pytest.mark.story("4.2", ac=4)
def test_requesting_clarification_with_an_empty_message_is_refused(coordinator_client):
    response = coordinator_client.post(
        f"/events/{Events.SUBMITTED}/clarifications", json={"message": ""}
    )
    assert response.status_code == 422


@pytest.mark.story("4.2", ac=4)
def test_requesting_clarification_with_a_whitespace_only_message_is_refused(
    coordinator_client, db: Session
):
    response = coordinator_client.post(
        f"/events/{Events.SUBMITTED}/clarifications", json={"message": "   "}
    )

    assert response.status_code == 422
    db.expire_all()
    row = db.execute(
        text("SELECT status FROM events WHERE id = :id"), {"id": Events.SUBMITTED}
    ).one()
    assert row.status == EventStatus.UNDER_REVIEW


@pytest.mark.story("4.2", ac=4)
def test_requesting_clarification_with_an_unknown_field_is_refused(coordinator_client):
    # EventRejection and every sibling request schema sets extra="forbid" (schemas.py);
    # ClarificationRequest should too, rather than silently drop a key that looks like it might
    # do something.
    response = coordinator_client.post(
        f"/events/{Events.SUBMITTED}/clarifications",
        json={"message": "Valid message.", "status": "PLANNING"},
    )
    assert response.status_code == 422


@pytest.mark.story("4.2", ac=4)
def test_request_clarification_refuses_a_blank_message_even_bypassing_the_schema(db: Session):
    # AC4's mandatory-message rule is enforced again in the service, not only by
    # ClarificationRequest's Pydantic validator, so a caller other than this HTTP endpoint (a
    # seed script, a test factory) cannot persist a blank one.
    event = make_event(
        db, status=EventStatus.UNDER_REVIEW, assigned_coordinator_id=Users.COORDINATOR.id
    )
    coordinator = db.get(User, Users.COORDINATOR.id)

    with pytest.raises(service.MissingClarificationMessage):
        service.request_clarification(db, event, actor=coordinator, message="   ")


@pytest.mark.story("4.2", ac=4)
def test_requesting_clarification_strips_the_message(coordinator_client, db: Session):
    response = coordinator_client.post(
        f"/events/{Events.SUBMITTED}/clarifications", json={"message": "  Please confirm X.  "}
    )

    assert response.status_code == 201
    assert response.json()["message"] == "Please confirm X."
    row = db.execute(
        text("SELECT message FROM event_clarifications WHERE event_id = :id AND kind = 'REQUEST'"),
        {"id": Events.SUBMITTED},
    ).one()
    assert row.message == "Please confirm X."


# --- AC5: several rounds are allowed, kept in order --------------------------------------------
@pytest.mark.story("4.2", ac=5)
def test_a_second_round_of_clarification_is_recorded_while_still_awaiting_a_response(
    coordinator_client, db: Session
):
    # This branch implements only story 4.2, so nothing ever moves the event back to Under
    # Review - a second round has to work directly from CLARIFICATION_REQUESTED.
    first = coordinator_client.post(
        f"/events/{Events.SUBMITTED}/clarifications", json={"message": "First question."}
    )
    assert first.status_code == 201

    # Postgres's now() is fixed for the life of the test's transaction, so both rounds would
    # otherwise tie on the same instant (story 4.6's own ordering tests hit the same thing and
    # pass an explicit created_at instead); pushing the first round back a minute keeps this test
    # about the write path's ordering rather than the clock.
    db.execute(
        text(
            "UPDATE event_clarifications SET created_at = created_at - interval '1 minute' "
            "WHERE event_id = :id AND kind = 'REQUEST'"
        ),
        {"id": Events.SUBMITTED},
    )
    db.expire_all()

    second = coordinator_client.post(
        f"/events/{Events.SUBMITTED}/clarifications", json={"message": "Second question."}
    )
    assert second.status_code == 201

    thread = coordinator_client.get(f"/events/{Events.SUBMITTED}/clarifications").json()
    messages = [row["message"] for row in thread if row["kind"] == "REQUEST"]
    assert messages == ["First question.", "Second question."]


@pytest.mark.story("4.2", ac=5)
def test_a_follow_up_request_leaves_the_event_clarification_requested(
    coordinator_client, db: Session
):
    event = make_event(
        db, status=EventStatus.CLARIFICATION_REQUESTED, assigned_coordinator_id=Users.COORDINATOR.id
    )

    response = coordinator_client.post(
        f"/events/{event.id}/clarifications", json={"message": "One more thing."}
    )

    assert response.status_code == 201
    db.expire_all()
    row = db.execute(text("SELECT status FROM events WHERE id = :id"), {"id": event.id}).one()
    assert row.status == EventStatus.CLARIFICATION_REQUESTED


@pytest.mark.story("4.2", ac=5)
def test_a_follow_up_request_does_not_add_a_status_history_row(coordinator_client, db: Session):
    event = make_event(
        db, status=EventStatus.CLARIFICATION_REQUESTED, assigned_coordinator_id=Users.COORDINATOR.id
    )
    before = db.execute(
        text("SELECT count(*) FROM event_status_history WHERE event_id = :id"), {"id": event.id}
    ).scalar()

    coordinator_client.post(
        f"/events/{event.id}/clarifications", json={"message": "One more thing."}
    )

    after = db.execute(
        text("SELECT count(*) FROM event_status_history WHERE event_id = :id"), {"id": event.id}
    ).scalar()
    assert after == before


@pytest.mark.story("4.2", ac=5)
def test_a_follow_up_request_notifies_the_organiser_again(coordinator_client, db: Session):
    event = make_event(
        db, status=EventStatus.CLARIFICATION_REQUESTED, assigned_coordinator_id=Users.COORDINATOR.id
    )

    coordinator_client.post(
        f"/events/{event.id}/clarifications", json={"message": "One more thing."}
    )

    row = db.execute(
        text(
            "SELECT recipient_id, message FROM notifications "
            "WHERE notification_type = 'EVENT_CLARIFICATION_REQUESTED' AND event_id = :id"
        ),
        {"id": event.id},
    ).one()
    assert row.recipient_id == Users.ORGANISER.id
    assert row.message == "One more thing."


# --- AC6/AC7: only the assigned coordinator, only while Under Review ---------------------------
@pytest.mark.story("4.2", ac=6)
def test_a_different_coordinator_cannot_request_clarification(login_as, db: Session):
    response = login_as(Users.COORDINATOR_2).post(
        f"/events/{Events.SUBMITTED}/clarifications", json={"message": "Not my request."}
    )

    assert response.status_code == 403
    db.expire_all()
    row = db.execute(
        text("SELECT status FROM events WHERE id = :id"), {"id": Events.SUBMITTED}
    ).one()
    assert row.status == EventStatus.UNDER_REVIEW


@pytest.mark.story("4.2", ac=6)
def test_an_unassigned_request_cannot_have_clarification_requested(coordinator_client, db: Session):
    event = make_event(db, status=EventStatus.UNDER_REVIEW)  # no assigned_coordinator_id

    response = coordinator_client.post(
        f"/events/{event.id}/clarifications", json={"message": "No coordinator is assigned yet."}
    )

    assert response.status_code == 403


@pytest.mark.story("4.2", ac=6)
def test_requesting_clarification_on_a_draft_is_not_found(coordinator_client, db: Session):
    # A draft is private to its organiser (service.get_event), so even the coordinator it names
    # cannot see it, let alone ask a question about it.
    event = make_event(db, status=EventStatus.DRAFT, assigned_coordinator_id=Users.COORDINATOR.id)

    response = coordinator_client.post(
        f"/events/{event.id}/clarifications", json={"message": "Refused for the boundary check."}
    )

    assert response.status_code == 404


@pytest.mark.story("4.2", ac=6)
def test_signed_out_visitors_cannot_request_clarification(client):
    response = client.post(
        f"/events/{Events.SUBMITTED}/clarifications", json={"message": "No session."}
    )
    assert response.status_code == 401


@pytest.mark.story("4.2", ac=6)
@pytest.mark.parametrize(
    "user",
    [Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda u: u.role,
)
def test_other_roles_cannot_request_clarification(client, user):
    # Events.SUBMITTED's own organiser is included here: this branch implements only story 4.2
    # (the coordinator's request), so the route is gated on events:review alone and an organiser
    # is refused the same way any other non-coordinator role is.
    client.login(user)
    response = client.post(
        f"/events/{Events.SUBMITTED}/clarifications", json={"message": "Wrong role."}
    )
    assert response.status_code == 403


@pytest.mark.story("4.2", ac=7)
def test_requesting_clarification_on_a_missing_event_is_404(coordinator_client):
    response = coordinator_client.post(
        f"/events/{uuid.uuid4()}/clarifications", json={"message": "No event to ask."}
    )
    assert response.status_code == 404


@pytest.mark.story("4.2", ac=7)
@pytest.mark.parametrize(
    "status",
    [
        EventStatus.PLANNING,
        EventStatus.CONFIRMED,
        EventStatus.COMPLETED,
        EventStatus.CANCELLED,
        EventStatus.REJECTED,
    ],
)
def test_requesting_clarification_once_decided_is_refused(coordinator_client, db: Session, status):
    event = make_event(db, status=status, assigned_coordinator_id=Users.COORDINATOR.id)

    response = coordinator_client.post(
        f"/events/{event.id}/clarifications", json={"message": "Refused for the boundary check."}
    )

    assert response.status_code == 409
    db.expire_all()
    row = db.execute(text("SELECT status FROM events WHERE id = :id"), {"id": event.id}).one()
    assert row.status == status
    count = db.execute(
        text("SELECT count(*) FROM event_clarifications WHERE event_id = :id"), {"id": event.id}
    ).scalar()
    assert count == 0


# --- AC8: refused if reassigned or decided while composing -------------------------------------
@pytest.mark.story("4.2", ac=8)
def test_a_reassignment_racing_the_request_is_refused(db: Session):
    coordinator = db.get(User, Users.COORDINATOR.id)
    event = service.get_event(db, Events.UNDER_REVIEW, viewer=coordinator)

    # Simulates a reassignment landing between opening the page and pressing Send: the row
    # changes underneath the already-loaded (still stale in Python) `event` object.
    db.execute(
        text("UPDATE events SET assigned_coordinator_id = :other WHERE id = :id"),
        {"other": Users.COORDINATOR_2.id, "id": event.id},
    )

    with pytest.raises(service.EventNotAwaitingClarification):
        service.request_clarification(db, event, actor=coordinator, message="Still trying to ask.")


@pytest.mark.story("4.2", ac=8)
def test_a_decision_racing_the_request_is_refused(db: Session):
    # Uses the seeded Events.SUBMITTED rather than a hand-built one: request_clarification's
    # failure path calls db.rollback(), which - with no seeded baseline already committed before
    # this test's transaction began - would also undo a freshly make_event()'d row that was only
    # ever flushed, unpersisting it before the assertion runs.
    coordinator = db.get(User, Users.COORDINATOR.id)
    event = service.get_event(db, Events.SUBMITTED, viewer=coordinator)

    # Simulates the request being decided (approved/rejected) between opening the page and
    # pressing Send.
    db.execute(text("UPDATE events SET status = 'PLANNING' WHERE id = :id"), {"id": event.id})

    with pytest.raises(service.EventNotAwaitingClarification):
        service.request_clarification(db, event, actor=coordinator, message="Still trying to ask.")


@pytest.mark.story("4.2", ac=8)
def test_a_stale_request_over_http_is_refused_with_409(coordinator_client, db: Session):
    # Warms the session's identity map with the pre-race event state, the way a coordinator's
    # already-open page would hold it.
    loaded = coordinator_client.get(f"/events/{Events.UNDER_REVIEW}")
    assert loaded.status_code == 200

    db.execute(
        text("UPDATE events SET status = 'PLANNING' WHERE id = :id"), {"id": Events.UNDER_REVIEW}
    )

    response = coordinator_client.post(
        f"/events/{Events.UNDER_REVIEW}/clarifications", json={"message": "Too late."}
    )

    assert response.status_code == 409, response.text
