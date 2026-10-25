"""The phone number rule, shared by an event's point of contact (story 2.1 AC13) and an attendee's
details (story 18.4 AC7), so the two can never drift apart. Mirrored, limits and message alike, by
``frontend/src/shared/phone.ts`` - keep the two in step."""

from __future__ import annotations

import re

PHONE_MAX_LENGTH = 50
PHONE_MIN_DIGITS = 8
PHONE_MAX_DIGITS = 15
PHONE_NUMBER_INVALID_MESSAGE = "Enter a phone number with 8 to 15 digits."
_PHONE_PATTERN = re.compile(r"^\+?[\d -]+$")


def is_phone_number(value: str) -> bool:
    """2.1 AC13, 18.4 AC7: 8 to 15 digits, with an optional leading "+", and spaces and dashes
    allowed, in at most 50 characters. ``value`` comes trimmed: what a blank one means is the
    caller's to decide, since a phone number is optional in both places."""
    digits = sum(char.isdigit() for char in value)
    return (
        len(value) <= PHONE_MAX_LENGTH
        and _PHONE_PATTERN.match(value) is not None
        and PHONE_MIN_DIGITS <= digits <= PHONE_MAX_DIGITS
    )
