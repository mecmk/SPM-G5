"""Story 12.5 - request a venue for each venue requirement and see when all are covered.

AC1  A request names the venue requirement it is for and carries that requirement's own times,
     number of people, layout and facilities; the event's booking list names it.
AC5  A request that names no requirement is an additional venue, carrying the event's own period
     and attendance (and AC7: so is every request for an event with "No venue requirements").
AC8  A requirement whose request is withdrawn or rejected takes a new one.
AC9  A venue requested for one requirement is held for that requirement's period, so it can serve
     another requirement only when their periods do not overlap.
AC10 Only the event's assigned coordinator requests; one pending or approved request per
     requirement, plus any number of additional venues.
AC11 A second request for a requirement that has one, and a request naming another event's
     requirement, are refused.
AC12 Of two requests for one requirement sent at the same moment, only the first is written; the
     second is refused, naming the venue requested for it.
AC13 Withdrawing or rejecting one booking never changes the event's others.
AC14 Each requirement's request is judged for suitability, and keeps its justification, on its own.

Decided 11 Oct 2026, beyond the ACs' wording: a requirement's pending request can be switched to
another venue in one step (``POST /bookings/{id}/switch``). The old request is withdrawn and the
new one written together, so a new venue that cannot take the request leaves the old one as it
was (AC11: still one request per requirement).

Also migration 017, which links the bookings made before this story to the requirement they were
made for, and the audit entry (DoD: each request records its requirement). The page flows are
tests/e2e/venue-requirement-booking.spec.ts.

Every case uses fresh venues and Planning events assigned to Chloe, dated December 2026, so no
seeded booking holds anything in the way.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bookings import service
from app.bookings.models import BookingStatus, VenueBooking
from app.bookings.schemas import BookingRequestIn, BookingSwitchIn
from app.common.audit import AuditLog
from app.events.models import Event, EventStatus, VenueRequirement
from app.notifications.models import Notification
from app.venues import service as venue_service
from app.venues.models import Venue
from tests.support.factories import make_booking, make_event, make_venue, make_venue_requirement
from tests.support.seed import Users

SGT = timezone(timedelta(hours=8))
BOOKINGS_PATH = "/bookings"
MIGRATION_017 = (
    Path(__file__).resolve().parents[2] / "db" / "migrations" / "017_booking_venue_requirement.sql"
)
# The schema as it stood before migration 017: bookings named no requirement.
PRE_017_SCHEMA = (
    "DROP INDEX uq_venue_bookings_one_per_requirement;"
    " ALTER TABLE venue_bookings DROP COLUMN venue_requirement_id;"
)


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    """A moment in December 2026, Singapore time."""
    return datetime(2026, 12, day, hour, minute, tzinfo=SGT)


def _moment(value: str) -> datetime:
    """A timestamp from a response body, which the API writes in UTC."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _event(db: Session, **overrides) -> Event:
    """A two-day Planning event for 200 people, assigned to Chloe."""
    return make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=overrides.pop("starts_at", _at(10, 9)),
        ends_at=overrides.pop("ends_at", _at(11, 17)),
        expected_attendance=overrides.pop("expected_attendance", 200),
        **overrides,
    )


def _plenary(db: Session, event: Event, **overrides) -> uuid.UUID:
    """The first requirement: 150 people in a theatre with two projectors, on the first day."""
    return make_venue_requirement(
        db,
        event.id,
        position=0,
        name="Plenary",
        capacity=overrides.pop("capacity", 150),
        starts_at=overrides.pop("starts_at", _at(10, 9)),
        ends_at=overrides.pop("ends_at", _at(10, 17)),
        layout_code="THEATRE",
        notes="Keynote on the first morning.",
        facilities=(("PROJECTOR", 2, "Front screen"),),
        **overrides,
    )


