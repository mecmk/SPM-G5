"""Story 18.4 - autofill attendee profile details. UNIT tests: the details' own rules.

Level: unit. Each test builds ``app/registrations/schemas.py::AttendeeDetailsIn`` - the details an
attendee sends, on My profile or with a registration - with no database, no HTTP and no fixture.
The phone number's own rule is unit-tested in ``tests/common/test_phone_unit.py``. The
integration tests beside this file (``test_attendee_profile_integration.py``) prove both
endpoints apply these rules and save what they produce; ``tests/e2e/attendee-profile.spec.ts``
proves the flows an attendee and an organiser click through.

AC1 The attendee keeps their name up to date on My profile, with their phone number and dietary
    requirements; their email stays fixed. The name and phone number are required, and the name
    is at most 200 characters. (CL-166; here: the name's own rules.)
AC6 Dietary requirements are free text of up to 500 characters. Left blank, or only spaces, they
    are recorded as "None" (stored as no value, shown as "None": CL-163).
AC7 The phone number is required. It follows the rule for an event's contact phone (2.1 AC13).
    (CL-166; here: a blank one is refused.)

Guests (fix f18.4.1), built as ``schemas.GuestIn``:
AC12 The attendee may bring one guest: the guest's name and phone number, both required, and
    their dietary requirements, optional, by the same rules as the attendee's own (AC1, AC6,
    AC7). Nothing else can be sent about them.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.common.phone import PHONE_NUMBER_INVALID_MESSAGE
from app.registrations import schemas


def _refusal(**fields) -> str:
    with pytest.raises(ValidationError) as caught:
        schemas.AttendeeDetailsIn(**fields)
    [error] = caught.value.errors()
    return error["msg"]


# --- AC6: dietary requirements ----------------------------------------------------------------
@pytest.mark.story("18.4", ac=6)
def test_dietary_requirements_of_500_characters_are_kept():
    text = "v" * schemas.DIETARY_REQUIREMENTS_MAX_LENGTH

    details = schemas.AttendeeDetailsIn(dietary_requirements=text)

    assert details.dietary_requirements == text


@pytest.mark.story("18.4", ac=6)
def test_dietary_requirements_of_501_characters_are_refused():
    text = "v" * (schemas.DIETARY_REQUIREMENTS_MAX_LENGTH + 1)

    assert schemas.DIETARY_REQUIREMENTS_TOO_LONG_MESSAGE in _refusal(dietary_requirements=text)


@pytest.mark.story("18.4", ac=6)
@pytest.mark.parametrize(
    "value", ["", "   ", "\t\n ", None], ids=["empty", "spaces", "tab", "null"]
)
def test_blank_or_spaces_only_dietary_requirements_are_recorded_as_none(value: str | None):
    assert schemas.AttendeeDetailsIn(dietary_requirements=value).dietary_requirements is None


@pytest.mark.story("18.4", ac=6)
def test_dietary_requirements_are_trimmed_before_their_length_is_counted():
    text = "v" * schemas.DIETARY_REQUIREMENTS_MAX_LENGTH

    details = schemas.AttendeeDetailsIn(dietary_requirements=f"  {text}\n")

    assert details.dietary_requirements == text


# --- AC7: a phone number left empty -----------------------------------------------------------
@pytest.mark.story("18.4", ac=7)
@pytest.mark.parametrize("value", ["", "   ", None], ids=["empty", "spaces", "null"])
def test_a_blank_or_spaces_only_phone_number_is_refused(value: str | None):
    assert schemas.PHONE_NUMBER_REQUIRED_MESSAGE in _refusal(phone=value)


# --- AC1: the attendee's name -----------------------------------------------------------------
@pytest.mark.story("18.4", ac=1)
def test_a_name_of_200_characters_is_kept():
    name = "n" * schemas.FULL_NAME_MAX_LENGTH

    assert schemas.AttendeeDetailsIn(full_name=name).full_name == name


@pytest.mark.story("18.4", ac=1)
def test_a_name_of_201_characters_is_refused():
    name = "n" * (schemas.FULL_NAME_MAX_LENGTH + 1)

    assert schemas.FULL_NAME_TOO_LONG_MESSAGE in _refusal(full_name=name)


@pytest.mark.story("18.4", ac=1)
@pytest.mark.parametrize("value", ["", "   ", None], ids=["empty", "spaces", "null"])
def test_a_blank_or_spaces_only_name_is_refused(value: str | None):
    assert schemas.FULL_NAME_REQUIRED_MESSAGE in _refusal(full_name=value)


@pytest.mark.story("18.4", ac=1)
def test_a_name_is_trimmed():
    assert schemas.AttendeeDetailsIn(full_name="  Esme Tan \n").full_name == "Esme Tan"


# =============================================================================================
# AC12 - a guest's details (fix f18.4.1)
# =============================================================================================
GUEST = {"full_name": "Alex Tan", "phone": "+65 9000 1111"}


def _guest_refusal(**fields) -> str:
    with pytest.raises(ValidationError) as caught:
        schemas.GuestIn(**fields)
    [error] = caught.value.errors()
    return error["msg"]


@pytest.mark.story("18.4", ac=12)
def test_a_guest_is_kept_trimmed_with_their_dietary_requirements():
    guest = schemas.GuestIn(
        full_name="  Alex Tan ", phone=" +65 9000 1111\n", dietary_requirements="  No pork "
    )

    assert (guest.full_name, guest.phone, guest.dietary_requirements) == (
        "Alex Tan",
        "+65 9000 1111",
        "No pork",
    )


@pytest.mark.story("18.4", ac=12)
@pytest.mark.parametrize("value", ["", "   ", None], ids=["empty", "spaces", "null"])
def test_a_guests_dietary_requirements_left_blank_are_recorded_as_none(value: str | None):
    assert schemas.GuestIn(**GUEST, dietary_requirements=value).dietary_requirements is None


@pytest.mark.story("18.4", ac=12)
def test_a_guests_dietary_requirements_may_be_left_out():
    assert schemas.GuestIn(**GUEST).dietary_requirements is None


@pytest.mark.story("18.4", ac=12)
@pytest.mark.parametrize("value", ["", "   ", None], ids=["empty", "spaces", "null"])
def test_a_guest_with_no_name_is_refused(value: str | None):
    message = _guest_refusal(**{**GUEST, "full_name": value})

    assert schemas.GUEST_FULL_NAME_REQUIRED_MESSAGE in message


@pytest.mark.story("18.4", ac=12)
def test_a_guests_name_of_200_characters_is_kept_and_of_201_is_refused():
    longest = "n" * schemas.FULL_NAME_MAX_LENGTH

    assert schemas.GuestIn(**{**GUEST, "full_name": longest}).full_name == longest
    assert schemas.GUEST_FULL_NAME_TOO_LONG_MESSAGE in _guest_refusal(
        **{**GUEST, "full_name": longest + "n"}
    )


@pytest.mark.story("18.4", ac=12)
@pytest.mark.parametrize("value", ["", "   ", None], ids=["empty", "spaces", "null"])
def test_a_guest_with_no_phone_number_is_refused(value: str | None):
    message = _guest_refusal(**{**GUEST, "phone": value})

    assert schemas.GUEST_PHONE_REQUIRED_MESSAGE in message


@pytest.mark.story("18.4", ac=12)
def test_a_guests_phone_number_follows_the_attendees_rule():
    """The rule's own boundaries are unit-tested in tests/common/test_phone_unit.py."""
    assert schemas.GuestIn(**{**GUEST, "phone": "9000 1111"}).phone == "9000 1111"
    assert PHONE_NUMBER_INVALID_MESSAGE in _guest_refusal(**{**GUEST, "phone": "9000 111"})


