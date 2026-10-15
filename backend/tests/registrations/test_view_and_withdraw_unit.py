"""Story 18.2 - view and withdraw my registrations. UNIT tests: the withdrawal rules alone.

Level: unit. Each test calls one pure function in ``app/registrations/service.py`` - no database,
no HTTP, no fixture - so the whole file runs in milliseconds without PostgreSQL. The integration
tests beside it (``test_view_and_withdraw_integration.py``) prove the service applies these rules
to real rows through the API, and ``tests/e2e/my-registrations.spec.ts`` proves the flows an
attendee clicks through. No case is proven at more than one level.

AC1 The attendee sees their registrations with event name, date and status (Registered,
    Withdrawn or Event cancelled). An active registration can be withdrawn after confirmation,
    and the place returns to capacity. (Here: which status a registration is shown with.)
AC3 Withdrawal is allowed until the event starts: a moment before it is accepted, at or after it
    refused.
AC7 A double-click withdraws once: a second withdrawal is refused as already withdrawn.
AC8 A registration shows as Event cancelled when its event was cancelled or it was cancelled with
    the event; one the attendee withdrew stays Withdrawn. Neither can be withdrawn. An event sent
    back to Planning keeps its registration Registered.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.events.models import EventStatus
from app.registrations.models import RegistrationStatus
from app.registrations.service import (
    AlreadyWithdrawn,
    EventStarted,
    RegistrationStanding,
    WithdrawalEventCancelled,
    can_withdraw,
    registration_standing,
    withdrawal_refusal,
)

NOW = datetime(2030, 1, 15, 9, 0, tzinfo=UTC)
TICK = timedelta(microseconds=1)  # the smallest step a timestamptz stores

# Every status an event can hold, other than Cancelled (ck_events_status).
NOT_CANCELLED_EVENT_STATUSES = [
    EventStatus.DRAFT,
    EventStatus.UNDER_REVIEW,
    EventStatus.CLARIFICATION_REQUESTED,
    EventStatus.PLANNING,
    EventStatus.AWAITING_SAFETY_CHECK,
    EventStatus.CONFIRMED,
    EventStatus.COMPLETED,
    EventStatus.REJECTED,
]
ALL_EVENT_STATUSES = [*NOT_CANCELLED_EVENT_STATUSES, EventStatus.CANCELLED]


# --- AC1: the status a registration is shown with ----------------------------------------------
@pytest.mark.story("18.2", ac=1)
def test_an_active_registration_on_a_confirmed_event_is_registered():
    assert (
        registration_standing(
            registration_status=RegistrationStatus.REGISTERED, event_status=EventStatus.CONFIRMED
        )
        is RegistrationStanding.REGISTERED
    )


@pytest.mark.story("18.2", ac=1)
@pytest.mark.parametrize("event_status", ALL_EVENT_STATUSES)
def test_a_withdrawn_registration_is_withdrawn_whatever_its_event(event_status):
    assert (
        registration_standing(
            registration_status=RegistrationStatus.WITHDRAWN, event_status=event_status
        )
        is RegistrationStanding.WITHDRAWN
    )


@pytest.mark.story("18.2", ac=1)
@pytest.mark.story("18.2", ac=8)
@pytest.mark.parametrize("event_status", ALL_EVENT_STATUSES)
def test_a_registration_cancelled_with_its_event_is_event_cancelled(event_status):
    """Story 6.2 will mark an event's registrations CANCELLED as it cancels the event."""
    assert (
        registration_standing(
            registration_status=RegistrationStatus.CANCELLED, event_status=event_status
        )
        is RegistrationStanding.EVENT_CANCELLED
    )


# --- AC8: a cancelled event, and one sent back to Planning ----------------------------------------
@pytest.mark.story("18.2", ac=8)
def test_an_active_registration_on_a_cancelled_event_is_event_cancelled():
    """Story 21.2's rejection cancels the event and leaves its registrations as they were."""
    assert (
        registration_standing(
            registration_status=RegistrationStatus.REGISTERED, event_status=EventStatus.CANCELLED
        )
        is RegistrationStanding.EVENT_CANCELLED
    )


@pytest.mark.story("18.2", ac=8)
@pytest.mark.parametrize("event_status", NOT_CANCELLED_EVENT_STATUSES)
def test_an_active_registration_on_an_event_not_cancelled_stays_registered(event_status):
    """Including Planning: an event sent back after confirmation keeps its registrations (18.1
    AC4)."""
    assert (
        registration_standing(
            registration_status=RegistrationStatus.REGISTERED, event_status=event_status
        )
        is RegistrationStanding.REGISTERED
    )


# --- AC3: until the event starts ----------------------------------------------------------------
@pytest.mark.story("18.2", ac=3)
def test_a_registration_can_be_withdrawn_a_moment_before_the_event_starts():
    assert can_withdraw(standing=RegistrationStanding.REGISTERED, now=NOW, starts_at=NOW + TICK)


@pytest.mark.story("18.2", ac=3)
def test_a_registration_cannot_be_withdrawn_once_the_event_starts():
    assert not can_withdraw(standing=RegistrationStanding.REGISTERED, now=NOW, starts_at=NOW)


@pytest.mark.story("18.2", ac=3)
def test_a_registration_cannot_be_withdrawn_after_the_event_has_started():
    assert not can_withdraw(standing=RegistrationStanding.REGISTERED, now=NOW, starts_at=NOW - TICK)


@pytest.mark.story("18.2", ac=3)
@pytest.mark.story("18.2", ac=8)
@pytest.mark.parametrize(
    "standing", [RegistrationStanding.WITHDRAWN, RegistrationStanding.EVENT_CANCELLED]
)
def test_only_an_active_registration_can_be_withdrawn_however_far_off_the_event(standing):
    assert not can_withdraw(standing=standing, now=NOW, starts_at=NOW + timedelta(days=365))


# --- AC7 / AC8: why a withdrawal that changed nothing was refused --------------------------------
@pytest.mark.story("18.2", ac=7)
def test_a_registration_already_withdrawn_is_refused_as_already_withdrawn():
    """The second request of a double-click, whether or not the event has since started."""
    assert isinstance(withdrawal_refusal(standing=RegistrationStanding.WITHDRAWN), AlreadyWithdrawn)


@pytest.mark.story("18.2", ac=8)
def test_a_registration_whose_event_was_cancelled_is_refused_as_cancelled():
    assert isinstance(
        withdrawal_refusal(standing=RegistrationStanding.EVENT_CANCELLED),
        WithdrawalEventCancelled,
    )


@pytest.mark.story("18.2", ac=3)
def test_an_active_registration_that_could_not_be_withdrawn_is_refused_as_started():
    """An active registration on an event not cancelled is refused only once the event starts."""
    assert isinstance(withdrawal_refusal(standing=RegistrationStanding.REGISTERED), EventStarted)
