from __future__ import annotations

from typing import TYPE_CHECKING

from flowmaticdb._query_with_params import QueryWithParams
from flowmaticdb.query._query import Query
from flowmaticdb.query._simple_mixins import LastInsertIdMixin, OnConflictMixin, ReturningMixin, ValuesMixin
from flowmaticdb.result._base import ResultABC

if TYPE_CHECKING:
    from flowmaticdb.database._abc import DatabaseABC
    from flowmaticdb.dialects._base import DialectABC


class InsertQuery(Query, ValuesMixin, OnConflictMixin, ReturningMixin, LastInsertIdMixin):
    def __init__(self, dialect: DialectABC, table: str | list[str], database: DatabaseABC) -> None:
        super().__init__(dialect, table, database=database)

    def to_query_with_params(self) -> QueryWithParams:
        return self._dialect.insert(
            table=self._table,
            values=self._values_list,
            on_conflict=self._on_conflict,
            returning=self._returning_list,
            last_insert_id=self._last_insert_id_col,
        )

    def execute(self, emulate_prepare: bool = False) -> ResultABC:
        return super().execute(emulate_prepare)  # type: ignore[return-value]
