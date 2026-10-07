"""Story 11.1 - venue suitability with reasons and override: requesting a venue that does not suit.

POST /bookings judges the venue again when the request is sent, with the same check the catalogue
uses (``app.venues.service.judge_venue_for_event``), so the request and the indicator cannot
disagree.

AC2  Requesting an unsuitable venue requires a justification, stored with the request.
AC3  The justification is saved on the booking request and returned to Venue Staff views.
AC5  A characteristic the venue has not recorded is never treated as met; an event with "No venue
     requirements" is judged on capacity only.
AC6  Only the assigned coordinator can override; the justification is visible to the assigned
     coordinator and the reviewing Venue Staff.
AC7  An empty justification is refused. If the requirements change, the request is judged as
     they stand when it is sent; a pending request keeps its justification.

Decided for this story (6-7 Oct 2026): a justification sent for a venue that suits is ignored and
nothing is stored (Q9); Venue Staff are not notified of an override (Q3), only told of the
request once, as story 20.1 tells them of any; who can read the justification is not
restricted (Q7). The justification is at most 2,000 characters, like a
clarification message. Availability is checked before suitability, so a venue that is both held
and unsuitable is refused as held.

The warning, the confirmation and the justification field the coordinator sees are the frontend's
(commit 5 of this story); these tests prove what the server does.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

import app.bookings.service as booking_service
from app.events.models import Event, EventStatus
from app.venues.models import Venue
from tests.support.factories import make_event, make_venue, make_venue_requirement
from tests.support.seed import Events, Users, Venues

BOOKINGS_PATH = "/bookings"
JUSTIFICATION = "Grand Hall is booked that day; the foyer is the only space left."


def _venue_suited_to_nimbus(db: Session) -> Venue:
    """A free venue that suits Nimbus's venue requirement: room for 350 in Theatre, a projector,
    sound system and stage, wheelchair access and a hearing loop. No seeded venue is both."""
    return make_venue(
        db,
        capacity=350,
        layouts={"THEATRE": None},
        facilities=("PROJECTOR", "SOUND_SYSTEM", "STAGE"),
        accessibility=("WHEELCHAIR_ACCESS", "HEARING_LOOP"),
    )


def _assigned_event(db: Session, **overrides) -> Event:
    return make_event(
        db, status=EventStatus.PLANNING, assigned_coordinator_id=Users.COORDINATOR.id, **overrides
    )


def _request(client, *, event_id: uuid.UUID, venue_id: uuid.UUID, **extra):
    return client.post(
        BOOKINGS_PATH, json={"event_id": str(event_id), "venue_id": str(venue_id), **extra}
    )


def _booking_count(db: Session, event_id: uuid.UUID) -> int:
    return db.scalar(
        text("SELECT count(*) FROM venue_bookings WHERE event_id = :id"), {"id": event_id}
    )


def _stored_reason(db: Session, booking_id: str) -> str | None:
    return db.scalar(
        text("SELECT suitability_override_reason FROM venue_bookings WHERE id = :id"),
        {"id": booking_id},
    )


def _audit_details(db: Session, booking_id: str) -> dict:
    return db.scalar(
        text(
            "SELECT details FROM audit_log WHERE action = 'BOOKING_REQUESTED' AND entity_id = :id"
        ),
        {"id": booking_id},
    )


# --- AC2/AC3: an unsuitable venue, requested with a justification -------------------------------
@pytest.mark.story("11.1", ac=2)
@pytest.mark.story("11.1", ac=3)
def test_an_unsuitable_venue_is_requested_with_a_justification_which_is_stored(
    coordinator_client, db: Session
):
    """Exhibition Foyer is free on Nimbus's day but does not suit it (250 < 350, no Theatre)."""
    response = _request(
        coordinator_client,
        event_id=Events.APPROVED,
        venue_id=Venues.EXHIBITION_FOYER,
        suitability_override_reason=JUSTIFICATION,
    )

    assert response.status_code == 201, response.text
    assert response.json()["suitability_override_reason"] == JUSTIFICATION
    assert _stored_reason(db, response.json()["id"]) == JUSTIFICATION


