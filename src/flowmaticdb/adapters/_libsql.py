from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import libsql

from flowmaticdb import AdapterError
from flowmaticdb._json import encode_json
from flowmaticdb._threading import ThreadLocalStore
from flowmaticdb.adapters._base import AdapterABC
from flowmaticdb.result import LibSQLResult, ResultABC

if TYPE_CHECKING:
    from flowmaticdb import QueryWithParams
    from flowmaticdb.dialects import DialectABC

_DRIVER_ERRORS = (libsql.Error, ValueError)
"""What a failing statement raises.

The driver surfaces SQL failures -- unknown table, syntax error, constraint
violation, readonly database -- as a plain :class:`ValueError`, and keeps
``libsql.Error`` for the few paths that raise its own class. Catching only the
latter would let every real query error past the debug callback."""


def _is_memory_database(database_name: str) -> bool:
    if database_name in ("", ":memory:"):
        return True

    return database_name.startswith("file:") and "mode=memory" in database_name


def _cast_param(dialect: DialectABC, value: Any) -> Any:
    """Serialize what the driver cannot bind.

    Bindable parameters are limited to NULL, int, float, str and bytes -- a
    temporal or a document reaches the driver as ``Unsupported parameter type``
    -- so those are rendered here instead. Temporals use ISO-8601 with a space
    separator, which keeps microseconds and the UTC offset (both of which the
    dialect's SQL-literal format drops) while staying readable to the engine's
    own date/time functions."""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return encode_json(value)
    return dialect.cast_to_driver(value)


