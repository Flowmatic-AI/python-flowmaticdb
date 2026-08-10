from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flowmaticdb.query.expressions._sql import SqlABC

if TYPE_CHECKING:
    from flowmaticdb.dialects import DialectABC


class Expression(SqlABC):
    def __init__(self, sql: str, params: list[Any] | None = None) -> None:
        self._sql = sql
        self._params = params or []

    def sql(self, dialect: DialectABC) -> str:
        return self._sql

    def params(self, dialect: DialectABC) -> list[Any]:
        return list(self._params)

    def raw_sql(self, dialect: DialectABC) -> str:
        from flowmaticdb._query_with_params import QueryWithParams
        qwp = QueryWithParams(query=self._sql, params=self._params)
        return qwp.to_sql(dialect)
