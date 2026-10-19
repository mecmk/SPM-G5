"""Story 12.6 - Request a replacement venue for an affected booking

Happy path
1. On an approved booking marked "Venue unavailable – alternative needed" (9.4), the assigned
    coordinator selects "Find a replacement venue" on the event page. The catalogue opens
    pre-filled from that booking's venue requirement (8.4), or, for an additional venue, from the
    event's own period and attendance, with the unavailable venue excluded. The banner names the
    booking being replaced, and stays while the coordinator changes or clears the filters.
2. "Request this venue" raises a new booking request linked to the original booking as its
    replacement, carrying the original's setup and teardown (still editable on the request step).
    The event's details, status and other venue bookings are not changed.
3. When Venue Staff approve the replacement (13.2), the original booking is released (Cancelled)
    in the same step. The event's booking list shows the original as "Replaced by <venue>", closed
    at the time of the release, and the replacement as "Replaces <venue>". Before approving, Venue
    Staff see "Replaces <venue>" and "Approving this releases <venue>". The coordinator's approval
    notice says the original was released and Venue Staff are told of the release; the organiser
    is not notified.

Boundary
4. Until a replacement is approved, the original booking stays approved and on record. The banner
    (12.5) shows its requirement as "Venue unavailable: <venue>", or "Replacement requested:
    <venue>" while one is pending. The event page does not show "All required venues booked" while
    a requirement's only booking is marked, and Find a venue skips marked requirements.

Edge
5. If the replacement is rejected or withdrawn, the original booking stays marked and another
    replacement can be requested.
6. If the unavailability ends before a replacement is approved (9.4 AC6), the mark clears and
    "Find a replacement venue" disappears; the coordinator can withdraw the pending replacement
    and keep the original booking. If Venue Staff approve it anyway, it still replaces the
    original.
7. A replacement caused by venue unavailability does not need an organiser change request (19.1),
    including when its suitability is overridden with a justification (11.1).
8. No replacement can be requested on a cancelled event (6.2). A replacement that was never
    approved is never shown as having replaced the original.

Permission
9. Only the event's assigned coordinator can request a replacement venue. Only an approved marked
    booking can be replaced. A marked pending booking for a requirement offers "Find another
    venue", which leads to "Switch to this venue" (12.5); a marked pending additional venue is
    withdrawn and requested again.

Conflict
10. Only one pending replacement request is allowed per original booking: while one is pending,
    "Find a replacement venue" is not offered, a second request is refused naming the venue
    already requested, and the pending replacement cannot be switched (withdraw it first). A
    replacement at the original booking's own venue is refused. If two replacements are sent at
    once, only the first succeeds.

Coordinator event list
11. The assigned coordinator's Events inbox has a "Venue unavailable" tab listing only their
    events with a booking marked "Venue unavailable – alternative needed", with the number of such
    events on the tab (0 when none). An event with a pending replacement stays listed and shows
    "Replacement requested: <venue>". Opening an event shows the marked booking. An event leaves
    the tab once no booking on it is marked.

Safety review and confirmation
12. While any booking on an event is marked "Venue unavailable – alternative needed" (9.4), or has
    a pending replacement, the coordinator cannot send the event for safety review (21.2) or
    confirm it. The refusal names each such venue together with any other missing arrangement.
    Once the replacement is approved or withdrawn, or the unavailability ends with no replacement
    pending, the event can be sent and confirmed as usual.

This file raises the replacement, and what follows from raising it: AC2, AC4-AC10. The search that
leaves out the unavailable venue (AC1) is test_venue_search_exclude_venue.py and the page flow is
tests/e2e/venue-replacement.spec.ts. Approval, the release of the original and the "Replaced by"
display are test_replacement_approval.py; the schema's own guards (the composite foreign key, the
index and its trigger) are test_replacement_schema.py; what Venue Staff see is
test_replacement_for_venue_staff.py. The one-per-requirement rule of 12.5 still refuses a normal
second request, whatever the replacement's state.

Every case builds its own event, venues and booking (``make_scenario``), dated 45 days ahead, so
no seeded booking is in the way.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings import schemas as booking_schemas
from app.bookings import service
from app.bookings.models import BookingStatus, VenueBooking
from app.common.audit import AuditLog
from app.events.models import Event, EventStatus
from app.venues import service as venue_service
from tests.support.factories import (
    make_booking,
    make_event,
    make_unavailability,
    make_venue,
)
from tests.support.replacement import (
    BOOKINGS_PATH,
    SETUP_MINUTES,
    TEARDOWN_MINUTES,
    add_pending_replacement,
    approve,
    column,
    created,
    end_the_closure,
    hall,
    make_scenario,
    notifications_of,
    purge,
    replace,
    set_status,
    when,
)
from tests.support.seed import SeedUser, Users


def _moment(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _bookings_of(db: Session, event: Event) -> list[VenueBooking]:
    db.expire_all()
    return list(
        db.scalars(
            select(VenueBooking)
            .where(VenueBooking.event_id == event.id)
            .order_by(VenueBooking.created_at, VenueBooking.id)
        ).all()
    )


# --- AC2: the replacement is raised pending and linked ------------------------------------------
@pytest.mark.story("12.6", ac=2)
def test_a_replacement_is_raised_pending_and_linked_to_the_original(coordinator_client, db):
    scene = make_scenario(db)

    body = created(replace(coordinator_client, scene.original.id, scene.alternative))

    assert body["status"] == BookingStatus.PENDING
    assert body["venue_id"] == str(scene.alternative.id)
    assert body["event_id"] == str(scene.event.id)
    assert body["venue_requirement_id"] == str(scene.requirement_id)
    assert (_moment(body["starts_at"]), _moment(body["ends_at"])) == (
        scene.starts_at,
        scene.ends_at,
    )
    assert (body["expected_attendance"], body["required_layout_code"]) == (40, "CLASSROOM")
    assert column(db, uuid.UUID(body["id"]), "replaces_booking_id") == scene.original.id


@pytest.mark.story("12.6", ac=2)
def test_a_replacement_carries_the_originals_setup_and_teardown_by_default(coordinator_client, db):
    scene = make_scenario(db)

    body = created(replace(coordinator_client, scene.original.id, scene.alternative))

    assert (body["setup_minutes"], body["teardown_minutes"]) == (SETUP_MINUTES, TEARDOWN_MINUTES)


@pytest.mark.story("12.6", ac=2)
@pytest.mark.parametrize(
    "sent",
    [{"setup_minutes": 0, "teardown_minutes": 0}, {"setup_minutes": 90}],
    ids=["zero", "one"],
)
def test_explicit_setup_and_teardown_override_the_originals_even_zero(coordinator_client, db, sent):
    """Zero is a choice, not an omission; one value sent leaves the other the original's."""
    scene = make_scenario(db)

    body = created(replace(coordinator_client, scene.original.id, scene.alternative, **sent))

    assert body["setup_minutes"] == sent["setup_minutes"]
    assert body["teardown_minutes"] == sent.get("teardown_minutes", TEARDOWN_MINUTES)


