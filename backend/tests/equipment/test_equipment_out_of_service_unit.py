"""Story 16.2 - mark equipment out of service. UNIT tests: the rules on their own.

Level: unit. Each test calls a pure function of ``app/equipment/service.py`` - how many units
records have out of service at once, which holds a shortage leaves short, whether a start is in
the past - or builds a request model of ``app/equipment/schemas.py``, with no database, no HTTP and
no fixture. ``test_equipment_out_of_service_integration.py`` proves the API applies them; the flows
Technical Support and a coordinator click through are e2e-tested in
``tests/e2e/equipment-out-of-service.spec.ts``.

AC1 Technical Support records units of an equipment type as out of service: how many, why
    (Damaged, Under maintenance, Lost or Other), an optional note, from when and, optionally,
    until when (left blank: until ended). (Here: what a record may hold.)
AC3 The quantity is a whole number from 1 up to the stock less the units other records already
    have out at any moment of its period. The end must be after the start; the start cannot be in
    the past. (Here: the units out at any one moment, the start's rule and the schema's checks.)
AC4 When the units left cannot cover the holds on that type over the period, the holds that
    cannot be covered - the most recently placed first, so earlier ones keep their units - are
    short. Only the part still to come counts. (Here: which holds, and by how many units.)
AC7 Records that overlap in time add up. (Here: as counted; the locking is an integration case.)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.equipment import schemas, service
from app.equipment.service import HeldUnits, OutOfServiceWindow

NOW = datetime(2030, 3, 1, 9, 30, 15, tzinfo=UTC)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


def _at(hours: float) -> datetime:
    """A moment ``hours`` after NOW (before it, when negative)."""
    return NOW + timedelta(hours=hours)


def _record(start: float, end: float | None, quantity: int) -> OutOfServiceWindow:
    return OutOfServiceWindow(
        starts_at=_at(start), ends_at=None if end is None else _at(end), quantity=quantity
    )


def _hold(start: float, end: float, units: int, *, placed: float = -100.0, hold_id=None):
    return HeldUnits(
        hold_id=hold_id or uuid.uuid4(),
        units=units,
        starts_at=_at(start),
        ends_at=_at(end),
        placed_at=_at(placed),
    )


# =============================================================================================
# AC3 / AC7 - the units records have out of service at any one moment of a period
# =============================================================================================
@pytest.mark.story("16.2", ac=3)
def test_with_no_records_no_units_are_out():
    assert service.units_out_at_most([], starts_at=_at(1), ends_at=_at(5)) == 0


@pytest.mark.story("16.2", ac=3)
def test_a_record_covering_the_period_counts_its_units():
    records = [_record(0, 10, 3)]

    assert service.units_out_at_most(records, starts_at=_at(1), ends_at=_at(5)) == 3


@pytest.mark.story("16.2", ac=7)
def test_overlapping_records_add_up():
    records = [_record(0, 10, 3), _record(2, 6, 2)]

    assert service.units_out_at_most(records, starts_at=_at(1), ends_at=_at(5)) == 5


@pytest.mark.story("16.2", ac=7)
def test_records_one_after_another_count_the_larger_not_their_sum():
    """They are never out at the same moment, so the period can spare the larger of the two."""
    records = [_record(1, 2, 3), _record(3, 4, 2)]

    assert service.units_out_at_most(records, starts_at=_at(0), ends_at=_at(5)) == 3


@pytest.mark.story("16.2", ac=7)
def test_a_record_starting_inside_the_period_counts_from_its_start():
    records = [_record(0, 10, 1), _record(4, 8, 4)]

    assert service.units_out_at_most(records, starts_at=_at(1), ends_at=_at(5)) == 5


@pytest.mark.story("16.2", ac=3)
def test_a_record_ending_as_the_period_starts_does_not_count():
    """Half-open, as holds are: the record's last moment is just before the period's first."""
    records = [_record(0, 2, 4)]

    assert service.units_out_at_most(records, starts_at=_at(2), ends_at=_at(5)) == 0


@pytest.mark.story("16.2", ac=3)
def test_a_record_starting_as_the_period_ends_does_not_count():
    records = [_record(5, 9, 4)]

    assert service.units_out_at_most(records, starts_at=_at(2), ends_at=_at(5)) == 0


@pytest.mark.story("16.2", ac=3)
def test_a_record_starting_just_before_the_period_ends_counts():
    records = [_record(4.9, 9, 4)]

    assert service.units_out_at_most(records, starts_at=_at(2), ends_at=_at(5)) == 4


@pytest.mark.story("16.2", ac=3)
def test_an_open_ended_record_counts_however_late_the_period():
    records = [_record(0, None, 2)]

    assert service.units_out_at_most(records, starts_at=_at(1000), ends_at=_at(1001)) == 2


@pytest.mark.story("16.2", ac=3)
def test_an_open_ended_period_counts_a_record_starting_any_time_after_it():
    records = [_record(500, 501, 2), _record(0, 1, 1)]

    assert service.units_out_at_most(records, starts_at=_at(2), ends_at=None) == 2


# =============================================================================================
# AC4 - the holds a shortage leaves short, first come first served, from now on
# =============================================================================================
@pytest.mark.story("16.2", ac=4)
def test_holds_the_units_left_can_cover_are_not_short():
    holds = [_hold(10, 12, 2), _hold(10, 12, 1)]

    assert service.short_units(stock=4, holds=holds, records=[_record(0, 20, 1)], now=NOW) == {}


@pytest.mark.story("16.2", ac=4)
def test_a_hold_the_units_left_cannot_cover_is_short_by_what_is_missing():
    hold = _hold(10, 12, 3)

    short = service.short_units(stock=3, holds=[hold], records=[_record(0, 20, 1)], now=NOW)

    assert short == {hold.hold_id: 1}


@pytest.mark.story("16.2", ac=4)
def test_the_hold_placed_last_is_short_first_and_the_earlier_keeps_its_units():
    earlier = _hold(10, 12, 2, placed=-50)
    later = _hold(10, 12, 2, placed=-10)

    short = service.short_units(
        stock=4, holds=[later, earlier], records=[_record(0, 20, 1)], now=NOW
    )

    assert short == {later.hold_id: 1}


@pytest.mark.story("16.2", ac=4)
def test_holds_placed_at_the_same_moment_are_served_in_id_order():
    first, second = sorted((uuid.uuid4(), uuid.uuid4()))
    holds = [_hold(10, 12, 2, hold_id=second), _hold(10, 12, 2, hold_id=first)]

    short = service.short_units(stock=3, holds=holds, records=[], now=NOW)

    assert short == {second: 1}


@pytest.mark.story("16.2", ac=4)
def test_a_hold_short_of_every_unit_is_short_by_all_of_them_and_no_more():
    hold = _hold(10, 12, 2)

    short = service.short_units(stock=2, holds=[hold], records=[_record(0, 20, 3)], now=NOW)

    assert short == {hold.hold_id: 2}


@pytest.mark.story("16.2", ac=4)
def test_an_earlier_hold_starting_later_still_comes_first_once_it_starts():
    """The later-placed hold has the units to itself until the earlier one's period begins."""
    earlier = _hold(11, 14, 2, placed=-50)
    later = _hold(10, 13, 2, placed=-10)

    short = service.short_units(stock=3, holds=[earlier, later], records=[], now=NOW)

    assert short == {later.hold_id: 1}


