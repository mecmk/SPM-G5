"""Story 12.8 - cancel an approved venue booking. The backlog's ACs, as written:

Happy path
1. The coordinator can cancel an approved booking of their event, for a venue requirement or an
    additional venue, without cancelling the event. They must give a reason.
2. Cancelling releases the hold at once. The booking shows as Cancelled with its reason and stays
    in the event's booking list as history. Its requirement needs a venue again (12.5).
3. Venue Staff are notified. They do not need to approve the cancellation.

Boundary
4. Cancelling closes 24 hours before the event's set-up time, when change requests close too
    (CL-150, the same cut-off as 19.1 AC12).

Edge
5. If the event is Awaiting Safety Check or Confirmed, cancelling any of its approved bookings
    returns it to Planning. It needs a new safety check (21.2 AC1) before it can be confirmed
    again. The organiser and the Safety Officers are notified.
6. If the event is in Planning, it stays in Planning, but a safety approval it already has no
    longer allows Confirm (21.2 AC14).
7. A booking marked "Venue unavailable - alternative needed" (9.4) can be cancelled like any
    other. A booking with a pending replacement (12.6) cannot be cancelled until the replacement
    is withdrawn.

Permission
8. Only the assigned coordinator can cancel the event's bookings. The API refuses a cancellation
    with no reason, after the cut-off, or while a replacement is pending.

Technical (team note)
9. Cancelling uses the same release path as 21.3 (19.2's ``release_booking``) with its own cause,
    and records who cancelled and the reason (CL-181 (3)).

Every rule here is a backend case except what a user must see or click, which is
tests/e2e/cancel-approved-booking.spec.ts. The event's set-up time is when set-up begins at its
first venue (12.1 AC1), as change requests read it. A refusal is checked against a booking that
is still approved and an event that is unchanged, so it cannot pass only because nothing happens.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings import service as bookings_service
from app.bookings.models import BookingStatus, VenueBooking
from app.bookings.schemas import BookingReplacementIn
from app.cancellations import service as cancellations_service
from app.common.audit import AuditLog
from app.events.models import Event, EventStatus, EventStatusHistory
from app.notifications.models import Notification
from app.safety.models import EventSafetyReview, SafetyReviewOutcome
from app.safety.service import current_facts
from app.venues.models import Venue
from tests.support.factories import (
    make_booking,
    make_event,
    make_secured_event,
    make_user,
    make_venue,
)
from tests.support.locks import LOCK_WAIT_SECONDS, backend_pid, wait_until_waiting
from tests.support.replacement import (
    add_pending_replacement,
    make_scenario,
    purge,
    set_status,
)
from tests.support.seed import Users, Venues

REASON = "The client moved the plenary online."
SETUP_MINUTES = 30
RELEASED_TITLE = "A venue booking was released"
NOT_ASSIGNED = "Only the coordinator assigned to this event can cancel its venue bookings."
NOT_APPROVED = "Only an approved booking can be cancelled. This one is {status}."
REPLACEMENT_PENDING = (
    "A replacement at {venue} is waiting for Venue Staff. Withdraw it before cancelling this "
    "booking."
)
CLOSED = "Cancelling this event's venue bookings closed 24 hours before its set-up time."
RETURNED_TITLE = '"{event}" is back in Planning'
RETURNED_MESSAGE = (
    'Chloe Coordinator cancelled the booking of {venue} for "{event}" while it was {status}, so '
    "it is back in Planning and needs a new safety check before it is confirmed again."
)
APPROVAL_OUT_OF_DATE = (
    "The event's venue bookings changed after the safety approval; request a safety review again."
)


@dataclass(frozen=True)
class Scene:
    """A secured event (story 21.2 AC1) coordinated by Chloe: ``first`` covers its requirement
    ("Main venue") at Grand Hall with 30 minutes of setup, ``extra`` is an additional venue at
    Exhibition Foyer, both approved by Venue Staff."""

    event: Event
    requirement_id: uuid.UUID
    first: VenueBooking
    extra: VenueBooking


def _scene(db: Session, *, status: str = EventStatus.PLANNING, **overrides: Any) -> Scene:
    """The scene in ``status``, on 4 Mar 2030 (09:00-17:00 Singapore) unless ``overrides`` date
    it, so no seeded booking holds its venues."""
    secured = make_secured_event(db, status=status, expected_attendance=60, **overrides)
    event, first = secured.event, secured.booking
    first.setup_minutes = SETUP_MINUTES
    first.decided_by_id = Users.VENUE_STAFF.id
    first.decided_at = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    db.flush()
    db.refresh(first)
    extra = make_booking(
        db,
        event_id=event.id,
        venue_id=Venues.EXHIBITION_FOYER,
        starts_at=event.starts_at + timedelta(hours=1),
        ends_at=event.ends_at,
        status=BookingStatus.APPROVED,
        expected_attendance=60,
        hold_expires_at=datetime.now(UTC) + timedelta(days=30),
        decided_by_id=Users.VENUE_STAFF.id,
        decided_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
    )
    return Scene(event, secured.requirement_id, first, extra)


@pytest.fixture
def scene(db: Session) -> Scene:
    return _scene(db)


def _cancel(client, booking: Any, reason: Any = REASON):
    booking_id = getattr(booking, "id", booking)
    body = {} if reason is None else {"reason": reason}
    return client.post(f"/bookings/{booking_id}/cancel", json=body)


def _cancelled(client, booking: Any, reason: str = REASON) -> dict[str, Any]:
    response = _cancel(client, booking, reason)
    assert response.status_code == 200, response.text
    return response.json()


def _fresh(db: Session, row: Any) -> Any:
    db.expire_all()
    return db.get(type(row), row.id)


def _notices(db: Session, event_id: uuid.UUID, kind: str) -> list[Notification]:
    db.expire_all()
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.event_id == event_id, Notification.notification_type == kind)
            .order_by(Notification.created_at, Notification.id)
        )
    )


def _recipients(db: Session, event_id: uuid.UUID, kind: str) -> list[uuid.UUID]:
    return sorted(notice.recipient_id for notice in _notices(db, event_id, kind))


def _active_safety_officers(db: Session) -> list[uuid.UUID]:
    return sorted(
        db.scalars(
            select(User.id).where(User.role_code == "SAFETY_OFFICER", User.is_active.is_(True))
        )
    )


def _untouched(db: Session, booking: VenueBooking, event: Event, status: str) -> None:
    """A refused cancel left the booking approved with no release recorded, the event where it
    was, and nobody told."""
    db.expire_all()
    row = db.get(VenueBooking, booking.id)
    assert row.status == BookingStatus.APPROVED
    assert (row.release_cause, row.release_reason, row.released_by_id) == (None, None, None)
    assert db.get(Event, event.id).status == status
    for kind in ("BOOKING_RELEASED", "EVENT_RETURNED_TO_PLANNING"):
        assert _notices(db, event.id, kind) == []


def _approve_safety(db: Session, event: Event) -> None:
    """The Safety Officer's approval of the event as it stands now (story 21.2)."""
    db.add(
        EventSafetyReview(
            event_id=event.id,
            reviewed_by_id=Users.SAFETY_OFFICER.id,
            reviewed_at=datetime(2026, 10, 1, tzinfo=UTC),
            outcome=SafetyReviewOutcome.APPROVED,
            facts=current_facts(db, event),
        )
    )
    db.flush()


