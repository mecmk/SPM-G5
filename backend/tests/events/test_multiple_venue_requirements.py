"""Story 2.7 - fe/be: record several venue requirements, each with its own times.

AC1  The organiser can add more than one venue requirement, each with a short name, how many
     people it must hold, a room layout, required facilities (each optionally with how many) and
     other requirements in free text.
AC2  Each requirement has its own start and end, defaulting to the event's (Singapore time).
AC3  Requirements can be added, edited and removed while a draft; "No venue requirements" clears
     them all.
AC4  Every requirement, with its times, is shown to the reviewing coordinator and other internal
     roles.
AC5  A requirement's times fall within the event's, inclusive, and its end is after its start.
AC6  How many people a requirement must hold is a positive whole number, at most the event's
     expected attendance. The first requirement's number defaults to the expected attendance.
AC7  A request recorded before this story keeps its venue requirements as one requirement named
     "Main venue", with the event's times and expected attendance.
AC8  To submit, the request needs at least one requirement with a name and a number of people, or
     "No venue requirements"; an incomplete requirement blocks submission, a draft may hold one.
AC9  Two requirements on one request cannot share a name (trimmed, case-insensitive).
AC10 An edit to the event's start or end that would leave a requirement outside is refused,
     naming it; moving the requirement in the same edit is accepted.
AC11 Only the owning organiser, only while a draft; the server checks every rule again and a
     refused save marks the field to fix.
AC12 A save that races a submission in another tab is refused, and the requirements stay as
     submitted.

PO decisions (Checkpoint 1, 2 Oct 2026), tested here as well:
* Lowering the expected attendance below a requirement's number of people is refused like AC10.
* On submit, a requirement without times takes the event's times.
* A name is at most 100 characters; a request holds at most 20 requirements.
* Migration 012 gives no requirement to an event marked "No venue requirements" or left
  unspecified - only recorded requirements are kept (AC7).

Client-side defaults and marking (AC2, AC6 defaults, AC8 checklist, AC11 focus) are
tests/e2e/venue-requirements.spec.ts. 12.1's booking request reading the first requirement is
tests/bookings/test_raise_booking_request.py.
"""

from __future__ import annotations

import queue
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.common.audit import AuditLog
from app.events import service
from app.events.models import Event
from app.events.schemas import EventCreate, EventUpdate
from tests.support.factories import (
    create_event_request,
    create_submittable_event_request,
    event_request_payload,
    future_datetime,
    make_event,
    make_venue_requirement,
    submittable_event_request_payload,
)
from tests.support.seed import Events, Users

SGT = timezone(timedelta(hours=8))
INT32_MAX = 2_147_483_647
MIGRATION_012 = (
    Path(__file__).resolve().parents[2] / "db" / "migrations" / "012_venue_requirements.sql"
)
SEED_SAMPLE_DATA = Path(__file__).resolve().parents[2] / "db" / "seed" / "020_sample_data.sql"
NAME_MAX_LENGTH = 100
MAX_REQUIREMENTS = 20

NOT_WHOLE_POSITIVE = [
    pytest.param(0, id="zero"),
    pytest.param(-5, id="negative"),
    pytest.param(1.5, id="fraction"),
    pytest.param("20", id="string"),
    pytest.param(True, id="boolean"),
    pytest.param(INT32_MAX + 1, id="beyond-int32"),
]
NON_ORGANISERS = [
    pytest.param(Users.COORDINATOR, id="coordinator"),
    pytest.param(Users.VENUE_STAFF, id="venue-staff"),
    pytest.param(Users.TECH_SUPPORT, id="tech-support"),
    pytest.param(Users.ATTENDEE, id="attendee"),
]
INTERNAL_ROLES = [
    pytest.param(Users.COORDINATOR, id="coordinator"),
    pytest.param(Users.VENUE_STAFF, id="venue-staff"),
    pytest.param(Users.TECH_SUPPORT, id="tech-support"),
]


# --- helpers -----------------------------------------------------------------------------------
def _window(*, days: int = 30, hours: int = 8) -> tuple[datetime, datetime]:
    """An event period safely in the future: ``hours`` long, starting ``days`` from now."""
    starts_at = future_datetime(days=days)
    return starts_at, starts_at + timedelta(hours=hours)


def _requirement(name: str | None = "Plenary hall", capacity: int | None = 40, **extra) -> dict:
    """One item of ``venue_requirements``. Times are left out unless a test passes them."""
    item: dict = {"name": name, "capacity": capacity}
    for key, value in extra.items():
        item[key] = value.isoformat() if isinstance(value, datetime) else value
    return item


def _create(client, requirements: list[dict], *, window=None, attendance: int = 40, **overrides):
    """A draft with these requirements, over ``window`` (default: 30 days out, 8 hours long)."""
    starts_at, ends_at = window or _window()
    return create_event_request(
        client,
        starts_at=starts_at.isoformat(),
        ends_at=ends_at.isoformat(),
        expected_attendance=attendance,
        venue_requirements=requirements,
        **overrides,
    )


def _create_submittable(client, requirements: list[dict], *, window=None, attendance: int = 40):
    starts_at, ends_at = window or _window()
    return create_submittable_event_request(
        client,
        starts_at=starts_at.isoformat(),
        ends_at=ends_at.isoformat(),
        expected_attendance=attendance,
        venue_none_required=False,
        venue_requirements=requirements,
    )


def _post(client, requirements: list[dict], *, window=None, attendance: int = 40, **overrides):
    """Like ``_create``, but returns the raw response so a test can assert a refusal."""
    starts_at, ends_at = window or _window()
    return client.post(
        "/events",
        json={
            "name": f"Venue requirements {uuid.uuid4().hex[:8]}",
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
            "expected_attendance": attendance,
            "venue_requirements": requirements,
            **overrides,
        },
    )


def _patch(client, event_id, **body):
    return client.patch(f"/events/{event_id}", json=body)


