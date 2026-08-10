from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from flowmaticdb._query_with_params import QueryWithParams
from flowmaticdb.result import ResultABC

if TYPE_CHECKING:
    from flowmaticdb.database import DatabaseABC
    from flowmaticdb.dialects import DialectABC
    from flowmaticdb.query.expressions import Alias, SubQuery


class Query(ABC):
    def __init__(self, dialect: DialectABC, table: str | list[str] | Alias | SubQuery, database: DatabaseABC) -> None:
        super().__init__()
        
        self._dialect = dialect
        self._table = table
        self._database = database

    @property
    def dialect(self) -> DialectABC:
        return self._dialect

    @abstractmethod
    def to_query_with_params(self) -> QueryWithParams | list[QueryWithParams]:
        ...

    def to_sql(self) -> str | list[str]:
        qwp = self.to_query_with_params()

        if isinstance(qwp, list):
            return [q.to_sql(self._dialect) for q in qwp]
        
        return qwp.to_sql(self._dialect)

    def execute(self, emulate_prepare: bool = False) -> ResultABC | list[ResultABC]:
        qwp = self.to_query_with_params()

        if isinstance(qwp, list):
            return [self._database.query_with_params(q, emulate_prepare) for q in qwp]

        return self._database.query_with_params(qwp, emulate_prepare)

    def explain(self, emulate_prepare: bool = False) -> list[dict[str, Any]]:
        qwp = self.to_query_with_params()
        if isinstance(qwp, list):
            results: list[dict[str, Any]] = []

            for q in qwp:
                explain_qwp = QueryWithParams(
                    query=f"EXPLAIN {q.query}",
                    params=list(q.params),
                )

                result = self._database.query_with_params(explain_qwp, emulate_prepare)
                results.extend(result.fetch_dicts())
            return results
        
        explain_qwp = QueryWithParams(
            query=f"EXPLAIN {qwp.query}",
            params=list(qwp.params),
        )

        result = self._database.query_with_params(explain_qwp, emulate_prepare)

        return result.fetch_dicts()
