"""Story 12.6 AC12 (PO decision, the customer's Q12 and Q37 answers, CL-121): an event with a
booking marked "Venue unavailable - alternative needed" is not sent for a safety review or
confirmed.

AC13 While any live booking of an event - pending or approved, for a requirement or an additional
     venue - is marked (9.4), the coordinator cannot send the event for a safety review or confirm
     it: 409, naming the unavailable venue and saying to replace it or wait for it to reopen. The
     event's safety summary says the same before anything is sent, which is how the event page
     shows it. Once the replacement is approved or the mark clears, both work as before; a mark
     left on a closed booking, or on another event's booking, blocks nothing.

No other 21.2 rule changes: test_safety_request.py and test_confirm_event.py are as they were.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.bookings.models import BookingStatus, VenueBooking
from app.events.models import EventStatus
from app.safety import service as safety_service
from app.safety.models import EventSafetyReview, SafetyReviewOutcome
from app.safety.service import current_facts
from tests.support.factories import (
    SecuredEvent,
    make_booking,
    make_secured_event,
    make_venue,
    make_venue_requirement,
)
from tests.support.replacement import approve, created, replace
from tests.support.seed import Users


def _request_path(event_id: uuid.UUID) -> str:
    return f"/safety-checks/{event_id}/request"


def _confirm_path(event_id: uuid.UUID) -> str:
    return f"/events/{event_id}/confirm"


def _summary_path(event_id: uuid.UUID) -> str:
    return f"/events/{event_id}/safety-review"


def _mark(db: Session, booking) -> None:
    """Venue Staff's closure marks the booking (9.4 AC3)."""
    booking.venue_unavailable_marked_at = datetime.now(UTC)
    db.flush()


def _approve_review(db: Session, secured: SecuredEvent, *, day: int = 1) -> None:
    """A safety approval, on ``day`` of October 2026, that saw the facts the event has now."""
    db.add(
        EventSafetyReview(
            event_id=secured.event.id,
            reviewed_by_id=Users.SAFETY_OFFICER.id,
            reviewed_at=datetime(2026, 10, day, tzinfo=UTC),
            outcome=SafetyReviewOutcome.APPROVED,
            facts=current_facts(db, secured.event),
        )
    )
    db.flush()


def _sentence(venue_name: str) -> str:
    return safety_service.VENUE_UNAVAILABLE_SENTENCE.format(venue=venue_name)


def _pending_sentence(venue_name: str) -> str:
    return safety_service.REPLACEMENT_PENDING_SENTENCE.format(venue=venue_name)


def _clear_the_mark(db: Session, secured: SecuredEvent) -> None:
    """The closure was removed (9.4 AC6): the original's mark clears; a pending replacement of it
    stays pending."""
    secured.booking.venue_unavailable_marked_at = None
    db.flush()


def _venue_name(db: Session, secured: SecuredEvent) -> str:
    db.refresh(secured.booking)
    return secured.booking.venue.name


# --- the safety review ---------------------------------------------------------------------------
@pytest.mark.story("12.6", ac=12)
def test_a_review_is_refused_while_a_booking_is_marked(coordinator_client, db: Session):
    secured = make_secured_event(db)
    _mark(db, secured.booking)

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 409, response.text
    db.refresh(secured.event)
    assert secured.event.status == EventStatus.PLANNING


@pytest.mark.story("12.6", ac=12)
def test_the_refusal_names_the_venue_and_says_to_replace_it_or_wait(coordinator_client, db):
    secured = make_secured_event(db)
    _mark(db, secured.booking)

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail.startswith(safety_service.VENUE_UNAVAILABLE_FOR_REVIEW_MESSAGE)
    assert _sentence(_venue_name(db, secured)) in detail


@pytest.mark.story("12.6", ac=12)
@pytest.mark.parametrize("status", [BookingStatus.APPROVED, BookingStatus.PENDING])
def test_a_marked_additional_venue_also_blocks_a_review(coordinator_client, db, status):
    """A booking for no requirement, pending or approved, is as live as any other."""
    secured = make_secured_event(db)
    extra_venue = make_venue(db, name=f"Unavailable Annex {uuid.uuid4().hex[:8]}")
    make_booking(
        db,
        event_id=secured.event.id,
        venue_id=extra_venue.id,
        starts_at=secured.event.starts_at,
        ends_at=secured.event.ends_at,
        status=status,
        venue_unavailable_marked_at=datetime.now(UTC),
        **(
            {"hold_expires_at": datetime.now(UTC) + timedelta(days=30)}
            if status == BookingStatus.APPROVED
            else {}
        ),
    )

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 409, response.text
    assert _sentence(extra_venue.name) in response.json()["detail"]


