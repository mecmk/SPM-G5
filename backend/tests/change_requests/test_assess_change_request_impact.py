"""Story 19.3 - be: assess a change request's impact before deciding it.

AC1 Each pending change request shows the venue bookings, equipment and registrations it would
    affect, and why. Attendance above what the booked venues hold is flagged as a warning only.
    If nothing is affected, that is stated.
AC2 For each affected arrangement, the assessment says what approval (19.2) will do to it and who
    acts on it. No new flag or notification is added.
AC3 The assessment is worked out on the server from current records when the request is opened,
    and changes nothing.
AC4 New times that only touch another booking are not flagged; an overlap of one minute is, with
    setup and teardown counted. Attendance equal to capacity is not flagged.
AC5 Venue unavailability, a conflicting booking or times outside opening hours are flagged.
    Equipment the change can no longer supply is flagged with the shortfall (16.1).
AC6 Only the assigned coordinator sees the assessment.
AC7 If the assessment changes after the request is opened, approving shows the new result before
    anything is applied.

Decisions agreed 19 Oct 2026 (CL-152 to CL-154), beyond the ACs' wording:
* Bookings are reported as 19.2 would treat them: cancelled when f7.2.4's fit rule says the change
  no longer fits them (judged on what the booking was made for), otherwise left alone. An event
  with several bookings has each judged on its own.
* A venue's capacity is a warning only and never cancels a booking. An attendance change is
  checked against the venues in use at each moment, each venue counted once in its booked layout
  (the layout's capacity where the venue records one, as story 11.1 judges it). Attendance one
  above it is flagged.
* Registrations are counted, never named. Lowering the attendance below the count, and changing
  the dates, are flagged; nothing is written to a registration and no attendee is told.
* For a booking the change cancels, the same venue is checked for the period a replacement would
  need, as a booking request is (12.1): the held period, setup and teardown included, for other
  bookings and unavailability, and the booking's own times for opening hours (f12.1.2).
* Equipment uses the calculation 19.2 holds equipment by, so the assessment predicts it exactly:
  ``EquipmentChangePlan``, ``take_units`` and the status each item ends in are shared with the
  approval. Each shortfall gives required, available and short.
* No new notification, flag or workflow: after approval, cancelled bookings and returned equipment
  reach Venue Staff, Technical Support and the coordinator the way 19.2 already sends them.
* Only approving re-runs the assessment, under the event's lock. Approving sends back the
  fingerprint of the assessment the coordinator saw; any change to it refuses the approval, with
  nothing applied, until the new one is reviewed. Only the assigned coordinator may see the
  assessment, enforced on the backend.

Fix f19.2.1 (CL-176, replacing CL-141 (2)):
* The event's attendance outgrowing what a booking was made for - an additional venue, or a
  requirement with no number of its own - cancels nothing, so that booking is kept and counts
  towards what the venues hold. A requirement's own number still does.

Excluded, with reason:
* How the assessment is shown, and the approval dialog showing an updated assessment before the
  coordinator approves again, are UI behaviour, proven in tests/e2e/change-request-impact.spec.ts.
* Two transactions truly at once need two connections; as in 19.2's tests, "someone else changed
  it meanwhile" is simulated by changing the records between reading the assessment and
  approving. The event's row lock and the equipment types' locks serialise the real race.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, object_session

from app.change_requests.models import EventChangeRequest
from app.events.models import Event, EventStatus
from tests.support.factories import (
    future_datetime,
    make_booking,
    make_equipment_hold,
    make_equipment_item,
    make_equipment_out_of_service,
    make_equipment_type,
    make_event,
    make_unavailability,
    make_user,
    make_venue,
    make_venue_requirement,
)
from tests.support.replacement import add_pending_replacement, make_scenario
from tests.support.seed import Users

_EVENT_NOT_FOUND = "Event not found."
_CHANGE_REQUEST_NOT_FOUND = "Change request not found."
_NOT_ASSIGNED = "Only the coordinator assigned to this event can view the impact of its changes."
_IMPACT_CHANGED = (
    "The impact of this change has changed since you opened it. Review the updated impact, then "
    "approve again."
)
# AC2: what the approval does to an item it removes, and to one it sends back for the new dates.
_KEPT_AS_CANCELLED = (
    "Removed: its hold is released, and it is kept as Cancelled for the record. Technical Support "
    "are told it was withdrawn."
)
_BACK_WITH_TECHNICAL_SUPPORT = (
    "Held again for the new dates, and back with Technical Support as Pending, to decide for the "
    "new dates."
)
# AC2: what the approval does to a booking it keeps, which is listed only for a warning.
_KEPT_WITH_WARNING = (
    "Stays as it is: a warning never cancels a booking, and Venue Staff are not told of the "
    "change. Check with them that the venue still suits it, or reject the change."
)


# --- helpers ---------------------------------------------------------------------------------


def _planning_event(db: Session, **overrides) -> Event:
    """Olivia's event in Planning, assigned to Chloe, dated safely in the future, for 100 people."""
    starts_at = overrides.pop("starts_at", future_datetime(days=60))
    return make_event(
        db,
        status=overrides.pop("status", EventStatus.PLANNING),
        starts_at=starts_at,
        ends_at=overrides.pop("ends_at", starts_at + timedelta(hours=8)),
        expected_attendance=overrides.pop("expected_attendance", 100),
        assigned_coordinator_id=overrides.pop("assigned_coordinator_id", Users.COORDINATOR.id),
        **overrides,
    )


def _requirement(db: Session, event: Event, *, capacity: int | None, **overrides) -> uuid.UUID:
    """A venue requirement over the whole event, for ``capacity`` people (None: the event's
    attendance)."""
    return make_venue_requirement(
        db,
        event.id,
        position=overrides.pop("position", 0),
        name=overrides.pop("name", "Main hall"),
        capacity=capacity,
        starts_at=overrides.pop("starts_at", event.starts_at),
        ends_at=overrides.pop("ends_at", event.ends_at),
        **overrides,
    )


def _book(db: Session, event: Event, *, people: int, requirement_id=None, **overrides):
    """An approved booking for ``event``'s requirement (or an additional venue), at a fresh venue
    unless one is given, over the event's period unless told otherwise."""
    venue = overrides.pop("venue", None) or make_venue(
        db, capacity=overrides.pop("capacity", 500), name=f"Room {uuid.uuid4().hex[:6]}"
    )
    return make_booking(
        db,
        event_id=event.id,
        venue_id=venue.id,
        starts_at=overrides.pop("starts_at", event.starts_at),
        ends_at=overrides.pop("ends_at", event.ends_at),
        expected_attendance=people,
        status=overrides.pop("status", "APPROVED"),
        venue_requirement_id=requirement_id,
        hold_expires_at=overrides.pop("hold_expires_at", event.starts_at - timedelta(days=1)),
        **overrides,
    )


def _register(db: Session, event: Event, count: int) -> None:
    """``count`` attendees registered for ``event`` (story 18.1), each a fresh attendee."""
    for _ in range(count):
        attendee = make_user(db, role="ATTENDEE")
        db.execute(
            text(
                "INSERT INTO event_registrations (event_id, attendee_id, status)"
                " VALUES (:e, :a, 'REGISTERED')"
            ),
            {"e": event.id, "a": attendee.id},
        )


def _raise(login_as, db: Session, event: Event, field: str, proposed) -> EventChangeRequest:
    """Olivia raises a change through 19.1's own endpoint, so the stored values are exactly what
    19.1 writes."""
    response = login_as(Users.ORGANISER).post(
        f"/events/{event.id}/change-requests",
        json={"field": field, "proposed": proposed, "reason": "Plans have changed."},
    )
    assert response.status_code == 201, response.text
    return db.get(EventChangeRequest, uuid.UUID(response.json()["id"]))


