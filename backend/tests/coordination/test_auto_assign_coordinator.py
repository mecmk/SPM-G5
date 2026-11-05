"""Story 5.1 (extended, f5.1.1) - be: what submission does about a coordinator.

5.1 extended to assign a coordinator automatically, in round-robin order, on submission. Story 5.4
replaced that (5.4 AC9, replacing 5.1 AC1, AC2 and AC13; PO decision, Checkpoint 1): a submitted
request now waits unassigned in the Event Coordinator Lead's queue, and only the Lead assigns it.
The round-robin tests went with the round-robin code; the queue, the Lead's assignment and the
refusals are tested in test_unassigned_queue.py.

Each criterion below is tested as it reads now that nobody is assigned on submission:

Boundary
AC5  With no active coordinators, the event is still submitted and left unassigned.

Edge
AC7  Saving or editing a draft never assigns a coordinator.
AC8  Resubmitting after clarification keeps the current coordinator: the organiser answering the
     coordinator's question (4.3) leaves the assignment as it was.
AC9  Submission never overrides an event that already has a coordinator: submitting it again is
     refused and writes nothing.

Permission
AC12 An organiser cannot choose the coordinator through the submit request.

Conflict
AC14 Simultaneous submissions each land Under Review, and neither is given a coordinator.
AC15 Submission is one transaction: if a write in it fails, the whole submission is rolled back.

What submission does about a hand assignment (AC1-AC4, AC6, AC10, AC11, AC13) is in
test_coordinator_assignment.py.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.common.audit import AuditLog
from app.events import service
from app.events.models import Event, EventStatus
from app.events.schemas import EventCreate
from tests.support.factories import (
    create_event_request,
    create_submittable_event_request,
    submittable_event_request_payload,
)
from tests.support.seed import Users


def _open_assignment_row(db: Session, event_id):
    return db.execute(
        text(
            "SELECT coordinator_id, assigned_by_id, assigned_at, note"
            " FROM event_coordinator_assignments"
            " WHERE event_id = :e AND unassigned_at IS NULL"
        ),
        {"e": event_id},
    ).one_or_none()


def _assignment_rows(db: Session, event_id) -> list:
    """Every assignment the event has had, open or closed, oldest first."""
    return db.execute(
        text(
            "SELECT coordinator_id, assigned_by_id, assigned_at, unassigned_at"
            " FROM event_coordinator_assignments WHERE event_id = :e ORDER BY assigned_at"
        ),
        {"e": event_id},
    ).all()


def _event_row(db: Session, event_id):
    db.expire_all()
    return db.execute(
        text("SELECT status, submitted_at, assigned_coordinator_id FROM events WHERE id = :e"),
        {"e": event_id},
    ).one()


def _submitted_and_assigned_to_chloe(login_as) -> str:
    """A fresh request of Olivia's, submitted, then given to Chloe by the Lead (5.4 AC3)."""
    organiser = login_as(Users.ORGANISER)
    draft = create_submittable_event_request(organiser)
    assert organiser.post(f"/events/{draft['id']}/submit").status_code == 200
    assigned = login_as(Users.LEAD).put(
        f"/events/{draft['id']}/coordinator", json={"coordinator_id": str(Users.COORDINATOR.id)}
    )
    assert assigned.status_code == 200, assigned.text
    return draft["id"]


# --- AC5: no active coordinators -------------------------------------------------------------
@pytest.mark.story("5.1", ac=5)
def test_with_no_active_coordinator_the_request_is_still_submitted_unassigned(
    login_as, db: Session
):
    db.execute(text("UPDATE users SET is_active = FALSE WHERE role_code = 'EVENT_COORDINATOR'"))
    organiser = login_as(Users.ORGANISER)
    draft = create_submittable_event_request(organiser)

    response = organiser.post(f"/events/{draft['id']}/submit")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == EventStatus.UNDER_REVIEW
    assert response.json()["assigned_coordinator_id"] is None
    row = _event_row(db, draft["id"])
    assert row.status == EventStatus.UNDER_REVIEW
    assert row.submitted_at is not None
    assert row.assigned_coordinator_id is None
    assert _open_assignment_row(db, draft["id"]) is None


# --- AC7: a draft is never assigned, saved or edited -----------------------------------------
@pytest.mark.story("5.1", ac=7)
def test_creating_a_draft_never_assigns_a_coordinator(organiser_client, db: Session):
    draft = create_event_request(organiser_client)

    assert draft["assigned_coordinator_id"] is None
    assert _open_assignment_row(db, draft["id"]) is None


@pytest.mark.story("5.1", ac=7)
def test_editing_a_draft_never_assigns_a_coordinator(organiser_client, db: Session):
    draft = create_event_request(organiser_client)

    response = organiser_client.patch(f"/events/{draft['id']}", json={"description": "Updated."})

    assert response.status_code == 200, response.text
    assert response.json()["assigned_coordinator_id"] is None
    assert _open_assignment_row(db, draft["id"]) is None


# --- AC8: answering a clarification keeps the coordinator ------------------------------------
@pytest.mark.story("5.1", ac=8)
def test_answering_a_clarification_keeps_the_current_coordinator(login_as, db: Session):
    event_id = _submitted_and_assigned_to_chloe(login_as)
    before = _assignment_rows(db, event_id)
    asked = login_as(Users.COORDINATOR).post(
        f"/events/{event_id}/clarifications", json={"message": "How many will attend?"}
    )
    assert asked.status_code == 201, asked.text

    answered = login_as(Users.ORGANISER).post(
        f"/events/{event_id}/clarifications/responses", json={"message": "About 60."}
    )

    assert answered.status_code == 201, answered.text
    row = _event_row(db, event_id)
    assert row.status == EventStatus.CLARIFICATION_REQUESTED
    assert row.assigned_coordinator_id == Users.COORDINATOR.id
    # The same one assignment, made by the Lead, still open: nothing was written or reopened.
    assert _assignment_rows(db, event_id) == before
    assert [(r.coordinator_id, r.assigned_by_id, r.unassigned_at) for r in before] == [
        (Users.COORDINATOR.id, Users.LEAD.id, None)
    ]
    shown = login_as(Users.ORGANISER).get(f"/events/{event_id}/coordinator").json()
    assert shown["coordinator_name"] == Users.COORDINATOR.full_name


