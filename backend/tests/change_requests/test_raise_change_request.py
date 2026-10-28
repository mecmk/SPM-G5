"""Story 19.1 - be: raise an event change request.

Happy path
AC1 On an event in Planning, the organiser picks a field (date/time, expected attendance, venue
    requirements, equipment), enters the new value and a reason, and submits. Nothing changes yet;
    the request shows as pending to the assigned coordinator, who is notified.
AC2 The point of contact (email, phone) can be updated from the same page. It is applied directly
    and logged in the change history (7.4).
AC3 The server validates the proposed values with the creation rules and saves the pending
    request without changing the event.

Boundary
AC4 A reason is mandatory. New values follow the same rules as creation (date limits, whole
    numbers, valid email and phone). A value identical to the current one is refused.

Edge
AC5 Only one pending request per field per event. Before final approval, change requests are not
    offered. (Its last sentence, "Once the event is Confirmed, change requests are not offered and
    the API refuses them", is replaced by AC11.)
AC6 The server refuses a duplicate pending request for the same field.

Permission
AC7 Only the owning organiser can raise change requests. Coordinators cannot raise them.

Conflict
AC8 If the event is cancelled while the request is being written, submitting it is refused.
    (Its "or becomes Confirmed" is replaced by AC11, so a request written while the event became
    Confirmed is now taken. AC13 repeats the cancelled case and adds completed.)

Withdrawal (added by the PO at Checkpoint 1)
AC9 The organiser can withdraw their own pending change request. It is kept as Withdrawn, the
    assigned coordinator is notified, and the field is free for a new request.
AC10 Only a Pending request can be withdrawn, including one decided while the organiser was
    confirming; only the owning organiser can withdraw.

Change requests on Confirmed events (f19.1.1)
AC11 The organiser can raise change requests on a Confirmed event as on a Planning one (replaces
    AC5's last sentence, and AC8's refusal when the event becomes Confirmed) (Q39). Approving one
    returns the event to Planning for every check again before it is confirmed again (19.2 AC8).
AC12 Change requests are still not offered before approval (AC5) or for Completed, Cancelled or
    Rejected events, and the API refuses them. Whether they are offered while the event is
    Awaiting Safety Check waits on Q20.
AC13 If the event is cancelled or completed while a request is being written, submitting it is
    refused.

Decisions recorded at Checkpoint 1 that these tests rely on:
* Date and time is one field, ``schedule``, holding ``starts_at`` and ``ends_at`` together.
* "Venue" is requested through ``venue_requirements``; organisers cannot pick a venue.
* Each proposed value is checked on its own creation rules against the event as it stands;
  effects on other fields, bookings and holds are story 19.3's impact view.
* The point of contact may be updated while Planning or Confirmed, and is logged to
  ``audit_log`` as ``EVENT_CONTACT_UPDATED`` (7.4's change history is not built yet).

Decisions recorded for fix f19.1.1 (CL-149, and the review of #125):
* Until Q20 is answered, an event awaiting its safety check takes no change requests, and the API
  refuses them with a sentence of its own (AC12).
* On a Confirmed event the form warns the organiser, before sending, that approval returns the
  event to Planning for a new safety check (AC11; the warning is an e2e case).
* Change requests close 24 hours before the event's set-up time: the earliest set-up start
  (``held_from``) among its bookings that hold a venue, Pending or Approved, or its start time if
  that is earlier or it has none. That covers an event already under way or over, which nothing
  marks Completed yet (Q57). (Team decision on the review of #125.)

Minimum attendance (fix f19.1.2; Q80 to Q82, CL-172, replacing CL-143's refusal on raising)
AC14 The change form shows, beneath the new attendance, the lowest allowed and the venue
     requirement setting it - a pending venue requirements change's when lower (e2e).
AC15 An attendance below a venue requirement's number of people is taken when the event's pending
     venue requirements change would bring every requirement to or below it. One that is out of
     date (19.2 AC7) does not count. (AC3's exception.)
AC16 Otherwise it is refused, naming the requirement needing the most people (the first on the
     form when two tie), the exact minimum, and that the venue requirements change comes first.
AC17 A pending attendance change the venue requirements do not allow yet says what it waits for,
     to the organiser and to the coordinator (e2e).

Excluded, with reason:
* What the form offers (AC11/AC12: offered on a Confirmed event, with what approval means; not
  offered before approval, while awaiting the safety check, once completed or cancelled, or
  within 24 hours of set-up, with the page saying when they close) and the reason field blocking
  submit (AC4's client-side half) are UI behaviour, proven in tests/e2e/change-requests.spec.ts.
* Most AC8 and AC13 cases share the test's one connection, so the other transaction is simulated
  by changing the status just before submitting.
  ``test_a_request_waits_for_a_cancellation_landing_at_the_same_time`` runs the real race, on two
  connections, to pin the row lock that makes it safe. AC1's handover also runs on two
  connections: what it proves is what the waiting request reads.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.change_requests import service as change_requests_service
from app.change_requests.models import EventChangeRequest
from app.change_requests.schemas import AttendanceChangeIn
from app.common.audit import AuditLog
from app.coordination import service as coordination_service
from app.coordination.models import EventCoordinatorAssignment
from app.coordination.schemas import AssignCoordinatorIn
from app.events.models import Event, EventStatus
from app.notifications.models import Notification
from tests.support.change_requests import approve_as_seen
from tests.support.factories import (
    future_datetime,
    make_booking,
    make_equipment_hold,
    make_event,
    make_venue,
    make_venue_requirement,
)
from tests.support.seed import Events, Users

_REASON = "The keynote speaker can only attend a day later."
# The service's own refusals, so a 404 is never confused with a route that does not exist.
_EVENT_NOT_FOUND = "Event not found."
_CHANGE_REQUEST_NOT_FOUND = "Change request not found."
# AC12/AC13: the sentence for each status that takes no change requests.
_CLOSED_REFUSAL = "This event is {status}, so it no longer takes change requests."
_AWAITING_SAFETY_CHECK_REFUSAL = (
    "This event is awaiting its safety check, so it does not take change requests."
)
_CLOSED_BEFORE_SETUP_REFUSAL = (
    "Change requests for this event closed 24 hours before its set-up time."
)
# Fix f19.1.2: an attendance below a venue requirement's number of people names the requirement
# that sets the minimum, the minimum itself, and what to change first.
_ATTENDANCE_BELOW_REFUSAL = (
    "The expected attendance cannot be lower than {minimum} while {requirement} needs room for"
    " {minimum} people. Ask for a venue requirements change that lowers it first."
)
_CURRENT_EMAIL = "olivia.events@acme.example"
_CURRENT_PHONE = "+65 6111 2233"


# --- helpers ---------------------------------------------------------------------------------
def _planning_event(db: Session, **overrides) -> Event:
    """Olivia's event in Planning, assigned to Chloe, dated safely in the future."""
    starts_at = overrides.pop("starts_at", future_datetime(days=60))
    return make_event(
        db,
        status=overrides.pop("status", EventStatus.PLANNING),
        starts_at=starts_at,
        ends_at=overrides.pop("ends_at", starts_at + timedelta(hours=8)),
        expected_attendance=overrides.pop("expected_attendance", 100),
        assigned_coordinator_id=overrides.pop("assigned_coordinator_id", Users.COORDINATOR.id),
        contact_name="Olivia Organiser",
        contact_email=overrides.pop("contact_email", _CURRENT_EMAIL),
        contact_phone=overrides.pop("contact_phone", _CURRENT_PHONE),
        **overrides,
    )


