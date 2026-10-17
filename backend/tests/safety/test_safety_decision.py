"""Story 21.2 - the Safety Officer records the decision. The backlog's ACs, as written:

AC2  The officer's review page shows the event's safety facts and the review factors (expected
     attendance, venue capacity and layout, emergency access, accessibility requirements,
     equipment placement, crowd movement, known venue restrictions).
AC3  Approve returns the event to Planning with the approval on record, and the coordinator is
     offered Confirm.
AC4  The officer adds one or more findings, each naming a factor and stating exactly what must
     change, optionally tied to venue bookings or equipment. The event returns to Planning; the
     coordinator and organiser see the findings on the event detail page, with flagged
     venue/equipment sections highlighted.
AC5  Approve and Request changes are the only decisions; any other outcome (e.g. reject) is
     refused and nothing is written.
AC6  [...] Every review round (outcome, findings, facts, who, when) is kept in order and shown to
     the officer, with what changed since the last one.
AC8  Every status change notifies.
AC9  A decision has no free-text notes: the outcome and its findings say it all. Each required
     change is at most 2000 characters.
AC10 Request changes needs at least one finding; each has a known factor and a non-blank required
     change; its arrangement is empty, `VENUE_BOOKINGS` or `EQUIPMENT`. Approve carries no
     findings.
AC15 A decision on an event with no assigned coordinator is still recorded; only the organiser is
     notified.
AC16 Only a Safety Officer records a decision; anyone else gets 403.
AC18 Signed out -> 401 on every new endpoint. The decision form and the coordinator's buttons are
     not shown to anyone else.
AC20 A decision on an event not awaiting the check -> 409; unknown event -> 404. Two decisions at
     once (two officers, double-click) -> one wins, the other 409 with no review written.

A decision carries the ``facts_fingerprint`` of the page the officer read, so the facts stored as
reviewed are the facts the officer saw; if they moved meanwhile, the decision is refused (AC20).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.bookings.models import BookingStatus
from app.common.audit import AuditLog
from app.events.models import (
    EquipmentRequestStatus,
    Event,
    EventStatus,
    EventStatusHistory,
)
from app.notifications.models import Notification
from app.safety.models import EventSafetyReview, SafetyReviewOutcome
from app.safety.service import STATUS_CHANGED_MESSAGE
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


def _decide(client, event_id: uuid.UUID, payload: dict):
    """Post ``payload`` as read from the review page: with that page's ``facts_fingerprint``."""
    page = client.get(f"/safety-checks/{event_id}")
    fingerprint = page.json()["facts_fingerprint"] if page.status_code == 200 else "unread"
    return client.post(_decision_path(event_id), json={**payload, "facts_fingerprint": fingerprint})


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


@pytest.mark.story("21.2", ac=6)
@pytest.mark.parametrize("payload", [APPROVE, CHANGES])
def test_each_outcome_keeps_who_when_and_facts(safety_client, db: Session, awaiting, payload):
    response = _decide(safety_client, awaiting.event.id, payload)

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
    audit = db.scalar(select(AuditLog).where(AuditLog.entity_id == awaiting.event.id))
    assert audit is not None
    assert (audit.action, audit.actor_id) == (
        f"SAFETY_{payload['outcome']}",
        Users.SAFETY_OFFICER.id,
    )


@pytest.mark.story("21.2", ac=6)
def test_rounds_are_listed_newest_first_with_their_findings(login_as, db, awaiting):
    """The client holds one session, so each step signs in as whoever acts."""
    _decide(login_as(Users.SAFETY_OFFICER), awaiting.event.id, CHANGES)
    awaiting.booking.expected_attendance += 1
    db.flush()
    login_as(Users.COORDINATOR).post(f"/safety-checks/{awaiting.event.id}/request", json={})
    safety_client = login_as(Users.SAFETY_OFFICER)
    _decide(safety_client, awaiting.event.id, APPROVE)

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
    response = _decide(safety_client, awaiting.event.id, APPROVE)

    assert response.status_code == 200, response.text
    assert _status(db, awaiting.event) == EventStatus.PLANNING
    assert response.json()["status"] == EventStatus.PLANNING


