"""Story 9.4: mark a venue temporarily unavailable.

The reasons a period can carry (migration 022).
Add, edit, end and remove a period, the preview of what it would affect, and who may.
What a saved period does to the bookings it covers - rejecting each pending request and cancelling
each approved booking, the event going back to Planning, who is told - is story 9.5's, which
replaced 9.4 AC3, AC4, AC6 and AC10 (CL-193) and extends AC2:
tests/venues/test_closure_ends_bookings.py.
A pending request that overlaps a period cannot be approved while it stands (AC7).

AC1  Venue Staff mark a venue unavailable from a start to an end with a reason: Maintenance,
     Equipment failure, Renovation, Safety concern or Other, and a description, which every
     reason needs (PO decision, 14 Oct 2026). It shows on the venue's calendar and is excluded
     from venue searches.

The table's own rules: the CHECK constraints refuse a reason outside the five and a period
without a description, migration 022 moves existing rows onto the new set, and the calendar and
the booking request name each reason.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings.models import VenueBooking
from app.common.audit import AuditLog
from app.events.models import Event, EventStatus
from app.notifications.models import Notification
from app.venues import service as venue_service
from app.venues.models import Venue, VenueUnavailabilityPeriod
from app.venues.schemas import VenueUnavailabilityCreate, VenueUnavailabilityUpdate
from tests.support.factories import (
    approval_payload,
    make_booking,
    make_event,
    make_unavailability,
    make_venue,
)
from tests.support.seed import Users

SGT = timezone(timedelta(hours=8))
MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"

REASON_CONSTRAINT = "ck_venue_unavailability_reason"
DESCRIPTION_CONSTRAINT = "ck_venue_unavailability_description"

# The table as it stood before migration 022: INTERNAL_USE allowed, no EQUIPMENT_FAILURE, and an
# Other that needs no description. IF EXISTS keeps this valid on a database 020 has not reached.
PRE_022_SCHEMA = (
    f"ALTER TABLE venue_unavailability_periods DROP CONSTRAINT IF EXISTS {DESCRIPTION_CONSTRAINT};"
    f" ALTER TABLE venue_unavailability_periods DROP CONSTRAINT {REASON_CONSTRAINT};"
    f" ALTER TABLE venue_unavailability_periods ADD CONSTRAINT {REASON_CONSTRAINT} CHECK"
    " (reason IN ('MAINTENANCE', 'RENOVATION', 'SAFETY', 'INTERNAL_USE', 'OTHER'));"
)

# Story 9.4 AC1: the five reasons, as the database stores them.
REASONS = ["MAINTENANCE", "EQUIPMENT_FAILURE", "RENOVATION", "SAFETY", "OTHER"]
# The names the page gives each reason (the calendar's `reason` is the code).


def _at(day: int, hour: int = 0) -> datetime:
    """A Singapore-time moment in March 2027, a month no seed row touches."""
    return datetime(2027, 3, day, hour, tzinfo=SGT)


def _insert(
    db: Session, venue_id: uuid.UUID, reason: str, notes: str | None, day: int
) -> uuid.UUID:
    """A period written in SQL, so it is stored exactly as given, whatever the models say."""
    return db.execute(
        text(
            "INSERT INTO venue_unavailability_periods (venue_id, starts_at, ends_at, reason, notes)"
            " VALUES (:venue_id, :starts_at, :ends_at, :reason, :notes) RETURNING id"
        ),
        {
            "venue_id": venue_id,
            "starts_at": _at(day),
            "ends_at": _at(day + 1),
            "reason": reason,
            "notes": notes,
        },
    ).scalar_one()


def _refused(db: Session, reason: str, notes: str | None) -> IntegrityError | None:
    """The database's refusal of a period with ``reason`` and ``notes``, or None if it took it."""
    venue = make_venue(db)
    try:
        with db.begin_nested():
            _insert(db, venue.id, reason, notes, day=1)
    except IntegrityError as exc:
        return exc
    return None


@pytest.mark.story("9.4", ac=1)
@pytest.mark.parametrize("notes", ["Gym floor relaid", "Members' studio closed"])
def test_internal_use_is_no_longer_a_reason(db, notes):
    """The five reasons are AC1's: a code outside them is refused by the table itself."""
    refusal = _refused(db, "INTERNAL_USE", notes)

    assert refusal is not None, "INTERNAL_USE was accepted"
    assert REASON_CONSTRAINT in str(refusal.orig)


@pytest.mark.story("9.4", ac=1)
@pytest.mark.parametrize("reason", REASONS)
@pytest.mark.parametrize("notes", [None, "", "   ", "\t\n"])
def test_every_reason_needs_a_description_in_the_table_itself(db, reason, notes):
    """AC1 (PO decision, 14 Oct 2026): a period with no description is refused whatever wrote
    it, for any reason. A description makes it valid."""
    refusal = _refused(db, reason, notes)

    assert refusal is not None, f"{reason} with notes {notes!r} was accepted"
    assert DESCRIPTION_CONSTRAINT in str(refusal.orig)
    assert _refused(db, reason, "Gala stage being built") is None


@pytest.mark.story("9.4", ac=1)
def test_migration_022_moves_existing_periods_onto_the_five_reasons(db):
    """Run on pre-020 rows inside the test's transaction, which is rolled back: Internal use
    becomes Other, saying so and keeping what was written; a period of any reason with nothing
    written gets a description; the rest is left as it was. Afterwards the table refuses what AC1
    refuses."""
    migration = next(MIGRATIONS.glob("022_*.sql"), None)
    assert migration is not None, "migration 022 has not been written"
    conn = db.connection()
    conn.exec_driver_sql(PRE_022_SCHEMA)
    venue = make_venue(db)
    internal_bare = _insert(db, venue.id, "INTERNAL_USE", None, day=1)
    internal_noted = _insert(db, venue.id, "INTERNAL_USE", "Gym floor relaid", day=2)
    other_null = _insert(db, venue.id, "OTHER", None, day=3)
    other_blank = _insert(db, venue.id, "OTHER", "   ", day=4)
    other_described = _insert(db, venue.id, "OTHER", "Gala stage being built", day=5)
    maintenance = _insert(db, venue.id, "MAINTENANCE", None, day=6)
    renovation_blank = _insert(db, venue.id, "RENOVATION", "  ", day=7)
    safety_described = _insert(db, venue.id, "SAFETY", "Rewiring", day=8)

    conn.exec_driver_sql(migration.read_text(encoding="utf-8"))

    def stored(period_id: uuid.UUID) -> tuple[str, str | None]:
        return tuple(
            db.execute(
                text("SELECT reason, notes FROM venue_unavailability_periods WHERE id = :id"),
                {"id": period_id},
            ).one()
        )

    assert stored(internal_bare) == ("OTHER", "Internal use")
    assert stored(internal_noted) == ("OTHER", "Internal use - Gym floor relaid")
    assert stored(other_null) == ("OTHER", "No description recorded.")
    assert stored(other_blank) == ("OTHER", "No description recorded.")
    assert stored(other_described) == ("OTHER", "Gala stage being built")
    assert stored(maintenance) == ("MAINTENANCE", "No description recorded.")
    assert stored(renovation_blank) == ("RENOVATION", "No description recorded.")
    assert stored(safety_described) == ("SAFETY", "Rewiring")
    refusal = _refused(db, "INTERNAL_USE", "x")
    assert refusal is not None and REASON_CONSTRAINT in str(refusal.orig)
    refusal = _refused(db, "MAINTENANCE", None)
    assert refusal is not None and DESCRIPTION_CONSTRAINT in str(refusal.orig)


@pytest.mark.story("9.4", ac=1)
def test_the_calendar_carries_each_reason_with_its_description(db, venue_staff_client):
    """AC1: a period shows with its reason - Equipment failure is one of the five, Safety concern
    is the code SAFETY - and the description it was given."""
    venue = make_venue(db)
    for day, reason in enumerate(REASONS, start=1):
        make_unavailability(
            db,
            venue_id=venue.id,
            starts_at=_at(day),
            ends_at=_at(day + 1),
            reason=reason,
            notes=f"{reason} work",
        )

    response = venue_staff_client.get(
        f"/venues/{venue.id}/calendar",
        params={"starts_at": _at(1).isoformat(), "ends_at": _at(28).isoformat()},
    )

    assert response.status_code == 200, response.text
    described = {window["reason"]: window["description"] for window in response.json()}
    assert described == {reason: f"{reason} work" for reason in REASONS}
    assert {window["label"] for window in response.json()} == {f"{r} work" for r in REASONS}


@pytest.mark.story("9.4", ac=1)
@pytest.mark.story("9.5", ac=6)
def test_a_venue_closed_for_equipment_failure_cannot_be_requested(db, coordinator_client):
    """12.1 AC14 for the new reason: the refusal says why the venue is closed."""
    venue = make_venue(db)
    make_unavailability(
        db,
        venue_id=venue.id,
        starts_at=_at(4),
        ends_at=_at(6),
        reason="EQUIPMENT_FAILURE",
    )
    event = make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=_at(5, 10),
        ends_at=_at(5, 12),
    )

    response = coordinator_client.post(
        "/bookings", json={"event_id": str(event.id), "venue_id": str(venue.id)}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        f"{venue.name} is closed for equipment failure from Thu 4 Mar 2027, 00:00 to "
        "Sat 6 Mar 2027, 00:00."
    )


