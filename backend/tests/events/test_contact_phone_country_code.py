"""Story 2.1 AC21, AC23, AC24 (fix f2.1.4) - the point of contact's phone, saved with its calling
code and without the spaces and dashes typed in it.

AC21 The phone has a Country or region picker in front of the number, offering every country and
     territory with a calling code, Singapore (+65) the default. The number is typed without the
     calling code; spaces and dashes may be typed and are removed before saving, so the phone is
     saved and shown as "+", the calling code and the number, e.g. +6591234567. AC13's 8 to 15
     digits still apply, counted with the calling code.
AC23 (Edge) A phone saved before the fix is cleaned the same way. The same number sent again with
     other spaces or dashes is not a change.
AC24 (Permission) The phone is saved the same way wherever it is entered: the request form, the
     coordinator's correction (7.2 AC4) and the point-of-contact update (19.1 AC2).

What the picker does - its choices, the calling code put in front of the number, the "+" and
leading 0 refusals (AC22), and how a saved phone reopens (AC23) - is
tests/e2e/event-request.spec.ts and tests/e2e/change-requests.spec.ts. AC13's own rules (which
characters, 8 to 15 digits, at most 50 characters) are test_event_request_poc.py. A phone saved
before the fix is built with make_event, because the API now cleans every phone it saves.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dbtool.migrate import MIGRATIONS_DIR
from app.events.models import Event, EventStatus
from tests.support.factories import create_event_request, make_event
from tests.support.seed import Events, Users

_CLEANING_MIGRATION = MIGRATIONS_DIR / "024_contact_phone_without_separators.sql"
_SAVED_PHONE = "+6561112233"


# --- helpers -----------------------------------------------------------------------------------
def _stored_phone(db: Session, event_id) -> str | None:
    return db.execute(
        text("SELECT contact_phone FROM events WHERE id = :id"), {"id": event_id}
    ).scalar_one()


def _planning_event(db: Session, contact_phone: str | None = _SAVED_PHONE) -> Event:
    """Olivia's approved event, whose point of contact she may update directly (19.1 AC2)."""
    return make_event(
        db,
        status=EventStatus.PLANNING,
        assigned_coordinator_id=Users.COORDINATOR.id,
        contact_name="Olivia Organiser",
        contact_email="olivia.events@acme.example",
        contact_phone=contact_phone,
    )


# --- AC21: saved without the spaces and dashes typed --------------------------------------------
@pytest.mark.story("2.1", ac=21)
def test_a_phone_typed_with_spaces_and_dashes_is_saved_without_them(organiser_client, db: Session):
    created = create_event_request(organiser_client, contact_phone="+60 12-345 6789")

    assert created["contact_phone"] == "+60123456789"
    assert _stored_phone(db, created["id"]) == "+60123456789"


@pytest.mark.story("2.1", ac=21)
def test_a_draft_edit_saves_the_phone_without_spaces_or_dashes(organiser_client, db: Session):
    created = create_event_request(organiser_client)

    response = organiser_client.patch(
        f"/events/{created['id']}", json={"contact_phone": "+44 7911-123 456"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["contact_phone"] == "+447911123456"
    assert _stored_phone(db, created["id"]) == "+447911123456"


# --- AC24: the same wherever the phone is entered -----------------------------------------------
@pytest.mark.story("2.1", ac=24)
def test_the_coordinators_correction_saves_the_phone_without_spaces_or_dashes(
    coordinator_client, db: Session
):
    event = coordinator_client.get(f"/events/{Events.SUBMITTED}").json()

    response = coordinator_client.patch(
        f"/events/{Events.SUBMITTED}/review-details",
        json={"expected_updated_at": event["updated_at"], "contact_phone": "+852 1234-5678"},
    )

    assert response.status_code == 200, response.text
    assert _stored_phone(db, Events.SUBMITTED) == "+85212345678"


@pytest.mark.story("2.1", ac=24)
def test_the_point_of_contact_update_saves_the_phone_without_spaces_or_dashes(
    organiser_client, db: Session
):
    event = _planning_event(db)

    response = organiser_client.patch(
        f"/events/{event.id}/point-of-contact", json={"contact_phone": "+81 90-1234-5678"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["contact_phone"] == "+819012345678"
    assert _stored_phone(db, event.id) == "+819012345678"


# --- AC23: the same number, other spacing; phones saved before ----------------------------------
@pytest.mark.story("2.1", ac=23)
def test_the_same_number_with_other_spacing_is_not_a_change(organiser_client, db: Session):
    event = _planning_event(db)

    response = organiser_client.patch(
        f"/events/{event.id}/point-of-contact", json={"contact_phone": "+65 6111-2233"}
    )

    assert response.status_code == 200, response.text
    assert _stored_phone(db, event.id) == _SAVED_PHONE
    logged = db.execute(
        text(
            "SELECT count(*) FROM audit_log"
            " WHERE action = 'EVENT_CONTACT_UPDATED' AND entity_id = :e"
        ),
        {"e": event.id},
    ).scalar()
    assert logged == 0


@pytest.mark.story("2.1", ac=23)
@pytest.mark.parametrize(
    ("saved_before", "cleaned"),
    [
        ("+65 6111 2233", "+6561112233"),
        ("+60 12-345 6789", "+60123456789"),
        ("9123-4567", "91234567"),
        ("+6591234567", "+6591234567"),
        (None, None),
    ],
)
def test_the_migration_cleans_phones_saved_before(db: Session, saved_before, cleaned):
    event = _planning_event(db, contact_phone=saved_before)

    db.connection().exec_driver_sql(_CLEANING_MIGRATION.read_text(encoding="utf-8"))

    assert _stored_phone(db, event.id) == cleaned
