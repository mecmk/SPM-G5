"""Role-based access control matrix (story 1.2).

AC1 of story 1.2 says "each user role has a defined set of permitted functions" - this file IS
that definition. Roles come from the `roles` table (seeded in backend/db/seed); the permissions
each role holds are declared here in code so they are versioned, reviewed and unit-tested with
the rest of the backend.

How to use in a router::

    from app.auth.deps import require_permission
    from app.auth.permissions import Permission

    @router.post("/venues", dependencies=[Depends(require_permission(Permission.VENUES_MANAGE))])
    def create_venue(...): ...

How to extend: add a member to ``Permission`` and grant it in ``ROLE_PERMISSIONS``. The test
``tests/auth/test_rbac.py`` checks that every permission is granted to at least one role and
that every role has a defined (non-empty) set.

Relationship-based rules ("an organiser may only see *their own* events") are deliberately not
expressed here - they need the record, so they belong in the feature's service layer, e.g.
``events.service.assert_can_view(user, event)``.
"""

from __future__ import annotations

from enum import StrEnum


class RoleCode(StrEnum):
    EVENT_ORGANISER = "EVENT_ORGANISER"
    EVENT_COORDINATOR = "EVENT_COORDINATOR"
    VENUE_STAFF = "VENUE_STAFF"
    TECH_SUPPORT_STAFF = "TECH_SUPPORT_STAFF"
    ATTENDEE = "ATTENDEE"


class Permission(StrEnum):
    """Functions a role may perform. Grouped by functionality area / backlog epic."""

    # --- Venue catalogue (8.x) & availability (9.x) ---
    VENUES_READ = "venues:read"  # browse catalogue, view characteristics (8.1, 8.2)
    VENUES_MANAGE = "venues:manage"  # create / update / withdraw venues (8.3, 8.4)
    VENUE_UNAVAILABILITY_MANAGE = "venue_unavailability:manage"  # maintenance periods (9.3)
    VENUE_CALENDAR_READ = "venue_calendar:read"  # availability calendar & search (9.x, 10.x)

    # --- Event requests (2.x, 3.x) ---
    EVENTS_CREATE = "events:create"  # raise / draft / submit own requests (2.1, 3.x)
    EVENTS_READ_OWN = "events:read_own"  # organiser sees own events (2.6, 7.1)
    EVENTS_READ_ALL = "events:read_all"  # internal staff see every event (7.1)
    EVENTS_REVIEW = "events:review"  # queue, clarify, approve, reject, assign (4.x, 5.x)
    EVENTS_EDIT_ROUTINE = "events:edit_routine"  # routine field edits (7.2)
    EVENTS_CANCEL = "events:cancel"  # cancel event (6.5)
    EVENT_CHANGE_REQUESTS_CREATE = "event_change_requests:create"  # organiser (19.1)
    EVENT_CHANGE_REQUESTS_DECIDE = "event_change_requests:decide"  # coordinator (19.x)

    # --- Venue bookings (12.x, 13.x, 14.x) ---
    BOOKINGS_READ = "bookings:read"
    BOOKINGS_REQUEST = "bookings:request"  # coordinator raises / withdraws (12.x)
    BOOKINGS_DECIDE = "bookings:decide"  # venue staff approve / reject (13.x)

    # --- Equipment (15.x, 16.x, 17.x) ---
    EQUIPMENT_READ = "equipment:read"
    EQUIPMENT_REQUEST = "equipment:request"  # record / amend requirements (15.1, 15.2)
    EQUIPMENT_MANAGE = "equipment:manage"  # availability, reservations, out-of-service (15.4-17.x)

    # --- Attendee registration (18.x) ---
    REGISTRATIONS_SELF = "registrations:self"  # browse, register, withdraw (18.1-18.4)
    REGISTRATIONS_VIEW = "registrations:view"  # organiser / coordinator view list (18.6)

    # --- Cross-cutting ---
    NOTIFICATIONS_READ_OWN = "notifications:read_own"  # (20.x)
    USERS_READ_INTERNAL = "users:read_internal"  # e.g. pick a coordinator to assign (5.1)


_INTERNAL_COMMON = {
    Permission.VENUES_READ,
    Permission.VENUE_CALENDAR_READ,
    Permission.EVENTS_READ_ALL,
    Permission.BOOKINGS_READ,
    Permission.EQUIPMENT_READ,
    Permission.NOTIFICATIONS_READ_OWN,
    Permission.USERS_READ_INTERNAL,
}

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    RoleCode.EVENT_ORGANISER: frozenset(
        {
            Permission.EVENTS_CREATE,
            Permission.EVENTS_READ_OWN,
            Permission.EVENT_CHANGE_REQUESTS_CREATE,
            Permission.REGISTRATIONS_VIEW,
            Permission.NOTIFICATIONS_READ_OWN,
        }
    ),
    RoleCode.EVENT_COORDINATOR: frozenset(
        _INTERNAL_COMMON
        | {
            Permission.EVENTS_REVIEW,
            Permission.EVENTS_EDIT_ROUTINE,
            Permission.EVENTS_CANCEL,
            Permission.EVENT_CHANGE_REQUESTS_DECIDE,
            Permission.BOOKINGS_REQUEST,
            Permission.EQUIPMENT_REQUEST,
            Permission.REGISTRATIONS_VIEW,
        }
    ),
    RoleCode.VENUE_STAFF: frozenset(
        _INTERNAL_COMMON
        | {
            Permission.VENUES_MANAGE,
            Permission.VENUE_UNAVAILABILITY_MANAGE,
            Permission.BOOKINGS_DECIDE,
        }
    ),
    RoleCode.TECH_SUPPORT_STAFF: frozenset(_INTERNAL_COMMON | {Permission.EQUIPMENT_MANAGE}),
    RoleCode.ATTENDEE: frozenset(
        {Permission.REGISTRATIONS_SELF, Permission.NOTIFICATIONS_READ_OWN}
    ),
}


def permissions_for(role_code: str) -> frozenset[Permission]:
    """Permissions granted to ``role_code``; an unknown role gets none."""
    return ROLE_PERMISSIONS.get(role_code, frozenset())


def role_has(role_code: str, *required: Permission) -> bool:
    """True when the role holds every permission in ``required``."""
    return set(required) <= permissions_for(role_code)