def _breakout(db: Session, event: Event, **overrides) -> uuid.UUID:
    """The second requirement: 30 people in a classroom, on the second afternoon."""
    return make_venue_requirement(
        db,
        event.id,
        position=1,
        name="Breakout",
        capacity=overrides.pop("capacity", 30),
        starts_at=overrides.pop("starts_at", _at(11, 13)),
        ends_at=overrides.pop("ends_at", _at(11, 17)),
        layout_code="CLASSROOM",
        **overrides,
    )


def _roomy(db: Session, **overrides) -> Venue:
    """A venue that suits both requirements, so suitability never gets in the way: it records
    four projectors, since a quantity it left blank would judge as Unknown (story 11.1 AC5)."""
    venue = make_venue(
        db,
        name=overrides.pop("name", f"Requirement Hall {uuid.uuid4().hex[:8]}"),
        capacity=overrides.pop("capacity", 400),
        layouts={"THEATRE": None, "CLASSROOM": None},
        facilities=("PROJECTOR",),
        **overrides,
    )
    venue.facilities[0].quantity = 4
    db.flush()
    return venue


def _request(client, event: Event, venue: Venue, requirement_id=None, **extra):
    body = {"event_id": str(event.id), "venue_id": str(venue.id), **extra}
    if requirement_id is not None:
        body["venue_requirement_id"] = str(requirement_id)
    return client.post(BOOKINGS_PATH, json=body)


def _switch(client, booking_id, venue: Venue, **extra):
    """Switch the pending request ``booking_id`` to ``venue`` (decided 11 Oct 2026)."""
    return client.post(
        f"{BOOKINGS_PATH}/{booking_id}/switch", json={"venue_id": str(venue.id), **extra}
    )


def _created(response) -> dict:
    assert response.status_code == 201, response.text
    return response.json()


def _bookings_of(db: Session, event: Event) -> list[VenueBooking]:
    db.expire_all()
    return list(
        db.scalars(
            select(VenueBooking)
            .where(VenueBooking.event_id == event.id)
            .order_by(VenueBooking.created_at)
        ).all()
    )


# --- AC1: a request names its requirement and carries its terms -------------------------------
@pytest.mark.story("12.5", ac=1)
def test_a_request_carries_the_named_requirements_own_terms(coordinator_client, db):
    event = _event(db)
    plenary_id = _plenary(db, event)
    breakout_id = _breakout(db, event)
    venue = _roomy(db)

    plenary = _created(_request(coordinator_client, event, venue, plenary_id))
    breakout = _created(_request(coordinator_client, event, _roomy(db), breakout_id))

    assert plenary["venue_requirement_id"] == str(plenary_id)
    assert (_moment(plenary["starts_at"]), _moment(plenary["ends_at"])) == (_at(10, 9), _at(10, 17))
    assert plenary["expected_attendance"] == 150
    assert plenary["required_layout_code"] == "THEATRE"
    assert plenary["requirement_notes"] == (
        "Required facilities: Projector & screen ×2 (Front screen).\nKeynote on the first morning."
    )
    assert breakout["venue_requirement_id"] == str(breakout_id)
    assert (breakout["expected_attendance"], breakout["required_layout_code"]) == (30, "CLASSROOM")
    assert breakout["requirement_notes"] is None


@pytest.mark.story("12.5", ac=1)
@pytest.mark.story("12.5", ac=4)
def test_the_events_booking_list_names_each_bookings_requirement(coordinator_client, db):
    event = _event(db)
    plenary_id = _plenary(db, event)
    venue, extra = _roomy(db), _roomy(db)
    _created(_request(coordinator_client, event, venue, plenary_id))
    _created(_request(coordinator_client, event, extra))

    listed = coordinator_client.get(f"{BOOKINGS_PATH}/for-event/{event.id}").json()

    by_venue = {entry["venue_name"]: entry for entry in listed}
    assert by_venue[venue.name]["venue_requirement_id"] == str(plenary_id)
    assert by_venue[venue.name]["venue_requirement_name"] == "Plenary"
    assert by_venue[extra.name]["venue_requirement_id"] is None
    assert by_venue[extra.name]["venue_requirement_name"] is None


