"""Story 12.1 - fe/be: raise venue booking request.

AC1 A request can be raised only from an approved event and against one venue.
AC2 The request carries the event's date, start and end times, expected attendance, required
    layout, and required facilities.
AC3 On submission the request appears in the Venue Staff pending queue with a pending status.
AC4 Only the assigned coordinator for that event can raise the request.

AC1's "against one venue" is structural rather than a rule to test: the request body takes a
single ``venue_id``, so one request is one venue by construction. What is testable - and tested
below - is the other half of AC1, the event's status.

AC3 is covered as far as this story's backend reaches. The pending *queue* itself is story 13.1
(``fe: display venue staff booking queue``), which depends on this story and does not exist
yet; there is no listing endpoint to assert against. What is proven here is everything the queue
will read: the new row is PENDING, carries no decision, and is immediately readable by Venue
Staff through story 13.2's ``GET /bookings/{id}``.

Excluded, with reason:
* Setup and teardown minutes - story 12.2 AC1 ("setup and teardown durations can be recorded on
  the request") owns them. This story leaves both at the column default of 0, so the held period
  equals the event period; ``test_the_held_period_is_the_event_period_until_story_12_2`` pins
  that so 12.2 has a test to change rather than a silent assumption to discover.
* A conflict check at submission time - story 14.1 ("warn of booking conflicts before
  submission"). An overlapping PENDING row is legitimately allowed today: the database's
  ``ex_venue_bookings_no_double_booking`` constraint only guards APPROVED rows, and stories
  13.2 / 14.2 already refuse the overlap at approval time.
  ``test_an_overlapping_pending_request_is_allowed_until_story_14_1`` records that deliberate
  gap.
* Refusing a venue that is too small or lacks a required facility - stories 11.2 / 11.3. 11.3
  AC1 wants a warning the coordinator can override, not a block, so refusing it here would
  pre-empt a decision that story reverses.
* An e2e spec - there is no page to click through. A coordinator cannot reach an approved event
  assigned to them until story 4.1's queue or 7.1's detail page exists, so the request flow has
  no UI entry point yet. Every case here is a rule, boundary or permission case, which
  AGENTS.md assigns to ``backend/tests/`` anyway.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.bookings.models import BookingStatus
from app.events.models import EventStatus
from tests.support.factories import make_event, make_venue
from tests.support.seed import Events, Users, Venues

# The seeded APPROVED event (Nimbus Developer Conference): 2026-11-25 09:00-18:00 +08, 350
# attendees, THEATRE layout, requiring PROJECTOR + SOUND_SYSTEM + STAGE.
EVENT_STARTS_AT = datetime(2026, 11, 25, 1, 0, tzinfo=timezone.utc)
EVENT_ENDS_AT = datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)
EVENT_ATTENDANCE = 350
EVENT_LAYOUT = "THEATRE"


def request_body(**overrides) -> dict:
    """A valid POST /bookings body: the assigned coordinator's event, plus one venue."""
    body = {"event_id": str(Events.APPROVED), "venue_id": str(Venues.GRAND_HALL)}
    body.update(overrides)
    return body


def _booking_count(db: Session, event_id: uuid.UUID) -> int:
    return db.scalar(
        text("SELECT count(*) FROM venue_bookings WHERE event_id = :id"), {"id": event_id}
    )


# --- AC1: only from an approved event, against one venue ------------------------------------
@pytest.mark.story("12.1", ac=1)
def test_assigned_coordinator_can_raise_a_request_for_an_approved_event(
    coordinator_client, db: Session
):
    response = coordinator_client.post("/bookings", json=request_body())

    assert response.status_code == 201
    body = response.json()
    assert body["event_id"] == str(Events.APPROVED)
    assert body["venue_id"] == str(Venues.GRAND_HALL)

    row = db.execute(
        text("SELECT event_id, venue_id, status FROM venue_bookings WHERE id = :id"),
        {"id": body["id"]},
    ).one()
    assert row.event_id == Events.APPROVED
    assert row.venue_id == Venues.GRAND_HALL
    assert row.status == BookingStatus.PENDING


