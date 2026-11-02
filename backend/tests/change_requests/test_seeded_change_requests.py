"""c14 - the seed's sample change requests, so a coordinator's queue and an organiser's event pages
have change requests to show without anyone raising one first. A chore, so it has no acceptance
criteria of its own; each case is tagged story 19.2 AC1, the queue and record these rows feed.

Each case below reads the seeded rows as the app serves them or as the database holds them, and
compares them with the figures written out in ``SEEDED``, not with each other. Raising, listing in
every status and ordering are 19.1 and 19.2's own cases (test_raise_change_request.py,
test_decide_change_request.py), made from factories; nothing here repeats them.

Happy path
* Each coordinator's queue holds their own pending requests, each reading with its two values, its
  reason and who asked; Chloe's has three, Carl's two.
* The rest of each coordinator's record, approved, rejected and withdrawn, and never the other's.
* Each organiser reads their own requests on their events' pages, in every status.
* The sample spreads over every status, as a real queue would.

Boundary
* Every seeded value is canonical JSON, as the service writes it, so the app reads it back.
* A pending request is not out of date: it records the value its event has now.

Edge
* An approved request records a change the event already shows; a rejected, withdrawn or pending
  one leaves the event's value as it was recorded.
* A decision names a coordinator and a time; a rejection also its reason; a pending or withdrawn
  request names neither.
* A decision comes after the request, and a request after its event was approved.
* Nadia's "Change approved" notification names a request that exists, on her event.

Permission and conflict cases do not apply: the seed adds no rule, and who may decide (19.2 AC6) and
the one pending request a field takes (19.1 AC6) are proved from factories in the files above. The
index behind AC6 would also refuse a seed that broke it, so the seed loading proves the rest.
"""

import json
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.change_requests.models import EventChangeRequest
from app.events.models import Event
from app.notifications.models import Notification
from tests.support.seed import ChangeRequests, Events, Notifications, Users

_SALES_KICKOFF = {"ends_at": "2027-08-18T10:00:00+00:00", "starts_at": "2027-08-18T01:00:00+00:00"}
_SALES_KICKOFF_NEXT_DAY = {
    "ends_at": "2027-08-19T10:00:00+00:00",
    "starts_at": "2027-08-19T01:00:00+00:00",
}
_FIRESIDE = {"ends_at": "2027-06-01T09:00:00+00:00", "starts_at": "2027-06-01T07:00:00+00:00"}
_FIRESIDE_LATER = {"ends_at": "2027-06-01T10:00:00+00:00", "starts_at": "2027-06-01T08:00:00+00:00"}
_TOWNHALL = {"ends_at": "2027-01-15T04:00:00+00:00", "starts_at": "2027-01-15T02:00:00+00:00"}
_TOWNHALL_EARLIER = {
    "ends_at": "2027-01-14T04:00:00+00:00",
    "starts_at": "2027-01-14T02:00:00+00:00",
}
_DEMO_DAY = {"ends_at": "2027-07-01T04:00:00+00:00", "starts_at": "2027-07-01T01:00:00+00:00"}
_DEMO_DAY_EVENING = {
    "ends_at": "2027-07-01T13:00:00+00:00",
    "starts_at": "2027-07-01T10:00:00+00:00",
}
_CHARITY_GALA = {"ends_at": "2027-08-01T14:00:00+00:00", "starts_at": "2027-08-01T10:00:00+00:00"}
_CHARITY_GALA_NEXT_WEEK = {
    "ends_at": "2027-08-08T14:00:00+00:00",
    "starts_at": "2027-08-08T10:00:00+00:00",
}

_REJECTION_REASONS = {
    ChangeRequests.CHARITY_GALA_ATTENDANCE: "No banquet venue we can book seats 400.",
    ChangeRequests.HOMECOMING_ATTENDANCE: "The campus venues we hold seat far fewer than that.",
    ChangeRequests.DEMO_DAY_SCHEDULE: "The venue is booked that evening, so the time stays.",
}


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


def _attendance(id, event_id, name, organiser, coordinator, current, proposed, status):
    return Seeded(
        id, event_id, name, organiser, coordinator, "expected_attendance", current, proposed, status
    )


def _schedule(id, event_id, name, organiser, coordinator, current, proposed, status):
    return Seeded(id, event_id, name, organiser, coordinator, "schedule", current, proposed, status)


