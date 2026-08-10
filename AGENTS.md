# flowmaticdb — Agent Instructions

A Python database abstraction layer (PostgreSQL + SQLite + MySQL), ported from PHP `sentience/database`.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Commands

| Command | Purpose |
|---------|---------|
| `python3 -m pytest` | Run all tests (unit + SQLite integration; 398 collected, 2 pre-existing failures in `test_database_port.py`) |
| `python3 -m pytest tests/test_integration_sqlite.py` | SQLite integration tests |
| `python3 -m pytest tests/test_integration_postgres.py` | PostgreSQL integration tests (skips when PG not reachable on localhost:5432; run `docker compose up -d postgres`) |
| `python3 -m pytest tests/test_integration_mysql.py` | MySQL integration tests (skips when MySQL not reachable on localhost:3306; run `docker start sentience-v3-mysql-1` or any `mysql` container with `MYSQL_ALLOW_EMPTY_PASSWORD=yes` on port 3306 — the suite auto-creates the `flowmaticdb` database) |
| `python3 -m pytest tests/test_dialect_sql.py -k "test_select"` | Single test or pattern |
| `python3 -m mypy src/flowmaticdb` | Typecheck (strict mode). Clean — no issues. |
| `python3 -m ruff check src/flowmaticdb/ tests/` | Lint. Clean — no issues. |
| `python3 main.py` | Run the example script (SQLite + PostgreSQL + MySQL CRUD + giant select) |

No Makefile, CI workflows, or pre-commit hooks exist.

## Architecture

Five pillars under `src/flowmaticdb/`:

- **`dialects/`** — SQL generation (`SQLDialect` base, `PostgresqlDialect`, `SQLiteDialect`). `SQLDialect` is the largest file (~713 lines).
- **`adapters/`** — Connection wrappers (`SQLiteAdapter`, `PsycopgAdapter`, `AsyncpgAdapter`, `MySQLAdapter`). Connection lifecycle is four methods: `_connect()` opens, `_disconnect()` unconditionally drops the driver handle, `close()` is the public teardown that honours the `persistent`/`optimize` options, and `is_connected()` reports liveness. `reconnect()` is concrete on `AdapterABC` (`_disconnect()`, errors suppressed, then `_connect()`); `AsyncpgAdapter` overrides it to restart its loop thread first, since its `close()` tears the loop down too.
- **`query/`** — Fluent query builders (`SelectQuery`, `InsertQuery`, `UpdateQuery`, `DeleteQuery`, `CreateTableQuery`, `AlterTableQuery`, `DropTableQuery`). Mixins: `WhereMixin`, `HavingMixin`, `JoinsMixin`, etc.
- **`result/`** — Result set abstraction (`Result`, `SQLite3Result`, `PsycopgResult`, `AsyncpgResult`, `MySQLResult`). Methods: `fetch_dict()`, `fetch_dicts()`, `scalar()`, `fetch_object()`, `fetch_objects()`, `columns()`.
- **`migrations/`** — Schema migrations. Subclass `MigrationABC` (`up(db)`/`down(db)` abstract — the `DB` is passed in, not stored on the instance; `in_transaction()` returns `True` by default). `Migrator(db, migrations_dir, migrations_table="migrations")` drives them: `init()`, `up()`, `down()`, `create(name)`.

User-facing facade: `from flowmaticdb.database import DB`

```python
db = DB.connect_sqlite(":memory:")
db = DB.connect_postgresql("mydb", host="localhost", user="postgres")
result = db.select("users").where_equals("name", "Alice").execute()
row = result.fetch_dict()
```

Within each package, modules named with a leading underscore (e.g. `flowmaticdb.adapters._postgres`) are private implementation details — never import from them.

## Import gotchas

- Always import from the package, never a `_`-prefixed module inside it: `from flowmaticdb.adapters import PsycopgAdapter`, not `from flowmaticdb.adapters._postgres import PsycopgAdapter`.
- `PsycopgAdapter` is exported from `flowmaticdb.adapters` — `from flowmaticdb.adapters import PsycopgAdapter`.
- `PsycopgResult` is exported from `flowmaticdb.result` — `from flowmaticdb.result import PsycopgResult`.
- `raw()`, `identifier()`, `alias()`, `expression()`, `sub_query()`, `current_timestamp()`, `now()` — module-level functions exported from the top-level package: `from flowmaticdb import raw`.
- `PostgresArray` — value wrapper that opts a list into a PostgreSQL array instead of JSON. Lives in `flowmaticdb.query.expressions`, re-exported from the top level: `from flowmaticdb import PostgresArray`.
- Snapshot a result: `from flowmaticdb.result import snapshot_result`.
- Exception classes: `from flowmaticdb import QueryError` — they live in `_exceptions.py` and are re-exported from the top-level package.

