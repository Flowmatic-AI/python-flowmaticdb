from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Self, TypeVar

from flowmaticdb._threading import ThreadLocalStore
from flowmaticdb.result import ResultABC

T = TypeVar("T")

if TYPE_CHECKING:
    from flowmaticdb import QueryWithParams
    from flowmaticdb.adapters import AdapterABC
    from flowmaticdb.database._table import Table
    from flowmaticdb.dialects import DialectABC
    from flowmaticdb.query import (
        AlterTableQuery,
        CreateTableQuery,
        DeleteQuery,
        DropTableQuery,
        InsertQuery,
        SelectQuery,
        UpdateQuery,
    )
    from flowmaticdb.query.expressions import Alias, SubQuery


class DatabaseABC:
    def __init__(self, adapter: AdapterABC, dialect: DialectABC, ensure_always_connected: bool = False) -> None:
        self._adapter = adapter
        self._dialect = dialect
        self._ensure_always_connected = ensure_always_connected
        self._savepoint_stacks: ThreadLocalStore[list[str]] = ThreadLocalStore()

    @property
    def _savepoints(self) -> list[str]:
        stack = self._savepoint_stacks.current()
        if stack is None:
            stack = []
            self._savepoint_stacks.set(stack)
        return stack

    @property
    def adapter(self) -> AdapterABC:
        return self._adapter

    @property
    def dialect(self) -> DialectABC:
        return self._dialect

    @property
    def ensure_always_connected(self) -> bool:
        return self._ensure_always_connected

    def exec(self, query: str) -> None:
        if self._ensure_always_connected:
            self.reconnect_if_disconnected()

        return self._adapter.exec(query)

    def query(self, query: str) -> ResultABC:
        if self._ensure_always_connected:
            self.reconnect_if_disconnected()

        return self._adapter.query(query)

    def prepared(self, query: str, params: list[Any] | None = None, emulate: bool = False) -> ResultABC:
        from flowmaticdb._query_with_params import QueryWithParams
        qwp = QueryWithParams(query=query, params=params or [])
        return self.query_with_params(qwp, emulate)

    def query_with_params(self, qwp: QueryWithParams, emulate: bool = False) -> ResultABC:
        if self._ensure_always_connected:
            self.reconnect_if_disconnected()

        if len(qwp.params) > 0:
            return self._adapter.query_with_params(self._dialect, qwp, emulate)
        return self._adapter.query(qwp.query)

    def begin_transaction(self, name: str | None = None) -> None:
        if not self.in_transaction:
            qwp = self._dialect.begin_transaction(name)
            self._adapter.begin_transaction(qwp.query)
            return

        name = name or f"savepoint_{len(self._savepoints) + 1}"
        self._savepoints.append(name)
        qwp = self._dialect.begin_savepoint(name)
        self._adapter.begin_savepoint(qwp.query)

    def commit_transaction(self, release_savepoints: bool = False, name: str | None = None) -> None:
        if not self.in_transaction:
            return

        if release_savepoints or len(self._savepoints) == 0:
            self._savepoints.clear()
            qwp = self._dialect.commit_transaction(name)
            self._adapter.commit_transaction(qwp.query)
            return

        qwp = self._dialect.commit_savepoint(self._savepoints.pop())
        self._adapter.commit_savepoint(qwp.query)

    def rollback_transaction(self, release_savepoints: bool = False, name: str | None = None) -> None:
        if not self.in_transaction:
            return

        if release_savepoints or len(self._savepoints) == 0:
            self._savepoints.clear()
            qwp = self._dialect.rollback_transaction(name)
            self._adapter.rollback_transaction(qwp.query)
            return

        qwp = self._dialect.rollback_savepoint(self._savepoints.pop())
        self._adapter.rollback_savepoint(qwp.query)

    @property
    def in_transaction(self) -> bool:
        return self._adapter.in_transaction

    def transaction(self, callback: Callable[[Self], T], release_savepoints: bool = False, name: str | None = None) -> T:
        self.begin_transaction(name=name)
        try:
            result = callback(self)
            self.commit_transaction(release_savepoints=release_savepoints, name=name)
            return result
        except Exception:
            self.rollback_transaction(release_savepoints=release_savepoints, name=name)
            raise

    def last_insert_id(self, name: str | None = None) -> int | str | None:
        return self._adapter.last_insert_id(name)

    def select(self, table: str | list[str] | Alias | SubQuery) -> SelectQuery:
        from flowmaticdb.query import SelectQuery
        return SelectQuery(self._dialect, table, database=self)

    def select_table(self, table: str | list[str], alias: str | None = None) -> SelectQuery:
        if alias:
            from flowmaticdb.query.expressions import Alias
            return self.select(Alias(table, alias))

        return self.select(table)

    def select_sub_query(self, sub_query: Any, alias: str) -> SelectQuery:
        from flowmaticdb.query.expressions import SubQuery
        return self.select(SubQuery(sub_query, alias))

    def insert(self, table: str | list[str]) -> InsertQuery:
        from flowmaticdb.query import InsertQuery
        return InsertQuery(self._dialect, table, database=self)

    def update(self, table: str | list[str]) -> UpdateQuery:
        from flowmaticdb.query import UpdateQuery
        return UpdateQuery(self._dialect, table, database=self)

    def delete(self, table: str | list[str]) -> DeleteQuery:
        from flowmaticdb.query import DeleteQuery
        return DeleteQuery(self._dialect, table, database=self)

    def create_table(self, table: str | list[str]) -> CreateTableQuery:
        from flowmaticdb.query import CreateTableQuery
        return CreateTableQuery(self._dialect, table, database=self)

    def alter_table(self, table: str | list[str]) -> AlterTableQuery:
        from flowmaticdb.query import AlterTableQuery
        return AlterTableQuery(self._dialect, table, database=self)

    def drop_table(self, table: str | list[str]) -> DropTableQuery:
        from flowmaticdb.query import DropTableQuery
        return DropTableQuery(self._dialect, table, database=self)

    def table(self, table: str | list[str]) -> Table:
        from flowmaticdb.database._table import Table
        return Table(self, self._dialect, table)

    def close(self) -> None:
        self.adapter.close()
    
    def is_connected(self) -> bool:
        return self.adapter.is_connected()

    def reconnect(self) -> None:
        self._savepoints.clear()
        self.adapter.reconnect()

    def reconnect_if_disconnected(self) -> bool:
        if self.adapter.is_connected():
            return False

        self.reconnect()
        return True

    def get_connection(self) -> Any:
        return self.adapter.get_connection()
