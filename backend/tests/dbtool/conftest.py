"""Fixtures for the tests of ``app/dbtool`` (the tool behind ``npm run db:*``).

The tool drops, creates and rebuilds whole databases, so these tests never use the session's test
database, which every other test shares. They work on scratch databases of their own, named after
it: ``<test database>_dbtool``, which a test may wipe, and two templates it is copied from, one
migrated and one migrated and seeded, built once so that each test starts from a fresh copy
without re-running every migration. All three are dropped before the first test and after the
last. The data dictionary and ERD the tool generates go to a temporary folder, never to
``docs/database/``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from psycopg import sql

from app.config import settings
from app.dbtool import connection, docs, migrate
from tests.conftest import TEST_DATABASE_URL

SCRATCH_DATABASE = f"{connection.database_name(TEST_DATABASE_URL)}_dbtool"
MIGRATED_TEMPLATE = f"{SCRATCH_DATABASE}_migrated"
SEEDED_TEMPLATE = f"{SCRATCH_DATABASE}_seeded"


def quiet(*_args, **_kwargs) -> None:
    """A ``log`` for migrate/seed calls that set a test up rather than prove anything."""


def _url(database: str) -> str:
    return connection.server_url(TEST_DATABASE_URL, dbname=database)


def _copy(template_url: str, url: str) -> None:
    """Recreate the database ``url`` names as a copy of ``template_url``'s."""
    connection.drop_database(url)
    with connection.connect(connection.server_url(url), autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(connection.database_name(url)),
                sql.Identifier(connection.database_name(template_url)),
            )
        )


@pytest.fixture(scope="session")
def scratch_url() -> Iterator[str]:
    """The URL of the scratch database, which does not exist when the first test starts."""
    protected = {
        connection.database_name(settings.database_url),
        connection.database_name(TEST_DATABASE_URL),
    }
    if protected & {SCRATCH_DATABASE, MIGRATED_TEMPLATE, SEEDED_TEMPLATE}:
        pytest.exit("refusing to let the dbtool tests rebuild the development or test database")
    scratch = [_url(SCRATCH_DATABASE), _url(MIGRATED_TEMPLATE), _url(SEEDED_TEMPLATE)]
    connection.wait_for_server(scratch[0], timeout_seconds=10)
    for url in scratch:
        connection.drop_database(url)
    yield scratch[0]
    for url in scratch:
        connection.drop_database(url)


@pytest.fixture(scope="session")
def migrated_template(scratch_url: str) -> str:
    url = _url(MIGRATED_TEMPLATE)
    connection.create_database(url)
    migrate.migrate(url, log=quiet)
    return url


@pytest.fixture(scope="session")
def seeded_template(migrated_template: str) -> str:
    """A migrated and seeded database. Tests only read it; anything that writes takes a copy."""
    url = _url(SEEDED_TEMPLATE)
    _copy(migrated_template, url)
    migrate.seed(url, log=quiet)
    return url


@pytest.fixture
def missing_url(scratch_url: str) -> str:
    """The scratch database, dropped: the state of a fresh checkout before `npm run db:ready`."""
    connection.drop_database(scratch_url)
    return scratch_url


@pytest.fixture
def empty_url(scratch_url: str) -> str:
    """The scratch database, existing but holding no tables."""
    connection.ensure_database(scratch_url)
    migrate.drop_all_objects(scratch_url)
    return scratch_url


@pytest.fixture
def migrated_url(scratch_url: str, migrated_template: str) -> str:
    """The scratch database with every migration applied and no sample data."""
    _copy(migrated_template, scratch_url)
    return scratch_url


@pytest.fixture
def seeded_url(scratch_url: str, seeded_template: str) -> str:
    """The scratch database migrated and seeded, as `npm run db:ready` leaves it."""
    _copy(seeded_template, scratch_url)
    return scratch_url


@pytest.fixture(autouse=True)
def docs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Send every data dictionary and ERD these tests generate to a temporary folder."""
    out = tmp_path / "docs" / "database"
    monkeypatch.setattr(docs, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(docs, "DOCS_DIR", out)
    monkeypatch.setattr(docs, "DICTIONARY_PATH", out / "DATA_DICTIONARY.md")
    monkeypatch.setattr(docs, "ERD_PATH", out / "ERD.excalidraw")
    return out