@pytest.mark.story("12.6", ac=12)
def test_the_safety_summary_names_the_venue_before_anything_is_sent(coordinator_client, db):
    """What the event page reads, as it reads every other thing that stops a request."""
    secured = make_secured_event(db)
    _mark(db, secured.booking)

    body = coordinator_client.get(_summary_path(secured.event.id)).json()

    assert _sentence(_venue_name(db, secured)) in body["request_blockers"]


# --- confirming ----------------------------------------------------------------------------------
@pytest.mark.story("12.6", ac=12)
def test_confirming_is_refused_while_a_booking_is_marked(coordinator_client, db: Session):
    secured = make_secured_event(db)
    _approve_review(db, secured)
    _mark(db, secured.booking)

    response = coordinator_client.post(_confirm_path(secured.event.id))

    assert response.status_code == 409, response.text
    assert _sentence(_venue_name(db, secured)) in response.json()["detail"]
    db.refresh(secured.event)
    assert secured.event.status == EventStatus.PLANNING


@pytest.mark.story("12.6", ac=12)
def test_the_confirmation_refusal_names_the_venue_and_says_to_replace_it_or_wait(
    coordinator_client, db
):
    secured = make_secured_event(db)
    _approve_review(db, secured)
    _mark(db, secured.booking)

    response = coordinator_client.post(_confirm_path(secured.event.id))

    assert response.status_code == 409, response.text
    assert safety_service.VENUE_UNAVAILABLE_FOR_CONFIRM_MESSAGE in response.json()["detail"]


# --- the way out ---------------------------------------------------------------------------------
@pytest.mark.story("12.6", ac=12)
def test_a_review_is_allowed_once_the_replacement_is_approved(login_as, db: Session):
    secured = make_secured_event(db)
    _mark(db, secured.booking)
    assert (
        login_as(Users.COORDINATOR).post(_request_path(secured.event.id), json={}).status_code
        == 409
    )
    replacement = created(
        replace(login_as(Users.COORDINATOR), secured.booking.id, make_venue(db, capacity=100))
    )
    assert approve(login_as(Users.VENUE_STAFF), replacement["id"]).status_code == 200

    response = login_as(Users.COORDINATOR).post(_request_path(secured.event.id), json={})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == EventStatus.AWAITING_SAFETY_CHECK


@pytest.mark.story("12.6", ac=12)
def test_confirming_is_allowed_once_the_replacement_is_approved_and_the_event_reviewed_again(
    login_as, db: Session
):
    """As before: the replacement changes the venue bookings an approval saw (21.2 AC14), so the
    event is reviewed again - then it confirms, the mark no longer in the way."""
    secured = make_secured_event(db)
    _approve_review(db, secured)
    _mark(db, secured.booking)
    assert login_as(Users.COORDINATOR).post(_confirm_path(secured.event.id)).status_code == 409
    replacement = created(
        replace(login_as(Users.COORDINATOR), secured.booking.id, make_venue(db, capacity=100))
    )
    assert approve(login_as(Users.VENUE_STAFF), replacement["id"]).status_code == 200
    _approve_review(db, secured, day=2)

    response = login_as(Users.COORDINATOR).post(_confirm_path(secured.event.id))

    assert response.status_code == 200, response.text
    assert response.json()["status"] == EventStatus.CONFIRMED


@pytest.mark.story("12.6", ac=12)
def test_a_review_and_a_confirmation_are_allowed_once_the_mark_clears(
    coordinator_client, db: Session
):
    """The unavailability ended (9.4 AC6): the same event, its approval unchanged, goes on."""
    secured = make_secured_event(db)
    _approve_review(db, secured)
    _mark(db, secured.booking)
    assert coordinator_client.post(_confirm_path(secured.event.id)).status_code == 409
    secured.booking.venue_unavailable_marked_at = None
    db.flush()

    confirmed = coordinator_client.post(_confirm_path(secured.event.id))

    assert confirmed.status_code == 200, confirmed.text


@pytest.mark.story("12.6", ac=12)
def test_a_review_is_allowed_once_the_mark_clears(coordinator_client, db: Session):
    secured = make_secured_event(db)
    _mark(db, secured.booking)
    assert coordinator_client.post(_request_path(secured.event.id), json={}).status_code == 409
    secured.booking.venue_unavailable_marked_at = None
    db.flush()

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 200, response.text


# --- what does not block -------------------------------------------------------------------------
@pytest.mark.story("12.6", ac=12)
def test_an_event_with_no_marked_booking_is_unaffected(coordinator_client, db: Session):
    """Another event's marked booking is that event's: it is refused, and this one - dated apart,
    so the two never share a venue - is reviewed as it always was."""
    marked = make_secured_event(db)
    _mark(db, marked.booking)
    secured = make_secured_event(
        db,
        starts_at=datetime(2030, 5, 6, 1, 0, tzinfo=UTC),
        ends_at=datetime(2030, 5, 6, 9, 0, tzinfo=UTC),
    )

    refused = coordinator_client.post(_request_path(marked.event.id), json={})
    allowed = coordinator_client.post(_request_path(secured.event.id), json={})

    assert refused.status_code == 409, refused.text
    assert allowed.status_code == 200, allowed.text