@pytest.mark.story("12.1", ac=1)
@pytest.mark.parametrize("status", [EventStatus.PLANNING, EventStatus.CONFIRMED])
def test_an_event_past_approval_can_still_raise_a_request(coordinator_client, db: Session, status):
    """The schema's rule is "APPROVED (or later)" (venue_bookings.event_id comment): an event
    already in planning or confirmed may still need another venue booked."""
    event = make_event(
        db,
        status=status,
        assigned_coordinator_id=Users.COORDINATOR.id,
    )

    response = coordinator_client.post("/bookings", json=request_body(event_id=str(event.id)))

    assert response.status_code == 201


@pytest.mark.story("12.1", ac=1)
@pytest.mark.parametrize(
    "status",
    [
        EventStatus.DRAFT,
        EventStatus.SUBMITTED,
        EventStatus.UNDER_REVIEW,
        EventStatus.CLARIFICATION_REQUESTED,
        EventStatus.REJECTED,
        EventStatus.CANCELLED,
        EventStatus.COMPLETED,
    ],
)
def test_an_event_that_is_not_approved_cannot_raise_a_request(
    coordinator_client, db: Session, status
):
    event = make_event(db, status=status, assigned_coordinator_id=Users.COORDINATOR.id)

    response = coordinator_client.post("/bookings", json=request_body(event_id=str(event.id)))

    assert response.status_code == 409
    assert status in response.json()["detail"]
    assert _booking_count(db, event.id) == 0


@pytest.mark.story("12.1", ac=1)
def test_the_seeded_draft_event_cannot_raise_a_request(coordinator_client, db: Session):
    """Same rule as above against real seed data rather than a factory row: the DRAFT event is
    also missing its dates, so this proves the status check refuses it on status alone."""
    response = coordinator_client.post("/bookings", json=request_body(event_id=str(Events.DRAFT)))

    assert response.status_code == 409
    assert _booking_count(db, Events.DRAFT) == 0


@pytest.mark.story("12.1", ac=1)
def test_raising_a_request_for_an_unknown_event_is_404(coordinator_client):
    response = coordinator_client.post("/bookings", json=request_body(event_id=str(uuid.uuid4())))

    assert response.status_code == 404


@pytest.mark.story("12.1", ac=1)
def test_raising_a_request_for_an_unknown_venue_is_404(coordinator_client):
    response = coordinator_client.post("/bookings", json=request_body(venue_id=str(uuid.uuid4())))

    assert response.status_code == 404


@pytest.mark.story("12.1", ac=1)
def test_a_withdrawn_venue_cannot_be_booked(coordinator_client, db: Session):
    response = coordinator_client.post(
        "/bookings", json=request_body(venue_id=str(Venues.OLD_ANNEX))
    )

    assert response.status_code == 409
    assert _booking_count(db, Events.APPROVED) == 2  # the two seeded rows, nothing added


@pytest.mark.story("12.1", ac=1)
def test_a_venue_created_without_a_status_defaults_to_active_and_is_bookable(
    coordinator_client, db: Session
):
    """Guards the withdrawn-venue check against being written as ``status != 'WITHDRAWN'`` on a
    column that is only defaulted by the database."""
    venue = make_venue(db, capacity=500)

    response = coordinator_client.post("/bookings", json=request_body(venue_id=str(venue.id)))

    assert response.status_code == 201


