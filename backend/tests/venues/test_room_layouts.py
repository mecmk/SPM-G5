"""Story 8.6 - manage the room layouts venues can offer.

As a Venue Staff member I want to add, edit and delete the room layouts our venues can offer so
that venue records, event requests and venue searches only use layouts we actually support.

AC1  Venue Staff open a Room layouts page that lists every room layout with its name and
     description. The list starts with seven standard layouts: Theatre, Classroom, Boardroom,
     U-shape, Banquet, Exhibition and Standing / reception (the customer left the choice to the
     team, Q26). These come first, in that order, then any added layouts from A to Z.
AC2  Venue Staff add a layout by giving it a name and a description. The new layout is offered
     the next time anyone opens a venue's form (8.3), an event's venue requirements (2.7) or the
     venue catalogue's layout filter (8.1).
AC3  Venue Staff can change a layout's name or description. The new name shows wherever the
     layout appears, including on the venues, venue requirements and booking requests that
     already use it. Past safety reviews keep the name they recorded.
AC4  Venue Staff can delete a layout that no venue, venue requirement or booking request uses,
     after confirming. It is then no longer offered anywhere.
AC5  A layout's name is required and can be at most 100 characters. The name box is marked with
     an asterisk (*), stops taking text at 100 characters, and shows how many are used, for
     example "7 of 100 characters". Spaces at the start and end are removed before saving, so a
     name of only spaces counts as empty.
AC6  No two layouts can have the same name, ignoring capitals: while "Theatre" exists, "theatre"
     is refused. This applies to adding and to renaming. Changing only the capitals of a
     layout's own name is allowed.
AC7  A layout's description is also required, when adding and when changing a layout, and can be
     at most 500 characters. Like the name box, the description box is marked with an asterisk
     (*), stops taking text at 500 characters, and shows how many are used, for example "28 of
     500 characters". Spaces at the start and end are removed before saving, so a description of
     only spaces counts as empty.
AC8  A layout that any venue, venue requirement or booking request uses cannot be deleted.
     Booking requests count whatever their status, since they keep their record. The message
     says which of these use the layout, and it can still be renamed.
AC9  Only Venue Staff can add, change or delete layouts. Event Coordinators, the Event
     Coordinator Lead, Technical Support Staff and Safety Officers can open the Room layouts page
     and see the list, without Add, Edit or Delete. Event Organisers see layouts only as choices
     in their venue requirements (2.7). The server refuses a change from anyone but Venue Staff,
     including one sent outside the app.
AC10 If two Venue Staff save the same name at the same moment, whether adding or renaming, only
     one is saved; the other is told the name is already in use.
AC11 If a layout is deleted while a venue's form is open with that layout ticked, saving the
     venue is refused with a message naming the layout, and the venue is left unchanged.
AC12 If a layout is deleted while another Venue Staff member is changing or deleting it, their
     save or delete is refused with a message that the layout no longer exists, and their list
     refreshes.

The page, its dialogs, the boxes' asterisks, limits and counts (AC5, AC7), the confirmation before
a delete (AC4) and the list refreshing (AC12) are e2e cases: tests/e2e/room-layouts.spec.ts.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.common.audit import AuditLog
from app.dbtool import migrate
from app.events.models import EventStatus
from app.safety.models import EventSafetyReview
from app.venues import schemas as venue_schemas
from app.venues import service
from app.venues.models import DeletedRoomLayout, RoomLayout, Venue
from tests.support.factories import (
    create_event_request,
    make_booking,
    make_event,
    make_venue,
    make_venue_requirement,
    venue_payload,
)
from tests.support.seed import SafetyReviews, Users, Venues

STANDARD_LAYOUTS = [
    ("THEATRE", "Theatre"),
    ("CLASSROOM", "Classroom"),
    ("BOARDROOM", "Boardroom"),
    ("U_SHAPE", "U-shape"),
    ("BANQUET", "Banquet"),
    ("EXHIBITION", "Exhibition"),
    ("STANDING", "Standing / reception"),
]
NOT_FOUND = "This room layout no longer exists."
NAME_REQUIRED = "Enter the layout's name."
NAME_TOO_LONG = "A layout's name must be 100 characters or fewer."
DESCRIPTION_REQUIRED = "Enter the layout's description."
DESCRIPTION_TOO_LONG = "A layout's description must be 500 characters or fewer."
THEATRE_DESCRIPTION = "Rows of chairs facing the front; highest capacity."
# The description a test's layout gets when the test is not about it (AC7: one is required).
_DESCRIPTION = "Round tables facing a stage."
# Event times for the uses a test makes; any free period of a fresh venue will do.
_STARTS_AT = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
_ENDS_AT = datetime(2026, 12, 1, 17, 0, tzinfo=UTC)


def _add(client, name: str | None, description: str = _DESCRIPTION):
    return client.post("/venues/layouts", json={"name": name, "description": description})


def _added(client, name: str, description: str = _DESCRIPTION) -> dict:
    response = _add(client, name, description)
    assert response.status_code == 201, response.text
    return response.json()


def _layouts(client) -> list[dict]:
    response = client.get("/venues/layouts")
    assert response.status_code == 200, response.text
    return response.json()


def _names(client) -> list[str]:
    return [layout["name"] for layout in _layouts(client)]


def _audit(db: Session, action: str) -> list[AuditLog]:
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action)))


# --- AC1: the list ----------------------------------------------------------------------------
@pytest.mark.story("8.6", ac=1)
def test_the_list_starts_with_the_seven_standard_layouts_in_their_order(venue_staff_client):
    layouts = _layouts(venue_staff_client)

    assert [(layout["code"], layout["name"]) for layout in layouts] == STANDARD_LAYOUTS
    assert layouts[0] == {
        "code": "THEATRE",
        "name": "Theatre",
        "description": "Rows of chairs facing the front; highest capacity.",
    }


@pytest.mark.story("8.6", ac=1)
def test_added_layouts_follow_the_standard_ones_from_a_to_z(venue_staff_client):
    for name in ("Zigzag rows", "amphitheatre", "Cabaret"):
        _added(venue_staff_client, name)

    assert _names(venue_staff_client)[7:] == ["amphitheatre", "Cabaret", "Zigzag rows"]


@pytest.mark.story("8.6", ac=1)
def test_an_accented_name_sorts_with_its_letter(venue_staff_client):
    for name in ("Fishbowl", "Élan lounge", "dais"):
        _added(venue_staff_client, name)

    assert _names(venue_staff_client)[7:] == ["dais", "Élan lounge", "Fishbowl"]


# --- AC2: adding ------------------------------------------------------------------------------
@pytest.mark.story("8.6", ac=2)
def test_venue_staff_add_a_layout_with_a_description(venue_staff_client):
    response = _add(venue_staff_client, "Cabaret", "Round tables facing a stage.")

    assert response.status_code == 201, response.text
    assert response.json() == {
        "code": "CABARET",
        "name": "Cabaret",
        "description": "Round tables facing a stage.",
    }
    assert _layouts(venue_staff_client)[-1] == response.json()


@pytest.mark.story("8.6", ac=2)
@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("Hollow square", "HOLLOW_SQUARE"),
        ("Café style", "CAFE_STYLE"),
        ("Classroom / U", "CLASSROOM_U"),
        ("  Fish-bowl  ", "FISH_BOWL"),
        ("★ ★", "LAYOUT"),
    ],
)
def test_a_new_layouts_code_is_made_from_its_name(venue_staff_client, name, code):
    assert _added(venue_staff_client, name)["code"] == code


@pytest.mark.story("8.6", ac=2)
def test_a_code_already_taken_gets_the_next_free_number(venue_staff_client):
    """ "U shape" is not "U-shape", but both make the code U_SHAPE. A rename keeps the code, so
    "Theatre" is free again once the standard Theatre is renamed, but its code is not."""
    renamed = venue_staff_client.patch("/venues/layouts/THEATRE", json={"name": "Lecture theatre"})
    assert renamed.status_code == 200, renamed.text

    assert _added(venue_staff_client, "U shape")["code"] == "U_SHAPE_2"
    assert _added(venue_staff_client, "Theatre")["code"] == "THEATRE_2"
    assert _added(venue_staff_client, "Theatre!")["code"] == "THEATRE_3"


@pytest.mark.story("8.6", ac=2)
@pytest.mark.story("8.6", ac=4)
def test_a_deleted_layouts_code_is_never_given_to_a_new_layout(venue_staff_client):
    """A code stands for one layout for good, so what kept a deleted layout's code (a pending
    change request, a saved catalogue link, the audit log) is never taken for a new layout of the
    same name. The same holds for a standard layout's code."""
    _added(venue_staff_client, "Cabaret")
    assert venue_staff_client.delete("/venues/layouts/CABARET").status_code == 204
    assert venue_staff_client.delete("/venues/layouts/U_SHAPE").status_code == 204

    assert _added(venue_staff_client, "Cabaret")["code"] == "CABARET_2"
    assert _added(venue_staff_client, "U-shape")["code"] == "U_SHAPE_2"