@pytest.mark.story("12.6", ac=12)
@pytest.mark.parametrize(
    "closed_as",
    [
        BookingStatus.REJECTED,
        BookingStatus.WITHDRAWN,
        BookingStatus.CANCELLED,
        BookingStatus.EXPIRED,
    ],
)
def test_a_mark_left_on_a_closed_booking_blocks_nothing(coordinator_client, db, closed_as):
    """A closed booking holds nothing, so its mark is history (9.4): beside a live marked booking
    that does block, the closed one is not even named."""
    secured = make_secured_event(db)
    closed_venue = make_venue(db, name=f"Closed Annex {uuid.uuid4().hex[:8]}")
    make_booking(
        db,
        event_id=secured.event.id,
        venue_id=closed_venue.id,
        starts_at=secured.event.starts_at,
        ends_at=secured.event.ends_at,
        status=closed_as,
        venue_unavailable_marked_at=datetime.now(UTC),
        **({"hold_expires_at": datetime.now(UTC)} if closed_as == BookingStatus.EXPIRED else {}),
    )
    _mark(db, secured.booking)

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert _sentence(_venue_name(db, secured)) in detail
    assert closed_venue.name not in detail


# --- a pending replacement blocks like a mark (PO decision, review of #123) ---------------------
# 9.4 AC3: an event that is Awaiting Safety Check or Confirmed returns to Planning, so its
# replacement venue and safety check are done again before it is confirmed again. The mark clears
# when the closure is removed, but the replacement asked for is still undecided, and approving it
# later changes the venue the review saw - so until it is approved or withdrawn, the event is
# neither sent for a review nor confirmed, the replacement's venue named.
def _marked_with_a_pending_replacement(login_as, db: Session, secured: SecuredEvent):
    _mark(db, secured.booking)
    replacement = created(
        replace(login_as(Users.COORDINATOR), secured.booking.id, make_venue(db, capacity=100))
    )
    _clear_the_mark(db, secured)
    return replacement


def _replacement_venue_name(db: Session, replacement: dict) -> str:
    db.expire_all()
    return db.get(VenueBooking, uuid.UUID(replacement["id"])).venue.name


@pytest.mark.story("12.6", ac=12)
def test_a_review_is_refused_while_a_replacement_is_pending_even_once_the_mark_clears(
    login_as, db: Session
):
    secured = make_secured_event(db)
    replacement = _marked_with_a_pending_replacement(login_as, db, secured)
    name = _replacement_venue_name(db, replacement)

    response = login_as(Users.COORDINATOR).post(_request_path(secured.event.id), json={})

    assert response.status_code == 409, response.text
    assert _pending_sentence(name) in response.json()["detail"]
    db.refresh(secured.event)
    assert secured.event.status == EventStatus.PLANNING
    summary = login_as(Users.COORDINATOR).get(_summary_path(secured.event.id)).json()
    assert _pending_sentence(name) in summary["request_blockers"]


@pytest.mark.story("12.6", ac=12)
def test_confirming_is_refused_while_a_replacement_is_pending_even_once_the_mark_clears(
    login_as, db: Session
):
    """The reviewer's scenario: the original was approved by the Safety Officer, its mark clears
    with the closure, and the replacement is still pending - Confirm must not go through, since
    approving the replacement afterwards would leave a Confirmed event at a venue nobody
    reviewed."""
    secured = make_secured_event(db)
    _approve_review(db, secured)
    replacement = _marked_with_a_pending_replacement(login_as, db, secured)
    name = _replacement_venue_name(db, replacement)

    response = login_as(Users.COORDINATOR).post(_confirm_path(secured.event.id))

    assert response.status_code == 409, response.text
    assert _pending_sentence(name) in response.json()["detail"]
    db.refresh(secured.event)
    assert secured.event.status == EventStatus.PLANNING
    summary = login_as(Users.COORDINATOR).get(_summary_path(secured.event.id)).json()
    assert _pending_sentence(name) in summary["confirm_blockers"]


@pytest.mark.story("12.6", ac=12)
def test_a_review_is_allowed_once_the_pending_replacement_is_withdrawn(login_as, db: Session):
    secured = make_secured_event(db)
    replacement = _marked_with_a_pending_replacement(login_as, db, secured)
    assert (
        login_as(Users.COORDINATOR).post(_request_path(secured.event.id), json={}).status_code
        == 409
    )
    withdrawn = login_as(Users.COORDINATOR).post(f"/bookings/{replacement['id']}/withdraw")
    assert withdrawn.status_code == 200, withdrawn.text

    response = login_as(Users.COORDINATOR).post(_request_path(secured.event.id), json={})

    assert response.status_code == 200, response.text


