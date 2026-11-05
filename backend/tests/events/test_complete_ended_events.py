"""Fix f21.2.2 - a Confirmed event becomes Completed once it has ended (story 21.2, Q57, CL-232).

AC28 A Confirmed event whose end time has passed becomes Completed with no one acting. The move
     records when, is in the event's status history as the system's, and is audited.
AC29 Its organiser and its assigned coordinator are each told, once; with no coordinator, only
     the organiser.
AC30 Only Confirmed events move: one that ended while in Planning or awaiting its safety check
     stays as it is, and so does a closed one. One whose end is still ahead stays Confirmed.
AC31 The API makes the move on a timer while it runs. An event another action holds at that
     moment is left to that action and looked at again on the next pass; a pass that fails is
     logged, and the next one still runs.

Every case makes its own events; the pass also completes any seeded Confirmed event that has
ended, which the test's rollback undoes. The page flow is tests/e2e/event-completion.spec.ts.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import main
from app.common.audit import AuditLog
from app.config import settings
from app.events import service
from app.events.models import Event, EventStatus, EventStatusHistory
from app.notifications.models import Notification
from tests.support.factories import make_event
from tests.support.seed import Users

COMPLETED_TITLE = '"{name}" is completed'
COMPLETED_MESSAGE = "The event has ended, so it is now marked Completed."
COMPLETION_FAILED = "Completing ended events failed"
# A moment long before any seeded event, for the one case that commits: its pass then completes
# its own event and no seeded one, so the shared test database is left as it was.
LONG_AGO = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)


def _ended_event(
    db: Session,
    *,
    ends_at: datetime,
    status: str = EventStatus.CONFIRMED,
    coordinator_id=Users.COORDINATOR.id,
) -> Event:
    return make_event(
        db,
        status=status,
        starts_at=ends_at - timedelta(hours=3),
        ends_at=ends_at,
        assigned_coordinator_id=coordinator_id,
    )


def _history(db: Session, event_id) -> list[EventStatusHistory]:
    return list(
        db.scalars(select(EventStatusHistory).where(EventStatusHistory.event_id == event_id)).all()
    )


def _notices(db: Session, event_id) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.event_id == event_id)
            .order_by(Notification.recipient_id)
        ).all()
    )


def _status(db: Session, event: Event) -> str:
    db.refresh(event)
    return event.status


# --- AC28: an ended Confirmed event becomes Completed ---------------------------------------------
@pytest.mark.story("21.2", ac=28)
def test_a_confirmed_event_that_has_ended_becomes_completed(db):
    now = datetime.now(UTC)
    event = _ended_event(db, ends_at=now - timedelta(hours=1))

    completed = service.complete_ended_events(db, now=now)

    assert event.id in {each.id for each in completed}
    db.refresh(event)
    assert (event.status, event.completed_at) == (EventStatus.COMPLETED, now)


@pytest.mark.story("21.2", ac=28)
def test_the_move_is_in_the_status_history_as_the_systems_and_is_audited(db):
    now = datetime.now(UTC)
    event = _ended_event(db, ends_at=now - timedelta(hours=1))

    service.complete_ended_events(db, now=now)

    (move,) = _history(db, event.id)
    assert (move.from_status, move.to_status, move.changed_by_id, move.changed_at) == (
        EventStatus.CONFIRMED,
        EventStatus.COMPLETED,
        None,
        now,
    )
    (entry,) = db.scalars(
        select(AuditLog).where(AuditLog.entity_id == event.id, AuditLog.action == "EVENT_COMPLETED")
    ).all()
    assert (entry.actor_id, entry.entity_type) == (None, "event")


@pytest.mark.story("21.2", ac=28)
@pytest.mark.parametrize(
    ("ends_after_now", "expected"),
    [
        pytest.param(timedelta(0), EventStatus.COMPLETED, id="ends-exactly-now"),
        pytest.param(timedelta(seconds=1), EventStatus.CONFIRMED, id="ends-a-second-later"),
    ],
)
def test_an_event_is_completed_from_the_moment_it_ends(db, ends_after_now, expected):
    now = datetime.now(UTC)
    event = _ended_event(db, ends_at=now + ends_after_now)

    service.complete_ended_events(db, now=now)

    assert _status(db, event) == expected


# --- AC29: who is told ---------------------------------------------------------------------------
@pytest.mark.story("21.2", ac=29)
def test_its_organiser_and_coordinator_are_each_told_once(db):
    now = datetime.now(UTC)
    event = _ended_event(db, ends_at=now - timedelta(hours=1))

    service.complete_ended_events(db, now=now)
    service.complete_ended_events(db, now=now + timedelta(minutes=1))

    notices = _notices(db, event.id)
    assert sorted(notice.recipient_id for notice in notices) == sorted(
        [Users.ORGANISER.id, Users.COORDINATOR.id]
    )
    for notice in notices:
        assert notice.notification_type == "EVENT_COMPLETED"
        assert notice.title == COMPLETED_TITLE.format(name=event.name)
        assert notice.message == COMPLETED_MESSAGE
        assert (notice.related_entity_type, notice.related_entity_id) == ("event", event.id)


@pytest.mark.story("21.2", ac=29)
def test_with_no_coordinator_only_the_organiser_is_told(db):
    now = datetime.now(UTC)
    event = _ended_event(db, ends_at=now - timedelta(hours=1), coordinator_id=None)

    service.complete_ended_events(db, now=now)

    assert [notice.recipient_id for notice in _notices(db, event.id)] == [Users.ORGANISER.id]


# --- AC30: only Confirmed events move ------------------------------------------------------------
@pytest.mark.story("21.2", ac=30)
@pytest.mark.parametrize(
    "status",
    [
        EventStatus.UNDER_REVIEW,
        EventStatus.CLARIFICATION_REQUESTED,
        EventStatus.PLANNING,
        EventStatus.AWAITING_SAFETY_CHECK,
        EventStatus.COMPLETED,
        EventStatus.CANCELLED,
        EventStatus.REJECTED,
    ],
)
def test_an_ended_event_that_is_not_confirmed_is_left_as_it_is(db, status):
    now = datetime.now(UTC)
    event = _ended_event(db, ends_at=now - timedelta(days=2), status=status)

    completed = service.complete_ended_events(db, now=now)

    assert event.id not in {each.id for each in completed}
    db.refresh(event)
    assert (event.status, event.completed_at) == (status, None)
    assert _history(db, event.id) == []
    assert _notices(db, event.id) == []


# --- AC31: an event another action holds ---------------------------------------------------------
@contextmanager
def _committed_ended_event(engine) -> Iterator[uuid.UUID]:
    """The id of a Confirmed event that ended just before ``LONG_AGO``, committed so that two
    sessions can meet on its row, and removed afterwards with what its completion wrote."""
    with Session(engine) as session:
        event = _ended_event(session, ends_at=LONG_AGO - timedelta(minutes=1))
        session.commit()
        event_id = event.id
    try:
        yield event_id
    finally:
        with Session(engine) as session:
            session.execute(delete(AuditLog).where(AuditLog.entity_id == event_id))
            session.execute(delete(Notification).where(Notification.event_id == event_id))
            session.execute(delete(Event).where(Event.id == event_id))
            session.commit()


@pytest.mark.story("21.2", ac=31)
def test_an_event_another_action_holds_is_left_to_it_and_completed_on_the_next_pass(engine):
    """A cancellation or a return to Planning holds the event's row while it decides; the pass
    neither waits for it nor overrules it. Skipped this time, the event is completed by the next
    pass once nothing holds it."""
    with _committed_ended_event(engine) as event_id, Session(engine) as holder:
        holder.execute(select(Event.id).where(Event.id == event_id).with_for_update())
        try:
            with Session(engine) as session:
                skipped = [each.id for each in service.complete_ended_events(session, now=LONG_AGO)]
                status_while_held = session.get(Event, event_id).status
        finally:
            holder.rollback()

        with Session(engine) as session:
            completed = [each.id for each in service.complete_ended_events(session, now=LONG_AGO)]
            status = session.get(Event, event_id).status

        assert (skipped, status_while_held) == ([], EventStatus.CONFIRMED)
        assert (completed, status) == ([event_id], EventStatus.COMPLETED)


# --- AC31: the timer -----------------------------------------------------------------------------
@pytest.mark.story("21.2", ac=31)
def test_the_api_completes_ended_events_on_a_timer_while_it_runs(monkeypatch):
    """The timer starts with the API and stops with it; each pass is counted here instead of
    touching a database."""
    passes: list[float] = []
    monkeypatch.setattr(
        main, "_complete_ended_events_once", lambda: passes.append(time.monotonic())
    )
    monkeypatch.setattr(settings, "event_completion_interval_seconds", 0.01)

    with TestClient(main.app):
        deadline = time.monotonic() + 5
        while len(passes) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
    stopped_at = len(passes)
    time.sleep(0.1)

    assert stopped_at >= 3
    assert len(passes) == stopped_at


@pytest.mark.story("21.2", ac=31)
def test_an_unexpected_error_in_a_completion_pass_is_logged_and_the_timer_carries_on(
    monkeypatch, caplog
):
    passes: list[float] = []

    def fails_once() -> None:
        passes.append(time.monotonic())
        if len(passes) == 1:
            raise RuntimeError("a notice could not be written")

    monkeypatch.setattr(main, "_complete_ended_events_once", fails_once)
    monkeypatch.setattr(settings, "event_completion_interval_seconds", 0.01)

    with TestClient(main.app):
        deadline = time.monotonic() + 5
        while len(passes) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)

    assert len(passes) >= 3
    assert COMPLETION_FAILED in caplog.text


@pytest.mark.story("21.2", ac=31)
def test_a_failed_completion_pass_is_logged_and_the_next_one_still_runs(
    engine, monkeypatch, caplog
):
    """A database that is briefly unreachable must not stop the timer: the pass is logged and
    left for the next one. Pointed at the test database, though it never reaches it."""

    def unreachable(db: Session, *, now: datetime) -> list[Event]:
        raise OperationalError("SELECT 1", {}, Exception("the database is restarting"))

    monkeypatch.setattr(main, "SessionLocal", lambda: Session(bind=engine))
    monkeypatch.setattr(service, "complete_ended_events", unreachable)

    main._complete_ended_events_once()

    assert COMPLETION_FAILED in caplog.text
