"""Business logic for event requests (story 2.1: create, edit/remove, view, submit).

Routers translate the exceptions raised here into HTTP statuses, keeping the rules in plain
functions that are easy to unit-test, matching app/venues/service.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.permissions import Permission, role_has
from app.common.audit import record_audit
from app.events.models import (
    AccessibilityFeature,
    EquipmentRequestStatus,
    EquipmentType,
    Event,
    EventAccessibilityNeed,
    EventEquipmentRequest,
    EventRequiredFacility,
    EventStatus,
    Facility,
    RoomLayout,
)
from app.events.schemas import (
    ACCESSIBILITY_CONFLICT_MESSAGE,
    INVALID_PERIOD_MESSAGE,
    EventCreate,
    EventUpdate,
)

NOT_OWNER_MESSAGE = "You may only edit your own event requests."
NOT_VIEWABLE_MESSAGE = "You may only view your own event requests."
NOT_EDITABLE_MESSAGE = "This request can no longer be edited because it has already been submitted."
ALREADY_SUBMITTED_MESSAGE = "This request has already been submitted."

# AC10: the friendly names shown when a field the database requires once submitted is missing.
# Order matches the database's own ck_events_submitted_fields_complete constraint.
_MANDATORY_FOR_SUBMISSION = (
    ("purpose", "purpose"),
    ("starts_at", "proposed start date and time"),
    ("ends_at", "proposed end date and time"),
    ("expected_attendance", "expected attendance"),
)


class EventNotFound(LookupError):
    pass


class NotPermittedToView(PermissionError):
    def __init__(self, message: str = NOT_VIEWABLE_MESSAGE):
        super().__init__(message)


class NotPermittedToEdit(PermissionError):
    def __init__(self, message: str = NOT_OWNER_MESSAGE):
        super().__init__(message)


class EventNotEditable(ValueError):
    def __init__(self, message: str = NOT_EDITABLE_MESSAGE):
        super().__init__(message)


class EventAlreadySubmitted(ValueError):
    """AC9/AC12: submission is only valid from DRAFT."""

    def __init__(self, message: str = ALREADY_SUBMITTED_MESSAGE):
        super().__init__(message)


class EventIncompleteForSubmission(ValueError):
    """AC10: the fields the database itself requires once a request is no longer a draft."""

    def __init__(self, missing: list[str]):
        super().__init__(f"Cannot submit: {', '.join(missing)} must be filled in first.")
        self.missing = missing


class UnknownReferenceCode(ValueError):
    def __init__(self, kind: str, codes: list[str]):
        super().__init__(f"Unknown {kind} code(s): {', '.join(codes)}")
        self.kind = kind
        self.codes = codes


class UnknownEquipmentType(ValueError):
    def __init__(self, ids: list[uuid.UUID]):
        super().__init__(f"Unknown equipment type id(s): {', '.join(str(i) for i in ids)}")
        self.ids = ids


class EventPeriodInvalid(ValueError):
    def __init__(self, message: str = INVALID_PERIOD_MESSAGE):
        super().__init__(message)


class AccessibilityConflict(ValueError):
    def __init__(self, message: str = ACCESSIBILITY_CONFLICT_MESSAGE):
        super().__init__(message)


# --- reads -------------------------------------------------------------------------------
def _load_event(db: Session, event_id: uuid.UUID) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        raise EventNotFound(event_id)
    return event


def get_event(db: Session, event_id: uuid.UUID, *, actor: User) -> Event:
    """AC8: the reviewing coordinator (or the owning organiser) sees every recorded detail."""
    event = _load_event(db, event_id)
    if not _can_view(event, actor):
        raise NotPermittedToView()
    return event


def list_events(db: Session, *, actor: User) -> list[Event]:
    """Coordinators see every request; organisers see only their own (needed to find a draft
    again to satisfy AC7 across sessions - no AC asks for a list endpoint by itself)."""
    query = select(Event).order_by(Event.created_at.desc())
    if role_has(actor.role_code, Permission.EVENTS_READ_ALL):
        return list(db.scalars(query).all())
    if role_has(actor.role_code, Permission.EVENTS_READ_OWN):
        return list(db.scalars(query.where(Event.organiser_id == actor.id)).all())
    raise NotPermittedToView()


def _can_view(event: Event, actor: User) -> bool:
    if role_has(actor.role_code, Permission.EVENTS_READ_ALL):
        return True
    return role_has(actor.role_code, Permission.EVENTS_READ_OWN) and event.organiser_id == actor.id


# --- writes ------------------------------------------------------------------------------
_SCALAR_FIELDS = (
    "name",
    "purpose",
    "description",
    "starts_at",
    "ends_at",
    "expected_attendance",
    "preferred_location",
    "required_layout_code",
    "venue_requirement_notes",
    "accessibility_none_required",
    "accessibility_notes",
)


def create_event(db: Session, data: EventCreate, *, actor: User) -> Event:
    """AC1: an event request can be created with, at minimum, a name."""
    _validate_reference_codes(db, data)
    event = Event(
        **{f: getattr(data, f) for f in _SCALAR_FIELDS},
        status=EventStatus.DRAFT,
        organiser_id=actor.id,
        organisation_id=actor.organisation_id,
    )
    _replace_line_items(event, data)
    db.add(event)
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="EVENT_CREATED",
        entity_type="event",
        entity_id=event.id,
        details={"name": event.name},
        commit=False,
    )
    db.commit()
    db.refresh(event)
    return event


def update_event(db: Session, event_id: uuid.UUID, data: EventUpdate, *, actor: User) -> Event:
    """AC7: any recorded detail, requirement or equipment item can be edited or removed, as
    long as the request is still a DRAFT and belongs to the actor."""
    event = _load_event(db, event_id)
    if event.organiser_id != actor.id:
        raise NotPermittedToEdit()
    if event.status != EventStatus.DRAFT:
        raise EventNotEditable()
    _validate_reference_codes(db, data)

    changes = data.model_dump(exclude_unset=True)
    before: dict[str, Any] = {}
    for field in _SCALAR_FIELDS:
        if field in changes and getattr(event, field) != changes[field]:
            before[field] = _jsonable(getattr(event, field))
            setattr(event, field, changes[field])

    if "required_facilities" in changes:
        before["required_facilities"] = [f.facility_code for f in event.required_facilities]
    if "accessibility_features" in changes:
        before["accessibility_features"] = [a.feature_code for a in event.accessibility_features]
    if "equipment_requests" in changes:
        before["equipment_requests"] = [
            {"equipment_type_id": str(e.equipment_type_id), "quantity": e.quantity}
            for e in event.equipment_requests
        ]
    _replace_line_items(event, data, only_present=True)

    # Authoritative check against the merged record - a partial update may only have supplied
    # one side of a relationship (see EventUpdate's docstring in schemas.py).
    if (
        event.starts_at is not None
        and event.ends_at is not None
        and event.ends_at <= event.starts_at
    ):
        db.rollback()
        raise EventPeriodInvalid()
    if event.accessibility_none_required and len(event.accessibility_features) > 0:
        db.rollback()
        raise AccessibilityConflict()

    db.flush()
    after = {k: _jsonable(changes[k]) if k in changes else None for k in before}
    record_audit(
        db,
        actor=actor,
        action="EVENT_UPDATED",
        entity_type="event",
        entity_id=event.id,
        details={k: {"from": before[k], "to": after[k]} for k in before},
        commit=False,
    )
    db.commit()
    db.refresh(event)
    return event


def submit_event(db: Session, event_id: uuid.UUID, *, actor: User) -> Event:
    """AC9-12: an organiser submits their own, complete, still-draft request."""
    event = _load_event(db, event_id)
    if event.organiser_id != actor.id:
        raise NotPermittedToEdit()
    if event.status != EventStatus.DRAFT:
        raise EventAlreadySubmitted()
    missing = [label for field, label in _MANDATORY_FOR_SUBMISSION if getattr(event, field) is None]
    if missing:
        raise EventIncompleteForSubmission(missing)

    event.status = EventStatus.SUBMITTED
    event.submitted_at = datetime.now(UTC)
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="EVENT_SUBMITTED",
        entity_type="event",
        entity_id=event.id,
        details={},
        commit=False,
    )
    db.commit()
    db.refresh(event)
    return event


# --- helpers -----------------------------------------------------------------------------
def _validate_reference_codes(db: Session, data: EventCreate | EventUpdate) -> None:
    checks = (
        ("facility", Facility, [f.code for f in (data.required_facilities or [])]),
        (
            "accessibility feature",
            AccessibilityFeature,
            [a.code for a in (data.accessibility_features or [])],
        ),
    )
    for kind, model, codes in checks:
        if not codes:
            continue
        wanted = set(codes)
        known = set(db.scalars(select(model.code).where(model.code.in_(wanted))).all())
        missing = sorted(wanted - known)
        if missing:
            raise UnknownReferenceCode(kind, missing)

    layout_code = getattr(data, "required_layout_code", None)
    if layout_code and db.get(RoomLayout, layout_code) is None:
        raise UnknownReferenceCode("layout", [layout_code])

    equipment_ids = [e.equipment_type_id for e in (data.equipment_requests or [])]
    if equipment_ids:
        wanted_ids = set(equipment_ids)
        known_ids = set(
            db.scalars(select(EquipmentType.id).where(EquipmentType.id.in_(wanted_ids))).all()
        )
        missing_ids = sorted(wanted_ids - known_ids, key=str)
        if missing_ids:
            raise UnknownEquipmentType(missing_ids)


def _replace_line_items(
    event: Event, data: EventCreate | EventUpdate, *, only_present: bool = False
) -> None:
    present = data.model_dump(exclude_unset=True) if only_present else None
    if present is None or "required_facilities" in present:
        event.required_facilities = [
            EventRequiredFacility(facility_code=f.code, notes=f.notes)
            for f in _dedupe_by_code(data.required_facilities or [])
        ]
    if present is None or "accessibility_features" in present:
        event.accessibility_features = [
            EventAccessibilityNeed(feature_code=a.code, notes=a.notes)
            for a in _dedupe_by_code(data.accessibility_features or [])
        ]
    if present is None or "equipment_requests" in present:
        event.equipment_requests = [
            EventEquipmentRequest(
                equipment_type_id=e.equipment_type_id,
                quantity=e.quantity,
                technical_notes=e.technical_notes,
                status=EquipmentRequestStatus.REQUESTED,
            )
            for e in (data.equipment_requests or [])
        ]


def _dedupe_by_code(items):
    seen: set[str] = set()
    for item in items:
        if item.code not in seen:
            seen.add(item.code)
            yield item


def _jsonable(value: Any) -> Any:
    """Recurse into dicts/lists: unlike venues' line items, equipment_requests carries a UUID
    (equipment_type_id), so a shallow check for `list` alone (venues' original version) is not
    enough - json.dumps chokes on a UUID buried inside a list of dicts."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)
