"""Story 2.1 - fe/be: submit an event request (AC9-AC12).

AC9  An organiser can submit their own request only while it is still a draft.
AC10 Submitting requires every event detail (name, purpose, description, proposed start,
     proposed end, expected attendance) to be filled in, and both the venue requirements and the
     accessibility needs to be answered - something chosen, or marked "none". If anything is
     missing, submission is refused with a message naming what's missing. Equipment stays
     optional.
AC11 On successful submission the status changes to "submitted" and the submission date/time is
     recorded.
AC12 An organiser cannot submit a request that belongs to someone else, or one that has already
     been submitted.

Recording the details (AC1-AC8) is in test_event_request_details.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.common.audit import AuditLog
from tests.support.factories import create_event_request, create_submittable_event_request
from tests.support.seed import Events, Users

# Each thing AC10 requires: how the message names it, and how to leave just that one out of an
# otherwise submittable request.
REQUIRED = {
    "purpose": ("purpose", {"purpose": None}),
    "description": ("description", {"description": None}),
    "starts_at": ("proposed start date and time", {"starts_at": None}),
    "ends_at": ("proposed end date and time", {"ends_at": None}),
    "expected_attendance": ("expected attendance", {"expected_attendance": None}),
    "venue": ("venue requirements", {"venue_none_required": False}),
    "accessibility": ("accessibility needs", {"accessibility_none_required": False}),
}
NON_ORGANISERS = [
    pytest.param(Users.COORDINATOR, id="coordinator"),
    pytest.param(Users.VENUE_STAFF, id="venue-staff"),
    pytest.param(Users.TECH_SUPPORT, id="tech-support"),
    pytest.param(Users.ATTENDEE, id="attendee"),
]


def _submit(client, event_id):
    return client.post(f"/events/{event_id}/submit")


def _state(db: Session, event_id) -> tuple[str, datetime | None]:
    row = db.execute(
        text("SELECT status, submitted_at FROM events WHERE id = :id"), {"id": str(event_id)}
    ).one()
    return row.status, row.submitted_at


# --- AC9: only the owner, only while a draft ---------------------------------------------------
@pytest.mark.story("2.1", ac=9)
def test_an_organiser_submits_their_own_draft(organiser_client):
    created = create_submittable_event_request(organiser_client)

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 200, response.text
    assert response.json()["id"] == created["id"]


@pytest.mark.story("2.1", ac=9)
@pytest.mark.parametrize("user", NON_ORGANISERS)
def test_only_an_organiser_can_submit(login_as, db: Session, user):
    created = create_submittable_event_request(login_as(Users.ORGANISER))

    response = _submit(login_as(user), created["id"])

    assert response.status_code == 403
    assert _state(db, created["id"]) == ("DRAFT", None)


@pytest.mark.story("2.1", ac=9)
def test_submitting_requires_sign_in(client, login_as):
    created = create_submittable_event_request(login_as(Users.ORGANISER))
    client.logout()

    assert _submit(client, created["id"]).status_code == 401


# --- AC10: everything must be filled in or answered ---------------------------------------------
@pytest.mark.story("2.1", ac=10)
@pytest.mark.parametrize("missing", list(REQUIRED))
def test_each_missing_requirement_is_named_and_refused(organiser_client, db: Session, missing):
    label, leave_out = REQUIRED[missing]
    created = create_submittable_event_request(organiser_client, **leave_out)

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 422
    detail = response.text.lower()
    assert label in detail
    for other, (other_label, _) in REQUIRED.items():
        if other != missing:
            assert other_label not in detail, f"{other_label} was given but is named as missing"
    assert _state(db, created["id"]) == ("DRAFT", None)


@pytest.mark.story("2.1", ac=10)
def test_every_missing_requirement_is_named_together(organiser_client):
    created = create_event_request(
        organiser_client,
        purpose=None,
        description=None,
        starts_at=None,
        ends_at=None,
        expected_attendance=None,
    )

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 422
    assert all(label in response.text.lower() for label, _ in REQUIRED.values())


@pytest.mark.story("2.1", ac=10)
def test_a_seeded_incomplete_draft_cannot_be_submitted(organiser_client):
    """The seeded draft has a description but nothing else that is required."""
    response = _submit(organiser_client, Events.DRAFT)

    assert response.status_code == 422
    detail = response.text.lower()
    assert all(label in detail for key, (label, _) in REQUIRED.items() if key != "description")
    assert REQUIRED["description"][0] not in detail


@pytest.mark.story("2.1", ac=10)
@pytest.mark.parametrize("field", ["purpose", "description"])
def test_a_detail_of_only_spaces_counts_as_missing(organiser_client, field):
    created = create_submittable_event_request(organiser_client, **{field: "   "})

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 422
    assert REQUIRED[field][0] in response.text.lower()


@pytest.mark.story("2.1", ac=10)
@pytest.mark.parametrize(
    "answer",
    [
        pytest.param({"venue_none_required": True}, id="marked-none"),
        pytest.param({"required_layout_code": "THEATRE"}, id="layout"),
        pytest.param({"required_facilities": [{"code": "WIFI"}]}, id="facility"),
        pytest.param({"venue_requirement_notes": "Near the lifts"}, id="notes"),
    ],
)
def test_venue_requirements_count_as_answered_by_choosing_something_or_marking_none(
    organiser_client, answer
):
    created = create_submittable_event_request(
        organiser_client, **{"venue_none_required": False, **answer}
    )

    assert _submit(organiser_client, created["id"]).status_code == 200


@pytest.mark.story("2.1", ac=10)
@pytest.mark.parametrize(
    "answer",
    [
        pytest.param({"accessibility_none_required": True}, id="marked-none"),
        pytest.param({"accessibility_needs": [{"code": "HEARING_LOOP"}]}, id="need"),
        pytest.param({"accessibility_notes": "Guide dog attending"}, id="notes"),
    ],
)
def test_accessibility_counts_as_answered_by_choosing_something_or_marking_none(
    organiser_client, answer
):
    created = create_submittable_event_request(
        organiser_client, **{"accessibility_none_required": False, **answer}
    )

    assert _submit(organiser_client, created["id"]).status_code == 200


@pytest.mark.story("2.1", ac=10)
def test_equipment_is_not_required_to_submit(organiser_client):
    created = create_submittable_event_request(organiser_client, equipment=[])

    assert _submit(organiser_client, created["id"]).status_code == 200


@pytest.mark.story("2.1", ac=10)
def test_a_draft_whose_start_has_since_passed_cannot_be_submitted(organiser_client, db: Session):
    created = create_submittable_event_request(organiser_client)
    db.execute(
        text(
            "UPDATE events SET starts_at = now() - interval '2 days',"
            " ends_at = now() - interval '1 day' WHERE id = :id"
        ),
        {"id": created["id"]},
    )
    db.expire_all()

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 422
    assert "in the past" in response.text.lower()
    assert _state(db, created["id"]) == ("DRAFT", None)


# --- AC11: status and submission time ------------------------------------------------------------
@pytest.mark.story("2.1", ac=11)
def test_submission_sets_the_status_and_records_when(organiser_client, db: Session):
    created = create_submittable_event_request(organiser_client)
    before = datetime.now(UTC)

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "SUBMITTED"
    submitted_at = datetime.fromisoformat(body["submitted_at"])
    assert submitted_at.tzinfo is not None
    assert before - timedelta(seconds=5) <= submitted_at <= datetime.now(UTC) + timedelta(seconds=5)
    assert _state(db, created["id"]) == ("SUBMITTED", submitted_at)
    assert organiser_client.get(f"/events/{created['id']}").json() == body


@pytest.mark.story("2.1", ac=11)
def test_submission_leaves_every_recorded_detail_unchanged(organiser_client):
    created = create_event_request(
        organiser_client,
        required_facilities=[{"code": "BREAKOUT_ROOMS", "quantity": 3}],
        accessibility_needs=[{"code": "LIFT_ACCESS"}],
        equipment=[{"equipment_type_code": "LAPTOP", "quantity": 2}],
    )

    submitted = _submit(organiser_client, created["id"]).json()

    assert submitted == {
        **created,
        "status": "SUBMITTED",
        "submitted_at": submitted["submitted_at"],
        "updated_at": submitted["updated_at"],
    }


@pytest.mark.story("2.1", ac=11)
def test_submission_is_written_to_the_status_history_and_audit_log(organiser_client, db: Session):
    created = create_submittable_event_request(organiser_client)

    _submit(organiser_client, created["id"])

    history = db.execute(
        text(
            "SELECT from_status, to_status, changed_by_id FROM event_status_history"
            " WHERE event_id = :id"
        ),
        {"id": created["id"]},
    ).all()
    assert {tuple(row) for row in history} == {
        (None, "DRAFT", Users.ORGANISER.id),
        ("DRAFT", "SUBMITTED", Users.ORGANISER.id),
    }
    actions = db.scalars(
        select(AuditLog.action).where(AuditLog.entity_id == uuid.UUID(created["id"]))
    ).all()
    assert sorted(actions) == ["EVENT_CREATED", "EVENT_SUBMITTED"]


# --- AC12: not someone else's, not twice ---------------------------------------------------------
@pytest.mark.story("2.1", ac=12)
def test_an_organiser_cannot_submit_another_organisers_request(login_as, db: Session):
    created = create_submittable_event_request(login_as(Users.ORGANISER))

    response = _submit(login_as(Users.ORGANISER_2), created["id"])

    assert response.status_code == 404
    assert _state(db, created["id"]) == ("DRAFT", None)


@pytest.mark.story("2.1", ac=12)
def test_a_submitted_request_cannot_be_submitted_again(organiser_client, db: Session):
    created = create_submittable_event_request(organiser_client)
    first = _submit(organiser_client, created["id"]).json()

    second = _submit(organiser_client, created["id"])

    assert second.status_code == 409
    assert "already been submitted" in second.text.lower()
    assert _state(db, created["id"])[1] == datetime.fromisoformat(first["submitted_at"])


@pytest.mark.story("2.1", ac=12)
@pytest.mark.parametrize(
    "owner, event_id",
    [
        pytest.param(Users.ORGANISER, Events.SUBMITTED, id="submitted"),
        pytest.param(Users.ORGANISER_2, Events.APPROVED, id="approved"),
        pytest.param(Users.ORGANISER_2, Events.REJECTED, id="rejected"),
    ],
)
def test_a_request_past_the_draft_stage_cannot_be_submitted(login_as, db: Session, owner, event_id):
    status_before, submitted_before = _state(db, event_id)

    response = _submit(login_as(owner), event_id)

    assert response.status_code == 409
    assert _state(db, event_id) == (status_before, submitted_before)


@pytest.mark.story("2.1", ac=12)
def test_submitting_a_request_that_does_not_exist(organiser_client):
    assert _submit(organiser_client, uuid.uuid4()).status_code == 404
    assert _submit(organiser_client, "not-a-uuid").status_code == 422


@pytest.mark.story("2.1", ac=12)
def test_a_dates_check_does_not_hide_the_ownership_check(login_as):
    """Someone else's incomplete draft is a 404, not a 422 that reveals what it lacks."""
    created = create_event_request(login_as(Users.ORGANISER), purpose=None)

    assert _submit(login_as(Users.ORGANISER_2), created["id"]).status_code == 404