@pytest.mark.story("12.6", ac=12)
def test_confirming_is_allowed_once_the_pending_replacement_is_withdrawn(login_as, db: Session):
    secured = make_secured_event(db)
    _approve_review(db, secured)
    replacement = _marked_with_a_pending_replacement(login_as, db, secured)
    assert login_as(Users.COORDINATOR).post(_confirm_path(secured.event.id)).status_code == 409
    withdrawn = login_as(Users.COORDINATOR).post(f"/bookings/{replacement['id']}/withdraw")
    assert withdrawn.status_code == 200, withdrawn.text

    response = login_as(Users.COORDINATOR).post(_confirm_path(secured.event.id))

    assert response.status_code == 200, response.text


@pytest.mark.story("12.6", ac=12)
def test_a_review_and_a_confirmation_are_allowed_once_the_pending_replacement_is_approved(
    login_as, db: Session
):
    """Approved, the replacement is the requirement's booking and the original is released; the
    event is reviewed again on the new venue (21.2 AC14) and then confirms."""
    secured = make_secured_event(db)
    _approve_review(db, secured)
    replacement = _marked_with_a_pending_replacement(login_as, db, secured)
    assert login_as(Users.COORDINATOR).post(_confirm_path(secured.event.id)).status_code == 409
    assert approve(login_as(Users.VENUE_STAFF), replacement["id"]).status_code == 200
    _approve_review(db, secured, day=2)

    response = login_as(Users.COORDINATOR).post(_confirm_path(secured.event.id))

    assert response.status_code == 200, response.text
    assert response.json()["status"] == EventStatus.CONFIRMED


@pytest.mark.story("12.6", ac=12)
def test_a_replacement_that_is_no_longer_pending_is_not_named(login_as, db: Session):
    """Only a pending replacement blocks: once withdrawn it holds nothing, so it is not named."""
    secured = make_secured_event(db)
    replacement = _marked_with_a_pending_replacement(login_as, db, secured)
    name = _replacement_venue_name(db, replacement)
    login_as(Users.COORDINATOR).post(f"/bookings/{replacement['id']}/withdraw")

    summary = login_as(Users.COORDINATOR).get(_summary_path(secured.event.id)).json()

    assert _pending_sentence(name) not in summary["request_blockers"]


# --- one refusal lists every blocker (21.2 AC19, AC21) ------------------------------------------
def _with_a_second_requirement_unbooked(db: Session, secured: SecuredEvent) -> None:
    make_venue_requirement(
        db,
        secured.event.id,
        position=1,
        name="Breakout room",
        starts_at=secured.event.starts_at,
        ends_at=secured.event.ends_at,
    )
    db.refresh(secured.event)


@pytest.mark.story("12.6", ac=12)
def test_the_review_refusal_names_the_venue_and_every_other_thing_missing(
    coordinator_client, db: Session
):
    """21.2 AC19: "Arrangements not secured -> 409 naming each missing one". A marked booking and a
    requirement with no approved venue are both said, not only the first the code reached."""
    secured = make_secured_event(db)
    _mark(db, secured.booking)
    _with_a_second_requirement_unbooked(db, secured)

    response = coordinator_client.post(_request_path(secured.event.id), json={})

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert _sentence(_venue_name(db, secured)) in detail
    assert safety_service.REQUIREMENT_NOT_BOOKED.format(name="Breakout room") in detail


@pytest.mark.story("12.6", ac=12)
def test_the_confirmation_refusal_names_the_venue_and_every_other_blocker(
    coordinator_client, db: Session
):
    """21.2 AC21: "naming each blocker". The review was approved before the second requirement was
    added, so its facts are out of date as well as the venue being unavailable."""
    secured = make_secured_event(db)
    _approve_review(db, secured)
    _mark(db, secured.booking)
    _with_a_second_requirement_unbooked(db, secured)

    response = coordinator_client.post(_confirm_path(secured.event.id))

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert _sentence(_venue_name(db, secured)) in detail
    assert safety_service.REQUIREMENT_NOT_BOOKED.format(name="Breakout room") in detail


@pytest.mark.story("12.6", ac=12)
def test_the_summary_lists_the_unavailable_venue_among_the_confirm_blockers(
    coordinator_client, db: Session
):
    """The page offers Confirm from ``confirm_blockers``: the unavailable venue is in it, as it is
    in ``request_blockers``, so Confirm is not offered only for the 409 to refuse it."""
    secured = make_secured_event(db)
    _approve_review(db, secured)
    _mark(db, secured.booking)

    body = coordinator_client.get(_summary_path(secured.event.id)).json()

    assert _sentence(_venue_name(db, secured)) in body["confirm_blockers"]
