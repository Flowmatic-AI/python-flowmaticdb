from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from flowmaticdb._query_with_params import QueryWithParams
from flowmaticdb.query._ddl_mixins import IfExistsMixin
from flowmaticdb.query._query import Query
from flowmaticdb.result._base import ResultABC

if TYPE_CHECKING:
    from flowmaticdb.database._abc import DatabaseABC
    from flowmaticdb.dialects._base import DialectABC


class DropTableQuery(Query, IfExistsMixin):
    def __init__(self, dialect: DialectABC, table: str | list[str], database: DatabaseABC, *args: Any, **kwargs: Any) -> None:
        kwargs['database'] = database
        super().__init__(dialect, table, *args, **kwargs)

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
        assert isinstance(result, ResultABC), "Expected a single ResultABC, got a list"
        return result