def _submit(client, event_id):
    return client.post(f"/events/{event_id}/submit")


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _names(body: dict) -> list[str | None]:
    return [item["name"] for item in body["venue_requirements"]]


def _field_locations(response) -> list[tuple]:
    """The last three parts of each issue's ``loc`` - e.g. ("venue_requirements", 1, "ends_at")
    - which is how the form finds the field to mark (AC11)."""
    detail = response.json().get("detail")
    if not isinstance(detail, list):
        return []
    return [tuple(issue.get("loc", [])[-3:]) for issue in detail]


def _requirement_rows(db: Session, event_id) -> list:
    return db.execute(
        text(
            "SELECT id, position, name, capacity, starts_at, ends_at, layout_code, notes"
            " FROM venue_requirements WHERE event_id = :id ORDER BY position"
        ),
        {"id": str(event_id)},
    ).all()


def _facility_rows(db: Session, requirement_id) -> set[tuple]:
    rows = db.execute(
        text(
            "SELECT facility_code, quantity, notes FROM venue_requirement_facilities"
            " WHERE requirement_id = :id"
        ),
        {"id": str(requirement_id)},
    ).all()
    return {tuple(row) for row in rows}


# --- AC1: several requirements, each with its own details --------------------------------------
@pytest.mark.story("2.7", ac=1)
def test_several_venue_requirements_are_recorded_with_their_own_details(organiser_client):
    created = _create(
        organiser_client,
        [
            _requirement(
                "Plenary hall",
                300,
                layout_code="THEATRE",
                facilities=[{"code": "PROJECTOR", "quantity": 2, "notes": "HDMI input needed"}],
                notes="Near the lifts",
            ),
            _requirement(
                "Breakout",
                40,
                layout_code="CLASSROOM",
                facilities=[{"code": "BREAKOUT_ROOMS", "quantity": 3}, {"code": "WIFI"}],
            ),
        ],
        attendance=300,
    )

    fetched = organiser_client.get(f"/events/{created['id']}").json()
    plenary, breakout = fetched["venue_requirements"]
    assert plenary["name"] == "Plenary hall"
    assert plenary["capacity"] == 300
    assert (plenary["layout_code"], plenary["layout_name"]) == ("THEATRE", "Theatre")
    assert plenary["facilities"] == [
        {
            "code": "PROJECTOR",
            "name": "Projector & screen",
            "quantity": 2,
            "notes": "HDMI input needed",
        }
    ]
    assert plenary["notes"] == "Near the lifts"
    assert breakout["name"] == "Breakout"
    assert breakout["capacity"] == 40
    assert breakout["layout_code"] == "CLASSROOM"
    assert {(f["code"], f["quantity"]) for f in breakout["facilities"]} == {
        ("BREAKOUT_ROOMS", 3),
        ("WIFI", None),
    }
    assert breakout["notes"] is None
    assert plenary["id"] != breakout["id"]


@pytest.mark.story("2.7", ac=1)
def test_the_old_single_set_of_venue_fields_is_no_longer_accepted(organiser_client):
    """AC1 moves layout, facilities and other requirements into each requirement, so the flat
    2.1 fields are refused rather than silently ignored."""
    for old_field, value in (
        ("required_layout_code", "THEATRE"),
        ("required_facilities", [{"code": "WIFI"}]),
        ("venue_requirement_notes", "Near the lifts"),
    ):
        # Sent on its own, without venue_requirements, so the refusal can only be the old field.
        response = organiser_client.post(
            "/events", json=event_request_payload(**{old_field: value})
        )

        assert response.status_code == 422, old_field


@pytest.mark.story("2.7", ac=1)
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"layout_code": "NOT_A_LAYOUT"}, id="layout"),
        pytest.param({"facilities": [{"code": "NOT_A_FACILITY"}]}, id="facility"),
    ],
)
def test_a_requirement_must_name_real_layout_and_facilities(organiser_client, overrides):
    real = _post(
        organiser_client, [_requirement(layout_code="THEATRE", facilities=[{"code": "WIFI"}])]
    )
    response = _post(organiser_client, [_requirement(**overrides)])

    assert real.status_code == 201, real.text

    assert response.status_code == 422


@pytest.mark.story("2.7", ac=1)
def test_a_facility_can_appear_only_once_in_a_requirement(organiser_client):
    two_different = _post(
        organiser_client, [_requirement(facilities=[{"code": "WIFI"}, {"code": "PROJECTOR"}])]
    )
    response = _post(
        organiser_client,
        [_requirement(facilities=[{"code": "WIFI"}, {"code": "WIFI", "quantity": 2}])],
    )

    assert two_different.status_code == 201, two_different.text
    assert response.status_code == 422


@pytest.mark.story("2.7", ac=1)
def test_the_same_facility_can_be_required_by_two_requirements(organiser_client):
    created = _create(
        organiser_client,
        [
            _requirement("Plenary hall", facilities=[{"code": "WIFI"}]),
            _requirement("Breakout", facilities=[{"code": "WIFI"}]),
        ],
    )

    assert [[f["code"] for f in item["facilities"]] for item in created["venue_requirements"]] == [
        ["WIFI"],
        ["WIFI"],
    ]


@pytest.mark.story("2.7", ac=1)
def test_a_requirement_name_is_at_most_100_characters(organiser_client):
    at_limit = _post(organiser_client, [_requirement("x" * NAME_MAX_LENGTH)])
    over_limit = _post(organiser_client, [_requirement("x" * (NAME_MAX_LENGTH + 1))])

    assert at_limit.status_code == 201, at_limit.text
    assert over_limit.status_code == 422
    assert ("venue_requirements", 0, "name") in _field_locations(over_limit)


@pytest.mark.story("2.7", ac=1)
def test_a_request_holds_at_most_20_requirements(organiser_client):
    def rooms(count: int) -> list[dict]:
        return [_requirement(f"Room {n}", 1) for n in range(1, count + 1)]

    at_limit = _post(organiser_client, rooms(MAX_REQUIREMENTS))
    over_limit = _post(organiser_client, rooms(MAX_REQUIREMENTS + 1))

    assert at_limit.status_code == 201, at_limit.text
    assert over_limit.status_code == 422