@pytest.mark.story("12.6", ac=2)
@pytest.mark.parametrize(
    "field,value", [("setup_minutes", -1), ("teardown_minutes", 20161), ("setup_minutes", 1.5)]
)
def test_setup_and_teardown_out_of_range_are_refused(coordinator_client, db, field, value):
    """As for any request (12.1 AC5): whole minutes, none negative, at most 14 days."""
    scene = make_scenario(db)

    response = replace(coordinator_client, scene.original.id, scene.alternative, **{field: value})

    assert response.status_code == 422
    assert [booking.id for booking in _bookings_of(db, scene.event)] == [scene.original.id]


@pytest.mark.story("12.6", ac=2)
def test_a_replacement_for_an_additional_venue_carries_the_events_period_and_attendance(
    coordinator_client, db
):
    scene = make_scenario(db, additional=True)

    body = created(replace(coordinator_client, scene.original.id, scene.alternative))

    assert body["venue_requirement_id"] is None
    assert (_moment(body["starts_at"]), _moment(body["ends_at"])) == (
        scene.starts_at,
        scene.ends_at,
    )
    assert body["expected_attendance"] == 40
    assert column(db, uuid.UUID(body["id"]), "replaces_booking_id") == scene.original.id


@pytest.mark.story("12.6", ac=2)
def test_a_replacement_changes_nothing_on_the_event_or_other_bookings(coordinator_client, db):
    scene = make_scenario(db, event_status=EventStatus.CONFIRMED)
    other = make_booking(
        db,
        event_id=scene.event.id,
        venue_id=hall(db).id,
        starts_at=when(46, 2),
        ends_at=when(46, 8),
        status=BookingStatus.APPROVED,
        decided_by_id=Users.VENUE_STAFF.id,
        decided_at=datetime.now(UTC),
        hold_expires_at=when(44),
    )

    def snapshot():
        db.expire_all()
        event = db.get(Event, scene.event.id)
        booking = db.get(VenueBooking, other.id)
        return (
            (event.status, event.name, event.starts_at, event.ends_at, event.expected_attendance),
            (booking.status, booking.decided_at, booking.hold_expires_at, booking.venue_id),
        )

    before = snapshot()
    created(replace(coordinator_client, scene.original.id, scene.alternative))

    assert snapshot() == before


