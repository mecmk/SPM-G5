"""Shared pytest fixtures and the story-traceability plugin.

How the database is handled in tests
------------------------------------
* A dedicated database (``TEST_DATABASE_URL``, default ``<dev db>_test``) is dropped and
  rebuilt ONCE per test session from the real migrations + seed files. The development
  database is never touched.
* Every test runs inside a transaction that is rolled back afterwards, so tests start from
  the seeded state, cannot see each other's rows, and need no clean-up code.
* The FastAPI app's ``get_db`` dependency is overridden to use that same transaction, so
  what the API writes is visible to assertions made directly on ``db``.

Writing a test
--------------
    @pytest.mark.story("8.3", ac=1)
    def test_venue_staff_can_create_venue(venue_staff_client):
        response = venue_staff_client.post("/venues", json={...})
        assert response.status_code == 201

``pytest --traceability ../docs/testing/TRACEABILITY.md`` writes a story/AC -> test matrix.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.dbtool import connection, migrate
from app.main import app
from tests.support.seed import SEED_PASSWORD, SeedUser, Users

TEST_DATABASE_URL = settings.resolved_test_database_url


# ---------------------------------------------------------------------------------------
# Database lifecycle
# ---------------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Rebuild the test database from migrations + seed once per session."""
    if connection.database_name(TEST_DATABASE_URL) == connection.database_name(
        settings.database_url
    ):
        pytest.exit("TEST_DATABASE_URL must differ from DATABASE_URL - refusing to wipe dev data")
    try:
        connection.wait_for_server(TEST_DATABASE_URL, timeout_seconds=10)
    except connection.DatabaseUnavailable as exc:
        pytest.exit(f"Backend tests need PostgreSQL.\n{exc}", returncode=2)
    connection.drop_database(TEST_DATABASE_URL)
    connection.create_database(TEST_DATABASE_URL)
    quiet = lambda *_args, **_kwargs: None  # noqa: E731
    migrate.migrate(TEST_DATABASE_URL, log=quiet)
    migrate.seed(TEST_DATABASE_URL, log=quiet)
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def engine(test_database_url: str):
    engine = create_engine(test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine) -> Session:
    """A session inside a transaction that is rolled back when the test ends."""
    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()


# ---------------------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------------------
class ApiClient(TestClient):
    """TestClient with login helpers so tests read as user actions."""

    def login(self, user: SeedUser | str, password: str = SEED_PASSWORD) -> dict:
        email = user.email if isinstance(user, SeedUser) else user
        response = self.post("/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, f"login as {email} failed: {response.text}"
        return response.json()

    def logout(self):
        return self.post("/auth/logout")


@pytest.fixture
def client(db: Session) -> ApiClient:
    app.dependency_overrides[get_db] = lambda: db
    with ApiClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


def _logged_in(user: SeedUser):
    @pytest.fixture
    def fixture(client: ApiClient) -> ApiClient:
        client.login(user)
        return client

    fixture.__doc__ = f"ApiClient already signed in as {user.role} ({user.email})."
    return fixture


organiser_client = _logged_in(Users.ORGANISER)
coordinator_client = _logged_in(Users.COORDINATOR)
venue_staff_client = _logged_in(Users.VENUE_STAFF)
tech_client = _logged_in(Users.TECH_SUPPORT)
attendee_client = _logged_in(Users.ATTENDEE)


@pytest.fixture
def login_as(client: ApiClient):
    """Factory: ``login_as(Users.COORDINATOR)`` returns the signed-in client."""

    def _login(user: SeedUser) -> ApiClient:
        client.login(user)
        return client

    return _login


# ---------------------------------------------------------------------------------------
# Story traceability plugin
# ---------------------------------------------------------------------------------------
def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "story(id, ac=None): backlog story (and optional acceptance-criterion number) "
        "the test verifies",
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--traceability",
        default=None,
        metavar="PATH",
        help="write a story/AC -> test traceability matrix (Markdown) to PATH",
    )


_outcomes: dict[str, str] = {}


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        _outcomes[report.nodeid] = report.outcome


def _story_sort_key(story: str):
    return [int(p) if p.isdigit() else p for p in re.split(r"[.]", story)]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    path = session.config.getoption("--traceability")
    if not path:
        return
    by_story: dict[str, list[tuple[str | None, str, str]]] = defaultdict(list)
    for item in session.items:
        for marker in item.iter_markers("story"):
            story = str(marker.args[0])
            ac = marker.kwargs.get("ac")
            by_story[story].append(
                (
                    str(ac) if ac is not None else None,
                    item.nodeid,
                    _outcomes.get(item.nodeid, "not run"),
                )
            )
    lines = [
        "# Test traceability matrix",
        "",
        "_Generated by `npm run test:trace` (pytest `--traceability`). Maps backlog stories and "
        "acceptance criteria (AC) to the automated tests that verify them._",
        "",
        "| Story | AC | Test | Result |",
        "| --- | --- | --- | --- |",
    ]
    for story in sorted(by_story, key=_story_sort_key):
        for ac, nodeid, outcome in sorted(by_story[story], key=lambda r: (r[0] or "", r[1])):
            lines.append(f"| {story} | {ac or '-'} | `{nodeid}` | {outcome} |")
    lines += [
        "",
        f"Stories covered: {len(by_story)}. Tests with story markers: "
        f"{sum(len(v) for v in by_story.values())}.",
        "",
    ]
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    session.config.pluginmanager.get_plugin("terminalreporter").write_line(
        f"traceability matrix written to {out}"
    )
