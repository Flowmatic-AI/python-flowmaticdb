"""Integration tests for flowmaticdb against the libsql driver.

The engine speaks SQLite, but the driver around it does not behave like
``sqlite3``, and that is what this module pins down:

    * ``LibSQLAdapter`` -- binds ``?`` placeholders, serializes temporals and
      documents itself (the driver binds nothing but NULL/int/float/str/bytes),
      and treats ``ValueError`` as the driver's error class.
    * ``LibSQLDialect`` -- SQLite grammar with the built-in ``REGEXP`` operator
      in place of the ``regexp_like()`` function that does not exist here.
    * ``LibSQLResult`` -- tuple rows keyed by cursor description, values left
      exactly as the engine stored them.

Run with::

    python3 -m pytest tests/test_integration_libsql.py -v
"""
from __future__ import annotations

import threading
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from flowmaticdb import AdapterError, QueryError
from flowmaticdb.database import DB
from flowmaticdb.dialects import LibSQLDialect

pytest.importorskip("libsql", reason="libsql is an optional driver; install flowmaticdb[libsql].")

from flowmaticdb.adapters import LibSQLAdapter


def _users_db() -> DB:
    db = DB.connect_libsql(":memory:")
    db.create_table("users").if_not_exists()\
        .identity("id")\
        .string("name")\
        .integer("age")\
        .boolean("active")\
        .datetime("created_at")\
        .json("meta")\
        .execute()
    return db


def test_libsql_in_memory_crud() -> None:
    db = _users_db()
    assert db.adapter.driver_name == "libsql"
    assert len(db.adapter.version()) > 0

    db.insert("users").values(
        {"name": "Alice", "age": 30},
        {"name": "Bob", "age": 25},
        {"name": "Charlie", "age": 35},
    ).execute()

    assert db.select("users").execute().scalars("name") == ["Alice", "Bob", "Charlie"]
    assert db.select("users").where_equals("name", "Alice").execute().scalar("age") == 30

    db.update("users").updates({"age": 26}).where_equals("name", "Bob").execute()
    assert db.select("users").where_equals("name", "Bob").execute().scalar("age") == 26

    db.delete("users").where_equals("name", "Charlie").execute()
    assert db.select("users").execute().scalars("name") == ["Alice", "Bob"]

    assert db.adapter.last_insert_id() == 3
    db.close()


def test_libsql_binds_the_types_the_driver_cannot() -> None:
    """A temporal or a document reaches the driver as ``Unsupported parameter
    type`` unless the adapter renders it first."""
    db = _users_db()
    happened_at = datetime(2026, 8, 3, 12, 30, 45, tzinfo=UTC)

    db.insert("users").values(
        {"name": "Alice", "active": True, "created_at": happened_at, "meta": {"tags": ["a", "b"]}},
        {"name": "Bob", "active": False, "created_at": None, "meta": None},
    ).execute()

    rows = db.select("users").order_by_asc("id").execute().fetch_dicts()

    assert rows[0]["created_at"] == happened_at
    assert rows[0]["meta"] == {"tags": ["a", "b"]}
    assert rows[1]["created_at"] is None
    assert rows[1]["meta"] is None

    # A boolean is stored as 0/1, which nothing in the value distinguishes from
    # an integer -- so it stays one, and the dialect decodes it on request.
    assert rows[0]["active"] == 1
    assert rows[1]["active"] == 0
    assert db.dialect.parse_bool(rows[0]["active"]) is True
    assert db.dialect.parse_bool(rows[1]["active"]) is False
    db.close()


def test_libsql_casts_columns_on_both_query_paths() -> None:
    """A builder query without parameters runs through ``adapter.query()``
    rather than ``query_with_params()``; both have to cast alike."""
    db = _users_db()
    happened_at = datetime(2026, 8, 3, 12, 30, 45, tzinfo=UTC)
    db.insert("users").values({"name": "Alice", "created_at": happened_at, "meta": {"k": "v"}}).execute()

    built = db.select("users").execute().fetch_dict()
    raw = db.query("SELECT created_at, meta FROM users").fetch_dict()

    assert built is not None
    assert raw is not None
    assert built["created_at"] == happened_at
    assert raw["created_at"] == happened_at
    assert built["meta"] == {"k": "v"}
    assert raw["meta"] == {"k": "v"}
    db.close()


def test_libsql_casting_reports_the_guessed_column_types() -> None:
    db = _users_db()
    db.insert("users").values({
        "name": "Alice",
        "age": 30,
        "created_at": datetime(2026, 8, 3, 12, 30, 45, tzinfo=UTC),
        "meta": {"k": "v"},
    }).execute()

    result = db.select("users").execute()
    result.fetch_dicts()

    columns = result.columns()
    assert columns["name"] == "TEXT"
    assert columns["age"] == "INTEGER"
    assert columns["created_at"] == "DATETIME"
    assert columns["meta"] == "JSON"
    assert columns["active"] == "NULL"
    db.close()


