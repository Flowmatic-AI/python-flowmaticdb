from __future__ import annotations

from typing import Any

from flowmaticdb import QueryError
from flowmaticdb.dialects._sqlite import SQLiteDialect
from flowmaticdb.query import Condition
from flowmaticdb.query.enums import ConditionEnum


class LibSQLDialect(SQLiteDialect):
    """SQLite grammar, with the differences the libsql engine actually has."""

    def _build_condition_regex(self, query: list[str], params: list[Any], cond: Condition) -> None:
        """The engine ships a REGEXP operator of its own, so matching never goes
        through ``regexp_like()`` -- that function does not exist here and no
        user-defined one can take its place, which makes the operator form the
        only form rather than the ``use_regexp`` opt-in it is on SQLite.

        Its regex flavour has no inline ``(?i)`` group either, so a case
        insensitive match folds both sides instead -- the same way a case
        insensitive GLOB comparison is built."""
        flags = cond.flags or ""
        unsupported = flags.replace("i", "")
        if unsupported:
            raise QueryError(f"Regex flags '{unsupported}' are not supported by libsql")

        identifier_sql = self._escape_or_sql(cond.identifier)

        value_parts: list[str] = []
        self._build_question_marks(value_parts, params, cond.value)
        value_sql = "".join(value_parts)

        if "i" in flags:
            identifier_sql = f"lower({identifier_sql})"
            value_sql = f"lower({value_sql})"

        operator = "NOT REGEXP" if cond.condition == ConditionEnum.NOT_REGEX else "REGEXP"
        query.append(f"{identifier_sql} {operator} {value_sql}")
