"""Story 2.7 AC14-AC17, AC20 (fix f2.7.4) - every event request has at least one venue requirement.

AC14 Every request has at least one venue requirement. A new request starts with one, the last
     cannot be removed, and the form no longer offers "No venue requirements".
AC15 To submit, the request needs at least one requirement with a name and a number of people. The
     server refuses a submission without one and says what is missing.
AC16 (Boundary) A request with exactly one requirement can be submitted; it can be edited, not
     removed.
AC17 (Edge) A draft saved with "No venue requirements" before the fix opens with one empty
     requirement. A submitted event with none cannot be approved (4.4) until the coordinator adds
     one.
AC20 (Permission) The server enforces AC14-AC19 on every save, submission, correction (7.2 AC4)
     and change request (19.1), including direct API requests.

AC18, a change request that would leave an event with no venue requirement, is
tests/change_requests/test_keep_a_venue_requirement.py. What the forms do - a new request starting
with one requirement, the last one's Remove disabled, a draft from before the fix opening with one
to fill in, the coordinator's form saying one is needed, 19.1's change form keeping one - is
tests/e2e/venue-requirements.spec.ts, and AC15's list of what is still needed is
tests/e2e/event-request.spec.ts. AC16's "can be edited" and "can be submitted with one" are 2.7's
test_an_edited_requirement_keeps_its_id and
test_a_request_with_a_complete_requirement_can_be_submitted, in
test_multiple_venue_requirements.py. A request from before the fix, with no venue requirement, is
built with make_event, because the API can no longer make one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.events.models import EventStatus
from tests.support.factories import create_event_request, future_datetime, make_event
from tests.support.seed import Events, Users

# The server's sentences, compared word for word, so a run before the fix shows what it says
# instead.
_NEEDS_A_REQUIREMENT = "A request needs at least one venue requirement."
_NONE_REQUIRED_REFUSED = (
    "Venue requirements cannot be marked none required: every request needs at least one venue "
    "requirement."
)
_SUBMISSION_NEEDS_A_REQUIREMENT = (
    "Add the following before submitting: venue requirements (at least one)."
)
_APPROVAL_NEEDS_A_REQUIREMENT = "This request has no venue requirement, so it cannot be approved."
_NOT_AWAITING_A_DECISION = "This request is {status}, so it cannot be approved."
# A refused "No venue requirements" is located at the flag itself, so a client still sending it
# is told which field to drop.
_FLAG_LOCATION = ["body", "venue_none_required"]

_ATTENDANCE = 40
_REQUIREMENT_NAME = "Main hall"
_DESCRIPTION = "A day of planning for the year ahead."
_NEW_DESCRIPTION = "A clearer agenda."
_REJECTION_REASON = "The organiser has not said what venue the event needs."


# --- helpers -----------------------------------------------------------------------------------
def _requirement() -> dict:
    """One complete venue requirement - a name and a number of people - as the form sends it."""
    return {"name": _REQUIREMENT_NAME, "capacity": _ATTENDANCE}


def _request_body(**fields) -> dict:
    """A POST /events body for a dated draft, with ``fields`` added. Written out here rather than
    taken from the factory, so whether it sends venue requirements at all is each test's choice."""
    starts_at = future_datetime(days=40)
    return {
        "name": f"Request {uuid.uuid4().hex[:8]}",
        "starts_at": starts_at.isoformat(),
        "ends_at": (starts_at + timedelta(hours=8)).isoformat(),
        "expected_attendance": _ATTENDANCE,
        **fields,
    }


def _draft_with_a_requirement(client) -> dict:
    """The organiser's own draft with one complete venue requirement, as its body was returned."""
    return create_event_request(
        client, expected_attendance=_ATTENDANCE, venue_requirements=[_requirement()]
    )


def _request_from_before_the_fix(
    db: Session, *, status: str = EventStatus.UNDER_REVIEW, venue_none_required: bool = True
) -> uuid.UUID:
    """Olivia's request as saved before the fix, with no venue requirement - which the API can no
    longer make - and, unless told otherwise, "No venue requirements" marked. Everything else is
    filled in: the description, the point of contact and an accessibility answer. A draft is not
    yet submitted; in any other status it is submitted and assigned to Chloe.

    Last saved two days ago, so a write that a refusal leaves behind shows in ``updated_at``, and
    committed, so a refusal's rollback cannot take the request away with it. Returns its id."""
    starts_at = future_datetime(days=40)
    saved_at = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
    is_draft = status == EventStatus.DRAFT
    event = make_event(
        db,
        status=status,
        purpose="Quarterly planning",
        description=_DESCRIPTION,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=8),
        expected_attendance=_ATTENDANCE,
        contact_name="Priya Nair",
        contact_email="priya.nair@example.com",
        contact_phone="+65 9123 4567",
        accessibility_none_required=True,
        venue_none_required=venue_none_required,
        submitted_at=None if is_draft else saved_at,
        assigned_coordinator_id=None if is_draft else Users.COORDINATOR.id,
        created_at=saved_at,
        updated_at=saved_at,
    )
    event_id = event.id
    db.commit()
    return event_id


