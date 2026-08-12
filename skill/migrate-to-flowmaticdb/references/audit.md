# Auditing the database layer

The verdict depends on **what owns the schema** and **what writes the queries**.
Both questions have to be answered from the code, not from the dependency list —
a `requirements.txt` line proves nothing about whether anything imports it.

## What owns the schema

| Evidence | Owner |
|---|---|
| `alembic/versions/*.py`, `alembic.ini` | Alembic |
| `<app>/migrations/00xx_*.py` with `class Migration` and `dependencies = [...]` | Django |
| `migrations/models/*.json` or `aerich.ini` | Tortoise (Aerich) |
| `piccolo_migrations/` | Piccolo |
| `docker-entrypoint-initdb.d/*.sql`, a `.sql` mounted in `docker-compose.yml` | The container entrypoint — runs **once**, on an empty volume |
| `CREATE TABLE` inside application code, guarded by `IF NOT EXISTS` | Ad-hoc bootstrap on startup |
| Nothing found | Nobody. The schema lives in someone's psql history. |

The last three are the cases flowmaticdb's migration runner genuinely improves.

## What writes the queries

| Evidence | Layer |
|---|---|
| `declarative_base()`, `Mapped[...]`, `sessionmaker`, `select(User)` | SQLAlchemy ORM |
| `create_engine` + `text("SELECT ...")` and no model classes | SQLAlchemy Core as a SQL executor |
| `models.Model`, `objects.filter(...)` | Django ORM |
| `SQLModel`, `Field(...)` | SQLModel |
| `psycopg.connect`, `cursor.execute("SELECT ...")` | Raw psycopg |
| `await conn.fetch("SELECT ...")`, `asyncpg.create_pool` | Raw asyncpg |
| `sqlite3.connect`, `conn.execute(...)` | Raw sqlite3 |
| `mysql.connector.connect`, `pymysql.connect`, `MySQLdb.connect` | Raw MySQL driver |
| `databases.Database(...)`, `await database.fetch_all(query)` with a SQL string | Raw SQL over an async wrapper |

## Cases that need a second look

**The driver is hidden behind a helper module.** A project with a `db.py`
exposing `query(sql, params)` still has raw driver usage — grep inside that
module, not just at the call sites.

**SQLAlchemy present but unused.** It arrives as a transitive dependency (Celery
result backends, `databases`, admin tooling). If nothing imports it, it does not
count as an existing abstraction.

**SQLAlchemy Core with no ORM models and no Alembic.** The engine is doing
connection pooling and placeholder handling but nothing owns the schema. Both
options are defensible; the smaller change is to add Alembic, so recommend that
first and only migrate if the user wants the ORM dependency gone.

**Async-first project on asyncpg.** Technically a raw-driver project and a valid
migration target, but flowmaticdb's API is synchronous. Surface the tradeoff from
SKILL.md Step 4 before starting — for an app whose endpoints are all `async def`
and whose throughput depends on it, the answer may legitimately be "keep asyncpg".

**Two databases.** A raw-SQL analytics connection alongside an ORM-managed
primary is the one mixed case worth migrating in part: the raw side is a genuine
fit, the ORM side must not be touched. Say clearly which is which.

**A database flowmaticdb does not support.** It speaks PostgreSQL, SQLite, MySQL
and MariaDB. DuckDB, MongoDB, ClickHouse, Snowflake, SQL Server and Oracle are
out of scope — say so and stop.

## Reporting the audit

Report, in this order:

1. Framework, database server, and driver in use.
2. Who owns the schema today, and whether migrations exist at all.
3. Roughly how many call sites the rewrite touches (`grep -c` on the cursor
   patterns is enough).
4. The verdict, with its reason.
5. For a migrate verdict: the module order you intend to convert in.