def _schedule(starts_at: datetime, ends_at: datetime) -> dict:
    return {"starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat()}


def _moved_a_day(event: Event) -> dict:
    return _schedule(event.starts_at + timedelta(days=1), event.ends_at + timedelta(days=1))


def _raise(client, event_id: uuid.UUID, field: str, proposed, reason: str | None = _REASON):
    body: dict = {"field": field, "proposed": proposed}
    if reason is not None:
        body["reason"] = reason
    return client.post(f"/events/{event_id}/change-requests", json=body)


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


def _insert_change_request(
    db: Session, event_id: uuid.UUID, *, field: str = "expected_attendance", status: str = "PENDING"
) -> uuid.UUID:
    """A change request written in SQL, so a test can start from any status (as 19.4/19.5 would
    leave it) without those stories existing."""
    return db.execute(
        text(
            "INSERT INTO event_change_requests"
            " (event_id, requested_by_id, field_name, current_value, proposed_value, reason,"
            " status)"
            " VALUES (:e, :u, :f, '100', '150', 'More sign-ups than expected.', :s) RETURNING id"
        ),
        {"e": event_id, "u": Users.ORGANISER.id, "f": field, "s": status},
    ).scalar_one()


def _set_status(db: Session, event_id: uuid.UUID, status: str) -> None:
    """Another transaction changing the event's status (simulated on the test's connection)."""
    db.execute(text("UPDATE events SET status = :s WHERE id = :e"), {"s": status, "e": event_id})
    db.expire_all()


def _add_equipment_line(db: Session, event_id: uuid.UUID, code: str, quantity: int) -> None:
    db.execute(
        text(
            "INSERT INTO event_equipment_requests (event_id, equipment_type_id, quantity)"
            " SELECT :e, id, :q FROM equipment_types WHERE code = :c"
        ),
        {"e": event_id, "q": quantity, "c": code},
    )
    db.expire_all()


def _as_moment(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --- AC1: raise a change on a Planning event ---------------------------------------------------
@pytest.mark.story("19.1", ac=1)
def test_organiser_raises_a_change_saved_as_pending(organiser_client, db: Session):
    event = _planning_event(db)
    proposed = _moved_a_day(event)

    response = _raise(organiser_client, event.id, "schedule", proposed)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["field"] == "schedule"
    assert body["status"] == "PENDING"
    assert body["reason"] == _REASON
    assert _as_moment(body["proposed_value"]["starts_at"]) == event.starts_at + timedelta(days=1)
    assert _as_moment(body["current_value"]["starts_at"]) == event.starts_at
    [row] = _change_requests(db, event.id)
    assert row.status == "PENDING"
    assert row.field_name == "schedule"
    assert row.requested_by_id == Users.ORGANISER.id
    assert str(row.id) == body["id"]
    stored = json.loads(row.proposed_value)
    assert _as_moment(stored["ends_at"]) == event.ends_at + timedelta(days=1)


@pytest.mark.story("19.1", ac=1)
@pytest.mark.parametrize(
    ("field", "proposed"),
    [
        ("expected_attendance", 150),
        ("venue_requirements", [{"name": "Breakout", "capacity": 30, "layout_code": "CLASSROOM"}]),
        ("equipment", [{"equipment_type_code": "WIRELESS_MIC", "quantity": 4}]),
    ],
)
def test_each_requestable_field_can_be_raised(organiser_client, db: Session, field, proposed):
    event = _planning_event(db)

    response = _raise(organiser_client, event.id, field, proposed)

    assert response.status_code == 201, response.text
    assert response.json()["field"] == field
    [row] = _change_requests(db, event.id)
    assert row.field_name == field


@pytest.mark.story("19.1", ac=1)
def test_raising_a_change_notifies_the_assigned_coordinator(organiser_client, db: Session):
    event = _planning_event(db)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 201, response.text
    [notification] = _notifications(db, event.id, "EVENT_CHANGE_REQUESTED")
    assert notification.recipient_id == Users.COORDINATOR.id
    assert notification.related_entity_type == "event_change_request"
    assert str(notification.related_entity_id) == response.json()["id"]


@pytest.mark.story("19.1", ac=1)
def test_notification_goes_to_the_coordinator_assigned_now(client, db: Session):
    """Regression for stories 5.2 and 5.6: Events.APPROVED is Omar's Planning event, assigned to
    Chloe. Once the Lead hands it to Carl, a change request must reach Carl."""
    client.login(Users.LEAD)
    handed_over = client.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )
    assert handed_over.status_code == 200, handed_over.text
    client.logout()
    client.login(Users.ORGANISER_2)

    response = _raise(client, Events.APPROVED, "expected_attendance", 360)

    assert response.status_code == 201, response.text
    [notification] = _notifications(db, Events.APPROVED, "EVENT_CHANGE_REQUESTED")
    assert notification.recipient_id == Users.COORDINATOR_2.id


@pytest.mark.story("19.1", ac=1)
def test_assigned_coordinator_lists_pending_change_requests(login_as, db: Session):
    event = _planning_event(db)
    request_id = _insert_change_request(db, event.id)

    response = login_as(Users.COORDINATOR).get(f"/events/{event.id}/change-requests")

    assert response.status_code == 200, response.text
    [listed] = response.json()
    assert listed["id"] == str(request_id)
    assert listed["status"] == "PENDING"
    assert listed["field"] == "expected_attendance"


@pytest.mark.story("19.1", ac=1)
@pytest.mark.parametrize(
    ("viewer", "expected_status"),
    [(Users.COORDINATOR_2, 403), (Users.ORGANISER_2, 404)],
    ids=["unassigned-coordinator", "another-organiser"],
)
def test_only_organiser_and_assigned_coordinator_list_change_requests(
    login_as, db: Session, viewer, expected_status
):
    event = _planning_event(db)
    _insert_change_request(db, event.id)

    response = login_as(viewer).get(f"/events/{event.id}/change-requests")

    assert response.status_code == expected_status, response.text
    assert response.json()["detail"] != "Not Found"


# --- AC2: point of contact, applied directly and logged --------------------------------------
@pytest.mark.story("19.1", ac=2)
def test_organiser_updates_point_of_contact_directly(organiser_client, db: Session):
    event = _planning_event(db)

    response = organiser_client.patch(
        f"/events/{event.id}/point-of-contact",
        json={"contact_email": "events@acme.example", "contact_phone": "+65 6999 0000"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["contact_email"] == "events@acme.example"
    assert body["contact_phone"] == "+65 6999 0000"
    db.refresh(event)
    assert event.contact_email == "events@acme.example"
    assert event.contact_phone == "+65 6999 0000"
    assert _change_requests(db, event.id) == []


@pytest.mark.story("19.1", ac=2)
def test_point_of_contact_update_is_logged_with_old_and_new_values(organiser_client, db: Session):
    event = _planning_event(db)

    response = organiser_client.patch(
        f"/events/{event.id}/point-of-contact",
        json={"contact_email": "events@acme.example", "contact_phone": "+65 6999 0000"},
    )

    assert response.status_code == 200, response.text
    [entry] = db.execute(
        text(
            "SELECT actor_id, details FROM audit_log"
            " WHERE action = 'EVENT_CONTACT_UPDATED' AND entity_id = :e"
        ),
        {"e": event.id},
    ).all()
    assert entry.actor_id == Users.ORGANISER.id
    assert entry.details == {
        "contact_email": {"from": _CURRENT_EMAIL, "to": "events@acme.example"},
        "contact_phone": {"from": _CURRENT_PHONE, "to": "+65 6999 0000"},
    }


@pytest.mark.story("19.1", ac=2)
def test_point_of_contact_can_be_updated_once_confirmed(organiser_client, db: Session):
    event = _planning_event(db, status=EventStatus.CONFIRMED)

    response = organiser_client.patch(
        f"/events/{event.id}/point-of-contact", json={"contact_phone": "+65 6999 0000"}
    )

    assert response.status_code == 200, response.text
    db.refresh(event)
    assert event.contact_phone == "+65 6999 0000"


@pytest.mark.story("19.1", ac=2)
@pytest.mark.parametrize(
    "status",
    [
        EventStatus.DRAFT,
        EventStatus.UNDER_REVIEW,
        EventStatus.CLARIFICATION_REQUESTED,
        EventStatus.COMPLETED,
        EventStatus.CANCELLED,
        EventStatus.REJECTED,
    ],
)
def test_point_of_contact_update_refused_outside_planning_and_confirmed(
    organiser_client, db: Session, status
):
    event = _planning_event(db, status=status)

    response = organiser_client.patch(
        f"/events/{event.id}/point-of-contact", json={"contact_phone": "+65 6999 0000"}
    )

    assert response.status_code == 409, response.text
    db.refresh(event)
    assert event.contact_phone == _CURRENT_PHONE


@pytest.mark.story("19.1", ac=2)
def test_unchanged_point_of_contact_writes_no_history(organiser_client, db: Session):
    event = _planning_event(db)

    response = organiser_client.patch(
        f"/events/{event.id}/point-of-contact",
        json={"contact_email": _CURRENT_EMAIL, "contact_phone": _CURRENT_PHONE},
    )

    assert response.status_code == 200, response.text
    logged = db.execute(
        text(
            "SELECT count(*) FROM audit_log"
            " WHERE action = 'EVENT_CONTACT_UPDATED' AND entity_id = :e"
        ),
        {"e": event.id},
    ).scalar()
    assert logged == 0


@pytest.mark.story("19.1", ac=2)
@pytest.mark.parametrize(
    ("user", "expected_status"),
    [(Users.COORDINATOR, 403), (Users.ORGANISER_2, 404)],
    ids=["assigned-coordinator", "another-organiser"],
)
def test_only_owning_organiser_updates_point_of_contact(
    login_as, db: Session, user, expected_status
):
    event = _planning_event(db)

    response = login_as(user).patch(
        f"/events/{event.id}/point-of-contact", json={"contact_phone": "+65 6999 0000"}
    )

    assert response.status_code == expected_status, response.text
    assert response.json()["detail"] != "Not Found"
    db.refresh(event)
    assert event.contact_phone == _CURRENT_PHONE


@pytest.mark.story("19.1", ac=2)
def test_general_edit_still_refused_on_planning_event(organiser_client, db: Session):
    """Regression for story 7.2 AC5: the new contact endpoint must not reopen the organiser's
    general edit once the event is approved."""
    event = _planning_event(db)

    response = organiser_client.patch(
        f"/events/{event.id}", json={"contact_email": "events@acme.example"}
    )

    assert response.status_code == 409, response.text
    db.refresh(event)
    assert event.contact_email == _CURRENT_EMAIL


# --- AC3: validated and saved, the event left unchanged ---------------------------------------
@pytest.mark.story("19.1", ac=3)
def test_raising_a_change_leaves_the_event_bookings_and_holds_unchanged(
    organiser_client, db: Session
):
    event = _planning_event(db)
    make_venue_requirement(db, event.id, name="Main hall", capacity=100)
    _add_equipment_line(db, event.id, "WIRELESS_MIC", 2)
    make_booking(
        db,
        event_id=event.id,
        venue_id=make_venue(db, capacity=200).id,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
    )
    make_equipment_hold(
        db,
        type_code="WIRELESS_MIC",
        quantity=2,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        event_id=event.id,
    )

    def snapshot() -> dict:
        def rows(sql: str) -> list:
            return [tuple(row) for row in db.execute(text(sql), {"e": event.id})]

        return {
            "event": rows(
                "SELECT starts_at, ends_at, expected_attendance, status, updated_at"
                " FROM events WHERE id = :e"
            ),
            "requirements": rows(
                "SELECT id, name, capacity, layout_code, starts_at, ends_at"
                " FROM venue_requirements WHERE event_id = :e ORDER BY id"
            ),
            "equipment": rows(
                "SELECT id, equipment_type_id, quantity FROM event_equipment_requests"
                " WHERE event_id = :e ORDER BY id"
            ),
            "bookings": rows(
                "SELECT id, venue_id, status, starts_at, ends_at FROM venue_bookings"
                " WHERE event_id = :e ORDER BY id"
            ),
            "holds": rows(
                "SELECT id, quantity, status, starts_at, ends_at FROM equipment_reservations"
                " WHERE event_id = :e ORDER BY id"
            ),
        }

    before = snapshot()

    responses = [
        _raise(organiser_client, event.id, "schedule", _moved_a_day(event)),
        _raise(organiser_client, event.id, "expected_attendance", 150),
        _raise(
            organiser_client, event.id, "venue_requirements", [{"name": "Hall", "capacity": 80}]
        ),
        _raise(
            organiser_client,
            event.id,
            "equipment",
            [{"equipment_type_code": "WIRELESS_MIC", "quantity": 4}],
        ),
    ]

    assert [r.status_code for r in responses] == [201, 201, 201, 201], [r.text for r in responses]
    db.expire_all()
    assert snapshot() == before


@pytest.mark.story("19.1", ac=3)
def test_refused_change_request_saves_nothing(organiser_client, db: Session):
    event = _planning_event(db)

    response = _raise(organiser_client, event.id, "expected_attendance", 0)

    assert response.status_code == 422, response.text
    assert _change_requests(db, event.id) == []
    assert _notifications(db, event.id, "EVENT_CHANGE_REQUESTED") == []


# --- AC4: boundary --------------------------------------------------------------------------
@pytest.mark.story("19.1", ac=4)
@pytest.mark.parametrize("reason", [None, "", "   "], ids=["missing", "empty", "whitespace"])
def test_reason_is_mandatory(organiser_client, db: Session, reason):
    event = _planning_event(db)

    response = _raise(organiser_client, event.id, "expected_attendance", 150, reason=reason)

    assert response.status_code == 422, response.text
    assert _change_requests(db, event.id) == []


def _in_the_past(event: Event) -> dict:
    start = future_datetime(days=-1)
    return _schedule(start, start + timedelta(hours=2))


def _more_than_two_years_ahead(event: Event) -> dict:
    start = future_datetime(days=2 * 366 + 30)
    return _schedule(start, start + timedelta(hours=2))


def _end_not_after_start(event: Event) -> dict:
    return _schedule(event.starts_at, event.starts_at)


def _longer_than_fourteen_days(event: Event) -> dict:
    return _schedule(event.starts_at, event.starts_at + timedelta(days=14, hours=1))


@pytest.mark.story("19.1", ac=4)
@pytest.mark.parametrize(
    "proposal",
    [_in_the_past, _more_than_two_years_ahead, _end_not_after_start, _longer_than_fourteen_days],
    ids=["in-the-past", "over-two-years-ahead", "end-not-after-start", "over-fourteen-days"],
)
def test_proposed_schedule_follows_creation_rules(organiser_client, db: Session, proposal):
    event = _planning_event(db)

    response = _raise(organiser_client, event.id, "schedule", proposal(event))

    assert response.status_code == 422, response.text
    assert _change_requests(db, event.id) == []


@pytest.mark.story("19.1", ac=4)
def test_proposed_schedule_at_the_limits_is_accepted(organiser_client, db: Session):
    event = _planning_event(db)
    proposed = _schedule(event.starts_at, event.starts_at + timedelta(days=14))

    response = _raise(organiser_client, event.id, "schedule", proposed)

    assert response.status_code == 201, response.text


@pytest.mark.story("19.1", ac=4)
@pytest.mark.parametrize("value", [0, -1, 1.5, "abc", "150"])
def test_proposed_attendance_must_be_a_positive_whole_number(organiser_client, db: Session, value):
    event = _planning_event(db)

    response = _raise(organiser_client, event.id, "expected_attendance", value)

    assert response.status_code == 422, response.text


@pytest.mark.story("19.1", ac=4)
@pytest.mark.story("19.1", ac=16)
@pytest.mark.parametrize(("proposed", "expected_status"), [(79, 422), (80, 201)])
def test_proposed_attendance_leaves_room_for_every_venue_requirement(
    organiser_client, db: Session, proposed, expected_status
):
    """2.7 AC6, checked when the request is raised, not only when it is approved: a requirement
    may need room for exactly the expected attendance, never more."""
    event = _planning_event(db)
    make_venue_requirement(db, event.id, name="Main hall", capacity=80)

    response = _raise(organiser_client, event.id, "expected_attendance", proposed)

    assert response.status_code == expected_status, response.text
    assert len(_change_requests(db, event.id)) == (1 if expected_status == 201 else 0)
    if expected_status == 422:
        assert response.json()["detail"] == _ATTENDANCE_BELOW_REFUSAL.format(
            minimum=80, requirement="Main hall"
        )


@pytest.mark.story("19.1", ac=16)
def test_the_refusal_names_the_requirement_needing_the_most_people(organiser_client, db: Session):
    """Fix f19.1.2: the minimum is the most people any requirement needs, not the first one found
    over the new attendance - Hall comes first but Breakout sets the minimum."""
    event = _planning_event(db, expected_attendance=200)
    make_venue_requirement(db, event.id, position=0, name="Hall", capacity=100)
    make_venue_requirement(db, event.id, position=1, name="Breakout", capacity=150)

    response = _raise(organiser_client, event.id, "expected_attendance", 90)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _ATTENDANCE_BELOW_REFUSAL.format(
        minimum=150, requirement="Breakout"
    )


@pytest.mark.story("19.1", ac=16)
def test_two_requirements_needing_the_most_people_name_the_first(organiser_client, db: Session):
    event = _planning_event(db, expected_attendance=200)
    make_venue_requirement(db, event.id, position=0, name="Hall", capacity=150)
    make_venue_requirement(db, event.id, position=1, name="Breakout", capacity=150)

    response = _raise(organiser_client, event.id, "expected_attendance", 90)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _ATTENDANCE_BELOW_REFUSAL.format(
        minimum=150, requirement="Hall"
    )


@pytest.mark.story("19.1", ac=16)
def test_an_unnamed_limiting_requirement_is_named_by_its_position(organiser_client, db: Session):
    """2.7's own rule names a requirement without a name by where it sits on the form."""
    event = _planning_event(db, expected_attendance=200)
    make_venue_requirement(db, event.id, position=0, name="Hall", capacity=50)
    make_venue_requirement(db, event.id, position=1, name=None, capacity=151)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _ATTENDANCE_BELOW_REFUSAL.format(
        minimum=151, requirement="Venue requirement 2"
    )


# --- AC15 (fix f19.1.2, CL-172): raised beside a venue requirements change that makes room -----


def _requirement_body(requirement_id: uuid.UUID, *, name: str, capacity: int, event: Event):
    """One venue requirement over the whole event, as the change form sends it."""
    return {
        "id": str(requirement_id),
        "name": name,
        "capacity": capacity,
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat(),
        "layout_code": None,
        "facilities": [],
        "notes": None,
    }


def _ask_for_requirements(client, event: Event, *requirements: dict) -> None:
    response = _raise(client, event.id, "venue_requirements", list(requirements))
    assert response.status_code == 201, response.text


@pytest.mark.story("19.1", ac=15)
@pytest.mark.parametrize(("hall", "expected_status"), [(100, 201), (120, 201), (121, 422)])
def test_attendance_is_taken_beside_a_requirements_change_that_makes_room(
    organiser_client, db: Session, hall, expected_status
):
    """The pending venue requirements change brings the hall to or below the new attendance, so
    both wait together; one person over and it is refused, naming the hall as it would be."""
    event = _planning_event(db, expected_attendance=200)
    hall_id = make_venue_requirement(db, event.id, name="Hall", capacity=150)
    _ask_for_requirements(
        organiser_client, event, _requirement_body(hall_id, name="Hall", capacity=hall, event=event)
    )

    response = _raise(organiser_client, event.id, "expected_attendance", 120)

    assert response.status_code == expected_status, response.text
    if expected_status == 201:
        assert {row.field_name for row in _change_requests(db, event.id)} == {
            "venue_requirements",
            "expected_attendance",
        }
        assert all(row.status == "PENDING" for row in _change_requests(db, event.id))
    else:
        assert response.json()["detail"] == _ATTENDANCE_BELOW_REFUSAL.format(
            minimum=121, requirement="Hall"
        )


@pytest.mark.story("19.1", ac=15)
def test_a_requirements_change_lowering_only_some_requirements_is_not_enough(
    organiser_client, db: Session
):
    """The change lowers the hall but keeps the breakout room at 150, so 100 is still refused,
    and the breakout room is named."""
    event = _planning_event(db, expected_attendance=200)
    hall_id = make_venue_requirement(db, event.id, position=0, name="Hall", capacity=150)
    breakout_id = make_venue_requirement(db, event.id, position=1, name="Breakout", capacity=150)
    _ask_for_requirements(
        organiser_client,
        event,
        _requirement_body(hall_id, name="Hall", capacity=80, event=event),
        _requirement_body(breakout_id, name="Breakout", capacity=150, event=event),
    )

    response = _raise(organiser_client, event.id, "expected_attendance", 100)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _ATTENDANCE_BELOW_REFUSAL.format(
        minimum=150, requirement="Breakout"
    )


@pytest.mark.story("19.1", ac=15)
def test_an_out_of_date_requirements_change_does_not_count(organiser_client, db: Session):
    """19.2 AC7: the requirements changed after the change to them was raised, so it can only be
    rejected, and the attendance is judged on the requirements as they stand."""
    event = _planning_event(db, expected_attendance=200)
    hall_id = make_venue_requirement(db, event.id, name="Hall", capacity=150)
    _ask_for_requirements(
        organiser_client, event, _requirement_body(hall_id, name="Hall", capacity=100, event=event)
    )
    db.execute(text("UPDATE venue_requirements SET capacity = 160 WHERE id = :r"), {"r": hall_id})
    db.expire_all()

    response = _raise(organiser_client, event.id, "expected_attendance", 100)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _ATTENDANCE_BELOW_REFUSAL.format(
        minimum=160, requirement="Hall"
    )


@pytest.mark.story("19.1", ac=15)
@pytest.mark.parametrize("status", ["WITHDRAWN", "REJECTED"])
def test_a_requirements_change_no_longer_waiting_does_not_count(
    organiser_client, db: Session, status
):
    event = _planning_event(db, expected_attendance=200)
    hall_id = make_venue_requirement(db, event.id, name="Hall", capacity=150)
    _ask_for_requirements(
        organiser_client, event, _requirement_body(hall_id, name="Hall", capacity=100, event=event)
    )
    db.execute(
        text("UPDATE event_change_requests SET status = :s WHERE event_id = :e"),
        {"s": status, "e": event.id},
    )
    db.expire_all()

    response = _raise(organiser_client, event.id, "expected_attendance", 100)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _ATTENDANCE_BELOW_REFUSAL.format(
        minimum=150, requirement="Hall"
    )


def _over_attendance(event: Event) -> list:
    return [{"name": "Hall", "capacity": 101}]


def _outside_event_times(event: Event) -> list:
    return [
        {
            "name": "Hall",
            "capacity": 50,
            "starts_at": (event.starts_at - timedelta(hours=1)).isoformat(),
            "ends_at": event.ends_at.isoformat(),
        }
    ]


def _duplicate_names(event: Event) -> list:
    return [{"name": "Hall", "capacity": 50}, {"name": " hall ", "capacity": 20}]


def _unknown_layout(event: Event) -> list:
    return [{"name": "Hall", "capacity": 50, "layout_code": "NOT_A_LAYOUT"}]


def _missing_name(event: Event) -> list:
    return [{"capacity": 50}]


def _missing_capacity(event: Event) -> list:
    return [{"name": "Hall"}]


@pytest.mark.story("19.1", ac=4)
@pytest.mark.parametrize(
    "proposal",
    [
        _over_attendance,
        _outside_event_times,
        _duplicate_names,
        _unknown_layout,
        _missing_name,
        _missing_capacity,
    ],
    ids=[
        "over-attendance",
        "outside-event-times",
        "duplicate-names",
        "unknown-layout",
        "missing-name",
        "missing-capacity",
    ],
)
def test_proposed_venue_requirements_follow_creation_rules(organiser_client, db: Session, proposal):
    """Judged against the event as it stands (100 people, its own times)."""
    event = _planning_event(db)

    response = _raise(organiser_client, event.id, "venue_requirements", proposal(event))

    assert response.status_code == 422, response.text
    assert _change_requests(db, event.id) == []


@pytest.mark.story("19.1", ac=4)
@pytest.mark.parametrize(
    "proposed",
    [
        [{"equipment_type_code": "NOT_A_TYPE", "quantity": 1}],
        [{"equipment_type_code": "WIRELESS_MIC", "quantity": 0}],
        [
            {"equipment_type_code": "WIRELESS_MIC", "quantity": 1},
            {"equipment_type_code": "WIRELESS_MIC", "quantity": 2},
        ],
    ],
    ids=["unknown-type", "zero-quantity", "duplicate-type"],
)
def test_proposed_equipment_follows_creation_rules(organiser_client, db: Session, proposed):
    event = _planning_event(db)

    response = _raise(organiser_client, event.id, "equipment", proposed)

    assert response.status_code == 422, response.text
    assert _change_requests(db, event.id) == []


@pytest.mark.story("19.1", ac=4)
@pytest.mark.parametrize(
    "body",
    [
        {"contact_email": "not-an-email"},
        {"contact_email": ""},
        {"contact_phone": "1234567"},
        {"contact_phone": "1234567890123456"},
    ],
    ids=["bad-email", "blank-email", "phone-7-digits", "phone-16-digits"],
)
def test_point_of_contact_follows_creation_rules(organiser_client, db: Session, body):
    event = _planning_event(db)

    response = organiser_client.patch(f"/events/{event.id}/point-of-contact", json=body)

    assert response.status_code == 422, response.text
    db.refresh(event)
    assert (event.contact_email, event.contact_phone) == (_CURRENT_EMAIL, _CURRENT_PHONE)


@pytest.mark.story("19.1", ac=4)
@pytest.mark.parametrize(
    "field", ["schedule", "expected_attendance", "venue_requirements", "equipment"]
)
def test_value_identical_to_current_is_refused(organiser_client, db: Session, field):
    event = _planning_event(db)
    make_venue_requirement(
        db,
        event.id,
        name="Main hall",
        capacity=50,
        layout_code="THEATRE",
        starts_at=event.starts_at,
        ends_at=event.ends_at,
    )
    _add_equipment_line(db, event.id, "WIRELESS_MIC", 2)
    current = {
        "schedule": _schedule(event.starts_at, event.ends_at),
        "expected_attendance": event.expected_attendance,
        "venue_requirements": [
            {
                "name": "Main hall",
                "capacity": 50,
                "layout_code": "THEATRE",
                "starts_at": event.starts_at.isoformat(),
                "ends_at": event.ends_at.isoformat(),
            }
        ],
        "equipment": [{"equipment_type_code": "WIRELESS_MIC", "quantity": 2}],
    }

    response = _raise(organiser_client, event.id, field, current[field])

    assert response.status_code == 422, response.text
    assert _change_requests(db, event.id) == []


@pytest.mark.story("19.1", ac=4)
@pytest.mark.parametrize("field", ["name", "status", "venue", "contact_email"])
def test_unknown_field_is_refused(organiser_client, db: Session, field):
    event = _planning_event(db)

    response = _raise(organiser_client, event.id, field, "anything")

    assert response.status_code == 422, response.text
    assert _change_requests(db, event.id) == []


@pytest.mark.story("19.1", ac=4)
@pytest.mark.parametrize(
    ("field", "proposed"),
    [
        (
            "equipment",
            [
                {"equipment_type_code": "WIRELESS_MIC", "quantity": 1},
                {"equipment_type_code": "WIRELESS_MIC", "quantity": 2},
            ],
        ),
        ("expected_attendance", 0),
        ("venue_requirements", [{"name": "Hall", "capacity": 0}]),
    ],
    ids=["duplicate-type", "zero-attendance", "zero-people"],
)
def test_a_refused_value_reports_only_its_own_problem(
    organiser_client, db: Session, field, proposed
):
    """Review of PR #94: the body is judged only as the field it names, so a refused value comes
    back as one problem located under that field, not one per kind of change request."""
    event = _planning_event(db)

    response = _raise(organiser_client, event.id, field, proposed)

    assert response.status_code == 422, response.text
    [problem] = response.json()["detail"]
    assert problem["loc"][:2] == ["body", field]


# --- AC5 / AC6 / AC12: one pending request per field, and none before approval or once closed -
@pytest.mark.story("19.1", ac=6)
def test_second_pending_request_for_the_same_field_is_refused(organiser_client, db: Session):
    event = _planning_event(db)
    first = _raise(organiser_client, event.id, "expected_attendance", 150)

    second = _raise(organiser_client, event.id, "expected_attendance", 180)

    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    [row] = _change_requests(db, event.id)
    assert json.loads(row.proposed_value) == 150


@pytest.mark.story("19.1", ac=5)
def test_pending_requests_on_different_fields_are_allowed(organiser_client, db: Session):
    event = _planning_event(db)

    attendance = _raise(organiser_client, event.id, "expected_attendance", 150)
    schedule = _raise(organiser_client, event.id, "schedule", _moved_a_day(event))

    assert attendance.status_code == 201, attendance.text
    assert schedule.status_code == 201, schedule.text
    assert len(_change_requests(db, event.id)) == 2


@pytest.mark.story("19.1", ac=6)
def test_database_refuses_two_pending_requests_for_one_field(db: Session):
    """The backstop for two submits racing past each other: the database itself refuses the
    second pending row for the same event and field."""
    event = _planning_event(db)
    _insert_change_request(db, event.id, field="expected_attendance")

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            _insert_change_request(db, event.id, field="expected_attendance")


@pytest.mark.story("19.1", ac=5)
@pytest.mark.story("19.1", ac=12)
@pytest.mark.parametrize(
    "status",
    [EventStatus.DRAFT, EventStatus.UNDER_REVIEW, EventStatus.CLARIFICATION_REQUESTED],
)
def test_change_request_refused_before_approval(organiser_client, db: Session, status):
    event = _planning_event(db, status=status)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 409, response.text
    assert _change_requests(db, event.id) == []


@pytest.mark.story("19.1", ac=12)
@pytest.mark.parametrize(
    "status", [EventStatus.COMPLETED, EventStatus.CANCELLED, EventStatus.REJECTED]
)
def test_change_request_refused_once_closed(organiser_client, db: Session, status):
    """AC12: a completed, cancelled or rejected event takes no change requests, and the refusal
    names its status in words. (A Confirmed one does since fix f19.1.1, AC11.)"""
    event = _planning_event(db, status=status)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == _CLOSED_REFUSAL.format(status=status.lower())
    assert _change_requests(db, event.id) == []


# --- AC7: permission --------------------------------------------------------------------------
@pytest.mark.story("19.1", ac=7)
def test_signed_out_cannot_raise_a_change_request(client, db: Session):
    event = _planning_event(db)

    response = _raise(client, event.id, "expected_attendance", 150)

    assert response.status_code == 401, response.text
    assert _change_requests(db, event.id) == []


@pytest.mark.story("19.1", ac=7)
def test_coordinator_cannot_raise_a_change_request(coordinator_client, db: Session):
    """Chloe is the assigned coordinator, and still may not raise one for the organiser."""
    event = _planning_event(db)

    response = _raise(coordinator_client, event.id, "expected_attendance", 150)

    assert response.status_code == 403, response.text
    assert _change_requests(db, event.id) == []


@pytest.mark.story("19.1", ac=7)
@pytest.mark.parametrize("target", ["someone-elses-event", "unknown-event"])
def test_organiser_cannot_raise_a_change_on_another_organisers_event(login_as, db: Session, target):
    event = _planning_event(db)
    event_id = event.id if target == "someone-elses-event" else uuid.uuid4()

    response = _raise(login_as(Users.ORGANISER_2), event_id, "expected_attendance", 150)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == _EVENT_NOT_FOUND
    assert _change_requests(db, event.id) == []


# --- AC8 / AC13: conflict -------------------------------------------------------------------
@pytest.mark.story("19.1", ac=8)
@pytest.mark.story("19.1", ac=13)
@pytest.mark.parametrize("new_status", [EventStatus.CANCELLED, EventStatus.COMPLETED])
def test_raise_refused_when_event_cancelled_or_completed_meanwhile(
    organiser_client, db: Session, new_status
):
    """AC8/AC13: the event was cancelled or completed while Olivia wrote the request, so submitting
    it is refused. (Becoming Confirmed meanwhile no longer refuses it: AC11.)"""
    event = _planning_event(db)
    opened = organiser_client.get(f"/events/{event.id}")
    assert opened.json()["status"] == EventStatus.PLANNING
    _set_status(db, event.id, new_status)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 409, response.text
    assert _change_requests(db, event.id) == []
    assert _notifications(db, event.id, "EVENT_CHANGE_REQUESTED") == []


@pytest.mark.story("19.1", ac=8)
@pytest.mark.story("19.1", ac=13)
def test_a_request_waits_for_a_cancellation_landing_at_the_same_time(engine):
    """Real concurrent transactions, committed and cleaned up after, as 5.6's cancellation race.
    The event is being cancelled - that transaction holds its row - while Olivia submits a change.
    Her request waits for the row, then sees the event Cancelled and is refused, rather than
    leaving a pending request and a notice on a cancelled event (review of #125, probe P1)."""
    with Session(engine) as session:
        event_id = _planning_event(session, name="Change Request Race").id
        session.commit()
    outcome: dict[str, str] = {}

    def submit() -> None:
        with Session(engine) as session:
            olivia = session.get(User, Users.ORGANISER.id)
            proposal = AttendanceChangeIn(field="expected_attendance", proposed=150, reason=_REASON)
            try:
                change_requests_service.raise_change_request(
                    session, event_id, proposal, actor=olivia
                )
                outcome["result"] = "raised"
            except change_requests_service.ChangeRequestsClosed:
                session.rollback()
                outcome["result"] = "refused"

    try:
        with Session(engine) as cancelling:
            cancelling.execute(select(Event.id).where(Event.id == event_id).with_for_update())
            olivia_submitting = threading.Thread(target=submit)
            olivia_submitting.start()
            # Long enough for the request to have read the event, or to be waiting for it.
            olivia_submitting.join(timeout=0.5)
            cancelling.execute(
                text("UPDATE events SET status = 'CANCELLED' WHERE id = :e"), {"e": event_id}
            )
            cancelling.commit()
        olivia_submitting.join(timeout=30)

        assert outcome == {"result": "refused"}
        with Session(engine) as session:
            assert (
                session.scalars(
                    select(EventChangeRequest).where(EventChangeRequest.event_id == event_id)
                ).all()
                == []
            )
            assert (
                session.scalars(select(Notification).where(Notification.event_id == event_id)).all()
                == []
            )
    finally:
        with Session(engine) as session:
            session.execute(delete(Notification).where(Notification.event_id == event_id))
            session.execute(delete(AuditLog).where(AuditLog.entity_id == event_id))
            session.execute(
                delete(EventChangeRequest).where(EventChangeRequest.event_id == event_id)
            )
            session.execute(delete(Event).where(Event.id == event_id))
            session.commit()


# --- AC9: withdraw a pending request ---------------------------------------------------------
def _withdraw(client, event_id: uuid.UUID, request_id: uuid.UUID | str):
    return client.post(f"/events/{event_id}/change-requests/{request_id}/withdraw")


@pytest.mark.story("19.1", ac=9)
def test_organiser_withdraws_a_pending_change_request(organiser_client, db: Session):
    event = _planning_event(db)
    request_id = _insert_change_request(db, event.id)

    response = _withdraw(organiser_client, event.id, request_id)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "WITHDRAWN"
    [row] = _change_requests(db, event.id)
    assert row.id == request_id
    assert row.status == "WITHDRAWN"


@pytest.mark.story("19.1", ac=9)
def test_withdrawing_notifies_the_assigned_coordinator(organiser_client, db: Session):
    event = _planning_event(db)
    request_id = _insert_change_request(db, event.id)

    response = _withdraw(organiser_client, event.id, request_id)

    assert response.status_code == 200, response.text
    [notification] = _notifications(db, event.id, "EVENT_CHANGE_REQUEST_WITHDRAWN")
    assert notification.recipient_id == Users.COORDINATOR.id
    assert notification.related_entity_id == request_id


@pytest.mark.story("19.1", ac=9)
def test_withdrawn_request_frees_the_field(organiser_client, db: Session):
    event = _planning_event(db)
    first = _raise(organiser_client, event.id, "expected_attendance", 150)
    assert first.status_code == 201, first.text
    withdrawn = _withdraw(organiser_client, event.id, first.json()["id"])

    again = _raise(organiser_client, event.id, "expected_attendance", 180)

    assert withdrawn.status_code == 200, withdrawn.text
    assert again.status_code == 201, again.text
    assert [row.status for row in _change_requests(db, event.id)] == ["WITHDRAWN", "PENDING"]


# --- AC10: only Pending, only the owning organiser --------------------------------------------
@pytest.mark.story("19.1", ac=10)
@pytest.mark.parametrize("status", ["APPROVED", "REJECTED", "WITHDRAWN"])
def test_only_a_pending_request_can_be_withdrawn(organiser_client, db: Session, status):
    event = _planning_event(db)
    request_id = _insert_change_request(db, event.id, status=status)

    response = _withdraw(organiser_client, event.id, request_id)

    assert response.status_code == 409, response.text
    [row] = _change_requests(db, event.id)
    assert row.status == status


@pytest.mark.story("19.1", ac=10)
def test_withdraw_refused_when_decided_meanwhile(organiser_client, db: Session):
    event = _planning_event(db)
    raised = _raise(organiser_client, event.id, "expected_attendance", 150)
    assert raised.status_code == 201, raised.text
    listed = organiser_client.get(f"/events/{event.id}/change-requests")
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["status"] == "PENDING"
    db.execute(
        text("UPDATE event_change_requests SET status = 'APPROVED' WHERE id = :id"),
        {"id": raised.json()["id"]},
    )
    db.expire_all()

    response = _withdraw(organiser_client, event.id, raised.json()["id"])

    assert response.status_code == 409, response.text
    [row] = _change_requests(db, event.id)
    assert row.status == "APPROVED"


@pytest.mark.story("19.1", ac=10)
@pytest.mark.parametrize(
    ("case", "expected_status"),
    [("assigned-coordinator", 403), ("another-organiser", 404), ("request-of-another-event", 404)],
)
def test_only_the_owning_organiser_withdraws(login_as, db: Session, case, expected_status):
    event = _planning_event(db)
    request_id = _insert_change_request(db, event.id)
    other_event = _planning_event(db)
    user = {
        "assigned-coordinator": Users.COORDINATOR,
        "another-organiser": Users.ORGANISER_2,
        "request-of-another-event": Users.ORGANISER,
    }[case]
    event_id = other_event.id if case == "request-of-another-event" else event.id

    response = _withdraw(login_as(user), event_id, request_id)

    assert response.status_code == expected_status, response.text
    expected_detail = {
        "another-organiser": _EVENT_NOT_FOUND,
        "request-of-another-event": _CHANGE_REQUEST_NOT_FOUND,
    }.get(case)
    if expected_detail is not None:
        assert response.json()["detail"] == expected_detail
    [row] = _change_requests(db, event.id)
    assert row.status == "PENDING"


# --- AC1: a request raised while the event changes hands -------------------------------------
_LOCK_WAIT_SECONDS = 20


def _wait_until_waiting(engine: Engine, pids: dict[str, int], name: str) -> None:
    """Block until the connection ``name`` stands waiting on a row lock another holds."""
    deadline = time.monotonic() + _LOCK_WAIT_SECONDS
    while time.monotonic() < deadline:
        if name in pids:
            with engine.connect() as watcher:
                waiting_on = watcher.execute(
                    text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                    {"pid": pids[name]},
                ).scalar()
            if waiting_on == "Lock":
                return
        time.sleep(0.05)
    raise AssertionError(f"{name} never waited on a lock")


@pytest.mark.story("19.1", ac=1)
def test_a_request_waiting_on_a_handover_tells_the_new_coordinator(engine, monkeypatch):
    """The Lead hands the event from Chloe to Carl and is held part-way, the event's row locked;
    Olivia's request waits for it. Once the handover commits, the request must tell Carl, who is
    assigned now (story 5.6), and not be left reading the coordinator as it stood before it
    waited."""
    with Session(engine) as session:
        event = _planning_event(session)
        session.add(
            EventCoordinatorAssignment(
                event_id=event.id,
                coordinator_id=Users.COORDINATOR.id,
                assigned_by_id=Users.LEAD.id,
            )
        )
        session.commit()
        event_id = event.id
    pids: dict[str, int] = {}
    holding, go = threading.Event(), threading.Event()
    real_current_assignment = coordination_service.current_assignment

    def held_current_assignment(db: Session, event_id: uuid.UUID):
        holding.set()
        go.wait(_LOCK_WAIT_SECONDS)
        return real_current_assignment(db, event_id)

    monkeypatch.setattr(coordination_service, "current_assignment", held_current_assignment)

    def hand_over() -> None:
        with Session(engine) as session:
            coordination_service.assign_coordinator(
                session,
                event_id,
                AssignCoordinatorIn(
                    coordinator_id=Users.COORDINATOR_2.id,
                    expected_coordinator_id=Users.COORDINATOR.id,
                ),
                actor=session.get(User, Users.LEAD.id),
            )

    def raise_request() -> None:
        holding.wait(_LOCK_WAIT_SECONDS)
        with Session(engine) as session:
            pids["raise"] = session.connection().exec_driver_sql("SELECT pg_backend_pid()").scalar()
            change_requests_service.raise_change_request(
                session,
                event_id,
                AttendanceChangeIn(field="expected_attendance", proposed=150, reason=_REASON),
                actor=session.get(User, Users.ORGANISER.id),
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            handing_over = pool.submit(hand_over)
            raising = pool.submit(raise_request)
            _wait_until_waiting(engine, pids, "raise")
            go.set()
            handing_over.result(timeout=_LOCK_WAIT_SECONDS)
            raising.result(timeout=_LOCK_WAIT_SECONDS)

        with Session(engine) as session:
            told = [
                row.recipient_id
                for row in _notifications(session, event_id, "EVENT_CHANGE_REQUESTED")
            ]
            assert told == [Users.COORDINATOR_2.id]
    finally:
        go.set()
        with Session(engine) as session:
            session.execute(
                text(
                    "DELETE FROM audit_log WHERE entity_id = :e OR entity_id IN"
                    " (SELECT id FROM event_change_requests WHERE event_id = :e)"
                ),
                {"e": event_id},
            )
            session.execute(text("DELETE FROM events WHERE id = :e"), {"e": event_id})
            session.commit()


# --- AC11-AC13 (fix f19.1.1): change requests on Confirmed events -----------------------------
def _confirmed_event(db: Session, **overrides) -> Event:
    """Olivia's event once Confirmed (Q39): the same as ``_planning_event``, a step further on."""
    return _planning_event(db, status=EventStatus.CONFIRMED, **overrides)


def _event_status(db: Session, event_id: uuid.UUID) -> str:
    return db.execute(text("SELECT status FROM events WHERE id = :e"), {"e": event_id}).scalar_one()


def _ended_event(db: Session, *, status: str) -> Event:
    """Olivia's event that ended yesterday, its status left as it was: nothing marks an ended event
    Completed yet (Q57)."""
    starts_at = datetime.now(UTC) - timedelta(days=1, hours=8)
    return _planning_event(
        db, status=status, starts_at=starts_at, ends_at=starts_at + timedelta(hours=8)
    )


@pytest.mark.story("19.1", ac=11)
def test_organiser_raises_a_change_on_a_confirmed_event(organiser_client, db: Session):
    """AC11: as on a Planning event - saved as pending, the coordinator told, and nothing on the
    event changes yet: it stays Confirmed, with its attendance as it was."""
    event = _confirmed_event(db)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "PENDING"
    [row] = _change_requests(db, event.id)
    assert row.status == "PENDING"
    assert row.requested_by_id == Users.ORGANISER.id
    [notification] = _notifications(db, event.id, "EVENT_CHANGE_REQUESTED")
    assert notification.recipient_id == Users.COORDINATOR.id
    assert _event_status(db, event.id) == EventStatus.CONFIRMED
    assert db.get(Event, event.id).expected_attendance == 100


@pytest.mark.story("19.1", ac=11)
@pytest.mark.parametrize(
    ("field", "proposal"),
    [
        ("schedule", _moved_a_day),
        ("expected_attendance", lambda _event: 150),
        (
            "venue_requirements",
            lambda _event: [{"name": "Breakout", "capacity": 30, "layout_code": "CLASSROOM"}],
        ),
        ("equipment", lambda _event: [{"equipment_type_code": "WIRELESS_MIC", "quantity": 4}]),
    ],
    ids=["schedule", "expected_attendance", "venue_requirements", "equipment"],
)
def test_each_field_can_be_raised_on_a_confirmed_event(
    organiser_client, db: Session, field, proposal
):
    """AC11: every field AC1 offers is taken on a Confirmed event too. Each proposal is built from
    the event, since the schedule's is its own dates a day later."""
    event = _confirmed_event(db)

    response = _raise(organiser_client, event.id, field, proposal(event))

    assert response.status_code == 201, response.text
    [row] = _change_requests(db, event.id)
    assert row.field_name == field


@pytest.mark.story("19.1", ac=11)
def test_a_change_raised_on_a_confirmed_event_returns_it_to_planning_when_approved(
    login_as, db: Session
):
    """AC11's second sentence, through 19.2: Olivia asks, Chloe approves, and the event is back
    in Planning with the new attendance, to go through every check again (19.2 AC8)."""
    event = _confirmed_event(db)
    raised = _raise(login_as(Users.ORGANISER), event.id, "expected_attendance", 150)
    assert raised.status_code == 201, raised.text

    approved = approve_as_seen(login_as(Users.COORDINATOR), event.id, raised.json()["id"])

    assert approved.status_code == 200, approved.text
    db.expire_all()
    assert _event_status(db, event.id) == EventStatus.PLANNING
    assert db.get(Event, event.id).expected_attendance == 150


@pytest.mark.story("19.1", ac=11)
def test_a_request_written_while_the_event_became_confirmed_is_taken(organiser_client, db: Session):
    """AC11 replaces AC8's refusal: Olivia opened her Planning event, and it was confirmed while
    she wrote the request. It is taken, against the event as it now stands."""
    event = _planning_event(db)
    opened = organiser_client.get(f"/events/{event.id}")
    assert opened.json()["status"] == EventStatus.PLANNING
    _set_status(db, event.id, EventStatus.CONFIRMED)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 201, response.text
    assert [row.status for row in _change_requests(db, event.id)] == ["PENDING"]


@pytest.mark.story("19.1", ac=11)
@pytest.mark.story("19.1", ac=6)
def test_one_pending_request_per_field_holds_once_confirmed(organiser_client, db: Session):
    """AC11 with AC6: on a Confirmed event, a request raised while it was in Planning, still
    pending, keeps its field - a second one is refused - while another field can still be asked
    for."""
    event = _planning_event(db)
    first = _raise(organiser_client, event.id, "expected_attendance", 150)
    assert first.status_code == 201, first.text
    _set_status(db, event.id, EventStatus.CONFIRMED)

    second = _raise(organiser_client, event.id, "expected_attendance", 180)
    other_field = _raise(organiser_client, event.id, "schedule", _moved_a_day(event))

    assert second.status_code == 409, second.text
    assert "already waiting for a decision" in second.json()["detail"]
    assert other_field.status_code == 201, other_field.text
    assert len(_change_requests(db, event.id)) == 2


@pytest.mark.story("19.1", ac=11)
@pytest.mark.story("19.1", ac=4)
@pytest.mark.parametrize("case", ["the same value as now", "a date in the past"])
def test_the_rules_for_a_change_still_apply_once_confirmed(organiser_client, db: Session, case):
    """AC4 on a Confirmed event: a value identical to the current one, and a date the creation
    rules refuse, are refused (422) as on a Planning event - not for the event's status."""
    event = _confirmed_event(db)
    field, proposed = {
        "the same value as now": ("expected_attendance", 100),
        "a date in the past": ("schedule", _in_the_past(event)),
    }[case]

    response = _raise(organiser_client, event.id, field, proposed)

    assert response.status_code == 422, response.text
    assert _change_requests(db, event.id) == []


@pytest.mark.story("19.1", ac=11)
@pytest.mark.story("19.1", ac=7)
@pytest.mark.parametrize(
    ("who", "expected_status"),
    [("the coordinator", 403), ("another organiser", 404), ("nobody signed in", 401)],
)
def test_only_the_owning_organiser_raises_on_a_confirmed_event(
    login_as, client, db: Session, who, expected_status
):
    """AC7 on a Confirmed event: Chloe, its coordinator, may not raise one for Olivia; Omar cannot
    see it; signing in is required."""
    event = _confirmed_event(db)
    actor = {
        "the coordinator": lambda: login_as(Users.COORDINATOR),
        "another organiser": lambda: login_as(Users.ORGANISER_2),
        "nobody signed in": lambda: client,
    }[who]()

    response = _raise(actor, event.id, "expected_attendance", 150)

    assert response.status_code == expected_status, response.text
    assert _change_requests(db, event.id) == []


@pytest.mark.story("19.1", ac=12)
def test_change_request_refused_while_awaiting_the_safety_check(organiser_client, db: Session):
    """AC12: whether change requests are offered while the event awaits its safety check waits on
    Q20, so until then the API refuses them, in a sentence of its own - the event is not past
    taking them, as "no longer" would say (CL-149)."""
    event = _planning_event(db, status=EventStatus.AWAITING_SAFETY_CHECK)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == _AWAITING_SAFETY_CHECK_REFUSAL
    assert _change_requests(db, event.id) == []


# --- AC12: change requests close 24 hours before set-up (team decision on the review of #125) -
def _confirmed_event_starting_in(
    db: Session, hours: float, *, status: str = EventStatus.CONFIRMED
) -> Event:
    """Olivia's event, Confirmed unless ``status`` says otherwise, starting ``hours`` from now."""
    starts_at = datetime.now(UTC) + timedelta(hours=hours)
    return _planning_event(
        db, status=status, starts_at=starts_at, ends_at=starts_at + timedelta(hours=4)
    )


def _book_with_setup(db: Session, event: Event, *, setup_minutes: int, status: str = "APPROVED"):
    """A booking for the whole event, its venue held ``setup_minutes`` before it starts. An expired
    one carries the hold expiry it lapsed at (``ck_venue_bookings_hold_expiry``)."""
    return make_booking(
        db,
        venue_id=make_venue(db).id,
        event_id=event.id,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        setup_minutes=setup_minutes,
        status=status,
        hold_expires_at=datetime.now(UTC) - timedelta(hours=1) if status == "EXPIRED" else None,
    )


@pytest.mark.story("19.1", ac=12)
@pytest.mark.parametrize("status", [EventStatus.PLANNING, EventStatus.CONFIRMED])
def test_change_requests_close_24_hours_before_the_event(organiser_client, db: Session, status):
    """With no venue booked, set-up is the event's start: 23 hours ahead is inside the last 24, so
    the request is refused, saying when they closed. Nothing is saved or sent."""
    event = _confirmed_event_starting_in(db, 23, status=status)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == _CLOSED_BEFORE_SETUP_REFUSAL
    assert _change_requests(db, event.id) == []
    assert _notifications(db, event.id, "EVENT_CHANGE_REQUESTED") == []


@pytest.mark.story("19.1", ac=11)
@pytest.mark.story("19.1", ac=12)
def test_a_change_is_taken_more_than_24_hours_before_the_event(organiser_client, db: Session):
    """The boundary's other side: 25 hours ahead, with nothing booked, is still open."""
    event = _confirmed_event_starting_in(db, 25)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 201, response.text


@pytest.mark.story("19.1", ac=12)
@pytest.mark.parametrize(
    ("setup_hours", "expected_status"),
    [(7, 409), (4, 201)],
    ids=["set-up starts in 23 hours", "set-up starts in 26 hours"],
)
def test_change_requests_close_24_hours_before_set_up(
    organiser_client, db: Session, setup_hours, expected_status
):
    """It is set-up that counts, not the start: the event starts in 30 hours, and its venue is held
    from ``setup_hours`` before that."""
    event = _confirmed_event_starting_in(db, 30)
    _book_with_setup(db, event, setup_minutes=setup_hours * 60)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == expected_status, response.text


@pytest.mark.story("19.1", ac=12)
@pytest.mark.parametrize(
    ("booking_status", "expected_status"),
    [
        ("PENDING", 409),
        ("APPROVED", 409),
        ("REJECTED", 201),
        ("WITHDRAWN", 201),
        ("CANCELLED", 201),
        ("EXPIRED", 201),
    ],
)
def test_only_a_booking_that_holds_a_venue_sets_the_set_up_time(
    organiser_client, db: Session, booking_status, expected_status
):
    """A pending or approved booking holds its venue, set-up included (12.1 AC3), so its set-up
    counts. A booking that no longer holds one - rejected, withdrawn, cancelled or expired - does
    not, and the event's own start, 30 hours ahead, leaves requests open."""
    event = _confirmed_event_starting_in(db, 30)
    _book_with_setup(db, event, setup_minutes=7 * 60, status=booking_status)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == expected_status, response.text


@pytest.mark.story("19.1", ac=12)
@pytest.mark.parametrize("status", [EventStatus.PLANNING, EventStatus.CONFIRMED])
def test_change_request_refused_once_the_event_has_ended(organiser_client, db: Session, status):
    """AC12's "not for Completed events", while nothing marks an ended event Completed (Q57): an
    event that is over is long past its set-up, so it takes none, whatever its status still says.
    The seed's Autumn Book Swap, Confirmed and over since 3 Oct, is such an event."""
    event = _ended_event(db, status=status)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == _CLOSED_BEFORE_SETUP_REFUSAL
    assert _change_requests(db, event.id) == []
    assert _event_status(db, event.id) == status


@pytest.mark.story("19.1", ac=12)
def test_the_event_start_counts_when_set_up_begins_after_it(organiser_client, db: Session):
    """Set-up time is the earlier of the first set-up and the event's start: a booking for the
    event's last hours, held from 30 hours ahead, doesn't keep requests open for an event that
    starts in 23."""
    event = _confirmed_event_starting_in(db, 23)
    make_booking(
        db,
        venue_id=make_venue(db).id,
        event_id=event.id,
        starts_at=event.starts_at + timedelta(hours=8),
        ends_at=event.starts_at + timedelta(hours=10),
        setup_minutes=60,
        status="APPROVED",
    )

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == _CLOSED_BEFORE_SETUP_REFUSAL


@pytest.mark.story("19.1", ac=12)
def test_the_earliest_set_up_of_several_bookings_counts(organiser_client, db: Session):
    """Two venues for an event starting in 30 hours: one held from 26 hours ahead, the other from
    23. It is the first set-up that counts, so requests are closed."""
    event = _confirmed_event_starting_in(db, 30)
    _book_with_setup(db, event, setup_minutes=4 * 60)
    _book_with_setup(db, event, setup_minutes=7 * 60)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 409, response.text


class _ClockAt:
    """Stands in for the service's ``datetime`` with ``now`` fixed at ``moment``, so the cut-off
    itself can be tested, not only the hours either side of it."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self, tz=None) -> datetime:
        return self._moment


@pytest.mark.story("19.1", ac=12)
def test_change_requests_are_closed_at_exactly_24_hours_before_set_up(
    organiser_client, db: Session, monkeypatch
):
    """The boundary itself: at the very moment 24 hours before set-up, requests are already closed
    - "until 24 hours before", not "until and including"."""
    event = _confirmed_event_starting_in(db, 48)
    monkeypatch.setattr(
        change_requests_service, "datetime", _ClockAt(event.starts_at - timedelta(hours=24))
    )

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == _CLOSED_BEFORE_SETUP_REFUSAL


@pytest.mark.story("19.1", ac=12)
def test_change_requests_are_open_a_second_before_the_cut_off(
    organiser_client, db: Session, monkeypatch
):
    event = _confirmed_event_starting_in(db, 48)
    monkeypatch.setattr(
        change_requests_service,
        "datetime",
        _ClockAt(event.starts_at - timedelta(hours=24, seconds=1)),
    )

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 201, response.text


def _window(client, event_id: uuid.UUID):
    return client.get(f"/events/{event_id}/change-request-window")


@pytest.mark.story("19.1", ac=12)
def test_the_organiser_is_told_when_change_requests_close(organiser_client, db: Session):
    """So the page can stop offering them (AC12's "not offered"): the moment they close, 24 hours
    before set-up, and whether that is still ahead."""
    event = _confirmed_event_starting_in(db, 30)
    booking = _book_with_setup(db, event, setup_minutes=2 * 60)

    response = _window(organiser_client, event.id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert _as_moment(body["closes_at"]) == booking.held_from - timedelta(hours=24)
    assert body["is_open"] is True


@pytest.mark.story("19.1", ac=12)
def test_the_window_says_closed_inside_the_last_24_hours(organiser_client, db: Session):
    event = _confirmed_event_starting_in(db, 23)

    response = _window(organiser_client, event.id)

    assert response.status_code == 200, response.text
    assert _as_moment(response.json()["closes_at"]) == event.starts_at - timedelta(hours=24)
    assert response.json()["is_open"] is False


@pytest.mark.story("19.1", ac=12)
@pytest.mark.parametrize(
    ("who", "expected_status"),
    [
        ("the assigned coordinator", 200),
        ("another coordinator", 403),
        ("another organiser", 404),
        ("nobody signed in", 401),
    ],
)
def test_who_may_read_when_change_requests_close(
    login_as, client, db: Session, who, expected_status
):
    """As the change requests themselves (AC1): the organiser and the assigned coordinator."""
    event = _confirmed_event_starting_in(db, 30)
    actor = {
        "the assigned coordinator": lambda: login_as(Users.COORDINATOR),
        "another coordinator": lambda: login_as(Users.COORDINATOR_2),
        "another organiser": lambda: login_as(Users.ORGANISER_2),
        "nobody signed in": lambda: client,
    }[who]()

    response = _window(actor, event.id)

    assert response.status_code == expected_status, response.text