# --- AC5/AC7: no requirement named = an additional venue ---------------------------------------
@pytest.mark.story("12.5", ac=5)
@pytest.mark.story("12.5", ac=7)
@pytest.mark.parametrize("has_requirements", [True, False], ids=["requirements", "none-required"])
def test_a_request_naming_no_requirement_is_an_additional_venue(
    coordinator_client, db, has_requirements
):
    """With requirements recorded or with "No venue requirements": the event's own period and
    attendance, and no layout, notes or requirement."""
    event = _event(db, venue_none_required=not has_requirements)
    if has_requirements:
        _plenary(db, event)

    additional = _created(_request(coordinator_client, event, _roomy(db)))

    assert additional["venue_requirement_id"] is None
    assert (_moment(additional["starts_at"]), _moment(additional["ends_at"])) == (
        _at(10, 9),
        _at(11, 17),
    )
    assert additional["expected_attendance"] == 200
    assert additional["required_layout_code"] is None
    assert additional["requirement_notes"] is None


# --- AC10: one per requirement, plus any number of additional venues --------------------------
@pytest.mark.story("12.5", ac=10)
def test_an_event_holds_a_request_per_requirement_and_several_additional_venues(
    coordinator_client, db
):
    event = _event(db)
    plenary_id, breakout_id = _plenary(db, event), _breakout(db, event)

    for requirement_id in (plenary_id, breakout_id, None, None):
        _created(_request(coordinator_client, event, _roomy(db), requirement_id))

    linked = [booking.venue_requirement_id for booking in _bookings_of(db, event)]
    assert linked == [plenary_id, breakout_id, None, None]


@pytest.mark.story("12.5", ac=10)
def test_an_unassigned_coordinator_is_refused_before_any_requirement_check(login_as, db):
    """Carl is not the event's coordinator: refused as before, whether the requirement he names
    is the event's or not, so the refusal says nothing about the event's requirements."""
    event = _event(db)
    plenary_id = _plenary(db, event)
    carl = login_as(Users.COORDINATOR_2)

    for requirement_id in (plenary_id, uuid.uuid4()):
        response = _request(carl, event, _roomy(db), requirement_id)
        assert response.status_code == 403
        assert response.json()["detail"] == service.NOT_ASSIGNED_COORDINATOR_MESSAGE


# --- AC11: refusals -----------------------------------------------------------------------------
@pytest.mark.story("12.5", ac=11)
@pytest.mark.parametrize("whose", ["another event's", "no event's"])
def test_a_requirement_that_is_not_the_events_is_refused(coordinator_client, db, whose):
    event = _event(db)
    _plenary(db, event)
    if whose == "another event's":
        requirement_id = _plenary(db, _event(db))
    else:
        requirement_id = uuid.uuid4()

    response = _request(coordinator_client, event, _roomy(db), requirement_id)

    assert response.status_code == 404
    assert response.json()["detail"] == service.REQUIREMENT_NOT_OF_EVENT_MESSAGE
    assert _bookings_of(db, event) == []


@pytest.mark.story("12.5", ac=11)
@pytest.mark.parametrize(
    ("status", "state"),
    [(BookingStatus.PENDING, "requested"), (BookingStatus.APPROVED, "booked")],
    ids=["pending", "approved"],
)
def test_a_second_request_for_a_covered_requirement_is_refused_naming_its_venue(
    coordinator_client, db, status, state
):
    event = _event(db)
    plenary_id = _plenary(db, event)
    first = _roomy(db)
    make_booking(
        db,
        event_id=event.id,
        venue_id=first.id,
        status=status,
        starts_at=_at(10, 9),
        ends_at=_at(10, 17),
        venue_requirement_id=plenary_id,
    )

    response = _request(coordinator_client, event, _roomy(db), plenary_id)

    assert response.status_code == 409
    assert response.json()["detail"] == service.REQUIREMENT_ALREADY_REQUESTED_MESSAGE.format(
        requirement="Plenary", state=state, venue=first.name
    )
    assert len(_bookings_of(db, event)) == 1


