"""Story 4.1 - be: display the coordinator review queue.

AC1 The queue lists all submitted requests not yet decided.
AC2 Each entry shows event name, organiser, proposed date, and submission date.
AC3 The queue can be ordered by submission date or proposed event date.
AC4 Drafts and already-decided requests do not appear.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.events.models import EventStatus
from tests.support.factories import make_event
from tests.support.seed import Events, Users


# --- AC1: which events appear -------------------------------------------------------------
@pytest.mark.story("4.1", ac=1)
def test_seeded_submitted_event_is_listed(coordinator_client):
    ids = [row["id"] for row in coordinator_client.get("/events/review-queue").json()]
    assert str(Events.SUBMITTED) in ids


@pytest.mark.story("4.1", ac=1)
@pytest.mark.parametrize("status", [EventStatus.UNDER_REVIEW, EventStatus.CLARIFICATION_REQUESTED])
def test_events_awaiting_review_are_listed(coordinator_client, db: Session, status):
    event = make_event(db, status=status)

    ids = [row["id"] for row in coordinator_client.get("/events/review-queue").json()]

    assert str(event.id) in ids


# --- AC2: entry shape ----------------------------------------------------------------------
@pytest.mark.story("4.1", ac=2)
def test_entry_shows_name_organiser_and_dates(coordinator_client):
    body = coordinator_client.get("/events/review-queue").json()
    entry = next(row for row in body if row["id"] == str(Events.SUBMITTED))

    assert entry["name"] == "Data Literacy Workshop"
    assert entry["organiser_name"] == Users.ORGANISER.full_name
    assert entry["starts_at"].startswith("2026-11-18")
    assert entry["submitted_at"].startswith("2026-09-08")


@pytest.mark.story("4.1", ac=2)
def test_entry_carries_the_cover_image_url(coordinator_client, db: Session):
    event = make_event(db, cover_image_url="/images/events/test.svg")

    body = coordinator_client.get("/events/review-queue").json()
    entry = next(row for row in body if row["id"] == str(event.id))

    assert entry["cover_image_url"] == "/images/events/test.svg"


# --- AC3: ordering ---------------------------------------------------------------------------
@pytest.mark.story("4.1", ac=3)
def test_default_order_is_by_submission_date(coordinator_client, db: Session):
    # Submitted after the seeded event, but proposed to happen earlier.
    later_submission = make_event(
        db,
        starts_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
        ends_at=datetime(2026, 10, 1, 17, 0, tzinfo=UTC),
        submitted_at=datetime(2026, 9, 12, 9, 0, tzinfo=UTC),
    )

    ids = [row["id"] for row in coordinator_client.get("/events/review-queue").json()]

    assert ids.index(str(Events.SUBMITTED)) < ids.index(str(later_submission.id))


@pytest.mark.story("4.1", ac=3)
def test_sort_by_starts_at_orders_by_proposed_date(coordinator_client, db: Session):
    # Submitted after the seeded event, but proposed to happen earlier.
    earlier_event = make_event(
        db,
        starts_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
        ends_at=datetime(2026, 10, 1, 17, 0, tzinfo=UTC),
        submitted_at=datetime(2026, 9, 12, 9, 0, tzinfo=UTC),
    )

    response = coordinator_client.get("/events/review-queue?sort=starts_at")
    ids = [row["id"] for row in response.json()]

    assert ids.index(str(earlier_event.id)) < ids.index(str(Events.SUBMITTED))


@pytest.mark.story("4.1", ac=3)
def test_unknown_sort_value_is_rejected(coordinator_client):
    assert coordinator_client.get("/events/review-queue?sort=name").status_code == 422


# --- AC4: drafts and decided requests are hidden --------------------------------------------
@pytest.mark.story("4.1", ac=4)
def test_drafts_and_decided_seed_events_are_hidden(coordinator_client):
    ids = [row["id"] for row in coordinator_client.get("/events/review-queue").json()]

    assert str(Events.DRAFT) not in ids
    assert str(Events.APPROVED) not in ids
    assert str(Events.REJECTED) not in ids


@pytest.mark.story("4.1", ac=4)
@pytest.mark.parametrize(
    "status",
    [
        EventStatus.PLANNING,
        EventStatus.CONFIRMED,
        EventStatus.COMPLETED,
        EventStatus.CANCELLED,
    ],
)
def test_other_decided_statuses_are_hidden(coordinator_client, db: Session, status):
    event = make_event(db, status=status)

    ids = [row["id"] for row in coordinator_client.get("/events/review-queue").json()]

    assert str(event.id) not in ids


# --- coordinator filter ----------------------------------------------------------------------
@pytest.mark.story("4.1", ac=1)
def test_coordinator_filter_narrows_the_queue(coordinator_client, db: Session):
    mine = make_event(
        db, status=EventStatus.UNDER_REVIEW, assigned_coordinator_id=Users.COORDINATOR.id
    )
    someone_elses = make_event(
        db, status=EventStatus.UNDER_REVIEW, assigned_coordinator_id=Users.COORDINATOR_2.id
    )
    unassigned = make_event(db, status=EventStatus.UNDER_REVIEW)

    response = coordinator_client.get(f"/events/review-queue?coordinator_id={Users.COORDINATOR.id}")
    ids = [row["id"] for row in response.json()]

    assert str(mine.id) in ids
    assert str(someone_elses.id) not in ids
    assert str(unassigned.id) not in ids
    assert str(Events.SUBMITTED) in ids  # assigned to coordinator 1 in the seed


@pytest.mark.story("4.1", ac=4)
def test_coordinator_filter_still_hides_decided_events(coordinator_client, db: Session):
    event = make_event(
        db, status=EventStatus.APPROVED, assigned_coordinator_id=Users.COORDINATOR.id
    )

    response = coordinator_client.get(f"/events/review-queue?coordinator_id={Users.COORDINATOR.id}")

    assert str(event.id) not in [row["id"] for row in response.json()]


@pytest.mark.story("4.1")
def test_malformed_coordinator_id_is_rejected(coordinator_client):
    response = coordinator_client.get("/events/review-queue?coordinator_id=not-a-uuid")
    assert response.status_code == 422


@pytest.mark.story("4.1")
def test_unknown_coordinator_id_returns_empty_list(coordinator_client):
    response = coordinator_client.get(f"/events/review-queue?coordinator_id={uuid.uuid4()}")
    assert response.json() == []


# --- access control --------------------------------------------------------------------------
@pytest.mark.story("4.1")
@pytest.mark.story("1.2", ac=4)
@pytest.mark.parametrize(
    "user", [Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE]
)
def test_other_roles_cannot_see_the_queue(client, user):
    client.login(user)
    assert client.get("/events/review-queue").status_code == 403


@pytest.mark.story("4.1")
def test_signed_out_user_is_rejected(client):
    assert client.get("/events/review-queue").status_code == 401
