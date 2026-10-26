"""Story 7.2 - be: the assigned Event Coordinator corrects an event's details until it is
confirmed.

AC4 While an event is Under Review or Clarification Requested, the assigned coordinator can edit
    the organiser-provided event details, including the cover picture and the venue requirements,
    using the same checks as creating a request (2.1, and 2.7 for the venue requirements). Each
    saved change is recorded for the change history (7.4).
AC5 Once the event is approved, organiser-provided details become read-only; internal notes stay
    editable.
AC6 The lock begins at approval: a correction saved before approval applies, one that arrives
    after it is refused.
AC7 Editing the event dates before approval re-validates all date-dependent fields and re-checks
    existing equipment holds for the new period. If the required equipment is no longer
    available, the edit is refused, leaving the event and its existing holds unchanged. Venue
    conflicts are checked later when a specific venue is requested.
AC8 Only the assigned coordinator can edit, enforced by the API.
AC9 A save made against a stale copy of the event is refused, so the user can reload.

Fix f7.2.4 (Q32, Q35) moves the lock from approval to confirmation, replacing AC5 and AC6:
AC10 The details can be corrected in every status before Confirmed, Planning and Awaiting Safety
     Check included, with AC4's checks; the status does not change.
AC11 After approval, an edit that touches no booking or equipment request saves as it would
     before approval.
AC12 Once Confirmed, the details are read-only and changes go through a change request (19.1).
AC13 An edit that keeps a booked requirement exactly at its booking's times and number of people
     still fits.
AC14 After approval, an edit that no longer fits a pending or approved venue booking - times
     outside it, more people, another layout, or the requirement removed - is refused, naming
     the venue and the requirement.
AC15 After approval, the equipment is changed in its own section (15.1), not here, and a date
     move outside the period an open item is held for is refused, naming the item.
AC16 A refused edit leaves the event, its bookings, its equipment and its holds as they were.
AC17 Only the assigned coordinator can edit (AC8).
AC18 The fit is judged against the bookings and items as they stand when the save arrives.

Excluded, with reason:
* Venue re-check (AC7) - a venue request can only be raised once the event is approved (12.1
  AC1), so no venue request can exist while it is under review.
* Organiser-vs-coordinator concurrent edits (AC9) - organisers cannot edit a submitted request
  until story 4.3 exists. The stale check is exercised here with a token that no longer matches;
  the real two-transaction case is covered end to end in tests/e2e.
* Change history UI (AC4) - story 7.4. These tests check the audit row it will read.
* The cover picture is sent as a file, so it has its own endpoint beside the JSON correction,
  under the same rules (assigned coordinator, not yet confirmed, the stale-copy token).
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
from app.events.models import Event, EventStatus
from app.events.schemas import EventReviewCorrection
from tests.support.factories import (
    create_submittable_event_request,
    make_booking,
    make_equipment_hold,
    make_equipment_item,
    make_equipment_out_of_service,
    make_equipment_type,
    make_event,
    make_venue,
    make_venue_requirement,
)
from tests.support.seed import Events, Users

ROUTE = "/events/{event_id}/review-details"
PICTURE_ROUTE = "/events/{event_id}/review-details/cover-image"
# Enough of a PNG for the 2.1 type check, which reads the signature only.
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
SEEDED_PICTURE = "/images/events/cat.jpg"
LAPTOP_STOCK = 6
# Fix f2.7.4's refusal (story 2.7 AC14, AC20), written out so a red run shows what the server
# answers instead.
_NEEDS_A_VENUE_REQUIREMENT = "A request needs at least one venue requirement."


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


def _requirement_in(requirement: dict) -> dict:
    """A venue requirement as the event returns it, as a correction sends it back (story 2.7)."""
    return {
        "id": requirement["id"],
        "name": requirement["name"],
        "capacity": requirement["capacity"],
        "starts_at": requirement["starts_at"],
        "ends_at": requirement["ends_at"],
        "layout_code": requirement["layout_code"],
        "facilities": [
            {"code": f["code"], "quantity": f["quantity"], "notes": f["notes"]}
            for f in requirement["facilities"]
        ],
        "notes": requirement["notes"],
    }


def _moved_to(event: dict, period: tuple[datetime, datetime]) -> dict:
    """A correction moving ``event`` (a GET body) to ``period``, its one venue requirement with it,
    as the form moves one that kept the event's times (story 2.7 AC10 refuses an event moved away
    from its requirement). Since fix f2.7.4 every request has one, and submission gave it the
    event's times (2.7 AC2)."""
    (main_venue,) = event["venue_requirements"]
    return {
        **_dates(period),
        "venue_requirements": [{**_requirement_in(main_venue), **_dates(period)}],
    }


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
def test_details_can_be_corrected_while_clarification_is_requested(coordinator_client):
    """AC4 covers Clarification Requested too (added in the backlog's Change Log), so asking the
    organiser a question does not take the coordinator's edit away. The status stays where it
    was."""
    event = _read(coordinator_client, Events.CLARIFICATION_REQUESTED)

    response = _correct(coordinator_client, event, name="Renamed mid-clarification")

    assert response.status_code == 200, response.text
    after = _read(coordinator_client, Events.CLARIFICATION_REQUESTED)
    assert after["name"] == "Renamed mid-clarification"
    assert after["status"] == "CLARIFICATION_REQUESTED"


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
    (main_venue,) = event["venue_requirements"]

    response = _correct(
        coordinator_client,
        event,
        venue_requirements=[
            {
                **_requirement_in(main_venue),
                "layout_code": "THEATRE",
                "facilities": [{"code": "PROJECTOR"}],
            }
        ],
        accessibility_none_required=False,
        accessibility_needs=[{"code": "WHEELCHAIR_ACCESS"}],
        registration_required=True,
        registration_closes_at=(starts_at - timedelta(days=1)).isoformat(),
        is_public=True,
    )

    assert response.status_code == 200, response.text
    after = response.json()
    (corrected,) = after["venue_requirements"]
    assert corrected["id"] == main_venue["id"]
    assert corrected["layout_code"] == "THEATRE"
    assert [f["code"] for f in corrected["facilities"]] == ["PROJECTOR"]
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
        ({"venue_none_required": True}, "venue requirements cannot be marked none required"),
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
@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        pytest.param(
            lambda main: {"venue_requirements": [{**main, "ends_at": "2026-11-18T18:00:00+08:00"}]},
            "cannot end after the event ends",
            id="ends-after-the-event",
        ),
        pytest.param(
            lambda main: {"starts_at": "2026-11-18T10:00:00+08:00"},
            "cannot start before the event starts",
            id="event-moved-past-it",
        ),
        pytest.param(
            lambda main: {"venue_requirements": [main, {"name": "main venue", "capacity": 10}]},
            "cannot both be called",
            id="duplicate-name",
        ),
        pytest.param(
            lambda main: {"venue_requirements": [{**main, "id": str(uuid.uuid4())}]},
            "does not belong to this request",
            id="another-requests-requirement",
        ),
        pytest.param(
            lambda main: {"venue_requirements": [{**main, "layout_code": "NOT_A_LAYOUT"}]},
            "unknown room layout",
            id="unknown-layout",
        ),
    ],
)
def test_the_2_7_rules_apply_to_a_correction(coordinator_client, changes, expected):
    """Story 2.7's venue requirement checks are part of creating a request, so a correction runs
    them too - AC10 included, where moving the event leaves a requirement outside it."""
    event = _read(coordinator_client, Events.SUBMITTED)
    main_venue = _requirement_in(event["venue_requirements"][0])

    response = _correct(coordinator_client, event, **changes(main_venue))

    assert response.status_code == 422
    assert expected in response.text.lower()
    assert _read(coordinator_client, Events.SUBMITTED)["updated_at"] == event["updated_at"]


