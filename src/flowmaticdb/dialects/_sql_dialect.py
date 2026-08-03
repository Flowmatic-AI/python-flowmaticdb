from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from flowmaticdb._query_with_params import QueryWithParams
from flowmaticdb.dialects._base import DialectABC
from flowmaticdb.exceptions import QueryError
from flowmaticdb.query._condition import Condition
from flowmaticdb.query._condition_group import ConditionGroupABC
from flowmaticdb.query._join import Join
from flowmaticdb.query._on_conflict import OnConflict
from flowmaticdb.query._order_by import OrderBy
from flowmaticdb.query._select import SelectQuery
from flowmaticdb.query._union import Union
from flowmaticdb.query.enums._chain import ChainEnum
from flowmaticdb.query.enums._condition import ConditionEnum
from flowmaticdb.query.enums._type import TypeEnum
from flowmaticdb.query.expressions._excluded import Excluded
from flowmaticdb.query.expressions._sql import SqlABC


class SQLDialect(DialectABC):
    def __init__(self, version: str = "0", options: dict[str, Any] | None = None) -> None:
        super().__init__(version=version, options=options)
        self.bool = False
        self.distinct_on = False
        self.on_conflict = False
        self.returning = False
        self.lateral = False
        self.savepoints = True
        self.generated_by_default_as_identity = True
        self.escape_identifier_char = '"'
        self.escape_string_char = "'"
        self.escape_ansi = True
        self.datetime_format = "%Y-%m-%d %H:%M:%S"

    def begin_transaction(self) -> QueryWithParams:
        return QueryWithParams(query="BEGIN TRANSACTION")

    def commit_transaction(self) -> QueryWithParams:
        return QueryWithParams(query="COMMIT TRANSACTION")

    def rollback_transaction(self) -> QueryWithParams:
        return QueryWithParams(query="ROLLBACK TRANSACTION")

    def begin_savepoint(self, name: str) -> QueryWithParams:
        return QueryWithParams(query=f"SAVEPOINT {self.escape_identifier(name)}")

    def commit_savepoint(self, name: str) -> QueryWithParams:
        return QueryWithParams(query=f"RELEASE SAVEPOINT {self.escape_identifier(name)}")

    def rollback_savepoint(self, name: str) -> QueryWithParams:
        return QueryWithParams(query=f"ROLLBACK TO SAVEPOINT {self.escape_identifier(name)}")

    def select(
        self,
        distinct: list[str] | None,
        columns: list[Any] | None,
        table: Any,
        joins: list[Any] | None,
        where: list[Any] | None,
        group_by: list[str] | None,
        having: list[Any] | None,
        order_by: list[Any] | None,
        limit: int | None,
        offset: int | None,
        unions: list[Any] | None,
    ) -> QueryWithParams:
        needs_wrapping = unions is not None and (limit is not None or offset is not None)

        query_parts: list[str] = []
        params: list[Any] = []

        if needs_wrapping:
            query_parts.append("(")

        query_parts.append("SELECT")
        self._build_distinct(query_parts, distinct)
        self._build_columns(query_parts, params, columns)
        self._build_table(query_parts, params, table)
        self._build_joins(query_parts, params, joins)
        self._build_where(query_parts, params, where)
        self._build_group_by(query_parts, group_by)
        self._build_having(query_parts, params, having)
        self._build_order_by(query_parts, order_by)
        self._build_limit(query_parts, limit)
        self._build_offset(query_parts, offset)

        if needs_wrapping:
            query_parts.append(")")

        self._build_unions(query_parts, params, unions)

        return QueryWithParams(query="".join(query_parts), params=params)

    def _build_distinct(self, query: list[str], distinct: list[str] | None) -> None:
        if distinct is None:
            return
        if not distinct:
            query.append(" DISTINCT")
        elif self.distinct_on:
            query.append(f" DISTINCT ON ({', '.join(self.escape_identifier(c) for c in distinct)})")
        else:
            raise QueryError("DISTINCT ON is not supported by this dialect")

    def _build_columns(self, query: list[str], params: list[Any], columns: list[Any] | None) -> None:
        if not columns:
            query.append(" *")
        else:
            col_parts = []
            for col in columns:
                if isinstance(col, SqlABC):
                    col_parts.append(col.sql(self))
                    params.extend(col.params(self))
                else:
                    col_parts.append(self.escape_identifier(str(col)))
            query.append(" " + ", ".join(col_parts))

    def _build_table(self, query: list[str], params: list[Any], table: Any) -> None:
        if table is None:
            return
        query.append(" FROM ")
        if isinstance(table, SqlABC):
            query.append(table.raw_sql(self))
            params.extend(table.params(self))
        elif isinstance(table, str):
            query.append(self.escape_identifier(table))
        elif isinstance(table, list):
            query.append(".".join(self.escape_identifier(t) for t in table))
        else:
            query.append(str(table))

    def _build_joins(self, query: list[str], params: list[Any], joins: list[Any] | None) -> None:
        if not joins:
            return
        for join_spec in joins:
            if isinstance(join_spec, SqlABC):
                query.append(" " + join_spec.raw_sql(self))
                params.extend(join_spec.params(self))
            elif isinstance(join_spec, Join):
                query.append(f" {join_spec.join.value} ")
                query.append(self._table_name(join_spec.table))
                if join_spec.conditions:
                    query.append(" ON ")
                    for i, cond in enumerate(join_spec.conditions):
                        if i > 0:
                            query.append(self._chain_connector(cond))
                        self._build_condition(query, params, cond)

    def _build_where(self, query: list[str], params: list[Any], where: list[Any] | None) -> None:
        if not where:
            return
        query.append(" WHERE ")
        for i, cond in enumerate(where):
            if i > 0:
                query.append(self._chain_connector(cond))
            self._build_condition(query, params, cond)

    def _build_having(self, query: list[str], params: list[Any], having: list[Any] | None) -> None:
        if not having:
            return
        query.append(" HAVING ")
        for i, cond in enumerate(having):
            if i > 0:
                query.append(self._chain_connector(cond))
            self._build_condition(query, params, cond)

    def _build_group_by(self, query: list[str], group_by: list[str] | None) -> None:
        if not group_by:
            return
        query.append(" GROUP BY " + ", ".join(self.escape_identifier(c) for c in group_by))

    def _build_order_by(self, query: list[str], order_by: list[Any] | None) -> None:
        if not order_by:
            return
        parts = []
        for ob in order_by:
            if isinstance(ob, OrderBy):
                parts.append(f"{self.escape_identifier(ob.column)} {ob.direction.value}")
            elif isinstance(ob, SqlABC):
                parts.append(ob.raw_sql(self))
            else:
                parts.append(str(ob))
        query.append(" ORDER BY " + ", ".join(parts))

    def _build_limit(self, query: list[str], limit: int | None) -> None:
        if limit is not None:
            query.append(f" LIMIT {limit}")

    def _build_offset(self, query: list[str], offset: int | None) -> None:
        if offset is not None:
            query.append(f" OFFSET {offset}")

    def _build_unions(self, query: list[str], params: list[Any], unions: list[Any] | None) -> None:
        if not unions:
            return
        for union_spec in unions:
            if isinstance(union_spec, Union):
                qwp = union_spec.select_query.to_query_with_params()
                query.append(f" {union_spec.union.value} ({qwp.query})")
                params.extend(qwp.params)

    def _escape_or_sql(self, identifier: Any) -> str:
        if isinstance(identifier, SqlABC):
            return identifier.raw_sql(self)
        if isinstance(identifier, list):
            parts: list[str] = []
            for part in identifier:
                parts.extend(self.escape_identifier(str(seg)) for seg in str(part).split("."))
            return ".".join(parts)
        return self.escape_identifier(str(identifier))

    def _chain_connector(self, condition: Any) -> str:
        if condition.chain == ChainEnum.OR:
            return " OR "
        return " AND "

    def _build_condition(self, query: list[str], params: list[Any], condition: Any) -> None:
        if isinstance(condition, ConditionGroupABC):
            self._build_condition_group(query, params, condition)
        elif isinstance(condition, Condition):
            self._build_single_condition(query, params, condition)
        elif isinstance(condition, SqlABC):
            query.append(condition.sql(self))
            params.extend(condition.params(self))
        else:
            query.append(str(condition))

    def _build_condition_group(self, query: list[str], params: list[Any], group: ConditionGroupABC) -> None:
        conds = group.conditions
        if not conds:
            return
        if group.not_:
            query.append("NOT (")
        else:
            query.append("(")
        for i, cond in enumerate(conds):
            if i > 0:
                query.append(self._chain_connector(cond))
            self._build_condition(query, params, cond)
        query.append(")")

    def _build_single_condition(self, query: list[str], params: list[Any], cond: Condition) -> None:
        if isinstance(cond.condition, ConditionEnum):
            condition_type = cond.condition
        else:
            query.append(f"{cond.identifier} {cond.condition} ")
            self._build_question_marks(query, params, cond.value)
            return

        if condition_type == ConditionEnum.RAW:
            if isinstance(cond.value, SqlABC):
                query.append(cond.value.raw_sql(self))
            else:
                query.append(str(cond.value))
        elif condition_type == ConditionEnum.EQUALS:
            self._build_condition_equals(query, params, cond)
        elif condition_type == ConditionEnum.NOT_EQUALS:
            self._build_condition_not_equals(query, params, cond)
        elif condition_type in (ConditionEnum.BETWEEN, ConditionEnum.NOT_BETWEEN):
            self._build_condition_between(query, params, cond)
        elif condition_type in (ConditionEnum.LIKE, ConditionEnum.NOT_LIKE):
            self._build_condition_like(query, params, cond)
        elif condition_type in (ConditionEnum.GLOB, ConditionEnum.NOT_GLOB):
            self._build_condition_glob(query, params, cond)
        elif condition_type in (ConditionEnum.IN, ConditionEnum.NOT_IN):
            self._build_condition_in(query, params, cond)
        elif condition_type in (ConditionEnum.REGEX, ConditionEnum.NOT_REGEX):
            self._build_condition_regex(query, params, cond)
        elif condition_type in (ConditionEnum.EXISTS, ConditionEnum.NOT_EXISTS):
            self._build_condition_exists(query, params, cond)
        else:
            query.append(self._escape_or_sql(cond.identifier))
            query.append(f" {cond.condition.value} ")
            self._build_question_marks(query, params, cond.value)

    def _build_condition_equals(self, query: list[str], params: list[Any], cond: Condition) -> None:
        query.append(self._escape_or_sql(cond.identifier))
        if cond.value is None:
            query.append(" IS NULL")
        elif cond.cast:
            query.append(" = ")
            query.append(self._escape_or_sql(cond.value))
        else:
            query.append(" = ")
            self._build_question_marks(query, params, cond.value)

    def _build_condition_not_equals(self, query: list[str], params: list[Any], cond: Condition) -> None:
        query.append(self._escape_or_sql(cond.identifier))
        if cond.value is None:
            query.append(" IS NOT NULL")
        elif cond.cast:
            query.append(" <> ")
            query.append(self._escape_or_sql(cond.value))
        else:
            query.append(" <> ")
            self._build_question_marks(query, params, cond.value)

    def _build_condition_between(self, query: list[str], params: list[Any], cond: Condition) -> None:
        query.append(self._escape_or_sql(cond.identifier))
        prefix = " NOT " if cond.condition == ConditionEnum.NOT_BETWEEN else " "
        query.append(f"{prefix}BETWEEN ")
        if isinstance(cond.value, (list, tuple)) and len(cond.value) >= 2:
            self._build_question_marks(query, params, cond.value[0])
            query.append(" AND ")
            self._build_question_marks(query, params, cond.value[1])

    def _build_condition_like(self, query: list[str], params: list[Any], cond: Condition) -> None:
        query.append(self._escape_or_sql(cond.identifier))
        prefix = " NOT " if cond.condition == ConditionEnum.NOT_LIKE else " "
        query.append(f"{prefix}LIKE ")
        self._build_question_marks(query, params, cond.value)

    def _build_condition_glob(self, query: list[str], params: list[Any], cond: Condition) -> None:
        raise QueryError("GLOB is not supported by this dialect")

    def _build_condition_in(self, query: list[str], params: list[Any], cond: Condition) -> None:
        query.append(self._escape_or_sql(cond.identifier))
        prefix = " NOT " if cond.condition == ConditionEnum.NOT_IN else " "
        values = cond.value if isinstance(cond.value, (list, tuple)) else [cond.value]
        if not values:
            query.append(f"{prefix}IN (NULL)")
            return
        query.append(f"{prefix}IN (")
        for i, val in enumerate(values):
            if i > 0:
                query.append(", ")
            self._build_question_marks(query, params, val)
        query.append(")")

    def _build_condition_regex(self, query: list[str], params: list[Any], cond: Condition) -> None:
        if isinstance(cond.identifier, SqlABC):
            query.append(cond.identifier.raw_sql(self))
        else:
            query.append(self.escape_identifier(str(cond.identifier)))
        is_not = " NOT " if str(cond.condition).startswith("NOT ") else " "
        query.append(f"{is_not}regexp_like(")
        self._build_question_marks(query, params, cond.value)
        query.append(f") ")
        

    def _build_condition_exists(self, query: list[str], params: list[Any], cond: Condition) -> None:
        prefix = "NOT " if cond.condition == ConditionEnum.NOT_EXISTS else ""
        query.append(f"{prefix}EXISTS (")
        if isinstance(cond.value, SqlABC):
            query.append(cond.value.raw_sql(self))
            params.extend(cond.value.params(self))
        elif isinstance(cond.value, SelectQuery):
            qwp = cond.value.to_query_with_params()
            query.append(qwp.query)
            params.extend(qwp.params)
        query.append(")")

    def _build_question_marks(self, query: list[str], params: list[Any], value: Any) -> None:
        if value is None:
            params.append(None)
            query.append("?")
        elif isinstance(value, SelectQuery):
            qwp = value.to_query_with_params()
            query.append(f"({qwp.query})")
            params.extend(qwp.params)
        elif isinstance(value, SqlABC):
            query.append(value.sql(self))
            params.extend(value.params(self))
        else:
            params.append(value)
            query.append("?")

    def insert(
        self,
        table: Any,
        values: list[dict[str, Any]],
        on_conflict: OnConflict | None = None,
        returning: list[str] | None = None,
        last_insert_id: str | None = None,
    ) -> QueryWithParams:
        query_parts = ["INSERT INTO "]
        params: list[Any] = []

        query_parts.append(self._table_name(table))

        if not values:
            raise QueryError("INSERT requires at least one value set")

        columns = list(values[0].keys())
        query_parts.append(" (" + ", ".join(self.escape_identifier(c) for c in columns) + ")")
        query_parts.append(" VALUES")

        for vi, val_set in enumerate(values):
            if vi > 0:
                query_parts.append(",")
            query_parts.append(" (")
            for ci, col in enumerate(columns):
                if ci > 0:
                    query_parts.append(", ")
                self._build_question_marks(query_parts, params, val_set.get(col))
            query_parts.append(")")

        self._build_on_conflict(query_parts, params, on_conflict, values, last_insert_id)
        self._build_returning(query_parts, returning)

        return QueryWithParams(query="".join(query_parts), params=params)

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
            raise QueryError(
                "Named constraint ON CONFLICT is not supported by the base SQL dialect"
            )

        query.append(
            f" ON CONFLICT ({', '.join(self.escape_identifier(c) for c in conflict)})"
        )
        self._build_on_conflict_action(query, params, on_conflict, values)
        return ""

    def _build_on_conflict_action(
        self,
        query: list[str],
        params: list[Any],
        on_conflict: OnConflict | None,
        values: list[dict[str, Any]],
    ) -> None:
        if on_conflict is None:
            return

        if on_conflict.updates is None:
            query.append(" DO NOTHING")
        elif not on_conflict.updates:
            if values:
                all_cols = list(values[0].keys())
                query.append(" DO UPDATE SET ")
                sets = [
                    f"{self.escape_identifier(col)} = EXCLUDED.{self.escape_identifier(col)}"
                    for col in all_cols
                ]
                query.append(", ".join(sets))
        else:
            query.append(" DO UPDATE SET ")
            update_sets: list[str] = []
            for col, val in on_conflict.updates.items():
                esc_col = self.escape_identifier(col)
                if isinstance(val, Excluded):
                    update_sets.append(f"{esc_col} = EXCLUDED.{esc_col}")
                else:
                    val_q: list[str] = []
                    val_p: list[Any] = []
                    self._build_question_marks(val_q, val_p, val)
                    update_sets.append(f"{esc_col} = {''.join(val_q)}")
                    params.extend(val_p)
            query.append(", ".join(update_sets))

    def _build_returning(self, query: list[str], returning: list[str] | None) -> None:
        pass

    def update(
        self,
        table: Any,
        updates: dict[str, Any],
        where: list[Any] | None = None,
        returning: list[str] | None = None,
    ) -> QueryWithParams:
        query_parts = ["UPDATE "]
        params: list[Any] = []

        query_parts.append(self._table_name(table))

        query_parts.append(" SET ")
        first = True
        for col, val in updates.items():
            if not first:
                query_parts.append(", ")
            first = False
            query_parts.append(f"{self.escape_identifier(col)} = ")
            self._build_question_marks(query_parts, params, val)

        self._build_where(query_parts, params, where)
        self._build_returning(query_parts, returning)

        return QueryWithParams(query="".join(query_parts), params=params)

    def delete(
        self,
        table: Any,
        where: list[Any] | None = None,
        returning: list[str] | None = None,
    ) -> QueryWithParams:
        query_parts = ["DELETE FROM "]
        params: list[Any] = []

        query_parts.append(self._table_name(table))

        self._build_where(query_parts, params, where)
        self._build_returning(query_parts, returning)

        return QueryWithParams(query="".join(query_parts), params=params)

    def create_table(
        self,
        if_not_exists: bool,
        table: Any,
        columns: list[dict[str, Any]],
        primary_keys: list[str] | None = None,
        constraints: list[dict[str, Any]] | None = None,
    ) -> QueryWithParams:
        query_parts = ["CREATE TABLE "]
        if if_not_exists:
            query_parts.append("IF NOT EXISTS ")

        query_parts.append(self._table_name(table))

        query_parts.append(" (\n")
        col_defs: list[str] = []
        has_auto_increment_pk = False

        for col in columns:
            col_def = self._build_column(col)
            if col.get("auto_increment") and "PRIMARY KEY" in col_def.upper():
                has_auto_increment_pk = True
            col_defs.append("  " + col_def)

        if primary_keys and not has_auto_increment_pk:
            col_defs.append(f"  PRIMARY KEY ({', '.join(self.escape_identifier(k) for k in primary_keys)})")

        if constraints:
            for constraint in constraints:
                col_defs.append("  " + self._build_constraint(constraint))

        query_parts.append(",\n".join(col_defs))
        query_parts.append("\n)")

        return QueryWithParams(query="".join(query_parts))

    def _build_column(self, col: dict[str, Any]) -> str:
        parts = [self.escape_identifier(col["name"])]

        sql_type = col.get("type", "INTEGER")
        if isinstance(sql_type, TypeEnum):
            sql_type = self.type(sql_type, col.get("bits"))
        parts.append(sql_type)

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
        if col.get("auto_increment"):
            if self.generated_by_default_as_identity:
                parts.append("GENERATED BY DEFAULT AS IDENTITY")
            else:
                parts.append("AUTOINCREMENT")

        return " ".join(parts)

    def _build_constraint(self, constraint: dict[str, Any]) -> str:
        ctype = constraint.get("type", "")
        if ctype == "unique":
            cols = constraint.get("columns", [])
            name = constraint.get("name")
            name_part = f"CONSTRAINT {self.escape_identifier(name)} " if name else ""
            return f"{name_part}UNIQUE ({', '.join(self.escape_identifier(c) for c in cols)})"
        elif ctype == "foreign_key":
            cols = constraint.get("columns", [])
            ref_table = constraint.get("ref_table", "")
            ref_cols = constraint.get("ref_columns", [])
            name = constraint.get("name")
            name_part = f"CONSTRAINT {self.escape_identifier(name)} " if name else ""
            on_delete = constraint.get("on_delete", "")
            on_update = constraint.get("on_update", "")
            parts = [f"{name_part}FOREIGN KEY ({', '.join(self.escape_identifier(c) for c in cols)})",
                     f"REFERENCES {self.escape_identifier(ref_table)} ({', '.join(self.escape_identifier(c) for c in ref_cols)})"]
            if on_delete:
                parts.append(f"ON DELETE {on_delete}")
            if on_update:
                parts.append(f"ON UPDATE {on_update}")
            return " ".join(parts)
        return ""

    def alter_table(self, table: Any, alters: list[dict[str, Any]]) -> list[QueryWithParams]:
        results = []
        for alter in alters:
            query = self._build_alter(table, alter)
            results.append(query)
        return results

    def _build_alter(self, table: Any, alter: dict[str, Any]) -> QueryWithParams:
        atype = alter.get("type", "")
        table_str = self._table_name(table)

        if atype == "add_column":
            col = alter.get("column", {})
            return QueryWithParams(query=f"ALTER TABLE {table_str} ADD COLUMN {self._build_column(col)}")
        elif atype == "alter_column":
            col = alter.get("column", {})
            col_name = self.escape_identifier(col.get("name", ""))
            if "type" in col:
                sql_type = col["type"]
                if isinstance(sql_type, TypeEnum):
                    sql_type = self.type(sql_type, col.get("bits"))
                return QueryWithParams(query=f"ALTER TABLE {table_str} ALTER COLUMN {col_name} TYPE {sql_type}")
            if "default" in col:
                default = col["default"]
                return QueryWithParams(query=f"ALTER TABLE {table_str} ALTER COLUMN {col_name} SET DEFAULT {default}")
            if "not_null" in col:
                if col["not_null"]:
                    return QueryWithParams(query=f"ALTER TABLE {table_str} ALTER COLUMN {col_name} SET NOT NULL")
                else:
                    return QueryWithParams(query=f"ALTER TABLE {table_str} ALTER COLUMN {col_name} DROP NOT NULL")
            if col.get("drop_default"):
                return QueryWithParams(query=f"ALTER TABLE {table_str} ALTER COLUMN {col_name} DROP DEFAULT")
            return QueryWithParams(query=f"ALTER TABLE {table_str} ALTER COLUMN {col_name}")
        elif atype == "rename_column":
            old = alter.get("old_name", "")
            new = alter.get("new_name", "")
            return QueryWithParams(query=f"ALTER TABLE {table_str} RENAME COLUMN {self.escape_identifier(old)} TO {self.escape_identifier(new)}")
        elif atype == "drop_column":
            col = alter.get("column", "")
            return QueryWithParams(query=f"ALTER TABLE {table_str} DROP COLUMN {self.escape_identifier(col)}")
        elif atype == "add_primary_key":
            cols = alter.get("columns", [])
            return QueryWithParams(query=f"ALTER TABLE {table_str} ADD PRIMARY KEY ({', '.join(self.escape_identifier(c) for c in cols)})")
        elif atype == "add_unique":
            cols = alter.get("columns", [])
            name = alter.get("name")
            name_part = f"CONSTRAINT {self.escape_identifier(name)} " if name else ""
            return QueryWithParams(query=f"ALTER TABLE {table_str} ADD {name_part}UNIQUE ({', '.join(self.escape_identifier(c) for c in cols)})")
        elif atype == "add_foreign_key":
            cols = alter.get("columns", [])
            ref_table = alter.get("ref_table", "")
            ref_cols = alter.get("ref_columns", [])
            name = alter.get("name")
            name_part = f"CONSTRAINT {self.escape_identifier(name)} " if name else ""
            return QueryWithParams(query=f"ALTER TABLE {table_str} ADD {name_part}FOREIGN KEY ({', '.join(self.escape_identifier(c) for c in cols)}) REFERENCES {self.escape_identifier(ref_table)} ({', '.join(self.escape_identifier(c) for c in ref_cols)})")
        elif atype == "drop_constraint":
            name = alter.get("name", "")
            return QueryWithParams(query=f"ALTER TABLE {table_str} DROP CONSTRAINT {self.escape_identifier(name)}")
        return QueryWithParams(query=f"ALTER TABLE {table_str}")

    def drop_table(self, if_exists: bool, table: Any) -> QueryWithParams:
        table_str = self._table_name(table)
        if if_exists:
            return QueryWithParams(query=f"DROP TABLE IF EXISTS {table_str}")
        return QueryWithParams(query=f"DROP TABLE {table_str}")

    def _table_name(self, table: Any) -> str:
        if isinstance(table, SqlABC):
            return table.raw_sql(self)
        if isinstance(table, list):
            return ".".join(self.escape_identifier(t) for t in table)
        return self.escape_identifier(str(table))

    def escape_identifier(self, identifier: str | list[str]) -> str:
        if isinstance(identifier, list):
            return ".".join(self.escape_identifier(i) for i in identifier)
        return f"{self.escape_identifier_char}{identifier}{self.escape_identifier_char}"

    def escape_string(self, string: str) -> str:
        return string.replace(self.escape_string_char, self.escape_string_char * 2)

    def cast_to_query(self, value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return str(self.cast_bool(value))
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return str(value)
        if isinstance(value, str):
            return f"'{self.escape_string(value)}'"
        if isinstance(value, datetime):
            return f"'{value.strftime(self.datetime_format)}'"
        if isinstance(value, SelectQuery):
            qwp = value.to_query_with_params()
            return f"({qwp.to_sql(self)})"
        if isinstance(value, SqlABC):
            return value.raw_sql(self)
        return str(value)

    def cast_bool(self, value: bool) -> bool | int:
        return 1 if value else 0

    def cast_datetime(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.strftime(self.datetime_format)
        return str(value)

    def cast_to_driver(self, value: Any) -> Any:
        if isinstance(value, bool):
            return self.cast_bool(value)
        if isinstance(value, datetime):
            return self.cast_datetime(value)
        return value

    def parse_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value != 0
        if isinstance(value, str):
            return value.lower() in ("true", "1", "t", "yes")
        return bool(value)

    def parse_datetime(self, value: Any) -> Any:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.strptime(value, self.datetime_format).replace(tzinfo=UTC)
            except ValueError:
                return value
        return value

    def type(self, type_enum: TypeEnum, bits: int | None = None) -> str:
        mapping = {
            TypeEnum.BOOL: "BOOLEAN",
            TypeEnum.INT: "INTEGER",
            TypeEnum.FLOAT: "FLOAT",
            TypeEnum.STRING: "VARCHAR",
            TypeEnum.DATETIME: "DATETIME",
        }
        sql_type = mapping.get(type_enum, "VARCHAR")
        if type_enum == TypeEnum.STRING and bits is not None:
            sql_type = f"VARCHAR({bits})"
        return sql_type