SEEDED = (
    # Pending
    _attendance(
        ChangeRequests.CUSTOMER_FORUM_ATTENDANCE,
        Events.CUSTOMER_FORUM,
        "Customer Success Forum",
        Users.ORGANISER_2,
        Users.COORDINATOR,
        150,
        180,
        "PENDING",
    ),
    _attendance(
        ChangeRequests.ROADMAP_TOWNHALL_ATTENDANCE,
        Events.APPROVED_3,
        "Product Roadmap Townhall",
        Users.ORGANISER_2,
        Users.COORDINATOR,
        300,
        260,
        "PENDING",
    ),
    _schedule(
        ChangeRequests.FIRESIDE_SCHEDULE,
        Events.APPROVED_4,
        "Founders Day Fireside Chat",
        Users.ORGANISER,
        Users.COORDINATOR,
        _FIRESIDE,
        _FIRESIDE_LATER,
        "PENDING",
    ),
    _schedule(
        ChangeRequests.SALES_KICKOFF_SCHEDULE,
        Events.SALES_KICKOFF,
        "Annual Sales Kickoff",
        Users.ORGANISER_2,
        Users.COORDINATOR_2,
        _SALES_KICKOFF,
        _SALES_KICKOFF_NEXT_DAY,
        "PENDING",
    ),
    _attendance(
        ChangeRequests.PARTNER_GALA_ATTENDANCE,
        Events.PARTNER_GALA,
        "Year-End Partner Gala",
        Users.ORGANISER_2,
        Users.COORDINATOR_2,
        180,
        220,
        "PENDING",
    ),
    # Approved
    _attendance(
        ChangeRequests.FIRESIDE_ATTENDANCE,
        Events.APPROVED_4,
        "Founders Day Fireside Chat",
        Users.ORGANISER,
        Users.COORDINATOR,
        180,
        200,
        "APPROVED",
    ),
    _schedule(
        ChangeRequests.ROADMAP_TOWNHALL_SCHEDULE,
        Events.APPROVED_3,
        "Product Roadmap Townhall",
        Users.ORGANISER_2,
        Users.COORDINATOR,
        _TOWNHALL_EARLIER,
        _TOWNHALL,
        "APPROVED",
    ),
    _attendance(
        ChangeRequests.NOTICE_GALA_ATTENDANCE,
        Events.NOTICE_GALA,
        "Harbour Lights Gala",
        Users.NOTICE,
        Users.COORDINATOR_2,
        40,
        60,
        "APPROVED",
    ),
    _attendance(
        ChangeRequests.DEMO_DAY_ATTENDANCE,
        Events.APPROVED_5,
        "Investor Demo Day",
        Users.ORGANISER_2,
        Users.COORDINATOR_2,
        80,
        100,
        "APPROVED",
    ),
    # Rejected
    _attendance(
        ChangeRequests.CHARITY_GALA_ATTENDANCE,
        Events.APPROVED_6,
        "Winter Charity Gala",
        Users.ORGANISER,
        Users.COORDINATOR,
        220,
        400,
        "REJECTED",
    ),
    _attendance(
        ChangeRequests.HOMECOMING_ATTENDANCE,
        Events.APPROVED_7,
        "Alumni Homecoming Weekend",
        Users.ORGANISER_2,
        Users.COORDINATOR_2,
        100,
        250,
        "REJECTED",
    ),
    _schedule(
        ChangeRequests.DEMO_DAY_SCHEDULE,
        Events.APPROVED_5,
        "Investor Demo Day",
        Users.ORGANISER_2,
        Users.COORDINATOR_2,
        _DEMO_DAY,
        _DEMO_DAY_EVENING,
        "REJECTED",
    ),
    # Withdrawn
    _attendance(
        ChangeRequests.FINTECH_BREAKFAST_ATTENDANCE,
        Events.FINTECH_BREAKFAST,
        "Fintech Leaders Breakfast",
        Users.ORGANISER_2,
        Users.COORDINATOR_2,
        45,
        60,
        "WITHDRAWN",
    ),
    _schedule(
        ChangeRequests.CHARITY_GALA_SCHEDULE,
        Events.APPROVED_6,
        "Winter Charity Gala",
        Users.ORGANISER,
        Users.COORDINATOR,
        _CHARITY_GALA,
        _CHARITY_GALA_NEXT_WEEK,
        "WITHDRAWN",
    ),
)
_IDS = lambda seeded: f"{seeded.event_name} {seeded.field} {seeded.status}"  # noqa: E731