@pytest.mark.story("7.2", ac=4)
def test_a_refused_venue_requirement_names_the_field_to_fix(coordinator_client):
    """Located as on the organiser's own edit (2.7 AC11), so the form can mark the field."""
    event = _read(coordinator_client, Events.SUBMITTED)
    (main_venue,) = event["venue_requirements"]
    too_many = event["expected_attendance"] + 1

    response = _correct(
        coordinator_client,
        event,
        venue_requirements=[{**_requirement_in(main_venue), "capacity": too_many}],
    )

    assert response.status_code == 422
    (issue,) = response.json()["detail"]
    assert issue["loc"][-3:] == ["venue_requirements", 0, "capacity"]
    assert "main venue" in issue["msg"].lower()


@pytest.mark.story("7.2", ac=4)
def test_a_venue_requirement_correction_alone_is_saved_and_recorded(
    coordinator_client, db: Session
):
    """Story 2.7's requirements are only replaced as an edit is written, so a correction to them
    alone must still count as a change, not be rolled back as one that changed nothing."""
    event = _read(coordinator_client, Events.SUBMITTED)
    (main_venue,) = event["venue_requirements"]

    response = _correct(
        coordinator_client,
        event,
        venue_requirements=[{**_requirement_in(main_venue), "capacity": 40}],
    )

    assert response.status_code == 200, response.text
    (saved,) = _read(coordinator_client, Events.SUBMITTED)["venue_requirements"]
    assert (saved["id"], saved["capacity"]) == (main_venue["id"], 40)
    details = db.execute(
        text(
            "SELECT details FROM audit_log"
            " WHERE action = 'EVENT_DETAILS_CORRECTED' AND entity_id = :id"
        ),
        {"id": Events.SUBMITTED},
    ).scalar_one()
    assert set(details) == {"venue_requirements"}
    assert [r["capacity"] for r in details["venue_requirements"]["from"]] == [60]
    assert [r["capacity"] for r in details["venue_requirements"]["to"]] == [40]


@pytest.mark.story("7.2", ac=4)
def test_a_requirement_added_without_times_is_needed_for_the_whole_event(coordinator_client):
    """2.7 AC2, as at submission: every requirement of a submitted request has a period a booking
    can copy, so one added without times takes the event's."""
    event = _read(coordinator_client, Events.SUBMITTED)
    (main_venue,) = event["venue_requirements"]

    response = _correct(
        coordinator_client,
        event,
        venue_requirements=[_requirement_in(main_venue), {"name": "Breakout room", "capacity": 20}],
    )

    assert response.status_code == 200, response.text
    added = response.json()["venue_requirements"][1]
    assert added["name"] == "Breakout room"
    assert datetime.fromisoformat(added["starts_at"]) == datetime.fromisoformat(event["starts_at"])
    assert datetime.fromisoformat(added["ends_at"]) == datetime.fromisoformat(event["ends_at"])


