"""20.2 view and act on notifications
Happy path
1. The bell in the main navigation shows the unread count and opens the user's newest 50
    notifications, newest first, each with its title, message and time; unread notifications stand
    out. Opening a notification goes to its item (the page where the reader acts on it while that
    page still holds it, otherwise the event) and marks it read. Notifications can also be marked
    read one at a time or all at once; marking all leaves unread any notification that arrived after
    the list was opened. The user's own recent actions stay in the same panel, below the
    notifications, and are not counted.
2. Read status is stored on the server for each user, and the unread count comes from the server, so
    it is the same on every device. The count and the list are fetched again whenever the user opens
    another page, opens the notification panel, or comes back to the browser tab.
Boundary
3. With 0 unread, no badge is shown. More than 99 unread shows "99+".
Edge
4. A notification for an item the user can no longer access shows a message, not an error.
Permission
5. Users see only their own notifications.
Conflict
6. Marking read in one tab shows on refresh in another. The count never goes below 0.

What is tested here, at the API (the panel, the badge text "99+", the message of AC4 and the
refetching on a page change or on regaining focus are the browser's, in
tests/e2e/notifications.spec.ts):

* ``GET /notifications`` gains ``read_at`` and ``target`` on every item. ``target`` is worked out on
  the server for the reader as ``{"kind": ..., "id": ...}``, or ``null`` when the reader has no
  page for it, cannot open its item, or the item no longer exists. The server never sends a
  frontend URL. ``id`` is ``null`` for a kind that needs none.
* ``GET /notifications/unread-count`` returns ``{"count": n}``, every unread row, not only the 50
  the list holds.
* ``PATCH /notifications/{id}`` with ``{"is_read": true}`` marks one of the caller's own read.
* ``PATCH /notifications`` with ``{"is_read": true, "through_id": "<id>"}`` marks read every unread
  row of the caller up to and including that row in the list's own order, ``(created_at, id)``,
  and answers ``{"marked": n}``. The row is the newest the client had loaded, so rows older than
  the newest 50 are cleared too and rows that arrived later stay unread.
* ``read_at`` is stamped with the clock at the moment of marking, as ``created_at`` is at writing
  (notifications/service.py ``notify``), not by the column's ``now()``, which is the start of the
  transaction.

Targets (reader -> target) are the table in ``TARGET_CASES`` and the tests after it. The tests
cover every ``NotificationType``: a story that adds a type adds its rows here, and
``test_every_notification_type_has_a_target_rule`` fails until it does.
"""

from __future__ import annotations

import itertools
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, event, func, select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.permissions import ROLE_PERMISSIONS, permissions_for
from app.common.audit import AuditLog
from app.coordination.models import EventCoordinatorAssignment
from app.db import get_db
from app.events.models import EquipmentRequestStatus, EventStatus
from app.main import app
from app.notifications import targets
from app.notifications.models import Notification
from app.notifications.service import NotificationType
from app.registrations.models import EventRegistration
from app.safety.models import (
    EventSafetyReview,
    SafetyArrangement,
    SafetyReviewFinding,
    SafetyReviewOutcome,
)
from app.safety.service import current_facts
from app.venues.models import Venue, VenueAccessibilityFeature, VenueFacility, VenueLayout
from tests.support.factories import (
    approval_payload,
    create_submittable_event_request,
    future_datetime,
    make_change_request,
    make_equipment_item,
    make_equipment_type,
    make_event,
    make_secured_event,
    make_user,
)
from tests.support.seed import SEED_PASSWORD, Bookings, Events, SeedUser, Users, Venues

_counter = itertools.count(1)
FIRST_WRITTEN = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
LIST_LIMIT = 50

ITEM_KEYS = {
    "id",
    "notification_type",
    "title",
    "message",
    "event_id",
    "related_entity_type",
    "related_entity_id",
    "created_at",
    "read_at",
    "target",
}

# Nimbus Developer Conference (Events.APPROVED, Chloe's) asking for Exhibition Foyer, which holds
# nothing on 25 Nov 2026 - the request 12.1's own tests raise.
FOYER_FOR_NIMBUS = {"event_id": str(Events.APPROVED), "venue_id": str(Venues.EXHIBITION_FOYER)}


def _notice(
    db: Session,
    recipient: SeedUser | User,
    notification_type: str = NotificationType.EVENT_APPROVED,
    *,
    event_id: uuid.UUID | None = Events.SUBMITTED,
    entity_type: str | None = "event",
    entity_id: uuid.UUID | None = Events.SUBMITTED,
    created_at: datetime | None = None,
    read_at: datetime | None = None,
) -> Notification:
    """One notification for ``recipient``, written the way ``notify`` writes it. Each is stamped a
    minute after the one before in the test unless ``created_at`` says otherwise, so the order the
    tests expect is the order they are made in."""
    n = next(_counter)
    row = Notification(
        recipient_id=recipient.id,
        event_id=event_id,
        notification_type=notification_type,
        title=f"Notice {n}",
        message=f"Message {n}.",
        related_entity_type=entity_type,
        related_entity_id=entity_id,
        created_at=created_at or FIRST_WRITTEN + timedelta(minutes=n),
        read_at=read_at,
    )
    db.add(row)
    db.flush()
    return row


def _listed(client: TestClient) -> list[dict]:
    response = client.get("/notifications")
    assert response.status_code == 200, response.text
    return response.json()


def _count(client: TestClient) -> int:
    response = client.get("/notifications/unread-count")
    assert response.status_code == 200, response.text
    return response.json()["count"]


def _mark_one(client: TestClient, notification_id: uuid.UUID, body: dict | None = None):
    return client.patch(
        f"/notifications/{notification_id}", json={"is_read": True} if body is None else body
    )


def _mark_all(client: TestClient, through_id: uuid.UUID | str, **body):
    return client.patch(
        "/notifications", json={"is_read": True, "through_id": str(through_id), **body}
    )


def _read_at(db: Session, row: Notification) -> datetime | None:
    db.expire_all()
    return db.scalar(select(Notification.read_at).where(Notification.id == row.id))


def _target_of(client: TestClient, row: Notification) -> dict | None:
    item = next(item for item in _listed(client) if item["id"] == str(row.id))
    return item["target"]


