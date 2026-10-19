"""Story 18.3 - the registration list for my event. UNIT tests: when an event is full.

Level: unit. ``is_full`` in ``app/registrations/service.py`` alone - no database, no HTTP. The
integration tests beside it (``test_registration_list_integration.py``) prove the API applies it.

AC3 No registrations shows an empty message. When the count reaches capacity, the list shows
    "Full".
"""

from __future__ import annotations

import pytest

from app.registrations.service import is_full


@pytest.mark.story("18.3", ac=3)
def test_one_short_of_capacity_is_not_full():
    assert is_full(capacity=5, active=4) is False


@pytest.mark.story("18.3", ac=3)
def test_reaching_capacity_is_full():
    assert is_full(capacity=5, active=5) is True


@pytest.mark.story("18.3", ac=3)
def test_beyond_a_lowered_capacity_is_still_full():
    assert is_full(capacity=5, active=6) is True


@pytest.mark.story("18.3", ac=3)
def test_no_registrations_is_not_full():
    assert is_full(capacity=1, active=0) is False