@pytest.mark.story("7.2", ac=4)
@pytest.mark.story("2.7", ac=16)
@pytest.mark.story("2.7", ac=20)
def test_the_venue_requirements_cannot_all_be_removed(coordinator_client):
    """Fix f2.7.4: a request's only venue requirement can be edited, not removed (2.7 AC16), and
    the server holds a correction to that as it holds every save (AC20)."""
    event = _read(coordinator_client, Events.SUBMITTED)

    response = _correct(coordinator_client, event, venue_requirements=[])

    assert response.status_code == 422
    assert _NEEDS_A_VENUE_REQUIREMENT in response.text
    assert len(_read(coordinator_client, Events.SUBMITTED)["venue_requirements"]) == 1


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
def test_every_field_a_correction_accepts_is_compared_for_the_change_history():
    """A field missing from _request_values would make a correction to it alone look like no
    change: rolled back, answered 200, nothing saved."""
    fields = set(EventReviewCorrection.model_fields) - {"expected_updated_at"}
    assert fields <= service._request_values(Event()).keys()


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


@pytest.mark.story("7.2", ac=12)
def test_the_cover_picture_is_locked_once_the_event_is_confirmed(coordinator_client, upload_dir):
    event = _read(coordinator_client, Events.CONFIRMED)

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


# --- AC12 (f7.2.4, replacing AC5): details lock at confirmation; internal notes do not ---------
@pytest.mark.story("7.2", ac=12)
def test_details_are_read_only_once_the_event_is_confirmed(coordinator_client):
    event = _read(coordinator_client, Events.CONFIRMED)

    response = _correct(coordinator_client, event, name="Renamed after confirmation")

    assert response.status_code == 409
    assert "change request" in response.json()["detail"]
    assert _read(coordinator_client, Events.CONFIRMED)["name"] == event["name"]


@pytest.mark.story("7.2", ac=12)
def test_internal_notes_stay_editable_once_details_are_locked(coordinator_client):
    response = coordinator_client.patch(
        f"/events/{Events.CONFIRMED}/routine-information",
        json={"internal_notes": "Catering confirmed."},
    )

    assert response.status_code == 200, response.text
    assert response.json()["internal_notes"] == "Catering confirmed."
    assert response.json()["status"] == "CONFIRMED"


@pytest.mark.story("7.2", ac=12)
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


# --- AC10 (f7.2.4, replacing AC6): approval does not lock the details ---------------------------
@pytest.mark.story("7.2", ac=10)
def test_a_correction_saved_before_approval_is_kept_through_it(coordinator_client):
    event = _read(coordinator_client, Events.SUBMITTED)
    assert _correct(coordinator_client, event, name="Corrected first").status_code == 200

    approved = coordinator_client.post(f"/events/{Events.SUBMITTED}/approve")

    assert approved.status_code == 200, approved.text
    assert approved.json()["name"] == "Corrected first"


@pytest.mark.story("7.2", ac=10)
def test_a_correction_arriving_after_approval_is_refused_as_stale(coordinator_client):
    """The editor was opened while under review; approval landed before Save reached the API.
    Planning still takes corrections (f7.2.4), but the copy on screen is out of date (AC9)."""
    opened = _read(coordinator_client, Events.SUBMITTED)
    assert coordinator_client.post(f"/events/{Events.SUBMITTED}/approve").status_code == 200

    response = _correct(coordinator_client, opened, name="Too late")

    assert response.status_code == 409
    assert "reload" in response.json()["detail"].lower()
    after = _read(coordinator_client, Events.SUBMITTED)
    assert after["name"] == "Data Literacy Workshop"
    assert after["status"] == "PLANNING"


# --- AC7: date and equipment changes re-check the event's own equipment holds ------------------
@pytest.mark.story("7.2", ac=7)
def test_moving_the_dates_moves_the_equipment_holds(login_as, db: Session):
    old, new = _period(40), _period(60)
    event = _submitted_with_equipment(login_as, db, old, _equipment("LAPTOP", 2))

    response = _correct(login_as(Users.COORDINATOR), event, **_moved_to(event, new))

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
    assert {line["status"] for line in response.json()["equipment"]} == {"REQUESTED"}


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

    response = _correct(login_as(Users.COORDINATOR), event, **_moved_to(event, shifted))

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

    response = _correct(login_as(Users.COORDINATOR), event, name="Moved", **_moved_to(event, new))

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

    response = _correct(login_as(Users.COORDINATOR), event, **_moved_to(event, new))

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
    # Its venue requirement moves with it, as the form moves one that kept the event's times
    # (story 2.7 AC10 refuses an event moved away from its requirement).
    (main_venue,) = event["venue_requirements"]
    moved_venue = {**_requirement_in(main_venue), **_dates(new)}

    response = _correct(coordinator_client, event, **_dates(new), venue_requirements=[moved_venue])

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


@pytest.mark.story("7.2", ac=7)
def test_a_technical_notes_change_leaves_the_holds_alone(login_as, db: Session):
    """Units taken out of service after submission leave the event short of what it holds, but a
    correction to a line's technical notes alone does not touch the hold."""
    period = _period()
    event = _submitted_with_equipment(login_as, db, period, _equipment("LAPTOP", 4))
    make_equipment_out_of_service(
        db, type_code="LAPTOP", quantity=3, starts_at=period[0], ends_at=period[1]
    )
    db.commit()
    before = _holds(db, event["id"])
    line = {**_equipment("LAPTOP", 4), "id": event["equipment"][0]["id"]}

    response = _correct(
        login_as(Users.COORDINATOR),
        event,
        equipment=[{**line, "technical_notes": "Bring HDMI adapters."}],
    )

    assert response.status_code == 200, response.text
    assert _holds(db, event["id"]) == before


