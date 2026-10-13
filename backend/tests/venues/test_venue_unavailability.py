"""Story 9.4: mark a venue temporarily unavailable.

Slice 1 (migration 020): the reasons a period can carry.
Slice 2: add, edit, end and remove a period, the preview of what it would affect, and who may.

AC1  Venue Staff mark a venue unavailable from a start to an end with a reason: Maintenance,
     Equipment failure, Renovation, Safety concern or Other (a description is required for
     Other). It shows on the venue's calendar and is excluded from venue searches.

The table's own rules are what this slice proves: the CHECK constraints refuse a reason outside
the five and an Other without a description, migration 020 moves existing rows onto the new set,
and the calendar and the booking request name each reason.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings.models import VenueBooking
from app.common.audit import AuditLog
from app.events.models import Event, EventStatus
from app.venues import service as venue_service
from app.venues.models import VenueUnavailabilityPeriod
from tests.support.factories import make_booking, make_event, make_unavailability, make_venue
from tests.support.seed import Users

SGT = timezone(timedelta(hours=8))
MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"

REASON_CONSTRAINT = "ck_venue_unavailability_reason"
DESCRIPTION_CONSTRAINT = "ck_venue_unavailability_other_description"

# The table as it stood before migration 020: INTERNAL_USE allowed, no EQUIPMENT_FAILURE, and an
# Other that needs no description. IF EXISTS keeps this valid on a database 020 has not reached.
PRE_020_SCHEMA = (
    f"ALTER TABLE venue_unavailability_periods DROP CONSTRAINT IF EXISTS {DESCRIPTION_CONSTRAINT};"
    f" ALTER TABLE venue_unavailability_periods DROP CONSTRAINT {REASON_CONSTRAINT};"
    f" ALTER TABLE venue_unavailability_periods ADD CONSTRAINT {REASON_CONSTRAINT} CHECK"
    " (reason IN ('MAINTENANCE', 'RENOVATION', 'SAFETY', 'INTERNAL_USE', 'OTHER'));"
)

# Story 9.4 AC1: the five reasons, as the database stores them.
REASONS = ["MAINTENANCE", "EQUIPMENT_FAILURE", "RENOVATION", "SAFETY", "OTHER"]
# What the calendar calls a period when it has no description of its own.
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
@pytest.mark.parametrize("notes", [None, "Gym floor relaid"])
def test_internal_use_is_no_longer_a_reason(db, notes):
    """The five reasons are AC1's: a code outside them is refused by the table itself."""
    refusal = _refused(db, "INTERNAL_USE", notes)

    assert refusal is not None, "INTERNAL_USE was accepted"
    assert REASON_CONSTRAINT in str(refusal.orig)


@pytest.mark.story("9.4", ac=1)
@pytest.mark.parametrize("notes", [None, "", "   ", "\t\n"])
def test_other_needs_a_description_in_the_table_itself(db, notes):
    """AC1: Other without a description is refused whatever wrote it. A description makes it
    valid, and every other reason may go without one."""
    refusal = _refused(db, "OTHER", notes)

    assert refusal is not None, f"OTHER with notes {notes!r} was accepted"
    assert DESCRIPTION_CONSTRAINT in str(refusal.orig)
    assert _refused(db, "OTHER", "Gala stage being built") is None
    assert _refused(db, "MAINTENANCE", None) is None


