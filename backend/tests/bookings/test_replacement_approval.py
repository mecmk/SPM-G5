"""Story 12.6 - request a replacement venue for an affected booking: approving the replacement.

AC3  When Venue Staff approve the replacement (13.2) the original is released - CANCELLED, with who
     approved it and when kept - in the same transaction, and records which booking replaced it.
     The event's booking list shows the original as "Replaced by <venue>" and the replacement as
     "Replaces <venue>"; the coordinator's approval notice says the original was released; the
     other Venue Staff are told; the organiser is not.
AC6  A replacement approved after the unavailability ended still replaces the original.
AC8  A replacement that was never approved is never shown as having replaced the original, even
     when both end up CANCELLED.
AC10 After the original closes by any path the pending replacement is the requirement's request:
     approving it then is a plain approval that releases nothing.

Raising the replacement is test_request_replacement.py.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings import schemas as booking_schemas
from app.bookings import service
from app.bookings.models import BookingStatus, VenueBooking, marked_booking_conditions
from app.common.audit import AuditLog
from tests.support.factories import make_unavailability, make_user
from tests.support.replacement import (
    BOOKINGS_PATH,
    add_pending_replacement,
    approve,
    column,
    created,
    end_the_closure,
    make_scenario,
    notifications_of,
    purge,
    replace,
    set_status,
)
from tests.support.seed import Users


def _outcome_of(db: Session, booking_id) -> VenueBooking:
    db.expire_all()
    return db.get(VenueBooking, booking_id)


def _listed(client, scene) -> dict:
    """The event's booking list, by booking id."""
    response = client.get(f"{BOOKINGS_PATH}/for-event/{scene.event.id}")
    assert response.status_code == 200, response.text
    return {entry["id"]: entry for entry in response.json()}


# --- AC3: the release -------------------------------------------------------------------------
@pytest.mark.story("12.6", ac=3)
def test_approving_a_replacement_cancels_the_original_in_one_transaction(login_as, db):
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    approved_by, approved_at = scene.original.decided_by_id, scene.original.decided_at

    response = approve(login_as(Users.VENUE_STAFF), body["id"])

    assert response.status_code == 200, response.text
    original = _outcome_of(db, scene.original.id)
    replacement = _outcome_of(db, uuid.UUID(body["id"]))
    assert replacement.status == BookingStatus.APPROVED
    assert original.status == BookingStatus.CANCELLED
    assert (original.decided_by_id, original.decided_at) == (approved_by, approved_at)
    assert original.decision_reason == f"Replaced by {scene.alternative.name}"
    assert column(db, original.id, "replaced_by_booking_id") == replacement.id
    assert (
        service.find_holding_booking(
            db, scene.original_venue.id, original.held_from, original.held_until
        )
        is None
    )


@pytest.mark.story("12.6", ac=3)
@pytest.mark.parametrize("why", ["expiry_in_the_past", "replacement_venue_closed"])
def test_a_refused_approval_leaves_the_original_approved(login_as, db, why):
    """The release is part of the approval, not a step before it: when the approval is refused the
    original is as it was and the replacement still pending."""
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    extra = {}
    if why == "expiry_in_the_past":
        extra = {"hold_expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}
    else:
        make_unavailability(
            db,
            venue_id=scene.alternative.id,
            starts_at=scene.starts_at - timedelta(hours=2),
            ends_at=scene.ends_at + timedelta(hours=2),
        )

    response = approve(login_as(Users.VENUE_STAFF), body["id"], **extra)

    assert response.status_code in (409, 422), response.text
    original = _outcome_of(db, scene.original.id)
    assert original.status == BookingStatus.APPROVED
    assert column(db, original.id, "replaced_by_booking_id") is None
    assert _outcome_of(db, uuid.UUID(body["id"])).status == BookingStatus.PENDING


@pytest.mark.story("12.6", ac=3)
def test_the_approval_notice_says_the_original_was_released(login_as, db):
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))

    approve(login_as(Users.VENUE_STAFF), body["id"])

    told = notifications_of(db, Users.COORDINATOR.id, event_id=scene.event.id)
    approval = [each for each in told if each.notification_type == "BOOKING_APPROVED"]
    assert len(approval) == 1
    assert (
        service.ORIGINAL_RELEASED_SENTENCE.format(venue=scene.original_venue.name)
        in approval[0].message
    )


