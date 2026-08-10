from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flowmaticdb.query._ddl_mixins import AltersMixin
from flowmaticdb.query._query import MultiQuery
from flowmaticdb.query.ddl import AlterABC

if TYPE_CHECKING:
    from flowmaticdb import QueryWithParams
    from flowmaticdb.database import DatabaseABC
    from flowmaticdb.dialects import DialectABC


class AlterTableQuery(MultiQuery, AltersMixin):
    def __init__(self, dialect: DialectABC, table: str | list[str], database: DatabaseABC) -> None:
        super().__init__(dialect, table, database)

        self._alters: list[AlterABC] = []

    def to_query_with_params(self) -> list[QueryWithParams]:
        return self._dialect.alter_table(
            table=self._table,
            alters=self._alters,
        )

    def explain(self, emulate_prepare: bool = False) -> list[dict[str, Any]]:
        return []