# --- AC1: the list carries read state and a target --------------------------------------------
@pytest.mark.story("20.2", ac=1)
def test_a_new_notification_lists_read_at_null_and_a_target(login_as, db: Session):
    _notice(db, Users.ORGANISER, NotificationType.EVENT_APPROVED)

    listed = _listed(login_as(Users.ORGANISER))

    assert len(listed) == 1
    assert set(listed[0]) == ITEM_KEYS
    assert listed[0]["read_at"] is None
    assert listed[0]["target"] == {"kind": "event", "id": str(Events.SUBMITTED)}


@pytest.mark.story("20.2", ac=1)
def test_marking_one_read_stamps_read_at_and_leaves_the_rest_unread(login_as, db: Session):
    first, middle, last = (_notice(db, Users.ORGANISER) for _ in range(3))
    client = login_as(Users.ORGANISER)

    before = datetime.now(UTC)
    response = _mark_one(client, middle.id)
    after = datetime.now(UTC)

    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(middle.id)
    assert before <= datetime.fromisoformat(response.json()["read_at"]) <= after
    assert [(item["id"], item["read_at"] is None) for item in _listed(client)] == [
        (str(last.id), True),
        (str(middle.id), False),
        (str(first.id), True),
    ]
    assert _count(client) == 2


@pytest.mark.story("20.2", ac=1)
def test_marking_all_read_clears_every_unread_up_to_the_newest_loaded(login_as, db: Session):
    rows = [_notice(db, Users.ORGANISER) for _ in range(3)]
    client = login_as(Users.ORGANISER)
    newest_loaded = _listed(client)[0]["id"]

    response = _mark_all(client, newest_loaded)

    assert response.status_code == 200, response.text
    assert response.json() == {"marked": 3}
    assert _count(client) == 0
    assert all(_read_at(db, row) is not None for row in rows)


@pytest.mark.story("20.2", ac=1)
def test_marking_all_leaves_unread_what_arrived_after_the_list_was_loaded(login_as, db: Session):
    older, newest_loaded = _notice(db, Users.ORGANISER), _notice(db, Users.ORGANISER)
    client = login_as(Users.ORGANISER)
    assert _listed(client)[0]["id"] == str(newest_loaded.id)
    arrived_later = _notice(db, Users.ORGANISER)

    response = _mark_all(client, newest_loaded.id)

    assert response.json() == {"marked": 2}
    assert _read_at(db, older) is not None
    assert _read_at(db, newest_loaded) is not None
    assert _read_at(db, arrived_later) is None
    assert _count(client) == 1


@pytest.mark.story("20.2", ac=1)
def test_marking_all_also_clears_unread_older_than_the_newest_50(login_as, db: Session):
    rows = [_notice(db, Users.ORGANISER) for _ in range(LIST_LIMIT + 10)]
    client = login_as(Users.ORGANISER)
    listed = _listed(client)
    assert len(listed) == LIST_LIMIT
    assert _count(client) == LIST_LIMIT + 10

    response = _mark_all(client, listed[0]["id"])

    assert response.json() == {"marked": LIST_LIMIT + 10}
    assert _count(client) == 0
    assert _read_at(db, rows[0]) is not None  # the oldest, which the list never showed


@pytest.mark.story("20.2", ac=1)
def test_marking_all_orders_rows_written_at_one_instant_by_id(login_as, db: Session):
    """The list orders by ``created_at`` then ``id``, so "up to" a row means the same: of two rows
    written at the same instant, the one with the greater id is the newer."""
    instant = FIRST_WRITTEN + timedelta(days=1)
    older = _notice(db, Users.ORGANISER, created_at=FIRST_WRITTEN)
    lower, higher = sorted(
        (
            _notice(db, Users.ORGANISER, created_at=instant),
            _notice(db, Users.ORGANISER, created_at=instant),
        ),
        key=lambda row: row.id,
    )
    client = login_as(Users.ORGANISER)

    response = _mark_all(client, lower.id)

    assert response.json() == {"marked": 2}
    assert _read_at(db, older) is not None
    assert _read_at(db, lower) is not None
    assert _read_at(db, higher) is None
    assert _count(client) == 1


# --- AC1: which page each notification goes to ------------------------------------------------
def _case(
    notification_type: NotificationType,
    reader: SeedUser,
    entity_type: str,
    kind: str,
    target_id: str | None,
):
    """One row of the table. ``entity_type`` is what the real call site stores (``entity_id`` is
    that record: the event, the booking, or a change request); ``target_id`` is which id the
    target must carry: ``"event"``, ``"booking"`` or ``None`` for a kind that needs none."""
    return pytest.param(
        notification_type,
        reader,
        entity_type,
        kind,
        target_id,
        id=f"{notification_type.value}-{reader.role}",
    )


_T = NotificationType
TARGET_CASES = [
    # The organiser: the event.
    *(
        _case(kind, Users.ORGANISER, "event", "event", "event")
        for kind in (
            _T.EVENT_CLARIFICATION_REQUESTED,
            _T.EVENT_APPROVED,
            _T.EVENT_REJECTED,
            _T.EVENT_ASSIGNED_ORGANISER,
            _T.EVENT_REASSIGNED_ORGANISER,
            _T.BOOKING_VENUE_UNAVAILABLE,
            _T.SAFETY_REVIEW_REQUESTED,
            _T.SAFETY_APPROVED,
            _T.SAFETY_CHANGES_REQUESTED,
            _T.EVENT_CONFIRMED,
        )
    ),
    *(
        _case(kind, Users.ORGANISER, "event_change_request", "event", "event")
        for kind in (_T.EVENT_CHANGE_APPROVED, _T.EVENT_CHANGE_REJECTED)
    ),
    # The coordinator: the event, except a new change request, which is decided from the queue.
    *(
        _case(kind, Users.COORDINATOR, "event", "event", "event")
        for kind in (
            _T.EVENT_CLARIFICATION_RESPONDED,
            _T.EVENT_ASSIGNED_TO,
            _T.EVENT_REASSIGNED_FROM,
            _T.EVENT_REASSIGNED_TO,
            _T.BOOKING_VENUE_UNAVAILABLE,
            _T.SAFETY_APPROVED,
            _T.SAFETY_CHANGES_REQUESTED,
        )
    ),
    *(
        _case(kind, Users.COORDINATOR, "venue_booking", "event", "event")
        for kind in (
            _T.BOOKING_APPROVED,
            _T.BOOKING_REJECTED,
            _T.BOOKING_HOLD_EXPIRING,
            _T.BOOKING_HOLD_EXPIRED,
            _T.BOOKING_HOLD_EXPIRY_CHANGED,
        )
    ),
    _case(
        _T.EVENT_CHANGE_REQUESTED,
        Users.COORDINATOR,
        "event_change_request",
        "change_request_queue",
        None,
    ),
    _case(
        _T.EVENT_CHANGE_REQUEST_WITHDRAWN,
        Users.COORDINATOR,
        "event_change_request",
        "event",
        "event",
    ),
    # Venue Staff: the booking request, by the booking the notification stores (for a replaced
    # booking, the original).
    *(
        _case(kind, Users.VENUE_STAFF, "venue_booking", "booking_request", "booking")
        for kind in (
            _T.BOOKING_REQUESTED,
            _T.BOOKING_WITHDRAWN,
            _T.BOOKING_REPLACED,
            _T.BOOKING_RELEASED,
        )
    ),
    # Technical Support: their equipment work page, which needs no id.
    *(
        _case(kind, Users.TECH_SUPPORT, "event", "equipment_requests", None)
        for kind in (_T.EQUIPMENT_SUBMITTED, _T.EQUIPMENT_WITHDRAWN)
    ),
    # Story 6.2: the cancelled event goes to its coordinator, or to the Leads when it has none;
    # each registered attendee finds the registration, closed as the event's cancellation.
    _case(_T.EVENT_CANCELLED, Users.COORDINATOR, "event", "event", "event"),
    _case(_T.EVENT_CANCELLED, Users.LEAD, "event", "event", "event"),
    _case(_T.REGISTRATION_CANCELLED, Users.ATTENDEE, "event", "registrations", None),
]