# --- AC2: each requirement has its own start and end --------------------------------------------
@pytest.mark.story("2.7", ac=2)
def test_a_requirement_records_its_own_start_and_end(organiser_client):
    """A two-day event whose breakout rooms are needed only on the second day."""
    day_one = future_datetime(days=30)
    day_two = day_one + timedelta(days=1)
    created = _create(
        organiser_client,
        [
            _requirement("Plenary hall", starts_at=day_one, ends_at=day_two + timedelta(hours=8)),
            _requirement("Breakout", starts_at=day_two, ends_at=day_two + timedelta(hours=8)),
        ],
        window=(day_one, day_two + timedelta(hours=8)),
    )

    plenary, breakout = created["venue_requirements"]
    assert (_at(plenary["starts_at"]), _at(plenary["ends_at"])) == (
        day_one,
        day_two + timedelta(hours=8),
    )
    assert (_at(breakout["starts_at"]), _at(breakout["ends_at"])) == (
        day_two,
        day_two + timedelta(hours=8),
    )


@pytest.mark.story("2.7", ac=2)
def test_requirement_times_are_kept_as_the_moment_sent_in_singapore_time(organiser_client):
    """Times are Singapore time: 13:00 +08:00 is stored and returned as that same moment."""
    starts_at, ends_at = _window()
    one_pm_singapore = starts_at.astimezone(SGT).replace(hour=13, minute=0)
    window = (one_pm_singapore - timedelta(hours=4), one_pm_singapore + timedelta(hours=4))

    created = _create(
        organiser_client,
        [_requirement(starts_at=one_pm_singapore, ends_at=window[1])],
        window=window,
    )

    assert _at(created["venue_requirements"][0]["starts_at"]) == one_pm_singapore


@pytest.mark.story("2.7", ac=2)
@pytest.mark.parametrize("given", ["starts_at", "ends_at"])
def test_a_requirement_needs_both_times_or_neither(organiser_client, given):
    starts_at, ends_at = _window()
    times = {"starts_at": starts_at, "ends_at": ends_at}

    both = _post(organiser_client, [_requirement(**times)])
    one = _post(organiser_client, [_requirement(**{given: times[given]})])

    assert both.status_code == 201, both.text
    assert one.status_code == 422


# --- AC3: added, edited and removed while a draft; "No venue requirements" clears them -----------
@pytest.mark.story("2.7", ac=3)
def test_an_edited_requirement_keeps_its_id(organiser_client):
    """A requirement is edited in place, never deleted and re-created, so a booking that later
    points at it (stories 8.4, 12.5) keeps pointing at the same requirement."""
    created = _create(organiser_client, [_requirement("Plenary hall", 30)])
    original = created["venue_requirements"][0]

    response = _patch(
        organiser_client,
        created["id"],
        venue_requirements=[{**_requirement("Main hall", 35), "id": original["id"]}],
    )

    assert response.status_code == 200, response.text
    (edited,) = response.json()["venue_requirements"]
    assert edited["id"] == original["id"]
    assert (edited["name"], edited["capacity"]) == ("Main hall", 35)


@pytest.mark.story("2.7", ac=3)
def test_a_requirement_left_out_of_an_edit_is_removed_and_one_without_an_id_is_added(
    organiser_client,
):
    created = _create(
        organiser_client, [_requirement("Plenary hall"), _requirement("Breakout", 20)]
    )
    plenary, breakout = created["venue_requirements"]

    response = _patch(
        organiser_client,
        created["id"],
        venue_requirements=[
            {**_requirement("Plenary hall"), "id": plenary["id"]},
            _requirement("Catering area", 10),
        ],
    )

    assert response.status_code == 200, response.text
    kept, added = response.json()["venue_requirements"]
    assert kept["id"] == plenary["id"]
    assert added["name"] == "Catering area"
    assert added["id"] not in {plenary["id"], breakout["id"]}


@pytest.mark.story("2.7", ac=3)
def test_an_edit_that_does_not_send_requirements_keeps_them(organiser_client):
    created = _create(organiser_client, [_requirement("Plenary hall")])

    response = _patch(organiser_client, created["id"], purpose="Changed purpose")

    assert response.status_code == 200, response.text
    assert _names(response.json()) == ["Plenary hall"]


@pytest.mark.story("2.7", ac=3)
def test_venue_requirements_cannot_be_set_to_null(organiser_client):
    created = _create(organiser_client, [_requirement("Plenary hall")])

    response = _patch(organiser_client, created["id"], venue_requirements=None)

    assert response.status_code == 422


@pytest.mark.story("2.7", ac=3)
def test_a_requirement_id_from_another_request_is_refused(organiser_client):
    mine = _create(organiser_client, [_requirement("Plenary hall")])
    other = _create(organiser_client, [_requirement("Breakout")])
    other_id = other["venue_requirements"][0]["id"]

    response = _patch(
        organiser_client,
        mine["id"],
        venue_requirements=[{**_requirement("Stolen"), "id": other_id}],
    )

    assert response.status_code == 422
    still = organiser_client.get(f"/events/{other['id']}").json()
    assert _names(still) == ["Breakout"]


@pytest.mark.story("2.7", ac=3)
def test_no_venue_requirements_clears_every_requirement(organiser_client):
    created = _create(
        organiser_client, [_requirement("Plenary hall"), _requirement("Breakout", 20)]
    )

    response = _patch(
        organiser_client, created["id"], venue_none_required=True, venue_requirements=[]
    )

    assert response.status_code == 200, response.text
    assert response.json()["venue_none_required"] is True
    assert response.json()["venue_requirements"] == []


