"""Story 18.5 - register guests with my registration. INTEGRATION tests: the API on PostgreSQL.

Level: integration. Each test calls ``POST /registrations``, ``PUT /registrations/{id}/guests``,
18.2's ``GET /registrations`` and withdrawal, 18.1's ``GET /registrations/events`` or 18.3's
``GET /events/{event_id}/registrations`` through a signed-in client, against the real schema in
the rolled-back test transaction. A guest's own rules are unit-tested in
``test_register_guests_unit.py``; these check both endpoints apply them. The flows an attendee and
an organiser click through are e2e-tested in ``tests/e2e/register-guests.spec.ts``.

API calls run on the real clock, so events are made relative to today. A test that expects a
request to be refused commits its own rows first: a refused request rolls its session back, and
committing keeps that to the request's own work (the commit only releases a savepoint; the test's
transaction still rolls back). The race tests at the end commit real concurrent transactions on a
fixed clock, and clean up after themselves.

The ACs are the Product Backlog's (row 57, CL-173, CL-185), summarised:

AC1 When registering, the attendee can add guests, each with a name, optional dietary requirements
    (as 18.4 AC6) and no phone number; they are registered together as one group.
AC2 Each guest takes a place against the event's capacity; a group that does not fit is refused.
AC3 After registering, the attendee can add, change or remove guests, and sees them on My
    registrations - until registration closes, and not once withdrawn or cancelled (CL-185).
    Added guests that do not fit are refused.
AC4 The organiser and assigned coordinator see each guest under their attendee in the
    registration list (18.3), with their name and dietary requirements.
AC5 The change-impact count in 19.3 includes guests.
AC6 An attendee can bring 0 to 10 guests. Each guest's name is required.
AC7 Withdrawing a registration withdraws the whole group and frees all its places.
AC8 Cancelling the event (6.2) frees every place, guests included; only the attendee is notified.
AC9 A withdrawn group's guests are listed by name only, without their dietary requirements.
AC10 Only the attendee who made the registration can change its guests.
AC11 Two requests for the last places cannot both succeed.
"""

from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import NOT_PERMITTED_MESSAGE
from app.auth.models import User
from app.cancellations import service as cancellations_service
from app.common.audit import AuditLog
from app.events.models import Event, EventStatus
from app.notifications.models import Notification
from app.registrations import schemas, service
from app.registrations.models import EventRegistration, RegistrationStatus
from tests.support.factories import future_datetime, make_event, make_user
from tests.support.seed import Users

REGISTER_PATH = "/registrations"
EVENTS_PATH = "/registrations/events"
CONFIRMED_AT = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
REGISTERED_AT = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
RAVI = {"full_name": "Ravi Kumar", "dietary_requirements": "Vegetarian"}
MEI = {"full_name": "Mei Lin", "dietary_requirements": None}
STAFF = [
    pytest.param(Users.ORGANISER, id="organiser"),
    pytest.param(Users.COORDINATOR, id="coordinator"),
    pytest.param(Users.LEAD, id="lead"),
    pytest.param(Users.VENUE_STAFF, id="venue-staff"),
    pytest.param(Users.TECH_SUPPORT, id="tech-support"),
    pytest.param(Users.SAFETY_OFFICER, id="safety-officer"),
]


def _attendee(db: Session) -> User:
    """An attendee who gave their details before (18.4), so no registration asks for them."""
    return make_user(
        db, role="ATTENDEE", phone="+65 9123 4567", attendee_details_confirmed_at=CONFIRMED_AT
    )


def _open_event(db: Session, *, capacity: int = 50, **overrides) -> Event:
    """A Confirmed, Public event of Users.ORGANISER's, assigned to Users.COORDINATOR, taking
    registrations now on the real clock (18.1 AC1)."""
    starts_at = future_datetime(days=30)
    return make_event(
        db,
        status=overrides.pop("status", EventStatus.CONFIRMED),
        assigned_coordinator_id=Users.COORDINATOR.id,
        registration_required=True,
        is_public=True,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=3),
        registration_closes_at=overrides.pop(
            "registration_closes_at", starts_at - timedelta(days=1)
        ),
        expected_attendance=capacity,
        **overrides,
    )


def _closed_event(db: Session) -> Event:
    """Not yet started, but its registration closed yesterday."""
    return _open_event(db, registration_closes_at=datetime.now(UTC) - timedelta(days=1))


def _add_registration(
    db: Session,
    event: Event,
    attendee: User,
    *,
    guests: tuple[dict, ...] = (),
    status: str = RegistrationStatus.REGISTERED,
) -> EventRegistration:
    """A registration written straight to the tables, with its guests in the order given - so a
    test can set up what no request would make, such as more guests than the places left."""
    registration = EventRegistration(
        event_id=event.id,
        attendee_id=attendee.id,
        status=status,
        registered_at=REGISTERED_AT,
        withdrawn_at=REGISTERED_AT + timedelta(days=1)
        if status == RegistrationStatus.WITHDRAWN
        else None,
    )
    db.add(registration)
    db.flush()
    for position, guest in enumerate(guests, start=1):
        db.execute(
            text(
                "INSERT INTO event_registration_guests"
                " (registration_id, position, full_name, dietary_requirements)"
                " VALUES (:r, :p, :n, :d)"
            ),
            {
                "r": registration.id,
                "p": position,
                "n": guest["full_name"],
                "d": guest.get("dietary_requirements"),
            },
        )
    return registration


