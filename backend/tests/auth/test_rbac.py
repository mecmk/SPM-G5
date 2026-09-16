"""Story 1.2 - fe/be: enforce role-based access control.

AC1 Each user role has a defined set of permitted functions.
AC2 Navigation and action controls outside a user's permitted set are not displayed. (Proven at
    the API level here: the login response and /auth/me list exactly the role's permissions, so
    a client can hide everything else.)
AC3 Users can only view and perform functions permitted for their role.
AC4 Attempts to access unauthorised functions are rejected, including through direct URLs or
    API requests.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.permissions import ROLE_PERMISSIONS, Permission, permissions_for, role_has
from tests.support.factories import venue_payload
from tests.support.seed import Users, Venues


# --- AC1: the matrix is complete and consistent ------------------------------------------
@pytest.mark.story("1.2", ac=1)
def test_every_role_in_the_database_has_a_defined_permission_set(db: Session):
    roles = db.execute(text("SELECT code FROM roles")).scalars().all()
    undefined = [r for r in roles if r not in ROLE_PERMISSIONS]
    assert not undefined, f"roles without a permission set: {undefined}"
    assert all(ROLE_PERMISSIONS[r] for r in roles), "a role has an empty permission set"


@pytest.mark.story("1.2", ac=1)
def test_every_permission_is_granted_to_at_least_one_role():
    granted = set().union(*ROLE_PERMISSIONS.values())
    unused = set(Permission) - granted
    assert not unused, f"permissions no role holds: {sorted(unused)}"


@pytest.mark.story("1.2", ac=1)
def test_unknown_role_has_no_permissions():
    assert permissions_for("NOT_A_ROLE") == frozenset()
    assert not role_has("NOT_A_ROLE", Permission.VENUES_READ)


@pytest.mark.story("1.2", ac=1)
@pytest.mark.story("1.2", ac=2)
@pytest.mark.parametrize("user", Users.ONE_PER_ROLE, ids=lambda u: u.role)
def test_me_reports_exactly_the_roles_permissions(client, user):
    body = client.login(user)
    assert body["permissions"] == sorted(permissions_for(user.role))


# --- AC2: the permission list a client hides controls with ---------------------------------
@pytest.mark.story("1.2", ac=2)
@pytest.mark.parametrize("user", Users.ONE_PER_ROLE, ids=lambda u: u.role)
def test_auth_me_lists_exactly_the_roles_permissions(client, user):
    client.login(user)
    body = client.get("/auth/me").json()
    assert body["permissions"] == sorted(permissions_for(user.role))


# --- AC3 / AC4: enforced on the API, role by role ------------------------------------------
# expected HTTP status per (role, action) for every venue endpoint. 403 = signed in but not
# permitted. "refdata" is the venue form's pick-lists.
VENUE_ACTIONS = ["list", "view", "refdata", "create", "update"]
MATRIX = {
    "EVENT_ORGANISER": {"list": 403, "view": 403, "refdata": 403, "create": 403, "update": 403},
    "EVENT_COORDINATOR": {"list": 200, "view": 200, "refdata": 200, "create": 403, "update": 403},
    "VENUE_STAFF": {"list": 200, "view": 200, "refdata": 200, "create": 201, "update": 200},
    "TECH_SUPPORT_STAFF": {"list": 200, "view": 200, "refdata": 200, "create": 403, "update": 403},
    "ATTENDEE": {"list": 403, "view": 403, "refdata": 403, "create": 403, "update": 403},
}


def _act(client, action: str):
    if action == "list":
        return client.get("/venues")
    if action == "view":
        return client.get(f"/venues/{Venues.GRAND_HALL}")
    if action == "refdata":
        return client.get("/venues/reference-data")
    if action == "create":
        return client.post("/venues", json=venue_payload())
    return client.patch(f"/venues/{Venues.BOARDROOM}", json={"capacity": 18})


@pytest.mark.story("1.2", ac=3)
@pytest.mark.story("1.2", ac=4)
@pytest.mark.parametrize("action", VENUE_ACTIONS)
@pytest.mark.parametrize("user", Users.ONE_PER_ROLE, ids=lambda u: u.role)
def test_venue_actions_are_allowed_only_for_permitted_roles(client, user, action):
    client.login(user)
    response = _act(client, action)
    assert response.status_code == MATRIX[user.role][action], response.text


@pytest.mark.story("1.2", ac=4)
@pytest.mark.parametrize("action", VENUE_ACTIONS)
def test_direct_api_requests_without_a_session_are_rejected(client, action):
    assert _act(client, action).status_code == 401


@pytest.mark.story("1.2", ac=4)
def test_forbidden_action_leaves_no_trace(organiser_client, db: Session):
    """A refused create must not write a venue (defence against partial writes)."""
    before = db.execute(text("SELECT count(*) FROM venues")).scalar()
    organiser_client.post("/venues", json=venue_payload())
    after = db.execute(text("SELECT count(*) FROM venues")).scalar()
    assert before == after
