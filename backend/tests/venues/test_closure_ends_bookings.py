"""Story 9.5 - end the bookings a venue closure covers. The backlog's ACs, as written:

Happy path
1. Before saving a closure (9.4 AC1), Venue Staff see every pending request and approved booking
    whose occupied period (setup and turnaround included) overlaps the part of the closure still
    to come, a booking already under way included, and are told that saving rejects each pending
    request and cancels each approved booking. Saving needs their confirmation; closing the
    confirmation saves nothing. Extending a closure, or moving its end later, shows the same
    preview and confirmation for each booking it newly covers (extends 9.4 AC2).
2. Saving rejects each affected pending request and cancels each affected approved booking in the
    same step, with the closure's reason and description, who saved it and when. A cancelled
    booking is released through the shared release path with the cause VENUE_UNAVAILABLE (21.3),
    and shows on the event's booking list and in the Venue Staff queue's Cancelled tab as
    cancelled because the venue closed, with the reason; a rejected request shows in the Rejected
    tab with the same reason. The venue's other bookings, and the event's other venue bookings and
    equipment, do not change (replaces 9.4 AC3's mark).
3. Each venue requirement that lost its booking shows "Needs a venue" again (12.5). Only a
    cancelled approved booking sends an event that is Awaiting Safety Check or Confirmed back to
    Planning, so its safety check (21.2) is done again before it is confirmed again, as 12.8 AC5;
    a rejected pending request does not, since the event never relied on it. An event in Planning
    stays in Planning, and the event itself is never cancelled (replaces 9.4 AC3's status rule).
4. The assigned coordinator and the organiser of each affected event are notified (20.1) with the
    venue, the period, the reason, and which bookings were cancelled or requests rejected; the
    coordinator's notice also carries the description. The other Venue Staff are notified of each
    booking ended, but not the member who saved the closure (20.1 AC3, as 21.3 AC4). The Safety
    Officers are notified when an event goes back to Planning (as 12.8 AC5). Technical Support
    and registered attendees are not notified (Q61) (replaces 9.4 AC4).

Boundary
5. Only the part of a closure still to come counts: a booking that ends before it, or one whose
    period only touches it, is not affected (as 9.4 AC5, AC8), and bookings of events already
    completed or cancelled are not touched.

Edge
6. Shortening, ending early or removing a closure restores nothing: a rejected request or
    cancelled booking stays as it is, and the coordinator raises a new request. A rejected
    request or cancelled booking cannot be approved again, and a new request that overlaps a
    closure is refused (12.1 AC14) (replaces 9.4 AC6's clearing of marks).
7. Nothing is marked "Venue unavailable – alternative needed" any more. The mark, "Find a
    replacement venue" and "Find another venue" (12.6), the coordinator's "Venue unavailable" tab
    (12.6 AC11), the checks for a marked booking or a pending replacement on the safety review
    and Confirm (21.2 AC22, 12.6 AC12), and 12.8's marked and pending-replacement checks are
    removed. A booking already replaced keeps showing "Replaced by <venue>".
8. Bookings still marked when this ships are closed in one migration, with no notices: pending
    ones are rejected and approved ones cancelled with the cause VENUE_UNAVAILABLE. Their events
    are already in Planning (9.4 AC3, 21.2 AC22). A pending replacement of such a booking stays
    as a normal pending request for its requirement, and approving it later leaves the cancelled
    original as it is. The seed matches.

Permission
9. Only Venue Staff save closures (9.4 AC9). Nobody can undo a rejection or cancellation a
    closure made, and the API refuses anyone else.

Conflict
10. If a booking is approved, withdrawn, or its hold expires at the moment a closure is saved,
    whichever is saved first wins: a booking approved first is still cancelled, one withdrawn or
    expired first is left as it is, and nothing is rejected, cancelled or notified twice. A
    request raised at that same instant that is missed still cannot be approved while the
    closure stands (9.4 AC7) (replaces 9.4 AC10).

Every case here is one layer, the backend: what a user clicks through is
tests/e2e/venue-closure-ends-bookings.spec.ts. A save ends bookings only for the ids the caller
confirmed (``confirmed_booking_ids``, D21), so ``_add`` and ``_edit`` send the ids of every
booking they expect to end. A refusal for a missing confirmation is a 409 whose ``detail`` is
``{"message": <a sentence>, "bookings": [<the fresh list, as the preview returns it>]}``.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings import service as booking_service
from app.bookings.models import VenueBooking
from app.common.audit import AuditLog
from app.events import service as events_service
from app.events.models import Event, EventStatus, EventStatusHistory
from app.notifications.models import Notification
from app.safety.models import EventSafetyReview, SafetyReviewOutcome
from app.safety.service import current_facts
from app.venues import service as venue_service
from app.venues.models import Venue, VenueUnavailabilityPeriod
from app.venues.schemas import VenueUnavailabilityCreate
from tests.support.factories import (
    approval_payload,
    make_booking,
    make_equipment_item,
    make_equipment_type,
    make_event,
    make_secured_event,
    make_unavailability,
    make_user,
    make_venue,
)
from tests.support.locks import LOCK_WAIT_SECONDS, backend_pid, wait_until_waiting
from tests.support.seed import Users

SGT = timezone(timedelta(hours=8))
STAFF_ID = Users.VENUE_STAFF.id

VENUE_UNAVAILABLE = "BOOKING_VENUE_UNAVAILABLE"
RELEASED = "BOOKING_RELEASED"
REJECTED = "BOOKING_REJECTED"
RETURNED_TO_PLANNING = "EVENT_RETURNED_TO_PLANNING"
RELEASED_TITLE = "A venue booking was released"
APPROVAL_OUT_OF_DATE = (
    "The event's venue bookings changed after the safety approval; request a safety review again."
)
# The names the page gives each reason (the closure's ``reason`` is the code).
REASON_NAMES = {
    "MAINTENANCE": "Maintenance",
    "EQUIPMENT_FAILURE": "Equipment failure",
    "RENOVATION": "Renovation",
    "SAFETY": "Safety concern",
    "OTHER": "Other",
}
CLOSURE_COLUMNS = (
    "status, release_cause, release_reason, released_by_id, cancelled_at, decided_by_id, "
    "decided_at, decision_reason, closure_reason, closure_description"
)


def _days_from_now(days: float) -> datetime:
    """A moment that far from now, to the second - used only where the case is days away from
    any boundary, so the clock cannot change its answer."""
    return datetime.now(UTC).replace(microsecond=0) + timedelta(days=days)


def _day(days: float, hour: int = 10) -> datetime:
    """``hour`` o'clock UTC, that many days from now: a start well clear of the clock."""
    return (datetime.now(UTC) + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )


def _url(venue_id: uuid.UUID, period_id: uuid.UUID | None = None) -> str:
    base = f"/venues/{venue_id}/unavailability"
    return base if period_id is None else f"{base}/{period_id}"


def _body(starts_at: datetime, ends_at: datetime, *covered, **overrides) -> dict:
    """A closure's body, confirming ``covered`` (bookings or ids) as the ones it may end."""
    body = {
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "reason": "MAINTENANCE",
        "description": "Scheduled servicing",
        "confirmed_booking_ids": [str(getattr(b, "id", b)) for b in covered],
    }
    body.update(overrides)
    return body


def _add(client, venue_id: uuid.UUID, starts_at, ends_at, *covered, **overrides) -> dict:
    response = client.post(_url(venue_id), json=_body(starts_at, ends_at, *covered, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _edit(client, venue_id: uuid.UUID, period_id, *covered, **fields):
    body = {**fields, "confirmed_booking_ids": [str(getattr(b, "id", b)) for b in covered]}
    return client.patch(_url(venue_id, uuid.UUID(str(period_id))), json=body)


def _preview(client, venue_id: uuid.UUID, starts_at, ends_at, **extra):
    return client.get(
        f"/venues/{venue_id}/unavailability/affected-bookings",
        params={"starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat(), **extra},
    )


def _ids(response) -> set[str]:
    assert response.status_code == 200, response.text
    return {entry["booking_id"] for entry in response.json()}


def _staff(db: Session) -> User:
    return db.get(User, STAFF_ID)


def _period(db: Session, venue_id, starts_at, ends_at, **overrides) -> VenueUnavailabilityPeriod:
    return make_unavailability(
        db, venue_id=venue_id, starts_at=starts_at, ends_at=ends_at, **overrides
    )


def _periods(db: Session, venue_id: uuid.UUID) -> list[VenueUnavailabilityPeriod]:
    db.expire_all()
    return list(
        db.scalars(
            select(VenueUnavailabilityPeriod).where(VenueUnavailabilityPeriod.venue_id == venue_id)
        )
    )


def _event_for(db: Session, status: str = EventStatus.PLANNING, **overrides) -> Event:
    """An event with the seed coordinator and organiser, unless overridden."""
    overrides.setdefault("assigned_coordinator_id", Users.COORDINATOR.id)
    return make_event(db, status=status, **overrides)


def _booking(db: Session, venue_id, starts_at, ends_at, **kwargs) -> VenueBooking:
    """A booking of an event of its own (Planning unless ``event_status`` says), so two never
    share an event."""
    event_status = kwargs.pop("event_status", EventStatus.PLANNING)
    event = _event_for(db, event_status, starts_at=starts_at, ends_at=ends_at)
    return make_booking(
        db, venue_id=venue_id, starts_at=starts_at, ends_at=ends_at, event_id=event.id, **kwargs
    )


def _live(db: Session, venue_id, starts_at, hours: float = 2, **kwargs) -> VenueBooking:
    """A pending request of a Planning event of its own, ``hours`` long."""
    return _booking(
        db, venue_id, starts_at, starts_at + timedelta(hours=hours), status="PENDING", **kwargs
    )


def _held(db: Session, venue_id, starts_at, hours: float = 2, **kwargs) -> VenueBooking:
    """An approved booking of a Planning event of its own, ``hours`` long."""
    return _booking(
        db, venue_id, starts_at, starts_at + timedelta(hours=hours), status="APPROVED", **kwargs
    )


def _pending_of(db: Session, event: Event, venue_id, starts_at, **kwargs) -> VenueBooking:
    """A booking of ``event`` (pending unless ``status`` says), two hours from ``starts_at``."""
    return make_booking(
        db,
        venue_id=venue_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        event_id=event.id,
        **kwargs,
    )


def _stored(db: Session, booking_id: uuid.UUID) -> VenueBooking:
    db.expire_all()
    return db.get(VenueBooking, booking_id)


def _closure(db: Session, booking_id: uuid.UUID) -> dict:
    """The booking's row as 9.5 records an ending, read in SQL so the columns are checked, not
    the model."""
    db.expire_all()
    return dict(
        db.execute(
            text(f"SELECT {CLOSURE_COLUMNS} FROM venue_bookings WHERE id = :id"), {"id": booking_id}
        )
        .mappings()
        .one()
    )


def _status_of(db: Session, event_id: uuid.UUID) -> str:
    db.expire_all()
    return db.get(Event, event_id).status


def _history(db: Session, event_id: uuid.UUID) -> list[EventStatusHistory]:
    db.expire_all()
    return list(
        db.scalars(
            select(EventStatusHistory)
            .where(EventStatusHistory.event_id == event_id)
            .order_by(EventStatusHistory.changed_at, EventStatusHistory.id)
        )
    )


def _returned(db: Session, event_id: uuid.UUID) -> list[EventStatusHistory]:
    return [
        row
        for row in _history(db, event_id)
        if row.to_status == EventStatus.PLANNING
        and row.from_status in (EventStatus.CONFIRMED, EventStatus.AWAITING_SAFETY_CHECK)
    ]


def _audit(db: Session, action: str, entity_id: uuid.UUID) -> list[AuditLog]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditLog).where(AuditLog.action == action, AuditLog.entity_id == entity_id)
        )
    )