@pytest.mark.story("9.4", ac=1)
def test_migration_020_moves_existing_periods_onto_the_five_reasons(db):
    """Run on pre-020 rows inside the test's transaction, which is rolled back: Internal use
    becomes Other, saying so and keeping what was written; an Other with nothing written gets a
    description; everything else is left as it was. Afterwards the table refuses what AC1
    refuses."""
    migration = next(MIGRATIONS.glob("020_*.sql"), None)
    assert migration is not None, "migration 020 has not been written"
    conn = db.connection()
    conn.exec_driver_sql(PRE_020_SCHEMA)
    venue = make_venue(db)
    internal_bare = _insert(db, venue.id, "INTERNAL_USE", None, day=1)
    internal_noted = _insert(db, venue.id, "INTERNAL_USE", "Gym floor relaid", day=2)
    other_null = _insert(db, venue.id, "OTHER", None, day=3)
    other_blank = _insert(db, venue.id, "OTHER", "   ", day=4)
    other_described = _insert(db, venue.id, "OTHER", "Gala stage being built", day=5)
    maintenance = _insert(db, venue.id, "MAINTENANCE", None, day=6)

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
    assert stored(maintenance) == ("MAINTENANCE", None)
    refusal = _refused(db, "INTERNAL_USE", "x")
    assert refusal is not None and REASON_CONSTRAINT in str(refusal.orig)
    refusal = _refused(db, "OTHER", None)
    assert refusal is not None and DESCRIPTION_CONSTRAINT in str(refusal.orig)


@pytest.mark.story("9.4", ac=1)
def test_the_calendar_names_each_reason(db, venue_staff_client):
    """AC1: a period shows with its reason, and Equipment failure is one of them. Safety is the
    code SAFETY, named Safety concern. A description, where given, is what the entry reads."""
    venue = make_venue(db)
    for day, reason in enumerate(REASON_NAMES, start=1):
        make_unavailability(
            db, venue_id=venue.id, starts_at=_at(day), ends_at=_at(day + 1), reason=reason
        )
    make_unavailability(
        db,
        venue_id=venue.id,
        starts_at=_at(10),
        ends_at=_at(11),
        reason="OTHER",
        notes="Gala stage being built",
    )

    response = venue_staff_client.get(
        f"/venues/{venue.id}/calendar",
        params={"starts_at": _at(1).isoformat(), "ends_at": _at(28).isoformat()},
    )

    assert response.status_code == 200, response.text
    labels = {window["reason"]: window["label"] for window in response.json()}
    assert labels == {**REASON_NAMES, "OTHER": "Gala stage being built"}


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
# Slice 2: add, edit, end and remove a period; preview what it would affect; who may.
#
#   POST   /venues/{id}/unavailability                       add
#   PATCH  /venues/{id}/unavailability/{period_id}           edit, or {"end_now": true} alone
#   DELETE /venues/{id}/unavailability/{period_id}           remove a period not yet started
#   GET    /venues/{id}/unavailability/affected-bookings     preview (AC2)
#
# A period's body is {starts_at, ends_at, reason, description}; ``description`` is the column
# ``notes``. Each failing case below fails today because the route does not exist (404/405), and
# the plan case it belongs to is named in its docstring. Marking bookings and the event's status
# are slices 3 and 4 and are not asserted here.
# =====================================================================================
PERIOD_FIELDS = {"id", "venue_id", "starts_at", "ends_at", "reason", "description"}

# Audit actions every write leaves, one row each (plan case X.2a, asserted in 6.11).
CREATED, UPDATED, ENDED, REMOVED = (
    "VENUE_UNAVAILABILITY_CREATED",
    "VENUE_UNAVAILABILITY_UPDATED",
    "VENUE_UNAVAILABILITY_ENDED",
    "VENUE_UNAVAILABILITY_REMOVED",
)

# Every case here is days away from the clock, so none depends on when it runs, except the two
# that ask for the server's own now (6.1a, the audit row), which bracket it, and the boundary at
# exactly now, which calls the service with a ``now`` of its own as 12.7's tests do.
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
        "description": None,
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


def _audit_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(AuditLog))


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
    """Plan 1.1: 201, the period as stored, the Venue Staff member who made it."""
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
    """Plan 1.3."""
    venue = make_venue(db)

    response = venue_staff_client.post(
        _url(venue.id), json=_future_body(reason="OTHER", description="Gala stage being built")
    )

    assert response.status_code == 201, response.text
    assert response.json()["description"] == "Gala stage being built"
    assert _periods(db, venue.id)[0].notes == "Gala stage being built"