# --- AC1/AC9: the coordinator cancels with a reason, through the shared release path ----------
@pytest.mark.story("12.8", ac=1)
def test_the_coordinator_cancels_an_approved_booking_with_a_reason(
    coordinator_client, db: Session, scene: Scene
):
    before = datetime.now(UTC)

    body = _cancelled(coordinator_client, scene.first, f"  {REASON}  ")

    assert body["status"] == BookingStatus.CANCELLED
    assert body["release_cause"] == "COORDINATOR_CANCELLED"
    assert body["release_reason"] == REASON
    row = _fresh(db, scene.first)
    assert row.released_by_id == Users.COORDINATOR.id
    assert before <= row.cancelled_at <= datetime.now(UTC)
    assert row.decided_by_id == Users.VENUE_STAFF.id  # who approved it stays on the record
    assert _fresh(db, scene.event).status == EventStatus.PLANNING
    assert _fresh(db, scene.extra).status == BookingStatus.APPROVED
    [audit] = db.scalars(
        select(AuditLog).where(
            AuditLog.action == "BOOKING_RELEASED", AuditLog.entity_id == scene.first.id
        )
    ).all()
    assert audit.actor_id == Users.COORDINATOR.id
    assert audit.details["event_id"] == str(scene.event.id)
    assert audit.details["venue_id"] == str(scene.first.venue_id)
    assert audit.details["cause"] == "COORDINATOR_CANCELLED"


