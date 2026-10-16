"""Story 9.4: mark a venue temporarily unavailable.

The reasons a period can carry (migration 022).
Add, edit, end and remove a period, the preview of what it would affect, and who may.
The bookings a period affects are marked, and the mark follows it (migration 023).
The event goes back to Planning and its coordinator and organiser are told.
A pending request that overlaps a period cannot be approved while it stands.

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
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings import service as booking_service
from app.bookings.models import VenueBooking
from app.common.audit import AuditLog
from app.events import service as events_service
from app.events.models import Event, EventStatus, EventStatusHistory
from app.notifications.models import Notification
from app.notifications.service import NotificationType
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
REASON_NAMES = {
    "MAINTENANCE": "Maintenance",
    "EQUIPMENT_FAILURE": "Equipment failure",
    "RENOVATION": "Renovation",
    "SAFETY": "Safety concern",
}


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
    assert _audit(db, MARKED, booking.id) == []
    db.expire_all()
    assert db.get(VenueBooking, booking.id).status == "PENDING"


@pytest.mark.story("9.4", ac=2)
def test_a_period_may_be_saved_with_bookings_in_the_way(db, venue_staff_client):
    """AC2: "saving is allowed even when there are some". The period is saved and the booking
    is not cancelled or moved; its mark is AC3's and is asserted there."""
    venue = make_venue(db)
    day = _days_from_now(20).replace(hour=9, minute=0, second=0)
    booking = _booking(db, venue.id, day, day + timedelta(hours=2), status="APPROVED")

    response = venue_staff_client.post(
        _url(venue.id), json=_body(day - timedelta(hours=1), day + timedelta(hours=3))
    )

    assert response.status_code == 201, response.text
    assert len(_periods(db, venue.id)) == 1
    db.expire_all()
    assert db.get(VenueBooking, booking.id).status == "APPROVED"


# --- AC9: who may do what --------------------------------------------------------------------
WRITES = ["post", "patch", "delete"]


def _write(client, method: str, venue_id: uuid.UUID, period_id: uuid.UUID):
    if method == "post":
        return client.post(_url(venue_id), json=_future_body())
    if method == "patch":
        return client.patch(_url(venue_id, period_id), json={"description": "x"})
    return client.delete(_url(venue_id, period_id))


@pytest.mark.story("9.4", ac=9)
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
# Marking (migration 023): the bookings a period affects, and clearing the mark.
#
#   venue_bookings.venue_unavailable_marked_at   timestamptz, nullable
#   venue_service.recheck_venue_bookings(db, venue_id, *, now, actor) -> RecheckResult
#
# The mark is set while a PENDING or APPROVED booking's held period overlaps a period of its
# venue, and cleared when none does. The re-check runs after every add, edit, end and removal.
# A booking that is no longer pending or approved keeps whatever value it had: history, which
# readers ignore. The event's status and the notifications are asserted in the AC3 and AC4
# sections below, not here.
# =====================================================================================
MARKED = "BOOKING_VENUE_UNAVAILABLE_MARKED"
CLEARED = "BOOKING_VENUE_UNAVAILABLE_CLEARED"
MARK_FIELD = "venue_unavailable_marked_at"


def _day(days: float, hour: int = 10) -> datetime:
    """``hour`` o'clock UTC, that many days from now: a start well clear of the clock."""
    return (datetime.now(UTC) + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )


def _mark_in_sql(db: Session, booking_id: uuid.UUID, at: datetime) -> None:
    """A mark written in SQL, so it is stored exactly as given whatever the models say."""
    db.execute(
        text("UPDATE venue_bookings SET venue_unavailable_marked_at = :at WHERE id = :id"),
        {"at": at, "id": booking_id},
    )


def _marked_at(db: Session, booking_id: uuid.UUID) -> datetime | None:
    db.expire_all()
    return db.get(VenueBooking, booking_id).venue_unavailable_marked_at


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


# --- AC3: the mark ---------------------------------------------------------------------------
@pytest.mark.story("9.4", ac=3)
def test_saving_a_period_marks_each_booking_it_overlaps(db, venue_staff_client):
    """AC3: pending and approved alike. Status, venue and period are untouched, and the
    event is not cancelled."""
    venue = make_venue(db)
    pending = _live(db, venue.id, _day(3))
    approved = _booking(db, venue.id, _day(5), _day(5) + timedelta(hours=2), status="APPROVED")
    before = {
        booking.id: (booking.status, booking.venue_id, booking.starts_at, booking.ends_at)
        for booking in (pending, approved)
    }

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    for booking in (pending, approved):
        assert _marked_at(db, booking.id) is not None
        stored = db.get(VenueBooking, booking.id)
        assert (stored.status, stored.venue_id, stored.starts_at, stored.ends_at) == before[
            booking.id
        ]
        assert db.get(Event, stored.event_id).status == EventStatus.PLANNING


@pytest.mark.story("9.4", ac=3)
def test_two_bookings_of_one_event_are_both_marked(db, venue_staff_client):
    """AC3: the event has two bookings on the venue; both carry the mark."""
    venue = make_venue(db)
    event = make_event(
        db, status=EventStatus.PLANNING, assigned_coordinator_id=Users.COORDINATOR.id
    )
    first = make_booking(
        db, venue_id=venue.id, starts_at=_day(3), ends_at=_day(3, 12), event_id=event.id
    )
    second = make_booking(
        db, venue_id=venue.id, starts_at=_day(4), ends_at=_day(4, 12), event_id=event.id
    )

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _marked_at(db, first.id) is not None
    assert _marked_at(db, second.id) is not None


@pytest.mark.story("9.4", ac=3)
def test_a_booking_outside_the_period_is_not_marked(db, venue_staff_client):
    """AC3. cannot fail first: it passes on an implementation that marks nothing; it is
    paired with the marking case above, which carries the red. Another event's booking on the
    same venue, and the same venue's booking on another venue, are left alone."""
    venue, elsewhere = make_venue(db), make_venue(db)
    inside = _live(db, venue.id, _day(3))
    outside = _live(db, venue.id, _day(20))
    other_venue = _live(db, elsewhere.id, _day(3))

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _marked_at(db, inside.id) is not None
    assert _marked_at(db, outside.id) is None
    assert _marked_at(db, other_venue.id) is None


@pytest.mark.story("9.4", ac=3)
def test_the_mark_is_the_time_of_the_save_and_a_second_period_does_not_move_it(
    db, venue_staff_client
):
    """AC3: the timestamp lies between a moment before the save and one after; a second
    period overlapping the same booking leaves it where it was."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3))

    before = datetime.now(UTC)
    _add(venue_staff_client, venue.id, _day(2), _day(7))
    after = datetime.now(UTC)
    marked = _marked_at(db, booking.id)
    _add(venue_staff_client, venue.id, _day(1), _day(9))

    assert before <= marked <= after
    assert _marked_at(db, booking.id) == marked


@pytest.mark.story("9.4", ac=3)
@pytest.mark.parametrize("status", ["REJECTED", "WITHDRAWN", "CANCELLED", "EXPIRED"])
def test_a_leftover_mark_on_a_closed_booking_is_history_readers_ignore(db, login_as, status):
    """AC3: no mark in ``BookingOut``, ``BookingOutcome`` or the queue entry, and the
    re-check neither clears nor re-marks the value."""
    venue = make_venue(db)
    extra = {"hold_expires_at": _day(1)} if status == "EXPIRED" else {}
    booking = _booking(db, venue.id, _day(3), _day(3, 12), status=status, **extra)
    left = _day(-1)
    _mark_in_sql(db, booking.id, left)
    # a live twin, so the same saves mark one booking and the reads can tell them apart
    twin = _live(db, venue.id, _day(3, 15))
    staff = login_as(Users.VENUE_STAFF)
    _add(staff, venue.id, _day(2), _day(7))

    detail = staff.get(f"/bookings/{booking.id}").json()
    outcomes = staff.get(f"/bookings/for-event/{booking.event_id}").json()
    queue = staff.get("/bookings", params={"status": status}).json()["items"]

    assert detail[MARK_FIELD] is None
    assert [outcome[MARK_FIELD] for outcome in outcomes] == [None]
    assert [entry[MARK_FIELD] for entry in queue if entry["id"] == str(booking.id)] == [None]
    assert _marked_at(db, booking.id) == left
    assert _marked_at(db, twin.id) is not None


@pytest.mark.story("9.4", ac=3)
def test_a_booking_carries_its_mark_in_the_booking_record(db, login_as):
    """AC3: ``BookingOut`` has the field for a live booking - the timestamp when marked,
    null (present, not absent) when not."""
    venue = make_venue(db)
    marked = _live(db, venue.id, _day(3))
    clear = _live(db, venue.id, _day(20))
    staff = login_as(Users.VENUE_STAFF)
    _add(staff, venue.id, _day(2), _day(7))

    marked_body = staff.get(f"/bookings/{marked.id}").json()
    clear_body = staff.get(f"/bookings/{clear.id}").json()

    assert datetime.fromisoformat(marked_body[MARK_FIELD].replace("Z", "+00:00"))
    assert clear_body[MARK_FIELD] is None


@pytest.mark.story("9.4", ac=3)
def test_the_queue_entry_carries_the_mark_and_the_queue_still_counts(db, login_as):
    """AC3: ``BookingQueueEntry`` has the field; the tab's total and the counts are what
    they were without it."""
    venue = make_venue(db)
    marked = _live(db, venue.id, _day(3))
    clear = _live(db, venue.id, _day(20))
    staff = login_as(Users.VENUE_STAFF)
    _add(staff, venue.id, _day(2), _day(7))

    page = staff.get("/bookings", params={"status": "PENDING"}).json()

    entries = {entry["id"]: entry for entry in page["items"]}
    assert entries[str(marked.id)][MARK_FIELD] is not None
    assert entries[str(clear.id)][MARK_FIELD] is None
    assert page["total"] == len(page["items"]) <= page["counts"]["pending"]


@pytest.mark.story("9.4", ac=3)
def test_the_event_page_outcome_carries_the_mark(db, login_as):
    """AC3: ``BookingOutcome`` has the field, for the coordinator's event page."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3))
    _add(login_as(Users.VENUE_STAFF), venue.id, _day(2), _day(7))

    outcomes = login_as(Users.COORDINATOR).get(f"/bookings/for-event/{booking.event_id}").json()

    (outcome,) = outcomes
    assert outcome[MARK_FIELD] is not None