@pytest.mark.story("7.2", ac=7)
def test_a_line_replaced_by_an_identical_one_is_held_again(login_as, db: Session):
    period = _period()
    event = _submitted_with_equipment(login_as, db, period, _equipment("LAPTOP", 2))

    response = _correct(
        login_as(Users.COORDINATOR), event, name="Renamed", equipment=[_equipment("LAPTOP", 2)]
    )

    assert response.status_code == 200, response.text
    # Since 15.1 a held line stays REQUESTED, so it is the hold that must point at the new line.
    (line,) = response.json()["equipment"]
    held_for = db.scalars(
        text(
            "SELECT equipment_request_id FROM equipment_reservations"
            " WHERE event_id = :id AND status = 'RESERVED'"
        ),
        {"id": event["id"]},
    ).all()
    assert held_for == [uuid.UUID(line["id"])]


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


# --- f7.2.4: editing until the event is confirmed (AC10-AC18) ----------------------------------
LAYOUT = "THEATRE"
OTHER_LAYOUT = "CLASSROOM"
BOOKED_PEOPLE = 80
# AC10: approved and not yet confirmed. Each takes corrections and keeps its bookings and holds.
APPROVED_STATUSES = [EventStatus.PLANNING, EventStatus.AWAITING_SAFETY_CHECK]


def _planning_event(db: Session, *, status: str = EventStatus.PLANNING) -> tuple[Event, uuid.UUID]:
    """An approved event (Planning unless ``status`` says otherwise) assigned to
    ``Users.COORDINATOR``, complete enough for any correction to keep everything 2.1 AC10
    requires, with one venue requirement for its whole period. Returns the event and the
    requirement's id; the caller commits."""
    starts_at, ends_at = _period()
    event = make_event(
        db,
        status=status,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=starts_at,
        ends_at=ends_at,
        expected_attendance=100,
        description="An approved event.",
        contact_name="Priya Nair",
        contact_email="priya.nair@example.com",
        contact_phone="+65 9123 4567",
        accessibility_none_required=True,
    )
    requirement_id = make_venue_requirement(
        db,
        event.id,
        capacity=BOOKED_PEOPLE,
        starts_at=starts_at,
        ends_at=ends_at,
        layout_code=LAYOUT,
    )
    return event, requirement_id


def _book(
    db: Session,
    event: Event,
    requirement_id: uuid.UUID | None,
    *,
    status: str = "APPROVED",
    people: int = BOOKED_PEOPLE,
):
    """A booking of a fresh venue for ``requirement_id``, recording the requirement as it is now:
    the event's period, ``people`` and ``LAYOUT`` - the values Venue Staff decided on. With no
    requirement it is an additional venue (12.5), which asks for no layout."""
    venue = make_venue(db, capacity=200, layouts={LAYOUT: None})
    expiry = {} if status == "PENDING" else {"hold_expires_at": event.starts_at}
    return make_booking(
        db,
        venue_id=venue.id,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        status=status,
        event_id=event.id,
        venue_requirement_id=requirement_id,
        expected_attendance=people,
        required_layout_code=None if requirement_id is None else LAYOUT,
        **expiry,
    )


def _requirement_change(event: dict, **changes) -> dict:
    """The event's one venue requirement, sent back with ``changes``."""
    return {"venue_requirements": [{**_requirement_in(event["venue_requirements"][0]), **changes}]}


def _booking_row(db: Session, booking_id) -> tuple:
    db.expire_all()
    return db.execute(
        text(
            "SELECT status, starts_at, ends_at, expected_attendance, venue_requirement_id"
            " FROM venue_bookings WHERE id = :id"
        ),
        {"id": booking_id},
    ).one()


def _item_status(db: Session, item_id) -> str:
    db.expire_all()
    return db.execute(
        text("SELECT status FROM event_equipment_requests WHERE id = :id"), {"id": item_id}
    ).scalar_one()


# AC10: Planning and Awaiting Safety Check take corrections; the status stays where it was.
@pytest.mark.story("7.2", ac=10)
@pytest.mark.parametrize("status", APPROVED_STATUSES)
def test_details_can_be_corrected_after_approval_until_confirmed(login_as, db: Session, status):
    event, _ = _planning_event(db, status=status)
    db.commit()
    client = login_as(Users.COORDINATOR)

    response = _correct(client, _read(client, event.id), name="Renamed while planning")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == status
    details = db.execute(
        text(
            "SELECT details FROM audit_log"
            " WHERE action = 'EVENT_DETAILS_CORRECTED' AND entity_id = :id"
        ),
        {"id": event.id},
    ).scalar_one()
    assert details["name"]["to"] == "Renamed while planning"


@pytest.mark.story("7.2", ac=10)
def test_the_cover_picture_can_be_changed_while_the_event_is_planning(
    login_as, db: Session, upload_dir
):
    event, _ = _planning_event(db)
    db.commit()
    client = login_as(Users.COORDINATOR)

    uploaded = _upload_picture(client, _read(client, event.id))
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["cover_image_url"] is not None
    removed = _remove_picture(client, _read(client, event.id))

    assert removed.status_code == 200, removed.text
    assert removed.json()["cover_image_url"] is None


@pytest.mark.story("7.2", ac=10)
def test_corrections_while_planning_keep_the_2_1_checks(login_as, db: Session):
    event, _ = _planning_event(db)
    db.commit()
    client = login_as(Users.COORDINATOR)

    response = _correct(client, _read(client, event.id), description="")

    assert response.status_code == 422
    assert _read(client, event.id)["description"] == "An approved event."