@pytest.mark.story("2.7", ac=3)
def test_no_venue_requirements_contradicts_a_listed_requirement(organiser_client):
    on_create = _post(organiser_client, [_requirement()], venue_none_required=True)
    created = _create(organiser_client, [_requirement("Plenary hall")])
    against_stored = _patch(organiser_client, created["id"], venue_none_required=True)

    assert on_create.status_code == 422
    assert against_stored.status_code == 422


# --- AC4: every requirement, with its times, is shown to internal roles --------------------------
@pytest.mark.story("2.7", ac=4)
@pytest.mark.parametrize("viewer", INTERNAL_ROLES)
def test_internal_roles_see_every_requirement_with_its_times(login_as, viewer):
    organiser = login_as(Users.ORGANISER)
    starts_at, ends_at = _window()
    afternoon = starts_at + timedelta(hours=4)
    created = _create_submittable(
        organiser,
        [
            _requirement("Plenary hall", 40, starts_at=starts_at, ends_at=ends_at),
            _requirement("Breakout", 20, starts_at=afternoon, ends_at=ends_at),
        ],
        window=(starts_at, ends_at),
    )
    assert _submit(organiser, created["id"]).status_code == 200

    seen = login_as(viewer).get(f"/events/{created['id']}")

    assert seen.status_code == 200
    plenary, breakout = seen.json()["venue_requirements"]
    assert (plenary["name"], _at(plenary["starts_at"]), _at(plenary["ends_at"])) == (
        "Plenary hall",
        starts_at,
        ends_at,
    )
    assert (breakout["name"], _at(breakout["starts_at"]), _at(breakout["ends_at"])) == (
        "Breakout",
        afternoon,
        ends_at,
    )


@pytest.mark.story("2.7", ac=4)
def test_another_organiser_cannot_see_the_requirements(login_as):
    created = _create_submittable(login_as(Users.ORGANISER), [_requirement("Plenary hall")])
    _submit(login_as(Users.ORGANISER), created["id"])

    response = login_as(Users.ORGANISER_2).get(f"/events/{created['id']}")

    assert response.status_code == 404


# --- AC5: within the event's times, inclusive; end after start -----------------------------------
@pytest.mark.story("2.7", ac=5)
def test_a_requirement_may_span_exactly_the_event(organiser_client):
    starts_at, ends_at = _window()

    response = _post(
        organiser_client,
        [_requirement(starts_at=starts_at, ends_at=ends_at)],
        window=(starts_at, ends_at),
    )

    assert response.status_code == 201, response.text


@pytest.mark.story("2.7", ac=5)
@pytest.mark.parametrize(
    ("start_shift", "end_shift", "field"),
    [
        pytest.param(-1, 0, "starts_at", id="starts-a-minute-before-the-event"),
        pytest.param(0, 1, "ends_at", id="ends-a-minute-after-the-event"),
    ],
)
def test_a_requirement_outside_the_event_is_refused(
    organiser_client, start_shift, end_shift, field
):
    starts_at, ends_at = _window()

    response = _post(
        organiser_client,
        [
            _requirement(
                "Plenary hall",
                starts_at=starts_at + timedelta(minutes=start_shift),
                ends_at=ends_at + timedelta(minutes=end_shift),
            )
        ],
        window=(starts_at, ends_at),
    )

    assert response.status_code == 422
    assert "plenary hall" in response.text.lower()
    assert ("venue_requirements", 0, field) in _field_locations(response)


@pytest.mark.story("2.7", ac=5)
@pytest.mark.parametrize("length_minutes", [0, -60], ids=["ends-as-it-starts", "ends-before"])
def test_a_requirement_must_end_after_it_starts(organiser_client, length_minutes):
    starts_at, ends_at = _window()
    middle = starts_at + timedelta(hours=4)

    response = _post(
        organiser_client,
        [_requirement(starts_at=middle, ends_at=middle + timedelta(minutes=length_minutes))],
        window=(starts_at, ends_at),
    )

    assert response.status_code == 422
    assert ("venue_requirements", 0, "ends_at") in _field_locations(response)


# --- AC6: a positive whole number of people, at most the expected attendance ---------------------
@pytest.mark.story("2.7", ac=6)
@pytest.mark.parametrize("capacity", NOT_WHOLE_POSITIVE)
def test_requirement_capacity_rejects_anything_but_a_positive_whole_number(
    organiser_client, capacity
):
    response = _post(organiser_client, [_requirement(capacity=capacity)])

    assert response.status_code == 422
    assert ("venue_requirements", 0, "capacity") in _field_locations(response)


@pytest.mark.story("2.7", ac=6)
def test_requirement_capacity_may_equal_but_not_exceed_expected_attendance(organiser_client):
    at_attendance = _post(organiser_client, [_requirement(capacity=40)], attendance=40)
    over_attendance = _post(organiser_client, [_requirement(capacity=41)], attendance=40)

    assert at_attendance.status_code == 201, at_attendance.text
    assert over_attendance.status_code == 422
    assert ("venue_requirements", 0, "capacity") in _field_locations(over_attendance)


@pytest.mark.story("2.7", ac=6)
def test_lowering_expected_attendance_below_a_requirement_is_refused_naming_it(
    organiser_client,
):
    created = _create(
        organiser_client,
        [_requirement("Plenary hall", 40), _requirement("Breakout", 20)],
        attendance=40,
    )

    response = _patch(organiser_client, created["id"], expected_attendance=30)

    assert response.status_code == 422
    assert "plenary hall" in response.text.lower()
    assert ("venue_requirements", 0, "capacity") in _field_locations(response)
    assert organiser_client.get(f"/events/{created['id']}").json()["expected_attendance"] == 40


@pytest.mark.story("2.7", ac=6)
def test_lowering_attendance_and_the_requirement_together_is_accepted(organiser_client):
    created = _create(organiser_client, [_requirement("Plenary hall", 40)], attendance=40)
    requirement_id = created["venue_requirements"][0]["id"]

    response = _patch(
        organiser_client,
        created["id"],
        expected_attendance=30,
        venue_requirements=[{**_requirement("Plenary hall", 30), "id": requirement_id}],
    )

    assert response.status_code == 200, response.text
    assert response.json()["venue_requirements"][0]["capacity"] == 30


