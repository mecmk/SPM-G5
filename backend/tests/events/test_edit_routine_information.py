"""Story 7.2 - be: the assigned Event Coordinator edits an event's routine information directly.

AC1 The only routine field, internal notes, can be edited and saved directly, only by the
    coordinator assigned to the event. Description and contact details are not editable here.
AC2 The change takes effect immediately: persisted, and returned by a subsequent read.
AC3 Editing is blocked once the event is completed, cancelled or rejected.

Excluded, with reason:
* Change history / audit UI - out of scope for 7.2 (story 7.4). ``record_audit`` is called the
  same way every other write in this service calls it; there is no viewer for it yet.
* Notifications - no notification application code exists anywhere in the backend (epic 20).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.events.models import EventStatus
from tests.support.factories import make_event
from tests.support.seed import Events, Users

ROUTE = "/events/{event_id}/routine-information"


def _patch(client, event_id, **body):
    return client.patch(ROUTE.format(event_id=event_id), json=body)


# --- AC1: only the assigned coordinator may edit, only routine fields ------------------------
@pytest.mark.story("7.2", ac=1)
def test_assigned_coordinator_can_update_internal_notes(coordinator_client, db: Session):
    response = _patch(
        coordinator_client, Events.SUBMITTED, internal_notes="Caterer confirmed for 60 pax."
    )

    assert response.status_code == 200, response.text
    assert response.json()["internal_notes"] == "Caterer confirmed for 60 pax."

    db.expire_all()
    stored = db.execute(
        text("SELECT internal_notes FROM events WHERE id = :id"), {"id": Events.SUBMITTED}
    ).scalar_one()
    assert stored == "Caterer confirmed for 60 pax."


@pytest.mark.story("7.2", ac=1)
def test_internal_notes_can_be_cleared_with_null(coordinator_client):
    _patch(coordinator_client, Events.SUBMITTED, internal_notes="Temporary note.")

    response = _patch(coordinator_client, Events.SUBMITTED, internal_notes=None)

    assert response.status_code == 200, response.text
    assert response.json()["internal_notes"] is None


@pytest.mark.story("7.2", ac=1)
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("description", "Updated description."),
        ("contact_name", "New Contact"),
        ("contact_email", "new-contact@acme.example"),
        ("contact_phone", "+65 6123 4567"),
    ],
)
def test_description_and_contact_details_cannot_be_changed_through_this_operation(
    coordinator_client, field, value
):
    before = coordinator_client.get(f"/events/{Events.SUBMITTED}").json()

    response = _patch(coordinator_client, Events.SUBMITTED, **{field: value})

    assert response.status_code == 422
    after = coordinator_client.get(f"/events/{Events.SUBMITTED}").json()
    assert after[field] == before[field]


@pytest.mark.story("7.2", ac=1)
def test_important_fields_cannot_be_changed_through_this_operation(coordinator_client):
    response = _patch(coordinator_client, Events.SUBMITTED, starts_at="2027-01-01T09:00:00+08:00")

    assert response.status_code == 422


@pytest.mark.story("7.2", ac=1)
def test_status_cannot_be_changed_through_this_operation(coordinator_client):
    response = _patch(coordinator_client, Events.SUBMITTED, status=EventStatus.CANCELLED)

    assert response.status_code == 422


@pytest.mark.story("7.2", ac=1)
def test_a_coordinator_not_assigned_to_the_event_cannot_edit_it(login_as):
    response = _patch(login_as(Users.COORDINATOR_2), Events.SUBMITTED, internal_notes="Nope.")

    assert response.status_code == 403
    assert "edit" in response.json()["detail"]
    assert "decide" not in response.json()["detail"]


@pytest.mark.story("7.2", ac=1)
@pytest.mark.parametrize(
    "client_name", ["organiser_client", "venue_staff_client", "tech_client", "attendee_client"]
)
def test_an_unauthorised_role_cannot_edit_routine_information(client_name, request):
    client = request.getfixturevalue(client_name)

    response = _patch(client, Events.SUBMITTED, internal_notes="Nope.")

    assert response.status_code == 403


# --- AC2: the edit takes effect immediately ---------------------------------------------------
@pytest.mark.story("7.2", ac=2)
def test_a_subsequent_read_returns_the_updated_value(coordinator_client):
    _patch(coordinator_client, Events.SUBMITTED, internal_notes="Now with catering.")

    response = coordinator_client.get(f"/events/{Events.SUBMITTED}")

    assert response.status_code == 200
    assert response.json()["internal_notes"] == "Now with catering."


@pytest.mark.story("7.2", ac=2)
def test_internal_notes_are_never_returned_to_the_organiser(coordinator_client, login_as):
    _patch(coordinator_client, Events.SUBMITTED, internal_notes="Coordinator eyes only.")

    response = login_as(Users.ORGANISER).get(f"/events/{Events.SUBMITTED}")

    assert response.status_code == 200
    assert response.json()["internal_notes"] is None


@pytest.mark.story("7.2", ac=2)
def test_a_no_op_edit_does_not_write_audit_or_bump_updated_at(coordinator_client, db: Session):
    before = db.execute(
        text("SELECT updated_at FROM events WHERE id = :id"), {"id": Events.SUBMITTED}
    ).one()

    response = _patch(coordinator_client, Events.SUBMITTED)

    assert response.status_code == 200, response.text
    db.expire_all()
    after = db.execute(
        text("SELECT updated_at FROM events WHERE id = :id"), {"id": Events.SUBMITTED}
    ).one()
    assert after.updated_at == before.updated_at
    count = db.execute(
        text(
            "SELECT count(*) FROM audit_log "
            "WHERE action = 'EVENT_ROUTINE_INFO_UPDATED' AND entity_id = :id"
        ),
        {"id": Events.SUBMITTED},
    ).scalar_one()
    assert count == 0


@pytest.mark.story("7.2", ac=2)
def test_internal_notes_are_never_returned_to_venue_staff_or_tech_support(
    coordinator_client, venue_staff_client, tech_client
):
    _patch(coordinator_client, Events.SUBMITTED, internal_notes="Coordinator eyes only.")

    venue_response = venue_staff_client.get(f"/events/{Events.SUBMITTED}")
    tech_response = tech_client.get(f"/events/{Events.SUBMITTED}")

    assert venue_response.status_code == 200
    assert venue_response.json()["internal_notes"] is None
    assert tech_response.status_code == 200
    assert tech_response.json()["internal_notes"] is None


# --- AC3: blocked once the event is completed, cancelled or rejected --------------------------
@pytest.mark.story("7.2", ac=3)
@pytest.mark.parametrize(
    "status", [EventStatus.COMPLETED, EventStatus.CANCELLED, EventStatus.REJECTED]
)
def test_routine_editing_is_blocked_for_terminal_statuses(coordinator_client, db: Session, status):
    event = make_event(db, status=status, assigned_coordinator_id=Users.COORDINATOR.id)
    db.commit()

    response = _patch(coordinator_client, event.id, internal_notes="Too late.")

    assert response.status_code == 409


@pytest.mark.story("7.2", ac=3)
def test_the_rejected_seed_event_cannot_be_edited(login_as):
    response = _patch(login_as(Users.COORDINATOR_2), Events.REJECTED, internal_notes="Too late.")

    assert response.status_code == 409


@pytest.mark.story("7.2", ac=3)
def test_a_closed_event_refuses_with_409_even_for_an_unassigned_coordinator(login_as, db: Session):
    """AC3's status gate is checked before the assignment check, so an unrelated coordinator
    learns the event is closed (409), not that they personally may not edit it (403)."""
    event = make_event(
        db, status=EventStatus.REJECTED, assigned_coordinator_id=Users.COORDINATOR.id
    )
    db.commit()

    response = _patch(login_as(Users.COORDINATOR_2), event.id, internal_notes="Too late.")

    assert response.status_code == 409


# --- failure behaviour --------------------------------------------------------------------
@pytest.mark.story("7.2")
def test_editing_a_missing_event_is_not_found(coordinator_client):
    response = _patch(
        coordinator_client, "00000000-0000-0000-0000-000000000000", internal_notes="Anything."
    )

    assert response.status_code == 404


@pytest.mark.story("7.2")
def test_a_failed_edit_does_not_change_the_stored_value(login_as):
    before = login_as(Users.COORDINATOR).get(f"/events/{Events.SUBMITTED}").json()

    response = _patch(
        login_as(Users.COORDINATOR_2), Events.SUBMITTED, internal_notes="Rejected edit."
    )
    assert response.status_code == 403

    after = login_as(Users.COORDINATOR).get(f"/events/{Events.SUBMITTED}").json()
    assert after["internal_notes"] == before["internal_notes"]
