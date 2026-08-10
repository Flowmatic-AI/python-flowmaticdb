from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flowmaticdb.query._ddl_mixins import (
    ColumnsDefinitionMixin,
    ConstraintsMixin,
    IfNotExistsMixin,
    PrimaryKeysMixin,
)
from flowmaticdb.query._query import Query
from flowmaticdb.query.ddl import Column, ConstraintABC
from flowmaticdb.result import ResultABC

if TYPE_CHECKING:
    from flowmaticdb._query_with_params import QueryWithParams
    from flowmaticdb.database import DatabaseABC
    from flowmaticdb.dialects import DialectABC


class CreateTableQuery(Query, ColumnsDefinitionMixin, PrimaryKeysMixin, ConstraintsMixin, IfNotExistsMixin):
    def __init__(self, dialect: DialectABC, table: str | list[str], database: DatabaseABC) -> None:
        super().__init__(dialect, table, database)

        self._columns: list[Column] = []
        self._primary_keys: list[str] = []
        self._constraints: list[ConstraintABC] = []
        self._if_not_exists: bool = False

    def to_query_with_params(self) -> QueryWithParams:
        return self._dialect.create_table(
            if_not_exists=self._if_not_exists,
            table=self._table,
            columns=self._columns,
            primary_keys=self._primary_keys if self._primary_keys else None,
            constraints=self._constraints if self._constraints else None,
        )

    def execute(self, emulate_prepare: bool = False) -> ResultABC:
        return self._database.query_with_params(self.to_query_with_params(), emulate_prepare)

    def explain(self, emulate_prepare: bool = False) -> list[dict[str, Any]]:
        return []
