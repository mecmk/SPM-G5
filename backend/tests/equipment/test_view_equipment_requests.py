"""Story 15.2 - view equipment requests.

As a Technical Support Staff member I want to see the equipment requests waiting for me, with
what is available for each, so that I can work through them in a sensible order.

AC1 The queue lists equipment requests with event name, event dates, item type, quantity,
    technical notes and requesting coordinator, soonest event first.
AC2 Each request shows the quantity available for the event's period and any shortfall (requested
    against available). It uses the same calculation as holding (15.1): total stock, less units
    held or reserved for overlapping periods, less units out of service.
AC3 Tabs show Pending, Accepted and Declined requests. A decided request leaves the Pending tab.
    Team request, beyond the AC: an All tab - leaving ``status`` out - lists the three together.
AC4 A request exactly equal to the available quantity shows no shortfall. Holds and reservations
    whose periods only touch the event's period at a boundary are not deducted.
AC5 An item the coordinator removes, or any item on a cancelled or rejected event, disappears from
    the queue.
    An empty queue shows a message (tests/e2e/equipment-queue.spec.ts).
AC6 Only Technical Support Staff can see the queue. Other roles are refused, including through
    the API.
AC7 The figures reflect every hold and reservation at the moment the page loads, and refreshing
    shows the current state.

A Pending item already holds its own units (15.1 AC2), so its hold is not counted against it: the
figure is what the event's period leaves for this request. A shortfall therefore appears only when
stock is lost after the hold was placed, such as units going out of service.

Accepted and Declined are Technical Support's decisions (story 16.1), which nothing in this story
writes, so the factory makes them. The other item statuses - REQUESTED (not yet sent), UNAVAILABLE
(15.1 AC8) and CANCELLED - belong to no tab.

Every case uses a fresh equipment type (``make_equipment_type``), so a test owns its whole stock,
on factory events dated September 2027, clear of every seeded hold. The seeded queue is never
empty, so a test looks for its own items rather than counting rows.

Excluded, with reason:
* Conflict "two people act on one request at once" - the queue is read-only; deciding a request
  is story 16.1. AC7's conflict is about fresh figures, covered below.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.events.models import EquipmentType, Event, EventEquipmentRequest, EventStatus
from tests.support.factories import (
    make_equipment_hold,
    make_equipment_item,
    make_equipment_out_of_service,
    make_equipment_type,
    make_event,
)
from tests.support.seed import EquipmentItems, Users

QUEUE_PATH = "/equipment-requests"
PENDING, ACCEPTED, DECLINED = "PENDING", "ACCEPTED", "DECLINED"
TAB_STATUSES = (PENDING, ACCEPTED, DECLINED)
NO_TAB_STATUSES = ("REQUESTED", "UNAVAILABLE", "CANCELLED")

SGT = timezone(timedelta(hours=8))
START = datetime(2027, 9, 6, 9, 0, tzinfo=SGT)
END = datetime(2027, 9, 6, 17, 0, tzinfo=SGT)


def _event(db: Session, *, starts_at: datetime = START, ends_at: datetime = END, **extra) -> Event:
    return make_event(
        db,
        status=extra.pop("status", EventStatus.PLANNING),
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=starts_at,
        ends_at=ends_at,
        **extra,
    )


def _sent(
    db: Session,
    *,
    event: Event,
    equipment_type: EquipmentType,
    quantity: int,
    status: str = PENDING,
    **extra,
) -> EventEquipmentRequest:
    """An item the coordinator has sent to Technical Support. A declined item holds nothing."""
    return make_equipment_item(
        db,
        event=event,
        equipment_type=equipment_type,
        quantity=quantity,
        status=status,
        is_held=extra.pop("is_held", status != DECLINED),
        submitted_by_id=extra.pop("submitted_by_id", Users.COORDINATOR.id),
        submitted_at=extra.pop("submitted_at", datetime(2026, 10, 1, 9, 0, tzinfo=SGT)),
        **extra,
    )


def _queue(client, status: str | None = PENDING) -> dict:
    """One tab of the queue; ``status=None`` is the All tab."""
    response = client.get(QUEUE_PATH if status is None else f"{QUEUE_PATH}?status={status}")
    assert response.status_code == 200, response.text
    return response.json()


def _ids(client, status: str | None = PENDING) -> list[str]:
    return [row["id"] for row in _queue(client, status)["items"]]


def _entry(client, item_id: uuid.UUID, status: str = PENDING) -> dict:
    return next(row for row in _queue(client, status)["items"] if row["id"] == str(item_id))


# --- AC1: what each request shows, and in what order -------------------------------------------
@pytest.mark.story("15.2", ac=1)
def test_the_seeded_pending_request_is_listed(tech_client):
    assert str(EquipmentItems.SHOWCASE_SPEAKERS) in _ids(tech_client)


@pytest.mark.story("15.2", ac=1)
def test_a_request_shows_its_event_item_notes_and_requesting_coordinator(tech_client, db):
    event = _event(db, name="Harbour Gala Dinner")
    kit = make_equipment_type(db, name="Stage monitor", total_quantity=5)
    item = _sent(
        db,
        event=event,
        equipment_type=kit,
        quantity=2,
        technical_notes="Facing the lectern",
        submitted_by_id=Users.COORDINATOR_2.id,
    )

    entry = _entry(tech_client, item.id)

    assert entry["event_id"] == str(event.id)
    assert entry["event_name"] == "Harbour Gala Dinner"
    assert datetime.fromisoformat(entry["starts_at"]) == START
    assert datetime.fromisoformat(entry["ends_at"]) == END
    assert entry["equipment_type_code"] == kit.code
    assert entry["equipment_type_name"] == "Stage monitor"
    assert entry["quantity"] == 2
    assert entry["technical_notes"] == "Facing the lectern"
    assert entry["status"] == PENDING
    # The coordinator who sent it, not the one now assigned to the event.
    assert entry["requested_by_name"] == Users.COORDINATOR_2.full_name


@pytest.mark.story("15.2", ac=1)
def test_a_request_with_no_recorded_sender_names_nobody(tech_client, db):
    """An item sent before migration 014 has no sender, and the queue does not guess one."""
    item = _sent(
        db,
        event=_event(db),
        equipment_type=make_equipment_type(db),
        quantity=1,
        submitted_by_id=None,
        submitted_at=None,
    )

    assert _entry(tech_client, item.id)["requested_by_name"] is None


@pytest.mark.story("15.2", ac=1)
def test_requests_are_listed_soonest_event_first(tech_client, db):
    kit = make_equipment_type(db, total_quantity=10)
    later = _sent(
        db,
        event=_event(db, starts_at=START + timedelta(days=14), ends_at=END + timedelta(days=14)),
        equipment_type=kit,
        quantity=1,
    )
    soonest = _sent(db, event=_event(db), equipment_type=kit, quantity=1)
    middle = _sent(
        db,
        event=_event(db, starts_at=START + timedelta(days=7), ends_at=END + timedelta(days=7)),
        equipment_type=kit,
        quantity=1,
    )
    mine = {str(item.id) for item in (later, soonest, middle)}

    listed = [item_id for item_id in _ids(tech_client) if item_id in mine]

    assert listed == [str(soonest.id), str(middle.id), str(later.id)]


# --- AC2: available for the event's period, and the shortfall ----------------------------------
@pytest.mark.story("15.2", ac=2)
def test_the_requests_own_hold_is_not_counted_against_it(tech_client, db):
    kit = make_equipment_type(db, total_quantity=4)
    item = _sent(db, event=_event(db), equipment_type=kit, quantity=4)

    entry = _entry(tech_client, item.id)

    assert entry["available"] == 4
    assert entry["shortfall"] == 0


@pytest.mark.story("15.2", ac=2)
def test_available_deducts_other_holds_and_units_out_of_service(tech_client, db):
    kit = make_equipment_type(db, total_quantity=10)
    item = _sent(db, event=_event(db), equipment_type=kit, quantity=2)
    make_equipment_hold(db, type_code=kit.code, quantity=3, starts_at=START, ends_at=END)
    make_equipment_out_of_service(db, type_code=kit.code, quantity=2, starts_at=START, ends_at=END)

    assert _entry(tech_client, item.id)["available"] == 10 - 3 - 2


@pytest.mark.story("15.2", ac=2)
def test_units_going_out_of_service_after_the_hold_show_a_shortfall(tech_client, db):
    kit = make_equipment_type(db, total_quantity=5)
    item = _sent(db, event=_event(db), equipment_type=kit, quantity=4)
    make_equipment_out_of_service(db, type_code=kit.code, quantity=3, starts_at=START, ends_at=END)

    entry = _entry(tech_client, item.id)

    assert entry["available"] == 2
    assert entry["shortfall"] == 2


@pytest.mark.story("15.2", ac=2)
def test_open_ended_out_of_service_units_are_deducted(tech_client, db):
    kit = make_equipment_type(db, total_quantity=5)
    item = _sent(db, event=_event(db), equipment_type=kit, quantity=3)
    make_equipment_out_of_service(
        db, type_code=kit.code, quantity=4, starts_at=START - timedelta(days=30), ends_at=None
    )

    entry = _entry(tech_client, item.id)

    assert entry["available"] == 1
    assert entry["shortfall"] == 2


@pytest.mark.story("15.2", ac=2)
def test_released_units_of_another_hold_are_not_deducted(tech_client, db):
    kit = make_equipment_type(db, total_quantity=6)
    item = _sent(db, event=_event(db), equipment_type=kit, quantity=1)
    make_equipment_hold(
        db, type_code=kit.code, quantity=3, released_quantity=2, starts_at=START, ends_at=END
    )

    assert _entry(tech_client, item.id)["available"] == 6 - 1


@pytest.mark.story("15.2", ac=2)
@pytest.mark.parametrize("status", [ACCEPTED, DECLINED])
def test_decided_requests_show_figures_too(tech_client, db, status):
    kit = make_equipment_type(db, total_quantity=5)
    item = _sent(db, event=_event(db), equipment_type=kit, quantity=2, status=status)
    make_equipment_hold(db, type_code=kit.code, quantity=4, starts_at=START, ends_at=END)

    entry = _entry(tech_client, item.id, status)

    assert entry["available"] == 1
    assert entry["shortfall"] == 1


# --- AC3: Pending, Accepted and Declined tabs ---------------------------------------------------
@pytest.mark.story("15.2", ac=3)
@pytest.mark.parametrize("status", TAB_STATUSES)
def test_a_tab_lists_only_requests_in_its_status(tech_client, db, status):
    item = _sent(
        db, event=_event(db), equipment_type=make_equipment_type(db), quantity=1, status=status
    )

    items = _queue(tech_client, status)["items"]

    assert str(item.id) in [row["id"] for row in items]
    assert {row["status"] for row in items} == {status}


@pytest.mark.story("15.2", ac=3)
def test_counts_cover_every_tab_whichever_is_asked_for(tech_client, db):
    before = _queue(tech_client, DECLINED)["counts"]
    for status in TAB_STATUSES:
        _sent(
            db, event=_event(db), equipment_type=make_equipment_type(db), quantity=1, status=status
        )

    after = _queue(tech_client, DECLINED)["counts"]

    assert after == {key: before[key] + 1 for key in ("pending", "accepted", "declined")}


@pytest.mark.story("15.2", ac=3)
@pytest.mark.parametrize("status", [ACCEPTED, DECLINED])
def test_a_decided_request_leaves_the_pending_tab(tech_client, db, status):
    item = _sent(db, event=_event(db), equipment_type=make_equipment_type(db), quantity=1)
    assert str(item.id) in _ids(tech_client, PENDING)

    item.status = status  # story 16.1's decision, made directly
    db.flush()

    assert str(item.id) not in _ids(tech_client, PENDING)
    assert str(item.id) in _ids(tech_client, status)


@pytest.mark.story("15.2", ac=3)
@pytest.mark.parametrize("status", ["pending", "REQUESTED", "ALL", ""])
def test_a_status_that_is_not_a_tab_is_refused(tech_client, status):
    assert tech_client.get(f"{QUEUE_PATH}?status={status}").status_code == 422


@pytest.mark.story("15.2", ac=3)
@pytest.mark.parametrize("status", TAB_STATUSES)
def test_without_a_status_every_tab_is_listed(tech_client, db, status):
    item = _sent(
        db, event=_event(db), equipment_type=make_equipment_type(db), quantity=1, status=status
    )

    items = _queue(tech_client, None)["items"]

    assert str(item.id) in [row["id"] for row in items]
    assert {row["status"] for row in items} <= set(TAB_STATUSES)


@pytest.mark.story("15.2", ac=3)
@pytest.mark.story("15.2", ac=5)
def test_without_a_status_no_tab_and_cancelled_items_are_still_left_out(tech_client, db):
    hidden = [
        _sent(
            db,
            event=_event(db),
            equipment_type=make_equipment_type(db),
            quantity=1,
            status=item_status,
            is_held=False,
        )
        for item_status in NO_TAB_STATUSES
    ]
    hidden.append(
        _sent(
            db,
            event=_event(db, status=EventStatus.CANCELLED),
            equipment_type=make_equipment_type(db),
            quantity=1,
        )
    )

    listed = set(_ids(tech_client, None))

    assert listed.isdisjoint({str(item.id) for item in hidden})


@pytest.mark.story("15.2", ac=1)
def test_the_all_tab_is_soonest_event_first_too(tech_client, db):
    kit = make_equipment_type(db, total_quantity=10)
    later = _sent(
        db,
        event=_event(db, starts_at=START + timedelta(days=7), ends_at=END + timedelta(days=7)),
        equipment_type=kit,
        quantity=1,
    )
    sooner = _sent(db, event=_event(db), equipment_type=kit, quantity=1, status=ACCEPTED)
    mine = {str(later.id), str(sooner.id)}

    listed = [item_id for item_id in _ids(tech_client, None) if item_id in mine]

    assert listed == [str(sooner.id), str(later.id)]


# --- AC4: boundaries ----------------------------------------------------------------------------
@pytest.mark.story("15.2", ac=4)
def test_a_request_equal_to_what_is_available_has_no_shortfall(tech_client, db):
    kit = make_equipment_type(db, total_quantity=5)
    item = _sent(db, event=_event(db), equipment_type=kit, quantity=3)
    make_equipment_out_of_service(db, type_code=kit.code, quantity=2, starts_at=START, ends_at=END)

    entry = _entry(tech_client, item.id)

    assert entry["available"] == 3
    assert entry["shortfall"] == 0


@pytest.mark.story("15.2", ac=4)
def test_a_request_one_over_what_is_available_is_short_by_one(tech_client, db):
    kit = make_equipment_type(db, total_quantity=5)
    item = _sent(db, event=_event(db), equipment_type=kit, quantity=4)
    make_equipment_out_of_service(db, type_code=kit.code, quantity=2, starts_at=START, ends_at=END)

    assert _entry(tech_client, item.id)["shortfall"] == 1


@pytest.mark.story("15.2", ac=4)
@pytest.mark.parametrize(
    ("starts_at", "ends_at"),
    [(START - timedelta(hours=3), START), (END, END + timedelta(hours=3))],
    ids=["ends-as-event-starts", "starts-as-event-ends"],
)
def test_a_hold_that_only_touches_the_event_is_not_deducted(tech_client, db, starts_at, ends_at):
    kit = make_equipment_type(db, total_quantity=5)
    item = _sent(db, event=_event(db), equipment_type=kit, quantity=5)
    make_equipment_hold(db, type_code=kit.code, quantity=5, starts_at=starts_at, ends_at=ends_at)

    entry = _entry(tech_client, item.id)

    assert entry["available"] == 5
    assert entry["shortfall"] == 0


@pytest.mark.story("15.2", ac=4)
@pytest.mark.parametrize(
    ("starts_at", "ends_at"),
    [(START - timedelta(hours=3), START), (END, END + timedelta(hours=3))],
    ids=["ends-as-event-starts", "starts-as-event-ends"],
)
def test_units_out_of_service_only_touching_the_event_are_not_deducted(
    tech_client, db, starts_at, ends_at
):
    kit = make_equipment_type(db, total_quantity=5)
    item = _sent(db, event=_event(db), equipment_type=kit, quantity=5)
    make_equipment_out_of_service(
        db, type_code=kit.code, quantity=5, starts_at=starts_at, ends_at=ends_at
    )

    assert _entry(tech_client, item.id)["shortfall"] == 0


@pytest.mark.story("15.2", ac=4)
def test_a_hold_overlapping_the_event_by_a_minute_is_deducted(tech_client, db):
    kit = make_equipment_type(db, total_quantity=5)
    item = _sent(db, event=_event(db), equipment_type=kit, quantity=5)
    make_equipment_hold(
        db,
        type_code=kit.code,
        quantity=1,
        starts_at=END - timedelta(minutes=1),
        ends_at=END + timedelta(hours=3),
    )

    assert _entry(tech_client, item.id)["shortfall"] == 1


# --- AC5: what leaves the queue -----------------------------------------------------------------
@pytest.mark.story("15.2", ac=5)
def test_an_item_the_coordinator_removes_disappears(login_as, db):
    event = _event(db)
    item = _sent(db, event=event, equipment_type=make_equipment_type(db), quantity=1)
    removed = login_as(Users.COORDINATOR).delete(f"/events/{event.id}/equipment/{item.id}")
    assert removed.status_code == 204

    assert str(item.id) not in _ids(login_as(Users.TECH_SUPPORT))


@pytest.mark.story("15.2", ac=5)
@pytest.mark.parametrize("event_status", [EventStatus.CANCELLED, EventStatus.REJECTED])
@pytest.mark.parametrize("status", TAB_STATUSES)
def test_any_item_on_a_cancelled_or_rejected_event_disappears(
    tech_client, db, status, event_status
):
    before = _queue(tech_client, status)["counts"]
    event = _event(db, status=event_status)
    item = _sent(db, event=event, equipment_type=make_equipment_type(db), quantity=1, status=status)

    assert str(item.id) not in _ids(tech_client, status)
    assert _queue(tech_client, status)["counts"] == before


@pytest.mark.story("15.2", ac=5)
@pytest.mark.parametrize("item_status", NO_TAB_STATUSES)
def test_an_item_in_no_tabs_status_is_never_listed_or_counted(tech_client, db, item_status):
    before = _queue(tech_client)["counts"]
    item = _sent(
        db,
        event=_event(db),
        equipment_type=make_equipment_type(db),
        quantity=1,
        status=item_status,
        is_held=item_status == "REQUESTED",
    )

    for tab in TAB_STATUSES:
        assert str(item.id) not in _ids(tech_client, tab)
    assert _queue(tech_client)["counts"] == before


# --- AC6: only Technical Support Staff ----------------------------------------------------------
@pytest.mark.story("15.2", ac=6)
@pytest.mark.parametrize(
    "user", [Users.ORGANISER, Users.COORDINATOR, Users.VENUE_STAFF, Users.ATTENDEE]
)
def test_other_roles_cannot_see_the_queue(client, user):
    client.login(user)
    assert client.get(f"{QUEUE_PATH}?status={PENDING}").status_code == 403


@pytest.mark.story("15.2", ac=6)
def test_signed_out_user_is_refused(client):
    assert client.get(f"{QUEUE_PATH}?status={PENDING}").status_code == 401


# --- AC7: figures as they stand at each load ----------------------------------------------------
@pytest.mark.story("15.2", ac=7)
def test_each_load_reflects_the_holds_as_they_stand(tech_client, db):
    kit = make_equipment_type(db, total_quantity=5)
    item = _sent(db, event=_event(db), equipment_type=kit, quantity=3)
    assert _entry(tech_client, item.id)["shortfall"] == 0

    hold = make_equipment_hold(db, type_code=kit.code, quantity=4, starts_at=START, ends_at=END)
    assert _entry(tech_client, item.id)["available"] == 1
    assert _entry(tech_client, item.id)["shortfall"] == 2

    hold.status = "RELEASED"
    hold.released_quantity = hold.quantity
    db.flush()
    assert _entry(tech_client, item.id)["available"] == 5
