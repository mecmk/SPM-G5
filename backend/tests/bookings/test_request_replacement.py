"""Story 12.6 - Request a replacement venue for an affected booking

Retired by 9.5 (CL-193, 1 Nov 2026), kept as history: a venue closure now ends the bookings it
covers, so nothing is marked and no replacement is requested. A booking already replaced still
shows "Replaced by <venue>" (9.5 AC7), and a request raised as a replacement before 9.5 becomes a
normal pending request once its original closes (9.5 AC8, CL-194).

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

import uuid

import pytest

from app.bookings.models import BookingStatus, VenueBooking
from tests.support.replacement import (
    BOOKINGS_PATH,
    add_pending_replacement,
    approve,
    column,
    end_the_closure,
    hall,
    make_scenario,
    request_replacement,
    set_status,
)
from tests.support.seed import Users

# --- AC2: the replacement is raised pending and linked ------------------------------------------


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

    request_replacement(db, scene)

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
    body = request_replacement(db, scene)

    listed = coordinator_client.get(f"{BOOKINGS_PATH}/for-event/{scene.event.id}").json()

    by_id = {entry["id"]: entry for entry in listed}
    original, replacement = by_id[str(scene.original.id)], by_id[body["id"]]
    assert original["pending_replacement_venue_name"] == scene.alternative.name
    assert original["replaced_by_venue_name"] is None
    assert replacement["replaces_venue_name"] == scene.original_venue.name
    assert replacement["pending_replacement_venue_name"] is None


# --- AC5: rejected or withdrawn -----------------------------------------------------------------


# --- AC6: the unavailability ends first ---------------------------------------------------------


@pytest.mark.story("12.6", ac=6)
def test_a_pending_replacement_can_still_be_withdrawn_after_the_mark_clears(login_as, db):
    scene = make_scenario(db)
    body = request_replacement(db, scene)
    end_the_closure(login_as, scene)
    assert column(db, scene.original.id, "venue_unavailable_marked_at") is None

    withdrawn = login_as(Users.COORDINATOR).post(f"{BOOKINGS_PATH}/{body['id']}/withdraw")

    assert withdrawn.status_code == 200, withdrawn.text
    db.expire_all()
    assert db.get(VenueBooking, scene.original.id).status == BookingStatus.APPROVED


# --- AC7: no change request ---------------------------------------------------------------------


# --- AC8: a cancelled event ---------------------------------------------------------------------


# --- AC9: who, and for which booking ------------------------------------------------------------


@pytest.mark.story("12.6", ac=9)
def test_a_reassigned_coordinator_can_withdraw_the_pending_replacement(login_as, db):
    """The assignment is read as it stands: once Carl holds the event he, not Chloe, withdraws
    the replacement Chloe asked for."""
    scene = make_scenario(db)
    body = request_replacement(db, scene)
    scene.event.assigned_coordinator_id = Users.COORDINATOR_2.id
    db.flush()

    chloe = login_as(Users.COORDINATOR).post(f"{BOOKINGS_PATH}/{body['id']}/withdraw")
    carl = login_as(Users.COORDINATOR_2).post(f"{BOOKINGS_PATH}/{body['id']}/withdraw")

    assert chloe.status_code == 403
    assert carl.status_code == 200, carl.text


# --- AC10: one pending replacement; never the original's own venue ------------------------------


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
    body = request_replacement(db, scene)
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


@pytest.mark.story("9.5", ac=8)
@pytest.mark.parametrize("closed_as", [BookingStatus.EXPIRED, BookingStatus.CANCELLED])
def test_after_the_original_closes_a_normal_request_is_refused_and_approving_does_not_error(
    login_as, db, closed_as
):
    """The carve-out ends with the original: once it expires or is cancelled by any path - a
    venue closure (9.5) among them - the pending replacement is the requirement's request and no
    longer reads as a replacement (CL-194 (8)). A normal request is refused (not allowed in
    beside it), and approving the replacement is a plain approval - not a unique-index failure."""
    scene = make_scenario(db)
    body = request_replacement(db, scene)
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
    assert column(db, uuid.UUID(body["id"]), "replaces_booking_id") is None


@pytest.mark.story("9.5", ac=8)
@pytest.mark.parametrize("closed_as", [BookingStatus.EXPIRED, BookingStatus.CANCELLED])
def test_after_the_original_closes_the_leftover_request_can_be_switched(login_as, db, closed_as):
    """CL-194 (8), 12.5: with its link gone the leftover request is an ordinary pending request,
    so the coordinator can switch it to another venue, which withdraws it."""
    scene = make_scenario(db)
    body = request_replacement(db, scene)
    set_status(db, scene.original.id, closed_as)

    switched = login_as(Users.COORDINATOR).post(
        f"{BOOKINGS_PATH}/{body['id']}/switch", json={"venue_id": str(hall(db).id)}
    )

    assert switched.status_code in (200, 201), switched.text
    db.expire_all()
    assert db.get(VenueBooking, uuid.UUID(body["id"])).status == BookingStatus.WITHDRAWN


@pytest.mark.story("12.6", ac=10)
def test_a_pending_replacement_cannot_be_switched_and_the_refusal_says_to_withdraw_it(
    coordinator_client, db
):
    """12.5's Switch would withdraw the replacement and ask for a normal request the original
    still blocks: it is refused first, saying what to do."""
    scene = make_scenario(db)
    body = request_replacement(db, scene)

    response = coordinator_client.post(
        f"{BOOKINGS_PATH}/{body['id']}/switch", json={"venue_id": str(hall(db).id)}
    )

    assert response.status_code == 409, response.text
    assert "withdraw" in response.json()["detail"].lower()
    db.expire_all()
    assert db.get(VenueBooking, uuid.UUID(body["id"])).status == BookingStatus.PENDING
