from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from flowmaticdb.adapters._base import AdapterABC
from flowmaticdb.result._base import ResultABC
from flowmaticdb.result._postgres import PsycopgResult

if TYPE_CHECKING:
    from flowmaticdb._query_with_params import QueryWithParams
    from flowmaticdb.dialects._base import DialectABC


class PsycopgAdapter(AdapterABC):
    def __init__(
        self,
        database_name: str,
        startup_queries: list[str] | None = None,
        options: dict[str, Any] | None = None,
        debug_callback: Callable[[str, float, str | None], None] | None = None,
        host: str = "localhost",
        port: int = 5432,
        user: str = "postgres",
        password: str = "",
    ) -> None:
        super().__init__(
            driver_name="postgresql",
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
        self._connect()

    def _connect(self) -> None:
        import psycopg

        kwargs: dict[str, Any] = {
            "host": self._host,
            "port": self._port,
            "dbname": self._database_name,
            "user": self._user,
            "password": self._password,
        }

        ssl_mode = self._options.get("sslmode")
        if ssl_mode:
            kwargs["sslmode"] = ssl_mode

        search_path = self._options.get("search_path")
        if search_path:
            kwargs["options"] = f"-c search_path={search_path}"

        self._connection = psycopg.connect(**kwargs)

        self._exec_startup_queries()

    def version(self) -> str:
        try:
            cursor = self._connection.execute("SELECT version()")
            row = cursor.fetchone()
            if row:
                version_str = str(row[0])
                import re
                match = re.search(r'(\d+\.\d+(?:\.\d+)?)', version_str)
                if match:
                    return match.group(1)
            return "0"
        except Exception:  # noqa: BLE001
            return "0"

    def exec(self, query: str) -> None:
        start = time.time()
        error: str | None = None
        try:
            self._connection.execute(query)
            self._connection.commit()
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
            cursor = self._connection.execute(query)
            return PsycopgResult(cursor)
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
            if emulate_prepare:
                sql_full = query_with_params.to_sql(dialect)
                cursor = self._connection.execute(sql_full)
            else:
                cursor = self._connection.execute(sql, params)
            return PsycopgResult(cursor)
        except Exception as e:
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
        return self._connection.info.transaction_status is not None

    def last_insert_id(self, name: str | None = None) -> int | str | None:
        if name:
            cursor = self._connection.execute(f"SELECT currval('{name}')")
        else:
            cursor = self._connection.execute("SELECT lastval()")
        row = cursor.fetchone()
        return row[0] if row else None
