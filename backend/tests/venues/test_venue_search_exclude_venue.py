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

This file is the search behind the catalogue opened to replace a booking (AC1): ``GET
/venues/search`` takes ``exclude_venue``, a venue the results never hold, whatever else is filtered
- the period included, which the coordinator may edit by hand once the catalogue is open. It is part
of the search's scope, not one of its filters, so the "Try removing" hints of a search that found
nothing never offer to bring that venue back, and never count it.

The page that sends it is tests/e2e/venue-replacement.spec.ts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.support.factories import make_venue


def _pair(db) -> tuple[str, object, object]:
    """Two venues sharing a name prefix no other venue has: a large one and a small one."""
    prefix = f"Replace {uuid.uuid4().hex[:8]}"
    large = make_venue(db, name=f"{prefix} Alpha", capacity=300)
    small = make_venue(db, name=f"{prefix} Beta", capacity=20)
    return prefix, large, small


def _names(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [venue["name"] for venue in response.json()["venues"]]


@pytest.mark.story("12.6", ac=1)
def test_search_excludes_the_named_venue(coordinator_client, db):
    prefix, large, small = _pair(db)

    everything = _names(coordinator_client.get("/venues/search", params={"search": prefix}))
    excluded = _names(
        coordinator_client.get(
            "/venues/search", params={"search": prefix, "exclude_venue": str(large.id)}
        )
    )

    assert everything == [large.name, small.name]
    assert excluded == [small.name]


@pytest.mark.story("12.6", ac=1)
def test_the_exclusion_holds_with_a_period_and_with_none(coordinator_client, db):
    """Free for the whole period, the venue would be found - the exclusion is what leaves it out,
    for the period the page opened with, a hand-edited one, and no period at all."""
    prefix, large, small = _pair(db)
    start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=60)

    for period in (
        {},
        {"starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=6)).isoformat()},
        {
            "starts_at": (start + timedelta(days=3)).isoformat(),
            "ends_at": (start + timedelta(days=3, hours=2)).isoformat(),
        },
    ):
        names = _names(
            coordinator_client.get(
                "/venues/search",
                params={"search": prefix, "exclude_venue": str(large.id), **period},
            )
        )
        assert names == [small.name], period


@pytest.mark.story("12.6", ac=1)
def test_the_excluded_venue_is_never_offered_back_or_counted_by_the_removal_hints(
    coordinator_client, db
):
    """Only the large venue fits 250 people. Excluded, nothing is found, and removing the capacity
    would find the one other venue - not two, since the excluded one is outside the search."""
    prefix, large, _small = _pair(db)
    params = {"search": prefix, "capacity": 250}

    unexcluded = coordinator_client.get("/venues/search", params=params).json()
    excluded = coordinator_client.get(
        "/venues/search", params={**params, "exclude_venue": str(large.id)}
    ).json()

    assert [venue["name"] for venue in unexcluded["venues"]] == [large.name]
    assert excluded["venues"] == []
    capacity = next(hint for hint in excluded["relax"] if hint["filter"] == "capacity")
    assert capacity["count"] == 1


@pytest.mark.story("12.6", ac=1)
def test_a_malformed_exclude_venue_is_refused(coordinator_client):
    response = coordinator_client.get("/venues/search", params={"exclude_venue": "not-an-id"})

    assert response.status_code == 422
