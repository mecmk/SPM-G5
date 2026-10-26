"""Story 18.4 - autofill attendee profile details. INTEGRATION tests: the API on PostgreSQL.

Level: integration. Each test calls ``GET`` / ``PATCH /profile``, ``POST /registrations`` or 18.3's
``GET /events/{event_id}/registrations`` through a signed-in client, against the real schema in
the rolled-back test transaction. The details' own rules are unit-tested in
``test_attendee_profile_unit.py`` and the phone rule in ``tests/common/test_phone_unit.py``; these
check both endpoints apply them. The flows an attendee and an organiser click through are
e2e-tested in ``tests/e2e/attendee-profile.spec.ts``.

API calls run on the real clock, so events are made relative to today. A test that expects a
registration to be refused commits its own rows first: a refused registration rolls its session
back, and committing keeps that to the registration's own work (the commit only releases a
savepoint; the test's transaction still rolls back).

AC1 An attendee has a My profile page that shows their name and email, which they cannot change,
    and the details they keep up to date: a contact phone number and their dietary requirements.
AC2 The first time an attendee registers for an event (18.1), they are asked for these details
    before the registration is confirmed. The details are saved to their profile, so later
    registrations do not ask again. (A registration refused for any reason saves none of the
    details sent with it: PO decision, 24 Oct 2026.)
AC3 These details are remembered and filled in automatically for later event registrations.
    Changing them while registering for a later event updates the profile.
AC4 The attendee can change their details on My profile at any time. The change shows wherever
    their details are shown, including on events they registered for earlier.
AC5 The event's organiser and assigned coordinator see each registered attendee's phone number and
    dietary requirements on the event's registration list (18.3).
AC6 Dietary requirements are free text of up to 500 characters. Left blank, or only spaces, they
    are recorded as "None" (sent as null, shown as "None").
AC7 The phone number is required (PO decision, 25 Oct 2026, changing "optional"), and follows the
    rule for an event's contact phone (2.1 AC13): an attendee who has given their details always
    has one (ck_users_attendee_details_have_phone).
AC9 Withdrawn registrations do not show the attendee's details on the registration list. (Nor do
    the registrations of a cancelled event: only a Registered row shows them, PO decision.)
AC1 (as changed, 25 Oct 2026) The attendee's name is editable and required, at most 200
    characters; the email stays fixed.
AC10 An attendee can see and change only their own profile. An event's registrants' details are
    shown only to its organiser and assigned coordinator. (Who may open the list at all is 18.3's
    rule, proven by ``test_registration_list_integration.py``.)
AC11 If the attendee saves their profile in two tabs, the later save wins, and reloading shows
    what was saved.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import NOT_PERMITTED_MESSAGE
from app.auth.models import User
from app.common.audit import AuditLog
from app.events.models import Event, EventStatus
from app.registrations import schemas, service
from app.registrations.models import EventRegistration, RegistrationStatus
from tests.support.factories import future_datetime, make_event, make_user
from tests.support.seed import Users

PROFILE_PATH = "/profile"
REGISTER_PATH = "/registrations"
PROFILE_KEYS = {"full_name", "email", "phone", "dietary_requirements", "has_confirmed_details"}
CONFIRMED_AT = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
REGISTERED_AT = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
# 2.1 AC13's sentence: the attendee's phone number follows the event contact phone's rule (AC7).
PHONE_INVALID_MESSAGE = "Enter a phone number with 8 to 15 digits."
STAFF = [
    pytest.param(Users.ORGANISER, id="organiser"),
    pytest.param(Users.COORDINATOR, id="coordinator"),
    pytest.param(Users.LEAD, id="lead"),
    pytest.param(Users.VENUE_STAFF, id="venue-staff"),
    pytest.param(Users.TECH_SUPPORT, id="tech-support"),
    pytest.param(Users.SAFETY_OFFICER, id="safety-officer"),
]


def _first_time_attendee(db: Session) -> User:
    """An attendee who has never been asked for their details."""
    return make_user(db, role="ATTENDEE", attendee_details_confirmed_at=None)


def _returning_attendee(
    db: Session, *, phone: str | None = "+65 9123 4567", dietary: str | None = "Vegetarian"
) -> User:
    """An attendee who gave their details before, on My profile or a first registration."""
    return make_user(
        db,
        role="ATTENDEE",
        phone=phone,
        dietary_requirements=dietary,
        attendee_details_confirmed_at=CONFIRMED_AT,
    )


def _open_event(db: Session, *, capacity: int = 50) -> Event:
    """A Confirmed, Public event taking registrations (18.1 AC1), open now on the real clock."""
    starts_at = future_datetime(days=30)
    return make_event(
        db,
        status=EventStatus.CONFIRMED,
        assigned_coordinator_id=Users.COORDINATOR.id,
        registration_required=True,
        is_public=True,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=3),
        registration_closes_at=starts_at - timedelta(days=1),
        expected_attendance=capacity,
    )


def _my_event(db: Session) -> Event:
    """A Confirmed event of Users.ORGANISER's, assigned to Users.COORDINATOR (18.3's fixture)."""
    return make_event(
        db,
        status=EventStatus.CONFIRMED,
        registration_required=True,
        is_public=True,
        expected_attendance=10,
        assigned_coordinator_id=Users.COORDINATOR.id,
    )


def _add_registration(
    db: Session,
    event: Event,
    attendee: User,
    *,
    status: str = RegistrationStatus.REGISTERED,
    minutes: int = 0,
) -> EventRegistration:
    registration = EventRegistration(
        event_id=event.id,
        attendee_id=attendee.id,
        status=status,
        registered_at=REGISTERED_AT + timedelta(minutes=minutes),
        withdrawn_at=REGISTERED_AT + timedelta(days=1)
        if status == RegistrationStatus.WITHDRAWN
        else None,
    )
    db.add(registration)
    db.flush()
    return registration


def _register(client, db: Session, event: Event, *, details: dict | None = None):
    """``POST /registrations`` as the signed-in attendee, the test's rows saved first."""
    db.commit()
    body: dict = {"event_id": str(event.id)}
    if details is not None:
        body["details"] = details
    return client.post(REGISTER_PATH, json=body)