@pytest.mark.story("12.1", ac=2)
def test_a_bookable_event_always_has_a_schedule_to_copy(db: Session):
    """AC2 copies the event's period and attendance unconditionally, which is only safe because
    the schema forbids a non-DRAFT event from leaving them null
    (``ck_events_submitted_fields_complete``). Asserted here rather than guarded in the service,
    because a guard for this would be a branch no request can reach.

    ``events.starts_at`` and friends being nullable is what makes this worth pinning: the
    nullability is for DRAFT rows (story 3.1 AC1), not for approved ones.
    """
    with pytest.raises(IntegrityError, match="ck_events_submitted_fields_complete"):
        make_event(
            db,
            status=EventStatus.APPROVED,
            assigned_coordinator_id=Users.COORDINATOR.id,
            starts_at=None,
            ends_at=None,
            expected_attendance=None,
        )


@pytest.mark.story("12.1", ac=1)
def test_two_venues_for_one_event_are_two_separate_requests(coordinator_client, db: Session):
    """ "Against one venue" is per request, not per event: a conference needing a hall and a
    breakout room raises one request each, which is how the seed data models it."""
    first = coordinator_client.post("/bookings", json=request_body(venue_id=str(Venues.BOARDROOM)))
    second = coordinator_client.post(
        "/bookings", json=request_body(venue_id=str(Venues.EXHIBITION_FOYER))
    )

    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["venue_id"] == str(Venues.BOARDROOM)
    assert second.json()["venue_id"] == str(Venues.EXHIBITION_FOYER)


# --- AC2: the request carries the event's details -------------------------------------------
@pytest.mark.story("12.1", ac=2)
def test_the_request_carries_the_events_schedule_attendance_and_layout(coordinator_client):
    response = coordinator_client.post("/bookings", json=request_body())

    assert response.status_code == 201
    body = response.json()
    assert datetime.fromisoformat(body["starts_at"]) == EVENT_STARTS_AT
    assert datetime.fromisoformat(body["ends_at"]) == EVENT_ENDS_AT
    assert body["expected_attendance"] == EVENT_ATTENDANCE
    assert body["required_layout_code"] == EVENT_LAYOUT


@pytest.mark.story("12.1", ac=2)
def test_the_request_states_the_events_required_facilities_to_venue_staff(coordinator_client):
    """The seeded event requires PROJECTOR, SOUND_SYSTEM and STAGE. Venue Staff read
    ``requirement_notes``, so the facilities are stated there by name, not by code."""
    response = coordinator_client.post("/bookings", json=request_body())

    notes = response.json()["requirement_notes"]
    assert "Projector & screen" in notes
    assert "Sound system" in notes
    assert "Stage" in notes


@pytest.mark.story("12.1", ac=2)
def test_the_events_own_venue_requirement_notes_are_carried_too(coordinator_client, db: Session):
    event = make_event(
        db,
        status=EventStatus.APPROVED,
        assigned_coordinator_id=Users.COORDINATOR.id,
        venue_requirement_notes="Must be step-free from the drop-off point.",
    )

    response = coordinator_client.post("/bookings", json=request_body(event_id=str(event.id)))

    assert "Must be step-free from the drop-off point." in response.json()["requirement_notes"]


@pytest.mark.story("12.1", ac=2)
def test_an_event_with_no_layout_or_facilities_recorded_carries_neither(
    coordinator_client, db: Session
):
    event = make_event(
        db,
        status=EventStatus.APPROVED,
        assigned_coordinator_id=Users.COORDINATOR.id,
        required_layout_code=None,
    )

    response = coordinator_client.post("/bookings", json=request_body(event_id=str(event.id)))

    assert response.status_code == 201
    body = response.json()
    assert body["required_layout_code"] is None
    assert body["requirement_notes"] is None