@pytest.mark.story("12.6", ac=2)
@pytest.mark.parametrize(
    "why,expected",
    [("held", 409), ("closure", 409), ("withdrawn", 409), ("closed_hours", 409), ("unknown", 404)],
)
def test_a_replacement_the_new_venue_cannot_take_changes_nothing(
    coordinator_client, db, why, expected
):
    """Every refusal a new request gets (12.1, 12.5) is a replacement's too, and nothing is
    written: the original stays as it was."""
    scene = make_scenario(db)
    venue = scene.alternative
    if why == "held":
        make_booking(
            db,
            event_id=make_event(db, status=EventStatus.PLANNING).id,
            venue_id=venue.id,
            starts_at=scene.starts_at,
            ends_at=scene.ends_at,
            status=BookingStatus.APPROVED,
        )
    elif why == "closure":
        make_unavailability(
            db,
            venue_id=venue.id,
            starts_at=scene.starts_at - timedelta(hours=2),
            ends_at=scene.ends_at + timedelta(hours=2),
        )
    elif why == "withdrawn":
        venue = hall(db, status="WITHDRAWN")
    elif why == "closed_hours":
        venue = make_venue(
            db, capacity=100, layouts={"CLASSROOM": None}, hours=(time(23, 0), time(23, 30))
        )

    target = uuid.uuid4() if why == "unknown" else venue.id
    response = coordinator_client.post(
        f"{BOOKINGS_PATH}/{scene.original.id}/replacements", json={"venue_id": str(target)}
    )

    assert response.status_code == expected, response.text
    assert [booking.id for booking in _bookings_of(db, scene.event)] == [scene.original.id]
    assert column(db, scene.original.id, "replaced_by_booking_id") is None


@pytest.mark.story("12.6", ac=2)
def test_a_replacement_is_audited_and_tells_venue_staff_it_is_a_replacement(coordinator_client, db):
    """The audit entry names the original; every active Venue Staff member is told, and the
    notice says what is being replaced (the inactive account is not told)."""
    scene = make_scenario(db)

    body = created(replace(coordinator_client, scene.original.id, scene.alternative))

    entry = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == uuid.UUID(body["id"]), AuditLog.action == "BOOKING_REQUESTED"
        )
    ).one()
    assert entry.details["replaces_booking_id"] == str(scene.original.id)
    told = notifications_of(db, Users.VENUE_STAFF.id, event_id=scene.event.id)
    assert [each.notification_type for each in told] == ["BOOKING_REQUESTED"]
    assert "replacement" in told[0].message.lower()
    assert scene.original_venue.name in told[0].message
    assert notifications_of(db, Users.INACTIVE.id, event_id=scene.event.id) == []


