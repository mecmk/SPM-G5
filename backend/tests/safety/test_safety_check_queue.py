"""Story 21.1 - the Safety Officer's queue of events awaiting the safety check.

AC2 The queue lists only events Awaiting Safety Check, oldest first by when each entered the
    status, with name, dates, expected attendance, approved venues and status.
AC3 An event's detail shows everything that affects safety: attendance, each approved venue,
    accessibility needs, accepted equipment and previous reviews.
AC4 A venue whose capacity is below the expected attendance is flagged.
AC5 What changed since the last review is listed, and unrecorded details stay null.
AC6 Only the Safety Officer may see it, and the officer cannot edit, book or manage equipment.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.bookings.models import BookingStatus
from app.events.models import EquipmentRequestStatus, Event, EventStatus, EventStatusHistory
from app.safety.models import EventSafetyReview, SafetyReviewOutcome
from tests.support.factories import (
    make_booking,
    make_equipment_item,
    make_equipment_type,
    make_event,
)
from tests.support.seed import Bookings, EquipmentItems, Events, SafetyReviews, Users, Venues

QUEUE_PATH = "/safety-checks"


def _detail_path(event_id: uuid.UUID) -> str:
    return f"{QUEUE_PATH}/{event_id}"


def _entered_check(db: Session, event: Event, at: datetime) -> None:
    db.add(
        EventStatusHistory(
            event_id=event.id,
            from_status=EventStatus.PLANNING,
            to_status=EventStatus.AWAITING_SAFETY_CHECK,
            changed_at=at,
        )
    )
    db.flush()


def _ids(client) -> list[str]:
    response = client.get(QUEUE_PATH)
    assert response.status_code == 200, response.text
    return [row["id"] for row in response.json()]


@pytest.fixture
def safety_client(login_as):
    return login_as(Users.SAFETY_OFFICER)


# --- AC2: which events, in what order ----------------------------------------------------------
@pytest.mark.story("21.1", ac=2)
def test_queue_lists_the_awaiting_events_oldest_first(safety_client):
    """The concert entered on 10 Oct; the book fair first entered on 6 Oct but was sent back and
    re-entered on 11 Oct, so its latest entry counts."""
    assert _ids(safety_client) == [str(Events.HARBOUR_CONCERT), str(Events.BOOK_FAIR)]


@pytest.mark.story("21.1", ac=2)
def test_queue_orders_by_when_each_event_entered_the_check(safety_client, db: Session):
    earliest = make_event(db, status=EventStatus.AWAITING_SAFETY_CHECK)
    _entered_check(db, earliest, datetime(2026, 10, 9, 1, 0, tzinfo=UTC))
    latest = make_event(db, status=EventStatus.AWAITING_SAFETY_CHECK)
    _entered_check(db, latest, datetime(2026, 10, 12, 1, 0, tzinfo=UTC))

    assert _ids(safety_client) == [
        str(earliest.id),
        str(Events.HARBOUR_CONCERT),
        str(Events.BOOK_FAIR),
        str(latest.id),
    ]


@pytest.mark.story("21.1", ac=2)
def test_entry_shows_name_dates_attendance_venues_and_status(safety_client):
    entry = safety_client.get(QUEUE_PATH).json()[0]

    assert entry == {
        "id": str(Events.HARBOUR_CONCERT),
        "name": "Harbour Lights Concert",
        "starts_at": "2028-08-16T10:00:00Z",
        "ends_at": "2028-08-16T14:00:00Z",
        "expected_attendance": 300,
        "venue_names": ["Exhibition Foyer"],
        "status": EventStatus.AWAITING_SAFETY_CHECK,
    }


@pytest.mark.story("21.1", ac=2)
@pytest.mark.parametrize(
    "status",
    [
        value
        for name, value in vars(EventStatus).items()
        if name.isupper() and value != EventStatus.AWAITING_SAFETY_CHECK
    ],
)
def test_events_in_other_statuses_are_left_out(safety_client, db: Session, status):
    event = make_event(db, status=status)

    assert str(event.id) not in _ids(safety_client)


@pytest.mark.story("21.1", ac=2)
def test_empty_queue_returns_an_empty_list(safety_client, db: Session):
    db.execute(
        update(Event)
        .where(Event.status == EventStatus.AWAITING_SAFETY_CHECK)
        .values(status=EventStatus.PLANNING)
    )

    assert _ids(safety_client) == []


@pytest.mark.story("21.1", ac=2)
def test_only_approved_bookings_count_as_venues(safety_client, db: Session):
    event = make_event(db, status=EventStatus.AWAITING_SAFETY_CHECK)
    _entered_check(db, event, datetime(2026, 10, 12, 1, 0, tzinfo=UTC))
    starts_at = datetime(2029, 3, 1, 1, 0, tzinfo=UTC)
    ends_at = datetime(2029, 3, 1, 9, 0, tzinfo=UTC)
    for venue_id, status, extra in (
        (Venues.BOARDROOM, BookingStatus.APPROVED, {}),
        (Venues.SEMINAR_ROOM, BookingStatus.PENDING, {}),
        (Venues.GRAND_HALL, BookingStatus.WITHDRAWN, {}),
        (Venues.EXHIBITION_FOYER, BookingStatus.EXPIRED, {"hold_expires_at": starts_at}),
    ):
        make_booking(
            db,
            event_id=event.id,
            venue_id=venue_id,
            starts_at=starts_at,
            ends_at=ends_at,
            status=status,
            **extra,
        )

    entry = next(row for row in safety_client.get(QUEUE_PATH).json() if row["id"] == str(event.id))

    assert entry["venue_names"] == ["Boardroom 3.4"]


# --- AC6: only the Safety Officer ---------------------------------------------------------------
@pytest.mark.story("21.1", ac=6)
@pytest.mark.parametrize(
    "user", [user for user in Users.ONE_PER_ROLE if user is not Users.SAFETY_OFFICER]
)
def test_other_roles_cannot_see_the_queue(client, user):
    client.login(user)

    assert client.get(QUEUE_PATH).status_code == 403


@pytest.mark.story("21.1", ac=6)
def test_signed_out_user_is_rejected(client):
    assert client.get(QUEUE_PATH).status_code == 401


@pytest.mark.story("21.1", ac=6)
@pytest.mark.parametrize(
    "user", [user for user in Users.ONE_PER_ROLE if user is not Users.SAFETY_OFFICER]
)
def test_other_roles_cannot_see_an_events_check(client, user):
    client.login(user)

    assert client.get(_detail_path(Events.HARBOUR_CONCERT)).status_code == 403


@pytest.mark.story("21.1", ac=6)
def test_signed_out_user_cannot_see_an_events_check(client):
    assert client.get(_detail_path(Events.HARBOUR_CONCERT)).status_code == 401


@pytest.mark.story("21.1", ac=6)
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("patch", f"/events/{Events.HARBOUR_CONCERT}/routine-information"),
        ("post", "/bookings"),
        ("post", f"/bookings/{Bookings.PENDING_GRAND_HALL}/approve"),
        ("post", f"/events/{Events.HARBOUR_CONCERT}/equipment"),
        ("post", f"/equipment-requests/{EquipmentItems.SHOWCASE_SPEAKERS}/decision"),
    ],
)
def test_safety_officer_cannot_edit_book_or_manage_equipment(safety_client, method, path):
    assert safety_client.request(method, path, json={}).status_code == 403


# --- AC3: what the detail shows -----------------------------------------------------------------
@pytest.mark.story("21.1", ac=3)
def test_detail_shows_attendance_venues_accessibility_and_equipment(safety_client):
    response = safety_client.get(_detail_path(Events.HARBOUR_CONCERT))

    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["name"] == "Harbour Lights Concert"
    assert detail["description"] == "An evening concert on the foyer floor."
    assert detail["expected_attendance"] == 300
    [venue] = detail["venues"]
    assert venue["venue"]["id"] == str(Venues.EXHIBITION_FOYER)
    assert venue["venue"]["capacity"] == 250
    assert venue["layout"] == "Standing / reception"
    assert detail["accessibility_needs"] == [
        {
            "code": "WHEELCHAIR_ACCESS",
            "name": "Wheelchair access",
            "notes": "A ramp up to the viewing area",
        }
    ]
    [equipment] = detail["equipment"]
    assert equipment["id"] == str(EquipmentItems.CONCERT_SPEAKERS)
    assert equipment["equipment_type_name"] == "Portable speaker set"
    assert equipment["quantity"] == 2
    assert equipment["technical_notes"] == "Stage left and right; cables taped down"
    assert detail["previous_reviews"] == []


@pytest.mark.story("21.1", ac=3)
@pytest.mark.parametrize(
    "status",
    [
        value
        for name, value in vars(EquipmentRequestStatus).items()
        if name.isupper() and value != EquipmentRequestStatus.ACCEPTED
    ],
)
def test_only_accepted_equipment_is_shown(safety_client, db: Session, status):
    make_equipment_item(
        db,
        event=db.get(Event, Events.HARBOUR_CONCERT),
        equipment_type=make_equipment_type(db),
        quantity=1,
        status=status,
        is_held=False,
    )

    equipment = safety_client.get(_detail_path(Events.HARBOUR_CONCERT)).json()["equipment"]

    assert [item["id"] for item in equipment] == [str(EquipmentItems.CONCERT_SPEAKERS)]


@pytest.mark.story("21.1", ac=3)
def test_previous_reviews_are_newest_first(safety_client, db: Session):
    newer = EventSafetyReview(
        event_id=Events.BOOK_FAIR,
        reviewed_by_id=Users.SAFETY_OFFICER.id,
        reviewed_at=datetime(2026, 10, 8, 1, 0, tzinfo=UTC),
        outcome=SafetyReviewOutcome.CHANGES_REQUESTED,
        notes=None,
        facts={},
    )
    db.add(newer)
    db.flush()

    reviews = safety_client.get(_detail_path(Events.BOOK_FAIR)).json()["previous_reviews"]

    assert [review["id"] for review in reviews] == [
        str(newer.id),
        str(SafetyReviews.BOOK_FAIR_CHANGES),
    ]
    assert reviews[1] == {
        "id": str(SafetyReviews.BOOK_FAIR_CHANGES),
        "reviewed_at": "2026-10-07T07:00:00Z",
        "reviewed_by_name": "Sam Safety",
        "outcome": SafetyReviewOutcome.CHANGES_REQUESTED,
        "notes": "Confirm the attendance and the microphones.",
    }


@pytest.mark.story("21.1", ac=3)
def test_event_not_awaiting_the_check_is_not_found(safety_client, db: Session):
    event = make_event(db, status=EventStatus.PLANNING)

    assert safety_client.get(_detail_path(event.id)).status_code == 404


@pytest.mark.story("21.1", ac=3)
def test_unknown_event_is_not_found(safety_client):
    assert safety_client.get(_detail_path(uuid.uuid4())).status_code == 404


# --- AC4: over capacity -------------------------------------------------------------------------
@pytest.mark.story("21.1", ac=4)
@pytest.mark.parametrize(("attendance", "is_over"), [(16, False), (17, True)])
def test_venue_is_over_capacity_only_above_its_capacity(
    safety_client, db: Session, attendance, is_over
):
    """The Boardroom seats 16."""
    event = make_event(db, status=EventStatus.AWAITING_SAFETY_CHECK, expected_attendance=attendance)
    make_booking(
        db,
        event_id=event.id,
        venue_id=Venues.BOARDROOM,
        starts_at=datetime(2029, 3, 1, 1, 0, tzinfo=UTC),
        ends_at=datetime(2029, 3, 1, 9, 0, tzinfo=UTC),
        status=BookingStatus.APPROVED,
    )

    [venue] = safety_client.get(_detail_path(event.id)).json()["venues"]

    assert venue["over_capacity"] is is_over


# --- AC5: changes since the last review, and what was never recorded ----------------------------
@pytest.mark.story("21.1", ac=5)
def test_changes_list_only_the_facts_that_changed(safety_client):
    """The book fair was reviewed at 120 people and two microphones; it now has 150 and four."""
    detail = safety_client.get(_detail_path(Events.BOOK_FAIR)).json()
    changes = detail["changes_since_last_review"]

    assert [change["fact"] for change in changes] == ["expected_attendance", "equipment"]
    assert changes[0] == {"fact": "expected_attendance", "before": 120, "after": 150}


@pytest.mark.story("21.1", ac=5)
def test_changed_description_is_listed(safety_client, db: Session):
    """The idea itself is part of the check, so a rewritten description counts as a change."""
    db.get(Event, Events.BOOK_FAIR).description = "Publisher stalls and a fireworks finale."
    db.flush()

    changes = safety_client.get(_detail_path(Events.BOOK_FAIR)).json()["changes_since_last_review"]

    assert {
        "fact": "description",
        "before": "Publisher stalls with author talks through the day.",
        "after": "Publisher stalls and a fireworks finale.",
    } in changes


@pytest.mark.story("21.1", ac=5)
def test_no_changes_without_a_previous_review(safety_client):
    detail = safety_client.get(_detail_path(Events.HARBOUR_CONCERT)).json()

    assert detail["changes_since_last_review"] == []


@pytest.mark.story("21.1", ac=5)
def test_unrecorded_venue_details_stay_null(safety_client):
    """The Exhibition Foyer's operating hours were never recorded."""
    [venue] = safety_client.get(_detail_path(Events.HARBOUR_CONCERT)).json()["venues"]

    assert venue["venue"]["operating_hours_start"] is None
    assert venue["venue"]["operating_hours_end"] is None
