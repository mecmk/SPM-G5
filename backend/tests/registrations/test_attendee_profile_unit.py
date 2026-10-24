"""Story 18.4 - autofill attendee profile details. UNIT tests: the details' own rules.

Level: unit. Each test builds ``app/registrations/schemas.py::AttendeeDetailsIn`` - the details an
attendee sends, on My profile or with a registration - with no database, no HTTP and no fixture.
The phone number's own rule is unit-tested in ``tests/common/test_phone_unit.py``. The
integration tests beside this file (``test_attendee_profile_integration.py``) prove both
endpoints apply these rules and save what they produce; ``tests/e2e/attendee-profile.spec.ts``
proves the flows an attendee and an organiser click through.

AC6 Dietary requirements are free text of up to 500 characters. Left blank, or only spaces, they
    are recorded as "None" (stored as no value, shown as "None": PO decision, 24 Oct 2026).
AC7 The phone number is optional. When given, it follows the rule for an event's contact phone
    (2.1 AC13). (Here: a blank one is not given.)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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
def test_a_blank_or_spaces_only_phone_number_is_not_given(value: str | None):
    assert schemas.AttendeeDetailsIn(phone=value).phone is None