@pytest.mark.story("9.4", ac=3)
def test_the_mark_is_a_nullable_timestamp_column(db):
    """AC3: migration 023's column, as the ORM and the dictionary describe it."""
    row = db.execute(
        text(
            "SELECT data_type, is_nullable FROM information_schema.columns"
            " WHERE table_name = 'venue_bookings' AND column_name = :name"
        ),
        {"name": MARK_FIELD},
    ).one_or_none()

    assert row is not None, "venue_bookings has no venue_unavailable_marked_at column"
    assert tuple(row) == ("timestamp with time zone", "YES")


@pytest.mark.story("9.4", ac=3)
def test_marking_and_clearing_each_leave_an_audit_row(db, venue_staff_client):
    """AC3: one row per booking marked, one per booking cleared, naming the actor, the
    venue and the event."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3))
    period = _add(venue_staff_client, venue.id, _day(2), _day(7))

    (marked,) = _audit(db, MARKED, booking.id)
    venue_staff_client.delete(_url(venue.id, uuid.UUID(period["id"])))
    (cleared,) = _audit(db, CLEARED, booking.id)

    for entry in (marked, cleared):
        assert entry.actor_id == Users.VENUE_STAFF.id
        assert entry.entity_type == "venue_booking"
        assert entry.details["venue_id"] == str(venue.id)
        assert entry.details["event_id"] == str(booking.event_id)


@pytest.mark.story("9.4", ac=3)
def test_the_recheck_says_what_it_marked_and_what_it_cleared(db):
    """AC3: the re-check's contract - a typed result with the bookings newly marked and
    the ones cleared; a second run on the same state changes nothing. Called with a ``now`` of
    its own, as 12.7's hold functions are."""
    venue = make_venue(db)
    now = datetime.now(UTC)
    _period(db, venue.id, _day(2), _day(7))
    overlapped = _live(db, venue.id, _day(3))
    stale = _live(db, venue.id, _day(20))
    _mark_in_sql(db, stale.id, now - timedelta(days=1))
    staff = _staff(db)

    first = venue_service.recheck_venue_bookings(db, venue.id, now=now, actor=staff)
    second = venue_service.recheck_venue_bookings(db, venue.id, now=now, actor=staff)

    assert [booking.id for booking in first.newly_marked] == [overlapped.id]
    assert [booking.id for booking in first.cleared] == [stale.id]
    assert (second.newly_marked, second.cleared) == ([], [])
    assert _marked_at(db, overlapped.id) == now
    assert _marked_at(db, stale.id) is None


# --- AC5: touching and overlapping, against the held period ----------------------------------
@pytest.mark.story("9.4", ac=5)
def test_overlapping_a_held_period_by_one_minute_marks_the_booking(db, venue_staff_client):
    """AC5: the least overlap there is."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3, 10))

    _add(venue_staff_client, venue.id, _day(3, 8), _day(3, 10) + timedelta(minutes=1))

    assert _marked_at(db, booking.id) is not None


@pytest.mark.story("9.4", ac=5)
def test_a_period_that_only_touches_the_booking_does_not_mark_it(db, venue_staff_client):
    """AC5. cannot fail first: it passes on an implementation that marks nothing;
    paired with the one-minute case above. A period ending exactly where the booking's held
    period starts, and one starting exactly where it ends, leave it unmarked."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3, 10))

    _add(venue_staff_client, venue.id, _day(3, 6), _day(3, 10))
    _add(venue_staff_client, venue.id, _day(3, 12), _day(3, 18))

    assert _marked_at(db, booking.id) is None


@pytest.mark.story("9.4", ac=5)
@pytest.mark.parametrize(
    ("period", "expected_marked"),
    [
        # booking 10:00-12:00 with 60 minutes' setup and 30 minutes' teardown: held 09:00-12:30
        (((9, 15), (9, 45)), True),  # only the setup
        (((12, 15), (13, 0)), True),  # only the teardown
        (((8, 0), (9, 0)), False),  # touches held_from
        (((12, 30), (14, 0)), False),  # touches held_until
    ],
)
def test_the_overlap_is_measured_against_the_held_period(
    db, venue_staff_client, period, expected_marked
):
    """AC5: setup and teardown count, and the held period's own edges are half-open."""
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

    _add(
        venue_staff_client,
        venue.id,
        _day(3, start_h) + timedelta(minutes=start_m),
        _day(3, end_h) + timedelta(minutes=end_m),
    )

    assert (_marked_at(db, booking.id) is not None) is expected_marked


# --- AC6: end, remove, shorten, extend: the marks follow -------------------------------------
@pytest.mark.story("9.4", ac=6)
def test_ending_a_period_clears_the_marks_of_bookings_no_longer_overlapped(db, venue_staff_client):
    """AC6: the period began yesterday and runs ten days; ending it now frees a booking
    three days away."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3))
    period = _add(venue_staff_client, venue.id, _day(-1), _day(10))
    assert _marked_at(db, booking.id) is not None

    ended = venue_staff_client.patch(
        _url(venue.id, uuid.UUID(period["id"])), json={"end_now": True}
    )

    assert ended.status_code == 200, ended.text
    assert _marked_at(db, booking.id) is None


@pytest.mark.story("9.4", ac=6)
def test_removing_a_period_clears_its_marks(db, venue_staff_client):
    """AC6."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3))
    period = _add(venue_staff_client, venue.id, _day(2), _day(7))
    assert _marked_at(db, booking.id) is not None

    removed = venue_staff_client.delete(_url(venue.id, uuid.UUID(period["id"])))

    assert removed.status_code == 204, removed.text
    assert _marked_at(db, booking.id) is None


@pytest.mark.story("9.4", ac=6)
def test_shortening_clears_only_the_bookings_that_drop_out(db, venue_staff_client):
    """AC6: the one still inside keeps its mark and its timestamp."""
    venue = make_venue(db)
    kept = _live(db, venue.id, _day(3))
    dropped = _live(db, venue.id, _day(8))
    period = _add(venue_staff_client, venue.id, _day(2), _day(10))
    kept_since = _marked_at(db, kept.id)
    assert kept_since is not None and _marked_at(db, dropped.id) is not None

    shortened = venue_staff_client.patch(
        _url(venue.id, uuid.UUID(period["id"])), json={"ends_at": _day(5).isoformat()}
    )

    assert shortened.status_code == 200, shortened.text
    assert _marked_at(db, kept.id) == kept_since
    assert _marked_at(db, dropped.id) is None


