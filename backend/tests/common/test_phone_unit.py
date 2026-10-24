"""Story 18.4 AC7 - the phone number rule, shared with story 2.1 AC13. UNIT tests: the rule alone.

Level: unit. Each test calls ``app/common/phone.py::is_phone_number`` - no database, no HTTP, no
fixture. The rule is the one an event's contact phone already follows (2.1 AC13); story 2.1's own
tests (``tests/events/``) prove the event request still applies it, and
``tests/registrations/test_attendee_profile_integration.py`` proves the attendee's details do.
What a blank phone number becomes is the details' rule, not this one's: see
``tests/registrations/test_attendee_profile_unit.py``.

AC7 The phone number is optional. When given, it follows the rule for an event's contact phone
    (2.1 AC13): 8 to 15 digits, an optional leading "+", spaces and dashes allowed.
"""

from __future__ import annotations

import pytest
from app.common.phone import PHONE_MAX_LENGTH, is_phone_number


@pytest.mark.story("18.4", ac=7)
def test_a_phone_number_of_7_digits_is_refused():
    assert is_phone_number("9123456") is False


@pytest.mark.story("18.4", ac=7)
def test_a_phone_number_of_8_digits_is_accepted():
    assert is_phone_number("91234567") is True


@pytest.mark.story("18.4", ac=7)
def test_a_phone_number_of_15_digits_is_accepted():
    assert is_phone_number("123456789012345") is True


@pytest.mark.story("18.4", ac=7)
def test_a_phone_number_of_16_digits_is_refused():
    assert is_phone_number("1234567890123456") is False


@pytest.mark.story("18.4", ac=7)
@pytest.mark.parametrize("value", ["+65 9123 4567", "+65-9123-4567", "6123 - 4567", "+6591234567"])
def test_a_leading_plus_spaces_and_dashes_are_allowed(value: str):
    assert is_phone_number(value) is True


@pytest.mark.story("18.4", ac=7)
@pytest.mark.parametrize("value", ["65+91234567", "6591234567+", "++6591234567"])
def test_a_plus_anywhere_but_the_front_is_refused(value: str):
    assert is_phone_number(value) is False


@pytest.mark.story("18.4", ac=7)
@pytest.mark.parametrize("value", ["9123 456a", "call 91234567", "+65 (9123) 4567"])
def test_letters_in_a_phone_number_are_refused(value: str):
    """Letters, and any other character the rule does not name, such as brackets."""
    assert is_phone_number(value) is False


@pytest.mark.story("18.4", ac=7)
def test_a_phone_number_over_50_characters_is_refused():
    """2.1 AC13's rule also caps the whole number, spaces included (PO decision, 24 Oct 2026)."""
    at_limit = "9" + " " * (PHONE_MAX_LENGTH - 8) + "1234567"
    over_limit = "9" + " " * (PHONE_MAX_LENGTH - 7) + "1234567"
    assert len(at_limit) == PHONE_MAX_LENGTH

    assert is_phone_number(at_limit) is True
    assert is_phone_number(over_limit) is False