def _row(db: Session, request_id: uuid.UUID) -> EventChangeRequest:
    row = db.get(EventChangeRequest, request_id)
    assert row is not None, f"seeded change request {request_id} is missing"
    return row


def _queue(client, coordinator) -> dict[str, dict]:
    client.login(coordinator)
    response = client.get("/change-requests")
    assert response.status_code == 200, response.text
    return {entry["id"]: entry for entry in response.json()}


def _event_value(event: Event, field: str) -> Any:
    if field == "expected_attendance":
        return event.expected_attendance
    return {
        "ends_at": event.ends_at.astimezone(UTC).isoformat(),
        "starts_at": event.starts_at.astimezone(UTC).isoformat(),
    }


@pytest.mark.story("19.2", ac=1)
@pytest.mark.parametrize("seeded", SEEDED, ids=_IDS)
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
@pytest.mark.parametrize("seeded", SEEDED, ids=_IDS)
def test_a_seeded_value_is_canonical_json(db: Session, seeded: Seeded):
    """Stored the way the service writes it - keys sorted, no spaces - so the same value always
    reads the same and an identical proposal is recognised (19.1 AC4)."""
    row = _row(db, seeded.id)

    for stored in (row.current_value, row.proposed_value):
        assert stored == json.dumps(json.loads(stored), sort_keys=True, separators=(",", ":"))


@pytest.mark.story("19.2", ac=1)
@pytest.mark.parametrize("seeded", SEEDED, ids=_IDS)
def test_a_seeded_decision_names_who_decided_and_when(db: Session, seeded: Seeded):
    row = _row(db, seeded.id)

    if seeded.status in ("APPROVED", "REJECTED"):
        assert row.decided_by_id == seeded.coordinator.id
        assert row.decided_at is not None
        assert row.decided_at > row.created_at
    else:
        assert row.decided_by_id is None
        assert row.decided_at is None
    assert row.decision_reason == _REJECTION_REASONS.get(seeded.id)


@pytest.mark.story("19.2", ac=1)
@pytest.mark.parametrize("seeded", SEEDED, ids=_IDS)
def test_a_seeded_request_comes_after_its_event_was_approved(db: Session, seeded: Seeded):
    """A request is raised on an approved event, so none is older than the event's approval."""
    event = db.get(Event, seeded.event_id)

    assert event.decided_at is not None
    assert _row(db, seeded.id).created_at > event.decided_at


@pytest.mark.story("19.2", ac=1)
@pytest.mark.parametrize("seeded", SEEDED, ids=_IDS)
def test_a_seeded_request_sits_on_an_event_its_coordinator_owns(db: Session, seeded: Seeded):
    """It is in that coordinator's queue and no other's, and the event is the one it names."""
    event = db.get(Event, seeded.event_id)

    assert event.name == seeded.event_name
    assert event.organiser_id == seeded.organiser.id
    assert event.assigned_coordinator_id == seeded.coordinator.id


@pytest.mark.story("19.2", ac=1)
@pytest.mark.parametrize("seeded", SEEDED, ids=_IDS)
def test_the_event_shows_the_value_its_requests_leave_it_with(db: Session, seeded: Seeded):
    """An approved change is already on the event; a pending, rejected or withdrawn one is not, so
    the event still has the value the request recorded as current."""
    event = db.get(Event, seeded.event_id)

    expected = seeded.proposed if seeded.status == "APPROVED" else seeded.current
    assert _event_value(event, seeded.field) == expected


@pytest.mark.story("19.2", ac=1)
def test_the_sample_spreads_over_every_status_as_a_real_queue_does(db: Session):
    """Not one of each: several pending and decided, some withdrawn, in both coordinators' hands."""
    rows = [_row(db, seeded.id) for seeded in SEEDED]

    assert Counter(row.status for row in rows) == {
        "PENDING": 5,
        "APPROVED": 4,
        "REJECTED": 3,
        "WITHDRAWN": 2,
    }
    assert (
        Counter((seeded.coordinator, seeded.status) for seeded in SEEDED)[
            (Users.COORDINATOR, "PENDING")
        ]
        == 3
    )
    assert (
        Counter((seeded.coordinator, seeded.status) for seeded in SEEDED)[
            (Users.COORDINATOR_2, "PENDING")
        ]
        == 2
    )
    assert {row.field_name for row in rows} == {"expected_attendance", "schedule"}