# --- AC8: withdrawn or rejected = needs a venue again ------------------------------------------
@pytest.mark.story("12.5", ac=8)
@pytest.mark.parametrize(
    "status", [BookingStatus.WITHDRAWN, BookingStatus.REJECTED], ids=["withdrawn", "rejected"]
)
def test_a_requirement_whose_request_was_released_takes_a_new_one(coordinator_client, db, status):
    event = _event(db)
    plenary_id = _plenary(db, event)
    make_booking(
        db,
        event_id=event.id,
        venue_id=_roomy(db).id,
        status=status,
        starts_at=_at(10, 9),
        ends_at=_at(10, 17),
        venue_requirement_id=plenary_id,
    )

    again = _created(_request(coordinator_client, event, _roomy(db), plenary_id))

    assert again["venue_requirement_id"] == str(plenary_id)


# --- AC9: one venue, two requirements ------------------------------------------------------------
@pytest.mark.story("12.5", ac=9)
def test_one_venue_serves_two_requirements_whose_periods_do_not_overlap(coordinator_client, db):
    """The breakout starts when the plenary ends: periods that only touch are no clash (12.1
    AC6), so the same venue takes both. A third requirement overlapping the plenary is refused,
    because the venue is held for the plenary's period."""
    event = _event(db)
    plenary_id = _plenary(db, event, starts_at=_at(10, 9), ends_at=_at(10, 12))
    breakout_id = _breakout(db, event, starts_at=_at(10, 12), ends_at=_at(10, 15))
    overlapping_id = make_venue_requirement(
        db,
        event.id,
        position=2,
        name="Overflow",
        capacity=50,
        starts_at=_at(10, 11),
        ends_at=_at(10, 13),
    )
    venue = _roomy(db)

    _created(_request(coordinator_client, event, venue, plenary_id))
    _created(_request(coordinator_client, event, venue, breakout_id))
    refused = _request(coordinator_client, event, venue, overlapping_id)

    assert refused.status_code == 409
    assert refused.json()["detail"].startswith(f"{venue.name} is already held by a pending request")


# --- AC12: two tabs at once ----------------------------------------------------------------------
@pytest.mark.story("12.5", ac=12)
def test_simultaneous_requests_for_one_requirement_write_one(engine):
    """Real concurrent transactions, so this test commits and cleans up after itself. Two
    requests for one requirement at the same moment, for two different venues: exactly one is
    written, and the other is refused naming the venue requested for it."""
    with Session(engine) as session:
        event = _event(session, name="Requirement Race")
        requirement_id = _plenary(session, event)
        venues = [_roomy(session), _roomy(session)]
        session.commit()
        event_id = event.id
        venue_names = {venue.id: venue.name for venue in venues}
    start = threading.Barrier(2)

    def attempt(venue_id: uuid.UUID) -> str:
        with Session(engine) as session:
            actor = session.get(User, Users.COORDINATOR.id)
            request = BookingRequestIn(
                event_id=event_id, venue_id=venue_id, venue_requirement_id=requirement_id
            )
            start.wait()
            try:
                service.create_booking_request(session, request, actor=actor)
            except service.RequirementAlreadyRequested as refusal:
                return str(refusal)
            return "created"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt, venue_id) for venue_id in venue_names]
            outcomes = [future.result(timeout=30) for future in futures]

        assert outcomes.count("created") == 1
        with Session(engine) as session:
            (written,) = session.scalars(
                select(VenueBooking).where(VenueBooking.event_id == event_id)
            ).all()
            winner = venue_names[written.venue_id]
        refusal = next(outcome for outcome in outcomes if outcome != "created")
        assert refusal == service.REQUIREMENT_ALREADY_REQUESTED_MESSAGE.format(
            requirement="Plenary", state="requested", venue=winner
        )
    finally:
        with Session(engine) as session:
            booking_ids = session.scalars(
                select(VenueBooking.id).where(VenueBooking.event_id == event_id)
            ).all()
            session.execute(delete(AuditLog).where(AuditLog.entity_id.in_(booking_ids)))
            session.execute(delete(VenueBooking).where(VenueBooking.event_id == event_id))
            session.execute(delete(VenueRequirement).where(VenueRequirement.event_id == event_id))
            session.execute(delete(Event).where(Event.id == event_id))
            session.execute(delete(Venue).where(Venue.id.in_(list(venue_names))))
            session.commit()


