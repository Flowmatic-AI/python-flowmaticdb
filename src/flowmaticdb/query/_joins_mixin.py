from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from flowmaticdb.query._join import Join
from flowmaticdb.query.enums import JoinEnum
from flowmaticdb.query.expressions import SqlABC

if TYPE_CHECKING:
    from flowmaticdb.query._select import SelectQuery


class JoinsMixin:
    joins: list[Any]

    def left_join(self, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.LEFT_JOIN, table, alias)

    def left_join_table(self, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.LEFT_JOIN, table, alias)

    def left_join_sub_query(self, query: SelectQuery, alias: str) -> Join:
        from flowmaticdb.query.expressions import SubQuery
        sq = SubQuery(query, alias)
        return self._add_join(JoinEnum.LEFT_JOIN, sq)

    def left_join_lateral(self, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.LEFT_JOIN_LATERAL, table, alias)

    def left_join_lateral_table(self, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.LEFT_JOIN_LATERAL, table, alias)

    def left_join_lateral_sub_query(self, query: SelectQuery, alias: str) -> Join:
        from flowmaticdb.query.expressions import SubQuery
        sq = SubQuery(query, alias)
        return self._add_join(JoinEnum.LEFT_JOIN_LATERAL, sq)

    def inner_join(self, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.INNER_JOIN, table, alias)

    def inner_join_table(self, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.INNER_JOIN, table, alias)

    def inner_join_sub_query(self, query: SelectQuery, alias: str) -> Join:
        from flowmaticdb.query.expressions import SubQuery
        sq = SubQuery(query, alias)
        return self._add_join(JoinEnum.INNER_JOIN, sq)

    def inner_join_lateral(self, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.INNER_JOIN_LATERAL, table, alias)

    def inner_join_lateral_table(self, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.INNER_JOIN_LATERAL, table, alias)

    def inner_join_lateral_sub_query(self, query: SelectQuery, alias: str) -> Join:
        from flowmaticdb.query.expressions import SubQuery
        sq = SubQuery(query, alias)
        return self._add_join(JoinEnum.INNER_JOIN_LATERAL, sq)

    def cross_join(self, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.CROSS_JOIN, table, alias)

    def cross_join_table(self, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.CROSS_JOIN, table, alias)

    def cross_join_sub_query(self, query: SelectQuery, alias: str) -> Join:
        from flowmaticdb.query.expressions import SubQuery
        sq = SubQuery(query, alias)
        return self._add_join(JoinEnum.CROSS_JOIN, sq)

    def cross_join_lateral(self, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.CROSS_JOIN_LATERAL, table, alias)

    def cross_join_lateral_table(self, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.CROSS_JOIN_LATERAL, table, alias)

    def cross_join_lateral_sub_query(self, query: SelectQuery, alias: str) -> Join:
        from flowmaticdb.query.expressions import SubQuery
        sq = SubQuery(query, alias)
        return self._add_join(JoinEnum.CROSS_JOIN_LATERAL, sq)

    def outer_apply(self, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.LEFT_JOIN_LATERAL, table, alias)

    def outer_apply_table(self, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.LEFT_JOIN_LATERAL, table, alias)

    def outer_apply_sub_query(self, query: SelectQuery, alias: str) -> Join:
        from flowmaticdb.query.expressions import SubQuery
        sq = SubQuery(query, alias)
        return self._add_join(JoinEnum.LEFT_JOIN_LATERAL, sq)

    def cross_apply(self, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.INNER_JOIN_LATERAL, table, alias)

    def cross_apply_table(self, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        return self._add_join(JoinEnum.INNER_JOIN_LATERAL, table, alias)

    def cross_apply_sub_query(self, query: SelectQuery, alias: str) -> Join:
        from flowmaticdb.query.expressions import SubQuery
        sq = SubQuery(query, alias)
        return self._add_join(JoinEnum.INNER_JOIN_LATERAL, sq)

    def join(self, sql: Any) -> Self:
        self.joins.append(sql)
        return self

    def _add_join(self, join_type: JoinEnum, table: str | list[str] | SqlABC, alias: str | None = None) -> Join:
        if alias:
            from flowmaticdb.query.expressions import Alias
            table = Alias(table, alias)
        j = Join(join=join_type, table=table)
        self.joins.append(j)
        return j
