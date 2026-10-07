"""Story 4.3 - be: respond to a clarification request.

Happy path
AC1  While clarification is outstanding, the organiser sees the message, can add a response.
AC2  A response notifies the coordinator. The clarification and response stay visible and
     read-only.
AC3  The server saves the response.

Boundary
AC4  The message is mandatory; blank or whitespace-only messages are refused.
AC5  It is trimmed, and capped at 2000 characters.

Edge
AC6  Several response rounds are allowed, and each is kept in the thread in order.
AC7  After a 5.2 reassignment, the notification goes to the currently assigned coordinator, not
     the one who asked.
AC8  The response, its notification and its audit entry are written in one transaction: a failed
     notification saves no response.
AC9  The coordinator can still approve or reject after a response.

Permission
AC10 Only the owning organiser can respond, and only while a response is awaited.

Conflict
AC11 Sending is refused if the event was cancelled, approved, or rejected in the meantime.

A response leaves the event at CLARIFICATION_REQUESTED: the organiser may answer more than once,
and the coordinator may ask again, until the coordinator decides.

Excluded, with reason:
* AC1's "sees the message" and AC2's "visible and read-only" are page behaviour - the thread and
  the response form - proven in tests/e2e/respond-to-clarification.spec.ts. Reading the thread is
  story 4.6's test_decision_history.py; its read-only API (no edit or delete route) is 4.6 AC3.
* AC4's page-side check (a blank Send refused before any request) is in the same e2e spec.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.events import service
from app.events.models import Event, EventStatus
from app.events.schemas import CLARIFICATION_MESSAGE_MAX_LENGTH
from tests.support.factories import make_clarification, make_event
from tests.support.seed import Events, Users


def _awaiting_response(db: Session, **overrides) -> Event:
    """A fresh event of organiser 1's, assigned to coordinator 1, awaiting a response."""
    return make_event(
        db,
        status=EventStatus.CLARIFICATION_REQUESTED,
        assigned_coordinator_id=Users.COORDINATOR.id,
        **overrides,
    )


def _respond(client, event_id, message="Headcount is 120."):
    return client.post(f"/events/{event_id}/clarifications/responses", json={"message": message})


def _count(db: Session, from_clause: str, event_id: uuid.UUID) -> int:
    """Rows matching ``from_clause``: a table name plus a WHERE clause binding ``:id``."""
    return db.execute(text(f"SELECT count(*) FROM {from_clause}"), {"id": event_id}).scalar()


def _status(db: Session, event_id: uuid.UUID) -> str:
    db.expire_all()
    return db.execute(text("SELECT status FROM events WHERE id = :id"), {"id": event_id}).scalar()


_RESPONSES = "event_clarifications WHERE event_id = :id AND kind = 'RESPONSE'"


# --- AC3: the server saves the response -------------------------------------------------------
@pytest.mark.story("4.3", ac=3)
def test_responding_is_recorded_with_author_and_time(organiser_client, db: Session):
    event = _awaiting_response(db)

    response = _respond(organiser_client, event.id)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "RESPONSE"
    assert body["author_id"] == str(Users.ORGANISER.id)
    assert body["author_name"] == Users.ORGANISER.full_name
    assert body["message"] == "Headcount is 120."
    assert body["created_at"] is not None


@pytest.mark.story("4.3", ac=3)
def test_the_response_is_persisted(organiser_client, db: Session):
    event = _awaiting_response(db)

    _respond(organiser_client, event.id)

    row = db.execute(text(f"SELECT author_id, message FROM {_RESPONSES}"), {"id": event.id}).one()
    assert row.author_id == Users.ORGANISER.id
    assert row.message == "Headcount is 120."


@pytest.mark.story("4.3", ac=3)
def test_responding_leaves_the_event_awaiting_a_decision(organiser_client, db: Session):
    event = _awaiting_response(db)
    history_before = _count(db, "event_status_history WHERE event_id = :id", event.id)

    response = _respond(organiser_client, event.id)

    assert response.status_code == 201, response.text
    assert _status(db, event.id) == EventStatus.CLARIFICATION_REQUESTED
    assert _count(db, "event_status_history WHERE event_id = :id", event.id) == history_before