@pytest.mark.story("16.2", ac=4)
def test_a_record_starting_part_way_through_a_hold_leaves_it_short_from_then():
    hold = _hold(10, 14, 3)

    short = service.short_units(stock=3, holds=[hold], records=[_record(12, 20, 2)], now=NOW)

    assert short == {hold.hold_id: 2}


@pytest.mark.story("16.2", ac=4)
def test_the_most_a_hold_is_short_by_is_what_it_is_short():
    hold = _hold(10, 14, 3)
    records = [_record(10, 11, 1), _record(12, 13, 2)]

    assert service.short_units(stock=3, holds=[hold], records=records, now=NOW) == {hold.hold_id: 2}


@pytest.mark.story("16.2", ac=4)
def test_a_shortfall_that_eases_later_keeps_its_worst():
    hold = _hold(10, 14, 3)
    records = [_record(10, 11, 2), _record(12, 13, 1)]

    assert service.short_units(stock=3, holds=[hold], records=records, now=NOW) == {hold.hold_id: 2}


@pytest.mark.story("16.2", ac=4)
def test_a_record_that_does_not_overlap_a_hold_leaves_it_whole():
    hold = _hold(10, 12, 3)
    records = [_record(0, 10, 3), _record(12, 20, 3)]

    assert service.short_units(stock=3, holds=[hold], records=records, now=NOW) == {}


