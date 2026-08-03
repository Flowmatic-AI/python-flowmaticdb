from __future__ import annotations

from datetime import UTC
from typing import Any

from flowmaticdb.dialects._sql_dialect import SQLDialect
from flowmaticdb.query._condition import Condition
from flowmaticdb.query._on_conflict import OnConflict
from flowmaticdb.query.enums._type import TypeEnum
from flowmaticdb.query.expressions._sql import SqlABC


class PostgresqlDialect(SQLDialect):
    def __init__(self, version: str = "16", options: dict[str, Any] | None = None) -> None:
        super().__init__(version=version, options=options)
        self.bool = True
        self.distinct_on = True
        self.on_conflict = True
        self.returning = True
        self.lateral = True
        self.datetime_format = "%Y-%m-%d %H:%M:%S.%f"
        self._version_gate()

    def _version_gate(self) -> None:
        v = self._version
        self.distinct_on = v >= 70200
        self.lateral = v >= 90300
        self.on_conflict = v >= 90500
        self.generated_by_default_as_identity = v >= 100000
        self.returning = v >= 80200

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

    def _build_returning(self, query: list[str], returning: list[str] | None) -> None:
        if returning is not None and returning:
            query.append(" RETURNING " + ", ".join(self.escape_identifier(c) for c in returning))

    def _build_condition_like(self, query: list[str], params: list[Any], cond: Any) -> None:
        if isinstance(cond.identifier, SqlABC):
            query.append(cond.identifier.raw_sql(self))
        else:
            query.append(self.escape_identifier(str(cond.identifier)))
        is_not = cond.condition.value.startswith("NOT ")
        if self._version >= 80400:
            query.append(f" {'NOT ' if is_not else ''}ILIKE ")
        else:
            query.append(f" {'NOT ' if is_not else ''}LIKE ")
        self._build_question_marks(query, params, cond.value)

    def _build_condition_regex(self, query: list[str], params: list[Any], cond: Condition) -> None:
        is_not = str(cond.condition).startswith("NOT ")
        neg = "!" if is_not else ""

        if isinstance(cond.identifier, SqlABC):
            query.append(cond.identifier.raw_sql(self))
        else:
            query.append(self.escape_identifier(str(cond.identifier)))

        use_tilde = self.option("use_tilde_regex", False)
        if not use_tilde and self._version >= 150000:
            query.append(f" {neg}~ ")
            self._build_question_marks(query, params, cond.value)
        else:
            query.append(f" {neg}~ ")
            self._build_question_marks(query, params, cond.value)

    def cast_to_query(self, value: Any) -> str:
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"

        return super().cast_to_query(value)

    def cast_bool(self, value: bool) -> bool | int:
        return value

    def parse_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value != 0
        if isinstance(value, str):
            return value.lower() in ("true", "1", "t", "yes", "on")
        return bool(value)

    def parse_datetime(self, value: Any) -> Any:
        from datetime import datetime
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            import re
            fixed = re.sub(r'([+-]\d{2})$', r'\1:00', value)
            try:
                return datetime.strptime(fixed, self.datetime_format).replace(tzinfo=UTC)
            except ValueError:
                try:
                    return datetime.fromisoformat(fixed)
                except ValueError:
                    return value
        return value

    def escape_string(self, string: str) -> str:
        result = string.replace("'", "''")
        result = result.replace("\\", "\\\\")
        return result

    def type(self, type_enum: TypeEnum, bits: int | None = None) -> str:
        mapping = {
            TypeEnum.BOOL: "BOOLEAN",
            TypeEnum.INT: "INTEGER",
            TypeEnum.FLOAT: "DOUBLE PRECISION" if (bits or 0) > 32 else "REAL",
            TypeEnum.STRING: f"VARCHAR({bits or 255})",
            TypeEnum.DATETIME: "TIMESTAMP",
        }
        return mapping.get(type_enum, "VARCHAR(255)")