@pytest.mark.story("12.8", ac=1)
def test_an_additional_venue_can_be_cancelled(coordinator_client, db: Session, scene: Scene):
    body = _cancelled(coordinator_client, scene.extra)

    assert body["status"] == BookingStatus.CANCELLED
    assert body["release_reason"] == REASON
    assert _fresh(db, scene.first).status == BookingStatus.APPROVED


# --- AC2: the hold goes at once, the booking stays as history, the requirement needs a venue ---
@pytest.mark.story("12.8", ac=2)
def test_the_hold_is_released_at_once(coordinator_client, db: Session, scene: Scene):
    other = make_event(db, status=EventStatus.PLANNING)

    _cancelled(coordinator_client, scene.first)

    try:
        with db.begin_nested():
            make_booking(
                db,
                event_id=other.id,
                venue_id=scene.first.venue_id,
                starts_at=scene.first.starts_at,
                ends_at=scene.first.ends_at,
                status=BookingStatus.PENDING,
            )
    except IntegrityError:
        pytest.fail("the venue is still held after the cancellation")


@pytest.mark.story("12.8", ac=2)
def test_the_booking_stays_listed_and_its_requirement_needs_a_venue(
    coordinator_client, scene: Scene
):
    """Grand Hall holds 400 and is open 08:00-22:00, and the requirement asks for 60 people with
    no layout or facility, so a new request is refused only while the booking stands."""
    _cancelled(coordinator_client, scene.first)

    listed = coordinator_client.get(f"/bookings/for-event/{scene.event.id}").json()
    [row] = [b for b in listed if b["id"] == str(scene.first.id)]
    assert row["status"] == BookingStatus.CANCELLED
    assert row["release_cause"] == "COORDINATOR_CANCELLED"
    assert row["release_reason"] == REASON
    response = coordinator_client.post(
        "/bookings",
        json={
            "event_id": str(scene.event.id),
            "venue_id": str(Venues.GRAND_HALL),
            "venue_requirement_id": str(scene.requirement_id),
        },
    )
    assert response.status_code == 201, response.text


# --- AC3: Venue Staff are told, and have nothing to approve ------------------------------------
@pytest.mark.story("12.8", ac=3)
def test_every_active_venue_staff_member_is_told_and_nobody_else(
    coordinator_client, db: Session, scene: Scene
):
    staff = make_user(db, role="VENUE_STAFF")

    body = _cancelled(coordinator_client, scene.first)

    assert body["status"] == BookingStatus.CANCELLED  # final, not waiting for Venue Staff
    notices = _notices(db, scene.event.id, "BOOKING_RELEASED")
    assert sorted(n.recipient_id for n in notices) == sorted([Users.VENUE_STAFF.id, staff.id])
    for notice in notices:
        assert notice.title == RELEASED_TITLE
        assert notice.related_entity_id == scene.first.id
        assert notice.message == (
            f'The booking of Grand Hall for "{scene.event.name}" on Mon 4 Mar 2030 from 08:30 '
            f"to 17:00 was cancelled by its coordinator. Reason: {REASON}"
        )
    # The event stays in Planning, so nobody else has anything to hear about.
    assert _notices(db, scene.event.id, "EVENT_RETURNED_TO_PLANNING") == []