def _registration_count(db: Session, event: Event) -> int:
    return db.scalar(
        select(func.count())
        .select_from(EventRegistration)
        .where(EventRegistration.event_id == event.id)
    )


def _details_audits(db: Session, attendee: User) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.action == service.ATTENDEE_DETAILS_UPDATED_ACTION,
                AuditLog.entity_id == attendee.id,
            )
        )
    )


def _validation_issue(response, field: str) -> dict:
    """The one 422 issue that names ``field`` - so a message is checked against its own field."""
    [issue] = [issue for issue in response.json()["detail"] if issue["loc"][-1] == field]
    return issue


def _expected_message(problem: str) -> str:
    """Each problem's own refusal, so no two of them can share a sentence."""
    return {
        "phone-invalid": PHONE_INVALID_MESSAGE,
        "phone-blank": schemas.PHONE_NUMBER_REQUIRED_MESSAGE,
        "dietary-long": schemas.DIETARY_REQUIREMENTS_TOO_LONG_MESSAGE,
        "name-blank": schemas.FULL_NAME_REQUIRED_MESSAGE,
        "name-long": schemas.FULL_NAME_TOO_LONG_MESSAGE,
    }[problem]


def _list_row(client, event: Event, attendee: User) -> dict:
    """The attendee's one row on the event's registration list (18.3)."""
    rows = client.get(f"/events/{event.id}/registrations").json()["items"]
    [row] = [row for row in rows if row["attendee_email"] == attendee.email]
    return row


# --- AC1: My profile --------------------------------------------------------------------------
@pytest.mark.story("18.4", ac=1)
def test_an_attendee_reads_their_own_name_email_and_details(client, db: Session):
    attendee = _returning_attendee(db, phone="+65 8111 2222", dietary="Halal, no nuts")
    client.login(attendee.email)

    response = client.get(PROFILE_PATH)

    assert response.status_code == 200
    assert response.json() == {
        "full_name": attendee.full_name,
        "email": attendee.email,
        "phone": "+65 8111 2222",
        "dietary_requirements": "Halal, no nuts",
        "has_confirmed_details": True,
    }


