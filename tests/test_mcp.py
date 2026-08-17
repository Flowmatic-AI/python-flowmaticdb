from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("mcp", reason="the mcp extra is not installed")

from flowmaticdb import MCP, QueryError, Where
from flowmaticdb.database import DB

TOOL_NAMES = {
    "driver",
    "execute_sql",
    "list_tables",
    "describe_table",
    "select",
    "insert",
    "update",
    "delete",
    "begin_transaction",
    "commit_transaction",
    "rollback_transaction",
    "begin_savepoint",
    "commit_savepoint",
    "rollback_savepoint",
}


@pytest.fixture
def server() -> MCP:
    db = DB.connect_sqlite(":memory:")
    db.create_table("users")\
        .auto_increment("id")\
        .string("name", not_null=True)\
        .integer("age")\
        .json("meta")\
        .execute()
    db.insert("users")\
        .values({"name": "Alice", "age": 30}, {"name": "Bob", "age": 41}, {"name": "Cara", "age": 22})\
        .execute()

    return MCP(db, "flowmaticdb-test")


@pytest.fixture
def grouped() -> MCP:
    db = DB.connect_sqlite(":memory:")
    db.create_table("orders")\
        .auto_increment("id")\
        .string("customer", not_null=True)\
        .integer("total")\
        .execute()
    db.insert("orders")\
        .values(
            {"customer": "ann", "total": 10},
            {"customer": "ann", "total": 30},
            {"customer": "bob", "total": 5},
            {"customer": "bob", "total": 5},
            {"customer": "cid", "total": 200},
        )\
        .execute()

    return MCP(db, "flowmaticdb-test")


def names(rows: list[dict[str, Any]]) -> list[str]:
    return [str(row["name"]) for row in rows]


def test_every_capability_is_registered_as_a_tool(server: MCP) -> None:
    tools = asyncio.run(server.server.list_tools())

    assert {tool.name for tool in tools} == TOOL_NAMES


def test_tools_are_callable_over_the_protocol(server: MCP) -> None:
    content, structured = asyncio.run(server.server.call_tool("driver", {}))

    assert structured == {"result": "sqlite"}
    assert len(content) == 1


def test_select_arguments_validate_over_the_protocol(server: MCP) -> None:
    arguments = {"table": "users", "wheres": [{"identifier": "age", "operator": ">=", "value": 30}]}
    _, structured = asyncio.run(server.server.call_tool("select", arguments))

    assert names(structured["result"]) == ["Alice", "Bob"]


def test_driver(server: MCP) -> None:
    assert server.driver() == "sqlite"


def test_execute_sql_returns_rows(server: MCP) -> None:
    rows = server.execute_sql("SELECT name FROM users WHERE age > ? ORDER BY age", [25])

    assert rows == [{"name": "Alice"}, {"name": "Bob"}]


def test_execute_sql_without_rows(server: MCP) -> None:
    assert server.execute_sql("CREATE TABLE things (id INTEGER)") == []


def test_list_tables(server: MCP) -> None:
    assert server.list_tables() == ["users"]


def test_describe_table(server: MCP) -> None:
    description = server.describe_table("users")

    assert description["table"] == "users"
    assert [column["name"] for column in description["columns"]] == ["id", "name", "age", "meta"]
    assert description["columns"][0]["auto_increment"] is True
    assert description["columns"][1]["type"] == "STRING"
    assert description["columns"][1]["not_null"] is True
    assert description["columns"][3]["type"] == "JSON"


def test_describe_table_reports_constraints(server: MCP) -> None:
    server.db.create_table("posts")\
        .auto_increment("id")\
        .string("title")\
        .integer("user_id")\
        .foreign_key_constraint("user_id", "users", "id")\
        .unique_constraint(["title"], "posts_title_unique")\
        .execute()

    description = server.describe_table("posts")

    assert description["unique_constraints"][0]["columns"] == ["title"]
    foreign_key = description["foreign_keys"][0]
    assert foreign_key["columns"] == ["user_id"]
    assert foreign_key["ref_table"] == "users"
    assert foreign_key["ref_columns"] == ["id"]


def test_select_without_wheres(server: MCP) -> None:
    assert names(server.select("users")) == ["Alice", "Bob", "Cara"]