@pytest.mark.story("8.6", ac=2)
def test_a_new_layout_is_offered_on_the_venue_form_and_the_request_form(login_as):
    client = login_as(Users.VENUE_STAFF)
    _added(client, "Cabaret")
    venue_form = client.get("/venues/reference-data")
    client.logout()
    request_form = login_as(Users.ORGANISER).get("/events/reference-data")

    assert ("CABARET", "Cabaret") in [(x["code"], x["name"]) for x in venue_form.json()["layouts"]]
    assert ("CABARET", "Cabaret") in [
        (x["code"], x["name"]) for x in request_form.json()["layouts"]
    ]


@pytest.mark.story("8.6", ac=1)
@pytest.mark.story("8.6", ac=2)
def test_every_pick_list_offers_the_layouts_in_the_pages_order(login_as):
    """The venue form and the catalogue filter (/venues/reference-data), and an event's venue
    requirements and its change requests (/events/reference-data), list the layouts as the page
    does: from A to Z ignoring capitals, also after a rename, which keeps the code (ZIGZAG is
    "Aardvark" here)."""
    client = login_as(Users.VENUE_STAFF)
    for name in ("Cabaret", "Zigzag", "amphitheatre"):
        _added(client, name)
    renamed = client.patch("/venues/layouts/ZIGZAG", json={"name": "Aardvark"})
    assert renamed.status_code == 200, renamed.text
    expected = [code for code, _name in STANDARD_LAYOUTS] + ["ZIGZAG", "AMPHITHEATRE", "CABARET"]

    page = [layout["code"] for layout in _layouts(client)]
    venue_form = [x["code"] for x in client.get("/venues/reference-data").json()["layouts"]]
    client.logout()
    request_form = login_as(Users.ORGANISER).get("/events/reference-data").json()["layouts"]

    assert page == expected
    assert venue_form == expected
    assert [x["code"] for x in request_form] == expected


