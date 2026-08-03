"""Integration tests for flowmaticdb using a live PostgreSQL service.

These tests require a running PostgreSQL instance reachable on
``localhost:5432`` with trust authentication and a ``postgres`` database.
The docker-compose.yml at the repository root provides such a service via::

    docker compose up -d postgres

When PostgreSQL is not reachable every test in this module is skipped, so
the suite remains green in environments without the service (mirroring the
philosophy of the SQLite in-memory integration tests, which need no external
services).
"""
from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest

from flowmaticdb._helpers import expression, identifier, raw
from flowmaticdb._query_with_params import QueryWithParams
from flowmaticdb.adapters._base import AdapterABC
from flowmaticdb.adapters._postgres import PsycopgAdapter
from flowmaticdb.database import DB
from flowmaticdb.dialects._postgres import PostgresqlDialect
from flowmaticdb.query._alter_table import AlterTableQuery
from flowmaticdb.query._condition import Condition
from flowmaticdb.query._create_table import CreateTableQuery
from flowmaticdb.query._insert import InsertQuery
from flowmaticdb.query._on_conflict import OnConflict
from flowmaticdb.query._select import SelectQuery
from flowmaticdb.query.enums._condition import ConditionEnum
from flowmaticdb.query.enums._type import TypeEnum
from flowmaticdb.query.expressions._alias import Alias
from flowmaticdb.query.expressions._excluded import Excluded
from flowmaticdb.result._base import ResultABC

# Connection parameters for the dockerized PostgreSQL service.
PG_HOST: str = "localhost"
PG_PORT: int = 5432
PG_DBNAME: str = "postgres"
PG_USER: str = "postgres"
PG_PASSWORD: str = ""