# Types whose targets are tested in the tests below the table, because they depend on the state of
# the event or booking rather than on the type and role alone.
TARGETED_BY_STATE = {
    _T.EVENT_SUBMITTED,  # the Lead: the queue while unassigned, the event once assigned
    _T.EVENT_RETURNED_TO_PLANNING,  # the Safety Officer: the check if it opens, else the event
}
SAFETY_OFFICER_TYPES = (_T.SAFETY_REVIEW_REQUESTED, _T.EVENT_CONFIRMED)


@pytest.mark.story("20.2", ac=1)
@pytest.mark.parametrize(
    ("notification_type", "reader", "entity_type", "kind", "target_id"), TARGET_CASES
)
def test_a_notification_targets_the_page_its_reader_acts_on(
    login_as, db: Session, notification_type, reader, entity_type, kind, target_id
):
    entity_id = {
        "event": Events.SUBMITTED,
        "venue_booking": Bookings.PENDING_EXHIBITION_FOYER,
        "event_change_request": uuid.uuid4(),
    }[entity_type]
    event_id = Events.SUBMITTED
    if kind == "change_request_queue":
        # The queue holds a real pending request on an event its coordinator still coordinates.
        event = make_event(db, status=EventStatus.PLANNING, assigned_coordinator_id=reader.id)
        event_id, entity_id = event.id, make_change_request(db, event=event).id
    if kind == "equipment_requests":
        # The queue lists an item of the event's that was sent to Technical Support.
        event = make_event(db, status=EventStatus.PLANNING)
        make_equipment_item(
            db,
            event=event,
            equipment_type=make_equipment_type(db),
            quantity=1,
            status=EquipmentRequestStatus.PENDING,
        )
        event_id = entity_id = event.id
    row = _notice(
        db,
        reader,
        notification_type,
        event_id=event_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    expected_id = {
        "event": str(Events.SUBMITTED),
        "booking": str(Bookings.PENDING_EXHIBITION_FOYER),
    }
    expected = {"kind": kind, "id": expected_id.get(target_id)}

    assert _target_of(login_as(reader), row) == expected


def _changes_requested(db: Session, event) -> EventSafetyReview:
    """A review that sent ``event`` back, seeing the facts it has now, with one finding."""
    review = EventSafetyReview(
        event_id=event.id,
        reviewed_by_id=Users.SAFETY_OFFICER.id,
        reviewed_at=datetime(2026, 10, 1, tzinfo=UTC),
        outcome=SafetyReviewOutcome.CHANGES_REQUESTED,
        facts=current_facts(db, event),
        findings=[
            SafetyReviewFinding(
                position=0,
                factor_code="CAPACITY_AND_LAYOUT",
                arrangement=SafetyArrangement.VENUE_BOOKINGS,
                required_change="Book a bigger room.",
            )
        ],
    )
    db.add(review)
    db.flush()
    return review


@pytest.mark.story("20.2", ac=1)
@pytest.mark.parametrize("notification_type", SAFETY_OFFICER_TYPES)
def test_a_safety_officer_is_sent_to_the_safety_check_of_an_event_it_opens(
    login_as, db: Session, notification_type
):
    secured = make_secured_event(db, status=EventStatus.AWAITING_SAFETY_CHECK)
    event = secured.event
    row = _notice(
        db,
        Users.SAFETY_OFFICER,
        notification_type,
        event_id=event.id,
        entity_id=event.id,
    )

    assert _target_of(login_as(Users.SAFETY_OFFICER), row) == {
        "kind": "safety_check",
        "id": str(event.id),
    }


@pytest.mark.story("20.2", ac=1)
def test_every_notification_type_has_a_target_rule(login_as, db: Session):
    """Every ``NotificationType`` has a row in ``TARGET_CASES``, a test of its own below the table,
    or is one of the Safety Officer's two. A story that adds a type adds its rows and its target
    rule in the same change; until then this fails and names the type. Every type is also listed
    with a ``target`` key, whatever its value."""
    in_the_table = {case.values[0] for case in TARGET_CASES}

    covered = in_the_table | TARGETED_BY_STATE | set(SAFETY_OFFICER_TYPES)

    assert set(NotificationType) - covered == set()
    assert covered - set(NotificationType) == set()
    for notification_type in NotificationType:
        _notice(db, Users.ORGANISER, notification_type)
    listed = _listed(login_as(Users.ORGANISER))
    assert {item["notification_type"] for item in listed} == {t.value for t in NotificationType}
    assert all("target" in item for item in listed)


# --- AC1: the real actions, end to end --------------------------------------------------------
@pytest.fixture
def foyer_suits_nimbus(db: Session) -> None:
    """Story 11.1 refuses a request for a venue that does not suit the event unless it carries a
    justification, and Exhibition Foyer does not suit Nimbus. This gives the foyer what Nimbus asks
    for, as notifications/test_generate_and_route_notifications.py does, so the plain request
    below is accepted. Only this test's transaction sees it."""
    foyer = db.get(Venue, Venues.EXHIBITION_FOYER)
    foyer.capacity = 350
    foyer.layouts.append(VenueLayout(layout_code="THEATRE", layout_capacity=None))
    foyer.facilities.extend(
        VenueFacility(facility_code=code) for code in ("PROJECTOR", "SOUND_SYSTEM", "STAGE")
    )
    foyer.accessibility_features.append(VenueAccessibilityFeature(feature_code="HEARING_LOOP"))
    db.flush()


def _newest_of(client: TestClient, notification_type: str) -> dict:
    return next(item for item in _listed(client) if item["notification_type"] == notification_type)


@pytest.mark.story("20.2", ac=1)
@pytest.mark.usefixtures("foyer_suits_nimbus")
def test_a_booking_request_reaches_venue_staff_with_the_booking_to_decide(login_as, db: Session):
    response = login_as(Users.COORDINATOR).post("/bookings", json=FOYER_FOR_NIMBUS)
    assert response.status_code == 201, response.text
    booking_id = response.json()["id"]

    item = _newest_of(login_as(Users.VENUE_STAFF), "BOOKING_REQUESTED")

    assert item["target"] == {"kind": "booking_request", "id": booking_id}


@pytest.mark.story("20.2", ac=1)
def test_a_booking_approval_reaches_the_coordinator_with_the_event(login_as, db: Session):
    response = login_as(Users.VENUE_STAFF).post(
        f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/approve", json=approval_payload()
    )
    assert response.status_code == 200, response.text

    item = _newest_of(login_as(Users.COORDINATOR_2), "BOOKING_APPROVED")

    assert item["target"] == {"kind": "event", "id": str(Events.APPROVED_2)}


@pytest.mark.story("20.2", ac=1)
def test_a_safety_review_request_reaches_a_safety_officer_with_the_check(login_as, db: Session):
    secured = make_secured_event(db)
    response = login_as(Users.COORDINATOR).post(
        f"/safety-checks/{secured.event.id}/request", json={}
    )
    assert response.status_code == 200, response.text

    item = _newest_of(login_as(Users.SAFETY_OFFICER), "SAFETY_REVIEW_REQUESTED")

    assert item["target"] == {"kind": "safety_check", "id": str(secured.event.id)}


@pytest.mark.story("20.2", ac=1)
def test_a_submission_reaches_the_lead_with_the_unassigned_queue_until_it_is_assigned(
    login_as, db: Session
):
    organiser = login_as(Users.ORGANISER)
    draft = create_submittable_event_request(organiser)
    assert organiser.post(f"/events/{draft['id']}/submit").status_code == 200
    lead = login_as(Users.LEAD)

    unassigned = _newest_of(lead, "EVENT_SUBMITTED")
    assigned = lead.put(
        f"/events/{draft['id']}/coordinator", json={"coordinator_id": str(Users.COORDINATOR.id)}
    )
    after_assignment = _newest_of(lead, "EVENT_SUBMITTED")

    assert unassigned["event_id"] == draft["id"]
    assert unassigned["target"] == {"kind": "unassigned_events", "id": None}
    assert assigned.status_code == 200, assigned.text
    assert after_assignment["id"] == unassigned["id"]
    assert after_assignment["target"] == {"kind": "event", "id": draft["id"]}


def _statements_run_by(db: Session, call) -> list[str]:
    """The SQL statements ``call()`` sends, in order."""
    sent: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        sent.append(statement)

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", record)
    try:
        call()
    finally:
        event.remove(connection, "before_cursor_execute", record)
    return sent


def _awaiting_check_rows(db: Session, count: int) -> None:
    """``count`` Safety Officer notifications, each about an event of its own awaiting the check."""
    for _ in range(count):
        event_row = make_event(
            db, status=EventStatus.AWAITING_SAFETY_CHECK, assigned_coordinator_id=None
        )
        _notice(
            db,
            Users.SAFETY_OFFICER,
            NotificationType.SAFETY_REVIEW_REQUESTED,
            event_id=event_row.id,
            entity_id=event_row.id,
        )


def _booking_request_rows(db: Session, count: int) -> None:
    """``count`` Venue Staff notifications, each about a booking of its own (none exists)."""
    for _ in range(count):
        _notice(
            db,
            Users.VENUE_STAFF,
            NotificationType.BOOKING_REQUESTED,
            entity_type="venue_booking",
            entity_id=uuid.uuid4(),
        )


@pytest.mark.story("20.2", ac=1)
@pytest.mark.parametrize(
    ("reader", "add_rows"),
    [
        pytest.param(Users.SAFETY_OFFICER, _awaiting_check_rows, id="events-and-safety-checks"),
        pytest.param(Users.VENUE_STAFF, _booking_request_rows, id="bookings"),
    ],
)
def test_the_targets_of_a_full_page_take_no_more_queries_than_those_of_a_short_one(
    login_as, db: Session, reader: SeedUser, add_rows
):
    """The events, bookings and safety checks a page names are read in one query each, so a page
    of 50 sends as many statements as a page of 5."""
    client = login_as(reader)
    add_rows(db, 5)
    short_page = _statements_run_by(db, lambda: client.get("/notifications"))
    add_rows(db, LIST_LIMIT - 5)
    full_page = _statements_run_by(db, lambda: client.get("/notifications"))

    assert len(_listed(client)) == LIST_LIMIT
    assert len(full_page) == len(short_page)


CANCELLATION_REASON = "Our sponsor withdrew the budget."


def _cancel(client: TestClient, event_id: uuid.UUID):
    return client.post(f"/events/{event_id}/cancel", json={"reason": CANCELLATION_REASON})


@pytest.mark.story("20.2", ac=1)
def test_a_cancellation_reaches_the_coordinator_and_each_attendee_with_their_pages(
    login_as, db: Session
):
    event = make_event(
        db,
        status=EventStatus.CONFIRMED,
        assigned_coordinator_id=Users.COORDINATOR.id,
        is_public=True,
        registration_required=True,
    )
    db.add(EventRegistration(event_id=event.id, attendee_id=Users.ATTENDEE.id, status="REGISTERED"))
    db.flush()
    cancelled = _cancel(login_as(Users.ORGANISER), event.id)
    assert cancelled.status_code == 200, cancelled.text

    coordinator = _newest_of(login_as(Users.COORDINATOR), "EVENT_CANCELLED")
    attendee = _newest_of(login_as(Users.ATTENDEE), "REGISTRATION_CANCELLED")

    assert coordinator["target"] == {"kind": "event", "id": str(event.id)}
    assert attendee["target"] == {"kind": "registrations", "id": None}


@pytest.mark.story("20.2", ac=1)
def test_a_cancellation_with_no_coordinator_reaches_every_active_lead_with_the_event(
    client, login_as, db: Session
):
    """A cancelled event is still one staff can open, so the Leads, who are told because nobody
    coordinates it, are sent to it."""
    second_lead = make_user(db, role="EVENT_COORDINATOR_LEAD")
    event = make_event(db, status=EventStatus.UNDER_REVIEW, assigned_coordinator_id=None)
    cancelled = _cancel(login_as(Users.ORGANISER), event.id)
    assert cancelled.status_code == 200, cancelled.text

    first = _newest_of(login_as(Users.LEAD), "EVENT_CANCELLED")
    client.login(second_lead.email)
    second = _newest_of(client, "EVENT_CANCELLED")

    assert first["target"] == {"kind": "event", "id": str(event.id)}
    assert second["target"] == {"kind": "event", "id": str(event.id)}


@pytest.mark.story("20.2", ac=1)
def test_a_submission_cancelled_before_assignment_sends_the_lead_to_the_event(login_as):
    organiser = login_as(Users.ORGANISER)
    draft = create_submittable_event_request(organiser)
    assert organiser.post(f"/events/{draft['id']}/submit").status_code == 200
    cancelled = organiser.post(
        f"/events/{draft['id']}/cancel", json={"reason": CANCELLATION_REASON}
    )
    assert cancelled.status_code == 200, cancelled.text

    submitted = _newest_of(login_as(Users.LEAD), "EVENT_SUBMITTED")

    assert submitted["event_id"] == draft["id"]
    assert submitted["target"] == {"kind": "event", "id": draft["id"]}


@pytest.mark.story("20.2", ac=1)
def test_a_change_request_on_an_event_reassigned_away_sends_the_coordinator_to_the_event(
    login_as, db: Session
):
    starts_at = future_datetime(days=60)
    event = make_event(
        db,
        status=EventStatus.PLANNING,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=8),
        expected_attendance=100,
        assigned_coordinator_id=Users.COORDINATOR.id,
    )
    db.add(EventCoordinatorAssignment(event_id=event.id, coordinator_id=Users.COORDINATOR.id))
    db.flush()
    raised = login_as(Users.ORGANISER).post(
        f"/events/{event.id}/change-requests",
        json={"field": "expected_attendance", "proposed": 150, "reason": "More sign-ups."},
    )
    assert raised.status_code == 201, raised.text
    moved = login_as(Users.LEAD).put(
        f"/events/{event.id}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )
    assert moved.status_code == 200, moved.text

    notice = _newest_of(login_as(Users.COORDINATOR), "EVENT_CHANGE_REQUESTED")

    assert notice["event_id"] == str(event.id)
    assert notice["target"] == {"kind": "event", "id": str(event.id)}


@pytest.mark.story("20.2", ac=1)
@pytest.mark.parametrize(
    "status", [EventStatus.CANCELLED, EventStatus.COMPLETED, EventStatus.REJECTED]
)
def test_a_pending_request_on_an_event_not_going_ahead_sends_the_coordinator_to_the_event(
    login_as, db: Session, status: str
):
    """The coordinator's queue leaves out a pending request on a cancelled, completed or rejected
    event (``list_coordinator_change_requests``), so the notice goes to the event. These states
    cannot be reached in the real app (change requests are raised only on Planning or Confirmed
    events, nothing sets Completed, and 6.2 closes a cancelled event's pending requests as
    Cancelled), so this guards the shared condition only."""
    event = make_event(db, status=status, assigned_coordinator_id=Users.COORDINATOR.id)
    request = make_change_request(db, event=event)
    row = _notice(
        db,
        Users.COORDINATOR,
        NotificationType.EVENT_CHANGE_REQUESTED,
        event_id=event.id,
        entity_type="event_change_request",
        entity_id=request.id,
    )

    assert _target_of(login_as(Users.COORDINATOR), row) == {"kind": "event", "id": str(event.id)}


def _send_one_item(coordinator: TestClient, db: Session, event) -> str:
    """The coordinator records one item for ``event`` and sends it to Technical Support (15.1)."""
    added = coordinator.post(
        f"/events/{event.id}/equipment",
        json={"equipment_type_code": make_equipment_type(db).code, "quantity": 1},
    )
    assert added.status_code == 201, added.text
    sent = coordinator.post(f"/events/{event.id}/equipment-submissions")
    assert sent.status_code == 201, sent.text
    return added.json()["id"]


@pytest.mark.story("20.2", ac=1)
def test_an_equipment_notice_whose_item_was_removed_sends_technical_support_to_the_event(
    login_as, db: Session
):
    starts_at = future_datetime(days=60)
    event = make_event(
        db,
        status=EventStatus.PLANNING,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=8),
        assigned_coordinator_id=Users.COORDINATOR.id,
    )
    coordinator = login_as(Users.COORDINATOR)
    item_id = _send_one_item(coordinator, db, event)
    removed = coordinator.delete(f"/events/{event.id}/equipment/{item_id}")
    assert removed.status_code == 204, removed.text

    notice = _newest_of(login_as(Users.TECH_SUPPORT), "EQUIPMENT_SUBMITTED")

    assert notice["event_id"] == str(event.id)
    assert notice["target"] == {"kind": "event", "id": str(event.id)}