@pytest.mark.story("9.4", ac=6)
def test_extending_marks_the_bookings_it_newly_reaches(db, venue_staff_client):
    """AC6: the booking already marked keeps its timestamp; the one reached is marked."""
    venue = make_venue(db)
    inside = _live(db, venue.id, _day(3))
    beyond = _live(db, venue.id, _day(8))
    period = _add(venue_staff_client, venue.id, _day(2), _day(5))
    inside_since = _marked_at(db, inside.id)
    assert inside_since is not None and _marked_at(db, beyond.id) is None

    extended = venue_staff_client.patch(
        _url(venue.id, uuid.UUID(period["id"])), json={"ends_at": _day(10).isoformat()}
    )

    assert extended.status_code == 200, extended.text
    assert _marked_at(db, inside.id) == inside_since
    assert _marked_at(db, beyond.id) is not None


@pytest.mark.story("9.4", ac=6)
def test_a_booking_another_period_still_overlaps_keeps_its_mark(db, venue_staff_client):
    """AC6: periods may overlap, so removing one frees nothing the other still holds,
    and the timestamp does not change."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3))
    first = _add(venue_staff_client, venue.id, _day(2), _day(7))
    marked = _marked_at(db, booking.id)
    _add(venue_staff_client, venue.id, _day(1), _day(9))

    removed = venue_staff_client.delete(_url(venue.id, uuid.UUID(first["id"])))

    assert removed.status_code == 204, removed.text
    assert _marked_at(db, booking.id) == marked


@pytest.mark.story("9.4", ac=6)
def test_one_edit_can_clear_one_booking_and_mark_another(db, venue_staff_client):
    """AC6: moving a period off one booking and onto another."""
    venue = make_venue(db)
    freed = _live(db, venue.id, _day(3))
    reached = _live(db, venue.id, _day(8))
    period = _add(venue_staff_client, venue.id, _day(2), _day(5))
    assert _marked_at(db, freed.id) is not None

    moved = venue_staff_client.patch(
        _url(venue.id, uuid.UUID(period["id"])),
        json={"starts_at": _day(6).isoformat(), "ends_at": _day(10).isoformat()},
    )

    assert moved.status_code == 200, moved.text
    assert _marked_at(db, freed.id) is None
    assert _marked_at(db, reached.id) is not None


# --- AC8: which bookings are candidates ------------------------------------------------------
@pytest.mark.story("9.4", ac=8)
def test_a_booking_in_progress_is_marked(db, venue_staff_client):
    """AC8: its held period began an hour ago and ends in two, and it is still to come."""
    venue = make_venue(db)
    now = datetime.now(UTC)
    booking = _booking(
        db,
        venue.id,
        now - timedelta(hours=1),
        now + timedelta(hours=2),
        status="APPROVED",
        event_status=EventStatus.CONFIRMED,
    )

    _add(venue_staff_client, venue.id, _day(-1), _day(1))

    assert _marked_at(db, booking.id) is not None


@pytest.mark.story("9.4", ac=8)
def test_a_completed_events_booking_is_not_marked(db, venue_staff_client):
    """AC8. cannot fail first: it passes on an implementation that marks nothing; paired
    with the in-progress case above, whose period covers both."""
    venue = make_venue(db)
    now = datetime.now(UTC)
    completed = _booking(
        db,
        venue.id,
        now - timedelta(hours=1),
        now + timedelta(hours=2),
        status="APPROVED",
        event_status=EventStatus.COMPLETED,
    )

    _add(venue_staff_client, venue.id, _day(-1), _day(1))

    assert _marked_at(db, completed.id) is None


@pytest.mark.story("9.4", ac=8)
def test_a_booking_whose_held_period_is_over_is_not_marked(db, venue_staff_client):
    """AC8. cannot fail first, as above: a period saved over days already gone
    marks nothing, though the booking was inside it."""
    venue = make_venue(db)
    gone = _booking(db, venue.id, _day(-6), _day(-6, 12), status="APPROVED")

    _add(venue_staff_client, venue.id, _day(-8), _day(-4))

    assert _marked_at(db, gone.id) is None


@pytest.mark.story("9.4", ac=8)
def test_a_stale_mark_on_a_booking_that_is_over_is_left_alone(db, venue_staff_client):
    """AC8. cannot fail first: it passes on an implementation that clears nothing; it
    is paired with the clearing cases in AC6. A re-check leaves the value on a booking whose held
    period has ended, as history."""
    venue = make_venue(db)
    gone = _booking(db, venue.id, _day(-6), _day(-6, 12), status="APPROVED")
    left = _day(-7)
    _mark_in_sql(db, gone.id, left)

    _add(venue_staff_client, venue.id, _day(20), _day(22))

    assert _marked_at(db, gone.id) == left


# --- 12.7 alongside the mark -----------------------------------------------------------------
@pytest.mark.story("9.4", ac=3)
def test_a_marked_hold_that_expires_keeps_its_timestamp_but_shows_no_mark(db, login_as):
    """AC3: the sweep still expires it; the value stays on the row as history and
    the booking record no longer reports it."""
    venue = make_venue(db)
    expiry = _day(1)
    booking = _booking(
        db, venue.id, _day(3), _day(3, 12), status="APPROVED", hold_expires_at=expiry
    )
    staff = login_as(Users.VENUE_STAFF)
    _add(staff, venue.id, _day(2), _day(7))
    marked = _marked_at(db, booking.id)
    assert marked is not None

    booking_service.expire_lapsed_holds(db, now=expiry + timedelta(minutes=1))

    db.expire_all()
    assert db.get(VenueBooking, booking.id).status == "EXPIRED"
    assert _marked_at(db, booking.id) == marked
    assert staff.get(f"/bookings/{booking.id}").json()[MARK_FIELD] is None


@pytest.mark.story("9.4", ac=3)
def test_a_marked_hold_is_still_warned_before_it_expires(db):
    """AC3. cannot fail first, for its behaviour: 12.7's reminder already runs for
    every open hold, so it is red only for the column the mark is written to."""
    venue = make_venue(db)
    expiry = _day(2)
    booking = _booking(
        db, venue.id, _day(3), _day(3, 12), status="APPROVED", hold_expires_at=expiry
    )
    _mark_in_sql(db, booking.id, datetime.now(UTC))

    booking_service.remind_expiring_holds(db, now=expiry - timedelta(hours=1))

    warned = db.scalars(
        select(Notification).where(
            Notification.notification_type == "BOOKING_HOLD_EXPIRING",
            Notification.related_entity_id == booking.id,
        )
    ).all()
    assert len(warned) == 1


# --- AC2: the preview knows which bookings are already marked ----------------------
@pytest.mark.story("9.4", ac=2)
def test_the_preview_says_which_bookings_are_already_marked(db, venue_staff_client):
    """AC2: ``already_marked`` per entry, so an edit's preview can tell the bookings a
    venue's marks already cover from the ones the new window would newly reach."""
    venue = make_venue(db)
    marked = _live(db, venue.id, _day(3))
    fresh = _live(db, venue.id, _day(6))
    _add(venue_staff_client, venue.id, _day(2), _day(5))

    response = _preview(venue_staff_client, venue.id, _day(2), _day(9))

    assert response.status_code == 200, response.text
    flags = {entry["booking_id"]: entry["already_marked"] for entry in response.json()}
    assert flags == {str(marked.id): True, str(fresh.id): False}


# =====================================================================================
# The event goes back to Planning, and its coordinator and organiser are told.
#
# For each event with a booking newly marked in a save (``RecheckResult.newly_marked``):
#   * CONFIRMED -> PLANNING, once, with an event_status_history row (its reason naming the
#     venue) and an audit entry EVENT_RETURNED_TO_PLANNING; PLANNING stays; nothing else moves.
#   * one BOOKING_VENUE_UNAVAILABLE notification each to the event's assigned coordinator (when
#     it has one) and its organiser, naming the venue, the period and the reason. The Venue Staff
#     member who saved is never told. Clearing a mark sends nothing and leaves the status alone.
# Awaiting Safety Check (story 21.1) goes back to Planning as a Confirmed event does.
# =====================================================================================
VENUE_UNAVAILABLE = "BOOKING_VENUE_UNAVAILABLE"
RETURNED_TO_PLANNING = "EVENT_RETURNED_TO_PLANNING"


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


def _recipients(notices: list[Notification]) -> list[uuid.UUID]:
    return sorted(notice.recipient_id for notice in notices)


def _status_of(db: Session, event_id: uuid.UUID) -> str:
    db.expire_all()
    return db.get(Event, event_id).status