def _register(client, db: Session, event: Event, *, guests: list[dict] | None = None, **extra):
    """``POST /registrations`` as the signed-in attendee, the test's rows saved first."""
    db.commit()
    body: dict = {"event_id": str(event.id), **extra}
    if guests is not None:
        body["guests"] = guests
    return client.post(REGISTER_PATH, json=body)


def _change_guests(client, db: Session, registration_id: uuid.UUID, guests: list[dict]):
    """``PUT /registrations/{id}/guests`` as the signed-in attendee, the test's rows saved first."""
    db.commit()
    return client.put(f"{REGISTER_PATH}/{registration_id}/guests", json={"guests": guests})


def _guests_of(db: Session, registration_id: uuid.UUID) -> list[dict]:
    """The registration's guests as stored, in their order."""
    rows = db.execute(
        text(
            "SELECT full_name, dietary_requirements FROM event_registration_guests"
            " WHERE registration_id = :r ORDER BY position"
        ),
        {"r": registration_id},
    ).all()
    return [{"full_name": name, "dietary_requirements": dietary} for name, dietary in rows]


def _guest_count(db: Session, event: Event) -> int:
    """Every guest stored for the event, whatever their registration's status."""
    return db.execute(
        text(
            "SELECT count(*) FROM event_registration_guests AS g"
            " JOIN event_registrations AS r ON r.id = g.registration_id WHERE r.event_id = :e"
        ),
        {"e": event.id},
    ).scalar_one()


def _registrations_of(db: Session, event: Event) -> list[EventRegistration]:
    return list(db.scalars(select(EventRegistration).where(EventRegistration.event_id == event.id)))


def _listed(client, event: Event) -> dict:
    """The event as 18.1's Upcoming events lists it to the signed-in attendee."""
    items = client.get(EVENTS_PATH, params={"limit": 100}).json()["items"]
    [item] = [item for item in items if item["id"] == str(event.id)]
    return item


def _mine(client, event: Event) -> dict:
    """The signed-in attendee's registration for the event on 18.2's My registrations."""
    items = client.get(REGISTER_PATH).json()
    [item] = [item for item in items if item["event_id"] == str(event.id)]
    return item


def _list_row(client, event: Event, attendee: User) -> dict:
    """The attendee's one row on the event's registration list (18.3)."""
    rows = client.get(f"/events/{event.id}/registrations").json()["items"]
    [row] = [row for row in rows if row["attendee_email"] == attendee.email]
    return row


def _guest_audits(db: Session, registration_id: uuid.UUID) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.action == service.REGISTRATION_GUESTS_UPDATED_ACTION,
                AuditLog.entity_id == registration_id,
            )
        )
    )


# --- AC1: registering with guests -------------------------------------------------------------
@pytest.mark.story("18.5", ac=1)
def test_registering_with_guests_records_them_in_order_and_answers_with_them(client, db: Session):
    attendee = _attendee(db)
    event = _open_event(db)
    client.login(attendee.email)

    response = _register(client, db, event, guests=[RAVI, MEI])

    assert response.status_code == 201
    assert response.json()["guests"] == [RAVI, MEI]
    [registration] = _registrations_of(db, event)
    assert registration.attendee_id == attendee.id
    assert _guests_of(db, registration.id) == [RAVI, MEI]


@pytest.mark.story("18.5", ac=1)
def test_a_first_registration_saves_the_details_and_the_guests_together(client, db: Session):
    """18.4 AC2's first registration, with guests: both are written in the one request."""
    attendee = make_user(db, role="ATTENDEE", attendee_details_confirmed_at=None)
    event = _open_event(db)
    client.login(attendee.email)

    response = _register(
        client,
        db,
        event,
        guests=[RAVI],
        details={"full_name": attendee.full_name, "phone": "+65 9876 5432"},
    )

    assert response.status_code == 201
    db.refresh(attendee)
    assert attendee.phone == "+65 9876 5432"
    [registration] = _registrations_of(db, event)
    assert _guests_of(db, registration.id) == [RAVI]


@pytest.mark.story("18.5", ac=1)
def test_a_first_registration_without_details_saves_none_of_its_guests(client, db: Session):
    attendee = make_user(db, role="ATTENDEE", attendee_details_confirmed_at=None)
    event = _open_event(db)
    client.login(attendee.email)

    response = _register(client, db, event, guests=[RAVI])

    assert response.status_code == 409
    assert response.json()["detail"] == service.ATTENDEE_DETAILS_REQUIRED_MESSAGE
    assert _registrations_of(db, event) == []
    assert _guest_count(db, event) == 0


# --- AC2: each guest takes a place ------------------------------------------------------------
@pytest.mark.story("18.5", ac=2)
def test_a_group_takes_a_place_for_each_member(client, db: Session):
    attendee = _attendee(db)
    event = _open_event(db, capacity=10)
    client.login(attendee.email)

    _register(client, db, event, guests=[RAVI, MEI])

    assert _listed(client, event)["places_left"] == 7


@pytest.mark.story("18.5", ac=2)
def test_the_events_page_takes_a_place_for_each_member_too(client, db: Session):
    """18.1 AC9 (fix f18.1.2): where the attendee registers, the event's own page, counts the
    group as its list entry does."""
    attendee = _attendee(db)
    event = _open_event(db, capacity=10)
    client.login(attendee.email)

    _register(client, db, event, guests=[RAVI, MEI])

    assert client.get(f"{EVENTS_PATH}/{event.id}").json()["places_left"] == 7


