"""Story 17.1 - display equipment reserved for my event. INTEGRATION tests: the event API on
PostgreSQL.

Level: integration. Each test reads an event's items through ``GET /events/{event_id}``, the
event page's own call, against the real schema in the rolled-back test transaction. There is no
unit file: 17.1 adds no rule to test on its own - an item's period is its event's, and its status
is the one 15.1 and 16.1 recorded - so every case needs an event and its items in the database.
What the Equipment requirements section shows (each status's label, Released, no controls for
the organiser) is e2e-tested in ``tests/e2e/equipment-display.spec.ts``. Refusing an organiser's
change to the equipment is 15.1 AC9's, tested in ``test_request_equipment.py``, and not repeated.

AC1 The event page's Equipment requirements section lists each item with its type, quantity,
    period (the event's own, which every item is held for, 15.1 AC2) and status: Not yet sent,
    Pending, Accepted (reserved), Declined with Technical Support's reason, Unavailable or
    Released; once decided, who decided and when. There is no separate equipment tab.
AC2 The event API returns each item with these fields. The owning organiser receives the same
    items, read-only.
AC3 An event with no equipment shows "No equipment requested".
AC4 An item released because its event was cancelled (6.2), or an approved change removed it
    (19.2), shows as Released, holding nothing.
AC5 Everyone who can open the event's page sees the list: the owning organiser and the internal
    roles (2.1 AC8), among them the assigned coordinator, Technical Support and the Safety
    Officer. Only the assigned coordinator can change it, while the event is open (15.1 AC9).
    An attendee is refused (403); another organiser is told the event is not found (404).
AC6 The list reflects the latest state when the page is loaded again.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.events.models import Event, EventStatus
from tests.support.factories import make_equipment_item, make_equipment_type, make_event
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


def _sign_in(client, user: SeedUser):
    client.login(user)
    return client


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
def test_an_items_period_follows_its_event_when_the_dates_change(coordinator_client, db: Session):
    """Every item is held for its event's period (15.1 AC2), so a date change (15.1 AC8) moves
    each item's period with it."""
    event = _event(db)
    make_equipment_item(db, event=event, equipment_type=make_equipment_type(db), quantity=1)
    moved_start, moved_end = STARTS_AT + timedelta(days=7), ENDS_AT + timedelta(days=7)

    event.starts_at, event.ends_at = moved_start, moved_end
    db.flush()

    (item,) = _items(coordinator_client, event)
    assert _period(item) == (moved_start, moved_end)


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
    """An item cancelled with its event (6.2): the event Cancelled, the item CANCELLED, holding
    nothing."""
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
    """Technical Support and the Safety Officer among them: 21.1's safety check reads the
    accepted equipment from here."""
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
def test_a_decision_made_after_the_page_loaded_shows_when_it_is_loaded_again(client, db: Session):
    event = _event(db)
    item = make_equipment_item(
        db,
        event=event,
        equipment_type=make_equipment_type(db),
        quantity=1,
        status="PENDING",
        **_sent(),
    )
    (before,) = _items(_sign_in(client, Users.COORDINATOR), event)

    decided = _sign_in(client, Users.TECH_SUPPORT).post(
        f"/equipment-requests/{item.id}/decision", json={"outcome": "ACCEPTED"}
    )
    (after,) = _items(_sign_in(client, Users.COORDINATOR), event)

    assert decided.status_code == 201, decided.text  # a decision is recorded once
    assert (before["status"], before["decided_by_name"]) == ("PENDING", None)
    assert (after["status"], after["decided_by_name"]) == ("ACCEPTED", Users.TECH_SUPPORT.full_name)
    assert after["decided_at"] is not None