# --- AC13: each booking on its own -----------------------------------------------------------
@pytest.mark.story("12.5", ac=13)
def test_withdrawing_or_rejecting_one_booking_leaves_the_others(login_as, db):
    """The role fixtures share one client, so each role signs in for its own step."""
    coordinator_client = login_as(Users.COORDINATOR)
    event = _event(db)
    plenary_id, breakout_id = _plenary(db, event), _breakout(db, event)
    plenary = _created(_request(coordinator_client, event, _roomy(db), plenary_id))
    breakout = _created(_request(coordinator_client, event, _roomy(db), breakout_id))
    additional = _created(_request(coordinator_client, event, _roomy(db)))

    withdrawn = coordinator_client.post(f"{BOOKINGS_PATH}/{plenary['id']}/withdraw")
    rejected = login_as(Users.VENUE_STAFF).post(
        f"{BOOKINGS_PATH}/{breakout['id']}/reject", json={"decision_reason": "Room under repair."}
    )

    assert (withdrawn.status_code, rejected.status_code) == (200, 200)
    statuses = {str(booking.id): booking.status for booking in _bookings_of(db, event)}
    assert statuses == {
        plenary["id"]: BookingStatus.WITHDRAWN,
        breakout["id"]: BookingStatus.REJECTED,
        additional["id"]: BookingStatus.PENDING,
    }


# --- AC14: suitability per requirement -----------------------------------------------------
@pytest.mark.story("12.5", ac=14)
def test_each_requirement_is_judged_and_keeps_its_justification_on_its_own(coordinator_client, db):
    """A room for 50 is too small for the plenary (150) but suits the breakout (30): the
    plenary's request needs a justification and keeps it; the breakout's needs none."""
    event = _event(db)
    plenary_id, breakout_id = _plenary(db, event), _breakout(db, event)
    small = make_venue(
        db,
        name=f"Small Room {uuid.uuid4().hex[:8]}",
        capacity=50,
        layouts={"THEATRE": None, "CLASSROOM": None},
        facilities=("PROJECTOR",),
    )

    unjustified = _request(coordinator_client, event, small, plenary_id)
    plenary = _created(
        _request(
            coordinator_client,
            event,
            small,
            plenary_id,
            suitability_override_reason="The only room free that morning.",
        )
    )
    breakout = _created(
        _request(
            coordinator_client,
            event,
            small,
            breakout_id,
            suitability_override_reason="Not needed.",
        )
    )

    assert unjustified.status_code == 422
    assert unjustified.json()["detail"] == service.JUSTIFICATION_REQUIRED_MESSAGE
    assert plenary["suitability_override_reason"] == "The only room free that morning."
    assert breakout["suitability_override_reason"] is None


@pytest.mark.story("12.5", ac=14)
def test_the_suitability_read_judges_the_named_requirement_or_the_attendance_alone(
    coordinator_client, db
):
    """The request step's read names the requirement it judged; with none named - an additional
    venue - only the event's attendance (200) is judged, as the booking will carry it."""
    event = _event(db)
    _plenary(db, event)
    breakout_id = _breakout(db, event)
    venue = make_venue(db, name=f"Read Room {uuid.uuid4().hex[:8]}", capacity=100)
    path = f"/venues/{venue.id}/suitability"

    named = coordinator_client.get(
        path, params={"event": str(event.id), "requirement": str(breakout_id)}
    )
    unnamed = coordinator_client.get(path, params={"event": str(event.id)})
    stray = coordinator_client.get(
        path, params={"event": str(event.id), "requirement": str(uuid.uuid4())}
    )

    assert named.status_code == 200, named.text
    assert named.json()["requirement_name"] == "Breakout"
    assert unnamed.json()["requirement_id"] is None
    assert unnamed.json()["failures"] == [
        {
            "criterion": "CAPACITY",
            "outcome": "NOT_MET",
            "code": None,
            "name": None,
            "required": 200,
            "venue_value": 100,
        }
    ]
    assert stray.status_code == 422
    assert stray.json()["detail"] == venue_service.SEARCH_REQUIREMENT_NOT_FOUND_MESSAGE


