"""Story 17.1 - display equipment reserved for my event. INTEGRATION tests: the event API on
PostgreSQL.

Level: integration. Each test reads an event's items through ``GET /events/{event_id}``, the
event page's own call, against the real schema in the rolled-back test transaction. There is no
unit file: 17.1 adds no rule to test on its own - an item's period is its hold's, or its event's
while it holds nothing, and its status is the one 15.1 and 16.1 recorded - so every case needs an
event, its items and their holds in the database. The section's own changes - Accepted (reserved),
Released and its note, which decision was made, the period on each item, and no controls for the
organiser - are e2e-tested in ``tests/e2e/equipment-display.spec.ts``; the other statuses' labels
are 15.1's and 16.1's. Refusing an organiser's change to the equipment is 15.1 AC9's, tested in
``test_request_equipment.py``, and not repeated.

The story and its acceptance criteria, as the backlog has them:

As an Event Coordinator I want to see what equipment is held for my event so that I can confirm the
arrangements.

AC1 The event page's Equipment requirements section lists each requested item with type,
    quantity, period and status: Pending, Accepted (reserved) or Declined with the reason. There
    is no separate equipment request tab.
AC2 The event API returns the items with their status; the organiser's copy is read-only.
AC3 An event with no equipment shows "No equipment requested".
AC4 A cancelled event shows its items as released.
AC5 Visible to the assigned coordinator and Technical Support. The organiser has read-only access.
AC6 The list reflects the latest state after a refresh.

Refinements proposed with this story, waiting on the backlog's Change Log; the tests below check
them:
AC1 The list also shows Not yet sent and Unavailable, and who decided and when. An item's period
    is the one its hold covers, or its event's while it holds nothing (a draft's item, or a
    declined, unavailable or released one).
AC4 An item is released when its event is cancelled (6.2) or an approved change removes it
    (19.2), and holds nothing.
AC5 Everyone who can open the event's page sees the list, as 2.1 AC8 already shows an event's
    items to every internal role: the organiser read-only, and the internal roles, among them the
    assigned coordinator and Technical Support. An attendee is refused (403); another organiser is
    told the event is not found (404).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.orm import Session

from app.events.models import Event, EventStatus
from tests.support.factories import (
    make_equipment_item,
    make_equipment_type,
    make_event,
    make_venue_requirement,
)
from tests.support.seed import SeedUser, Users

STARTS_AT = datetime(2027, 6, 15, 1, 0, tzinfo=UTC)
ENDS_AT = STARTS_AT + timedelta(hours=8)
DECIDED_AT = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)
SUBMITTED_AT = datetime(2026, 9, 30, 2, 0, tzinfo=UTC)

# Every internal role but the assigned coordinator's (AC5): each holds events:read_all.
OTHER_INTERNAL_ROLES = [
    Users.TECH_SUPPORT,
    Users.SAFETY_OFFICER,
    Users.LEAD,
    Users.COORDINATOR_2,
    Users.VENUE_STAFF,
]


def _event(db: Session, **overrides) -> Event:
    """A Planning event of the organiser's, assigned to the coordinator."""
    return make_event(
        db,
        status=overrides.pop("status", EventStatus.PLANNING),
        organiser_id=Users.ORGANISER.id,
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=overrides.pop("starts_at", STARTS_AT),
        ends_at=overrides.pop("ends_at", ENDS_AT),
        **overrides,
    )


def _sent(**fields) -> dict:
    """The fields an item sent to Technical Support carries (15.1 AC1)."""
    return {"submitted_at": SUBMITTED_AT, "submitted_by_id": Users.COORDINATOR.id, **fields}


def _correctable_event(db: Session) -> Event:
    """``_event`` with everything a 7.2 correction keeps 2.1 AC10's checks on: the details, the
    point of contact, the accessibility answer and a venue requirement for the whole period."""
    event = _event(
        db,
        description="A planned event.",
        contact_name="Priya Nair",
        contact_email="priya.nair@example.com",
        contact_phone="+65 9123 4567",
        accessibility_none_required=True,
    )
    make_venue_requirement(db, event.id)
    return event


def _decided(**fields) -> dict:
    """The fields an item Technical Support decided carries (16.1 AC3)."""
    return _sent(decided_at=DECIDED_AT, decided_by_id=Users.TECH_SUPPORT.id, **fields)


def _items(client, event: Event) -> list[dict]:
    response = client.get(f"/events/{event.id}")
    assert response.status_code == 200, response.text
    return response.json()["equipment"]


def _period(item: dict) -> tuple[datetime | None, datetime | None]:
    starts, ends = item["period_starts_at"], item["period_ends_at"]
    return (
        None if starts is None else datetime.fromisoformat(starts),
        None if ends is None else datetime.fromisoformat(ends),
    )