@pytest.mark.story("20.2", ac=1)
def test_an_equipment_notice_for_an_event_since_rejected_sends_technical_support_to_the_event(
    login_as, db: Session
):
    starts_at = future_datetime(days=60)
    event = make_event(
        db,
        status=EventStatus.UNDER_REVIEW,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=8),
        assigned_coordinator_id=Users.COORDINATOR.id,
    )
    coordinator = login_as(Users.COORDINATOR)
    _send_one_item(coordinator, db, event)
    rejected = coordinator.post(
        f"/events/{event.id}/reject", json={"reason": "The venue cannot take this event."}
    )
    assert rejected.status_code == 200, rejected.text

    notice = _newest_of(login_as(Users.TECH_SUPPORT), "EQUIPMENT_SUBMITTED")

    assert notice["event_id"] == str(event.id)
    assert notice["target"] == {"kind": "event", "id": str(event.id)}


@pytest.mark.story("20.2", ac=1)
def test_a_raised_change_request_sends_the_coordinator_to_the_queue(login_as, db: Session):
    starts_at = future_datetime(days=60)
    event = make_event(
        db,
        status=EventStatus.PLANNING,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=8),
        expected_attendance=100,
        assigned_coordinator_id=Users.COORDINATOR.id,
    )
    db.add(EventCoordinatorAssignment(event_id=event.id, coordinator_id=Users.COORDINATOR.id))
    db.flush()
    raised = login_as(Users.ORGANISER).post(
        f"/events/{event.id}/change-requests",
        json={"field": "expected_attendance", "proposed": 150, "reason": "More sign-ups."},
    )
    assert raised.status_code == 201, raised.text

    notice = _newest_of(login_as(Users.COORDINATOR), "EVENT_CHANGE_REQUESTED")

    assert notice["event_id"] == str(event.id)
    assert notice["target"] == {"kind": "change_request_queue", "id": None}