# =====================================================================================
# Add, edit, end and remove a period; preview what it would affect; who may.
#
#   POST   /venues/{id}/unavailability                       add
#   PATCH  /venues/{id}/unavailability/{period_id}           edit, or {"end_now": true} alone
#   DELETE /venues/{id}/unavailability/{period_id}           remove a period not yet started
#   GET    /venues/{id}/unavailability/affected-bookings     preview (AC2)
#
# A period's body is {starts_at, ends_at, reason, description}; ``description`` is the column
# ``notes``. Marking bookings and the event's status are asserted in the sections below, not
# here.
# =====================================================================================
PERIOD_FIELDS = {"id", "venue_id", "starts_at", "ends_at", "reason", "description"}

# Audit actions every write leaves, one row each.
CREATED, UPDATED, ENDED, REMOVED = (
    "VENUE_UNAVAILABILITY_CREATED",
    "VENUE_UNAVAILABILITY_UPDATED",
    "VENUE_UNAVAILABILITY_ENDED",
    "VENUE_UNAVAILABILITY_REMOVED",
)

# Every case here is days away from the clock, so none depends on when it runs, except the two
# that ask for the server's own now (End now, and the audit row), which bracket it, and the
# boundary at exactly now, which calls the service with a ``now`` of its own as 12.7's tests do.
STAFF_ID = Users.VENUE_STAFF.id


def _days_from_now(days: float) -> datetime:
    """A moment that far from now, to the second - used only where the case is days away from
    any boundary, so the clock cannot change its answer."""
    return datetime.now(UTC).replace(microsecond=0) + timedelta(days=days)


def _url(venue_id: uuid.UUID, period_id: uuid.UUID | None = None) -> str:
    base = f"/venues/{venue_id}/unavailability"
    return base if period_id is None else f"{base}/{period_id}"


def _preview_url(venue_id: uuid.UUID) -> str:
    return f"/venues/{venue_id}/unavailability/affected-bookings"


def _body(starts_at: datetime, ends_at: datetime, **overrides) -> dict:
    body = {
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "reason": "MAINTENANCE",
        "description": "Scheduled servicing",
    }
    body.update(overrides)
    return body


def _future_body(**overrides) -> dict:
    """A period two days long that starts 10 days from now: not started, whatever the clock."""
    return _body(_days_from_now(10), _days_from_now(12), **overrides)


def _periods(db: Session, venue_id: uuid.UUID) -> list[VenueUnavailabilityPeriod]:
    db.expire_all()
    return list(
        db.scalars(
            select(VenueUnavailabilityPeriod).where(VenueUnavailabilityPeriod.venue_id == venue_id)
        )
    )


def _audit(db: Session, action: str, entity_id: uuid.UUID) -> list[AuditLog]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditLog).where(AuditLog.action == action, AuditLog.entity_id == entity_id)
        )
    )


def _venue_audit_count(db: Session, venue_id: uuid.UUID) -> int:
    """The audit rows this venue's writes leave. Not every row: another request may release a
    lapsed hold anywhere and write rows of its own, which this test is not about."""
    return db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.details["venue_id"].astext == str(venue_id))
    )


def _as_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _started(db: Session, venue_id: uuid.UUID) -> VenueUnavailabilityPeriod:
    """A period in force: it began a day ago and ends in a day, well clear of now either way."""
    return _period(db, venue_id, _days_from_now(-1), _days_from_now(1))


def _staff(db: Session) -> User:
    return db.get(User, STAFF_ID)


def _period(
    db: Session, venue_id: uuid.UUID, starts_at: datetime, ends_at: datetime, **overrides
) -> VenueUnavailabilityPeriod:
    return make_unavailability(
        db, venue_id=venue_id, starts_at=starts_at, ends_at=ends_at, **overrides
    )


# --- AC1: add a period -----------------------------------------------------------------------
@pytest.mark.story("9.4", ac=1)
@pytest.mark.parametrize("reason", ["MAINTENANCE", "EQUIPMENT_FAILURE", "RENOVATION", "SAFETY"])
def test_venue_staff_add_a_period_for_each_reason(db, venue_staff_client, reason):
    """AC1: 201, the period as stored, the Venue Staff member who made it."""
    venue = make_venue(db)

    response = venue_staff_client.post(_url(venue.id), json=_future_body(reason=reason))

    assert response.status_code == 201, response.text
    created = response.json()
    assert set(created) == PERIOD_FIELDS
    assert (created["venue_id"], created["reason"]) == (str(venue.id), reason)
    (stored,) = _periods(db, venue.id)
    assert str(stored.id) == created["id"]
    assert stored.reason == reason
    assert stored.created_by_id == Users.VENUE_STAFF.id


@pytest.mark.story("9.4", ac=1)
def test_other_with_a_description_is_accepted(db, venue_staff_client):
    """AC1."""
    venue = make_venue(db)

    response = venue_staff_client.post(
        _url(venue.id), json=_future_body(reason="OTHER", description="Gala stage being built")
    )

    assert response.status_code == 201, response.text
    assert response.json()["description"] == "Gala stage being built"
    assert _periods(db, venue.id)[0].notes == "Gala stage being built"


@pytest.mark.story("9.4", ac=1)
@pytest.mark.parametrize("reason", REASONS)
@pytest.mark.parametrize("description", [None, "", "   ", "\t\n", "<omitted>"])
def test_a_block_off_without_a_description_is_refused(db, venue_staff_client, reason, description):
    """AC1 (PO decision, 14 Oct 2026): 422 and nothing saved, for a missing, empty or blank
    description, whichever reason is given - every block off says why."""
    venue = make_venue(db)
    body = _future_body(reason=reason, description=description)
    if description == "<omitted>":
        del body["description"]

    response = venue_staff_client.post(_url(venue.id), json=body)

    assert response.status_code == 422, response.text
    assert _periods(db, venue.id) == []


@pytest.mark.story("9.4", ac=1)
@pytest.mark.parametrize("reason", ["INTERNAL_USE", "WEATHER", "", "maintenance"])
def test_a_reason_outside_the_five_is_refused(db, venue_staff_client, reason):
    """AC1: 422, nothing saved. Codes are exact, so lower case is refused too."""
    venue = make_venue(db)

    response = venue_staff_client.post(
        _url(venue.id), json=_future_body(reason=reason, description="x")
    )

    assert response.status_code == 422, response.text
    assert _periods(db, venue.id) == []


@pytest.mark.story("9.4", ac=1)
def test_the_refusal_of_a_missing_description_says_what_is_needed(db, venue_staff_client):
    """AC1: the sentence the page shows, in the backend's own words."""
    venue = make_venue(db)

    response = venue_staff_client.post(_url(venue.id), json=_future_body(description=None))

    assert response.status_code == 422
    assert response.json()["detail"] == "Describe why the venue is blocked off."


@pytest.mark.story("9.4", ac=1)
def test_an_unknown_venue_is_not_found(db, venue_staff_client):
    """AC1: 404 for a venue that is not there; a known venue takes the same body (201), so
    the 404 is the venue's and not the route's."""
    known = make_venue(db)
    assert venue_staff_client.post(_url(known.id), json=_future_body()).status_code == 201

    response = venue_staff_client.post(_url(uuid.uuid4()), json=_future_body())

    assert response.status_code == 404


@pytest.mark.story("9.4", ac=1)
def test_a_withdrawn_venue_can_be_marked_unavailable(db, venue_staff_client):
    """AC1: editing a withdrawn venue is allowed today, so marking it is too."""
    venue = make_venue(db, status="WITHDRAWN")

    response = venue_staff_client.post(_url(venue.id), json=_future_body())

    assert response.status_code == 201, response.text


@pytest.mark.story("9.4", ac=1)
def test_the_calendar_shows_the_new_period_with_its_reason_description_and_id(
    db, venue_staff_client
):
    """AC1: AC1's "shows on the venue's calendar", and the period's id so the page can
    target it for an edit."""
    venue = make_venue(db)
    starts_at, ends_at = _days_from_now(10), _days_from_now(12)
    created = venue_staff_client.post(
        _url(venue.id),
        json=_body(starts_at, ends_at, reason="OTHER", description="Gala stage being built"),
    ).json()

    response = venue_staff_client.get(
        f"/venues/{venue.id}/calendar",
        params={
            "starts_at": (starts_at - timedelta(days=1)).isoformat(),
            "ends_at": (ends_at + timedelta(days=1)).isoformat(),
        },
    )

    assert response.status_code == 200, response.text
    (window,) = response.json()
    assert window["id"] == created["id"]
    assert (window["reason"], window["label"]) == ("OTHER", "Gala stage being built")