@pytest.mark.story("8.6", ac=2)
def test_a_new_layout_can_be_saved_on_a_venue(venue_staff_client):
    _added(venue_staff_client, "Cabaret")

    response = venue_staff_client.post(
        "/venues", json=venue_payload(layouts=[{"code": "CABARET", "layout_capacity": 60}])
    )

    assert response.status_code == 201, response.text
    assert response.json()["layouts"] == [
        {"code": "CABARET", "name": "Cabaret", "layout_capacity": 60}
    ]


@pytest.mark.story("8.6", ac=2)
def test_a_new_layout_can_be_chosen_for_a_venue_requirement(login_as):
    _added(login_as(Users.VENUE_STAFF), "Cabaret")
    client = login_as(Users.ORGANISER)

    draft = create_event_request(
        client, venue_requirements=[{"name": "Main venue", "layout_code": "CABARET"}]
    )

    requirement = draft["venue_requirements"][0]
    assert (requirement["layout_code"], requirement["layout_name"]) == ("CABARET", "Cabaret")


@pytest.mark.story("8.6", ac=2)
def test_the_catalogue_filters_by_a_new_layout(venue_staff_client, db):
    _added(venue_staff_client, "Cabaret")
    tag = uuid.uuid4().hex[:8]
    make_venue(db, name=f"{tag} Supper Club", layouts={"CABARET": None})
    make_venue(db, name=f"{tag} Lecture Room", layouts={"THEATRE": None})

    response = venue_staff_client.get("/venues/search", params={"search": tag, "layout": "CABARET"})

    assert response.status_code == 200, response.text
    assert [venue["name"] for venue in response.json()["venues"]] == [f"{tag} Supper Club"]


@pytest.mark.story("8.6", ac=2)
def test_adding_a_layout_is_audited(venue_staff_client, db):
    _added(venue_staff_client, "Cabaret", "Round tables facing a stage.")

    [entry] = _audit(db, "ROOM_LAYOUT_CREATED")
    assert entry.actor_id == Users.VENUE_STAFF.id
    assert entry.entity_type == "room_layout"
    assert entry.details == {
        "code": "CABARET",
        "name": "Cabaret",
        "description": "Round tables facing a stage.",
    }


# --- AC3: changing a layout -------------------------------------------------------------------
@pytest.mark.story("8.6", ac=3)
def test_a_rename_shows_on_the_venues_requirements_and_booking_requests_using_it(
    venue_staff_client, db
):
    _added(venue_staff_client, "Cabaret")
    venue = make_venue(db, layouts={"CABARET": None})
    event = make_event(db, status=EventStatus.PLANNING)
    make_venue_requirement(db, event.id, layout_code="CABARET")
    booking = make_booking(
        db,
        venue_id=venue.id,
        event_id=event.id,
        starts_at=_STARTS_AT,
        ends_at=_ENDS_AT,
        required_layout_code="CABARET",
    )

    response = venue_staff_client.patch(
        "/venues/layouts/CABARET", json={"name": "Supper club", "description": "Dinner seating."}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "code": "CABARET",
        "name": "Supper club",
        "description": "Dinner seating.",
    }
    venue_layouts = venue_staff_client.get(f"/venues/{venue.id}").json()["layouts"]
    assert [layout["name"] for layout in venue_layouts] == ["Supper club"]
    requirements = venue_staff_client.get(f"/events/{event.id}").json()["venue_requirements"]
    assert [requirement["layout_name"] for requirement in requirements] == ["Supper club"]
    queue = venue_staff_client.get("/bookings", params={"status": "PENDING", "limit": 100}).json()
    [entry] = [item for item in queue["items"] if item["id"] == str(booking.id)]
    assert entry["required_layout_name"] == "Supper club"


@pytest.mark.story("8.6", ac=3)
def test_past_safety_reviews_keep_the_name_they_recorded(venue_staff_client, db):
    """The Riverside Book Fair's earlier review saw Grand Hall in the Exhibition layout."""
    response = venue_staff_client.patch("/venues/layouts/EXHIBITION", json={"name": "Open floor"})
    assert response.status_code == 200, response.text

    review = db.get(EventSafetyReview, SafetyReviews.BOOK_FAIR_CHANGES)
    db.refresh(review)
    assert review.facts["venues"][0]["layout_name"] == "Exhibition"
    grand_hall = venue_staff_client.get(f"/venues/{Venues.GRAND_HALL}").json()
    assert "Open floor" in [layout["name"] for layout in grand_hall["layouts"]]


@pytest.mark.story("8.6", ac=3)
def test_changing_only_the_description_keeps_the_name(venue_staff_client):
    response = venue_staff_client.patch(
        "/venues/layouts/THEATRE", json={"description": "Rows facing a stage."}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "code": "THEATRE",
        "name": "Theatre",
        "description": "Rows facing a stage.",
    }