@pytest.mark.story("18.5", ac=2)
def test_a_group_filling_the_last_places_leaves_the_event_full_for_others(client, db: Session):
    attendee = _attendee(db)
    other = _attendee(db)
    event = _open_event(db, capacity=3)
    client.login(attendee.email)
    _register(client, db, event, guests=[RAVI, MEI])

    client.login(other.email)
    listed = _listed(client, event)

    assert listed["places_left"] == 0
    assert listed["state"] == "FULL"


# --- AC3: changing the guests afterwards ------------------------------------------------------
@pytest.mark.story("18.5", ac=3)
def test_guests_can_be_added_after_registering(client, db: Session):
    attendee = _attendee(db)
    event = _open_event(db, capacity=10)
    registration = _add_registration(db, event, attendee)
    client.login(attendee.email)

    response = _change_guests(client, db, registration.id, [RAVI, MEI])

    assert response.status_code == 200
    assert response.json()["guests"] == [RAVI, MEI]
    assert _guests_of(db, registration.id) == [RAVI, MEI]
    assert _listed(client, event)["places_left"] == 7


@pytest.mark.story("18.5", ac=2)
@pytest.mark.story("18.5", ac=3)
def test_guests_can_be_renamed_and_one_removed_and_the_place_is_freed(client, db: Session):
    attendee = _attendee(db)
    event = _open_event(db, capacity=10)
    registration = _add_registration(db, event, attendee, guests=(RAVI, MEI))
    client.login(attendee.email)
    renamed = {"full_name": "Mei Lin Tan", "dietary_requirements": "Halal"}

    response = _change_guests(client, db, registration.id, [renamed])

    assert response.status_code == 200
    assert _guests_of(db, registration.id) == [renamed]
    db.refresh(registration)
    assert registration.status == RegistrationStatus.REGISTERED
    assert _listed(client, event)["places_left"] == 8


@pytest.mark.story("18.5", ac=3)
def test_removing_every_guest_leaves_the_attendee_registered_alone(client, db: Session):
    attendee = _attendee(db)
    event = _open_event(db, capacity=10)
    registration = _add_registration(db, event, attendee, guests=(RAVI, MEI))
    client.login(attendee.email)

    response = _change_guests(client, db, registration.id, [])

    assert response.status_code == 200
    assert response.json()["status"] == "REGISTERED"
    assert _guests_of(db, registration.id) == []
    assert _listed(client, event)["places_left"] == 9


@pytest.mark.story("18.5", ac=3)
def test_a_change_to_the_guests_is_audited_with_their_number_not_their_names(client, db: Session):
    attendee = _attendee(db)
    event = _open_event(db)
    registration = _add_registration(db, event, attendee)
    client.login(attendee.email)

    _change_guests(client, db, registration.id, [RAVI])

    [audit] = _guest_audits(db, registration.id)
    assert audit.actor_id == attendee.id
    assert audit.details == {"event_id": str(event.id), "guest_count": 1}
    assert "Ravi" not in json.dumps(audit.details)


@pytest.mark.story("18.5", ac=1)
def test_registering_with_guests_is_audited_with_their_number_not_their_names(client, db: Session):
    """As a later change to them is: the group's size is in the log from the start."""
    attendee = _attendee(db)
    event = _open_event(db)
    client.login(attendee.email)

    _register(client, db, event, guests=[RAVI, MEI])

    [registration] = _registrations_of(db, event)
    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == service.REGISTRATION_CREATED_ACTION,
            AuditLog.entity_id == registration.id,
        )
    )
    assert audit.details == {"event_id": str(event.id), "guest_count": 2}
    assert "Ravi" not in json.dumps(audit.details)


# --- AC3: the attendee sees their guests ------------------------------------------------------
@pytest.mark.story("18.5", ac=3)
def test_my_registrations_show_each_registrations_guests_in_order(client, db: Session):
    attendee = _attendee(db)
    with_guests = _open_event(db)
    alone = _open_event(db)
    _add_registration(db, with_guests, attendee, guests=(RAVI, MEI))
    _add_registration(db, alone, attendee)
    client.login(attendee.email)

    assert _mine(client, with_guests)["guests"] == [RAVI, MEI]
    assert _mine(client, alone)["guests"] == []


@pytest.mark.story("18.5", ac=3)
def test_my_registrations_say_whether_the_guests_can_still_be_changed(client, db: Session):
    attendee = _attendee(db)
    open_event = _open_event(db)
    closed_event = _closed_event(db)
    _add_registration(db, open_event, attendee)
    _add_registration(db, closed_event, attendee)
    client.login(attendee.email)

    assert _mine(client, open_event)["can_change_guests"] is True
    assert _mine(client, closed_event)["can_change_guests"] is False


# --- AC4: the registration list ---------------------------------------------------------------
@pytest.mark.story("18.5", ac=4)
def test_the_organiser_sees_each_attendees_guests_with_their_dietary_requirements(
    organiser_client, db: Session
):
    event = _open_event(db)
    attendee = _attendee(db)
    _add_registration(db, event, attendee, guests=(RAVI, MEI))

    row = _list_row(organiser_client, event, attendee)

    assert row["guests"] == [RAVI, MEI]


@pytest.mark.story("18.5", ac=4)
def test_the_assigned_coordinator_sees_the_same_guests(coordinator_client, db: Session):
    event = _open_event(db)
    attendee = _attendee(db)
    _add_registration(db, event, attendee, guests=(RAVI,))

    assert _list_row(coordinator_client, event, attendee)["guests"] == [RAVI]