# --- DoD auditability ---------------------------------------------------------------------------
@pytest.mark.story("12.5", ac=1)
def test_the_audit_entry_records_the_requirement(coordinator_client, db):
    event = _event(db)
    plenary_id = _plenary(db, event)
    named = _created(_request(coordinator_client, event, _roomy(db), plenary_id))
    additional = _created(_request(coordinator_client, event, _roomy(db)))

    def details_of(booking: dict) -> dict:
        entry = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == uuid.UUID(booking["id"]),
                AuditLog.action == "BOOKING_REQUESTED",
            )
        )
        return entry.details

    assert details_of(named)["venue_requirement_id"] == str(plenary_id)
    assert details_of(additional)["venue_requirement_id"] is None


# --- migration 017 --------------------------------------------------------------------------------
@pytest.mark.story("12.5", ac=1)
def test_migration_017_links_each_events_earlier_booking_to_its_first_requirement(db):
    """Bookings made before this story carried the event's first requirement (2.7 AC13). The
    oldest pending or approved one on each event is linked to it; any later ones become
    additional venues; released ones and events without requirements link nothing. Run on
    pre-017 rows inside the test's transaction, which is rolled back."""
    conn = db.connection()
    conn.exec_driver_sql(PRE_017_SCHEMA)
    event, bare = _event(db), _event(db, venue_none_required=True)
    plenary_id = _plenary(db, event)
    _breakout(db, event)

    def booking(event_id, minute: int, status=BookingStatus.PENDING) -> uuid.UUID:
        """A pre-017 row, written in SQL since the model maps the column 017 adds."""
        return db.execute(
            text(
                "INSERT INTO venue_bookings (event_id, venue_id, requested_by_id, starts_at,"
                " ends_at, expected_attendance, status, created_at) VALUES (:event_id, :venue_id,"
                " :actor, :starts_at, :ends_at, 10, :status, :created_at) RETURNING id"
            ),
            {
                "event_id": event_id,
                "venue_id": _roomy(db).id,
                "actor": Users.COORDINATOR.id,
                "starts_at": _at(10, 9),
                "ends_at": _at(10, 17),
                "status": status,
                "created_at": datetime(2026, 9, 20, 9, minute, tzinfo=SGT),
            },
        ).scalar_one()

    rejected_first = booking(event.id, 0, BookingStatus.REJECTED)
    oldest = booking(event.id, 1, BookingStatus.APPROVED)
    later = booking(event.id, 2)
    without_requirements = booking(bare.id, 3)

    conn.exec_driver_sql(MIGRATION_017.read_text(encoding="utf-8"))
    db.expire_all()

    def linked(booking_id: uuid.UUID) -> uuid.UUID | None:
        return db.get(VenueBooking, booking_id).venue_requirement_id

    assert linked(oldest) == plenary_id
    assert linked(later) is None
    assert linked(rejected_first) is None
    assert linked(without_requirements) is None