@pytest.mark.story("9.4", ac=1)
def test_the_calendar_carries_a_closures_description_apart_from_its_label(db, venue_staff_client):
    """AC1: the page's Edit prefills from the closure's own description, so the
    window says it, as the label does; a booking's window has none, and its label is its event."""
    venue = make_venue(db)
    described = _period(
        db, venue.id, _days_from_now(10), _days_from_now(11), reason="RENOVATION", notes="Floor"
    )
    bare = _period(
        db, venue.id, _days_from_now(12), _days_from_now(13), reason="SAFETY", notes="Wiring"
    )
    booking = _booking(
        db, venue.id, _days_from_now(14), _days_from_now(14) + timedelta(hours=2), status="PENDING"
    )

    response = venue_staff_client.get(
        f"/venues/{venue.id}/calendar",
        params={
            "starts_at": _days_from_now(9).isoformat(),
            "ends_at": _days_from_now(16).isoformat(),
        },
    )

    assert response.status_code == 200, response.text
    windows = {window["id"]: window for window in response.json() if window["id"] is not None}
    assert (windows[str(described.id)]["description"], windows[str(described.id)]["label"]) == (
        "Floor",
        "Floor",
    )
    assert (windows[str(bare.id)]["description"], windows[str(bare.id)]["label"]) == (
        "Wiring",
        "Wiring",
    )
    held = [window for window in response.json() if window["id"] is None]
    assert [window["description"] for window in held] == [None]
    assert held[0]["label"] == db.get(Event, booking.event_id).name


@pytest.mark.story("9.4", ac=1)
def test_a_period_added_through_the_api_keeps_the_venue_out_of_a_search(db, venue_staff_client):
    """AC1. cannot fail first, for the search half: 8.1 already leaves a blocked venue out
    and keeps one a closure only touches. Written through the new POST so it is red with it."""
    venue = make_venue(db)
    starts_at = _days_from_now(10).replace(hour=9, minute=0, second=0)
    ends_at = starts_at + timedelta(hours=8)
    assert (
        venue_staff_client.post(_url(venue.id), json=_body(starts_at, ends_at)).status_code == 201
    )

    def found(window_starts: datetime, window_ends: datetime) -> bool:
        result = venue_staff_client.get(
            "/venues/search",
            params={
                "search": venue.name,
                "starts_at": window_starts.isoformat(),
                "ends_at": window_ends.isoformat(),
            },
        ).json()
        return str(venue.id) in [hit["id"] for hit in result["venues"]]

    assert not found(starts_at + timedelta(hours=1), starts_at + timedelta(hours=2))
    assert found(ends_at, ends_at + timedelta(hours=1))


# --- AC5: end after start --------------------------------------------------------------------
@pytest.mark.story("9.4", ac=5)
@pytest.mark.parametrize("offset_minutes", [0, -1, -24 * 60])
def test_a_period_must_end_after_it_starts(db, venue_staff_client, offset_minutes):
    """AC5: end equal to or before start is 422 on create - not the database's 500."""
    venue = make_venue(db)
    starts_at = _days_from_now(10)

    response = venue_staff_client.post(
        _url(venue.id), json=_body(starts_at, starts_at + timedelta(minutes=offset_minutes))
    )

    assert response.status_code == 422, response.text
    assert _periods(db, venue.id) == []


@pytest.mark.story("9.4", ac=5)
@pytest.mark.parametrize(
    "edit",
    [
        {"ends_at": "<start>"},
        {"ends_at": "<before start>"},
        {"starts_at": "<after end>"},
    ],
)
def test_an_edit_may_not_leave_the_end_before_the_start(db, venue_staff_client, edit):
    """AC5 on edit: the rule applies to the period as it would be after the edit, so moving
    only the start past the end is refused too. The period is left as it was."""
    venue = make_venue(db)
    starts_at, ends_at = _days_from_now(10), _days_from_now(12)
    period = _period(db, venue.id, starts_at, ends_at)
    moments = {
        "<start>": starts_at,
        "<before start>": starts_at - timedelta(hours=1),
        "<after end>": ends_at + timedelta(hours=1),
    }
    body = {key: moments[value].isoformat() for key, value in edit.items()}

    response = venue_staff_client.patch(_url(venue.id, period.id), json=body)

    assert response.status_code == 422, response.text
    stored = _periods(db, venue.id)[0]
    assert (stored.starts_at, stored.ends_at) == (starts_at, ends_at)


@pytest.mark.story("9.4", ac=5)
@pytest.mark.parametrize("missing", ["starts_at", "ends_at"])
def test_both_ends_are_required_and_must_carry_a_timezone(db, venue_staff_client, missing):
    """AC5: a missing end, or a moment with no timezone, is 422."""
    venue = make_venue(db)
    body = _future_body()
    del body[missing]
    # The end is after the start in this body, so the missing zone is all that can refuse it.
    naive = {**_future_body(), "starts_at": _days_from_now(9).replace(tzinfo=None).isoformat()}

    assert venue_staff_client.post(_url(venue.id), json=body).status_code == 422
    assert venue_staff_client.post(_url(venue.id), json=naive).status_code == 422
    assert _periods(db, venue.id) == []


# --- AC6 (the period itself): end, remove, shorten, extend -----------------------------------
@pytest.mark.story("9.4", ac=6)
def test_end_now_ends_a_started_period_at_the_servers_now(db, venue_staff_client):
    """AC6: the server sets ``ends_at`` to its own now, not a moment the client names - it
    lies between a timestamp taken just before the request and one taken just after."""
    venue = make_venue(db)
    period = _started(db, venue.id)

    before = datetime.now(UTC)
    response = venue_staff_client.patch(_url(venue.id, period.id), json={"end_now": True})
    after = datetime.now(UTC)

    assert response.status_code == 200, response.text
    assert before <= _as_instant(response.json()["ends_at"]) <= after
    assert before <= _periods(db, venue.id)[0].ends_at <= after


@pytest.mark.story("9.4", ac=6)
def test_a_period_not_yet_started_is_removed(db, venue_staff_client):
    """AC6: the row is gone."""
    venue = make_venue(db)
    period = _period(db, venue.id, _days_from_now(10), _days_from_now(12))

    response = venue_staff_client.delete(_url(venue.id, period.id))

    assert response.status_code == 204, response.text
    assert _periods(db, venue.id) == []


@pytest.mark.story("9.4", ac=6)
def test_an_edit_changes_start_end_reason_and_description(db, venue_staff_client):
    """AC6: the four fields each change, shortening and extending included."""
    venue = make_venue(db)
    starts_at, ends_at = _days_from_now(10), _days_from_now(12)
    period = _period(db, venue.id, starts_at, ends_at)

    shortened = venue_staff_client.patch(
        _url(venue.id, period.id), json={"ends_at": (ends_at - timedelta(days=1)).isoformat()}
    )
    extended = venue_staff_client.patch(
        _url(venue.id, period.id),
        json={
            "starts_at": (starts_at - timedelta(days=1)).isoformat(),
            "ends_at": (ends_at + timedelta(days=3)).isoformat(),
            "reason": "RENOVATION",
            "description": "Floor relaid",
        },
    )

    assert shortened.status_code == 200, shortened.text
    assert _as_instant(shortened.json()["ends_at"]) == ends_at - timedelta(days=1)
    assert extended.status_code == 200, extended.text
    stored = _periods(db, venue.id)[0]
    assert (stored.starts_at, stored.ends_at) == (
        starts_at - timedelta(days=1),
        ends_at + timedelta(days=3),
    )
    assert (stored.reason, stored.notes) == ("RENOVATION", "Floor relaid")


@pytest.mark.story("9.4", ac=1)
@pytest.mark.story("9.4", ac=6)
def test_an_edit_may_not_leave_a_closure_without_its_description(db, venue_staff_client):
    """AC1 on edit (PO decision, 14 Oct 2026): clearing the description of a closure of any
    reason is refused, and the period is unchanged."""
    venue = make_venue(db)
    plain = _period(db, venue.id, _days_from_now(10), _days_from_now(12), notes="Servicing")
    other = _period(
        db, venue.id, _days_from_now(20), _days_from_now(22), reason="OTHER", notes="Gala stage"
    )

    cleared_plain = venue_staff_client.patch(_url(venue.id, plain.id), json={"description": ""})
    cleared_other = venue_staff_client.patch(_url(venue.id, other.id), json={"description": None})

    assert (cleared_plain.status_code, cleared_other.status_code) == (422, 422)
    stored = {period.id: period for period in _periods(db, venue.id)}
    assert stored[plain.id].notes == "Servicing"
    assert stored[other.id].notes == "Gala stage"


@pytest.mark.story("9.4", ac=6)
def test_a_period_starting_exactly_now_counts_as_not_started(db):
    """AC6: ``starts_at == now`` is not started - ending it would break
    ``ends_at > starts_at`` - so it cannot be ended, and it can be removed. Called on the service
    with a chosen ``now``, as 12.7's tests do."""
    venue = make_venue(db)
    now = _days_from_now(10)
    period = _period(db, venue.id, now, now + timedelta(days=1))

    with pytest.raises(venue_service.PeriodNotStarted):
        venue_service.end_unavailability(db, venue.id, period.id, actor=_staff(db), now=now)
    assert _periods(db, venue.id)[0].ends_at == now + timedelta(days=1)

    venue_service.remove_unavailability(db, venue.id, period.id, actor=_staff(db), now=now)
    assert _periods(db, venue.id) == []


@pytest.mark.story("9.4", ac=6)
def test_a_period_ending_exactly_now_has_ended(db):
    """AC6 at its boundary: ``ends_at == now`` is ended, and it is left as it was."""
    venue = make_venue(db)
    now = _days_from_now(10)
    period = _period(db, venue.id, now - timedelta(days=3), now)

    with pytest.raises(venue_service.PeriodAlreadyEnded):
        venue_service.end_unavailability(db, venue.id, period.id, actor=_staff(db), now=now)
    assert _periods(db, venue.id)[0].ends_at == now


