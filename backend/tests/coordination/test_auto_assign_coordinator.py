"""Story 5.1 (extended) - be: what submission does about a coordinator.

5.1 extended to assign a coordinator automatically, in round-robin order, on submission. Story 5.4
replaced that (5.4 AC9, replacing 5.1 AC1, AC2 and AC13; PO decision, Checkpoint 1): a submitted
request now waits unassigned in the Event Coordinator Lead's queue, and only the Lead assigns it.
The round-robin tests went with the round-robin code; the queue, the Lead's assignment and the
refusals are tested in test_unassigned_queue.py.

What remains true, and is tested here:
AC7  Saving or editing a draft never assigns a coordinator.
AC12 An organiser cannot choose the coordinator through the submit request.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.support.factories import create_event_request, create_submittable_event_request
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


# --- AC12: an organiser cannot choose the coordinator through submit -------------------------
@pytest.mark.story("5.1", ac=12)
def test_submit_ignores_a_coordinator_chosen_by_the_organiser(organiser_client):
    draft = create_submittable_event_request(organiser_client)

    response = organiser_client.post(
        f"/events/{draft['id']}/submit", json={"coordinator_id": str(Users.COORDINATOR.id)}
    )

    assert response.status_code == 200, response.text
    # Story 5.4 AC9: nobody is assigned on submission, and naming Chloe in the body changes that.
    assert response.json()["assigned_coordinator_id"] is None