def _statements_reading(client, db: Session, *, items: int) -> int:
    """How many SQL statements ``GET /events/{event_id}`` runs for an event with ``items`` items,
    each holding its units."""
    event = _event(db)
    for _ in range(items):
        make_equipment_item(db, event=event, equipment_type=make_equipment_type(db), quantity=1)
    db.commit()  # expires every row, so the read loads them all, as a fresh request does
    executed: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        executed.append(statement)

    connection = db.connection()
    sqlalchemy_event.listen(connection, "before_cursor_execute", record)
    try:
        _items(client, event)
    finally:
        sqlalchemy_event.remove(connection, "before_cursor_execute", record)
    return len(executed)


# =============================================================================================
# AC1 - each item, with its type, quantity, period and status
# =============================================================================================
@pytest.mark.story("17.1", ac=1)
def test_each_item_is_listed_with_its_type_quantity_period_and_status(
    coordinator_client, db: Session
):
    event = _event(db)
    waiting = make_equipment_type(db, name="Waiting kit")
    pending = make_equipment_type(db, name="Pending kit")
    accepted = make_equipment_type(db, name="Accepted kit")
    declined = make_equipment_type(db, name="Declined kit")
    make_equipment_item(db, event=event, equipment_type=waiting, quantity=1)
    make_equipment_item(
        db, event=event, equipment_type=pending, quantity=2, status="PENDING", **_sent()
    )
    make_equipment_item(
        db, event=event, equipment_type=accepted, quantity=3, status="ACCEPTED", **_decided()
    )
    make_equipment_item(
        db,
        event=event,
        equipment_type=declined,
        quantity=4,
        status="DECLINED",
        is_held=False,
        **_decided(status_notes="All four are booked for a conference that week."),
    )

    items = _items(coordinator_client, event)

    # Items made in one transaction share created_at, so the list's order is not asserted.
    assert sorted(
        (item["equipment_type_name"], item["quantity"], item["status"], _period(item))
        for item in items
    ) == [
        ("Accepted kit", 3, "ACCEPTED", (STARTS_AT, ENDS_AT)),
        ("Declined kit", 4, "DECLINED", (STARTS_AT, ENDS_AT)),
        ("Pending kit", 2, "PENDING", (STARTS_AT, ENDS_AT)),
        ("Waiting kit", 1, "REQUESTED", (STARTS_AT, ENDS_AT)),
    ]
    (declined_item,) = [item for item in items if item["status"] == "DECLINED"]
    assert declined_item["decision_reason"] == "All four are booked for a conference that week."
    assert declined_item["decided_by_name"] == Users.TECH_SUPPORT.full_name
    assert datetime.fromisoformat(declined_item["decided_at"]) == DECIDED_AT


@pytest.mark.story("17.1", ac=1)
def test_a_drafts_items_have_no_period_until_its_dates_are_set(organiser_client, db: Session):
    """A draft may be saved with equipment before its dates (2.1 AC1, AC6); it holds nothing
    until submitted (2.1 AC11), so its items have no period yet."""
    draft = make_event(
        db, status=EventStatus.DRAFT, organiser_id=Users.ORGANISER.id, starts_at=None, ends_at=None
    )
    make_equipment_item(
        db, event=draft, equipment_type=make_equipment_type(db), quantity=1, is_held=False
    )

    (item,) = _items(organiser_client, draft)

    assert _period(item) == (None, None)


@pytest.mark.story("17.1", ac=1)
def test_an_items_period_is_what_its_hold_covers_after_a_correction_shortens_the_event(
    login_as, db: Session
):
    """7.2 AC15 keeps every hold as it is for a move inside the period it covers, so an event a
    correction starts an hour late and ends an hour early still holds its accepted item for the
    old period, and the page says what is held. A declined item holds nothing, so it is for the
    event's own, new period."""
    event = _correctable_event(db)
    make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db, name="Held kit"),
        quantity=1,
        status="ACCEPTED",
        **_decided(),
    )
    make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db, name="Unheld kit"),
        quantity=1,
        status="DECLINED",
        is_held=False,
        **_decided(status_notes="None are free that day."),
    )
    db.commit()
    client = login_as(Users.COORDINATOR)
    read = client.get(f"/events/{event.id}").json()
    later_start, earlier_end = STARTS_AT + timedelta(hours=1), ENDS_AT - timedelta(hours=1)

    corrected = client.patch(
        f"/events/{event.id}/review-details",
        json={
            "expected_updated_at": read["updated_at"],
            "starts_at": later_start.isoformat(),
            "ends_at": earlier_end.isoformat(),
        },
    )

    assert corrected.status_code == 200, corrected.text
    periods = {item["equipment_type_name"]: _period(item) for item in _items(client, event)}
    assert periods == {
        "Held kit": (STARTS_AT, ENDS_AT),
        "Unheld kit": (later_start, earlier_end),
    }