def test_select_limit_and_offset(server: MCP) -> None:
    assert names(server.select("users", None, None, None, 2, 1)) == ["Bob", "Cara"]


def test_select_group_by_collapses_rows(grouped: MCP) -> None:
    rows = grouped.select("orders", None, ["customer"])

    assert [row["customer"] for row in rows] == ["ann", "bob", "cid"]


def test_select_group_by_a_qualified_column(grouped: MCP) -> None:
    rows = grouped.select("orders", None, [["orders", "customer"]])

    assert [row["customer"] for row in rows] == ["ann", "bob", "cid"]


def test_select_havings_filter_the_groups(grouped: MCP) -> None:
    havings = [Where(identifier="total", operator=">", value=100)]
    rows = grouped.select("orders", None, ["customer"], havings)

    assert [row["customer"] for row in rows] == ["cid"]


def test_select_havings_are_chained_with_and(grouped: MCP) -> None:
    havings = [
        Where(identifier="total", operator=">=", value=10),
        Where(identifier="customer", operator="!=", value="cid"),
    ]
    rows = grouped.select("orders", None, ["customer"], havings)

    assert [row["customer"] for row in rows] == ["ann"]


def test_select_havings_chain_with_or(grouped: MCP) -> None:
    havings = [
        Where(identifier="total", operator="=", value=5),
        Where(identifier="total", operator="=", value=200, chain="or"),
    ]
    rows = grouped.select("orders", None, ["customer"], havings)

    assert [row["customer"] for row in rows] == ["bob", "cid"]


def test_unknown_having_chain_is_refused(grouped: MCP) -> None:
    havings = [
        Where(identifier="total", operator="=", value=5),
        Where(identifier="total", operator="=", value=200, chain="xor"),
    ]

    with pytest.raises(QueryError, match="unknown chain"):
        grouped.select("orders", None, ["customer"], havings)


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        ("=", "ann", ["ann"]),
        ("!=", "ann", ["bob", "cid"]),
        ("in", ["ann", "cid"], ["ann", "cid"]),
        ("not in", ["ann", "cid"], ["bob"]),
        ("like", "%i%", ["cid"]),
        ("starts with", "b", ["bob"]),
        ("is not null", None, ["ann", "bob", "cid"]),
    ],
)
def test_having_operators(grouped: MCP, operator: str, value: Any, expected: list[str]) -> None:
    havings = [Where(identifier="customer", operator=operator, value=value)]
    rows = grouped.select("orders", None, ["customer"], havings)

    assert [row["customer"] for row in rows] == expected


def test_having_range_operators(grouped: MCP) -> None:
    havings = [Where(identifier="total", operator="between", value=[5, 100])]
    rows = grouped.select("orders", None, ["customer"], havings)

    assert [row["customer"] for row in rows] == ["ann", "bob"]


def test_wheres_and_havings_combine(grouped: MCP) -> None:
    wheres = [Where(identifier="total", operator=">", value=5)]
    havings = [Where(identifier="customer", operator="!=", value="cid")]
    rows = grouped.select("orders", wheres, ["customer"], havings)

    assert [row["customer"] for row in rows] == ["ann"]


def test_unknown_having_operator_is_refused(grouped: MCP) -> None:
    with pytest.raises(QueryError, match="unknown operator"):
        grouped.select("orders", None, ["customer"], [Where(identifier="total", operator="~~", value=1)])


def test_having_in_needs_a_list(grouped: MCP) -> None:
    with pytest.raises(QueryError, match="needs a list value"):
        grouped.select("orders", None, ["customer"], [Where(identifier="customer", operator="in", value="ann")])


def test_group_by_and_havings_over_the_protocol(grouped: MCP) -> None:
    arguments = {
        "table": "orders",
        "group_by": ["customer"],
        "havings": [{"identifier": "total", "operator": ">", "value": 100}],
    }
    _, structured = asyncio.run(grouped.server.call_tool("select", arguments))

    assert [row["customer"] for row in structured["result"]] == ["cid"]


def test_select_wheres_are_chained_with_and(server: MCP) -> None:
    wheres = [
        Where(identifier="age", operator=">=", value=22),
        Where(identifier="name", operator="starts with", value="C"),
    ]

    assert names(server.select("users", wheres)) == ["Cara"]