@pytest.mark.story("16.2", ac=4)
def test_an_open_ended_record_leaves_any_later_hold_short():
    hold = _hold(1000, 1002, 3)

    short = service.short_units(stock=3, holds=[hold], records=[_record(0, None, 1)], now=NOW)

    assert short == {hold.hold_id: 1}


@pytest.mark.story("16.2", ac=4)
def test_only_what_is_still_to_come_counts():
    """A hold under way is short only by what the records take from now on: the record that ended
    a moment ago leaves nothing short, the one in force does."""
    hold = _hold(-2, 2, 3)

    assert service.short_units(stock=3, holds=[hold], records=[_record(-2, 0, 2)], now=NOW) == {}
    assert service.short_units(stock=3, holds=[hold], records=[_record(-2, 1, 2)], now=NOW) == {
        hold.hold_id: 2
    }


@pytest.mark.story("16.2", ac=4)
def test_a_hold_under_way_is_short_at_once_when_a_record_is_in_force_now():
    hold = _hold(-1, 1, 2)

    short = service.short_units(stock=2, holds=[hold], records=[_record(-5, None, 1)], now=NOW)

    assert short == {hold.hold_id: 1}


# =============================================================================================
# AC3 - a start in the past
# =============================================================================================
@pytest.mark.story("16.2", ac=3)
def test_a_start_in_the_current_minute_is_not_in_the_past():
    """A form that starts the record now sends the minute it was filled in, seconds ago."""
    assert service.starts_in_the_past(NOW.replace(second=0), now=NOW) is False
    assert service.starts_in_the_past(NOW + HOUR, now=NOW) is False


@pytest.mark.story("16.2", ac=3)
def test_a_start_before_the_current_minute_is_in_the_past():
    assert service.starts_in_the_past(NOW.replace(second=0) - timedelta(seconds=1), now=NOW)


# =============================================================================================
# AC1 / AC3 - what a record may hold, as sent
# =============================================================================================
def _record_in(**fields) -> dict:
    return {
        "quantity": 2,
        "reason": "DAMAGED",
        "starts_at": _at(1).isoformat(),
        "ends_at": _at(5).isoformat(),
    } | fields


def _refusal(model, **fields) -> dict:
    with pytest.raises(ValidationError) as caught:
        model(**fields)
    [error] = caught.value.errors()
    return error


@pytest.mark.story("16.2", ac=1)
def test_a_record_is_kept_with_its_note_trimmed():
    record = schemas.OutOfServiceIn(**_record_in(notes="  Cracked lens  "))

    assert (record.quantity, record.reason, record.notes) == (2, "DAMAGED", "Cracked lens")
    assert (record.starts_at, record.ends_at) == (_at(1), _at(5))


@pytest.mark.story("16.2", ac=1)
@pytest.mark.parametrize("reason", ["DAMAGED", "MAINTENANCE", "LOST", "OTHER"])
def test_each_of_the_four_reasons_is_taken(reason: str):
    assert schemas.OutOfServiceIn(**_record_in(reason=reason)).reason == reason


@pytest.mark.story("16.2", ac=1)
def test_any_other_reason_is_refused():
    assert _refusal(schemas.OutOfServiceIn, **_record_in(reason="STOLEN"))["loc"] == ("reason",)