# --- AC4: no target when the reader has no page for it, cannot open it, or it is gone ---------
@pytest.mark.story("20.2", ac=4)
@pytest.mark.parametrize(
    ("reader", "notification_type", "entity_type", "entity_id"),
    [
        pytest.param(
            Users.ATTENDEE,
            NotificationType.EVENT_APPROVED,
            "event",
            Events.SUBMITTED,
            id="an-attendee-has-no-page-for-an-event",
        ),
        pytest.param(
            Users.VENUE_STAFF,
            NotificationType.EVENT_APPROVED,
            "event",
            Events.SUBMITTED,
            id="venue-staff-have-no-page-for-an-event-notification",
        ),
        pytest.param(
            Users.TECH_SUPPORT,
            NotificationType.EVENT_APPROVED,
            "event",
            Events.SUBMITTED,
            id="technical-support-have-no-page-for-an-event-notification",
        ),
        pytest.param(
            Users.SAFETY_OFFICER,
            NotificationType.EVENT_APPROVED,
            "event",
            Events.SUBMITTED,
            id="a-safety-officer-has-no-page-for-an-approval",
        ),
        pytest.param(
            Users.TECH_SUPPORT,
            NotificationType.BOOKING_REQUESTED,
            "venue_booking",
            Bookings.PENDING_EXHIBITION_FOYER,
            id="technical-support-have-no-page-for-a-booking",
        ),
        pytest.param(
            Users.COORDINATOR,
            NotificationType.EQUIPMENT_SUBMITTED,
            "event",
            Events.SUBMITTED,
            id="a-coordinator-has-no-page-for-equipment-sent-to-technical-support",
        ),
        pytest.param(
            Users.ORGANISER,
            NotificationType.BOOKING_REQUESTED,
            "venue_booking",
            Bookings.PENDING_EXHIBITION_FOYER,
            id="an-organiser-has-no-page-for-a-booking-request",
        ),
    ],
)
def test_a_pair_of_type_and_role_with_no_rule_has_no_target(
    login_as, db: Session, reader, notification_type, entity_type, entity_id
):
    row = _notice(db, reader, notification_type, entity_type=entity_type, entity_id=entity_id)

    assert _target_of(login_as(reader), row) is None


