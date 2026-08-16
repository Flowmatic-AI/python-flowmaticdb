from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flowmaticdb.query.ddl import (
    Column,
    ForeignKeyConstraint,
    TableConstraints,
    TableDescription,
    UniqueConstraint,
)

if TYPE_CHECKING:
    from flowmaticdb.database._abc import DatabaseABC
    from flowmaticdb.dialects import DialectABC


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


def parse_columns(dialect: DialectABC, rows: list[dict[str, Any]]) -> list[Column]:
    columns: list[Column] = []

    for row in rows:
        auto_increment = dialect.parse_bool(row["auto_increment"])
        # The engine reports its own spelling ("character varying(64)"); the
        # dialect maps it back onto the TypeEnum and width that produced it.
        column_type, size = dialect.parse_column_type(str(row["column_type"]), auto_increment)

        columns.append(Column(
            name=str(row["column_name"]),
            type=column_type,
            size=size,
            not_null=dialect.parse_bool(row["not_null"]),
            # An auto-incrementing column's default is the sequence driving it,
            # which is not a default the table ever declared.
            default=None if auto_increment else _optional_string(row["default_expression"]),
            auto_increment=auto_increment,
        ))

    return columns


def parse_constraints(rows: list[dict[str, Any]]) -> TableConstraints:
    constraints = TableConstraints()

    # A multi-column constraint arrives as one row per column, already ordered
    # by position, so each row either opens a constraint or extends the one its
    # id opened. Grouping goes by id rather than by name because SQLite reports
    # no name at all for a foreign key.
    unique_by_id: dict[str, UniqueConstraint] = {}
    foreign_keys_by_id: dict[str, ForeignKeyConstraint] = {}

    for row in rows:
        constraint_id = str(row["constraint_id"])
        constraint_type = str(row["constraint_type"])
        name = _optional_string(row["constraint_name"])
        column = str(row["column_name"])

        if constraint_type == "UNIQUE":
            unique = unique_by_id.get(constraint_id)
            if unique is None:
                unique = UniqueConstraint(columns=[], name=name)
                unique_by_id[constraint_id] = unique
                constraints.unique.append(unique)

            unique.columns.append(column)
            continue

        if constraint_type != "FOREIGN KEY":
            continue

        foreign_key = foreign_keys_by_id.get(constraint_id)
        if foreign_key is None:
            foreign_key = ForeignKeyConstraint(
                columns=[],
                ref_table=str(row["ref_table"]),
                ref_columns=[],
                name=name,
                on_delete=_optional_string(row["on_delete"]),
                on_update=_optional_string(row["on_update"]),
            )
            foreign_keys_by_id[constraint_id] = foreign_key
            constraints.foreign_keys.append(foreign_key)

        foreign_key.columns.append(column)
        foreign_key.ref_columns.append(str(row["ref_column"]))

    return constraints


def describe_table(database: DatabaseABC, dialect: DialectABC, table: str | list[str]) -> TableDescription:
    column_rows = database.query_with_params(dialect.describe_table_columns(table)).fetch_dicts()
    constraint_rows = database.query_with_params(dialect.describe_table_constraints(table)).fetch_dicts()

    return TableDescription(
        columns=parse_columns(dialect, column_rows),
        constraints=parse_constraints(constraint_rows),
    )
