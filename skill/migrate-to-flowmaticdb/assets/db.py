"""Single connection module for the application.

Adjust the connect call, the environment variable names and MIGRATIONS_DIR to
the project, then import get_db() everywhere a database handle is needed.

One DB is built per process and shared by every thread; the adapter gives each
thread its own driver connection on first use.

Defaults to SQLite: no server, no extra dependency, no container. Switching to
PostgreSQL or MySQL later means changing this one function — the query builder
and the migrations render per dialect and do not change.
"""

from __future__ import annotations

import os

from flowmaticdb.database import DB

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")

_db: DB | None = None


def connect() -> DB:
    """Open a new connection. Used by the app at startup and by the migration CLI."""
    # Connections open with a WAL journal, foreign keys ON and a 500 ms busy
    # timeout already. Pass `options` only to change one: read_only,
    # encryption_key, encoding, check_same_thread, create_functions, or a
    # busy_timeout above 500 if writers contend heavily.
    return DB.connect_sqlite(os.environ.get("DB_NAME", "database.db"))

    # PostgreSQL. Needs the flowmaticdb[postgres] extra for psycopg, or
    # flowmaticdb[asyncpg] with asyncpg_adapter=True.
    #
    # max_concurrent_connections is a ceiling on live connections, and a slot is
    # held for the life of a thread rather than a query — so keep it at or above
    # the worker pool (FastAPI's is 41 threads), and keep the server's own
    # max_connections above that.
    #
    # return DB.connect_postgresql(
    #     os.environ["POSTGRES_DB"],
    #     host=os.environ.get("POSTGRES_HOST", "localhost"),
    #     port=int(os.environ.get("POSTGRES_PORT", "5432")),
    #     user=os.environ["POSTGRES_USER"],
    #     password=os.environ.get("POSTGRES_PASSWORD", ""),
    #     asyncpg_adapter=False,
    #     max_concurrent_connections=45,
    #     acquire_connection_timeout=10.0,
    # )

    # MySQL / MariaDB. Needs the flowmaticdb[mysql] extra. Use connect_mariadb
    # for MariaDB so the dialect knows it has native RETURNING.
    #
    # return DB.connect_mysql(
    #     os.environ["MYSQL_DATABASE"],
    #     host=os.environ.get("MYSQL_HOST", "localhost"),
    #     port=int(os.environ.get("MYSQL_PORT", "3306")),
    #     user=os.environ["MYSQL_USER"],
    #     password=os.environ.get("MYSQL_PASSWORD", ""),
    #     options={"charset": "utf8mb4"},
    #     max_concurrent_connections=45,
    # )


def get_db() -> DB:
    """Return the process-wide handle, opening it on first call."""
    global _db

    if _db is None:
        _db = connect()

    return _db


def close_db() -> None:
    """Close every thread's connection. Call from the framework's shutdown hook."""
    global _db

    if _db is None:
        return

    _db.close()
    _db = None
