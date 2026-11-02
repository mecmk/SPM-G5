"""Story 13.3 - search and order the Technical Support equipment queue (story 15.2). The Venue
Staff booking queue's half is backend/tests/bookings/test_queue_search_sort.py.

AC1 The equipment queue gets a search box and an Order by list beside its tabs; the search and
    order apply within whichever tab is open.
AC2 The search matches the event name, the equipment type or who requested it, containing the
    text and ignoring capitals; each tab's count shows how many of its requests match.
AC3 Order by: date, soonest first (the default) or latest first; requested, oldest or newest
    first; event name, A to Z; equipment type, A to Z. Names ignore capitals, and requests that
    tie stay in date order, soonest first.
AC4 The search and order run on the server, across every request in the tab. The equipment queue
    has no pages, so AC1-AC3's cases cover it.
AC5 A search of up to 100 characters is accepted and a longer one refused; spaces around it are
    ignored, and a blank one lists the whole tab. An order the list does not offer is refused.
AC6 %, _ and ' are matched as typed, not as wildcards. A request with no recorded request time
    comes last when ordered by when it was requested.
AC8 Only Technical Support Staff: a signed-out visitor gets 401 and any other role 403, with or
    without a search.
AC9 Each load searches and orders the requests as they stand at that moment.

The box, the address and Clear search are the page's: tests/e2e/queue-search.spec.ts. AC7 is
wholly the page's.

Every request a test makes carries ``TOKEN`` in a searched field, which no seeded name holds, so a
search for it finds only that test's requests. Each is on an event of its own, dated September
2027 like story 15.2's tests, clear of every seeded hold, with an equipment type of its own.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.events.models import EventEquipmentRequest, EventStatus
from tests.support.factories import (
    make_equipment_item,
    make_equipment_type,
    make_event,
    make_user,
)
from tests.support.seed import Users

QUEUE_PATH = "/equipment-requests"
TOKEN = "Quokka"
SEARCH_MAX_LENGTH = 100
PENDING, ACCEPTED, DECLINED = "PENDING", "ACCEPTED", "DECLINED"
NO_COUNTS = {"pending": 0, "accepted": 0, "declined": 0, "cancelled": 0, "withdrawn": 0}

SGT = timezone(timedelta(hours=8))


def _day(day: int) -> datetime:
    """9 am on a day in September 2027."""
    return datetime(2027, 9, day, 9, 0, tzinfo=SGT)


def _sent_at(day: int) -> datetime:
    """When a request was sent to Technical Support: a day in October 2026."""
    return datetime(2026, 10, day, 9, 0, tzinfo=SGT)


def _request(
    db: Session,
    *,
    event_name: str,
    starts_at: datetime,
    type_name: str | None = None,
    status: str = PENDING,
    **extra,
) -> EventEquipmentRequest:
    """One request sent to Technical Support, for an event of its own and a type of its own (or
    ``type_name``'s, made here). A declined request holds nothing."""
    event = make_event(
        db,
        status=EventStatus.PLANNING,
        name=event_name,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=8),
    )
    kit = extra.pop("equipment_type", None) or make_equipment_type(
        db, total_quantity=5, **({} if type_name is None else {"name": type_name})
    )
    return make_equipment_item(
        db,
        event=event,
        equipment_type=kit,
        quantity=1,
        status=status,
        is_held=status != DECLINED,
        submitted_by_id=extra.pop("submitted_by_id", Users.COORDINATOR.id),
        submitted_at=extra.pop("submitted_at", _sent_at(1)),
        **extra,
    )