# --- AC4: until it is approved ------------------------------------------------------------------
@pytest.mark.story("12.6", ac=4)
def test_the_original_is_untouched_while_a_replacement_is_pending(coordinator_client, db):
    scene = make_scenario(db)
    before = (
        scene.original.status,
        scene.original.decided_by_id,
        scene.original.decided_at,
        scene.original.hold_expires_at,
        scene.original.venue_unavailable_marked_at,
    )

    created(replace(coordinator_client, scene.original.id, scene.alternative))

    db.expire_all()
    original = db.get(VenueBooking, scene.original.id)
    assert (
        original.status,
        original.decided_by_id,
        original.decided_at,
        original.hold_expires_at,
        original.venue_unavailable_marked_at,
    ) == before
    assert column(db, original.id, "replaced_by_booking_id") is None


@pytest.mark.story("12.6", ac=4)
def test_the_event_list_names_the_pending_replacement_on_the_original(coordinator_client, db):
    """What the page reads to say "Replacement requested: <venue>" on the original's card, and
    "Replaces <venue>" on the replacement's."""
    scene = make_scenario(db)
    body = created(replace(coordinator_client, scene.original.id, scene.alternative))

    listed = coordinator_client.get(f"{BOOKINGS_PATH}/for-event/{scene.event.id}").json()

    by_id = {entry["id"]: entry for entry in listed}
    original, replacement = by_id[str(scene.original.id)], by_id[body["id"]]
    assert original["pending_replacement_venue_name"] == scene.alternative.name
    assert original["replaced_by_venue_name"] is None
    assert replacement["replaces_venue_name"] == scene.original_venue.name
    assert replacement["pending_replacement_venue_name"] is None


# --- AC5: rejected or withdrawn -----------------------------------------------------------------
@pytest.mark.story("12.6", ac=5)
def test_a_rejected_replacement_leaves_the_original_marked_and_another_can_be_requested(
    login_as, db
):
    scene = make_scenario(db)
    first = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    rejected = login_as(Users.VENUE_STAFF).post(
        f"{BOOKINGS_PATH}/{first['id']}/reject", json={"decision_reason": "Booked for a tour."}
    )
    assert rejected.status_code == 200, rejected.text

    second = replace(login_as(Users.COORDINATOR), scene.original.id, hall(db))

    assert second.status_code == 201, second.text
    db.expire_all()
    original = db.get(VenueBooking, scene.original.id)
    assert original.status == BookingStatus.APPROVED
    assert original.venue_unavailable_mark is not None


@pytest.mark.story("12.6", ac=5)
def test_a_withdrawn_replacement_leaves_the_original_marked_and_another_can_be_requested(
    coordinator_client, db
):
    scene = make_scenario(db)
    first = created(replace(coordinator_client, scene.original.id, scene.alternative))
    withdrawn = coordinator_client.post(f"{BOOKINGS_PATH}/{first['id']}/withdraw")
    assert withdrawn.status_code == 200, withdrawn.text

    second = replace(coordinator_client, scene.original.id, hall(db))

    assert second.status_code == 201, second.text
    db.expire_all()
    original = db.get(VenueBooking, scene.original.id)
    assert original.status == BookingStatus.APPROVED
    assert original.venue_unavailable_mark is not None


# --- AC6: the unavailability ends first ---------------------------------------------------------
@pytest.mark.story("12.6", ac=6)
def test_a_replacement_is_refused_once_the_mark_has_cleared(login_as, db):
    scene = make_scenario(db)
    end_the_closure(login_as, scene)
    assert column(db, scene.original.id, "venue_unavailable_marked_at") is None

    response = replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative)

    assert response.status_code == 409, response.text
    assert "marked" in response.json()["detail"]
    assert [booking.id for booking in _bookings_of(db, scene.event)] == [scene.original.id]


