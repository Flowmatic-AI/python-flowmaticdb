from __future__ import annotations

from typing import TYPE_CHECKING, cast

from flowmaticdb.query._query import Query
from flowmaticdb.query._simple_mixins import ReturningMixin, UpdatesMixin
from flowmaticdb.query._where_mixin import WhereMixin
from flowmaticdb.result._base import ResultABC

if TYPE_CHECKING:
    from flowmaticdb._query_with_params import QueryWithParams
    from flowmaticdb.database._abc import DatabaseABC
    from flowmaticdb.dialects._base import DialectABC


class UpdateQuery(Query, WhereMixin, UpdatesMixin, ReturningMixin):
    def __init__(self, dialect: DialectABC, table: str | list[str], database: DatabaseABC) -> None:
        super().__init__(dialect, table, database=database)

    def to_query_with_params(self) -> QueryWithParams:
        return self._dialect.update(
            table=self._table,
            updates=self._updates_dict,
            where=self.where,
            returning=self._returning_list,
        )