@pytest.mark.story("18.4", ac=12)
def test_a_guests_dietary_requirements_of_500_characters_are_kept_and_of_501_refused():
    longest = "v" * schemas.DIETARY_REQUIREMENTS_MAX_LENGTH

    assert schemas.GuestIn(**GUEST, dietary_requirements=longest).dietary_requirements == longest
    assert schemas.DIETARY_REQUIREMENTS_TOO_LONG_MESSAGE in _guest_refusal(
        **GUEST, dietary_requirements=longest + "v"
    )


@pytest.mark.story("18.4", ac=12)
@pytest.mark.parametrize("field", ["full_name", "phone"])
def test_a_guest_sent_without_a_name_or_phone_number_is_refused(field: str):
    fields = {key: value for key, value in GUEST.items() if key != field}

    with pytest.raises(ValidationError) as caught:
        schemas.GuestIn(**fields)

    [error] = caught.value.errors()
    assert (error["type"], error["loc"]) == ("missing", (field,))


@pytest.mark.story("18.4", ac=12)
def test_nothing_else_can_be_sent_about_a_guest():
    with pytest.raises(ValidationError) as caught:
        schemas.GuestIn(**GUEST, email="alex@test.example")

    [error] = caught.value.errors()
    assert error["type"] == "extra_forbidden"