# --- AC7: requests recorded before this story keep a "Main venue" --------------------------------
# Migration 012 is run here on pre-012 data, inside the test's transaction, which is rolled back -
# the same approach as test_venue_hold.py's migration 010 test. PRE_012_SCHEMA puts back the
# venue-requirement shape of migration 001 that 012 replaces.
PRE_012_SCHEMA = """
DROP TABLE IF EXISTS venue_requirement_facilities;
DROP TABLE IF EXISTS venue_requirements;
ALTER TABLE events
    ADD COLUMN IF NOT EXISTS required_layout_code TEXT REFERENCES room_layouts (code);
ALTER TABLE events ADD COLUMN IF NOT EXISTS venue_requirement_notes TEXT;
CREATE TABLE IF NOT EXISTS event_required_facilities (
    event_id      UUID NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    facility_code TEXT NOT NULL REFERENCES facilities (code),
    quantity      INTEGER,
    notes         TEXT,
    PRIMARY KEY (event_id, facility_code),
    CONSTRAINT ck_event_required_facilities_quantity CHECK (quantity IS NULL OR quantity > 0)
);
"""


def _pre_012_event(
    db: Session,
    *,
    status: str = "UNDER_REVIEW",
    starts_at: datetime | None = datetime(2026, 12, 1, 9, 0, tzinfo=SGT),
    ends_at: datetime | None = datetime(2026, 12, 1, 17, 0, tzinfo=SGT),
    attendance: int | None = 80,
    layout: str | None = None,
    notes: str | None = None,
    none_required: bool = False,
    facilities: tuple[tuple[str, int | None, str | None], ...] = (),
) -> uuid.UUID:
    """An event as a request recorded before story 2.7 stores its venue requirements."""
    event_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO events (id, organiser_id, name, purpose, starts_at, ends_at,"
            " expected_attendance, status, required_layout_code, venue_requirement_notes,"
            " venue_none_required)"
            " VALUES (:id, :organiser, :name, 'Testing', :starts_at, :ends_at, :attendance,"
            " :status, :layout, :notes, :none_required)"
        ),
        {
            "id": event_id,
            "organiser": Users.ORGANISER.id,
            "name": f"Pre-012 {event_id.hex[:8]}",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "attendance": attendance,
            "status": status,
            "layout": layout,
            "notes": notes,
            "none_required": none_required,
        },
    )
    for code, quantity, facility_notes in facilities:
        db.execute(
            text(
                "INSERT INTO event_required_facilities (event_id, facility_code, quantity, notes)"
                " VALUES (:event_id, :code, :quantity, :notes)"
            ),
            {"event_id": event_id, "code": code, "quantity": quantity, "notes": facility_notes},
        )
    return event_id


def _run_migration_012(db: Session) -> None:
    db.connection().exec_driver_sql(MIGRATION_012.read_text(encoding="utf-8"))
    db.expire_all()


@pytest.mark.story("2.7", ac=7)
def test_migration_012_turns_recorded_venue_requirements_into_a_main_venue(db: Session):
    db.connection().exec_driver_sql(PRE_012_SCHEMA)
    starts_at = datetime(2026, 12, 1, 9, 0, tzinfo=SGT)
    ends_at = datetime(2026, 12, 1, 17, 0, tzinfo=SGT)
    everything = _pre_012_event(
        db,
        starts_at=starts_at,
        ends_at=ends_at,
        attendance=80,
        layout="THEATRE",
        notes="Near the loading bay",
        facilities=(("BREAKOUT_ROOMS", 3, "HDMI input needed"), ("PROJECTOR", None, None)),
    )
    facilities_only = _pre_012_event(db, facilities=(("WIFI", None, None),))
    notes_only = _pre_012_event(db, notes="Step-free access")

    _run_migration_012(db)

    (main,) = _requirement_rows(db, everything)
    assert main.name == "Main venue"
    assert main.position == 0
    assert (main.starts_at, main.ends_at, main.capacity) == (starts_at, ends_at, 80)
    assert (main.layout_code, main.notes) == ("THEATRE", "Near the loading bay")
    assert _facility_rows(db, main.id) == {
        ("BREAKOUT_ROOMS", 3, "HDMI input needed"),
        ("PROJECTOR", None, None),
    }
    (from_facilities,) = _requirement_rows(db, facilities_only)
    assert _facility_rows(db, from_facilities.id) == {("WIFI", None, None)}
    (from_notes,) = _requirement_rows(db, notes_only)
    assert from_notes.notes == "Step-free access"


@pytest.mark.story("2.7", ac=7)
def test_migration_012_creates_no_requirement_where_none_was_recorded(db: Session):
    """PO decision: "No venue requirements" stays an answer, and "not yet specified" stays
    unanswered - inventing a Main venue for either would put words in the organiser's mouth."""
    db.connection().exec_driver_sql(PRE_012_SCHEMA)
    marked_none = _pre_012_event(db, none_required=True)
    left_empty = _pre_012_event(db, status="DRAFT")

    _run_migration_012(db)

    assert _requirement_rows(db, marked_none) == []
    assert _requirement_rows(db, left_empty) == []
    assert db.get(Event, marked_none).venue_none_required is True


@pytest.mark.story("2.7", ac=7)
def test_migration_012_keeps_an_undated_drafts_times_and_people_blank(db: Session):
    db.connection().exec_driver_sql(PRE_012_SCHEMA)
    undated = _pre_012_event(
        db, status="DRAFT", starts_at=None, ends_at=None, attendance=None, layout="BOARDROOM"
    )

    _run_migration_012(db)

    (main,) = _requirement_rows(db, undated)
    assert (main.name, main.layout_code) == ("Main venue", "BOARDROOM")
    assert (main.starts_at, main.ends_at, main.capacity) == (None, None, None)