def _schedule(starts_at: datetime, ends_at: datetime) -> dict:
    return {"starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat()}


def _grow(login_as, db: Session, event: Event, requirement_id, capacity: int):
    """Olivia asks for the Main hall requirement to need room for ``capacity`` people: past what
    its booking was made for, a change 19.2 cancels the booking for (f7.2.4)."""
    body = _requirement_body(requirement_id, name="Main hall", capacity=capacity, event=event)
    return _raise(login_as, db, event, "venue_requirements", [body])


def _requirement_body(requirement_id, *, name: str, capacity: int, event: Event) -> dict:
    """One venue requirement over the whole event, as 19.1's change form sends it."""
    return {
        "id": None if requirement_id is None else str(requirement_id),
        "name": name,
        "capacity": capacity,
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat(),
        "layout_code": None,
        "facilities": [],
        "notes": None,
    }


def _equipment_body(item_id, equipment_type, quantity: int) -> dict:
    return {
        "id": None if item_id is None else str(item_id),
        "equipment_type_code": equipment_type.code,
        "quantity": quantity,
        "technical_notes": None,
    }


def _impact_url(request) -> str:
    return f"/events/{request.event_id}/change-requests/{request.id}/impact"


def _impact(login_as, request, user=Users.COORDINATOR):
    response = login_as(user).get(_impact_url(request))
    assert response.status_code == 200, response.text
    return response.json()


def _approve(login_as, request, fingerprint: str | None):
    """Approve ``request`` as Chloe with the assessment she saw. The test's rows are committed
    first - to the test's own transaction, still rolled back at the end - so a refused approval's
    rollback cannot undo them as well (as 19.2's tests do)."""
    object_session(request).commit()
    body = {} if fingerprint is None else {"assessment_fingerprint": fingerprint}
    return login_as(Users.COORDINATOR).post(
        f"/events/{request.event_id}/change-requests/{request.id}/approve", json=body
    )


def _at(event: Event, fraction: float) -> datetime:
    """The moment ``fraction`` of the way through ``event``."""
    return event.starts_at + (event.ends_at - event.starts_at) * fraction


def _short_periods(shortfall: dict) -> list[tuple]:
    """Each flagged period as (start, end, capacity, shortfall, venue ids), times parsed."""
    return [
        (
            datetime.fromisoformat(period["starts_at"]),
            datetime.fromisoformat(period["ends_at"]),
            period["capacity"],
            period["shortfall"],
            [venue["venue_id"] for venue in period["venues"]],
        )
        for period in shortfall["periods"]
    ]


def _bookings_by_id(impact: dict) -> dict[str, dict]:
    return {row["booking_id"]: row for row in impact["venue_bookings"]}


def _booking_status(db: Session, booking_id) -> str:
    return db.execute(
        text("SELECT status FROM venue_bookings WHERE id = :b"), {"b": booking_id}
    ).scalar_one()


def _item_status(db: Session, item_id) -> str | None:
    return db.execute(
        text("SELECT status FROM event_equipment_requests WHERE id = :i"), {"i": item_id}
    ).scalar_one_or_none()


def _request_status(db: Session, request_id) -> str:
    return db.execute(
        text("SELECT status FROM event_change_requests WHERE id = :id"), {"id": request_id}
    ).scalar_one()


def _snapshot(db: Session, event: Event) -> dict:
    """Everything an assessment could conceivably write: the event, its bookings, holds,
    registrations, notifications and audit entries."""
    db.expire_all()
    queries = {
        "event": "SELECT starts_at, ends_at, expected_attendance, status FROM events WHERE id = :e",
        "bookings": "SELECT id, status FROM venue_bookings WHERE event_id = :e ORDER BY id",
        "items": "SELECT id, status FROM event_equipment_requests WHERE event_id = :e ORDER BY id",
        "holds": (
            "SELECT id, status, released_quantity FROM equipment_reservations"
            " WHERE event_id = :e ORDER BY id"
        ),
        "registrations": "SELECT id, status FROM event_registrations WHERE event_id = :e",
        "notifications": "SELECT count(*) FROM notifications",
        "audit": "SELECT count(*) FROM audit_log",
    }
    return {name: list(db.execute(text(sql), {"e": event.id})) for name, sql in queries.items()}


# --- AC1: what the change affects, each with why -----------------------------------------------


@pytest.mark.story("19.3", ac=1)
@pytest.mark.parametrize("proposed", [81, 800])
def test_an_attendance_rise_cancels_no_booking(login_as, db: Session, proposed):
    """Fix f19.2.1: one person over, or ten times over: the additional foyer and the side room
    (a requirement with no number of its own) were both booked for the event's 80, and both seat
    1000, so the approval keeps them and nothing is listed; the hall's own 50 is untouched."""
    event = _planning_event(db, expected_attendance=80)
    hall = _book(db, event, people=50, requirement_id=_requirement(db, event, capacity=50))
    side = _requirement(db, event, capacity=None, name="Side room", position=1)
    side_room = _book(db, event, people=80, requirement_id=side, capacity=1000)
    foyer = _book(db, event, people=80, capacity=1000)
    request = _raise(login_as, db, event, "expected_attendance", proposed)

    impact = _impact(login_as, request)
    response = _approve(login_as, request, impact["fingerprint"])

    assert impact["venue_bookings"] == []
    assert impact["capacity_shortfall"] is None
    assert impact["has_impact"] is False
    assert response.status_code == 200, response.text
    for booking in (hall, side_room, foyer):
        assert _booking_status(db, booking.id) == "APPROVED"


@pytest.mark.story("19.3", ac=1)
def test_a_booking_kept_through_an_attendance_rise_keeps_its_capacity_warning(
    login_as, db: Session
):
    """Fix f19.2.1: the foyer was booked for the event's 80 and seats 85, so 90 keeps it - with
    11.1's warning that it holds fewer than the 90 now expected."""
    event = _planning_event(db, expected_attendance=80)
    foyer = _book(db, event, people=80, capacity=85)
    request = _raise(login_as, db, event, "expected_attendance", 90)

    row = _bookings_by_id(_impact(login_as, request))[str(foyer.id)]

    assert row["will_be_cancelled"] is False
    assert row["reasons"] == []
    assert row["capacity_warning"] == {
        "people_needed": 90,
        "venue_capacity": 85,
        "layout_name": None,
    }
    assert row["after_approval"] == _KEPT_WITH_WARNING


@pytest.mark.story("19.3", ac=1)
def test_a_requirement_grown_past_its_booking_lists_it_as_cancelled_and_why(login_as, db: Session):
    """Unchanged by fix f19.2.1: the Main hall requirement's own number going from 80 to 90 is
    past what its booking was made for, so 19.2 cancels it."""
    event = _planning_event(db, expected_attendance=100)
    requirement = _requirement(db, event, capacity=80)
    hall = _book(db, event, people=80, requirement_id=requirement)
    request = _grow(login_as, db, event, requirement, 90)

    impact = _impact(login_as, request)

    row = _bookings_by_id(impact)[str(hall.id)]
    assert row["will_be_cancelled"] is True
    assert row["requirement_name"] == "Main hall"
    assert row["reasons"] == ["It was booked for 80 people; the change needs room for 90."]
    assert row["capacity_warning"] is None
    assert impact["has_impact"] is True


@pytest.mark.story("19.3", ac=1)
def test_the_events_own_cancelled_booking_never_holds_the_venue(login_as, db: Session):
    """The hall was booked for 80, so a requirement grown to 90 cancels it; a replacement needs the
    very period the hall's own booking holds, which the approval frees, so it is not shown as
    held."""
    event = _planning_event(db, expected_attendance=100)
    requirement = _requirement(db, event, capacity=80)
    hall = _book(db, event, people=80, requirement_id=requirement)
    request = _grow(login_as, db, event, requirement, 90)

    row = _bookings_by_id(_impact(login_as, request))[str(hall.id)]

    assert row["will_be_cancelled"] is True
    assert row["needed_starts_at"] is not None
    assert row["held_by"] is None


@pytest.mark.story("19.3", ac=1)
def test_each_of_several_bookings_is_judged_on_its_own(login_as, db: Session):
    event = _planning_event(db)
    hall_requirement = _requirement(db, event, capacity=60, name="Main hall")
    room_requirement = _requirement(db, event, capacity=30, name="Breakout room", position=1)
    hall = _book(db, event, people=60, requirement_id=hall_requirement)
    room = _book(db, event, people=30, requirement_id=room_requirement)
    request = _raise(
        login_as,
        db,
        event,
        "venue_requirements",
        [
            _requirement_body(hall_requirement, name="Main hall", capacity=80, event=event),
            _requirement_body(room_requirement, name="Breakout room", capacity=30, event=event),
        ],
    )

    rows = _bookings_by_id(_impact(login_as, request))

    assert set(rows) == {str(hall.id)}
    assert rows[str(hall.id)]["requirement_name"] == "Main hall"
    assert rows[str(hall.id)]["reasons"] == [
        "It was booked for 60 people; the change needs room for 80."
    ]
    assert room.id  # booked, and left out: the change still fits it


@pytest.mark.story("19.3", ac=1)
def test_removing_a_requirement_cancels_its_booking(login_as, db: Session):
    event = _planning_event(db)
    hall_requirement = _requirement(db, event, capacity=60, name="Main hall")
    room_requirement = _requirement(db, event, capacity=30, name="Breakout room", position=1)
    _book(db, event, people=60, requirement_id=hall_requirement)
    room = _book(db, event, people=30, requirement_id=room_requirement)
    request = _raise(
        login_as,
        db,
        event,
        "venue_requirements",
        [_requirement_body(hall_requirement, name="Main hall", capacity=60, event=event)],
    )

    rows = _bookings_by_id(_impact(login_as, request))

    assert set(rows) == {str(room.id)}
    assert rows[str(room.id)]["reasons"] == [
        "The change removes the venue requirement it was booked for."
    ]


@pytest.mark.story("19.3", ac=1)
def test_a_capacity_warning_is_not_a_cancellation(login_as, db: Session):
    """The hall was booked for 200 people, so 150 still fit what was booked and 19.2 keeps it - but
    the hall seats only 120, so the coordinator is warned."""
    event = _planning_event(db, expected_attendance=200)
    requirement = _requirement(db, event, capacity=100)
    hall = _book(db, event, people=200, requirement_id=requirement, capacity=120)
    request = _raise(
        login_as,
        db,
        event,
        "venue_requirements",
        [_requirement_body(requirement, name="Main hall", capacity=150, event=event)],
    )

    row = _bookings_by_id(_impact(login_as, request))[str(hall.id)]

    assert row["will_be_cancelled"] is False
    assert row["reasons"] == []
    assert row["capacity_warning"] == {
        "people_needed": 150,
        "venue_capacity": 120,
        "layout_name": None,
    }
    assert row["after_approval"] == _KEPT_WITH_WARNING


@pytest.mark.story("19.3", ac=1)
def test_a_cancelled_booking_can_also_carry_a_capacity_warning(login_as, db: Session):
    event = _planning_event(db, expected_attendance=150)
    requirement = _requirement(db, event, capacity=100)
    hall = _book(db, event, people=100, requirement_id=requirement, capacity=120)
    request = _grow(login_as, db, event, requirement, 140)

    row = _bookings_by_id(_impact(login_as, request))[str(hall.id)]

    assert row["will_be_cancelled"] is True
    assert row["capacity_warning"]["venue_capacity"] == 120


@pytest.mark.story("19.3", ac=1)
def test_registrations_are_counted_not_named(login_as, db: Session):
    event = _planning_event(db, expected_attendance=100)
    _register(db, event, 3)
    request = _raise(login_as, db, event, "expected_attendance", 2)

    registrations = _impact(login_as, request)["registrations"]

    assert registrations == {
        "active_count": 3,
        "proposed_attendance": 2,
        "over_by": 1,
        "dates_change": False,
    }


@pytest.mark.story("19.3", ac=1)
def test_registrations_alone_are_an_impact(login_as, db: Session):
    """No booking or equipment is touched, but three registered for an attendance lowered to 2,
    so the page must not also say nothing is affected."""
    event = _planning_event(db, expected_attendance=100)
    _register(db, event, 3)
    request = _raise(login_as, db, event, "expected_attendance", 2)

    impact = _impact(login_as, request)

    assert impact["venue_bookings"] == []
    assert impact["equipment"] == []
    assert impact["has_impact"] is True


@pytest.mark.story("19.3", ac=1)
def test_withdrawn_registrations_are_not_counted(login_as, db: Session):
    event = _planning_event(db, expected_attendance=100)
    _register(db, event, 2)
    db.execute(
        text(
            "UPDATE event_registrations SET status = 'WITHDRAWN', withdrawn_at = now()"
            " WHERE id = (SELECT id FROM event_registrations WHERE event_id = :e LIMIT 1)"
        ),
        {"e": event.id},
    )
    request = _raise(login_as, db, event, "expected_attendance", 1)

    assert _impact(login_as, request)["registrations"] is None


@pytest.mark.story("19.3", ac=1)
def test_an_attendance_still_above_the_registrations_does_not_affect_them(login_as, db: Session):
    event = _planning_event(db, expected_attendance=100)
    _register(db, event, 3)
    request = _raise(login_as, db, event, "expected_attendance", 3)

    assert _impact(login_as, request)["registrations"] is None


@pytest.mark.story("19.3", ac=1)
def test_new_dates_affect_every_registration(login_as, db: Session):
    event = _planning_event(db)
    _register(db, event, 2)
    starts_at = event.starts_at + timedelta(days=7)
    request = _raise(
        login_as, db, event, "schedule", _schedule(starts_at, starts_at + timedelta(hours=8))
    )

    registrations = _impact(login_as, request)["registrations"]

    assert registrations["active_count"] == 2
    assert registrations["dates_change"] is True
    assert registrations["over_by"] == 0


@pytest.mark.story("19.3", ac=1)
def test_nothing_affected_is_said_plainly(login_as, db: Session):
    event = _planning_event(db, expected_attendance=80)
    _book(db, event, people=50, requirement_id=_requirement(db, event, capacity=50))
    request = _raise(login_as, db, event, "expected_attendance", 90)

    impact = _impact(login_as, request)

    assert impact["has_impact"] is False
    assert impact["venue_bookings"] == []
    assert impact["equipment"] == []
    assert impact["registrations"] is None
    assert impact["capacity_shortfall"] is None
    assert impact["refused_because"] is None


@pytest.mark.story("19.3", ac=1)
def test_a_change_the_approval_would_refuse_says_why(login_as, db: Session):
    """A requirement for 60 people was added after the organiser asked for 50: approving would
    leave it needing more room than the attendance (2.7 AC6), which 19.2 refuses, so the
    assessment says so and predicts nothing else."""
    event = _planning_event(db, expected_attendance=100)
    request = _raise(login_as, db, event, "expected_attendance", 50)
    _requirement(db, event, capacity=60)

    impact = _impact(login_as, request)

    assert impact["refused_because"] == (
        "The expected attendance cannot be lower than 60 while Main hall needs room for 60"
        " people. Approve a venue requirements change that lowers it first."
    )
    assert impact["venue_bookings"] == []


@pytest.mark.story("19.3", ac=1)
def test_an_attendance_change_waiting_on_a_requirements_change_says_so(login_as, db: Session):
    """Fix f19.1.2: raised beside a change bringing the hall to 50, the attendance change is
    judged on the hall as it stands until that change is approved, as 19.2 approves it."""
    event = _planning_event(db, expected_attendance=100)
    hall = _requirement(db, event, capacity=60)
    _raise(
        login_as,
        db,
        event,
        "venue_requirements",
        [_requirement_body(hall, name="Main hall", capacity=50, event=event)],
    )
    request = _raise(login_as, db, event, "expected_attendance", 50)

    impact = _impact(login_as, request)

    assert impact["refused_because"] == (
        "The expected attendance cannot be lower than 60 while Main hall needs room for 60"
        " people. Approve a venue requirements change that lowers it first."
    )


@pytest.mark.story("19.3", ac=1)
def test_an_out_of_date_request_says_so(login_as, db: Session):
    event = _planning_event(db, expected_attendance=100)
    request = _raise(login_as, db, event, "expected_attendance", 120)
    db.execute(text("UPDATE events SET expected_attendance = 110 WHERE id = :e"), {"e": event.id})
    db.expire_all()

    impact = _impact(login_as, request)

    assert impact["is_out_of_date"] is True
    assert impact["venue_bookings"] == []


@pytest.mark.story("19.3", ac=1)
def test_an_attendance_beyond_what_the_booked_venues_hold_is_flagged(login_as, db: Session):
    """The Annual Wellness Summit case: its Main venue requirement is for 180, booked at a hall
    seating 250. Raising the attendance to 500 leaves the requirement - and so the booking - as it
    is, but over the hall's whole booking it holds only 250 of the 500 now expected."""
    event = _planning_event(db, expected_attendance=180)
    hall = _book(
        db, event, people=180, requirement_id=_requirement(db, event, capacity=180), capacity=250
    )
    request = _raise(login_as, db, event, "expected_attendance", 500)

    impact = _impact(login_as, request)

    shortfall = impact["capacity_shortfall"]
    assert shortfall["proposed_attendance"] == 500
    assert _short_periods(shortfall) == [
        (event.starts_at, event.ends_at, 250, 250, [str(hall.venue_id)])
    ]
    assert shortfall["periods"][0]["venues"] == [
        {
            "venue_id": str(hall.venue_id),
            "venue_name": hall.venue.name,
            "capacity": 250,
            "layout_name": None,
        }
    ]
    assert impact["venue_bookings"] == []
    assert impact["has_impact"] is True


@pytest.mark.story("19.3", ac=1)
def test_a_pending_replacement_counts_in_place_of_the_booking_it_replaces(login_as, db: Session):
    """Venue Staff closed the original's venue (9.4) and a replacement is pending (12.6): both are
    for the Main hall at the same times, but only one of them will ever hold the people. Each hall
    holds 100, so 150 does not fit."""
    scenario = make_scenario(db)
    replacement = add_pending_replacement(db, scenario)
    request = _raise(login_as, db, scenario.event, "expected_attendance", 150)

    shortfall = _impact(login_as, request)["capacity_shortfall"]

    assert shortfall is not None
    [period] = shortfall["periods"]
    assert [venue["venue_id"] for venue in period["venues"]] == [str(replacement.venue_id)]
    assert (period["capacity"], period["shortfall"]) == (100, 50)


@pytest.mark.story("19.3", ac=4)
@pytest.mark.parametrize(("attendance", "is_flagged"), [(250, False), (251, True)])
def test_an_attendance_equal_to_the_booked_capacity_fits(
    login_as, db: Session, attendance, is_flagged
):
    event = _planning_event(db, expected_attendance=180)
    _book(db, event, people=180, requirement_id=_requirement(db, event, capacity=180), capacity=250)
    request = _raise(login_as, db, event, "expected_attendance", attendance)

    assert (_impact(login_as, request)["capacity_shortfall"] is not None) is is_flagged


@pytest.mark.story("19.3", ac=1)
def test_venues_in_use_at_once_count_together(login_as, db: Session):
    """A 500-seat hall and a 40-seat breakout room, both booked for the whole event, hold the 500
    now expected between them: the room was never meant to hold everyone, so nothing is
    flagged."""
    event = _planning_event(db, expected_attendance=300)
    hall_requirement = _requirement(db, event, capacity=300, name="Main hall")
    room_requirement = _requirement(db, event, capacity=40, name="Breakout room", position=1)
    _book(db, event, people=300, requirement_id=hall_requirement, capacity=500)
    _book(db, event, people=40, requirement_id=room_requirement, capacity=40)
    request = _raise(login_as, db, event, "expected_attendance", 500)

    assert _impact(login_as, request)["capacity_shortfall"] is None


@pytest.mark.story("19.3", ac=1)
def test_venues_used_at_different_times_never_add_up(login_as, db: Session):
    """A 250-seat hall in the morning and a 200-seat theatre in the afternoon add up to 450, but
    never hold anyone at the same time: 400 people do not fit at either time, so both are
    flagged, each with the venue in use then."""
    event = _planning_event(db, expected_attendance=200)
    midpoint = _at(event, 0.5)
    morning = _requirement(db, event, capacity=200, name="Morning", ends_at=midpoint)
    afternoon = _requirement(
        db, event, capacity=200, name="Afternoon", position=1, starts_at=midpoint
    )
    hall = _book(db, event, people=200, requirement_id=morning, capacity=250, ends_at=midpoint)
    theatre = _book(
        db, event, people=200, requirement_id=afternoon, capacity=200, starts_at=midpoint
    )
    request = _raise(login_as, db, event, "expected_attendance", 400)

    shortfall = _impact(login_as, request)["capacity_shortfall"]

    assert _short_periods(shortfall) == [
        (event.starts_at, midpoint, 250, 150, [str(hall.venue_id)]),
        (midpoint, event.ends_at, 200, 200, [str(theatre.venue_id)]),
    ]


@pytest.mark.story("19.3", ac=1)
def test_only_the_times_without_enough_room_are_flagged(login_as, db: Session):
    """A 250-seat hall all day and a 200-seat room in the afternoon: 400 people fit once the room
    opens (450), not before it (250), so only the morning is flagged."""
    event = _planning_event(db, expected_attendance=200)
    midpoint = _at(event, 0.5)
    hall = _book(
        db, event, people=200, requirement_id=_requirement(db, event, capacity=200), capacity=250
    )
    room_requirement = _requirement(
        db, event, capacity=150, name="Afternoon room", position=1, starts_at=midpoint
    )
    _book(db, event, people=150, requirement_id=room_requirement, capacity=200, starts_at=midpoint)
    request = _raise(login_as, db, event, "expected_attendance", 400)

    shortfall = _impact(login_as, request)["capacity_shortfall"]

    assert _short_periods(shortfall) == [
        (event.starts_at, midpoint, 250, 150, [str(hall.venue_id)])
    ]


@pytest.mark.story("19.3", ac=1)
def test_a_time_with_no_venue_booked_is_not_flagged(login_as, db: Session):
    """A morning venue and an afternoon venue, each big enough, with nothing booked over lunch:
    a break needs no room, so nothing is flagged."""
    event = _planning_event(db, expected_attendance=200)
    morning_ends, afternoon_starts = _at(event, 0.25), _at(event, 0.75)
    morning = _requirement(db, event, capacity=200, name="Morning", ends_at=morning_ends)
    afternoon = _requirement(
        db, event, capacity=200, name="Afternoon", position=1, starts_at=afternoon_starts
    )
    _book(db, event, people=200, requirement_id=morning, capacity=500, ends_at=morning_ends)
    _book(db, event, people=200, requirement_id=afternoon, capacity=500, starts_at=afternoon_starts)
    request = _raise(login_as, db, event, "expected_attendance", 400)

    assert _impact(login_as, request)["capacity_shortfall"] is None


@pytest.mark.story("19.3", ac=1)
def test_a_venue_booked_for_two_requirements_counts_once(login_as, db: Session):
    """12.5 AC9: one 250-seat hall serves a morning and an afternoon requirement back to back. It
    holds 250 at every moment, so 450 people are flagged once, over both, with the hall listed
    once."""
    event = _planning_event(db, expected_attendance=200)
    midpoint = _at(event, 0.5)
    hall = make_venue(db, capacity=250, name=f"Hall {uuid.uuid4().hex[:6]}")
    morning = _requirement(db, event, capacity=200, name="Morning", ends_at=midpoint)
    afternoon = _requirement(
        db, event, capacity=200, name="Afternoon", position=1, starts_at=midpoint
    )
    _book(db, event, people=200, requirement_id=morning, venue=hall, ends_at=midpoint)
    _book(db, event, people=200, requirement_id=afternoon, venue=hall, starts_at=midpoint)
    request = _raise(login_as, db, event, "expected_attendance", 450)

    shortfall = _impact(login_as, request)["capacity_shortfall"]

    assert _short_periods(shortfall) == [(event.starts_at, event.ends_at, 250, 200, [str(hall.id)])]


@pytest.mark.story("19.3", ac=1)
def test_a_venue_booked_for_fewer_than_the_new_attendance_still_counts(login_as, db: Session):
    """Fix f19.2.1: the additional foyer was booked for the event's 180, so 500 is past it - but
    the approval keeps it, so its 200 seats count beside the 250-seat hall's: 50 short, not 250."""
    event = _planning_event(db, expected_attendance=180)
    hall = _book(
        db, event, people=180, requirement_id=_requirement(db, event, capacity=100), capacity=250
    )
    foyer = _book(db, event, people=180, capacity=200)
    request = _raise(login_as, db, event, "expected_attendance", 500)

    shortfall = _impact(login_as, request)["capacity_shortfall"]

    [(starts_at, ends_at, capacity, short, venue_ids)] = _short_periods(shortfall)
    assert (starts_at, ends_at, capacity, short) == (event.starts_at, event.ends_at, 450, 50)
    assert sorted(venue_ids) == sorted([str(hall.venue_id), str(foyer.venue_id)])


@pytest.mark.story("19.3", ac=4)
def test_the_booked_layouts_capacity_is_what_a_venue_holds(login_as, db: Session):
    event = _planning_event(db, expected_attendance=100)
    venue = make_venue(db, capacity=300, layouts={"THEATRE": 120})
    requirement = _requirement(db, event, capacity=100, layout_code="THEATRE")
    _book(
        db,
        event,
        people=100,
        requirement_id=requirement,
        venue=venue,
        required_layout_code="THEATRE",
    )
    request = _raise(login_as, db, event, "expected_attendance", 200)

    period = _impact(login_as, request)["capacity_shortfall"]["periods"][0]

    assert period["capacity"] == 120
    assert period["venues"][0]["layout_name"] == "Theatre"


@pytest.mark.story("19.3", ac=1)
def test_only_an_attendance_change_is_judged_against_the_booked_capacity(login_as, db: Session):
    """The event already expects more than its hall seats; moving its dates does not ask about
    capacity at all."""
    event = _planning_event(db, expected_attendance=300)
    hall = _book(
        db, event, people=300, requirement_id=_requirement(db, event, capacity=300), capacity=250
    )
    starts_at = event.starts_at + timedelta(days=7)
    request = _raise(
        login_as, db, event, "schedule", _schedule(starts_at, starts_at + timedelta(hours=8))
    )

    impact = _impact(login_as, request)

    assert impact["capacity_shortfall"] is None
    assert _bookings_by_id(impact)[str(hall.id)]["capacity_warning"] is None


@pytest.mark.story("19.3", ac=1)
def test_no_booking_means_no_capacity_to_judge(login_as, db: Session):
    request = _raise(login_as, db, _planning_event(db), "expected_attendance", 500)

    assert _impact(login_as, request)["capacity_shortfall"] is None


# --- AC2: what happens to each after approval, as 19.2 does it ---------------------------------


@pytest.mark.story("19.3", ac=2)
def test_predicted_cancellations_are_what_the_approval_cancels(login_as, db: Session):
    """New dates a week later: the whole-event hall and the additional foyer no longer cover them;
    a booking already cancelled is not judged at all."""
    event = _planning_event(db)
    hall = _book(db, event, people=100, requirement_id=_requirement(db, event, capacity=100))
    foyer = _book(db, event, people=100)
    old = _book(db, event, people=100, status="CANCELLED")
    starts_at = event.starts_at + timedelta(days=7)
    request = _raise(
        login_as, db, event, "schedule", _schedule(starts_at, starts_at + timedelta(hours=8))
    )

    impact = _impact(login_as, request)
    predicted = {row["booking_id"] for row in impact["venue_bookings"] if row["will_be_cancelled"]}
    response = _approve(login_as, request, impact["fingerprint"])

    assert response.status_code == 200, response.text
    assert predicted == {str(hall.id), str(foyer.id)}
    for booking in (hall, foyer):
        assert _booking_status(db, booking.id) == "CANCELLED"
    assert str(old.id) not in _bookings_by_id(impact)


@pytest.mark.story("19.3", ac=2)
def test_a_cancelled_booking_says_what_happens_next(login_as, db: Session):
    event = _planning_event(db)
    requirement = _requirement(db, event, capacity=80)
    hall = _book(db, event, people=80, requirement_id=requirement)
    request = _grow(login_as, db, event, requirement, 90)

    row = _bookings_by_id(_impact(login_as, request))[str(hall.id)]

    assert row["after_approval"] == (
        "Cancelled when the change is approved, freeing the venue. Venue Staff are told, and need "
        "do nothing; request a replacement from the event page."
    )


@pytest.mark.story("19.3", ac=2)
def test_predicted_equipment_is_what_the_approval_does(login_as, db: Session):
    """Removed after being accepted, kept as Cancelled; lowered and still in stock, held again
    and back to Requested; new and short, flagged Unavailable; unchanged, not listed."""
    event = _planning_event(db)
    accepted = make_equipment_item(
        db, event=event, equipment_type=make_equipment_type(db), quantity=2, status="ACCEPTED"
    )
    lowered_type = make_equipment_type(db, total_quantity=5)
    lowered = make_equipment_item(
        db, event=event, equipment_type=lowered_type, quantity=4, status="PENDING"
    )
    kept_type = make_equipment_type(db)
    kept = make_equipment_item(db, event=event, equipment_type=kept_type, quantity=1)
    short_type = make_equipment_type(db, total_quantity=2)
    request = _raise(
        login_as,
        db,
        event,
        "equipment",
        [
            _equipment_body(lowered.id, lowered_type, 3),
            _equipment_body(kept.id, kept_type, 1),
            _equipment_body(None, short_type, 3),
        ],
    )

    impact = _impact(login_as, request)
    rows = {row["equipment_type_code"]: row for row in impact["equipment"]}
    response = _approve(login_as, request, impact["fingerprint"])

    assert response.status_code == 200, response.text
    assert kept_type.code not in rows
    assert rows[accepted.equipment_type.code]["change"] == "removed"
    assert rows[accepted.equipment_type.code]["status_after"] == _item_status(db, accepted.id)
    assert rows[accepted.equipment_type.code]["after_approval"] == _KEPT_AS_CANCELLED
    assert rows[lowered_type.code]["status_after"] == _item_status(db, lowered.id) == "REQUESTED"
    assert rows[lowered_type.code]["technical_support_told"] is True
    added_status = db.execute(
        text(
            "SELECT i.status FROM event_equipment_requests i JOIN equipment_types t"
            " ON t.id = i.equipment_type_id WHERE i.event_id = :e AND t.code = :c"
        ),
        {"e": event.id, "c": short_type.code},
    ).scalar_one()
    assert rows[short_type.code]["status_after"] == added_status == "UNAVAILABLE"
    assert rows[short_type.code]["shortfall"] == 1


@pytest.mark.story("19.3", ac=2)
def test_new_dates_send_equipment_back_as_the_approval_does(login_as, db: Session):
    """A pending item that fits the new dates goes back to Technical Support; one that does not -
    another event holds the units then - is flagged Unavailable."""
    event = _planning_event(db)
    fits_type = make_equipment_type(db, total_quantity=4)
    fits = make_equipment_item(
        db, event=event, equipment_type=fits_type, quantity=2, status="PENDING"
    )
    short_type = make_equipment_type(db, total_quantity=4)
    short = make_equipment_item(
        db, event=event, equipment_type=short_type, quantity=3, status="ACCEPTED"
    )
    starts_at = event.starts_at + timedelta(days=7)
    ends_at = starts_at + timedelta(hours=8)
    make_equipment_hold(
        db, type_code=short_type.code, quantity=2, starts_at=starts_at, ends_at=ends_at
    )
    request = _raise(login_as, db, event, "schedule", _schedule(starts_at, ends_at))

    impact = _impact(login_as, request)
    rows = {row["item_id"]: row for row in impact["equipment"]}
    response = _approve(login_as, request, impact["fingerprint"])

    assert response.status_code == 200, response.text
    assert rows[str(fits.id)]["change"] == "rechecked"
    assert rows[str(fits.id)]["status_after"] == _item_status(db, fits.id) == "PENDING"
    assert rows[str(short.id)]["status_after"] == _item_status(db, short.id) == "UNAVAILABLE"
    assert rows[str(short.id)]["required"] == 3
    assert rows[str(short.id)]["available"] == 2
    assert rows[str(short.id)]["shortfall"] == 1


@pytest.mark.story("19.3", ac=2)
def test_an_accepted_item_that_still_fits_goes_back_to_technical_support(login_as, db: Session):
    """Technical Support accepted 2 of 4 projectors for the old dates; the new dates have them
    all, but that decision was for the old dates, so the approval sends it back as Pending."""
    event = _planning_event(db)
    projectors = make_equipment_type(db, total_quantity=4)
    item = make_equipment_item(
        db, event=event, equipment_type=projectors, quantity=2, status="ACCEPTED"
    )
    starts_at = event.starts_at + timedelta(days=7)
    request = _raise(
        login_as, db, event, "schedule", _schedule(starts_at, starts_at + timedelta(hours=8))
    )

    impact = _impact(login_as, request)
    row = {row["item_id"]: row for row in impact["equipment"]}[str(item.id)]
    response = _approve(login_as, request, impact["fingerprint"])

    assert response.status_code == 200, response.text
    assert row["status_after"] == _item_status(db, item.id) == "PENDING"
    assert row["after_approval"] == _BACK_WITH_TECHNICAL_SUPPORT


@pytest.mark.story("19.3", ac=2)
def test_an_items_own_hold_does_not_count_against_dates_it_overlaps(login_as, db: Session):
    """Moved an hour later, the new dates overlap the old: the item's own hold of 3 of 4
    projectors is released before it is held again, so all 4 are available to it."""
    event = _planning_event(db)
    projectors = make_equipment_type(db, total_quantity=4)
    item = make_equipment_item(db, event=event, equipment_type=projectors, quantity=3)
    request = _raise(
        login_as,
        db,
        event,
        "schedule",
        _schedule(event.starts_at + timedelta(hours=1), event.ends_at + timedelta(hours=1)),
    )

    impact = _impact(login_as, request)
    row = {row["item_id"]: row for row in impact["equipment"]}[str(item.id)]
    response = _approve(login_as, request, impact["fingerprint"])

    assert response.status_code == 200, response.text
    assert (row["available"], row["shortfall"]) == (4, 0)
    assert row["status_after"] == _item_status(db, item.id) == "REQUESTED"


@pytest.mark.story("19.3", ac=2)
def test_approval_sends_no_notice_beyond_19_2s(login_as, db: Session):
    event = _planning_event(db)
    requirement = _requirement(db, event, capacity=80)
    _book(db, event, people=80, requirement_id=requirement)
    request = _grow(login_as, db, event, requirement, 90)

    impact = _impact(login_as, request)
    _approve(login_as, request, impact["fingerprint"])

    kinds = set(
        db.execute(
            text("SELECT DISTINCT notification_type FROM notifications WHERE event_id = :e"),
            {"e": event.id},
        ).scalars()
    )
    assert kinds == {"EVENT_CHANGE_REQUESTED", "EVENT_CHANGE_APPROVED", "BOOKING_RELEASED"}


# --- AC3: from the records as they stand, writing nothing --------------------------------------


@pytest.mark.story("19.3", ac=3)
def test_assessing_changes_nothing(login_as, db: Session):
    event = _planning_event(db)
    _book(db, event, people=100, requirement_id=_requirement(db, event, capacity=100))
    make_equipment_item(
        db, event=event, equipment_type=make_equipment_type(db), quantity=2, status="ACCEPTED"
    )
    _register(db, event, 2)
    starts_at = event.starts_at + timedelta(days=7)
    request = _raise(
        login_as, db, event, "schedule", _schedule(starts_at, starts_at + timedelta(hours=8))
    )
    # Signed in first: signing in is audited, and only the assessment is being watched.
    coordinator = login_as(Users.COORDINATOR)
    before = _snapshot(db, event)

    response = coordinator.get(_impact_url(request))

    assert response.status_code == 200, response.text
    assert _snapshot(db, event) == before
    assert _request_status(db, request.id) == "PENDING"


@pytest.mark.story("19.3", ac=3)
def test_a_booking_made_after_the_request_is_assessed(login_as, db: Session):
    event = _planning_event(db)
    requirement = _requirement(db, event, capacity=80)
    request = _grow(login_as, db, event, requirement, 90)
    hall = _book(db, event, people=80, requirement_id=requirement)

    assert str(hall.id) in _bookings_by_id(_impact(login_as, request))


# --- AC4: boundaries --------------------------------------------------------------------------


def _moved_by_a_week(login_as, db: Session, *, setup: int = 0, teardown: int = 0, hours=None):
    """An event with its hall booked, and a request to move it a week later; returns the event,
    the hall's booking, the venue and the new period."""
    event = _planning_event(db)
    venue = make_venue(db, capacity=500, hours=hours)
    hall = _book(
        db,
        event,
        people=100,
        requirement_id=_requirement(db, event, capacity=100),
        venue=venue,
        setup_minutes=setup,
        teardown_minutes=teardown,
    )
    starts_at = event.starts_at + timedelta(days=7)
    ends_at = starts_at + timedelta(hours=8)
    request = _raise(login_as, db, event, "schedule", _schedule(starts_at, ends_at))
    return request, hall, venue, starts_at, ends_at


def _other_booking(db: Session, venue, *, starts_at: datetime, ends_at: datetime):
    other = _planning_event(db, starts_at=starts_at - timedelta(days=1))
    return make_booking(
        db,
        event_id=other.id,
        venue_id=venue.id,
        starts_at=starts_at,
        ends_at=ends_at,
        status="PENDING",
    )


@pytest.mark.story("19.3", ac=4)
def test_a_booking_touching_the_new_period_does_not_conflict(login_as, db: Session):
    request, hall, venue, starts_at, _ = _moved_by_a_week(login_as, db)
    _other_booking(db, venue, starts_at=starts_at - timedelta(hours=2), ends_at=starts_at)

    row = _bookings_by_id(_impact(login_as, request))[str(hall.id)]

    assert row["held_by"] is None


@pytest.mark.story("19.3", ac=4)
def test_one_minute_of_overlap_conflicts(login_as, db: Session):
    request, hall, venue, starts_at, _ = _moved_by_a_week(login_as, db)
    other = _other_booking(
        db,
        venue,
        starts_at=starts_at - timedelta(hours=2),
        ends_at=starts_at + timedelta(minutes=1),
    )

    row = _bookings_by_id(_impact(login_as, request))[str(hall.id)]

    assert row["held_by"]["event_name"] == db.get(Event, other.event_id).name
    assert row["needed_starts_at"] is not None


@pytest.mark.story("19.3", ac=4)
def test_setup_time_counts_towards_the_period_needed(login_as, db: Session):
    """The other booking ends as the new event starts, but the hall needs 30 minutes' setup
    before it, as it was booked with (12.1)."""
    request, hall, venue, starts_at, _ = _moved_by_a_week(login_as, db, setup=30)
    _other_booking(db, venue, starts_at=starts_at - timedelta(hours=2), ends_at=starts_at)

    row = _bookings_by_id(_impact(login_as, request))[str(hall.id)]

    assert row["held_by"] is not None


@pytest.mark.story("19.3", ac=4)
def test_teardown_time_counts_towards_the_period_needed(login_as, db: Session):
    """The other booking starts as the new event ends, but the hall needs 30 minutes' teardown
    after it, as it was booked with (12.1)."""
    request, hall, venue, _, ends_at = _moved_by_a_week(login_as, db, teardown=30)
    _other_booking(db, venue, starts_at=ends_at, ends_at=ends_at + timedelta(hours=2))

    row = _bookings_by_id(_impact(login_as, request))[str(hall.id)]

    assert row["held_by"] is not None


@pytest.mark.story("19.3", ac=4)
@pytest.mark.parametrize(("capacity", "is_warned"), [(150, False), (149, True)])
def test_attendance_equal_to_capacity_fits(login_as, db: Session, capacity, is_warned):
    """The foyer, booked for the event's 100, is kept through a rise to 150 (fix f19.2.1), so it
    is listed only when it is warned about."""
    event = _planning_event(db, expected_attendance=100)
    foyer = _book(db, event, people=100, capacity=capacity)
    request = _raise(login_as, db, event, "expected_attendance", 150)

    rows = _bookings_by_id(_impact(login_as, request))

    if is_warned:
        assert rows[str(foyer.id)]["capacity_warning"] is not None
    else:
        assert str(foyer.id) not in rows


@pytest.mark.story("19.3", ac=4)
def test_the_booked_layouts_capacity_is_compared(login_as, db: Session):
    """The hall seats 300, but only 120 in the theatre layout it was booked for (11.1 AC4)."""
    event = _planning_event(db, expected_attendance=200)
    requirement = _requirement(db, event, capacity=100, layout_code="THEATRE")
    venue = make_venue(db, capacity=300, layouts={"THEATRE": 120})
    hall = _book(
        db,
        event,
        people=200,
        requirement_id=requirement,
        venue=venue,
        required_layout_code="THEATRE",
    )
    body = _requirement_body(requirement, name="Main hall", capacity=150, event=event)
    request = _raise(
        login_as, db, event, "venue_requirements", [{**body, "layout_code": "THEATRE"}]
    )

    row = _bookings_by_id(_impact(login_as, request))[str(hall.id)]

    assert row["capacity_warning"] == {
        "people_needed": 150,
        "venue_capacity": 120,
        "layout_name": "Theatre",
    }


# --- AC5: unavailability, opening hours and equipment shortfalls --------------------------------


@pytest.mark.story("19.3", ac=5)
def test_an_unavailability_period_over_the_new_times_is_flagged(login_as, db: Session):
    request, hall, venue, starts_at, ends_at = _moved_by_a_week(login_as, db)
    make_unavailability(
        db, venue_id=venue.id, starts_at=ends_at - timedelta(hours=1), ends_at=ends_at
    )

    row = _bookings_by_id(_impact(login_as, request))[str(hall.id)]

    assert row["closure"]["reason"] == "MAINTENANCE"


@pytest.mark.story("19.3", ac=5)
def test_an_unavailability_period_touching_the_new_times_is_not(login_as, db: Session):
    request, hall, venue, _, ends_at = _moved_by_a_week(login_as, db)
    make_unavailability(
        db, venue_id=venue.id, starts_at=ends_at, ends_at=ends_at + timedelta(hours=2)
    )

    row = _bookings_by_id(_impact(login_as, request))[str(hall.id)]

    assert row["closure"] is None


@pytest.mark.story("19.3", ac=5)
def test_an_unavailability_period_over_the_setup_is_flagged(login_as, db: Session):
    """The closure ends as the new event starts, but the hall is held from 30 minutes before for
    setup, and 12.1 judges a closure on the held period."""
    request, hall, venue, starts_at, _ = _moved_by_a_week(login_as, db, setup=30)
    make_unavailability(
        db, venue_id=venue.id, starts_at=starts_at - timedelta(hours=2), ends_at=starts_at
    )

    row = _bookings_by_id(_impact(login_as, request))[str(hall.id)]

    assert row["closure"] is not None


@pytest.mark.story("19.3", ac=5)
def test_new_times_outside_the_opening_hours_are_flagged(login_as, db: Session):
    """The hall opens 07:00-09:00 Singapore time, which no eight-hour event fits."""
    request, hall, *_ = _moved_by_a_week(login_as, db, hours=(time(7, 0), time(9, 0)))

    row = _bookings_by_id(_impact(login_as, request))[str(hall.id)]

    assert row["is_outside_opening_hours"] is True


@pytest.mark.story("19.3", ac=5)
def test_opening_hours_are_judged_on_the_booked_times_not_the_setup(login_as, db: Session):
    """10:00-16:00 Singapore time at a hall open 09:00-17:00: inside the hours, though its 90
    minutes' setup starts at 08:30. 12.1 judges the hours on the booking's own times (f12.1.2)."""
    day = future_datetime(days=60).date()
    starts_at = datetime.combine(day, time(2, 0), tzinfo=UTC)  # 10:00 in Singapore
    event = _planning_event(db, starts_at=starts_at, ends_at=starts_at + timedelta(hours=6))
    hall = _book(
        db,
        event,
        people=100,
        requirement_id=_requirement(db, event, capacity=100),
        venue=make_venue(db, capacity=500, hours=(time(9, 0), time(17, 0))),
        setup_minutes=90,
    )
    moved = starts_at + timedelta(days=7)
    request = _raise(login_as, db, event, "schedule", _schedule(moved, moved + timedelta(hours=6)))

    row = _bookings_by_id(_impact(login_as, request))[str(hall.id)]

    assert row["will_be_cancelled"] is True
    assert row["is_outside_opening_hours"] is False


@pytest.mark.story("19.3", ac=5)
def test_an_equipment_shortfall_names_required_available_and_short(login_as, db: Session):
    event = _planning_event(db)
    microphones = make_equipment_type(db, total_quantity=5)
    starts_at = event.starts_at + timedelta(days=7)
    ends_at = starts_at + timedelta(hours=8)
    make_equipment_hold(
        db, type_code=microphones.code, quantity=2, starts_at=starts_at, ends_at=ends_at
    )
    item = make_equipment_item(db, event=event, equipment_type=microphones, quantity=5)
    request = _raise(login_as, db, event, "schedule", _schedule(starts_at, ends_at))

    row = {row["item_id"]: row for row in _impact(login_as, request)["equipment"]}[str(item.id)]

    assert (row["required"], row["available"], row["shortfall"]) == (5, 3, 2)
    assert row["status_after"] == "UNAVAILABLE"


@pytest.mark.story("19.3", ac=5)
def test_units_out_of_service_count_against_availability(login_as, db: Session):
    event = _planning_event(db)
    microphones = make_equipment_type(db, total_quantity=5)
    item = make_equipment_item(db, event=event, equipment_type=microphones, quantity=2)
    make_equipment_out_of_service(
        db, type_code=microphones.code, quantity=4, starts_at=datetime.now(UTC)
    )
    request = _raise(login_as, db, event, "equipment", [_equipment_body(item.id, microphones, 3)])

    row = {row["item_id"]: row for row in _impact(login_as, request)["equipment"]}[str(item.id)]

    assert (row["required"], row["available"], row["shortfall"]) == (3, 1, 2)


# --- AC6: only the assigned coordinator --------------------------------------------------------


@pytest.mark.story("19.3", ac=6)
def test_signed_out_cannot_see_the_impact(client, login_as, db: Session):
    request = _raise(login_as, db, _planning_event(db), "expected_attendance", 120)
    client.post("/auth/logout")

    assert client.get(_impact_url(request)).status_code == 401


@pytest.mark.story("19.3", ac=6)
@pytest.mark.parametrize(
    "user",
    [Users.ORGANISER, Users.COORDINATOR_2, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE],
)
def test_only_the_assigned_coordinator_sees_the_impact(login_as, db: Session, user):
    request = _raise(login_as, db, _planning_event(db), "expected_attendance", 120)

    assert login_as(user).get(_impact_url(request)).status_code == 403


@pytest.mark.story("19.3", ac=6)
def test_another_coordinator_is_told_why(login_as, db: Session):
    request = _raise(login_as, db, _planning_event(db), "expected_attendance", 120)

    response = login_as(Users.COORDINATOR_2).get(_impact_url(request))

    assert response.json()["detail"] == _NOT_ASSIGNED


@pytest.mark.story("19.3", ac=6)
def test_after_reassignment_only_the_new_coordinator_sees_it(login_as, db: Session):
    event = _planning_event(db)
    request = _raise(login_as, db, event, "expected_attendance", 120)
    db.execute(
        text("UPDATE events SET assigned_coordinator_id = :c WHERE id = :e"),
        {"c": Users.COORDINATOR_2.id, "e": event.id},
    )
    db.expire_all()

    assert login_as(Users.COORDINATOR).get(_impact_url(request)).status_code == 403
    assert login_as(Users.COORDINATOR_2).get(_impact_url(request)).status_code == 200


@pytest.mark.story("19.3", ac=6)
def test_an_unknown_event_or_request_is_not_found(login_as, db: Session):
    request = _raise(login_as, db, _planning_event(db), "expected_attendance", 120)
    coordinator = login_as(Users.COORDINATOR)

    unknown_event = coordinator.get(f"/events/{uuid.uuid4()}/change-requests/{request.id}/impact")
    unknown_request = coordinator.get(
        f"/events/{request.event_id}/change-requests/{uuid.uuid4()}/impact"
    )

    assert (unknown_event.status_code, unknown_event.json()["detail"]) == (404, _EVENT_NOT_FOUND)
    assert (unknown_request.status_code, unknown_request.json()["detail"]) == (
        404,
        _CHANGE_REQUEST_NOT_FOUND,
    )


@pytest.mark.story("19.3", ac=6)
@pytest.mark.parametrize("status", ["APPROVED", "REJECTED", "WITHDRAWN"])
def test_a_decided_request_has_no_impact_to_assess(login_as, db: Session, status):
    request = _raise(login_as, db, _planning_event(db), "expected_attendance", 120)
    db.execute(
        text("UPDATE event_change_requests SET status = :s WHERE id = :id"),
        {"s": status, "id": request.id},
    )
    db.expire_all()

    assert login_as(Users.COORDINATOR).get(_impact_url(request)).status_code == 409


@pytest.mark.story("19.3", ac=6)
def test_a_cancelled_event_has_no_impact_to_assess(login_as, db: Session):
    event = _planning_event(db)
    request = _raise(login_as, db, event, "expected_attendance", 120)
    db.execute(text("UPDATE events SET status = 'CANCELLED' WHERE id = :e"), {"e": event.id})
    db.expire_all()

    assert login_as(Users.COORDINATOR).get(_impact_url(request)).status_code == 409


# --- AC7: re-assessed when approving ------------------------------------------------------------


@pytest.mark.story("19.3", ac=7)
def test_approving_with_the_current_assessment_applies_the_change(login_as, db: Session):
    event = _planning_event(db, expected_attendance=80)
    request = _raise(login_as, db, event, "expected_attendance", 90)

    response = _approve(login_as, request, _impact(login_as, request)["fingerprint"])

    assert response.status_code == 200, response.text
    assert _request_status(db, request.id) == "APPROVED"


@pytest.mark.story("19.3", ac=7)
def test_approving_after_the_impact_changed_is_refused_and_applies_nothing(login_as, db: Session):
    """Chloe opened the request when nothing was affected; a booking the change no longer fits
    was approved for the event before she clicked Approve."""
    event = _planning_event(db)
    requirement = _requirement(db, event, capacity=80)
    request = _grow(login_as, db, event, requirement, 90)
    seen = _impact(login_as, request)
    hall = _book(db, event, people=80, requirement_id=requirement)

    response = _approve(login_as, request, seen["fingerprint"])

    assert (response.status_code, response.json()["detail"]) == (412, _IMPACT_CHANGED)
    assert _request_status(db, request.id) == "PENDING"
    assert _booking_status(db, hall.id) == "APPROVED"
    db.expire_all()
    assert [item.capacity for item in db.get(Event, event.id).venue_requirements] == [80]
    fresh = _impact(login_as, request)
    assert fresh["fingerprint"] != seen["fingerprint"]
    assert _approve(login_as, request, fresh["fingerprint"]).status_code == 200


@pytest.mark.story("19.3", ac=7)
def test_equipment_taken_meanwhile_changes_the_assessment(login_as, db: Session):
    event = _planning_event(db)
    microphones = make_equipment_type(db, total_quantity=5)
    item = make_equipment_item(db, event=event, equipment_type=microphones, quantity=2)
    request = _raise(login_as, db, event, "equipment", [_equipment_body(item.id, microphones, 4)])
    seen = _impact(login_as, request)
    make_equipment_hold(
        db,
        type_code=microphones.code,
        quantity=2,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
    )

    response = _approve(login_as, request, seen["fingerprint"])

    assert response.status_code == 412
    assert _item_status(db, item.id) == "REQUESTED"


@pytest.mark.story("19.3", ac=7)
def test_a_registration_made_meanwhile_changes_the_assessment(login_as, db: Session):
    event = _planning_event(db, expected_attendance=100)
    _register(db, event, 3)
    request = _raise(login_as, db, event, "expected_attendance", 2)
    seen = _impact(login_as, request)
    _register(db, event, 1)

    response = _approve(login_as, request, seen["fingerprint"])

    assert response.status_code == 412
    assert _request_status(db, request.id) == "PENDING"


@pytest.mark.story("19.3", ac=7)
def test_a_capacity_shortfall_changed_meanwhile_changes_the_assessment(login_as, db: Session):
    """The hall seated 250 of the 500 asked for when Chloe looked; Venue Staff then recorded it
    as seating 200."""
    event = _planning_event(db, expected_attendance=180)
    hall = _book(
        db, event, people=180, requirement_id=_requirement(db, event, capacity=180), capacity=250
    )
    request = _raise(login_as, db, event, "expected_attendance", 500)
    seen = _impact(login_as, request)
    db.execute(text("UPDATE venues SET capacity = 200 WHERE id = :v"), {"v": hall.venue_id})
    db.expire_all()

    response = _approve(login_as, request, seen["fingerprint"])

    assert response.status_code == 412
    assert _request_status(db, request.id) == "PENDING"


@pytest.mark.story("19.3", ac=7)
def test_approving_needs_the_assessment_seen(login_as, db: Session):
    request = _raise(login_as, db, _planning_event(db), "expected_attendance", 120)

    response = _approve(login_as, request, None)

    assert response.status_code == 422
    assert _request_status(db, request.id) == "PENDING"


@pytest.mark.story("19.3", ac=7)
def test_an_out_of_date_request_is_still_refused_as_19_2_refuses_it(login_as, db: Session):
    event = _planning_event(db, expected_attendance=100)
    request = _raise(login_as, db, event, "expected_attendance", 120)
    seen = _impact(login_as, request)
    db.execute(text("UPDATE events SET expected_attendance = 110 WHERE id = :e"), {"e": event.id})
    db.expire_all()

    response = _approve(login_as, request, seen["fingerprint"])

    assert response.status_code == 409
    assert "changed since this request was raised" in response.json()["detail"]


@pytest.mark.story("19.3", ac=7)
def test_rejecting_needs_no_assessment(login_as, db: Session):
    request = _raise(login_as, db, _planning_event(db), "expected_attendance", 120)
    object_session(request).commit()

    response = login_as(Users.COORDINATOR).post(
        f"/events/{request.event_id}/change-requests/{request.id}/reject",
        json={"reason": "Not this time."},
    )

    assert response.status_code == 200, response.text
