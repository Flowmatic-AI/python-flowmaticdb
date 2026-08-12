"""Migration CLI.

    python migrate.py create add_email_to_users
    python migrate.py up
    python migrate.py down
    python migrate.py status

Adjust the `from app.db import ...` line to the project's layout.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from flowmaticdb.migrations import Migrator

from app.db import MIGRATIONS_DIR, connect

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def migration_filenames() -> list[str]:
    """Every migration file in the directory, in the order the runner applies them.

    Mirrors the runner's own rules: `.py`, no leading underscore, sorted by name.
    """
    if not os.path.isdir(MIGRATIONS_DIR):
        return []

    filenames = [
        entry
        for entry in os.listdir(MIGRATIONS_DIR)
        if entry.endswith(".py")
        and not entry.startswith("_")
        and os.path.isfile(os.path.join(MIGRATIONS_DIR, entry))
    ]

    return sorted(filenames)


def main() -> int:
    parser = argparse.ArgumentParser(prog="migrate", description="flowmaticdb migrations")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("up", help="Apply every pending migration as one batch")
    subparsers.add_parser("down", help="Roll back the most recently applied batch")
    subparsers.add_parser("status", help="Show applied and pending migrations")

    create_parser = subparsers.add_parser("create", help="Write a new migration file")
    create_parser.add_argument("name", help="snake_case name, e.g. add_email_to_users")

    args = parser.parse_args()

    db = connect()
    migrator = Migrator(db, MIGRATIONS_DIR)

    try:
        if args.command == "create":
            # The name goes into the filename verbatim, spaces included.
            if not NAME_PATTERN.match(args.name):
                print(f"name must be snake_case ([a-z][a-z0-9_]*), got: {args.name!r}", file=sys.stderr)
                return 1

            print(f"created {migrator.create(args.name)}")
            return 0

        migrator.init()

        if args.command == "up":
            migrator.up()
            print("migrations applied")
            return 0

        if args.command == "down":
            migrator.down()
            print("last batch rolled back")
            return 0

        if args.command == "status":
            rows = (
                db.select("migrations")
                .columns(["filename", "batch", "applied_at"])
                .order_by_asc("filename")
                .execute()
                .fetch_dicts()
            )
            applied = {row["filename"]: row for row in rows}
            filenames = migration_filenames()

            for filename in filenames:
                row = applied.get(filename)

                if row is None:
                    print(f"  pending  {filename}")
                    continue

                print(f"  applied  {filename}  batch {row['batch']}  {row['applied_at']}")

            for filename in applied:
                if filename not in filenames:
                    print(f"  MISSING  {filename}  (recorded as applied, file is gone)")

            return 0

        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