@pytest.mark.story("12.6", ac=6)
def test_a_pending_replacement_can_still_be_withdrawn_after_the_mark_clears(login_as, db):
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    end_the_closure(login_as, scene)
    assert column(db, scene.original.id, "venue_unavailable_marked_at") is None

    withdrawn = login_as(Users.COORDINATOR).post(f"{BOOKINGS_PATH}/{body['id']}/withdraw")

    assert withdrawn.status_code == 200, withdrawn.text
    db.expire_all()
    assert db.get(VenueBooking, scene.original.id).status == BookingStatus.APPROVED


@pytest.mark.story("12.6", ac=6)
def test_a_replacement_raced_by_the_closure_ending_is_made_or_refused_whole(engine):
    """Real concurrent transactions, so this test commits and cleans up after itself. One session
    requests the replacement while another removes the closure that marks the original. Either
    the request runs first and the replacement stands, or the removal does and the request is
    refused as "no longer marked": no deadlock, no error, no half-written replacement."""
    with Session(engine) as session:
        scene = make_scenario(session)
        period = make_unavailability(
            session,
            venue_id=scene.original_venue.id,
            starts_at=scene.starts_at - timedelta(days=1),
            ends_at=scene.ends_at + timedelta(days=1),
        )
        session.commit()
        ids = (
            scene.original.id,
            scene.event.id,
            scene.original_venue.id,
            scene.alternative.id,
            period.id,
        )
    original_id, event_id, original_venue_id, alternative_id, period_id = ids
    start = threading.Barrier(2)

    def request() -> str:
        with Session(engine) as session:
            actor = session.get(User, Users.COORDINATOR.id)
            start.wait()
            try:
                original = service.get_booking_for_decision(session, original_id)
                service.request_replacement_booking(
                    session,
                    original,
                    booking_schemas.BookingReplacementIn(venue_id=alternative_id),
                    actor=actor,
                )
            except Exception as refusal:  # noqa: BLE001 - the outcome is asserted below
                session.rollback()
                return f"refused: {refusal}"
            return "created"

    def end_the_closure() -> str:
        with Session(engine) as session:
            actor = session.get(User, Users.VENUE_STAFF.id)
            start.wait()
            venue_service.remove_unavailability(
                session, original_venue_id, period_id, actor=actor, now=datetime.now(UTC)
            )
            session.commit()
            return "removed"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            requested = pool.submit(request)
            removed = pool.submit(end_the_closure)
            outcome, ended = requested.result(timeout=30), removed.result(timeout=30)

        assert ended == "removed"
        with Session(engine) as session:
            replacements = session.scalars(
                select(func.count())
                .select_from(VenueBooking)
                .where(VenueBooking.event_id == event_id, VenueBooking.id != original_id)
            ).one()
            mark = session.execute(
                text("SELECT venue_unavailable_marked_at FROM venue_bookings WHERE id = :id"),
                {"id": original_id},
            ).scalar_one()
        assert mark is None
        if outcome == "created":
            assert replacements == 1
        else:
            assert "no longer" in outcome
            assert replacements == 0
    finally:
        purge(
            engine,
            event_ids=[event_id],
            venue_ids=[original_venue_id, alternative_id],
            period_ids=[period_id],
        )


# --- AC7: no change request ---------------------------------------------------------------------
@pytest.mark.story("12.6", ac=7)
def test_a_replacement_needs_no_change_request(coordinator_client, db):
    scene = make_scenario(db)
    before = db.scalar(text("SELECT count(*) FROM event_change_requests"))

    created(replace(coordinator_client, scene.original.id, scene.alternative))

    assert db.scalar(text("SELECT count(*) FROM event_change_requests")) == before


@pytest.mark.story("12.6", ac=7)
def test_an_unsuitable_replacement_needs_a_justification_and_stores_it(coordinator_client, db):
    """Too small for the requirement: refused without a justification (11.1 AC7), allowed with one,
    which is stored - and still no change request is created."""
    scene = make_scenario(db)
    small = make_venue(db, capacity=10, layouts={"CLASSROOM": None})
    before = db.scalar(text("SELECT count(*) FROM event_change_requests"))

    refused = replace(coordinator_client, scene.original.id, small)
    allowed = replace(
        coordinator_client,
        scene.original.id,
        small,
        suitability_override_reason="The venue's partner room is free for the overflow.",
    )

    assert refused.status_code == 422, refused.text
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["suitability_override_reason"] == (
        "The venue's partner room is free for the overflow."
    )
    assert db.scalar(text("SELECT count(*) FROM event_change_requests")) == before


