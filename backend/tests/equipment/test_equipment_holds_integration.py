"""Story 17.3 - view the equipment holds schedule as Technical Support. INTEGRATION tests: the API
over PostgreSQL.

As Technical Support Staff, I want a schedule of every equipment hold, grouped by equipment type,
so that I can see at a glance which events have which equipment, from when to when.

AC1 The Equipment holds page groups every current hold by equipment type. Under each type, each
    hold shows the event name, the quantity, the dates it runs from and to, and whether it is not
    yet sent, Pending or Accepted. Holds are listed soonest first.
AC2 Holds on items not yet sent to Technical Support are included, since they already hold units
    (15.1 AC2).
AC3 It can be filtered by equipment type and by date range. A hold is shown when any part of it
    falls in the range. The range can't start before today, since past holds are not listed
    (AC5).
AC4 Each sent hold opens its equipment request page (16.1). The page is read-only: there is no
    Accept or Decline.
AC5 Only holds that haven't ended appear. Declined, cancelled, withdrawn, unavailable and released
    items hold nothing, so they never appear. (Reworded before the build, CL-210: a 7.2 correction
    inside the held period keeps the hold's dates, so a hold can outlast its event, and its units
    stay taken until it ends.)
AC6 A type with no holds in the range says so.
AC7 Only EQUIPMENT_MANAGE holders can open it. Anyone else gets a 403.

``GET /equipment-holds`` answers with ``types``, every active type for the filter, and ``groups``,
one per active type by name - or the filtered type's alone - each with its holds. A hold is a
RESERVED ``equipment_reservations`` row, its quantity the units it has not released, its dates its
own, which are its event's unless a 7.2 correction moved the event inside them.

The rules on their own - Singapore's today, the period a range covers, the three refusals and the
grouping - are unit-tested in ``test_equipment_holds_unit.py``. Moments are the request's own
(``datetime.now``) except where AC5 needs a fixed one: those cases call the service with ``now``.
Every hold here is on a fresh type (``make_equipment_type``), so a test owns its whole stock, and
dated in 2032, clear of every seeded hold. The seeded types are listed too, so a test reads its own
type's group by code rather than counting groups.

Excluded, with reason:
* Conflict - the endpoint only reads, so there is nothing two people can do at once. A hold
  released between two reads is the decline, withdrawal, removal and cancellation cases below.
* The page's links and the absence of Accept and Decline (AC4) are e2e cases:
  ``tests/e2e/equipment-holds.spec.ts``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.equipment import service
from app.events.models import (
    EquipmentReservation,
    EquipmentType,
    Event,
    EventEquipmentRequest,
    EventStatus,
)
from tests.support.factories import make_equipment_item, make_equipment_type, make_event
from tests.support.seed import Users

HOLDS_PATH = "/equipment-holds"
SGT = timezone(timedelta(hours=8))
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
# A day of 2032 no seeded hold is on, and the days either side of it.
DAY_BEFORE, THE_DAY, DAY_AFTER = date(2032, 3, 9), date(2032, 3, 10), date(2032, 3, 11)
MIDNIGHT = datetime(2032, 3, 10, 0, 0, tzinfo=SGT)  # 00:00 SGT on THE_DAY
# AC3's refusals, written out so a red run shows what the server answers instead.
START_BEFORE_TODAY = "The start date cannot be before today."
END_BEFORE_START = "The end date cannot be before the start date."
END_BEFORE_TODAY = "The end date cannot be before today."


def _event(db: Session, *, starts_at: datetime, ends_at: datetime, **extra) -> Event:
    """A Planning event coordinated by Users.COORDINATOR, so its equipment can still change."""
    return make_event(
        db,
        status=extra.pop("status", EventStatus.PLANNING),
        assigned_coordinator_id=Users.COORDINATOR.id,
        starts_at=starts_at,
        ends_at=ends_at,
        **extra,
    )


def _held(
    db: Session,
    kind: EquipmentType,
    *,
    starts_at: datetime,
    ends_at: datetime,
    quantity: int = 2,
    status: str = "ACCEPTED",
    event: Event | None = None,
    name: str | None = None,
    released: int = 0,
    hold_id: uuid.UUID | None = None,
) -> EquipmentReservation:
    """An item of ``kind`` holding ``quantity`` units from ``starts_at`` to ``ends_at``, on
    ``event`` or on an event of its own over that period. The hold's dates are its own, as a 7.2
    correction inside the held period leaves them. A sent item carries who sent it and when."""
    if event is None:
        extra = {} if name is None else {"name": name}
        event = _event(db, starts_at=starts_at, ends_at=ends_at, **extra)
    sent = {}
    if status != "REQUESTED":
        sent = {"submitted_by_id": Users.COORDINATOR.id, "submitted_at": datetime.now(SGT)}
    item = make_equipment_item(
        db,
        event=event,
        equipment_type=kind,
        quantity=quantity,
        status=status,
        is_held=False,
        **sent,
    )
    hold = EquipmentReservation(
        id=hold_id or uuid.uuid4(),
        event_id=event.id,
        equipment_request_id=item.id,
        equipment_type_id=kind.id,
        quantity=quantity,
        released_quantity=released,
        starts_at=starts_at,
        ends_at=ends_at,
        reserved_by_id=Users.COORDINATOR.id,
    )
    db.add(hold)
    db.flush()
    return hold


def _on_the_day(db: Session, kind: EquipmentType, **extra) -> EquipmentReservation:
    """A hold of ``kind`` from 09:00 to 17:00 SGT on THE_DAY."""
    return _held(db, kind, starts_at=MIDNIGHT + 9 * HOUR, ends_at=MIDNIGHT + 17 * HOUR, **extra)


def _query(*, type_code=None, from_date=None, to_date=None) -> dict:
    params = {"type": type_code, "from": from_date, "to": to_date}
    return {key: str(value) for key, value in params.items() if value is not None}


def _schedule(client, **filters) -> dict:
    response = client.get(HOLDS_PATH, params=_query(**filters))
    assert response.status_code == 200, response.text
    return response.json()


def _group(body: dict, kind: EquipmentType) -> list[dict]:
    """The holds listed under ``kind``."""
    found = [group for group in body["groups"] if group["equipment_type_code"] == kind.code]
    assert len(found) == 1, f"{kind.code} is not one group: {body['groups']}"
    return found[0]["holds"]


def _ids(body: dict, kind: EquipmentType) -> list[str]:
    return [hold["id"] for hold in _group(body, kind)]


def _active_types(db: Session) -> list[EquipmentType]:
    return list(
        db.scalars(
            select(EquipmentType)
            .where(EquipmentType.is_active.is_(True))
            .order_by(EquipmentType.name, EquipmentType.id)
        )
    )


def _listed_at(db: Session, kind: EquipmentType, now: datetime) -> list[uuid.UUID]:
    """The holds of ``kind`` the service lists at ``now``."""
    schedule = service.list_equipment_holds(
        db, type_code=kind.code, from_date=None, to_date=None, now=now
    )
    return [held.hold.id for held in schedule.groups[0].holds]


def _singapore_today() -> date:
    return datetime.now(SGT).date()


# =============================================================================================
# AC1 - every current hold, grouped by type, with its event, quantity, dates and status
# =============================================================================================
@pytest.mark.story("17.3", ac=1)
def test_every_active_type_is_a_group_by_name_and_listed_for_the_filter(tech_client, db: Session):
    make_equipment_type(db, name="Aaa holds kit")
    make_equipment_type(db, name="Zzz holds kit")
    active = [kind.code for kind in _active_types(db)]

    body = _schedule(tech_client)

    assert [group["equipment_type_code"] for group in body["groups"]] == active
    assert [kind["code"] for kind in body["types"]] == active


@pytest.mark.story("17.3", ac=1)
def test_types_sharing_a_name_keep_their_own_holds_in_a_fixed_order(tech_client, db: Session):
    """Only a type's code is unique, so two may share a name. Each keeps its own holds, and the
    two are listed by id, whichever has the earlier hold - their rows fall between each other when
    the listing sorts by start."""
    first = make_equipment_type(db, name="Twin kit", id=uuid.UUID(int=0x173A1))
    second = make_equipment_type(db, name="Twin kit", id=uuid.UUID(int=0x173A2))
    at = MIDNIGHT + 9 * HOUR
    second_early = _held(db, second, starts_at=at, ends_at=at + HOUR)
    first_between = _held(db, first, starts_at=at + HOUR, ends_at=at + 2 * HOUR)
    second_late = _held(db, second, starts_at=at + 2 * HOUR, ends_at=at + 3 * HOUR)

    groups = _schedule(tech_client)["groups"]

    twins = [group for group in groups if group["equipment_type_name"] == "Twin kit"]
    assert [
        (group["equipment_type_code"], [hold["id"] for hold in group["holds"]]) for group in twins
    ] == [
        (first.code, [str(first_between.id)]),
        (second.code, [str(second_early.id), str(second_late.id)]),
    ]


@pytest.mark.story("17.3", ac=1)
def test_each_hold_shows_its_event_quantity_dates_status_and_item(tech_client, db: Session):
    kit = make_equipment_type(db, name="Holds kit")
    hold = _on_the_day(db, kit, quantity=3, status="PENDING", name="Holds Expo")
    item = db.get(EventEquipmentRequest, hold.equipment_request_id)

    body = _schedule(tech_client)

    (listed,) = _group(body, kit)
    assert {key: listed[key] for key in ("id", "event_id", "event_name", "item_id")} == {
        "id": str(hold.id),
        "event_id": str(item.event_id),
        "event_name": "Holds Expo",
        "item_id": str(item.id),
    }
    assert (listed["quantity"], listed["status"]) == (3, "PENDING")
    assert datetime.fromisoformat(listed["starts_at"]) == MIDNIGHT + 9 * HOUR
    assert datetime.fromisoformat(listed["ends_at"]) == MIDNIGHT + 17 * HOUR
    group = next(each for each in body["groups"] if each["equipment_type_code"] == kit.code)
    assert group["equipment_type_name"] == "Holds kit"
    assert {"code": kit.code, "name": "Holds kit"} in body["types"]


@pytest.mark.story("17.3", ac=1)
def test_holds_are_listed_soonest_first_then_by_end_event_name_and_id(tech_client, db: Session):
    """Made in the reverse of the expected order, the two holds that tie on everything but id
    with fixed ids, so a list in the order rows were made cannot pass. Their events share a
    name, so each is another organiser's."""
    kit = make_equipment_type(db)
    at = MIDNIGHT + 9 * HOUR
    later_start = _held(db, kit, starts_at=at + HOUR, ends_at=at + 2 * HOUR, name="Aardvark Day")
    later_end = _held(db, kit, starts_at=at, ends_at=at + 9 * HOUR, name="Aardvark Fair")
    tie_second, tie_first = (
        _held(
            db,
            kit,
            starts_at=at,
            ends_at=at + 2 * HOUR,
            event=_event(
                db, starts_at=at, ends_at=at + 2 * HOUR, name="Gamma Fair", organiser_id=organiser
            ),
            hold_id=uuid.UUID(f"ffffffff-0000-0000-0000-00000000000{n}"),
        )
        for n, organiser in ((2, Users.ORGANISER.id), (1, Users.ORGANISER_2.id))
    )
    beta = _held(db, kit, starts_at=at, ends_at=at + 2 * HOUR, name="Beta Fair")
    alpha = _held(db, kit, starts_at=at, ends_at=at + 2 * HOUR, name="alpha Fair")

    listed = _ids(_schedule(tech_client), kit)

    assert listed == [
        str(hold.id) for hold in (alpha, beta, tie_first, tie_second, later_end, later_start)
    ]


