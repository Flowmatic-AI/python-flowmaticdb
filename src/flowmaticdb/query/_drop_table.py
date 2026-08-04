from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from flowmaticdb._query_with_params import QueryWithParams
from flowmaticdb.query._ddl_mixins import IfExistsMixin
from flowmaticdb.query._query import Query
from flowmaticdb.result import ResultABC

if TYPE_CHECKING:
    from flowmaticdb.database import DatabaseABC
    from flowmaticdb.dialects import DialectABC


class DropTableQuery(Query, IfExistsMixin):
    def __init__(self, dialect: DialectABC, table: str | list[str], database: DatabaseABC) -> None:
        super().__init__(dialect, table, database)

        self._if_exists: bool = False

    def table(self, table: str | list[str]) -> Self:
        self._table = table
        return self

    def to_query_with_params(self) -> QueryWithParams:
        if_exists = self._if_exists
        return self._dialect.drop_table(
            if_exists=if_exists,
            table=self._table,
        )

    def execute(self, emulate_prepare: bool = False) -> ResultABC:
        result = super().execute(emulate_prepare)
        if not isinstance(result, ResultABC):
            msg = "Expected a single ResultABC, got a list"
            raise TypeError(msg)
        return result

    def explain(self, emulate_prepare: bool = False) -> list[dict[str, Any]]:
        return []