@pytest.mark.story("12.6", ac=3)
def test_other_venue_staff_are_told_the_original_was_released_and_the_organiser_is_not(
    login_as, db
):
    colleague = make_user(db, role="VENUE_STAFF")
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    before = len(notifications_of(db, colleague.id, event_id=scene.event.id))

    approve(login_as(Users.VENUE_STAFF), body["id"])

    told = notifications_of(db, colleague.id, event_id=scene.event.id)[before:]
    assert len(told) == 1
    assert scene.original_venue.name in told[0].message
    assert "released" in told[0].message
    # The approver acted, so is not told (20.1 AC3); the inactive account and the organiser never.
    assert not [
        each
        for each in notifications_of(db, Users.VENUE_STAFF.id, event_id=scene.event.id)
        if "released" in each.message
    ]
    assert notifications_of(db, Users.INACTIVE.id, event_id=scene.event.id) == []
    assert notifications_of(db, scene.event.organiser_id, event_id=scene.event.id) == []


@pytest.mark.story("12.6", ac=3)
def test_the_release_is_audited(login_as, db):
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))

    approve(login_as(Users.VENUE_STAFF), body["id"])

    entry = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == scene.original.id, AuditLog.action == "BOOKING_REPLACED"
        )
    ).one()
    assert entry.actor_id == Users.VENUE_STAFF.id
    assert entry.details["replaced_by_booking_id"] == body["id"]
    assert entry.details["venue_id"] == str(scene.original_venue.id)


@pytest.mark.story("12.6", ac=3)
def test_a_reassigned_coordinator_is_told_of_the_approval(login_as, db):
    """The approval notice goes to whoever holds the event when Venue Staff decide (20.1 AC4)."""
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    scene.event.assigned_coordinator_id = Users.COORDINATOR_2.id
    db.flush()

    approve(login_as(Users.VENUE_STAFF), body["id"])

    carl = [
        each
        for each in notifications_of(db, Users.COORDINATOR_2.id, event_id=scene.event.id)
        if each.notification_type == "BOOKING_APPROVED"
    ]
    released_sentence = service.ORIGINAL_RELEASED_SENTENCE.format(venue=scene.original_venue.name)
    assert len(carl) == 1 and released_sentence in carl[0].message
    assert not [
        each
        for each in notifications_of(db, Users.COORDINATOR.id, event_id=scene.event.id)
        if each.notification_type == "BOOKING_APPROVED"
    ]


@pytest.mark.story("12.6", ac=3)
@pytest.mark.parametrize("state", ["pending", "rejected", "withdrawn", "approved"])
def test_the_event_list_shows_replaced_by_only_for_an_approved_replacement(login_as, db, state):
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    if state == "rejected":
        login_as(Users.VENUE_STAFF).post(
            f"{BOOKINGS_PATH}/{body['id']}/reject", json={"decision_reason": "Not free."}
        )
    elif state == "withdrawn":
        login_as(Users.COORDINATOR).post(f"{BOOKINGS_PATH}/{body['id']}/withdraw")
    elif state == "approved":
        assert approve(login_as(Users.VENUE_STAFF), body["id"]).status_code == 200

    listed = _listed(login_as(Users.COORDINATOR), scene)

    original, replacement = listed[str(scene.original.id)], listed[body["id"]]
    expected = scene.alternative.name if state == "approved" else None
    assert original["replaced_by_venue_name"] == expected
    assert replacement["replaces_venue_name"] == scene.original_venue.name


@pytest.mark.story("12.6", ac=3)
@pytest.mark.parametrize("later", [BookingStatus.EXPIRED, BookingStatus.CANCELLED])
def test_replaced_by_stays_once_an_approved_replacement_later_closes(login_as, db, later):
    """Which booking replaced the original is a fact of the approval: it does not depend on the
    replacement still being approved."""
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    assert approve(login_as(Users.VENUE_STAFF), body["id"]).status_code == 200
    set_status(db, uuid.UUID(body["id"]), later)

    listed = _listed(login_as(Users.COORDINATOR), scene)

    assert listed[str(scene.original.id)]["replaced_by_venue_name"] == scene.alternative.name


