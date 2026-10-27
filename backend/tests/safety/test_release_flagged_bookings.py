"""Story 21.3 - Release venue bookings named in a safety finding. The backlog's ACs, as written:

Happy path
1. When the Safety Officer requests changes (21.2 AC4), a finding about venue bookings can name
    one or more of the event's approved bookings that must change. The review page lists each
    approved booking with its venue, its requirement (or "Additional venue") and its booked
    period for the officer to choose from.
2. Recording the decision releases each named booking in the same step: it becomes Cancelled,
    its hold is released and the venue is free for other events over that period. The booking
    records that it was released by the safety review, with the finding's required change as the
    reason, and the event page shows it that way.
3. The event's other bookings and its equipment stay exactly as they were.
4. The assigned coordinator is notified once per decision, naming every released venue. Venue
    Staff are notified of each released booking, with the event, venue, period and the finding's
    required change. Technical Support and the organiser are not notified of the release; the
    organiser is already told of the decision (21.2 AC8).
5. Each venue requirement that lost its booking shows "Needs a venue" again (12.5), so the
    coordinator can request a new one. The event cannot be sent for its safety review again
    until every requirement has an approved booking (21.2 AC1). A released additional venue needs
    no replacement and does not block the review.

Boundary
6. Approve releases nothing. A finding about venue bookings that names no booking releases
    nothing, nor does a finding about anything else, such as crowd movement.
7. Only the event's approved bookings can be named, and only on a finding about venue bookings.
    Naming any other booking, or naming one on another kind of finding, is refused and nothing
    is written.

Edge
8. A released booking stays in the event's booking list and in the Venue Staff queue's Cancelled
    and All tabs as history. It cannot be approved again; the coordinator raises a new request,
    which may be for the same venue. Resubmitting with the same venue in its place still shows
    21.2 AC12's warning.
9. Each review round shows the Safety Officer and the coordinator which bookings it released. A
    booking named in two findings of one decision is released once.

Permission
10. Only a Safety Officer's Request changes decision releases bookings this way. The
    coordinator, the organiser and Venue Staff cannot undo a release.

Conflict
11. If a named booking's hold expires (12.7), or the event is cancelled (6.2), at the moment the
    decision is recorded, whichever is saved first wins. If the expiry or the cancellation wins,
    the decision is refused (409) saying why, and nothing is released or notified. Nothing is
    released twice and nobody is notified twice.

Every rule here is a backend case except what a user must see or click, which is
tests/e2e/safety-release.spec.ts. "Booked period" is the period including setup and teardown
(12.1 AC1). A case that checks a refusal first checks the release really happens, so it cannot
pass only because nothing is released yet. Written before the feature: the new fields are read
with ``.get`` so a missing one is a failed assertion.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, inspect, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings import service as bookings_service
from app.bookings.models import BookingStatus, VenueBooking
from app.cancellations import service as cancellations_service
from app.common.audit import AuditLog
from app.events.models import Event, EventEquipmentRequest, EventStatus
from app.notifications.models import Notification
from app.safety import service as safety_service
from app.safety.models import EventSafetyReview, SafetyReviewFinding
from app.safety.schemas import SafetyDecisionIn
from app.venues.models import Venue
from tests.support.factories import (
    approval_payload,
    make_booking,
    make_event,
    make_secured_event,
    make_user,
    make_venue,
    make_venue_requirement,
)
from tests.support.locks import LOCK_WAIT_SECONDS, backend_pid, wait_until_waiting
from tests.support.replacement import set_status
from tests.support.seed import Bookings, Users, Venues

CHANGE = "Book a room with a second exit."
OTHER_CHANGE = "Add marshals."
SETUP_MINUTES = 30
OFFICER_NAME = "Sam Safety"
VENUE_FINDING = {"factor_code": "CAPACITY_AND_LAYOUT", "arrangement": "VENUE_BOOKINGS"}
RELEASED_TITLE = "A venue booking was released"
NOT_AWAITING = "Only an event awaiting the safety check can be decided."
NOT_APPROVED_NOW = (
    "Not approved now: {bookings}. Your decision was not recorded. "
    "Reload the review and decide again."
)
COORDINATOR_RELEASED = (
    "{officer} asked for changes before it can pass and released these venue bookings: "
    "{bookings}. What must change: {changes}"
)
PLAIN_CHANGES = "{officer} asked for changes before it can pass: {changes}"
ADDITIONAL = "Additional venue"
PLENARY = "Plenary"
DAY_TWO = "Day 2 sessions"
REASON_SEPARATOR = " | "
MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"
FAR_FUTURE = datetime(2030, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Scene:
    """An Awaiting Safety Check event, secured as story 21.2 AC1 asks: ``first`` covers its
    requirement at Grand Hall, ``extra`` is an additional venue at Exhibition Foyer, and its
    accessories are one accepted equipment item. ``later`` is the second requirement's booking,
    in the three-booking scene only."""

    event: Event
    requirement_id: uuid.UUID
    first: VenueBooking
    extra: VenueBooking | None
    later: VenueBooking | None
    equipment: EventEquipmentRequest


def _approved_by_venue_staff(booking: VenueBooking) -> None:
    booking.decided_by_id = Users.VENUE_STAFF.id
    booking.decided_at = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _scene(db: Session, *, three: bool = False, with_extra: bool = True, **overrides: Any) -> Scene:
    """The scene of this story's cases. ``first`` has 30 minutes of setup, so its booked period
    (08:30-17:00 Singapore) is not the event's own times (09:00-17:00). With ``three`` the event
    has two requirements, "Plenary" and "Day 2 sessions", both at Grand Hall, one after the other.
    The additional venue starts after ``first`` so every list of bookings has one order."""
    secured = make_secured_event(
        db, status=EventStatus.AWAITING_SAFETY_CHECK, expected_attendance=60, **overrides
    )
    event, first, later = secured.event, secured.booking, None
    first.setup_minutes = SETUP_MINUTES
    _approved_by_venue_staff(first)
    extra_starts = event.starts_at + timedelta(hours=1)
    if three:
        db.execute(
            text("UPDATE venue_requirements SET name = :name WHERE id = :id"),
            {"name": PLENARY, "id": secured.requirement_id},
        )
        first.ends_at = event.starts_at + timedelta(hours=3)
        db.flush()
        second_requirement = make_venue_requirement(
            db,
            event.id,
            position=1,
            name=DAY_TWO,
            capacity=60,
            starts_at=event.starts_at + timedelta(hours=4),
            ends_at=event.ends_at,
        )
        later = make_booking(
            db,
            event_id=event.id,
            venue_id=first.venue_id,
            starts_at=event.starts_at + timedelta(hours=4),
            ends_at=event.ends_at,
            status=BookingStatus.APPROVED,
            venue_requirement_id=second_requirement,
            expected_attendance=60,
            hold_expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        _approved_by_venue_staff(later)
        extra_starts = event.starts_at + timedelta(hours=5)
    db.flush()
    db.refresh(first)
    extra = None
    if with_extra:
        extra = make_booking(
            db,
            event_id=event.id,
            venue_id=Venues.EXHIBITION_FOYER,
            starts_at=extra_starts,
            ends_at=event.ends_at,
            status=BookingStatus.APPROVED,
            venue_requirement_id=None,
            expected_attendance=60,
            hold_expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        _approved_by_venue_staff(extra)
        db.flush()
    return Scene(event, secured.requirement_id, first, extra, later, secured.equipment)


@pytest.fixture
def two_booked(db: Session) -> Scene:
    return _scene(db)


@pytest.fixture
def three_booked(db: Session) -> Scene:
    return _scene(db, three=True)


def _ids(*bookings: Any) -> list[str]:
    return [str(getattr(booking, "id", booking)) for booking in bookings]


def _finding(change: str = CHANGE, *bookings: Any, **overrides: Any) -> dict[str, Any]:
    return {**VENUE_FINDING, "required_change": change, "booking_ids": _ids(*bookings), **overrides}


def _decide(client, event_id: uuid.UUID, findings: list[dict[str, Any]], *, outcome="CHANGES"):
    """Post the officer's decision with the facts fingerprint of the page the officer read."""
    page = client.get(f"/safety-checks/{event_id}")
    fingerprint = page.json()["facts_fingerprint"] if page.status_code == 200 else "unread"
    return client.post(
        f"/safety-checks/{event_id}/decision",
        json={
            "outcome": "APPROVED" if outcome == "APPROVE" else "CHANGES_REQUESTED",
            "findings": findings,
            "facts_fingerprint": fingerprint,
        },
    )


