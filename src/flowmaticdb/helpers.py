from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from flowmaticdb.query import SelectQuery
from flowmaticdb.query.expressions._alias import Alias
from flowmaticdb.query.expressions._current_timestamp import CurrentTimestamp
from flowmaticdb.query.expressions._expression import Expression
from flowmaticdb.query.expressions._identifier import Identifier
from flowmaticdb.query.expressions._raw import Raw
from flowmaticdb.query.expressions._sub_query import SubQuery


def escape_ansi(string: str, chars: str) -> str:
    return string.translate(str.maketrans(chars, chars * 2))


def escape_backslash(string: str, chars: str) -> str:
    return string.translate(str.maketrans(chars, "\\" + chars))


def raw(sql: str) -> Raw:
    return Raw(sql)


def identifier(identifier: str | list[str]) -> Identifier:
    return Identifier(identifier)


def alias(identifier: str | list[str] | Any, alias: str) -> Alias:
    return Alias(identifier, alias)


def expression(sql: str, params: list[Any] | None = None) -> Expression:
    return Expression(sql, params)


def sub_query(query: SelectQuery, alias: str) -> SubQuery:
    return SubQuery(query, alias)


def current_timestamp() -> CurrentTimestamp:
    return CurrentTimestamp()


def now() -> CurrentTimestamp:
    return current_timestamp()