@pytest.mark.story("17.3", ac=1)
def test_a_partly_released_hold_shows_the_units_it_still_holds(tech_client, db: Session):
    """The same count availability takes away (events.service.available_by_type)."""
    kit = make_equipment_type(db)
    _on_the_day(db, kit, quantity=5, released=2)

    (listed,) = _group(_schedule(tech_client), kit)

    assert listed["quantity"] == 3


# =============================================================================================
# AC2 - an item not yet sent already holds its units
# =============================================================================================
@pytest.mark.story("17.3", ac=2)
def test_a_not_yet_sent_items_hold_is_listed_beside_pending_and_accepted_ones(
    tech_client, db: Session
):
    kit = make_equipment_type(db)
    at = MIDNIGHT + 9 * HOUR
    waiting = _held(db, kit, starts_at=at, ends_at=at + HOUR, status="REQUESTED")
    pending = _held(db, kit, starts_at=at + HOUR, ends_at=at + 2 * HOUR, status="PENDING")
    accepted = _held(db, kit, starts_at=at + 2 * HOUR, ends_at=at + 3 * HOUR, status="ACCEPTED")

    listed = _group(_schedule(tech_client), kit)

    assert [(hold["id"], hold["status"]) for hold in listed] == [
        (str(waiting.id), "REQUESTED"),
        (str(pending.id), "PENDING"),
        (str(accepted.id), "ACCEPTED"),
    ]


