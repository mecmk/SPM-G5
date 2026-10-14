"""FastAPI dependencies for venue bookings: story 12.7's lapsed holds.

    from app.bookings.deps import ReleaseLapsedHolds

    @router.get("/things", dependencies=[ReleaseLapsedHolds])
    def list_things(): ...                    # answered as if every lapsed hold had expired

The API also sweeps on a timer (``app/main.py``), but a hold lapses at its expiry, not at the next
tick: every answer that a lapsed hold would change sweeps first.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser
from app.bookings import service
from app.db import get_db


def release_lapsed_holds(_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> None:
    """Story 12.7 AC3/AC11: expire every hold that has lapsed, and warn the coordinators of those
    about to (AC2), before the request is answered - so the booking queue, the event's booking
    list, the venue search and the calendar never show, count or are blocked by a lapsed hold,
    and no action is taken on one. Only for a signed-in caller, so a visitor's request writes
    nothing."""
    service.sweep_holds(db, now=datetime.now(UTC))


ReleaseLapsedHolds = Depends(release_lapsed_holds)