@pytest.mark.story("9.4", ac=1)
@pytest.mark.parametrize("description", [None, "", "   ", "\t\n", "<omitted>"])
def test_other_without_a_description_is_refused(db, venue_staff_client, description):
    """Plan 1.4: 422 and nothing saved, for a missing, empty or blank description."""
    venue = make_venue(db)
    body = _future_body(reason="OTHER", description=description)
    if description == "<omitted>":
        del body["description"]

    response = venue_staff_client.post(_url(venue.id), json=body)

    assert response.status_code == 422, response.text
    assert _periods(db, venue.id) == []


@pytest.mark.story("9.4", ac=1)
@pytest.mark.parametrize("reason", ["INTERNAL_USE", "WEATHER", "", "maintenance"])
def test_a_reason_outside_the_five_is_refused(db, venue_staff_client, reason):
    """Plan 1.2b and 1.7: 422, nothing saved. Codes are exact, so lower case is refused too."""
    venue = make_venue(db)

    response = venue_staff_client.post(
        _url(venue.id), json=_future_body(reason=reason, description="x")
    )

    assert response.status_code == 422, response.text
    assert _periods(db, venue.id) == []


@pytest.mark.story("9.4", ac=1)
@pytest.mark.parametrize("description", [None, "Annual air-con servicing"])
def test_a_reason_other_than_other_needs_no_description(db, venue_staff_client, description):
    """Plan 1.6: saved with or without one."""
    venue = make_venue(db)

    response = venue_staff_client.post(_url(venue.id), json=_future_body(description=description))

    assert response.status_code == 201, response.text
    assert response.json()["description"] == description


@pytest.mark.story("9.4", ac=1)
def test_an_unknown_venue_is_not_found(db, venue_staff_client):
    """Plan 1.8: 404 for a venue that is not there; a known venue takes the same body (201), so
    the 404 is the venue's and not the route's."""
    known = make_venue(db)
    assert venue_staff_client.post(_url(known.id), json=_future_body()).status_code == 201

    response = venue_staff_client.post(_url(uuid.uuid4()), json=_future_body())

    assert response.status_code == 404


@pytest.mark.story("9.4", ac=1)
def test_a_withdrawn_venue_can_be_marked_unavailable(db, venue_staff_client):
    """Plan 1.9 (D14): editing a withdrawn venue is allowed today, so marking it is too."""
    venue = make_venue(db, status="WITHDRAWN")

    response = venue_staff_client.post(_url(venue.id), json=_future_body())

    assert response.status_code == 201, response.text


@pytest.mark.story("9.4", ac=1)
def test_the_calendar_shows_the_new_period_with_its_reason_description_and_id(
    db, venue_staff_client
):
    """Plan 1.10: AC1's "shows on the venue's calendar", and the period's id so the page can
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
def test_a_period_added_through_the_api_keeps_the_venue_out_of_a_search(db, venue_staff_client):
    """Plan 1.11. cannot fail first, for the search half: 8.1 already leaves a blocked venue out
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
    """Plan 5.1: end equal to or before start is 422 on create - not the database's 500."""
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
    """Plan 5.1 on edit: the rule applies to the period as it would be after the edit, so moving
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
    """Plan 5.6: a missing end, or a moment with no timezone, is 422."""
    venue = make_venue(db)
    body = _future_body()
    del body[missing]
    naive = {**_future_body(), "starts_at": "2027-03-04T09:00:00"}

    assert venue_staff_client.post(_url(venue.id), json=body).status_code == 422
    assert venue_staff_client.post(_url(venue.id), json=naive).status_code == 422
    assert _periods(db, venue.id) == []


# --- AC6 (the period itself): end, remove, shorten, extend -----------------------------------
@pytest.mark.story("9.4", ac=6)
def test_end_now_ends_a_started_period_at_the_servers_now(db, venue_staff_client):
    """Plan 6.1a: the server sets ``ends_at`` to its own now, not a moment the client names - it
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
    """Plan 6.2a: the row is gone."""
    venue = make_venue(db)
    period = _period(db, venue.id, _days_from_now(10), _days_from_now(12))

    response = venue_staff_client.delete(_url(venue.id, period.id))

    assert response.status_code == 204, response.text
    assert _periods(db, venue.id) == []


