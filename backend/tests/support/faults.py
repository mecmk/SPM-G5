"""Database failures a test cannot cause through the API.

A service catches ``IntegrityError`` to turn a constraint it knows into a clear refusal, and
re-raises any other. Those other constraints, and a second request winning a race between the
service's check and its write, cannot be reached with real data, because the service's own checks
refuse the request first. ``fail_flush`` makes the session's flush raise the error PostgreSQL
would, so the handler for each can be proven.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

OTHER_CONSTRAINT = "a_constraint_no_service_names"


def integrity_error(constraint: str = OTHER_CONSTRAINT) -> IntegrityError:
    """The error psycopg raises when ``constraint`` refuses a write: its message names it."""
    return IntegrityError("INSERT ...", {}, Exception(f'violates constraint "{constraint}"'))


def fail_flush(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    constraint: str = OTHER_CONSTRAINT,
    *,
    after: int = 0,
) -> None:
    """Make ``db``'s next flush raise ``integrity_error(constraint)``, once.

    ``after`` lets that many flushes through first, for a service that flushes before the write
    under test. Autoflush goes through ``Session.flush`` too, so it counts.
    """
    real_flush = db.flush
    let_through = after

    def flush(*args, **kwargs):
        nonlocal let_through
        if let_through:
            let_through -= 1
            return real_flush(*args, **kwargs)
        monkeypatch.setattr(db, "flush", real_flush)
        raise integrity_error(constraint)

    monkeypatch.setattr(db, "flush", flush)


def fail_write_of(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    model: type,
    constraint: str = OTHER_CONSTRAINT,
) -> None:
    """Make the flush that writes the next new ``model`` row raise ``integrity_error(constraint)``.

    ``fail_flush`` is armed the moment that row is added to ``db``, so every read, autoflush and
    commit before the write runs as usual. For a request that sweeps, queries and commits before
    its write, where an ``after`` count would change with each one added.
    """
    real_add = db.add

    def add(instance, *args, **kwargs):
        real_add(instance, *args, **kwargs)
        if isinstance(instance, model):
            monkeypatch.setattr(db, "add", real_add)
            fail_flush(db, monkeypatch, constraint)

    monkeypatch.setattr(db, "add", add)
