# Migrations

## The model

A migration is one `.py` file holding exactly one `MigrationABC` subclass:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from flowmaticdb.migrations import MigrationABC

if TYPE_CHECKING:
    from flowmaticdb.database import DB


class CreateUsersTable(MigrationABC):
    def up(self, db: DB) -> None:
        db.create_table("users").if_not_exists().identity("id").string("email", size=255, not_null=True).execute()

    def down(self, db: DB) -> None:
        db.drop_table("users").if_exists().execute()
```

`Migrator(db, migrations_dir, migrations_table="migrations")` drives them:

| Method | Effect |
|---|---|
| `init()` | Creates the `migrations` bookkeeping table (`if_not_exists`, so it is idempotent) |
| `up()` | Applies every file not yet recorded, in filename order, as one new batch |
| `down()` | Rolls back the **most recent batch**, reverse filename order |
| `create(name)` | Writes `<UTC timestamp>_<name>.py` from the template and returns its path |

Rules the runner enforces, worth knowing before you fight them:

- **`init()` must run before `up()` or `down()`.** They read the bookkeeping
  table directly and fail with "no such table" otherwise. The CLI template calls
  it every time.
- **`create(name)` puts `name` in the filename verbatim** — spaces and all.
  Always pass `snake_case`: `add_email_to_users`, never `"add email to users"`.
- **Ordering is a plain sort of the filenames**, which is why the timestamp
  prefix matters. Do not rename applied files; the bookkeeping table keys on the
  filename.
- **One `MigrationABC` subclass per file.** Zero or two raises `DatabaseError`.
  Classes imported from elsewhere are ignored, so shared helpers are fine.
- **Files starting with `_` are skipped** — that is where helper modules go.
- **Each migration runs inside a transaction** unless it overrides
  `in_transaction()` to return `False`. On MySQL that guarantee is thin: DDL
  commits implicitly, so a file with several DDL statements cannot be half
  rolled back. Keep one logical change per file.
- **`down()` rolls back a whole batch**, not a single file. Everything `up()`
  applied in one run comes back off together.

## Layout

```
app/
  db.py               # connect() / get_db() / close_db(), MIGRATIONS_DIR
  migrations/
    20260812093000_initial_schema.py
    20260813104500_add_email_to_users.py