def _release(login_as, scene: Scene, *named: Any, change: str = CHANGE) -> dict[str, Any]:
    """The officer requests changes naming ``named``; the decision's body."""
    response = _decide(login_as(Users.SAFETY_OFFICER), scene.event.id, [_finding(change, *named)])
    assert response.status_code == 200, response.text
    return response.json()


def _outcomes(login_as, event_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    """The event's booking list as its coordinator reads it, by booking id."""
    response = login_as(Users.COORDINATOR).get(f"/bookings/for-event/{event_id}")
    assert response.status_code == 200, response.text
    return {row["id"]: row for row in response.json()}


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


def _audit(db: Session, action: str, *entity_ids: uuid.UUID) -> list[AuditLog]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditLog).where(AuditLog.action == action, AuditLog.entity_id.in_(entity_ids))
        )
    )


def _columns(row: Any) -> dict[str, Any]:
    return {column.key: getattr(row, column.key) for column in inspect(row).mapper.column_attrs}


def _fresh(db: Session, row: Any) -> Any:
    db.expire_all()
    return db.get(type(row), row.id)


def _reviews(db: Session, event_id: uuid.UUID) -> int:
    db.expire_all()
    return len(
        list(db.scalars(select(EventSafetyReview).where(EventSafetyReview.event_id == event_id)))
    )


def _nothing_written(db: Session, scene: Scene, *bookings: VenueBooking) -> None:
    """A refused decision left the event awaiting, no review, no notice, every booking approved."""
    db.expire_all()
    assert db.get(Event, scene.event.id).status == EventStatus.AWAITING_SAFETY_CHECK
    assert _reviews(db, scene.event.id) == 0
    for kind in ("BOOKING_RELEASED", "SAFETY_CHANGES_REQUESTED"):
        assert _notices(db, scene.event.id, kind) == []
    for booking in bookings:
        assert db.get(VenueBooking, booking.id).status == BookingStatus.APPROVED


def _approved(db: Session, event: Event, *, venue: Venue | None = None, **overrides: Any):
    """An additional-venue booking of ``event`` at a fresh venue: approved, unless ``overrides``
    say otherwise (they replace any of the defaults)."""
    fields: dict[str, Any] = {
        "event_id": event.id,
        "venue_id": (venue or make_venue(db)).id,
        "starts_at": event.starts_at,
        "ends_at": event.ends_at,
        "status": BookingStatus.APPROVED,
        "expected_attendance": 60,
        "hold_expires_at": datetime.now(UTC) + timedelta(days=30),
        "decided_by_id": Users.VENUE_STAFF.id,
        "decided_at": datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
    }
    return make_booking(db, **{**fields, **overrides})


def _venue_name(db: Session, booking: VenueBooking) -> str:
    return db.get(Venue, booking.venue_id).name


# --- AC1: the review page lists the bookings; a finding can name them --------------------------
@pytest.mark.story("21.3", ac=1)
def test_review_page_lists_each_approved_booking_with_what_the_officer_needs(
    login_as, db: Session, two_booked: Scene
):
    scene = two_booked
    pending = _approved(db, scene.event, status=BookingStatus.PENDING, hold_expires_at=None)
    withdrawn = _approved(db, scene.event, status=BookingStatus.WITHDRAWN, hold_expires_at=None)
    cancelled = _approved(db, scene.event, status=BookingStatus.CANCELLED, hold_expires_at=None)

    response = login_as(Users.SAFETY_OFFICER).get(f"/safety-checks/{scene.event.id}")

    assert response.status_code == 200, response.text
    venues = response.json()["venues"]
    assert [row.get("booking_id") for row in venues] == _ids(scene.first, scene.extra)
    assert [row.get("requirement_name") for row in venues] == ["Main venue", None]
    assert [row["venue"]["name"] for row in venues] == ["Grand Hall", "Exhibition Foyer"]
    for row, booking in zip(venues, (scene.first, scene.extra), strict=True):
        assert datetime.fromisoformat(row["starts_at"]) == booking.starts_at
        assert datetime.fromisoformat(row["ends_at"]) == booking.ends_at
    shown = {row.get("booking_id") for row in venues}
    assert shown.isdisjoint(_ids(pending, withdrawn, cancelled))


@pytest.mark.story("21.3", ac=1)
def test_a_finding_can_name_one_or_more_approved_bookings(login_as, two_booked: Scene):
    scene = two_booked

    body = _release(login_as, scene, scene.first, scene.extra)

    [finding] = body["previous_reviews"][0]["findings"]
    assert finding.get("released_bookings") == [
        {
            "booking_id": str(scene.first.id),
            "venue_name": "Grand Hall",
            "requirement_name": "Main venue",
        },
        {
            "booking_id": str(scene.extra.id),
            "venue_name": "Exhibition Foyer",
            "requirement_name": None,
        },
    ]


# --- AC2: recording the decision releases each named booking ----------------------------------
@pytest.mark.story("21.3", ac=2)
def test_each_named_booking_becomes_cancelled_and_records_why(
    login_as, db: Session, two_booked: Scene
):
    scene = two_booked
    approved_at = scene.first.decided_at

    body = _release(login_as, scene, scene.first, scene.extra)

    reviewed_at = datetime.fromisoformat(body["previous_reviews"][0]["reviewed_at"])
    outcomes = _outcomes(login_as, scene.event.id)
    for booking in (scene.first, scene.extra):
        row = outcomes[str(booking.id)]
        assert row["status"] == BookingStatus.CANCELLED
        assert row.get("release_cause") == "SAFETY_REVIEW"
        assert row.get("release_reason") == CHANGE
        assert datetime.fromisoformat(row["cancelled_at"]) == reviewed_at
    assert datetime.fromisoformat(outcomes[str(scene.first.id)]["decided_at"]) == approved_at
    assert _fresh(db, scene.event).status == EventStatus.PLANNING


@pytest.mark.story("21.3", ac=2)
def test_the_hold_is_released_and_the_venue_is_free(login_as, db: Session, two_booked: Scene):
    scene = two_booked
    other = make_event(db, status=EventStatus.PLANNING)

    _release(login_as, scene, scene.first)

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
        pytest.fail("the venue is still held after the decision")
    bookings_service.sweep_holds(db, now=datetime.now(UTC) + timedelta(days=60))
    assert _fresh(db, scene.first).status == BookingStatus.CANCELLED
    for kind in ("BOOKING_HOLD_EXPIRED", "BOOKING_HOLD_EXPIRING"):
        assert [
            n for n in _notices(db, scene.event.id, kind) if n.related_entity_id == scene.first.id
        ] == []


