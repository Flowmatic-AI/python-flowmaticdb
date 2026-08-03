from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from flowmaticdb.query._join import Join
from flowmaticdb.query.enums._join import JoinEnum
from flowmaticdb.query.expressions._sql import SqlABC

if TYPE_CHECKING:
    from flowmaticdb.query._select import SelectQuery


class JoinsMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.joins: list[Any] = []

    def left_join(self, table: str | list[str], alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.LEFT_JOIN, table, alias)

    def left_join_table(self, table: str | list[str], alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.LEFT_JOIN, table, alias)

    def left_join_sub_query(self, query: SelectQuery, alias: str) -> Join:
        from flowmaticdb.query.expressions._sub_query import SubQuery
        sq = SubQuery(query, alias)
        return self._add_join(JoinEnum.LEFT_JOIN, sq)

    def left_join_lateral(self, query: SelectQuery, alias: str) -> Join:
        from flowmaticdb.query.expressions._sub_query import SubQuery
        sq = SubQuery(query, alias)
        return self._add_join(JoinEnum.LEFT_JOIN_LATERAL, sq)

    def inner_join(self, table: str | list[str], alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.INNER_JOIN, table, alias)

    def inner_join_lateral(self, query: SelectQuery, alias: str) -> Join:
        from flowmaticdb.query.expressions._sub_query import SubQuery
        sq = SubQuery(query, alias)
        return self._add_join(JoinEnum.INNER_JOIN_LATERAL, sq)

    def cross_join(self, table: str | list[str], alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.CROSS_JOIN, table, alias)

    def cross_join_lateral(self, query: SelectQuery, alias: str) -> Join:
        from flowmaticdb.query.expressions._sub_query import SubQuery
        sq = SubQuery(query, alias)
        return self._add_join(JoinEnum.CROSS_JOIN_LATERAL, sq)

    def join(self, sql: Any) -> Self:
        self.joins.append(sql)
        return self

    def _add_join(self, join_type: JoinEnum, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        if alias:
            from flowmaticdb.query.expressions._alias import Alias
            table = Alias(table, alias)
        j = Join(join=join_type, table=table)
        self.joins.append(j)
        return j