# --- AC4: cancelling closes 24 hours before the event's set-up time ----------------------------
def _dated_scene(db: Session, *, starts_in: timedelta, setup_minutes: int) -> Scene:
    """The scene starting ``starts_in`` from now at venues of its own, ``first`` with
    ``setup_minutes`` of setup. Each hold runs 30 days, so no sweep expires it first."""
    starts_at = (datetime.now(UTC) + starts_in).replace(microsecond=0)
    built = _scene(
        db,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=8),
        venue_id=make_venue(db, capacity=400).id,
    )
    built.first.setup_minutes = setup_minutes
    built.extra.venue_id = make_venue(db, capacity=400).id
    db.flush()
    db.refresh(built.first)
    db.refresh(built.extra)
    return built


@pytest.mark.story("12.8", ac=4)
def test_cancelling_is_open_until_24_hours_before_set_up(coordinator_client, db: Session):
    """Set-up begins 24 hours and 30 minutes from now (an hour of setup before a start 25 hours
    and 30 minutes away)."""
    built = _dated_scene(db, starts_in=timedelta(hours=25, minutes=30), setup_minutes=60)

    assert _cancel(coordinator_client, built.first).status_code == 200


@pytest.mark.story("12.8", ac=4)
@pytest.mark.parametrize(
    "case",
    [
        # The start is 24h30m away, but its hour of setup begins 23h30m from now.
        "setup-inside-the-cutoff",
        # The event is under way: set-up began an hour ago.
        "set-up-passed",
        # This booking's own set-up is days away; the event's first set-up, at its additional
        # venue, is 20 hours away.
        "another-booking-sets-up-first",
    ],
)
def test_cancelling_after_the_cutoff_is_refused(coordinator_client, db: Session, case: str):
    if case == "setup-inside-the-cutoff":
        built = _dated_scene(db, starts_in=timedelta(hours=24, minutes=30), setup_minutes=60)
    elif case == "set-up-passed":
        built = _dated_scene(db, starts_in=-timedelta(hours=1), setup_minutes=0)
    else:
        built = _dated_scene(db, starts_in=timedelta(days=3), setup_minutes=0)
        built.extra.starts_at = datetime.now(UTC) + timedelta(hours=20)
        built.extra.ends_at = built.extra.starts_at + timedelta(hours=2)
        db.flush()

    response = _cancel(coordinator_client, built.first)

    assert response.status_code == 409
    assert response.json()["detail"] == CLOSED
    _untouched(db, built.first, built.event, EventStatus.PLANNING)


# --- AC5: an event past Planning goes back to it, and the organiser and officers are told -----
@pytest.mark.story("12.8", ac=5)
@pytest.mark.parametrize(
    ("status", "in_words"),
    [
        (EventStatus.AWAITING_SAFETY_CHECK, "awaiting safety check"),
        (EventStatus.CONFIRMED, "confirmed"),
    ],
)
@pytest.mark.parametrize("which", ["requirement", "additional"])
def test_an_event_past_planning_goes_back_to_planning(
    coordinator_client, db: Session, status: str, in_words: str, which: str
):
    built = _scene(db, status=status)
    if status == EventStatus.CONFIRMED:
        built.event.confirmed_at = datetime(2026, 10, 2, tzinfo=UTC)
        db.flush()
    booking = built.first if which == "requirement" else built.extra
    venue = "Grand Hall" if which == "requirement" else "Exhibition Foyer"

    _cancelled(coordinator_client, booking)

    event = _fresh(db, built.event)
    assert event.status == EventStatus.PLANNING
    assert event.confirmed_at is None
    [history] = db.scalars(
        select(EventStatusHistory).where(
            EventStatusHistory.event_id == event.id,
            EventStatusHistory.to_status == EventStatus.PLANNING,
        )
    ).all()
    assert history.from_status == status
    assert history.changed_by_id == Users.COORDINATOR.id
    notices = _notices(db, event.id, "EVENT_RETURNED_TO_PLANNING")
    assert sorted(n.recipient_id for n in notices) == sorted(
        [Users.ORGANISER.id, *_active_safety_officers(db)]
    )
    for notice in notices:
        assert notice.title == RETURNED_TITLE.format(event=event.name)
        assert notice.message == RETURNED_MESSAGE.format(
            venue=venue, event=event.name, status=in_words
        )