def _read(client, event_id) -> dict:
    response = client.get(f"/events/{event_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _edit(client, event_id, **changes):
    """The organiser's own edit of a draft (2.7 AC3)."""
    return client.patch(f"/events/{event_id}", json=changes)


def _correct(client, event: dict, **changes):
    """The coordinator's correction (7.2 AC4) of ``event`` (a GET body), sending the token it was
    read with."""
    return client.patch(
        f"/events/{event['id']}/review-details",
        json={"expected_updated_at": event["updated_at"], **changes},
    )


def _validation_issues(response) -> list[dict]:
    """The issues of a body FastAPI refused, each with its ``loc`` and ``msg``. Fails, showing the
    detail, when the refusal is a sentence instead."""
    detail = response.json()["detail"]
    assert isinstance(detail, list), detail
    return detail


def _requests_named(db: Session, name: str) -> int:
    return db.execute(
        text("SELECT count(*) FROM events WHERE name = :name"), {"name": name}
    ).scalar_one()


def _notified(db: Session, notification_type: str, event_id: uuid.UUID) -> list[uuid.UUID]:
    """Who received ``notification_type`` about the event, one entry per notification."""
    return list(
        db.execute(
            text(
                "SELECT recipient_id FROM notifications"
                " WHERE notification_type = :type AND event_id = :id"
            ),
            {"type": notification_type, "id": event_id},
        ).scalars()
    )


def _audit_details(db: Session, action: str, event_id: uuid.UUID) -> list[dict]:
    """The details of each ``action`` entry the audit log holds for the event, oldest first."""
    return list(
        db.execute(
            text(
                "SELECT details FROM audit_log WHERE action = :action AND entity_id = :id"
                " ORDER BY occurred_at"
            ),
            {"action": action, "id": event_id},
        ).scalars()
    )


# --- AC14/AC16/AC20: no save leaves a request without a venue requirement ----------------------
@pytest.mark.story("2.7", ac=14)
@pytest.mark.story("2.7", ac=16)
@pytest.mark.story("2.7", ac=20)
@pytest.mark.parametrize(
    "requirements",
    [
        pytest.param({}, id="list-left-out"),
        pytest.param({"venue_requirements": []}, id="empty-list"),
    ],
)
def test_a_request_is_never_saved_without_a_venue_requirement(
    organiser_client, db: Session, requirements
):
    """AC14/AC16/AC20: no request is created without a venue requirement, however it is sent - a
    direct API request may leave the list out or send it empty - and nothing is saved."""
    body = _request_body(**requirements)

    response = organiser_client.post("/events", json=body)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _NEEDS_A_REQUIREMENT
    assert _requests_named(db, body["name"]) == 0


@pytest.mark.story("2.7", ac=14)
@pytest.mark.story("2.7", ac=16)
@pytest.mark.story("2.7", ac=20)
def test_the_only_venue_requirement_cannot_be_removed(organiser_client):
    """AC14/AC16/AC20: a request's only venue requirement can be edited, not removed - an edit
    that sends none is refused, and the requirement stays as it was."""
    draft = _draft_with_a_requirement(organiser_client)

    response = _edit(organiser_client, draft["id"], venue_requirements=[])

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _NEEDS_A_REQUIREMENT
    after = _read(organiser_client, draft["id"])
    assert after["venue_requirements"] == draft["venue_requirements"]


@pytest.mark.story("2.7", ac=14)
@pytest.mark.story("2.7", ac=16)
@pytest.mark.story("2.7", ac=20)
@pytest.mark.parametrize(
    "venue_none_required",
    [pytest.param(True, id="marked-none-required"), pytest.param(False, id="left-unanswered")],
)
def test_a_draft_from_before_the_fix_is_not_saved_again_until_it_has_a_requirement(
    organiser_client, db: Session, venue_none_required
):
    """AC14/AC16/AC20: a draft saved with no venue requirement before the fix - marked "No venue
    requirements" or left unanswered - takes no save that leaves it without one, so an edit to
    anything else is refused until one is added too. Its form starts it with one (AC17)."""
    event_id = _request_from_before_the_fix(
        db, status=EventStatus.DRAFT, venue_none_required=venue_none_required
    )

    response = _edit(organiser_client, event_id, description=_NEW_DESCRIPTION)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _NEEDS_A_REQUIREMENT
    assert _read(organiser_client, event_id)["description"] == _DESCRIPTION


# --- AC14/AC20: "No venue requirements" is no longer an answer ---------------------------------
@pytest.mark.story("2.7", ac=14)
@pytest.mark.story("2.7", ac=20)
@pytest.mark.parametrize(
    "requirements",
    [
        pytest.param([], id="with-no-requirement"),
        pytest.param([_requirement()], id="beside-a-requirement"),
    ],
)
def test_venue_requirements_can_no_longer_be_marked_none_required(
    organiser_client, db: Session, requirements
):
    """AC14/AC20: the server no longer takes "No venue requirements", on its own or beside a
    requirement. It is refused at the flag, so a client still sending it is told which field to
    drop, and nothing is saved."""
    body = _request_body(venue_none_required=True, venue_requirements=requirements)

    response = organiser_client.post("/events", json=body)

    assert response.status_code == 422, response.text
    issues = _validation_issues(response)
    assert [issue["loc"] for issue in issues] == [_FLAG_LOCATION]
    assert _NONE_REQUIRED_REFUSED in issues[0]["msg"]
    assert _requests_named(db, body["name"]) == 0


@pytest.mark.story("2.7", ac=14)
@pytest.mark.story("2.7", ac=20)
def test_an_edit_cannot_mark_venue_requirements_none_required(organiser_client):
    """AC14/AC20: an edit cannot mark them none required either - the request "No venue
    requirements" made before the fix, clearing the list with it. The draft keeps its
    requirement, and the flag stays unset."""
    draft = _draft_with_a_requirement(organiser_client)

    response = _edit(organiser_client, draft["id"], venue_none_required=True, venue_requirements=[])

    assert response.status_code == 422, response.text
    issues = _validation_issues(response)
    assert [issue["loc"] for issue in issues] == [_FLAG_LOCATION]
    assert _NONE_REQUIRED_REFUSED in issues[0]["msg"]
    after = _read(organiser_client, draft["id"])
    assert after["venue_requirements"] == draft["venue_requirements"]
    assert after["venue_none_required"] is False


# --- AC15/AC20: a request is submitted only with a venue requirement ---------------------------
@pytest.mark.story("2.7", ac=15)
@pytest.mark.story("2.7", ac=20)
@pytest.mark.parametrize(
    "venue_none_required",
    [pytest.param(True, id="marked-none-required"), pytest.param(False, id="left-unanswered")],
)
def test_a_draft_without_a_venue_requirement_cannot_be_submitted(
    organiser_client, db: Session, venue_none_required
):
    """AC15/AC20: a draft with no venue requirement - one saved before the fix - is not
    submitted, and "No venue requirements" no longer counts as an answer. Everything else on it
    is filled in, so the refusal names the venue requirement alone; the draft stays a draft."""
    event_id = _request_from_before_the_fix(
        db, status=EventStatus.DRAFT, venue_none_required=venue_none_required
    )

    response = organiser_client.post(f"/events/{event_id}/submit")

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _SUBMISSION_NEEDS_A_REQUIREMENT
    assert _read(organiser_client, event_id)["status"] == EventStatus.DRAFT


# --- AC17: a draft from before the fix saves once it has a venue requirement -------------------
@pytest.mark.story("2.7", ac=17)
def test_a_draft_marked_none_required_before_the_fix_saves_once_it_has_a_requirement(
    organiser_client, db: Session
):
    """AC17: a draft saved with "No venue requirements" before the fix opens with one empty
    requirement. Filled in and saved - the form no longer sends the flag - it is taken, and the
    old answer is cleared."""
    event_id = _request_from_before_the_fix(db, status=EventStatus.DRAFT)

    response = _edit(organiser_client, event_id, venue_requirements=[_requirement()])

    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["venue_none_required"] is False
    assert [(r["name"], r["capacity"]) for r in saved["venue_requirements"]] == [
        (_REQUIREMENT_NAME, _ATTENDANCE)
    ]


# --- AC14/AC17/AC20: a correction never leaves a request without a venue requirement -----------
@pytest.mark.story("2.7", ac=14)
@pytest.mark.story("2.7", ac=17)
@pytest.mark.story("2.7", ac=20)
def test_a_correction_cannot_leave_a_request_without_a_venue_requirement(
    coordinator_client, db: Session
):
    """AC14/AC17/AC20: the coordinator's correction (7.2 AC4) of a request submitted before the
    fix with no venue requirement is refused while it leaves the request without one, so
    correcting the description alone is refused until one is added too. Nothing is written."""
    event = _read(coordinator_client, _request_from_before_the_fix(db))

    response = _correct(coordinator_client, event, description=_NEW_DESCRIPTION)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _NEEDS_A_REQUIREMENT
    after = _read(coordinator_client, event["id"])
    assert after["description"] == event["description"]
    assert after["updated_at"] == event["updated_at"]


@pytest.mark.story("2.7", ac=14)
@pytest.mark.story("2.7", ac=17)
@pytest.mark.story("2.7", ac=20)
def test_a_correction_cannot_mark_venue_requirements_none_required(coordinator_client):
    """AC14/AC17/AC20: a correction cannot mark "No venue requirements" and clear the list
    either, which before the fix removed a submitted request's last requirement. Data Literacy
    Workshop, under review with Chloe, keeps its Main venue, and nothing is written."""
    event = _read(coordinator_client, Events.SUBMITTED)

    response = _correct(coordinator_client, event, venue_none_required=True, venue_requirements=[])

    assert response.status_code == 422, response.text
    issues = _validation_issues(response)
    assert [issue["loc"] for issue in issues] == [_FLAG_LOCATION]
    assert _NONE_REQUIRED_REFUSED in issues[0]["msg"]
    after = _read(coordinator_client, Events.SUBMITTED)
    assert after["venue_requirements"] == event["venue_requirements"]
    assert after["updated_at"] == event["updated_at"]


# --- AC17: approved only once it has a venue requirement ---------------------------------------
@pytest.mark.story("2.7", ac=17)
@pytest.mark.parametrize("status", [EventStatus.UNDER_REVIEW, EventStatus.CLARIFICATION_REQUESTED])
def test_a_request_without_a_venue_requirement_cannot_be_approved_but_can_be_rejected(
    coordinator_client, db: Session, status
):
    """AC17: a request submitted before the fix with no venue requirement is not approved (4.4)
    until its coordinator adds one: it stays as it was, and nobody is told it was approved.
    Rejecting it (4.5) still works."""
    event_id = _request_from_before_the_fix(db, status=status)

    refused = coordinator_client.post(f"/events/{event_id}/approve")

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == _APPROVAL_NEEDS_A_REQUIREMENT
    assert _read(coordinator_client, event_id)["status"] == status
    assert _notified(db, "EVENT_APPROVED", event_id) == []
    assert _audit_details(db, "EVENT_APPROVED", event_id) == []
    rejected = coordinator_client.post(
        f"/events/{event_id}/reject", json={"reason": _REJECTION_REASON}
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == EventStatus.REJECTED


@pytest.mark.story("2.7", ac=17)
def test_once_the_coordinator_adds_a_venue_requirement_the_request_can_be_approved(
    coordinator_client, db: Session
):
    """AC17: once its coordinator adds a venue requirement (7.2 AC4), a request submitted before
    the fix without one can be approved. The correction clears its "No venue requirements", and
    the change history (7.4) records that beside the new requirement."""
    event_id = _request_from_before_the_fix(db)

    corrected = _correct(
        coordinator_client, _read(coordinator_client, event_id), venue_requirements=[_requirement()]
    )

    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["venue_none_required"] is False
    assert [r["name"] for r in corrected.json()["venue_requirements"]] == [_REQUIREMENT_NAME]
    (changes,) = _audit_details(db, "EVENT_DETAILS_CORRECTED", event_id)
    assert changes["venue_none_required"] == {"from": True, "to": False}
    approved = coordinator_client.post(f"/events/{event_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == EventStatus.PLANNING


@pytest.mark.story("2.7", ac=17)
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
def test_a_request_not_awaiting_a_decision_is_told_so_even_without_a_venue_requirement(
    coordinator_client, db: Session, status
):
    """AC17, a pin on the order of the refusals, so it passes before the fix as well: the venue
    requirement is checked after the status (4.4 AC1), so a request no longer awaiting a decision
    is told that, not that it has no venue requirement."""
    event_id = _request_from_before_the_fix(db, status=status)

    response = coordinator_client.post(f"/events/{event_id}/approve")

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == _NOT_AWAITING_A_DECISION.format(status=status)