@pytest.mark.story("12.1", ac=2)
def test_details_supplied_by_the_client_are_ignored_in_favour_of_the_events_own(
    coordinator_client,
):
    """AC2 says the request carries *the event's* details, so these are read from the event row,
    never from the request body - a coordinator cannot book a different period or a larger
    attendance than the event was approved for."""
    response = coordinator_client.post(
        "/bookings",
        json=request_body(
            starts_at="2030-01-01T00:00:00+00:00",
            ends_at="2030-01-02T00:00:00+00:00",
            expected_attendance=1,
            required_layout_code="BOARDROOM",
            status=BookingStatus.APPROVED,
        ),
    )

    assert response.status_code == 201
    body = response.json()
    assert datetime.fromisoformat(body["starts_at"]) == EVENT_STARTS_AT
    assert body["expected_attendance"] == EVENT_ATTENDANCE
    assert body["required_layout_code"] == EVENT_LAYOUT
    assert body["status"] == BookingStatus.PENDING


@pytest.mark.story("12.1", ac=2)
def test_the_held_period_is_the_event_period_until_story_12_2(coordinator_client):
    """Story 12.2 is what records setup and teardown time; this story leaves both at the column
    default of 0, so the held period the conflict checks use is exactly the event period. When
    12.2 lands, this test is the one to change."""
    body = coordinator_client.post("/bookings", json=request_body()).json()

    assert (body["setup_minutes"], body["teardown_minutes"]) == (0, 0)
    assert datetime.fromisoformat(body["held_from"]) == EVENT_STARTS_AT
    assert datetime.fromisoformat(body["held_until"]) == EVENT_ENDS_AT


# --- AC3: the request is pending and visible to Venue Staff ---------------------------------
@pytest.mark.story("12.1", ac=3)
def test_a_new_request_is_pending_and_carries_no_decision(coordinator_client):
    response = coordinator_client.post("/bookings", json=request_body())

    body = response.json()
    assert body["status"] == BookingStatus.PENDING
    assert body["decided_by_id"] is None
    assert body["decided_at"] is None
    assert body["decision_reason"] is None
    assert body["alternative_suggestion"] is None


@pytest.mark.story("12.1", ac=3)
def test_venue_staff_can_read_a_newly_raised_request(client, login_as):
    """The pending queue itself is story 13.1; what this story owes it is a row Venue Staff can
    already fetch, through the read endpoint story 13.2 built."""
    raised = login_as(Users.COORDINATOR).post("/bookings", json=request_body())
    assert raised.status_code == 201

    response = login_as(Users.VENUE_STAFF).get(f"/bookings/{raised.json()['id']}")

    assert response.status_code == 200
    assert response.json()["status"] == BookingStatus.PENDING
    assert response.json()["expected_attendance"] == EVENT_ATTENDANCE


@pytest.mark.story("12.1", ac=3)
def test_a_raised_request_can_then_be_approved_by_venue_staff(client, login_as, db: Session):
    """End of the chain this story starts: the row it writes is one story 13.2 can decide on.
    Booked against a venue with no seeded booking, so the approval is not refused by 14.2."""
    raised = login_as(Users.COORDINATOR).post(
        "/bookings", json=request_body(venue_id=str(Venues.BOARDROOM))
    )
    assert raised.status_code == 201

    approved = login_as(Users.VENUE_STAFF).post(f"/bookings/{raised.json()['id']}/approve")

    assert approved.status_code == 200
    assert approved.json()["status"] == BookingStatus.APPROVED


@pytest.mark.story("12.1", ac=3)
def test_an_overlapping_pending_request_is_allowed_until_story_14_1(coordinator_client):
    """The seeded APPROVED booking holds the Grand Hall for this exact period. Story 14.1 is
    what warns about that at submission time; today the request is accepted and story 13.2 /
    14.2 refuse it at approval. Recorded as a test so the gap is deliberate and visible."""
    response = coordinator_client.post("/bookings", json=request_body())

    assert response.status_code == 201
    assert response.json()["status"] == BookingStatus.PENDING


# --- AC4: only the assigned coordinator ------------------------------------------------------
@pytest.mark.story("12.1", ac=4)
def test_the_request_records_the_coordinator_who_raised_it(coordinator_client):
    response = coordinator_client.post("/bookings", json=request_body())

    assert response.json()["requested_by_id"] == str(Users.COORDINATOR.id)