@pytest.mark.story("7.2", ac=10)
@pytest.mark.parametrize(
    ("cleared", "label", "booked"),
    [
        ("starts_at", "proposed start date and time", "held_item"),
        ("ends_at", "proposed end date and time", "held_item"),
        ("expected_attendance", "expected attendance", "additional_venue"),
        ("expected_attendance", "expected attendance", "requirement_without_people"),
    ],
)
def test_clearing_a_date_or_the_attendance_after_approval_is_refused_as_missing(
    login_as, db: Session, cleared, label, booked
):
    """As before approval, a cleared detail submission needed is named (2.1 AC10), even where a
    held item or a booking would otherwise have been judged against it."""
    event, requirement_id = _planning_event(db)
    if booked == "held_item":
        make_equipment_item(
            db, event=event, equipment_type=make_equipment_type(db), quantity=2, status="ACCEPTED"
        )
    elif booked == "additional_venue":
        _book(db, event, None, people=event.expected_attendance)
    else:
        db.execute(
            text("UPDATE venue_requirements SET capacity = NULL WHERE id = :id"),
            {"id": requirement_id},
        )
        _book(db, event, requirement_id, people=event.expected_attendance)
    db.commit()
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)

    response = _correct(client, read, **{cleared: None})

    assert response.status_code == 422, response.text
    assert label in response.json()["detail"]
    assert _read(client, event.id)[cleared] == read[cleared]


# AC11: an edit that touches no booking or equipment saves as it does under review.
@pytest.mark.story("7.2", ac=11)
def test_an_edit_that_touches_no_booking_saves_and_leaves_the_booking_alone(login_as, db: Session):
    event, requirement_id = _planning_event(db)
    booking = _book(db, event, requirement_id)
    db.commit()
    before = _booking_row(db, booking.id)
    client = login_as(Users.COORDINATOR)

    response = _correct(
        client,
        _read(client, event.id),
        description="Now with a keynote.",
        contact_email="events@acme.example",
    )

    assert response.status_code == 200, response.text
    assert response.json()["description"] == "Now with a keynote."
    assert _booking_row(db, booking.id) == before


# AC12: confirmation landing while the form is open still locks the details.
@pytest.mark.story("7.2", ac=12)
def test_a_correction_arriving_after_confirmation_is_refused(login_as, db: Session):
    """No story confirms an event yet (21.x), so the status is set directly."""
    event, _ = _planning_event(db)
    db.commit()
    client = login_as(Users.COORDINATOR)
    opened = _read(client, event.id)
    db.execute(text("UPDATE events SET status = 'CONFIRMED' WHERE id = :id"), {"id": event.id})
    db.commit()

    response = _correct(client, opened, name="Too late")

    assert response.status_code == 409
    assert "change request" in response.json()["detail"]
    assert _read(client, event.id)["name"] == opened["name"]


# AC13: exactly at the booking's limits still fits.
@pytest.mark.story("7.2", ac=13)
def test_a_requirement_kept_exactly_at_its_booking_still_fits(login_as, db: Session):
    event, requirement_id = _planning_event(db)
    _book(db, event, requirement_id)
    db.commit()
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)

    response = _correct(
        client,
        read,
        **_requirement_change(
            read,
            starts_at=event.starts_at.isoformat(),
            ends_at=event.ends_at.isoformat(),
            capacity=BOOKED_PEOPLE,
            notes="Stage on the left.",
        ),
    )

    assert response.status_code == 200, response.text
    assert response.json()["venue_requirements"][0]["notes"] == "Stage on the left."


# AC14: an edit that no longer fits a booking is refused, naming it. AC16: a refused edit changes
# nothing, so each refusal below also reads the event, its booking or its holds again. It is a 422,
# not a 409: the copy on screen is not out of date, the change itself does not fit.
@pytest.mark.story("7.2", ac=14)
@pytest.mark.story("7.2", ac=16)
@pytest.mark.parametrize(
    "case",
    ["ends_a_minute_late", "starts_a_minute_early", "one_more_person", "another_layout"],
)
def test_a_requirement_edit_that_no_longer_fits_its_booking_is_refused(login_as, db: Session, case):
    event, requirement_id = _planning_event(db)
    booking = _book(db, event, requirement_id)
    db.commit()
    before = _booking_row(db, booking.id)
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)
    minute = timedelta(minutes=1)
    change = {
        "ends_a_minute_late": {"ends_at": (event.ends_at + minute).isoformat()},
        "starts_a_minute_early": {"starts_at": (event.starts_at - minute).isoformat()},
        "one_more_person": {"capacity": BOOKED_PEOPLE + 1},
        "another_layout": {"layout_code": OTHER_LAYOUT},
    }[case]
    # The event's own period moves with the requirement, so only the booking can refuse it.
    period = {
        "ends_a_minute_late": {"ends_at": (event.ends_at + minute).isoformat()},
        "starts_a_minute_early": {"starts_at": (event.starts_at - minute).isoformat()},
    }.get(case, {})

    response = _correct(client, read, **period, **_requirement_change(read, **change))

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert booking.venue.name in detail
    assert "Main venue" in detail
    assert "within what was booked" in detail
    after = _read(client, event.id)
    assert after["venue_requirements"] == read["venue_requirements"]
    assert (after["starts_at"], after["ends_at"]) == (read["starts_at"], read["ends_at"])
    assert _booking_row(db, booking.id) == before


