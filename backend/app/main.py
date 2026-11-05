import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.auth.router import RETRY_AFTER_HEADER
from app.auth.router import router as auth_router
from app.bookings import service as bookings_service
from app.bookings.router import router as bookings_router
from app.cancellations.router import router as cancellations_router
from app.change_requests.router import queue_router as change_request_queue_router
from app.change_requests.router import router as change_requests_router
from app.config import settings
from app.coordination.router import router as coordination_router
from app.db import SessionLocal
from app.equipment.router import holds_router as equipment_holds_router
from app.equipment.router import queue_router as equipment_queue_router
from app.equipment.router import router as equipment_router
from app.equipment.router import types_router as equipment_types_router
from app.events import service as events_service
from app.events.router import router as events_router
from app.events.router import uploads_router
from app.notifications.router import router as notifications_router
from app.registrations.router import events_router as registrations_events_router
from app.registrations.router import profile_router
from app.registrations.router import router as registrations_router
from app.safety.router import events_router as safety_events_router
from app.safety.router import router as safety_router
from app.venues.router import router as venues_router
from app.venues.router import uploads_router as venue_uploads_router

_log = logging.getLogger(__name__)

_HOLD_SWEEP_FAILED = "The hold sweep failed; it runs again on the next pass."
_EVENT_COMPLETION_FAILED = "Completing ended events failed; it runs again on the next pass."


def _sweep_holds_once() -> None:
    """Story 12.7 AC2/AC3: one pass of the hold timer, in a session of its own. A database error
    is logged and the pass left to the next one, so a brief outage never stops the timer."""
    db = SessionLocal()
    try:
        bookings_service.sweep_holds(db, now=datetime.now(UTC))
    except SQLAlchemyError:
        db.rollback()
        _log.exception(_HOLD_SWEEP_FAILED)
    finally:
        db.close()


def _complete_ended_events_once() -> None:
    """Fix f21.2.2 (21.2 AC31): one pass of the completion timer, in a session of its own. A
    database error is logged and the pass left to the next one, as the hold sweep's is."""
    db = SessionLocal()
    try:
        events_service.complete_ended_events(db, now=datetime.now(UTC))
    except SQLAlchemyError:
        db.rollback()
        _log.exception(_EVENT_COMPLETION_FAILED)
    finally:
        db.close()


async def _run_forever(
    run_once: Callable[[], None], *, interval_seconds: float, failed: str
) -> None:
    """Story 12.7 AC2/AC3, fix f21.2.2 (21.2 AC31): run ``run_once`` now and then every
    ``interval_seconds``, so holds expire and ended events complete on time with nobody using the
    app. Each pass runs in a worker thread, so the API keeps answering meanwhile. An error a pass
    did not expect is logged as ``failed`` and the timer carries on (review of #103): left to
    escape, it would end the task, unseen until shutdown. Shutdown's ``CancelledError`` is no
    ``Exception``, so it still stops the loop."""
    while True:
        try:
            await asyncio.to_thread(run_once)
        except Exception:
            _log.exception(failed)
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Story 12.7's hold timer and fix f21.2.2's completion timer run while the API is up, every
    ``hold_sweep_interval_seconds`` and ``event_completion_interval_seconds`` (0 turns either
    off), and stop with it."""
    timers = [
        (_sweep_holds_once, settings.hold_sweep_interval_seconds, _HOLD_SWEEP_FAILED),
        (
            _complete_ended_events_once,
            settings.event_completion_interval_seconds,
            _EVENT_COMPLETION_FAILED,
        ),
    ]
    tasks = [
        asyncio.create_task(_run_forever(run_once, interval_seconds=interval, failed=failed))
        for run_once, interval, failed in timers
        if interval > 0
    ]
    yield
    for task in tasks:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="ConnectSphere API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,  # the session cookie must travel with cross-origin requests
    allow_methods=["*"],
    allow_headers=["*"],
    # Story 1.1 AC6: the sign-in page reads the seconds left from a locked sign-in's Retry-After.
    expose_headers=[RETRY_AFTER_HEADER],
)

# One router per feature area (see AGENTS.md "Repository Structure").
app.include_router(auth_router)
app.include_router(bookings_router)
app.include_router(cancellations_router)
app.include_router(change_requests_router)
app.include_router(change_request_queue_router)
app.include_router(coordination_router)
app.include_router(equipment_router)
app.include_router(equipment_queue_router)
app.include_router(equipment_types_router)
app.include_router(equipment_holds_router)
app.include_router(events_router)
app.include_router(notifications_router)
app.include_router(registrations_router)
app.include_router(registrations_events_router)
app.include_router(profile_router)
app.include_router(safety_router)
app.include_router(safety_events_router)
app.include_router(uploads_router)
app.include_router(venues_router)
app.include_router(venue_uploads_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
