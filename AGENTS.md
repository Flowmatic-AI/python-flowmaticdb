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
| `python3 -m pytest` | Run all tests (unit + SQLite integration; 524 passing without a server, 577 with MySQL and PostgreSQL up). Three long-standing failures: `test_sqlite_foreign_keys_pragma_left_alone_by_default`, `test_pg_identity_column_modern_version` and — only once PostgreSQL is reachable — `test_postgres_joins` |
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
- **`adapters/`** — Connection wrappers (`SQLiteAdapter`, `PsycopgAdapter`, `AsyncpgAdapter`, `MySQLAdapter`). Connection lifecycle is four methods: `_connect()` opens, `_disconnect()` unconditionally drops the driver handle, `close()` is the public teardown that honours the `persistent`/`optimize` options, and `is_connected()` reports liveness. All four are **per calling thread** except `close()`, which is global. `reconnect()` is concrete on `AdapterABC` (`_disconnect()`, errors suppressed, then `_connect()`); `AsyncpgAdapter` overrides it to restart its loop thread first, since its `close()` tears the loop down too.
- **`query/`** — Fluent query builders (`SelectQuery`, `InsertQuery`, `UpdateQuery`, `DeleteQuery`, `CreateTableQuery`, `AlterTableQuery`, `DropTableQuery`, `CreateIndexQuery`, `DropIndexQuery`). Mixins: `WhereMixin`, `HavingMixin`, `JoinsMixin`, etc.
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

- Always import from the package, never a `_`-prefixed module inside it: `from flowmaticdb.adapters import PsycopgAdapter`, not `from flowmaticdb.adapters._postgres import PsycopgAdapter`. Inside `src/flowmaticdb` three carve-outs are forced by the import graph — see **Leading underscore = private** under Key conventions before "fixing" a `_module` import there.
- **Never import an optional driver at module scope.** `adapters/__init__.py` imports every adapter module, so one module-scope `import psycopg`/`asyncpg`/`mysql.connector` makes the whole `flowmaticdb.adapters` package — and with it `connect_sqlite()`, which needs no extra at all — fail without that package installed. Every adapter puts its driver under `if TYPE_CHECKING:` (annotations are strings, so they never execute) and does the real import inside `_open_connection()`. Regression test: `test_sqlite_works_without_any_optional_driver_installed` in `tests/test_integration_sqlite.py` re-runs a SQLite CRUD in a subprocess with `-S`, so site-packages is off the path.
- **`drivers()` checks a dotted module's parent first.** `importlib.util.find_spec("mysql.connector")` imports `mysql` to look the submodule up and *raises* when that package is absent, instead of answering `None`.
- `PsycopgAdapter` is exported from `flowmaticdb.adapters` — `from flowmaticdb.adapters import PsycopgAdapter`.
- `PsycopgResult` is exported from `flowmaticdb.result` — `from flowmaticdb.result import PsycopgResult`.
- `raw()`, `identifier()`, `alias()`, `expression()`, `sub_query()`, `current_timestamp()`, `now()` — module-level functions exported from the top-level package: `from flowmaticdb import raw`.
- `PostgresArray` — value wrapper that opts a list into a PostgreSQL array instead of JSON. Lives in `flowmaticdb.query.expressions`, re-exported from the top level: `from flowmaticdb import PostgresArray`.
- Snapshot a result: `from flowmaticdb.result import snapshot_result`.
- Exception classes: `from flowmaticdb import QueryError` — they live in `_exceptions.py` and are re-exported from the top-level package. All are flat `Exception` subclasses except `ConnectionLimitError`, which subclasses `AdapterError` so callers already handling connection trouble catch it without knowing about the connection cap.

## Key conventions