@pytest.mark.story("2.7", ac=7)
def test_seeded_events_keep_their_venue_requirements(coordinator_client):
    """The seed runs after the migrations, so it writes its own requirements; the sample events
    keep the venue requirements they had, as a Main venue."""
    submitted = coordinator_client.get(f"/events/{Events.SUBMITTED}").json()
    approved = coordinator_client.get(f"/events/{Events.APPROVED}").json()

    (data_literacy,) = submitted["venue_requirements"]
    assert data_literacy["name"] == "Main venue"
    assert data_literacy["capacity"] == 60
    assert _at(data_literacy["starts_at"]) == datetime(2026, 11, 18, 9, 0, tzinfo=SGT)
    assert _at(data_literacy["ends_at"]) == datetime(2026, 11, 18, 17, 0, tzinfo=SGT)
    assert data_literacy["layout_code"] == "CLASSROOM"
    assert {f["code"] for f in data_literacy["facilities"]} == {"PROJECTOR", "WIFI"}

    nimbus = approved["venue_requirements"][0]
    assert (nimbus["name"], nimbus["capacity"], nimbus["layout_code"]) == (
        "Main venue",
        350,
        "THEATRE",
    )
    assert {f["code"] for f in nimbus["facilities"]} == {"PROJECTOR", "SOUND_SYSTEM", "STAGE"}


@pytest.mark.story("2.7", ac=7)
def test_reseeding_does_not_duplicate_venue_requirements(db: Session):
    before = len(_requirement_rows(db, Events.APPROVED))

    db.connection().exec_driver_sql(SEED_SAMPLE_DATA.read_text(encoding="utf-8"))
    db.expire_all()

    assert before > 0
    assert len(_requirement_rows(db, Events.APPROVED)) == before


# --- AC8: what a requirement needs before the request can be submitted ---------------------------
@pytest.mark.story("2.7", ac=8)
def test_a_request_with_a_complete_requirement_can_be_submitted(organiser_client):
    created = _create_submittable(organiser_client, [_requirement("Plenary hall", 40)])

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 200, response.text


@pytest.mark.story("2.7", ac=8)
@pytest.mark.parametrize(
    ("incomplete", "named_as"),
    [
        pytest.param({"name": None}, "name", id="no-name"),
        pytest.param({"name": "   "}, "name", id="blank-name"),
        pytest.param({"capacity": None}, "number of people", id="no-number-of-people"),
    ],
)
def test_a_requirement_missing_its_name_or_people_blocks_submission_and_is_named(
    organiser_client, incomplete, named_as
):
    created = _create_submittable(
        organiser_client,
        [_requirement("Plenary hall", 40), {**_requirement("Breakout", 20), **incomplete}],
    )

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 422
    assert "venue requirement 2" in response.text.lower()
    assert named_as in response.text.lower()
    assert organiser_client.get(f"/events/{created['id']}").json()["status"] == "DRAFT"


@pytest.mark.story("2.7", ac=8)
def test_one_incomplete_requirement_blocks_submission_beside_a_complete_one(organiser_client):
    created = _create_submittable(
        organiser_client, [_requirement(None, None), _requirement("Breakout", 20)]
    )

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 422
    assert "venue requirement 1" in response.text.lower()


@pytest.mark.story("2.7", ac=8)
def test_no_requirements_and_not_marked_none_blocks_submission(organiser_client):
    created = _create_submittable(organiser_client, [])

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 422
    assert "venue requirements" in response.text.lower()


@pytest.mark.story("2.7", ac=8)
def test_a_draft_may_hold_incomplete_requirements(organiser_client):
    response = _post(organiser_client, [_requirement(None, None), _requirement("Breakout", None)])

    assert response.status_code == 201, response.text
    assert _names(response.json()) == [None, "Breakout"]


@pytest.mark.story("2.7", ac=8)
def test_a_requirement_without_times_takes_the_events_times_on_submit(organiser_client):
    """PO decision: AC2's default applies when the organiser never gave the requirement its own
    times - so a submitted requirement always has a period 12.1 can book."""
    starts_at, ends_at = _window()
    created = _create_submittable(
        organiser_client, [_requirement("Plenary hall", 40)], window=(starts_at, ends_at)
    )

    response = _submit(organiser_client, created["id"])

    assert response.status_code == 200, response.text
    (plenary,) = response.json()["venue_requirements"]
    assert (_at(plenary["starts_at"]), _at(plenary["ends_at"])) == (starts_at, ends_at)


# --- AC9: no two requirements on one request share a name ----------------------------------------
@pytest.mark.story("2.7", ac=9)
@pytest.mark.parametrize(
    "second_name",
    [
        pytest.param("Plenary hall", id="exact"),
        pytest.param("PLENARY HALL", id="other-case"),
        pytest.param("  Plenary hall  ", id="padded"),
    ],
)
def test_two_requirements_cannot_share_a_name(organiser_client, second_name):
    response = _post(
        organiser_client, [_requirement("Plenary hall"), _requirement(second_name, 20)]
    )

    assert response.status_code == 422
    assert "plenary hall" in response.text.lower()
    assert ("venue_requirements", 1, "name") in _field_locations(response)


@pytest.mark.story("2.7", ac=9)
def test_the_database_refuses_two_requirements_with_one_name(db: Session):
    """The unique index behind AC9, bypassing the service: the last line of defence."""
    event = make_event(db, status="DRAFT")
    make_venue_requirement(db, event.id, position=0, name="Plenary hall")

    with pytest.raises(IntegrityError) as excinfo:
        with db.begin_nested():
            make_venue_requirement(db, event.id, position=1, name=" plenary HALL ")

    assert "uq_venue_requirements_event_name" in str(excinfo.value.orig)


@pytest.mark.story("2.7", ac=9)
def test_two_requests_may_each_have_a_requirement_with_the_same_name(organiser_client):
    first = _post(organiser_client, [_requirement("Plenary hall")])
    second = _post(organiser_client, [_requirement("Plenary hall")])

    assert (first.status_code, second.status_code) == (201, 201)


