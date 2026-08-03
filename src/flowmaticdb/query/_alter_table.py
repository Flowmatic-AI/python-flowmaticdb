from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flowmaticdb.query._ddl_mixins import AltersMixin
from flowmaticdb.query._query import Query
from flowmaticdb.result._base import ResultABC

if TYPE_CHECKING:
    from flowmaticdb._query_with_params import QueryWithParams
    from flowmaticdb.database._abc import DatabaseABC
    from flowmaticdb.dialects._base import DialectABC


class AlterTableQuery(Query, AltersMixin):
    def __init__(self, dialect: DialectABC, table: str | list[str], database: DatabaseABC, *args: Any, **kwargs: Any) -> None:
        kwargs['database'] = database
        super().__init__(dialect, table, *args, **kwargs)

    def to_query_with_params(self) -> list[QueryWithParams]:
        alters = self._alters
        return self._dialect.alter_table(
            table=self._table,
            alters=alters,
        )

    def to_sql(self) -> list[str]:
        queries_with_params = self.to_query_with_params()
        return [qwp.to_sql(self._dialect) for qwp in queries_with_params]

    def execute(self, emulate_prepare: bool = False) -> list[ResultABC]:
        queries_with_params = self.to_query_with_params()
        return [self._database.query_with_params(qwp, emulate_prepare) for qwp in queries_with_params]

    def explain(self, emulate_prepare: bool = False) -> list[dict[str, Any]]:
        return super().explain(emulate_prepare)