# =============================================================================================
# AC3 - filtered by type and by date range
# =============================================================================================
@pytest.mark.story("17.3", ac=3)
def test_a_type_filter_gives_that_types_group_alone_and_still_every_type(tech_client, db: Session):
    kit, other = make_equipment_type(db), make_equipment_type(db)
    kept = _on_the_day(db, kit)
    _on_the_day(db, other)

    body = _schedule(tech_client, type_code=kit.code)

    assert [group["equipment_type_code"] for group in body["groups"]] == [kit.code]
    assert _ids(body, kit) == [str(kept.id)]
    assert [kind["code"] for kind in body["types"]] == [kind.code for kind in _active_types(db)]


@pytest.mark.story("17.3", ac=3)
def test_an_unknown_type_is_refused(tech_client):
    response = tech_client.get(HOLDS_PATH, params={"type": "NO_SUCH_KIT"})

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown equipment type: NO_SUCH_KIT."


@pytest.mark.story("17.3", ac=3)
def test_an_inactive_type_is_refused_and_never_listed(tech_client, db: Session):
    retired = make_equipment_type(db, is_active=False)
    _on_the_day(db, retired)

    response = tech_client.get(HOLDS_PATH, params={"type": retired.code})

    assert response.status_code == 422
    assert response.json()["detail"] == f"Unknown equipment type: {retired.code}."
    body = _schedule(tech_client)
    assert retired.code not in [kind["code"] for kind in body["types"]]
    assert retired.code not in [group["equipment_type_code"] for group in body["groups"]]


