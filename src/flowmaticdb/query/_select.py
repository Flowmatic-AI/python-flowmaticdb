from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

from flowmaticdb.query._having_mixin import HavingMixin
from flowmaticdb.query._joins_mixin import JoinsMixin
from flowmaticdb.query._query import Query
from flowmaticdb.query._simple_mixins import (
    ColumnsMixin,
    DistinctMixin,
    GroupByMixin,
    LimitMixin,
    OffsetMixin,
    OrderByMixin,
    UnionMixin,
)
from flowmaticdb.query._where_mixin import WhereMixin
from flowmaticdb.result._base import ResultABC

if TYPE_CHECKING:
    from flowmaticdb._query_with_params import QueryWithParams
    from flowmaticdb.database._abc import DatabaseABC
    from flowmaticdb.dialects._base import DialectABC
    from flowmaticdb.query.expressions._alias import Alias
    from flowmaticdb.query.expressions._sub_query import SubQuery


class SelectQuery(
    Query, WhereMixin, HavingMixin, JoinsMixin,
    ColumnsMixin, DistinctMixin, GroupByMixin,
    OrderByMixin, LimitMixin, OffsetMixin, UnionMixin,
):
    def __init__(self, dialect: DialectABC, table: str | list[str] | Alias | SubQuery, database: DatabaseABC) -> None:
        super().__init__(dialect, table, database=database)

    def table(self, table: str | list[str] | Alias | SubQuery) -> Self:
        self._table = table
        return self

    def to_query_with_params(self) -> QueryWithParams:
        return self._dialect.select(
            distinct=self._distinct,
            columns=self._columns_list,
            table=self._table,
            joins=self.joins,
            where=self.where,
            group_by=self._group_by_cols,
            having=self.having,
            order_by=self._order_by_list,
            limit=self._limit_val,
            offset=self._offset_val,
            unions=self._unions_list,
        )

    def execute(self, emulate_prepare: bool = False) -> ResultABC:
        return cast(ResultABC, super().execute(emulate_prepare))

    def count(self, emulate_prepare: bool = False) -> int:
        inner_qwp = self.to_query_with_params()
        inner_sql = inner_qwp.query
        count_sql = f"SELECT count(*) FROM ({inner_sql}) AS _count"
        count_qwp = QueryWithParams(query=count_sql, params=list(inner_qwp.params))
        result = self._database.query_with_params(count_qwp, emulate_prepare)
        row = result.fetch_dict()
        if row:
            for val in row.values():
                return int(val)
        return 0
