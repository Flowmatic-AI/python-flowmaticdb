# flowmaticdb API cheat sheet

Enough to write application code and migrations. The package README is the full
reference.

## Connecting

```python
from flowmaticdb.database import DB

db = DB.connect_sqlite("app.db")
db = DB.connect_sqlite(":memory:")
db = DB.connect_sqlite("app.db", options={"read_only": True})
db = DB.connect_postgresql("mydb", host="localhost", port=5432, user="postgres", password="secret")
db = DB.connect_mysql("mydb", host="localhost", port=3306, user="root", password="secret")
db = DB.connect_mariadb("mydb", host="localhost", user="root", password="secret")
```

Shared keyword arguments on every `connect_*`:

| Argument | Purpose |
|---|---|
| `startup_queries` | SQL run on every new connection, including after a reconnect |
| `options` | Driver/dialect options (`sslmode`, `charset`, `read_only`, …) |
| `debug_callback` | `(sql, duration, error) -> None`, called per statement |
| `max_concurrent_connections` | Ceiling on live connections across all threads |
| `acquire_connection_timeout` | Seconds to wait for a slot before `ConnectionLimitError` |
| `ensure_always_connected` | Run `reconnect_if_disconnected()` before **every** statement — costs a liveness ping per query on PostgreSQL and MySQL |

`connect_postgresql` additionally takes `asyncpg_adapter`, **default `True`**.
Pass `asyncpg_adapter=False` for psycopg.

Extras: `flowmaticdb[postgres]` (psycopg), `flowmaticdb[asyncpg]`,
`flowmaticdb[mysql]`. SQLite needs none.

SQLite already opens with a **WAL journal, foreign keys ON and a 500 ms busy
timeout** — do not re-specify those. The options worth passing are `read_only`,
`encryption_key`, `encoding`, `check_same_thread`, `create_functions`, and a
`busy_timeout` above 500 when writers contend heavily.

## Lifecycle

```python
db.is_connected()
db.reconnect_if_disconnected()   # caller's thread only
db.reconnect()
db.close()                       # global: closes every thread's connection
db.adapter.connection_count()
```

A `DB` is shared between threads; each thread gets its own connection on first
query and keeps it for the thread's life. Transactions, savepoints and
`last_insert_id()` are therefore **per thread**. Results are cursor-backed and
belong to the thread that ran the query — pass rows, or `snapshot_result(result)`,
never the result itself.

## Queries

```python
db.select("users").columns(["id", "name"]).where_equals("active", True).order_by_asc("name").limit(10).execute()
db.select_table("users", "u").columns([["u", "id"]]).execute()
db.select("users").count()                       # int

db.insert("users").values({"name": "Alice"}).execute()
db.insert("users").values({"name": "Bob"}, {"name": "Eve"}).execute()
db.update("users").updates({"age": 26}).where_equals("name", "Bob").execute()
db.delete("users").where_less_than("age", 18).execute()
```

Conditions come in four variants — `where_*`, `or_where_*`, `where_not_*`,
`or_where_not_*` — and the same set exists as `having_*`:

`equals`, `less_than`, `less_than_or_equals`, `greater_than`,
`greater_than_or_equals`, `is_null`, `is_not_null`, `like`, `starts_with`,
`ends_with`, `contains`, `glob`, `in`, `between`, `empty`, `regex`, `exists`,
`group`, `raw`, `operator`.

```python
db.select("users").where_group(lambda group: group.where_equals("plan", "pro").or_where_equals("plan", "team")).execute()
db.select("users").where_raw("extract(year from created_at) = ?", [2026]).execute()
```

### Insert extras

```python
result = db.insert("users").values({"name": "Dave"}).returning(["id"]).last_insert_id("id").execute()
new_id = result.scalar()

db.insert("users").values({"name": "Alice"}).on_conflict_do_nothing(["name"]).execute()
db.insert("users").values({"name": "Alice", "age": 31}).on_conflict_do_update(["name"], {"age": 31}).execute()
```

The conflict target is **a list of columns**. A bare string is the *named
constraint* form (`ON CONFLICT ON CONSTRAINT ...`), which SQLite rejects with
`QueryError`. Always pass a list unless the code is PostgreSQL-only.

`RETURNING` is native on PostgreSQL, SQLite ≥ 3.35 and MariaDB ≥ 10.5, and
emulated on INSERT elsewhere by re-selecting on the primary key — which is why
emulated `returning()` requires `last_insert_id("id")` and raises `QueryError`
without it. On UPDATE and DELETE the clause is dropped, not emulated.

### Results

| Method | Returns |
|---|---|
| `fetch_dict()` | `dict \| None` |
| `fetch_dicts()` | `list[dict]` |
| `scalar(column=None)` | first value of the next row |
| `fetch_object(cls)` / `fetch_objects(cls)` | hydrated instances |
| `columns()` | `{name: type}` |