- **Leading underscore = private** — a `_`-prefixed module name marks an implementation detail. A package's public API is exactly its `__init__.py` `__all__`; import from the package, never from a module inside it. This binds **consumers of a package**, which includes sibling packages inside `flowmaticdb` itself — `adapters/_mysql.py` reaches `AdapterError` as `from flowmaticdb import AdapterError`, not `from flowmaticdb._exceptions import …`. Three carve-outs, all forced by the import graph rather than by preference:
  - **A module cannot route through its own package's `__init__`.** `query/_select.py` importing `from flowmaticdb.query import Condition` is a cycle — `query/__init__.py` is what imports `_select` in the first place. Same-package siblings therefore stay on the `_module` path (~164 of these).
  - **`QueryWithParams` at runtime.** `flowmaticdb/__init__.py` reaches `flowmaticdb.query` through `_helpers` on line 2, well before it binds `QueryWithParams`, so a runtime `from flowmaticdb import QueryWithParams` inside `query/` raises `ImportError`. Reordering `__init__.py` to dodge that would make correctness depend on statement order, which ruff's isort rule (`I001`) actively re-sorts. Runtime uses import `flowmaticdb._query_with_params`; **`if TYPE_CHECKING:` uses go through the package**, since they never execute. The exceptions have no such problem — `_exceptions` is a dependency-free leaf bound on line 1.
  - **Genuinely private cross-package helpers.** `ThreadLocalStore`, `encode_json`/`decode_json` and `REGEX_PATTERN` are internal and deliberately absent from `__all__`; exporting them to satisfy the rule would widen the library's public API. These 12 imports keep the `_module` path.
- **ABCs over Protocols** — nominal subtyping (`abc.ABC`) used everywhere.
- **Mixins over traits** — multiple inheritance with `WhereMixin`, `HavingMixin`, etc.
- **Fluent API returns `Self`** — all query builder methods return `Self` for chaining.
- **`to_query_with_params()`** — central method that returns `QueryWithParams(query, params)`. Each query class implements this.
- **`execute(emulate_prepare=False)`** — runs via the bound database, returns `ResultABC`.
- **`emulate_prepare`** — parameter for `query_with_params()` and `execute()` (used for drivers without native prepared statements).
- **`from __future__ import annotations`** — used in every file.
- **`if TYPE_CHECKING`** — used for lazy imports in type stubs.

## Threading

A `DB`/adapter is shared between threads; a **connection is not**.