@pytest.mark.story("17.3", ac=3)
@pytest.mark.parametrize(
    "params",
    [
        {"from": "2032-02-30"},
        {"to": "20320-03-10"},
        {"from": "tomorrow"},
        {"to": "2032-3-10T09:00"},
        {"type": ""},
    ],
    ids=["no such day", "five-digit year", "not a date", "a time too", "a blank type"],
)
def test_a_filter_that_is_not_a_date_or_a_type_is_refused(tech_client, params):
    assert tech_client.get(HOLDS_PATH, params=params).status_code == 422


@pytest.mark.story("17.3", ac=3)
def test_a_range_lists_every_hold_with_any_part_in_it(tech_client, db: Session):
    kit = make_equipment_type(db)
    night_before = MIDNIGHT - 4 * HOUR
    starts_before = _held(db, kit, starts_at=night_before, ends_at=MIDNIGHT + 2 * HOUR)
    ends_after = _held(db, kit, starts_at=MIDNIGHT + 22 * HOUR, ends_at=MIDNIGHT + 34 * HOUR)
    spans = _held(db, kit, starts_at=MIDNIGHT - DAY, ends_at=MIDNIGHT + 2 * DAY)
    inside = _on_the_day(db, kit)
    _held(db, kit, starts_at=MIDNIGHT - 15 * HOUR, ends_at=MIDNIGHT - 7 * HOUR)  # wholly before
    _held(db, kit, starts_at=MIDNIGHT + 33 * HOUR, ends_at=MIDNIGHT + 41 * HOUR)  # wholly after

    listed = _ids(_schedule(tech_client, from_date=THE_DAY, to_date=THE_DAY), kit)

    assert sorted(listed) == sorted(
        str(hold.id) for hold in (starts_before, ends_after, spans, inside)
    )


