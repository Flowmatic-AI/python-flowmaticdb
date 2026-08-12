# Transparency
This package is a port of [PHP Sentience Database](https://github.com/Sentience-Framework/database)

It was ported using AI agents mostly powered by:
- Orchestrator: Deepseek V4 Flash (occational GLM 5.2 or Qwen 3.6 35B A3B)
- Sub agents: Qwen 3.6 35B A3B (occational Gemma 4 E2B)

The original PHP is made almost entirely by hand (except for the ExpressionF parsing). The workflow went as follows:
1. Copy sentience/database package to this directory
2. Let Deepseek V4 Flash explore the codebase and write a simple SQLite compatible port, with only CRUD queries, plan in PLAN.md
3. Let a new session with Deepseek V4 Flash as the orchestrator, and Qwen 3.6 35B A3B as subagent implement this first plan
4. Add DDL queries
5. Write Postgres implementation using the same setup
6. Write MySQL implementation using the same setup
7. Refine codebase

From a moral and environmental perspective, i've tried to use as much local AI as possible. The total token cost of this port is about $14 in Openrouter credits, most of which was used on GLM 5.2, even though Deepseek was the primary model used.

Coding agents work best if you give them a clear structure. In this case, having a human crafted package as an example, in a language with similar features, provied to be a great task for these models.

# flowmaticdb — Python Database Abstraction

A multi-dialect database abstraction layer for Python, supporting **PostgreSQL**, **SQLite**, **MySQL** and **MariaDB**. Ported from the PHP library `sentience/database`.

flowmaticdb gives you a fluent query builder API, driver-level adapters, dialect-aware SQL generation, a unified result abstraction and a schema migration runner — all with strict type hints and zero magic strings.

---

## Quick Start

```bash
pip install flowmaticdb                 # SQLite works out of the box
pip install "flowmaticdb[postgres]"     # PostgreSQL via psycopg
pip install "flowmaticdb[asyncpg]"      # PostgreSQL via asyncpg (the default driver)
pip install "flowmaticdb[mysql]"        # MySQL and MariaDB
pip install "flowmaticdb[all]"          # every driver
pip install "flowmaticdb[dev]"          # pytest, mypy, ruff
```

The package itself has **no dependencies** — a driver extra is only needed for a
server database, since `sqlite3` ships with Python.

```python
from flowmaticdb.database import DB

# Connect to any supported database
db = DB.connect_sqlite(":memory:")
# db = DB.connect_postgresql("mydb", host="localhost", user="postgres")
# db = DB.connect_mysql("mydb", host="localhost", user="root")

# Fluent query building
result = (
    db.select("users")
    .columns(["id", "name", "email"])
    .where_equals("active", True)
    .where_greater_than("age", 18)
    .order_by_asc("name")
    .limit(10)
    .execute()
)

# Fetch results
for row in result.fetch_dicts():
    print(row["name"], row["email"])

first = result.fetch_dict()  # Single row or None
count = result.scalar()      # First column of first row
```

---

## Supported Databases

| Database | Connection Method | Adapter | Dialect | Required Driver |
|----------|-------------------|---------|---------|----------------|
| SQLite   | `DB.connect_sqlite()` | `SQLiteAdapter` | `SQLiteDialect` | Built-in (`sqlite3`) |
| PostgreSQL | `DB.connect_postgresql()` | `AsyncpgAdapter` (default) or `PsycopgAdapter` | `PostgresqlDialect` | `asyncpg>=0.29` or `psycopg[binary]>=3.1` |
| MySQL   | `DB.connect_mysql()` | `MySQLAdapter` | `MySQLDialect` | `mysql-connector-python` |
| MariaDB | `DB.connect_mariadb()` | `MySQLAdapter` | `MySQLDialect` | `mysql-connector-python` |

`connect_mariadb()` is `connect_mysql()` with the dialect told it is talking to
MariaDB, which is what enables native `RETURNING` (≥ 10.5) and shifts the
`ON CONFLICT` and `JSON` version gates. Use it rather than `connect_mysql()`
against a MariaDB server.

---

## Connecting to a Database

### SQLite

```python
from flowmaticdb.database import DB

# In-memory
db = DB.connect_sqlite(":memory:")

# File-based
db = DB.connect_sqlite("/path/to/database.sqlite")

# With options
db = DB.connect_sqlite("mydb.db", options={
    "read_only": False,
    "journal_mode": "WAL",
    "foreign_keys": 1,
    "busy_timeout": 5000,
    "encoding": "UTF-8",
})
```

Every SQLite option and its default:

| Option | Default | Effect |
|--------|---------|--------|
| `journal_mode` | `WAL` | `PRAGMA journal_mode` |
| `busy_timeout` | `500` | `PRAGMA busy_timeout`, in milliseconds |
| `foreign_keys` | `True` | Runs `PRAGMA foreign_keys = ON` |
| `read_only` | `False` | Opens the file as a `mode=ro` URI |
| `check_same_thread` | `True` for a file, `False` for `:memory:` | Passed to `sqlite3.connect()` |
| `encoding` | unset | `PRAGMA encoding` |
| `encryption_key` | unset | `PRAGMA key`, for builds with encryption support |
| `create_functions` | `{}` | `{name: callable}` registered on every connection as variadic SQL functions. `REGEXP` and `regexp_like` are registered automatically unless a key of that name overrides them |

The first three are already what a threaded server wants, so passing them is
usually redundant — a bare `DB.connect_sqlite("mydb.db")` is opened with a WAL
journal, foreign keys ON and a 500 ms busy timeout. Raise `busy_timeout` above
the default when writers contend heavily.

Connections are opened with `sqlite3`'s same-thread check **enabled** — the
stock behaviour. Each thread gets its own connection, so nothing needs to cross
threads; handing a handle from `get_connection()` (or a `Result` reading from
one) to another thread raises `sqlite3.ProgrammingError` instead of corrupting
state silently. Pass `options={"check_same_thread": False}` to opt out.

A file-backed database gives every thread its own connection (see
[Threads and Concurrency](#threads-and-concurrency)), so concurrent writers are
separate SQLite writers competing for the same file. Use
`"journal_mode": "WAL"` plus a `"busy_timeout"` so they wait on each other
instead of failing with `database is locked`.

An **in-memory** database is the exception: it lives inside the connection that
opened it, so a second connection would be a second, empty database. Threads
therefore share the single handle (with the same-thread check off, since sharing
is the point), statements are serialized through a lock, and transaction state is
process-wide rather than per thread. Use a file (WAL is enough to keep it fast)
when threads need real isolation.

### PostgreSQL

```python
db = DB.connect_postgresql(
    "mydb",
    host="localhost",
    port=5432,
    user="postgres",
    password="secret",
    options={
        "sslmode": "require",
        "search_path": "public",
    },
)
```

Two drivers are supported and `asyncpg_adapter` picks between them. It
**defaults to `True`**, so the stock connection uses `AsyncpgAdapter` and needs
the `asyncpg` extra:

```python
db = DB.connect_postgresql("mydb", user="postgres")                        # asyncpg
db = DB.connect_postgresql("mydb", user="postgres", asyncpg_adapter=False)  # psycopg
```

Both share `PostgresqlDialect` and behave identically through the public API.
asyncpg is coroutine-only, so `AsyncpgAdapter` owns a private event loop on a
daemon thread and blocks on it — the `DB` surface stays synchronous either way.
It binds temporal values natively and rejects the `client_encoding` option,
since asyncpg is UTF-8 only.

### MySQL

```python
db = DB.connect_mysql(
    "mydb",
    host="localhost",
    port=3306,
    user="root",
    password="secret",
    options={
        "charset": "utf8mb4",
        "connect_timeout": 10,
    },
)

# Same signature; tells the dialect it is MariaDB
db = DB.connect_mariadb("mydb", host="localhost", user="root", password="secret")
```

### Arguments every `connect_*` accepts

| Argument | Purpose |
|----------|---------|
| `startup_queries` | SQL run on every new connection, including after a reconnect |
| `options` | Driver and dialect options (see each database above) |
| `debug_callback` | `(query, starttime, error)` called per statement — see [Debug Callback](#debug-callback) |
| `ensure_always_connected` | Run `reconnect_if_disconnected()` before **every** statement |
| `max_concurrent_connections` | Cap on live connections across all threads |
| `acquire_connection_timeout` | Seconds a thread waits for a slot before `ConnectionLimitError` |

`ensure_always_connected` trades a liveness check per statement for never
handing a dead connection to a query. On PostgreSQL and MySQL that check pings
the server, so it is not free — prefer calling `reconnect_if_disconnected()`
once at the top of a request when the cost matters.

### Reconnecting

A long-lived `DB` outlives its connection: servers close idle sessions, restart,
or drop the socket. Three methods cover that:

```python
db.is_connected()               # is the connection still usable?
db.reconnect_if_disconnected()  # reconnect only if it is not; returns whether it did
db.reconnect()                  # unconditionally drop and reopen
```

A reconnect opens a completely fresh connection: the `startup_queries` and
`options` given at connect time are reapplied, and any open transaction is gone
(the savepoint bookkeeping is reset to match). All three act on the **calling
thread's** connection only — other threads keep theirs and reconnect on their
own when they find their own connection broken.

```python
def handle_request(db):
    db.reconnect_if_disconnected()
    return db.select("users").execute().fetch_dicts()
```

`is_connected()` pings the server on PostgreSQL (psycopg) and MySQL, so an idle
connection whose backend died is detected before the next query rather than
after it fails. Two caveats:

- Reconnecting a SQLite `:memory:` database opens an **empty** one — the old
  database only ever existed inside the dropped handle.
- Inside an open transaction the PostgreSQL check falls back to the local
  connection status (no ping), so a transaction is never disturbed by it.

### Threads and Concurrency

A `DB` is safe to share between threads. Build one at startup and use it from
every worker — a threaded server (FastAPI's `def` endpoints on its worker thread
pool, Gunicorn/Uvicorn threads, a `ThreadPoolExecutor`) needs nothing else:

```python
db = DB.connect_postgresql("mydb", user="postgres")   # module level

@app.get("/users")
def list_users():                     # runs on a worker thread
    return db.select("users").execute().fetch_dicts()

@app.on_event("shutdown")
def shutdown():
    db.close()
```

Each thread gets its **own driver connection**, opened the first time that
thread runs a query and reused for the rest of its life. That is what makes
sharing safe: threads never interleave statements, cursors, or transaction state
on one handle, so a `begin_transaction()` on one worker cannot swallow another
worker's write.

```python
db.adapter.connection_count()   # live connections, across all threads
```

What follows from the model:

- **Transactions, savepoints and `last_insert_id()` are per thread.** A
  transaction belongs to the thread that opened it; other threads are unaffected
  and see nothing of it until it commits.
- **Connection count tracks thread count.** N worker threads means up to N server
  connections, so keep the server's own `max_connections` above your thread-pool
  size, or cap this side with `max_concurrent_connections=` (see
  [Limiting concurrent connections](#limiting-concurrent-connections)).
  Connections belonging to finished threads are closed automatically when a
  new thread opens one.
- **`close()` is global, everything else is local.** `close()` is the shutdown
  hook and closes every thread's connection; `reconnect()`, `is_connected()` and
  `_disconnect()` act on the caller's connection alone. A query after `close()`
  raises `AdapterError` rather than quietly opening a new connection —
  `reconnect()` revives the adapter if you really want it back.
- **Results belong to their thread.** A `ResultABC` reads from a live cursor on
  the connection that ran the query. Consume it on the thread that created it and
  pass rows (or `snapshot_result(result)`) to other threads, not the result
  itself. On SQLite that rule is enforced: `sqlite3`'s same-thread check is on by
  default again, so a stray cross-thread fetch raises instead of misbehaving.
- **The query builders are per call and the dialect is immutable**, so neither
  needs any care.

Two engine-specific notes: SQLite `:memory:` cannot give threads separate
connections and shares one instead (see [SQLite](#sqlite) above), and the
`AsyncpgAdapter`'s private event loop is shared by all threads while its
connections are not — asyncpg cannot run two queries on one connection at once.

### Limiting Concurrent Connections

By default a thread that needs a connection opens one, however many are already
live. Every `connect_*` method takes `max_concurrent_connections` to cap that, and
`acquire_connection_timeout` to bound how long a thread waits for its turn:

```python
db = DB.connect_postgresql(
    "mydb",
    user="postgres",
    max_concurrent_connections=10,   # at most 10 live connections, across all threads
    acquire_connection_timeout=5.0,  # give up after 5s of waiting
)
```

A thread that needs a **new** connection while the cap is reached blocks until a
slot frees, and slots are handed out in arrival order — first to wait is first
served. A thread that already has a connection never waits; it just reuses its
own, so a capped adapter cannot deadlock against itself.

```python
db.adapter.max_concurrent_connections  # 10
db.adapter.connection_count()          # live connections right now, never above the cap
```

With no `acquire_connection_timeout` a thread waits indefinitely. Set one and a thread
that waits too long raises `ConnectionLimitError` (a subclass of `AdapterError`,
so existing handlers keep working) instead of hanging:

```python
from flowmaticdb import ConnectionLimitError

try:
    rows = db.select("users").execute().fetch_dicts()
except ConnectionLimitError:
    ...   # shed the request rather than pile up behind the cap
```

**A slot is held for the lifetime of the thread, not the query.** Connections are
per thread (above), so a slot only comes free when its thread exits, is swept as
finished, or `close()` runs — not when a query returns. Under a long-lived worker
pool an idle worker still holds its slot, so `max_concurrent_connections` must be at least
the number of workers that run queries concurrently or requests will queue behind
threads that are doing nothing. Size it as a **safety ceiling against runaway
thread growth**, not as a way to serve N workers from fewer than N connections:

```python
# FastAPI def endpoints run on AnyIO's worker pool (41 threads by default)
db = DB.connect_postgresql("mydb", user="postgres", max_concurrent_connections=45)
```

### Debug Callback

All connection methods accept a `debug_callback` for query logging:

```python
def debug(sql: str, duration: float, error: str | None):
    print(f"[{duration:.4f}s] {sql}")
    if error:
        print(f"  ERROR: {error}")

db = DB.connect_sqlite(":memory:", debug_callback=debug)
```

---

## Query Building

All query builders return `Self` for seamless method chaining.

### SELECT

```python
# Basic select
db.select("users").execute()

# With columns
db.select("users").columns(["id", "name"]).execute()

# Alias the table
db.select_table("users", "u").columns(["u.id", "u.name"]).execute()

# Sub-query as source
sub = db.select("active_users").columns(["id"])
db.select_sub_query(sub, "a").execute()

# Change table (fluent)
q = db.select("users")
q.table("admins").execute()

# Count
count: int = db.select("users").where_equals("active", True).count()
```

### INSERT

```python
# Single row
db.insert("users").values({"name": "Alice", "age": 30}).execute()

# Multiple rows
db.insert("users").values(
    {"name": "Bob", "age": 25},
    {"name": "Charlie", "age": 35},
).execute()

# With RETURNING — native on PostgreSQL and SQLite >= 3.35, emulated elsewhere
result = db.insert("users").values({"name": "Dave"}).returning(["id"]).last_insert_id("id").execute()
new_id = result.scalar()

# ON CONFLICT — native on PostgreSQL, SQLite >= 3.24 and MySQL, emulated elsewhere
db.insert("users").values({"name": "Alice"}).on_conflict_do_nothing(["name"]).execute()
db.insert("users").values({"name": "Alice", "age": 31}).on_conflict_do_update(
    ["name"], {"age": 31}
).execute()

# Get last insert ID
db.insert("users").values({"name": "Eve"}).last_insert_id("id").execute()
last_id = db.last_insert_id()
```

#### Emulated RETURNING and ON CONFLICT

Both clauses work on every dialect. When the dialect cannot express one, the
insert falls back to the equivalent sequence of statements by itself — writing a
per-driver fallback is never necessary:

| | Native | Emulated as |
|---|---|---|
| `RETURNING` | PostgreSQL, SQLite ≥ 3.35, MariaDB ≥ 10.5 | INSERT, then SELECT the row by its primary key |
| `ON CONFLICT` | PostgreSQL, SQLite ≥ 3.24, MySQL, MariaDB | SELECT on the conflict columns, then INSERT or UPDATE |

Emulated RETURNING reads the inserted row back by primary key, so it needs to
know that column. Supply it with `last_insert_id("id")` (or `emulate_returning("id")`);
without it the insert raises `QueryError` rather than handing back an empty result:

```python
db.insert("users").values({"name": "Dave"}).returning(["id"]).last_insert_id("id").execute()
```

`emulate_returning("id")` and `emulate_on_conflict("id")` are only needed to opt
*into* the emulation on a dialect that has the clause natively — for instance to
get identical statement sequences across environments. `emulate_on_conflict()`
also takes `in_transaction=True` to wrap its select-then-write in a transaction.

`returning()` on UPDATE and DELETE is not emulated: on a dialect without native
RETURNING the clause is dropped and the result holds no rows.

#### Conflict targets

The first argument to `on_conflict_do_nothing()` / `on_conflict_do_update()` is
read two different ways, and the difference is not portable:

| Argument | Meaning | Renders as |
|---|---|---|
| `list[str]` — `["email"]` | the conflicting **columns** | `ON CONFLICT ("email")` |
| `str` — `"uq_users_email"` | a **named constraint** | `ON CONFLICT ON CONSTRAINT "uq_users_email"` |

Per dialect:

- **PostgreSQL** renders both.
- **SQLite** renders the column list, and raises on the string form rather than
  guessing which constraint was meant.
- **MySQL and MariaDB** ignore the target entirely — the insert becomes
  `INSERT IGNORE` or `ON DUPLICATE KEY UPDATE`, neither of which names one — so
  either form is accepted and neither has any effect on which conflict matches.

```python
db.insert("users").values({"name": "Alice"}).on_conflict_do_nothing("name").execute()
# QueryError: Named ON CONFLICT constraints are not supported by SQLite
```

Pass a list unless the code is deliberately PostgreSQL-only.

### UPDATE

```python
db.update("users").updates({"age": 26}).where_equals("name", "Bob").execute()

# With RETURNING
result = (
    db.update("users")
    .updates({"age": 27})
    .where_equals("name", "Bob")
    .returning(["id", "age"])
    .execute()
)
updated = result.fetch_dict()
```

### DELETE

```python
db.delete("users").where_equals("name", "Alice").execute()

# Change table
q = db.delete("users")
q.table("old_users").execute()

# With RETURNING
result = db.delete("users").where_less_than("age", 18).returning(["id"]).execute()
```

### CREATE TABLE

```python
# Using convenience methods
db.create_table("users").if_not_exists() \
    .identity("id") \
    .string("name", not_null=True) \
    .integer("age") \
    .boolean("active", default=True) \
    .datetime("created_at") \
    .json("preferences") \
    .execute()

# Using raw column definitions
db.create_table("posts").if_not_exists() \
    .column("id", TypeEnum.INT, not_null=True) \
    .column("title", TypeEnum.STRING, not_null=True) \
    .column("body", "TEXT") \
    .primary_keys("id") \
    .execute()

# With constraints
db.create_table("orders").if_not_exists() \
    .identity("id") \
    .integer("user_id") \
    .string("status") \
    .unique_constraint(["status", "user_id"], name="uq_orders_status_user") \
    .foreign_key_constraint(
        "user_id", "users", "id",
        referential_actions=["ON DELETE CASCADE"],
    ) \
    .execute()
```

### ALTER TABLE

```python
# Add columns
db.alter_table("users") \
    .add_string("email", size=255) \
    .add_int("score", not_null=True, default=0) \
    .execute()

# Rename / drop columns
db.alter_table("users") \
    .rename_column("name", "full_name") \
    .drop_column("temp_field") \
    .execute()

# Add constraints
db.alter_table("users") \
    .add_unique_constraint(["email"], name="uq_users_email") \
    .add_foreign_key_constraint("role_id", "roles", "id") \
    .execute()

# Drop constraints
db.alter_table("users") \
    .drop_constraint("uq_users_email") \
    .execute()

# Raw alter
db.alter_table("users").alter("ALTER COLUMN age SET NOT NULL").execute()
```

An `AlterTableQuery` emits **one statement per alteration**, not one combined
statement, so `to_query_with_params()` returns a `list[QueryWithParams]` where
every other builder returns a single one:

```python
query = db.alter_table("users").add_string("nickname", size=64).add_int("score", default=0)
for qwp in query.to_query_with_params():
    print(qwp.query)
# ALTER TABLE "users" ADD COLUMN "nickname" VARCHAR(64)
# ALTER TABLE "users" ADD COLUMN "score" BIGINT DEFAULT 0
```

On MySQL each of those statements also commits implicitly, so a multi-step
`alter_table()` cannot be rolled back halfway.

### Indexes

There is no index builder — indexes go through `exec()`:

```python
db.exec('CREATE INDEX IF NOT EXISTS "idx_posts_user_id" ON "posts" ("user_id")')
```

`IF NOT EXISTS` on an index is supported by PostgreSQL, SQLite and MariaDB but
**not by MySQL**, which needs a catalog check instead:

```python
exists = db.prepared(
    "SELECT count(*) FROM information_schema.statistics "
    "WHERE table_schema = database() AND table_name = ? AND index_name = ?",
    ["posts", "idx_posts_user_id"],
).scalar()
```

Use `dialect.escape_identifier()` to quote names rather than hardcoding quotes,
since PostgreSQL and SQLite use `"` while MySQL uses `` ` ``.

### DROP TABLE

```python
db.drop_table("posts").execute()
db.drop_table("posts").if_exists().execute()
```

---

## WHERE Conditions

Every condition method has four variants:

| Variant | Example |
|---------|---------|
| `where_*` | `where_equals("name", "Alice")` |
| `or_where_*` | `or_where_equals("name", "Bob")` |
| `where_not_*` | `where_not_equals("status", "banned")` |
| `or_where_not_*` | `or_where_not_equals("role", "admin")` |

### Available Conditions

```python
# Comparison
.where_equals("name", "Alice")
.where_not_equals("status", "banned")
.where_less_than("age", 18)
.where_less_than_or_equals("age", 65)
.where_greater_than("score", 100)
.where_greater_than_or_equals("score", 0)

# Null checks
.where_is_null("deleted_at")
.where_is_not_null("email")

# Pattern matching
.where_like("name", "Alice%")        # SQL LIKE
.where_not_like("email", "%@spam.com")
.where_starts_with("username", "admin")  # LIKE 'admin%'
.where_ends_with("filename", ".pdf")     # LIKE '%.pdf'
.where_contains("bio", "engineer")       # LIKE '%engineer%'
.where_not_contains("bio", "spam")       # NOT LIKE '%spam%'

# File globbing (SQLite)
.where_glob("path", "*.txt")
.where_not_glob("path", "*.tmp")

# Set membership
.where_in("id", [1, 2, 3])
.where_not_in("role", ["guest", "anon"])

# Range
.where_between("age", 18, 65)
.where_not_between("age", 0, 17)

# Empty string
.where_empty("middle_name")
.where_not_empty("full_name")

# Regex
.where_regex("email", r"^[a-z]+@")
.where_not_regex("email", r"^test@")

# Subquery existence
sub = db.select("orders").columns(["user_id"])
.where_exists(sub)
.where_not_exists(sub)

# Grouped conditions
.where_group(lambda g: (
    g.where_equals("plan", "premium")
     .or_where_group(lambda g2: (
         g2.where_equals("plan", "free")
            .where_less_than("trial_days", 30)
     ))
))
.where_not_group(lambda g: g.where_equals("role", "internal"))

# Raw SQL conditions
.where_raw("EXTRACT(YEAR FROM created_at) = ?", [2026])
.or_where_raw("last_login IS NOT NULL")

# Custom operator
.where_operator("json_data", "@>", '{"vip": true}')
```

---

## HAVING Conditions

Exactly the same methods as WHERE, prefixed with `having_*` / `or_having_*`:

```python
db.select("users") \
    .columns(["plan", "count(*)"]) \
    .group_by(["plan"]) \
    .having_greater_than("count(*)", 5) \
    .having_between("avg(age)", 18, 65) \
    .having_group(lambda g: g.where_equals("plan", "enterprise")) \
    .execute()
```

---

## JOINs

```python
from flowmaticdb import raw, identifier

query = db.select("users").columns(["users.id", "posts.title"])

# INNER JOIN with ON conditions — the callback receives the Join,
# every join method returns the query so you can keep chaining
query.inner_join_table(
    "posts",
    lambda join: join
        .on(["users", "id"], ["p", "user_id"])       # ON users.id = p.user_id
        .or_on(["p", "status"], ["'published'"]),    # OR p.status = 'published'
    "p",
)

# LEFT JOIN
query.left_join_table("comments", lambda join: join.on(["p", "id"], ["c", "post_id"]), "c")

# CROSS JOIN (never takes ON conditions)
query.cross_join("sessions")

# LATERAL joins
query.left_join_lateral_sub_query(sub_query, "sq")
query.inner_join_lateral_sub_query(sub_query, "sq")
query.cross_join_lateral_sub_query(sub_query, "sq")

# Raw join SQL (e.g. for aggregates)
query.join(raw("LEFT JOIN (SELECT user_id, count(*) AS cnt FROM orders GROUP BY user_id) AS o ON o.user_id = users.id"))
```

### Join ON Conditions

`Join` objects support all the same condition methods as WHERE:

```python
query.inner_join(
    "orders",
    lambda join: join
        .where_equals(["orders", "user_id"], ["users", "id"])
        .where_greater_than("orders.total", 100),
)
```

---

## DISTINCT, GROUP BY, ORDER BY, LIMIT, OFFSET

```python
db.select("users") \
    .distinct()                   # DISTINCT
    .distinct(["category"])       # DISTINCT ON (PostgreSQL only)
    .group_by(["plan", "status"]) \
    .order_by_asc("name") \
    .order_by_desc("created_at")  # Multiple orderings
    .limit(50) \
    .offset(10) \
    .execute()
```

---

## UNION / UNION ALL

```python
active  = db.select("users").where_equals("active", True)
archived = db.select("archived_users")

db.select("users") \
    .columns(["id", "name"]) \
    .union(active) \
    .union_all(archived) \
    .execute()
```

---

## Transactions

```python
# Explicit transaction
db.begin_transaction()
try:
    db.insert("users").values({"name": "Alice"}).execute()
    db.insert("users").values({"name": "Bob"}).execute()
    db.commit_transaction()
except Exception:
    db.rollback_transaction()

# With context-manager-style callback
def work(database):
    database.insert("users").values({"name": "Charlie"}).execute()
    database.insert("users").values({"name": "Dave"}).execute()

db.transaction(work)  # Auto commit/rollback

# Savepoints for nested transactions
db.begin_transaction()
db.begin_transaction("savepoint_1")
db.commit_transaction("savepoint_1")
db.rollback_transaction()  # Rolls back main transaction
```

---

## Working with Results

All `execute()` calls return a `ResultABC` object.

### Fetching Data

```python
result = db.select("users").execute()

# Single row
row: dict | None = result.fetch_dict()

# All rows
rows: list[dict] = result.fetch_dicts()

# First column of first row
val: Any = result.scalar()
val = result.scalar("name")  # Named column

# Column metadata
cols: dict[str, str] = result.columns()  # {"id": "integer", "name": "text", ...}

# Hydrate into objects
class User:
    def __init__(self):
        self.id = 0
        self.name = ""

user = result.fetch_object(User)       # Single
users = result.fetch_objects(User)     # List
```

### Snapshotting a Result

Freeze a live cursor result into an in-memory `Result`:

```python
from flowmaticdb.result import snapshot_result

live_result = db.select("users").execute()
snapshot = snapshot_result(live_result)  # Can be iterated repeatedly
```

### Result Methods Summary

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_dict()` | `dict \| None` | Next row as dict, or `None` |
| `fetch_dicts()` | `list[dict]` | All remaining rows |
| `scalar(column=None)` | `Any` | First value of next row |
| `fetch_object(cls, args)` | `object \| None` | Hydrate next row into object |
| `fetch_objects(cls, args)` | `list[object]` | Hydrate all rows into objects |
| `columns()` | `dict[str, str]` | Column name → type mapping |

---

## Table API

High-level table wrapper for common patterns:

```python
from flowmaticdb.database import Table

# Create a table reference
table = Table(db, db.dialect, "users")

# Shortcuts
table.select()                              # SELECT *
table.select(["id", "name"])                # SELECT id, name
table.insert({"name": "Alice"})            # INSERT
table.update({"age": 30})                  # UPDATE ... (add WHERE separately)
table.delete()                              # DELETE ... (add WHERE separately)

# Smart operations
table.select_or_insert(["name"], ["Alice"])  # SELECT first, INSERT if not found
table.insert_or_ignore(["name"], ["Bob"])   # INSERT ... ON CONFLICT DO NOTHING
table.insert_or_update(
    ["name"], ["Charlie"],
    conflict="name",
    updates={"age": 40},
)                                         # INSERT ... ON CONFLICT DO UPDATE

# DDL
table.create(lambda q: q.identity("id").string("name"))
table.create_if_not_exists(...)
table.drop()
table.drop_if_exists()
table.truncate()

# Introspection
table.columns()     # list[str] — column names
table.is_empty()    # bool
```

`db.table("users")` is the same thing without repeating the dialect:

```python
table = db.table("users")
```

---

## Migrations

Schema changes as ordered, reversible Python files. One migration is one file
holding exactly one `MigrationABC` subclass:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from flowmaticdb.migrations import MigrationABC

if TYPE_CHECKING:
    from flowmaticdb.database import DB


class CreateUsersTable(MigrationABC):
    def up(self, db: DB) -> None:
        db.create_table("users").if_not_exists() \
            .identity("id") \
            .string("email", size=255, not_null=True) \
            .execute()

    def down(self, db: DB) -> None:
        db.drop_table("users").if_exists().execute()
```

`up()` and `down()` are abstract and receive the `DB` as an argument rather than
holding one. `in_transaction()` is concrete and returns `True`; override it to
return `False` for a migration that must not run inside a transaction.

### Migrator

```python
from flowmaticdb.migrations import Migrator

migrator = Migrator(db, "app/migrations")          # migrations_table="migrations"

migrator.init()                                     # create the bookkeeping table
migrator.up()                                       # apply everything pending, as one batch
migrator.down()                                     # roll back the most recent batch
path = migrator.create("add_email_to_users")        # write a new migration file
```

| Method | Effect |
|--------|--------|
| `init()` | Creates the migrations table (`if_not_exists`, so it is safe to call every run) |
| `up()` | Applies every file not yet recorded, in filename order, under one new batch number |
| `down()` | Reverses the highest batch, in reverse filename order |
| `create(name)` | Writes `<YYYYMMDDHHMMSS>_<name>.py` from the template and returns its path |

The bookkeeping table records `filename`, `batch` and `applied_at` per applied
migration.

### Rules

- **`init()` must run before `up()` or `down()`.** Both read the bookkeeping
  table directly and fail if it does not exist yet.
- **`create(name)` uses `name` verbatim in the filename**, spaces included. Pass
  `snake_case`.
- **Ordering is a plain sort of filenames**, which is what the timestamp prefix
  is for. Do not rename a file once it has been applied — the table keys on it.
- **Exactly one `MigrationABC` subclass per file.** Zero raises `DatabaseError`,
  and so does more than one. Classes imported from elsewhere do not count, so
  shared helpers are fine.
- **Files beginning with `_` are skipped**, which is where helper modules go.
  They are not importable as a package, though — the loader reads each migration
  by path, so add the directory to `sys.path` before importing a sibling helper.
- **Each migration runs inside a transaction** unless `in_transaction()` returns
  `False`. On MySQL that guarantee is limited: DDL commits implicitly, so a file
  with several DDL statements cannot be rolled back halfway. Keep one logical
  change per file.
- **`down()` reverses a whole batch**, not one file — everything a single `up()`
  applied comes back off together.

### Adopting migrations for a database that already exists

Write the current schema as an initial migration with `if_not_exists()` on every
create and `if_exists()` on every drop. Applied to a database that already has
the schema it creates nothing, records one row, and leaves the data untouched;
applied to an empty one it builds everything. The same file therefore works for
both existing deployments and fresh checkouts.

Drop tables in reverse dependency order in `down()`, or foreign keys will block
the drop.

### A CLI

There is no console entry point; wire one up in the project:

```python
import sys

from flowmaticdb.migrations import Migrator

from app.db import connect

db = connect()
migrator = Migrator(db, "app/migrations")

command = sys.argv[1]

if command == "create":
    print(migrator.create(sys.argv[2]))
else:
    migrator.init()
    if command == "up":
        migrator.up()
    elif command == "down":
        migrator.down()

db.close()
```

Run `up` on deploy, before the application starts serving — not from a request
handler, and not from every worker at once.

---

## Expressions

Import module-level factory functions:

```python
from flowmaticdb import raw, identifier, alias, expression, sub_query, current_timestamp, now
```

### Available Expressions

| Expression | Purpose | Example |
|-----------|---------|---------|
| `raw(sql)` | Raw SQL snippet | `raw("COUNT(*) AS cnt")` |
| `identifier(name)` | Escaped identifier | `identifier(["schema", "table"])` |
| `alias(expr, alias)` | `expr AS alias` | `alias("users", "u")` |
| `expression(sql, params)` | SQL with positional params | `expression("? + ?", [1, 2])` |
| `sub_query(query, alias)` | `(SELECT ...) AS alias` | `sub_query(select_q, "sq")` |
| `current_timestamp()` | `CURRENT_TIMESTAMP` | `current_timestamp()` |
| `now()` | `datetime.now(UTC)` | `now()` |
| `PostgresArray(values)` | Bind a list as a PostgreSQL array instead of JSON | `PostgresArray([1, 2, 3])` |

```python
db.select(raw("COUNT(*) AS cnt")).table("users").execute()

# Schema-qualified table reference
db.select(identifier(["public", "users"])).execute()

# Alias in joins
join = query.inner_join(alias("users", "u"))
join.on(identifier(["u", "id"]), identifier(["posts", "user_id"]))
```

---

## EXPLAIN Queries

```python
plan = db.select("users").where_equals("name", "Alice").explain()
for row in plan:
    print(row)
```

---

## Raw Query Execution

For one-off SQL that doesn't need the query builder:

```python
# DDL (no parameters) — one statement per call, never a script
db.exec("CREATE TABLE temp (id INTEGER PRIMARY KEY)")

# DML with parameters
from flowmaticdb import QueryWithParams
qwp = QueryWithParams(query="SELECT * FROM users WHERE name = ?", params=["Alice"])
result = db.query_with_params(qwp)
rows = result.fetch_dicts()

# Prepared statement shortcut
result = db.prepared("SELECT * FROM users WHERE age > ? AND active = ?", [18, True])
```

`exec()` hands the string straight to the driver, which accepts **one statement
per call**. A whole `.sql` file cannot be passed through it — split it, or
rebuild it with the query builder:

```python
db.exec("CREATE TABLE a (id INTEGER); CREATE TABLE b (id INTEGER);")
# sqlite3.ProgrammingError: You can only execute one statement at a time.
```

---

## QueryWithParams

The core data structure that travels from query builders through dialects to adapters:

```python
from flowmaticdb import QueryWithParams

qwp = QueryWithParams(query="SELECT * FROM users WHERE age > ?", params=[18])

# Convert %s placeholders to ? positional
qwp2 = qwp.percent_s_to_question_marks()

# Interpolate values into SQL string (for debugging / emulation)
sql = qwp.to_sql(dialect)
# Returns: SELECT * FROM users WHERE age > 18
```

---

## Exception Hierarchy

```
DatabaseError
├── AdapterError        — Adapter-level issues (connection, configuration)
├── DriverError         — Driver/connection errors
├── QueryError          — Query building errors (e.g., unsupported SQL feature)
└── QueryWithParamsError — Parameterized query errors
```

```python
from flowmaticdb import DatabaseError, QueryError

try:
    db.select("users").execute()
except QueryError as e:
    print(f"Query error: {e}")
except DatabaseError as e:
    print(f"Database error: {e}")
```

---

## Datetime, JSON and Boolean Values

`datetime` objects, JSON documents and booleans are serialized on the way into the database and deserialized on the way back out, on every adapter.

```python
from datetime import datetime, timezone

db.create_table("events").if_not_exists() \
    .identity("id") \
    .datetime("happened_at") \
    .json("payload") \
    .execute()

db.insert("events").values({
    "happened_at": datetime.now(timezone.utc),
    "payload": {"kind": "signup", "tags": ["a", "b"]},
}).execute()

row = db.select("events").execute().fetch_dict()
row["happened_at"]   # datetime
row["payload"]       # dict
```

`TypeEnum.JSON` (the `.json()` column builder) maps to the best type the server has: `JSONB` on PostgreSQL ≥ 9.4, `JSON` on PostgreSQL ≥ 9.2, MySQL ≥ 5.7.8, MariaDB ≥ 10.2.7 and SQLite, and `TEXT` on anything older. `TypeEnum.DATETIME` maps to `TIMESTAMPTZ`, `DATETIME(6)` and `DATETIME` respectively.

Nested values `json` does not know are rendered rather than raising: `datetime`, `date` and `time` become ISO-8601 strings, `Decimal` becomes a string (a float would lose precision). A JSON column holding text that is not valid JSON is handed back as that text instead of failing the fetch.

How each driver is wired up:

| Driver | Datetime | JSON |
|--------|----------|------|
| psycopg | Native, both directions | Serialized on the way in; psycopg decodes `json`/`jsonb` on the way out |
| asyncpg | Bound natively, reconciled against the placeholder's declared type | `json`/`jsonb` codecs registered on connect, both directions |
| mysql.connector | Native, both directions | Serialized on the way in; `MySQLResult` decodes columns the server reports as `json` |
| sqlite3 | `DATETIME`/`TIMESTAMP`/`DATE` adapters and converters registered by `SQLiteAdapter` | `JSON`/`JSONB` adapters and converters |

SQLite stores only primitives, so `SQLiteAdapter` registers custom datatypes with the `sqlite3` module and opens its connections with `detect_types=sqlite3.PARSE_DECLTYPES`. Conversion is keyed off the column's *declared* type, so a `DATETIME`, `JSON` or `BOOLEAN` table column is converted while an expression (`count(*)`, a computed alias) has no declared type and is returned as-is. Datetimes are written as full ISO-8601, so microseconds and UTC offsets survive the round trip.

### Booleans

Only PostgreSQL has a boolean type. SQLite stores 0/1 under a declared `BOOLEAN` column and MySQL stores a `TINYINT`, and both are read back as a real `bool`:

```python
db.create_table("flags").if_not_exists().identity("id").boolean("active").execute()
db.insert("flags").values({"active": True}).execute()

db.select("flags").execute().scalar("active")   # True, not 1
```

The two emulating dialects reach that differently, which is worth knowing when reading a table this library did not create:

- **SQLite** is exact — the converter fires on the column's declared `BOOLEAN`/`BOOL` type, and nothing else is touched.
- **MySQL** reports `BOOL` and `TINYINT` as the same wire type and drops the display width, so **every** `TINYINT` column reads back as a `bool`. `TypeEnum.INT` never maps to `TINYINT` (it is `INTEGER`/`BIGINT`), so a schema this library created is unaffected; a foreign table storing small numbers in a `TINYINT` is. Select such a column as `CAST(col AS SIGNED)` — or let a pydantic model coerce at the edge — if you need the number.

### PostgreSQL arrays — `PostgresArray`

A bare `list` is a JSON document on **every** dialect, PostgreSQL included. PostgreSQL also has a real array type, but nothing in the value itself says which of the two is meant, so the array reading is opt-in — wrap the value in `PostgresArray`:

```python
from flowmaticdb import PostgresArray

db.insert("rows").values({
    "id": 1,
    "actual_json_column": [1, 2, 3, 4],
    "postgres_array_column": PostgresArray([5, 6, 7, 8]),
}).execute()

# Also works anywhere else a value is bound, e.g. the array containment operators
db.select("rows").where_operator("tags", "@>", PostgresArray(["a", "b"])).execute()
```

Both PostgreSQL drivers behave identically here: a bare list aimed at an array column is sent as JSON and rejected, rather than quietly being taken as an array. Element types are left to the driver, so `PostgresArray([datetime(...)])` binds as `timestamptz[]`, not `text[]`.

Dialects with no array type unwrap `PostgresArray` back to JSON, so a query written for PostgreSQL still runs against SQLite and MySQL.

Reading is unaffected — an array column always comes back as a plain `list`.

---

## Dialect-Specific Behavior

### PostgreSQL

| Feature | Support | Details |
|---------|---------|---------|
| `DISTINCT ON` | ✅ | `distinct(["col1", "col2"])` |
| `ON CONFLICT` | ✅ | Native (≥ 9.5) |
| `RETURNING` | ✅ | Native (≥ 8.2) |
| `ILIKE` | ✅ | Case-insensitive LIKE |
| `LATERAL` | ✅ | (≥ 9.3) |
| Regex | ✅ | `regexp_like()` (≥ 15) or `~`/`!~` operators |
| `GENERATED BY DEFAULT AS IDENTITY` | ✅ | (≥ 17, or falls back to `SERIAL`) |
| Native boolean | ✅ | `BOOLEAN` type |
| Datetime | ✅ | Microsecond precision: `%Y-%m-%d %H:%M:%S.%f`; `TypeEnum.DATETIME` → `TIMESTAMPTZ` |
| JSON | ✅ | `TypeEnum.JSON` → `JSONB` (≥ 9.4) or `JSON` (≥ 9.2); a bare `list`/`dict` is a document |
| Arrays | ✅ | Opt-in via `PostgresArray([...])` — see [PostgreSQL arrays](#postgresql-arrays--postgresarray) |

### SQLite

| Feature | Support | Details |
|---------|---------|---------|
| `ON CONFLICT` | ✅ | (≥ 3.24.0) |
| `RETURNING` | ✅ | (≥ 3.35.0) |
| `GLOB` | ✅ | Native file globbing |
| `REGEXP` | ✅ | Via `regexp_like()` or `REGEXP` operator |
| `ALTER COLUMN` | ❌ | Raises `QueryError` |
| `DROP COLUMN` | ✅ | Rendered as-is; SQLite supports it from 3.35.0, and an older library raises from the driver, not the dialect |
| Named constraints | ❌ | Names stripped from constraints |
| Named `ON CONFLICT` | ❌ | Raises `QueryError`; pass conflict **columns** as a list |
| Auto-increment | ✅ | `INTEGER PRIMARY KEY AUTOINCREMENT` |
| Case-insensitive LIKE | ✅ | Default SQLite behavior |
| Datetime | ✅ | Custom `DATETIME`/`TIMESTAMP`/`DATE` datatype via `sqlite3` adapters and converters |
| JSON | ✅ | Custom `JSON`/`JSONB` datatype via `sqlite3` adapters and converters |
| Native boolean | ❌ | `TypeEnum.BOOL` → `BOOLEAN`, stored as 0/1 and converted back to `bool` on read |

### MySQL

| Feature | Support | Details |
|---------|---------|---------|
| `ON DUPLICATE KEY` | ✅ | Via `on_conflict_do_update()` |
| `RETURNING` | ⚠️ | Not supported by the server (MariaDB ≥ 10.5 excepted); INSERT emulates it, UPDATE/DELETE drop the clause |
| Auto-increment | ✅ | `AUTO_INCREMENT` |
| Placeholders | ✅ | `?` → `%s` conversion for connector |
| Datetime | ✅ | `TypeEnum.DATETIME` → `DATETIME(size)`, fsp clamped to 6 |
| JSON | ✅ | `TypeEnum.JSON` → `JSON` (MySQL ≥ 5.7.8, MariaDB ≥ 10.2.7), else `TEXT` |
| Native boolean | ❌ | `TypeEnum.BOOL` → `TINYINT`; every `TINYINT` column reads back as `bool` |

### General ANSI (SQLDialect base)

- `LIMIT` / `OFFSET` — Standard ANSI syntax
- `LIMIT ? OFFSET ?` — Parameterized
- No native `ON CONFLICT`, `RETURNING`, `DISTINCT ON`, or `LATERAL` — INSERT emulates the first two
- No `GLOB` support
- Regex raises `QueryError`

---

## Architecture

```
┌────────────────────────────────────────────────────┐
│                   User Code                        │
│   DB.connect_*() → Database → Query Builders      │
└──────────────────┬─────────────────────────────────┘
                   │
          ┌────────┴────────┐
          ▼                 ▼
    ┌──────────┐    ┌──────────────┐
    │ Dialects │    │  Adapters    │
    │ ──────── │    │ ──────────   │
    │ SQL gen  │    │ Connection   │
    │ + types  │    │ + execution  │
    └────┬─────┘    └──────┬───────┘
         │                 │
         ▼                 ▼
    ┌──────────┐    ┌──────────────┐
    │ Query    │    │   Result     │
    │ Builders │    │ ──────────   │
    │ ──────── │    │ fetch_dict() │
    │ Fluent   │    │ fetch_dicts()│
    │ chaining │    │ scalar()     │
    └──────────┘    └──────────────┘
```

### Five Pillars

1. **Dialects** — Database-specific SQL generation
   - `DialectABC` — Abstract base
   - `SQLDialect` — ANSI SQL (~713 lines; overridable in subclasses)
   - `PostgresqlDialect` — PostgreSQL overrides
   - `SQLiteDialect` — SQLite overrides
   - `MySQLDialect` — MySQL overrides

2. **Adapters** — Connection wrappers
   - `AdapterABC` — Abstract base
   - `SQLiteAdapter` — Wraps `sqlite3.Connection`
   - `PsycopgAdapter` — Wraps `psycopg.Connection`
   - `AsyncpgAdapter` — Wraps `asyncpg.Connection` on a private event loop
   - `MySQLAdapter` — Wraps `mysql.connector.Connection`

3. **Query Builders** — Fluent SQL construction
   - `SelectQuery` — SELECT with WHERE/HAVING/JOINs/GROUP BY/ORDER BY/LIMIT/OFFSET/UNION
   - `InsertQuery` — INSERT with ON CONFLICT/RETURNING
   - `UpdateQuery` — UPDATE with WHERE/RETURNING
   - `DeleteQuery` — DELETE with WHERE/RETURNING
   - `CreateTableQuery` — CREATE TABLE with columns, keys, constraints
   - `AlterTableQuery` — ALTER TABLE (add/rename/drop columns, constraints)
   - `DropTableQuery` — DROP TABLE

4. **Results** — Unified result set
   - `ResultABC` — Abstract base
   - `Result` — In-memory result (snapshot)
   - `SQLite3Result` — Wraps `sqlite3.Cursor`
   - `PsycopgResult` — Wraps psycopg cursor
   - `AsyncpgResult` — Wraps an asyncpg record set
   - `MySQLResult` — Wraps `mysql.connector.cursor`

5. **Migrations** — Ordered, reversible schema changes
   - `MigrationABC` — Abstract base (`up()`, `down()`, `in_transaction()`)
   - `Migrator` — Discovery, bookkeeping and execution

### Mixin Architecture

Query builders use Python multiple inheritance for composable behavior:

| Mixin | Used By | Methods |
|-------|---------|---------|
| `WhereMixin` | Select, Update, Delete | `where_*`, `or_where_*` (40+ methods) |
| `HavingMixin` | Select | `having_*`, `or_having_*` (40+ methods) |
| `JoinsMixin` | Select | `left_join()`, `inner_join()`, `cross_join()`, etc. |
| `ColumnsMixin` | Select | `columns()` |
| `DistinctMixin` | Select | `distinct()` |
| `GroupByMixin` | Select | `group_by()` |
| `OrderByMixin` | Select | `order_by_asc()`, `order_by_desc()` |
| `LimitMixin` | Select | `limit()` |
| `OffsetMixin` | Select | `offset()` |
| `UnionMixin` | Select | `union()`, `union_all()` |
| `ValuesMixin` | Insert | `values()` |
| `UpdatesMixin` | Update | `updates()` |
| `ReturningMixin` | Insert, Update, Delete | `returning()` |
| `OnConflictMixin` | Insert | `on_conflict_do_nothing()`, `on_conflict_do_update()` |
| `LastInsertIdMixin` | Insert | `last_insert_id()` |
| `ColumnsDefinitionMixin` | CreateTable | `column()`, `integer()`, `string()`, `boolean()`, etc. |
| `AltersMixin` | AlterTable | `add_column()`, `rename_column()`, `drop_column()`, etc. |
| `ConstraintsMixin` | CreateTable | `unique_constraint()`, `foreign_key_constraint()` |
| `PrimaryKeysMixin` | CreateTable | `primary_keys()` |
| `IfNotExistsMixin` | CreateTable | `if_not_exists()` |
| `IfExistsMixin` | DropTable | `if_exists()` |

---

## Enums Reference

```python
from flowmaticdb.query.enums import ConditionEnum
# =, <>, <, <=, >, >=, BETWEEN, NOT BETWEEN, LIKE, NOT LIKE,
# GLOB, NOT GLOB, IN, NOT IN, REGEX, NOT REGEX, EXISTS, NOT EXISTS, RAW

from flowmaticdb.query.enums import ChainEnum
# AND, OR

from flowmaticdb.query.enums import JoinEnum
# LEFT JOIN, LEFT JOIN LATERAL, INNER JOIN, INNER JOIN LATERAL,
# CROSS JOIN, CROSS JOIN LATERAL

from flowmaticdb.query.enums import OrderByDirectionEnum
# ASC, DESC

from flowmaticdb.query.enums import UnionEnum
# UNION, UNION ALL

from flowmaticdb.query.enums import TypeEnum
# BOOL, INT, FLOAT, STRING, DATETIME, JSON

from flowmaticdb.query.enums import ReferentialActionEnum
# ON_UPDATE_NO_ACTION, ON_UPDATE_SET_NULL, ON_UPDATE_CASCADE,
# ON_DELETE_NO_ACTION, ON_DELETE_SET_NULL, ON_DELETE_CASCADE
```

---

## Import Notes

A leading underscore on a module name marks it as a private implementation detail — never import from it directly. Each package's public API is exactly its `__init__.py` `__all__`; import from the package instead. This holds without exception, including the exception classes and helper functions, which live in `_exceptions.py` and `_helpers.py` and are re-exported from `flowmaticdb`.

- `PsycopgAdapter`, `MySQLAdapter` — Import from `flowmaticdb.adapters`, NOT a submodule
- `PostgresArray` — Re-exported from the top-level package: `from flowmaticdb import PostgresArray` (it also lives in `flowmaticdb.query.expressions`)
- `PsycopgResult`, `MySQLResult` — Import from `flowmaticdb.result`, NOT a submodule
- `raw()`, `identifier()`, `alias()`, `expression()`, `sub_query()`, `current_timestamp()`, `now()` — Module-level functions, imported from `flowmaticdb`
- `snapshot_result()` — Import from `flowmaticdb.result`

- `MigrationABC`, `Migrator` — Import from `flowmaticdb.migrations`

```python
from flowmaticdb.adapters import PsycopgAdapter, AsyncpgAdapter, MySQLAdapter
from flowmaticdb.result import PsycopgResult, MySQLResult, snapshot_result
from flowmaticdb.migrations import MigrationABC, Migrator
from flowmaticdb import raw, identifier, alias, expression, sub_query, current_timestamp, now
```

---

## Qualified Column References

Use two-element lists for schema-qualified or table-qualified column names:

```python
# Correct: table-qualified
.where_equals(["users", "name"], "Alice")

# Correct: schema-qualified
.where_equals(["public", "users", "name"], "Alice")

# Correct: using identifier()
.where_equals(identifier(["users", "name"]), "Alice")

# WRONG: "users.name" is treated as a single identifier
# and escaped as "users.name" (non-existent column)
```

The same lists work in `columns()`, `group_by()` and `returning()` — every
identifier is escaped segment by segment, however deeply the list nests:

```python
db.select("users").columns([["users", "email"], "name"]).execute()
# SELECT "users"."email", "name" FROM "users"

# With an alias, pass the qualified column as the dict value
db.select("users").columns({"mail": ["users", "email"]}).execute()
# SELECT "users"."email" AS "mail" FROM "users"
```

For raw JOIN clauses and aggregate expressions, use `raw()`:

```python
query.join(raw("LEFT JOIN orders o ON o.user_id = users.id"))
```

Schema-qualified table references work with plain lists:

```python
db.insert(["public", "users"]).values({"name": "Alice"}).execute()
db.delete(["schema", "table"]).where_equals("id", 1).execute()
db.update(["schema", "table"]).updates({"name": "Bob"}).execute()
db.create_table(["schema", "table"]).identity("id").string("name").execute()
```

---

## Database-Specific Notes

### Placeholder Conversion

All dialects emit `?` as the placeholder. Each adapter converts to its driver's native format:
- **PostgreSQL**: `?` → `%s` via `question_marks_to_percent_s()` (psycopg expects `%s`)
- **MySQL**: `?` → `%s` via `question_marks_to_percent_s()` (mysql-connector expects `%s`)
- **SQLite**: `%s` → `?` via `percent_s_to_question_marks()` (SQLite uses `?` natively; handles user-provided `%s`)

Both conversion methods use `REGEX_PATTERN` to skip placeholders inside quoted strings and comments.

### DDL vs DML

- **DDL** (CREATE, ALTER, DROP, BEGIN, COMMIT): Use `adapter.exec(sql)` — no parameter binding
- **DML** (SELECT, INSERT, UPDATE, DELETE): Use `adapter.query_with_params(dialect, qwp)` — uses parameterized queries

---

## Development

### Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Running Tests

```bash
# All 191 tests
python3 -m pytest

# Unit tests only (no database needed)
python3 -m pytest tests/test_dialect_sql.py
python3 -m pytest tests/test_select_query.py

# SQLite integration (in-memory, no setup)
python3 -m pytest tests/test_integration_sqlite.py

# PostgreSQL integration (requires Docker)
docker compose up -d postgres
python3 -m pytest tests/test_integration_postgres.py

# MySQL integration (requires Docker)
docker compose up -d mysql
python3 -m pytest tests/test_integration_mysql.py

# Single test
python3 -m pytest tests/test_dialect_sql.py -k "test_select"

# Type checking
python3 -m mypy src/flowmaticdb

# Linting
python3 -m ruff check src/flowmaticdb/ tests/
```

### Run Demo

```bash
python3 main.py
```

Connects to MySQL by default. Edit `main.py` to switch to SQLite or PostgreSQL.

---

## Requirements

- Python ≥ 3.11
- `asyncpg>=0.29` (PostgreSQL, the default adapter — optional)
- `psycopg[binary]>=3.1` (PostgreSQL, with `asyncpg_adapter=False` — optional)
- `mysql-connector-python>=9.0` (MySQL and MariaDB adapter — optional)
- SQLite uses the standard library (`sqlite3`)

---

## License

MIT