# --- AC2: the coordinator is notified -----------------------------------------------------------
@pytest.mark.story("4.3", ac=2)
def test_the_assigned_coordinator_is_notified(organiser_client, db: Session):
    event = _awaiting_response(db)

    _respond(organiser_client, event.id)

    row = db.execute(
        text(
            "SELECT recipient_id, message FROM notifications "
            "WHERE notification_type = 'EVENT_CLARIFICATION_RESPONDED' AND event_id = :id"
        ),
        {"id": event.id},
    ).one()
    assert row.recipient_id == Users.COORDINATOR.id
    assert row.message == "Headcount is 120."


@pytest.mark.story("4.3", ac=2)
def test_the_response_is_recorded_in_the_audit_log(organiser_client, db: Session):
    event = _awaiting_response(db)

    _respond(organiser_client, event.id)

    row = db.execute(
        text(
            "SELECT actor_id, details FROM audit_log "
            "WHERE action = 'EVENT_CLARIFICATION_RESPONDED' AND entity_id = :id"
        ),
        {"id": event.id},
    ).one()
    assert row.actor_id == Users.ORGANISER.id
    assert row.details["message"] == "Headcount is 120."


# --- AC4: the message is mandatory --------------------------------------------------------------
@pytest.mark.story("4.3", ac=4)
@pytest.mark.parametrize("body", [{}, {"message": ""}, {"message": "   "}], ids=str)
def test_a_missing_or_blank_message_is_refused(organiser_client, db: Session, body):
    event = _awaiting_response(db)

    response = organiser_client.post(f"/events/{event.id}/clarifications/responses", json=body)

    assert response.status_code == 422
    assert _count(db, _RESPONSES, event.id) == 0


@pytest.mark.story("4.3", ac=4)
def test_respond_refuses_a_blank_message_even_bypassing_the_schema(db: Session):
    event = _awaiting_response(db)
    organiser = db.get(User, Users.ORGANISER.id)

    with pytest.raises(service.MissingClarificationMessage):
        service.respond_to_clarification(db, event.id, actor=organiser, message="   ")


# --- AC5: trimmed, capped at 2000 characters ----------------------------------------------------
@pytest.mark.story("4.3", ac=5)
def test_the_response_is_stored_trimmed(organiser_client, db: Session):
    event = _awaiting_response(db)

    response = _respond(organiser_client, event.id, "  Headcount is 120.  ")

    assert response.json()["message"] == "Headcount is 120."
    row = db.execute(text(f"SELECT message FROM {_RESPONSES}"), {"id": event.id}).one()
    assert row.message == "Headcount is 120."


@pytest.mark.story("4.3", ac=5)
def test_a_response_at_the_length_limit_is_accepted(organiser_client, db: Session):
    event = _awaiting_response(db)

    response = _respond(organiser_client, event.id, "x" * CLARIFICATION_MESSAGE_MAX_LENGTH)

    assert response.status_code == 201, response.text


@pytest.mark.story("4.3", ac=5)
def test_an_over_long_response_is_refused(organiser_client, db: Session):
    event = _awaiting_response(db)

    response = _respond(organiser_client, event.id, "x" * (CLARIFICATION_MESSAGE_MAX_LENGTH + 1))

    assert response.status_code == 422
    assert _count(db, _RESPONSES, event.id) == 0


@pytest.mark.story("4.3", ac=5)
def test_a_response_with_an_unknown_field_is_refused(organiser_client, db: Session):
    event = _awaiting_response(db)

    response = organiser_client.post(
        f"/events/{event.id}/clarifications/responses",
        json={"message": "Valid.", "status": "UNDER_REVIEW"},
    )

    assert response.status_code == 422


# --- AC6: several rounds, kept in order ---------------------------------------------------------
@pytest.mark.story("4.3", ac=6)
def test_the_organiser_may_respond_more_than_once(organiser_client, db: Session):
    event = _awaiting_response(db)

    first = _respond(organiser_client, event.id, "Headcount is 120.")
    second = _respond(organiser_client, event.id, "Correction: 130.")

    assert first.status_code == 201
    assert second.status_code == 201
    assert _count(db, _RESPONSES, event.id) == 2
    assert _status(db, event.id) == EventStatus.CLARIFICATION_REQUESTED