@pytest.mark.story("9.4", ac=6)
def test_an_already_ended_period_cannot_be_ended_again(db, venue_staff_client):
    """AC6: a period that ended a day ago. 409, and the row is exactly as it was."""
    venue = make_venue(db)
    ends_at = _days_from_now(-1)
    period = _period(db, venue.id, ends_at - timedelta(days=3), ends_at)

    response = venue_staff_client.patch(_url(venue.id, period.id), json={"end_now": True})

    assert response.status_code == 409, response.text
    assert _periods(db, venue.id)[0].ends_at == ends_at


@pytest.mark.story("9.4", ac=6)
def test_a_started_period_cannot_be_removed(db, venue_staff_client):
    """AC6: a period in force is ended, not removed, so the calendar keeps its history.
    409, and the row is left."""
    venue = make_venue(db)
    period = _started(db, venue.id)

    response = venue_staff_client.delete(_url(venue.id, period.id))

    assert response.status_code == 409, response.text
    assert len(_periods(db, venue.id)) == 1


@pytest.mark.story("9.4", ac=6)
@pytest.mark.parametrize(
    "extra", [{"reason": "RENOVATION"}, {"description": "x"}, {"ends_at": "2030-01-01T00:00:00Z"}]
)
def test_end_now_stands_alone(db, venue_staff_client, extra):
    """AC6: ``end_now`` with any other field is 422 and changes nothing."""
    venue = make_venue(db)
    period = _started(db, venue.id)
    ends_at = period.ends_at

    response = venue_staff_client.patch(_url(venue.id, period.id), json={"end_now": True, **extra})

    assert response.status_code == 422, response.text
    assert _periods(db, venue.id)[0].ends_at == ends_at


@pytest.mark.story("9.4", ac=6)
def test_an_unknown_period_and_one_of_another_venue_are_not_found(db, venue_staff_client):
    """AC6: 404 for edit and removal alike. The period's own venue takes the same edit
    (200), so the 404 is the period's and not the route's."""
    venue, other = make_venue(db), make_venue(db)
    period = _period(db, venue.id, _days_from_now(10), _days_from_now(12))
    own = venue_staff_client.patch(_url(venue.id, period.id), json={"description": "ok"})
    assert own.status_code == 200, own.text

    for missing_id, venue_id in ((uuid.uuid4(), venue.id), (period.id, other.id)):
        patched = venue_staff_client.patch(_url(venue_id, missing_id), json={"description": "x"})
        deleted = venue_staff_client.delete(_url(venue_id, missing_id))
        assert (patched.status_code, deleted.status_code) == (404, 404)
    assert _periods(db, venue.id)[0].notes == "ok"


@pytest.mark.story("9.4", ac=6)
def test_every_write_leaves_an_audit_row(db, venue_staff_client):
    """AC6: creation, edit, end and removal each write one row, naming the actor,
    and an edit keeps what it replaced so the log is the history."""
    venue = make_venue(db)
    created = venue_staff_client.post(
        _url(venue.id), json=_body(_days_from_now(5), _days_from_now(6))
    ).json()
    period_id = uuid.UUID(created["id"])
    venue_staff_client.patch(_url(venue.id, period_id), json={"reason": "RENOVATION"})
    started = _started(db, venue.id)
    original_end = started.ends_at
    before = datetime.now(UTC)
    venue_staff_client.patch(_url(venue.id, started.id), json={"end_now": True})
    after = datetime.now(UTC)
    removable = _period(db, venue.id, _days_from_now(9), _days_from_now(10))
    venue_staff_client.delete(_url(venue.id, removable.id))

    (made,) = _audit(db, CREATED, period_id)
    (edited,) = _audit(db, UPDATED, period_id)
    (ended,) = _audit(db, ENDED, started.id)
    (removed,) = _audit(db, REMOVED, removable.id)

    for entry in (made, edited, ended, removed):
        assert entry.actor_id == Users.VENUE_STAFF.id
        assert entry.entity_type == "venue_unavailability_period"
        assert entry.details["venue_id"] == str(venue.id)
    assert edited.details["before"]["reason"] == "MAINTENANCE"
    assert edited.details["after"]["reason"] == "RENOVATION"
    assert _as_instant(ended.details["before"]["ends_at"]) == original_end
    assert before <= _as_instant(ended.details["after"]["ends_at"]) <= after
    assert removed.details["reason"] == "MAINTENANCE"


@pytest.mark.story("9.4", ac=6)
def test_a_refused_write_leaves_no_audit_row(db, venue_staff_client):
    """AC6, the refused half of the audit trail. cannot fail first: no route wrote an audit row
    before, so the count could not change; it guards the refused paths, and is paired with the
    audit-row case above."""
    venue = make_venue(db)
    period = _started(db, venue.id)
    before = _venue_audit_count(db, venue.id)

    venue_staff_client.post(_url(venue.id), json=_future_body(description=None))
    venue_staff_client.delete(_url(venue.id, period.id))
    venue_staff_client.patch(_url(venue.id, uuid.uuid4()), json={"end_now": True})

    assert _venue_audit_count(db, venue.id) == before


# --- AC1 (the period itself): in the past ----------------------------------------------------
@pytest.mark.story("9.4", ac=1)
def test_a_period_in_the_past_is_saved_and_shown(db, venue_staff_client):
    """AC1: nothing beyond AC5 limits the start, so a closure that has happened is
    kept and on the calendar."""
    venue = make_venue(db)
    starts_at, ends_at = _days_from_now(-10), _days_from_now(-9)

    response = venue_staff_client.post(_url(venue.id), json=_body(starts_at, ends_at))

    assert response.status_code == 201, response.text
    shown = venue_staff_client.get(
        f"/venues/{venue.id}/calendar",
        params={
            "starts_at": (starts_at - timedelta(days=1)).isoformat(),
            "ends_at": (ends_at + timedelta(days=1)).isoformat(),
        },
    ).json()
    assert [window["id"] for window in shown] == [response.json()["id"]]