def test_select_wheres_chain_with_or(server: MCP) -> None:
    wheres = [
        Where(identifier="name", operator="=", value="Alice"),
        Where(identifier="name", operator="=", value="Bob", chain="or"),
    ]

    assert names(server.select("users", wheres)) == ["Alice", "Bob"]


def test_an_or_where_reaches_every_operator(server: MCP) -> None:
    wheres = [
        Where(identifier="age", operator="between", value=[40, 50]),
        Where(identifier="name", operator="in", value=["Cara"], chain="or"),
    ]

    assert names(server.select("users", wheres)) == ["Bob", "Cara"]


def test_wheres_chain_left_to_right_without_grouping(server: MCP) -> None:
    wheres = [
        Where(identifier="name", operator="=", value="Alice"),
        Where(identifier="name", operator="=", value="Bob", chain="or"),
        Where(identifier="age", operator=">", value=50),
    ]

    assert names(server.select("users", wheres)) == ["Alice"]


def test_the_chain_of_the_first_where_is_ignored(server: MCP) -> None:
    wheres = [Where(identifier="name", operator="=", value="Bob", chain="or")]

    assert names(server.select("users", wheres)) == ["Bob"]


@pytest.mark.parametrize("chain", ["and", "AND", "&&", "all", "_and_"])
def test_and_chains_are_spelled_loosely(server: MCP, chain: str) -> None:
    wheres = [
        Where(identifier="age", operator=">=", value=22),
        Where(identifier="name", operator="=", value="Cara", chain=chain),
    ]

    assert names(server.select("users", wheres)) == ["Cara"]


@pytest.mark.parametrize("chain", ["or", "OR", "||", "any"])
def test_or_chains_are_spelled_loosely(server: MCP, chain: str) -> None:
    wheres = [
        Where(identifier="name", operator="=", value="Alice"),
        Where(identifier="name", operator="=", value="Cara", chain=chain),
    ]

    assert names(server.select("users", wheres)) == ["Alice", "Cara"]


def test_unknown_chain_is_refused(server: MCP) -> None:
    with pytest.raises(QueryError, match="unknown chain"):
        server.select("users", [Where(identifier="name", operator="=", value="Bob", chain="xor")])


def test_wheres_chain_over_the_protocol(server: MCP) -> None:
    arguments = {
        "table": "users",
        "wheres": [
            {"identifier": "name", "operator": "=", "value": "Alice"},
            {"identifier": "name", "operator": "=", "value": "Bob", "chain": "or"},
        ],
    }
    _, structured = asyncio.run(server.server.call_tool("select", arguments))

    assert names(structured["result"]) == ["Alice", "Bob"]


def test_update_chains_its_wheres_with_or(server: MCP) -> None:
    wheres = [
        Where(identifier="name", operator="=", value="Alice"),
        Where(identifier="name", operator="=", value="Cara", chain="or"),
    ]

    server.update("users", {"age": 1}, wheres)

    assert [row["age"] for row in server.select("users")] == [1, 41, 1]


def test_delete_chains_its_wheres_with_or(server: MCP) -> None:
    wheres = [
        Where(identifier="name", operator="=", value="Alice"),
        Where(identifier="name", operator="=", value="Cara", chain="or"),
    ]

    server.delete("users", wheres)

    assert names(server.select("users")) == ["Bob"]


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        ("=", "Bob", ["Bob"]),
        ("!=", "Bob", ["Alice", "Cara"]),
        ("<>", "Bob", ["Alice", "Cara"]),
        ("in", ["Alice", "Cara"], ["Alice", "Cara"]),
        ("not in", ["Alice", "Cara"], ["Bob"]),
        ("like", "%o%", ["Bob"]),
        ("not like", "%o%", ["Alice", "Cara"]),
        ("contains", "ar", ["Cara"]),
        ("starts with", "A", ["Alice"]),
        ("ends with", "b", ["Bob"]),
        ("glob", "*ob", ["Bob"]),
        ("is null", None, []),
        ("is not null", None, ["Alice", "Bob", "Cara"]),
    ],
)
def test_name_operators(server: MCP, operator: str, value: Any, expected: list[str]) -> None:
    rows = server.select("users", [Where(identifier="name", operator=operator, value=value)])

    assert names(rows) == expected


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        ("<", 30, ["Cara"]),
        ("<=", 30, ["Alice", "Cara"]),
        (">", 30, ["Bob"]),
        (">=", 30, ["Alice", "Bob"]),
        ("between", [22, 30], ["Alice", "Cara"]),
        ("not between", [22, 30], ["Bob"]),
    ],
)
def test_age_operators(server: MCP, operator: str, value: Any, expected: list[str]) -> None:
    rows = server.select("users", [Where(identifier="age", operator=operator, value=value)])

    assert names(rows) == expected


