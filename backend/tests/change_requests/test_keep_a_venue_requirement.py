"""Story 2.7 AC18, AC20 (fix f2.7.4) - a change request cannot remove an event's last venue
requirement.

AC18 (Edge) A change request (19.1) cannot remove the last requirement: the form keeps one, the
     server refuses a change that would leave none.
AC20 (Permission) The server enforces AC14-AC19 on every save, submission, correction (7.2 AC4)
     and change request (19.1), including direct API requests.

A change to the venue requirements proposes the event's whole list (19.1), so removing the last
requirement is proposing an empty list. That is refused before 19.1 AC4 compares the proposal with
the current value, so an event approved before this fix with no requirement is told why, rather
than that nothing would change, and can still propose one.

Excluded, with reason:
* The form half of AC18 - the change form keeps the last row, and gives an event without a
  requirement one blank row to fill in - is UI behaviour, proven in
  tests/e2e/venue-requirements.spec.ts.
* Permission (who may act) does not change: only the owning organiser raises a change (19.1 AC7),
  proven in tests/change_requests/test_raise_change_request.py.
* Conflict does not apply: raising a change leaves the event as it is (19.1 AC3), and a field
  takes one pending change at a time (19.1 AC6).
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.events.models import Event, EventStatus
from tests.support.factories import future_datetime, make_event, make_venue_requirement
from tests.support.seed import Users

_REASON = "The keynote speaker can only attend a day later."
# AC18's refusal, written out so a red run shows what the server answers instead.
_NO_VENUE_REQUIREMENT_LEFT = "A change cannot leave this event without a venue requirement."

# Each with a name of its own and room for no more than the event's 100 people (2.7 AC6, AC9), so
# only how many requirements are left is ever in question.
_PLENARY = {"name": "Plenary hall", "capacity": 100}
_BREAKOUT = {"name": "Breakout room", "capacity": 40}
_EXHIBITION = {"name": "Exhibition hall", "capacity": 60}


# --- helpers, as in test_raise_change_request.py ----------------------------------------------
def _planning_event(db: Session, **overrides) -> Event:
    """Olivia's event in Planning, assigned to Chloe, dated safely in the future, for 100
    people."""
    starts_at = future_datetime(days=60)
    return make_event(
        db,
        status=EventStatus.PLANNING,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=8),
        expected_attendance=100,
        assigned_coordinator_id=Users.COORDINATOR.id,
        **overrides,
    )


def _raise(client, event_id: uuid.UUID, field: str, proposed):
    return client.post(
        f"/events/{event_id}/change-requests",
        json={"field": field, "proposed": proposed, "reason": _REASON},
    )


def _change_requests(db: Session, event_id: uuid.UUID) -> list:
    return list(
        db.execute(
            text(
                "SELECT id, field_name, current_value, proposed_value, reason, status,"
                " requested_by_id FROM event_change_requests WHERE event_id = :e"
                " ORDER BY created_at"
            ),
            {"e": event_id},
        )
    )


def _notifications(db: Session, event_id: uuid.UUID, notification_type: str) -> list:
    return list(
        db.execute(
            text(
                "SELECT recipient_id, related_entity_type, related_entity_id FROM notifications"
                " WHERE event_id = :e AND notification_type = :t"
            ),
            {"e": event_id, "t": notification_type},
        )
    )


def _proposed_requirements(row) -> list[tuple[str, int]]:
    """The requirements a saved change request proposes, each as its name and number of people."""
    return [(item["name"], item["capacity"]) for item in json.loads(row.proposed_value)]


# --- AC18 / AC20: a change cannot leave the event without a venue requirement ------------------
@pytest.mark.story("2.7", ac=18)
@pytest.mark.story("2.7", ac=20)
@pytest.mark.parametrize(
    ("requirements", "kept"),
    [
        # Its only requirement, edited: the same name, for fewer people.
        pytest.param([_PLENARY], {**_PLENARY, "capacity": 80}, id="one-requirement"),
        # Cut down to the first of three, as it stands.
        pytest.param([_PLENARY, _BREAKOUT, _EXHIBITION], _PLENARY, id="three-requirements"),
    ],
)
def test_a_change_that_would_leave_no_venue_requirement_is_refused(
    organiser_client, db: Session, requirements, kept
):
    """AC18: whether the event has one venue requirement or several, a change proposing none is
    refused, and no change request is saved or sent to the coordinator. The change the organiser
    can still ask for is taken: the only requirement edited, or the list cut down to one. AC20:
    the server refuses it itself, to a direct API request."""
    event = _planning_event(db)
    requirement_ids = [
        make_venue_requirement(
            db,
            event.id,
            position=position,
            name=requirement["name"],
            capacity=requirement["capacity"],
        )
        for position, requirement in enumerate(requirements)
    ]

    refused = _raise(organiser_client, event.id, "venue_requirements", [])

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == _NO_VENUE_REQUIREMENT_LEFT
    assert _change_requests(db, event.id) == []
    assert _notifications(db, event.id, "EVENT_CHANGE_REQUESTED") == []

    taken = _raise(
        organiser_client,
        event.id,
        "venue_requirements",
        [{"id": str(requirement_ids[0]), **kept}],
    )

    assert taken.status_code == 201, taken.text
    [row] = _change_requests(db, event.id)
    assert _proposed_requirements(row) == [(kept["name"], kept["capacity"])]


@pytest.mark.story("2.7", ac=18)
@pytest.mark.story("2.7", ac=20)
def test_an_event_approved_without_a_venue_requirement_can_propose_one_but_not_none(
    organiser_client, db: Session
):
    """AC18, on an event approved before this fix with "No venue requirements": proposing none is
    refused with AC18's own sentence - not as a value the same as the current one (19.1 AC4),
    which would not say why - and proposing one complete requirement, named and with a number of
    people, is taken. AC20: the server refuses it itself, to a direct API request."""
    event = _planning_event(db, venue_none_required=True)

    refused = _raise(organiser_client, event.id, "venue_requirements", [])

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == _NO_VENUE_REQUIREMENT_LEFT
    assert _change_requests(db, event.id) == []
    assert _notifications(db, event.id, "EVENT_CHANGE_REQUESTED") == []

    taken = _raise(organiser_client, event.id, "venue_requirements", [_PLENARY])

    assert taken.status_code == 201, taken.text
    [row] = _change_requests(db, event.id)
    assert json.loads(row.current_value) == []
    assert _proposed_requirements(row) == [("Plenary hall", 100)]