## Key conventions

- **Leading underscore = private** — a `_`-prefixed module name marks an implementation detail. A package's public API is exactly its `__init__.py` `__all__`; import from the package, never from a module inside it. This holds without exception, including `_exceptions.py` and `_helpers.py`.
- **ABCs over Protocols** — nominal subtyping (`abc.ABC`) used everywhere.
- **Mixins over traits** — multiple inheritance with `WhereMixin`, `HavingMixin`, etc.
- **Fluent API returns `Self`** — all query builder methods return `Self` for chaining.
- **`to_query_with_params()`** — central method that returns `QueryWithParams(query, params)`. Each query class implements this.
- **`execute(emulate_prepare=False)`** — runs via the bound database, returns `ResultABC`.
- **`emulate_prepare`** — parameter for `query_with_params()` and `execute()` (used for drivers without native prepared statements).
- **`from __future__ import annotations`** — used in every file.
- **`if TYPE_CHECKING`** — used for lazy imports in type stubs.

## Dialect quirks

- `SQLDialect` properties like `bool`, `distinct_on`, `on_conflict`, `returning` are instance attributes (not abstract properties), set in `__init__`.
- `PostgresqlDialect.datetime_format = "%Y-%m-%d %H:%M:%S.%f"` (microseconds).
- `SQLiteDialect` raises `QueryError` for ALTER COLUMN, DROP COLUMN, named constraints, and named ON CONFLICT.
- `TypeEnum.JSON` → `JSONB`/`JSON`/`TEXT` per server version, gated by the `json`/`jsonb` dialect flags set in `_version_gate()`.
- Version parsing: `"15.2"` → `150200` (major\*100^2 + minor\*100 + patch).

## Testing

- **Testing**: 396 tests pass without any database (unit + SQLite in-memory integration). 2 pre-existing failures in `test_database_port.py`.
- **Unit tests** (no database): `test_dialect_*.py`, `test_*_query.py`, `test_conditions.py`, `test_joins.py`, `test_expressions.py`, `test_query_with_params.py`, `test_result_abstract.py`, `test_json_and_datetime_types.py`.
- **Integration tests**: `test_integration_sqlite.py` uses SQLite `:memory:` — no external services needed. `test_integration_postgres.py` requires a PostgreSQL service on `localhost:5432` (skipped via `pytestmark` when unreachable; run `docker compose up -d postgres`). `test_integration_mysql.py` requires a MySQL service on `localhost:3306` with `MYSQL_ALLOW_EMPTY_PASSWORD=yes` (skipped via a session-scoped fixture when unreachable; the suite auto-creates the `flowmaticdb` database and drops all user tables between tests).
- **Fixtures**: `conftest.py` provides `sql_dialect`, `sqlite_dialect`, `pg_dialect`, `mysql_dialect`. The postgres integration module defines its own `pg_adapter` / `pg_dialect` / `pg_db` yield fixtures. The mysql integration module defines `mysql_adapter` / `mysql_dialect` (the latter overrides the conftest one within that module) plus a session-scoped `_flowmaticdb_database` bootstrap fixture.
- **DDL has no parameters** — use `adapter.exec(qwp.query)` not `adapter.query_with_params()`.
- **DML uses parameters** — use `adapter.query_with_params(dialect, qwp)`.
- **Placeholder conversion lives in adapters** — each adapter converts the dialect's `?` placeholders to its driver's native format:
  - `SQLiteAdapter.query_with_params()` calls `percent_s_to_question_marks()` — `%s` → `?` (SQLite uses `?` natively)
  - `PsycopgAdapter.query_with_params()` calls `question_marks_to_percent_s()` — `?` → `%s` (psycopg uses `%s`)
  - `MySQLAdapter.query_with_params()` calls `question_marks_to_percent_s()` — `?` → `%s` (mysql.connector uses `%s`)
  - `AsyncpgAdapter.query_with_params()` calls the module-local `_placeholders_to_dollar_signs()` — both `?` and `%s` → `$1`, `$2`, … (asyncpg only speaks native PostgreSQL placeholders)
  - Both methods are on `QueryWithParams` and use `REGEX_PATTERN` to skip placeholders inside quoted strings and comments.
  - The `DatabaseABC.prepared()` method passes the `QueryWithParams` through unchanged — the adapter handles conversion.
