"""Story 1.1 AC6 (bug f1.1.2) - temporary lockout after repeated failed sign-ins.

AC6 After 5 failed sign-in attempts for the same email within 15 minutes, sign-in for that email
    is refused for 15 minutes, starting with the 5th attempt's own response, and the sign-in page
    counts down the time left. This applies
    whether or not the account exists, and whatever the password. A successful sign-in resets
    the count. Attempts made while locked do not extend the lock.

The time left travels as a number of seconds (``Retry-After``), never as a clock time, so no time
zone, daylight-saving change or calendar quirk can affect it.

Time is moved by editing ``window_started_at`` / ``locked_until`` inside the test's transaction,
never by sleeping.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.models import LoginAttempt
from app.auth.router import LOGIN_LOCKED_MESSAGE
from app.common.audit import AuditLog
from app.config import settings
from tests.support.seed import SEED_PASSWORD, Users

WRONG_PASSWORD = "not-the-password"
_UTC = ZoneInfo("UTC")
_SINGAPORE = ZoneInfo("Asia/Singapore")
_NEW_YORK = ZoneInfo("America/New_York")
_LONDON = ZoneInfo("Europe/London")


def _unknown_email() -> str:
    return f"lockout-{uuid.uuid4().hex[:8]}@nowhere.example"


def _sign_in(client, email: str, password: str = WRONG_PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def _fail(client, email: str, times: int) -> None:
    """Fail ``times`` sign-ins, each refused as wrong credentials (fewer than the maximum)."""
    for _ in range(times):
        assert _sign_in(client, email).status_code == 401


def _lock(client, email: str):
    """Fail until the email locks; the last failure is itself answered with the lock."""
    _fail(client, email, settings.login_max_failures - 1)
    response = _sign_in(client, email)
    assert response.status_code == 429
    return response


def _attempt_row(db: Session, email: str) -> LoginAttempt | None:
    db.expire_all()
    return db.scalar(select(LoginAttempt).where(LoginAttempt.email == email.strip()))


def _lock_audits(db: Session, email: str) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.action == "LOGIN_LOCKED",
                func.lower(AuditLog.details["email"].astext) == email.strip().lower(),
            )
        )
    )


# --- happy path --------------------------------------------------------------------------
@pytest.mark.story("1.1", ac=6)
def test_the_fifth_failure_is_answered_with_the_lock(client, db: Session):
    _fail(client, Users.VENUE_STAFF.email, 4)

    response = _sign_in(client, Users.VENUE_STAFF.email)

    assert response.status_code == 429
    assert response.json() == {"detail": LOGIN_LOCKED_MESSAGE}
    assert response.headers["Retry-After"] == str(settings.login_lock_minutes * 60)
    assert _attempt_row(db, Users.VENUE_STAFF.email).locked_until is not None


@pytest.mark.story("1.1", ac=6)
def test_once_locked_even_the_right_password_is_refused(client):
    _lock(client, Users.VENUE_STAFF.email)

    response = _sign_in(client, Users.VENUE_STAFF.email, SEED_PASSWORD)

    assert response.status_code == 429
    assert response.json() == {"detail": LOGIN_LOCKED_MESSAGE}
    lock_seconds = settings.login_lock_minutes * 60
    assert lock_seconds - 5 <= int(response.headers["Retry-After"]) <= lock_seconds
    assert settings.session_cookie_name not in response.cookies


@pytest.mark.story("1.1", ac=6)
def test_a_successful_sign_in_resets_the_count(client):
    _fail(client, Users.VENUE_STAFF.email, 4)
    client.login(Users.VENUE_STAFF)
    client.logout()

    _fail(client, Users.VENUE_STAFF.email, 4)

    assert _sign_in(client, Users.VENUE_STAFF.email, SEED_PASSWORD).status_code == 200


@pytest.mark.story("1.1", ac=6)
def test_sign_in_works_again_once_the_lock_ends(client, db: Session):
    _lock(client, Users.VENUE_STAFF.email)
    row = _attempt_row(db, Users.VENUE_STAFF.email)
    row.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    row.window_started_at = datetime.now(UTC) - timedelta(minutes=16)
    db.flush()

    assert _sign_in(client, Users.VENUE_STAFF.email, SEED_PASSWORD).status_code == 200
    client.logout()
    assert _sign_in(client, Users.VENUE_STAFF.email).status_code == 401
    assert _sign_in(client, Users.VENUE_STAFF.email, SEED_PASSWORD).status_code == 200


# --- boundary ----------------------------------------------------------------------------
@pytest.mark.story("1.1", ac=6)
def test_four_failures_do_not_lock(client):
    _fail(client, Users.VENUE_STAFF.email, 4)

    assert _sign_in(client, Users.VENUE_STAFF.email, SEED_PASSWORD).status_code == 200


@pytest.mark.story("1.1", ac=6)
def test_a_failure_after_the_window_starts_a_new_count(client, db: Session):
    email = _unknown_email()
    _fail(client, email, 4)
    row = _attempt_row(db, email)
    row.window_started_at = datetime.now(UTC) - timedelta(
        minutes=settings.login_failure_window_minutes
    )
    db.flush()

    _fail(client, email, 1)
    row = _attempt_row(db, email)
    assert row.failure_count == 1
    _fail(client, email, 3)
    assert _sign_in(client, email).status_code == 429  # the 5th of the new window


@pytest.mark.story("1.1", ac=6)
def test_the_lock_ends_exactly_at_the_unlock_time(client, db: Session):
    _lock(client, Users.VENUE_STAFF.email)
    row = _attempt_row(db, Users.VENUE_STAFF.email)

    row.locked_until = datetime.now(UTC) + timedelta(seconds=1)
    db.flush()
    assert _sign_in(client, Users.VENUE_STAFF.email, SEED_PASSWORD).status_code == 429

    row = _attempt_row(db, Users.VENUE_STAFF.email)
    row.locked_until = datetime.now(UTC)
    db.flush()
    assert _sign_in(client, Users.VENUE_STAFF.email, SEED_PASSWORD).status_code == 200


@pytest.mark.story("1.1", ac=6)
def test_retry_after_counts_down_to_the_unlock_time(client, db: Session):
    _lock(client, Users.VENUE_STAFF.email)
    row = _attempt_row(db, Users.VENUE_STAFF.email)
    row.locked_until = datetime.now(UTC) + timedelta(seconds=90.5)
    db.flush()

    response = _sign_in(client, Users.VENUE_STAFF.email, SEED_PASSWORD)

    assert response.status_code == 429
    assert response.headers["Retry-After"] in {"90", "91"}


@pytest.mark.story("1.1", ac=6)
@pytest.mark.parametrize(
    ("now", "unlock_at", "expected"),
    [
        # Leap day: 23:55 on 28 Feb 2028 to 00:10 on 29 Feb, then 29 Feb into 1 Mar.
        (
            datetime(2028, 2, 28, 23, 55, tzinfo=_SINGAPORE),
            datetime(2028, 2, 29, 0, 10, tzinfo=_SINGAPORE),
            900,
        ),
        (
            datetime(2028, 2, 29, 23, 55, tzinfo=_SINGAPORE),
            datetime(2028, 3, 1, 0, 10, tzinfo=_SINGAPORE),
            900,
        ),
        # 2100 is not a leap year: 28 Feb runs straight into 1 Mar.
        (datetime(2100, 2, 28, 23, 55, tzinfo=_UTC), datetime(2100, 3, 1, 0, 10, tzinfo=_UTC), 900),
        # New Year.
        (
            datetime(2026, 12, 31, 23, 55, tzinfo=_SINGAPORE),
            datetime(2027, 1, 1, 0, 10, tzinfo=_SINGAPORE),
            900,
        ),
        # New York clocks go back at 02:00: 01:55 EDT to 01:10 EST is 15 minutes later.
        (
            datetime(2026, 11, 1, 1, 55, tzinfo=_NEW_YORK),
            datetime(2026, 11, 1, 1, 10, fold=1, tzinfo=_NEW_YORK),
            900,
        ),
        # New York clocks go forward at 02:00: 01:55 EST to 03:10 EDT is 15 minutes later.
        (
            datetime(2027, 3, 14, 1, 55, tzinfo=_NEW_YORK),
            datetime(2027, 3, 14, 3, 10, tzinfo=_NEW_YORK),
            900,
        ),
        # London clocks go forward at 01:00: 00:55 GMT to 02:10 BST is 15 minutes later.
        (
            datetime(2027, 3, 28, 0, 55, tzinfo=_LONDON),
            datetime(2027, 3, 28, 2, 10, tzinfo=_LONDON),
            900,
        ),
        # The same instant written in two different zones.
        (
            datetime(2026, 9, 25, 7, 0, tzinfo=_UTC),
            datetime(2026, 9, 25, 15, 15, tzinfo=_SINGAPORE),
            900,
        ),
        # Part-seconds round up, so the time left never runs out before the lock does.
        (
            datetime(2026, 9, 25, 7, 0, tzinfo=_UTC),
            datetime(2026, 9, 25, 7, 14, 59, 1, tzinfo=_UTC),
            900,
        ),
        (
            datetime(2026, 9, 25, 7, 0, tzinfo=_UTC),
            datetime(2026, 9, 25, 7, 0, 0, 1, tzinfo=_UTC),
            1,
        ),
    ],
    ids=[
        "into-leap-day",
        "out-of-leap-day",
        "no-leap-day-in-2100",
        "new-year",
        "new-york-clocks-go-back",
        "new-york-clocks-go-forward",
        "london-clocks-go-forward",
        "different-zones",
        "part-second-rounds-up",
        "one-microsecond-left",
    ],
)
def test_the_time_left_is_exact_across_calendar_and_clock_changes(now, unlock_at, expected):
    assert service.seconds_until(unlock_at, now=now) == expected


@pytest.mark.story("1.1", ac=6)
def test_the_browser_may_read_the_time_left(client):
    """The frontend is on another origin, so CORS must expose Retry-After for it to count down."""
    _lock(client, Users.VENUE_STAFF.email)

    response = client.post(
        "/auth/login",
        json={"email": Users.VENUE_STAFF.email, "password": SEED_PASSWORD},
        headers={"Origin": settings.cors_origins[0]},
    )

    assert response.status_code == 429
    exposed = response.headers["Access-Control-Expose-Headers"].lower().split(", ")
    assert "retry-after" in exposed


# --- edge --------------------------------------------------------------------------------
@pytest.mark.story("1.1", ac=6)
def test_an_unknown_email_locks_exactly_like_a_real_one(client):
    unknown_response = _lock(client, _unknown_email())
    real_response = _lock(client, Users.VENUE_STAFF.email)

    assert unknown_response.json() == real_response.json() == {"detail": LOGIN_LOCKED_MESSAGE}
    assert unknown_response.headers["Retry-After"] == real_response.headers["Retry-After"]

    unknown_again = _sign_in(client, _unknown_email())
    assert unknown_again.status_code == 401  # a different unknown email is not locked


@pytest.mark.story("1.1", ac=6)
def test_case_and_spaces_count_as_the_same_email(client):
    _fail(client, " Organiser@ACME.example ", 2)
    _fail(client, "ORGANISER@acme.example", 2)

    assert _sign_in(client, Users.ORGANISER.email).status_code == 429
    assert _sign_in(client, Users.ORGANISER.email, SEED_PASSWORD).status_code == 429


@pytest.mark.story("1.1", ac=6)
def test_an_inactive_account_locks_like_any_other(client):
    _lock(client, Users.INACTIVE.email)

    assert _sign_in(client, Users.INACTIVE.email, SEED_PASSWORD).status_code == 429


@pytest.mark.story("1.1", ac=6)
def test_a_lock_affects_only_its_own_email(client):
    _lock(client, Users.VENUE_STAFF.email)

    assert _sign_in(client, Users.TECH_SUPPORT.email, SEED_PASSWORD).status_code == 200


@pytest.mark.story("1.1", ac=6)
def test_attempts_while_locked_do_not_extend_the_lock(client, db: Session):
    _lock(client, Users.VENUE_STAFF.email)
    locked_until = _attempt_row(db, Users.VENUE_STAFF.email).locked_until

    for password in (WRONG_PASSWORD, SEED_PASSWORD, WRONG_PASSWORD):
        assert _sign_in(client, Users.VENUE_STAFF.email, password).status_code == 429

    row = _attempt_row(db, Users.VENUE_STAFF.email)
    assert row.locked_until == locked_until
    assert row.failure_count == 0


@pytest.mark.story("1.1", ac=6)
def test_a_lock_does_not_end_an_existing_session(client):
    client.login(Users.VENUE_STAFF)

    _lock(client, Users.VENUE_STAFF.email)

    assert client.get("/auth/me").status_code == 200


@pytest.mark.story("1.1", ac=6)
def test_a_lock_is_audited_once(client, db: Session):
    unknown = _unknown_email()
    _lock(client, Users.VENUE_STAFF.email)
    _lock(client, unknown)
    for _ in range(3):
        assert _sign_in(client, Users.VENUE_STAFF.email).status_code == 429

    [real_audit] = _lock_audits(db, Users.VENUE_STAFF.email)
    [unknown_audit] = _lock_audits(db, unknown)
    assert real_audit.actor_id == real_audit.entity_id == Users.VENUE_STAFF.id
    assert real_audit.entity_type == "user"
    assert real_audit.details["locked_until"] is not None
    assert unknown_audit.actor_id is None
    assert unknown_audit.entity_id is None


# --- permission --------------------------------------------------------------------------
@pytest.mark.story("1.1", ac=6)
def test_staff_accounts_are_not_exempt(client):
    _lock(client, Users.COORDINATOR.email)

    assert _sign_in(client, Users.COORDINATOR.email, SEED_PASSWORD).status_code == 429


# --- conflict ----------------------------------------------------------------------------
@pytest.mark.story("1.1", ac=6)
def test_simultaneous_failures_all_count(engine):
    """Real concurrent transactions, so this test commits and cleans up after itself."""
    email = _unknown_email()
    attempts = settings.login_max_failures
    start = threading.Barrier(attempts)

    def attempt() -> str:
        with Session(engine) as session:
            start.wait()
            try:
                user = service.authenticate(session, email, WRONG_PASSWORD)
            except service.LoginLocked:
                return "locked"
            return "refused" if user is None else "signed in"

    try:
        with ThreadPoolExecutor(max_workers=attempts) as pool:
            results = [pool.submit(attempt) for _ in range(attempts)]
            outcomes = sorted(future.result(timeout=30) for future in results)

        # Whichever failure counts last is the 5th, and it alone is answered with the lock.
        assert outcomes == ["locked"] + ["refused"] * (attempts - 1)

        with Session(engine) as session:
            row = session.scalar(select(LoginAttempt).where(LoginAttempt.email == email))
            assert row.locked_until is not None
            assert len(_lock_audits(session, email)) == 1
            with pytest.raises(service.LoginLocked):
                service.authenticate(session, email, WRONG_PASSWORD)
    finally:
        with Session(engine) as session:
            session.execute(delete(LoginAttempt).where(LoginAttempt.email == email))
            for audit in _lock_audits(session, email):
                session.delete(audit)
            session.commit()


@pytest.mark.story("1.1", ac=6)
def test_simultaneous_successful_sign_ins_all_succeed(engine):
    """The first success deletes the attempt row the others are waiting to lock."""
    email = Users.TECH_SUPPORT.email
    attempts = settings.login_max_failures
    with Session(engine) as session:
        assert service.authenticate(session, email, WRONG_PASSWORD) is None
    start = threading.Barrier(attempts)

    def attempt() -> uuid.UUID:
        with Session(engine) as session:
            start.wait()
            return service.authenticate(session, email, SEED_PASSWORD).id

    try:
        with ThreadPoolExecutor(max_workers=attempts) as pool:
            results = [pool.submit(attempt) for _ in range(attempts)]
            user_ids = [future.result(timeout=30) for future in results]

        assert user_ids == [Users.TECH_SUPPORT.id] * attempts
    finally:
        with Session(engine) as session:
            session.execute(delete(LoginAttempt).where(LoginAttempt.email == email))
            session.commit()