# --- AC8: a cancelled event ---------------------------------------------------------------------
@pytest.mark.story("12.6", ac=8)
def test_no_replacement_can_be_requested_on_a_cancelled_event(coordinator_client, db):
    """A stale mark on a booking of a cancelled event offers nothing: the event no longer takes
    a booking (12.1 AC1)."""
    scene = make_scenario(db, event_status=EventStatus.CANCELLED)

    response = replace(coordinator_client, scene.original.id, scene.alternative)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == service.EVENT_NOT_BOOKABLE_MESSAGE.format(
        status=EventStatus.CANCELLED
    )
    assert [booking.id for booking in _bookings_of(db, scene.event)] == [scene.original.id]


# --- AC9: who, and for which booking ------------------------------------------------------------
@pytest.mark.story("12.6", ac=9)
@pytest.mark.parametrize(
    "actor",
    [
        Users.COORDINATOR_2,
        Users.LEAD,
        Users.VENUE_STAFF,
        Users.ORGANISER,
        Users.ORGANISER_2,
        Users.ATTENDEE,
        Users.TECH_SUPPORT,
        Users.SAFETY_OFFICER,
    ],
    ids=lambda user: user.role.lower(),
)
def test_only_the_assigned_coordinator_can_request_a_replacement(login_as, db, actor: SeedUser):
    scene = make_scenario(db)

    response = replace(login_as(actor), scene.original.id, scene.alternative)

    assert response.status_code == 403, response.text
    assert [booking.id for booking in _bookings_of(db, scene.event)] == [scene.original.id]


@pytest.mark.story("12.6", ac=9)
def test_an_unassigned_coordinator_is_refused_before_the_bookings_state_is_read(login_as, db):
    """As for a withdrawal: asked of an unmarked booking, Carl is told he may not (403), not that
    the booking is unmarked (409), which would give its state away."""
    scene = make_scenario(db, marked=False)

    response = replace(login_as(Users.COORDINATOR_2), scene.original.id, scene.alternative)

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == service.REPLACEMENT_NOT_ASSIGNED_COORDINATOR_MESSAGE


@pytest.mark.story("12.6", ac=9)
def test_a_signed_out_request_is_refused(client, db):
    scene = make_scenario(db)

    response = replace(client, scene.original.id, scene.alternative)

    assert response.status_code == 401


@pytest.mark.story("12.6", ac=9)
def test_an_unknown_original_is_not_found(coordinator_client, db):
    scene = make_scenario(db)

    response = replace(coordinator_client, uuid.uuid4(), scene.alternative)

    assert response.status_code == 404
    assert response.json()["detail"] == "Booking request not found."


@pytest.mark.story("12.6", ac=9)
def test_a_marked_pending_booking_cannot_be_replaced(coordinator_client, db):
    """12.5's Switch is the way for a pending request: the refusal says so."""
    scene = make_scenario(db, status=BookingStatus.PENDING)

    response = replace(coordinator_client, scene.original.id, scene.alternative)

    assert response.status_code == 409, response.text
    assert "Switch" in response.json()["detail"]
    assert [booking.id for booking in _bookings_of(db, scene.event)] == [scene.original.id]


@pytest.mark.story("12.6", ac=9)
def test_an_unmarked_approved_booking_cannot_be_replaced(coordinator_client, db):
    scene = make_scenario(db, marked=False)

    response = replace(coordinator_client, scene.original.id, scene.alternative)

    assert response.status_code == 409, response.text
    assert "marked" in response.json()["detail"]
    assert [booking.id for booking in _bookings_of(db, scene.event)] == [scene.original.id]