@pytest.mark.story("8.6", ac=3)
def test_changing_a_layout_is_audited_with_its_old_and_new_values(venue_staff_client, db):
    venue_staff_client.patch(
        "/venues/layouts/THEATRE", json={"name": "Lecture theatre", "description": "Tiered."}
    )

    [entry] = _audit(db, "ROOM_LAYOUT_UPDATED")
    assert entry.actor_id == Users.VENUE_STAFF.id
    assert entry.entity_type == "room_layout"
    assert entry.details == {
        "code": "THEATRE",
        "name": {"from": "Theatre", "to": "Lecture theatre"},
        "description": {
            "from": "Rows of chairs facing the front; highest capacity.",
            "to": "Tiered.",
        },
    }


@pytest.mark.story("8.6", ac=3)
def test_saving_a_layout_unchanged_records_nothing(venue_staff_client, db):
    response = venue_staff_client.patch(
        "/venues/layouts/THEATRE",
        json={
            "name": "Theatre",
            "description": "Rows of chairs facing the front; highest capacity.",
        },
    )

    assert response.status_code == 200, response.text
    assert _audit(db, "ROOM_LAYOUT_UPDATED") == []


@pytest.mark.story("8.6", ac=3)
def test_rerunning_the_seed_keeps_the_changes_made_in_the_app(venue_staff_client, db):
    """``npm run db:ready`` re-runs the seed. It must neither undo a rename nor fail on the
    unique name now that a new layout holds the standard Theatre's old name."""
    venue_staff_client.patch("/venues/layouts/THEATRE", json={"name": "Lecture theatre"})
    _added(venue_staff_client, "Theatre")

    conn = db.connection()
    for seed_file in migrate.list_seeds():
        conn.exec_driver_sql(seed_file.read())

    layouts = {(layout["code"], layout["name"]) for layout in _layouts(venue_staff_client)}
    assert {("THEATRE", "Lecture theatre"), ("THEATRE_2", "Theatre")} <= layouts


# --- AC4: deleting ----------------------------------------------------------------------------
@pytest.mark.story("8.6", ac=4)
def test_venue_staff_delete_a_layout_nothing_uses(login_as):
    client = login_as(Users.VENUE_STAFF)

    response = client.delete("/venues/layouts/U_SHAPE")

    assert response.status_code == 204, response.text
    assert "U-shape" not in _names(client)
    assert "U_SHAPE" not in [
        x["code"] for x in client.get("/venues/reference-data").json()["layouts"]
    ]
    client.logout()
    request_form = login_as(Users.ORGANISER).get("/events/reference-data").json()
    assert "U_SHAPE" not in [x["code"] for x in request_form["layouts"]]


@pytest.mark.story("8.6", ac=4)
def test_deleting_a_layout_is_audited(venue_staff_client, db):
    venue_staff_client.delete("/venues/layouts/U_SHAPE")

    [entry] = _audit(db, "ROOM_LAYOUT_DELETED")
    assert entry.actor_id == Users.VENUE_STAFF.id
    assert entry.entity_type == "room_layout"
    assert entry.details == {"code": "U_SHAPE", "name": "U-shape"}


@pytest.mark.story("8.6", ac=4)
def test_rerunning_the_seed_does_not_bring_back_a_deleted_layout(venue_staff_client, db):
    """``npm run db:ready`` re-runs the seed, which adds the standard layouts. One Venue Staff
    deleted stays deleted, so it is offered nowhere, and its code is never used again."""
    assert venue_staff_client.delete("/venues/layouts/U_SHAPE").status_code == 204

    conn = db.connection()
    for seed_file in migrate.list_seeds():
        conn.exec_driver_sql(seed_file.read())

    assert "U_SHAPE" not in [layout["code"] for layout in _layouts(venue_staff_client)]


# --- AC5: the name ----------------------------------------------------------------------------
@pytest.mark.story("8.6", ac=5)
@pytest.mark.parametrize("body", [{}, {"name": None}, {"name": ""}, {"name": "   "}])
def test_a_new_layout_needs_a_name(venue_staff_client, body):
    response = venue_staff_client.post("/venues/layouts", json=body)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == NAME_REQUIRED
    assert len(_layouts(venue_staff_client)) == len(STANDARD_LAYOUTS)


@pytest.mark.story("8.6", ac=5)
@pytest.mark.parametrize("name", [None, "", "   "])
def test_a_layout_cannot_be_renamed_to_nothing(venue_staff_client, name):
    response = venue_staff_client.patch("/venues/layouts/THEATRE", json={"name": name})

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == NAME_REQUIRED
    assert _names(venue_staff_client)[0] == "Theatre"


@pytest.mark.story("8.6", ac=5)
def test_spaces_around_a_name_are_removed(venue_staff_client):
    assert _added(venue_staff_client, "  Cabaret  ")["name"] == "Cabaret"
    renamed = venue_staff_client.patch("/venues/layouts/CABARET", json={"name": " Supper club "})
    assert renamed.json()["name"] == "Supper club"


@pytest.mark.story("8.6", ac=5)
def test_a_name_may_have_100_characters_but_not_101(venue_staff_client):
    longest = "A" * 100

    assert _add(venue_staff_client, f"  {longest}  ").status_code == 201
    too_long = _add(venue_staff_client, "B" * 101)
    assert too_long.status_code == 422, too_long.text
    assert too_long.json()["detail"] == NAME_TOO_LONG
    renamed = venue_staff_client.patch("/venues/layouts/THEATRE", json={"name": "C" * 100})
    assert renamed.status_code == 200, renamed.text
    refused = venue_staff_client.patch("/venues/layouts/THEATRE", json={"name": "D" * 101})
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == NAME_TOO_LONG
    assert "B" * 101 not in _names(venue_staff_client)
    assert "C" * 100 in _names(venue_staff_client)


