"""Story 1.1 - fe/be: implement user login and logout.

AC1 Valid credentials grant access and start an authenticated session.
AC2 Invalid credentials are refused with a message that does not reveal whether the account exists.
AC3 Stored credentials are not held in plain text.
AC4 After successful login, the user is redirected to the appropriate authenticated page.
AC5 After logout the session is invalidated.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.models import User, UserSession
from app.auth.router import INVALID_CREDENTIALS_MESSAGE
from app.config import settings
from tests.support.factories import make_user
from tests.support.seed import SEED_PASSWORD, Users

COOKIE = settings.session_cookie_name


# --- AC1 -------------------------------------------------------------------------------
@pytest.mark.story("1.1", ac=1)
def test_valid_credentials_start_a_session(client, db: Session):
    response = client.post(
        "/auth/login", json={"email": Users.VENUE_STAFF.email, "password": SEED_PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["email"] == Users.VENUE_STAFF.email
    assert COOKIE in response.cookies, "session cookie not set"
    session = db.scalar(select(UserSession).where(UserSession.user_id == Users.VENUE_STAFF.id))
    assert session is not None and session.revoked_at is None


@pytest.mark.story("1.1", ac=1)
def test_session_cookie_grants_access_to_protected_endpoint(client):
    client.login(Users.VENUE_STAFF)

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["full_name"] == Users.VENUE_STAFF.full_name


@pytest.mark.story("1.1", ac=1)
def test_email_is_case_insensitive(client):
    response = client.post(
        "/auth/login", json={"email": Users.VENUE_STAFF.email.upper(), "password": SEED_PASSWORD}
    )
    assert response.status_code == 200


@pytest.mark.story("1.1", ac=1)
def test_session_cookie_is_http_only(client):
    response = client.post(
        "/auth/login", json={"email": Users.VENUE_STAFF.email, "password": SEED_PASSWORD}
    )
    assert "httponly" in response.headers["set-cookie"].lower()


# --- AC2 -------------------------------------------------------------------------------
@pytest.mark.story("1.1", ac=2)
def test_wrong_password_and_unknown_email_get_identical_responses(client):
    wrong_password = client.post(
        "/auth/login", json={"email": Users.VENUE_STAFF.email, "password": "not-the-password"}
    )
    unknown_email = client.post(
        "/auth/login", json={"email": "nobody@nowhere.example", "password": SEED_PASSWORD}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json() == {"detail": INVALID_CREDENTIALS_MESSAGE}
    assert COOKIE not in wrong_password.cookies


@pytest.mark.story("1.1", ac=2)
def test_inactive_account_is_refused_with_the_same_message(client):
    response = client.post(
        "/auth/login", json={"email": Users.INACTIVE.email, "password": SEED_PASSWORD}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": INVALID_CREDENTIALS_MESSAGE}


@pytest.mark.story("1.1", ac=2)
@pytest.mark.parametrize(
    "body", [{}, {"email": "x@y.z"}, {"password": "p"}, {"email": "", "password": ""}]
)
def test_missing_fields_are_rejected(client, body):
    assert client.post("/auth/login", json=body).status_code == 422


# --- AC3 -------------------------------------------------------------------------------
@pytest.mark.story("1.1", ac=3)
def test_password_is_stored_hashed_not_plain(db: Session):
    stored = db.execute(
        text("SELECT password_hash FROM users WHERE id = :id"), {"id": Users.VENUE_STAFF.id}
    ).scalar()
    assert SEED_PASSWORD not in stored
    assert stored.startswith("scrypt$")


@pytest.mark.story("1.1", ac=3)
def test_no_user_has_a_plain_text_password(db: Session):
    hashes = db.execute(text("SELECT password_hash FROM users")).scalars().all()
    assert all(h.count("$") == 5 and h.startswith("scrypt$") for h in hashes)


# --- AC4 -------------------------------------------------------------------------------
@pytest.mark.story("1.1", ac=4)
@pytest.mark.parametrize("user", Users.ONE_PER_ROLE, ids=lambda u: u.role)
def test_login_response_tells_the_frontend_the_role_for_redirection(client, user):
    """A client picks the authenticated landing page from role_code and permissions."""
    body = client.login(user)
    assert body["role_code"] == user.role
    assert isinstance(body["permissions"], list)


@pytest.mark.story("1.1", ac=4)
def test_login_response_is_the_same_user_record_as_me(client):
    """A client can route straight from the login response, without a second lookup."""
    body = client.login(Users.VENUE_STAFF)
    assert body == client.get("/auth/me").json()


# --- AC5 -------------------------------------------------------------------------------
@pytest.mark.story("1.1", ac=5)
def test_logout_invalidates_the_session_server_side(client, db: Session):
    client.login(Users.VENUE_STAFF)
    token = client.cookies[COOKIE]

    response = client.logout()

    assert response.status_code == 204
    session = db.scalar(
        select(UserSession).where(UserSession.token_hash == service.hash_token(token))
    )
    assert session.revoked_at is not None
    # Even if the browser kept the cookie, it no longer works.
    client.cookies.set(COOKIE, token)
    assert client.get("/auth/me").status_code == 401


@pytest.mark.story("1.1", ac=5)
def test_logout_without_a_session_is_harmless(client):
    assert client.logout().status_code == 204


@pytest.mark.story("1.1", ac=5)
def test_expired_session_is_rejected(client, db: Session, monkeypatch):
    user = db.get(User, Users.VENUE_STAFF.id)
    monkeypatch.setattr(settings, "session_ttl_hours", -1)  # already expired
    _, token = service.create_session(db, user)

    client.cookies.set(COOKIE, token)

    assert client.get("/auth/me").status_code == 401


@pytest.mark.story("1.1", ac=5)
def test_deactivating_a_user_kills_their_live_session(client, db: Session):
    user = make_user(db, role="VENUE_STAFF")
    client.login(user.email)
    assert client.get("/auth/me").status_code == 200

    user.is_active = False
    db.flush()

    assert client.get("/auth/me").status_code == 401


@pytest.mark.story("1.1", ac=1)
def test_unauthenticated_request_is_rejected(client):
    assert client.get("/auth/me").status_code == 401
