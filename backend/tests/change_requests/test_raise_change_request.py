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
    offered; once the event is Confirmed, they are not offered and the API refuses them.
AC6 The server refuses a duplicate pending request for the same field.

Permission
AC7 Only the owning organiser can raise change requests. Coordinators cannot raise them.

Conflict
AC8 If the event is cancelled or becomes Confirmed while the request is being written,
    submitting it is refused.

Withdrawal (added by the PO at Checkpoint 1)
AC9 The organiser can withdraw their own pending change request. It is kept as Withdrawn, the
    assigned coordinator is notified, and the field is free for a new request.
AC10 Only a Pending request can be withdrawn, including one decided while the organiser was
    confirming; only the owning organiser can withdraw.

Decisions recorded at Checkpoint 1 that these tests rely on:
* Date and time is one field, ``schedule``, holding ``starts_at`` and ``ends_at`` together.
* "Venue" is requested through ``venue_requirements``; organisers cannot pick a venue.
* Each proposed value is checked on its own creation rules against the event as it stands;
  effects on other fields, bookings and holds are story 19.3's impact view.
* The point of contact may be updated while Planning or Confirmed, and is logged to
  ``audit_log`` as ``EVENT_CONTACT_UPDATED`` (7.4's change history is not built yet).

Excluded, with reason:
* What the form offers (AC5's "not offered") and the reason field blocking submit (AC4's
  client-side half) are UI behaviour, proven in tests/e2e/change-requests.spec.ts.
* AC8's true race needs two database connections; these tests share the test's one connection,
  so the other transaction is simulated by changing the status just before submitting. The
  row lock that makes the real race safe is the same one story 2.7 AC12 relies on.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.events.models import Event, EventStatus
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
    """Regression for story 5.2: Events.APPROVED is Omar's Planning event, assigned to Chloe.
    Once Chloe hands it to Carl, a change request must reach Carl."""
    client.login(Users.COORDINATOR)
    handed_over = client.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
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


# --- AC5 / AC6: one pending request per field, only while Planning --------------------------
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
@pytest.mark.parametrize(
    "status",
    [EventStatus.DRAFT, EventStatus.UNDER_REVIEW, EventStatus.CLARIFICATION_REQUESTED],
)
def test_change_request_refused_before_approval(organiser_client, db: Session, status):
    event = _planning_event(db, status=status)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 409, response.text
    assert _change_requests(db, event.id) == []


@pytest.mark.story("19.1", ac=5)
@pytest.mark.parametrize(
    "status",
    [
        EventStatus.CONFIRMED,
        EventStatus.COMPLETED,
        EventStatus.CANCELLED,
        EventStatus.REJECTED,
    ],
)
def test_change_request_refused_once_confirmed_or_closed(organiser_client, db: Session, status):
    event = _planning_event(db, status=status)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 409, response.text
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


# --- AC8: conflict -----------------------------------------------------------------------------
@pytest.mark.story("19.1", ac=8)
@pytest.mark.parametrize("new_status", [EventStatus.CONFIRMED, EventStatus.CANCELLED])
def test_raise_refused_when_event_confirmed_or_cancelled_meanwhile(
    organiser_client, db: Session, new_status
):
    event = _planning_event(db)
    opened = organiser_client.get(f"/events/{event.id}")
    assert opened.json()["status"] == EventStatus.PLANNING
    _set_status(db, event.id, new_status)

    response = _raise(organiser_client, event.id, "expected_attendance", 150)

    assert response.status_code == 409, response.text
    assert _change_requests(db, event.id) == []
    assert _notifications(db, event.id, "EVENT_CHANGE_REQUESTED") == []


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
