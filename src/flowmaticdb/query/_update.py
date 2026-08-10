from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flowmaticdb.query._query import Query
from flowmaticdb.query._simple_mixins import ReturningMixin, UpdatesMixin
from flowmaticdb.query._where_mixin import WhereMixin
from flowmaticdb.result import ResultABC

if TYPE_CHECKING:
    from flowmaticdb._query_with_params import QueryWithParams
    from flowmaticdb.database import DatabaseABC
    from flowmaticdb.dialects import DialectABC


class UpdateQuery(Query, WhereMixin, UpdatesMixin, ReturningMixin):
    def __init__(self, dialect: DialectABC, table: str | list[str], database: DatabaseABC) -> None:
        super().__init__(dialect, table, database)

        self.where: list[Any] = []
        self._updates_dict: dict[str, Any] = {}
        self._returning_list: list[Any] | None = None

    def to_query_with_params(self) -> QueryWithParams:
        return self._dialect.update(
            table=self._table,
            updates=self._updates_dict,
            where=self.where,
            returning=self._returning_list,
        )

    def execute(self, emulate_prepare: bool = False) -> ResultABC:
        return self._database.query_with_params(self.to_query_with_params(), emulate_prepare)

