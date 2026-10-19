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

This file is the coordinator's "Venue unavailable" tab (AC11). ``GET /events/assigned-to-me`` (story
6.1) gains ``?venue_unavailable=true``, which lists only the signed-in coordinator's events with a
booking marked "Venue unavailable - alternative needed" (9.4), and every answer carries
``venue_unavailable_count``: how many such events the coordinator has, whatever the page or the
filter, 0 when none - the tab is never hidden. Each entry says whether its event has a marked
booking and, when a replacement is pending, which venue it asks for. An event leaves the tab when no
booking on it is marked any more: the replacement approved, the unavailability ended, the event
cancelled.

The seed has marked events of both coordinators (Events.LANTERN_SHOWCASE and the rest of story
12.6's e2e events), so a count is read before a case adds its own and compared with it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.bookings.models import BookingStatus
from app.events.models import EventStatus
from tests.support.replacement import (
    add_pending_replacement,
    approve,
    created,
    make_scenario,
    replace,
)
from tests.support.seed import Users

PATH = "/events/assigned-to-me"


def _listed(client, **params) -> dict:
    response = client.get(PATH, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(body: dict) -> list[str]:
    return [entry["id"] for entry in body["items"]]


def _unmark_everything(db) -> None:
    """Start from no marked booking at all, the seed's included (rolled back with the test)."""
    db.execute(text("UPDATE venue_bookings SET venue_unavailable_marked_at = NULL"))
    db.expire_all()


@pytest.mark.story("12.6", ac=11)
def test_the_filtered_list_holds_only_the_coordinators_events_with_a_marked_booking(
    coordinator_client, db
):
    mine = make_scenario(db)
    unmarked = make_scenario(db, marked=False)
    carls = make_scenario(db, coordinator_id=Users.COORDINATOR_2.id)

    body = _listed(coordinator_client, venue_unavailable="true")

    ids = _ids(body)
    assert str(mine.event.id) in ids
    assert str(unmarked.event.id) not in ids
    assert str(carls.event.id) not in ids
    assert all(entry["is_venue_unavailable"] for entry in body["items"])


@pytest.mark.story("12.6", ac=11)
def test_the_count_ignores_paging_and_the_filter(coordinator_client, db):
    baseline = _listed(coordinator_client)["venue_unavailable_count"]
    make_scenario(db)
    make_scenario(db)
    # Another coordinator's marked event is not this coordinator's to count.
    make_scenario(db, coordinator_id=Users.COORDINATOR_2.id)

    plain = _listed(coordinator_client)
    paged = _listed(coordinator_client, limit=1, offset=1)
    filtered = _listed(coordinator_client, venue_unavailable="true", limit=1)

    assert plain["venue_unavailable_count"] == baseline + 2
    assert paged["venue_unavailable_count"] == baseline + 2
    assert filtered["venue_unavailable_count"] == baseline + 2


@pytest.mark.story("12.6", ac=11)
def test_the_count_is_zero_when_none_is_marked(coordinator_client, db):
    _unmark_everything(db)

    plain = _listed(coordinator_client)
    filtered = _listed(coordinator_client, venue_unavailable="true")

    assert plain["venue_unavailable_count"] == 0
    assert (filtered["venue_unavailable_count"], filtered["total"], filtered["items"]) == (0, 0, [])


@pytest.mark.story("12.6", ac=11)
def test_a_filtered_total_pages_the_filtered_set(coordinator_client, db):
    _unmark_everything(db)
    scenes = [make_scenario(db, days=45 + index) for index in range(3)]

    first = _listed(coordinator_client, venue_unavailable="true", limit=2)
    second = _listed(coordinator_client, venue_unavailable="true", limit=2, offset=2)

    assert (first["total"], len(first["items"])) == (3, 2)
    assert (second["total"], len(second["items"])) == (3, 1)
    assert sorted(_ids(first) + _ids(second)) == sorted(str(scene.event.id) for scene in scenes)


@pytest.mark.story("12.6", ac=11)
def test_an_event_with_a_pending_replacement_stays_listed_and_names_its_venue(
    coordinator_client, db
):
    scene = make_scenario(db)
    add_pending_replacement(db, scene)

    body = _listed(coordinator_client, venue_unavailable="true")

    entry = next(each for each in body["items"] if each["id"] == str(scene.event.id))
    assert entry["is_venue_unavailable"] is True
    assert entry["pending_replacement_venue_name"] == scene.alternative.name


@pytest.mark.story("12.6", ac=11)
def test_every_entry_says_whether_its_event_has_a_marked_booking(coordinator_client, db):
    marked, unmarked = make_scenario(db), make_scenario(db, marked=False)

    entries = {entry["id"]: entry for entry in _listed(coordinator_client)["items"]}

    assert entries[str(marked.event.id)]["is_venue_unavailable"] is True
    assert entries[str(unmarked.event.id)]["is_venue_unavailable"] is False
    assert entries[str(unmarked.event.id)]["pending_replacement_venue_name"] is None


@pytest.mark.story("12.6", ac=11)
@pytest.mark.parametrize(
    "why",
    [
        "replacement_approved",
        "mark_cleared",
        "event_cancelled",
        BookingStatus.REJECTED,
        BookingStatus.WITHDRAWN,
        BookingStatus.EXPIRED,
        BookingStatus.CANCELLED,
    ],
)
def test_an_event_leaves_the_tab_when_no_booking_is_marked(login_as, db, why):
    """The replacement was approved (the original is released), the mark cleared, the event was
    cancelled, or the marked booking is closed: its mark, if still on the row, is history."""
    baseline = _listed(login_as(Users.COORDINATOR))["venue_unavailable_count"]
    if why == "replacement_approved":
        scene = make_scenario(db)
        body = created(replace(login_as(Users.COORDINATOR), scene.original.id, scene.alternative))
        assert approve(login_as(Users.VENUE_STAFF), body["id"]).status_code == 200
    elif why == "mark_cleared":
        scene = make_scenario(db, marked=False)
    elif why == "event_cancelled":
        scene = make_scenario(db, event_status=EventStatus.CANCELLED)
    else:
        scene = make_scenario(db, status=why)

    client = login_as(Users.COORDINATOR)
    filtered = _listed(client, venue_unavailable="true")
    plain = _listed(client)

    assert str(scene.event.id) not in _ids(filtered)
    assert plain["venue_unavailable_count"] == baseline


@pytest.mark.story("12.6", ac=11)
def test_an_unknown_filter_value_is_refused(coordinator_client):
    response = coordinator_client.get(PATH, params={"venue_unavailable": str(uuid.uuid4())})

    assert response.status_code == 422
