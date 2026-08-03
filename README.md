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

A multi-dialect database abstraction layer for Python, supporting **PostgreSQL**, **SQLite**, and **MySQL**. Ported from the PHP library `sentience/database`.

flowmaticdb gives you a fluent query builder API, driver-level adapters, dialect-aware SQL generation, and a unified result abstraction — all with strict type hints and zero magic strings.

---

## Quick Start

```bash
pip install flowmaticdb
# Or with dev dependencies:
pip install "flowmaticdb[dev]"
```

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
| PostgreSQL | `DB.connect_postgresql()` | `PsycopgAdapter` | `PostgresqlDialect` | `psycopg[binary]>=3.1` |
| MySQL   | `DB.connect_mysql()` | `MySQLAdapter` | `MySQLDialect` | `mysql-connector-python` |

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

# With RETURNING (PostgreSQL / SQLite ≥ 3.35)
result = db.insert("users").values({"name": "Dave"}).returning(["id"]).execute()
new_id = result.scalar()

# ON CONFLICT (PostgreSQL / SQLite ≥ 3.24)
db.insert("users").values({"name": "Alice"}).on_conflict_do_nothing("name").execute()
db.insert("users").values({"name": "Alice", "age": 31}).on_conflict_do_update(
    "name", {"age": 31}
).execute()

# Get last insert ID
db.insert("users").values({"name": "Eve"}).last_insert_id("id").execute()
last_id = db.last_insert_id()
```

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
    .date_time("created_at") \
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

# INNER JOIN with ON conditions
join = query.inner_join("posts", "p")  # Returns Join object
join.on(["users", "id"], ["p", "user_id"])    # ON users.id = p.user_id
join.or_on(["p", "status"], ["'published'"])   # OR p.status = 'published'

# LEFT JOIN
query.left_join("comments", "c").on(["p", "id"], ["c", "post_id"])

# CROSS JOIN
query.cross_join("sessions")

# LATERAL joins
query.left_join_lateral(sub_query, "sq")
query.inner_join_lateral(sub_query, "sq")
query.cross_join_lateral(sub_query, "sq")

# Raw join SQL (e.g. for aggregates)
query.join(raw("LEFT JOIN (SELECT user_id, count(*) AS cnt FROM orders GROUP BY user_id) AS o ON o.user_id = users.id"))
```

### Join ON Conditions

`Join` objects support all the same condition methods as WHERE:

```python
join = query.inner_join("orders")
join.where_equals(["orders", "user_id"], ["users", "id"])
join.where_greater_than("orders.total", 100)
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
# DDL (no parameters)
db.exec("CREATE TABLE temp (id INTEGER PRIMARY KEY)")

# DML with parameters
from flowmaticdb import QueryWithParams
qwp = QueryWithParams(query="SELECT * FROM users WHERE name = ?", params=["Alice"])
result = db.query_with_params(qwp)
rows = result.fetch_dicts()

# Prepared statement shortcut
result = db.prepared("SELECT * FROM users WHERE age > ? AND active = ?", [18, True])
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
from flowmaticdb.exceptions import DatabaseError, QueryError

try:
    db.select("users").execute()
except QueryError as e:
    print(f"Query error: {e}")
except DatabaseError as e:
    print(f"Database error: {e}")
```

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
| Datetime | ✅ | Microsecond precision: `%Y-%m-%d %H:%M:%S.%f` |

### SQLite

| Feature | Support | Details |
|---------|---------|---------|
| `ON CONFLICT` | ✅ | (≥ 3.24.0) |
| `RETURNING` | ✅ | (≥ 3.35.0) |
| `GLOB` | ✅ | Native file globbing |
| `REGEXP` | ✅ | Via `regexp_like()` or `REGEXP` operator |
| `ALTER COLUMN` | ❌ | Raises `QueryError` |
| `DROP COLUMN` | ❌ | Raises `QueryError` (pre-3.35.0; newer versions support it — check dialect option) |
| Named constraints | ❌ | Names stripped from constraints |
| Auto-increment | ✅ | `INTEGER PRIMARY KEY AUTOINCREMENT` |
| Case-insensitive LIKE | ✅ | Default SQLite behavior |

### MySQL

| Feature | Support | Details |
|---------|---------|---------|
| `ON DUPLICATE KEY` | ✅ | Via `on_conflict_do_update()` |
| `RETURNING` | ❌ | Not supported; emulation not implemented |
| Auto-increment | ✅ | `AUTO_INCREMENT` |
| Placeholders | ✅ | `?` → `%s` conversion for connector |

### General ANSI (SQLDialect base)

- `LIMIT` / `OFFSET` — Standard ANSI syntax
- `LIMIT ? OFFSET ?` — Parameterized
- No native `ON CONFLICT`, `RETURNING`, `DISTINCT ON`, or `LATERAL`
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

### Four Pillars

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
   - `MySQLResult` — Wraps `mysql.connector.cursor`

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
# BOOL, INT, FLOAT, STRING, DATETIME

from flowmaticdb.query.enums import ReferentialActionEnum
# ON_UPDATE_NO_ACTION, ON_UPDATE_SET_NULL, ON_UPDATE_CASCADE,
# ON_DELETE_NO_ACTION, ON_DELETE_SET_NULL, ON_DELETE_CASCADE
```

---

## Import Notes

A leading underscore on a module name marks it as a private implementation detail — never import from it directly. Each package's public API is exactly its `__init__.py` `__all__`; import from the package instead. (`flowmaticdb.exceptions` is the one deliberate exception, kept as a public module by convention.)

- `PsycopgAdapter`, `MySQLAdapter` — Import from `flowmaticdb.adapters`, NOT a submodule
- `PsycopgResult`, `MySQLResult` — Import from `flowmaticdb.result`, NOT a submodule
- `raw()`, `identifier()`, `alias()`, `expression()`, `sub_query()`, `current_timestamp()`, `now()` — Module-level functions, imported from `flowmaticdb`
- `snapshot_result()` — Import from `flowmaticdb.result`

```python
from flowmaticdb.adapters import PsycopgAdapter, MySQLAdapter
from flowmaticdb.result import PsycopgResult, MySQLResult, snapshot_result
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
- `psycopg[binary]>=3.1` (PostgreSQL adapter — optional)
- `mysql-connector-python` (MySQL adapter — optional)
- SQLite uses the standard library (`sqlite3`)

---

## License

MIT