@pytest.mark.story("18.5", ac=4)
def test_the_lists_count_includes_guests_and_says_full_when_they_fill_it(
    organiser_client, db: Session
):
    event = _open_event(db, capacity=4)
    _add_registration(db, event, _attendee(db), guests=(RAVI, MEI))
    _add_registration(db, event, _attendee(db))

    listing = organiser_client.get(f"/events/{event.id}/registrations").json()

    assert listing["active_count"] == 4
    assert listing["is_full"] is True


@pytest.mark.story("18.5", ac=7)
@pytest.mark.story("18.5", ac=9)
def test_a_withdrawn_group_is_listed_by_name_without_dietary_requirements_or_places(
    organiser_client, db: Session
):
    """As 18.4 AC9 does for the attendee's own details."""
    event = _open_event(db, capacity=10)
    attendee = _attendee(db)
    _add_registration(db, event, attendee, guests=(RAVI,), status=RegistrationStatus.WITHDRAWN)

    listing = organiser_client.get(f"/events/{event.id}/registrations").json()

    [row] = listing["items"]
    assert row["guests"] == [{"full_name": "Ravi Kumar", "dietary_requirements": None}]
    assert listing["active_count"] == 0


# --- AC6: at most ten guests ------------------------------------------------------------------
@pytest.mark.story("18.5", ac=6)
def test_ten_guests_are_registered_and_take_eleven_places(client, db: Session):
    attendee = _attendee(db)
    event = _open_event(db, capacity=20)
    client.login(attendee.email)
    guests = [{"full_name": f"Guest {n}"} for n in range(1, 11)]

    response = _register(client, db, event, guests=guests)

    assert response.status_code == 201
    assert len(response.json()["guests"]) == 10
    assert _listed(client, event)["places_left"] == 9


@pytest.mark.story("18.5", ac=6)
def test_eleven_guests_are_refused_and_nothing_is_written(client, db: Session):
    attendee = _attendee(db)
    event = _open_event(db, capacity=50)
    client.login(attendee.email)
    guests = [{"full_name": f"Guest {n}"} for n in range(1, 12)]

    response = _register(client, db, event, guests=guests)

    assert response.status_code == 422
    assert schemas.TOO_MANY_GUESTS_MESSAGE in json.dumps(response.json())
    assert _registrations_of(db, event) == []


@pytest.mark.story("18.5", ac=6)
def test_a_change_to_eleven_guests_is_refused_and_the_guests_stay_as_they_were(client, db: Session):
    attendee = _attendee(db)
    event = _open_event(db, capacity=50)
    registration = _add_registration(db, event, attendee, guests=(RAVI,))
    client.login(attendee.email)
    guests = [{"full_name": f"Guest {n}"} for n in range(1, 12)]

    response = _change_guests(client, db, registration.id, guests)

    assert response.status_code == 422
    assert _guests_of(db, registration.id) == [RAVI]


@pytest.mark.story("18.5", ac=6)
def test_a_registration_without_guests_answers_with_none(client, db: Session):
    attendee = _attendee(db)
    event = _open_event(db)
    client.login(attendee.email)

    response = _register(client, db, event)

    assert response.status_code == 201
    assert response.json()["guests"] == []


# --- AC1/AC6: a guest's details ---------------------------------------------------------------
@pytest.mark.story("18.5", ac=1)
@pytest.mark.story("18.5", ac=6)
@pytest.mark.parametrize(
    "guest",
    [
        {"full_name": "   "},
        {"full_name": "n" * 201},
        {"full_name": "Ravi Kumar", "dietary_requirements": "v" * 501},
        {"full_name": "Ravi Kumar", "phone": "+65 9123 4567"},
    ],
    ids=["name-blank", "name-long", "dietary-long", "phone"],
)
def test_a_guest_outside_the_rules_is_refused_and_nothing_is_written(
    client, db: Session, guest: dict
):
    attendee = _attendee(db)
    event = _open_event(db)
    client.login(attendee.email)

    response = _register(client, db, event, guests=[RAVI, guest])

    assert response.status_code == 422
    assert _registrations_of(db, event) == []
    assert _guest_count(db, event) == 0


@pytest.mark.story("18.5", ac=1)
def test_a_guests_blank_dietary_requirements_are_stored_as_none(client, db: Session):
    attendee = _attendee(db)
    event = _open_event(db)
    client.login(attendee.email)

    _register(
        client, db, event, guests=[{"full_name": " Ravi Kumar ", "dietary_requirements": "  "}]
    )

    [registration] = _registrations_of(db, event)
    assert _guests_of(db, registration.id) == [
        {"full_name": "Ravi Kumar", "dietary_requirements": None}
    ]


@pytest.mark.story("18.5", ac=1)
@pytest.mark.story("18.5", ac=6)
@pytest.mark.parametrize(
    ("position", "full_name", "dietary"),
    [(11, "Guest 11", None), (0, "Guest 0", None), (1, "   ", None), (1, "Ravi", " ")],
    ids=["eleventh", "position-0", "blank-name", "blank-dietary"],
)
def test_the_database_refuses_a_guest_outside_the_rules(
    db: Session, position: int, full_name: str, dietary: str | None
):
    registration = _add_registration(db, _open_event(db), _attendee(db))

    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO event_registration_guests"
                " (registration_id, position, full_name, dietary_requirements)"
                " VALUES (:r, :p, :n, :d)"
            ),
            {"r": registration.id, "p": position, "n": full_name, "d": dietary},
        )


