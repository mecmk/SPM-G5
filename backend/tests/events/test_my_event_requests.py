"""Story 2.6 - be: list my event requests.

AC1 The list shows every request owned by the signed-in organiser, with name, proposed date,
    and current status.
AC2 Selecting an entry opens its full details. (Opening a request is story 2.1 AC8's
    ``GET /events/{id}``, and refusing someone else's is proven there; the click-through is an
    e2e case: tests/e2e/my-event-requests.spec.ts.)
AC3 The list contains no requests belonging to other organisers.

Proposed and agreed with the team while planning this story:
AC4 Drafts are listed too. A draft can be saved with only a name, so its dates may be empty.
AC5 An organiser with no requests gets an empty list.
AC6 The list is ordered most recently updated first, ties broken by id.
AC7 Only an organiser (``events:read_own``) may read it: other roles get 403, signed-out 401.
AC8 The "New event request" action on the page is a UI case: tests/e2e/my-event-requests.spec.ts.
AC9 The list is paged: at most 100 requests a call, with the total, and the rest a page away.

Ordering tests set ``updated_at`` explicitly. Every test runs in one transaction, and PostgreSQL's
``now()`` is fixed for the whole of it, so rows created in a test would otherwise all tie.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

from app.auth.models import User
from app.events import service
from app.events.models import EventStatus
from app.events.schemas import MyEventEntry
from tests.support.factories import (
    create_event_request,
    create_submittable_event_request,
    make_event,
    make_user,
)
from tests.support.seed import Events, Users

MY_EVENTS_PATH = "/events/mine"
ENTRY_FIELDS = {"id", "name", "starts_at", "ends_at", "status", "cover_image_url"}
# Derived, so a status added later (stories 6.x) is covered without anyone remembering to
# add it here.
ALL_STATUSES = [value for name, value in vars(EventStatus).items() if name.isupper()]
# Later than any seeded or freshly created row, so the ordering tests own the top of the list.
_NEWER = datetime(2030, 2, 1, 9, 0, tzinfo=UTC)
_OLDER = datetime(2030, 1, 1, 9, 0, tzinfo=UTC)


def _page(client: TestClient, query: str = "") -> dict:
    response = client.get(f"{MY_EVENTS_PATH}{query}")
    assert response.status_code == 200, response.text
    return response.json()


def _ids(client: TestClient, query: str = "") -> list[str]:
    return [row["id"] for row in _page(client, query)["items"]]


def _entry(client: TestClient, event_id: uuid.UUID | str) -> dict:
    items = _page(client)["items"]
    entry = next((row for row in items if row["id"] == str(event_id)), None)
    assert entry is not None, f"{event_id} is not in the list: {[row['id'] for row in items]}"
    return entry


# --- AC1: every request I own -------------------------------------------------------------
@pytest.mark.story("2.6", ac=1)
def test_organiser_sees_every_request_they_own(organiser_client):
    assert set(_ids(organiser_client)) == {
        str(Events.DRAFT),
        str(Events.SUBMITTED),
        str(Events.CLARIFICATION_REQUESTED),
        str(Events.SUBMITTED_2),
        str(Events.APPROVED_2),
        str(Events.APPROVED_4),
        str(Events.PLANNING),
        str(Events.COMPLETED),
    }


@pytest.mark.story("2.6", ac=1)
@pytest.mark.story("2.6", ac=3)
def test_second_organiser_sees_only_their_own_requests(login_as):
    assert set(_ids(login_as(Users.ORGANISER_2))) == {
        str(Events.APPROVED),
        str(Events.REJECTED),
        str(Events.UNDER_REVIEW),
        str(Events.APPROVED_3),
        str(Events.APPROVED_5),
        str(Events.CONFIRMED),
        str(Events.CANCELLED),
    }


@pytest.mark.story("2.6", ac=1)
@pytest.mark.parametrize("status", ALL_STATUSES)
def test_a_request_is_listed_whatever_its_status(organiser_client, db: Session, status):
    event = make_event(db, status=status)

    assert str(event.id) in _ids(organiser_client)


@pytest.mark.story("2.6", ac=1)
def test_a_request_just_raised_is_listed_and_follows_its_status(organiser_client):
    created = create_submittable_event_request(organiser_client)
    assert _entry(organiser_client, created["id"])["status"] == "DRAFT"

    assert organiser_client.post(f"/events/{created['id']}/submit").status_code == 200

    assert _entry(organiser_client, created["id"])["status"] == "UNDER_REVIEW"


@pytest.mark.story("2.6", ac=1)
def test_entry_shows_name_proposed_date_and_status_and_nothing_more(organiser_client):
    entry = _entry(organiser_client, Events.SUBMITTED)

    assert set(entry) == ENTRY_FIELDS
    assert entry["name"] == "Data Literacy Workshop"
    assert entry["starts_at"].startswith("2026-11-18")
    assert entry["ends_at"].startswith("2026-11-18")
    assert entry["status"] == "UNDER_REVIEW"


@pytest.mark.story("2.6", ac=1)
def test_entry_carries_the_cover_image_url(organiser_client, db: Session):
    event = make_event(db, cover_image_url="/images/events/test.svg")

    assert _entry(organiser_client, event.id)["cover_image_url"] == "/images/events/test.svg"


# --- AC4: drafts, and drafts without dates ------------------------------------------------
@pytest.mark.story("2.6", ac=4)
def test_seeded_draft_is_listed_with_no_dates(organiser_client):
    entry = _entry(organiser_client, Events.DRAFT)

    assert entry["status"] == "DRAFT"
    assert entry["starts_at"] is None
    assert entry["ends_at"] is None


@pytest.mark.story("2.6", ac=4)
def test_a_draft_saved_with_only_a_name_is_listed(organiser_client):
    response = organiser_client.post("/events", json={"name": "Only a name"})
    assert response.status_code == 201, response.text

    entry = _entry(organiser_client, response.json()["id"])

    assert entry["name"] == "Only a name"
    assert entry["starts_at"] is None


# --- AC3: nobody else's requests ------------------------------------------------------------
@pytest.mark.story("2.6", ac=3)
def test_another_organisers_draft_is_not_listed(organiser_client, db: Session):
    draft = make_event(db, status=EventStatus.DRAFT, organiser_id=Users.ORGANISER_2.id)

    assert str(draft.id) not in _ids(organiser_client)


@pytest.mark.story("2.6", ac=3)
def test_a_colleague_in_the_same_organisation_is_not_listed(organiser_client, db: Session):
    organisation_id = db.get(User, Users.ORGANISER.id).organisation_id
    colleague = make_user(db, role="EVENT_ORGANISER", organisation_id=organisation_id)
    theirs = make_event(db, organiser_id=colleague.id)

    assert str(theirs.id) not in _ids(organiser_client)


@pytest.mark.story("2.6", ac=3)
def test_an_organiser_id_in_the_query_cannot_widen_the_list(organiser_client):
    own = _ids(organiser_client)

    widened = _ids(organiser_client, f"?organiser_id={Users.ORGANISER_2.id}")

    assert widened == own


# --- AC5: nothing raised yet ----------------------------------------------------------------
@pytest.mark.story("2.6", ac=5)
def test_an_organiser_with_no_requests_gets_an_empty_list(client, db: Session):
    newcomer = make_user(db, role="EVENT_ORGANISER")
    client.login(newcomer.email)

    assert _page(client) == {"items": [], "total": 0}


# --- AC6: order -----------------------------------------------------------------------------
@pytest.mark.story("2.6", ac=6)
def test_most_recently_updated_request_is_first(organiser_client, db: Session):
    # Created older-first, so an insertion-order list would put them the other way round.
    older = make_event(db, updated_at=_OLDER)
    newer = make_event(db, updated_at=_NEWER)

    assert _ids(organiser_client)[:2] == [str(newer.id), str(older.id)]


@pytest.mark.story("2.6", ac=6)
def test_requests_updated_at_the_same_moment_keep_a_stable_order(organiser_client, db: Session):
    first = make_event(db, updated_at=_NEWER)
    second = make_event(db, updated_at=_NEWER)

    assert _ids(organiser_client)[:2] == sorted([str(first.id), str(second.id)])


# --- AC7: who may read it ---------------------------------------------------------------------
@pytest.mark.story("2.6", ac=7)
@pytest.mark.story("1.2", ac=4)
@pytest.mark.parametrize(
    "user", [Users.COORDINATOR, Users.VENUE_STAFF, Users.TECH_SUPPORT, Users.ATTENDEE]
)
def test_other_roles_cannot_read_the_list(client, user):
    client.login(user)

    assert client.get(MY_EVENTS_PATH).status_code == 403


@pytest.mark.story("2.6", ac=7)
def test_signed_out_user_is_rejected(client):
    assert client.get(MY_EVENTS_PATH).status_code == 401


# --- AC9: paging ---------------------------------------------------------------------------
@pytest.mark.story("2.6", ac=9)
def test_limit_caps_the_page_and_total_counts_every_request_i_own(organiser_client, db: Session):
    make_event(db, organiser_id=Users.ORGANISER_2.id)  # someone else's: not counted

    page = _page(organiser_client, "?limit=2")

    assert len(page["items"]) == 2
    assert page["total"] == 8  # the eight seeded requests Olivia owns


@pytest.mark.story("2.6", ac=9)
def test_pages_follow_on_from_each_other_without_overlap(organiser_client):
    everything = _ids(organiser_client)

    first = _ids(organiser_client, "?limit=4&offset=0")
    second = _ids(organiser_client, "?limit=4&offset=4")

    assert first + second == everything


@pytest.mark.story("2.6", ac=9)
def test_pages_keep_one_order_even_when_updated_at_ties(organiser_client, db: Session):
    tied = [make_event(db, updated_at=_NEWER) for _ in range(3)]

    paged = [_ids(organiser_client, f"?limit=1&offset={n}")[0] for n in range(3)]

    assert paged == sorted(str(event.id) for event in tied)


@pytest.mark.story("2.6", ac=9)
def test_an_offset_past_the_end_is_an_empty_page_not_an_error(organiser_client):
    page = _page(organiser_client, "?offset=100")

    assert page["items"] == []
    assert page["total"] == 8


@pytest.mark.story("2.6", ac=9)
@pytest.mark.parametrize("query", ["?limit=1", "?limit=100", "?offset=0", "?offset=2147483647"])
def test_the_edges_of_the_allowed_range_are_accepted(organiser_client, query):
    assert organiser_client.get(f"{MY_EVENTS_PATH}{query}").status_code == 200


@pytest.mark.story("2.6", ac=9)
@pytest.mark.parametrize(
    "query",
    ["?limit=0", "?limit=101", "?limit=-1", "?offset=-1", "?offset=2147483648", "?limit=ten"],
)
def test_a_limit_or_offset_outside_the_allowed_range_is_refused(organiser_client, query):
    assert organiser_client.get(f"{MY_EVENTS_PATH}{query}").status_code == 422


# --- cost ---------------------------------------------------------------------------------------
@pytest.mark.story("2.6")
def test_listing_is_two_queries_and_does_not_join_the_users_it_does_not_show(db: Session):
    """The entry shows six columns of the event. ``Event.organiser`` and
    ``Event.assigned_coordinator`` are joined eagerly for the review queue's sake, so without an
    opt-out every call would join ``users`` twice per row for nothing."""
    organiser = db.get(User, Users.ORGANISER.id)
    statements: list[str] = []
    listener = lambda _conn, _cursor, statement, *_rest: statements.append(statement)  # noqa: E731
    sa_event.listen(db.get_bind(), "before_cursor_execute", listener)
    try:
        listing = service.list_my_events(db, organiser=organiser)
        [MyEventEntry.from_event(row) for row in listing.events]
    finally:
        sa_event.remove(db.get_bind(), "before_cursor_execute", listener)

    assert listing.events
    assert len(statements) == 2, statements  # the page, and the count behind ``total``
    assert not any("JOIN users" in statement for statement in statements)


# --- the route must not be read as an event id --------------------------------------------------
@pytest.mark.story("2.6", ac=1)
def test_mine_is_not_taken_for_an_event_id(organiser_client):
    """``/events/mine`` sits beside ``/events/{event_id}``; if it were declared after it, "mine"
    would be parsed as an id and the call would be a 422."""
    created = create_event_request(organiser_client)

    assert organiser_client.get(MY_EVENTS_PATH).status_code == 200
    assert organiser_client.get(f"/events/{created['id']}").status_code == 200
