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
        asyncpg_adapter: bool = False,
    ) -> Self:
        from flowmaticdb.adapters import AdapterABC, AsyncpgAdapter, PsycopgAdapter
        from flowmaticdb.dialects import PostgresqlDialect

        adapter: AdapterABC
        if asyncpg_adapter:
            adapter = AsyncpgAdapter(
                database_name=name,
                host=host,
                port=port,
                user=user,
                password=password,
                startup_queries=startup_queries,
                options=options,
                debug_callback=debug_callback,
            )
        else:
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

    @classmethod
    def drivers(cls) -> list[str]:
        import importlib.util

        drivers: list[str] = []

        if importlib.util.find_spec("sqlite3") is not None:
            drivers.append("sqlite")

        if importlib.util.find_spec("psycopg") is not None or importlib.util.find_spec("asyncpg") is not None:
            drivers.append("postgresql")

        if importlib.util.find_spec("mysql.connector") is not None:
            drivers.append("mysql")
            drivers.append("mariadb")

        return drivers

    def close(self) -> None:
        self.adapter.close()

    def is_connected(self) -> bool:
        return self.adapter.is_connected()

    def reconnect(self) -> None:
        """Drop the current connection and open a fresh one.

        Any open transaction dies with the old connection, so the savepoint
        bookkeeping is reset here as well."""
        self._savepoints = []
        self.adapter.reconnect()

    def reconnect_if_disconnected(self) -> bool:
        """Reconnect when the connection has dropped. Returns whether it did.

        Note for SQLite ``:memory:`` databases: a reconnect opens an *empty*
        database, since the old one only ever existed in the dropped handle."""
        if self.adapter.is_connected():
            return False

        self.reconnect()
        return True

    def get_connection(self) -> Any:
        return self.adapter.get_connection()
