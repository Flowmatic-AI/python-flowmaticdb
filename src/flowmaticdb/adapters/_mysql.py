from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from flowmaticdb.adapters._base import AdapterABC
from flowmaticdb.result._base import ResultABC
from flowmaticdb.result._mysql import MySQLResult

if TYPE_CHECKING:
    from flowmaticdb._query_with_params import QueryWithParams
    from flowmaticdb.dialects._base import DialectABC


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
        self._connection: Any = None
        self._current_cursor: Any = None
        self._connect()

    def _connect(self) -> None:
        import mysql.connector

        kwargs: dict[str, Any] = {
            "host": self._host,
            "port": self._port,
            "database": self._database_name,
            "user": self._user,
            "password": self._password,
            "autocommit": True,
        }

        ssl_mode = self._options.get("ssl_mode")
        if ssl_mode:
            kwargs["ssl_mode"] = ssl_mode

        connect_timeout = self._options.get("connect_timeout")
        if connect_timeout:
            kwargs["connect_timeout"] = connect_timeout

        charset = self._options.get("charset", "utf8mb4")
        kwargs["charset"] = charset

        self._connection = mysql.connector.connect(**kwargs)

        self._exec_startup_queries()

    def _drain_cursor(self) -> None:
        """Drain any unread results from the previous cursor.

        MySQL connector forbids creating a new cursor while the previous
        one still has unread rows.  This method consumes and discards any
        remaining rows so the next query can proceed.
        """
        if self._current_cursor is not None:
            try:
                self._current_cursor.fetchall()
            except Exception:  # noqa: BLE001, S110
                pass
            self._current_cursor = None

    def version(self) -> str:
        try:
            cursor = self._connection.execute("SELECT VERSION()")
            row = cursor.fetchone()
            if row:
                return str(row[0])
            return "0"
        except Exception:  # noqa: BLE001
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

    def begin_transaction(self) -> None:
        self._connection.start_transaction()
        self._in_transaction = True

    def commit_transaction(self) -> None:
        self._connection.commit()
        self._in_transaction = False

    def rollback_transaction(self) -> None:
        self._connection.rollback()
        self._in_transaction = False

    def begin_savepoint(self, name: str) -> None:
        self._drain_cursor()
        cursor = self._connection.cursor()
        cursor.execute(f"SAVEPOINT {name}")

    def commit_savepoint(self, name: str) -> None:
        self._drain_cursor()
        cursor = self._connection.cursor()
        cursor.execute(f"RELEASE SAVEPOINT {name}")

    def rollback_savepoint(self, name: str) -> None:
        self._drain_cursor()
        cursor = self._connection.cursor()
        cursor.execute(f"ROLLBACK TO SAVEPOINT {name}")

    @property
    def in_transaction(self) -> bool:
        return self._in_transaction

    def last_insert_id(self, name: str | None = None) -> int | str | None:
        self._drain_cursor()
        cursor = self._connection.cursor()
        cursor.execute("SELECT LAST_INSERT_ID()")
        row = cursor.fetchone()
        return row[0] if row else None
