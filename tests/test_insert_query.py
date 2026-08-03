from __future__ import annotations

import pytest

from flowmaticdb._query_with_params import QueryWithParams
from flowmaticdb.dialects._sql_dialect import SQLDialect
from flowmaticdb.query._insert import InsertQuery


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


def test_insert_with_on_conflict_do_nothing(sql_dialect: SQLDialect, mock_db) -> None:
    """Base ANSI dialect supports column-list ON CONFLICT ... DO NOTHING."""
    q = InsertQuery(sql_dialect, "users", database=mock_db)
    q.values({"id": 1, "name": "John"})
    q.on_conflict_do_nothing(["id"])
    qwp: QueryWithParams = q.to_query_with_params()
    assert 'ON CONFLICT ("id")' in qwp.query
    assert "DO NOTHING" in qwp.query


def test_insert_with_on_conflict_do_nothing_string_raises(
    sql_dialect: SQLDialect, mock_db
) -> None:
    """Base ANSI dialect raises QueryError for string (named) conflicts."""
    from flowmaticdb.exceptions import QueryError

    q = InsertQuery(sql_dialect, "users", database=mock_db)
    q.values({"id": 1, "name": "John"})
    q.on_conflict_do_nothing("users_pkey")
    with pytest.raises(QueryError, match="Named constraint ON CONFLICT"):
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
