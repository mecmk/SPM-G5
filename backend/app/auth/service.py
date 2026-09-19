"""Authentication service (story 1.1): credential check and server-side sessions."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User, UserSession
from app.auth.passwords import hash_password, verify_password
from app.config import settings

_SESSION_TOKEN_BYTES = 32
# Verified against when the e-mail is unknown, so the response time does not reveal whether an
# account exists (story 1.1 AC2).
_DUMMY_HASH = hash_password("dummy-password-for-timing-equalisation")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def authenticate(db: Session, email: str, password: str) -> User | None:
    """Return the active user matching ``email``/``password``, else None.

    Deliberately returns None for every failure mode (unknown e-mail, wrong password, inactive
    account) so callers cannot leak which one applied.
    """
    user = db.scalar(select(User).where(User.email == email.strip()))
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    return user


def create_session(
    db: Session, user: User, *, user_agent: str | None = None
) -> tuple[UserSession, str]:
    """Create a session row and return it with the raw token to put in the cookie."""
    token = secrets.token_urlsafe(_SESSION_TOKEN_BYTES)
    session = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours),
        user_agent=user_agent,
    )
    db.add(session)
    db.commit()
    return session, token


def get_session_user(db: Session, token: str | None) -> User | None:
    """Resolve a cookie token to its user, or None if missing/revoked/expired/inactive."""
    if not token:
        return None
    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if session is None or session.revoked_at is not None:
        return None
    if session.expires_at <= datetime.now(UTC):
        return None
    if not session.user.is_active:
        return None
    return session.user


def revoke_session(db: Session, token: str | None) -> bool:
    """Invalidate the session behind ``token`` (story 1.1 AC5). Returns True if one was live."""
    if not token:
        return False
    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if session is None or session.revoked_at is not None:
        return False
    session.revoked_at = datetime.now(UTC)
    db.commit()
    return True