def _history(db: Session, event_id: uuid.UUID) -> list[EventStatusHistory]:
    db.expire_all()
    return list(
        db.scalars(
            select(EventStatusHistory)
            .where(EventStatusHistory.event_id == event_id)
            .order_by(EventStatusHistory.changed_at, EventStatusHistory.id)
        )
    )


def _returned(db: Session, event_id: uuid.UUID) -> list[EventStatusHistory]:
    return [
        row
        for row in _history(db, event_id)
        if (row.from_status, row.to_status) == (EventStatus.CONFIRMED, EventStatus.PLANNING)
    ]


def _on_singapore_date(moment: datetime) -> str:
    """The date as a notice words it: ``4 Mar 2027``, in Singapore time."""
    local = moment.astimezone(SGT)
    return f"{local.day} {local:%b %Y}"


# --- AC3: the event's status -----------------------------------------------------------------
@pytest.mark.story("9.4", ac=3)
def test_a_planning_event_stays_in_planning(db, venue_staff_client):
    """AC3. cannot fail first: nothing changes an event's status today, so it passes before
    the change; it is paired with the Confirmed case below, which carries the red. No history
    row, no audit entry."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.PLANNING)
    _pending_of(db, event, venue.id, _day(3))
    history_before = len(_history(db, event.id))

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _status_of(db, event.id) == EventStatus.PLANNING
    assert len(_history(db, event.id)) == history_before
    assert _audit(db, RETURNED_TO_PLANNING, event.id) == []


@pytest.mark.story("9.4", ac=3)
def test_a_confirmed_event_goes_back_to_planning(db, venue_staff_client):
    """AC3: with a status-history row naming the venue, written by the Venue Staff member,
    and an audit entry that says where it came from. Its booking is still approved: the event is
    not cancelled and keeps its details."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.CONFIRMED, name="Nimbus Developer Conference")
    booking = _pending_of(db, event, venue.id, _day(3), status="APPROVED")

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _status_of(db, event.id) == EventStatus.PLANNING
    (row,) = _returned(db, event.id)
    assert row.changed_by_id == Users.VENUE_STAFF.id
    assert venue.name in row.reason
    (entry,) = _audit(db, RETURNED_TO_PLANNING, event.id)
    assert entry.actor_id == Users.VENUE_STAFF.id
    assert entry.details["from_status"] == EventStatus.CONFIRMED
    assert entry.details["venue_id"] == str(venue.id)
    db.expire_all()
    assert db.get(VenueBooking, booking.id).status == "APPROVED"
    assert db.get(Event, event.id).name == "Nimbus Developer Conference"


@pytest.mark.story("9.4", ac=3)
def test_an_event_awaiting_its_safety_check_goes_back_to_planning_and_its_people_are_told(
    db, venue_staff_client
):
    """AC3 (21.1): the same as for a Confirmed event - once, with a history row naming the
    venue and an EVENT_RETURNED_TO_PLANNING audit entry saying where it came from - and its
    coordinator and organiser are told exactly as for a Confirmed one."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.AWAITING_SAFETY_CHECK)
    _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    _pending_of(db, event, venue.id, _day(4), status="APPROVED")
    starts_at, ends_at = _day(2), _day(7)

    _add(venue_staff_client, venue.id, starts_at, ends_at, reason="SAFETY", description="Wiring")

    assert _status_of(db, event.id) == EventStatus.PLANNING
    returned = [
        row
        for row in _history(db, event.id)
        if (row.from_status, row.to_status)
        == (EventStatus.AWAITING_SAFETY_CHECK, EventStatus.PLANNING)
    ]
    (row,) = returned
    assert row.changed_by_id == Users.VENUE_STAFF.id
    assert venue.name in row.reason
    (entry,) = _audit(db, RETURNED_TO_PLANNING, event.id)
    assert entry.details["from_status"] == EventStatus.AWAITING_SAFETY_CHECK
    assert entry.details["venue_id"] == str(venue.id)
    notices = _told(db, event.id)
    assert _recipients(notices) == sorted([Users.COORDINATOR.id, Users.ORGANISER.id])
    for notice in notices:
        for text_wanted in (venue.name, "Safety concern"):
            assert text_wanted in notice.message
    # The description is the coordinator's to read; the organiser's notice leaves it out.
    by_recipient = {notice.recipient_id: notice.message for notice in notices}
    assert "Wiring" in by_recipient[Users.COORDINATOR.id]
    assert "Wiring" not in by_recipient[Users.ORGANISER.id]


@pytest.mark.story("9.4", ac=3)
def test_two_marked_bookings_of_one_event_move_it_once(db, venue_staff_client):
    """AC3: one status change, one history row, one audit entry."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.CONFIRMED)
    _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    _pending_of(db, event, venue.id, _day(4), status="APPROVED")

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _status_of(db, event.id) == EventStatus.PLANNING
    assert len(_returned(db, event.id)) == 1
    assert len(_audit(db, RETURNED_TO_PLANNING, event.id)) == 1


@pytest.mark.story("9.4", ac=3)
def test_an_event_whose_booking_is_not_reached_is_not_moved(db, venue_staff_client):
    """AC3's other half. cannot fail first: passes on a no-op; paired with the case above that
    returns a reached event to Planning."""
    venue = make_venue(db)
    reached = _event_for(db, EventStatus.CONFIRMED)
    untouched = _event_for(db, EventStatus.CONFIRMED)
    _pending_of(db, reached, venue.id, _day(3), status="APPROVED")
    _pending_of(db, untouched, venue.id, _day(20), status="APPROVED")

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _status_of(db, reached.id) == EventStatus.PLANNING
    assert _status_of(db, untouched.id) == EventStatus.CONFIRMED
    assert _told(db, untouched.id) == []


# --- AC4: the notifications ------------------------------------------------------------------
@pytest.mark.story("9.4", ac=4)
def test_the_coordinator_and_the_organiser_are_each_told_naming_venue_period_and_reason(
    db, venue_staff_client
):
    """AC4: the type is defined, one notice each, about the event, with the venue, the period
    and the reason - and the description when there is one."""
    venue = make_venue(db)
    event = _event_for(db)
    _pending_of(db, event, venue.id, _day(3))
    starts_at, ends_at = _day(2), _day(7)

    _add(
        venue_staff_client,
        venue.id,
        starts_at,
        ends_at,
        reason="RENOVATION",
        description="Floor relaid",
    )

    assert NotificationType.BOOKING_VENUE_UNAVAILABLE.value == VENUE_UNAVAILABLE
    notices = _told(db, event.id)
    assert _recipients(notices) == sorted([Users.COORDINATOR.id, Users.ORGANISER.id])
    for notice in notices:
        assert venue.name in notice.title
        for text_wanted in (
            venue.name,
            _on_singapore_date(starts_at),
            _on_singapore_date(ends_at),
            "Renovation",
        ):
            assert text_wanted in notice.message
        assert (notice.related_entity_type, notice.related_entity_id) == ("event", event.id)
    by_recipient = {notice.recipient_id: notice.message for notice in notices}
    assert "Floor relaid" in by_recipient[Users.COORDINATOR.id]
    assert "Floor relaid" not in by_recipient[Users.ORGANISER.id]


@pytest.mark.story("9.4", ac=4)
def test_two_newly_marked_bookings_of_one_event_tell_it_once(db, venue_staff_client):
    """AC4: one notice each to the coordinator and the organiser, not one per
    booking."""
    venue = make_venue(db)
    event = _event_for(db)
    _pending_of(db, event, venue.id, _day(3))
    _pending_of(db, event, venue.id, _day(4))

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert len(_told(db, event.id)) == 2


@pytest.mark.story("9.4", ac=4)
def test_an_event_with_no_coordinator_still_tells_its_organiser(db, venue_staff_client):
    """AC4: nobody is assigned yet, so the organiser alone is told, and nothing fails."""
    venue = make_venue(db)
    event = _event_for(db, assigned_coordinator_id=None)
    _pending_of(db, event, venue.id, _day(3))

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _recipients(_told(db, event.id)) == [Users.ORGANISER.id]


@pytest.mark.story("9.4", ac=4)
def test_after_a_reassignment_the_new_coordinator_is_told(db, venue_staff_client):
    """AC4 (20.1 AC4): whoever coordinates the event when the period is saved, not whoever
    did when the booking was requested."""
    venue = make_venue(db)
    event = _event_for(db)
    _pending_of(db, event, venue.id, _day(3))
    event.assigned_coordinator_id = Users.COORDINATOR_2.id
    db.flush()

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _recipients(_told(db, event.id)) == sorted([Users.COORDINATOR_2.id, Users.ORGANISER.id])