@pytest.mark.story("12.1", ac=4)
def test_a_coordinator_cannot_raise_a_request_for_someone_elses_event(client, db: Session):
    """Carl is a coordinator - he holds bookings:request - but this event is Chloe's."""
    client.login(Users.COORDINATOR_2)

    response = client.post("/bookings", json=request_body())

    assert response.status_code == 403
    assert _booking_count(db, Events.APPROVED) == 2  # the two seeded rows, nothing added


@pytest.mark.story("12.1", ac=4)
def test_an_event_with_no_coordinator_assigned_cannot_raise_a_request(
    coordinator_client, db: Session
):
    """Story 5.1 assigns the coordinator. Until an event has one, nobody is "the assigned
    coordinator", so there is no one who may raise its booking."""
    event = make_event(db, status=EventStatus.APPROVED, assigned_coordinator_id=None)

    response = coordinator_client.post("/bookings", json=request_body(event_id=str(event.id)))

    assert response.status_code == 403
    assert _booking_count(db, event.id) == 0


@pytest.mark.story("12.1", ac=4)
def test_a_coordinator_cannot_raise_a_request_in_another_coordinators_name(coordinator_client):
    """The requester is the signed-in actor, never a client-supplied field."""
    response = coordinator_client.post(
        "/bookings", json=request_body(requested_by_id=str(Users.COORDINATOR_2.id))
    )

    assert response.status_code == 201
    assert response.json()["requested_by_id"] == str(Users.COORDINATOR.id)


@pytest.mark.story("12.1", ac=4)
@pytest.mark.parametrize(
    "user",
    [Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE],
    ids=lambda u: u.role,
)
def test_roles_without_the_booking_request_permission_are_refused(client, db: Session, user):
    client.login(user)

    response = client.post("/bookings", json=request_body())

    assert response.status_code == 403
    assert _booking_count(db, Events.APPROVED) == 2  # the two seeded rows, nothing added


@pytest.mark.story("12.1", ac=4)
def test_signed_out_visitors_cannot_raise_a_request(client):
    assert client.post("/bookings", json=request_body()).status_code == 401


# --- Validation and audit --------------------------------------------------------------------
@pytest.mark.story("12.1", ac=1)
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"event_id": str(Events.APPROVED)},
        {"venue_id": str(Venues.GRAND_HALL)},
        {"event_id": "not-a-uuid", "venue_id": str(Venues.GRAND_HALL)},
        {"event_id": str(Events.APPROVED), "venue_id": ""},
    ],
    ids=["empty", "venue missing", "event missing", "event not a uuid", "venue blank"],
)
def test_an_incomplete_request_body_is_rejected(coordinator_client, body):
    assert coordinator_client.post("/bookings", json=body).status_code == 422


@pytest.mark.story("12.1")
def test_raising_a_request_is_recorded_in_the_audit_log(coordinator_client, db: Session):
    raised = coordinator_client.post("/bookings", json=request_body())

    row = db.execute(
        text(
            "SELECT actor_id, details FROM audit_log "
            "WHERE action = 'BOOKING_REQUESTED' AND entity_id = :id"
        ),
        {"id": raised.json()["id"]},
    ).one()
    assert row.actor_id == Users.COORDINATOR.id
    assert row.details["event_id"] == str(Events.APPROVED)
    assert row.details["venue_id"] == str(Venues.GRAND_HALL)


@pytest.mark.story("12.1", ac=3)
def test_the_request_records_when_it_was_raised(coordinator_client):
    before = datetime.now(timezone.utc)

    response = coordinator_client.post("/bookings", json=request_body())

    created_at = datetime.fromisoformat(response.json()["created_at"])
    assert (
        before - timedelta(seconds=5)
        <= created_at
        <= datetime.now(timezone.utc) + timedelta(seconds=5)
    )