def test_operators_are_spelled_loosely(server: MCP) -> None:
    rows = server.select("users", [Where(identifier="name", operator="  NOT_IN ", value=["Bob"])])

    assert names(rows) == ["Alice", "Cara"]


def test_qualified_identifier(server: MCP) -> None:
    rows = server.select("users", [Where(identifier=["users", "name"], operator="=", value="Bob")])

    assert names(rows) == ["Bob"]


def test_unknown_operator_is_refused(server: MCP) -> None:
    with pytest.raises(QueryError, match="unknown operator"):
        server.select("users", [Where(identifier="name", operator="~~", value="Bob")])


def test_in_needs_a_list(server: MCP) -> None:
    with pytest.raises(QueryError, match="needs a list value"):
        server.select("users", [Where(identifier="name", operator="in", value="Bob")])


def test_between_needs_two_bounds(server: MCP) -> None:
    with pytest.raises(QueryError, match=r"needs a \[min, max\] list value"):
        server.select("users", [Where(identifier="age", operator="between", value=[1])])


def test_insert_without_returning(server: MCP) -> None:
    assert server.insert("users", [{"name": "Dan", "age": 55}]) == []
    assert names(server.select("users")) == ["Alice", "Bob", "Cara", "Dan"]


def test_insert_returning_all_columns(server: MCP) -> None:
    rows = server.insert("users", [{"name": "Dan", "age": 55}], [])

    assert rows == [{"id": 4, "name": "Dan", "age": 55, "meta": None}]


def test_insert_returning_named_columns(server: MCP) -> None:
    rows = server.insert("users", [{"name": "Dan", "age": 55}, {"name": "Eve", "age": 19}], ["id", "name"])

    assert rows == [{"id": 4, "name": "Dan"}, {"id": 5, "name": "Eve"}]


def test_insert_needs_values(server: MCP) -> None:
    with pytest.raises(QueryError, match="at least one row"):
        server.insert("users", [])


def test_update(server: MCP) -> None:
    server.update("users", {"age": 31}, [Where(identifier="name", operator="=", value="Alice")])

    rows = server.select("users", [Where(identifier="name", operator="=", value="Alice")])
    assert rows[0]["age"] == 31


def test_update_needs_a_where(server: MCP) -> None:
    with pytest.raises(QueryError, match="update needs at least one where"):
        server.update("users", {"age": 1}, [])


def test_update_needs_values(server: MCP) -> None:
    with pytest.raises(QueryError, match="at least one column"):
        server.update("users", {}, [Where(identifier="name", operator="=", value="Alice")])


def test_delete(server: MCP) -> None:
    server.delete("users", [Where(identifier="age", operator=">", value=25)])

    assert names(server.select("users")) == ["Cara"]


def test_delete_needs_a_where(server: MCP) -> None:
    with pytest.raises(QueryError, match="delete needs at least one where"):
        server.delete("users", [])


def test_commit_transaction(server: MCP) -> None:
    assert server.begin_transaction() == {"in_transaction": True, "savepoints": []}
    server.insert("users", [{"name": "Dan", "age": 55}])
    assert server.commit_transaction() == {"in_transaction": False, "savepoints": []}

    assert names(server.select("users")) == ["Alice", "Bob", "Cara", "Dan"]


def test_rollback_transaction(server: MCP) -> None:
    server.begin_transaction()
    server.insert("users", [{"name": "Dan", "age": 55}])
    assert server.rollback_transaction() == {"in_transaction": False, "savepoints": []}

    assert names(server.select("users")) == ["Alice", "Bob", "Cara"]


def test_transactions_do_not_nest_implicitly(server: MCP) -> None:
    server.begin_transaction()

    with pytest.raises(QueryError, match="already open"):
        server.begin_transaction()


def test_commit_without_a_transaction(server: MCP) -> None:
    with pytest.raises(QueryError, match="no transaction is open"):
        server.commit_transaction()