- `flowmaticdb/_threading.py` (private) holds `ThreadLocalStore[T]` — one value per thread, keyed by the `threading.Thread` object (not `ident`, which is recycled), with `current()`/`require()`/`set()`/`discard()`/`values()`/`take_all()`/`take_orphaned()`/`count()`/`reserve()`.
- **Values are released the moment their thread exits.** `set()` arms a `_ThreadExitHook` parked in a `threading.local`; CPython drops the last reference to it while tearing the thread's state down, so its `__del__` runs *in the dying thread*, while it can still do IO. The hook evicts the entry and hands the value to the store's `on_thread_exit` callback — which is how each adapter closes that thread's connection. Nothing polls, and no later caller has to come along and notice. The hook captures its `Thread` key up front: by the time `__del__` runs the thread is out of `threading._active`, so `current_thread()` would return a fresh dummy. `discard()` cancels the hook; a `shared_across_threads` store never arms one, since its single value outlives every individual thread.
- `take_orphaned()` is now only a backstop for what the hook cannot reach (a thread killed without teardown). `_close_orphaned_connections()` still runs on the new-thread path.
- This matters most under a **FastAPI sync (`def`) endpoint**, which runs on AnyIO's worker pool: those workers are retired once idle for 10s (`MAX_IDLE_TIME`), lazily, on the next `to_thread.run_sync`. Measured against live MySQL, a burst of 20 requests opens 21 connections and falls back to 2 as the pool retires — server-side `information_schema.processlist` drops in lockstep. Before the hook, all 21 stayed open until `wait_timeout` (8h) or process exit. `async def` endpoints run on the loop thread and hold a single connection for the process.
- `persistent` spares the handles `close()` would drop; it does **not** keep a finished thread's connection alive, which is unreachable by construction — no thread can ever bind to it again.
- Every adapter keeps `self._connections: ThreadLocalStore[<driver connection>]` and exposes `_connection` as a **property**: returns the calling thread's handle, else prunes finished threads' handles and calls `_connect()`. `_connect()` binds the handle to the store *before* running the startup queries, since those go back through `exec()`.
- `AdapterABC._closed` + `_ensure_not_closed()` stop a post-`close()` query from silently opening a fresh connection; `_connect()` clears the flag, so `reconnect()` revives a closed adapter. `close()` skips the flag on the `persistent` path (it deliberately leaves handles open).
- `AdapterABC.connection_count()` is concrete (`1 if is_connected() else 0`) and overridden per adapter with `self._connections.count()` — deliberately not abstract, so existing `AdapterABC` subclasses keep working.
- **`max_concurrent_connections` caps live connections; `acquire_connection_timeout` bounds the wait.** Both are optional on every `connect_*` method and on all four adapter constructors (`None` = uncapped, today's behaviour and zero overhead). They reach `ThreadLocalStore` as `max_values`/`acquire_timeout`, which is what actually enforces them — the store owns the whole key lifecycle, so permits and entries stay in lockstep. The invariant is **permits held == entries + reservations in flight**:
  - `reserve()` takes a permit *before* the driver connection is opened (counting after opening is exactly what the cap exists to prevent) and returns a context manager. `set()` transfers the permit to the entry; leaving the block without a `set()` — an open that raised — hands it straight back. `set()` onto an already-occupied key releases the incoming permit instead of transferring it, since that slot is already paid for.
  - Every removal path releases: `_release()` (the thread-exit hook), `discard()`, `take_all()`, `take_orphaned()`. A slot therefore frees when a thread **exits**, not when a query returns. `_release()` deliberately closes *before* releasing (in a `finally`) — freeing the slot first would let its taker open a new connection while this one is still closing, briefly putting the driver over the limit, and this is the path every slot normally comes back through. The three paths that hand the value to their caller cannot order that and release as they pop.
  - FIFO is `threading.Semaphore`'s doing — it parks waiters on a `Condition`, whose `notify()` wakes the longest-waiting one.
  - `_connect()` is the only caller. SQLite and MySQL grew a `_open_connection()` helper so the reserve block stays two lines instead of wrapping 50; psycopg/asyncpg wrap their one-line open directly.
  - No self-deadlock: a thread holding a connection returns from `current()` before reaching `reserve()`, and `reconnect()` releases via `_disconnect()` before re-acquiring. The trade-off is that an **idle** long-lived worker still holds its slot, so `max_concurrent_connections` must be ≥ the number of concurrently querying threads — it is a ceiling against runaway thread growth, not a way to serve N workers from fewer than N connections. `ConnectionLimitError` (subclasses `AdapterError`) is raised when `acquire_connection_timeout` elapses.
  - `max_concurrent_connections < 1` raises `AdapterError` from `AdapterABC.__init__`, and the store rejects `max_values < 1` the same way. The store keeps the generic names on purpose — it also backs the cursor and savepoint stores, which have no connection to cap.
  - Tests: `tests/test_connection_limit.py` (SQLite, no server, 14 tests), plus `test_postgres_psycopg_connection_limit` / `test_postgres_asyncpg_connection_limit` and `test_mysql_connection_limit` in the integration modules. Note the harness constraint documented on `_Waiter`: a `ThreadPoolExecutor` worker **keeps** the slot it is handed, and its shutdown joins workers still queued for a slot the test has not released — so anything expected to block uses raw threads that exit. Verified server-side as well: 12 threads through a 3-slot cap never put more than 3 rows in `pg_stat_activity`.
- `DatabaseABC._savepoints` is a property over a per-thread `ThreadLocalStore[list[str]]`; mutate it with `.clear()`, never reassign.
- `SQLiteAdapter` is the exception: `_is_memory_database()` (`:memory:`, `""`, or a `file:…mode=memory` URI) puts the store in `shared_across_threads` mode, since a second connection would be a second empty database. It then serializes statements through `self._statement_lock` (an `RLock`; a `nullcontext()` for file databases, which need no lock) and keeps `check_same_thread=False`. `sqlite3.connect()` is now called with `uri=True` for `file:`-prefixed names.
- `MySQLAdapter._cursors` is a second store — an unread cursor belongs to one connection, so `_drain_cursor()` is per thread too.
- `AsyncpgAdapter` shares its event loop across threads (it only runs I/O) but not its connections. `_fetch()`/`_fetch_with_params()` take the connection as a **parameter**: reading `self._connection` inside a coroutine would resolve it on the loop thread. `_ensure_loop()` (under `_loop_lock`) restarts the loop after `close()`.
- Results are cursor-backed and stay bound to the thread that ran the query.
- Tests: `tests/test_threading.py` and `tests/test_connection_limit.py` (SQLite, no server), plus `test_postgres_psycopg_threaded_access` / `test_postgres_asyncpg_threaded_access` and `test_mysql_threaded_access` in the integration modules.

## Dialect quirks

- `SQLDialect` properties like `bool`, `distinct_on`, `on_conflict`, `returning` are instance attributes (not abstract properties), set in `__init__`. `_build_returning()` / `_build_on_conflict()` drop their clause when the flag is off, so **the dialect never renders what it cannot run** — `InsertQuery` is what notices and emulates.
- **RETURNING and ON CONFLICT are emulated by default.** `InsertQuery._emulating_returning` / `._emulating_on_conflict` are true when the clause was asked for *and* (the dialect lacks it **or** `emulate_returning()`/`emulate_on_conflict()` forced it) — the `emulate_*()` methods are only the force switch, never the on switch. Emulated RETURNING re-selects by primary key, so `execute()` raises `QueryError` when `_last_insert_id_col` is unset rather than returning an empty result. `UpdateQuery`/`DeleteQuery` have no emulation: their `returning()` is silently dropped by a dialect without it.
- `escape_identifier()` recurses: an `Alias` renders as `<identifier> AS <alias>`, a `SqlABC` as its `raw_sql()`, a list as its segments joined by dots (nesting to any depth), anything else is escaped as one name. `_table_name()` is a thin alias for it. Column lists therefore take `["users", "email"]` directly — never `str()` an identifier before escaping it.
- `PostgresqlDialect.datetime_format = "%Y-%m-%d %H:%M:%S.%f"` (microseconds).
- `SQLiteDialect` raises `QueryError` for ALTER COLUMN, named constraint alterations, and named ON CONFLICT. **Not** for DROP COLUMN — there is no override, so it renders through the base and SQLite handles it (supported from 3.35.0; an older library errors from the driver).
- `TypeEnum.JSON` → `JSONB`/`JSON`/`TEXT` per server version, gated by the `json`/`jsonb` dialect flags set in `_version_gate()`.
- Version parsing: `"15.2"` → `150200` (major\*100^2 + minor\*100 + patch).
- **Index guards raise rather than silently drop.** `index_if_not_exists` / `index_if_exists` are two more `_version_gate()` flags (PostgreSQL 9.5 / 8.2, SQLite always, MariaDB 10.1.4, MySQL never). Unlike `_build_returning()` / `_build_on_conflict()`, `create_index()` / `drop_index()` raise `QueryError` when the flag is off — a dropped `IF NOT EXISTS` turns an idempotent DDL statement into one that fails on its second run, which is not an emulation the builder can paper over.
- **The index name is a bare name; `_index_name()` decides where the schema goes.** `CreateIndexQuery` / `DropIndexQuery` type `name` as `str` and derive the schema from the table, because the three engines disagree about which half may carry it and *all three reject the other half*:

  | | CREATE INDEX | DROP INDEX |
  |---|---|---|
  | PostgreSQL | bare index, qualified table | qualified index, no table |
  | SQLite | qualified index, **bare table** | qualified index, no table |
  | MySQL | bare index, qualified table | bare index, `ON <qualified table>` |

  So `SQLDialect.create_index()` renders the PostgreSQL/MySQL shape, `SQLiteDialect.create_index()` swaps the schema over to the index and strips the table, `SQLDialect.drop_index()` qualifies via `_index_name()`, and `MySQLDialect` overrides `_index_name()` to a no-op and appends `ON <table>`. Verified live against all three engines (attached SQLite database, non-`public` PostgreSQL schema, database-qualified MySQL table) — see `test_postgres_index_and_describe_in_another_schema`, `test_mysql_index_and_describe_with_a_qualified_table` and `test_create_and_drop_index_in_an_attached_schema`.

## Introspection

`DatabaseABC.list_tables(schema="public")` and `DatabaseABC.describe_table(table)`; `Table.describe()` is the facade shortcut. `TableDescription` / `TableConstraints` live in `flowmaticdb.query.ddl` beside the `Column`, `UniqueConstraint` and `ForeignKeyConstraint` dataclasses they hold.

- **`MySQLDialect` cannot use the base constraints query.** The ANSI one reaches the referenced column by joining `key_column_usage` back onto `referential_constraints.unique_constraint_name`, which assumes a constraint name identifies one constraint per schema. MySQL names *every* primary key `PRIMARY`, so that join multiplies a foreign key by the number of tables in the schema (caught live: `columns == ['role_id', 'role_id']`). The override reads `kcu.referenced_table_name` / `kcu.referenced_column_name` instead.
- **The dialect renders, `database/_introspection.py` parses.** Dialects never touch a connection, so `describe_table_columns()` / `describe_table_constraints()` return a `QueryWithParams` each, and every dialect aliases its result columns to the *same* names — `(column_name, column_type, not_null, default_expression, auto_increment)` and `(constraint_id, constraint_name, constraint_type, column_name, column_position, ref_table, ref_column, on_delete, on_update)`. That is what lets one `parse_columns()` / `parse_constraints()` pair read all three engines. Change an alias in one dialect and you have to change it in all of them.
- Grouping goes by `constraint_id`, not by name: SQLite reports no name at all for a foreign key, so two unnamed FKs would otherwise merge into one.
- Sources: PostgreSQL `pg_catalog` via `to_regclass(?)` (needs 9.6+, and `attidentity` only from 10 — gated), SQLite the `pragma_table_info` / `pragma_index_list` / `pragma_index_info` / `pragma_foreign_key_list` table-valued functions, MySQL and the base `SQLDialect` `information_schema`. `default_schema_sql` (a `ClassVar`) is what `_schema_filter()` falls back on for an unqualified table — `current_schema` on PostgreSQL, `DATABASE()` on MySQL, `None` (no filter) on the base.
- **No literal `%` in an introspection query.** psycopg and mysql.connector interpolate `%s`, so a stray `%` in a `LIKE` pattern breaks the statement. `POSITION(... IN ...)`, `LOCATE()` and `INSTR()` are used instead — see `describe_table_columns()` on each dialect.
- `list_tables(schema)` runs everywhere, but **only PostgreSQL honours `schema`**. SQLite has no schemas and MySQL calls its databases schemas, so `SQLiteDialect.list_tables()` / `MySQLDialect.list_tables()` take the argument and ignore it (`sqlite_master` minus the `sqlite_*` internals, and `TABLE_SCHEMA = DATABASE()`) — they render no placeholder at all, which is what the unit tests assert on. Do not "fix" that into a `QueryError`: silently ignoring an inapplicable schema is the documented contract.
- **`parse_type()` is the inverse of `type()` and must stay that way.** A described `Column` carries a `TypeEnum` and a `size`, not the engine's spelling, so `describe_table()` answers in the same terms `create_table()` was called in. Each `_parse_type_name()` branch returns *the width that renders that very name again* — `tests/test_type_parsing.py` asserts `dialect.type(*dialect.parse_type(s)) == s` across every `TypeEnum` × width each dialect can emit, so touching either half without the other fails there. A name a dialect cannot produce returns `None` from `_parse_type_name()` and reaches the caller as the raw string (`Column.type` is `TypeEnum | str`).
  - Ambiguities resolved by what the dialect *emits*, not by what the engine allows: MySQL `tinyint` → `BOOL` (this dialect renders a boolean that way and nothing else), base `SQLDialect` `INTEGER` → `INT` (it has no boolean type, so it renders both as `INTEGER` — the one case where the enum cannot round-trip, and the reason `test_parse_type_recovers_the_type_enum` skips `BOOL` when `not dialect.bool`).
  - `parse_column_type(sql_type, auto_increment)` is a **concrete** hook on `DialectABC` that defaults to `parse_type()`. Only `SQLiteDialect` overrides it: `_build_column()` renders every identity column as `INTEGER PRIMARY KEY AUTOINCREMENT` whatever the declared width, and that rowid alias is 64-bit, so a bare `INTEGER` reading of 32 would be wrong there. PostgreSQL keeps the width (`serial` vs `bigserial`) and MySQL keeps `BIGINT`, so neither needs it.
- **`parse_default()` is the inverse of `_build_column_default()`.** A described `Column` carries the Python value the column was declared with — `False`, `42`, `"anon"`, `{"a": 1}`, `CurrentTimestamp()` — not the engine's stored text. The quoting is what varies: `_parse_default_literal()` is the hook, and only two dialects override it. PostgreSQL strips the `::type` it appends to every literal; MySQL reports the *value* rather than the literal (`no way`, not `'no way'`), so it strips nothing and treats every string default as a value. Get that override wrong and MySQL string defaults keep phantom quotes. Anything that is not a literal of its type — `(1 + 1)`, `upper('x')` — falls through to the raw string, as does any default on a column whose type did not resolve to a `TypeEnum`.
- A described `Column` is still a report elsewhere: primary keys are not reported at all. The README's **Schema Introspection** section is the user-facing contract.

## Testing

- **Testing**: 524 tests pass without any database (unit + SQLite in-memory/file integration, including `test_threading.py`, `test_connection_limit.py` and `test_introspection.py`); 577 with both servers up — the 54 skips are exactly the PostgreSQL (36) and MySQL (18) suites.
- **Unit tests** (no database): `test_dialect_*.py`, `test_*_query.py`, `test_conditions.py`, `test_joins.py`, `test_expressions.py`, `test_query_with_params.py`, `test_result_abstract.py`, `test_json_and_datetime_types.py`, `test_boolean_types.py`, `test_index_queries.py`, `test_type_parsing.py`. `test_introspection.py` is a hybrid: the `describe_table()` half runs against in-memory SQLite, the PostgreSQL/MySQL half only asserts on rendered SQL.
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
- **Two PostgreSQL drivers** — `asyncpg_adapter` on `Database.connect_postgresql()` picks between them and **defaults to `True`**, so the stock connection is `AsyncpgAdapter` and needs the `asyncpg` extra; pass `asyncpg_adapter=False` for `PsycopgAdapter`. Both share `PostgresqlDialect`. asyncpg is coroutine-only, so `AsyncpgAdapter` owns a private event loop on a daemon thread and blocks on `run_coroutine_threadsafe` — that keeps the synchronous `AdapterABC` surface intact and also works when called from inside a running loop. It binds temporal values natively instead of using the dialect's strftime cast, and rejects the `client_encoding` option (asyncpg is UTF-8 only).
- **MySQL now uses `autocommit=True`** — `MySQLAdapter._connect()` passes `autocommit=True` to `mysql.connector.connect()`. Every statement commits immediately. No implicit transaction workarounds needed.
- **Datetime and JSON values are serialized/deserialized on every adapter** — see the "Datetime and JSON Values" section of `README.md` for the user-facing contract. Implementation notes:
  - `flowmaticdb/_json.py` (private) holds `encode_json()` / `decode_json()`; the dialects expose them as `cast_json()` / `parse_json()` (abstract on `DialectABC`, implemented on `SQLDialect`).
  - A bare `dict`/`list` is a JSON document on **every** dialect, PostgreSQL included. PostgreSQL arrays are opt-in via `PostgresArray` (`flowmaticdb.query.expressions`, re-exported from `flowmaticdb`) — a plain value wrapper, deliberately **not** a `SqlABC`, so `_build_question_marks()` binds it as a parameter instead of inlining SQL.
  - `PostgresqlDialect.cast_to_driver()` unwraps `PostgresArray` to a plain list (element types untouched, so the driver types them natively) and `cast_to_query()` renders it as `ARRAY[...]` (`'{}'` when empty) for `emulate_prepare`. `SQLDialect` unwraps it to JSON instead — engines with no array type drop the array reading rather than erroring, so a PostgreSQL-shaped query still runs on SQLite/MySQL.
  - `AsyncpgAdapter._open()` registers `json`/`jsonb` type codecs; `_cast_param()` leaves `dict`/`list`/`PostgresArray` native because whether a document has to be rendered depends on the placeholder type, which only `_adapt_param()` knows. There, a document is passed through for `_JSON_TYPE_OIDS` and `cast_json()`-rendered everywhere else — which is what makes a bare list bound to an array column fail loudly on asyncpg too, matching psycopg.
  - `MySQLResult` decodes columns the server reports as type code 245 (`json`); it tracks them by *position*, so duplicate column names in a join still decode correctly.
  - `SQLiteAdapter._connect()` opens connections with `check_same_thread` defaulting to `not shared_across_threads` — i.e. stock `sqlite3` behaviour (`True`) for file databases, since each thread now has its own handle, and `False` only for in-memory ones, where the handle is shared by design. The option still overrides both. `close()` closes every thread's handle from the caller's thread, which the check rejects: the `contextlib.suppress(sqlite3.Error)` there is load-bearing, and dropping the last reference (`take_all()`) closes those handles at deallocation instead.
  - `SQLiteAdapter._connect()` calls the module-local `_register_types()` (idempotent, so it runs per connect rather than at import) and opens connections with `detect_types=sqlite3.PARSE_DECLTYPES`. Registration mutates the process-wide `sqlite3` registry — that is deliberate and commented. Params of type `datetime`/`date`/`dict`/`list` bypass `cast_to_driver()` (see the module-local `_cast_param()`) so the registered adapters serialize them at full ISO-8601 fidelity; the dialect's `datetime_format` drops microseconds.
- **Fluent table reassignment** — use `.table("new_table")` instead of `.from_("new_table")` on `SelectQuery`, `DeleteQuery`, and `DropTableQuery`.
- **Qualified column references** — pass columns/conditions as two-element lists (e.g. `["users", "id"]`) or wrap in `identifier(["users","id"])`. This holds for `columns()`, `group_by()` and `returning()` as well as the `where_*`/`having_*` families. A dotted string like `"users.id"` is treated as a single identifier and escaped as `` `users.id` `` (non-existent column). Use `raw("...")` (a `SqlABC`) for raw JOIN clauses and aggregate expressions — `JoinsMixin.join()` ignores bare strings.
- **Schema-qualified INSERT/DELETE/UPDATE/CREATE** — pass `list[str]` directly (e.g. `db.insert(["schema", "table"])`). The dialect handles list splitting natively.

## Reference

- `PLAN.md` — 801-line implementation plan with architecture decisions, detailed method lists, and testing strategy.
- `README.md` — Comprehensive user-facing documentation with API reference, examples, and architecture overview.
- `SentienceDatabase/` — PHP reference implementation (not part of the Python package).
- `docker-compose.yml` — provides MySQL and PostgreSQL services (used by `test_integration_postgres.py`).