# --- AC6: an event in Planning stays there, but its safety approval no longer confirms it -----
@pytest.mark.story("12.8", ac=6)
def test_a_planning_events_approval_no_longer_allows_confirm(
    coordinator_client, db: Session, scene: Scene
):
    """The additional venue is cancelled, so every requirement is still booked: only the approval
    being out of date can stop the confirmation."""
    _approve_safety(db, scene.event)
    page = coordinator_client.get(f"/events/{scene.event.id}/safety-review").json()
    assert page["confirm_blockers"] == []

    _cancelled(coordinator_client, scene.extra)

    assert _fresh(db, scene.event).status == EventStatus.PLANNING
    assert _notices(db, scene.event.id, "EVENT_RETURNED_TO_PLANNING") == []
    response = coordinator_client.post(f"/events/{scene.event.id}/confirm")
    assert response.status_code == 409
    assert APPROVAL_OUT_OF_DATE in response.json()["detail"]


# --- AC7: a marked booking can be cancelled; a pending replacement blocks it -------------------
@pytest.mark.story("12.8", ac=7)
def test_a_booking_marked_venue_unavailable_can_be_cancelled(coordinator_client, db: Session):
    scenario = make_scenario(db, marked=True)

    body = _cancelled(coordinator_client, scenario.original)

    assert body["status"] == BookingStatus.CANCELLED
    assert body["release_cause"] == "COORDINATOR_CANCELLED"


@pytest.mark.story("12.8", ac=7)
def test_a_pending_replacement_blocks_the_cancel_until_it_is_withdrawn(
    coordinator_client, db: Session
):
    scenario = make_scenario(db, marked=True)
    replacement = add_pending_replacement(db, scenario)

    response = _cancel(coordinator_client, scenario.original)

    assert response.status_code == 409
    assert response.json()["detail"] == REPLACEMENT_PENDING.format(venue=scenario.alternative.name)
    _untouched(db, scenario.original, scenario.event, EventStatus.PLANNING)
    withdrawn = coordinator_client.post(f"/bookings/{replacement.id}/withdraw")
    assert withdrawn.status_code == 200, withdrawn.text
    assert _cancel(coordinator_client, scenario.original).status_code == 200


# --- AC8: who may cancel, and what the API refuses ---------------------------------------------
@pytest.mark.story("12.8", ac=8)
@pytest.mark.parametrize(
    "user",
    [
        Users.COORDINATOR_2,
        Users.ORGANISER,
        Users.VENUE_STAFF,
        Users.SAFETY_OFFICER,
        Users.LEAD,
        Users.TECH_SUPPORT,
        Users.ATTENDEE,
    ],
    ids=lambda user: user.role if user is not Users.COORDINATOR_2 else "OTHER_COORDINATOR",
)
def test_only_the_assigned_coordinator_can_cancel(login_as, db: Session, scene: Scene, user):
    response = _cancel(login_as(user), scene.first)

    assert response.status_code == 403
    if user is Users.COORDINATOR_2:
        assert response.json()["detail"] == NOT_ASSIGNED
    _untouched(db, scene.first, scene.event, EventStatus.PLANNING)


@pytest.mark.story("12.8", ac=8)
def test_a_signed_out_visitor_cannot_cancel(client, db: Session, scene: Scene):
    assert _cancel(client, scene.first).status_code == 401
    _untouched(db, scene.first, scene.event, EventStatus.PLANNING)