@pytest.mark.story("4.3", ac=6)
def test_alternating_rounds_are_kept_in_order(login_as, db: Session):
    """Request, response, request, response - each written through its own endpoint. Postgres's
    now() is fixed for the test's transaction, so every row would tie on created_at; each earlier
    row is pushed back a minute before the next is written (4.2's ordering test does the same)."""
    event = _awaiting_response(db)
    make_clarification(db, event_id=event.id, kind="REQUEST", message="Q1")

    def _age_existing():
        db.execute(
            text(
                "UPDATE event_clarifications SET created_at = created_at - interval '1 minute' "
                "WHERE event_id = :id"
            ),
            {"id": event.id},
        )
        db.expire_all()

    _age_existing()
    assert _respond(login_as(Users.ORGANISER), event.id, "A1").status_code == 201
    _age_existing()
    asked = login_as(Users.COORDINATOR).post(
        f"/events/{event.id}/clarifications", json={"message": "Q2"}
    )
    assert asked.status_code == 201
    _age_existing()
    assert _respond(login_as(Users.ORGANISER), event.id, "A2").status_code == 201

    thread = login_as(Users.ORGANISER).get(f"/events/{event.id}/clarifications").json()
    assert [(row["kind"], row["message"]) for row in thread] == [
        ("REQUEST", "Q1"),
        ("RESPONSE", "A1"),
        ("REQUEST", "Q2"),
        ("RESPONSE", "A2"),
    ]


# --- AC7: the currently assigned coordinator is notified ----------------------------------------
@pytest.mark.story("4.3", ac=7)
def test_after_a_reassignment_the_new_coordinator_is_notified(login_as, db: Session):
    # The seeded event, whose question coordinator 1 asked: a make_event() row has no assignment
    # history, which story 5.2's reassignment needs.
    event_id = Events.CLARIFICATION_REQUESTED
    reassigned = login_as(Users.COORDINATOR).put(
        f"/events/{event_id}/coordinator", json={"coordinator_id": str(Users.COORDINATOR_2.id)}
    )
    assert reassigned.status_code == 200, reassigned.text

    assert _respond(login_as(Users.ORGANISER), event_id).status_code == 201

    recipients = db.scalars(
        text(
            "SELECT recipient_id FROM notifications "
            "WHERE notification_type = 'EVENT_CLARIFICATION_RESPONDED' AND event_id = :id"
        ),
        {"id": event_id},
    ).all()
    assert recipients == [Users.COORDINATOR_2.id]