@pytest.mark.story("20.2", ac=4)
def test_another_organisers_draft_event_has_no_target(login_as, db: Session):
    """Olivia's draft is private to her, so Omar cannot open it."""
    row = _notice(
        db,
        Users.ORGANISER_2,
        NotificationType.EVENT_APPROVED,
        event_id=Events.DRAFT,
        entity_id=Events.DRAFT,
    )

    assert _target_of(login_as(Users.ORGANISER_2), row) is None


@pytest.mark.story("20.2", ac=4)
def test_a_booking_that_does_not_exist_has_no_target(login_as, db: Session):
    row = _notice(
        db,
        Users.VENUE_STAFF,
        NotificationType.BOOKING_REQUESTED,
        entity_type="venue_booking",
        entity_id=uuid.uuid4(),
    )

    assert _target_of(login_as(Users.VENUE_STAFF), row) is None


@pytest.mark.story("20.2", ac=4)
def test_returned_to_planning_with_no_review_and_the_event_in_planning_goes_to_the_event(
    login_as, db: Session
):
    event = make_event(
        db, status=EventStatus.PLANNING, assigned_coordinator_id=Users.COORDINATOR.id
    )
    row = _notice(
        db,
        Users.SAFETY_OFFICER,
        NotificationType.EVENT_RETURNED_TO_PLANNING,
        event_id=event.id,
        entity_id=event.id,
    )

    assert _target_of(login_as(Users.SAFETY_OFFICER), row) == {
        "kind": "event",
        "id": str(event.id),
    }


@pytest.mark.story("20.2", ac=4)
def test_returned_to_planning_with_a_review_on_record_goes_to_the_safety_check(
    login_as, db: Session
):
    event = make_event(
        db, status=EventStatus.PLANNING, assigned_coordinator_id=Users.COORDINATOR.id
    )
    _changes_requested(db, event)
    row = _notice(
        db,
        Users.SAFETY_OFFICER,
        NotificationType.EVENT_RETURNED_TO_PLANNING,
        event_id=event.id,
        entity_id=event.id,
    )

    assert _target_of(login_as(Users.SAFETY_OFFICER), row) == {
        "kind": "safety_check",
        "id": str(event.id),
    }


@pytest.mark.story("20.2", ac=4)
def test_returned_to_planning_while_awaiting_the_check_goes_to_the_safety_check(
    login_as, db: Session
):
    event = make_event(
        db,
        status=EventStatus.AWAITING_SAFETY_CHECK,
        assigned_coordinator_id=Users.COORDINATOR.id,
    )
    row = _notice(
        db,
        Users.SAFETY_OFFICER,
        NotificationType.EVENT_RETURNED_TO_PLANNING,
        event_id=event.id,
        entity_id=event.id,
    )

    assert _target_of(login_as(Users.SAFETY_OFFICER), row) == {
        "kind": "safety_check",
        "id": str(event.id),
    }


