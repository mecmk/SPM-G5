"""Helpers for the tests that make two database sessions meet on a row lock (story 21.3 AC11).

A race test commits its rows, holds a lock in one thread, starts the action under test in
another, and waits until that action stands waiting on the lock before it lets the first go - so
which of the two is saved first is decided by the test, never by a sleep. The same pattern is in
tests/cancellations/test_cancel_event.py, which keeps its own copy.
"""

from __future__ import annotations

import time

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

LOCK_WAIT_SECONDS = 10


def backend_pid(session: Session) -> int:
    """The PostgreSQL connection ``session`` runs on, for ``wait_until_waiting`` to watch."""
    return session.connection().exec_driver_sql("SELECT pg_backend_pid()").scalar()


def wait_until_waiting(engine: Engine, pids: dict[str, int], name: str) -> None:
    """Block until the connection ``name`` stands waiting on a row lock another holds."""
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while time.monotonic() < deadline:
        if name in pids:
            with engine.connect() as watcher:
                waiting_on = watcher.execute(
                    text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                    {"pid": pids[name]},
                ).scalar()
            if waiting_on == "Lock":
                return
        time.sleep(0.05)
    raise AssertionError(f"{name} never waited on a lock")
