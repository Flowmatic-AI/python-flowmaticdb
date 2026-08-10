from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from flowmaticdb.query._ddl_mixins import IfExistsMixin
from flowmaticdb.query._query import SingleQuery

if TYPE_CHECKING:
    from flowmaticdb import QueryWithParams
    from flowmaticdb.database import DatabaseABC
    from flowmaticdb.dialects import DialectABC


class DropTableQuery(SingleQuery, IfExistsMixin):
    def __init__(self, dialect: DialectABC, table: str | list[str], database: DatabaseABC) -> None:
        super().__init__(dialect, table, database)

        self._if_exists: bool = False

    def table(self, table: str | list[str]) -> Self:
        self._table = table
        return self

    def to_query_with_params(self) -> QueryWithParams:
        return self._dialect.drop_table(
            if_exists=self._if_exists,
            table=self._table,
        )

    def explain(self, emulate_prepare: bool = False) -> list[dict[str, Any]]:
        return []