# --- AC2: preview ----------------------------------------------------------------------------
def _booking(db: Session, venue_id: uuid.UUID, starts_at: datetime, ends_at: datetime, **kwargs):
    """A booking of a Planning event of its own, so two never share an event."""
    event_status = kwargs.pop("event_status", EventStatus.PLANNING)
    event = make_event(
        db,
        status=event_status,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    return make_booking(
        db, venue_id=venue_id, starts_at=starts_at, ends_at=ends_at, event_id=event.id, **kwargs
    )


def _preview(client, venue_id: uuid.UUID, starts_at: datetime, ends_at: datetime, **extra):
    return client.get(
        _preview_url(venue_id),
        params={"starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat(), **extra},
    )


def _ids(response) -> set[str]:
    assert response.status_code == 200, response.text
    return {entry["booking_id"] for entry in response.json()}


@pytest.mark.story("9.4", ac=2)
def test_the_preview_lists_pending_and_approved_bookings_that_overlap(db, venue_staff_client):
    """AC2: each with its event, status and held period."""
    venue = make_venue(db)
    day = _days_from_now(20).replace(hour=9, minute=0, second=0)
    pending = _booking(db, venue.id, day, day + timedelta(hours=2), status="PENDING")
    approved = _booking(
        db,
        venue.id,
        day + timedelta(days=1),
        day + timedelta(days=1, hours=2),
        status="APPROVED",
        event_status=EventStatus.CONFIRMED,
    )

    response = _preview(
        venue_staff_client, venue.id, day - timedelta(hours=1), day + timedelta(days=3)
    )

    assert _ids(response) == {str(pending.id), str(approved.id)}
    entry = next(item for item in response.json() if item["booking_id"] == str(approved.id))
    assert entry["status"] == "APPROVED"
    assert entry["event_name"] == db.get(Event, approved.event_id).name
    assert _as_instant(entry["held_from"]) == approved.held_from
    assert _as_instant(entry["held_until"]) == approved.held_until


@pytest.mark.story("9.4", ac=2)
def test_a_booking_overlapped_only_by_its_teardown_is_listed(db, venue_staff_client):
    """AC2: the held period, not the event's own, is what is measured; a window that only
    touches the end of it is not an overlap."""
    venue = make_venue(db)
    day = _days_from_now(20).replace(hour=10, minute=0, second=0)
    booking = _booking(
        db,
        venue.id,
        day,
        day + timedelta(hours=2),
        status="APPROVED",
        setup_minutes=60,
        teardown_minutes=30,
    )
    held_until = day + timedelta(hours=2, minutes=30)

    inside_teardown = _preview(
        venue_staff_client,
        venue.id,
        held_until - timedelta(minutes=15),
        held_until + timedelta(hours=1),
    )
    touching = _preview(venue_staff_client, venue.id, held_until, held_until + timedelta(hours=1))

    assert _ids(inside_teardown) == {str(booking.id)}
    assert _ids(touching) == set()


@pytest.mark.story("9.4", ac=2)
def test_the_preview_leaves_out_bookings_that_no_longer_hold_the_venue(db, venue_staff_client):
    """AC2: rejected, withdrawn, cancelled and expired ones hold nothing, so they are not
    listed; the live booking beside them is, which is what makes this red."""
    venue = make_venue(db)
    day = _days_from_now(20).replace(hour=9, minute=0, second=0)
    live = _booking(db, venue.id, day, day + timedelta(hours=2), status="PENDING")
    for status in ("REJECTED", "WITHDRAWN", "CANCELLED"):
        _booking(db, venue.id, day, day + timedelta(hours=2), status=status)
    _booking(
        db,
        venue.id,
        day,
        day + timedelta(hours=2),
        status="EXPIRED",
        hold_expires_at=day - timedelta(days=1),
    )

    response = _preview(
        venue_staff_client, venue.id, day - timedelta(hours=1), day + timedelta(hours=3)
    )

    assert _ids(response) == {str(live.id)}


@pytest.mark.story("9.4", ac=2)
def test_the_preview_is_for_this_venue_only(db, venue_staff_client):
    """AC2."""
    venue, elsewhere = make_venue(db), make_venue(db)
    day = _days_from_now(20).replace(hour=9, minute=0, second=0)
    mine = _booking(db, venue.id, day, day + timedelta(hours=2), status="APPROVED")
    _booking(db, elsewhere.id, day, day + timedelta(hours=2), status="APPROVED")

    response = _preview(
        venue_staff_client, venue.id, day - timedelta(hours=1), day + timedelta(hours=3)
    )

    assert _ids(response) == {str(mine.id)}


@pytest.mark.story("9.4", ac=2)
@pytest.mark.story("9.4", ac=8)
def test_the_preview_leaves_out_completed_events_and_periods_already_over(db, venue_staff_client):
    """AC2: a COMPLETED event's booking, and one whose held period has ended, are not
    candidates. A Confirmed event's booking on the same days is, which is what makes this red."""
    venue = make_venue(db)
    future = _days_from_now(20).replace(hour=9, minute=0, second=0)
    candidate = _booking(
        db,
        venue.id,
        future,
        future + timedelta(hours=2),
        status="APPROVED",
        event_status=EventStatus.CONFIRMED,
    )
    _booking(
        db,
        venue.id,
        future + timedelta(days=1),
        future + timedelta(days=1, hours=2),
        status="APPROVED",
        event_status=EventStatus.COMPLETED,
    )
    past = _days_from_now(-10).replace(hour=9, minute=0, second=0)
    _booking(db, venue.id, past, past + timedelta(hours=2), status="APPROVED")

    response = _preview(
        venue_staff_client, venue.id, past - timedelta(days=1), future + timedelta(days=3)
    )

    assert _ids(response) == {str(candidate.id)}


@pytest.mark.story("9.4", ac=2)
def test_the_preview_writes_nothing(db, venue_staff_client):
    """AC2: 200, no period, no audit row, no booking or event touched."""
    venue = make_venue(db)
    day = _days_from_now(20).replace(hour=9, minute=0, second=0)
    booking = _booking(db, venue.id, day, day + timedelta(hours=2), status="PENDING")
    audit_before = _venue_audit_count(db, venue.id)

    response = _preview(
        venue_staff_client, venue.id, day - timedelta(hours=1), day + timedelta(hours=3)
    )

    assert response.status_code == 200, response.text
    assert _periods(db, venue.id) == []
    assert _venue_audit_count(db, venue.id) == audit_before
    assert _audit(db, "BOOKING_REJECTED", booking.id) == []
    assert _audit(db, "BOOKING_RELEASED", booking.id) == []
    db.expire_all()
    assert db.get(VenueBooking, booking.id).status == "PENDING"


# --- AC9: who may do what --------------------------------------------------------------------
WRITES = ["post", "patch", "delete"]


def _write(client, method: str, venue_id: uuid.UUID, period_id: uuid.UUID):
    if method == "post":
        return client.post(_url(venue_id), json=_future_body())
    if method == "patch":
        return client.patch(_url(venue_id, period_id), json={"description": "x"})
    return client.delete(_url(venue_id, period_id))


@pytest.mark.story("9.4", ac=9)
@pytest.mark.story("9.5", ac=9)
@pytest.mark.parametrize("method", WRITES)
@pytest.mark.parametrize(
    "role", [Users.COORDINATOR, Users.LEAD, Users.TECH_SUPPORT, Users.SAFETY_OFFICER]
)
def test_other_internal_roles_cannot_add_edit_or_end(db, login_as, role, method):
    """AC9: 403, and the period is as it was. A period already exists so PATCH and DELETE
    have something to refuse. The Safety Officer (21.1) is a guard, cannot fail first: 21.1 gives
    that role no manage permission, so the refusal is already in place."""
    venue = make_venue(db)
    period = _period(db, venue.id, _days_from_now(10), _days_from_now(12))

    response = _write(login_as(role), method, venue.id, period.id)

    assert response.status_code == 403, response.text
    (stored,) = _periods(db, venue.id)
    # The factory's default description, written out, so the assertion compares with a value
    # and not with the row it is checking.
    assert (stored.reason, stored.notes) == ("MAINTENANCE", "Closed for testing")


@pytest.mark.story("9.4", ac=9)
@pytest.mark.story("9.5", ac=9)
@pytest.mark.parametrize("method", WRITES)
@pytest.mark.parametrize("role", [Users.ORGANISER, Users.ATTENDEE, None])
def test_external_roles_and_the_signed_out_cannot_add_edit_or_end(db, login_as, role, method):
    """AC9: 403 for a signed-in organiser or attendee, 401 when signed out."""
    venue = make_venue(db)
    period = _period(db, venue.id, _days_from_now(10), _days_from_now(12))
    client = login_as(role) if role is not None else login_as(Users.VENUE_STAFF)
    if role is None:
        client.logout()

    response = _write(client, method, venue.id, period.id)

    assert response.status_code == (401 if role is None else 403), response.text
    assert len(_periods(db, venue.id)) == 1


@pytest.mark.story("9.4", ac=9)
@pytest.mark.story("9.4", ac=2)
@pytest.mark.story("9.5", ac=9)
@pytest.mark.parametrize(
    "role",
    [
        Users.COORDINATOR,
        Users.LEAD,
        Users.TECH_SUPPORT,
        Users.SAFETY_OFFICER,
        Users.ORGANISER,
        None,
    ],
)
def test_only_venue_staff_may_preview(db, login_as, role):
    """AC2: the preview is part of marking a venue unavailable, so it is Venue Staff's. The
    Safety Officer (21.1) is a guard, cannot fail first: 21.1 gives that role no manage
    permission, so it is already refused."""
    venue = make_venue(db)
    day = _days_from_now(20)
    client = login_as(role or Users.VENUE_STAFF)
    if role is None:
        client.logout()

    response = _preview(client, venue.id, day, day + timedelta(days=1))

    assert response.status_code == (401 if role is None else 403), response.text


@pytest.mark.story("9.4", ac=9)
@pytest.mark.parametrize(
    "role", [Users.COORDINATOR, Users.LEAD, Users.TECH_SUPPORT, Users.SAFETY_OFFICER]
)
def test_other_internal_roles_read_the_reason_on_the_calendar(db, login_as, role):
    """AC9. cannot fail first, for the read half: 9.1 already shows a closure's reason to
    these roles, and the Safety Officer (21.1) has venues:read and venue_calendar:read through
    the internal roles' common set. Written through the new POST so it is red with it."""
    venue = make_venue(db)
    starts_at, ends_at = _days_from_now(10), _days_from_now(12)
    staff = login_as(Users.VENUE_STAFF)
    assert (
        staff.post(
            _url(venue.id),
            json=_body(starts_at, ends_at, reason="EQUIPMENT_FAILURE", description="Lift jammed"),
        ).status_code
        == 201
    )

    response = login_as(role).get(
        f"/venues/{venue.id}/calendar",
        params={
            "starts_at": (starts_at - timedelta(days=1)).isoformat(),
            "ends_at": (ends_at + timedelta(days=1)).isoformat(),
        },
    )

    assert response.status_code == 200, response.text
    (window,) = response.json()
    assert (window["reason"], window["label"]) == ("EQUIPMENT_FAILURE", "Lift jammed")


@pytest.mark.story("9.4", ac=9)
@pytest.mark.parametrize("role", [Users.ORGANISER, Users.ATTENDEE])
def test_organisers_and_attendees_see_no_calendar(db, login_as, role):
    """AC9. cannot fail first: they hold neither venues:read nor venue_calendar:read today
    (9.1 AC13), so the refusal is already in place; pinned so a later change cannot expose a
    closure's reason to them."""
    venue = make_venue(db)
    period = _period(db, venue.id, _days_from_now(10), _days_from_now(12), reason="SAFETY")

    response = login_as(role).get(
        f"/venues/{venue.id}/calendar",
        params={
            "starts_at": _days_from_now(9).isoformat(),
            "ends_at": _days_from_now(13).isoformat(),
        },
    )

    assert response.status_code == 403
    assert str(period.id) not in response.text


# =====================================================================================
# What a saved period does to the bookings it covers is story 9.5's, in
# test_closure_ends_bookings.py. The cases below write a closure straight to the table where
# they need one over a booking, so they test the rule beside it, not the save.
# =====================================================================================
def _day(days: float, hour: int = 10) -> datetime:
    """``hour`` o'clock UTC, that many days from now: a start well clear of the clock."""
    return (datetime.now(UTC) + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )


def _live(
    db: Session,
    venue_id: uuid.UUID,
    starts_at: datetime,
    hours: float = 2,
    **kwargs,
) -> VenueBooking:
    """A pending booking of a Planning event of its own, ``hours`` long."""
    return _booking(
        db, venue_id, starts_at, starts_at + timedelta(hours=hours), status="PENDING", **kwargs
    )


def _add(client, venue_id: uuid.UUID, starts_at: datetime, ends_at: datetime, **overrides):
    response = client.post(_url(venue_id), json=_body(starts_at, ends_at, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


# =====================================================================================
# The event goes back to Planning, and its coordinator and organiser are told.
#
# For each event with a booking a save ends (story 9.5, which replaced 9.4's marking):
#   * CONFIRMED -> PLANNING, once, with an event_status_history row (its reason naming the
#     venue) and an audit entry EVENT_RETURNED_TO_PLANNING; PLANNING stays; nothing else moves.
#   * one BOOKING_VENUE_UNAVAILABLE notification each to the event's assigned coordinator (when
#     it has one) and its organiser, naming the venue, the period and the reason. The Venue Staff
#     member who saved is never told. Ending a closure early or removing it sends nothing and
#     leaves the status alone.
# Awaiting Safety Check (story 21.1) goes back to Planning as a Confirmed event does.
# =====================================================================================
VENUE_UNAVAILABLE = "BOOKING_VENUE_UNAVAILABLE"


def _event_for(db: Session, status: str = EventStatus.PLANNING, **overrides) -> Event:
    """An event with the seed coordinator and organiser, unless overridden."""
    overrides.setdefault("assigned_coordinator_id", Users.COORDINATOR.id)
    return make_event(db, status=status, **overrides)


def _pending_of(
    db: Session, event: Event, venue_id: uuid.UUID, starts_at: datetime, **kwargs
) -> VenueBooking:
    return make_booking(
        db,
        venue_id=venue_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        event_id=event.id,
        **kwargs,
    )


def _told(db: Session, event_id: uuid.UUID) -> list[Notification]:
    db.expire_all()
    return list(
        db.scalars(
            select(Notification)
            .where(
                Notification.notification_type == VENUE_UNAVAILABLE,
                Notification.event_id == event_id,
            )
            .order_by(Notification.created_at, Notification.id)
        )
    )


def _status_of(db: Session, event_id: uuid.UUID) -> str:
    db.expire_all()
    return db.get(Event, event_id).status


def _on_singapore_date(moment: datetime) -> str:
    """The date as a notice words it: ``4 Mar 2027``, in Singapore time."""
    local = moment.astimezone(SGT)
    return f"{local.day} {local:%b %Y}"


# --- AC3: the event's status -----------------------------------------------------------------


@pytest.mark.story("9.4", ac=3)
def test_a_closure_written_to_the_table_changes_no_booking_or_event(db):
    """Re-pointed by 9.5 (the save, not the closure, ends a booking): a closure over a booking
    leaves the booking approved, its event where it was, and nobody told, for the one it covers
    and the one it does not. cannot fail first: nothing reads the table on its own."""
    venue = make_venue(db)
    reached = _event_for(db, EventStatus.CONFIRMED)
    untouched = _event_for(db, EventStatus.CONFIRMED)
    covered = _pending_of(db, reached, venue.id, _day(3), status="APPROVED")
    clear = _pending_of(db, untouched, venue.id, _day(20), status="APPROVED")

    _period(db, venue.id, _day(2), _day(7))

    assert (_stored(db, covered.id).status, _stored(db, clear.id).status) == ("APPROVED",) * 2
    assert _status_of(db, reached.id) == EventStatus.CONFIRMED
    assert _status_of(db, untouched.id) == EventStatus.CONFIRMED
    assert _told(db, reached.id) == [] and _told(db, untouched.id) == []


# --- AC4: the notifications ------------------------------------------------------------------


@pytest.mark.story("9.4", ac=4)
def test_a_refused_save_tells_nobody(db, login_as):
    """AC4. cannot fail first: no route notifies today; paired with the notice above. A
    save refused for its body (422), or by role (403), leaves no notification and the booking
    as it was."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.CONFIRMED)
    booking = _pending_of(db, event, venue.id, _day(3), status="APPROVED")

    refused_body = login_as(Users.VENUE_STAFF).post(
        _url(venue.id), json=_body(_day(2), _day(7), reason="OTHER", description=None)
    )
    refused_role = login_as(Users.COORDINATOR).post(_url(venue.id), json=_body(_day(2), _day(7)))

    assert (refused_body.status_code, refused_role.status_code) == (422, 403)
    assert _told(db, event.id) == []
    assert _status_of(db, event.id) == EventStatus.CONFIRMED
    assert _stored(db, booking.id).status == "APPROVED"


# (The save and the confirmation of one event, at the same moment, is with the AC10 races
# below: it needs their lock-watching helpers.)


# =====================================================================================
# A pending request that overlaps a period cannot be approved while it stands.
#
# ``approve_booking`` refuses, right after its not-pending check and as its own query once the
# row is locked, a request whose held period overlaps a period of its venue
# (``find_blocking_unavailability``, the live overlap - not the mark), with the same
# ``VenueBlocked`` the request step gives. The approve route answers it 409. Refusal order: not
# pending, venue closed, hold period started, expiry.
# =====================================================================================
LOCK_WAIT_SECONDS = 20


def _approve(client, booking_id: uuid.UUID, **overrides):
    return client.post(f"/bookings/{booking_id}/approve", json=approval_payload(**overrides))


def _stored(db: Session, booking_id: uuid.UUID) -> VenueBooking:
    db.expire_all()
    return db.get(VenueBooking, booking_id)


# --- AC7: the refusal ------------------------------------------------------------------------
@pytest.mark.story("9.4", ac=7)
@pytest.mark.story("9.5", ac=10)
def test_a_request_overlapping_a_period_cannot_be_approved_until_it_ends(db, login_as):
    """AC7: 409, still pending with no hold and nobody's decision; once the
    period is removed the same request is approved."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3))
    staff = login_as(Users.VENUE_STAFF)
    period = _period(db, venue.id, _day(2), _day(7))

    refused = _approve(staff, booking.id)

    assert refused.status_code == 409, refused.text
    stored = _stored(db, booking.id)
    assert stored.status == "PENDING"
    assert (stored.hold_expires_at, stored.decided_by_id) == (None, None)

    staff.delete(_url(venue.id, period.id))
    approved = _approve(staff, booking.id)

    assert approved.status_code == 200, approved.text
    assert _stored(db, booking.id).status == "APPROVED"


@pytest.mark.story("9.4", ac=7)
def test_the_refusal_uses_the_live_overlap(db, login_as):
    """AC7, re-pointed by 9.5 (nothing is marked any more): a closure written straight to the
    table sits over a request no save ended - one a save missed - and the request is still
    refused; a request no closure overlaps is approved. cannot fail first: the refusal reads
    the closure itself and is in place today."""
    venue, elsewhere = make_venue(db), make_venue(db)
    missed = _live(db, venue.id, _day(3))
    _period(db, venue.id, _day(2), _day(7))
    unaffected = _live(db, elsewhere.id, _day(3))
    staff = login_as(Users.VENUE_STAFF)

    assert _approve(staff, missed.id).status_code == 409
    assert _approve(staff, unaffected.id).status_code == 200


@pytest.mark.story("9.4", ac=7)
def test_the_refusal_names_the_venue_and_the_period(db, login_as):
    """AC7: the sentence the request step gives (12.1 AC14), not a new one."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3))
    starts_at, ends_at = _day(2), _day(7)
    staff = login_as(Users.VENUE_STAFF)
    _period(db, venue.id, starts_at, ends_at, reason="EQUIPMENT_FAILURE", notes="Lift jammed")

    refused = _approve(staff, booking.id)

    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail.startswith(f"{venue.name} is closed for equipment failure from ")
    assert _on_singapore_date(starts_at) in detail and _on_singapore_date(ends_at) in detail


@pytest.mark.story("9.4", ac=7)
def test_a_period_that_only_touches_the_request_does_not_stop_its_approval(db, login_as):
    """AC7. cannot fail first: no guard exists yet, so every approval passes; it pins the
    half-open rule beside the refusal above. A period ending exactly where the request's held
    period starts, and one starting exactly where it ends."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3, 10))
    staff = login_as(Users.VENUE_STAFF)
    _add(staff, venue.id, _day(3, 6), _day(3, 10))
    _add(staff, venue.id, _day(3, 12), _day(3, 18))

    approved = _approve(staff, booking.id)

    assert approved.status_code == 200, approved.text


@pytest.mark.story("9.4", ac=7)
@pytest.mark.parametrize("action", ["reject", "withdraw"])
def test_a_request_a_save_missed_can_still_be_rejected_or_withdrawn(db, login_as, action):
    """AC7, re-pointed by 9.5: the guard touches approval only. A request that sits inside a
    closure no save ended can still be rejected by Venue Staff or withdrawn by its coordinator.
    cannot fail first: these already work; it pins that nothing else refuses such a request."""
    venue = make_venue(db)
    staff = login_as(Users.VENUE_STAFF)
    booking = _live(db, venue.id, _day(3))
    _period(db, venue.id, _day(2), _day(7))

    if action == "reject":
        response = staff.post(f"/bookings/{booking.id}/reject", json={"decision_reason": "No."})
    else:
        response = login_as(Users.COORDINATOR).post(f"/bookings/{booking.id}/withdraw")

    assert response.status_code == 200, response.text


@pytest.mark.story("9.4", ac=7)
@pytest.mark.parametrize(
    ("case", "expected_status", "expected_in_detail"),
    [
        ("not_pending_and_closed", 409, "APPROVED"),
        ("closed_and_started", 409, "is closed for maintenance"),
        ("started_only", 409, "already started"),
        ("expiry_only", 422, "must expire in the future"),
    ],
)
def test_the_refusals_keep_their_order(db, login_as, case, expected_status, expected_in_detail):
    """AC7: not pending, then venue closed, then hold period started, then expiry. Only
    ``closed_and_started`` fails before the guard - the others cannot fail first: they are the
    existing refusals, pinned so the guard slots in without reordering them."""
    venue = make_venue(db)
    staff = login_as(Users.VENUE_STAFF)
    now = datetime.now(UTC)
    payload = {}
    if case == "not_pending_and_closed":
        booking = _booking(db, venue.id, _day(3), _day(3, 12), status="APPROVED")
    elif case in ("closed_and_started", "started_only"):
        booking = _booking(
            db, venue.id, now - timedelta(hours=1), now + timedelta(hours=1), status="PENDING"
        )
    else:
        booking = _live(db, venue.id, _day(3))
        payload = {"expires_in": timedelta(days=-1)}
    if case in ("not_pending_and_closed", "closed_and_started"):
        _period(db, venue.id, _day(-2), _day(7))

    response = _approve(staff, booking.id, **payload)

    assert response.status_code == expected_status, response.text
    assert expected_in_detail in response.json()["detail"]


# --- AC10 and 10.6: the save and the approval at the same moment -----------------------------
def _backend_pid(session: Session) -> int:
    return session.connection().exec_driver_sql("SELECT pg_backend_pid()").scalar()


def _is_waiting_on_a_lock(engine, pid: int) -> bool:
    with engine.connect() as watcher:
        waiting_on = watcher.execute(
            text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"), {"pid": pid}
        ).scalar()
        watcher.rollback()  # pg_stat_activity is a per-transaction snapshot
    return waiting_on == "Lock"


def _wait_until(engine, pids: dict[str, int], name: str) -> None:
    """Block until the connection ``name`` stands waiting on a row lock another holds."""
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while time.monotonic() < deadline:
        if name in pids and _is_waiting_on_a_lock(engine, pids[name]):
            return
        time.sleep(0.05)
    raise AssertionError(f"{name} never waited on the booking's lock")


# =====================================================================================
# Review follow-ups: what an edit may not do, the horizon, which period a notice names, which
# events are candidates, and the rule that only the part of a period still to come counts.
# =====================================================================================
def _stored_period(db: Session, period_id: uuid.UUID) -> VenueUnavailabilityPeriod:
    db.expire_all()
    return db.get(VenueUnavailabilityPeriod, period_id)


# --- AC6: what an edit may not do ---------------------------------------------------------
@pytest.mark.story("9.4", ac=6)
def test_an_ended_period_cannot_be_edited(db, venue_staff_client):
    """AC6: 409, as End now gives for a period already over, and the period is as it was."""
    venue = make_venue(db)
    period = _period(db, venue.id, _days_from_now(-3), _days_from_now(-1), notes="Painted")

    response = venue_staff_client.patch(
        _url(venue.id, period.id), json={"description": "Painted again"}
    )

    assert response.status_code == 409, response.text
    assert _stored_period(db, period.id).notes == "Painted"


@pytest.mark.story("9.4", ac=6)
def test_the_start_of_a_period_in_force_cannot_be_moved(db, venue_staff_client):
    """AC6: moving a started period's start later would make it removable, which a period in
    force is not (Remove would be sidestepped): 409, and the period is as it was."""
    venue = make_venue(db)
    period = _started(db, venue.id)
    start = period.starts_at

    response = venue_staff_client.patch(
        _url(venue.id, period.id), json={"starts_at": _days_from_now(0.5).isoformat()}
    )

    assert response.status_code == 409, response.text
    assert _stored_period(db, period.id).starts_at == start


@pytest.mark.story("9.4", ac=6)
def test_a_period_in_force_may_still_change_its_end_reason_and_description(db, venue_staff_client):
    """AC6. cannot fail first: it passes before the 409 above; it pins that only the start of a
    period in force is locked, and that sending the start it already has is not moving it."""
    venue = make_venue(db)
    period = _started(db, venue.id)

    response = venue_staff_client.patch(
        _url(venue.id, period.id),
        json={
            "starts_at": period.starts_at.isoformat(),
            "ends_at": _days_from_now(3).isoformat(),
            "reason": "RENOVATION",
            "description": "Longer than planned",
        },
    )

    assert response.status_code == 200, response.text


# --- AC1/AC5: validation -------------------------------------------------------------------
@pytest.mark.story("9.4", ac=6)
def test_end_now_null_is_refused(db, venue_staff_client):
    """AC6: ``{"end_now": null}`` is 422, not an edit that changes nothing."""
    venue = make_venue(db)
    period = _started(db, venue.id)
    ends_before = period.ends_at

    response = venue_staff_client.patch(_url(venue.id, period.id), json={"end_now": None})

    assert response.status_code == 422, response.text
    assert _stored_period(db, period.id).ends_at == ends_before


# A fixed now and the latest end worked out by hand: two calendar years on, on Singapore's clock
# (from 29 February, the next 1 March), plus the longest event, 14 days.
HORIZON_CASES = [
    (datetime(2026, 10, 16, 9, 0, tzinfo=SGT), datetime(2028, 10, 30, 9, 0, tzinfo=SGT)),
    (datetime(2028, 2, 29, 9, 0, tzinfo=SGT), datetime(2030, 3, 15, 9, 0, tzinfo=SGT)),
]


@pytest.mark.story("9.4", ac=5)
@pytest.mark.parametrize(("now", "limit"), HORIZON_CASES, ids=["ordinary-day", "leap-day"])
@pytest.mark.parametrize(
    ("offset", "is_allowed"),
    [(timedelta(0), True), (timedelta(minutes=1), False)],
    ids=["exactly-the-limit", "a-minute-past"],
)
def test_a_period_may_end_at_most_two_years_and_a_longest_event_ahead(
    db, now, limit, offset, is_allowed
):
    """AC5: the end is at most two years (from 29 February, the next 1 March) and 14 days from
    now - the latest an event a venue could be booked for can end. Exactly the limit is
    allowed; a minute past it is refused. The limit is worked out above, not by the code under
    test, and ``now`` is given so no clock is involved."""
    venue = make_venue(db)
    data = VenueUnavailabilityCreate(
        starts_at=now + timedelta(days=1),
        ends_at=limit + offset,
        reason="MAINTENANCE",
        description="Servicing",
    )

    if is_allowed:
        period = venue_service.add_unavailability(db, venue.id, data, actor=_staff(db), now=now)
        assert period.ends_at == limit
    else:
        with pytest.raises(venue_service.InvalidDateRange):
            venue_service.add_unavailability(db, venue.id, data, actor=_staff(db), now=now)
        assert _periods(db, venue.id) == []


@pytest.mark.story("9.4", ac=5)
def test_a_period_ending_in_the_year_9999_is_refused_on_add_and_on_edit(db, venue_staff_client):
    """AC5: 422 each way, and nothing is saved or changed."""
    venue = make_venue(db)
    period = _period(db, venue.id, _days_from_now(10), _days_from_now(12))
    ends_before = period.ends_at
    far = datetime(9999, 12, 31, 12, tzinfo=UTC)

    added = venue_staff_client.post(_url(venue.id), json=_body(_days_from_now(1), far))
    edited = venue_staff_client.patch(_url(venue.id, period.id), json={"ends_at": far.isoformat()})

    assert (added.status_code, edited.status_code) == (422, 422), (added.text, edited.text)
    assert len(_periods(db, venue.id)) == 1
    assert _stored_period(db, period.id).ends_at == ends_before


# --- AC3/AC4: which period a notice names; ending and removing settle too ---------------------


# --- AC4: who sees the description -------------------------------------------------------------


# --- AC8: which events are candidates ----------------------------------------------------------


# --- the preview, scoped and half-open ------------------------------------------------------
@pytest.mark.story("9.4", ac=2)
def test_the_preview_leaves_out_a_booking_that_only_touches_the_end_of_the_period(
    db, venue_staff_client
):
    """AC2. cannot fail first: the overlap is half-open already; this is the end's side of the
    pair, the start's side being in the held-period case. The booking is held from exactly the
    period's end."""
    venue = make_venue(db)
    touching = _booking(db, venue.id, _day(7, 10), _day(7, 12), status="PENDING")
    inside = _booking(db, venue.id, _day(6, 10), _day(6, 12), status="PENDING")

    response = _preview(venue_staff_client, venue.id, _day(2, 10), _day(7, 10))

    assert _ids(response) == {str(inside.id)}
    assert str(touching.id) not in _ids(response)


# --- AC7: the refusal counts setup and teardown ----------------------------------------------
@pytest.mark.story("9.4", ac=7)
@pytest.mark.parametrize(
    ("period", "expected_status"),
    [
        # booking 10:00-12:00 with 60 minutes' setup and 30 minutes' teardown: held 09:00-12:30
        (((9, 15), (9, 45)), 409),  # only the setup
        (((12, 15), (13, 0)), 409),  # only the teardown
        (((8, 0), (9, 0)), 200),  # touches held_from
        (((12, 30), (14, 0)), 200),  # touches held_until
    ],
)
def test_the_approval_refusal_is_measured_against_the_held_period(
    db, login_as, period, expected_status
):
    """AC7: the guard reads the held period, setup and teardown included, half-open at both
    edges, as the preview and the save do. The period is written straight to the table, so it is
    the guard that decides."""
    venue = make_venue(db)
    booking = _booking(
        db,
        venue.id,
        _day(3, 10),
        _day(3, 12),
        status="PENDING",
        setup_minutes=60,
        teardown_minutes=30,
    )
    (start_h, start_m), (end_h, end_m) = period
    _period(
        db,
        venue.id,
        _day(3, start_h) + timedelta(minutes=start_m),
        _day(3, end_h) + timedelta(minutes=end_m),
    )

    response = _approve(login_as(Users.VENUE_STAFF), booking.id)

    assert response.status_code == expected_status, response.text


# --- AC8/AC6: only the part of a period still to come counts -----------------------------------
def _in_progress(db: Session, venue_id: uuid.UUID) -> VenueBooking:
    """A pending booking that began an hour ago and ends in two."""
    now = datetime.now(UTC)
    return _booking(
        db, venue_id, now - timedelta(hours=1), now + timedelta(hours=2), status="PENDING"
    )


@pytest.mark.story("9.4", ac=8)
def test_a_period_wholly_in_the_past_flags_nothing_and_the_preview_lists_nothing(
    db, venue_staff_client
):
    """AC8 (PO decision): only the time still to come counts. A period that began three days ago
    and ended yesterday overlapped part of a booking that is in progress, but that part is
    already over, so the booking is neither listed nor ended."""
    venue = make_venue(db)
    booking = _booking(
        db,
        venue.id,
        _days_from_now(-2),
        _days_from_now(2),
        status="PENDING",
    )

    preview = _preview(venue_staff_client, venue.id, _days_from_now(-3), _days_from_now(-1))
    _add(venue_staff_client, venue.id, _days_from_now(-3), _days_from_now(-1))

    assert _ids(preview) == set()
    assert _stored(db, booking.id).status == "PENDING"


@pytest.mark.story("9.4", ac=8)
def test_the_preview_lists_a_booking_in_progress_under_a_period_in_force(db, venue_staff_client):
    """AC8. cannot fail first: the period covers the booking's remaining time, so it counts;
    paired with the wholly-past case above. That the save then ends it is 9.5's."""
    venue = make_venue(db)
    booking = _in_progress(db, venue.id)

    preview = _preview(venue_staff_client, venue.id, _days_from_now(-1), _days_from_now(1))

    assert _ids(preview) == {str(booking.id)}


# --- housekeeping: the write endpoints and the preview release lapsed holds -----------------


# --- the notice does not say who saved ---------------------------------------------------------


# --- AC6: ending a period that ends exactly now -------------------------------------------------
@pytest.mark.story("9.4", ac=6)
def test_a_period_ending_exactly_now_cannot_be_edited(db):
    """AC6: ``ends_at == now`` is ended, so an edit is refused as End now would refuse it, and
    the period is left as it was. Called with a ``now`` of its own."""
    venue = make_venue(db)
    now = datetime.now(UTC).replace(microsecond=0)
    period = _period(db, venue.id, now - timedelta(days=1), now, notes="Painted")

    with pytest.raises(venue_service.PeriodAlreadyEnded):
        venue_service.edit_unavailability(
            db,
            venue.id,
            period.id,
            VenueUnavailabilityUpdate(description="Painted again"),
            actor=_staff(db),
            now=now,
        )

    assert _stored_period(db, period.id).notes == "Painted"


# --- housekeeping: an edit and a removal release lapsed holds too ---------------------------------


# --- AC6: two writers to one period, in a forced order --------------------------------------------
def _committed_period(engine, starts_at: datetime, ends_at: datetime):
    with Session(engine) as session:
        venue = make_venue(session)
        period = make_unavailability(
            session, venue_id=venue.id, starts_at=starts_at, ends_at=ends_at, notes="Servicing"
        )
        session.commit()
        return venue.id, period.id


def _remove_period_rows(engine, venue_id: uuid.UUID) -> None:
    with Session(engine) as session:
        session.execute(
            delete(AuditLog).where(AuditLog.details["venue_id"].astext == str(venue_id))
        )
        session.execute(delete(Venue).where(Venue.id == venue_id))
        session.commit()


def _race_on_a_period(engine, monkeypatch, *, action, first, second):
    """Run ``first`` and ``second`` on one period, the first holding its row lock (the period is
    written, the transaction not yet committed) until the second is waiting on a lock: the pause is
    the period's own audit entry, ``action``, so no other audit row triggers it. ``first``
    and ``second`` are called with a session of their own; ``second`` starts once the first holds.
    Returns what each returned or raised."""
    pids: dict[str, int] = {}
    holding = threading.Event()
    original = venue_service.record_audit

    def paused(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("action") == action and not holding.is_set():
            holding.set()
            _wait_until(engine, pids, "second")
        return result

    monkeypatch.setattr(venue_service, "record_audit", paused)

    def run_first():
        with Session(engine) as session:
            pids["first"] = _backend_pid(session)
            return first(session)

    def run_second():
        with Session(engine) as session:
            pids["second"] = _backend_pid(session)
            assert holding.wait(LOCK_WAIT_SECONDS)
            try:
                return second(session)
            except Exception as refusal:  # the refusal is what is asserted
                return refusal

    with ThreadPoolExecutor(max_workers=2) as pool:
        running_first = pool.submit(run_first)
        running_second = pool.submit(run_second)
        running_first.result(timeout=40)
        return running_second.result(timeout=40)


@pytest.mark.story("9.4", ac=6)
def test_an_edit_that_waited_for_end_now_finds_the_period_ended(engine, monkeypatch):
    """AC6: End now holds the period's row; an edit that began meanwhile waits for it and, once
    End now commits, sees an ended period and is refused. Without the row lock the edit read the
    period before End now committed, passed its checks and revived the period."""
    venue_id, period_id = _committed_period(engine, _days_from_now(-1), _days_from_now(2))
    new_end = _days_from_now(6)
    try:
        refusal = _race_on_a_period(
            engine,
            monkeypatch,
            action=venue_service.UNAVAILABILITY_ENDED,
            first=lambda session: venue_service.end_unavailability(
                session,
                venue_id,
                period_id,
                actor=session.get(User, STAFF_ID),
                now=datetime.now(UTC),
            ),
            second=lambda session: venue_service.edit_unavailability(
                session,
                venue_id,
                period_id,
                VenueUnavailabilityUpdate(ends_at=new_end),
                actor=session.get(User, STAFF_ID),
                now=datetime.now(UTC),
            ),
        )

        assert isinstance(refusal, venue_service.PeriodAlreadyEnded), refusal
        with Session(engine) as session:
            assert session.get(VenueUnavailabilityPeriod, period_id).ends_at < new_end
    finally:
        _remove_period_rows(engine, venue_id)


@pytest.mark.story("9.4", ac=6)
def test_an_edit_that_waited_for_a_removal_finds_the_period_gone(engine, monkeypatch):
    """AC6: a removal holds the period's row (its delete is written, not committed); an edit that
    began meanwhile waits and, once the removal commits, finds no period: 404, not the 500 of an
    UPDATE that matched no row."""
    venue_id, period_id = _committed_period(engine, _days_from_now(3), _days_from_now(5))
    try:
        refusal = _race_on_a_period(
            engine,
            monkeypatch,
            action=venue_service.UNAVAILABILITY_REMOVED,
            first=lambda session: venue_service.remove_unavailability(
                session,
                venue_id,
                period_id,
                actor=session.get(User, STAFF_ID),
                now=datetime.now(UTC),
            ),
            second=lambda session: venue_service.edit_unavailability(
                session,
                venue_id,
                period_id,
                VenueUnavailabilityUpdate(description="Repainting"),
                actor=session.get(User, STAFF_ID),
                now=datetime.now(UTC),
            ),
        )

        assert isinstance(refusal, venue_service.UnavailabilityNotFound), refusal
    finally:
        _remove_period_rows(engine, venue_id)


@pytest.mark.story("9.4", ac=6)
def test_a_removal_that_waited_for_an_edit_sees_what_the_edit_made(engine, monkeypatch):
    """AC6: an edit holds the period's row and moves its start into the past; a removal that
    began meanwhile waits, then sees a period in force and is refused - not removed on the strength
    of the start it read before the edit committed."""
    venue_id, period_id = _committed_period(engine, _days_from_now(3), _days_from_now(5))
    try:
        refusal = _race_on_a_period(
            engine,
            monkeypatch,
            action=venue_service.UNAVAILABILITY_UPDATED,
            first=lambda session: venue_service.edit_unavailability(
                session,
                venue_id,
                period_id,
                VenueUnavailabilityUpdate(starts_at=_days_from_now(-1)),
                actor=session.get(User, STAFF_ID),
                now=datetime.now(UTC),
            ),
            second=lambda session: venue_service.remove_unavailability(
                session,
                venue_id,
                period_id,
                actor=session.get(User, STAFF_ID),
                now=datetime.now(UTC),
            ),
        )

        assert isinstance(refusal, venue_service.PeriodStarted), refusal
        with Session(engine) as session:
            assert session.get(VenueUnavailabilityPeriod, period_id) is not None
    finally:
        _remove_period_rows(engine, venue_id)


# --- AC10: the save first, then the confirmation, then the save settles ---------------------------
