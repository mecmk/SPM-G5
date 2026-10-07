"""Story 20.1 - generate and route notifications.

AC1 Notifications are generated for submission, clarification, approval or rejection,
    assignment, booking decisions, change decisions, registration changes and cancellation, and
    for the triggers the Week 7 changes added (5.4, 5.6, 9.4, 14.4, 12.7, 21.2). Each records the
    action, the event and the time, and goes only to related users.
AC2 New notifications appear in the recipient's notification list (20.2) without any extra
    action from them.
AC3 The user who performed an action is not notified of it.
AC4 No notification is created if the action fails. After a reassignment, the new coordinator
    receives later notifications.
AC5 Recipients for each notification type are defined and applied consistently. Unrelated users
    receive nothing.
AC6 Actions in quick succession produce notifications in the right order, without duplicates.

AC1 is tested for every action that exists today and notified nobody before this story:
submission (2.1, with 5.1's automatic assignment), approval and rejection (4.4, 4.5), the booking
request (12.1) and the booking decisions (13.2, 13.2.1). The actions that already notified keep
their own tests: 4.2's ``test_the_organiser_is_notified``, 4.3's
``test_the_assigned_coordinator_is_notified`` and 12.2's
``test_withdrawing_notifies_every_active_venue_staff_member`` pin their recipients exactly, and
5.2's reassignment is tested here under AC3. Change decisions (19.2), registration changes
(18.x), cancellation (6.2) and the Week 7 triggers belong to stories not built yet, which send
their own through ``notify``. AC2 is tested at the API, ``GET /notifications``: the list in the
app is story 20.2.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings import service as bookings_service
from app.events import service as events_service
from app.events.models import Event, EventStatus
from app.notifications.models import Notification
from app.notifications.service import NotificationType, notify
from tests.support.factories import create_submittable_event_request, make_booking, make_event
from tests.support.seed import Bookings, Events, SeedUser, Users, Venues

REJECTION_REASON = "The dates clash with the board retreat."
BOOKING_REJECTION_REASON = "Grand Hall is closed for repairs that week."
# Nimbus Developer Conference (Events.APPROVED, Chloe's) asking for Exhibition Foyer, which holds
# nothing on 25 Nov 2026 - the request 12.1's own tests raise.
FOYER_FOR_NIMBUS = {"event_id": str(Events.APPROVED), "venue_id": str(Venues.EXHIBITION_FOYER)}


def _recipients(db: Session, notification_type: str, *, event_id: uuid.UUID) -> list[uuid.UUID]:
    """Who received ``notification_type`` about ``event_id``, one entry per notification, so a
    duplicate shows up as a repeated id."""
    return sorted(
        db.execute(
            text(
                "SELECT recipient_id FROM notifications"
                " WHERE notification_type = :type AND event_id = :event"
            ),
            {"type": notification_type, "event": event_id},
        ).scalars()
    )


def _only_notification(db: Session, notification_type: str, *, event_id: uuid.UUID) -> Any:
    """The one notification of ``notification_type`` about ``event_id``; fails if there is more."""
    return db.execute(
        text(
            "SELECT recipient_id, related_entity_type, related_entity_id, title, message,"
            " created_at FROM notifications"
            " WHERE notification_type = :type AND event_id = :event"
        ),
        {"type": notification_type, "event": event_id},
    ).one()


def _notification_count(db: Session) -> int:
    return db.execute(text("SELECT count(*) FROM notifications")).scalar()


def _fail_audit_of(monkeypatch: pytest.MonkeyPatch, module: Any, failing_action: str) -> None:
    """Make ``module``'s audit entry for ``failing_action`` fail, as a database error part-way
    through the action would. Every other audit entry is written as usual."""
    real_record_audit = module.record_audit

    def record_audit(db: Session, *, action: str, **kwargs: Any) -> Any:
        if action == failing_action:
            raise RuntimeError(f"simulated failure recording {failing_action}")
        return real_record_audit(db, action=action, **kwargs)

    monkeypatch.setattr(module, "record_audit", record_audit)


def _delete_committed_event(engine: Engine, event_id: uuid.UUID, *entity_ids: uuid.UUID) -> None:
    """Remove what a concurrency test committed: the event, whose bookings, status history and
    notifications go with it (ON DELETE CASCADE), and the audit entries, which have no foreign
    key."""
    with Session(engine) as session:
        session.execute(
            text("DELETE FROM audit_log WHERE entity_id = ANY(:ids)"),
            {"ids": [event_id, *entity_ids]},
        )
        session.execute(text("DELETE FROM events WHERE id = :id"), {"id": event_id})
        session.commit()


# --- AC1/AC5: each action notifies its related users, and nobody else ----------------------
@pytest.mark.story("20.1", ac=1)
@pytest.mark.story("20.1", ac=5)
def test_submitting_a_request_notifies_its_coordinator(organiser_client, db: Session):
    """With Carl inactive, 5.1 assigns every submission to Chloe (5.1 AC4). Olivia submitted it,
    so she is not told (AC3)."""
    db.execute(
        text("UPDATE users SET is_active = false WHERE id = :id"), {"id": Users.COORDINATOR_2.id}
    )
    db.expire_all()
    draft = create_submittable_event_request(organiser_client)
    event_id = uuid.UUID(draft["id"])

    before = datetime.now(UTC)
    response = organiser_client.post(f"/events/{event_id}/submit")
    after = datetime.now(UTC)

    assert response.status_code == 200, response.text
    assert _recipients(db, "EVENT_SUBMITTED", event_id=event_id) == [Users.COORDINATOR.id]
    row = _only_notification(db, "EVENT_SUBMITTED", event_id=event_id)
    assert (row.related_entity_type, row.related_entity_id) == ("event", event_id)
    assert draft["name"] in row.title
    assert "Olivia Organiser" in row.message
    assert before <= row.created_at <= after


@pytest.mark.story("20.1", ac=1)
@pytest.mark.story("20.1", ac=5)
def test_approving_a_request_notifies_its_organiser(coordinator_client, db: Session):
    """Data Literacy Workshop is Olivia's, under review with Chloe."""
    before = datetime.now(UTC)
    response = coordinator_client.post(f"/events/{Events.SUBMITTED}/approve")
    after = datetime.now(UTC)

    assert response.status_code == 200, response.text
    assert _recipients(db, "EVENT_APPROVED", event_id=Events.SUBMITTED) == [Users.ORGANISER.id]
    row = _only_notification(db, "EVENT_APPROVED", event_id=Events.SUBMITTED)
    assert (row.related_entity_type, row.related_entity_id) == ("event", Events.SUBMITTED)
    assert "Data Literacy Workshop" in row.title
    assert "Chloe Coordinator" in row.message
    assert before <= row.created_at <= after