@pytest.mark.story("12.6", ac=9)
@pytest.mark.parametrize(
    "status",
    [
        BookingStatus.REJECTED,
        BookingStatus.WITHDRAWN,
        BookingStatus.CANCELLED,
        BookingStatus.EXPIRED,
    ],
)
def test_a_closed_booking_cannot_be_replaced(coordinator_client, db, status):
    """A mark left on a booking that no longer holds its venue is history (9.4): it is not
    one to replace."""
    scene = make_scenario(db, status=status)

    response = replace(coordinator_client, scene.original.id, scene.alternative)

    assert response.status_code == 409, response.text
    assert status in response.json()["detail"]
    assert [booking.id for booking in _bookings_of(db, scene.event)] == [scene.original.id]


@pytest.mark.story("12.6", ac=9)
def test_a_reassigned_coordinator_can_withdraw_the_pending_replacement(login_as, db):
    """The assignment is read as it stands: once Carl holds the event he, not Chloe, withdraws
    the replacement Chloe asked for."""
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    scene.event.assigned_coordinator_id = Users.COORDINATOR_2.id
    db.flush()

    chloe = login_as(Users.COORDINATOR).post(f"{BOOKINGS_PATH}/{body['id']}/withdraw")
    carl = login_as(Users.COORDINATOR_2).post(f"{BOOKINGS_PATH}/{body['id']}/withdraw")

    assert chloe.status_code == 403
    assert carl.status_code == 200, carl.text


# --- AC10: one pending replacement; never the original's own venue ------------------------------
@pytest.mark.story("12.6", ac=10)
def test_a_second_pending_replacement_is_refused_naming_the_venue_already_requested(
    coordinator_client, db
):
    scene = make_scenario(db)
    created(replace(coordinator_client, scene.original.id, scene.alternative))

    response = replace(coordinator_client, scene.original.id, hall(db))

    assert response.status_code == 409, response.text
    assert scene.alternative.name in response.json()["detail"]
    assert len(_bookings_of(db, scene.event)) == 2


@pytest.mark.story("12.6", ac=10)
def test_after_withdrawing_the_first_another_replacement_is_allowed(coordinator_client, db):
    scene = make_scenario(db)
    first = created(replace(coordinator_client, scene.original.id, scene.alternative))
    assert coordinator_client.post(f"{BOOKINGS_PATH}/{first['id']}/withdraw").status_code == 200

    second = replace(coordinator_client, scene.original.id, hall(db))

    assert second.status_code == 201, second.text


@pytest.mark.story("12.6", ac=10)
def test_a_replacement_at_the_originals_own_venue_is_refused(coordinator_client, db):
    """Refused for what it is, in a sentence of its own - not as the venue being held by the very
    booking it would replace."""
    scene = make_scenario(db)

    response = replace(coordinator_client, scene.original.id, scene.original_venue)

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "replacement" in detail.lower()
    assert scene.original_venue.name in detail
    assert "already" not in detail
    assert [booking.id for booking in _bookings_of(db, scene.event)] == [scene.original.id]


@pytest.mark.story("12.6", ac=10)
def test_two_replacements_sent_at_once_make_one(engine):
    """Real concurrent transactions, so this test commits and cleans up after itself. Two tabs
    send a replacement for one original to two different venues at the same moment: one is
    written, the other is refused as one already pending."""
    with Session(engine) as session:
        scene = make_scenario(session)
        extra = hall(session)
        session.commit()
        original_id, event_id = scene.original.id, scene.event.id
        venue_ids = [scene.alternative.id, extra.id]
        venue_names = [scene.alternative.name, extra.name]
        all_venue_ids = [scene.original_venue.id, *venue_ids]
    start = threading.Barrier(2)

    def attempt(venue_id: uuid.UUID) -> str:
        with Session(engine) as session:
            actor = session.get(User, Users.COORDINATOR.id)
            start.wait()
            try:
                original = service.get_booking_for_decision(session, original_id)
                service.request_replacement_booking(
                    session,
                    original,
                    booking_schemas.BookingReplacementIn(venue_id=venue_id),
                    actor=actor,
                )
            except Exception as refusal:  # noqa: BLE001 - the outcome is asserted below
                session.rollback()
                return f"refused: {refusal}"
            return "created"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt, venue_id) for venue_id in venue_ids]
            outcomes = sorted(future.result(timeout=30) for future in futures)

        assert outcomes[0] == "created"
        # Refused as the database's index refuses it, naming the venue the other tab asked for.
        assert outcomes[1] in {
            "refused: " + service.REPLACEMENT_ALREADY_PENDING_MESSAGE.format(venue=name)
            for name in venue_names
        }
        with Session(engine) as session:
            count = session.scalars(
                select(func.count())
                .select_from(VenueBooking)
                .where(VenueBooking.event_id == event_id)
            ).one()
        assert count == 2
    finally:
        purge(engine, event_ids=[event_id], venue_ids=all_venue_ids)