@pytest.mark.story("18.5", ac=6)
def test_the_database_refuses_two_guests_in_one_place_of_a_group(db: Session):
    registration = _add_registration(db, _open_event(db), _attendee(db), guests=(RAVI,))

    with pytest.raises(IntegrityError) as caught:
        db.execute(
            text(
                "INSERT INTO event_registration_guests (registration_id, position, full_name)"
                " VALUES (:r, 1, 'Mei Lin')"
            ),
            {"r": registration.id},
        )

    assert "uq_event_registration_guests_position" in str(caught.value.orig)


# --- AC7: withdrawing withdraws the group -----------------------------------------------------
@pytest.mark.story("18.5", ac=7)
def test_withdrawing_withdraws_the_whole_group_and_frees_every_place(client, db: Session):
    attendee = _attendee(db)
    event = _open_event(db, capacity=3)
    registration = _add_registration(db, event, attendee, guests=(RAVI, MEI))
    client.login(attendee.email)
    db.commit()

    response = client.post(f"{REGISTER_PATH}/{registration.id}/withdraw")

    assert response.status_code == 200
    assert response.json()["status"] == "WITHDRAWN"
    assert response.json()["can_change_guests"] is False
    other = _attendee(db)
    db.commit()
    client.login(other.email)
    assert _listed(client, event)["places_left"] == 3


# --- AC3 (CL-185): when the guests can no longer change ---------------------------------------
@pytest.mark.story("18.5", ac=3)
def test_guests_cannot_be_changed_once_registration_has_closed(client, db: Session):
    attendee = _attendee(db)
    registration = _add_registration(db, _closed_event(db), attendee, guests=(RAVI,))
    client.login(attendee.email)

    response = _change_guests(client, db, registration.id, [])

    assert response.status_code == 409
    assert response.json()["detail"] == service.GUESTS_REGISTRATION_CLOSED_MESSAGE
    assert _guests_of(db, registration.id) == [RAVI]


@pytest.mark.story("18.5", ac=3)
@pytest.mark.parametrize(
    "change",
    [
        {"status": EventStatus.PLANNING},
        {"is_public": False},
        {"registration_required": False},
    ],
    ids=["sent-back-to-planning", "made-private", "no-longer-taking-registrations"],
)
def test_guests_cannot_be_changed_once_the_event_stops_taking_registrations(
    client, db: Session, change: dict
):
    """The event still before its closing time, but no longer open to attendees (18.1 AC4)."""
    attendee = _attendee(db)
    event = _open_event(db)
    registration = _add_registration(db, event, attendee, guests=(RAVI,))
    for field, value in change.items():
        setattr(event, field, value)
    client.login(attendee.email)

    response = _change_guests(client, db, registration.id, [])

    assert response.status_code == 409
    assert response.json()["detail"] == service.GUESTS_REGISTRATION_CLOSED_MESSAGE
    assert _guests_of(db, registration.id) == [RAVI]


@pytest.mark.story("18.5", ac=3)
def test_guests_can_be_changed_until_the_closing_moment_and_not_at_it(db: Session):
    """The closing moment itself is closed, as 18.1 refuses a registration at it."""
    event = _open_event(db)
    closes_at = event.registration_closes_at
    registered = service.RegistrationStanding.REGISTERED

    just_before = service.guests_change_refusal(
        standing=registered, event=event, now=closes_at - timedelta(microseconds=1)
    )
    at_closing = service.guests_change_refusal(standing=registered, event=event, now=closes_at)

    assert just_before is None
    assert isinstance(at_closing, service.GuestsRegistrationClosed)


@pytest.mark.story("18.5", ac=3)
def test_guests_cannot_be_changed_after_withdrawing(client, db: Session):
    attendee = _attendee(db)
    registration = _add_registration(
        db, _open_event(db), attendee, guests=(RAVI,), status=RegistrationStatus.WITHDRAWN
    )
    client.login(attendee.email)

    response = _change_guests(client, db, registration.id, [RAVI, MEI])

    assert response.status_code == 409
    assert response.json()["detail"] == service.GUESTS_WITHDRAWN_MESSAGE
    assert _guests_of(db, registration.id) == [RAVI]


@pytest.mark.story("18.5", ac=3)
def test_guests_cannot_be_changed_once_the_event_is_cancelled(client, db: Session):
    attendee = _attendee(db)
    event = _open_event(db, status=EventStatus.CANCELLED)
    registration = _add_registration(
        db, event, attendee, guests=(RAVI,), status=RegistrationStatus.CANCELLED
    )
    client.login(attendee.email)

    response = _change_guests(client, db, registration.id, [])

    assert response.status_code == 409
    assert response.json()["detail"] == service.GUESTS_EVENT_CANCELLED_MESSAGE
    assert _guests_of(db, registration.id) == [RAVI]


# --- AC8: cancelling the event ----------------------------------------------------------------
@pytest.mark.story("18.5", ac=8)
def test_cancelling_the_event_releases_every_guests_place(db: Session):
    event = _open_event(db)
    _add_registration(db, event, _attendee(db), guests=(RAVI, MEI))

    service.cancel_for_event(db, event.id)

    assert service.count_places_taken(db, event.id) == 0