@pytest.mark.story("20.1", ac=1)
@pytest.mark.story("20.1", ac=5)
def test_rejecting_a_request_notifies_its_organiser_with_the_reason(
    coordinator_client, db: Session
):
    """Nimbus Leadership Offsite is Omar's, under review with Chloe."""
    before = datetime.now(UTC)
    response = coordinator_client.post(
        f"/events/{Events.UNDER_REVIEW}/reject", json={"reason": REJECTION_REASON}
    )
    after = datetime.now(UTC)

    assert response.status_code == 200, response.text
    assert _recipients(db, "EVENT_REJECTED", event_id=Events.UNDER_REVIEW) == [Users.ORGANISER_2.id]
    row = _only_notification(db, "EVENT_REJECTED", event_id=Events.UNDER_REVIEW)
    assert (row.related_entity_type, row.related_entity_id) == ("event", Events.UNDER_REVIEW)
    assert "Nimbus Leadership Offsite" in row.title
    assert REJECTION_REASON in row.message
    assert before <= row.created_at <= after


@pytest.mark.story("20.1", ac=1)
@pytest.mark.story("20.1", ac=5)
def test_raising_a_booking_request_notifies_active_venue_staff(coordinator_client, db: Session):
    """Vera is told; Ian, also Venue Staff but inactive, is not, and neither is Chloe, who asked.
    With no setup or teardown the held period is the event's own, 09:00 to 18:00."""
    before = datetime.now(UTC)
    response = coordinator_client.post("/bookings", json=FOYER_FOR_NIMBUS)
    after = datetime.now(UTC)

    assert response.status_code == 201, response.text
    booking_id = uuid.UUID(response.json()["id"])
    assert _recipients(db, "BOOKING_REQUESTED", event_id=Events.APPROVED) == [Users.VENUE_STAFF.id]
    row = _only_notification(db, "BOOKING_REQUESTED", event_id=Events.APPROVED)
    assert (row.related_entity_type, row.related_entity_id) == ("venue_booking", booking_id)
    assert "Exhibition Foyer" in row.title
    assert "Chloe Coordinator" in row.message
    assert "Nimbus Developer Conference" in row.message
    assert "on Wed 25 Nov 2026 from 09:00 to 18:00" in row.message
    assert before <= row.created_at <= after


