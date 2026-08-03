from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from flowmaticdb.result._base import ResultABC

if TYPE_CHECKING:
    from flowmaticdb.database._abc import DatabaseABC
    from flowmaticdb.dialects._base import DialectABC
    from flowmaticdb.query._delete import DeleteQuery
    from flowmaticdb.query._insert import InsertQuery
    from flowmaticdb.query._select import SelectQuery
    from flowmaticdb.query._update import UpdateQuery


class Table:
    def __init__(self, database: DatabaseABC, dialect: DialectABC, table: str) -> None:
        self._database = database
        self._dialect = dialect
        self._table = table

    def select(self, columns: list[Any] | None = None) -> SelectQuery:
        q = self._database.select(self._table)
        if columns:
            q.columns(columns)
        return q

    def insert(self, *values: dict[str, Any]) -> InsertQuery:
        q = self._database.insert(self._table)
        if values:
            q.values(*values)
        return q

    def select_or_insert(self, columns: list[Any], values: list[Any], **kwargs: Any) -> ResultABC:
        q = self.select(columns).where_equals(**{columns[0]: values[0]})
        result = q.execute()
        row = result.fetch_dict()
        if row:
            return result
        return self.insert(dict(zip(columns, values))).execute()

    def insert_or_ignore(self, columns: list[Any], values: list[Any], **kwargs: Any) -> ResultABC:
        q = self._database.insert(self._table)
        q.values(dict(zip(columns, values)))
        conflict = kwargs.get("conflict", columns[0])
        q.on_conflict_do_nothing(conflict)
        return self._database.query_with_params(q.to_query_with_params())

    def insert_or_update(self, columns: list[Any], values: list[Any], **kwargs: Any) -> ResultABC:
        q = self._database.insert(self._table)
        q.values(dict(zip(columns, values)))
        conflict = kwargs.get("conflict", columns[0])
        updates = kwargs.get("updates", dict(zip(columns, values)))
        q.on_conflict_do_update(conflict, updates)
        return self._database.query_with_params(q.to_query_with_params())

    def update(self, values: dict[str, Any]) -> UpdateQuery:
        q = self._database.update(self._table)
        q.updates(values)
        return q

    def delete(self) -> DeleteQuery:
        return self._database.delete(self._table)

    def create(self, callback: Callable[..., Any] | None = None) -> ResultABC:
        q = self._database.create_table(self._table)
        if callback:
            callback(q)
        return q.execute()

    def create_if_not_exists(self, callback: Callable[..., Any] | None = None) -> ResultABC:
        q = self._database.create_table(self._table)
        q.if_not_exists()
        if callback:
            callback(q)
        return q.execute()

    def truncate(self) -> None:
        qwp = self._dialect.delete(table=self._table, where=None, returning=None)
        self._database.query_with_params(qwp)

    def drop(self) -> ResultABC:
        return self._database.drop_table(self._table).execute()

    def drop_if_exists(self) -> ResultABC:
        q = self._database.drop_table(self._table)
        q.if_exists()
        return q.execute()

    def columns(self) -> list[str]:
        adapter_driver = self._database.adapter.driver_name
        if adapter_driver == 'sqlite':
            result = self._database.query(f"PRAGMA table_info({self._table})")
            rows = result.fetch_dicts()
            return [row['name'] for row in rows]
        result = self._database.query(
            f"SELECT column_name FROM information_schema.columns WHERE table_name = '{self._table}'"
        )
        rows = result.fetch_dicts()
        return [row['column_name'] for row in rows]

    def is_empty(self) -> bool:
        result = self._database.query(f"SELECT count(*) AS cnt FROM {self._table}")
        row = result.fetch_dict()
        return row is None or row.get('cnt', 0) == 0
