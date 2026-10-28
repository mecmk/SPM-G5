"""Story 7.4 - be: an Event Organiser sees what was changed on their event and by whom.

AC1 Each saved change records the field, old and new values, who made it (with role) and when.
    Changes are listed newest first.
AC2 History entries are written on the server as part of the same save.
AC3 An event with no changes shows "No changes yet". Long values are shortened, with an option to
    expand.
AC4 Saving several fields at once creates one entry per field under the same time. Changes that
    came from a change request show its reference.
AC5 Visible to the owning organiser and the assigned coordinator; internal-notes changes are shown
    only to coordinators. Entries cannot be edited or deleted.
AC6 The history API is read-only and filtered by role: organisers do not receive internal-notes
    changes.
AC7 Saves made in quick succession are recorded in the order they happened, and none are lost.

Excluded, with reason:
* AC3's "No changes yet" and the shortened long values are wording and layout on the page,
  covered in tests/e2e/event-change-history.spec.ts; here AC3 is the empty list behind them.
* Draft edits before submission are not part of the history (CL-174), nor are the Equipment
  section's own saves (15.1); the history covers the event's details and approved change requests.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, object_session

from app.auth.models import User
from app.change_requests.models import EventChangeRequest
from app.common.audit import AuditLog
from app.config import settings
from app.events import schemas, service
from app.events.models import Event, EventChange, EventStatus
from app.main import app
from tests.support.change_requests import approve_as_seen
from tests.support.factories import (
    create_event_request,
    future_datetime,
    make_equipment_type,
    make_event,
)
from tests.support.seed import Events, Users

ROUTE = "/events/{event_id}/changes"
EDIT_OR_DELETE_METHODS = {"PUT", "PATCH", "DELETE"}
_ANY_FINGERPRINT = "not-assessed"
PICTURE_ROUTE = "/events/{event_id}/review-details/cover-image"
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def upload_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    return tmp_path


def _history(client, event_id) -> list[dict]:
    response = client.get(ROUTE.format(event_id=event_id))
    assert response.status_code == 200, response.text
    return response.json()


def _correct(client, event_id, **changes):
    event = client.get(f"/events/{event_id}").json()
    response = client.patch(
        f"/events/{event_id}/review-details",
        json={"expected_updated_at": event["updated_at"], **changes},
    )
    assert response.status_code == 200, response.text


def _notes(client, event_id, notes: str | None):
    response = client.patch(
        f"/events/{event_id}/routine-information", json={"internal_notes": notes}
    )
    assert response.status_code == 200, response.text


def _upload_correction_picture(client, event_id):
    event = client.get(f"/events/{event_id}").json()
    response = client.put(
        PICTURE_ROUTE.format(event_id=event_id),
        params={"expected_updated_at": event["updated_at"]},
        files={"file": ("cover.png", _PNG, "image/png")},
    )
    assert response.status_code == 200, response.text
    return response.json()["cover_image_url"]


def _planning_event(db: Session, **overrides) -> Event:
    start = overrides.pop("starts_at", future_datetime(days=60))
    return make_event(
        db,
        status=EventStatus.PLANNING,
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        expected_attendance=100,
        assigned_coordinator_id=Users.COORDINATOR.id,
        **overrides,
    )


def _raise_and_approve(login_as, db: Session, event: Event, field: str, proposed) -> dict:
    """Olivia raises ``proposed`` through 19.1's endpoint and Chloe approves it. Returns the
    request as raised, whose ``current_value`` is the value the approval replaces."""
    raised = login_as(Users.ORGANISER).post(
        f"/events/{event.id}/change-requests",
        json={"field": field, "proposed": proposed, "reason": "Plans have changed."},
    )
    assert raised.status_code == 201, raised.text
    request = db.get(EventChangeRequest, uuid.UUID(raised.json()["id"]))
    object_session(request).commit()
    approved = approve_as_seen(
        login_as(Users.COORDINATOR), event.id, request.id, fallback=_ANY_FINGERPRINT
    )
    assert approved.status_code == 200, approved.text
    return raised.json()


# --- AC1: field, values, who with role, when; newest first ----------------------------------
@pytest.mark.story("7.4", ac=1)
def test_a_correction_is_recorded_with_its_values_author_and_role(coordinator_client):
    _correct(coordinator_client, Events.SUBMITTED, expected_attendance=80)

    [entry] = _history(coordinator_client, Events.SUBMITTED)
    assert entry["field"] == "expected_attendance"
    assert entry["old_value"] == 60
    assert entry["new_value"] == 80
    assert entry["changed_by_name"] == Users.COORDINATOR.full_name
    assert entry["changed_by_role_name"] == "Event Coordinator"
    assert entry["changed_at"] is not None
    assert entry["change_request_id"] is None


@pytest.mark.story("7.4", ac=1)
def test_changes_are_listed_newest_first(coordinator_client):
    _correct(coordinator_client, Events.SUBMITTED, expected_attendance=80)
    _correct(coordinator_client, Events.SUBMITTED, expected_attendance=90)

    entries = _history(coordinator_client, Events.SUBMITTED)
    assert [e["new_value"] for e in entries] == [90, 80]


@pytest.mark.story("7.4", ac=1)
def test_the_organisers_contact_edit_is_recorded_with_their_role(login_as):
    organiser = login_as(Users.ORGANISER_2)
    response = organiser.patch(
        f"/events/{Events.APPROVED}/point-of-contact", json={"contact_email": "nora@nimbus.example"}
    )
    assert response.status_code == 200, response.text

    [entry] = _history(organiser, Events.APPROVED)
    assert entry["field"] == "contact_email"
    assert entry["new_value"] == "nora@nimbus.example"
    assert entry["changed_by_name"] == Users.ORGANISER_2.full_name
    assert entry["changed_by_role_name"] == "Event Organiser"


# --- AC2: written by the save itself, and only by a save that lands -------------------------
@pytest.mark.story("7.4", ac=2)
def test_a_refused_correction_writes_no_history(coordinator_client):
    event = coordinator_client.get(f"/events/{Events.SUBMITTED}").json()
    _correct(coordinator_client, Events.SUBMITTED, expected_attendance=80)

    stale = coordinator_client.patch(
        f"/events/{Events.SUBMITTED}/review-details",
        json={"expected_updated_at": event["updated_at"], "expected_attendance": 99},
    )

    assert stale.status_code == 409, stale.text
    assert [e["new_value"] for e in _history(coordinator_client, Events.SUBMITTED)] == [80]


@pytest.mark.story("7.4", ac=2)
def test_a_save_that_changes_nothing_writes_no_history(coordinator_client):
    _notes(coordinator_client, Events.SUBMITTED, "Caterer booked.")
    _notes(coordinator_client, Events.SUBMITTED, "Caterer booked.")

    assert len(_history(coordinator_client, Events.SUBMITTED)) == 1


# --- AC3: nothing changed yet -----------------------------------------------------------------
@pytest.mark.story("7.4", ac=3)
def test_an_event_with_no_changes_has_an_empty_history(coordinator_client, organiser_client):
    assert _history(coordinator_client, Events.SUBMITTED) == []
    assert _history(organiser_client, Events.SUBMITTED) == []


# --- AC4: one entry per field, one time per save; a change request's reference ----------------
@pytest.mark.story("7.4", ac=4)
def test_several_fields_saved_together_share_one_time(coordinator_client):
    _correct(
        coordinator_client,
        Events.SUBMITTED,
        name="Data Literacy Bootcamp",
        expected_attendance=80,
    )

    entries = _history(coordinator_client, Events.SUBMITTED)
    assert sorted(e["field"] for e in entries) == ["expected_attendance", "name"]
    assert len({e["changed_at"] for e in entries}) == 1


@pytest.mark.story("7.4", ac=4)
def test_an_approved_change_request_records_its_reference(login_as, db: Session):
    start = future_datetime(days=60)
    event = make_event(
        db,
        status=EventStatus.PLANNING,
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        expected_attendance=100,
        assigned_coordinator_id=Users.COORDINATOR.id,
    )
    new_start, new_end = start + timedelta(days=1), start + timedelta(days=1, hours=9)
    raised = login_as(Users.ORGANISER).post(
        f"/events/{event.id}/change-requests",
        json={
            "field": "schedule",
            "proposed": {"starts_at": new_start.isoformat(), "ends_at": new_end.isoformat()},
            "reason": "Plans have changed.",
        },
    )
    assert raised.status_code == 201, raised.text
    request = db.get(EventChangeRequest, uuid.UUID(raised.json()["id"]))
    object_session(request).commit()

    coordinator = login_as(Users.COORDINATOR)
    approved = approve_as_seen(coordinator, event.id, request.id, fallback=_ANY_FINGERPRINT)
    assert approved.status_code == 200, approved.text

    entries = _history(coordinator, event.id)
    assert sorted(e["field"] for e in entries) == ["ends_at", "starts_at"]
    assert {e["change_request_id"] for e in entries} == {str(request.id)}
    assert {e["changed_by_role_name"] for e in entries} == {"Event Coordinator"}


@pytest.mark.story("7.4", ac=4)
@pytest.mark.parametrize("field", ["expected_attendance", "venue_requirements", "equipment"])
def test_an_approved_change_records_the_value_it_replaced(login_as, db: Session, field):
    event = _planning_event(db)
    start = event.starts_at
    proposed = {
        "expected_attendance": 140,
        "venue_requirements": [
            {
                "id": None,
                "name": "Main venue",
                "capacity": 100,
                "starts_at": start.isoformat(),
                "ends_at": (start + timedelta(hours=8)).isoformat(),
                "layout_code": None,
                "facilities": [],
                "notes": None,
            }
        ],
        "equipment": [
            {"equipment_type_code": make_equipment_type(db, total_quantity=10).code, "quantity": 2}
        ],
    }[field]

    raised = _raise_and_approve(login_as, db, event, field, proposed)

    [entry] = _history(login_as(Users.COORDINATOR), event.id)
    assert entry["field"] == field
    assert entry["old_value"] == raised["current_value"]
    assert entry["new_value"] != entry["old_value"]


@pytest.mark.story("7.4", ac=4)
def test_an_approved_schedule_change_records_only_the_part_that_moved(login_as, db: Session):
    event = _planning_event(db)
    new_start = event.starts_at - timedelta(hours=1)

    _raise_and_approve(
        login_as,
        db,
        event,
        "schedule",
        {"starts_at": new_start.isoformat(), "ends_at": event.ends_at.isoformat()},
    )

    [entry] = _history(login_as(Users.COORDINATOR), event.id)
    assert entry["field"] == "starts_at"


@pytest.mark.story("7.4", ac=1)
def test_a_correction_that_replaces_the_cover_picture_is_recorded(coordinator_client, upload_dir):
    url = _upload_correction_picture(coordinator_client, Events.SUBMITTED)

    [entry] = _history(coordinator_client, Events.SUBMITTED)
    assert entry["field"] == "cover_image_url"
    assert entry["new_value"] == url


@pytest.mark.story("7.4", ac=1)
def test_a_correction_that_removes_the_cover_picture_is_recorded(coordinator_client, upload_dir):
    url = _upload_correction_picture(coordinator_client, Events.SUBMITTED)
    event = coordinator_client.get(f"/events/{Events.SUBMITTED}").json()
    removed = coordinator_client.delete(
        PICTURE_ROUTE.format(event_id=Events.SUBMITTED),
        params={"expected_updated_at": event["updated_at"]},
    )
    assert removed.status_code == 200, removed.text

    latest = _history(coordinator_client, Events.SUBMITTED)[0]
    assert latest["field"] == "cover_image_url"
    assert (latest["old_value"], latest["new_value"]) == (url, None)


@pytest.mark.story("7.4", ac=1)
def test_the_organisers_draft_picture_is_not_recorded(organiser_client, upload_dir):
    """Draft edits before submission are out of the history (CL-174)."""
    created = create_event_request(organiser_client)
    uploaded = organiser_client.put(
        f"/events/{created['id']}/cover-image", files={"file": ("cover.png", _PNG, "image/png")}
    )
    assert uploaded.status_code == 200, uploaded.text

    assert _history(organiser_client, created["id"]) == []


# --- AC5: who sees it; nothing edits or deletes it ------------------------------------------
@pytest.mark.story("7.4", ac=5)
def test_the_assigned_coordinator_sees_internal_notes_changes(coordinator_client):
    _notes(coordinator_client, Events.SUBMITTED, "Caterer booked.")

    [entry] = _history(coordinator_client, Events.SUBMITTED)
    assert entry["field"] == "internal_notes"
    assert entry["old_value"] is None
    assert entry["new_value"] == "Caterer booked."


@pytest.mark.story("7.4", ac=5)
def test_no_route_edits_or_deletes_a_history_entry():
    """No PUT/PATCH/DELETE exists on any path under the history, read from the route table as
    4.6's clarifications test does, so ``.../changes/{change_id}`` is covered too."""
    offenders = [
        (context.route.path, sorted(context.route.methods & EDIT_OR_DELETE_METHODS))
        for context in iter_route_contexts(app.routes)
        if isinstance(context.route, APIRoute)
        and context.route.path.startswith(ROUTE)
        and context.route.methods & EDIT_OR_DELETE_METHODS
    ]
    assert not offenders, offenders