def _postgres_reachable(timeout: float = 1.0) -> bool:
    """Return True when a TCP connection to the PostgreSQL port succeeds."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((PG_HOST, PG_PORT)) == 0
    finally:
        sock.close()


# Skip the entire module when PostgreSQL is not running. Importing psycopg
# unconditionally would also be fine, but the skip keeps the suite portable.
pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason=f"PostgreSQL not reachable at {PG_HOST}:{PG_PORT}; run `docker compose up -d postgres`.",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pg_adapter() -> Iterator[PsycopgAdapter]:
    """Yield a connected PsycopgAdapter; close it after the test."""
    adapter = PsycopgAdapter(
        database_name=PG_DBNAME,
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
    )
    try:
        yield adapter
    finally:
        adapter.close()


@pytest.fixture
def pg_dialect(pg_adapter: PsycopgAdapter) -> PostgresqlDialect:
    """Return a PostgresqlDialect bound to the live server version."""
    return PostgresqlDialect(version=pg_adapter.version())


@pytest.fixture
def pg_db() -> Iterator[DB]:
    """Yield a DB facade connected to PostgreSQL; close afterwards."""
    db = DB.connect_postgresql(
        PG_DBNAME,
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
    )
    try:
        yield db
    finally:
        db.adapter.close()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _drop(adapter: AdapterABC, *tables: str) -> None:
    """Drop the given tables if they exist, using CASCADE for safety."""
    for table in tables:
        adapter.exec(f'DROP TABLE IF EXISTS "{table}" CASCADE')


# ---------------------------------------------------------------------------
# 1. CRUD
# ---------------------------------------------------------------------------


def test_postgres_crud(pg_adapter: PsycopgAdapter, pg_dialect: PostgresqlDialect) -> None:
    """Full CRUD lifecycle against PostgreSQL via the PsycopgAdapter.

    Verifies CREATE TABLE (DDL via exec), INSERT/SELECT/UPDATE/DELETE
    (DML via query_with_params with native prepared statements) and that
    the double-quote escaping and ``%s`` placeholder conversion behave
    correctly.
    """
    adapter, dialect = pg_adapter, pg_dialect
    _drop(adapter, "crud_users")

    qwp: QueryWithParams = dialect.create_table(
        if_not_exists=False,
        table="crud_users",
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

    # Verify the table exists in pg_class.
    result: ResultABC = adapter.query(
        "SELECT table_name FROM information_schema.tables WHERE table_name = 'crud_users'"
    )
    rows: list[dict[str, Any]] = result.fetch_dicts()
    assert len(rows) == 1

    # INSERT (multi-row) — DML uses prepared statements via query_with_params.
    qwp = dialect.insert(
        table="crud_users",
        values=[
            {"name": "Alice", "email": "alice@example.com", "age": 30},
            {"name": "Bob", "email": "bob@example.com", "age": 25},
            {"name": "Charlie", "email": "charlie@example.com", "age": 35},
        ],
        on_conflict=None,
        returning=None,
        last_insert_id=None,
    )
    adapter.query_with_params(dialect, qwp)

    # SELECT all.
    qwp = dialect.select(
        distinct=None, columns=None, table="crud_users", joins=None, where=None,
        group_by=None, having=None, order_by=None, limit=None, offset=None, unions=None,
    )
    rows = adapter.query_with_params(dialect, qwp).fetch_dicts()
    assert len(rows) == 3

    # SELECT with WHERE.
    where: list[Any] = [Condition(condition=ConditionEnum.EQUALS, identifier="name", value="Alice")]
    qwp = dialect.select(
        distinct=None, columns=["id", "name", "email"], table="crud_users", joins=None,
        where=where, group_by=None, having=None, order_by=None, limit=None, offset=None,
        unions=None,
    )
    rows = adapter.query_with_params(dialect, qwp).fetch_dicts()
    assert len(rows) == 1
    assert rows[0]["name"] == "Alice"

    # UPDATE.
    where = [Condition(condition=ConditionEnum.EQUALS, identifier="name", value="Bob")]
    qwp = dialect.update(table="crud_users", updates={"age": 26}, where=where, returning=None)
    adapter.query_with_params(dialect, qwp)

    where = [Condition(condition=ConditionEnum.EQUALS, identifier="name", value="Bob")]
    qwp = dialect.select(
        distinct=None, columns=["age"], table="crud_users", joins=None, where=where,
        group_by=None, having=None, order_by=None, limit=None, offset=None, unions=None,
    )
    row: dict[str, Any] | None = adapter.query_with_params(dialect, qwp).fetch_dict()
    assert row is not None
    assert row["age"] == 26

    # DELETE.
    where = [Condition(condition=ConditionEnum.EQUALS, identifier="name", value="Charlie")]
    qwp = dialect.delete(table="crud_users", where=where, returning=None)
    adapter.query_with_params(dialect, qwp)

    qwp = dialect.select(
        distinct=None, columns=None, table="crud_users", joins=None, where=None,
        group_by=None, having=None, order_by=None, limit=None, offset=None, unions=None,
    )
    rows = adapter.query_with_params(dialect, qwp).fetch_dicts()
    assert len(rows) == 2

    _drop(adapter, "crud_users")


# ---------------------------------------------------------------------------
# 2. DB.connect factory
# ---------------------------------------------------------------------------


def test_postgres_database_connect() -> None:
    """The DB.connect("postgresql", ...) factory wires adapter and dialect."""
    db = DB.connect_postgresql(
        PG_DBNAME,
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
    )
    try:
        assert db is not None
        assert db.adapter.driver_name == "postgresql"  # type: ignore[attr-defined]
        assert isinstance(db.dialect, PostgresqlDialect)
        assert db.dialect.bool is True
        assert db.dialect.returning is True
        assert db.dialect.on_conflict is True
        assert db.dialect.distinct_on is True
        # Version should be a real string (e.g. "18.3").
        assert len(db.adapter.version()) > 0  # type: ignore[attr-defined]
    finally:
        db.adapter.close()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 3. SelectQuery builder
# ---------------------------------------------------------------------------


def test_postgres_query_builder_select(pg_db: DB) -> None:
    """SelectQuery with WHERE, ORDER BY, LIMIT and OFFSET against PostgreSQL."""
    db = pg_db
    adapter = db.adapter  # type: ignore[attr-defined]
    _drop(adapter, "qb_items")

    cq: CreateTableQuery = db.create_table("qb_items")
    cq.identity("id")
    cq.string("name")
    cq.execute()
    adapter.commit_transaction()

    iq = db.insert("qb_items")
    iq.values({"name": "Item A"}, {"name": "Item B"}, {"name": "Item C"}, {"name": "Item D"})
    iq.execute()
    adapter.commit_transaction()  # type: ignore[attr-defined]

    # WHERE + ORDER BY ASC + LIMIT
    q = db.select("qb_items")
    q.columns(["id", "name"])
    q.where_greater_than("id", 1)
    q.order_by_asc("name")
    q.limit(2)
    rows: list[dict[str, Any]] = q.execute().fetch_dicts()
    assert [r["name"] for r in rows] == ["Item B", "Item C"]

    # OFFSET skips the first row of the ordered set.
    q2 = db.select("qb_items")
    q2.columns(["name"])
    q2.order_by_asc("name")
    q2.limit(2).offset(1)
    rows = q2.execute().fetch_dicts()
    assert [r["name"] for r in rows] == ["Item B", "Item C"]

    # COUNT wrapper
    q3 = db.select("qb_items")
    assert q3.count() == 4

    _drop(adapter, "qb_items")


# ---------------------------------------------------------------------------
# 4. Joins
# ---------------------------------------------------------------------------


def test_postgres_joins(pg_adapter: PsycopgAdapter, pg_dialect: PostgresqlDialect) -> None:
    """INNER, LEFT, RIGHT and CROSS joins with .on() using list[str] identifiers.

    RIGHT JOIN is not exposed as a fluent helper (only INNER/LEFT/CROSS are),
    so it is exercised via the raw join() escape hatch.
    """
    adapter, dialect = pg_adapter, pg_dialect
    _drop(adapter, "j_users", "j_posts")

    adapter.exec(
        'CREATE TABLE "j_users" ("id" SERIAL PRIMARY KEY, "name" TEXT)'
    )
    adapter.exec(
        'CREATE TABLE "j_posts" ('
        ' "id" SERIAL PRIMARY KEY, "user_id" INT REFERENCES "j_users"("id"), '
        ' "title" TEXT)'
    )
    adapter.exec(
        "INSERT INTO \"j_users\" (\"name\") VALUES ('Alice'), ('Bob')"
    )
    # Alice has two posts, Bob has none.
    adapter.exec(
        "INSERT INTO \"j_posts\" (\"user_id\", \"title\") VALUES (1, 'p1'), (1, 'p2')"
    )
    adapter.commit_transaction()

    # INNER JOIN — only rows with matching posts.
    q = SelectQuery(dialect, "j_users")
    q.columns([identifier(["j_users", "name"]), identifier(["j_posts", "title"])])
    q.inner_join("j_posts").on(["j_users", "id"], ["j_posts", "user_id"])
    rows: list[dict[str, Any]] = adapter.query_with_params(dialect, q.to_query_with_params()).fetch_dicts()
    assert len(rows) == 2  # Alice's two posts
    assert all(r["name"] == "Alice" for r in rows)

    # LEFT JOIN — Bob appears with NULL title.
    q = SelectQuery(dialect, "j_users")
    q.columns([identifier(["j_users", "name"]), identifier(["j_posts", "title"])])
    q.left_join("j_posts").on(["j_users", "id"], ["j_posts", "user_id"])
    rows = adapter.query_with_params(dialect, q.to_query_with_params()).fetch_dicts()
    names: dict[str, Any] = {r["name"]: r["title"] for r in rows}
    # Alice appears at least once with a non-null title; Bob appears with NULL.
    assert names["Bob"] is None
    assert any(r["name"] == "Alice" and r["title"] is not None for r in rows)

    # RIGHT JOIN — via raw escape hatch. All posts appear even though we start
    # from j_users (the right-hand table is j_posts).
    q = SelectQuery(dialect, "j_users")
    q.columns([identifier(["j_users", "name"]), identifier(["j_posts", "title"])])
    q.join(raw('RIGHT JOIN "j_posts" ON "j_posts"."user_id" = "j_users"."id"'))
    rows = adapter.query_with_params(dialect, q.to_query_with_params()).fetch_dicts()
    assert len(rows) == 2  # both posts
    assert all(r["title"] in ("p1", "p2") for r in rows)

    # CROSS JOIN — cartesian product (2 users x 2 posts = 4 rows).
    q = SelectQuery(dialect, "j_users")
    q.columns([identifier(["j_users", "name"]), identifier(["j_posts", "title"])])
    q.cross_join("j_posts")
    rows = adapter.query_with_params(dialect, q.to_query_with_params()).fetch_dicts()
    assert len(rows) == 4

    _drop(adapter, "j_users", "j_posts")


# ---------------------------------------------------------------------------
# 5. Conditions
# ---------------------------------------------------------------------------


def test_postgres_conditions(pg_adapter: PsycopgAdapter, pg_dialect: PostgresqlDialect) -> None:
    """where_equals, where_in, where_between, where_like, where_is_null,
    where_regex and where_operator (with @> and <@ array operators).
    """
    adapter, dialect = pg_adapter, pg_dialect
    _drop(adapter, "cond_t")

    adapter.exec(
        'CREATE TABLE "cond_t" ('
        ' "id" SERIAL PRIMARY KEY, "name" TEXT, "age" INT, "tags" TEXT[])'
    )
    adapter.exec(
        "INSERT INTO \"cond_t\" (\"name\", \"age\", \"tags\") VALUES "
        "('Alice', 30, ARRAY['a','b']), "
        "('Bob', 25, ARRAY['x']), "
        "('Charlie', 35, ARRAY['a','c']), "
        "('Dora', 40, ARRAY['a'])"
    )
    adapter.commit_transaction()

    # where_equals
    q = SelectQuery(dialect, "cond_t")
    q.where_equals("name", "Bob")
    rows = adapter.query_with_params(dialect, q.to_query_with_params()).fetch_dicts()
    assert len(rows) == 1 and rows[0]["name"] == "Bob"

    # where_in
    q = SelectQuery(dialect, "cond_t")
    q.where_in("name", ["Alice", "Charlie"])
    rows = adapter.query_with_params(dialect, q.to_query_with_params()).fetch_dicts()
    assert {r["name"] for r in rows} == {"Alice", "Charlie"}

    # where_between
    q = SelectQuery(dialect, "cond_t")
    q.where_between("age", 26, 35)
    rows = adapter.query_with_params(dialect, q.to_query_with_params()).fetch_dicts()
    assert {r["name"] for r in rows} == {"Alice", "Charlie"}

    # where_like (PostgreSQL dialect emits ILIKE)
    q = SelectQuery(dialect, "cond_t")
    q.where_like("name", "%a%")
    rows = adapter.query_with_params(dialect, q.to_query_with_params()).fetch_dicts()
    assert {r["name"] for r in rows} == {"Alice", "Charlie", "Dora"}

    # where_is_null (Dora gets no tags here; use a fresh column to test NULL)
    adapter.exec('ALTER TABLE "cond_t" ADD COLUMN "nick" TEXT')
    adapter.exec("UPDATE \"cond_t\" SET \"nick\" = 'Al' WHERE \"name\" = 'Alice'")
    adapter.commit_transaction()
    q = SelectQuery(dialect, "cond_t")
    q.where_is_null("nick")
    rows = adapter.query_with_params(dialect, q.to_query_with_params()).fetch_dicts()
    assert {r["name"] for r in rows} == {"Bob", "Charlie", "Dora"}

    q = SelectQuery(dialect, "cond_t")
    q.where_is_not_null("nick")
    rows = adapter.query_with_params(dialect, q.to_query_with_params()).fetch_dicts()
    assert {r["name"] for r in rows} == {"Alice"}

    # where_regex — PostgreSQL ~ operator.
    q = SelectQuery(dialect, "cond_t")
    q.where_regex("name", "^A")
    rows = adapter.query_with_params(dialect, q.to_query_with_params()).fetch_dicts()
    assert {r["name"] for r in rows} == {"Alice"}

    # where_operator with @> (array contains)
    q = SelectQuery(dialect, "cond_t")
    q.where_operator("tags", "@>", ["a", "b"])
    rows = adapter.query_with_params(dialect, q.to_query_with_params()).fetch_dicts()
    assert {r["name"] for r in rows} == {"Alice"}

    # where_operator with <@ (array is contained by the given array):
    # Alice [a,b], Charlie [a,c] and Dora [a] are all subsets of [a,b,c];
    # Bob [x] is not.
    q = SelectQuery(dialect, "cond_t")
    q.where_operator("tags", "<@", ["a", "b", "c"])
    rows = adapter.query_with_params(dialect, q.to_query_with_params()).fetch_dicts()
    assert {r["name"] for r in rows} == {"Alice", "Charlie", "Dora"}

    _drop(adapter, "cond_t")


# ---------------------------------------------------------------------------
# 6. Transactions and savepoints
# ---------------------------------------------------------------------------


def test_postgres_transactions(pg_adapter: PsycopgAdapter, pg_dialect: PostgresqlDialect) -> None:
    """BEGIN/COMMIT/ROLLBACK and SAVEPOINT RELEASE/ROLLBACK TO."""
    adapter, dialect = pg_adapter, pg_dialect
    _drop(adapter, "tx_t")

    adapter.exec('CREATE TABLE "tx_t" ("id" SERIAL PRIMARY KEY, "val" TEXT)')
    adapter.commit_transaction()

    # COMMIT path
    adapter.begin_transaction()
    qwp = dialect.insert(table="tx_t", values=[{"val": "committed"}])
    adapter.query_with_params(dialect, qwp)
    adapter.commit_transaction()
    assert adapter.query('SELECT count(*) AS c FROM "tx_t"').fetch_dict()["c"] == 1  # type: ignore[index]

    # ROLLBACK path
    adapter.begin_transaction()
    qwp = dialect.insert(table="tx_t", values=[{"val": "rolledback"}])
    adapter.query_with_params(dialect, qwp)
    adapter.rollback_transaction()
    assert adapter.query('SELECT count(*) AS c FROM "tx_t"').fetch_dict()["c"] == 1  # type: ignore[index]

    # Savepoint RELEASE keeps the inner work.
    adapter.begin_transaction()
    adapter.begin_savepoint("sp1")
    qwp = dialect.insert(table="tx_t", values=[{"val": "sp_kept"}])
    adapter.query_with_params(dialect, qwp)
    adapter.commit_savepoint("sp1")
    adapter.commit_transaction()
    assert adapter.query('SELECT count(*) AS c FROM "tx_t"').fetch_dict()["c"] == 2  # type: ignore[index]

    # Savepoint ROLLBACK discards the inner work but keeps the outer tx.
    adapter.begin_transaction()
    adapter.begin_savepoint("sp2")
    qwp = dialect.insert(table="tx_t", values=[{"val": "sp_discarded"}])
    adapter.query_with_params(dialect, qwp)
    adapter.rollback_savepoint("sp2")
    adapter.commit_transaction()
    assert adapter.query('SELECT count(*) AS c FROM "tx_t"').fetch_dict()["c"] == 2  # type: ignore[index]

    _drop(adapter, "tx_t")


# ---------------------------------------------------------------------------
# 7. ON CONFLICT
# ---------------------------------------------------------------------------


def test_postgres_on_conflict(pg_adapter: PsycopgAdapter, pg_dialect: PostgresqlDialect) -> None:
    """INSERT ... ON CONFLICT DO NOTHING and DO UPDATE (with EXCLUDED)."""
    adapter, dialect = pg_adapter, pg_dialect
    _drop(adapter, "oc_t")

    adapter.exec('CREATE TABLE "oc_t" ("id" INT PRIMARY KEY, "val" TEXT)')
    adapter.commit_transaction()

    # Initial insert.
    qwp = dialect.insert(
        table="oc_t",
        values=[{"id": 1, "val": "first"}],
        on_conflict=None,
        returning=None,
        last_insert_id=None,
    )
    adapter.query_with_params(dialect, qwp)

    # DO NOTHING — second insert with same id is silently dropped.
    qwp = dialect.insert(
        table="oc_t",
        values=[{"id": 1, "val": "ignored"}],
        on_conflict=OnConflict(conflict=["id"], updates=None),
        returning=None,
        last_insert_id=None,
    )
    adapter.query_with_params(dialect, qwp)
    assert adapter.query('SELECT "val" FROM "oc_t" WHERE "id" = 1').fetch_dict()["val"] == "first"  # type: ignore[index]

    # DO UPDATE with specific column updates referencing EXCLUDED.
    qwp = dialect.insert(
        table="oc_t",
        values=[{"id": 1, "val": "third"}],
        on_conflict=OnConflict(conflict=["id"], updates={"val": Excluded()}),
        returning=None,
        last_insert_id=None,
    )
    adapter.query_with_params(dialect, qwp)
    assert adapter.query('SELECT "val" FROM "oc_t" WHERE "id" = 1').fetch_dict()["val"] == "third"  # type: ignore[index]

    # DO UPDATE with empty updates dict means "update all columns from EXCLUDED".
    qwp = dialect.insert(
        table="oc_t",
        values=[{"id": 1, "val": "fourth"}],
        on_conflict=OnConflict(conflict=["id"], updates={}),
        returning=None,
        last_insert_id=None,
    )
    adapter.query_with_params(dialect, qwp)
    assert adapter.query('SELECT "val" FROM "oc_t" WHERE "id" = 1').fetch_dict()["val"] == "fourth"  # type: ignore[index]

    # Fluent InsertQuery path.
    iq = InsertQuery(dialect, "oc_t")
    iq.values({"id": 1, "val": "fifth"})
    iq.on_conflict_do_update(["id"], {"val": Excluded()})
    adapter.query_with_params(dialect, iq.to_query_with_params())
    assert adapter.query('SELECT "val" FROM "oc_t" WHERE "id" = 1').fetch_dict()["val"] == "fifth"  # type: ignore[index]

    iq = InsertQuery(dialect, "oc_t")
    iq.values({"id": 1, "val": "ignored2"})
    iq.on_conflict_do_nothing(["id"])
    adapter.query_with_params(dialect, iq.to_query_with_params())
    assert adapter.query('SELECT "val" FROM "oc_t" WHERE "id" = 1').fetch_dict()["val"] == "fifth"  # type: ignore[index]

    _drop(adapter, "oc_t")


# ---------------------------------------------------------------------------
# 8. RETURNING
# ---------------------------------------------------------------------------


def test_postgres_returning(pg_adapter: PsycopgAdapter, pg_dialect: PostgresqlDialect) -> None:
    """INSERT/UPDATE/DELETE with RETURNING clauses."""
    adapter, dialect = pg_adapter, pg_dialect
    _drop(adapter, "ret_t")

    adapter.exec('CREATE TABLE "ret_t" ("id" SERIAL PRIMARY KEY, "name" TEXT, "age" INT)')
    adapter.commit_transaction()

    # INSERT ... RETURNING
    qwp = dialect.insert(
        table="ret_t",
        values=[{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}],
        on_conflict=None,
        returning=["id", "name"],
        last_insert_id=None,
    )
    rows = adapter.query_with_params(dialect, qwp).fetch_dicts()
    assert {r["name"] for r in rows} == {"Alice", "Bob"}
    assert all(isinstance(r["id"], int) for r in rows)

    # UPDATE ... RETURNING
    qwp = dialect.update(
        table="ret_t",
        updates={"age": 31},
        where=[Condition(condition=ConditionEnum.EQUALS, identifier="name", value="Alice")],
        returning=["id", "age"],
    )
    rows = adapter.query_with_params(dialect, qwp).fetch_dicts()
    assert len(rows) == 1
    assert rows[0]["age"] == 31

    # DELETE ... RETURNING
    qwp = dialect.delete(
        table="ret_t",
        where=[Condition(condition=ConditionEnum.EQUALS, identifier="name", value="Bob")],
        returning=["id", "name"],
    )
    rows = adapter.query_with_params(dialect, qwp).fetch_dicts()
    assert len(rows) == 1 and rows[0]["name"] == "Bob"

    # Only Alice remains.
    qwp = dialect.select(
        distinct=None, columns=None, table="ret_t", joins=None, where=None,
        group_by=None, having=None, order_by=None, limit=None, offset=None, unions=None,
    )
    remaining = adapter.query_with_params(dialect, qwp).fetch_dicts()
    assert [r["name"] for r in remaining] == ["Alice"]

    _drop(adapter, "ret_t")


# ---------------------------------------------------------------------------
# 9. DDL — varied types
# ---------------------------------------------------------------------------


def test_postgres_ddl(pg_adapter: PsycopgAdapter, pg_dialect: PostgresqlDialect) -> None:
    """CREATE TABLE with SERIAL, TEXT, JSONB, UUID and TIMESTAMP types
    plus DROP TABLE. The TypeEnum surface does not cover JSONB/UUID, so the
    table is created with a raw DDL string while the DROP uses the dialect.
    """
    adapter, dialect = pg_adapter, pg_dialect
    _drop(adapter, "ddl_t")

    # Raw DDL exercising PostgreSQL-specific types.
    adapter.exec(
        'CREATE TABLE "ddl_t" ('
        ' "id" SERIAL PRIMARY KEY, '
        ' "body" TEXT, '
        ' "meta" JSONB, '
        ' "uid" UUID DEFAULT gen_random_uuid(), '
        ' "created" TIMESTAMP DEFAULT now())'
    )
    adapter.commit_transaction()

    # Confirm all columns exist with the expected types.
    result = adapter.query(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = 'ddl_t' ORDER BY ordinal_position"
    )
    cols: dict[str, str] = {r["column_name"]: r["data_type"] for r in result.fetch_dicts()}
    assert cols["id"] == "integer"
    assert cols["body"] == "text"
    assert cols["meta"] == "jsonb"
    assert cols["uid"] == "uuid"
    assert cols["created"] == "timestamp without time zone"

    # Insert a row with a JSONB value using psycopg's Jsonb adapter so the
    # native prepared-statement path can adapt the dict.
    from psycopg.types.json import Jsonb

    iq = InsertQuery(dialect, "ddl_t")
    iq.values({"body": "hello", "meta": Jsonb({"k": "v"})})
    iq.returning(["id", "uid", "meta"])
    row = adapter.query_with_params(dialect, iq.to_query_with_params()).fetch_dict()
    assert row is not None
    assert row["meta"] == {"k": "v"}
    # UUID columns come back as a uuid.UUID instance (or its string form).
    from uuid import UUID

    assert isinstance(row["uid"], (UUID, str))

    # DROP TABLE via the dialect.
    qwp = dialect.drop_table(if_exists=True, table="ddl_t")
    adapter.exec(qwp.query)
    result = adapter.query(
        "SELECT count(*) AS c FROM information_schema.tables WHERE table_name = 'ddl_t'"
    )
    assert result.fetch_dict()["c"] == 0  # type: ignore[index]


# ---------------------------------------------------------------------------
# 10. ALTER TABLE
# ---------------------------------------------------------------------------


def test_postgres_alter_table(pg_adapter: PsycopgAdapter, pg_dialect: PostgresqlDialect) -> None:
    """ADD COLUMN, RENAME COLUMN and DROP COLUMN via the PostgresqlDialect.

    Unlike SQLiteDialect (which raises QueryError for ALTER/DROP COLUMN),
    PostgresqlDialect fully supports these operations.
    """
    adapter, dialect = pg_adapter, pg_dialect
    _drop(adapter, "alt_t")

    adapter.exec('CREATE TABLE "alt_t" ("id" SERIAL PRIMARY KEY, "name" TEXT)')
    adapter.commit_transaction()

    # ADD COLUMN via the fluent AlterTableQuery.
    alter = AlterTableQuery(dialect, "alt_t")
    alter.add_string("email", 255)
    alter.add_int("age")
    for qwp in alter.to_query_with_params():
        adapter.exec(qwp.query)

    result = adapter.query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'alt_t' ORDER BY ordinal_position"
    )
    names = [r["column_name"] for r in result.fetch_dicts()]
    assert names == ["id", "name", "email", "age"]

    # RENAME COLUMN.
    alter = AlterTableQuery(dialect, "alt_t")
    alter.rename_column("email", "mail")
    for qwp in alter.to_query_with_params():
        adapter.exec(qwp.query)
    result = adapter.query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'alt_t' ORDER BY ordinal_position"
    )
    names = [r["column_name"] for r in result.fetch_dicts()]
    assert names == ["id", "name", "mail", "age"]

    # DROP COLUMN.
    alter = AlterTableQuery(dialect, "alt_t")
    alter.drop_column("age")
    for qwp in alter.to_query_with_params():
        adapter.exec(qwp.query)
    result = adapter.query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'alt_t' ORDER BY ordinal_position"
    )
    names = [r["column_name"] for r in result.fetch_dicts()]
    assert names == ["id", "name", "mail"]

    # Direct dialect.alter_table returns a list of QueryWithParams.
    alters = dialect.alter_table(
        table="alt_t",
        alters=[{"type": "add_column", "column": {"name": "note", "type": TypeEnum.STRING}}],
    )
    assert isinstance(alters, list)
    for qwp in alters:
        adapter.exec(qwp.query)
    result = adapter.query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'alt_t' ORDER BY ordinal_position"
    )
    names = [r["column_name"] for r in result.fetch_dicts()]
    assert names == ["id", "name", "mail", "note"]

    _drop(adapter, "alt_t")


# ---------------------------------------------------------------------------
# 11. Giant SELECT
# ---------------------------------------------------------------------------


def test_postgres_giant_select(pg_adapter: PsycopgAdapter, pg_dialect: PostgresqlDialect) -> None:
    """One query combining many condition types, an aliased INNER JOIN,
    GROUP BY + HAVING, ORDER BY + LIMIT + OFFSET, plus separate assertions
    for UNION and DISTINCT ON.
    """
    adapter, dialect = pg_adapter, pg_dialect
    _drop(adapter, "g_posts", "g_users")

    adapter.exec(
        'CREATE TABLE "g_users" ('
        ' "id" SERIAL PRIMARY KEY, "name" TEXT, "age" INT, '
        ' "email" TEXT, "tags" TEXT[])'
    )
    adapter.exec(
        'CREATE TABLE "g_posts" ('
        ' "id" SERIAL PRIMARY KEY, "user_id" INT REFERENCES "g_users"("id"), '
        ' "title" TEXT)'
    )
    adapter.exec(
        "INSERT INTO \"g_users\" (\"name\", \"age\", \"email\", \"tags\") VALUES "
        "('Alice', 30, 'a@x.com', ARRAY['a','b']), "
        "('Bob', 25, 'b@x.com', ARRAY['x']), "
        "('Charlie', 35, 'c@x.com', ARRAY['a','c']), "
        "('Dora', 40, 'd@x.com', ARRAY['a'])"
    )
    adapter.exec(
        "INSERT INTO \"g_posts\" (\"user_id\", \"title\") VALUES "
        "(1, 'p1'), (1, 'p2'), (2, 'p3')"
    )
    adapter.commit_transaction()

    # The giant query: aliased table, INNER JOIN with .on() list identifiers,
    # WHERE chaining equals/in/between/like/is_not_null/regex/operator(@>),
    # GROUP BY, HAVING (raw), ORDER BY, LIMIT, OFFSET.
    q = SelectQuery(dialect, Alias("g_users", "u"))  # type: ignore[arg-type]
    q.columns([identifier(["u", "name"]), expression('count("p"."id") AS post_count')])
    q.inner_join("g_posts", "p").on(["u", "id"], ["p", "user_id"])
    q.where_greater_than_or_equals("age", 25)
    q.where_in("name", ["Alice", "Bob"])
    q.where_between("age", 20, 40)
    q.where_like("email", "%@x.com")
    q.where_is_not_null("email")
    q.where_regex("name", "^A|B")
    q.where_operator("tags", "@>", ["a"])
    q.group_by(["name"])
    q.having_raw('count("p"."id") > 0')
    q.order_by_asc("name")
    q.limit(10).offset(0)

    qwp = q.to_query_with_params()
    rows = adapter.query_with_params(dialect, qwp).fetch_dicts()
    # Only Alice survives every filter (Bob's tags ['x'] does not contain 'a).
    assert [r["name"] for r in rows] == ["Alice"]
    assert rows[0]["post_count"] == 2

    # UNION of two single-row selects.
    q1 = SelectQuery(dialect, "g_users")
    q1.columns(["name"])
    q1.where_equals("name", "Alice")
    q2 = SelectQuery(dialect, "g_users")
    q2.columns(["name"])
    q2.where_equals("name", "Charlie")
    q1.union(q2)
    union_rows = adapter.query_with_params(dialect, q1.to_query_with_params()).fetch_dicts()
    assert {r["name"] for r in union_rows} == {"Alice", "Charlie"}

    # DISTINCT ON — first row per age bucket when ordered by age.
    q3 = SelectQuery(dialect, "g_users")
    q3.distinct(["age"])
    q3.columns(["age", "name"])
    q3.order_by_asc("age")
    q3.order_by_desc("name")
    distinct_rows = adapter.query_with_params(dialect, q3.to_query_with_params()).fetch_dicts()
    ages = [r["age"] for r in distinct_rows]
    assert ages == sorted(ages)
    assert len(distinct_rows) == len(set(ages))  # one row per distinct age

    _drop(adapter, "g_posts", "g_users")


# ---------------------------------------------------------------------------
# 12. Schema-qualified identifiers
# ---------------------------------------------------------------------------


def test_postgres_schema_qualified(pg_adapter: PsycopgAdapter, pg_dialect: PostgresqlDialect) -> None:
    """Queries with schema-qualified identifiers like ["public", "users", "id"]."""
    adapter, dialect = pg_adapter, pg_dialect
    _drop(adapter, "sq_users")
    adapter.exec('DROP SCHEMA IF EXISTS "sq" CASCADE')
    adapter.exec('CREATE SCHEMA "sq"')
    adapter.exec('CREATE TABLE "sq"."sq_users" ("id" SERIAL PRIMARY KEY, "name" TEXT)')
    adapter.exec("INSERT INTO \"sq\".\"sq_users\" (\"name\") VALUES ('sch1'), ('sch2')")
    adapter.commit_transaction()

    # Schema-qualified FROM.
    q = SelectQuery(dialect, ["sq", "sq_users"])
    q.columns([identifier(["sq", "sq_users", "id"]), identifier(["sq", "sq_users", "name"])])
    q.order_by_asc("name")
    qwp = q.to_query_with_params()
    assert qwp.query == 'SELECT "sq"."sq_users"."id", "sq"."sq_users"."name" FROM "sq"."sq_users" ORDER BY "name" ASC'
    rows = adapter.query_with_params(dialect, qwp).fetch_dicts()
    assert [r["name"] for r in rows] == ["sch1", "sch2"]

    # Schema-qualified WHERE on a schema-qualified column.
    q = SelectQuery(dialect, ["sq", "sq_users"])
    q.columns(["name"])
    q.where_equals(["sq", "sq_users", "id"], 1)
    qwp = q.to_query_with_params()
    assert qwp.query == 'SELECT "name" FROM "sq"."sq_users" WHERE "sq"."sq_users"."id" = ?'
    rows = adapter.query_with_params(dialect, qwp).fetch_dicts()
    assert len(rows) == 1 and rows[0]["name"] == "sch1"

    # INSERT into a schema-qualified table. The base dialect's insert() does
    # not split a list table argument, so wrap it in an Identifier expression.
    qwp = dialect.insert(
        table=identifier(["sq", "sq_users"]),
        values=[{"name": "sch3"}],
        on_conflict=None,
        returning=["id", "name"],
        last_insert_id=None,
    )
    assert qwp.query == 'INSERT INTO "sq"."sq_users" ("name") VALUES (?) RETURNING "id", "name"'
    row = adapter.query_with_params(dialect, qwp).fetch_dict()
    assert row is not None and row["name"] == "sch3"

    # DROP TABLE on a schema-qualified table.
    qwp = dialect.drop_table(if_exists=True, table=["sq", "sq_users"])
    adapter.exec(qwp.query)
    adapter.exec('DROP SCHEMA "sq" CASCADE')


# ---------------------------------------------------------------------------
# Extra: driver registry / version sanity
# ---------------------------------------------------------------------------


def test_postgres_drivers_registry() -> None:
    """DB.drivers() advertises postgresql."""
    drivers: list[str] = DB.drivers()
    assert "postgresql" in drivers


def test_postgres_adapter_version(pg_adapter: PsycopgAdapter) -> None:
    """The adapter reports a parseable PostgreSQL version string."""
    version: str = pg_adapter.version()
    assert version != "0"
    # Format like "18.3" or "15.2".
    parts = version.split(".")
    assert len(parts) >= 2 and all(p.isdigit() for p in parts)
