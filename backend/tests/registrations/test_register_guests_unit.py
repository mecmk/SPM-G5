"""Story 18.5 - register guests with my registration. UNIT tests: a guest's own rules.

Level: unit. Each test builds ``app/registrations/schemas.py::GuestIn``, ``RegistrationCreate`` or
``GuestsUpdate`` - the guests an attendee sends, with a registration or as a change afterwards -
with no database, no HTTP and no fixture. The integration tests beside this file
(``test_register_guests_integration.py``) prove both endpoints apply these rules and save what
they produce; ``tests/e2e/register-guests.spec.ts`` proves the flows an attendee and an organiser
click through.

The ACs are the Product Backlog's (row 57, CL-173), summarised:

AC1 When registering, the attendee can add guests, each with optional dietary requirements (as
    18.4 AC6: at most 500 characters, blank shown as "None") and no phone number.
AC3 After registering, the attendee can add, change or remove guests.
AC6 An attendee can bring 0 to 10 guests. Each guest's name is required, at most 200 characters.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.registrations import schemas

EVENT_ID = "33333333-0000-0000-0000-000000018503"


def _guest_refusal(**fields) -> str:
    with pytest.raises(ValidationError) as caught:
        schemas.GuestIn(**fields)
    [error] = caught.value.errors()
    return error["msg"]


def _guests(count: int) -> list[dict]:
    return [{"full_name": f"Guest {n}"} for n in range(1, count + 1)]


# --- AC6: how many guests ---------------------------------------------------------------------
@pytest.mark.story("18.5", ac=6)
def test_a_registration_may_bring_ten_guests():
    registration = schemas.RegistrationCreate(event_id=EVENT_ID, guests=_guests(schemas.MAX_GUESTS))

    assert len(registration.guests) == 10


@pytest.mark.story("18.5", ac=6)
def test_a_registration_with_eleven_guests_is_refused():
    with pytest.raises(ValidationError) as caught:
        schemas.RegistrationCreate(event_id=EVENT_ID, guests=_guests(schemas.MAX_GUESTS + 1))

    assert schemas.TOO_MANY_GUESTS_MESSAGE in str(caught.value)


@pytest.mark.story("18.5", ac=6)
def test_a_registration_without_guests_has_none():
    """As in 18.1: nothing about guests need be sent."""
    assert schemas.RegistrationCreate(event_id=EVENT_ID).guests == []


@pytest.mark.story("18.5", ac=6)
def test_a_change_may_leave_ten_guests_or_none():
    assert len(schemas.GuestsUpdate(guests=_guests(10)).guests) == 10
    assert schemas.GuestsUpdate(guests=[]).guests == []


@pytest.mark.story("18.5", ac=6)
def test_a_change_to_eleven_guests_is_refused():
    with pytest.raises(ValidationError) as caught:
        schemas.GuestsUpdate(guests=_guests(11))

    assert schemas.TOO_MANY_GUESTS_MESSAGE in str(caught.value)


@pytest.mark.story("18.5", ac=6)
def test_a_change_must_say_what_the_guests_are_now():
    """A replacement of the whole list: sending nothing is not taken as "no guests"."""
    with pytest.raises(ValidationError):
        schemas.GuestsUpdate()


@pytest.mark.story("18.5", ac=3)
def test_a_change_sends_nothing_but_the_guests():
    """Nothing else - not the event, nor another registration - rides along with a change."""
    with pytest.raises(ValidationError) as caught:
        schemas.GuestsUpdate(guests=[], event_id=EVENT_ID)

    [error] = caught.value.errors()
    assert error["type"] == "extra_forbidden"


# --- AC6: a guest's name ----------------------------------------------------------------------
@pytest.mark.story("18.5", ac=6)
def test_a_guest_name_of_200_characters_is_kept():
    name = "n" * schemas.FULL_NAME_MAX_LENGTH

    assert schemas.GuestIn(full_name=name).full_name == name


@pytest.mark.story("18.5", ac=6)
def test_a_guest_name_of_201_characters_is_refused():
    name = "n" * (schemas.FULL_NAME_MAX_LENGTH + 1)

    assert schemas.GUEST_FULL_NAME_TOO_LONG_MESSAGE in _guest_refusal(full_name=name)


@pytest.mark.story("18.5", ac=6)
@pytest.mark.parametrize("value", ["", "   ", None], ids=["empty", "spaces", "null"])
def test_a_blank_or_spaces_only_guest_name_is_refused(value: str | None):
    assert schemas.GUEST_FULL_NAME_REQUIRED_MESSAGE in _guest_refusal(full_name=value)


@pytest.mark.story("18.5", ac=6)
def test_a_guest_without_a_name_is_refused():
    assert schemas.GUEST_FULL_NAME_REQUIRED_MESSAGE in _guest_refusal()


@pytest.mark.story("18.5", ac=6)
def test_a_guest_name_is_trimmed():
    assert schemas.GuestIn(full_name="  Ravi Kumar \n").full_name == "Ravi Kumar"


# --- AC1: a guest's dietary requirements ------------------------------------------------------
@pytest.mark.story("18.5", ac=1)
def test_guest_dietary_requirements_of_500_characters_are_kept():
    text = "v" * schemas.DIETARY_REQUIREMENTS_MAX_LENGTH

    guest = schemas.GuestIn(full_name="Ravi Kumar", dietary_requirements=text)

    assert guest.dietary_requirements == text


@pytest.mark.story("18.5", ac=1)
def test_guest_dietary_requirements_of_501_characters_are_refused():
    text = "v" * (schemas.DIETARY_REQUIREMENTS_MAX_LENGTH + 1)

    refusal = _guest_refusal(full_name="Ravi Kumar", dietary_requirements=text)

    assert schemas.GUEST_DIETARY_REQUIREMENTS_TOO_LONG_MESSAGE in refusal


@pytest.mark.story("18.5", ac=1)
@pytest.mark.parametrize(
    "value", ["", "   ", "\t\n ", None], ids=["empty", "spaces", "tab", "null"]
)
def test_blank_guest_dietary_requirements_are_recorded_as_none(value: str | None):
    guest = schemas.GuestIn(full_name="Ravi Kumar", dietary_requirements=value)

    assert guest.dietary_requirements is None


@pytest.mark.story("18.5", ac=1)
def test_guest_dietary_requirements_are_optional():
    assert schemas.GuestIn(full_name="Ravi Kumar").dietary_requirements is None


# --- AC1: nothing else is asked of a guest ----------------------------------------------------
@pytest.mark.story("18.5", ac=1)
@pytest.mark.parametrize("field", ["phone", "email", "attendee_id"])
def test_nothing_but_a_name_and_dietary_requirements_can_be_sent_for_a_guest(field: str):
    with pytest.raises(ValidationError) as caught:
        schemas.GuestIn(full_name="Ravi Kumar", **{field: "+65 9123 4567"})

    [error] = caught.value.errors()
    assert error["type"] == "extra_forbidden"


@pytest.mark.story("18.5", ac=6)
def test_each_guest_message_is_its_own_sentence():
    """No two refusals share a sentence (backend/STYLE.md), the attendee's own included."""
    messages = [
        schemas.GUEST_FULL_NAME_REQUIRED_MESSAGE,
        schemas.GUEST_FULL_NAME_TOO_LONG_MESSAGE,
        schemas.GUEST_DIETARY_REQUIREMENTS_TOO_LONG_MESSAGE,
        schemas.TOO_MANY_GUESTS_MESSAGE,
        schemas.FULL_NAME_REQUIRED_MESSAGE,
        schemas.FULL_NAME_TOO_LONG_MESSAGE,
        schemas.DIETARY_REQUIREMENTS_TOO_LONG_MESSAGE,
    ]

    assert len(set(messages)) == len(messages)