@pytest.mark.story("19.2", ac=1)
@pytest.mark.parametrize(
    "coordinator", [Users.COORDINATOR, Users.COORDINATOR_2], ids=["Chloe", "Carl"]
)
def test_a_coordinators_queue_holds_their_pending_requests_with_what_was_asked(client, coordinator):
    queue = _queue(client, coordinator)

    for seeded in (s for s in SEEDED if s.coordinator == coordinator and s.status == "PENDING"):
        entry = queue[str(seeded.id)]
        assert entry["event_name"] == seeded.event_name
        assert entry["event_status"] == "PLANNING"
        assert entry["field"] == seeded.field
        assert entry["current_value"] == seeded.current
        assert entry["proposed_value"] == seeded.proposed
        assert entry["reason"]
        assert entry["status"] == "PENDING"
        assert entry["requested_by_name"] == seeded.organiser.full_name
        assert entry["is_out_of_date"] is False


@pytest.mark.story("19.2", ac=1)
def test_each_coordinators_record_holds_only_their_own_events_requests(client):
    """Chloe's record has Olivia's and Omar's on her events; Carl's his, Nadia's included.
    Neither holds the other's."""
    chloe = _queue(client, Users.COORDINATOR)
    carl = _queue(client, Users.COORDINATOR_2)

    for seeded in SEEDED:
        own, other = (chloe, carl) if seeded.coordinator == Users.COORDINATOR else (carl, chloe)
        assert own[str(seeded.id)]["status"] == seeded.status, seeded.event_name
        assert str(seeded.id) not in other, seeded.event_name


@pytest.mark.story("19.2", ac=1)
def test_the_queue_reads_pending_requests_before_the_record_oldest_first(client):
    """What waits comes first, oldest first, so the pending ones the seed raises over a fortnight
    read in the order they were raised."""
    for coordinator in (Users.COORDINATOR, Users.COORDINATOR_2):
        queue = list(_queue(client, coordinator).values())
        seeded_ids = {str(seeded.id) for seeded in SEEDED if seeded.coordinator == coordinator}
        mine = [entry for entry in queue if entry["id"] in seeded_ids]
        statuses = [entry["status"] for entry in mine]
        pending = [entry for entry in mine if entry["status"] == "PENDING"]

        assert statuses[: len(pending)] == ["PENDING"] * len(pending)
        assert [entry["created_at"] for entry in pending] == sorted(
            entry["created_at"] for entry in pending
        )


@pytest.mark.story("19.2", ac=1)
def test_the_rejections_and_an_approval_read_with_who_decided(client):
    for coordinator in (Users.COORDINATOR, Users.COORDINATOR_2):
        queue = _queue(client, coordinator)

        for seeded in (s for s in SEEDED if s.coordinator == coordinator):
            if seeded.status in ("APPROVED", "REJECTED"):
                entry = queue[str(seeded.id)]
                assert entry["decided_by_name"] == coordinator.full_name
                assert entry["decision_reason"] == _REJECTION_REASONS.get(seeded.id)


@pytest.mark.story("19.2", ac=1)
@pytest.mark.parametrize("organiser", [Users.ORGANISER, Users.ORGANISER_2], ids=["Olivia", "Omar"])
def test_an_organiser_reads_their_requests_on_their_events_in_every_status(client, organiser):
    client.login(organiser)
    mine = [seeded for seeded in SEEDED if seeded.organiser == organiser]

    seen = []
    for seeded in mine:
        response = client.get(f"/events/{seeded.event_id}/change-requests")
        assert response.status_code == 200, response.text
        row = {row["id"]: row for row in response.json()}[str(seeded.id)]
        assert row["proposed_value"] == seeded.proposed
        seen.append(row["status"])

    assert set(seen) == {"PENDING", "APPROVED", "REJECTED", "WITHDRAWN"}


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