# --- AC6: unique names ------------------------------------------------------------------------
@pytest.mark.story("8.6", ac=6)
@pytest.mark.parametrize("name", ["Theatre", "theatre", "THEATRE", "  tHeAtRe  "])
def test_a_name_in_use_is_refused_whatever_its_capitals(venue_staff_client, name):
    response = _add(venue_staff_client, name)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == 'A room layout named "Theatre" already exists.'
    assert len(_layouts(venue_staff_client)) == len(STANDARD_LAYOUTS)


@pytest.mark.story("8.6", ac=6)
def test_a_layout_cannot_be_renamed_to_another_layouts_name(venue_staff_client):
    response = venue_staff_client.patch("/venues/layouts/CLASSROOM", json={"name": "theatre"})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == 'A room layout named "Theatre" already exists.'
    assert _names(venue_staff_client)[:2] == ["Theatre", "Classroom"]


@pytest.mark.story("8.6", ac=6)
@pytest.mark.parametrize("name", ["U-Shape", "U-shape"])
def test_a_layout_can_change_the_capitals_of_its_own_name(venue_staff_client, name):
    response = venue_staff_client.patch("/venues/layouts/U_SHAPE", json={"name": name})

    assert response.status_code == 200, response.text
    assert response.json()["name"] == name


# --- AC7: the description ---------------------------------------------------------------------
@pytest.mark.story("8.6", ac=7)
def test_a_description_may_have_500_characters_but_not_501(venue_staff_client):
    assert _add(venue_staff_client, "Cabaret", "A" * 500).status_code == 201
    too_long = _add(venue_staff_client, "Supper club", "B" * 501)
    assert too_long.status_code == 422, too_long.text
    assert too_long.json()["detail"] == DESCRIPTION_TOO_LONG
    refused = venue_staff_client.patch("/venues/layouts/THEATRE", json={"description": "C" * 501})
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == DESCRIPTION_TOO_LONG
    assert "Supper club" not in _names(venue_staff_client)


@pytest.mark.story("8.6", ac=7)
@pytest.mark.parametrize(
    "body",
    [
        {"name": "Cabaret"},
        {"name": "Cabaret", "description": None},
        {"name": "Cabaret", "description": ""},
        {"name": "Cabaret", "description": "   "},
    ],
)
def test_a_new_layout_needs_a_description(venue_staff_client, body):
    response = venue_staff_client.post("/venues/layouts", json=body)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == DESCRIPTION_REQUIRED
    assert len(_layouts(venue_staff_client)) == len(STANDARD_LAYOUTS)


