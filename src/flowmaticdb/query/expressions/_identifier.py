from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flowmaticdb.query.expressions._sql import SqlABC

if TYPE_CHECKING:
    from flowmaticdb.dialects._base import DialectABC


class Identifier(SqlABC):
    def __init__(self, identifier: str | list[str]) -> None:
        self._identifier = identifier

    def sql(self, dialect: DialectABC) -> str:
        return dialect.escape_identifier(self._identifier)

    def params(self, dialect: DialectABC) -> list[Any]:
        return []

    def raw_sql(self, dialect: DialectABC) -> str:
        return dialect.escape_identifier(self._identifier)
