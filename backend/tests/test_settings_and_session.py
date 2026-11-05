"""Story 1 - chore: set up database schema. The platform plumbing around it (unit tests).

Guard-rails, like those in ``test_schema.py``: the test database is never the development
database, and each request's session is handed back once the request is done. Neither has an
acceptance criterion of its own, so the marker names the story alone.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

import app.db
from app.config import Settings

DEV_DATABASE_URL = "postgresql+psycopg://connectsphere:connectsphere@db.example:5433/connectsphere"


@pytest.mark.story("1")
def test_the_test_database_defaults_to_the_dev_database_name_with_test_appended():
    """Left unset, ``TEST_DATABASE_URL`` names a database of its own on the same server, so the
    suite that drops and rebuilds it never touches the development database."""
    settings = Settings(_env_file=None, database_url=DEV_DATABASE_URL, test_database_url=None)

    assert settings.resolved_test_database_url == (
        "postgresql+psycopg://connectsphere:connectsphere@db.example:5433/connectsphere_test"
    )


@pytest.mark.story("1")
def test_a_test_database_that_is_set_is_used_as_given():
    chosen = "postgresql+psycopg://connectsphere:connectsphere@db.example:5433/scratch"
    settings = Settings(_env_file=None, database_url=DEV_DATABASE_URL, test_database_url=chosen)

    assert settings.resolved_test_database_url == chosen


@pytest.mark.story("1")
def test_each_request_gets_a_session_that_is_closed_when_the_request_ends(engine, monkeypatch):
    """``get_db`` is what the running API uses; every other test replaces it with the rolled-back
    test session. Here its session factory is pointed at the test database, never the dev one."""
    monkeypatch.setattr(app.db, "SessionLocal", sessionmaker(bind=engine))
    request = app.db.get_db()

    db = next(request)
    db.execute(text("SELECT 1"))
    assert isinstance(db, Session)
    assert db.in_transaction()

    request.close()

    assert not db.in_transaction()
