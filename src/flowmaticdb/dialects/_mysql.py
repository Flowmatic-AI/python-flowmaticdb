from __future__ import annotations

from typing import Any

from flowmaticdb._query_with_params import QueryWithParams
from flowmaticdb.dialects._sql_dialect import SQLDialect
from flowmaticdb.exceptions import QueryError
from flowmaticdb.query._condition import Condition
from flowmaticdb.query._on_conflict import OnConflict
from flowmaticdb.query.enums._type import TypeEnum
from flowmaticdb.query.expressions._excluded import Values
from flowmaticdb.query.expressions._sql import SqlABC


class MySQLDialect(SQLDialect):
    def __init__(self, version: str = "8.0.0", options: dict[str, Any] | None = None, is_mariadb: bool = False) -> None:
        super().__init__(version=version, options=options)
        self.bool = False
        self.distinct_on = False
        self.on_conflict = False
        self.returning = False
        self.lateral = False
        self.savepoints = True
        self.generated_by_default_as_identity = False
        self.escape_identifier_char = "`"
        self.escape_string_char = "'"
        self.escape_ansi = False
        self.datetime_format = "%Y-%m-%d %H:%M:%S"
        self._is_mariadb = is_mariadb
        self._version_gate()

    def _version_gate(self) -> None:
        self.lateral = self._version >= 80014
        if self._is_mariadb and self._version >= 100500:
            self.returning = True

    def begin_transaction(self) -> QueryWithParams:
        return QueryWithParams(query="START TRANSACTION")

    def commit_transaction(self) -> QueryWithParams:
        return QueryWithParams(query="COMMIT")

    def rollback_transaction(self) -> QueryWithParams:
        return QueryWithParams(query="ROLLBACK")

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

        if on_conflict.updates is None:
            assert query[0] == "INSERT INTO ", (
                "Expected query to start with 'INSERT INTO '"
            )
            query[0] = "INSERT IGNORE INTO "
            return ""

        query.append(" ON DUPLICATE KEY UPDATE ")

        sets: list[str] = []

        if last_insert_id is not None:
            col = self.escape_identifier(last_insert_id)
            sets.append(f"{col} = LAST_INSERT_ID({col})")

        if not on_conflict.updates:
            if values:
                for col in values[0]:
                    if col == last_insert_id:
                        continue
                    esc = self.escape_identifier(col)
                    sets.append(f"{esc} = VALUES({esc})")
        else:
            for col, val in on_conflict.updates.items():
                if isinstance(val, Values):
                    esc = self.escape_identifier(col)
                    sets.append(f"{esc} = VALUES({esc})")
                else:
                    val_q: list[str] = []
                    val_p: list[Any] = []
                    self._build_question_marks(val_q, val_p, val)
                    sets.append(f"{self.escape_identifier(col)} = {''.join(val_q)}")
                    params.extend(val_p)

        query.append(", ".join(sets))

        return ""

    def _build_returning(self, query: list[str], returning: list[str] | None) -> None:
        if returning is not None and returning:
            if not self.returning:
                raise QueryError("RETURNING is not supported by MySQL")
            query.append(" RETURNING " + ", ".join(self.escape_identifier(c) for c in returning))

    def _build_condition_regex(self, query: list[str], params: list[Any], cond: Condition) -> None:
        if isinstance(cond.identifier, SqlABC):
            query.append(cond.identifier.raw_sql(self))
        else:
            query.append(self.escape_identifier(str(cond.identifier)))
        is_not = " NOT " if str(cond.condition).startswith("NOT ") else " "
        query.append(f"{is_not}REGEXP ")
        self._build_question_marks(query, params, cond.value)

    def _build_column(self, col: dict[str, Any]) -> str:
        parts = [self.escape_identifier(col["name"])]

        sql_type = col.get("type", "INTEGER")
        if isinstance(sql_type, TypeEnum):
            sql_type = self.type(sql_type, col.get("bits"))
        parts.append(sql_type)

        if col.get("auto_increment"):
            parts.append("AUTO_INCREMENT")
            parts.append("PRIMARY KEY")
            return " ".join(parts)

        if col.get("not_null"):
            parts.append("NOT NULL")
        if col.get("default") is not None:
            default = col["default"]
            if isinstance(default, bool):
                parts.append(f"DEFAULT {self.cast_bool(default)}")
            elif isinstance(default, int):
                parts.append(f"DEFAULT {default}")
            elif isinstance(default, str):
                parts.append(f"DEFAULT '{self.escape_string(default)}'")
            elif isinstance(default, SqlABC):
                parts.append(f"DEFAULT {default.raw_sql(self)}")
            else:
                parts.append(f"DEFAULT {default}")

        return " ".join(parts)

    def _build_alter(self, table: Any, alter: dict[str, Any]) -> QueryWithParams:
        atype = alter.get("type", "")
        table_str = self._table_name(table)

        if atype == "add_column":
            col = alter.get("column", {})
            return QueryWithParams(
                query=f"ALTER TABLE {table_str} ADD COLUMN {self._build_column(col)}"
            )
        elif atype == "alter_column":
            col = alter.get("column", {})
            col_name = self.escape_identifier(col.get("name", ""))
            if "type" in col:
                sql_type = col["type"]
                if isinstance(sql_type, TypeEnum):
                    sql_type = self.type(sql_type, col.get("bits"))
                return QueryWithParams(
                    query=f"ALTER TABLE {table_str} MODIFY COLUMN {col_name} {sql_type}"
                )
            if "default" in col:
                default = col["default"]
                return QueryWithParams(
                    query=f"ALTER TABLE {table_str} ALTER COLUMN {col_name} SET DEFAULT {default}"
                )
            if col.get("drop_default"):
                return QueryWithParams(
                    query=f"ALTER TABLE {table_str} ALTER COLUMN {col_name} DROP DEFAULT"
                )
            if "not_null" in col:
                raise QueryError(
                    "MySQL requires MODIFY COLUMN with full type for NOT NULL changes"
                )
            return QueryWithParams(query=f"ALTER TABLE {table_str} ALTER COLUMN {col_name}")
        elif atype == "rename_column":
            old = alter.get("old_name", "")
            new = alter.get("new_name", "")
            return QueryWithParams(
                query=(
                    f"ALTER TABLE {table_str} RENAME COLUMN "
                    f"{self.escape_identifier(old)} TO {self.escape_identifier(new)}"
                )
            )
        elif atype == "drop_column":
            col = alter.get("column", "")
            return QueryWithParams(
                query=f"ALTER TABLE {table_str} DROP COLUMN {self.escape_identifier(col)}"
            )
        elif atype == "add_primary_key":
            cols = alter.get("columns", [])
            return QueryWithParams(
                query=(
                    f"ALTER TABLE {table_str} ADD PRIMARY KEY "
                    f"({', '.join(self.escape_identifier(c) for c in cols)})"
                )
            )
        elif atype == "add_unique":
            cols = alter.get("columns", [])
            name = alter.get("name")
            name_part = f"CONSTRAINT {self.escape_identifier(name)} " if name else ""
            return QueryWithParams(
                query=(
                    f"ALTER TABLE {table_str} ADD {name_part}UNIQUE "
                    f"({', '.join(self.escape_identifier(c) for c in cols)})"
                )
            )
        elif atype == "add_foreign_key":
            cols = alter.get("columns", [])
            ref_table = alter.get("ref_table", "")
            ref_cols = alter.get("ref_columns", [])
            name = alter.get("name")
            name_part = f"CONSTRAINT {self.escape_identifier(name)} " if name else ""
            on_delete = alter.get("on_delete", "")
            on_update = alter.get("on_update", "")
            fk_parts = [
                f"{name_part}FOREIGN KEY ({', '.join(self.escape_identifier(c) for c in cols)})",
                f"REFERENCES {self.escape_identifier(ref_table)} ({', '.join(self.escape_identifier(c) for c in ref_cols)})",
            ]
            if on_delete:
                fk_parts.append(f"ON DELETE {on_delete}")
            if on_update:
                fk_parts.append(f"ON UPDATE {on_update}")
            return QueryWithParams(
                query=f"ALTER TABLE {table_str} ADD {' '.join(fk_parts)}"
            )
        elif atype == "drop_constraint":
            constraint_type = alter.get("constraint_type", "")
            if constraint_type == "primary_key":
                return QueryWithParams(query=f"ALTER TABLE {table_str} DROP PRIMARY KEY")
            elif constraint_type == "foreign_key":
                name = alter.get("name", "")
                return QueryWithParams(
                    query=f"ALTER TABLE {table_str} DROP FOREIGN KEY {self.escape_identifier(name)}"
                )
            elif constraint_type in ("unique", "index"):
                name = alter.get("name", "")
                return QueryWithParams(
                    query=f"ALTER TABLE {table_str} DROP INDEX {self.escape_identifier(name)}"
                )
            return QueryWithParams(query=f"ALTER TABLE {table_str}")
        return QueryWithParams(query=f"ALTER TABLE {table_str}")

    def cast_bool(self, value: bool) -> int:
        return 1 if value else 0

    def parse_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value != 0
        if isinstance(value, str):
            return value.lower() in ("true", "1", "t", "yes", "on")
        return bool(value)

    def escape_string(self, string: str) -> str:
        result = string.replace("\\", "\\\\")
        result = result.replace("'", "''")
        return result

    def type(self, type_enum: TypeEnum, bits: int | None = None) -> str:
        mapping = {
            TypeEnum.BOOL: "TINYINT(1)",
            TypeEnum.INT: "INT",
            TypeEnum.FLOAT: "DOUBLE" if (bits or 0) > 32 else "FLOAT",
            TypeEnum.STRING: f"VARCHAR({bits or 255})",
            TypeEnum.DATETIME: "DATETIME",
        }
        return mapping.get(type_enum, "VARCHAR(255)")