`from flowmaticdb.result import snapshot_result` freezes a live result so it can
be re-read.

## DDL

```python
db.create_table("users").if_not_exists() \
    .identity("id") \
    .string("email", size=255, not_null=True) \
    .text("bio") \
    .integer("age") \
    .float("score") \
    .boolean("active", not_null=True, default=True) \
    .datetime("last_seen") \
    .current_timestamp("created_at") \
    .json("preferences") \
    .unique_constraint(["email"], name="uq_users_email") \
    .foreign_key_constraint("role_id", "roles", "id", referential_actions=[ReferentialActionEnum.ON_DELETE_CASCADE]) \
    .execute()

db.alter_table("users").add_string("nickname", size=64).add_int("score", not_null=True, default=0).execute()
db.alter_table("users").rename_column("name", "full_name").drop_column("temp").execute()
db.alter_table("users").add_unique_constraint(["email"], name="uq_users_email").execute()
db.alter_table("users").drop_constraint("uq_users_email").execute()

db.drop_table("posts").if_exists().execute()
```

`identity(name, size=64, add_primary_key=True)` is the portable auto-increment
primary key; `serial()` and `auto_increment()` are aliases for the same builder.

Column types map per dialect:

| Builder | PostgreSQL | SQLite | MySQL |
|---|---|---|---|
| `identity()` | `GENERATED BY DEFAULT AS IDENTITY` (≥ 17) / `BIGSERIAL` | `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGINT AUTO_INCREMENT` |
| `boolean()` | `BOOLEAN` | `BOOLEAN` (0/1, read back as `bool`) | `TINYINT` (read back as `bool`) |
| `datetime()` | `TIMESTAMPTZ` | `DATETIME` | `DATETIME(6)` |
| `json()` | `JSONB` / `JSON` | `JSON` | `JSON` / `TEXT` |

## Raw SQL

```python
db.exec("CREATE INDEX IF NOT EXISTS idx_posts_user_id ON posts (user_id)")   # one statement, no params
db.prepared("SELECT * FROM users WHERE age > ? AND active = ?", [18, True])  # params
db.query_with_params(QueryWithParams(query="SELECT ...", params=[...]))
```

Write `?` placeholders; each adapter converts to its driver's format.

## Transactions

```python
def work(database):
    database.insert("users").values({"name": "Alice"}).execute()

db.transaction(work)        # commits, or rolls back on exception

db.begin_transaction()
db.begin_transaction("savepoint_1")
db.commit_transaction("savepoint_1")
db.rollback_transaction()
```

## Values

`datetime`, `dict`/`list` (JSON) and `bool` are serialized in and deserialized
out on every adapter. A bare `list` is a JSON document **everywhere**, PostgreSQL
included — wrap it in `PostgresArray([...])` to bind a real PostgreSQL array.

## Imports

```python
from flowmaticdb import DatabaseError, QueryError, AdapterError, DriverError, ConnectionLimitError
from flowmaticdb import raw, identifier, alias, expression, sub_query, current_timestamp, now, PostgresArray
from flowmaticdb import QueryWithParams
from flowmaticdb.database import DB, Table
from flowmaticdb.dialects import MySQLDialect, PostgresqlDialect, SQLiteDialect
from flowmaticdb.migrations import MigrationABC, Migrator
from flowmaticdb.result import snapshot_result
from flowmaticdb.query.enums import ReferentialActionEnum, TypeEnum
```

Never import from a `_`-prefixed module. A package's public API is exactly its
`__init__.py`.

## Gotchas that cost the most time

- **`"users.id"` is one identifier**, escaped as `"users.id"` and resolving to
  nothing. Qualified columns are lists: `["users", "id"]`. Same in `columns()`,
  `group_by()`, `returning()` and every condition.
- **Aggregates and functions need `raw()`** — `raw("count(*) AS cnt")`.
  `.count()` covers the common case.
- **`on_conflict_*` takes a list.** A string is the named-constraint form and
  raises `QueryError` on SQLite.
- **`db.exec()` takes one statement.** No script dumps.
- **`ALTER TABLE` emits one statement per alteration**, and
  `to_query_with_params()` on it returns a **list**.
- **SQLite raises `QueryError`** for `ALTER COLUMN` and named constraint
  alterations, and silently strips constraint names in `CREATE TABLE`.
- **Every MySQL `TINYINT` reads back as `bool`**, including columns this library
  did not create. `raw("CAST(col AS SIGNED)")` when the number is wanted.
- **A `max_concurrent_connections` slot is held by a thread, not a query** — it
  frees when the thread exits. Size it above the worker pool.
- **`:memory:` SQLite is shared across threads** and is wiped by `reconnect()`.