# --- Switching a pending request to another venue (decided 11 Oct 2026) -------------------------
@pytest.mark.story("12.5", ac=11)
def test_switching_a_pending_request_withdraws_it_and_requests_the_new_venue(
    coordinator_client, db
):
    """The requirement keeps one request: the old one is withdrawn, the new one is pending with
    the requirement's own terms, and the old venue is free again for that period."""
    event = _event(db)
    plenary_id = _plenary(db, event)
    first, second = _roomy(db), _roomy(db)
    old = _created(_request(coordinator_client, event, first, plenary_id))

    new = _created(_switch(coordinator_client, old["id"], second))

    assert new["venue_id"] == str(second.id)
    assert new["venue_requirement_id"] == str(plenary_id)
    assert (_moment(new["starts_at"]), _moment(new["ends_at"])) == (_at(10, 9), _at(10, 17))
    assert (new["expected_attendance"], new["required_layout_code"]) == (150, "THEATRE")
    statuses = {str(booking.id): booking.status for booking in _bookings_of(db, event)}
    assert statuses == {old["id"]: BookingStatus.WITHDRAWN, new["id"]: BookingStatus.PENDING}
    other = _event(db)
    _created(_request(coordinator_client, other, first, _plenary(db, other)))


@pytest.mark.story("12.5", ac=11)
@pytest.mark.parametrize("why", ["held", "unsuitable"])
def test_a_switch_the_new_venue_cannot_take_changes_nothing(coordinator_client, db, why):
    """Held for another event (409), or not suiting the requirement with no justification (422):
    the old request stays pending, and nothing new is written."""
    event = _event(db)
    plenary_id = _plenary(db, event)
    old = _created(_request(coordinator_client, event, _roomy(db), plenary_id))
    if why == "held":
        target = _roomy(db)
        make_booking(
            db,
            event_id=_event(db).id,
            venue_id=target.id,
            starts_at=_at(10, 9),
            ends_at=_at(10, 17),
        )
    else:
        target = make_venue(
            db,
            name=f"Small Room {uuid.uuid4().hex[:8]}",
            capacity=50,
            layouts={"THEATRE": None},
            facilities=("PROJECTOR",),
        )

    response = _switch(coordinator_client, old["id"], target)

    assert response.status_code == (409 if why == "held" else 422), response.text
    remaining = [(str(booking.id), booking.status) for booking in _bookings_of(db, event)]
    assert remaining == [(old["id"], BookingStatus.PENDING)]


@pytest.mark.story("12.5", ac=11)
@pytest.mark.parametrize(
    "status", [BookingStatus.APPROVED, BookingStatus.WITHDRAWN], ids=["approved", "withdrawn"]
)
def test_only_a_pending_request_can_be_switched(coordinator_client, db, status):
    event = _event(db)
    plenary_id = _plenary(db, event)
    decided = make_booking(
        db,
        event_id=event.id,
        venue_id=_roomy(db).id,
        status=status,
        starts_at=_at(10, 9),
        ends_at=_at(10, 17),
        venue_requirement_id=plenary_id,
    )

    response = _switch(coordinator_client, decided.id, _roomy(db))

    assert response.status_code == 409
    assert response.json()["detail"] == service.BOOKING_NOT_PENDING_MESSAGE.format(
        status=status, action="switched"
    )
    assert [booking.status for booking in _bookings_of(db, event)] == [status]


@pytest.mark.story("12.5", ac=10)
def test_only_the_assigned_coordinator_switches_and_an_unknown_request_is_not_found(login_as, db):
    """Carl is not the event's coordinator and Venue Staff do not request venues: both are
    refused (403) and the request stays as it was. A request that does not exist is 404."""
    event = _event(db)
    plenary_id = _plenary(db, event)
    old = _created(_request(login_as(Users.COORDINATOR), event, _roomy(db), plenary_id))

    carl = login_as(Users.COORDINATOR_2)
    refused = _switch(carl, old["id"], _roomy(db))
    unknown = _switch(carl, uuid.uuid4(), _roomy(db))
    staff = _switch(login_as(Users.VENUE_STAFF), old["id"], _roomy(db))

    assert refused.status_code == 403
    assert refused.json()["detail"] == service.NOT_ASSIGNED_COORDINATOR_MESSAGE
    assert unknown.status_code == 404
    assert staff.status_code == 403
    remaining = [(str(booking.id), booking.status) for booking in _bookings_of(db, event)]
    assert remaining == [(old["id"], BookingStatus.PENDING)]


