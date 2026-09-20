"""Story 2.1 - equipment availability and the soft hold made when a request is submitted.

AC6  Equipment items are added with a type and a quantity, and no more can be requested than is
     available for the event's dates. Availability for a period is the stock, less units held for
     other events over that period (a hold's quantity less what was released), less units out of
     service. Saving a draft holds nothing.
AC11 On submission the equipment on the request is held for the event over its dates (a soft
     reserve). If the stock has gone since the draft was saved, the request is not submitted and
     nothing is held.

Seeded stock: 6 presentation laptops, 3 mobile LED screens, 20 wireless microphones. Releasing a
hold later (a rejected or cancelled request) belongs to the request-decision stories.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.support.factories import (
    create_event_request,
    create_submittable_event_request,
    event_request_payload,
    make_equipment_hold,
    make_equipment_out_of_service,
)
from tests.support.seed import Users

LAPTOP_STOCK = 6
LED_SCREEN_STOCK = 3
ACTIVE_EQUIPMENT_TYPES = 8


def _period(days: int = 40) -> tuple[datetime, datetime]:
    start = (datetime.now(UTC) + timedelta(days=days)).replace(microsecond=0)
    return start, start + timedelta(hours=8)


def _equipment(code: str, quantity: int) -> dict:
    return {"equipment_type_code": code, "quantity": quantity}


def _request(client, period, *lines, **extra) -> dict:
    start, end = period
    return create_event_request(
        client, starts_at=start.isoformat(), ends_at=end.isoformat(), equipment=list(lines), **extra
    )


def _submittable(client, period, *lines) -> dict:
    start, end = period
    return create_submittable_event_request(
        client, starts_at=start.isoformat(), ends_at=end.isoformat(), equipment=list(lines)
    )


def _available(client, period) -> dict[str, int]:
    start, end = period
    response = client.get(
        "/events/equipment-availability",
        params={"starts_at": start.isoformat(), "ends_at": end.isoformat()},
    )
    assert response.status_code == 200, response.text
    return {row["equipment_type_code"]: row["available"] for row in response.json()}


# --- AC6: how many are available for the dates ---------------------------------------------------
@pytest.mark.story("2.1", ac=6)
def test_availability_lists_every_active_type_with_its_full_stock_when_nothing_is_held(
    organiser_client,
):
    available = _available(organiser_client, _period())

    assert len(available) == ACTIVE_EQUIPMENT_TYPES
    assert available["LAPTOP"] == LAPTOP_STOCK
    assert available["LED_SCREEN"] == LED_SCREEN_STOCK


@pytest.mark.story("2.1", ac=6)
def test_an_inactive_type_is_not_listed_in_availability(organiser_client, db: Session):
    db.execute(text("UPDATE equipment_types SET is_active = FALSE WHERE code = 'LAPTOP'"))

    assert "LAPTOP" not in _available(organiser_client, _period())


@pytest.mark.story("2.1", ac=6)
def test_overlapping_holds_reduce_availability(organiser_client, db: Session):
    start, end = _period()
    make_equipment_hold(
        db,
        type_code="LAPTOP",
        quantity=2,
        starts_at=start - timedelta(hours=2),
        ends_at=start + timedelta(hours=1),
    )
    make_equipment_hold(
        db,
        type_code="LAPTOP",
        quantity=1,
        starts_at=end - timedelta(hours=1),
        ends_at=end + timedelta(hours=3),
    )

    assert _available(organiser_client, (start, end))["LAPTOP"] == LAPTOP_STOCK - 3


@pytest.mark.story("2.1", ac=6)
def test_a_partly_released_hold_counts_only_what_is_still_held(organiser_client, db: Session):
    start, end = _period()
    make_equipment_hold(
        db, type_code="LAPTOP", quantity=3, released_quantity=1, starts_at=start, ends_at=end
    )

    assert _available(organiser_client, (start, end))["LAPTOP"] == LAPTOP_STOCK - 2


@pytest.mark.story("2.1", ac=6)
def test_a_released_hold_no_longer_counts(organiser_client, db: Session):
    start, end = _period()
    make_equipment_hold(
        db,
        type_code="LAPTOP",
        quantity=3,
        released_quantity=3,
        status="RELEASED",
        starts_at=start,
        ends_at=end,
    )

    assert _available(organiser_client, (start, end))["LAPTOP"] == LAPTOP_STOCK


@pytest.mark.story("2.1", ac=6)
@pytest.mark.parametrize(
    "hold_offset_hours",
    [
        pytest.param((-8, 0), id="ends-exactly-as-the-event-starts"),
        pytest.param((8, 16), id="starts-exactly-as-the-event-ends"),
        pytest.param((-72, -48), id="well-before"),
        pytest.param((72, 96), id="well-after"),
    ],
)
def test_holds_that_only_touch_or_miss_the_period_do_not_count(
    organiser_client, db: Session, hold_offset_hours
):
    start, end = _period()
    first, last = hold_offset_hours
    make_equipment_hold(
        db,
        type_code="LAPTOP",
        quantity=4,
        starts_at=start + timedelta(hours=first),
        ends_at=start + timedelta(hours=last),
    )

    assert _available(organiser_client, (start, end))["LAPTOP"] == LAPTOP_STOCK


@pytest.mark.story("2.1", ac=6)
def test_units_out_of_service_reduce_availability(organiser_client, db: Session):
    start, end = _period()
    make_equipment_out_of_service(
        db,
        type_code="LAPTOP",
        quantity=2,
        starts_at=start - timedelta(days=1),
        ends_at=end + timedelta(days=1),
    )
    make_equipment_out_of_service(
        db,
        type_code="LED_SCREEN",
        quantity=1,
        starts_at=start - timedelta(days=30),
        reason="DAMAGED",
    )  # open-ended
    make_equipment_out_of_service(
        db,
        type_code="LAPEL_MIC",
        quantity=5,
        starts_at=start - timedelta(days=9),
        ends_at=start - timedelta(days=2),
    )  # over before the event

    available = _available(organiser_client, (start, end))

    assert available["LAPTOP"] == LAPTOP_STOCK - 2
    assert available["LED_SCREEN"] == LED_SCREEN_STOCK - 1
    assert available["LAPEL_MIC"] == 10


@pytest.mark.story("2.1", ac=6)
def test_availability_is_never_below_zero(organiser_client, db: Session):
    start, end = _period()
    make_equipment_hold(
        db, type_code="LAPTOP", quantity=LAPTOP_STOCK + 4, starts_at=start, ends_at=end
    )

    assert _available(organiser_client, (start, end))["LAPTOP"] == 0


@pytest.mark.story("2.1", ac=6)
@pytest.mark.parametrize(
    "params",
    [
        pytest.param({}, id="no-dates"),
        pytest.param({"starts_at": "2030-01-01T09:00:00+00:00"}, id="no-end"),
        pytest.param(
            {"starts_at": "2030-01-01T09:00:00+00:00", "ends_at": "2030-01-01T09:00:00+00:00"},
            id="end-equals-start",
        ),
        pytest.param(
            {"starts_at": "2030-01-01T09:00:00+00:00", "ends_at": "2030-01-01T08:00:00+00:00"},
            id="end-before-start",
        ),
        pytest.param(
            {"starts_at": "2030-01-01T09:00:00", "ends_at": "2030-01-01T17:00:00"}, id="no-timezone"
        ),
    ],
)
def test_availability_needs_a_valid_period(organiser_client, params):
    assert organiser_client.get("/events/equipment-availability", params=params).status_code == 422


@pytest.mark.story("2.1", ac=6)
@pytest.mark.parametrize(
    "user",
    [
        pytest.param(Users.COORDINATOR, id="coordinator"),
        pytest.param(Users.TECH_SUPPORT, id="tech-support"),
        pytest.param(Users.ATTENDEE, id="attendee"),
    ],
)
def test_only_an_organiser_can_see_availability_for_a_request(login_as, user):
    start, end = _period()
    response = login_as(user).get(
        "/events/equipment-availability",
        params={"starts_at": start.isoformat(), "ends_at": end.isoformat()},
    )

    assert response.status_code == 403


@pytest.mark.story("2.1", ac=6)
def test_availability_requires_sign_in(client):
    start, end = _period()
    response = client.get(
        "/events/equipment-availability",
        params={"starts_at": start.isoformat(), "ends_at": end.isoformat()},
    )

    assert response.status_code == 401


# --- AC6: no more than is available can be requested ----------------------------------------
@pytest.mark.story("2.1", ac=6)
def test_a_request_for_all_that_is_available_is_accepted_and_one_more_is_refused(
    organiser_client, db: Session
):
    period = _period()
    make_equipment_hold(db, type_code="LAPTOP", quantity=4, starts_at=period[0], ends_at=period[1])
    start, end = period

    accepted = organiser_client.post(
        "/events",
        json=event_request_payload(
            starts_at=start.isoformat(),
            ends_at=end.isoformat(),
            equipment=[_equipment("LAPTOP", 2)],
        ),
    )
    refused = organiser_client.post(
        "/events",
        json=event_request_payload(
            starts_at=start.isoformat(),
            ends_at=end.isoformat(),
            equipment=[_equipment("LAPTOP", 3)],
        ),
    )

    assert accepted.status_code == 201, accepted.text
    assert refused.status_code == 422
    assert "not enough presentation laptop" in refused.text.lower()


@pytest.mark.story("2.1", ac=6)
def test_a_type_with_nothing_left_is_refused_by_name(organiser_client, db: Session):
    period = _period()
    make_equipment_hold(
        db,
        type_code="LED_SCREEN",
        quantity=LED_SCREEN_STOCK,
        starts_at=period[0],
        ends_at=period[1],
    )
    start, end = period

    response = organiser_client.post(
        "/events",
        json=event_request_payload(
            starts_at=start.isoformat(),
            ends_at=end.isoformat(),
            equipment=[_equipment("LED_SCREEN", 1)],
        ),
    )

    assert response.status_code == 422
    assert "mobile led screen" in response.text.lower()


@pytest.mark.story("2.1", ac=6)
def test_saving_a_draft_holds_nothing_so_two_drafts_can_ask_for_the_same_stock(login_as):
    period = _period()

    first = _request(login_as(Users.ORGANISER), period, _equipment("LAPTOP", LAPTOP_STOCK))
    second = _request(login_as(Users.ORGANISER_2), period, _equipment("LAPTOP", LAPTOP_STOCK))

    assert first["id"] != second["id"]
    assert _available(login_as(Users.ORGANISER), period)["LAPTOP"] == LAPTOP_STOCK


@pytest.mark.story("2.1", ac=6)
def test_availability_is_only_checked_once_both_dates_are_known(organiser_client):
    start, _ = _period()

    without_dates = organiser_client.post(
        "/events", json={"name": "No dates yet", "equipment": [_equipment("LAPTOP", 100)]}
    )
    with_only_a_start = organiser_client.post(
        "/events",
        json={
            "name": "Start only",
            "starts_at": start.isoformat(),
            "equipment": [_equipment("LAPTOP", 100)],
        },
    )

    assert without_dates.status_code == 201, without_dates.text
    assert with_only_a_start.status_code == 201, with_only_a_start.text


@pytest.mark.story("2.1", ac=6)
def test_an_edit_raising_the_quantity_beyond_what_is_available_is_refused(
    organiser_client, db: Session
):
    period = _period()
    created = _request(organiser_client, period, _equipment("LAPTOP", 2))
    make_equipment_hold(db, type_code="LAPTOP", quantity=3, starts_at=period[0], ends_at=period[1])
    line_id = created["equipment"][0]["id"]

    too_many = organiser_client.patch(
        f"/events/{created['id']}",
        json={"equipment": [{"id": line_id, **_equipment("LAPTOP", 4)}]},
    )
    all_of_it = organiser_client.patch(
        f"/events/{created['id']}",
        json={"equipment": [{"id": line_id, **_equipment("LAPTOP", 3)}]},
    )

    assert too_many.status_code == 422
    assert all_of_it.status_code == 200, all_of_it.text


@pytest.mark.story("2.1", ac=6)
def test_an_edit_moving_the_dates_into_a_busier_period_is_refused(organiser_client, db: Session):
    quiet, busy = _period(40), _period(60)
    created = _request(organiser_client, quiet, _equipment("LAPTOP", 5))
    make_equipment_hold(db, type_code="LAPTOP", quantity=4, starts_at=busy[0], ends_at=busy[1])

    response = organiser_client.patch(
        f"/events/{created['id']}",
        json={"starts_at": busy[0].isoformat(), "ends_at": busy[1].isoformat()},
    )

    assert response.status_code == 422
    assert "not enough presentation laptop" in response.text.lower()


# --- AC11: submitting soft-holds the equipment -----------------------------------------------
@pytest.mark.story("2.1", ac=11)
def test_submitting_holds_the_equipment_for_the_event(login_as, db: Session):
    period = _period()
    created = _submittable(
        login_as(Users.ORGANISER), period, _equipment("LAPTOP", 2), _equipment("WIRELESS_MIC", 3)
    )

    submitted = login_as(Users.ORGANISER).post(f"/events/{created['id']}/submit")

    assert submitted.status_code == 200, submitted.text
    assert {line["status"] for line in submitted.json()["equipment"]} == {"RESERVED"}
    holds = db.execute(
        text(
            "SELECT t.code, r.quantity, r.starts_at, r.ends_at, r.status, r.reserved_by_id,"
            " r.equipment_request_id FROM equipment_reservations r"
            " JOIN equipment_types t ON t.id = r.equipment_type_id WHERE r.event_id = :id"
        ),
        {"id": created["id"]},
    ).all()
    line_ids = {line["equipment_type_code"]: line["id"] for line in submitted.json()["equipment"]}
    assert {(h.code, h.quantity) for h in holds} == {("LAPTOP", 2), ("WIRELESS_MIC", 3)}
    assert {(h.starts_at, h.ends_at, h.status) for h in holds} == {
        (period[0], period[1], "RESERVED")
    }
    assert {h.reserved_by_id for h in holds} == {Users.ORGANISER.id}
    assert {str(h.equipment_request_id) for h in holds} == set(line_ids.values())


@pytest.mark.story("2.1", ac=11)
def test_the_held_equipment_is_no_longer_available_to_the_next_request(login_as):
    period = _period()
    created = _submittable(login_as(Users.ORGANISER), period, _equipment("LAPTOP", 4))
    login_as(Users.ORGANISER).post(f"/events/{created['id']}/submit")

    assert _available(login_as(Users.ORGANISER_2), period)["LAPTOP"] == LAPTOP_STOCK - 4


@pytest.mark.story("2.1", ac=11)
def test_a_request_without_equipment_holds_nothing(organiser_client, db: Session):
    created = create_submittable_event_request(organiser_client)

    assert organiser_client.post(f"/events/{created['id']}/submit").status_code == 200
    count = db.execute(
        text("SELECT count(*) FROM equipment_reservations WHERE event_id = :id"),
        {"id": created["id"]},
    ).scalar()
    assert count == 0


@pytest.mark.story("2.1", ac=11)
def test_stock_held_for_another_period_does_not_block_a_submission(login_as):
    first_period, other_period = _period(40), _period(70)
    first = _submittable(
        login_as(Users.ORGANISER), first_period, _equipment("LAPTOP", LAPTOP_STOCK)
    )
    second = _submittable(
        login_as(Users.ORGANISER_2), other_period, _equipment("LAPTOP", LAPTOP_STOCK)
    )

    assert login_as(Users.ORGANISER).post(f"/events/{first['id']}/submit").status_code == 200
    assert login_as(Users.ORGANISER_2).post(f"/events/{second['id']}/submit").status_code == 200


@pytest.mark.story("2.1", ac=11)
def test_the_last_units_go_to_whoever_submits_first(login_as, db: Session):
    period = _period()
    first = _submittable(login_as(Users.ORGANISER), period, _equipment("LAPTOP", LAPTOP_STOCK))
    second = _submittable(login_as(Users.ORGANISER_2), period, _equipment("LAPTOP", LAPTOP_STOCK))

    won = login_as(Users.ORGANISER).post(f"/events/{first['id']}/submit")
    lost = login_as(Users.ORGANISER_2).post(f"/events/{second['id']}/submit")

    assert won.status_code == 200, won.text
    assert lost.status_code == 409
    assert "presentation laptop" in lost.text.lower()
    assert (
        db.execute(text("SELECT status FROM events WHERE id = :id"), {"id": second["id"]}).scalar()
        == "DRAFT"
    )


@pytest.mark.story("2.1", ac=11)
def test_a_refused_submission_holds_nothing_even_for_the_lines_that_were_available(
    login_as, db: Session
):
    period = _period()
    mine = _submittable(
        login_as(Users.ORGANISER), period, _equipment("LAPTOP", 2), _equipment("LED_SCREEN", 3)
    )
    other = _submittable(login_as(Users.ORGANISER_2), period, _equipment("LED_SCREEN", 2))
    assert login_as(Users.ORGANISER_2).post(f"/events/{other['id']}/submit").status_code == 200

    response = login_as(Users.ORGANISER).post(f"/events/{mine['id']}/submit")

    assert response.status_code == 409
    assert "mobile led screen" in response.text.lower()
    assert "presentation laptop" not in response.text.lower()  # that line was fine
    assert (
        db.execute(
            text("SELECT count(*) FROM equipment_reservations WHERE event_id = :id"),
            {"id": mine["id"]},
        ).scalar()
        == 0
    )
    still_draft = login_as(Users.ORGANISER).get(f"/events/{mine['id']}").json()
    assert still_draft["status"] == "DRAFT"
    assert {line["status"] for line in still_draft["equipment"]} == {"REQUESTED"}
