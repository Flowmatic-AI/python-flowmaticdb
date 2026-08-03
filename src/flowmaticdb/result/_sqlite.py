from __future__ import annotations

from typing import Any

from flowmaticdb.result._base import ResultABC


class SQLite3Result(ResultABC):
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
                type_name = _SQLITE_TYPE_NAMES.get(type_code, "TEXT")
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

_SQLITE_TYPE_NAMES: dict[int, str] = {
    1: "INTEGER",
    2: "FLOAT",
    3: "TEXT",
    4: "BLOB",
    5: "NULL",
}