@pytest.mark.story("21.2", ac=3)
def test_approve_offers_the_coordinator_confirm(login_as, awaiting):
    _decide(login_as(Users.SAFETY_OFFICER), awaiting.event.id, APPROVE)

    summary = login_as(Users.COORDINATOR).get(f"/events/{awaiting.event.id}/safety-review").json()

    assert summary["latest_review"]["outcome"] == "APPROVED"
    assert summary["confirm_blockers"] == []


# --- AC4: request changes ------------------------------------------------------------------------
@pytest.mark.story("21.2", ac=4)
def test_changes_return_to_planning_and_leave_arrangements(safety_client, db: Session, awaiting):
    response = _decide(safety_client, awaiting.event.id, CHANGES)

    assert response.status_code == 200, response.text
    assert _status(db, awaiting.event) == EventStatus.PLANNING
    db.refresh(awaiting.booking)
    db.refresh(awaiting.equipment)
    assert awaiting.booking.status == BookingStatus.APPROVED
    assert awaiting.equipment.status == EquipmentRequestStatus.ACCEPTED


@pytest.mark.story("21.2", ac=4)
@pytest.mark.parametrize("viewer", [Users.COORDINATOR, Users.ORGANISER])
def test_event_page_shows_the_findings(safety_client, login_as, awaiting, viewer):
    _decide(safety_client, awaiting.event.id, CHANGES)

    response = login_as(viewer).get(f"/events/{awaiting.event.id}/safety-review")

    assert response.status_code == 200, response.text
    latest = response.json()["latest_review"]
    assert latest["outcome"] == "CHANGES_REQUESTED"
    assert [f["required_change"] for f in latest["findings"]] == [
        "Keep the north fire exit clear of the stage.",
        "Book a room that seats 300 in theatre layout.",
    ]
    assert latest["flagged_arrangements"] == ["VENUE_BOOKINGS"]


@pytest.mark.story("21.2", ac=18)
@pytest.mark.parametrize("viewer", [Users.ORGANISER, Users.COORDINATOR_2])
def test_only_the_assigned_coordinator_gets_blockers(safety_client, login_as, awaiting, viewer):
    """COORDINATOR_2 may read every event (events:read_all) but does not coordinate this one."""
    _decide(safety_client, awaiting.event.id, CHANGES)

    other_view = login_as(viewer).get(f"/events/{awaiting.event.id}/safety-review")

    assert other_view.status_code == 200, other_view.text
    assert other_view.json()["request_blockers"] is None
    assert other_view.json()["confirm_blockers"] is None


@pytest.mark.story("21.2", ac=18)
def test_the_assigned_coordinator_gets_the_blockers(safety_client, login_as, db, awaiting):
    _decide(safety_client, awaiting.event.id, CHANGES)
    coordinator = login_as(Users.COORDINATOR)
    summary_path = f"/events/{awaiting.event.id}/safety-review"

    assert coordinator.get(summary_path).json()["request_blockers"] == []
    awaiting.booking.status = BookingStatus.WITHDRAWN
    db.flush()
    assert coordinator.get(summary_path).json()["request_blockers"] == [
        "Main venue has no approved venue booking.",
        "No venue is booked.",
    ]


@pytest.mark.story("21.2", ac=18)
def test_signed_out_cannot_read_the_safety_summary(client, awaiting):
    assert client.get(f"/events/{awaiting.event.id}/safety-review").status_code == 401


# --- AC5: only approve or request changes --------------------------------------------------------
@pytest.mark.story("21.2", ac=5)
def test_reject_is_not_an_outcome(safety_client, db: Session, awaiting):
    payload = {"outcome": "REJECTED", "findings": []}

    response = _decide(safety_client, awaiting.event.id, payload)

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
    _decide(safety_client, awaiting.event.id, payload)

    assert _recipients(db, awaiting.event.id, kind) == {Users.COORDINATOR.id, Users.ORGANISER.id}


@pytest.mark.story("21.2", ac=15)
def test_no_coordinator_only_the_organiser_is_told(safety_client, db: Session):
    secured = make_secured_event(
        db, status=EventStatus.AWAITING_SAFETY_CHECK, assigned_coordinator_id=None
    )

    response = _decide(safety_client, secured.event.id, CHANGES)

    assert response.status_code == 200, response.text
    assert len(_reviews(db, secured.event.id)) == 1
    assert _recipients(db, secured.event.id, "SAFETY_CHANGES_REQUESTED") == {Users.ORGANISER.id}


