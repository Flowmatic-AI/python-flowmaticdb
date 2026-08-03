"""Integration tests for flowmaticdb using a real MySQL server (via Docker).

These tests require a running MySQL service reachable on ``localhost:3306``
with user ``root`` and an empty password (the standard ``mysql`` Docker image
launched with ``MYSQL_ALLOW_EMPTY_PASSWORD=yes``).  The ``flowmaticdb`` database is
created automatically on the first run.

The suite mirrors ``tests/test_integration_sqlite.py`` but exercises the
MySQL-specific adapter, dialect and result set implementation:

    * ``MySQLAdapter`` — wraps ``mysql.connector`` and converts ``?`` to ``%s``.
    * ``MySQLDialect`` — backtick escaping, ``ON DUPLICATE KEY UPDATE`` instead
      of ``ON CONFLICT``, no ``RETURNING``, ``TINYINT(1)`` booleans.
    * ``MySQLResult`` — cursor-backed result set.

Run with::

    python3 -m pytest tests/test_integration_mysql.py -v
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import pytest

from flowmaticdb._query_with_params import QueryWithParams
from flowmaticdb.adapters._mysql import MySQLAdapter
from flowmaticdb.database import DB
from flowmaticdb.dialects._mysql import MySQLDialect
from flowmaticdb.query._on_conflict import OnConflict
from flowmaticdb.query._select import SelectQuery
from flowmaticdb.query.enums._type import TypeEnum
from flowmaticdb.result._base import ResultABC

# ---------------------------------------------------------------------------
# Connection constants — match the Docker service described in the module
# docstring.  All tests share the same server; the ``flowmaticdb`` database is
# created lazily by the session-scoped fixture below.
# ---------------------------------------------------------------------------
MYSQL_HOST: str = "localhost"
MYSQL_PORT: int = 3306
MYSQL_USER: str = "root"
MYSQL_PASSWORD: str = ""
MYSQL_DATABASE: str = "flowmaticdb"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _flowmaticdb_database() -> None:
    """Ensure the ``flowmaticdb`` database exists on the MySQL server.

    Connects to the server without selecting a database (using the ``mysql``
    system database) and issues ``CREATE DATABASE IF NOT EXISTS``.  The whole
    test module is skipped if MySQL is not reachable.
    """
    import mysql.connector

    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database="mysql",
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"MySQL server not reachable on {MYSQL_HOST}:{MYSQL_PORT}: {exc}")

    try:
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}`")
        conn.commit()
        cursor.close()
    finally:
        conn.close()


@pytest.fixture
def mysql_adapter(_flowmaticdb_database: None) -> Iterator[MySQLAdapter]:
    """Yield a fresh ``MySQLAdapter`` connected to the ``flowmaticdb`` database.

    All user tables are dropped on teardown so each test starts from a clean
    schema, keeping the suite hermetic.
    """
    adapter = MySQLAdapter(
        database_name=MYSQL_DATABASE,
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
    )
    try:
        yield adapter
    finally:
        # Drop every user table so tests do not leak schema into each other.
        try:
            # Roll back any unfinished transaction so DDL/DROP succeeds.
            try:
                adapter.rollback_transaction()
            except Exception:  # noqa: BLE001, S110
                pass
            result: ResultABC = adapter.query("SHOW TABLES")
            rows: list[dict[str, Any]] = result.fetch_dicts()
            if rows:
                adapter.exec("SET FOREIGN_KEY_CHECKS = 0")
                for row in rows:
                    for table_name in row.values():
                        adapter.exec(f"DROP TABLE IF EXISTS `{table_name}`")
                adapter.exec("SET FOREIGN_KEY_CHECKS = 1")
        finally:
            adapter.close()


@pytest.fixture
def mysql_dialect(mysql_adapter: MySQLAdapter) -> MySQLDialect:
    """Return a ``MySQLDialect`` bound to the live server's version string."""
    return MySQLDialect(version=mysql_adapter.version())


# ---------------------------------------------------------------------------
# Small helpers shared across tests
# ---------------------------------------------------------------------------


def _create_users_table(adapter: MySQLAdapter, dialect: MySQLDialect) -> None:
    """Create a minimal ``users`` table for CRUD-style tests."""
    qwp: QueryWithParams = dialect.create_table(
        if_not_exists=False,
        table="users",
        columns=[
            {"name": "id", "type": TypeEnum.INT, "auto_increment": True, "not_null": True},
            {"name": "name", "type": TypeEnum.STRING, "not_null": True},
            {"name": "email", "type": TypeEnum.STRING},
            {"name": "age", "type": TypeEnum.INT},
            {"name": "active", "type": TypeEnum.BOOL, "default": True},
        ],
        primary_keys=["id"],
        constraints=None,
    )
    adapter.exec(qwp.query)


# ---------------------------------------------------------------------------
# 1. Full CRUD round-trip
# ---------------------------------------------------------------------------


