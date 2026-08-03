from __future__ import annotations

from typing import Any

from flowmaticdb.result._base import ResultABC


class MySQLResult(ResultABC):
    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor
        self._columns_cache: dict[str, str] | None = None

    def columns(self) -> dict[str, str]:
        if self._columns_cache is not None:
            return dict(self._columns_cache)
        result: dict[str, str] = {}
        if self._cursor.description:
            for desc in self._cursor.description:
                name = desc[0]
                type_code = desc[1]
                type_name = _MYSQL_TYPE_NAMES.get(type_code, "unknown")
                result[name] = type_name
        self._columns_cache = result
        return dict(result)

    def fetch_dict(self) -> dict[str, Any] | None:
        row = self._cursor.fetchone()
        if row is None:
            return None
        if self._columns_cache is None:
            self.columns()
        if self._columns_cache:
            return dict(zip(self._columns_cache.keys(), row))
        return dict(row)

    def fetch_dicts(self) -> list[dict[str, Any]]:
        rows = self._cursor.fetchall()
        if self._columns_cache is None:
            self.columns()
        if not self._columns_cache:
            return [dict(r) for r in rows]
        cols = list(self._columns_cache.keys())
        return [dict(zip(cols, row)) for row in rows]

_MYSQL_TYPE_NAMES: dict[int, str] = {
    0: "decimal",
    1: "tinyint",
    2: "smallint",
    3: "integer",
    4: "float",
    5: "double",
    6: "null",
    7: "timestamp",
    8: "bigint",
    9: "mediumint",
    10: "date",
    11: "time",
    12: "datetime",
    13: "year",
    14: "unknown",
    15: "varchar",
    16: "bit",
    246: "decimal",
    249: "tinyint",
    250: "varchar",
    251: "char",
    252: "blob",
    253: "text",
    254: "string",
    245: "json",
}
