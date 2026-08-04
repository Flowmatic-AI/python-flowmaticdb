from __future__ import annotations

from collections.abc import Callable
from typing import Any, Self

from flowmaticdb.database._abc import DatabaseABC


class Database(DatabaseABC):
    @classmethod
    def connect_sqlite(
        cls,
        name: str,
        startup_queries: list[str] | None = None,
        options: dict[str, Any] | None = None,
        debug_callback: Callable[[str, float, str | None], None] | None = None,
    ) -> Self:
        from flowmaticdb.adapters import SQLiteAdapter
        from flowmaticdb.dialects import SQLiteDialect

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
    ) -> Self:
        from flowmaticdb.adapters import PsycopgAdapter
        from flowmaticdb.dialects import PostgresqlDialect

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
    def _connect_mysql_family(
        cls,
        name: str,
        host: str,
        port: int,
        user: str,
        password: str,
        startup_queries: list[str] | None,
        options: dict[str, Any] | None,
        debug_callback: Callable[[str, float, str | None], None] | None,
        is_mariadb: bool,
    ) -> Self:
        from flowmaticdb.adapters import MySQLAdapter
        from flowmaticdb.dialects import MySQLDialect

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
        return cls(adapter, MySQLDialect(version=adapter.version(), options=options or {}, is_mariadb=is_mariadb))

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
    ) -> Self:
        return cls._connect_mysql_family(
            name, host, port, user, password, startup_queries, options, debug_callback, is_mariadb=False
        )

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
    ) -> Self:
        return cls._connect_mysql_family(
            name, host, port, user, password, startup_queries, options, debug_callback, is_mariadb=True
        )

    _DRIVER_NAMES = ("sqlite", "postgresql", "postgres", "pgsql", "mysql", "mariadb")

    @classmethod
    def connect(
        cls,
        driver: str,
        name: str,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        startup_queries: list[str] | None = None,
        options: dict[str, Any] | None = None,
        debug_callback: Callable[[str, float, str | None], None] | None = None,
    ) -> Self:
        if driver == "sqlite":
            return cls.connect_sqlite(
                name,
                startup_queries=startup_queries,
                options=options,
                debug_callback=debug_callback,
            )

        if driver in ("postgresql", "postgres", "pgsql"):
            return cls.connect_postgresql(
                name,
                host=host if host is not None else "localhost",
                port=port if port is not None else 5432,
                user=user if user is not None else "postgres",
                password=password if password is not None else "",
                startup_queries=startup_queries,
                options=options,
                debug_callback=debug_callback,
            )

        if driver == "mysql":
            return cls.connect_mysql(
                name,
                host=host if host is not None else "localhost",
                port=port if port is not None else 3306,
                user=user if user is not None else "root",
                password=password if password is not None else "",
                startup_queries=startup_queries,
                options=options,
                debug_callback=debug_callback,
            )

        if driver == "mariadb":
            return cls.connect_mariadb(
                name,
                host=host if host is not None else "localhost",
                port=port if port is not None else 3306,
                user=user if user is not None else "root",
                password=password if password is not None else "",
                startup_queries=startup_queries,
                options=options,
                debug_callback=debug_callback,
            )

        msg = f"unsupported driver: {driver!r} (expected one of {sorted(cls._DRIVER_NAMES)})"
        raise ValueError(msg)

    @classmethod
    def drivers(cls) -> list[str]:
        import importlib.util

        drivers: list[str] = []

        if importlib.util.find_spec("sqlite3") is not None:
            drivers.append("sqlite")

        if importlib.util.find_spec("psycopg") is not None:
            drivers.append("postgresql")

        if importlib.util.find_spec("mysql.connector") is not None:
            drivers.append("mysql")
            drivers.append("mariadb")

        return drivers

    def show_tables(self) -> list[str]:
        result = self.query("SHOW TABLES")

        tables: list[str] = []
        while True:
            table = result.scalar()
            if not table:
                break
            tables.append(table)

        return tables

    def describe_table(self, table: str) -> list[dict[str, Any]]:
        query = f"DESCRIBE {self._dialect.escape_identifier(table)}"
        return self.query(query).fetch_dicts()

    def information_schema_tables(self) -> list[dict[str, Any]]:
        return (
            self.select(["information_schema", "tables"])
            .where_not_in("table_schema", ["pg_catalog", "information_schema"])
            .execute()
            .fetch_dicts()
        )

    def information_schema_columns(self, table: str) -> list[dict[str, Any]]:
        return (
            self.select(["information_schema", "columns"])
            .where_equals("table_name", table)
            .execute()
            .fetch_dicts()
        )

    def sqlite_master_tables(self) -> list[dict[str, Any]]:
        return (
            self.select("sqlite_master")
            .where_equals("type", "table")
            .execute()
            .fetch_dicts()
        )

    def pragma_table_info(self, table: str) -> list[dict[str, Any]]:
        query = f"PRAGMA table_info({self._dialect.escape_identifier(table)})"
        return self.query(query).fetch_dicts()