@pytest.mark.story("21.3", ac=2)
def test_a_failed_decision_releases_nothing(engine):
    """Recorded in the same step: a refusal after the release was written takes it back. Run on
    committed rows, as the refusal rolls its session back. Passes before the feature, as nothing is
    released yet; it can only fail once something is."""
    event_id, booking_id, _, venue_id, type_id = _committed_scene(engine)
    payload = _payload(engine, event_id, booking_id)
    payload.findings[0].factor_code = "NOT_A_FACTOR"
    try:
        with Session(engine) as session, pytest.raises(safety_service.UnknownSafetyFactor):
            safety_service.decide_safety_check(
                session, event_id, payload, actor=session.get(User, Users.SAFETY_OFFICER.id)
            )

        with Session(engine) as session:
            assert session.get(Event, event_id).status == EventStatus.AWAITING_SAFETY_CHECK
            assert session.get(VenueBooking, booking_id).status == BookingStatus.APPROVED
            assert _reviews(session, event_id) == 0
            assert _notices(session, event_id, "BOOKING_RELEASED") == []
            assert _audit(session, "BOOKING_RELEASED", booking_id) == []
    finally:
        _delete_committed(engine, event_id, booking_id, venue_id=venue_id, type_id=type_id)


@pytest.mark.story("21.3", ac=2)
def test_the_event_page_reads_the_release(login_as, two_booked: Scene):
    scene = two_booked

    _release(login_as, scene, scene.first)

    coordinator = login_as(Users.COORDINATOR)
    listed = coordinator.get(f"/bookings/for-event/{scene.event.id}").json()
    one = coordinator.get(f"/bookings/{scene.first.id}").json()
    assert {row["id"]: row.get("release_cause") for row in listed}[str(scene.first.id)] == (
        "SAFETY_REVIEW"
    )
    assert (one.get("release_cause"), one.get("release_reason")) == ("SAFETY_REVIEW", CHANGE)


def _violates(db: Session, constraint: str, sql: str, **params: Any) -> None:
    with pytest.raises(IntegrityError) as raised, db.begin_nested():
        db.execute(text(sql), params)
    assert constraint in str(raised.value.orig)


@pytest.mark.story("21.3", ac=2)
def test_the_release_columns_obey_their_constraints(db: Session, two_booked: Scene):
    scene = two_booked
    officer = Users.SAFETY_OFFICER.id
    fields = "ck_venue_bookings_release_fields"
    set_status(db, scene.extra.id, BookingStatus.CANCELLED)

    _violates(
        db,
        fields,
        "UPDATE venue_bookings SET release_cause = 'SAFETY_REVIEW', release_reason = 'x',"
        " released_by_id = :officer WHERE id = :id",
        id=scene.first.id,
        officer=officer,
    )
    _violates(
        db,
        fields,
        "UPDATE venue_bookings SET release_reason = 'x' WHERE id = :id",
        id=scene.extra.id,
    )
    _violates(
        db,
        fields,
        "UPDATE venue_bookings SET released_by_id = :officer WHERE id = :id",
        id=scene.extra.id,
        officer=officer,
    )
    _violates(
        db,
        "ck_venue_bookings_safety_release_reason",
        "UPDATE venue_bookings SET release_cause = 'SAFETY_REVIEW' WHERE id = :id",
        id=scene.extra.id,
    )
    _violates(
        db,
        "ck_venue_bookings_release_cause",
        "UPDATE venue_bookings SET release_cause = 'BOGUS', release_reason = 'x' WHERE id = :id",
        id=scene.extra.id,
    )
    # A cancelled booking with no cause is allowed: tests and the seed write them.
    assert (
        db.execute(
            text("SELECT release_cause FROM venue_bookings WHERE id = :id"), {"id": scene.extra.id}
        ).scalar()
        is None
    )


@pytest.mark.story("21.3", ac=2)
def test_a_finding_links_to_real_bookings_only_and_goes_with_its_event(
    db: Session, two_booked: Scene
):
    scene = two_booked
    review = EventSafetyReview(
        event_id=scene.event.id,
        reviewed_by_id=Users.SAFETY_OFFICER.id,
        outcome="CHANGES_REQUESTED",
        facts={},
        findings=[
            SafetyReviewFinding(
                position=0,
                factor_code="CAPACITY_AND_LAYOUT",
                arrangement="VENUE_BOOKINGS",
                required_change=CHANGE,
            )
        ],
    )
    db.add(review)
    db.flush()
    finding_id = review.findings[0].id
    link = "INSERT INTO event_safety_finding_bookings (finding_id, booking_id) VALUES (:f, :b)"

    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(text(link), {"f": finding_id, "b": uuid.uuid4()})
    db.execute(text(link), {"f": finding_id, "b": scene.first.id})
    db.execute(text("DELETE FROM events WHERE id = :id"), {"id": scene.event.id})

    assert (
        db.execute(
            text("SELECT count(*) FROM event_safety_finding_bookings WHERE finding_id = :f"),
            {"f": finding_id},
        ).scalar()
        == 0
    )


@pytest.mark.story("21.3", ac=2)
def test_the_other_release_paths_record_their_cause_and_actor(db: Session, two_booked: Scene):
    """The one ``release_booking`` every story uses records who released a booking and why,
    whatever the cause, and says what it said before to Venue Staff."""
    scene = two_booked
    staff = make_user(db, role="VENUE_STAFF")
    organiser = db.get(User, Users.ORGANISER.id)
    approver = db.get(User, Users.VENUE_STAFF.id)
    event_name = scene.event.name
    cancelled = _approved(db, scene.event)
    changed = _approved(db, scene.event)
    replaced = _approved(db, scene.event)
    replacement = _approved(db, scene.event, venue=db.get(Venue, Venues.BOARDROOM))
    at = datetime.now(UTC)

    assert bookings_service.release_booking(
        db,
        cancelled,
        actor=organiser,
        cause="EVENT_CANCELLED",
        because="its event was cancelled",
        details={"cause": "EVENT_CANCELLED"},
        at=at,
    )
    assert bookings_service.release_booking(
        db,
        changed,
        actor=organiser,
        cause="CHANGE_APPROVED",
        because="an approved change to the event's attendance no longer fits it",
        details={"change": "attendance"},
        at=at,
    )
    assert bookings_service.release_booking(
        db, replaced, actor=approver, cause="REPLACED", replacement=replacement
    )

    for booking, cause, actor in (
        (cancelled, "EVENT_CANCELLED", organiser),
        (changed, "CHANGE_APPROVED", organiser),
        (replaced, "REPLACED", approver),
    ):
        row = _fresh(db, booking)
        assert row.status == BookingStatus.CANCELLED
        assert row.release_cause == cause
        assert row.released_by_id == actor.id
    assert _fresh(db, cancelled).cancelled_at == at
    assert _fresh(db, replaced).cancelled_at is None
    assert _fresh(db, replaced).decision_reason == f"Replaced by {_venue_name(db, replacement)}"
    assert _fresh(db, replaced).replaced_by_booking_id == replacement.id
    messages = {
        notice.related_entity_id: (notice.notification_type, notice.title, notice.message)
        for notice in db.scalars(select(Notification).where(Notification.recipient_id == staff.id))
    }
    assert messages[cancelled.id] == (
        "BOOKING_RELEASED",
        RELEASED_TITLE,
        f'The booking of {_venue_name(db, cancelled)} for "{event_name}" was released: '
        "its event was cancelled.",
    )
    assert messages[changed.id][2] == (
        f'The booking of {_venue_name(db, changed)} for "{event_name}" was released: '
        "an approved change to the event's attendance no longer fits it."
    )
    assert messages[replaced.id] == (
        "BOOKING_REPLACED",
        f"A booking of {_venue_name(db, replaced)} was released",
        f'The booking of {_venue_name(db, replaced)} for "{event_name}" was released: '
        f"{_venue_name(db, replacement)} was approved as its replacement.",
    )