@pytest.mark.story("2.7", ac=9)
def test_two_requirements_can_swap_names_in_one_save(organiser_client):
    created = _create(organiser_client, [_requirement("Hall A", 30), _requirement("Hall B", 20)])
    a, b = created["venue_requirements"]

    response = _patch(
        organiser_client,
        created["id"],
        venue_requirements=[
            {**_requirement("Hall B", 30), "id": a["id"]},
            {**_requirement("Hall A", 20), "id": b["id"]},
        ],
    )

    assert response.status_code == 200, response.text
    assert [(item["id"], item["name"]) for item in response.json()["venue_requirements"]] == [
        (a["id"], "Hall B"),
        (b["id"], "Hall A"),
    ]


@pytest.mark.story("2.7", ac=9)
def test_several_unnamed_requirements_may_sit_on_a_draft(organiser_client):
    response = _post(organiser_client, [_requirement(None), _requirement(None, 20)])

    assert response.status_code == 201, response.text


# --- AC10: moving the event cannot leave a requirement outside it --------------------------------
@pytest.mark.story("2.7", ac=10)
@pytest.mark.parametrize(
    ("start_shift_hours", "end_shift_hours", "field"),
    [
        pytest.param(1, 0, "starts_at", id="start-moved-later"),
        pytest.param(0, -1, "ends_at", id="end-moved-earlier"),
    ],
)
def test_moving_the_event_so_a_requirement_falls_outside_is_refused_naming_it(
    organiser_client, start_shift_hours, end_shift_hours, field
):
    starts_at, ends_at = _window()
    created = _create(
        organiser_client,
        [_requirement("Plenary hall", starts_at=starts_at, ends_at=ends_at)],
        window=(starts_at, ends_at),
    )

    response = _patch(
        organiser_client,
        created["id"],
        starts_at=(starts_at + timedelta(hours=start_shift_hours)).isoformat(),
        ends_at=(ends_at + timedelta(hours=end_shift_hours)).isoformat(),
    )

    assert response.status_code == 422
    assert "plenary hall" in response.text.lower()
    assert ("venue_requirements", 0, field) in _field_locations(response)


@pytest.mark.story("2.7", ac=10)
def test_moving_the_event_and_its_requirement_in_one_edit_is_accepted(organiser_client):
    starts_at, ends_at = _window()
    created = _create(
        organiser_client,
        [_requirement("Plenary hall", starts_at=starts_at, ends_at=ends_at)],
        window=(starts_at, ends_at),
    )
    requirement_id = created["venue_requirements"][0]["id"]
    later_start, later_end = starts_at + timedelta(days=1), ends_at + timedelta(days=1)

    response = _patch(
        organiser_client,
        created["id"],
        starts_at=later_start.isoformat(),
        ends_at=later_end.isoformat(),
        venue_requirements=[
            {
                **_requirement("Plenary hall", starts_at=later_start, ends_at=later_end),
                "id": requirement_id,
            }
        ],
    )

    assert response.status_code == 200, response.text
    (moved,) = response.json()["venue_requirements"]
    assert (_at(moved["starts_at"]), _at(moved["ends_at"])) == (later_start, later_end)


@pytest.mark.story("2.7", ac=10)
def test_a_refused_move_leaves_the_event_and_its_requirements_unchanged(organiser_client):
    starts_at, ends_at = _window()
    created = _create(
        organiser_client,
        [_requirement("Plenary hall", starts_at=starts_at, ends_at=ends_at)],
        window=(starts_at, ends_at),
    )

    refused = _patch(
        organiser_client,
        created["id"],
        starts_at=(starts_at + timedelta(hours=1)).isoformat(),
        name="Renamed in the same edit",
    )

    assert refused.status_code == 422
    after = organiser_client.get(f"/events/{created['id']}").json()
    assert _at(after["starts_at"]) == starts_at
    assert after["name"] == created["name"]
    assert _at(after["venue_requirements"][0]["starts_at"]) == starts_at


# --- AC11: only the owning organiser, only while a draft ----------------------------------------
@pytest.mark.story("2.7", ac=11)
def test_signed_out_user_cannot_change_venue_requirements(client, login_as):
    created = _create(login_as(Users.ORGANISER), [_requirement("Plenary hall")])
    client.logout()

    response = _patch(client, created["id"], venue_requirements=[_requirement("Hijacked")])

    assert response.status_code == 401


@pytest.mark.story("2.7", ac=11)
@pytest.mark.parametrize("user", NON_ORGANISERS)
def test_other_roles_cannot_change_venue_requirements(login_as, user):
    created = _create(login_as(Users.ORGANISER), [_requirement("Plenary hall")])

    response = _patch(login_as(user), created["id"], venue_requirements=[_requirement("Hijacked")])

    assert response.status_code == 403


@pytest.mark.story("2.7", ac=11)
def test_another_organiser_cannot_change_venue_requirements(login_as):
    created = _create(login_as(Users.ORGANISER), [_requirement("Plenary hall")])

    response = _patch(
        login_as(Users.ORGANISER_2), created["id"], venue_requirements=[_requirement("Hijacked")]
    )

    assert response.status_code == 404
    assert _names(login_as(Users.ORGANISER).get(f"/events/{created['id']}").json()) == [
        "Plenary hall"
    ]


@pytest.mark.story("2.7", ac=11)
def test_venue_requirements_cannot_change_once_submitted(organiser_client):
    created = _create_submittable(organiser_client, [_requirement("Plenary hall")])
    assert _submit(organiser_client, created["id"]).status_code == 200

    response = _patch(organiser_client, created["id"], venue_requirements=[])

    assert response.status_code == 409
    assert _names(organiser_client.get(f"/events/{created['id']}").json()) == ["Plenary hall"]


