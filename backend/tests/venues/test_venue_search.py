"""Story 8.1 (Sprint 2, built as s8.1) - search and filter the venue catalogue: GET /venues/search.

AC1  Every venue in service is listed with its name, location and capacity.
AC2  Withdrawn venues only when asked for, and marked.
AC3  One filter panel: capacity, a period, name or location, facilities, accessibility features
     and room layout. Only venues matching every criterion and free for the whole period are
     listed - not booked or held (a pending or approved booking, the hold's rule from s12.1), not
     blocked (an unavailability period) and not closed at those hours (its opening hours). A venue
     that stops being available between two searches is gone from the second.
AC4  The search runs on the server: Coordinators, Venue Staff and Technical Support may search;
     nobody else.
AC6  Capacity equal to the minimum is included; one seat below is not. With a layout chosen, the
     capacity compared is that layout's.
AC7  A booking or closure ending exactly when the period starts does not exclude a venue; other
     bookings that day do not either.
AC8  A period may cover several days; both ends or neither; the end after the start; never in
     the past.
AC9  No results: the filters whose removal alone would give results, with how many, largest first.
AC10 Several facilities, or several accessibility features: all are required.

Every test makes its own venues under one unique tag and searches for that tag, so the seed
venues never interfere - except the unfiltered listing, which is the seed itself.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta, timezone

import pytest

from app.bookings.models import BookingStatus
from app.events.models import EventStatus
from app.venues.service import END_NOT_AFTER_START_MESSAGE
from tests.support.factories import make_booking, make_event, make_unavailability, make_venue
from tests.support.seed import Users, Venues

SGT = timezone(timedelta(hours=8))
OPEN_8_TO_6 = (time(8, 0), time(18, 0))


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    """A moment in March 2027, Singapore time: after today, and clear of every seeded booking."""
    return datetime(2027, 3, day, hour, minute, tzinfo=SGT)


def _tag() -> str:
    """A name part no seed venue has, shared by the venues one test makes."""
    return f"Search {uuid.uuid4().hex[:8]}"


def _period(starts_at: datetime, ends_at: datetime) -> dict[str, str]:
    return {"starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat()}


def _search(client, **params) -> dict:
    response = client.get("/venues/search", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _names(result: dict) -> list[str]:
    return [hit["name"] for hit in result["venues"]]


# --- AC1/AC2 ---------------------------------------------------------------------------------
@pytest.mark.story("8.1", ac=1)
@pytest.mark.story("8.1", ac=2)
def test_no_filters_lists_every_venue_in_service(coordinator_client):
    result = _search(coordinator_client)

    assert _names(result) == ["Boardroom 3.4", "Exhibition Foyer", "Grand Hall", "Seminar Room 2.1"]
    assert result["total"] == 4
    assert result["relax"] == []
    grand_hall = result["venues"][2]
    assert grand_hall == {
        "id": str(Venues.GRAND_HALL),
        "name": "Grand Hall",
        "location": "Tower A, Level 1",
        "capacity": 400,
        "status": "ACTIVE",
        "cover_image_url": None,
        "operating_hours_start": "08:00:00",
        "operating_hours_end": "22:00:00",
        "suitability": None,
    }

    with_withdrawn = _search(coordinator_client, include_withdrawn=True)

    assert _names(with_withdrawn) == [
        "Boardroom 3.4",
        "Exhibition Foyer",
        "Grand Hall",
        "Old Annex Room",
        "Seminar Room 2.1",
    ]
    assert with_withdrawn["total"] == 5
    assert with_withdrawn["venues"][3]["status"] == "WITHDRAWN"


# --- AC3: each filter ----------------------------------------------------------------------
# (params given the tag, venues expected). Alpha fits every narrowing below; Beta fits none.
NARROWING_CASES = {
    "capacity": (lambda tag: {"search": tag, "capacity": 50}, ["Alpha"]),
    "capacity_max": (lambda tag: {"search": tag, "capacity_max": 50}, ["Beta"]),
    "layout": (lambda tag: {"search": tag, "layout": "THEATRE"}, ["Alpha"]),
    "facility": (lambda tag: {"search": tag, "facility": "PROJECTOR"}, ["Alpha"]),
    "accessibility": (lambda tag: {"search": tag, "accessibility": "WHEELCHAIR_ACCESS"}, ["Alpha"]),
    "name": (lambda tag: {"search": f"{tag} beta"}, ["Beta"]),
    "location": (lambda tag: {"search": f"{tag} north"}, ["Alpha"]),
}


@pytest.mark.story("8.1", ac=3)
@pytest.mark.parametrize("case", NARROWING_CASES, ids=list(NARROWING_CASES))
def test_each_filter_narrows_the_results(coordinator_client, db, case):
    tag = _tag()
    make_venue(
        db,
        name=f"{tag} Alpha",
        location=f"{tag} North Wing",
        capacity=100,
        layouts={"THEATRE": None},
        facilities=("PROJECTOR",),
        accessibility=("WHEELCHAIR_ACCESS",),
    )
    make_venue(
        db,
        name=f"{tag} Beta",
        location=f"{tag} South Wing",
        capacity=30,
        layouts={"CLASSROOM": None},
    )
    params, expected = NARROWING_CASES[case]

    result = _search(coordinator_client, **params(tag))

    assert _names(result) == [f"{tag} {name}" for name in expected]


@pytest.mark.story("8.1", ac=3)
def test_every_filter_must_match(coordinator_client, db):
    tag = _tag()
    fits = {
        "capacity": 100,
        "layouts": {"THEATRE": None},
        "facilities": ("PROJECTOR",),
        "accessibility": ("WHEELCHAIR_ACCESS",),
        "hours": OPEN_8_TO_6,
    }
    make_venue(db, name=f"{tag} Match", **fits)
    make_venue(db, name=f"{tag} Too small", **{**fits, "capacity": 40})
    make_venue(db, name=f"{tag} Wrong layout", **{**fits, "layouts": {"BANQUET": None}})
    make_venue(db, name=f"{tag} No projector", **{**fits, "facilities": ()})
    make_venue(db, name=f"{tag} Not step-free", **{**fits, "accessibility": ()})
    make_venue(db, name=f"{tag} Closes early", **{**fits, "hours": (time(8, 0), time(11, 0))})
    blocked = make_venue(db, name=f"{tag} Blocked", **fits)
    make_unavailability(db, venue_id=blocked.id, starts_at=_at(1, 0), ends_at=_at(2, 0))

    result = _search(
        coordinator_client,
        search=tag,
        capacity=60,
        layout="THEATRE",
        facility="PROJECTOR",
        accessibility="WHEELCHAIR_ACCESS",
        **_period(_at(1, 9), _at(1, 12)),
    )

    assert _names(result) == [f"{tag} Match"]


# --- AC3: availability ----------------------------------------------------------------------
@pytest.mark.story("8.1", ac=3)
@pytest.mark.parametrize("status", [BookingStatus.APPROVED, BookingStatus.PENDING])
def test_a_booked_or_held_venue_is_left_out(coordinator_client, db, status):
    tag = _tag()
    taken = make_venue(db, name=f"{tag} Taken")
    make_venue(db, name=f"{tag} Free")
    make_booking(db, venue_id=taken.id, starts_at=_at(1, 10), ends_at=_at(1, 11), status=status)

    result = _search(coordinator_client, search=tag, **_period(_at(1, 9), _at(1, 12)))

    assert _names(result) == [f"{tag} Free"]


@pytest.mark.story("8.1", ac=3)
@pytest.mark.parametrize(
    "status", [BookingStatus.REJECTED, BookingStatus.WITHDRAWN, BookingStatus.CANCELLED]
)
def test_released_bookings_do_not_hide_a_venue(coordinator_client, db, status):
    tag = _tag()
    venue = make_venue(db, name=f"{tag} Released")
    make_booking(db, venue_id=venue.id, starts_at=_at(1, 10), ends_at=_at(1, 11), status=status)

    result = _search(coordinator_client, search=tag, **_period(_at(1, 9), _at(1, 12)))

    assert _names(result) == [f"{tag} Released"]


@pytest.mark.story("8.1", ac=3)
def test_a_blocked_venue_is_left_out(coordinator_client, db):
    tag = _tag()
    blocked = make_venue(db, name=f"{tag} Blocked")
    make_venue(db, name=f"{tag} Open")
    make_unavailability(db, venue_id=blocked.id, starts_at=_at(1, 0), ends_at=_at(3, 0))

    result = _search(coordinator_client, search=tag, **_period(_at(2, 9), _at(2, 12)))

    assert _names(result) == [f"{tag} Open"]


@pytest.mark.story("8.1", ac=3)
def test_a_venue_closed_at_those_hours_is_left_out(coordinator_client, db):
    tag = _tag()
    make_venue(db, name=f"{tag} Closes at six", hours=OPEN_8_TO_6)
    make_venue(db, name=f"{tag} Open late", hours=(time(8, 0), time(22, 0)))

    result = _search(coordinator_client, search=tag, **_period(_at(1, 17), _at(1, 19)))

    assert _names(result) == [f"{tag} Open late"]


@pytest.mark.story("8.1", ac=3)
def test_a_venue_without_recorded_hours_is_kept(coordinator_client, db):
    tag = _tag()
    make_venue(db, name=f"{tag} Hours unknown")

    result = _search(coordinator_client, search=tag, **_period(_at(1, 21), _at(1, 23)))

    assert _names(result) == [f"{tag} Hours unknown"]
    hit = result["venues"][0]
    assert hit["operating_hours_start"] is None
    assert hit["operating_hours_end"] is None


# --- AC6: capacity --------------------------------------------------------------------------
@pytest.mark.story("8.1", ac=6)
def test_capacity_limits_are_inclusive(coordinator_client, db):
    tag = _tag()
    for capacity in (49, 50, 51):
        make_venue(db, name=f"{tag} Seats {capacity}", capacity=capacity)

    at_least = _search(coordinator_client, search=tag, capacity=50)
    at_most = _search(coordinator_client, search=tag, capacity_max=50)
    exactly = _search(coordinator_client, search=tag, capacity=50, capacity_max=50)

    assert _names(at_least) == [f"{tag} Seats 50", f"{tag} Seats 51"]
    assert _names(at_most) == [f"{tag} Seats 49", f"{tag} Seats 50"]
    assert _names(exactly) == [f"{tag} Seats 50"]


@pytest.mark.story("8.1", ac=6)
def test_capacity_uses_the_chosen_layouts_capacity(coordinator_client, db):
    # Like Grand Hall: 400 as a theatre (no capacity of its own), 240 at banquet.
    tag = _tag()
    make_venue(db, name=f"{tag} Hall", capacity=400, layouts={"THEATRE": None, "BANQUET": 240})

    def found(**params) -> bool:
        return _names(_search(coordinator_client, search=tag, **params)) == [f"{tag} Hall"]

    assert not found(capacity=300, layout="BANQUET")
    assert found(capacity=240, layout="BANQUET")
    assert found(capacity=300, layout="THEATRE")
    assert found(capacity=400, layout="THEATRE")
    assert found(capacity_max=250, layout="BANQUET")
    assert not found(capacity_max=250, layout="THEATRE")
    assert not found(layout="CLASSROOM")


# --- AC7: touching periods ------------------------------------------------------------------
@pytest.mark.story("8.1", ac=7)
def test_touching_bookings_do_not_hide_a_venue(coordinator_client, db):
    tag = _tag()
    before = make_venue(db, name=f"{tag} Booked before")
    after = make_venue(db, name=f"{tag} Booked after")
    make_booking(db, venue_id=before.id, starts_at=_at(1, 8), ends_at=_at(1, 10), status="APPROVED")
    make_booking(db, venue_id=after.id, starts_at=_at(1, 12), ends_at=_at(1, 14))

    result = _search(coordinator_client, search=tag, **_period(_at(1, 10), _at(1, 12)))

    assert _names(result) == [f"{tag} Booked after", f"{tag} Booked before"]


@pytest.mark.story("8.1", ac=7)
def test_one_minute_of_overlap_hides_it(coordinator_client, db):
    tag = _tag()
    before = make_venue(db, name=f"{tag} Runs over")
    after = make_venue(db, name=f"{tag} Starts early")
    make_booking(db, venue_id=before.id, starts_at=_at(1, 8), ends_at=_at(1, 10, 1))
    make_booking(db, venue_id=after.id, starts_at=_at(1, 11, 59), ends_at=_at(1, 14))

    result = _search(coordinator_client, search=tag, **_period(_at(1, 10), _at(1, 12)))

    assert _names(result) == []


@pytest.mark.story("8.1", ac=7)
def test_other_bookings_that_day_do_not_hide_it(coordinator_client, db):
    tag = _tag()
    venue = make_venue(db, name=f"{tag} Busy day")
    make_booking(db, venue_id=venue.id, starts_at=_at(1, 8), ends_at=_at(1, 9), status="APPROVED")
    make_booking(db, venue_id=venue.id, starts_at=_at(1, 14), ends_at=_at(1, 16))

    result = _search(coordinator_client, search=tag, **_period(_at(1, 10), _at(1, 12)))

    assert _names(result) == [f"{tag} Busy day"]


@pytest.mark.story("8.1", ac=7)
def test_touching_unavailability_does_not_hide_a_venue(coordinator_client, db):
    tag = _tag()
    venue = make_venue(db, name=f"{tag} Serviced around it")
    make_unavailability(db, venue_id=venue.id, starts_at=_at(1, 0), ends_at=_at(1, 10))
    make_unavailability(db, venue_id=venue.id, starts_at=_at(1, 12), ends_at=_at(2, 0))

    result = _search(coordinator_client, search=tag, **_period(_at(1, 10), _at(1, 12)))

    assert _names(result) == [f"{tag} Serviced around it"]


# --- AC3: opening hours ---------------------------------------------------------------------
HOURS_CASES = {
    # A period from opening to closing fits; a minute outside either end does not.
    "opening to closing": (OPEN_8_TO_6, _at(1, 8), _at(1, 18), True),
    "a minute before opening": (OPEN_8_TO_6, _at(1, 7, 59), _at(1, 12), False),
    "a minute after closing": (OPEN_8_TO_6, _at(1, 12), _at(1, 18, 1), False),
    # Several days are daily sessions from the start time to the end time.
    "several days of daily sessions": (OPEN_8_TO_6, _at(1, 9), _at(3, 17), True),
    # An end time before the start time passes midnight, which no recorded hours cover - even
    # hours that cover both times.
    "past midnight": ((time(0, 0), time(23, 59)), _at(1, 17), _at(2, 9), False),
}


@pytest.mark.story("8.1", ac=3)
@pytest.mark.parametrize("case", HOURS_CASES, ids=list(HOURS_CASES))
def test_opening_hours_boundaries(coordinator_client, db, case):
    hours, starts_at, ends_at, is_open = HOURS_CASES[case]
    tag = _tag()
    make_venue(db, name=f"{tag} Hours", hours=hours)

    result = _search(coordinator_client, search=tag, **_period(starts_at, ends_at))

    assert _names(result) == ([f"{tag} Hours"] if is_open else [])


# --- AC8: the period ------------------------------------------------------------------------
@pytest.mark.story("8.1", ac=8)
def test_a_search_can_cover_several_days(coordinator_client, db):
    tag = _tag()
    make_venue(db, name=f"{tag} Free all week")
    busy = make_venue(db, name=f"{tag} Busy midweek")
    make_booking(db, venue_id=busy.id, starts_at=_at(2, 10), ends_at=_at(2, 11))

    result = _search(coordinator_client, search=tag, **_period(_at(1, 9), _at(3, 17)))

    assert _names(result) == [f"{tag} Free all week"]


def _past_period() -> dict[str, str]:
    now = datetime.now(UTC)
    return _period(now - timedelta(days=1), now + timedelta(days=1))


INVALID_SEARCHES = {
    "one date only": (
        lambda: {"starts_at": _at(1, 9).isoformat()},
        "Choose both a start and an end, or neither.",
    ),
    "end not after start": (lambda: _period(_at(1, 9), _at(1, 9)), END_NOT_AFTER_START_MESSAGE),
    "start in the past": (_past_period, "Searches cannot start in the past."),
    "capacity to below capacity from": (
        lambda: {"capacity": 50, "capacity_max": 40},
        "Capacity to must not be below capacity from.",
    ),
}


@pytest.mark.story("8.1", ac=8)
@pytest.mark.parametrize("case", INVALID_SEARCHES, ids=list(INVALID_SEARCHES))
def test_invalid_searches_are_refused(coordinator_client, case):
    params, message = INVALID_SEARCHES[case]

    response = coordinator_client.get("/venues/search", params=params())

    assert response.status_code == 422
    assert response.json()["detail"] == message


# --- AC9: nothing matches -------------------------------------------------------------------
@pytest.mark.story("8.1", ac=9)
def test_no_results_suggests_which_filter_to_relax(coordinator_client, db):
    tag = _tag()
    # The only theatre is booked; two banquet halls are free. No seed venue seats 450.
    hall = make_venue(
        db, name=f"{tag} Hall", capacity=500, layouts={"THEATRE": None}, facilities=("PROJECTOR",)
    )
    make_booking(db, venue_id=hall.id, starts_at=_at(1, 9), ends_at=_at(1, 18), status="APPROVED")
    for name in ("Banquet One", "Banquet Two"):
        make_venue(
            db,
            name=f"{tag} {name}",
            capacity=600,
            layouts={"BANQUET": None},
            facilities=("PROJECTOR",),
        )

    result = _search(
        coordinator_client,
        search=tag,
        capacity=450,
        layout="THEATRE",
        facility="PROJECTOR",
        **_period(_at(1, 10), _at(1, 12)),
    )

    assert result["venues"] == []
    # Without the layout, both banquet halls fit; without the dates, the booked theatre does.
    # Removing the name, the capacity or the facility alone still leaves nothing.
    assert result["relax"] == [
        {"filter": "layout", "label": "Layout", "count": 2},
        {"filter": "dates", "label": "Dates", "count": 1},
    ]


@pytest.mark.story("8.1", ac=9)
def test_no_suggestions_without_filters_or_with_results(coordinator_client, db):
    tag = _tag()
    make_venue(db, name=f"{tag} Room", capacity=20)

    assert _search(coordinator_client)["relax"] == []
    assert _search(coordinator_client, search=tag, capacity=10)["relax"] == []


# --- AC10: several of a kind ----------------------------------------------------------------
@pytest.mark.story("8.1", ac=10)
def test_several_facilities_are_all_required(coordinator_client, db):
    tag = _tag()
    make_venue(db, name=f"{tag} Both", facilities=("PROJECTOR", "WIFI"))
    make_venue(db, name=f"{tag} Projector only", facilities=("PROJECTOR",))

    result = _search(coordinator_client, search=tag, facility=["PROJECTOR", "WIFI"])

    assert _names(result) == [f"{tag} Both"]


@pytest.mark.story("8.1", ac=10)
def test_several_accessibility_features_are_all_required(coordinator_client, db):
    tag = _tag()
    make_venue(db, name=f"{tag} Both", accessibility=("WHEELCHAIR_ACCESS", "HEARING_LOOP"))
    make_venue(db, name=f"{tag} Loop only", accessibility=("HEARING_LOOP",))

    result = _search(
        coordinator_client, search=tag, accessibility=["WHEELCHAIR_ACCESS", "HEARING_LOOP"]
    )

    assert _names(result) == [f"{tag} Both"]


# --- AC3: what the filters accept -----------------------------------------------------------
@pytest.mark.story("8.1", ac=3)
def test_unknown_codes_are_refused(coordinator_client):
    refusals = {
        "Unknown layout code(s): HOLODECK": {"layout": "HOLODECK"},
        "Unknown facility code(s): TELEPORTER": {"facility": ["PROJECTOR", "TELEPORTER"]},
        "Unknown accessibility feature code(s): RAMP_TO_SPACE": {"accessibility": "RAMP_TO_SPACE"},
    }
    for message, params in refusals.items():
        response = coordinator_client.get("/venues/search", params=params)

        assert response.status_code == 422, params
        assert response.json()["detail"] == message


@pytest.mark.story("8.1", ac=3)
def test_search_text_is_literal_and_case_insensitive(coordinator_client, db):
    tag = _tag()
    for name in ("100% Room", "1000 Room", "A_B Room", "AXB Room"):
        make_venue(db, name=f"{tag} {name}")

    percent = _search(coordinator_client, search=f"{tag} 100%")
    underscore = _search(coordinator_client, search=f"{tag.upper()} a_b")

    assert _names(percent) == [f"{tag} 100% Room"]
    assert _names(underscore) == [f"{tag} A_B Room"]


# --- AC4: who may search --------------------------------------------------------------------
@pytest.mark.story("8.1", ac=4)
@pytest.mark.parametrize("user", [Users.COORDINATOR, Users.VENUE_STAFF, Users.TECH_SUPPORT])
def test_internal_roles_can_search(login_as, user):
    client = login_as(user)

    assert "Grand Hall" in _names(_search(client, capacity=300))


@pytest.mark.story("8.1", ac=4)
@pytest.mark.parametrize("user", [Users.ORGANISER, Users.ATTENDEE])
def test_other_roles_cannot_search(login_as, user):
    assert login_as(user).get("/venues/search").status_code == 403


@pytest.mark.story("8.1", ac=4)
def test_signed_out_visitors_cannot_search(client):
    assert client.get("/venues/search").status_code == 401


# --- AC3: availability changes between searches ---------------------------------------------
@pytest.mark.story("8.1", ac=3)
def test_a_venue_held_after_a_search_is_gone_from_the_next(coordinator_client, db):
    tag = _tag()
    venue = make_venue(db, name=f"{tag} In demand")
    event = make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=_at(1, 9),
        ends_at=_at(1, 12),
    )
    search = {"search": tag, **_period(_at(1, 9), _at(1, 12))}
    assert _names(_search(coordinator_client, **search)) == [f"{tag} In demand"]

    requested = coordinator_client.post(
        "/bookings", json={"event_id": str(event.id), "venue_id": str(venue.id)}
    )
    assert requested.status_code == 201, requested.text

    assert _names(_search(coordinator_client, **search)) == []
