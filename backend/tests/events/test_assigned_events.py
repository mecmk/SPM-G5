"""Story 6.1 - be: the coordinator's assigned events, any status.

AC1 Every event assigned to the signed-in coordinator comes back, whatever its status - unlike
    the review queue (story 4.1), which only ever returns the three awaiting-decision statuses.
AC2 Nobody else's assigned events appear, and an event with no coordinator (a draft) never does.
AC3 The list is paged, most recently updated first, mirroring story 2.6's `/events/mine`.
AC4 Only `events:review` may read it: other roles get 403, signed-out gets 401.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.events.models import EventStatus
from tests.support.factories import make_event
from tests.support.seed import Events, Users

ASSIGNED_PATH = "/events/assigned-to-me"
ENTRY_FIELDS = {
    "id",
    "name",
    "organiser_name",
    "starts_at",
    "ends_at",
    "submitted_at",
    "status",
    "cover_image_url",
}
# Derived, so a status added later is covered without anyone remembering to add it here.
ALL_STATUSES = [value for name, value in vars(EventStatus).items() if name.isupper()]


def _page(client, query: str = "") -> dict:
    response = client.get(f"{ASSIGNED_PATH}{query}")
    assert response.status_code == 200, response.text
    return response.json()


def _ids(client, query: str = "") -> list[str]:
    return [row["id"] for row in _page(client, query)["items"]]


# --- AC1: every status, not just the review queue's three ---------------------------------
@pytest.mark.story("6.1", ac=1)
@pytest.mark.parametrize(
    "status",
    [
        EventStatus.SUBMITTED,
        EventStatus.UNDER_REVIEW,
        EventStatus.CLARIFICATION_REQUESTED,
        EventStatus.APPROVED,
        EventStatus.PLANNING,
        EventStatus.CONFIRMED,
        EventStatus.COMPLETED,
        EventStatus.CANCELLED,
        EventStatus.REJECTED,
    ],
)
def test_an_assigned_event_is_listed_whatever_its_status(coordinator_client, db: Session, status):
    event = make_event(db, status=status, assigned_coordinator_id=Users.COORDINATOR.id)

    assert str(event.id) in _ids(coordinator_client)


@pytest.mark.story("6.1", ac=1)
def test_seeded_events_in_the_newer_statuses_are_listed(coordinator_client):
    """The four statuses story 6.1 adds to the visible/status model - the review queue never
    returned any of these, so this is the first coverage proving they can be listed at all."""
    ids = _ids(coordinator_client)

    assert str(Events.PLANNING) in ids
    assert str(Events.CONFIRMED) in ids
    assert str(Events.COMPLETED) in ids
    assert str(Events.CANCELLED) in ids


# --- AC2: only mine, and never a draft -------------------------------------------------------
@pytest.mark.story("6.1", ac=2)
def test_an_event_assigned_to_another_coordinator_is_not_listed(login_as):
    assert str(Events.APPROVED_2) not in _ids(login_as(Users.COORDINATOR))
    assert str(Events.APPROVED_2) in _ids(login_as(Users.COORDINATOR_2))


@pytest.mark.story("6.1", ac=2)
def test_a_draft_is_never_listed(coordinator_client, db: Session):
    """A draft has no assigned coordinator (assignment happens at submission), so it can never
    match the `assigned_coordinator_id` filter regardless of who is signed in."""
    draft = make_event(db, status=EventStatus.DRAFT, assigned_coordinator_id=None)

    assert str(draft.id) not in _ids(coordinator_client)


# --- entry shape -----------------------------------------------------------------------------
@pytest.mark.story("6.1", ac=1)
def test_entry_shows_name_organiser_dates_and_status(coordinator_client):
    entry = next(
        row for row in _page(coordinator_client)["items"] if row["id"] == str(Events.APPROVED)
    )

    assert set(entry) == ENTRY_FIELDS
    assert entry["name"] == "Nimbus Developer Conference"
    assert entry["organiser_name"] == Users.ORGANISER_2.full_name
    assert entry["status"] == "APPROVED"


# --- AC3: paging, most recently updated first ------------------------------------------------
@pytest.mark.story("6.1", ac=3)
def test_limit_caps_the_page_and_total_counts_every_assigned_event(coordinator_client):
    page = _page(coordinator_client, "?limit=2")

    assert len(page["items"]) == 2
    assert page["total"] >= 2


@pytest.mark.story("6.1", ac=3)
def test_pages_follow_on_from_each_other_without_overlap(coordinator_client):
    everything = _ids(coordinator_client)

    first = _ids(coordinator_client, "?limit=5&offset=0")
    second = _ids(coordinator_client, f"?limit={len(everything)}&offset=5")

    assert first + second == everything


@pytest.mark.story("6.1", ac=3)
def test_an_offset_past_the_end_is_an_empty_page_not_an_error(coordinator_client):
    total = _page(coordinator_client)["total"]

    page = _page(coordinator_client, f"?offset={total + 100}")

    assert page["items"] == []
    assert page["total"] == total


# --- AC4: who may read it ---------------------------------------------------------------------
@pytest.mark.story("6.1", ac=4)
@pytest.mark.story("1.2", ac=4)
@pytest.mark.parametrize(
    "user", [Users.ORGANISER, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE]
)
def test_other_roles_cannot_read_the_list(client, user):
    client.login(user)

    assert client.get(ASSIGNED_PATH).status_code == 403


@pytest.mark.story("6.1", ac=4)
def test_signed_out_user_is_rejected(client):
    assert client.get(ASSIGNED_PATH).status_code == 401