@pytest.mark.story("12.5", ac=12)
def test_two_switches_of_one_request_at_once_make_one(engine):
    """Real concurrent transactions, so this test commits and cleans up after itself. Two tabs
    switch the same request to two different venues at the same moment: one switch is made, and
    the other is refused because the request is no longer pending."""
    with Session(engine) as session:
        event = _event(session, name="Switch Race")
        requirement_id = _plenary(session, event)
        venues = [_roomy(session), _roomy(session), _roomy(session)]
        old = make_booking(
            session,
            event_id=event.id,
            venue_id=venues[0].id,
            starts_at=_at(10, 9),
            ends_at=_at(10, 17),
            venue_requirement_id=requirement_id,
        )
        session.commit()
        event_id, old_id = event.id, old.id
        venue_ids = [venue.id for venue in venues]
    start = threading.Barrier(2)

    def attempt(venue_id: uuid.UUID) -> str:
        with Session(engine) as session:
            actor = session.get(User, Users.COORDINATOR.id)
            start.wait()
            replaced = service.get_booking_for_decision(session, old_id)
            try:
                service.switch_booking_request(
                    session, replaced, BookingSwitchIn(venue_id=venue_id), actor=actor
                )
            except service.BookingNotPending as refusal:
                return str(refusal)
            return "switched"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt, venue_id) for venue_id in venue_ids[1:]]
            outcomes = [future.result(timeout=30) for future in futures]

        assert sorted(outcomes) == sorted(
            [
                "switched",
                service.BOOKING_NOT_PENDING_MESSAGE.format(
                    status=BookingStatus.WITHDRAWN, action="switched"
                ),
            ]
        )
        with Session(engine) as session:
            statuses = sorted(
                session.scalars(
                    select(VenueBooking.status).where(VenueBooking.event_id == event_id)
                ).all()
            )
        assert statuses == [BookingStatus.PENDING, BookingStatus.WITHDRAWN]
    finally:
        with Session(engine) as session:
            booking_ids = session.scalars(
                select(VenueBooking.id).where(VenueBooking.event_id == event_id)
            ).all()
            session.execute(delete(AuditLog).where(AuditLog.entity_id.in_(booking_ids)))
            session.execute(delete(VenueBooking).where(VenueBooking.event_id == event_id))
            session.execute(delete(VenueRequirement).where(VenueRequirement.event_id == event_id))
            session.execute(delete(Event).where(Event.id == event_id))
            session.execute(delete(Venue).where(Venue.id.in_(venue_ids)))
            session.commit()


@pytest.mark.story("12.5", ac=11)
def test_a_switch_is_audited_and_venue_staff_are_told(coordinator_client, db):
    """Both halves are recorded as their own actions are: the withdrawal (12.2) and the new
    request (12.1), which names the request it replaces. Venue Staff are told of each."""
    event = _event(db)
    plenary_id = _plenary(db, event)
    old = _created(_request(coordinator_client, event, _roomy(db), plenary_id))

    new = _created(_switch(coordinator_client, old["id"], _roomy(db)))

    entries = db.scalars(
        select(AuditLog).where(AuditLog.entity_id.in_([uuid.UUID(old["id"]), uuid.UUID(new["id"])]))
    ).all()
    recorded = {(entry.action, str(entry.entity_id)): entry.details for entry in entries}
    assert ("BOOKING_WITHDRAWN", old["id"]) in recorded
    assert recorded[("BOOKING_REQUESTED", new["id"])]["replaces_booking_id"] == old["id"]
    told = {
        (notice.notification_type, str(notice.related_entity_id))
        for notice in db.scalars(
            select(Notification).where(Notification.recipient_id == Users.VENUE_STAFF.id)
        )
    }
    assert ("BOOKING_WITHDRAWN", old["id"]) in told
    assert ("BOOKING_REQUESTED", new["id"]) in told
