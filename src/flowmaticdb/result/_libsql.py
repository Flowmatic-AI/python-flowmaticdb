from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from flowmaticdb._json import decode_json
from flowmaticdb.result._base import ResultABC

_DOCUMENT_PREFIXES = ("{", "[")

_DATETIME_SHAPE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?")
"""The dialect renders a datetime as ``%Y-%m-%d %H:%M:%S``, and the adapter
stores the fuller ISO-8601 form that keeps microseconds and the UTC offset.
Both are accepted; anything shorter -- a bare date, a time on its own -- is
left as the text it is."""


def _libsql_runtime_type(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, datetime):
        return "DATETIME"
    if isinstance(value, date):
        return "DATE"
    if isinstance(value, (dict, list)):
        return "JSON"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "FLOAT"
    if isinstance(value, bytes):
        return "BLOB"
    return "TEXT"


def _guess_value(value: Any) -> Any:
    """Read a stored value back as the type it was written from.

    Only text is ever reinterpreted, and only when it can only have come from
    one of the two types this library serializes on the way in: a document, or
    a datetime in the format the dialect writes. A document is recognized by
    its opening brace or bracket, so a bare ``"1"`` or ``"null"`` -- valid JSON
    but far more likely a string someone stored -- stays a string. Text that
    fails to parse is returned untouched, never raised over."""
    if not isinstance(value, str):
        return value

    if value[:1] in _DOCUMENT_PREFIXES:
        return decode_json(value)

    if _DATETIME_SHAPE.fullmatch(value):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value

    return value


class LibSQLResult(ResultABC):
    """Rows arrive as plain tuples and the cursor description carries names
    only, so the column order is the only thing tying a value to its name.

    That missing description is also why ``auto_cast_column_types`` exists:
    with no declared type to decode against, a DATETIME and a JSON column both
    read back as the text they are stored as. The values are guessed from their
    own shape instead -- see :func:`_guess_value` -- unless the option is off,
    in which case they are handed over exactly as the engine stored them.
    Nothing guesses at BOOLEAN: it is stored as 0/1, which no amount of looking
    distinguishes from an integer."""

    def __init__(self, cursor: Any, auto_cast_column_types: bool = True) -> None:
        self._cursor = cursor
        self._auto_cast_column_types = auto_cast_column_types
        self._columns_cache: dict[str, str] | None = None
        self._column_indices: dict[str, int] = {}

    def columns(self) -> dict[str, str]:
        if self._columns_cache is None:
            self._columns_cache = self._describe()
        return dict(self._columns_cache)

    def _describe(self) -> dict[str, str]:
        result: dict[str, str] = {}
        indices: dict[str, int] = {}
        if self._cursor.description:
            for index, desc in enumerate(self._cursor.description):
                result[desc[0]] = "NULL"
                indices[desc[0]] = index
        self._column_indices = indices
        return result

    def _cast_row(self, row: tuple[Any, ...]) -> list[Any]:
        if not self._auto_cast_column_types:
            return list(row)
        return [_guess_value(value) for value in row]

    def _observe_row(self, values: list[Any]) -> None:
        if self._columns_cache is None:
            self._columns_cache = self._describe()
        for name, index in self._column_indices.items():
            self._columns_cache[name] = _libsql_runtime_type(values[index])

    def _to_dict(self, values: list[Any]) -> dict[str, Any]:
        return {name: values[index] for name, index in self._column_indices.items()}

    def fetch_dict(self) -> dict[str, Any] | None:
        row = self._cursor.fetchone()
        if row is None:
            return None
        values = self._cast_row(row)
        self._observe_row(values)
        return self._to_dict(values)

    def fetch_dicts(self) -> list[dict[str, Any]]:
        # A statement that produced no result set at all -- an INSERT without
        # RETURNING, a PRAGMA that only sets -- fetches None here rather than an
        # empty sequence.
        rows = [self._cast_row(row) for row in self._cursor.fetchall() or []]
        if rows:
            self._observe_row(rows[0])
        elif self._columns_cache is None:
            self._columns_cache = self._describe()
        return [self._to_dict(values) for values in rows]