@pytest.mark.story("17.3", ac=3)
def test_a_range_shares_no_moment_with_a_hold_that_only_touches_it(tech_client, db: Session):
    """Holds run up to their end, not including it, as availability counts them: one ending at
    00:00 on the range's first day, or starting at 00:00 after its last, shares no moment with
    it. A minute further in, each does."""
    kit = make_equipment_type(db)
    next_midnight = MIDNIGHT + DAY
    _held(db, kit, starts_at=MIDNIGHT - 4 * HOUR, ends_at=MIDNIGHT)
    ends_a_minute_in = _held(
        db, kit, starts_at=MIDNIGHT - 4 * HOUR, ends_at=MIDNIGHT + timedelta(minutes=1)
    )
    _held(db, kit, starts_at=next_midnight, ends_at=next_midnight + 4 * HOUR)
    starts_a_minute_before = _held(
        db, kit, starts_at=next_midnight - timedelta(minutes=1), ends_at=next_midnight + 4 * HOUR
    )

    listed = _ids(_schedule(tech_client, from_date=THE_DAY, to_date=THE_DAY), kit)

    assert sorted(listed) == sorted(
        str(hold.id) for hold in (ends_a_minute_in, starts_a_minute_before)
    )


@pytest.mark.story("17.3", ac=3)
def test_a_ranges_days_are_singapore_days(tech_client, db: Session):
    """07:30 SGT on THE_DAY is 23:30 UTC the day before: in a range of THE_DAY, not of the day
    before."""
    kit = make_equipment_type(db)
    morning = _held(db, kit, starts_at=MIDNIGHT + 7.5 * HOUR, ends_at=MIDNIGHT + 8.5 * HOUR)

    on_the_day = _ids(_schedule(tech_client, from_date=THE_DAY, to_date=THE_DAY), kit)
    day_before = _ids(_schedule(tech_client, from_date=DAY_BEFORE, to_date=DAY_BEFORE), kit)

    assert (on_the_day, day_before) == ([str(morning.id)], [])


@pytest.mark.story("17.3", ac=3)
def test_a_side_of_the_range_left_out_leaves_it_open(tech_client, db: Session):
    kit = make_equipment_type(db)
    before = _held(db, kit, starts_at=MIDNIGHT - DAY + 9 * HOUR, ends_at=MIDNIGHT - DAY + 17 * HOUR)
    after = _held(db, kit, starts_at=MIDNIGHT + DAY + 9 * HOUR, ends_at=MIDNIGHT + DAY + 17 * HOUR)

    from_the_day = _ids(_schedule(tech_client, from_date=THE_DAY), kit)
    to_the_day = _ids(_schedule(tech_client, to_date=THE_DAY), kit)

    assert (from_the_day, to_the_day) == ([str(after.id)], [str(before.id)])


@pytest.mark.story("17.3", ac=3)
@pytest.mark.parametrize("from_date", [None, THE_DAY], ids=["to alone", "from and to"])
def test_a_range_ending_on_the_last_day_there_is_is_read(tech_client, db: Session, from_date):
    """31 December 9999 is a date the page can send, and no day follows it: the range is read as
    open at its end, not refused or failed."""
    kit = make_equipment_type(db)
    hold = _on_the_day(db, kit)

    body = _schedule(tech_client, from_date=from_date, to_date=date.max)

    assert _ids(body, kit) == [str(hold.id)]


@pytest.mark.story("17.3", ac=3)
@pytest.mark.parametrize(
    ("days", "detail"),
    [
        ({"from": -1}, START_BEFORE_TODAY),
        ({"from": 1, "to": 0}, END_BEFORE_START),
        ({"to": -1}, END_BEFORE_TODAY),
    ],
    ids=["from yesterday", "to before from", "to yesterday"],
)
def test_a_range_reaching_before_today_is_refused_with_why(tech_client, days, detail):
    today = _singapore_today()
    params = {key: str(today + offset * DAY) for key, offset in days.items()}

    response = tech_client.get(HOLDS_PATH, params=params)

    assert response.status_code == 422
    assert response.json()["detail"] == detail


@pytest.mark.story("17.3", ac=3)
def test_a_range_of_today_alone_is_accepted(tech_client):
    today = str(_singapore_today())

    response = tech_client.get(HOLDS_PATH, params={"from": today, "to": today})

    assert response.status_code == 200, response.text