def test_rollback_without_a_transaction(server: MCP) -> None:
    with pytest.raises(QueryError, match="no transaction is open"):
        server.rollback_transaction()


def test_rollback_savepoint_keeps_the_transaction_open(server: MCP) -> None:
    server.begin_transaction()
    server.insert("users", [{"name": "Dan", "age": 55}])
    assert server.begin_savepoint("sp") == {"in_transaction": True, "savepoints": ["sp"]}
    server.insert("users", [{"name": "Eve", "age": 19}])
    assert server.rollback_savepoint("sp") == {"in_transaction": True, "savepoints": []}

    assert names(server.select("users")) == ["Alice", "Bob", "Cara", "Dan"]

    server.commit_transaction()
    assert names(server.select("users")) == ["Alice", "Bob", "Cara", "Dan"]


def test_commit_savepoint_folds_into_the_transaction(server: MCP) -> None:
    server.begin_transaction()
    server.begin_savepoint("sp")
    server.insert("users", [{"name": "Dan", "age": 55}])
    assert server.commit_savepoint("sp") == {"in_transaction": True, "savepoints": []}
    server.rollback_transaction()

    assert names(server.select("users")) == ["Alice", "Bob", "Cara"]


def test_savepoints_nest(server: MCP) -> None:
    server.begin_transaction()
    server.begin_savepoint("outer")
    server.insert("users", [{"name": "Dan", "age": 55}])
    assert server.begin_savepoint("inner") == {"in_transaction": True, "savepoints": ["outer", "inner"]}
    server.insert("users", [{"name": "Eve", "age": 19}])
    server.rollback_savepoint("inner")
    assert names(server.select("users")) == ["Alice", "Bob", "Cara", "Dan"]

    server.rollback_savepoint("outer")
    assert names(server.select("users")) == ["Alice", "Bob", "Cara"]

    server.commit_transaction()


def test_savepoint_needs_a_transaction(server: MCP) -> None:
    with pytest.raises(QueryError, match="no transaction is open"):
        server.begin_savepoint("sp")


def test_savepoint_names_are_unique(server: MCP) -> None:
    server.begin_transaction()
    server.begin_savepoint("sp")

    with pytest.raises(QueryError, match="already open"):
        server.begin_savepoint("sp")


def test_savepoints_close_innermost_first(server: MCP) -> None:
    server.begin_transaction()
    server.begin_savepoint("outer")
    server.begin_savepoint("inner")

    with pytest.raises(QueryError, match='"inner" is open inside "outer"'):
        server.commit_savepoint("outer")


def test_closing_a_savepoint_that_is_not_open(server: MCP) -> None:
    server.begin_transaction()

    with pytest.raises(QueryError, match="no savepoint is open"):
        server.rollback_savepoint("sp")


def test_committing_a_transaction_releases_its_savepoints(server: MCP) -> None:
    server.begin_transaction()
    server.begin_savepoint("sp")
    server.insert("users", [{"name": "Dan", "age": 55}])
    assert server.commit_transaction() == {"in_transaction": False, "savepoints": []}

    assert names(server.select("users")) == ["Alice", "Bob", "Cara", "Dan"]


def test_json_and_datetime_values_are_json_safe(server: MCP) -> None:
    server.db.create_table("events").auto_increment("id").json("payload").datetime("at").execute()
    server.insert("events", [{"payload": {"key": [1, 2]}, "at": "2026-08-17 10:11:12"}])

    rows = server.select("events")

    assert rows == [{"id": 1, "payload": {"key": [1, 2]}, "at": "2026-08-17T10:11:12"}]


def test_text_in_a_binary_column_stays_readable(server: MCP) -> None:
    server.db.exec("CREATE TABLE blobs (id INTEGER PRIMARY KEY, payload BLOB)")
    server.db.prepared("INSERT INTO blobs (payload) VALUES (?)", [b"readable text"])

    assert server.select("blobs")[0]["payload"] == "readable text"


def test_binary_that_is_not_text_is_base64_encoded(server: MCP) -> None:
    server.db.exec("CREATE TABLE blobs (id INTEGER PRIMARY KEY, payload BLOB)")
    server.db.prepared("INSERT INTO blobs (payload) VALUES (?)", [b"\x00\x01\x02\xff"])

    assert server.select("blobs")[0]["payload"] == "AAEC/w=="