@pytest.mark.story("20.1", ac=1)
@pytest.mark.story("20.1", ac=5)
def test_approving_a_booking_notifies_the_events_coordinator(venue_staff_client, db: Session):
    """Exhibition Foyer for Annual Wellness Summit, Carl's event: 09:00 to 17:00 on 3 Dec 2026
    with 45 minutes of setup and teardown, so held from 08:15 to 17:45."""
    before = datetime.now(UTC)
    response = venue_staff_client.post(f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/approve")
    after = datetime.now(UTC)

    assert response.status_code == 200, response.text
    assert _recipients(db, "BOOKING_APPROVED", event_id=Events.APPROVED_2) == [
        Users.COORDINATOR_2.id
    ]
    row = _only_notification(db, "BOOKING_APPROVED", event_id=Events.APPROVED_2)
    assert (row.related_entity_type, row.related_entity_id) == (
        "venue_booking",
        Bookings.PENDING_EXHIBITION_FOYER,
    )
    assert "Exhibition Foyer" in row.title
    assert "Annual Wellness Summit" in row.title
    assert "Vera Venue" in row.message
    assert "on Thu 3 Dec 2026 from 08:15 to 17:45" in row.message
    assert before <= row.created_at <= after


@pytest.mark.story("20.1", ac=1)
@pytest.mark.story("20.1", ac=5)
def test_rejecting_a_booking_notifies_the_events_coordinator_with_the_reason(
    venue_staff_client, db: Session
):
    """Grand Hall for Product Roadmap Townhall, Chloe's event."""
    before = datetime.now(UTC)
    response = venue_staff_client.post(
        f"/bookings/{Bookings.PENDING_GRAND_HALL}/reject",
        json={"decision_reason": BOOKING_REJECTION_REASON},
    )
    after = datetime.now(UTC)

    assert response.status_code == 200, response.text
    assert _recipients(db, "BOOKING_REJECTED", event_id=Events.APPROVED_3) == [Users.COORDINATOR.id]
    row = _only_notification(db, "BOOKING_REJECTED", event_id=Events.APPROVED_3)
    assert (row.related_entity_type, row.related_entity_id) == (
        "venue_booking",
        Bookings.PENDING_GRAND_HALL,
    )
    assert "Grand Hall" in row.title
    assert "Product Roadmap Townhall" in row.title
    assert BOOKING_REJECTION_REASON in row.message
    assert before <= row.created_at <= after


# --- AC2: the recipient's list holds it without them doing anything -------------------------
@pytest.mark.story("20.1", ac=2)
def test_a_new_notification_is_in_its_recipients_list_straight_away(client, db: Session):
    client.login(Users.COORDINATOR)
    before = datetime.now(UTC)
    assert client.post(f"/events/{Events.SUBMITTED}/approve").status_code == 200
    after = datetime.now(UTC)
    client.login(Users.ORGANISER)

    response = client.get("/notifications")

    assert response.status_code == 200, response.text
    newest = response.json()[0]
    assert set(newest) == {
        "id",
        "notification_type",
        "title",
        "message",
        "event_id",
        "related_entity_type",
        "related_entity_id",
        "created_at",
    }
    assert newest["notification_type"] == "EVENT_APPROVED"
    assert newest["event_id"] == str(Events.SUBMITTED)
    assert newest["related_entity_type"] == "event"
    assert newest["related_entity_id"] == str(Events.SUBMITTED)
    assert "Data Literacy Workshop" in newest["title"]
    assert "Chloe Coordinator" in newest["message"]
    assert before <= datetime.fromisoformat(newest["created_at"]) <= after


@pytest.mark.story("20.1", ac=2)
@pytest.mark.parametrize("user", Users.ONE_PER_ROLE, ids=lambda user: user.role)
def test_every_role_can_read_its_own_notifications(login_as, user: SeedUser):
    """The seed holds no notifications, so every list starts empty."""
    response = login_as(user).get("/notifications")

    assert response.status_code == 200, response.text
    assert response.json() == []


@pytest.mark.story("20.1", ac=2)
def test_the_list_holds_the_newest_50(login_as, db: Session):
    first_written = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    for minute in range(51):
        db.add(
            Notification(
                recipient_id=Users.TECH_SUPPORT.id,
                notification_type=NotificationType.BOOKING_WITHDRAWN,
                title=f"Notice {minute}",
                message="A venue booking request was withdrawn.",
                created_at=first_written + timedelta(minutes=minute),
            )
        )
    db.flush()

    listed = login_as(Users.TECH_SUPPORT).get("/notifications").json()

    assert len(listed) == 50
    assert listed[0]["title"] == "Notice 50"
    assert listed[-1]["title"] == "Notice 1"  # Notice 0, the oldest, is left out


# --- AC3: nobody is notified of their own action ---------------------------------------------
@pytest.mark.story("20.1", ac=3)
def test_nobody_is_notified_of_their_own_action(db: Session):
    """``actor=None`` is the system acting (12.7's expiries, later): its notifications go out."""
    chloe = db.get(User, Users.COORDINATOR.id)

    own = notify(
        db,
        recipient=chloe,
        actor=chloe,
        notification_type=NotificationType.EVENT_APPROVED,
        title="Own action",
        message="Chloe did this herself.",
        commit=False,
    )
    by_the_system = notify(
        db,
        recipient=chloe,
        actor=None,
        notification_type=NotificationType.EVENT_APPROVED,
        title="System action",
        message="The system did this.",
        commit=False,
    )

    assert own is None
    assert by_the_system is not None
    titles = db.execute(
        text("SELECT title FROM notifications WHERE recipient_id = :id"), {"id": chloe.id}
    ).scalars()
    assert list(titles) == ["System action"]


@pytest.mark.story("20.1", ac=3)
def test_the_coordinator_who_reassigns_is_not_notified(coordinator_client, db: Session):
    """Chloe hands Nimbus Developer Conference (Omar's) to Carl: Carl and Omar are told, Chloe,
    who made the change, is not. 5.2 AC1's "both coordinators" holds when someone else
    reassigns, which 5.6 (the Lead) brings."""
    response = coordinator_client.put(
        f"/events/{Events.APPROVED}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )

    assert response.status_code == 200, response.text
    rows = db.execute(
        text("SELECT notification_type, recipient_id FROM notifications WHERE event_id = :id"),
        {"id": Events.APPROVED},
    ).all()
    assert sorted(tuple(row) for row in rows) == [
        ("EVENT_REASSIGNED_ORGANISER", Users.ORGANISER_2.id),
        ("EVENT_REASSIGNED_TO", Users.COORDINATOR_2.id),
    ]


# --- AC4: a failed action notifies nobody; later notifications follow the event ----------------
class _Refused(NamedTuple):
    actor: SeedUser
    path: str
    body: dict | None
    status: int


@pytest.mark.story("20.1", ac=4)
@pytest.mark.parametrize(
    "refused",
    [
        pytest.param(
            _Refused(Users.COORDINATOR, f"/events/{Events.APPROVED}/approve", None, 409),
            id="approve-a-request-already-decided",
        ),
        pytest.param(
            _Refused(Users.COORDINATOR_2, f"/events/{Events.SUBMITTED}/approve", None, 403),
            id="approve-someone-elses-request",
        ),
        pytest.param(
            _Refused(
                Users.COORDINATOR, f"/events/{Events.SUBMITTED}/reject", {"reason": "  "}, 422
            ),
            id="reject-with-a-blank-reason",
        ),
        pytest.param(
            _Refused(Users.ORGANISER, f"/events/{Events.DRAFT}/submit", None, 422),
            id="submit-an-incomplete-draft",
        ),
        pytest.param(
            _Refused(
                Users.COORDINATOR,
                "/bookings",
                {"event_id": str(Events.APPROVED), "venue_id": str(Venues.GRAND_HALL)},
                409,
            ),
            id="request-a-venue-already-held",
        ),
        pytest.param(
            _Refused(
                Users.VENUE_STAFF, f"/bookings/{Bookings.APPROVED_GRAND_HALL}/approve", None, 409
            ),
            id="approve-a-booking-already-decided",
        ),
        pytest.param(
            _Refused(
                Users.VENUE_STAFF,
                f"/bookings/{Bookings.APPROVED_GRAND_HALL}/reject",
                {"decision_reason": "Too late."},
                409,
            ),
            id="reject-a-booking-already-decided",
        ),
    ],
)
def test_a_refused_action_notifies_nobody(login_as, db: Session, refused: _Refused):
    response = login_as(refused.actor).post(refused.path, json=refused.body)

    assert response.status_code == refused.status, response.text
    assert _notification_count(db) == 0


class _FailsAtAudit(NamedTuple):
    actor: SeedUser
    path: str
    body: dict | None
    module: Any
    notification_type: str
    event_id: uuid.UUID


@pytest.mark.story("20.1", ac=4)
@pytest.mark.parametrize(
    "failing",
    [
        pytest.param(
            _FailsAtAudit(
                Users.COORDINATOR,
                f"/events/{Events.SUBMITTED}/approve",
                None,
                events_service,
                "EVENT_APPROVED",
                Events.SUBMITTED,
            ),
            id="approval",
        ),
        pytest.param(
            _FailsAtAudit(
                Users.COORDINATOR,
                "/bookings",
                FOYER_FOR_NIMBUS,
                bookings_service,
                "BOOKING_REQUESTED",
                Events.APPROVED,
            ),
            id="booking-request",
        ),
        pytest.param(
            _FailsAtAudit(
                Users.VENUE_STAFF,
                f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/approve",
                None,
                bookings_service,
                "BOOKING_APPROVED",
                Events.APPROVED_2,
            ),
            id="booking-approval",
        ),
    ],
)
def test_an_action_that_fails_part_way_leaves_no_notification(
    login_as, db: Session, monkeypatch: pytest.MonkeyPatch, failing: _FailsAtAudit
):
    """Each action's audit entry is written after its notification, so failing it undoes a
    notification already written - unless that notification was committed on its own."""
    client = login_as(failing.actor)
    _fail_audit_of(monkeypatch, failing.module, failing.notification_type)

    with pytest.raises(RuntimeError):
        client.post(failing.path, json=failing.body)
    db.rollback()  # mirrors app.db.get_db's real teardown

    assert _recipients(db, failing.notification_type, event_id=failing.event_id) == []


@pytest.mark.story("20.1", ac=4)
def test_a_submission_that_fails_part_way_leaves_no_notification(
    organiser_client, db: Session, monkeypatch: pytest.MonkeyPatch
):
    draft = create_submittable_event_request(organiser_client)
    _fail_audit_of(monkeypatch, events_service, "EVENT_SUBMITTED")

    with pytest.raises(RuntimeError):
        organiser_client.post(f"/events/{draft['id']}/submit")
    db.rollback()  # mirrors app.db.get_db's real teardown

    assert _recipients(db, "EVENT_SUBMITTED", event_id=uuid.UUID(draft["id"])) == []


@pytest.mark.story("20.1", ac=4)
def test_after_a_reassignment_the_new_coordinator_gets_later_notifications(client, db: Session):
    """Chloe asked for Grand Hall for Product Roadmap Townhall, then handed the event to Carl.
    The decision goes to the coordinator the event has now, not the one who asked."""
    client.login(Users.COORDINATOR)
    reassigned = client.put(
        f"/events/{Events.APPROVED_3}/coordinator",
        json={"coordinator_id": str(Users.COORDINATOR_2.id)},
    )
    assert reassigned.status_code == 200, reassigned.text
    client.login(Users.VENUE_STAFF)

    response = client.post(f"/bookings/{Bookings.PENDING_GRAND_HALL}/approve")

    assert response.status_code == 200, response.text
    assert _recipients(db, "BOOKING_APPROVED", event_id=Events.APPROVED_3) == [
        Users.COORDINATOR_2.id
    ]


# --- AC5: recipients are defined, and nobody else receives anything ---------------------------
@pytest.mark.story("20.1", ac=5)
def test_a_submission_with_no_coordinator_notifies_nobody(organiser_client, db: Session):
    """5.1 AC5: with no active coordinator the request is still submitted, and left unassigned.
    Nobody is related to it yet, so nobody is told."""
    db.execute(text("UPDATE users SET is_active = false WHERE role_code = 'EVENT_COORDINATOR'"))
    db.expire_all()
    draft = create_submittable_event_request(organiser_client)

    response = organiser_client.post(f"/events/{draft['id']}/submit")

    assert response.status_code == 200, response.text
    status, coordinator_id = db.execute(
        text("SELECT status, assigned_coordinator_id FROM events WHERE id = :id"),
        {"id": draft["id"]},
    ).one()
    assert (status, coordinator_id) == (EventStatus.UNDER_REVIEW, None)
    assert _notification_count(db) == 0


@pytest.mark.story("20.1", ac=5)
def test_only_defined_notification_types_can_be_sent(db: Session):
    chloe = db.get(User, Users.COORDINATOR.id)

    with pytest.raises(ValueError):
        notify(
            db,
            recipient=chloe,
            actor=None,
            notification_type="EVENT_TELEPORTED",
            title="Not a defined type",
            message="Nobody has said who receives this.",
            commit=False,
        )
    assert _notification_count(db) == 0


@pytest.mark.story("20.1", ac=5)
def test_the_list_holds_only_the_signed_in_users_notifications(client, db: Session):
    """Chloe approves Olivia's request and rejects Omar's."""
    client.login(Users.COORDINATOR)
    assert client.post(f"/events/{Events.SUBMITTED}/approve").status_code == 200
    rejected = client.post(
        f"/events/{Events.UNDER_REVIEW}/reject", json={"reason": REJECTION_REASON}
    )
    assert rejected.status_code == 200, rejected.text

    def events_listed_for(user: SeedUser) -> list[str]:
        client.login(user)
        return [item["event_id"] for item in client.get("/notifications").json()]

    assert events_listed_for(Users.ORGANISER) == [str(Events.SUBMITTED)]
    assert events_listed_for(Users.ORGANISER_2) == [str(Events.UNDER_REVIEW)]
    assert events_listed_for(Users.COORDINATOR) == []


@pytest.mark.story("20.1", ac=5)
def test_reading_notifications_requires_signing_in(client):
    assert client.get("/notifications").status_code == 401


# --- AC6: in the order the actions happened, never twice --------------------------------------
@pytest.mark.story("20.1", ac=6)
def test_notifications_are_listed_in_the_order_the_actions_happened(client, db: Session):
    """Four of Chloe's actions on Olivia's three requests, one straight after another, all in
    this test's one transaction."""
    client.login(Users.COORDINATOR)
    actions = [
        (f"/events/{Events.SUBMITTED}/clarifications", {"message": "Which layout do you need?"}),
        (f"/events/{Events.SUBMITTED_2}/approve", None),
        (f"/events/{Events.CLARIFICATION_REQUESTED}/clarifications", {"message": "Four speakers?"}),
        (f"/events/{Events.SUBMITTED}/reject", {"reason": REJECTION_REASON}),
    ]
    for path, body in actions:
        response = client.post(path, json=body)
        assert response.status_code in (200, 201), response.text
    client.login(Users.ORGANISER)

    listed = client.get("/notifications").json()

    assert [(item["notification_type"], item["event_id"]) for item in listed] == [
        ("EVENT_REJECTED", str(Events.SUBMITTED)),
        ("EVENT_CLARIFICATION_REQUESTED", str(Events.CLARIFICATION_REQUESTED)),
        ("EVENT_APPROVED", str(Events.SUBMITTED_2)),
        ("EVENT_CLARIFICATION_REQUESTED", str(Events.SUBMITTED)),
    ]


class _Twice(NamedTuple):
    actor: SeedUser
    path: str
    body: dict | None
    notification_type: str
    event_id: uuid.UUID
    recipients: list[uuid.UUID]


@pytest.mark.story("20.1", ac=6)
@pytest.mark.parametrize(
    "twice",
    [
        pytest.param(
            _Twice(
                Users.COORDINATOR,
                f"/events/{Events.SUBMITTED}/approve",
                None,
                "EVENT_APPROVED",
                Events.SUBMITTED,
                [Users.ORGANISER.id],
            ),
            id="approve-a-request",
        ),
        pytest.param(
            _Twice(
                Users.VENUE_STAFF,
                f"/bookings/{Bookings.PENDING_EXHIBITION_FOYER}/approve",
                None,
                "BOOKING_APPROVED",
                Events.APPROVED_2,
                [Users.COORDINATOR_2.id],
            ),
            id="approve-a-booking",
        ),
        pytest.param(
            _Twice(
                Users.COORDINATOR,
                "/bookings",
                FOYER_FOR_NIMBUS,
                "BOOKING_REQUESTED",
                Events.APPROVED,
                [Users.VENUE_STAFF.id],
            ),
            id="request-a-venue",
        ),
    ],
)
def test_a_repeated_action_notifies_once(login_as, db: Session, twice: _Twice):
    """The second of two identical requests (a double-click) is refused, so it tells nobody."""
    client = login_as(twice.actor)

    first = client.post(twice.path, json=twice.body)
    second = client.post(twice.path, json=twice.body)

    assert first.status_code in (200, 201), first.text
    assert second.status_code == 409, second.text
    assert _recipients(db, twice.notification_type, event_id=twice.event_id) == twice.recipients


@pytest.mark.story("20.1", ac=6)
def test_submitting_twice_notifies_once(organiser_client, db: Session):
    draft = create_submittable_event_request(organiser_client)

    first = organiser_client.post(f"/events/{draft['id']}/submit")
    second = organiser_client.post(f"/events/{draft['id']}/submit")

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    assert len(_recipients(db, "EVENT_SUBMITTED", event_id=uuid.UUID(draft["id"]))) == 1


@pytest.mark.story("20.1", ac=6)
def test_simultaneous_booking_decisions_notify_once(engine: Engine):
    """Two Venue Staff approvals of one request at the same moment: the row lock lets one
    through, and only that one notifies. Real concurrent transactions, so this test commits and
    cleans up after itself. Seminar Room 2.1 holds nothing on 3 Mar 2027."""
    with Session(engine) as session:
        event = make_event(
            session, status=EventStatus.PLANNING, assigned_coordinator_id=Users.COORDINATOR.id
        )
        booking = make_booking(
            session,
            venue_id=Venues.SEMINAR_ROOM,
            starts_at=datetime(2027, 3, 3, 2, 0, tzinfo=UTC),
            ends_at=datetime(2027, 3, 3, 4, 0, tzinfo=UTC),
            event_id=event.id,
        )
        session.commit()
        event_id, booking_id = event.id, booking.id
    start = threading.Barrier(2)

    def approve() -> str:
        with Session(engine) as session:
            start.wait()
            booking = bookings_service.get_booking_for_decision(session, booking_id)
            try:
                bookings_service.approve_booking(session, booking, actor_id=Users.VENUE_STAFF.id)
            except bookings_service.BookingNotPending:
                return "refused"
            return "approved"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(approve) for _ in range(2)]
            outcomes = sorted(future.result(timeout=30) for future in results)

        assert outcomes == ["approved", "refused"]
        with Session(engine) as session:
            assert _recipients(session, "BOOKING_APPROVED", event_id=event_id) == [
                Users.COORDINATOR.id
            ]
    finally:
        _delete_committed_event(engine, event_id, booking_id)


@pytest.mark.story("20.1", ac=6)
def test_simultaneous_event_decisions_notify_once(engine: Engine):
    """Two approvals of one request at the same moment, both read while it was under review: the
    conditional update lets one through, and only that one notifies."""
    with Session(engine) as session:
        event = make_event(
            session, status=EventStatus.UNDER_REVIEW, assigned_coordinator_id=Users.COORDINATOR.id
        )
        session.commit()
        event_id = event.id
    start = threading.Barrier(2)

    def approve() -> str:
        with Session(engine) as session:
            event = session.get(Event, event_id)
            actor = session.get(User, Users.COORDINATOR.id)
            start.wait()
            try:
                events_service.approve_event(session, event, actor=actor)
            except events_service.EventNotAwaitingDecision:
                return "refused"
            return "approved"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(approve) for _ in range(2)]
            outcomes = sorted(future.result(timeout=30) for future in results)

        assert outcomes == ["approved", "refused"]
        with Session(engine) as session:
            assert _recipients(session, "EVENT_APPROVED", event_id=event_id) == [Users.ORGANISER.id]
    finally:
        _delete_committed_event(engine, event_id)