@pytest.mark.story("2.7", ac=11)
def test_a_refused_requirement_names_the_field_to_fix(organiser_client):
    """The server's own refusal points at the requirement and field, in the shape FastAPI uses
    for a validation error, so the form can mark it even when only the server could tell."""
    starts_at, ends_at = _window()

    response = _post(
        organiser_client,
        [
            _requirement("Plenary hall", starts_at=starts_at, ends_at=ends_at),
            _requirement("Breakout", 20, starts_at=starts_at, ends_at=ends_at + timedelta(hours=1)),
        ],
        window=(starts_at, ends_at),
    )

    assert response.status_code == 422
    (issue,) = response.json()["detail"]
    assert issue["loc"][-3:] == ["venue_requirements", 1, "ends_at"]
    assert "breakout" in issue["msg"].lower()


# --- AC12: a save racing a submission in another tab ---------------------------------------------
# Real concurrent transactions, so these commit and clean up after themselves (as
# tests/bookings/test_venue_hold.py does). A second connection plays the other tab: it holds the
# event row mid-transaction while the service call starts, and the test waits until that call is
# blocked on the row before letting the other tab commit - so the interleaving is the same on
# every run, not a matter of thread timing.
LOCK_WAIT_SECONDS = 10


def _committed_submittable_draft(engine, requirements: list[dict]) -> tuple[uuid.UUID, str]:
    with Session(engine) as session:
        organiser = session.get(User, Users.ORGANISER.id)
        starts_at, ends_at = _window()
        payload = submittable_event_request_payload(
            name=f"Race {uuid.uuid4().hex[:8]}",
            starts_at=starts_at.isoformat(),
            ends_at=ends_at.isoformat(),
            venue_none_required=False,
            venue_requirements=requirements,
        )
        event = service.create_event(session, EventCreate(**payload), actor=organiser)
        session.commit()
        requirement_id = session.execute(
            text("SELECT id FROM venue_requirements WHERE event_id = :id ORDER BY position"),
            {"id": event.id},
        ).scalar_one()
        return event.id, str(requirement_id)


def _remove_event(engine, event_id: uuid.UUID) -> None:
    with Session(engine) as session:
        session.execute(delete(AuditLog).where(AuditLog.entity_id == event_id))
        session.execute(delete(Event).where(Event.id == event_id))
        session.commit()


def _wait_until_waiting_on_a_lock(engine, pid: int) -> bool:
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    with engine.connect() as watcher:
        while time.monotonic() < deadline:
            waiting_on = watcher.execute(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": pid},
            ).scalar()
            watcher.rollback()  # pg_stat_activity is a per-transaction snapshot
            if waiting_on == "Lock":
                return True
            time.sleep(0.05)
    return False


def _run_while_the_row_is_held(engine, event_id, other_tab_sql: list[str], call) -> object:
    """Hold the event row in another transaction, run ``call(session)`` in a thread, wait until
    it is blocked on that row, then commit the other transaction. Returns what ``call`` returned
    (or raised)."""
    pids: queue.Queue[int] = queue.Queue()

    def attempt():
        with Session(engine) as session:
            pids.put(session.connection().exec_driver_sql("SELECT pg_backend_pid()").scalar())
            try:
                return call(session)
            except Exception as refusal:  # the outcome under test, returned to be asserted on
                return refusal

    with engine.connect() as other_tab:
        other_tab.execute(text("SELECT id FROM events WHERE id = :id FOR UPDATE"), {"id": event_id})
        for statement in other_tab_sql:
            other_tab.execute(text(statement), {"id": event_id})
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(attempt)
            pid = pids.get(timeout=LOCK_WAIT_SECONDS)
            blocked = _wait_until_waiting_on_a_lock(engine, pid)
            other_tab.commit()
            outcome = future.result(timeout=LOCK_WAIT_SECONDS * 3)
    assert blocked, f"the service call never waited for the row held by the other tab: {outcome!r}"
    return outcome


@pytest.mark.story("2.7", ac=12)
def test_an_edit_racing_a_submission_is_refused_and_leaves_the_submitted_requirements(engine):
    event_id, requirement_id = _committed_submittable_draft(
        engine, [_requirement("Plenary hall", 40)]
    )
    try:

        def edit(session: Session):
            organiser = session.get(User, Users.ORGANISER.id)
            change = EventUpdate(
                venue_requirements=[
                    {**_requirement("Edited after submit", 10), "id": requirement_id}
                ]
            )
            return service.update_event(session, event_id, change, actor=organiser)

        outcome = _run_while_the_row_is_held(
            engine,
            event_id,
            ["UPDATE events SET status = 'UNDER_REVIEW', submitted_at = now() WHERE id = :id"],
            edit,
        )

        assert isinstance(outcome, service.EventNotEditable), outcome
        with Session(engine) as session:
            assert [row.name for row in _requirement_rows(session, event_id)] == ["Plenary hall"]
            assert [row.capacity for row in _requirement_rows(session, event_id)] == [40]
    finally:
        _remove_event(engine, event_id)


@pytest.mark.story("2.7", ac=12)
def test_a_submission_racing_an_edit_checks_the_edited_requirements(engine):
    """The mirror image: an edit in the other tab makes the requirement incomplete while the
    submission is on its way. The submission must judge what the edit left, not what it read
    before the edit committed."""
    event_id, _ = _committed_submittable_draft(engine, [_requirement("Plenary hall", 40)])
    try:

        def submit(session: Session):
            organiser = session.get(User, Users.ORGANISER.id)
            return service.submit_event(session, event_id, actor=organiser)

        outcome = _run_while_the_row_is_held(
            engine,
            event_id,
            ["UPDATE venue_requirements SET capacity = NULL WHERE event_id = :id"],
            submit,
        )

        assert isinstance(outcome, service.MissingSubmissionDetails), outcome
        with Session(engine) as session:
            assert session.scalar(select(Event.status).where(Event.id == event_id)) == "DRAFT"
    finally:
        _remove_event(engine, event_id)
