from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from flowmaticdb.adapters._base import AdapterABC
from flowmaticdb.result._base import ResultABC
from flowmaticdb.result._sqlite import SQLite3Result

if TYPE_CHECKING:
    from flowmaticdb._query_with_params import QueryWithParams
    from flowmaticdb.dialects._base import DialectABC


class SQLiteAdapter(AdapterABC):
    def __init__(
        self,
        database_name: str = ":memory:",
        startup_queries: list[str] | None = None,
        options: dict[str, Any] | None = None,
        debug_callback: Callable[[str, float, str | None], None] | None = None,
    ) -> None:
        super().__init__(
            driver_name="sqlite",
            database_name=database_name,
            startup_queries=startup_queries,
            options=options,
            debug_callback=debug_callback,
        )
        self._connection: sqlite3.Connection
        self._connect()

    def _connect(self) -> None:
        db_name = self._database_name
        read_only = self._options.get("read_only", False)

        if read_only:
            uri = f"file:{db_name}?mode=ro"
            self._connection = sqlite3.connect(uri, uri=True)
        else:
            self._connection = sqlite3.connect(db_name)

        self._connection.row_factory = sqlite3.Row

        pragmas = {
            "busy_timeout": self._options.get("busy_timeout", 5000),
            "encoding": self._options.get("encoding", "UTF-8"),
            "journal_mode": self._options.get("journal_mode", "WAL"),
            "foreign_keys": self._options.get("foreign_keys", 1),
        }
        for key, value in pragmas.items():
            try:
                self._connection.execute(f"PRAGMA {key} = {value}")
            except sqlite3.Error:
                pass

        enc_key = self._options.get("encryption_key")
        if enc_key:
            self._connection.execute(f"PRAGMA key = '{enc_key}'")

        self._connection.create_function("REGEXP", 2, _regexp_fn)

        self._exec_startup_queries()

    def version(self) -> str:
        try:
            cursor = self._connection.execute("SELECT sqlite_version()")
            row = cursor.fetchone()
            return str(row[0]) if row else "0"
        except sqlite3.Error:
            return "0"

    def exec(self, query: str) -> None:
        start = time.time()
        error: str | None = None
        try:
            self._connection.execute(query)
            self._connection.commit()
        except sqlite3.Error as e:
            error = str(e)
            raise
        finally:
            duration = time.time() - start
            self._debug(query, duration, error)

    def query(self, query: str) -> ResultABC:
        start = time.time()
        error: str | None = None
        try:
            cursor = self._connection.execute(query)
            return SQLite3Result(cursor)
        except sqlite3.Error as e:
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
        query_with_params = query_with_params.percent_s_to_question_marks()
        sql = query_with_params.query
        params = [dialect.cast_to_driver(param) for param in query_with_params.params]

        start = time.time()
        error: str | None = None
        try:
            if emulate_prepare:
                sql_full = query_with_params.to_sql(dialect)
                cursor = self._connection.execute(sql_full)
            else:
                cursor = self._connection.execute(sql, params)
            return SQLite3Result(cursor)
        except sqlite3.Error as e:
            error = str(e)
            raise
        finally:
            duration = time.time() - start
            self._debug(query_with_params.to_sql(dialect), duration, error)

    def begin_transaction(self) -> None:
        self._connection.execute("BEGIN TRANSACTION")
        self._in_transaction = True

    def commit_transaction(self) -> None:
        self._connection.commit()
        self._in_transaction = False

    def rollback_transaction(self) -> None:
        self._connection.rollback()
        self._in_transaction = False

    def begin_savepoint(self, name: str) -> None:
        self._connection.execute(f"SAVEPOINT {name}")

    def commit_savepoint(self, name: str) -> None:
        self._connection.execute(f"RELEASE SAVEPOINT {name}")

    def rollback_savepoint(self, name: str) -> None:
        self._connection.execute(f"ROLLBACK TO SAVEPOINT {name}")

    @property
    def in_transaction(self) -> bool:
        return self._connection.in_transaction

    def last_insert_id(self, name: str | None = None) -> int | str | None:
        cursor = self._connection.execute("SELECT last_insert_rowid()")
        row = cursor.fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self._connection.close()

def _regexp_fn(pattern: str, value: str) -> int:
    import re
    try:
        return 1 if re.search(pattern, str(value)) else 0
    except re.error:
        return 0
