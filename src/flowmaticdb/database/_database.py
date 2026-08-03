from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flowmaticdb.database._abc import DatabaseABC


class Database(DatabaseABC):
    @classmethod
    def connect_sqlite(
        cls,
        name: str,
        startup_queries: list[str] | None = None,
        options: dict[str, Any] | None = None,
        debug_callback: Callable[[str, float, str | None], None] | None = None,
    ) -> Database:
        from flowmaticdb.adapters._sqlite import SQLiteAdapter
        from flowmaticdb.dialects._sqlite import SQLiteDialect

        adapter = SQLiteAdapter(
            database_name=name,
            startup_queries=startup_queries,
            options=options,
            debug_callback=debug_callback,
        )
        return cls(adapter, SQLiteDialect(version=adapter.version(), options=options or {}))

    @classmethod
    def connect_postgresql(
        cls,
        name: str,
        host: str = "localhost",
        port: int = 5432,
        user: str = "postgres",
        password: str = "",
        startup_queries: list[str] | None = None,
        options: dict[str, Any] | None = None,
        debug_callback: Callable[[str, float, str | None], None] | None = None,
    ) -> Database:
        from flowmaticdb.adapters._postgres import PsycopgAdapter
        from flowmaticdb.dialects._postgres import PostgresqlDialect

        adapter = PsycopgAdapter(
            database_name=name,
            host=host,
            port=port,
            user=user,
            password=password,
            startup_queries=startup_queries,
            options=options,
            debug_callback=debug_callback,
        )
        return cls(adapter, PostgresqlDialect(version=adapter.version(), options=options or {}))

    @classmethod
    def connect_mysql(
        cls,
        name: str,
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "",
        startup_queries: list[str] | None = None,
        options: dict[str, Any] | None = None,
        debug_callback: Callable[[str, float, str | None], None] | None = None,
    ) -> Database:
        from flowmaticdb.adapters._mysql import MySQLAdapter
        from flowmaticdb.dialects._mysql import MySQLDialect

        adapter = MySQLAdapter(
            database_name=name,
            host=host,
            port=port,
            user=user,
            password=password,
            startup_queries=startup_queries,
            options=options,
            debug_callback=debug_callback,
        )
        return cls(adapter, MySQLDialect(version=adapter.version(), options=options or {}))

    @classmethod
    def connect_mariadb(
        cls,
        name: str,
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "",
        startup_queries: list[str] | None = None,
        options: dict[str, Any] | None = None,
        debug_callback: Callable[[str, float, str | None], None] | None = None,
    ) -> Database:
        from flowmaticdb.adapters._mysql import MySQLAdapter
        from flowmaticdb.dialects._mysql import MySQLDialect

        adapter = MySQLAdapter(
            database_name=name,
            host=host,
            port=port,
            user=user,
            password=password,
            startup_queries=startup_queries,
            options=options,
            debug_callback=debug_callback,
        )
        return cls(adapter, MySQLDialect(version=adapter.version(), options=options or {}, is_mariadb=True))

    @classmethod
    def drivers(cls) -> list[str]:
        return ["sqlite", "postgresql", "mysql"]