@pytest.mark.story("7.2", ac=14)
@pytest.mark.story("7.2", ac=16)
def test_removing_a_booked_requirement_is_refused(login_as, db: Session):
    event, requirement_id = _planning_event(db)
    booking = _book(db, event, requirement_id)
    make_venue_requirement(
        db,
        event.id,
        position=1,
        name="Breakout room",
        capacity=20,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
    )
    db.commit()
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)
    breakout = next(r for r in read["venue_requirements"] if r["name"] == "Breakout room")

    response = _correct(client, read, venue_requirements=[_requirement_in(breakout)])

    assert response.status_code == 422, response.text
    assert booking.venue.name in response.json()["detail"]
    assert len(_read(client, event.id)["venue_requirements"]) == 2
    assert _booking_row(db, booking.id).venue_requirement_id == requirement_id


@pytest.mark.story("7.2", ac=14)
@pytest.mark.story("7.2", ac=16)
@pytest.mark.parametrize("status", APPROVED_STATUSES)
def test_moving_the_event_moves_a_booked_requirement_out_of_its_booking(
    login_as, db: Session, status
):
    """The form moves a requirement that follows the event (2.7 AC2) along with it."""
    event, requirement_id = _planning_event(db, status=status)
    booking = _book(db, event, requirement_id)
    db.commit()
    before = _booking_row(db, booking.id)
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)
    hour = timedelta(hours=1)
    moved = {"starts_at": event.starts_at + hour, "ends_at": event.ends_at + hour}
    moved = {key: value.isoformat() for key, value in moved.items()}

    response = _correct(client, read, **moved, **_requirement_change(read, **moved))

    assert response.status_code == 422, response.text
    assert booking.venue.name in response.json()["detail"]
    after = _read(client, event.id)
    assert (after["starts_at"], after["ends_at"]) == (read["starts_at"], read["ends_at"])
    assert after["venue_requirements"] == read["venue_requirements"]
    assert _booking_row(db, booking.id) == before


@pytest.mark.story("7.2", ac=14)
def test_fewer_people_and_shorter_times_inside_the_booking_still_fit(login_as, db: Session):
    event, requirement_id = _planning_event(db)
    _book(db, event, requirement_id)
    db.commit()
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)
    hour = timedelta(hours=1)

    response = _correct(
        client,
        read,
        **_requirement_change(
            read,
            starts_at=(event.starts_at + hour).isoformat(),
            ends_at=(event.ends_at - hour).isoformat(),
            capacity=BOOKED_PEOPLE - 30,
        ),
    )

    assert response.status_code == 200, response.text
    assert response.json()["venue_requirements"][0]["capacity"] == BOOKED_PEOPLE - 30


@pytest.mark.story("7.2", ac=14)
@pytest.mark.story("7.2", ac=16)
@pytest.mark.parametrize(
    ("status", "is_refused"),
    [
        ("PENDING", True),
        ("REJECTED", False),
        ("WITHDRAWN", False),
        ("CANCELLED", False),
        ("EXPIRED", False),
    ],
)
def test_only_a_pending_or_approved_booking_holds_its_requirement(
    login_as, db: Session, status, is_refused
):
    event, requirement_id = _planning_event(db)
    booking = _book(db, event, requirement_id, status=status)
    db.commit()
    before = _booking_row(db, booking.id)
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)

    response = _correct(client, read, **_requirement_change(read, capacity=BOOKED_PEOPLE + 1))

    assert response.status_code == (422 if is_refused else 200), response.text
    assert (booking.venue.name in response.text) is is_refused
    if is_refused:
        assert _read(client, event.id)["venue_requirements"] == read["venue_requirements"]
    assert _booking_row(db, booking.id) == before


@pytest.mark.story("7.2", ac=14)
@pytest.mark.story("7.2", ac=16)
def test_a_requirement_with_no_people_of_its_own_is_held_to_the_events_attendance(
    login_as, db: Session
):
    """A requirement with no number of its own was booked for the event's attendance
    (``people_to_hold``), so raising that attendance no longer fits the booking."""
    event, requirement_id = _planning_event(db)
    db.execute(
        text("UPDATE venue_requirements SET capacity = NULL WHERE id = :id"), {"id": requirement_id}
    )
    booking = _book(db, event, requirement_id, people=event.expected_attendance)
    db.commit()
    before = _booking_row(db, booking.id)
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)

    response = _correct(client, read, expected_attendance=event.expected_attendance + 1)

    assert response.status_code == 422, response.text
    assert booking.venue.name in response.json()["detail"]
    assert _read(client, event.id)["expected_attendance"] == event.expected_attendance
    assert _booking_row(db, booking.id) == before


@pytest.mark.story("7.2", ac=14)
@pytest.mark.story("7.2", ac=16)
@pytest.mark.parametrize(
    "case",
    [
        "moved_an_hour_later",
        "starts_an_hour_early",
        "one_more_person",
        "requirement_needs_more_people",
    ],
)
def test_an_additional_venue_is_held_to_the_events_own_period_and_attendance(
    login_as, db: Session, case
):
    """An additional venue (12.5, no requirement) was booked for the event's own period and
    attendance, so it is those that have to keep fitting; a requirement's own needs do not."""
    event, _ = _planning_event(db)
    booking = _book(db, event, None, people=event.expected_attendance)
    db.commit()
    before = _booking_row(db, booking.id)
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)
    hour = timedelta(hours=1)
    moved = {
        "starts_at": (event.starts_at + hour).isoformat(),
        "ends_at": (event.ends_at + hour).isoformat(),
    }
    earlier = {"starts_at": (event.starts_at - hour).isoformat()}
    change, is_refused = {
        "moved_an_hour_later": ({**moved, **_requirement_change(read, **moved)}, True),
        "starts_an_hour_early": ({**earlier, **_requirement_change(read, **earlier)}, True),
        "one_more_person": ({"expected_attendance": event.expected_attendance + 1}, True),
        "requirement_needs_more_people": (
            _requirement_change(read, capacity=BOOKED_PEOPLE + 1),
            False,
        ),
    }[case]

    response = _correct(client, read, **change)

    assert response.status_code == (422 if is_refused else 200), response.text
    assert (booking.venue.name in response.text) is is_refused
    if is_refused:
        after = _read(client, event.id)
        assert (after["starts_at"], after["expected_attendance"]) == (
            read["starts_at"],
            read["expected_attendance"],
        )
    assert _booking_row(db, booking.id) == before