@pytest.mark.story("21.3", ac=2)
def test_a_release_is_audited_with_who_why_and_which_booking(
    login_as, db: Session, two_booked: Scene
):
    scene = two_booked

    body = _release(login_as, scene, scene.first, scene.extra)

    rows = _audit(db, "BOOKING_RELEASED", scene.first.id, scene.extra.id)
    assert sorted(row.entity_id for row in rows) == sorted([scene.first.id, scene.extra.id])
    for row in rows:
        booking = scene.first if row.entity_id == scene.first.id else scene.extra
        assert row.entity_type == "venue_booking"
        assert row.actor_id == Users.SAFETY_OFFICER.id
        assert row.details == {
            "venue_id": str(booking.venue_id),
            "event_id": str(scene.event.id),
            "cause": "SAFETY_REVIEW",
            "reason": CHANGE,
            "review_id": body["previous_reviews"][0]["id"],
        }
    [decision] = _audit(db, "SAFETY_CHANGES_REQUESTED", scene.event.id)
    assert decision.details == {"findings": 1}


def _backfill() -> str:
    """The migration's backfill statements, which a database migrated before the migration
    runs when it is applied (as tests/equipment/test_equipment_request_migration.py runs 014)."""
    found = sorted(MIGRATIONS.glob("*_safety_release_bookings.sql"))
    assert found, "the migration for story 21.3 does not exist yet"
    return (
        found[0]
        .read_text(encoding="utf-8")
        .split("-- backfill start")[1]
        .split("-- backfill end")[0]
    )


def _cancelled_without_cause(db: Session, event: Event, **overrides: Any) -> VenueBooking:
    return _approved(
        db, event, **{"status": BookingStatus.CANCELLED, "hold_expires_at": None, **overrides}
    )


@pytest.mark.story("21.3", ac=2)
def test_the_migration_backfills_the_cause_of_bookings_cancelled_before_it(
    db: Session, two_booked: Scene
):
    planning = make_event(db, status=EventStatus.PLANNING)
    cancelled_event = make_event(
        db,
        status=EventStatus.CANCELLED,
        cancelled_at=datetime(2026, 10, 2, tzinfo=UTC),
        cancelled_by_id=Users.ORGANISER.id,
        cancellation_reason="Our sponsor withdrew.",
    )
    original = _cancelled_without_cause(db, planning)
    replacement = _approved(db, planning, replaces_booking_id=original.id)
    db.execute(
        text("UPDATE venue_bookings SET replaced_by_booking_id = :r WHERE id = :o"),
        {"r": replacement.id, "o": original.id},
    )
    with_event = _cancelled_without_cause(db, cancelled_event)
    plain = _cancelled_without_cause(db, planning)
    approved, withdrawn = (
        two_booked.first,
        _approved(db, planning, status="WITHDRAWN", hold_expires_at=None),
    )
    db.flush()

    db.connection().exec_driver_sql(_backfill())
    db.connection().exec_driver_sql(_backfill())

    def read(booking: VenueBooking) -> tuple[Any, Any]:
        return tuple(
            db.execute(
                text("SELECT release_cause, released_by_id FROM venue_bookings WHERE id = :id"),
                {"id": booking.id},
            ).one()
        )

    assert read(original) == ("REPLACED", Users.VENUE_STAFF.id)
    assert read(with_event) == ("EVENT_CANCELLED", Users.ORGANISER.id)
    assert read(plain) == ("CHANGE_APPROVED", None)
    assert read(approved) == (None, None)
    assert read(withdrawn) == (None, None)


@pytest.mark.story("21.3", ac=2)
def test_every_seeded_cancelled_booking_has_a_cause(db: Session):
    rows = db.execute(
        text(
            "SELECT id, release_cause, released_by_id FROM venue_bookings"
            " WHERE status = 'CANCELLED'"
        )
    ).all()

    assert (
        Bookings.CANCELLED_CHARITY_RUN_PAVILION,
        "CHANGE_APPROVED",
        None,
    ) in [tuple(row) for row in rows]
    assert [row.id for row in rows if row.release_cause is None] == []


# --- AC3: everything else stays as it was -----------------------------------------------------
@pytest.mark.story("21.3", ac=3)
def test_other_bookings_and_equipment_are_untouched(login_as, db: Session, three_booked: Scene):
    scene = three_booked
    before = [_columns(row) for row in (scene.extra, scene.later, scene.equipment)]

    _release(login_as, scene, scene.first)

    assert _fresh(db, scene.first).status == BookingStatus.CANCELLED
    after = [_columns(_fresh(db, row)) for row in (scene.extra, scene.later, scene.equipment)]
    assert after == before
    assert _notices(db, scene.event.id, "EQUIPMENT_WITHDRAWN") == []


# --- AC4: who is told, and what ---------------------------------------------------------------
@pytest.mark.story("21.3", ac=4)
def test_the_coordinator_is_told_once_naming_every_released_booking(
    login_as, db: Session, three_booked: Scene
):
    scene = three_booked
    officer = login_as(Users.SAFETY_OFFICER)

    response = _decide(
        officer,
        scene.event.id,
        [_finding(CHANGE, scene.first, scene.extra), _finding(OTHER_CHANGE, scene.later)],
    )

    assert response.status_code == 200, response.text
    [notice] = [
        n
        for n in _notices(db, scene.event.id, "SAFETY_CHANGES_REQUESTED")
        if n.recipient_id == Users.COORDINATOR.id
    ]
    assert notice.title == f'Safety changes requested for "{scene.event.name}"'
    assert notice.message == COORDINATOR_RELEASED.format(
        officer=OFFICER_NAME,
        bookings=f"Grand Hall ({PLENARY}), Grand Hall ({DAY_TWO}), Exhibition Foyer ({ADDITIONAL})",
        changes=f"{CHANGE}; {OTHER_CHANGE}",
    )


@pytest.mark.story("21.3", ac=4)
def test_the_organiser_is_told_of_the_decision_but_not_the_release(
    login_as, db: Session, two_booked: Scene
):
    scene = two_booked

    _release(login_as, scene, scene.first, scene.extra)

    [notice] = [
        n
        for n in _notices(db, scene.event.id, "SAFETY_CHANGES_REQUESTED")
        if n.recipient_id == Users.ORGANISER.id
    ]
    assert notice.message == PLAIN_CHANGES.format(officer=OFFICER_NAME, changes=CHANGE)
    assert [
        n
        for n in _notices(db, scene.event.id, "BOOKING_RELEASED")
        if n.recipient_id == Users.ORGANISER.id
    ] == []
    assert _fresh(db, scene.first).status == BookingStatus.CANCELLED


@pytest.mark.story("21.3", ac=4)
def test_venue_staff_are_told_of_each_released_booking(login_as, db: Session, two_booked: Scene):
    scene = two_booked
    staff = make_user(db, role="VENUE_STAFF")

    _release(login_as, scene, scene.first, scene.extra)

    notices = _notices(db, scene.event.id, "BOOKING_RELEASED")
    expected_message = {
        scene.first.id: (
            f'The booking of Grand Hall for "{scene.event.name}" on Mon 4 Mar 2030 '
            f"from 08:30 to 17:00 was released by the safety review. Required change: {CHANGE}"
        ),
        scene.extra.id: (
            f'The booking of Exhibition Foyer for "{scene.event.name}" on Mon 4 Mar 2030 '
            f"from 10:00 to 17:00 was released by the safety review. Required change: {CHANGE}"
        ),
    }
    for member in (Users.VENUE_STAFF.id, staff.id):
        mine = {n.related_entity_id: n for n in notices if n.recipient_id == member}
        assert set(mine) == set(expected_message)
        for booking_id, notice in mine.items():
            assert notice.title == RELEASED_TITLE
            assert notice.related_entity_type == "venue_booking"
            assert notice.message == expected_message[booking_id]
    assert Users.INACTIVE.id not in {n.recipient_id for n in notices}
    listed = login_as(Users.VENUE_STAFF).get("/notifications").json()
    [opened] = [n for n in listed if n["related_entity_id"] == str(scene.first.id)]
    assert opened["target"] == {"kind": "booking_request", "id": str(scene.first.id)}


