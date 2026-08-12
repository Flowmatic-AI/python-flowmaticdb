# Translating raw driver code

Rewrite one module at a time and run the tests between modules. The mapping is
mechanical; the parts that are not mechanical are listed at the bottom.

## The shape that replaces everything

Every raw-driver call site follows `connect → cursor → execute → fetch → close`.
flowmaticdb collapses that to `db → builder → execute → fetch`. There is no
cursor to manage and no connection to open per call: the shared `DB` gives the
calling thread its own connection on first use and reuses it.

```python
result = db.select("users").where_equals("id", user_id).execute()
row = result.fetch_dict()          # dict | None
rows = result.fetch_dicts()        # list[dict]
value = result.scalar()            # first column of the next row
```

## psycopg 3 / psycopg2

```python
# Before
conn = psycopg.connect(dsn)
with conn.cursor(row_factory=dict_row) as cur:
    cur.execute("SELECT id, email FROM users WHERE active = %s ORDER BY email", (True,))
    rows = cur.fetchall()

# After
rows = (
    db.select("users")
    .columns(["id", "email"])
    .where_equals("active", True)
    .order_by_asc("email")
    .execute()
    .fetch_dicts()
)
```

| Before | After |
|---|---|
| `psycopg.connect(...)` / connection pool | `DB.connect_postgresql(name, host=..., user=..., password=..., asyncpg_adapter=False)` at startup |
| `cursor(row_factory=dict_row)`, `RealDictCursor` | nothing — `fetch_dicts()` always returns dicts |
| `cur.fetchone()` / `fetchall()` | `.fetch_dict()` / `.fetch_dicts()` |
| `cur.execute(sql, params)` with `%s` | builder methods, or `db.prepared(sql, params)` for SQL you keep |
| `cur.rowcount` | run a `.count()` query, or use `returning()` and count the rows |
| `INSERT ... RETURNING id` | `.returning(["id"]).last_insert_id("id")`, then `result.scalar()` |
| `ON CONFLICT ... DO UPDATE` | `.on_conflict_do_update(["email"], {"name": name})` — a list of columns; a bare string is the named-constraint form |
| `conn.commit()` / `rollback()` | `db.transaction(callback)`, or `begin_transaction()` / `commit_transaction()` |
| `with conn:` | `db.transaction(callback)` |
| `psycopg.errors.*` | `flowmaticdb.DatabaseError` and its subclasses — driver errors still surface underneath |

psycopg2's `execute_values` / `executemany` become one `values()` call with
several dicts:

```python
db.insert("users").values(
    {"name": "Alice", "age": 30},
    {"name": "Bob", "age": 25},
).execute()
```

## asyncpg

Same mapping as psycopg, plus the sync/async decision. `DB.connect_postgresql()`
uses the asyncpg driver by default (`asyncpg_adapter=True`) — but the API it
exposes is synchronous and blocking either way.

```python
# Before
row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
rows = await conn.fetch("SELECT * FROM users")
value = await conn.fetchval("SELECT count(*) FROM users")

# After — in a `def` endpoint, or via asyncio.to_thread from a coroutine
row = db.select("users").where_equals("id", user_id).execute().fetch_dict()
rows = db.select("users").execute().fetch_dicts()
value = db.select("users").count()
```

- `$1, $2` placeholders disappear; if you keep raw SQL, write `?` and let the
  adapter convert.
- `asyncpg.create_pool(min_size, max_size)` has no direct equivalent —
  connections are per thread. `max_concurrent_connections` is a ceiling, not a
  pool: a thread holds its slot until the thread exits, so it must be at least
  the number of threads that query concurrently.
- `async with conn.transaction():` → `db.transaction(callback)`.
- Record objects become plain dicts; `row["col"]` still works, `row.col` does not.

## sqlite3

```python
# Before
conn = sqlite3.connect("app.db")
conn.row_factory = sqlite3.Row
cur = conn.execute("SELECT * FROM users WHERE name LIKE ?", (f"{prefix}%",))
rows = [dict(r) for r in cur.fetchall()]

# After
db = DB.connect_sqlite("app.db")
rows = db.select("users").where_starts_with("name", prefix).execute().fetch_dicts()
```

- `row_factory = sqlite3.Row` and the `dict(r)` dance are gone.
- The `PRAGMA` lines most projects carry around go too: the adapter already
  opens every connection with a WAL journal, foreign keys ON and a 500 ms busy
  timeout. Raise `busy_timeout` above 500 only if writers actually contend —
  each thread is a separate SQLite writer.
- `:memory:` is shared across threads by design and is reset by `reconnect()`;
  use a file when threads need real isolation.
- Datetimes, JSON and booleans round-trip as real Python types when the column
  is declared `DATETIME` / `JSON` / `BOOLEAN`, which the builder does for you.

## mysql-connector-python / PyMySQL / MySQLdb / aiomysql

```python
# Before
cur = conn.cursor(dictionary=True)          # or DictCursor
cur.execute("SELECT id, name FROM users WHERE age > %s", (18,))
rows = cur.fetchall()

# After
rows = db.select("users").columns(["id", "name"]).where_greater_than("age", 18).execute().fetch_dicts()
```

- `DB.connect_mysql(...)`, or `DB.connect_mariadb(...)` — MariaDB has native
  `RETURNING` from 10.5, so the dialect needs to know which server it is.
- The adapter connects with `autocommit=True`; every statement commits
  immediately unless you open an explicit transaction.
- `INSERT ... ON DUPLICATE KEY UPDATE` → `.on_conflict_do_update(["col"], {...})`.
- `RETURNING` is emulated on MySQL for INSERT (insert, then re-select by primary
  key), so `.returning([...])` needs `.last_insert_id("id")` alongside it.
  On UPDATE and DELETE the clause is silently dropped — re-select explicitly.
- Every `TINYINT` column reads back as a `bool`, including foreign tables that
  store small integers there. Select such a column as
  `raw("CAST(col AS SIGNED)")` if you need the number.

## `databases` / `aiosqlite` used as a SQL executor

Treat the SQL string as the source and translate it directly with the builder.
`await database.fetch_all(query, values)` → `db.prepared(sql, params).fetch_dicts()`
as a first mechanical pass, then convert to builder calls module by module.

## What does not translate mechanically

- **Dotted column names.** `"users.id"` is escaped as a single identifier and
  will not resolve. Write `["users", "id"]` — in `columns()`, `group_by()`,
  `returning()` and every `where_*` / `having_*`.
- **SQL functions and aggregates.** `raw("count(*) AS cnt")`,
  `raw("coalesce(a, b)")` — the builder escapes identifiers, so anything that is
  an expression has to say so.
- **`rowcount`.** No equivalent. Count separately, or return the rows.
- **Server-side cursors and streaming.** Results are cursor-backed and belong to
  the thread that ran the query; `snapshot_result(result)` freezes one into
  memory when it has to be re-read or handed to another thread.
- **`LISTEN`/`NOTIFY`, `COPY`, advisory locks, prepared statement caches.** Not
  covered by the builder — keep the raw driver for those specific call sites, or
  issue them through `db.exec()` / `db.prepared()`.
- **Anything reading `cursor.description`.** Use `result.columns()`, which
  returns a `{name: type}` mapping.

## Verifying a rewritten module

1. Print the generated SQL without running it:
   `print(db.select("users").where_equals("id", 1).to_query_with_params().query)`
   — `ALTER TABLE` returns a *list* of `QueryWithParams`, one per alteration.
2. Attach `debug_callback=` at connect time to log every statement with its
   duration during the migration window.
3. Diff the row counts of the old and new code paths on a copy of the data
   before deleting the old driver.
