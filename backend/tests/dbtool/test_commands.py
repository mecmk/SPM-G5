"""Story 1 - chore: set up database schema. The commands of ``python -m app.dbtool``.

Level: integration. Each test runs the tool in-process through ``app/dbtool/__main__.py::main``,
as ``npm run db:*`` runs it, against the scratch database in ``conftest.py``, and checks what it
prints and what it leaves in the database. The generated documents are checked in
``test_docs.py``.

AC1 Schema covers users, events, venues, bookings, equipment. (Here: the migrations that build it
    are applied, once each, and an applied one edited since is caught.)
AC3 Schema can be populated with sample data without integrity errors. (Here: the seed runs on
    the migrated schema, re-runs without duplicating rows, and `ready` refuses a database left
    without it.)

The tool's own guard-rails - refusing to wipe a remote database, a server it cannot reach - serve
no AC and carry the bare story marker, as ``test_schema.py::test_seed_constants_match_database``
does.
"""

from __future__ import annotations

import argparse
import runpy
import sys

import psycopg
import pytest

from app.dbtool import connection, migrate
from app.dbtool.__main__ import REQUIRED_SEEDED_TABLES, SEED_ACCOUNTS, SEED_PASSWORD, main
from tests.dbtool.conftest import PROTECTED_DATABASES, quiet

REMOTE_URL = "postgresql+psycopg://connectsphere:secret@db.example.com:5432/connectsphere"
UNREACHABLE_URL = "postgresql+psycopg://connectsphere:connectsphere@127.0.0.1:1/connectsphere"


def _migration_names() -> list[str]:
    return [m.name for m in migrate.list_migrations()]


def _count(url: str, table: str) -> int:
    with connection.connect(url) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608


@pytest.mark.story("1", ac=1)
@pytest.mark.story("1", ac=3)
def test_ready_creates_a_missing_database_and_prints_the_sample_logins(
    missing_url, docs_dir, capsys
):
    """`npm run db:ready` on a fresh checkout creates the database, migrates, seeds, writes the
    docs and ends with the table counts and the accounts to sign in with."""
    assert main(["--url", missing_url, "ready"]) == 0

    printed = capsys.readouterr().out
    name = connection.database_name(missing_url)
    assert f"created database {name}" in printed
    assert f"migrations: {len(_migration_names())} applied, 0 already present" in printed
    assert f"seed files: {len(migrate.list_seeds())} run" in printed
    assert "Table row counts:" in printed
    assert f"all use password {SEED_PASSWORD}" in printed
    assert all(email in printed for _, email in SEED_ACCOUNTS)
    assert printed.rstrip().endswith("Database is ready.")
    assert (docs_dir / "DATA_DICTIONARY.md").is_file()
    assert (docs_dir / "ERD.excalidraw").is_file()
    assert all(_count(missing_url, table) > 0 for table in REQUIRED_SEEDED_TABLES)


@pytest.mark.story("1", ac=3)
def test_ready_on_a_ready_database_applies_nothing_and_leaves_the_docs_alone(
    seeded_url, docs_dir, capsys
):
    """Re-running `npm run db:ready` re-seeds but applies no migration, so the docs stay as
    they are."""
    users_before = _count(seeded_url, "users")

    assert main(["--url", seeded_url, "ready"]) == 0

    printed = capsys.readouterr().out
    assert "created database" not in printed
    assert f"migrations: 0 applied, {len(_migration_names())} already present" in printed
    assert "Database is ready." in printed
    assert _count(seeded_url, "users") == users_before
    assert not docs_dir.exists()


@pytest.mark.story("1", ac=3)
def test_ready_without_the_seed_reports_the_required_tables_left_empty(empty_url, docs_dir, capsys):
    """`ready --no-seed` migrates, but a database with no sample data is not ready to use."""
    assert main(["--url", empty_url, "ready", "--no-seed", "--no-docs"]) == 1

    printed = capsys.readouterr().out
    assert "seed files" not in printed
    assert "ERROR: required tables are empty after seeding:" in printed
    assert "users" in printed
    assert "Database is ready." not in printed
    assert not docs_dir.exists()


@pytest.mark.story("1")
def test_ready_reports_a_server_it_cannot_reach(capsys):
    """With nothing listening, `ready` gives up after --wait seconds and says to start Docker."""
    assert main(["--url", UNREACHABLE_URL, "ready", "--wait", "0.1"]) == 1

    printed = capsys.readouterr().out
    assert "ERROR: PostgreSQL at" in printed
    assert "did not become reachable within" in printed
    assert "docker compose up -d" in printed