def _notices(
    db: Session, kind: str, *, event_id: uuid.UUID | None = None, entity_id=None
) -> list[Notification]:
    db.expire_all()
    query = select(Notification).where(Notification.notification_type == kind)
    if event_id is not None:
        query = query.where(Notification.event_id == event_id)
    if entity_id is not None:
        query = query.where(Notification.related_entity_id == entity_id)
    return list(db.scalars(query.order_by(Notification.created_at, Notification.id)))


def _told(db: Session, event_id: uuid.UUID) -> list[Notification]:
    """The closure notices an event's coordinator and organiser got."""
    return _notices(db, VENUE_UNAVAILABLE, event_id=event_id)


def _recipients(notices: list[Notification]) -> list[uuid.UUID]:
    return sorted(notice.recipient_id for notice in notices)


def _on_singapore_date(moment: datetime) -> str:
    """The date as a notice words it: ``4 Mar 2027``, in Singapore time."""
    local = moment.astimezone(SGT)
    return f"{local.day} {local:%b %Y}"


def _approve(client, booking_id: uuid.UUID, **overrides):
    return client.post(f"/bookings/{booking_id}/approve", json=approval_payload(**overrides))


def _nothing_written(db: Session, venue_id, booking: VenueBooking, event: Event) -> None:
    """A refused save left no period, the booking as it was, the event where it was, and no
    audit entry or notice about it."""
    db.expire_all()
    assert _periods(db, venue_id) == []
    row = _closure(db, booking.id)
    assert (row["status"], row["release_cause"], row["closure_reason"]) == (
        booking.status,
        None,
        None,
    )
    assert _status_of(db, event.id) == event.status
    assert _audit(db, "BOOKING_RELEASED", booking.id) == []
    assert _audit(db, "BOOKING_REJECTED", booking.id) == []
    assert _told(db, event.id) == []


def _pause_before_commit(session: Session, engine, pids: dict, holding, waiter: str) -> None:
    """The first commit of ``session`` waits until ``waiter`` stands on a lock this transaction
    holds, so which of two saves is first is the test's choice, never a sleep."""
    real = session.commit

    def paused() -> None:
        session.commit = real
        holding.set()
        wait_until_waiting(engine, pids, waiter)
        real()

    session.commit = paused