@pytest.mark.story("7.2", ac=14)
@pytest.mark.parametrize(
    ("case", "is_refused"),
    [("description_only", False), ("attendance_lowered", False), ("attendance_raised", True)],
)
def test_attendance_already_past_a_kept_booking_is_judged_only_when_raised(
    login_as, db: Session, case, is_refused
):
    """Fix f19.2.1: an approved change raising the attendance keeps an additional venue booked
    for fewer people, so the event already expects more than it was booked for. A correction that
    leaves the attendance alone, or lowers it, is not refused for that; one that raises it further
    still is. (A requirement with no number of its own cannot reach this check: a correction
    refuses it first, as 2.1 AC10 requires a number.)"""
    event, _ = _planning_event(db)
    booking = _book(db, event, None, people=60)
    db.commit()
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)
    change = {
        "description_only": {"description": "Now with a keynote."},
        "attendance_lowered": {"expected_attendance": event.expected_attendance - 10},
        "attendance_raised": {"expected_attendance": event.expected_attendance + 1},
    }[case]

    response = _correct(client, read, **change)

    assert response.status_code == (422 if is_refused else 200), response.text
    assert (booking.venue.name in response.text) is is_refused


# AC15: after approval, equipment is changed in its own section, and its holds bound the dates.
@pytest.mark.story("7.2", ac=15)
@pytest.mark.story("7.2", ac=16)
@pytest.mark.parametrize("status", APPROVED_STATUSES)
@pytest.mark.parametrize("case", ["quantity", "technical_notes", "type", "emptied"])
def test_the_equipment_cannot_be_changed_here_after_approval(login_as, db: Session, status, case):
    """Sent at all, the list must come back exactly as it is: an empty list would remove every
    line, the accepted ones included."""
    event, _ = _planning_event(db, status=status)
    item = make_equipment_item(
        db, event=event, equipment_type=make_equipment_type(db), quantity=2, technical_notes="HDMI"
    )
    other_type = make_equipment_type(db)
    db.commit()
    held = _held(db, event.id)
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)
    line = {
        "id": read["equipment"][0]["id"],
        "equipment_type_code": read["equipment"][0]["equipment_type_code"],
        "quantity": 2,
        "technical_notes": "HDMI",
    }
    equipment = {
        "quantity": [{**line, "quantity": 3}],
        "technical_notes": [{**line, "technical_notes": "VGA"}],
        "type": [{**line, "equipment_type_code": other_type.code}],
        "emptied": [],
    }[case]

    response = _correct(client, read, equipment=equipment)

    assert response.status_code == 422, response.text
    assert "can no longer be changed here" in response.json()["detail"]
    assert _read(client, event.id)["equipment"] == read["equipment"]
    assert _item_status(db, item.id) == "REQUESTED"
    assert _held(db, event.id) == held


@pytest.mark.story("7.2", ac=15)
def test_a_correction_that_leaves_the_equipment_out_saves_beside_a_reopened_type(
    login_as, db: Session
):
    """15.1 lets a type declined by Technical Support be requested again, so an approved event can
    carry two lines of one type - which 2.1's one-line-per-type rule would refuse if the list were
    sent. The form leaves the equipment out once the event is approved, and that saves."""
    event, _ = _planning_event(db)
    projector = make_equipment_type(db)
    declined = make_equipment_item(
        db, event=event, equipment_type=projector, quantity=1, status="DECLINED", is_held=False
    )
    requested = make_equipment_item(db, event=event, equipment_type=projector, quantity=1)
    db.commit()
    client = login_as(Users.COORDINATOR)

    response = _correct(client, _read(client, event.id), name="Renamed beside a reopened type")

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Renamed beside a reopened type"
    assert (_item_status(db, declined.id), _item_status(db, requested.id)) == (
        "DECLINED",
        "REQUESTED",
    )


@pytest.mark.story("7.2", ac=15)
def test_the_equipment_resent_unchanged_does_not_block_a_save(login_as, db: Session):
    """The form leaves the equipment out once the event is approved, but an API call may still
    send it; sent back exactly as it is, it is not a change."""
    event, _ = _planning_event(db)
    make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db),
        quantity=2,
        technical_notes="HDMI",
    )
    db.commit()
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)
    resent = [
        {
            "id": line["id"],
            "equipment_type_code": line["equipment_type_code"],
            "quantity": line["quantity"],
            "technical_notes": line["technical_notes"],
        }
        for line in read["equipment"]
    ]

    response = _correct(client, read, equipment=resent, name="Renamed with equipment")

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Renamed with equipment"


