"""Low-level PostgreSQL connection helpers shared by the db tool and the test-suite."""

from __future__ import annotations

import time
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql


class DatabaseUnavailable(RuntimeError):
    """Raised when the PostgreSQL server cannot be reached."""


def to_psycopg_url(url: str) -> str:
    """Convert a SQLAlchemy URL (``postgresql+psycopg://``) to a plain libpq URL."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def database_name(url: str) -> str:
    return urlsplit(to_psycopg_url(url)).path.lstrip("/")


def server_url(url: str, dbname: str = "postgres") -> str:
    """Return ``url`` pointing at the maintenance database ``dbname`` on the same server."""
    parts = urlsplit(to_psycopg_url(url))
    return urlunsplit(parts._replace(path=f"/{dbname}"))


def is_local(url: str) -> bool:
    host = urlsplit(to_psycopg_url(url)).hostname or ""
    return host in {"localhost", "127.0.0.1", "::1", "db"}


def connect(url: str, **kwargs) -> psycopg.Connection:
    return psycopg.connect(to_psycopg_url(url), **kwargs)


def wait_for_server(url: str, timeout_seconds: float = 30.0, interval: float = 1.0) -> None:
    """Block until the server behind ``url`` accepts connections, or raise DatabaseUnavailable."""
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with connect(server_url(url), connect_timeout=3):
                return
        except psycopg.OperationalError as exc:  # server not up yet
            last_error = exc
            time.sleep(interval)
    raise DatabaseUnavailable(
        f"PostgreSQL at {server_url(url)} did not become reachable within {timeout_seconds:.0f}s. "
        f"Is the database running? Try `docker compose up -d` from the repo root.\n"
        f"Last error: {last_error}"
    )


def database_exists(url: str) -> bool:
    with connect(server_url(url), autocommit=True) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (database_name(url),)
        ).fetchone()
    return row is not None


def create_database(url: str) -> None:
    with connect(server_url(url), autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name(url))))


def drop_database(url: str) -> None:
    name = database_name(url)
    with connect(server_url(url), autocommit=True) as conn:
        # Kick off any lingering sessions (e.g. a dev server) so the drop cannot hang.
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        )
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))


def ensure_database(url: str) -> bool:
    """Create the database named in ``url`` if missing. Returns True when it was created."""
    if database_exists(url):
        return False
    create_database(url)
    return True
