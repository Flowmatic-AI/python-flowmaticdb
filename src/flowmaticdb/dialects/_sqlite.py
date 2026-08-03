from __future__ import annotations

from datetime import UTC
from typing import Any

from flowmaticdb._query_with_params import QueryWithParams
from flowmaticdb.dialects._sql_dialect import SQLDialect
from flowmaticdb.exceptions import QueryError
from flowmaticdb.query._on_conflict import OnConflict
from flowmaticdb.query.enums._type import TypeEnum
from flowmaticdb.query.expressions._sql import SqlABC


class SQLiteDialect(SQLDialect):
    def __init__(self, version: str = "3.45", options: dict[str, Any] | None = None) -> None:
        super().__init__(version=version, options=options)
        self.generated_by_default_as_identity = False
        self.escape_identifier_char = '"'
        self.datetime_format = "%Y-%m-%d %H:%M:%S"
        self._version_gate()

    def _version_gate(self) -> None:
        v = self._version
        self.on_conflict = v >= 32400
        self.returning = v >= 33500
        self.savepoints = v >= 30000

    def _build_condition_like(self, query: list[str], params: list[Any], cond: Any) -> None:
        if isinstance(cond.identifier, SqlABC):
            query.append(cond.identifier.raw_sql(self))
        else:
            query.append(self.escape_identifier(str(cond.identifier)))
        is_not = " NOT " if cond.condition.value.startswith("NOT ") else " "
        query.append(f"{is_not}LIKE ")
        self._build_question_marks(query, params, cond.value)

    def _build_condition_glob(self, query: list[str], params: list[Any], cond: Any) -> None:
        if isinstance(cond.identifier, SqlABC):
            query.append(cond.identifier.raw_sql(self))
        else:
            query.append(self.escape_identifier(str(cond.identifier)))
        is_not = " NOT " if cond.condition.value.startswith("NOT ") else " "
        query.append(f"{is_not}GLOB ")
        self._build_question_marks(query, params, cond.value)

    def _build_condition_regex(self, query: list[str], params: list[Any], cond: Any) -> None:
        is_not = " NOT " if cond.condition.value.startswith("NOT ") else " "
        if isinstance(cond.identifier, SqlABC):
            query.append(cond.identifier.raw_sql(self))
        else:
            query.append(self.escape_identifier(str(cond.identifier)))

        use_regexp = self.option("use_regexp", False)
        if use_regexp:
            query.append(f"{is_not}REGEXP ")
        else:
            query.append(f"{is_not}REGEXP ")
        self._build_question_marks(query, params, cond.value)

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

        if isinstance(on_conflict.conflict, str):
            raise QueryError(
                "Named ON CONFLICT constraints are not supported by SQLite"
            )

        return super()._build_on_conflict(
            query, params, on_conflict, values, last_insert_id
        )

    def _build_returning(self, query: list[str], returning: list[str] | None) -> None:
        if returning is not None and returning:
            query.append(" RETURNING " + ", ".join(self.escape_identifier(c) for c in returning))

    def _build_column(self, col: dict[str, Any]) -> str:
        parts = [self.escape_identifier(col["name"])]

        sql_type = col.get("type", "INTEGER")
        if isinstance(sql_type, TypeEnum):
            sql_type = self.type(sql_type, col.get("bits"))
        parts.append(sql_type)

        if col.get("auto_increment") and sql_type.upper() == "INTEGER":
            parts.append("PRIMARY KEY AUTOINCREMENT")
            return " ".join(parts)

        if col.get("not_null"):
            parts.append("NOT NULL")
        if col.get("default") is not None:
            default = col["default"]
            if isinstance(default, bool):
                parts.append(f"DEFAULT {1 if default else 0}")
            elif isinstance(default, (int, float)):
                parts.append(f"DEFAULT {default}")
            elif isinstance(default, str):
                parts.append(f"DEFAULT '{self.escape_string(default)}'")
            elif isinstance(default, SqlABC):
                parts.append(f"DEFAULT {default.raw_sql(self)}")
            else:
                parts.append(f"DEFAULT {default}")

        return " ".join(parts)

    def _build_unique_constraint(self, constraint: dict[str, Any]) -> str:
        cols = constraint.get("columns", [])
        return f"UNIQUE ({', '.join(self.escape_identifier(c) for c in cols)})"

    def _build_foreign_key_constraint(self, constraint: dict[str, Any]) -> str:
        cols = constraint.get("columns", [])
        ref_table = constraint.get("ref_table", "")
        ref_cols = constraint.get("ref_columns", [])
        on_delete = constraint.get("on_delete", "")
        on_update = constraint.get("on_update", "")
        parts = [f"FOREIGN KEY ({', '.join(self.escape_identifier(c) for c in cols)})",
                 f"REFERENCES {self.escape_identifier(ref_table)} ({', '.join(self.escape_identifier(c) for c in ref_cols)})"]
        if on_delete:
            parts.append(f"ON DELETE {on_delete}")
        if on_update:
            parts.append(f"ON UPDATE {on_update}")
        return " ".join(parts)

    def _build_alter(self, table: Any, alter: dict[str, Any]) -> QueryWithParams:
        atype = alter.get("type", "")
        table_str = self._table_name(table)

        if atype == "add_column":
            col = alter.get("column", {})
            return QueryWithParams(query=f"ALTER TABLE {table_str} ADD COLUMN {self._build_column(col)}")
        elif atype == "rename_column":
            if self._version < 32500:
                raise QueryError("RENAME COLUMN is not supported by SQLite before 3.25.0")
            old = alter.get("old_name", "")
            new = alter.get("new_name", "")
            return QueryWithParams(query=f"ALTER TABLE {table_str} RENAME COLUMN {self.escape_identifier(old)} TO {self.escape_identifier(new)}")
        elif atype == "drop_column":
            if self._version < 33500:
                raise QueryError("DROP COLUMN is not supported by SQLite before 3.35.0")
            col = alter.get("column", "")
            return QueryWithParams(query=f"ALTER TABLE {table_str} DROP COLUMN {self.escape_identifier(col)}")
        elif atype == "alter_column":
            raise QueryError("ALTER COLUMN is not supported by SQLite")
        elif atype in ("add_primary_key", "add_unique", "add_foreign_key", "drop_constraint"):
            raise QueryError(f"Constraint alteration ({atype}) is not supported by SQLite")

        return QueryWithParams(query=f"ALTER TABLE {table_str}")

    def type(self, type_enum: TypeEnum, bits: int | None = None) -> str:
        mapping = {
            TypeEnum.BOOL: "BOOLEAN",
            TypeEnum.INT: "INTEGER",
            TypeEnum.FLOAT: "REAL",
            TypeEnum.STRING: f"VARCHAR({bits or 255})",
            TypeEnum.DATETIME: "TEXT",
        }
        return mapping.get(type_enum, "TEXT")

    def parse_datetime(self, value: Any) -> Any:
        from datetime import datetime
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.strptime(value, self.datetime_format).replace(tzinfo=UTC)
            except ValueError:
                try:
                    return datetime.fromisoformat(value)
                except ValueError:
                    return value
        return value