@pytest.mark.story("12.8", ac=8)
@pytest.mark.parametrize("reason", [None, "", "   "], ids=["missing", "empty", "spaces"])
def test_a_cancel_without_a_reason_is_refused(coordinator_client, db: Session, scene, reason):
    response = _cancel(coordinator_client, scene.first, reason)

    assert response.status_code == 422
    _untouched(db, scene.first, scene.event, EventStatus.PLANNING)


@pytest.mark.story("12.8", ac=8)
@pytest.mark.parametrize("status", ["PENDING", "REJECTED", "WITHDRAWN", "EXPIRED", "CANCELLED"])
def test_only_an_approved_booking_can_be_cancelled(
    coordinator_client, db: Session, scene: Scene, status: str
):
    """A pending request is withdrawn instead (12.2); a closed one has nothing left to release, so
    a second cancel tells Venue Staff nothing again."""
    if status == "CANCELLED":
        _cancelled(coordinator_client, scene.first)
    elif status == "PENDING":  # a pending request has no hold yet (ck_venue_bookings_hold_expiry)
        db.execute(
            text(
                "UPDATE venue_bookings SET status = 'PENDING', hold_expires_at = NULL,"
                " decided_by_id = NULL, decided_at = NULL WHERE id = :id"
            ),
            {"id": scene.first.id},
        )
    else:
        set_status(db, scene.first.id, status)
    told = len(_notices(db, scene.event.id, "BOOKING_RELEASED"))

    response = _cancel(coordinator_client, scene.first)

    assert response.status_code == 409
    assert response.json()["detail"] == NOT_APPROVED.format(status=status.lower())
    assert _fresh(db, scene.first).status == status
    assert len(_notices(db, scene.event.id, "BOOKING_RELEASED")) == told


@pytest.mark.story("12.8", ac=8)
def test_an_unknown_booking_is_not_found(coordinator_client):
    assert _cancel(coordinator_client, uuid.uuid4()).status_code == 404


# --- AC9: the database keeps the reason with the cause ----------------------------------------
@pytest.mark.story("12.8", ac=9)
def test_a_coordinator_cancellation_always_records_its_reason(db: Session, scene: Scene):
    sql = (
        "UPDATE venue_bookings SET status = 'CANCELLED', cancelled_at = now(),"
        " release_cause = 'COORDINATOR_CANCELLED', release_reason = :reason,"
        " released_by_id = :actor WHERE id = :id"
    )
    params = {"actor": Users.COORDINATOR.id, "id": scene.first.id}

    with pytest.raises(IntegrityError) as raised, db.begin_nested():
        db.execute(text(sql), {**params, "reason": None})
    assert "ck_venue_bookings_coordinator_cancel_reason" in str(raised.value.orig)
    with db.begin_nested():
        db.execute(text(sql), {**params, "reason": REASON})


# --- AC7/AC9: two writers on one booking ------------------------------------------------------
def _committed(engine: Engine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, list[uuid.UUID]]:
    """A marked approved booking on a venue of its own, with a free alternative, committed so two
    sessions can meet on its rows. Returns the event, the booking, the alternative venue and the
    venues to purge."""
    with Session(engine) as session:
        scenario = make_scenario(session, marked=True)
        session.commit()
        return (
            scenario.event.id,
            scenario.original.id,
            scenario.alternative.id,
            [scenario.original_venue.id, scenario.alternative.id],
        )


def _cancel_in(engine: Engine, booking_id: uuid.UUID, pids: dict[str, int]) -> str:
    """The coordinator's cancel in a session of its own: "cancelled", or the refusal's words."""
    from app.bookings.schemas import BookingCancellation

    with Session(engine) as session:
        pids["cancel"] = backend_pid(session)
        try:
            bookings_service.cancel_booking(
                session,
                booking_id,
                BookingCancellation(reason=REASON),
                actor=session.get(User, Users.COORDINATOR.id),
            )
        except bookings_service.BookingNotApproved as refused:
            return str(refused)
        except bookings_service.ReplacementPending as refused:
            return str(refused)
        return "cancelled"


