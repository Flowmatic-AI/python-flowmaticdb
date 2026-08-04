"""Integration tests for flowmaticdb using SQLite in-memory database."""
from __future__ import annotations

from typing import Any

from flowmaticdb import QueryWithParams
from flowmaticdb.adapters import SQLiteAdapter
from flowmaticdb.database import DB
from flowmaticdb.dialects import SQLiteDialect
from flowmaticdb.query.ddl import Column
from flowmaticdb.result import ResultABC


def test_sqlite_in_memory_crud() -> None:
    """Full CRUD integration test using SQLite in-memory database."""
    adapter = SQLiteAdapter(database_name=":memory:")
    version: str = adapter.version()
    dialect = SQLiteDialect(version=version)

    assert adapter.driver_name == "sqlite"
    assert len(version) > 0

    from flowmaticdb.query.enums import TypeEnum
    qwp: QueryWithParams = dialect.create_table(
        if_not_exists=False,
        table="users",
        columns=[
            Column(name="id", type=TypeEnum.INT, auto_increment=True, not_null=True),
            Column(name="name", type=TypeEnum.STRING, not_null=True),
            Column(name="email", type=TypeEnum.STRING),
            Column(name="age", type=TypeEnum.INT),
            Column(name="active", type=TypeEnum.BOOL, default=True),
        ],
        primary_keys=["id"],
        constraints=None,
    )
    adapter.exec(qwp.query)

    result: ResultABC = adapter.query("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    rows: list[dict] = result.fetch_dicts()
    assert len(rows) == 1
    assert rows[0]["name"] == "users"

    qwp = dialect.insert(
        table="users",
        values=[
            {"name": "Alice", "email": "alice@example.com", "age": 30},
            {"name": "Bob", "email": "bob@example.com", "age": 25},
            {"name": "Charlie", "email": "charlie@example.com", "age": 35},
        ],
        on_conflict=None,
        returning=None,
        last_insert_id=None,
    )
    result = adapter.query_with_params(dialect, qwp)
    assert result is not None

    qwp = dialect.select(
        distinct=None,
        columns=None,
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
    result = adapter.query_with_params(dialect, qwp)
    rows = result.fetch_dicts()
    assert len(rows) == 3

    from flowmaticdb.query import Condition
    from flowmaticdb.query.enums import ConditionEnum
    where: list[Condition] = [Condition(condition=ConditionEnum.EQUALS, identifier="name", value="Alice")]
    qwp = dialect.select(
        distinct=None,
        columns=["id", "name", "email"],
        table="users",
        joins=None,
        where=where,
        group_by=None,
        having=None,
        order_by=None,
        limit=None,
        offset=None,
        unions=None,
    )
    result = adapter.query_with_params(dialect, qwp)
    rows = result.fetch_dicts()
    assert len(rows) == 1
    assert rows[0]["name"] == "Alice"

    where = [Condition(condition=ConditionEnum.EQUALS, identifier="name", value="Bob")]
    qwp = dialect.update(
        table="users",
        updates={"age": 26},
        where=where,
        returning=None,
    )
    adapter.query_with_params(dialect, qwp)

    where = [Condition(condition=ConditionEnum.EQUALS, identifier="name", value="Bob")]
    qwp = dialect.select(
        distinct=None,
        columns=["age"],
        table="users",
        joins=None,
        where=where,
        group_by=None,
        having=None,
        order_by=None,
        limit=None,
        offset=None,
        unions=None,
    )
    result = adapter.query_with_params(dialect, qwp)
    row: dict[str, Any] | None = result.fetch_dict()
    assert row is not None
    assert row["age"] == 26

    where = [Condition(condition=ConditionEnum.EQUALS, identifier="name", value="Charlie")]
    qwp = dialect.delete(table="users", where=where, returning=None)
    adapter.query_with_params(dialect, qwp)

    qwp = dialect.select(
        distinct=None, columns=None, table="users",
        joins=None, where=None, group_by=None, having=None,
        order_by=None, limit=None, offset=None, unions=None,
    )
    result = adapter.query_with_params(dialect, qwp)
    rows = result.fetch_dicts()
    assert len(rows) == 2

    adapter.commit_transaction(dialect.commit_transaction().query)
    adapter.begin_transaction(dialect.begin_transaction().query)
    qwp = dialect.insert(
        table="users",
        values=[{"name": "Dave", "email": "dave@example.com", "age": 40}],
        on_conflict=None, returning=None, last_insert_id=None,
    )
    adapter.query_with_params(dialect, qwp)
    adapter.rollback_transaction(dialect.rollback_transaction().query)

    result = adapter.query("SELECT count(*) AS cnt FROM users")
    row = result.fetch_dict()
    assert row is not None
    assert row["cnt"] == 2

    db = DB(adapter, dialect)
    assert db.adapter is adapter
    assert db.dialect is dialect

    adapter.exec(dialect.drop_table(if_exists=True, table="users").query)
    adapter.close()


def test_database_connect_sqlite() -> None:
    """Test the DB.connect() factory method."""
    db = DB.connect_sqlite(":memory:")
    assert db is not None
    assert db.adapter.driver_name == "sqlite"
    assert db.dialect is not None
    assert db.in_transaction is False


def test_database_drivers() -> None:
    """Test the drivers() static method."""
    drivers: list[str] = DB.drivers()
    assert "sqlite" in drivers
    assert "postgresql" in drivers


def test_query_builder_select_integration() -> None:
    """Test SelectQuery with SQLite adapter."""
    adapter = SQLiteAdapter(database_name=":memory:")
    dialect = SQLiteDialect(version=adapter.version())

    from flowmaticdb.query.enums import TypeEnum
    qwp: QueryWithParams = dialect.create_table(
        if_not_exists=False, table="items",
        columns=[
            Column(name="id", type=TypeEnum.INT, auto_increment=True, not_null=True),
            Column(name="name", type=TypeEnum.STRING),
        ],
        primary_keys=["id"], constraints=None,
    )
    adapter.exec(qwp.query)

    qwp = dialect.insert(
        table="items",
        values=[{"name": "Item A"}, {"name": "Item B"}, {"name": "Item C"}],
        on_conflict=None, returning=None, last_insert_id=None,
    )
    adapter.query_with_params(dialect, qwp)

    from flowmaticdb.database import Database
    from flowmaticdb.query import SelectQuery
    db = Database(adapter, dialect)
    q = SelectQuery(dialect, "items", database=db)
    q.columns(["id", "name"])
    q.where_greater_than("id", 1)
    q.order_by_asc("name")

    qwp = q.to_query_with_params()
    result = adapter.query_with_params(dialect, qwp)
    rows: list[dict] = result.fetch_dicts()
    assert len(rows) == 2

    q2 = SelectQuery(dialect, "items", database=db)
    q2.limit(1)
    qwp2: QueryWithParams = q2.to_query_with_params()
    result2 = adapter.query_with_params(dialect, qwp2)
    rows2: list[dict] = result2.fetch_dicts()
    assert len(rows2) == 1

    adapter.close()


def test_result_scalar() -> None:
    """Test scalar result fetching."""
    adapter = SQLiteAdapter(database_name=":memory:")

    adapter.exec("CREATE TABLE test (val INTEGER)")
    adapter.exec("INSERT INTO test VALUES (42)")

    result: ResultABC = adapter.query("SELECT val FROM test")
    val: Any = result.scalar()
    assert val == 42

    adapter.close()


def test_last_insert_id() -> None:
    """Test last insert ID."""
    adapter = SQLiteAdapter(database_name=":memory:")
    dialect = SQLiteDialect(version=adapter.version())

    from flowmaticdb.query.enums import TypeEnum
    qwp: QueryWithParams = dialect.create_table(
        if_not_exists=False, table="t",
        columns=[Column(name="id", type=TypeEnum.INT, auto_increment=True, not_null=True)],
        primary_keys=["id"], constraints=None,
    )
    adapter.exec(qwp.query)

    adapter.exec("INSERT INTO t DEFAULT VALUES")
    lid: Any = adapter.last_insert_id()
    assert lid is not None
    assert lid >= 1

    adapter.close()