# --- AC7: no justification, or an empty one, is refused ----------------------------------------
@pytest.mark.story("11.1", ac=7)
def test_an_unsuitable_venue_without_a_justification_is_refused_and_nothing_is_written(
    coordinator_client, db: Session
):
    before = _booking_count(db, Events.APPROVED)

    response = _request(
        coordinator_client, event_id=Events.APPROVED, venue_id=Venues.EXHIBITION_FOYER
    )

    assert response.status_code == 422
    assert response.json()["detail"] == booking_service.JUSTIFICATION_REQUIRED_MESSAGE
    assert _booking_count(db, Events.APPROVED) == before


@pytest.mark.story("11.1", ac=7)
@pytest.mark.parametrize("justification", ["", "   "], ids=["empty", "whitespace only"])
def test_an_empty_justification_is_refused(coordinator_client, db: Session, justification):
    before = _booking_count(db, Events.APPROVED)

    response = _request(
        coordinator_client,
        event_id=Events.APPROVED,
        venue_id=Venues.EXHIBITION_FOYER,
        suitability_override_reason=justification,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == booking_service.JUSTIFICATION_REQUIRED_MESSAGE
    assert _booking_count(db, Events.APPROVED) == before


# --- AC2: the justification's length and shape ------------------------------------------------
@pytest.mark.story("11.1", ac=2)
def test_a_justification_of_2000_characters_is_stored(coordinator_client, db: Session):
    justification = "x" * 2000

    response = _request(
        coordinator_client,
        event_id=Events.APPROVED,
        venue_id=Venues.EXHIBITION_FOYER,
        suitability_override_reason=justification,
    )

    assert response.status_code == 201, response.text
    assert _stored_reason(db, response.json()["id"]) == justification


@pytest.mark.story("11.1", ac=2)
def test_a_justification_of_2001_characters_is_refused(coordinator_client, db: Session):
    before = _booking_count(db, Events.APPROVED)

    response = _request(
        coordinator_client,
        event_id=Events.APPROVED,
        venue_id=Venues.EXHIBITION_FOYER,
        suitability_override_reason="x" * 2001,
    )

    assert response.status_code == 422
    assert _booking_count(db, Events.APPROVED) == before


@pytest.mark.story("11.1", ac=2)
def test_the_justification_is_stored_without_surrounding_spaces(coordinator_client, db: Session):
    response = _request(
        coordinator_client,
        event_id=Events.APPROVED,
        venue_id=Venues.EXHIBITION_FOYER,
        suitability_override_reason=f"  {JUSTIFICATION}\n",
    )

    assert response.status_code == 201, response.text
    assert _stored_reason(db, response.json()["id"]) == JUSTIFICATION


# --- Q9 and the plain path: a venue that suits ---------------------------------------------------
@pytest.mark.story("11.1", ac=2)
def test_a_justification_sent_for_a_suitable_venue_is_not_stored(coordinator_client, db: Session):
    """Decided (Q9): nothing was overridden, so nothing is stored."""
    venue = _venue_suited_to_nimbus(db)

    response = _request(
        coordinator_client,
        event_id=Events.APPROVED,
        venue_id=venue.id,
        suitability_override_reason=JUSTIFICATION,
    )

    assert response.status_code == 201, response.text
    assert response.json()["suitability_override_reason"] is None
    assert _stored_reason(db, response.json()["id"]) is None


@pytest.mark.story("11.1", ac=2)
def test_a_suitable_venue_needs_no_justification(coordinator_client, db: Session):
    venue = _venue_suited_to_nimbus(db)

    response = _request(coordinator_client, event_id=Events.APPROVED, venue_id=venue.id)

    assert response.status_code == 201, response.text
    assert _stored_reason(db, response.json()["id"]) is None


# --- AC5: Unknown is never met; "No venue requirements" is judged on capacity --------------------
@pytest.mark.story("11.1", ac=5)
def test_a_venue_that_recorded_no_layouts_needs_a_justification_for_one(
    coordinator_client, db: Session
):
    """The requirement needs Theatre and the venue recorded no layouts at all: Unknown, which is
    never treated as met."""
    event = _assigned_event(db, expected_attendance=40)
    make_venue_requirement(db, event.id, capacity=40, layout_code="THEATRE")
    venue = make_venue(db, capacity=100)

    refused = _request(coordinator_client, event_id=event.id, venue_id=venue.id)
    accepted = _request(
        coordinator_client,
        event_id=event.id,
        venue_id=venue.id,
        suitability_override_reason=JUSTIFICATION,
    )

    assert refused.status_code == 422
    assert accepted.status_code == 201, accepted.text


@pytest.mark.story("11.1", ac=5)
def test_an_event_with_no_venue_requirements_is_judged_on_capacity_alone(
    coordinator_client, db: Session
):
    """A venue too small for the attendance needs a justification; one big enough does not, even
    though it recorded nothing else at all."""
    event = _assigned_event(db, expected_attendance=100, venue_none_required=True)
    too_small = make_venue(db, capacity=99)
    big_enough = make_venue(db, capacity=100)

    refused = _request(coordinator_client, event_id=event.id, venue_id=too_small.id)
    accepted = _request(coordinator_client, event_id=event.id, venue_id=big_enough.id)

    assert refused.status_code == 422
    assert refused.json()["detail"] == booking_service.JUSTIFICATION_REQUIRED_MESSAGE
    assert accepted.status_code == 201, accepted.text


# --- AC7: requirements that change ------------------------------------------------------------
@pytest.mark.story("11.1", ac=7)
def test_a_venue_that_stopped_suiting_after_the_step_loaded_needs_a_justification_when_sent(
    coordinator_client, db: Session
):
    """The request step read the venue as suitable; the requirement then grew. The request is
    judged as the requirement stands when it is sent."""
    event = _assigned_event(db, expected_attendance=150)
    requirement_id = make_venue_requirement(db, event.id, capacity=60)
    venue = make_venue(db, capacity=80)
    read = coordinator_client.get(
        f"/venues/{venue.id}/suitability", params={"event": str(event.id)}
    )
    db.execute(
        text("UPDATE venue_requirements SET capacity = 120 WHERE id = :id"), {"id": requirement_id}
    )
    db.expire_all()

    response = _request(coordinator_client, event_id=event.id, venue_id=venue.id)

    assert read.status_code == 200, read.text
    assert read.json()["is_suitable"] is True
    assert response.status_code == 422
    assert response.json()["detail"] == booking_service.JUSTIFICATION_REQUIRED_MESSAGE
    assert _booking_count(db, event.id) == 0


@pytest.mark.story("11.1", ac=7)
def test_a_pending_request_keeps_its_justification_after_the_requirements_change(
    coordinator_client, db: Session
):
    """The venue was too small when requested; the requirement then shrank so it would now suit.
    The request is not judged again: its justification stays as it was sent."""
    event = _assigned_event(db, expected_attendance=300)
    requirement_id = make_venue_requirement(db, event.id, capacity=300)
    venue = make_venue(db, capacity=250)
    raised = _request(
        coordinator_client,
        event_id=event.id,
        venue_id=venue.id,
        suitability_override_reason=JUSTIFICATION,
    )
    assert raised.status_code == 201, raised.text

    db.execute(
        text("UPDATE venue_requirements SET capacity = 200 WHERE id = :id"), {"id": requirement_id}
    )
    db.expire_all()
    read = coordinator_client.get(f"{BOOKINGS_PATH}/{raised.json()['id']}")

    assert read.json()["suitability_override_reason"] == JUSTIFICATION


@pytest.mark.story("11.1", ac=7)
def test_a_venue_both_held_and_unsuitable_is_refused_as_held(coordinator_client, db: Session):
    """Availability is checked before suitability: Seminar Room 2.1 does not suit Nimbus, and the
    seeded pending request already holds it on Nimbus's day. With no justification sent, the
    refusal is the hold (409), not the missing justification (422)."""
    before = _booking_count(db, Events.APPROVED)

    response = _request(coordinator_client, event_id=Events.APPROVED, venue_id=Venues.SEMINAR_ROOM)

    assert response.status_code == 409
    assert _booking_count(db, Events.APPROVED) == before


# --- AC3/AC6: who reads the justification ---------------------------------------------------
@pytest.mark.story("11.1", ac=3)
@pytest.mark.story("11.1", ac=6)
def test_venue_staff_read_the_justification_on_the_request(client, login_as, db: Session):
    raised = _request(
        login_as(Users.COORDINATOR),
        event_id=Events.APPROVED,
        venue_id=Venues.EXHIBITION_FOYER,
        suitability_override_reason=JUSTIFICATION,
    )
    assert raised.status_code == 201, raised.text

    read = login_as(Users.VENUE_STAFF).get(f"{BOOKINGS_PATH}/{raised.json()['id']}")

    assert read.status_code == 200
    assert read.json()["suitability_override_reason"] == JUSTIFICATION


@pytest.mark.story("11.1", ac=6)
def test_the_assigned_coordinator_reads_the_justification_on_the_events_bookings(
    coordinator_client, db: Session
):
    """The event page's booking history (``GET /bookings/for-event/{id}``) carries it too."""
    raised = _request(
        coordinator_client,
        event_id=Events.APPROVED,
        venue_id=Venues.EXHIBITION_FOYER,
        suitability_override_reason=JUSTIFICATION,
    )
    assert raised.status_code == 201, raised.text

    history = coordinator_client.get(f"{BOOKINGS_PATH}/for-event/{Events.APPROVED}").json()

    entry = next(each for each in history if each["id"] == raised.json()["id"])
    assert entry["suitability_override_reason"] == JUSTIFICATION


# --- The audit trail ------------------------------------------------------------------------
@pytest.mark.story("11.1", ac=2)
def test_the_audit_entry_records_whether_the_check_was_overridden_but_not_the_text(
    coordinator_client, db: Session
):
    overridden = _request(
        coordinator_client,
        event_id=Events.APPROVED,
        venue_id=Venues.EXHIBITION_FOYER,
        suitability_override_reason=JUSTIFICATION,
    )
    plain = _request(
        coordinator_client, event_id=Events.APPROVED, venue_id=_venue_suited_to_nimbus(db).id
    )

    overridden_details = _audit_details(db, overridden.json()["id"])
    assert overridden_details["suitability_overridden"] is True
    assert JUSTIFICATION not in str(overridden_details)
    assert _audit_details(db, plain.json()["id"])["suitability_overridden"] is False


# --- Story 20.1's notification, around the check -----------------------------------------------
def _notifications_about(db: Session, event_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    return db.execute(
        text(
            "SELECT recipient_id, notification_type FROM notifications WHERE event_id = :id"
            " ORDER BY recipient_id"
        ),
        {"id": event_id},
    ).all()


def _request_audits_for(db: Session, event_id: uuid.UUID) -> int:
    return db.scalar(
        text(
            "SELECT count(*) FROM audit_log"
            " WHERE action = 'BOOKING_REQUESTED' AND details->>'event_id' = :id"
        ),
        {"id": str(event_id)},
    )


@pytest.mark.story("11.1", ac=2)
@pytest.mark.story("11.1", ac=7)
def test_a_request_refused_for_its_justification_tells_nobody_and_an_override_tells_staff_once(
    coordinator_client, db: Session
):
    """Read straight after the refusal, before any rollback, so a notification or audit entry
    written ahead of the check shows up even if it was only flushed."""
    refused = _request(
        coordinator_client, event_id=Events.APPROVED, venue_id=Venues.EXHIBITION_FOYER
    )

    assert refused.status_code == 422
    assert _notifications_about(db, Events.APPROVED) == []
    assert _request_audits_for(db, Events.APPROVED) == 0

    overridden = _request(
        coordinator_client,
        event_id=Events.APPROVED,
        venue_id=Venues.EXHIBITION_FOYER,
        suitability_override_reason=JUSTIFICATION,
    )

    assert overridden.status_code == 201, overridden.text
    active_venue_staff = db.scalars(
        text("SELECT id FROM users WHERE role_code = 'VENUE_STAFF' AND is_active ORDER BY id")
    ).all()
    assert _notifications_about(db, Events.APPROVED) == [
        (member, "BOOKING_REQUESTED") for member in active_venue_staff
    ]
    assert _request_audits_for(db, Events.APPROVED) == 1