@pytest.mark.story("8.6", ac=7)
@pytest.mark.parametrize("description", [None, "", "   "])
def test_a_layout_cannot_lose_its_description(venue_staff_client, description):
    response = venue_staff_client.patch(
        "/venues/layouts/THEATRE", json={"description": description}
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == DESCRIPTION_REQUIRED
    assert _layouts(venue_staff_client)[0]["description"] == THEATRE_DESCRIPTION


@pytest.mark.story("8.6", ac=7)
def test_spaces_around_a_description_are_removed(venue_staff_client):
    added = _added(venue_staff_client, "Cabaret", "  Round tables.  ")
    changed = venue_staff_client.patch(
        "/venues/layouts/CABARET", json={"description": " Dinner seating. "}
    )

    assert added["description"] == "Round tables."
    assert changed.json()["description"] == "Dinner seating."


# --- AC8: a layout in use ---------------------------------------------------------------------
def _venue_uses(db: Session, code: str) -> None:
    make_venue(db, layouts={code: None})


def _requirement_uses(db: Session, code: str) -> None:
    make_venue_requirement(db, make_event(db).id, layout_code=code)


def _booking_uses(status: str):
    def use(db: Session, code: str) -> None:
        make_booking(
            db,
            venue_id=make_venue(db).id,
            event_id=make_event(db, status=EventStatus.PLANNING).id,
            starts_at=_STARTS_AT,
            ends_at=_ENDS_AT,
            status=status,
            required_layout_code=code,
        )

    return use


@pytest.mark.story("8.6", ac=8)
@pytest.mark.parametrize(
    ("use", "places"),
    [
        (_venue_uses, "venues"),
        (_requirement_uses, "venue requirements"),
        (_booking_uses("PENDING"), "booking requests"),
        (_booking_uses("WITHDRAWN"), "booking requests"),
    ],
    ids=["venue", "venue requirement", "pending booking request", "withdrawn booking request"],
)
def test_a_layout_in_use_cannot_be_deleted_and_the_refusal_says_where(
    venue_staff_client, db, use, places
):
    _added(venue_staff_client, "Cabaret")
    use(db, "CABARET")

    response = venue_staff_client.delete("/venues/layouts/CABARET")

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == (
        f'You cannot delete "Cabaret" because {places} use it. You can still rename it.'
    )
    assert "Cabaret" in _names(venue_staff_client)


@pytest.mark.story("8.6", ac=8)
def test_theatre_names_every_place_that_uses_it_and_can_still_be_renamed(venue_staff_client):
    refused = venue_staff_client.delete("/venues/layouts/THEATRE")
    renamed = venue_staff_client.patch("/venues/layouts/THEATRE", json={"name": "Lecture theatre"})

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == (
        'You cannot delete "Theatre" because venues, venue requirements and booking requests use '
        "it. You can still rename it."
    )
    assert renamed.status_code == 200, renamed.text
    assert _names(venue_staff_client)[0] == "Lecture theatre"


# --- AC9: who may read and change -------------------------------------------------------------
@pytest.mark.story("8.6", ac=9)
@pytest.mark.parametrize(
    "user",
    [Users.COORDINATOR, Users.LEAD, Users.TECH_SUPPORT, Users.SAFETY_OFFICER],
    ids=lambda user: user.role,
)
def test_other_staff_can_read_the_list(login_as, user):
    response = login_as(user).get("/venues/layouts")

    assert response.status_code == 200, response.text
    assert [(x["code"], x["name"]) for x in response.json()] == STANDARD_LAYOUTS


@pytest.mark.story("8.6", ac=9)
@pytest.mark.parametrize("user", [Users.ORGANISER, Users.ATTENDEE], ids=lambda user: user.role)
def test_organisers_and_attendees_cannot_read_the_list(login_as, user):
    assert login_as(user).get("/venues/layouts").status_code == 403


@pytest.mark.story("8.6", ac=9)
def test_a_signed_out_visitor_cannot_read_the_list(client):
    assert client.get("/venues/layouts").status_code == 401


_CHANGES = {
    "add": lambda client: client.post(
        "/venues/layouts", json={"name": "Cabaret", "description": _DESCRIPTION}
    ),
    "rename": lambda client: client.patch("/venues/layouts/THEATRE", json={"name": "Hall"}),
    "delete": lambda client: client.delete("/venues/layouts/U_SHAPE"),
}


def _nothing_changed(db: Session) -> bool:
    layouts = db.execute(select(RoomLayout.code, RoomLayout.name).order_by(RoomLayout.sort_order))
    return [tuple(row) for row in layouts] == STANDARD_LAYOUTS


@pytest.mark.story("8.6", ac=9)
@pytest.mark.parametrize("change", _CHANGES, ids=list(_CHANGES))
@pytest.mark.parametrize(
    "user",
    [
        Users.COORDINATOR,
        Users.LEAD,
        Users.TECH_SUPPORT,
        Users.SAFETY_OFFICER,
        Users.ORGANISER,
        Users.ATTENDEE,
    ],
    ids=lambda user: user.role,
)
def test_only_venue_staff_can_change_layouts(login_as, db, user, change):
    response = _CHANGES[change](login_as(user))

    assert response.status_code == 403, response.text
    assert _nothing_changed(db)


@pytest.mark.story("8.6", ac=9)
@pytest.mark.parametrize("change", _CHANGES, ids=list(_CHANGES))
def test_a_signed_out_visitor_cannot_change_layouts(client, db, change):
    assert _CHANGES[change](client).status_code == 401
    assert _nothing_changed(db)


# --- AC10 to AC12: changes that cross --------------------------------------------------------
# These run real concurrent transactions, so they commit, and clean up after themselves.
def _clean_up(engine, *, codes: list[str], venue_ids: list[uuid.UUID] = ()) -> None:
    with Session(engine) as session:
        session.execute(
            delete(AuditLog).where(
                AuditLog.entity_type == "room_layout",
                AuditLog.details["code"].astext.in_(codes),
            )
        )
        session.execute(delete(AuditLog).where(AuditLog.entity_id.in_(venue_ids)))
        session.execute(delete(Venue).where(Venue.id.in_(venue_ids)))
        session.execute(delete(RoomLayout).where(RoomLayout.code.in_(codes)))
        session.execute(delete(DeletedRoomLayout).where(DeletedRoomLayout.code.in_(codes)))
        session.commit()


def _wait_until_a_session_waits_on_a_lock(engine) -> None:
    """Until another session of this database is blocked on a lock, for 10 s at most."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with engine.connect() as conn:
            waiting = conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            ).scalar_one()
        if waiting > 0:
            return
        time.sleep(0.05)
    raise AssertionError("no session started waiting on a lock")


@pytest.mark.story("8.6", ac=10)
@pytest.mark.parametrize("second", ["the same name", "other capitals"])
def test_two_venue_staff_adding_one_name_at_once_create_one_layout(engine, second):
    """Two Venue Staff press Add at the same moment: one layout is saved, the other told why."""
    name = f"Race {uuid.uuid4().hex[:8]}"
    names = [name, name if second == "the same name" else name.upper()]
    start = threading.Barrier(2)

    def attempt(attempted: str) -> str:
        with Session(engine) as session:
            actor = session.get(User, Users.VENUE_STAFF.id)
            start.wait(timeout=10)
            try:
                service.create_room_layout(
                    session,
                    venue_schemas.RoomLayoutCreate(name=attempted, description=_DESCRIPTION),
                    actor=actor,
                )
            except service.RoomLayoutNameTaken as refusal:
                return str(refusal)
            return "created"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt, attempted) for attempted in names]
            outcomes = [future.result(timeout=30) for future in futures]

        assert outcomes.count("created") == 1
        [refusal] = [outcome for outcome in outcomes if outcome != "created"]
        assert refusal in {f'A room layout named "{saved}" already exists.' for saved in names}
        with Session(engine) as session:
            same_name = func.lower(RoomLayout.name) == name.lower()
            assert session.scalar(select(func.count()).where(same_name)) == 1
    finally:
        with Session(engine) as session:
            codes = list(
                session.scalars(
                    select(RoomLayout.code).where(func.lower(RoomLayout.name) == name.lower())
                )
            )
        _clean_up(engine, codes=codes)


@pytest.mark.story("8.6", ac=11)
@pytest.mark.parametrize("save", ["create", "update"])
def test_saving_a_venue_with_a_deleted_layout_is_refused_naming_it(venue_staff_client, db, save):
    _added(venue_staff_client, "Cabaret")
    assert venue_staff_client.delete("/venues/layouts/CABARET").status_code == 204
    layouts = [{"code": "THEATRE"}, {"code": "CABARET"}]

    if save == "create":
        response = venue_staff_client.post(
            "/venues", json=venue_payload(name="Supper Club", layouts=layouts)
        )
    else:
        response = venue_staff_client.patch(
            f"/venues/{Venues.BOARDROOM}", json={"name": "Supper Club", "layouts": layouts}
        )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == (
        'The room layout "Cabaret" no longer exists. Untick it and save again.'
    )
    assert db.scalar(select(func.count()).where(Venue.name == "Supper Club")) == 0
    boardroom = venue_staff_client.get(f"/venues/{Venues.BOARDROOM}").json()
    assert [layout["code"] for layout in boardroom["layouts"]] == ["BOARDROOM"]


@pytest.mark.story("8.6", ac=11)
def test_two_deleted_layouts_are_named_together(venue_staff_client):
    for name in ("Supper club", "Cabaret"):
        _added(venue_staff_client, name)
    for code in ("CABARET", "SUPPER_CLUB"):
        venue_staff_client.delete(f"/venues/layouts/{code}")

    response = venue_staff_client.post(
        "/venues",
        json=venue_payload(layouts=[{"code": "SUPPER_CLUB"}, {"code": "CABARET"}]),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == (
        'The room layouts "Cabaret" and "Supper club" no longer exist. Untick them and save again.'
    )


@pytest.mark.story("8.6", ac=11)
@pytest.mark.parametrize("save", ["create", "update"])
def test_a_layout_code_that_never_existed_is_refused_as_unknown(venue_staff_client, save):
    """Only a deleted layout is said to no longer exist. A code no layout ever had, such as a
    typo sent from outside the app, keeps the catalogue's own refusal."""
    layouts = [{"code": "THEATER"}]

    if save == "create":
        response = venue_staff_client.post(
            "/venues", json=venue_payload(name="Supper Club", layouts=layouts)
        )
    else:
        response = venue_staff_client.patch(
            f"/venues/{Venues.BOARDROOM}", json={"layouts": layouts}
        )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "Unknown layout code(s): THEATER"


@pytest.mark.story("8.6", ac=11)
def test_a_layout_deleted_between_the_venue_saves_check_and_its_write_is_refused(
    engine, monkeypatch
):
    """The save has checked the venue's layouts when another Venue Staff member's delete of one
    lands. The database's foreign key then stops the write, and the save is refused the same
    way, naming the layout, rather than failing."""
    tag = uuid.uuid4().hex[:8].upper()
    code = f"RACE_{tag}"
    with Session(engine) as session:
        session.add(RoomLayout(code=code, name=f"Race layout {tag}", description=_DESCRIPTION))
        venue_id = make_venue(session, name=f"Race Venue {tag}").id
        session.commit()
    checked = threading.Event()
    deleted = threading.Event()
    check = service._validate_reference_codes

    def check_then_wait(db: Session, data: object) -> None:
        check(db, data)
        checked.set()
        assert deleted.wait(timeout=10)

    monkeypatch.setattr(service, "_validate_reference_codes", check_then_wait)

    def save_venue() -> str:
        with Session(engine) as session:
            actor = session.get(User, Users.VENUE_STAFF.id)
            change = venue_schemas.VenueUpdate(layouts=[venue_schemas.VenueLayoutIn(code=code)])
            try:
                service.update_venue(session, venue_id, change, actor=actor)
            except service.RoomLayoutGone as refusal:
                return str(refusal)
            return "saved"

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            saving = pool.submit(save_venue)
            try:
                assert checked.wait(timeout=10)
                with Session(engine) as session:
                    actor = session.get(User, Users.VENUE_STAFF.id)
                    service.delete_room_layout(session, code, actor=actor)
            finally:
                deleted.set()
            outcome = saving.result(timeout=30)

        assert outcome == (
            f'The room layout "Race layout {tag}" no longer exists. Untick it and save again.'
        )
        with Session(engine) as session:
            assert session.get(Venue, venue_id).layouts == []
    finally:
        _clean_up(engine, codes=[code], venue_ids=[venue_id])


@pytest.mark.story("8.6", ac=12)
@pytest.mark.parametrize("change", ["rename", "delete"])
def test_changing_a_layout_that_no_longer_exists_is_refused(venue_staff_client, change):
    _added(venue_staff_client, "Cabaret")
    assert venue_staff_client.delete("/venues/layouts/CABARET").status_code == 204

    if change == "rename":
        response = venue_staff_client.patch("/venues/layouts/CABARET", json={"name": "Bistro"})
    else:
        response = venue_staff_client.delete("/venues/layouts/CABARET")

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == NOT_FOUND
    assert "Bistro" not in _names(venue_staff_client)


@pytest.mark.story("8.6", ac=12)
@pytest.mark.parametrize(
    "change",
    [{"name": ""}, {"description": "   "}, {"name": "A" * 101}],
    ids=["blank name", "blank description", "name too long"],
)
def test_a_deleted_layout_is_said_to_be_gone_before_its_fields_are_checked(
    venue_staff_client, change
):
    """Correcting the field would not save the change, so the first answer says the layout no
    longer exists rather than asking for the field to be fixed."""
    _added(venue_staff_client, "Cabaret")
    assert venue_staff_client.delete("/venues/layouts/CABARET").status_code == 204

    response = venue_staff_client.patch("/venues/layouts/CABARET", json=change)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == NOT_FOUND


@pytest.mark.story("8.6", ac=12)
def test_a_rename_waiting_on_a_delete_is_refused_once_the_delete_lands(engine, monkeypatch):
    """Another Venue Staff member's delete has removed the layout but not yet finished when the
    rename arrives. The rename waits for it, then finds no layout, rather than renaming a row that
    is gone."""
    tag = uuid.uuid4().hex[:8].upper()
    code = f"RACE_{tag}"
    with Session(engine) as session:
        session.add(RoomLayout(code=code, name=f"Race layout {tag}", description=_DESCRIPTION))
        session.commit()
    deleting = threading.Event()
    proceed = threading.Event()
    audit = service.record_audit

    def audit_then_wait(db: Session, **kwargs: object) -> AuditLog:
        if kwargs["action"] == "ROOM_LAYOUT_DELETED":
            deleting.set()
            assert proceed.wait(timeout=10)
        return audit(db, **kwargs)

    monkeypatch.setattr(service, "record_audit", audit_then_wait)

    def delete_layout() -> None:
        with Session(engine) as session:
            actor = session.get(User, Users.VENUE_STAFF.id)
            service.delete_room_layout(session, code, actor=actor)

    def rename_layout() -> str:
        with Session(engine) as session:
            actor = session.get(User, Users.VENUE_STAFF.id)
            change = venue_schemas.RoomLayoutUpdate(name=f"Renamed {tag}")
            try:
                service.update_room_layout(session, code, change, actor=actor)
            except service.RoomLayoutNotFound:
                return "not found"
            return "renamed"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            deletion = pool.submit(delete_layout)
            try:
                assert deleting.wait(timeout=10)
                renaming = pool.submit(rename_layout)
                _wait_until_a_session_waits_on_a_lock(engine)
            finally:
                proceed.set()
            deletion.result(timeout=30)
            outcome = renaming.result(timeout=30)

        assert outcome == "not found"
        with Session(engine) as session:
            assert session.get(RoomLayout, code) is None
    finally:
        _clean_up(engine, codes=[code])


@pytest.mark.story("8.6", ac=12)
def test_a_rename_in_progress_does_not_hold_up_a_venue_saved_with_the_layout(engine, monkeypatch):
    """A rename locks the layout only against other changes to it, so a venue saved with that
    layout meanwhile goes through at once instead of waiting for the rename to finish."""
    tag = uuid.uuid4().hex[:8].upper()
    code = f"RACE_{tag}"
    with Session(engine) as session:
        session.add(RoomLayout(code=code, name=f"Race layout {tag}", description=_DESCRIPTION))
        venue_id = make_venue(session, name=f"Race Venue {tag}").id
        session.commit()
    renaming = threading.Event()
    proceed = threading.Event()
    audit = service.record_audit

    def audit_then_wait(db: Session, **kwargs: object) -> AuditLog:
        if kwargs["action"] == "ROOM_LAYOUT_UPDATED":
            renaming.set()
            assert proceed.wait(timeout=10)
        return audit(db, **kwargs)

    monkeypatch.setattr(service, "record_audit", audit_then_wait)

    def rename_layout() -> None:
        with Session(engine) as session:
            actor = session.get(User, Users.VENUE_STAFF.id)
            change = venue_schemas.RoomLayoutUpdate(name=f"Renamed {tag}")
            service.update_room_layout(session, code, change, actor=actor)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            renamed = pool.submit(rename_layout)
            try:
                assert renaming.wait(timeout=10)
                with Session(engine) as session:
                    # A save that has to wait for the rename fails here rather than hanging.
                    session.execute(text("SET LOCAL lock_timeout = '2s'"))
                    actor = session.get(User, Users.VENUE_STAFF.id)
                    change = venue_schemas.VenueUpdate(
                        layouts=[venue_schemas.VenueLayoutIn(code=code)]
                    )
                    service.update_venue(session, venue_id, change, actor=actor)
            finally:
                proceed.set()
            renamed.result(timeout=30)

        with Session(engine) as session:
            venue = session.get(Venue, venue_id)
            assert [layout.layout_code for layout in venue.layouts] == [code]
            assert session.get(RoomLayout, code).name == f"Renamed {tag}"
    finally:
        _clean_up(engine, codes=[code], venue_ids=[venue_id])
