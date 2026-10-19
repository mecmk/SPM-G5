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

This file is what Venue Staff are shown before they approve (AC3, and AC6 where the original is no
longer marked): the queue card and the request's own page say which venue it replaces, which venue
approving it will release - only while that booking still holds its venue - and whether the original
is still marked. The queue also carries the time a released original was released. The approval
itself is test_replacement_approval.py.
"""

from __future__ import annotations

import uuid

import pytest

from app.bookings.models import BookingStatus
from tests.support.replacement import (
    BOOKINGS_PATH,
    add_pending_replacement,
    approve,
    created,
    end_the_closure,
    make_scenario,
    replace,
    set_status,
)
from tests.support.seed import Users

FIELDS = ("replaces_venue_name", "approval_releases_venue_name", "original_is_marked")


def _queue_entry(client, booking_id: uuid.UUID) -> dict:
    response = client.get(BOOKINGS_PATH, params={"status": "PENDING"})
    assert response.status_code == 200, response.text
    return next(entry for entry in response.json()["items"] if entry["id"] == str(booking_id))


def _detail(client, booking_id: uuid.UUID) -> dict:
    response = client.get(f"{BOOKINGS_PATH}/{booking_id}")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.story("12.6", ac=3)
def test_the_queue_card_says_which_venue_it_replaces_and_will_release(venue_staff_client, db):
    scene = make_scenario(db)
    replacement = add_pending_replacement(db, scene)

    entry = _queue_entry(venue_staff_client, replacement.id)

    assert entry["replaces_venue_name"] == scene.original_venue.name
    assert entry["approval_releases_venue_name"] == scene.original_venue.name
    assert entry["original_is_marked"] is True


@pytest.mark.story("12.6", ac=3)
def test_the_request_page_says_which_venue_it_replaces_and_will_release(venue_staff_client, db):
    scene = make_scenario(db)
    replacement = add_pending_replacement(db, scene)

    body = _detail(venue_staff_client, replacement.id)

    assert body["replaces_venue_name"] == scene.original_venue.name
    assert body["approval_releases_venue_name"] == scene.original_venue.name
    assert body["original_is_marked"] is True


@pytest.mark.story("12.6", ac=3)
@pytest.mark.parametrize("closed_as", [BookingStatus.EXPIRED, BookingStatus.CANCELLED])
def test_approving_releases_nothing_once_the_original_has_closed(venue_staff_client, db, closed_as):
    """Still a replacement - the card says what it replaces - but approving it releases nothing,
    so the warning is not shown."""
    scene = make_scenario(db)
    replacement = add_pending_replacement(db, scene)
    set_status(db, scene.original.id, closed_as)

    entry = _queue_entry(venue_staff_client, replacement.id)

    assert entry["replaces_venue_name"] == scene.original_venue.name
    assert entry["approval_releases_venue_name"] is None
    assert entry["original_is_marked"] is False


@pytest.mark.story("12.6", ac=6)
def test_the_card_says_when_the_original_is_no_longer_marked(login_as, db):
    """The unavailability ended first: the original is still released on approval, and Venue Staff
    are told it is no longer marked."""
    scene = make_scenario(db)
    replacement = add_pending_replacement(db, scene)
    end_the_closure(login_as, scene)

    entry = _queue_entry(login_as(Users.VENUE_STAFF), replacement.id)

    assert entry["approval_releases_venue_name"] == scene.original_venue.name
    assert entry["original_is_marked"] is False


@pytest.mark.story("12.6", ac=3)
def test_an_ordinary_request_shows_no_replacement_facts(venue_staff_client, db):
    """A request that replaces nothing carries the fields, empty."""
    scene = make_scenario(db, status=BookingStatus.PENDING)

    entry = _queue_entry(venue_staff_client, scene.original.id)

    assert [entry[field] for field in FIELDS] == [None, None, None]
    assert entry["released_at"] is None


@pytest.mark.story("12.6", ac=3)
def test_the_queue_carries_the_time_a_released_original_was_released(login_as, db):
    """The queue card of a released original says "Closed at": the release, which is when its
    replacement was approved, not the original's own approval."""
    scene = make_scenario(db)
    body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
    staff = login_as(Users.VENUE_STAFF)
    assert approve(staff, body["id"]).status_code == 200

    def entry(status: str, booking_id: str) -> dict:
        response = staff.get(BOOKINGS_PATH, params={"status": status, "limit": 100})
        assert response.status_code == 200, response.text
        return next(each for each in response.json()["items"] if each["id"] == booking_id)

    original = entry("CANCELLED", str(scene.original.id))
    replacement = entry("APPROVED", body["id"])
    assert original["released_at"] == replacement["decided_at"]
    assert original["released_at"] != original["decided_at"]
    assert replacement["released_at"] is None
