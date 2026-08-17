from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as time_of_day
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from flowmaticdb import QueryError
from flowmaticdb.database import DatabaseABC
from flowmaticdb.query import DeleteQuery, SelectQuery, UpdateQuery
from flowmaticdb.query.enums import ReferentialActionEnum, TypeEnum
from flowmaticdb.query.expressions import SqlABC
from flowmaticdb.result import ResultABC

_OPERATOR_DOC = """
A where is {"identifier": ..., "operator": ..., "value": ...}; every where in the
array is joined with AND. The identifier is a column name, or a ["table", "column"]
pair for a qualified one.

Operators: "=", "!=", "<", "<=", ">", ">=", "like", "not like", "ilike", "not ilike",
"in", "not in", "between", "not between", "is null", "is not null", "contains",
"not contains", "starts with", "ends with", "glob", "not glob", "regex", "not regex",
"empty", "not empty".

"in" and "not in" take a list value, "between" and "not between" take a two element
[min, max] list, and "is null", "is not null", "empty" and "not empty" ignore the
value. Every other operator takes a scalar. A "=" against a null value becomes IS NULL.
"""

_EQUALS_OPERATORS = ("=", "==", "eq", "equals")
_NOT_EQUALS_OPERATORS = ("!=", "<>", "ne", "not equals")
_KNOWN_OPERATORS = (
    '"=", "!=", "<", "<=", ">", ">=", "like", "not like", "ilike", "not ilike", "in", '
    '"not in", "between", "not between", "is null", "is not null", "contains", '
    '"not contains", "starts with", "ends with", "glob", "not glob", "regex", '
    '"not regex", "empty", "not empty"'
)


@dataclass
class Where:
    identifier: str | list[str]
    operator: str
    value: Any = None


def _normalize_operator(operator: str) -> str:
    return " ".join(operator.replace("_", " ").lower().split())


