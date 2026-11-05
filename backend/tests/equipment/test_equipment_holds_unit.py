"""Story 17.3 - view the equipment holds schedule as Technical Support. UNIT tests: the rules on
their own.

Level: unit. Each test calls a pure function of ``app/equipment/service.py`` - which day it is in
Singapore, the period a date range covers, which ranges are refused, and how the listing's rows fall
into groups - with no database, no HTTP and no fixture. ``test_equipment_holds_integration.py``
proves the API applies them to real holds; the page Technical Support clicks through is e2e-tested
in ``tests/e2e/equipment-holds.spec.ts``.

AC1 The Equipment holds page groups every current hold by equipment type. Under each type, each
    hold shows the event name, the quantity, the dates it runs from and to, and whether it is not
    yet sent, Pending or Accepted. Holds are listed soonest first. (Here: how the rows fall into
    groups, kept in the order the listing gives them, and the units a hold still holds.)
AC3 It can be filtered by equipment type and by date range. A hold is shown when any part of it
    falls in the range. The range can't start before today, since past holds are not listed
    (AC5). (Here: today and the range's days are Singapore's, the period a range covers, its
    three refusals, and the type filter's group.)
AC6 A type with no holds in the range says so. (Here: such a type stays, as a group with none.)

Story 16.2 AC9 (fix f16.2.2): each hold on the schedule is marked short by the units 16.2 AC4
marks on its event. (Here: each hold carries the shortfall it is given, and none when it has none.)
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.equipment import service
from app.equipment.service import HoldRow, HoldWindow
from app.events.models import EquipmentReservation, EquipmentType

SGT = timezone(timedelta(hours=8))
TODAY = date(2026, 11, 2)
DAY = timedelta(days=1)
# AC3's refusals, written out so a red run shows what the function says instead.
START_BEFORE_TODAY = "The start date cannot be before today."
END_BEFORE_START = "The end date cannot be before the start date."
END_BEFORE_TODAY = "The end date cannot be before today."
# Fix f16.2.2: no hold is short, as with no unit out of service.
NONE_SHORT: dict[uuid.UUID, int] = {}


def _type(code: str) -> EquipmentType:
    return EquipmentType(id=uuid.uuid4(), code=code, name=code.title(), is_active=True)


def _hold(kind: EquipmentType, *, quantity: int = 2, released: int = 0) -> EquipmentReservation:
    return EquipmentReservation(
        id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        equipment_request_id=uuid.uuid4(),
        equipment_type_id=kind.id,
        quantity=quantity,
        released_quantity=released,
        starts_at=datetime(2031, 4, 9, 9, 0, tzinfo=SGT),
        ends_at=datetime(2031, 4, 9, 17, 0, tzinfo=SGT),
        status="RESERVED",
    )


def _row(
    kind: EquipmentType,
    hold: EquipmentReservation | None = None,
    *,
    event_name: str = "Bayfront Product Showcase",
    item_status: str = "ACCEPTED",
) -> HoldRow:
    """One row of the listing: ``kind`` and one of its holds, or ``kind`` alone when none of its
    holds matched, as the outer join gives it."""
    if hold is None:
        return HoldRow(equipment_type=kind, hold=None, event_name=None, item_status=None)
    return HoldRow(equipment_type=kind, hold=hold, event_name=event_name, item_status=item_status)


# =============================================================================================
# AC3 - today is Singapore's day
# =============================================================================================
@pytest.mark.story("17.3", ac=3)
@pytest.mark.parametrize(
    ("now", "today"),
    [
        (datetime(2026, 11, 2, 16, 30, tzinfo=UTC), date(2026, 11, 3)),
        (datetime(2026, 11, 2, 16, 0, tzinfo=UTC), date(2026, 11, 3)),
        (datetime(2026, 11, 2, 15, 59, 59, 999999, tzinfo=UTC), date(2026, 11, 2)),
        (datetime(2026, 11, 2, 23, 59, tzinfo=SGT), date(2026, 11, 2)),
    ],
    ids=[
        "00:30 SGT on the 3rd is still the 2nd in UTC",
        "midnight SGT starts the 3rd",
        "the last moment of the 2nd SGT",
        "a Singapore time is read as it is",
    ],
)
def test_today_is_the_day_in_singapore(now, today):
    assert service.singapore_today(now) == today


# =============================================================================================
# AC3 - the period a range covers
# =============================================================================================
@pytest.mark.story("17.3", ac=3)
def test_a_range_runs_from_midnight_on_its_first_day_to_midnight_after_its_last():
    window = service.hold_window(date(2031, 4, 9), date(2031, 4, 10))

    assert window == HoldWindow(
        starts_at=datetime(2031, 4, 9, 0, 0, tzinfo=SGT),
        ends_at=datetime(2031, 4, 11, 0, 0, tzinfo=SGT),
    )


@pytest.mark.story("17.3", ac=3)
def test_a_range_of_one_day_covers_that_whole_day():
    window = service.hold_window(date(2031, 4, 9), date(2031, 4, 9))

    assert window == HoldWindow(
        starts_at=datetime(2031, 4, 9, 0, 0, tzinfo=SGT),
        ends_at=datetime(2031, 4, 10, 0, 0, tzinfo=SGT),
    )


@pytest.mark.story("17.3", ac=3)
@pytest.mark.parametrize(
    ("last_day", "next_midnight"),
    [
        (date(2030, 12, 31), datetime(2031, 1, 1, 0, 0, tzinfo=SGT)),
        (date(2031, 4, 30), datetime(2031, 5, 1, 0, 0, tzinfo=SGT)),
        (date(2031, 2, 28), datetime(2031, 3, 1, 0, 0, tzinfo=SGT)),
        (date(2032, 2, 28), datetime(2032, 2, 29, 0, 0, tzinfo=SGT)),
    ],
    ids=["year end", "month end", "February", "leap February"],
)
def test_a_range_ending_on_a_months_last_day_runs_into_the_next(last_day, next_midnight):
    assert service.hold_window(date(2030, 12, 1), last_day).ends_at == next_midnight


@pytest.mark.story("17.3", ac=3)
def test_a_side_left_out_leaves_the_range_open_on_that_side():
    assert service.hold_window(date(2031, 4, 9), None) == HoldWindow(
        starts_at=datetime(2031, 4, 9, 0, 0, tzinfo=SGT), ends_at=None
    )
    assert service.hold_window(None, date(2031, 4, 9)) == HoldWindow(
        starts_at=None, ends_at=datetime(2031, 4, 10, 0, 0, tzinfo=SGT)
    )
    assert service.hold_window(None, None) == HoldWindow(starts_at=None, ends_at=None)


@pytest.mark.story("17.3", ac=3)
def test_a_range_ending_on_the_last_day_there_is_is_open_at_its_end():
    """No day follows 31 December 9999, so there is no midnight after it to end on."""
    assert service.hold_window(date(2031, 4, 9), date.max) == HoldWindow(
        starts_at=datetime(2031, 4, 9, 0, 0, tzinfo=SGT), ends_at=None
    )
    assert service.hold_window(None, date.max) == HoldWindow(starts_at=None, ends_at=None)


# =============================================================================================
# AC3 - which ranges are refused
# =============================================================================================
@pytest.mark.story("17.3", ac=3)
@pytest.mark.parametrize(
    ("from_date", "to_date"),
    [
        (TODAY, None),
        (TODAY, TODAY),
        (TODAY, TODAY + DAY),
        (None, TODAY),
        (TODAY + DAY, TODAY + DAY),
        (None, None),
    ],
    ids=[
        "from today",
        "today alone",
        "from today to tomorrow",
        "to today",
        "tomorrow alone",
        "no range",
    ],
)
def test_a_range_from_today_on_is_accepted(from_date, to_date):
    service.check_hold_range(from_date, to_date, today=TODAY)


@pytest.mark.story("17.3", ac=3)
def test_a_start_before_today_is_refused():
    with pytest.raises(service.InvalidHoldRange) as refused:
        service.check_hold_range(TODAY - DAY, None, today=TODAY)

    assert str(refused.value) == START_BEFORE_TODAY


@pytest.mark.story("17.3", ac=3)
def test_an_end_before_the_start_is_refused():
    with pytest.raises(service.InvalidHoldRange) as refused:
        service.check_hold_range(TODAY + DAY, TODAY, today=TODAY)

    assert str(refused.value) == END_BEFORE_START


@pytest.mark.story("17.3", ac=3)
def test_with_no_start_an_end_before_today_is_refused():
    with pytest.raises(service.InvalidHoldRange) as refused:
        service.check_hold_range(None, TODAY - DAY, today=TODAY)

    assert str(refused.value) == END_BEFORE_TODAY


@pytest.mark.story("17.3", ac=3)
def test_a_start_before_today_is_named_before_an_end_before_it():
    with pytest.raises(service.InvalidHoldRange) as refused:
        service.check_hold_range(TODAY - DAY, TODAY - 2 * DAY, today=TODAY)

    assert str(refused.value) == START_BEFORE_TODAY


# =============================================================================================
# AC1 / AC6 - the rows fall into one group per type
# =============================================================================================
@pytest.mark.story("17.3", ac=1)
@pytest.mark.story("17.3", ac=6)
def test_the_rows_fall_into_one_group_per_type_in_the_order_given():
    laptops, mics, speakers = _type("LAPTOP"), _type("WIRELESS_MIC"), _type("SPEAKER_SET")
    first_laptops, first_mics, second_mics = _hold(laptops), _hold(mics), _hold(mics)

    schedule = service.group_holds(
        [
            _row(laptops, first_laptops),
            _row(mics, first_mics),
            _row(mics, second_mics),
            _row(speakers),
        ],
        type_code=None,
        units_short=NONE_SHORT,
    )

    assert schedule.types == [laptops, mics, speakers]
    assert [group.equipment_type for group in schedule.groups] == [laptops, mics, speakers]
    assert [[held.hold for held in group.holds] for group in schedule.groups] == [
        [first_laptops],
        [first_mics, second_mics],
        [],
    ]


@pytest.mark.story("17.3", ac=1)
def test_each_hold_keeps_its_event_and_its_items_status():
    mics = _type("WIRELESS_MIC")
    hold = _hold(mics)

    schedule = service.group_holds(
        [_row(mics, hold, event_name="Harbour Expo", item_status="PENDING")],
        type_code=None,
        units_short=NONE_SHORT,
    )

    (held,) = schedule.groups[0].holds
    assert (held.hold, held.event_name, held.item_status) == (hold, "Harbour Expo", "PENDING")


@pytest.mark.story("17.3", ac=1)
@pytest.mark.parametrize(("quantity", "released", "units"), [(5, 0, 5), (5, 2, 3), (1, 0, 1)])
def test_a_hold_counts_the_units_it_has_not_released(quantity, released, units):
    mics = _type("WIRELESS_MIC")

    schedule = service.group_holds(
        [_row(mics, _hold(mics, quantity=quantity, released=released))],
        type_code=None,
        units_short=NONE_SHORT,
    )

    assert schedule.groups[0].holds[0].units == units


@pytest.mark.story("16.2", ac=9)
def test_each_hold_carries_the_units_it_is_short_and_none_when_it_is_whole():
    mics = _type("WIRELESS_MIC")
    short, whole = _hold(mics, quantity=3), _hold(mics)

    schedule = service.group_holds(
        [_row(mics, short), _row(mics, whole)], type_code=None, units_short={short.id: 2}
    )

    assert [held.units_short for held in schedule.groups[0].holds] == [2, 0]


@pytest.mark.story("17.3", ac=1)
def test_with_no_active_types_there_are_no_groups():
    schedule = service.group_holds([], type_code=None, units_short=NONE_SHORT)

    assert (schedule.types, schedule.groups) == ([], [])


# =============================================================================================
# AC3 - the type filter keeps that type's group, and every type for the filter
# =============================================================================================
@pytest.mark.story("17.3", ac=3)
def test_a_type_filter_keeps_only_that_types_group_and_every_type():
    laptops, mics = _type("LAPTOP"), _type("WIRELESS_MIC")
    hold = _hold(mics)

    schedule = service.group_holds(
        [_row(laptops), _row(mics, hold)], type_code="WIRELESS_MIC", units_short=NONE_SHORT
    )

    assert schedule.types == [laptops, mics]
    assert [group.equipment_type for group in schedule.groups] == [mics]
    assert [held.hold for held in schedule.groups[0].holds] == [hold]


@pytest.mark.story("17.3", ac=6)
def test_a_filtered_type_with_no_holds_is_still_its_group():
    laptops, mics = _type("LAPTOP"), _type("WIRELESS_MIC")

    schedule = service.group_holds(
        [_row(laptops, _hold(laptops)), _row(mics)],
        type_code="WIRELESS_MIC",
        units_short=NONE_SHORT,
    )

    assert [(group.equipment_type, group.holds) for group in schedule.groups] == [(mics, [])]


@pytest.mark.story("17.3", ac=3)
def test_a_type_filter_naming_no_listed_type_is_refused():
    with pytest.raises(service.UnknownEquipmentType) as refused:
        service.group_holds(
            [_row(_type("LAPTOP"))], type_code="NO_SUCH_KIT", units_short=NONE_SHORT
        )

    assert str(refused.value) == "Unknown equipment type: NO_SUCH_KIT."