- **Two PostgreSQL drivers** — `Database.connect_postgresql(..., asyncpg_adapter=True)` selects `AsyncpgAdapter`; the default is `PsycopgAdapter`. Both share `PostgresqlDialect`. asyncpg is coroutine-only, so `AsyncpgAdapter` owns a private event loop on a daemon thread and blocks on `run_coroutine_threadsafe` — that keeps the synchronous `AdapterABC` surface intact and also works when called from inside a running loop. It binds temporal values natively instead of using the dialect's strftime cast, and rejects the `client_encoding` option (asyncpg is UTF-8 only).
- **MySQL now uses `autocommit=True`** — `MySQLAdapter._connect()` passes `autocommit=True` to `mysql.connector.connect()`. Every statement commits immediately. No implicit transaction workarounds needed.
- **Datetime and JSON values are serialized/deserialized on every adapter** — see the "Datetime and JSON Values" section of `README.md` for the user-facing contract. Implementation notes:
  - `flowmaticdb/_json.py` (private) holds `encode_json()` / `decode_json()`; the dialects expose them as `cast_json()` / `parse_json()` (abstract on `DialectABC`, implemented on `SQLDialect`).
  - A bare `dict`/`list` is a JSON document on **every** dialect, PostgreSQL included. PostgreSQL arrays are opt-in via `PostgresArray` (`flowmaticdb.query.expressions`, re-exported from `flowmaticdb`) — a plain value wrapper, deliberately **not** a `SqlABC`, so `_build_question_marks()` binds it as a parameter instead of inlining SQL.
  - `PostgresqlDialect.cast_to_driver()` unwraps `PostgresArray` to a plain list (element types untouched, so the driver types them natively) and `cast_to_query()` renders it as `ARRAY[...]` (`'{}'` when empty) for `emulate_prepare`. `SQLDialect` unwraps it to JSON instead — engines with no array type drop the array reading rather than erroring, so a PostgreSQL-shaped query still runs on SQLite/MySQL.
  - `AsyncpgAdapter._open()` registers `json`/`jsonb` type codecs; `_cast_param()` leaves `dict`/`list`/`PostgresArray` native because whether a document has to be rendered depends on the placeholder type, which only `_adapt_param()` knows. There, a document is passed through for `_JSON_TYPE_OIDS` and `cast_json()`-rendered everywhere else — which is what makes a bare list bound to an array column fail loudly on asyncpg too, matching psycopg.
  - `MySQLResult` decodes columns the server reports as type code 245 (`json`); it tracks them by *position*, so duplicate column names in a join still decode correctly.
  - `SQLiteAdapter._connect()` opens connections with `check_same_thread=False` unless the `check_same_thread` option says otherwise — deliberately unlike stock `sqlite3`, which would raise `ProgrammingError` whenever a threaded server opens a connection on one worker thread and closes it on another. Interleaving is still the caller's problem (see the SQLite section of `README.md`).
  - `SQLiteAdapter._connect()` calls the module-local `_register_types()` (idempotent, so it runs per connect rather than at import) and opens connections with `detect_types=sqlite3.PARSE_DECLTYPES`. Registration mutates the process-wide `sqlite3` registry — that is deliberate and commented. Params of type `datetime`/`date`/`dict`/`list` bypass `cast_to_driver()` (see the module-local `_cast_param()`) so the registered adapters serialize them at full ISO-8601 fidelity; the dialect's `datetime_format` drops microseconds.
- **Fluent table reassignment** — use `.table("new_table")` instead of `.from_("new_table")` on `SelectQuery`, `DeleteQuery`, and `DropTableQuery`.
- **Qualified column references** — pass columns/conditions as two-element lists (e.g. `["users", "id"]`) or wrap in `identifier(["users","id"])`. A dotted string like `"users.id"` is treated as a single identifier and escaped as `` `users.id` `` (non-existent column). Use `raw("...")` (a `SqlABC`) for raw JOIN clauses and aggregate expressions — `JoinsMixin.join()` ignores bare strings.
- **Schema-qualified INSERT/DELETE/UPDATE/CREATE** — pass `list[str]` directly (e.g. `db.insert(["schema", "table"])`). The dialect handles list splitting natively.

## Reference

- `PLAN.md` — 801-line implementation plan with architecture decisions, detailed method lists, and testing strategy.
- `README.md` — Comprehensive user-facing documentation with API reference, examples, and architecture overview.
- `SentienceDatabase/` — PHP reference implementation (not part of the Python package).
- `docker-compose.yml` — provides MySQL and PostgreSQL services (used by `test_integration_postgres.py`).