@pytest.mark.story("9.4", ac=4)
def test_only_the_events_own_people_are_told_and_never_the_one_who_saved(db, venue_staff_client):
    """AC4. cannot fail first: nothing notifies today; paired with the notice above. Other
    users get none, and when the Venue Staff member who saves is also the event's assigned
    coordinator, they are not told of their own action."""
    venue = make_venue(db)
    event = _event_for(db, assigned_coordinator_id=Users.VENUE_STAFF.id)
    _pending_of(db, event, venue.id, _day(3))

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _recipients(_told(db, event.id)) == [Users.ORGANISER.id]
    everyone_else = [
        Users.ORGANISER_2.id,
        Users.COORDINATOR.id,
        Users.COORDINATOR_2.id,
        Users.TECH_SUPPORT.id,
        Users.ATTENDEE.id,
        Users.VENUE_STAFF.id,
    ]
    told = db.scalars(
        select(Notification.recipient_id).where(
            Notification.notification_type == VENUE_UNAVAILABLE,
            Notification.recipient_id.in_(everyone_else),
        )
    ).all()
    assert list(told) == []


@pytest.mark.story("9.4", ac=4)
def test_a_refused_save_tells_nobody(db, login_as):
    """AC4. cannot fail first: no route notifies today; paired with the notice above. A
    save refused for its body (422), or by role (403), leaves no notification and no mark."""
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
    assert _marked_at(db, booking.id) is None


@pytest.mark.story("9.4", ac=4)
def test_a_reason_only_edit_tells_nobody_and_a_later_save_tells_again(db, venue_staff_client):
    """AC4: editing the reason or description of a period that affects the same
    bookings sends nothing; a later save that newly affects another booking of the same event
    sends that event's people another notice; bookings already marked are not told twice."""
    venue = make_venue(db)
    event = _event_for(db)
    _pending_of(db, event, venue.id, _day(3))
    later = _pending_of(db, event, venue.id, _day(12))
    period = _add(venue_staff_client, venue.id, _day(2), _day(7))
    period_id = uuid.UUID(period["id"])
    assert len(_told(db, event.id)) == 2

    venue_staff_client.patch(_url(venue.id, period_id), json={"reason": "SAFETY"})
    venue_staff_client.patch(_url(venue.id, period_id), json={"description": "Rewiring"})
    assert len(_told(db, event.id)) == 2

    extended = venue_staff_client.patch(
        _url(venue.id, period_id), json={"ends_at": _day(14).isoformat()}
    )

    assert extended.status_code == 200, extended.text
    assert _marked_at(db, later.id) is not None
    assert len(_told(db, event.id)) == 4
    assert _recipients(_told(db, event.id)) == sorted(
        [Users.COORDINATOR.id, Users.ORGANISER.id] * 2
    )


@pytest.mark.story("9.4", ac=4)
@pytest.mark.story("9.4", ac=6)
def test_extending_tells_only_the_event_of_the_booking_it_newly_reaches(db, venue_staff_client):
    """AC6: the event already told is not told again."""
    venue = make_venue(db)
    inside = _event_for(db)
    beyond = _event_for(db)
    _pending_of(db, inside, venue.id, _day(3))
    _pending_of(db, beyond, venue.id, _day(8))
    period = _add(venue_staff_client, venue.id, _day(2), _day(5))
    assert len(_told(db, inside.id)) == 2 and _told(db, beyond.id) == []

    venue_staff_client.patch(
        _url(venue.id, uuid.UUID(period["id"])), json={"ends_at": _day(10).isoformat()}
    )

    assert len(_told(db, inside.id)) == 2
    assert len(_told(db, beyond.id)) == 2


@pytest.mark.story("9.4", ac=6)
def test_clearing_a_mark_sends_nothing_and_leaves_the_status_alone(db, venue_staff_client):
    """AC6. cannot fail first: nothing changes status or notifies on clearing
    today; paired with the case that returns an event to Planning, which gives the clearing
    something to leave."""
    venue = make_venue(db)
    event = _event_for(db, EventStatus.CONFIRMED)
    _pending_of(db, event, venue.id, _day(3), status="APPROVED")
    period = _add(venue_staff_client, venue.id, _day(2), _day(7))
    notices = len(_told(db, event.id))
    history = len(_history(db, event.id))
    assert _status_of(db, event.id) == EventStatus.PLANNING

    removed = venue_staff_client.delete(_url(venue.id, uuid.UUID(period["id"])))

    assert removed.status_code == 204, removed.text
    assert _status_of(db, event.id) == EventStatus.PLANNING
    assert len(_told(db, event.id)) == notices == 2
    assert len(_history(db, event.id)) == history


@pytest.mark.story("9.4", ac=8)
def test_a_completed_events_status_and_notices_are_untouched(db, venue_staff_client):
    """AC8. cannot fail first: its booking is not a candidate, so nothing reaches the
    event; paired with the notice above, whose period covers both."""
    venue = make_venue(db)
    now = datetime.now(UTC)
    completed = _event_for(db, EventStatus.COMPLETED)
    _pending_of(db, completed, venue.id, now - timedelta(hours=1), status="APPROVED")
    reached = _event_for(db)
    _pending_of(db, reached, venue.id, _day(1))

    _add(venue_staff_client, venue.id, _day(-1), _day(3))

    assert _status_of(db, completed.id) == EventStatus.COMPLETED
    assert _told(db, completed.id) == []
    assert len(_told(db, reached.id)) == 2


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
def test_a_request_overlapping_a_period_cannot_be_approved_until_it_ends(db, login_as):
    """AC7: 409, still pending with no hold and nobody's decision; once the
    period is removed the same request is approved."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3))
    staff = login_as(Users.VENUE_STAFF)
    period = _add(staff, venue.id, _day(2), _day(7))

    refused = _approve(staff, booking.id)

    assert refused.status_code == 409, refused.text
    stored = _stored(db, booking.id)
    assert stored.status == "PENDING"
    assert (stored.hold_expires_at, stored.decided_by_id) == (None, None)

    staff.delete(_url(venue.id, uuid.UUID(period["id"])))
    approved = _approve(staff, booking.id)

    assert approved.status_code == 200, approved.text
    assert _stored(db, booking.id).status == "APPROVED"


@pytest.mark.story("9.4", ac=7)
def test_the_refusal_uses_the_live_overlap_not_the_mark(db, login_as):
    """AC7: a period written straight to the table leaves its booking unmarked and the
    request is still refused; a stale mark on a request no period overlaps does not refuse it."""
    venue, elsewhere = make_venue(db), make_venue(db)
    unmarked = _live(db, venue.id, _day(3))
    _period(db, venue.id, _day(2), _day(7))
    stale = _live(db, elsewhere.id, _day(3))
    _mark_in_sql(db, stale.id, datetime.now(UTC))
    staff = login_as(Users.VENUE_STAFF)

    assert _marked_at(db, unmarked.id) is None
    assert _approve(staff, unmarked.id).status_code == 409
    assert _approve(staff, stale.id).status_code == 200


@pytest.mark.story("9.4", ac=7)
def test_the_refusal_names_the_venue_and_the_period(db, login_as):
    """AC7: the sentence the request step gives (12.1 AC14), not a new one."""
    venue = make_venue(db)
    booking = _live(db, venue.id, _day(3))
    starts_at, ends_at = _day(2), _day(7)
    staff = login_as(Users.VENUE_STAFF)
    _add(staff, venue.id, starts_at, ends_at, reason="EQUIPMENT_FAILURE", description="Lift jammed")

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
@pytest.mark.parametrize("action", ["reject", "withdraw", "change_hold_expiry"])
def test_a_marked_booking_can_still_be_rejected_withdrawn_or_given_a_new_expiry(
    db, login_as, action
):
    """AC7. cannot fail first: the guard touches approval only, and these already
    work; it pins that nothing else refuses a marked booking."""
    venue = make_venue(db)
    staff = login_as(Users.VENUE_STAFF)
    if action == "change_hold_expiry":
        booking = _booking(
            db, venue.id, _day(3), _day(3, 12), status="APPROVED", hold_expires_at=_day(1)
        )
    else:
        booking = _live(db, venue.id, _day(3))
    _add(staff, venue.id, _day(2), _day(7))
    assert _marked_at(db, booking.id) is not None

    if action == "reject":
        response = staff.post(f"/bookings/{booking.id}/reject", json={"decision_reason": "No."})
    elif action == "withdraw":
        response = login_as(Users.COORDINATOR).post(f"/bookings/{booking.id}/withdraw")
    else:
        response = staff.patch(
            f"/bookings/{booking.id}",
            json={
                "hold_expires_at": _day(2).isoformat(),
                "hold_expiry_change_reason": "The organiser asked for more time.",
            },
        )

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


def _committed_pending_request(engine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A venue, and a pending request of a Planning event for it three days away, committed."""
    with Session(engine) as session:
        venue = make_venue(session)
        event = _event_for(session)
        booking = _pending_of(session, event, venue.id, _day(3))
        session.commit()
        return venue.id, event.id, booking.id