def _committed_pending_request(engine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A venue, and a pending request of a Planning event for it three days away, committed."""
    with Session(engine) as session:
        venue = make_venue(session)
        event = _event_for(session)
        booking = _pending_of(session, event, venue.id, _day(3))
        session.commit()
        return venue.id, event.id, booking.id


def _remove_race_rows(engine, venue_id, event_id, *booking_ids) -> None:
    with Session(engine) as session:
        session.execute(
            delete(AuditLog).where(
                AuditLog.entity_id.in_([*booking_ids, event_id])
                | (AuditLog.details["venue_id"].astext == str(venue_id))
            )
        )
        session.execute(delete(Notification).where(Notification.event_id == event_id))
        session.execute(delete(EventStatusHistory).where(EventStatusHistory.event_id == event_id))
        session.execute(delete(VenueBooking).where(VenueBooking.id.in_(booking_ids)))
        session.execute(delete(Event).where(Event.id == event_id))
        session.execute(
            delete(VenueUnavailabilityPeriod).where(VenueUnavailabilityPeriod.venue_id == venue_id)
        )
        session.execute(delete(Venue).where(Venue.id == venue_id))
        session.commit()


def _data(*covered, starts_at=None, ends_at=None) -> VenueUnavailabilityCreate:
    """What the save takes, for the tests that call the service on a session of their own."""
    return VenueUnavailabilityCreate(
        starts_at=starts_at or _day(2),
        ends_at=ends_at or _day(7),
        reason="MAINTENANCE",
        description="Servicing",
        confirmed_booking_ids=[getattr(b, "id", b) for b in covered],
    )


# --- AC1: the preview, and the confirmation a save needs ---------------------------------------
@pytest.mark.story("9.5", ac=1)
def test_a_save_with_the_confirmed_ids_ends_the_request_and_the_booking_it_covers(
    db, venue_staff_client
):
    """AC1 and AC2: the preview lists both, the save names them, and the pending request is
    rejected and the approved booking cancelled."""
    venue = make_venue(db)
    pending = _live(db, venue.id, _day(3))
    approved = _held(db, venue.id, _day(5))
    assert _ids(_preview(venue_staff_client, venue.id, _day(2), _day(7))) == {
        str(pending.id),
        str(approved.id),
    }

    _add(venue_staff_client, venue.id, _day(2), _day(7), pending, approved)

    assert _stored(db, pending.id).status == "REJECTED"
    assert _stored(db, approved.id).status == "CANCELLED"
    assert len(_periods(db, venue.id)) == 1


@pytest.mark.story("9.5", ac=1)
def test_a_save_without_the_confirmation_is_refused_and_nothing_is_written(db, venue_staff_client):
    """AC1: closing the confirmation saves nothing, and the API holds the same line - a save
    sent with no ids, or with one missing, while bookings are in the way is a 409 carrying the
    fresh list. No period, no booking change, no audit entry, no notice."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.CONFIRMED)
    first = _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    second = _live(db, venue.id, _day(4))
    db.commit()

    bare = venue_staff_client.post(_url(venue.id), json=_body(_day(2), _day(7)))
    partial = venue_staff_client.post(_url(venue.id), json=_body(_day(2), _day(7), second))

    for refused in (bare, partial):
        assert refused.status_code == 409, refused.text
        detail = refused.json()["detail"]
        assert detail["message"].endswith(".")
        assert {entry["booking_id"] for entry in detail["bookings"]} == {
            str(first.id),
            str(second.id),
        }
    _nothing_written(db, venue.id, first, event)
    assert _stored(db, second.id).status == "PENDING"


@pytest.mark.story("9.5", ac=1)
def test_a_request_raised_after_the_preview_stops_the_save(db, venue_staff_client):
    """AC1: Venue Staff confirmed the list they saw; a request raised since is not on it, so the
    save is refused with the fresh list and nothing is written (D21)."""
    venue = make_venue(db)
    seen = _held(db, venue.id, _day(3))
    listed = _ids(_preview(venue_staff_client, venue.id, _day(2), _day(7)))
    assert listed == {str(seen.id)}
    late = _live(db, venue.id, _day(4))
    db.commit()

    refused = venue_staff_client.post(_url(venue.id), json=_body(_day(2), _day(7), seen))

    assert refused.status_code == 409, refused.text
    assert {b["booking_id"] for b in refused.json()["detail"]["bookings"]} == {
        str(seen.id),
        str(late.id),
    }
    assert _periods(db, venue.id) == []
    assert _stored(db, seen.id).status == "APPROVED"
    assert _stored(db, late.id).status == "PENDING"


@pytest.mark.story("9.5", ac=1)
def test_a_booking_that_left_the_list_meanwhile_does_not_stop_the_save(db, venue_staff_client):
    """AC1: one the coordinator withdrew after the preview is no longer in the way; the save goes
    through, ends the other, and leaves the withdrawn one withdrawn."""
    venue = make_venue(db)
    kept = _held(db, venue.id, _day(3))
    gone = _live(db, venue.id, _day(4))
    gone.status = "WITHDRAWN"
    db.flush()

    _add(venue_staff_client, venue.id, _day(2), _day(7), kept, gone)

    assert _stored(db, kept.id).status == "CANCELLED"
    assert _stored(db, gone.id).status == "WITHDRAWN"


@pytest.mark.story("9.5", ac=1)
def test_extending_a_closure_ends_only_the_bookings_it_newly_covers(db, venue_staff_client):
    """AC1 (extends 9.4 AC2): the booking the first save ended is not ended or told again; the
    one the new end reaches is."""
    venue = make_venue(db)
    inside = _live(db, venue.id, _day(3))
    beyond = _live(db, venue.id, _day(8))
    period = _add(venue_staff_client, venue.id, _day(2), _day(5), inside)
    inside_row = _closure(db, inside.id)
    assert inside_row["status"] == "REJECTED" and _stored(db, beyond.id).status == "PENDING"

    extended = _edit(
        venue_staff_client, venue.id, period["id"], beyond, ends_at=_day(10).isoformat()
    )

    assert extended.status_code == 200, extended.text
    assert _stored(db, beyond.id).status == "REJECTED"
    assert _closure(db, inside.id) == inside_row


@pytest.mark.story("9.5", ac=1)
def test_moving_the_start_earlier_ends_the_booking_it_newly_covers(db, venue_staff_client):
    """AC1 (D22): a closure that has not started can begin sooner; the booking in the slice the
    new start adds is ended, and one inside the old range that was already there is left to
    the edit's preview, which lists the added slices only."""
    venue = make_venue(db)
    period = _add(venue_staff_client, venue.id, _day(5), _day(8))
    earlier = _live(db, venue.id, _day(3))

    moved = _edit(
        venue_staff_client, venue.id, period["id"], earlier, starts_at=_day(2).isoformat()
    )

    assert moved.status_code == 200, moved.text
    assert _stored(db, earlier.id).status == "REJECTED"


@pytest.mark.story("9.5", ac=1)
def test_the_preview_of_an_edit_lists_only_the_added_slices(db, venue_staff_client):
    """AC1 (D22): with ``period_id`` the preview lists the bookings in the slices an edit adds -
    [new start, old start) and (old end, new end] - and not one the closure already covered. An
    edit that changes only the text adds nothing."""
    venue = make_venue(db)
    period = _period(db, venue.id, _day(5), _day(8))
    before = _live(db, venue.id, _day(3))
    already = _live(db, venue.id, _day(6))
    after = _live(db, venue.id, _day(10))

    wider = _preview(venue_staff_client, venue.id, _day(2), _day(12), period_id=str(period.id))
    same = _preview(venue_staff_client, venue.id, _day(5), _day(8), period_id=str(period.id))

    assert _ids(wider) == {str(before.id), str(after.id)}
    assert str(already.id) not in _ids(wider)
    assert _ids(same) == set()


@pytest.mark.story("9.5", ac=1)
def test_a_booking_already_under_way_is_previewed_and_ended(db, venue_staff_client):
    """AC1: its held period began an hour ago and ends in two, and it is still to come."""
    venue = make_venue(db)
    now = datetime.now(UTC)
    booking = _booking(
        db,
        venue.id,
        now - timedelta(hours=1),
        now + timedelta(hours=2),
        status="APPROVED",
        event_status=EventStatus.CONFIRMED,
    )
    assert _ids(_preview(venue_staff_client, venue.id, _day(-1), _day(1))) == {str(booking.id)}

    _add(venue_staff_client, venue.id, _day(-1), _day(1), booking)

    assert _stored(db, booking.id).status == "CANCELLED"


# --- AC2: what saving does ---------------------------------------------------------------------
@pytest.mark.story("9.5", ac=2)
def test_a_pending_request_is_rejected_and_an_approved_booking_cancelled_with_the_closure(
    db, venue_staff_client
):
    """AC2: who saved it, when, and the closure's reason and description on each. A request is
    REJECTED with its reason worded for the queue; a booking is CANCELLED through the release
    path with the cause VENUE_UNAVAILABLE and no release reason (D18). Venue and period are
    unchanged."""
    venue = make_venue(db)
    pending = _live(db, venue.id, _day(3))
    approved = _held(db, venue.id, _day(5))
    kept = {b.id: (b.venue_id, b.starts_at, b.ends_at) for b in (pending, approved)}
    before = datetime.now(UTC)

    _add(
        venue_staff_client,
        venue.id,
        _day(2),
        _day(7),
        pending,
        approved,
        reason="RENOVATION",
        description="Floor relaid",
    )

    rejected = _closure(db, pending.id)
    assert rejected["status"] == "REJECTED"
    assert rejected["decided_by_id"] == STAFF_ID and rejected["decided_at"] >= before
    assert rejected["decision_reason"] == "Venue closed: Renovation"
    assert (rejected["closure_reason"], rejected["closure_description"]) == (
        "RENOVATION",
        "Floor relaid",
    )
    assert rejected["release_cause"] is None
    cancelled = _closure(db, approved.id)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["release_cause"] == "VENUE_UNAVAILABLE"
    assert cancelled["released_by_id"] == STAFF_ID and cancelled["cancelled_at"] >= before
    assert cancelled["release_reason"] is None
    assert (cancelled["closure_reason"], cancelled["closure_description"]) == (
        "RENOVATION",
        "Floor relaid",
    )
    for booking in (pending, approved):
        stored = _stored(db, booking.id)
        assert (stored.venue_id, stored.starts_at, stored.ends_at) == kept[booking.id]


@pytest.mark.story("9.5", ac=2)
def test_two_bookings_of_one_event_are_both_ended(db, venue_staff_client):
    """AC2: the event has two bookings on the venue; both are ended."""
    venue = make_venue(db)
    event = _event_for(db)
    first = _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    second = _pending_of(db, event, venue.id, _day(4))

    _add(venue_staff_client, venue.id, _day(2), _day(7), first, second)

    assert _stored(db, first.id).status == "CANCELLED"
    assert _stored(db, second.id).status == "REJECTED"


@pytest.mark.story("9.5", ac=2)
def test_a_booking_outside_the_closure_or_at_another_venue_is_not_touched(db, venue_staff_client):
    """AC2. cannot fail first on its own assertions - nothing is ended today - so it is paired
    with the case above, which carries the red. The same venue outside the period, and another
    venue under a closure written without a save, are left alone."""
    venue, elsewhere = make_venue(db), make_venue(db)
    inside = _live(db, venue.id, _day(3))
    outside = _live(db, venue.id, _day(20))
    stranger = _live(db, elsewhere.id, _day(3))
    _period(db, elsewhere.id, _day(2), _day(7))

    _add(venue_staff_client, venue.id, _day(2), _day(7), inside)

    assert _stored(db, inside.id).status == "REJECTED"
    assert _stored(db, outside.id).status == "PENDING"
    assert _stored(db, stranger.id).status == "PENDING"


@pytest.mark.story("9.5", ac=2)
def test_the_events_other_bookings_and_equipment_do_not_change(db, venue_staff_client):
    """AC2: its approved booking at another venue, and an equipment request with its hold, stay
    as they were."""
    venue, other = make_venue(db), make_venue(db)
    event = _event_for(db, EventStatus.PLANNING)
    closed = _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    elsewhere = _pending_of(db, event, other.id, _day(3), status="APPROVED")
    item = make_equipment_item(
        db, event=event, equipment_type=make_equipment_type(db), quantity=1, is_held=True
    )
    equipment_before = db.execute(
        text("SELECT status, quantity FROM event_equipment_requests WHERE id = :id"),
        {"id": item.id},
    ).one()

    _add(venue_staff_client, venue.id, _day(2), _day(7), closed)

    assert _stored(db, closed.id).status == "CANCELLED"
    assert _stored(db, elsewhere.id).status == "APPROVED"
    assert (
        db.execute(
            text("SELECT status, quantity FROM event_equipment_requests WHERE id = :id"),
            {"id": item.id},
        ).one()
        == equipment_before
    )
    assert _status_of(db, event.id) == EventStatus.PLANNING


@pytest.mark.story("9.5", ac=2)
def test_each_ending_leaves_an_audit_row_naming_the_closure(db, venue_staff_client):
    """AC2: BOOKING_REJECTED for the request and BOOKING_RELEASED for the booking, each naming
    the actor, the venue, the event, the closure, its reason and the cause."""
    venue = make_venue(db)
    pending = _live(db, venue.id, _day(3))
    approved = _held(db, venue.id, _day(5))

    period = _add(
        venue_staff_client, venue.id, _day(2), _day(7), pending, approved, reason="SAFETY"
    )

    (rejected,) = _audit(db, "BOOKING_REJECTED", pending.id)
    (released,) = _audit(db, "BOOKING_RELEASED", approved.id)
    for entry, booking in ((rejected, pending), (released, approved)):
        assert entry.actor_id == STAFF_ID
        assert entry.entity_type == "venue_booking"
        assert entry.details["venue_id"] == str(venue.id)
        assert entry.details["event_id"] == str(booking.event_id)
        assert entry.details["closure_id"] == period["id"]
        assert entry.details["reason"] == "SAFETY"
    assert released.details["cause"] == "VENUE_UNAVAILABLE"


@pytest.mark.story("9.5", ac=2)
def test_editing_or_removing_the_closure_afterwards_leaves_the_record_as_it_was(
    db, venue_staff_client
):
    """AC2 (D18): the reason and description an ended booking carries are copied at the save,
    so a later edit of the closure's text, or its removal, does not change them."""
    venue = make_venue(db)
    booking = _held(db, venue.id, _day(3))
    period = _add(
        venue_staff_client,
        venue.id,
        _day(2),
        _day(7),
        booking,
        reason="MAINTENANCE",
        description="Servicing",
    )
    recorded = _closure(db, booking.id)
    assert recorded["closure_description"] == "Servicing"

    edited = _edit(
        venue_staff_client, venue.id, period["id"], reason="SAFETY", description="Rewiring"
    )
    removed = venue_staff_client.delete(_url(venue.id, uuid.UUID(period["id"])))

    assert edited.status_code == 200 and removed.status_code == 204
    assert _closure(db, booking.id) == recorded


@pytest.mark.story("9.5", ac=2)
def test_the_booking_records_carry_the_closure_fields_and_the_organisers_do_not(
    db, venue_staff_client, login_as
):
    """AC2 (D18): BookingOut, the queue entry and the event page's outcome carry the closure's
    reason and description; the organiser's own list carries neither - f7.1.3 adds the reason."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.PLANNING)
    booking = _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    _add(venue_staff_client, venue.id, _day(2), _day(7), booking, reason="SAFETY")

    record = venue_staff_client.get(f"/bookings/{booking.id}").json()
    queue = venue_staff_client.get("/bookings", params={"status": "CANCELLED"}).json()
    entry = next(item for item in queue["items"] if item["id"] == str(booking.id))
    outcome = next(
        item
        for item in venue_staff_client.get(f"/bookings/for-event/{event.id}").json()
        if item["id"] == str(booking.id)
    )
    for shown in (record, entry, outcome):
        assert (shown["closure_reason"], shown["closure_description"]) == (
            "SAFETY",
            "Scheduled servicing",
        )
    organiser = login_as(Users.ORGANISER).get(f"/bookings/for-my-event/{event.id}")
    assert organiser.status_code == 200, organiser.text
    for shown in organiser.json():
        assert "closure_reason" not in shown and "closure_description" not in shown


@pytest.mark.story("9.5", ac=2)
def test_the_closure_columns_hold_to_their_constraints(db):
    """AC2 (D18): the reason and description are both set or both null; only on a REJECTED or
    CANCELLED booking; a CANCELLED booking has the cause VENUE_UNAVAILABLE exactly when they are
    set; release_cause takes all six causes; and each new constraint has a comment."""

    def refused(status: str, cause: str | None, reason: str | None, description: str | None):
        booking = _booking(db, make_venue(db).id, _day(3), _day(3, 12), status="PENDING")
        values = {
            "id": booking.id,
            "status": status,
            "cause": cause,
            "reason": reason,
            "description": description,
        }
        try:
            with db.begin_nested():
                db.execute(
                    text(
                        "UPDATE venue_bookings SET status = :status, release_cause = :cause,"
                        " closure_reason = :reason, closure_description = :description,"
                        " cancelled_at = CASE WHEN :status = 'CANCELLED' THEN now() END"
                        " WHERE id = :id"
                    ),
                    values,
                )
        except IntegrityError:
            return True
        return False

    assert refused("PENDING", None, "SAFETY", "Wiring")
    assert refused("APPROVED", None, "SAFETY", "Wiring")
    assert refused("REJECTED", None, "SAFETY", None)
    assert refused("REJECTED", None, None, "Wiring")
    assert refused("CANCELLED", "VENUE_UNAVAILABLE", None, None)
    assert refused("CANCELLED", "EVENT_CANCELLED", "SAFETY", "Wiring")
    assert refused("REJECTED", None, "NOT_A_REASON", "Wiring")
    assert not refused("REJECTED", None, "SAFETY", "Wiring")
    assert not refused("CANCELLED", "VENUE_UNAVAILABLE", "OTHER", "Closed")
    named = db.execute(
        text(
            "SELECT c.conname, d.description FROM pg_constraint c"
            " LEFT JOIN pg_description d ON d.objoid = c.oid"
            " WHERE c.conrelid = 'venue_bookings'::regclass AND c.conname LIKE '%closure%'"
        )
    ).all()
    assert named, "no constraint on the closure columns"
    assert all(description for _, description in named)


@pytest.mark.story("9.5", ac=2)
def test_a_notice_that_fails_part_way_leaves_nothing_saved(db, monkeypatch):
    """AC2: one transaction. The second notice fails, so no period, no booking or event change,
    no audit entry and no notice from the save stays."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.CONFIRMED)
    booking = _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    db.commit()
    calls = []
    armed = [True]

    def failing(*args, **kwargs):
        calls.append(1)
        if armed[0] and len(calls) == 2:
            raise RuntimeError("the notice could not be written")

    for module in (booking_service, venue_service):
        monkeypatch.setattr(module, "notify", failing, raising=False)

    with pytest.raises(RuntimeError):
        venue_service.add_unavailability(
            db, venue.id, _data(booking), actor=_staff(db), now=datetime.now(UTC)
        )
    db.rollback()

    assert _periods(db, venue.id) == []
    assert _stored(db, booking.id).status == "APPROVED"
    assert _status_of(db, event.id) == EventStatus.CONFIRMED
    assert _audit(db, "BOOKING_RELEASED", booking.id) == []
    assert _notices(db, VENUE_UNAVAILABLE, event_id=event.id) == []
    # The same save, once the notices work, does end the booking: the refusal above changed
    # nothing, rather than nothing being there to change.
    armed[0] = False
    venue_service.add_unavailability(
        db, venue.id, _data(booking), actor=_staff(db), now=datetime.now(UTC)
    )
    assert _stored(db, booking.id).status == "CANCELLED"


# --- AC3: the event and its requirements -------------------------------------------------------
def _secured_scene(db: Session, status: str = EventStatus.PLANNING):
    """A secured event (21.2 AC1) in ``status`` whose requirement is covered by an approved
    booking at ``main`` and which holds a second, additional booking at ``closed``, both for
    the same hours ten days ahead. Returns (event, main_booking, extra_booking, closed, main)."""
    main, closed = make_venue(db, capacity=500), make_venue(db, capacity=500)
    secured = make_secured_event(
        db,
        status=status,
        starts_at=_day(10, 1),
        ends_at=_day(10, 9),
        venue_id=main.id,
        expected_attendance=60,
    )
    extra = make_booking(
        db,
        event_id=secured.event.id,
        venue_id=closed.id,
        starts_at=secured.event.starts_at,
        ends_at=secured.event.ends_at,
        status="APPROVED",
        expected_attendance=60,
        hold_expires_at=datetime.now(UTC) + timedelta(days=30),
        decided_by_id=STAFF_ID,
        decided_at=datetime.now(UTC) - timedelta(days=1),
    )
    return secured, extra, closed, main


def _approve_safety(db: Session, event: Event) -> None:
    """The Safety Officer's approval of the event as it stands now (21.2)."""
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


@pytest.mark.story("9.5", ac=3)
def test_a_planning_event_stays_in_planning(db, venue_staff_client):
    """AC3. cannot fail first on the status - nothing returns a Planning event today - so it
    is paired with the Confirmed case below, which carries the red; what it adds is that a
    cancelled booking and a rejected request both leave the event in Planning with no history
    row and no audit entry."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.PLANNING)
    approved = _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    pending = _pending_of(db, event, venue.id, _day(4))
    history_before = len(_history(db, event.id))

    _add(venue_staff_client, venue.id, _day(2), _day(7), approved, pending)

    assert _stored(db, approved.id).status == "CANCELLED"
    assert _stored(db, pending.id).status == "REJECTED"
    assert _status_of(db, event.id) == EventStatus.PLANNING
    assert len(_history(db, event.id)) == history_before
    assert _audit(db, RETURNED_TO_PLANNING, event.id) == []


@pytest.mark.story("9.5", ac=3)
def test_a_confirmed_event_goes_back_to_planning_when_its_booking_is_cancelled(
    db, venue_staff_client
):
    """AC3 (12.8 AC5): one history row naming the venue and the closure's reason, written by the
    Venue Staff member, an audit entry saying where it came from, and its booking CANCELLED -
    the event is not cancelled and keeps its details."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.CONFIRMED, name="Nimbus Developer Conference")
    booking = _pending_of(db, event, venue.id, _day(3), status="APPROVED")

    _add(venue_staff_client, venue.id, _day(2), _day(7), booking, reason="SAFETY")

    assert _status_of(db, event.id) == EventStatus.PLANNING
    (row,) = _returned(db, event.id)
    assert row.changed_by_id == STAFF_ID
    assert venue.name in row.reason and "Safety concern" in row.reason
    (entry,) = _audit(db, RETURNED_TO_PLANNING, event.id)
    assert entry.actor_id == STAFF_ID
    assert entry.details["from_status"] == EventStatus.CONFIRMED
    assert _stored(db, booking.id).status == "CANCELLED"
    assert db.get(Event, event.id).name == "Nimbus Developer Conference"


@pytest.mark.story("9.5", ac=3)
def test_an_event_awaiting_its_safety_check_goes_back_to_planning(db, venue_staff_client):
    """AC3 (12.8 AC5): the same for an event the Safety Officers have yet to decide, once, with
    a history row and an EVENT_RETURNED_TO_PLANNING audit entry saying where it came from."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.AWAITING_SAFETY_CHECK)
    booking = _pending_of(db, event, venue.id, _day(3), status="APPROVED")

    _add(venue_staff_client, venue.id, _day(2), _day(7), booking)

    assert _stored(db, booking.id).status == "CANCELLED"
    assert _status_of(db, event.id) == EventStatus.PLANNING
    (row,) = _returned(db, event.id)
    assert (row.from_status, row.to_status) == (
        EventStatus.AWAITING_SAFETY_CHECK,
        EventStatus.PLANNING,
    )
    assert venue.name in row.reason
    (entry,) = _audit(db, RETURNED_TO_PLANNING, event.id)
    assert entry.details["from_status"] == EventStatus.AWAITING_SAFETY_CHECK


@pytest.mark.story("9.5", ac=3)
def test_two_cancelled_bookings_of_one_event_move_it_once(db, venue_staff_client):
    """AC3: one status change, one history row, one audit entry."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.CONFIRMED)
    first = _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    second = _pending_of(db, event, venue.id, _day(4), status="APPROVED")

    _add(venue_staff_client, venue.id, _day(2), _day(7), first, second)

    assert {_stored(db, first.id).status, _stored(db, second.id).status} == {"CANCELLED"}
    assert _status_of(db, event.id) == EventStatus.PLANNING
    assert len(_returned(db, event.id)) == 1
    assert len(_audit(db, RETURNED_TO_PLANNING, event.id)) == 1


@pytest.mark.story("9.5", ac=3)
def test_a_confirmed_event_stays_confirmed_when_only_a_request_is_rejected(db, venue_staff_client):
    """AC3: an additional venue asked for after confirmation is still pending; the event never
    relied on it, so rejecting it does not send the event back."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.CONFIRMED)
    request = _pending_of(db, event, venue.id, _day(3))

    _add(venue_staff_client, venue.id, _day(2), _day(7), request)

    assert _stored(db, request.id).status == "REJECTED"
    assert _status_of(db, event.id) == EventStatus.CONFIRMED
    assert _returned(db, event.id) == []
    assert _audit(db, RETURNED_TO_PLANNING, event.id) == []


@pytest.mark.story("9.5", ac=3)
def test_a_planning_events_safety_approval_no_longer_allows_confirm(
    db, venue_staff_client, login_as
):
    """AC3 (12.8 AC6, 21.2 AC14): the additional venue's booking is cancelled, so the
    requirement is still booked and only the approval being out of date can stop the
    confirmation."""
    secured, extra, closed, _main = _secured_scene(db)
    _approve_safety(db, secured.event)
    db.commit()

    _add(venue_staff_client, closed.id, _day(9), _day(11), extra)

    assert _stored(db, extra.id).status == "CANCELLED"
    assert _status_of(db, secured.event.id) == EventStatus.PLANNING
    response = login_as(Users.COORDINATOR).post(f"/events/{secured.event.id}/confirm")
    assert response.status_code == 409
    assert APPROVAL_OUT_OF_DATE in response.json()["detail"]


@pytest.mark.story("9.5", ac=3)
def test_the_requirement_needs_a_venue_again_and_the_event_is_never_cancelled(
    db, venue_staff_client, login_as
):
    """AC3 (12.5): the requirement the cancelled booking covered takes a new request, which is
    refused only while a booking holds it; the event keeps its status and its details."""
    main, other = make_venue(db, capacity=500), make_venue(db, capacity=500)
    secured = make_secured_event(
        db,
        starts_at=_day(10, 1),
        ends_at=_day(10, 9),
        venue_id=main.id,
        expected_attendance=60,
    )
    event, booking, requirement_id = secured.event, secured.booking, secured.requirement_id
    db.commit()
    again = {
        "event_id": str(event.id),
        "venue_id": str(other.id),
        "venue_requirement_id": str(requirement_id),
    }

    _add(venue_staff_client, main.id, _day(9), _day(11), booking)

    assert _stored(db, booking.id).status == "CANCELLED"
    assert _status_of(db, event.id) == EventStatus.PLANNING
    response = login_as(Users.COORDINATOR).post("/bookings", json=again)
    assert response.status_code == 201, response.text


# --- AC4: who is told --------------------------------------------------------------------------
@pytest.mark.story("9.5", ac=4)
def test_the_coordinator_and_the_organiser_are_each_told_once_naming_what_ended(
    db, venue_staff_client
):
    """AC4: one notice each, about the event, with the venue, the period, the reason and which
    booking was cancelled and which request rejected; not one per booking. The coordinator's
    carries the description and the organiser's does not."""
    venue = make_venue(db)
    event = _event_for(db)
    approved = _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    pending = _pending_of(db, event, venue.id, _day(4))
    starts_at, ends_at = _day(2), _day(7)

    _add(
        venue_staff_client,
        venue.id,
        starts_at,
        ends_at,
        approved,
        pending,
        reason="RENOVATION",
        description="Floor relaid",
    )

    notices = _told(db, event.id)
    assert _recipients(notices) == sorted([Users.COORDINATOR.id, Users.ORGANISER.id])
    for notice in notices:
        assert venue.name in notice.title
        for wanted in (
            venue.name,
            _on_singapore_date(starts_at),
            _on_singapore_date(ends_at),
            "Renovation",
            "cancelled",
            "rejected",
        ):
            assert wanted in notice.message
        assert (notice.related_entity_type, notice.related_entity_id) == ("event", event.id)
    by_recipient = {notice.recipient_id: notice.message for notice in notices}
    assert "Floor relaid" in by_recipient[Users.COORDINATOR.id]
    assert "Floor relaid" not in by_recipient[Users.ORGANISER.id]


@pytest.mark.story("9.5", ac=4)
def test_an_event_with_no_coordinator_still_tells_its_organiser(db, venue_staff_client):
    """AC4: nobody is assigned yet, so the organiser alone is told, and nothing fails."""
    venue = make_venue(db)
    event = _event_for(db, assigned_coordinator_id=None)
    booking = _pending_of(db, event, venue.id, _day(3))

    _add(venue_staff_client, venue.id, _day(2), _day(7), booking)

    assert _stored(db, booking.id).status == "REJECTED"
    assert _recipients(_told(db, event.id)) == [Users.ORGANISER.id]


@pytest.mark.story("9.5", ac=4)
def test_after_a_reassignment_the_new_coordinator_is_told(db, venue_staff_client):
    """AC4 (20.1 AC4): whoever coordinates the event when the closure is saved, not whoever did
    when the booking was requested."""
    venue = make_venue(db)
    event = _event_for(db)
    booking = _pending_of(db, event, venue.id, _day(3))
    event.assigned_coordinator_id = Users.COORDINATOR_2.id
    db.flush()

    _add(venue_staff_client, venue.id, _day(2), _day(7), booking)

    assert _stored(db, booking.id).status == "REJECTED"
    assert _recipients(_told(db, event.id)) == sorted([Users.COORDINATOR_2.id, Users.ORGANISER.id])


@pytest.mark.story("9.5", ac=4)
def test_the_one_who_saved_is_never_told_and_nor_are_others(db, venue_staff_client):
    """AC4 (20.1 AC3): when the Venue Staff member who saves is also the event's assigned
    coordinator, they are told of nothing of their own doing; Technical Support, other
    organisers and coordinators, and registered attendees are told nothing."""
    venue = make_venue(db)
    event = _event_for(db, assigned_coordinator_id=STAFF_ID)
    booking = _pending_of(db, event, venue.id, _day(3), status="APPROVED")

    _add(venue_staff_client, venue.id, _day(2), _day(7), booking)

    assert _stored(db, booking.id).status == "CANCELLED"
    assert _recipients(_told(db, event.id)) == [Users.ORGANISER.id]
    unrelated = [
        Users.ORGANISER_2.id,
        Users.COORDINATOR.id,
        Users.COORDINATOR_2.id,
        Users.TECH_SUPPORT.id,
        Users.ATTENDEE.id,
        STAFF_ID,
    ]
    told = db.scalars(
        select(Notification.recipient_id).where(
            Notification.event_id == event.id, Notification.recipient_id.in_(unrelated)
        )
    ).all()
    assert list(told) == []


@pytest.mark.story("9.5", ac=4)
def test_every_other_active_venue_staff_member_is_told_of_each_booking_ended(
    db, venue_staff_client
):
    """AC4 (20.1 AC3, as 21.3 AC4): one BOOKING_RELEASED per booking ended, pending or approved,
    to every other active Venue Staff member - a rejected request under a title of its own - and
    to nobody else: not the member who saved, not an inactive one. It names the booking."""
    venue = make_venue(db)
    colleague = make_user(db, role="VENUE_STAFF")
    make_user(db, role="VENUE_STAFF", is_active=False)
    event = _event_for(db)
    approved = _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    pending = _pending_of(db, event, venue.id, _day(4))

    _add(venue_staff_client, venue.id, _day(2), _day(7), approved, pending)

    told_of_cancel = _notices(db, RELEASED, entity_id=approved.id)
    told_of_reject = _notices(db, RELEASED, entity_id=pending.id)
    for notices in (told_of_cancel, told_of_reject):
        assert [notice.recipient_id for notice in notices] == [colleague.id]
        assert notices[0].related_entity_type == "venue_booking"
        assert venue.name in notices[0].message
    assert told_of_reject[0].title != told_of_cancel[0].title


@pytest.mark.story("9.5", ac=4)
def test_the_safety_officers_are_told_when_an_event_goes_back_and_the_organiser_is_not_again(
    db, venue_staff_client
):
    """AC4 (as 12.8 AC5): EVENT_RETURNED_TO_PLANNING goes to the Safety Officers only - the
    organiser already has the closure's notice - and the coordinator gets no per-booking
    BOOKING_REJECTED. An event that stays Confirmed tells them nothing."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.CONFIRMED)
    booking = _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    staying = _event_for(db, EventStatus.CONFIRMED)
    request = _pending_of(db, staying, venue.id, _day(4))

    _add(venue_staff_client, venue.id, _day(2), _day(7), booking, request)

    returned = _notices(db, RETURNED_TO_PLANNING, event_id=event.id)
    assert Users.SAFETY_OFFICER.id in _recipients(returned)
    assert Users.ORGANISER.id not in _recipients(returned)
    assert Users.COORDINATOR.id not in _recipients(returned)
    assert _notices(db, RETURNED_TO_PLANNING, event_id=staying.id) == []
    assert _notices(db, REJECTED, event_id=staying.id) == []


@pytest.mark.story("9.5", ac=4)
def test_a_text_only_edit_tells_nobody(db, venue_staff_client):
    """AC4: editing the reason or description of a closure sends nothing and ends nothing; the
    notices of the first save are all there are."""
    venue = make_venue(db)
    event = _event_for(db)
    booking = _pending_of(db, event, venue.id, _day(3))
    period = _add(venue_staff_client, venue.id, _day(2), _day(7), booking)
    assert _stored(db, booking.id).status == "REJECTED"
    assert len(_told(db, event.id)) == 2
    released_before = len(_notices(db, RELEASED))

    _edit(venue_staff_client, venue.id, period["id"], reason="SAFETY")
    _edit(venue_staff_client, venue.id, period["id"], description="Rewiring")

    assert len(_told(db, event.id)) == 2
    assert len(_notices(db, RELEASED)) == released_before


@pytest.mark.story("9.5", ac=4)
def test_extending_tells_only_the_event_of_the_booking_it_newly_covers(db, venue_staff_client):
    """AC4: the event already told is not told again."""
    venue = make_venue(db)
    inside, beyond = _event_for(db), _event_for(db)
    first = _pending_of(db, inside, venue.id, _day(3))
    second = _pending_of(db, beyond, venue.id, _day(8))
    period = _add(venue_staff_client, venue.id, _day(2), _day(5), first)
    assert _stored(db, first.id).status == "REJECTED"
    assert len(_told(db, inside.id)) == 2 and _told(db, beyond.id) == []

    _edit(venue_staff_client, venue.id, period["id"], second, ends_at=_day(10).isoformat())

    assert _stored(db, second.id).status == "REJECTED"
    assert len(_told(db, inside.id)) == 2
    assert len(_told(db, beyond.id)) == 2


@pytest.mark.story("9.5", ac=4)
def test_the_notice_does_not_name_whoever_saved(db, venue_staff_client):
    """AC4: it says the venue is unavailable for the period, not that someone closed it."""
    venue = make_venue(db)
    event = _event_for(db)
    booking = _pending_of(db, event, venue.id, _day(3))
    saver = _staff(db).full_name

    _add(venue_staff_client, venue.id, _day(2), _day(7), booking)

    assert _stored(db, booking.id).status == "REJECTED"
    notices = _told(db, event.id)
    assert len(notices) == 2
    for notice in notices:
        assert saver not in notice.message


# --- AC5: only the part still to come counts ---------------------------------------------------
@pytest.mark.story("9.5", ac=5)
def test_overlapping_a_held_period_by_one_minute_ends_the_booking(db, venue_staff_client):
    """AC5: the least overlap there is."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3, 10))

    _add(
        venue_staff_client,
        venue.id,
        _day(3, 8),
        _day(3, 10) + timedelta(minutes=1),
        booking,
    )

    assert _stored(db, booking.id).status == "REJECTED"


@pytest.mark.story("9.5", ac=5)
def test_a_period_that_only_touches_the_booking_does_not_end_it(db, venue_staff_client):
    """AC5. cannot fail first on the status - nothing is ended today - so it is paired with
    the one-minute case above. A closure ending exactly where the booking's held period starts,
    and one starting exactly where it ends, leave it as it is, and neither is a 409."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3, 10))

    _add(venue_staff_client, venue.id, _day(3, 6), _day(3, 10))
    _add(venue_staff_client, venue.id, _day(3, 12), _day(3, 18))

    assert _stored(db, booking.id).status == "PENDING"


@pytest.mark.story("9.5", ac=5)
@pytest.mark.parametrize(
    ("period", "expected_ended"),
    [
        (((9, 15), (9, 45)), True),  # only the setup
        (((12, 15), (13, 0)), True),  # only the teardown
        (((8, 0), (9, 0)), False),  # touches held_from
        (((12, 30), (14, 0)), False),  # touches held_until
    ],
)
def test_the_overlap_is_measured_against_the_held_period(
    db, venue_staff_client, period, expected_ended
):
    """AC5: setup and teardown count, and the held period's own edges are half-open. The booking
    is 10:00-12:00 with 60 minutes' setup and 30 minutes' teardown: held 09:00-12:30. The two
    cases that touch an edge cannot fail first - nothing is ended today - and are paired with the
    two that overlap."""
    venue = make_venue(db)
    booking = _booking(
        db,
        venue.id,
        _day(3, 10),
        _day(3, 12),
        status="PENDING",
        setup_minutes=60,
        teardown_minutes=30,
    )
    (start_h, start_m), (end_h, end_m) = period

    _add(
        venue_staff_client,
        venue.id,
        _day(3, start_h) + timedelta(minutes=start_m),
        _day(3, end_h) + timedelta(minutes=end_m),
        *([booking] if expected_ended else []),
    )

    assert (_stored(db, booking.id).status == "REJECTED") is expected_ended


@pytest.mark.story("9.5", ac=5)
def test_a_completed_events_booking_is_not_listed_or_ended(db, venue_staff_client):
    """AC5. cannot fail first on the status of the completed one - it is not marked today
    either - so it is paired with the in-progress case, whose period covers both; the pair's
    red is that the in-progress one is ended."""
    venue = make_venue(db)
    now = datetime.now(UTC)
    completed = _booking(
        db,
        venue.id,
        now + timedelta(hours=3),
        now + timedelta(hours=5),
        status="APPROVED",
        event_status=EventStatus.COMPLETED,
    )
    under_way = _booking(
        db,
        venue.id,
        now - timedelta(hours=1),
        now + timedelta(hours=2),
        status="APPROVED",
        event_status=EventStatus.CONFIRMED,
    )
    assert _ids(_preview(venue_staff_client, venue.id, _day(-1), _day(1))) == {str(under_way.id)}

    _add(venue_staff_client, venue.id, _day(-1), _day(1), under_way)

    assert _stored(db, under_way.id).status == "CANCELLED"
    assert _stored(db, completed.id).status == "APPROVED"
    assert _status_of(db, completed.event_id) == EventStatus.COMPLETED
    assert _told(db, completed.event_id) == []


@pytest.mark.story("9.5", ac=5)
def test_a_booking_whose_held_period_is_over_is_not_ended(db, venue_staff_client):
    """AC5. cannot fail first, as above: a closure saved over days already gone ends nothing,
    though the booking was inside it, and lists nothing. Paired with the in-progress case."""
    venue = make_venue(db)
    gone = _booking(db, venue.id, _day(-6), _day(-6, 12), status="APPROVED")
    now = datetime.now(UTC)
    under_way = _booking(
        db,
        venue.id,
        now - timedelta(hours=1),
        now + timedelta(hours=2),
        status="APPROVED",
        event_status=EventStatus.CONFIRMED,
    )
    assert _ids(_preview(venue_staff_client, venue.id, _day(-8), _day(-4))) == set()

    _add(venue_staff_client, venue.id, _day(-8), _day(2), under_way)

    assert _stored(db, gone.id).status == "APPROVED"
    assert _stored(db, under_way.id).status == "CANCELLED"


@pytest.mark.story("9.5", ac=5)
@pytest.mark.parametrize(
    "event_status",
    [
        EventStatus.DRAFT,
        EventStatus.UNDER_REVIEW,
        EventStatus.CLARIFICATION_REQUESTED,
        EventStatus.CANCELLED,
        EventStatus.REJECTED,
    ],
)
def test_only_planning_awaiting_and_confirmed_events_are_candidates(
    db, venue_staff_client, event_status
):
    """AC5: a booking of an event in any other status is neither listed nor ended - a list of the
    statuses that count, so a status added later is left out until someone says it counts.
    cannot fail first: nothing is ended today; it is paired with the candidates below."""
    venue = make_venue(db)
    booking = _booking(
        db, venue.id, _day(3), _day(3, 12), status="PENDING", event_status=event_status
    )

    preview = _preview(venue_staff_client, venue.id, _day(2), _day(7))
    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert str(booking.id) not in _ids(preview)
    assert _stored(db, booking.id).status == "PENDING"


@pytest.mark.story("9.5", ac=5)
@pytest.mark.parametrize(
    "event_status",
    [EventStatus.PLANNING, EventStatus.AWAITING_SAFETY_CHECK, EventStatus.CONFIRMED],
)
def test_planning_awaiting_and_confirmed_events_are_candidates(
    db, venue_staff_client, event_status
):
    """AC5: their bookings are listed and ended."""
    venue = make_venue(db)
    booking = _booking(
        db, venue.id, _day(3), _day(3, 12), status="PENDING", event_status=event_status
    )
    assert str(booking.id) in _ids(_preview(venue_staff_client, venue.id, _day(2), _day(7)))

    _add(venue_staff_client, venue.id, _day(2), _day(7), booking)

    assert _stored(db, booking.id).status == "REJECTED"


# --- AC6: nothing is restored ------------------------------------------------------------------
@pytest.mark.story("9.5", ac=6)
@pytest.mark.parametrize("how", ["shorten", "end_now", "remove"])
def test_shortening_ending_early_or_removing_a_closure_restores_nothing(
    db, venue_staff_client, how
):
    """AC6: the cancelled booking stays cancelled with what it recorded, its event stays where
    the cancellation put it, and nobody is told or audited again."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.CONFIRMED)
    booking = _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    started = how == "end_now"
    period = _add(
        venue_staff_client,
        venue.id,
        _day(-1) if started else _day(2),
        _day(7),
        booking,
    )
    ended = _closure(db, booking.id)
    assert ended["status"] == "CANCELLED"
    notices_before = len(_notices(db, VENUE_UNAVAILABLE) + _notices(db, RELEASED))
    history_before = len(_history(db, event.id))
    period_id = uuid.UUID(period["id"])

    if how == "shorten":
        response = _edit(venue_staff_client, venue.id, period_id, ends_at=_day(2, 12).isoformat())
    elif how == "end_now":
        response = venue_staff_client.patch(_url(venue.id, period_id), json={"end_now": True})
    else:
        response = venue_staff_client.delete(_url(venue.id, period_id))

    assert response.status_code in (200, 204), response.text
    assert _closure(db, booking.id) == ended
    assert _status_of(db, event.id) == EventStatus.PLANNING
    assert len(_history(db, event.id)) == history_before
    assert len(_notices(db, VENUE_UNAVAILABLE) + _notices(db, RELEASED)) == notices_before


@pytest.mark.story("9.5", ac=6)
@pytest.mark.story("9.5", ac=9)
@pytest.mark.parametrize("status", ["PENDING", "APPROVED"])
def test_a_request_or_booking_a_closure_ended_cannot_be_approved_again(
    db, venue_staff_client, status
):
    """AC6 and AC9: nobody can undo what a closure did - Venue Staff's approval of the rejected
    request, or of the cancelled booking, is refused as not pending."""
    venue = make_venue(db)
    booking = _booking(db, venue.id, _day(3), _day(3, 12), status=status)
    _add(venue_staff_client, venue.id, _day(2), _day(7), booking)
    assert _stored(db, booking.id).status in ("REJECTED", "CANCELLED")

    response = _approve(venue_staff_client, booking.id)

    assert response.status_code == 409, response.text
    assert _stored(db, booking.id).status in ("REJECTED", "CANCELLED")


# --- AC7: the mark and 12.6's request path are gone --------------------------------------------
@pytest.mark.story("9.5", ac=7)
def test_no_response_carries_the_mark(db, venue_staff_client, login_as):
    """AC7: ``venue_unavailable_marked_at``, ``already_marked``, ``is_venue_unavailable`` and
    ``venue_unavailable_count`` are gone from every response that carried them: the booking
    record, the queue, the event page's outcomes, the organiser's list, the preview and the
    coordinator's event list."""
    venue = make_venue(db)
    event = _event_for(db)
    booking = _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    responses = [
        venue_staff_client.get(f"/bookings/{booking.id}"),
        venue_staff_client.get("/bookings"),
        venue_staff_client.get(f"/bookings/for-event/{event.id}"),
        _preview(venue_staff_client, venue.id, _day(2), _day(7)),
        login_as(Users.ORGANISER).get(f"/bookings/for-my-event/{event.id}"),
        login_as(Users.COORDINATOR).get("/events/assigned-to-me"),
    ]
    gone = (
        "venue_unavailable_marked_at",
        "already_marked",
        "is_venue_unavailable",
        "venue_unavailable_count",
    )
    for response in responses:
        assert response.status_code == 200, response.text
        for name in gone:
            assert name not in response.text, f"{name} in {response.request.url}"


@pytest.mark.story("9.5", ac=7)
def test_the_unavailable_filter_of_the_coordinators_events_is_gone(db, login_as):
    """AC7 (12.6 AC11): ``?venue_unavailable=true`` lists every assigned event as the plain list
    does."""
    venue = make_venue(db)
    _pending_of(db, _event_for(db), venue.id, _day(3), status="APPROVED")
    coordinator = login_as(Users.COORDINATOR)

    plain = coordinator.get("/events/assigned-to-me").json()
    narrowed = coordinator.get(
        "/events/assigned-to-me", params={"venue_unavailable": "true"}
    ).json()

    assert narrowed["total"] == plain["total"]


@pytest.mark.story("9.5", ac=7)
def test_the_replacement_request_route_and_the_search_exclusion_are_gone(
    db, login_as, venue_staff_client
):
    """AC7 (D2): ``POST /bookings/{id}/replacements`` has no route, and ``exclude_venue`` no
    longer keeps a venue out of the venue search."""
    venue = make_venue(db, name=f"Replace {uuid.uuid4().hex[:8]} Alpha", capacity=300)
    event = _event_for(db)
    booking = _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    other = make_venue(db)

    route = login_as(Users.COORDINATOR).post(
        f"/bookings/{booking.id}/replacements", json={"venue_id": str(other.id)}
    )
    found = login_as(Users.COORDINATOR).get(
        "/venues/search", params={"search": venue.name, "exclude_venue": str(venue.id)}
    )

    assert route.status_code == 404
    assert found.status_code == 200, found.text
    assert [v["name"] for v in found.json()["venues"]] == [venue.name]


def _with_a_pending_replacement(db: Session):
    """A secured event (21.2 AC1) whose approved booking still holds its requirement and which
    has a replacement for it still pending, as one raised before 9.5 leaves it (D3)."""
    from types import SimpleNamespace

    from tests.support.replacement import add_pending_replacement

    secured = make_secured_event(db)
    add_pending_replacement(
        db, SimpleNamespace(original=secured.booking, alternative=make_venue(db, capacity=500))
    )
    return secured


@pytest.mark.story("9.5", ac=7)
def test_a_pending_replacement_of_a_holding_original_no_longer_blocks_the_review(
    db, coordinator_client
):
    """AC7 (D3): the check for a pending replacement on the safety review is removed; the event
    is sent for its review as any other would be."""
    secured = _with_a_pending_replacement(db)

    response = coordinator_client.post(f"/safety-checks/{secured.event.id}/request", json={})

    assert response.status_code == 200, response.text


@pytest.mark.story("9.5", ac=7)
def test_a_pending_replacement_of_a_holding_original_no_longer_blocks_confirm(
    db, coordinator_client
):
    """AC7 (D3): the same for Confirm, once the event's review approved it."""
    secured = _with_a_pending_replacement(db)
    _approve_safety(db, secured.event)

    response = coordinator_client.post(f"/events/{secured.event.id}/confirm")

    assert response.status_code == 200, response.text


# --- AC8: the migration that closes the bookings still marked ----------------------------------
MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"
FALLBACK_DESCRIPTION = "The closure was no longer on record when story 9.5 shipped."

# The table as it stood before migration 035: no closure constraints and no closure record (the
# columns stay, since the model writes them), the five release causes (the closure's own cancelled
# bookings, which the seed holds, taken for event cancellations), and the 9.4 mark.
PRE_035_SCHEMA = """
ALTER TABLE venue_bookings DROP CONSTRAINT IF EXISTS ck_venue_bookings_closure_reason;
ALTER TABLE venue_bookings DROP CONSTRAINT IF EXISTS ck_venue_bookings_closure_fields;
ALTER TABLE venue_bookings DROP CONSTRAINT IF EXISTS ck_venue_bookings_closure_release;
UPDATE venue_bookings SET release_cause = 'EVENT_CANCELLED'
    WHERE release_cause = 'VENUE_UNAVAILABLE';
UPDATE venue_bookings SET closure_reason = NULL, closure_description = NULL;
ALTER TABLE venue_bookings ADD COLUMN IF NOT EXISTS venue_unavailable_marked_at timestamptz;
ALTER TABLE venue_bookings DROP CONSTRAINT ck_venue_bookings_release_cause;
ALTER TABLE venue_bookings ADD CONSTRAINT ck_venue_bookings_release_cause CHECK
    (release_cause IS NULL OR release_cause IN
     ('EVENT_CANCELLED', 'CHANGE_APPROVED', 'REPLACED', 'SAFETY_REVIEW', 'COORDINATOR_CANCELLED'));
"""


def _migration_035() -> str:
    found = sorted(MIGRATIONS.glob("035_*.sql"))
    assert found, "migration 035 does not exist yet"
    return found[0].read_text(encoding="utf-8")


def _mark_in_sql(db: Session, booking_id: uuid.UUID) -> None:
    """The 9.4 mark, written in SQL on the schema as it stood before 035."""
    db.execute(
        text("UPDATE venue_bookings SET venue_unavailable_marked_at = now() WHERE id = :id"),
        {"id": booking_id},
    )


def _closure_by(db: Session, period, user: User, age_days: float) -> None:
    """Who saved ``period`` and when, which the migration reads back (D20)."""
    db.execute(
        text(
            "UPDATE venue_unavailability_periods SET created_by_id = :by,"
            " created_at = now() - make_interval(days => :age) WHERE id = :id"
        ),
        {"by": user.id, "age": age_days, "id": period.id},
    )


def _run_035(db: Session) -> datetime:
    """Take the schema back to before 035 and run it, as the migrator would; returns the moment
    it ran, from the database's clock."""
    migration = _migration_035()
    started = db.execute(text("SELECT clock_timestamp()")).scalar_one()
    db.connection().exec_driver_sql(migration)
    return started


def _before_035(db: Session) -> None:
    db.connection().exec_driver_sql(PRE_035_SCHEMA)


def _migrated_scene(db: Session):
    """Marked bookings of every kind 035 meets, on a schema taken back to before it: a pending
    request and an approved booking under a closure two Venue Staff members saved (the earlier
    one counts, D20), an approved booking of a Cancelled event (D1), an unmarked approved booking,
    a marked pending replacement of a marked approved original (D15), and a marked pending
    replacement of an unmarked original (the seed's ...012638)."""
    from tests.support.replacement import add_pending_replacement, make_scenario

    _before_035(db)
    first = make_user(db, role="VENUE_STAFF")
    second = make_user(db, role="VENUE_STAFF")
    venue = make_venue(db)
    early = _period(db, venue.id, _day(2), _day(7), reason="SAFETY", notes="Wiring")
    late = _period(db, venue.id, _day(1), _day(8), reason="RENOVATION", notes="Floor")
    _closure_by(db, early, first, 3)
    _closure_by(db, late, second, 1)
    pending = _live(db, venue.id, _day(3))
    approved = _held(db, venue.id, _day(4))
    unmarked = _held(db, venue.id, _day(5))
    cancelled_event = _booking(
        db, venue.id, _day(6), _day(6, 12), status="APPROVED", event_status=EventStatus.CANCELLED
    )
    for booking in (pending, approved, cancelled_event):
        _mark_in_sql(db, booking.id)

    linked = make_scenario(db)
    link_replacement = add_pending_replacement(db, linked)
    alone = make_scenario(db)
    alone_replacement = add_pending_replacement(db, alone)
    for scenario, ids in ((linked, (linked.original.id, link_replacement.id)), (alone, ())):
        for venue_of in (scenario.original_venue, scenario.alternative):
            _period(
                db,
                venue_of.id,
                scenario.starts_at - timedelta(days=1),
                scenario.ends_at + timedelta(days=1),
                reason="OTHER",
                notes="Closed",
            )
        for booking_id in ids:
            _mark_in_sql(db, booking_id)
    _mark_in_sql(db, alone_replacement.id)
    return {
        "first": first,
        "early": early,
        "pending": pending,
        "approved": approved,
        "unmarked": unmarked,
        "cancelled_event": cancelled_event,
        "linked": linked,
        "link_replacement": link_replacement,
        "alone": alone,
        "alone_replacement": alone_replacement,
    }


@pytest.mark.story("9.5", ac=8)
def test_migration_035_closes_the_marked_bookings_with_the_earliest_closures_record(db):
    """AC8 and D18-D20: a marked pending request is REJECTED and a marked approved booking
    CANCELLED with VENUE_UNAVAILABLE. Who, the reason and the description come from the earliest
    closure that overlaps it; when is the migration's own moment. An unmarked booking is left
    alone, and the events keep their status."""
    scene = _migrated_scene(db)
    notices_before = db.scalar(select(func.count()).select_from(Notification))
    event_status = {
        booking.id: _status_of(db, booking.event_id)
        for booking in (scene["pending"], scene["approved"])
    }

    started = _run_035(db)

    rejected = _closure(db, scene["pending"].id)
    assert rejected["status"] == "REJECTED"
    assert rejected["decided_by_id"] == scene["first"].id and rejected["decided_at"] >= started
    assert rejected["decision_reason"] == "Venue closed: Safety concern"
    assert (rejected["closure_reason"], rejected["closure_description"]) == ("SAFETY", "Wiring")
    cancelled = _closure(db, scene["approved"].id)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["release_cause"] == "VENUE_UNAVAILABLE"
    assert cancelled["released_by_id"] == scene["first"].id and cancelled["cancelled_at"] >= started
    assert (cancelled["closure_reason"], cancelled["closure_description"]) == ("SAFETY", "Wiring")
    assert _closure(db, scene["unmarked"].id)["status"] == "APPROVED"
    for booking in (scene["pending"], scene["approved"]):
        assert _status_of(db, booking.event_id) == event_status[booking.id]
    assert db.scalar(select(func.count()).select_from(Notification)) == notices_before


@pytest.mark.story("9.5", ac=8)
def test_migration_035_leaves_a_marked_booking_of_a_cancelled_event_alone(db):
    """D1: a booking of an event that is already Cancelled is not a candidate (AC5), marked or
    not; the seed's heritage walk is fixed in the seed, not by the migration."""
    scene = _migrated_scene(db)

    _run_035(db)

    assert _closure(db, scene["cancelled_event"].id)["status"] == "APPROVED"


@pytest.mark.story("9.5", ac=8)
def test_migration_035_audits_each_booking_it_ends_and_tells_nobody(db):
    """D8: one audit row each - BOOKING_REJECTED or BOOKING_RELEASED - by the system, naming the
    closure, the cause and the migration; no notice is written."""
    scene = _migrated_scene(db)

    _run_035(db)

    (rejected,) = _audit(db, "BOOKING_REJECTED", scene["pending"].id)
    (released,) = _audit(db, "BOOKING_RELEASED", scene["approved"].id)
    for entry in (rejected, released):
        assert entry.actor_id is None
        assert entry.details["closure_id"] == str(scene["early"].id)
        assert entry.details["migration"] == "035"
    assert released.details["cause"] == "VENUE_UNAVAILABLE"


@pytest.mark.story("9.5", ac=8)
def test_migration_035_rejects_a_marked_replacement_before_it_cancels_its_original(db):
    """D15: the request is rejected first, so closing its original does not clear the link it
    carries as history; a pending replacement of an unmarked original is rejected too and its
    original stays approved (the seed's ...012638 and ...012637)."""
    scene = _migrated_scene(db)

    _run_035(db)

    linked = _closure(db, scene["link_replacement"].id)
    assert linked["status"] == "REJECTED"
    assert _closure(db, scene["linked"].original.id)["status"] == "CANCELLED"
    stored = db.execute(
        text("SELECT replaces_booking_id FROM venue_bookings WHERE id = :id"),
        {"id": scene["link_replacement"].id},
    ).scalar_one()
    assert stored == scene["linked"].original.id
    assert _closure(db, scene["alone_replacement"].id)["status"] == "REJECTED"
    assert _closure(db, scene["alone"].original.id)["status"] == "APPROVED"


@pytest.mark.story("9.5", ac=8)
def test_migration_035_names_other_when_no_closure_is_left_on_record(db):
    """D9: a marked booking no closure covers is closed with the reason OTHER and an apology for
    the missing description."""
    _before_035(db)
    venue = make_venue(db)
    orphan = _held(db, venue.id, _day(3))
    _mark_in_sql(db, orphan.id)

    _run_035(db)

    row = _closure(db, orphan.id)
    assert row["status"] == "CANCELLED"
    assert (row["closure_reason"], row["closure_description"]) == ("OTHER", FALLBACK_DESCRIPTION)


@pytest.mark.story("9.5", ac=8)
def test_migration_035_drops_the_mark_last(db):
    """B2: the mark column is gone once the migration has read it."""
    _before_035(db)

    _run_035(db)

    columns = db.execute(
        text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'venue_bookings' AND column_name = 'venue_unavailable_marked_at'"
        )
    ).all()
    assert columns == []