@pytest.mark.story("7.4", ac=5)
def test_another_organiser_cannot_find_the_history(login_as):
    response = login_as(Users.ORGANISER_2).get(ROUTE.format(event_id=Events.SUBMITTED))

    assert response.status_code == 404


@pytest.mark.story("7.4", ac=5)
def test_a_coordinator_not_assigned_to_the_event_is_refused(login_as):
    response = login_as(Users.COORDINATOR_2).get(ROUTE.format(event_id=Events.SUBMITTED))

    assert response.status_code == 403


@pytest.mark.story("7.4", ac=5)
def test_signed_out_is_refused(client):
    response = client.get(ROUTE.format(event_id=Events.SUBMITTED))

    assert response.status_code == 401


# --- AC6: the organiser never receives internal-notes changes --------------------------------
@pytest.mark.story("7.4", ac=6)
def test_the_organiser_does_not_receive_internal_notes_changes(login_as):
    coordinator = login_as(Users.COORDINATOR)
    _notes(coordinator, Events.SUBMITTED, "Organiser is hard to reach.")
    _correct(coordinator, Events.SUBMITTED, expected_attendance=80)

    entries = _history(login_as(Users.ORGANISER), Events.SUBMITTED)
    assert [e["field"] for e in entries] == ["expected_attendance"]


