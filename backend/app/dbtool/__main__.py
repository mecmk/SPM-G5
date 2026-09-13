"""Command-line entry point: ``uv run python -m app.dbtool <command>``.

Commands
--------
status   Show applied / pending / drifted migrations.
migrate  Apply pending migrations.
seed     Run the seed files (idempotent).
reset    Drop everything in the database, then migrate + seed + docs.  (local only)
ready    Wait for the server, create the DB if missing, migrate, seed, verify, print a summary.
         This is what `npm run db:ready` runs.
docs     Regenerate docs/database/DATA_DICTIONARY.md and ERD.excalidraw from the live schema.
drop     Drop every object in the database (no rebuild).                (local only)

Options
-------
--url URL   Target a different database (default: DATABASE_URL from backend/.env).
--test      Target the test database (TEST_DATABASE_URL, default "<db>_test").
--force     Allow reset/drop against a non-local database.
"""

from __future__ import annotations

import argparse
import sys

from app.config import settings
from app.dbtool import connection, docs, migrate

SEED_ACCOUNTS = [
    ("Event Organiser", "organiser@acme.example"),
    ("Event Organiser", "organiser@nimbus.example"),
    ("Event Coordinator", "coordinator@connectsphere.example"),
    ("Event Coordinator", "coordinator2@connectsphere.example"),
    ("Venue Staff", "venue@connectsphere.example"),
    ("Technical Support Staff", "tech@connectsphere.example"),
    ("Attendee", "attendee@example.com"),
]
SEED_PASSWORD = "Password123!"

# Tables that must contain rows after seeding for the app to be usable.
REQUIRED_SEEDED_TABLES = ["roles", "users", "venues", "facilities", "room_layouts"]


def _print_counts(url: str) -> None:
    counts = migrate.table_row_counts(url)
    width = max(len(t) for t in counts)
    print("  Table row counts:")
    for table, count in counts.items():
        print(f"    {table:<{width}}  {count}")


def _print_accounts() -> None:
    print("  Sample logins (all use password " + SEED_PASSWORD + "):")
    for role, email in SEED_ACCOUNTS:
        print(f"    {role:<24} {email}")


def _guard_local(url: str, force: bool, action: str) -> None:
    if not connection.is_local(url) and not force:
        sys.exit(
            f"Refusing to {action} a non-local database ({connection.server_url(url)}). "
            "Pass --force if you really mean it."
        )


def cmd_status(url: str) -> int:
    st = migrate.status(url)
    print(f"Database: {connection.database_name(url)} @ {connection.server_url(url)}")
    print(f"  applied : {', '.join(n for _, n in st.applied) or '-'}")
    print(f"  pending : {', '.join(m.name for m in st.pending) or '-'}")
    print(f"  drifted : {', '.join(m.name for m in st.drifted) or '-'}")
    return 0 if st.is_clean else 1


def cmd_migrate(url: str) -> int:
    applied = migrate.migrate(url)
    print(f"Applied {len(applied)} migration(s)." if applied else "Nothing to apply.")
    return 0


def cmd_seed(url: str) -> int:
    ran = migrate.seed(url)
    print(f"Ran {len(ran)} seed file(s).")
    return 0


def cmd_docs(url: str) -> int:
    docs.generate(url)
    return 0


def cmd_drop(url: str, force: bool) -> int:
    _guard_local(url, force, "drop all objects in")
    migrate.drop_all_objects(url)
    print(f"Dropped all objects in {connection.database_name(url)}.")
    return 0


def cmd_reset(url: str, force: bool, *, with_docs: bool = True) -> int:
    _guard_local(url, force, "reset")
    connection.wait_for_server(url)
    connection.ensure_database(url)
    print(f"Resetting {connection.database_name(url)} ...")
    migrate.drop_all_objects(url)
    migrate.migrate(url)
    migrate.seed(url)
    if with_docs:
        docs.generate(url)
    _print_counts(url)
    _print_accounts()
    print("Reset complete.")
    return 0


def cmd_ready(url: str, *, with_seed: bool = True, with_docs: bool = True, wait: float = 30) -> int:
    print(f"Checking database {connection.database_name(url)} @ {connection.server_url(url)}")
    connection.wait_for_server(url, timeout_seconds=wait)
    if connection.ensure_database(url):
        print(f"  created database {connection.database_name(url)}")
    st = migrate.status(url)
    if st.drifted:
        print(
            "ERROR: migration file(s) changed after being applied: "
            + ", ".join(m.name for m in st.drifted)
        )
        print("  Sprint 1 fix: `npm run db:reset` (rebuilds the local database from scratch).")
        print("  From Sprint 2: leave applied files alone and add a new NNN_*.sql migration.")
        return 1
    applied = migrate.migrate(url)
    print(f"  migrations: {len(applied)} applied, {len(st.applied)} already present")
    if with_seed:
        ran = migrate.seed(url)
        print(f"  seed files: {len(ran)} run")
    if applied and with_docs:
        docs.generate(url)
    counts = migrate.table_row_counts(url)
    empty = [t for t in REQUIRED_SEEDED_TABLES if counts.get(t, 0) == 0]
    if empty:
        print("ERROR: required tables are empty after seeding: " + ", ".join(empty))
        return 1
    _print_counts(url)
    _print_accounts()
    print("Database is ready.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.dbtool", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--url", help="database URL (default: DATABASE_URL)")
    parser.add_argument("--test", action="store_true", help="target the test database")
    parser.add_argument(
        "--force", action="store_true", help="allow destructive commands off-localhost"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("migrate")
    sub.add_parser("seed")
    sub.add_parser("docs")
    sub.add_parser("drop")
    reset = sub.add_parser("reset")
    reset.add_argument("--no-docs", action="store_true")
    ready = sub.add_parser("ready")
    ready.add_argument("--no-seed", action="store_true")
    ready.add_argument("--no-docs", action="store_true")
    ready.add_argument("--wait", type=float, default=30, help="seconds to wait for the server")
    args = parser.parse_args(argv)

    url = args.url or (settings.resolved_test_database_url if args.test else settings.database_url)
    try:
        match args.command:
            case "status":
                return cmd_status(url)
            case "migrate":
                return cmd_migrate(url)
            case "seed":
                return cmd_seed(url)
            case "docs":
                return cmd_docs(url)
            case "drop":
                return cmd_drop(url, args.force)
            case "reset":
                return cmd_reset(url, args.force, with_docs=not args.no_docs)
            case "ready":
                return cmd_ready(
                    url, with_seed=not args.no_seed, with_docs=not args.no_docs, wait=args.wait
                )
    except (connection.DatabaseUnavailable, migrate.MigrationDrift) as exc:
        print(f"ERROR: {exc}")
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
