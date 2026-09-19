"""Apply SQL migrations and seed files.

Design (see docs/database/README.md for the team-facing explanation):

* ``backend/db/migrations/NNN_name.sql`` - applied once, in filename order, each inside its own
  transaction. Applied versions and a SHA-256 checksum are recorded in ``schema_migrations``.
  If an already-applied file changes on disk the tool reports *drift* and refuses to continue;
  during Sprint 1 the fix is ``npm run db:reset``, later sprints add a new file instead.
* ``backend/db/seed/NNN_name.sql`` - re-run on every ``seed``/``ready``. Seed files must be
  idempotent (UPSERTs), so re-running self-heals the canonical sample rows and never
  duplicates them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import psycopg

from app.dbtool.connection import connect

BACKEND_DIR = Path(__file__).resolve().parents[2]
DB_DIR = BACKEND_DIR / "db"
MIGRATIONS_DIR = DB_DIR / "migrations"
SEED_DIR = DB_DIR / "seed"

MIGRATIONS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    checksum   TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE schema_migrations IS
    'Infrastructure. One row per migration file applied by app.dbtool; '
    'the checksum detects edits to already-applied files.';
COMMENT ON COLUMN schema_migrations.version IS 'Numeric prefix of the migration file, e.g. 001.';
COMMENT ON COLUMN schema_migrations.name IS 'Migration file name.';
COMMENT ON COLUMN schema_migrations.checksum IS 'SHA-256 of the file contents when applied.';
COMMENT ON COLUMN schema_migrations.applied_at IS 'When it was applied.';
"""


class MigrationDrift(RuntimeError):
    """An already-applied migration file has been edited."""


@dataclass(frozen=True)
class SqlFile:
    version: str
    name: str
    path: Path

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")


def _list_sql_files(directory: Path) -> list[SqlFile]:
    files = []
    for path in sorted(directory.glob("*.sql")):
        version, _, _ = path.name.partition("_")
        if not version.isdigit():
            raise ValueError(f"{path.name}: SQL files must be named NNN_description.sql")
        files.append(SqlFile(version=version, name=path.name, path=path))
    return files


def list_migrations() -> list[SqlFile]:
    return _list_sql_files(MIGRATIONS_DIR)


def list_seeds() -> list[SqlFile]:
    return _list_sql_files(SEED_DIR)


@dataclass
class MigrationStatus:
    applied: list[tuple[str, str]]  # (version, name)
    pending: list[SqlFile]
    drifted: list[SqlFile]

    @property
    def is_clean(self) -> bool:
        return not self.pending and not self.drifted


def _ensure_migrations_table(conn: psycopg.Connection) -> None:
    conn.execute(MIGRATIONS_TABLE_DDL)


def status(url: str) -> MigrationStatus:
    with connect(url) as conn:
        _ensure_migrations_table(conn)
        rows = conn.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        conn.commit()
    recorded = {version: (name, checksum) for version, name, checksum in rows}
    pending, drifted = [], []
    for migration in list_migrations():
        if migration.version not in recorded:
            pending.append(migration)
        elif recorded[migration.version][1] != migration.checksum:
            drifted.append(migration)
    return MigrationStatus(
        applied=[(v, n) for v, (n, _) in recorded.items()], pending=pending, drifted=drifted
    )


def migrate(url: str, *, log=print) -> list[SqlFile]:
    """Apply every pending migration. Raises MigrationDrift if an applied file was edited."""
    current = status(url)
    if current.drifted:
        names = ", ".join(m.name for m in current.drifted)
        raise MigrationDrift(
            f"Applied migration(s) changed on disk: {names}.\n"
            "  - Sprint 1: run `npm run db:reset` to rebuild the local database from scratch.\n"
            "  - Later sprints: do not edit applied migrations; add a new NNN_*.sql file instead."
        )
    applied: list[SqlFile] = []
    for migration in current.pending:
        with connect(url) as conn:
            log(f"  applying {migration.name} ...")
            conn.execute(migration.read())
            conn.execute(
                "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                (migration.version, migration.name, migration.checksum),
            )
            conn.commit()
        applied.append(migration)
    return applied


def seed(url: str, *, only: list[str] | None = None, log=print) -> list[SqlFile]:
    """Run every seed file (or the named subset) inside one transaction each."""
    ran: list[SqlFile] = []
    for seed_file in list_seeds():
        if only and seed_file.name not in only and seed_file.version not in only:
            continue
        with connect(url) as conn:
            log(f"  seeding  {seed_file.name} ...")
            conn.execute(seed_file.read())
            conn.commit()
        ran.append(seed_file)
    return ran


def drop_all_objects(url: str) -> None:
    """Wipe the public schema (tables, types, functions) without dropping the database."""
    with connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.execute("COMMENT ON SCHEMA public IS 'standard public schema'")


def table_row_counts(url: str) -> dict[str, int]:
    """Exact row counts for every table in the public schema (used by `ready` to verify)."""
    counts: dict[str, int] = {}
    with connect(url) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            )
        ]
        for table in tables:
            counts[table] = conn.execute(
                psycopg.sql.SQL("SELECT count(*) FROM {}").format(psycopg.sql.Identifier(table))
            ).fetchone()[0]
    return counts
