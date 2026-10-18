"""Story 12.6 AC3 / AC6 - what Venue Staff are shown about a replacement before they approve it.

Approving a replacement releases another booking, so the queue card and the request's own page say
so: which venue it replaces, which venue approving it will release - only while that booking still
holds its venue - and whether the original is still marked "Venue unavailable" (AC6: the
replacement is approved either way).

The approval itself is test_replacement_approval.py.
"""

from __future__ import annotations

import uuid

import pytest

from app.bookings.models import BookingStatus
from tests.support.replacement import (
    BOOKINGS_PATH,
    add_pending_replacement,
    end_the_closure,
    make_scenario,
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