# --- AC9: submission never overrides a coordinator -------------------------------------------
@pytest.mark.story("5.1", ac=9)
def test_submitting_an_assigned_request_again_keeps_its_coordinator(login_as, db: Session):
    event_id = _submitted_and_assigned_to_chloe(login_as)
    before = _assignment_rows(db, event_id)

    again = login_as(Users.ORGANISER).post(f"/events/{event_id}/submit")

    assert again.status_code == 409, again.text
    assert _event_row(db, event_id).assigned_coordinator_id == Users.COORDINATOR.id
    assert _assignment_rows(db, event_id) == before


# --- AC12: an organiser cannot choose the coordinator through submit -------------------------
@pytest.mark.story("5.1", ac=12)
def test_submit_ignores_a_coordinator_chosen_by_the_organiser(organiser_client):
    draft = create_submittable_event_request(organiser_client)

    response = organiser_client.post(
        f"/events/{draft['id']}/submit", json={"coordinator_id": str(Users.COORDINATOR.id)}
    )

    assert response.status_code == 200, response.text
    # Story 5.4 AC9: nobody is assigned on submission, and naming Chloe in the body does not
    # change that.
    assert response.json()["assigned_coordinator_id"] is None


# --- AC14: simultaneous submissions ----------------------------------------------------------
def _committed_draft(engine, organiser_id: uuid.UUID) -> uuid.UUID:
    """A submittable draft of ``organiser_id``'s, committed so another connection can submit it."""
    with Session(engine) as session:
        organiser = session.get(User, organiser_id)
        payload = submittable_event_request_payload(name=f"Race {uuid.uuid4().hex[:8]}")
        event = service.create_event(session, EventCreate(**payload), actor=organiser)
        session.commit()
        return event.id


def _remove_events(engine, event_ids: list[uuid.UUID]) -> None:
    """Delete the events and their audit entries; every other row they own cascades."""
    with Session(engine) as session:
        session.execute(delete(AuditLog).where(AuditLog.entity_id.in_(event_ids)))
        session.execute(delete(Event).where(Event.id.in_(event_ids)))
        session.commit()


@pytest.mark.story("5.1", ac=14)
def test_simultaneous_submissions_each_land_without_a_coordinator(engine):
    """Two organisers submit at the same moment, each in a transaction of their own. Both are
    accepted, and neither is given a coordinator out of turn: each waits for the Lead."""
    owners = (Users.ORGANISER.id, Users.ORGANISER_2.id)
    event_ids = [_committed_draft(engine, owner) for owner in owners]
    start = threading.Barrier(len(owners))

    def submit(event_id: uuid.UUID, owner: uuid.UUID) -> str:
        with Session(engine) as session:
            actor = session.get(User, owner)
            start.wait()
            return service.submit_event(session, event_id, actor=actor).status

    try:
        with ThreadPoolExecutor(max_workers=len(owners)) as pool:
            futures = [pool.submit(submit, e, o) for e, o in zip(event_ids, owners, strict=True)]
            outcomes = [future.result(timeout=30) for future in futures]

        assert outcomes == [EventStatus.UNDER_REVIEW, EventStatus.UNDER_REVIEW]
        with Session(engine) as session:
            rows = session.execute(
                select(Event.status, Event.assigned_coordinator_id).where(Event.id.in_(event_ids))
            ).all()
            assert sorted(rows) == [(EventStatus.UNDER_REVIEW, None)] * 2
            assignments = session.execute(
                text("SELECT count(*) FROM event_coordinator_assignments WHERE event_id = ANY(:e)"),
                {"e": event_ids},
            ).scalar()
            assert assignments == 0
    finally:
        _remove_events(engine, event_ids)


# --- AC15: one transaction ---------------------------------------------------------------------
@pytest.mark.story("5.1", ac=15)
def test_a_failed_write_rolls_the_whole_submission_back(organiser_client, db: Session, monkeypatch):
    """The Leads' notice is the submission's last write before the commit (20.1 AC1); when it
    fails, the move to Under Review, its status history and its audit entry go with it."""

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated failure notifying the Leads")

    draft = create_submittable_event_request(organiser_client)
    monkeypatch.setattr(service, "notify", _boom)

    with pytest.raises(RuntimeError):
        organiser_client.post(f"/events/{draft['id']}/submit")
    db.rollback()  # mirrors app.db.get_db's real teardown

    row = _event_row(db, draft["id"])
    assert (row.status, row.submitted_at, row.assigned_coordinator_id) == (
        EventStatus.DRAFT,
        None,
        None,
    )
    assert _assignment_rows(db, draft["id"]) == []
    history = db.execute(
        text("SELECT to_status FROM event_status_history WHERE event_id = :e"), {"e": draft["id"]}
    ).scalars()
    assert list(history) == [EventStatus.DRAFT]
    actions = db.scalars(
        select(AuditLog.action).where(AuditLog.entity_id == uuid.UUID(draft["id"]))
    ).all()
    assert actions == ["EVENT_CREATED"]
