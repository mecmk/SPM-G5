"""Story 7.2 - be: the assigned Event Coordinator corrects an event's details while it is under
review.

AC4 While an event is Under Review, the assigned coordinator can edit the organiser-provided event
    details, including the cover picture, using the same checks as creating a request (2.1).
    Each saved change is recorded for the change history (7.4).
AC5 Once the event is approved, organiser-provided details become read-only; internal notes stay
    editable.
AC6 The lock begins at approval: a correction saved before approval applies, one that arrives
    after it is refused.
AC7 Editing the event dates during review re-validates all date-dependent fields and re-checks
    existing equipment holds for the new period. If the required equipment is no longer
    available, the edit is refused, leaving the event and its existing holds unchanged. Venue
    conflicts are checked later when a specific venue is requested.
AC8 Only the assigned coordinator can edit, enforced by the API.
AC9 A save made against a stale copy of the event is refused, so the user can reload.

Excluded, with reason:
* Venue re-check (AC7) - a venue request can only be raised once the event is approved (12.1
  AC1), so no venue request can exist while it is under review.
* Organiser-vs-coordinator concurrent edits (AC9) - organisers cannot edit a submitted request
  until story 4.3 exists. The stale check is exercised here with a token that no longer matches;
  the real two-transaction case is covered end to end in tests/e2e.
* Change history UI (AC4) - story 7.4. These tests check the audit row it will read.
* The cover picture is sent as a file, so it has its own endpoint beside the JSON correction,
  under the same rules (assigned coordinator, under review, the stale-copy token).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.events import service
from app.events.models import EventStatus
from tests.support.factories import (
    create_submittable_event_request,
    make_equipment_hold,
    make_event,
)
from tests.support.seed import Events, Users

ROUTE = "/events/{event_id}/review-details"
PICTURE_ROUTE = "/events/{event_id}/review-details/cover-image"
# Enough of a PNG for the 2.1 type check, which reads the signature only.
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
SEEDED_PICTURE = "/images/events/cat.jpg"
LAPTOP_STOCK = 6


def _read(client, event_id) -> dict:
    response = client.get(f"/events/{event_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _correct(client, event: dict, **changes):
    """PATCH the details of ``event`` (a GET body), sending the token it was read with."""
    body = {"expected_updated_at": event["updated_at"], **changes}
    return client.patch(ROUTE.format(event_id=event["id"]), json=body)


@pytest.fixture
def upload_dir(tmp_path: Path, monkeypatch) -> Path:
    """Uploaded pictures go to a temporary folder, never backend/uploads."""
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    return tmp_path


def _upload_picture(client, event: dict, content: bytes = _PNG, *, token: str | None = None):
    return client.put(
        PICTURE_ROUTE.format(event_id=event["id"]),
        params={"expected_updated_at": token or event["updated_at"]},
        files={"file": ("cover.png", content, "image/png")},
    )


def _remove_picture(client, event: dict):
    return client.delete(
        PICTURE_ROUTE.format(event_id=event["id"]),
        params={"expected_updated_at": event["updated_at"]},
    )


def _period(days: int = 40) -> tuple[datetime, datetime]:
    start = (datetime.now(UTC) + timedelta(days=days)).replace(microsecond=0)
    return start, start + timedelta(hours=8)


def _dates(period: tuple[datetime, datetime]) -> dict:
    return {"starts_at": period[0].isoformat(), "ends_at": period[1].isoformat()}


def _equipment(code: str, quantity: int) -> dict:
    return {"equipment_type_code": code, "quantity": quantity}


def _submitted_with_equipment(login_as, db: Session, period, *lines) -> dict:
    """An event the organiser submitted (so 2.1 AC11 holds its equipment), assigned to
    ``Users.COORDINATOR``, as the coordinator reads it."""
    created = create_submittable_event_request(
        login_as(Users.ORGANISER), **_dates(period), equipment=list(lines)
    )
    submitted = login_as(Users.ORGANISER).post(f"/events/{created['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    db.execute(
        text("UPDATE events SET assigned_coordinator_id = :c WHERE id = :id"),
        {"c": Users.COORDINATOR.id, "id": created["id"]},
    )
    # Committed, so a refused correction's rollback cannot undo the assignment as well.
    db.commit()
    return _read(login_as(Users.COORDINATOR), created["id"])


def _holds(db: Session, event_id) -> list:
    db.expire_all()
    return db.execute(
        text(
            "SELECT t.code, r.quantity, r.starts_at, r.ends_at, r.status"
            " FROM equipment_reservations r JOIN equipment_types t ON t.id = r.equipment_type_id"
            " WHERE r.event_id = :id ORDER BY r.reserved_at, t.code"
        ),
        {"id": event_id},
    ).all()


def _held(db: Session, event_id) -> set[tuple]:
    """(type, quantity, start, end) of every hold still RESERVED for the event."""
    return {
        (h.code, h.quantity, h.starts_at, h.ends_at)
        for h in _holds(db, event_id)
        if h.status == "RESERVED"
    }


# --- AC4: the assigned coordinator corrects details under review -----------------------------
@pytest.mark.story("7.2", ac=4)
def test_the_assigned_coordinator_corrects_details_under_review(coordinator_client):
    event = _read(coordinator_client, Events.SUBMITTED)

    response = _correct(
        coordinator_client,
        event,
        name="Data Literacy Workshop (corrected)",
        description="A one-day workshop.",
        expected_attendance=65,
        contact_phone="+65 6123 4567",
    )

    assert response.status_code == 200, response.text
    after = _read(coordinator_client, Events.SUBMITTED)
    assert after["name"] == "Data Literacy Workshop (corrected)"
    assert after["description"] == "A one-day workshop."
    assert after["expected_attendance"] == 65
    assert after["contact_phone"] == "+65 6123 4567"


@pytest.mark.story("7.2", ac=4)
def test_correcting_details_does_not_change_the_status(coordinator_client):
    event = _read(coordinator_client, Events.SUBMITTED)

    response = _correct(coordinator_client, event, purpose="Upskilling")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "UNDER_REVIEW"
    assert _read(coordinator_client, Events.SUBMITTED)["status"] == "UNDER_REVIEW"


@pytest.mark.story("7.2", ac=4)
def test_requirements_registration_and_visibility_can_be_corrected(coordinator_client):
    event = _read(coordinator_client, Events.SUBMITTED)
    starts_at = datetime.fromisoformat(event["starts_at"])

    response = _correct(
        coordinator_client,
        event,
        required_layout_code="THEATRE",
        required_facilities=[{"code": "PROJECTOR"}],
        accessibility_none_required=False,
        accessibility_needs=[{"code": "WHEELCHAIR_ACCESS"}],
        registration_required=True,
        registration_closes_at=(starts_at - timedelta(days=1)).isoformat(),
        is_public=True,
    )

    assert response.status_code == 200, response.text
    after = response.json()
    assert after["required_layout_code"] == "THEATRE"
    assert [f["code"] for f in after["required_facilities"]] == ["PROJECTOR"]
    assert [n["code"] for n in after["accessibility_needs"]] == ["WHEELCHAIR_ACCESS"]
    assert after["registration_required"] is True
    assert after["is_public"] is True


@pytest.mark.story("7.2", ac=4)
def test_equipment_lines_can_be_corrected(coordinator_client):
    event = _read(coordinator_client, Events.SUBMITTED)

    response = _correct(coordinator_client, event, equipment=[_equipment("WIRELESS_MIC", 4)])

    assert response.status_code == 200, response.text
    lines = response.json()["equipment"]
    assert [(line["equipment_type_code"], line["quantity"]) for line in lines] == [
        ("WIRELESS_MIC", 4)
    ]


@pytest.mark.story("7.2", ac=4)
@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (
            {"ends_at": "2026-11-18T08:00:00+08:00"},
            "end date and time must be after the start",
        ),
        (
            {"starts_at": "2020-01-01T09:00:00+08:00", "ends_at": "2020-01-01T17:00:00+08:00"},
            "cannot be in the past",
        ),
        ({"ends_at": "2026-12-18T17:00:00+08:00"}, "more than 14 days"),
        ({"contact_email": "not-an-email"}, "email address like"),
        ({"contact_phone": "12"}, "8 to 15 digits"),
        (
            {"venue_none_required": True, "required_layout_code": "THEATRE"},
            "venue requirements cannot be marked none required",
        ),
        (
            {"registration_required": True, "registration_closes_at": "2026-11-19T09:00:00+08:00"},
            "registration must close no later than the proposed start",
        ),
        ({"equipment": [_equipment("NOT_A_TYPE", 1)]}, "unknown equipment type"),
    ],
)
def test_the_2_1_rules_apply_to_a_correction(coordinator_client, changes, expected):
    event = _read(coordinator_client, Events.SUBMITTED)

    response = _correct(coordinator_client, event, **changes)

    assert response.status_code == 422
    assert expected in response.text.lower()
    assert _read(coordinator_client, Events.SUBMITTED)["updated_at"] == event["updated_at"]


@pytest.mark.story("7.2", ac=4)
def test_a_name_another_of_the_organisers_requests_has_is_refused_naming_the_organiser(
    login_as, db: Session
):
    """2.1 AC20 applies to a correction too, worded for the coordinator: it is the organiser, not
    the coordinator, who already has a request with that name and those dates."""
    period = _period()
    event = _submitted_with_equipment(login_as, db, period)
    create_submittable_event_request(login_as(Users.ORGANISER), name="Taken name", **_dates(period))

    response = _correct(login_as(Users.COORDINATOR), event, name="Taken name")

    assert response.status_code == 422
    assert "the organiser already has a request" in response.text.lower()
    assert _read(login_as(Users.COORDINATOR), event["id"])["name"] == event["name"]


@pytest.mark.story("7.2", ac=4)
@pytest.mark.parametrize("attendance", [0, -5, 1.5, "20"])
def test_attendance_must_be_a_positive_whole_number(coordinator_client, attendance):
    event = _read(coordinator_client, Events.SUBMITTED)

    response = _correct(coordinator_client, event, expected_attendance=attendance)

    assert response.status_code == 422


@pytest.mark.story("7.2", ac=4)
@pytest.mark.parametrize(
    ("field", "label"),
    [
        ("purpose", "purpose"),
        ("description", "description"),
        ("contact_email", "point of contact email"),
        ("expected_attendance", "expected attendance"),
    ],
)
def test_a_detail_needed_for_submission_cannot_be_cleared(coordinator_client, field, label):
    event = _read(coordinator_client, Events.SUBMITTED)

    response = _correct(coordinator_client, event, **{field: None})

    assert response.status_code == 422
    assert label in response.text
    assert _read(coordinator_client, Events.SUBMITTED)[field] == event[field]


@pytest.mark.story("7.2", ac=4)
def test_a_detail_missing_since_submission_must_be_added_before_saving(
    coordinator_client, db: Session
):
    """A request submitted before 2.1 made the contact phone required (as the seed data once was)
    cannot have anything else corrected until the phone is added, so a field the form marks
    required always is."""
    db.execute(
        text("UPDATE events SET contact_phone = NULL WHERE id = :id"), {"id": Events.SUBMITTED}
    )
    db.commit()
    event = _read(coordinator_client, Events.SUBMITTED)

    refused = _correct(coordinator_client, event, description="Updated agenda.")

    assert refused.status_code == 422
    assert "point of contact phone number" in refused.json()["detail"]
    saved = _correct(
        coordinator_client, event, description="Updated agenda.", contact_phone="+65 6123 4567"
    )
    assert saved.status_code == 200, saved.text


@pytest.mark.story("7.2", ac=4)
@pytest.mark.parametrize(
    "field", ["cover_image_url", "internal_notes", "status", "assigned_coordinator_id"]
)
def test_fields_outside_the_organisers_request_cannot_be_sent(coordinator_client, field):
    event = _read(coordinator_client, Events.SUBMITTED)

    response = _correct(coordinator_client, event, **{field: "anything"})

    assert response.status_code == 422
    assert _read(coordinator_client, Events.SUBMITTED)[field] == event[field]


@pytest.mark.story("7.2", ac=4)
def test_a_correction_records_each_old_and_new_value_for_the_change_history(
    coordinator_client, db: Session
):
    event = _read(coordinator_client, Events.SUBMITTED)

    response = _correct(
        coordinator_client,
        event,
        name="Data Literacy Bootcamp",
        expected_attendance=80,
        equipment=[_equipment("LAPTOP", 2)],
    )

    assert response.status_code == 200, response.text
    entry = db.execute(
        text(
            "SELECT actor_id, details, occurred_at FROM audit_log"
            " WHERE action = 'EVENT_DETAILS_CORRECTED' AND entity_id = :id"
        ),
        {"id": Events.SUBMITTED},
    ).one()
    assert entry.actor_id == Users.COORDINATOR.id
    assert entry.occurred_at is not None
    assert entry.details["name"] == {
        "from": "Data Literacy Workshop",
        "to": "Data Literacy Bootcamp",
    }
    assert entry.details["expected_attendance"] == {"from": 60, "to": 80}
    assert entry.details["equipment"]["to"] == [
        {"equipment_type_code": "LAPTOP", "quantity": 2, "technical_notes": None}
    ]
    assert set(entry.details) == {"name", "expected_attendance", "equipment"}


@pytest.mark.story("7.2", ac=4)
def test_a_correction_that_changes_nothing_writes_nothing(coordinator_client, db: Session):
    event = _read(coordinator_client, Events.SUBMITTED)

    response = _correct(coordinator_client, event, name=event["name"], purpose=event["purpose"])

    assert response.status_code == 200, response.text
    assert response.json()["updated_at"] == event["updated_at"]
    count = db.execute(
        text(
            "SELECT count(*) FROM audit_log"
            " WHERE action = 'EVENT_DETAILS_CORRECTED' AND entity_id = :id"
        ),
        {"id": Events.SUBMITTED},
    ).scalar_one()
    assert count == 0


@pytest.mark.story("7.2", ac=4)
def test_the_coordinator_can_load_the_request_forms_pick_lists(coordinator_client):
    response = coordinator_client.get("/events/reference-data")

    assert response.status_code == 200
    assert response.json()["equipment_types"]


@pytest.mark.story("7.2", ac=4)
def test_the_assigned_coordinator_replaces_the_cover_picture_under_review(
    coordinator_client, db: Session, upload_dir
):
    event = _read(coordinator_client, Events.SUBMITTED)
    assert event["cover_image_url"] == SEEDED_PICTURE

    response = _upload_picture(coordinator_client, event)

    assert response.status_code == 200, response.text
    url = response.json()["cover_image_url"]
    assert url.startswith("/uploads/events/")
    assert (upload_dir / "events" / url.removeprefix("/uploads/events/")).read_bytes() == _PNG
    assert response.json()["status"] == "UNDER_REVIEW"
    details = db.execute(
        text(
            "SELECT details FROM audit_log"
            " WHERE action = 'EVENT_DETAILS_CORRECTED' AND entity_id = :id"
        ),
        {"id": Events.SUBMITTED},
    ).scalar_one()
    assert details == {"cover_image_url": {"from": SEEDED_PICTURE, "to": url}}


@pytest.mark.story("7.2", ac=4)
def test_the_assigned_coordinator_removes_the_cover_picture_under_review(
    coordinator_client, upload_dir
):
    event = _read(coordinator_client, Events.SUBMITTED)

    response = _remove_picture(coordinator_client, event)

    assert response.status_code == 200, response.text
    assert response.json()["cover_image_url"] is None


@pytest.mark.story("7.2", ac=4)
def test_a_cover_picture_the_2_1_rules_refuse_is_refused_and_changes_nothing(
    coordinator_client, upload_dir
):
    event = _read(coordinator_client, Events.SUBMITTED)

    response = _upload_picture(coordinator_client, event, b"GIF89a not a picture we take")

    assert response.status_code == 422
    after = _read(coordinator_client, Events.SUBMITTED)
    assert after["cover_image_url"] == SEEDED_PICTURE
    assert after["updated_at"] == event["updated_at"]
    assert list(upload_dir.rglob("*.*")) == []


@pytest.mark.story("7.2", ac=4)
def test_the_organiser_cannot_use_the_coordinators_picture_upload(login_as, upload_dir):
    event = _read(login_as(Users.COORDINATOR), Events.SUBMITTED)

    response = _upload_picture(login_as(Users.ORGANISER), event)

    assert response.status_code == 403


@pytest.mark.story("7.2", ac=8)
def test_a_coordinator_not_assigned_to_the_event_cannot_change_its_picture(login_as, upload_dir):
    client = login_as(Users.COORDINATOR_2)
    event = _read(client, Events.SUBMITTED)

    assert _upload_picture(client, event).status_code == 403
    assert _remove_picture(client, event).status_code == 403
    assert _read(client, Events.SUBMITTED)["cover_image_url"] == SEEDED_PICTURE


@pytest.mark.story("7.2", ac=5)
def test_the_cover_picture_is_locked_once_the_event_is_approved(coordinator_client, upload_dir):
    event = _read(coordinator_client, Events.PLANNING)

    assert _upload_picture(coordinator_client, event).status_code == 409
    assert _remove_picture(coordinator_client, event).status_code == 409


@pytest.mark.story("7.2", ac=9)
def test_a_picture_saved_against_a_stale_copy_is_refused(coordinator_client, upload_dir):
    event = _read(coordinator_client, Events.SUBMITTED)
    stale_at = datetime.fromisoformat(event["updated_at"]) - timedelta(seconds=1)

    response = _upload_picture(coordinator_client, event, token=stale_at.isoformat())

    assert response.status_code == 409
    assert "reload" in response.json()["detail"].lower()
    assert _read(coordinator_client, Events.SUBMITTED)["cover_image_url"] == SEEDED_PICTURE


# --- AC5: details lock at approval; internal notes do not -------------------------------------
@pytest.mark.story("7.2", ac=5)
@pytest.mark.parametrize("event_id", [Events.PLANNING, Events.CONFIRMED])
def test_details_are_read_only_once_the_event_is_approved(coordinator_client, event_id):
    event = _read(coordinator_client, event_id)

    response = _correct(coordinator_client, event, name="Renamed after approval")

    assert response.status_code == 409
    assert "change request" in response.json()["detail"]
    assert _read(coordinator_client, event_id)["name"] == event["name"]


@pytest.mark.story("7.2", ac=5)
def test_internal_notes_stay_editable_once_details_are_locked(coordinator_client):
    response = coordinator_client.patch(
        f"/events/{Events.PLANNING}/routine-information",
        json={"internal_notes": "Catering confirmed."},
    )

    assert response.status_code == 200, response.text
    assert response.json()["internal_notes"] == "Catering confirmed."
    assert response.json()["status"] == "PLANNING"


@pytest.mark.story("7.2", ac=5)
def test_details_cannot_be_corrected_while_clarification_is_requested(coordinator_client):
    """Only UNDER_REVIEW is "under review"; the clarification round-trip belongs to 4.2/4.3."""
    event = _read(coordinator_client, Events.CLARIFICATION_REQUESTED)

    response = _correct(coordinator_client, event, name="Renamed mid-clarification")

    assert response.status_code == 409


@pytest.mark.story("7.2", ac=5)
@pytest.mark.parametrize(
    "status", [EventStatus.COMPLETED, EventStatus.CANCELLED, EventStatus.REJECTED]
)
def test_details_of_a_closed_event_cannot_be_corrected(login_as, db: Session, status):
    event = make_event(db, status=status, assigned_coordinator_id=Users.COORDINATOR.id)
    db.commit()
    # Refused on its status whoever asks, as the internal-notes edit is (AC3).
    client = login_as(Users.COORDINATOR_2)
    read = _read(client, event.id)

    response = _correct(client, read, name="Too late")

    assert response.status_code == 409


# --- AC6: the lock begins at approval ----------------------------------------------------------
@pytest.mark.story("7.2", ac=6)
def test_a_correction_saved_before_approval_is_kept_through_it(coordinator_client):
    event = _read(coordinator_client, Events.SUBMITTED)
    assert _correct(coordinator_client, event, name="Corrected first").status_code == 200

    approved = coordinator_client.post(f"/events/{Events.SUBMITTED}/approve")

    assert approved.status_code == 200, approved.text
    assert approved.json()["name"] == "Corrected first"


@pytest.mark.story("7.2", ac=6)
def test_a_correction_arriving_after_approval_is_refused(coordinator_client):
    """The editor was opened while under review; approval landed before Save reached the API."""
    opened = _read(coordinator_client, Events.SUBMITTED)
    assert coordinator_client.post(f"/events/{Events.SUBMITTED}/approve").status_code == 200

    response = _correct(coordinator_client, opened, name="Too late")

    assert response.status_code == 409
    assert "change request" in response.json()["detail"]
    after = _read(coordinator_client, Events.SUBMITTED)
    assert after["name"] == "Data Literacy Workshop"
    assert after["status"] == "PLANNING"


# --- AC7: date and equipment changes re-check the event's own equipment holds ------------------
@pytest.mark.story("7.2", ac=7)
def test_moving_the_dates_moves_the_equipment_holds(login_as, db: Session):
    old, new = _period(40), _period(60)
    event = _submitted_with_equipment(login_as, db, old, _equipment("LAPTOP", 2))

    response = _correct(login_as(Users.COORDINATOR), event, **_dates(new))

    assert response.status_code == 200, response.text
    assert _held(db, event["id"]) == {("LAPTOP", 2, new[0], new[1])}
    assert {h.status for h in _holds(db, event["id"]) if h.starts_at == old[0]} == {"RELEASED"}


@pytest.mark.story("7.2", ac=7)
def test_changing_the_quantity_resizes_the_hold(login_as, db: Session):
    period = _period()
    event = _submitted_with_equipment(login_as, db, period, _equipment("LAPTOP", 2))
    line = event["equipment"][0]

    response = _correct(
        login_as(Users.COORDINATOR),
        event,
        equipment=[{"id": line["id"], "equipment_type_code": "LAPTOP", "quantity": 5}],
    )

    assert response.status_code == 200, response.text
    assert _held(db, event["id"]) == {("LAPTOP", 5, period[0], period[1])}


@pytest.mark.story("7.2", ac=7)
def test_changing_the_type_holds_the_new_type_instead(login_as, db: Session):
    period = _period()
    event = _submitted_with_equipment(login_as, db, period, _equipment("LAPTOP", 2))

    response = _correct(
        login_as(Users.COORDINATOR), event, equipment=[_equipment("WIRELESS_MIC", 2)]
    )

    assert response.status_code == 200, response.text
    assert _held(db, event["id"]) == {("WIRELESS_MIC", 2, period[0], period[1])}
    assert {line["status"] for line in response.json()["equipment"]} == {"RESERVED"}


@pytest.mark.story("7.2", ac=7)
def test_removing_a_line_releases_its_hold(login_as, db: Session):
    period = _period()
    event = _submitted_with_equipment(
        login_as, db, period, _equipment("LAPTOP", 2), _equipment("WIRELESS_MIC", 3)
    )
    mic = next(line for line in event["equipment"] if line["equipment_type_code"] == "WIRELESS_MIC")

    response = _correct(
        login_as(Users.COORDINATOR),
        event,
        equipment=[{"id": mic["id"], "equipment_type_code": "WIRELESS_MIC", "quantity": 3}],
    )

    assert response.status_code == 200, response.text
    assert _held(db, event["id"]) == {("WIRELESS_MIC", 3, period[0], period[1])}


@pytest.mark.story("7.2", ac=7)
def test_the_events_own_holds_do_not_count_against_it(login_as, db: Session):
    """All the laptops are held for this event; moving it by an hour overlaps its own hold."""
    period = _period()
    event = _submitted_with_equipment(login_as, db, period, _equipment("LAPTOP", LAPTOP_STOCK))
    shifted = (period[0] + timedelta(hours=1), period[1] + timedelta(hours=1))

    response = _correct(login_as(Users.COORDINATOR), event, **_dates(shifted))

    assert response.status_code == 200, response.text
    assert _held(db, event["id"]) == {("LAPTOP", LAPTOP_STOCK, shifted[0], shifted[1])}


@pytest.mark.story("7.2", ac=7)
def test_availability_for_the_form_leaves_out_the_events_own_holds(login_as, db: Session):
    period = _period()
    event = _submitted_with_equipment(login_as, db, period, _equipment("LAPTOP", 4))

    response = login_as(Users.COORDINATOR).get(
        "/events/equipment-availability",
        params={**_dates(period), "exclude_event_id": event["id"]},
    )

    assert response.status_code == 200, response.text
    available = {row["equipment_type_code"]: row["available"] for row in response.json()}
    assert available["LAPTOP"] == LAPTOP_STOCK


@pytest.mark.story("7.2", ac=7)
def test_availability_cannot_leave_out_an_event_the_viewer_cannot_see(login_as):
    response = login_as(Users.ORGANISER_2).get(
        "/events/equipment-availability",
        params={**_dates(_period()), "exclude_event_id": str(Events.SUBMITTED)},
    )

    assert response.status_code == 404


@pytest.mark.story("7.2", ac=7)
def test_moving_into_a_period_without_enough_stock_is_refused_and_changes_nothing(
    login_as, db: Session
):
    old, new = _period(40), _period(60)
    event = _submitted_with_equipment(login_as, db, old, _equipment("LAPTOP", 2))
    make_equipment_hold(db, type_code="LAPTOP", quantity=5, starts_at=new[0], ends_at=new[1])
    db.commit()

    response = _correct(login_as(Users.COORDINATOR), event, name="Moved", **_dates(new))

    assert response.status_code == 422
    assert "presentation laptop" in response.text.lower()
    after = _read(login_as(Users.COORDINATOR), event["id"])
    assert (after["name"], after["starts_at"]) == (event["name"], event["starts_at"])
    assert _held(db, event["id"]) == {("LAPTOP", 2, old[0], old[1])}
    assert len(_holds(db, event["id"])) == 1


@pytest.mark.story("7.2", ac=7)
def test_stock_taken_between_the_check_and_the_hold_is_refused_as_unavailable(
    login_as, db: Session, monkeypatch
):
    """The 2.1 check passes, then the last units go before the types are locked: the save is
    refused as unavailable equipment (422), not as an event that changed (409), and nothing
    changes."""
    old, new = _period(40), _period(60)
    event = _submitted_with_equipment(login_as, db, old, _equipment("LAPTOP", 2))
    make_equipment_hold(db, type_code="LAPTOP", quantity=5, starts_at=new[0], ends_at=new[1])
    db.commit()
    monkeypatch.setattr(service, "_check_equipment_available", lambda *args, **kwargs: None)

    response = _correct(login_as(Users.COORDINATOR), event, **_dates(new))

    assert response.status_code == 422
    assert "presentation laptop" in response.text.lower()
    assert _held(db, event["id"]) == {("LAPTOP", 2, old[0], old[1])}


@pytest.mark.story("7.2", ac=7)
def test_resending_unchanged_dates_and_equipment_is_not_rechecked_against_the_stock(
    login_as, db: Session
):
    """The form sends every field. Another event has since taken stock the period no longer has,
    but this event already holds its own, so a correction to anything else still saves."""
    period = _period()
    event = _submitted_with_equipment(login_as, db, period, _equipment("LAPTOP", 4))
    make_equipment_hold(db, type_code="LAPTOP", quantity=3, starts_at=period[0], ends_at=period[1])
    db.commit()
    before = _holds(db, event["id"])
    resent_equipment = [
        {
            "id": line["id"],
            "equipment_type_code": line["equipment_type_code"],
            "quantity": line["quantity"],
        }
        for line in event["equipment"]
    ]

    response = _correct(
        login_as(Users.COORDINATOR),
        event,
        starts_at=event["starts_at"],
        ends_at=event["ends_at"],
        equipment=resent_equipment,
        contact_email="events@acme.example",
    )

    assert response.status_code == 200, response.text
    assert response.json()["contact_email"] == "events@acme.example"
    assert _holds(db, event["id"]) == before


@pytest.mark.story("7.2", ac=7)
def test_a_seeded_event_with_equipment_but_no_hold_is_held_when_its_dates_move(
    coordinator_client, db: Session
):
    assert _holds(db, Events.SUBMITTED) == []
    event = _read(coordinator_client, Events.SUBMITTED)
    new = _period(60)

    response = _correct(coordinator_client, event, **_dates(new))

    assert response.status_code == 200, response.text
    assert _held(db, Events.SUBMITTED) == {("PROJECTOR_PORTABLE", 1, new[0], new[1])}


@pytest.mark.story("7.2", ac=7)
def test_a_correction_that_leaves_dates_and_equipment_alone_leaves_the_holds_alone(
    login_as, db: Session
):
    period = _period()
    event = _submitted_with_equipment(login_as, db, period, _equipment("LAPTOP", 2))
    before = _holds(db, event["id"])

    response = _correct(login_as(Users.COORDINATOR), event, description="Clearer agenda.")

    assert response.status_code == 200, response.text
    assert _holds(db, event["id"]) == before


# --- AC8: only the assigned coordinator, enforced by the API ----------------------------------
@pytest.mark.story("7.2", ac=8)
def test_a_coordinator_not_assigned_to_the_event_cannot_correct_it(login_as):
    client = login_as(Users.COORDINATOR_2)
    event = _read(client, Events.SUBMITTED)

    response = _correct(client, event, name="Not mine to change")

    assert response.status_code == 403
    assert _read(client, Events.SUBMITTED)["name"] == event["name"]


@pytest.mark.story("7.2", ac=8)
@pytest.mark.parametrize(
    "user", [Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE]
)
def test_no_other_role_can_correct_details(login_as, user):
    event = _read(login_as(Users.COORDINATOR), Events.SUBMITTED)

    response = _correct(login_as(user), event, name="Not my role")

    assert response.status_code == 403
    assert _read(login_as(Users.COORDINATOR), Events.SUBMITTED)["name"] == event["name"]


@pytest.mark.story("7.2", ac=8)
def test_correcting_a_missing_event_is_not_found(coordinator_client):
    missing = {"id": str(uuid.uuid4()), "updated_at": datetime.now(UTC).isoformat()}

    response = _correct(coordinator_client, missing, name="Anything")

    assert response.status_code == 404


# --- AC9: a stale save is refused -----------------------------------------------------------
@pytest.mark.story("7.2", ac=9)
def test_a_save_made_against_a_stale_copy_is_refused(coordinator_client):
    event = _read(coordinator_client, Events.SUBMITTED)
    stale_at = datetime.fromisoformat(event["updated_at"]) - timedelta(seconds=1)
    stale = {**event, "updated_at": stale_at.isoformat()}

    response = _correct(coordinator_client, stale, name="Overwrites someone else")

    assert response.status_code == 409
    assert "reload" in response.json()["detail"].lower()
    assert _read(coordinator_client, Events.SUBMITTED)["name"] == event["name"]


@pytest.mark.story("7.2", ac=9)
def test_a_save_without_the_token_it_was_read_with_is_refused(coordinator_client):
    response = coordinator_client.patch(
        ROUTE.format(event_id=Events.SUBMITTED), json={"name": "No token"}
    )

    assert response.status_code == 422
