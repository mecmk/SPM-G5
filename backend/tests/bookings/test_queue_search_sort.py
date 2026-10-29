"""Story 13.3 - search and order the Venue Staff booking queue (story 13.1). The Technical Support
equipment queue's half is backend/tests/equipment/test_queue_search_sort.py.

AC1 The booking queue gets a search box and an Order by list beside its tabs; the search and order
    apply within whichever tab is open.
AC2 The search matches the event name, the venue name or who submitted the request, containing
    the text and ignoring capitals; each tab's count shows how many of its requests match.
AC3 Order by: date, soonest first (the default) or latest first; requested, oldest or newest
    first; event name, A to Z; venue, A to Z. Names ignore capitals, and requests that tie stay in
    date order, soonest first.
AC4 The search and order run on the server across the whole tab before it is cut into pages of
    ten (13.1.2 AC4); the total counts only the matching requests.
AC5 A search of up to 100 characters is accepted and a longer one refused; spaces around it are
    ignored, and a blank one lists the whole tab. An order the list does not offer is refused.
AC6 %, _ and ' are matched as typed, not as wildcards.
AC8 Only Venue Staff: a signed-out visitor gets 401 and any other role 403, with or without a
    search.
AC9 Each load searches and orders the requests as they stand at that moment.

The box, the address, the pager and Clear search are the page's: tests/e2e/queue-search.spec.ts.
AC7 is wholly the page's.

Every request a test makes carries ``TOKEN`` in a searched field, which no seeded name holds, so a
search for it finds only that test's requests, whatever the seed and other tests add. Requests are
dated in 2029, after every seeded one, on separate days so no two hold one venue at once.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.bookings.models import BookingStatus, VenueBooking
from app.events.models import EventStatus
from tests.support.factories import (
    approval_payload,
    make_booking,
    make_event,
    make_user,
    make_venue,
)
from tests.support.seed import Users, Venues

BOOKINGS_PATH = "/bookings"
TOKEN = "Quokka"
SEARCH_MAX_LENGTH = 100
QUEUE_PAGE_SIZE = 10
NO_COUNTS = {status.lower(): 0 for status in vars(BookingStatus) if status.isupper()}


def _day(day: int, *, month: int = 4) -> datetime:
    """9 am Singapore time on a day in 2029."""
    return datetime(2029, month, day, 1, 0, tzinfo=UTC)


def _request(
    db: Session,
    *,
    event_name: str,
    starts_at: datetime,
    venue_id: uuid.UUID = Venues.BOARDROOM,
    status: str = BookingStatus.PENDING,
    **extra,
) -> VenueBooking:
    """A booking request for an event of its own, both two hours long. Events with one name are
    told apart by their dates (``uq_events_organiser_name_dates``)."""
    ends_at = starts_at + timedelta(hours=2)
    event = make_event(
        db, status=EventStatus.PLANNING, name=event_name, starts_at=starts_at, ends_at=ends_at
    )
    return make_booking(
        db,
        event_id=event.id,
        venue_id=venue_id,
        starts_at=starts_at,
        ends_at=ends_at,
        status=status,
        **extra,
    )


def _queue(client, **params: str | int) -> dict:
    response = client.get(BOOKINGS_PATH, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(client, **params: str | int) -> list[str]:
    return [row["id"] for row in _queue(client, **params)["items"]]


def _id(booking: VenueBooking) -> str:
    return str(booking.id)


def _tied_id(n: int) -> uuid.UUID:
    """A fixed id, so requests that tie can be given ids in the opposite order to their dates."""
    return uuid.UUID(f"13300000-0000-0000-0000-{n:012d}")


# --- AC1: the search applies within the open tab --------------------------------------------------
@pytest.mark.story("13.3", ac=1)
def test_a_search_lists_only_the_open_tabs_matching_requests(venue_staff_client, db):
    pending = _request(db, event_name=f"{TOKEN} Gala", starts_at=_day(1))
    approved = _request(
        db, event_name=f"{TOKEN} Ball", starts_at=_day(2), status=BookingStatus.APPROVED
    )
    _request(db, event_name="Plain Gala", starts_at=_day(3))

    assert _ids(venue_staff_client, status=BookingStatus.PENDING, search=TOKEN) == [_id(pending)]
    assert _ids(venue_staff_client, search=TOKEN) == [_id(pending), _id(approved)]


# --- AC2: what the search matches, and the tab counts ---------------------------------------------
@pytest.mark.story("13.3", ac=2)
@pytest.mark.parametrize("field", ["event name", "venue name", "submitted by"])
def test_each_searched_field_finds_a_request(venue_staff_client, db, field):
    venue = make_venue(db, name=f"{TOKEN} Loft" if field == "venue name" else "Plain Loft")
    requester = make_user(
        db,
        role="EVENT_COORDINATOR",
        full_name=f"Quinn {TOKEN}" if field == "submitted by" else "Quinn Plain",
    )
    booking = _request(
        db,
        event_name=f"{TOKEN} Gala" if field == "event name" else "Plain Gala",
        starts_at=_day(1),
        venue_id=venue.id,
        requested_by_id=requester.id,
    )

    assert _ids(venue_staff_client, search=TOKEN) == [_id(booking)]


@pytest.mark.story("13.3", ac=2)
@pytest.mark.parametrize("search", ["QUOKKAFEST", "quokkafest", "uokkaf"])
def test_the_search_ignores_capitals_and_matches_inside_a_word(venue_staff_client, db, search):
    booking = _request(db, event_name="Grand Quokkafest", starts_at=_day(1))

    assert _ids(venue_staff_client, search=search) == [_id(booking)]


@pytest.mark.story("13.3", ac=2)
@pytest.mark.parametrize("field", ["venue location", "requirement notes"])
def test_text_only_in_a_field_not_searched_matches_nothing(venue_staff_client, db, field):
    venue = make_venue(
        db, location=f"{TOKEN} Tower" if field == "venue location" else "Plain Tower"
    )
    _request(
        db,
        event_name="Plain Gala",
        starts_at=_day(1),
        venue_id=venue.id,
        requirement_notes=f"{TOKEN} staging" if field == "requirement notes" else None,
    )

    assert _ids(venue_staff_client, search=TOKEN) == []


@pytest.mark.story("13.3", ac=2)
def test_each_tabs_count_is_how_many_of_its_requests_match(venue_staff_client, db):
    _request(db, event_name=f"{TOKEN} One", starts_at=_day(1))
    _request(db, event_name=f"{TOKEN} Two", starts_at=_day(2))
    _request(db, event_name=f"{TOKEN} Three", starts_at=_day(3), status=BookingStatus.APPROVED)
    _request(db, event_name=f"{TOKEN} Four", starts_at=_day(4), status=BookingStatus.REJECTED)
    _request(db, event_name="Plain Five", starts_at=_day(5))

    body = _queue(venue_staff_client, status=BookingStatus.APPROVED, search=TOKEN)

    assert body["counts"] == {**NO_COUNTS, "pending": 2, "approved": 1, "rejected": 1}
    assert body["total"] == 1


# --- AC3: Order by --------------------------------------------------------------------------------
def _three_to_order(db: Session) -> dict[str, VenueBooking]:
    """Three requests that every order puts in a different sequence. Their names mix capitals, so
    a byte-wise order would differ from one that ignores them."""
    rows = {
        "A": ("QUOKKA Bravo", "Bravo Hall", _day(1), datetime(2026, 9, 1, tzinfo=UTC)),
        "B": ("Quokka alpha", "CHARLIE hall", _day(2), datetime(2026, 9, 3, tzinfo=UTC)),
        "C": ("quokka Charlie", "alpha hall", _day(3), datetime(2026, 9, 2, tzinfo=UTC)),
    }
    return {
        key: _request(
            db,
            event_name=event_name,
            starts_at=starts_at,
            venue_id=make_venue(db, name=venue_name).id,
            created_at=created_at,
        )
        for key, (event_name, venue_name, starts_at, created_at) in rows.items()
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
        ("venue_name", "CAB"),
    ],
)
def test_each_order_lists_the_requests_in_that_order(venue_staff_client, db, order, expected):
    bookings = _three_to_order(db)
    params = {"search": TOKEN} if order is None else {"search": TOKEN, "order": order}

    assert _ids(venue_staff_client, **params) == [_id(bookings[key]) for key in expected]


@pytest.mark.story("13.3", ac=3)
@pytest.mark.parametrize("order", ["event_name", "venue_name", "requested", "requested_desc"])
def test_requests_that_tie_stay_in_date_order_soonest_first(venue_staff_client, db, order):
    """The three tie on everything but their dates, and their ids run the other way, so only the
    date can put them soonest first."""
    raised_at = datetime(2026, 9, 1, tzinfo=UTC)
    latest, middle, soonest = (
        _request(
            db,
            event_name=f"{TOKEN} Tie",
            starts_at=_day(day),
            created_at=raised_at,
            id=_tied_id(n),
        )
        for n, day in [(1, 3), (2, 2), (3, 1)]
    )

    ids = _ids(venue_staff_client, search=TOKEN, order=order)

    assert ids == [_id(soonest), _id(middle), _id(latest)]


# --- AC4: searched and ordered across the whole tab, then paged -----------------------------------
@pytest.mark.story("13.3", ac=4)
def test_the_search_runs_over_the_whole_tab_before_it_is_paged(venue_staff_client, db):
    matches = [
        _request(db, event_name=f"{TOKEN} {day:02d}", starts_at=_day(day)) for day in range(1, 13)
    ]
    pending = {"status": BookingStatus.PENDING, "limit": QUEUE_PAGE_SIZE}

    # Dated after every seeded pending request, none is on the unsearched tab's first page.
    assert not {_id(b) for b in matches} & set(_ids(venue_staff_client, **pending))
    first = _queue(venue_staff_client, **pending, search=TOKEN)
    second = _queue(venue_staff_client, **pending, search=TOKEN, offset=QUEUE_PAGE_SIZE)

    assert [row["id"] for row in first["items"] + second["items"]] == [_id(b) for b in matches]
    assert first["total"] == second["total"] == len(matches)


@pytest.mark.story("13.3", ac=4)
def test_every_page_follows_one_order_with_no_request_repeated_or_skipped(venue_staff_client, db):
    """Twelve requests in four groups of three tied names, each group's ids against its dates, read
    five at a time in event-name order."""
    made = [
        _request(
            db,
            event_name=f"{TOKEN} {name}",
            starts_at=_day(day),
            id=_tied_id(100 - day),
        )
        for day, name in enumerate(["delta", "Bravo", "CHARLIE", "alpha"] * 3, start=1)
    ]
    expected = sorted(made, key=lambda b: (b.event.name.lower(), b.starts_at))

    walked: list[str] = []
    for offset in range(0, len(made), 5):
        walked += _ids(venue_staff_client, search=TOKEN, order="event_name", limit=5, offset=offset)

    assert walked == [_id(b) for b in expected]


# --- AC5: boundaries ------------------------------------------------------------------------------
@pytest.mark.story("13.3", ac=5)
def test_a_search_of_100_characters_is_accepted(venue_staff_client, db):
    name = f"{TOKEN} " + "x" * (SEARCH_MAX_LENGTH - len(TOKEN) - 1)
    booking = _request(db, event_name=name, starts_at=_day(1))

    assert len(name) == SEARCH_MAX_LENGTH
    assert _ids(venue_staff_client, search=name) == [_id(booking)]


@pytest.mark.story("13.3", ac=5)
def test_a_search_of_101_characters_is_refused(venue_staff_client):
    response = venue_staff_client.get(BOOKINGS_PATH, params={"search": "x" * 101})

    assert response.status_code == 422


@pytest.mark.story("13.3", ac=5)
def test_spaces_around_the_search_are_ignored(venue_staff_client, db):
    booking = _request(db, event_name=f"{TOKEN} Gala", starts_at=_day(1))

    assert _ids(venue_staff_client, search=f"   {TOKEN.lower()}  ") == [_id(booking)]


@pytest.mark.story("13.3", ac=5)
@pytest.mark.parametrize("search", ["", "   "])
def test_a_blank_or_spaces_only_search_lists_the_whole_tab(venue_staff_client, search):
    whole = _queue(venue_staff_client, status=BookingStatus.PENDING)

    assert _queue(venue_staff_client, status=BookingStatus.PENDING, search=search) == whole


@pytest.mark.story("13.3", ac=5)
@pytest.mark.parametrize("order", ["price", "event_name_desc", "DATE", "", "equipment_type"])
def test_an_order_the_list_does_not_offer_is_refused(venue_staff_client, order):
    response = venue_staff_client.get(BOOKINGS_PATH, params={"order": order})

    assert response.status_code == 422


# --- AC6: characters that are wildcards in SQL ----------------------------------------------------
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
    venue_staff_client, db, search, target, decoy
):
    """Each decoy is what the search would also find if its character were a LIKE wildcard, or
    the escape character LIKE was given."""
    found = _request(db, event_name=target, starts_at=_day(1))
    _request(db, event_name=decoy, starts_at=_day(2))

    assert _ids(venue_staff_client, search=search) == [_id(found)]


# --- AC8: who may search --------------------------------------------------------------------------
WITH_A_SEARCH = {"search": TOKEN, "order": "event_name"}


@pytest.mark.story("13.3", ac=8)
@pytest.mark.parametrize("params", [{}, WITH_A_SEARCH], ids=["without a search", "with a search"])
def test_a_signed_out_visitor_is_refused(client, params):
    assert client.get(BOOKINGS_PATH, params=params).status_code == 401


@pytest.mark.story("13.3", ac=8)
@pytest.mark.parametrize("params", [{}, WITH_A_SEARCH], ids=["without a search", "with a search"])
@pytest.mark.parametrize(
    "user",
    [
        Users.ORGANISER,
        Users.COORDINATOR,
        Users.LEAD,
        Users.TECH_SUPPORT,
        Users.SAFETY_OFFICER,
        Users.ATTENDEE,
    ],
)
def test_any_other_role_is_refused(client, user, params):
    client.login(user)

    assert client.get(BOOKINGS_PATH, params=params).status_code == 403


# --- AC9: each load as the requests stand ---------------------------------------------------------
@pytest.mark.story("13.3", ac=9)
def test_each_load_searches_the_requests_as_they_stand(venue_staff_client, db):
    decided = _request(db, event_name=f"{TOKEN} Alpha", starts_at=_day(1))
    kept = _request(db, event_name=f"{TOKEN} Charlie", starts_at=_day(3))
    pending = {"status": BookingStatus.PENDING, "search": TOKEN}
    assert _ids(venue_staff_client, **pending) == [_id(decided), _id(kept)]

    approve = venue_staff_client.post(
        f"{BOOKINGS_PATH}/{decided.id}/approve", json=approval_payload()
    )
    assert approve.status_code == 200, approve.text
    added = _request(db, event_name=f"{TOKEN} Bravo", starts_at=_day(2))
    body = _queue(venue_staff_client, **pending)

    assert [row["id"] for row in body["items"]] == [_id(added), _id(kept)]
    assert body["counts"] == {**NO_COUNTS, "pending": 2, "approved": 1}