@pytest.mark.story("16.2", ac=1)
@pytest.mark.parametrize("notes", ["", "   ", None], ids=["empty", "spaces", "null"])
def test_a_note_left_blank_is_no_note(notes: str | None):
    assert schemas.OutOfServiceIn(**_record_in(notes=notes)).notes is None


@pytest.mark.story("16.2", ac=1)
def test_a_note_of_1000_characters_is_kept_and_of_1001_refused():
    longest = "n" * schemas.OUT_OF_SERVICE_NOTES_MAX_LENGTH

    assert schemas.OutOfServiceIn(**_record_in(notes=f" {longest} ")).notes == longest
    error = _refusal(schemas.OutOfServiceIn, **_record_in(notes=longest + "n"))
    assert schemas.OUT_OF_SERVICE_NOTES_TOO_LONG_MESSAGE in error["msg"]


@pytest.mark.story("16.2", ac=1)
def test_a_record_with_no_end_is_open_ended():
    record = schemas.OutOfServiceIn(**_record_in(ends_at=None))

    assert record.ends_at is None


@pytest.mark.story("16.2", ac=3)
def test_a_quantity_of_1_is_taken_and_of_0_refused():
    assert schemas.OutOfServiceIn(**_record_in(quantity=1)).quantity == 1
    error = _refusal(schemas.OutOfServiceIn, **_record_in(quantity=0))
    assert schemas.OUT_OF_SERVICE_QUANTITY_MESSAGE in error["msg"]


@pytest.mark.story("16.2", ac=3)
def test_a_quantity_that_is_not_a_whole_number_is_refused():
    assert _refusal(schemas.OutOfServiceIn, **_record_in(quantity=1.5))["loc"] == ("quantity",)


@pytest.mark.story("16.2", ac=3)
@pytest.mark.parametrize("end", [1, 0.5], ids=["at-the-start", "before-the-start"])
def test_an_end_not_after_the_start_is_refused(end: float):
    error = _refusal(schemas.OutOfServiceIn, **_record_in(ends_at=_at(end).isoformat()))

    assert schemas.OUT_OF_SERVICE_END_NOT_AFTER_START_MESSAGE in error["msg"]


@pytest.mark.story("16.2", ac=3)
def test_an_end_a_moment_after_the_start_is_taken():
    end = _at(1) + timedelta(minutes=1)

    assert schemas.OutOfServiceIn(**_record_in(ends_at=end.isoformat())).ends_at == end


@pytest.mark.story("16.2", ac=3)
def test_a_time_without_its_zone_is_refused():
    error = _refusal(schemas.OutOfServiceIn, **_record_in(starts_at="2030-03-01T10:00:00"))

    assert error["loc"] == ("starts_at",)


@pytest.mark.story("16.2", ac=1)
def test_nothing_else_can_be_sent_with_a_record():
    assert _refusal(schemas.OutOfServiceIn, **_record_in(equipment_type_id="x"))["type"] == (
        "extra_forbidden"
    )


@pytest.mark.story("16.2", ac=2)
def test_an_edit_sends_only_what_changes():
    change = schemas.OutOfServiceUpdate(quantity=3)

    assert change.model_fields_set == {"quantity"}
    assert change.end_now is False


@pytest.mark.story("16.2", ac=3)
def test_an_edit_follows_the_same_rules():
    assert (
        schemas.OUT_OF_SERVICE_QUANTITY_MESSAGE
        in _refusal(schemas.OutOfServiceUpdate, quantity=0)["msg"]
    )
    assert (
        schemas.OUT_OF_SERVICE_NOTES_TOO_LONG_MESSAGE
        in _refusal(schemas.OutOfServiceUpdate, notes="n" * 1001)["msg"]
    )
    assert (
        schemas.OUT_OF_SERVICE_END_NOT_AFTER_START_MESSAGE
        in _refusal(
            schemas.OutOfServiceUpdate, starts_at=_at(2).isoformat(), ends_at=_at(1).isoformat()
        )["msg"]
    )
    assert schemas.OutOfServiceUpdate(notes="  ").notes is None