@pytest.mark.story("1")
def test_waiting_no_time_at_all_reports_the_server_without_trying_it():
    """A zero wait gives up before the first attempt, so there is no last error to quote."""
    with pytest.raises(connection.DatabaseUnavailable, match="Last error: None"):
        connection.wait_for_server(UNREACHABLE_URL, timeout_seconds=0)


@pytest.mark.story("1", ac=1)
def test_status_lists_every_migration_as_pending_on_an_empty_database(empty_url, capsys):
    """`npm run db:status` exits 1 while any migration is still to apply."""
    assert main(["--url", empty_url, "status"]) == 1

    printed = capsys.readouterr().out
    assert f"Database: {connection.database_name(empty_url)} @ " in printed
    assert "  applied : -" in printed
    assert f"  pending : {', '.join(_migration_names())}" in printed
    assert "  drifted : -" in printed


@pytest.mark.story("1", ac=1)
def test_status_is_clean_once_every_migration_is_applied(migrated_url, capsys):
    """Once migrated, every file is listed as applied and the status exits 0."""
    assert main(["--url", migrated_url, "status"]) == 0

    printed = capsys.readouterr().out
    assert f"  applied : {', '.join(_migration_names())}" in printed
    assert "  pending : -" in printed
    assert "  drifted : -" in printed


@pytest.mark.story("1", ac=1)
def test_an_applied_migration_edited_since_is_reported_and_blocks_migrate(migrated_url, capsys):
    """A file whose checksum no longer matches the one recorded when it was applied is drift:
    status lists it, and migrate refuses to go on and names the two ways out."""
    edited = _migration_names()[0]
    with connection.connect(migrated_url) as conn:
        conn.execute("UPDATE schema_migrations SET checksum = 'edited' WHERE name = %s", (edited,))

    assert main(["--url", migrated_url, "status"]) == 1
    assert f"  drifted : {edited}" in capsys.readouterr().out

    assert main(["--url", migrated_url, "migrate"]) == 1
    printed = capsys.readouterr().out
    assert f"ERROR: Applied migration(s) changed on disk: {edited}." in printed
    assert "npm run db:reset" in printed
    assert "new NNN_*.sql migration" in printed


@pytest.mark.story("1", ac=1)
def test_migrate_applies_each_pending_migration_once(empty_url, capsys):
    """The first run applies and records every file; a second run has nothing to apply."""
    names = _migration_names()

    assert main(["--url", empty_url, "migrate"]) == 0
    printed = capsys.readouterr().out
    assert f"  applying {names[0]} ..." in printed
    assert f"Applied {len(names)} migration(s)." in printed

    assert main(["--url", empty_url, "migrate"]) == 0
    assert capsys.readouterr().out.strip() == "Nothing to apply."
    assert _count(empty_url, "schema_migrations") == len(names)
    assert {"users", "events", "venues", "venue_bookings", "equipment_types"} <= set(
        migrate.table_row_counts(empty_url)
    )


