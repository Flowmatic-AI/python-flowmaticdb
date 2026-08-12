---
name: migrate-to-flowmaticdb
description: Audit a FastAPI or Flask project's database layer and migrate it to flowmaticdb, or set flowmaticdb up in a fresh project. Use when asked to adopt, add, install, or migrate to flowmaticdb; to replace raw psycopg / psycopg2 / sqlite3 / asyncpg / mysql-connector / PyMySQL cursor code with a query builder; to add schema migrations to a project that has none; or to turn docker-entrypoint SQL files into real migrations. Also use to decide whether flowmaticdb is the right fit at all — it advises against adopting it over SQLAlchemy + Alembic or any other ORM that already does the job.
---

# Migrate a project to flowmaticdb

flowmaticdb is a **synchronous, multi-dialect query builder plus a small migration
runner** for PostgreSQL, SQLite, MySQL and MariaDB. It is not an ORM. It earns its
place in projects that talk to the database through raw driver cursors and
hand-written SQL strings; it is a downgrade for projects that already run a real
ORM with a real migration tool.

So the first deliverable of this skill is a **verdict**, not a rewrite.

## Step 1 — Audit before touching anything

Work out what the project actually uses. Never infer from a single import.

```bash
# Declared dependencies
cat pyproject.toml requirements*.txt setup.py Pipfile 2>/dev/null | grep -iE \
  "sqlalchemy|alembic|django|sqlmodel|tortoise|piccolo|peewee|pony|psycopg|asyncpg|mysql|pymysql|mariadb|databases|aiosqlite|duckdb|supabase|prisma"

# Actual usage in code
grep -rniE "sqlalchemy|declarative_base|sessionmaker|create_engine|alembic" --include="*.py" . | head -30
grep -rniE "psycopg2?|asyncpg|sqlite3|mysql\.connector|pymysql|MySQLdb|aiomysql" --include="*.py" . | head -30
grep -rnE "\.cursor\(\)|cursor\.execute|conn\.execute|await conn\.(fetch|execute)" --include="*.py" . | head -30

# Existing schema management
ls alembic/ migrations/ 2>/dev/null
find . -name "*.sql" -not -path "./.git/*" | head -20
grep -rn "docker-entrypoint-initdb.d\|initdb\|\.sql" docker-compose*.yml Dockerfile* 2>/dev/null

# Web framework and endpoint style (async matters — see Step 4)
grep -rnE "FastAPI\(|Flask\(" --include="*.py" . | head
grep -rcE "^async def |    async def " --include="*.py" . | grep -v ":0" | head
```

`references/audit.md` has the full detection matrix, including mixed stacks and
the frameworks that hide their driver behind a helper module.

## Step 2 — Give the verdict