@pytest.mark.story("9.4", ac=6)
def test_an_edit_changes_start_end_reason_and_description(db, venue_staff_client):
    """Plan 6.3a and 6.11: the four fields each change, shortening and extending included."""
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


@pytest.mark.story("9.4", ac=6)
def test_an_edit_may_not_leave_an_other_without_its_description(db, venue_staff_client):
    """Plan 1.4 on edit, kept with the edit cases: changing the reason to OTHER needs a
    description, and clearing the description of an OTHER is refused. The period is unchanged."""
    venue = make_venue(db)
    plain = _period(db, venue.id, _days_from_now(10), _days_from_now(12))
    other = _period(
        db, venue.id, _days_from_now(20), _days_from_now(22), reason="OTHER", notes="Gala stage"
    )

    to_other = venue_staff_client.patch(_url(venue.id, plain.id), json={"reason": "OTHER"})
    cleared = venue_staff_client.patch(_url(venue.id, other.id), json={"description": ""})

    assert (to_other.status_code, cleared.status_code) == (422, 422)
    stored = {period.id: period for period in _periods(db, venue.id)}
    assert stored[plain.id].reason == "MAINTENANCE"
    assert stored[other.id].notes == "Gala stage"


@pytest.mark.story("9.4", ac=6)
def test_a_period_starting_exactly_now_counts_as_not_started(db):
    """Plan 6.8: ``starts_at == now`` is not started - ending it would break
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
    """Plan 6.9 at its boundary: ``ends_at == now`` is ended, and it is left as it was."""
    venue = make_venue(db)
    now = _days_from_now(10)
    period = _period(db, venue.id, now - timedelta(days=3), now)

    with pytest.raises(venue_service.PeriodAlreadyEnded):
        venue_service.end_unavailability(db, venue.id, period.id, actor=_staff(db), now=now)
    assert _periods(db, venue.id)[0].ends_at == now


@pytest.mark.story("9.4", ac=6)
def test_an_already_ended_period_cannot_be_ended_again(db, venue_staff_client):
    """Plan 6.9: a period that ended a day ago. 409, and the row is exactly as it was."""
    venue = make_venue(db)
    ends_at = _days_from_now(-1)
    period = _period(db, venue.id, ends_at - timedelta(days=3), ends_at)

    response = venue_staff_client.patch(_url(venue.id, period.id), json={"end_now": True})

    assert response.status_code == 409, response.text
    assert _periods(db, venue.id)[0].ends_at == ends_at


@pytest.mark.story("9.4", ac=6)
def test_a_started_period_cannot_be_removed(db, venue_staff_client):
    """Plan 6.12: a period in force is ended, not removed, so the calendar keeps its history.
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
    """Plan 6.13: ``end_now`` with any other field is 422 and changes nothing."""
    venue = make_venue(db)
    period = _started(db, venue.id)
    ends_at = period.ends_at

    response = venue_staff_client.patch(_url(venue.id, period.id), json={"end_now": True, **extra})

    assert response.status_code == 422, response.text
    assert _periods(db, venue.id)[0].ends_at == ends_at