@pytest.mark.story("21.3", ac=4)
def test_nobody_else_is_told(login_as, db: Session, two_booked: Scene):
    scene = two_booked

    _release(login_as, scene, scene.first, scene.extra)

    assert _recipients(db, scene.event.id, "SAFETY_CHANGES_REQUESTED") == sorted(
        [Users.COORDINATOR.id, Users.ORGANISER.id]
    )
    assert _recipients(db, scene.event.id, "BOOKING_RELEASED") == sorted([Users.VENUE_STAFF.id] * 2)
    assert _notices(db, scene.event.id, "EQUIPMENT_WITHDRAWN") == []
    for kind in ("BOOKING_RELEASED", "SAFETY_CHANGES_REQUESTED", "EQUIPMENT_WITHDRAWN"):
        told = set(_recipients(db, scene.event.id, kind))
        assert told.isdisjoint(
            {Users.TECH_SUPPORT.id, Users.LEAD.id, Users.ATTENDEE.id, Users.SAFETY_OFFICER.id}
        )


@pytest.mark.story("21.3", ac=4)
def test_with_no_coordinator_the_release_still_happens(login_as, db: Session):
    scene = _scene(db, assigned_coordinator_id=None)

    _release(login_as, scene, scene.first)

    assert _fresh(db, scene.first).status == BookingStatus.CANCELLED
    assert _recipients(db, scene.event.id, "BOOKING_RELEASED") == [Users.VENUE_STAFF.id]
    [notice] = _notices(db, scene.event.id, "SAFETY_CHANGES_REQUESTED")
    assert notice.recipient_id == Users.ORGANISER.id
    assert notice.message == PLAIN_CHANGES.format(officer=OFFICER_NAME, changes=CHANGE)


# --- AC5: Needs a venue again; the review is blocked; an additional venue is not --------------
@pytest.mark.story("21.3", ac=5)
def test_a_released_requirement_booking_blocks_the_next_review(
    login_as, db: Session, two_booked: Scene
):
    scene = two_booked

    _release(login_as, scene, scene.first)

    coordinator = login_as(Users.COORDINATOR)
    page = coordinator.get(f"/events/{scene.event.id}/safety-review").json()
    assert page["request_blockers"] == ["Main venue has no approved venue booking."]
    refused = coordinator.post(f"/safety-checks/{scene.event.id}/request", json={})
    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "Secure every arrangement before requesting a safety review. "
        "Main venue has no approved venue booking."
    )
    assert _fresh(db, scene.event).status == EventStatus.PLANNING