@pytest.mark.story("18.5", ac=8)
def test_cancelling_the_event_notifies_the_attendee_and_not_their_guests(db: Session):
    """Guests have no account (AC1), so the one attendee of a group of three is told, once."""
    event = _open_event(db)
    attendee = _attendee(db)
    _add_registration(db, event, attendee, guests=(RAVI, MEI))

    cancellations_service.cancel_event(
        db, event.id, actor=db.get(User, Users.ORGANISER.id), reason="The venue flooded."
    )

    told = db.scalars(
        select(Notification.recipient_id).where(
            Notification.event_id == event.id,
            Notification.notification_type == "REGISTRATION_CANCELLED",
        )
    ).all()
    assert told == [attendee.id]


# --- AC5: 19.3's change-impact count ----------------------------------------------------------
@pytest.mark.story("18.5", ac=5)
def test_the_count_19_3_reports_includes_every_registered_attendees_guests(db: Session):
    """19.3 reports ``count_places_taken`` beside a change request (its AC1)."""
    event = _open_event(db)
    _add_registration(db, event, _attendee(db), guests=(RAVI, MEI))
    _add_registration(db, event, _attendee(db))
    _add_registration(db, event, _attendee(db), guests=(RAVI,), status=RegistrationStatus.WITHDRAWN)

    count = service.count_places_taken(db, event.id)

    assert count == 4
    assert type(count) is int  # PostgreSQL sums a count as numeric, which reads as a Decimal


# --- AC10: only the attendee's own registration -----------------------------------------------
@pytest.mark.story("18.5", ac=10)
def test_another_attendees_guests_are_not_found_and_stay_as_they_were(client, db: Session):
    owner = _attendee(db)
    registration = _add_registration(db, _open_event(db), owner, guests=(RAVI,))
    client.login(_attendee(db).email)

    response = _change_guests(client, db, registration.id, [MEI])

    assert response.status_code == 404
    assert response.json()["detail"] == service.REGISTRATION_NOT_FOUND_MESSAGE
    assert _guests_of(db, registration.id) == [RAVI]


@pytest.mark.story("18.5", ac=10)
def test_an_unknown_registration_is_not_found(client, db: Session):
    client.login(_attendee(db).email)

    response = _change_guests(client, db, uuid.uuid4(), [RAVI])

    assert response.status_code == 404
    assert response.json()["detail"] == service.REGISTRATION_NOT_FOUND_MESSAGE


@pytest.mark.story("18.5", ac=10)
@pytest.mark.parametrize("user", STAFF)
def test_staff_cannot_change_an_attendees_guests(login_as, db: Session, user):
    registration = _add_registration(db, _open_event(db), _attendee(db), guests=(RAVI,))
    db.commit()

    response = login_as(user).put(f"{REGISTER_PATH}/{registration.id}/guests", json={"guests": []})

    assert response.status_code == 403
    assert response.json()["detail"] == NOT_PERMITTED_MESSAGE
    assert _guests_of(db, registration.id) == [RAVI]


@pytest.mark.story("18.5", ac=10)
def test_signed_out_users_cannot_change_guests(client, db: Session):
    registration = _add_registration(db, _open_event(db), _attendee(db), guests=(RAVI,))

    response = _change_guests(client, db, registration.id, [])

    assert response.status_code == 401
    assert _guests_of(db, registration.id) == [RAVI]


@pytest.mark.story("18.5", ac=10)
def test_a_guest_is_not_made_a_user(client, db: Session):
    attendee = _attendee(db)
    event = _open_event(db)
    client.login(attendee.email)

    _register(client, db, event, guests=[RAVI])

    assert db.scalar(select(User).where(User.full_name == RAVI["full_name"])) is None


# --- AC2/AC3: a group, or added guests, that do not fit ---------------------------------------
@pytest.mark.story("18.5", ac=2)
def test_a_group_larger_than_the_places_left_is_refused_whole(client, db: Session):
    event = _open_event(db, capacity=3)
    _add_registration(db, event, _attendee(db))
    attendee = _attendee(db)
    client.login(attendee.email)

    response = _register(client, db, event, guests=[RAVI, MEI])

    assert response.status_code == 409
    assert response.json()["detail"] == service.NOT_ENOUGH_PLACES_MESSAGE
    assert attendee.id not in [r.attendee_id for r in _registrations_of(db, event)]
    assert _guest_count(db, event) == 0


@pytest.mark.story("18.5", ac=2)
def test_a_group_filling_exactly_the_places_left_is_registered(client, db: Session):
    event = _open_event(db, capacity=3)
    attendee = _attendee(db)
    client.login(attendee.email)

    response = _register(client, db, event, guests=[RAVI, MEI])

    assert response.status_code == 201
    [registration] = _registrations_of(db, event)
    assert _guests_of(db, registration.id) == [RAVI, MEI]
    client.login(_attendee(db).email)
    assert _listed(client, event)["state"] == "FULL"


@pytest.mark.story("18.5", ac=2)
@pytest.mark.story("18.5", ac=6)
def test_an_attendee_alone_still_hears_that_the_event_is_full(client, db: Session):
    """No guests: 18.1's refusal, word for word."""
    event = _open_event(db, capacity=1)
    _add_registration(db, event, _attendee(db))
    client.login(_attendee(db).email)

    response = _register(client, db, event)

    assert response.status_code == 409
    assert response.json()["detail"] == service.EVENT_FULL_MESSAGE


@pytest.mark.story("18.5", ac=3)
def test_guests_beyond_the_places_left_are_refused_and_the_guests_stay_as_they_were(
    client, db: Session
):
    event = _open_event(db, capacity=3)
    attendee = _attendee(db)
    registration = _add_registration(db, event, attendee, guests=(RAVI,))
    client.login(attendee.email)

    response = _change_guests(client, db, registration.id, [RAVI, MEI, {"full_name": "Ana"}])

    assert response.status_code == 409
    assert response.json()["detail"] == service.GUESTS_NOT_ENOUGH_PLACES_MESSAGE
    assert _guests_of(db, registration.id) == [RAVI]
    assert _guest_audits(db, registration.id) == []