@pytest.mark.story("12.6", ac=3)
def test_two_approvals_at_once_release_the_original_once(engine):
    """Real concurrent transactions, so this test commits and cleans up after itself. Two Venue
    Staff approve the same replacement at the same moment: one approval is made and releases the
    original; the other finds it no longer pending."""
    with Session(engine) as session:
        scene = make_scenario(session)
        session.commit()
        original_id, event_id = scene.original.id, scene.event.id
        venue_ids = [scene.original_venue.id, scene.alternative.id]
        alternative_id = scene.alternative.id
    start = threading.Barrier(2)

    def approve_it(replacement_id) -> str:
        with Session(engine) as session:
            start.wait()
            booking = service.get_booking_for_approval(session, replacement_id)
            try:
                service.approve_booking(
                    session,
                    booking,
                    actor_id=Users.VENUE_STAFF.id,
                    hold_expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            except service.BookingNotPending:
                return "refused"
            return "approved"

    try:
        with Session(engine) as session:
            actor = session.get(User, Users.COORDINATOR.id)
            original = service.get_booking_for_decision(session, original_id)
            replacement = service.request_replacement_booking(
                session,
                original,
                booking_schemas.BookingReplacementIn(venue_id=alternative_id),
                actor=actor,
            )
            replacement_id = replacement.id
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(approve_it, replacement_id) for _ in range(2)]
            outcomes = sorted(future.result(timeout=30) for future in futures)

        assert outcomes == ["approved", "refused"]
        with Session(engine) as session:
            assert session.get(VenueBooking, original_id).status == BookingStatus.CANCELLED
            released = session.scalars(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.entity_id == original_id, AuditLog.action == "BOOKING_REPLACED")
            ).one()
        assert released == 1
    finally:
        purge(engine, event_ids=[event_id], venue_ids=venue_ids)


@pytest.mark.story("12.6", ac=3)
def test_a_released_original_carries_the_time_it_was_released(login_as, db):
    """ "Closed at" on the event page is when the replacement was approved, not the original's own
    approval, which its decided_at still is: the outcome carries the release time, derived from
    the replacement that released it, and only for an original that was released."""
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    before = _listed(login_as(Users.COORDINATOR), scene)
    assert before[str(scene.original.id)]["released_at"] is None

    assert approve(login_as(Users.VENUE_STAFF), body["id"]).status_code == 200

    listed = _listed(login_as(Users.COORDINATOR), scene)
    original, replacement = listed[str(scene.original.id)], listed[body["id"]]
    assert original["released_at"] == replacement["decided_at"]
    assert original["released_at"] != original["decided_at"]
    assert replacement["released_at"] is None


@pytest.mark.story("12.6", ac=3)
def test_an_additional_venues_replacement_releases_its_original_when_approved(login_as, db):
    """A replacement for a booking that is for no requirement is released the same way: the
    original is CANCELLED and linked, so it leaves the Venue unavailable tab and stops blocking the
    safety review - the one-per-requirement index never comes into it."""
    scene = make_scenario(db, additional=True)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))

    assert approve(login_as(Users.VENUE_STAFF), body["id"]).status_code == 200

    original = _outcome_of(db, scene.original.id)
    assert original.status == BookingStatus.CANCELLED
    assert original.decision_reason == service.REPLACED_BY_REASON.format(
        venue=scene.alternative.name
    )
    assert str(column(db, original.id, "replaced_by_booking_id")) == body["id"]
    assert _outcome_of(db, uuid.UUID(body["id"])).status == BookingStatus.APPROVED
    db.expire_all()
    assert (
        db.scalar(
            select(func.count())
            .select_from(VenueBooking)
            .where(VenueBooking.event_id == scene.event.id, *marked_booking_conditions())
        )
        == 0
    )


