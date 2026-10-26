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
* AC7 with truly concurrent requests: every test runs in one rolled-back transaction, so two
  saves cannot race here. Each save takes the event's row lock before reading the old value, and
  the order is the insert sequence, so quick saves one after another are what is checked.
* Draft edits before submission are not part of the history (agreed with the PO for 7.4).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from sqlalchemy.orm import Session, object_session

from app.change_requests.models import EventChangeRequest
from app.events.models import EventStatus
from app.main import app
from tests.support.change_requests import approve_as_seen
from tests.support.factories import future_datetime, make_event
from tests.support.seed import Events, Users

ROUTE = "/events/{event_id}/changes"
EDIT_OR_DELETE_METHODS = {"PUT", "PATCH", "DELETE"}
_ANY_FINGERPRINT = "not-assessed"


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
    path = "/events/{event_id}/changes"
    methods = {
        method
        for context in iter_route_contexts(app.routes)
        if isinstance(context.route, APIRoute) and context.route.path == path
        for method in context.route.methods
    }
    assert methods == {"GET"}


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
