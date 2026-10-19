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

This file is a replacement and an approved change request (story 19.2) meeting. Both stories
release a booking, through the one ``release_booking``: 19.2 when an approved change to the event no
longer fits it, 12.6 when the replacement that is approved takes its place. A replacement carries
its original's requirement, period, layout and attendance, so f7.2.4's fit rule (which 19.2 applies
to the event's pending and approved bookings alike) judges the two together:

* a change that unfits a flagged original unfits its pending replacement as well, so both are
  released by 19.2 - the original with no "Replaced by", since no replacement approved took its
  place - and the requirement needs a venue again (AC3, AC10);
* a release of the original alone (here through ``release_booking`` itself - the fit rule never
  separates the two, but a rejection or the sweep can close one meanwhile) leaves the pending
  replacement covering the requirement, a normal request refused beside it, and its approval
  working, with nothing left to release (AC3, AC10).

The release's own rules are test_replacement_approval.py (12.6) and test_decide_change_request.py
(19.2); the database's guards are test_replacement_schema.py.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, object_session

from app.auth.models import User
from app.bookings import service
from app.bookings.models import BookingStatus, VenueBooking
from app.change_requests.models import EventChangeRequest
from tests.support.factories import make_venue
from tests.support.replacement import (
    BOOKINGS_PATH,
    approve,
    column,
    created,
    hall,
    make_scenario,
    notifications_of,
    replace,
)
from tests.support.seed import Users


def _raise_attendance(login_as, db: Session, event, attendance: int) -> EventChangeRequest:
    """Olivia asks, through 19.1's own endpoint, for the event to take ``attendance`` people."""
    response = login_as(Users.ORGANISER).post(
        f"/events/{event.id}/change-requests",
        json={"field": "expected_attendance", "proposed": attendance, "reason": "More are coming."},
    )
    assert response.status_code == 201, response.text
    return db.get(EventChangeRequest, uuid.UUID(response.json()["id"]))


def _approve_change(client, request: EventChangeRequest):
    """Approve ``request`` as the assigned coordinator, the test's rows committed first as
    test_decide_change_request.py does, so a refusal's rollback cannot undo them."""
    object_session(request).commit()
    return client.post(f"/events/{request.event_id}/change-requests/{request.id}/approve")


def _booking(db: Session, booking_id: uuid.UUID) -> VenueBooking:
    db.expire_all()
    return db.get(VenueBooking, booking_id)


@pytest.mark.story("12.6", ac=3)
def test_a_change_that_unfits_a_flagged_original_releases_its_pending_replacement_too(login_as, db):
    """The event's attendance outgrows an additional venue's booking: the original and the
    replacement requested for it were booked for the same people, so both go, as 19.2 releases any
    booking it unfits. Neither is "Replaced by" anything, and the audit and Venue Staff's notices
    are 19.2's."""
    scene = make_scenario(db, additional=True)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    request = _raise_attendance(login_as, db, scene.event, 80)

    approval = _approve_change(login_as(Users.COORDINATOR), request)

    assert approval.status_code == 200, approval.text
    original, replacement = _booking(db, scene.original.id), _booking(db, uuid.UUID(body["id"]))
    assert (original.status, replacement.status) == (
        BookingStatus.CANCELLED,
        BookingStatus.CANCELLED,
    )
    # No replacement was approved, so nothing says one replaced the original.
    assert column(db, original.id, "replaced_by_booking_id") is None
    assert original.decision_reason is None
    listed = login_as(Users.COORDINATOR).get(f"{BOOKINGS_PATH}/for-event/{scene.event.id}").json()
    assert {entry["id"]: entry["replaced_by_venue_name"] for entry in listed} == {
        str(original.id): None,
        str(replacement.id): None,
    }
    audited = db.execute(
        text(
            "SELECT entity_id, action FROM audit_log WHERE entity_type = 'venue_booking'"
            " AND action IN ('BOOKING_RELEASED', 'BOOKING_REPLACED')"
            " AND entity_id IN (:original, :replacement)"
        ),
        {"original": original.id, "replacement": replacement.id},
    ).all()
    assert {(row.entity_id, row.action) for row in audited} == {
        (original.id, "BOOKING_RELEASED"),
        (replacement.id, "BOOKING_RELEASED"),
    }
    notices = notifications_of(db, Users.VENUE_STAFF.id, event_id=scene.event.id)
    released = [notice for notice in notices if notice.notification_type == "BOOKING_RELEASED"]
    assert {notice.related_entity_id for notice in released} == {original.id, replacement.id}
    assert not [notice for notice in notices if notice.notification_type == "BOOKING_REPLACED"]


def _raise_requirement_layout(login_as, db: Session, scene, layout_code: str) -> EventChangeRequest:
    """Olivia asks, through 19.1's own endpoint, for the event's one venue requirement to be laid
    out as ``layout_code``: a change the original's booking, and the replacement beside it, no
    longer fit (f7.2.4: the requirement asks for another layout than they were requested for)."""
    proposed = [
        {
            "id": str(scene.requirement_id),
            "name": "Main hall",
            "capacity": 40,
            "starts_at": scene.starts_at.isoformat(),
            "ends_at": scene.ends_at.isoformat(),
            "layout_code": layout_code,
            "facilities": [],
            "notes": None,
        }
    ]
    response = login_as(Users.ORGANISER).post(
        f"/events/{scene.event.id}/change-requests",
        json={"field": "venue_requirements", "proposed": proposed, "reason": "More are coming."},
    )
    assert response.status_code == 201, response.text
    return db.get(EventChangeRequest, uuid.UUID(response.json()["id"]))


@pytest.mark.story("12.6", ac=10)
def test_a_requirement_needs_a_venue_again_once_the_change_released_both(login_as, db):
    """The requirement is laid out another way, so 19.2 releases the original and the replacement
    asked for it. With neither left the requirement is uncovered, and a normal request for a venue
    is taken as 12.5 takes it for any requirement that needs one - the one-per-requirement index
    sees no live booking, and the replacement's carve-out is gone with it."""
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    request = _raise_requirement_layout(login_as, db, scene, "THEATRE")
    assert _approve_change(login_as(Users.COORDINATOR), request).status_code == 200
    assert _booking(db, scene.original.id).status == BookingStatus.CANCELLED
    assert _booking(db, uuid.UUID(body["id"])).status == BookingStatus.CANCELLED

    again = login_as(Users.COORDINATOR).post(
        BOOKINGS_PATH,
        json={
            "event_id": str(scene.event.id),
            "venue_id": str(make_venue(db, capacity=100, layouts={"THEATRE": None}).id),
            "venue_requirement_id": str(scene.requirement_id),
        },
    )

    assert again.status_code == 201, again.text


@pytest.mark.story("12.6", ac=10)
def test_an_original_released_alone_leaves_its_pending_replacement_covering_the_requirement(
    login_as, db
):
    """The original is closed with no replacement approved (here by ``release_booking``, as 19.2
    does): the replacement's carve-out ends with it, so the requirement is covered by the
    replacement and a normal request is refused, naming it; the original is not "Replaced by"."""
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    replacement_id = uuid.UUID(body["id"])
    assert column(db, replacement_id, "replaces_live_original") is True

    chloe = db.get(User, Users.COORDINATOR.id)
    assert service.release_booking(
        db, _booking(db, scene.original.id), actor=chloe, change="expected attendance"
    )
    db.flush()

    original = _booking(db, scene.original.id)
    assert original.status == BookingStatus.CANCELLED
    assert column(db, original.id, "replaced_by_booking_id") is None
    assert _booking(db, replacement_id).status == BookingStatus.PENDING
    assert column(db, replacement_id, "replaces_live_original") is False
    refused = login_as(Users.COORDINATOR).post(
        BOOKINGS_PATH,
        json={
            "event_id": str(scene.event.id),
            "venue_id": str(hall(db).id),
            "venue_requirement_id": str(scene.requirement_id),
        },
    )
    assert refused.status_code == 409, refused.text
    assert scene.alternative.name in refused.json()["detail"]


@pytest.mark.story("12.6", ac=3)
def test_approving_the_replacement_of_an_original_released_by_a_change_still_works(login_as, db):
    """Nothing is left to release, so the approval releases nothing and says so: the coordinator's
    notice has no "it replaces was released" sentence, the original keeps what 19.2 left, and no
    "replaced" notice or audit exists."""
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    chloe = db.get(User, Users.COORDINATOR.id)
    assert service.release_booking(
        db, _booking(db, scene.original.id), actor=chloe, change="expected attendance"
    )
    db.flush()

    approval = approve(login_as(Users.VENUE_STAFF), body["id"])

    assert approval.status_code == 200, approval.text
    assert _booking(db, uuid.UUID(body["id"])).status == BookingStatus.APPROVED
    original = _booking(db, scene.original.id)
    assert original.status == BookingStatus.CANCELLED
    assert original.decision_reason is None
    assert column(db, original.id, "replaced_by_booking_id") is None
    [approved] = [
        notice
        for notice in notifications_of(db, Users.COORDINATOR.id, event_id=scene.event.id)
        if notice.notification_type == "BOOKING_APPROVED"
    ]
    assert service.ORIGINAL_RELEASED_SENTENCE.format(venue=scene.original_venue.name) not in (
        approved.message
    )
    assert not [
        notice
        for notice in notifications_of(db, Users.VENUE_STAFF.id, event_id=scene.event.id)
        if notice.notification_type == "BOOKING_REPLACED"
    ]
    replaced_audit = db.execute(
        text("SELECT 1 FROM audit_log WHERE action = 'BOOKING_REPLACED' AND entity_id = :id"),
        {"id": original.id},
    ).all()
    assert replaced_audit == []