@pytest.mark.story("18.4", ac=1)
def test_a_new_attendee_has_no_details_and_has_not_confirmed_them(client, db: Session):
    attendee = _first_time_attendee(db)
    client.login(attendee.email)

    body = client.get(PROFILE_PATH).json()

    assert set(body) == PROFILE_KEYS
    assert body["phone"] is None
    assert body["dietary_requirements"] is None
    assert body["has_confirmed_details"] is False


# --- AC2: the first registration asks for the details -----------------------------------------
@pytest.mark.story("18.4", ac=2)
def test_a_first_registration_with_details_saves_them_and_registers(client, db: Session):
    attendee = _first_time_attendee(db)
    event = _open_event(db)
    client.login(attendee.email)

    response = _register(
        client,
        db,
        event,
        details={"phone": "+65 9876 5432", "dietary_requirements": "  Vegan  "},
    )

    assert response.status_code == 201
    assert _registration_count(db, event) == 1
    assert client.get(PROFILE_PATH).json() == {
        "full_name": attendee.full_name,
        "email": attendee.email,
        "phone": "+65 9876 5432",
        "dietary_requirements": "Vegan",
        "has_confirmed_details": True,
    }
    [audit] = _details_audits(db, attendee)
    assert audit.actor_id == attendee.id


@pytest.mark.story("18.4", ac=2)
def test_a_first_registration_without_details_is_refused_and_writes_nothing(client, db: Session):
    attendee = _first_time_attendee(db)
    event = _open_event(db)
    client.login(attendee.email)

    response = _register(client, db, event)

    assert response.status_code == 409
    assert response.json()["detail"] == service.ATTENDEE_DETAILS_REQUIRED_MESSAGE
    assert _registration_count(db, event) == 0
    assert client.get(PROFILE_PATH).json()["has_confirmed_details"] is False


@pytest.mark.story("18.4", ac=2)
@pytest.mark.story("18.4", ac=7)
def test_a_first_registration_without_a_phone_number_is_refused_and_writes_nothing(
    client, db: Session
):
    attendee = _first_time_attendee(db)
    event = _open_event(db)
    client.login(attendee.email)

    response = _register(client, db, event, details={"dietary_requirements": "Vegan"})

    assert response.status_code == 422
    assert response.json()["detail"] == schemas.PHONE_NUMBER_REQUIRED_MESSAGE
    assert _registration_count(db, event) == 0
    assert client.get(PROFILE_PATH).json()["has_confirmed_details"] is False