@pytest.mark.story("7.2", ac=15)
@pytest.mark.story("7.2", ac=16)
@pytest.mark.parametrize("status", ["REQUESTED", "PENDING", "ACCEPTED"])
@pytest.mark.parametrize("moved", ["ends_an_hour_late", "starts_an_hour_early"])
def test_moving_the_dates_beyond_an_open_items_hold_is_refused(
    login_as, db: Session, status, moved
):
    event, _ = _planning_event(db)
    kit = make_equipment_type(db)
    item = make_equipment_item(db, event=event, equipment_type=kit, quantity=2, status=status)
    db.commit()
    held = _held(db, event.id)
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)
    hour = timedelta(hours=1)
    change = {
        "ends_an_hour_late": {"ends_at": (event.ends_at + hour).isoformat()},
        "starts_an_hour_early": {"starts_at": (event.starts_at - hour).isoformat()},
    }[moved]

    response = _correct(client, read, **change)

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert kit.name in detail
    assert "held period" in detail
    after = _read(client, event.id)
    assert (after["starts_at"], after["ends_at"]) == (read["starts_at"], read["ends_at"])
    assert _item_status(db, item.id) == status
    assert _held(db, event.id) == held


@pytest.mark.story("7.2", ac=15)
@pytest.mark.parametrize("shortened", ["ends_an_hour_earlier", "starts_an_hour_later"])
def test_shortening_the_dates_inside_the_holds_keeps_the_accepted_equipment(
    login_as, db: Session, shortened
):
    """The end left where it was is exactly the hold's end (or the start its start), which still
    covers the event."""
    event, _ = _planning_event(db)
    item = make_equipment_item(
        db, event=event, equipment_type=make_equipment_type(db), quantity=2, status="ACCEPTED"
    )
    db.commit()
    held = _held(db, event.id)
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)
    hour = timedelta(hours=1)
    change = {
        "ends_an_hour_earlier": {"ends_at": (event.ends_at - hour).isoformat()},
        "starts_an_hour_later": {"starts_at": (event.starts_at + hour).isoformat()},
    }[shortened]

    response = _correct(client, read, **change, **_requirement_change(read, **change))

    assert response.status_code == 200, response.text
    assert _item_status(db, item.id) == "ACCEPTED"
    assert _held(db, event.id) == held


@pytest.mark.story("7.2", ac=15)
@pytest.mark.parametrize("status", ["DECLINED", "CANCELLED"])
def test_a_declined_or_cancelled_item_does_not_bound_the_dates(login_as, db: Session, status):
    event, _ = _planning_event(db)
    make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db),
        quantity=2,
        status=status,
        is_held=False,
    )
    db.commit()
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)

    response = _correct(client, read, ends_at=(event.ends_at + timedelta(hours=1)).isoformat())

    assert response.status_code == 200, response.text


@pytest.mark.story("7.2", ac=15)
def test_an_open_item_holding_nothing_does_not_bound_the_dates(login_as, db: Session):
    """A seeded item that predates holds has no period to keep inside, and is not held for the
    new one either: its hold is Technical Support's to place."""
    event, _ = _planning_event(db)
    item = make_equipment_item(
        db, event=event, equipment_type=make_equipment_type(db), quantity=2, is_held=False
    )
    db.commit()
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)
    later_start = (event.starts_at + timedelta(hours=1)).isoformat()

    response = _correct(
        client, read, starts_at=later_start, **_requirement_change(read, starts_at=later_start)
    )

    assert response.status_code == 200, response.text
    assert _item_status(db, item.id) == "REQUESTED"
    assert _held(db, event.id) == set()


@pytest.mark.story("7.2", ac=15)
def test_an_event_with_nothing_booked_moves_freely_after_approval(login_as, db: Session):
    event, _ = _planning_event(db)
    db.commit()
    client = login_as(Users.COORDINATOR)
    read = _read(client, event.id)
    day = timedelta(days=1)
    starts_at, ends_at = event.starts_at + day, event.ends_at + day
    moved = {"starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat()}

    response = _correct(client, read, **moved, **_requirement_change(read, **moved))

    assert response.status_code == 200, response.text
    after = _read(client, event.id)
    assert datetime.fromisoformat(after["starts_at"]) == starts_at
    assert datetime.fromisoformat(after["ends_at"]) == ends_at


# AC17: only the assigned coordinator, in Planning as under review.
@pytest.mark.story("7.2", ac=17)
@pytest.mark.parametrize("user", [Users.COORDINATOR_2, Users.ORGANISER])
def test_only_the_assigned_coordinator_corrects_a_planning_event(login_as, db: Session, user):
    event, _ = _planning_event(db)
    db.commit()
    read = _read(login_as(Users.COORDINATOR), event.id)

    response = _correct(login_as(user), read, name="Not mine to change")

    assert response.status_code == 403
    assert _read(login_as(Users.COORDINATOR), event.id)["name"] == read["name"]


# AC18: the fit is judged against the bookings as they stand when the save arrives.
@pytest.mark.story("7.2", ac=18)
@pytest.mark.story("7.2", ac=16)
def test_a_booking_requested_after_the_form_opened_is_still_respected(login_as, db: Session):
    event, requirement_id = _planning_event(db)
    db.commit()
    client = login_as(Users.COORDINATOR)
    opened = _read(client, event.id)
    booking = _book(db, event, requirement_id, status="PENDING")
    db.commit()
    before = _booking_row(db, booking.id)

    response = _correct(client, opened, **_requirement_change(opened, capacity=BOOKED_PEOPLE + 1))

    assert response.status_code == 422, response.text
    assert booking.venue.name in response.json()["detail"]
    assert _read(client, event.id)["venue_requirements"] == opened["venue_requirements"]
    assert _booking_row(db, booking.id) == before