def test_libsql_casting_leaves_text_that_only_looks_convertible() -> None:
    """The guess is deliberately narrow: valid JSON that is not a document, a
    date without a time, and text that merely starts like a document all stay
    text."""
    db = DB.connect_libsql(":memory:")
    db.create_table("notes").if_not_exists().identity("id").string("body").execute()
    db.insert("notes").values(
        {"body": "1"},
        {"body": "null"},
        {"body": "true"},
        {"body": "2026-08-03"},
        {"body": "12:30:45"},
        {"body": "{not json at all}"},
        {"body": "[unclosed"},
    ).execute()

    assert db.select("notes").order_by_asc("id").execute().scalars("body") == [
        "1", "null", "true", "2026-08-03", "12:30:45", "{not json at all}", "[unclosed",
    ]
    db.close()


def test_libsql_casting_round_trips_a_naive_datetime() -> None:
    """No timezone is invented for a value that was written without one."""
    db = _users_db()
    happened_at = datetime(2026, 8, 3, 12, 30, 45, 123456, tzinfo=UTC).replace(tzinfo=None)

    db.insert("users").values({"name": "Alice", "created_at": happened_at}).execute()

    assert db.select("users").execute().scalar("created_at") == happened_at
    db.close()


def test_libsql_auto_cast_column_types_can_be_turned_off() -> None:
    db = DB.connect_libsql(":memory:", options={"auto_cast_column_types": False})
    db.create_table("users").if_not_exists().identity("id").string("name")\
        .datetime("created_at").json("meta").execute()
    db.insert("users").values({
        "name": "Alice",
        "created_at": datetime(2026, 8, 3, 12, 30, 45, tzinfo=UTC),
        "meta": {"tags": ["a", "b"]},
    }).execute()

    row = db.select("users").execute().fetch_dict()

    assert row is not None
    assert row["created_at"] == "2026-08-03 12:30:45+00:00"
    assert row["meta"] == '{"tags": ["a", "b"]}'
    db.close()


def test_libsql_binds_a_bare_date() -> None:
    db = DB.connect_libsql(":memory:")
    db.create_table("events").if_not_exists().identity("id").string("on_day").execute()

    db.insert("events").values({"on_day": date(2026, 8, 3)}).execute()

    assert db.select("events").execute().scalar("on_day") == "2026-08-03"
    db.close()


def test_libsql_placeholders_are_converted() -> None:
    """Queries are built with ``%s``; the driver only knows ``?``."""
    db = _users_db()
    db.insert("users").values({"name": "Alice", "age": 30}).execute()

    result = db.prepared("SELECT name FROM users WHERE age > %s", [20])
    assert result.fetch_dicts() == [{"name": "Alice"}]
    db.close()


def test_libsql_emulated_prepare_inlines_the_params() -> None:
    db = _users_db()
    db.insert("users").values({"name": "Alice", "age": 30}).execute()

    rows = db.select("users").where_equals("name", "Alice").execute(emulate_prepare=True).fetch_dicts()

    assert [row["name"] for row in rows] == ["Alice"]
    db.close()


def test_libsql_result_reports_its_columns() -> None:
    db = _users_db()
    db.insert("users").values({"name": "Alice", "age": 30}).execute()

    result = db.query("SELECT id, name, age FROM users")
    assert list(result.columns()) == ["id", "name", "age"]

    rows = result.fetch_dicts()
    assert rows == [{"id": 1, "name": "Alice", "age": 30}]
    assert result.columns() == {"id": "INTEGER", "name": "TEXT", "age": "INTEGER"}
    db.close()


def test_libsql_result_of_a_statement_without_rows_is_empty() -> None:
    db = _users_db()

    result = db.query("INSERT INTO users (name) VALUES ('Alice')")

    assert result.columns() == {}
    assert result.fetch_dict() is None
    assert result.fetch_dicts() == []
    db.close()


def test_libsql_transactions_and_savepoints() -> None:
    db = _users_db()
    db.insert("users").values({"name": "Alice"}).execute()

    db.begin_transaction()
    assert db.in_transaction is True
    db.insert("users").values({"name": "Bob"}).execute()
    db.rollback_transaction()

    assert db.in_transaction is False
    assert db.select("users").execute().scalars("name") == ["Alice"]

    db.begin_transaction()
    db.begin_transaction("sp1")
    db.insert("users").values({"name": "Carol"}).execute()
    db.rollback_transaction(name="sp1")
    db.commit_transaction()

    assert db.select("users").execute().scalars("name") == ["Alice"]
    db.close()


def test_libsql_upsert() -> None:
    db = _users_db()
    db.insert("users").values({"id": 1, "name": "Alice", "age": 30}).execute()

    db.insert("users").values({"id": 1, "name": "Alice", "age": 31})\
        .on_conflict_do_update(["id"])\
        .execute()

    assert db.select("users").execute().fetch_dicts() == [
        {"id": 1, "name": "Alice", "age": 31, "active": None, "created_at": None, "meta": None},
    ]
    db.close()


def test_libsql_returning() -> None:
    db = _users_db()

    result = db.insert("users").values({"name": "Alice"}).returning(["id", "name"]).execute()

    assert result.fetch_dicts() == [{"id": 1, "name": "Alice"}]
    db.close()