@pytest.mark.story("18.4", ac=2)
def test_a_refused_first_registration_does_not_save_the_details_sent_with_it(client, db: Session):
    event = _open_event(db, capacity=1)
    _add_registration(db, event, _returning_attendee(db))
    attendee = _first_time_attendee(db)
    client.login(attendee.email)

    response = _register(
        client, db, event, details={"phone": "+65 9876 5432", "dietary_requirements": "Vegan"}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == service.EVENT_FULL_MESSAGE
    body = client.get(PROFILE_PATH).json()
    assert (body["phone"], body["dietary_requirements"]) == (None, None)
    assert body["has_confirmed_details"] is False
    assert _details_audits(db, attendee) == []


@pytest.mark.story("18.4", ac=2)
def test_details_saved_on_my_profile_first_mean_the_first_registration_does_not_ask(
    client, db: Session
):
    attendee = _first_time_attendee(db)
    event = _open_event(db)
    client.login(attendee.email)
    client.patch(PROFILE_PATH, json={"phone": "+65 9876 5432", "dietary_requirements": None})

    response = _register(client, db, event)

    assert response.status_code == 201


@pytest.mark.story("18.4", ac=2)
@pytest.mark.story("18.4", ac=7)
@pytest.mark.parametrize(
    ("details", "field"),
    [
        pytest.param({"phone": "12345", "dietary_requirements": None}, "phone", id="phone"),
        pytest.param(
            {"phone": None, "dietary_requirements": "v" * 501}, "dietary_requirements", id="dietary"
        ),
    ],
)
def test_invalid_details_sent_with_a_registration_are_refused_and_nothing_is_written(
    client, db: Session, details: dict, field: str
):
    attendee = _first_time_attendee(db)
    event = _open_event(db)
    client.login(attendee.email)

    response = _register(client, db, event, details=details)

    assert response.status_code == 422
    expected = {"phone": "phone-invalid", "dietary_requirements": "dietary-long"}[field]
    assert _expected_message(expected) in _validation_issue(response, field)["msg"]
    assert _registration_count(db, event) == 0
    assert client.get(PROFILE_PATH).json()["has_confirmed_details"] is False


# --- AC3: later registrations -----------------------------------------------------------------
@pytest.mark.story("18.4", ac=3)
def test_a_later_registration_needs_no_details_and_leaves_them_as_they_were(client, db: Session):
    attendee = _returning_attendee(db, phone="+65 8111 2222", dietary="Halal")
    event = _open_event(db)
    client.login(attendee.email)

    response = _register(client, db, event)

    assert response.status_code == 201
    body = client.get(PROFILE_PATH).json()
    assert (body["phone"], body["dietary_requirements"]) == ("+65 8111 2222", "Halal")
    assert _details_audits(db, attendee) == []


@pytest.mark.story("18.4", ac=3)
def test_details_sent_with_a_later_registration_update_the_profile(client, db: Session):
    attendee = _returning_attendee(db, phone="+65 8111 2222", dietary="Halal")
    event = _open_event(db)
    client.login(attendee.email)

    response = _register(
        client, db, event, details={"phone": "+65 8333 4444", "dietary_requirements": ""}
    )

    assert response.status_code == 201
    body = client.get(PROFILE_PATH).json()
    assert (body["phone"], body["dietary_requirements"]) == ("+65 8333 4444", None)


# --- AC4: changing the details on My profile --------------------------------------------------
@pytest.mark.story("18.4", ac=4)
def test_saving_my_profile_updates_the_details_and_answers_with_them(client, db: Session):
    attendee = _returning_attendee(db)
    client.login(attendee.email)

    response = client.patch(
        PROFILE_PATH, json={"phone": "+65 6000 1111", "dietary_requirements": "No shellfish"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "full_name": attendee.full_name,
        "email": attendee.email,
        "phone": "+65 6000 1111",
        "dietary_requirements": "No shellfish",
        "has_confirmed_details": True,
    }
    assert client.get(PROFILE_PATH).json() == response.json()


@pytest.mark.story("18.4", ac=4)
def test_a_profile_change_shows_on_the_list_of_an_event_registered_for_earlier(client, db: Session):
    attendee = _returning_attendee(db, phone="+65 8111 2222", dietary="Halal")
    event = _my_event(db)
    _add_registration(db, event, attendee)
    client.login(attendee.email)
    client.patch(PROFILE_PATH, json={"phone": "+65 8999 0000", "dietary_requirements": "Vegan"})

    client.login(Users.ORGANISER)
    row = _list_row(client, event, attendee)

    assert (row["attendee_phone"], row["dietary_requirements"]) == ("+65 8999 0000", "Vegan")


@pytest.mark.story("18.4", ac=4)
def test_saving_my_profile_is_audited_naming_the_changed_fields_not_their_values(
    client, db: Session
):
    attendee = _returning_attendee(db, phone="+65 8111 2222", dietary="Halal")
    client.login(attendee.email)

    client.patch(PROFILE_PATH, json={"phone": "+65 8999 0000", "dietary_requirements": "Halal"})

    [audit] = _details_audits(db, attendee)
    assert audit.actor_id == attendee.id
    assert audit.entity_type == "user"
    assert audit.details == {"fields": ["phone"]}
    # Phone numbers and dietary (sometimes health) needs stay out of the append-only log.
    assert "8999" not in json.dumps(audit.details)


@pytest.mark.story("18.4", ac=4)
def test_a_save_changes_only_the_details_sent(client, db: Session):
    """Only the fields sent are changed: a client that sends the phone number alone leaves the
    dietary requirements as they were."""
    attendee = _returning_attendee(db, phone="+65 8111 2222", dietary="Halal")
    client.login(attendee.email)

    response = client.patch(PROFILE_PATH, json={"phone": "+65 8999 0000"})

    assert response.status_code == 200
    assert (response.json()["phone"], response.json()["dietary_requirements"]) == (
        "+65 8999 0000",
        "Halal",
    )


@pytest.mark.story("18.4", ac=4)
def test_saving_unchanged_details_records_no_audit_entry(client, db: Session):
    """The audit says what changed; a save that changed nothing adds nothing to it."""
    attendee = _returning_attendee(db, phone="+65 8111 2222", dietary="Halal")
    client.login(attendee.email)

    response = client.patch(
        PROFILE_PATH, json={"phone": "+65 8111 2222", "dietary_requirements": "Halal"}
    )

    assert response.status_code == 200
    assert _details_audits(db, attendee) == []


# --- AC6/AC7: the rules, through My profile ---------------------------------------------------
@pytest.mark.story("18.4", ac=1)
@pytest.mark.story("18.4", ac=6)
@pytest.mark.story("18.4", ac=7)
@pytest.mark.parametrize(
    ("change", "field", "problem"),
    [
        pytest.param({"phone": "9123 456a"}, "phone", "phone-invalid", id="phone-invalid"),
        pytest.param({"phone": "  "}, "phone", "phone-blank", id="phone-blank"),
        pytest.param(
            {"dietary_requirements": "v" * 501},
            "dietary_requirements",
            "dietary-long",
            id="dietary",
        ),
        pytest.param({"full_name": " "}, "full_name", "name-blank", id="name-blank"),
        pytest.param({"full_name": "n" * 201}, "full_name", "name-long", id="name-long"),
    ],
)
def test_details_outside_the_rules_are_refused_with_their_message_and_not_saved(
    client, db: Session, change: dict, field: str, problem: str
):
    attendee = _returning_attendee(db, phone="+65 8111 2222", dietary="Halal")
    name = attendee.full_name
    client.login(attendee.email)

    response = client.patch(PROFILE_PATH, json=change)

    assert response.status_code == 422
    assert _expected_message(problem) in _validation_issue(response, field)["msg"]
    body = client.get(PROFILE_PATH).json()
    assert (body["full_name"], body["phone"], body["dietary_requirements"]) == (
        name,
        "+65 8111 2222",
        "Halal",
    )


@pytest.mark.story("18.4", ac=6)
def test_blank_dietary_requirements_are_saved_as_none(client, db: Session):
    attendee = _returning_attendee(db, phone="+65 8111 2222", dietary="Halal")
    client.login(attendee.email)

    response = client.patch(
        PROFILE_PATH, json={"phone": "+65 8111 2222", "dietary_requirements": " \n "}
    )

    assert response.status_code == 200
    db.refresh(attendee)
    assert attendee.phone == "+65 8111 2222"
    assert attendee.dietary_requirements is None


@pytest.mark.story("18.4", ac=7)
def test_saving_details_without_a_phone_number_on_file_is_refused(client, db: Session):
    """The phone number may be left out of a save only when one is already on file."""
    attendee = _first_time_attendee(db)
    client.login(attendee.email)

    response = client.patch(PROFILE_PATH, json={"dietary_requirements": "Vegan"})

    assert response.status_code == 422
    assert response.json()["detail"] == schemas.PHONE_NUMBER_REQUIRED_MESSAGE
    body = client.get(PROFILE_PATH).json()
    assert (body["dietary_requirements"], body["has_confirmed_details"]) == (None, False)


@pytest.mark.story("18.4", ac=7)
def test_an_attendee_cannot_be_recorded_as_having_given_their_details_without_a_phone_number(
    db: Session,
):
    """The database holds the rule too, whatever writes the row."""
    with pytest.raises(IntegrityError, match="ck_users_attendee_details_have_phone"):
        _returning_attendee(db, phone=None)


@pytest.mark.story("18.4", ac=1)
@pytest.mark.story("18.4", ac=4)
def test_a_changed_name_shows_on_my_profile_and_on_the_registration_list(client, db: Session):
    attendee = _returning_attendee(db)
    event = _my_event(db)
    _add_registration(db, event, attendee)
    client.login(attendee.email)

    response = client.patch(PROFILE_PATH, json={"full_name": "  Esme Tan  "})

    assert response.status_code == 200
    assert response.json()["full_name"] == "Esme Tan"
    [audit] = _details_audits(db, attendee)
    assert audit.details == {"fields": ["full_name"]}
    client.login(Users.ORGANISER)
    assert _list_row(client, event, attendee)["attendee_name"] == "Esme Tan"


# --- AC5/AC6: the registration list -----------------------------------------------------------
@pytest.mark.story("18.4", ac=5)
def test_the_organiser_sees_each_registered_attendees_phone_and_dietary_requirements(
    organiser_client, db: Session
):
    event = _my_event(db)
    first = _returning_attendee(db, phone="+65 8111 2222", dietary="Halal")
    second = _returning_attendee(db, phone="+65 8333 4444", dietary="Vegetarian, no eggs")
    _add_registration(db, event, first)
    _add_registration(db, event, second, minutes=5)

    rows = organiser_client.get(f"/events/{event.id}/registrations").json()["items"]

    assert [(row["attendee_phone"], row["dietary_requirements"]) for row in rows] == [
        ("+65 8111 2222", "Halal"),
        ("+65 8333 4444", "Vegetarian, no eggs"),
    ]


@pytest.mark.story("18.4", ac=5)
def test_the_assigned_coordinator_sees_the_same_details(coordinator_client, db: Session):
    event = _my_event(db)
    attendee = _returning_attendee(db, phone="+65 8111 2222", dietary="Halal")
    _add_registration(db, event, attendee)

    row = _list_row(coordinator_client, event, attendee)

    assert (row["attendee_phone"], row["dietary_requirements"]) == ("+65 8111 2222", "Halal")


@pytest.mark.story("18.4", ac=5)
@pytest.mark.story("18.4", ac=6)
def test_an_attendee_with_no_dietary_requirements_is_listed_with_them_as_null(
    organiser_client, db: Session
):
    """The list sends no value; the page shows "None" (AC6)."""
    event = _my_event(db)
    attendee = _returning_attendee(db, phone="+65 8111 2222", dietary=None)
    _add_registration(db, event, attendee)

    row = _list_row(organiser_client, event, attendee)

    assert row["attendee_phone"] == "+65 8111 2222"
    assert row["dietary_requirements"] is None


# --- AC9: rows that are no longer registered --------------------------------------------------
@pytest.mark.story("18.4", ac=9)
def test_a_withdrawn_registration_is_listed_without_the_attendees_details(
    organiser_client, db: Session
):
    event = _my_event(db)
    attendee = _returning_attendee(db)
    _add_registration(db, event, attendee, status=RegistrationStatus.WITHDRAWN)

    row = _list_row(organiser_client, event, attendee)

    assert row["status"] == "WITHDRAWN"
    assert row["attendee_name"] == attendee.full_name
    assert row["attendee_phone"] is None
    assert row["dietary_requirements"] is None


@pytest.mark.story("18.4", ac=9)
@pytest.mark.parametrize(
    "registration_status",
    [RegistrationStatus.REGISTERED, RegistrationStatus.CANCELLED],
    ids=["still-active", "cancelled"],
)
def test_the_registrations_of_a_cancelled_event_are_listed_without_details(
    organiser_client, db: Session, registration_status: str
):
    event = _my_event(db)
    attendee = _returning_attendee(db)
    _add_registration(db, event, attendee, status=registration_status)
    event.status = EventStatus.CANCELLED
    db.flush()

    row = _list_row(organiser_client, event, attendee)

    assert row["status"] == "EVENT_CANCELLED"
    assert row["attendee_phone"] is None
    assert row["dietary_requirements"] is None


@pytest.mark.story("18.4", ac=9)
def test_an_attendee_who_registered_again_shows_details_only_on_the_active_row(
    organiser_client, db: Session
):
    event = _my_event(db)
    attendee = _returning_attendee(db, phone="+65 8111 2222", dietary="Halal")
    _add_registration(db, event, attendee, status=RegistrationStatus.WITHDRAWN)
    _add_registration(db, event, attendee, minutes=60)

    rows = organiser_client.get(f"/events/{event.id}/registrations").json()["items"]

    assert [
        (row["status"], row["attendee_phone"], row["dietary_requirements"]) for row in rows
    ] == [
        ("WITHDRAWN", None, None),
        ("REGISTERED", "+65 8111 2222", "Halal"),
    ]


# --- AC10: only their own profile -------------------------------------------------------------
@pytest.mark.story("18.4", ac=10)
@pytest.mark.parametrize("method", ["get", "patch"])
def test_signed_out_users_cannot_read_or_save_a_profile(client, method: str):
    response = client.request(method.upper(), PROFILE_PATH, json={"phone": None})

    assert response.status_code == 401


@pytest.mark.story("18.4", ac=10)
@pytest.mark.parametrize("method", ["get", "patch"])
@pytest.mark.parametrize("user", STAFF)
def test_staff_cannot_open_my_profile(login_as, method: str, user):
    response = login_as(user).request(method.upper(), PROFILE_PATH, json={"phone": None})

    assert response.status_code == 403
    assert response.json()["detail"] == NOT_PERMITTED_MESSAGE


@pytest.mark.story("18.4", ac=10)
def test_an_attendee_saving_their_profile_changes_only_their_own(client, db: Session):
    mine = _returning_attendee(db, phone="+65 8111 2222", dietary="Halal")
    theirs = _returning_attendee(db, phone="+65 8333 4444", dietary="Vegan")
    client.login(mine.email)

    # No route names an attendee: an id in the query is not read.
    read = client.get(PROFILE_PATH, params={"attendee_id": str(theirs.id)}).json()
    client.patch(PROFILE_PATH, json={"phone": "+65 8999 0000"})

    assert read["email"] == mine.email
    db.refresh(mine)
    db.refresh(theirs)
    assert mine.phone == "+65 8999 0000"
    assert (theirs.phone, theirs.dietary_requirements) == ("+65 8333 4444", "Vegan")


@pytest.mark.story("18.4", ac=10)
@pytest.mark.parametrize("field", ["email", "id"])
def test_an_email_or_an_id_cannot_be_sent_with_the_profile(client, db: Session, field: str):
    attendee = _returning_attendee(db)
    other = _returning_attendee(db)
    before = (attendee.full_name, attendee.email, attendee.phone)
    value = {"email": "else@test.example", "id": str(other.id)}[field]
    client.login(attendee.email)

    response = client.patch(PROFILE_PATH, json={"phone": "+65 8999 0000", field: value})

    assert response.status_code == 422
    assert _validation_issue(response, field)["type"] == "extra_forbidden"
    db.refresh(attendee)
    assert (attendee.full_name, attendee.email, attendee.phone) == before


# --- AC11: two tabs ---------------------------------------------------------------------------
@pytest.mark.story("18.4", ac=11)
def test_the_later_of_two_saves_wins_and_a_reload_shows_it(client, db: Session):
    attendee = _returning_attendee(db)
    client.login(attendee.email)
    # Both tabs loaded the same profile; each sends the whole form.
    first_tab = {"phone": "+65 8111 1111", "dietary_requirements": "Vegan"}
    second_tab = {"phone": "+65 8222 2222", "dietary_requirements": "Halal"}

    assert client.patch(PROFILE_PATH, json=first_tab).status_code == 200
    assert client.patch(PROFILE_PATH, json=second_tab).status_code == 200

    reloaded = client.get(PROFILE_PATH).json()
    assert (reloaded["phone"], reloaded["dietary_requirements"]) == ("+65 8222 2222", "Halal")