@pytest.mark.story("20.2", ac=4)
def test_an_event_that_does_not_exist_has_no_target(login_as, db: Session):
    row = _notice(
        db,
        Users.SAFETY_OFFICER,
        NotificationType.EVENT_RETURNED_TO_PLANNING,
        event_id=None,
        entity_id=uuid.uuid4(),
    )

    assert _target_of(login_as(Users.SAFETY_OFFICER), row) is None


@pytest.mark.story("20.2", ac=4)
def test_a_draft_event_a_safety_officer_cannot_see_has_no_target(login_as, db: Session):
    row = _notice(
        db,
        Users.SAFETY_OFFICER,
        NotificationType.EVENT_RETURNED_TO_PLANNING,
        event_id=Events.DRAFT,
        entity_id=Events.DRAFT,
    )

    assert _target_of(login_as(Users.SAFETY_OFFICER), row) is None


@pytest.mark.story("20.2", ac=4)
def test_a_notification_with_no_target_can_still_be_marked_read(login_as, db: Session):
    row = _notice(db, Users.ATTENDEE, NotificationType.EVENT_APPROVED)
    client = login_as(Users.ATTENDEE)
    assert _target_of(client, row) is None

    response = _mark_one(client, row.id)

    assert response.status_code == 200, response.text
    assert response.json()["read_at"] is not None
    assert _count(client) == 0


@pytest.mark.story("20.2", ac=1)
def test_marking_all_without_a_through_id_is_refused(login_as, db: Session):
    row = _notice(db, Users.ORGANISER)

    response = login_as(Users.ORGANISER).patch("/notifications", json={"is_read": True})

    assert response.status_code == 422, response.text
    assert _read_at(db, row) is None


@pytest.mark.story("20.2", ac=4)
def test_a_lead_has_no_target_for_a_type_it_has_no_rule_for(login_as, db: Session):
    """A Lead has a rule for ``EVENT_SUBMITTED`` (the queue, then the event) and for
    ``EVENT_CANCELLED`` (the event); any other type listed for a Lead, such as the approval of a
    request, has none."""
    row = _notice(db, Users.LEAD, NotificationType.EVENT_APPROVED)
    client = login_as(Users.LEAD)

    assert _target_of(client, row) is None
    assert _mark_one(client, row.id).status_code == 200


# --- AC2: read state and the count are the server's, per user ---------------------------------
@pytest.mark.story("20.2", ac=2)
def test_the_unread_count_counts_only_the_viewers_unread_rows(login_as, db: Session):
    for _ in range(3):
        _notice(db, Users.ORGANISER)
    for _ in range(2):
        _notice(db, Users.ORGANISER, read_at=FIRST_WRITTEN + timedelta(days=2))
    for _ in range(4):
        _notice(db, Users.ORGANISER_2)

    response = login_as(Users.ORGANISER).get("/notifications/unread-count")

    assert response.status_code == 200, response.text
    assert response.json() == {"count": 3}


@pytest.mark.story("20.2", ac=2)
def test_read_state_is_stored_per_user_and_is_the_same_from_every_session(login_as, db: Session):
    rows = [_notice(db, Users.ORGANISER) for _ in range(2)]
    first_device = login_as(Users.ORGANISER)
    with TestClient(app) as second_device:
        signed_in = second_device.post(
            "/auth/login", json={"email": Users.ORGANISER.email, "password": SEED_PASSWORD}
        )
        assert signed_in.status_code == 200, signed_in.text
        assert _count(second_device) == 2

        assert _mark_one(first_device, rows[0].id).status_code == 200

        assert _count(second_device) == 1
        assert [item["read_at"] is None for item in _listed(second_device)] == [True, False]


@pytest.mark.story("20.2", ac=2)
def test_two_recipients_of_one_action_keep_separate_read_state(login_as, db: Session):
    organiser_row = _notice(db, Users.ORGANISER, NotificationType.SAFETY_APPROVED)
    _notice(db, Users.COORDINATOR, NotificationType.SAFETY_APPROVED)

    assert _mark_one(login_as(Users.ORGANISER), organiser_row.id).status_code == 200

    assert _count(login_as(Users.ORGANISER)) == 0
    assert _count(login_as(Users.COORDINATOR)) == 1


# --- AC3: the count is the whole count, so the client can show "99+" --------------------------
@pytest.mark.story("20.2", ac=3)
@pytest.mark.parametrize("unread", [0, 1, 99, 100, 150])
def test_the_unread_count_is_exact_at_the_boundaries(login_as, db: Session, unread: int):
    for _ in range(unread):
        _notice(db, Users.TECH_SUPPORT)

    response = login_as(Users.TECH_SUPPORT).get("/notifications/unread-count")

    assert response.status_code == 200, response.text
    assert response.json() == {"count": unread}


# --- AC5: only your own ----------------------------------------------------------------------
@pytest.mark.story("20.2", ac=5)
def test_another_users_notification_cannot_be_marked_read(login_as, db: Session):
    olivias, olivias_other = _notice(db, Users.ORGANISER), _notice(db, Users.ORGANISER)
    assert _mark_one(login_as(Users.ORGANISER), olivias_other.id).status_code == 200
    omar = login_as(Users.ORGANISER_2)

    refused = _mark_one(omar, olivias.id)
    unknown = _mark_one(omar, uuid.uuid4())

    assert refused.status_code == 404, refused.text
    assert unknown.status_code == 404, unknown.text
    assert refused.json() == unknown.json()
    assert _read_at(db, olivias) is None


@pytest.mark.story("20.2", ac=5)
def test_marking_all_read_never_touches_another_users_rows(login_as, db: Session):
    olivias = [_notice(db, Users.ORGANISER) for _ in range(2)]
    omars = [_notice(db, Users.ORGANISER_2) for _ in range(2)]
    omar = login_as(Users.ORGANISER_2)

    response = _mark_all(omar, _listed(omar)[0]["id"])

    assert response.json() == {"marked": 2}
    assert all(_read_at(db, row) is not None for row in omars)
    assert all(_read_at(db, row) is None for row in olivias)
    assert _count(login_as(Users.ORGANISER)) == 2