@pytest.mark.story("12.6", ac=10)
def test_a_normal_second_request_is_still_refused_while_a_replacement_is_pending(
    coordinator_client, db
):
    """The index carve-out is for the replacement alone: a normal request for the requirement is
    refused as 12.5 refuses it, naming the venue the original holds."""
    scene = make_scenario(db)
    add_pending_replacement(db, scene)

    response = coordinator_client.post(
        BOOKINGS_PATH,
        json={
            "event_id": str(scene.event.id),
            "venue_id": str(hall(db).id),
            "venue_requirement_id": str(scene.requirement_id),
        },
    )

    assert response.status_code == 409, response.text
    assert scene.original_venue.name in response.json()["detail"]


@pytest.mark.story("12.6", ac=10)
def test_an_approved_replacement_covers_the_requirement_so_a_normal_request_is_refused(
    login_as, db
):
    """Only a PENDING replacement is left out of the one-per-requirement rule: once approved it
    is the requirement's live booking, and the original is released."""
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    assert approve(login_as(Users.VENUE_STAFF), body["id"]).status_code == 200

    response = login_as(Users.COORDINATOR).post(
        BOOKINGS_PATH,
        json={
            "event_id": str(scene.event.id),
            "venue_id": str(hall(db).id),
            "venue_requirement_id": str(scene.requirement_id),
        },
    )

    assert response.status_code == 409, response.text
    assert scene.alternative.name in response.json()["detail"]


@pytest.mark.story("12.6", ac=10)
@pytest.mark.parametrize("closed_as", [BookingStatus.EXPIRED, BookingStatus.CANCELLED])
def test_after_the_original_closes_a_normal_request_is_refused_and_approving_does_not_error(
    login_as, db, closed_as
):
    """The carve-out ends with the original: once it expires or is cancelled by any path, the
    pending replacement is the requirement's request. A normal request is refused (not allowed in
    beside it), and approving the replacement is a plain approval - not a unique-index failure."""
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    set_status(db, scene.original.id, closed_as)

    normal = login_as(Users.COORDINATOR).post(
        BOOKINGS_PATH,
        json={
            "event_id": str(scene.event.id),
            "venue_id": str(hall(db).id),
            "venue_requirement_id": str(scene.requirement_id),
        },
    )
    approved = approve(login_as(Users.VENUE_STAFF), body["id"])

    assert normal.status_code == 409, normal.text
    assert scene.alternative.name in normal.json()["detail"]
    assert approved.status_code == 200, approved.text


@pytest.mark.story("12.6", ac=10)
def test_a_pending_replacement_cannot_be_switched_and_the_refusal_says_to_withdraw_it(
    coordinator_client, db
):
    """12.5's Switch would withdraw the replacement and ask for a normal request the original
    still blocks: it is refused first, saying what to do."""
    scene = make_scenario(db)
    body = created(replace(coordinator_client, scene.original.id, scene.alternative))

    response = coordinator_client.post(
        f"{BOOKINGS_PATH}/{body['id']}/switch", json={"venue_id": str(hall(db).id)}
    )

    assert response.status_code == 409, response.text
    assert "withdraw" in response.json()["detail"].lower()
    db.expire_all()
    assert db.get(VenueBooking, uuid.UUID(body["id"])).status == BookingStatus.PENDING