def _require_list(operator: str, value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise QueryError(f'the "{operator}" operator needs a list value')

    return value


def _require_range(operator: str, value: Any) -> list[Any]:
    values = _require_list(operator, value)
    if len(values) != 2:
        raise QueryError(f'the "{operator}" operator needs a [min, max] list value')

    return values


class FlowmaticDBMCP:
    def __init__(self, db: DatabaseABC, name: str = "flowmaticdb") -> None:
        self._db = db
        self._savepoints: list[str] = []
        self._server = FastMCP(name)

        self._register_tools()

    @property
    def db(self) -> DatabaseABC:
        return self._db

    @property
    def server(self) -> FastMCP:
        return self._server

    def run(self, transport: Literal["stdio", "sse", "streamable-http"] = "stdio") -> None:
        self._server.run(transport)

    def _register_tools(self) -> None:
        read_only = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
        writes = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
        destructive = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)

        self._server.add_tool(
            self.driver,
            name="driver",
            title="Current driver",
            description="""Name of the driver this server is connected through: "mysql", "postgresql" or "sqlite".

The SQL dialect follows the driver, so read this first when writing raw SQL.""",
            annotations=read_only,
        )
        self._server.add_tool(
            self.execute_sql,
            name="execute_sql",
            title="Execute SQL",
            description="""Run a single SQL statement and return every row it produced.

Pass values through "params" rather than interpolating them into the statement: each ?
placeholder in the statement consumes one entry, in order. Statements that produce no
rows return an empty array.""",
            annotations=destructive,
        )
        self._server.add_tool(
            self.list_tables,
            name="list_tables",
            title="List tables",
            description="""Names of the tables in a schema.

The schema is ignored by engines that have no schemas, so the default suits SQLite and
MySQL as well.""",
            annotations=read_only,
        )
        self._server.add_tool(
            self.describe_table,
            name="describe_table",
            title="Describe table",
            description="""Columns, unique constraints and foreign keys of a table.

The table is a name, or a ["schema", "table"] pair for a qualified one. A column type
reads as BOOL, INT, FLOAT, STRING, DATETIME or JSON, and falls back to the engine's own
spelling for a type that maps to none of those.""",
            annotations=read_only,
        )
        self._server.add_tool(
            self.select,
            name="select",
            title="Select rows",
            description=f"""Read rows from a table.

Returns every matched row as an object keyed by column name. "group_by" is a list of
columns to collapse the rows on, and "havings" filters what the grouping produced -- the
same shape and operators as "wheres", applied after the grouping rather than before it.
{_OPERATOR_DOC}""",
            annotations=read_only,
        )
        self._server.add_tool(
            self.insert,
            name="insert",
            title="Insert rows",
            description="""Insert one or more rows, each an object keyed by column name.

"returning" names the columns to read back off the inserted rows; an empty array reads
all of them, and leaving it out returns nothing. Engines without a native RETURNING
clause read the rows back by primary key instead, which needs "last_insert_id" set to
the name of that key column.""",
            annotations=writes,
        )
        self._server.add_tool(
            self.update,
            name="update",
            title="Update rows",
            description=f"""Update rows in a table.

"values" maps column name to its new value. At least one where is required; run an
unfiltered update through execute_sql instead.
{_OPERATOR_DOC}""",
            annotations=destructive,
        )
        self._server.add_tool(
            self.delete,
            name="delete",
            title="Delete rows",
            description=f"""Delete rows from a table.

At least one where is required; run an unfiltered delete through execute_sql instead.
{_OPERATOR_DOC}""",
            annotations=destructive,
        )
        self._server.add_tool(
            self.begin_transaction,
            name="begin_transaction",
            title="Begin transaction",
            description="""Open a transaction.

Nesting is not implicit: while a transaction is open, use begin_savepoint to carve out a
part of it that can be rolled back on its own.""",
            annotations=writes,
        )
        self._server.add_tool(
            self.commit_transaction,
            name="commit_transaction",
            title="Commit transaction",
            description="Commit the open transaction, together with every savepoint still open inside it.",
            annotations=writes,
        )
        self._server.add_tool(
            self.rollback_transaction,
            name="rollback_transaction",
            title="Roll back transaction",
            description="Roll back the open transaction, discarding every savepoint still open inside it.",
            annotations=writes,
        )
        self._server.add_tool(
            self.begin_savepoint,
            name="begin_savepoint",
            title="Begin savepoint",
            description="""Open a named savepoint inside the open transaction.

Savepoints close in the order they opened: only the innermost one can be committed or
rolled back.""",
            annotations=writes,
        )
        self._server.add_tool(
            self.commit_savepoint,
            name="commit_savepoint",
            title="Release savepoint",
            description="Release the innermost savepoint, folding its work into the transaction around it.",
            annotations=writes,
        )
        self._server.add_tool(
            self.rollback_savepoint,
            name="rollback_savepoint",
            title="Roll back to savepoint",
            description="""Roll back to the innermost savepoint, discarding the work done since it opened.

The transaction around it stays open.""",
            annotations=writes,
        )

    def driver(self) -> str:
        return self._db.adapter.driver_name

    def execute_sql(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        return self._rows(self._db.prepared(sql, params))

    def list_tables(self, schema: str = "public") -> list[str]:
        return self._db.list_tables(schema)

    def describe_table(self, table: str | list[str]) -> dict[str, Any]:
        description = self._db.describe_table(table)

        columns: list[dict[str, Any]] = []
        for column in description.columns:
            columns.append({
                "name": column.name,
                "type": self._type_name(column.type),
                "size": column.size,
                "not_null": column.not_null,
                "default": self._json_safe(column.default),
                "auto_increment": column.auto_increment,
            })

        unique: list[dict[str, Any]] = []
        for constraint in description.constraints.unique:
            unique.append({"name": constraint.name, "columns": constraint.columns})

        foreign_keys: list[dict[str, Any]] = []
        for foreign_key in description.constraints.foreign_keys:
            foreign_keys.append({
                "name": foreign_key.name,
                "columns": foreign_key.columns,
                "ref_table": foreign_key.ref_table,
                "ref_columns": foreign_key.ref_columns,
                "on_delete": self._referential_action(foreign_key.on_delete),
                "on_update": self._referential_action(foreign_key.on_update),
            })

        return {
            "table": table,
            "columns": columns,
            "unique_constraints": unique,
            "foreign_keys": foreign_keys,
        }

    def select(
        self,
        table: str | list[str],
        wheres: list[Where] | None = None,
        group_by: list[str | list[str]] | None = None,
        havings: list[Where] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        query = self._db.select(table)
        self._apply_wheres(query, wheres)

        if group_by:
            query.group_by(list(group_by))

        self._apply_havings(query, havings)

        if limit is not None:
            query.limit(limit)

        if offset is not None:
            query.offset(offset)

        return self._rows(query.execute())

    def insert(
        self,
        table: str | list[str],
        values: list[dict[str, Any]],
        returning: list[str] | None = None,
        last_insert_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not values:
            raise QueryError("insert needs at least one row of values")

        query = self._db.insert(table)
        for row in values:
            query.values(row)

        if last_insert_id is not None:
            query.last_insert_id(last_insert_id)

        if returning is not None:
            query.returning(returning)

        result = query.execute()
        if not isinstance(result, list):
            return self._rows(result)

        rows: list[dict[str, Any]] = []
        for single in result:
            rows.extend(self._rows(single))

        return rows

    def update(self, table: str | list[str], values: dict[str, Any], wheres: list[Where]) -> str:
        if not values:
            raise QueryError("update needs at least one column to set")

        self._require_wheres("update", wheres)

        query = self._db.update(table)
        query.updates(values)
        self._apply_wheres(query, wheres)
        query.execute()

        return f"updated {self._table_name(table)}"

    def delete(self, table: str | list[str], wheres: list[Where]) -> str:
        self._require_wheres("delete", wheres)

        query = self._db.delete(table)
        self._apply_wheres(query, wheres)
        query.execute()

        return f"deleted from {self._table_name(table)}"

    def begin_transaction(self) -> dict[str, Any]:
        if self._db.in_transaction:
            raise QueryError("a transaction is already open; use begin_savepoint to nest inside it")

        self._db.begin_transaction()

        return self._state()

    def commit_transaction(self) -> dict[str, Any]:
        if not self._db.in_transaction:
            raise QueryError("no transaction is open")

        self._db.commit_transaction(release_savepoints=True)
        self._savepoints.clear()

        return self._state()

    def rollback_transaction(self) -> dict[str, Any]:
        if not self._db.in_transaction:
            raise QueryError("no transaction is open")

        self._db.rollback_transaction(release_savepoints=True)
        self._savepoints.clear()

        return self._state()

    def begin_savepoint(self, name: str) -> dict[str, Any]:
        if not self._db.in_transaction:
            raise QueryError("no transaction is open; call begin_transaction first")

        if name in self._savepoints:
            raise QueryError(f'savepoint "{name}" is already open')

        self._db.begin_transaction(name=name)
        self._savepoints.append(name)

        return self._state()

    def commit_savepoint(self, name: str) -> dict[str, Any]:
        self._require_innermost_savepoint(name)

        self._db.commit_transaction(name=name)
        self._savepoints.pop()

        return self._state()

    def rollback_savepoint(self, name: str) -> dict[str, Any]:
        self._require_innermost_savepoint(name)

        self._db.rollback_transaction(name=name)
        self._savepoints.pop()

        return self._state()

    def _state(self) -> dict[str, Any]:
        return {"in_transaction": self._db.in_transaction, "savepoints": list(self._savepoints)}

    def _require_innermost_savepoint(self, name: str) -> None:
        if not self._savepoints:
            raise QueryError("no savepoint is open")

        innermost = self._savepoints[-1]
        if innermost != name:
            raise QueryError(f'savepoint "{innermost}" is open inside "{name}" and has to be closed first')

    def _require_wheres(self, action: str, wheres: list[Where]) -> None:
        if not wheres:
            raise QueryError(
                f"{action} needs at least one where; run an unfiltered {action} through execute_sql"
            )

    def _table_name(self, table: str | list[str]) -> str:
        return table if isinstance(table, str) else ".".join(table)

    def _type_name(self, column_type: TypeEnum | str) -> str:
        return column_type.name if isinstance(column_type, TypeEnum) else column_type

    def _referential_action(self, action: ReferentialActionEnum | str | None) -> str | None:
        if action is None:
            return None

        return action.value if isinstance(action, ReferentialActionEnum) else action

    def _rows(self, result: ResultABC) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        for row in result.fetch_dicts():
            rows.append({name: self._json_safe(value) for name, value in row.items()})

        return rows

    def _json_safe(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value

        if isinstance(value, (datetime, date, time_of_day)):
            return value.isoformat()

        if isinstance(value, Decimal):
            return str(value)

        if isinstance(value, UUID):
            return str(value)

        if isinstance(value, (bytes, bytearray)):
            return self._binary(bytes(value))

        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items()}

        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(item) for item in value]

        if isinstance(value, SqlABC):
            return value.raw_sql(self._db.dialect)

        return str(value)

    def _binary(self, value: bytes) -> str:
        try:
            text = value.decode("utf-8")
        except UnicodeDecodeError:
            return base64.b64encode(value).decode("ascii")

        for character in text:
            if character not in "\t\n\r" and not character.isprintable():
                return base64.b64encode(value).decode("ascii")

        return text

    def _apply_wheres(self, query: SelectQuery | UpdateQuery | DeleteQuery, wheres: list[Where] | None) -> None:
        if wheres is None:
            return

        for where in wheres:
            self._apply_where(query, where)

    def _apply_where(self, query: SelectQuery | UpdateQuery | DeleteQuery, where: Where) -> None:
        operator = _normalize_operator(where.operator)
        identifier = where.identifier
        value = where.value

        if operator in _EQUALS_OPERATORS:
            query.where_equals(identifier, value)
        elif operator in _NOT_EQUALS_OPERATORS:
            query.where_not_equals(identifier, value)
        elif operator == "<":
            query.where_less_than(identifier, value)
        elif operator == "<=":
            query.where_less_than_or_equals(identifier, value)
        elif operator == ">":
            query.where_greater_than(identifier, value)
        elif operator == ">=":
            query.where_greater_than_or_equals(identifier, value)
        elif operator == "like":
            query.where_like(identifier, value)
        elif operator == "not like":
            query.where_not_like(identifier, value)
        elif operator == "ilike":
            query.where_like(identifier, value, case_insensitive=True)
        elif operator == "not ilike":
            query.where_not_like(identifier, value, case_insensitive=True)
        elif operator == "in":
            query.where_in(identifier, _require_list(operator, value))
        elif operator == "not in":
            query.where_not_in(identifier, _require_list(operator, value))
        elif operator == "between":
            bounds = _require_range(operator, value)
            query.where_between(identifier, bounds[0], bounds[1])
        elif operator == "not between":
            bounds = _require_range(operator, value)
            query.where_not_between(identifier, bounds[0], bounds[1])
        elif operator == "is null":
            query.where_is_null(identifier)
        elif operator == "is not null":
            query.where_is_not_null(identifier)
        elif operator == "contains":
            query.where_contains(identifier, value)
        elif operator == "not contains":
            query.where_not_contains(identifier, value)
        elif operator == "starts with":
            query.where_starts_with(identifier, value)
        elif operator == "ends with":
            query.where_ends_with(identifier, value)
        elif operator == "glob":
            query.where_glob(identifier, value)
        elif operator == "not glob":
            query.where_not_glob(identifier, value)
        elif operator == "regex":
            query.where_regex(identifier, value)
        elif operator == "not regex":
            query.where_not_regex(identifier, value)
        elif operator == "empty":
            query.where_empty(identifier)
        elif operator == "not empty":
            query.where_not_empty(identifier)
        else:
            raise QueryError(f'unknown operator "{where.operator}"; supported operators are {_KNOWN_OPERATORS}')

    def _apply_havings(self, query: SelectQuery, havings: list[Where] | None) -> None:
        if havings is None:
            return

        for having in havings:
            self._apply_having(query, having)

    def _apply_having(self, query: SelectQuery, having: Where) -> None:
        operator = _normalize_operator(having.operator)
        identifier = having.identifier
        value = having.value

        if operator in _EQUALS_OPERATORS:
            query.having_equals(identifier, value)
        elif operator in _NOT_EQUALS_OPERATORS:
            query.having_not_equals(identifier, value)
        elif operator == "<":
            query.having_less_than(identifier, value)
        elif operator == "<=":
            query.having_less_than_or_equals(identifier, value)
        elif operator == ">":
            query.having_greater_than(identifier, value)
        elif operator == ">=":
            query.having_greater_than_or_equals(identifier, value)
        elif operator == "like":
            query.having_like(identifier, value)
        elif operator == "not like":
            query.having_not_like(identifier, value)
        elif operator == "ilike":
            query.having_like(identifier, value, case_insensitive=True)
        elif operator == "not ilike":
            query.having_not_like(identifier, value, case_insensitive=True)
        elif operator == "in":
            query.having_in(identifier, _require_list(operator, value))
        elif operator == "not in":
            query.having_not_in(identifier, _require_list(operator, value))
        elif operator == "between":
            bounds = _require_range(operator, value)
            query.having_between(identifier, bounds[0], bounds[1])
        elif operator == "not between":
            bounds = _require_range(operator, value)
            query.having_not_between(identifier, bounds[0], bounds[1])
        elif operator == "is null":
            query.having_is_null(identifier)
        elif operator == "is not null":
            query.having_is_not_null(identifier)
        elif operator == "contains":
            query.having_contains(identifier, value)
        elif operator == "not contains":
            query.having_not_contains(identifier, value)
        elif operator == "starts with":
            query.having_starts_with(identifier, value)
        elif operator == "ends with":
            query.having_ends_with(identifier, value)
        elif operator == "glob":
            query.having_glob(identifier, value)
        elif operator == "not glob":
            query.having_not_glob(identifier, value)
        elif operator == "regex":
            query.having_regex(identifier, value)
        elif operator == "not regex":
            query.having_not_regex(identifier, value)
        elif operator == "empty":
            query.having_empty(identifier)
        elif operator == "not empty":
            query.having_not_empty(identifier)
        else:
            raise QueryError(f'unknown operator "{having.operator}"; supported operators are {_KNOWN_OPERATORS}')