# --- AC8: one transaction -----------------------------------------------------------------------
@pytest.mark.story("4.3", ac=8)
def test_a_failed_notification_saves_no_response(organiser_client, db: Session, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated failure notifying the coordinator")

    monkeypatch.setattr(service, "notify", _boom)
    # The seeded thread already holds a response; only a new one would be the failure.
    before = _count(db, _RESPONSES, Events.CLARIFICATION_REQUESTED)

    with pytest.raises(RuntimeError):
        _respond(organiser_client, Events.CLARIFICATION_REQUESTED)
    db.rollback()  # mirrors app.db.get_db's real teardown

    assert _count(db, _RESPONSES, Events.CLARIFICATION_REQUESTED) == before
    assert (
        _count(
            db,
            "audit_log WHERE entity_id = :id AND action = 'EVENT_CLARIFICATION_RESPONDED'",
            Events.CLARIFICATION_REQUESTED,
        )
        == 0
    )
    assert _status(db, Events.CLARIFICATION_REQUESTED) == EventStatus.CLARIFICATION_REQUESTED


# --- AC9: the coordinator can still decide ------------------------------------------------------
@pytest.mark.story("4.3", ac=9)
@pytest.mark.parametrize(
    ("action", "body", "to_status"),
    [
        ("approve", None, EventStatus.PLANNING),
        ("reject", {"reason": "No suitable venue."}, EventStatus.REJECTED),
    ],
    ids=["approve", "reject"],
)
def test_the_coordinator_can_decide_after_a_response(
    login_as, db: Session, action, body, to_status
):
    event = _awaiting_response(db)
    assert _respond(login_as(Users.ORGANISER), event.id).status_code == 201

    decided = login_as(Users.COORDINATOR).post(f"/events/{event.id}/{action}", json=body)

    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == to_status


# --- AC10: the owning organiser only, only while a response is awaited --------------------------
@pytest.mark.story("4.3", ac=10)
def test_another_organiser_cannot_see_the_event_to_respond(login_as, db: Session):
    event = _awaiting_response(db)

    response = _respond(login_as(Users.ORGANISER_2), event.id)

    assert response.status_code == 404
    assert _count(db, _RESPONSES, event.id) == 0


@pytest.mark.story("4.3", ac=10)
def test_the_assigned_coordinator_cannot_respond(coordinator_client, db: Session):
    event = _awaiting_response(db)

    response = _respond(coordinator_client, event.id)

    assert response.status_code == 403
    assert _count(db, _RESPONSES, event.id) == 0


@pytest.mark.story("4.3", ac=10)
@pytest.mark.parametrize(
    "user",
    [Users.COORDINATOR_2, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda u: u.email,
)
def test_other_roles_cannot_respond(login_as, db: Session, user):
    event = _awaiting_response(db)

    response = _respond(login_as(user), event.id)

    assert response.status_code == 403


@pytest.mark.story("4.3", ac=10)
def test_signed_out_visitors_cannot_respond(client):
    response = _respond(client, Events.CLARIFICATION_REQUESTED)
    assert response.status_code == 401


@pytest.mark.story("4.3", ac=10)
def test_responding_to_a_missing_event_is_404(organiser_client):
    response = _respond(organiser_client, uuid.uuid4())
    assert response.status_code == 404


@pytest.mark.story("4.3", ac=10)
@pytest.mark.parametrize(
    "status",
    [
        EventStatus.DRAFT,
        EventStatus.UNDER_REVIEW,
        EventStatus.PLANNING,
        EventStatus.REJECTED,
        EventStatus.CANCELLED,
    ],
)
def test_responding_when_no_response_is_awaited_is_refused(organiser_client, db: Session, status):
    event = make_event(db, status=status, assigned_coordinator_id=Users.COORDINATOR.id)

    response = _respond(organiser_client, event.id)

    assert response.status_code == 409, response.text
    assert _status(db, event.id) == status
    assert _count(db, _RESPONSES, event.id) == 0


# --- AC11: refused if cancelled, approved or rejected in the meantime ---------------------------
@pytest.mark.story("4.3", ac=11)
@pytest.mark.parametrize(
    "status", [EventStatus.CANCELLED, EventStatus.PLANNING, EventStatus.REJECTED]
)
def test_a_status_change_racing_the_response_is_refused(db: Session, status):
    # Uses the seeded event, not make_event(): the refusal path rolls back, which would also undo
    # a row that was only ever flushed (see 4.2's test_a_decision_racing_the_request_is_refused).
    organiser = db.get(User, Users.ORGANISER.id)
    event = service.get_event(db, Events.CLARIFICATION_REQUESTED, viewer=organiser)

    # The event moves on between opening the page and pressing Send; `event` is still stale.
    db.execute(
        text("UPDATE events SET status = :status WHERE id = :id"),
        {"status": status, "id": event.id},
    )
    before = _count(db, _RESPONSES, event.id)  # the seeded thread already holds a response

    with pytest.raises(service.EventNotAwaitingResponse):
        service.respond_to_clarification(db, event.id, actor=organiser, message="Too late.")
    assert _count(db, _RESPONSES, event.id) == before


@pytest.mark.story("4.3", ac=11)
def test_a_stale_response_over_http_is_refused_with_409(organiser_client, db: Session):
    # Holds the pre-race event in the request's session, the way the organiser's open page holds
    # it, so the POST reaches the race guard rather than the ordinary status check.
    held = db.get(Event, Events.CLARIFICATION_REQUESTED)
    assert held.status == EventStatus.CLARIFICATION_REQUESTED

    db.execute(
        text("UPDATE events SET status = 'CANCELLED' WHERE id = :id"),
        {"id": Events.CLARIFICATION_REQUESTED},
    )

    response = _respond(organiser_client, Events.CLARIFICATION_REQUESTED, "Too late.")

    assert response.status_code == 409, response.text