@pytest.mark.story("21.3", ac=5)
def test_the_coordinator_can_request_a_new_venue_once_it_is_released(login_as, two_booked: Scene):
    """Grand Hall holds 400 and is open 08:00-22:00; the requirement asks for 60 people from
    09:00 to 17:00 with no layout or facility, so nothing in 11.1 or the opening hours refuses
    the request: it is refused only while the booking stands."""
    scene = two_booked

    _release(login_as, scene, scene.first)

    response = login_as(Users.COORDINATOR).post(
        "/bookings",
        json={
            "event_id": str(scene.event.id),
            "venue_id": str(Venues.GRAND_HALL),
            "venue_requirement_id": str(scene.requirement_id),
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == BookingStatus.PENDING


@pytest.mark.story("21.3", ac=5)
def test_a_released_additional_venue_does_not_block_the_review(
    login_as, db: Session, two_booked: Scene
):
    scene = two_booked

    _release(login_as, scene, scene.extra)

    coordinator = login_as(Users.COORDINATOR)
    assert (
        coordinator.get(f"/events/{scene.event.id}/safety-review").json()["request_blockers"] == []
    )
    response = coordinator.post(f"/safety-checks/{scene.event.id}/request", json={})
    assert response.status_code == 200, response.text
    assert _fresh(db, scene.event).status == EventStatus.AWAITING_SAFETY_CHECK
    assert _fresh(db, scene.extra).status == BookingStatus.CANCELLED


# --- AC6: what releases nothing ---------------------------------------------------------------
@pytest.mark.story("21.3", ac=6)
def test_approve_releases_nothing(login_as, db: Session, two_booked: Scene):
    scene = two_booked

    response = _decide(login_as(Users.SAFETY_OFFICER), scene.event.id, [], outcome="APPROVE")

    assert response.status_code == 200, response.text
    for booking in (scene.first, scene.extra):
        row = _fresh(db, booking)
        assert (row.status, row.cancelled_at) == (BookingStatus.APPROVED, None)
    assert _notices(db, scene.event.id, "BOOKING_RELEASED") == []
    texts = {n.message for n in _notices(db, scene.event.id, "SAFETY_APPROVED")}
    assert texts == {f"{OFFICER_NAME} approved it. The coordinator can now confirm the event."}


@pytest.mark.story("21.3", ac=6)
@pytest.mark.parametrize(
    "findings",
    [
        [_finding(CHANGE)],
        [_finding(CHANGE, arrangement="EQUIPMENT")],
        [_finding(CHANGE, arrangement=None, factor_code="CROWD_MOVEMENT")],
        [
            _finding(CHANGE),
            _finding(OTHER_CHANGE, arrangement="EQUIPMENT"),
            _finding("Add marshals at the doors.", arrangement=None, factor_code="CROWD_MOVEMENT"),
        ],
    ],
    ids=["venue-names-none", "equipment", "crowd-movement", "all-three"],
)
def test_a_finding_that_names_no_booking_releases_nothing(
    login_as, db: Session, two_booked: Scene, findings
):
    scene = two_booked

    response = _decide(login_as(Users.SAFETY_OFFICER), scene.event.id, findings)

    assert response.status_code == 200, response.text
    for booking in (scene.first, scene.extra):
        assert _fresh(db, booking).status == BookingStatus.APPROVED
    assert _notices(db, scene.event.id, "BOOKING_RELEASED") == []
    changes = "; ".join(finding["required_change"] for finding in findings)
    expected = PLAIN_CHANGES.format(officer=OFFICER_NAME, changes=changes)
    assert {n.message for n in _notices(db, scene.event.id, "SAFETY_CHANGES_REQUESTED")} == {
        expected
    }


# --- AC7: only approved bookings of the event, only on a venue finding ------------------------
@pytest.mark.story("21.3", ac=7)
@pytest.mark.parametrize("kind", ["another-event", "unknown"])
def test_a_booking_that_could_never_be_named_is_refused_with_422(
    login_as, db: Session, two_booked: Scene, kind
):
    scene = two_booked
    if kind == "unknown":
        stranger: Any = uuid.uuid4()
    else:
        stranger = make_secured_event(db, venue_id=make_venue(db).id).booking

    response = _decide(
        login_as(Users.SAFETY_OFFICER), scene.event.id, [_finding(CHANGE, scene.first, stranger)]
    )

    assert response.status_code == 422
    assert "Only this event's bookings can be named." in response.text
    _nothing_written(db, scene, scene.first, scene.extra)


@pytest.mark.story("21.3", ac=7)
@pytest.mark.parametrize("status", ["PENDING", "WITHDRAWN", "REJECTED", "EXPIRED", "CANCELLED"])
def test_a_booking_that_is_not_approved_now_is_refused_with_409(
    login_as, db: Session, two_booked: Scene, status
):
    scene = two_booked
    hold = datetime(2026, 1, 1, tzinfo=UTC) if status == "EXPIRED" else None
    stale = _approved(db, scene.event, status=status, hold_expires_at=hold)

    response = _decide(
        login_as(Users.SAFETY_OFFICER), scene.event.id, [_finding(CHANGE, scene.first, stale)]
    )

    assert response.status_code == 409
    assert response.json()["detail"] == NOT_APPROVED_NOW.format(
        bookings=f"{_venue_name(db, stale)} ({ADDITIONAL})"
    )
    _nothing_written(db, scene, scene.first, scene.extra)


@pytest.mark.story("21.3", ac=7)
def test_every_named_booking_that_is_not_approved_is_listed(
    login_as, db: Session, two_booked: Scene
):
    scene = two_booked
    event = scene.event
    pending = _approved(db, event, status="PENDING", hold_expires_at=None)
    withdrawn = _approved(
        db,
        event,
        status="WITHDRAWN",
        hold_expires_at=None,
        starts_at=event.starts_at + timedelta(hours=1),
    )

    response = _decide(
        login_as(Users.SAFETY_OFFICER),
        event.id,
        [_finding(CHANGE, scene.first, withdrawn, pending)],
    )

    assert response.status_code == 409
    assert response.json()["detail"] == NOT_APPROVED_NOW.format(
        bookings=", ".join(
            f"{_venue_name(db, booking)} ({ADDITIONAL})" for booking in (pending, withdrawn)
        )
    )
    _nothing_written(db, scene, scene.first, scene.extra)


@pytest.mark.story("21.3", ac=7)
@pytest.mark.parametrize("arrangement", [None, "EQUIPMENT"])
def test_only_a_finding_about_venue_bookings_can_name_bookings(
    login_as, db: Session, two_booked: Scene, arrangement
):
    scene = two_booked

    response = _decide(
        login_as(Users.SAFETY_OFFICER),
        scene.event.id,
        [_finding(CHANGE, scene.first, arrangement=arrangement)],
    )

    assert response.status_code == 422
    assert "Only a finding about venue bookings can name bookings." in response.text
    _nothing_written(db, scene, scene.first, scene.extra)


# --- AC8: history, no second approval, a new request, the warning ------------------------------
@pytest.mark.story("21.3", ac=8)
def test_a_released_booking_stays_in_both_lists(login_as, db: Session, two_booked: Scene):
    scene = two_booked
    staff = login_as(Users.VENUE_STAFF)
    before = staff.get("/bookings").json()["counts"]

    _release(login_as, scene, scene.first)

    assert str(scene.first.id) in _outcomes(login_as, scene.event.id)
    staff = login_as(Users.VENUE_STAFF)
    cancelled = staff.get("/bookings", params={"status": "CANCELLED", "limit": 100}).json()
    everything = staff.get("/bookings", params={"limit": 100}).json()
    for listing in (cancelled, everything):
        [entry] = [item for item in listing["items"] if item["id"] == str(scene.first.id)]
        assert (entry.get("release_cause"), entry.get("release_reason")) == (
            "SAFETY_REVIEW",
            CHANGE,
        )
    assert cancelled["counts"]["cancelled"] == before["cancelled"] + 1
    assert cancelled["counts"]["approved"] == before["approved"] - 1


@pytest.mark.story("21.3", ac=8)
def test_a_released_booking_cannot_be_approved_again(login_as, db: Session, two_booked: Scene):
    scene = two_booked
    _release(login_as, scene, scene.first)

    response = login_as(Users.VENUE_STAFF).post(
        f"/bookings/{scene.first.id}/approve", json=approval_payload()
    )

    assert response.status_code == 409
    assert (
        response.json()["detail"] == "This request is already CANCELLED, so it cannot be approved."
    )
    assert _fresh(db, scene.first).status == BookingStatus.CANCELLED


@pytest.mark.story("21.3", ac=8)
def test_resubmitting_with_the_same_venue_still_warns(login_as, db: Session, two_booked: Scene):
    scene = two_booked
    _release(login_as, scene, scene.first)
    try:
        with db.begin_nested():
            make_booking(
                db,
                event_id=scene.event.id,
                venue_id=scene.first.venue_id,
                starts_at=scene.first.starts_at,
                ends_at=scene.first.ends_at,
                status=BookingStatus.APPROVED,
                venue_requirement_id=scene.requirement_id,
                expected_attendance=60,
                hold_expires_at=datetime.now(UTC) + timedelta(days=30),
            )
    except IntegrityError:
        pytest.fail("the venue is still held after the decision")
    coordinator = login_as(Users.COORDINATOR)

    warned = coordinator.post(f"/safety-checks/{scene.event.id}/request", json={})

    assert warned.status_code == 409
    detail = warned.json()["detail"]
    assert detail["unchanged_arrangements"] == ["VENUE_BOOKINGS"]
    assert detail["message"] == (
        "The venue bookings the Safety Officer flagged have not changed since their review."
    )
    sent = coordinator.post(
        f"/safety-checks/{scene.event.id}/request", json={"acknowledge_unchanged": True}
    )
    assert sent.status_code == 200, sent.text


# --- AC9: each round shows what it released; once per decision --------------------------------
@pytest.mark.story("21.3", ac=9)
def test_each_round_lists_its_released_bookings_to_officer_coordinator_and_organiser(
    login_as, db: Session, two_booked: Scene
):
    scene = two_booked
    first_round = _release(login_as, scene, scene.first)
    assert _fresh(db, scene.first).status == BookingStatus.CANCELLED
    other = db.get(Venue, Venues.BOARDROOM)
    rebooked = _approved(db, scene.event, venue=other, venue_requirement_id=scene.requirement_id)
    coordinator = login_as(Users.COORDINATOR)
    assert coordinator.post(f"/safety-checks/{scene.event.id}/request", json={}).status_code == 200
    assert first_round["previous_reviews"][0]["findings"][0].get("released_bookings")

    second_round = _release(login_as, scene, rebooked, change=OTHER_CHANGE)

    def released(reviews: list[dict[str, Any]]) -> list[list[str]]:
        return [
            [
                item["venue_name"]
                for finding in review["findings"]
                for item in finding.get("released_bookings", [])
            ]
            for review in reviews
        ]

    assert released(second_round["previous_reviews"]) == [[other.name], ["Grand Hall"]]
    for viewer in (Users.COORDINATOR, Users.ORGANISER):
        latest = (
            login_as(viewer).get(f"/events/{scene.event.id}/safety-review").json()["latest_review"]
        )
        assert released([latest]) == [[other.name]]


@pytest.mark.story("21.3", ac=9)
def test_a_booking_named_in_two_findings_is_released_once(
    login_as, db: Session, three_booked: Scene
):
    scene = three_booked

    body = _decide(
        login_as(Users.SAFETY_OFFICER),
        scene.event.id,
        [_finding("A", scene.first), _finding("B", scene.first)],
    )

    assert body.status_code == 200, body.text
    assert len(_audit(db, "BOOKING_RELEASED", scene.first.id)) == 1
    [notice] = _notices(db, scene.event.id, "BOOKING_RELEASED")
    assert notice.message.endswith(f"Required change: A{REASON_SEPARATOR}B")
    [coordinator] = [
        n
        for n in _notices(db, scene.event.id, "SAFETY_CHANGES_REQUESTED")
        if n.recipient_id == Users.COORDINATOR.id
    ]
    assert coordinator.message.count("Grand Hall (Plenary)") == 1
    row = _outcomes(login_as, scene.event.id)[str(scene.first.id)]
    assert row.get("release_reason") == f"A{REASON_SEPARATOR}B"
    findings = body.json()["previous_reviews"][0]["findings"]
    assert [len(finding.get("released_bookings", [])) for finding in findings] == [1, 1]


# --- AC10: who may release, and nobody may undo it --------------------------------------------
@pytest.mark.story("21.3", ac=10)
@pytest.mark.parametrize(
    "user",
    [
        Users.COORDINATOR,
        Users.ORGANISER,
        Users.VENUE_STAFF,
        Users.TECH_SUPPORT,
        Users.LEAD,
        Users.ATTENDEE,
    ],
)
def test_only_the_safety_officer_can_release(login_as, db: Session, two_booked: Scene, user):
    scene = two_booked

    response = login_as(user).post(
        f"/safety-checks/{scene.event.id}/decision",
        json={
            "outcome": "CHANGES_REQUESTED",
            "findings": [_finding(CHANGE, scene.first)],
            "facts_fingerprint": "unread",
        },
    )

    assert response.status_code == 403
    _nothing_written(db, scene, scene.first, scene.extra)


@pytest.mark.story("21.3", ac=10)
def test_a_signed_out_visitor_cannot_release(client, db: Session, two_booked: Scene):
    scene = two_booked

    response = client.post(
        f"/safety-checks/{scene.event.id}/decision",
        json={
            "outcome": "CHANGES_REQUESTED",
            "findings": [_finding(CHANGE, scene.first)],
            "facts_fingerprint": "unread",
        },
    )

    assert response.status_code == 401
    _nothing_written(db, scene, scene.first, scene.extra)


@pytest.mark.story("21.3", ac=10)
@pytest.mark.parametrize(
    ("user", "method", "tail", "body"),
    [
        (Users.VENUE_STAFF, "post", "reject", {"decision_reason": "No."}),
        (Users.COORDINATOR, "post", "withdraw", None),
        (Users.COORDINATOR, "post", "replacements", {"venue_id": str(Venues.BOARDROOM)}),
        (Users.COORDINATOR, "post", "switch", {"venue_id": str(Venues.BOARDROOM)}),
        (
            Users.VENUE_STAFF,
            "patch",
            "",
            {"hold_expires_at": FAR_FUTURE.isoformat(), "hold_expiry_change_reason": "Later."},
        ),
    ],
    ids=["reject", "withdraw", "replacement", "switch", "hold-expiry"],
)
def test_nobody_can_reopen_a_released_booking(
    login_as, db: Session, two_booked: Scene, user, method, tail, body
):
    scene = two_booked
    _release(login_as, scene, scene.first)
    assert _fresh(db, scene.first).status == BookingStatus.CANCELLED
    path = f"/bookings/{scene.first.id}" + (f"/{tail}" if tail else "")

    refused = login_as(user).request(method, path, json=body)
    stranger = login_as(Users.ORGANISER).request(method, path, json=body)

    assert refused.status_code == 409, refused.text
    assert stranger.status_code == 403
    row = _fresh(db, scene.first)
    assert (row.status, row.release_cause) == (BookingStatus.CANCELLED, "SAFETY_REVIEW")


# --- AC11: conflicts ---------------------------------------------------------------------------
@pytest.mark.story("21.3", ac=11)
def test_a_hold_that_expired_first_refuses_the_decision(login_as, db: Session, two_booked: Scene):
    scene = two_booked
    db.execute(
        update(VenueBooking)
        .where(VenueBooking.id == scene.first.id)
        .values(hold_expires_at=datetime.now(UTC) - timedelta(hours=1))
    )
    db.flush()
    bookings_service.expire_lapsed_holds(db, now=datetime.now(UTC))
    assert _fresh(db, scene.first).status == BookingStatus.EXPIRED

    response = _decide(
        login_as(Users.SAFETY_OFFICER), scene.event.id, [_finding(CHANGE, scene.first, scene.extra)]
    )

    assert response.status_code == 409
    assert response.json()["detail"] == NOT_APPROVED_NOW.format(bookings="Grand Hall (Main venue)")
    db.expire_all()
    assert db.get(Event, scene.event.id).status == EventStatus.AWAITING_SAFETY_CHECK
    assert _reviews(db, scene.event.id) == 0
    assert _fresh(db, scene.extra).status == BookingStatus.APPROVED
    assert _notices(db, scene.event.id, "BOOKING_RELEASED") == []
    expired = _notices(db, scene.event.id, "BOOKING_HOLD_EXPIRED")
    assert [n.recipient_id for n in expired] == [Users.COORDINATOR.id]


@pytest.mark.story("21.3", ac=11)
def test_a_cancellation_that_came_first_refuses_the_decision(
    login_as, db: Session, two_booked: Scene
):
    scene = two_booked
    cancelled = login_as(Users.ORGANISER).post(
        f"/events/{scene.event.id}/cancel", json={"reason": "Our sponsor withdrew."}
    )
    assert cancelled.status_code == 200, cancelled.text

    response = _decide(
        login_as(Users.SAFETY_OFFICER), scene.event.id, [_finding(CHANGE, scene.first, scene.extra)]
    )

    assert response.status_code == 409
    assert response.json()["detail"] == NOT_AWAITING
    assert _reviews(db, scene.event.id) == 0
    outcomes = _outcomes(login_as, scene.event.id)
    for booking in (scene.first, scene.extra):
        assert outcomes[str(booking.id)].get("release_cause") == "EVENT_CANCELLED"
    released = _notices(db, scene.event.id, "BOOKING_RELEASED")
    assert sorted(n.related_entity_id for n in released) == sorted([scene.first.id, scene.extra.id])
    assert _notices(db, scene.event.id, "SAFETY_CHANGES_REQUESTED") == []


def _committed_scene(engine: Engine, *, three: bool = False) -> tuple[uuid.UUID, ...]:
    """A scene on a venue of its own, committed so two sessions can meet on its rows. Returns the
    event, its first booking, the second (when ``three``), the venue and the equipment type."""
    with Session(engine) as session:
        venue = make_venue(session)
        scene = _scene(session, three=three, with_extra=False, venue_id=venue.id)
        session.commit()
        return (
            scene.event.id,
            scene.first.id,
            scene.later.id if scene.later is not None else scene.first.id,
            venue.id,
            scene.equipment.equipment_type_id,
        )


def _delete_committed(
    engine: Engine, event_id: uuid.UUID, *entity_ids: uuid.UUID, venue_id, type_id
):
    """Remove what a race committed: the event, whose bookings, equipment, reviews and
    notifications go with it, the audit entries, and the venue and equipment type made for it."""
    with Session(engine) as session:
        session.execute(
            text("DELETE FROM audit_log WHERE entity_id = ANY(:ids)"),
            {"ids": [event_id, *entity_ids]},
        )
        session.execute(text("DELETE FROM events WHERE id = :id"), {"id": event_id})
        session.execute(text("DELETE FROM venues WHERE id = :id"), {"id": venue_id})
        session.execute(text("DELETE FROM equipment_types WHERE id = :id"), {"id": type_id})
        session.commit()


def _payload(engine: Engine, event_id: uuid.UUID, *booking_ids: uuid.UUID) -> SafetyDecisionIn:
    """The officer's decision as the page read now would send it."""
    with Session(engine) as session:
        facts = safety_service.current_facts(session, session.get(Event, event_id))
        return SafetyDecisionIn.model_validate(
            {
                "outcome": "CHANGES_REQUESTED",
                "findings": [_finding(CHANGE, *booking_ids)],
                "facts_fingerprint": safety_service.facts_fingerprint(facts),
            }
        )


def _decide_in(engine: Engine, event_id: uuid.UUID, payload: SafetyDecisionIn, pids, name) -> str:
    with Session(engine) as session:
        pids[name] = backend_pid(session)
        try:
            safety_service.decide_safety_check(
                session, event_id, payload, actor=session.get(User, Users.SAFETY_OFFICER.id)
            )
        except safety_service.SafetyStateConflict as refused:
            return str(refused)
        return "recorded"


@pytest.mark.story("21.3", ac=11)
def test_an_expiry_racing_the_decision_loses_cleanly(engine):
    """One session holds the booking and expires it; the decision waits on that row, then finds it
    expired and is refused. Follows tests/cancellations/test_cancel_event.py's races."""
    event_id, booking_id, _, venue_id, type_id = _committed_scene(engine)
    payload = _payload(engine, event_id, booking_id)
    with Session(engine) as session:
        venue_name = session.get(Venue, venue_id).name
    pids: dict[str, int] = {}
    holding, go = threading.Event(), threading.Event()

    def expire() -> None:
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

    def decide() -> str:
        holding.wait(LOCK_WAIT_SECONDS)
        return _decide_in(engine, event_id, payload, pids, "decide")

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            expiring = pool.submit(expire)
            deciding = pool.submit(decide)
            try:
                wait_until_waiting(engine, pids, "decide")
            finally:
                go.set()
            expiring.result(timeout=LOCK_WAIT_SECONDS)
            outcome = deciding.result(timeout=LOCK_WAIT_SECONDS)

        assert outcome == NOT_APPROVED_NOW.format(bookings=f"{venue_name} (Main venue)")
        with Session(engine) as session:
            assert session.get(Event, event_id).status == EventStatus.AWAITING_SAFETY_CHECK
            assert _reviews(session, event_id) == 0
            assert session.get(VenueBooking, booking_id).status == BookingStatus.EXPIRED
    finally:
        go.set()
        _delete_committed(engine, event_id, booking_id, venue_id=venue_id, type_id=type_id)


@pytest.mark.story("21.3", ac=11)
def test_a_cancellation_racing_the_decision_wins_cleanly(engine):
    """The cancellation holds the event; the decision waits on it, then finds the event cancelled
    and is refused with the sentence story 21.2 gives for an event not awaiting the check."""
    event_id, booking_id, _, venue_id, type_id = _committed_scene(engine)
    payload = _payload(engine, event_id, booking_id)
    pids: dict[str, int] = {}
    holding, go = threading.Event(), threading.Event()

    def cancel() -> None:
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

    def decide() -> str:
        holding.wait(LOCK_WAIT_SECONDS)
        return _decide_in(engine, event_id, payload, pids, "decide")

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            cancelling = pool.submit(cancel)
            deciding = pool.submit(decide)
            try:
                wait_until_waiting(engine, pids, "decide")
            finally:
                go.set()
            cancelling.result(timeout=LOCK_WAIT_SECONDS)
            outcome = deciding.result(timeout=LOCK_WAIT_SECONDS)

        assert outcome == NOT_AWAITING
        with Session(engine) as session:
            released = session.get(VenueBooking, booking_id)
            assert released.status == BookingStatus.CANCELLED
            assert getattr(released, "release_cause", None) == "EVENT_CANCELLED"
            assert _reviews(session, event_id) == 0
            assert _notices(session, event_id, "SAFETY_CHANGES_REQUESTED") == []
            assert len(_notices(session, event_id, "BOOKING_RELEASED")) == 1
    finally:
        go.set()
        _delete_committed(engine, event_id, booking_id, venue_id=venue_id, type_id=type_id)


@pytest.mark.story("21.3", ac=11)
def test_the_decision_wins_then_expiry_and_cancellation_find_nothing_to_do(
    login_as, db: Session, two_booked: Scene
):
    scene = two_booked
    _release(login_as, scene, scene.first, scene.extra)
    released = len(_notices(db, scene.event.id, "BOOKING_RELEASED"))
    assert released == 2

    bookings_service.sweep_holds(db, now=datetime.now(UTC) + timedelta(days=60))
    cancelled = login_as(Users.ORGANISER).post(
        f"/events/{scene.event.id}/cancel", json={"reason": "Our sponsor withdrew."}
    )

    assert cancelled.status_code == 200, cancelled.text
    assert _notices(db, scene.event.id, "BOOKING_HOLD_EXPIRED") == []
    assert len(_notices(db, scene.event.id, "BOOKING_RELEASED")) == released
    assert len(_audit(db, "BOOKING_RELEASED", scene.first.id, scene.extra.id)) == 2
    row = _fresh(db, scene.first)
    assert getattr(row, "release_cause", None) == "SAFETY_REVIEW"


@pytest.mark.story("21.3", ac=11)
def test_the_decision_locks_the_event_then_the_bookings_in_id_order(engine):
    """A session holds the higher-id booking; the decision takes the event and the lower-id
    booking and then waits on that one. A probe session cannot take either at once."""
    event_id, first_id, later_id, venue_id, type_id = _committed_scene(engine, three=True)
    low, high = sorted([first_id, later_id])
    payload = _payload(engine, event_id, first_id, later_id)
    pids: dict[str, int] = {}
    holding, go = threading.Event(), threading.Event()

    def hold() -> None:
        with Session(engine) as session:
            session.execute(
                select(VenueBooking.id).where(VenueBooking.id == high).with_for_update()
            )
            holding.set()
            go.wait(LOCK_WAIT_SECONDS)
            session.rollback()

    def decide() -> str:
        holding.wait(LOCK_WAIT_SECONDS)
        return _decide_in(engine, event_id, payload, pids, "decide")

    def is_taken(statement) -> bool:
        with Session(engine) as probe:
            try:
                probe.execute(statement)
            except OperationalError:
                return True
            return False

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            holder = pool.submit(hold)
            deciding = pool.submit(decide)
            try:
                wait_until_waiting(engine, pids, "decide")
                event_taken = is_taken(
                    select(Event.id)
                    .where(Event.id == event_id)
                    .with_for_update(key_share=True, nowait=True)
                )
                low_taken = is_taken(
                    select(VenueBooking.id)
                    .where(VenueBooking.id == low)
                    .with_for_update(nowait=True)
                )
            finally:
                go.set()
            holder.result(timeout=LOCK_WAIT_SECONDS)
            deciding.result(timeout=LOCK_WAIT_SECONDS)

        assert (event_taken, low_taken) == (True, True)
    finally:
        go.set()
        _delete_committed(engine, event_id, first_id, later_id, venue_id=venue_id, type_id=type_id)


@pytest.mark.story("21.3", ac=11)
def test_a_second_decision_releases_nothing_twice(login_as, db: Session, two_booked: Scene):
    scene = two_booked
    _release(login_as, scene, scene.first, scene.extra)
    assert _fresh(db, scene.first).status == BookingStatus.CANCELLED

    again = _decide(
        login_as(Users.SAFETY_OFFICER), scene.event.id, [_finding(CHANGE, scene.first, scene.extra)]
    )

    assert again.status_code == 409
    assert again.json()["detail"] == NOT_AWAITING
    assert _reviews(db, scene.event.id) == 1
    assert len(_audit(db, "BOOKING_RELEASED", scene.first.id, scene.extra.id)) == 2
    assert len(_notices(db, scene.event.id, "BOOKING_RELEASED")) == 2