@pytest.mark.story("12.6", ac=3)
def test_an_approval_locks_the_original_before_the_replacement(login_as, db):
    """Everything that closes the original (the sweep, 19.2's release) locks it first and the
    trigger then updates the replacement, so an approval taking the two in the other order could
    deadlock with them. ``get_booking_for_approval`` locks the original, then the replacement."""
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    replacement_id = uuid.UUID(body["id"])
    locked: list[list[uuid.UUID]] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE" in statement and "venue_bookings" in statement:
            values = parameters.values() if isinstance(parameters, dict) else parameters
            locked.append([value for value in values if isinstance(value, uuid.UUID)])

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", record)
    try:
        service.get_booking_for_approval(db, replacement_id)
    finally:
        event.remove(connection, "before_cursor_execute", record)

    assert locked == [[scene.original.id], [replacement_id]]


# --- AC6: approved after the unavailability ended ------------------------------------------------
@pytest.mark.story("12.6", ac=6)
def test_approving_a_replacement_after_the_mark_cleared_still_replaces_the_original(login_as, db):
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    end_the_closure(login_as, scene)
    assert column(db, scene.original.id, "venue_unavailable_marked_at") is None

    response = approve(login_as(Users.VENUE_STAFF), body["id"])

    assert response.status_code == 200, response.text
    assert _outcome_of(db, scene.original.id).status == BookingStatus.CANCELLED
    assert str(column(db, scene.original.id, "replaced_by_booking_id")) == body["id"]


# --- AC8: never approved, never "replaced" -------------------------------------------------------
@pytest.mark.story("12.6", ac=8)
def test_a_never_approved_replacement_is_not_shown_as_replacing_when_both_are_cancelled(
    login_as, db
):
    """The event is cancelled and both bookings end CANCELLED, as a cancellation would leave
    them. The replacement was never approved, so nothing says the original was replaced."""
    scene = make_scenario(db)
    replacement = add_pending_replacement(db, scene)
    set_status(db, scene.original.id, BookingStatus.CANCELLED)
    set_status(db, replacement.id, BookingStatus.CANCELLED)

    listed = _listed(login_as(Users.COORDINATOR), scene)

    assert listed[str(scene.original.id)]["replaced_by_venue_name"] is None
    assert listed[str(replacement.id)]["replaces_venue_name"] == scene.original_venue.name


# --- AC10: the original closed first ------------------------------------------------------------
@pytest.mark.story("12.6", ac=10)
@pytest.mark.parametrize("closed_as", [BookingStatus.EXPIRED, BookingStatus.CANCELLED])
def test_approving_a_replacement_whose_original_is_already_closed_approves_alone(
    login_as, db, closed_as
):
    """The original lapsed (12.7) or was cancelled by another path while the replacement waited:
    the approval is the replacement's alone. Nothing is released, nothing says it was, and Venue
    Staff are told of no release."""
    colleague = make_user(db, role="VENUE_STAFF")
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    set_status(db, scene.original.id, closed_as)
    reason_before = _outcome_of(db, scene.original.id).decision_reason
    before = len(notifications_of(db, colleague.id, event_id=scene.event.id))

    response = approve(login_as(Users.VENUE_STAFF), body["id"])

    assert response.status_code == 200, response.text
    assert response.json()["status"] == BookingStatus.APPROVED
    original = _outcome_of(db, scene.original.id)
    assert original.status == closed_as
    assert original.decision_reason == reason_before
    assert column(db, scene.original.id, "replaced_by_booking_id") is None
    told = notifications_of(db, Users.COORDINATOR.id, event_id=scene.event.id)
    approval = [each for each in told if each.notification_type == "BOOKING_APPROVED"]
    # Not the word "released": 12.7's hold sentence in every approval notice has it. The sentence
    # that says the original was released is the one that must be absent.
    release_sentence = service.ORIGINAL_RELEASED_SENTENCE.format(venue=scene.original_venue.name)
    assert len(approval) == 1 and release_sentence not in approval[0].message
    assert not [
        each
        for each in notifications_of(db, colleague.id, event_id=scene.event.id)[before:]
        if "released" in each.message
    ]
    assert not db.scalars(
        select(AuditLog).where(
            AuditLog.entity_id == scene.original.id, AuditLog.action == "BOOKING_REPLACED"
        )
    ).all()
