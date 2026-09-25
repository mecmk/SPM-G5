"""Authentication service (story 1.1): credentials, sign-in lockout and server-side sessions."""

from __future__ import annotations

import hashlib
import math
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.models import LoginAttempt, User, UserSession
from app.auth.passwords import hash_password, verify_password
from app.common.audit import record_audit
from app.config import settings

_SESSION_TOKEN_BYTES = 32
# Verified against when the e-mail is unknown, so the response time does not reveal whether an
# account exists (story 1.1 AC2).
_DUMMY_HASH = hash_password("dummy-password-for-timing-equalisation")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def seconds_until(moment: datetime, *, now: datetime) -> int:
    """Whole seconds from ``now`` until ``moment``, rounded up (story 1.1 AC6).

    Both are converted to UTC first. Python subtracts two datetimes that share a tzinfo by wall
    clock, ignoring offsets, so across a daylight-saving change the result would be off by an
    hour. Rounding up means the time left never runs out before the lock does.
    """
    return math.ceil((moment.astimezone(UTC) - now.astimezone(UTC)).total_seconds())


class LoginLocked(Exception):
    """Sign-in for this e-mail is refused for ``seconds_left`` more seconds (story 1.1 AC6)."""

    def __init__(self, locked_until: datetime, *, seconds_left: int) -> None:
        super().__init__(f"sign-in locked until {locked_until.isoformat()}")
        self.locked_until = locked_until
        self.seconds_left = seconds_left


def _lock_attempt_row(db: Session, email: str, *, now: datetime) -> LoginAttempt:
    """The e-mail's attempt row, created if missing, held with a row lock until commit.

    Inserting first with ON CONFLICT DO NOTHING means concurrent first failures cannot race to
    create the row, and the FOR UPDATE makes every attempt for one e-mail take its turn. A
    concurrent successful sign-in may delete the row while this one waits for the lock, so the
    insert is simply retried.
    """
    attempt = None
    while attempt is None:
        db.execute(
            insert(LoginAttempt)
            .values(email=email, failure_count=0, window_started_at=now)
            .on_conflict_do_nothing(index_elements=[LoginAttempt.email])
        )
        attempt = db.scalar(
            select(LoginAttempt)
            .where(LoginAttempt.email == email)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return attempt


def _record_failure(
    db: Session, attempt: LoginAttempt, *, user: User | None, now: datetime
) -> datetime | None:
    """Count one failure, starting a lock when it reaches the maximum (story 1.1 AC6).

    Returns when that lock ends if this failure started one, else None.
    """
    window = timedelta(minutes=settings.login_failure_window_minutes)
    if attempt.failure_count == 0 or now >= attempt.window_started_at + window:
        attempt.failure_count = 1
        attempt.window_started_at = now
    else:
        attempt.failure_count += 1
    if attempt.failure_count >= settings.login_max_failures:
        attempt.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
        attempt.failure_count = 0
        record_audit(
            db,
            actor=user,
            action="LOGIN_LOCKED",
            entity_type="user",
            entity_id=user.id if user is not None else None,
            details={"email": attempt.email, "locked_until": attempt.locked_until.isoformat()},
            commit=False,
        )
        db.commit()
        return attempt.locked_until
    db.commit()
    return None


def authenticate(db: Session, email: str, password: str) -> User | None:
    """Return the active user matching ``email``/``password``, else None.

    Deliberately returns None for every failure mode (unknown e-mail, wrong password, inactive
    account) so callers cannot leak which one applied (AC2).

    AC6: failures are counted per typed e-mail, known or not. The failure that reaches the
    maximum raises ``LoginLocked`` itself, so the user hears about the lock straight away. Once
    an e-mail is locked, every attempt raises ``LoginLocked`` before the password is checked, so
    the right password does not get through, no hashing runs for known and unknown e-mails
    alike, and the attempt is not counted. A successful sign-in clears the count.
    """
    email = email.strip()
    now = datetime.now(UTC)
    attempt = _lock_attempt_row(db, email, now=now)
    if attempt.locked_until is not None and attempt.locked_until > now:
        locked_until = attempt.locked_until
        db.commit()  # nothing changed; releases the row lock
        raise LoginLocked(locked_until, seconds_left=seconds_until(locked_until, now=now))

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        verify_password(password, _DUMMY_HASH)
    elif verify_password(password, user.password_hash) and user.is_active:
        db.execute(delete(LoginAttempt).where(LoginAttempt.email == email))
        db.commit()
        return user
    locked_until = _record_failure(db, attempt, user=user, now=now)
    if locked_until is not None:
        raise LoginLocked(locked_until, seconds_left=seconds_until(locked_until, now=now))
    return None


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