| What the audit found | Verdict |
|---|---|
| SQLAlchemy ORM + Alembic | **Advise against adopting flowmaticdb.** Stop here. |
| Django ORM, SQLModel, Tortoise, Piccolo, Pony, Peewee with a migration tool | **Advise against.** Stop here. |
| SQLAlchemy Core or an ORM with **no** migration tool | **Advise against switching**; recommend adding Alembic (or that ORM's migration tool) instead. |
| Raw `psycopg` / `psycopg2` / `sqlite3` / `asyncpg` / `mysql-connector-python` / `PyMySQL` / `MySQLdb` / `aiomysql` cursors and SQL strings | **Migrate.** This is what flowmaticdb is for → Step 3, Path B. |
| `databases` / `aiosqlite` used purely as a raw SQL executor | **Migrate** → Path B. |
| No database layer at all, or a fresh project | **Set it up** → Step 3, Path C. |
| Mixed: an ORM for most models plus a corner of raw SQL | **Advise against.** Two schema owners is worse than either one alone. |

### When the verdict is "advise against", say so plainly and stop

Do not migrate anyway, and do not soften it into a menu of options. State the
reasoning concretely:

> This project already has SQLAlchemy models and Alembic migrations. flowmaticdb
> is a query builder with a light migration runner — moving to it would trade
> away the identity map, relationship loading, unit-of-work session handling,
> connection pooling, async support, and Alembic's autogenerate/downgrade for a
> large hand-written rewrite, and gain nothing. The abstraction you have already
> does this job properly. I'd leave it as is.

Offer the one honest exception: if the user's actual goal is to *drop* the ORM
(they want plain SQL semantics, they are fighting the session lifecycle, they
want to shed a heavy dependency), then flowmaticdb is a reasonable target — but
that is a deliberate architectural decision, so make them confirm it before you
write any code.

## Step 3 — Execute the chosen path

### Path B — replacing a raw driver

1. **Install.** `flowmaticdb` plus the extra matching the server:
   `flowmaticdb[postgres]` (psycopg), `flowmaticdb[asyncpg]`, `flowmaticdb[mysql]`.
   SQLite needs no extra. Leave the old driver installed until the last call site
   is gone.
2. **Create one connection module** (`assets/db.py`) and point it at the same
   database and env vars the project already uses — the template ships on the
   SQLite branch, so switch `connect()` to the server variant below it. One `DB`
   for the whole process: it is thread-safe and hands each thread its own
   connection. Never change which database an existing project runs on as part
   of this migration.
3. **Capture the current schema first**, before rewriting any query: dump the
   live schema (or read the entrypoint SQL / setup script) and write it as the
   **initial migration** — see `references/migrations.md`. Existing databases
   must survive it untouched, which is what the `if_not_exists` safeguards buy.
4. **Rewrite call sites one module at a time**, using the driver-by-driver
   recipes in `references/translation.md`. Run the test suite between modules.
5. **Wire lifecycle into the framework** (below), then delete the old driver
   from the dependency list.

### Path C — fresh project

**Default to SQLite.** Do not ask which database to use, and do not stand up a
PostgreSQL container to hold three tables. `pip install flowmaticdb` and a file
path is the whole setup: no server, no extra dependency, no compose file, no
credentials in the environment. The connection opens with a WAL journal, foreign
keys ON and a 500 ms busy timeout already, so there is nothing to tune either.

Switching later is one function: `connect()` in `assets/db.py`. The query
builder and every migration render per dialect, so they are unchanged by the
move — provided they stay portable. Keep them that way while the project is on
SQLite: conflict targets as column lists, no `db.exec()` of dialect-specific
SQL, no reliance on SQLite's loose typing. Then building on SQLite now does not
lock the project in.

Use a server database from day one only when the user asks for one, or when the
project already implies it — multiple processes or machines writing the same
data, an existing managed instance, or a PostgreSQL-specific feature in the
requirements. Say which one you picked and why, in a sentence.

1. `pip install flowmaticdb`. Extras are only for server databases:
   `flowmaticdb[postgres]`, `[asyncpg]`, `[mysql]`.
2. Drop in `assets/db.py` and `assets/migrate.py`, adjusted for the project's
   layout and env vars. `assets/db.py` ships on the SQLite branch, with the
   server variants commented below it.
3. Create `migrations/` and write the initial schema migration — from the
   docker entrypoint SQL if one exists (`references/migrations.md`), otherwise
   from the models the user describes.
4. Wire lifecycle into the framework, add `python migrate.py up` to the startup
   or deploy step, and confirm `up` then `down` then `up` round-trips cleanly.
5. Add the database file to `.gitignore` — `app.db`, plus the `app.db-wal` and
   `app.db-shm` sidecars WAL creates.

### Framework wiring

flowmaticdb's API is **synchronous**. Build the `DB` once at startup, share it,
close it at shutdown.

```python
# FastAPI
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import close_db, get_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_db()
    yield
    close_db()


app = FastAPI(lifespan=lifespan)


@app.get("/users")
def list_users():                      # `def`, not `async def` — see Step 4
    return get_db().select("users").execute().fetch_dicts()
```

```python
# Flask
import atexit

from flask import Flask

from app.db import close_db, get_db


def create_app() -> Flask:
    app = Flask(__name__)

    get_db()
    atexit.register(close_db)

    @app.route("/users")
    def list_users():
        return get_db().select("users").execute().fetch_dicts()

    return app
```

Flask's dev server and Uvicorn's sync workers are threaded, which is exactly
the model flowmaticdb is built for. There is no per-request teardown to write:
a worker thread's connection is closed when that thread exits, and `close_db()`
sweeps whatever is left at process exit.

## Step 4 — The decisions that bite later

Raise these **before** writing code, not after.

- **Sync API in an async app.** Every flowmaticdb call blocks. If the project is
  `async def` endpoints over asyncpg, migrating means either converting those
  endpoints to `def` (FastAPI runs them on its worker-thread pool, which is the
  intended pattern) or wrapping each call in `await asyncio.to_thread(...)`.
  Calling `db.select(...)` straight from a coroutine stalls the event loop.
  Flag this explicitly and let the user choose. `AsyncpgAdapter` does not change
  it — that is an internal driver choice with a synchronous surface.
- **Connection count tracks thread count.** Each thread opens its own
  connection and holds it for the thread's life. Size `max_concurrent_connections`
  at or above the worker pool (FastAPI's default pool is 41 threads), and keep
  the server's own `max_connections` above that.
- **`asyncpg_adapter` defaults to `True`** on `connect_postgresql()`. Pass
  `asyncpg_adapter=False` to use psycopg — otherwise install the `asyncpg` extra.
- **MySQL DDL is not transactional.** A migration that runs several DDL
  statements cannot be rolled back halfway on MySQL. Keep one logical change per
  migration file.
- **SQLite cannot ALTER COLUMN, name a constraint, or take a named ON CONFLICT
  target** — all three raise `QueryError`. Pass conflict targets as a list of
  columns (`on_conflict_do_nothing(["email"])`), and write column-type changes
  as a create-copy-drop-rename dance through `db.exec()`.
- **`db.exec()` runs exactly one statement.** A whole `.sql` file cannot be
  handed to it; that is why entrypoint SQL gets rebuilt with the builder.

## Reference material

| File | Read it when |
|---|---|
| `references/audit.md` | Classifying the project, including mixed and disguised stacks |
| `references/translation.md` | Rewriting raw driver calls — one section per driver |
| `references/migrations.md` | Setting up `migrations/`, the CLI, and converting entrypoint SQL |
| `references/api.md` | Query builder, DDL, results, types, and the dialect gotchas |
| `assets/db.py` | Connection module template |
| `assets/migrate.py` | Migration CLI template |
