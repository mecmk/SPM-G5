"""c14 - the seed's sample change requests, so a coordinator's queue and an organiser's event pages
have change requests to show without anyone raising one first. A chore, so it has no acceptance
criteria of its own; each case is tagged story 19.2 AC1, the queue and record these rows feed.

Each case below reads the seeded rows as the app serves them or as the database holds them, and
compares them with the figures written out in ``SEEDED``, not with each other. Raising, listing in
every status and ordering are 19.1 and 19.2's own cases (test_raise_change_request.py,
test_decide_change_request.py), made from factories; nothing here repeats them.

Happy path
* Chloe's queue holds the Customer Success Forum's pending request, Carl's the Annual Sales
  Kickoff's; each reads with its two values, its reason and who asked.
* The rest of each coordinator's record: Chloe's approved and rejected one, Carl's withdrawn one
  and the approved one on Nadia's event.
* Each organiser reads their own requests on their events' pages, in more than one status.

Boundary
* Every seeded value is canonical JSON, as the service writes it, so the app reads it back.
* A pending request is not out of date: it records the value its event has now.

Edge
* The approved requests record a change the event already shows; the rejected, withdrawn and
  pending ones leave its figure as it was.
* A decision names a coordinator and a time; a rejection also its reason; a pending or withdrawn
  request names neither.
* Nadia's "Change approved" notification names a request that exists, on her event.

Permission and conflict cases do not apply: the seed adds no rule, and who may decide (19.2 AC6)
and the one pending request a field takes (19.1 AC6) are proved from factories in the files above.
The index behind AC6 would also refuse a seed that broke it, so the seed loading proves the rest.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.change_requests.models import EventChangeRequest
from app.events.models import Event
from app.notifications.models import Notification
from tests.support.seed import ChangeRequests, Events, Notifications, Users

_KICKOFF_NOW = {"ends_at": "2027-08-18T10:00:00+00:00", "starts_at": "2027-08-18T01:00:00+00:00"}
_NEXT_DAY = {"ends_at": "2027-08-19T10:00:00+00:00", "starts_at": "2027-08-19T01:00:00+00:00"}


@dataclass(frozen=True)
class Seeded:
    id: uuid.UUID
    event_id: uuid.UUID
    event_name: str
    organiser: Any
    coordinator: Any
    field: str
    current: Any
    proposed: Any
    status: str
    decision_reason: str | None = None


SEEDED = (
    Seeded(
        ChangeRequests.CUSTOMER_FORUM_ATTENDANCE,
        Events.CUSTOMER_FORUM,
        "Customer Success Forum",
        Users.ORGANISER_2,
        Users.COORDINATOR,
        "expected_attendance",
        150,
        180,
        "PENDING",
    ),
    Seeded(
        ChangeRequests.SALES_KICKOFF_SCHEDULE,
        Events.SALES_KICKOFF,
        "Annual Sales Kickoff",
        Users.ORGANISER_2,
        Users.COORDINATOR_2,
        "schedule",
        _KICKOFF_NOW,
        _NEXT_DAY,
        "PENDING",
    ),
    Seeded(
        ChangeRequests.FIRESIDE_ATTENDANCE,
        Events.APPROVED_4,
        "Founders Day Fireside Chat",
        Users.ORGANISER,
        Users.COORDINATOR,
        "expected_attendance",
        180,
        200,
        "APPROVED",
    ),
    Seeded(
        ChangeRequests.CHARITY_GALA_ATTENDANCE,
        Events.APPROVED_6,
        "Winter Charity Gala",
        Users.ORGANISER,
        Users.COORDINATOR,
        "expected_attendance",
        220,
        400,
        "REJECTED",
        decision_reason="The banquet venues we can book do not seat 400 guests.",
    ),
    Seeded(
        ChangeRequests.FINTECH_BREAKFAST_ATTENDANCE,
        Events.FINTECH_BREAKFAST,
        "Fintech Leaders Breakfast",
        Users.ORGANISER_2,
        Users.COORDINATOR_2,
        "expected_attendance",
        45,
        60,
        "WITHDRAWN",
    ),
    Seeded(
        ChangeRequests.NOTICE_GALA_ATTENDANCE,
        Events.NOTICE_GALA,
        "Harbour Lights Gala",
        Users.NOTICE,
        Users.COORDINATOR_2,
        "expected_attendance",
        40,
        60,
        "APPROVED",
    ),
)
_BY_ID = {seeded.id: seeded for seeded in SEEDED}


def _row(db: Session, request_id: uuid.UUID) -> EventChangeRequest:
    row = db.get(EventChangeRequest, request_id)
    assert row is not None, f"seeded change request {request_id} is missing"
    return row


def _queue(client, coordinator) -> dict[str, dict]:
    client.login(coordinator)
    response = client.get("/change-requests")
    assert response.status_code == 200, response.text
    return {entry["id"]: entry for entry in response.json()}


@pytest.mark.story("19.2", ac=1)
@pytest.mark.parametrize(
    "seeded", SEEDED, ids=lambda seeded: f"{seeded.event_name} {seeded.status}"
)
def test_a_seeded_request_records_what_the_seed_describes(db: Session, seeded: Seeded):
    row = _row(db, seeded.id)

    assert row.event_id == seeded.event_id
    assert row.requested_by_id == seeded.organiser.id
    assert row.field_name == seeded.field
    assert json.loads(row.current_value) == seeded.current
    assert json.loads(row.proposed_value) == seeded.proposed
    assert row.status == seeded.status
    assert row.reason.strip()


@pytest.mark.story("19.2", ac=1)
@pytest.mark.parametrize(
    "seeded", SEEDED, ids=lambda seeded: f"{seeded.event_name} {seeded.status}"
)
def test_a_seeded_value_is_canonical_json(db: Session, seeded: Seeded):
    """Stored the way the service writes it - keys sorted, no spaces - so the same value always
    reads the same and an identical proposal is recognised (19.1 AC4)."""
    row = _row(db, seeded.id)

    for stored in (row.current_value, row.proposed_value):
        assert stored == json.dumps(json.loads(stored), sort_keys=True, separators=(",", ":"))


@pytest.mark.story("19.2", ac=1)
@pytest.mark.parametrize(
    "seeded", SEEDED, ids=lambda seeded: f"{seeded.event_name} {seeded.status}"
)
def test_a_seeded_decision_names_who_decided_and_when(db: Session, seeded: Seeded):
    row = _row(db, seeded.id)

    if seeded.status in ("APPROVED", "REJECTED"):
        assert row.decided_by_id == seeded.coordinator.id
        assert row.decided_at is not None
        assert row.decided_at > row.created_at
    else:
        assert row.decided_by_id is None
        assert row.decided_at is None
    assert row.decision_reason == seeded.decision_reason


@pytest.mark.story("19.2", ac=1)
@pytest.mark.parametrize(
    "seeded", SEEDED, ids=lambda seeded: f"{seeded.event_name} {seeded.status}"
)
def test_a_seeded_request_sits_on_an_event_its_coordinator_owns(db: Session, seeded: Seeded):
    """It is in that coordinator's queue and no other's, and the event is the one it names."""
    event = db.get(Event, seeded.event_id)

    assert event.name == seeded.event_name
    assert event.organiser_id == seeded.organiser.id
    assert event.assigned_coordinator_id == seeded.coordinator.id


@pytest.mark.story("19.2", ac=1)
@pytest.mark.parametrize(
    "seeded", [s for s in SEEDED if s.field == "expected_attendance"], ids=lambda s: s.event_name
)
def test_the_event_shows_the_attendance_its_requests_leave_it_with(db: Session, seeded: Seeded):
    """An approved change is already on the event; a pending, rejected or withdrawn one is not,
    so the event still has the figure the request recorded as current."""
    attendance = db.get(Event, seeded.event_id).expected_attendance

    assert attendance == (seeded.proposed if seeded.status == "APPROVED" else seeded.current)


@pytest.mark.story("19.2", ac=1)
def test_chloes_queue_holds_the_customer_forums_pending_request(client):
    entry = _queue(client, Users.COORDINATOR)[str(ChangeRequests.CUSTOMER_FORUM_ATTENDANCE)]

    assert entry["event_name"] == "Customer Success Forum"
    assert entry["event_status"] == "PLANNING"
    assert entry["field"] == "expected_attendance"
    assert (entry["current_value"], entry["proposed_value"]) == (150, 180)
    assert entry["reason"]
    assert entry["status"] == "PENDING"
    assert entry["requested_by_name"] == Users.ORGANISER_2.full_name
    assert entry["is_out_of_date"] is False


@pytest.mark.story("19.2", ac=1)
def test_carls_queue_holds_the_sales_kickoffs_pending_date_change(client):
    entry = _queue(client, Users.COORDINATOR_2)[str(ChangeRequests.SALES_KICKOFF_SCHEDULE)]

    assert entry["event_name"] == "Annual Sales Kickoff"
    assert entry["field"] == "schedule"
    assert entry["current_value"] == _KICKOFF_NOW
    assert entry["proposed_value"] == _NEXT_DAY
    assert entry["status"] == "PENDING"
    assert entry["requested_by_name"] == Users.ORGANISER_2.full_name
    assert entry["is_out_of_date"] is False


@pytest.mark.story("19.2", ac=1)
def test_each_coordinators_record_holds_only_their_own_events_requests(client):
    """Chloe's record has Olivia's approved and rejected ones; Carl's the withdrawn one and the
    approved one on Nadia's event. Neither holds the other's."""
    chloe = _queue(client, Users.COORDINATOR)
    carl = _queue(client, Users.COORDINATOR_2)

    for seeded in SEEDED:
        own, other = (chloe, carl) if seeded.coordinator == Users.COORDINATOR else (carl, chloe)
        assert own[str(seeded.id)]["status"] == seeded.status, seeded.event_name
        assert str(seeded.id) not in other, seeded.event_name


@pytest.mark.story("19.2", ac=1)
def test_the_rejection_and_the_approval_read_with_who_decided(client):
    queue = _queue(client, Users.COORDINATOR)

    rejected = queue[str(ChangeRequests.CHARITY_GALA_ATTENDANCE)]
    assert (
        rejected["decision_reason"]
        == _BY_ID[ChangeRequests.CHARITY_GALA_ATTENDANCE].decision_reason
    )
    assert rejected["decided_by_name"] == Users.COORDINATOR.full_name
    approved = queue[str(ChangeRequests.FIRESIDE_ATTENDANCE)]
    assert approved["decided_by_name"] == Users.COORDINATOR.full_name
    assert approved["decision_reason"] is None


@pytest.mark.story("19.2", ac=1)
@pytest.mark.parametrize(
    ("organiser", "statuses"),
    [
        (Users.ORGANISER, {"APPROVED", "REJECTED"}),
        (Users.ORGANISER_2, {"PENDING", "WITHDRAWN"}),
    ],
    ids=["Olivia", "Omar"],
)
def test_an_organiser_reads_their_requests_on_their_events_in_more_than_one_status(
    client, organiser, statuses: set[str]
):
    client.login(organiser)
    mine = [seeded for seeded in SEEDED if seeded.organiser == organiser]

    seen = []
    for seeded in mine:
        response = client.get(f"/events/{seeded.event_id}/change-requests")
        assert response.status_code == 200, response.text
        row = {row["id"]: row for row in response.json()}[str(seeded.id)]
        assert row["proposed_value"] == seeded.proposed
        seen.append(row["status"])

    assert set(seen) == statuses


@pytest.mark.story("19.2", ac=1)
def test_nadias_change_approved_notification_names_a_request_that_exists(db: Session):
    """Before c14 it named a request no row held."""
    notification = db.get(Notification, Notifications.CHANGE_APPROVED)

    request = db.scalar(
        select(EventChangeRequest).where(EventChangeRequest.id == notification.related_entity_id)
    )

    assert request is not None
    assert request.event_id == notification.event_id == Events.NOTICE_GALA
    assert request.status == "APPROVED"
    assert request.requested_by_id == notification.recipient_id == Users.NOTICE.id