@pytest.mark.story("18.5", ac=3)
def test_guests_filling_exactly_the_places_left_are_accepted(client, db: Session):
    event = _open_event(db, capacity=3)
    attendee = _attendee(db)
    registration = _add_registration(db, event, attendee)
    client.login(attendee.email)

    response = _change_guests(client, db, registration.id, [RAVI, MEI])

    assert response.status_code == 200


@pytest.mark.story("18.5", ac=3)
def test_guests_can_still_be_removed_from_an_event_already_over_its_capacity(client, db: Session):
    """The capacity was lowered below the places taken (a 19.2 change): a smaller group must not
    be refused for a shortage it does not add to."""
    event = _open_event(db, capacity=1)
    attendee = _attendee(db)
    registration = _add_registration(db, event, attendee, guests=(RAVI, MEI))
    client.login(attendee.email)

    response = _change_guests(client, db, registration.id, [RAVI])

    assert response.status_code == 200
    assert _guests_of(db, registration.id) == [RAVI]


@pytest.mark.story("18.5", ac=3)
def test_guests_can_be_renamed_on_an_event_already_over_its_capacity(client, db: Session):
    """As many guests as before take no more places, so only a larger group is counted."""
    event = _open_event(db, capacity=1)
    attendee = _attendee(db)
    registration = _add_registration(db, event, attendee, guests=(RAVI, MEI))
    client.login(attendee.email)
    renamed = {"full_name": "Ravi Kumar Jr", "dietary_requirements": "Vegan"}

    response = _change_guests(client, db, registration.id, [renamed, MEI])

    assert response.status_code == 200
    assert _guests_of(db, registration.id) == [renamed, MEI]


def _take_places(db: Session, event: Event, places: int) -> None:
    """``places`` places taken at ``event`` by other attendees: groups of eleven (an attendee and
    ten guests), then attendees alone for the rest."""
    full_groups, alone = divmod(places, 1 + schemas.MAX_GUESTS)
    ten_guests = tuple({"full_name": f"Guest {n}"} for n in range(1, schemas.MAX_GUESTS + 1))
    for _ in range(full_groups):
        _add_registration(db, event, _attendee(db), guests=ten_guests)
    for _ in range(alone):
        _add_registration(db, event, _attendee(db))


@pytest.mark.story("18.5", ac=2)
def test_with_48_of_50_places_taken_a_sign_up_brings_one_guest_and_fills_the_event(
    client, db: Session
):
    """AC2 worked through: 48 of 50 places taken, guests included. A sign-up may
    bring one guest, which fills the event, and no one can register after it."""
    event = _open_event(db, capacity=50)
    _take_places(db, event, 48)
    assert service.count_places_taken(db, event.id) == 48
    attendee = _attendee(db)
    late = _attendee(db)
    client.login(attendee.email)

    response = _register(client, db, event, guests=[RAVI])

    assert response.status_code == 201
    assert service.count_places_taken(db, event.id) == 50
    client.login(late.email)
    assert _listed(client, event)["state"] == "FULL"
    refused = _register(client, db, event)
    assert refused.status_code == 409
    assert refused.json()["detail"] == service.EVENT_FULL_MESSAGE


@pytest.mark.story("18.5", ac=2)
def test_with_48_of_50_places_taken_a_sign_up_with_two_guests_is_refused_whole(client, db: Session):
    """The PO's example: two guests would make 51 of 50, so nothing is registered."""
    event = _open_event(db, capacity=50)
    _take_places(db, event, 48)
    attendee = _attendee(db)
    client.login(attendee.email)

    response = _register(client, db, event, guests=[RAVI, MEI])

    assert response.status_code == 409
    assert response.json()["detail"] == service.NOT_ENOUGH_PLACES_MESSAGE
    assert attendee.id not in [r.attendee_id for r in _registrations_of(db, event)]
    assert service.count_places_taken(db, event.id) == 48


# --- AC3: how many guests My registrations allows ---------------------------------------------
@pytest.mark.story("18.5", ac=3)
def test_my_registrations_allow_the_guests_there_are_places_for(client, db: Session):
    """5 places: the attendee and one guest hold 2, another attendee 1, so 2 are left. Their guests
    may grow by those 2, from one guest to three."""
    event = _open_event(db, capacity=5)
    attendee = _attendee(db)
    _add_registration(db, event, attendee, guests=(RAVI,))
    _add_registration(db, event, _attendee(db))
    client.login(attendee.email)
    db.commit()

    assert _mine(client, event)["max_guests"] == 3


@pytest.mark.story("18.5", ac=3)
@pytest.mark.story("18.5", ac=6)
def test_my_registrations_allow_no_more_than_ten_guests_however_many_places_are_left(
    client, db: Session
):
    event = _open_event(db, capacity=50)
    attendee = _attendee(db)
    _add_registration(db, event, attendee, guests=(RAVI,))
    client.login(attendee.email)
    db.commit()

    assert _mine(client, event)["max_guests"] == schemas.MAX_GUESTS