@pytest.mark.story("9.4", ac=6)
def test_an_unknown_period_and_one_of_another_venue_are_not_found(db, venue_staff_client):
    """Plan 6.10: 404 for edit and removal alike. The period's own venue takes the same edit
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
    """Plan 6.11 and X.2a: creation, edit, end and removal each write one row, naming the actor,
    and an edit keeps what it replaced so the log is the history (D3)."""
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
    """Plan X.2a, the refused half. cannot fail first: no route writes an audit row today, so
    the count cannot change; it guards the refused paths once the routes exist, and is paired
    with the audit-row case above."""
    venue = make_venue(db)
    period = _started(db, venue.id)
    before = _audit_count(db)

    venue_staff_client.post(_url(venue.id), json=_future_body(reason="OTHER"))
    venue_staff_client.delete(_url(venue.id, period.id))
    venue_staff_client.patch(_url(venue.id, uuid.uuid4()), json={"end_now": True})

    assert _audit_count(db) == before


# --- AC8 (the period itself): in the past ----------------------------------------------------
@pytest.mark.story("9.4", ac=8)
def test_a_period_in_the_past_is_saved_and_shown(db, venue_staff_client):
    """Plan 8.4 (D5): nothing beyond AC5 limits the start, so a closure that has happened is
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
    """Plan 2.1: each with its event, status and held period."""
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
    """Plan 2.2: the held period, not the event's own, is what is measured; a window that only
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
    """Plan 2.3: rejected, withdrawn, cancelled and expired ones hold nothing, so they are not
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
    """Plan 2.4."""
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
    """Plan 2.5 (D12): a COMPLETED event's booking, and one whose held period has ended, are not
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
    """Plan 2.6: 200, no period, no audit row, no booking or event touched."""
    venue = make_venue(db)
    day = _days_from_now(20).replace(hour=9, minute=0, second=0)
    booking = _booking(db, venue.id, day, day + timedelta(hours=2), status="PENDING")
    audit_before = _audit_count(db)

    response = _preview(
        venue_staff_client, venue.id, day - timedelta(hours=1), day + timedelta(hours=3)
    )

    assert response.status_code == 200, response.text
    assert _periods(db, venue.id) == []
    assert _audit_count(db) == audit_before
    db.expire_all()
    assert db.get(VenueBooking, booking.id).status == "PENDING"


@pytest.mark.story("9.4", ac=2)
def test_a_period_may_be_saved_with_bookings_in_the_way(db, venue_staff_client):
    """Plan 2.7: AC2's "saving is allowed even when there are some". The booking stays as it
    was - marking it is slice 3's."""
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
@pytest.mark.parametrize("role", [Users.COORDINATOR, Users.TECH_SUPPORT])
def test_other_internal_roles_cannot_add_edit_or_end(db, login_as, role, method):
    """Plan 9.1: 403, and the period is as it was. A period already exists so PATCH and DELETE
    have something to refuse."""
    venue = make_venue(db)
    period = _period(db, venue.id, _days_from_now(10), _days_from_now(12))

    response = _write(login_as(role), method, venue.id, period.id)

    assert response.status_code == 403, response.text
    (stored,) = _periods(db, venue.id)
    assert (stored.reason, stored.notes) == ("MAINTENANCE", None)


@pytest.mark.story("9.4", ac=9)
@pytest.mark.parametrize("method", WRITES)
@pytest.mark.parametrize("role", [Users.ORGANISER, Users.ATTENDEE, None])
def test_external_roles_and_the_signed_out_cannot_add_edit_or_end(db, login_as, role, method):
    """Plan 9.2: 403 for a signed-in organiser or attendee, 401 when signed out."""
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
@pytest.mark.parametrize("role", [Users.COORDINATOR, Users.TECH_SUPPORT, Users.ORGANISER, None])
def test_only_venue_staff_may_preview(db, login_as, role):
    """Plan 2.9: the preview is part of marking a venue unavailable, so it is Venue Staff's."""
    venue = make_venue(db)
    day = _days_from_now(20)
    client = login_as(role or Users.VENUE_STAFF)
    if role is None:
        client.logout()

    response = _preview(client, venue.id, day, day + timedelta(days=1))

    assert response.status_code == (401 if role is None else 403), response.text


@pytest.mark.story("9.4", ac=9)
@pytest.mark.parametrize("role", [Users.COORDINATOR, Users.TECH_SUPPORT])
def test_other_internal_roles_read_the_reason_on_the_calendar(db, login_as, role):
    """Plan 9.3. cannot fail first, for the read half: 9.1 already shows a closure's reason to
    these roles. Written through the new POST so it is red with it."""
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
    """Plan 9.4. cannot fail first: they hold neither venues:read nor venue_calendar:read today
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