# --- AC9: no notes -------------------------------------------------------------------------------
@pytest.mark.story("21.2", ac=9)
def test_the_review_has_no_notes(safety_client, awaiting):
    _decide(safety_client, awaiting.event.id, CHANGES)

    review = safety_client.get(f"/safety-checks/{awaiting.event.id}").json()["previous_reviews"][0]

    assert "notes" not in review


@pytest.mark.story("21.2", ac=9)
@pytest.mark.parametrize(("length", "expected"), [(2000, 200), (2001, 422)])
def test_required_change_length_limit(safety_client, awaiting, length, expected):
    payload = {**CHANGES, "findings": [{**FINDING, "required_change": "x" * length}]}

    assert _decide(safety_client, awaiting.event.id, payload).status_code == expected


# --- AC10: findings ------------------------------------------------------------------------------
@pytest.mark.story("21.2", ac=10)
def test_a_finding_may_flag_the_equipment(safety_client, awaiting):
    payload = {**CHANGES, "findings": [{**FINDING, "arrangement": "EQUIPMENT"}]}

    response = _decide(safety_client, awaiting.event.id, payload)

    assert response.status_code == 200, response.text
    assert response.json()["previous_reviews"][0]["flagged_arrangements"] == ["EQUIPMENT"]


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
    response = _decide(safety_client, awaiting.event.id, payload)

    assert response.status_code == 422, response.text
    assert _reviews(db, awaiting.event.id) == []
    assert _status(db, awaiting.event) == EventStatus.AWAITING_SAFETY_CHECK


# --- AC16: who may decide ------------------------------------------------------------------------
@pytest.mark.story("21.2", ac=16)
@pytest.mark.parametrize(
    "user", [Users.COORDINATOR, Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT]
)
def test_other_roles_cannot_decide(login_as, db: Session, awaiting, user):
    response = _decide(login_as(user), awaiting.event.id, APPROVE)

    assert response.status_code == 403
    assert _reviews(db, awaiting.event.id) == []


@pytest.mark.story("21.2", ac=18)
def test_signed_out_cannot_decide(client, awaiting):
    assert _decide(client, awaiting.event.id, APPROVE).status_code == 401


# --- AC20: conflicts -----------------------------------------------------------------------------
@pytest.mark.story("21.2", ac=20)
def test_facts_changed_after_the_officer_read_them_is_refused(safety_client, db, awaiting):
    """Story 7.2 lets the coordinator correct the attendance while the event awaits the check."""
    read = safety_client.get(f"/safety-checks/{awaiting.event.id}").json()["facts_fingerprint"]
    awaiting.event.expected_attendance += 180
    db.flush()

    response = safety_client.post(
        _decision_path(awaiting.event.id), json={**APPROVE, "facts_fingerprint": read}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == STATUS_CHANGED_MESSAGE
    assert _reviews(db, awaiting.event.id) == []
    assert _status(db, awaiting.event) == EventStatus.AWAITING_SAFETY_CHECK


@pytest.mark.story("21.2", ac=20)
def test_a_decision_without_the_facts_read_is_refused(safety_client, db, awaiting):
    response = safety_client.post(_decision_path(awaiting.event.id), json=APPROVE)

    assert response.status_code == 422
    assert _reviews(db, awaiting.event.id) == []


@pytest.mark.story("21.2", ac=20)
def test_event_not_awaiting_is_refused(safety_client, db: Session):
    secured = make_secured_event(db)

    response = _decide(safety_client, secured.event.id, APPROVE)

    assert response.status_code == 409
    assert _reviews(db, secured.event.id) == []


@pytest.mark.story("21.2", ac=20)
def test_unknown_event_is_not_found(safety_client):
    assert _decide(safety_client, uuid.uuid4(), APPROVE).status_code == 404


@pytest.mark.story("21.2", ac=20)
def test_second_decision_is_refused_and_writes_nothing(safety_client, db: Session, awaiting):
    assert _decide(safety_client, awaiting.event.id, APPROVE).status_code == 200

    response = _decide(safety_client, awaiting.event.id, CHANGES)

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

    response = _decide(safety_client, awaiting.event.id, APPROVE)

    assert response.status_code == 409
    assert (
        db.scalar(
            select(func.count())
            .select_from(EventSafetyReview)
            .where(EventSafetyReview.event_id == awaiting.event.id)
        )
        == 0
    )