@pytest.mark.story("18.5", ac=3)
def test_my_registrations_never_ask_for_fewer_guests_than_an_overfull_event_already_has(
    client, db: Session
):
    """Capacity lowered below the places taken (19.2): no places are left, but the guests
    already registered are kept, so the limit is never below them."""
    event = _open_event(db, capacity=1)
    attendee = _attendee(db)
    _add_registration(db, event, attendee, guests=(RAVI, MEI))
    client.login(attendee.email)
    db.commit()

    assert _mine(client, event)["max_guests"] == 2


@pytest.mark.story("18.5", ac=3)
def test_a_change_to_the_guests_answers_with_the_new_limit(client, db: Session):
    """Adding guests uses up places: the answer's limit is worked out after the change."""
    event = _open_event(db, capacity=5)
    attendee = _attendee(db)
    registration = _add_registration(db, event, attendee)
    client.login(attendee.email)

    response = _change_guests(client, db, registration.id, [RAVI, MEI])

    assert response.status_code == 200
    assert response.json()["max_guests"] == 4


# =============================================================================================
# AC11 - real concurrent transactions. These commit, so each cleans up after itself.
# =============================================================================================
# After every seeded event has started, as in test_browse_and_register_integration.py.
NOW = datetime(2030, 1, 15, 9, 0, tzinfo=UTC)
CHANGED = "changed"
REGISTERED = "registered"


@dataclass(frozen=True)
class _Race:
    event_id: uuid.UUID
    attendee_ids: list[uuid.UUID]
    registration_id: uuid.UUID


def _race(engine: Engine, *, capacity: int) -> _Race:
    """An event with ``capacity`` places, the first of two attendees registered for it alone."""
    with Session(engine) as session:
        starts_at = NOW + timedelta(days=30)
        event = make_event(
            session,
            status=EventStatus.CONFIRMED,
            assigned_coordinator_id=Users.COORDINATOR.id,
            registration_required=True,
            is_public=True,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=3),
            registration_closes_at=starts_at - timedelta(days=1),
            expected_attendance=capacity,
        )
        people = [_attendee(session) for _ in range(2)]
        registration = EventRegistration(
            event_id=event.id, attendee_id=people[0].id, registered_at=NOW
        )
        session.add(registration)
        session.commit()
        return _Race(
            event_id=event.id,
            attendee_ids=[person.id for person in people],
            registration_id=registration.id,
        )


def _clean_up(engine: Engine, race: _Race) -> None:
    with Session(engine) as session:
        session.execute(delete(AuditLog).where(AuditLog.actor_id.in_(race.attendee_ids)))
        session.execute(
            delete(EventRegistration).where(EventRegistration.event_id == race.event_id)
        )
        session.execute(delete(Event).where(Event.id == race.event_id))
        session.execute(delete(User).where(User.id.in_(race.attendee_ids)))
        session.commit()


def _change_at_once(
    engine: Engine, race: _Race, guests: list[dict], start: threading.Barrier
) -> str:
    """The first attendee's change to their guests, in a session of its own."""
    with Session(engine) as session:
        attendee = session.get(User, race.attendee_ids[0])
        start.wait()
        try:
            service.update_guests(
                session,
                race.registration_id,
                schemas.GuestsUpdate(guests=guests),
                attendee=attendee,
                now=NOW,
            )
        except service.GuestsChangeRefused as refusal:
            return str(refusal)
        return CHANGED


def _register_at_once(engine: Engine, race: _Race, start: threading.Barrier) -> str:
    """The second attendee's registration, alone, in a session of its own."""
    with Session(engine) as session:
        attendee = session.get(User, race.attendee_ids[1])
        start.wait()
        try:
            service.register(
                session,
                schemas.RegistrationCreate(event_id=race.event_id),
                attendee=attendee,
                now=NOW,
            )
        except service.RegistrationRefused as refusal:
            return str(refusal)
        return REGISTERED


@pytest.mark.story("18.5", ac=11)
def test_guests_added_while_another_attendee_takes_the_last_place_leave_one_of_them(
    engine: Engine,
):
    """Three places, one taken. Two guests and a second attendee both want the other two."""
    race = _race(engine, capacity=3)
    start = threading.Barrier(2, timeout=10)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            change = pool.submit(_change_at_once, engine, race, [RAVI, MEI], start)
            registration = pool.submit(_register_at_once, engine, race, start)
            outcomes = {change.result(timeout=30), registration.result(timeout=30)}

        assert outcomes in (
            {CHANGED, service.EVENT_FULL_MESSAGE},
            {service.GUESTS_NOT_ENOUGH_PLACES_MESSAGE, REGISTERED},
        )
        with Session(engine) as session:
            assert service.count_places_taken(session, race.event_id) <= 3
    finally:
        _clean_up(engine, race)


@pytest.mark.story("18.5", ac=3)
@pytest.mark.story("18.5", ac=11)
def test_two_changes_to_the_guests_at_once_leave_one_list_whole(engine: Engine):
    """The same page open in two tabs: the guests end as one tab sent them, never a mix."""
    race = _race(engine, capacity=20)
    start = threading.Barrier(2, timeout=10)
    first_tab = [RAVI, MEI]
    second_tab = [{"full_name": "Ana Cruz", "dietary_requirements": None}]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            changes = [
                pool.submit(_change_at_once, engine, race, guests, start)
                for guests in (first_tab, second_tab)
            ]
            outcomes = [change.result(timeout=30) for change in changes]

        assert outcomes == [CHANGED, CHANGED]
        with Session(engine) as session:
            assert _guests_of(session, race.registration_id) in (first_tab, second_tab)
    finally:
        _clean_up(engine, race)
