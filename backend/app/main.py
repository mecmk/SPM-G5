import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.auth.router import RETRY_AFTER_HEADER
from app.auth.router import router as auth_router
from app.bookings import service as bookings_service
from app.bookings.router import router as bookings_router
from app.change_requests.router import router as change_requests_router
from app.config import settings
from app.coordination.router import router as coordination_router
from app.db import SessionLocal
from app.equipment.router import queue_router as equipment_queue_router
from app.equipment.router import router as equipment_router
from app.events.router import router as events_router
from app.events.router import uploads_router
from app.notifications.router import router as notifications_router
from app.registrations.router import router as registrations_router
from app.safety.router import events_router as safety_events_router
from app.safety.router import router as safety_router
from app.venues.router import router as venues_router
from app.venues.router import uploads_router as venue_uploads_router

_log = logging.getLogger(__name__)


def _sweep_holds_once() -> None:
    """Story 12.7 AC2/AC3: one pass of the hold timer, in a session of its own. A database error
    is logged and the pass left to the next one, so a brief outage never stops the timer."""
    db = SessionLocal()
    try:
        bookings_service.sweep_holds(db, now=datetime.now(UTC))
    except SQLAlchemyError:
        db.rollback()
        _log.exception("The hold sweep failed; it runs again on the next pass.")
    finally:
        db.close()


async def _sweep_holds_forever(interval_seconds: float) -> None:
    """Story 12.7 AC2/AC3: warn coordinators and expire lapsed holds on time, with nobody using
    the app. Each pass runs in a worker thread, so the API keeps answering meanwhile. An error a
    pass did not expect is logged and the timer carries on (review of #103): left to escape, it
    would end the task, unseen until shutdown, and warnings and expiries would wait for someone
    to open a bookings page. Shutdown's ``CancelledError`` is no ``Exception``, so it still stops
    the loop."""
    while True:
        try:
            await asyncio.to_thread(_sweep_holds_once)
        except Exception:
            _log.exception("The hold sweep failed; it runs again on the next pass.")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Story 12.7: the hold timer runs while the API is up, every
    ``hold_sweep_interval_seconds`` (0 turns it off), and stops with it."""
    interval = settings.hold_sweep_interval_seconds
    sweeper = asyncio.create_task(_sweep_holds_forever(interval)) if interval > 0 else None
    yield
    if sweeper is not None:
        sweeper.cancel()
        with suppress(asyncio.CancelledError):
            await sweeper


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
app.include_router(change_requests_router)
app.include_router(coordination_router)
app.include_router(equipment_router)
app.include_router(equipment_queue_router)
app.include_router(events_router)
app.include_router(notifications_router)
app.include_router(registrations_router)
app.include_router(safety_router)
app.include_router(safety_events_router)
app.include_router(uploads_router)
app.include_router(venues_router)
app.include_router(venue_uploads_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
