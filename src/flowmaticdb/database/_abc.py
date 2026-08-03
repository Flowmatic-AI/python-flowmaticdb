from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from flowmaticdb.result._base import ResultABC

if TYPE_CHECKING:
    from flowmaticdb._query_with_params import QueryWithParams
    from flowmaticdb.adapters._base import AdapterABC
    from flowmaticdb.dialects._base import DialectABC
    from flowmaticdb.query._alter_table import AlterTableQuery
    from flowmaticdb.query._create_table import CreateTableQuery
    from flowmaticdb.query._delete import DeleteQuery
    from flowmaticdb.query._drop_table import DropTableQuery
    from flowmaticdb.query._insert import InsertQuery
    from flowmaticdb.query._select import SelectQuery
    from flowmaticdb.query._update import UpdateQuery
    from flowmaticdb.query.expressions._alias import Alias
    from flowmaticdb.query.expressions._sub_query import SubQuery


class DatabaseABC:
    def __init__(self, adapter: AdapterABC, dialect: DialectABC) -> None:
        self._adapter = adapter
        self._dialect = dialect

    @property
    def adapter(self) -> AdapterABC:
        return self._adapter

    @property
    def dialect(self) -> DialectABC:
        return self._dialect

    def exec(self, query: str) -> None:
        return self._adapter.exec(query)

    def query(self, query: str) -> ResultABC:
        return self._adapter.query(query)

    def prepared(self, query: str, params: list[Any], emulate: bool = False) -> ResultABC:
        from flowmaticdb._query_with_params import QueryWithParams
        qwp = QueryWithParams(query=query, params=params)
        return self._adapter.query_with_params(self._dialect, qwp, emulate)

    def query_with_params(self, qwp: QueryWithParams, emulate: bool = False) -> ResultABC:
        return self._adapter.query_with_params(self._dialect, qwp, emulate)

    def begin_transaction(self, name: str | None = None) -> None:
        if name:
            qwp = self._dialect.begin_savepoint(name)
            self._adapter.exec(qwp.query)
        else:
            self._adapter.begin_transaction()

    def commit_transaction(self, release_savepoints: bool = False, name: str | None = None) -> None:
        if name:
            qwp = self._dialect.commit_savepoint(name)
            self._adapter.exec(qwp.query)
        else:
            self._adapter.commit_transaction()

    def rollback_transaction(self, release_savepoints: bool = False, name: str | None = None) -> None:
        if name:
            qwp = self._dialect.rollback_savepoint(name)
            self._adapter.exec(qwp.query)
        else:
            self._adapter.rollback_transaction()

    @property
    def in_transaction(self) -> bool:
        return self._adapter.in_transaction

    def transaction(self, callback: Callable[..., Any], release_savepoints: bool = False, name: str | None = None) -> Any:
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
        from flowmaticdb.query._select import SelectQuery
        return SelectQuery(self._dialect, table, database=self)

    def select_table(self, table: str | list[str], alias: str | None = None) -> SelectQuery:
        from flowmaticdb.query._select import SelectQuery
        if alias:
            from flowmaticdb.query.expressions._alias import Alias
            return SelectQuery(self._dialect, Alias(table, alias), database=self)
        
        return SelectQuery(self._dialect, table, database=self)

    def select_sub_query(self, sub_query: Any, alias: str) -> SelectQuery:
        from flowmaticdb.query._select import SelectQuery
        from flowmaticdb.query.expressions._sub_query import SubQuery
        sq = SubQuery(sub_query, alias)
        return SelectQuery(self._dialect, sq, database=self)

    def insert(self, table: str | list[str]) -> InsertQuery:
        from flowmaticdb.query._insert import InsertQuery
        return InsertQuery(self._dialect, table, database=self)

    def update(self, table: str | list[str]) -> UpdateQuery:
        from flowmaticdb.query._update import UpdateQuery
        return UpdateQuery(self._dialect, table, database=self)

    def delete(self, table: str | list[str]) -> DeleteQuery:
        from flowmaticdb.query._delete import DeleteQuery
        return DeleteQuery(self._dialect, table, database=self)

    def create_table(self, table: str | list[str]) -> CreateTableQuery:
        from flowmaticdb.query._create_table import CreateTableQuery
        return CreateTableQuery(self._dialect, table, database=self)

    def alter_table(self, table: str | list[str]) -> AlterTableQuery:
        from flowmaticdb.query._alter_table import AlterTableQuery
        return AlterTableQuery(self._dialect, table, database=self)

    def drop_table(self, table: str | list[str]) -> DropTableQuery:
        from flowmaticdb.query._drop_table import DropTableQuery
        return DropTableQuery(self._dialect, table, database=self)