# =============================================================================================
# AC4 - each sent hold opens its equipment request page
# =============================================================================================
@pytest.mark.story("17.3", ac=4)
@pytest.mark.parametrize("status", ["PENDING", "ACCEPTED"])
def test_a_sent_holds_item_is_the_request_its_page_reads(tech_client, db: Session, status):
    kit = make_equipment_type(db)
    hold = _on_the_day(db, kit, status=status)
    (listed,) = _group(_schedule(tech_client), kit)

    response = tech_client.get(f"/equipment-requests/{listed['item_id']}")

    assert response.status_code == 200, response.text
    request = response.json()
    assert (request["event_id"], request["equipment_type_code"], request["status"]) == (
        str(hold.event_id),
        kit.code,
        status,
    )


@pytest.mark.story("17.3", ac=4)
def test_a_not_yet_sent_holds_item_has_no_request_page(tech_client, db: Session):
    """16.1 AC7: a request not yet sent is not Technical Support's, so its page is not found."""
    kit = make_equipment_type(db)
    _on_the_day(db, kit, status="REQUESTED")
    (listed,) = _group(_schedule(tech_client), kit)

    response = tech_client.get(f"/equipment-requests/{listed['item_id']}")

    assert response.status_code == 404


# =============================================================================================
# AC5 - only holds that haven't ended, and only what is still held
# =============================================================================================
@pytest.mark.story("17.3", ac=5)
def test_a_hold_is_listed_until_the_moment_it_ends(db: Session):
    kit = make_equipment_type(db)
    now = MIDNIGHT + 12 * HOUR
    _held(db, kit, starts_at=now - 4 * HOUR, ends_at=now - HOUR)  # ended
    _held(db, kit, starts_at=now - 3 * HOUR, ends_at=now)  # ends exactly now
    under_way = _held(db, kit, starts_at=now - HOUR, ends_at=now + timedelta(microseconds=1))
    to_come = _held(db, kit, starts_at=now + 2 * HOUR, ends_at=now + 3 * HOUR)

    assert _listed_at(db, kit, now) == [under_way.id, to_come.id]


@pytest.mark.story("17.3", ac=5)
def test_a_hold_kept_past_its_corrected_events_end_is_listed_until_the_hold_ends(db: Session):
    """CL-210. A 7.2 correction that ends the event at 13:00, inside its hold of 09:00-17:00, keeps
    the hold as it was (tests/events/test_correct_event_under_review.py::
    test_shortening_the_dates_inside_the_holds_keeps_the_accepted_equipment), so its units stay
    taken until 17:00: the schedule shows it until then, as availability counts it."""
    kit = make_equipment_type(db)
    nine = MIDNIGHT + 9 * HOUR
    event = _event(db, starts_at=nine, ends_at=nine + 4 * HOUR)
    hold = _held(db, kit, starts_at=nine, ends_at=nine + 8 * HOUR, event=event)

    assert _listed_at(db, kit, nine + 5 * HOUR) == [hold.id]
    assert _listed_at(db, kit, nine + 8 * HOUR) == []


@pytest.mark.story("17.3", ac=5)
def test_a_released_hold_is_not_listed(tech_client, db: Session):
    kit = make_equipment_type(db)
    hold = _on_the_day(db, kit, quantity=2, released=2)
    hold.status = "RELEASED"
    db.flush()

    assert _group(_schedule(tech_client), kit) == []


@pytest.mark.story("17.3", ac=5)
@pytest.mark.parametrize("status", ["DECLINED", "CANCELLED", "WITHDRAWN", "UNAVAILABLE"])
def test_an_item_that_holds_nothing_is_not_listed_even_with_a_hold_left_behind(
    tech_client, db: Session, status
):
    """Every write releases an item's hold as it moves to one of these (the next test proves it
    through each endpoint), so a reserved hold should never be left on one. Should one be, the
    schedule still lists only items that hold units - not yet sent, Pending or Accepted."""
    kit = make_equipment_type(db)
    _on_the_day(db, kit, status=status)

    assert _group(_schedule(tech_client), kit) == []


def _decline(login_as, item: EventEquipmentRequest):
    return login_as(Users.TECH_SUPPORT).post(
        f"/equipment-requests/{item.id}/decision",
        json={"outcome": "DECLINED", "reason": "Every unit is booked that week."},
    )