class LibSQLAdapter(AdapterABC):
    def __init__(
        self,
        database_name: str = ":memory:",
        startup_queries: list[str] | None = None,
        options: dict[str, Any] | None = None,
        debug_callback: Callable[[str, float, str | None], None] | None = None,
        max_concurrent_connections: int | None = None,
        acquire_connection_timeout: float | None = None,
    ) -> None:
        super().__init__(
            driver_name="libsql",
            database_name=database_name,
            startup_queries=startup_queries,
            options=options,
            debug_callback=debug_callback,
            max_concurrent_connections=max_concurrent_connections,
            acquire_connection_timeout=acquire_connection_timeout,
        )
        # Read once: every result set built by this adapter answers to it, and
        # the two query paths have to agree.
        self._auto_cast_column_types: bool = self._options.get("auto_cast_column_types", True)
        shared = _is_memory_database(database_name)
        self._connections: ThreadLocalStore[libsql.Connection] = ThreadLocalStore(
            shared_across_threads=shared,
            on_thread_exit=self._close_connection,
            max_values=max_concurrent_connections,
            acquire_timeout=acquire_connection_timeout,
        )
        self._statement_lock: AbstractContextManager[Any] = threading.RLock() if shared else nullcontext()
        self._connect()

    @property
    def _connection(self) -> libsql.Connection:
        connection = self._connections.current()
        if connection is not None:
            return connection

        self._ensure_not_closed()
        self._close_orphaned_connections()
        self._connect()
        return self._connections.require()

    def _close_connection(self, connection: libsql.Connection) -> None:
        # Closing twice is safe; every other call on a closed handle is not --
        # see is_connected().
        with contextlib.suppress(*_DRIVER_ERRORS):
            connection.close()

    def _close_orphaned_connections(self) -> None:
        for connection in self._connections.take_orphaned():
            self._close_connection(connection)

    def connection_count(self) -> int:
        return self._connections.count()

    def _connect(self) -> None:
        # The slot is claimed before the handle is opened -- opening first and
        # counting after is exactly what the limit exists to prevent.
        with self._connections.reserve():
            self._connections.set(self._open_connection())
            self._closed = False

        self._exec_startup_queries()

    def _open_connection(self) -> libsql.Connection:
        if "create_functions" in self._options:
            raise AdapterError("user-defined SQL functions are not supported by the libsql driver")

        db_name = self._database_name
        read_only = self._options.get("read_only", False)

        connect_options: dict[str, Any] = {
            "database": f"file:{db_name}?mode=ro" if read_only else db_name,
            "timeout": self._options.get("timeout", 5.0),
            # None is autocommit: transactions are opened by the SQL this
            # library emits, so the driver must not open one of its own.
            "isolation_level": self._options.get("isolation_level", None),
            "_check_same_thread": self._options.get(
                "check_same_thread",
                not self._connections.shared_across_threads,
            ),
            "_uri": read_only or db_name.startswith("file:"),
        }

        # Encryption is a connect-time argument here, not a PRAGMA.
        if "encryption_key" in self._options:
            connect_options["encryption_key"] = self._options["encryption_key"]

        # Embedded-replica settings; only meaningful against a remote database.
        if "sync_url" in self._options:
            connect_options["sync_url"] = self._options["sync_url"]
        if "sync_interval" in self._options:
            connect_options["sync_interval"] = self._options["sync_interval"]
        if "offline" in self._options:
            connect_options["offline"] = self._options["offline"]
        if "auth_token" in self._options:
            connect_options["auth_token"] = self._options["auth_token"]

        connection = libsql.connect(**connect_options)

        connection.execute(f"PRAGMA journal_mode = {self._options.get('journal_mode', 'WAL')}")
        connection.execute(f"PRAGMA busy_timeout = {int(self._options.get('busy_timeout', 500))}")

        if "encoding" in self._options:
            connection.execute(f"PRAGMA encoding = '{self._options['encoding']}'")

        if self._options.get("foreign_keys", True):
            connection.execute("PRAGMA foreign_keys = ON")

        return connection

    def _disconnect(self) -> None:
        connection = self._connections.discard()
        if connection is not None:
            connection.close()

    def is_connected(self) -> bool:
        """Whether this thread holds a live handle.

        Unlike the other drivers this one cannot be probed: reading any
        attribute of a closed handle aborts inside the extension module rather
        than raising, and that abort is not catchable as an ordinary exception.
        So the store is the record of truth instead -- every path that closes a
        handle drops it from the store in the same breath, which leaves a stored
        handle open by construction. A caller that closes the handle it got from
        :meth:`get_connection` is the one case this cannot see."""
        return self._connections.current() is not None

    def version(self) -> str:
        try:
            with self._statement_lock:
                cursor = self._connection.execute("SELECT sqlite_version()")
                row = cursor.fetchone()
            return str(row[0]) if row else "0"
        except _DRIVER_ERRORS:
            return "0"

    def sync(self) -> None:
        """Pull the remote database into the local replica.

        Only does anything on a connection opened with ``sync_url``; a purely
        local database has nothing to sync and the driver says so."""
        with self._statement_lock:
            self._connection.sync()

    def exec(self, query: str) -> None:
        start = time.time()
        error: str | None = None
        try:
            with self._statement_lock:
                self._connection.execute(query)
        except _DRIVER_ERRORS as e:
            error = str(e)
            raise
        finally:
            duration = time.time() - start
            self._debug(query, duration, error)

    def query(self, query: str) -> ResultABC:
        start = time.time()
        error: str | None = None
        try:
            with self._statement_lock:
                cursor = self._connection.execute(query)
            return LibSQLResult(cursor, auto_cast_column_types=self._auto_cast_column_types)
        except _DRIVER_ERRORS as e:
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
        params = [_cast_param(dialect, param) for param in query_with_params.params]

        start = time.time()
        error: str | None = None
        try:
            with self._statement_lock:
                if emulate_prepare:
                    sql_full = query_with_params.to_sql(dialect)
                    cursor = self._connection.execute(sql_full)
                else:
                    cursor = self._connection.execute(sql, params)
            return LibSQLResult(cursor, auto_cast_column_types=self._auto_cast_column_types)
        except _DRIVER_ERRORS as e:
            error = str(e)
            raise
        finally:
            duration = time.time() - start
            self._debug(query_with_params.to_sql(dialect), duration, error)

    @property
    def in_transaction(self) -> bool:
        return bool(self._connection.in_transaction)

    def last_insert_id(self, name: str | None = None) -> int | str | None:
        with self._statement_lock:
            cursor = self._connection.execute("SELECT last_insert_rowid()")
            row = cursor.fetchone()
        if row is None:
            return None
        last_insert_id: int | str | None = row[0]
        return last_insert_id

    def get_connection(self) -> Any:
        return self._connection

    def close(self) -> None:
        optimize = self._options.get("optimize", False)
        persistent = self._options.get("persistent", False)

        if not optimize and persistent:
            return

        with self._statement_lock:
            connections = self._connections.values() if persistent else self._connections.take_all()

            for connection in connections:
                if optimize:
                    with contextlib.suppress(*_DRIVER_ERRORS):
                        connection.execute("PRAGMA optimize")

                if not persistent:
                    with contextlib.suppress(*_DRIVER_ERRORS):
                        connection.close()

        if not persistent:
            self._closed = True
