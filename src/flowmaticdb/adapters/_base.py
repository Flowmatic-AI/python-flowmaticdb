from __future__ import annotations

import contextlib
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from flowmaticdb.result import ResultABC

if TYPE_CHECKING:
    from flowmaticdb._query_with_params import QueryWithParams
    from flowmaticdb.dialects import DialectABC


class AdapterABC(ABC):
    def __init__(
        self,
        driver_name: str,
        database_name: str,
        startup_queries: list[str] | None = None,
        options: dict[str, Any] | None = None,
        debug_callback: Callable[[str, float, str | None], None] | None = None,
    ) -> None:
        self._driver_name = driver_name
        self._database_name = database_name
        self._startup_queries = startup_queries or []
        self._options = options or {}
        self._debug_callback = debug_callback

    def _exec_startup_queries(self) -> None:
        for query in self._startup_queries:
            self.exec(query)

    def _debug(self, sql: str, duration: float, error: str | None = None) -> None:
        if self._debug_callback is not None:
            self._debug_callback(sql, duration, error)

    @property
    def driver_name(self) -> str:
        return self._driver_name

    @property
    def database_name(self) -> str:
        return self._database_name

    @abstractmethod
    def _connect(self) -> None:
        ...

    @abstractmethod
    def _disconnect(self) -> None:
        """Unconditionally drop the driver handle.

        Separate from :meth:`close`, which honours the ``persistent`` option and
        may deliberately leave the handle open."""

    @abstractmethod
    def is_connected(self) -> bool:
        ...

    def reconnect(self) -> None:
        """Throw the current connection away and open a fresh one.

        The old handle is very likely dead already -- that is what makes a
        reconnect necessary -- so failures while dropping it are ignored."""
        with contextlib.suppress(Exception):
            self._disconnect()

        self._connect()

    @abstractmethod
    def version(self) -> str:
        ...

    @abstractmethod
    def exec(self, query: str) -> None:
        ...

    @abstractmethod
    def query(self, query: str) -> ResultABC:
        ...

    @abstractmethod
    def query_with_params(
        self,
        dialect: DialectABC,
        query_with_params: QueryWithParams,
        emulate_prepare: bool = False,
    ) -> ResultABC:
        ...

    @property
    @abstractmethod
    def in_transaction(self) -> bool:
        ...

    def begin_transaction(self, sql: str) -> None:
        if self.in_transaction:
            return
        self.exec(sql)

    def commit_transaction(self, sql: str) -> None:
        if not self.in_transaction:
            return
        self.exec(sql)

    def rollback_transaction(self, sql: str) -> None:
        if not self.in_transaction:
            return
        self.exec(sql)

    def begin_savepoint(self, sql: str) -> None:
        if not self.in_transaction:
            return
        self.exec(sql)

    def commit_savepoint(self, sql: str) -> None:
        if not self.in_transaction:
            return
        self.exec(sql)

    def rollback_savepoint(self, sql: str) -> None:
        if not self.in_transaction:
            return
        self.exec(sql)

    @abstractmethod
    def last_insert_id(self, name: str | None = None) -> int | str | None:
        ...

    @abstractmethod
    def get_connection(self) -> Any:
        ...

    @abstractmethod
    def close(self) -> None:
        ...