def test_libsql_regex_uses_the_built_in_operator() -> None:
    """regexp_like() does not exist here and no user-defined function can be
    registered to supply it, so the operator form is the only form."""
    db = _users_db()
    db.insert("users").values({"name": "Alice"}, {"name": "Bob"}).execute()

    assert db.select("users").where_regex("name", "^Al").execute().scalars("name") == ["Alice"]
    assert db.select("users").where_not_regex("name", "^Al").execute().scalars("name") == ["Bob"]
    assert db.select("users").where_regex("name", "^AL", flags="i").execute().scalars("name") == ["Alice"]
    db.close()


def test_libsql_regex_rejects_flags_it_cannot_express() -> None:
    """The regex flavour has no inline group for them, and folding both sides
    only stands in for ``i``."""
    db = _users_db()

    with pytest.raises(QueryError):
        db.select("users").where_regex("name", "^a", flags="m").execute()

    db.close()


def test_libsql_dialect_matches_the_sqlite_grammar() -> None:
    dialect = LibSQLDialect(version="3.45.1")
    assert dialect.escape_identifier("name") == '"name"'
    assert dialect.on_conflict is True
    assert dialect.returning is True
    assert dialect.savepoints is True


def test_libsql_reports_query_errors_to_the_debug_callback() -> None:
    """The driver raises ValueError rather than its own error class, which the
    adapter has to expect or every failure escapes the callback."""
    seen: list[tuple[str, str | None]] = []
    db = DB.connect_libsql(":memory:", debug_callback=lambda sql, duration, error: seen.append((sql, error)))

    with pytest.raises(ValueError):
        db.query("SELECT * FROM nope")

    assert seen[-1][0] == "SELECT * FROM nope"
    assert seen[-1][1] is not None
    assert "nope" in seen[-1][1]
    db.close()


def test_libsql_adapter_reports_connection_state() -> None:
    adapter = LibSQLAdapter(database_name=":memory:")
    assert adapter.is_connected() is True

    adapter.close()
    assert adapter.is_connected() is False


def test_libsql_adapter_reconnect_opens_a_fresh_connection(tmp_path: Path) -> None:
    db_path = str(tmp_path / "reconnect.db")
    adapter = LibSQLAdapter(database_name=db_path)
    adapter.exec("CREATE TABLE t (val INTEGER)")
    adapter.exec("INSERT INTO t (val) VALUES (1)")
    adapter.close()
    assert adapter.is_connected() is False

    adapter.reconnect()

    assert adapter.is_connected() is True
    assert adapter.query("SELECT val FROM t").scalars("val") == [1]
    adapter.close()


def test_libsql_adapter_reconnect_reapplies_startup_queries(tmp_path: Path) -> None:
    adapter = LibSQLAdapter(
        database_name=str(tmp_path / "startup.db"),
        startup_queries=["CREATE TABLE IF NOT EXISTS startup (id INTEGER)"],
        options={"foreign_keys": True},
    )
    adapter.close()

    adapter.reconnect()

    assert adapter.query("PRAGMA foreign_keys").scalar() == 1
    adapter.query("SELECT id FROM startup")
    adapter.close()


def test_libsql_read_only_option_blocks_writes(tmp_path: Path) -> None:
    db_path = str(tmp_path / "ro.db")
    writer = LibSQLAdapter(database_name=db_path)
    writer.exec("CREATE TABLE t (val INTEGER)")
    writer.exec("INSERT INTO t (val) VALUES (1)")
    writer.close()

    reader = LibSQLAdapter(database_name=db_path, options={"read_only": True})
    assert reader.query("SELECT val FROM t").scalars("val") == [1]

    with pytest.raises(ValueError):
        reader.exec("INSERT INTO t (val) VALUES (2)")

    reader.close()


def test_libsql_rejects_user_defined_functions() -> None:
    """There is no create_function() on this driver, so a query relying on one
    would fail at execution time instead of at connect time."""
    with pytest.raises(AdapterError):
        LibSQLAdapter(database_name=":memory:", options={"create_functions": {"double": lambda v: v * 2}})


def test_libsql_gives_each_thread_its_own_connection(tmp_path: Path) -> None:
    db = DB.connect_libsql(str(tmp_path / "threads.db"))
    db.create_table("t").if_not_exists().identity("id").integer("val").execute()

    def insert(value: int) -> None:
        db.insert("t").values({"val": value}).execute()

    threads = [threading.Thread(target=insert, args=(value,)) for value in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(db.select("t").execute().scalars("val")) == [0, 1, 2, 3, 4]
    db.close()


def test_libsql_memory_database_is_shared_between_threads() -> None:
    """One handle for every thread: separate ``:memory:`` connections would each
    get their own empty database."""
    db = DB.connect_libsql(":memory:")
    db.create_table("t").if_not_exists().identity("id").integer("val").execute()

    thread = threading.Thread(target=lambda: db.insert("t").values({"val": 7}).execute())
    thread.start()
    thread.join()

    assert db.select("t").execute().scalars("val") == [7]
    assert db.adapter.connection_count() == 1
    db.close()


def test_libsql_is_listed_as_an_available_driver() -> None:
    assert "libsql" in DB.drivers()