def _withdraw(login_as, item: EventEquipmentRequest):
    return login_as(Users.COORDINATOR).post(
        f"/events/{item.event_id}/equipment/{item.id}/withdrawal",
        json={"expected_status": item.status},
    )


def _remove(login_as, item: EventEquipmentRequest):
    return login_as(Users.COORDINATOR).delete(f"/events/{item.event_id}/equipment/{item.id}")


def _cancel(login_as, item: EventEquipmentRequest):
    return login_as(Users.ORGANISER).post(
        f"/events/{item.event_id}/cancel", json={"reason": "The launch moved to next year."}
    )


@pytest.mark.story("17.3", ac=5)
@pytest.mark.parametrize(
    ("status", "act"),
    [
        ("PENDING", _decline),
        ("ACCEPTED", _withdraw),
        ("REQUESTED", _remove),
        ("ACCEPTED", _cancel),
    ],
    ids=["declined (16.1)", "withdrawn (17.2)", "removed (15.1)", "event cancelled (6.2)"],
)
def test_a_hold_its_item_gives_up_leaves_the_schedule_at_once(login_as, db: Session, status, act):
    kit = make_equipment_type(db)
    hold = _on_the_day(db, kit, status=status)
    item = db.get(EventEquipmentRequest, hold.equipment_request_id)
    assert _ids(_schedule(login_as(Users.TECH_SUPPORT)), kit) == [str(hold.id)]

    response = act(login_as, item)

    assert response.status_code < 300, response.text
    assert _group(_schedule(login_as(Users.TECH_SUPPORT)), kit) == []


# =============================================================================================
# AC6 - a type with no holds in the range says so
# =============================================================================================
@pytest.mark.story("17.3", ac=6)
def test_a_type_with_no_holds_in_the_range_is_still_listed_with_none(tech_client, db: Session):
    kit = make_equipment_type(db)
    _on_the_day(db, kit)

    body = _schedule(tech_client, from_date=DAY_AFTER, to_date=DAY_AFTER)

    assert _group(body, kit) == []


@pytest.mark.story("17.3", ac=6)
def test_a_type_with_no_holds_at_all_is_listed_with_none(tech_client, db: Session):
    kit = make_equipment_type(db)

    assert _group(_schedule(tech_client), kit) == []
    assert _group(_schedule(tech_client, type_code=kit.code), kit) == []


# =============================================================================================
# AC7 - Technical Support only
# =============================================================================================
@pytest.mark.story("17.3", ac=7)
@pytest.mark.parametrize(
    "user",
    [user for user in Users.ONE_PER_ROLE if user != Users.TECH_SUPPORT],
    ids=lambda user: user.role,
)
def test_every_other_role_is_refused(login_as, user):
    assert login_as(user).get(HOLDS_PATH).status_code == 403


@pytest.mark.story("17.3", ac=7)
def test_signed_out_is_refused(client):
    assert client.get(HOLDS_PATH).status_code == 401


@pytest.mark.story("17.3", ac=7)
def test_technical_support_may_read_it(tech_client):
    assert tech_client.get(HOLDS_PATH).status_code == 200


# =============================================================================================
# Definition of done - one read, however many types and holds
# =============================================================================================
def _statements_reading(client, db: Session, *, types: int) -> int:
    """How many SQL statements ``GET /equipment-holds`` runs once ``types`` more types each have a
    hold."""
    for _ in range(types):
        _on_the_day(db, make_equipment_type(db))
    db.commit()  # expires every row, so the read loads them all, as a fresh request does
    executed: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        executed.append(statement)

    connection = db.connection()
    sqlalchemy_event.listen(connection, "before_cursor_execute", record)
    try:
        _schedule(client)
    finally:
        sqlalchemy_event.remove(connection, "before_cursor_execute", record)
    return len(executed)


@pytest.mark.story("17.3", ac=1)
def test_the_schedule_is_read_in_as_many_statements_whatever_the_number_of_types(
    tech_client, db: Session
):
    one = _statements_reading(tech_client, db, types=1)
    four_more = _statements_reading(tech_client, db, types=4)

    assert four_more == one