# --- AC10: races ---------------------------------------------------------------------------------
# Real concurrent transactions, so these tests commit and clean up after themselves.
def _save(engine, venue_id, *covered, starts_at=None, ends_at=None) -> None:
    with Session(engine) as session:
        venue_service.add_unavailability(
            session,
            venue_id,
            _data(*covered, starts_at=starts_at, ends_at=ends_at),
            actor=session.get(User, STAFF_ID),
            now=datetime.now(UTC),
        )


@pytest.mark.story("9.5", ac=10)
def test_an_approval_that_wins_the_lock_is_approved_and_the_save_then_cancels_it(engine):
    """AC10, approve first. The approval holds the request's row; the save, which listed the
    request as pending and confirmed it, waits on the row; the approval commits and the save
    ends the request as it now stands - approved, so cancelled, not rejected."""
    venue_id, event_id, booking_id = _committed_pending_request(engine)
    pids: dict[str, int] = {}
    holding = threading.Event()

    def approve() -> None:
        with Session(engine) as session:
            pids["approve"] = backend_pid(session)
            booking = booking_service.get_booking_for_approval(session, booking_id)
            holding.set()
            wait_until_waiting(engine, pids, "save")
            booking_service.approve_booking(
                session,
                booking,
                actor_id=STAFF_ID,
                hold_expires_at=datetime.now(UTC) + timedelta(days=1),
            )

    def save() -> None:
        with Session(engine) as session:
            pids["save"] = backend_pid(session)
            assert holding.wait(LOCK_WAIT_SECONDS)
            venue_service.add_unavailability(
                session,
                venue_id,
                _data(booking_id),
                actor=session.get(User, STAFF_ID),
                now=datetime.now(UTC),
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            approving = pool.submit(approve)
            saving = pool.submit(save)
            approving.result(timeout=40)
            saving.result(timeout=40)

        with Session(engine) as session:
            row = session.get(VenueBooking, booking_id)
            assert (row.status, row.release_cause) == ("CANCELLED", "VENUE_UNAVAILABLE")
            assert row.decided_by_id == STAFF_ID  # the approval is on the record
    finally:
        _remove_race_rows(engine, venue_id, event_id, booking_id)


@pytest.mark.story("9.5", ac=10)
def test_a_save_that_wins_the_lock_rejects_the_request_and_the_approval_finds_it_rejected(engine):
    """AC10, save first. The save rejects the request and holds its row; the approval waits on
    it; the save commits, and the approval, reading the request once the lock is its, is refused
    as not pending - the request is REJECTED, nobody approved it."""
    venue_id, event_id, booking_id = _committed_pending_request(engine)
    pids: dict[str, int] = {}
    holding = threading.Event()

    def save() -> None:
        with Session(engine) as session:
            pids["save"] = backend_pid(session)
            _pause_before_commit(session, engine, pids, holding, "approve")
            venue_service.add_unavailability(
                session,
                venue_id,
                _data(booking_id),
                actor=session.get(User, STAFF_ID),
                now=datetime.now(UTC),
            )

    def approve() -> Exception | None:
        with Session(engine) as session:
            pids["approve"] = backend_pid(session)
            assert holding.wait(LOCK_WAIT_SECONDS)
            try:
                booking = booking_service.get_booking_for_approval(session, booking_id)
                booking_service.approve_booking(
                    session,
                    booking,
                    actor_id=STAFF_ID,
                    hold_expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            except (booking_service.BookingNotPending, booking_service.VenueBlocked) as refusal:
                return refusal
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            saving = pool.submit(save)
            approving = pool.submit(approve)
            saving.result(timeout=40)
            refusal = approving.result(timeout=40)

        assert isinstance(refusal, booking_service.BookingNotPending), refusal
        with Session(engine) as session:
            row = session.get(VenueBooking, booking_id)
            assert row.status == "REJECTED"
            assert row.hold_expires_at is None
    finally:
        _remove_race_rows(engine, venue_id, event_id, booking_id)


@pytest.mark.story("9.5", ac=10)
def test_a_save_and_the_events_confirmation_at_the_same_moment_both_finish(engine):
    """AC10. The confirmation holds the event's row (it sets the event to Confirmed again, which
    fires trg_events_complete_venue_holds and updates its approved bookings); the save, which
    returns a Confirmed event to Planning, waits on that row; the confirmation commits and the
    save goes on. The save locks the event before its bookings, as the confirmation does, so
    neither waits on the other for ever: both finish, the booking is cancelled, the event's return
    to Planning is recorded once, and the hold the confirmation completed stays completed."""
    expiry = datetime.now(UTC) + timedelta(days=1)
    with Session(engine) as session:
        venue = make_venue(session)
        event = _event_for(session, EventStatus.CONFIRMED)
        booking = _pending_of(
            session, event, venue.id, _day(3), status="APPROVED", hold_expires_at=expiry
        )
        session.commit()
        venue_id, event_id, booking_id = venue.id, event.id, booking.id
    pids: dict[str, int] = {}
    holding = threading.Event()

    def confirm() -> None:
        with Session(engine) as session:
            pids["confirm"] = backend_pid(session)
            for status in (EventStatus.PLANNING, EventStatus.CONFIRMED):
                session.execute(update(Event).where(Event.id == event_id).values(status=status))
            holding.set()
            wait_until_waiting(engine, pids, "save")
            session.commit()

    def save() -> None:
        with Session(engine) as session:
            pids["save"] = backend_pid(session)
            assert holding.wait(LOCK_WAIT_SECONDS)
            venue_service.add_unavailability(
                session,
                venue_id,
                _data(booking_id),
                actor=session.get(User, STAFF_ID),
                now=datetime.now(UTC),
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            confirming = pool.submit(confirm)
            saving = pool.submit(save)
            confirming.result(timeout=40)
            saving.result(timeout=40)

        with Session(engine) as session:
            row = session.get(VenueBooking, booking_id)
            assert row.status == "CANCELLED"
            assert row.hold_completed_at is not None
            assert session.get(Event, event_id).status == EventStatus.PLANNING
            returned = [
                history
                for history in session.scalars(
                    select(EventStatusHistory).where(EventStatusHistory.event_id == event_id)
                )
                if history.changed_by_id == STAFF_ID
                and (history.from_status, history.to_status)
                == (EventStatus.CONFIRMED, EventStatus.PLANNING)
            ]
            assert len(returned) == 1
    finally:
        _remove_race_rows(engine, venue_id, event_id, booking_id)


@pytest.mark.story("9.5", ac=10)
def test_a_save_that_holds_the_event_first_and_a_confirmation_that_follows_both_finish(
    engine, monkeypatch
):
    """AC10, save first. The save holds the event's row, then pauses before it returns the event
    to Planning; the confirmation starts and blocks on that row; once it is waiting, the save goes
    on and commits; the confirmation then goes through. Both finish. Without the save's lock on the
    event the confirmation took the event first, its trigger then waited on the bookings the save
    held, and the save's own update of the event waited on the confirmation: a deadlock."""
    expiry = datetime.now(UTC) + timedelta(days=1)
    with Session(engine) as session:
        venue = make_venue(session)
        event = _event_for(session, EventStatus.CONFIRMED)
        booking = _pending_of(
            session, event, venue.id, _day(3), status="APPROVED", hold_expires_at=expiry
        )
        session.commit()
        venue_id, event_id, booking_id = venue.id, event.id, booking.id
    pids: dict[str, int] = {}
    holding = threading.Event()
    original = events_service.return_event_to_planning

    def paused(*args, **kwargs):
        holding.set()
        wait_until_waiting(engine, pids, "confirm")
        return original(*args, **kwargs)

    monkeypatch.setattr(events_service, "return_event_to_planning", paused)

    def save() -> None:
        with Session(engine) as session:
            pids["save"] = backend_pid(session)
            venue_service.add_unavailability(
                session,
                venue_id,
                _data(booking_id),
                actor=session.get(User, STAFF_ID),
                now=datetime.now(UTC),
            )

    def confirm() -> None:
        with Session(engine) as session:
            pids["confirm"] = backend_pid(session)
            assert holding.wait(LOCK_WAIT_SECONDS)
            for status in (EventStatus.PLANNING, EventStatus.CONFIRMED):
                session.execute(update(Event).where(Event.id == event_id).values(status=status))
            session.commit()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            saving = pool.submit(save)
            confirming = pool.submit(confirm)
            saving.result(timeout=40)
            confirming.result(timeout=40)

        with Session(engine) as session:
            row = session.get(VenueBooking, booking_id)
            assert row.status == "CANCELLED"
            # Cancelled before the confirmation ran, so its trigger completed no hold.
            assert row.hold_completed_at is None
            assert session.get(Event, event_id).status == EventStatus.CONFIRMED
            returned = [
                history
                for history in session.scalars(
                    select(EventStatusHistory).where(EventStatusHistory.event_id == event_id)
                )
                if history.changed_by_id == STAFF_ID
                and (history.from_status, history.to_status)
                == (EventStatus.CONFIRMED, EventStatus.PLANNING)
            ]
            assert len(returned) == 1
    finally:
        _remove_race_rows(engine, venue_id, event_id, booking_id)


@pytest.mark.story("9.5", ac=10)
def test_two_saves_at_once_end_a_booking_once_and_tell_once(engine):
    """AC10: one save rejects the request and holds its row; the other, over the same booking,
    waits; once the first commits the second finds it already ended, and ends and tells
    nothing more - one audit entry, one notice each for the coordinator and the organiser."""
    venue_id, event_id, booking_id = _committed_pending_request(engine)
    pids: dict[str, int] = {}
    holding = threading.Event()

    def first() -> None:
        with Session(engine) as session:
            pids["first"] = backend_pid(session)
            _pause_before_commit(session, engine, pids, holding, "second")
            venue_service.add_unavailability(
                session,
                venue_id,
                _data(booking_id),
                actor=session.get(User, STAFF_ID),
                now=datetime.now(UTC),
            )

    def second() -> None:
        with Session(engine) as session:
            pids["second"] = backend_pid(session)
            assert holding.wait(LOCK_WAIT_SECONDS)
            venue_service.add_unavailability(
                session,
                venue_id,
                _data(booking_id, starts_at=_day(1), ends_at=_day(8)),
                actor=session.get(User, STAFF_ID),
                now=datetime.now(UTC),
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(first)
            two = pool.submit(second)
            one.result(timeout=40)
            two.result(timeout=40)

        with Session(engine) as session:
            assert session.get(VenueBooking, booking_id).status == "REJECTED"
            rejections = session.scalars(
                select(AuditLog).where(
                    AuditLog.entity_id == booking_id, AuditLog.action == "BOOKING_REJECTED"
                )
            ).all()
            told = session.scalars(
                select(Notification).where(
                    Notification.event_id == event_id,
                    Notification.notification_type == VENUE_UNAVAILABLE,
                )
            ).all()
            assert len(rejections) == 1
            assert len(told) == 2
    finally:
        _remove_race_rows(engine, venue_id, event_id, booking_id)


@pytest.mark.story("9.5", ac=10)
def test_a_request_that_slipped_in_during_a_save_still_cannot_be_approved(db, login_as):
    """AC10 (9.4 AC7): a request raised at the instant of a save sits pending inside the
    closure, missed. Its approval is refused while the closure stands and the request is left
    pending. cannot fail first: the approval check reads the closure itself and is in place
    today; it pins the rule for the missed request, which 9.5 no longer marks."""
    venue = make_venue(db)
    _period(db, venue.id, _day(2), _day(7))
    slipped = _live(db, venue.id, _day(3))

    refused = _approve(login_as(Users.VENUE_STAFF), slipped.id)

    assert refused.status_code == 409, refused.text
    assert _stored(db, slipped.id).status == "PENDING"


@pytest.mark.story("9.5", ac=10)
def test_a_lapsed_hold_is_released_before_the_preview_and_the_save_look(db, venue_staff_client):
    """AC10: an approved booking whose hold has lapsed holds nothing, as the calendar already
    treats it; the preview does not list it and the save does not cancel or tell anyone of it,
    whichever comes first - the routes release lapsed holds as the calendar's does. cannot fail
    first: the sweep is on every closure route today; it pins that the booking stays EXPIRED."""
    venue = make_venue(db)
    event = _event_for(db)
    lapsed = _pending_of(
        db,
        event,
        venue.id,
        _day(3),
        status="APPROVED",
        hold_expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    preview = _preview(venue_staff_client, venue.id, _day(2), _day(7))
    assert str(lapsed.id) not in _ids(preview)
    other_venue = make_venue(db)
    other_event = _event_for(db)
    lapsed2 = _pending_of(
        db,
        other_event,
        other_venue.id,
        _day(4),
        status="APPROVED",
        hold_expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    _add(venue_staff_client, other_venue.id, _day(2), _day(7))

    assert _stored(db, lapsed.id).status == "EXPIRED"
    assert _stored(db, lapsed2.id).status == "EXPIRED"
    assert _audit(db, "BOOKING_RELEASED", lapsed2.id) == []
    assert _told(db, other_event.id) == []


@pytest.mark.story("9.5", ac=10)
@pytest.mark.parametrize("method", ["patch", "delete"])
def test_a_lapsed_hold_is_released_before_an_edit_or_a_removal(db, venue_staff_client, method):
    """AC10: the edit and the removal release lapsed holds as the add and the preview do. cannot
    fail first: the dependency is on every write route today; it is pinned beside the add's."""
    venue = make_venue(db)
    period = _period(db, venue.id, _days_from_now(10), _days_from_now(12))
    lapsed = _pending_of(
        db,
        _event_for(db),
        make_venue(db).id,
        _day(3),
        status="APPROVED",
        hold_expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    if method == "patch":
        response = venue_staff_client.patch(_url(venue.id, period.id), json={"description": "x"})
    else:
        response = venue_staff_client.delete(_url(venue.id, period.id))

    assert response.status_code in (200, 204), response.text
    assert _stored(db, lapsed.id).status == "EXPIRED"


@pytest.mark.story("9.5", ac=10)
def test_the_same_save_sent_twice_makes_two_closures_and_ends_nothing_more(db, venue_staff_client):
    """AC10 (a double-click): the second save has nothing left to end, so it is accepted, adds
    its closure, and rejects, cancels, audits and tells nobody again."""
    venue = make_venue(db)
    event = _event_for(db)
    booking = _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    _add(venue_staff_client, venue.id, _day(2), _day(7), booking)
    recorded = _closure(db, booking.id)
    told_before = len(_told(db, event.id))

    _add(venue_staff_client, venue.id, _day(2), _day(7), booking)

    assert len(_periods(db, venue.id)) == 2
    assert _closure(db, booking.id) == recorded
    assert len(_audit(db, "BOOKING_RELEASED", booking.id)) == 1
    assert told_before == 2 and len(_told(db, event.id)) == told_before
