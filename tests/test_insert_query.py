from __future__ import annotations

import pytest

from flowmaticdb import QueryWithParams
from flowmaticdb.dialects import SQLDialect
from flowmaticdb.query import InsertQuery


def test_insert_simple(sql_dialect: SQLDialect, mock_db) -> None:
    q = InsertQuery(sql_dialect, "users", database=mock_db)
    q.values({"name": "John", "age": 30})
    qwp: QueryWithParams = q.to_query_with_params()
    assert "INSERT INTO" in qwp.query
    assert '"name"' in qwp.query


def test_insert_multiple_rows(sql_dialect: SQLDialect, mock_db) -> None:
    q = InsertQuery(sql_dialect, "users", database=mock_db)
    q.values({"name": "John"}, {"name": "Jane"})
    qwp: QueryWithParams = q.to_query_with_params()
    assert "INSERT INTO" in qwp.query
    assert "VALUES" in qwp.query
    assert qwp.params == ["John", "Jane"]


def test_insert_with_on_conflict_do_nothing_is_a_noop_when_dialect_lacks_support(
    sql_dialect: SQLDialect, mock_db
) -> None:
    """PHP's base SQLDialect::ON_CONFLICT constant is false, so
    buildOnConflict() always returns early regardless of what was requested
    (Database/Dialects/SQLDialect.php `if (!$this->onConflict()) return;`).
    The base ANSI dialect must therefore silently drop the clause rather than
    render it."""
    q = InsertQuery(sql_dialect, "users", database=mock_db)
    q.values({"id": 1, "name": "John"})
    q.on_conflict_do_nothing(["id"])
    qwp: QueryWithParams = q.to_query_with_params()
    assert "ON CONFLICT" not in qwp.query


def test_insert_with_on_conflict_do_nothing(sqlite_dialect) -> None:
    """A dialect that *does* support ON CONFLICT (e.g. modern SQLite) renders
    the column-list clause."""
    from flowmaticdb.database import DatabaseABC

    class _MockDB(DatabaseABC):
        def __init__(self) -> None:
            pass

    q = InsertQuery(sqlite_dialect, "users", database=_MockDB())
    q.values({"id": 1, "name": "John"})
    q.on_conflict_do_nothing(["id"])
    qwp: QueryWithParams = q.to_query_with_params()
    assert 'ON CONFLICT ("id")' in qwp.query
    assert "DO NOTHING" in qwp.query


def test_insert_with_on_conflict_do_nothing_string_raises(sqlite_dialect) -> None:
    """SQLiteDialect::buildOnConflict() explicitly raises for named
    constraints (SQLite has no `ON CONSTRAINT` syntax); the base ANSI
    dialect does not (it never even reaches that branch)."""
    from flowmaticdb import QueryError
    from flowmaticdb.database import DatabaseABC

    class _MockDB(DatabaseABC):
        def __init__(self) -> None:
            pass

    q = InsertQuery(sqlite_dialect, "users", database=_MockDB())
    q.values({"id": 1, "name": "John"})
    q.on_conflict_do_nothing("users_pkey")
    with pytest.raises(QueryError, match="[Nn]amed"):
        q.to_query_with_params()


def test_insert_with_returning(sql_dialect: SQLDialect, mock_db) -> None:
    """Base ANSI dialect doesn't support RETURNING natively."""
    q = InsertQuery(sql_dialect, "users", database=mock_db)
    q.values({"name": "John"})
    q.returning(["id"])
    qwp: QueryWithParams = q.to_query_with_params()
    assert "INSERT INTO" in qwp.query


def test_insert_last_insert_id(sql_dialect: SQLDialect, mock_db) -> None:
    q = InsertQuery(sql_dialect, "users", database=mock_db)
    q.values({"name": "John"})
    q.last_insert_id("id")
    qwp: QueryWithParams = q.to_query_with_params()
    assert "INSERT" in qwp.query
