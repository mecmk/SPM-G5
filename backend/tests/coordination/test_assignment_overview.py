"""Story 5.5 - be: the Event Coordinator Lead's overview of coordinators' assignments.

Happy path
AC1  Every active event, with name, dates, status, its coordinator (or none yet) and the Lead who
     assigned it, filterable by coordinator, by status (6.1's active statuses) and to "Assigned
     by me".
AC2  A per-coordinator view: each Event Coordinator with their number of active events, and the
     events themselves.
Boundary
AC4  A coordinator with no active events is listed with 0.
Edge
AC5  After an assignment or a reassignment, the new coordinator is shown on the next read. A
     deactivated coordinator who still holds active events is listed and flagged.
Permission
AC6  Only the Lead sees either view; every other role is refused (403), and signing in is
     required (401).

PO decisions at Checkpoint 1 these tests rely on:
* P1 "Active" is 5.4's five statuses (Under Review, Clarification Requested, Planning, Awaiting
  Safety Check, Confirmed). A draft is not active.
* P2 "Assigned by me" is the event's current assignment's assigner.
* P3 "Assigned by" names the assigner only when they hold ``events:assign`` - the Lead's
  permission, checked as a permission rather than a role name; otherwise it is null.
* P4 A deactivated coordinator is listed only while they hold active events.
* P5 ``coordinator=unassigned`` selects the events with no coordinator.
* P6 Both views are gated on ``events:assign``.

Excluded, with reason:
* AC3 (an event opens read-only) is UI: tests/e2e/assignment-overview.spec.ts. The Lead's 403 on
  approve, reject and clarification is already proven by 5.4's
  test_the_lead_opens_an_assigned_event_but_cannot_decide_it.
* AC6's "a coordinator still sees only their own events" is 6.1's list, unchanged and proven by
  its own tests.
* Conflict: none. 5.5 only reads; two Leads assigning at once is 5.4 AC8.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.coordination.models import EventCoordinatorAssignment
from app.events.models import Event, EventStatus
from tests.support.factories import make_event, make_user
from tests.support.seed import Users

OVERVIEW_PATH = "/coordination/active-events"
WORKLOADS_PATH = "/coordination/workloads"
COORDINATOR_ROLE = "EVENT_COORDINATOR"
LEAD_ROLE = "EVENT_COORDINATOR_LEAD"
ACTIVE_STATUSES = (
    EventStatus.UNDER_REVIEW,
    EventStatus.CLARIFICATION_REQUESTED,
    EventStatus.PLANNING,
    EventStatus.AWAITING_SAFETY_CHECK,
    EventStatus.CONFIRMED,
)
# Every role but the Lead's, so a role added later is refused here without editing this list.
REFUSED_ROLES = [user for user in Users.ONE_PER_ROLE if user != Users.LEAD]


# --- helpers ---------------------------------------------------------------------------------
def _event(db: Session, **overrides) -> Event:
    """A submitted event dated safely in the future, with no coordinator unless one is given."""
    starts_at = overrides.pop("starts_at", datetime.now(UTC) + timedelta(days=90))
    return make_event(
        db,
        status=overrides.pop("status", EventStatus.UNDER_REVIEW),
        starts_at=starts_at,
        ends_at=overrides.pop("ends_at", starts_at + timedelta(hours=6)),
        **overrides,
    )


def _assigned_event(
    db: Session, coordinator_id: uuid.UUID, *, assigned_by_id: uuid.UUID | None, **overrides
) -> Event:
    """An event with ``coordinator_id`` as its current coordinator, recorded the way an
    assignment is: the pointer on the event and an open row in its assignment history."""
    event = _event(db, assigned_coordinator_id=coordinator_id, **overrides)
    db.add(
        EventCoordinatorAssignment(
            event_id=event.id, coordinator_id=coordinator_id, assigned_by_id=assigned_by_id
        )
    )
    db.flush()
    return event


def _overview(client, **params) -> list[dict]:
    response = client.get(OVERVIEW_PATH, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _row(rows: list[dict], event: Event) -> dict:
    [row] = [row for row in rows if row["id"] == str(event.id)]
    return row


def _ids(rows: list[dict]) -> set[str]:
    return {row["id"] for row in rows}


def _sorting_id(n: int) -> uuid.UUID:
    """A fixed id that sorts by ``n``, for ordering tests: given the reverse of the order a test
    expects, so a list that came out in id order (or by chance) fails."""
    return uuid.UUID(int=0x55_0000 + n)


def _workloads(client) -> dict[str, dict]:
    response = client.get(WORKLOADS_PATH)
    assert response.status_code == 200, response.text
    return {entry["coordinator_id"]: entry for entry in response.json()}


# --- AC1: every active event ------------------------------------------------------------------
@pytest.mark.story("5.5", ac=1)
def test_the_overview_lists_every_active_event_with_its_coordinator_and_assigner(
    login_as, db: Session
):
    event = _assigned_event(
        db,
        Users.COORDINATOR_2.id,
        assigned_by_id=Users.LEAD.id,
        name="Overview Harbour Gala",
        status=EventStatus.PLANNING,
    )

    row = _row(_overview(login_as(Users.LEAD)), event)

    assert row["name"] == "Overview Harbour Gala"
    assert datetime.fromisoformat(row["starts_at"]) == event.starts_at
    assert datetime.fromisoformat(row["ends_at"]) == event.ends_at
    assert row["status"] == EventStatus.PLANNING
    assert row["coordinator_id"] == str(Users.COORDINATOR_2.id)
    assert row["coordinator_name"] == Users.COORDINATOR_2.full_name
    assert row["coordinator_is_active"] is True
    assert row["assigned_by_name"] == Users.LEAD.full_name


@pytest.mark.story("5.5", ac=1)
@pytest.mark.parametrize(
    "status",
    [EventStatus.DRAFT, EventStatus.COMPLETED, EventStatus.CANCELLED, EventStatus.REJECTED],
)
def test_the_overview_leaves_out_drafts_and_closed_events(login_as, db: Session, status):
    """P1: a draft is not active, and a closed event needs no oversight."""
    left_out = _event(db, status=status)
    active = _event(db, status=EventStatus.CONFIRMED)

    listed = _ids(_overview(login_as(Users.LEAD)))

    assert str(left_out.id) not in listed
    assert str(active.id) in listed


@pytest.mark.story("5.5", ac=1)
def test_an_unassigned_event_is_listed_without_a_coordinator(login_as, db: Session):
    event = _event(db)

    row = _row(_overview(login_as(Users.LEAD)), event)

    assert row["coordinator_id"] is None
    assert row["coordinator_name"] is None
    assert row["coordinator_is_active"] is None
    assert row["assigned_by_name"] is None


@pytest.mark.story("5.5", ac=1)
@pytest.mark.parametrize(
    "assigner",
    ["the Lead", "the coordinator themselves", "another coordinator", "nobody recorded"],
)
def test_assigned_by_names_only_a_lead(login_as, db: Session, assigner):
    """P3: events assigned before 5.4 were self-assigned or have no assigner, and a coordinator's
    handover (5.2) was made by the coordinator handing over; none is "the Lead who assigned it", so
    none is named."""
    assigned_by_id, expected = {
        "the Lead": (Users.LEAD.id, Users.LEAD.full_name),
        "the coordinator themselves": (Users.COORDINATOR.id, None),
        "another coordinator": (Users.COORDINATOR_2.id, None),
        "nobody recorded": (None, None),
    }[assigner]
    event = _assigned_event(db, Users.COORDINATOR.id, assigned_by_id=assigned_by_id)

    row = _row(_overview(login_as(Users.LEAD)), event)

    assert row["assigned_by_name"] == expected


@pytest.mark.story("5.5", ac=1)
def test_the_overview_lists_events_soonest_first(login_as, db: Session):
    """Made out of order, listed by start: the order the Lead plans by. The ids run the other way,
    so a list in id order fails."""
    team_of_one = make_user(db, role=COORDINATOR_ROLE, full_name="Ordered Coordinator")
    soon = datetime.now(UTC) + timedelta(days=30)
    later, latest, soonest = (
        _assigned_event(
            db,
            team_of_one.id,
            assigned_by_id=None,
            id=_sorting_id(n),
            starts_at=soon + timedelta(days=days),
        )
        for days, n in ((10, 2), (20, 1), (0, 3))
    )

    rows = _overview(login_as(Users.LEAD), coordinator=str(team_of_one.id))

    assert [row["id"] for row in rows] == [str(soonest.id), str(later.id), str(latest.id)]


@pytest.mark.story("5.5", ac=1)
def test_the_overview_filters_by_coordinator(login_as, db: Session):
    chloes = _assigned_event(db, Users.COORDINATOR.id, assigned_by_id=Users.LEAD.id)
    carls = _assigned_event(db, Users.COORDINATOR_2.id, assigned_by_id=Users.LEAD.id)
    unassigned = _event(db)

    rows = _overview(login_as(Users.LEAD), coordinator=str(Users.COORDINATOR_2.id))

    assert str(carls.id) in _ids(rows)
    assert str(chloes.id) not in _ids(rows)
    assert str(unassigned.id) not in _ids(rows)
    assert {row["coordinator_id"] for row in rows} == {str(Users.COORDINATOR_2.id)}


@pytest.mark.story("5.5", ac=1)
def test_the_overview_filters_to_unassigned_events(login_as, db: Session):
    """P5: ``coordinator=unassigned`` selects the events with no coordinator yet."""
    unassigned = _event(db)
    assigned = _assigned_event(db, Users.COORDINATOR.id, assigned_by_id=Users.LEAD.id)

    rows = _overview(login_as(Users.LEAD), coordinator="unassigned")

    assert str(unassigned.id) in _ids(rows)
    assert str(assigned.id) not in _ids(rows)
    assert {row["coordinator_id"] for row in rows} == {None}


@pytest.mark.story("5.5", ac=1)
def test_the_overview_filters_by_status(login_as, db: Session):
    planning = _event(db, status=EventStatus.PLANNING)
    awaiting = _event(db, status=EventStatus.AWAITING_SAFETY_CHECK)

    rows = _overview(login_as(Users.LEAD), status=EventStatus.AWAITING_SAFETY_CHECK)

    assert str(awaiting.id) in _ids(rows)
    assert str(planning.id) not in _ids(rows)
    assert {row["status"] for row in rows} == {EventStatus.AWAITING_SAFETY_CHECK}


@pytest.mark.story("5.5", ac=1)
@pytest.mark.parametrize("status", [EventStatus.COMPLETED, EventStatus.DRAFT, "NOT_A_STATUS"])
def test_a_status_filter_outside_the_active_statuses_is_refused(login_as, status):
    response = login_as(Users.LEAD).get(OVERVIEW_PATH, params={"status": status})

    assert response.status_code == 422, response.text


@pytest.mark.story("5.5", ac=1)
def test_assigned_by_me_lists_only_this_leads_current_assignments(login_as, db: Session):
    """P2: the current assignment's assigner. Another Lead's assignment is not mine, and once
    another Lead reassigns an event this Lead assigned (5.6), its current assigner is that Lead.
    The fixtures share one client, so the other Lead acts before this one signs in."""
    other_lead = make_user(db, role=LEAD_ROLE, full_name="Other Lead")
    mine = _assigned_event(db, Users.COORDINATOR_2.id, assigned_by_id=Users.LEAD.id)
    theirs = _assigned_event(db, Users.COORDINATOR_2.id, assigned_by_id=other_lead.id)
    handed_on = _assigned_event(db, Users.COORDINATOR.id, assigned_by_id=Users.LEAD.id)
    reassigned = login_as(other_lead.email).put(
        f"/events/{handed_on.id}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )
    assert reassigned.status_code == 200, reassigned.text

    rows = _overview(login_as(Users.LEAD), assigned_by="me")

    assert str(mine.id) in _ids(rows)
    assert str(theirs.id) not in _ids(rows)
    assert str(handed_on.id) not in _ids(rows)
    assert {row["assigned_by_name"] for row in rows} == {Users.LEAD.full_name}


@pytest.mark.story("5.5", ac=1)
def test_filters_combine(login_as, db: Session):
    match = _assigned_event(
        db, Users.COORDINATOR.id, assigned_by_id=Users.LEAD.id, status=EventStatus.PLANNING
    )
    wrong_status = _assigned_event(
        db, Users.COORDINATOR.id, assigned_by_id=Users.LEAD.id, status=EventStatus.CONFIRMED
    )
    wrong_coordinator = _assigned_event(
        db, Users.COORDINATOR_2.id, assigned_by_id=Users.LEAD.id, status=EventStatus.PLANNING
    )
    not_mine = _assigned_event(
        db, Users.COORDINATOR.id, assigned_by_id=None, status=EventStatus.PLANNING
    )

    rows = _overview(
        login_as(Users.LEAD),
        coordinator=str(Users.COORDINATOR.id),
        status=EventStatus.PLANNING,
        assigned_by="me",
    )

    assert str(match.id) in _ids(rows)
    for event in (wrong_status, wrong_coordinator, not_mine):
        assert str(event.id) not in _ids(rows)


@pytest.mark.story("5.5", ac=1)
@pytest.mark.parametrize("case", ["no event in that status for them", "unknown coordinator"])
def test_filters_with_no_match_return_an_empty_list(login_as, db: Session, case):
    idle = make_user(db, role=COORDINATOR_ROLE, full_name="Idle Coordinator")
    coordinator = idle.id if case == "no event in that status for them" else uuid.uuid4()

    rows = _overview(
        login_as(Users.LEAD), coordinator=str(coordinator), status=EventStatus.CONFIRMED
    )

    assert rows == []


@pytest.mark.story("5.5", ac=1)
def test_a_malformed_coordinator_filter_is_refused(login_as):
    response = login_as(Users.LEAD).get(OVERVIEW_PATH, params={"coordinator": "not-an-id"})

    assert response.status_code == 422, response.text


# --- AC2 / AC4: the per-coordinator view --------------------------------------------------
@pytest.mark.story("5.5", ac=2)
def test_workloads_list_each_coordinator_with_their_active_events(login_as, db: Session):
    busy = make_user(db, role=COORDINATOR_ROLE, full_name="Busy Coordinator")
    first = _assigned_event(db, busy.id, assigned_by_id=Users.LEAD.id, name="Workload One")
    second = _assigned_event(
        db, busy.id, assigned_by_id=None, name="Workload Two", status=EventStatus.CONFIRMED
    )

    entry = _workloads(login_as(Users.LEAD))[str(busy.id)]

    assert entry["coordinator_name"] == "Busy Coordinator"
    assert entry["is_active"] is True
    assert entry["active_event_count"] == 2
    assert {event["id"] for event in entry["events"]} == {str(first.id), str(second.id)}
    listed = {event["id"]: event for event in entry["events"]}[str(second.id)]
    assert listed["name"] == "Workload Two"
    assert listed["status"] == EventStatus.CONFIRMED
    assert datetime.fromisoformat(listed["starts_at"]) == second.starts_at
    assert datetime.fromisoformat(listed["ends_at"]) == second.ends_at


@pytest.mark.story("5.5", ac=2)
def test_workloads_list_coordinators_by_name_and_their_events_soonest_first(login_as, db: Session):
    """The ids run the other way from the names and the dates, so a list in id order fails."""
    zed = make_user(
        db, role=COORDINATOR_ROLE, full_name="Zed Ordering Coordinator", id=_sorting_id(1)
    )
    abe = make_user(
        db, role=COORDINATOR_ROLE, full_name="Abe Ordering Coordinator", id=_sorting_id(2)
    )
    soon = datetime.now(UTC) + timedelta(days=30)
    later = _assigned_event(
        db, abe.id, assigned_by_id=None, id=_sorting_id(3), starts_at=soon + timedelta(days=5)
    )
    sooner = _assigned_event(db, abe.id, assigned_by_id=None, id=_sorting_id(4), starts_at=soon)

    workloads = _workloads(login_as(Users.LEAD))

    names = [entry["coordinator_name"] for entry in workloads.values()]
    assert names.index("Abe Ordering Coordinator") < names.index("Zed Ordering Coordinator")
    assert [event["id"] for event in workloads[str(abe.id)]["events"]] == [
        str(sooner.id),
        str(later.id),
    ]
    assert workloads[str(zed.id)]["events"] == []


@pytest.mark.story("5.5", ac=2)
def test_workloads_list_only_event_coordinators(login_as, db: Session):
    """AC2 is each Event Coordinator's workload: the Lead and the other roles are not listed,
    even holding an event as its coordinator, which only a coordinator should."""
    _assigned_event(db, Users.LEAD.id, assigned_by_id=Users.LEAD.id)

    listed = _workloads(login_as(Users.LEAD))

    for user in REFUSED_ROLES + [Users.LEAD]:
        if user.role != COORDINATOR_ROLE:
            assert str(user.id) not in listed, user.role


@pytest.mark.story("5.5", ac=2)
def test_workloads_count_only_active_events(login_as, db: Session):
    """P1, the same rule as 5.4's picker: closed events are neither counted nor listed, and the
    count always equals the events listed."""
    busy = make_user(db, role=COORDINATOR_ROLE, full_name="Counted Coordinator")
    for status in (*ACTIVE_STATUSES, EventStatus.COMPLETED, EventStatus.CANCELLED):
        _assigned_event(db, busy.id, assigned_by_id=Users.LEAD.id, status=status)
    _assigned_event(db, busy.id, assigned_by_id=Users.LEAD.id, status=EventStatus.REJECTED)

    workloads = _workloads(login_as(Users.LEAD))

    entry = workloads[str(busy.id)]
    assert entry["active_event_count"] == len(ACTIVE_STATUSES)
    assert sorted(event["status"] for event in entry["events"]) == sorted(ACTIVE_STATUSES)
    for other in workloads.values():
        assert other["active_event_count"] == len(other["events"])


@pytest.mark.story("5.5", ac=4)
def test_a_coordinator_with_no_active_events_is_listed_with_zero(login_as, db: Session):
    idle = make_user(db, role=COORDINATOR_ROLE, full_name="Idle Coordinator")
    _assigned_event(db, idle.id, assigned_by_id=Users.LEAD.id, status=EventStatus.COMPLETED)

    entry = _workloads(login_as(Users.LEAD))[str(idle.id)]

    assert entry["active_event_count"] == 0
    assert entry["events"] == []
    assert entry["is_active"] is True


# --- AC5: fresh reads, and deactivated coordinators ---------------------------------------
@pytest.mark.story("5.5", ac=5)
def test_both_views_show_the_coordinator_after_an_assignment(login_as, db: Session):
    event = _event(db)
    lead = login_as(Users.LEAD)
    assert _row(_overview(lead), event)["coordinator_id"] is None

    assigned = lead.put(
        f"/events/{event.id}/coordinator", json={"coordinator_id": str(Users.COORDINATOR_2.id)}
    )

    assert assigned.status_code == 200, assigned.text
    row = _row(_overview(lead), event)
    assert row["coordinator_id"] == str(Users.COORDINATOR_2.id)
    assert row["assigned_by_name"] == Users.LEAD.full_name
    carls = _workloads(lead)[str(Users.COORDINATOR_2.id)]
    assert str(event.id) in {listed["id"] for listed in carls["events"]}


@pytest.mark.story("5.5", ac=5)
def test_both_views_show_the_new_coordinator_after_a_reassignment(login_as, db: Session):
    """The Lead hands Chloe's event to Carl (5.6); the Lead's next read shows Carl."""
    event = _assigned_event(db, Users.COORDINATOR.id, assigned_by_id=Users.LEAD.id)
    lead = login_as(Users.LEAD)

    reassigned = lead.put(
        f"/events/{event.id}/coordinator",
        json={
            "coordinator_id": str(Users.COORDINATOR_2.id),
            "expected_coordinator_id": str(Users.COORDINATOR.id),
        },
    )

    assert reassigned.status_code == 200, reassigned.text
    row = _row(_overview(lead), event)
    assert row["coordinator_id"] == str(Users.COORDINATOR_2.id)
    # P3: the Lead made this assignment, so they are named.
    assert row["assigned_by_name"] == Users.LEAD.full_name
    workloads = _workloads(lead)
    assert str(event.id) in {e["id"] for e in workloads[str(Users.COORDINATOR_2.id)]["events"]}
    assert str(event.id) not in {e["id"] for e in workloads[str(Users.COORDINATOR.id)]["events"]}


@pytest.mark.story("5.5", ac=5)
def test_a_deactivated_coordinator_with_active_events_is_listed_and_flagged(login_as, db: Session):
    """P4: so the Lead can see whose events need reassigning. The overview flags the event too."""
    gone = make_user(db, role=COORDINATOR_ROLE, full_name="Departed Coordinator", is_active=False)
    event = _assigned_event(db, gone.id, assigned_by_id=Users.LEAD.id)
    lead = login_as(Users.LEAD)

    entry = _workloads(lead)[str(gone.id)]
    row = _row(_overview(lead), event)

    assert entry["is_active"] is False
    assert entry["active_event_count"] == 1
    assert [listed["id"] for listed in entry["events"]] == [str(event.id)]
    assert row["coordinator_name"] == "Departed Coordinator"
    assert row["coordinator_is_active"] is False


@pytest.mark.story("5.5", ac=5)
def test_a_deactivated_coordinator_without_active_events_is_not_listed(login_as, db: Session):
    """P4: with nothing to reassign, a deactivated coordinator is not part of the team's load."""
    gone = make_user(db, role=COORDINATOR_ROLE, full_name="Retired Coordinator", is_active=False)
    _assigned_event(db, gone.id, assigned_by_id=Users.LEAD.id, status=EventStatus.COMPLETED)

    assert str(gone.id) not in _workloads(login_as(Users.LEAD))


# --- AC6: only the Lead -------------------------------------------------------------------
@pytest.mark.story("5.5", ac=6)
@pytest.mark.parametrize("user", REFUSED_ROLES, ids=lambda u: u.role)
def test_only_the_lead_sees_the_overview(login_as, user):
    response = login_as(user).get(OVERVIEW_PATH)

    assert response.status_code == 403, response.text


@pytest.mark.story("5.5", ac=6)
@pytest.mark.parametrize("user", REFUSED_ROLES, ids=lambda u: u.role)
def test_only_the_lead_sees_the_workloads(login_as, user):
    response = login_as(user).get(WORKLOADS_PATH)

    assert response.status_code == 403, response.text


@pytest.mark.story("5.5", ac=6)
@pytest.mark.parametrize("path", [OVERVIEW_PATH, WORKLOADS_PATH])
def test_signing_in_is_required_for_the_overview_and_workloads(client, path):
    assert client.get(path).status_code == 401
