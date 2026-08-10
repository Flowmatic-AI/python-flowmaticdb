from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from flowmaticdb._exceptions import AdapterError
from flowmaticdb.adapters._base import AdapterABC
from flowmaticdb.result import MySQLResult, ResultABC

if TYPE_CHECKING:
    from mysql.connector.abstracts import MySQLConnectionAbstract, MySQLCursorAbstract
    from mysql.connector.types import RowItemType, RowType

    from flowmaticdb._query_with_params import QueryWithParams
    from flowmaticdb.dialects import DialectABC


class MySQLAdapter(AdapterABC):
    def __init__(
        self,
        database_name: str,
        startup_queries: list[str] | None = None,
        options: dict[str, Any] | None = None,
        debug_callback: Callable[[str, float, str | None], None] | None = None,
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "",
    ) -> None:
        super().__init__(
            driver_name="mysql",
            database_name=database_name,
            startup_queries=startup_queries,
            options=options,
            debug_callback=debug_callback,
        )
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._connection: MySQLConnectionAbstract
        self._current_cursor: MySQLCursorAbstract | None = None
        self._connect()

    def _connect(self) -> None:
        import mysql.connector
        from mysql.connector.pooling import PooledMySQLConnection

        # A cursor from a previous connection cannot be drained on the new one.
        self._current_cursor = None

        connect_options: dict[str, Any] = {
            "host": self._host,
            "port": self._port,
            "database": self._database_name,
            "user": self._user,
            "password": self._password,
            "autocommit": True,
        }

        ssl_mode = self._options.get("ssl_mode")
        if ssl_mode:
            connect_options["ssl_mode"] = ssl_mode

        connect_timeout = self._options.get("connect_timeout")
        if connect_timeout:
            connect_options["connect_timeout"] = connect_timeout

        charset = self._options.get("charset", "utf8mb4")
        connect_options["charset"] = charset

        connection = mysql.connector.connect(**connect_options)
        if isinstance(connection, PooledMySQLConnection):
            raise AdapterError("pooled MySQL connections are not supported")
        self._connection = connection

        if "charset" in self._options:
            collation = self._options.get("collation")
            names_sql = f"SET NAMES {self._options['charset']}"
            if collation:
                names_sql += f" COLLATE {collation}"
            self.exec(names_sql)

        if "engine" in self._options:
            self.exec(f"SET SESSION default_storage_engine = {self._options['engine']}")

        self._exec_startup_queries()

    def _disconnect(self) -> None:
        self._connection.close()

    def is_connected(self) -> bool:
        return bool(self._connection.is_connected())

    def _drain_cursor(self) -> None:
        if self._current_cursor is not None:
            import mysql.connector

            try:
                self._current_cursor.fetchall()
            except mysql.connector.Error:
                pass
            self._current_cursor = None

    @staticmethod
    def _first_column(row: RowType | dict[str, RowItemType]) -> RowItemType:
        if isinstance(row, dict):
            return next(iter(row.values()))
        return row[0]

    def version(self) -> str:
        import mysql.connector

        try:
            self._drain_cursor()
            cursor = self._connection.cursor()
            cursor.execute("SELECT VERSION()")
            row = cursor.fetchone()
            if row:
                return str(self._first_column(row))
            return "0"
        except mysql.connector.Error:
            return "0"

    def exec(self, query: str) -> None:
        start = time.time()
        error: str | None = None
        try:
            self._drain_cursor()
            cursor = self._connection.cursor()
            cursor.execute(query)
        except Exception as e:
            error = str(e)
            raise
        finally:
            duration = time.time() - start
            self._debug(query, duration, error)

    def query(self, query: str) -> ResultABC:
        start = time.time()
        error: str | None = None
        try:
            self._drain_cursor()
            cursor = self._connection.cursor()
            cursor.execute(query)
            self._current_cursor = cursor
            return MySQLResult(cursor)
        except Exception as e:
            error = str(e)
            raise
        finally:
            duration = time.time() - start
            self._debug(query, duration, error)

    def query_with_params(
        self,
        dialect: DialectABC,
        query_with_params: QueryWithParams,
        emulate_prepare: bool = False,
    ) -> ResultABC:
        query_with_params = query_with_params.question_marks_to_percent_s()
        sql = query_with_params.query
        params = [dialect.cast_to_driver(param) for param in query_with_params.params]

        start = time.time()
        error: str | None = None
        try:
            self._drain_cursor()
            if emulate_prepare:
                sql_full = query_with_params.to_sql(dialect)
                cursor = self._connection.cursor()
                cursor.execute(sql_full)
            else:
                cursor = self._connection.cursor()
                cursor.execute(sql, params)
            self._current_cursor = cursor
            return MySQLResult(cursor)
        except Exception as e:
            error = str(e)
            raise
        finally:
            duration = time.time() - start
            self._debug(query_with_params.to_sql(dialect), duration, error)

    @property
    def in_transaction(self) -> bool:
        return bool(self._connection.in_transaction)

    def last_insert_id(self, name: str | None = None) -> int | str | None:
        self._drain_cursor()
        cursor = self._connection.cursor()
        cursor.execute("SELECT LAST_INSERT_ID()")
        row = cursor.fetchone()
        if not row:
            return None
        value = self._first_column(row)
        if value is None or isinstance(value, (int, str)):
            return value
        raise AdapterError(
            f"unexpected LAST_INSERT_ID() result type: {type(value).__name__}"
        )

    def get_connection(self) -> Any:
        return self._connection

    def close(self) -> None:
        if not self._options.get("persistent", False):
            self._disconnect()