# --- AC7: quick saves keep their order, none lost ------------------------------------------
@pytest.mark.story("7.4", ac=7)
def test_quick_saves_are_all_recorded_in_order(coordinator_client):
    for notes in ("First.", "Second.", "Third."):
        _notes(coordinator_client, Events.SUBMITTED, notes)

    entries = list(reversed(_history(coordinator_client, Events.SUBMITTED)))
    assert [(e["old_value"], e["new_value"]) for e in entries] == [
        (None, "First."),
        ("First.", "Second."),
        ("Second.", "Third."),
    ]


@contextmanager
def _committed_event(engine) -> Iterator[uuid.UUID]:
    """An event under review assigned to Chloe, committed so other connections see it, then
    removed with everything the race wrote."""
    with Session(engine) as session:
        event_id = make_event(session, assigned_coordinator_id=Users.COORDINATOR.id).id
        session.commit()
    try:
        yield event_id
    finally:
        with Session(engine) as session:
            session.execute(delete(EventChange).where(EventChange.event_id == event_id))
            session.execute(delete(AuditLog).where(AuditLog.entity_id == event_id))
            session.execute(delete(Event).where(Event.id == event_id))
            session.commit()


def _race(engine, attempts: list[Callable[[Session], None]]) -> None:
    """Run each attempt in its own thread and session, released together at a barrier, as
    tests/equipment/test_decide_equipment_requests.py does."""
    start = threading.Barrier(len(attempts))

    def run(attempt: Callable[[Session], None]) -> None:
        with Session(engine) as session:
            start.wait()
            attempt(session)

    with ThreadPoolExecutor(max_workers=len(attempts)) as pool:
        for future in [pool.submit(run, attempt) for attempt in attempts]:
            future.result(timeout=30)


def _notes_saver(event_id: uuid.UUID, notes: str) -> Callable[[Session], None]:
    def attempt(session: Session) -> None:
        service.update_routine_information(
            session,
            session.get(Event, event_id),
            schemas.EventRoutineUpdate(internal_notes=notes),
            actor=session.get(User, Users.COORDINATOR.id),
        )

    return attempt


@pytest.mark.story("7.4", ac=7)
def test_two_notes_saves_at_once_are_recorded_in_order(engine):
    """AC7 with the saves truly at once, each in its own session: the one that takes the event's
    row lock second records the first one's notes as its old value, so neither is lost."""
    with _committed_event(engine) as event_id:
        _race(engine, [_notes_saver(event_id, "A"), _notes_saver(event_id, "B")])

        with Session(engine) as session:
            rows = session.scalars(
                select(EventChange)
                .where(EventChange.event_id == event_id)
                .order_by(EventChange.seq)
            ).all()
            notes = session.get(Event, event_id).internal_notes
        assert [(row.old_value, row.new_value) for row in rows] in (
            [(None, "A"), ("A", "B")],
            [(None, "B"), ("B", "A")],
        )
        assert rows[-1].new_value == notes