def _remove_race_rows(engine, venue_id, event_id, booking_id) -> None:
    with Session(engine) as session:
        session.execute(
            delete(AuditLog).where(
                AuditLog.entity_id.in_([booking_id, event_id])
                | (AuditLog.details["venue_id"].astext == str(venue_id))
            )
        )
        session.execute(delete(Notification).where(Notification.event_id == event_id))
        session.execute(delete(VenueBooking).where(VenueBooking.id == booking_id))
        session.execute(delete(Event).where(Event.id == event_id))
        session.execute(delete(Venue).where(Venue.id == venue_id))
        session.commit()


def _save_period(session: Session, venue_id: uuid.UUID):
    """The save, in the two steps whose lock a race needs held between them: the period, then the
    re-check that marks and so locks the venue's bookings. The caller commits."""
    session.add(
        VenueUnavailabilityPeriod(
            venue_id=venue_id,
            starts_at=_day(2),
            ends_at=_day(7),
            reason="MAINTENANCE",
            notes="Servicing",
            created_by_id=STAFF_ID,
        )
    )
    session.flush()
    return venue_service.recheck_venue_bookings(
        session, venue_id, now=datetime.now(UTC), actor=session.get(User, STAFF_ID)
    )


@pytest.mark.story("9.4", ac=10)
def test_an_approval_that_wins_the_lock_is_approved_and_the_save_then_marks_it(engine):
    """AC10, approve first. The approval holds the request's row; the save, which
    loaded the request as pending, waits on it; the approval commits and the save marks the
    request as it now stands - approved - rather than as it loaded it. cannot fail first: the
    save's re-read (``populate_existing``) is already in place; it pins the order the guard
    must keep."""
    venue_id, event_id, booking_id = _committed_pending_request(engine)
    pids: dict[str, int] = {}
    holding = threading.Event()

    def approve() -> None:
        with Session(engine) as session:
            pids["approve"] = _backend_pid(session)
            booking = booking_service.get_booking_for_decision(session, booking_id)
            holding.set()
            _wait_until(engine, pids, "save")
            booking_service.approve_booking(
                session,
                booking,
                actor_id=STAFF_ID,
                hold_expires_at=datetime.now(UTC) + timedelta(days=1),
            )

    def save() -> list[tuple[uuid.UUID, str]]:
        with Session(engine) as session:
            pids["save"] = _backend_pid(session)
            assert holding.wait(LOCK_WAIT_SECONDS)
            loaded = session.get(VenueBooking, booking_id)
            assert loaded.status == "PENDING"
            marked = _save_period(session, venue_id).newly_marked
            seen = [(booking.id, booking.status) for booking in marked]
            session.commit()
            return seen

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            approving = pool.submit(approve)
            saving = pool.submit(save)
            approving.result(timeout=40)
            seen = saving.result(timeout=40)

        assert seen == [(booking_id, "APPROVED")]
        with Session(engine) as session:
            row = session.get(VenueBooking, booking_id)
            assert (row.status, row.venue_unavailable_marked_at is not None) == ("APPROVED", True)
    finally:
        _remove_race_rows(engine, venue_id, event_id, booking_id)