migrate.py            # CLI entrypoint
```

Copy `assets/db.py` and `assets/migrate.py` and adjust the import paths and env
var names to the project. Then:

```bash
python migrate.py create add_email_to_users
python migrate.py up
python migrate.py status
python migrate.py down
```

Run `up` on deploy, before the app starts serving. Do not run it from the app's
request path or from every worker at once.

## Writing the initial schema migration

This is the step that makes an existing database adoptable. The initial
migration has to be safe to apply to **a database that already has the schema**,
because that is the normal case — production already exists.

Hence the safeguards, on every statement:

- `create_table(...)` → always `.if_not_exists()`
- `drop_table(...)` → always `.if_exists()`
- indexes → `CREATE INDEX IF NOT EXISTS` / `DROP INDEX IF EXISTS` (see the MySQL
  caveat below)
- `down()` drops in **reverse dependency order** — children before parents, or
  the foreign keys block the drop

### From docker entrypoint SQL

`docker-entrypoint-initdb.d/*.sql` only ever runs against an empty data volume,
so it silently stops being the schema the moment anyone alters a table by hand.
Converting it to a migration is the point of this exercise.

1. **Collect the files in the order the entrypoint runs them** — alphabetical
   within the mounted directory. Check `docker-compose.yml` for what is mounted
   where, and read every file.
2. **Rebuild each statement with the builder**, not as a SQL string. The builder
   renders per dialect, and `db.exec()` refuses more than one statement at a
   time, so the file cannot simply be piped through.
3. **Order tables parents-first** in `up()` so foreign keys resolve.
4. **Reverse that order in `down()`.**
5. **Seed data**, if the entrypoint inserts any, goes through
   `.on_conflict_do_nothing(...)` so re-running is harmless.
6. **Stop mounting the entrypoint SQL** once the migration exists, so there is
   one owner of the schema. Keep the `.sql` in git history, not in the container.
7. **Diff the result against the live schema** before trusting it — a
   hand-altered production table that the entrypoint never knew about will be
   skipped by `if_not_exists` and silently diverge. `\d+ <table>` on PostgreSQL,
   `SHOW CREATE TABLE` on MySQL, `.schema` on SQLite.

### Worked example

```sql
-- docker-entrypoint-initdb.d/01-schema.sql
CREATE TABLE roles (
    id   BIGSERIAL PRIMARY KEY,
    name VARCHAR(64) NOT NULL UNIQUE
);

CREATE TABLE users (
    id          BIGSERIAL PRIMARY KEY,
    email       VARCHAR(255) NOT NULL UNIQUE,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    preferences JSONB,
    created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE posts (
    id      BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    title   VARCHAR(255) NOT NULL,
    body    TEXT
);

CREATE INDEX idx_posts_user_id ON posts (user_id);

INSERT INTO roles (name) VALUES ('admin'), ('editor');
```

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from flowmaticdb.migrations import MigrationABC
from flowmaticdb.query.enums import ReferentialActionEnum

if TYPE_CHECKING:
    from flowmaticdb.database import DB


class InitialSchema(MigrationABC):
    def up(self, db: DB) -> None:
        db.create_table("roles").if_not_exists() \
            .identity("id") \
            .string("name", size=64, not_null=True) \
            .unique_constraint(["name"], name="uq_roles_name") \
            .execute()

        db.create_table("users").if_not_exists() \
            .identity("id") \
            .string("email", size=255, not_null=True) \
            .boolean("active", not_null=True, default=True) \
            .json("preferences") \
            .current_timestamp("created_at") \
            .unique_constraint(["email"], name="uq_users_email") \
            .execute()

        db.create_table("posts").if_not_exists() \
            .identity("id") \
            .integer("user_id", not_null=True) \
            .string("title", size=255, not_null=True) \
            .text("body") \
            .foreign_key_constraint(
                "user_id",
                "users",
                "id",
                referential_actions=[ReferentialActionEnum.ON_DELETE_CASCADE],
            ) \
            .execute()

        create_index_if_not_exists(db, "idx_posts_user_id", "posts", ["user_id"])

        db.insert("roles").values(
            {"name": "admin"},
            {"name": "editor"},
        ).on_conflict_do_nothing(["name"]).execute()

    def down(self, db: DB) -> None:
        drop_index_if_exists(db, "idx_posts_user_id", "posts")
        db.drop_table("posts").if_exists().execute()
        db.drop_table("users").if_exists().execute()
        db.drop_table("roles").if_exists().execute()
```

`migrations/_helpers.py` is not importable as `from _helpers import ...` on its
own — the runner loads each migration by file path, not as a package member, so
put the directory on `sys.path` at the top of the migration, or inline the two
helpers in the file that needs them:

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _helpers import create_index_if_not_exists, drop_index_if_exists
```

Note what changed and why:

- `BIGSERIAL PRIMARY KEY` → `.identity("id")`, which renders as
  `GENERATED BY DEFAULT AS IDENTITY` on PostgreSQL 17+, `BIGSERIAL` below that,
  `AUTO_INCREMENT` on MySQL and `INTEGER PRIMARY KEY AUTOINCREMENT` on SQLite.
- The inline `UNIQUE` became a named constraint. SQLite strips constraint names
  rather than failing, so the name is portable.
- `REFERENCES ... ON DELETE CASCADE` → `foreign_key_constraint(...)` with
  `ReferentialActionEnum`, which is the enum, not a string.
- `TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP` → `.current_timestamp("created_at")`.
  A plain `.datetime("created_at")` is the column without the default.
- `JSONB` → `.json(...)`, which picks `JSONB` / `JSON` / `TEXT` per server version.
- The seed insert gained `on_conflict_do_nothing(["name"])`. Pass the conflict
  target as a **list of columns**: a bare string means a *named constraint*,
  which SQLite rejects outright with
  `QueryError: Named ON CONFLICT constraints are not supported by SQLite`.

### Indexes

There is no index builder — indexes go through `db.exec()`. `IF NOT EXISTS` on
an index is supported by PostgreSQL and SQLite but **not by MySQL** (MariaDB
does support it, but the dialect does not expose which of the two it is
publicly, so the whole family takes the catalog check). Put the helper in
`migrations/_helpers.py` (underscore-prefixed, so the runner skips it):

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from flowmaticdb.dialects import MySQLDialect

if TYPE_CHECKING:
    from flowmaticdb.database import DB


def create_index_if_not_exists(db: DB, name: str, table: str, columns: list[str]) -> None:
    dialect = db.dialect
    escaped_name = dialect.escape_identifier(name)
    escaped_table = dialect.escape_identifier(table)
    escaped_columns = ", ".join(dialect.escape_identifier(column) for column in columns)

    if isinstance(dialect, MySQLDialect):
        if _mysql_index_exists(db, table, name):
            return
        db.exec(f"CREATE INDEX {escaped_name} ON {escaped_table} ({escaped_columns})")
        return

    db.exec(f"CREATE INDEX IF NOT EXISTS {escaped_name} ON {escaped_table} ({escaped_columns})")


def drop_index_if_exists(db: DB, name: str, table: str) -> None:
    dialect = db.dialect
    escaped_name = dialect.escape_identifier(name)
    escaped_table = dialect.escape_identifier(table)

    if isinstance(dialect, MySQLDialect):
        if not _mysql_index_exists(db, table, name):
            return
        db.exec(f"DROP INDEX {escaped_name} ON {escaped_table}")
        return

    db.exec(f"DROP INDEX IF EXISTS {escaped_name}")


def _mysql_index_exists(db: DB, table: str, name: str) -> bool:
    result = db.prepared(
        "SELECT count(*) FROM information_schema.statistics "
        "WHERE table_schema = database() AND table_name = ? AND index_name = ?",
        [table, name],
    )
    return int(result.scalar()) > 0
```

Index names must be unique per schema on PostgreSQL and per table on MySQL —
prefix them with the table name and they are safe on both.

### From a live database with no SQL file

Dump the schema and translate it the same way:

```bash
pg_dump --schema-only --no-owner --no-privileges "$DATABASE_URL" > schema.sql
mysqldump --no-data --skip-add-drop-table <db> > schema.sql
sqlite3 app.db .schema > schema.sql
```

Then delete `schema.sql` — the migration is the artefact, not the dump.

## Subsequent migrations

Each schema change is a new file. Both directions must be written; a migration
whose `down()` is a stub is a migration that cannot be rolled back.

```python
class AddNicknameToUsers(MigrationABC):
    def up(self, db: DB) -> None:
        db.alter_table("users").add_string("nickname", size=64).execute()

    def down(self, db: DB) -> None:
        db.alter_table("users").drop_column("nickname").execute()
```

`ALTER TABLE` emits one statement per alteration, so several chained calls are
several statements — and on MySQL, several implicit commits.

SQLite refuses `ALTER COLUMN` and all named constraint alterations with
`QueryError`. Changing a column type or adding a constraint there means the
create-copy-drop-rename dance in `db.exec()` calls, guarded by
`if_not_exists` / `if_exists` like everything else.

## Adopting migrations for a database that already exists

1. Write the initial migration from the current schema, with the safeguards.
2. Run `python migrate.py up` against a **copy** of production first, confirm it
   creates nothing and records one row.
3. Run it against production. It writes the bookkeeping row and touches no table.
4. From then on, every schema change is a migration file.

Do not backfill fake history — one initial migration representing "the schema as
it was on adoption day" is the whole point.