def test_mysql_in_memory_crud(
    mysql_adapter: MySQLAdapter, mysql_dialect: MySQLDialect
) -> None:
    """Full CRUD integration test using the live MySQL server.

    Exercises CREATE TABLE, multi-row INSERT, SELECT (all / filtered), UPDATE
    and DELETE through the dialect + adapter pair.
    """
    adapter, dialect = mysql_adapter, mysql_dialect

    # The driver reports a non-empty version string once connected.
    assert adapter.driver_name == "mysql"
    version: str = adapter.version()
    assert len(version) > 0

    # --- CREATE TABLE -------------------------------------------------------
    _create_users_table(adapter, dialect)

    # Verify the table exists via ``SHOW TABLES``.
    result: ResultABC = adapter.query("SHOW TABLES")
    rows: list[dict[str, Any]] = result.fetch_dicts()
    table_names: list[str] = [str(v) for row in rows for v in row.values()]
    assert "users" in table_names

    # --- INSERT (multi-row, parameterised) ----------------------------------
    qwp: QueryWithParams = dialect.insert(
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

    # --- SELECT * -----------------------------------------------------------
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

    # --- SELECT with WHERE --------------------------------------------------
    from flowmaticdb.query._condition import Condition
    from flowmaticdb.query.enums._condition import ConditionEnum

    where: list[Any] = [
        Condition(condition=ConditionEnum.EQUALS, identifier="name", value="Alice")
    ]
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

    # --- UPDATE -------------------------------------------------------------
    where = [Condition(condition=ConditionEnum.EQUALS, identifier="name", value="Bob")]
    qwp = dialect.update(
        table="users",
        updates={"age": 26},
        where=where,
        returning=None,
    )
    adapter.query_with_params(dialect, qwp)

    # Verify the update persisted.
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

    # --- DELETE -------------------------------------------------------------
    where = [
        Condition(condition=ConditionEnum.EQUALS, identifier="name", value="Charlie")
    ]
    qwp = dialect.delete(table="users", where=where, returning=None)
    adapter.query_with_params(dialect, qwp)

    # Two rows should remain.
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
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# 2. DB.connect("mysql", ...) factory
# ---------------------------------------------------------------------------


def test_mysql_database_connect(_flowmaticdb_database: None) -> None:
    """The ``DB.connect("mysql", "flowmaticdb")`` factory wires adapter + dialect."""
    db = DB.connect_mysql(
        MYSQL_DATABASE,
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
    )
    live_adapter: MySQLAdapter = cast(MySQLAdapter, db.adapter)
    try:
        assert db is not None
        assert live_adapter.driver_name == "mysql"
        assert db.dialect is not None
        assert db.in_transaction is False
    finally:
        live_adapter.close()


# ---------------------------------------------------------------------------
# 3. SelectQuery builder (WHERE / ORDER BY / LIMIT)
# ---------------------------------------------------------------------------


def test_mysql_query_builder_select(
    mysql_adapter: MySQLAdapter, mysql_dialect: MySQLDialect
) -> None:
    """Exercise ``SelectQuery`` against MySQL with WHERE, ORDER BY and LIMIT."""
    adapter, dialect = mysql_adapter, mysql_dialect

    qwp: QueryWithParams = dialect.create_table(
        if_not_exists=False,
        table="items",
        columns=[
            {"name": "id", "type": TypeEnum.INT, "auto_increment": True, "not_null": True},
            {"name": "name", "type": TypeEnum.STRING},
        ],
        primary_keys=["id"],
        constraints=None,
    )
    adapter.exec(qwp.query)

    qwp = dialect.insert(
        table="items",
        values=[{"name": "Item A"}, {"name": "Item B"}, {"name": "Item C"}],
        on_conflict=None,
        returning=None,
        last_insert_id=None,
    )
    adapter.query_with_params(dialect, qwp)

    # SELECT id, name FROM items WHERE id > 1 ORDER BY name ASC
    q: SelectQuery = SelectQuery(dialect, "items")
    q.columns(["id", "name"])
    q.where_greater_than("id", 1)
    q.order_by_asc("name")

    qwp = q.to_query_with_params()
    result: ResultABC = adapter.query_with_params(dialect, qwp)
    rows: list[dict[str, Any]] = result.fetch_dicts()
    assert len(rows) == 2  # ids 2 and 3
    assert rows[0]["name"] == "Item B"
    assert rows[1]["name"] == "Item C"

    # LIMIT clause.
    q2: SelectQuery = SelectQuery(dialect, "items")
    q2.limit(1)
    qwp2: QueryWithParams = q2.to_query_with_params()
    result2: ResultABC = adapter.query_with_params(dialect, qwp2)
    rows2: list[dict[str, Any]] = result2.fetch_dicts()
    assert len(rows2) == 1


# ---------------------------------------------------------------------------
# 4. JOINs (inner / left / right / cross)
# ---------------------------------------------------------------------------


def test_mysql_joins(
    mysql_adapter: MySQLAdapter, mysql_dialect: MySQLDialect
) -> None:
    """Exercise inner, left, right and cross joins with ``.on()`` conditions."""
    adapter, dialect = mysql_adapter, mysql_dialect

    users_qwp: QueryWithParams = dialect.create_table(
        if_not_exists=False,
        table="users",
        columns=[
            {"name": "id", "type": TypeEnum.INT, "auto_increment": True, "not_null": True},
            {"name": "name", "type": TypeEnum.STRING, "not_null": True},
        ],
        primary_keys=["id"],
        constraints=None,
    )
    adapter.exec(users_qwp.query)

    posts_qwp: QueryWithParams = dialect.create_table(
        if_not_exists=False,
        table="posts",
        columns=[
            {"name": "id", "type": TypeEnum.INT, "auto_increment": True, "not_null": True},
            {"name": "user_id", "type": TypeEnum.INT},
            {"name": "title", "type": TypeEnum.STRING},
        ],
        primary_keys=["id"],
        constraints=[
            {
                "type": "foreign_key",
                "columns": ["user_id"],
                "ref_table": "users",
                "ref_columns": ["id"],
                "on_delete": "CASCADE",
            }
        ],
    )
    adapter.exec(posts_qwp.query)

    adapter.query_with_params(
        dialect,
        dialect.insert(
            table="users",
            values=[{"name": "Alice"}, {"name": "Bob"}],
            on_conflict=None,
            returning=None,
            last_insert_id=None,
        ),
    )
    adapter.query_with_params(
        dialect,
        dialect.insert(
            table="posts",
            values=[
                {"user_id": 1, "title": "Alice post 1"},
                {"user_id": 1, "title": "Alice post 2"},
                {"user_id": 2, "title": "Bob post 1"},
            ],
            on_conflict=None,
            returning=None,
            last_insert_id=None,
        ),
    )

    # --- INNER JOIN ---------------------------------------------------------
    # ``name`` only exists on users, ``title`` only on posts → unqualified
    # references are unambiguous.  We avoid the ambiguous ``id`` column.
    q: SelectQuery = SelectQuery(dialect, "users")
    q.columns(["name", "title"])
    j = q.inner_join("posts")
    j.on(["users", "id"], ["posts", "user_id"])
    q.order_by_asc("title")

    qwp: QueryWithParams = q.to_query_with_params()
    result: ResultABC = adapter.query_with_params(dialect, qwp)
    rows: list[dict[str, Any]] = result.fetch_dicts()
    assert len(rows) == 3  # every user has posts
    assert [r["title"] for r in rows] == ["Alice post 1", "Alice post 2", "Bob post 1"]

    # --- LEFT JOIN (include a user with no posts) ---------------------------
    # Add a third user without posts.
    adapter.query_with_params(
        dialect,
        dialect.insert(
            table="users",
            values=[{"name": "Carol"}],
            on_conflict=None,
            returning=None,
            last_insert_id=None,
        ),
    )

    q2: SelectQuery = SelectQuery(dialect, "users")
    q2.columns(["name", "title"])
    lj = q2.left_join("posts")
    lj.on(["users", "id"], ["posts", "user_id"])
    q2.order_by_asc("name")

    qwp2: QueryWithParams = q2.to_query_with_params()
    result2: ResultABC = adapter.query_with_params(dialect, qwp2)
    rows2: list[dict[str, Any]] = result2.fetch_dicts()
    # Carol (id 3) has no posts → LEFT JOIN keeps her row with NULL title.
    assert len(rows2) == 4
    carol = [r for r in rows2 if r["name"] == "Carol"]
    assert len(carol) == 1
    assert carol[0]["title"] is None

    # --- RIGHT JOIN (via raw join expression; JoinEnum has no RIGHT) --------
    # ``JoinsMixin.join()`` accepts a ``SqlABC`` expression, so wrap the raw
    # SQL in ``raw(...)`` — a bare string would be silently ignored.
    from flowmaticdb.helpers import raw as raw_expr

    q3: SelectQuery = SelectQuery(dialect, "users")
    q3.columns(["name", "title"])
    q3.join(raw_expr("RIGHT JOIN `posts` ON `users`.`id` = `posts`.`user_id`"))
    q3.order_by_asc("title")

    qwp3: QueryWithParams = q3.to_query_with_params()
    result3: ResultABC = adapter.query_with_params(dialect, qwp3)
    rows3: list[dict[str, Any]] = result3.fetch_dicts()
    # Every post is returned (all belong to users, so no NULL user side).
    assert len(rows3) == 3
    assert [r["title"] for r in rows3] == ["Alice post 1", "Alice post 2", "Bob post 1"]

    # --- CROSS JOIN ---------------------------------------------------------
    q4: SelectQuery = SelectQuery(dialect, "users")
    q4.columns(["name", "title"])
    cj = q4.cross_join("posts")
    # CROSS JOIN with no ON → cartesian product.
    assert cj.conditions == []

    qwp4: QueryWithParams = q4.to_query_with_params()
    result4: ResultABC = adapter.query_with_params(dialect, qwp4)
    rows4: list[dict[str, Any]] = result4.fetch_dicts()
    # 3 users × 3 posts = 9 rows.
    assert len(rows4) == 9


# ---------------------------------------------------------------------------
# 5. WHERE conditions
# ---------------------------------------------------------------------------


def test_mysql_conditions(
    mysql_adapter: MySQLAdapter, mysql_dialect: MySQLDialect
) -> None:
    """Exercise the full ``where_*`` fluent API against MySQL."""
    adapter, dialect = mysql_adapter, mysql_dialect

    qwp: QueryWithParams = dialect.create_table(
        if_not_exists=False,
        table="products",
        columns=[
            {"name": "id", "type": TypeEnum.INT, "auto_increment": True, "not_null": True},
            {"name": "name", "type": TypeEnum.STRING, "not_null": True},
            {"name": "price", "type": TypeEnum.INT},
            {"name": "category", "type": TypeEnum.STRING},
            {"name": "in_stock", "type": TypeEnum.BOOL, "default": True},
        ],
        primary_keys=["id"],
        constraints=None,
    )
    adapter.exec(qwp.query)

    adapter.query_with_params(
        dialect,
        dialect.insert(
            table="products",
            values=[
                {"name": "Widget", "price": 10, "category": "A", "in_stock": True},
                {"name": "Gadget", "price": 25, "category": "B", "in_stock": False},
                {"name": "Gizmo", "price": 50, "category": "A", "in_stock": True},
                {"name": "Thingy", "price": 75, "category": "C", "in_stock": None},
            ],
            on_conflict=None,
            returning=None,
            last_insert_id=None,
        ),
    )

    def _rows(q: SelectQuery) -> list[dict[str, Any]]:
        qwp_ = q.to_query_with_params()
        rows: list[dict[str, Any]] = adapter.query_with_params(dialect, qwp_).fetch_dicts()
        return rows

    # where_equals
    q = SelectQuery(dialect, "products").columns(["name"])
    q.where_equals("name", "Widget")
    assert [r["name"] for r in _rows(q)] == ["Widget"]

    # where_in
    q = SelectQuery(dialect, "products").columns(["name"])
    q.where_in("category", ["A", "C"])
    names = sorted(r["name"] for r in _rows(q))
    assert names == ["Gizmo", "Thingy", "Widget"]

    # where_between
    q = SelectQuery(dialect, "products").columns(["name"])
    q.where_between("price", 20, 60)
    names = sorted(r["name"] for r in _rows(q))
    assert names == ["Gadget", "Gizmo"]

    # where_not_between
    q = SelectQuery(dialect, "products").columns(["name"])
    q.where_not_between("price", 20, 60)
    names = sorted(r["name"] for r in _rows(q))
    assert names == ["Thingy", "Widget"]

    # where_like
    q = SelectQuery(dialect, "products").columns(["name"])
    q.where_like("name", "G%")
    names = sorted(r["name"] for r in _rows(q))
    assert names == ["Gadget", "Gizmo"]

    # where_starts_with
    q = SelectQuery(dialect, "products").columns(["name"])
    q.where_starts_with("name", "Wi")
    assert [r["name"] for r in _rows(q)] == ["Widget"]

    # where_ends_with
    q = SelectQuery(dialect, "products").columns(["name"])
    q.where_ends_with("name", "et")
    names = sorted(r["name"] for r in _rows(q))
    assert names == ["Gadget", "Widget"]

    # where_contains
    q = SelectQuery(dialect, "products").columns(["name"])
    q.where_contains("name", "adge")
    assert [r["name"] for r in _rows(q)] == ["Gadget"]

    # where_is_null
    q = SelectQuery(dialect, "products").columns(["name"])
    q.where_is_null("in_stock")
    assert [r["name"] for r in _rows(q)] == ["Thingy"]

    # where_is_not_null
    q = SelectQuery(dialect, "products").columns(["name"])
    q.where_is_not_null("in_stock")
    names = sorted(r["name"] for r in _rows(q))
    assert names == ["Gadget", "Gizmo", "Widget"]

    # where_greater_than / where_less_than_or_equals
    q = SelectQuery(dialect, "products").columns(["name"])
    q.where_greater_than("price", 25)
    names = sorted(r["name"] for r in _rows(q))
    assert names == ["Gizmo", "Thingy"]

    q = SelectQuery(dialect, "products").columns(["name"])
    q.where_less_than_or_equals("price", 25)
    names = sorted(r["name"] for r in _rows(q))
    assert names == ["Gadget", "Widget"]

    # where_not_equals
    q = SelectQuery(dialect, "products").columns(["name"])
    q.where_not_equals("category", "A")
    names = sorted(r["name"] for r in _rows(q))
    assert names == ["Gadget", "Thingy"]

    # where_not_in
    q = SelectQuery(dialect, "products").columns(["name"])
    q.where_not_in("category", ["A"])
    names = sorted(r["name"] for r in _rows(q))
    assert names == ["Gadget", "Thingy"]

    # where_regex (MySQL REGEXP)
    q = SelectQuery(dialect, "products").columns(["name"])
    q.where_regex("name", "^G.*o$")
    names = sorted(r["name"] for r in _rows(q))
    assert names == ["Gizmo"]


# ---------------------------------------------------------------------------
# 6. Transactions & savepoints
# ---------------------------------------------------------------------------


def test_mysql_transactions(
    mysql_adapter: MySQLAdapter, mysql_dialect: MySQLDialect
) -> None:
    """Verify BEGIN/COMMIT/ROLLBACK and SAVEPOINT behaviour."""
    adapter, dialect = mysql_adapter, mysql_dialect

    qwp: QueryWithParams = dialect.create_table(
        if_not_exists=False,
        table="accounts",
        columns=[
            {"name": "id", "type": TypeEnum.INT, "auto_increment": True, "not_null": True},
            {"name": "balance", "type": TypeEnum.INT},
        ],
        primary_keys=["id"],
        constraints=None,
    )
    adapter.exec(qwp.query)

    insert_qwp: QueryWithParams = dialect.insert(
        table="accounts",
        values=[{"balance": 100}],
        on_conflict=None,
        returning=None,
        last_insert_id=None,
    )

    def _count() -> int:
        """Read the current row count."""
        result: ResultABC = adapter.query("SELECT COUNT(*) AS cnt FROM accounts")
        row: dict[str, Any] | None = result.fetch_dict()
        assert row is not None
        return int(row["cnt"])

    assert _count() == 0

    # --- ROLLBACK discards the insert --------------------------------------
    adapter.begin_transaction()
    assert adapter.in_transaction is True
    adapter.query_with_params(dialect, insert_qwp)
    adapter.rollback_transaction()
    assert adapter.in_transaction is False
    assert _count() == 0

    # --- COMMIT persists the insert ----------------------------------------
    adapter.begin_transaction()
    adapter.query_with_params(dialect, insert_qwp)
    adapter.commit_transaction()
    assert adapter.in_transaction is False
    assert _count() == 1

    # --- SAVEPOINT rollback does not undo the outer transaction ------------
    adapter.begin_transaction()
    adapter.query_with_params(dialect, insert_qwp)  # second row

    adapter.begin_savepoint("sp1")
    adapter.query_with_params(dialect, insert_qwp)  # third row (inside savepoint)
    adapter.rollback_savepoint("sp1")  # discard the third row only

    adapter.commit_transaction()  # commit the second row
    assert _count() == 2  # first commit + second commit; savepoint rolled back

    # --- SAVEPOINT release (commit) keeps the savepoint's work -------------
    adapter.begin_transaction()
    adapter.query_with_params(dialect, insert_qwp)  # third row

    adapter.begin_savepoint("sp2")
    adapter.query_with_params(dialect, insert_qwp)  # fourth row (inside savepoint)
    adapter.commit_savepoint("sp2")  # release → keep the row

    adapter.rollback_transaction()  # rolling back outer tx discards everything
    assert _count() == 2  # unchanged from before the last transaction


# ---------------------------------------------------------------------------
# 7. INSERT ... ON DUPLICATE KEY UPDATE
# ---------------------------------------------------------------------------


def test_mysql_on_duplicate_key(
    mysql_adapter: MySQLAdapter, mysql_dialect: MySQLDialect
) -> None:
    """``on_conflict_do_update`` renders as MySQL ``ON DUPLICATE KEY UPDATE``."""
    adapter, dialect = mysql_adapter, mysql_dialect

    qwp: QueryWithParams = dialect.create_table(
        if_not_exists=False,
        table="kv",
        columns=[
            {"name": "id", "type": TypeEnum.INT, "auto_increment": True, "not_null": True},
            {"name": "key", "type": TypeEnum.STRING, "not_null": True},
            {"name": "value", "type": TypeEnum.STRING},
        ],
        primary_keys=["id"],
        constraints=[{"type": "unique", "columns": ["key"]}],
    )
    adapter.exec(qwp.query)

    # Initial insert.
    adapter.query_with_params(
        dialect,
        dialect.insert(
            table="kv",
            values=[{"key": "greeting", "value": "hello"}],
            on_conflict=None,
            returning=None,
            last_insert_id=None,
        ),
    )

    # Build the ON DUPLICATE KEY UPDATE query via the dialect directly so we
    # can also assert the generated SQL shape.
    qwp = dialect.insert(
        table="kv",
        values=[{"key": "greeting", "value": "world"}],
        on_conflict=OnConflict(conflict="key", updates={"value": "world"}),
        returning=None,
        last_insert_id=None,
    )
    assert "ON DUPLICATE KEY UPDATE" in qwp.query
    adapter.query_with_params(dialect, qwp)

    # The row should be updated, not duplicated.
    result: ResultABC = adapter.query("SELECT COUNT(*) AS cnt FROM kv")
    row: dict[str, Any] | None = result.fetch_dict()
    assert row is not None
    assert row["cnt"] == 1

    result = adapter.query("SELECT `value` AS v FROM kv WHERE `key` = 'greeting'")
    row = result.fetch_dict()
    assert row is not None
    assert row["v"] == "world"

    # --- DO NOTHING → INSERT IGNORE ----------------------------------------
    qwp = dialect.insert(
        table="kv",
        values=[{"key": "greeting", "value": "ignored"}],
        on_conflict=OnConflict(conflict="key", updates=None),
        returning=None,
        last_insert_id=None,
    )
    assert qwp.query.startswith("INSERT IGNORE INTO ")
    adapter.query_with_params(dialect, qwp)

    result = adapter.query("SELECT `value` AS v FROM kv WHERE `key` = 'greeting'")
    row = result.fetch_dict()
    assert row is not None
    assert row["v"] == "world"  # unchanged

    # --- Update-all (empty updates dict → VALUES(col)) ---------------------
    qwp = dialect.insert(
        table="kv",
        values=[{"key": "greeting", "value": "from_values"}],
        on_conflict=OnConflict(conflict="key", updates={}),
        returning=None,
        last_insert_id=None,
    )
    adapter.query_with_params(dialect, qwp)
    result = adapter.query("SELECT `value` AS v FROM kv WHERE `key` = 'greeting'")
    row = result.fetch_dict()
    assert row is not None
    assert row["v"] == "from_values"


# ---------------------------------------------------------------------------
# 8. ALTER TABLE
# ---------------------------------------------------------------------------


def test_mysql_alter_table(
    mysql_adapter: MySQLAdapter, mysql_dialect: MySQLDialect
) -> None:
    """Exercise ADD / MODIFY / RENAME / DROP COLUMN + UNIQUE + FOREIGN KEY."""
    adapter, dialect = mysql_adapter, mysql_dialect

    # Parent table for the FK test.
    parent_qwp: QueryWithParams = dialect.create_table(
        if_not_exists=False,
        table="categories",
        columns=[
            {"name": "id", "type": TypeEnum.INT, "auto_increment": True, "not_null": True},
            {"name": "name", "type": TypeEnum.STRING, "not_null": True},
        ],
        primary_keys=["id"],
        constraints=None,
    )
    adapter.exec(parent_qwp.query)

    # Child table to ALTER.
    child_qwp: QueryWithParams = dialect.create_table(
        if_not_exists=False,
        table="articles",
        columns=[
            {"name": "id", "type": TypeEnum.INT, "auto_increment": True, "not_null": True},
            {"name": "title", "type": TypeEnum.STRING, "not_null": True},
        ],
        primary_keys=["id"],
        constraints=None,
    )
    adapter.exec(child_qwp.query)

    # ADD COLUMN
    for qwp_ in dialect.alter_table(
        "articles",
        [{"type": "add_column", "column": {"name": "body", "type": TypeEnum.STRING}}],
    ):
        adapter.exec(qwp_.query)

    cols = _column_names(adapter, "articles")
    assert "body" in cols

    # MODIFY COLUMN (widen title to VARCHAR(100))
    for qwp_ in dialect.alter_table(
        "articles",
        [{"type": "alter_column", "column": {"name": "title", "type": TypeEnum.STRING, "bits": 100}}],
    ):
        adapter.exec(qwp_.query)
    # MySQL stores the new length in information_schema.
    assert _column_type(adapter, "articles", "title") == "varchar(100)"

    # RENAME COLUMN title → headline
    for qwp_ in dialect.alter_table(
        "articles",
        [{"type": "rename_column", "old_name": "title", "new_name": "headline"}],
    ):
        adapter.exec(qwp_.query)
    cols = _column_names(adapter, "articles")
    assert "headline" in cols
    assert "title" not in cols

    # ADD UNIQUE on body
    for qwp_ in dialect.alter_table(
        "articles",
        [{"type": "add_unique", "columns": ["body"], "name": "uq_articles_body"}],
    ):
        adapter.exec(qwp_.query)
    assert _has_index(adapter, "articles", "uq_articles_body")

    # ADD FOREIGN KEY articles.category_id → categories.id
    # First add the column we will reference.
    for qwp_ in dialect.alter_table(
        "articles",
        [{"type": "add_column", "column": {"name": "category_id", "type": TypeEnum.INT}}],
    ):
        adapter.exec(qwp_.query)

    for qwp_ in dialect.alter_table(
        "articles",
        [
            {
                "type": "add_foreign_key",
                "columns": ["category_id"],
                "ref_table": "categories",
                "ref_columns": ["id"],
                "name": "fk_articles_category",
                "on_delete": "CASCADE",
            }
        ],
    ):
        adapter.exec(qwp_.query)
    assert _has_fk(adapter, "articles", "fk_articles_category")

    # DROP COLUMN body
    for qwp_ in dialect.alter_table(
        "articles",
        [{"type": "drop_column", "column": "body"}],
    ):
        adapter.exec(qwp_.query)
    cols = _column_names(adapter, "articles")
    assert "body" not in cols


def _column_names(adapter: MySQLAdapter, table: str) -> list[str]:
    """Return the column names of *table* in declaration order."""
    result: ResultABC = adapter.query(
        "SELECT `COLUMN_NAME` AS c FROM `information_schema`.`COLUMNS` "
        f"WHERE `TABLE_SCHEMA` = '{MYSQL_DATABASE}' AND `TABLE_NAME` = '{table}' "
        "ORDER BY `ORDINAL_POSITION`"
    )
    return [r["c"] for r in result.fetch_dicts()]


def _column_type(adapter: MySQLAdapter, table: str, column: str) -> str:
    """Return the lower-cased SQL column type string for *table.column*.

    Uses ``COLUMN_TYPE`` from ``information_schema`` so the full spec including
    length (e.g. ``varchar(100)``, ``tinyint(1)``) is returned.
    """
    result: ResultABC = adapter.query(
        "SELECT `COLUMN_TYPE` AS t FROM `information_schema`.`COLUMNS` "
        f"WHERE `TABLE_SCHEMA` = '{MYSQL_DATABASE}' AND `TABLE_NAME` = '{table}' "
        f"AND `COLUMN_NAME` = '{column}'"
    )
    row: dict[str, Any] | None = result.fetch_dict()
    assert row is not None
    return str(row["t"]).lower()


def _has_index(adapter: MySQLAdapter, table: str, index_name: str) -> bool:
    result: ResultABC = adapter.query(
        "SELECT COUNT(*) AS cnt FROM `information_schema`.`STATISTICS` "
        f"WHERE `TABLE_SCHEMA` = '{MYSQL_DATABASE}' AND `TABLE_NAME` = '{table}' "
        f"AND `INDEX_NAME` = '{index_name}'"
    )
    row: dict[str, Any] | None = result.fetch_dict()
    return bool(row and int(row["cnt"]) > 0)


def _has_fk(adapter: MySQLAdapter, table: str, constraint_name: str) -> bool:
    result: ResultABC = adapter.query(
        "SELECT COUNT(*) AS cnt FROM `information_schema`.`KEY_COLUMN_USAGE` "
        f"WHERE `TABLE_SCHEMA` = '{MYSQL_DATABASE}' AND `TABLE_NAME` = '{table}' "
        f"AND `CONSTRAINT_NAME` = '{constraint_name}' "
        "AND `REFERENCED_TABLE_NAME` IS NOT NULL"
    )
    row: dict[str, Any] | None = result.fetch_dict()
    return bool(row and int(row["cnt"]) > 0)


# ---------------------------------------------------------------------------
# 9. DDL — CREATE TABLE with several column types + DROP TABLE
# ---------------------------------------------------------------------------


def test_mysql_ddl(
    mysql_adapter: MySQLAdapter, mysql_dialect: MySQLDialect
) -> None:
    """Create a table exercising every ``TypeEnum`` then drop it."""
    adapter, dialect = mysql_adapter, mysql_dialect

    qwp: QueryWithParams = dialect.create_table(
        if_not_exists=False,
        table="typed",
        columns=[
            {"name": "id", "type": TypeEnum.INT, "auto_increment": True, "not_null": True},
            {"name": "flag", "type": TypeEnum.BOOL, "default": False},
            {"name": "score", "type": TypeEnum.FLOAT},
            {"name": "label", "type": TypeEnum.STRING, "not_null": True},
            {"name": "created_at", "type": TypeEnum.DATETIME},
        ],
        primary_keys=["id"],
        constraints=None,
    )
    adapter.exec(qwp.query)

    cols = _column_names(adapter, "typed")
    assert cols == ["id", "flag", "score", "label", "created_at"]

    # Booleans come back as TINYINT(1) in MySQL.
    assert _column_type(adapter, "typed", "flag") == "tinyint(1)"

    # Insert a row with a bool and verify round-trip cast (1/0).
    adapter.query_with_params(
        dialect,
        dialect.insert(
            table="typed",
            values=[
                {"flag": True, "score": 1.5, "label": "row1", "created_at": None}
            ],
            on_conflict=None,
            returning=None,
            last_insert_id=None,
        ),
    )
    result: ResultABC = adapter.query("SELECT `flag` AS f, `score` AS s FROM typed")
    row: dict[str, Any] | None = result.fetch_dict()
    assert row is not None
    assert row["f"] == 1  # MySQL stores TINYINT(1)
    assert float(row["s"]) == 1.5

    # DROP TABLE
    drop_qwp: QueryWithParams = dialect.drop_table(if_exists=True, table="typed")
    adapter.exec(drop_qwp.query)

    result = adapter.query("SHOW TABLES")
    rows: list[dict[str, Any]] = result.fetch_dicts()
    names = [str(v) for r in rows for v in r.values()]
    assert "typed" not in names


# ---------------------------------------------------------------------------
# 10. Giant SELECT — every condition flavour, joins, group/having, union
# ---------------------------------------------------------------------------


def test_mysql_giant_select(
    mysql_adapter: MySQLAdapter, mysql_dialect: MySQLDialect
) -> None:
    """Build a maximal query exercising every supported SELECT feature."""
    adapter, dialect = mysql_adapter, mysql_dialect

    # --- Schema -------------------------------------------------------------
    users_qwp: QueryWithParams = dialect.create_table(
        if_not_exists=False,
        table="users",
        columns=[
            {"name": "id", "type": TypeEnum.INT, "auto_increment": True, "not_null": True},
            {"name": "name", "type": TypeEnum.STRING, "not_null": True},
            {"name": "age", "type": TypeEnum.INT},
            {"name": "email", "type": TypeEnum.STRING},
        ],
        primary_keys=["id"],
        constraints=[{"type": "unique", "columns": ["email"]}],
    )
    adapter.exec(users_qwp.query)

    posts_qwp: QueryWithParams = dialect.create_table(
        if_not_exists=False,
        table="posts",
        columns=[
            {"name": "id", "type": TypeEnum.INT, "auto_increment": True, "not_null": True},
            {"name": "user_id", "type": TypeEnum.INT, "not_null": True},
            {"name": "title", "type": TypeEnum.STRING, "not_null": True},
            {"name": "views", "type": TypeEnum.INT},
        ],
        primary_keys=["id"],
        constraints=[
            {
                "type": "foreign_key",
                "columns": ["user_id"],
                "ref_table": "users",
                "ref_columns": ["id"],
                "on_delete": "CASCADE",
            }
        ],
    )
    adapter.exec(posts_qwp.query)

    adapter.query_with_params(
        dialect,
        dialect.insert(
            table="users",
            values=[
                {"name": "Alice", "age": 30, "email": "alice@example.com"},
                {"name": "Bob", "age": 22, "email": "bob@example.com"},
                {"name": "Carol", "age": 40, "email": "carol@example.com"},
            ],
            on_conflict=None,
            returning=None,
            last_insert_id=None,
        ),
    )
    adapter.query_with_params(
        dialect,
        dialect.insert(
            table="posts",
            values=[
                {"user_id": 1, "title": "Hello World", "views": 100},
                {"user_id": 1, "title": "Second Post", "views": 50},
                {"user_id": 2, "title": "Bob Says Hi", "views": 10},
                {"user_id": 3, "title": "Carol Corner", "views": 999},
            ],
            on_conflict=None,
            returning=None,
            last_insert_id=None,
        ),
    )

    # --- Build the giant query ---------------------------------------------
    # Qualified column references are expressed as ``Identifier(["t","col"])``
    # so the dialect emits `` `t`.`col` `` rather than treating ``"t.col"`` as
    # a single (non-existent) identifier.  Aggregate expressions use ``raw()``
    # since the fluent API has no first-class aggregate builder.
    from flowmaticdb.helpers import identifier, raw

    q: SelectQuery = SelectQuery(dialect, "users")
    q.columns(
        [
            identifier(["users", "id"]),
            identifier(["users", "name"]),
            raw("COUNT(`posts`.`id`) AS post_count"),
            raw("SUM(`posts`.`views`) AS total_views"),
        ]
    )

    inner = q.inner_join("posts")
    inner.on(["users", "id"], ["posts", "user_id"])

    # Every supported condition flavour (identifiers passed as two-element
    # lists so the qualifier is preserved).
    q.where_greater_than(["users", "age"], 18)
    q.where_in(["users", "id"], [1, 2, 3])
    q.where_not_in(["users", "name"], ["Zoe"])
    q.where_between(["users", "age"], 20, 45)
    q.where_like(["users", "email"], "%@example.com")
    q.where_is_not_null(["posts", "title"])
    q.where_starts_with(["users", "name"], "")
    q.where_ends_with(["users", "email"], ".com")
    q.where_contains(["users", "email"], "@")

    q.group_by([["users", "id"], ["users", "name"]])
    q.having_greater_than("post_count", 0)
    q.order_by_desc("total_views")
    q.limit(10)

    # A UNION branch that selects Carol again so we can assert it merges.
    # UNION requires both branches to have the same number of columns, so we
    # pad the branch with NULLs for the aggregate columns.
    union_q: SelectQuery = SelectQuery(dialect, "users")
    union_q.columns(
        [
            identifier(["users", "id"]),
            identifier(["users", "name"]),
            raw("NULL AS post_count"),
            raw("NULL AS total_views"),
        ]
    )
    union_q.where_equals(["users", "name"], "Carol")
    q.union(union_q)

    qwp: QueryWithParams = q.to_query_with_params()

    # Sanity-check the generated SQL shape (MySQL placeholders, no RETURNING).
    # The query is wrapped in parentheses because UNION is combined with
    # LIMIT, so it starts with "(" not "SELECT".
    assert qwp.query.startswith("(")
    assert "SELECT" in qwp.query
    assert "RETURNING" not in qwp.query
    assert "ON DUPLICATE" not in qwp.query
    assert "?" in qwp.query  # parameterised
    assert "INNER JOIN" in qwp.query
    assert "GROUP BY" in qwp.query
    assert "HAVING" in qwp.query
    assert "ORDER BY" in qwp.query
    assert "LIMIT" in qwp.query
    assert "UNION" in qwp.query
    # Qualified identifiers must be split into `` `t`.`c` ``, not `` `t.c` ``.
    assert "`users`.`id`" in qwp.query
    assert "`users`.`age`" in qwp.query

    # --- Execute & assert ---------------------------------------------------
    result: ResultABC = adapter.query_with_params(dialect, qwp)
    rows: list[dict[str, Any]] = result.fetch_dicts()

    # The main branch returns 3 grouped rows (Alice 2, Bob 1, Carol 1).
    # The UNION adds Carol's id+name again.  Because the column lists differ
    # between the two branches (the union branch has no post_count/total_views
    # columns) MySQL fills them with NULL — that is fine, we just assert the
    # main rows are present and ordered.
    main_rows = [r for r in rows if r["post_count"] is not None]
    assert len(main_rows) == 3

    # Ordered by total_views DESC → Carol (999), Alice (150), Bob (10).
    names_in_order = [r["name"] for r in main_rows]
    assert names_in_order == ["Carol", "Alice", "Bob"]

    carol = next(r for r in main_rows if r["name"] == "Carol")
    assert int(carol["post_count"]) == 1
    assert int(carol["total_views"]) == 999