# =============================================================================================
# AC2 - the event API, and the organiser's read-only copy
# =============================================================================================
@pytest.mark.story("17.1", ac=2)
def test_the_organiser_is_sent_the_same_items_as_the_coordinator(login_as, db: Session):
    event = _event(db)
    make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db),
        quantity=2,
        status="ACCEPTED",
        **_decided(),
    )

    coordinators = _items(login_as(Users.COORDINATOR), event)
    organisers = _items(login_as(Users.ORGANISER), event)

    assert organisers == coordinators
    assert _period(organisers[0]) == (STARTS_AT, ENDS_AT)


# =============================================================================================
# AC3 - an event with no equipment
# =============================================================================================
@pytest.mark.story("17.1", ac=2)
def test_each_items_hold_is_read_with_the_items_not_one_statement_per_item(
    coordinator_client, db: Session
):
    """An item's period comes from its hold, loaded with the item: an event with six items is read
    in as many statements as an event with one."""
    one = _statements_reading(coordinator_client, db, items=1)
    six = _statements_reading(coordinator_client, db, items=6)

    assert six == one


@pytest.mark.story("17.1", ac=3)
def test_an_event_with_no_equipment_is_sent_an_empty_list(coordinator_client, db: Session):
    assert _items(coordinator_client, _event(db)) == []


# =============================================================================================
# AC4 - a released item
# =============================================================================================
@pytest.mark.story("17.1", ac=4)
def test_a_released_item_on_a_cancelled_event_is_sent_as_cancelled_with_its_period(
    coordinator_client, db: Session
):
    """A Cancelled event with its item CANCELLED and holding nothing, the state a cancelled
    event's items are in."""
    event = _event(db, status=EventStatus.CANCELLED)
    make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db),
        quantity=2,
        status="CANCELLED",
        is_held=False,
        **_sent(),
    )

    (item,) = _items(coordinator_client, event)

    assert (item["status"], _period(item)) == ("CANCELLED", (STARTS_AT, ENDS_AT))


# =============================================================================================
# AC5 - who sees the list
# =============================================================================================
@pytest.mark.story("17.1", ac=5)
@pytest.mark.parametrize("user", OTHER_INTERNAL_ROLES, ids=lambda user: user.role)
def test_every_internal_role_is_sent_the_items(login_as, db: Session, user: SeedUser):
    """Technical Support and the Safety Officer among them: 2.1 AC8 already shows an event's
    items to every internal role."""
    event = _event(db)
    make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db, name="Shared kit"),
        quantity=1,
        status="ACCEPTED",
        **_decided(),
    )

    (item,) = _items(login_as(user), event)

    assert (item["equipment_type_name"], item["status"], _period(item)) == (
        "Shared kit",
        "ACCEPTED",
        (STARTS_AT, ENDS_AT),
    )


@pytest.mark.story("17.1", ac=5)
def test_another_organiser_is_told_the_event_is_not_found(login_as, db: Session):
    """The event is not theirs, so its existence is not given away (2.1 AC12)."""
    event = _event(db)
    make_equipment_item(db, event=event, equipment_type=make_equipment_type(db), quantity=1)

    response = login_as(Users.ORGANISER_2).get(f"/events/{event.id}")

    assert response.status_code == 404
    assert "equipment" not in response.json()


@pytest.mark.story("17.1", ac=5)
def test_an_attendee_is_refused_the_event(login_as, db: Session):
    """An attendee's role may not read events at all (1.2 AC4), so the refusal comes first."""
    event = _event(db)
    make_equipment_item(db, event=event, equipment_type=make_equipment_type(db), quantity=1)

    response = login_as(Users.ATTENDEE).get(f"/events/{event.id}")

    assert response.status_code == 403
    assert "equipment" not in response.json()


# =============================================================================================
# AC6 - the latest state, when the page is loaded again
# =============================================================================================
@pytest.mark.story("17.1", ac=6)
def test_a_decision_made_after_the_page_loaded_shows_when_it_is_loaded_again(login_as, db: Session):
    event = _event(db)
    item = make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db),
        quantity=1,
        status="PENDING",
        **_sent(),
    )
    (before,) = _items(login_as(Users.COORDINATOR), event)

    decided = login_as(Users.TECH_SUPPORT).post(
        f"/equipment-requests/{item.id}/decision", json={"outcome": "ACCEPTED"}
    )
    (after,) = _items(login_as(Users.COORDINATOR), event)

    assert decided.status_code == 201, decided.text  # a decision is recorded once
    assert (before["status"], before["decided_by_name"]) == ("PENDING", None)
    assert (after["status"], after["decided_by_name"]) == ("ACCEPTED", Users.TECH_SUPPORT.full_name)
    assert after["decided_at"] is not None