def _queue(client, **params: str) -> dict:
    response = client.get(QUEUE_PATH, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(client, **params: str) -> list[str]:
    return [row["id"] for row in _queue(client, **params)["items"]]


def _id(item: EventEquipmentRequest) -> str:
    return str(item.id)


def _tied_id(n: int) -> uuid.UUID:
    """A fixed id, so requests that tie can be given ids in the opposite order to their dates."""
    return uuid.UUID(f"13300000-0000-0000-0000-{n:012d}")


# --- AC1: the search applies within the open tab --------------------------------------------------
@pytest.mark.story("13.3", ac=1)
def test_a_search_lists_only_the_open_tabs_matching_requests(tech_client, db):
    pending = _request(db, event_name=f"{TOKEN} Gala", starts_at=_day(6))
    accepted = _request(db, event_name=f"{TOKEN} Ball", starts_at=_day(7), status=ACCEPTED)
    _request(db, event_name="Plain Gala", starts_at=_day(8))

    assert _ids(tech_client, status=PENDING, search=TOKEN) == [_id(pending)]
    assert _ids(tech_client, search=TOKEN) == [_id(pending), _id(accepted)]


# --- AC2: what the search matches, and the tab counts ---------------------------------------------
@pytest.mark.story("13.3", ac=2)
@pytest.mark.parametrize("field", ["event name", "equipment type", "requested by"])
def test_each_searched_field_finds_a_request(tech_client, db, field):
    requester = make_user(
        db,
        role="EVENT_COORDINATOR",
        full_name=f"Quinn {TOKEN}" if field == "requested by" else "Quinn Plain",
    )
    item = _request(
        db,
        event_name=f"{TOKEN} Gala" if field == "event name" else "Plain Gala",
        starts_at=_day(6),
        type_name=f"{TOKEN} mixer" if field == "equipment type" else "Plain mixer",
        submitted_by_id=requester.id,
    )

    assert _ids(tech_client, search=TOKEN) == [_id(item)]


@pytest.mark.story("13.3", ac=2)
@pytest.mark.parametrize("search", ["QUOKKAFEST", "quokkafest", "uokkaf"])
def test_the_search_ignores_capitals_and_matches_inside_a_word(tech_client, db, search):
    item = _request(db, event_name="Grand Quokkafest", starts_at=_day(6))

    assert _ids(tech_client, search=search) == [_id(item)]


@pytest.mark.story("13.3", ac=2)
@pytest.mark.parametrize("field", ["technical notes", "equipment type code"])
def test_text_only_in_a_field_not_searched_matches_nothing(tech_client, db, field):
    kit = make_equipment_type(
        db, code=f"{TOKEN.upper()}_KIT" if field == "equipment type code" else "PLAIN_KIT"
    )
    _request(
        db,
        event_name="Plain Gala",
        starts_at=_day(6),
        equipment_type=kit,
        technical_notes=f"{TOKEN} cabling" if field == "technical notes" else None,
    )

    assert _ids(tech_client, search=TOKEN) == []


@pytest.mark.story("13.3", ac=2)
def test_each_tabs_count_is_how_many_of_its_requests_match(tech_client, db):
    _request(db, event_name=f"{TOKEN} One", starts_at=_day(6))
    _request(db, event_name=f"{TOKEN} Two", starts_at=_day(7))
    _request(db, event_name=f"{TOKEN} Three", starts_at=_day(8), status=ACCEPTED)
    _request(db, event_name=f"{TOKEN} Four", starts_at=_day(9), status=DECLINED)
    _request(db, event_name="Plain Five", starts_at=_day(10))

    body = _queue(tech_client, status=ACCEPTED, search=TOKEN)

    assert body["counts"] == {**NO_COUNTS, "pending": 2, "accepted": 1, "declined": 1}
    assert [row["status"] for row in body["items"]] == [ACCEPTED]


# --- AC3: Order by --------------------------------------------------------------------------------
def _three_to_order(db: Session) -> dict[str, EventEquipmentRequest]:
    """Three requests that every order puts in a different sequence. Their names mix capitals, so
    a byte-wise order would differ from one that ignores them."""
    rows = {
        "A": ("QUOKKA Bravo", "Bravo Kit", _day(6), _sent_at(1)),
        "B": ("Quokka alpha", "CHARLIE kit", _day(7), _sent_at(3)),
        "C": ("quokka Charlie", "alpha kit", _day(8), _sent_at(2)),
    }
    return {
        key: _request(
            db,
            event_name=event_name,
            starts_at=starts_at,
            type_name=type_name,
            submitted_at=submitted_at,
        )
        for key, (event_name, type_name, starts_at, submitted_at) in rows.items()
    }


@pytest.mark.story("13.3", ac=3)
@pytest.mark.parametrize(
    ("order", "expected"),
    [
        (None, "ABC"),
        ("date", "ABC"),
        ("date_desc", "CBA"),
        ("requested", "ACB"),
        ("requested_desc", "BCA"),
        ("event_name", "BAC"),
        ("equipment_type", "CAB"),
    ],
)
def test_each_order_lists_the_requests_in_that_order(tech_client, db, order, expected):
    items = _three_to_order(db)
    params = {"search": TOKEN} if order is None else {"search": TOKEN, "order": order}

    assert _ids(tech_client, **params) == [_id(items[key]) for key in expected]


@pytest.mark.story("13.3", ac=3)
@pytest.mark.parametrize("order", ["event_name", "equipment_type", "requested", "requested_desc"])
def test_requests_that_tie_stay_in_date_order_soonest_first(tech_client, db, order):
    """The three tie on everything but their dates - one type, one name, sent together - and their
    ids run the other way, so only the date can put them soonest first."""
    kit = make_equipment_type(db, name=f"{TOKEN} tie kit")
    latest, middle, soonest = (
        _request(
            db, event_name=f"{TOKEN} Tie", starts_at=_day(day), equipment_type=kit, id=_tied_id(n)
        )
        for n, day in [(1, 8), (2, 7), (3, 6)]
    )

    ids = _ids(tech_client, search=TOKEN, order=order)

    assert ids == [_id(soonest), _id(middle), _id(latest)]


# --- AC5: boundaries ------------------------------------------------------------------------------
@pytest.mark.story("13.3", ac=5)
def test_a_search_of_100_characters_is_accepted(tech_client, db):
    name = f"{TOKEN} " + "x" * (SEARCH_MAX_LENGTH - len(TOKEN) - 1)
    item = _request(db, event_name=name, starts_at=_day(6))

    assert len(name) == SEARCH_MAX_LENGTH
    assert _ids(tech_client, search=name) == [_id(item)]


@pytest.mark.story("13.3", ac=5)
def test_a_search_of_101_characters_is_refused(tech_client):
    assert tech_client.get(QUEUE_PATH, params={"search": "x" * 101}).status_code == 422


@pytest.mark.story("13.3", ac=5)
def test_spaces_around_the_search_are_ignored(tech_client, db):
    item = _request(db, event_name=f"{TOKEN} Gala", starts_at=_day(6))

    assert _ids(tech_client, search=f"   {TOKEN.lower()}  ") == [_id(item)]


@pytest.mark.story("13.3", ac=5)
@pytest.mark.parametrize("search", ["", "   "])
def test_a_blank_or_spaces_only_search_lists_the_whole_tab(tech_client, search):
    whole = _queue(tech_client, status=PENDING)

    assert _queue(tech_client, status=PENDING, search=search) == whole


@pytest.mark.story("13.3", ac=5)
@pytest.mark.parametrize("order", ["price", "event_name_desc", "DATE", "", "venue_name"])
def test_an_order_the_list_does_not_offer_is_refused(tech_client, order):
    assert tech_client.get(QUEUE_PATH, params={"order": order}).status_code == 422


# --- AC6: characters that are wildcards in SQL, and a request with no recorded time ---------------
@pytest.mark.story("13.3", ac=6)
@pytest.mark.parametrize(
    ("search", "target", "decoy"),
    [
        ("quokka%fun", "Quokka%Fun", "Quokka Big Fun"),
        ("quokka_night", "Quokka_Night", "Quokka Night"),
        ("quokka's", "Quokka's Ball", "Quokkas Ball"),
        ("quokka\\night", "Quokka\\Night", "QuokkaNight"),
        ("quokka/night", "Quokka/Night", "QuokkaNight"),
    ],
)
def test_wildcard_characters_and_quotes_are_matched_as_typed(
    tech_client, db, search, target, decoy
):
    """Each decoy is what the search would also find if its character were a LIKE wildcard, or
    the escape character LIKE was given."""
    found = _request(db, event_name=target, starts_at=_day(6))
    _request(db, event_name=decoy, starts_at=_day(7))

    assert _ids(tech_client, search=search) == [_id(found)]


@pytest.mark.story("13.3", ac=6)
@pytest.mark.parametrize(("order", "expected"), [("requested", "AB-"), ("requested_desc", "BA-")])
def test_a_request_with_no_recorded_time_comes_last_either_way(tech_client, db, order, expected):
    """Sent before migration 014, it has no recorded sender or time. Its event is the soonest, so
    date order would put it first, not last."""
    items = {
        "-": _request(
            db,
            event_name=f"{TOKEN} Unrecorded",
            starts_at=_day(6),
            submitted_by_id=None,
            submitted_at=None,
        ),
        "A": _request(db, event_name=f"{TOKEN} Older", starts_at=_day(7), submitted_at=_sent_at(1)),
        "B": _request(db, event_name=f"{TOKEN} Newer", starts_at=_day(8), submitted_at=_sent_at(2)),
    }

    assert _ids(tech_client, search=TOKEN, order=order) == [_id(items[key]) for key in expected]


# --- AC8: who may search --------------------------------------------------------------------------
WITH_A_SEARCH = {"search": TOKEN, "order": "event_name"}


@pytest.mark.story("13.3", ac=8)
@pytest.mark.parametrize("params", [{}, WITH_A_SEARCH], ids=["without a search", "with a search"])
def test_a_signed_out_visitor_is_refused(client, params):
    assert client.get(QUEUE_PATH, params=params).status_code == 401


@pytest.mark.story("13.3", ac=8)
@pytest.mark.parametrize("params", [{}, WITH_A_SEARCH], ids=["without a search", "with a search"])
@pytest.mark.parametrize(
    "user",
    [
        Users.ORGANISER,
        Users.COORDINATOR,
        Users.LEAD,
        Users.VENUE_STAFF,
        Users.SAFETY_OFFICER,
        Users.ATTENDEE,
    ],
)
def test_any_other_role_is_refused(client, user, params):
    client.login(user)

    assert client.get(QUEUE_PATH, params=params).status_code == 403


# --- AC9: each load as the requests stand ---------------------------------------------------------
@pytest.mark.story("13.3", ac=9)
def test_each_load_searches_the_requests_as_they_stand(tech_client, db):
    decided = _request(db, event_name=f"{TOKEN} Alpha", starts_at=_day(6))
    kept = _request(db, event_name=f"{TOKEN} Charlie", starts_at=_day(8))
    pending = {"status": PENDING, "search": TOKEN}
    assert _ids(tech_client, **pending) == [_id(decided), _id(kept)]

    accept = tech_client.post(f"{QUEUE_PATH}/{decided.id}/decision", json={"outcome": ACCEPTED})
    assert accept.status_code == 201, accept.text
    added = _request(db, event_name=f"{TOKEN} Bravo", starts_at=_day(7))
    body = _queue(tech_client, **pending)

    assert [row["id"] for row in body["items"]] == [_id(added), _id(kept)]
    assert body["counts"] == {**NO_COUNTS, "pending": 2, "accepted": 1}