@pytest.mark.story("9.4", ac=10)
def test_a_save_that_wins_the_lock_refuses_the_approval_that_waited(engine):
    """AC10, save first. The save marks the request and holds its row; the approval waits on
    it; the save commits the period and the mark together, and the approval, reading the period
    in a query of its own once the lock is its, is refused as the request step would: still
    pending, still marked, nobody's decision."""
    venue_id, event_id, booking_id = _committed_pending_request(engine)
    pids: dict[str, int] = {}
    holding = threading.Event()

    def save() -> None:
        with Session(engine) as session:
            pids["save"] = _backend_pid(session)
            _save_period(session, venue_id)
            holding.set()
            _wait_until(engine, pids, "approve")
            session.commit()

    def approve() -> Exception | None:
        with Session(engine) as session:
            pids["approve"] = _backend_pid(session)
            assert holding.wait(LOCK_WAIT_SECONDS)
            booking = booking_service.get_booking_for_decision(session, booking_id)
            try:
                booking_service.approve_booking(
                    session,
                    booking,
                    actor_id=STAFF_ID,
                    hold_expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            except booking_service.VenueBlocked as refusal:
                return refusal
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            saving = pool.submit(save)
            approving = pool.submit(approve)
            saving.result(timeout=40)
            refusal = approving.result(timeout=40)

        assert isinstance(refusal, booking_service.VenueBlocked), "the approval was not refused"
        with Session(engine) as session:
            row = session.get(VenueBooking, booking_id)
            assert row.status == "PENDING"
            assert row.venue_unavailable_marked_at is not None
            assert (row.decided_by_id, row.hold_expires_at) == (None, None)
    finally:
        _remove_race_rows(engine, venue_id, event_id, booking_id)


@pytest.mark.story("9.4", ac=10)
def test_a_save_and_the_events_confirmation_at_the_same_moment_both_finish(engine):
    """AC10. Real concurrent transactions, so this test commits and cleans up after itself. The
    confirmation holds the event's row (it sets the event to Confirmed again, which fires
    trg_events_complete_venue_holds and updates its approved bookings); the save, which returns a
    Confirmed event to Planning, waits on that row; the confirmation commits and the save goes on.
    The save locks the event before its bookings, as the confirmation does, so neither waits on
    the other for ever: both finish, the booking is marked, the event's return to Planning is
    recorded once, and the hold the confirmation completed stays completed."""
    expiry = datetime.now(UTC) + timedelta(days=1)
    with Session(engine) as session:
        venue = make_venue(session)
        event = _event_for(session, EventStatus.CONFIRMED)
        booking = _pending_of(
            session, event, venue.id, _day(3), status="APPROVED", hold_expires_at=expiry
        )
        session.commit()
        venue_id, event_id, booking_id = venue.id, event.id, booking.id
    data = VenueUnavailabilityCreate(
        starts_at=_day(2), ends_at=_day(7), reason="MAINTENANCE", description="Servicing"
    )
    pids: dict[str, int] = {}
    holding = threading.Event()

    def confirm() -> None:
        with Session(engine) as session:
            pids["confirm"] = _backend_pid(session)
            for status in (EventStatus.PLANNING, EventStatus.CONFIRMED):
                session.execute(update(Event).where(Event.id == event_id).values(status=status))
            holding.set()
            _wait_until(engine, pids, "save")
            session.commit()

    def save() -> None:
        with Session(engine) as session:
            pids["save"] = _backend_pid(session)
            assert holding.wait(LOCK_WAIT_SECONDS)
            venue_service.add_unavailability(
                session, venue_id, data, actor=session.get(User, STAFF_ID), now=datetime.now(UTC)
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            confirming = pool.submit(confirm)
            saving = pool.submit(save)
            confirming.result(timeout=40)
            saving.result(timeout=40)

        with Session(engine) as session:
            row = session.get(VenueBooking, booking_id)
            assert row.venue_unavailable_marked_at is not None
            assert row.hold_completed_at is not None
            assert session.get(Event, event_id).status == EventStatus.PLANNING
            returned = [
                history
                for history in session.scalars(
                    select(EventStatusHistory).where(EventStatusHistory.event_id == event_id)
                )
                if history.changed_by_id == STAFF_ID
                and (history.from_status, history.to_status)
                == (EventStatus.CONFIRMED, EventStatus.PLANNING)
            ]
            assert len(returned) == 1
    finally:
        _remove_race_rows(engine, venue_id, event_id, booking_id)


@pytest.mark.story("9.4", ac=10)
def test_two_saves_at_once_leave_a_booking_flagged_while_a_period_still_covers_it(engine):
    """AC10, two saves on one venue. cannot fail first: the events are locked in a statement of
    their own before the overlap is read, so a save that waited reads what the other committed.
    One save adds a second period over a flagged booking and holds; the other shortens the first
    period off the booking and waits; once the first commits, the booking stays flagged, for the
    second period still covers it."""
    venue_id, event_id, booking_id = _committed_pending_request(engine)
    with Session(engine) as session:
        first = VenueUnavailabilityPeriod(
            venue_id=venue_id,
            starts_at=_day(1),
            ends_at=_day(8),
            reason="MAINTENANCE",
            notes="Floors",
            created_by_id=STAFF_ID,
        )
        session.add(first)
        session.flush()
        first_id = first.id
        _mark_in_sql(session, booking_id, datetime.now(UTC))
        session.commit()
    pids: dict[str, int] = {}
    holding = threading.Event()

    def add_second() -> None:
        with Session(engine) as session:
            pids["add"] = _backend_pid(session)
            _save_period(session, venue_id)
            holding.set()
            _wait_until(engine, pids, "shorten")
            session.commit()

    def shorten_first() -> None:
        with Session(engine) as session:
            pids["shorten"] = _backend_pid(session)
            assert holding.wait(LOCK_WAIT_SECONDS)
            venue_service.edit_unavailability(
                session,
                venue_id,
                first_id,
                VenueUnavailabilityUpdate(ends_at=_day(2)),
                actor=session.get(User, STAFF_ID),
                now=datetime.now(UTC),
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            adding = pool.submit(add_second)
            shortening = pool.submit(shorten_first)
            adding.result(timeout=40)
            shortening.result(timeout=40)

        with Session(engine) as session:
            assert session.get(VenueBooking, booking_id).venue_unavailable_marked_at is not None
    finally:
        _remove_race_rows(engine, venue_id, event_id, booking_id)


@pytest.mark.story("9.4", ac=10)
def test_a_request_that_slipped_in_unmarked_cannot_be_approved_and_the_next_save_marks_it(
    db, login_as
):
    """AC10, the known gap, on one connection: a request raised at the instant of a save
    sits pending inside the period, unmarked. Its approval is refused; the next save on the venue
    - any - marks it."""
    venue = make_venue(db)
    _period(db, venue.id, _day(2), _day(7))
    slipped = _live(db, venue.id, _day(3))
    assert _marked_at(db, slipped.id) is None
    staff = login_as(Users.VENUE_STAFF)

    refused = _approve(staff, slipped.id)
    _add(staff, venue.id, _day(30), _day(31))

    assert refused.status_code == 409, refused.text
    assert _stored(db, slipped.id).status == "PENDING"
    assert _marked_at(db, slipped.id) is not None


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
def _unmarked_booking_under_a_period(
    db: Session, venue_id: uuid.UUID, status=EventStatus.CONFIRMED
):
    """A booking in 3 days of an event with the given status, and a period over it written
    straight to the table, so the booking is overlapped and not marked: the state a request that
    slipped in during a save leaves, which the next change to the venue's periods settles."""
    event = _event_for(db, status)
    booking = _pending_of(db, event, venue_id, _day(3))
    over = _period(db, venue_id, _day(2), _day(7), notes="Wiring")
    assert _marked_at(db, booking.id) is None
    return event, booking, over


@pytest.mark.story("9.4", ac=4)
def test_a_notice_names_the_period_that_overlaps_the_booking_not_the_one_just_saved(
    db, venue_staff_client
):
    """AC4: the booking is overlapped by a period saved earlier, and a save of another period,
    far from the booking, is what flags it. The history reason and both notices name the period
    over the booking."""
    venue = make_venue(db)
    event, _booking_, over = _unmarked_booking_under_a_period(db, venue.id)

    # Saved on the day before the covering closure begins, so it is both the one just saved and
    # the earliest of the venue's closures, and neither is the one over the booking.
    _add(venue_staff_client, venue.id, _day(1), _day(2), description="Unrelated painting")

    reason = _returned(db, event.id)[0].reason
    assert "Wiring" in reason and "Unrelated painting" not in reason
    notices = _told(db, event.id)
    assert len(notices) == 2
    for notice in notices:
        assert _on_singapore_date(over.starts_at) in notice.message
        assert _on_singapore_date(over.ends_at) in notice.message
        assert "Unrelated painting" not in notice.message


@pytest.mark.story("9.4", ac=3)
@pytest.mark.story("9.4", ac=6)
def test_ending_a_period_settles_a_booking_it_newly_flags(db, venue_staff_client):
    """AC6: the re-check after an end flags a booking that slipped in unmarked, so the event
    goes back to Planning and its people are told, as after an add or an edit."""
    venue = make_venue(db)
    event, booking, over = _unmarked_booking_under_a_period(db, venue.id)
    ending = _started(db, venue.id)

    response = venue_staff_client.patch(_url(venue.id, ending.id), json={"end_now": True})

    assert response.status_code == 200, response.text
    assert _marked_at(db, booking.id) is not None
    assert _status_of(db, event.id) == EventStatus.PLANNING
    notices = _told(db, event.id)
    assert len(notices) == 2
    assert all(_on_singapore_date(over.starts_at) in notice.message for notice in notices)


@pytest.mark.story("9.4", ac=3)
@pytest.mark.story("9.4", ac=6)
def test_removing_a_period_settles_a_booking_it_newly_flags(db, venue_staff_client):
    """AC6: the same after a removal."""
    venue = make_venue(db)
    event, booking, _over = _unmarked_booking_under_a_period(db, venue.id)
    removing = _period(db, venue.id, _days_from_now(20), _days_from_now(21))

    response = venue_staff_client.delete(_url(venue.id, removing.id))

    assert response.status_code == 204, response.text
    assert _marked_at(db, booking.id) is not None
    assert _status_of(db, event.id) == EventStatus.PLANNING
    assert len(_told(db, event.id)) == 2


# --- AC4: who sees the description -------------------------------------------------------------
@pytest.mark.story("9.4", ac=4)
def test_the_organisers_notice_leaves_out_the_description_and_the_coordinators_keeps_it(
    db, venue_staff_client
):
    """AC4 (PO decision): the organiser's notice names the venue, the period and the reason;
    the coordinator's names the description too."""
    venue = make_venue(db)
    event = _event_for(db)
    _pending_of(db, event, venue.id, _day(3))

    _add(venue_staff_client, venue.id, _day(2), _day(7), description="Asbestos found in ceiling")

    by_recipient = {notice.recipient_id: notice.message for notice in _told(db, event.id)}
    coordinator, organiser = by_recipient[Users.COORDINATOR.id], by_recipient[event.organiser_id]
    assert "Asbestos found in ceiling" in coordinator
    assert "Asbestos" not in organiser
    assert venue.name in organiser and "Maintenance" in organiser
    assert _on_singapore_date(_day(2)) in organiser


# --- AC8: which events are candidates ----------------------------------------------------------
@pytest.mark.story("9.4", ac=8)
@pytest.mark.parametrize(
    "event_status",
    [
        EventStatus.DRAFT,
        EventStatus.UNDER_REVIEW,
        EventStatus.CLARIFICATION_REQUESTED,
        EventStatus.CANCELLED,
        EventStatus.REJECTED,
    ],
)
def test_only_planning_awaiting_and_confirmed_events_are_candidates(
    db, venue_staff_client, event_status
):
    """AC8: a booking of an event in any other status is neither listed nor marked - a list of
    the statuses that count, so a status added later is left out until someone says it counts."""
    venue = make_venue(db)
    booking = _booking(
        db, venue.id, _day(3), _day(3, 12), status="PENDING", event_status=event_status
    )

    preview = _preview(venue_staff_client, venue.id, _day(2), _day(7))
    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert preview.status_code == 200, preview.text
    assert str(booking.id) not in _ids(preview)
    assert _marked_at(db, booking.id) is None


@pytest.mark.story("9.4", ac=8)
@pytest.mark.parametrize(
    "event_status",
    [EventStatus.PLANNING, EventStatus.AWAITING_SAFETY_CHECK, EventStatus.CONFIRMED],
)
def test_planning_awaiting_and_confirmed_events_are_candidates(
    db, venue_staff_client, event_status
):
    """AC8. cannot fail first: they are marked today; pinned beside the exclusions above."""
    venue = make_venue(db)
    booking = _booking(
        db, venue.id, _day(3), _day(3, 12), status="PENDING", event_status=event_status
    )

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _marked_at(db, booking.id) is not None


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


@pytest.mark.story("9.4", ac=3)
def test_a_save_leaves_another_venues_unmarked_booking_alone(db, venue_staff_client):
    """AC3. cannot fail first: the re-check is scoped to its venue; pinned so a change to its
    query cannot sweep the whole table. Another venue's booking sits inside a closure of its own
    that was written without a re-check, so it is overlapped and unmarked."""
    venue, elsewhere = make_venue(db), make_venue(db)
    stranger = _live(db, elsewhere.id, _day(3))
    _period(db, elsewhere.id, _day(2), _day(7))

    _add(venue_staff_client, venue.id, _day(2), _day(7))

    assert _marked_at(db, stranger.id) is None


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
    edges, as the marking does. The period is written straight to the table, so it is the
    guard, not the mark, that decides."""
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
    already over, so the booking is neither flagged nor listed."""
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
    assert _marked_at(db, booking.id) is None


@pytest.mark.story("9.4", ac=8)
def test_a_period_in_force_flags_a_booking_in_progress_and_the_preview_lists_it(
    db, venue_staff_client
):
    """AC8. cannot fail first: the period covers the booking's remaining time, so it counts;
    paired with the wholly-past case above."""
    venue = make_venue(db)
    booking = _in_progress(db, venue.id)

    preview = _preview(venue_staff_client, venue.id, _days_from_now(-1), _days_from_now(1))
    _add(venue_staff_client, venue.id, _days_from_now(-1), _days_from_now(1))

    assert _ids(preview) == {str(booking.id)}
    assert _marked_at(db, booking.id) is not None


@pytest.mark.story("9.4", ac=6)
def test_ending_a_period_early_clears_a_booking_whose_remaining_time_it_no_longer_covers(
    db, venue_staff_client
):
    """AC6 (PO decision): the period began yesterday and runs until tomorrow, so it covers all
    the time still to come of a booking in progress. Ending it now leaves nothing of the
    booking's remaining time covered, so the flag clears."""
    venue = make_venue(db)
    booking = _in_progress(db, venue.id)
    period = _add(venue_staff_client, venue.id, _days_from_now(-1), _days_from_now(1))
    assert _marked_at(db, booking.id) is not None

    response = venue_staff_client.patch(
        _url(venue.id, uuid.UUID(period["id"])), json={"end_now": True}
    )

    assert response.status_code == 200, response.text
    assert _marked_at(db, booking.id) is None


# --- housekeeping: the write endpoints and the preview release lapsed holds -----------------
@pytest.mark.story("9.4", ac=2)
@pytest.mark.story("9.4", ac=3)
def test_a_lapsed_hold_is_released_before_the_preview_and_the_save_look(db, venue_staff_client):
    """AC2 and AC3: an approved booking whose hold has lapsed holds nothing, as the calendar already
    treats it; the preview does not list it and the save does not flag it, whichever request
    comes first - the routes release lapsed holds as the calendar's does."""
    venue = make_venue(db)
    event = _event_for(db)
    lapsed = _pending_of(
        db,
        event,
        venue.id,
        _day(3),
        status="APPROVED",
        hold_expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    preview = _preview(venue_staff_client, venue.id, _day(2), _day(7))
    assert str(lapsed.id) not in _ids(preview)
    # A second venue's lapsed hold meets the save, with no preview before it.
    other_venue = make_venue(db)
    lapsed2 = _pending_of(
        db,
        _event_for(db),
        other_venue.id,
        _day(4),
        status="APPROVED",
        hold_expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    _add(venue_staff_client, other_venue.id, _day(2), _day(7))

    assert _marked_at(db, lapsed2.id) is None
    assert _stored(db, lapsed.id).status == "EXPIRED"
    assert _stored(db, lapsed2.id).status == "EXPIRED"


# --- the notice does not say who saved ---------------------------------------------------------
@pytest.mark.story("9.4", ac=4)
def test_the_notice_does_not_name_whoever_saved(db, venue_staff_client):
    """AC4: when a save flags a booking an earlier closure covers, the closure is not the
    saver's, so the notice says the venue is unavailable - not that someone marked it."""
    venue = make_venue(db)
    event, _booking_, _over = _unmarked_booking_under_a_period(db, venue.id)
    saver = _staff(db).full_name

    _add(venue_staff_client, venue.id, _day(1), _day(2))

    notices = _told(db, event.id)
    assert len(notices) == 2
    for notice in notices:
        assert saver not in notice.message
        assert f"{venue.name} is unavailable " in notice.message


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
@pytest.mark.story("9.4", ac=2)
@pytest.mark.story("9.4", ac=3)
@pytest.mark.parametrize("method", ["patch", "delete"])
def test_a_lapsed_hold_is_released_before_an_edit_or_a_removal(db, venue_staff_client, method):
    """AC2 and AC3: the edit and the removal release lapsed holds as the add and the preview do.
    cannot fail first: the dependency is on every write route today; it is pinned beside the
    add's."""
    venue = make_venue(db)
    period = _period(db, venue.id, _days_from_now(10), _days_from_now(12))
    lapsed = _pending_of(
        db,
        _event_for(db),
        make_venue(db).id,
        _day(3),
        status="APPROVED",
        hold_expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    response = _write(venue_staff_client, method, venue.id, period.id)

    assert response.status_code in (200, 204), response.text
    assert _stored(db, lapsed.id).status == "EXPIRED"


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


def _race_on_a_period(engine, monkeypatch, *, first, second):
    """Run ``first`` and ``second`` on one period, the first holding its row lock (the period is
    written, the transaction not yet committed) until the second is waiting on a lock. ``first``
    and ``second`` are called with a session of their own; ``second`` starts once the first holds.
    Returns what each returned or raised."""
    pids: dict[str, int] = {}
    holding = threading.Event()
    original = venue_service.recheck_venue_bookings

    def paused(*args, **kwargs):
        if not holding.is_set():
            holding.set()
            _wait_until(engine, pids, "second")
        return original(*args, **kwargs)

    monkeypatch.setattr(venue_service, "recheck_venue_bookings", paused)

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
@pytest.mark.story("9.4", ac=10)
def test_a_save_that_holds_the_event_first_and_a_confirmation_that_follows_both_finish(
    engine, monkeypatch
):
    """AC10, save first. The save re-checks and so holds the event's row, then pauses before it
    settles the event; the confirmation starts and blocks on that row; once it is waiting, the
    save settles (the event goes back to Planning) and commits; the confirmation then goes
    through. Both finish. Without the save's lock on the event the confirmation took the event
    first, its trigger then waited on the bookings the save held, and the save's own update of the
    event waited on the confirmation: a deadlock."""
    expiry = datetime.now(UTC) + timedelta(days=1)
    with Session(engine) as session:
        venue = make_venue(session)
        event = _event_for(session, EventStatus.CONFIRMED)
        booking = _pending_of(
            session, event, venue.id, _day(3), status="APPROVED", hold_expires_at=expiry
        )
        session.commit()
        venue_id, event_id, booking_id = venue.id, event.id, booking.id
    data = VenueUnavailabilityCreate(
        starts_at=_day(2), ends_at=_day(7), reason="MAINTENANCE", description="Servicing"
    )
    pids: dict[str, int] = {}
    holding = threading.Event()
    original = events_service.return_event_to_planning

    def paused(*args, **kwargs):
        holding.set()
        _wait_until(engine, pids, "confirm")
        return original(*args, **kwargs)

    monkeypatch.setattr(events_service, "return_event_to_planning", paused)

    def save() -> None:
        with Session(engine) as session:
            pids["save"] = _backend_pid(session)
            venue_service.add_unavailability(
                session, venue_id, data, actor=session.get(User, STAFF_ID), now=datetime.now(UTC)
            )

    def confirm() -> None:
        with Session(engine) as session:
            pids["confirm"] = _backend_pid(session)
            assert holding.wait(LOCK_WAIT_SECONDS)
            for status in (EventStatus.PLANNING, EventStatus.CONFIRMED):
                session.execute(update(Event).where(Event.id == event_id).values(status=status))
            session.commit()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            saving = pool.submit(save)
            confirming = pool.submit(confirm)
            saving.result(timeout=40)
            confirming.result(timeout=40)

        with Session(engine) as session:
            row = session.get(VenueBooking, booking_id)
            assert row.venue_unavailable_marked_at is not None
            assert row.hold_completed_at is not None
            assert session.get(Event, event_id).status == EventStatus.CONFIRMED
            returned = [
                history
                for history in session.scalars(
                    select(EventStatusHistory).where(EventStatusHistory.event_id == event_id)
                )
                if history.changed_by_id == STAFF_ID
                and (history.from_status, history.to_status)
                == (EventStatus.CONFIRMED, EventStatus.PLANNING)
            ]
            assert len(returned) == 1
    finally:
        _remove_race_rows(engine, venue_id, event_id, booking_id)
