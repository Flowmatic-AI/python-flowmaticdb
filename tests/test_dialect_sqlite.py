from __future__ import annotations

import pytest

from flowmaticdb._query_with_params import QueryWithParams
from flowmaticdb.dialects._sqlite import SQLiteDialect
from flowmaticdb.exceptions import QueryError
from flowmaticdb.query._condition import Condition
from flowmaticdb.query.enums._condition import ConditionEnum


def test_sqlite_select(sqlite_dialect: SQLiteDialect) -> None:
    qwp: QueryWithParams = sqlite_dialect.select(
        distinct=None,
        columns=["id", "name"],
        table="users",
        joins=None,
        where=None,
        group_by=None,
        having=None,
        order_by=None,
        limit=None,
        offset=None,
        unions=None,
    )
    assert qwp.query == 'SELECT "id", "name" FROM "users"'


def test_sqlite_on_conflict(sqlite_dialect: SQLiteDialect) -> None:
    from flowmaticdb.query._on_conflict import OnConflict
    qwp: QueryWithParams = sqlite_dialect.insert(
        table="users",
        values=[{"id": 1, "name": "John"}],
        on_conflict=OnConflict(conflict=["id"], updates=None),
        returning=None,
        last_insert_id=None,
    )
    # SQLite 3.45 supports ON CONFLICT
    assert "ON CONFLICT" in qwp.query
    assert "DO NOTHING" in qwp.query


def test_sqlite_on_conflict_named_constraint_raises(
    sqlite_dialect: SQLiteDialect,
) -> None:
    from flowmaticdb.query._on_conflict import OnConflict
    with pytest.raises(QueryError, match="Named ON CONFLICT"):
        sqlite_dialect.insert(
            table="users",
            values=[{"id": 1, "name": "John"}],
            on_conflict=OnConflict(conflict="users_pkey", updates=None),
            returning=None,
            last_insert_id=None,
        )


def test_sqlite_returning(sqlite_dialect: SQLiteDialect) -> None:
    qwp: QueryWithParams = sqlite_dialect.insert(
        table="users",
        values=[{"name": "John"}],
        on_conflict=None,
        returning=["id"],
        last_insert_id=None,
    )
    assert "RETURNING" in qwp.query
    assert '"id"' in qwp.query


def test_sqlite_type_mapping(sqlite_dialect: SQLiteDialect) -> None:
    from flowmaticdb.query.enums._type import TypeEnum
    assert sqlite_dialect.type(TypeEnum.BOOL) == "BOOLEAN"
    assert sqlite_dialect.type(TypeEnum.INT) == "INTEGER"
    assert sqlite_dialect.type(TypeEnum.FLOAT) == "REAL"
    assert sqlite_dialect.type(TypeEnum.DATETIME) == "TEXT"


def test_sqlite_no_distinct_on(sqlite_dialect: SQLiteDialect) -> None:
    assert not sqlite_dialect.distinct_on


def test_sqlite_no_generated_identity(sqlite_dialect: SQLiteDialect) -> None:
    assert not sqlite_dialect.generated_by_default_as_identity


def test_sqlite_auto_increment_column(sqlite_dialect: SQLiteDialect) -> None:
    from flowmaticdb.query.enums._type import TypeEnum
    col: dict[str, object] = {
        "name": "id",
        "type": TypeEnum.INT,
        "auto_increment": True,
    }
    col_def: str = sqlite_dialect._build_column(col)
    assert "PRIMARY KEY AUTOINCREMENT" in col_def


def test_sqlite_glob_condition(sqlite_dialect: SQLiteDialect) -> None:
    cond = Condition(condition=ConditionEnum.GLOB, identifier="name", value="foo*")
    query_parts: list[str] = []
    params: list[object] = []
    sqlite_dialect._build_condition(query_parts, params, cond)
    result = "".join(query_parts)
    assert "GLOB" in result


def test_sqlite_alter_raises(sqlite_dialect: SQLiteDialect) -> None:
    with pytest.raises(QueryError):
        sqlite_dialect._build_alter("test", {"type": "alter_column"})

    with pytest.raises(QueryError):
        sqlite_dialect._build_alter("test", {"type": "add_primary_key"})
