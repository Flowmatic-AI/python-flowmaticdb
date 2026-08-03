from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from flowmaticdb.query._ddl_mixins import (
    ColumnsDefinitionMixin,
    ConstraintsMixin,
    IfNotExistsMixin,
    PrimaryKeysMixin,
)
from flowmaticdb.query._query import Query
from flowmaticdb.result._base import ResultABC

if TYPE_CHECKING:
    from flowmaticdb._query_with_params import QueryWithParams
    from flowmaticdb.database._abc import DatabaseABC
    from flowmaticdb.dialects._base import DialectABC


class CreateTableQuery(Query, ColumnsDefinitionMixin, PrimaryKeysMixin, ConstraintsMixin, IfNotExistsMixin):
    def __init__(self, dialect: DialectABC, table: str | list[str], database: DatabaseABC, *args: Any, **kwargs: Any) -> None:
        kwargs['database'] = database
        super().__init__(dialect, table, *args, **kwargs)

    def to_query_with_params(self) -> QueryWithParams:
        return self._dialect.create_table(
            if_not_exists=self._if_not_exists,
            table=self._table,
            columns=self._columns,
            primary_keys=self._primary_keys if self._primary_keys else None,
            constraints=self._constraints if self._constraints else None,
        )

    def execute(self, emulate_prepare: bool = False) -> ResultABC:
        return cast(ResultABC, super().execute(emulate_prepare))
