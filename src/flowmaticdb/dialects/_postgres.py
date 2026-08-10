from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar

from flowmaticdb.dialects._sql_dialect import SQLDialect
from flowmaticdb.query import Condition, OnConflict
from flowmaticdb.query.ddl import Column
from flowmaticdb.query.enums import ConditionEnum, TypeEnum
from flowmaticdb.query.expressions import PostgresArray

_TZ_OFFSET_RE = re.compile(r"([+-]\d{2})$")

_NAIVE_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


class PostgresqlDialect(SQLDialect):
    escape_chars: ClassVar[Mapping[str, str]] = {
        "\\": "\\\\",
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
        "\0": "",
        "\b": "\\b",
        "\x1a": "\\x1A",
        "\f": "\\f",
        "\v": "\\v",
    }

    def __init__(self, version: str = "16", options: dict[str, Any] | None = None) -> None:
        super().__init__(version=version, options=options)
        self.bool = True
        self.distinct_on = True
        self.on_conflict = True
        self.returning = True
        self.lateral = True
        self.datetime_format = "%Y-%m-%d %H:%M:%S.%f%z"
        self._version_gate()

    def _version_gate(self) -> None:
        v = self._version
        self.distinct_on = v >= 70200
        self.lateral = v >= 90300
        self.on_conflict = v >= 90500
        self.generated_by_default_as_identity = v >= 170000
        self.returning = v >= 80200
        self.json = v >= 90200
        self.jsonb = v >= 90400

    def _build_on_conflict(
        self,
        query: list[str],
        params: list[Any],
        on_conflict: OnConflict | None,
        values: list[dict[str, Any]],
        last_insert_id: str | None,
    ) -> str:
        if on_conflict is None:
            return ""

        conflict = on_conflict.conflict

        if isinstance(conflict, str):
            query.append(
                f" ON CONFLICT ON CONSTRAINT {self.escape_identifier(conflict)}"
            )
            self._build_on_conflict_action(query, params, on_conflict, values)
        else:
            super()._build_on_conflict(
                query, params, on_conflict, values, last_insert_id
            )

        return ""

    def _build_condition_like(self, query: list[str], params: list[Any], cond: Condition) -> None:
        identifier_sql = self._escape_or_sql(cond.identifier)
        if cond.condition == ConditionEnum.LIKE:
            operator = "ILIKE" if cond.case_insensitive else "LIKE"
        else:
            operator = "NOT ILIKE" if cond.case_insensitive else "NOT LIKE"
        query.append(f"{identifier_sql} {operator} ")
        self._build_question_marks(query, params, cond.value)

    def _build_condition_regex(self, query: list[str], params: list[Any], cond: Condition) -> None:
        use_tilde = self.option("use_tilde_regex", False)
        if self._version >= 150000 and not use_tilde:
            super()._build_condition_regex(query, params, cond)
            return

        self._build_condition_regex_operator(query, params, cond, "~", "!~")

    def _build_column(self, col: Column) -> str:
        if not col.auto_increment:
            return super()._build_column(col)

        if self.generated_by_default_as_identity and not self.option("use_serials", False):
            return super()._build_column(col)

        sql_type = col.type
        if isinstance(sql_type, TypeEnum):
            sql_type = self.type(sql_type, col.bits)

        type_is_uppercase = any(ch.isupper() for ch in sql_type)
        upper_type = sql_type.upper()
        if upper_type in ("SMALLINT", "INTEGER", "INT", "INT2", "INT4"):
            serial_type = "SERIAL" if type_is_uppercase else "serial"
        elif upper_type in ("BIGINT", "INT8"):
            serial_type = "BIGSERIAL" if type_is_uppercase else "bigserial"
        else:
            serial_type = sql_type

        serial_col = dataclasses.replace(col, type=serial_type, auto_increment=False, default=None)
        return super()._build_column(serial_col)

    def cast_to_query(self, value: Any) -> str:
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"

        if isinstance(value, PostgresArray):
            if not value.values:
                return "'{}'"
            items = ", ".join(self.cast_to_query(item) for item in value.values)
            return f"ARRAY[{items}]"

        return super().cast_to_query(value)

    def cast_to_driver(self, value: Any) -> Any:
        if isinstance(value, PostgresArray):
            return list(value.values)

        return super().cast_to_driver(value)

    def cast_bool(self, value: bool) -> bool | int:
        return value

    def cast_datetime(self, value: Any) -> str:
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return super().cast_datetime(value)

    def parse_datetime(self, value: Any) -> Any:
        if isinstance(value, str):
            value = _TZ_OFFSET_RE.sub(r"\1:00", value)
            try:
                return datetime.strptime(value, self.datetime_format)
            except ValueError:
                pass
            try:
                return datetime.strptime(value, _NAIVE_DATETIME_FORMAT).replace(tzinfo=UTC)
            except ValueError:
                pass
        return super().parse_datetime(value)

    def type(self, type_enum: TypeEnum, bits: int | None = None) -> str:
        size = bits or 0
        if type_enum == TypeEnum.FLOAT:
            return "DOUBLE PRECISION" if size > 32 else "REAL"
        if type_enum == TypeEnum.DATETIME:
            return "TIMESTAMPTZ"
        if type_enum == TypeEnum.JSON and self.jsonb:
            return "JSONB"
        return super().type(type_enum, bits)