@pytest.mark.story("1")
def test_a_migration_file_without_a_number_is_refused(tmp_path, monkeypatch):
    """Files apply in name order, so one not named NNN_description.sql has no place in it."""
    (tmp_path / "001_first.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "second.sql").write_text("SELECT 2;", encoding="utf-8")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)

    with pytest.raises(ValueError, match="second.sql: SQL files must be named NNN_description"):
        migrate.list_migrations()


@pytest.mark.story("1", ac=3)
def test_seed_runs_every_seed_file_and_reruns_without_duplicating_rows(migrated_url, capsys):
    """`npm run db:seed` loads the sample data; a second run upserts the same rows again."""
    assert main(["--url", migrated_url, "seed"]) == 0
    printed = capsys.readouterr().out
    assert f"Ran {len(migrate.list_seeds())} seed file(s)." in printed
    first = migrate.table_row_counts(migrated_url)

    assert main(["--url", migrated_url, "seed"]) == 0
    assert migrate.table_row_counts(migrated_url) == first
    assert first["users"] > 0


@pytest.mark.story("1", ac=3)
def test_seed_can_run_only_the_named_files(migrated_url):
    """`seed(only=...)` runs the files named by version or file name and skips the rest."""
    ran = migrate.seed(migrated_url, only=["010"], log=quiet)

    assert [f.name for f in ran] == ["010_reference_data.sql"]
    assert _count(migrated_url, "roles") > 0
    assert _count(migrated_url, "users") == 0


@pytest.mark.story("1")
def test_drop_empties_a_local_database_without_force(seeded_url, capsys):
    """`drop` needs no --force on a local database and leaves it with no tables at all."""
    assert main(["--url", seeded_url, "drop"]) == 0

    assert f"Dropped all objects in {connection.database_name(seeded_url)}." in (
        capsys.readouterr().out
    )
    assert migrate.table_row_counts(seeded_url) == {}


@pytest.mark.story("1", ac=1)
@pytest.mark.story("1", ac=3)
@pytest.mark.parametrize(
    ("options", "writes_docs"), [([], True), (["--no-docs"], False)], ids=["docs", "no-docs"]
)
def test_reset_rebuilds_the_database_from_scratch(
    seeded_url, docs_dir, capsys, options, writes_docs
):
    """`npm run db:reset` throws away rows added since, then migrates, seeds and (unless told
    not to) regenerates the docs."""
    seeded_venues = _count(seeded_url, "venues")
    with connection.connect(seeded_url) as conn:
        conn.execute(
            "INSERT INTO venues (name, location, capacity) VALUES ('Added since', 'Tower B', 40)"
        )

    assert main(["--url", seeded_url, "reset", *options]) == 0

    printed = capsys.readouterr().out
    assert f"Resetting {connection.database_name(seeded_url)} ..." in printed
    assert all(email in printed for _, email in SEED_ACCOUNTS)
    assert printed.rstrip().endswith("Reset complete.")
    assert _count(seeded_url, "schema_migrations") == len(_migration_names())
    assert _count(seeded_url, "venues") == seeded_venues
    assert (docs_dir / "DATA_DICTIONARY.md").is_file() is writes_docs


@pytest.mark.story("1")
@pytest.mark.parametrize("command", ["reset", "drop"])
def test_reset_and_drop_refuse_a_remote_database_before_connecting(monkeypatch, command):
    """Without --force, a database off this machine is refused before any connection is made."""

    def no_connection(*_args, **_kwargs):
        raise AssertionError("the tool connected before refusing")

    monkeypatch.setattr(psycopg, "connect", no_connection)

    with pytest.raises(SystemExit) as refused:
        main(["--url", REMOTE_URL, command])

    assert str(refused.value.code).startswith("Refusing to ")
    assert "db.example.com" in str(refused.value.code)
    assert "Pass --force" in str(refused.value.code)


@pytest.mark.story("1")
@pytest.mark.parametrize(
    ("url", "is_local"),
    [
        ("postgresql+psycopg://u:p@localhost:5433/x", True),
        ("postgresql://u:p@127.0.0.1/x", True),
        ("postgresql://u:p@[::1]:5433/x", True),
        ("postgresql://u:p@db:5432/x", True),
        ("postgresql://u:p@db.example.com:5432/x", False),
        ("postgresql:///x", False),
    ],
)
def test_only_this_machine_and_the_compose_service_count_as_local(url, is_local):
    """The hosts reset and drop accept without --force."""
    assert connection.is_local(url) is is_local


@pytest.mark.story("1")
@pytest.mark.parametrize("options", [[], ["--test"]], ids=["DATABASE_URL", "test-database"])
def test_a_command_given_no_url_cannot_reach_the_development_or_test_database(monkeypatch, options):
    """Without --url the tool falls back to DATABASE_URL, or with --test to the database the
    rest of the suite shares. Neither is the scratch database, so a test here that forgot --url
    must fail to connect rather than rebuild a database someone else is using."""
    tried = []

    def record(conninfo, **_kwargs):
        tried.append(connection.database_name(conninfo))
        raise psycopg.OperationalError("this test never connects")

    monkeypatch.setattr(psycopg, "connect", record)

    with pytest.raises(psycopg.OperationalError):
        main([*options, "status"])

    assert tried
    assert not set(tried) & PROTECTED_DATABASES


@pytest.mark.story("1")
def test_a_parsed_command_with_no_handler_exits_with_a_usage_error(monkeypatch, scratch_url):
    """argparse only lets through the commands main lists, so this is a guard against a new
    subcommand added to the parser without a case: main exits 2 rather than reporting success.
    The parser is replaced to hand main such a command, as no real argument list can."""
    parsed = argparse.Namespace(url=scratch_url, test=False, force=False, command="vacuum")
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda *_args: parsed)

    assert main(["vacuum"]) == 2


@pytest.mark.story("1", ac=1)
def test_python_m_app_dbtool_exits_with_the_commands_status(migrated_url, monkeypatch, capsys):
    """`python -m app.dbtool` runs main on the command line and exits with its return code."""
    monkeypatch.setattr(sys, "argv", ["app.dbtool", "--url", migrated_url, "status"])
    monkeypatch.delitem(sys.modules, "app.dbtool.__main__")

    with pytest.raises(SystemExit) as exited:
        runpy.run_module("app.dbtool", run_name="__main__")

    assert exited.value.code == 0
    assert "  pending : -" in capsys.readouterr().out
