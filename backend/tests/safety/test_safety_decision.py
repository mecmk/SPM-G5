"""Story 21.2 - the Safety Officer records the decision (AC2-AC5, AC8-AC10, AC15, AC16, AC20).

AC2  The review page lists the review factors; each decision keeps who, when, findings
     and the facts reviewed, and every round is kept in order.
AC3  Approve returns the event to Planning; it is never confirmed by the officer.
AC4  Request changes returns it to Planning with findings: a factor, what must change, and
     optionally the arrangement to rebook. The event page shows them.
AC5  Approve and Request changes are the only outcomes; anything else writes nothing.
AC8  The coordinator and organiser are told of each decision, the officer is not.
AC9  A decision has no notes.
AC10 Request changes needs at least one finding, each valid; Approve carries none.
AC15 With no coordinator, the decision is recorded and only the organiser told.
AC16 Only a Safety Officer may decide.
AC20 Not awaiting is a 409, unknown a 404, and a second decision writes nothing.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.bookings.models import BookingStatus
from app.events.models import (
    EquipmentRequestStatus,
    Event,
    EventStatus,
    EventStatusHistory,
)
from app.notifications.models import Notification
from app.safety.models import EventSafetyReview, SafetyReviewOutcome
from tests.support.factories import make_secured_event
from tests.support.seed import Users, Venues

APPROVE = {"outcome": SafetyReviewOutcome.APPROVED, "findings": []}
FINDING = {
    "factor_code": "EMERGENCY_ACCESS",
    "required_change": "Keep the north fire exit clear of the stage.",
    "arrangement": None,
}
CHANGES = {
    "outcome": SafetyReviewOutcome.CHANGES_REQUESTED,
    "findings": [
        FINDING,
        {
            "factor_code": "CAPACITY_AND_LAYOUT",
            "required_change": "Book a room that seats 300 in theatre layout.",
            "arrangement": "VENUE_BOOKINGS",
        },
    ],
}


def _decision_path(event_id: uuid.UUID) -> str:
    return f"/safety-checks/{event_id}/decision"


@pytest.fixture
def safety_client(login_as):
    return login_as(Users.SAFETY_OFFICER)


@pytest.fixture
def awaiting(db: Session):
    return make_secured_event(db, status=EventStatus.AWAITING_SAFETY_CHECK)


def _reviews(db: Session, event_id: uuid.UUID) -> list[EventSafetyReview]:
    db.expire_all()
    return list(
        db.scalars(
            select(EventSafetyReview)
            .where(EventSafetyReview.event_id == event_id)
            .order_by(EventSafetyReview.reviewed_at)
        )
    )


def _recipients(db: Session, event_id: uuid.UUID, kind: str) -> set[uuid.UUID]:
    return set(
        db.scalars(
            select(Notification.recipient_id).where(
                Notification.event_id == event_id, Notification.notification_type == kind
            )
        )
    )


def _status(db: Session, event: Event) -> str:
    db.refresh(event)
    return event.status


# --- AC2: the factors, and what each decision keeps ---------------------------------------------
@pytest.mark.story("21.2", ac=2)
def test_review_page_lists_the_factors_in_order(safety_client, awaiting):
    response = safety_client.get(f"/safety-checks/{awaiting.event.id}")

    assert response.status_code == 200, response.text
    assert [factor["name"] for factor in response.json()["factors"]] == [
        "Expected attendance",
        "Venue capacity and layout",
        "Emergency access",
        "Accessibility requirements",
        "Equipment placement",
        "Crowd movement",
        "Known venue restrictions",
    ]


@pytest.mark.story("21.2", ac=2)
@pytest.mark.parametrize("payload", [APPROVE, CHANGES])
def test_each_outcome_keeps_who_when_and_facts(safety_client, db: Session, awaiting, payload):
    response = safety_client.post(_decision_path(awaiting.event.id), json=payload)

    assert response.status_code == 200, response.text
    (review,) = _reviews(db, awaiting.event.id)
    assert review.outcome == payload["outcome"]
    assert review.reviewed_by_id == Users.SAFETY_OFFICER.id
    assert review.reviewed_at is not None
    assert review.facts["expected_attendance"] == awaiting.event.expected_attendance
    assert [venue["id"] for venue in review.facts["venues"]] == [str(Venues.GRAND_HALL)]
    history = db.scalar(
        select(EventStatusHistory).where(EventStatusHistory.event_id == awaiting.event.id)
    )
    assert history is not None
    assert history.from_status == EventStatus.AWAITING_SAFETY_CHECK
    assert history.changed_by_id == Users.SAFETY_OFFICER.id
    assert history.reason is None


@pytest.mark.story("21.2", ac=2)
def test_rounds_are_listed_newest_first_with_their_findings(login_as, db, awaiting):
    """The client holds one session, so each step signs in as whoever acts."""
    login_as(Users.SAFETY_OFFICER).post(_decision_path(awaiting.event.id), json=CHANGES)
    awaiting.booking.expected_attendance += 1
    db.flush()
    login_as(Users.COORDINATOR).post(f"/safety-checks/{awaiting.event.id}/request", json={})
    safety_client = login_as(Users.SAFETY_OFFICER)
    safety_client.post(_decision_path(awaiting.event.id), json=APPROVE)

    reviews = safety_client.get(f"/safety-checks/{awaiting.event.id}").json()["previous_reviews"]

    assert [review["outcome"] for review in reviews] == ["APPROVED", "CHANGES_REQUESTED"]
    assert reviews[1]["findings"] == [
        {
            "factor_code": "EMERGENCY_ACCESS",
            "factor_name": "Emergency access",
            "required_change": "Keep the north fire exit clear of the stage.",
            "arrangement": None,
        },
        {
            "factor_code": "CAPACITY_AND_LAYOUT",
            "factor_name": "Venue capacity and layout",
            "required_change": "Book a room that seats 300 in theatre layout.",
            "arrangement": "VENUE_BOOKINGS",
        },
    ]
    assert reviews[1]["flagged_arrangements"] == ["VENUE_BOOKINGS"]


# --- AC3: approve --------------------------------------------------------------------------------
@pytest.mark.story("21.2", ac=3)
def test_approve_returns_the_event_to_planning(safety_client, db: Session, awaiting):
    response = safety_client.post(_decision_path(awaiting.event.id), json=APPROVE)

    assert response.status_code == 200, response.text
    assert _status(db, awaiting.event) == EventStatus.PLANNING
    assert response.json()["status"] == EventStatus.PLANNING


@pytest.mark.story("21.2", ac=3)
def test_approve_offers_the_coordinator_confirm(login_as, awaiting):
    login_as(Users.SAFETY_OFFICER).post(_decision_path(awaiting.event.id), json=APPROVE)

    summary = login_as(Users.COORDINATOR).get(f"/events/{awaiting.event.id}/safety-review").json()

    assert summary["latest_review"]["outcome"] == "APPROVED"
    assert summary["confirm_blockers"] == []


# --- AC4: request changes ------------------------------------------------------------------------
@pytest.mark.story("21.2", ac=4)
def test_changes_return_to_planning_and_leave_arrangements(safety_client, db: Session, awaiting):
    response = safety_client.post(_decision_path(awaiting.event.id), json=CHANGES)

    assert response.status_code == 200, response.text
    assert _status(db, awaiting.event) == EventStatus.PLANNING
    db.refresh(awaiting.booking)
    db.refresh(awaiting.equipment)
    assert awaiting.booking.status == BookingStatus.APPROVED
    assert awaiting.equipment.status == EquipmentRequestStatus.ACCEPTED


@pytest.mark.story("21.2", ac=4)
@pytest.mark.parametrize("viewer", [Users.COORDINATOR, Users.ORGANISER])
def test_event_page_shows_the_findings(safety_client, login_as, awaiting, viewer):
    safety_client.post(_decision_path(awaiting.event.id), json=CHANGES)

    response = login_as(viewer).get(f"/events/{awaiting.event.id}/safety-review")

    assert response.status_code == 200, response.text
    latest = response.json()["latest_review"]
    assert latest["outcome"] == "CHANGES_REQUESTED"
    assert [f["required_change"] for f in latest["findings"]] == [
        "Keep the north fire exit clear of the stage.",
        "Book a room that seats 300 in theatre layout.",
    ]
    assert latest["flagged_arrangements"] == ["VENUE_BOOKINGS"]


@pytest.mark.story("21.2", ac=4)
def test_only_the_assigned_coordinator_gets_blockers(safety_client, login_as, awaiting):
    safety_client.post(_decision_path(awaiting.event.id), json=CHANGES)

    organiser_view = login_as(Users.ORGANISER).get(f"/events/{awaiting.event.id}/safety-review")

    assert organiser_view.json()["request_blockers"] is None
    assert organiser_view.json()["confirm_blockers"] is None


# --- AC5: only approve or request changes --------------------------------------------------------
@pytest.mark.story("21.2", ac=5)
def test_reject_is_not_an_outcome(safety_client, db: Session, awaiting):
    payload = {"outcome": "REJECTED", "findings": []}

    response = safety_client.post(_decision_path(awaiting.event.id), json=payload)

    assert response.status_code == 422
    assert _reviews(db, awaiting.event.id) == []
    assert _status(db, awaiting.event) == EventStatus.AWAITING_SAFETY_CHECK
    db.refresh(awaiting.booking)
    db.refresh(awaiting.equipment)
    assert awaiting.booking.status == BookingStatus.APPROVED
    assert awaiting.equipment.status == EquipmentRequestStatus.ACCEPTED


# --- AC8, AC15: who is told ----------------------------------------------------------------------
@pytest.mark.story("21.2", ac=8)
@pytest.mark.parametrize(
    ("payload", "kind"),
    [
        (APPROVE, "SAFETY_APPROVED"),
        (CHANGES, "SAFETY_CHANGES_REQUESTED"),
    ],
)
def test_coordinator_and_organiser_are_told(safety_client, db: Session, awaiting, payload, kind):
    safety_client.post(_decision_path(awaiting.event.id), json=payload)

    assert _recipients(db, awaiting.event.id, kind) == {Users.COORDINATOR.id, Users.ORGANISER.id}


@pytest.mark.story("21.2", ac=15)
def test_no_coordinator_only_the_organiser_is_told(safety_client, db: Session):
    secured = make_secured_event(
        db, status=EventStatus.AWAITING_SAFETY_CHECK, assigned_coordinator_id=None
    )

    response = safety_client.post(_decision_path(secured.event.id), json=CHANGES)

    assert response.status_code == 200, response.text
    assert len(_reviews(db, secured.event.id)) == 1
    assert _recipients(db, secured.event.id, "SAFETY_CHANGES_REQUESTED") == {Users.ORGANISER.id}


# --- AC9: no notes -------------------------------------------------------------------------------
@pytest.mark.story("21.2", ac=9)
def test_the_review_has_no_notes(safety_client, awaiting):
    safety_client.post(_decision_path(awaiting.event.id), json=CHANGES)

    review = safety_client.get(f"/safety-checks/{awaiting.event.id}").json()["previous_reviews"][0]

    assert "notes" not in review


@pytest.mark.story("21.2", ac=10)
@pytest.mark.parametrize(("length", "expected"), [(2000, 200), (2001, 422)])
def test_required_change_length_limit(safety_client, awaiting, length, expected):
    payload = {**CHANGES, "findings": [{**FINDING, "required_change": "x" * length}]}

    assert (
        safety_client.post(_decision_path(awaiting.event.id), json=payload).status_code == expected
    )


# --- AC10: findings ------------------------------------------------------------------------------
@pytest.mark.story("21.2", ac=10)
@pytest.mark.parametrize(
    "payload",
    [
        {**CHANGES, "findings": []},
        {**CHANGES, "findings": [{**FINDING, "factor_code": "NOT_A_FACTOR"}]},
        {**CHANGES, "findings": [{**FINDING, "arrangement": "CATERING"}]},
        {**CHANGES, "findings": [{**FINDING, "required_change": "   "}]},
        {**APPROVE, "findings": [FINDING]},
    ],
    ids=["none", "unknown-factor", "bad-arrangement", "blank-change", "on-approve"],
)
def test_invalid_findings_are_refused(safety_client, db: Session, awaiting, payload):
    db.commit()  # keep the setup when a refusal from the database rolls back
    response = safety_client.post(_decision_path(awaiting.event.id), json=payload)

    assert response.status_code == 422, response.text
    assert _reviews(db, awaiting.event.id) == []
    assert _status(db, awaiting.event) == EventStatus.AWAITING_SAFETY_CHECK


# --- AC16: who may decide ------------------------------------------------------------------------
@pytest.mark.story("21.2", ac=16)
@pytest.mark.parametrize(
    "user", [Users.COORDINATOR, Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT]
)
def test_other_roles_cannot_decide(login_as, db: Session, awaiting, user):
    response = login_as(user).post(_decision_path(awaiting.event.id), json=APPROVE)

    assert response.status_code == 403
    assert _reviews(db, awaiting.event.id) == []


@pytest.mark.story("21.2", ac=18)
def test_signed_out_cannot_decide(client, awaiting):
    assert client.post(_decision_path(awaiting.event.id), json=APPROVE).status_code == 401


# --- AC20: conflicts -----------------------------------------------------------------------------
@pytest.mark.story("21.2", ac=20)
def test_event_not_awaiting_is_refused(safety_client, db: Session):
    secured = make_secured_event(db)

    response = safety_client.post(_decision_path(secured.event.id), json=APPROVE)

    assert response.status_code == 409
    assert _reviews(db, secured.event.id) == []


@pytest.mark.story("21.2", ac=20)
def test_unknown_event_is_not_found(safety_client):
    assert safety_client.post(_decision_path(uuid.uuid4()), json=APPROVE).status_code == 404


@pytest.mark.story("21.2", ac=20)
def test_second_decision_is_refused_and_writes_nothing(safety_client, db: Session, awaiting):
    assert safety_client.post(_decision_path(awaiting.event.id), json=APPROVE).status_code == 200

    response = safety_client.post(_decision_path(awaiting.event.id), json=CHANGES)

    assert response.status_code == 409
    assert len(_reviews(db, awaiting.event.id)) == 1
    assert _status(db, awaiting.event) == EventStatus.PLANNING


@pytest.mark.story("21.2", ac=20)
def test_status_changed_just_before_the_update_writes_nothing(
    safety_client, db: Session, awaiting, monkeypatch
):
    """Another request cancels the event after this one read it, before its update."""
    from app.safety import service

    real = service.current_facts

    def facts_then_cancel(db_: Session, event: Event):
        facts = real(db_, event)
        db_.execute(update(Event).where(Event.id == event.id).values(status=EventStatus.CANCELLED))
        return facts

    monkeypatch.setattr(service, "current_facts", facts_then_cancel)
    db.commit()  # keep the setup when the refused request rolls back

    response = safety_client.post(_decision_path(awaiting.event.id), json=APPROVE)

    assert response.status_code == 409
    assert (
        db.scalar(
            select(func.count())
            .select_from(EventSafetyReview)
            .where(EventSafetyReview.event_id == awaiting.event.id)
        )
        == 0
    )
