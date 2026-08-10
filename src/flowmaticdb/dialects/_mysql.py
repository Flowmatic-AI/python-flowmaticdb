from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any, ClassVar

from flowmaticdb._query_with_params import QueryWithParams
from flowmaticdb.dialects._sql_dialect import SQLDialect
from flowmaticdb.query import Condition, OnConflict
from flowmaticdb.query.ddl import AlterColumn, Column, ConstraintABC, DropConstraint
from flowmaticdb.query.enums import ConditionEnum, TypeEnum
from flowmaticdb.query.expressions import Raw, SqlABC, Values


class MySQLDialect(SQLDialect):
    CAST_TYPES: ClassVar[Mapping[str, str]] = {
        "bool": "UNSIGNED",
        "int": "SIGNED",
        "float": "DECIMAL",
        "string": "CHAR",
    }

    escape_chars: ClassVar[Mapping[str, str]] = {
        "\\": "\\\\",
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
        "\0": "\\0",
        "\b": "\\b",
        "\x1a": "\\Z",
        "'": "\\'",
    }

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
        self.escape_string_char = '"'
        self.escape_ansi = False
        self.datetime_format = "%Y-%m-%d %H:%M:%S.%f"
        self._is_mariadb = is_mariadb
        self._version_gate()

    def _version_gate(self) -> None:
        self.lateral = (not self._is_mariadb) and self._version >= 80014
        self.on_conflict = True if self._is_mariadb else self._version >= 40100
        self.returning = self._is_mariadb and self._version >= 100500
        # MariaDB spells JSON as a LONGTEXT alias from 10.2.7; MySQL has a real
        # native JSON type from 5.7.8. Older servers fall back to TEXT.
        self.json = self._version >= 100207 if self._is_mariadb else self._version >= 50708

    def begin_transaction(self, name: str | None = None) -> QueryWithParams:
        return QueryWithParams(query="START TRANSACTION")

    def commit_transaction(self, name: str | None = None) -> QueryWithParams:
        return QueryWithParams(query="COMMIT")

    def rollback_transaction(self, name: str | None = None) -> QueryWithParams:
        return QueryWithParams(query="ROLLBACK")

    def create_table(
        self,
        if_not_exists: bool,
        table: Any,
        columns: list[Column],
        primary_keys: list[str] | None = None,
        constraints: list[ConstraintABC] | None = None,
    ) -> QueryWithParams:
        merged_primary_keys = list(primary_keys) if primary_keys else []
        for col in columns:
            if not col.auto_increment:
                continue
            if col.name not in merged_primary_keys:
                merged_primary_keys.append(col.name)

        return super().create_table(if_not_exists, table, columns, merged_primary_keys, constraints)

    def _build_on_conflict(
        self,
        query: list[str],
        params: list[Any],
        on_conflict: OnConflict | None,
        values: list[dict[str, Any]],
        last_insert_id: str | None,
    ) -> str:
        if not self.on_conflict:
            return ""

        if on_conflict is None:
            return ""

        insert_ignore = on_conflict.updates is None

        if insert_ignore and not last_insert_id:
            assert query[0] == "INSERT INTO ", (
                "Expected query to start with 'INSERT INTO '"
            )
            query[0] = "INSERT IGNORE INTO "
            return ""

        updates: dict[str, Any] = {}
        if not insert_ignore:
            if on_conflict.updates:
                updates = dict(on_conflict.updates)
            else:
                columns: list[str] = []
                for val_set in values:
                    for col in val_set:
                        if col not in columns:
                            columns.append(col)
                updates = {col: Values() for col in columns}

        if last_insert_id is not None:
            updates[last_insert_id] = Raw(
                f"LAST_INSERT_ID({self.escape_identifier(last_insert_id)})"
            )

        sets: list[str] = []
        for col, val in updates.items():
            esc = self.escape_identifier(col)
            if isinstance(val, Values):
                sets.append(f"{esc} = VALUES({esc})")
            elif isinstance(val, SqlABC):
                sets.append(f"{esc} = {val.raw_sql(self)}")
            else:
                val_q: list[str] = []
                val_p: list[Any] = []
                self._build_question_marks(val_q, val_p, val)
                sets.append(f"{esc} = {''.join(val_q)}")
                params.extend(val_p)

        query.append(" ON DUPLICATE KEY UPDATE ")
        query.append(", ".join(sets))

        return ""

    def _build_returning(self, query: list[str], returning: list[str] | None) -> None:
        if query and query[0].startswith("UPDATE"):
            return
        super()._build_returning(query, returning)

    def _build_condition_like(self, query: list[str], params: list[Any], cond: Condition) -> None:
        if self._version < 40000:
            super()._build_condition_like(query, params, cond)
            return

        identifier_sql = self._escape_or_sql(cond.identifier)
        if cond.condition == ConditionEnum.LIKE:
            operator = "LIKE" if cond.case_insensitive else "LIKE BINARY"
        else:
            operator = "NOT LIKE" if cond.case_insensitive else "NOT LIKE BINARY"
        query.append(f"{identifier_sql} {operator} ")
        self._build_question_marks(query, params, cond.value)

    def _build_condition_regex(self, query: list[str], params: list[Any], cond: Condition) -> None:
        use_regexp_option = self.option("use_regexp", False)
        if not self._is_mariadb and self._version >= 80000 and not use_regexp_option:
            super()._build_condition_regex(query, params, cond)
            return

        self._build_condition_regex_operator(query, params, cond, "REGEXP", "NOT REGEXP")

    def _build_column(self, col: Column) -> str:
        is_auto_increment = col.auto_increment
        base_col = dataclasses.replace(col, auto_increment=False) if is_auto_increment else col
        sql = super()._build_column(base_col)
        if is_auto_increment:
            sql += " AUTO_INCREMENT"
        return sql

    def _build_alter_table_alter_column(self, alter: AlterColumn) -> str:
        fragment = super()._build_alter_table_alter_column(alter)
        return "MODIFY" + fragment[len("ALTER"):]

    def _build_alter_table_drop_constraint(self, alter: DropConstraint) -> str:
        fragment = super()._build_alter_table_drop_constraint(alter)
        return fragment[:5] + "INDEX" + fragment[15:]

    def type(self, type_enum: TypeEnum, bits: int | None = None) -> str:
        size = bits or 0
        if type_enum == TypeEnum.BOOL:
            return "TINYINT"
        if type_enum == TypeEnum.FLOAT:
            return "DOUBLE" if size > 32 else "FLOAT"
        if type_enum == TypeEnum.STRING:
            if size > 16777215:
                return "LONGTEXT"
            if size > 65535:
                return "MEDIUMTEXT"
            if size > 255:
                return "TEXT"
            return f"VARCHAR({bits or 255})"
        if type_enum == TypeEnum.DATETIME:
            if size <= 0:
                return "DATETIME"
            return f"DATETIME({min(size, 6)})"
        return super().type(type_enum, bits)