@pytest.mark.story("20.2", ac=5)
def test_marking_all_through_another_users_notification_is_not_found(login_as, db: Session):
    olivias = _notice(db, Users.ORGANISER)
    omars = _notice(db, Users.ORGANISER_2)

    response = _mark_all(login_as(Users.ORGANISER_2), olivias.id)

    assert response.status_code == 404, response.text
    assert _read_at(db, olivias) is None
    assert _read_at(db, omars) is None


@pytest.mark.story("20.2", ac=5)
@pytest.mark.parametrize(
    "request_for",
    [
        pytest.param(lambda c: c.get("/notifications/unread-count"), id="unread-count"),
        pytest.param(
            lambda c: c.patch(f"/notifications/{uuid.uuid4()}", json={"is_read": True}),
            id="mark-one",
        ),
        pytest.param(
            lambda c: c.patch(
                "/notifications", json={"is_read": True, "through_id": str(uuid.uuid4())}
            ),
            id="mark-all",
        ),
    ],
)
def test_signed_out_requests_are_refused(client, request_for):
    assert request_for(client).status_code == 401


@pytest.mark.story("20.2", ac=5)
@pytest.mark.parametrize("user", Users.ONE_PER_ROLE, ids=lambda user: user.role)
def test_every_role_can_count_and_mark_its_own(login_as, db: Session, user: SeedUser):
    client = login_as(user)
    assert _count(client) == 0
    row = _notice(db, user)
    assert _count(client) == 1

    response = _mark_one(client, row.id)

    assert response.status_code == 200, response.text
    assert _count(client) == 0


@pytest.mark.story("20.2", ac=1)
@pytest.mark.parametrize("role", sorted(ROLE_PERMISSIONS))
def test_no_role_holds_more_than_one_permission_with_a_target_rule(role: str):
    """``_kind_for`` takes the first permission of the reader's that has a rule, so a role holding
    two would be sent by whichever it met first. Each role holds at most one today."""
    with_a_rule = {permission for permission, _, _ in targets._RULES}

    assert len(permissions_for(role) & with_a_rule) <= 1


@pytest.mark.story("20.2", ac=5)
@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"is_read": False}, id="mark-unread"),
        pytest.param({}, id="no-is_read"),
    ],
)
def test_marking_one_with_a_bad_body_is_refused(login_as, db: Session, body: dict):
    row = _notice(db, Users.ORGANISER)

    response = _mark_one(login_as(Users.ORGANISER), row.id, body)

    assert response.status_code == 422, response.text
    assert _read_at(db, row) is None


@pytest.mark.story("20.2", ac=5)
@pytest.mark.parametrize(
    "body",
    [
        pytest.param(lambda through: {"is_read": False, "through_id": through}, id="mark-unread"),
        pytest.param(lambda through: {"through_id": through}, id="no-is_read"),
        pytest.param(lambda through: {"is_read": True, "through_id": "not-a-uuid"}, id="malformed"),
    ],
)
def test_marking_all_with_a_bad_body_is_refused(login_as, db: Session, body):
    row = _notice(db, Users.ORGANISER)

    response = login_as(Users.ORGANISER).patch("/notifications", json=body(str(row.id)))

    assert response.status_code == 422, response.text
    assert _read_at(db, row) is None


# --- AC6: marking again changes nothing; the count never goes below 0 --------------------------
@pytest.mark.story("20.2", ac=6)
def test_marking_a_read_notification_again_changes_nothing(login_as, db: Session):
    row = _notice(db, Users.ORGANISER)
    _notice(db, Users.ORGANISER)
    client = login_as(Users.ORGANISER)
    first = _mark_one(client, row.id)

    second = _mark_one(client, row.id)

    assert second.status_code == 200, second.text
    assert datetime.fromisoformat(second.json()["read_at"]) == datetime.fromisoformat(
        first.json()["read_at"]
    )
    assert _read_at(db, row) == datetime.fromisoformat(first.json()["read_at"])
    assert _count(client) == 1


@pytest.mark.story("20.2", ac=6)
def test_the_unread_count_never_goes_below_zero(login_as, db: Session):
    rows = [_notice(db, Users.ORGANISER) for _ in range(3)]
    client = login_as(Users.ORGANISER)
    newest = _listed(client)[0]["id"]

    assert _mark_all(client, newest).json() == {"marked": 3}
    assert _mark_all(client, newest).json() == {"marked": 0}
    for row in rows:
        assert _mark_one(client, row.id).status_code == 200
        assert _count(client) == 0

    assert _count(client) == 0


@pytest.mark.story("20.2", ac=6)
def test_simultaneous_marks_of_one_notification_leave_one_read_at(engine: Engine):
    """Two tabs mark one notification at the same moment. Real concurrent transactions, so this
    test commits and cleans up after itself: whichever runs second finds it already read, answers
    with the first's ``read_at`` and changes nothing."""
    with Session(engine) as session:
        reader = make_user(session, role="EVENT_ORGANISER")
        row = Notification(
            recipient_id=reader.id,
            notification_type=NotificationType.EVENT_APPROVED,
            title="Race",
            message="Two tabs.",
            created_at=FIRST_WRITTEN,
        )
        session.add(row)
        session.commit()
        reader_id, reader_email, row_id = reader.id, reader.email, row.id
    start = threading.Barrier(2)

    def request_scoped_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = request_scoped_session

    def mark():
        with TestClient(app) as tab:
            signed_in = tab.post(
                "/auth/login", json={"email": reader_email, "password": SEED_PASSWORD}
            )
            assert signed_in.status_code == 200, signed_in.text
            start.wait()
            return _mark_one(tab, row_id)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = [
                future.result(timeout=30) for future in [pool.submit(mark), pool.submit(mark)]
            ]

        assert [response.status_code for response in responses] == [200, 200]
        stamped = {datetime.fromisoformat(response.json()["read_at"]) for response in responses}
        with Session(engine) as session:
            stored = session.scalar(select(Notification.read_at).where(Notification.id == row_id))
            unread = session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.recipient_id == reader_id, Notification.read_at.is_(None))
            )
        assert stamped == {stored}
        assert unread == 0
    finally:
        app.dependency_overrides.pop(get_db, None)
        with Session(engine) as session:
            session.execute(delete(AuditLog).where(AuditLog.actor_id == reader_id))
            session.execute(delete(User).where(User.id == reader_id))
            session.commit()
