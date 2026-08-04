from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from flowmaticdb.adapters._base import AdapterABC
from flowmaticdb.result import PsycopgResult, ResultABC

if TYPE_CHECKING:
    from psycopg import Connection
    from psycopg.rows import TupleRow

    from flowmaticdb._query_with_params import QueryWithParams
    from flowmaticdb.dialects import DialectABC


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
        self._connection: Connection[TupleRow]
        self._connect()

    def _connect(self) -> None:
        import psycopg

        connect_options: dict[str, Any] = {
            "host": self._host,
            "port": self._port,
            "dbname": self._database_name,
            "user": self._user,
            "password": self._password,
            "autocommit": True,
        }

        if "ssl_mode" in self._options:
            connect_options["sslmode"] = self._options["ssl_mode"]

        if "ssl_cert" in self._options:
            connect_options["sslcert"] = self._options["ssl_cert"]

        if "ssl_key" in self._options:
            connect_options["sslkey"] = self._options["ssl_key"]

        if "ssl_root_cert" in self._options:
            connect_options["sslrootcert"] = self._options["ssl_root_cert"]

        if "ssl_crl" in self._options:
            connect_options["sslcrl"] = self._options["ssl_crl"]

        if "client_encoding" in self._options:
            connect_options["client_encoding"] = self._options["client_encoding"]

        search_path = self._options.get("search_path")
        if search_path:
            connect_options["options"] = f"-c search_path={search_path}"

        self._connection = psycopg.connect(**connect_options)

        self._exec_startup_queries()

    def version(self) -> str:
        import psycopg

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
        except psycopg.Error:
            return "0"

    def _encode(self, query: str) -> bytes:
        return query.encode(self._connection.info.encoding)

    def exec(self, query: str) -> None:
        start = time.time()
        error: str | None = None
        try:
            self._connection.execute(self._encode(query))
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
            cursor = self._connection.execute(self._encode(query))
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
                cursor = self._connection.execute(self._encode(sql_full))
            else:
                cursor = self._connection.execute(self._encode(sql), params)
            return PsycopgResult(cursor)
        except Exception as e:
            error = str(e)
            raise
        finally:
            duration = time.time() - start
            self._debug(query_with_params.to_sql(dialect), duration, error)

    @property
    def in_transaction(self) -> bool:
        from psycopg.pq import TransactionStatus

        return bool(self._connection.info.transaction_status != TransactionStatus.IDLE)

    def last_insert_id(self, name: str | None = None) -> int | str | None:
        import psycopg

        try:
            if name:
                cursor = self._connection.execute("SELECT currval(%s::regclass)", (name,))
            else:
                cursor = self._connection.execute("SELECT lastval()")
            row = cursor.fetchone()
        except psycopg.Error:
            return None
        return row[0] if row else None

    def close(self) -> None:
        self._connection.close()