def _race(engine: Engine, first, booking_id: uuid.UUID) -> str:
    """``first`` takes its lock and signals; the cancel starts and stands waiting on it; then
    ``first`` commits. Returns the cancel's outcome."""
    pids: dict[str, int] = {}
    holding, go = threading.Event(), threading.Event()

    def cancel() -> str:
        holding.wait(LOCK_WAIT_SECONDS)
        return _cancel_in(engine, booking_id, pids)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            winning = pool.submit(first, holding, go)
            cancelling = pool.submit(cancel)
            try:
                wait_until_waiting(engine, pids, "cancel")
            finally:
                go.set()
            winning.result(timeout=LOCK_WAIT_SECONDS)
            return cancelling.result(timeout=LOCK_WAIT_SECONDS)
    finally:
        go.set()


@pytest.mark.story("12.8", ac=9)
@pytest.mark.parametrize("rival", ["event-cancelled", "hold-expired"])
def test_a_release_that_lands_first_wins_and_the_cancel_is_refused(engine, rival: str):
    """The organiser's cancellation (6.2) holds the event, or the hold sweep holds the booking;
    the coordinator's cancel waits on that row, then finds the booking no longer approved.
    Nothing is released twice and Venue Staff hear once at most."""
    event_id, booking_id, _, venue_ids = _committed(engine)

    def cancel_event(holding: threading.Event, go: threading.Event) -> None:
        with Session(engine) as session:
            session.execute(
                select(Event.id).where(Event.id == event_id).with_for_update(key_share=True)
            )
            holding.set()
            go.wait(LOCK_WAIT_SECONDS)
            cancellations_service.cancel_event(
                session,
                event_id,
                actor=session.get(User, Users.ORGANISER.id),
                reason="Our sponsor withdrew.",
            )

    def expire(holding: threading.Event, go: threading.Event) -> None:
        with Session(engine) as session:
            session.execute(
                select(VenueBooking.id).where(VenueBooking.id == booking_id).with_for_update()
            )
            session.execute(
                update(VenueBooking)
                .where(VenueBooking.id == booking_id)
                .values(status=BookingStatus.EXPIRED, hold_expires_at=datetime.now(UTC))
            )
            holding.set()
            go.wait(LOCK_WAIT_SECONDS)
            session.commit()

    try:
        outcome = _race(engine, cancel_event if rival == "event-cancelled" else expire, booking_id)

        expected = "cancelled" if rival == "event-cancelled" else "expired"
        assert outcome == NOT_APPROVED.format(status=expected)
        with Session(engine) as session:
            booking = session.get(VenueBooking, booking_id)
            assert booking.release_cause != "COORDINATOR_CANCELLED"
            told = _notices(session, event_id, "BOOKING_RELEASED")
            assert len(told) == (1 if rival == "event-cancelled" else 0)
    finally:
        purge(engine, event_ids=[event_id], venue_ids=venue_ids)


@pytest.mark.story("12.8", ac=7)
def test_a_replacement_requested_first_blocks_the_cancel(engine):
    """The coordinator's other tab asks for a replacement, holding the booking and its event
    until it commits (12.6 locks the original, then the event); the cancel waits on them, then
    finds the replacement pending. A cancelled booking never has a pending replacement."""
    event_id, booking_id, alternative_id, venue_ids = _committed(engine)

    def replace(holding: threading.Event, go: threading.Event) -> None:
        with Session(engine) as session:
            original = bookings_service.get_booking_for_decision(session, booking_id)
            bookings_service.request_replacement_booking(
                session,
                original,
                BookingReplacementIn(venue_id=alternative_id),
                actor=session.get(User, Users.COORDINATOR.id),
            )
            holding.set()
            go.wait(LOCK_WAIT_SECONDS)
            session.commit()

    try:
        outcome = _race(engine, replace, booking_id)

        with Session(engine) as session:
            alternative = session.get(Venue, alternative_id).name
            assert outcome == REPLACEMENT_PENDING.format(venue=alternative)
            assert session.get(VenueBooking, booking_id).status == BookingStatus.APPROVED
    finally:
        purge(engine, event_ids=[event_id], venue_ids=venue_ids)
